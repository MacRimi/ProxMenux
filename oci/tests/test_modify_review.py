"""Maintainer review: fallback, complete mount edits and retained unused disks."""
import contextlib
import copy
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'remote'))
import oci_instances as instances
import oci_instance_transaction as transaction
import oci_native_modify as native
import oci_update_current as update
import oci_operation_notice
from test_modify_image_reuse import record, CONFIG


def installation():
    result=record()
    result['deployment'].update(rootfs={'storage':'local-zfs','size_gb':8}, onboot=True,
                               security={'unprivileged':True})
    result['observed']['image']['defaults']={}
    config=CONFIG+b'unprivileged: 1\nonboot: 1\nnet0: name=eth0,bridge=vmbr0,ip=dhcp,hwaddr=AA:BB:CC:DD:EE:FF\n'
    result['observed'].update(config=config.decode(), config_sha256=transaction.sha(config))
    return result,config


class FallbackTests(unittest.TestCase):
    def test_all_installer_adaptations_fall_back_before_any_native_write(self):
        saved,config=installation()
        def nvidia(c):c['deployment']['devices']=[{'kind':'nvidia-runtime','host_path':'/dev/nvidia0'}]
        def groups(c):c['deployment']['devices']=[{'host_path':'/dev/dri/renderD128','append_host_device_gid_to_environment':'GROUPS'}]
        def permissions(c):
            c['deployment']['devices']=[{'host_path':'/dev/dri/renderD128'}]
            c['deployment']['device_permissions']={'uid':1000}
        mutations=[nvidia,groups,permissions,
            lambda c:c['deployment'].update(completion_notes=['Installer note']),
            lambda c:c['deployment'].update(post_start_configurations=[{'id':'adapter'}]),
            lambda c:c['template']['catalog_ui'].update(title='Refreshed catalog template'),
            lambda c:c['deployment'].update(mounts=[{'type':'host-bind','source':'/host/file','container_path':'/config/file','backup':False,'size_gb':None}])]
        for mutation in mutations:
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as folder:
                candidate=copy.deepcopy(saved);mutation(candidate)
                root=Path(folder);instances.write(instances.location(root,115),saved)
                with patch.object(instances,'ROOT',root),patch.object(instances,'locked',return_value=contextlib.nullcontext()), \
                        patch.object(instances,'command',return_value=config), \
                        patch.object(transaction,'external_changes',return_value={}),patch.object(transaction,'preflight'), \
                        patch.object(transaction,'is_file_bind',side_effect=lambda m:m.get('source')=='/host/file'), \
                        patch.object(native,'apply',side_effect=AssertionError('partial native apply')), \
                        patch.object(update,'resolve_archive',return_value=(Path('/cached.tar'),'sha256:resolved')) as resolve, \
                        patch.object(transaction,'apply') as recreate, \
                        patch.object(oci_operation_notice,'operation',return_value=contextlib.nullcontext()):
                    update.update(115,proposal={'operation':'recreate','candidate':candidate})
                recreate.assert_called_once();resolve.assert_called_once()
                self.assertEqual(resolve.call_args.kwargs['local_archives'],[saved['observed']['archive_path']])

    def test_native_validation_failure_never_falls_back_to_recreation(self):
        saved,config=installation();candidate=copy.deepcopy(saved)
        candidate['deployment']['environment']=[{'name':'INVALID NAME','value':'value'}]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);instances.write(instances.location(root,115),saved)
            with patch.object(instances,'ROOT',root),patch.object(instances,'locked',return_value=contextlib.nullcontext()), \
                    patch.object(instances,'command',return_value=config), \
                    patch.object(transaction,'preflight'),patch.object(transaction,'external_changes',return_value={}), \
                    patch.object(transaction,'apply') as recreate,patch.object(update,'resolve_archive') as resolve, \
                    patch.object(oci_operation_notice,'operation',return_value=contextlib.nullcontext()):
                with self.assertRaises(ValueError):update.update(115,proposal={'operation':'recreate','candidate':candidate})
            recreate.assert_not_called();resolve.assert_not_called()

    def test_native_api_failure_never_falls_back_after_starting_the_edit(self):
        saved,config=installation();candidate=copy.deepcopy(saved)
        candidate['deployment']['environment']=[{'name':'VALID','value':'value'}]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);instances.write(instances.location(root,115),saved)
            with patch.object(instances,'ROOT',root),patch.object(instances,'locked',return_value=contextlib.nullcontext()), \
                    patch.object(instances,'command',return_value=config), \
                    patch.object(transaction,'preflight'),patch.object(transaction,'external_changes',return_value={}), \
                    patch.object(transaction,'apply') as recreate,patch.object(update,'resolve_archive') as resolve, \
                    patch.object(native,'apply',side_effect=RuntimeError('native API failed')), \
                    patch.object(oci_operation_notice,'operation',return_value=contextlib.nullcontext()):
                with self.assertRaisesRegex(RuntimeError,'native API failed'):
                    update.update(115,proposal={'operation':'recreate','candidate':candidate})
            recreate.assert_not_called();resolve.assert_not_called()


class MountTests(unittest.TestCase):
    def setUp(self):
        self.record,self.config=installation()
        self.mount={'type':'host-bind','source':'/mnt/old','container_path':'/media',
                    'size_gb':None,'backup':False,'read_only':False,'create_if_missing':False}
        self.record['deployment']['mounts']=[self.mount]
        self.config+=b'mp3: /mnt/old,mp=/media,backup=0,ro=0,replicate=0\n'
        self.record['observed'].update(config=self.config.decode(),config_sha256=transaction.sha(self.config))
        self.candidate=copy.deepcopy(self.record)

    def test_existing_bind_source_and_flags_are_applied_with_other_options_preserved(self):
        self.candidate['deployment']['mounts'][0].update(source='/mnt/new',read_only=True)
        with patch.object(Path,'is_dir',return_value=True):
            plan=native.plan(self.record,self.candidate,self.config)
        self.assertEqual(plan['values'],{'mp3':'/mnt/new,mp=/media,backup=0,ro=1,replicate=0'})
        self.assertTrue(plan['restart']);self.assertEqual(plan['delete'],[])

    def test_missing_replacement_directory_is_rejected_unless_creation_was_requested(self):
        self.candidate['deployment']['mounts'][0]['source']='/mnt/new'
        with patch.object(Path,'is_dir',return_value=False):
            with self.assertRaisesRegex(ValueError,'directory does not exist'):
                native.plan(self.record,self.candidate,self.config)
            self.candidate['deployment']['mounts'][0]['create_if_missing']=True
            self.assertIn('/mnt/new,',native.plan(self.record,self.candidate,self.config)['values']['mp3'])

    def test_verification_detects_a_source_that_was_not_applied(self):
        operation={'values':{'mp3':'/mnt/new,mp=/media,backup=0,ro=0'},'delete':[]}
        with self.assertRaisesRegex(ValueError,'could not apply'):native.verify_values(self.config,operation)
        native.verify_values(self.config.replace(b'/mnt/old',b'/mnt/new'),operation)

    def test_unknown_mount_options_and_permission_grants_use_installer(self):
        for fields in ({'grant_access':True},{'mount_options':['noexec']},{'type':'managed-volume','source':'local-zfs','size_gb':2,'backup':True}):
            candidate=copy.deepcopy(self.candidate);candidate['deployment']['mounts'][0].update(fields)
            self.assertIsNone(native.changes(self.record,candidate,self.config))

    def test_recursive_bind_adaptations_use_installer(self):
        self.candidate['deployment']['mounts'][0]['read_only']=True
        derived=b'lxc.mount.entry: /mnt/old media none rbind,rslave,create=dir 0 0\n'
        self.assertIsNone(native.changes(self.record,self.candidate,self.config+derived))

    def test_storage_and_disk_size_changes_keep_existing_migration_guard(self):
        self.record['deployment']['mounts'][0].update(type='managed-volume',source='local-zfs',size_gb=1,backup=True)
        self.config=self.config.replace(b'/mnt/old,mp=/media,backup=0',b'local-zfs:subvol-115-disk-1,mp=/media,backup=1')
        self.record['observed']['config']=self.config.decode()
        for fields in ({'size_gb':2},{'source':'other-storage'}):
            candidate=copy.deepcopy(self.record);candidate['deployment']['mounts'][0].update(fields)
            self.assertIsNone(native.changes(self.record,candidate,self.config))
            with self.assertRaisesRegex(ValueError,'migration'):transaction.preflight(self.record,candidate,self.config)


class DetachedPreflightTests(unittest.TestCase):
    def test_removing_a_mount_then_updating_accepts_the_recorded_unused_disk(self):
        saved,config=installation()
        saved['deployment']['mounts']=[{'type':'managed-volume','source':'local-zfs','size_gb':1,
            'container_path':'/extra','backup':True,'read_only':False}]
        config+=b'mp4: local-zfs:subvol-115-disk-1,mp=/extra,backup=1,size=1G\n'
        saved['observed']['config']=config.decode()
        candidate=copy.deepcopy(saved);candidate['deployment']['mounts']=[]
        self.assertEqual(native.plan(saved,candidate,config)['delete'],['mp4'])
        detached=config.replace(b'mp4: local-zfs:subvol-115-disk-1,mp=/extra,backup=1,size=1G\n',b'unused0: local-zfs:subvol-115-disk-1\n')
        candidate['observed'].update(config=detached.decode(),config_sha256=transaction.sha(detached))
        cfg,_,_=transaction.preflight(candidate,copy.deepcopy(candidate),detached)
        self.assertIn('unused0',cfg)

    def test_unrecorded_detached_disks_are_not_adopted_silently(self):
        saved,config=installation()
        with self.assertRaisesRegex(ValueError,'disks do not match|discard those changes'):
            transaction.preflight(saved,copy.deepcopy(saved),config+b'unused0: local-zfs:subvol-115-disk-1\n')

    def test_invalid_duplicate_or_mounted_unused_disks_are_rejected(self):
        for extra in (b'unused0: /etc/passwd\n',b'unused0: local-zfs:subvol-115-disk-0\n',
                      b'unused0: local-zfs:subvol-115-disk-1\nunused1: local-zfs:subvol-115-disk-1\n'):
            saved,config=installation();config+=extra;saved['observed']['config']=config.decode()
            with self.assertRaisesRegex(ValueError,'disks do not match'):transaction.preflight(saved,copy.deepcopy(saved),config)


class DetachedTransferTests(unittest.TestCase):
    def setUp(self):
        saved,config=installation()
        self.configs={115:config+b'unused0: local-zfs:subvol-115-disk-1\nunused2: local-zfs:subvol-115-disk-2\n',
                      900:b'description: proxmenux-transaction=test-tx\nrootfs: local-zfs:subvol-900-disk-0\n'}
        self.state={'vmid':115,'stage':900,'id':'test-tx','record':saved,
                    'retained_unused':transaction.unused_volumes(self.configs[115])}
        self.calls=[]
        def owned(vmid,marker):
            self.assertIn(marker.encode(),self.configs[vmid]);return self.configs[vmid]
        def run(*args):
            self.calls.append(args);self.assertEqual(args[:2],('pct','move-volume'))
            source,key,target=int(args[2]),args[3],int(args[5]);self.assertEqual(key,args[7])
            line=next(line for line in self.configs[source].splitlines(keepends=True) if line.startswith((key+': ').encode()))
            self.configs[source]=self.configs[source].replace(line,b'')
            self.configs[target]+=line.replace(('subvol-'+str(source)+'-').encode(),('subvol-'+str(target)+'-').encode())
        for p in (patch.object(transaction,'owned',side_effect=owned),patch.object(transaction,'run',side_effect=run)):
            p.start();self.addCleanup(p.stop)

    def test_unused_disks_are_parked_and_returned_without_freeing_any_volume(self):
        transaction.move_retained_unused(self.state,True)
        self.assertEqual(transaction.unused_volumes(self.configs[115]),{})
        self.assertEqual(set(transaction.unused_volumes(self.configs[900])),{'unused0','unused2'})
        transaction.move_retained_unused(self.state,False)
        self.assertEqual(transaction.unused_volumes(self.configs[115]),self.state['retained_unused'])
        self.assertEqual(transaction.unused_volumes(self.configs[900]),{})
        self.assertEqual(len(self.calls),4)

    def test_an_interrupted_transfer_can_be_retried_in_both_directions(self):
        original=transaction.run.side_effect
        def interrupt(*args):
            original(*args);raise RuntimeError('interrupted after reassignment')
        with patch.object(transaction,'run',side_effect=interrupt):
            with self.assertRaises(RuntimeError):transaction.move_retained_unused(self.state,True)
        transaction.move_retained_unused(self.state,True)
        with patch.object(transaction,'run',side_effect=interrupt):
            with self.assertRaises(RuntimeError):transaction.move_retained_unused(self.state,False)
        transaction.move_retained_unused(self.state,False)
        self.assertEqual(transaction.unused_volumes(self.configs[115]),self.state['retained_unused'])

    def test_unrelated_unused_disks_are_not_moved(self):
        self.configs[115]+=b'unused3: local-zfs:subvol-115-disk-3\n'
        with self.assertRaises(ValueError):transaction.move_retained_unused(self.state,True)
        self.assertEqual(self.calls,[])

    def test_a_missing_disk_or_target_collision_blocks_the_transfer(self):
        del self.state['retained_unused']['unused2']
        self.configs[115]=self.configs[115].replace(b'unused2: local-zfs:subvol-115-disk-2\n',b'')
        self.configs[900]+=b'unused0: local-zfs:subvol-900-disk-9\n'
        with self.assertRaises(ValueError):transaction.move_retained_unused(self.state,True)
        self.configs[115]=self.configs[115].replace(b'unused0: local-zfs:subvol-115-disk-1\n',b'')
        self.configs[900]=self.configs[900].replace(b'unused0: local-zfs:subvol-900-disk-9\n',b'')
        with self.assertRaises(ValueError):transaction.move_retained_unused(self.state,False)


if __name__=='__main__':unittest.main()
