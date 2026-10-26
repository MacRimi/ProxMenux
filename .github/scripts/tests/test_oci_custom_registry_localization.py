"""Exercise the native custom-image and registry UI with the real EN/SK lookup."""
import json
from pathlib import Path
import runpy
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'oci/src'))
from proxmenux_oci import custom, i18n, registry_accounts as accounts, registry_auth as auth
from proxmenux_oci.ui import UserCancelled

COMPOSE = 'services:\n  app:\n    image: ghcr.io/owner/app:latest\n'


class UI:
    def __init__(self, choices=(), answers=(), confirms=()):
        self.choices = iter(choices)
        self.answers = iter(answers)
        self.confirms = iter(confirms)
        self.seen = []

    def choose(self, text, options, default=None, **kwargs):
        self.seen.append((text, options, kwargs))
        return next(self.choices)

    def ask(self, text, default=None, **kwargs):
        self.seen.append(text)
        return next(self.answers)

    def password(self, text):
        self.seen.append(text)
        raise UserCancelled(text)

    def confirm(self, text, default=False, **kwargs):
        self.seen.append((text, default))
        return next(self.confirms)

    def review(self, text, title=None, **kwargs):
        self.seen.append((text, title, kwargs))
        return False

    def message(self, text, title=None):
        self.seen.append((text, title))

    info = message


class CustomRegistryLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / 'lang').mkdir()
        (self.base / 'config.json').write_text('{"language":"sk"}')
        (self.base / 'lang/sk.json').write_bytes((ROOT / 'lang/sk.json').read_bytes())
        for name, value in [('BASE_DIR', self.base), ('_language', None), ('_cache', None)]:
            item = patch.object(i18n, name, value)
            item.start()
            self.addCleanup(item.stop)
        # Any unmocked subprocess, network fetch or installation is a failure.
        self.run = self.guard(custom.subprocess, 'run')
        self.network = self.guard(custom.urllib.request, 'urlopen')
        self.install = self.guard(custom, 'install_template')

    def guard(self, module, name):
        item = patch.object(module, name, side_effect=AssertionError('Forbidden effect: ' + name))
        mock = item.start()
        self.addCleanup(item.stop)
        return mock

    def no_effects(self):
        self.run.assert_not_called()
        self.network.assert_not_called()
        self.install.assert_not_called()

    def manager(self):
        return SimpleNamespace(path=Path('/fixture/auth.json'),
            accounts=MagicMock(return_value=[{'registry': 'ghcr.io', 'account': 'owner',
                'method': 'Používateľské meno / token', 'status': 'Saved'}]),
            login=MagicMock(), logout=MagicMock())

    def menu(self, ui, manager):
        with patch.object(accounts, 'require_root'):
            accounts.registry_accounts_menu(ui, auth=manager)

    def test_dynamic_blockers_are_extracted_and_rendered_in_slovak(self):
        expected = {
            'multi-service-compose': 'definuje viac než jeden obraz',
            'native-multi-lxc-orchestrator-not-yet-implemented': 'definuje viac než jeden obraz',
            'top-level-configs': 'používa nastavenia Compose configs, ktoré tu nemajú ekvivalent',
            'devices-format': 'požadované zariadenia sú zadané v nepodporovanom formáte',
            'healthcheck-format': 'kontrola stavu je zadaná v nepodporovanom formáte',
            'stop-grace-period-format': 'časový limit zastavenia je zadaný v nepodporovanom formáte',
            'shm-size-format': 'veľkosť zdieľanej pamäte je zadaná v nepodporovanom formáte',
            'ulimits-format-or-resource': 'požadované limity systémových prostriedkov nemožno uplatniť',
            'mem-limit-format-or-below-proxmox-minimum': 'požadovaný limit pamäte nemožno uplatniť',
            'mem-limit-deploy-consistency-review': 'požaduje dva rozdielne limity pamäte',
        }
        extractor = runpy.run_path(str(ROOT / '.github/scripts/build_translation_cache.py'))
        extracted = extractor['extract_python_texts']([ROOT / 'oci/src'])
        self.assertTrue(set(custom.BLOCKER_TEXTS.values()) <= set(extracted))
        for code, message in expected.items():
            with self.subTest(code=code):
                self.assertEqual(custom.blocker_text('service:app:' + code), message)
        self.assertEqual(custom.blocker_text('unrecognized:raw-code'), 'unrecognized:raw-code')
        self.no_effects()

    def test_cancelled_source_menu_is_translated_without_reading_an_image(self):
        ui = UI([None])
        with self.assertRaises(UserCancelled) as caught:
            custom.explore(ui)
        self.assertEqual(str(caught.exception), 'Výber obrazu bol zrušený')
        self.assertIn('Obraz, ktorý nie je v katalógu', repr(ui.seen))
        self.assertIn('Len odkaz na obraz bez súboru Compose', repr(ui.seen))
        self.no_effects()

    def test_invalid_compose_inputs_reach_localized_error_before_registry_or_install(self):
        cases = [
            ('services: {}', 'Súbor Compose neobsahuje žiadnu službu'),
            ('services: [', 'Súbor Compose nie je platný YAML:'),
            (COMPOSE + '    environment: 42\n', 'Položka environment'),
            (COMPOSE + '    volumes: {}\n', 'Položka volumes'),
            (COMPOSE + '    ports: invalid\n', 'Položka ports'),
            (COMPOSE + '    ports: [invalid]\n', 'Neplatný port'),
            (COMPOSE + '    volumes: [relative:relative]\n', 'Neplatná cesta dátového úložiska'),
            (COMPOSE + 'x-casaos:\n  main: missing\n', 'Položka x-casaos.main'),
        ]
        for text, expected in cases:
            with self.subTest(text=text), patch.object(custom, 'read_definition', return_value=(text, 'fixture')), \
                    self.assertRaises(custom.ConversionError) as caught:
                custom.explore(UI())
            self.assertIn(expected, str(caught.exception))
        self.no_effects()

    def test_converter_raw_contract_and_english_ui_are_preserved(self):
        bad = COMPOSE + '    ports: [invalid]\n'
        with self.assertRaises(custom.ConversionError) as raw:
            custom.template_from_compose(bad)
        self.assertEqual(str(raw.exception), "Puerto no valido: 'invalid'")
        with patch.object(i18n, '_language', 'en'), \
                patch.object(custom, 'read_definition', return_value=(bad, 'fixture')), \
                self.assertRaises(custom.ConversionError) as ui_error:
            custom.explore(UI())
        self.assertEqual(str(ui_error.exception), str(raw.exception))
        self.no_effects()

    def test_conversion_message_retains_literal_diagnostic_data_and_unknown_fallback(self):
        detail = " {'target': '<path>{literal}\\á'}"
        message = custom.conversion_message(custom.ConversionError('Ruta de volumen no valida:' + detail))
        self.assertEqual(message, 'Neplatná cesta dátového úložiska v súbore Compose:' + detail)
        unknown = 'unknown <diagnostic> {literal}'
        self.assertEqual(custom.conversion_message(custom.ConversionError(unknown)), unknown)
        self.no_effects()

    def test_all_legacy_converter_diagnostics_have_slovak_ui_and_unchanged_english(self):
        messages = [
            'environment must be a list or a mapping', 'volumes must be a list', 'ports must be a list',
            'The CasaOS Compose file has no services', 'The CasaOS document is not a Compose mapping',
            'The Compose file has no x-casaos metadata', 'x-casaos.main no identifica un servicio valido',
            'The main CasaOS service declares no image', 'Ruta de volumen no valida: /data',
            'Puerto no valido: invalid', 'Cannot normalise the CasaOS identifier: ???',
            'Docker Compose CasaOS no valido: fixture',
        ]
        for text in messages:
            with self.subTest(text=text):
                self.assertNotEqual(custom.conversion_message(custom.ConversionError(text)), text)
                with patch.object(i18n, '_language', 'en'):
                    self.assertEqual(custom.conversion_message(custom.ConversionError(text)), text)
        self.no_effects()

    def test_custom_review_cancel_keeps_installation_disabled(self):
        ui = UI()
        with patch.object(custom, 'read_definition', return_value=(COMPOSE, 'vloženého súboru Compose')), \
                patch.object(custom, 'registry_report', return_value=(True, 'Dostupný obraz')):
            custom.explore(ui)
        self.assertIn('Nainštalovať tento obraz?', repr(ui.seen))
        self.assertIn('Obraz:', repr(ui.seen))
        self.assertIn('ghcr.io/owner/app:latest', repr(ui.seen))
        self.no_effects()

    def test_unavailable_image_explains_registry_accounts_without_authentication_or_install(self):
        ui = UI()
        with patch.object(custom, 'read_definition', return_value=(COMPOSE, 'fixture')), \
                patch.object(custom, 'registry_report', return_value=(False, 'Nedostupný obraz')), \
                patch.object(custom, '_registry_refused', return_value=False), \
                patch.object(accounts, 'offer_sign_in') as offer:
            custom.explore(ui)
        self.assertIn('prihláste cez Účty registrov', repr(ui.seen))
        offer.assert_not_called()
        self.no_effects()

    def test_registry_metadata_dialog_uses_image_and_digest_and_retains_values(self):
        manager = self.manager()
        ui = UI(['account-0', 'inspect', None], ['ghcr.io/owner/app:latest'])
        metadata = dict(architecture='amd64', version='<v>{literal}', size=1024, digest='sha256:' + 'a'*64)
        with patch.object(accounts, 'inspect_registry_image', return_value=metadata) as inspect:
            self.menu(ui, manager)
        inspect.assert_called_once_with('ghcr.io/owner/app:latest')
        rendered = repr(ui.seen)
        for value in ('Prístup k obrazu bol potvrdený.', 'Digest: sha256:', '<v>{literal}', 'Účty registrov'):
            self.assertIn(value, rendered)
        self.assertNotIn('obráz', rendered)
        manager.login.assert_not_called()
        manager.logout.assert_not_called()
        self.no_effects()

    def test_credential_help_retains_permissions_and_no_encryption_claim(self):
        manager = self.manager()
        ui = UI(['storage', None])
        self.menu(ui, manager)
        rendered = repr(ui.seen)
        for value in ('root', '700', '600', 'base64', 'nie sú šifrované', 'každý uzol klastra', '/fixture/auth.json'):
            self.assertIn(value, rendered)
        manager.login.assert_not_called()
        manager.logout.assert_not_called()
        self.no_effects()

    def test_cancelled_password_and_declined_logout_do_not_change_accounts(self):
        for ui in (UI(['add', None], ['ghcr.io', 'owner']), UI(['account-0', 'logout', None], confirms=[False])):
            manager = self.manager()
            self.menu(ui, manager)
            manager.login.assert_not_called()
            manager.logout.assert_not_called()
        self.no_effects()

    def test_mismatched_registry_is_rejected_before_download(self):
        manager = self.manager()
        ui = UI(['account-0', 'download', None], ['quay.io/owner/app:latest'])
        with patch.object(accounts, 'download_registry_image') as download:
            self.menu(ui, manager)
        download.assert_not_called()
        self.assertIn('Zadajte obraz z tohto registra.', repr(ui.seen))
        self.no_effects()

    def test_declined_private_image_signin_does_not_even_construct_auth_manager(self):
        ui = UI(confirms=[False])
        with patch.object(accounts, 'RegistryAuth') as manager, patch.object(accounts, 'require_root') as root:
            self.assertFalse(accounts.offer_sign_in(ui, 'ghcr.io/owner/app:latest'))
        manager.assert_not_called()
        root.assert_not_called()
        self.assertIn('Prihlásiť sa teraz?', repr(ui.seen))
        self.no_effects()

    def test_registry_error_classes_hide_untrusted_remote_data_in_both_languages(self):
        cases = [('status code: 429', 'obmedzuje počet požiadaviek'),
                 ('requested access to the resource is denied', 'odmietol prístup'),
                 ('manifest unknown', 'Obraz alebo tag'),
                 ('unsupported manifest', 'metadáta obrazu'),
                 ('docker-credential-helper', 'správu prihlasovacích údajov'),
                 ('unknown failure', 'Obraz sa nepodarilo načítať')]
        for language in ('sk', 'en'):
            for error, expected in cases:
                with self.subTest(language=language, error=error), patch.object(i18n, '_language', language):
                    message = auth.registry_error('registry.test:5000', error + ' REMOTE_PRIVATE_VALUE')
                    self.assertNotIn('REMOTE_PRIVATE_VALUE', message)
                    if language == 'sk':
                        self.assertIn(expected, message)
                    if 'credential' not in error:
                        self.assertIn('registry.test:5000', message)
        self.no_effects()


if __name__ == '__main__':
    unittest.main()
