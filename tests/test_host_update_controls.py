"""Actual version/guard helpers and authenticated Flask routes; no real reboot."""
import fcntl
import importlib.util
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'AppImage/scripts'))
import host_update_controls as controls
import proxmenux_version_status as versions


class VersionStatus(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root_patch = patch.object(versions, 'ROOT', self.root); self.root_patch.start(); self.addCleanup(self.root_patch.stop)
        versions._cache.clear()
        (self.root/'version.txt').write_text('1.2.7\n')
        self.now = 1000.
        self.clock = patch.object(versions.time, 'monotonic', side_effect=lambda:self.now); self.clock.start(); self.addCleanup(self.clock.stop)
        self.remote = Mock(return_value=io.BytesIO(b'1.2.8\n'))
        self.network = patch.object(versions.urllib.request, 'urlopen', self.remote); self.network.start(); self.addCleanup(self.network.stop)

    def test_real_contract_stable_and_beta_use_only_fixed_urls(self):
        result = versions.version_status()
        self.assertEqual((result['state'], result['installed'], result['available']), ('available','1.2.7','1.2.8'))
        self.assertEqual(self.remote.call_args.args[0].full_url, versions.URLS['stable'])
        (self.root/'beta_version.txt').write_text('1.2.9')
        self.remote.return_value = io.BytesIO(b'1.2.10')
        result = versions.version_status()
        self.assertEqual((result['channel'], result['state'], result['available']), ('beta','available','1.2.10'))
        self.assertEqual(self.remote.call_args.args[0].full_url, versions.URLS['beta'])

    def test_fresh_cache_then_ttl_boundary_refetch(self):
        versions.version_status()
        for age in (0,1799.999):
            self.now = 1000+age
            self.assertEqual(versions.version_status()['state'],'available')
        self.assertEqual(self.remote.call_count,1)
        self.now=2800
        self.remote.return_value = io.BytesIO(b'1.2.7')
        self.assertEqual(versions.version_status()['state'],'current')
        self.assertEqual(self.remote.call_count,2)
        self.now=4600.001;self.remote.return_value=io.BytesIO(b'1.2.9')
        self.assertEqual(versions.version_status()['state'],'available')

    def test_failed_refresh_keeps_last_known_and_retries_after_sixty_seconds(self):
        first=versions.version_status()
        self.now=2800;self.remote.side_effect=OSError('fixture timeout')
        failed=versions.version_status()
        self.assertEqual(failed['state'],'unknown')
        self.assertEqual(failed['available'],first['available'])
        self.assertEqual(failed['checked_at'],first['checked_at'])
        self.now=2859.999;versions.version_status();self.assertEqual(self.remote.call_count,2)
        self.now=2860;versions.version_status();self.assertEqual(self.remote.call_count,3)

    def test_missing_or_invalid_installed_never_probes_network(self):
        for text in ('', 'junk', '1.2.7\npartial', '1.2.7-rc1'):
            (self.root/'version.txt').write_text(text)
            self.assertEqual(versions.version_status()['state'],'unknown')
        (self.root/'version.txt').unlink()
        self.assertEqual(versions.version_status()['state'],'unknown')
        self.remote.assert_not_called()

    def test_bad_remote_and_http_failure_never_mean_current_or_write_local_files(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        for content in (b'',b'<html>error</html>',b'1.2.8\npartial',b'1.'+b'9'*128,b'\xff'):
            versions._cache.clear(); self.remote.return_value=io.BytesIO(content)
            self.assertEqual(versions.version_status()['state'],'unknown')
        versions._cache.clear(); self.remote.side_effect=TimeoutError('fixture')
        self.assertEqual(versions.version_status()['state'],'unknown')
        self.assertEqual({p.name:p.read_bytes() for p in self.root.iterdir()},before)

    def test_installed_version_change_and_numeric_comparison(self):
        versions.version_status()
        (self.root/'version.txt').write_text('1.2.10')
        self.assertEqual(versions.version_status()['state'],'current')
        self.assertEqual(self.remote.call_count,1)
        self.assertEqual(versions._version('1.2'),versions._version('1.2.0'))


class RebootGuards(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name); self.lock=self.root/'update.lock'
        (self.root/'proc').mkdir()
        self.proc=patch.object(controls,'PROC',self.root/'proc');self.proc.start();self.addCleanup(self.proc.stop)
        boot=self.root/'boot_id';boot.write_text('fixture-boot')
        self.boot=patch.object(controls,'BOOT_ID',boot);self.boot.start();self.addCleanup(self.boot.stop)
        self.a=patch.object(controls,'LOCK',str(self.lock)); self.a.start(); self.addCleanup(self.a.stop)
        self.jobs=patch.object(controls,'list_jobs',return_value=[]).start()
        self.probe=patch.object(controls,'reboot_status',return_value={'state':'required'}).start()
        self.addCleanup(patch.stopall)

    def test_active_attention_starting_and_unreadable_jobs_block_before_kernel_probe(self):
        for state in ('starting','running','attention','finalizing',None):
            self.jobs.return_value=[{'state':state}]
            self.assertFalse(controls.reboot_context()['allowed'])
        self.jobs.side_effect=OSError('fixture missing registry')
        self.assertFalse(controls.reboot_context()['allowed'])
        self.probe.assert_not_called()

    def test_lock_probe_does_not_create_missing_file_and_symlink_is_refused(self):
        self.assertTrue(controls.reboot_context()['allowed'])
        self.assertFalse(self.lock.exists())
        self.lock.symlink_to(self.root/'missing')
        self.probe.reset_mock()
        self.assertFalse(controls.reboot_context()['allowed'])
        self.probe.assert_not_called()

    def test_real_shared_flock_stops_probe_and_final_command_before_any_effect(self):
        self.lock.touch()
        marker=self.root/'inert-action'
        command=list(controls.COMMAND)
        self.assertEqual(command[5:],['/usr/bin/python3','/usr/local/share/proxmenux/monitor-app/usr/bin/host_update_controls.py','--execute-reboot'])
        command[4]=str(self.lock);command[5:]=['/bin/sh','-c','printf reached > '+shlex.quote(str(marker))]
        with self.lock.open('r') as owner:
            fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertFalse(controls.reboot_context()['allowed'])
            self.probe.assert_not_called()
            self.assertEqual(subprocess.run(command,check=False).returncode,75)
            self.assertFalse(marker.exists())
        self.assertEqual(subprocess.run(command,check=False).returncode,0)
        self.assertEqual(marker.read_text(),'reached')

    def test_current_unknown_and_read_failures_never_allow_restart(self):
        for state in ('current','unknown','not_applicable'):
            self.probe.return_value={'state':state}
            self.assertFalse(controls.reboot_context()['allowed'])

    def test_direct_package_process_blocks_before_kernel_probe(self):
        path=self.root/'proc/123';path.mkdir();(path/'comm').write_text('apt-get\n')
        self.assertFalse(controls.reboot_context()['allowed'])
        self.probe.assert_not_called()

    def test_worker_package_locks_missing_or_unknown_kernel_never_reboot(self):
        paths=[str(self.root/name) for name in ('frontend','backend')]
        with patch.object(controls,'PACKAGE_LOCKS',paths),patch.object(controls.subprocess,'run') as reboot,patch.object(controls.time,'sleep') as delay:
            self.assertEqual(controls.execute_reboot(),75)
            reboot.assert_not_called();delay.assert_not_called()
            for path in paths:Path(path).touch()
            self.probe.return_value={'state':'unknown'}
            self.assertEqual(controls.execute_reboot(),77)
            reboot.assert_not_called()
            self.probe.return_value={'state':'required'}
            self.assertEqual(controls.execute_reboot(),0)
            reboot.assert_called_once_with(['/bin/systemctl','reboot'],check=True,timeout=10)
            delay.assert_called_once_with(60)

    def test_actual_posix_package_lock_blocks_worker_before_reboot(self):
        paths=[str(self.root/name) for name in ('frontend','backend')]
        for path in paths:Path(path).touch()
        # A separate process holds the same POSIX lock, just as APT does.
        code='import fcntl,sys,time; f=open(sys.argv[1],"r+"); fcntl.lockf(f,fcntl.LOCK_EX); print("locked",flush=True); time.sleep(5)'
        child=subprocess.Popen([sys.executable,'-c',code,paths[0]],stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'locked')
            with patch.object(controls,'PACKAGE_LOCKS',paths),patch.object(controls.subprocess,'run') as reboot:
                self.assertEqual(controls.execute_reboot(),75)
                reboot.assert_not_called()
        finally:
            child.terminate();child.wait(timeout=2);child.stdout.close()


class Routes(unittest.TestCase):
    def setUp(self):
        auth=ModuleType('auth_manager')
        auth.load_auth_config=lambda:{'enabled':True}
        auth.verify_token=lambda token:'fixture' if token=='admin' else None
        auth.verify_token_full=lambda token:('fixture','full_admin') if token=='admin' else ('fixture','read_only') if token=='reader' else (None,None)
        patches={'auth_manager':auth,'health_monitor':SimpleNamespace(health_monitor=object()),
                 'health_persistence':SimpleNamespace(health_persistence=object()),'mount_monitor':ModuleType('mount_monitor')}
        self.modules=patch.dict(sys.modules,patches);self.modules.start();self.addCleanup(self.modules.stop)
        def load(name,filename):
            spec=importlib.util.spec_from_file_location(name,ROOT/'AppImage/scripts'/filename)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
        middleware=load('controls_middleware','jwt_middleware.py')
        self.mw=patch.dict(sys.modules,{'jwt_middleware':middleware});self.mw.start();self.addCleanup(self.mw.stop)
        routes=load('controls_routes','flask_health_routes.py')
        self.app=Flask(__name__);self.app.register_blueprint(routes.health_bp)
        self.run=Mock(return_value=(True,{}));self.state=Mock(return_value={'state':'running'})
        self.app.extensions['host_update_power']={'run':self.run,'state':self.state}
        self.context=patch.object(controls,'reboot_context',return_value={'allowed':True,'reason':'required','boot_id':'fixture-boot'}).start()
        self.version=patch.object(versions,'version_status',return_value={'state':'unknown'}).start()
        self.addCleanup(patch.stopall)
        self.client=self.app.test_client()
        import socket
        self.body={'confirm':True,'hostname':socket.gethostname(),'boot_id':'fixture-boot'}

    def test_denied_auth_and_methods_do_not_probe_or_launch(self):
        for token in (None,'bad','reader'):
            headers={'Authorization':'Bearer '+token} if token else {}
            response=self.client.post('/api/health/reboot-after-update',json=self.body,headers=headers)
            self.assertEqual(response.status_code,403 if token=='reader' else 401)
        self.assertEqual(self.client.get('/api/health/reboot-after-update').status_code,405)
        self.context.assert_not_called();self.run.assert_not_called()
        self.assertEqual(self.client.get('/api/health/proxmenux-version').status_code,401)
        self.version.assert_not_called()

    def test_invalid_or_missing_confirmation_and_wrong_host_have_zero_probes(self):
        for body in ({},{'confirm':'true'},dict(self.body,confirm=False),dict(self.body,hostname='another-host')):
            self.assertEqual(self.client.post('/api/health/reboot-after-update',json=body,headers={'Authorization':'Bearer admin'}).status_code,400)
        self.context.assert_not_called();self.run.assert_not_called()

    def test_busy_current_unknown_and_unconfigured_runner_never_launch(self):
        for reason in ('busy','current','unknown'):
            self.context.return_value={'allowed':False,'reason':reason,'boot_id':'fixture-boot'}
            self.assertEqual(self.client.post('/api/health/reboot-after-update',json=self.body,headers={'Authorization':'Bearer admin'}).status_code,409)
        self.app.extensions.clear();self.context.reset_mock()
        self.assertEqual(self.client.post('/api/health/reboot-after-update',json=self.body,headers={'Authorization':'Bearer admin'}).status_code,503)
        self.context.assert_not_called();self.run.assert_not_called()

    def test_stale_or_other_server_boot_identity_never_launches(self):
        self.assertEqual(self.client.post('/api/health/reboot-after-update',json=dict(self.body,boot_id='another-boot'),headers={'Authorization':'Bearer admin'}).status_code,409)
        self.run.assert_not_called()

    def test_allowed_confirmation_queues_only_fixed_guarded_action_and_preserves_existing_api(self):
        response=self.client.post('/api/health/reboot-after-update',json=self.body,headers={'Authorization':'Bearer admin'})
        self.assertEqual(response.status_code,202);self.assertTrue(response.json['accepted'])
        self.run.assert_called_once_with(controls.UNIT,list(controls.COMMAND),description='ProxMenux: reboot after host update',extra_properties=['RuntimeMaxSec=75'])
        self.run.return_value=(False,{'status':409})
        self.assertEqual(self.client.post('/api/health/reboot-after-update',json=self.body,headers={'Authorization':'Bearer admin'}).status_code,409)

    def test_read_only_version_is_allowed_but_context_and_action_status_are_admin_only(self):
        self.assertEqual(self.client.get('/api/health/proxmenux-version',headers={'Authorization':'Bearer reader'}).status_code,200)
        for path in ('reboot-context','reboot-after-update/status'):
            self.assertEqual(self.client.get('/api/health/'+path,headers={'Authorization':'Bearer reader'}).status_code,403)
        self.context.assert_not_called();self.state.assert_not_called();self.run.assert_not_called()


if __name__=='__main__':
    unittest.main(verbosity=2)
