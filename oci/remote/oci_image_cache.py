#!/usr/bin/env python3
"""Image archives that ProxMenux downloaded to the template storage and that
no installation uses any more are removed after a successful operation."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import time

import oci_instances as instances

# Names given by the OCI installers and by updates; other archives are never touched.
NAME = re.compile(r'(?:proxmenux-update-[a-z0-9]+-[0-9a-f]{64}'
                  r'|(?:image|linuxserver)-[A-Za-z0-9._-]+_[a-z0-9]+_[0-9a-f]{16})\.tar')
IN_PROGRESS = {'installing', 'assembling', 'updating', 'recovering'}
# A recent archive may belong to an installation that has not saved its record yet.
MIN_AGE_SECONDS = 3600


def unused_archives(root=instances.ROOT):
    """Archives no installed guest uses; empty while any operation is pending
    or a record cannot be read."""
    keep, folders = set(), set()
    for path in Path(root).glob('*/oci-compose.json'):
        try:
            record = json.loads(path.read_text())
            vmid = int(record['vmid'])
        except (OSError, ValueError, KeyError, TypeError):
            return []
        exists = instances.guest_exists(vmid)
        if (record.get('pending_transaction') or record.get('pending_stack_transaction')
                or (exists and record.get('status') in IN_PROGRESS)):
            return []
        archive = (record.get('observed') or {}).get('archive_path')
        if not archive:
            continue
        folders.add(Path(archive).parent)
        if exists:
            keep.add(Path(archive))
    now = time.time()
    result = []
    for folder in folders:
        for candidate in folder.glob('*.tar'):
            if candidate in keep or not NAME.fullmatch(candidate.name) or candidate.is_symlink():
                continue
            info = candidate.stat()
            if candidate.is_file() and now - info.st_mtime >= MIN_AGE_SECONDS:
                result.append((candidate, info.st_size))
    return result


def prune(root=instances.ROOT, lock=True):
    """Removes the unused archives and returns them as (path, size). Callers
    that already hold the registry lock pass lock=False."""
    if lock:
        with instances.locked(root):
            return prune(root, lock=False)
    removed = []
    for candidate, size in unused_archives(root):
        try:
            candidate.unlink()
        except OSError:
            continue
        removed.append((candidate, size))
    return removed


def archives_of(vmids, root=instances.ROOT):
    """The downloaded archives the given installations were created from."""
    result = {}
    for vmid in vmids:
        archive = (instances.read(root, vmid).get('observed') or {}).get('archive_path')
        path = Path(archive) if archive else None
        if path and NAME.fullmatch(path.name) and path.is_file() and not path.is_symlink():
            result[path] = path.stat().st_size
    return result


def main(arguments):
    command = arguments[0] if arguments else 'prune'
    if command == 'prune':
        for path, size in prune():
            print(f'removed unused image archive: {path} ({size} bytes)')
        return 0
    if command not in ('list', 'remove') or not all(a.isdigit() for a in arguments[1:]):
        print('usage: oci_image_cache.py [prune | list VMID... | remove VMID...]', file=sys.stderr)
        return 2
    with instances.locked(instances.ROOT):
        archives = archives_of([int(a) for a in arguments[1:]])
        freed = 0
        if command == 'remove':
            for path, size in archives.items():
                path.unlink()
                freed += size
    print(json.dumps({'archives': [{'path': str(p), 'size': s} for p, s in archives.items()],
                      'freed': freed}))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, BlockingIOError) as error:
        print(f'image cache: {error}', file=sys.stderr)
        sys.exit(1)
