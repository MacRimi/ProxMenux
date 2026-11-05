"""Actual full-health route with inert collaborators; no APT or host actions."""
import ast
import copy
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'AppImage/scripts'))
import kernel_reboot as kernel


def snapshot():
    return dict(overall='OK', summary='All systems operational', timestamp='original', details={
        'cpu': dict(status='OK', checks={}),
        'updates': dict(status='OK', count=0, checks={'pending_updates': dict(status='OK')})})


class FullHealth(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.now = time.time()
        self.cached = snapshot()
        self.owner = SimpleNamespace(cached_results={'_bg_detailed': self.cached},
                                     last_check_times={'_bg_detailed': self.now},
                                     get_detailed_status=Mock(return_value=snapshot()))
        persistence = SimpleNamespace(get_active_errors=Mock(return_value=[]),
                                      get_dismissed_errors=Mock(return_value=[]),
                                      get_custom_suppressions=Mock(return_value=[]))
        node = next(n for n in ast.parse((ROOT/'AppImage/scripts/flask_health_routes.py').read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'get_full_health')
        node.decorator_list = []
        self.scope = dict(health_monitor=self.owner, health_persistence=persistence,
                          request=request, jsonify=jsonify)
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'actual-health-route', 'exec'), self.scope)
        self.uname = patch.object(kernel.os, 'uname', return_value=SimpleNamespace(release='7.0.14-25-pve'))
        self.marker = patch.object(Path, 'exists', return_value=False)
        self.uname.start(); self.marker.start()
        self.addCleanup(self.uname.stop); self.addCleanup(self.marker.stop)
        def command(args, **kwargs):
            self.assertEqual(args, ['dpkg-query', '-W', '-f=${db:Status-Status}\t${binary:Package}\n'])
            return subprocess.CompletedProcess(args, 0, 'installed\tproxmox-kernel-7.0.14-26-pve-signed\n', '')
        self.probe = patch.object(kernel.subprocess, 'run', side_effect=command).start()
        self.addCleanup(patch.stopall)

    def call(self, query=''):
        with self.app.test_request_context('/api/health/full'+query), patch('time.time', return_value=self.now):
            response = self.scope['get_full_health']()
            if isinstance(response, tuple):
                return response[0].get_json(), response[1]
            return response.get_json(), response.status_code

    def test_cached_full_response_detects_external_update_without_full_check(self):
        before = copy.deepcopy(self.cached)
        result, code = self.call()
        self.assertEqual(code, 200)
        self.assertTrue(result['health']['details']['updates']['reboot_required'])
        self.assertEqual(result['health']['details']['updates']['count'], 0)
        self.assertEqual(result['health']['timestamp'], 'original')
        self.assertEqual(result['health']['summary'], 'Reboot required: running 7.0.14-25-pve; installed 7.0.14-26-pve')
        self.assertEqual(self.cached, before)
        self.owner.get_detailed_status.assert_not_called()
        self.assertEqual(self.probe.call_count, 1)

    def test_cached_only_miss_expiry_and_future_never_run_full_check_or_clear_cache(self):
        for age in (360, 360.001, -1):
            for query in ('?cached=1', '?cached=1&refresh=1'):
                with self.subTest(age=age, query=query):
                    self.owner.last_check_times['_bg_detailed'] = self.now-age
                    before = copy.deepcopy(self.owner.cached_results)
                    result, code = self.call(query)
                    self.assertEqual(code, 503)
                    self.assertIn('error', result)
                    self.assertEqual(self.owner.cached_results, before)
        self.owner.cached_results.clear()
        self.assertEqual(self.call('?cached=1')[1], 503)
        self.owner.get_detailed_status.assert_not_called()
        self.probe.assert_not_called()

    def test_real_completion_finalizer_then_cached_poll_has_no_new_audit(self):
        import sys
        from types import ModuleType
        node = next(n for n in ast.parse((ROOT/'AppImage/scripts/flask_terminal_routes.py').read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == '_host_update_completed')
        scope = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'actual-finalizer', 'exec'), scope)
        module = ModuleType('health_monitor')
        module.health_monitor = self.owner
        with patch.dict(sys.modules, {'health_monitor': module}):
            scope['_host_update_completed']('/fixed-script', {}, 0, 164)
        self.assertNotIn('_bg_detailed', self.owner.cached_results)
        result, code = self.call('?cached=1')
        self.assertEqual(code, 503)
        self.assertIn('error', result)
        self.owner.get_detailed_status.assert_not_called()
        self.probe.assert_not_called()

    def test_cached_only_just_before_boundary_is_fresh_reboot_without_full_check(self):
        self.owner.last_check_times['_bg_detailed'] = self.now-359.999
        result, code = self.call('?cached=1')
        self.assertEqual(code, 200)
        self.assertTrue(result['health']['details']['updates']['reboot_required'])
        self.owner.get_detailed_status.assert_not_called()

    def test_invalid_timestamp_and_incomplete_snapshot_never_start_full_check(self):
        for value in (None, 'bad', float('nan'), float('inf')):
            self.owner.last_check_times['_bg_detailed'] = value
            self.assertEqual(self.call('?cached=1')[1], 503)
        self.owner.last_check_times['_bg_detailed'] = self.now
        self.owner.cached_results['_bg_detailed'] = {'details': {}}
        self.assertEqual(self.call('?cached=1')[1], 500)
        self.owner.get_detailed_status.assert_not_called()
        self.probe.assert_not_called()

    def test_probe_failure_is_unknown_not_green_and_retains_other_categories(self):
        self.cached['details']['cpu']['status'] = 'CRITICAL'
        self.cached['overall'] = 'CRITICAL'
        with patch.object(kernel.subprocess, 'run', side_effect=OSError('fixture-read-error')):
            result, code = self.call('?cached=1')
        self.assertEqual(code, 200)
        health = result['health']
        self.assertIsNone(health['details']['updates']['reboot_required'])
        self.assertEqual(health['details']['updates']['status'], 'UNKNOWN')
        self.assertEqual(health['overall'], 'CRITICAL')
        self.assertEqual(health['details']['cpu'], self.cached['details']['cpu'])

    def test_marker_zero_package_probes_and_no_process_or_shell_actions(self):
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(kernel.subprocess, 'Popen') as spawn, patch.object(kernel.os, 'system') as shell:
            self.assertTrue(self.call('?cached=1')[0]['health']['details']['updates']['reboot_required'])
            spawn.assert_not_called()
            shell.assert_not_called()
        self.probe.assert_not_called()

    def test_explicit_refresh_retains_original_full_check_contract(self):
        result, code = self.call('?refresh=1')
        self.assertEqual(code, 200)
        self.owner.get_detailed_status.assert_called_once()

    def test_explicit_refresh_publishes_then_poll_never_rechecks(self):
        result, code = self.call('?refresh=1')
        self.assertEqual(code, 200)
        self.assertIn('_bg_detailed', self.owner.cached_results)
        self.assertEqual(self.owner.cached_results['_bg_overall']['status'],result['health']['overall'])
        self.assertEqual(self.owner.last_check_times['_bg_overall'],self.owner.last_check_times['_bg_detailed'])
        before = copy.deepcopy(self.owner.cached_results)
        result, code = self.call('?cached=1')
        self.assertEqual(code, 200)
        self.assertEqual(result['health']['timestamp'], 'original')
        self.assertEqual(self.owner.cached_results, before)
        self.owner.get_detailed_status.assert_called_once()

    def test_invalid_live_result_never_publishes_or_becomes_fresh(self):
        for result in (None, {}, {'details': {}}, {'details': {'updates': {'status': 'OK'}}}):
            with self.subTest(result=result):
                self.owner.cached_results.clear()
                self.owner.last_check_times.clear()
                self.owner.get_detailed_status.return_value = result
                self.assertEqual(self.call()[1], 500)
                self.assertNotIn('_bg_detailed', self.owner.cached_results)
                self.assertNotIn('_bg_detailed', self.owner.last_check_times)


class Overlay(unittest.TestCase):
    def test_repeated_required_unknown_current_preserves_package_result_and_snapshot(self):
        states = [dict(state=s, running_kernel='old', installed_kernel='new' if s=='required' else None)
                  for s in ('required', 'unknown', 'current')]
        for package in ('OK', 'INFO', 'WARNING', 'CRITICAL', 'UNKNOWN'):
            value = snapshot()
            value['details']['updates']['status'] = package
            before = copy.deepcopy(value)
            for state in states:
                previous = copy.deepcopy(value)
                with patch.object(kernel, 'reboot_status', return_value=state):
                    refreshed = kernel.refresh_health_reboot(value)
                self.assertEqual(value, previous)
                value = refreshed
                block = value['details']['updates']
                expected = ('INFO' if state['state']=='required' else 'UNKNOWN' if state['state']=='unknown' else 'OK') if package=='OK' else package
                self.assertEqual(block['status'], expected)
                self.assertEqual(block['package_status'], package)
                self.assertEqual(value['timestamp'], 'original')
                self.assertEqual(value['details']['cpu'], before['details']['cpu'])

    def test_dismissed_package_warning_stays_dismissed_but_reboot_remains_visible(self):
        value = snapshot()
        value['details']['updates'].update(status='OK', package_status='WARNING', all_dismissed=True)
        state = dict(state='required', running_kernel='old', installed_kernel='new')
        with patch.object(kernel, 'reboot_status', return_value=state):
            result = kernel.refresh_health_reboot(value)
        self.assertEqual(result['details']['updates']['status'], 'INFO')
        self.assertTrue(result['details']['updates']['all_dismissed'])
        self.assertEqual(value['details']['updates']['status'], 'OK')

    def test_unknown_recovery_recomputes_overall_without_erasing_unrelated_warning(self):
        value = snapshot()
        with patch.object(kernel, 'reboot_status', return_value=dict(state='unknown', running_kernel='old')):
            value = kernel.refresh_health_reboot(value)
        self.assertEqual(value['overall'], 'WARNING')
        with patch.object(kernel, 'reboot_status', return_value=dict(state='current', running_kernel='new')):
            recovered = kernel.refresh_health_reboot(value)
            value['details']['cpu']['status'] = 'WARNING'
            preserved = kernel.refresh_health_reboot(value)
        self.assertEqual(recovered['overall'], 'OK')
        self.assertEqual(preserved['overall'], 'WARNING')


if __name__ == '__main__':
    unittest.main(verbosity=2)
