"""A completed OCI job needs real exit-zero proof, not stopped/CLI output."""
import contextlib
import copy
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'remote'))
import oci_compose_jobs as jobs

IID='55bb1839-f087-4b03-a9b8-75bec7537c9c'
DIGEST='sha256:'+'a'*64
IDENTITY={'vmid':4790,'installation_id':IID,'image_digest':DIGEST,'config_fingerprint':'f'*64}
PROOF={'raw_waitstatus':0,'exit_code':0,'fresh_start_observed':True,'protocol':'lxc-msg-native264'}
CONFIG=f'''description: OCI %3C!-- proxmenux-instance={IID} --%3E
rootfs: local-zfs:subvol-4790-disk-0,size=8G
entrypoint: sh -c 'exit 0'
env: TOKEN=literal-secret-value
unprivileged: 1
lxc.init.uid: 1000
lxc.init.gid: 1000
mp0: /mnt/test/shared,mp=/data,backup=0,size=8G
cores: 1
memory: 256
tags: temporary
'''


def pack(kind,name,value):return jobs.FRAME.pack(kind,str(name).encode(),value)


class FakeProcess:
    def __init__(self,rc=255):self.returncode=rc
    def poll(self):return self.returncode
    def wait(self,timeout=None):return self.returncode
    def terminate(self):self.returncode=-15
    def kill(self):self.returncode=-9


class NativeExitTests(unittest.TestCase):
    def attempt(self, events):
        receiver,sender=socket.socketpair()
        with receiver,sender:
            receiver.setblocking(False)
            @contextlib.contextmanager
            def subscription():yield receiver,{'protocol':'test-native-frames'}
            def start(*args,**kwargs):
                sender.sendall(b''.join(pack(*event) for event in events))
                return FakeProcess()
            with patch.object(jobs,'_subscription',subscription), \
                 patch.object(jobs.subprocess,'Popen',side_effect=start), \
                 patch.object(jobs,'_status',return_value='stopped'):
                return jobs._run_attempt(4790,time.monotonic()+.2)

    def test_exit_zero_is_proven_even_when_pct_start_loses_the_fast_pid(self):
        proof=self.attempt([(0,4790,1),(0,4790,2),(2,4790,0)])
        self.assertEqual(proof['raw_waitstatus'],0)
        self.assertEqual(proof['pct_start_returncode'],255)

    def test_nonzero_and_sigkill_never_become_completed(self):
        for raw in (7<<8,9):
            with self.subTest(raw=raw),self.assertRaises(jobs.JobError):
                self.attempt([(0,4790,1),(0,4790,2),(2,4790,raw)])

    def test_stopped_or_missing_exit_is_not_success(self):
        with self.assertRaisesRegex(jobs.JobError,'timed out'):
            self.attempt([(0,4790,1),(0,4790,2),(0,4790,0)])

    def test_exit_without_a_fresh_start_event_is_rejected(self):
        with self.assertRaisesRegex(jobs.JobError,'fresh'):
            self.attempt([(2,4790,0)])

    def test_unrelated_guest_exit_zero_does_not_complete_this_job(self):
        with self.assertRaisesRegex(jobs.JobError,'timed out'):
            self.attempt([(0,4790,1),(2,123,0),(0,4790,0)])

    def test_partial_frames_are_buffered_and_unknown_abi_is_rejected(self):
        data=pack(2,4790,1792)
        self.assertEqual(jobs._frames(data[:8]),([],data[:8]))
        self.assertEqual(jobs._frames(data),([(2,'4790',1792)],b''))
        with self.assertRaises(jobs.JobError):jobs._frames(pack(100,4790,0))


class IdentityAndTrustTests(unittest.TestCase):
    def test_command_environment_user_and_mount_changes_invalidate_fingerprint(self):
        first=jobs.config_fingerprint(CONFIG)
        for before,after in [('exit 0','exit 7'),('literal-secret-value','changed'),
                             ('lxc.init.uid: 1000','lxc.init.uid: 1001'),('/mnt/test/shared','/mnt/test/other')]:
            with self.subTest(before=before):
                self.assertNotEqual(jobs.config_fingerprint(CONFIG.replace(before,after)),first)
        altered=CONFIG.replace('cores: 1','cores: 4').replace('memory: 256','memory: 4096').replace('tags: temporary','tags: renamed').replace('size=8G','size=16G')
        self.assertEqual(jobs.config_fingerprint(altered),first)
        self.assertNotIn('literal-secret-value',first)

    def test_instance_uuid_digest_and_container_marker_are_bound(self):
        record={'vmid':4790,'installation_id':IID,'observed':{'resolved_registry_digest':DIGEST}}
        spec={'installation_id':IID,'image_digest':DIGEST}
        def read(path):return json.dumps(record) if str(path).endswith('.json') else CONFIG
        with patch.object(jobs,'_trusted_read',side_effect=read), patch.object(jobs,'_config_text',return_value=CONFIG):
            result=jobs.current_identity(4790,spec)
            self.assertEqual(result['installation_id'],IID)
            with self.assertRaises(jobs.JobError):jobs.current_identity(4790,{**spec,'image_digest':'sha256:'+'b'*64})
            with self.assertRaises(jobs.JobError):jobs.current_identity(4790,{**spec,'installation_id':str(__import__('uuid').uuid4())})
            with self.assertRaises(jobs.JobError):jobs.current_identity(4790,{**spec,'expected_config_fingerprint':'b'*64})
        with patch.object(jobs,'_trusted_read',return_value=json.dumps(record)), patch.object(jobs,'_config_text',return_value=CONFIG.replace(IID,'another-instance')):
            with self.assertRaises(jobs.JobError):jobs.current_identity(4790,spec)

    def test_staged_digest_requires_matching_child_and_stack_transactions(self):
        txid='a'*32
        stackid='b'*32
        journal=jobs.INSTANCE_ROOT/'4790'/'transactions'/txid/'transaction.json'
        parent=jobs.INSTANCE_ROOT/'4792'/'stack-transactions'/stackid/'transaction.json'
        new_digest='sha256:'+'b'*64
        record={'vmid':4790,'installation_id':IID,'status':'updating',
                'observed':{'resolved_registry_digest':DIGEST},'transaction_id':txid,
                'pending_transaction':str(journal),'pending_stack_transaction':str(parent)}
        child={'schema_version':1,'id':txid,'vmid':4790,'phase':'candidate-installed',
               'record':{'installation_id':IID},'registry_digest':new_digest,
               'staged_config_sha256':__import__('hashlib').sha256(CONFIG.encode()).hexdigest(),
               'coordinated':{'journal':str(parent),'id':'active-stack-operation'}}
        stack={'schema_version':1,'id':'active-stack-operation','phase':'starting',
               'plan':{'members':[{'vmid':4790,'installation_id':IID}]}}
        def read(path):
            return json.dumps(child if path==journal else stack if path==parent else record)
        with patch.object(jobs,'_trusted_read',side_effect=read),patch.object(jobs,'_config_text',return_value=CONFIG):
            spec=jobs.job_spec_from_record(record,CONFIG)
            self.assertEqual(spec['image_digest'],new_digest)
            self.assertEqual(jobs.current_identity(4790,spec)['image_digest'],new_digest)
            child['staged_config_sha256']='0'*64
            with self.assertRaises(jobs.JobError):jobs.current_identity(4790,spec)
            child['staged_config_sha256']=__import__('hashlib').sha256(CONFIG.encode()).hexdigest()
            stack['id']='another-operation'
            with self.assertRaises(jobs.JobError):jobs.current_identity(4790,spec)
            stack['id']='active-stack-operation';stack['phase']='replacing'
            self.assertEqual(jobs.job_spec_from_record(record,CONFIG)['image_digest'],new_digest)
            with self.assertRaises(jobs.JobError):jobs.current_identity(4790,spec)

    def test_restore_generation_changes_identity_even_with_identical_config(self):
        record={'vmid':4790,'installation_id':IID,'observed':{'resolved_registry_digest':DIGEST}}
        spec={'installation_id':IID,'image_digest':DIGEST}
        with patch.object(jobs,'_trusted_read',side_effect=lambda path:json.dumps(record)),patch.object(jobs,'_config_text',return_value=CONFIG):
            before=jobs.current_identity(4790,spec)
            record['recovered_at']='2026-10-28T12:00:00Z'
            after=jobs.current_identity(4790,spec)
        self.assertEqual(before['config_fingerprint'],after['config_fingerprint'])
        self.assertNotEqual(before,after)

    def test_metadata_final_symlinks_and_world_writes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'record';source.write_text('{}');source.chmod(0o600)
            link=Path(directory)/'link';link.symlink_to(source)
            self.assertEqual(jobs._trusted_read(source,owner=os.getuid()),'{}')
            with self.assertRaises(OSError):jobs._trusted_read(link,owner=os.getuid())
            source.chmod(0o666)
            with self.assertRaises(jobs.JobError):jobs._trusted_read(source,owner=os.getuid())

    def test_socket_name_is_the_source_verified_lxc_hash(self):
        self.assertEqual(jobs._socket_name(),'lxc/ad055575fe28ddd5//var/lib/lxc')


class CompletionCacheTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        for name,replacement in [('STATE_ROOT',self.root),('_root',lambda:None),
                                 ('_job_lock',lambda *args:contextlib.nullcontext()),
                                 ('_status',lambda *args:'stopped')]:
            item=patch.object(jobs,name,replacement);item.start();self.addCleanup(item.stop)
        item=patch.object(jobs,'current_identity',return_value=IDENTITY);item.start();self.addCleanup(item.stop)
        item=patch.object(jobs,'_read_cache',side_effect=lambda path:json.loads(path.read_text()) if path.exists() else None);item.start();self.addCleanup(item.stop)
        self.spec={'installation_id':IID,'image_digest':DIGEST,'timeout_seconds':30}

    def test_only_matching_proven_cache_skips_job_start(self):
        with patch.object(jobs,'_run_attempt',return_value=PROOF) as attempt:
            self.assertFalse(jobs.ensure_completed(4790,self.spec)['cached'])
            self.assertTrue(jobs.ensure_completed(4790,self.spec)['cached'])
            attempt.assert_called_once()
        cache=json.loads((self.root/'4790.json').read_text())
        self.assertEqual(cache['identity'],IDENTITY)
        self.assertEqual(cache['proof']['raw_waitstatus'],0)

    def test_changed_image_identity_or_config_never_reuses_old_completion(self):
        cache={'schema':1,'status':'completed','identity':{**IDENTITY,'image_digest':'sha256:'+'b'*64},'proof':PROOF}
        (self.root/'4790.json').write_text(json.dumps(cache))
        with patch.object(jobs,'_run_attempt',return_value=PROOF) as attempt:
            self.assertFalse(jobs.ensure_completed(4790,self.spec)['cached'])
            attempt.assert_called_once()

    def test_force_failure_invalidates_earlier_success(self):
        with patch.object(jobs,'_run_attempt',return_value=PROOF):jobs.ensure_completed(4790,self.spec)
        with patch.object(jobs,'_run_attempt',side_effect=jobs.JobError('signal 9')):
            with self.assertRaises(jobs.JobError):jobs.ensure_completed(4790,self.spec,force=True)
        self.assertFalse((self.root/'4790.json').exists())

    def test_remove_forgets_only_matching_installation_uuid(self):
        with patch.object(jobs,'_run_attempt',return_value=PROOF):jobs.ensure_completed(4790,self.spec)
        other='45e85d70-4e28-416f-8ae8-325ae9153272'
        self.assertFalse(jobs.forget_completed(4790,other))
        self.assertTrue((self.root/'4790.json').exists())
        self.assertTrue(jobs.forget_completed(4790,IID))
        self.assertFalse((self.root/'4790.json').exists())
        self.assertFalse(jobs.forget_completed(4790,IID))

    def test_running_job_and_bad_timeout_are_refused(self):
        with patch.object(jobs,'_status',return_value='running'),patch.object(jobs,'_run_attempt') as attempt:
            with self.assertRaisesRegex(jobs.JobError,'already running'):jobs.ensure_completed(4790,self.spec)
            attempt.assert_not_called()
        for timeout in (True,0,29,3601,'300'):
            with self.subTest(timeout=timeout),self.assertRaises(jobs.JobError):
                jobs.ensure_completed(4790,{**self.spec,'timeout_seconds':timeout})


if __name__=='__main__':unittest.main()
