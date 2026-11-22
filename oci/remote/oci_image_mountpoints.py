#!/usr/bin/env python3

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : jcastro
# GitHub      : github.com/jcastro
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 22/10/2026
# ==========================================================
# Description:
# Preserve original OCI image files outside managed-volume mountpoints
# before attaching persistent disks, so ZFS snapshot backups can mount them.
# Only operate on a stopped container's freshly extracted raw rootfs.
# ==========================================================

"""Keep raw OCI image defaults out of future managed-volume mountpoints.

Call only on a stopped, freshly extracted rootfs, after capturing volume seeds
and before attaching persistent disks. Reused disks are never opened here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

ARCHIVE = '.proxmenux-image-defaults'
MARKER = '.proxmenux-image-defaults-v1'
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def path_parts(value):
    if (not isinstance(value, str) or not value.startswith('/') or value == '/'
            or any(c in value for c in '\0\n\r')
            or any(p in ('.', '..', '') for p in value.split('/')[1:])):
        raise ValueError(f'Unsafe image mountpoint: {value!r}')
    parts = PurePosixPath(value).parts[1:]
    if parts[0] == ARCHIVE:
        raise ValueError('The image-default archive is a reserved path')
    return parts


def mounted_paths():
    def unescape(text):
        return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), text)
    return [Path(unescape(line.split()[4]))
            for line in Path('/proc/self/mountinfo').read_text().splitlines()]


def open_directory(root_fd, parts):
    current = os.dup(root_fd)
    try:
        for component in parts:
            child = os.open(component, FLAGS, dir_fd=current)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def normalize(root, paths, mounts=None):
    root = Path(root)
    if root.is_symlink() or not root.is_absolute() or root.resolve() != root:
        raise ValueError('The raw rootfs must be a real absolute directory')
    paths = sorted(set(paths), key=lambda p: (-len(path_parts(p)), p))
    mounts = mounted_paths() if mounts is None else list(map(Path, mounts))
    root_fd = os.open(root, FLAGS)
    targets, result = [], []
    try:
        root_stat = os.fstat(root_fd)
        # Validate every path before moving any entry. A mount on an ancestor
        # or descendant means this is not exclusively the raw image anymore.
        for value in paths:
            parts = path_parts(value)
            target = root.joinpath(*parts)
            for mount in mounts:
                if mount != root and mount.is_relative_to(root) and (mount == target or target.is_relative_to(mount)
                                      or mount.is_relative_to(target)):
                    raise ValueError(f'An attached filesystem intersects {value}')
            try:
                fd = open_directory(root_fd, parts)
            except FileNotFoundError:
                continue
            except OSError as error:
                raise ValueError(f'Image mountpoint is not a real directory: {value}') from error
            if os.fstat(fd).st_dev != root_stat.st_dev:
                os.close(fd)
                raise ValueError(f'Image mountpoint crosses a filesystem: {value}')
            targets.append((value, fd))
        nonempty = [(p, fd) for p, fd in targets if os.listdir(fd)]
        if not nonempty:
            return []
        existing_archive = False
        try:
            os.stat(ARCHIVE, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            existing_archive = True
        if not existing_archive:
            os.mkdir(ARCHIVE, 0o755, dir_fd=root_fd)
        archive_fd = os.open(ARCHIVE, FLAGS, dir_fd=root_fd)
        try:
            if existing_archive:
                marker = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=archive_fd)
                try:
                    if (not stat.S_ISREG(os.fstat(marker).st_mode)
                            or os.read(marker, 32) != b'proxmenux-image-defaults-v1\n'):
                        raise ValueError('The image-default archive already exists')
                finally:
                    os.close(marker)
            else:
                os.fchown(archive_fd, root_stat.st_uid, root_stat.st_gid)
                marker = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644, dir_fd=archive_fd)
                try:
                    os.fchown(marker, root_stat.st_uid, root_stat.st_gid)
                    os.write(marker, b'proxmenux-image-defaults-v1\n')
                finally:
                    os.close(marker)
            # Validate all destinations before moving entries; never overwrite
            # a prior saved directory (including one shipped by the image).
            for value, _ in nonempty:
                name = hashlib.sha256(value.encode()).hexdigest()
                try:
                    os.stat(name, dir_fd=archive_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise ValueError(f'Image-default destination already exists: {value}')
            for value, fd in nonempty:
                name = hashlib.sha256(value.encode()).hexdigest()
                os.mkdir(name, 0o700, dir_fd=archive_fd)
                saved_fd = os.open(name, FLAGS, dir_fd=archive_fd)
                try:
                    owner = os.fstat(fd)
                    os.fchown(saved_fd, owner.st_uid, owner.st_gid)
                    os.fchmod(saved_fd, stat.S_IMODE(owner.st_mode))
                    for child in os.listdir(fd):
                        os.rename(child, child, src_dir_fd=fd, dst_dir_fd=saved_fd)
                finally:
                    os.close(saved_fd)
                result.append({'target': value, 'saved': f'/{ARCHIVE}/{name}'})
        finally:
            os.close(archive_fd)
        return result
    finally:
        for _, fd in targets:
            os.close(fd)
        os.close(root_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rootfs')
    parser.add_argument('deployment')
    args = parser.parse_args()
    deployment = json.loads(Path(args.deployment).read_text())
    paths = [m['container_path'] for m in deployment.get('mounts', [])
             if m.get('type') == 'managed-volume']
    for item in normalize(Path(args.rootfs), paths):
        print(f"Image defaults preserved: {item['target']} -> {item['saved']}")


if __name__ == '__main__':
    main()
