"""Maintainer review: conservative ZFS preflight and non-blocking cleanup."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'remote'), str(Path(__file__).parent)]
import oci_zfs_recovery as zfs
import oci_work_backup as work
import oci_instance_transaction as tx
from test_zfs_recovery import manifest, VMID, IDENTITY, TOKEN


class Review(unittest.TestCase):
    def test_read_only_plan_falls_back_on_unexpected_backend_exception(self):
        for error in (TypeError('shape'), StopIteration(), subprocess.TimeoutExpired('pvesh', 30)):
            with self.subTest(error=error), patch.object(zfs, 'enabled', return_value=True), \
                 patch.object(zfs, 'run', side_effect=error):
                self.assertIsNone(zfs.plan({VMID: {'installation_id': IDENTITY}}))

    def test_space_requires_full_rewrite_plus_margin(self):
        volumes = manifest()['volumes']
        def values(ds, names):
            return {'available': str(1024**3 + 219)} if names == ('available',) else {'referenced': '100', 'logicalreferenced': '200'}
        with patch.object(zfs, 'properties', side_effect=values), self.assertRaisesRegex(ValueError, 'space'):
            zfs.check_space(volumes)
        with patch.object(zfs, 'properties', side_effect=lambda ds,n: {'available': str(2*1024**3)} if n == ('available',) else {'referenced':'100','logicalreferenced':'200'}):
            zfs.check_space(volumes)

    def test_multiple_volumes_share_one_space_reservation(self):
        volumes = manifest()['volumes'] * 2
        with patch.object(zfs, 'properties', side_effect=lambda ds,n: {'available': str(1024**3 + 300)} if n == ('available',) else {'referenced':'200','logicalreferenced':'100'}), self.assertRaises(ValueError):
            zfs.check_space(volumes)

    def test_storage_datasets_cannot_double_spend_shared_pool_space(self):
        volumes=manifest()['volumes']
        second=copy.deepcopy(volumes[0]);second['pool']='rpool/other';second['source']='rpool/other/subvol-9905-disk-0'
        def values(ds,names):
            if names==('available',):return {'available':str(2*1024**3 if ds=='rpool' else 3*1024**3)}
            return {'referenced':'200','logicalreferenced':'200'}
        with patch.object(zfs,'properties',side_effect=values),self.assertRaisesRegex(ValueError,'shared pool space'):
            zfs.check_space(volumes+[second])

    def test_new_recovery_dataset_names_are_not_native_disks(self):
        volume = manifest()['volumes'][0]
        name = zfs.backup_name(volume, TOKEN)
        self.assertNotIn('/subvol-', name)
        volume['backup'] = name
        data = manifest(); data['volumes'] = [volume]
        zfs.validate(data)
        zfs.validate(manifest())  # old opt-in metadata remains readable

    def create(self, run):
        data = manifest()
        prepared = {'volumes': data['volumes'], 'configs': {VMID:'config'}, 'raw_configs':{VMID:data['config']}}
        fake = Mock(); fake.owned.return_value = b'config'
        with tempfile.TemporaryDirectory() as d, patch.object(zfs, 'api', return_value=fake), \
             patch.object(zfs, 'run', side_effect=run), patch.object(zfs, 'check_space'), \
             patch.object(zfs, 'properties', return_value={'guid':'1','origin':'-'}):
            zfs.create({VMID:{'installation_id':IDENTITY}}, Path(d), prepared)

    def test_external_snapshot_before_protection_prevents_snapshot_and_clone(self):
        commands=[]
        def run(*args):
            commands.append(args)
            return 'status: stopped' if args[:2] == ('pct','status') else 'pool/volume@external'
        with self.assertRaisesRegex(ValueError, 'acquired snapshots'):
            self.create(run)
        self.assertFalse(any(c[:2] in [('zfs','snapshot'),('zfs','clone')] for c in commands))

    def test_restore_properties_are_exercised_before_promotion(self):
        commands=[]
        def run(*args):
            commands.append(args)
            if args[:2] == ('pct','status'): return 'status: stopped'
            if args[:2] == ('zfs','clone'): raise RuntimeError('unsupported aclmode')
            return ''
        with self.assertRaisesRegex(RuntimeError, 'aclmode'):
            self.create(run)
        clone = next(c for c in commands if c[:2] == ('zfs','clone'))
        self.assertIn('aclmode=off', clone)
        self.assertIn('com.sun:auto-snapshot=false', clone)
        self.assertFalse(any(c[:2] == ('zfs','promote') for c in commands))

    def test_cleanup_error_keeps_archive_and_warns(self):
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d); backup=directory/'backup'/'vzdump-lxc-9001.zfs.tar'
            backup.parent.mkdir(); backup.write_text('metadata')
            with patch.object(zfs,'cleanup',side_effect=KeyError('malformed journal')), patch.object(work,'msg_warn') as warn:
                self.assertIs(work.clear(directory),False)
            self.assertTrue(backup.exists()); warn.assert_called_once()

    def test_forget_continues_and_preserves_blocked_recovery_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); app=root/str(VMID)
            blocked=app/'transactions'/'blocked'; healthy=app/'transactions'/'healthy'
            for p in (blocked,healthy):p.mkdir(parents=True)
            (blocked/'zfs-build.json').write_text('owned metadata')
            def cleanup(p):
                if p==blocked:raise ValueError('external clone')
            with patch.object(zfs,'cleanup',side_effect=cleanup) as cleaned, patch.object(work,'msg_warn'):
                work.forget(root,VMID)
            self.assertEqual(cleaned.call_count,2)
            retained=root/'retained-zfs-recovery'/str(VMID)/'transactions'/'blocked'/'zfs-build.json'
            self.assertEqual(retained.read_text(),'owned metadata')
            self.assertFalse(blocked.exists())

    def test_unreleased_points_are_visible_until_cleanup_is_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/str(VMID)/'transactions'/'one'/'zfs-build.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'released':False}))
            self.assertEqual(work.unreleased(d,VMID),[str(path)])
            path.write_text(json.dumps({'released':True}))
            self.assertEqual(work.unreleased(d,VMID),[])

    def test_unusual_cleanup_errors_do_not_fail_healthy_recovery(self):
        for error in (KeyError('a'),TypeError('b'),StopIteration()):
            with patch.object(zfs,'cleanup',side_effect=error), patch.object(tx,'log'), patch.object(tx,'msg_warn'):
                tx.release_local_recovery('/private/fixture')

if __name__=='__main__':unittest.main()
