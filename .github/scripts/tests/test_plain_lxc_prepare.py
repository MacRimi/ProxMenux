"""Offline rootfs preparation, including real filesystem failure boundaries."""
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[3] / 'scripts/lxc/plain_lxc_prepare.py'
spec = importlib.util.spec_from_file_location('rootfs_preparation', SOURCE)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
CERT = b'[Unit]\nConditionFirstBoot=yes\n[Service]\nType=oneshot\nExecStart=make-ssl-cert -f generate-default-snakeoil\n'
SSL = b'[Service]\nType=oneshot\nExecStart=-/usr/sbin/make-ssl-cert generate-default-snakeoil --force-overwrite\n'
WAIT = b'[Service]\nType=oneshot\nExecStart=/usr/lib/systemd/systemd-networkd-wait-online\n'


class PreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.put('etc/systemd/system/' + prepare.CERT_UNIT, CERT)
        self.put('usr/lib/systemd/system/ssl-cert.service', SSL)
        self.put('usr/lib/systemd/system/' + prepare.WAIT_UNIT, WAIT)
        (self.root/'lib').symlink_to('usr/lib')

    def put(self, name, content):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def run_preparation(self, offline=True):
        return prepare.prepare(self.root, os.getuid(), os.getgid(), offline)

    def snapshot(self):
        return {str(p.relative_to(self.root)): ('link', os.readlink(p)) if p.is_symlink()
                else ('file', p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in self.root.rglob('*')
                if p.is_file() or p.is_symlink()}

    def test_real_unit_contract_installs_exact_owned_files_and_is_idempotent(self):
        result = self.run_preparation()
        self.assertEqual(len(result['prepared_files']), 3)
        for name in result['prepared_files']:
            path = self.root/name
            mode = 0o755 if name.endswith('proxmenux-has-network-interface') else 0o644
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
            self.assertEqual((path.stat().st_uid, path.stat().st_gid), (os.getuid(), os.getgid()))
        snapshot = self.snapshot()
        self.assertEqual(self.run_preparation(), result)
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual((self.root/'etc/systemd/system'/prepare.CERT_UNIT).read_bytes(), CERT)

    def test_networked_plan_does_not_modify_network_units_or_install_condition(self):
        result = self.run_preparation(offline=False)
        self.assertEqual(len(result['prepared_files']), 1)
        self.assertFalse((self.root/'usr/local').exists())

    def test_restrictive_host_umask_does_not_make_guest_directories_private(self):
        previous = os.umask(0o077)
        try:
            result = self.run_preparation()
        finally:
            os.umask(previous)
        for name in result['prepared_files']:
            self.assertEqual(stat.S_IMODE((self.root/name).parent.stat().st_mode), 0o755)

    def test_absent_units_are_valid_noop_not_an_invented_systemd_recipe(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(prepare.prepare(folder, os.getuid(), os.getgid(), True)['prepared_files'], [])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_unknown_unit_contract_or_customization_has_zero_writes(self):
        cases = (
            ('usr/lib/systemd/system/' + prepare.WAIT_UNIT, b'[Service]\nExecStart=/custom/program\n'),
            ('etc/systemd/system/' + prepare.CERT_UNIT + '.d/custom.conf', b'[Unit]\nAfter=custom.service\n'),
            ('etc/systemd/system/' + prepare.CERT_UNIT + '.d/' + prepare.MANAGED, b'custom data\n'),
            ('usr/local/libexec/proxmenux-has-network-interface', b'custom executable\n'),
            ('usr/lib/systemd/system/ssl-cert.service', SSL + b'\n[Unit]\nAfter=proxmox-regenerate-snakeoil.service\n'),
            ('usr/lib/systemd/system/' + prepare.WAIT_UNIT, WAIT + b'ExecStartPre=/custom/network-setup\n'),
        )
        for name, content in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                import shutil
                shutil.copytree(self.root, folder, dirs_exist_ok=True, symlinks=True)
                original = self.root; self.root = Path(folder)
                try:
                    self.put(name, content); before = self.snapshot()
                    with self.assertRaises(prepare.PreparationError): self.run_preparation()
                    self.assertEqual(self.snapshot(), before)
                finally: self.root = original

    def test_symlink_directories_and_files_never_write_outside_rootfs(self):
        with tempfile.TemporaryDirectory() as outside:
            sentinel = Path(outside)/'sentinel'; sentinel.write_bytes(b'host untouched')
            (self.root/'usr/local').symlink_to(outside)
            before = self.snapshot()
            with self.assertRaises(OSError): self.run_preparation()
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(list(Path(outside).iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b'host untouched')
            (self.root/'usr/local').unlink()
            target = self.put('usr/local/libexec/proxmenux-has-network-interface', b'')
            target.unlink(); target.symlink_to(sentinel)
            with self.assertRaises(OSError): self.run_preparation()
            self.assertEqual(sentinel.read_bytes(), b'host untouched')

    def test_write_and_publish_failure_roll_back_only_new_managed_files(self):
        for operation in ('fsync', 'link', 'fchown'):
            with self.subTest(operation=operation):
                before = self.snapshot(); original = getattr(prepare.os, operation); calls = 0
                def fail_once(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 2: raise OSError('simulated write failure')
                    return original(*args, **kwargs)
                with patch.object(prepare.os, operation, side_effect=fail_once):
                    with self.assertRaises(OSError): self.run_preparation()
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(list(self.root.rglob('.proxmenux-*')))

    def test_hardlinks_and_fifo_are_rejected_without_reading_or_writing(self):
        unit = self.root/'usr/lib/systemd/system'/prepare.WAIT_UNIT
        saved = unit.read_bytes(); unit.unlink()
        os.mkfifo(unit)
        with self.assertRaises(prepare.PreparationError): self.run_preparation()
        unit.unlink(); unit.write_bytes(saved)
        os.link(unit, self.root/'hardlink')
        with self.assertRaises(prepare.PreparationError): self.run_preparation()
        self.assertEqual(unit.read_bytes(), saved)

    def test_interface_condition_distinguishes_absence_loopback_files_and_real_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory)/'net'
            script = prepare.INTERFACE_HELPER.replace(b'/sys/class/net', os.fsencode(inventory))
            def result(): return subprocess.run(['/bin/sh'], input=script, capture_output=True).returncode
            self.assertEqual(result(), 255)
            inventory.mkdir(); (inventory/'lo').mkdir()
            (inventory/'bonding_masters').write_text('')
            self.assertEqual(result(), 1)
            (inventory/'eth0').mkdir()
            self.assertEqual(result(), 0)

    def test_cli_invalid_root_never_opens_the_filesystem(self):
        with patch.object(prepare.sys, 'argv', ['helper', '/etc', '100000', '100000', '1']), \
                patch.object(prepare, 'prepare') as action, patch('builtins.print'):
            self.assertEqual(prepare.main(), 1)
            action.assert_not_called()
