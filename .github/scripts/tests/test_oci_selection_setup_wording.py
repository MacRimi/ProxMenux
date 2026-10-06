"""Inert extracted OCI selection/setup consumers; no admin module imports or scripts sourced."""
import ast
import importlib.util
import json
import tempfile
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
MENU = ROOT / 'oci/src/proxmenux_oci/management.py'
OLD_EMPTY = 'No OCI instances are registered.'
EMPTY = 'No registered OCI containers are available for selection on this host.'
OLD_REPLAY = 'This stack requires replaying specific rootfs adaptations. Coordinated updates are not yet enabled for it.'
NO_MEMBERS = 'This stack has no saved members to update.'
REPLAY = 'This stack needs rootfs adaptations that coordinated updates cannot replay yet.'
HTTP = 'The application did not pass its HTTP check:'


def extracted(name, **dependencies):
    node = next(n for n in ast.parse(MENU.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    # Drop only infrastructure imports, retaining all selection, guard, and return logic.
    node.body = [n for n in node.body if not (isinstance(n, ast.Import) and
                 any(a.name == 'oci_instances' or a.name == 'oci_stack_replay' for a in n.names))]
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.With)):
            n.body = [x for x in n.body if not (isinstance(x, ast.Import) and
                      any(a.name in ('oci_instances', 'oci_stack_replay') for a in x.names))]
    scope = dict(dependencies)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(MENU), 'exec'), scope)
    return scope[name]


class SelectionSetupWording(TestCase):
    def test_selector_empty_explains_availability_not_registry_absence(self):
        ui = SimpleNamespace(message=Mock(), choose=Mock())
        fn = extracted('_interactive_management', os=SimpleNamespace(geteuid=lambda: 0),
            shutil=SimpleNamespace(which=lambda _: '/fake/pct'), saved_inventory=lambda _: [],
            _clean_orphans=lambda project: None,
            recover_automatically=lambda project: None, offer_recovery=lambda project, ui: None,
            carry_records=lambda project, **options: {},
            translate=lambda s: s)
        fn(Path('/fixture'), ui)
        ui.message.assert_called_once_with(EMPTY, 'OCI management')
        ui.choose.assert_not_called()

    def test_selector_filters_missing_guest_without_erasing_saved_contract(self):
        class Entry:
            name = '101'
        class Lock:
            def __enter__(self): return None
            def __exit__(self, *_): return False
        fake = SimpleNamespace(ROOT=SimpleNamespace(iterdir=lambda: [Entry()]),
            locked=lambda _: Lock(), has_contract=lambda *args: True,
            guest_exists=lambda _: False, read=Mock())
        fn = extracted('saved_inventory', sys=SimpleNamespace(path=[]),
            instances=fake, public_row=Mock())
        self.assertEqual(fn(Path('/fixture')), [])
        fake.read.assert_not_called()

    def test_stack_without_members_is_not_diagnosed_as_replay_failure(self):
        self._stack({}, NO_MEMBERS).choose.assert_not_called()

    def test_stack_unsupported_replay_retains_distinct_verdict(self):
        # It cannot be updated, but it can still be changed or removed.
        ui = self._stack({'members': [{'native_stack_intent': {'adapt': True}}]}, REPLAY)
        ui.choose.assert_called_once()
        self.assertEqual([tag for tag, _ in ui.choose.call_args.args[1]], ['modify', 'remove'])

    def _stack(self, stack, expected):
        record = {'stack': stack}
        fake = SimpleNamespace(ROOT=Path('/fixture'), read=lambda *args: record)
        replay = SimpleNamespace(**{n + '_menu_ready': lambda _: False
            for n in ('nextcloud', 'paperless', 'tandoor', 'immich')})
        ui = SimpleNamespace(message=Mock(), choose=Mock(return_value=None), review=Mock())
        fn = extracted('_manage_stack', sys=SimpleNamespace(path=[]), instances=fake,
            oci_stack_replay=replay, translate=lambda s: s)
        self.assertFalse(fn(Path('/fixture'), ui, {'vmid': 101}))
        ui.message.assert_called_once_with(expected, 'OCI stack management')
        ui.review.assert_not_called()
        return ui

    def test_actual_http_failure_seams_preserve_app_and_log_redirect(self):
        for app, port in (('paperless', ':8000'), ('tandoor', '')):
            with self.subTest(app=app):
                path = ROOT / f'oci/remote/install_{app}_stack.sh'
                lines = path.read_text().splitlines()
                start = next(i for i, line in enumerate(lines) if line.strip().startswith('curl -fsS "http://${APPLICATION_LAN_IP}' + port + '/" >/dev/null 2>>"$OCI_LOG"'))
                command = '\n'.join(lines[start:start + (3 if app == 'tandoor' else 2)])
                # Actual Bash failure expression, never source the parent installer.
                harness = '''set -u
APPLICATION_LAN_IP=192.0.2.1
APPLICATION_ID=101
OCI_LOG=/dev/null
curl() { return 7; }
translate() { printf '%s' "$1"; }
print_first_boot_diagnostics() { :; }
die() { printf 'ERROR:%s\\n' "$1"; }
''' + command + '\n'
                run = subprocess.run(['bash', '-c', harness], text=True,
                                     capture_output=True, timeout=3)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(run.stdout.strip(),
                                 f'ERROR:{HTTP} {"Paperless-ngx" if app == "paperless" else "Tandoor"}')
                self.assertIn('2>>"$OCI_LOG"', command)

    def test_nextcloud_explicit_setup_guard_kept(self):
        source = (ROOT / 'oci/remote/install_nextcloud_stack.sh').read_text()
        self.assertIn("jq -e '.installed == true and .maintenance == false and .needsDbUpgrade == false'", source)
        self.assertIn('die "$(translate "The application did not complete its initial setup:") Nextcloud"', source)

    def test_shell_lookup_shipped_missing_and_synthetic_translation(self):
        source = (ROOT / 'oci/remote/oci_ui.sh').read_text()
        start = source.index('translate() {')
        fn = source[start:source.index('\n}', start) + 2]
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'missing.json'
            missing.write_text('{}')
            translated = Path(tmp) / 'translated.json'
            translated.write_text(json.dumps({HTTP: 'VERIFICA HTTP FALLITA:'}))
            for path in [*sorted((ROOT / 'lang').glob('*.json')), missing, translated]:
                cache = json.loads(path.read_text())
                bash = '_OCI_LANGUAGE=it\n_OCI_LANG_FILE="$1"\n' + fn + '\ntranslate "$2"\n'
                result = subprocess.run(['bash', '-c', bash, 'fixture', str(path), HTTP],
                                        text=True, capture_output=True, timeout=3)
                self.assertEqual(result.returncode, 0, (path, result.stderr))
                self.assertEqual(result.stdout, cache.get(HTTP) or HTTP, path)

    def test_extraction_and_real_lookup_all_locales(self):
        import runpy
        generator = runpy.run_path(str(ROOT / '.github/scripts/build_translation_cache.py'))
        extracted_keys = generator['extract_python_texts']([ROOT / 'oci/src', ROOT / 'oci/remote'])
        for key in (EMPTY, NO_MEMBERS, REPLAY):
            self.assertIn(key, extracted_keys)
        shell_keys = generator['extract_translate_texts'](ROOT / 'oci/remote')
        self.assertIn(HTTP, shell_keys)
        spec = importlib.util.spec_from_file_location('oci_i18n', ROOT / 'oci/src/proxmenux_oci/i18n.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for path in sorted((ROOT / 'lang').glob('*.json')):
            cache = json.loads(path.read_text())
            module._language, module._cache = path.stem, cache
            for key in (EMPTY, NO_MEMBERS, REPLAY, HTTP):
                self.assertEqual(module.translate(key), cache.get(key) or key)
            module._cache = {}
            self.assertEqual(module.translate(EMPTY), EMPTY)
            module._cache = {EMPTY: 'LOCALIZED SELECTOR'}
            self.assertEqual(module.translate(EMPTY), 'LOCALIZED SELECTOR')
