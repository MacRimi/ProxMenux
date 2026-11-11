"""Avoid redundant work without bypassing stack recovery or archive integrity."""
import copy
import gzip
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
import oci_stack_transaction as tx
import oci_instance_transaction as member
import oci_stack_native as native


class Adapter:
    def __init__(self, unchanged=(), fail=None):
        self.unchanged = set(unchanged)
        self.events = []
        self.fail = fail

    def validate(self, plan): pass
    def is_running(self, vmid): return True
    def prepare(self, record, operation):
        vmid = record['vmid']
        if self.fail == ('prepare', vmid): raise RuntimeError('registry unavailable')
        return {'archive': '/image.tar', 'unchanged': vmid in self.unchanged and operation == 'update'}
    def stop(self, vmid): self.events.append(('stop', vmid))
    def backup(self, vmid, identity):
        self.events.append(('backup', vmid))
        return {'archive': f'/backup-{vmid}'}
    def verify_backups(self, backups): self.events.append(('verified', len(backups)))
    def replace(self, vmid, prepared, identity): self.events.append(('replace', vmid))
    def start(self, vmid): self.events.append(('start', vmid))
    def healthcheck(self, vmid):
        if self.fail == ('health', vmid): raise RuntimeError('not ready')
    def validate_candidates(self, state): pass
    def restore_running_state(self, running, order): self.events.append(('running', tuple(order)))
    def publish(self, state): self.events.append(('publish', None))
    def restore(self, vmid, backup, identity): self.events.append(('restore', vmid))
    def restore_contracts(self, plan, identity): pass
    def finalize(self, state): self.events.append(('finalize', state['phase']))


class SelectiveStackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'transaction.json'
        self.plan = {'operation': 'update', 'primary_vmid': 9600,
                     'members': [{'vmid': 9600}, {'vmid': 9601}],
                     'start_order': [9601, 9600], 'stop_order': [9600, 9601]}

    def run_plan(self, adapter):
        with patch.object(tx.member_tx, 'report_error'):
            return tx.execute(self.path, adapter, self.plan)

    def test_all_unchanged_has_no_downtime_backups_replacement_or_publication(self):
        adapter = Adapter([9600, 9601])
        state = self.run_plan(adapter)
        self.assertTrue(state['no_change'])
        self.assertFalse(state['stop_intent'])
        self.assertFalse(state['replacement_intent'])
        self.assertEqual(adapter.events, [('finalize', 'committed')])

    def test_only_changed_member_is_replaced_but_all_are_backed_up(self):
        adapter = Adapter([9601])
        self.run_plan(adapter)
        self.assertEqual([x for x in adapter.events if x[0] == 'replace'], [('replace', 9600)])
        self.assertEqual([x for x in adapter.events if x[0] == 'backup'], [('backup', 9601), ('backup', 9600)])
        self.assertLess(adapter.events.index(('backup', 9600)), adapter.events.index(('replace', 9600)))

    def test_failed_candidate_restores_even_the_unchanged_database(self):
        adapter = Adapter([9601], ('health', 9600))
        with self.assertRaisesRegex(RuntimeError, 'not ready'): self.run_plan(adapter)
        self.assertEqual([x for x in adapter.events if x[0] == 'restore'], [('restore', 9601), ('restore', 9600)])
        self.assertEqual(json.loads(self.path.read_text())['phase'], 'rolled-back')

    def test_registry_failure_does_not_stop_any_guest(self):
        adapter = Adapter([9601], ('prepare', 9600))
        with self.assertRaisesRegex(RuntimeError, 'registry'): self.run_plan(adapter)
        self.assertEqual(adapter.events, [('finalize', 'rolled-back')])

    def test_recreate_still_replaces_every_member(self):
        self.plan['operation'] = 'recreate'
        adapter = Adapter([9600, 9601])
        self.run_plan(adapter)
        self.assertEqual([x for x in adapter.events if x[0] == 'replace'], [('replace', 9601), ('replace', 9600)])

    def test_recovery_of_a_noop_does_not_stop_any_guest(self):
        self.run_plan(Adapter([9600, 9601]))
        adapter = Adapter()
        tx.execute(self.path, adapter)
        self.assertEqual(adapter.events, [('finalize', 'committed')])

    def test_phase_timings_are_kept_in_the_journal(self):
        state = self.run_plan(Adapter([9601]))
        self.assertTrue({'preparing', 'backing-up', 'replacing', 'checking'} <= state['phase_seconds'].keys())
        self.assertTrue(all(t >= 0 for t in state['phase_seconds'].values()))




class DataHolderTests(unittest.TestCase):
    def test_holder_has_only_empty_directories_and_no_network_or_candidate_image(self):
        import tarfile
        with tempfile.TemporaryDirectory() as folder:
            def create(*args):
                self.assertEqual(args[:3], ('pct', 'create', '9661'))
                archive = Path(args[3])
                self.assertLessEqual(archive.stat().st_size, 10240)
                with tarfile.open(archive) as tar:
                    self.assertTrue(all(entry.isdir() for entry in tar))
                    self.assertEqual(set(tar.getnames()), {'etc', 'dev', 'proc', 'sys', 'tmp'})
                self.assertNotIn('--net0', args)
                self.assertEqual(args[args.index('--rootfs')+1], 'local-zfs:1')
                self.assertEqual(args[args.index('--arch')+1], 'arm64')
                self.assertEqual(args[args.index('--onboot')+1], '0')
                self.assertIn('proxmenux-transaction=identity', args)
            with patch.object(member, 'run', side_effect=create) as run:
                member.create_data_holder(9661, 'local-zfs', 'identity', Path(folder), 'arm64')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_failed_creation_removes_only_its_temporary_archive_and_can_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(member, 'run', side_effect=RuntimeError('storage full')):
                with self.assertRaises(RuntimeError):
                    member.create_data_holder(9661, 'storage', 'id', Path(folder))
            self.assertEqual(list(Path(folder).iterdir()), [])
            with patch.object(member, 'run'):
                member.create_data_holder(9661, 'storage', 'id', Path(folder))


class ScopedValidationTests(unittest.TestCase):
    def test_member_checks_query_only_that_config_but_full_checks_query_every_member(self):
        with tempfile.TemporaryDirectory() as folder:
            records = [{'vmid': v, 'installation_id': str(v), 'deployment': {},
                        'stack': {'deployment': {'services': []}}} for v in (9662, 9663, 9664)]
            adapter = native.NativeAdapter(Path(folder), Path(folder)/'journal',
                {'primary_vmid': 9662, 'members': records})
            configs = []
            def command(*args):
                if args[0] == 'pvesh':
                    return json.dumps([{'vmid': r['vmid'], 'type': 'lxc', 'node': native.socket.gethostname().split('.')[0]} for r in records]).encode()
                configs.append(int(args[2]))
                return ('description: proxmenux-instance='+args[2]+'\n').encode()
            with patch.object(native.instances, 'command', side_effect=command), \
                    patch.object(native.instances, 'identity', side_effect=lambda config: config.decode().split('=')[1].strip()), \
                    patch.object(native.instances, 'read', side_effect=lambda root, vmid: {'installation_id': str(vmid)}), \
                    patch.object(native.instances, 'same_config_except_notes', return_value=True), \
                    patch.object(native.public_routes, 'check'):
                adapter.validate(adapter.plan, [9663])
                self.assertEqual(configs, [9663])
                configs.clear()
                adapter.validate(adapter.plan)
                self.assertEqual(configs, [9662, 9663, 9664])

    def test_changed_identity_is_still_rejected_in_targeted_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            record = {'vmid': 9662, 'installation_id': 'original', 'deployment': {},
                      'stack': {'deployment': {'services': []}}}
            adapter = native.NativeAdapter(Path(folder), Path(folder)/'journal',
                {'primary_vmid': 9662, 'members': [record]})
            inventory = json.dumps([{'vmid': 9662, 'type': 'lxc', 'node': native.socket.gethostname().split('.')[0]}]).encode()
            with patch.object(native.instances, 'command', side_effect=[inventory, b'description: proxmenux-instance=replaced\n']), \
                    patch.object(native.public_routes, 'check'), self.assertRaisesRegex(ValueError, 'identity'):
                adapter.validate(adapter.plan, [9662])


class PreparationTests(unittest.TestCase):
    def test_pending_records_are_marked_once_not_once_per_image(self):
        records = [{'vmid': v, 'installation_id': str(v), 'observed': {'image': {}, 'resolved_registry_digest': 'saved'},
                    'stack': {'deployment': {'services': []}}} for v in (9662, 9663)]
        adapter = native.NativeAdapter(Path('/registry'), Path('/journal'), {'primary_vmid': 9662, 'members': records})
        with patch.object(native.instances, 'read', return_value={}), patch.object(native.instances, 'write') as write, \
                patch.object(native.instances, 'location', return_value=Path('/registry/r')), \
                patch.object(native.instances, 'command', return_value=b'arch: amd64\n'), \
                patch.object(native, 'resolve_archive', return_value=(None, 'digest')):
            for record in records: adapter.prepare(record, 'update')
        self.assertEqual(write.call_count, 2)

    def test_unchanged_completion_job_is_prepared_again_when_another_image_changes(self):
        record = {'vmid': 9662, 'stack': {'deployment': {'services': [
            {'vmid': 9662, 'healthcheck': {'type': 'completed'}}]}}}
        adapter = native.NativeAdapter(Path('/registry'), Path('/journal'), {'primary_vmid': 9662, 'members': [record]})
        state = {'prepared': {'9662': {'unchanged': True, 'digest': 'sha256:fixed'}}}
        with patch.object(adapter, 'prepare', return_value={'archive': 'job.tar'}) as prepare:
            adapter.prepare_changed_stack(state)
        prepare.assert_called_once_with(adapter.records[9662], 'update', force=True, required_digest='sha256:fixed')
        self.assertEqual(state['prepared']['9662'], {'archive': 'job.tar'})


class PhaseTimingTests(unittest.TestCase):
    def test_recovery_does_not_count_time_from_another_process(self):
        state = {'phase': 'replacing', 'phase_clock_id': 'old-process', 'phase_started': 0}
        member.time_phase(state, 'recovering')
        self.assertNotIn('phase_seconds', state)
        self.assertEqual(state['phase_clock_id'], member._phase_clock_id)


class RecoveryCoverageTests(unittest.TestCase):
    def recover_same_config(self, coordinated):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            journal = folder / 'transaction.json'
            backup = folder / 'backup.zst'
            backup.write_bytes(b'verified backup fixture')
            state = {'id': 'transaction', 'vmid': 9662, 'phase': 'backup-ready',
                     'record': {'installation_id': 'original'}, 'before_config': 'arch: amd64\n',
                     'backup': str(backup), 'backup_sha256': 'sha', 'was_running': False}
            if coordinated: state['coordinated'] = {'id': 'stack'}
            journal.write_text(json.dumps(state))
            record = {'installation_id': 'original', 'transaction_id': 'transaction',
                      'pending_transaction': str(journal)}
            original_exists = Path.exists
            def exists(path):
                return True if str(path) == '/etc/pve/lxc/9662.conf' else original_exists(path)
            inventory = [{'vmid': 9662, 'type': 'lxc', 'node': member.socket.gethostname().split('.')[0]}]
            def run(*args):
                return json.dumps(inventory).encode() if args[0] == 'pvesh' else b'arch: amd64\n'
            with patch.object(Path, 'exists', exists), patch.object(member, 'run', side_effect=run), \
                    patch.object(member.instances, 'read', return_value=record), \
                    patch.object(member.instances, 'write'), patch.object(member, 'owned'), \
                    patch.object(member, 'release_stage'), patch.object(member.host_mounts, 'verify_sources'), \
                    patch.object(member.gpu_devices, 'verify'), \
                    patch.object(member, 'filehash', side_effect=RuntimeError('full data restore required')) as hashing:
                if coordinated:
                    with self.assertRaisesRegex(RuntimeError, 'full data restore required'):
                        member.recover(folder, journal)
                    hashing.assert_called_once_with(str(backup))
                else:
                    member.recover(folder, journal)
                    hashing.assert_not_called()

    def test_coordinated_recovery_does_not_treat_same_config_as_untouched_data(self):
        self.recover_same_config(True)

    def test_standalone_untouched_recovery_keeps_its_existing_shortcut(self):
        self.recover_same_config(False)


if __name__ == '__main__': unittest.main()
