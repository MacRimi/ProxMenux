"""Downstream Proxmox builds (PXVIRT) keep their APT sources: fixture-only checks.

No host pvesh, dpkg or APT command runs here; the authentic capture is read-only.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'scripts/global/repository_policy.py'
PLATFORM = ROOT / 'scripts/global/proxmox_platform.py'
HELPER = ROOT / 'scripts/global/repository-functions.sh'
CAPTURE = ROOT / 'tests/fixtures/pxvirt-9.0-arm64-raspberry-pi.json'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repo(components, *, uri='https://mirror.example/debian/pve', suite='trixie', enabled=True, types='deb'):
    return {'Types': types.split(), 'URIs': [uri], 'Suites': [suite],
            'Components': components.split(), 'Enabled': enabled}


def inventory(*files, infos=None):
    data = {'files': [{'path': path, 'repositories': rows} for path, rows in files],
            'errors': [], 'digest': 'fixture-digest',
            'standard-repos': [{'handle': 'no-subscription', 'name': 'PVE No-Subscription'}]}
    if infos is not None:
        data['infos'] = infos
    return data


class DownstreamPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load(POLICY, 'repository_policy_downstream')

    def setUp(self):
        self.calls = []
        self.writes = 0
        self.variant = ''
        self.subscription = 'status: notfound\nmessage: There is no subscription key\n'
        self.repositories = inventory(
            ('/etc/apt/sources.list.d/pve-enterprise.list', [repo('pve-enterprise')]),
            ('/etc/apt/sources.list', [repo('main contrib', uri='http://deb.debian.org/debian')]),
        )
        patcher = patch.object(self.module, 'downstream_variant', side_effect=lambda: self.variant)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_policy(self, apply=False, suite='trixie', product='pve'):
        def run(args):
            self.calls.append(args)
            if args[:2] == ['pvesubscription', 'get'] or args[:1] == ['proxmox-backup-manager']:
                if isinstance(self.subscription, Exception):
                    raise self.subscription
                return self.subscription
            if 'get' in args[:3]:  # pvesh get … / proxmox-backup-debug api get …
                return json.dumps(self.repositories)
            self.writes += 1
            return ''
        with patch.object(self.module, 'run', side_effect=run):
            return self.module.evaluate(suite, apply=apply, product=product)

    def test_authentic_pxvirt_capture_is_downstream_without_lookup_or_writes(self):
        capture = CAPTURE.read_bytes()
        for apply in (False, True):
            with self.subTest(apply=apply):
                self.setUp()
                self.repositories = json.loads(capture)
                # PXVIRT answers `status: active`; the policy must not even ask.
                self.subscription = RuntimeError('must not query subscription')
                before = json.dumps(self.repositories)
                self.assertEqual(self.run_policy(apply=apply), 'downstream')
                self.assertEqual(json.dumps(self.repositories), before)
                self.assertEqual(self.writes, 0)
                self.assertEqual([c[:2] for c in self.calls], [['pvesh', 'get']])

    def test_origin_info_alone_marks_downstream(self):
        path = '/etc/apt/sources.list.d/port.list'
        self.repositories = inventory(
            ('/etc/apt/sources.list', [repo('main contrib', uri='http://deb.debian.org/debian')]),
            (path, [repo('main', uri='https://mirror.example/port')]),
            infos=[{'index': 0, 'kind': 'origin', 'message': 'Lierfang', 'path': path}],
        )
        self.subscription = RuntimeError('must not query subscription')
        self.assertEqual(self.run_policy(), 'downstream')
        self.assertEqual(self.writes, 0)

    def test_mirror_path_alone_marks_downstream(self):
        self.repositories['files'].append({'path': '/etc/apt/sources.list.d/pxvirt-sources.list',
                                           'repositories': [repo('main', uri='https://apt.dedi.zone/pxcloud/pxvirt')]})
        self.subscription = RuntimeError('must not query subscription')
        self.assertEqual(self.run_policy(apply=True), 'downstream')
        self.assertEqual(self.writes, 0)

    def test_package_marker_alone_marks_downstream(self):
        self.variant = 'pxvirt'
        self.subscription = RuntimeError('must not query subscription')
        self.assertEqual(self.run_policy(apply=True), 'downstream')
        self.assertEqual(self.writes, 0)

    def test_disabled_or_source_only_downstream_entries_do_not_count(self):
        path = '/etc/apt/sources.list.d/pveport.list'
        self.repositories['files'].append({'path': path, 'repositories': [
            repo('main', uri='https://mirrors.lierfang.com/pxcloud/pxvirt', enabled=False),
            repo('main', uri='https://mirrors.lierfang.com/pxcloud/pxvirt', types='deb-src'),
        ]})
        self.repositories['infos'] = [{'index': i, 'kind': 'origin', 'message': 'Lierfang', 'path': path} for i in (0, 1)]
        self.assertEqual(self.run_policy(), 'offer')
        self.assertIn(['pvesubscription', 'get'], [c[:2] for c in self.calls])

    def test_malformed_infos_fall_back_to_the_other_checks(self):
        for infos in ('garbage', [None, 7, {'kind': 'origin'}, {'kind': 'origin', 'message': 5}], {}):
            with self.subTest(infos=infos):
                self.setUp()
                self.repositories['infos'] = infos
                self.assertEqual(self.run_policy(), 'offer')

    def test_upstream_host_is_not_downstream(self):
        self.assertEqual(self.run_policy(), 'offer')
        self.repositories = json.loads((ROOT / 'tests/fixtures/pr407-macrimi-pve9.2-no-subscription.json').read_bytes())
        self.assertEqual(self.run_policy(), 'preserve')

    def test_pbs_product_uses_the_same_detection(self):
        self.repositories = inventory(
            ('/etc/apt/sources.list', [repo('main contrib', uri='http://deb.debian.org/debian')]),
            ('/etc/apt/sources.list.d/pxvirt-sources.list', [repo('main', uri='https://mirrors.lierfang.com/pxcloud/pxvirt')]),
        )
        self.subscription = RuntimeError('must not query subscription')
        self.assertEqual(self.run_policy(product='pbs'), 'downstream')

    def test_cli_prints_downstream_decision(self):
        with patch.object(self.module, 'run', side_effect=lambda args: json.dumps(json.loads(CAPTURE.read_bytes()))), \
             patch.object(self.module.sys, 'argv', ['repository_policy.py', 'plan', 'trixie']), \
             patch('builtins.print') as printed:
            self.assertEqual(self.module.main(), 0)
        printed.assert_called_once_with('downstream')


class PlatformVariantTest(unittest.TestCase):
    def detect(self, rows, codename='trixie'):
        module = load(PLATFORM, 'proxmox_platform_variant')
        stdout = ''.join(f'{package}\tinstall ok installed\t{version}\n' for package, version in rows)
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            release = Path(directory) / 'os-release'
            release.write_text(f'ID=debian\nVERSION_CODENAME={codename}\n')
            with patch.object(module, 'OS_RELEASE', release), \
                 patch.object(module.subprocess, 'run',
                              return_value=subprocess.CompletedProcess([], 1, stdout=stdout, stderr='')) as run:
                data = module.detect_platform()
        self.assertIn('proxmox-kernel-helper', run.call_args.args[0])
        return data

    def test_pxvirt_markers_set_the_variant_and_keep_the_product(self):
        for rows in (
            [('pve-manager', '9.0.10-2'), ('proxmox-kernel-helper', '9.0.4+pxvirt1'), ('pve-qemu-kvm', '10.0.9')],
            [('pve-manager', '9.0.10-2'), ('proxmox-kernel-helper', '9.0.4'), ('pve-qemu-kvm', '10.0.2-4+port1')],
        ):
            with self.subTest(rows=rows):
                data = self.detect(rows)
                self.assertEqual((data['product'], data['major'], data['variant'], data['supported']),
                                 ('pve', 9, 'pxvirt', True))

    def test_upstream_versions_leave_the_variant_empty(self):
        data = self.detect([('pve-manager', '9.2.20'), ('proxmox-kernel-helper', '9.2.0'), ('pve-qemu-kvm', '11.1.1-2')])
        self.assertEqual((data['product'], data['variant']), ('pve', ''))
        self.assertEqual(self.detect([])['variant'], '')

    def test_field_flag_accepts_variant(self):
        result = subprocess.run(['python3', '-I', str(PLATFORM), '--field', 'variant'],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


class DownstreamShellTest(unittest.TestCase):
    def run_helper(self, function, product):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            calls = Path(directory) / 'calls'
            script = f'''source "{HELPER}"
                translate() {{ printf %s "$1"; }}
                msg_info() {{ printf 'spinner: %s\\n' "$1"; }}
                msg_info2() {{ printf 'info: %s\\n' "$1"; }}
                msg_error() {{ printf 'error: %s\\n' "$1" >&2; }}
                pveversion() {{ echo pve-manager/9.0.10-2/74d1bcc54a6e6730; }}
                pmx_is_pbs() {{ [[ "{product}" == pbs ]]; }}
                pmx_platform_field() {{ [[ "$1" == codename ]] && echo trixie || echo true; }}
                repository_policy() {{ printf 'policy %s\\n' "$*" >> "{calls}"; echo downstream; }}
                hybrid_yesno() {{ printf 'prompt\\n' >> "{calls}"; }}
                apt-get() {{ printf 'apt %s\\n' "$*" >> "{calls}"; }}
                {function}
            '''
            result = subprocess.run(['/bin/bash', '-c', script], stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=15)
            recorded = calls.read_text().splitlines() if calls.exists() else []
        return result, recorded

    def test_pve_downstream_decision_succeeds_without_prompt_or_apt(self):
        result, calls = self.run_helper('ensure_repositories', 'pve')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['policy plan trixie'])
        self.assertIn('PXVIRT', result.stdout)
        self.assertIn('left unchanged', result.stdout)
        self.assertNotIn('spinner:', result.stdout)  # no spinner left running behind the caller
        self.assertEqual(result.stderr, '')

    def test_pbs_downstream_decision_succeeds_without_prompt_or_apt(self):
        result, calls = self.run_helper('ensure_pbs_repositories', 'pbs')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['policy plan trixie pbs'])
        self.assertIn('left unchanged', result.stdout)
        self.assertEqual(result.stderr, '')


class UpdateScriptsDownstreamTest(unittest.TestCase):
    """The post-install updaters rewrite the APT sources themselves; on a downstream
    build they must skip that and still offer the package upgrade."""

    def run_updater(self, path, name, decision):
        source = (ROOT / path).read_text()
        start = source.index(f'\n{name}() {{\n') + 1
        body = source[start:source.index('\n}\n', start) + 3]
        self.assertEqual(body.count('/var/log/'), 1)
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            d = Path(directory)
            bindir = d / 'bin'
            bindir.mkdir()
            for cmd in ('grep', 'head', 'tee', 'date', 'awk', 'rm', 'cat', 'sed', 'cut', 'xargs',
                        'hostname', 'printf', 'env', 'mktemp', 'cp', 'mkdir', 'basename', 'clear'):
                target = shutil.which(cmd)
                if target:
                    (bindir / cmd).symlink_to(target)
            stubs = {
                'python3': f'echo {decision}',
                'df': "printf 'Filesystem 1K-blocks Used Available Use%% Mounted on\\nfixture 9999999 1 9999999 1%% /\\n'",
                'ping': 'exit 1',
                'apt-get': f'echo "apt-get $*" >> "{d}/calls"',
                'apt': 'echo Listing...; echo "pve-manager/stable 9.0.10-2 arm64 [upgradable from: 9.0.10-1]"',
                'apt-cache': 'echo "  Candidate: 9.0.10"',
                'pveversion': 'echo pve-manager/9.0.10-2/74d1bcc54a6e6730',
                'lsb_release': 'echo trixie', 'whiptail': 'exit 0', 'pvesh': 'exit 1',
            }
            for cmd, text in stubs.items():
                stub = bindir / cmd
                stub.write_text(f'#!/bin/bash\n{text}\n')
                stub.chmod(0o755)
            body = body.replace('/var/log/', f'{d}/').replace('/tmp/proxmenux_screen_capture_', f'{d}/screen_')
            script = f'''
                LOCAL_SCRIPTS="{d}/missing"; APT_ENV="env LC_ALL=C"; SCRIPT_TITLE=fixture; TAB=""
                for fn in pmx_journal_context download_common_functions show_proxmenux_logo msg_title \\
                    msg_ok msg_warn msg_success pmx_record_execution cleanup_duplicate_repos; do
                    eval "$fn() {{ :; }}"
                done
                translate() {{ printf %s "$1"; }}
                msg_error() {{ printf 'error: %s\\n' "$1" >&2; }}
                msg_info() {{ printf 'info: %s\\n' "$1"; }}
                msg_info2() {{ printf 'info2: %s\\n' "$1"; }}
                pmx_format_upgradable() {{ cat; }}
                pmx_confirm_update() {{ echo "confirm" >> "{d}/calls"; return 1; }}
                for fn in pmx_write_file pmx_edit_file pmx_remove_file pmx_append_file chmod; do
                    eval "$fn() {{ echo \\"$fn $*\\" >> \\"{d}/writes\\"; }}"
                done
                {body}
                {name}
            '''
            result = subprocess.run(['/bin/bash', '-c', script],
                                    env={'PATH': str(bindir), 'TMPDIR': str(d), 'HOME': str(d)},
                                    stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=30)
            calls = (d / 'calls').read_text().splitlines() if (d / 'calls').exists() else []
            writes = (d / 'writes').read_text().splitlines() if (d / 'writes').exists() else []
        return result, calls, writes

    def test_downstream_skips_source_rewrite_and_still_offers_the_upgrade(self):
        for path, name in (('scripts/global/update-pve9_2.sh', 'update_pve9'),
                           ('scripts/global/update-pve8.sh', 'update_pve8')):
            with self.subTest(path=path):
                result, calls, writes = self.run_updater(path, name, 'downstream')
                self.assertIn('left unchanged', result.stdout, result.stderr)
                self.assertNotIn('Cannot reach Proxmox repositories', result.stdout)
                self.assertEqual(writes, [], writes)
                self.assertEqual(calls[:2], ['apt-get update', 'confirm'], (calls, result.stderr))

    def test_upstream_host_still_configures_the_sources(self):
        for path, name, marker in (('scripts/global/update-pve9_2.sh', 'update_pve9', 'proxmox.sources'),
                                   ('scripts/global/update-pve8.sh', 'update_pve8', 'pve-public-repo.list')):
            with self.subTest(path=path):
                result, calls, writes = self.run_updater(path, name, 'offer')
                # ping is stubbed to fail: the upstream path stops at the reachability check...
                self.assertIn('Cannot reach Proxmox repositories', result.stdout + result.stderr)
                self.assertNotIn('left unchanged', result.stdout)
                self.assertEqual(writes, [])
                self.assertIn(marker, (ROOT / path).read_text())

    def test_written_apt_sources_start_at_column_zero(self):
        # In deb822 a leading space continues the previous field: APT then
        # silently reads no source at all from the file.
        for path in ('scripts/global/update-pve9_2.sh', 'scripts/global/update-pve8.sh'):
            inside = False
            for number, line in enumerate((ROOT / path).read_text().splitlines(), 1):
                if inside:
                    if line == 'EOF':
                        inside = False
                    else:
                        with self.subTest(path=path, line=number):
                            self.assertEqual(line, line.lstrip())
                elif 'pmx_write_file' in line and line.endswith('<< EOF'):
                    inside = True


if __name__ == '__main__':
    unittest.main()
