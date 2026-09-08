"""Regression tests for clean_sigs; only disposable regular files are written.

Run: python3 -m unittest discover -s tests/storage -v
Requires util-linux (blkid, sfdisk, wipefs) and e2fsprogs (mkfs.ext4).
The original clean_sigs branch is extracted without running the full script.
Only device enumeration and UI are mocked; signature probing/wiping is real.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ENV = {**os.environ, 'PATH': os.environ.get('PATH', '') + ':/usr/sbin:/sbin', 'LC_ALL': 'C'}


def run(*args, **kwargs):
    return subprocess.run(args, env=ENV, text=True, capture_output=True, check=True, **kwargs)


class PreservePartitionTables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for tool in ('blkid', 'sfdisk', 'wipefs', 'mkfs.ext4'):
            if not shutil.which(tool, path=ENV['PATH']):
                raise unittest.SkipTest(f'Missing {tool}')
        source = (ROOT / 'scripts/storage/format-disk.sh').read_text()
        start = source.index('    if [[ "$OPERATION_MODE" == "clean_sigs" ]]; then', source.index('main() {'))
        end = source.index('    if [[ "$OPERATION_MODE" == "wipe_data" ]]; then', start)
        cls.branch = source[start:end]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pmx-partition-test-')
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / 'disk.img'
        with self.image.open('wb') as stream:
            stream.truncate(16 * 1024 * 1024)

    def clean(self, extra=''):
        shell = '''
translate() { printf '%s' "$*"; }
msg_info() { :; }
msg_warn() { printf 'WARNING: %s\\n' "$*"; }
msg_error() { printf 'ERROR: %s\\n' "$*"; }
msg_ok() { printf 'OK: %s\\n' "$*"; }
msg_success() { :; }
wait_for_enter_to_main() { :; }
# No real device enumeration. The fixture is the whole-device target.
lsblk() { printf 'fixture\\n'; }
SELECTED_DISK="$1"
OPERATION_MODE=clean_sigs
'''
        shell += extra + '\nmain() {\n' + self.branch + '\n}\nmain\n'
        return subprocess.run(['bash', '--noprofile', '--norc', '-c', shell, 'test', str(self.image)],
                              env=ENV, text=True, capture_output=True, timeout=10)

    def test_gpt_layout_and_bytes_preserved(self):
        self.assert_table_preserved('gpt')

    def test_dos_layout_and_bytes_preserved(self):
        self.assert_table_preserved('dos')

    def test_partition_wipe_preserves_nested_table(self):
        run('sfdisk', str(self.image), input='label: gpt\n,8M,L\n')
        before = self.image.read_bytes()
        # Redirect the partition invocation onto the regular-file fixture.
        # The block-device predicate is the only source condition replaced.
        original = self.branch
        self.branch = self.branch.replace('[[ -b "/dev/$pname" ]]', 'true')
        try:
            result = self.clean('''
lsblk() { printf 'fixture\\nfixturepart\\n'; }
wipefs() {
  local -a args=("$@")
  if [[ "${args[-1]}" == /dev/fixturepart ]]; then
    args[-1]="$SELECTED_DISK"
  fi
  command wipefs "${args[@]}"
}
''')
        finally:
            self.branch = original
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.image.read_bytes(), before, 'Nested partition table changed')

    def test_unpartitioned_ext4_signature_removed(self):
        run('mkfs.ext4', '-q', '-F', str(self.image))
        before = json.loads(run('wipefs', '--json', str(self.image)).stdout)
        self.assertIn('ext4', [s['type'] for s in before['signatures']])
        result = self.clean()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(run('wipefs', '--json', str(self.image)).stdout)['signatures'], [])

    def test_failed_or_empty_type_discovery_does_not_write(self):
        for stub in ('blkid() { return 1; }', 'blkid() { return 0; }'):
            with self.subTest(stub=stub):
                result = self.clean(stub + '\nwipefs() { printf called > "$SELECTED_DISK.calls"; }')
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(Path(str(self.image) + '.calls').exists())
                self.assertNotIn('Partition table preserved.', result.stdout)

    def test_wipe_failure_is_reported(self):
        result = self.clean('wipefs() { return 1; }')
        self.assertIn('Some signatures could not be removed', result.stdout)
        self.assertNotIn('OK:', result.stdout)

    def assert_table_preserved(self, label):
        run('sfdisk', str(self.image), input=f'label: {label}\n,8M,L\n')
        before = self.image.read_bytes()
        layout = json.loads(run('sfdisk', '--json', str(self.image)).stdout)
        result = self.clean()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.image.read_bytes(), before, 'Partition-table bytes changed')
        self.assertEqual(json.loads(run('sfdisk', '--json', str(self.image)).stdout), layout)
        self.assertIn('Partition table preserved.', result.stdout)


if __name__ == '__main__':
    unittest.main()
