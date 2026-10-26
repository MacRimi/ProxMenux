"""A host backup and a finished restore tell the Monitor on its own port,
over HTTPS once the Monitor has a certificate."""
from pathlib import Path
import subprocess
import tempfile
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
LIBRARY = ROOT / 'scripts/backup_restore/lib_host_backup_common.sh'
POSTBOOT = ROOT / 'scripts/backup_restore/apply_cluster_postboot.sh'
SETTING = '/etc/proxmenux/ssl_config.json'


def function(text, name):
    start = text.index(name + '() {')
    return text[start:text.index('\n}\n', start) + 3]


class BackupNotifyHttps(TestCase):
    def address(self, setting):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ssl_config.json'
            if setting is not None:
                path.write_text(setting)
            body = function(LIBRARY.read_text(), 'hb_notify_lifecycle').replace(SETTING, str(path))
            # The function silences curl, so the stub writes the address it was given.
            called = Path(folder) / 'called'
            script = (f'curl() {{ printf "%s" "${{@: -1}}" > {called}; }}\n' + body
                      + 'HB_NOTIFY_JOB_ID=job1 hb_notify_lifecycle complete\n')
            result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', script],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return called.read_text()

    def test_plain_http_while_the_monitor_has_no_certificate(self):
        expected = 'http://127.0.0.1:8008/api/notifications/webhook'
        self.assertEqual(self.address(None), expected)
        self.assertEqual(self.address('{"enabled": false}'), expected)

    def test_https_once_the_monitor_has_a_certificate(self):
        self.assertEqual(self.address('{"enabled": true, "source": "proxmox"}'),
                         'https://127.0.0.1:8008/api/notifications/webhook')

    def test_the_finished_restore_follows_the_same_setting(self):
        source = POSTBOOT.read_text()
        self.assertIn('"${NOTIFY_SCHEME}://127.0.0.1:8008/api/internal/restore-event"', source)
        self.assertNotIn('"http://127.0.0.1:8008/api/internal/restore-event"', source)
        check = source[source.index('NOTIFY_SCHEME="http"'):source.index('NOTIFY_HTTP=$(curl')]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ssl_config.json'
            for setting, expected in (('{"enabled": true}', 'https'), ('{"enabled":false}', 'http'), (None, 'http')):
                path.unlink(missing_ok=True)
                if setting is not None:
                    path.write_text(setting)
                result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                                         check.replace(SETTING, str(path)) + '\necho "$NOTIFY_SCHEME"'],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.stdout.strip(), expected, setting)
