"""Review regressions at actual consumer seams; no operational imports."""
import unittest
from notification_fixture import receive, LANGUAGES
from notification_final_fixture import deliver

class ReviewCorrectionTests(unittest.TestCase):
    def test_subject_equivalent_late_error_is_reserved_before_cap(self):
        cause = 'job-end hook denied'
        # Frozen native Perl notifier/log-reader output; Rust table source-modeled.
        raw = '\nDetails\n=======\nVMID    Name    Status    Time     Size    Filename    \n100     web     err       1m 1s    0 B     null        \n\nTotal running time: 1m 1s\nTotal size: 0 B\n\nLogs\n====\nvzdump --all 1 --storage PBS --mode snapshot\n\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 0\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 1\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 2\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 3\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 4\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 5\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 6\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 7\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 8\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 9\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 10\n100: 2026-09-29 17:00:00 ERROR: earlier diagnostic 11\n100: 2026-09-29 17:00:00 ERROR: job-end hook denied\n\n\n'
        event = receive(raw, 'error', 'vzdump backup status (raw-host): backup failed: ' + cause)
        for language in LANGUAGES:
            for manual in (False, True):
                with self.subTest(language=language, manual=manual):
                    result = deliver(event.event_type, {**event.data, 'hostname':'alias {rack.location}'}, event.severity, language, manual=manual)
                    self.assertEqual(result['text'].count(cause), 1)
                    self.assertNotIn('raw-host', result['text'])
                    diagnostics = [line for line in result['body'].splitlines() if 'ERROR:' in line]
                    self.assertLessEqual(len(diagnostics), 8)
                    self.assertLessEqual(len('\n'.join(diagnostics)), 1024)
                    self.assertTrue(all(len(line) <= 512 for line in diagnostics))
                    self.assertEqual(result['data']['pve_message'], raw)

if __name__ == '__main__': unittest.main()
