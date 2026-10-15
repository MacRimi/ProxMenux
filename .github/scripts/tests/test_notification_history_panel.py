"""The notification settings show the delivery history the Monitor records,
the daily digest runs included, and never offer to erase it: Audit & Report
reads the same history to tell whether each channel delivers."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / 'AppImage/components/notification-settings.tsx'
KEYS = ('title', 'description', 'empty', 'loadFailed', 'sent', 'notSent',
        'severityInfo', 'severityWarning', 'severityCritical')


class NotificationHistoryPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text(encoding='utf-8')

    def test_the_panel_opens_and_lists_the_history(self):
        self.assertIn('setShowHistory(open => !open)', self.page)
        self.assertIn('history.map(entry =>', self.page)
        self.assertIn('t("settings.notifications.history.title")', self.page)

    def test_the_history_is_read_without_a_success_flag(self):
        loader = re.search(r'const loadHistory = useCallback\(async \(\) => \{(.*?)\n  \}, \[\]\)', self.page, re.S)
        self.assertIsNotNone(loader)
        self.assertIn('Array.isArray(data.history)', loader.group(1))
        self.assertNotIn('data.success', loader.group(1))

    def test_a_digest_run_and_a_failed_delivery_show_their_message(self):
        self.assertIn('entry.event_type === "digest" ? entry.message', self.page)
        self.assertIn('!sent ? entry.error_message', self.page)

    def test_the_page_never_erases_the_history(self):
        self.assertNotIn('handleClearHistory', self.page)
        self.assertIsNone(re.search(r'notifications/history["\'`][^)]*method:\s*["\']DELETE', self.page))

    def test_the_texts_exist_in_english_and_spanish(self):
        for language in ('en', 'es'):
            catalog = json.loads((ROOT / f'AppImage/messages/{language}/common.json').read_text(encoding='utf-8'))
            history = catalog['settings']['notifications']['history']
            for key in KEYS:
                with self.subTest(language=language, key=key):
                    self.assertTrue(history.get(key))


if __name__ == '__main__':
    unittest.main()
