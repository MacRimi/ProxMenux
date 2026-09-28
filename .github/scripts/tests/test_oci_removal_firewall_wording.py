"""Exercise extracted removal/UI/guard consumers with inert dependencies only."""
import ast
import argparse
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MENU = ROOT / 'oci/src/proxmenux_oci/management.py'
REMOVE = ROOT / 'oci/remote/oci_remove.py'
INSTALL = ROOT / 'oci/remote/install_oci.sh'
PREVIEW = 'Private network targeted for release if no other guest uses it:'
CONFIRM = ('Remove the application? Its container disks are targeted for deletion; '
           'recovery from backups is not checked here.')
RESULT = 'Removal command finished; review any warnings above.'
BRIDGE = 'Private network release attempted:'
FIREWALL = 'Could not verify removal of the managed host firewall rule.'
PORT = 'The host-monitor firewall port does not match exactly one TCP port in the container contract'
OPTIONAL = 'A matching managed host firewall rule may also be removed.'
MEMBERS = 'All of them are targeted for removal.'
WHOLE = ('It cannot be removed on its own, because the application would stop '
         'working: continuing targets the whole application for removal.')
TARGETS = 'Containers targeted for removal:'
DATA = 'Container data targeted for deletion:'
KEYS = (PREVIEW, CONFIRM, RESULT, BRIDGE, FIREWALL, PORT, OPTIONAL, MEMBERS, WHOLE, TARGETS, DATA)


def extract(path, name, scope):
    node = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
    return scope[name]


class RemovalWordings(unittest.TestCase):
    def preview(self, bridge='vmbr9', translated=None):
        instances = ModuleType('oci_instances')
        instances.ROOT = Path('/inert')
        instances.read = lambda root, vmid: {'installation_id': 'owned'}
        remover = ModuleType('oci_remove')
        remover.members_of = lambda root, vmid: (101, {'stack': {}}, [102, 101])
        remover.guest_config = lambda member: None
        remover.host_directories = lambda root, members: []
        remover.private_bridge = lambda primary: bridge
        state = ModuleType('oci_installation_state')
        state.parse_config = lambda raw: {}
        scope = {'sys': SimpleNamespace(path=[]), 'source_text': lambda value: value or '',
                 'translate': translated or (lambda value: value), 're': re}
        with patch.dict(sys.modules, {'oci_instances': instances, 'oci_remove': remover,
                                      'oci_installation_state': state}):
            return extract(MENU, '_removal_summary', scope)(Path('/inert'), 101)

    def test_preview_conditions_network_and_discloses_optional_firewall(self):
        preview = self.preview()
        self.assertIn(PREVIEW + ' vmbr9', preview)
        self.assertIn(OPTIONAL, preview)
        self.assertIn(MEMBERS, preview)
        self.assertIn(TARGETS, preview)
        self.assertIn(DATA, preview)
        self.assertNotIn('Private network of the application that is released:', preview)
        self.assertNotIn(PREVIEW, self.preview(bridge=None))

    def test_member_preview_does_not_promise_whole_stack_removed(self):
        instances = ModuleType('oci_instances')
        instances.ROOT = Path('/inert')
        instances.read = lambda root, vmid: {'installation_id': 'owned'}
        remover = ModuleType('oci_remove')
        remover.members_of = lambda root, vmid: (101, {'stack': {}}, [102, 101])
        remover.guest_config = lambda member: None
        remover.host_directories = lambda root, members: []
        remover.private_bridge = lambda primary: None
        state = ModuleType('oci_installation_state')
        state.parse_config = lambda raw: {}
        with patch.dict(sys.modules, {'oci_instances': instances, 'oci_remove': remover,
                                      'oci_installation_state': state}):
            scope = {'sys': SimpleNamespace(path=[]), 'source_text': lambda value: value or '',
                     'translate': lambda value: value, 're': re}
            preview = extract(MENU, '_removal_summary', scope)(Path('/inert'), 102)
        self.assertIn(WHOLE, preview)

    def test_cancellation_preserves_lifecycle_boundary_and_warns_precisely(self):
        calls = []
        ui = SimpleNamespace(review=lambda message, title, **kw: calls.append((message, kw)) or False,
                             message=lambda *args: self.fail('unexpected error'))
        scope = {'_removal_summary': lambda project, vmid: 'Preview',
                 '_run_lifecycle': lambda *args: self.fail('must not run'),
                 'translate': lambda value: value, 'sys': SimpleNamespace(executable='python3'),
                 'Path': Path, 'OSError': OSError, 'ValueError': ValueError, 'KeyError': KeyError}
        self.assertFalse(extract(MENU, '_remove', scope)(Path('/inert'), ui, 101))
        self.assertEqual(calls, [('Preview', {'question': CONFIRM, 'default': False})])

    def test_shared_bridge_and_skipped_member_are_not_reported_removed(self):
        events = []
        records = {102: {'installation_id': 'owned'}, 101: {'installation_id': 'owned'}}
        scope = {'members_of': lambda root, vmid: (101, records[101], [102, 101]),
                 'instances': SimpleNamespace(read=lambda root, vmid: records[vmid],
                     identity=lambda raw: 'reassigned' if raw == b'reassigned' else 'owned',
                     location=lambda root, vmid: Path('/inert/absent/record.json')),
                 'guest_config': lambda vmid: b'reassigned' if vmid == 102 else b'owned',
                 'host_directories': lambda root, members: [], 'private_bridge': lambda primary: 'vmbr9',
                 'bridge_in_use': lambda bridge, removed: True,
                 'release_bridge': lambda bridge: self.fail('shared bridge release'),
                 'remove_owned_host_firewall': lambda record: None,
                 'run': lambda *args: events.append(('run', args)),
                 'subprocess': SimpleNamespace(run=lambda *args, **kwargs: None),
                 'Path': Path, 'shutil': SimpleNamespace(rmtree=lambda path: None),
                 'image_cache': SimpleNamespace(prune=lambda root, lock: []),
                 'oci_console': SimpleNamespace(remove_log=lambda vmid: None),
                 'translate': lambda text: text,
                 'msg_info': lambda text: events.append(('info', text)),
                 'msg_ok': lambda text: events.append(('ok', text)),
                 'msg_warn': lambda text: events.append(('warn', text))}
        remove = extract(REMOVE, 'remove', scope)
        for skipped_config in (b'reassigned', None):
            with self.subTest(skipped_config=skipped_config):
                scope['guest_config'] = lambda vmid: skipped_config if vmid == 102 else b'owned'
                events.clear()
                remove(Path('/inert'), 101)
                self.assertEqual([x for x in events if x[0] == 'run'],
                                 [('run', ('pct', 'destroy', '101', '--purge', '1', '--destroy-unreferenced-disks', '1'))])
                self.assertFalse(any(x == ('ok', 'The application was removed') for x in events))
                self.assertTrue(any('still used' in x[1] for x in events if x[0] == 'warn'))
                self.assertTrue(any('no longer exists' in x[1] if skipped_config is None
                                    else 'belongs to another container' in x[1]
                                    for x in events if x[0] == 'warn'))
        # The actual main() success line is independently guarded by the expected neutral literal.
        tree = ast.parse(REMOVE.read_text())
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        self.assertIn(RESULT, [n.value for n in ast.walk(main) if isinstance(n, ast.Constant) and isinstance(n.value, str)])

    def test_actual_main_success_is_completion_not_all_members_removed(self):
        events = []
        scope = {'argparse': argparse, 'Path': Path, 'instances': SimpleNamespace(ROOT=Path('/inert'),
                    locked=lambda root: nullcontext()),
                 'os': SimpleNamespace(geteuid=lambda: 0),
                 'sys': SimpleNamespace(argv=['oci_remove.py', '101']),
                 'remove': lambda root, vmid: events.append(('warn', 'Skipped CT 102')),
                 'translate': lambda text: text,
                 'msg_error': lambda text: events.append(('error', text)),
                 'msg_ok': lambda text: events.append(('ok', text)),
                 'subprocess': subprocess}
        with patch.object(sys, 'argv', ['oci_remove.py', '101']):
            self.assertEqual(extract(REMOVE, 'main', scope)(), 0)
        self.assertEqual(events, [('warn', 'Skipped CT 102'), ('ok', RESULT)])

    def test_ignored_bridge_command_failures_do_not_claim_release(self):
        events = []
        scope = {'members_of': lambda root, vmid: (101, {}, [101]),
                 'instances': SimpleNamespace(read=lambda root, vmid: {'installation_id': 'owned'},
                     identity=lambda cfg: 'owned', location=lambda root, vmid: Path('/inert/absent/record.json')),
                 'guest_config': lambda vmid: b'owned', 'host_directories': lambda *args: [],
                 'private_bridge': lambda primary: 'vmbr9', 'bridge_in_use': lambda *args: False,
                 'release_bridge': lambda bridge: events.append(('attempt', bridge)),
                 'remove_owned_host_firewall': lambda record: None, 'run': lambda *args: None,
                 'subprocess': SimpleNamespace(run=lambda *args, **kwargs: None),
                 'Path': Path, 'shutil': SimpleNamespace(rmtree=lambda path: None),
                 'image_cache': SimpleNamespace(prune=lambda root, lock: []),
                 'oci_console': SimpleNamespace(remove_log=lambda vmid: None),
                 'translate': lambda text: text, 'msg_info': lambda text: None,
                 'msg_ok': lambda text: events.append(('ok', text)), 'msg_warn': lambda text: None}
        extract(REMOVE, 'remove', scope)(Path('/inert'), 101)
        self.assertIn(('attempt', 'vmbr9'), events)
        self.assertIn(('ok', BRIDGE + ' vmbr9'), events)
        self.assertNotIn(('ok', 'Private network of the application released: vmbr9'), events)

    def test_firewall_delete_exception_has_unknown_outcome_not_unchanged_rule(self):
        events = []
        installation_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        commands = []
        def fake_run(args, **kwargs):
            commands.append(args)
            if args[1] == 'get':
                return SimpleNamespace(stdout=json.dumps([{'comment': 'ProxMenux OCI firewall ' + installation_id,
                    'dport': '8080', 'source': '192.0.2.0/24', 'proto': 'tcp', 'type': 'in',
                    'action': 'ACCEPT', 'pos': 2}]))
            raise subprocess.CalledProcessError(1, args)
        scope = {'re': re, 'socket': SimpleNamespace(gethostname=lambda: 'node'), 'json': json,
                 'subprocess': SimpleNamespace(run=fake_run, CalledProcessError=subprocess.CalledProcessError),
                 'translate': lambda text: text, 'msg_ok': lambda text: events.append(('ok', text)),
                 'msg_warn': lambda text: events.append(('warn', text)), 'OSError': OSError, 'ValueError': ValueError}
        extract(REMOVE, 'remove_owned_host_firewall', scope)({'installation_id': installation_id,
            'deployment': {'host_firewall': {'port': 8080, 'source': '192.0.2.0/24'}}})
        self.assertEqual(commands[-1][1], 'delete')
        self.assertEqual(events, [('warn', FIREWALL)])

    def test_extractor_and_runtime_lookup_fallback_and_synthetic_translation(self):
        generator = runpy.run_path(str(ROOT / '.github/scripts/build_translation_cache.py'))
        found = set(generator['extract_python_texts']([ROOT / 'oci/src', ROOT / 'oci/remote']))
        shell_keys = set(generator['extract_translate_texts'](ROOT / 'oci/remote'))
        self.assertTrue(set(KEYS) - {PORT} <= found, (set(KEYS) - {PORT}) - found)
        self.assertIn(PORT, shell_keys)
        spec = importlib.util.spec_from_file_location('oci_i18n', ROOT / 'oci/src/proxmenux_oci/i18n.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for path in sorted((ROOT / 'lang').glob('*.json')):
            cache = json.loads(path.read_text())
            module._language, module._cache = path.stem, cache
            for key in KEYS:
                self.assertEqual(module.translate(key), cache.get(key) or key)
            module._cache = {}
            for key in KEYS:
                self.assertEqual(module.translate(key), key)
        module._language, module._cache = 'it', {key: 'IT: ' + key for key in KEYS}
        self.assertIn('IT: ' + PREVIEW, self.preview(translated=module.translate))
        self.assertIn('IT: ' + OPTIONAL, self.preview(translated=module.translate))

    def test_actual_shell_guard_fails_for_missing_tcp_contract_not_web_role(self):
        source = INSTALL.read_text()
        function = source[source.index('validate_host_monitor_firewall() {'):source.index('\napply_host_monitor_firewall() {')]
        script = '''set -eu
translate() { printf '%s' "$1"; }
die() { printf '%s' "$1" >&2; exit 7; }
jq() {
  case "$*" in
    *'.host_firewall == null'*) printf 'false\\n' ;;
    *'.host_firewall | type'*) printf 'true\\n' ;;
    *'.host_firewall.bridge'*) printf 'vmbr0\\n' ;;
    *'.host_firewall.source'*) printf '192.0.2.0/24\\n' ;;
    *'.host_firewall.port'*) printf '8080\\n' ;;
    *'.proxmox.installer_profile.host_monitor_firewall.web_port'*) printf '8080\\n' ;;
    *'.container_contract.ports'*) printf '0\\n' ;;
    *) exit 99 ;;
  esac
}
ip() { printf '2: vmbr0 inet 192.0.2.1/24 scope global vmbr0\\n'; }
BRIDGE=vmbr0 HOST_MONITOR=netdata DEPLOYMENT_FILE=/inert/deployment TEMPLATE_FILE=/inert/template
''' + function + '\nvalidate_host_monitor_firewall\n'
        result = subprocess.run(['bash', '-c', script], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stderr, PORT)


if __name__ == '__main__':
    unittest.main()
