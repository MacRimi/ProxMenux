"""Execute the build's literal backend copies, then a clean shipped-only runtime."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
PROBE = r'''
import ast, pathlib, sys, types, typing
stage = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(stage))
assert 'health_recovery' not in sys.modules
import notification_templates as templates
from notification_channels import EmailChannel
import health_recovery
for module in (templates, health_recovery, sys.modules['notification_channels']):
    assert pathlib.Path(module.__file__).parent == stage
assert not any('projects/proxmox' in p for p in sys.path)
templates._get_hostname = lambda: 'node-a'
channel = object.__new__(EmailChannel)
channel.subject_prefix = '[ProxMenux]'
neutral = {'hostname': 'node-a', 'category': 'cpu', 'reason': 'CPU high', '_event_type': 'error_resolved'}
templates.render_template('error_resolved', neutral)
templates.enrich_with_emojis('error_resolved', 'Observation', 'Body', neutral)
channel._format_html('Observation', 'Body', 'OK', neutral)
templates.render_template('node_reconnect', {'hostname': 'node-a'})
now = 1000.0
calls = []
ns = dict(vars(typing), time=types.SimpleNamespace(time=lambda: now),
    os=types.SimpleNamespace(cpu_count=lambda: 4),
    psutil=types.SimpleNamespace(cpu_percent=lambda **kw: 20, cpu_count=lambda: 4),
    health_persistence=types.SimpleNamespace(resolve_error=lambda *a, **kw: calls.append((a, kw))))
tree = ast.parse((stage/'health_monitor.py').read_text())
owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'HealthMonitor')
node = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == '_check_cpu_with_hysteresis')
exec(compile(ast.Module(body=[node], type_ignores=[]), 'shipped_cpu', 'exec'), ns)
monitor = types.SimpleNamespace(state_history={'cpu_usage': [{'value':20,'time':now-i*10} for i in range(1,11)]},
    CPU_WARNING=85, CPU_CRITICAL=95, CPU_RECOVERY=75, CPU_WARNING_DURATION=300,
    CPU_CRITICAL_DURATION=300, CPU_RECOVERY_DURATION=120, _check_cpu_temperature=lambda:None)
assert ns['_check_cpu_with_hysteresis'](monitor)['status'] == 'OK'
assert len(calls) == 1 and calls[0][1]['check_evidence']['value'] == 20
proof = calls[0][1]['check_evidence']
native = dict(neutral, error_key='cpu_usage', check_evidence=proof, is_recovery=True, recovery_outcome='resolved')
# Actual body/icon/email consumers from the package, no source-module fixture rescue.
import unittest.mock
with unittest.mock.patch('health_recovery.time.time', return_value=now):
    result = templates.render_template('error_resolved', native)
    title, body = result['title'], result['body']
    assert 'Resolved' in title and 'fresh health check' in body, (title, body, proof)
    rich_title, rich_body = templates.enrich_with_emojis('error_resolved', title, body, native)
    assert rich_title.startswith('✅')
    assert 'background:#f0fdf4;' in channel._format_html(title, body, 'OK', native)
print('shipped-only neutral body/icon/email + CPU native measurement/proof consumers PASS')
'''


class PackagedRecoveryTests(unittest.TestCase):
    def test_actual_copy_manifest_supports_isolated_recovery_runtime(self):
        source = ROOT / 'AppImage/scripts'
        build = (source / 'build_appimage.sh').read_text()
        lines = [line for line in build.splitlines()
                 if re.match(r'^cp "\$SCRIPT_DIR/[^"/]+\.py" "\$APP_DIR/usr/bin/"', line)]
        self.assertTrue(lines)
        catalog_copy = re.search(r'^for locale in en de es fr it pt sk sv; do\n.*?^done$', build, re.MULTILINE | re.DOTALL)
        if catalog_copy is None:
            self.fail('The shipped locale-copy loop was not found in the actual build script')
        lines.append(catalog_copy.group(0))
        with tempfile.TemporaryDirectory(prefix='shipped-recovery-') as directory:
            stage = Path(directory) / 'usr/bin'
            stage.mkdir(parents=True)
            copied = subprocess.run(['/bin/bash'], input='set -e\n'+'\n'.join(lines)+'\n', text=True,
                capture_output=True, env={**os.environ, 'SCRIPT_DIR': str(source), 'APPIMAGE_ROOT': str(source.parent), 'APP_DIR': directory})
            self.assertEqual(copied.returncode, 0, copied.stderr)
            result = subprocess.run([sys.executable, '-I', '-B', '-c', PROBE, str(stage)],
                cwd=directory, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
