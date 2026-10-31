"""Native runtime edits keep rootfs, defaults and secrets; failures roll back."""
import contextlib
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'remote'))
import oci_native_modify as native
import oci_instances as instances
import oci_update_current as update
import oci_operation_notice
from test_modify_image_reuse import record, CONFIG


class NativePlanTests(unittest.TestCase):
    def setUp(self):
        self.record = record()
        self.record['observed']['image']['defaults'] = {'Env': ['A=image-default']}
        self.record['deployment']['environment'] = [{'name': 'A', 'value': 'one'}]
        self.config = CONFIG+b'net0: name=eth0,bridge=vmbr0,ip=dhcp,hwaddr=AA:BB:CC:DD:EE:FF,tag=20,ip6=auto\n'
        self.candidate = copy.deepcopy(self.record)
        p = patch.object(native.transaction, 'preflight')
        self.preflight = p.start(); self.addCleanup(p.stop)

    def test_environment_preserves_image_defaults_and_other_runtime_values(self):
        self.candidate['deployment']['environment'] = [{'name': 'SECRET', 'value': "a' $x \" ; = value", 'sensitive': True}]
        result = native.plan(self.record, self.candidate, self.config)
        env = dict(x.split('=', 1) for x in result['values']['env'].split('\0'))
        self.assertEqual(env, {'A': 'image-default', 'B': 'two', 'SECRET': "a' $x \" ; = value"})
        self.assertTrue(result['restart'])

    def test_remove_environment_without_default_restores_image_environment(self):
        self.record['observed']['image']['defaults'] = {}
        self.candidate['deployment']['environment'] = []
        self.assertEqual(native.plan(self.record, self.candidate, self.config)['values']['env'], 'B=two')

    def test_public_pct_environment_and_native_lines_have_the_same_values(self):
        raw=b'lxc.environment.runtime: A=one\nlxc.environment.runtime: B=two\n'
        public=b'env: A=one\0B=two\n'
        self.assertEqual(native.environment(raw),native.environment(public))
        self.assertEqual(native.environment(public),{'A':'one','B':'two'})

    def test_duplicate_invalid_and_control_character_values_are_refused(self):
        for items in ([{'name':'X','value':'a'},{'name':'X','value':'b'}],
                      [{'name':'X','value':'a\nb'}],[{'name':'BAD NAME','value':'a'}]):
            self.candidate['deployment']['environment'] = items
            with self.assertRaises(ValueError): native.plan(self.record, self.candidate, self.config)

    def test_network_preserves_mac_vlan_ipv6_and_interface_identity(self):
        self.candidate['deployment']['network'].update(ipv4='192.0.2.2/24', gateway='192.0.2.1')
        with patch.object(Path, 'is_dir', return_value=True):
            result = native.plan(self.record, self.candidate, self.config)
        fields = dict(x.split('=',1) for x in result['values']['net0'].split(','))
        self.assertEqual(fields['hwaddr'], 'AA:BB:CC:DD:EE:FF')
        self.assertEqual(fields['tag'], '20'); self.assertEqual(fields['ip6'], 'auto')
        self.assertEqual(fields['ip'], '192.0.2.2/24'); self.assertEqual(fields['gw'], '192.0.2.1')

    def test_the_vlan_tag_is_set_changed_and_removed(self):
        for saved, wanted, expected in ((None, 30, '30'), (20, 30, '30'), (20, None, None)):
            with self.subTest(saved=saved, wanted=wanted):
                self.record['deployment']['network'].pop('vlan_tag', None)
                self.candidate['deployment']['network'].pop('vlan_tag', None)
                if saved: self.record['deployment']['network']['vlan_tag'] = saved
                if wanted: self.candidate['deployment']['network']['vlan_tag'] = wanted
                self.candidate['deployment']['network']['ipv4'] = '192.0.2.2/24'
                with patch.object(Path, 'is_dir', return_value=True):
                    result = native.plan(self.record, self.candidate, self.config)
                fields = dict(x.split('=',1) for x in result['values']['net0'].split(','))
                self.assertEqual(fields.get('tag'), expected)

    def test_an_invalid_vlan_tag_is_rejected_before_stopping(self):
        self.candidate['deployment']['network']['vlan_tag'] = 5000
        with patch.object(Path, 'is_dir', return_value=True), self.assertRaises(ValueError):
            native.plan(self.record, self.candidate, self.config)

    def test_invalid_network_is_rejected_before_stopping(self):
        for value in ('nonsense', '2001:db8::1/64'):
            self.candidate['deployment']['network']['ipv4'] = value
            with patch.object(Path, 'is_dir', return_value=True), self.assertRaises(ValueError):
                native.plan(self.record,self.candidate,self.config)

    def test_new_managed_disk_uses_native_allocation_and_existing_disk_is_untouched(self):
        self.candidate['deployment']['mounts'] = [{'type':'managed-volume','container_path':'/extra',
            'source':'local-zfs','size_gb':1,'backup':True,'read_only':False}]
        result = native.plan(self.record,self.candidate,self.config)
        self.assertEqual(result['values'], {'mp0':'local-zfs:1,mp=/extra,backup=1,ro=0'})
        self.assertNotIn('rootfs', result['values'])

    def test_removing_mount_detaches_it_without_freeing_its_volume(self):
        mount={'type':'managed-volume','container_path':'/extra','source':'local-zfs','size_gb':1,'backup':True}
        self.record['deployment']['mounts']=[mount]
        result=native.plan(self.record,self.candidate,self.config+b'mp4: local-zfs:subvol-115-disk-1,mp=/extra,backup=1,size=1G\n')
        self.assertEqual(result['delete'],['mp4'])

    def test_image_or_installer_adapter_changes_do_not_take_native_path(self):
        for key in ('image', 'adapter'):
            candidate=copy.deepcopy(self.record)
            if key=='image':candidate['template']['container_contract']['image']['reference']='new/image'
            else:candidate['deployment']['post_start_configurations']=[{'id':'rootfs-adapter'}]
            self.assertIsNone(native.changes(self.record,candidate,self.config))

    def test_secrets_use_stdin_never_arguments_or_logs(self):
        secret="super-secret with 'quotes' and $shell"
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'115.conf').write_bytes(self.config)
            with patch.object(native.resources,'CONFIG_DIR',root), \
                    patch.object(instances,'command',return_value=self.config), \
                    patch.object(native.transaction,'log') as log, \
                    patch.object(native.subprocess,'run',return_value=Mock(returncode=0)) as run:
                native.set_config(115,self.record['installation_id'],self.config,{'env':'SECRET='+secret+'\0B=two'})
            self.assertNotIn(secret,str(run.call_args.args))
            self.assertNotIn(secret,str(log.call_args_list))
            self.assertIn(secret,json.loads(run.call_args.kwargs['input'])['env'])

    def test_native_api_failure_does_not_echo_secret_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'115.conf').write_bytes(self.config)
            with patch.object(native.resources,'CONFIG_DIR',root),patch.object(instances,'command',return_value=self.config), \
                    patch.object(native.subprocess,'run',return_value=Mock(returncode=1,stderr=b'secret')):
                with self.assertRaisesRegex(RuntimeError,'Proxmox could not apply') as error:
                    native.set_config(115,self.record['installation_id'],self.config,{'env':'SECRET=secret'})
            self.assertNotIn('secret',str(error.exception))

    def test_verifies_all_environment_entries_and_native_values(self):
        native.verify_values(CONFIG,{'values':{'env':'A=one\0B=two','cores':'2'},'delete':[]})
        for values in ({'env':'A=wrong\0B=two'},{'cores':'3'}):
            with self.assertRaises(ValueError):native.verify_values(CONFIG,{'values':values,'delete':[]})
        with self.assertRaises(ValueError):native.verify_values(CONFIG,{'values':{},'delete':['env']})

    def test_native_property_canonicalization_keeps_modes_and_default_flags(self):
        cfg=CONFIG+b'dev0: path=/dev/fuse,mode=660\n'
        native.verify_values(cfg,{'values':{'dev0':'path=/dev/fuse,mode=0660,uid=0,gid=0,deny-write=0'},'delete':[]})


class NativeApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.record=record();self.candidate=copy.deepcopy(self.record)
        self.candidate['deployment']['environment']=[{'name':'A','value':'changed'}]
        self.config=CONFIG
        self.state={'config':CONFIG,'running':True}
        self.commands=[]
        def run(*args):
            self.commands.append(args)
            if args[:2]==('pct','status'):return b'status: running' if self.state['running'] else b'status: stopped'
            if args[:2]==('pct','start'):self.state['running']=True
            return b''
        def stop(vmid):self.state['running']=False
        def setter(vmid,identity,expected,values,delete=()):
            self.assertEqual(expected,self.state['config'])
            text=self.state['config'].decode()
            if 'env' in values or 'env' in delete:
                public='env: ' in text
                text=''.join(x for x in text.splitlines(keepends=True) if not x.startswith(('lxc.environment.runtime: ','env: ')))
                if public and values.get('env'):text+='env: '+values['env']+'\n'
                else:
                    for item in values.get('env','').split('\0'):
                        if item:text+='lxc.environment.runtime: '+item+'\n'
            self.state['config']=text.encode()
        def observe(*args):
            observed=copy.deepcopy(self.record['observed'])
            observed.update(config=self.state['config'].decode(),config_sha256=native.sha(self.state['config']))
            return observed
        patches=[patch.object(native,'plan',return_value={'values':{'env':'A=changed\0B=two'},'delete':[],'restart':True,'changed':['environment']}),
            patch.object(native,'set_config',side_effect=setter),patch.object(instances,'command',side_effect=lambda *a:self.state['config']),
            patch.object(native.transaction,'run',side_effect=run),patch.object(native.transaction,'stop',side_effect=stop),
            patch.object(native.transaction,'healthcheck'),patch.object(native.transaction,'preflight'),
            patch.object(native.transaction,'freeze_host_sources',return_value=({},{})),
            patch.object(native.transaction,'open_log'),patch.object(native.transaction,'log'),
            patch.object(instances,'observe',side_effect=observe),patch('oci_carried_record.carry')]
        for p in patches:p.start();self.addCleanup(p.stop)
        instances.write(instances.location(self.root,115),self.record)

    def apply(self):return native.apply(self.root,self.record,self.candidate,self.config)

    def test_runtime_edit_restarts_existing_guest_and_keeps_rootfs_image_and_data(self):
        folder=self.apply()
        saved=instances.read(self.root,115)
        self.assertEqual(saved['observed']['image'],self.record['observed']['image'])
        self.assertIn(b'rootfs: local-zfs:subvol-115-disk-0',self.state['config'])
        self.assertEqual(saved['deployment'],self.candidate['deployment'])
        self.assertTrue(self.state['running'])
        self.assertEqual(json.loads((folder/'before.json').read_text())['phase'],'committed')
        self.assertFalse(any(c[:2] in (('pct','create'),('pct','destroy')) for c in self.commands))

    def test_failed_healthcheck_rolls_back_and_starts_original_service(self):
        with patch.object(native.transaction,'healthcheck',side_effect=[RuntimeError('not healthy'),None]):
            with self.assertRaisesRegex(RuntimeError,'not healthy'):self.apply()
        self.assertEqual(self.state['config'],CONFIG)
        self.assertTrue(self.state['running'])
        self.assertEqual(instances.read(self.root,115)['deployment'],self.record['deployment'])

    def test_health_failure_restores_public_nul_separated_environment(self):
        self.config=CONFIG.replace(b'lxc.environment.runtime: A=one\nlxc.environment.runtime: B=two\n',b'env: A=one\0B=two\n')
        self.state['config']=self.config
        self.record['observed'].update(config=self.config.decode(),config_sha256=native.sha(self.config))
        instances.write(instances.location(self.root,115),self.record)
        with patch.object(native.transaction,'healthcheck',side_effect=[RuntimeError('not healthy'),None]):
            with self.assertRaises(RuntimeError):self.apply()
        self.assertEqual(native.environment(self.state['config']),{'A':'one','B':'two'})
        self.assertTrue(self.state['running'])

    def test_stopped_guest_stays_stopped(self):
        self.state['running']=False
        self.apply()
        self.assertFalse(self.state['running'])
        self.assertNotIn(('pct','start','115'),self.commands)

    def test_interrupted_edit_is_recovered_through_transaction_dispatch(self):
        folder=self.apply()
        path=folder/'before.json';state=json.loads(path.read_text());state['phase']='configured'
        instances.write(path,state)
        pending=copy.deepcopy(self.record)
        pending.update(status='updating',transaction_id=folder.name,pending_transaction=str(path))
        instances.write(instances.location(self.root,115),pending)
        native.transaction.recover(self.root,path)
        self.assertEqual(self.state['config'],CONFIG)
        saved=instances.read(self.root,115)
        self.assertEqual(saved['status'],'installed');self.assertNotIn('pending_transaction',saved)
        self.assertEqual(json.loads(path.read_text())['phase'],'rolled-back')

    def test_recovery_refuses_a_concurrent_environment_edit(self):
        folder=self.apply();path=folder/'before.json';state=json.loads(path.read_text());state['phase']='configured'
        instances.write(path,state)
        pending=copy.deepcopy(self.record)
        pending.update(status='updating',transaction_id=folder.name,pending_transaction=str(path))
        instances.write(instances.location(self.root,115),pending)
        self.state['config']=self.state['config'].replace(b'A=changed',b'A=concurrent')
        with self.assertRaisesRegex(ValueError,'changed'):native.transaction.recover(self.root,path)
        self.assertIn(b'A=concurrent',self.state['config'])

    def test_concurrent_change_before_write_is_not_overwritten(self):
        def stop(vmid):
            self.state['running']=False
            self.state['config']+=b'timezone: host\n'
        with patch.object(native.transaction,'stop',side_effect=stop):
            with self.assertRaisesRegex(ValueError,'changed'):self.apply()
        self.assertIn(b'timezone: host',self.state['config'])
        self.assertTrue(self.state['running'])

    def test_router_does_not_resolve_download_or_recreate_for_environment_edit(self):
        with patch.object(instances,'ROOT',self.root),patch.object(instances,'locked',return_value=contextlib.nullcontext()), \
                patch.object(native.transaction,'external_changes',return_value={}), \
                patch.object(update,'resolve_archive',side_effect=AssertionError('registry path')), \
                patch.object(native.transaction,'apply',side_effect=AssertionError('recreation')), \
                patch.object(oci_operation_notice,'operation',return_value=contextlib.nullcontext()):
            update.update(115,proposal={'operation':'recreate','candidate':self.candidate})
        self.assertEqual(instances.read(self.root,115)['deployment']['environment'],self.candidate['deployment']['environment'])

    def test_unsupported_same_image_adaptation_uses_the_existing_recreation_flow(self):
        self.candidate['deployment']['post_start_configurations']=[{'id':'unsupported-adapter'}]
        with patch.object(instances,'ROOT',self.root),patch.object(instances,'locked',return_value=contextlib.nullcontext()), \
                patch.object(native.transaction,'external_changes',return_value={}), \
                patch.object(update,'resolve_archive',return_value=(Path('/verified.tar'),'sha256:test')) as resolve, \
                patch.object(native.transaction,'apply') as recreate, \
                patch.object(native,'apply',side_effect=AssertionError('partial native edit')), \
                patch.object(oci_operation_notice,'operation',return_value=contextlib.nullcontext()):
            update.update(115,proposal={'operation':'recreate','candidate':self.candidate})
        resolve.assert_called_once()
        recreate.assert_called_once()
        self.assertEqual(recreate.call_args.args[3],'recreate')

    def test_optional_backup_does_not_force_recreation(self):
        with patch.object(instances,'ROOT',self.root),patch.object(instances,'locked',return_value=contextlib.nullcontext()), \
                patch.object(native.transaction,'external_changes',return_value={}), \
                patch.object(update,'resolve_archive',side_effect=AssertionError('registry path')), \
                patch.object(update,'backup_native_settings') as backup, \
                patch.object(oci_operation_notice,'operation',return_value=contextlib.nullcontext()):
            update.update(115,proposal={'operation':'recreate','candidate':self.candidate},keep_backup='test-storage')
        backup.assert_called_once_with(115,'test-storage')


if __name__=='__main__':unittest.main()
