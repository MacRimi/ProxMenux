"""Regression tests for explicit adoption of external OCI resources."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess

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
    def test_note_only_comparison_keeps_other_lxc_settings_strict(self):
        marker = '11111111-1111-1111-1111-111111111111'
        before = f'description: Old proxmenux-instance={marker}\ncores: 2\n'.encode()
        record = {'installation_id': marker, 'observed': {'config': before.decode()}}
        updated = f'description: New proxmenux-instance={marker}\ncores: 2\n'.encode()
        self.assertTrue(reconcile.instances.same_config_except_notes(record, updated))
        self.assertFalse(reconcile.instances.same_config_except_notes(record, updated.replace(b'cores: 2', b'cores: 4')))
        self.assertFalse(reconcile.instances.same_config_except_notes(record, b'description: Other instance\ncores: 2\n'))

    def test_replacement_restores_user_notes_verbatim(self):
        marker = '11111111-1111-1111-1111-111111111111'
        notes = f'<p>Nota personal: no borrar</p><!-- proxmenux-instance={marker} -->'
        state = {'record': {'installation_id': marker}, 'original_description': notes}
        with patch.object(reconcile.transaction, 'run') as run:
            reconcile.transaction.restore_description(200, state)
        run.assert_called_once_with('pct', 'set', '200', '--description', notes)
        state.pop('original_description')
        state['before_config'] = f'description: {notes.replace("%", "%25").replace("<", "%3C").replace(">", "%3E")}\n'
        self.assertEqual(reconcile.transaction.original_description(state), notes)

    def test_restoring_notes_does_not_log_their_contents(self):
        notes = '<p>Nota privada del usuario</p>'
        with (patch.object(reconcile.transaction, 'log') as log,
              patch.object(reconcile.transaction.subprocess, 'run',
                           return_value=CompletedProcess([], 0, b'', b'')) as command):
            reconcile.transaction.run('pct', 'set', '200', '--description', notes)
        command.assert_called_once()
        self.assertNotIn(notes, str(log.call_args))

    def test_notes_only_change_does_not_require_adoption_or_block_update(self):
        marker = '11111111-1111-1111-1111-111111111111'
        config = f'description: Old notes proxmenux-instance={marker}\n'.encode()
        updated = f'description: New notes proxmenux-instance={marker}\n'.encode()
        record = {
            'vmid': 200, 'status': 'installed', 'installation_id': marker,
            'deployment': {'mounts': [], 'devices': []},
            'observed': {'config': config.decode(), 'config_sha256': sha(config)},
        }
        self.assertIsNone(reconcile.propose(record, updated))
        self.assertEqual(reconcile.transaction.external_changes(record, updated), {})

    def test_notes_cannot_hide_identity_or_platform_changes(self):
        marker = '11111111-1111-1111-1111-111111111111'
        config = f'description: Old notes proxmenux-instance={marker}\n'.encode()
        record = {
            'vmid': 200, 'status': 'installed', 'installation_id': marker,
            'deployment': {'mounts': [], 'devices': []},
            'observed': {'config': config.decode(), 'config_sha256': sha(config)},
        }
        with self.assertRaises(ValueError):
            reconcile.propose(record, b'description: Different instance\n')
        changed = f'description: New notes proxmenux-instance={marker}\narch: arm64\n'.encode()
        with self.assertRaises(ValueError):
            reconcile.propose(record, changed)
        with self.assertRaises(ValueError):
            reconcile.transaction.external_changes(record, changed)

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


class EnvironmentAdoptionTests(unittest.TestCase):
    marker = '11111111-1111-1111-1111-111111111111'

    def record(self, env):
        config = f'description: proxmenux-instance={self.marker}\nenv: {env}\n'.encode()
        return {
            'vmid': 200, 'status': 'installed', 'installation_id': self.marker,
            'deployment': {'mounts': [], 'devices': [], 'environment': [
                {'name': 'APP_PASSWORD', 'value': 'first-secret', 'sensitive': True}]},
            'observed': {'config': config.decode(), 'config_sha256': sha(config),
                         'archive_path': '/unused.tar', 'resolved_registry_digest': 'sha256:test',
                         'image': {'manifest_digest': 'sha256:test', 'defaults': {'Env': ['PATH=/bin']}}},
        }

    def propose(self, record, env):
        config = f'description: proxmenux-instance={self.marker}\nenv: {env}\n'.encode()
        with (patch.object(reconcile.instances, 'ROOT', Path('/inert')),
              patch.object(reconcile.instances, 'identity', return_value=self.marker),
              patch.object(reconcile.instances, 'location', return_value=Path(__file__)),
              patch.object(reconcile.gpu_devices, 'capture', return_value={}),
              patch.object(reconcile.host_mounts, 'capture_sources', return_value={}),
              patch.object(reconcile.transaction, 'preflight')):
            return reconcile.propose(record, config)

    def test_a_password_changed_in_proxmox_is_adopted_without_showing_it(self):
        record = self.record('PATH=/bin\0APP_PASSWORD=first-secret')
        proposal = self.propose(record, 'PATH=/bin\0APP_PASSWORD=my-own-secret\0TZ=Europe/Madrid')
        environment = proposal['candidate']['deployment']['environment']
        self.assertEqual(environment, [
            {'name': 'APP_PASSWORD', 'value': 'my-own-secret', 'sensitive': True},
            {'name': 'TZ', 'value': 'Europe/Madrid', 'sensitive': True}])
        self.assertEqual(proposal['details'], ['env APP_PASSWORD: value changed in Proxmox',
                                               'env TZ: added in Proxmox'])
        self.assertNotIn('my-own-secret', str(proposal['details']))
        self.assertEqual(record['deployment']['environment'][0]['value'], 'first-secret')

    def test_reordered_variables_need_no_decision(self):
        record = self.record('PATH=/bin\0APP_PASSWORD=first-secret')
        proposal = self.propose(record, 'APP_PASSWORD=first-secret\0PATH=/bin')
        self.assertEqual(proposal['details'], [])

    def test_an_image_default_removed_in_proxmox_comes_back_with_its_value(self):
        record = self.record('PATH=/bin\0APP_PASSWORD=first-secret')
        proposal = self.propose(record, 'APP_PASSWORD=first-secret')
        self.assertFalse(proposal['review'])
        self.assertNotIn('PATH', [item['name'] for item in proposal['candidate']['deployment']['environment']])

    def test_removing_a_saved_variable_removes_it_from_the_contract(self):
        record = self.record('PATH=/bin\0APP_PASSWORD=first-secret')
        proposal = self.propose(record, 'PATH=/bin')
        self.assertEqual(proposal['candidate']['deployment']['environment'], [])
        self.assertEqual(proposal['details'], ['env APP_PASSWORD: removed in Proxmox'])

    def test_other_changes_next_to_the_variables_are_still_refused(self):
        record = self.record('PATH=/bin')
        config = (f'description: proxmenux-instance={self.marker}\nenv: PATH=/bin\0A=1\n'
                  'arch: arm64\n').encode()
        with (patch.object(reconcile.instances, 'identity', return_value=self.marker),
              self.assertRaisesRegex(ValueError, 'arch')):
            reconcile.propose(record, config)


class OverlapMessageTests(unittest.TestCase):
    def test_the_refusal_names_both_paths(self):
        from test_modify_review import installation
        saved, config = installation()
        candidate = copy.deepcopy(saved)
        volume = {'type': 'managed-volume', 'source': 'local-lvm', 'size_gb': 1, 'backup': True, 'read_only': False}
        candidate['deployment']['mounts'] = [dict(volume, container_path='/source'),
                                             dict(volume, container_path='/source/archivos')]
        with self.assertRaisesRegex(ValueError, '/source/archivos - /source$'):
            reconcile.transaction.preflight(saved, candidate, config)


if __name__ == '__main__':
    unittest.main()
