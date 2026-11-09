"""What the user changes in Proxmox on a stack member is kept by every stack."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))

import oci_instance_reconcile as reconcile
import oci_stack_modify as stack_modify
from oci_installation_state import sha

MARKER = '22222222-2222-2222-2222-222222222222'
BEFORE = (f'description: proxmenux-instance={MARKER}\narch: amd64\ncores: 2\nmemory: 6000\nswap: 512\n'
          'hostname: immich-server\nonboot: 1\n'
          'rootfs: local-lvm:vm-201-disk-0,size=8G\n'
          'mp0: local-lvm:vm-201-disk-1,mp=/data,size=16G,backup=1\n')


def member(adapter='install_immich_stack.sh', **deployment):
    plan = {'resources': {'cores': 2, 'memory_mb': 6000, 'swap_mb': 512}, 'hostname': 'immich-server',
            'onboot': True, 'rootfs': {'storage': 'local-lvm', 'size_gb': 8},
            'mounts': [{'type': 'managed-volume', 'container_path': '/data', 'source': 'local-lvm',
                        'size_gb': 16, 'backup': True, 'read_only': False}],
            'devices': [], 'replay_profile': {'adapter': adapter, 'role': 'application'}, **deployment}
    return {'vmid': 201, 'status': 'installed', 'installation_id': MARKER, 'stack_member': True,
            'deployment': plan, 'observed': {'config': BEFORE, 'config_sha256': sha(BEFORE.encode())}}


class AdoptSettingsTests(unittest.TestCase):
    def test_resources_hostname_and_disk_size_go_into_the_record(self):
        record = member()
        changed = (BEFORE.replace('memory: 6000', 'memory: 6140').replace('cores: 2', 'cores: 4')
                   .replace('hostname: immich-server', 'hostname: photos')
                   .replace('vm-201-disk-0,size=8G', 'vm-201-disk-0,size=12G')).encode()
        plan = copy.deepcopy(record['deployment'])
        reconcile.adopt_settings(record, changed, plan, owned=['mp0'])
        self.assertEqual(plan['resources'], {'cores': 4, 'memory_mb': 6140, 'swap_mb': 512})
        self.assertEqual(plan['hostname'], 'photos')
        self.assertEqual(plan['rootfs']['size_gb'], 12)

    def test_mounts_and_devices_are_left_to_the_caller(self):
        record = member()
        changed = (BEFORE.replace('size=16G', 'size=32G')
                   + 'dev0: /dev/dri/renderD128,gid=104\n').encode()
        plan = copy.deepcopy(record['deployment'])
        reconcile.adopt_settings(record, changed, plan, owned=['mp0', 'dev0'])
        self.assertEqual(plan['mounts'][0]['size_gb'], 16)
        self.assertEqual(plan['devices'], [])

    def test_a_change_no_container_can_keep_still_stops(self):
        record = member()
        with self.assertRaises(ValueError):
            reconcile.adopt_settings(record, BEFORE.replace('arch: amd64', 'arch: arm64').encode(),
                                     copy.deepcopy(record['deployment']), owned=['mp0'])


class StackAdoptTests(unittest.TestCase):
    def run_adopt(self, record, config):
        written, order = [], []
        with patch.object(stack_modify.instances, 'read', return_value=record), \
                patch.object(stack_modify.instances, 'command', return_value=config), \
                patch.object(stack_modify.instances, 'location', return_value=Path('/x/record.json')), \
                patch.object(stack_modify.instances, 'write',
                             side_effect=lambda path, value: (written.append(copy.deepcopy(value)), order.append('write'))), \
                patch.object(stack_modify, 'register', side_effect=lambda root, vmid: order.append('register')):
            stack_modify.adopt(Path('/x'), 201)
        return written, order

    def test_an_adapter_member_after_its_first_update_keeps_the_ram_the_user_set(self):
        # The Immich case: 6000 MB set at installation, 6140 MB set in Proxmox.
        written, order = self.run_adopt(member(), BEFORE.replace('memory: 6000', 'memory: 6140').encode())
        self.assertEqual(order, ['write', 'register'])
        self.assertEqual(written[0]['deployment']['resources']['memory_mb'], 6140)

    def test_an_adapter_member_before_its_first_update_is_read_from_its_native_config(self):
        record = member(native_config=BEFORE)
        written, order = self.run_adopt(record, BEFORE.replace('memory: 6000', 'memory: 6140').encode())
        self.assertEqual(order, ['register'])
        self.assertEqual(written, [])

    def test_a_variable_changed_in_proxmox_is_kept_on_an_adapter_member(self):
        record = member(environment=[{'name': 'TZ', 'value': 'UTC', 'sensitive': False}])
        record['observed']['config'] = BEFORE + 'lxc.environment.runtime: TZ=UTC\n'
        record['observed']['config_sha256'] = sha(record['observed']['config'].encode())
        written, _ = self.run_adopt(record, (BEFORE + 'lxc.environment.runtime: TZ=Europe/Madrid\n').encode())
        values = {item['name']: item['value'] for item in written[0]['deployment']['environment']}
        self.assertEqual(values['TZ'], 'Europe/Madrid')


if __name__ == '__main__':
    unittest.main()
