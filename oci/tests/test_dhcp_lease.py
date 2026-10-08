"""The DHCP client of a container that restarted itself is started again."""
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
import oci_dhcp_lease as lease

NET = 'name=eth0,bridge=vmbr0,firewall=1,host-managed=1,hwaddr=BC:24:11:D5:0F:FD,type=veth'


class ManagedInterfaceTests(TestCase):
    def test_only_host_managed_interfaces_on_dhcp(self):
        config = (f'net0: {NET},ip=dhcp\n'
                  'net1: name=eth1,bridge=vmbr10,host-managed=1,ip=10.77.1.30/24,type=veth\n'
                  'net2: name=eth2,bridge=vmbr0,ip=dhcp,type=veth\n'
                  'net3: name=eth3,bridge=vmbr0,host-managed=1,ip=dhcp,ip6=dhcp,type=veth\n'
                  'net4: name=eth4,bridge=vmbr0,host-managed=1,ip=dhcp,link_down=1,type=veth\n')
        self.assertEqual(lease.managed(config), [('eth0', 4), ('eth3', 4), ('eth3', 6)])

    def test_snapshots_and_odd_names_are_ignored(self):
        config = ('net0: name=eth0;reboot,bridge=vmbr0,host-managed=1,ip=dhcp\n'
                  f'[before-update]\nnet1: {NET},ip=dhcp\n')
        self.assertEqual(lease.managed(config), [])


class RepairTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'conf').mkdir()
        (self.root / 'proc').mkdir()
        (self.root / 'conf/121.conf').write_text(f'net0: {NET},ip=dhcp\n')
        for item in (patch.object(lease, 'CONFIGS', self.root / 'conf'), patch.object(lease, 'PROC', self.root / 'proc'),
                     patch.object(lease, 'init_pid', return_value=53014)):
            item.start()
            self.addCleanup(item.stop)

    def client(self, pid, vmid):
        (self.root / f'proc/{pid}').mkdir()
        (self.root / f'proc/{pid}/cmdline').write_bytes(
            f'/sbin/dhclient\0-1\0-4\0-pf\0/var/lib/lxc/{vmid}/hook/dhclient4-eth0.pid\0eth0\0'.encode())

    def test_a_missing_client_is_started(self):
        self.client(1661, 115)
        with patch.object(lease, 'start_client', return_value=True) as start:
            self.assertEqual(lease.repair(121), [('eth0', 4)])
        start.assert_called_once_with(121, 'eth0', 4, 53014)

    def test_a_running_client_is_left_alone(self):
        self.client(42092, 121)
        with patch.object(lease, 'start_client') as start:
            self.assertEqual(lease.repair(121), [])
        start.assert_not_called()

    def test_a_stopped_or_unknown_container_is_left_alone(self):
        with patch.object(lease, 'start_client') as start:
            with patch.object(lease, 'init_pid', return_value=None):
                self.assertEqual(lease.repair(121), [])
            self.assertEqual(lease.repair(999), [])
        start.assert_not_called()

    def test_a_container_that_just_started_is_left_to_proxmox(self):
        with patch.object(lease, 'start_client', return_value=True) as start:
            with patch.object(lease, 'running_for', return_value=5.0):
                self.assertEqual(lease.repair(121, settle=lease.SETTLE), [])
            with patch.object(lease, 'running_for', return_value=3600.0):
                self.assertEqual(lease.repair(121, settle=lease.SETTLE), [('eth0', 4)])
        start.assert_called_once()

    def test_every_container_with_a_managed_interface_is_listed(self):
        (self.root / 'conf/109.conf').write_text('net0: name=eth0,bridge=vmbr0,ip=dhcp,type=veth\n')
        (self.root / 'conf/100.conf').write_text(f'net0: {NET},ip=dhcp\n')
        self.assertEqual(lease.containers(), [100, 121])

    def test_the_start_hook_queues_the_check(self):
        hook = (ROOT / 'remote/oci_console_mark.sh').read_text()
        self.assertIn('lease="${0%/*}/oci_dhcp_lease.py"', hook)
        self.assertIn('systemd-run --quiet --collect --on-active=20 /usr/bin/python3 "$lease" "$1"', hook)
        self.assertTrue(hook.rstrip().endswith('exit 0'))


if __name__ == '__main__':
    import unittest
    unittest.main()
