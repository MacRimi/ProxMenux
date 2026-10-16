from contextlib import nullcontext
import errno
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))
from proxmenux_oci import registry_auth as auth
from proxmenux_oci import registry_accounts as accounts


class FailureHandlingTests(unittest.TestCase):
    def setUp(self):
        self.platform = patch.object(accounts, 'host_architecture', return_value='amd64')
        self.platform.start()
        self.addCleanup(self.platform.stop)

    def test_transport_errors_are_specific_and_never_echo_server_text(self):
        cases = [
            ('unauthorized', 'Access denied'), ('denied', 'Access denied'),
            ('manifest unknown', 'image or tag was not found'),
            ('received unexpected HTTP status: 404 Not Found', 'image or tag was not found'),
            ('toomanyrequests', 'rate limiting'), ('StatusCode: 429', 'rate limiting'),
            ('500 Internal Server Error', 'server error'), ('503 Service Unavailable', 'server error'),
            ('x509: certificate has expired', 'TLS verification failed'),
            ('x509: certificate signed by unknown authority', 'TLS verification failed'),
            ('http: server gave HTTP response to HTTPS client', 'plain HTTP'),
            ('tls: first record does not look like a TLS handshake', 'plain HTTP'),
            ('dial: no such host', 'Could not reach'), ('connection refused', 'Could not reach'),
            ('i/o timeout', 'Could not reach'), ('connection reset', 'Could not reach'),
            ('invalid character in manifest', 'invalid or unsupported'),
            ('docker-credential-missing: executable file not found', 'credential helper'),
        ]
        for error, expected in cases:
            with self.subTest(error=error):
                message = auth.registry_error('registry.test', error + ' SECRET_TOKEN\x1b[31m')
                self.assertIn(expected, message)
                self.assertNotIn('SECRET_TOKEN', message)
                self.assertNotIn('\x1b', message)

    def test_bad_login_credentials_have_a_specific_safe_error(self):
        for error in ('invalid username/password', 'invalid username', 'invalid password',
                      'invalid credentials', 'unauthorized',
                      'Requesting bearer token: invalid status code from registry 403 (Forbidden)'):
            with self.subTest(error=error):
                message = auth.registry_error('registry.test', error + ' SECRET_TOKEN', login=True)
                self.assertIn('Authentication failed', message)
                self.assertNotIn('SECRET_TOKEN', message)

    def test_corrupt_authfile_does_not_trap_the_user_in_a_message_loop(self):
        class Cancelled(RuntimeError):
            pass
        ui = SimpleNamespace(message=MagicMock(), choose=MagicMock())
        saved = SimpleNamespace(accounts=MagicMock(side_effect=auth.RegistryError('Invalid auth file')))
        with patch.object(accounts, 'require_root'), \
                patch.object(accounts.importlib, 'import_module', return_value=SimpleNamespace(UserCancelled=Cancelled)):
            accounts.registry_accounts_menu(ui, auth=saved)
        ui.message.assert_called_once()
        ui.choose.assert_not_called()

    def images(self):
        image = SimpleNamespace(command=MagicMock())
        def resolve(ref, architecture):
            image.command('skopeo', 'inspect', '--raw', 'docker://' + ref)
            return {'manifest_digest': 'sha256:' + 'a' * 64, 'size': 10, 'version': '1.0'}
        image.resolve_candidate = resolve
        return image

    def test_native_resolver_transport_hook_is_scoped_and_restored(self):
        image = self.images()
        original = image.command
        with patch.object(accounts.importlib, 'import_module', return_value=image), \
                patch.object(accounts, 'registry_environment', nullcontext), \
                patch.object(accounts.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'{}')):
            self.assertEqual(accounts.inspect_registry_image('registry.test/team/app:latest')['version'], '1.0')
        self.assertIs(image.command, original)

    def test_native_resolver_restores_transport_hook_after_access_denied(self):
        image = self.images()
        original = image.command
        response = SimpleNamespace(returncode=1, stderr=b'unauthorized SECRET_TOKEN')
        with patch.object(accounts.importlib, 'import_module', return_value=image), \
                patch.object(accounts, 'registry_environment', nullcontext), \
                patch.object(accounts.subprocess, 'run', return_value=response), \
                self.assertRaises(auth.RegistryError) as error:
            accounts.inspect_registry_image('registry.test/team/app:latest')
        self.assertIn('Access denied', str(error.exception))
        self.assertNotIn('SECRET_TOKEN', str(error.exception))
        self.assertIs(image.command, original)

    def test_image_query_timeout_does_not_fall_back_to_a_long_native_timeout(self):
        image = self.images()
        with patch.object(accounts.importlib, 'import_module', return_value=image), \
                patch.object(accounts, 'registry_environment', nullcontext), \
                patch.object(accounts.subprocess, 'run', side_effect=subprocess.TimeoutExpired('skopeo', 30)), \
                self.assertRaises(auth.RegistryError) as error:
            accounts.inspect_registry_image('registry.test/team/app:latest')
        self.assertIn('within 30 seconds', str(error.exception))

    def test_wrong_architecture_and_malformed_metadata_do_not_recommend_relogin(self):
        for native_error, expected in [(ValueError('A single matching image platform cannot be resolved'), 'compatible Linux'),
                                       (ValueError('Invalid JSON'), 'invalid or unsupported'),
                                       (KeyError('config'), 'incomplete or unsupported'),
                                       (AttributeError('bad config'), 'incomplete or unsupported')]:
            image = self.images()
            image.resolve_candidate = MagicMock(side_effect=native_error)
            with self.subTest(error=type(native_error).__name__), \
                    patch.object(accounts.importlib, 'import_module', return_value=image), \
                    patch.object(accounts, 'registry_environment', nullcontext), \
                    self.assertRaises(auth.RegistryError) as error:
                accounts.inspect_registry_image('registry.test/team/app:latest')
            self.assertIn(expected, str(error.exception))

    def test_storage_failures_have_storage_messages_and_keep_native_lock_scope(self):
        for failure, expected in [(ValueError('The new image does not fit on the storage'), 'Not enough free space'),
                                  (OSError(errno.ENOSPC, 'No space left on device'), 'Not enough free space'),
                                  (PermissionError('denied'), 'Cannot write'),
                                  (OSError(errno.EROFS, 'Read-only file system'), 'Cannot write'),
                                  (ValueError('Unsafe OCI archive path'), 'unsafe'),
                                  (RuntimeError('Could not obtain an intact image'), 'integrity verification')]:
            native = SimpleNamespace(instances=SimpleNamespace(ROOT='/fixture', locked=lambda root: nullcontext()),
                                     resolve_archive=MagicMock(side_effect=failure))
            with self.subTest(error=str(failure)), patch.object(accounts, 'inspect_registry_image'), \
                    patch.object(accounts.importlib, 'import_module', return_value=native), \
                    patch.object(accounts, 'registry_environment', nullcontext), \
                    self.assertRaises(auth.RegistryError) as error:
                accounts.download_registry_image('registry.test/team/app:latest', 'local')
            self.assertIn(expected, str(error.exception))

    def test_missing_skopeo_does_not_create_a_saved_account(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve() / 'containers/auth.json'
            manager = auth.RegistryAuth(path)
            with patch.object(auth.subprocess, 'run', side_effect=FileNotFoundError()), \
                    self.assertRaises(auth.RegistryError) as error:
                manager.login('registry.test', 'example', 'example-token')
            self.assertIn('Skopeo is not available', str(error.exception))
            self.assertFalse(path.exists())

    def test_invalid_usernames_and_multiline_or_empty_tokens_never_reach_skopeo(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = auth.RegistryAuth(Path(temp).resolve() / 'containers/auth.json')
            for username, token in [('', 'token'), (' ', 'token'), ('user:colon', 'token'),
                                    ('user\x7f', 'token'), ('name', ''), ('name', 'x\ny'),
                                    ('name', 'x\0y'), ('name', 'x' * 65537)]:
                with self.subTest(username=username, token_length=len(token)), \
                        patch.object(auth.subprocess, 'run') as run, self.assertRaises(auth.RegistryError):
                    manager.login('registry.test', username, token)
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
