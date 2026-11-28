"""Unit tests for notification_manager.py and Telegram per-category topic routing."""
from datetime import datetime
import json
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SCRIPTS_DIR.parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_channels  # noqa: E402
from notification_channels import TelegramChannel, create_channel  # noqa: E402
from notification_events import NotificationEvent  # noqa: E402
import notification_manager  # noqa: E402
from notification_manager import NotificationManager, SENSITIVE_PLACEHOLDER  # noqa: E402
from notification_templates import EVENT_GROUPS  # noqa: E402


def _init_test_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS notification_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            channel TEXT NOT NULL,
            title TEXT,
            message TEXT,
            severity TEXT DEFAULT 'INFO',
            sent_at TEXT,
            success INTEGER DEFAULT 1,
            error_message TEXT,
            source TEXT
        );
        CREATE TABLE IF NOT EXISTS notification_last_sent (
            fingerprint TEXT PRIMARY KEY,
            last_sent_ts INTEGER NOT NULL,
            count INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS digest_pending (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT,
            event_type TEXT,
            event_group TEXT,
            severity TEXT,
            ts INTEGER,
            title TEXT,
            body TEXT
        );
        CREATE TABLE IF NOT EXISTS quiet_pending (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT,
            event_type TEXT,
            event_group TEXT,
            severity TEXT,
            ts INTEGER,
            title TEXT,
            body TEXT
        );
    """)
    conn.commit()
    conn.close()


def _parse_multipart_thread_id(raw_body: bytes):
    """Extract message_thread_id from multipart/form-data payload if present."""
    text = raw_body.decode('utf-8', errors='replace')
    match = re.search(
        r'Content-Disposition: form-data; name="message_thread_id"\r\n\r\n([^\r\n]+)',
        text,
    )
    return int(match.group(1)) if match else None


class _NotificationManagerTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / 'health_monitor.db'
        self.key_path = Path(tmp.name) / '.notification_key'
        _init_test_db(self.db_path)

        db_patcher = patch.object(notification_manager, 'DB_PATH', self.db_path)
        key_patcher = patch.object(notification_manager, 'ENCRYPTION_KEY_FILE', self.key_path)
        db_patcher.start()
        key_patcher.start()
        self.addCleanup(db_patcher.stop)
        self.addCleanup(key_patcher.stop)

        self.manager = NotificationManager()
        self.manager._load_config()


class TestNotificationManagerSettings(_NotificationManagerTestBase):
    """Settings persistence, validation, masking, and channel rebuild in NotificationManager."""

    def test_save_and_get_settings_round_trip_for_category_topics(self):
        res = self.manager.save_settings({
            'enabled': 'false',
            'telegram.enabled': 'true',
            'telegram.bot_token': '123456:ABCDEF_TOKEN',
            'telegram.chat_id': '-1001234567890',
            'telegram.topic_id': '10',
            'telegram.topic_id.vm_ct': '101',
            'telegram.topic_id.backup': '202',
            'telegram.topic_id.security': ' 303 ',
        })
        self.assertTrue(res['success'])

        got = self.manager.get_settings()
        self.assertTrue(got['success'])
        cfg = got['config']
        self.assertEqual(cfg['channels']['telegram']['topic_id'], '10')
        self.assertEqual(cfg['channels']['telegram']['bot_token'], SENSITIVE_PLACEHOLDER)

        topics = cfg['channel_overrides']['telegram']['topics']
        for group_key in EVENT_GROUPS:
            if group_key != 'other':
                self.assertIn(group_key, topics)
        self.assertEqual(topics['vm_ct'], '101')
        self.assertEqual(topics['backup'], '202')
        self.assertEqual(topics['security'], '303')
        self.assertEqual(topics['storage'], '')

        # Non-Telegram channels do not expose a `topics` override dictionary
        self.assertNotIn('topics', cfg['channel_overrides']['discord'])
        self.assertNotIn('topics', cfg['channel_overrides']['email'])

        # Rebuilt TelegramChannel holds normalized default + category topics
        tg_channel = self.manager._channels['telegram']
        self.assertIsInstance(tg_channel, TelegramChannel)
        self.assertEqual(tg_channel.topic_id, '10')
        self.assertEqual(
            tg_channel.category_topics,
            {'vm_ct': '101', 'backup': '202', 'security': '303'},
        )

    def test_clearing_category_topic_reverts_to_default_and_preserves_masked_token(self):
        self.manager.save_settings({
            'telegram.enabled': 'true',
            'telegram.bot_token': '123456:SECRET_BOT_TOKEN',
            'telegram.chat_id': '-1001234567890',
            'telegram.topic_id': '10',
            'telegram.topic_id.backup': '202',
        })
        res = self.manager.save_settings({
            'telegram.bot_token': SENSITIVE_PLACEHOLDER,
            'telegram.topic_id.backup': '',
        })
        self.assertTrue(res['success'])
        self.assertEqual(
            self.manager.get_settings()['config']['channel_overrides']['telegram']['topics']['backup'],
            '',
        )
        tg_channel = self.manager._channels['telegram']
        self.assertEqual(tg_channel.bot_token, '123456:SECRET_BOT_TOKEN')
        self.assertEqual(tg_channel.category_topics, {})

    def test_load_config_rehydrates_category_topics_from_database(self):
        self.manager.save_settings({
            'telegram.enabled': 'true',
            'telegram.bot_token': '123456:ABCDEF_TOKEN',
            'telegram.chat_id': '-1001234567890',
            'telegram.topic_id': '15',
            'telegram.topic_id.storage': '505',
        })
        fresh_manager = NotificationManager()
        fresh_manager._load_config()
        self.assertIn('telegram', fresh_manager._channels)
        self.assertEqual(fresh_manager._channels['telegram'].topic_id, '15')
        self.assertEqual(fresh_manager._channels['telegram'].category_topics, {'storage': '505'})

    def test_save_settings_rejects_invalid_topic_ids_and_invalid_categories(self):
        invalid_cases = [
            {'telegram.topic_id': 'abc'},
            {'telegram.topic_id': '0'},
            {'telegram.topic_id': '-42'},
            {'telegram.topic_id.vm_ct': 'not-a-number'},
            {'telegram.topic_id.vm_ct': '0'},
            {'telegram.topic_id.vm_ct': '-1'},
            {'telegram.topic_id.nonexistent_group': '123'},
            {'telegram.topic_id.other': '123'},
        ]
        for payload in invalid_cases:
            with self.subTest(payload=payload):
                res = self.manager.save_settings(payload)
                self.assertFalse(res['success'])
                self.assertIn('Invalid Telegram topic', res.get('error', ''))

    def test_save_settings_mixed_valid_and_invalid_payload_rolls_back_memory_and_db(self):
        self.manager.save_settings({
            'telegram.enabled': 'true',
            'telegram.bot_token': '123456:ABCDEF_TOKEN',
            'telegram.chat_id': '-1001234567890',
            'telegram.events.backup': 'true',
            'telegram.topic_id': '10',
            'telegram.topic_id.backup': '222',
        })
        res = self.manager.save_settings({
            'telegram.events.backup': 'false',
            'telegram.topic_id.backup': 'not-a-number',
        })
        self.assertFalse(res['success'])
        self.assertIn('Invalid Telegram topic', res.get('error', ''))

        # In-memory config must remain unchanged
        self.assertEqual(self.manager._config.get('telegram.events.backup'), 'true')
        self.assertEqual(self.manager._config.get('telegram.topic_id.backup'), '222')
        overrides = self.manager.get_settings()['config']['channel_overrides']['telegram']
        self.assertTrue(overrides['categories']['backup'])
        self.assertEqual(overrides['topics']['backup'], '222')

        # Database must also remain unchanged
        fresh_manager = NotificationManager()
        fresh_manager._load_config()
        self.assertEqual(fresh_manager._config.get('telegram.events.backup'), 'true')
        self.assertEqual(fresh_manager._config.get('telegram.topic_id.backup'), '222')


class TestNotificationManagerCategoryTopicDispatch(_NotificationManagerTestBase):
    """End-to-end dispatch routing across categories, fallbacks, rich cards, and bursts."""

    def setUp(self):
        super().setUp()
        self.requests = []
        self.manager.save_settings({
            'enabled': 'false',
            'ai_enabled': 'false',
            'notification_language': 'en',
            'telegram.enabled': 'true',
            'telegram.bot_token': '123456:ABCDEF_TOKEN',
            'telegram.chat_id': '-100999888777',
            'telegram.topic_id': '10',
            'telegram.rich_format': 'true',
            'telegram.rich_cards': 'false',
            'telegram.topic_id.vm_ct': '111',
            'telegram.topic_id.backup': '222',
            'telegram.topic_id.services': '333',
            'telegram.topic_id.health': '444',
            'telegram.topic_id.system': '555',
        })
        self.manager._enabled = True

        def fake_http(url, body_bytes, headers):
            if '/sendRichMessage' in url:
                self.requests.append({
                    'endpoint': 'sendRichMessage',
                    'thread_id': _parse_multipart_thread_id(body_bytes),
                })
            elif '/sendPhoto' in url:
                payload = json.loads(body_bytes.decode('utf-8'))
                self.requests.append({
                    'endpoint': 'sendPhoto',
                    'thread_id': payload.get('message_thread_id'),
                    'payload': payload,
                })
            else:
                payload = json.loads(body_bytes.decode('utf-8'))
                self.requests.append({
                    'endpoint': 'sendMessage',
                    'thread_id': payload.get('message_thread_id'),
                    'payload': payload,
                })
            return 200, '{"ok": true}'

        self.tg_channel = self.manager._channels['telegram']
        self.tg_channel._http_request = fake_http

    def test_event_pipeline_routes_overridden_categories_and_falls_back_to_default(self):
        with patch.object(self.manager, '_is_backup_running', return_value=False):
            self.manager._dispatch_event(NotificationEvent(
                event_type='vm_start',
                severity='INFO',
                data={'vmid': '100', 'name': 'web-01', 'hostname': 'pve1'},
                source='test',
            ))
            self.manager._dispatch_event(NotificationEvent(
                event_type='backup_complete',
                severity='INFO',
                data={'vmid': '100', 'name': 'web-01', 'hostname': 'pve1'},
                source='test',
            ))
            # `storage` has no category topic override -> falls back to default topic 10
            self.manager._dispatch_event(NotificationEvent(
                event_type='disk_space_low',
                severity='WARNING',
                data={'mount': '/', 'usage': '92', 'available': '8G', 'hostname': 'pve1'},
                source='test',
            ))

        self.assertEqual(
            [r['thread_id'] for r in self.requests],
            [111, 222, 10],
        )
        history = self.manager.get_history(limit=10)['history']
        self.assertEqual(len(history), 3)
        self.assertTrue(all(row['channel'] == 'telegram' and row['success'] for row in history))

    def test_no_default_topic_omits_message_thread_id_when_category_not_overridden(self):
        self.tg_channel.topic_id = ''
        self.manager._dispatch_to_channels(
            'pve1: Storage low', 'Disk usage is 92%', 'WARNING',
            'disk_space_low', {'hostname': 'pve1', '_group': 'storage'}, 'test',
        )
        self.manager._dispatch_to_channels(
            'pve1: VM started', 'VM 100 started', 'INFO',
            'vm_start', {'hostname': 'pve1', '_group': 'vm_ct'}, 'test',
        )
        self.assertEqual(len(self.requests), 2)
        self.assertIsNone(self.requests[0]['thread_id'])
        self.assertNotIn('message_thread_id', self.requests[0]['payload'])
        self.assertEqual(self.requests[1]['thread_id'], 111)

    def test_native_rich_cards_use_resolved_category_topic(self):
        self.manager._config['telegram.rich_cards'] = 'true'
        self.tg_channel.rich_cards = True

        self.manager._dispatch_to_channels(
            'pve1: Backup complete', 'Backup finished OK', 'INFO',
            'backup_complete', {'hostname': 'pve1', '_group': 'backup'}, 'test',
        )
        self.manager._dispatch_to_channels(
            'pve1: Disk alert', 'SMART warning on sda', 'WARNING',
            'smart_test_failed', {'hostname': 'pve1', '_group': 'storage', 'device': 'sda'}, 'test',
        )
        self.assertEqual(
            [(r['endpoint'], r['thread_id']) for r in self.requests],
            [('sendRichMessage', 222), ('sendRichMessage', 10)],
        )

    def test_long_split_messages_preserve_category_topic_across_all_chunks(self):
        long_body = ('Line of diagnostic output for backup job\n' * 150)
        self.manager._dispatch_to_channels(
            'pve1: Backup log', long_body, 'WARNING',
            'backup_fail', {'hostname': 'pve1', '_group': 'backup'}, 'test',
        )
        self.assertGreaterEqual(len(self.requests), 2)
        for req in self.requests:
            self.assertEqual(req['thread_id'], 222)

    def test_hidden_burst_summary_inherits_originating_event_category_topic(self):
        # `burst_generic` has template group `'other'`, while `oom_kill` belongs to `'services'` (topic 333)
        delivered = self.manager._dispatch_to_channels(
            'pve1: Multiple OOM events', '3 OOM kills in 60s', 'CRITICAL',
            'burst_generic',
            {'event_type': 'oom_kill', 'count': 3, 'hostname': 'pve1', '_group': 'other'},
            'aggregator',
        )
        self.assertTrue(delivered)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]['thread_id'], 333)

    def test_error_resolved_respects_originating_alert_switch_and_routes_to_health_topic(self):
        delivered = self.manager._dispatch_to_channels(
            'pve1: Storage recovered', 'Disk usage normal', 'OK',
            'error_resolved',
            {'alert_event_type': 'disk_space_low', 'category': 'storage', 'hostname': 'pve1'},
            'health_monitor',
        )
        self.assertTrue(delivered)
        self.assertEqual(self.requests[-1]['thread_id'], 444)

        # Disabling the originating alert category prevents recovery delivery
        self.manager._config['telegram.events.storage'] = 'false'
        delivered_blocked = self.manager._dispatch_to_channels(
            'pve1: Storage recovered', 'Disk usage normal', 'OK',
            'error_resolved',
            {'alert_event_type': 'disk_space_low', 'category': 'storage', 'hostname': 'pve1'},
            'health_monitor',
        )
        self.assertFalse(delivered_blocked)
        self.assertEqual(len(self.requests), 1)

    def test_disabled_category_switch_blocks_delivery_even_when_category_topic_set(self):
        self.manager._config['telegram.events.backup'] = 'false'
        delivered = self.manager._dispatch_to_channels(
            'pve1: Backup complete', 'Finished', 'INFO',
            'backup_complete', {'hostname': 'pve1', '_group': 'backup'}, 'test',
        )
        self.assertFalse(delivered)
        self.assertEqual(self.requests, [])


class TestNotificationManagerDirectSendAndChannelTest(_NotificationManagerTestBase):
    """Direct API/CLI sends (`send_notification`, `send_raw`) and `test_channel`."""

    def setUp(self):
        super().setUp()
        self.requests = []
        self.manager.save_settings({
            'enabled': 'false',
            'ai_enabled': 'false',
            'notification_language': 'en',
            'telegram.enabled': 'true',
            'telegram.bot_token': '123456:ABCDEF_TOKEN',
            'telegram.chat_id': '-100999888777',
            'telegram.topic_id': '10',
            'telegram.topic_id.vm_ct': '111',
            'telegram.topic_id.storage': '666',
            'telegram.topic_id.system': '777',
        })
        self.manager._enabled = True

        def fake_http(url, body_bytes, headers):
            payload = json.loads(body_bytes.decode('utf-8'))
            self.requests.append({
                'endpoint': 'sendPhoto' if '/sendPhoto' in url else 'sendMessage',
                'thread_id': payload.get('message_thread_id'),
            })
            return 200, '{"ok": true}'

        self.fake_http = fake_http
        self.manager._channels['telegram']._http_request = fake_http

    def test_send_notification_and_send_raw_use_category_topics(self):
        res_storage = self.manager.send_notification(
            'smart_test_failed', 'CRITICAL',
            'pve1: SMART test failed', 'Read error on /dev/sda',
            source='cli',
        )
        self.assertTrue(res_storage['success'])

        res_raw = self.manager.send_raw(
            'pve1: Custom maintenance finished', 'All tasks done',
            severity='INFO', source='cli',
        )
        self.assertTrue(res_raw['success'])

        res_untemplated = self.manager.send_notification(
            'external_hook_event', 'INFO',
            'pve1: Hook complete', 'Done',
            source='api',
        )
        self.assertTrue(res_untemplated['success'])

        # storage -> 666, custom/untemplated -> system -> 777
        self.assertEqual([r['thread_id'] for r in self.requests], [666, 777, 777])

    def test_test_channel_uses_default_topic_for_message_and_photo(self):
        res = self.manager.test_channel('telegram')
        self.assertTrue(res['results']['telegram']['success'])
        self.assertEqual(
            [(r['endpoint'], r['thread_id']) for r in self.requests],
            [('sendMessage', 10), ('sendPhoto', 10)],
        )


class TestNotificationManagerDigestAndQuietHours(_NotificationManagerTestBase):
    """Buffered quiet-hours and daily-digest flushes route to the Default Topic ID."""

    def setUp(self):
        super().setUp()
        self.requests = []
        self.manager.save_settings({
            'enabled': 'false',
            'ai_enabled': 'false',
            'notification_language': 'en',
            'telegram.enabled': 'true',
            'telegram.bot_token': '123456:ABCDEF_TOKEN',
            'telegram.chat_id': '-100999888777',
            'telegram.topic_id': '10',
            'telegram.topic_id.backup': '222',
            'telegram.topic_id.updates': '888',
        })
        self.manager._enabled = True

        def fake_http(url, body_bytes, headers):
            payload = json.loads(body_bytes.decode('utf-8'))
            self.requests.append(payload.get('message_thread_id'))
            return 200, '{"ok": true}'

        self.tg_channel = self.manager._channels['telegram']
        self.tg_channel._http_request = fake_http

    def test_digest_and_quiet_summaries_route_to_default_topic(self):
        conn = sqlite3.connect(self.db_path)
        for table in ('digest_pending', 'quiet_pending'):
            conn.executemany(
                f"INSERT INTO {table} (channel, event_type, event_group, severity, ts, title, body) "
                "VALUES ('telegram', ?, ?, 'INFO', 1700000000, ?, 'body')",
                [
                    ('backup_complete', 'backup', 'pve1: Backup OK'),
                    ('update_summary', 'updates', 'pve1: Updates available'),
                ],
            )
        conn.commit()
        conn.close()

        with patch.object(self.manager, '_save_setting'):
            self.manager._flush_digest_for_channel('telegram', self.tg_channel, datetime(2026, 11, 27, 9, 0))
        self.manager._flush_quiet_for_channel('telegram', self.tg_channel)

        self.assertEqual(self.requests, [10, 10])


class TestNotificationSettingsCatalogKeys(unittest.TestCase):
    """Verify all shipped Monitor locale catalogs parse and define Telegram topic keys."""

    def test_all_locales_have_valid_json_and_telegram_topic_keys(self):
        messages_dir = REPO_DIR / 'AppImage' / 'messages'
        expected_locales = {'en', 'de', 'es', 'fr', 'it', 'pt', 'ru', 'sk', 'sv'}
        found_locales = {p.parent.name for p in messages_dir.glob('*/common.json')}
        self.assertTrue(expected_locales.issubset(found_locales))

        required_keys = (
            'topicId',
            'defaultTopicId',
            'topicHint',
            'defaultTopicHint',
            'topicDefault',
            'topicDefaultWithId',
        )
        for locale in sorted(expected_locales):
            catalog_path = messages_dir / locale / 'common.json'
            with self.subTest(locale=locale):
                data = json.loads(catalog_path.read_text(encoding='utf-8'))
                ui = data['settings']['notifications']['ui']
                for key in required_keys:
                    self.assertIn(key, ui)
                    self.assertTrue(isinstance(ui[key], str) and ui[key].strip())
                self.assertIn('{id}', ui['topicDefaultWithId'])


if __name__ == '__main__':
    unittest.main()
