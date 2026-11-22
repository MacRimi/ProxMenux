"""Browser-independent owners for explicitly confirmed LXC Updates runs.

Only the two Updates entrypoints are allowed. Import/list/attach never runs
anything. Interactive /ws/script consumers retain their original lifecycle.
Jobs survive viewer loss, not a Monitor/host restart; missing resume IDs fail
closed. The update shell still owns the shared scheduler/control/check flock.
"""
import codecs
import errno
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import tempfile
import termios
import fcntl
import threading
import time

SCRIPTS = {
    "/usr/local/share/proxmenux/scripts/lxc/apply_updates.sh",
    "/usr/local/share/proxmenux/scripts/lxc/install_checked_os_updates.sh",
}
PARAMS = {
    "VMID", "RUN_ID", "CT_NAME", "TARGET", "REQUESTED_TARGETS_JSON",
    "TARGET_LABELS_JSON", "BACKUP", "BACKUP_STORAGE", "RESTART",
    "UPDATE_COMMAND", "APP_NAME", "RUN_HELPER", "ALLOW_HELPER_WITH_CUSTOM",
    "DOCKER_STANDALONE_TARGETS", "UPDATE_DOCKER_ENGINE",
    "REFRESH_DOCKER_INVENTORY",
}
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
INTERACTION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_RUNTIME = 4 * 3600
# The shared runner restores a guest it started in its EXIT trap. Its package
# observation and `pct shutdown --timeout 60` need time after SIGTERM, too.
STOP_GRACE = 300
RESULT_TTL = 6 * 3600
MAX_OUTPUT = 256 * 1024
MAX_INPUT = 64 * 1024
MAX_JOBS = 32
_lock = threading.RLock()
_jobs = {}


class JobConflict(ValueError):
    pass


def _validate(run_id, script, params):
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid update job ID")
    if script not in SCRIPTS or os.path.realpath(script) != script:
        raise ValueError("Only the LXC Updates entrypoints support background runs")
    if not isinstance(params, dict) or set(params) - PARAMS:
        raise ValueError("Invalid update parameters")
    if any(not isinstance(v, str) or len(v) > 65536 for v in params.values()):
        raise ValueError("Invalid update parameter value")
    if len(json.dumps(params)) > 128 * 1024:
        raise ValueError("Update parameters are too large")
    if params.get("RUN_ID") != run_id:
        raise ValueError("Update run ID does not match")
    vmid = params.get("VMID", "")
    if not re.fullmatch(r"[1-9][0-9]{0,8}", vmid):
        raise ValueError("Invalid container ID")
    if params.get("TARGET") not in ("os", "app", "both"):
        raise ValueError("Invalid update target")
    return int(vmid)


class UpdateJob:
    def __init__(self, run_id, script, params, callback):
        self.id, self.script, self.params = run_id, script, dict(params)
        self.vmid = int(params["VMID"])
        self.created_at = time.time()
        self.started = time.monotonic()
        self.finished_at = None
        self.exit_code = None
        self.state = "running"
        self.output = ""
        self.offset = 0
        self.interaction = None
        self.revision = 0
        self.lock = threading.RLock()
        self.callback = callback
        self.stop_reason = None
        self.stop_at = None
        self.master = None
        self.process = None
        self.log_path = None
        self._interaction_buffer = ""
        self._input = bytearray()

    def launch(self):
        master, slave = pty.openpty()
        self.master = master
        try:
            # A viewer's paste must never block the worker's output, timeout
            # or cancellation when the updater does not read its stdin.
            os.set_blocking(master, False)
            fd, self.log_path = tempfile.mkstemp(prefix="proxmenux_update_", suffix=".log")
            os.close(fd)
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
            env = dict(os.environ, **self.params, EXECUTION_MODE="web",
                       WEB_LOG=self.log_path, TERM="xterm-256color", PYTHONUNBUFFERED="1")
            self.process = subprocess.Popen(
                ["/bin/bash", self.script], stdin=slave, stdout=slave, stderr=slave,
                start_new_session=True, env=env,
            )
        except BaseException:
            os.close(master)
            self.master = None
            if self.log_path:
                os.unlink(self.log_path)
            raise
        finally:
            os.close(slave)
        try:
            threading.Thread(target=self._run, daemon=True,
                             name=f"lxc-update-{self.id}").start()
        except BaseException:
            # A failed worker start must not leave an untracked updater alive.
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
            os.close(master)
            self.master = None
            os.unlink(self.log_path)
            raise

    def _append(self, text):
        with self.lock:
            self.output = (self.output + text)[-MAX_OUTPUT:]
            self.offset += len(text)

    def _interactions(self, stream):
        self._interaction_buffer += stream.read(16384)
        if len(self._interaction_buffer) > 65536:
            self._interaction_buffer = ""
            return
        lines = self._interaction_buffer.split("\n")
        self._interaction_buffer = lines.pop()
        for line in lines:
            if not line.startswith("WEB_INTERACTION:"):
                continue
            try:
                import base64
                parts = line.rstrip("\n")[16:].split(":", 4)
                kind, identity, title, message = parts[:4]
                if not INTERACTION_ID.fullmatch(identity):
                    continue
                value = dict(type=kind, id=identity,
                             title=base64.b64decode(title).decode(),
                             message=base64.b64decode(message).decode())
                if len(parts) > 4:
                    if kind == "menu":
                        value["options"] = json.loads(parts[4])
                    elif kind in ("input", "inputbox"):
                        value["default"] = base64.b64decode(parts[4]).decode()
                with self.lock:
                    if not self.stop_reason:
                        self.interaction = value
                        self.revision += 1
            except (ValueError, UnicodeError, IndexError):
                continue

    def _signal(self, reason):
        with self.lock:
            if self.process.poll() is not None or self.stop_reason:
                return
            self.stop_reason, self.stop_at = reason, time.monotonic()
            self._input.clear()
            self.interaction = None
            self.revision += 1
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def cancel(self):
        self._signal("cancelled")

    def _write_input(self):
        # The descriptor is nonblocking, so even a full PTY cannot hold this
        # lock. Retain unwritten bytes in order until the child can read them.
        with self.lock:
            if not self._input or self.stop_reason:
                return
            try:
                written = os.write(self.master, self._input[:16384])
            except BlockingIOError:
                return
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                # The child can close its terminal and keep working. Losing
                # stdin must not turn that update into a viewer failure.
                self._input.clear()
                return
            del self._input[:written]

    def _run(self):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        eof, exited_at = False, None
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as interactions:
                while True:
                    now = time.monotonic()
                    running = self.process.poll() is None
                    if not running:
                        exited_at = exited_at or now
                        if eof or now - exited_at >= 1:
                            break
                    if time.monotonic() - self.started >= MAX_RUNTIME:
                        self._signal("timeout")
                    if running and self.stop_at and now - self.stop_at >= STOP_GRACE:
                        try:
                            os.killpg(self.process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    self._interactions(interactions)
                    with self.lock:
                        pending_input = bool(self._input) and running and not self.stop_reason
                    readable, writable, _ = select.select(
                        [] if eof else [self.master],
                        [self.master] if pending_input else [], [], 0.05)
                    if writable:
                        self._write_input()
                    if readable:
                        try:
                            data = os.read(self.master, 16384)
                        except BlockingIOError:
                            continue
                        except OSError as exc:
                            if exc.errno != errno.EIO:
                                raise
                            data = b""
                        if data:
                            self._append(decoder.decode(data))
                            continue
                        eof = True
            code = self.process.wait()
            self._append(decoder.decode(b"", final=True))
            if self.stop_reason:
                code = 124 if self.stop_reason == "timeout" else 130
        except BaseException as exc:
            self._append(f"\r\nUpdate viewer failed: {type(exc).__name__}\r\n")
            self._signal("viewer failure")
            try:
                self.process.wait(timeout=STOP_GRACE)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
            code = 1
        finally:
            os.close(self.master)
            self.master = None
            try:
                os.unlink(self.log_path)
            except FileNotFoundError:
                pass
        with self.lock:
            self.exit_code = code
            self.state = "finalizing"
            self.interaction = None
            self._input.clear()
            self.revision += 1
        try:
            self.callback(self.script, self.params, code, time.monotonic() - self.started)
        finally:
            with self.lock:
                self.state = "complete"
                self.finished_at = time.time()
                self.revision += 1

    def view(self):
        with self.lock:
            return dict(id=self.id, vmid=self.vmid, state=self.state,
                        target=self.params["TARGET"], ct_name=self.params.get("CT_NAME", ""),
                        created_at=self.created_at, finished_at=self.finished_at,
                        exit_code=self.exit_code, script_path=self.script)

    def read(self, offset):
        with self.lock:
            begin = self.offset - len(self.output)
            cursor = max(begin, min(offset, self.offset))
            return dict(text=self.output[cursor - begin:], offset=self.offset,
                        truncated=offset < begin, interaction=self.interaction,
                        revision=self.revision, state=self.state, exit_code=self.exit_code)

    def input(self, message):
        with self.lock:
            if self.state != "running" or self.master is None:
                return
            if isinstance(message, str):
                if len(message) > 16384:
                    raise ValueError("Terminal input is too large")
                if message == "\x03":
                    self.cancel()
                else:
                    data = message.encode()
                    if len(self._input) + len(data) > MAX_INPUT:
                        raise ValueError("Terminal input buffer is full")
                    if not self.stop_reason:
                        self._input.extend(data)
            elif message.get("type") == "cancel":
                self.cancel()
            elif message.get("type") == "resize":
                cols = max(20, min(400, int(message.get("cols", 120))))
                rows = max(5, min(200, int(message.get("rows", 30))))
                fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            elif message.get("type") == "interaction_response":
                identity, value = message.get("id"), message.get("value")
                if (not self.interaction or identity != self.interaction["id"]
                        or not isinstance(value, str) or len(value) > 16384):
                    raise ValueError("No matching pending interaction")
                path = f"/tmp/proxmenux_response_{identity}"
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w") as response:
                    response.write(value)
                self.interaction = None
                self.revision += 1


def start(run_id, script, params, callback):
    vmid = _validate(run_id, script, params)
    with _lock:
        existing = _jobs.get(run_id)
        if existing:
            if existing.script != script or existing.params != params:
                raise JobConflict("Update job ID already belongs to another request")
            return existing
        _prune()
        if any(j.vmid == vmid and j.state != "complete" for j in _jobs.values()):
            raise JobConflict("An update is already running for this container")
        if len(_jobs) >= MAX_JOBS:
            completed = [j for j in _jobs.values() if j.state == "complete"]
            if not completed:
                raise JobConflict("Too many active update jobs; try again later")
            oldest = min(completed, key=lambda j: j.finished_at)
            del _jobs[oldest.id]
        job = UpdateJob(run_id, script, params, callback)
        _jobs[run_id] = job
        try:
            job.launch()
        except BaseException:
            _jobs.pop(run_id, None)
            raise
        return job


def _prune():
    now = time.time()
    for identity, job in list(_jobs.items()):
        if job.finished_at and now - job.finished_at > RESULT_TTL:
            del _jobs[identity]


def get(run_id, vmid):
    with _lock:
        job = _jobs.get(run_id)
        if job is None or job.vmid != int(vmid):
            raise KeyError("Update job is unavailable; it was not restarted")
        return job


def list_jobs():
    with _lock:
        _prune()
        return [j.view() for j in sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)]
