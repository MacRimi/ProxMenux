"""Inert source-as-key checks for OCI update and recreation; no host modules imported."""
import ast
from contextlib import nullcontext
import copy
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
RECREATE = ROOT / 'oci/src/proxmenux_oci/recreation.py'
MANAGE = ROOT / 'oci/src/proxmenux_oci/management.py'
UPDATE = ROOT / 'oci/remote/oci_update_current.py'
OLD_CONFIRM = 'Apply the options from the current catalog template? Your data and configuration are kept.'
CONFIRM = ('Apply options from the current catalog template? New required paths and settings may be requested. '
           'Review the resulting configuration before recreating the CT.')
OLD_GUARD = 'The current template changes the image or identity; an explicit migration is required'
GUARD = 'The current template changes the template identity or image repository; an explicit migration is required'
OLD_PREVIEW = ('The current image of the saved channel will be checked and downloaded. Resources, paths and GPU are kept. '
               'The CT is stopped during the replacement and a native backup is created first.')
PREVIEW = ('The saved image channel is checked for a newer image. If replacement is needed, the CT is stopped and '
           'a native backup is verified before its root is replaced. Host directories are outside that backup.')


def extracted(path, name, scope):
    node = next(n for n in ast.parse(path.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
    return scope[name]


class RecreationWording(unittest.TestCase):
    def refresh(self, mutate, proceed=True):
        old = {'id': 'app-old', 'container_contract': {'image': {'repository': 'example/app', 'reference': 'example/app:v1'},
                                                        'volumes': [], 'environment': []},
               'proxmox': {'installer_profile': {}}, 'catalog_ui': {'title': 'old'}}
        latest = copy.deepcopy(old)
        mutate(latest)
        candidate = {'template': old, 'deployment': {'mounts': [], 'environment': [], 'security': {}}}
        events = []
        catalog_module = ModuleType('proxmenux_oci.catalog')
        class Catalog:
            def __init__(self, root):
                pass
            def load_index(self):
                return {'applications': [{'template_id': old['id'], 'id': 'app'}]}
            def compose(self, name):
                return latest
        catalog_module.Catalog = Catalog
        ui = SimpleNamespace(confirm=lambda message, default: events.append(('confirm', message, default)) or proceed,
                             info=lambda message: events.append(('info', message)))
        scope = {'__package__': 'proxmenux_oci', '__file__': str(RECREATE), 'Path': Path, 're': re,
                 'translate': lambda text: text, 'copy': copy}
        with patch.dict(sys.modules, {'proxmenux_oci.catalog': catalog_module}):
            try:
                extracted(RECREATE, 'refresh_template', scope)(candidate, ui)
            except ValueError as error:
                events.append(('error', str(error)))
        return candidate, events

    def test_confirmation_describes_followup_without_preservation_guarantee(self):
        candidate, events = self.refresh(lambda latest: latest['catalog_ui'].update(title='new'), proceed=False)
        self.assertEqual(events, [('confirm', CONFIRM, True)])
        self.assertEqual(candidate['template']['catalog_ui']['title'], 'old')
        self.assertNotIn(OLD_CONFIRM, str(events))

    def test_guard_names_exact_rejected_identity_and_repository_changes(self):
        for change in (lambda latest: latest.update(id='app-new'),
                       lambda latest: latest['container_contract']['image'].update(repository='other/app')):
            with self.subTest(change=change):
                candidate, events = self.refresh(change)
                self.assertEqual(events, [('confirm', CONFIRM, True), ('error', GUARD)])
                self.assertEqual(candidate['template']['id'], 'app-old')

    def test_same_repository_new_tag_does_not_trigger_migration_guard(self):
        candidate, events = self.refresh(lambda latest: latest['container_contract']['image'].update(reference='example/app:v2'))
        self.assertEqual(events, [('confirm', CONFIRM, True)])
        self.assertEqual(candidate['template']['container_contract']['image']['reference'], 'example/app:v2')


class UpdateWording(unittest.TestCase):
    def test_actual_native_backup_verification_succeeds_or_fails_before_replacement(self):
        transaction = ROOT / 'oci/remote/oci_instance_transaction.py'
        for failures in (1, 2):
            with self.subTest(failed_integrity_checks=failures), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                archive = directory / 'vzdump-lxc-101.tar.zst'
                calls = []
                def inert_run(*args):
                    calls.append(args)
                    if args[0] == 'vzdump':
                        archive.write_bytes(b'inert fixture')
                    elif args[0] == 'zstd' and sum(call[0] == 'zstd' for call in calls) <= failures:
                        raise RuntimeError('invalid backup')
                scope = {'run': inert_run, 'log': lambda text: None,
                         'msg_warn': lambda text: None, 'translate': lambda text: text}
                backup = extracted(transaction, 'verified_backup', scope)
                if failures == 2:
                    with self.assertRaisesRegex(RuntimeError, 'invalid backup'):
                        backup(101, directory, 'zstd', 'missing backup')
                else:
                    self.assertEqual(backup(101, directory, 'zstd', 'missing backup'), archive)
                self.assertEqual([call[0] for call in calls], ['vzdump', 'zstd', 'vzdump', 'zstd'])
                self.assertTrue(all(call[call.index('--mode') + 1] == 'stop'
                                    for call in calls if call[0] == 'vzdump'))
        apply_source = transaction.read_text()
        apply_node = next(n for n in ast.parse(apply_source).body
                          if isinstance(n, ast.FunctionDef) and n.name == 'apply')
        calls = [(n.lineno, n.func.id) for n in ast.walk(apply_node) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id in ('verified_backup', 'checkpoint', 'install_candidate')]
        backup_line = next(line for line, name in calls if name == 'verified_backup')
        ready_line = next(line for line, name in calls if name == 'checkpoint' and line > backup_line)
        install_line = next(line for line, name in calls if name == 'install_candidate')
        self.assertLess(backup_line, ready_line)
        self.assertLess(ready_line, install_line)

    def test_preview_blocks_lifecycle_when_cancelled_and_keeps_command_on_accept(self):
        events = []
        instances = ModuleType('oci_instances')
        instances.ROOT = Path('/inert')
        instances.read = lambda root, vmid: {'status': 'installed'}
        instances.command = lambda *args: b'description: owned'
        reconcile = ModuleType('oci_instance_reconcile')
        reconcile.propose = lambda *args: None
        scope = {'sys': SimpleNamespace(path=[], executable='python3'),
                 'translate': lambda text: text, 'check_selected': lambda project, row: row,
                 'images': SimpleNamespace(offer_removal=lambda *args: None),
                 '_run_lifecycle': lambda command, title: events.append(('run', command, title)) or True}
        row = {'vmid': 101, 'reason': 'matched', 'stack': False, 'pending': False, 'status': 'installed'}
        decision = False
        def review(message, title, **kwargs):
            events.append(('review', message, title, kwargs))
            return decision
        ui = SimpleNamespace(review=review, unattended=True)
        with patch.dict(sys.modules, {'oci_instances': instances, 'oci_instance_reconcile': reconcile}):
            manage = extracted(MANAGE, 'manage_instance', scope)
            self.assertFalse(manage(ROOT / 'oci', ui, row, action='update'))
            self.assertEqual(events, [('review', PREVIEW, 'Update OCI', {'question': 'Update now?', 'default': True})])
            decision = True
            self.assertTrue(manage(ROOT / 'oci', ui, row, action='update'))
        self.assertEqual(events[-1], ('run', ['python3', str(ROOT / 'oci/remote/oci_update_current.py'), '101',
                                             '--acknowledge-external-data'], 'Update OCI'))
        self.assertNotIn(OLD_PREVIEW, str(events))

    def test_noop_image_digest_returns_before_any_backup_or_apply(self):
        events = []
        record = {'status': 'installed', 'observed': {'image': {'manifest_digest': 'sha256:current'}}}
        instances = SimpleNamespace(ROOT=Path('/inert'), locked=lambda root: nullcontext(),
                                    read=lambda root, vmid: record, command=lambda *args: b'arch: amd64')
        transaction = SimpleNamespace(candidate_contract=lambda *args: {'deployment': {}},
                                      external_changes=lambda *args: {}, preflight=lambda *args: None,
                                      require_backup_space=lambda *args: self.fail('backup space checked on no-op'),
                                      apply=lambda *args, **kwargs: self.fail('apply on no-op'))
        scope = {'instances': instances, 'transaction': transaction,
                 'translate': lambda text: text,
                 'msg_info': lambda text: events.append(text), 'msg_ok': lambda text: events.append(text),
                 'resolve_archive': lambda desired, config, current, check: (None, current),
                 'kept_settings': lambda *args: self.fail('kept settings on no-op')}
        extracted(UPDATE, 'update', scope)(101, keep_backup='not-a-real-storage')
        self.assertIn('The image is already up to date; nothing was changed.', events)

    def test_new_keys_extracted_and_shipped_and_missing_locale_fallback(self):
        generator = runpy.run_path(str(ROOT / '.github/scripts/build_translation_cache.py'))
        found = generator['extract_python_texts']([ROOT / 'oci/src', ROOT / 'oci/remote'])
        for key in (CONFIRM, GUARD, PREVIEW):
            self.assertIn(key, found)
        scope = {'json': json, 'Path': Path, 'BASE_DIR': ROOT,
                 '_language': 'it', '_cache': None}
        lookup = extracted(ROOT / 'oci/src/proxmenux_oci/i18n.py', 'translate', scope)
        scope['language'] = lambda: scope['_language']
        for path in sorted((ROOT / 'lang').glob('*.json')):
            scope['_language'] = path.stem
            scope['_cache'] = None
            values = json.loads(path.read_text())
            for key in (CONFIRM, GUARD, PREVIEW):
                self.assertEqual(lookup(key), values.get(key) or key, (path.name, key))
        scope['_language'] = 'it'
        for key in (CONFIRM, GUARD, PREVIEW):
            scope['_cache'] = {}
            self.assertEqual(lookup(key), key, ('missing', key))
            scope['_cache'] = {key: 'LOCALIZED: ' + key}
            self.assertEqual(lookup(key), 'LOCALIZED: ' + key, ('synthetic', key))

if __name__ == '__main__':
    unittest.main()
