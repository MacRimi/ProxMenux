#!/usr/bin/env python3
"""Verify native OCI one-shot completion using authenticated raw LXC events.

No image wrapper, shell injection or STOPPED-state inference is used. The
supported monitor ABI was verified against upstream LXC v7.0.0 monitor.h,
monitor.c and tools/lxc_monitor.c. The textual CLI loses signal information.
This standalone helper is copied beside the persistent dependency hook.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import select
import socket
import stat
import struct
import subprocess
import tempfile
import time
import urllib.parse
import uuid

STATE_ROOT = Path('/var/lib/proxmenux/oci/jobs')
INSTANCE_ROOT = Path('/usr/local/share/proxmenux/oci/instances')
PCT = '/usr/sbin/pct'
MONITOR = '/usr/bin/lxc-monitor'
LXC_PATH = '/var/lib/lxc'
FRAME = struct.Struct('@i256si')
SUPPORTED_VERSIONS = frozenset({'7.0.0'})
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')


class JobError(RuntimeError):
    pass


def _vmid(value):
    if type(value) is not int or not 100 <= value <= 999999999:
        raise JobError('Invalid OCI job VMID')
    return value


def _root():
    if os.geteuid() != 0:
        raise JobError('OCI job execution requires root')


def _trusted_read(path, *, owner=0):
    """Open a root-owned regular file without following its final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
            raise JobError('Untrusted OCI job metadata file')
        if info.st_size > 8 * 1024 * 1024:
            raise JobError('OCI job metadata file is too large')
        with os.fdopen(fd, 'r', encoding='utf-8') as source:
            fd = -1
            return source.read()
    finally:
        if fd >= 0:
            os.close(fd)


def _private_directory(path):
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077):
        raise JobError('OCI job state directory is not private')


def config_fingerprint(text):
    """Presentation and resource changes do not re-run a completed migration."""
    selected = []
    for line in text.split('\n'):
        if line.startswith('['):
            break  # Pending/snapshot sections are not the active definition.
        key, separator, value = line.partition(': ')
        if not separator:
            continue
        if (key in {'entrypoint', 'env', 'rootfs', 'unprivileged', 'features', 'ostype'}
                or re.fullmatch(r'(?:mp|dev)[0-9]+', key)
                or key.startswith(('lxc.init.', 'lxc.environment.', 'lxc.mount.',
                                   'lxc.cgroup', 'lxc.apparmor', 'lxc.seccomp'))):
            if key == 'rootfs' or re.fullmatch(r'mp[0-9]+', key):
                value = ','.join(part for part in value.split(',') if not part.startswith('size='))
            selected.append((key, value))
    if not any(key == 'rootfs' for key, _ in selected):
        raise JobError('OCI job has no root filesystem configuration')
    selected.sort(key=lambda item: item[0])
    return hashlib.sha256(json.dumps(selected, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def _config_text(vmid):
    # Validate the actual PVE file's ownership; use the same API rendering
    # whose exact hash the coordinated transaction authorizes.
    _trusted_read(Path('/etc/pve/lxc') / f'{vmid}.conf')
    result = subprocess.run([PCT, 'config', str(vmid)], capture_output=True, check=True, timeout=15)
    return result.stdout.decode('utf-8')


def _record_digest(record, config_text, *, executing=False):
    pending = record.get('pending_transaction')
    if not pending:
        return record.get('observed', {}).get('resolved_registry_digest')
    vmid = _vmid(record.get('vmid'))
    if record.get('status') != 'updating' or not record.get('pending_stack_transaction'):
        raise JobError('OCI job has no authorized coordinated update context')
    journal = Path(pending)
    try:
        relative = journal.relative_to(INSTANCE_ROOT / str(vmid) / 'transactions')
    except ValueError as error:
        raise JobError('OCI job transaction is outside its private instance state') from error
    if (len(relative.parts) != 2 or relative.parts[1] != 'transaction.json'
            or not re.fullmatch(r'[0-9a-f]{32}', relative.parts[0])):
        raise JobError('Invalid OCI job transaction path')
    child = json.loads(_trusted_read(journal))
    coordinated = child.get('coordinated') or {}
    if (child.get('schema_version') != 1 or child.get('id') != record.get('transaction_id')
            or child.get('id') != relative.parts[0] or child.get('vmid') != vmid
            or child.get('phase') not in {'candidate-installed', 'health-passed', 'committing'}
            or child.get('record', {}).get('installation_id') != record.get('installation_id')
            or coordinated.get('journal') != record.get('pending_stack_transaction')
            or child.get('staged_config_sha256') != hashlib.sha256(config_text.encode()).hexdigest()):
        raise JobError('OCI job staged image is not bound to this actual container configuration')
    stack_journal = Path(record['pending_stack_transaction'])
    try:
        stack_path = stack_journal.relative_to(INSTANCE_ROOT)
    except ValueError as error:
        raise JobError('OCI job stack transaction is outside private instance state') from error
    if (len(stack_path.parts) != 4 or not stack_path.parts[0].isdigit()
            or stack_path.parts[1] != 'stack-transactions'
            or not re.fullmatch(r'[0-9a-f]{32}', stack_path.parts[2])
            or stack_path.parts[3] != 'transaction.json'):
        raise JobError('Invalid OCI job stack transaction path')
    stack = json.loads(_trusted_read(stack_journal))
    phases = {'starting', 'checking', 'publishing', 'recovering'}
    if not executing:
        phases.add('replacing')
    members = stack.get('plan', {}).get('members') or []
    if (stack.get('schema_version') != 1 or stack.get('id') != coordinated.get('id')
            or stack.get('phase') not in phases
            or not any(member.get('vmid') == vmid
                       and member.get('installation_id') == record.get('installation_id')
                       for member in members)):
        raise JobError('OCI job is not authorized by the active stack transaction')
    return child.get('registry_digest')


def job_spec_from_record(record, config_text, timeout_seconds=300):
    """Bind a first installation, staged update or restored member for its hook."""
    if isinstance(config_text, bytes):
        config_text = config_text.decode('utf-8')
    if not isinstance(config_text, str) or not isinstance(record, dict):
        raise JobError('Invalid OCI job binding input')
    if type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 3600:
        raise JobError('OCI job timeout must be between 30 and 3600 seconds')
    _vmid(record.get('vmid'))
    try:
        installation_id = str(uuid.UUID(record['installation_id']))
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise JobError('OCI job requires an installation identity') from error
    digest = _record_digest(record, config_text)
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise JobError('OCI job requires a verified image digest')
    return {'installation_id': installation_id, 'image_digest': digest,
            'expected_config_fingerprint': config_fingerprint(config_text),
            'timeout_seconds': timeout_seconds}


def current_identity(vmid, spec):
    """Bind the request to both a trusted instance record and the actual CT."""
    _vmid(vmid)
    if not isinstance(spec, dict):
        raise JobError('Invalid OCI job specification')
    try:
        installation_id = str(uuid.UUID(spec['installation_id']))
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise JobError('OCI job requires an installation identity') from error
    digest = spec.get('image_digest')
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise JobError('OCI job requires a verified image digest')
    record = json.loads(_trusted_read(INSTANCE_ROOT / str(vmid) / 'oci-compose.json'))
    if record.get('vmid') != vmid or record.get('installation_id') != installation_id:
        raise JobError('OCI job installation identity changed')
    config = _config_text(vmid)
    if _record_digest(record, config, executing=True) != digest:
        raise JobError('OCI job image digest changed')
    description = next((line.partition(': ')[2] for line in config.split('\n')
                        if line.startswith('description: ')), '')
    markers = re.findall(r'proxmenux-instance=([0-9a-fA-F-]{36})', urllib.parse.unquote(description))
    if installation_id not in markers:
        raise JobError('The CT does not carry the OCI job installation identity')
    fingerprint = config_fingerprint(config)
    if spec.get('expected_config_fingerprint', fingerprint) != fingerprint:
        raise JobError('OCI job runtime configuration changed')
    recovery = record.get('recovered_at', '')
    if not isinstance(recovery, str):
        raise JobError('Invalid OCI job recovery generation')
    return {'vmid': vmid, 'installation_id': installation_id, 'image_digest': digest,
            'config_fingerprint': fingerprint, 'recovery_generation': recovery}


def _status(vmid):
    result = subprocess.run([PCT, 'status', str(vmid)], capture_output=True, text=True, timeout=15)
    value = result.stdout.strip()
    if result.returncode or value not in {'status: stopped', 'status: running'}:
        raise JobError('Cannot establish the OCI job container state')
    return value.removeprefix('status: ')


def _socket_name(lxcpath=LXC_PATH):
    value = 14695981039346656037
    for byte in ('lxc/'+lxcpath+'/monitor-sock').encode():
        value = ((value ^ byte) * 1099511628211) & ((1 << 64)-1)
    return f'lxc/{value:016x}/{lxcpath}'


@contextlib.contextmanager
def _subscription():
    version = subprocess.run([MONITOR, '--version'], capture_output=True, text=True,
                             check=True, timeout=10).stdout.strip()
    if version not in SUPPORTED_VERSIONS or FRAME.size != 264:
        raise JobError('Unsupported native LXC monitor ABI; refusing to guess job completion')
    # This CLI only bootstraps monitord when no other container has started it.
    # Its lossy textual exit status is NEVER consumed.
    primer = subprocess.Popen([MONITOR, '-n', '^$'], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              close_fds=True)
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        receiver.settimeout(1)
        deadline = time.monotonic()+5
        name = _socket_name()
        while True:
            try:
                receiver.connect(b'\0'+name.encode())
                break
            except (ConnectionRefusedError, FileNotFoundError):
                if time.monotonic() >= deadline:
                    raise JobError('Native LXC monitor subscription could not be established')
                time.sleep(.05)
        peer = struct.unpack('3i', receiver.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                      struct.calcsize('3i')))
        pid, uid, gid = peer
        executable = str(Path(f'/proc/{pid}/exe').resolve())
        if uid != 0 or gid != 0 or executable not in {
                '/usr/libexec/lxc/lxc-monitord', '/usr/lib/lxc/lxc-monitord'}:
            raise JobError('Native LXC monitor peer is not the trusted root daemon')
        receiver.setblocking(False)
        yield receiver, {'version': version, 'peer_uid': uid, 'peer_gid': gid,
                         'peer_executable': executable, 'protocol': 'lxc-msg-native264'}
    finally:
        receiver.close()
        primer.terminate()
        try:
            primer.wait(timeout=3)
        except subprocess.TimeoutExpired:
            primer.kill()
            primer.wait(timeout=3)


def _frames(buffer):
    messages = []
    while len(buffer) >= FRAME.size:
        chunk, buffer = buffer[:FRAME.size], buffer[FRAME.size:]
        kind, name, value = FRAME.unpack(chunk)
        if kind not in {0, 1, 2}:
            raise JobError('Unknown native LXC monitor event')
        try:
            name = name.split(b'\0', 1)[0].decode('ascii')
        except UnicodeDecodeError as error:
            raise JobError('Malformed native LXC monitor event') from error
        messages.append((kind, name, value))
    return messages, buffer


def _run_attempt(vmid, deadline):
    with _subscription() as (receiver, proof):
        # Drain traffic before our start; events from unrelated guests do not
        # become evidence for this job. There is no historical event replay.
        pending = b''
        while select.select([receiver], [], [], 0)[0]:
            data = receiver.recv(8192)
            if not data:
                raise JobError('Native LXC monitor closed before job start')
            messages, pending = _frames(pending+data)
            if any(name == str(vmid) for _, name, _ in messages):
                raise JobError('OCI job changed state before its start attempt')
        started = False
        # Fast successful PID1 jobs can make pct start return 255 because
        # Proxmox can no longer query the PID. Only raw exit evidence decides.
        process = subprocess.Popen([PCT, 'start', str(vmid)], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   close_fds=True)
        try:
            while time.monotonic() < deadline:
                if not select.select([receiver], [], [], min(1, max(.01, deadline-time.monotonic())))[0]:
                    continue
                data = receiver.recv(8192)
                if not data:
                    raise JobError('Native LXC monitor closed without a job exit event')
                messages, pending = _frames(pending+data)
                for kind, name, value in messages:
                    if name != str(vmid):
                        continue
                    if kind == 0 and value in {1, 2}:
                        started = True
                    if kind != 2:
                        continue
                    if not started or not 0 <= value <= 65535:
                        raise JobError('No fresh, valid native OCI job exit proof')
                    if not os.WIFEXITED(value):
                        reason = f'signal {os.WTERMSIG(value)}' if os.WIFSIGNALED(value) else 'unknown wait status'
                        raise JobError(f'OCI job CT {vmid} did not complete normally ({reason})')
                    exitcode = os.WEXITSTATUS(value)
                    if exitcode != 0:
                        raise JobError(f'OCI job CT {vmid} exited with code {exitcode}')
                    while _status(vmid) != 'stopped':
                        if time.monotonic() >= deadline:
                            raise JobError('OCI job reported exit zero but did not stop')
                        time.sleep(.05)
                    process.wait(timeout=max(.1, min(5, deadline-time.monotonic())))
                    return {**proof, 'raw_waitstatus': value, 'exit_code': exitcode,
                            'fresh_start_observed': True, 'pct_start_returncode': process.returncode}
            raise JobError('OCI job timed out without verified native exit zero')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def _cache_matches(cache, identity):
    return (isinstance(cache, dict) and cache.get('schema') == 1
            and cache.get('status') == 'completed' and cache.get('identity') == identity
            and isinstance(cache.get('proof'), dict)
            and type(cache['proof'].get('raw_waitstatus')) is int
            and cache['proof']['raw_waitstatus'] == 0
            and cache['proof'].get('fresh_start_observed') is True)


def _read_cache(path):
    try:
        return json.loads(_trusted_read(path))
    except FileNotFoundError:
        return None


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_cache(path, value):
    descriptor, name = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump(value, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        _sync_directory(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)


@contextlib.contextmanager
def _job_lock(vmid, deadline):
    _private_directory(STATE_ROOT)
    fd = os.open(STATE_ROOT/f'{vmid}.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise JobError('Untrusted OCI job lock file')
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise JobError('Timed out waiting for another OCI job attempt')
                time.sleep(.05)
        yield
    finally:
        os.close(fd)


def ensure_completed(vmid, job_spec, force=False):
    _root()
    _vmid(vmid)
    if type(force) is not bool:
        raise JobError('Invalid OCI job force flag')
    timeout = job_spec.get('timeout_seconds', 300) if isinstance(job_spec, dict) else None
    if type(timeout) is not int or not 30 <= timeout <= 3600:
        raise JobError('OCI job timeout must be between 30 and 3600 seconds')
    deadline = time.monotonic()+timeout
    with _job_lock(vmid, deadline):
        identity = current_identity(vmid, job_spec)
        if _status(vmid) != 'stopped':
            raise JobError('OCI job is already running without this attempt\'s exit subscription')
        path = STATE_ROOT/f'{vmid}.json'
        cache = _read_cache(path)
        if not force and _cache_matches(cache, identity):
            return {'status': 'completed', 'cached': True, **identity, 'proof': cache['proof']}
        # A forced failed retry must never leave an earlier success reusable.
        if path.exists():
            path.unlink()
            _sync_directory(path.parent)
        proof = _run_attempt(vmid, deadline)
        if current_identity(vmid, job_spec) != identity:
            raise JobError('OCI job identity or configuration changed during execution')
        if _status(vmid) != 'stopped':
            raise JobError('OCI job restarted before completion could be recorded')
        value = {'schema': 1, 'status': 'completed', 'identity': identity, 'proof': proof,
                 'attempt_id': str(uuid.uuid4()),
                 'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        _write_cache(path, value)
        return {'status': 'completed', 'cached': False, **identity, 'proof': proof}


def forget_completed(vmid, installation_id):
    """Remove only this installation's completion, never a reused VMID's state."""
    _vmid(vmid)
    try:
        installation_id = str(uuid.UUID(installation_id))
    except (ValueError, TypeError, AttributeError):
        return False  # Older non-job records may use a legacy identity format.
    if not STATE_ROOT.exists():
        return False
    _root()
    with _job_lock(vmid, time.monotonic()+30):
        path = STATE_ROOT/f'{vmid}.json'
        cache = _read_cache(path)
        if (not isinstance(cache, dict) or not isinstance(cache.get('identity'), dict)
                or cache['identity'].get('installation_id') != installation_id):
            return False
        path.unlink()
        _sync_directory(path.parent)
        # The stable lock inode stays: unlinking it could split concurrent
        # waiters across two locks when this numeric VMID is reused.
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['ensure'])
    parser.add_argument('vmid', type=int)
    parser.add_argument('--spec-json', required=True)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        if len(args.spec_json) > 65536:
            raise JobError('OCI job specification is too large')
        result = ensure_completed(args.vmid, json.loads(args.spec_json), force=args.force)
    except (JobError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(str(error), file=__import__('sys').stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
