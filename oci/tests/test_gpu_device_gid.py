"""Keep recorded LXC device-node GIDs distinct from host device ownership."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))

import oci_gpu_devices as devices
import oci_accelerators as accelerators


HOST = {
    'path': '/dev/dri/renderD128', 'major': 226, 'minor': 128,
    'uid': 0, 'gid': 993, 'mode': 0o660,
    'vendor': '0x8086', 'pci_path': '/sys/devices/pci0000:00/0000:00:02.0',
}
DEPLOYMENT = {'devices': [{
    'kind': 'character-device', 'host_path': '/dev/dri/renderD128',
    'container_path': '/dev/dri/renderD128', 'gid_strategy': 'host-device-gid',
    'mode': '0660', 'drm_vendor_ids': ['0x8086', '0x1002'],
}]}
SAVED_CONFIG = 'dev0: path=/dev/dri/renderD128,mode=0660,deny-write=0,gid=44\n'
CURRENT_CONFIG = SAVED_CONFIG.encode()


class ContainerDeviceGidTests(unittest.TestCase):
    @patch.object(devices, 'snapshot', return_value=HOST)
    def test_recorded_guest_gid_is_carried_to_update_and_still_checks_host_identity(self, _snapshot):
        record = {'deployment': {'devices': [dict(DEPLOYMENT['devices'][0])]},
                  'observed': {'config': SAVED_CONFIG}}
        candidate = {'deployment': {'devices': [dict(DEPLOYMENT['devices'][0])]}}

        devices.preserve_recorded_container_gids(record, candidate, CURRENT_CONFIG)

        self.assertEqual(record['deployment']['devices'][0]['container_gid'], 44)
        self.assertEqual(candidate['deployment']['devices'][0]['container_gid'], 44)
        self.assertEqual(devices.check(CURRENT_CONFIG, record['deployment'])['/dev/dri/renderD128'], HOST)
        self.assertEqual(devices.check(CURRENT_CONFIG, candidate['deployment'])['/dev/dri/renderD128'], HOST)

    @patch.object(devices, 'snapshot', return_value=HOST)
    def test_a_guest_gid_changed_in_proxmox_is_kept(self, _snapshot):
        record = {'deployment': {'devices': [dict(DEPLOYMENT['devices'][0], container_gid=44)]},
                  'observed': {'config': SAVED_CONFIG}}
        candidate = {'deployment': {'devices': [dict(DEPLOYMENT['devices'][0])]}}
        # Written from the Proxmox interface, without `path=`.
        changed = b'dev0: /dev/dri/renderD128,mode=0660,deny-write=0,gid=45\n'

        devices.preserve_recorded_container_gids(record, candidate, changed)

        self.assertEqual(record['deployment']['devices'][0]['container_gid'], 45)
        self.assertEqual(candidate['deployment']['devices'][0]['container_gid'], 45)
        self.assertEqual(devices.check(changed, candidate['deployment'])['/dev/dri/renderD128'], HOST)

    @patch.object(devices, 'snapshot', return_value=HOST)
    def test_other_permission_changes_are_still_refused(self, _snapshot):
        record = {'deployment': {'devices': [dict(DEPLOYMENT['devices'][0])]},
                  'observed': {'config': SAVED_CONFIG}}
        candidate = {'deployment': {'devices': [dict(DEPLOYMENT['devices'][0])]}}
        changed = CURRENT_CONFIG.replace(b'mode=0660', b'mode=0666')

        with self.assertRaisesRegex(ValueError, 'device settings changed'):
            devices.preserve_recorded_container_gids(record, candidate, changed)

    @patch.object(devices, 'snapshot', return_value=HOST)
    def test_host_gid_is_not_automatically_mapped_to_guest_gid_44(self, _snapshot):
        with self.assertRaisesRegex(ValueError, 'native GPU permissions were not kept'):
            devices.check(CURRENT_CONFIG, DEPLOYMENT)

        # Under Proxmox's default unprivileged map, guest GID 44 maps to host
        # GID 100044; host GID 993 is outside that map.
        self.assertEqual(100000 + 44, 100044)
        self.assertFalse(100000 <= 993 < 165536)

    @patch.object(devices, 'snapshot', return_value=HOST)
    def test_changed_host_device_identity_or_permissions_still_fail_baseline(self, snapshot):
        baseline = {'/dev/dri/renderD128': HOST}
        current = dict(HOST, gid=992)
        snapshot.return_value = current
        with self.assertRaisesRegex(ValueError, 'GPU identity or permissions changed'):
            accelerators.verify_baseline(baseline, DEPLOYMENT)

    def test_container_gid_must_be_a_bounded_integer(self):
        for invalid in (True, -1, 4294967295, '44'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'Invalid container device GID'):
                devices.container_gid({'gid_strategy': 'host-device-gid', 'container_gid': invalid}, HOST)


if __name__ == '__main__':
    unittest.main()
