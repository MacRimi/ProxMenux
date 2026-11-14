"""The HTML email keeps the lines of a digest whole.

A digest or quiet-hours summary has no structured rows, so the email splits
"Label: value" lines into two cells; the time of a bullet line, a clock time
and a URL are not labels."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'AppImage' / 'scripts'


class DigestRows(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(sys.path.remove, str(SCRIPTS))
        spec = importlib.util.spec_from_file_location('digest_channels', SCRIPTS / 'notification_channels.py')
        channels = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(channels)
        self.channel = object.__new__(channels.EmailChannel)
        self.channel.subject_prefix = '[ProxMenux]'

    def cells(self, body):
        message = self.channel._format_html('24-hour summary', body, 'INFO', {})
        return message

    def test_bullet_lines_and_times_stay_in_one_cell(self):
        body = ("Updates: 2\n"
                "• 14:47  2 app updates available\n"
                "• 💾✅ 01:22  Backup completed — PBS_URANO\n"
                "Next run 03:15 tonight\n"
                "Docs: https://proxmenux.com/docs")
        message = self.cells(body)
        self.assertIn('• 14:47  2 app updates available', message)
        self.assertIn('• 💾✅ 01:22  Backup completed — PBS_URANO', message)
        self.assertIn('Next run 03:15 tonight', message)
        self.assertNotIn('>• 14<', message)
        # A real "Label: value" line is still split, also one carrying a URL.
        self.assertIn('>Updates</td>', message)
        self.assertIn('>Docs</td>', message)
        self.assertIn('https://proxmenux.com/docs', message)

    def test_a_bare_time_or_url_is_not_a_label(self):
        message = self.cells("14:47\nhttps://example.invalid/path")
        self.assertNotIn('>14</td>', message)
        self.assertNotIn('>https</td>', message)
        self.assertIn('14:47', message)
        self.assertIn('https://example.invalid/path', message)


if __name__ == '__main__':
    unittest.main()
