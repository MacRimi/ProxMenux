"""Real catalogue/wizard rendering, with host and installation effects forbidden."""
import copy
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(os.environ.get('OCI_I18N_TEST_ROOT', Path(__file__).resolve().parents[3]))
sys.path[:0] = [str(ROOT / 'oci/src'), str(ROOT / 'oci/remote'), str(ROOT / 'oci/tests')]
from proxmenux_oci import cli, i18n, installer, stack
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.converter import ConversionError
from proxmenux_oci.ui import UserCancelled
from test_advanced_flow_order import RecordingUI, addresses, storages


class CompleteUI(unittest.TestCase):
    def setUp(self):
        self.scope = ExitStack()
        self.addCleanup(self.scope.close)
        self.sk = json.loads((ROOT / 'lang/sk.json').read_text())
        self.catalog = Catalog(ROOT / 'oci')
        self.patch(i18n, '_language', 'sk')
        self.patch(i18n, '_cache', self.sk)
        self.patch(installer.host, 'storages', side_effect=storages)
        self.patch(installer.host, 'bridges', return_value=[{'iface': 'vmbr0', 'cidr': '192.0.2.10/24'}])
        self.patch(installer.host, 'timezone', return_value='Europe/Bratislava')
        self.patch(installer.host, 'gpus', return_value={'intel': [], 'amd': [], 'nvidia': False})
        self.patch(installer.access, 'ask_addresses', side_effect=addresses)
        self.patch(installer.access, 'ask_ipv4', return_value=('dhcp', None))
        self.effects = []
        for module, name in [(cli, '_install'), (cli, '_rclone_mount'), (cli, 'run_remote_install'),
                             (installer, 'run_remote_install'), (cli.images, 'offer_removal'),
                             (subprocess, 'run'), (subprocess, 'Popen'), (subprocess, 'check_output'),
                             (Path, 'write_text'), (Path, 'write_bytes'), (Path, 'unlink')]:
            self.effects.append(self.patch(module, name, side_effect=AssertionError('Forbidden effect: ' + name)))
        self.addCleanup(lambda: [effect.assert_not_called() for effect in self.effects])

    def patch(self, obj, name, *args, **kwargs):
        return self.scope.enter_context(patch.object(obj, name, *args, **kwargs))

    def test_search_no_match_uses_application_wording_and_never_installs(self):
        ui = Mock()
        ui.ask.return_value = 'fiction-no-such-app'
        cli._search(self.catalog, ui, [])
        self.assertEqual(ui.ask.call_args.args[0], 'Názov alebo časť popisu aplikácie')
        self.assertIn('Žiadna zhoda aplikácií', ui.message.call_args.args[0])
        ui.choose.assert_not_called()

    def test_immich_detail_translates_service_roles_without_changing_template(self):
        template = self.catalog.compose('immich')
        before = copy.deepcopy(template)
        text = cli._app_detail_text(self.catalog, self.catalog.find_item('immich'), template)
        self.assertIn('Strojové učenie', text)
        self.assertIn('Aplikácia', text)
        self.assertIn('Oficiálny obraz', text)
        self.assertNotIn('Machine learning', text)
        self.assertEqual(template, before)
        with patch.object(i18n, '_language', 'en'):
            self.assertIn('Machine learning', cli._app_detail_text(self.catalog, self.catalog.find_item('immich'), template))

    def test_missing_catalogue_entry_preserves_raw_error_and_localizes_cli(self):
        for language, expected in [('sk', "Aplikácia 'fiction-missing' nie je v indexe"),
                                    ('en', "The application 'fiction-missing' is not in the index")]:
            with self.subTest(language=language), patch.object(i18n, '_language', language):
                with self.assertRaisesRegex(ConversionError, "The application 'fiction-missing' is not in the index"):
                    self.catalog.find_item('fiction-missing')
                output = io.StringIO()
                with redirect_stdout(io.StringIO()), patch.object(sys, 'stderr', output), patch.object(cli, 'PROJECT_ROOT', ROOT / 'oci'):
                    self.assertEqual(cli.main(['show', 'fiction-missing']), 1)
                self.assertEqual(output.getvalue().strip(), 'ERROR: ' + expected)

    def test_missing_template_uses_existing_translation_and_keeps_identifier(self):
        self.patch(self.catalog, 'find_item', return_value={'id': 'fiction-missing'})
        with self.assertRaises(ConversionError) as caught:
            self.catalog.compose('fiction-missing')
        self.assertEqual(str(caught.exception), "No template is available for 'fiction-missing'")
        self.assertEqual(i18n.diagnostic(caught.exception), "Pre aplikáciu 'fiction-missing' nie je dostupná šablóna")

    def test_detail_cancel_and_escape_do_not_enter_install_or_rclone(self):
        for app in ('jellyfin', 'rclone', 'immich', 'suite-arr'):
            for escape in (False, True):
                with self.subTest(app=app, escape=escape):
                    ui = Mock()
                    ui.confirm.return_value = False
                    ui.detail_menu.return_value = None
                    if escape:
                        ui.detail_menu.side_effect = UserCancelled()
                    try:
                        cli._app_detail(self.catalog, ui, self.catalog.find_item(app))
                    except UserCancelled:
                        self.assertTrue(escape)

    def test_special_wizard_plans_are_identical_in_english_and_slovak(self):
        for app in ('immich', 'nextcloud-stack', 'paperless-ngx', 'tandoor'):
            for mode in (installer.DEFAULT_MODE, installer.ADVANCED_MODE):
                with self.subTest(app=app, mode=mode):
                    template = self.catalog.compose(app)
                    before = copy.deepcopy(template)
                    plan_sk = installer.build_deployment(template, RecordingUI(), mode)
                    with patch.object(i18n, '_language', 'en'):
                        plan_en = installer.build_deployment(template, RecordingUI(), mode)
                    self.assertEqual(plan_sk, plan_en)
                    self.assertEqual(template, before)
                    text = cli._deployment_summary_text(template, plan_sk)
                    self.assertNotIn('Consume/export:', text)
                    if app == 'paperless-ngx':
                        self.assertIn('Priečinky consume a export', text)

    def test_romm_optional_credentials_are_localized_but_variable_names_stay(self):
        ui = RecordingUI()
        ui.confirm = lambda text, default=False, **kwargs: (ui.asked.append(text) or text.startswith('Nastaviť IGDB'))
        ui.password = lambda text, **kwargs: (ui.asked.append(text) or 'fiction-secret')
        ui.ask = lambda text, default=None, **kwargs: (ui.asked.append(text) or (default if default is not None else 'fiction-value'))
        plan = installer.build_deployment(self.catalog.compose('romm'), ui, installer.ADVANCED_MODE)
        self.assertTrue(any('Tajný kľúč klienta IGDB' == text for text in ui.asked))
        self.assertFalse(any('IGDB Client Secret' == text for text in ui.asked))
        server = next(service for service in plan['services'] if service['name'] == 'romm')
        self.assertTrue(any(row['name'] == 'IGDB_CLIENT_SECRET' for row in server['deployment']['environment']))

    def test_tandoor_warning_keeps_negative_requirement_and_first_run_account(self):
        template = self.catalog.compose('tandoor')
        warning = i18n.translate(template['proxmox']['security_profile']['warning'])
        self.assertIn('nevyžaduje privilegovaný', warning)
        credentials = template['first_run']['credentials']
        self.assertTrue(any('Vygenerovaný účet správcu Tandoor' == i18n.translate(row['label']) for row in credentials))

    def test_documented_commands_paths_and_literals_remain_copyable(self):
        fragments = {
            'rsnapshot starts with the default configuration, which backs up /data into /.snapshots. Edit /config/rsnapshot.conf inside the container to set your own backup points, snapshot root and retention intervals.': ['/data', '/.snapshots', '/config/rsnapshot.conf'],
            'Each /request command needs a backend: add a [[backends]] block in the same file with the url and api_key of your Sonarr, Radarr or Seerr instance, then restart the container.': ['/request', '[[backends]]', 'url', 'api_key'],
            'Named accounts need private mode. Stop the container, set public: false in /config/config.js, start it again and create each user with: pct exec <CTID> -- env THELOUNGE_HOME=/config s6-setuidgid abc thelounge add <user>': ['public: false', 'pct exec <CTID> -- env THELOUNGE_HOME=/config s6-setuidgid abc thelounge add <user>'],
            'Certificate provider: empty for Let\'s Encrypt, zerossl for ZeroSSL': ["Let's Encrypt", 'zerossl', 'ZeroSSL'],
            'Libraries: /data/media/movies, /data/media/series and /data/media/music. Select them in the media server.': ['/data/media/movies', '/data/media/series', '/data/media/music'],
        }
        for source, tokens in fragments.items():
            with self.subTest(source=source):
                for token in tokens:
                    self.assertIn(token, i18n.translate(source))


if __name__ == '__main__':
    unittest.main()
