"""Execute only the actual pure HEALTH decision; never source the admin script."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'scripts/storage/smart-disk-test.sh'


class NvmeStatusMessage(unittest.TestCase):
    def render(self, health):
        source = SOURCE.read_text()
        start = source.index('          if [[ "$HEALTH" == "0" ]]; then')
        end = source.index('\n          fi', start) + len('\n          fi')
        seam = source[start:end]
        # Only printf-backed display/translation stubs are available to this seam.
        harness = '''translate() { printf '%s' "$1"; }
msg_ok() { printf 'OK:%s\\n' "$1"; }
msg_warn() { printf 'WARN:%s\\n' "$1"; }
HEALTH=$1
'''
        return subprocess.run(['bash', '-c', harness + seam, 'fixture', health],
                              check=True, capture_output=True, text=True).stdout.strip()

    def test_zero_describes_critical_warning_not_self_test(self):
        self.assertEqual(self.render('0'), 'OK:NVMe critical_warning is 0 (no critical warnings reported).')

    def test_nonzero_and_missing_keep_existing_warning_branch(self):
        for health in ['1', '2', '255', '', '0x00']:
            with self.subTest(health=health):
                self.assertEqual(self.render(health), f'WARN:NVMe health status: WARNING (critical_warning = {health})')


if __name__ == '__main__':
    unittest.main()
