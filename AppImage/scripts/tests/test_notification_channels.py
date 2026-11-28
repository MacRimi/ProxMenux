"""Unit tests for notification_channels.py (TelegramChannel topic routing & delivery)."""
import json
import re
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from notification_channels import TelegramChannel, create_channel  # noqa: E402


def _parse_multipart_fields(raw_body: bytes) -> dict:
    """Extract simple text fields from TelegramChannel multipart/form-data body."""
    text = raw_body.decode('utf-8', errors='replace')
    fields = {}
    for match in re.finditer(
        r'Content-Disposition: form-data; name="([^"]+)"\r\n\r\n(.*?)\r\n(?=--)',
        text,
        re.DOTALL,
    ):
        fields[match.group(1)] = match.group(2)
    return fields


class TelegramChannelTopicTests(unittest.TestCase):
    BOT_TOKEN = '123456789:ABCdefGHIjklMNOpqrsTUVwxyz'
    CHAT_ID = '-1001234567890'

    def make_channel(self, **kwargs) -> TelegramChannel:
        channel = TelegramChannel(
            bot_token=kwargs.pop('bot_token', self.BOT_TOKEN),
            chat_id=kwargs.pop('chat_id', self.CHAT_ID),
            **kwargs,
        )
        channel.MAX_RETRIES = 1
        return channel

    def test_create_channel_normalizes_credentials_and_category_topics(self):
        channel = create_channel('telegram', {
            'bot_token': f'bot{self.BOT_TOKEN}',
            'chat_id': f'  {self.CHAT_ID}  ',
            'topic_id': ' 99 ',
            'rich_format': 'true',
            'rich_cards': 'true',
            'category_topics': {
                'vm_ct': ' 101 ',
                'backup': 202,
                'storage': '   ',
                'network': None,
                '': '303',
            },
        })
        self.assertIsInstance(channel, TelegramChannel)
        self.assertEqual(channel.bot_token, self.BOT_TOKEN)
        self.assertEqual(channel.chat_id, self.CHAT_ID)
        self.assertEqual(channel.topic_id, '99')
        self.assertTrue(channel.rich_format)
        self.assertTrue(channel.rich_cards)
        self.assertEqual(channel.category_topics, {'vm_ct': '101', 'backup': '202'})

    def test_resolve_topic_id_priority_and_fallbacks(self):
        channel = self.make_channel(
            topic_id='50',
            category_topics={'vm_ct': '101', 'backup': '202'},
        )
        # 1. Explicit _topic_id wins over category and default
        self.assertEqual(
            channel._resolve_topic_id({'_topic_id': '999', '_topic_group': 'vm_ct', '_group': 'backup'}),
            '999',
        )
        # Whitespace-only _topic_id is ignored and falls through to category
        self.assertEqual(
            channel._resolve_topic_id({'_topic_id': '   ', '_topic_group': 'vm_ct'}),
            '101',
        )
        # 2. _topic_group wins over _group / group
        self.assertEqual(
            channel._resolve_topic_id({'_topic_group': 'backup', '_group': 'other'}),
            '202',
        )
        # 3. _group and group both resolve category overrides
        self.assertEqual(channel._resolve_topic_id({'_group': 'vm_ct'}), '101')
        self.assertEqual(channel._resolve_topic_id({'group': 'backup'}), '202')
        # 4. Unconfigured category or empty data falls back to default topic_id
        self.assertEqual(channel._resolve_topic_id({'_group': 'storage'}), '50')
        self.assertEqual(channel._resolve_topic_id({}), '50')
        self.assertEqual(channel._resolve_topic_id(None), '50')

    def test_send_standard_message_routes_by_category_default_and_main_chat(self):
        sent_payloads = []
        channel = self.make_channel(
            topic_id='50',
            category_topics={'backup': '202'},
        )

        def fake_http(url, body, headers):
            sent_payloads.append(json.loads(body.decode('utf-8')))
            return 200, '{"ok": true}'

        channel._http_request = fake_http

        # Category override -> 202
        res1 = channel.send('Backup OK', 'Finished', 'INFO', data={'_group': 'backup'})
        # Unconfigured category -> default 50
        res2 = channel.send('Storage alert', 'Disk 90%', 'WARNING', data={'_group': 'storage'})
        # No default topic + unconfigured category -> omitted (main chat)
        channel.topic_id = ''
        res3 = channel.send('Storage alert', 'Disk 90%', 'WARNING', data={'_group': 'storage'})

        self.assertTrue(res1['success'] and res2['success'] and res3['success'])
        self.assertEqual(sent_payloads[0].get('message_thread_id'), 202)
        self.assertEqual(sent_payloads[1].get('message_thread_id'), 50)
        self.assertNotIn('message_thread_id', sent_payloads[2])

    def test_post_message_sentinel_supports_default_and_explicit_empty_override(self):
        payloads = []
        channel = self.make_channel(topic_id='50')

        def fake_http(url, body, headers):
            payloads.append(json.loads(body.decode('utf-8')))
            return 200, '{"ok": true}'

        channel._http_request = fake_http
        # Omit topic_id -> uses self.topic_id (50)
        channel._post_message('Hello default')
        # Explicit empty string -> suppresses self.topic_id
        channel._post_message('Hello main chat', topic_id='')
        # Explicit override -> uses 303
        channel._post_message('Hello override', topic_id='303')

        self.assertEqual(payloads[0].get('message_thread_id'), 50)
        self.assertNotIn('message_thread_id', payloads[1])
        self.assertEqual(payloads[2].get('message_thread_id'), 303)

    def test_split_long_messages_include_category_topic_on_every_chunk(self):
        payloads = []
        channel = self.make_channel(
            topic_id='50',
            category_topics={'security': '404'},
        )

        def fake_http(url, body, headers):
            payloads.append(json.loads(body.decode('utf-8')))
            return 200, '{"ok": true}'

        channel._http_request = fake_http
        long_text = ('Failed SSH login from 198.51.100.25\n' * 160)
        res = channel.send('Auth Failures', long_text, 'WARNING', data={'_group': 'security'})

        self.assertTrue(res['success'])
        self.assertGreaterEqual(len(payloads), 2)
        for payload in payloads:
            self.assertEqual(payload.get('message_thread_id'), 404)

    def test_rich_cards_send_and_fallback_preserve_category_topic(self):
        calls = []
        channel = self.make_channel(
            topic_id='50',
            rich_cards=True,
            category_topics={'backup': '202', 'storage': '303'},
        )

        # Case 1: Rich card succeeds -> multipart form contains message_thread_id=202
        def fake_http_rich_ok(url, body, headers):
            calls.append(('rich', _parse_multipart_fields(body)))
            return 200, '{"ok": true}'

        channel._http_request = fake_http_rich_ok
        res_ok = channel.send('Backup OK', 'All guests backed up', 'INFO', data={'_group': 'backup'})
        self.assertTrue(res_ok['success'])
        self.assertEqual(calls[-1][0], 'rich')
        self.assertEqual(calls[-1][1].get('message_thread_id'), '202')

        # Case 2: Rich card fails (HTTP 400) -> fallback sendMessage STILL routes to topic 303
        calls.clear()

        def fake_http_rich_fallback(url, body, headers):
            if '/sendRichMessage' in url:
                calls.append(('rich_fail', _parse_multipart_fields(body).get('message_thread_id')))
                return 400, '{"ok": false, "description": "Bad Request"}'
            payload = json.loads(body.decode('utf-8'))
            calls.append(('fallback_msg', payload.get('message_thread_id')))
            return 200, '{"ok": true}'

        channel._http_request = fake_http_rich_fallback
        res_fb = channel.send('Disk Alert', 'SMART warning', 'WARNING', data={'_group': 'storage'})
        self.assertTrue(res_fb['success'])
        self.assertEqual(calls, [('rich_fail', '303'), ('fallback_msg', 303)])

    def test_send_photo_and_channel_test_use_default_or_explicit_topic(self):
        calls = []
        channel = self.make_channel(
            topic_id='50',
            category_topics={'vm_ct': '101'},
        )

        def fake_http(url, body, headers):
            payload = json.loads(body.decode('utf-8'))
            endpoint = 'sendPhoto' if '/sendPhoto' in url else 'sendMessage'
            calls.append((endpoint, payload.get('message_thread_id')))
            return 200, '{"ok": true}'

        channel._http_request = fake_http
        # channel.test() sends _group='other' -> uses default topic 50
        ok, err = channel.test()
        self.assertTrue(ok)
        self.assertFalse(err)
        # send_photo defaults to self.topic_id, and supports explicit override / empty override
        channel.send_photo('https://proxmenux.com/telegram.png', caption='Logo')
        channel.send_photo('https://proxmenux.com/telegram.png', caption='Custom', topic_id='777')
        channel.send_photo('https://proxmenux.com/telegram.png', caption='Main chat', topic_id='')

        self.assertEqual(calls, [
            ('sendMessage', 50),
            ('sendPhoto', 50),
            ('sendPhoto', 777),
            ('sendPhoto', None),
        ])

    def test_invalid_non_integer_topic_id_is_ignored_gracefully(self):
        payloads = []
        channel = self.make_channel(
            topic_id='not-an-int',
            category_topics={'vm_ct': 'also-invalid'},
        )

        def fake_http(url, body, headers):
            if '/sendRichMessage' in url:
                payloads.append(_parse_multipart_fields(body))
            else:
                payloads.append(json.loads(body.decode('utf-8')))
            return 200, '{"ok": true}'

        channel._http_request = fake_http
        self.assertTrue(channel.send('Title', 'Body', 'INFO', data={'_group': 'vm_ct'})['success'])
        self.assertNotIn('message_thread_id', payloads[-1])

        channel.rich_cards = True
        self.assertTrue(channel.send('Title', 'Body', 'INFO', data={'_group': 'vm_ct'})['success'])
        self.assertNotIn('message_thread_id', payloads[-1])

        self.assertTrue(channel.send_photo('https://proxmenux.com/telegram.png')['success'])
        self.assertNotIn('message_thread_id', payloads[-1])


if __name__ == '__main__':
    unittest.main()
