"""An application's inner bridges must not hide its Proxmox-managed service IP."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'remote'))
import oci_instance_transaction as transaction

TEMPLATE={'proxmox':{'installer_profile':{'startup_healthcheck':{
    'scheme':'http','port':8006,'path':'/','timeout_seconds':1,'stability_seconds':0}}}}

class RecoveryManagedAddressTests(unittest.TestCase):
    def run_command(self,*args):
        self.calls.append(args)
        if args[:2]==('pct','config'):return b'net0: name=eth0,bridge=vmbr0,ip=dhcp\n'
        if args[:2]==('pct','status'):return b'status: running'
        if args[0]=='lxc-attach':return self.interface_addresses
        if args[0]=='lxc-info':return b'172.30.244.1\n172.30.244.254\n172.31.244.10\n'
        raise AssertionError(args)

    def test_recovery_probes_the_managed_interface_instead_of_the_first_inner_bridge(self):
        self.calls=[];self.interface_addresses=b'2: eth0 inet 172.31.244.10/24 scope global eth0\n'
        with patch.object(transaction,'run',side_effect=self.run_command),patch.object(transaction,'probe_http',return_value=(b'',0))as probe:
            self.assertEqual(transaction.healthcheck(9482,TEMPLATE),'http://172.31.244.10:8006/')
        self.assertEqual(probe.call_args.args[0][-1],'http://172.31.244.10:8006/')
        self.assertFalse(any(args[0]=='lxc-info'for args in self.calls))

    def test_a_managed_interface_without_an_address_waits_instead_of_falling_back_to_inner_bridges(self):
        self.calls=[];self.interface_addresses=b''
        with patch.object(transaction,'run',side_effect=self.run_command),patch.object(transaction,'probe_http')as probe,patch.object(transaction.time,'monotonic',side_effect=[0,0,0,2]),patch.object(transaction.time,'sleep'):
            with self.assertRaises(ValueError):transaction.healthcheck(9482,TEMPLATE)
        probe.assert_not_called()
        self.assertFalse(any(args[0]=='lxc-info'for args in self.calls))
