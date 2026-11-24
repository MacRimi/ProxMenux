"""Tests for user-configurable Vital Signs sampling intervals."""

import ast
import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from health_fixture_modules import load_health_modules, load_source  # noqa: E402

Times = namedtuple("Times", "user nice system idle iowait irq softirq steal guest guest_nice")


def _load_isolated_thresholds(temp_dir):
    ht = load_source("health_thresholds")
    ht._DB_DIR = temp_dir
    ht._CONFIG_PATH = os.path.join(temp_dir, "health_thresholds.json")
    ht.invalidate_cache()
    return ht


def _load_isolated_vital_signs():
    with mock.patch.dict(sys.modules, {"psutil": types.ModuleType("psutil")}):
        return load_source("vital_signs")


def _extract_flask_function(name, namespace):
    source = (SCRIPTS_DIR / "flask_server.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="flask_server.py")
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])), "flask_server.py", "exec"), namespace)
    return namespace[name]


class TestSamplingIntervals(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sampling-intervals-")
        self.addCleanup(self.temporary.cleanup)
        self.ht = _load_isolated_thresholds(self.temporary.name)
        self.vs = _load_isolated_vital_signs()

    def _specs(self):
        return (
            ("cpu", self.ht.CPU_INTERVAL_SPEC),
            ("temperature", self.ht.TEMPERATURE_INTERVAL_SPEC),
            ("memory", self.ht.MEMORY_INTERVAL_SPEC),
        )

    def test_defaults_and_immutability(self):
        specs = self._specs()
        self.assertEqual(
            (self.vs.CPU_INTERVAL, self.vs.TEMPERATURE_INTERVAL, self.vs.MEMORY_INTERVAL),
            tuple(spec.default for _, spec in specs),
        )
        with self.assertRaises(AttributeError):
            self.ht.CPU_INTERVAL_SPEC.max = 999

        effective = self.ht.load_effective()["sampling_intervals"]
        for name, spec in specs:
            self.assertEqual(self.ht.DEFAULTS["sampling_intervals"][name], spec.to_threshold_meta())
            self.assertEqual(self.ht.get("sampling_intervals", name), float(spec.default))
            self.assertEqual(effective[name]["min"], spec.min)
            self.assertEqual(effective[name]["max"], spec.max)
            self.assertEqual(effective[name]["unit"], "s")
            self.assertFalse(effective[name]["customised"])

    def test_save_validation_and_reset(self):
        specs = self._specs()
        res = self.ht.save({
            "cpu": {"warning": 80},
            "sampling_intervals": {"cpu": 15, "temperature": 45, "memory": 40},
        })
        self.assertTrue(res["sampling_intervals"]["cpu"]["customised"])
        self.ht.invalidate_cache()
        self.assertEqual(self.ht.get("sampling_intervals", "cpu"), 15.0)
        self.assertEqual(self.ht.get("sampling_intervals", "temperature"), 45.0)
        self.assertEqual(self.ht.get("sampling_intervals", "memory"), 40.0)

        invalid = [
            *(({"sampling_intervals": {n: s.min - 1}}) for n, s in specs),
            *(({"sampling_intervals": {n: s.max + 1}}) for n, s in specs),
            {"sampling_intervals": {"cpu": True}},
            {"sampling_intervals": {"cpu": False}},
            {"sampling_intervals": {"cpu": float("nan")}},
            {"sampling_intervals": {"cpu": "fast"}},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(self.ht.ThresholdValidationError):
                    self.ht.save(payload)

        self.ht.reset_section("sampling_intervals")
        self.assertEqual(self.ht.get("sampling_intervals", "cpu"), float(self.ht.CPU_INTERVAL_SPEC.default))
        self.assertEqual(self.ht.get("cpu", "warning"), 80.0)

        self.ht.save({"sampling_intervals": {"cpu": 25}})
        self.ht.reset_all()
        self.assertEqual(self.ht.get("sampling_intervals", "cpu"), float(self.ht.CPU_INTERVAL_SPEC.default))

    def test_vital_signs_refresh_wake_and_clamping(self):
        defaults = tuple(spec.default for _, spec in self._specs())
        self.vs.wake_event.clear()
        self.assertEqual(self.vs.refresh_intervals(self.ht), defaults)
        self.assertFalse(self.vs.wake_event.is_set())

        self.ht.save({"sampling_intervals": {"cpu": 20, "temperature": 45, "memory": 40}})
        self.assertEqual(self.vs.refresh_intervals(self.ht), (20, 45, 40))
        self.assertEqual((self.vs.CPU_INTERVAL, self.vs.TEMPERATURE_INTERVAL, self.vs.MEMORY_INTERVAL), (20, 45, 40))
        self.assertTrue(self.vs.wake_event.is_set())

        self.vs.wake_event.clear()
        self.assertEqual(self.vs.refresh_intervals(self.ht), (20, 45, 40))
        self.assertFalse(self.vs.wake_event.is_set())

        with open(self.ht._CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"sampling_intervals": {"cpu": 0, "temperature": -5, "memory": 9999}}, f)
        self.ht.invalidate_cache()
        expected_clamped = (
            self.ht.CPU_INTERVAL_SPEC.min,
            self.ht.TEMPERATURE_INTERVAL_SPEC.min,
            self.ht.MEMORY_INTERVAL_SPEC.max,
        )
        self.assertEqual(self.vs.refresh_intervals(self.ht), expected_clamped)
        self.assertTrue(self.vs.wake_event.is_set())

    def test_cpu_cache_window_follows_configured_interval(self):
        times = [Times(0, 0, 0, 100, 0, 0, 0, 0, 0, 0), Times(50, 0, 0, 150, 0, 0, 0, 0, 0, 0)]
        clock = [1000.0]
        self.ht.save({"sampling_intervals": {"cpu": 60}})
        self.vs.refresh_intervals(self.ht)

        with mock.patch.object(self.vs, "psutil", types.SimpleNamespace(cpu_times=lambda: times.pop(0))), \
                mock.patch.object(self.vs.time, "monotonic", lambda: clock[0]):
            self.assertIsNone(self.vs.sample_cpu())
            sampled = self.vs.sample_cpu()
            clock[0] += 120.0  # > default 3*5s, within 3*60s
            self.assertEqual(self.vs.cpu(), sampled)
            self.assertEqual(times, [])

    def test_sampler_reschedules_on_interval_changes(self):
        self.ht.save({"sampling_intervals": {n: s.max for n, s in self._specs()}})

        clock, events, sleeps = [1000.0], [], []

        class StopSampler(BaseException):
            pass

        hm_mod = types.ModuleType("health_monitor")
        hm_mod.health_monitor = types.SimpleNamespace(
            _sample_cpu_usage=lambda: events.append(("cpu", clock[0])),
            _sample_cpu_temperature=lambda: events.append(("temp", clock[0])),
            _sample_memory_usage=lambda: events.append(("mem", clock[0])),
        )

        def fake_wait(timeout):
            sleeps.append(timeout)
            if len(sleeps) == 1:
                # Shorten CPU 90s -> 5s while waiting; pending deadline clamps to now + 5s.
                clock[0] += 10.0
                self.ht.save({"sampling_intervals": {"cpu": 5}})
                self.vs.refresh_intervals(self.ht)
                return True
            if len(sleeps) == 2:
                # Advance to clamped CPU deadline, then lengthen CPU 5s -> 60s.
                clock[0] += 5.0
                self.ht.save({"sampling_intervals": {"cpu": 60}})
                self.vs.refresh_intervals(self.ht)
                return True
            raise StopSampler()

        sampler = _extract_flask_function(
            "_vital_signs_sampler",
            {"time": types.SimpleNamespace(sleep=lambda _s: None, monotonic=lambda: clock[0]), "vital_signs": self.vs},
        )
        fake_event = types.SimpleNamespace(clear=lambda: None, set=lambda: None, wait=fake_wait)
        with mock.patch.dict(sys.modules, {"health_monitor": hm_mod}), \
                mock.patch.object(self.vs, "health_thresholds", self.ht), \
                mock.patch.object(self.vs, "wake_event", fake_event), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(StopSampler):
                sampler()

        self.assertEqual(events[0], ("cpu", 1000.0))
        self.assertAlmostEqual(sleeps[0], 7.0)
        self.assertIn(("temp", 1010.0), events)
        self.assertAlmostEqual(sleeps[1], 5.0)
        self.assertIn(("cpu", 1015.0), events)
        temp_max, mem_max = self.ht.TEMPERATURE_INTERVAL_SPEC.max, self.ht.MEMORY_INTERVAL_SPEC.max
        self.assertAlmostEqual(sleeps[2], min(1010.0 + temp_max, 1015.0 + mem_max, 1015.0 + 60) - 1015.0)

    def test_max_intervals_fit_health_monitor_windows(self):
        hm, _, _ = load_health_modules(self.temporary.name)
        monitor = hm.HealthMonitor.__new__(hm.HealthMonitor)
        monitor.cached_results, monitor.last_check_times = {}, {}
        now = hm.time.time()
        cpu_max = self.ht.CPU_INTERVAL_SPEC.max
        temp_max = self.ht.TEMPERATURE_INTERVAL_SPEC.max
        mem_max = self.ht.MEMORY_INTERVAL_SPEC.max

        def worst_ages(window, interval):
            return list(range(interval + 5, window + 1, interval))[::-1]

        monitor.state_history = {
            "cpu_usage": [{"value": 97.0, "time": now - a} for a in worst_ages(monitor.CPU_CRITICAL_DURATION, cpu_max)],
            "cpu_temp_history": [{"value": 86.0, "time": now - a} for a in worst_ages(180, temp_max)],
            "memory_usage": [
                {"mem_percent": 96.0, "swap_percent": 90.0, "available_percent": 5.0, "time": now - a}
                for a in worst_ages(monitor.MEMORY_DURATION, mem_max)
            ],
        }
        mem = types.SimpleNamespace(percent=96.0, available=1 * 1024**3, total=16 * 1024**3)
        swap = types.SimpleNamespace(percent=90.0, used=9 * 1024**3, total=10 * 1024**3)

        with mock.patch.object(hm.vital_signs, "CPU_INTERVAL", cpu_max), \
                mock.patch.object(hm.vital_signs, "TEMPERATURE_INTERVAL", temp_max), \
                mock.patch.object(hm.vital_signs, "MEMORY_INTERVAL", mem_max), \
                mock.patch.object(hm.vital_signs, "cpu", return_value={"value": 97.0}), \
                mock.patch.object(hm.vital_signs, "memory", return_value=(mem, swap)), \
                mock.patch.object(hm, "psutil", types.SimpleNamespace(cpu_count=lambda *a, **k: 4), create=True), \
                mock.patch.object(hm.health_persistence, "record_error"), \
                mock.patch.object(hm.health_persistence, "resolve_error"), \
                mock.patch.object(hm.health_persistence, "is_error_active", return_value=False):
            self.assertEqual(monitor._check_cpu_temperature()["status"], "WARNING")
            self.assertEqual(monitor._check_cpu_with_hysteresis()["status"], "CRITICAL")
            self.assertEqual(monitor._check_memory_comprehensive()["status"], "CRITICAL")

    def test_one_reading_at_max_intervals_is_not_a_sustained_alert(self):
        hm, _, _ = load_health_modules(self.temporary.name)
        monitor = hm.HealthMonitor.__new__(hm.HealthMonitor)
        monitor.cached_results, monitor.last_check_times = {}, {}
        now = hm.time.time()
        cpu_max = self.ht.CPU_INTERVAL_SPEC.max
        temp_max = self.ht.TEMPERATURE_INTERVAL_SPEC.max
        mem_max = self.ht.MEMORY_INTERVAL_SPEC.max
        monitor.state_history = {
            "cpu_usage": [{"value": 97.0, "time": now - 1}],
            "cpu_temp_history": [{"value": 86.0, "time": now - 1}],
            "memory_usage": [{"mem_percent": 96.0, "swap_percent": 90.0, "available_percent": 5.0, "time": now - 1}],
        }
        mem = types.SimpleNamespace(percent=96.0, available=1 * 1024**3, total=16 * 1024**3)
        swap = types.SimpleNamespace(percent=90.0, used=9 * 1024**3, total=10 * 1024**3)

        with mock.patch.object(hm.vital_signs, "CPU_INTERVAL", cpu_max), \
                mock.patch.object(hm.vital_signs, "TEMPERATURE_INTERVAL", temp_max), \
                mock.patch.object(hm.vital_signs, "MEMORY_INTERVAL", mem_max), \
                mock.patch.object(hm.vital_signs, "cpu", return_value={"value": 97.0}), \
                mock.patch.object(hm.vital_signs, "memory", return_value=(mem, swap)), \
                mock.patch.object(hm, "psutil", types.SimpleNamespace(cpu_count=lambda *a, **k: 4), create=True), \
                mock.patch.object(hm.health_persistence, "record_error"), \
                mock.patch.object(hm.health_persistence, "resolve_error"), \
                mock.patch.object(hm.health_persistence, "is_error_active", return_value=False):
            self.assertEqual(monitor._check_cpu_temperature()["status"], "OK")
            self.assertEqual(monitor._check_cpu_with_hysteresis()["status"], "OK")
            self.assertEqual(monitor._check_memory_comprehensive()["status"], "OK")


if __name__ == "__main__":
    unittest.main()
