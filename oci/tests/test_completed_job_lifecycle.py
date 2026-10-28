"""Completion proofs survive native staging, rollback and renumbered restore."""
import copy
import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))
import oci_compose_jobs as jobs
import oci_instances as instances
import oci_stack_native as native
import oci_stack_plan as plans
import oci_restore_recovery as recovery

MAIN = '11111111-1111-4111-8111-111111111111'
JOB = '22222222-2222-4222-8222-222222222222'
DB = '33333333-3333-4333-8333-333333333333'
OLD = 'sha256:' + 'a' * 64
NEW = 'sha256:' + 'b' * 64
CONFIG = 'rootfs: local-zfs:subvol-4901-disk-0,size=8G\nunprivileged: 1\nentrypoint: migrate\n'
SPEC = {'installation_id': JOB, 'image_digest': OLD,
        'expected_config_fingerprint': jobs.config_fingerprint(CONFIG), 'timeout_seconds': 300}
CHECK = {'type': 'completed', 'timeout_seconds': 300, 'job': SPEC}


def fixture():
    services = [{'vmid': 4902, 'name': 'database', 'kind': 'postgres', 'healthcheck': {'type': 'running', 'timeout_seconds': 120}},
                {'vmid': 4901, 'name': 'migration', 'healthcheck': copy.deepcopy(CHECK)},
                {'vmid': 4900, 'name': 'web', 'frontend': True, 'healthcheck': {'type': 'running', 'timeout_seconds': 120}}]
    records = []
    for vmid, identity in ((4900, MAIN), (4901, JOB), (4902, DB)):
        records.append({'schema_version': 1, 'vmid': vmid, 'installation_id': identity, 'status': 'installed',
                        'deployment': {'onboot': False, 'mounts': []},
                        'observed': {'resolved_registry_digest': OLD, 'image': {'defaults': {}}},
                        'stack_member': {'stack_id': MAIN, 'primary_vmid': 4900}})
    records[1]['deployment']['execution_mode'] = 'one-shot'
    records[0]['stack'] = {'id': MAIN, 'deployment': {'stack_name': 'test', 'services': services},
                           'members': copy.deepcopy(records)}
    plan = {'operation': 'update', 'primary_vmid': 4900, 'members': records,
            'start_order': [4902, 4901, 4900], 'stop_order': [4900, 4901, 4902]}
    return plan


class NativeCompletedJobs(unittest.TestCase):
    def adapter(self):
        return native.NativeAdapter(Path('/unused'), Path('/unused/journal'), fixture())

    def test_stopped_job_is_not_accepted_without_an_authenticated_success(self):
        adapter = self.adapter()
        with patch.object(adapter, '_job_contract'), \
             patch.object(jobs, 'ensure_completed', side_effect=jobs.JobError('exit 7')), \
             patch.object(adapter, 'is_running', return_value=False), \
             patch.object(native.member_tx, 'run') as run:
            with self.assertRaisesRegex(jobs.JobError, 'exit 7'):
                adapter.healthcheck(4901)
        run.assert_not_called()

    def test_job_start_calls_completion_runner_not_pct_start(self):
        adapter = self.adapter()
        with patch.object(adapter, 'validate'), patch.object(adapter, '_job_contract'), \
             patch.object(jobs, 'ensure_completed', return_value={'status': 'completed'}) as complete, \
             patch.object(native.member_tx, 'run') as run:
            adapter.start(4901)
        complete.assert_called_once_with(4901, SPEC, force=False)
        run.assert_not_called()

    def test_database_host_bind_cannot_be_acknowledged_as_a_migration_backup(self):
        adapter = self.adapter()
        adapter.acknowledge = True
        adapter.records[4902]['deployment']['mounts'] = [{'type': 'host-bind', 'source': '/database'}]
        with self.assertRaisesRegex(ValueError, 'Migration jobs'):
            adapter._migration_backups()

    def test_unknown_internal_backend_host_bind_is_not_assumed_safe(self):
        adapter = self.adapter()
        adapter.services[4902]['kind'] = 'application'
        adapter.records[4902]['deployment']['mounts'] = [{'type': 'host-bind', 'source': '/unknown'}]
        with self.assertRaisesRegex(ValueError, 'Migration jobs'):
            adapter._migration_backups()

    def test_image_database_fingerprint_detects_an_unknown_tagged_repository(self):
        adapter = self.adapter()
        adapter.services[4902].update(kind='application', frontend=True)
        adapter.records[4902]['observed']['image']['defaults']['Env'] = ['PG_MAJOR=16']
        adapter.records[4902]['deployment']['mounts'] = [{'type': 'host-bind', 'source': '/database'}]
        with self.assertRaisesRegex(ValueError, 'Migration jobs'):
            adapter._migration_backups()

    def test_primary_app_shared_files_and_readonly_backend_are_not_database_write_risks(self):
        adapter = self.adapter()
        adapter.records[4900]['deployment']['mounts'] = [{'type': 'host-bind', 'source': '/app'}]
        adapter.records[4902]['deployment']['mounts'] = [{'type': 'host-bind', 'source': '/db', 'read_only': True}]
        adapter._migration_backups()

    def test_rollback_checks_database_before_rerunning_old_job_then_starts_main(self):
        adapter = self.adapter()
        events = []
        with patch.object(adapter, 'state', return_value={'phase': 'recovering', 'replacement_intent': True}), \
             patch.object(adapter, 'start', side_effect=lambda vmid: events.append(('start', vmid))), \
             patch.object(adapter, 'healthcheck', side_effect=lambda vmid: events.append(('healthy', vmid))), \
             patch.object(adapter, '_ensure_job', side_effect=lambda vmid, force=False: events.append(('job', vmid, force))), \
             patch.object(adapter, 'stop', side_effect=lambda vmid: events.append(('stop', vmid))):
            adapter.restore_running_state({'4900': True, '4901': False, '4902': True}, [4902, 4901, 4900])
        self.assertLess(events.index(('healthy', 4902)), events.index(('job', 4901, True)))
        self.assertLess(events.index(('job', 4901, True)), events.index(('start', 4900)))
        self.assertNotIn(('start', 4901), events)

    def job_contract(self, tamper=False, rollback=False):
        adapter = self.adapter()
        original = {'schema': 1, 'stack': 'test', 'dependencies': [
            {'vmid': s['vmid'], 'label': s['name'], 'healthcheck': copy.deepcopy(s['healthcheck'])}
            for s in adapter.services.values() if s['vmid'] != 4900]}
        contract = copy.deepcopy(original)
        if tamper:
            contract['dependencies'][0]['label'] = 'externally changed'
        state = {'id': 'operation', 'phase': 'recovering' if rollback else 'starting'}
        writes = []
        path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0),
                               read_text=lambda: json.dumps(contract))
        staged = copy.deepcopy(adapter.records[4901])
        staged['observed']['resolved_registry_digest'] = OLD if rollback else NEW
        updated = {**SPEC, 'image_digest': OLD if rollback else NEW,
                   'expected_config_fingerprint': 'c' * 64}
        def write(target, value):
            writes.append(copy.deepcopy(value))
            if target is path:
                contract.clear(); contract.update(copy.deepcopy(value))
            else:
                state.clear(); state.update(copy.deepcopy(value))
        with patch.object(native, 'Path', return_value=path), \
             patch.object(adapter, 'state', side_effect=lambda: copy.deepcopy(state)), \
             patch.object(instances, 'write', side_effect=write), \
             patch.object(instances, 'read', return_value=staged), \
             patch.object(native.member_tx, 'owned', return_value=CONFIG.encode()), \
             patch.object(jobs, 'job_spec_from_record', return_value=updated) as bind:
            if tamper:
                with self.assertRaisesRegex(ValueError, 'hook and the stack recipe differ'):
                    adapter._job_contract()
                bind.assert_not_called()
                self.assertEqual(writes, [])
                return
            adapter._job_contract(rollback=rollback)
        self.assertEqual(bind.call_args.args[0]['observed']['resolved_registry_digest'], updated['image_digest'])
        self.assertEqual(adapter.services[4901]['healthcheck']['job'], updated)
        self.assertEqual(contract['dependencies'][1]['healthcheck']['job'], updated)
        self.assertIn('job_hook_contract_intent', writes[0])
        self.assertNotIn('job_hook_contract_intent', state)

    def test_new_image_binds_new_job_digest_before_main_hook(self):
        self.job_contract()

    def test_rollback_rebinds_old_image_with_actual_restored_config(self):
        self.job_contract(rollback=True)

    def test_concurrent_hook_edit_is_not_overwritten(self):
        self.job_contract(tamper=True)

    def test_job_hook_intent_survives_orchestrator_rewriting_its_main_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.adapter()
            adapter.journal = Path(directory) / 'transaction.json'
            adapter.journal.write_text(json.dumps({'id': 'operation', 'phase': 'starting'}))
            contract = {'schema': 1, 'stack': 'test', 'dependencies': [
                {'vmid': s['vmid'], 'label': s['name'], 'healthcheck': copy.deepcopy(s['healthcheck'])}
                for s in adapter.services.values() if s['vmid'] != 4900]}
            hook = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0),
                                   read_text=lambda: json.dumps(contract))
            staged = copy.deepcopy(adapter.records[4901])
            staged['observed']['resolved_registry_digest'] = NEW
            updated = {**SPEC, 'image_digest': NEW, 'expected_config_fingerprint': 'c' * 64}
            actual_write = instances.write
            def write(path, value):
                if path is hook:
                    contract.clear(); contract.update(copy.deepcopy(value))
                else:
                    actual_write(path, value)
            with patch.object(native, 'Path', return_value=hook), \
                 patch.object(instances, 'write', side_effect=write), \
                 patch.object(instances, 'read', return_value=staged), \
                 patch.object(native.member_tx, 'owned', return_value=CONFIG.encode()), \
                 patch.object(jobs, 'job_spec_from_record', return_value=updated):
                adapter._job_contract()
                # The orchestration engine checkpoints its own original state object.
                adapter.journal.write_text(json.dumps({'id': 'operation', 'phase': 'checking'}))
                adapter._job_contract()
            marker = json.loads((Path(directory) / 'completed-job-contract.json').read_text())
            self.assertEqual(marker['operation_id'], 'operation')
            self.assertEqual(marker['job_hook_contract']['dependencies'][1]['healthcheck']['job'], updated)
            self.assertNotIn('job_hook_contract_intent', marker)



class JobPlanValidation(unittest.TestCase):
    def test_plan_preserves_database_job_main_order(self):
        fixture_plan = fixture()
        primary = fixture_plan['members'][0]
        records = {r['vmid']: r for r in fixture_plan['members']}
        plan = plans.build(primary, records, {r['vmid']: r['installation_id'] for r in records.values()}, 'update')
        self.assertEqual(plan['start_order'], [4902, 4901, 4900])

    def test_job_cannot_be_onboot_or_bound_to_another_image(self):
        for mutation in ('onboot', 'watchdog', 'mode', 'digest'):
            with self.subTest(mutation=mutation):
                value = fixture()
                records = {r['vmid']: r for r in value['members']}
                if mutation in ('onboot', 'watchdog'):
                    records[4901]['deployment'][mutation] = True
                elif mutation == 'mode':
                    records[4901]['deployment'].pop('execution_mode')
                else:
                    value['members'][0]['stack']['deployment']['services'][1]['healthcheck']['job']['image_digest'] = NEW
                with self.assertRaises(ValueError):
                    plans.build(value['members'][0], records, {r['vmid']: r['installation_id'] for r in records.values()}, 'update')


class RestoreCompletedJobs(unittest.TestCase):
    def test_only_bound_completed_contracts_are_accepted(self):
        contract = {'schema': 1, 'dependencies': [{'vmid': 4901, 'label': 'migration', 'healthcheck': copy.deepcopy(CHECK)}]}
        self.assertTrue(recovery.valid_contract(contract, {4901}))
        for field, value in (('image_digest', 'latest'), ('installation_id', 'arbitrary'),
                             ('expected_config_fingerprint', ''), ('timeout_seconds', True)):
            broken = copy.deepcopy(contract)
            broken['dependencies'][0]['healthcheck']['job'][field] = value
            self.assertFalse(recovery.valid_contract(broken, {4901}), field)

    def test_restore_never_starts_a_job_as_an_ordinary_daemon(self):
        entries = [{'vmid': vmid, 'config': 'startup: order=' + str(order), 'contract': None}
                   for order, vmid in enumerate((4902, 4901, 4900), 1)]
        plan = {'bridges': {}, 'renumbered': {}, 'restored': entries, 'hold': False, 'notes': []}
        calls = []
        def run(*args):
            calls.append(args)
            return SimpleNamespace(stdout='status: stopped', stderr='', returncode=0)
        with patch.object(recovery, 'restore_host_files'), patch.object(recovery, 'clean_format_directories'), \
             patch.object(recovery, 'register', return_value=[4902, 4901, 4900]), \
             patch.object(recovery.carried, 'carry'), \
             patch.object(recovery, 'completed_job', side_effect=lambda root, vmid: vmid == 4901), \
             patch.object(recovery, 'run', side_effect=run):
            recovery.recover(Path('/unused'), plan, start=True)
        self.assertEqual([call for call in calls if call[:2] == ('pct', 'start')],
                         [('pct', 'start', '4902'), ('pct', 'start', '4900')])

    def test_renumbered_restore_rebinds_current_config_and_invalidates_deferred_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = fixture()
            for record in plan['members']:
                instances.write(instances.location(root, record['vmid']), record)
            entry = {'vmid': 4900, 'contract': {'schema': 1}}
            restore_plan = {'restored': [entry]}
            calls = []
            def checked(*args):
                if args[:2] == ('pct', 'config'):
                    return CONFIG.replace('subvol-4901', 'subvol-NEW-4901')
                calls.append((args, json.loads(Path(args[-1]).read_text())))
                return ''
            with patch.object(recovery, 'checked', side_effect=checked):
                recovery.refresh_completed_jobs(root, restore_plan)
            restored = instances.read(root, 4901)
            main = instances.read(root, 4900)
            check = main['stack']['deployment']['services'][1]['healthcheck']
            self.assertTrue(restored['recovered_at'])
            self.assertEqual(check['job']['installation_id'], JOB)
            self.assertEqual(check['job']['image_digest'], OLD)
            self.assertNotEqual(check['job']['expected_config_fingerprint'], SPEC['expected_config_fingerprint'])
            self.assertEqual(calls[0][0][-2], '4900')
            self.assertEqual([d['vmid'] for d in calls[0][1]['dependencies']], [4902, 4901])
            self.assertTrue(recovery.completed_job(root, 4901))
            self.assertFalse(recovery.completed_job(root, 4902))


if __name__ == '__main__':
    unittest.main()
