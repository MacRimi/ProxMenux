#!/usr/bin/env python3
"""Remove only empty, unshifted ext4 format directories on managed mounts."""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess


def mount_path(value):
    if (not isinstance(value, str) or not value.startswith('/') or value == '/'
            or '\x00' in value or '\n' in value
            or not value.strip('/')
            or any(part in ('.', '..') for part in value.split('/'))):
        raise ValueError('Invalid managed volume path')
    return '/' + '/'.join(part for part in value.split('/') if part)


def eligible_paths(deployment, backed_only=True):
    mounts = deployment.get('mounts', [])
    if not isinstance(mounts, list) or any(not isinstance(m, dict) for m in mounts):
        raise ValueError('Invalid managed mount contract')
    paths = [(mount_path(m.get('container_path')), m) for m in mounts]
    if len({path for path, _ in paths}) != len(paths):
        raise ValueError('Duplicate managed volume path')
    selected = []
    for path, mount in paths:
        if (mount.get('type') != 'managed-volume' or mount.get('read_only')
                or (backed_only and not mount.get('backup'))):
            continue
        candidate = path + '/lost+found'
        # A nested mount can replace the directory or something inside it.
        if any(other == candidate or other.startswith(candidate + '/')
               for other, _ in paths):
            continue
        selected.append(path)
    return selected


def format_directory(info):
    return (stat.S_ISDIR(info.st_mode) and info.st_ino == 11
            and info.st_uid == 0 and info.st_gid == 0
            and stat.S_IMODE(info.st_mode) == 0o700)


def remove_empty_at(parent):
    try:
        before = os.stat('lost+found', dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not format_directory(before):
        return False
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    child = os.open('lost+found', flags, dir_fd=parent)
    try:
        opened = os.fstat(child)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            return False
        with os.scandir(child) as entries:
            if next(entries, None) is not None:
                return False
        current = os.stat('lost+found', dir_fd=parent, follow_symlinks=False)
        if ((current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
                or not format_directory(current)):
            return False
        # rmdir cannot delete files, and does not follow a replacement link.
        os.rmdir('lost+found', dir_fd=parent)
        return True
    finally:
        os.close(child)


def remove_empty_format_directories(rootfs, deployment, backed_only=True, target=None):
    paths = eligible_paths(deployment, backed_only)
    if target is not None:
        wanted = mount_path(target)
        paths = [path for path in paths if path == wanted]
    if not paths:
        return 0
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    # A running container is reached through /proc/<pid>/root, a link.
    root = os.open(rootfs, os.O_RDONLY | os.O_DIRECTORY)
    removed = 0
    try:
        for path in paths:
            current = os.dup(root)
            try:
                for part in path.lstrip('/').split('/'):
                    following = os.open(part, flags, dir_fd=current)
                    os.close(current)
                    current = following
                removed += int(remove_empty_at(current))
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise ValueError('Symbolic link or invalid managed volume path') from error
                raise
            finally:
                os.close(current)
    finally:
        os.close(root)
    return removed


def startup_mounts(config, deployment):
    """Use the current PVE mount type/RO flag, gated by the saved contract."""
    declared = {mount_path(m.get('container_path')): m
                for m in deployment.get('mounts', [])}
    mounts = []
    for key, value in config.items():
        if not re.fullmatch(r'mp[0-9]+', key):
            continue
        source, *parts = value.split(',')
        options = dict(part.split('=', 1) for part in parts if '=' in part)
        path = mount_path(options.get('mp'))
        saved = declared.get(path, {})
        managed = (saved.get('type') == 'managed-volume' and not source.startswith('/')
                   and ':' in source)
        mounts.append({'container_path': path,
                       'type': 'managed-volume' if managed else 'host-bind',
                       'backup': bool(saved.get('backup')) and options.get('backup') == '1',
                       'read_only': bool(saved.get('read_only')) or options.get('ro', '0') != '0'})
    return {'mounts': mounts}


def cleanup_startup(root, vmid, rootfs_base=Path('/var/lib/lxc')):
    # Locks are nonblocking. A transaction already prepares its own restore
    # before starting it; the hook must not wait on its parent's registry lock.
    import oci_instances as instances
    from oci_installation_state import parse_config
    lock = os.open(root / '.lock', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = instances.read(root, vmid)
        if record.get('status') != 'installed' or record.get('pending_transaction'):
            return 0
        if not eligible_paths(record['deployment']):
            return 0
        result = subprocess.run(['pct', 'config', str(vmid)], capture_output=True, timeout=3)
        if result.returncode or instances.identity(result.stdout) != record['installation_id']:
            return 0
        mounts = startup_mounts(parse_config(result.stdout), record['deployment'])
        return remove_empty_format_directories(rootfs_base / str(vmid) / 'rootfs', mounts)
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('rootfs', type=Path)
    prepare.add_argument('deployment', type=Path)
    prepare.add_argument('--target')
    startup = sub.add_parser('startup')
    startup.add_argument('vmid', type=int)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            remove_empty_format_directories(args.rootfs, json.loads(args.deployment.read_text()),
                                            backed_only=False, target=args.target)
        elif args.vmid > 0:
            import oci_instances as instances
            cleanup_startup(instances.ROOT, args.vmid)
        else:
            return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Private contracts/configuration must never be printed by a hook.
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
