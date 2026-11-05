"""Proxmox tags can change without preventing OCI management or being lost."""
import copy
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))

import oci_instance_reconcile as reconcile
import oci_instance_transaction as transaction
from oci_installation_state import sha

MARKER = '11111111-1111-4111-8111-111111111111'
BASE = (f'description: proxmenux-instance={MARKER}\n'
        'rootfs: local-lvm:vm-200-disk-0,size=8G\n'
        'unprivileged: 1\ncores: 2\nmemory: 512\n'
        'net0: name=eth0,bridge=vmbr0,hwaddr=02:00:00:00:00:01,ip=dhcp\n'
        'net1: name=eth1,bridge=vmbr1,ip=dhcp\nstartup: order=20\n').encode()


def config(tags):
    return BASE + (f'tags: {tags}\n'.encode() if tags is not None else b'')


def record(tags='oci;proxmenux'):
    before = config(tags)
    return {
        'schema_version': 1, 'vmid': 200, 'status': 'installed',
        'installation_id': MARKER,
        'template': {'id': 'test-app', 'container_contract': {'volumes': []}},
        'deployment': {
            'vmid': 200, 'rootfs': {'storage': 'local-lvm', 'size_gb': 8},
            'network': {}, 'resources': {'cores': 2, 'memory_mb': 512},
            'mounts': [], 'devices': [],
        },
        'observed': {
            'config': before.decode(), 'config_sha256': sha(before),
            'image': {'architecture': 'amd64', 'manifest_digest': 'sha256:old',
                      'defaults': {'Volumes': {}}},
        },
    }


class ExternalTagsTests(unittest.TestCase):
    def test_adding_editing_reordering_and_removing_tags_need_no_adoption(self):
        for old, new in ((None, 'homelab'), ('oci;proxmenux', 'homelab;oci;proxmenux'),
                         ('oci;proxmenux', 'proxmenux;oci'), ('oci;proxmenux', None),
                         ('oci;proxmenux', '')):
            with self.subTest(old=old, new=new):
                saved, current = record(old), config(new)
                self.assertIsNone(reconcile.propose(saved, current))
                self.assertEqual(transaction.external_changes(saved, current), {})

    def test_tags_can_change_together_with_cpu_and_memory(self):
        current = config('homelab').replace(b'cores: 2', b'cores: 4').replace(b'memory: 512', b'memory: 2048')
        self.assertIsNone(reconcile.propose(record(), current))
        self.assertEqual(transaction.external_changes(record(), current), {'cores': 4, 'memory': 2048})

    def test_tag_changes_do_not_bypass_identity_or_network_checks(self):
        current = config('homelab').replace(MARKER.encode(), b'22222222-2222-4222-8222-222222222222')
        with self.assertRaises(ValueError):
            reconcile.propose(record(), current)
        with self.assertRaises(ValueError):
            transaction.external_changes(record(), current + b'arch: arm64\n')

    def test_new_volume_still_requires_adoption_when_tags_also_change(self):
        saved = record()
        current = config('homelab') + b'mp0: local-lvm:vm-200-disk-1,mp=/data,size=8G,backup=1\n'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / '200/oci-compose.json'
            path.parent.mkdir()
            path.write_text(json.dumps(saved))
            with patch.object(reconcile.instances, 'ROOT', root):
                proposal = reconcile.propose(saved, current)
            self.assertEqual(proposal['candidate']['deployment']['mounts'][0]['container_path'], '/data')
            self.assertEqual(len(proposal['details']), 1)
            self.assertEqual(json.loads(path.read_text()), saved)


    def test_a_vlan_tag_set_in_proxmox_is_taken_into_the_record(self):
        for saved_net, current_net, expected in ((b'ip=dhcp\nnet1', b'ip=dhcp,tag=4\nnet1', 4),
                                                 (b'ip=dhcp,tag=4\nnet1', b'ip=dhcp\nnet1', None)):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                saved = record()
                before = config('oci;proxmenux').replace(b'ip=dhcp\nnet1', saved_net)
                saved['observed'].update(config=before.decode(), config_sha256=sha(before))
                root = Path(folder)
                path = root / '200/oci-compose.json'
                path.parent.mkdir()
                path.write_text(json.dumps(saved))
                current = before.replace(saved_net, current_net)
                with patch.object(reconcile.instances, 'ROOT', root):
                    proposal = reconcile.propose(saved, current)
                self.assertEqual(proposal['candidate']['deployment']['network']['vlan_tag'], expected)
                self.assertEqual(proposal['details'], [])

    def test_a_host_directory_taken_away_in_proxmox_leaves_the_record(self):
        saved = record()
        before = config('oci;proxmenux') + b'mp0: /srv/share,mp=/share,backup=0\n'
        saved['observed'].update(config=before.decode(), config_sha256=sha(before))
        saved['deployment']['mounts'] = [{'type': 'host-bind', 'container_path': '/share', 'source': '/srv/share'}]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / '200/oci-compose.json'
            path.parent.mkdir()
            path.write_text(json.dumps(saved))
            with patch.object(reconcile.instances, 'ROOT', root):
                proposal = reconcile.propose(saved, config('oci;proxmenux'))
        self.assertEqual(proposal['candidate']['deployment']['mounts'], [])
        self.assertFalse(proposal['review'])

    def test_a_data_volume_taken_away_in_proxmox_still_stops_the_update(self):
        saved = record()
        before = config('oci;proxmenux') + b'mp0: local-lvm:vm-200-disk-1,mp=/data,size=8G,backup=1\n'
        saved['observed'].update(config=before.decode(), config_sha256=sha(before))
        with self.assertRaisesRegex(ValueError, 'mp0'):
            reconcile.propose(saved, config('oci;proxmenux'))

    def test_a_network_changed_in_proxmox_is_taken_into_the_record(self):
        current = config('oci;proxmenux').replace(b'bridge=vmbr0', b'bridge=vmbr9')
        self.assertEqual(transaction.external_changes(record(), current), {'bridge': 'vmbr9'})
        self.assertEqual(transaction.external_changes(record(), current, adopt=False), {})


class Prepared(Exception):
    """Stop a mocked transaction before it can stop or modify any container."""


class TagReplayTests(unittest.TestCase):
    def prepare(self, folder, tags, operation, coordinated=None):
        current, saved = config(tags), record()
        archive = folder / 'image.tar'
        archive.write_bytes(b'fixture')
        states = []

        def checkpoint(_path, state, phase):
            self.assertEqual(phase, 'prepared')
            states.append(copy.deepcopy(state))
            raise Prepared()

        def command(*args):
            if args[:2] == ('pct', 'config'):
                return current
            if args[:3] == ('pvesh', 'get', '/cluster/ha/resources'):
                return b'[]'
            if args[:2] == ('pct', 'status'):
                return b'status: running'
            self.fail(f'Unexpected host command: {args}')

        proposal = {'operation': 'recreate', 'candidate': copy.deepcopy(saved)} if operation == 'recreate' else None
        image = {'architecture': 'amd64', 'os': 'linux', 'manifest_digest': 'sha256:new', 'defaults': {}}
        with (patch.object(transaction.instances, 'read', return_value=saved),
              patch.object(transaction, 'run', side_effect=command),
              patch.object(transaction, 'check_archive'),
              patch.object(transaction, 'image_from_archive', return_value=image),
              patch.object(transaction.work_backup, 'locate', side_effect=lambda directory, *_: directory),
              patch.object(transaction, 'open_log'),
              patch.object(transaction, 'checkpoint', side_effect=checkpoint),
              redirect_stdout(io.StringIO()), self.assertRaises(Prepared)):
            transaction.apply(folder, 200, archive, operation, proposal=proposal, coordinated=coordinated)
        return states[0]

    @unittest.skipUnless(shutil.which('bash') and shutil.which('jq'), 'bash and jq are needed')
    def test_update_and_modify_replay_current_tags_including_no_tags(self):
        installer = (ROOT / 'remote/install_oci.sh').read_text()
        function = re.search(r'^apply_kept_settings\(\) \{\n.*?^\}\n', installer, re.M | re.S)
        self.assertIsNotNone(function)
        for operation in ('update', 'recreate'):
            for tags in ('homelab;oci;proxmenux', 'oci', None, ''):
                with self.subTest(operation=operation, tags=tags), tempfile.TemporaryDirectory() as name:
                    folder = Path(name)
                    state = self.prepare(folder, tags, operation)
                    kept = state['runtime_deployment']['kept_proxmox_settings']
                    deployment = folder / 'deployment.json'
                    deployment.write_text(json.dumps({'kept_proxmox_settings': kept}))
                    calls = folder / 'calls'
                    script = '''
pct() { printf '%s\\0' "$@" >> "$CALLS"; printf '\\n' >> "$CALLS"; }
oci_quiet() { "$@"; }
translate() { printf '%s' "$1"; }
die() { printf '%s\\n' "$*" >&2; exit 1; }
'''
                    done = subprocess.run(['bash', '-euc', script + function.group(0) + '\napply_kept_settings'],
                                          env=dict(os.environ, VMID='200', DEPLOYMENT_FILE=str(deployment), CALLS=str(calls)),
                                          capture_output=True, text=True)
                    self.assertEqual(done.returncode, 0, done.stderr)
                    commands = [line.split(b'\0')[:-1] for line in calls.read_bytes().splitlines()]
                    expected = [b'set', b'200', b'--tags', tags.encode()] if tags else [b'set', b'200', b'--delete', b'tags']
                    self.assertIn(expected, commands)
                    self.assertIn([b'set', b'200', b'--net1', b'name=eth1,bridge=vmbr1,ip=dhcp'], commands)
                    self.assertIn([b'set', b'200', b'--startup', b'order=20'], commands)

    def test_stack_operations_also_preserve_tags_and_their_absence(self):
        for operation in ('update', 'recreate'):
            for tags in ('homelab;oci', None, ''):
                with self.subTest(operation=operation, tags=tags), tempfile.TemporaryDirectory() as name:
                    state = self.prepare(Path(name), tags, operation, coordinated={'stack': 'test'})
                    self.assertEqual(state['preserved_stack_config']['tags'], tags or '')

    @unittest.skipUnless(shutil.which('bash') and shutil.which('jq'), 'bash and jq are needed')
    def test_native_stack_check_accepts_tag_edits_and_nothing_else(self):
        saved = record()
        instances = transaction.instances
        for new in ('homelab;oci;proxmenux', 'proxmenux;oci', '', None):
            with self.subTest(new=new):
                self.assertTrue(instances.same_config_except_notes(saved, config(new), ignore_tags=True))
                self.assertFalse(instances.same_config_except_notes(saved, config(new)))
        changed = config('homelab').replace(b'cores: 2', b'cores: 4')
        self.assertFalse(instances.same_config_except_notes(saved, changed, ignore_tags=True))
        other = config('homelab').replace(MARKER.encode(), b'22222222-2222-4222-8222-222222222222')
        self.assertFalse(instances.same_config_except_notes(saved, other, ignore_tags=True))
        source = (ROOT / 'remote/oci_stack_native.py').read_text()
        self.assertIn('same_config_except_notes(record, config, ignore_tags=True)', source)

    def test_installer_still_refuses_unsupported_kept_settings(self):
        installer = (ROOT / 'remote/install_oci.sh').read_text()
        function = re.search(r'^apply_kept_settings\(\) \{\n.*?^\}\n', installer, re.M | re.S).group(0)
        with tempfile.TemporaryDirectory() as name:
            deployment = Path(name) / 'deployment.json'
            deployment.write_text(json.dumps({'kept_proxmox_settings': {'unprivileged': '0'}}))
            script = '''
oci_quiet() { echo 'must not run' >&2; exit 99; }
translate() { printf '%s' "$1"; }
die() { printf '%s\\n' "$*" >&2; exit 1; }
'''
            done = subprocess.run(['bash', '-euc', script + function + '\napply_kept_settings'],
                                  env=dict(os.environ, VMID='200', DEPLOYMENT_FILE=str(deployment)),
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 1)
            self.assertIn('Unsupported kept setting: unprivileged', done.stderr)
            self.assertNotIn('must not run', done.stderr)


if __name__ == '__main__':
    unittest.main()
