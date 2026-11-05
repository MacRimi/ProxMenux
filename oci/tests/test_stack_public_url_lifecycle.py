"""Public origins remain fixed desired state across native stack lifecycle APIs."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'remote'))
from proxmenux_oci.custom import template_from_compose
from proxmenux_oci.stack import build_stack, DefaultsUI
from proxmenux_oci.installer import DEFAULT_MODE
import install_generic_stack as runtime
import oci_instances as instances
import oci_instance_transaction as transactions
import oci_stack_plan as plans
import oci_stack_native as native
import oci_restore_recovery as recovery

SOURCE = '''services:
  web:
    image: nginx:alpine
    ports: ['9001:8080']
    environment: {PUBLIC_ORIGIN: 'http://localhost:9001/entry'}
    depends_on: [backend, secondary]
  backend:
    image: example/worker:latest
    environment: {PUBLIC_ORIGIN: 'http://localhost:9001/entry'}
  secondary:
    image: nginx:alpine
    ports: ['8025:80']
    environment: {PUBLIC_ORIGIN: 'http://localhost:8025/mail'}
'''
DIGEST = 'sha256:' + 'a' * 64


class StaticPublicURLLifecycle(unittest.TestCase):
    def publish(self, root):
        template = template_from_compose(SOURCE)
        with patch('proxmenux_oci.installer.ask_storage', return_value='local-zfs'), \
             patch('proxmenux_oci.installer.ask_bridge', return_value='vmbr909'), \
             patch('proxmenux_oci.host.timezone', return_value='UTC'), \
             patch('proxmenux_oci.network.ask_addresses', side_effect=lambda ui, bridge, labels:
                   ({name: ('172.30.249.91/24' if name == 'secondary' else '172.30.249.90/24')
                     for name in labels}, None)):
            deployment = build_stack(template, DefaultsUI(), DEFAULT_MODE)
        services = deployment['services']
        original = copy.deepcopy(services)
        runtime.prepare_public_environment(services)
        configs, observed = {}, {}
        for index, service in enumerate(services):
            vmid = 4900 + service['offset']
            service['vmid'] = vmid
            service['deployment']['vmid'] = vmid
            service['ip'] = f'10.77.5.{30 + service["offset"]}'
            runtime.assign_health_address(service)
            identity = str(uuid.uuid4())
            config = f'description: proxmenux-instance={identity}\nrootfs: local-zfs:subvol-{vmid}-disk-0,size=8G\n'
            configs[vmid] = config.encode()
            observed[vmid] = {'config': config, 'archive_path': '/fixture/image.tar',
                              'resolved_registry_digest': DIGEST,
                              'image': {'architecture': 'amd64', 'os': 'linux', 'defaults': {}}}
            # The installer must publish final runtime plans, not stale input snapshots.
            instances.write(instances.location(root, vmid), {
                'schema_version': 1, 'vmid': vmid, 'installation_id': identity,
                'status': 'assembling', 'template': copy.deepcopy(service['template']),
                'deployment': copy.deepcopy(original[index]['deployment']),
                'observed': copy.deepcopy(observed[vmid])})
        contract = {'schema': 1, 'stack': 'public-url-fixture', 'dependencies': [
            {'vmid': s['vmid'], 'label': s['name'], 'healthcheck': copy.deepcopy(s['healthcheck'])}
            for s in services if not s['main']]}
        with patch.object(instances, 'command', side_effect=lambda *args: configs[int(args[-1])]), \
             patch.object(instances, 'observe', side_effect=lambda vmid, *args: copy.deepcopy(observed[vmid])):
            instances.publish_stack(root, 4900, template, deployment, services)
        return contract, {s['name']: s['vmid'] for s in services}

    def assert_origins(self, records, names):
        for name, vmid in names.items():
            values = {item['name']: item['value'] for item in records[vmid]['deployment']['environment']}
            self.assertEqual(values['PUBLIC_ORIGIN'], 'http://172.30.249.91:80/mail'
                             if name == 'secondary' else 'http://172.30.249.90:8080/entry')
            self.assertNotIn('@STACK_LAN_IP@', json.dumps(records[vmid]['deployment']))
            self.assertNotIn('localhost', values['PUBLIC_ORIGIN'])

    def test_published_static_origins_survive_native_update_contract_and_private_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract, names = self.publish(root)
            records = {vmid: instances.read(root, vmid) for vmid in names.values()}
            self.assert_origins(records, names)
            plan = plans.build(records[4900], records,
                               {v: r['installation_id'] for v, r in records.items()}, 'update')
            adapter = native.NativeAdapter(root, root / 'journal.json', plan)
            candidates = {r['vmid']: transactions.candidate_contract(r, 'update') for r in plan['members']}
            self.assert_origins(candidates, names)
            expected = [{'vmid': s['vmid'], 'label': s['name'], 'healthcheck': s['healthcheck']}
                        for s in adapter.services.values() if s['vmid'] != 4900]
            self.assertEqual(expected, contract['dependencies'])
            secondary = next(s for s in adapter.services.values() if s['name'] == 'secondary')
            self.assertTrue(secondary['healthcheck']['url'].startswith('http://10.77.5.'))
            self.assertTrue(recovery.valid_contract(contract, set(names.values()) - {4900}))

    def test_restore_refresh_adopts_storage_without_reinferring_url_or_lan_healthchecks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract, names = self.publish(root)
            for vmid in names.values():
                record = instances.read(root, vmid)
                record['deployment']['rootfs']['storage'] = 'restored-zfs'
                record['recovered_at'] = instances.now()
                instances.write(instances.location(root, vmid), record)
            recovery.refresh_service_plans(root, list(names.values()))
            records = {v: instances.read(root, v) for v in names.values()}
            self.assert_origins(records, names)
            primary = records[4900]
            for service in primary['stack']['deployment']['services']:
                self.assertEqual(service['deployment'], records[service['vmid']]['deployment'])
                self.assertEqual(service['deployment']['rootfs']['storage'], 'restored-zfs')
            expected = [{'vmid': s['vmid'], 'label': s['name'], 'healthcheck': s['healthcheck']}
                        for s in primary['stack']['deployment']['services'] if s['vmid'] != 4900]
            self.assertEqual(expected, contract['dependencies'])
            self.assertTrue(recovery.valid_contract(contract, set(names.values()) - {4900}))


if __name__ == '__main__':
    unittest.main()
