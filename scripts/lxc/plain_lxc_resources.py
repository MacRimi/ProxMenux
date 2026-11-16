#!/usr/bin/env python3

# ==========================================================
# ProxMenux - Plain LXC resource checks
# ==========================================================
# Author      : Vaso73
# GitHub      : github.com/Vaso73
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 15/11/2026
# ==========================================================
# Description:
# Read existing device nodes, PCI safety metadata and guest assignments.
# Validate selected bind directories without changing their permissions.
# No driver installation, mount, guest command or lifecycle operation.
# ==========================================================
"""Read-only host resource discovery and identities, never driver configuration."""
import os
from pathlib import Path
import re
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plain_lxc_spec import DEVICE_PATH, LxcError, mount_path


def path_identity(path, *, device=False):
    path = Path(path)
    try:
        for part in reversed(path.parents):
            if part.is_symlink():
                raise LxcError('resource_unavailable')
        info = path.lstat()
    except OSError:
        raise LxcError('resource_unavailable') from None
    if not (stat.S_ISCHR(info.st_mode) if device else stat.S_ISDIR(info.st_mode)):
        raise LxcError('resource_unavailable')
    # Filesystem identifiers can exceed JavaScript's exact integer range.
    return {'dev':str(info.st_dev), 'ino':str(info.st_ino), 'rdev':str(info.st_rdev),
            'uid':info.st_uid, 'gid':info.st_gid, 'mode':stat.S_IMODE(info.st_mode)}


def usb_identifiers(path, sysroot=Path('/sys'), identity=None):
    try:
        identity = identity or path_identity(path, device=True)
        number = int(identity['rdev'])
        kernel = (sysroot/'dev/char'/f'{os.major(number)}:{os.minor(number)}').resolve(strict=True)
        usb = next((part for part in (kernel,*kernel.parents) if (part/'idVendor').is_file() and (part/'idProduct').is_file()), None)
        if usb is None or not re.fullmatch(r'[0-9]+-[0-9]+(?:\.[0-9]+)*',usb.name):
            raise LxcError('resource_unavailable')
        vendor, product = ((usb/name).read_text().strip().lower() for name in ('idVendor','idProduct'))
        device_class = (usb/'bDeviceClass').read_text().strip().lower()
        if not re.fullmatch(r'[0-9a-f]{4}',vendor) or not re.fullmatch(r'[0-9a-f]{4}',product) or not re.fullmatch(r'[0-9a-f]{2}',device_class) or device_class == '09':
            raise LxcError('resource_unavailable')
        return {'id':vendor+':'+product,'port':usb.name}
    except (OSError,ValueError,RuntimeError):
        raise LxcError('resource_unavailable') from None


def device_policy(path, identity, sysroot=Path('/sys')):
    """Keep the existing GPU helper's VF/active-PF/VFIO exclusion policy.

    Unlike its broad globs, selection binds one kernel node. Accelerator nodes
    without an unambiguous PCI parent are not advertised as safe passthrough.
    """
    if path.startswith(('/dev/bus/usb/', '/dev/ttyUSB', '/dev/ttyACM')):
        usb_identifiers(path,sysroot,identity)
        return
    try:
        number = int(identity['rdev'])
        kernel = (sysroot/'dev/char'/f'{os.major(number)}:{os.minor(number)}').resolve(strict=True)
        pci = next((part for part in (kernel,*kernel.parents) if re.fullmatch(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]', part.name)), None)
        if pci is None or (pci/'physfn').is_symlink() or (pci/'physfn').exists():
            raise LxcError('resource_unavailable')
        count = (pci/'sriov_numvfs').read_text().strip() if (pci/'sriov_numvfs').exists() else '0'
        if count != '0' or (pci/'driver').resolve(strict=True).name == 'vfio-pci':
            raise LxcError('resource_unavailable')
    except (OSError, ValueError, RuntimeError):
        raise LxcError('resource_unavailable') from None


def device_assignments(paths, vmid, directory=Path('/etc/pve/lxc'),
                       qemu_directory=Path('/etc/pve/qemu-server'), sysroot=Path('/sys')):
    if not paths:
        return {}
    if not directory.is_dir():
        raise LxcError('resource_unavailable')
    assigned = {path:[] for path in paths}
    try:
        for config in directory.glob('*.conf'):
            if not config.stem.isdecimal() or int(config.stem) == vmid:
                continue
            active = True
            for line in config.read_text().splitlines():
                if line.startswith('['):
                    active = line.strip() == '[PENDING]'
                    continue
                if not active or not re.match(r'^(?:(?:dev|mp)[0-9]+|lxc\.mount\.entry):\s', line):
                    continue
                raw = line.split(':',1)[1].strip()
                explicit = re.search(r'(?:^|,)path=([^,]+)',raw)
                source = explicit[1] if explicit else raw.split(',',1)[0].split()[0]
                for path in paths:
                    if source == path or ((source == '/dev' or source.startswith('/dev/')) and path.startswith(source+'/')):
                        if int(config.stem) not in assigned[path]: assigned[path].append(int(config.stem))
        usb_paths = [path for path in paths if path.startswith(('/dev/bus/usb/', '/dev/ttyUSB', '/dev/ttyACM'))]
        if usb_paths:
            if not qemu_directory.is_dir():
                raise LxcError('resource_unavailable')
            identifiers = {}
            for config in qemu_directory.glob('*.conf'):
                active = True
                for line in config.read_text().splitlines():
                    if line.startswith('['):
                        active = line.strip() == '[PENDING]'
                        continue
                    if not active or not re.match(r'^usb[0-9]+:\s',line):
                        continue
                    raw=line.split(':',1)[1].strip()
                    options={}
                    for part in raw.split(','):
                        key,value=part.split('=',1) if '=' in part else ('host',part)
                        if key in options or key not in ('host','mapping','usb3'):
                            raise LxcError('resource_unavailable')
                        options[key]=value
                    if options.get('host','').lower() == 'spice':
                        continue
                    # Cluster USB mappings require a separate native resolver;
                    # never assume they are empty or silently steal the device.
                    if 'mapping' in options or not options.get('host'):
                        raise LxcError('resource_unavailable')
                    host=options['host'].lower()
                    ids=re.fullmatch(r'(?:0x)?([0-9a-f]{4}):(?:0x)?([0-9a-f]{4})',host)
                    if ids: host=ids[1]+':'+ids[2]
                    elif re.fullmatch(r'[0-9]+-[0-9]+(?:\.[0-9]+)*',host):
                        host=re.sub(r'[0-9]+',lambda match:str(int(match[0])),host)
                    else: raise LxcError('resource_unavailable')
                    for path in usb_paths:
                        if path not in identifiers: identifiers[path]=usb_identifiers(path,sysroot)
                        if host in identifiers[path].values():
                            raise LxcError('resource_in_use','devices.path')
    except (OSError, UnicodeError, IndexError):
        raise LxcError('resource_unavailable') from None
    # Sharing a GPU is intentional, as in add_gpu_lxc.sh. USB/serial/TPU/NPU
    # ownership must not silently be duplicated in another CT's configuration.
    for path, owners in assigned.items():
        gpu = path.startswith(('/dev/dri/', '/dev/nvidia'))
        if owners and not gpu:
            raise LxcError('resource_in_use', 'devices.path')
    return assigned


def discover_devices():
    result = {}
    patterns = (('GPU','/dev/dri/renderD*'), ('GPU','/dev/dri/card[0-9]*'),
                ('GPU','/dev/nvidia*'), ('TPU','/dev/apex_[0-9]*'),
                ('NPU','/dev/accel/accel[0-9]*'), ('USB','/dev/bus/usb/*/*'),
                ('USB','/dev/ttyUSB[0-9]*'), ('USB','/dev/ttyACM[0-9]*'))
    for kind, pattern in patterns:
        for path in Path('/').glob(pattern.removeprefix('/')):
            name = str(path)
            if not re.fullmatch(DEVICE_PATH, name):
                continue
            try:
                identity = path_identity(name, device=True)
                device_policy(name, identity)
                label=kind
                if name.startswith('/dev/bus/usb/'):
                    usb=usb_identifiers(name,identity=identity)
                    if usb['id'] in ('18d1:9302','1a6e:089a'):
                        label='TPU / Coral USB'
            except LxcError:
                continue
            result[name] = {'path':name, 'kind':label, 'identity':identity}
            if len(result) >= 512:
                return result
    return result


def bind_identity(source):
    return path_identity(mount_path(source, 'mounts.source', host=True))


def checked_identity(identity):
    if type(identity) is not dict or set(identity) != {'dev','ino','rdev','uid','gid','mode'}:
        raise LxcError('pve_output_invalid')
    if any(type(identity[key]) is not str or not re.fullmatch(r'[0-9]{1,20}',identity[key]) for key in ('dev','ino','rdev')):
        raise LxcError('pve_output_invalid')
    if any(type(identity[key]) is not int or not 0 <= identity[key] <= 4294967295 for key in ('uid','gid')):
        raise LxcError('pve_output_invalid')
    if type(identity['mode']) is not int or not 0 <= identity['mode'] <= 0o7777:
        raise LxcError('pve_output_invalid')
    return identity


if __name__ == '__main__':
    try:
        if len(sys.argv) != 4 or sys.argv[1] != '--check-device' or not re.fullmatch(DEVICE_PATH, sys.argv[2]) or not re.fullmatch(r'[1-9][0-9]{2,8}',sys.argv[3]):
            raise LxcError('invalid_request')
        path = sys.argv[2]
        device_policy(path, path_identity(path, device=True))
        device_assignments([path], int(sys.argv[3]))
    except LxcError:
        sys.exit(1)
