"""Exercise two-phase batching with native-shaped private records and no PVE calls."""
import copy
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'remote')]
from proxmenux_oci import batch_updates as batch, management, recommended, host
import oci_instances as instances

OLD='sha256:'+'a'*64
NEW='sha256:'+'b'*64


class UI:
    unattended=False
    def __init__(self, failure_policy=False):
        self.events=[];self.executing=False;self.failure_policy=failure_policy
        self.decline=None;self.before_start=None
    def confirm(self,text,default=False,**kwargs):
        assert not self.executing,'a question appeared during execution'
        self.events.append(('confirm',text));return self.failure_policy
    def review(self,text,title=None,question=None,**kwargs):
        assert not self.executing,'a review appeared during execution'
        self.events.append(('review',title))
        if title=='Update selected OCI applications'and self.before_start:self.before_start()
        return title!=self.decline
    def message(self,text,title=None):self.events.append(('message',title,text))


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'instances';self.configs=Path(self.tmp.name)/'configs'
        self.configs.mkdir()
        for obj,name,value in ((instances,'ROOT',self.root),(batch,'CONFIGS',self.configs)):
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        for name in ('show_logo','msg_title'):
            p=patch('proxmenux_oci.console.'+name);p.start();self.addCleanup(p.stop)
        p=patch.object(management,'carry_records',return_value={});self.carry=p.start();self.addCleanup(p.stop)
        self.seed(2401);self.seed(2402)
        self.ui=UI();self.prepared=[];self.executed=[]
        self.rows=[{'vmid':v,'title':f'App {v}'}for v in (2401,2402)]
        self.prepare_hook=None;self.execute_hook=None;self.cancel_app=None
        self.managing=patch.object(management,'manage_instance',side_effect=self.prepare)
        self.managing.start();self.addCleanup(self.managing.stop)
        self.running=patch.object(batch,'_run_command',side_effect=self.execute)
        self.run=self.running.start();self.addCleanup(self.running.stop)

    def seed(self,vmid,primary=None,members=None):
        identity=str(uuid.UUID(int=vmid))
        r={'schema_version':1,'vmid':vmid,'status':'installed','installation_id':identity,
           'deployment':{'hostname':f'app-{vmid}'},'observed':{'image':{'manifest_digest':OLD}}}
        if primary:r['stack_member']={'primary_vmid':primary}
        if members:r['stack']={'members':[{'vmid':v,'installation_id':str(uuid.UUID(int=v))}for v in members]}
        instances.write(instances.location(self.root,vmid),r)
        (self.configs/f'{vmid}.conf').write_text(f'arch: amd64\ndescription: proxmenux-instance={identity}\ncores: 1\n')

    def prepare(self,project,ui,row,action,heading,runner):
        self.assertFalse(ui.executing)
        v=row['vmid'];self.prepared.append(v)
        if v==self.cancel_app:return management.CANCELLED
        self.assertTrue(ui.review('Application update',f'Prepare {v}'))
        if self.prepare_hook:self.prepare_hook(v,runner)
        runner([sys.executable,'updater.py',str(v)],'Update OCI')
        return True

    def execute(self,command):
        self.ui.executing=True;v=int(command[2]);self.executed.append(v)
        if self.execute_hook:return self.execute_hook(v,command)
        r=instances.read(self.root,v);r['observed']['image']['manifest_digest']=NEW
        instances.write(instances.location(self.root,v),r);return 0

    def start(self):return batch.run_batch(ROOT,self.ui,self.rows)

    def reports(self):return list(self.root.glob('batch-updates/*/report.json'))

    def test_every_question_precedes_every_update_and_summary_comes_last(self):
        report=self.start()
        self.assertEqual(self.prepared,[2401,2402]);self.assertEqual(self.executed,[2401,2402])
        self.assertEqual(report['status'],'completed')
        self.assertEqual([r['status']for r in report['applications']],['updated','updated'])
        self.assertEqual(self.ui.events[-1][0],'message')
        self.assertEqual([call.kwargs['vmids']for call in self.carry.call_args_list],[[2401],[2402]])

    def test_native_file_encoded_multiline_description_keeps_its_identity(self):
        from urllib.parse import quote
        identity=str(uuid.UUID(int=2401))
        description=quote('<div>Application</div>\n<!-- proxmenux-instance='+identity+' -->',safe='')
        (self.configs/'2401.conf').write_text('arch: amd64\ndescription: '+description+'\ncores: 1\n')
        self.assertEqual(self.start()['status'],'completed')

    def test_pve_file_comment_description_is_not_confused_with_snapshot_comments(self):
        identity=str(uuid.UUID(int=2401))
        (self.configs/'2401.conf').write_text('#<div>Application</div>\n#<!-- proxmenux-instance='+identity+' -->\narch: amd64\ncores: 1\n\n[old]\n#proxmenux-instance='+str(uuid.UUID(int=99))+'\n')
        self.assertEqual(self.start()['status'],'completed')

    def test_snapshot_marker_cannot_supply_a_missing_live_identity(self):
        identity=str(uuid.UUID(int=2401))
        (self.configs/'2401.conf').write_text('arch: amd64\n\n[old]\n#proxmenux-instance='+identity+'\n')
        self.assertIsNone(self.start());self.run.assert_not_called()

    def test_cancel_during_second_preparation_runs_neither_application(self):
        self.cancel_app=2402
        self.assertIsNone(self.start());self.run.assert_not_called();self.assertFalse(self.reports())

    def test_sigterm_during_preparation_cleans_private_proposals_and_starts_nothing(self):
        paths=[];before=signal.getsignal(signal.SIGTERM)
        def prepare(v,runner):
            with tempfile.NamedTemporaryFile(mode='w')as original:
                json.dump({'secret':'preparation-only'},original);original.flush()
                runner([sys.executable,'updater.py',str(v),'--proposal',original.name],'Modify OCI')
            # The cloned proposal exists until the outer preparation context exits.
            # Its path is private to the collector, so observe its own folder.
            paths.extend(Path(self.tmp.name).glob('proxmenux-oci-batch-*/*.json'))
            signal.raise_signal(signal.SIGTERM)
        self.prepare_hook=prepare
        with patch.object(tempfile,'tempdir',self.tmp.name):
            self.assertIsNone(self.start())
        self.run.assert_not_called()
        self.assertTrue(paths);self.assertTrue(all(not p.exists()for p in paths))
        self.assertEqual(signal.getsignal(signal.SIGTERM),before)
        self.assertFalse(self.reports())

    def test_final_confirmation_can_cancel_without_runtime_changes(self):
        self.ui.decline='Update selected OCI applications'
        self.assertIsNone(self.start());self.run.assert_not_called();self.assertFalse(self.reports())

    def test_default_failure_policy_stops_the_queue(self):
        self.execute_hook=lambda v,c:1
        report=self.start()
        self.assertEqual(self.executed,[2401])
        self.assertEqual([r['status']for r in report['applications']],['failed','skipped'])
        self.assertEqual(report['status'],'failed')

    def test_continue_policy_runs_next_after_safe_preflight_or_recovered_failure(self):
        self.ui.failure_policy=True
        self.execute_hook=lambda v,c:1 if v==2401 else 0
        report=self.start();self.assertEqual(self.executed,[2401,2402])
        self.assertEqual([r['status']for r in report['applications']],['failed','unchanged'])

    def test_pending_recovery_overrides_continue_policy(self):
        self.ui.failure_policy=True
        def failure(v,c):
            r=instances.read(self.root,v);r['status']='updating';r['pending_transaction']='private journal'
            instances.write(instances.location(self.root,v),r);return 1
        self.execute_hook=failure
        report=self.start();self.assertEqual(self.executed,[2401])
        self.assertEqual([r['status']for r in report['applications']],['recovery-required','skipped'])

    def test_change_during_final_confirmation_blocks_the_entire_batch(self):
        self.ui.before_start=lambda:(self.configs/'2402.conf').write_text('replaced configuration')
        report=self.start();self.run.assert_not_called()
        self.assertEqual([r['status']for r in report['applications']],['skipped','blocked'])

    def test_change_to_a_later_app_during_an_update_stops_before_touching_it(self):
        def change(v,c):
            (self.configs/'2402.conf').write_text('changed while first app ran');return 0
        self.execute_hook=change
        report=self.start();self.assertEqual(self.executed,[2401])
        self.assertEqual([r['status']for r in report['applications']],['unchanged','blocked'])

    def test_interruption_never_starts_the_next_app_and_persists_a_report(self):
        self.execute_hook=Mock(side_effect=KeyboardInterrupt)
        report=self.start();self.assertEqual(self.executed,[2401])
        self.assertEqual(report['status'],'interrupted')
        self.assertEqual([r['status']for r in report['applications']],['interrupted','skipped'])
        self.assertEqual(json.loads(self.reports()[0].read_text())['status'],'interrupted')
        self.assertEqual(report['applications'][0]['steps'][0]['status'],'interrupted')

    def test_helper_spawn_failure_is_not_left_running_in_the_report(self):
        self.execute_hook=Mock(side_effect=OSError('Cannot start helper'))
        report=self.start()
        self.assertEqual(report['applications'][0]['status'],'failed')
        self.assertEqual(report['applications'][0]['steps'][0]['status'],'failed')
        self.assertEqual(report['applications'][1]['status'],'skipped')

    def test_a_signalled_child_stops_even_with_continue_enabled(self):
        self.ui.failure_policy=True;self.execute_hook=lambda v,c:-signal.SIGTERM
        report=self.start();self.assertEqual(self.executed,[2401])
        self.assertEqual(report['status'],'interrupted')

    def test_private_proposals_outlive_the_source_file_but_never_enter_the_report(self):
        proposals=[]
        def prepare(v,runner):
            if v!=2401:return
            with tempfile.NamedTemporaryFile(mode='w')as original:
                json.dump({'environment':'private-test-secret'},original);original.flush()
                runner([sys.executable,'updater.py',str(v),'--proposal',original.name],'Modify OCI')
        self.prepare_hook=prepare
        def run(v,c):
            if '--proposal'in c:
                p=Path(c[c.index('--proposal')+1]);proposals.append(p)
                self.assertEqual(json.loads(p.read_text())['environment'],'private-test-secret')
                self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)
                self.assertEqual(stat.S_IMODE(p.parent.stat().st_mode),0o700)
            return 0
        self.execute_hook=run
        report=self.start();self.assertEqual(len(proposals),1)
        self.assertEqual(report['applications'][0]['status'],'settings-updated')
        self.assertFalse(proposals[0].exists())
        raw=self.reports()[0].read_text();self.assertNotIn('private-test-secret',raw)
        self.assertNotIn('command',raw);self.assertNotIn('--proposal',raw)
        self.assertEqual(stat.S_IMODE(self.reports()[0].stat().st_mode),0o600)

    def test_stack_primary_and_member_selection_are_not_executed_twice(self):
        self.seed(2401,primary=2401,members=[2401,2403]);self.seed(2403,primary=2401)
        self.rows=[{'vmid':2401,'title':'Stack'},{'vmid':2403,'title':'Database'}]
        report=self.start();self.assertEqual(self.executed,[2401]);self.assertEqual(len(report['applications']),1)
        self.assertEqual(self.carry.call_args.kwargs['vmids'],[2401,2403])

    def test_pending_metadata_during_preparation_aborts_before_any_helper(self):
        r=instances.read(self.root,2402);r['pending_stack_transaction']='journal'
        instances.write(instances.location(self.root,2402),r)
        self.assertIsNone(self.start());self.run.assert_not_called()

    def test_report_separates_preparation_execution_and_step_times(self):
        report=self.start()
        self.assertGreaterEqual(report['preparation_seconds'],0)
        self.assertGreaterEqual(report['seconds'],sum(r['seconds']for r in report['applications']))
        for row in report['applications']:
            self.assertGreaterEqual(row['seconds'],sum(s['seconds']for s in row['steps']))
        self.assertIn('finished_at',report)


class PreparationIntegrationTests(unittest.TestCase):
    setUp = BatchTests.setUp
    seed = BatchTests.seed
    prepare = BatchTests.prepare
    execute = BatchTests.execute
    """The actual menu must collect lifecycle calls rather than execute them."""
    # Keep these focused cases separate from the queue-state tests above.
    def test_real_menu_collects_recommended_settings_and_update_without_applying_them(self):
        self.managing.stop()
        row=dict(self.rows[0],reason='matched',stack=False,pending=False,status='installed')
        steps=[]
        offer={'details':['Memory: 512 MiB'],'candidate':{'memory_mb':512}}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(management,'check_selected',return_value=row), \
             patch.object(management,'_selected_configuration',return_value=b'arch: amd64'), \
             patch('oci_instance_reconcile.propose',return_value=None), \
             patch.object(recommended,'latest_template',return_value={'id':'fixture'}), \
             patch.object(recommended,'recommendation',return_value=offer), \
             patch.object(host,'gpu_memory',return_value=0), \
             patch.object(host,'memory_total_mb',return_value=8192), \
             patch.object(host,'cpu_count',return_value=4), \
             patch.object(management,'_work_backup_ready',return_value=True), \
             patch.object(management,'_run_lifecycle') as lifecycle:
            self.assertTrue(management.manage_instance(ROOT,self.ui,row,action='update',runner=batch._collect(Path(folder),steps)))
            lifecycle.assert_not_called()
            self.assertEqual(len(steps),2)
            path=Path(steps[0]['command'][steps[0]['command'].index('--proposal')+1])
            self.assertEqual(json.loads(path.read_text())['candidate'],offer['candidate'])
            self.assertNotIn('--proposal',steps[1]['command'])
        self.assertFalse(path.exists())
        self.assertEqual(instances.read(self.root,2401)['observed']['image']['manifest_digest'],OLD)

    def test_fresh_pending_single_record_never_enters_interactive_recovery(self):
        self.managing.stop()
        row=dict(self.rows[0],reason='matched',stack=False,pending=True,status='updating')
        with patch.object(management,'check_selected',return_value=row),patch.object(management,'_run_lifecycle') as lifecycle:
            self.assertFalse(management.manage_instance(ROOT,self.ui,row,action='update',runner=Mock()))
            lifecycle.assert_not_called()

    def test_fresh_pending_stack_record_never_runs_recovery_during_preparation(self):
        self.seed(2401,primary=2401,members=[2401,2403]);self.seed(2403,primary=2401)
        r=instances.read(self.root,2401);r['pending_stack_transaction']='journal'
        instances.write(instances.location(self.root,2401),r)
        with patch.object(management,'_run_lifecycle') as lifecycle:
            self.assertFalse(management._manage_stack(ROOT,self.ui,self.rows[0],action='update',runner=Mock()))
            lifecycle.assert_not_called()


class ProcessTests(unittest.TestCase):
    def test_child_has_no_stdin_or_controlling_terminal(self):
        command=[sys.executable,'-c','import os,sys; assert sys.stdin.read()==""; '
                 '\ntry: os.open("/dev/tty",os.O_RDONLY)\nexcept OSError: sys.exit(0)\nsys.exit(1)']
        self.assertEqual(batch._run_command(command),0)

    def test_interrupt_terminates_only_the_owned_process_group(self):
        process=Mock(pid=912345);process.wait.side_effect=[KeyboardInterrupt,None];process.poll.return_value=None
        with patch.object(batch.subprocess,'Popen',return_value=process)as popen,patch.object(batch.os,'killpg')as kill:
            with self.assertRaises(KeyboardInterrupt):batch._run_command(['helper'])
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertEqual(popen.call_args.kwargs['stdin'],subprocess.DEVNULL)
        kill.assert_called_once_with(912345,signal.SIGTERM)

    def test_termination_handler_is_restored(self):
        before=signal.getsignal(signal.SIGTERM)
        with self.assertRaises(KeyboardInterrupt):
            with batch._interruptions():signal.raise_signal(signal.SIGTERM)
        self.assertEqual(signal.getsignal(signal.SIGTERM),before)


if __name__=='__main__':unittest.main()
