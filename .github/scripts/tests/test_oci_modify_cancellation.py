"""Cancel a real editor through Menu/CLI/Monitor contracts, never apply it."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

from test_oci_update_cancellation import CancellationFixture, ROOT
from proxmenux_oci import cli, management as menu, recreation
from proxmenux_oci.ui import UserCancelled


class ModifyCancellationTests(CancellationFixture):
    def setUp(self):
        super().setUp()
        self.record.update({
            'installation_id': 'fixture-oci-edit-cancel',
            'observed': {'config_sha256': 'fixture-config-hash'},
            'template': {'id': 'fixture-app', 'catalog_ui': {'title': 'Fixture'},
                'container_contract': {'image': {'reference': 'example/fixture:latest'}}},
            'deployment': {'vmid': 110, 'hostname': 'fixture',
                'resources': {'cores': 2, 'memory_mb': 512},
                'rootfs': {'storage': 'fixture-storage', 'size_gb': 8},
                'mounts': [], 'devices': [], 'environment': [
                    {'name': 'PASSWORD', 'value': 'private-fixture-value', 'sensitive': True}],
                'network': {'bridge': 'vmbr-fixture', 'ipv4': 'dhcp'}}})
        self.original = copy.deepcopy(self.record)
        self.ui.back_enabled = False
        self.path_write = self.guard(Path, 'write_text')
        self.path_bytes = self.guard(Path, 'write_bytes')

    def script(self, choices, answers=(), confirms=(), reviews=()):
        self.ui.choose.side_effect = choices
        self.ui.ask.side_effect = answers
        self.ui.confirm.side_effect = confirms
        self.ui.review.side_effect = reviews

    def no_effects(self):
        super().no_effects()
        self.path_write.assert_not_called()
        self.path_bytes.assert_not_called()
        self.assertFalse(self.ui.back_enabled)

    def test_main_cancel_is_distinct_falsy_cancellation(self):
        self.script([None])
        self.assertIs(menu.manage_instance(ROOT/'oci', self.ui, self.row, action='modify'), menu.CANCELLED)
        self.assertFalse(menu.CANCELLED)
        self.no_effects()

    def test_main_discard_without_edits_returns_cancel_code(self):
        self.script(['discard'])
        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'modify'), 6)
        self.ui.confirm.assert_not_called()
        self.no_effects()

    def test_real_cli_cancel_returns_code_six_without_extra_console_output(self):
        self.script([None])
        with patch.object(cli, 'Catalog'), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['manage', '110', '--action', 'modify']), 6)
        self.assertEqual(output.getvalue(), '')
        self.no_effects()

    def test_real_cli_discard_after_edits_never_calls_backup_or_lifecycle(self):
        self.script(['cores', 'discard'], ['3'], [True])
        with patch.object(cli, 'Catalog'), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['manage', '110', '--action', 'modify']), 6)
        self.ui.confirm.assert_called_once_with('Discard unapplied changes?', False)
        self.no_effects()

    def test_main_cancel_after_edits_requires_discard_confirmation(self):
        self.script(['cores', None], ['3'], [True])
        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'modify'), 6)
        self.ui.confirm.assert_called_once_with('Discard unapplied changes?', False)
        self.no_effects()

    def test_declining_discard_preserves_draft_until_later_main_cancel(self):
        self.script(['cores', 'discard', None], ['3'], [False, True])
        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'modify'), 6)
        last_options = dict(self.ui.choose.call_args.args[1])
        self.assertTrue(last_options['cores'].rstrip().endswith('3'))
        self.assertIn('Unapplied changes', self.ui.choose.call_args.args[0])
        self.assertEqual(self.ui.confirm.call_count, 2)
        self.no_effects()

    def test_section_cancel_returns_to_editor_before_main_cancel(self):
        self.script(['cores', None], [UserCancelled()])
        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'modify'), 6)
        self.assertEqual(self.ui.choose.call_count, 2)
        self.assertIn('No pending changes', self.ui.choose.call_args.args[0])
        self.ui.review.assert_not_called()
        self.no_effects()

    def test_zero_cores_rejected_then_section_and_main_cancel_are_safe(self):
        self.script(['cores', None], ['0', UserCancelled()])
        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'modify'), 6)
        self.assertIn('Cores: minimum 1', self.ui.message.call_args.args[0])
        self.assertIn('No pending changes', self.ui.choose.call_args.args[0])
        self.no_effects()

    def test_review_no_returns_to_editor_with_draft_then_discard_cancels(self):
        self.script(['cores', 'apply', 'discard'], ['3'], [True], [False])
        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'modify'), 6)
        self.assertEqual(self.ui.choose.call_count, 3)
        self.assertIn('Unapplied changes', self.ui.choose.call_args.args[0])
        self.assertNotIn('private-fixture-value', self.ui.review.call_args.args[0])
        self.no_effects()

    def test_native_menu_returns_to_list_after_editor_cancel(self):
        self.script(['110', 'modify', None, None])
        with patch.object(menu, '_clean_orphans'), patch.object(menu, 'offer_recovery'), \
                patch.object(menu, '_records_unread', return_value=[]):
            menu.interactive_management(ROOT/'oci', self.ui)
        self.assertEqual(self.ui.choose.call_count, 4)
        self.no_effects()

    def test_legacy_editor_callers_still_receive_none_on_cancel(self):
        for choice in (None, 'discard'):
            with self.subTest(choice=choice):
                self.script([choice])
                self.assertIsNone(recreation.edit_recreation(self.record, self.ui))
        self.no_effects()

    def test_unchanged_review_is_not_mislabeled_as_user_cancellation(self):
        self.script(['apply'])
        self.assertIsNone(recreation.edit_recreation(self.record, self.ui, cancelled_result=menu.CANCELLED))
        self.ui.message.assert_called_once_with('Nothing was changed.', 'Modify OCI')
        self.no_effects()

    def test_real_editor_error_is_not_converted_to_cancellation(self):
        self.script(['cores'], [RuntimeError('fixture editor failure')])
        with self.assertRaisesRegex(RuntimeError, 'fixture editor failure'):
            menu.direct_management(ROOT/'oci', 110, 'modify')
        self.no_effects()

    def test_real_cli_validation_failure_remains_failure_one(self):
        self.script(['cores'], [cli.InstallError('fixture validation failure')])
        with patch.object(cli, 'Catalog'), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['manage', '110', '--action', 'modify']), 1)
        self.no_effects()

    def test_unattended_modify_is_rejected_before_opening_the_editor(self):
        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'modify', unattended=True), 1)
        self.ui.choose.assert_not_called()
        self.no_effects()

    def test_accepted_proposal_keeps_original_backend_and_private_payload(self):
        self.script(['cores', 'apply'], ['3'], reviews=[True])
        self.backup.side_effect = None
        self.backup.return_value = True
        def lifecycle(command, title):
            self.assertEqual(command[:3], [sys.executable, str(ROOT/'oci/remote/oci_update_current.py'), '110'])
            proposal_file = Path(command[command.index('--proposal')+1])
            self.assertEqual(proposal_file.stat().st_mode & 0o777, 0o600)
            proposal = json.loads(proposal_file.read_text())
            self.assertEqual(proposal['operation'], 'recreate')
            self.assertEqual(proposal['candidate']['deployment']['resources']['cores'], 3)
            self.assertEqual(proposal['base_config_sha256'], 'fixture-config-hash')
            self.assertNotIn('private-fixture-value', ' '.join(command))
            return True
        self.lifecycle.side_effect = lifecycle
        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'modify'), 0)
        self.backup.assert_called_once()
        self.lifecycle.assert_called_once()
        self.assertEqual(self.record, self.original)
        self.write.assert_not_called()

    def test_failed_backup_after_review_remains_failure_without_lifecycle(self):
        self.script(['cores', 'apply'], ['3'], reviews=[True])
        self.backup.side_effect = None
        self.backup.return_value = False
        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'modify'), 1)
        self.lifecycle.assert_not_called()
        self.write.assert_not_called()
        self.assertEqual(self.record, self.original)
