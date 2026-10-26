import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))
from proxmenux_oci import registry_accounts as accounts


class Cancelled(RuntimeError):
    pass


class UI:
    def __init__(self, choices, answers=(), password='MENU_TEST_TOKEN'):
        self.choices = iter(choices)
        self.answers = iter(answers)
        self.password_value = password
        self.seen = []

    def choose(self, text, options, default=None, **kwargs):
        self.seen.append((text, options, kwargs))
        return next(self.choices)

    def ask(self, text, default=None):
        self.seen.append(text)
        return next(self.answers)

    def password(self, text):
        self.seen.append(text)
        if isinstance(self.password_value, Exception):
            raise self.password_value
        return self.password_value

    def message(self, text, title=None):
        self.seen.append((title, text))

    def info(self, text, title=None):
        self.seen.append((title, text))

    def confirm(self, text, default=False, **kwargs):
        self.seen.append(text)
        return False


class RegistryMenuTests(unittest.TestCase):
    def run_menu(self, ui, auth, extra_modules=None):
        modules = {'proxmenux_oci.ui': SimpleNamespace(UserCancelled=Cancelled),
                   'proxmenux_oci.host': SimpleNamespace(storages=lambda content: [{'storage': 'local', 'avail': 10**9}])}
        modules.update(extra_modules or {})
        with patch.object(accounts, 'require_root'), patch.object(accounts.importlib, 'import_module', side_effect=lambda name: modules[name]):
            accounts.registry_accounts_menu(ui, engine='/fake/engine', auth=auth)

    def account(self):
        return {'registry': 'ghcr.io', 'account': 'example', 'method': 'Username / token', 'status': 'Saved'}

    def auth(self, rows=None):
        return SimpleNamespace(accounts=MagicMock(return_value=rows or []), login=MagicMock(), logout=MagicMock())

    def test_native_menu_can_add_an_account_without_exposing_the_token(self):
        auth = self.auth()
        ui = UI(['add', None], ['ghcr.io', 'example'])
        self.run_menu(ui, auth)
        auth.login.assert_called_once_with('ghcr.io', 'example', 'MENU_TEST_TOKEN')
        self.assertNotIn('MENU_TEST_TOKEN', repr(ui.seen))

    def test_cancelled_password_does_not_change_credentials(self):
        auth = self.auth()
        ui = UI(['add', None], ['ghcr.io', 'example'], password=Cancelled())
        self.run_menu(ui, auth)
        auth.login.assert_not_called()

    def test_invalid_authority_cannot_reach_login(self):
        auth = self.auth()
        ui = UI(['add', None], ['https://ghcr.io'])
        self.run_menu(ui, auth)
        auth.login.assert_not_called()
        self.assertIn('registry hostname', repr(ui.seen))

    def test_account_can_download_through_the_shared_native_cache_helper(self):
        auth = self.auth([self.account()])
        ui = UI(['account-0', 'download', 'local', None], ['ghcr.io/example/private:latest'])
        result = {'archive': '/cache/proxmenux-update-amd64-fixture.tar', 'size': 1024}
        with patch.object(accounts, 'download_registry_image', return_value=result) as download:
            self.run_menu(ui, auth)
        download.assert_called_once_with('ghcr.io/example/private:latest', 'local')
        self.assertIn('Image downloaded and verified', repr(ui.seen))

    def test_selected_account_does_not_pull_from_another_registry(self):
        auth = self.auth([self.account()])
        ui = UI(['account-0', 'download', None], ['quay.io/example/private:latest'])
        with patch.object(accounts, 'download_registry_image') as download:
            self.run_menu(ui, auth)
        download.assert_not_called()

    def test_logout_requires_confirmation_in_the_menu(self):
        auth = self.auth([self.account()])
        ui = UI(['account-0', 'logout', None])
        self.run_menu(ui, auth)
        auth.logout.assert_not_called()

    def test_menu_offers_install_download_and_credential_management(self):
        auth = self.auth([self.account()])
        ui = UI(['account-0', None, None])
        self.run_menu(ui, auth)
        actions = ui.seen[1][1]
        self.assertEqual([tag for tag, label in actions], ['inspect', 'download', 'install', 'login', 'logout'])

    def test_menu_preserves_the_configured_language_when_an_operation_fails(self):
        from proxmenux_oci import i18n
        cache = {'Saved': 'Guardado'}
        with patch.object(i18n, '_language', 'es'), patch.object(i18n, '_cache', cache), \
                patch.object(accounts, 'registry_accounts_menu', side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):
                accounts.open_registry_accounts(UI([]))
            self.assertEqual(i18n._language, 'es')
            self.assertIs(i18n._cache, cache)

    def test_native_main_menu_dispatches_to_registry_accounts(self):
        from proxmenux_oci import cli
        catalog = SimpleNamespace(index_path=SimpleNamespace(exists=lambda: True),
                                  load_index=lambda: {'applications': []})
        ui = UI(['registries', None])
        with patch.object(cli, 'interactive_ui', return_value=ui), \
                patch.object(accounts, 'open_registry_accounts') as open_accounts:
            self.assertEqual(cli.interactive(catalog), 0)
        open_accounts.assert_called_once_with(ui)

    def test_terminal_fallback_can_sign_in_without_exposing_the_password(self):
        from proxmenux_oci.ui import TerminalUI
        auth = self.auth()
        output = io.StringIO()
        with patch.object(accounts, 'require_root'), \
                patch('builtins.input', side_effect=['1', 'registry.test', 'example', '0']), \
                patch('getpass.getpass', return_value='MENU_TEST_TOKEN'), \
                contextlib.redirect_stdout(output):
            accounts.registry_accounts_menu(TerminalUI(), auth=auth)
        auth.login.assert_called_once_with('registry.test', 'example', 'MENU_TEST_TOKEN')
        self.assertIn('Signed in to registry.test', output.getvalue())
        self.assertNotIn('MENU_TEST_TOKEN', output.getvalue())

    def test_startup_configuration_errors_return_a_message_to_the_main_menu(self):
        from proxmenux_oci.registry_auth import RegistryError
        ui = UI([])
        with patch.object(accounts, 'registry_accounts_menu', side_effect=RegistryError('Invalid auth path')):
            accounts.open_registry_accounts(ui)
        self.assertIn('Invalid auth path', repr(ui.seen))

    def test_private_image_install_uses_the_existing_native_lxc_wizard(self):
        auth = self.auth([self.account()])
        ui = UI(['account-0', 'install', 'default', None], ['ghcr.io/example/private:latest'])
        template = {'id': 'private-app', 'compatibility': {'automatic_install_candidate': True}}
        install = MagicMock()
        modules = {'proxmenux_oci.installer': SimpleNamespace(DEFAULT_MODE='default', ADVANCED_MODE='advanced'),
                   'proxmenux_oci.cli': SimpleNamespace(install_template=install)}
        with patch.object(accounts, 'image_template', return_value=template), \
                patch.object(accounts, 'registry_environment', contextlib.nullcontext):
            self.run_menu(ui, auth, modules)
        install.assert_called_once_with(ui, template, 'private-app', 'default')


if __name__ == '__main__':
    unittest.main()
