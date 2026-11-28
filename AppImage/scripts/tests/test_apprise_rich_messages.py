"""The Rich messages option of the Apprise channel: the event reaches Apprise
with its emojis when the option is on, and as plain text when it is off."""

import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_manager  # noqa: E402
from notification_channels import AppriseChannel  # noqa: E402
from notification_events import NotificationEvent  # noqa: E402
from notification_templates import SEVERITY_ICONS, EVENT_EMOJI, CATEGORY_EMOJI  # noqa: E402


def fake_apprise(sent):
    class Apprise:
        def add(self, url):
            return True

        def notify(self, body, title, notify_type):
            sent.append((title, body))
            return True

    module = types.ModuleType('apprise')
    module.Apprise = Apprise
    module.NotifyType = types.SimpleNamespace(FAILURE='failure', WARNING='warning', SUCCESS='success', INFO='info')
    return module


class AppriseRichMessagesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / 'health_monitor.db'
        conn = sqlite3.connect(str(db_path))
        conn.execute('CREATE TABLE notification_last_sent (fingerprint TEXT PRIMARY KEY, '
                     'last_sent_ts INTEGER NOT NULL, count INTEGER DEFAULT 1)')
        conn.execute('CREATE TABLE notification_history (id INTEGER PRIMARY KEY AUTOINCREMENT, '
                     'event_type TEXT NOT NULL, channel TEXT NOT NULL, title TEXT, message TEXT, '
                     'severity TEXT, sent_at TEXT NOT NULL, success INTEGER DEFAULT 1, '
                     "error_message TEXT, source TEXT DEFAULT 'server')")
        conn.commit()
        conn.close()
        for patcher in (mock.patch.object(notification_manager, 'DB_PATH', db_path),
                        mock.patch.object(notification_manager, 'enrich_context_for_ai', return_value=''),
                        mock.patch.object(notification_manager, '_format_with_ai_bounded', return_value=None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def deliver(self, rich_format):
        sent = []
        manager = notification_manager.NotificationManager()
        manager._enabled = True
        manager._config = {'apprise.enabled': 'true', 'apprise.rich_format': rich_format,
                           'ai_enabled': 'false'}
        manager._channels = {'apprise': AppriseChannel('matrixs://user:pass@example.org/#room')}
        event = NotificationEvent(event_type='lxc_update_applied', severity='INFO', data={
            'hostname': 'pve-test', 'vmid': 210, 'ct_name': 'web', 'target': 'Docker Engine',
            'result': 'succeeded', 'duration': '10s', 'details': 'Update completed'},
            source='manual', entity='ct', entity_id='210:rich')
        with mock.patch.dict(sys.modules, {'apprise': fake_apprise(sent)}):
            manager._dispatch_event(event)
        self.assertEqual(len(sent), 1)
        return sent[0]

    @staticmethod
    def starts_with_icon(text):
        icons = set(SEVERITY_ICONS.values()) | set(EVENT_EMOJI.values()) | set(CATEGORY_EMOJI.values())
        return any(icon and text.startswith(icon) for icon in icons)

    def test_rich_messages_on_sends_the_emojis_to_apprise(self):
        title, _ = self.deliver('true')
        self.assertTrue(self.starts_with_icon(title), title)

    def test_rich_messages_off_sends_plain_text(self):
        title, _ = self.deliver('false')
        self.assertFalse(self.starts_with_icon(title), title)


if __name__ == '__main__':
    unittest.main()
