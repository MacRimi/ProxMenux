#!/usr/bin/env python3
"""Image archives that ProxMenux downloaded to the template storage and that
no installation uses any more are removed after a successful operation. The
newest archive of an application that is no longer installed is kept, so it can
be installed again when the registry cannot be reached."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time

import oci_instances as instances
from oci_installation_state import image_from_archive
from oci_ui import translate

# Names given by the OCI installers and by updates; other archives are never touched.
NAME = re.compile(r'(?:proxmenux-update-[a-z0-9]+-[0-9a-f]{64}'
                  r'|(?:image|linuxserver)-[A-Za-z0-9._-]+_[a-z0-9]+_[0-9a-f]{16})\.tar')
# The archive an installation downloads: <application>_<architecture>_<digest>.tar
APP_ARCHIVE = re.compile(r'((?:image|linuxserver)-[A-Za-z0-9._-]+_[a-z0-9]+)_([0-9a-f]{16})\.tar')
UPDATE_ARCHIVE = re.compile(r'proxmenux-update-([a-z0-9]+)-([0-9a-f]{64})\.tar')
IN_PROGRESS = {'installing', 'assembling', 'updating', 'recovering'}
# A recent archive may belong to an installation that has not saved its record yet.
MIN_AGE_SECONDS = 3600


def safe_app(app_id):
    """The application part of an archive name, as the installer writes it."""
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', f'{app_id}\n')
    return name[:-1] if name.endswith('_') else name


def unused_archives(root=instances.ROOT):
    """Archives no installed guest uses, except the newest one of each
    application that is no longer installed; empty while any operation is
    pending or a record cannot be read."""
    keep, folders, installed = set(), set(), set()
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
        observed = record.get('observed') or {}
        archive = observed.get('archive_path')
        if not archive:
            continue
        folders.add(Path(archive).parent)
        if exists:
            keep.add(Path(archive))
            architecture = (observed.get('image') or {}).get('architecture')
            app_id = (record.get('template') or {}).get('id')
            if architecture and app_id:
                installed.add((Path(archive).parent, f'{safe_app(app_id)}_{architecture}'))
    now = time.time()
    result, newest = [], {}
    for folder in folders:
        for candidate in folder.glob('*.tar'):
            if candidate in keep or not NAME.fullmatch(candidate.name) or candidate.is_symlink():
                continue
            info = candidate.stat()
            if not candidate.is_file() or now - info.st_mtime < MIN_AGE_SECONDS:
                continue
            result.append((candidate, info.st_size))
            match = APP_ARCHIVE.fullmatch(candidate.name)
            group = (folder, match.group(1)) if match else None
            if group and group not in installed and (
                    group not in newest or info.st_mtime > newest[group].stat().st_mtime):
                newest[group] = candidate
    kept = set(newest.values())
    return [(candidate, size) for candidate, size in result if candidate not in kept]


def keep_for_reinstall(record):
    """The archive an updated installation uses carries the update's name: it
    is linked under the application's name, so the archive is kept when the
    installation is removed and found when the application is installed again."""
    archive = (record.get('observed') or {}).get('archive_path')
    match = UPDATE_ARCHIVE.fullmatch(Path(archive).name) if archive else None
    app_id = (record.get('template') or {}).get('id')
    if not match or not app_id:
        return None
    path = Path(archive)
    target = path.with_name(f'{safe_app(app_id)}_{match.group(1)}_{match.group(2)[:16]}.tar')
    if not APP_ARCHIVE.fullmatch(target.name) or path.is_symlink() or not path.is_file() or target.exists():
        return None
    try:
        os.link(path, target)
    except OSError:
        return None
    return target


def saved_archive(folder, app_id, architecture, digest=None):
    """The newest archive kept for this application, for an installation that
    cannot reach the registry. A reference pinned to a digest accepts only that
    image. The registry digest of a multi-platform image is not stored in the
    archive: the image's own manifest digest stands for it then."""
    group = f'{safe_app(app_id)}_{architecture}'
    found = []
    for candidate in Path(folder).glob(f'{group}_*.tar'):
        match = APP_ARCHIVE.fullmatch(candidate.name)
        if (not match or match.group(1) != group or candidate.is_symlink() or not candidate.is_file()
                or (digest and not digest.startswith(f'sha256:{match.group(2)}'))):
            continue
        found.append(candidate)
    if not found:
        return None
    path = max(found, key=lambda p: p.stat().st_mtime)
    image = image_from_archive(path)
    if image['architecture'] != architecture:
        return None
    return {'archive': str(path), 'digest': digest or image['manifest_digest'],
            'created': image.get('created') or ''}


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
    if command == 'saved' and len(arguments) in (4, 5):
        saved = saved_archive(*arguments[1:])
        if not saved:
            return 1
        print(json.dumps(saved))
        return 0
    if command == 'prune':
        for path, size in prune():
            print(translate('removed unused image archive: {path} ({size} bytes)').format(path=path, size=size))
        return 0
    if command not in ('list', 'remove') or not all(a.isdigit() for a in arguments[1:]):
        print(translate('Usage:') + ' oci_image_cache.py [prune | list VMID... | remove VMID...]', file=sys.stderr)
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
        print(f"{translate('Image cache')}: {error}", file=sys.stderr)
        sys.exit(1)
