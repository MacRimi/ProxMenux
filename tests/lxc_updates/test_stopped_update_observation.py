"""Real update runner -> trusted handoff -> real completion/API, fake CT only."""
import ast
from contextlib import redirect_stdout
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

import test_observed_state as observed
import managed_installs as managed
import lxc_update_observation as handoff
from flask import request

ROOT = observed.ROOT
RUNNER = ROOT / "scripts/lxc/apply_updates.sh"
REAL_RUN = subprocess.run


class StoppedUpdateObservationTests(unittest.TestCase):
    def setUp(self):
        self.real_run = REAL_RUN
        self.fixture = observed.ObservedStateRoutesTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.folder = Path(self.fixture.temp.name)
        self.state = self.folder / "state"
        self.state.write_text("stopped")
        self.log = self.folder / "commands"
        self.log.write_text("")
        self.bin = self.folder / "bin"
        self.bin.mkdir()
        self.observations = self.folder / "observations"
        ctx = patch.object(handoff, "OBSERVATION_DIR", self.observations)
        ctx.start()
        self.addCleanup(ctx.stop)
        registry = managed.get_registry()
        registry["items"][0]["update_check"]["_count"] = 20
        managed._write_registry(registry)
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "PYTHONPATH": str(ROOT / "AppImage/scripts"),
                    "FIXTURE_DIR": str(self.folder), "VMID": "100", "TARGET": "os",
                    "BACKUP": "0", "RESTART": "0", "RUN_HELPER": "0",
                    "UPDATE_COMMAND": "", "RUN_ID": "manual-fixture",
                    "PROXMENUX_LOCK_DIR": str(self.folder), "REMAINING": "0"}
        self.write("pct", f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys
root = pathlib.Path(os.environ['FIXTURE_DIR'])
args = sys.argv[1:]
with (root/'commands').open('a') as log: log.write(json.dumps(args)+'\\n')
state = root/'state'
if args[0] == 'list':
    if os.environ.get('FOREIGN') == '1': print('VMID Status Name\\n200 stopped foreign')
    else: print('VMID Status Name\\n100 '+state.read_text()+' fixture')
elif args[0] == 'status': print('status: '+state.read_text())
elif args[0] == 'start':
    if os.environ.get('START_FAIL') == '1': sys.exit(1)
    state.write_text('running')
elif args[0] == 'shutdown':
    if os.environ.get('SHUTDOWN_FAIL') == '1': sys.exit(1)
    state.write_text('stopped')
elif args[0] == 'reboot':
    if os.environ.get('REBOOT_FAIL') == '1': sys.exit(1)
    if os.environ.get('REBOOT_TRANSITION') == '1': state.write_text('restarting')
elif args[0] == 'exec':
    if state.read_text() != 'running': sys.exit(1)
    command = ' '.join(args[3:])
    if '/etc/os-release' in command: print('ID=debian')
    elif 'dist-upgrade' in command:
        if os.environ.get('UPDATE_FAIL') == '1': sys.exit(4)
        if os.environ.get('CLEAR_AFTER_UPGRADE') == '1': (root/'remaining').write_text('0')
    elif 'apt-get update' in command:
        if os.environ.get('INDEX_FAIL') == '1': sys.exit(3)
    elif 'apt list --upgradable' in command:
        if os.environ.get('PROBE_FAIL') == '1': sys.exit(1)
        print('Listing...')
        pending = (root/'remaining').read_text() if (root/'remaining').exists() else os.environ['REMAINING']
        for n in range(int(pending)):
            print(f'pkg{n}/stable 2.0 amd64 [upgradable from: 1.0]')
    elif command == '/usr/bin/docker --version':
        if os.environ.get('DOCKER_PROBE_FAIL') == '1': sys.exit(1)
        print('Docker version 29.9.0')
    else: sys.exit(91)
else: sys.exit(92)
''')
        driver = self.folder / "capture.py"
        driver.write_text('''
import os, pathlib
import managed_installs as m
import lxc_update_observation as h
import lxc_apps as apps
root = pathlib.Path(os.environ['FIXTURE_DIR'])
m._DB_DIR = str(root)
m._REGISTRY_PATH = str(root/'registry.json')
m._PCT_BIN = str(root/'bin/pct')
h.OBSERVATION_DIR = root/'observations'
apps._APPS_DIR = str(root/'apps')
apps._PCT_BIN = str(root/'bin/pct')
marker = '--mark-started' in os.sys.argv
with (root/'commands').open('a') as log: log.write('MARK_STARTED\\n' if marker else 'CAPTURE\\n')
if os.environ.get('MARKER_FAIL') == '1' and marker: raise SystemExit(1)
if os.environ.get('CAPTURE_FAIL') == '1' and not marker: raise SystemExit(1)
m._detect_lxc_containers = lambda **_: ([{'id':'lxc:100','type':'lxc','_vmid':'100',
    '_is_oci':os.environ.get('OCI') == '1'}] if (root/'state').read_text() == 'running' else [])
raise SystemExit(h.main())
''')
        self.write("python3", "#!/bin/bash\n"
                   f"exec {shlex.quote(sys.executable)} {shlex.quote(str(driver))} \"${{@:2}}\"\n")
        self.write("sleep", "#!/bin/sh\nexit 0\n")
        self.write("flock", "#!/bin/sh\nexit 0\n")
        names = {"_finalize_lxc_update", "_terminal_lxc_update_completed",
                 "api_lxc_updates_applied", "_run_scheduled_update",
                 "_scheduled_runner_reported_stopped"}
        nodes = [n for n in ast.parse(observed.SERVER.read_text()).body
                 if isinstance(n, ast.FunctionDef) and n.name in names]
        self.scope = self.fixture.scope
        self.scope.update({
            "os": os, "re": re, "time": time, "uuid": uuid, "datetime": datetime, "json": json,
            "request": request, "_LXC_APPLY_UPDATES_SCRIPT": str(RUNNER),
            "_LXC_INSTALL_CHECKED_OS_SCRIPT": str(ROOT / 'scripts/lxc/install_checked_os_updates.sh'),
            "_APPLY_UPDATES_SCRIPT": str(RUNNER),
            "_normalise_lxc_update_run_id": lambda value, **_: value or "manual-fixture",
            "_normalise_lxc_update_targets": lambda values, target: values or [target],
            "_normalise_lxc_update_labels": lambda values: values or [],
            "_json_list": lambda value: json.loads(value or '[]'),
            "_lxc_update_finalizations": {}, "_lxc_update_finalization_lock": threading.RLock(),
            "_LXC_UPDATE_FINALIZATION_TTL": 3600,
            "_SCHEDULED_STOPPED_EXIT": 9,
            "_fast_guest_status": lambda *_: self.state.read_text(),
            "_lxc_update_snapshot": lambda *_: {"ct_name": "fixture"},
            "_lxc_update_target_labels": lambda *_: ["OS"],
            "_lxc_update_details": lambda **kwargs: str(kwargs),
            "_publish_guest_modal_cache_revision": Mock(),
            "notification_manager": Mock(),
            "_create_lxc_update_log": lambda *_: (None, None),
            "_append_lxc_update_log": lambda *_: None,
            "_prune_lxc_update_logs": lambda *_: None,
            "_normalise_schedule_targets": lambda sched: sched.get('targets') or ['os'],
            "_scheduled_helper_enabled": lambda *_: False,
            "_compose_scheduled_update_command": lambda *_, **__: '',
            "_inspect_lxc_reboot_requirement": lambda *_, **__: (False, [], None),
        })
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'update-completion', 'exec'), self.scope)

    def write(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run_manual(self, **extra):
        env = {**self.env, **extra}
        result = self.real_run(['/bin/bash', str(RUNNER)], env=env, text=True,
                               capture_output=True, timeout=20)
        # The runner's separate process has not modified the shared registry.
        self.assertEqual(managed.get_registry()['items'][0]['update_check']['_count'], 20)
        self.scope['_terminal_lxc_update_completed'](script_path=str(RUNNER),
            params={'RUN_ID': env.get('RUN_ID'), 'VMID': '100', 'TARGET': 'os'},
            exit_code=result.returncode, duration_seconds=1)
        return result

    def test_manual_hook_stores_verified_zero_after_shutdown_without_restart(self):
        result = self.run_manual()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state.read_text(), 'stopped')
        row = self.fixture.row()['update_check']
        self.assertEqual(row['count'], 0)
        self.assertIsNone(row['error'])
        self.assertEqual(row['os_family'], 'debian')
        log = self.log.read_text()
        self.assertLess(log.index('MARK_STARTED'), log.index('CAPTURE'))
        self.assertLess(log.index('CAPTURE'), log.index('shutdown'))
        self.assertLess(log.index('apt list --upgradable'), log.index('shutdown'))
        self.assertNotIn('apt-get update', log)
        self.assertEqual(log.count('dist-upgrade'), 1)
        self.assertFalse(list(self.observations.iterdir()))
        self.assertEqual(managed.get_registry()['items'][1]['update_check']['_count'], 7)
        self.assertEqual(self.fixture.commands, [], 'GET and stopped finalization run no guest probes')

    def test_partial_update_keeps_verified_remaining_packages(self):
        result = self.run_manual(REMAINING='3', UPDATE_FAIL='1')
        self.assertEqual(result.returncode, 4)
        self.assertEqual(self.state.read_text(), 'stopped')
        self.assertEqual(self.fixture.row()['update_check']['count'], 3)

    def assert_unverified(self, flag):
        result = self.run_manual(**{flag: '1'})
        self.assertEqual(result.returncode, 0, 'verification failure is not updater failure')
        self.assertEqual(self.state.read_text(), 'stopped')
        stored = managed.get_registry()['items'][0]['update_check']
        self.assertTrue(stored['error'])
        self.assertNotIn('_count', stored)
        self.assertTrue(self.fixture.row()['update_check']['error'])

    def test_failed_probe_does_not_present_old_count_or_fresh_zero(self):
        self.assert_unverified('PROBE_FAIL')

    def test_missing_capture_does_not_present_old_count_or_fresh_zero(self):
        self.assert_unverified('CAPTURE_FAIL')

    def test_pre_start_failure_or_foreign_target_preserves_last_verified_result(self):
        for condition in ('START_FAIL', 'FOREIGN'):
            with self.subTest(condition=condition):
                registry = managed.get_registry()
                registry['items'][0]['update_check'] = {
                    'available': True, 'last_check': '2026-10-14T00:00:00Z',
                    '_count': 20, 'error': None,
                }
                managed._write_registry(registry)
                result = self.run_manual(**{condition: '1'})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.read_text(), 'stopped')
                stored = managed.get_registry()['items'][0]['update_check']
                self.assertEqual(stored['_count'], 20)
                self.assertIsNone(stored['error'])
                log = self.log.read_text()
                self.assertNotIn('MARK_STARTED', log)
                self.assertNotIn('CAPTURE', log)

    def test_started_run_with_unwritable_marker_is_reported_as_unverified(self):
        result = self.run_manual(MARKER_FAIL='1', CAPTURE_FAIL='1')
        self.assertEqual(result.returncode, 8)
        self.assertEqual(self.state.read_text(), 'stopped')
        stored = managed.get_registry()['items'][0]['update_check']
        self.assertTrue(stored['error'])
        self.assertNotIn('_count', stored)

    def test_web_runner_without_identity_reports_unverified_instead_of_silent_skip(self):
        env = {**self.env, 'EXECUTION_MODE': 'web'}
        env.pop('RUN_ID')
        result = self.real_run(['/bin/bash', str(RUNNER)], env=env,
                               capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.state.read_text(), 'stopped')
        self.assertIn('verification has no RUN_ID', result.stderr)
        self.assertNotIn('CAPTURE', self.log.read_text())

    def test_rejected_handoff_is_retained_with_safe_diagnostic_and_no_false_zero(self):
        self.observations.mkdir(mode=0o700)
        handoff.mark_started(100, 'manual-fixture')
        path = self.observations / '100-manual-fixture.json'
        path.write_text(json.dumps({'private_payload': 'must-not-be-logged'}))
        path.chmod(0o600)
        output = io.StringIO()
        with redirect_stdout(output):
            self.scope['_finalize_lxc_update'](100, run_id='manual-fixture',
                status='success', source='manual', target='os')
        self.assertTrue(path.exists())
        self.assertIn('reason=KeyError', output.getvalue())
        self.assertIn('handoff=False started=True untouched=False verified=False', output.getvalue())
        self.assertNotIn('must-not-be-logged', output.getvalue())
        self.assertTrue(self.fixture.row()['update_check']['error'])
        self.assertNotIn('_count', managed.get_registry()['items'][0]['update_check'])

    def test_frontend_completion_route_deduplicates_authoritative_hook(self):
        self.run_manual()
        class InlineThread:
            def __init__(self, target, args, kwargs, **_):
                self.callback = lambda: target(*args, **kwargs)
            def start(self):
                self.callback()
        self.scope['threading'] = SimpleNamespace(Thread=InlineThread)
        response = self.fixture.client.post('/api/lxc-updates/100/applied', json={
            'success': True, 'run_id': 'manual-fixture', 'target': 'os'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.fixture.row()['update_check']['count'], 0)
        self.scope['notification_manager'].emit_event.assert_called_once()

    def test_entrypoint_and_imported_server_share_finalization_for_same_run(self):
        # AppRun executes flask_server as __main__; health collectors later
        # import flask_server by name. Those namespaces must not own separate
        # finalization maps when the terminal hook and HTTP callback collide.
        tree = ast.parse(observed.SERVER.read_text())
        state_names = {'_lxc_update_finalization_lock', '_lxc_update_finalizations'}
        initializers = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == 'lxc_update_finalization':
                initializers.append(node)
            elif isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id in state_names for target in node.targets):
                initializers.append(node)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in state_names:
                initializers.append(node)
        hook_scope = dict(self.scope)
        exec(compile(ast.Module(body=initializers, type_ignores=[]), 'entrypoint-state', 'exec'), hook_scope)
        exec(compile(ast.Module(body=initializers, type_ignores=[]), 'imported-state', 'exec'), self.scope)
        for scope in (hook_scope, self.scope):
            scope['_lxc_update_finalizations'].clear()
            self.addCleanup(scope['_lxc_update_finalizations'].clear)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {'_finalize_lxc_update', '_terminal_lxc_update_completed'}]
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'entrypoint-hook', 'exec'), hook_scope)
        self.scope['_terminal_lxc_update_completed'] = hook_scope['_terminal_lxc_update_completed']
        self.run_manual()
        self.assertEqual(self.fixture.row()['update_check']['count'], 0)
        class InlineThread:
            def __init__(self, target, args, kwargs, **_):
                self.callback = lambda: target(*args, **kwargs)
            def start(self):
                self.callback()
        self.scope['threading'] = SimpleNamespace(Thread=InlineThread)
        response = self.fixture.client.post('/api/lxc-updates/100/applied', json={
            'success': True, 'run_id': 'manual-fixture', 'target': 'os'})
        self.assertEqual(response.status_code, 202)
        result = self.fixture.row()['update_check']
        self.assertEqual(result['count'], 0)
        self.assertIsNone(result['error'])
        self.scope['notification_manager'].emit_event.assert_called_once()

    def test_scheduled_path_executes_real_runner_and_real_finalization(self):
        self.state.write_text("running")
        def run(command, **kwargs):
            kwargs['env'].update({key: value for key, value in self.env.items()
                                  if key != 'RUN_ID'})
            return self.real_run(command, **kwargs)
        self.scope['subprocess'] = SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired)
        result = self.scope['_run_scheduled_update'](100, {'targets': ['os'], 'target': 'os'})
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(self.state.read_text(), 'running')
        self.assertEqual(self.fixture.row()['update_check']['count'], 0)

    def test_legacy_cli_without_run_id_preserves_update_and_original_state(self):
        env = dict(self.env)
        env.pop('RUN_ID')
        result = self.real_run(['/bin/bash', str(RUNNER)], env=env,
                               capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.state.read_text(), 'stopped')
        self.assertNotIn('CAPTURE', self.log.read_text())

    def test_appimage_packaging_copies_the_actual_observation_helper(self):
        builder = (ROOT / 'AppImage/scripts/build_appimage.sh').read_text()
        copies = [line for line in builder.splitlines()
                  if line.startswith('cp ') and '$SCRIPT_DIR/lxc_update_observation.py' in line]
        self.assertEqual(len(copies), 1)
        appdir = self.folder / 'AppDir'
        (appdir / 'usr/bin').mkdir(parents=True)
        result = self.real_run(['/bin/bash', '-ec', copies[0]], env={**os.environ,
            'SCRIPT_DIR': str(ROOT / 'AppImage/scripts'), 'APP_DIR': str(appdir)},
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((appdir / 'usr/bin/lxc_update_observation.py').read_bytes(),
                         (ROOT / 'AppImage/scripts/lxc_update_observation.py').read_bytes())
        shared = [line for line in builder.splitlines()
                  if line.startswith('cp ') and '$SCRIPT_DIR/lxc_update_finalization.py' in line]
        self.assertEqual(len(shared), 1)
        result = self.real_run(['/bin/bash', '-ec', shared[0]], env={**os.environ,
            'SCRIPT_DIR': str(ROOT / 'AppImage/scripts'), 'APP_DIR': str(appdir)},
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((appdir / 'usr/bin/lxc_update_finalization.py').read_bytes(),
                         (ROOT / 'AppImage/scripts/lxc_update_finalization.py').read_bytes())

    def test_bad_or_untrusted_handoffs_are_not_accepted(self):
        self.run_manual()
        self.observations.mkdir(exist_ok=True)
        path = self.observations / '100-manual-fixture.json'
        for body in ('{}', '[]', '{bad'):
            path.write_text(body)
            path.chmod(0o600)
            self.assertIsNone(handoff.read(100, 'manual-fixture'))
        path.unlink()
        path.symlink_to(self.folder / 'registry.json')
        self.assertIsNone(handoff.read(100, 'manual-fixture'))
        with self.assertRaises(ValueError):
            handoff.read(100, '../../escape')

    def test_wrong_run_expired_incomplete_and_public_observations_are_rejected(self):
        handoff.capture(100, 'manual-fixture')
        original = handoff.read(100, 'manual-fixture')
        self.assertIsNotNone(original)
        path = self.observations / '100-manual-fixture.json'
        cases = []
        for key, value in (('vmid', 200), ('run_id', 'wrong-run'),
                           ('captured_at', '2020-01-01T00:00:00+00:00'),
                           ('captured_at', '2999-01-01T00:00:00+00:00')):
            cases.append({**original, key: value})
        cases.append({**original, 'result': {'available': False, 'last_check': 'now'}})
        for data in cases:
            path.write_text(json.dumps(data))
            self.assertIsNone(handoff.read(100, 'manual-fixture'))
        path.write_text(json.dumps(original))
        path.chmod(0o644)
        self.assertIsNone(handoff.read(100, 'manual-fixture'))
        path.unlink()
        os.mkfifo(path, mode=0o600)
        self.assertIsNone(handoff.read(100, 'manual-fixture'))

    def test_oci_observation_never_runs_a_generic_package_listing(self):
        result = self.run_manual(OCI='1')
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('apt list --upgradable', self.log.read_text())
        self.assertTrue(self.fixture.row()['update_check']['is_oci_lxc'])

    def test_oci_handoff_without_family_accepts_only_complete_skipped_zero(self):
        with patch.object(managed, '_probe_lxc_is_oci', return_value=True):
            observation = handoff.capture(100, 'manual-fixture')
        observation['entry']['_os_family'] = None
        path = self.observations / '100-manual-fixture.json'
        path.write_text(json.dumps(observation))
        self.assertIsNotNone(handoff.read(100, 'manual-fixture'))
        for patch_result in ({'available': True}, {'_count': 1},
                             {'_security_count': 1}, {'_packages': [{'name': 'unexpected'}]}):
            path.write_text(json.dumps({**observation, 'result': {**observation['result'], **patch_result}}))
            self.assertIsNone(handoff.read(100, 'manual-fixture'))
        observation['entry']['_is_oci'] = False
        path.write_text(json.dumps(observation))
        self.assertIsNone(handoff.read(100, 'manual-fixture'), 'non-OCI still needs a verified supported family')

    def test_reboot_failure_preserves_exit_code_and_still_verifies_before_stop(self):
        result = self.run_manual(RESTART='1', REBOOT_FAIL='1')
        self.assertEqual(result.returncode, 6)
        self.assertEqual(self.state.read_text(), 'stopped')
        self.assertEqual(self.fixture.row()['update_check']['count'], 0)

    def test_capture_precedes_reboot_and_is_not_retried_in_transitional_guest(self):
        result = self.run_manual(RESTART='1', REBOOT_TRANSITION='1')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.state.read_text(), 'stopped')
        self.assertEqual(self.fixture.row()['update_check']['count'], 0)
        log = self.log.read_text()
        self.assertLess(log.index('CAPTURE'), log.index('reboot'))
        self.assertEqual(log.count('CAPTURE'), 1)

    def test_registry_failure_does_not_discard_the_valid_observation(self):
        result = self.real_run(['/bin/bash', str(RUNNER)], env=self.env,
                               capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0)
        with patch.object(managed, '_write_registry', return_value=False):
            outcome = self.scope['_finalize_lxc_update'](100, run_id='manual-fixture',
                status='success', source='manual', target='os')
        self.assertTrue(outcome['verification_errors'])
        self.assertIsNotNone(handoff.read(100, 'manual-fixture'))
        self.assertEqual(managed.get_registry()['items'][0]['update_check']['_count'], 20)

    def test_originally_running_guest_keeps_existing_finalization_path(self):
        self.state.write_text('running')
        import lxc_apps
        with patch.object(lxc_apps, 'mark_manual_versions_unverified'), \
                patch.object(lxc_apps, 'check_all'):
            result = self.run_manual()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.state.read_text(), 'running')
        self.assertNotIn('CAPTURE', self.log.read_text())
        self.assertEqual(self.fixture.row()['update_check']['count'], 0)

    def test_stopped_finalizer_consumes_captured_app_versions_without_guest_probes(self):
        import lxc_apps
        self.state.write_text('running')
        observation = handoff.capture(100, 'manual-fixture')
        observation['apps'] = [{'id': 'docker', 'installed_version': '29.9.0'}]
        self.state.write_text('stopped')
        with patch.object(handoff, 'read', return_value=observation), \
             patch.object(lxc_apps, 'store_installed_observations', create=True,
                          return_value={'errors': [], 'applied': 1}) as store, \
             patch.object(lxc_apps, 'check_all') as check, \
             patch.object(lxc_apps, 'mark_manual_versions_unverified') as manual:
            self.scope['_finalize_lxc_update'](100, run_id='manual-fixture',
                status='success', source='manual', target='both',
                requested_targets=['os', 'app:ghstats'])
        store.assert_called_once_with(100, observation['apps'])
        manual.assert_called_once_with(100, ['ghstats'])
        check.assert_not_called()

    def test_real_os_runner_updates_registered_docker_before_shutdown_and_backend_merge(self):
        import lxc_apps
        folder = self.folder / 'apps'
        folder.mkdir()
        sidecar = folder / '100.json'
        original = {'apps': [{'id': 'docker', 'installed_via': 'binary',
            'binary_path': '/usr/bin/docker', 'state': {'installed_version': '29.8.1',
            'latest_version': '29.9.0', 'checked_at': '2026-01-01T00:00:00Z',
            'update_available': True}}], 'schedule': {'enabled': False}}
        sidecar.write_text(json.dumps(original))
        with patch.object(lxc_apps, '_APPS_DIR', str(folder)), \
             patch.object(lxc_apps, 'check_all') as check:
            result = self.run_manual()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state.read_text(), 'stopped')
        saved = json.loads(sidecar.read_text())
        self.assertEqual(saved['apps'][0]['state']['installed_version'], '29.9.0')
        self.assertFalse(saved['apps'][0]['state']['update_available'])
        self.assertEqual(saved['schedule'], original['schedule'])
        commands = self.log.read_text()
        self.assertLess(commands.index('/usr/bin/docker'), commands.index('shutdown'))
        self.assertEqual(commands.count('/usr/bin/docker'), 1)
        check.assert_not_called()

    def test_failed_app_write_retains_handoff_and_does_not_claim_verified(self):
        import lxc_apps
        self.state.write_text('running')
        observation = handoff.capture(100, 'manual-fixture')
        observation['apps'] = []
        path = handoff._path(100, 'manual-fixture')
        path.write_text(json.dumps(observation))
        self.state.write_text('stopped')
        with patch.object(lxc_apps, 'store_installed_observations', side_effect=OSError):
            outcome = self.scope['_finalize_lxc_update'](100, run_id='manual-fixture',
                status='success', source='manual', target='os')
        self.assertTrue(path.exists())
        self.assertIn('post-update application persistence failed', outcome['verification_errors'])


if __name__ == '__main__':
    unittest.main()
