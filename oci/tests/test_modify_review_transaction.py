"""Exercise the actual update and recovery orchestration with a simulated PVE API.

Unused volumes must leave the old CT before destroy/restore and return before
validation/commit, including an interruption during volume reassignment.
"""
import copy
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'remote'))
import oci_instances as instances
import oci_instance_transaction as transaction
from test_modify_review import installation
from test_modify_image_reuse import NEW


class UpdateRetainedDiskTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/'instances'
        self.archive=Path(temp.name)/'image.tar';self.archive.write_bytes(b'verified fixture')
        self.backup=Path(temp.name)/'backup.tar.zst';self.backup.write_bytes(b'verified backup')
        self.saved,config=installation()
        self.base_config=config
        config+=b'unused0: local-zfs:subvol-115-disk-1\nunused2: local-zfs:subvol-115-disk-2\n'
        self.saved['observed'].update(config=config.decode(),config_sha256=transaction.sha(config))
        self.saved['observed']['archive_path']=str(self.archive)
        self.image=copy.deepcopy(self.saved['observed']['image']);self.image['manifest_digest']=NEW
        self.configs={115:config};self.commands=[];self.fail_install=False;self.interrupt_return=False
        instances.write(instances.location(self.root,115),self.saved)
        def config_line(vmid,key,value):
            before=self.configs[vmid]
            result=b''.join(line for line in before.splitlines(keepends=True) if not line.startswith((key+': ').encode()))
            self.configs[vmid]=result+(key+': '+value+'\n').encode()
        def run(*args):
            self.commands.append(args)
            if args[0]=='zstd':
                self.assertEqual(args[1:],('-t',str(self.backup)))
                return b''
            if args[:2]==('pvesh','get'):
                if args[2]=='/cluster/nextid':return b'900'
                return json.dumps([{'vmid':vmid,'type':'lxc','node':socket.gethostname().split('.')[0]}
                                   for vmid in self.configs]).encode() if args[2]=='/cluster/resources' else b'[]'
            self.assertEqual(args[0],'pct',args)
            action,vmid=args[1],int(args[2])
            if action=='config':return self.configs[vmid]
            if action=='status':return b'status: running'
            if action in ('start','shutdown','stop'):return b''
            if action=='create':
                marker=args[args.index('--description')+1]
                self.configs[vmid]=f'description: {marker}\nrootfs: local-zfs:subvol-{vmid}-disk-0\n'.encode()
            elif action=='destroy':
                self.assertFalse(transaction.unused_volumes(self.configs[vmid]),'would destroy retained data')
                self.assertFalse(transaction.mounts(self.configs[vmid]),'would destroy attached data')
                del self.configs[vmid]
            elif action=='set':
                for index in range(3,len(args),2):config_line(vmid,args[index][2:],args[index+1])
            elif action=='move-volume':
                key,target,target_key=args[3],int(args[5]),args[7]
                volume=transaction.unused_volumes(self.configs[vmid])[key]
                line=(key+': '+volume+'\n').encode()
                self.configs[vmid]=self.configs[vmid].replace(line,b'')
                volume=volume.replace('subvol-'+str(vmid)+'-','subvol-'+str(target)+'-')
                config_line(target,target_key,volume)
                if self.interrupt_return and target==115:
                    self.interrupt_return=False
                    raise RuntimeError('interrupted return after PVE reassignment')
            elif action=='restore':
                # vzdump does not contain detached disks; restore skips unusedN.
                self.assertFalse(transaction.unused_volumes(self.configs.get(vmid,b'')))
                self.configs[vmid]=self.base_config
            else:self.fail('Unexpected PVE command: '+str(args))
            return b''
        def install(root,journal,state,progress=None):
            if self.fail_install:raise RuntimeError('installer failed after old rootfs was removed')
            self.configs[state['vmid']]=self.base_config
        def observe(vmid,identity,archive,digest,image=None):
            observed=copy.deepcopy(self.saved['observed'])
            observed.update(config=self.configs[vmid].decode(),config_sha256=transaction.sha(self.configs[vmid]),
                            image=copy.deepcopy(image or self.image),resolved_registry_digest=digest)
            return observed
        original_exists=Path.exists
        def exists(path):
            match=re.fullmatch(r'/etc/pve/lxc/([0-9]+)\.conf',str(path))
            return int(match[1]) in self.configs if match else original_exists(path)
        patches=[patch.object(transaction,'run',side_effect=run),patch.object(transaction,'open_log'),
            patch.object(transaction,'log'),patch.object(transaction,'stop'),
            patch.object(transaction,'check_archive'),patch.object(transaction,'image_from_archive',return_value=self.image),
            patch.object(transaction,'verified_backup',return_value=self.backup),
            patch.object(transaction,'install_candidate',side_effect=install),
            patch.object(transaction,'healthcheck',return_value='running'),
            patch.object(transaction,'candidate_host_sources',return_value={}),
            patch.object(transaction,'prune_backups'),patch.object(transaction.image_cache,'prune',return_value=[]),
            patch.object(transaction,'cleanup_restored_format_dirs'),patch.object(transaction.runtime_settings,'restore'),
            patch.object(transaction.work_backup,'locate',side_effect=lambda directory,*a:directory),
            patch.object(instances,'observe',side_effect=observe),patch.object(Path,'exists',exists)]
        for p in patches:p.start();self.addCleanup(p.stop)
        self.addCleanup(transaction._run.update,journal=None)

    def apply(self,**kwargs):return transaction.apply(self.root,115,self.archive,'update',registry_digest=NEW,**kwargs)

    def journal(self):return next(instances.location(self.root,115).parent.glob('transactions/*/transaction.json'))

    def assert_retained(self):
        self.assertEqual(transaction.unused_volumes(self.configs[115]),{
            'unused0':'local-zfs:subvol-115-disk-1','unused2':'local-zfs:subvol-115-disk-2'})
        self.assertNotIn(900,self.configs)
        self.assertFalse(any(args[:2]==('pct','set') and '--delete' in args for args in self.commands))

    def test_update_keeps_detached_disks_and_the_next_update_preflight_accepts_them(self):
        self.apply();self.assert_retained()
        saved=instances.read(self.root,115)
        self.assertEqual(saved['status'],'installed')
        self.assertEqual(saved['observed']['image']['manifest_digest'],NEW)
        transaction.preflight(saved,copy.deepcopy(saved),self.configs[115])
        self.assertEqual(json.loads(self.journal().read_text())['phase'],'committed')

    def test_failed_install_restores_both_backup_and_detached_disks(self):
        self.fail_install=True
        with self.assertRaisesRegex(RuntimeError,'installer failed'):self.apply()
        transaction.recover(self.root,self.journal())
        self.assert_retained()
        self.assertEqual(instances.read(self.root,115)['observed']['image'],self.saved['observed']['image'])
        self.assertEqual(json.loads(self.journal().read_text())['phase'],'rolled-back')

    def test_recovery_after_parking_data_returns_the_original_unused_disks(self):
        with self.assertRaisesRegex(RuntimeError,'Lab interruption'):self.apply(interrupt_after='data-parked')
        transaction.recover(self.root,self.journal());self.assert_retained()

    def test_recovery_handles_an_interruption_while_returning_unused_disks(self):
        self.interrupt_return=True
        with self.assertRaisesRegex(RuntimeError,'interrupted return'):self.apply()
        transaction.recover(self.root,self.journal());self.assert_retained()

    def test_failed_runtime_check_recovers_disks_already_returned_to_the_candidate(self):
        with patch.object(transaction.gpu_devices,'validate_runtime',side_effect=[RuntimeError('invalid runtime'), None]):
            with self.assertRaisesRegex(RuntimeError,'invalid runtime'):self.apply()
            transaction.recover(self.root,self.journal())
        self.assert_retained()


if __name__=='__main__':unittest.main()
