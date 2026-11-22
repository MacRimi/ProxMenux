"""Internal TCP readiness survives initial install, native lifecycle and restore."""
import copy
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'remote'))
import install_generic_stack as installer
import oci_stack_native as native
import oci_restore_recovery as recovery


class TCPReadinessTests(unittest.TestCase):
    def test_initial_runtime_probe_uses_allocated_private_address(self):
        service={'ip':'10.77.20.31','healthcheck':{'type':'tcp','port':9998,'timeout_seconds':120}}
        installer.assign_health_address(service)
        self.assertEqual(service['healthcheck']['host'],'10.77.20.31')
        self.assertNotIn('url',service['healthcheck'])
        self.assertNotIn('frontend',service)

    def test_native_health_probes_real_socket_without_http(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1',0));server.listen()
            port=server.getsockname()[1]
            member={'vmid':4800,'deployment':{},'stack':{'deployment':{'services':[
                {'vmid':4800,'name':'helper','healthcheck':{'type':'tcp','host':'127.0.0.1','port':port,'timeout_seconds':5}}]}}}
            adapter=native.NativeAdapter(Path('/registry'),Path('/journal'),{'members':[member],'primary_vmid':4800})
            with patch.object(adapter,'is_running',return_value=True), \
                 patch.object(native.member_tx.gpu_devices,'validate_runtime'), \
                 patch.object(native.member_tx,'run') as run:
                adapter.healthcheck(4800)
            run.assert_not_called()

    def test_native_tcp_target_rejects_names_and_invalid_ports(self):
        for host,port in [('example.com',3000),('127.0.0.1',True),('127.0.0.1',0),('127.0.0.1',65536),('127.0.0.1','3000')]:
            with self.subTest(host=host,port=port),self.assertRaises(ValueError):
                native.tcp_target({'host':host,'port':port})

    def test_restore_retains_only_private_tcp_probes_with_valid_ports(self):
        contract={'schema':1,'dependencies':[{'vmid':4801,'label':'helper',
            'healthcheck':{'type':'tcp','host':'10.77.20.31','port':9998,'timeout_seconds':120}}]}
        self.assertTrue(recovery.valid_contract(contract,{4801}))
        for changes in ({'host':'192.168.1.1'},{'host':'localhost'},{'port':False},{'port':65536}):
            invalid=copy.deepcopy(contract);invalid['dependencies'][0]['healthcheck'].update(changes)
            self.assertFalse(recovery.valid_contract(invalid,{4801}))

    def test_hook_tcp_probe_checks_connection_not_http_status(self):
        text=(ROOT/'remote/stack_dependency_hook.sh').read_text()
        functions=text[text.index('dependency_is_healthy() {'):text.index('\nstart_dependencies()')]
        with socket.socket() as server:
            server.bind(('127.0.0.1',0));server.listen()
            port=server.getsockname()[1]
            command=functions+'\ndependency_is_healthy 4801 \'{"type":"tcp","host":"127.0.0.1","port":'+str(port)+'}\''
            result=subprocess.run(['bash','-c',command],text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
        failed=subprocess.run(['bash','-c',command],text=True,capture_output=True)
        self.assertNotEqual(failed.returncode,0)


if __name__=='__main__':unittest.main()
