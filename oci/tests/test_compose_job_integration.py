"""One-shot dependencies use the persistent verified helper, never bare pct start."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'remote'))
sys.path.insert(0,str(ROOT/'src'))
import install_generic_stack as stack
import oci_compose_jobs as jobs
from proxmenux_oci import installer

IID='55bb1839-f087-4b03-a9b8-75bec7537c9c'
DIGEST='sha256:'+'a'*64
CONFIG=f'description: proxmenux-instance={IID}\nrootfs: local-zfs:subvol-4791-disk-0,size=8G\nentrypoint: sh -c true\n'
RECORD={'vmid':4791,'installation_id':IID,'observed':{'resolved_registry_digest':DIGEST}}


class JobInstallIntegrationTests(unittest.TestCase):
    def test_installer_binds_completed_job_after_actual_runtime_configuration(self):
        service={'vmid':4791,'deployment':{'onboot':True},'healthcheck':{'type':'completed','timeout_seconds':300}}
        def run(*args):
            if args==('pct','config',4791):return CONFIG
            self.assertEqual(args,('pct','set',4791,'--onboot','0'));return ''
        with patch.object(stack,'run',side_effect=run),patch.object(stack.oci_instances,'read',return_value=RECORD):
            stack.bind_completed_jobs([service])
        self.assertFalse(service['deployment']['onboot'])
        self.assertEqual(service['healthcheck']['job'],jobs.job_spec_from_record(RECORD,CONFIG))

    def test_local_transport_really_copies_standalone_job_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            template=Path(directory)/'template.json';template.write_text('{}')
            def inspect(command,*args):
                staged=Path(command[1]).parent/'oci_compose_jobs.py'
                self.assertEqual(staged.read_bytes(),(ROOT/'remote/oci_compose_jobs.py').read_bytes())
                return None
            with patch.object(installer,'_stream_process',side_effect=inspect):
                installer._run_remote_install(ROOT,template,{'deployment_kind':'generic-multi-lxc-stack'},'local',True)

    def test_ssh_transport_really_archives_standalone_job_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            template=Path(directory)/'template.json';template.write_text('{}')
            def inspect(command,data):
                self.assertEqual(command[0],'ssh')
                with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
                    self.assertEqual(archive.extractfile('oci_compose_jobs.py').read(),(ROOT/'remote/oci_compose_jobs.py').read_bytes())
                return None
            with patch.object(installer,'_stream_process',side_effect=inspect):
                installer._run_remote_install(ROOT,template,{'deployment_kind':'generic-multi-lxc-stack'},'test-node',True)

    @unittest.skipUnless(shutil.which('jq'),'jq required')
    def test_hook_contract_rejects_incomplete_or_unsafe_job_spec(self):
        text=(ROOT/'remote/stack_dependency_hook.sh').read_text()
        start=text.index("  jq -e '")+len("  jq -e '");end=text.index("\n  ' \"$source_config\"",start)
        expression=text[start:end]
        spec=jobs.job_spec_from_record(RECORD,CONFIG)
        contract={'schema':1,'dependencies':[{'vmid':4791,'label':'migration','healthcheck':{'type':'completed','timeout_seconds':300,'job':spec}}]}
        good=subprocess.run(['jq','-e',expression],input=json.dumps(contract),text=True,capture_output=True)
        self.assertEqual(good.returncode,0,good.stderr)
        contract['dependencies'][0]['healthcheck']['job']['image_digest']='latest'
        bad=subprocess.run(['jq','-e',expression],input=json.dumps(contract),text=True,capture_output=True)
        self.assertNotEqual(bad.returncode,0)

    @unittest.skipUnless(shutil.which('jq') and shutil.which('flock'),'jq/flock required')
    def test_hook_calls_completed_helper_without_starting_job_directly(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);priv=root/'priv';priv.mkdir();locks=root/'locks';locks.mkdir();binary=root/'bin';binary.mkdir()
            helper=root/'jobs.py';helper.write_text("import json,os,sys\nfrom pathlib import Path\nPath(os.environ['JOB_CALLS']).write_text(json.dumps(sys.argv[1:]))\n")
            pct=binary/'pct';pct.write_text('#!/bin/sh\n[ "$1" = config ] && exit 0\necho "UNEXPECTED_PCT_START" >&2\nexit 99\n');pct.chmod(0o755)
            stat=binary/'stat';stat.write_text('#!/bin/sh\n[ "$2" = %u ] && { echo 0; exit 0; }\n[ "$2" = %a ] && { echo 755; exit 0; }\nexit 1\n');stat.chmod(0o755)
            spec=jobs.job_spec_from_record(RECORD,CONFIG)
            (priv/'proxmenux-stack-4790.json').write_text(json.dumps({'schema':1,'dependencies':[{'vmid':4791,'label':'migration','healthcheck':{'type':'completed','timeout_seconds':300,'job':spec}}]}))
            text=(ROOT/'remote/stack_dependency_hook.sh').read_text()
            functions=text[text.index('die() {'):text.index('\nif [[ ${1:-} == "--install"')]
            functions=functions.replace('/etc/pve/priv',str(priv)).replace('/run/lock',str(locks))
            command='COMPOSE_JOB_HELPER='+str(helper)+'\n'+functions+'\nstart_dependencies 4790\n'
            calls=root/'calls.json';env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],'JOB_CALLS':str(calls)}
            result=subprocess.run(['bash','-c',command],env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(calls.read_text())[:2],['ensure','4791'])
            self.assertNotIn('UNEXPECTED_PCT_START',result.stderr)


if __name__=='__main__':unittest.main()
