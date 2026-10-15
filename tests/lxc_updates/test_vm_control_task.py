"""Actual Flask routes: additive task metadata and confined read-only status."""
import ast
import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[2]
TASK = 'UPID:fixture:000A:000B:000C:vzreboot:100:root@pam:'

class ControlTaskTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.run = Mock()
        self.cache = {}
        self.invalidate = Mock()
        scope = dict(app=self.app, jsonify=jsonify, request=request, require_auth=lambda fn: fn,
                     get_cached_pvesh_cluster_resources_vm=lambda: [
                         dict(vmid=100, type='lxc', node='fixture'),
                         dict(vmid=200, type='qemu', node='fixture')],
                     subprocess=SimpleNamespace(run=self.run, TimeoutExpired=subprocess.TimeoutExpired),
                     _pvesh_cache=self.cache, _vm_cache_invalidate=self.invalidate)
        nodes = [n for n in ast.parse((ROOT / 'AppImage/scripts/flask_server.py').read_text()).body
                 if isinstance(n, ast.FunctionDef) and n.name in ('api_vm_control_task', 'api_vm_control')]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'routes', 'exec'), scope)
        self.client = self.app.test_client()

    def get(self, task=TASK, vmid=100):
        return self.client.get(f'/api/vms/{vmid}/control-task/{task}')

    def result(self, payload, code=0):
        return subprocess.CompletedProcess([], code, json.dumps(payload), '')

    def test_actual_control_post_preserves_each_action_and_adds_its_task(self):
        lock = Mock()
        retained = Mock()
        module = SimpleNamespace(acquire=lambda _: lock, begin_control=Mock(),
                                 retain_control=retained, cancel_control=Mock())
        with patch.dict('sys.modules', {'lxc_check_job': module}):
            for family, vmid in [('vz', 100), ('qm', 200)]:
                for action in ['start', 'shutdown', 'reboot', 'stop']:
                    self.run.reset_mock()
                    task = TASK.replace('vzreboot:100', f'{family}{action}:{vmid}')
                    self.run.return_value = self.result(task)
                    response = self.client.post(f'/api/vms/{vmid}/control', json={'action': action})
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.json['success'])
                    self.assertEqual(response.json['action'], action)
                    self.assertEqual(response.json['vmid'], vmid)
                    self.assertEqual(response.json['task'], task)
                    self.assertEqual(self.run.call_count, 1, 'POST accepts once without polling or extra action')
                    self.assertEqual(self.run.call_args.args[0],
                        ['pvesh', 'create', f'/nodes/fixture/{"lxc" if family == "vz" else "qemu"}/{vmid}/status/{action}'])
            self.assertEqual(retained.call_count, 4)
            lock.close.assert_not_called()

    def test_control_post_reads_final_upid_after_pvesh_log_output(self):
        lock = Mock()
        retained = Mock()
        module = SimpleNamespace(acquire=lambda _: lock, begin_control=Mock(),
                                 retain_control=retained, cancel_control=Mock())
        task = TASK.replace('vzreboot', 'vzstart')
        self.run.return_value = subprocess.CompletedProcess(
            [], 0, f'waiting for server lock\n"{task}"\n', '')
        with patch.dict('sys.modules', {'lxc_check_job': module}):
            response = self.client.post('/api/vms/100/control', json={'action': 'start'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['task'], task)
        retained.assert_called_once_with(100, task, lock)

    def test_control_post_accepts_ha_shutdown_task_for_lxc_and_qemu(self):
        lock = Mock()
        retained = Mock()
        module = SimpleNamespace(acquire=lambda _: lock, begin_control=Mock(),
                                 retain_control=retained, cancel_control=Mock())
        with patch.dict('sys.modules', {'lxc_check_job': module}):
            for vmid in (100, 200):
                with self.subTest(vmid=vmid):
                    self.run.reset_mock()
                    task = TASK.replace('vzreboot:100', f'hastop:{vmid}')
                    self.run.return_value = self.result(task)
                    response = self.client.post(
                        f'/api/vms/{vmid}/control', json={'action': 'shutdown'})
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertTrue(response.json['success'])
                    self.assertEqual(response.json['task'], task)
                    self.assertEqual(self.run.call_count, 1)
                    self.assertEqual(self.run.call_args.args[0], [
                        'pvesh', 'create',
                        f'/nodes/fixture/{"lxc" if vmid == 100 else "qemu"}/{vmid}/status/shutdown',
                    ])
        retained.assert_called_once_with(100, TASK.replace('vzreboot:100', 'hastop:100'), lock)

    def test_control_post_rejects_success_without_a_confirmable_task(self):
        lock = Mock()
        module = SimpleNamespace(acquire=lambda _: lock, begin_control=Mock(),
                                 retain_control=Mock(), cancel_control=Mock())
        self.run.return_value = subprocess.CompletedProcess([], 0, 'waiting for server lock\n', '')
        with patch.dict('sys.modules', {'lxc_check_job': module}):
            response = self.client.post('/api/vms/100/control', json={'action': 'start'})
        self.assertEqual(response.status_code, 502, response.json)
        self.assertFalse(response.json['success'])
        self.assertIn('task', response.json['error'].lower())
        module.retain_control.assert_not_called()
        module.cancel_control.assert_called_once_with(lock)
        lock.close.assert_called_once()
        self.run.reset_mock()
        self.assertEqual(self.client.post('/api/vms/100/control', json={'action': 'destroy'}).status_code, 400)
        self.run.assert_not_called()

    def test_running_task_never_probes_guest_or_mutates(self):
        self.run.return_value = self.result(dict(status='running'))
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, dict(status='running', exitstatus=None))
        self.assertEqual(self.run.call_count, 1)
        self.assertEqual(self.run.call_args.args[0][:2], ['pvesh', 'get'])
        self.invalidate.assert_not_called()

    def test_complete_task_checks_actual_guest_for_all_power_actions_and_qemu(self):
        for family, vmid in [('vz', 100), ('qm', 200)]:
            for action in ['start', 'shutdown', 'reboot', 'stop']:
                with self.subTest(family=family, action=action):
                    self.run.reset_mock()
                    expected = 'stopped' if action in ('shutdown', 'stop') else 'running'
                    self.run.side_effect = [self.result(dict(status='stopped', exitstatus='OK')),
                                            self.result(dict(status=expected))]
                    task = TASK.replace('vzreboot:100', f'{family}{action}:{vmid}')
                    response = self.get(task, vmid)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json['guest_status'], expected)
                    self.assertEqual(self.run.call_count, 2)
                    self.assertTrue(all(call.args[0][:2] == ['pvesh', 'get'] for call in self.run.call_args_list))

    def test_ha_start_and_stop_tasks_belong_to_the_guest(self):
        for action, expected in [('hastart', 'running'), ('hastop', 'stopped')]:
            with self.subTest(action=action):
                self.run.reset_mock()
                self.run.side_effect = [self.result(dict(status='stopped', exitstatus='OK')),
                                        self.result(dict(status=expected))]
                task = TASK.replace('vzreboot', action)
                response = self.get(task)
                self.assertEqual(response.status_code, 200, response.json)
                self.assertEqual(response.json['guest_status'], expected)
                self.assertEqual(self.run.call_count, 2)

    def test_wrong_guest_node_type_and_path_make_zero_probes(self):
        for task in [TASK.replace(':100:', ':200:'), TASK.replace('fixture', 'other'),
                     TASK.replace('vzreboot', 'qmreboot'), TASK.replace('vzreboot', 'vzdump'),
                     TASK + '/extra', '../../etc/passwd', 'not-a-task']:
            with self.subTest(task=task):
                self.run.reset_mock()
                self.assertIn(self.get(task).status_code, [400, 404])
                self.run.assert_not_called()
        self.assertEqual(self.get(vmid=999).status_code, 404)
        self.run.assert_not_called()

    def test_task_failure_never_probes_guest_or_claims_success(self):
        self.run.return_value = self.result(dict(status='stopped', exitstatus='start failed'))
        self.assertEqual(self.get().json['exitstatus'], 'start failed')
        self.assertEqual(self.run.call_count, 1)
        self.invalidate.assert_not_called()

    def test_unknown_and_invalid_reads_are_errors_not_success(self):
        for value in [[], {}, dict(status='unknown'), dict(status='running')]:
            self.run.return_value = self.result(value, code=1 if value == dict(status='running') else 0)
            self.assertEqual(self.get().status_code, 502)
        self.run.return_value = subprocess.CompletedProcess([], 0, '', '')
        self.assertEqual(self.get().status_code, 502)
        self.run.side_effect = subprocess.TimeoutExpired('pvesh', 5)
        self.assertEqual(self.get().status_code, 502)

    def test_invalid_final_guest_never_clears_cache(self):
        for value in [{}, [], dict(status='unknown')]:
            self.run.side_effect = [self.result(dict(status='stopped', exitstatus='OK')), self.result(value)]
            self.assertEqual(self.get().status_code, 502)
            self.invalidate.assert_not_called()

if __name__ == '__main__':
    unittest.main()
