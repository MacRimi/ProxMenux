"""Copies of the app registrations of a container that outlive the node.

The registrations of a container live on the disk of the node, by VMID. Two
copies go with them, as the OCI records do:

- inside the container, in its root filesystem, so a backup carries them: a
  container restored under another VMID, or in a different order, brings its
  own apps. The container could change this copy, so every app in it is
  validated again before it is used;
- in /etc/pve, which every node of a cluster shares and only root of the host
  reads, so a container that migrates finds its apps on the node it moves to.

Only the configuration of the apps is copied, never their check results.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Optional

DIRECTORY = '.proxmenux'
NAME = 'app-watch.json'
KIND = 'proxmenux.app-watch'
LIMIT = 1024 * 1024
CLUSTER = Path('/etc/pve/priv/proxmenux/apps')
PVE_ROOT = '/etc/pve'
# Per app, what is not configuration: the result of its checks.
RUNTIME_FIELDS = ('state', 'updated_at')


def _run(*args, timeout=15):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout)


def running_pid(vmid) -> Optional[int]:
    try:
        result = _run('lxc-info', '-n', str(int(vmid)), '-pH')
    except (OSError, subprocess.SubprocessError):
        return None
    pid = result.stdout.strip()
    return int(pid) if result.returncode == 0 and pid.isdigit() else None


def mapped_root(vmid):
    """The host owner that is root inside the container."""
    try:
        config = _run('pct', 'config', str(int(vmid))).stdout
    except (OSError, subprocess.SubprocessError):
        config = ''
    owner = {}
    for line in config.splitlines():
        fields = line.partition(': ')[2].split()
        if line.startswith('lxc.idmap: ') and len(fields) == 4 and fields[1] == '0' and fields[0] in 'ug':
            owner.setdefault(fields[0], int(fields[2]))
    default = 100000 if re.search(r'^unprivileged: 1$', config, re.MULTILINE) else 0
    return owner.get('u', default), owner.get('g', default)


def payload(vmid, sidecar: dict) -> dict:
    """What travels: the configuration of each app, without results."""
    apps = []
    for app in sidecar.get('apps') or []:
        if isinstance(app, dict):
            apps.append({k: v for k, v in app.items() if k not in RUNTIME_FIELDS})
    return {'kind': KIND, 'schema_version': 1, 'vmid': int(vmid),
            'watch_id': sidecar.get('watch_id'), 'identity': sidecar.get('identity') or {},
            'apps': apps, 'dismissed_slugs': list(sidecar.get('dismissed_slugs') or [])}


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def valid(value) -> bool:
    return (isinstance(value, dict) and value.get('kind') == KIND and value.get('schema_version') == 1
            and isinstance(value.get('watch_id'), str) and value['watch_id']
            and isinstance(value.get('apps'), list))


# ── Inside the container ─────────────────────────────────────────────

def _root(pid) -> str:
    return f'/proc/{int(pid)}/root'


def _directory(root, owner=None):
    """The private folder of the copy, opened without following a link the
    container could have left in its place."""
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        if owner is not None:
            with contextlib.suppress(FileExistsError):
                os.mkdir(DIRECTORY, 0o700, dir_fd=root_fd)
        fd = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    finally:
        os.close(root_fd)
    if owner is not None:
        os.fchown(fd, *owner)
        os.fchmod(fd, 0o700)
    return fd


def _read_from(directory_fd) -> Optional[dict]:
    try:
        fd = os.open(NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError:
        return None
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            return None
        try:
            value = json.loads(source.read(LIMIT))
        except ValueError:
            return None
    return value if valid(value) else None


def read_container(vmid, pid=None) -> Optional[dict]:
    """The copy a running container carries, or None."""
    pid = pid or running_pid(vmid)
    if not pid:
        return None
    try:
        directory = _directory(_root(pid))
    except OSError:
        return None
    try:
        return _read_from(directory)
    finally:
        os.close(directory)


def write_container(vmid, value: dict, pid=None) -> bool:
    pid = pid or running_pid(vmid)
    if not pid:
        return False
    owner = mapped_root(vmid)
    directory = _directory(_root(pid), owner)
    temporary = f'.{NAME}.{os.getpid()}'
    try:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(value, output, sort_keys=True)
                output.flush()
                os.fchown(output.fileno(), *owner)
                os.fsync(output.fileno())
            os.rename(temporary, NAME, src_dir_fd=directory, dst_dir_fd=directory)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary, dir_fd=directory)
            raise
        os.fsync(directory)
    finally:
        os.close(directory)
    return True


def remove_container(vmid, pid=None) -> None:
    pid = pid or running_pid(vmid)
    if not pid:
        return
    with contextlib.suppress(OSError):
        directory = _directory(_root(pid))
        try:
            os.unlink(NAME, dir_fd=directory)
        finally:
            os.close(directory)


def machine_id(vmid, pid=None) -> Optional[str]:
    """The machine ID of a running container: it travels with its backup."""
    pid = pid or running_pid(vmid)
    if not pid:
        return None
    try:
        root_fd = os.open(_root(pid), os.O_RDONLY | os.O_DIRECTORY)
        try:
            etc = os.open('etc', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        finally:
            os.close(root_fd)
        try:
            fd = os.open('machine-id', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=etc)
        finally:
            os.close(etc)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return None
            value = source.read(64).decode('ascii', 'replace').strip()
    except OSError:
        return None
    return value if re.fullmatch(r'[0-9a-f]{32}', value) else None


# ── In the cluster ───────────────────────────────────────────────────

def _cluster_ready() -> bool:
    # Unmounted, /etc/pve is a plain folder of the disk: a file written
    # there would keep pve-cluster from starting.
    return os.path.ismount(PVE_ROOT)


def read_cluster(vmid) -> Optional[dict]:
    if not _cluster_ready():
        return None
    path = CLUSTER / f'{int(vmid)}.json'
    try:
        if path.is_symlink() or path.stat().st_size > LIMIT:
            return None
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if valid(value) else None


def write_cluster(vmid, value: dict) -> bool:
    if not _cluster_ready():
        return False
    CLUSTER.mkdir(parents=True, exist_ok=True)
    path = CLUSTER / f'{int(vmid)}.json'
    temporary = path.with_name(f'.{path.name}.{os.getpid()}')
    temporary.write_text(json.dumps(value, sort_keys=True))
    os.replace(temporary, path)
    return True


def remove_cluster(vmid) -> None:
    if _cluster_ready():
        with contextlib.suppress(FileNotFoundError):
            (CLUSTER / f'{int(vmid)}.json').unlink()


# ── Writing both ─────────────────────────────────────────────────────

_written: dict = {}


def write(vmid, sidecar: dict) -> None:
    """Keep both copies in line with the registrations; only when their
    configuration changed. Never raises: the record on the node is what the
    Monitor uses."""
    value = payload(vmid, sidecar)
    if not value['watch_id']:
        return
    key = digest(value)
    if _written.get(int(vmid)) == key:
        return
    complete = True
    for writer in (write_container, write_cluster):
        try:
            complete = writer(vmid, value) and complete
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            complete = False
            print(f'[ProxMenux] app_watch_copies: {writer.__name__} CT {vmid}: {error}')
    if complete:
        _written[int(vmid)] = key


def remove(vmid) -> None:
    _written.pop(int(vmid), None)
    for remover in (remove_container, remove_cluster):
        try:
            remover(vmid)
        except (OSError, subprocess.SubprocessError):
            pass


def forget(vmid) -> None:
    """The next write goes to the copies again, as after adopting them."""
    _written.pop(int(vmid), None)
