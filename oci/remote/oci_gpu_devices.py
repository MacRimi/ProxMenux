"""Native Intel/AMD device preservation. NVIDIA library mounts need a separate profile."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

from oci_installation_state import parse_config
from oci_ui import translate


def gpu_path(path):
    return isinstance(path, str) and (re.fullmatch(r'/dev/dri/(renderD|card)[0-9]+', path) is not None or path == '/dev/kfd')


def peripheral_path(path):
    """Coral, NPU (/dev/accel), USB and serial nodes, identified by their sysfs path."""
    return isinstance(path, str) and re.fullmatch(
        r'/dev/(apex_[0-9]+|accel/accel[0-9]+|ttyUSB[0-9]+|ttyACM[0-9]+|bus/usb/[0-9]{3}/[0-9]{3})', path) is not None


def system_path(path):
    """Fixed nodes the kernel always presents the same way. They carry no
    identity beyond their device numbers, so there is no sysfs to interrogate:
    the numbers and the permissions are the whole record."""
    return isinstance(path, str) and re.fullmatch(
        r'/dev/(kvm|fuse|net/tun|video[0-9]+|sg[0-9]+)', path) is not None


def block_path(path):
    return isinstance(path, str) and re.fullmatch(r'/dev/sr[0-9]+', path) is not None


def known_path(path):
    return gpu_path(path) or peripheral_path(path) or system_path(path) or block_path(path)


def snapshot(path):
    if not known_path(path):
        raise ValueError(translate('Device node outside the supported profiles'))
    info = Path(path).stat()
    if block_path(path):
        if not stat.S_ISBLK(info.st_mode):
            raise ValueError(translate('The selected device is not a block device'))
    elif not stat.S_ISCHR(info.st_mode):
        raise ValueError(translate('The selected device is not a character device'))
    value = {'path': str(Path(path).resolve()), 'major': os.major(info.st_rdev),
             'minor': os.minor(info.st_rdev), 'uid': info.st_uid, 'gid': info.st_gid,
             'mode': stat.S_IMODE(info.st_mode)}
    if peripheral_path(path):
        sysfs = Path('/sys/dev/char') / f'{value["major"]}:{value["minor"]}'
        value['sysfs_path'] = str(sysfs.resolve(strict=True))
        if '/bus/usb/' in path:
            for name in ('idVendor', 'idProduct', 'serial'):
                field = sysfs / name
                if field.is_file():
                    value[name] = field.read_text().strip()
    elif gpu_path(path) and path != '/dev/kfd':
        sysfs = Path('/sys/class/drm') / Path(path).name / 'device'
        value.update(vendor=(sysfs / 'vendor').read_text().strip(), pci_path=str(sysfs.resolve()))
        if value['vendor'] not in ('0x1002', '0x8086'):
            raise ValueError(translate('The DRM node is not an Intel or AMD GPU; NVIDIA requires its library profile'))
    return value


def planned(deployment):
    result = {}
    for device in deployment.get('devices', []):
        path = device.get('host_path')
        kind = device.get('kind', 'character-device')
        if kind == 'block-device':
            allowed = block_path(path)
        elif kind == 'character-device':
            allowed = gpu_path(path) or peripheral_path(path) or system_path(path)
        else:
            allowed = False
        if not allowed:
            raise ValueError(translate('Device outside the supported profiles; NVIDIA and device trees require another profile'))
        if device.get('container_path') != path or path in result:
            raise ValueError(translate('The device must keep its native path without duplicates'))
        value = snapshot(path)
        vendors = device.get('drm_vendor_ids')
        if vendors and value.get('vendor') not in vendors:
            raise ValueError(translate('The GPU vendor differs from the requested profile'))
        mode = device.get('mode', '0660')
        if mode != 'preserve-host' and (not isinstance(mode, str) or not re.fullmatch(r'0?[0-7]{3}', mode)):
            raise ValueError(translate('Invalid device mode'))
        if device.get('gid_strategy') not in ('none', 'host-device-gid'):
            raise ValueError(translate('Unsupported device GID strategy'))
        if 'container_gid' in device:
            container_gid(device, value)
        result[path] = value
    return result


def container_gid(device, host_value):
    """The GID assigned to the device node in the LXC's user namespace.

    A recorded container GID is distinct from the host device's GID. Proxmox
    maps the configured LXC GID through the container's id map when it creates
    its passthrough node; the numeric host GID is not automatically translated.
    """
    if 'container_gid' in device:
        gid = device['container_gid']
        if isinstance(gid, bool) or not isinstance(gid, int) or not 0 <= gid < 4294967295:
            raise ValueError(translate('Invalid container device GID'))
        return gid
    return host_value['gid'] if device['gid_strategy'] == 'host-device-gid' else 0


def _permission_fields(fields):
    return (fields.get('path'), int(fields.get('mode', '0660'), 8),
            int(fields.get('uid', 0)), int(fields.get('gid', 0)),
            fields.get('deny-write', '0'))


def preserve_recorded_container_gids(record, candidate, config):
    """Carry forward only device GIDs already captured in the saved config.

    This is not a host-to-container GID translation. The saved config is the
    baseline for the GID Proxmox previously assigned inside the LXC. Any
    unrecorded change is rejected, and the host device is still verified
    independently by ``verify_baseline``.
    """
    saved_config = record.get('observed', {}).get('config')
    if not isinstance(saved_config, str) or not saved_config:
        return
    saved = actual_devices(saved_config.encode())
    current = actual_devices(config)
    if set(saved) != set(current):
        return  # check() below reports the device set mismatch.
    if any(_permission_fields(saved[path]) != _permission_fields(current[path]) for path in saved):
        raise ValueError(translate('The container device settings changed since the last recorded operation'))

    original_devices = record.get('deployment', {}).get('devices', [])
    old_snapshots = planned(record.get('deployment', {}))
    for device in original_devices:
        path = device.get('host_path')
        if path not in saved or path not in old_snapshots:
            continue
        observed_gid = int(saved[path].get('gid', 0))
        expected_gid = container_gid(device, old_snapshots[path])
        if observed_gid != expected_gid and 'container_gid' in device:
            raise ValueError(translate('The recorded container device GID does not match its configuration'))
        if observed_gid != expected_gid:
            device['container_gid'] = observed_gid

        for desired in candidate.get('deployment', {}).get('devices', []):
            if (desired.get('host_path') == path
                    and desired.get('gid_strategy') == device.get('gid_strategy')
                    and 'container_gid' not in desired):
                desired['container_gid'] = observed_gid


def verify(expected):
    for path, value in expected.items():
        if snapshot(path) != value:
            raise ValueError(translate('The GPU identity or permissions changed; the container is not modified'))


def device_fields(value):
    """The options of a devN line. Proxmox writes its path either as `path=`
    or, when the device was added from its own interface, as the first value
    without a name: `dev0: /dev/dri/renderD128,gid=993`."""
    fields = {}
    for index, part in enumerate(value.split(',')):
        if '=' in part:
            key, item = part.split('=', 1)
            fields[key] = item
        elif index == 0 and part:
            fields['path'] = part
        else:
            raise ValueError(translate('Incomplete device configuration'))
    return fields


def actual_devices(config):
    result = {}
    for key, value in parse_config(config).items():
        if re.fullmatch(r'dev[0-9]+', key):
            fields = device_fields(value)
            path = fields.get('path')
            if path in result:
                raise ValueError(translate('Duplicated GPU device in the container'))
            result[path] = fields
    return result


def check(config, deployment):
    expected = planned(deployment)
    actual = actual_devices(config)
    if actual.keys() != expected.keys():
        raise ValueError(translate('The container devices do not match the saved record'))
    for device in deployment.get('devices', []):
        path = device['host_path']
        fields = actual[path]
        value = expected[path]
        requested_mode = device.get('mode', '0660')
        mode = value['mode'] if requested_mode == 'preserve-host' else int(requested_mode, 8)
        gid = container_gid(device, value)
        if (set(fields) - {'path', 'mode', 'gid', 'uid', 'deny-write'}
                or int(fields.get('mode', '0660'), 8) != mode
                or int(fields.get('gid', 0)) != gid
                or int(fields.get('uid', 0)) != int(device.get('uid', 0))
                or fields.get('deny-write', '0') != ('1' if device.get('deny_write') else '0')):
            raise ValueError(translate('The native GPU permissions were not kept'))
    return expected


def verify_observation(expected, observed):
    if observed.get('gpu_devices', {}) != expected:
        raise ValueError(translate('The GPU evidence does not match the verified devices'))
    verify(expected)


def capture(config):
    result = {}
    for path in actual_devices(config):
        if not known_path(path):
            continue
        if gpu_path(path) and path != '/dev/kfd':
            vendor = (Path('/sys/class/drm') / Path(path).name / 'device/vendor').read_text().strip()
            if vendor not in ('0x1002', '0x8086'):
                continue
        result[path] = snapshot(path)
    return result
