"""Fixture-only PBS policy checks: never call host proxmox-backup-* tools or edit host APT sources."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'scripts/global/repository_policy.py'


def repo(components, *, uri='https://enterprise.proxmox.com/debian/pbs', suite='trixie', enabled=True):
    return {'Types': ['deb'], 'URIs': [uri], 'Suites': [suite],
            'Components': components.split(), 'Enabled': enabled}


class PBSRepositoryPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('repository_policy', POLICY)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.calls = []
        self.status = 'notfound'
        self.repositories = {
            'files': [
                {'path': '/etc/apt/sources.list.d/pbs-enterprise.sources', 'repositories': [repo('pbs-enterprise')]},
                {'path': '/etc/apt/sources.list.d/debian.sources',
                 'repositories': [repo('main contrib', uri='http://deb.debian.org/debian')]},
            ],
            'errors': [], 'digest': 'fixture-digest',
            'standard-repos': [{'handle': 'enterprise'}, {'handle': 'no-subscription'}, {'handle': 'test'}],
        }

    def run_policy(self, apply=False):
        def run(args):
            self.calls.append(args)
            if args[:3] == ['proxmox-backup-manager', 'subscription', 'get']:
                return json.dumps({'status': self.status, 'serverid': 'FIXTURE-SECRET'})
            self.assertEqual(args[:2], ['proxmox-backup-debug', 'api'])
            action = args[2]
            if action == 'get':
                return json.dumps(self.repositories)
            self.assertEqual(args[args.index('--digest') + 1], self.repositories['digest'])
            if action == 'create':
                path = args[args.index('--path') + 1]
                index = int(args[args.index('--index') + 1])
                next(f for f in self.repositories['files'] if f['path'] == path)['repositories'][index]['Enabled'] = False
            elif action == 'set':
                self.repositories['files'].append({'path': '/etc/apt/sources.list.d/proxmox.sources',
                                                   'repositories': [repo('pbs-no-subscription', uri='http://download.proxmox.com/debian/pbs')]})
            self.repositories['digest'] += '+'
            return ''
        with patch.object(self.module, 'run', side_effect=run):
            return self.module.evaluate('trixie', apply=apply, product='pbs')

    def writes(self):
        return [c for c in self.calls if c[:2] == ['proxmox-backup-debug', 'api'] and c[2] in ('create', 'set')]

    def test_fresh_pbs_offers_switch_without_writing(self):
        self.assertEqual(self.run_policy(), 'offer')
        self.assertEqual(self.writes(), [])
        self.assertFalse(any(c[0] in ('pvesh', 'pvesubscription') for c in self.calls))

    def test_consented_switch_disables_pbs_enterprise_then_adds_no_subscription(self):
        self.assertEqual(self.run_policy(apply=True), 'changed')
        writes = self.writes()
        self.assertEqual([c[2] for c in writes], ['create', 'set'])
        self.assertEqual(writes[0][writes[0].index('--path') + 1], '/etc/apt/sources.list.d/pbs-enterprise.sources')
        self.assertEqual(writes[0][writes[0].index('--enabled') + 1], '0')
        self.assertEqual(writes[1][writes[1].index('--handle') + 1], 'no-subscription')

    def test_active_subscription_preserves_enterprise(self):
        self.status = 'active'
        self.assertEqual(self.run_policy(apply=True), 'preserve')
        self.assertEqual(self.writes(), [])

    def test_existing_no_subscription_is_preserved_without_lookup(self):
        self.repositories['files'][0]['repositories'] = [repo('pbs-no-subscription')]
        self.assertEqual(self.run_policy(apply=True), 'preserve')
        self.assertFalse(any(c[0] == 'proxmox-backup-manager' for c in self.calls))

    def test_unrecognized_subscription_status_cannot_mutate(self):
        self.status = 'invalid'
        with self.assertRaisesRegex(ValueError, 'proxmox-backup-manager'):
            self.run_policy(apply=True)
        self.assertEqual(self.writes(), [])

    def test_pve_channels_do_not_count_as_pbs_sources(self):
        self.repositories['files'][0]['repositories'] = [repo('pve-no-subscription')]
        self.assertEqual(self.run_policy(), 'offer')

    def test_wrong_suite_points_to_pbs_interface(self):
        self.repositories['files'][0]['repositories'] = [repo('pbs-enterprise', suite='bookworm')]
        with self.assertRaisesRegex(ValueError, 'Administration > Repositories'):
            self.run_policy()
        self.assertEqual(self.writes(), [])


if __name__ == '__main__':
    unittest.main()
