"""Regression tests for explicit adoption of external OCI resources."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))

import oci_instance_reconcile as reconcile
from oci_installation_state import sha


class MountTests(unittest.TestCase):
    def test_managed_volume_belongs_to_container(self):
        mount = reconcile._mount(
            'mp2', 'local-lvm:vm-200-disk-3,mp=/media,size=8G,backup=1', 200)
        self.assertEqual((mount['source'], mount['size_gb'], mount['backup']),
                         ('local-lvm', 8, True))
        with self.assertRaises(ValueError):
            reconcile._mount('mp2', 'local-lvm:vm-201-disk-3,mp=/media,size=8G,backup=1', 200)

    def test_mount_rejects_missing_backup_and_unsupported_options(self):
        for value in (
            'local-lvm:vm-200-disk-3,mp=/media,size=8G,backup=0',
            'local-lvm:vm-200-disk-3,mp=/media,size=8G,backup=1,acl=1',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reconcile._mount('mp2', value, 200)

    def test_non_integral_disk_size_rejected(self):
        with self.assertRaises(ValueError):
            reconcile._managed_size('7M')


class ProposalTests(unittest.TestCase):
    def test_new_volume_requires_confirmation_before_contract_changes(self):
        config = b'description: proxmenux-instance=11111111-1111-1111-1111-111111111111\n'
        added = config + b'mp2: local-lvm:vm-200-disk-3,mp=/media,size=8G,backup=1\n'
        record = {
            'vmid': 200, 'status': 'installed',
            'installation_id': '11111111-1111-1111-1111-111111111111',
            'deployment': {'mounts': [], 'devices': []},
            'observed': {'config': config.decode(), 'config_sha256': sha(config),
                         'archive_path': '/unused.tar', 'resolved_registry_digest': 'sha256:test',
                         'image': {'manifest_digest': 'sha256:test'}},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / '200' / 'oci-compose.json'
            target.parent.mkdir()
            target.write_text(json.dumps(record))
            with (patch.object(reconcile.instances, 'ROOT', root),
                  patch.object(reconcile.instances, 'identity', return_value=record['installation_id']),
                  patch.object(reconcile.gpu_devices, 'capture', return_value={}),
                  patch.object(reconcile.host_mounts, 'capture_sources', return_value={}),
                  patch.object(reconcile.transaction, 'preflight')):
                proposal = reconcile.propose(record, added)
            self.assertEqual(proposal['candidate']['deployment']['mounts'][0]['container_path'], '/media')
            self.assertEqual(json.loads(target.read_text())['deployment']['mounts'], [])

    def test_commit_rechecks_configuration_and_saves_only_after_validation(self):
        config = b'description: proxmenux-instance=11111111-1111-1111-1111-111111111111\n'
        added = config + b'mp2: local-lvm:vm-200-disk-3,mp=/media,size=8G,backup=1\n'
        record = {
            'schema_version': 1, 'vmid': 200, 'status': 'installed',
            'installation_id': '11111111-1111-1111-1111-111111111111',
            'deployment': {'mounts': [], 'devices': []},
            'observed': {'config': config.decode(), 'config_sha256': sha(config),
                         'archive_path': '/unused.tar', 'resolved_registry_digest': 'sha256:test',
                         'image': {'manifest_digest': 'sha256:test'}},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / '200' / 'oci-compose.json'
            target.parent.mkdir()
            target.write_text(json.dumps(record))
            with (patch.object(reconcile.instances, 'ROOT', root),
                  patch.object(reconcile.instances, 'identity', return_value=record['installation_id']),
                  patch.object(reconcile.instances, 'command', return_value=added),
                  patch.object(reconcile.instances, 'observe', return_value={
                      'config': added.decode(), 'config_sha256': sha(added)}),
                  patch.object(reconcile.gpu_devices, 'capture', return_value={}),
                  patch.object(reconcile.host_mounts, 'capture_sources', return_value={}),
                  patch.object(reconcile.transaction, 'preflight')):
                proposal = reconcile.propose(record, added)
                stale = dict(proposal, config_sha256='wrong')
                with self.assertRaises(ValueError):
                    reconcile.commit(root, 200, stale)
                self.assertEqual(json.loads(target.read_text())['deployment']['mounts'], [])
                result = reconcile.commit(root, 200, proposal)
            self.assertEqual(result['deployment']['mounts'][0]['container_path'], '/media')
            self.assertEqual(json.loads(target.read_text())['observed']['config_sha256'], sha(added))
            history = list((target.parent / 'history').glob('before-reconciliation-*.json'))
            self.assertEqual(len(history), 1)
            self.assertEqual(json.loads(history[0].read_text())['deployment']['mounts'], [])


if __name__ == '__main__':
    unittest.main()
