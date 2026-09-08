"""Fixture-only pending staging tests; never source/run complete host scripts.

Only extracted preparation runs. Commands are allowlisted, filesystem arguments
must stay below TemporaryDirectory, and service/UI/rollback calls are mocked.
ln/readlink model pointers with regular files: no symlinks or devices are created.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'scripts/backup_restore/backup_host.sh'

DISPATCH = r'''
import os, pathlib, shutil, subprocess, sys, tempfile
root = pathlib.Path(os.environ['FIXTURE'])
cmd, *args = sys.argv[1:]
mode = os.environ.get('FAIL', '')
def checked(s):
    p = pathlib.Path(s)
    if not p.is_absolute() or not p.resolve().is_relative_to(root):
        raise RuntimeError('out-of-fixture path: ' + s)
    return p
paths = [checked(a) for a in args if a.startswith('/')]
with (root / 'commands').open('a') as f:
    f.write(cmd + ' ' + ' '.join(args) + '\n')
if cmd == 'date':
    print('20260907_120000' if args[0].startswith('+') else '2026-09-07T12:00:00+02:00')
elif cmd in ('dirname', 'basename'):
    print(str(pathlib.Path(args[0]).parent) if cmd == 'dirname' else pathlib.Path(args[0]).name)
elif cmd == 'mktemp':
    template = paths[-1]
    print(tempfile.mkdtemp(prefix=template.name.replace('XXXXXX', ''), dir=template.parent))
elif cmd == 'ln':
    if mode == 'link': sys.exit(1)
    paths[-1].write_text(str(paths[-2]))
elif cmd == 'readlink':
    print(paths[-1].read_text())
elif cmd == 'rsync':
    if mode == 'directory':
        (paths[-1] / 'partial').write_text('incomplete')
        sys.exit(11)
    sys.exit(subprocess.call(['/usr/bin/rsync', *args]))
elif cmd == 'cp':
    if mode == 'file' and '/rootfs/' in str(paths[0]):
        paths[-1].write_text('incomplete')
        sys.exit(1)
    if mode == 'metadata' and '/metadata' in str(paths[0]): sys.exit(1)
    sys.exit(subprocess.call(['/usr/bin/cp', *args]))
elif cmd == 'mv':
    if mode == 'publish': sys.exit(1)
    sys.exit(subprocess.call(['/usr/bin/mv', *args]))
elif cmd == 'cat':
    if mode == 'plan': sys.exit(1)
    sys.stdout.write(sys.stdin.read() if not paths else paths[0].read_text())
elif cmd in ('mkdir', 'rm', 'chmod'):
    if cmd == mode and (cmd == 'chmod' or any('/rootfs' in str(p) for p in paths)): sys.exit(1)
    sys.exit(subprocess.call(['/usr/bin/' + cmd, *args]))
else:
    raise RuntimeError('unexpected command: ' + cmd)
'''


def extract(name):
    match = re.search(r'^' + re.escape(name) + r'\(\) \{\n.*?^\}', SOURCE.read_text(), re.M | re.S)
    if not match:
        raise AssertionError('missing function ' + name)
    return match.group()


class PendingRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pmx-pending-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.put('stage/rootfs/etc/network/interfaces', 'backup network\n')
        self.put('stage/rootfs/etc/hostname', 'backup host\n')
        self.put('stage/metadata/selected_paths.txt', 'etc/network\netc/hostname\n')
        self.put('scripts/backup_restore/apply_pending_restore.sh', '# inert\n').chmod(0o700)
        self.put('scripts/backup_restore/restore/compute_rollback_plan.sh', '# inert\n').chmod(0o700)
        self.put('dispatch.py', DISPATCH)
        (self.root / 'empty-path').mkdir()

    def put(self, path, content):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def run_prepare(self, fail='', paths=('etc/network', 'etc/hostname')):
        code = extract('_rs_prepare_pending_restore')
        literal = 'local pending_base="/var/lib/proxmenux/restore-pending"'
        self.assertEqual(code.count(literal), 1)
        code = code.replace(literal, 'local pending_base="$FIXTURE/pending"')
        wrappers = '\n'.join(f'{c}() {{ /usr/bin/python3 "$FIXTURE/dispatch.py" {c} "$@"; }}'
                             for c in ('mkdir', 'rm', 'cp', 'rsync', 'ln', 'mv', 'mktemp', 'cat', 'chmod', 'date', 'dirname', 'basename', 'readlink'))
        code += '\n' + wrappers + r'''
LOCAL_SCRIPTS="$FIXTURE/scripts"
SCRIPT_DIR="$LOCAL_SCRIPTS/backup_restore"
translate() { printf '%s' "$1"; }
msg_ok() { printf 'OK:%s\n' "$*"; }
msg_warn() { printf 'WARN:%s\n' "$*"; }
msg_error() { printf 'ERROR:%s\n' "$*"; }
HB_ROLLBACK_EXECUTE=1
bash() { [[ "$FAIL" != rollback_plan ]] || return 1; builtin printf '{}\n'; }
jq() { :; }
echo() {
    [[ "$FAIL:$1" != list:etc/network && "$FAIL:$1" != state:pending ]] || return 1
    builtin echo "$@"
}
printf() {
    [[ "$FAIL:${2:-}" != skips:/etc/kernel/foreign ]] || return 1
    builtin printf "$@"
}
_rs_execute_rollback() { builtin printf 'rollback\n' >> "$FIXTURE/rollback"; }
_rs_install_pending_service_unit() {
    printf 'install\n' >> "$FIXTURE/services"
    [[ "$FAIL" != install ]]
}
systemctl() {
    printf '%s\n' "$*" >> "$FIXTURE/services"
    [[ "$FAIL" != "$1" ]]
}
# Conditional invocation deliberately disables inherited errexit: production
# callers use this form, so every I/O failure needs an explicit check.
if _rs_prepare_pending_restore "$FIXTURE/stage" "$@"; then exit 0; else exit 1; fi
'''
        env = {'PATH': str(self.root / 'empty-path'), 'HOME': str(self.root),
               'LC_ALL': 'C', 'FIXTURE': str(self.root), 'FAIL': fail,
               'RS_SKIP_PATHS': '/etc/kernel/foreign'}
        result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', code, 'fixture', *paths],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
        self.assertNotIn('out-of-fixture', result.stderr)
        self.assertNotIn('command not found', result.stderr)
        return result

    def boot_eligible(self):
        # Execute only the real consumer's entry checks, never its apply loop,
        # service installation, host writes, logging setup, or reboot helpers.
        boot = (REPO / 'scripts/backup_restore/apply_pending_restore.sh').read_text()
        gate = boot[boot.index('if [[ ! -e "$CURRENT_LINK" ]]; then'):
                    boot.index('echo "Pending dir:')]
        code = r'''
CURRENT_LINK="$FIXTURE/pending/current"
readlink() { /usr/bin/python3 "$FIXTURE/dispatch.py" readlink "$@"; }
rm() { /usr/bin/python3 "$FIXTURE/dispatch.py" rm "$@"; }
''' + gate + '\nprintf "BOOT_ELIGIBLE\\n"\n'
        result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', code],
                                cwd=self.root, env={'PATH': str(self.root / 'empty-path'),
                                                   'FIXTURE': str(self.root)},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return 'BOOT_ELIGIBLE' in result.stdout

    def assert_failed_unpublished(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('OK:', result.stdout)
        self.assertFalse((self.root / 'pending/current').exists(), 'partial tree is boot-eligible')
        self.assertFalse((self.root / 'services').exists(), 'service touched after staging failure')
        self.assertFalse(self.boot_eligible(), 'consumer accepted failed staging')

    def test_failed_directory_copy_is_not_scheduled(self):
        self.assert_failed_unpublished(self.run_prepare('directory'))

    def test_failed_replacement_preserves_old_pending(self):
        for mode in ('directory', 'file', 'metadata', 'plan'):
            with self.subTest(mode=mode):
                self.setUp()
                first = self.run_prepare()
                self.assertEqual(first.returncode, 0, first.stderr)
                current = self.root / 'pending/current'
                old = Path(current.read_text())
                before = {str(p.relative_to(old)): p.read_bytes() for p in old.rglob('*') if p.is_file()}
                (self.root / 'services').unlink()
                (self.root / 'rollback').unlink()
                result = self.run_prepare(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(current.read_text(), str(old))
                after = {str(p.relative_to(old)): p.read_bytes() for p in old.rglob('*') if p.is_file()}
                self.assertEqual(after, before, 'same-second replacement damaged old pending tree')
                self.assertFalse((self.root / 'services').exists())
                self.assertFalse((self.root / 'rollback').exists())
                self.assertTrue(self.boot_eligible())

    def test_staging_io_failure_is_not_published(self):
        for mode in ('metadata', 'plan', 'mkdir', 'list', 'state', 'skips', 'chmod', 'rollback_plan'):
            with self.subTest(mode=mode):
                self.setUp()
                self.assert_failed_unpublished(self.run_prepare(mode))
                self.assertFalse((self.root / 'rollback').exists())

    def test_publication_failure_preserves_current(self):
        for mode in ('install', 'daemon-reload', 'enable', 'link', 'publish'):
            for existing in (False, True):
                with self.subTest(mode=mode, existing=existing):
                    self.setUp()
                    current = self.root / 'pending/current'
                    old = None
                    if existing:
                        self.assertEqual(self.run_prepare().returncode, 0)
                        old = current.read_text()
                        (self.root / 'rollback').unlink()
                    result = self.run_prepare(mode)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertNotIn('OK:', result.stdout)
                    self.assertEqual(current.read_text() if current.exists() else None, old)
                    self.assertFalse((self.root / 'rollback').exists())

    def test_missing_selected_source_aborts_whole_stage(self):
        self.assert_failed_unpublished(self.run_prepare(paths=('etc/network', 'etc/missing')))

    def test_success_publishes_complete_restore(self):
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OK:', result.stdout)
        pending = Path((self.root / 'pending/current').read_text())
        self.assertEqual((pending / 'rootfs/etc/network/interfaces').read_text(), 'backup network\n')
        self.assertEqual((pending / 'rootfs/etc/hostname').read_text(), 'backup host\n')
        self.assertEqual((pending / 'apply-on-boot.list').read_text(), 'etc/network\netc/hostname\n')
        self.assertEqual((pending / 'state').read_text(), 'pending\n')
        self.assertEqual((pending / 'rs-skip-paths.txt').read_text(), '/etc/kernel/foreign\n')
        self.assertIn(f'RESTORE_ID={pending.name}\n', (pending / 'plan.env').read_text())
        self.assertEqual((pending / 'metadata/selected_paths.txt').read_bytes(),
                         (self.root / 'stage/metadata/selected_paths.txt').read_bytes())
        self.assertEqual((self.root / 'services').read_text(), 'install\ndaemon-reload\nenable proxmenux-restore-onboot.service\n')
        self.assertTrue((self.root / 'rollback').exists())
        self.assertTrue(self.boot_eligible())

    def test_failed_file_copy_is_not_scheduled(self):
        self.assert_failed_unpublished(self.run_prepare('file'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
