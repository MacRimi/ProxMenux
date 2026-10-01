"""Isolated repository-check consumer gates; no full installer is sourced.

Synthetic policy decisions and mocked APT only. These are not live-host tests.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/global/repository-functions.sh'


def function(path, name):
    source = (ROOT / path).read_text()
    match = re.search(rf'^( *){re.escape(name)}\(\) \{{', source, re.MULTILINE)
    if not match:
        raise AssertionError(f'Missing function {name} in {path}')
    end = source.index('\n' + match[1] + '}', match.end()) + len(match[1]) + 2
    return source[match.start():end]


class RepositoryCallerTest(unittest.TestCase):
    def test_upgrade_repair_dispatch_reports_repository_failure_not_success(self):
        for path in ('scripts/utilities/upgrade_pve8_to_pve9.sh',
                     'scripts/utilities/pve8to9_check.sh'):
            source = (ROOT / path).read_text()
            commands = re.findall(r'repair_commands\+=\("([^"\n]*ensure_repositories[^"\n]*)"\)', source)
            gates = re.findall(r'if eval "\$\{repair_commands\[\$i\]\}"; then.*?\n\s*fi',
                               source, re.DOTALL)
            self.assertTrue(commands, path)
            self.assertEqual(len(commands), len(gates), path)
            for command, gate in zip(commands, gates):
                with self.subTest(path=path, command=command):
                    script = f'''
                        cleanup_duplicate_repos() {{ :; }}
                        ensure_repositories() {{ return 100; }}
                        translate() {{ printf %s "$1"; }}
                        msg_ok() {{ printf '%s\\n' "$1"; }}
                        msg_error() {{ printf '%s\\n' "$1"; }}
                        repair_commands=('{command}'); repair_descriptions=(fixture)
                        i=0; repair_success=0
                        {gate}
                        exit "$repair_success"
                    '''
                    result = subprocess.run(['/bin/bash', '-c', script], capture_output=True,
                                            text=True, timeout=15)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Failed', result.stdout)
                    self.assertNotIn('Success', result.stdout)

    def test_changed_refresh_failure_stops_all_package_consumers(self):
        consumers = [
            ('scripts/post_install/auto_post_install.sh', 'setup_proxmox_repositories', ''),
            ('scripts/post_install/customizable_post_install.sh', 'setup_proxmox_repositories', ''),
            ('scripts/utilities/system_utils.sh', 'install_utility_group', 'fixture fixturepkg'),
            ('scripts/utilities/system_utils.sh', 'install_selected_utilities', 'fixturepkg'),
            ('scripts/post_install/customizable_post_install.sh', 'install_system_utils', ''),
            ('scripts/menus/network_menu.sh', '_ensure_network_tool', 'fixturepkg'),
            ('scripts/utilities/import_vm_ova_ovf.sh', 'ensure_gawk', ''),
            ('scripts/gpu_tpu/nvidia_installer.sh', 'ensure_repos_and_headers', ''),
            ('scripts/global/update-pve-safe.sh', 'update_pve_safe', ''),
        ]
        for path, name, args in consumers:
            for pipefail in (False, True):
                with self.subTest(path=path, function=name, pipefail=pipefail):
                    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
                        d = Path(directory)
                        # Only allow read-only pipeline/log helpers from PATH.
                        bindir = d / 'bin'
                        bindir.mkdir()
                        for cmd in ('grep', 'head', 'tee', 'date', 'awk', 'rm'):
                            target = shutil.which(cmd)
                            if target is None:
                                self.fail(f'Missing fixture command: {cmd}')
                            (bindir / cmd).symlink_to(target)
                        body = function(path, name)
                        if name == 'install_system_utils':
                            # Only the actual pre-install gate, before mktemp and
                            # package iteration, is in scope for this fixture.
                            self.assertIn('    new_packages_tmp="$(mktemp)"', body)
                            body = body.split('    new_packages_tmp="$(mktemp)"', 1)[0]
                            body += '    install_single_package fixturepkg\n}'
                        if name == 'update_pve_safe':
                            self.assertEqual(body.count('/var/log/'), 1)
                            self.assertEqual(body.count('/tmp/proxmenux_screen_capture_'), 1)
                            body = body.replace('/var/log/', f'{d}/').replace(
                                '/tmp/proxmenux_screen_capture_', f'{d}/screen_')
                        script = f'''source "{HELPER}"
                            set -e; set {'-o' if pipefail else '+o'} pipefail
                            LOCAL_SCRIPTS="$TEST_ROOT/missing"
                            LOG_FILE="$TEST_ROOT/log"; screen_capture="$TEST_ROOT/screen"
                            FORMAT_TYPE=exfat; INTEL_GPU_PRESENT=true
                            INTEL_GPU_TOOLS_INSTALLED=false; PROXMENUX_UTILS=(fixturepkg:fixturepkg:fixture)
                            for fn in clear show_proxmenux_logo msg_title msg_info msg_info2 msg_info3 \\
                                msg_warn msg_success cleanup sleep pmx_journal_context detect_intel_gpus \\
                                check_intel_gpu_tools_installed download_common_functions source_install_functions; do
                                eval "$fn() {{ :; }}"
                            done
                            translate() {{ printf %s "$1"; }}
                            msg_error() {{ printf '%s\\n' "$1" >&2; }}
                            msg_ok() {{ printf '%s\\n' "$1"; }}
                            register_tool() {{ printf 'register %s\\n' "$*" >> "$TEST_ROOT/calls"; }}
                            chmod() {{ printf 'chmod\\n' >> "$TEST_ROOT/calls"; }}
                            hostname() {{ printf fixture; }}
                            pveversion() {{ echo pve-manager/9.0.0; }}
                            is_web_mode() {{ return 0; }}
                            hybrid_yesno() {{ printf 'prompt\\n' >> "$TEST_ROOT/calls"; }}
                            repository_policy() {{
                                printf '%s\\n' "$1" >> "$TEST_ROOT/calls"
                                [[ "$1" == plan ]] && echo offer || echo changed
                            }}
                            apt-get() {{ printf 'apt %s\\n' "$*" >> "$TEST_ROOT/calls"; return 100; }}
                            command() {{
                                if [[ "$1" == -v ]]; then return 1; fi
                                builtin command "$@"
                            }}
                            dialog() {{ printf fixturepkg >&2; }}
                            df() {{ printf 'Filesystem 1K-blocks Used Available Use%% Mounted on\\n';
                                   printf 'fixture 9999999 1 9999999 1%% /\\n'; }}
                            dpkg() {{ return 1; }}
                            dpkg-query() {{ return 1; }}
                            install_single_package() {{ printf 'install\\n' >> "$TEST_ROOT/calls"; }}
                            install_intel_gpu_tools() {{ printf 'install\\n' >> "$TEST_ROOT/calls"; }}
                            pmx_install_pkg() {{ printf 'install\\n' >> "$TEST_ROOT/calls"; }}
                            {body}
                            if {name} {args}; then exit 0; else exit $?; fi
                        '''
                        result = subprocess.run(['/bin/bash', '-c', script],
                                                env=dict(os.environ, PATH=str(bindir), TEST_ROOT=str(d)),
                                                stdin=subprocess.DEVNULL, text=True,
                                                capture_output=True, timeout=15)
                        calls = (d / 'calls').read_text().splitlines()
                        self.assertEqual(calls[:4], ['plan', 'prompt', 'apply', 'apt update'], result.stderr)
                        self.assertNotEqual(result.returncode, 0, result.stderr)
                        self.assertNotIn('install', calls)
                        self.assertNotIn('chmod', calls)
                        self.assertFalse(any(c.startswith('register proxmox_repos true') for c in calls))
                        self.assertIn('Repository sources changed, but APT', result.stderr + result.stdout)
                        self.assertNotIn('repositories configured', result.stdout)
                        self.assertNotIn('installation completed', result.stdout.lower())
                        self.assertNotIn('verified.', result.stdout)


if __name__ == '__main__':
    unittest.main()
