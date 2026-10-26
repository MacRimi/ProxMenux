"""Inert branch tests for the real Lynis deletion/uninstall producers."""
import ast
import os
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]

def extracted(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text())
    fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name)
    fn.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(path), 'exec'), namespace)
    return namespace[name]

class LynisFeedbackProducer(unittest.TestCase):
    def test_actual_ui_feedback_handlers_all_shipped_locales(self):
        result = subprocess.run(['node', str(ROOT / '.github/scripts/tests/fixtures/lynis_feedback_contract.cjs')],
                                cwd=ROOT, capture_output=True, text=True, env=os.environ.copy())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_uninstall_nothing_to_remove_is_not_reported_as_uninstalled(self):
        fake_os = SimpleNamespace(path=SimpleNamespace(exists=lambda p: False, join=lambda *p: '/'.join(p)), remove=lambda p: self.fail(p))
        result = extracted('AppImage/scripts/security_manager.py', 'uninstall_lynis', {'os': fake_os})()
        self.assertFalse(result[0])
        self.assertEqual(result[3], 'no_files')
        manager = SimpleNamespace(uninstall_lynis=lambda: result)
        route = extracted('AppImage/scripts/flask_security_routes.py', 'lynis_uninstall', {'security_manager': manager, 'jsonify': lambda data: data})
        self.assertEqual(route()['outcome'], 'no_files')

    def test_report_outcomes(self):
        paths = ['/var/log/lynis-report.dat', '/var/log/lynis.log', '/var/log/lynis-output.log']
        for fail_at in (None, 0, 1, 'missing'):
            with self.subTest(fail_at=fail_at):
                removed = []
                def remove(p):
                    if fail_at in (0, 1) and p == paths[fail_at]:
                        raise PermissionError('inert denial')
                    removed.append(p)
                fake_os = SimpleNamespace(path=SimpleNamespace(isfile=lambda p: fail_at != 'missing'), remove=remove)
                ns = {'security_manager': object(), 'jsonify': lambda data: data}
                orig_import = __import__
                with patch('builtins.__import__', side_effect=lambda n, *a, **kw: fake_os if n == 'os' else orig_import(n, *a, **kw)):
                    result = extracted('AppImage/scripts/flask_security_routes.py', 'lynis_report_delete', ns)()
                body, status = result if isinstance(result, tuple) else (result, 200)
                self.assertEqual(removed, paths[:fail_at] if fail_at in (0, 1) else ([] if fail_at == 'missing' else paths))
                self.assertEqual(body['success'], fail_at is None)
                if fail_at == 'missing':
                    self.assertEqual(body['outcome'], 'no_files')
                elif fail_at in (0, 1):
                    self.assertEqual(status, 500)
                    self.assertEqual(body['partial'], fail_at == 1)
                    self.assertIn('inert denial', body['message'])

    def test_uninstall_outcomes_and_route(self):
        targets = ['/opt/lynis', '/usr/local/bin/lynis', '/var/log/lynis-report.dat', '/var/log/lynis.log', '/var/log/lynis-output.log']
        for fail_at in (None, 0, 2):
            with self.subTest(fail_at=fail_at):
                removed = []
                def remove(path):
                    if fail_at is not None and path == targets[fail_at]: raise PermissionError('inert denial')
                    removed.append(path)
                fake_os = SimpleNamespace(path=SimpleNamespace(exists=lambda p: p in targets, join=lambda *parts: '/'.join(parts)), remove=remove)
                fake_shutil = SimpleNamespace(rmtree=remove)
                orig_import = __import__
                with patch('builtins.__import__', side_effect=lambda n, *a, **kw: fake_shutil if n == 'shutil' else orig_import(n, *a, **kw)):
                    result = extracted('AppImage/scripts/security_manager.py', 'uninstall_lynis', {'os': fake_os})()
                self.assertEqual(removed, targets[:fail_at] if fail_at is not None else targets)
                self.assertEqual(result[0], fail_at is None)
                self.assertEqual(result[2], fail_at == 2)
                manager = SimpleNamespace(uninstall_lynis=lambda: result)
                route = extracted('AppImage/scripts/flask_security_routes.py', 'lynis_uninstall', {'security_manager': manager, 'jsonify': lambda data: data})
                self.assertEqual(route()['partial'], fail_at == 2)

if __name__ == '__main__': unittest.main()
