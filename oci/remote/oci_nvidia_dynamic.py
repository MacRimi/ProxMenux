"""Validation for the experimental native-device/dynamic-library NVIDIA profile.

Driver files are runtime evidence, not persistent desired-state dependencies.
This module does not enable transactions before the common installer supports
the same profile.
"""
from pathlib import Path
import hashlib

import oci_nvidia_runtime as nv
from oci_ui import translate


def gpu_identity(inventory):
    identities = []
    for row in inventory['gpus']:
        fields = [part.strip() for part in row.split(',')]
        if len(fields) != 3 or not all(fields):
            raise ValueError(translate('Incomplete NVIDIA identity'))
        identities.append(tuple(fields[:2]))
    if not identities or len(set(identities)) != len(identities):
        raise ValueError(translate('Empty or duplicated NVIDIA identity'))
    return sorted(identities)


def validate(config, previous, current, hook, expected_hook_sha256,
             capabilities='compute,utility,video'):
    if gpu_identity(previous) != gpu_identity(current):
        raise ValueError(translate('The selected GPU changed'))
    if nv.mount_lines(config):
        raise ValueError(translate('The dynamic profile does not support static driver mounts'))
    hook = Path(hook)
    info = hook.stat()
    if (hook.is_symlink() or not hook.is_file() or info.st_uid != 0
            or info.st_mode & 0o022 or not info.st_mode & 0o111
            or hashlib.sha256(hook.read_bytes()).hexdigest() != expected_hook_sha256):
        raise ValueError(translate('Untrusted or modified NVIDIA hook'))
    allowed = {'lxc.hook.mount': str(hook),
               'lxc.environment': {'NVIDIA_VISIBLE_DEVICES=all',
                                   f'NVIDIA_DRIVER_CAPABILITIES={capabilities}'}}
    found_hook, environments = [], []
    for line in config.decode().splitlines():
        if not line.startswith('lxc.') or ': ' not in line:
            continue
        key, value = line.split(': ', 1)
        if key == 'lxc.hook.mount':
            found_hook.append(value)
        elif key == 'lxc.environment':
            environments.append(value)
        elif key.startswith(('lxc.hook.', 'lxc.cgroup', 'lxc.apparmor')):
            raise ValueError(translate('Security directive outside the dynamic profile'))
    if found_hook != [allowed['lxc.hook.mount']] or (
            len(environments) != 2 or set(environments) != allowed['lxc.environment']):
        raise ValueError(translate('The NVIDIA hook or environment differs from the declared one'))
    nv.check_devices(config, current)
    return {'gpu_identity': gpu_identity(current), 'hook_sha256': expected_hook_sha256,
            'driver_capabilities': capabilities, 'inventory': current}
