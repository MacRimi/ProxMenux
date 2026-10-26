"""Real inert processes and actual Flask/ticket/socket handler boundaries."""
import ast
import base64
import io
import importlib.util
import json
import os
import pty
import re
import select
import fcntl
import struct
import termios
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Blueprint, Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "AppImage/scripts"))
import lxc_update_jobs as jobs


def wait_for(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for fixture")
        time.sleep(0.01)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.script = self.folder / "apply.sh"
        self.gate = self.folder / "backup-done"
        self.events = self.folder / "events"
        self.script.write_text(
            f"echo backup-start; echo backup >> {shlex.quote(str(self.events))}\n"
            f"while [ ! -e {shlex.quote(str(self.gate))} ]; do sleep .02; done\n"
            f"echo update-finished; echo update >> {shlex.quote(str(self.events))}\n"
        )
        self.allowed = patch.object(jobs, "SCRIPTS", {str(self.script)})
        self.allowed.start()
        self.addCleanup(self.allowed.stop)
        jobs._jobs.clear()
        self.callback = Mock()
        self.addCleanup(self.stop_jobs)

    def stop_jobs(self):
        for job in list(jobs._jobs.values()):
            if job.state != "complete":
                job.cancel()
                wait_for(lambda: job.state == "complete")
        jobs._jobs.clear()

    def params(self, run="run-1", vmid="100"):
        return dict(VMID=vmid, RUN_ID=run, TARGET="app", CT_NAME="fixture", BACKUP="1")

    def start(self, run="run-1", vmid="100"):
        return jobs.start(run, str(self.script), self.params(run, vmid), self.callback)

    def finish(self, job):
        self.gate.touch()
        wait_for(lambda: job.state == "complete")

    def test_real_backup_and_update_continue_without_any_viewer(self):
        job = self.start()
        wait_for(lambda: self.events.exists())
        self.assertEqual(self.events.read_text().splitlines(), ["backup"])
        self.assertEqual(job.state, "running")
        self.finish(job)
        self.assertEqual(self.events.read_text().splitlines(), ["backup", "update"])
        self.assertEqual(job.exit_code, 0)
        self.callback.assert_called_once()
        self.assertEqual(self.callback.call_args.args[:3],
                         (str(self.script), self.params(), 0))
        self.assertIn("update-finished", job.read(0)["text"])

    def test_same_run_reconnect_is_idempotent_and_other_ct_cannot_attach(self):
        job = self.start()
        self.assertIs(self.start(), job)
        with self.assertRaises(KeyError):
            jobs.get(job.id, 200)
        with self.assertRaises(KeyError):
            jobs.get("lost-run", 100)
        self.finish(job)
        self.assertIs(jobs.get(job.id, 100), job)
        self.assertIs(self.start(), job)
        self.assertEqual(self.events.read_text().splitlines(), ["backup", "update"])
        self.callback.assert_called_once()

    def test_different_run_for_same_ct_rejected_before_second_spawn(self):
        job = self.start()
        with patch.object(jobs.subprocess, "Popen") as spawn:
            with self.assertRaises(jobs.JobConflict):
                self.start("run-2")
            spawn.assert_not_called()
        self.finish(job)
        other = self.start("run-2")
        wait_for(lambda: other.state == "complete")
        self.assertEqual(self.events.read_text().splitlines().count("update"), 2)

    def test_concurrent_same_id_starts_once(self):
        calls, errors = [], []
        barrier = threading.Barrier(6)
        def attempt():
            barrier.wait()
            try:
                calls.append(self.start())
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=attempt) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(errors)
        self.assertEqual(len({id(job) for job in calls}), 1)
        self.finish(calls[0])
        self.assertEqual(self.events.read_text().splitlines(), ["backup", "update"])

    def test_invalid_request_has_zero_process_and_zero_tempfile_effects(self):
        bad = [
            ("../bad", str(self.script), self.params()),
            ("run-1", "/bin/bash", self.params()),
            ("run-1", str(self.script), dict(self.params(), LD_PRELOAD="/bad")),
            ("run-1", str(self.script), dict(self.params(), VMID="0")),
            ("run-1", str(self.script), dict(self.params(), RUN_ID="other")),
            ("run-1", str(self.script), dict(self.params(), UPDATE_COMMAND=123)),
            ("run-1", str(self.script), dict(self.params(), TARGET="unexpected")),
        ]
        with patch.object(jobs.subprocess, "Popen") as spawn, \
                patch.object(jobs.tempfile, "mkstemp") as files:
            for identity, script, params in bad:
                with self.subTest(params=params), self.assertRaises(ValueError):
                    jobs.start(identity, script, params, self.callback)
            spawn.assert_not_called()
            files.assert_not_called()
        self.assertFalse(jobs.list_jobs())

    def test_request_id_cannot_be_rebound_to_another_command(self):
        job = self.start()
        with patch.object(jobs.subprocess, "Popen") as spawn:
            with self.assertRaises(jobs.JobConflict):
                jobs.start("run-1", str(self.script),
                           dict(self.params(), UPDATE_COMMAND="different"), self.callback)
            spawn.assert_not_called()
        self.finish(job)

    def test_failure_and_launch_error_are_not_reported_as_success(self):
        self.script.write_text("echo failed-backup; exit 3\n")
        job = self.start()
        wait_for(lambda: job.state == "complete")
        self.assertEqual(job.exit_code, 3)
        self.assertFalse(self.events.exists())
        self.callback.assert_called_once()
        with patch.object(jobs.subprocess, "Popen", side_effect=OSError("cannot execute")):
            with self.assertRaises(OSError):
                self.start("run-2")
        self.assertNotIn("run-2", jobs._jobs)

    def test_cancel_is_explicit_and_kills_the_inert_process_group(self):
        job = self.start()
        wait_for(lambda: self.events.exists())
        job.input({"type": "cancel"})
        wait_for(lambda: job.state == "complete")
        self.assertEqual(job.exit_code, 130)
        self.assertEqual(self.events.read_text().splitlines(), ["backup"])
        self.callback.assert_called_once()

    def test_timeout_is_bounded_even_if_the_child_closes_its_terminal(self):
        self.script.write_text("exec </dev/null >/dev/null 2>&1\nwhile :; do sleep .02; done\n")
        with patch.object(jobs, "MAX_RUNTIME", .15):
            job = self.start()
            wait_for(lambda: job.state == "complete")
        self.assertEqual(job.exit_code, 124)
        self.callback.assert_called_once()

    def test_output_is_bounded_and_cursor_replay_is_read_only(self):
        job = self.start()
        wait_for(lambda: self.events.exists())
        with patch.object(jobs, "MAX_OUTPUT", 32):
            job._append("x" * 100)
            snap = job.read(0)
            self.assertEqual(len(snap["text"]), 32)
            self.assertTrue(snap["truncated"])
            self.assertEqual(job.read(snap["offset"])["text"], "")
        self.finish(job)

    def test_unknown_interaction_response_never_writes_a_file(self):
        job = self.start()
        with patch.object(jobs.os, "open") as files:
            with self.assertRaises(ValueError):
                job.input({"type": "interaction_response", "id": "not-pending", "value": "yes"})
            files.assert_not_called()
        self.finish(job)

    def test_real_process_exit_calls_existing_backend_finalizer_without_viewer(self):
        source = ast.parse((ROOT / "AppImage/scripts/flask_server.py").read_text())
        node = next(n for n in source.body if isinstance(n, ast.FunctionDef)
                    and n.name == "_terminal_lxc_update_completed")
        finalize = Mock()
        scope = dict(os=os, _LXC_APPLY_UPDATES_SCRIPT=str(self.script),
            _LXC_INSTALL_CHECKED_OS_SCRIPT=str(self.folder/'checked.sh'),
            _normalise_lxc_update_run_id=lambda value, **_: value,
            _normalise_lxc_update_targets=lambda value, target: value or [target],
            _json_list=lambda value: json.loads(value or '[]'),
            _finalize_lxc_update=finalize)
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'actual-completion-hook', 'exec'), scope)
        def callback(script, params, code, duration):
            scope['_terminal_lxc_update_completed'](script_path=script, params=params,
                exit_code=code, duration_seconds=duration)
        self.callback.side_effect = callback
        job = self.start()
        self.finish(job)
        finalize.assert_called_once()
        args, kwargs = finalize.call_args
        self.assertEqual(args, (100,))
        self.assertEqual(kwargs['status'], 'success')
        self.assertEqual(kwargs['run_id'], 'run-1')
        self.assertEqual(kwargs['target'], 'app')
        self.assertEqual(kwargs['requested_targets'], ['app'])

    def test_list_never_starts_or_probes_a_guest_and_retention_has_safe_margin(self):
        job = self.start()
        with patch.object(jobs.subprocess, "Popen") as spawn:
            for _ in range(5):
                self.assertEqual(jobs.list_jobs()[0]["id"], job.id)
            spawn.assert_not_called()
        self.assertGreater(jobs.RESULT_TTL, jobs.MAX_RUNTIME)
        self.finish(job)
        ended = job.finished_at
        with patch.object(jobs.time, "time", return_value=ended + jobs.RESULT_TTL):
            self.assertEqual(len(jobs.list_jobs()), 1)
        with patch.object(jobs.time, "time", return_value=ended + jobs.RESULT_TTL + .01):
            self.assertEqual(jobs.list_jobs(), [])

    def test_full_history_evicts_only_completed_jobs_not_running_work(self):
        first = self.start()
        self.finish(first)
        with patch.object(jobs, "MAX_JOBS", 1):
            second = self.start("run-2")
            self.assertNotIn(first.id, jobs._jobs)
            wait_for(lambda: second.state == "complete")
        self.assertEqual(self.callback.call_count, 2)

    def test_tempfile_and_worker_start_failures_leave_no_job_or_process(self):
        with patch.object(jobs.tempfile, "mkstemp", side_effect=OSError("disk full")), \
                patch.object(jobs.subprocess, "Popen") as spawn:
            with self.assertRaises(OSError):
                self.start()
            spawn.assert_not_called()
        actual_spawn = jobs.subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            child = actual_spawn(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(jobs.subprocess, "Popen", side_effect=launch), \
                patch.object(jobs.threading.Thread, "start", side_effect=RuntimeError("no worker")):
            with self.assertRaises(RuntimeError):
                self.start()
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(jobs.list_jobs(), [])
        self.callback.assert_not_called()

    def test_pending_interaction_survives_partial_log_and_reconnect(self):
        job = self.start()
        identity = "fixture-" + os.urandom(8).hex()
        response = Path("/tmp/proxmenux_response_" + identity)
        self.addCleanup(lambda: response.unlink(missing_ok=True))
        encode = lambda s: base64.b64encode(s.encode()).decode()
        line = f"WEB_INTERACTION:inputbox:{identity}:{encode('Title')}:{encode('Question')}:{encode('default')}\n"
        job._interactions(io.StringIO(line[:20]))
        self.assertIsNone(job.read(0)["interaction"])
        job._interactions(io.StringIO(line[20:]))
        self.assertEqual(jobs.get(job.id, 100).read(0)["interaction"]["default"], "default")
        job.input({"type": "interaction_response", "id": identity, "value": "answer"})
        self.assertEqual(response.read_text(), "answer")
        self.assertEqual(response.stat().st_mode & 0o777, 0o600)
        with patch.object(jobs.os, "open") as files:
            with self.assertRaises(ValueError):
                job.input({"type": "interaction_response", "id": identity, "value": "again"})
            files.assert_not_called()
        self.finish(job)


class RouteTests(unittest.TestCase):
    stop_jobs = JobTests.stop_jobs
    params = JobTests.params
    finish = JobTests.finish

    def setUp(self):
        JobTests.setUp(self)
        self.app = Flask(__name__)
        self.auth = ModuleType("auth_manager")
        self.auth.load_auth_config = lambda: {"enabled": True}
        self.auth.verify_token = lambda token: "fixture" if token == "valid" else None
        self.auth.verify_token_full = lambda token: (
            ("fixture", "full_admin") if token == "valid" else
            ("fixture", "read_only") if token == "read-only" else (None, None))
        self.auth_patch = patch.dict(sys.modules, {"auth_manager": self.auth})
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)
        spec = importlib.util.spec_from_file_location(
            "update_jobs_jwt_fixture", ROOT / "AppImage/scripts/jwt_middleware.py")
        middleware = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(middleware)
        self.ws_routes = {}
        def route(path):
            def register(fn):
                self.ws_routes[path] = fn
                return fn
            return register
        scope = dict(terminal_bp=Blueprint("jobs_fixture", __name__),
                     sock=SimpleNamespace(route=route), request=request, jsonify=jsonify,
                     require_admin_scope=middleware.require_admin_scope,
                     _TERMINAL_TICKETS={}, _TICKETS_LOCK=threading.Lock(),
                     _TICKET_TTL=5, _TICKET_MAX_INFLIGHT=256,
                     time=time, secrets=__import__("secrets"), json=json,
                     _run_script_completion_hook=self.callback)
        names = {"_issue_terminal_ticket", "_consume_terminal_ticket", "_ws_auth_check",
                 "issue_terminal_ticket_route", "lxc_update_jobs_status", "lxc_update_viewer"}
        nodes = [n for n in ast.parse((ROOT / "AppImage/scripts/flask_terminal_routes.py").read_text()).body
                 if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual(len(nodes), len(names))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "actual-terminal-routes", "exec"), scope)
        self.scope = scope
        self.app.register_blueprint(scope["terminal_bp"])
        self.client = self.app.test_client()

    def ticket(self, token="valid"):
        return self.client.post("/api/terminal/ticket",
                                headers={"Authorization": "Bearer " + token})

    def attach(self, init, ticket=None, messages=None):
        frames = iter([json.dumps(init), *(messages or [])])
        ws = Mock()
        def receive(**_):
            try:
                return next(frames)
            except StopIteration:
                raise ConnectionError("browser reload / connection closed")
        ws.receive.side_effect = receive
        path = "/ws/lxc-update/run-1" + ("?ticket=" + ticket if ticket else "")
        with self.app.test_request_context(path):
            self.ws_routes["/ws/lxc-update/<run_id>"](ws, "run-1")
        return ws

    def test_expired_login_cannot_start_and_has_zero_job_effects(self):
        for token, status in [("expired", 401), ("read-only", 403)]:
            with self.subTest(token=token), patch.object(jobs.subprocess, "Popen") as launch:
                response = self.ticket(token)
                self.assertEqual(response.status_code, status)
                self.attach(dict(resume=False, script_path=str(self.script), params=self.params()))
                launch.assert_not_called()
        self.assertFalse(jobs.list_jobs())

    def test_expiry_during_backup_does_not_cancel_or_restart_and_fresh_login_resumes(self):
        ticket = self.ticket().json["ticket"]
        self.attach(dict(resume=False, script_path=str(self.script), params=self.params()), ticket)
        job = jobs.get("run-1", 100)
        wait_for(lambda: self.events.exists())
        denied = self.client.get("/api/lxc-update-jobs",
                                 headers={"Authorization": "Bearer expired"})
        self.assertEqual(denied.status_code, 401)
        self.assertIsNone(job.stop_reason)
        self.assertEqual(self.client.get("/api/lxc-update-jobs",
                         headers={"Authorization": "Bearer valid"}).json["jobs"][0]["id"], job.id)
        with patch.object(jobs.subprocess, "Popen") as launch:
            self.attach(dict(resume=True, vmid=100), self.ticket().json["ticket"])
            launch.assert_not_called()
        self.finish(job)
        self.assertEqual(job.exit_code, 0)
        self.assertEqual(self.events.read_text().splitlines(), ["backup", "update"])
        self.callback.assert_called_once()
        complete = self.attach(dict(resume=True, vmid=100), self.ticket().json["ticket"])
        frames = [json.loads(c.args[0]) for c in complete.send.call_args_list]
        self.assertEqual(frames[-1], {"type": "script_complete", "exit_code": 0})

    def test_ticket_is_single_use_and_invalid_resume_never_becomes_execution(self):
        ticket = self.ticket().json["ticket"]
        with patch.object(jobs.subprocess, "Popen") as launch:
            ws = self.attach(dict(resume=True, vmid=100), ticket)
            self.assertIn("job_unavailable", ws.send.call_args.args[0])
            denied = self.attach(dict(resume=True, vmid=100), ticket)
            denied.close.assert_called_once()
            launch.assert_not_called()

    def test_expiry_during_update_then_two_viewers_cannot_duplicate_or_finalize_early(self):
        update_gate = self.folder / "update-done"
        self.script.write_text(self.script.read_text() +
            f"while [ ! -e {shlex.quote(str(update_gate))} ]; do sleep .02; done\n")
        self.attach(dict(resume=False, script_path=str(self.script), params=self.params()),
                    self.ticket().json["ticket"])
        job = jobs.get("run-1", 100)
        self.gate.touch()
        wait_for(lambda: self.events.exists() and "update" in self.events.read_text())
        for token, status in [("expired", 401), ("read-only", 403)]:
            self.assertEqual(self.client.get("/api/lxc-update-jobs", headers={
                "Authorization": "Bearer " + token}).status_code, status)
        self.callback.assert_not_called()
        with patch.object(jobs.subprocess, "Popen") as spawn:
            for _ in range(2):
                self.attach(dict(resume=True, vmid=100), self.ticket().json["ticket"])
            spawn.assert_not_called()
        self.assertIsNone(job.stop_reason)
        update_gate.touch()
        wait_for(lambda: job.state == "complete")
        self.callback.assert_called_once()
        self.assertEqual(self.events.read_text().splitlines(), ["backup", "update"])

    def test_original_interactive_route_still_terminates_its_process_on_disconnect(self):
        # Reproduce the original ownership bug using the untouched legacy route.
        # Only its allowed fixture directory and process observation are injected.
        nodes = [n for n in ast.parse((ROOT / "AppImage/scripts/flask_terminal_routes.py").read_text()).body
                 if isinstance(n, ast.FunctionDef) and n.name == "script_websocket"]
        realpath = os.path.realpath
        os_view = SimpleNamespace(**vars(os))
        os_view.path = SimpleNamespace(**vars(os.path))
        os_view.path.realpath = lambda p: (str(self.folder)
            if p == "/usr/local/share/proxmenux/scripts" else realpath(p))
        children = []
        def spawn(*args, **kwargs):
            child = subprocess.Popen(*args, **kwargs)
            children.append(child)
            self.addCleanup(lambda: child.poll() is None and child.kill())
            return child
        self.scope.update(os=os_view, subprocess=SimpleNamespace(Popen=spawn),
            tempfile=tempfile, pty=pty, fcntl=fcntl, select=select, base64=base64, threading=threading,
            _SAFE_ID_RE=re.compile(r"^[A-Za-z0-9_-]{1,64}$"),
            set_winsize=lambda *_: None)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'actual-legacy-route', 'exec'), self.scope)
        ws = Mock()
        def receive(**_):
            if not children:
                return json.dumps(dict(script_path=str(self.script), params=self.params()))
            wait_for(lambda: self.events.exists())
            raise ConnectionError("expired login reloaded browser")
        ws.receive.side_effect = receive
        with self.app.test_request_context('/ws/script/fixture?ticket='+self.ticket().json['ticket']):
            self.ws_routes['/ws/script/<session_id>'](ws, 'fixture')
        self.assertIsNotNone(children[0].poll())
        self.assertNotEqual(children[0].returncode, 0)
        self.assertEqual(self.events.read_text().splitlines(), ['backup'])


if __name__ == "__main__":
    unittest.main()
