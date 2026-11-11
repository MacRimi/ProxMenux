"""Read-only native worker lifecycle, protocol, fresh reads and CLI fallbacks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'remote'))
import oci_native_reads as native
import oci_installation_state as state
import oci_instance_transaction as tx

SERVER = '''import json,sys
count=0
for line in sys.stdin:
 request=json.loads(line);count+=1
 op=request['op']
 result=([{'vmid':110,'type':'lxc','node':'test'}]if op=='resources'else
         []if op=='ha'else 'status: running\\n'if op=='status'else
         'cores: '+str(count)+'\\ndescription: fixture-secret\\n')
 print(json.dumps({'id':request['id'],'ok':True,'result':result}),flush=True)
'''


class ClassificationTests(unittest.TestCase):
    def test_only_exact_native_read_forms_are_recognized(self):
        self.assertEqual(native.request_for(('pct','config','110')),{'op':'config','vmid':110})
        self.assertEqual(native.request_for(('pct','status','110')),{'op':'status','vmid':110})
        self.assertEqual(native.request_for(('pvesh','get','/cluster/resources','--type','vm','--output-format','json')),{'op':'resources'})
        self.assertEqual(native.request_for(('pvesh','get','/cluster/ha/resources','--output-format','json')),{'op':'ha'})

    def test_writes_extra_flags_paths_and_invalid_ids_keep_the_cli(self):
        for args in [('pct','set','110','--memory','512'),('pct','destroy','110'),
                     ('pct','config','110','--current'),('pct','status','110','--verbose'),
                     ('/usr/sbin/pct','config','110'),('pct','config','../110'),
                     ('pct','config','99'),('pct','config','0110'),('pct','config','1000000000'),
                     ('pvesh','set','/cluster/resources'),('pvesh','get','/cluster/resources')]:
            with self.subTest(args=args):self.assertIsNone(native.request_for(args))

    def test_disabled_or_missing_native_libraries_use_the_cli(self):
        with patch.dict(os.environ,{'PROXMENUX_OCI_NATIVE_READS':'0'}),patch.object(os,'geteuid',return_value=0):
            self.assertFalse(native.supported())
        with patch.object(os,'geteuid',return_value=1000):self.assertFalse(native.supported())

    def test_outside_an_operation_never_starts_a_worker(self):
        with patch.object(native.subprocess,'Popen') as popen:
            self.assertIsNone(native.read(('pct','config','110')))
            popen.assert_not_called()


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.real_popen=subprocess.Popen;self.children=[];self.server=SERVER
        self.support=patch.object(native,'supported',return_value=True);self.support.start();self.addCleanup(self.support.stop)
        self.popen=patch.object(native.subprocess,'Popen',side_effect=self.launch);self.factory=self.popen.start();self.addCleanup(self.popen.stop)
        self.addCleanup(self.reap)

    def launch(self,argv,**kwargs):
        self.assertEqual(argv,['/usr/bin/perl',str(native.HELPER)])
        self.assertEqual(kwargs['stderr'],subprocess.DEVNULL)
        self.assertTrue(kwargs['close_fds']);self.assertFalse(kwargs.get('start_new_session',False))
        child=self.real_popen([sys.executable,'-u','-c',self.server],**kwargs)
        self.children.append(child);return child

    def reap(self):
        for child in self.children:
            if child.poll() is None:child.kill();child.wait()
            for stream in (child.stdin,child.stdout):
                if stream and not stream.closed:stream.close()

    def read(self):return native.read(('pct','config','110'))

    def test_repeated_reads_reuse_imports_not_results_and_hide_config_from_metrics(self):
        logs=[]
        with native.session(log=logs.append):
            first=self.read();second=self.read()
            self.assertTrue(first.startswith(b'cores: 1\n'));self.assertTrue(second.startswith(b'cores: 2\n'))
            self.assertEqual(len(self.children),1)
            self.assertEqual(os.getpgid(self.children[0].pid),os.getpgrp())
        self.assertIsNotNone(self.children[0].poll())
        self.assertNotIn('fixture-secret',''.join(logs));self.assertNotIn('description',''.join(logs))
        self.assertEqual(json.loads(logs[0].partition(': ')[2])['requests'],{'config':2})

    def test_nested_operations_share_one_child_and_outer_scope_closes_it(self):
        with native.session():
            original=native._ACTIVE.get();self.read()
            with native.session():
                self.assertIs(original,native._ACTIVE.get());self.read()
            self.assertIsNone(self.children[0].poll())
        self.assertIsNone(native._ACTIVE.get());self.assertIsNotNone(self.children[0].poll())

    def test_separate_operations_create_independent_workers(self):
        with native.session():self.read()
        with native.session():self.read()
        self.assertEqual(len(self.children),2)
        self.assertTrue(all(c.poll() is not None for c in self.children))

    def test_structured_inventory_and_ha_keep_the_cli_json_contract(self):
        with native.session():
            data=native.read(('pvesh','get','/cluster/resources','--type','vm','--output-format','json'))
            self.assertEqual(json.loads(data),[{'vmid':110,'type':'lxc','node':'test'}])
            self.assertEqual(json.loads(native.read(('pvesh','get','/cluster/ha/resources','--output-format','json'))),[])
            self.assertEqual(native.read(('pct','status','110')),b'status: running\n')

    def test_writes_never_reach_the_worker(self):
        with native.session():self.assertIsNone(native.read(('pct','set','110','--cores','2')))
        self.factory.assert_not_called()

    def test_worker_is_not_inherited_by_another_process(self):
        with native.session():
            native._ACTIVE.get().owner=-1
            self.assertIsNone(self.read())
        self.factory.assert_not_called()

    def test_exception_closes_the_worker_and_restores_the_scope(self):
        with self.assertRaises(RuntimeError):
            with native.session():self.read();raise RuntimeError('controlled')
        self.assertIsNone(native._ACTIVE.get());self.assertIsNotNone(self.children[0].poll())

    def test_interrupt_closes_the_worker(self):
        with self.assertRaises(KeyboardInterrupt):
            with native.session():
                self.read()
                with patch.object(native.Reader,'_line',side_effect=KeyboardInterrupt):self.read()
        self.assertIsNone(native._ACTIVE.get());self.assertIsNotNone(self.children[0].poll())

    def test_dead_worker_switches_permanently_to_fresh_cli_without_stale_results(self):
        with native.session():
            self.assertIsNotNone(self.read())
            self.children[0].kill();self.children[0].wait()
            self.assertIsNone(self.read());self.assertIsNone(self.read())
        self.assertEqual(len(self.children),1)

    def test_wrong_sequence_is_rejected(self):
        self.server=SERVER.replace("'id':request['id']","'id':request['id']+1")
        with native.session():self.assertIsNone(self.read());self.assertTrue(native._ACTIVE.get().broken)

    def test_wrong_result_type_is_rejected(self):
        self.server=SERVER.replace("'result':result","'result':{'unexpected':'fixture-secret'}")
        with native.session():self.assertIsNone(self.read())

    def test_api_failure_is_not_logged_or_returned_as_data(self):
        self.server=SERVER.replace("'ok':True","'ok':False")
        logs=[]
        with native.session(log=logs.append):self.assertIsNone(self.read());self.assertIsNone(self.read())
        self.assertNotIn('fixture-secret',''.join(logs));self.assertEqual(len(self.children),1)

    def test_bad_json_partial_reply_and_unexpected_output_are_rejected(self):
        for output in ['not-json\\n','{}','{}\\n{}\\n']:
            self.server='import sys;sys.stdin.readline();sys.stdout.write('+repr(output.replace('\\n','\n'))+');sys.stdout.flush()'
            with native.session():self.assertIsNone(self.read())

    def test_oversized_reply_is_rejected(self):
        self.server='import sys;sys.stdin.readline();print("x"*1024,flush=True)'
        with patch.object(native,'MAX_REPLY',128),native.session():self.assertIsNone(self.read())

    def test_stalled_reply_times_out_and_closes(self):
        self.server='import sys,time;sys.stdin.readline();time.sleep(0.5)'
        with patch.object(native,'TIMEOUT',0.2),native.session():self.assertIsNone(self.read())
        self.assertIsNotNone(self.children[0].poll())

    def test_general_command_uses_worker_but_keeps_writes_on_cli(self):
        with native.session(),patch.object(state.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'cli-write',b'')) as run:
            self.assertTrue(state.command('pct','config','110').startswith(b'cores: 1'))
            run.assert_not_called()
            self.assertEqual(state.command('pct','set','110','--memory','512'),b'cli-write')
            run.assert_called_once()

    def test_transaction_command_does_not_log_private_response(self):
        with native.session(),patch.object(tx,'log') as log:
            result=tx.run('pct','config','110')
            self.assertIn(b'fixture-secret',result)
            self.assertFalse(any('fixture-secret'in str(call)for call in log.call_args_list))

    def test_api_error_runs_cli_afresh_and_does_not_restart_worker(self):
        self.server=SERVER.replace("'ok':True","'ok':False")
        with native.session(),patch.object(state.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'fresh-cli',b'')) as run:
            self.assertEqual(state.command('pct','config','110'),b'fresh-cli')
            self.assertEqual(state.command('pct','config','110'),b'fresh-cli')
            self.assertEqual(run.call_count,2)
        self.assertEqual(len(self.children),1)


if __name__=='__main__':unittest.main()
