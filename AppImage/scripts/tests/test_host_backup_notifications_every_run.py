"""Every run of a host backup is reported, the way a VM or CT backup is: a
nightly job is not the same event as the night before, and its result is not
kept for the daily digest."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import notification_manager  # noqa: E402
from notification_events import NotificationEvent  # noqa: E402

BACKUP_EVENTS = ('backup_start', 'backup_complete', 'backup_fail',
                 'host_backup_start', 'host_backup_complete', 'host_backup_fail')


class HostBackupEveryRunTests(unittest.TestCase):
    def setUp(self):
        self.manager = notification_manager.NotificationManager.__new__(notification_manager.NotificationManager)
        self.manager._config = {'email.digest_enabled': 'true'}

    def event(self, event_type, severity='INFO'):
        return NotificationEvent(event_type, severity, {'hostname': 'pve'}, source='test', entity='node', entity_id='')

    def test_two_runs_a_day_apart_or_closer_are_both_sent(self):
        for event_type in BACKUP_EVENTS:
            with self.subTest(event_type=event_type):
                severity = 'CRITICAL' if event_type.endswith('_fail') else 'INFO'
                self.assertEqual(self.manager._cooldown_seconds(self.event(event_type, severity)), 10)

    def test_the_result_is_not_kept_for_the_daily_digest(self):
        for event_type in BACKUP_EVENTS:
            with self.subTest(event_type=event_type):
                self.assertFalse(self.manager._should_buffer_for_digest('email', 'INFO', event_type))

    def test_a_cooldown_set_by_the_user_is_still_respected(self):
        self.manager._config['cooldown.host_backup_complete'] = '3600'
        self.assertEqual(self.manager._cooldown_seconds(self.event('host_backup_complete')), 3600)

    def test_other_informational_events_still_go_to_the_digest(self):
        self.assertTrue(self.manager._should_buffer_for_digest('email', 'INFO', 'update_summary'))


if __name__ == '__main__':
    unittest.main()
