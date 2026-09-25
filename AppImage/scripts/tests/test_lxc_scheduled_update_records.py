import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lxc_apps  # noqa: E402


class ScheduledUpdateRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.apps_dir_patch = mock.patch.object(
            lxc_apps, '_APPS_DIR', self.temp_dir.name,
        )
        self.apps_dir_patch.start()
        self.addCleanup(self.apps_dir_patch.stop)
        self.vmid = 9911
        self.assertTrue(lxc_apps._write_sidecar(self.vmid, {
            'vmid': self.vmid,
            'apps': [],
            'schedule': {'enabled': True, 'cron': '0 3 * * *'},
        }))

    def test_record_keeps_log_and_reboot_evidence(self):
        self.assertTrue(lxc_apps.record_schedule_run(
            self.vmid,
            'success',
            'both',
            log_name='../9911-scheduled-' + ('a' * 32) + '.log',
            reboot_required=True,
            reboot_packages=['linux-image-amd64', 'libc6'],
        ))
        schedule = lxc_apps._read_sidecar(self.vmid)['schedule']
        self.assertEqual(
            schedule['last_run_log'],
            '9911-scheduled-' + ('a' * 32) + '.log',
        )
        self.assertTrue(schedule['last_run_reboot_required'])
        self.assertEqual(
            schedule['last_run_reboot_packages'],
            ['linux-image-amd64', 'libc6'],
        )

    def test_lifecycle_clear_preserves_run_and_log(self):
        lxc_apps.record_schedule_run(
            self.vmid,
            'success',
            'os',
            log_name='9911-scheduled-' + ('b' * 32) + '.log',
            reboot_required=True,
            reboot_packages=['linux-image-amd64'],
        )
        self.assertTrue(lxc_apps.clear_schedule_reboot_required(self.vmid))
        schedule = lxc_apps._read_sidecar(self.vmid)['schedule']
        self.assertFalse(schedule['last_run_reboot_required'])
        self.assertNotIn('last_run_reboot_packages', schedule)
        self.assertEqual(schedule['last_run_status'], 'success')
        self.assertIn('last_run_log', schedule)


if __name__ == '__main__':
    unittest.main()
