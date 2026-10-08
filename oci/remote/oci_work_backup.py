#!/usr/bin/env python3
"""Where the backup taken before changing an OCI application is written.

An update, a modification or a recreation stops the application and takes a
verified backup first, to go back to if the new container does not work; it
is deleted when the operation ends. That backup goes next to the record of
the application, on the system disk of the host. An application with a lot
of data may not fit there: the user can then choose a file storage of the
host that accepts backups, and the choice is kept in the record so later
operations, the scheduled ones included, use it without asking.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import socket
import subprocess

import oci_instances as instances
from oci_ui import translate

FOLDER = 'proxmenux-oci-work'
KEY = 'work_storage'
MARK = 'backup-location'
STORAGE_RE = re.compile(r'[A-Za-z0-9._-]{1,64}')


def gib(size):
    return f'{size / 1024**3:.1f} GB'


def required(vmids):
    """The data in use on the backed-up volumes plus a margin: data that is
    already compressed does not shrink."""
    import oci_instance_transaction as transaction
    return int(sum(transaction.backup_size(vmid) for vmid in vmids) * 1.1) + 1024**3


def available(path):
    """Free bytes where `path` is or will be created."""
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def file_storages():
    """The storages of this node that accept backups and are a directory of
    the host, with their free space: [{'storage', 'path', 'free'}]."""
    node = socket.gethostname().split('.', 1)[0]
    listed = subprocess.run(['pvesh', 'get', f'/nodes/{node}/storage', '--content', 'backup', '--enabled', '1',
                             '--output-format', 'json'], capture_output=True, text=True, timeout=60)
    if listed.returncode != 0:
        return []
    found = []
    for entry in json.loads(listed.stdout):
        name = str(entry.get('storage') or '')
        if not entry.get('active') or not STORAGE_RE.fullmatch(name):
            continue
        path = storage_path(name)
        if path is not None and path.is_dir():
            found.append({'storage': name, 'path': path, 'free': available(path)})
    return found


def storage_path(storage):
    """The directory of a file storage that accepts backups, or None."""
    if not STORAGE_RE.fullmatch(storage or ''):
        return None
    result = subprocess.run(['pvesh', 'get', f'/storage/{storage}', '--output-format', 'json'],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return None
    info = json.loads(result.stdout)
    if 'backup' not in str(info.get('content', '')).split(',') or not info.get('path'):
        return None
    return Path(info['path'])


def explain(needed, free, storage=None, storage_free=None):
    text = (f"{translate('The backup made before changing the application does not fit on the system disk of the host.')} "
            f"{translate('Needed:')} {gib(needed)}. {translate('Free:')} {gib(free)}.")
    if storage:
        text += (f" {translate('The storage chosen for this backup has no room either:')} {storage}"
                 + (f" ({gib(storage_free)})." if storage_free is not None else '.'))
    return (f"{text} {translate('The application was not modified.')} "
            f"{translate('Free space on the host, or choose another storage for this backup from Manage installed OCI applications.')}")


def locate(default, vmids, record, owner):
    """The directory the backups of one operation are written under: `default`
    when they fit there, otherwise a folder of its own on the storage chosen
    for the application. Nothing is created. Raises ValueError with what is
    needed when there is no room."""
    default = Path(default)
    needed = required(vmids)
    free = available(default)
    if free >= needed:
        return default
    storage = (record.get('deployment') or {}).get(KEY)
    path = storage_path(storage) if storage else None
    if path is None or not path.is_dir():
        raise ValueError(explain(needed, free))
    storage_free = available(path)
    if storage_free < needed:
        raise ValueError(explain(needed, free, storage, storage_free))
    return path / FOLDER / str(int(owner)) / default.name


def prepare(base):
    """Create the folder of an operation on another storage and make sure it
    can be written, before anything is stopped."""
    base = Path(base)
    try:
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        probe = base / '.write-test'
        probe.write_text('')
        probe.unlink()
    except OSError as error:
        raise ValueError(f"{translate('The storage chosen for this backup cannot be written:')} {base} ({error.strerror or error})")


def remember(directory, base):
    """Leave in the folder of the operation where its backups are, when they
    are not in that folder: a recovery or a cleanup reads it from there."""
    directory, base = Path(directory), Path(base)
    if base != directory:
        (directory / MARK).write_text(str(base) + '\n')


def recall(directory):
    """Where the backups of the operation kept in `directory` are."""
    directory = Path(directory)
    try:
        text = (directory / MARK).read_text().strip()
    except OSError:
        return directory
    base = Path(text)
    return base if base.is_absolute() and FOLDER in base.parts else directory


def clear(directory):
    """Delete the backups of a closed operation, and its folder on another
    storage once it is empty. The journal and the log of the operation stay."""
    directory = Path(directory)
    base = recall(directory)
    if base != directory and not base.exists():
        return
    for backup in list(base.glob('backup/vzdump-lxc-*')) + list(base.glob('backup-*/vzdump-lxc-*')):
        if backup.is_file() and not backup.is_symlink():
            backup.unlink()
    if base == directory:
        return
    for folder in sorted(base.glob('backup*'), reverse=True):
        _remove_empty(folder)
    # The folder of the operation and the one of the application, never the
    # one shared by every application nor the storage itself.
    for folder in (base, base.parent):
        if folder.parent.name == FOLDER or folder.parent.parent.name == FOLDER:
            _remove_empty(folder)


def _remove_empty(folder):
    try:
        if folder.is_dir() and not folder.is_symlink():
            folder.rmdir()
    except OSError:
        pass


def forget(root, vmid):
    """Before the record of an application is deleted: remove what its
    operations left on another storage."""
    transactions = instances.location(root, vmid).parent / 'transactions'
    if not transactions.is_dir():
        return
    for directory in transactions.iterdir():
        base = recall(directory)
        if base != directory and base.exists() and FOLDER in base.parts:
            shutil.rmtree(base, ignore_errors=True)
            _remove_empty(base.parent)


def application(root, vmid):
    """The containers of the application `vmid` belongs to."""
    record = instances.read(root, vmid)
    primary_id = int((record.get('stack_member') or {}).get('primary_vmid') or vmid)
    primary = record if primary_id == vmid else instances.read(root, primary_id)
    members = [int(member['vmid']) for member in (primary.get('stack') or {}).get('members') or []]
    return primary_id, members or [vmid]


def status(root, vmid):
    """What the menu needs to know before an operation: whether the backup
    fits on the system disk, the storage chosen earlier and the ones that
    have room."""
    primary_id, vmids = application(root, vmid)
    record = instances.read(root, primary_id)
    default = instances.location(root, primary_id).parent
    needed, free = required(vmids), available(default)
    saved = (record.get('deployment') or {}).get(KEY)
    path = storage_path(saved) if saved else None
    saved_free = available(path) if path is not None and path.is_dir() else None
    return {'needed': needed, 'free': free, 'fits': free >= needed, 'saved': saved,
            'saved_fits': saved_free is not None and saved_free >= needed,
            'candidates': [{'storage': item['storage'], 'free': item['free']}
                           for item in file_storages() if item['free'] >= needed]}


def choose(root, vmid, storage):
    """Keep the storage chosen for the backups of an application in the
    record of each of its containers. None forgets it."""
    import oci_carried_record
    if storage is not None and storage_path(storage) is None:
        raise ValueError(f"{translate('The storage does not accept backups:')} {storage}")
    with instances.locked(root):
        _, vmids = application(root, vmid)
        for member in vmids:
            record = instances.read(root, member)
            deployment = record.setdefault('deployment', {})
            if storage is None:
                deployment.pop(KEY, None)
            else:
                deployment[KEY] = storage
            instances.write(instances.location(root, member), record)
            oci_carried_record.carry(root, member, mount_stopped=False)
    return vmids
