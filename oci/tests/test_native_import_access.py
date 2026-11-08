"""Native mapped readers may read an image without exposing its private cache."""
import errno
import importlib.util
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_import_access', ROOT / 'remote/oci_native_import.py')
imports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imports)


class PrivateImageImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'private-image.tar'
        self.source.write_bytes(b'OCI image fixture\x00private layers')
        self.source.chmod(0o600)

    def staging(self):
        return patch.object(imports, 'trusted_staging_root', return_value=self.root)

    def test_normal_readable_image_uses_original_storage_volume_without_copy(self):
        with patch.object(imports, 'readable', return_value=True), \
             patch.object(imports, '_copy', side_effect=AssertionError('must stay zero-copy')):
            with imports.import_archive(self.source, 'local:vztmpl/public.tar', 100000, 100000) as path:
                self.assertEqual(path, 'local:vztmpl/public.tar')

    def test_private_copy_preserves_source_and_limits_mapped_reader_group(self):
        before = self.source.stat()
        with self.staging(), patch.object(imports.os, 'chown') as chown, \
             patch.object(imports, 'readable', return_value=False):
            with imports.import_archive(self.source, str(self.source), 100000, 100000) as path:
                staged = Path(path)
                self.assertEqual(staged.read_bytes(), self.source.read_bytes())
                self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o440)
                self.assertEqual(stat.S_IMODE(staged.parent.stat().st_mode), 0o750)
                chown.assert_any_call(staged, 0, 100000)
                chown.assert_any_call(staged.parent, 0, 100000)
            self.assertFalse(staged.parent.exists())
        after = self.source.stat()
        self.assertEqual((before.st_uid, before.st_gid, before.st_mode),
                         (after.st_uid, after.st_gid, after.st_mode))

    def test_copy_error_cleans_stage_and_never_invokes_pct(self):
        with self.staging(), patch.object(imports, 'readable', return_value=False), \
             patch.object(imports, '_copy', side_effect=OSError(errno.ENOSPC, 'fixture')), \
             patch.object(imports.subprocess, 'run') as run:
            with self.assertRaises(OSError):
                imports.create('9161', str(self.source), str(self.source), ['--unprivileged', '1'])
            run.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_pct_failure_and_interrupt_both_clean_stage(self):
        for error in (None, KeyboardInterrupt()):
            with self.staging(), patch.object(imports.os, 'chown'), \
                 patch.object(imports, 'readable', return_value=False), \
                 patch.object(imports.subprocess, 'run', side_effect=error,
                              return_value=types.SimpleNamespace(returncode=23)) as run:
                if error:
                    with self.assertRaises(KeyboardInterrupt):
                        imports.create('9161', str(self.source), str(self.source), ['--unprivileged', '1'])
                else:
                    self.assertEqual(imports.create('9161', str(self.source), str(self.source),
                                                    ['--unprivileged', '1']), 23)
                self.assertEqual(run.call_args.kwargs['umask'], 0o022)
            self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_standard_map_and_privileged_profile_initial_unprivileged_create(self):
        for options in (['--unprivileged', '1'], ['--unprivileged=1'], ['--unprivileged', 'true']):
            self.assertEqual(imports.reader_ids(options), (100000, 100000))
        self.assertEqual(imports.reader_ids(['--unprivileged', '0']), (0, 0))
        installer = (ROOT / 'remote/install_oci.sh').read_text()
        self.assertIn('CREATE_UNPRIVILEGED_FLAG=1', installer)
        self.assertIn('--unprivileged "$CREATE_UNPRIVILEGED_FLAG"', installer)

    def test_derived_numeric_user_image_is_staged_without_mutating_its_source(self):
        derived = self.root / 'image.user-databases.123.tar'
        derived.write_bytes(b'derived OCI image')
        derived.chmod(0o600)
        with self.staging(), patch.object(imports.os, 'chown'), \
             patch.object(imports, 'readable', return_value=False):
            with imports.import_archive(derived, str(derived), 100000, 100000) as path:
                self.assertEqual(Path(path).read_bytes(), derived.read_bytes())
        self.assertEqual(stat.S_IMODE(derived.stat().st_mode), 0o600)

    def test_reflink_unavailable_falls_back_to_an_identical_copy(self):
        target = self.root / 'copy.tar'
        with patch.object(imports.fcntl, 'ioctl', side_effect=OSError(errno.EOPNOTSUPP, 'fixture')):
            imports._copy(self.source, target)
        self.assertEqual(target.read_bytes(), self.source.read_bytes())

    def test_reflink_permission_denied_stages_a_private_copy_without_changing_source(self):
        before = self.source.stat()
        with self.staging(), patch.object(imports.os, 'chown'), \
             patch.object(imports, 'readable', return_value=False), \
             patch.object(imports.fcntl, 'ioctl', side_effect=PermissionError(errno.EPERM, 'fixture')):
            with imports.import_archive(self.source, str(self.source), 100000, 100000) as path:
                staged = Path(path)
                self.assertEqual(staged.read_bytes(), self.source.read_bytes())
                self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o440)
                self.assertEqual(stat.S_IMODE(staged.parent.stat().st_mode), 0o750)
            self.assertFalse(staged.parent.exists())
        after = self.source.stat()
        self.assertEqual((before.st_uid, before.st_gid, before.st_mode),
                         (after.st_uid, after.st_gid, after.st_mode))

    def test_reflink_io_error_is_not_hidden_by_a_fallback_copy(self):
        with self.staging(), patch.object(imports, 'readable', return_value=False), \
             patch.object(imports.fcntl, 'ioctl', side_effect=OSError(errno.EIO, 'fixture')), \
             patch.object(imports.shutil, 'copyfileobj') as copy, \
             patch.object(imports.subprocess, 'run') as run:
            with self.assertRaises(OSError) as raised:
                imports.create('9161', str(self.source), str(self.source), ['--unprivileged', '1'])
            self.assertEqual(raised.exception.errno, errno.EIO)
            copy.assert_not_called()
            run.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_local_and_ssh_installer_stage_the_native_helper(self):
        import ast
        tree = ast.parse((ROOT / 'src/proxmenux_oci/installer.py').read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_run_remote_install')
        lists = [n.iter for n in ast.walk(function) if isinstance(n, ast.For)
                 and isinstance(n.iter, ast.Tuple)
                 and any(isinstance(v, ast.Constant) and v.value == 'oci_ui.sh' for v in n.iter.elts)]
        self.assertEqual(len(lists), 2)
        for values in lists:
            self.assertIn('oci_native_import.py', [v.value for v in values.elts])
        self.assertIn('oci_native_import.py', (ROOT / 'remote/oci_ui.sh').read_text())


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0,
                     'isolated mapped UID/GID proof runs as root in Linux CI')
class MappedReaderProof(unittest.TestCase):
    def reader(self, path, uid, gid):
        return subprocess.run([sys.executable, '-c',
            'import os,sys; os.setgroups([]); os.setgid(int(sys.argv[2])); '
            'os.setuid(int(sys.argv[1])); print(open(sys.argv[3],"rb").read().decode())',
            str(uid), str(gid), str(path)], capture_output=True, text=True)

    def test_mapped_reader_only_private_source_and_caller_state_are_preserved(self):
        with tempfile.TemporaryDirectory(dir='/var/tmp') as folder:
            root = Path(folder)
            root.chmod(0o700)
            source = root / 'private.tar'
            source.write_text('private image contents')
            source.chmod(0o600)
            self.assertNotEqual(self.reader(source, 100000, 100000).returncode, 0)
            previous = os.umask(0o077)
            try:
                with imports.import_archive(source, str(source), 100000, 100000) as staged:
                    path = Path(staged)
                    self.assertEqual(self.reader(path, 100000, 100000).stdout.strip(), 'private image contents')
                    self.assertNotEqual(self.reader(path, 100001, 100001).returncode, 0)
                    self.assertFalse(path.stat().st_mode & 0o022)
                    self.assertEqual(path.stat().st_uid, 0)
                self.assertFalse(path.parent.exists())
                record = root / 'record.json'
                record.write_text('private credentials fixture')
                self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
                self.assertEqual(os.umask(0o077), 0o077)
                self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            finally:
                os.umask(previous)

    def test_sigterm_removes_staging_and_preserves_native_output_and_status(self):
        with tempfile.TemporaryDirectory(dir='/var/tmp') as folder:
            root = Path(folder)
            source = root / 'private.tar'; source.write_text('private image'); source.chmod(0o600)
            pct = root / 'pct'
            pct.write_text('#!/bin/sh\nmkdir "$FIXTURE/pve-tmp"\ntouch "$FIXTURE/pve-tmp/pct.conf"\nprintf "%s\\n" "$3" >"$MARKER"\necho native-output\nexec sleep 60\n')
            pct.chmod(0o700)
            marker = root / 'marker'
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], MARKER=str(marker), FIXTURE=str(root))
            process = subprocess.Popen([sys.executable, str(ROOT / 'remote/oci_native_import.py'),
                '9161', str(source), str(source), '--unprivileged', '1'], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, umask=0o077)
            try:
                for _ in range(100):
                    if marker.exists(): break
                    time.sleep(0.05)
                self.assertTrue(marker.exists())
                staged = Path(marker.read_text().strip())
                self.assertTrue(staged.exists())
                self.assertEqual(stat.S_IMODE((root / "pve-tmp").stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE((root / "pve-tmp/pct.conf").stat().st_mode), 0o644)
                process.send_signal(signal.SIGTERM)
                # Do not leave a shell sleep grandchild holding capture pipes open.
                output, error = process.communicate(timeout=5)
                self.assertIn("native-output", output)
                self.assertEqual(process.returncode, 143)
                self.assertFalse(staged.parent.exists())
            finally:
                if process.poll() is None: process.kill(); process.wait()
                process.stdout.close(); process.stderr.close()
