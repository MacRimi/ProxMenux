"""Pending recovery through real Menu/CLI/Dialog paths; all host effects forbidden."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

from test_oci_update_cancellation import CancellationFixture, ROOT
from proxmenux_oci import cli, i18n, management as menu, ui as native_ui
import oci_instances as instances
import oci_instance_transaction as transaction
import oci_native_modify as native_modify
import oci_stack_transaction as stack_transaction
import oci_ui

ACTUAL_RECOVER = transaction.recover


class PendingRecoveryFixture(CancellationFixture):
    def setUp(self):
        super().setUp()
        self.record.update(pending_transaction='/fiction-only/transaction.json')
        self.row['pending'] = True
        self.ui.choose.return_value = 'recover'
        self.original = copy.deepcopy(self.record)
        self.writes = [self.guard(Path, name) for name in ('write_text', 'write_bytes', 'unlink')]
        self.processes = [self.guard(subprocess, name) for name in ('run', 'Popen', 'check_output')]
        self.recovery = self.guard(transaction, 'recover')
        self.native_recovery = self.guard(native_modify, 'recover')
        self.stack_recovery = self.guard(stack_transaction, 'execute')

    def stack(self):
        self.row['stack'] = True
        self.record['pending_stack_transaction'] = '/fiction-only/stack.json'
        self.original = copy.deepcopy(self.record)

    def no_effects(self):
        super().no_effects()
        for mock in [*self.writes, *self.processes, self.recovery, self.native_recovery, self.stack_recovery]:
            mock.assert_not_called()


class PendingRecoveryTests(PendingRecoveryFixture):
    def test_single_no_is_distinct_falsy_cancellation(self):
        self.assertIs(menu.manage_instance(ROOT/'oci', self.ui, self.row), menu.CANCELLED)
        self.assertFalse(menu.CANCELLED)
        self.no_effects()

    def test_single_menu_cancel_is_distinct_cancellation(self):
        self.ui.choose.return_value = None
        self.assertIs(menu.manage_instance(ROOT/'oci', self.ui, self.row), menu.CANCELLED)
        self.ui.review.assert_not_called()
        self.no_effects()

    def test_real_cli_single_no_and_cancel_return_six_without_duplicate_output(self):
        for choice in ('recover', None):
            with self.subTest(choice=choice), patch.object(cli, 'Catalog'), redirect_stdout(io.StringIO()) as output:
                self.ui.choose.return_value = choice
                self.assertEqual(cli.main(['manage', '110', '--action', 'update']), 6)
                self.assertEqual(output.getvalue(), '')
            self.no_effects()

    def test_real_cli_stack_no_returns_six_before_reading_the_journal(self):
        self.stack()
        with patch.object(cli, 'Catalog'), patch.object(Path, 'read_text', side_effect=AssertionError('Journal read after No')) as read:
            self.assertEqual(cli.main(['manage', '110', '--action', 'update']), 6)
        read.assert_not_called()
        self.no_effects()

    def test_actual_dialog_no_and_escape_cancel_single_and_stack(self):
        dialog = native_ui.DialogUI()
        for stacked in (False, True):
            if stacked:
                self.stack()
            for code in (1, 255):
                with self.subTest(stack=stacked, code=code):
                    answers = ([] if stacked else [subprocess.CompletedProcess('dialog', 0, stderr='2')])
                    answers.append(subprocess.CompletedProcess('dialog', code, stderr=''))
                    with patch.object(native_ui, 'interactive_ui', return_value=dialog), \
                            patch.object(dialog, '_run', side_effect=answers):
                        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'update'), 6)
                    self.no_effects()

    def test_actual_dialog_cancel_and_escape_from_single_operation_menu(self):
        dialog = native_ui.DialogUI()
        for code in (1, 255):
            with self.subTest(code=code), patch.object(native_ui, 'interactive_ui', return_value=dialog), \
                    patch.object(dialog, '_run', return_value=subprocess.CompletedProcess('dialog', code, stderr='')):
                self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'update'), 6)
            self.no_effects()

    def test_native_menu_returns_to_its_list_after_pending_single_or_stack_no(self):
        for stacked in (False, True):
            if stacked:
                self.stack()
            self.ui.choose.reset_mock()
            self.ui.choose.side_effect = ['110', None] if stacked else ['110', 'recover', None]
            with self.subTest(stack=stacked), patch.object(menu, '_clean_orphans'), \
                    patch.object(menu, 'offer_recovery'), patch.object(menu, '_records_unread', return_value=[]):
                menu.interactive_management(ROOT/'oci', self.ui)
            self.assertEqual(self.ui.choose.call_count, 2 if stacked else 3)
            self.no_effects()

    def test_confirmed_single_recovery_and_status_preserve_exact_commands_and_results(self):
        self.ui.review.return_value = True
        for action in ('recover', 'status'):
            for success, code in ((True, 0), (False, 1)):
                self.lifecycle.reset_mock()
                self.lifecycle.side_effect = None
                self.lifecycle.return_value = success
                self.ui.choose.return_value = action
                with self.subTest(action=action, result=success):
                    self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'update'), code)
                    self.lifecycle.assert_called_once_with(
                        [sys.executable, str(ROOT/'oci/remote/oci_instance_transaction.py'), action, '110'],
                        'Recover OCI' if action == 'recover' else 'OCI management')
                    self.write.assert_not_called(); self.backup.assert_not_called()
        self.assertEqual(self.record, self.original)

    def test_confirmed_stack_recovery_preserves_command_and_failure_is_not_cancel(self):
        self.stack()
        self.ui.review.return_value = True
        for success, code in ((True, 0), (False, 1)):
            self.lifecycle.reset_mock()
            self.lifecycle.side_effect = None
            self.lifecycle.return_value = success
            with self.subTest(result=success), patch.object(Path, 'read_text', return_value=json.dumps({'plan': {'members': [{'vmid': 110}, {'vmid': 111}]}})):
                self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'update'), code)
            self.lifecycle.assert_called_once_with(
                [sys.executable, str(ROOT/'oci/remote/oci_stack_native.py'), '110', '--recover', '--acknowledge-external-data'],
                'Recover OCI stack')
            self.write.assert_not_called(); self.backup.assert_not_called()
        self.assertEqual(self.record, self.original)

    def test_identity_failure_stays_failure_and_does_not_offer_recovery(self):
        with patch.object(menu, 'check_selected', return_value={**self.row, 'reason': 'different-installation'}):
            self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'update'), 1)
        self.ui.choose.assert_not_called(); self.ui.review.assert_not_called()
        self.no_effects()

    def test_unattended_does_not_turn_pending_menu_into_an_automatic_restore(self):
        self.assertEqual(menu.direct_management(ROOT/'oci', 110, 'update', unattended=True), 1)
        self.no_effects()

    def test_registration_cli_retains_its_separate_entry_point(self):
        with patch.object(cli, 'Catalog'), patch.object(menu, 'direct_recovery', return_value=0) as register, \
                patch.object(menu, 'direct_management', side_effect=AssertionError('Registration routed to rollback')):
            self.assertEqual(cli.main(['recover']), 0)
        register.assert_called_once_with(ROOT/'oci')
        self.no_effects()


class RecoverySlovakMeaning(PendingRecoveryFixture):
    def test_actual_recovery_dialogs_preserve_host_data_and_bounded_recovery_meaning(self):
        cache = json.loads((ROOT/'lang/sk.json').read_text())
        with patch.object(i18n, '_language', 'sk'), patch.object(i18n, '_cache', cache):
            menu.manage_instance(ROOT/'oci', self.ui, self.row)
            text = self.ui.review.call_args.args[0]
            self.assertIn('Zdieľané hostiteľské adresáre sa nevrátia späť', text)
            self.assertIn('po úspešnom vyčistení', text)
            self.assertEqual(self.ui.choose.call_args.args[0], 'Prerušená operácia')
            self.assertEqual(dict(self.ui.choose.call_args.args[1])['status'], 'Zobraziť stav')
            self.stack()
            menu.manage_instance(ROOT/'oci', self.ui, self.row)
            self.assertEqual(self.ui.review.call_args.args[1], 'Obnoviť OCI aplikáciu s viacerými kontajnermi')
            self.assertIn('môžu zlyhať', self.ui.review.call_args.args[0])
            self.assertEqual(self.ui.review.call_args.kwargs['question'], 'Obnoviť alebo dokončiť operáciu?')
        self.no_effects()


class RecoveryGuardMessages(PendingRecoveryFixture):
    def setUp(self):
        super().setUp()
        cache = json.loads((ROOT/'lang/sk.json').read_text())
        for name, value in (('_language', 'sk'), ('_cache', cache)):
            p = patch.object(oci_ui, name, value)
            p.start(); self.addCleanup(p.stop)
        self.record.update(installation_id='fiction-installation', transaction_id='fiction-tx')
        self.original = copy.deepcopy(self.record)
        self.journal = Path(self.record['pending_transaction'])
        self.state = {'id': 'fiction-tx', 'vmid': 110, 'phase': 'backup-ready',
            'record': {'installation_id': 'fiction-installation'}, 'before_config': 'before',
            'backup': None, 'backup_sha256': 'saved-sha'}

    def rejected(self, text, *, node='fiction-host', changed_backup=False):
        calls = []
        def readonly(*args):
            calls.append(args)
            if args[0] == 'pvesh':
                return json.dumps([{'type': 'lxc', 'vmid': 110, 'node': node}]).encode()
            if args == ('pct', 'config', '110'):
                return b'changed'
            raise AssertionError('Unexpected recovery effect: ' + repr(args))
        with patch.object(Path, 'read_text', return_value=json.dumps(self.state)), \
                patch.object(Path, 'exists', return_value=True), patch.object(Path, 'is_file', return_value=True), \
                patch.object(transaction.socket, 'gethostname', return_value='fiction-host'), \
                patch.object(transaction.host_mounts, 'verify_sources'), patch.object(transaction.gpu_devices, 'verify'), \
                patch.object(transaction, 'owned', return_value=b'fiction config'), \
                patch.object(transaction, 'filehash', return_value='changed-sha' if changed_backup else 'saved-sha'), \
                patch.object(transaction, 'run', side_effect=readonly), redirect_stdout(io.StringIO()):
            # Only reads before the rejecting guard are supplied. Any next
            # command or attempt to persist state fails this fixture.
            with self.assertRaisesRegex(ValueError, text):
                ACTUAL_RECOVER(ROOT/'oci', self.journal)
        self.no_effects()
        return calls

    def test_foreign_transaction_is_rejected_before_probing_the_container(self):
        self.state['record']['installation_id'] = 'different-installation'
        self.assertEqual(self.rejected('Záznam nepatrí k tejto operácii'), [])

    def test_missing_verified_backup_cannot_touch_a_changed_container(self):
        self.assertEqual(len(self.rejected('Chýba overená záloha; zmenený kontajner zostáva nedotknutý')), 2)

    def test_changed_backup_is_rejected_before_decompression_or_restore(self):
        self.state['backup'] = '/fiction-only/backup.zst'
        self.assertEqual(len(self.rejected('Záloha bola zmenená; obnova zablokovaná', changed_backup=True)), 2)

    def test_guest_on_another_node_is_never_overwritten(self):
        self.assertEqual(len(self.rejected('kontajner je na inom uzle; nie je prepísaný', node='another-node')), 1)

    def test_incomplete_stack_recovery_state_fails_before_any_adapter_call(self):
        adapter = SimpleNamespace(validate=self.recovery, stop=self.native_recovery,
                                  restore=self.stack_recovery)
        state = {'phase': 'recovery-failed', 'plan': {'start_order': [110, 111]},
                 'running': {'110': True}, 'stop_intent': True, 'replacement_intent': False}
        before = copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError, 'Záznam operácie obsahuje neúplný stav obnovy'):
            stack_transaction.recover_state(self.journal, state, adapter)
        self.assertEqual(state, before)
        self.no_effects()

    def test_critical_safety_and_untouched_result_have_the_correct_meaning(self):
        cache = json.loads((ROOT/'lang/sk.json').read_text())
        self.assertEqual(cache['A host mount is not part of the journal; recovery blocked'],
                         'Pripojenie adresára hostiteľa nie je uvedené v zázname operácie; obnova je zablokovaná')
        self.assertEqual(cache['Recovery completed. The container had not been modified yet.'],
                         'Obnova dokončená. Kontajner ešte nebol zmenený.')
        self.assertEqual(cache['A backup was modified'], 'Záloha bola zmenená')
        self.assertEqual(cache['Recovering the previous installation'], 'Obnovovanie predchádzajúcej inštalácie')
        self.assertEqual(cache['Recover the previous installation'], 'Obnoviť predchádzajúcu inštaláciu')
        self.no_effects()
