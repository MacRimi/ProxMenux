"""Owners for explicitly started PVE updates, independent of browser viewers.

Only the fixed PVE wrapper can run. List/resume/input cannot create a process.
Jobs survive logout, not a Monitor/host restart. Missing IDs fail closed.
Neither disconnect nor a watchdog kills a host package transaction.
"""
import base64
import codecs
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import struct
import subprocess
import tempfile
import termios
import threading
import time

SCRIPT = "/usr/local/share/proxmenux/scripts/utilities/proxmox_update.sh"
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
INTERACTION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ATTENTION_AFTER = 4 * 3600
RESULT_TTL = 6 * 3600
MAX_JOBS = 16
MAX_OUTPUT = 256 * 1024
MAX_INPUT = 64 * 1024
_lock = threading.RLock()
_jobs = {}


class JobConflict(ValueError):
    pass


def _group_active(pgid):
    """Observe descendants after an abnormal shell exit; ignore zombies."""
    try:
        for entry in os.scandir('/proc'):
            if not entry.name.isdigit():
                continue
            try:
                fields = Path(entry.path, 'stat').read_text().rsplit(') ', 1)[1].split()
                if fields[0] != 'Z' and int(fields[2]) == pgid:
                    return True
            except (OSError, ValueError, IndexError):
                continue
        return False
    except OSError:
        return True  # Unknown group state must not permit a second updater.


def _identity(identity):
    if not isinstance(identity, str) or not RUN_ID.fullmatch(identity):
        raise ValueError("Invalid host update job ID")


class HostUpdateJob:
    def __init__(self, identity, callback):
        self.id = identity
        self.created_at = time.time()
        self.started = time.monotonic()
        self.finished_at = self.exit_code = self.script_exit_code = None
        self.state = "starting"
        self.output, self.offset, self.revision = "", 0, 0
        self.interaction = self.attention_reason = None
        self.finalization_error = False
        self.lock = threading.RLock()
        self.process = self.master = self.log_path = None
        self.callback = callback
        self._input = bytearray()
        self._interaction_buffer = ""

    def launch(self):
        # Start the owner before spawning anything: thread-start failure must
        # never leave an updater that has no owner to drain its PTY.
        threading.Thread(target=self._run, daemon=True,
                         name=f"host-update-{self.id}").start()

    def _append(self, text):
        with self.lock:
            self.output = (self.output + text)[-MAX_OUTPUT:]
            self.offset += len(text)

    def _attention(self, reason):
        with self.lock:
            if self.attention_reason == reason and self.state == "attention":
                return
            self.attention_reason = reason
            self.state = "attention"
            self.revision += 1

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
                parts = line[16:].split(":", 4)
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
                    self.interaction = value
                    self.revision += 1
            except (ValueError, UnicodeError, IndexError):
                continue

    def _run(self):
        code, slave, interactions = 1, None, None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            self.master, slave = pty.openpty()
            os.set_blocking(self.master, False)
            fd, self.log_path = tempfile.mkstemp(prefix="proxmenux_host_update_", suffix=".log")
            os.close(fd)
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
            env = dict(os.environ, EXECUTION_MODE="web", PROXMENUX_HOST_UPDATE_JOB="1",
                       WEB_LOG=self.log_path, TERM="xterm-256color", PYTHONUNBUFFERED="1")
            interactions = open(self.log_path, encoding="utf-8", errors="replace")
            self.process = subprocess.Popen(["/bin/bash", SCRIPT], stdin=slave,
                                            stdout=slave, stderr=slave,
                                            start_new_session=True, env=env)
            os.close(slave)
            slave = None
            with self.lock:
                self.state = "running"
                self.revision += 1
            eof, exited_at = False, None
            while True:
                running = self.process.poll() is None
                now = time.monotonic()
                if not running:
                    exited_at = exited_at or now
                    if _group_active(self.process.pid):
                        self._attention("shell_exited")
                    elif eof or now - exited_at >= 1:
                        break
                if running and now - self.started >= ATTENTION_AFTER and not self.attention_reason:
                    self._attention("runtime_limit")
                try:
                    self._interactions(interactions)
                    with self.lock:
                        pending = bool(self._input) and running
                    readable, writable, _ = select.select(
                        [] if eof else [self.master], [self.master] if pending else [], [], .05)
                    if writable:
                        with self.lock:
                            try:
                                size = os.write(self.master, self._input[:16384])
                                del self._input[:size]
                            except BlockingIOError:
                                pass
                    if readable:
                        try:
                            chunk = os.read(self.master, 16384)
                        except BlockingIOError:
                            continue
                        except OSError as exc:
                            if exc.errno != errno.EIO:
                                raise
                            chunk = b""
                        if chunk:
                            self._append(decoder.decode(chunk))
                        else:
                            eof = True
                    if eof:
                        time.sleep(.05)
                except Exception:
                    # An observation failure must not turn into SIGTERM of
                    # dpkg. Keep owning the PTY and the single-job reservation.
                    self._attention("observation_failed")
                    time.sleep(.1)
            code = self.process.wait()
            self._append(decoder.decode(b"", final=True))
        except Exception as exc:
            self._append(f"\r\nHost update could not start: {type(exc).__name__}\r\n")
            # Popen/setup failure before launch is a recorded failure. Once
            # alive, preserve the updater even if observation setup failed.
            if self.process is not None:
                self._attention("observation_failed")
                code = self.process.wait()
        finally:
            for resource in (interactions, slave, self.master):
                if resource is not None:
                    try:
                        resource.close() if hasattr(resource, 'close') else os.close(resource)
                    except OSError:
                        pass
            self.master = None
            if self.log_path:
                try:
                    os.unlink(self.log_path)
                except OSError:
                    pass
        with self.lock:
            self.state = "finalizing"
            self.script_exit_code = self.exit_code = code
            self.interaction = None
            self._input.clear()
            self.revision += 1
        try:
            self.callback(SCRIPT, {"PROXMENUX_HOST_UPDATE_JOB": "1"}, code,
                          time.monotonic() - self.started)
        except Exception:
            self.finalization_error = True
            self.exit_code = code or 1
        finally:
            with self.lock:
                self.state = "complete"
                self.finished_at = time.time()
                self.revision += 1

    def view(self):
        with self.lock:
            return dict(id=self.id, state=self.state, created_at=self.created_at,
                        finished_at=self.finished_at, exit_code=self.exit_code,
                        script_exit_code=self.script_exit_code,
                        attention_reason=self.attention_reason,
                        finalization_error=self.finalization_error)

    def read(self, offset):
        with self.lock:
            begin = self.offset - len(self.output)
            cursor = max(begin, min(offset, self.offset))
            return dict(self.view(), text=self.output[cursor-begin:], offset=self.offset,
                        truncated=offset < begin, interaction=self.interaction,
                        revision=self.revision)

    def input(self, message):
        with self.lock:
            if self.state not in ("running", "attention") or self.master is None:
                return
            if isinstance(message, str):
                if any(c in message for c in ("\x03", "\x1a", "\x1c")):
                    raise ValueError("Host package updates cannot be cancelled from the viewer")
                encoded = message.encode()
                if len(encoded) > 16384 or len(self._input) + len(encoded) > MAX_INPUT:
                    raise ValueError("Host update input buffer is full")
                self._input.extend(encoded)
            elif isinstance(message, dict) and message.get("type") == "resize":
                cols = max(20, min(400, int(message.get("cols", 120))))
                rows = max(5, min(200, int(message.get("rows", 30))))
                fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            elif isinstance(message, dict) and message.get("type") == "interaction_response":
                identity, value = message.get("id"), message.get("value")
                if (not isinstance(identity, str) or not INTERACTION_ID.fullmatch(identity)
                        or not self.interaction or identity != self.interaction["id"]
                        or not isinstance(value, str) or len(value.encode()) > 16384):
                    raise ValueError("No matching pending host update interaction")
                fd = os.open(f"/tmp/proxmenux_response_{identity}",
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w") as response:
                    response.write(value)
                self.interaction = None
                self.revision += 1
            else:
                raise ValueError("Unsupported host update input")


def _prune():
    for identity, job in list(_jobs.items()):
        if job.finished_at is not None and time.time() - job.finished_at > RESULT_TTL:
            del _jobs[identity]


def start(identity, callback):
    _identity(identity)
    if os.path.realpath(SCRIPT) != SCRIPT or not os.path.isfile(SCRIPT):
        raise ValueError("PVE update script is unavailable")
    with _lock:
        if identity in _jobs:
            return _jobs[identity]
        _prune()
        if any(job.state != "complete" for job in _jobs.values()):
            raise JobConflict("A host update is already running; reconnect to it")
        while len(_jobs) >= MAX_JOBS:
            del _jobs[min(_jobs, key=lambda key: _jobs[key].finished_at)]
        job = HostUpdateJob(identity, callback)
        _jobs[identity] = job
        try:
            job.launch()
        except BaseException:
            _jobs.pop(identity, None)
            raise
        return job


def get(identity):
    _identity(identity)
    with _lock:
        if identity not in _jobs:
            raise KeyError("Host update is unavailable; it was not restarted")
        return _jobs[identity]


def list_jobs():
    with _lock:
        _prune()
        return [job.view() for job in sorted(_jobs.values(), key=lambda job: job.created_at, reverse=True)]
