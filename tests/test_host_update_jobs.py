"""Real inert host workers plus actual auth/ticket/viewer boundaries. No APT."""
import ast
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from flask import Blueprint, Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'AppImage/scripts'))
import host_update_jobs as jobs


def wait(predicate, timeout=6):
    limit = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= limit:
            raise AssertionError('Inert job did not reach the expected boundary')
        time.sleep(.01)


class Jobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.script, self.gate, self.events = [self.folder / n for n in ('host.sh', 'finish', 'events')]
        self.script.write_text(f'echo started >> {shlex.quote(str(self.events))}\n'
                               f'while [ ! -e {shlex.quote(str(self.gate))} ]; do sleep .02; done\n'
                               f'echo final-step >> {shlex.quote(str(self.events))}\necho done\n')
        self.fixed = patch.object(jobs, 'SCRIPT', str(self.script))
        self.fixed.start()
        self.addCleanup(self.fixed.stop)
        jobs._jobs.clear()
        self.callback = Mock()
        self.addCleanup(self.finish_all)

    def finish_all(self):
        self.gate.touch()
        for job in list(jobs._jobs.values()):
            wait(lambda: job.state == 'complete')
        jobs._jobs.clear()

    def start(self, identity='job-1'):
        return jobs.start(identity, self.callback)

    def finish(self, job):
        self.gate.touch()
        wait(lambda: job.state == 'complete')

    def test_real_worker_finishes_post_steps_without_any_viewer(self):
        job = self.start()
        wait(self.events.exists)
        self.assertEqual(self.events.read_text().splitlines(), ['started'])
        self.finish(job)
        self.assertEqual(self.events.read_text().splitlines(), ['started', 'final-step'])
        self.assertEqual(job.exit_code, 0)
        self.callback.assert_called_once()

    def test_same_id_is_idempotent_and_other_id_cannot_start(self):
        first = self.start()
        wait(self.events.exists)
        with patch.object(jobs.subprocess, 'Popen') as spawn:
            self.assertIs(self.start(), first)
            with self.assertRaises(jobs.JobConflict):
                self.start('other')
            self.assertIs(jobs.get(first.id), first)
            spawn.assert_not_called()
        self.finish(first)
        self.assertIs(self.start(), first)

    def test_concurrent_start_has_one_process(self):
        barrier, results = threading.Barrier(6), []
        def run():
            barrier.wait()
            results.append(self.start())
        workers = [threading.Thread(target=run) for _ in range(6)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(len({id(job) for job in results}), 1)
        self.finish(results[0])
        self.assertEqual(self.events.read_text().splitlines().count('started'), 1)

    def test_read_list_and_missing_resume_have_zero_effects(self):
        with patch.object(jobs.subprocess, 'Popen') as spawn, patch.object(jobs.tempfile, 'mkstemp') as files:
            self.assertEqual(jobs.list_jobs(), [])
            for value in ('missing', '../bad', '', None):
                with self.subTest(value=value), self.assertRaises((KeyError, ValueError)):
                    jobs.get(value)
            spawn.assert_not_called()
            files.assert_not_called()

    def test_invalid_start_and_missing_script_spawn_nothing(self):
        with patch.object(jobs.subprocess, 'Popen') as spawn, patch.object(jobs.tempfile, 'mkstemp') as files:
            for value in ('../bad', 'x'*65, None):
                with self.assertRaises(ValueError):
                    self.start(value)
            with patch.object(jobs.os.path, 'isfile', return_value=False):
                with self.assertRaises(ValueError):
                    self.start()
            spawn.assert_not_called()
            files.assert_not_called()

    def test_owner_thread_failure_cannot_spawn_an_unowned_update(self):
        with patch.object(jobs.threading.Thread, 'start', side_effect=RuntimeError('thread unavailable')), patch.object(jobs.subprocess, 'Popen') as spawn:
            with self.assertRaises(RuntimeError):
                self.start()
            spawn.assert_not_called()
        self.assertEqual(jobs.list_jobs(), [])

    def test_popen_failure_is_recorded_not_success_or_automatic_retry(self):
        with patch.object(jobs.subprocess, 'Popen', side_effect=OSError('fixture failure')) as spawn:
            job = self.start()
            wait(lambda: job.state == 'complete')
            self.assertEqual(job.exit_code, 1)
            self.assertIs(self.start(), job)
            spawn.assert_called_once()
        self.assertFalse(self.events.exists())

    def test_runtime_limit_marks_attention_without_signal_or_second_update(self):
        with patch.object(jobs, 'ATTENTION_AFTER', .05), patch.object(jobs.os, 'killpg') as signals:
            job = self.start()
            wait(lambda: job.state == 'attention')
            self.assertIsNone(job.process.poll())
            with self.assertRaises(jobs.JobConflict):
                self.start('other')
            signals.assert_not_called()
            self.finish(job)
        self.assertEqual(job.exit_code, 0)

    def test_explicit_viewer_cancel_and_terminal_control_cannot_kill_host(self):
        job = self.start()
        wait(self.events.exists)
        with patch.object(jobs.os, 'killpg') as signals:
            for value in ({'type':'cancel'}, '\x03', 'paste\x1a', '\x1c'):
                with self.assertRaises(ValueError):
                    job.input(value)
            signals.assert_not_called()
        self.finish(job)

    def test_partial_interaction_replays_and_can_only_be_answered_once(self):
        job = self.start()
        wait(self.events.exists)
        identity = 'host-fixture-' + os.urandom(8).hex()
        target = Path('/tmp/proxmenux_response_' + identity)
        self.addCleanup(lambda: target.unlink(missing_ok=True))
        b64 = lambda s: base64.b64encode(s.encode()).decode()
        text = f'WEB_INTERACTION:yesno:{identity}:{b64("Confirm")}:{b64("Question")}\n'
        job._interactions(io.StringIO(text[:17]))
        self.assertIsNone(job.interaction)
        job._interactions(io.StringIO(text[17:]))
        self.assertEqual(jobs.get(job.id).read(0)['interaction']['id'], identity)
        job.input(dict(type='interaction_response', id=identity, value='yes'))
        self.assertEqual(target.read_text(), 'yes')
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with patch.object(jobs.os, 'open') as write:
            with self.assertRaises(ValueError):
                job.input(dict(type='interaction_response', id=identity, value='yes'))
            write.assert_not_called()
        self.finish(job)

    def test_symlink_response_is_not_overwritten(self):
        job = self.start()
        wait(self.events.exists)
        identity = 'host-fixture-' + os.urandom(8).hex()
        target = Path('/tmp/proxmenux_response_' + identity)
        target.symlink_to(self.events)
        self.addCleanup(lambda: target.unlink(missing_ok=True))
        job.interaction = dict(id=identity)
        before = self.events.read_bytes()
        with self.assertRaises(OSError):
            job.input(dict(type='interaction_response', id=identity, value='no'))
        self.assertEqual(self.events.read_bytes(), before)
        self.finish(job)

    def test_finalizing_reserves_host_and_failure_is_not_hidden(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def finalize(*_):
            entered.set()
            release.wait(3)
            raise RuntimeError('cache failure')
        self.callback.side_effect = finalize
        job = self.start()
        self.gate.touch()
        self.assertTrue(entered.wait(3))
        with self.assertRaises(jobs.JobConflict):
            self.start('other')
        release.set()
        wait(lambda: job.state == 'complete')
        self.assertEqual(job.script_exit_code, 0)
        self.assertEqual(job.exit_code, 1)
        self.assertTrue(job.finalization_error)
        self.callback.assert_called_once()

    def test_failed_shell_with_surviving_child_remains_reserved(self):
        self.script.write_text(
            f'(trap "" HUP; echo child-ready >> {shlex.quote(str(self.events))}; '
            f'while [ ! -e {shlex.quote(str(self.gate))} ]; do sleep .02; done; '
            f'echo child-finished >> {shlex.quote(str(self.events))}) &\n'
            f'while [ ! -s {shlex.quote(str(self.events))} ]; do sleep .01; done\nexit 7\n')
        job = self.start()
        wait(lambda: job.state == 'attention')
        with self.assertRaises(jobs.JobConflict):
            self.start('other')
        self.gate.touch()
        wait(lambda: job.state == 'complete')
        self.assertEqual(job.exit_code, 7)
        self.assertIn('child-finished', self.events.read_text())


class Routes(unittest.TestCase):
    finish_all = Jobs.finish_all
    finish = Jobs.finish
    def setUp(self):
        Jobs.setUp(self)
        self.app = Flask(__name__)
        auth = ModuleType('auth_manager')
        auth.load_auth_config = lambda: {'enabled':True}
        auth.verify_token = lambda token: 'fixture' if token=='valid' else None
        auth.verify_token_full = lambda token: ('fixture','full_admin') if token=='valid' else ('fixture','read_only') if token=='read-only' else (None,None)
        modules = patch.dict(sys.modules, {'auth_manager':auth})
        modules.start()
        self.addCleanup(modules.stop)
        spec = importlib.util.spec_from_file_location('host_jwt_fixture',ROOT/'AppImage/scripts/jwt_middleware.py')
        middleware = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(middleware)
        self.ws_routes = {}
        def route(path):
            def register(fn):
                self.ws_routes[path]=fn
                return fn
            return register
        scope=dict(terminal_bp=Blueprint('host_fixture',__name__),sock=SimpleNamespace(route=route),
                   request=request,jsonify=jsonify,require_admin_scope=middleware.require_admin_scope,
                   _TERMINAL_TICKETS={},_TICKETS_LOCK=threading.Lock(),_TICKET_TTL=5,
                   _TICKET_MAX_INFLIGHT=256,time=time,secrets=__import__('secrets'),json=json,
                   _host_update_completed=self.callback)
        names={'_issue_terminal_ticket','_consume_terminal_ticket','_ws_auth_check',
               'issue_terminal_ticket_route','host_update_jobs_status','host_update_result','host_update_viewer'}
        nodes=[n for n in ast.parse((ROOT/'AppImage/scripts/flask_terminal_routes.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name in names]
        self.assertEqual(len(nodes),len(names))
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-host-routes','exec'),scope)
        self.app.register_blueprint(scope['terminal_bp'])
        self.client=self.app.test_client()

    def ticket(self, token='valid'):
        return self.client.post('/api/terminal/ticket',headers={'Authorization':'Bearer '+token})

    def attach(self, init, ticket=None, identity='job-1'):
        frames=iter([json.dumps(init)])
        ws=Mock()
        def receive(**_):
            try:
                return next(frames)
            except StopIteration:
                raise ConnectionError('viewer signed out')
        ws.receive.side_effect=receive
        with self.app.test_request_context('/ws/host-update/'+identity+('?ticket='+ticket if ticket else '')):
            self.ws_routes['/ws/host-update/<run_id>'](ws,identity)
        return ws

    def test_401_and_read_only_cannot_list_start_or_get_a_ticket(self):
        for token,status in [('expired',401),('read-only',403)]:
            with patch.object(jobs.subprocess,'Popen') as spawn:
                self.assertEqual(self.ticket(token).status_code,status)
                self.assertEqual(self.client.get('/api/host-update-jobs',headers={'Authorization':'Bearer '+token}).status_code,status)
                self.assertEqual(self.client.get('/api/host-update-jobs/fixture/result',headers={'Authorization':'Bearer '+token}).status_code,status)
                self.attach(dict(resume=False))
                spawn.assert_not_called()
        self.assertEqual(jobs.list_jobs(),[])

    def test_finished_result_is_read_only_and_bounded_by_owner_output(self):
        view=dict(state='complete',exit_code=0,text='inert saved output',truncated=False)
        with patch.object(jobs,'get',return_value=SimpleNamespace(read=Mock(return_value=view))) as get,patch.object(jobs,'start') as start,patch.object(jobs.subprocess,'Popen') as spawn:
            response=self.client.get('/api/host-update-jobs/fixture/result',headers={'Authorization':'Bearer valid'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json,view)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            get.assert_called_once_with('fixture');start.assert_not_called();spawn.assert_not_called()

    def test_result_auth_missing_invalid_running_never_starts_job(self):
        with patch.object(jobs,'get') as get,patch.object(jobs,'start') as start,patch.object(jobs.subprocess,'Popen') as spawn:
            self.assertEqual(self.client.get('/api/host-update-jobs/fixture/result').status_code,401)
            get.assert_not_called()
            get.side_effect=KeyError('missing')
            self.assertEqual(self.client.get('/api/host-update-jobs/missing/result',headers={'Authorization':'Bearer valid'}).status_code,404)
            get.side_effect=ValueError('invalid')
            self.assertEqual(self.client.get('/api/host-update-jobs/invalid/result',headers={'Authorization':'Bearer valid'}).status_code,404)
            get.side_effect=None
            for state in ('running','attention','finalizing'):
                get.return_value=SimpleNamespace(read=Mock(return_value=dict(state=state,exit_code=None)))
                self.assertEqual(self.client.get('/api/host-update-jobs/fixture/result',headers={'Authorization':'Bearer valid'}).status_code,409)
            start.assert_not_called();spawn.assert_not_called()
    def test_real_route_disconnect_401_then_relogin_replays_one_job(self):
        self.attach(dict(resume=False),self.ticket().json['ticket'])
        job=jobs.get('job-1')
        wait(self.events.exists)
        self.assertEqual(self.client.get('/api/host-update-jobs',headers={'Authorization':'Bearer expired'}).status_code,401)
        self.assertEqual(self.client.get('/api/host-update-jobs',headers={'Authorization':'Bearer valid'}).json['jobs'][0]['id'],job.id)
        with patch.object(jobs.subprocess,'Popen') as spawn:
            self.attach(dict(resume=True),self.ticket().json['ticket'])
            spawn.assert_not_called()
        self.finish(job)
        ws=self.attach(dict(resume=True),self.ticket().json['ticket'])
        messages=[json.loads(call.args[0]) for call in ws.send.call_args_list]
        self.assertEqual(messages[-1],dict(type='script_complete',exit_code=0))
        self.assertEqual(self.events.read_text().splitlines(),['started','final-step'])
        self.callback.assert_called_once()

    def test_missing_resume_extra_params_and_boolean_cursor_spawn_nothing(self):
        with patch.object(jobs.subprocess,'Popen') as spawn, patch.object(jobs.tempfile,'mkstemp') as files:
            for init in (dict(resume=True),dict(resume=False,params={'LD_PRELOAD':'bad'}),dict(resume=False,offset=True),dict(resume='false')):
                self.attach(init,self.ticket().json['ticket'])
            spawn.assert_not_called()
            files.assert_not_called()

    def test_legacy_action_api_keeps_fixed_command_and_cancel_cannot_target_host_job(self):
        # Execute the actual existing API functions, with only the systemd
        # boundary replaced. They must keep their original unit/argv contract.
        source=ast.parse((ROOT/'AppImage/scripts/flask_server.py').read_text())
        names={'api_system_pve_update_run','api_system_pve_update_status','api_system_pve_update_cancel'}
        nodes=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in names]
        app=Flask('legacy-host-action-fixture')
        run=Mock(return_value=(True,None))
        state=Mock(return_value={'status':'running'})
        cancel=Mock()
        scope=dict(app=app,require_admin_scope=lambda fn:fn,require_auth=lambda fn:fn,
                   os=os,jsonify=jsonify,_PVE_UPDATE_SCRIPT=str(self.script),
                   _action_run=run,_action_state=state,_action_cancel=cancel)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-legacy-api','exec'),scope)
        client=app.test_client()
        self.assertEqual(client.post('/api/system/pve-update/run').status_code,202)
        run.assert_called_once_with('proxmenux-action-pve-update',['/bin/bash',str(self.script)],
                                    description='ProxMenux action: Proxmox VE update')
        self.assertEqual(client.get('/api/system/pve-update/status').status_code,200)
        self.assertEqual(client.delete('/api/system/pve-update').status_code,200)
        cancel.assert_called_once_with('proxmenux-action-pve-update')
        self.assertEqual(jobs.list_jobs(),[])

    def test_actual_host_finalizer_invalidates_health_without_viewer_or_package_calls(self):
        from types import SimpleNamespace
        keys=('updates_check','overall_health','_bg_overall','_bg_detailed')
        cache=SimpleNamespace(last_check_times=dict.fromkeys((*keys,'unrelated'),123),
                              cached_results=dict.fromkeys((*keys,'unrelated'),{'status':'old'}))
        module=ModuleType('health_monitor')
        module.health_monitor=cache
        node=next(n for n in ast.parse((ROOT/'AppImage/scripts/flask_terminal_routes.py').read_text()).body
                  if isinstance(n,ast.FunctionDef) and n.name=='_host_update_completed')
        scope={}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-finalizer','exec'),scope)
        with patch.dict(sys.modules,{'health_monitor':module}),patch.object(jobs.subprocess,'Popen') as spawn:
            scope['_host_update_completed'](jobs.SCRIPT,{},0,1)
            spawn.assert_not_called()
        self.assertEqual(cache.last_check_times,{'unrelated':123})
        self.assertEqual(cache.cached_results,{'unrelated':{'status':'old'}})


if __name__=='__main__':
    unittest.main(verbosity=2)
