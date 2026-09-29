import sys
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import health_monitor
import notification_events

NO_POWER_STATUS = ('Sep 27 09:08:50 proxmox smartd[893]: Device: /dev/sdc [SAT], '
                   'no ATA CHECK POWER STATUS support, ignoring -n Directive')
PENDING = ('Sep 27 09:08:50 proxmox smartd[893]: Device: /dev/sdc [SAT], '
           '8 Currently unreadable (pending) sectors')


class SmartdConfigurationNotices(unittest.TestCase):
    def issues(self, *lines):
        monitor = health_monitor.HealthMonitor.__new__(health_monitor.HealthMonitor)
        monitor._get_journalctl_1hour_warnings = lambda: '\n'.join(lines)
        monitor._get_disk_identity = lambda disk: None
        with patch.object(health_monitor.os.path, 'exists', return_value=True):
            return monitor._check_disk_health_from_events()

    def test_configuration_notice_is_not_a_disk_problem(self):
        self.assertEqual(self.issues(NO_POWER_STATUS), {})

    def test_a_real_warning_on_the_same_disk_is_still_reported(self):
        issues = self.issues(NO_POWER_STATUS, PENDING)
        self.assertEqual(list(issues), ['/dev/sdc'])
        self.assertIn('pending', issues['/dev/sdc']['reason'])
        self.assertNotIn('CHECK POWER STATUS', issues['/dev/sdc']['reason'])


class StorageUsageDetail(unittest.TestCase):
    def test_a_full_pbs_storage_reads_its_usage(self):
        # The storage row merges this entry over the availability one, so it
        # must carry its own text or it reads "pbs storage available".
        monitor = health_monitor.HealthMonitor.__new__(health_monitor.HealthMonitor)
        monitor._read_capacity_thresholds = lambda section: (85, 95)
        status = {'available': [{'name': 'PBS-Cloud', 'type': 'pbs', 'total': 1000, 'used': 924}]}
        module = MagicMock()
        module.proxmox_storage_monitor.get_storage_status.return_value = status
        persistence = health_monitor.health_persistence
        with patch.dict(sys.modules, {'proxmox_storage_monitor': module}), \
             patch.object(health_monitor, 'PROXMOX_STORAGE_AVAILABLE', True), \
             patch.object(persistence, 'get_excluded_storage_names', return_value=set()), \
             patch.object(persistence, 'is_error_acknowledged', return_value=False), \
             patch.object(persistence, 'record_error'), \
             patch.object(persistence, 'get_active_errors', return_value=[]):
            result = monitor._check_pve_storage_capacity()
        entry = result['checks']['PBS-Cloud (pbs)']
        self.assertEqual((entry['status'], entry['detail']), ('WARNING', '92.4% used'))

    def test_a_storage_excluded_from_health_is_not_checked(self):
        # Excluded in Health -> Exclusions, it raises nothing and its earlier
        # error is cleared on the next cycle.
        monitor = health_monitor.HealthMonitor.__new__(health_monitor.HealthMonitor)
        monitor._read_capacity_thresholds = lambda section: (85, 95)
        status = {'available': [{'name': 'Pluton', 'type': 'pbs', 'total': 1000, 'used': 860}]}
        module = MagicMock()
        module.proxmox_storage_monitor.get_storage_status.return_value = status
        persistence = health_monitor.health_persistence
        with patch.dict(sys.modules, {'proxmox_storage_monitor': module}), \
             patch.object(health_monitor, 'PROXMOX_STORAGE_AVAILABLE', True), \
             patch.object(persistence, 'get_excluded_storage_names', return_value={'Pluton'}), \
             patch.object(persistence, 'record_error') as record, \
             patch.object(persistence, 'clear_error') as clear, \
             patch.object(persistence, 'get_active_errors',
                          return_value=[{'error_key': 'pve_storage_full_Pluton'}]):
            result = monitor._check_pve_storage_capacity()
        self.assertIsNone(result)
        record.assert_not_called()
        clear.assert_called_once_with('pve_storage_full_Pluton')


class FstrimUnsupportedDevices(unittest.TestCase):
    def run_with(self, journal):
        result = MagicMock(stdout=journal)
        with patch.object(notification_events.subprocess, 'run', return_value=result):
            return notification_events._fstrim_failed_only_unsupported()

    def test_devices_that_cannot_discard(self):
        self.assertTrue(self.run_with(
            'fstrim: /mnt/nas1_con_backup: FITRIM ioctl failed: Remote I/O error\n'
            'fstrim: /mnt/usb2: FITRIM ioctl failed: Operation not supported\n'
            '/: 20 GiB (21474836480 bytes) trimmed on /dev/mapper/pve-root\n'))

    def test_a_real_failure_is_still_reported(self):
        self.assertFalse(self.run_with(
            'fstrim: /mnt/nas1_con_backup: FITRIM ioctl failed: Remote I/O error\n'
            'fstrim: /mnt/data: FITRIM ioctl failed: Input/output error\n'))

    def test_failure_without_fitrim_lines_or_journal_is_reported(self):
        self.assertFalse(self.run_with('fstrim: cannot open /etc/fstab\n'))
        with patch.object(notification_events.subprocess, 'run', side_effect=subprocess.TimeoutExpired('journalctl', 5)):
            self.assertFalse(notification_events._fstrim_failed_only_unsupported())

    def test_the_service_failure_is_not_emitted(self):
        watcher = notification_events.JournalWatcher.__new__(notification_events.JournalWatcher)
        watcher._emit = MagicMock()
        with patch.object(notification_events, 'is_apt_active_on_host', return_value=False), \
             patch.object(notification_events, '_fstrim_failed_only_unsupported', return_value=True):
            watcher._check_service_failure('fstrim.service: Main process exited, code=exited, status=32/n/a',
                                           'init.scope')
        watcher._emit.assert_not_called()
        with patch.object(notification_events, 'is_apt_active_on_host', return_value=False), \
             patch.object(notification_events, '_fstrim_failed_only_unsupported', return_value=False):
            watcher._check_service_failure('fstrim.service: Main process exited, code=exited, status=32/n/a',
                                           'init.scope')
        self.assertEqual(watcher._emit.call_args.args[0], 'service_fail')


if __name__ == '__main__':
    unittest.main()
