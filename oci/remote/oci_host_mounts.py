"""Read-only identity checks for directory bind mounts; never manage their data."""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

from oci_installation_state import parse_config
from oci_ui import translate


def valid_path(value):
    if (not isinstance(value, str) or not value.startswith('/') or value == '/'
            or any(c.isspace() or ord(c) < 32 or c == ',' for c in value)
            or any(p in ('.', '..') for p in value.split('/'))
            or str(PurePosixPath(value)) != value or value.startswith('//')):
        raise ValueError(translate('Invalid absolute mount path'))
    return value


MOUNTINFO = Path('/proc/self/mountinfo')
BY_UUID = Path('/dev/disk/by-uuid')
# Filesystems that number their folders again every time they are mounted.
RENUMBERED = ('vfat', 'exfat', 'msdos')


def _field(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match.group(1), 8)), value)


def _mounted_at(resolved):
    """Type and source of the filesystem a path is on: the mount with the
    longest mount point above it, the last one when several share it."""
    found = None
    try:
        lines = MOUNTINFO.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        before, _, after = line.partition(' - ')
        fields, origin = before.split(), after.split()
        if len(fields) < 5 or len(origin) < 2:
            continue
        point = _field(fields[4])
        if resolved == point or resolved.startswith(point.rstrip('/') + '/'):
            if found is None or len(point) >= len(found[0]):
                found = (point, origin[0], _field(origin[1]))
    return found and found[1:]


def _uuid(device):
    """UUID of the filesystem on a block device, as the host publishes it."""
    try:
        number = os.stat(device).st_rdev
        for link in BY_UUID.iterdir():
            if os.stat(link).st_rdev == number:
                return link.name
    except OSError:
        pass
    try:
        result = subprocess.run(['blkid', '-o', 'value', '-s', 'UUID', device],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def filesystem(resolved):
    """What tells the filesystem of a directory apart across restarts, and its
    type. The device number does not: the host gives it again on every boot,
    and to a disk every time it is connected. A filesystem on a block device
    is told by its UUID; one without, as a ZFS dataset or a network share, by
    what is mounted. The identity is None when the host does not tell."""
    mounted = _mounted_at(resolved)
    if mounted is None:
        return None, None
    kind, origin = mounted
    if origin.startswith('/'):
        try:
            block = stat.S_ISBLK(os.stat(origin).st_mode)
        except OSError:
            block = False
        if block:
            uuid = _uuid(origin)
            return (f'uuid:{uuid}' if uuid else None), kind
    return f'{kind}:{origin}', kind


def snapshot(source, allow_missing=False):
    path = Path(source)
    resolved = str(path.resolve())
    try:
        info = path.stat()
    except FileNotFoundError:
        if not allow_missing or path.is_symlink():
            raise ValueError(f"{translate('The container is not modified because a host directory is not available:')} {source}")
        return {'resolved_path': resolved, 'exists': False}
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(translate('This profile only supports directory bind mounts'))
    identity, kind = filesystem(resolved)
    return {'resolved_path': resolved, 'exists': True, 'device': info.st_dev,
            'inode': info.st_ino, 'uid': info.st_uid, 'gid': info.st_gid,
            'mode': stat.S_IMODE(info.st_mode), 'filesystem': identity, 'fstype': kind}


def validate_source(source, allow_missing=False, declared=False):
    """`declared` is a source the recipe of the application names itself, as a
    host monitor does with /proc and /sys: it is not one the user typed."""
    valid_path(source)
    value = snapshot(source, allow_missing)
    if declared:
        return dict(value, declared=True)
    protected = ('/etc', '/usr', '/bin', '/sbin', '/lib', '/lib64', '/dev', '/proc', '/sys', '/run')
    protected += tuple(str(Path(p).resolve()) for p in protected)
    resolved = value['resolved_path']
    if resolved == '/' or any(resolved == p or resolved.startswith(p + '/') for p in protected):
        raise ValueError(translate('The shared directory points to a protected host path'))
    return value


def same_source(a, b):
    # Native application init may legitimately change permissions, not identity.
    if any(a.get(k) != b.get(k) for k in ('resolved_path', 'exists')):
        return False
    known = bool(a.get('filesystem') and b.get('filesystem'))
    if known and a['filesystem'] != b['filesystem']:
        return False
    if a.get('inode') != b.get('inode') and not (known and a.get('fstype') in RENUMBERED):
        return False
    if known:
        return True
    # A record written before the filesystem was looked at has only the device
    # number, which does not survive a restart: there is nothing to compare.
    if 'filesystem' not in a or 'filesystem' not in b:
        return True
    return a.get('device') == b.get('device')


def verify_sources(expected):
    for source, previous in expected.items():
        current = validate_source(source, allow_missing=not previous['exists'],
                                  declared=previous.get('declared', False))
        if not same_source(previous, current):
            raise ValueError(f"{translate('The operation was stopped because a shared directory changed its identity:')} {source}")


def verify_observation(expected, observed):
    actual = observed.get('host_bind_sources', {})
    if actual.keys() != expected.keys() or any(not same_source(value, actual[source])
                                              for source, value in expected.items()):
        raise ValueError(translate('The mount evidence does not match the verified directories'))


def missing_sources(config):
    """Host directories a container mounts that are not there, as when their
    disk is not connected. Proxmox cannot mount the container without them,
    and leaves it locked when it tries."""
    return [value.split(',', 1)[0] for key, value in parse_config(config).items()
            if re.fullmatch(r'mp[0-9]+', key) and value.startswith('/')
            and not Path(value.split(',', 1)[0]).exists()]


def capture_sources(config):
    result = {}
    for key, value in parse_config(config).items():
        if re.fullmatch(r'mp[0-9]+', key):
            source = value.split(',', 1)[0]
            if source.startswith('/'):
                result[source] = snapshot(source)
    return result
