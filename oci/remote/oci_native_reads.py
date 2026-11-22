"""Fresh PVE reads without repeatedly importing the same native Perl modules.

A private child lives for one operation, never as a daemon. Every request runs
PVE's native read API again and refreshes pmxcfs versions. All writes and
unsupported command forms retain the ordinary CLI. On transport/API failure,
close the child and permanently fall back to fresh CLI reads for this operation.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import threading
import time

_ACTIVE = ContextVar('oci_native_read_session', default=None)
HELPER = Path(__file__).with_suffix('.pl')
MAX_REPLY = 64 * 1024 * 1024
TIMEOUT = 30


def request_for(args):
    args = tuple(str(arg) for arg in args)
    if (len(args) == 3 and args[0] == 'pct' and args[1] in ('config', 'status')
            and re.fullmatch(r'[1-9][0-9]{2,8}', args[2])):
        return {'op': args[1], 'vmid': int(args[2])}
    if args == ('pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'):
        return {'op': 'resources'}
    if args == ('pvesh', 'get', '/cluster/ha/resources', '--output-format', 'json'):
        return {'op': 'ha'}
    return None


def supported():
    return (os.geteuid() == 0 and os.environ.get('PROXMENUX_OCI_NATIVE_READS') != '0'
            and HELPER.is_file() and Path('/usr/bin/perl').is_file()
            and Path('/usr/share/perl5/PVE/API2/LXC/Config.pm').is_file())


class Unavailable(Exception):
    """Use the normal CLI again; never return cached data or exception payloads."""


class Reader:
    def __init__(self):
        self.process = None
        self.owner = os.getpid()
        self.sequence = 0
        self.broken = False
        self.lock = threading.Lock()
        self.counts = {}
        self.seconds = 0

    def _line(self):
        data = bytearray()
        deadline = time.monotonic() + TIMEOUT
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while len(data) <= MAX_REPLY:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise Unavailable()
                block = os.read(self.process.stdout.fileno(), min(65536, MAX_REPLY + 1 - len(data)))
                if not block:
                    raise Unavailable()
                data.extend(block)
                if b'\n' in block:
                    if data[-1:] != b'\n' or data.count(b'\n') != 1:
                        raise Unavailable()
                    return bytes(data)
        raise Unavailable()

    def read(self, request):
        if os.getpid() != self.owner or self.broken:
            return None
        with self.lock:
            started = time.monotonic()
            try:
                if self.process is None:
                    # Stay in the operation's process group: cancelling a
                    # batch must also terminate its read-only child.
                    self.process = subprocess.Popen(['/usr/bin/perl', str(HELPER)], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True,
                        bufsize=0)
                self.sequence += 1
                payload = dict(request, id=self.sequence)
                self.process.stdin.write(json.dumps(payload).encode() + b'\n')
                self.process.stdin.flush()
                reply = json.loads(self._line())
                if (not isinstance(reply, dict) or type(reply.get('id')) is not int
                        or reply['id'] != self.sequence or reply.get('ok') is not True):
                    raise Unavailable()
                result = reply['result']
                if request['op'] in ('config', 'status'):
                    if not isinstance(result, str):
                        raise Unavailable()
                    value = result.encode()
                else:
                    if not isinstance(result, list):
                        raise Unavailable()
                    value = json.dumps(result).encode()
                self.counts[request['op']] = self.counts.get(request['op'], 0) + 1
                return value
            except (OSError, ValueError, KeyError, Unavailable):
                self.broken = True
                self.close()
                return None
            finally:
                self.seconds += time.monotonic() - started

    def close(self):
        if self.process is None or os.getpid() != self.owner:
            return
        process, self.process = self.process, None
        try:
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        finally:
            process.stdout.close()


def read(args):
    current = _ACTIVE.get()
    if current is None:
        return None
    request = request_for(args)
    return current.read(request) if request else None


@contextmanager
def session(log=None):
    if _ACTIVE.get() is not None or not supported():
        yield
        return
    reader = Reader()
    token = _ACTIVE.set(reader)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
        reader.close()
        if log and (reader.counts or reader.broken):
            log('Native PVE reads: ' + json.dumps({'requests': reader.counts,
                'seconds': round(reader.seconds, 3), 'cli_fallback': reader.broken}, sort_keys=True))
