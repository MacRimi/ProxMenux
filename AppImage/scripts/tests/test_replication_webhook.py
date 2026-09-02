import sys
import unittest
from pathlib import Path
from queue import Queue
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_events  # noqa: E402
import notification_templates  # noqa: E402


class ReplicationWebhookTests(unittest.TestCase):
    def _process(self, payload, guest_name='fileserver'):
        watcher = notification_events.ProxmoxHookWatcher(Queue())
        with mock.patch.object(
            watcher,
            '_resolve_replication_guest_name',
            return_value=guest_name,
        ), mock.patch.object(
            notification_events,
            'capture_journal_context',
            return_value='',
        ):
            result = watcher.process_webhook(payload)
        return result, watcher._queue.get_nowait()

    def test_structured_job_id_populates_template_fields(self):
        reason = 'command zfs error: cannot open pool\nremote side unavailable'
        result, event = self._process({
            'title': "Replication Job: '100-0' failed",
            'message': (
                "Replication job '100-0' with target 'pve02' and schedule "
                "'*/15' failed!\n\n"
                "Last successful sync: 2026-09-02 15:00:00\n"
                "Next sync try: 2026-09-02 15:30:00\n"
                "Failure count: 1\n\n"
                f"Error:\n{reason}"
            ),
            'severity': 'error',
            'fields': {
                'type': 'replication',
                'hostname': 'pve01',
                'job-id': '100-0',
            },
        })

        self.assertTrue(result['accepted'])
        self.assertEqual(event.event_type, 'replication_fail')
        self.assertEqual(event.entity_id, '100-0')
        self.assertEqual(event.data['job_id'], '100-0')
        self.assertEqual(event.data['vmid'], '100')
        self.assertEqual(event.data['vmname'], 'fileserver')
        self.assertEqual(event.data['target_node'], 'pve02')
        self.assertEqual(event.data['reason'], reason)

        rendered = notification_templates.render_template(
            event.event_type,
            event.data,
        )
        self.assertIn('fileserver (100)', rendered['title'])
        self.assertIn('ID: 100', rendered['body_text'])
        self.assertIn(reason, rendered['body_text'])

    def test_title_and_message_are_used_when_job_id_field_is_missing(self):
        _, event = self._process({
            'title': "Replication Job: '212-3' failed",
            'message': (
                "Replication job '212-3' with target 'pve03' failed!\n\n"
                "Error: storage 'replica-zfs' is not available"
            ),
            'severity': 'error',
            'fields': {'type': 'replication', 'hostname': 'pve01'},
        }, guest_name='')

        self.assertEqual(event.entity_id, '212-3')
        self.assertEqual(event.data['vmid'], '212')
        self.assertEqual(event.data['vmname'], 'VM/CT')
        self.assertEqual(event.data['target_node'], 'pve03')
        self.assertEqual(
            event.data['reason'],
            "storage 'replica-zfs' is not available",
        )

    def test_missing_error_block_never_renders_an_empty_reason(self):
        message = "Replication job '300-0' failed unexpectedly"
        _, event = self._process({
            'title': "Replication Job: '300-0' failed",
            'message': message,
            'severity': 'error',
            'fields': {'type': 'replication', 'hostname': 'pve01'},
        })

        self.assertEqual(event.data['reason'], message)
        rendered = notification_templates.render_template(
            event.event_type,
            event.data,
        )
        self.assertIn(f'Reason: {message}', rendered['body_text'])


if __name__ == '__main__':
    unittest.main()
