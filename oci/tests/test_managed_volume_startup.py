"""Managed filesystem preparation must preserve read-only data."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
import oci_instance_transaction as transaction


class RecoveryGuardTests(unittest.TestCase):
    def test_read_only_managed_volume_is_not_probed_or_changed(self):
        deployment = {'mounts': [{'type': 'managed-volume', 'backup': True,
                                  'container_path': '/config', 'read_only': True}]}
        with patch.object(Path, 'is_symlink', return_value=False) as probe, \
                patch.object(Path, 'exists', return_value=False):
            transaction.remove_empty_format_directories('/fixture/rootfs', deployment)
        probe.assert_not_called()

    def test_nested_read_only_mount_protects_the_format_directory(self):
        deployment = {'mounts': [
            {'type': 'managed-volume', 'backup': True, 'container_path': '/config'},
            {'type': 'host-bind', 'container_path': '/config/lost+found', 'read_only': True},
        ]}
        with patch.object(Path, 'is_symlink', return_value=False) as probe, \
                patch.object(Path, 'exists', return_value=False):
            transaction.remove_empty_format_directories('/fixture/rootfs', deployment)
        probe.assert_not_called()

    def test_a_relative_mount_path_is_rejected_before_filesystem_probes(self):
        deployment = {'mounts': [{'type': 'managed-volume', 'backup': True,
                                  'container_path': 'config'}]}
        with patch.object(Path, 'is_symlink', return_value=False) as probe, \
                patch.object(Path, 'exists', return_value=False):
            with self.assertRaises(ValueError):
                transaction.remove_empty_format_directories('/fixture/rootfs', deployment)
        probe.assert_not_called()


import contextlib
import copy
import fcntl
import json
import os
from types import SimpleNamespace
import subprocess

import oci_managed_volumes as volumes
import oci_restore_recovery as recovery
import oci_instances as instances


@contextlib.contextmanager
def ext4_metadata(**overrides):
    """Use real filesystem operations; only mkfs inode/ownership are fixtures."""
    real_stat, real_fstat = os.stat, os.fstat
    def info(value):
        fields = {key: getattr(value, key) for key in ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode')}
        fields.update(st_ino=11, st_uid=0, st_gid=0)
        fields.update(overrides)
        return SimpleNamespace(**fields)
    def observed(path, *args, **kwargs):
        value = real_stat(path, *args, **kwargs)
        return info(value) if str(path) == 'lost+found' else value
    def opened(fd):
        value = real_fstat(fd)
        return info(value) if os.readlink(f'/proc/self/fd/{fd}').endswith('/lost+found') else value
    with patch.object(volumes.os, 'stat', side_effect=observed), \
            patch.object(volumes.os, 'fstat', side_effect=opened):
        yield


class FormatDirectoryTests(unittest.TestCase):
    def fixture(self, root):
        target = root / 'config'
        target.mkdir()
        lost = target / 'lost+found'
        lost.mkdir(mode=0o700)
        (target / 'keep').write_bytes(b'application data')
        return lost, {'mounts': [{'container_path': '/config', 'type': 'managed-volume', 'backup': True}]}

    def test_only_an_empty_format_directory_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); lost, deployment = self.fixture(root)
            before = copy.deepcopy(deployment)
            with ext4_metadata():
                self.assertEqual(volumes.remove_empty_format_directories(root, deployment), 1)
            self.assertFalse(lost.exists())
            self.assertEqual((root / 'config/keep').read_bytes(), b'application data')
            self.assertEqual(deployment, before)

    def test_nonempty_format_directory_has_no_remove_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); lost, deployment = self.fixture(root)
            (lost / 'recovered-file').write_bytes(b'must survive')
            with ext4_metadata(), patch.object(volumes.os, 'rmdir') as remove:
                self.assertEqual(volumes.remove_empty_format_directories(root, deployment), 0)
                remove.assert_not_called()
            self.assertEqual((lost / 'recovered-file').read_bytes(), b'must survive')

    def test_nonstandard_metadata_is_preserved_without_remove(self):
        for override in ({'st_ino': 12}, {'st_uid': 100000}, {'st_gid': 100000}, {'st_mode': 0o40755}):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); lost, deployment = self.fixture(root)
                with ext4_metadata(**override), patch.object(volumes.os, 'rmdir') as remove:
                    self.assertEqual(volumes.remove_empty_format_directories(root, deployment), 0)
                    remove.assert_not_called()
                self.assertTrue(lost.is_dir())

    def test_link_and_parent_link_never_reach_external_data(self):
        for parent in (False, True):
            with self.subTest(parent=parent), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp); root = base / 'root'; root.mkdir()
                outside = base / 'outside'; outside.mkdir()
                (outside / 'keep').write_text('external')
                if parent:
                    (root / 'config').symlink_to(outside, target_is_directory=True)
                else:
                    (root / 'config').mkdir()
                    (root / 'config/lost+found').symlink_to(outside, target_is_directory=True)
                deployment = {'mounts': [{'container_path': '/config', 'type': 'managed-volume', 'backup': True}]}
                with patch.object(volumes.os, 'rmdir') as remove:
                    if parent:
                        with self.assertRaises(ValueError):
                            volumes.remove_empty_format_directories(root, deployment)
                    else:
                        self.assertEqual(volumes.remove_empty_format_directories(root, deployment), 0)
                    remove.assert_not_called()
                self.assertEqual((outside / 'keep').read_text(), 'external')

    def test_bind_readonly_and_nonbacked_recovery_make_no_filesystem_calls(self):
        for options in ({'type': 'host-bind'}, {'read_only': True}, {'backup': False}):
            mount = {'container_path': '/config', 'type': 'managed-volume', 'backup': True, **options}
            with self.subTest(options=options), patch.object(volumes.os, 'open') as opened, \
                    patch.object(volumes.os, 'rmdir') as remove:
                self.assertEqual(volumes.remove_empty_format_directories('/rootfs', {'mounts': [mount]}), 0)
                opened.assert_not_called(); remove.assert_not_called()

    def test_new_nonbacked_managed_disk_is_prepared_without_changing_backup_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); lost, deployment = self.fixture(root)
            deployment['mounts'][0]['backup'] = False
            with ext4_metadata():
                self.assertEqual(volumes.remove_empty_format_directories(root, deployment, backed_only=False), 1)
            self.assertFalse(lost.exists())
            self.assertFalse(deployment['mounts'][0]['backup'])

    def test_read_failure_does_not_mean_empty_and_does_not_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); lost, deployment = self.fixture(root)
            with ext4_metadata(), patch.object(volumes.os, 'scandir', side_effect=PermissionError), \
                    patch.object(volumes.os, 'rmdir') as remove:
                with self.assertRaises(PermissionError):
                    volumes.remove_empty_format_directories(root, deployment)
                remove.assert_not_called()
            self.assertTrue(lost.is_dir())

    def test_invalid_paths_are_rejected_before_any_filesystem_call(self):
        for path in ('config', '/', '//', '/config/../outside', '/config/./data', '/bad\npath'):
            with self.subTest(path=path), patch.object(volumes.os, 'open') as opened:
                with self.assertRaises(ValueError):
                    volumes.remove_empty_format_directories('/rootfs', {'mounts': [
                        {'container_path': path, 'type': 'managed-volume', 'backup': True}]})
                opened.assert_not_called()


    def test_duplicate_paths_are_rejected_before_filesystem_calls(self):
        mount = {'container_path': '/config', 'type': 'managed-volume', 'backup': True}
        with patch.object(volumes.os, 'open') as opened:
            with self.assertRaises(ValueError):
                volumes.remove_empty_format_directories('/rootfs', {'mounts': [mount, dict(mount)]})
            opened.assert_not_called()


    def test_missing_rootfs_is_an_error_without_remove(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(volumes.os, 'rmdir') as remove:
            with self.assertRaises(FileNotFoundError):
                volumes.remove_empty_format_directories(Path(tmp) / 'missing', {'mounts': [
                    {'container_path': '/config', 'type': 'managed-volume', 'backup': True}]})
            remove.assert_not_called()

    def test_missing_managed_mount_is_an_error_without_remove(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(volumes.os, 'rmdir') as remove:
            with self.assertRaises(FileNotFoundError):
                volumes.remove_empty_format_directories(Path(tmp), {'mounts': [
                    {'container_path': '/missing', 'type': 'managed-volume', 'backup': True}]})
            remove.assert_not_called()


class StartupContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.base = Path(directory.name); self.registry = self.base / 'registry'
        self.registry.mkdir(); (self.registry / '.lock').touch(mode=0o600)
        self.record = {'schema_version': 1, 'vmid': 1000,
                       'installation_id': '11111111-1111-4111-8111-111111111111',
                       'status': 'installed', 'deployment': {'mounts': [
                           {'container_path': '/config', 'type': 'managed-volume', 'backup': True}]}}
        (self.registry / '1000').mkdir()
        self.record_path = self.registry / '1000/oci-compose.json'
        self.record_path.write_text(json.dumps(self.record))
        self.rootfs = self.base / 'guests/1000/rootfs'
        self.rootfs.mkdir(parents=True)
        self.lost = self.rootfs / 'config/lost+found'; self.lost.mkdir(parents=True, mode=0o700)
        (self.rootfs / 'config/keep').write_text('application data')
        self.config = (f'description: <!-- proxmenux-instance={self.record["installation_id"]} -->\n'
                       'mp0: local:1000/vm-1000-disk-1.raw,mp=/config,backup=1,size=16G\n').encode()

    def call(self, *, config=None, returncode=0):
        response = SimpleNamespace(returncode=returncode, stdout=self.config if config is None else config)
        before = self.record_path.read_bytes()
        with patch.object(volumes.subprocess, 'run', return_value=response) as command:
            result = volumes.cleanup_startup(self.registry, 1000, self.base / 'guests')
        self.assertEqual(self.record_path.read_bytes(), before)
        return result, command

    def test_current_matching_managed_mount_cleans_before_start_without_guest_exec(self):
        with ext4_metadata():
            result, command = self.call()
        self.assertEqual(result, 1); self.assertFalse(self.lost.exists())
        command.assert_called_once_with(['pct', 'config', '1000'], capture_output=True, timeout=3)
        self.assertEqual((self.rootfs / 'config/keep').read_text(), 'application data')

    def test_wrong_identity_failed_command_empty_output_and_changed_mount_do_not_remove(self):
        cases = [(self.config.replace(b'11111111', b'22222222'), 0), (b'', 0), (self.config, 1),
                 (self.config.replace(b'local:1000/vm-1000-disk-1.raw', b'/host/data'), 0),
                 (self.config.replace(b'backup=1', b'backup=0'), 0),
                 (self.config.replace(b'backup=1', b'backup=1,ro=1'), 0)]
        for config, code in cases:
            with self.subTest(config=config, code=code), ext4_metadata(), patch.object(volumes.os, 'rmdir') as remove:
                result, _ = self.call(config=config, returncode=code)
                self.assertEqual(result, 0); remove.assert_not_called()
                self.assertTrue(self.lost.is_dir())

    def test_pending_unsupported_or_hostonly_record_never_calls_pct(self):
        for change in ({'status': 'updating'}, {'status': 'failed'}, {'pending_transaction': '/private/journal'},
                       {'deployment': {'mounts': [{'container_path': '/config', 'type': 'host-bind'}]}}):
            with self.subTest(change=change):
                self.record_path.write_text(json.dumps({**self.record, **change}))
                result, command = self.call()
                self.assertEqual(result, 0); command.assert_not_called()
                self.assertTrue(self.lost.is_dir())

    def test_busy_lock_is_immediate_and_leaves_files_unchanged(self):
        with (self.registry / '.lock').open('r') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(volumes.subprocess, 'run') as command, patch.object(volumes.os, 'rmdir') as remove:
                with self.assertRaises(BlockingIOError):
                    volumes.cleanup_startup(self.registry, 1000, self.base / 'guests')
                command.assert_not_called(); remove.assert_not_called()
        self.assertTrue(self.lost.is_dir())

    def test_missing_or_invalid_record_and_timeout_never_remove(self):
        for value in ('missing', 'invalid', 'timeout'):
            with self.subTest(value=value):
                if value == 'missing': self.record_path.unlink()
                elif value == 'invalid': self.record_path.write_text('{')
                else: self.record_path.write_text(json.dumps(self.record))
                with patch.object(volumes.subprocess, 'run', side_effect=subprocess.TimeoutExpired('pct', 3)), \
                        patch.object(volumes.os, 'rmdir') as remove:
                    with self.assertRaises((OSError, ValueError, subprocess.TimeoutExpired)):
                        volumes.cleanup_startup(self.registry, 1000, self.base / 'guests')
                    remove.assert_not_called()
                self.assertTrue(self.lost.is_dir())


class RecoveryConsumerTests(unittest.TestCase):
    def test_transaction_recovery_uses_real_cleanup_and_always_unmounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base / '1000/rootfs'; root.mkdir(parents=True)
            lost, deployment = FormatDirectoryTests().fixture(root)
            with patch.object(transaction, 'owned') as owned, patch.object(transaction, 'run') as command, \
                    patch.object(transaction, 'Path', return_value=base), ext4_metadata(), \
                    patch.object(volumes, 'remove_empty_format_directories', wraps=volumes.remove_empty_format_directories) as clean:
                transaction.cleanup_restored_format_dirs(1000, deployment, 'identity')
                owned.assert_called_once_with(1000, 'identity')
                self.assertEqual([c.args for c in command.call_args_list],
                                 [('pct', 'mount', '1000'), ('pct', 'unmount', '1000')])
                clean.assert_called_once()
            self.assertFalse(lost.exists())
            self.assertEqual((root / 'config/keep').read_bytes(), b'application data')

    def test_transaction_failure_still_unmounts_and_identity_failure_never_mounts(self):
        deployment = {'mounts': [{'type': 'managed-volume', 'container_path': '/config', 'backup': True}]}
        with patch.object(transaction, 'owned'), patch.object(transaction, 'run') as command, \
                patch.object(volumes, 'remove_empty_format_directories', side_effect=OSError('read failed')):
            with self.assertRaises(OSError):
                transaction.cleanup_restored_format_dirs(1000, deployment, 'identity')
            self.assertEqual(command.call_args_list[-1].args, ('pct', 'unmount', '1000'))
        with patch.object(transaction, 'owned', side_effect=ValueError('identity')), \
                patch.object(transaction, 'run') as command:
            with self.assertRaises(ValueError):
                transaction.cleanup_restored_format_dirs(1000, deployment, 'identity')
            command.assert_not_called()

    def test_recover_menu_consumer_cleans_managed_and_preserves_ro_or_nested_bind(self):
        for protected in ('none', 'readonly', 'nested-bind'):
            with self.subTest(protected=protected), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); lost, _ = FormatDirectoryTests().fixture(root)
                config = 'mp0: local:1000/vm-1000-disk-1.raw,mp=/config,backup=1'
                if protected == 'readonly': config += ',ro=1'
                if protected == 'nested-bind': config += '\nmp1: /host/recovery,mp=/config/lost+found,ro=1'
                with ext4_metadata(), patch.object(recovery.carried, 'container_root', return_value=contextlib.nullcontext(root)), \
                        patch.object(volumes.os, 'rmdir', wraps=os.rmdir) as remove:
                    recovery.clean_format_directories({'vmid': 1000, 'config': config})
                    if protected == 'none':
                        self.assertFalse(lost.exists()); remove.assert_called_once()
                    else:
                        self.assertTrue(lost.is_dir()); remove.assert_not_called()
                self.assertEqual((root / 'config/keep').read_bytes(), b'application data')


if __name__ == '__main__':
    unittest.main()
