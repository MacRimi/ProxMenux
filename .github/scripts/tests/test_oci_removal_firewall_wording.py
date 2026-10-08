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
CONFIRM = 'Remove the application? Its container disks are deleted, and only a backup can bring them back.'
RESULT = 'Removal command finished; review any warnings above.'
BRIDGE = 'Private network release attempted:'
BRIDGE_FAILURE = 'Could not complete private network release:'
SUCCESS = 'The application was removed'
FIREWALL = 'Could not verify removal of the managed host firewall rule.'
PORT = 'The host-monitor firewall port does not match exactly one TCP port in the container contract'
OPTIONAL = 'A matching managed host firewall rule may also be removed.'
MEMBERS = 'All of them are targeted for removal.'
WHOLE = ('It cannot be removed on its own, because the application would stop '
         'working: continuing targets the whole application for removal.')
TARGETS = 'Containers targeted for removal:'
DATA = 'Container data targeted for deletion:'
KEYS = (PREVIEW, CONFIRM, RESULT, BRIDGE, BRIDGE_FAILURE, SUCCESS, FIREWALL, PORT, OPTIONAL, MEMBERS, WHOLE, TARGETS, DATA)


def extract(path, name, scope):
    node = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
    return scope[name]


class RemovalWordings(unittest.TestCase):
    def preview(self, bridge='vmbr9', translated=None, firewall=True):
        instances = ModuleType('oci_instances')
        instances.ROOT = Path('/inert')
        instances.read = lambda root, vmid: {'installation_id': 'owned'}
        remover = ModuleType('oci_remove')
        remover.members_of = lambda root, vmid: (101, {'stack': {}, 'deployment':
            {'host_firewall': {'port': 8080}} if firewall else {}}, [102, 101])
        remover.guest_config = lambda member: None
        remover.host_directories = lambda root, members: []
        remover.granted_directories = lambda root, members: []
        remover.private_bridge = lambda primary: bridge
        remover.bridge_in_use = lambda bridge, removed: False
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
        self.assertNotIn(OPTIONAL, self.preview(firewall=False))

    def test_member_preview_does_not_promise_whole_stack_removed(self):
        instances = ModuleType('oci_instances')
        instances.ROOT = Path('/inert')
        instances.read = lambda root, vmid: {'installation_id': 'owned'}
        remover = ModuleType('oci_remove')
        remover.members_of = lambda root, vmid: (101, {'stack': {}}, [102, 101])
        remover.guest_config = lambda member: None
        remover.host_directories = lambda root, members: []
        remover.granted_directories = lambda root, members: []
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
                 'host_directories': lambda root, members: [], 'granted_directories': lambda *args: [], 'private_bridge': lambda primary: 'vmbr9',
                 'bridge_in_use': lambda bridge, removed: True,
                 'release_bridge': lambda bridge: self.fail('shared bridge release'),
                 'remove_owned_host_firewall': lambda record: None,
                 'run': lambda *args: events.append(('run', args)),
                 'subprocess': SimpleNamespace(run=lambda *args, **kwargs: None),
                 'Path': lambda value: Path('/inert/no-lifecycle') if str(value).startswith('/etc/pve/') else Path(value),
                 'shutil': SimpleNamespace(rmtree=lambda path: None),
                 'image_cache': SimpleNamespace(prune=lambda root, lock: []),
                 'work_backup': SimpleNamespace(forget=lambda root, vmid: None),
                 'oci_console': SimpleNamespace(remove_log=lambda vmid: None),
                 'guest_node': lambda vmid: None, 'remove_host_state': lambda vmid: None, 'release_shared_host_files': lambda hookscripts: None, 're': re,
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
                self.assertTrue(any('still used' in x[1] for x in events if x[0] == 'info'))
                self.assertTrue(any('no longer exists' in x[1] if skipped_config is None
                                    else 'belongs to another container' in x[1]
                                    for x in events if x[0] == 'warn'))
        # The actual main() success line is independently guarded by the expected neutral literal.
        tree = ast.parse(REMOVE.read_text())
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        self.assertIn(RESULT, [n.value for n in ast.walk(main) if isinstance(n, ast.Constant) and isinstance(n.value, str)])

    def test_actual_main_success_is_completion_not_all_members_removed(self):
        events = self.lifecycle_events(missing=True)
        self.assertIn(('warn', 'The container no longer exists: CT 102'), events)
        self.assertEqual(events[-1], ('ok', RESULT))

    def lifecycle_events(self, *, missing=False, reassigned=False, bridge='none',
                         ip_rc=0, pvesh_rc=0, ip_error=False, firewall_failure=False,
                         firewall_success=False, kept=False):
        events, commands = [], []
        self.last_commands = commands
        record = {'installation_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}
        if firewall_failure or firewall_success:
            record['deployment'] = {'host_firewall': {'source': '192.0.2.0/24', 'port': 8080}}
        records = {101: record, 102: {'installation_id': 'owned'}}

        def fake_command(args, **kwargs):
            commands.append(tuple(args))
            if ip_error and args[:2] == ['ip', 'link']:
                raise OSError('ip unavailable')
            if args[:2] == ['pvesh', 'get']:
                return SimpleNamespace(stdout=json.dumps([{'comment': 'ProxMenux OCI firewall ' + record['installation_id'],
                    'dport': '8080', 'source': '192.0.2.0/24', 'proto': 'tcp', 'type': 'in',
                    'action': 'ACCEPT', 'pos': 2}]), returncode=0)
            if args[:2] == ['pvesh', 'delete'] and '/firewall/' in args[2] and firewall_failure:
                raise subprocess.CalledProcessError(1, args)
            return SimpleNamespace(returncode=ip_rc if args[:2] == ['ip', 'link'] else
                                   pvesh_rc if args[:2] == ['pvesh', 'delete'] else 0)

        fake_subprocess = SimpleNamespace(run=fake_command, CalledProcessError=subprocess.CalledProcessError)
        scope = {'members_of': lambda root, vmid: (101, record, [102, 101]),
                 'instances': SimpleNamespace(ROOT=Path('/inert'), locked=lambda root: nullcontext(),
                     read=lambda root, vmid: records[vmid],
                     identity=lambda cfg: record['installation_id'] if cfg == b'primary' else
                         'other' if cfg == b'reassigned' else 'owned',
                     location=lambda root, vmid: Path('/inert/absent/record.json')),
                 'guest_config': lambda vmid: (None if missing else b'reassigned' if reassigned else b'owned')
                     if vmid == 102 else b'primary',
                 'host_directories': lambda *args: ['/retained'] if kept else [], 'granted_directories': lambda *args: [],
                 'private_bridge': lambda primary: 'vmbr9' if bridge != 'none' else None,
                 'bridge_in_use': lambda *args: bridge == 'shared',
                 'run': lambda *args: commands.append(args), 'subprocess': fake_subprocess,
                 'socket': SimpleNamespace(gethostname=lambda: 'node'), 'json': json, 're': re,
                 'Path': lambda value: Path('/inert/no-lifecycle') if str(value).startswith('/etc/pve/') else Path(value),
                 'shutil': SimpleNamespace(rmtree=lambda path: None),
                 'image_cache': SimpleNamespace(prune=lambda root, lock: []),
                 'work_backup': SimpleNamespace(forget=lambda root, vmid: None),
                 'oci_console': SimpleNamespace(remove_log=lambda vmid: None),
                 'guest_node': lambda vmid: None, 'remove_host_state': lambda vmid: None, 'release_shared_host_files': lambda hookscripts: None,
                 'translate': lambda text: text,
                 'msg_info': lambda text: events.append(('info', text)),
                 'msg_ok': lambda text: events.append(('ok', text)),
                 'msg_warn': lambda text: events.append(('warn', text)),
                 'msg_error': lambda text: events.append(('error', text)),
                 'argparse': argparse, 'os': SimpleNamespace(geteuid=lambda: 0),
                 'sys': SimpleNamespace(argv=['oci_remove.py', '101'])}
        scope['release_bridge'] = extract(REMOVE, 'release_bridge', scope)
        scope['remove_owned_host_firewall'] = extract(REMOVE, 'remove_owned_host_firewall', scope)
        scope['remove'] = extract(REMOVE, 'remove', scope)
        with patch.object(sys, 'argv', ['oci_remove.py', '101']):
            self.assertEqual(extract(REMOVE, 'main', scope)(), 0)
        return events

    def test_clean_removal_has_clear_success(self):
        events = self.lifecycle_events()
        self.assertEqual(events[-1], ('ok', 'The application was removed'))
        self.assertFalse(any(kind == 'warn' for kind, _ in events))

    def test_skipped_identity_and_kept_bridge_have_partial_result(self):
        events = self.lifecycle_events(reassigned=True, bridge='shared')
        self.assertIn(('warn', 'The VMID belongs to another container now and is not touched: CT 102'), events)
        self.assertEqual(events[-1], ('ok', RESULT))

    def test_shared_bridge_intentionally_kept_does_not_taint_clean_removal(self):
        events = self.lifecycle_events(bridge='shared')
        self.assertTrue(any('still used' in text for kind, text in events if kind == 'info'))
        self.assertEqual(events[-1], ('ok', 'The application was removed'))

    def test_failed_bridge_commands_have_partial_result(self):
        for ip_rc, pvesh_rc in ((1, 0), (0, 1), (1, 1)):
            with self.subTest(ip_rc=ip_rc, pvesh_rc=pvesh_rc):
                events = self.lifecycle_events(bridge='private', ip_rc=ip_rc, pvesh_rc=pvesh_rc)
                self.assertTrue(any(kind == 'warn' and 'private network' in text.lower()
                                    for kind, text in events), events)
                self.assertEqual(events[-1], ('ok', RESULT))

    def test_successful_bridge_release_and_retained_paths_are_clean(self):
        events = self.lifecycle_events(bridge='private', kept=True)
        self.assertIn(('ok', BRIDGE + ' vmbr9'), events)
        self.assertTrue(any(kind == 'info' and '/retained' in text for kind, text in events))
        self.assertFalse(any(kind == 'warn' for kind, _ in events))
        self.assertEqual(events[-1], ('ok', SUCCESS))

    def test_bridge_exception_is_reported_but_cleanup_continues(self):
        events = self.lifecycle_events(bridge='private', ip_error=True)
        self.assertEqual([cmd[:2] for cmd in self.last_commands],
                         [('pct', 'stop'), ('pct', 'destroy'), ('pct', 'stop'),
                          ('pct', 'destroy'), ('ip', 'link'), ('pvesh', 'delete')])
        self.assertTrue(any(kind == 'warn' and 'private network' in text.lower()
                            for kind, text in events), events)
        self.assertEqual(events[-1], ('ok', RESULT))

    def test_successful_firewall_delete_is_clean(self):
        events = self.lifecycle_events(firewall_success=True)
        self.assertTrue(any('Host firewall rule removed:' in text for kind, text in events if kind == 'ok'))
        self.assertEqual(events[-1], ('ok', SUCCESS))

    def test_firewall_delete_failure_has_partial_result(self):
        events = self.lifecycle_events(firewall_failure=True)
        self.assertIn(('warn', FIREWALL), events)
        self.assertEqual(events[-1], ('ok', RESULT))

    def test_ignored_bridge_command_failures_do_not_claim_release(self):
        events = []
        scope = {'members_of': lambda root, vmid: (101, {}, [101]),
                 'instances': SimpleNamespace(read=lambda root, vmid: {'installation_id': 'owned'},
                     identity=lambda cfg: 'owned', location=lambda root, vmid: Path('/inert/absent/record.json')),
                 'guest_config': lambda vmid: b'owned', 'host_directories': lambda *args: [], 'granted_directories': lambda *args: [],
                 'private_bridge': lambda primary: 'vmbr9', 'bridge_in_use': lambda *args: False,
                 'release_bridge': lambda bridge: events.append(('attempt', bridge)),
                 'remove_owned_host_firewall': lambda record: None, 'run': lambda *args: None,
                 'subprocess': SimpleNamespace(run=lambda *args, **kwargs: None),
                 'Path': lambda value: Path('/inert/no-lifecycle') if str(value).startswith('/etc/pve/') else Path(value),
                 'shutil': SimpleNamespace(rmtree=lambda path: None),
                 'image_cache': SimpleNamespace(prune=lambda root, lock: []),
                 'work_backup': SimpleNamespace(forget=lambda root, vmid: None),
                 'oci_console': SimpleNamespace(remove_log=lambda vmid: None),
                 'guest_node': lambda vmid: None, 'remove_host_state': lambda vmid: None, 'release_shared_host_files': lambda hookscripts: None, 're': re,
                 'translate': lambda text: text, 'msg_info': lambda text: None,
                 'msg_ok': lambda text: events.append(('ok', text)), 'msg_warn': lambda text: None}
        extract(REMOVE, 'remove', scope)(Path('/inert'), 101)
        self.assertIn(('attempt', 'vmbr9'), events)
        self.assertIn(('ok', BRIDGE + ' vmbr9'), events)
        self.assertNotIn(('ok', 'Private network of the application released: vmbr9'), events)

    def test_invalid_managed_firewall_metadata_warns_instead_of_silent_clean(self):
        events = []
        scope = {'re': re, 'socket': SimpleNamespace(gethostname=lambda: 'node'), 'json': json,
                 'subprocess': subprocess, 'translate': lambda text: text,
                 'msg_ok': lambda text: events.append(('ok', text)),
                 'msg_warn': lambda text: events.append(('warn', text))}
        result = extract(REMOVE, 'remove_owned_host_firewall', scope)(
            {'installation_id': 'invalid', 'deployment': {'host_firewall': {'source': '192.0.2.0/24', 'port': 8080}}})
        self.assertFalse(result)
        self.assertEqual(events, [('warn', FIREWALL)])

    def test_ambiguous_firewall_match_warns_without_deleting_other_rules(self):
        events, commands = [], []
        installation_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        rule = {'comment': 'ProxMenux OCI firewall ' + installation_id, 'dport': '8080',
                'source': '192.0.2.0/24', 'proto': 'tcp', 'type': 'in', 'action': 'ACCEPT', 'pos': 2}
        def fake_run(args, **kwargs):
            commands.append(args)
            return SimpleNamespace(stdout=json.dumps([rule, {**rule, 'pos': 3}]))
        scope = {'re': re, 'socket': SimpleNamespace(gethostname=lambda: 'node'), 'json': json,
                 'subprocess': SimpleNamespace(run=fake_run, CalledProcessError=subprocess.CalledProcessError),
                 'translate': lambda text: text, 'msg_ok': lambda text: events.append(('ok', text)),
                 'msg_warn': lambda text: events.append(('warn', text))}
        result = extract(REMOVE, 'remove_owned_host_firewall', scope)(
            {'installation_id': installation_id,
             'deployment': {'host_firewall': {'source': '192.0.2.0/24', 'port': 8080}}})
        self.assertFalse(result)
        self.assertEqual(events, [('warn', FIREWALL)])
        self.assertEqual([command[1] for command in commands], ['get'])

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
