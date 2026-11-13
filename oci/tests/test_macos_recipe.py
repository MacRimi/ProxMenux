"""macOS remains a KVM guest inside an OCI LXC, with persistent virtual disks."""
import json
from pathlib import Path
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(Path(__file__).parent)]
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.custom import template_from_oci_compose
from proxmenux_oci.installer import build_deployment, DEFAULT_MODE, ADVANCED_MODE
from proxmenux_oci.ui import UserCancelled
from test_advanced_flow_order import RecordingUI, storages

class MacOSRecipeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog(ROOT, catalog_dir=ROOT / 'catalog')
        self.template = self.catalog.compose('macos')

    def plan(self, mode, answers=None):
        ui = RecordingUI(answers)
        with ExitStack() as stack:
            for name, kwargs in {
                'i18n.language': {'return_value': 'en'},
                'installer.host.storages': {'side_effect': storages},
                'installer.host.bridges': {'return_value': [{'iface': 'vmbr0'}]},
                'installer.host.timezone': {'return_value': 'UTC'},
                'installer.host.memory_total_mb': {'return_value': 32768},
                'installer.host.cpu_count': {'return_value': 8},
                'installer.access.ask_ipv4': {'return_value': ('dhcp', None)},
            }.items():stack.enter_context(patch('proxmenux_oci.'+name, **kwargs))
            return build_deployment(self.template, ui, mode)

    def test_roundtrip_preserves_virtualization_requirements_and_no_default_guest_login(self):
        t = template_from_oci_compose(json.dumps(self.template));self.catalog.validate(t)
        self.assertEqual(t['container_contract']['image']['repository'], 'dockurr/macos')
        self.assertEqual(t['proxmox']['image_metadata_policy']['entrypoint'], 'import-from-oci-image')
        self.assertEqual(t['proxmox']['installer_profile']['security']['required_capabilities'], ['NET_ADMIN'])
        self.assertEqual(t['first_run']['credentials'], [])
        self.assertEqual(t['catalog_ui']['architectures'], ['amd64'])
        self.assertFalse(t['proxmox'].get('security_profile', {}).get('requires_privileged_lxc'))

    def test_default_and_advanced_keep_guest_ram_below_lxc_limit_and_retain_storage(self):
        for mode in (DEFAULT_MODE, ADVANCED_MODE):
            with self.subTest(mode=mode):
                answers = {'Where to store /storage':'host-bind', 'Host path for /storage':'/srv/macos-test'} if mode==ADVANCED_MODE else {}
                plan = self.plan(mode, answers)
                env = {e['name']:e['value'] for e in plan['environment']}
                self.assertEqual((env['VERSION'],env['RAM_SIZE'],env['CPU_CORES'],env['DISK_SIZE']),('15','4G','2','64G'))
                self.assertEqual(plan['resources']['memory_mb'],6144)
                self.assertEqual({d['host_path'] for d in plan['devices']},{'/dev/kvm','/dev/net/tun'})
                self.assertEqual(plan['mounts'][0]['container_path'],'/storage')
                if mode==ADVANCED_MODE:
                    self.assertEqual(plan['mounts'][0]['type'],'host-bind')
                    self.assertEqual(plan['mounts'][0]['source'],'/srv/macos-test')
                else:
                    self.assertEqual(plan['mounts'][0]['size_gb'],128)
                    self.assertTrue(plan['mounts'][0]['backup'])

    def test_declining_required_kvm_cancels_instead_of_silently_emulating(self):
        with self.assertRaises(UserCancelled):
            self.plan(ADVANCED_MODE, {'Pass /dev/kvm to the LXC':False})
