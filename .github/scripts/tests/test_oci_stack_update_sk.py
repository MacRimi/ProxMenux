"""Coordinated update/recreate contracts; no host lifecycle is permitted."""
import copy
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from test_oci_update_cancellation import CancellationFixture, ROOT
from proxmenux_oci import cli, i18n, management as menu, ui as native_ui, updates
import oci_instances as instances
import oci_stack_plan as stack_plan
import oci_stack_transaction as transaction
import oci_ui


class StackFixture(CancellationFixture):
    def setUp(self):
        super().setUp()
        self.row['stack'] = True
        self.record.update(installation_id='fiction-main', stack={
            'id': 'fiction-main', 'members': [
                {'vmid': vmid, 'installation_id': identity, 'status': 'installed',
                 'stack_member': {'stack_id': 'fiction-main', 'primary_vmid': 110}}
                for vmid, identity in [(110, 'fiction-main'), (111, 'fiction-dependent')]],
            'deployment': {'services': [{'vmid': 111}, {'vmid': 110}]}})
        self.original = copy.deepcopy(self.record)
        self.extra_effects = [self.guard(Path, name) for name in ('write_text', 'write_bytes', 'unlink')]
        self.extra_effects += [self.guard(subprocess, name) for name in ('run', 'Popen', 'check_output')]
        self.extra_effects += [self.guard(transaction, 'execute'), self.guard(transaction, 'save'),
                               self.guard(menu.images, 'offer_removal')]

    def no_effects(self):
        super().no_effects()
        for effect in self.extra_effects:
            effect.assert_not_called()


class StackCancellationTests(StackFixture):
    def test_update_and_recreate_no_are_falsy_distinct_cancellation(self):
        for action in ('update', 'recreate'):
            with self.subTest(action=action):
                result = menu.manage_instance(ROOT/'oci', self.ui, self.row, action=action)
                self.assertIs(result, menu.CANCELLED)
                self.assertFalse(result)
                self.no_effects()

    def test_real_cli_cancel_returns_six_for_both_actions(self):
        for action in ('update', 'recreate'):
            with self.subTest(action=action), patch.object(cli, 'Catalog'):
                self.assertEqual(cli.main(['manage', '110', '--action', action]), 6)
                self.no_effects()

    def test_actual_dialog_no_and_escape_return_six_before_any_effect(self):
        dialog = native_ui.DialogUI()
        for action in ('update', 'recreate'):
            for code in (1, 255):
                with self.subTest(action=action, code=code), \
                        patch.object(native_ui, 'interactive_ui', return_value=dialog), \
                        patch.object(dialog, '_run', return_value=subprocess.CompletedProcess('dialog', code, stderr='')):
                    self.assertEqual(menu.direct_management(ROOT/'oci', 110, action), 6)
                    self.no_effects()

    def test_confirmation_defaults_and_member_count_are_preserved(self):
        for action, default in [('update', True), ('recreate', False)]:
            menu.manage_instance(ROOT/'oci', self.ui, self.row, action=action)
            args, kwargs = self.ui.review.call_args
            self.assertIn('2 containers', args[0])
            self.assertIn('main CT: 110', args[0])
            self.assertEqual(kwargs['default'], default)
        self.no_effects()

    def test_native_menu_returns_to_the_application_list_after_no(self):
        for action in ('update', 'recreate'):
            with self.subTest(action=action):
                self.ui.choose.reset_mock()
                self.ui.choose.side_effect = ['110', action, None]
                with patch.object(menu, '_clean_orphans'), patch.object(menu, 'offer_recovery'), \
                        patch.object(menu, '_records_unread', return_value=[]):
                    menu.interactive_management(ROOT/'oci', self.ui)
                self.assertEqual(self.ui.choose.call_count, 3)
                self.no_effects()

    def test_batch_cancel_never_checks_the_next_application(self):
        available = [{'vmid': 110, 'title': 'First'}, {'vmid': 112, 'title': 'Second'}]
        self.ui.checklist.return_value = ['all']
        self.ui.review.side_effect = [True, False]
        with patch.object(updates, 'UpdateCheck') as checker, \
                patch.object(menu, 'saved_inventory', return_value=[self.row, {**self.row, 'vmid': 112}]), \
                patch.object(menu, 'check_selected', side_effect=lambda project, row: row) as selected:
            checker.return_value.status.return_value = {'available': available}
            self.assertFalse(updates.select_updates(ROOT/'oci', self.ui, available))
        self.assertEqual([call.args[1]['vmid'] for call in selected.call_args_list], [110])
        self.no_effects()

    def test_rejected_backup_remains_failure_one_without_dispatch(self):
        self.ui.review.return_value = True
        self.backup.side_effect = None
        self.backup.return_value = False
        for action in ('update', 'recreate'):
            self.assertEqual(menu.direct_management(ROOT/'oci', 110, action), 1)
        self.lifecycle.assert_not_called()
        self.assertEqual(self.record, self.original)

    def test_positive_confirmation_preserves_success_failure_and_exact_commands(self):
        self.ui.review.return_value = True
        self.backup.side_effect = None
        self.backup.return_value = True
        self.lifecycle.side_effect = None
        for action in ('update', 'recreate'):
            for result in (False, True):
                self.lifecycle.reset_mock()
                self.lifecycle.return_value = result
                with patch.object(menu.images, 'offer_removal') as offer:
                    self.assertEqual(menu.direct_management(ROOT/'oci', 110, action,
                        lifecycle_args=('--keep-backup',)), 0 if result else 1)
                    expected = [sys.executable, str(ROOT/'oci/remote/oci_stack_native.py'), '110', '--keep-backup']
                    if action == 'recreate':
                        expected += ['--operation', 'recreate']
                    self.assertEqual(self.lifecycle.call_args.args[0], expected+['--acknowledge-external-data'])
                    self.assertEqual(offer.call_count, int(result))
                self.assertEqual(self.record, self.original)
        self.write.assert_not_called()
        self.command.assert_not_called()

    def test_acknowledgement_is_not_duplicated(self):
        self.ui.review.return_value = True
        self.backup.side_effect = None
        self.backup.return_value = True
        self.lifecycle.side_effect = None
        self.lifecycle.return_value = False
        menu.direct_management(ROOT/'oci', 110, 'recreate', lifecycle_args=('--acknowledge-external-data',))
        self.assertEqual(self.lifecycle.call_args.args[0].count('--acknowledge-external-data'), 1)


class StackSlovakTests(StackFixture):
    def setUp(self):
        super().setUp()
        self.catalog = json.loads((ROOT/'lang/sk.json').read_text())
        for module in (i18n, oci_ui):
            for name, value in [('_language', 'sk'), ('_cache', self.catalog)]:
                item = patch.object(module, name, value)
                item.start()
                self.addCleanup(item.stop)

    def test_questions_and_titles_name_the_whole_application(self):
        for action, question in [('update', 'Aktualizovať celú aplikáciu?'),
                                 ('recreate', 'Znovu vytvoriť všetky kontajnery aplikácie?')]:
            menu.manage_instance(ROOT/'oci', self.ui, self.row, action=action)
            self.assertEqual(self.ui.review.call_args.kwargs['question'], question)
            self.assertIn('aplikáciu s viacerými kontajnermi', self.ui.review.call_args.args[1])
        self.no_effects()

    def test_recreation_dialog_explains_saved_images_and_restoring_backups(self):
        menu.manage_instance(ROOT/'oci', self.ui, self.row, action='recreate')
        text = self.ui.review.call_args.args[0]
        self.assertIn('uložených identifikátorov obrazov', text)
        self.assertIn('2', text)
        self.assertIn('110', text)
        self.assertIn('zálohy sa obnovia', text)
        self.assertNotIn('Stack', text)
        self.no_effects()

    def test_shared_missing_primary_error_in_plan_and_publish_before_any_effect(self):
        primary = copy.deepcopy(self.record)
        primary['vmid'] = 112
        with self.assertRaisesRegex(ValueError, '^Chýba hlavný kontajner aplikácie$'):
            stack_plan.build(primary, {}, {}, 'update')
        with self.assertRaisesRegex(ValueError, '^Chýba hlavný kontajner aplikácie$'):
            instances.publish_stack(Path('/fiction-only'), 110, {}, {}, [])
        self.no_effects()

    def test_missing_member_error_keeps_volume_verification_requirement(self):
        records = {row['vmid']: row for row in self.record['stack']['members']}
        with self.assertRaisesRegex(ValueError, 'znova ich vytvorte až po overení ich dátových zväzkov'):
            stack_plan.build(self.record, records, {110: 'fiction-main'}, 'update')
        self.no_effects()

    def test_pending_and_conflicting_member_errors_keep_the_identifier(self):
        records = {row['vmid']: copy.deepcopy(row) for row in self.record['stack']['members']}
        inventory = {key: row['installation_id'] for key, row in records.items()}
        records[111]['status'] = 'pending'
        with self.assertRaisesRegex(ValueError, '^Nedokončená operácia existuje pre CT 111$'):
            stack_plan.build(self.record, records, inventory, 'update')
        records[111]['status'] = 'installed'
        inventory[111] = 'different-installation'
        with self.assertRaisesRegex(ValueError, '^Iná inštancia už používa VMID 111$'):
            stack_plan.build(self.record, records, inventory, 'update')
        self.no_effects()

    def test_plan_failure_is_read_only_and_distinguishes_invalid_identity(self):
        primary = copy.deepcopy(self.record)
        primary['stack']['id'] = 'different-stack'
        with self.assertRaisesRegex(ValueError, '^Nekonzistentná identita aplikácie s viacerými kontajnermi$'):
            stack_plan.build(primary, {}, {}, 'recreate')
        self.no_effects()
