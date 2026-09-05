"""Run real shells and the real LXC runner against local download/guest fixtures."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'AppImage/scripts'))
import lxc_apps

URL = 'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/odoo.sh2'
LEGACY = f'''PHS_SILENT=1 bash -c "$(wget -qLO - '{URL}')"'''


class DownloadGuardTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='proxmenux-download-test-')
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.bin = self.folder / 'bin'
        self.bin.mkdir()
        self.env = {**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
                    'PYTHONPATH': str(ROOT / 'AppImage/scripts'),
                    'FETCH_STATUS': '8', 'FETCH_BODY': '', 'VMID': '101',
                    'TARGET': 'app', 'BACKUP': '0', 'RESTART': '0',
                    'RUN_HELPER': '0', 'UPDATE_COMMAND': '',
                    'PROXMENUX_LOCK_DIR': str(self.folder)}
        for tool in ('wget', 'curl'):
            self.write(tool, '#!/bin/sh\nprintf "%s" "$FETCH_BODY"\nexit "$FETCH_STATUS"\n')
        self.write('flock', '#!/bin/sh\nexit 0\n')
        self.write('pct', '''#!/bin/bash
case "$1" in
  list) printf 'VMID Status Name\\n101 running fixture\\n' ;;
  status) echo 'status: running' ;;
  exec)
    shift 3
    case "$*" in
      *'/etc/os-release'*) echo 'ID=debian' ;;
      'test -f /usr/bin/update') exit 0 ;;
      'cat /usr/bin/update') echo 'SCRIPT_SLUG="odoo"' ;;
      *) exec "$@" ;;
    esac ;;
  *) exit 90 ;;
esac
''')
        # Only consent is stubbed. Preparation imports the real implementation.
        self.write('python3', '#!/bin/bash\n'
                   'if [[ "$2" != "protect-update-command" ]]; then exit 0; fi\n'
                   # Preload the source under test, not a monitor already
                   # installed on the build host at the production path.
                   f'exec {shlex.quote(sys.executable)} -c '
                   "'import sys, lxc_apps; exec(sys.stdin.read())'\n")

    def write(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def shell(self, command, status=8, body=''):
        return subprocess.run(['/bin/sh', '-c', command], text=True, capture_output=True,
                              env={**self.env, 'FETCH_STATUS': str(status), 'FETCH_BODY': body}, timeout=10)

    def test_reproduces_original_false_success(self):
        self.assertEqual(self.shell(LEGACY).returncode, 0)
        fixed = self.shell(lxc_apps.protect_download_update_command(LEGACY))
        self.assertNotEqual(fixed.returncode, 0)
        self.assertIn('download failed', fixed.stderr)

    def test_supported_literal_launchers_preserve_url_shell_and_environment(self):
        for tool in ('wget -qLO -', 'wget -qO-', 'wget -qO -', 'curl -fsSL', 'curl -fSL'):
            for shell in ('bash', 'sh', '/bin/bash', '/bin/sh'):
                for prefix in ('', 'PHS_SILENT=0 ', 'PHS_SILENT=1 '):
                    original = f'''{prefix}{shell} -c "$({tool} '{URL}')"'''
                    with self.subTest(command=original):
                        prepared = lxc_apps.protect_download_update_command(original)
                        self.assertNotEqual(prepared, original)
                        self.assertEqual(lxc_apps.protect_download_update_command(prepared), prepared)
                        self.assertIn(URL, prepared)
                        result = self.shell(prepared, 0, 'echo "RAN:${PHS_SILENT:-unset}"')
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.strip(), 'RAN:' + (prefix.strip()[-1] if prefix else 'unset'))

    def test_does_not_reinterpret_unrelated_or_dynamic_commands(self):
        for command in ('/opt/odoo/update.sh', 'false; true', 'echo "$(date)"',
                        'bash -c "$(wget -qLO - \'$UPDATE_URL\')"',
                        'bash -c "$(curl -fsSL https://example.com/update.sh; echo injected)"',
                        'bash -c "$(curl -fsSL https://example.com/update.sh?x=1&y=2)"',
                        'PHS_SILENT=1 bash -c "$(wget -qLO - https://example.com/update.sh)"; true',
                        'curl -fsSL https://example.com/update.sh | bash'):
            self.assertEqual(lxc_apps.protect_download_update_command(command), command)

    def test_failed_partial_and_empty_downloads_never_execute(self):
        prepared = lxc_apps.protect_download_update_command(LEGACY)
        for status, body in ((8, ''), (8, 'echo BAD_EXECUTION'), (0, '')):
            result = self.shell(prepared, status, body)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('BAD_EXECUTION', result.stdout)
        result = self.shell(prepared, 0, 'echo REAL_UPDATER; exit 23')
        self.assertEqual(result.returncode, 23)
        self.assertIn('REAL_UPDATER', result.stdout)

    def test_grouping_stops_later_apps_and_preserves_failures(self):
        command = lxc_apps.protect_download_update_command(LEGACY) + ' && echo NEXT_APP'
        self.assertNotIn('NEXT_APP', self.shell(command).stdout)
        self.assertNotIn('NEXT_APP', self.shell(command, 0, 'exit 23').stdout)
        self.assertIn('NEXT_APP', self.shell(command, 0, 'exit 0').stdout)

    def test_real_runner_reports_failure_for_both_methods(self):
        for method in ('helper', 'custom'):
            for status, body, expected in ((8, '', 4), (8, 'echo BAD_EXECUTION', 4),
                                           (0, '', 4), (0, 'exit 23', 4), (0, 'exit 0', 0)):
                with self.subTest(method=method, status=status, body=body):
                    result = subprocess.run(['/bin/bash', str(ROOT / 'scripts/lxc/apply_updates.sh')],
                        capture_output=True, text=True, timeout=15, env={**self.env,
                            'RUN_HELPER': '1' if method == 'helper' else '0',
                            'UPDATE_COMMAND': LEGACY if method == 'custom' else '',
                            'FETCH_STATUS': str(status), 'FETCH_BODY': body})
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                    self.assertEqual('=== Update complete' in result.stdout, expected == 0)
                    self.assertEqual('=== Update FAILED' in result.stdout, expected != 0)
                    self.assertNotIn('BAD_EXECUTION', result.stdout)
                    self.assert_terminal_notification(result.returncode)

    def assert_terminal_notification(self, exit_code):
        # Actual completion hook + finalizer; only IO/metadata are stubbed.
        names = {'_terminal_lxc_update_completed', '_finalize_lxc_update'}
        nodes = [n for n in ast.parse((ROOT / 'AppImage/scripts/flask_server.py').read_text()).body
                 if isinstance(n, ast.FunctionDef) and n.name in names]
        notification = Mock()
        ns = dict(os=os, time=time, re=__import__('re'), notification_manager=notification,
                  _LXC_APPLY_UPDATES_SCRIPT=str(ROOT / 'scripts/lxc/apply_updates.sh'),
                  _normalise_lxc_update_run_id=lambda value, **_: value,
                  _normalise_lxc_update_targets=lambda values, _: values,
                  _normalise_lxc_update_labels=lambda values: values,
                  _json_list=lambda _: [], _lxc_update_finalizations={},
                  _lxc_update_finalization_lock=threading.Lock(), _LXC_UPDATE_FINALIZATION_TTL=3600,
                  _fast_guest_status=lambda *_: 'stopped',
                  _lxc_update_snapshot=lambda *_: {'ct_name': 'fixture'},
                  _lxc_update_target_labels=lambda *_: ['Odoo'],
                  _lxc_update_details=lambda **kwargs: kwargs['status'],
                  get_proxmox_node_name=lambda: 'fixture-node')
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'completion', 'exec'), ns)
        params = {'RUN_ID': 'fixture-run', 'VMID': '101', 'TARGET': 'app'}
        for _ in range(2):
            ns['_terminal_lxc_update_completed'](script_path=ns['_LXC_APPLY_UPDATES_SCRIPT'],
                params=params, exit_code=exit_code, duration_seconds=1)
        notification.emit_event.assert_called_once()
        event = notification.emit_event.call_args.kwargs
        self.assertEqual(event['data']['result'], 'succeeded' if exit_code == 0 else 'failed')
        self.assertEqual(event['severity'], 'INFO' if exit_code == 0 else 'WARNING')


if __name__ == '__main__':
    unittest.main()
