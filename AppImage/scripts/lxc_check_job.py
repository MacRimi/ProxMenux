"""Explicit check-only jobs; the shared updater lock protects each CT.

Importing or reading a job never probes a guest. Only start() may launch work
for an already-running CT; package indexes are never refreshed by starting one.
"""
import datetime
import fcntl
import json
import os
import re
from pathlib import Path
import subprocess
import threading
import time
import uuid

import managed_installs
import lxc_update_observation

LOCK_DIR = Path(os.environ.get('PROXMENUX_LOCK_DIR', '/run/lock'))
CONF_DIR = Path('/etc/pve/lxc')
OCI_REGISTRY = Path('/usr/local/share/proxmenux/oci/installed.json')
_lock = threading.RLock()
_jobs = {}
_attempts = {}
COOLDOWN = 60
JOB_TTL = 3600
CONTROL_TASK_WAIT_SECONDS = 180


def acquire(vmid):
    path = LOCK_DIR / f'proxmenux-lxc-update-{int(vmid)}.lock'
    handle = os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'r+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check_control_task(vmid, handle)
        return handle
    except BaseException:
        handle.close()
        raise


def _invalid_marker(vmid):
    return LOCK_DIR / f'proxmenux-lxc-check-invalid-{int(vmid)}'


def _acquire_invalid_marker_guard(vmid):
    path = LOCK_DIR / f'proxmenux-lxc-check-invalid-{int(vmid)}.guard'
    handle = os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'r+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle
    except BaseException:
        handle.close()
        raise


def _mark_check_invalid(vmid):
    handle = _acquire_invalid_marker_guard(vmid)
    try:
        _invalid_marker(vmid).touch(mode=0o600)
    finally:
        handle.close()


def clear_invalid_marker(vmid, *, check_started_ns=None):
    """Clear an obsolete failed-check marker without hiding a newer run."""
    try:
        handle = _acquire_invalid_marker_guard(vmid)
    except OSError:
        return False
    try:
        marker = _invalid_marker(vmid)
        try:
            if (check_started_ns is not None
                    and marker.stat().st_mtime_ns > check_started_ns):
                return False
            marker.unlink()
            return True
        except FileNotFoundError:
            # A concurrent successful check may already have published the
            # valid state; there is no stale marker left to clear.
            return True
        except OSError:
            return False
    finally:
        handle.close()


def _write_control(handle, record):
    handle.seek(0)
    if record is not None:
        handle.write(json.dumps(record))
    handle.flush()
    # Do not erase the old reservation before the replacement was written.
    # A partial/failed write stays non-empty and therefore fails closed.
    handle.truncate(handle.tell())


def begin_control(handle, node):
    """Persist uncertainty before submission, including across Monitor restart."""
    if not isinstance(node, str) or not re.fullmatch(r'[\w.-]+', node):
        raise ValueError('Invalid control node')
    _write_control(handle, {'node': node, 'task': None})


def cancel_control(handle):
    """Clear a request for which no recoverable task identity was recorded."""
    _write_control(handle, None)


def check_control_task(vmid, handle=None):
    """Called under the shared flock, also by the shell update runner.

    No record means no probe. A restart releases OS file descriptors, but the
    record still forbids a new operation until PVE confirms task termination.
    Unknown submission/status cannot safely be treated as completion.
    """
    if handle is None:
        with open(LOCK_DIR / f'proxmenux-lxc-update-{int(vmid)}.lock', 'r+') as stream:
            return check_control_task(vmid, stream)
    handle.seek(0)
    raw = handle.read(1025)
    if not raw:
        return
    try:
        record = json.loads(raw)
        node, task = record['node'], record['task']
        if not isinstance(node, str) or not re.fullmatch(r'[\w.-]+', node):
            raise ValueError('Invalid node')
        if (not isinstance(task, str)
                or not re.fullmatch(r'UPID:[\w.-]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:'
                                    r'[0-9A-Fa-f]+:(?:vz(?:start|stop|shutdown|reboot)'
                                    r'|ha(?:start|stop)):'
                                    r'[0-9]+:[\w.@!-]+:', task)
                or task.split(':')[1] != node or task.split(':')[6] != str(vmid)):
            raise ValueError('Unconfirmed control task')
        result = subprocess.run(['pvesh', 'get', f'/nodes/{node}/tasks/{task}/status',
                                '--output-format', 'json'],
                               capture_output=True, text=True, timeout=5)
        status = json.loads(result.stdout) if result.returncode == 0 else None
        if (not isinstance(status, dict) or status.get('status') != 'stopped'
                or not isinstance(status.get('exitstatus'), str) or not status['exitstatus']):
            raise ValueError('Control task completion not confirmed')
    except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
        raise BlockingIOError('Container control completion is not confirmed') from exc
    _write_control(handle, None)


def _wait_control(vmid, reservation):
    deadline = time.monotonic() + CONTROL_TASK_WAIT_SECONDS
    try:
        while time.monotonic() < deadline:
            try:
                check_control_task(vmid, reservation)
                return
            except BlockingIOError:
                # Keep the known task record for recovery after this bounded
                # waiter exits; a later caller asks Proxmox to verify it.
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(2, remaining))
    finally:
        reservation.close()


def retain_control(vmid, task, reservation):
    reservation.seek(0)
    record = json.loads(reservation.read(1025))
    record['task'] = task
    _write_control(reservation, record)
    # Reservation ownership transfers only after Thread.start succeeds.
    threading.Thread(target=_wait_control, args=(vmid, reservation), daemon=True).start()


def guard(vmid):
    if not managed_installs._lxc_updates_detection_enabled():
        raise RuntimeError('LXC update detection is disabled')
    # Fail closed if current configuration cannot be read. Never infer OCI
    # eligibility from an old OS hint or from a failed config read.
    config = (CONF_DIR / f'{int(vmid)}.conf').read_text()
    # The normal collector tolerates broken OCI metadata. An action must
    # instead fail closed: an unreadable registry is not an empty registry.
    if OCI_REGISTRY.exists():
        registry = json.loads(OCI_REGISTRY.read_text())
        instances = registry.get('instances')
        if not isinstance(instances, dict) or any(not isinstance(item, dict) for item in instances.values()):
            raise RuntimeError('OCI registry could not be verified')
        if any(str(item.get('vmid')) == str(vmid) for item in instances.values()):
            raise RuntimeError('OCI containers require their own updater')
    if any(line.lstrip().startswith(managed_installs._OCI_LXC_MARKERS)
           for line in config.splitlines()) or str(vmid) in managed_installs._get_oci_managed_vmids():
        raise RuntimeError('OCI containers require their own updater')
    # Retain the independent registered-OCI boundary if its collector is
    # temporarily unavailable. These hints can only forbid an action.
    if any(str(item.get('_vmid')) == str(vmid) and item.get('_managed_oci_app')
           for item in managed_installs.get_active_items()):
        raise RuntimeError('OCI containers require their own updater')
    if any(line.startswith('lock:') for line in config.splitlines()):
        raise RuntimeError('Container is locked by Proxmox')


def command(vmid, *args, timeout=30):
    result = subprocess.run([managed_installs._PCT_BIN, *args[:1], str(vmid), *args[1:]],
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Container {args[0]} failed')
    return result.stdout.strip()


def status(vmid):
    value = command(vmid, 'status')
    if value not in ('status: running', 'status: stopped'):
        raise RuntimeError('Container state could not be determined')
    return value.split(': ', 1)[1]


def checked_os(vmid):
    """Installation precondition; called under the updater lock before start."""
    guard(vmid)
    if (LOCK_DIR / f'proxmenux-lxc-check-invalid-{int(vmid)}').exists():
        raise RuntimeError('Latest check failed or is still running')
    item = next((item for item in managed_installs.get_active_items()
                 if item.get('id') == f'lxc:{int(vmid)}'), {})
    observation = item.get('update_check') or {}
    checked = datetime.datetime.fromisoformat(observation.get('last_check') or '')
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=datetime.timezone.utc)
    age = (datetime.datetime.now(datetime.timezone.utc) - checked).total_seconds()
    if (not 0 <= age < 172800 or observation.get('error')
            or observation.get('available') is not True
            or type(observation.get('_count')) is not int or observation['_count'] <= 0):
        raise RuntimeError('Check OS updates successfully before installation')


def run(vmid, job_id, reservation):
    error = None
    check_started = False
    try:
        _mark_check_invalid(vmid)
        guard(vmid)
        if status(vmid) != 'running':
            raise RuntimeError('Container is stopped; start it first')
        check_started = True
        observation = lxc_update_observation.capture(vmid, job_id, refresh_indexes=True)
        if not managed_installs.store_lxc_update_observation(vmid, observation):
            raise RuntimeError(observation['result'].get('error') or 'Package check failed')
        lxc_update_observation.discard(vmid, job_id)
    except Exception as exc:
        error = str(exc)
        # A failed package operation must block installation. A state change
        # before the worker runs did not check or alter packages, so keep the
        # last verified observation but leave the invalid marker in place.
        if check_started:
            try:
                managed_installs.store_lxc_update_observation(vmid, None)
            except Exception:
                error += '; package result could not be persisted'
    finally:
        if not error:
            if not clear_invalid_marker(vmid):
                error = 'Successful check could not be published for installation'
        reservation.close()
        with _lock:
            _jobs[job_id].update(state='failed' if error else 'complete', error=error)


def start(vmid):
    now = time.monotonic()
    with _lock:
        for key in list(_jobs):
            if _jobs[key]['state'] != 'running' and now - _jobs[key]['created'] >= JOB_TTL:
                del _jobs[key]
        last = _attempts.get(vmid)
        if (any(job['vmid'] == vmid and job['state'] == 'running' for job in _jobs.values())
                or last is not None and now - last < COOLDOWN):
            return None, 429
        reservation = acquire(vmid)
        try:
            guard(vmid)
            if status(vmid) != 'running':
                raise RuntimeError('Container is stopped; start it first')
            job_id = uuid.uuid4().hex
            _jobs[job_id] = dict(vmid=vmid, state='running', error=None, created=now)
            _attempts[vmid] = now
            threading.Thread(target=run, args=(vmid, job_id, reservation), daemon=False).start()
        except BaseException:
            if 'job_id' in locals():
                _jobs.pop(job_id, None)
                _attempts.pop(vmid, None)
            reservation.close()
            raise
        return dict(job_id=job_id, vmid=vmid, state='running'), 202


def get(vmid, job_id):
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job['vmid'] != vmid:
            return None
        return {key: value for key, value in job.items() if key != 'created'}
