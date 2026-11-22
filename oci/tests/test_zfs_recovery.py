"""The experimental local recovery path must fail closed and leave backup default."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))
import oci_zfs_recovery as zfs
import oci_instance_transaction as tx

TOKEN = 'a' * 32
IDENTITY = '3c72566e-4baf-4f76-b271-7a6b56f843c8'
VMID = 9001

def manifest():
    return {'kind': zfs.KIND, 'token': TOKEN, 'vmid': VMID, 'installation_id': IDENTITY,
            'config': '# proxmenux-installation=' + IDENTITY + '\nrootfs: local-zfs:subvol-9001-disk-0,size=4G\nmp1: /mnt/shared,mp=/external\n',
            'volumes': [{'vmid': VMID, 'key': 'rootfs', 'pool': 'rpool/data', 'source': 'rpool/data/subvol-9001-disk-0',
                         'storage': 'local-zfs', 'backup': f'rpool/data/subvol-9001-oci-recovery-{TOKEN}-rootfs',
                         'snapshot': 'oci-' + TOKEN, 'source_guid': '1', 'snapshot_guid': '2', 'backup_guid': '3',
                         'options': 'size=4G', 'properties': {p: 'off' for p in zfs.PROPERTIES}}]}


class Metadata(unittest.TestCase):
    def test_backup_is_the_default_even_with_zfs_installed(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(zfs.shutil, 'which', return_value='/sbin/zfs'):
            self.assertFalse(zfs.enabled())
            self.assertIsNone(zfs.plan({VMID: {}}))

    def test_auto_requires_zfs(self):
        with patch.dict(os.environ, {'PROXMENUX_OCI_RECOVERY': 'auto'}), patch.object(zfs.shutil, 'which', return_value=None):
            self.assertFalse(zfs.enabled())

    def test_metadata_is_private_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'backup.zfs.tar'; data = manifest()
            zfs.metadata_tar(path, data['config'], 'enabled: 1', data)
            self.assertEqual(zfs.load(path), data)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_config_must_match_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'backup.zfs.tar'
            zfs.metadata_tar(path, 'different', manifest=manifest())
            with self.assertRaisesRegex(ValueError, 'configuration changed'):
                zfs.load(path)

    def test_missing_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'backup.zfs.tar'; zfs.metadata_tar(path, 'config')
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                zfs.load(path)

    def test_symlink_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'real'; target.write_text('not a tar')
            link = Path(d) / 'link'; link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                zfs.load(link)

    def test_oversize_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'large'; path.write_bytes(b'x' * (4 * 1024**2 + 1))
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                zfs.load(path)

    def test_paths_and_repeated_members_are_rejected(self):
        for names in (['../evil'], ['etc/vzdump/pct.conf'] * 2):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as d:
                path = Path(d) / 'bad'
                with tarfile.open(path, 'w') as tar:
                    for name in names:
                        info = tarfile.TarInfo(name); info.size = 1
                        tar.addfile(info, io.BytesIO(b'x'))
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    zfs.load(path)

    def test_foreign_identities_and_paths_are_rejected(self):
        mutations = [lambda d: d.update(token='../bad'), lambda d: d.update(vmid=True),
                     lambda d: d.update(config='no identity'), lambda d: d.update(volumes=[]),
                     lambda d: d['volumes'].append(copy.deepcopy(d['volumes'][0])),
                     lambda d: d['volumes'][0].update(pool='/foreign'),
                     lambda d: d['volumes'][0].update(pool='rpool/../data'),
                     lambda d: d['volumes'][0].update(source='rpool/data/subvol-100-disk-0'),
                     lambda d: d['volumes'][0].update(backup='rpool/production'),
                     lambda d: d['volumes'][0].update(snapshot_guid='not-a-guid'),
                     lambda d: d['volumes'][0]['properties'].update(untrusted='on')]
        for mutation in mutations:
            data = manifest(); mutation(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                zfs.validate(data)

    def test_storage_failure_is_not_mistaken_for_absence(self):
        result = subprocess.CompletedProcess([], 1, b'', b'pool unavailable')
        with patch('subprocess.run', return_value=result), self.assertRaises(RuntimeError):
            zfs.exists('rpool/data')

    def test_missing_dataset_is_identified(self):
        result = subprocess.CompletedProcess([], 1, b'', b'cannot open: dataset does not exist')
        with patch('subprocess.run', return_value=result):
            self.assertFalse(zfs.exists('rpool/data'))

    def test_guid_change_blocks_verification(self):
        with patch.object(zfs, 'properties', return_value={zfs.TAG: TOKEN, 'guid': '999'}), self.assertRaisesRegex(ValueError, 'identity changed'):
            zfs.tagged('rpool/recovery', TOKEN, '3')

    def test_format_dispatch_preserves_existing_archives(self):
        with patch.object(tx, 'run') as run, patch.object(zfs, 'verify') as verify:
            tx.verify_recovery_archive('backup.tar.zst')
            tx.verify_recovery_archive('backup.tar.gz', 'gzip')
            tx.verify_recovery_archive('backup.zfs.tar')
            self.assertEqual(run.call_args_list[0].args, ('zstd', '-t', 'backup.tar.zst'))
            self.assertEqual(run.call_args_list[1].args, ('gzip', '-t', 'backup.tar.gz'))
            verify.assert_called_once_with('backup.zfs.tar')

    def test_restore_keeps_bind_mounts_and_uses_distinct_retry_clones(self):
        data = manifest(); commands = []
        data['volumes'][0]['properties']['quota'] = '0'
        def properties(ds, names):
            if names == ('mountpoint',):
                return {'mountpoint': '/rpool/clone'}
            if names == ('origin',):
                return {'origin': data['volumes'][0]['backup'] + '@oci-' + TOKEN}
            return data['volumes'][0]['properties']
        def run(*args):
            commands.append(args)
            return '/rpool/clone' if args[:2] == ('pvesm', 'path') else ''
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'backup.zfs.tar'; zfs.metadata_tar(path, data['config'], manifest=data)
            with patch.object(zfs, 'verify', return_value=data), patch.object(zfs, 'exists', return_value=False), \
                 patch.object(zfs, 'tagged', return_value='42'), patch.object(zfs, 'properties', side_effect=properties), \
                 patch.object(zfs, 'run', side_effect=run):
                clean, first = zfs.restore(path, VMID)
                _, second = zfs.restore(path, VMID)
            self.assertNotEqual(first[1], second[1])
            clones = [c for c in commands if c[:2] == ('zfs', 'clone')]
            self.assertTrue(clones)
            self.assertTrue(all('quota=none' in c and 'quota=0' not in c for c in clones))
            self.assertTrue(all(not any(str(x).startswith('mountpoint=') for x in c) for c in clones))
            self.assertEqual(first[-2:], ['--mp1', '/mnt/shared,mp=/external'])
            with tarfile.open(clean) as tar:
                self.assertEqual([m.name for m in tar.getmembers()], ['./etc/vzdump/pct.conf'])
            self.assertEqual(len(json.loads((path.parent/'zfs-restore.json').read_text())['attempts']), 2)

    def test_recovery_point_is_not_created_for_running_member(self):
        data = manifest(); prepared = {'volumes': data['volumes'], 'configs': {VMID: 'config'}, 'raw_configs': {VMID: data['config']}}
        fake = Mock(); fake.owned.return_value = b'config'
        with tempfile.TemporaryDirectory() as d, patch.object(zfs, 'api', return_value=fake), patch.object(zfs, 'run', return_value='status: running') as run:
            with self.assertRaisesRegex(ValueError, 'stopped'):
                zfs.create({VMID: {'installation_id': IDENTITY}}, Path(d), prepared)
            self.assertTrue((Path(d)/'zfs-build.json').exists())
            self.assertFalse(any(c.args[:2] == ('zfs', 'snapshot') for c in run.call_args_list))

    def test_eligibility_failure_falls_back_without_writes(self):
        with patch.object(zfs, 'enabled', return_value=True), patch.object(zfs, 'run', side_effect=RuntimeError('network')) as run:
            self.assertIsNone(zfs.plan({VMID: {'installation_id': IDENTITY}}))
            self.assertEqual(run.call_count, 1)

class Cleanup(unittest.TestCase):
    def state(self):
        d = manifest()
        return {'kind': zfs.KIND, 'token': TOKEN, 'records': {str(VMID): IDENTITY}, 'volumes': d['volumes'], 'released': False}

    def test_foreign_or_multiple_clones_block_destruction(self):
        state = self.state(); volume = state['volumes'][0]; point = volume['backup'] + '@' + volume['snapshot']
        def props(ds, names):
            return {n: {'guid': '3' if ds == volume['backup'] else '2', zfs.TAG: TOKEN,
                        'origin': '-', 'clones': 'rpool/foreign,rpool/other'}[n] for n in names}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'zfs-build.json'; path.write_text(json.dumps(state))
            with patch.object(zfs, 'exists', return_value=True), patch.object(zfs, 'properties', side_effect=props), \
                 patch.object(zfs, 'run', return_value=point) as run:
                with self.assertRaisesRegex(ValueError, 'external dependent'):
                    zfs.cleanup(Path(d))
                self.assertFalse(any(c.args[:2] == ('zfs','destroy') for c in run.call_args_list))
            self.assertFalse(json.loads(path.read_text())['released'])

    def test_foreign_snapshot_blocks_destruction(self):
        state = self.state(); volume = state['volumes'][0]
        def props(ds, names):
            return {n: {'guid': '3' if ds == volume['backup'] else '2', zfs.TAG: TOKEN, 'origin': '-'}[n] for n in names}
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'zfs-build.json').write_text(json.dumps(state))
            with patch.object(zfs, 'exists', return_value=True), patch.object(zfs, 'properties', side_effect=props), \
                 patch.object(zfs, 'run', return_value='foreign@snapshot') as run:
                with self.assertRaisesRegex(ValueError, 'untracked snapshots'):
                    zfs.cleanup(Path(d))
                self.assertFalse(any(c.args[:2] == ('zfs','destroy') for c in run.call_args_list))

    def test_cleanup_resumes_after_live_promotion_and_backup_deletion(self):
        state = self.state(); volume = state['volumes'][0]
        volume['cleanup_live'] = {'dataset': 'rpool/data/subvol-9001-restored', 'guid': '4'}
        live = volume['cleanup_live']['dataset']; point = live + '@' + volume['snapshot']
        def props(ds, names):
            return {n: {'guid': '4' if ds == live else '2', zfs.TAG: TOKEN}[n] for n in names}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'zfs-build.json'; path.write_text(json.dumps(state))
            with patch.object(zfs, 'exists', side_effect=lambda ds: ds == point), patch.object(zfs, 'properties', side_effect=props), \
                 patch.object(zfs, 'run') as run:
                zfs.cleanup(Path(d)); zfs.cleanup(Path(d))
                run.assert_called_once_with('zfs', 'destroy', point)
            self.assertTrue(json.loads(path.read_text())['released'])

    def test_cleanup_resumes_after_last_snapshot_was_already_removed(self):
        state=self.state(); volume=state['volumes'][0]
        def props(ds,names):
            return {n:{'guid':'3',zfs.TAG:TOKEN,'origin':'-'}[n] for n in names}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'zfs-build.json';path.write_text(json.dumps(state))
            with patch.object(zfs,'exists',side_effect=lambda ds: ds==volume['backup']),patch.object(zfs,'properties',side_effect=props),patch.object(zfs,'run',return_value='') as run:
                zfs.cleanup(Path(d))
                self.assertIn(('zfs','destroy',volume['backup']),[c.args for c in run.call_args_list])
                self.assertTrue(json.loads(path.read_text())['released'])

    def test_cleanup_failure_does_not_undo_a_healthy_recovery(self):
        with patch.object(zfs, 'cleanup', side_effect=ValueError('external clone')), patch.object(tx, 'log') as logged, patch.object(tx, 'msg_warn') as warned:
            tx.release_local_recovery(Path('/fixture'))
            self.assertIn('external clone', logged.call_args.args[0])
            self.assertIn('final cleanup did not complete', warned.call_args.args[0])

    def test_partial_snapshot_is_owned_before_removal(self):
        state=self.state(); volume=state['volumes'][0]; point=volume['source']+'@'+volume['snapshot']
        def props(ds,names):
            return {n:{'guid':'999',zfs.TAG:TOKEN}[n] for n in names}
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'zfs-build.json').write_text(json.dumps(state))
            with patch.object(zfs,'exists',side_effect=lambda ds:ds==point),patch.object(zfs,'properties',side_effect=props),patch.object(zfs,'run') as run:
                with self.assertRaisesRegex(ValueError,'source identity'):
                    zfs.cleanup(Path(d))
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
