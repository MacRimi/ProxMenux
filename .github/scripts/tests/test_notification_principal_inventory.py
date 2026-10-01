"""Principal diagnostics must not be deduplicated against inventory substrings."""
import unittest
from notification_fixture import receive, LANGUAGES
from notification_final_fixture import deliver


def noisy_report(name='ordinary-web', storage='PBS', filename='null', cause='denied'):
    # Frozen native Perl notifier/log-reader shape; fixed-column table is
    # source-modeled from the official plaintext renderer, not a live PVE run.
    return ('\nDetails\n=======\nVMID    Name    Status    Time     Size    Filename\n'
        f'100     {name}     err       1m 1s    0 B     {filename}\n\n'
        'Total running time: 1m 1s\nTotal size: 0 B\n\nLogs\n====\n'
        f'vzdump --all 1 --storage {storage} --mode snapshot\n\n' +
        '\n'.join(f'100: 2026-09-29 17:00:00 ERROR: earlier diagnostic {i}' for i in range(12)) +
        f'\n100: 2026-09-29 17:00:00 ERROR: {cause}\n\n')


class PrincipalInventoryTests(unittest.TestCase):
    def assert_principal(self, raw, cause):
        event = receive(raw, 'error', 'vzdump backup status (raw-host): backup failed: ' + cause)
        for language in LANGUAGES:
            for manual in (False, True):
                with self.subTest(language=language, manual=manual):
                    result = deliver(event.event_type, {**event.data, 'hostname':'alias {rack.location}'},
                        event.severity, language, manual=manual)
                    exact = [line for line in result['body'].splitlines()
                        if line.strip() == cause or line.rstrip().endswith('ERROR: ' + cause)]
                    self.assertEqual(len(exact), 1)
                    diagnostics = [line for line in result['body'].splitlines() if 'ERROR:' in line]
                    self.assertLessEqual(len(diagnostics), 8)
                    self.assertLessEqual(len('\n'.join(diagnostics)), 1024)
                    self.assertTrue(all(len(line) <= 512 for line in diagnostics))
                    self.assertEqual(result['data']['pve_message'], raw)
                    self.assertNotIn('raw-host', result['text'])
                    self.assertIn('alias {rack.location}', result['text'])
                    self.assertEqual(result['text'].count('ERROR: ' + cause), 1)

    def test_late_principal_survives_incidental_guest_storage_and_archive(self):
        for name, storage, filename in (('ordinary-web','PBS','null'), ('denied','PBS','null'),
                ('ordinary-web','denied','null'), ('ordinary-web','PBS','denied.tar')):
            with self.subTest(name=name, storage=storage, filename=filename):
                self.assert_principal(noisy_report(name,storage,filename), 'denied')

    def test_raw_principal_braces_and_markup_survive_once(self):
        cause = 'denied {rack.location} <native>'
        self.assert_principal(noisy_report('denied', cause=cause), cause)


if __name__ == '__main__':
    unittest.main()
