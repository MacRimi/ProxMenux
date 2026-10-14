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


def acquire(vmid):
    path = LOCK_DIR / f'proxmenux-lxc-update-{int(vmid)}.lock'
    handle = os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'r+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except BaseException:
        handle.close()
        raise


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
    invalid = LOCK_DIR / f'proxmenux-lxc-check-invalid-{int(vmid)}'
    try:
        invalid.touch(mode=0o600)
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
            try:
                invalid.unlink()
            except OSError:
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
