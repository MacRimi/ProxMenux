"""Exercise the multi-container editor in Slovak without applying a change."""
from contextlib import redirect_stderr
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'oci/src'), str(ROOT / 'oci/remote')]
from proxmenux_oci import host, i18n, installer, management, stack_recreation as editor
import oci_immich_recognition as recognition
import oci_instances as instances
import oci_stack_modify as modify
import oci_ui

CONFIG = {
    'rootfs': 'fixture:vm-999991-disk-0,size=8G',
    'mp0': 'fixture:vm-999991-disk-1,mp=/opt/recipes/mediafiles,size=8G',
    'mp1': 'fixture:vm-999991-disk-2,mp=/extra,size=4G',
    'mp2': '/fixture/shared,mp=/shared',
    'dev0': 'path=/dev/ttyACM7,mode=0660',
}


class StackEditorSlovakTests(unittest.TestCase):
    def setUp(self):
        self.translations = json.loads((ROOT / 'lang/sk.json').read_text())
        for module in (i18n, oci_ui):
            for name, value in (('_language', 'sk'), ('_cache', self.translations)):
                item = patch.object(module, name, value)
                item.start()
                self.addCleanup(item.stop)
        self.member = {'vmid': 999991, 'stack_member': {'name': 'application'},
                       'deployment': {'replay_profile': {'adapter': 'install_tandoor_stack.sh',
                                                         'role': 'application'}}}
        self.primary = {'vmid': 999990, 'stack': {'members': [self.member,
            {'vmid': 999992, 'deployment': {'replay_profile': {'role': 'database'}}}]}}
        self.original = copy.deepcopy(self.primary)
        self.ui = Mock()
        self.ui.choose.return_value = None
        self.ui.confirm.return_value = False
        self.ui.review.return_value = False
        self.ui.checklist.side_effect = lambda text, options, defaults: list(defaults)
        config = patch.object(editor, '_config', return_value=CONFIG)
        config.start()
        self.addCleanup(config.stop)
        self.forbidden = []
        for target, name in ((subprocess, 'run'), (subprocess, 'Popen'),
                             (subprocess, 'check_output'), (Path, 'write_text'),
                             (Path, 'write_bytes'), (instances, 'write'),
                             (instances, 'command'), (modify, 'apply'),
                             (recognition, 'apply'), (recognition, 'configure'),
                             (management, '_run_lifecycle')):
            item = patch.object(target, name, side_effect=AssertionError('Forbidden effect: ' + name))
            self.forbidden.append(item.start())
            self.addCleanup(item.stop)
        self.lifecycle = Mock(side_effect=AssertionError('Editor called lifecycle'))
        self.forbidden.append(self.lifecycle)

    def tearDown(self):
        self.assertEqual(self.primary, self.original)
        for callback in self.forbidden:
            callback.assert_not_called()

    def shown(self):
        return '\n'.join(str(call) for call in self.ui.mock_calls)

    def immich(self, acceleration='cpu'):
        self.member['deployment']['replay_profile'] = {
            'adapter': 'install_immich_stack.sh', 'role': 'machine-learning'}
        self.member['deployment']['machine_learning'] = {'acceleration': acceleration}
        self.original = copy.deepcopy(self.primary)
        return self.member

    def changes(self, **values):
        return {'add_mounts': [], 'remove_mounts': [], 'add_devices': [],
                'remove_devices': [], **values}

    def test_editor_only_offers_extra_paths_and_leaves_database_out(self):
        self.assertFalse(editor.modify_stack(ROOT / 'oci', self.ui, self.primary, self.lifecycle))
        shown = self.shown()
        self.assertIn('odznačené sa odstránia po potvrdení', shown)
        self.assertIn('odznačené sa odpoja po potvrdení', shown)
        options = self.ui.checklist.call_args_list[0].args[1]
        self.assertEqual([path for path, label in options], ['/extra', '/shared'])
        self.assertNotIn('zásobník', shown)

    def test_declining_volume_deletion_keeps_it_and_only_detaches_host_path_in_draft(self):
        self.ui.checklist.side_effect = [[], ['/dev/ttyACM7']]
        self.assertFalse(editor.modify_stack(ROOT / 'oci', self.ui, self.primary, self.lifecycle))
        warning = self.ui.confirm.call_args_list[0].args[0]
        self.assertIn('trvalé úložisko aj všetky údaje v ňom', warning)
        self.assertIn('/extra', warning)
        summary = self.ui.review.call_args.args[0]
        self.assertIn('- /shared', summary)
        self.assertNotIn('- /extra', summary)
        self.assertIn('Spustený kontajner sa reštartuje', summary)
        self.assertIn('zastavený zostane zastavený', summary)
        self.assertIn('Databáza ani ostatné kontajnery sa nemenia', summary)

    def test_declined_review_describes_confirmed_volume_deletion_without_performing_it(self):
        self.ui.checklist.side_effect = [[], []]
        self.ui.confirm.side_effect = [True, False, False]
        self.assertFalse(editor.modify_stack(ROOT / 'oci', self.ui, self.primary, self.lifecycle))
        self.assertIn('- /extra', self.ui.review.call_args.args[0])
        self.assertIn('vymažú aj údaje', self.ui.review.call_args.args[0])
        self.assertEqual(self.ui.review.call_args.kwargs['question'], 'Použiť tieto zmeny?')

    def test_member_selection_cancels_before_any_configuration_read(self):
        other = copy.deepcopy(self.member)
        other['vmid'] = 999993
        self.primary['stack']['members'].append(other)
        self.original = copy.deepcopy(self.primary)
        with patch.object(editor, '_config') as read:
            self.assertFalse(editor.modify_stack(ROOT / 'oci', self.ui, self.primary, self.lifecycle))
        read.assert_not_called()
        self.assertEqual(self.ui.choose.call_args.args[0], 'Kontajner, ktorý chcete upraviť')

    def test_missing_member_error_uses_application_language(self):
        self.primary['stack']['members'] = []
        self.original = copy.deepcopy(self.primary)
        self.assertFalse(editor.modify_stack(ROOT / 'oci', self.ui, self.primary, self.lifecycle))
        self.assertIn('Pre túto aplikáciu nie je uložený zoznam kontajnerov.', self.shown())
        self.assertIn('Správa OCI aplikácie s viacerými kontajnermi', self.shown())

    def test_immich_action_menu_identifies_recognition_instead_of_video_transcoding(self):
        self.immich()
        self.assertFalse(editor.modify_stack(ROOT / 'oci', self.ui, self.primary, self.lifecycle))
        self.assertIn('Vybrať CPU alebo GPU pre rozpoznávanie', self.shown())
        self.assertIn('Upraviť pripojené cesty a zariadenia', self.shown())

    def test_cpu_only_host_explains_why_no_gpu_choice_is_offered(self):
        member = self.immich()
        with patch.object(host, 'gpus', return_value={'intel': [], 'amd': [], 'nvidia': []}):
            self.assertFalse(editor.change_recognition(ROOT / 'oci', self.ui, self.primary,
                                                       member, self.lifecycle))
        self.assertIn('nenašla použiteľná grafická karta', self.shown())
        self.assertIn('Rozpoznávanie zostáva na CPU.', self.shown())
        self.ui.review.assert_not_called()

    def test_gpu_review_explains_whole_application_update_and_kept_data_before_no(self):
        member = self.immich()
        self.ui.choose.return_value = 'openvino'
        found = {'intel': ['/dev/dri/renderD128'], 'amd': [], 'nvidia': []}
        with patch.object(host, 'gpus', return_value=found):
            self.assertFalse(editor.change_recognition(ROOT / 'oci', self.ui, self.primary,
                                                       member, self.lifecycle))
        choices = self.ui.choose.call_args.args[1]
        self.assertEqual(choices, [('cpu', 'CPU'), ('openvino', 'Intel GPU')])
        text = self.ui.review.call_args.args[0]
        for fragment in ('CPU → Intel GPU', 'pamäť modelov, knižnica a databáza sa zachovajú',
                         'Celá aplikácia sa zastaví a aktualizuje', 'ProxMenux sa pokúsi obnoviť',
                         'ponuky správy OCI'):
            self.assertIn(fragment, text)
        self.assertEqual(self.ui.review.call_args.kwargs['question'],
                         'Použiť zvolený CPU/GPU pre rozpoznávanie?')

    def test_unchanged_recognition_does_not_open_confirmation_or_apply(self):
        member = self.immich()
        self.ui.choose.return_value = 'cpu'
        with patch.object(editor, 'recognition_choices', return_value=[('cpu', 'CPU', {}),
                                                                      ('cuda', 'NVIDIA GPU', {})]):
            self.assertFalse(editor.change_recognition(ROOT / 'oci', self.ui, self.primary,
                                                       member, self.lifecycle))
        self.ui.review.assert_not_called()
        self.assertIn('Nič sa nezmenilo.', self.shown())

    def test_experimental_rocm_can_be_declined_before_final_review(self):
        member = self.immich()
        self.ui.choose.return_value = 'rocm'
        choices = [('cpu', 'CPU', {}), ('rocm', 'AMD GPU', {'experimental': True})]
        with patch.object(editor, 'recognition_choices', return_value=choices), \
                patch.object(host, 'amd_gpu_name', return_value='Fixture AMD'):
            self.assertFalse(editor.change_recognition(ROOT / 'oci', self.ui, self.primary,
                                                       member, self.lifecycle))
        text = self.ui.confirm.call_args.args[0]
        self.assertIn('ROCm túto grafickú kartu oficiálne nepodporuje.', text)
        self.assertIn('GPU prestať reagovať', text)
        self.assertIn('bez preinštalovania', text)
        self.assertIn('Použiť napriek tomu GPU s ROCm?', text)
        self.assertFalse(self.ui.confirm.call_args.args[1])
        self.ui.review.assert_not_called()

    def test_backend_invalid_volume_size_preserves_path_and_fails_before_mutation(self):
        mount = {'type': 'managed-volume', 'container_path': '/new-data',
                 'size_gb': 0, 'source': 'fixture'}
        with patch.object(modify, 'entries', return_value={}):
            with self.assertRaisesRegex(ValueError, 'Neplatná veľkosť trvalého úložiska: /new-data'):
                modify.validate(999991, self.changes(add_mounts=[mount]))

    def test_backend_unsupported_device_explains_separate_profile_before_mutation(self):
        device = {'kind': 'character-device', 'host_path': '/dev/sda'}
        with patch.object(modify, 'entries', return_value={}):
            with self.assertRaisesRegex(ValueError, 'NVIDIA a celé stromy zariadení vyžadujú iný profil: /dev/sda'):
                modify.validate(999991, self.changes(add_devices=[device]))

    def test_root_error_is_localized_without_starting_the_operation(self):
        with patch.object(modify.os, 'geteuid', return_value=1000), \
                patch.object(sys, 'argv', ['fixture', '999991', '--changes', '/not-read.json']), \
                redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as result:
                modify.main()
        self.assertEqual(result.exception.code, 2)
        self.assertIn('Vyžadujú sa oprávnenia používateľa root', output.getvalue())
        self.assertNotIn('required', output.getvalue())

    def test_invalid_recognition_profile_is_localized_without_any_gpu_probe(self):
        with self.assertRaisesRegex(ValueError, 'Profil GPU pre Immich nebol overený'):
            recognition.validate('unknown', None, None)

    def test_recognition_errors_distinguish_unchanged_from_incomplete_operation(self):
        incomplete = RuntimeError('fixture diagnostic')
        incomplete.recognition_kept = False
        for error, expected in ((ValueError('fixture diagnostic'), 'Spôsob rozpoznávania v Immichu sa nezmenil:'),
                                (incomplete, 'Zmenu CPU/GPU pre rozpoznávanie v Immichu sa nepodarilo dokončiť:')):
            with self.subTest(error=type(error).__name__), \
                    patch.object(recognition.os, 'geteuid', return_value=0), \
                    patch.object(sys, 'argv', ['fixture', '999990', '--acceleration', 'cpu']), \
                    patch.object(recognition, 'change', side_effect=error), \
                    patch.object(recognition, 'msg_error') as message:
                self.assertEqual(recognition.main(), 1)
                self.assertEqual(message.call_args.args[0], expected + ' fixture diagnostic')

    def test_english_and_missing_translation_fallback_preserve_source_text(self):
        changes = self.changes(remove_mounts=['/extra'])
        for language, cache in (('en', self.translations), ('sk', {})):
            with self.subTest(language=language, empty_cache=not cache), \
                    patch.object(i18n, '_language', language), patch.object(i18n, '_cache', cache):
                text = editor.summary(self.member, changes)
                self.assertIn('A running container is restarted', text)
                self.assertIn('- /extra', text)


if __name__ == '__main__':
    unittest.main()
