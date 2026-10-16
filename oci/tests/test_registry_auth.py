import base64
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))
from proxmenux_oci import registry_auth as auth_module


class AuthenticationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve() / 'containers'
        self.directory.mkdir(mode=0o700)
        self.path = self.directory / 'auth.json'
        self.auth = auth_module.RegistryAuth(self.path)
        self.token = 'TEST_TOKEN_MUST_NEVER_APPEAR_IN_OUTPUT'
        self.output = io.StringIO()

    def save(self, registry='ghcr.io', username='example', token='old-token'):
        data = {'auths': {registry: {'auth': base64.b64encode(f'{username}:{token}'.encode()).decode()}}}
        self.path.write_text(json.dumps(data))
        self.path.chmod(0o600)
        return data

    def skopeo_login(self, argv, **kwargs):
        self.assertEqual(argv[:2], ['skopeo', 'login'])
        self.assertNotIn(self.token, ' '.join(argv))
        self.assertNotIn('env', kwargs)
        self.assertEqual(kwargs['input'], self.token + '\n')
        stage = Path(argv[argv.index('--authfile') + 1])
        self.assertEqual(stage.stat().st_mode & 0o777, 0o600)
        data = json.loads(stage.read_text())
        data.setdefault('auths', {})[argv[-1]] = {'auth': base64.b64encode(f'new-user:{self.token}'.encode()).decode()}
        stage.write_text(json.dumps(data))
        return SimpleNamespace(returncode=0, stderr='', stdout='Login Succeeded!')

    def test_login_is_atomic_private_and_preserves_other_accounts(self):
        original = self.save('docker.io')
        with patch.object(auth_module.subprocess, 'run', side_effect=self.skopeo_login):
            self.auth.login('ghcr.io', 'new-user', self.token)
        data = json.loads(self.path.read_text())
        self.assertEqual(data['auths']['docker.io'], original['auths']['docker.io'])
        self.assertIn('ghcr.io', data['auths'])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.directory.glob('.proxmenux-auth-*')), [])

    def test_failed_login_retains_previous_file_and_never_echoes_registry_error(self):
        self.save()
        before = self.path.read_bytes()
        result = SimpleNamespace(returncode=1, stderr='unauthorized: ' + self.token)
        with patch.object(auth_module.subprocess, 'run', return_value=result), self.assertRaises(auth_module.RegistryError) as error:
            self.auth.login('ghcr.io', 'new-user', self.token)
        self.assertIn('Authentication failed', str(error.exception))
        self.assertNotIn(self.token, str(error.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.directory.glob('.proxmenux-auth-*')), [])

    def test_timed_out_login_does_not_create_a_credential_file(self):
        with patch.object(auth_module.subprocess, 'run', side_effect=subprocess.TimeoutExpired('skopeo', 5)), \
                self.assertRaises(auth_module.RegistryError):
            self.auth.login('ghcr.io', 'new-user', self.token, 5)
        self.assertFalse(self.path.exists())

    def test_external_credential_edit_is_not_overwritten(self):
        self.save()
        def concurrent_edit(argv, **kwargs):
            result = self.skopeo_login(argv, **kwargs)
            self.save('quay.io', 'other-task')
            return result
        with patch.object(auth_module.subprocess, 'run', side_effect=concurrent_edit), self.assertRaises(auth_module.RegistryError):
            self.auth.login('ghcr.io', 'new-user', self.token)
        self.assertEqual(set(json.loads(self.path.read_text())['auths']), {'quay.io'})

    def test_empty_listing_does_not_create_paths(self):
        path = self.directory / 'new' / 'auth.json'
        auth = auth_module.RegistryAuth(path)
        self.assertEqual(auth.accounts(), [])
        self.assertFalse(path.parent.exists())

    def test_logout_preserves_unrelated_accounts(self):
        self.save()
        data = json.loads(self.path.read_text())
        data['auths']['docker.io'] = {'auth': base64.b64encode(b'user:other-token').decode()}
        self.path.write_text(json.dumps(data))
        def logout(argv, **kwargs):
            stage = Path(argv[argv.index('--authfile') + 1])
            saved = json.loads(stage.read_text())
            saved['auths'].pop('ghcr.io')
            stage.write_text(json.dumps(saved))
            return SimpleNamespace(returncode=0)
        with patch.object(auth_module.subprocess, 'run', side_effect=logout):
            self.assertTrue(self.auth.logout('ghcr.io'))
        self.assertEqual(set(json.loads(self.path.read_text())['auths']), {'docker.io'})

    def test_logout_unknown_registry_does_not_modify_file(self):
        self.save()
        before = self.path.read_bytes()
        with patch.object(auth_module.subprocess, 'run') as run:
            self.assertFalse(self.auth.logout('quay.io'))
        run.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_logout_removes_repository_scopes_without_affecting_other_registries(self):
        self.save('ghcr.io/private/team')
        with patch.object(auth_module.subprocess, 'run') as run:
            self.assertTrue(self.auth.logout('ghcr.io'))
        run.assert_not_called()
        self.assertFalse(json.loads(self.path.read_text())['auths'])

    def test_symlink_authfile_is_rejected_without_reading_target(self):
        target = self.directory / 'other'
        target.write_text('sensitive target')
        self.path.symlink_to(target)
        with self.assertRaises(auth_module.RegistryError):
            self.auth.accounts()
        self.assertEqual(target.read_text(), 'sensitive target')

    def test_insecure_directory_or_file_permissions_are_rejected(self):
        self.save()
        self.path.chmod(0o644)
        with self.assertRaises(auth_module.RegistryError):
            self.auth.accounts()
        self.path.chmod(0o600)
        self.directory.chmod(0o755)
        with self.assertRaises(auth_module.RegistryError):
            self.auth.accounts()

    def test_non_regular_credential_file_cannot_block_the_command(self):
        os.mkfifo(self.path, mode=0o600)
        with self.assertRaises(auth_module.RegistryError):
            self.auth.accounts()

    def test_writable_parent_directory_is_rejected(self):
        self.directory.parent.chmod(0o777)
        self.addCleanup(self.directory.parent.chmod, 0o700)
        with self.assertRaises(auth_module.RegistryError):
            self.auth.accounts()

    def test_corrupt_file_is_not_overwritten(self):
        self.path.write_text('{invalid')
        self.path.chmod(0o600)
        with patch.object(auth_module.subprocess, 'run') as run, self.assertRaises(auth_module.RegistryError):
            self.auth.login('ghcr.io', 'new-user', self.token)
        run.assert_not_called()
        self.assertEqual(self.path.read_text(), '{invalid')

    def test_durable_authfile_is_used_by_descendants_and_environment_is_restored(self):
        self.save()
        with patch.dict(os.environ, {'REGISTRY_AUTH_FILE': str(self.path)}):
            with auth_module.registry_environment():
                self.assertEqual(os.environ['REGISTRY_AUTH_FILE'], str(self.path))
            self.assertEqual(os.environ['REGISTRY_AUTH_FILE'], str(self.path))
        with patch.dict(os.environ, clear=True), patch.object(auth_module.Path, 'home', return_value=self.directory.parent):
            # Use the normal XDG_CONFIG_HOME fallback without touching /root.
            os.environ['XDG_CONFIG_HOME'] = str(self.directory.parent)
            with auth_module.registry_environment():
                self.assertEqual(os.environ['REGISTRY_AUTH_FILE'], str(self.path))
            self.assertNotIn('REGISTRY_AUTH_FILE', os.environ)

    def test_account_listing_never_returns_a_password_or_token(self):
        self.save(token=self.token)
        with patch.object(auth_module.subprocess, 'run') as run:
            rows = self.auth.accounts()
        run.assert_not_called()
        text = json.dumps(rows)
        self.assertEqual(rows[0]['account'], 'example')
        self.assertNotIn(self.token, text)
        self.assertNotIn(base64.b64encode(f'example:{self.token}'.encode()).decode(), text)

    def test_invalid_staged_credentials_cannot_replace_a_working_account(self):
        self.save()
        before = self.path.read_bytes()
        def corrupt_login(argv, **kwargs):
            Path(argv[argv.index('--authfile') + 1]).write_text('{invalid')
            return SimpleNamespace(returncode=0, stderr='')
        with patch.object(auth_module.subprocess, 'run', side_effect=corrupt_login), \
                self.assertRaises(auth_module.RegistryError):
            self.auth.login('ghcr.io', 'new-user', self.token)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.directory.glob('.proxmenux-auth-*')), [])

    def test_credential_commit_failure_preserves_saved_file_and_cleans_staging(self):
        for failure in (OSError(errno.ENOSPC, 'No space left on device'),
                        PermissionError(errno.EACCES, 'Permission denied')):
            self.save()
            before = self.path.read_bytes()
            with self.subTest(error=type(failure).__name__), \
                    patch.object(auth_module.subprocess, 'run', side_effect=self.skopeo_login), \
                    patch.object(auth_module.os, 'replace', side_effect=failure), \
                    self.assertRaises(OSError):
                self.auth.login('ghcr.io', 'new-user', self.token)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(list(self.directory.glob('.proxmenux-auth-*')), [])

    def test_failed_or_timed_out_logout_keeps_saved_accounts(self):
        self.save()
        before = self.path.read_bytes()
        for failure in (None, subprocess.TimeoutExpired('skopeo', 30), FileNotFoundError()):
            response = SimpleNamespace(returncode=1, stderr=self.token)
            with self.subTest(error=type(failure).__name__), \
                    patch.object(auth_module.subprocess, 'run', side_effect=failure, return_value=response), \
                    self.assertRaises(auth_module.RegistryError) as error:
                self.auth.logout('ghcr.io')
            self.assertNotIn(self.token, str(error.exception))
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(list(self.directory.glob('.proxmenux-auth-*')), [])


if __name__ == '__main__':
    unittest.main()
