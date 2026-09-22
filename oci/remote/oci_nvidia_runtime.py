"""Read-only NVIDIA Toolkit inventory and strict native runtime validation."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess

from oci_gpu_devices import actual_devices
from oci_ui import translate

KEY = '_nvidia_runtime'
QUERY = '--query-gpu=uuid,pci.bus_id,driver_version'


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{args[0]} {translate('could not validate NVIDIA; exit code')} {result.returncode}")
    return result.stdout


def enabled(deployment):
    devices = [d for d in deployment.get('devices', []) if d.get('kind') == 'nvidia-runtime']
    if len(devices) > 1 or any(d.get('device_selection', 'all-requested-by-compose') != 'all-requested-by-compose' for d in devices):
        raise ValueError(translate('NVIDIA selection not supported by this profile'))
    return bool(devices)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def snapshot():
    gpus = sorted(line.strip() for line in command('nvidia-smi', QUERY, '--format=csv,noheader').splitlines() if line.strip())
    if not gpus:
        raise ValueError(translate('No working NVIDIA GPU was found'))
    version = command('nvidia-container-cli', '--version')
    paths = command('nvidia-container-cli', 'list', '--device', 'all', '--libraries', '--binaries', '--firmwares', '--ipcs')
    devices, files, links = {}, {}, {}
    for name in sorted(set(paths.splitlines())):
        if not name.startswith('/') or str(PurePosixPath(name)) != name or any(c.isspace() or c == ',' for c in name):
            raise ValueError(translate('Invalid path in the NVIDIA inventory'))
        path = Path(name)
        info = path.stat()
        basic = {'source': str(path.resolve()), 'uid': info.st_uid,
                 'gid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode)}
        if stat.S_ISCHR(info.st_mode):
            if not name.startswith('/dev/nvidia'):
                raise ValueError(translate('NVIDIA device outside the expected native profile'))
            devices[name] = dict(basic, major=os.major(info.st_rdev), minor=os.minor(info.st_rdev))
        elif stat.S_ISREG(info.st_mode):
            files[name] = dict(basic, size=info.st_size, sha256=digest(path))
            if name.startswith('/usr/lib/'):
                for link in path.parent.iterdir():
                    if link.is_symlink() and str(link.resolve()) == basic['source']:
                        links[str(link)] = os.readlink(link)
        # The common installer intentionally does not publish IPC sockets.
    if not devices or not files:
        raise ValueError(translate('Incomplete NVIDIA inventory'))
    versions = [l for l in version.splitlines() if l.startswith(('cli-version:', 'lib-version:'))]
    if len(versions) != 2:
        raise ValueError(translate('The NVIDIA Container Toolkit version cannot be identified'))
    return {'gpus': gpus, 'toolkit_version': versions,
            'devices': devices, 'files': files, 'links': links}


def verify(value):
    if snapshot() != value:
        raise ValueError(translate('The NVIDIA driver or inventory changed; the operation was stopped'))


def refresh_plan(config, previous, current=None):
    """Resolve current host components without treating a driver version as intent.

    This only prepares a plan; applying it requires a stopped-CT transaction and
    preparing file destinations/library links before the next native start.
    """
    check_devices(config, previous)
    check_mounts(config, previous)
    current = snapshot() if current is None else current
    def identities(value):
        result = []
        for row in value['gpus']:
            fields = [field.strip() for field in row.split(',')]
            if len(fields) != 3 or not all(fields):
                raise ValueError(translate('Incomplete NVIDIA identity'))
            result.append(tuple(fields[:2]))
        return sorted(result)
    if identities(previous) != identities(current):
        raise ValueError(translate('The physical NVIDIA selection changed'))
    # Remove only entries already validated against our recorded inventory.
    kept = []
    for line in config.decode().splitlines():
        if line.startswith('lxc.mount.entry: '):
            continue
        if line.startswith('dev') and ': ' in line:
            key, properties = line.split(': ', 1)
            if key[3:].isdigit():
                fields = dict(part.split('=', 1) for part in properties.split(','))
                if fields.get('path') in previous['devices']:
                    continue
        kept.append(line)
    occupied = {int(line.split(':', 1)[0][3:]) for line in kept
                if line.startswith('dev') and line.split(':', 1)[0][3:].isdigit()}
    for path, info in sorted(current['devices'].items()):
        slot = next(i for i in range(256) if i not in occupied)
        occupied.add(slot)
        kept.append(f'dev{slot}: path={path},mode={info["mode"]:04o},gid={info["gid"]},deny-write=0')
    for path, info in sorted(current['files'].items()):
        kept.append(f'lxc.mount.entry: {info["source"]} {path.lstrip("/")} none ro,bind,create=file 0 0')
    candidate = ('\n'.join(kept) + '\n').encode()
    check_devices(candidate, current)
    check_mounts(candidate, current)
    return {'config': candidate, 'inventory': current,
            'links': dict(current['links']), 'changed': previous != current}


def mount_lines(config):
    return [line.split(': ', 1)[1] for line in config.decode().splitlines() if line.startswith('lxc.mount.entry: ')]


def check_mounts(config, value, complete=True):
    remaining = dict(value['files'])
    seen = set()
    for line in mount_lines(config):
        parts = line.split()
        if (len(parts) != 6 or parts[2] != 'none' or set(parts[3].split(',')) != {'ro', 'bind', 'create=file'}
                or parts[4:] != ['0', '0'] or line in seen):
            raise ValueError(translate('LXC entry outside the read-only NVIDIA profile'))
        seen.add(line)
        match = next((name for name, file in remaining.items()
                      if parts[0] == file['source'] and parts[1] in {name.lstrip('/'), file['source'].lstrip('/')}), None)
        if match is None:
            raise ValueError(translate('NVIDIA mount with an unauthorized source or target'))
        del remaining[match]
    if complete and remaining:
        raise ValueError(translate('NVIDIA runtime libraries or components are missing'))


def check_devices(config, value):
    actual = actual_devices(config)
    for path, info in value['devices'].items():
        fields = actual.get(path, {})
        if (fields.get('path') != path or set(fields) - {'path', 'mode', 'gid', 'uid', 'deny-write'}
                or int(fields.get('mode', '0'), 8) != info['mode']
                or int(fields.get('gid', 0)) != info['gid'] or int(fields.get('uid', 0)) != 0
                or fields.get('deny-write', '0') != '0'):
            raise ValueError(translate('NVIDIA permissions or device nodes differ from the official inventory'))


def validate_runtime(vmid, value):
    rows = command('pct', 'exec', str(vmid), '--', 'nvidia-smi', QUERY, '--format=csv,noheader')
    if sorted(line.strip() for line in rows.splitlines() if line.strip()) != value['gpus']:
        raise ValueError(translate('NVIDIA inside the container does not match the host driver or GPU'))
    if value['links']:
        arguments = [part for pair in sorted(value['links'].items()) for part in pair]
        command('pct', 'exec', str(vmid), '--', 'sh', '-c',
                'while [ "$#" -gt 0 ]; do [ "$(readlink -- "$1")" = "$2" ] || exit 1; shift 2; done',
                'check-nvidia-links', *arguments)
