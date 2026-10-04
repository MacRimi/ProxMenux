#!/usr/bin/env python3
"""Copies of the record of an OCI application that outlive the host record.

The record of an installation lives on the disk of the node that installed
it. Two copies are kept with it, written together after every operation:

- inside the container, in its root filesystem, so a backup carries it: a
  container restored on another Proxmox host, or on this one after a
  reinstall, still has what is needed to register it again. The container
  could change this copy, so it is checked against the configuration Proxmox
  restored before anything is taken from it;
- in /etc/pve, which every node of a cluster shares and only root of the host
  reads, so a container that migrates finds its record on the node it moves
  to. This one is trusted.

Neither is read back as a source of truth while the host record is current.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import uuid

import oci_instances as instances
from oci_installation_state import sha
from oci_ui import translate

DIRECTORY = '.proxmenux'
NAME = 'oci-record.json'
KIND = 'proxmenux.oci-carried-record'
STAMP = 'carried.sha256'
LIMIT = 16 * 1024 * 1024
STACK_CONTRACT = '/etc/pve/priv/proxmenux-stack-{}.json'
NVIDIA_HOOK = re.compile(r'/usr/local/lib/proxmenux/oci/nvidia-mount-([a-f0-9]{64})\.sh')
SNIPPETS = Path('/var/lib/vz/snippets')
# Every node of a cluster reads this folder and only root of the host can:
# a container that moves to another node finds its record there.
CLUSTER = Path('/etc/pve/priv/proxmenux/oci')
RCLONE_HOOK = re.compile(r'^hookscript: local:snippets/(proxmenux-rclone-[0-9]+-fuse-hook\.sh)$', re.MULTILINE)


def _run(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)


def running_pid(vmid):
    result = _run('lxc-info', '-n', str(int(vmid)), '-pH')
    pid = result.stdout.strip()
    return int(pid) if result.returncode == 0 and pid.isdigit() else None


@contextlib.contextmanager
def container_root(vmid, mount_stopped=True):
    """The root filesystem of the container as the host sees it, or None. A
    running container is reached through its init process; a stopped one is
    mounted for as long as the block lasts."""
    pid = running_pid(vmid)
    if pid:
        yield Path(f'/proc/{pid}/root')
        return
    if not mount_stopped or _run('pct', 'mount', str(int(vmid))).returncode != 0:
        yield None
        return
    try:
        yield Path(f'/var/lib/lxc/{int(vmid)}/rootfs')
    finally:
        _run('pct', 'unmount', str(int(vmid)))


def mapped_root(config):
    """The host owner that is root inside the container."""
    owner = {}
    for line in config.splitlines():
        fields = line.partition(': ')[2].split()
        if line.startswith('lxc.idmap: ') and len(fields) == 4 and fields[1] == '0' and fields[0] in 'ug':
            owner.setdefault(fields[0], int(fields[2]))
    default = 100000 if re.search(r'^unprivileged: 1$', config, re.MULTILINE) else 0
    return owner.get('u', default), owner.get('g', default)


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


def valid_copy(value):
    return (isinstance(value, dict) and value.get('kind') == KIND and value.get('schema_version') == 1
            and isinstance(value.get('record'), dict))


def read_cluster(vmid):
    """The copy the cluster keeps for a container, or None."""
    path = CLUSTER / f'{int(vmid)}.json'
    try:
        if path.is_symlink() or path.stat().st_size > LIMIT:
            return None
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if valid_copy(value) else None


def write_cluster(vmid, value):
    """Best effort: /etc/pve is read-only without quorum and takes files of
    up to 1 MiB. The copy inside the container does not depend on it."""
    try:
        CLUSTER.mkdir(parents=True, exist_ok=True)
        (CLUSTER / f'{int(vmid)}.json').write_text(json.dumps(value))
    except OSError:
        return False
    return True


def remove_cluster(vmid):
    with contextlib.suppress(OSError):
        (CLUSTER / f'{int(vmid)}.json').unlink()


def keep_cluster(vmid, value, generation):
    """Leave in the cluster the same copy the container carries."""
    shared = read_cluster(vmid)
    if shared is not None and digest(shared) == digest(value) and shared.get('generation') == generation:
        return
    write_cluster(vmid, dict(value, generation=generation, saved_at=value.get('saved_at')
                             or datetime.datetime.now(datetime.timezone.utc).isoformat()))


def replaced_elsewhere(record, record_path, shared, node):
    """Whether another node of the cluster wrote a different record for this
    container after the one of this host: the container was changed there and
    came back."""
    if shared is None or shared.get('node') == node or shared['record'] == record \
            or shared['record'].get('installation_id') != record['installation_id'] \
            or shared['record'].get('vmid') != record['vmid']:
        return False
    try:
        saved = datetime.datetime.fromisoformat(str(shared.get('saved_at')))
        return saved.timestamp() > record_path.stat().st_mtime
    except (ValueError, OSError, TypeError):
        return False


def read_copy(root):
    """The copy a container carries, or None when it has none that can be used."""
    try:
        directory = _directory(root)
    except OSError:
        return None
    try:
        fd = os.open(NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    except OSError:
        return None
    finally:
        os.close(directory)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            return None
        try:
            value = json.loads(source.read(LIMIT))
        except ValueError:
            return None
    return value if valid_copy(value) else None


def write_copy(root, value, owner):
    directory = _directory(root, owner)
    temporary = f'.{NAME}.{os.getpid()}'
    try:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(value, output)
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


def rclone_mount(config):
    """Where the hookscript of an Rclone container publishes its mount on the
    host. The hookscript itself is written again from the engine."""
    hook = RCLONE_HOOK.search(config)
    if not hook:
        return None
    path = SNIPPETS / hook[1]
    try:
        if path.is_symlink():
            return None
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    name = re.search(r'^inside=/data/mounts/(\S+)$', text, re.MULTILINE)
    views = {key: re.search(rf'^{key}=(/\S+)/(\S+)$', text, re.MULTILINE) for key in ('published', 'published_ro')}
    parent = re.search(r'^\s*if ! mountpoint -q (/\S+); then$', text, re.MULTILINE)
    if not name or not parent or not all(views.values()) \
            or any(view[2] != name[1] for view in views.values()):
        return None
    return {'mount_name': name[1], 'shared_mount_root': views['published'][1],
            'shared_mount_read_only_root': views['published_ro'][1], 'shared_mount_root_parent': parent[1]}


def bundle(record, config):
    """What the container carries: its record and the host files a start of
    the application depends on."""
    vmid = record['vmid']
    value = {'schema_version': 1, 'kind': KIND, 'node': socket.gethostname().split('.', 1)[0],
             'vmid': vmid, 'record': record}
    contract = Path(STACK_CONTRACT.format(vmid))
    if contract.is_file() and not contract.is_symlink():
        with contextlib.suppress(OSError, ValueError):
            value['stack_contract'] = json.loads(contract.read_text())
    hook = NVIDIA_HOOK.search(config)
    if hook:
        path = Path(hook[0])
        with contextlib.suppress(OSError, UnicodeDecodeError):
            if path.is_file() and not path.is_symlink() and sha(path.read_bytes()) == hook[1]:
                value['nvidia_hook'] = {'sha256': hook[1], 'content': path.read_text()}
    mount = rclone_mount(config)
    if mount:
        value['rclone_mount'] = mount
    return value


def digest(value):
    stable = {key: item for key, item in value.items() if key not in ('saved_at', 'generation')}
    return sha(json.dumps(stable, sort_keys=True, separators=(',', ':')).encode())


def read_stamp(path):
    """What this host last wrote into the container: the digest of the copy
    and the mark that tells that copy from any other."""
    try:
        text = path.read_text().strip()
    except OSError:
        return {}
    try:
        value = json.loads(text)
    except ValueError:
        return {'digest': text}
    return value if isinstance(value, dict) else {}


def superseded(record, existing, stamp):
    """Whether the container carries a copy this host did not write, with a
    record that differs from the one of this host. That is a container that
    came back: migrated to another node and changed there, restored from a
    backup made before the last operation, or rolled back to a snapshot. Its
    content is the one its own copy describes."""
    if not stamp.get('generation') or existing.get('generation') == stamp['generation']:
        return False
    carried_record = existing['record']
    return (carried_record.get('installation_id') == record['installation_id']
            and carried_record.get('vmid') == record['vmid'] and carried_record != record)


def carry(root, vmid, mount_stopped=True, verify=False, adopted=False):
    """Leave the current record inside its container. Returns 'carried',
    'current' when the copy was already up to date, 'skipped' when the
    instance is in the middle of an operation or cannot be reached, or
    'stale' when the container came back with another record: the record of
    this host is set aside, and the container is then recovered like any
    restored one. A stopped container is opened only when its copy is known to
    be old, or when `verify` asks to look anyway before an operation. A record
    that was just recovered is `adopted`: it replaces the copies it came from."""
    try:
        record = instances.read(root, vmid)
    except (OSError, ValueError, KeyError):
        return 'skipped'
    if record.get('status') != 'installed' or record.get('pending_transaction') \
            or record.get('pending_stack_transaction'):
        return 'skipped'
    result = _run('pct', 'config', str(vmid))
    if result.returncode != 0 or instances.identity(result.stdout.encode()) != record['installation_id']:
        return 'skipped'
    value = bundle(record, result.stdout)
    expected = digest(value)
    record_path = instances.location(root, vmid)
    path = record_path.parent / STAMP
    stamp = read_stamp(path)
    if not adopted and replaced_elsewhere(record, record_path, read_cluster(vmid), value['node']):
        record_path.replace(record_path.with_name(f"retired-{record['installation_id']}.json"))
        with contextlib.suppress(OSError):
            path.unlink()
        return 'stale'
    if not running_pid(vmid):
        if stamp.get('digest') == expected and stamp.get('generation') and not verify:
            keep_cluster(vmid, value, stamp['generation'])
            return 'current'
        if not mount_stopped:
            return 'skipped'
    try:
        with container_root(vmid, mount_stopped) as rootfs:
            if rootfs is None:
                return 'skipped'
            existing = read_copy(rootfs)
            if existing is not None and not adopted and superseded(record, existing, stamp):
                outcome = 'stale'
            elif existing is not None and digest(existing) == expected and existing.get('generation') \
                    and existing.get('generation') == stamp.get('generation'):
                outcome = 'current'
            else:
                value['saved_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                value['generation'] = uuid.uuid4().hex
                write_copy(rootfs, value, mapped_root(result.stdout))
                stamp = {'generation': value['generation']}
                outcome = 'carried'
        if outcome == 'stale':
            record_path.replace(record_path.with_name(f"retired-{record['installation_id']}.json"))
            with contextlib.suppress(OSError):
                path.unlink()
            return outcome
        path.write_text(json.dumps({'digest': expected, 'generation': stamp.get('generation')}) + '\n')
        path.chmod(0o600)
        if stamp.get('generation'):
            keep_cluster(vmid, value, stamp['generation'])
    except OSError:
        return 'skipped'
    return outcome


def registered(root):
    if not root.is_dir():
        return []
    return sorted(int(d.name) for d in root.iterdir()
                  if d.name.isdecimal() and instances.has_contract(root, int(d.name)))


def sync(root, vmids=None, mount_stopped=True, verify=False):
    """Bring the copies of the given instances, or of all, up to date. Never
    waits for the registry: an operation in progress carries its own copy
    when it ends."""
    try:
        with instances.locked(root):
            return {vmid: carry(root, vmid, mount_stopped, verify)
                    for vmid in (registered(root) if vmids is None else vmids)}
    except (BlockingIOError, OSError, ValueError):
        return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmid', type=int, nargs='*')
    parser.add_argument('--root', type=Path, default=instances.ROOT)
    parser.add_argument('--running-only', action='store_true')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    print(json.dumps(sync(args.root, args.vmid or None, not args.running_only, args.verify)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
