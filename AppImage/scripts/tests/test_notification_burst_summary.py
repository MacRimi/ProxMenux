"""A grouped burst names its events and what each one is about."""
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_manager  # noqa: E402
from notification_events import NotificationEvent  # noqa: E402
from notification_templates import render_template  # noqa: E402


def oci_update(app, vmid):
    return NotificationEvent('oci_update_completed', 'INFO', {
        'hostname': 'constructor', 'app_name': app, 'vmid': vmid,
        'containers': f'CT {vmid}', 'reason': ''}, entity='ct', entity_id=vmid)


def backup_start(reason):
    return NotificationEvent('backup_start', 'INFO', {
        'hostname': 'constructor', 'vmid': '101, 102', 'vmname': '',
        'reason': reason, 'storage': 'local'}, entity='backup', entity_id='vzdump_101_102')


class BurstSummaryTests(unittest.TestCase):
    def summary(self, events):
        aggregator = notification_manager.BurstAggregator()
        return aggregator._create_summary(events, notification_manager._DEFAULT_AGGREGATION)

    def test_oci_updates_list_each_application(self):
        summary = self.summary([oci_update('Jellyfin', '105'), oci_update('Sonarr', '106'),
                                oci_update('CT 107', '107')])
        self.assertEqual(summary.data['details'], '  - Sonarr (CT 106)\n  - CT 107')

    def test_backup_start_lists_its_guests_not_the_heading(self):
        reason = 'VM/CT:\n  CT web (101)\n  VM db (102)\n\U0001F5C4️ Storage: local'
        summary = self.summary([backup_start(reason), backup_start(reason)])
        self.assertEqual(summary.data['details'],
                         '  - CT web (101) · VM db (102) · \U0001F5C4️ Storage: local')

    def test_an_empty_reason_falls_back_to_the_guest(self):
        summary = self.summary([backup_start(''), backup_start('')])
        self.assertEqual(summary.data['details'], '  - 101, 102')

    def test_title_names_the_events_in_the_users_language(self):
        summary = self.summary([oci_update('Jellyfin', '105'), oci_update('Sonarr', '106')])
        for language, label in (('en', 'OCI application updated'), ('es', 'Aplicación OCI actualizada')):
            rendered = render_template('burst_generic', summary.data, language)
            self.assertIn(label, rendered['title'])
            self.assertNotIn('oci_update_completed', rendered['title'] + rendered['body'])
            self.assertIn('Sonarr (CT 106)', rendered['body'])


if __name__ == '__main__':
    unittest.main()
