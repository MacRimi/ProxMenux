"""Single-container editor wording, real helper paths and no-apply boundaries."""
import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from test_modify_menu import MenuUI, record
from proxmenux_oci import i18n, installer, management, recreation
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.cli import _deployment_summary_text
from proxmenux_oci.converter import ConversionError
from proxmenux_oci.ui import UserCancelled

ROOT = Path(__file__).resolve().parents[2]


class EditorUI(MenuUI):
    def info(self, text):
        self.events.append(('info', text))

    def password(self, text, **kwargs):
        self.events.append(('password', text))
        return next(self.answers)


class SlovakEditorTests(unittest.TestCase):
    def setUp(self):
        translations = json.loads((ROOT / 'lang/sk.json').read_text())
        for mock in (patch.object(i18n, '_language', 'sk'),
                     patch.object(i18n, '_cache', translations)):
            mock.start()
            self.addCleanup(mock.stop)
        self.forbidden = []
        # The actual editor/helpers run, but any external action fails the test.
        for target, name in ((management, '_run_lifecycle'), (subprocess, 'run'),
                             (subprocess, 'Popen'), (subprocess, 'check_output'),
                             (Path, 'write_text'), (Path, 'write_bytes')):
            mock = patch.object(target, name, side_effect=AssertionError('editor performed an external action'))
            self.forbidden.append(mock.start())
            self.addCleanup(mock.stop)
        self.original = record()
        self.saved = copy.deepcopy(self.original)

    def tearDown(self):
        self.assertEqual(self.original, self.saved)
        for mock in self.forbidden:
            mock.assert_not_called()

    def text(self, ui):
        return '\n'.join(str(e[1:]) for e in ui.events)

    def test_cpu_minimum_then_invalid_number_can_be_corrected_and_discarded(self):
        ui = EditorUI(['cores', 'discard'], ['0', 'two', '3'], confirms=[True])
        self.assertIsNone(recreation.edit_recreation(self.original, ui))
        text = self.text(ui)
        self.assertIn('Počet jadier CPU', text)
        self.assertIn('Počet jadier: minimum 1', text)
        self.assertIn('Hodnota musí byť číslo:', text)
        self.assertIn('Zadajte hodnotu znova.', text)
        self.assertIn('Zahodiť nepoužité zmeny?', text)
        self.assertNotIn('private-test-secret', text)

    def test_ram_boundary_and_declined_review_do_not_apply_a_proposal(self):
        ui = EditorUI(['memory', 'apply', 'discard'], ['127', '128'],
                      reviews=[False], confirms=[True])
        self.assertIsNone(recreation.edit_recreation(self.original, ui))
        self.assertIn('RAM v MiB: minimum 128', self.text(ui))
        summary = next(e[1] for e in ui.events if e[0] == 'review')
        self.assertIn('128 MB RAM', summary)
        self.assertIn('rootfs 8 GB na local-zfs', summary)
        self.assertIn('vyrovnávacia pamäť obrazov na', summary)
        self.assertIn('neprivilegovaný LXC', summary)
        self.assertNotIn('private-test-secret', summary)

    def test_no_change_and_cancelled_section_keep_the_existing_record(self):
        for choices, answers in ((['apply'], []), (['cores', 'discard'], [UserCancelled()])):
            with self.subTest(choices=choices):
                ui = EditorUI(choices, answers)
                self.assertIsNone(recreation.edit_recreation(self.original, ui))
                self.assertFalse(any(e[0] == 'review' for e in ui.events))

    def test_environment_duplicate_is_an_error_not_an_instruction_to_duplicate(self):
        self.original['deployment']['environment'] *= 2
        self.saved = copy.deepcopy(self.original)
        ui = EditorUI([], ['PASSWORD', UserCancelled()], confirms=[True])
        result = recreation.edit_section(self.original, ui, 'environment')
        self.assertIs(result, self.original)
        self.assertIn('Premenná je v definícii kontajnera uvedená viackrát; pred úpravou ju skontrolujte', self.text(ui))

    def test_invalid_variable_name_and_value_are_rejected_before_draft_is_returned(self):
        for name, value, expected in (('INVALID NAME', None, 'Neplatný názov premennej'),
                                      ('VISIBLE', 'bad\x00value', 'Hodnota obsahuje nepodporovaný znak')):
            with self.subTest(name=name):
                answers = [name] + ([value] if value is not None else []) + [UserCancelled()]
                ui = EditorUI([], answers, confirms=[True, False])
                self.assertIs(recreation.edit_section(self.original, ui, 'environment'), self.original)
                self.assertIn(expected, self.text(ui))

    def test_new_secret_prompt_and_summary_do_not_expose_the_value(self):
        candidate = copy.deepcopy(self.original)
        ui = EditorUI([], ['NEW_SECRET', 'fixture-new-secret'], confirms=[True, True, False])
        recreation.edit_setting(candidate, ui, 'environment')
        self.assertIn(('password', 'Nová hodnota pre NEW_SECRET'), ui.events)
        self.assertNotIn('fixture-new-secret', self.text(ui))
        self.assertNotIn('fixture-new-secret', _deployment_summary_text(candidate['template'], candidate['deployment']))

    def test_storage_picker_reports_free_space_not_customs_duty(self):
        ui = EditorUI(['local-zfs'])
        rows = [{'storage': name, 'type': 'zfspool', 'avail': 8 * 1024**3}
                for name in ('local-zfs', 'other')]
        with patch.object(installer.host, 'storages', return_value=rows):
            self.assertEqual(installer.ask_storage(ui, 'Úložisko', 'rootdir', 'local-zfs'), 'local-zfs')
        self.assertIn('8 GB voľné', self.text(ui))

    def test_shared_host_path_prompt_changes_only_the_draft(self):
        candidate = copy.deepcopy(self.original)
        candidate['template']['proxmox']['installer_profile']['shared_directories'] = {
            'container_root': '/shares'}
        ui = EditorUI(['host-bind'], ['media', '/fixture/nonexistent'], confirms=[True, False])
        with patch.object(installer.os.path, 'isdir', return_value=False):
            recreation.edit_setting(candidate, ui, 'shares')
        self.assertIn('Cesta na hostiteľovi pre /shares/media', self.text(ui))
        self.assertEqual(candidate['deployment']['mounts'][-1]['source'], '/fixture/nonexistent')

    def test_extra_path_cannot_cover_system_directories(self):
        ui = EditorUI(['host-bind'], ['/etc', '/fixture/host', UserCancelled()],
                      confirms=[True, False])
        self.assertIs(recreation.edit_section(self.original, ui, 'paths'), self.original)
        self.assertIn('Vlastná cesta nemôže skryť systémové adresáre', self.text(ui))

    def test_network_gateway_explains_outbound_route(self):
        ui = EditorUI(['static'], ['vmbr0', '192.0.2.42/24', ''], confirms=[])
        with patch.object(installer.host, 'bridges', return_value=[]), \
                patch.object(installer.host, 'address_answers', return_value=False):
            recreation.edit_setting(copy.deepcopy(self.original), ui, 'network')
        self.assertIn('Brána IPv4 (prázdne = bez odchádzajúcej trasy)', self.text(ui))

    def test_incompatible_docker_mods_are_localized_without_gpu_or_image_probe(self):
        self.original['template']['proxmox']['installer_profile']['hardware_acceleration'] = {
            'profiles': [{'id': 'gpu', 'environment': [{'name': 'DOCKER_MODS', 'value': 'mod'}]}]}
        self.saved = copy.deepcopy(self.original)
        ui = EditorUI([])
        self.assertIs(recreation.edit_section(self.original, ui, 'acceleration'), self.original)
        self.assertIn('Docker Mods sú dostupné iba pre kompatibilné obrazy LinuxServer', self.text(ui))

    def test_duplicate_usb_device_is_rejected_without_attaching_it(self):
        self.original['deployment']['devices'] = [{'host_path': '/dev/ttyACM0'}]
        self.saved = copy.deepcopy(self.original)
        ui = EditorUI(['usb'], ['/dev/ttyACM0', UserCancelled()], confirms=[True])
        with patch.object(installer.host, 'usb_devices', return_value=[]):
            self.assertIs(recreation.edit_section(self.original, ui, 'devices'), self.original)
        self.assertIn('Toto zariadenie je už pripojené', self.text(ui))

    def catalog_refresh(self, error=None, latest=None):
        candidate = copy.deepcopy(self.original)
        candidate['template']['container_contract']['image']['repository'] = 'example/app'
        ui = EditorUI(['managed-volume'], ['local-zfs', '4'], confirms=[True])
        index = {'applications': [{'id': 'example', 'template_id': 'example-app'}]}
        with patch.object(Catalog, 'load_index', return_value=index), \
                patch.object(Catalog, 'compose', side_effect=error, return_value=latest):
            recreation.refresh_template(candidate, ui)
        return candidate, ui

    def test_required_catalog_path_has_a_clear_persistence_prompt(self):
        latest = copy.deepcopy(self.original['template'])
        latest['container_contract']['image']['repository'] = 'example/app'
        latest['container_contract']['volumes'] = [{'id': 'new', 'container_path': '/new-data'}]
        candidate, ui = self.catalog_refresh(latest=latest)
        self.assertIn('Aktuálna šablóna vyžaduje nové trvalé úložisko pre cestu: /new-data', self.text(ui))
        self.assertIn('Nové úložisko bude prázdne; existujúce údaje sa doň automaticky neprenesú.', self.text(ui))
        self.assertIn('Trvalé úložisko pre /new-data', self.text(ui))
        self.assertEqual(candidate['deployment']['mounts'][-1]['container_path'], '/new-data')

    def test_template_identity_change_is_a_localized_migration_error(self):
        latest = copy.deepcopy(self.original['template'])
        latest['container_contract']['image']['repository'] = 'different/app'
        with self.assertRaisesRegex(ValueError, 'Aktuálna šablóna mení identitu šablóny alebo repozitár obrazu; je potrebná výslovná migrácia'):
            self.catalog_refresh(latest=latest)

    def test_real_catalog_missing_file_error_is_localized_only_in_editor(self):
        index = {'applications': [{'id': 'example', 'template_id': 'example-app'}]}
        item = dict(index['applications'][0], template_family='curated-profile', curated_path='absent-template.json')
        with patch.object(Catalog, 'load_index', return_value=index), patch.object(Catalog, 'find_item', return_value=item):
            with self.assertRaisesRegex(ConversionError, "No template is available for 'example'"):
                Catalog(ROOT / 'oci').compose('example')
            with self.assertRaisesRegex(ConversionError, "Pre aplikáciu 'example' nie je dostupná šablóna"):
                recreation.refresh_template(copy.deepcopy(self.original), EditorUI([]))

    def test_real_schema_diagnostic_preserves_field_paths_and_exception_type(self):
        with self.assertRaises(ConversionError) as raw:
            Catalog(ROOT / 'oci').validate({})
        self.assertTrue(str(raw.exception).startswith('La plantilla generada no cumple el esquema:'))
        details = str(raw.exception).split(':', 1)[1]
        with self.assertRaises(ConversionError) as localized:
            self.catalog_refresh(error=raw.exception)
        self.assertEqual(str(localized.exception), 'Vygenerovaná šablóna nezodpovedá schéme:' + details)

    def test_missing_index_entry_preserves_the_application_identifier(self):
        with self.assertRaisesRegex(ConversionError, "Aplikácia 'example' nie je v indexe"):
            self.catalog_refresh(error=ConversionError("The application 'example' is not in the index"))

    def test_english_missing_translation_and_unknown_diagnostics_are_preserved(self):
        for message in ("No template is available for 'example'", "The application 'example' is not in the index",
                        'La plantilla generada no cumple el esquema: field: required', 'unknown technical failure'):
            for language, cache in (('en', {}), ('sk', {})):
                with self.subTest(message=message, language=language), \
                        patch.object(i18n, '_language', language), patch.object(i18n, '_cache', cache):
                    with self.assertRaises(ConversionError) as error:
                        self.catalog_refresh(error=ConversionError(message))
                    self.assertEqual(str(error.exception), message)


if __name__ == '__main__':
    unittest.main()
