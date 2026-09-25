#!/usr/bin/env python3
"""Keeping the backup an OCI update takes, in a Proxmox VE backup storage.

Every update already stops the container and takes a verified vzdump backup,
which the rollback uses and which is deleted once the new image works. When
the backup is to be kept, that same archive is moved into the dump directory
of the chosen storage instead of being deleted: one backup, not two.

A storage without a directory of its own (Proxmox Backup Server) cannot
receive a file, so a backup is written to it with vzdump before the update.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

from oci_ui import translate

STORAGE_RE = re.compile(r'[A-Za-z0-9._-]{1,64}')


def _storage(storage):
    if not STORAGE_RE.fullmatch(storage or ''):
        raise ValueError(translate('Invalid storage name'))
    result = subprocess.run(['pvesh', 'get', f'/storage/{storage}', '--output-format', 'json'],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ValueError(f"{translate('The backup storage does not exist:')} {storage}")
    info = json.loads(result.stdout)
    if 'backup' not in str(info.get('content', '')).split(','):
        raise ValueError(f"{translate('The storage does not accept backups:')} {storage}")
    return info


def dump_dir(storage):
    """The directory vzdump writes to on a file storage, or None."""
    info = _storage(storage)
    path = info.get('path')
    return Path(path) / 'dump' if path else None


def validate(storage):
    _storage(storage)


def before_update(vmid, storage):
    """A storage that cannot receive the file gets its own backup first."""
    if dump_dir(storage) is not None:
        return None
    subprocess.run(['vzdump', str(vmid), '--storage', storage, '--mode', 'snapshot',
                    '--compress', 'zstd', '--notes-template', 'ProxMenux OCI: before the image update'],
                   check=True)
    return storage


def keep(archive, storage):
    """Move the update's own backup into the storage; returns where it went,
    or None when the storage received its backup before the update."""
    directory = dump_dir(storage)
    if directory is None:
        return None
    archive = Path(archive)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / archive.name
    shutil.move(str(archive), str(target))
    target.chmod(0o644)
    stem = archive.name.split('.tar')[0]
    log = archive.with_name(stem + '.log')
    if log.is_file():
        shutil.move(str(log), str(directory / log.name))
    (directory / (archive.name + '.notes')).write_text('ProxMenux OCI: before the image update\n')
    return str(target)
