"""Fixture-only policy checks: never call host pvesh or edit host APT sources."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'scripts/global/repository_policy.py'


def repo(components, *, uri='https://mirror.example/debian/pve', suite='trixie', enabled=True):
    return {'Types': ['deb'], 'URIs': [uri], 'Suites': [suite],
            'Components': components.split(), 'Enabled': enabled}


def fixture(*entries):
    files = {}
    for path, entries_for_file in entries:
        files[path] = {'path': path, 'repositories': entries_for_file}
    return {'files': list(files.values()), 'errors': [], 'digest': 'fixture-digest',
            'standard-repos': [{'handle': 'no-subscription', 'name': 'PVE No-Subscription'}]}


class RepositoryPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('repository_policy', POLICY)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.calls = []
        self.mutate = True
        self.after_write = lambda: None
        self.writes = 0
        self.subscription = 'status: notfound\nmessage: There is no subscription key\n'
        self.repositories = fixture(
            ('/etc/apt/sources.list.d/custom.sources', [repo('pve-enterprise')]),
            ('/etc/apt/sources.list.d/debian.sources', [repo('main', uri='https://deb.example/debian')]),
        )

    def run_policy(self, apply=False, suite='trixie'):
        def run(args):
            self.calls.append(args)
            if args[:2] == ['pvesubscription', 'get']:
                if isinstance(self.subscription, Exception):
                    raise ValueError('service unavailable') from self.subscription
                return self.subscription
            if args[:2] == ['pvesh', 'get']:
                return json.dumps(self.repositories)
            if args[1] in ('create', 'set'):
                self.assertEqual(args[args.index('--digest') + 1], self.repositories['digest'])
                self.writes += 1
            if self.mutate and args[:2] == ['pvesh', 'create']:
                path = args[args.index('--path') + 1]
                index = int(args[args.index('--index') + 1])
                next(f for f in self.repositories['files'] if f['path'] == path)['repositories'][index]['Enabled'] = False
            if self.mutate and args[:2] == ['pvesh', 'set']:
                self.repositories['files'].append({'path': '/etc/apt/sources.list.d/proxmox.sources',
                    'repositories': [repo('pve-no-subscription')]})
            self.repositories['digest'] = f'write-{self.writes}'
            self.after_write()
            return ''
        with patch.object(self.module, 'run', side_effect=run):
            return self.module.evaluate(suite, apply=apply)

    def test_concurrent_inventory_edit_aborts_before_second_mutation(self):
        for edit in ('replace', 'reorder', 'unrelated'):
            with self.subTest(edit=edit):
                self.setUp()
                rows = self.repositories['files'][0]['repositories']
                rows.extend([repo('enterprise', uri='https://example/ceph-squid'),
                             repo('custom')])

                def external_edit():
                    if self.writes != 1:
                        return
                    if edit == 'replace':
                        rows[1] = repo('custom-replacement')
                    elif edit == 'reorder':
                        rows[1], rows[2] = rows[2], rows[1]
                    else:
                        self.repositories['files'][1]['repositories'][0]['Options'] = [
                            {'Key': 'Signed-By', 'Values': ['/external/keyring.gpg']}]
                    self.repositories['digest'] = 'external-edit'

                self.after_write = external_edit
                with self.assertRaises(ValueError):
                    self.run_policy(apply=True)
                self.assertEqual(self.writes, 1)
                self.assertTrue(rows[1]['Enabled'])
                self.assertTrue(rows[2]['Enabled'])

    def test_failed_post_write_readback_reports_partial_or_unknown_state(self):
        for after in (1, 2):
            with self.subTest(after=after):
                self.setUp()

                def break_readback():
                    if self.writes == after:
                        self.repositories['errors'] = [{'error': 'external parse error'}]

                self.after_write = break_readback
                with self.assertRaises(ValueError) as error:
                    self.run_policy(apply=True)
                self.assertEqual(self.writes, after)
                self.assertNotIn('no repository changed', str(error.exception))
                self.assertRegex(str(error.exception), 'partial|unknown')

    def test_inventory_comparison_accepts_api_serialization_and_new_digests(self):
        self.repositories['files'][0]['repositories'].append(
            repo('enterprise', uri='https://example/ceph-squid'))
        self.repositories['files'].append({'path': '/etc/apt/sources.list.d/flat.list',
            'repositories': [repo('', uri='https://example/flat', suite='./')]})

        def serialize():
            for file in self.repositories['files']:
                file['digest'] = f'file-digest-{self.writes}'
                for row in file['repositories']:
                    if row.get('Components') == []:
                        del row['Components']
            self.repositories['files'].reverse()

        self.after_write = serialize
        self.assertEqual(self.run_policy(apply=True), 'changed')
        self.assertEqual(self.writes, 3)

    def test_fresh_iso_requires_consent_before_any_write(self):
        self.assertEqual(self.run_policy(), 'offer')
        self.assertFalse(any(c[1] in ('create', 'set') for c in self.calls))

    def test_consented_switch_disables_enterprise_then_adds_public_pve(self):
        self.assertEqual(self.run_policy(apply=True), 'changed')
        writes = [c for c in self.calls if c[1] in ('create', 'set')]
        self.assertEqual([c[1] for c in writes], ['create', 'set'])
        self.assertEqual(writes[0][writes[0].index('--path') + 1], '/etc/apt/sources.list.d/custom.sources')
        self.assertEqual(writes[0][writes[0].index('--enabled') + 1], '0')
        self.assertEqual(writes[1][writes[1].index('--handle') + 1], 'no-subscription')

    def test_api_noop_after_write_does_not_report_success(self):
        self.mutate = False
        with self.assertRaisesRegex(ValueError, 'verify'):
            self.run_policy(apply=True)

    def test_flat_repository_without_components_is_preserved(self):
        self.subscription = 'status: active\n'
        flat = repo('', uri='https://vendor.example/flat', suite='./')
        del flat['Components']
        self.repositories['files'].append({'path': '/etc/apt/sources.list.d/vendor.list',
                                           'repositories': [flat]})
        before = json.dumps(self.repositories)
        self.assertEqual(self.run_policy(apply=True), 'preserve')
        self.assertEqual(json.dumps(self.repositories), before)
        self.assertEqual(self.writes, 0)

    def test_malformed_components_fail_closed(self):
        self.subscription = 'status: active\n'
        for components in (None, 'main', {}, [42]):
            with self.subTest(components=components):
                self.repositories['files'][1]['repositories'][0]['Components'] = components
                with self.assertRaises(ValueError):
                    self.run_policy(apply=True)
                self.assertEqual(self.writes, 0)

    def test_active_subscription_preserves_enterprise(self):
        self.subscription = 'key: pve1x-SECRET\nstatus: active\nserverid: SECRET\n'
        self.assertEqual(self.run_policy(apply=True), 'preserve')
        self.assertFalse(any(c[1] in ('create', 'set') for c in self.calls))

    def test_active_subscription_without_pve_source_stops_without_add(self):
        self.subscription = 'status: active\n'
        self.repositories['files'][0]['repositories'][0]['Enabled'] = False
        with self.assertRaisesRegex(ValueError, 'active subscription'):
            self.run_policy(apply=True)
        self.assertFalse(any(c[1] in ('create', 'set') for c in self.calls))

    def test_existing_public_or_test_preserved_without_switch(self):
        for channel in ('pve-no-subscription', 'pve-test'):
            with self.subTest(channel=channel):
                self.repositories['files'][0]['repositories'] = [repo(channel)]
                self.assertEqual(self.run_policy(), 'preserve')

    def test_legacy_pvetest_list_on_pve8_is_preserved(self):
        self.repositories = fixture(
            ('/etc/apt/sources.list.d/operator.list', [repo('pvetest', suite='bookworm')]),
            ('/etc/apt/sources.list', [repo('main', uri='https://deb.example/debian', suite='bookworm')]),
        )
        self.assertEqual(self.run_policy(suite='bookworm'), 'preserve')

    def test_disabled_enterprise_stanza_is_not_disabled_again(self):
        self.repositories['files'][0]['repositories'][0]['Enabled'] = False
        self.assertEqual(self.run_policy(apply=True), 'changed')
        self.assertFalse(any(c[1] == 'create' for c in self.calls))

    def test_unrecognized_and_failed_subscription_cannot_mutate(self):
        for response in ('status: unknown\n', 'status: invalid\n', 'status: active\nstatus: notfound\n',
                         'key: secret\n', RuntimeError('service unavailable')):
            with self.subTest(response=response):
                self.subscription = response
                self.calls = []
                with self.assertRaises(ValueError):
                    self.run_policy(apply=True)
                self.assertFalse(any(c[1] in ('create', 'set') for c in self.calls))

    def test_multiple_stanzas_disables_only_pve_enterprise_and_ceph_enterprise(self):
        self.repositories = fixture(
            ('/etc/apt/sources.list.d/anything.sources', [
                repo('main', uri='https://debian.example/debian'),
                repo('pve-enterprise'),
                repo('enterprise', uri='https://enterprise.proxmox.com/debian/ceph-squid'),
                repo('pve-enterprise', enabled=False),
            ]),
        )
        self.assertEqual(self.run_policy(apply=True), 'changed')
        writes = [c for c in self.calls if c[1] == 'create']
        self.assertEqual([int(c[c.index('--index') + 1]) for c in writes], [1, 2])

    def test_mixed_components_block_switch_without_partial_write(self):
        self.repositories['files'][0]['repositories'] = [repo('pve-enterprise custom')]
        with self.assertRaises(ValueError):
            self.run_policy(apply=True)
        self.assertFalse(any(c[1] in ('create', 'set') for c in self.calls))

    def test_wrong_suite_and_parse_errors_block_before_writes(self):
        for mode in ('suite', 'error'):
            with self.subTest(mode=mode):
                self.repositories = fixture(
                    ('/etc/apt/sources.list.d/custom.list', [repo('pve-enterprise', suite='bookworm')]),
                    ('/etc/apt/sources.list.d/debian.sources', [repo('main', uri='https://deb.example/debian')]),
                )
                if mode == 'error':
                    self.repositories['errors'] = [{'path': 'custom.list', 'error': 'invalid'}]
                with self.assertRaises(ValueError):
                    self.run_policy(apply=True)
                self.assertFalse(any(c[1] in ('create', 'set') for c in self.calls))

    def test_ceph_enterprise_mirror_is_disabled_without_choosing_ceph_channel(self):
        self.repositories['files'].append({'path': '/etc/apt/sources.list.d/storage.list',
            'repositories': [repo('enterprise', uri='https://mirror.example/ceph-squid')]})
        self.assertEqual(self.run_policy(apply=True), 'changed')
        writes = [c for c in self.calls if c[1] == 'create']
        self.assertEqual(len(writes), 2)
        self.assertFalse(any(c[1] == 'set' and 'ceph' in ' '.join(c) for c in self.calls))

    def test_wrong_suite_ceph_stops_before_switch(self):
        self.repositories['files'].append({'path': '/etc/apt/sources.list.d/ceph.sources',
            'repositories': [repo('enterprise', uri='https://enterprise.proxmox.com/debian/ceph-reef', suite='bookworm')]})
        with self.assertRaisesRegex(ValueError, 'suite'):
            self.run_policy(apply=True)
        self.assertFalse(any(c[1] in ('create', 'set') for c in self.calls))

    def test_missing_debian_base_blocks_switch(self):
        self.repositories['files'].pop()
        with self.assertRaises(ValueError):
            self.run_policy(apply=True)
        self.assertFalse(any(c[1] in ('create', 'set') for c in self.calls))


class CallerPropagationTest(unittest.TestCase):
    def test_safe_update_refusal_blocks_apt_update(self):
        source = (ROOT / 'scripts/global/update-pve-safe.sh').read_text()
        body = source.split('update_pve_safe() {', 1)[1].split(
            '\nif [[ "${BASH_SOURCE[0]}"', 1)[0]
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as d:
            body = body.replace('/var/log/', f'{d}/').replace(
                '/tmp/proxmenux_screen_capture_', f'{d}/proxmenux_screen_capture_')
            script = '''
                pveversion() { printf 'pve-manager/9.0.0\\n'; }
                translate() { printf '%s' "$1"; }
                msg_info2() { :; }
                msg_error() { :; }
                df() { printf 'Filesystem 1K-blocks Used Available Use%% Mounted on\\n';
                       printf 'fixture 9999999 1 9999999 1%% /\\n'; }
                download_common_functions() { :; }
                source_install_functions() { :; }
                ensure_repositories() { return 1; }
                apt-get() { touch "$TEST_ROOT/apt_called"; }
                update_pve_safe() {
            ''' + body + '\nupdate_pve_safe\n'
            result = subprocess.run(['bash', '-c', script], env=dict(os.environ, TEST_ROOT=d),
                                    capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                    timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(d) / 'apt_called').exists())

    def test_nvidia_refusal_preserves_working_driver_before_uninstall(self):
        source = (ROOT / 'scripts/gpu_tpu/nvidia_installer.sh').read_text()
        main = 'main() {' + source.split('main() {', 1)[1].split(
            '\n# ==========================================================\n# Non-interactive', 1)[0]
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as d:
            script = '''
                LOG_FILE="$TEST_ROOT/log"; screen_capture="$TEST_ROOT/screen"
                NVIDIA_GPU_PRESENT=true; CURRENT_DRIVER_INSTALLED=true
                CURRENT_DRIVER_VERSION=580.1; DRIVER_VERSION=580.2; ACTION=install
                for fn in detect_nvidia_gpus detect_driver_status check_gpu_not_in_vm_passthrough \\
                    check_stale_vfio_config_for_nvidia show_action_menu_if_installed \\
                    show_install_overview get_system_info show_version_menu hybrid_yesno \\
                    show_proxmenux_logo msg_title msg_info2 sleep; do
                    eval "$fn() { :; }"
                done
                translate() { printf '%s' "$1"; }
                ensure_repos_and_headers() { return 1; }
                download_nvidia_installer() { touch "$TEST_ROOT/downloaded"; return 1; }
                complete_nvidia_uninstall() { touch "$TEST_ROOT/uninstalled"; }
            ''' + main + '\nmain\n'
            result = subprocess.run(['bash', '-c', script],
                                    env=dict(os.environ, TEST_ROOT=d),
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(d) / 'downloaded').exists())
            self.assertFalse((Path(d) / 'uninstalled').exists())

    def test_nvidia_repository_failure_blocks_header_install(self):
        source = (ROOT / 'scripts/gpu_tpu/nvidia_installer.sh').read_text()
        fn = source.split('ensure_repos_and_headers() {', 1)[1].split(
            '\n_nouveau_legacy_file_is_proxmenux_shape()', 1)[0]
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as d:
            script = '''
                LOG_FILE="$TEST_ROOT/log"; screen_capture="$TEST_ROOT/screen"
                translate() { printf %s "$1"; }
                msg_error() { :; }
                ensure_repositories() { return 1; }
                apt-get() { touch "$TEST_ROOT/apt_called"; }
                ensure_repos_and_headers() {
            ''' + fn + '\nensure_repos_and_headers\n'
            result = subprocess.run(['bash', '-c', script], env=dict(os.environ, TEST_ROOT=d),
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(d) / 'apt_called').exists())


class ShellFlowTest(unittest.TestCase):
    def test_web_consent_applies_only_after_prompt(self):
        helper = ROOT / 'scripts/global/repository-functions.sh'
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as d:
            log = Path(d) / 'calls'
            script = f'''source "{helper}"
                pveversion() {{ echo pve-manager/9.0; }}
                translate() {{ printf %s "$1"; }}
                msg_error() {{ :; }}
                is_web_mode() {{ return 0; }}
                hybrid_yesno() {{ printf 'prompt\\n' >> "{log}"; [[ "$2" == *'This host has no subscription, switch to the no-subscription repository?'* ]]; }}
                repository_policy() {{ printf '%s\\n' "$1" >> "{log}"; [[ "$1" == plan ]] && echo offer || echo changed; }}
                ensure_repositories
            '''
            result = subprocess.run(['bash', '-c', script], input='', text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(log.read_text().splitlines(), ['plan', 'prompt', 'apply'])

    def test_refusal_and_noninteractive_never_apply(self):
        helper = ROOT / 'scripts/global/repository-functions.sh'
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as d:
            mock = Path(d) / 'policy.py'
            mock.write_text('import sys\nfrom pathlib import Path\n'
                            'Path(sys.argv[1]).open("a").write(sys.argv[2]+"\\n")\n'
                            'print("offer" if sys.argv[2] == "plan" else "changed")\n')
            for web, confirm in ((False, True), (True, False)):
                with self.subTest(web=web, confirm=confirm):
                    log = Path(d) / 'calls'
                    log.unlink(missing_ok=True)
                    script = f'''source "{helper}"
                    pveversion() {{ echo pve-manager/9.0; }}
                    translate() {{ printf %s "$1"; }}
                    msg_error() {{ :; }}
                    msg_info2() {{ :; }}
                    is_web_mode() {{ {'return 0' if web else 'return 1'}; }}
                    hybrid_yesno() {{ {'return 0' if confirm else 'return 1'}; }}
                    repository_policy() {{ python3 "{mock}" "{log}" "$1"; }}
                    ensure_repositories
                    '''
                    result = subprocess.run(['bash', '-c', script], input='', text=True, capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(log.read_text(), 'plan\n')


if __name__ == '__main__':
    unittest.main()
