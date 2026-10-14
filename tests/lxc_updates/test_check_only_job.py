"""Real job, Flask routes and shared flock; guest transport is isolated."""
import ast
import datetime
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify
from flask import request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'AppImage/scripts'))
import lxc_check_job as job


class CheckOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.conf = self.folder / '100.conf'
        self.conf.write_text('hostname: fixture\n')
        self.patches = [patch.object(job, 'LOCK_DIR', self.folder),
                        patch.object(job, 'CONF_DIR', self.folder),
                        patch.object(job, 'OCI_REGISTRY', self.folder / 'installed.json'),
                        patch.object(job.managed_installs, '_lxc_updates_detection_enabled', return_value=True),
                        patch.object(job.managed_installs, '_get_oci_managed_vmids', return_value={}),
                        patch.object(job.managed_installs, 'get_active_items', return_value=[])]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        job._jobs.clear()
        job._attempts.clear()
        self.state = 'stopped'
        self.calls = []
        self.result = {'result': {'available': True, '_count': 2}, 'entry': {}}

    def transport(self, vmid, action, *args, **kwargs):
        self.calls.append(action)
        if action == 'status':
            return 'status: ' + self.state
        if action == 'start':
            self.state = 'running'
        if action in ('stop', 'shutdown'):
            self.state = 'stopped'
        return ''

    def run_check(self, capture_error=None, persistence_error=None, transport=None):
        reservation = job.acquire(100)
        job._jobs['run'] = dict(vmid=100, state='running', created=time.monotonic())
        with patch.object(job, 'command', side_effect=transport or self.transport), \
             patch.object(job.lxc_update_observation, 'capture', return_value=self.result,
                          side_effect=capture_error) as capture, \
             patch.object(job.lxc_update_observation, 'discard'), \
             patch.object(job.managed_installs, 'store_lxc_update_observation',
                          return_value=True, side_effect=persistence_error) as store:
            job.run(100, 'run', reservation)
        return job.get(100, 'run'), capture, store

    def test_stopped_check_is_rejected_before_a_job_or_guest_mutation(self):
        with patch.object(job, 'command', side_effect=self.transport):
            with self.assertRaisesRegex(RuntimeError, 'start it first'):
                job.start(100)
        self.assertEqual(self.state, 'stopped')
        self.assertEqual(self.calls, ['status'])
        self.assertEqual(job._jobs, {})
        self.assertEqual(job._attempts, {})
        self.assertFalse((self.folder / 'proxmenux-lxc-check-invalid-100').exists())
        reservation = job.acquire(100)
        reservation.close()

    def test_running_check_has_no_lifecycle_effect(self):
        self.state = 'running'
        result, _, _ = self.run_check()
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(self.calls, ['status'])
        self.assertEqual(self.state, 'running')
        self.assertFalse((self.folder / 'proxmenux-lxc-check-invalid-100').exists())

    def test_successful_running_check_clears_an_older_failure_marker(self):
        self.state = 'running'
        (self.folder / 'proxmenux-lxc-check-invalid-100').touch()
        result, _, _ = self.run_check()
        self.assertEqual(result['state'], 'complete')
        self.assertFalse((self.folder / 'proxmenux-lxc-check-invalid-100').exists())

    def test_marker_cleanup_failure_reports_failure_and_releases_the_operation_lock(self):
        self.state = 'running'
        with patch.object(job, 'clear_invalid_marker', return_value=False):
            result, _, _ = self.run_check()
        self.assertEqual(result['state'], 'failed')
        self.assertIn('could not be published', result['error'])
        reservation = job.acquire(100)
        reservation.close()

    def test_marker_created_after_a_check_started_is_not_cleared(self):
        marker = self.folder / 'proxmenux-lxc-check-invalid-100'
        marker.touch()
        os.utime(marker, ns=(2_000, 2_000))

        self.assertFalse(job.clear_invalid_marker(100, check_started_ns=1_000))
        self.assertTrue(marker.exists())

    def test_already_cleared_marker_is_a_successful_publish(self):
        self.assertTrue(job.clear_invalid_marker(100))

    def test_index_read_timeout_and_persistence_errors_keep_running_guest_running(self):
        self.state = 'running'
        for error in [RuntimeError('index failed'), OSError('read failed'),
                      subprocess.TimeoutExpired('package listing', 30)]:
            with self.subTest(error=type(error).__name__):
                result, _, _ = self.run_check(capture_error=error)
                self.assertEqual(result['state'], 'failed')
                self.assertEqual(self.state, 'running')
        result, _, _ = self.run_check(persistence_error=OSError('disk full'))
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(self.state, 'running')
        self.assertIn('could not be persisted', result['error'])

    def test_unexpected_stopped_worker_never_starts_or_probes_the_guest(self):
        result, capture, store = self.run_check()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(self.state, 'stopped')
        self.assertEqual(self.calls, ['status'])
        capture.assert_not_called()
        store.assert_not_called()
        self.assertTrue((self.folder / 'proxmenux-lxc-check-invalid-100').exists())

    def test_unknown_status_does_not_start(self):
        self.state = 'unknown'
        result, capture, _ = self.run_check()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(self.calls, ['status'])
        capture.assert_not_called()

    def test_guard_oci_config_lock_and_disabled_forbid_all_guest_calls(self):
        for config in ['lxc.environment.runtime: OCI=1\n', 'lock: backup\n']:
            self.conf.write_text(config)
            result, capture, _ = self.run_check()
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(self.calls, [])
            capture.assert_not_called()
        self.conf.unlink()
        result, capture, _ = self.run_check()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(self.calls, [])
        capture.assert_not_called()
        self.conf.write_text('hostname: fixture\n')
        with patch.object(job.managed_installs, '_lxc_updates_detection_enabled', return_value=False):
            result, capture, _ = self.run_check()
        self.assertEqual(self.calls, [])
        capture.assert_not_called()

    def test_registered_oci_is_excluded_before_probe(self):
        with patch.object(job.managed_installs, '_get_oci_managed_vmids', return_value={'100': 'fixture'}):
            result, capture, _ = self.run_check()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(self.calls, [])
        capture.assert_not_called()

    def test_unreadable_or_invalid_oci_registry_never_means_non_oci(self):
        for content in ['broken', '{"instances": []}', '{"instances": {"app": {"vmid": 100}}}']:
            job.OCI_REGISTRY.write_text(content)
            result, capture, _ = self.run_check()
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(self.calls, [])
            capture.assert_not_called()

    def test_thread_start_failure_releases_lock_and_job(self):
        with patch.object(job, 'status', return_value='running'), \
                patch.object(job.threading, 'Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('cannot create worker')
            with self.assertRaises(RuntimeError):
                job.start(100)
        self.assertEqual(job._jobs, {})
        self.assertEqual(job._attempts, {})
        reservation = job.acquire(100)
        reservation.close()

    def test_corrupt_registry_is_preserved_and_installation_stays_blocked(self):
        registry = self.folder / 'registry.json'
        registry.write_text('malformed-but-must-not-be-overwritten')
        with patch.object(job.managed_installs, '_REGISTRY_PATH', str(registry)):
            result, _, _ = self.run_check(persistence_error=job.managed_installs.store_lxc_update_observation)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(self.state, 'stopped')
        self.assertEqual(registry.read_text(), 'malformed-but-must-not-be-overwritten')
        self.assertTrue((self.folder / 'proxmenux-lxc-check-invalid-100').exists())

    def test_shared_lock_excludes_scheduler_and_manual_runner(self):
        reservation = job.acquire(100)
        self.addCleanup(reservation.close)
        with self.assertRaises(BlockingIOError):
            job.start(100)
        process = subprocess.run(['/usr/bin/flock', '-n',
            str(self.folder / 'proxmenux-lxc-update-100.lock'), '/bin/true'])
        self.assertEqual(process.returncode, 1)
        self.assertEqual(job._jobs, {})
        reservation.close()
        other = job.acquire(100)
        other.close()

    def test_cooldown_boundaries_and_inflight(self):
        for elapsed, expected in [(59.999, 429), (60, 202), (60.001, 202)]:
            job._jobs.clear()
            job._attempts[100] = 100
            reservation = Mock()
            with patch.object(job.time, 'monotonic', return_value=100 + elapsed), \
                 patch.object(job.threading, 'Thread'), patch.object(job, 'acquire', return_value=reservation), \
                 patch.object(job, 'status', return_value='running'):
                result, code = job.start(100)
            self.assertEqual(code, expected)
        job._jobs['active'] = dict(vmid=100, state='running', created=100)
        job._attempts[100] = 0
        with patch.object(job.time, 'monotonic', return_value=10000):
            self.assertEqual(job.start(100)[1], 429)

    def test_poll_is_read_only_and_scoped_to_guest(self):
        job._jobs['run'] = dict(vmid=100, state='running', error=None, created=1)
        with patch.object(job, 'command') as command, patch.object(job, 'guard') as guard:
            self.assertEqual(job.get(100, 'run')['state'], 'running')
            self.assertIsNone(job.get(101, 'run'))
            self.assertIsNone(job.get(100, 'missing'))
        command.assert_not_called()
        guard.assert_not_called()

    def test_install_gate_positive_zero_unknown_error_and_freshness(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        for count, available, error, age, allowed in [
            (2, True, None, 60, True), (0, False, None, 60, False),
            (None, True, None, 60, False), (2, True, 'failed', 60, False),
            (2, True, None, 172799, True), (2, True, None, 172800, False),
            (2, True, None, -60, False)]:
            with self.subTest(count=count, age=age, error=error):
                item = {'id': 'lxc:100', 'update_check': {'_count': count,
                    'available': available, 'error': error,
                    'last_check': (now - datetime.timedelta(seconds=age)).isoformat()}}
                with patch.object(job.managed_installs, 'get_active_items', return_value=[item]):
                    if allowed:
                        job.checked_os(100)
                    else:
                        with self.assertRaises((RuntimeError, ValueError)):
                            job.checked_os(100)

    def test_pending_failure_marker_forbids_install_before_probe(self):
        (self.folder / 'proxmenux-lxc-check-invalid-100').touch()
        with self.assertRaises(RuntimeError):
            job.checked_os(100)

    def test_real_capture_refreshes_lists_and_persists_without_installation(self):
        for count, index_rc in [(0, 0), (2, 0), (2, 1)]:
            with self.subTest(count=count, index_rc=index_rc):
                self.state = 'running'
                reservation = job.acquire(100)
                job._jobs['real'] = dict(vmid=100, state='running', created=time.monotonic())
                entry = {'id': 'lxc:100', 'type': 'lxc', '_vmid': '100', '_os_family': 'debian'}
                output = 'Listing...\n' + '\n'.join(
                    f'pkg{i}/stable 2.0 amd64 [upgradable from: 1.0]' for i in range(count))
                commands = []
                def transport(command, **kwargs):
                    commands.append(command)
                    return subprocess.CompletedProcess(command, index_rc if 'update' in command else 0,
                                                       output if 'list' in ' '.join(command) else '', '')
                with patch.object(job, 'command', side_effect=self.transport), \
                     patch.object(job.managed_installs, '_DB_DIR', str(self.folder)), \
                     patch.object(job.managed_installs, '_REGISTRY_PATH', str(self.folder / 'registry.json')), \
                     patch.object(job.lxc_update_observation, 'OBSERVATION_DIR', self.folder / 'observations'), \
                     patch.object(job.managed_installs, '_detect_lxc_containers', return_value=[entry]), \
                     patch.object(job.managed_installs, '_probe_lxc_os', return_value='debian'), \
                     patch.object(job.managed_installs.subprocess, 'run', side_effect=transport):
                    job.run(100, 'real', reservation)
                    stored = job.managed_installs.get_registry()['items'][0]['update_check']
                self.assertEqual(self.state, 'running')
                self.assertEqual(job.get(100, 'real')['state'], 'failed' if index_rc else 'complete')
                self.assertTrue(any('update' in command for command in commands))
                self.assertFalse(any(any(word in command for word in ('upgrade', 'install', 'full-upgrade'))
                                     for command in commands))
                if not index_rc:
                    self.assertEqual(stored['_count'], count)
                else:
                    self.assertTrue(stored['error'])
                    self.assertFalse(any('apt list' in ' '.join(command) for command in commands))

    def test_control_route_uses_same_lock_and_preserves_qemu(self):
        app = Flask(__name__)
        command = Mock(return_value=subprocess.CompletedProcess(
            [], 0, '"UPID:fixture:000A:000B:000C:vzstart:100:root@pam:"\n', ''))
        scope = {'app': app, 'jsonify': jsonify, 'request': request,
                 'require_auth': lambda fn: fn,
                 'get_cached_pvesh_cluster_resources_vm': lambda: [
                     {'vmid': 100, 'type': 'lxc', 'node': 'fixture'},
                     {'vmid': 200, 'type': 'qemu', 'node': 'fixture'}],
                 'subprocess': SimpleNamespace(run=command), '_pvesh_cache': {},
                 '_vm_cache_invalidate': Mock()}
        node = next(n for n in ast.parse((ROOT / 'AppImage/scripts/flask_server.py').read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'api_vm_control')
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'route', 'exec'), scope)
        client = app.test_client()
        reservation = job.acquire(100)
        try:
            self.assertEqual(client.post('/api/vms/100/control', json={'action': 'stop'}).status_code, 409)
            command.assert_not_called()
            self.assertEqual(client.post('/api/vms/200/control', json={'action': 'reboot'}).status_code, 200)
        finally:
            reservation.close()
        # The production waiter owns a long-lived reservation. Isolate its
        # launch here so it cannot probe through another test's transport.
        with patch.object(job.threading, 'Thread') as worker:
            response = client.post('/api/vms/100/control', json={'action': 'start'})
            worker.return_value.start.assert_called_once_with()
            retained = worker.call_args.kwargs['args'][1]
            self.addCleanup(retained.close)
            job.cancel_control(retained)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        self.assertEqual(response.json['task'], 'UPID:fixture:000A:000B:000C:vzstart:100:root@pam:')
        self.assertIn('/nodes/fixture/lxc/100/status/start', command.call_args.args[0])

    def test_actual_routes_submit_poll_and_control_lock(self):
        app = Flask(__name__)
        scope = {'app': app, 'jsonify': jsonify, 'require_auth': lambda fn: fn,
                 '_vm_cache_invalidate': Mock(), '_lxc_os_info_cache': {},
                 '_pvesh_cache': {}, '_get_lxc_update_status_map': lambda: {'100': {'count': 2}}}
        names = {'api_lxc_updates_refresh_check', 'api_lxc_updates_refresh_check_status'}
        nodes = [n for n in ast.parse((ROOT / 'AppImage/scripts/flask_server.py').read_text()).body
                 if isinstance(n, ast.FunctionDef) and n.name in names]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'routes', 'exec'), scope)
        client = app.test_client()
        with patch.object(job, 'start', return_value=({'job_id': 'run'}, 202)):
            self.assertEqual(client.post('/api/vms/100/updates/refresh-check').status_code, 202)
        job._jobs['run'] = dict(vmid=100, state='complete', error=None, created=1)
        with patch.object(job, 'command') as command:
            response = client.get('/api/vms/100/updates/refresh-check/run')
            self.assertEqual(response.json['update_check']['count'], 2)
            self.assertEqual(client.get('/api/vms/101/updates/refresh-check/run').status_code, 404)
        command.assert_not_called()
