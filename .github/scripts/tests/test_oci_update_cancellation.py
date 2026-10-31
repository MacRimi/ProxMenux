"""Real native OCI menu/CLI paths with all external effects replaced."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'oci/src'), str(ROOT / 'oci/remote')]
from proxmenux_oci import cli, i18n, management as menu, ui as native_ui, updates
import oci_instances as instances
import oci_instance_reconcile as reconcile


class CancellationFixture(unittest.TestCase):
    def setUp(self):
        self.record = {'status': 'installed', 'vmid': 110, 'deployment': {}, 'template': {}}
        self.original = copy.deepcopy(self.record)
        self.row = dict(vmid=110, reason='matched', stack=False, pending=False, status='installed',
                        title='Fixture application', hostname='fixture', image='fixture:latest')
        self.ui = Mock()
        self.ui.unattended = False
        self.ui.review.return_value = False
        for module, name, options in [
            (i18n, '_language', dict(new='en')), (i18n, '_cache', dict(new={})),
            (menu.os, 'geteuid', dict(return_value=0)), (menu.shutil, 'which', dict(return_value='/fixture/pct')),
            (native_ui, 'interactive_ui', dict(return_value=self.ui)),
            (menu, 'recover_automatically', dict(return_value=None)),
            (menu, 'carry_records', dict(return_value={})),
            (menu, 'check_selected', dict(side_effect=lambda project, row: row)),
            (menu, 'saved_inventory', dict(return_value=[self.row])),
            (menu, '_selected_configuration', dict(return_value=b'fixture configuration')),
            (instances, 'read', dict(return_value=self.record)),
            (reconcile, 'propose', dict(return_value=None)),
        ]:
            item = patch.object(module, name, **options)
            item.start()
            self.addCleanup(item.stop)
        self.lifecycle = self.guard(menu, '_run_lifecycle')
        self.backup = self.guard(menu, '_work_backup_ready')
        self.write = self.guard(instances, 'write')
        self.command = self.guard(instances, 'command')
        self.commit = self.guard(reconcile, 'commit')

    def guard(self, module, name):
        item = patch.object(module, name, side_effect=AssertionError('Forbidden effect: ' + name))
        mock = item.start()
        self.addCleanup(item.stop)
        return mock

    def no_effects(self):
        for mock in [self.lifecycle, self.backup, self.write, self.command, self.commit]:
            mock.assert_not_called()
        self.assertEqual(self.record, self.original)


class UpdateCancellationTests(CancellationFixture):
    def test_no_is_a_distinct_falsy_result_before_backup_or_lifecycle(self):
        result = menu.manage_instance(ROOT / 'oci', self.ui, self.row, action='update')
        self.assertIs(result, menu.CANCELLED)
        self.assertFalse(result)
        self.no_effects()

    def test_real_cli_no_returns_cancel_code_instead_of_failure_or_success(self):
        with patch.object(cli, 'Catalog'), redirect_stdout(io.StringIO()) as output:
            result = cli.main(['manage', '110', '--action', 'update'])
        self.assertEqual(result, 6)
        self.assertEqual(output.getvalue(), '')  # The terminal renders the localized outcome once.
        self.no_effects()

    def test_no_in_stack_confirmation_keeps_every_member_unchanged(self):
        self.row['stack'] = True
        self.record['stack'] = {'members': [{'vmid': 110}, {'vmid': 111}]}
        self.original = copy.deepcopy(self.record)
        with redirect_stdout(io.StringIO()):
            result = menu.direct_management(ROOT / 'oci', 110, 'update')
        self.assertEqual(result, 6)
        self.no_effects()

    def test_native_menu_returns_to_its_list_after_no(self):
        self.ui.choose.side_effect = ['110', 'update', None]
        with patch.object(menu, '_clean_orphans'), patch.object(menu, 'offer_recovery'), \
                patch.object(menu, '_records_unread', return_value=[]):
            menu.interactive_management(ROOT / 'oci', self.ui)
        self.assertEqual(self.ui.choose.call_count, 3)
        self.no_effects()

    def test_batch_no_does_not_start_the_next_application(self):
        available = [{'vmid': 110, 'title': 'First'}, {'vmid': 111, 'title': 'Second'}]
        rows = [self.row, {**self.row, 'vmid': 111}]
        self.ui.checklist.return_value = ['all']
        self.ui.review.side_effect = [True, False]  # Batch review, first application's confirmation.
        with patch.object(updates, 'UpdateCheck') as checker, patch.object(menu, 'saved_inventory', return_value=rows), \
                patch.object(menu, 'check_selected', wraps=lambda project, row: row) as selected:
            checker.return_value.status.return_value = {'available': available}
            self.assertFalse(updates.select_updates(ROOT / 'oci', self.ui, available))
        self.assertEqual([call.args[1]['vmid'] for call in selected.call_args_list], [110])
        self.no_effects()

    def test_accepted_update_failure_keeps_failure_code_one(self):
        self.ui.review.return_value = True
        self.backup.side_effect = None
        self.backup.return_value = False
        self.assertEqual(menu.direct_management(ROOT / 'oci', 110, 'update'), 1)
        self.lifecycle.assert_not_called()
        self.write.assert_not_called()

    def test_accepted_update_preserves_success_and_existing_lifecycle_command(self):
        self.ui.review.return_value = True
        self.backup.side_effect = None
        self.backup.return_value = True
        self.lifecycle.side_effect = None
        self.lifecycle.return_value = True
        self.assertEqual(menu.direct_management(ROOT / 'oci', 110, 'update'), 0)
        self.lifecycle.assert_called_once()
        command = self.lifecycle.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, str(ROOT / 'oci/remote/oci_update_current.py'), '110'])
        self.assertIn('--acknowledge-external-data', command)
        self.write.assert_not_called()

    def test_actual_lifecycle_failure_remains_failure_after_positive_confirmation(self):
        self.ui.review.return_value = True
        self.backup.side_effect = None
        self.backup.return_value = True
        self.lifecycle.side_effect = None
        self.lifecycle.return_value = False
        self.assertEqual(menu.direct_management(ROOT / 'oci', 110, 'update'), 1)
        self.lifecycle.assert_called_once()
        self.write.assert_not_called()

    def test_unattended_positive_default_still_reaches_existing_update(self):
        self.backup.side_effect = None
        self.backup.return_value = True
        self.lifecycle.side_effect = None
        self.lifecycle.return_value = True
        self.assertEqual(menu.direct_management(ROOT / 'oci', 110, 'update', unattended=True), 0)
        self.lifecycle.assert_called_once()
        self.write.assert_not_called()

    def test_existing_unattended_review_age_busy_and_missing_codes_are_preserved(self):
        def declined(unattended, *_args, **_kwargs):
            unattended.declined = 'review'
            return False
        with patch.object(reconcile, 'propose', return_value={'details': ['external change'], 'review': True}), \
                patch.object(menu.UnattendedUI, 'review', declined), redirect_stdout(io.StringIO()):
            self.assertEqual(menu.direct_management(ROOT / 'oci', 110, 'update', unattended=True), 4)
        with patch.object(menu, '_image_too_recent', return_value=True), redirect_stdout(io.StringIO()):
            self.assertEqual(menu.direct_management(ROOT / 'oci', 110, 'update', unattended=True, min_image_age_days=3), 5)
        with patch.object(menu, 'saved_inventory', return_value=[]):
            self.assertEqual(menu.direct_management(ROOT / 'oci', 110, 'update'), 2)
        with patch.object(menu, 'recover_automatically', side_effect=BlockingIOError()):
            self.assertEqual(menu.direct_management(ROOT / 'oci', 110, 'update'), 3)
        self.no_effects()

    def test_slovak_dialog_and_recovery_choice_have_the_approved_meaning(self):
        cache = json.loads((ROOT / 'lang/sk.json').read_text())
        with patch.object(i18n, '_language', 'sk'), patch.object(i18n, '_cache', cache):
            menu.manage_instance(ROOT / 'oci', self.ui, self.row, action='update')
            self.assertEqual(i18n.translate('Recover the previous installation'), 'Obnoviť predchádzajúcu inštaláciu')
        text = self.ui.review.call_args.args[0]
        for part in ['novší obraz aplikácie', 'overí sa jej integrita', 'pokúsi obnoviť', 'Pripojené adresáre hostiteľa']:
            self.assertIn(part, text)
        self.assertNotIn('kanál obrazov', text)
        self.assertEqual(self.ui.review.call_args.kwargs['question'], 'Spustiť aktualizáciu?')
        self.no_effects()


if __name__ == '__main__':
    unittest.main()
