"""An NVIDIA host as the Container Toolkit lists it: nvidia-modeset among the
nodes, and a DRM render node of its own next to the Intel one."""
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import test_plain_lxc as fixture  # noqa: F401  (sets the import paths)
import plain_lxc_resources as resources
from plain_lxc_spec import DEVICE_PATH

NODES = ['/dev/nvidia-modeset', '/dev/nvidia-uvm', '/dev/nvidia-uvm-tools', '/dev/nvidia0', '/dev/nvidiactl']
VENDORS = {'renderD128': '0x8086', 'renderD129': '0x10de'}


class NvidiaNodeTests(unittest.TestCase):
    def test_every_node_of_the_toolkit_is_an_accepted_device(self):
        for node in NODES:
            self.assertTrue(re.fullmatch(DEVICE_PATH, node), node)

    def test_the_native_bridge_accepts_the_same_nodes(self):
        bridge = (Path(resources.__file__).with_name('plain_lxc_pve.pl')).read_text()
        self.assertIn('nvidia(?:[0-9]+|ctl|-modeset|-uvm(?:-tools)?)', bridge)

    def test_the_nvidia_profile_is_offered_and_its_render_node_is_not_a_failure(self):
        def glob(path, pattern):
            if pattern == 'dev/dri/renderD*':
                return [Path('/dev/dri/renderD128'), Path('/dev/dri/renderD129')]
            return []

        def sysfs(path):
            return VENDORS.get(path.parent.parent.name, '') if path.name == 'vendor' else ''

        def identity(name, device=True):
            return {'dev': '7', 'ino': '1', 'rdev': '1', 'uid': 0, 'gid': 44, 'mode': 0o666}

        inventory = {'gpus': ['GPU-1, 00000000:02:00.0, 580.0'], 'toolkit_version': [],
                     'devices': {node: {} for node in NODES}, 'files': {}, 'links': {}}
        intel = {'vendor': '0x8086', 'pci_path': '/sys/devices/pci0000:00/0000:00:02.0'}
        with patch.object(Path, 'glob', glob), \
                patch.object(resources.shutil, 'which', side_effect=lambda name: None if name == 'lsusb' else '/usr/bin/' + name), \
                patch.object(resources.hardware, 'usb_devices', return_value=[]), \
                patch.object(resources.hardware, '_sysfs', side_effect=sysfs), \
                patch.object(resources.hardware, 'device_snapshot', return_value=intel), \
                patch.object(resources, 'nvidia_inventory', return_value=inventory), \
                patch.object(resources, 'nvidia_runtime', side_effect=lambda value: {'inventory': value}), \
                patch.object(resources, 'path_identity', side_effect=identity), \
                patch.object(resources, 'device_policy'):
            devices = resources.discover_devices()
            offered = resources.profiles(devices)
        self.assertEqual(devices.errors, [])
        self.assertNotIn('/dev/dri/renderD129', devices)
        self.assertEqual([d['path'] for d in offered['nvidia-runtime']['devices']], NODES)
        self.assertIn('intel-drm', {item['profile'] for item in offered.values()})


if __name__ == '__main__':
    unittest.main()
