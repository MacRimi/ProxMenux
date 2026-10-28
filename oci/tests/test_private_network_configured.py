"""Down and pending bridge configs must reserve their names and IPv4 subnets."""
import importlib.util
import ipaddress
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
spec = importlib.util.spec_from_file_location('configured_private_network', ROOT / 'remote/allocate_private_network.py')
allocator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(allocator)


def deployment():
    return {'network': {'private_allocation':'automatic', 'private_subnet':'10.77.0.0/24',
                        'private_bridge':'vmbr10', 'private_host_address':'10.77.0.1/24'}}


class ConfiguredPrivateNetworkTests(unittest.TestCase):
    def test_interface_files_include_pending_main_and_include_fragments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'interfaces').write_text('auto vmbr0\n')
            (root/'interfaces.new').write_text('auto vmbr10\n')
            (root/'interfaces.d').mkdir()
            (root/'interfaces.d/down').write_text('iface vmbr11 inet static\n')
            (root/'interfaces.d/nested').mkdir()
            def fake_path(value):
                return root / Path(value).relative_to('/etc/network')
            with patch.object(allocator, 'Path', side_effect=fake_path):
                files = allocator._interface_files()
            self.assertEqual(set(files), {root/'interfaces',root/'interfaces.new',root/'interfaces.d/down'})

    def test_down_and_pending_subnets_are_occupied_even_with_different_bridge_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            down = root/'interfaces'
            down.write_text('iface vmbr999 inet static\n    address 10.77.0.1\n    netmask 255.255.255.0\n')
            pending = root/'interfaces.new'
            pending.write_text('auto vmbr11\niface vmbr11 inet static\n    address 10.77.1.1/24\n')
            with patch.object(allocator, '_interface_files', return_value=[down,pending]), \
                 patch.object(allocator, 'command_output', return_value=''), \
                 patch.object(allocator.Path, 'glob', return_value=[]):
                bridges = allocator.existing_bridges()
                occupied = allocator.existing_networks()
            self.assertIn('vmbr11', bridges)
            self.assertIn(ipaddress.ip_network('10.77.0.0/24'), occupied)
            self.assertIn(ipaddress.ip_network('10.77.1.0/24'), occupied)
            self.assertEqual(allocator.allocate_network(deployment(),bridges,occupied),
                             ('vmbr12',ipaddress.ip_network('10.77.2.0/24')))

    def test_pending_bridge_name_reserves_name_without_an_address(self):
        with tempfile.TemporaryDirectory() as directory:
            pending = Path(directory)/'interfaces.new'
            pending.write_text('auto vmbr0 vmbr10\niface vmbr10 inet manual\n')
            with patch.object(allocator, '_interface_files', return_value=[pending]), \
                 patch.object(allocator, 'command_output', return_value=''), \
                 patch.object(allocator.Path, 'glob', return_value=[]):
                bridges = allocator.existing_bridges()
            self.assertEqual(allocator.allocate_network(deployment(),bridges,[]),
                             ('vmbr11',ipaddress.ip_network('10.77.1.0/24')))

    def test_ipv6_and_invalid_addresses_do_not_reserve_ipv4_pool(self):
        text = ('iface vmbr12 inet6 static\n address fd00::1/64\n'
                'iface vmbr20 inet static\n address invalid\n'
                'iface vmbr21 inet static\n address 10.77.8.1/24 # comment\n')
        self.assertEqual(allocator._configured_networks(text), [ipaddress.ip_network('10.77.8.0/24')])


if __name__ == '__main__':
    unittest.main()
