"""Read-only identity checks for directory bind mounts; never manage their data."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import stat

from oci_installation_state import parse_config
from oci_ui import translate


def valid_path(value):
    if (not isinstance(value, str) or not value.startswith('/') or value == '/'
            or any(c.isspace() or ord(c) < 32 or c == ',' for c in value)
            or any(p in ('.', '..') for p in value.split('/'))
            or str(PurePosixPath(value)) != value or value.startswith('//')):
        raise ValueError(translate('Invalid absolute mount path'))
    return value


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
    return {'resolved_path': resolved, 'exists': True, 'device': info.st_dev,
            'inode': info.st_ino, 'uid': info.st_uid, 'gid': info.st_gid,
            'mode': stat.S_IMODE(info.st_mode)}


def validate_source(source, allow_missing=False):
    valid_path(source)
    value = snapshot(source, allow_missing)
    protected = ('/etc', '/usr', '/bin', '/sbin', '/lib', '/lib64', '/dev', '/proc', '/sys', '/run')
    protected += tuple(str(Path(p).resolve()) for p in protected)
    resolved = value['resolved_path']
    if resolved == '/' or any(resolved == p or resolved.startswith(p + '/') for p in protected):
        raise ValueError(translate('The shared directory points to a protected host path'))
    return value


def same_source(a, b):
    # Native application init may legitimately change permissions, not identity.
    return all(a.get(k) == b.get(k) for k in ('resolved_path', 'exists', 'device', 'inode'))


def verify_sources(expected):
    for source, previous in expected.items():
        current = validate_source(source, allow_missing=not previous['exists'])
        if not same_source(previous, current):
            raise ValueError(f"{translate('The operation was stopped because a shared directory changed its identity:')} {source}")


def verify_observation(expected, observed):
    actual = observed.get('host_bind_sources', {})
    if actual.keys() != expected.keys() or any(not same_source(value, actual[source])
                                              for source, value in expected.items()):
        raise ValueError(translate('The mount evidence does not match the verified directories'))


def capture_sources(config):
    result = {}
    for key, value in parse_config(config).items():
        if re.fullmatch(r'mp[0-9]+', key):
            source = value.split(',', 1)[0]
            if source.startswith('/'):
                result[source] = snapshot(source)
    return result
