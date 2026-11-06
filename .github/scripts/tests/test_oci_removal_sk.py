"""Actual removal UI/guards in SK and EN; real host effects are forbidden."""
from contextlib import nullcontext
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'oci/src'), str(ROOT / 'oci/remote')]
from proxmenux_oci import i18n, management
from proxmenux_oci.ui import UserCancelled
import oci_instances as instances
import oci_remove as removal
import oci_ui


class RemovalSlovakTests(unittest.TestCase):
    def setUp(self):
        cache = json.loads((ROOT / 'lang/sk.json').read_text())
        for module in (i18n, oci_ui):
            for name, value in (('_language', 'sk'), ('_cache', cache)):
                p = patch.object(module, name, value)
                p.start(); self.addCleanup(p.stop)
        self.records = {}
        self.make_records(2)
        self.read = self.start(instances, 'read', side_effect=lambda root, vmid: self.records[vmid])
        self.start(management, '_selected_configuration', side_effect=self.config)
        self.bridge = self.start(removal, 'bridge_in_use', return_value=False)
        self.ui = Mock()
        self.ui.review.return_value = False
        self.forbidden = []
        for module, name in ((subprocess, 'run'), (subprocess, 'Popen'), (subprocess, 'check_output'),
                             (Path, 'write_text'), (Path, 'write_bytes'), (Path, 'unlink'),
                             (removal.shutil, 'rmtree'), (instances, 'write'), (instances, 'command'),
                             (management, '_run_lifecycle'), (removal, 'run'),
                             (removal, 'remove_host_state'), (removal.oci_console, 'remove_log'),
                             (removal, 'release_bridge'), (removal, 'remove_owned_host_firewall'),
                             (removal, 'release_shared_host_files'), (removal.work_backup, 'forget'),
                             (removal.image_cache, 'prune')):
            self.forbidden.append(self.start(module, name, side_effect=AssertionError('Forbidden effect: ' + name)))

    def start(self, module, name, **kwargs):
        p = patch.object(module, name, **kwargs)
        result = p.start(); self.addCleanup(p.stop)
        return result

    def make_records(self, count):
        self.records.clear()
        for offset in range(count):
            vmid = 999990 + offset
            self.records[vmid] = {'vmid': vmid, 'installation_id': 'fixture-' + str(vmid),
                'template': {'catalog_ui': {'title': 'Fixture App'}},
                'deployment': {'mounts': [{'type': 'host-bind', 'source': '/fixture/saved',
                                          'container_path': '/saved'}]}}
            if offset:
                self.records[vmid]['stack_member'] = {'primary_vmid': 999990}
        if count > 1:
            self.records[999990]['stack'] = {'members': [{'vmid': vmid} for vmid in self.records],
                'deployment': {'network': {'private_bridge': 'vmbr999', 'private_subnet': '10.77.99.0/24'}}}
        self.records[999990]['deployment']['host_firewall'] = {'port': 8080}
        self.original = copy.deepcopy(self.records)

    def config(self, vmid):
        return (f'hostname: fixture-{vmid}\nrootfs: fixture:vm-{vmid}-disk-0,size=8G\n'
                f'mp0: fixture:vm-{vmid}-disk-1,mp=/data,size=16G\n'
                'mp1: /fixture/shared,mp=/shared\n').encode()

    def tearDown(self):
        self.assertEqual(self.records, self.original)
        for effect in self.forbidden:
            effect.assert_not_called()

    def test_single_summary_separates_deleted_disks_and_retained_host_paths(self):
        self.make_records(1)
        text = management._removal_summary(ROOT / 'oci', 999990)
        self.assertIn('Kontajnery určené na odstránenie:', text)
        self.assertIn('Údaje kontajnera určené na vymazanie:', text)
        self.assertIn('/data (16G)', text)
        kept = text.split('Cesty hostiteľa nájdené')[1]
        self.assertIn('/fixture/shared', kept); self.assertIn('/fixture/saved', kept)
        self.assertNotIn('/fixture/shared', text.split('Cesty hostiteľa nájdené')[0])
        self.assertNotIn('súkromnej siete:', text)

    def test_primary_summary_counts_are_grammatical_for_two_three_and_five(self):
        for count in (2, 3, 5):
            with self.subTest(count=count):
                self.make_records(count)
                text = management._removal_summary(ROOT / 'oci', 999990)
                self.assertIn(f'Počet kontajnerov aplikácie Fixture App: {count}.', text)
                self.assertIn('Všetky sú určené na odstránenie.', text)
                for vmid in self.records:
                    self.assertIn(f'CT {vmid}', text)

    def test_member_summary_warns_that_entire_application_is_selected(self):
        text = management._removal_summary(ROOT / 'oci', 999991)
        self.assertIn('CT 999991 patrí do aplikácie Fixture App (počet kontajnerov: 2).', text)
        self.assertIn('odstránenie celej aplikácie', text)
        self.assertNotIn('nádob', text)

    def test_free_bridge_is_only_targeted_and_firewall_removal_is_conditional(self):
        text = management._removal_summary(ROOT / 'oci', 999990)
        self.assertIn('Súkromná sieť určená na uvoľnenie, ak ju nepoužíva iná VM alebo iný CT: vmbr999', text)
        self.assertIn('Môže sa odstrániť aj zodpovedajúce spravované pravidlo firewallu hostiteľa.', text)

    def test_shared_bridge_is_kept_and_not_reported_as_released(self):
        self.bridge.return_value = True
        text = management._removal_summary(ROOT / 'oci', 999990)
        self.assertIn('Súkromná sieť zachovaná', text)
        self.assertNotIn('určená na uvoľnenie', text)

    def test_missing_config_still_discloses_saved_host_paths_without_deleting(self):
        with patch.object(management, '_selected_configuration', side_effect=OSError('fixture missing')):
            text = management._removal_summary(ROOT / 'oci', 999990)
        self.assertIn('/fixture/saved', text)
        self.assertIn('rootfs -', text)

    def test_no_from_real_remove_review_never_calls_lifecycle(self):
        self.assertFalse(management._remove(ROOT / 'oci', self.ui, 999991))
        review = self.ui.review.call_args
        self.assertFalse(review.kwargs['default'])
        self.assertEqual(review.kwargs['question'],
            'Odstrániť aplikáciu? Jej kontajnerové disky sa vymažú a obnoviť ich možno iba zo zálohy.')

    def test_cancelled_real_remove_review_never_calls_lifecycle(self):
        self.ui.review.side_effect = UserCancelled('fixture cancelled')
        with self.assertRaises(UserCancelled):
            management._remove(ROOT / 'oci', self.ui, 999990)

    def test_preparation_error_does_not_show_confirmation_or_call_lifecycle(self):
        with patch.object(removal, 'members_of', side_effect=ValueError('fixture record invalid')):
            self.assertFalse(management._remove(ROOT / 'oci', self.ui, 999990))
        self.ui.review.assert_not_called()
        self.assertIn('Odstránenie nebolo možné pripraviť:', self.ui.message.call_args.args[0])

    def test_pending_operation_error_precedes_configuration_probe_and_all_mutations(self):
        self.make_records(1)
        self.records[999990]['pending_transaction'] = {'fixture': True}
        self.original = copy.deepcopy(self.records)
        with patch.object(removal, 'guest_config') as config:
            with self.assertRaisesRegex(ValueError, 'Operácia tejto inštalácie sa ešte nedokončila'):
                removal.remove(Path('/fixture/oci'), 999990)
        config.assert_not_called()

    def test_container_on_other_node_errors_before_host_cleanup(self):
        with patch.object(removal, 'guest_config', return_value=None), \
             patch.object(removal, 'guest_node', return_value='fixture-other-node'):
            with self.assertRaisesRegex(ValueError, 'Kontajner beží na inom uzle klastra'):
                removal.remove(Path('/fixture/oci'), 999990)

    def run_main(self, result=False, busy=False):
        with patch.object(sys, 'argv', ['oci_remove.py', '999990']), \
             patch.object(removal.os, 'geteuid', return_value=0), \
             patch.object(instances, 'locked', side_effect=BlockingIOError if busy else None,
                          return_value=nullcontext()), \
             patch.object(removal, 'remove', return_value=result) as mocked_remove, \
             patch.object(removal, 'msg_ok') as ok, patch.object(removal, 'msg_error') as error:
            code = removal.main()
        return code, mocked_remove, ok, error

    def test_busy_registry_error_does_not_enter_removal(self):
        code, remove, ok, error = self.run_main(busy=True)
        self.assertEqual(code, 1); remove.assert_not_called(); ok.assert_not_called()
        self.assertEqual(error.call_args.args[0], 'Register inštancií používa iná operácia OCI')

    def test_partial_completion_is_a_warning_to_review_not_unqualified_success(self):
        code, remove, ok, error = self.run_main(result=True)
        self.assertEqual(code, 0); error.assert_not_called()
        self.assertEqual(ok.call_args.args[0],
            'Príkaz na odstránenie sa dokončil; skontrolujte všetky upozornenia vyššie.')
        self.assertNotEqual(ok.call_args.args[0], i18n.translate('The application was removed'))

    def test_clean_completion_keeps_existing_success_contract(self):
        code, remove, ok, error = self.run_main()
        self.assertEqual(code, 0); error.assert_not_called()
        self.assertEqual(ok.call_args.args[0], 'Aplikácia bola odstránená')

    def test_english_primary_and_member_summaries_keep_identical_sentences(self):
        with patch.object(i18n, '_language', 'en'):
            primary = management._removal_summary(ROOT / 'oci', 999990)
            member = management._removal_summary(ROOT / 'oci', 999991)
        self.assertTrue(primary.startswith('Fixture App runs in 2 containers. All of them are targeted for removal.\n'))
        self.assertTrue(member.startswith('CT 999991 is one of the 2 containers of Fixture App. It cannot be removed on its own,'))

    def test_missing_translation_falls_back_to_the_same_english_summary(self):
        with patch.object(i18n, '_cache', {}):
            text = management._removal_summary(ROOT / 'oci', 999990)
        self.assertTrue(text.startswith('Fixture App runs in 2 containers. All of them are targeted for removal.\n'))

    def test_yes_only_builds_the_existing_command_when_lifecycle_is_inert(self):
        self.ui.review.return_value = True
        with patch.object(management, '_run_lifecycle', return_value=True) as inert:
            self.assertTrue(management._remove(ROOT / 'oci', self.ui, 999990))
        self.assertEqual(inert.call_args.args[0],
            [sys.executable, str(ROOT / 'oci/remote/oci_remove.py'), '999990'])

    def test_single_and_stack_menu_routes_use_the_translated_label_and_real_no_review(self):
        for count in (1, 2):
            with self.subTest(count=count):
                self.make_records(count)
                self.ui.reset_mock()
                self.ui.choose.return_value = 'remove'
                row = {'vmid': 999990, 'stack': count > 1, 'pending': False,
                       'status': 'installed', 'reason': 'matched'}
                with patch.object(management, 'carry_records', return_value={}), \
                     patch.object(management, 'check_selected', return_value=row):
                    self.assertFalse(management.manage_instance(ROOT / 'oci', self.ui, row))
                options = self.ui.choose.call_args.args[1]
                self.assertIn(('remove', 'Odstrániť: zmazať aplikáciu a jej kontajnery'), options)
                self.ui.review.assert_called_once()
                self.assertFalse(self.ui.review.call_args.kwargs['default'])

    def test_changed_identity_warning_does_not_claim_the_other_container_was_deleted(self):
        self.make_records(1)
        # Exercise the real backend branch; record cleanup is inert as well.
        with patch.object(removal, 'guest_config', return_value=b'fixture'), \
             patch.object(instances, 'identity', return_value='fixture-other-identity'), \
             patch.object(removal, 'remove_owned_host_firewall', return_value=True), \
             patch.object(removal, 'release_shared_host_files'), \
             patch.object(removal.work_backup, 'forget'), \
             patch.object(removal.image_cache, 'prune', return_value=[]), \
             patch.object(Path, 'exists', return_value=False), \
             patch.object(Path, 'is_dir', return_value=False), \
             patch.object(removal, 'msg_warn') as warning, \
             patch.object(removal, 'msg_ok') as ok, patch.object(removal, 'msg_info'):
            self.assertTrue(removal.remove(Path('/fixture/oci'), 999990))
        self.assertEqual(warning.call_args.args[0],
            'VMID teraz patrí inému kontajneru; ten zostane nedotknutý: CT 999990')
        self.assertNotIn('Odstránený kontajner:', str(ok.mock_calls))


if __name__ == '__main__':
    unittest.main()
