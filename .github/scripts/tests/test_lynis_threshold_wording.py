"""Inert source-contract checks; never import operational modules or touch host paths."""
import ast
import json
import os
import subprocess
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / 'AppImage'


def extract_function(path, name, *, owner=None):
    tree = ast.parse(path.read_text())
    container = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner) if owner else tree
    node = next(n for n in container.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    namespace = {}
    return node, ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))


def leaf(pointer):
    data = json.loads((APP / 'messages/en/common.json').read_text())
    for segment in pointer.split('.'):
        data = data[segment]
    return data


class LynisThresholdContracts(unittest.TestCase):
    def test_delete_confirmation_names_all_three_actual_targets(self):
        node, module = extract_function(APP / 'scripts/flask_security_routes.py', 'lynis_report_delete')
        removed = []
        fake_os = SimpleNamespace(path=SimpleNamespace(isfile=lambda p: True), remove=removed.append)
        original_import = __import__
        def fake_import(name, *args, **kwargs):
            if name == 'os':
                return fake_os
            return original_import(name, *args, **kwargs)
        namespace = {'security_manager': object(), 'jsonify': lambda x: x}
        with patch('builtins.__import__', side_effect=fake_import):
            exec(compile(module, str(APP / 'scripts/flask_security_routes.py'), 'exec'), namespace)
            result = namespace['lynis_report_delete']()
        self.assertEqual(result['success'], True)
        self.assertEqual(removed, ['/var/log/lynis-report.dat', '/var/log/lynis.log', '/var/log/lynis-output.log'])
        text = leaf('securityPage.confirm.deleteAuditReport').lower()
        self.assertIn('report', text)
        self.assertIn('logs', text)
        self.assertNotIn('this audit report?', text)

    def test_delete_route_partial_failure_is_not_reported_as_full_success(self):
        _, module = extract_function(APP / 'scripts/flask_security_routes.py', 'lynis_report_delete')
        removed = []
        def remove(path):
            if path.endswith('lynis.log'):
                raise PermissionError('inert denial')
            removed.append(path)
        fake_os = SimpleNamespace(path=SimpleNamespace(isfile=lambda p: True), remove=remove)
        original_import = __import__
        def fake_import(name, *args, **kwargs):
            return fake_os if name == 'os' else original_import(name, *args, **kwargs)
        namespace = {'security_manager': object(), 'jsonify': lambda x: x}
        with patch('builtins.__import__', side_effect=fake_import):
            exec(compile(module, '<inert lynis route>', 'exec'), namespace)
            result, status = namespace['lynis_report_delete']()
        self.assertEqual(removed, ['/var/log/lynis-report.dat'])
        self.assertEqual(status, 500)
        self.assertFalse(result['success'])
        self.assertIn('inert denial', result['message'])

    def test_delete_route_with_no_files_returns_success_false_not_a_clean_result(self):
        _, module = extract_function(APP / 'scripts/flask_security_routes.py', 'lynis_report_delete')
        fake_os = SimpleNamespace(path=SimpleNamespace(isfile=lambda p: False), remove=lambda p: self.fail(p))
        original_import = __import__
        def fake_import(name, *args, **kwargs):
            return fake_os if name == 'os' else original_import(name, *args, **kwargs)
        namespace = {'security_manager': object(), 'jsonify': lambda x: x}
        with patch('builtins.__import__', side_effect=fake_import):
            exec(compile(module, '<inert lynis route>', 'exec'), namespace)
            result = namespace['lynis_report_delete']()
        self.assertFalse(result['success'])
        self.assertIn('No report files', result['message'])

    def test_uninstall_notice_describes_existing_cleanup_targets(self):
        _, module = extract_function(APP / 'scripts/security_manager.py', 'uninstall_lynis')
        removed = []
        fake_os = SimpleNamespace(path=SimpleNamespace(exists=lambda p: p != '/usr/local/share/proxmenux/components_status.json', join=lambda *s: '/'.join(s)), remove=removed.append)
        class FakeShutil:
            @staticmethod
            def rmtree(path):
                removed.append(path)
        original_import = __import__
        def fake_import(name, *args, **kwargs):
            return FakeShutil if name == 'shutil' else original_import(name, *args, **kwargs)
        namespace = {'os': fake_os}
        with patch('builtins.__import__', side_effect=fake_import):
            exec(compile(module, '<inert lynis uninstall>', 'exec'), namespace)
            result = namespace['uninstall_lynis']()
        self.assertTrue(result[0])
        self.assertEqual(removed, ['/opt/lynis', '/usr/local/bin/lynis', '/var/log/lynis-report.dat', '/var/log/lynis.log', '/var/log/lynis-output.log'])
        for key in ('securityPage.lynis.removeReports', 'securityPage.lynis.uninstallConfirmDescription'):
            text = leaf(key).lower()
            self.assertIn('report', text)
            self.assertIn('logs', text)
            self.assertNotIn('monitor-created', text)

    def test_swap_hint_qualifies_sampling_and_independent_ram_alarm(self):
        _, module = extract_function(APP / 'scripts/health_monitor.py', '_check_memory_comprehensive', owner='HealthMonitor')
        # The method is bound to an inert class, not the production constructor.
        self_obj = SimpleNamespace(state_history=defaultdict(list), MEMORY_DURATION=300, SWAP_CRITICAL_DURATION=300,
                                   MEMORY_WARNING=80, SWAP_HIGH_PERCENT=80, AVAILABLE_MIN_PERCENT=20)
        memory = SimpleNamespace(percent=50, available=10, total=100)
        swap = SimpleNamespace(percent=90, used=90, total=100)
        namespace = {'Dict': dict, 'Any': object, 'psutil': SimpleNamespace(virtual_memory=lambda: memory, swap_memory=lambda: swap),
                     'time': SimpleNamespace(time=lambda: 1000)}
        exec(compile(module, '<inert memory check>', 'exec'), namespace)
        first = namespace['_check_memory_comprehensive'](self_obj)
        second = namespace['_check_memory_comprehensive'](self_obj)
        self.assertEqual(first['status'], 'OK')
        self.assertEqual(second['checks']['swap_usage']['status'], 'CRITICAL')
        self_obj.state_history.clear()
        memory.percent = 91
        swap.percent = 0
        for _ in range(8):
            last = namespace['_check_memory_comprehensive'](self_obj)
        self.assertEqual(last['status'], 'CRITICAL')
        self.assertEqual(last['checks']['swap_usage']['status'], 'OK')
        hint = leaf('settings.healthThresholds.swapPressureHint').lower()
        self.assertIn('swap usage', hint)
        self.assertIn('repeated', hint)
        self.assertIn('ram', hint)
        self.assertNotIn('swap file', hint)
        self.assertNotIn('swap file', leaf('settings.healthThresholds.swapHighLabel').lower())
        self.assertNotIn('only when both', hint)

    def test_print_generator_and_descriptions(self):
        node = ROOT / '.github/scripts/tests/fixtures/lynis_print_contract.cjs'
        for lang in ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv'):
            result = subprocess.run(['node', str(node)], cwd=ROOT, text=True, capture_output=True,
                                    env={**os.environ, 'LYNIS_FIXTURE_LANG': lang})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(f'print HTML ({lang}):', result.stdout)


if __name__ == '__main__':
    unittest.main()
