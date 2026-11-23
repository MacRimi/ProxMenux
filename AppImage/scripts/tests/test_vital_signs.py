"""The host's vital signs are read once and shared: CPU usage only by the
sampler, memory and temperatures through one cache, and the health checks
evaluate the sampler's readings whatever its interval."""
from collections import namedtuple
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from health_fixture_modules import load_health_modules, load_source  # noqa: E402

# The host's psutil is never used: each test gives the module a fake one.
with mock.patch.dict(sys.modules, {'psutil': ModuleType('psutil')}):
    vital_signs = load_source('vital_signs')

Times = namedtuple('Times', 'user nice system idle iowait irq softirq steal guest guest_nice')
Sensor = namedtuple('Sensor', 'label current high critical')


class FakePsutil:
    def __init__(self):
        self.times = []
        self.memory_reads = 0
        self.sensor_reads = 0
        self.sensors = {}

    def cpu_times(self):
        return self.times.pop(0)

    def cpu_percent(self, *args, **kwargs):
        raise AssertionError('psutil.cpu_percent keeps a baseline of its own')

    def virtual_memory(self):
        self.memory_reads += 1
        return SimpleNamespace(percent=40.0)

    def swap_memory(self):
        return SimpleNamespace(percent=0.0, total=0)

    def sensors_temperatures(self):
        self.sensor_reads += 1
        return self.sensors


class VitalSignsTests(unittest.TestCase):
    def setUp(self):
        self.psutil = FakePsutil()
        self.clock = [1000.0]
        for target, value in (('psutil', self.psutil), ('_readings', {}), ('_cpu_counters', None)):
            patcher = mock.patch.object(vital_signs, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(vital_signs.time, 'monotonic', lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_first_cpu_sample_only_sets_the_baseline(self):
        self.psutil.times.append(Times(10, 0, 10, 80, 0, 0, 0, 0, 0, 0))
        self.assertIsNone(vital_signs.sample_cpu())

    def test_cpu_use_is_the_busy_share_since_the_previous_sample(self):
        self.psutil.times += [Times(10, 0, 10, 80, 0, 0, 0, 0, 0, 0), Times(40, 10, 20, 100, 0, 5, 5, 0, 20, 0)]
        vital_signs.sample_cpu()
        self.assertEqual(vital_signs.sample_cpu(), {'value': 75.0, 'user': 50.0, 'system': 25.0})

    def test_everyone_else_reads_the_sampler_cpu_reading(self):
        self.psutil.times += [Times(0, 0, 0, 100, 0, 0, 0, 0, 0, 0), Times(50, 0, 0, 150, 0, 0, 0, 0, 0, 0)]
        vital_signs.sample_cpu()
        sampled = vital_signs.sample_cpu()
        self.clock[0] += vital_signs.CPU_INTERVAL
        self.assertEqual(vital_signs.cpu(), sampled)
        self.assertEqual(self.psutil.times, [])

    def test_memory_is_read_again_only_when_older_than_asked(self):
        vital_signs.memory(max_age=0)
        self.clock[0] += 3
        vital_signs.memory(max_age=5)
        self.assertEqual(self.psutil.memory_reads, 1)
        self.clock[0] += 3
        vital_signs.memory(max_age=5)
        self.assertEqual(self.psutil.memory_reads, 2)

    def test_the_cpu_sensor_wins_over_the_hottest_one(self):
        self.psutil.sensors = {'nvme': [Sensor('Composite', 61.0, 0, 0)],
                               'coretemp': [Sensor('Package id 0', 48.0, 0, 0)]}
        readings = vital_signs.temperatures()
        self.assertEqual(vital_signs.cpu_temperature(readings), 48.0)
        self.assertEqual(vital_signs.highest_temperature(readings), 61.0)
        vital_signs.cpu_temperature()
        self.assertEqual(self.psutil.sensor_reads, 1)

    def test_a_host_without_sensors(self):
        self.assertEqual(vital_signs.cpu_temperature(), 0)
        self.assertIsNone(vital_signs.highest_temperature())

    def test_readings_needed_to_cover_a_time(self):
        self.assertEqual(vital_signs.samples_for(125, 5), 25)
        self.assertEqual(vital_signs.samples_for(240, 30), 8)
        self.assertEqual(vital_signs.samples_for(165, 15), 11)
        self.assertEqual(vital_signs.samples_for(-120, 300), 1)


class ChecksFollowTheSamplerTests(unittest.TestCase):
    """The checks read only what the sampler recorded, so their result does
    not depend on how often they run nor on its interval."""

    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='vital-signs-')
        cls.addClassCleanup(temporary.cleanup)
        cls.hm, _, _ = load_health_modules(temporary.name)

    def setUp(self):
        health_monitor = self.hm
        self.monitor = health_monitor.HealthMonitor.__new__(health_monitor.HealthMonitor)
        self.monitor.cached_results, self.monitor.last_check_times = {}, {}
        self.now = health_monitor.time.time()
        for target in ('record_error', 'resolve_error'):
            patcher = mock.patch.object(health_monitor.health_persistence, target)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(health_monitor.health_persistence, 'is_error_active', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def history(self, key, value, interval, span, field='value'):
        return [{field: value, 'time': self.now - age} for age in range(span, -1, -interval)]

    def temperature(self, interval, span, value=85.0):
        self.monitor.state_history = {'cpu_temp_history': self.history('cpu_temp_history', value, interval, span)}
        with mock.patch.object(self.hm.vital_signs, 'TEMPERATURE_INTERVAL', interval):
            return self.monitor._check_cpu_temperature()

    def test_three_hot_minutes_raise_the_temperature_warning(self):
        self.assertEqual(self.temperature(15, 180)['status'], 'WARNING')

    def test_two_hot_minutes_do_not(self):
        self.assertEqual(self.temperature(15, 120)['status'], 'OK')

    def test_the_warning_follows_a_longer_interval(self):
        self.assertEqual(self.temperature(60, 180)['status'], 'WARNING')

    def test_no_sensor_reading_means_no_temperature_check(self):
        self.assertIsNone(self.temperature(15, -1))

    def cpu(self, interval, span, value=97.0):
        self.monitor.state_history = {'cpu_usage': self.history('cpu_usage', value, interval, span)}
        with mock.patch.object(self.hm.vital_signs, 'CPU_INTERVAL', interval), \
                mock.patch.object(self.hm.vital_signs, 'cpu', return_value={'value': value}), \
                mock.patch.object(self.hm, 'psutil', SimpleNamespace(cpu_count=lambda *a, **k: 4), create=True), \
                mock.patch.object(self.monitor, '_check_cpu_temperature', return_value=None):
            return self.monitor._check_cpu_with_hysteresis()

    def test_sustained_cpu_raises_the_critical_alert(self):
        self.assertEqual(self.cpu(5, 150)['status'], 'CRITICAL')

    def test_a_short_cpu_burst_does_not(self):
        self.assertEqual(self.cpu(5, 60)['status'], 'OK')

    def test_the_cpu_alert_follows_a_longer_interval(self):
        self.assertEqual(self.cpu(30, 150)['status'], 'CRITICAL')
        self.assertEqual(self.cpu(30, 60)['status'], 'OK')


if __name__ == '__main__':
    unittest.main()
