"""Offline checks of real OCI messages; never import administrative modules."""
import ast
import importlib.util
import json
from pathlib import Path
import re
import runpy
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MENU = ROOT / 'oci/src/proxmenux_oci/management.py'
REMOVE = ROOT / 'oci/remote/oci_remove.py'
PREVIEW_HOST = 'Host paths found in container configs or saved records (not targeted for removal):'
EMPTY_HOST = 'No host directories found in the available container configs or saved records.'
POST_HOST = 'Host directory listed in saved records (not targeted for removal):'
UPDATE = ('All images are downloaded and verified first, and native backups are taken with the stack stopped. '
          'Contracts are published after the whole set is checked. If a step fails, recovery is attempted '
          'where needed; recovery can also fail.')
PENDING = ('A coordinated operation has a saved journal. Continuing attempts to recover the previous stack '
           'where needed, or finish cleanup for a completed operation. Recovery or cleanup can fail.')
KEYS = (PREVIEW_HOST, EMPTY_HOST, POST_HOST, UPDATE, PENDING)
TRANSACTION = ROOT / 'oci/remote/oci_stack_transaction.py'


def extracted(path, name, scope):
    node = next(n for n in ast.parse(path.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
    return scope[name]


class InventoryMessages(unittest.TestCase):
    def preview(self, configs, records, cache=None, translate=lambda text: text):
        instances = ModuleType('oci_instances')
        instances.ROOT = Path('/inert')
        def read(root, vmid):
            if vmid not in records:
                raise OSError('unreadable record')
            return records[vmid]
        instances.read = read
        remover = ModuleType('oci_remove')
        remover.members_of = lambda root, vmid: (101, {}, [102, 101])
        remover.guest_config = lambda vmid: configs.get(vmid)
        remover.host_directories = lambda root, members: cache or []
        remover.private_bridge = lambda primary: None
        state = ModuleType('oci_installation_state')
        state.parse_config = lambda raw: dict(line.split(': ', 1) for line in raw.decode().splitlines())
        scope = {'sys': SimpleNamespace(path=[]), 'source_text': lambda text: text or '',
                 'translate': translate, 're': re}
        summary = extracted(MENU, '_removal_summary', scope)
        with patch.dict(sys.modules, {'oci_instances': instances, 'oci_remove': remover,
                                      'oci_installation_state': state}):
            return summary(Path('/inert'), 101)

    def test_missing_metadata_is_not_reported_as_no_host_usage(self):
        text = self.preview({101: None, 102: None}, {})
        self.assertIn(EMPTY_HOST, text)
        self.assertNotIn('No host directory is used by this application.', text)

    def test_discovered_paths_do_not_promise_exhaustive_preservation(self):
        text = self.preview({101: b'mp0: /bind/current,mp=/data\n', 102: None}, {}, ['/bind/saved'])
        self.assertIn(PREVIEW_HOST + '\n  /bind/current\n  /bind/saved', text)
        self.assertNotIn('Host directories that are kept, with their content:', text)

    def test_removal_notice_qualifies_saved_record_source(self):
        events = []
        scope = {'members_of': lambda root, vmid: (101, {}, [101]),
                 'instances': SimpleNamespace(read=lambda root, vmid: {'installation_id': 'owned'},
                    identity=lambda raw: 'owned', location=lambda root, vmid: Path('/inert/absent/record.json')),
                 'guest_config': lambda vmid: b'description: owned',
                 'host_directories': lambda root, members: ['/bind/saved'],
                 'private_bridge': lambda primary: None,
                 'run': lambda *args: events.append(('run', args)),
                 'subprocess': SimpleNamespace(run=lambda *args, **kwargs: None),
                 'Path': Path, 'shutil': SimpleNamespace(rmtree=lambda path: None),
                 'image_cache': SimpleNamespace(prune=lambda root, lock: []),
                 'translate': lambda text: text,
                 'msg_info': lambda text: events.append(('info', text)),
                 'msg_ok': lambda text: events.append(('ok', text)),
                 'msg_warn': lambda text: events.append(('warn', text))}
        remove = extracted(REMOVE, 'remove', scope)
        remove(Path('/inert'), 101)
        self.assertIn(('warn', POST_HOST + ' /bind/saved'), events)
        self.assertIn(('run', ('pct', 'destroy', '101', '--purge', '1', '--destroy-unreferenced-disks', '1')), events)
        scope['translate'] = lambda text: 'Tradotto: ' + text if text == POST_HOST else text
        events.clear()
        remove(Path('/inert'), 101)
        self.assertIn(('warn', 'Tradotto: ' + POST_HOST + ' /bind/saved'), events)


class RecoveryMessages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal = Path(self.tmp.name) / 'journal.json'
        self.members = [{'vmid': 101, 'deployment': {'mounts': []}}]
        self.primary = {'stack': {'members': self.members}}
        self.calls = []
        instances = ModuleType('oci_instances')
        instances.ROOT = Path('/inert')
        instances.read = lambda root, vmid: self.primary
        self.modules = {'oci_instances': instances, 'oci_stack_replay': ModuleType('oci_stack_replay')}
        self.scope = {'sys': SimpleNamespace(path=[], executable='python3'), 'Path': Path,
                      'translate': lambda text: text, 'images': SimpleNamespace(offer_removal=lambda *args: None),
                      '_remove': lambda *args: self.fail('remove must not run'),
                      '_run_lifecycle': lambda command, title: self.calls.append((command, title)) or False}
        self.ui = SimpleNamespace(
            choose=lambda *args: 'update',
            review=lambda message, *args, **kwargs: self.calls.append(('review', message)) or False,
            confirm=lambda *args: self.fail('host confirmation must not run'),
            message=lambda *args: self.fail('unexpected error'))

    def manage(self):
        with patch.dict(sys.modules, self.modules):
            extracted(MENU, '_manage_stack', self.scope)(Path('/inert'), self.ui, {'vmid': 101})
        return next(message for kind, message in self.calls if kind == 'review')

    def test_update_preview_describes_recovery_attempt_not_guarantee(self):
        message = self.manage()
        self.assertIn(UPDATE, message)
        self.assertNotIn('all members are recovered', message)

    def test_pending_terminal_and_recovery_failed_states_share_bounded_wording(self):
        for phase in ('committed', 'rolled-back', 'recovery-failed'):
            with self.subTest(phase=phase):
                self.calls.clear()
                self.journal.write_text(json.dumps({'phase': phase, 'plan': {'members': self.members}}))
                self.primary['pending_stack_transaction'] = str(self.journal)
                self.assertEqual(self.manage(), PENDING)
                self.assertFalse(any(isinstance(item[0], list) for item in self.calls))

    def test_pending_confirmation_preserves_recover_command_in_each_state(self):
        self.ui.review = lambda message, *args, **kwargs: True
        for phase in ('committed', 'recovery-failed'):
            with self.subTest(phase=phase):
                self.calls.clear()
                self.journal.write_text(json.dumps({'phase': phase, 'plan': {'members': self.members}}))
                self.primary['pending_stack_transaction'] = str(self.journal)
                with patch.dict(sys.modules, self.modules):
                    extracted(MENU, '_manage_stack', self.scope)(Path('/inert'), self.ui, {'vmid': 101})
                self.assertEqual(self.calls, [
                    (['python3', '/inert/remote/oci_stack_native.py', '101', '--recover',
                      '--acknowledge-external-data'], 'Recover OCI stack')])

    def test_actual_transaction_distinguishes_terminal_cleanup_from_failed_restore(self):
        events = []
        scope = {'TERMINAL': {'committed', 'rolled-back'},
                 'translate': lambda message: message,
                 'member_tx': SimpleNamespace(log=lambda message: None),
                 'write': lambda path, state: Path(path).write_text(json.dumps(state)),
                 'msg_info': lambda message: None, 'msg_ok': lambda message: None,
                 'member': lambda adapter, vmid: f'CT {vmid}'}
        extracted(TRANSACTION, 'save', scope)
        recover = extracted(TRANSACTION, 'recover_state', scope)
        class Adapter:
            def finalize(self, state): events.append('finalize')
            def validate(self, plan): events.append('validate')
            def restore(self, vmid, backup, txid):
                events.append('restore')
                raise RuntimeError('restore failed')
            def stop(self, vmid): events.append('stop')
        plan = {'start_order': [101], 'stop_order': [101]}
        terminal = {'phase': 'committed', 'plan': plan}
        self.assertIs(recover(self.journal, terminal, Adapter()), terminal)
        self.assertEqual(events, ['finalize'])
        events.clear()
        failed = dict(terminal, phase='recovery-failed', id='tx', running={'101': True},
                      stop_intent=True, replacement_intent=True, backups={'101': {'archive': 'a'}})
        with self.assertRaisesRegex(RuntimeError, 'restore failed'):
            recover(self.journal, failed, Adapter())
        self.assertEqual(events, ['validate', 'stop', 'restore'])
        self.assertEqual(json.loads(self.journal.read_text())['phase'], 'recovery-failed')

    def test_new_keys_extract_and_shipped_fallback_and_synthetic_translation(self):
        generator = runpy.run_path(str(ROOT / '.github/scripts/build_translation_cache.py'))
        found = generator['extract_python_texts']([ROOT / 'oci/src', ROOT / 'oci/remote'])
        self.assertEqual(len(KEYS), len(set(KEYS)))
        self.assertTrue(set(KEYS) <= set(found), set(KEYS) - set(found))
        spec = importlib.util.spec_from_file_location('oci_i18n', ROOT / 'oci/src/proxmenux_oci/i18n.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        paths = sorted((ROOT / 'lang').glob('*.json'))
        self.assertEqual(len(paths), 7)
        for path in paths:
            cache = json.loads(path.read_text())
            setattr(module, '_language', path.stem)
            setattr(module, '_cache', cache)
            for key in KEYS:
                self.assertEqual(module.translate(key), cache.get(key) or key, (path.name, key))
            setattr(module, '_cache', {})
            for key in KEYS:
                self.assertEqual(module.translate(key), key, (path.name, key, 'synthetic missing'))
        module._language, module._cache = 'it', {key: 'Tradotto: ' + key for key in KEYS}
        self.assertEqual(module.translate(EMPTY_HOST), 'Tradotto: ' + EMPTY_HOST)
        preview = InventoryMessages().preview({101: None, 102: None}, {}, translate=module.translate)
        self.assertIn('Tradotto: ' + EMPTY_HOST, preview)
        preview = InventoryMessages().preview({101: b'mp0: /bind,mp=/data'}, {},
                                              translate=module.translate)
        self.assertIn('Tradotto: ' + PREVIEW_HOST + '\n  /bind', preview)
        # Exercise the actual management consumer, not just the provider.
        self.scope['translate'] = module.translate
        self.assertIn('Tradotto: ' + UPDATE, self.manage())
        self.journal.write_text(json.dumps({'phase': 'committed', 'plan': {'members': self.members}}))
        self.primary['pending_stack_transaction'] = str(self.journal)
        self.calls.clear()
        self.assertEqual(self.manage(), 'Tradotto: ' + PENDING)


if __name__ == '__main__':
    unittest.main()
