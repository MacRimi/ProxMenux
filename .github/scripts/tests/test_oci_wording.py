"""Offline OCI wording seams; compile actual functions, never import operational modules."""
import ast
import importlib.util
import io
import json
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
CUSTOM = ROOT / 'oci/src/proxmenux_oci/custom.py'
TRANSACTION = ROOT / 'oci/remote/oci_instance_transaction.py'
MENU = ROOT / 'oci/src/proxmenux_oci/management.py'
CHOICE = 'Recover the previous installation'
BEFORE = 'The operation stopped halfway. Choose "{choice}" for this container in the OCI management menu.'
AFTER = 'The recovery did not complete. Review the log and choose "{choice}" again for this container in the OCI management menu.'
NEW_KEYS = (
    'The Compose file describes several services:',
    'Only one service at a time can be installed this way.',
    'No docker run command was given',
    'Image selection was cancelled',
    'Could not inspect the image in its registry:',
    'Check the image reference and registry access. If the registry is unavailable, try again later. A private registry needs credentials, which are not supported yet.',
    BEFORE, AFTER,
)


class ConversionError(Exception):
    pass


class UserCancelled(Exception):
    pass


def function(path, name, **dependencies):
    node = next(n for n in ast.parse(path.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    # Only read_definition's infrastructure import is omitted; keep the function intact.
    if name == 'read_definition':
        node.body = [n for n in node.body if not isinstance(n, ast.ImportFrom)]
    scope = dict(translate=lambda text: text, ConversionError=ConversionError,
                 UserCancelled=UserCancelled, Any=Any, yaml=__import__('yaml'), json=json,
                 Path=Path, MENU_SIZE=(20, 80), MAX_COMPOSE_BYTES=256*1024)
    scope.update(dependencies)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(path), 'exec'), scope)
    return scope[name]


class OciWordingTests(TestCase):
    def test_extractor_shipped_locales_and_synthetic_fallback(self):
        generator = runpy.run_path(str(ROOT / '.github/scripts/build_translation_cache.py'))
        extracted = generator['extract_python_texts']([ROOT / 'oci/src', ROOT / 'oci/remote'])
        self.assertEqual(len(NEW_KEYS), len(set(NEW_KEYS)))
        self.assertTrue(set(NEW_KEYS) <= set(extracted), set(NEW_KEYS) - set(extracted))
        spec = importlib.util.spec_from_file_location('oci_i18n', ROOT / 'oci/src/proxmenux_oci/i18n.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        paths = sorted((ROOT / 'lang').glob('*.json'))
        self.assertEqual(len(paths), 7)
        for path in paths:
            cache = json.loads(path.read_text())
            setattr(module, '_language', path.stem)
            setattr(module, '_cache', cache)
            for key in NEW_KEYS:
                self.assertEqual(module.translate(key), cache.get(key) or key, (path.name, key))
            setattr(module, '_cache', {})
            for key in NEW_KEYS:
                self.assertEqual(module.translate(key), key, (path.name, key, 'synthetic missing'))
            setattr(module, '_cache', {NEW_KEYS[0]: 'Several services (translated):'})
            self.assertEqual(module.translate(NEW_KEYS[0]), 'Several services (translated):')

    def test_multiple_services_named_not_images(self):
        template = function(CUSTOM, 'template_from_compose',
            _services=lambda doc: doc['services'], _check_mounts=lambda _: None)
        with self.assertRaises(ConversionError) as caught:
            template(json.dumps({'services': {'alpha': {'image': 'same:latest'},
                                              'beta': {'image': 'same:latest'}}}))
        self.assertEqual(str(caught.exception),
                         'The Compose file describes several services: alpha, beta. '
                         'Only one service at a time can be installed this way.')

    def test_empty_paste_is_specific_and_nonempty_unchanged(self):
        for title, expected in ((None, 'No Compose file was given'),
                                ('docker run command of the application', 'No docker run command was given')):
            def paste(content):
                return function(CUSTOM, '_read_pasted',
                    console=SimpleNamespace(show_logo=lambda: None, msg_title=lambda *_: None,
                                            msg_info2=lambda *_: None),
                    sys=SimpleNamespace(stdin=io.StringIO(content)))
            with self.assertRaises(UserCancelled) as caught:
                paste('')(None, title)
            self.assertEqual(str(caught.exception), expected)
            self.assertEqual(paste('  literal input\n')(None, title), '  literal input\n')

    def test_cancelled_image_menu(self):
        with self.assertRaises(UserCancelled) as caught:
            function(CUSTOM, 'read_definition')(SimpleNamespace(choose=lambda *_, **__: None))
        self.assertEqual(str(caught.exception), 'Image selection was cancelled')

    def test_registry_nonzero_and_success_command_unchanged(self):
        result = SimpleNamespace(returncode=1, stdout='', stderr='connection timed out')
        run = Mock(return_value=result)
        report = function(CUSTOM, 'registry_report', subprocess=SimpleNamespace(run=run))
        self.assertEqual(report('example:latest'),
                         (False, 'Could not inspect the image in its registry: example:latest'))
        run.assert_called_once_with(['skopeo', 'inspect', '--raw', 'docker://example:latest'],
                                    capture_output=True, text=True, check=False, timeout=120)
        run.reset_mock()
        run.return_value = SimpleNamespace(returncode=0,
            stdout='{"manifests":[{"platform":{"architecture":"amd64"}}]}', stderr='')
        self.assertEqual(report('example:latest'), (True, 'The image is in its registry: amd64'))
        self.assertEqual(run.call_count, 1)

    def test_failed_registry_inspection_has_neutral_advice(self):
        ui = SimpleNamespace(message=Mock())
        fn = function(CUSTOM, 'explore', read_definition=lambda _: ('definition', 'source'),
            ignored_settings=lambda _: [], template_from_compose=lambda _: {
                'container_contract': {'image': {'reference': 'example:latest'}}},
            describe=lambda _: 'SUMMARY', registry_report=lambda _: (False, 'INSPECTION FAILED'))
        fn(ui)
        self.assertEqual(ui.message.call_args.args[0], 'SUMMARY\n\nINSPECTION FAILED\n\n'
            'Check the image reference and registry access. If the registry is unavailable, '
            'try again later. A private registry needs credentials, which are not supported yet.')

    def test_recovery_hint_quotes_translated_choice_in_all_locales(self):
        # Pin the real translated management choice, not an English AST constant alone.
        source = ast.parse(MENU.read_text())
        self.assertTrue(any(isinstance(n, ast.Tuple) and len(n.elts) == 2
            and isinstance(n.elts[0], ast.Constant) and n.elts[0].value == 'recover'
            and isinstance(n.elts[1], ast.Call) and isinstance(n.elts[1].func, ast.Name)
            and n.elts[1].func.id == 'translate' and n.elts[1].args
            and isinstance(n.elts[1].args[0], ast.Constant)
            and n.elts[1].args[0].value == CHOICE for n in ast.walk(source)))
        spec = importlib.util.spec_from_file_location('oci_remote_ui', ROOT / 'oci/remote/oci_ui.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for path in sorted((ROOT / 'lang').glob('*.json')):
            cache = json.loads(path.read_text())
            setattr(module, '_language', path.stem)
            setattr(module, '_cache', cache)
            warnings = []
            hint = function(TRANSACTION, 'recovery_hint', translate=module.translate,
                            msg_warn=warnings.append)
            hint()
            hint(after_recovery=True)
            label = module.translate(CHOICE)
            self.assertNotEqual(label, CHOICE, path.name)
            expected = [(cache.get(key) or key).replace('{choice}', label)
                        if '{choice}' in (cache.get(key) or key) else key.replace('{choice}', label)
                        for key in (BEFORE, AFTER)]
            self.assertEqual(warnings, expected, path.name)
            # An intentionally absent message key proves fallback independently of shipped catalogs.
            setattr(module, '_cache', {CHOICE: label})
            warnings.clear()
            hint()
            hint(after_recovery=True)
            self.assertEqual(warnings, [BEFORE.replace('{choice}', label),
                                        AFTER.replace('{choice}', label)], (path.name, 'synthetic missing'))

    def test_recovery_hint_uses_translated_whole_messages_and_malformed_fallback(self):
        spec = importlib.util.spec_from_file_location('oci_remote_ui', ROOT / 'oci/remote/oci_ui.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module._language = 'it'
        for translation in ('Before: «{choice}».', 'Before: label missing.'):
            module._cache = {CHOICE: 'Recupero', BEFORE: translation,
                             AFTER: 'After: «{choice}».'}
            warnings = []
            hint = function(TRANSACTION, 'recovery_hint', translate=module.translate,
                            msg_warn=warnings.append)
            hint()
            hint(after_recovery=True)
            self.assertEqual(warnings, [
                ('Before: «Recupero».' if '{choice}' in translation
                 else BEFORE.replace('{choice}', 'Recupero')),
                'After: «Recupero».'])
