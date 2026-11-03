"""The publisher contract survives native catalog composition and both wizards."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'remote'), str(ROOT / 'tests')]
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.custom import template_from_oci_compose
from proxmenux_oci.installer import build_deployment, DEFAULT_MODE, ADVANCED_MODE
from test_advanced_flow_order import RecordingUI, storages, addresses


class AirDCppRecipeTests(unittest.TestCase):
    def test_import_roundtrip_keeps_udp_and_all_persistent_paths(self):
        catalog = Catalog(ROOT)
        template = catalog.compose('airdcpp-webclient')
        restored = template_from_oci_compose(json.dumps(template))
        catalog.validate(restored)
        ports = {(p['container_port'], p['protocol']) for p in restored['container_contract']['ports']}
        self.assertEqual(ports, {(5600,'tcp'),(5601,'tcp'),(21248,'tcp'),(21248,'udp'),(21249,'tcp')})
        paths = {v['container_path']:v for v in restored['container_contract']['volumes']}
        self.assertEqual(set(paths), {'/.airdcpp','/Downloads','/Share'})
        self.assertEqual(paths['/.airdcpp']['installation_choice'], ['managed-volume'])
        for path in ('/Downloads','/Share'):
            self.assertIn('host-bind', paths[path]['installation_choice'])
        self.assertEqual(restored['catalog_ui']['architectures'], ['amd64'])
        self.assertEqual(restored['proxmox']['image_metadata_policy']['entrypoint'], 'import-from-oci-image')

    def test_wizards_preserve_managed_configuration_and_use_selected_shared_directories(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for target, value in [
                ('proxmenux_oci.installer.host.storages', storages),
                ('proxmenux_oci.installer.access.ask_addresses', addresses)]:
                stack.enter_context(patch(target, side_effect=value))
            stack.enter_context(patch('proxmenux_oci.i18n.language', return_value='en'))
            stack.enter_context(patch('proxmenux_oci.installer.host.bridges',return_value=[{'iface':'vmbr0','cidr':'192.0.2.10/24'}]))
            stack.enter_context(patch('proxmenux_oci.installer.host.timezone',return_value='Europe/Madrid'))
            stack.enter_context(patch('proxmenux_oci.installer.host.gpus',return_value={'intel':[],'amd':[],'nvidia':False}))
            stack.enter_context(patch('proxmenux_oci.installer.access.ask_ipv4',return_value=('dhcp',None)))
            for mode in (DEFAULT_MODE, ADVANCED_MODE):
                with self.subTest(mode=mode):
                    ui = RecordingUI({'Where to store /Downloads':'host-bind','Where to store /Share':'host-bind'})
                    plan = build_deployment(Catalog(ROOT).compose('airdcpp-webclient'), ui, mode)
                    mounts = {item['container_path']:item for item in plan['mounts']}
                    self.assertEqual(mounts['/.airdcpp']['type'], 'managed-volume')
                    self.assertTrue(mounts['/.airdcpp']['backup'])
                    self.assertEqual(mounts['/Downloads']['type'], 'host-bind')
                    self.assertEqual(mounts['/Share']['type'], 'host-bind')
                    env = {item['name']:item['value'] for item in plan['environment']}
                    self.assertEqual((env['PUID'],env['PGID']),('1000','1000'))
                    self.assertEqual(plan['resources']['cores'],2)
                    self.assertTrue(plan['security']['unprivileged'])


if __name__ == '__main__':
    unittest.main()
