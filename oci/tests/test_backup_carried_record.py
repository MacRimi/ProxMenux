"""A backup must contain its validated original metadata, despite a pending registry."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))
import oci_carried_record as carried

VMID = 4801
IDENTITY = '488ed3cb-1145-477a-b90f-c46777d69fb2'
CONFIG = ('description: <!-- proxmenux-instance='+IDENTITY+' -->\n'
          'rootfs: local-zfs:subvol-4801-disk-0,size=8G\n'
          'unprivileged: 1\nlxc.init.uid: 999\n'
          'net0: name=eth0,bridge=vmbr10,ip=10.77.0.31/24\n')
ORIGINAL = {'vmid': VMID, 'installation_id': IDENTITY, 'status': 'installed',
            'deployment': {}, 'observed': {'config': CONFIG}}

class BackupCarriedRecordTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'registry'; self.rootfs_base = Path(temporary.name)/'lxc'
        self.rootfs = self.rootfs_base/str(VMID)/'rootfs'; self.rootfs.mkdir(parents=True)
        self.config = CONFIG; self.status = 'stopped'; self.unmount_code = 0; self.commands = []
        def run(*args):
            self.commands.append(args)
            value = self.config if args[1]=='config' else 'status: '+self.status if args[1]=='status' else ''
            code = self.unmount_code if args[1]=='unmount' else 0
            return SimpleNamespace(returncode=code, stdout=value)
        for name, value in [('_run',run),('_host_directory_missing',lambda _:False),
                            ('ROOTFS',self.rootfs_base),('mapped_root',lambda _: (os.getuid(),os.getgid()))]:
            context=patch.object(carried,name,value);context.start();self.addCleanup(context.stop)

    def carry(self, original=None):
        return carried.carry_backup(self.root,VMID,original or ORIGINAL,CONFIG)

    def test_pending_host_registry_does_not_replace_the_validated_original(self):
        pending=copy.deepcopy(ORIGINAL);pending.update(status='updating',pending_stack_transaction='/transaction')
        carried.instances.write(carried.instances.location(self.root,VMID),pending)
        result=self.carry()
        copy_in_backup=carried.read_copy(self.rootfs)
        self.assertEqual(copy_in_backup['record'],ORIGINAL)
        self.assertNotIn('pending_stack_transaction',copy_in_backup['record'])
        self.assertEqual(result['digest'],carried.digest(copy_in_backup))
        self.assertEqual(self.commands.count(('pct','mount',str(VMID))),1)
        self.assertEqual(self.commands.count(('pct','unmount',str(VMID))),1)
        self.assertEqual(json.loads(carried.instances.location(self.root,VMID).read_text()),pending)

    def test_notes_and_backup_lock_changes_do_not_hide_identity(self):
        self.config=CONFIG.replace('description: ','description: user notes ')+'lock: backup\n'
        self.carry()
        self.assertEqual(carried.read_copy(self.rootfs)['record'],ORIGINAL)

    def test_runtime_network_mount_user_and_identity_drift_are_refused(self):
        for before,after in [('10.77.0.31','10.77.0.99'),('disk-0','disk-1'),('uid: 999','uid: 1000'),(IDENTITY,'11111111-1111-4111-8111-111111111111')]:
            with self.subTest(after=after):
                self.config=CONFIG.replace(before,after);self.commands=[]
                with self.assertRaises(ValueError):self.carry()
                self.assertNotIn(('pct','mount',str(VMID)),self.commands)

    def test_running_guest_and_pending_original_are_refused(self):
        self.status='running'
        with self.assertRaises(ValueError):self.carry()
        self.status='stopped'
        for field,value in [('status','updating'),('pending_transaction','/transaction'),('pending_stack_transaction','/stack')]:
            record=dict(ORIGINAL,**{field:value})
            with self.subTest(field=field),self.assertRaises(ValueError):self.carry(record)

    def test_write_failure_is_not_silenced_and_always_unmounts(self):
        with patch.object(carried,'write_copy',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):self.carry()
        self.assertIn(('pct','unmount',str(VMID)),self.commands)

    def test_roundtrip_mismatch_and_unmount_failure_abort_before_success_stamp(self):
        with patch.object(carried,'read_copy',return_value=None):
            with self.assertRaises(ValueError):self.carry()
        self.assertFalse((carried.instances.location(self.root,VMID).parent/carried.STAMP).exists())
        self.unmount_code=1
        with self.assertRaises(ValueError):self.carry()

if __name__=='__main__':unittest.main()
