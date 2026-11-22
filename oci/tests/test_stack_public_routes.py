"""Managed routes cannot configure an unowned guest or the host namespace."""
import copy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))
import oci_stack_public_routes as routes

OWNER = '11111111-1111-4111-8111-111111111111'
PRIMARY = '22222222-2222-4222-8222-222222222222'
MAC = '02:11:22:33:44:55'


def fixture():
    return {'stack_public_routes': {'schema': 1, 'stack_id': PRIMARY, 'primary_vmid': 4900,
        'vmid': 4901, 'installation_id': OWNER, 'private_bridge': 'vmbr15',
        'private_address': '10.77.5.31/24', 'routes': [
            {'destination': '172.30.249.90', 'via': '10.77.5.30',
             'target_vmid': 4900, 'target_installation_id': PRIMARY}]}}


class PublicRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in {'DIRECTORY': root/'owned', 'HELPER': root/'helper.py',
                           'CONFIGS': root/'configs', 'ROOT_UID': os.getuid()}.items():
            self.stack.enter_context(patch.object(routes, key, value))
        routes.CONFIGS.mkdir()
        routes.HELPER.write_text(Path(routes.__file__).read_text())
        routes.HELPER.chmod(0o644)
        self.deployment = fixture()
        self.spec = self.deployment['stack_public_routes']

    def config(self, vmid, identity, private, public=None, mac=MAC):
        text = f'# proxmenux-instance={identity}\nnet0: name=eth0,bridge=vmbr15,ip={private},hwaddr={mac}\n'
        if public:
            text += f'net1: name=eth1,bridge=vmbr909,ip={public}\n'
        if vmid == 4901:
            text += f'lxc.include: {routes.include_path(vmid)}\n'
        path = routes.CONFIGS/f'{vmid}.conf'
        path.write_text(text)
        path.chmod(0o600)
        return text

    def install(self):
        return routes.install(self.deployment, 4901, OWNER)

    def test_install_check_canonical_include_and_root_owned_contract(self):
        line = self.install()
        self.assertEqual(line, f'lxc.include: {routes.include_path(4901)}')
        self.assertNotIn('lxc.hook.version', routes.include_path(4901).read_text())
        self.assertIn(' -I ', routes.include_content())
        self.assertEqual(routes.check(line, self.deployment, 4901, OWNER), self.spec)
        self.assertEqual(routes.contract_path(4901).stat().st_mode & 0o777, 0o600)
        self.assertEqual(routes.HELPER.stat().st_mode & 0o777, 0o644)

    def test_restore_can_validate_without_assets_but_not_a_foreign_include(self):
        line = f'lxc.include: {routes.include_path(4901)}\n'
        self.assertEqual(routes.check(line, self.deployment, 4901, OWNER, require_host_assets=False), self.spec)
        with self.assertRaises(routes.RouteError):
            routes.check(line.replace('4901.conf','4902.conf'), self.deployment, 4901, OWNER, require_host_assets=False)
        self.assertEqual(routes.renumber_line(line.encode(),4901,5901), f'lxc.include: {routes.include_path(5901)}\n'.encode())

    def test_reused_vmid_cannot_remove_another_installation_contract(self):
        self.install()
        with self.assertRaises(routes.RouteError):routes.remove(4901, PRIMARY)
        self.assertTrue(routes.contract_path(4901).exists())
        self.assertTrue(routes.remove(4901, OWNER))
        self.assertFalse(routes.include_path(4901).exists())

    def test_bad_identity_and_unsafe_routes_fail_before_commands(self):
        changes = [lambda s:s.update(vmid=4902), lambda s:s.update(installation_id=PRIMARY),
                   lambda s:s['routes'][0].update(destination='0.0.0.0/0'),
                   lambda s:s['routes'][0].update(destination='127.0.0.1'),
                   lambda s:s['routes'][0].update(via='172.30.249.1'),
                   lambda s:s['routes'][0].update(destination=True),
                   lambda s:s['routes'].append(copy.deepcopy(s['routes'][0]))]
        with patch.object(routes.subprocess,'run') as run:
            for change in changes:
                value=copy.deepcopy(self.deployment);change(value['stack_public_routes'])
                with self.subTest(value=value),self.assertRaises(routes.RouteError):routes.validate(value,4901,OWNER)
            run.assert_not_called()

    def test_symlink_and_unsafe_helper_fail_closed(self):
        routes.DIRECTORY.mkdir()
        target=Path(self.temp.name)/'other';target.write_text('do not touch')
        routes.include_path(4901).symlink_to(target)
        with self.assertRaises(routes.RouteError):self.install()
        self.assertEqual(target.read_text(),'do not touch')
        routes.include_path(4901).unlink()
        routes.HELPER.chmod(0o666)
        with self.assertRaises(routes.RouteError):self.install()

    def test_symlink_directory_and_foreign_file_owner_are_rejected(self):
        outside=Path(self.temp.name)/'outside';outside.mkdir()
        routes.DIRECTORY.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(routes.RouteError):self.install()
        unsafe=SimpleNamespace(lstat=lambda:SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=routes.ROOT_UID+1,st_size=10))
        with self.assertRaises(routes.RouteError):routes._read(unsafe)

    def test_live_identity_and_frontend_addresses_are_verified(self):
        self.install()
        self.config(4901,OWNER,'10.77.5.31/24')
        self.config(4900,PRIMARY,'10.77.5.30/24','172.30.249.90/24')
        self.assertEqual(routes.live_contract(self.spec),MAC)
        self.config(4900,OWNER,'10.77.5.30/24','172.30.249.90/24')
        with self.assertRaises(routes.RouteError):routes.live_contract(self.spec)
        self.config(4900,PRIMARY,'10.77.5.30/24','172.30.249.91/24')
        with self.assertRaises(routes.RouteError):routes.live_contract(self.spec)

    def test_tampered_or_world_writable_contract_is_rejected(self):
        self.install();routes.contract_path(4901).chmod(0o666)
        with self.assertRaises(routes.RouteError):routes.check(f'lxc.include: {routes.include_path(4901)}',self.deployment,4901,OWNER)

    def test_namespace_is_a_net_namespace_and_never_the_host(self):
        with patch.object(routes.os,'open',return_value=17),patch.object(routes.os,'close') as close, \
             patch.object(routes.fcntl,'ioctl',return_value=routes.CLONE_NEWNET), \
             patch.object(routes.os,'fstat',return_value=SimpleNamespace(st_dev=1,st_ino=9)), \
             patch.object(routes.os,'stat',return_value=SimpleNamespace(st_dev=1,st_ino=9)):
            with self.assertRaisesRegex(routes.RouteError,'host network'):routes.namespace_fd('/proc/123/fd/4')
            close.assert_called_once_with(17)
        with patch.object(routes.os,'open',return_value=17),patch.object(routes.os,'close'), \
             patch.object(routes.fcntl,'ioctl',return_value=0):
            with self.assertRaisesRegex(routes.RouteError,'not a network'):routes.namespace_fd('/proc/123/fd/4')
        with patch.object(routes.os,'open') as opened:
            for value in (None,'/proc/self/ns/net','/etc/passwd','/proc/123/ns/mnt'):
                with self.assertRaises(routes.RouteError):routes.namespace_fd(value)
            opened.assert_not_called()

    def test_routes_are_only_32_in_verified_namespace_with_no_shell(self):
        interface=[{'address':MAC,'addr_info':[{'family':'inet','local':'10.77.5.31','prefixlen':24}]}]
        with patch.object(routes,'_namespace_command',side_effect=[json.dumps(interface).encode(),b'']) as command:
            routes.apply(self.spec,17,MAC)
        self.assertEqual(command.call_args_list[0].args,(17,'-j','address','show','dev','eth0'))
        self.assertEqual(command.call_args.args,(17,'-4','route','replace','172.30.249.90/32','via','10.77.5.30','dev','eth0','src','10.77.5.31'))
        with patch.object(routes.subprocess,'run',return_value=SimpleNamespace(stdout=b'ok')) as run:
            routes._namespace_command(17,'-4','route','show')
        self.assertEqual(run.call_args.args[0][:3],[routes.NSENTER,'--net=/proc/self/fd/17','--'])
        self.assertEqual(run.call_args.kwargs['pass_fds'],(17,));self.assertNotIn('shell',run.call_args.kwargs)

    def test_engine_helper_can_change_normally_without_stale_snapshot_adoption(self):
        routes.HELPER.write_text('# trusted engine update, same stable path\n')
        self.install()
        self.assertEqual(routes.HELPER.read_text(),'# trusted engine update, same stable path\n')

    def test_namespace_with_wrong_owner_address_cannot_receive_routes(self):
        for value in ([], [{'address':'02:aa:bb:cc:dd:ee','addr_info':[{'family':'inet','local':'10.77.5.31','prefixlen':24}]}]):
            with patch.object(routes,'_namespace_command',return_value=json.dumps(value).encode()) as command:
                with self.assertRaises(routes.RouteError):routes.apply(self.spec,17,MAC)
            self.assertEqual(command.call_count,1)

    def test_ip_failure_propagates_so_startup_cannot_report_success(self):
        interface=[{'address':MAC,'addr_info':[{'family':'inet','local':'10.77.5.31','prefixlen':24}]}]
        with patch.object(routes,'_namespace_command',side_effect=[json.dumps(interface).encode(),subprocess.CalledProcessError(2,['ip'])]):
            with self.assertRaises(subprocess.CalledProcessError):routes.apply(self.spec,17,MAC)

    def test_start_uses_only_the_runtime_pid_namespace(self):
        self.install()
        with patch.dict(os.environ,{'LXC_NAME':'4901','LXC_PID':'12345'},clear=True), \
             patch.object(routes.os,'geteuid',return_value=0), \
             patch.object(routes,'live_contract',return_value=MAC), \
             patch.object(routes,'namespace_fd',return_value=17) as namespace, \
             patch.object(routes,'apply') as apply, patch.object(routes.os,'close') as close:
            routes.start()
        namespace.assert_called_once_with('/proc/12345/ns/net')
        apply.assert_called_once_with(self.spec,17,MAC)
        close.assert_called_once_with(17)

    def test_default_hook_arguments_must_match_owner_and_phase(self):
        with patch.dict(os.environ,{'LXC_NAME':'4901'},clear=True), \
             patch.object(routes.os,'geteuid',return_value=0),patch.object(routes,'start') as start:
            with patch.object(sys,'argv',['helper','start','4901','lxc','start-host']):routes.main()
            start.assert_called_once()
            start.reset_mock()
            with patch.object(sys,'argv',['helper','start','4902','lxc','start-host']), self.assertRaises(routes.RouteError):routes.main()
            with patch.object(sys,'argv',['helper','start','4901','lxc','post-stop']), self.assertRaises(routes.RouteError):routes.main()
            start.assert_not_called()

    def test_missing_lxc_pid_is_not_replaced_by_a_host_fallback(self):
        self.install()
        with patch.dict(os.environ,{'LXC_NAME':'4901'},clear=True),patch.object(routes.os,'geteuid',return_value=0),patch.object(routes,'live_contract',return_value=MAC),patch.object(routes,'apply') as apply:
            with self.assertRaises(routes.RouteError):routes.start()
            apply.assert_not_called()


if __name__=='__main__':unittest.main()
