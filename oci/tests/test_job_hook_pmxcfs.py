"""Job hook contracts can be published on pmxcfs without chmod of /etc/pve/priv."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
import oci_stack_native as native

class JobHookPmxcfsTests(unittest.TestCase):
    def test_atomic_publish_does_not_change_parent_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            path = parent / 'proxmenux-stack-4900.json'
            path.write_text('{"old":true}')
            path.chmod(0o600)
            mode = parent.stat().st_mode
            with patch.object(native, 'private_directory', side_effect=AssertionError('No directory chmod')), \
                 patch.object(native.os, 'chmod', side_effect=PermissionError('pmxcfs')):
                native.write_hook_contract(path, {'schema': 1, 'dependencies': []})
            self.assertEqual(json.loads(path.read_text()), {'schema': 1, 'dependencies': []})
            self.assertEqual(parent.stat().st_mode, mode)
            self.assertEqual(list(parent.iterdir()), [path])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_atomic_publish_preserves_existing_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'proxmenux-stack-4900.json'
            path.write_text('{"old":true}')
            path.chmod(0o600)
            with patch.object(native.os, 'replace', side_effect=OSError('pmxcfs write failed')):
                with self.assertRaisesRegex(OSError, 'write failed'):
                    native.write_hook_contract(path, {'schema': 1})
            self.assertEqual(json.loads(path.read_text()), {'old': True})
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_untrusted_parent_or_file_is_refused_without_writing(self):
        for parent_mode, file_mode in ((0o755, 0o600), (0o700, 0o644)):
            with self.subTest(parent_mode=parent_mode, file_mode=file_mode), tempfile.TemporaryDirectory() as folder:
                parent = Path(folder); parent.chmod(parent_mode)
                path = parent / 'contract.json'; path.write_text('{"old":true}'); path.chmod(file_mode)
                with self.assertRaisesRegex(ValueError, 'Unsafe dependency hook contract'):
                    native.write_hook_contract(path, {'schema': 1})
                self.assertEqual(json.loads(path.read_text()), {'old': True})

    def test_symlink_contract_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            real = Path(folder) / 'real.json'; real.write_text('{"old":true}'); real.chmod(0o600)
            link = Path(folder) / 'contract.json'; link.symlink_to(real)
            with self.assertRaisesRegex(ValueError, 'Unsafe dependency hook contract'):
                native.write_hook_contract(link, {'schema': 1})
            self.assertEqual(json.loads(real.read_text()), {'old': True})
