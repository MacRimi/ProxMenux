"""A service reloading or restarting is working; a failed one is still reported."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
TESTS_DIR = str(Path(__file__).resolve().parent)
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

from health_fixture_modules import load_health_modules


class ServiceStates(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.module, _, _ = load_health_modules(folder.name)
        self.monitor = self.module.HealthMonitor.__new__(self.module.HealthMonitor)
        self.persistence = self.module.health_persistence

    def check(self, states, updating=False):
        """`states` gives each service its answers to is-active, one per call."""
        answers = {service: list(values) for service, values in states.items()}

        def is_active(command, **_kwargs):
            pending = answers.get(command[-1], ['active'])
            return SimpleNamespace(stdout=(pending.pop(0) if len(pending) > 1 else pending[0]) + '\n')

        with patch.object(self.module.subprocess, 'run', side_effect=is_active), \
                patch.object(self.module.time, 'sleep'), \
                patch.object(self.monitor, '_package_update_running', return_value=updating):
            return self.monitor._check_pve_services()

    def active(self, service):
        return self.persistence.is_error_active(f'pve_service_{service}')

    def test_a_service_reloading_is_not_a_failure(self):
        result = self.check({'pveproxy': ['reloading']})
        self.assertEqual(result['status'], 'OK')
        self.assertFalse(self.active('pveproxy'))

    def test_a_restart_that_ends_is_not_a_failure(self):
        result = self.check({'pveproxy': ['deactivating', 'activating', 'active']})
        self.assertEqual(result['status'], 'OK')
        self.assertFalse(self.active('pveproxy'))

    def test_a_service_that_never_finishes_starting_is_reported(self):
        with patch.object(self.module.HealthMonitor, 'SERVICE_SETTLE_SECONDS', 0):
            result = self.check({'pveproxy': ['activating']})
        self.assertEqual(result['status'], 'CRITICAL')
        self.assertTrue(self.active('pveproxy'))

    def test_a_failed_service_is_reported_at_once(self):
        for state in ('failed', 'inactive'):
            with self.subTest(state=state):
                result = self.check({'pvedaemon': [state]})
                self.assertEqual(result['status'], 'CRITICAL')
                self.assertEqual(result['failed'], ['pvedaemon'])

    def test_a_package_update_stops_nothing_being_reported(self):
        result = self.check({'pveproxy': ['inactive']}, updating=True)
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['checks']['pveproxy']['detail'], 'Service is inactive')
        self.assertFalse(self.active('pveproxy'))

    def test_a_package_update_does_not_clear_a_real_failure(self):
        self.check({'pveproxy': ['failed']})
        self.check({'pveproxy': ['inactive']}, updating=True)
        self.assertTrue(self.active('pveproxy'))

    def test_the_failure_shows_once_the_update_has_finished(self):
        self.check({'pveproxy': ['inactive']}, updating=True)
        result = self.check({'pveproxy': ['inactive']})
        self.assertEqual(result['status'], 'CRITICAL')


if __name__ == '__main__':
    unittest.main()
