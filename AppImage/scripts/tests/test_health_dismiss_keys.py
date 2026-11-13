"""Every check the Health Monitor offers to dismiss carries the key its error is saved under."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from health_fixture_modules import load_health_modules  # noqa: E402


def setUpModule():
    global health_monitor, persistence
    temporary = tempfile.TemporaryDirectory(prefix='dismiss-keys-')
    unittest.addModuleCleanup(temporary.cleanup)
    health_monitor, _, _ = load_health_modules(temporary.name)
    persistence = health_monitor.health_persistence


class _Recorder:
    def __init__(self):
        self.recorded = []

    def get_excluded_storage_names(self, check_type='health'):
        return set()

    def record_error(self, **kwargs):
        self.recorded.append(kwargs['error_key'])

    def get_active_errors(self, *args, **kwargs):
        return []

    def clear_error(self, key):
        pass


class StorageDismissKey(unittest.TestCase):
    def check(self, grace):
        recorder = _Recorder()
        storage = SimpleNamespace(
            reload_configuration=lambda: None,
            get_storage_status=lambda: {'unavailable': [{'name': 'pbs-lab', 'type': 'pbs', 'status_detail': 'unknown'}],
                                        'available': [{'name': 'local', 'type': 'dir'}]})
        with mock.patch.object(health_monitor, 'PROXMOX_STORAGE_AVAILABLE', True), \
                mock.patch.object(health_monitor, 'proxmox_storage_monitor', storage, create=True), \
                mock.patch.object(health_monitor, 'health_persistence', recorder), \
                mock.patch.object(health_monitor, '_is_startup_health_grace', return_value=grace):
            result = health_monitor.HealthMonitor._check_proxmox_storage(SimpleNamespace(platform_type='pve'))
        return result['checks']['pbs-lab'], recorder.recorded

    def test_an_unavailable_storage_is_dismissed_under_the_key_it_is_recorded_with(self):
        check, recorded = self.check(grace=False)
        self.assertTrue(check['dismissable'])
        self.assertEqual(check['error_key'], 'storage_unavailable_pbs-lab')
        self.assertEqual(recorded, ['storage_unavailable_pbs-lab'])

    def test_the_startup_entry_carries_the_same_key(self):
        check, _ = self.check(grace=True)
        self.assertEqual(check['error_key'], 'storage_unavailable_pbs-lab')


class MemoryDismissKey(unittest.TestCase):
    def test_ram_and_swap_carry_their_keys_and_dismiss_marks_them(self):
        gib = 1024 ** 3
        fake = SimpleNamespace(
            virtual_memory=lambda: SimpleNamespace(percent=97.0, total=16 * gib, available=gib // 2, used=15 * gib),
            swap_memory=lambda: SimpleNamespace(percent=95.0, total=4 * gib, used=3 * gib, free=gib))
        monitor = health_monitor.HealthMonitor.__new__(health_monitor.HealthMonitor)
        monitor.state_history = {'memory_usage': []}
        monitor.MEMORY_CRITICAL, monitor.MEMORY_WARNING, monitor.MEMORY_DURATION = 95, 85, 60
        for name in ('cached_results', 'last_check_times'):
            setattr(monitor, name, {})
        with mock.patch.object(health_monitor, 'psutil', fake, create=True):
            for _ in range(4):
                result = monitor._check_memory_comprehensive()
        checks = result['checks']
        self.assertEqual(checks['ram_usage']['error_key'], 'memory_ram_usage')
        self.assertEqual(checks['swap_usage']['error_key'], 'memory_swap_usage')
        self.assertEqual(persistence.acknowledge_error('memory_ram_usage')['category'], 'memory')


if __name__ == '__main__':
    unittest.main()
