"""Maintainer review regressions: purpose-based checks at the PVE boundary."""
from contextlib import closing
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import time
import subprocess
import json
import io
import shlex
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_plain_lxc as fixture
import plain_lxc as engine
import plain_lxc_state as state
import plain_lxc_resources as resources


class ReviewEngineTests(unittest.TestCase):
    def setUp(self):
        fixture.EngineTests.setUp(self)
        self.spec.pop('prepare_system')
    call = fixture.EngineTests.call
    create_body = fixture.EngineTests.create_body

    def test_default_creation_submits_only_native_create_without_optional_preparation(self):
        payload = self.create_body()
        result = self.call('create', **payload)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual([name for name, _ in self.api.writes], ['create'])
        self.assertEqual(self.api.boot_attempts, 0)
        self.assertNotIn('prepared', result)

    def test_default_start_explicitly_disables_rootfs_preparation(self):
        result = self.call('create', **self.create_body(start_after_create=True))
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual([name for name, _ in self.api.writes], ['create', 'start'])
        self.assertIs(self.api.writes[1][1]['expected']['prepare_system'], False)
        self.assertNotIn('prepared', result)

    def test_opt_in_preparation_runs_once_and_failure_never_boots(self):
        self.api.start_exit = 'ProxMenux preparation failed: simulated failure'
        result = self.call('create', **self.create_body(prepare_system=True, start_after_create=True))
        self.assertEqual((result['status'], result['reason']), ('partial', 'preparation_failed'))
        self.assertEqual(self.api.boot_attempts, 0)
        writes = deepcopy(self.api.writes)
        self.call('status', request_id=fixture.REQUEST_ID)
        self.assertEqual(self.api.writes, writes)

    def orphan(self, *, download=False, submission='started'):
        operation = dict(request_id=fixture.REQUEST_ID, node=fixture.NODE,
                         action='download_template' if download else 'create',
                         phase='download' if download else 'create', status='unknown',
                         fingerprint='audit', deadline=100, admitted_at=100, submission=submission)
        if download:
            operation.update(volume_id=fixture.VOLUME, sha512=fixture.CHECKSUM)
        else:
            operation.update(vmid=fixture.VMID, start_after_create=False)
        self.store.admit(operation, 'download:'+fixture.VOLUME if download else 'vmid:'+str(fixture.VMID))
        return operation

    def test_recovery_of_never_submitted_request_releases_without_pve_or_replay(self):
        self.orphan(submission='not_started')
        result = self.call('recover', request_id=fixture.REQUEST_ID, confirmed=True)
        self.assertEqual((result['status'], result['reason']), ('failed', 'recovered_not_submitted'))
        self.assertEqual(self.api.calls, [])
        self.assertEqual(self.api.writes, [])
        self.assertEqual(self.store.pending(), [])

    def test_recovery_requires_confirmation_owner_and_no_live_controller(self):
        self.orphan()
        with self.assertRaisesRegex(fixture.LxcError, '^confirmation_required$'):
            self.call('recover', request_id=fixture.REQUEST_ID, confirmed=False)
        with self.store.controller(fixture.REQUEST_ID):
            with self.assertRaisesRegex(fixture.LxcError, '^operation_controller_active$'):
                self.call('recover', request_id=fixture.REQUEST_ID, confirmed=True)
        other = fixture.Operations(self.store.directory, self.store.actor + 1)
        with self.assertRaisesRegex(fixture.LxcError, '^request_conflict$'):
            engine.execute(fixture.body('recover', request_id=fixture.REQUEST_ID, confirmed=True), self.api, other)
        self.assertEqual(self.api.writes, [])
        self.assertEqual(len(self.store.pending()), 1)

    def test_status_does_not_release_a_live_controller_between_phases(self):
        operation=self.orphan()
        upid=fixture.upid('vzcreate',fixture.VMID)
        operation.update(upid=upid)
        self.store.save(operation)
        self.api.tasks[upid]={'upid':upid,'status':'stopped','exitstatus':'OK'}
        self.api.config={'description':'ProxMenux request '+fixture.REQUEST_ID}
        with self.store.controller(fixture.REQUEST_ID):
            result=self.call('status',request_id=fixture.REQUEST_ID)
            self.assertEqual((result['status'],result['reason']),('running','controller_active'))
            self.assertEqual(len(self.store.pending()),1)
        result=self.call('status',request_id=fixture.REQUEST_ID)
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(self.store.pending(),[])
        self.assertEqual(self.api.writes,[])

    def test_unknown_submit_never_expires_and_grace_boundary_precedes_recovery_probe(self):
        self.orphan()
        original = self.api.dispatch
        probes = []
        def dispatch(action, node, params):
            if action == 'recovery_check':
                probes.append(params)
                return {'safe': 1, 'present': 0}
            return original(action, node, params)
        with patch.object(self.api, 'dispatch', side_effect=dispatch):
            for now in (399, 400):
                with patch.object(engine.time, 'time', return_value=now):
                    if now == 399:
                        result = self.call('recover', request_id=fixture.REQUEST_ID, confirmed=True)
                        self.assertEqual(result['reason'], 'recovery_wait')
                        self.assertEqual(probes, [])
                    else:
                        result = self.call('recover', request_id=fixture.REQUEST_ID, confirmed=True)
                        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(probes), 1)
        self.assertEqual(self.api.writes, [])
        self.assertEqual(self.store.pending(), [])

    def test_recovery_unavailable_keeps_reservation_and_all_resources(self):
        self.orphan()
        original = self.api.dispatch
        def dispatch(action, node, params):
            if action == 'recovery_check':
                raise fixture.LxcError('pve_unavailable')
            return original(action, node, params)
        with patch.object(self.api, 'dispatch', side_effect=dispatch), patch.object(engine.time, 'time', return_value=1000):
            result = self.call('recover', request_id=fixture.REQUEST_ID, confirmed=True)
        self.assertEqual((result['status'], result['reason']), ('unknown', 'recovery_unavailable'))
        self.assertEqual(len(self.store.pending()), 1)
        self.assertEqual(self.api.writes, [])

    def test_known_task_with_lost_status_can_use_confirmed_idle_recovery_without_replay(self):
        operation=self.orphan(); operation['upid']=fixture.upid('vzcreate',fixture.VMID); self.store.save(operation)
        self.api.task_error=True
        original=self.api.dispatch
        def dispatch(action,node,params):
            return {'safe':1,'present':0} if action=='recovery_check' else original(action,node,params)
        with patch.object(self.api,'dispatch',side_effect=dispatch),patch.object(engine.time,'time',return_value=1000):
            result=self.call('recover',request_id=fixture.REQUEST_ID,confirmed=True)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(self.store.pending(),[])
        self.assertEqual(self.api.writes,[])

    def test_known_running_task_stays_reserved_without_an_idle_probe(self):
        operation=self.orphan(); task=fixture.upid('vzcreate',fixture.VMID)
        operation['upid']=task; self.store.save(operation)
        self.api.tasks[task]={'upid':task,'status':'running'}
        with patch.object(self.api,'dispatch',side_effect=AssertionError('must not probe idle while task runs')):
            result=self.call('recover',request_id=fixture.REQUEST_ID,confirmed=True)
        self.assertEqual(result['status'],'running')
        self.assertEqual(len(self.store.pending()),1)
        self.assertEqual(self.api.writes,[])

    def test_download_recovery_checks_original_checksum_without_download_or_overwrite(self):
        self.orphan(download=True)
        original = self.api.dispatch
        def dispatch(action, node, params):
            return {'safe': 1, 'present': 1} if action == 'recovery_check' else original(action, node, params)
        with patch.object(self.api, 'dispatch', side_effect=dispatch), patch.object(engine.time, 'time', return_value=1000):
            result = self.call('recover', request_id=fixture.REQUEST_ID, confirmed=True)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.api.writes, [])
        self.assertEqual(self.store.pending(), [])

    def test_thin_and_zfs_subvol_logical_limit_can_exceed_free_but_zero_cannot(self):
        for backend in ('lvmthin', 'zfspool'):
            with self.subTest(backend=backend):
                self.api.storage[1].update(type=backend, avail=fixture.GIB)
                result = self.call('plan', spec=self.spec)
                self.assertIn('storage_overcommit', result['plan']['warnings'])
                self.api.storage[1]['avail'] = 0
                with self.assertRaisesRegex(fixture.LxcError, '^disk_space_insufficient$'):
                    self.call('plan', spec=self.spec)
                self.assertEqual(self.api.writes, [])
                self.assertFalse(self.store.path.exists())

    def test_turnkey_catalog_is_selectable_with_native_source_and_architecture(self):
        self.api.catalog.update(section='turnkeylinux', source='https://releases.turnkeylinux.org/pve',
                                location='https://releases.turnkeylinux.org/pve/'+fixture.NAME)
        context = self.call('context')
        self.assertIn(fixture.VOLUME, context['templates'])
        self.assertEqual(context['templates'][fixture.VOLUME]['origin'], 'turnkey')
        result = self.call('plan', spec=self.spec)
        self.assertEqual(result['plan']['resources']['template']['architecture'], 'amd64')
        self.assertEqual(self.api.writes, [])

    def test_real_turnkey_mirror_rows_are_listed_without_trusting_foreign_urls(self):
        from plain_lxc_pve import official_catalog
        rows=json.loads((fixture.ROOT/'.github/scripts/tests/fixtures/plain_lxc_turnkey_aplinfo.json').read_text())
        for row in rows:
            for scheme in ('https','http'):
                actual={**row,'location':scheme+row['location'][row['location'].index(':'):]}
                catalog=official_catalog([actual],'amd64')
                self.assertEqual(catalog[row['template']]['origin'],'turnkey')
                self.assertEqual(catalog[row['template']]['sha512'],row['sha512sum'])
                self.assertEqual(official_catalog([actual],'arm64'),{})
            for location in ('https://example.org/'+row['template'],
                             row['location']+'?other=1',
                             row['location'].replace('mirror.turnkeylinux.org','mirror.turnkeylinux.org.example.org'),
                             row['location'].replace('/images/proxmox/','/images/../proxmox/')):
                self.assertEqual(official_catalog([{**row,'location':location}],'amd64'),{})
            self.assertEqual(official_catalog([{**row,'source':'https://example.org'}],'amd64'),{})
        self.assertEqual(self.api.writes,[])
        self.assertFalse(self.store.path.exists())

    def test_custom_local_template_requires_explicit_arch_and_binds_archive_hash(self):
        self.api.catalog = {}
        context = self.call('context')
        self.assertEqual(context['templates'][fixture.VOLUME]['origin'], 'local')
        with self.assertRaisesRegex(fixture.LxcError, '^template_architecture_required$'):
            self.call('plan', spec=self.spec)
        custom = {**self.spec, 'template': {'volume_id':fixture.VOLUME, 'architecture':'amd64'}}
        result = self.call('plan', spec=custom)
        self.assertIn('custom_template', result['plan']['warnings'])
        self.api.file.write_bytes(b'changed local archive')
        changed = self.call('plan', spec=custom)
        self.assertNotEqual(changed['plan_hash'], result['plan_hash'])
        self.assertEqual(self.api.writes, [])

    def test_template_declared_arch_mismatch_rejects_before_any_write(self):
        spec = {**self.spec, 'template': {'volume_id':fixture.VOLUME, 'architecture':'arm64'}}
        with self.assertRaisesRegex(fixture.LxcError, '^template_architecture_mismatch$'):
            self.call('plan', spec=spec)
        self.assertEqual(self.api.writes, [])

    def test_unknown_device_is_rejected_before_admission(self):
        spec={**self.spec,'devices':[{'path':'/dev/dri/renderD128'}]}
        with self.assertRaisesRegex(fixture.LxcError, '^resource_unavailable$'):
            self.call('plan',spec=spec)
        self.assertEqual(self.api.writes,[])
        self.assertFalse(self.store.path.exists())

    def test_mount_allocations_share_a_storage_budget(self):
        self.api.storage[1].update(type='lvm',avail=12*fixture.GIB)
        spec={**self.spec,'mounts':[{'type':'volume','storage':'local-lvm','size_gib':8,'path':'/data'}]}
        with self.assertRaisesRegex(fixture.LxcError, '^disk_space_insufficient$'):
            self.call('plan',spec=spec)
        self.assertEqual(self.api.writes,[])
        self.assertFalse(self.store.path.exists())

    def test_protected_bind_source_and_overlapping_targets_have_zero_probes_or_writes(self):
        for mounts in ([{'type':'bind','source':'/etc','path':'/data'}],
                       [{'type':'volume','storage':'local-lvm','size_gib':1,'path':'/data'},
                        {'type':'volume','storage':'local-lvm','size_gib':1,'path':'/data/child'}]):
            with self.subTest(mounts=mounts):
                with self.assertRaisesRegex(fixture.LxcError, '^invalid_field$'):
                    self.call('plan',spec={**self.spec,'mounts':mounts})
                self.assertEqual(self.api.calls,[])
                self.assertEqual(self.api.writes,[])

    def test_selected_device_identity_and_bind_source_are_bound_to_plan_and_rechecked(self):
        identity = {'dev':'10','ino':'12','rdev':'226','uid':0,'gid':0,'mode':0o660}
        self.api.hardware['/dev/dri/renderD128'] = {'path':'/dev/dri/renderD128','kind':'GPU','identity':identity}
        spec = {**self.spec,'devices':[{'path':'/dev/dri/renderD128'}]}
        payload = self.create_body(**spec)
        self.assertIn('device_passthrough',payload['plan']['warnings'])
        identity['ino']='13'
        with self.assertRaisesRegex(fixture.LxcError,'^plan_changed$'):
            self.call('create',**payload)
        self.assertEqual(self.api.writes,[])
        self.assertFalse(self.store.path.exists())
        for mounts in ([{'type':'bind','source':'/mnt/review-bind','path':'/data'}],):
            with patch.object(self.api,'bind_identity',return_value={'dev':'10','ino':'11','rdev':'0','uid':0,'gid':0,'mode':0o755}):
                result=self.call('plan',spec={**self.spec,'mounts':mounts})
                self.assertIn('bind_mount',result['plan']['warnings'])
                self.assertEqual(result['plan']['resources']['attachments']['mounts'][0]['identity']['ino'],'11')
        self.assertEqual(self.api.writes,[])

    def test_unsupported_native_device_api_has_zero_probe_or_write(self):
        self.api.capabilities['devices']=0
        with patch.object(self.api,'hardware_inventory',side_effect=AssertionError('must not probe hardware')):
            with self.assertRaisesRegex(fixture.LxcError,'^resource_unsupported$'):
                self.call('plan',spec={**self.spec,'devices':[{'path':'/dev/dri/renderD128'}]})
        self.assertEqual(self.api.writes,[])
        self.assertFalse(self.store.path.exists())


STAT_DRIVER = r'''
BEGIN {
    *CORE::GLOBAL::lstat = sub {
        my ($path) = @_;
        if ($ENV{TEST_RESOURCE_STATS}) {
            my $device = $path eq '/dev/dri/renderD128';
            my $bind = $path eq '/mnt/review-bind';
            if ($device || $bind) {
                my $mode = $device ? 0020000+0660 : 0040000+0755;
                $mode = 0120000+0777 if $ENV{TEST_RESOURCE_SYMLINK};
                return (10, ($ENV{TEST_RESOURCE_CHANGED} ? 99 : $device ? 12 : 11),$mode,1,0,0,$device ? 226 : 0,0,0,0,0,4096,0);
            }
            return (10,1,0040000+0755,1,0,0,0,0,0,0,0,4096,0) if $path eq '/dev/dri';
        }
        return CORE::lstat($path);
    };
}
'''


class NativeAttachmentTests(unittest.TestCase):
    setUpClass = classmethod(fixture.PerlBridgeTests.setUpClass.__func__)
    call = fixture.PerlBridgeTests.call

    def resources(self):
        return {'mounts':[
            {'type':'volume','storage':'local-lvm','storage_type':'lvmthin','size_gib':8,'path':'/data','read_only':False,'backup':True},
            {'type':'bind','source':'/mnt/review-bind','path':'/media','read_only':True,'backup':False,
             'identity':{'dev':'10','ino':'11','rdev':'0','uid':0,'gid':0,'mode':0o755}}],
            'devices':[{'path':'/dev/dri/renderD128','uid':0,'gid':0,'mode':'0660',
                        'identity':{'dev':'10','ino':'12','rdev':'226','uid':0,'gid':0,'mode':0o660}}]}

    def test_native_start_validates_attachments_and_opt_in_mounts_only_rootfs(self):
        config={'mp0':'local-lvm:vm-240-disk-1,mp=/data,ro=0,backup=1,size=8G',
                'mp1':'/mnt/review-bind,mp=/media,ro=1,backup=0',
                'dev0':'path=/dev/dri/renderD128,uid=0,gid=0,mode=0660'}
        with tempfile.TemporaryDirectory() as temp, patch.object(fixture,'PERL_DRIVER',STAT_DRIVER+fixture.PERL_DRIVER):
            for prepare in (False,True):
                with self.subTest(prepare=prepare):
                    log=Path(temp)/str(prepare)
                    env={'TEST_RESOURCE_STATS':'1','TEST_EXTRA_CONFIG':json.dumps(config),
                         'TEST_MARKER':'ProxMenux request '+fixture.REQUEST_ID,'TEST_CALL_LOG':str(log)}
                    result=self.call('start',vmid=240,description=env['TEST_MARKER'],
                        expected={**fixture.NATIVE_EXPECTED,'prepare_system':prepare,'arch':'amd64','resources':self.resources()},environment=env)
                    self.assertEqual(result.returncode,0,result.stderr)
                    calls=log.read_text().splitlines()
                    self.assertEqual(calls.count('START'),1)
                    self.assertIn('START_FULL_CONFIG',calls)
                    self.assertNotIn('MOUNT_INCLUDES_DATA',calls)
                    self.assertNotIn('UNMOUNT_INCLUDES_DATA',calls)
                    self.assertEqual(calls.count('MOUNT'),int(prepare))
                    self.assertEqual(calls.count('PREPARE'),int(prepare))
            for change in ({'TEST_RESOURCE_CHANGED':'1'}, {'TEST_RESOURCE_SYMLINK':'1'}, {'TEST_DEVICE_POLICY_FAIL':'1'},
                           {'TEST_EXTRA_CONFIG':json.dumps({**config,'mp2':'/etc,mp=/host'})}):
                log=Path(temp)/('negative'+str(len(list(Path(temp).iterdir()))))
                env={'TEST_RESOURCE_STATS':'1','TEST_EXTRA_CONFIG':json.dumps(config),'TEST_CALL_LOG':str(log),
                     'TEST_MARKER':'ProxMenux request '+fixture.REQUEST_ID,**change}
                result=self.call('start',vmid=240,description=env['TEST_MARKER'],
                    expected={**fixture.NATIVE_EXPECTED,'prepare_system':False,'arch':'amd64','resources':self.resources()},environment=env)
                self.assertNotEqual(result.returncode,0)
                calls=log.read_text().splitlines()
                self.assertNotIn('START',calls); self.assertNotIn('MOUNT',calls)

    def test_native_create_allows_only_new_volumes_and_exact_reviewed_device_identities(self):
        spec=fixture.EngineTests('test_context_and_plan_are_read_only_and_stable_for_json_clients')
        spec.setUp(); self.addCleanup(spec.doCleanups)
        from plain_lxc_spec import normalize,pve_params
        normalized=normalize({**spec.spec,'mounts':[
            {key:value for key,value in item.items() if key not in ('identity','storage_type')} for item in self.resources()['mounts']],
            'devices':[{'path':'/dev/dri/renderD128'}]})
        params=pve_params(normalized,None,fixture.REQUEST_ID)
        params['resource_identity']=self.resources()
        with tempfile.TemporaryDirectory() as temp, patch.object(fixture,'PERL_DRIVER',STAT_DRIVER+fixture.PERL_DRIVER):
            log=Path(temp)/'calls'
            env={'TEST_RESOURCE_STATS':'1','TEST_MARKER':'ProxMenux request '+fixture.REQUEST_ID,'TEST_CALL_LOG':str(log)}
            result=self.call('create',environment=env,**params)
            self.assertEqual(result.returncode,0,result.stderr)
            before=log.read_text()
            for change in ({'mp0':'local-lvm:vm-999-disk-0,mp=/data,ro=0,backup=1'},
                           {'dev0':'path=/dev/mem,uid=0,gid=0,mode=0660'}):
                self.assertNotEqual(self.call('create',environment=env,**{**params,**change}).returncode,0)
                self.assertEqual(log.read_text(),before)


class StateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.old, self.new = self.root/'legacy', self.root/'install/state/plain-lxc'
        self.store = fixture.Operations(self.old, os.getuid())
        self.original = dict(request_id=fixture.REQUEST_ID, status='succeeded', action='create', vmid=240)
        self.store.admit(self.original, 'vmid:240')
        self.store.save(self.original)
        self.quiet = patch.object(state, 'assert_quiescent_processes')
        self.quiet.start(); self.addCleanup(self.quiet.stop)

    def test_migration_and_reverse_preserve_newer_journal_not_old_snapshot(self):
        state.migrate_state(self.old, self.new)
        self.assertTrue(self.old.is_symlink())
        migrated = fixture.Operations(self.new, os.getuid())
        self.assertEqual(migrated.get(fixture.REQUEST_ID), self.original)
        newer = {**self.original, 'request_id': '2'*32}
        migrated.admit(newer, 'vmid:241'); migrated.save(newer)
        state.migrate_state(self.old, self.new, rollback=True)
        self.assertFalse(self.old.is_symlink())
        self.assertEqual(self.store.get('2'*32), newer)
        self.assertFalse(self.new.exists())

    def test_pending_live_controller_conflict_and_failed_rename_preserve_source(self):
        self.store.save({**self.original, 'status': 'unknown'})
        with self.assertRaisesRegex(fixture.LxcError, '^state_operations_pending$'):
            state.migrate_state(self.old, self.new)
        self.store.save(self.original)
        with self.store.controller(fixture.REQUEST_ID):
            with self.assertRaisesRegex(fixture.LxcError, '^operation_controller_active$'):
                state.migrate_state(self.old, self.new)
        with patch.object(state, 'exchange_directories', side_effect=OSError('cross-filesystem')):
            with self.assertRaises(OSError): state.migrate_state(self.old, self.new)
        self.assertEqual(self.store.get(fixture.REQUEST_ID), self.original)
        self.assertFalse(self.new.exists())
        self.new.mkdir(mode=0o700)
        with self.assertRaisesRegex(fixture.LxcError, '^state_migration_conflict$'):
            state.migrate_state(self.old, self.new)
        self.assertEqual(self.store.get(fixture.REQUEST_ID), self.original)

    def test_uninstall_blocks_pending_without_changing_guest_or_database(self):
        self.store.save({**self.original, 'status': 'unknown'})
        before = self.store.path.read_bytes()
        with patch.object(state, 'STATE', self.new), patch.object(state, 'LEGACY_STATE', self.old):
            with self.assertRaisesRegex(fixture.LxcError, '^state_operations_pending$'):
                state.check_uninstall()
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_ephemeral_uninstall_lock_blocks_admission_and_migration(self):
        with patch.object(state,'RUNTIME',self.root/'run'):
            with state.runtime_lock(exclusive=True):
                with self.assertRaisesRegex(fixture.LxcError,'^operation_controller_active$'):
                    with state.runtime_lock(): self.fail('shared admission passed uninstall')
            with state.runtime_lock(), state.runtime_lock():
                with self.assertRaisesRegex(fixture.LxcError,'^operation_controller_active$'):
                    with state.runtime_lock(exclusive=True): self.fail('migration passed active controllers')
            with state.runtime_lock(exclusive=True): pass

    def test_empty_journal_migration_and_own_alias_cleanup_are_safe(self):
        self.store.path.unlink()
        state.migrate_state(self.old,self.new)
        migrated=fixture.Operations(self.new,os.getuid())
        migrated.admit(self.original,'vmid:240'); migrated.save(self.original)
        before=migrated.path.read_bytes()
        with patch.object(state,'STATE',self.new),patch.object(state,'LEGACY_STATE',self.old):
            state.remove_legacy_alias()
            self.assertEqual(state.installed_directory(),self.new)
        self.assertFalse(self.old.exists()); self.assertFalse(self.old.is_symlink())
        self.assertEqual(migrated.path.read_bytes(),before)

    def test_symlink_or_hardlinked_database_cannot_be_written(self):
        target=self.root/'unrelated'; target.write_bytes(b'owned by another purpose')
        self.store.path.unlink(); self.store.path.symlink_to(target)
        before=target.read_bytes()
        with self.assertRaisesRegex(fixture.LxcError,'^operation_store_unavailable$'):
            self.store.admit(self.original,'vmid:240')
        self.assertEqual(target.read_bytes(),before)
        self.store.path.unlink(); os.link(target,self.store.path)
        with self.assertRaisesRegex(fixture.LxcError,'^operation_store_unavailable$'):
            self.store.admit(self.original,'vmid:240')
        self.assertEqual(target.read_bytes(),before)


class DevicePolicyTests(unittest.TestCase):
    def test_sriov_vf_active_pf_vfio_and_unknown_mapping_fail_without_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            pci=root/'devices/pci0000:00/0000:00:02.0'; pci.mkdir(parents=True)
            driver=root/'bus/pci/drivers/i915'; driver.mkdir(parents=True)
            (pci/'driver').symlink_to(driver)
            node=root/'dev/char/226:128'; node.parent.mkdir(parents=True); node.symlink_to(pci)
            (pci/'sriov_numvfs').write_text('0\n')
            identity={'rdev':str(os.makedev(226,128))}
            def probe(reject):
                before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
                if reject:
                    with self.assertRaisesRegex(fixture.LxcError,'^resource_unavailable$'):
                        resources.device_policy('/dev/dri/renderD128',identity,root)
                else: resources.device_policy('/dev/dri/renderD128',identity,root)
                self.assertEqual({str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file() and not p.is_symlink()},before)
            probe(False)
            (pci/'physfn').symlink_to(pci.parent/'0000:00:01.0'); probe(True); (pci/'physfn').unlink()
            (pci/'sriov_numvfs').write_text('2\n'); probe(True); (pci/'sriov_numvfs').write_text('0\n')
            (pci/'driver').unlink(); vfio=root/'bus/pci/drivers/vfio-pci'; vfio.mkdir(); (pci/'driver').symlink_to(vfio); probe(True)
            node.unlink(); probe(True)

    def test_usb_sysfs_identity_and_hub_exclusion_use_real_temporary_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); usb=root/'devices/usb1/1-3.2'; usb.mkdir(parents=True)
            for name,value in (('idVendor','18d1'),('idProduct','9302'),('bDeviceClass','00')): (usb/name).write_text(value+'\n')
            node=root/'dev/char/189:2'; node.parent.mkdir(parents=True); node.symlink_to(usb)
            identity={'rdev':str(os.makedev(189,2))}
            self.assertEqual(resources.usb_identifiers('/dev/bus/usb/001/003',root,identity),{'id':'18d1:9302','port':'1-3.2'})
            resources.device_policy('/dev/bus/usb/001/003',identity,root)
            (usb/'bDeviceClass').write_text('09\n')
            with self.assertRaisesRegex(fixture.LxcError,'^resource_unavailable$'):
                resources.device_policy('/dev/bus/usb/001/003',identity,root)

    def test_ct_pending_and_vm_usb_assignments_block_stealing_but_gpu_sharing_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); ct=root/'lxc'; vm=root/'qemu'; ct.mkdir(); vm.mkdir()
            gpu='/dev/dri/renderD128'; usb='/dev/bus/usb/001/003'
            def check(paths): return resources.device_assignments(paths,240,ct,vm)
            (ct/'101.conf').write_text('dev0: uid=0,path='+usb+',gid=0\n')
            with self.assertRaisesRegex(fixture.LxcError,'^resource_in_use$'): check([usb])
            (ct/'101.conf').write_text('mp0: /dev/dri,mp=/dev/dri\n')
            self.assertEqual(check([gpu]),{gpu:[101]})
            (ct/'101.conf').write_text('[old-snapshot]\ndev0: '+usb+'\n')
            self.assertEqual(check([usb]),{usb:[]})
            (ct/'101.conf').write_text('[PENDING]\ndev0: '+usb+'\n')
            with self.assertRaisesRegex(fixture.LxcError,'^resource_in_use$'): check([usb])
            (ct/'101.conf').unlink()
            for host in ('host=0x18d1:0x9302','host=1-3.2'):
                (vm/'250.conf').write_text('usb0: '+host+',usb3=1\n')
                with patch.object(resources,'usb_identifiers',return_value={'id':'18d1:9302','port':'1-3.2'}):
                    with self.assertRaisesRegex(fixture.LxcError,'^resource_in_use$'): check([usb])
            (vm/'250.conf').write_text('usb0: spice\n')
            with patch.object(resources,'usb_identifiers',side_effect=AssertionError('must not probe SPICE')):
                self.assertEqual(check([usb]),{usb:[]})
            for raw in ('mapping=unknown-map','host=garbage','host=1-2,host=1-3'):
                (vm/'250.conf').write_text('usb0: '+raw+'\n')
                with self.assertRaisesRegex(fixture.LxcError,'^resource_unavailable$'): check([usb])

    def test_bind_symlinks_and_regular_files_are_rejected_without_modifying_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'data'; source.mkdir(); sentinel=source/'sentinel'; sentinel.write_bytes(b'unchanged')
            alias=root/'alias'; alias.symlink_to(source)
            self.assertEqual(resources.bind_identity(str(source))['ino'],str(source.stat().st_ino))
            for path in (alias,sentinel):
                with self.assertRaisesRegex(fixture.LxcError,'^resource_unavailable$'): resources.bind_identity(str(path))
            self.assertEqual(sentinel.read_bytes(),b'unchanged')
            self.assertEqual(sorted(p.name for p in root.iterdir()),['alias','data'])


class NativeOptionTests(unittest.TestCase):
    setUpClass = classmethod(fixture.PerlBridgeTests.setUpClass.__func__)
    call = fixture.PerlBridgeTests.call

    def test_real_turnkey_mirror_download_is_native_and_rejects_forged_locations(self):
        row=json.loads((fixture.ROOT/'.github/scripts/tests/fixtures/plain_lxc_turnkey_aplinfo.json').read_text())[0]
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/row['template'];log=Path(temp)/'calls'
            params={'storage':'local','template':row['template'],'sha512':row['sha512sum'],'architecture':'amd64'}
            env={'TEST_ARCHIVE':str(target),'TEST_TEMPLATE':row['template'],'TEST_SHA':row['sha512sum'],
                 'TEST_SOURCE':row['source'],'TEST_LOCATION':row['location'],'TEST_CALL_LOG':str(log)}
            for scheme in ('https','http'):
                result=self.call('download_template',environment={**env,'TEST_LOCATION':scheme+row['location'][row['location'].index(':'):]},**params)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout),fixture.upid('download',row['template']))
            accepted=log.read_text()
            for location in ('https://example.org/'+row['template'],row['location']+'?other=1',
                             row['location'].replace('mirror.turnkeylinux.org','mirror.turnkeylinux.org.example.org')):
                result=self.call('download_template',environment={**env,'TEST_LOCATION':location},**params)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(log.read_text(),accepted)
            target.write_bytes(b'existing')
            self.assertNotEqual(self.call('download_template',environment=env,**params).returncode,0)
            self.assertEqual(target.read_bytes(),b'existing')
            self.assertEqual(log.read_text(),accepted)

    def test_native_default_start_skips_preparation_mount_and_helper_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp)/'calls'
            result = self.call('start', vmid=240, description='ProxMenux request '+fixture.REQUEST_ID,
                               expected={**fixture.NATIVE_EXPECTED, 'prepare_system': False},
                               environment={'TEST_MARKER':'ProxMenux request '+fixture.REQUEST_ID, 'TEST_CALL_LOG':str(log)})
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text().splitlines()
            self.assertEqual([x for x in calls if x in ('MOUNT','PREPARE','UNMOUNT','START')], ['START'])

    def test_recovery_native_guard_checks_all_workers_and_releases_no_guest_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp)/'calls'
            env = {'TEST_CALL_LOG':str(log)}
            # An earlier response-pipe fixture can still have its own bounded
            # child alive. Production correctly refuses recovery until it exits.
            for _ in range(50):
                result = self.call('recovery_check', vmid=240,
                                   description='ProxMenux request '+fixture.REQUEST_ID, environment=env)
                if result.returncode == 0:
                    break
                time.sleep(0.1)
            self.assertEqual(result.returncode, 0, result.stderr)
            import json
            self.assertEqual(json.loads(result.stdout), {'safe':1,'present':0})
            for name in ('TEST_ACTIVE_TASK', 'TEST_BAD_TASKS', 'TEST_LOCK_BUSY'):
                self.assertNotEqual(self.call('recovery_check',vmid=240,
                                   description='ProxMenux request '+fixture.REQUEST_ID,
                                   environment={**env,name:'1'}).returncode, 0)
            calls = log.read_text().splitlines()
            self.assertNotIn('START', calls); self.assertNotIn('MOUNT', calls)
            self.assertFalse(any(x.startswith(('POST ', 'DELETE ', 'PUT ')) for x in calls))


class WizardNavigationTests(unittest.TestCase):
    setUp = fixture.EngineTests.setUp
    simulate_engine = fixture.WizardTests.simulate_engine

    def test_back_reopens_previous_resource_field_with_its_value_and_no_effects(self):
        class UI(fixture.ScriptedDialog):
            def __init__(self):
                super().__init__(False); self.back = True; self.cores = []
            def number(self, step, prompt, default, optional=False):
                if prompt == 'Root disk size (GiB)': return 12
                if prompt == 'CPU cores': self.cores.append(default); return 3
                if prompt == 'RAM (MiB)' and self.back:
                    self.back = False; raise fixture.wizard.Back()
                return 1024 if prompt == 'RAM (MiB)' else default
        ui = UI()
        context = fixture.EngineTests.call(self, 'context')
        draft, _, _ = fixture.wizard.edit_group(ui, 'resources', {'node':fixture.NODE}, {}, context)
        self.assertEqual(ui.cores, [1, 3])
        self.assertEqual(draft['rootfs']['size_gib'], 12)
        self.assertEqual(draft['memory']['ram_mib'], 1024)
        self.assertEqual(self.api.writes, [])
        self.assertFalse(self.store.directory.exists())

    def test_template_is_chosen_before_suggested_hostname_and_custom_name_survives(self):
        class UI(fixture.ScriptedDialog):
            def input(self, step, prompt, default='', hidden=False):
                self.events.append(('input',prompt,default)); return default
            def choose(self, step, prompt, choices, default=''):
                self.events.append(('choose',prompt,default)); return choices[0][0]
        context = fixture.EngineTests.call(self, 'context')
        for hostname, expected in (('', 'debian-13'), ('my-server','my-server')):
            ui = UI(False); ui.events = []
            draft, _, _ = fixture.wizard.edit_group(ui, 'system',
                {'node':fixture.NODE,'hostname':hostname}, {}, context)
            self.assertEqual(draft['hostname'], expected)
            self.assertEqual(ui.events[0][1], 'Select a system template')
            self.assertEqual(ui.events[1][1], 'Container hostname')
        self.assertEqual(self.api.writes, [])

    def test_one_review_and_short_confirmation_cancel_have_zero_mutations(self):
        ui = fixture.ScriptedDialog(False)
        with self.simulate_engine(self.api, self.store) as calls:
            fixture.wizard.wizard(ui)
        self.assertIn('VMID: 240', ui.review)
        self.assertEqual(ui.confirmation, 'Create this container?')
        self.assertNotIn(fixture.PASSWORD, ui.review)
        self.assertEqual([item['action'] for item in calls], ['context','plan'])
        self.assertEqual(self.api.writes, [])
        self.assertFalse(self.store.directory.exists())

    def test_back_at_first_field_returns_without_plan_or_create(self):
        class UI(fixture.ScriptedDialog):
            def number(self, *args, **kwargs): raise fixture.wizard.Back()
        with self.simulate_engine(self.api, self.store) as calls:
            fixture.wizard.wizard(UI(False))
        self.assertEqual([item['action'] for item in calls], ['context'])
        self.assertEqual(self.api.writes, [])
        self.assertFalse(self.store.directory.exists())

    def test_back_after_confirmed_download_never_replays_that_download(self):
        class UI(fixture.ScriptedDialog):
            def __init__(self): super().__init__(False,download=True); self.back=True
            def input(self,step,prompt,default='',hidden=False):
                if prompt=='Container hostname' and self.back:
                    self.back=False; raise fixture.wizard.Back()
                return super().input(step,prompt,default,hidden)
        self.api.present=False
        with self.simulate_engine(self.api,self.store) as calls:
            fixture.wizard.wizard(UI())
        self.assertEqual([item['action'] for item in calls].count('download_template'),1)
        self.assertEqual([name for name,_ in self.api.writes],['download_template'])
        self.assertNotIn('create',[item['action'] for item in calls])

    def test_mount_and_hardware_fields_use_same_plan_and_cancel_has_zero_guest_mutations(self):
        class UI(fixture.ScriptedDialog):
            def __init__(self):
                super().__init__(False)
                self.mount_actions=iter(['volume','done']); self.device_actions=iter(['/dev/dri/renderD128','done'])
            def choose(self,step,prompt,choices,default=''):
                if prompt.startswith('Mount points'): return next(self.mount_actions)
                if prompt=='Select mount point storage': return 'local-lvm'
                if prompt=='Select optional hardware': return next(self.device_actions)
                return super().choose(step,prompt,choices,default)
            def confirm(self,step,text,default=False):
                if text in ('Add mount points?','Add hardware passthrough?'): return True
                return super().confirm(step,text,default=default)
            def input(self,step,prompt,default='',hidden=False):
                if prompt=='Mount path inside the container': return '/data'
                if prompt=='Device access mode (four octal digits)': return '0660'
                return super().input(step,prompt,default,hidden)
        self.api.hardware['/dev/dri/renderD128']={'path':'/dev/dri/renderD128','kind':'GPU',
            'identity':{'dev':'10','ino':'12','rdev':'226','uid':0,'gid':0,'mode':0o660}}
        ui=UI()
        with self.simulate_engine(self.api,self.store) as calls:
            fixture.wizard.wizard(ui)
        plan=next(item['spec'] for item in calls if item['action']=='plan')
        self.assertEqual(plan['mounts'][0]['path'],'/data')
        self.assertEqual(plan['devices'][0]['path'],'/dev/dri/renderD128')
        self.assertIn('/data',ui.review); self.assertIn('/dev/dri/renderD128',ui.review)
        self.assertEqual(self.api.writes,[])
        self.assertFalse(self.store.directory.exists())


    def test_pending_recovery_reuses_original_id_and_never_creates_or_replays(self):
        ReviewEngineTests.orphan(self,submission='not_started')
        class UI(fixture.ScriptedDialog):
            def choose(self,step,prompt,choices,default=''):
                if prompt.startswith('An earlier operation needs to be checked.'):
                    return 'recover'
                return super().choose(step,prompt,choices,default)
            def confirm(self,step,text,default=False):
                return text.startswith('Recover this reservation without repeating the operation?')
            def number(self,*args,**kwargs): raise fixture.wizard.Back()
        with self.simulate_engine(self.api,self.store) as calls:
            fixture.wizard.wizard(UI(False))
        self.assertEqual([item['action'] for item in calls],['context','recover','context'])
        self.assertEqual(calls[1]['request_id'],fixture.REQUEST_ID)
        self.assertIs(calls[1]['confirmed'],True)
        self.assertEqual(self.api.writes,[])
        self.assertEqual(self.store.pending(),[])
        self.assertEqual(self.store.get(fixture.REQUEST_ID)['reason'],'recovered_not_submitted')


class MainAndUninstallTests(unittest.TestCase):
    def test_cli_runtime_guard_rejects_before_any_pve_probe(self):
        output=io.StringIO()
        with patch.object(engine.os,'geteuid',return_value=0),patch.object(engine.os,'umask'), \
             patch.object(engine.sys,'argv',['plain_lxc.py']), \
             patch.object(engine.sys,'stdin',SimpleNamespace(buffer=io.BytesIO(b'{"schema_version":1,"action":"create"}'))), \
             patch.object(engine.sys,'stdout',output), \
             patch.object(engine,'runtime_lock',side_effect=fixture.LxcError('operation_controller_active')), \
             patch.object(engine,'Proxmox') as api:
            self.assertEqual(engine.main(),1)
        self.assertEqual(json.loads(output.getvalue())['error'],'operation_controller_active')
        api.assert_not_called()

    def test_uninstall_pending_and_late_guard_failure_have_zero_removals_and_no_false_success(self):
        source=(fixture.ROOT/'scripts/menus/config_menu.sh').read_text()
        function='uninstall_proxmenu() {'+source.split('uninstall_proxmenu() {',1)[1].split('\n}\n',1)[0]+'\n}\n'
        for phase in ('initial','late'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); base=root/'install'; helper=base/'scripts/lxc/plain_lxc.py'; helper.parent.mkdir(parents=True)
                runtime=root/'run'; forbidden=root/'forbidden'; events=root/'events'
                helper.write_text("import fcntl,sys,os\nfrom pathlib import Path\n"
                    +f"phase={phase!r}\n"
                    +"if sys.argv[1]=='--check-uninstall': sys.exit(1 if phase=='initial' else 0)\n"
                    +f"fd=os.open({str(runtime/'controller.lock')!r},os.O_RDWR)\n"
                    +"try: fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)\n"
                    +f"except BlockingIOError: Path({str(events)!r}).write_text('LOCK_HELD')\n"
                    +"sys.exit(1)\n")
                legacy=root/'legacy-google'; legacy.mkdir()
                local=function.replace('/run/proxmenux-plain-lxc',str(runtime)).replace('/opt/googletrans-env',str(legacy))
                self.assertNotIn('/run/proxmenux-plain-lxc',local)
                prefix=f'BASE_DIR={shlex.quote(str(base))}\nFORBIDDEN={shlex.quote(str(forbidden))}\n'
                prefix+='translate() { echo "$1"; }\npmx_journal_context() { :; }\npmx_record_execution() { :; }\n'
                prefix+='dialog() { if [[ " $* " == *" --gauge "* ]]; then cat >/dev/null; fi; if [[ "$*" == *"Uninstallation Complete"* ]]; then echo FALSE_SUCCESS >> "$FORBIDDEN"; fi; return 0; }\n'
                for name in ('rm','pmx_remove_file','remove_usbip_sharing','remove_registry_logins','uninstall_proxmenux_monitor','pmx_write_file','pmx_edit_file'):
                    prefix+=name+'() { echo FORBIDDEN >> "$FORBIDDEN"; return 97; }\n'
                prefix+='sleep() { :; }\n'
                result=subprocess.run(['bash'],input=prefix+local+'\nuninstall_proxmenu\n',text=True,capture_output=True,timeout=8)
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertFalse(forbidden.exists(),forbidden.read_text() if forbidden.exists() else '')
                self.assertTrue(helper.exists()); self.assertTrue(legacy.exists())
                if phase=='late': self.assertEqual(events.read_text(),'LOCK_HELD')


class VMRouteTests(unittest.TestCase):
    def test_visible_lxc_four_preserves_legacy_cli_four_and_five_without_external_execution(self):
        import shutil
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); scripts = root/'scripts'; menus=scripts/'menus'; vm=scripts/'vm'; commands=root/'bin'
            for path in (menus,vm,commands): path.mkdir(parents=True)
            shutil.copyfile(fixture.ROOT/'scripts/menus/create_vm_menu.sh', menus/'create_vm_menu.sh')
            (scripts/'utils.sh').write_text('load_language() { LANGUAGE=en; }\ninitialize_cache() { :; }\ntranslate() { echo "$1"; }\n')
            for name in ('vm_configurator.sh','disk_selector.sh','vm_creator.sh'): (vm/name).write_text(':\n')
            (vm/'select_nas_iso.sh').write_text('select_nas_iso() { echo "NAS $VM_PRESET"; return 1; }\n')
            (vm/'select_linux_iso.sh').write_text('select_linux_other_scripts() { echo "OTHERS $VM_PRESET"; return 1; }\nselect_linux_iso() { echo "LINUX $VM_PRESET"; return 1; }\n')
            (vm/'select_windows_iso.sh').write_text('select_windows_iso() { echo "WINDOWS $VM_PRESET"; return 1; }\n')
            (menus/'main_menu.sh').write_text('echo MAIN\n')
            (menus/'plain_lxc_wizard.py').write_text('print("LXC")\n')
            for name, content in {
                'dialog':'read -r choice < "$QUEUE" || exit 255\nsed -i "1d" "$QUEUE"\nprintf "%s" "$choice" >&2\n',
                'whiptail':'echo MACOS_CONFIRM\nexit 1\n',
                **{name:'echo "$0" >> "$FORBIDDEN"\nexit 97\n' for name in ('curl','pct','pvesh','pvesm','sudo','systemctl','mount','apt-get')}
            }.items():
                path=commands/name; path.write_text('#!/bin/bash\n'+content); path.chmod(0o755)
            for args, queue, catalog, expected, exitcode in (
                ([], '4\n7\n', '', 'LXC\nMAIN', 0),
                ([], '5\n7\n', '', 'MACOS_CONFIRM\nMAIN', 0),
                (['4'], '', '1', 'MACOS_CONFIRM', 130),
                (['5','alpine'], '', '1', 'OTHERS alpine', 130),
                (['1','truenas-scale'], '', '1', 'NAS truenas-scale', 130),
                (['2','uupdump'], '', '1', 'WINDOWS uupdump', 130),
                (['3','ubuntu'], '', '1', 'LINUX ubuntu', 130),
            ):
                with self.subTest(args=args,queue=queue):
                    (root/'queue').write_text(queue)
                    result=subprocess.run(['bash',str(menus/'create_vm_menu.sh'),*args],capture_output=True,text=True,timeout=5,
                        env={**os.environ,'PATH':str(commands)+':'+os.environ['PATH'],'QUEUE':str(root/'queue'),
                             'FORBIDDEN':str(root/'forbidden'),'PROXMENUX_CATALOG':catalog})
                    self.assertEqual(result.returncode,exitcode,result.stderr)
                    self.assertEqual(result.stdout.strip(),expected)
                    self.assertFalse((root/'forbidden').exists())
