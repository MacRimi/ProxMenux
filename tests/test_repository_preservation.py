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

    def test_authentic_pve92_public_capture_preserved_without_subscription_or_writes(self):
        capture = (ROOT / 'tests/fixtures/pr407-macrimi-pve9.2-no-subscription.json').read_bytes()
        for apply in (False, True):
            with self.subTest(apply=apply):
                self.setUp()
                self.repositories = json.loads(capture)
                self.subscription = RuntimeError('must not query subscription')
                before = json.dumps(self.repositories)
                self.assertEqual(self.run_policy(apply=apply), 'preserve')
                self.assertEqual(json.dumps(self.repositories), before)
                self.assertEqual(self.writes, 0)
                self.assertEqual([c[:2] for c in self.calls], [['pvesh', 'get']])

    def simulated_enterprise_capture(self):
        # GENERATED scenario, NOT a maintainer before capture: remove public PVE,
        # enable Enterprise PVE/Ceph, and omit their serialized Enabled option.
        data = json.loads((ROOT / 'tests/fixtures/pr407-macrimi-pve9.2-no-subscription.json').read_bytes())
        data['files'] = [file for file in data['files']
                         if file['path'] != '/etc/apt/sources.list.d/proxmox.sources']
        for file in data['files']:
            for row in file['repositories']:
                if row['Components'] in (['pve-enterprise'], ['enterprise']):
                    row['Enabled'] = 1
                    row['Options'] = [option for option in row['Options']
                                      if option['Key'] != 'Enabled']
        data['digest'] = 'simulated-enterprise-before'
        return data

    def test_simulated_capture_disable_accepts_equivalent_enabled_option_serialization(self):
        for explicit_before in (False, True):
            with self.subTest(explicit_before=explicit_before):
                self.setUp()
                self.repositories = self.simulated_enterprise_capture()
                if explicit_before:
                    for file in self.repositories['files'][:2]:
                        file['repositories'][0]['Options'].append({'Key': 'Enabled', 'Values': ['true']})
                original_options = [file['repositories'][0]['Options'][0].copy()
                                    for file in self.repositories['files'][:2]]

                def serialize():
                    for file in self.repositories['files']:
                        file['digest'] = [self.writes] * 32
                        for row in file['repositories']:
                            row['Enabled'] = int(row['Enabled'])
                            if row['Components'] in (['pve-enterprise'], ['enterprise']):
                                row['Options'] = [option for option in row['Options']
                                                  if option['Key'] != 'Enabled']
                                row['Options'].append({'Key': 'Enabled', 'Values': [
                                    'true' if row['Enabled'] else 'false']})

                self.after_write = serialize
                self.assertEqual(self.run_policy(), 'offer')
                self.assertEqual(self.writes, 0)
                self.assertEqual(self.run_policy(apply=True), 'changed')
                self.assertEqual(self.writes, 3)
                for file, option in zip(self.repositories['files'][:2], original_options):
                    row = file['repositories'][0]
                    self.assertEqual(row['Enabled'], 0)
                    self.assertEqual(row['Options'], [option, {'Key': 'Enabled', 'Values': ['false']}])
                self.assertEqual([c[c.index('--path') + 1] for c in self.calls if c[1] == 'create'],
                                 ['/etc/apt/sources.list.d/pve-enterprise.sources',
                                  '/etc/apt/sources.list.d/ceph.sources'])
                self.assertEqual([c[:2] for c in self.calls if c[1] in ('create', 'set')],
                                 [['pvesh', 'create'], ['pvesh', 'create'], ['pvesh', 'set']])

    def test_malformed_or_conflicting_enabled_options_stop_before_any_write(self):
        invalid_options = (
            None, {}, 'Enabled: false', [None], [{'Key': 'Enabled'}],
            [{'Key': 'Enabled', 'Values': 'false'}],
            [{'Key': 'Enabled', 'Values': [False]}],
            [{'Key': 'Enabled', 'Values': []}],
            [{'Key': 'Enabled', 'Values': ['false', 'false']}],
            [{'Key': 'Enabled', 'Values': ['unknown']}],
            [{'Key': 'Enabled', 'Values': ['true']}],  # conflicts with Enabled=0
            [{'Key': 'Enabled', 'Values': ['false'], 'extra': 'unexpected'}],
            [{'Key': 'Enabled', 'Values': ['false']}] * 2,
            [{'Values': ['false']}], [{'Key': 1, 'Values': ['false']}],
            [{'Key': 'Signed-By', 'Values': [42]}],
        )
        for options in invalid_options:
            with self.subTest(options=options):
                self.setUp()
                self.repositories = json.loads((ROOT / 'tests/fixtures/pr407-macrimi-pve9.2-no-subscription.json').read_bytes())
                self.repositories['files'][0]['repositories'][0]['Options'] = options
                with self.assertRaisesRegex(ValueError, 'inventory'):
                    self.run_policy(apply=True)
                self.assertEqual(self.writes, 0)
                self.assertEqual([c[:2] for c in self.calls], [['pvesh', 'get']])

    def test_enabled_normalizes_only_booleans_and_integer_zero_one(self):
        for enabled in (True, False, 0, 1):
            with self.subTest(enabled=enabled):
                self.setUp()
                self.repositories['files'][0]['repositories'][0]['Enabled'] = enabled
                with patch.object(self.module, 'run', return_value=json.dumps(self.repositories)):
                    data, entries = self.module.repository_state('trixie')
                self.assertIs(entries[0][2]['Enabled'], bool(enabled))
                self.assertIs(data['files'][0]['repositories'][0]['Enabled'], bool(enabled))
        for enabled in (None, 0.0, 1.0, 0.5, -1, 2, '0', '1', 'false', [], {}):
            with self.subTest(invalid=enabled):
                self.setUp()
                self.repositories['files'][0]['repositories'][0]['Enabled'] = enabled
                with self.assertRaisesRegex(ValueError, 'inventory'):
                    self.run_policy(apply=True)
                self.assertEqual(self.writes, 0)
                self.assertEqual([c[:2] for c in self.calls], [['pvesh', 'get']])

    def test_redundant_enabled_option_keeps_authoritative_state_and_other_options(self):
        for enabled, values in ((True, ('true', 'yes', '1', 'TRUE')),
                                (False, ('false', 'no', '0', 'FALSE'))):
            for key in ('Enabled', 'enabled'):
                for value in values:
                    with self.subTest(enabled=enabled, key=key, value=value):
                        self.setUp()
                        row = self.repositories['files'][0]['repositories'][0]
                        row['Enabled'] = enabled
                        signed_by = {'Key': 'Signed-By', 'Values': ['/operator/keyring.gpg']}
                        row['Options'] = [signed_by, {'Key': key, 'Values': [value]}]
                        with patch.object(self.module, 'run', return_value=json.dumps(self.repositories)):
                            data, entries = self.module.repository_state('trixie')
                        self.assertIs(entries[0][2]['Enabled'], enabled)
                        self.assertEqual(data['files'][0]['repositories'][0]['Options'], [signed_by])
                        self.assertEqual(len(row['Options']), 2)  # input untouched

    def test_simulated_capture_unrelated_state_edits_abort_before_next_mutation(self):
        for field in ('Enabled', 'Signed-By', 'option-added', 'URIs', 'Suites', 'Components'):
            with self.subTest(field=field):
                self.setUp()
                self.repositories = self.simulated_enterprise_capture()
                target = self.repositories['files'][0]['repositories'][0]
                unrelated = self.repositories['files'][2]['repositories'][0]

                def external_edit():
                    target['Options'].append({'Key': 'Enabled', 'Values': ['false']})
                    if field == 'Enabled':
                        unrelated['Enabled'] = 0
                        unrelated['Options'].append({'Key': 'Enabled', 'Values': ['false']})
                    elif field == 'Signed-By':
                        unrelated['Options'][0]['Values'] = ['/external/keyring.gpg']
                    elif field == 'option-added':
                        unrelated['Options'].append({'Key': 'Trusted', 'Values': ['yes']})
                    else:
                        unrelated[field].append('external-edit')
                    self.repositories['digest'] = 'external-edit'

                self.after_write = external_edit
                with self.assertRaisesRegex(ValueError, 'partial.*unknown'):
                    self.run_policy(apply=True)
                self.assertEqual(self.writes, 1)
                self.assertTrue(self.repositories['files'][1]['repositories'][0]['Enabled'])
                self.assertFalse(any(c[1] == 'set' for c in self.calls))

    def test_simulated_capture_conflicting_readback_stops_after_first_write(self):
        for mode in ('conflicting-option', 'malformed-option', 'reenabled-target'):
            with self.subTest(mode=mode):
                self.setUp()
                self.repositories = self.simulated_enterprise_capture()
                target = self.repositories['files'][0]['repositories'][0]

                def external_edit():
                    value = 'unknown' if mode == 'malformed-option' else 'true'
                    if mode == 'reenabled-target':
                        target['Enabled'] = 1
                    target['Options'].append({'Key': 'Enabled', 'Values': [value]})

                self.after_write = external_edit
                with self.assertRaisesRegex(ValueError, 'partial.*unknown') as error:
                    self.run_policy(apply=True)
                self.assertNotIn('no repository changed', str(error.exception))
                self.assertEqual(self.writes, 1)
                self.assertTrue(self.repositories['files'][1]['repositories'][0]['Enabled'])
                self.assertFalse(any(c[1] == 'set' for c in self.calls))

    def test_synthetic_pve8_list_inventory_supports_boolean_and_integer_enabled(self):
        for integer in (False, True):
            with self.subTest(integer=integer):
                self.setUp()
                self.repositories = fixture(
                    ('/etc/apt/sources.list.d/enterprise.list', [repo('pve-enterprise', suite='bookworm')]),
                    ('/etc/apt/sources.list', [repo('main', uri='https://deb.example/debian', suite='bookworm')]),
                )
                for file in self.repositories['files']:
                    file['file-type'] = 'list'
                    for row in file['repositories']:
                        row['FileType'] = 'list'
                        row['Enabled'] = 1 if integer else True
                def serialize():
                    for file in self.repositories['files']:
                        for row in file['repositories']:
                            if integer:
                                row['Enabled'] = int(row['Enabled'])
                            # Synthetic standard handle adds the requested suite.
                            if row['Components'] == ['pve-no-subscription']:
                                row['Suites'] = ['bookworm']
                self.after_write = serialize
                self.assertEqual(self.run_policy(suite='bookworm'), 'offer')
                self.assertEqual(self.writes, 0)
                self.assertEqual(self.run_policy(apply=True, suite='bookworm'), 'changed')
                self.assertEqual(self.writes, 2)

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

    def test_expired_subscription_offers_switch_then_applies_with_consent(self):
        self.subscription = 'key: FIXTURE-SECRET\nstatus: expired\nserverid: FIXTURE-SECRET\n'
        before = json.dumps(self.repositories)
        self.assertEqual(self.run_policy(), 'offer')
        self.assertEqual(json.dumps(self.repositories), before)
        self.assertEqual(self.writes, 0)
        self.assertEqual([c[:2] for c in self.calls],
                         [['pvesh', 'get'], ['pvesubscription', 'get']])
        self.assertEqual(self.run_policy(apply=True), 'changed')
        self.assertEqual(self.writes, 2)

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

    def test_existing_public_or_test_preserved_without_subscription_lookup(self):
        # Synthetic inventory only: this does not model real pvesh serialization.
        for channel in ('pve-no-subscription', 'pve-test', 'pvetest'):
            for subscription in ('active', 'notfound', 'expired', 'new', 'suspended',
                                 'invalid', 'unknown', RuntimeError('lookup failed')):
                for apply in (False, True):
                    with self.subTest(channel=channel, subscription=subscription, apply=apply):
                        self.setUp()
                        self.subscription = (subscription if isinstance(subscription, Exception)
                                             else f'status: {subscription}\n')
                        self.repositories['files'][0]['repositories'].append(repo(channel))
                        before = json.dumps(self.repositories)
                        self.assertEqual(self.run_policy(apply=apply), 'preserve')
                        self.assertEqual(json.dumps(self.repositories), before)
                        self.assertEqual(self.writes, 0)
                        self.assertEqual([c[:2] for c in self.calls], [['pvesh', 'get']])

    def test_invalid_inventory_stops_before_subscription_lookup(self):
        self.repositories['errors'] = [{'error': 'fixture parse failure'}]
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.run_policy(apply=True)
        self.assertEqual([c[:2] for c in self.calls], [['pvesh', 'get']])
        self.assertEqual(self.writes, 0)

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
        for response in ('status: unknown\n', 'status: invalid\n', 'status: new\n',
                         'status: suspended\n', 'status: active\nstatus: notfound\n',
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
    def test_expired_and_notfound_consent_use_real_policy_with_synthetic_api(self):
        helper = ROOT / 'scripts/global/repository-functions.sh'
        # The runner replaces every API command; bool Enabled is synthetic and
        # deliberately does not claim to reproduce the maintainer's JSON.
        runner_source = f'''import importlib.util
import json
import os
from pathlib import Path
spec = importlib.util.spec_from_file_location('policy', {str(POLICY)!r})
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
root = Path(os.environ['TEST_ROOT'])
state_path = root / 'inventory.json'
state = json.loads(state_path.read_text())
def run(args):
    verb = args[:2]
    with (root / 'calls').open('a') as log:
        log.write(' '.join(verb) + '\\n')
    if verb == ['pvesubscription', 'get']:
        return 'key: FIXTURE-SECRET\\nstatus: ' + os.environ['STATUS'] + '\\n'
    if verb == ['pvesh', 'get']:
        return json.dumps(state)
    if verb == ['pvesh', 'create']:
        path = args[args.index('--path') + 1]
        index = int(args[args.index('--index') + 1])
        next(f for f in state['files'] if f['path'] == path)['repositories'][index]['Enabled'] = False
    elif verb == ['pvesh', 'set']:
        row = dict(state['files'][0]['repositories'][0])
        row['Enabled'] = True
        row['Components'] = ['pve-no-subscription']
        state['files'].append({{'path': '/etc/apt/sources.list.d/public.sources', 'repositories': [row]}})
    else:
        raise AssertionError('Unexpected fixture API command')
    state['digest'] += '-write'
    state_path.write_text(json.dumps(state))
    return ''
policy.run = run
raise SystemExit(policy.main())
'''
        for status, consent, refresh_rc in (('expired', False, 0), ('expired', True, 0),
                                            ('expired', True, 100), ('notfound', False, 0),
                                            ('notfound', True, 0)):
            with self.subTest(status=status, consent=consent, refresh_rc=refresh_rc):
                with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as d:
                    root = Path(d)
                    runner = root / 'fixture_policy.py'
                    runner.write_text(runner_source)
                    state_path = root / 'inventory.json'
                    state_path.write_text(json.dumps(fixture(
                        ('/etc/apt/sources.list.d/operator.sources', [repo('pve-enterprise')]),
                        ('/etc/apt/sources.list.d/base.sources', [repo('main')]))))
                    before = state_path.read_bytes()
                    script = f'''source "{helper}"
                        pveversion() {{ echo pve-manager/9.0; }}
                        translate() {{ printf %s "$1"; }}
                        msg_error() {{ printf '%s\\n' "$1" >&2; }}
                        is_web_mode() {{ return 0; }}
                        hybrid_yesno() {{ printf 'prompt\\n' >> "$TEST_ROOT/calls";
                            printf '%s\\n' "$2" >&2; {'return 0' if consent else 'return 1'}; }}
                        repository_policy() {{ python3 "{runner}" "$@"; }}
                        apt-get() {{ printf 'apt %s\\n' "$*" >> "$TEST_ROOT/calls"; return {refresh_rc}; }}
                        if ensure_repositories; then printf 'consumer\\n' >> "$TEST_ROOT/calls"; exit 0;
                        else exit $?; fi
                    '''
                    result = subprocess.run(['bash', '-c', script], input='', text=True,
                                            capture_output=True, timeout=15,
                                            env=dict(os.environ, TEST_ROOT=d, STATUS=status))
                    calls = (root / 'calls').read_text().splitlines()
                    self.assertEqual(calls[:3], ['pvesh get', 'pvesubscription get', 'prompt'])
                    self.assertIn('no active subscription', result.stderr)
                    self.assertNotIn('FIXTURE-SECRET', result.stdout + result.stderr)
                    if not consent:
                        self.assertEqual(calls, ['pvesh get', 'pvesubscription get', 'prompt'])
                        self.assertEqual(state_path.read_bytes(), before)
                        self.assertNotEqual(result.returncode, 0)
                    else:
                        self.assertEqual(calls[3:10], ['pvesh get', 'pvesubscription get',
                            'pvesh create', 'pvesh get', 'pvesh set', 'pvesh get', 'apt update'])
                        state = json.loads(state_path.read_text())
                        self.assertFalse(state['files'][0]['repositories'][0]['Enabled'])
                        self.assertEqual(state['files'][-1]['repositories'][0]['Components'],
                                         ['pve-no-subscription'])
                        self.assertEqual(result.returncode, refresh_rc)
                        if refresh_rc:
                            self.assertNotIn('consumer', calls)
                            self.assertIn('sources changed, but APT', result.stderr)
                        else:
                            self.assertEqual(calls[-1], 'consumer')

    def test_refresh_only_after_changed_apply_and_failure_stops_consumer(self):
        helper = ROOT / 'scripts/global/repository-functions.sh'
        for plan, apply, refresh_rc in (('offer', 'changed', 0), ('offer', 'changed', 100),
                                       ('offer', 'preserve', 0), ('preserve', 'changed', 0),
                                       ('offer', 'unexpected', 0), ('offer', 'failed', 0)):
            for pipefail in (False, True):
                with self.subTest(plan=plan, apply=apply, refresh_rc=refresh_rc, pipefail=pipefail):
                    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as d:
                        log = Path(d) / 'calls'
                        script = f'''source "{helper}"
                            set -e; set {'-o' if pipefail else '+o'} pipefail
                            pveversion() {{ echo pve-manager/9.0; }}
                            translate() {{ printf %s "$1"; }}
                            msg_error() {{ printf '%s\\n' "$1" >&2; }}
                            is_web_mode() {{ return 0; }}
                            hybrid_yesno() {{ printf 'prompt\\n' >> "{log}"; }}
                            repository_policy() {{
                                printf '%s\\n' "$1" >> "{log}"
                                if [[ "$1" == plan ]]; then echo {plan};
                                elif [[ {apply} == failed ]]; then return 1;
                                else echo {apply}; fi
                            }}
                            apt-get() {{ printf 'apt %s\\n' "$*" >> "{log}"; return {refresh_rc}; }}
                            # Exercise the conditional context used by most callers:
                            # inherited errexit cannot be relied on inside the helper.
                            if ensure_repositories; then
                                printf 'consumer\\n' >> "{log}"; exit 0
                            else exit $?; fi
                        '''
                        result = subprocess.run(['bash', '-c', script], input='', text=True,
                                                capture_output=True, timeout=15)
                        calls = log.read_text().splitlines()
                        expected = ['plan']
                        if plan == 'offer':
                            expected += ['prompt', 'apply']
                            if apply == 'changed':
                                expected += ['apt update']
                        success = (plan == 'preserve' or apply in ('changed', 'preserve')) and refresh_rc == 0
                        if success:
                            expected += ['consumer']
                        self.assertEqual(calls, expected)
                        self.assertEqual(result.returncode == 0, success, result.stderr)
                        if refresh_rc:
                            self.assertRegex(result.stderr, 'sources changed|repositories changed')
                            self.assertIn('APT', result.stderr)
                            self.assertNotIn('no APT source changed', result.stderr)
                            self.assertNotIn('success', result.stdout.lower())

    def test_web_consent_applies_only_after_prompt(self):
        helper = ROOT / 'scripts/global/repository-functions.sh'
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as d:
            log = Path(d) / 'calls'
            script = f'''source "{helper}"
                pveversion() {{ echo pve-manager/9.0; }}
                translate() {{ printf %s "$1"; }}
                msg_error() {{ :; }}
                is_web_mode() {{ return 0; }}
                hybrid_yesno() {{ printf 'prompt\\n' >> "{log}"; [[ "$2" == *'This host has no active subscription, switch to the no-subscription repository?'* ]]; }}
                repository_policy() {{ printf '%s\\n' "$1" >> "{log}"; [[ "$1" == plan ]] && echo offer || echo changed; }}
                apt-get() {{ printf 'apt %s\\n' "$*" >> "{log}"; }}
                ensure_repositories
            '''
            result = subprocess.run(['bash', '-c', script], input='', text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(log.read_text().splitlines(), ['plan', 'prompt', 'apply', 'apt update'])

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
                    apt-get() {{ printf 'apt %s\\n' "$*" >> "{log}"; }}
                    ensure_repositories
                    '''
                    result = subprocess.run(['bash', '-c', script], input='', text=True, capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(log.read_text(), 'plan\n')


if __name__ == '__main__':
    unittest.main()
