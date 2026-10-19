"""Explicit update selection and live status redraw without lifecycle shortcuts."""
from pathlib import Path
import ast
import json
import os
import re
import signal
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'remote')]
from proxmenux_oci import cli, management, updates
from proxmenux_oci.ui import DialogUI, MenuRefresh, ReadableTags, UserCancelled

AVAILABLE = [{'vmid': 110, 'title': 'First app'}, {'vmid': 111, 'title': 'Second app'}]


class SelectionTests(unittest.TestCase):
    def select(self, picked, available=AVAILABLE, review=True, fresh=None, outcomes=None):
        ui = Mock()
        ui.checklist.side_effect = picked if isinstance(picked, Exception) else [picked]
        ui.review.return_value = review
        current = [{**row, 'reason': 'matched'} for row in available]
        with patch.object(updates, 'UpdateCheck') as checker, \
                patch.object(management, 'saved_inventory', return_value=current), \
                patch.object(management, 'manage_instance', side_effect=outcomes or [True] * len(available)) as run:
            checker.return_value.status.return_value = {'available': available if fresh is None else fresh}
            result = updates.select_updates(ROOT, ui, available)
        return result, ui, run

    def test_one_update_is_not_checked_by_default(self):
        _, ui, run = self.select([], available=AVAILABLE[:1])
        self.assertEqual(ui.checklist.call_args.args[2], [])
        self.assertEqual(ui.checklist.call_args.args[1][0], ('all', 'Select all'))
        run.assert_not_called()

    def test_only_selected_app_uses_existing_update_flow(self):
        _, ui, run = self.select(['111'])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[2]['vmid'], 111)
        self.assertEqual(run.call_args.kwargs, {'action': 'update', 'heading': 'Update OCI (1/1) · Second app'})
        self.assertIn('Second app', ui.review.call_args.args[0])
        self.assertNotIn('First app', ui.review.call_args.args[0])

    def test_select_all_includes_every_app_once(self):
        _, ui, run = self.select(['all', '111'])
        self.assertEqual([c.args[2]['vmid'] for c in run.call_args_list], [110, 111])
        # Each update shows its place in the batch while its container is checked.
        self.assertEqual([c.kwargs['heading'] for c in run.call_args_list],
                         ['Update OCI (1/2) · First app', 'Update OCI (2/2) · Second app'])
        self.assertFalse(ui.review.call_args.kwargs['default'])

    def test_cancel_does_nothing(self):
        _, ui, run = self.select(UserCancelled())
        ui.review.assert_not_called(); run.assert_not_called()

    def test_selection_has_an_update_button_and_no_extra_action(self):
        result, ui, run = self.select([])
        self.assertEqual(ui.checklist.call_args.kwargs['ok_label'], 'Update')
        self.assertNotIn('extra_button', ui.checklist.call_args.kwargs)
        self.assertFalse(result); ui.review.assert_not_called(); run.assert_not_called()

    def test_changed_app_blocks_batch_before_any_lifecycle(self):
        _, ui, run = self.select(['all'], fresh=AVAILABLE[1:])
        run.assert_not_called()
        self.assertIn('changed since', ui.message.call_args.args[0])

    def test_failure_or_per_app_cancel_stops_later_selections(self):
        _, _, run = self.select(['all'], outcomes=[False])
        self.assertEqual(run.call_count, 1)

    def test_declining_review_returns_to_selection_instead_of_updating(self):
        ui = Mock(); ui.checklist.side_effect = [['all'], []]; ui.review.return_value = False
        with patch.object(management, 'manage_instance') as run:
            self.assertFalse(updates.select_updates(ROOT, ui, AVAILABLE))
        run.assert_not_called()
        self.assertEqual(ui.checklist.call_args.args[2], ['110', '111'])


class StatusTests(unittest.TestCase):
    def checker(self):
        return updates.UpdateCheck(ROOT)

    def test_labels_show_cached_count_or_manual_check(self):
        checker = self.checker()
        self.assertEqual(checker.label({'available': []}), 'Check for updates')
        self.assertEqual(checker.label({'available': AVAILABLE}), 'Updates available (2)')
        checker.process = Mock(stdout=None); checker.process.poll.return_value = None
        self.assertEqual(checker.label({'available': AVAILABLE}), 'Checking for updates (0/0)')

    def test_partial_check_keeps_the_entry_clean_without_a_header_warning(self):
        checker = self.checker()
        state = {'checked': True, 'available': [], 'unknown': 1, 'applications': 2}
        self.assertEqual(checker.label(state), 'Check for updates')
        self.assertEqual(checker.notice(state), '')

    def test_completed_checks_show_only_the_update_count(self):
        state = {'checked': True, 'available': AVAILABLE, 'unknown': 0, 'applications': 2}
        self.assertEqual(self.checker().label(state), 'Updates available (2)')

    def progress_checker(self):
        reader, writer = os.pipe()
        stream = os.fdopen(reader, 'rb', buffering=0)
        self.addCleanup(stream.close); self.addCleanup(os.close, writer)
        os.set_blocking(reader, False)
        checker = self.checker(); checker.total = 24
        checker.process = Mock(stdout=stream); checker.process.poll.return_value = None
        return checker, writer

    def test_numeric_progress_redraws_only_when_the_count_changes(self):
        checker, writer = self.progress_checker()
        self.assertEqual(checker.label({}), 'Checking for updates (0/24)')
        self.assertFalse(checker.changed())
        os.write(writer, b'{"completed":12,"total":24}\n')
        self.assertTrue(checker.changed())
        self.assertEqual(checker.label({}), 'Checking for updates (12/24)')
        self.assertFalse(checker.changed())
        os.write(writer, b'{"completed":12,"total":24}\n')
        self.assertFalse(checker.changed())

    def test_split_and_invalid_worker_output_never_appears_in_the_menu(self):
        checker, writer = self.progress_checker()
        os.write(writer, b'password=secret\n{"completed":-1,"total":24}\n{"completed":')
        self.assertEqual(checker.label({}), 'Checking for updates (0/24)')
        os.write(writer, b'7,"total":24}\n{"completed":25,"total":24}\n')
        self.assertEqual(checker.label({}), 'Checking for updates (7/24)')

    def test_worker_failure_does_not_reuse_an_old_successful_result(self):
        checker = self.checker(); checker.process = Mock(stdout=None)
        checker.process.poll.return_value = checker.process.wait.return_value = 1
        old = {'checked': True, 'available': AVAILABLE, 'unknown': 0, 'applications': 2}
        with patch.object(checker.backend, 'cached', return_value=old):
            state = checker.status()
        self.assertEqual(checker.label(state), 'Check for updates')
        self.assertEqual(state['available'], [])
        self.assertEqual(checker.notice(state), 'The update check could not be completed. Try again later.')

    def test_finished_worker_keeps_the_final_redraw_pending_until_status_is_consumed(self):
        checker = self.checker(); checker.completed = checker.total = 2
        checker.process = Mock(stdout=None)
        checker.process.poll.return_value = checker.process.wait.return_value = 0
        self.assertFalse(checker.running)
        self.assertTrue(checker.active)
        self.assertEqual(checker.label({}), 'Checking for updates (2/2)')
        self.assertTrue(checker.changed())
        state = {'checked': True, 'available': AVAILABLE, 'unknown': 0, 'applications': 2}
        with patch.object(checker.backend, 'cached', return_value=state):
            final = checker.status()
        self.assertFalse(checker.active)
        self.assertEqual(checker.label(final), 'Updates available (2)')

    def test_check_process_is_isolated_and_displays_no_registry_errors(self):
        checker = self.checker()
        with patch.object(subprocess, 'Popen') as popen, patch.object(updates.os, 'set_blocking') as blocking, \
                patch.object(checker.backend, 'monitor_available', return_value=True):
            checker.start()
        args = popen.call_args
        self.assertTrue(args.kwargs['start_new_session'])
        self.assertEqual(args.kwargs['stderr'], subprocess.DEVNULL)
        self.assertEqual(args.args[0][1], str(ROOT / 'remote/oci_update_check.py'))
        self.assertIn('--progress', args.args[0])
        self.assertEqual(args.kwargs['stdout'], subprocess.PIPE)
        blocking.assert_called_once_with(checker.process.stdout.fileno(), False)

    def test_failed_applications_are_reported_and_cleared_by_a_new_check(self):
        checker = self.checker(); read, write = os.pipe()
        os.write(write, b'{"completed": 2, "total": 2}\n{"failed": [110]}\n'); os.close(write)
        os.set_blocking(read, False)
        checker.process = Mock(stdout=Mock(fileno=Mock(return_value=read)))
        checker.process.poll.return_value = checker.process.wait.return_value = 0
        state = {'checked': True, 'available': [], 'unknown': 1, 'applications': 2}
        with patch.object(checker.backend, 'cached', return_value=state) as cached:
            final = checker.status()
        os.close(read)
        self.assertEqual(cached.call_args.kwargs['failed'], {110})
        self.assertEqual(checker.notice(final),
                         'Some applications could not be checked (1). Try again later.')
        with patch.object(subprocess, 'Popen'), patch.object(updates.os, 'set_blocking'), \
                patch.object(checker.backend, 'monitor_available', return_value=True), \
                patch.object(checker.backend, 'cached', return_value=state):
            checker.start()
        self.assertEqual(checker.failed_applications, set())

    def test_a_failed_check_is_reported_in_the_menu(self):
        checker = self.checker(); checker.failed = True
        self.assertEqual(checker.notice({}), 'The update check could not be completed. Try again later.')

    def test_missing_monitor_never_starts_a_fallback_checker(self):
        checker = self.checker()
        with patch.object(checker.backend, 'monitor_available', return_value=False), \
                patch.object(subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(ValueError, 'ProxMenux Monitor'):
                checker.start()
        popen.assert_not_called()

    def test_cancelling_stops_the_worker_process_group(self):
        checker = self.checker(); process = Mock(); checker.process = process
        process.pid = 4321; process.poll.return_value = None
        with patch.object(updates.os, 'killpg') as kill:
            checker.close()
        kill.assert_called_once_with(4321, signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=2)

    def test_finished_worker_is_not_signalled_after_its_pid_could_be_reused(self):
        checker = self.checker(); checker.process = Mock(); checker.process.poll.return_value = 0
        with patch.object(updates.os, 'killpg') as kill:
            checker.close()
        kill.assert_not_called()


class DialogTests(unittest.TestCase):
    def test_status_change_redraws_menu_and_reaps_dialog(self):
        process = Mock(); process.poll.return_value = None
        process.communicate.side_effect = [subprocess.TimeoutExpired('dialog', .1), (None, '')]
        popen = Mock(); popen.__enter__ = Mock(return_value=process); popen.__exit__ = Mock(return_value=False)
        with patch.object(subprocess, 'Popen', return_value=popen):
            with self.assertRaises(MenuRefresh):
                DialogUI().choose('OCI', ReadableTags([('updates', 'Checking for updates...')]),
                                  'updates', size=(20, 75, 12), refresh=lambda: True)
        process.terminate.assert_called_once()
        self.assertEqual(process.communicate.call_count, 2)

    def test_escape_from_live_menu_remains_cancel(self):
        process = Mock(); process.poll.return_value = 255; process.returncode = 255
        process.communicate.return_value = (None, '')
        popen = Mock(); popen.__enter__ = Mock(return_value=process); popen.__exit__ = Mock(return_value=False)
        with patch.object(subprocess, 'Popen', return_value=popen):
            self.assertIsNone(DialogUI().choose('OCI', [('1', 'Checking')], refresh=lambda: False))
        process.terminate.assert_not_called()

    def test_checklist_starts_unselected_with_update_and_cancel_only(self):
        ui = DialogUI()
        with patch.object(ui, '_run', return_value=SimpleNamespace(returncode=0, stderr='111\n')) as run:
            picked = ui.checklist('Updates', [('all', 'Select all'), ('111', 'App')], [],
                                  ok_label='Update')
        self.assertEqual(picked, ['111'])
        widget = run.call_args.args[0]
        self.assertNotIn('--extra-button', widget)
        self.assertEqual(widget[widget.index('--ok-label') + 1], 'Update')
        self.assertNotIn('on', widget)


class MainMenuTests(unittest.TestCase):
    def test_status_changes_in_the_same_main_menu_entry(self):
        class Checker:
            running = False
            completed = 0
            @property
            def active(self): return self.running
            def __enter__(self): return self
            def __exit__(self, *exc): pass
            def start(self): self.running = True
            def status(self): return {'available': AVAILABLE if getattr(self, 'done', False) else []}
            def changed(self): return True
            def label(self, state):
                return (f'Checking for updates ({self.completed}/2)' if self.running else
                        'Updates available (2)' if state['available'] else 'Check for updates')
            def notice(self, state): return ''
        checker = Checker(); seen = []
        class UI:
            live_refresh = True
            def choose(self, text, entries, default, **kw):
                seen.append(dict(entries)['updates'])
                if len(seen) == 1: return 'updates'
                if len(seen) == 2:
                    checker.completed = 1
                    raise MenuRefresh()
                if len(seen) == 3:
                    checker.running = False; checker.done = True
                    raise MenuRefresh()
                return None
        with patch.object(cli, 'interactive_ui', return_value=UI()), \
                patch.object(updates, 'UpdateCheck', return_value=checker):
            self.assertEqual(cli.interactive(cli.Catalog(ROOT)), 0)
        self.assertEqual(seen, ['Check for updates', 'Checking for updates (0/2)',
                               'Checking for updates (1/2)', 'Updates available (2)'])


class TranslationTests(unittest.TestCase):
    def test_update_menu_literals_are_translated_in_every_shipped_language(self):
        source = ast.parse((ROOT / 'src/proxmenux_oci/updates.py').read_text())
        texts = {node.args[0].value for node in ast.walk(source)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == 'translate' and node.args
                 and isinstance(node.args[0], ast.Constant)}
        for path in sorted((ROOT.parent / 'lang').glob('*.json')):
            dictionary = json.loads(path.read_text())
            for text in texts:
                with self.subTest(locale=path.stem, text=text):
                    self.assertTrue(dictionary.get(text))
                    self.assertEqual(set(re.findall(r'\{\w+\}', text)),
                                     set(re.findall(r'\{\w+\}', dictionary[text])))


if __name__ == '__main__':
    unittest.main()
