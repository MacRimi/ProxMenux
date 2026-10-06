#!/usr/bin/env python3
"""Change what runs the recognition of an installed Immich: the CPU or a GPU.

The machine learning container takes the image built for the new choice and
the devices that choice needs. Its model cache, the library, the database and
the other containers keep their data. The change is applied with an update of
the application, so a failure restores the previous containers, and with them
the previous choice.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

import oci_instances as instances
import oci_stack_modify
import oci_stack_native
from oci_ui import msg_error, msg_info, msg_ok, msg_warn, translate

ADAPTER = 'install_immich_stack.sh'
ENGINE = Path(__file__).resolve().parent
PROFILES = ('cpu', 'openvino', 'cuda', 'rocm')
RENDER = re.compile(r'/dev/dri/renderD[0-9]+')
# What a previous choice left in the container: its devices and the settings
# of its runtime.
GPU_DEVICE = re.compile(r'/dev/dri/renderD[0-9]+|/dev/kfd|/dev/nvidia\S*')
GPU_LINE = re.compile(r'lxc\.environment\.runtime: HSA_[A-Z_]+=|lxc\.environment: NVIDIA_[A-Z_]+=|'
                      r'lxc\.hook\.mount: /usr/local/lib/proxmenux/oci/nvidia-mount-')
ROCM_ROOTFS_GB = 40
NVIDIA_CAPABILITIES = 'compute,utility'
GPU_VARIABLES = ('NVIDIA_DRIVER_CAPABILITIES', 'HSA_OVERRIDE_GFX_VERSION', 'HSA_USE_SVM')


def run(*command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ['']
        raise RuntimeError(f"{' '.join(command[:3])}: {detail[0]}")
    return result.stdout


def members(root, primary_id):
    """The record of each container of the application, by its role."""
    primary = instances.read(root, primary_id)
    found = {}
    for member in (primary.get('stack') or {}).get('members', []):
        record = instances.read(root, member['vmid'])
        profile = record['deployment'].get('replay_profile') or {}
        if profile.get('adapter') != ADAPTER:
            raise ValueError(translate('This application is not an Immich installed by ProxMenux'))
        found[profile.get('role')] = record
    if set(found) != {'server', 'database', 'valkey', 'machine-learning'} or found['server']['vmid'] != primary_id:
        raise ValueError(translate('This application is not an Immich installed by ProxMenux'))
    return primary, found


def current(record):
    return (record['deployment'].get('machine_learning') or {}).get('acceleration', 'cpu')


def conf(vmid):
    return Path(f'/etc/pve/lxc/{int(vmid)}.conf')


def settings(vmid):
    """The current configuration of the container, one value per key."""
    lines = [line.partition(': ') for line in run('pct', 'config', str(vmid)).splitlines()]
    return {key: value for key, separator, value in lines if separator}


def strip_gpu(vmid):
    """Take the devices and runtime settings of the previous choice away."""
    for key, value in oci_stack_modify.entries(vmid, 'dev').items():
        if GPU_DEVICE.fullmatch(oci_stack_modify.device_path(value)):
            run('pct', 'set', str(vmid), '--delete', key)
    text = conf(vmid).read_text()
    head, separator, snapshots = text.partition('\n[')
    rebuilt = '\n'.join(line for line in head.split('\n') if not GPU_LINE.match(line)) + separator + snapshots
    if rebuilt != text:
        conf(vmid).write_text(rebuilt)


def append_lines(vmid, lines):
    """Add lines to the current configuration, before any snapshot section."""
    head, separator, snapshots = conf(vmid).read_text().partition('\n[')
    conf(vmid).write_text(head.rstrip('\n') + '\n' + '\n'.join(lines) + '\n' + separator + snapshots)


def add_device(vmid, path):
    info = os.stat(path)
    run('pct', 'set', str(vmid), '--' + oci_stack_modify.free_key(vmid, 'dev'),
        f'path={path},gid={info.st_gid},mode=0660')


def configure(vmid, acceleration, render_device, gfx_override):
    """Give the stopped container what the new choice needs."""
    strip_gpu(vmid)
    if acceleration in ('openvino', 'rocm'):
        add_device(vmid, render_device)
    if acceleration == 'rocm':
        add_device(vmid, '/dev/kfd')
        if gfx_override:
            append_lines(vmid, [f'lxc.environment.runtime: HSA_OVERRIDE_GFX_VERSION={gfx_override}',
                                'lxc.environment.runtime: HSA_USE_SVM=0'])
        size = re.search(r'size=([0-9]+)G', settings(vmid).get('rootfs', ''))
        if size and int(size[1]) < ROCM_ROOTFS_GB:
            # The ROCm image is several times larger than the others.
            run('pct', 'resize', str(vmid), 'rootfs', f'{ROCM_ROOTFS_GB}G')
    if acceleration == 'cuda':
        # The same NVIDIA setup the installation uses.
        run('bash', '-c', f'set -e; SCRIPT_DIR="{ENGINE}"; source "$SCRIPT_DIR/oci_ui.sh"; '
            'die() { msg_error "$*"; exit 1; }; oci_log() { :; }; '
            'source "$SCRIPT_DIR/oci_nvidia_setup.sh"; source "$SCRIPT_DIR/oci_immich_ml.sh"; '
            f'configure_immich_nvidia {int(vmid)} {NVIDIA_CAPABILITIES}')
    run('pct', 'set', str(vmid), '--memory', str(memory(acceleration)))
    values = settings(vmid)
    limited = 'cpulimit' in values and 'cores' not in values
    # Intel keeps the CPU topology and limits its share of time; the others
    # are given four cores.
    if acceleration == 'openvino' and not limited:
        run('pct', 'set', str(vmid), '--cpulimit', '4', '--delete', 'cores')
    elif acceleration != 'openvino' and limited:
        run('pct', 'set', str(vmid), '--cores', '4', '--delete', 'cpulimit')


def validate(acceleration, render_device, gfx_override):
    if acceleration not in PROFILES:
        raise ValueError(translate('Immich GPU profile not validated'))
    if acceleration in ('openvino', 'rocm'):
        if not render_device or not RENDER.fullmatch(render_device) or not Path(render_device).is_char_device():
            raise ValueError(f"{translate('The render device does not exist:')} {render_device}")
        vendor = Path(f'/sys/class/drm/{Path(render_device).name}/device/vendor').read_text().strip()
        if vendor != ('0x8086' if acceleration == 'openvino' else '0x1002'):
            raise ValueError(translate('The render device does not belong to the GPU of that choice'))
    if acceleration == 'rocm' and not Path('/dev/kfd').is_char_device():
        raise ValueError(translate('ROCm requires /dev/kfd on the host'))
    if acceleration == 'cuda' and subprocess.run(['nvidia-smi', '-L'], capture_output=True, check=False).returncode:
        raise ValueError(translate('The host NVIDIA driver is not responding correctly'))
    if gfx_override and (acceleration != 'rocm' or not re.fullmatch(r'[0-9]{1,2}\.[0-9]\.[0-9]', gfx_override)):
        raise ValueError(translate('Invalid ROCm generation override'))


def recorded(record, acceleration, render_device, gfx_override):
    """The recognition settings of a record after the change."""
    settings = dict(record['deployment'].get('machine_learning') or {})
    settings.update(acceleration=acceleration,
                    render_device=render_device if acceleration in ('openvino', 'rocm') else None,
                    gfx_override=gfx_override if acceleration == 'rocm' else None)
    settings['resources'] = dict(settings.get('resources') or {}, memory_mb=memory(acceleration),
                                 cpu_allocation='quota' if acceleration == 'openvino' else 'cpuset')
    return settings


def memory(acceleration):
    return 4096 if acceleration == 'cpu' else 8192


def resources(current, acceleration):
    """The resources a record declares for the container of the new choice."""
    result = dict(current, memory_mb=memory(acceleration))
    result.pop('cpu_allocation', None)
    if acceleration == 'openvino':
        result['cpu_allocation'] = 'quota'
    return result


def declared(environment, acceleration, gfx_override):
    """The variables a record declares, with the ones of the new choice."""
    result = [entry for entry in environment if entry.get('name') not in GPU_VARIABLES]
    if acceleration == 'cuda':
        result.append({'name': 'NVIDIA_DRIVER_CAPABILITIES', 'value': NVIDIA_CAPABILITIES})
    if acceleration == 'rocm' and gfx_override:
        result += [{'name': 'HSA_OVERRIDE_GFX_VERSION', 'value': gfx_override}, {'name': 'HSA_USE_SVM', 'value': '0'}]
    return result


def declare(record, acceleration, gfx_override):
    """A record an update already rebuilt describes its container by itself:
    it takes the variables, the resources and the disk of the new choice."""
    plan = record['deployment']
    if 'native_config' in plan:
        return
    plan['environment'] = declared(plan.get('environment', []), acceleration, gfx_override)
    plan['resources'] = resources(plan.get('resources') or {}, acceleration)
    size = re.search(r'size=([0-9]+)G', settings(record['vmid']).get('rootfs', ''))
    if size and isinstance(plan.get('rootfs'), dict):
        plan['rootfs']['size_gb'] = int(size[1])
    profile = (record['template'].get('proxmox') or {}).get('installer_profile')
    if isinstance(profile, dict):
        profile.pop('cpu_allocation', None)
        if acceleration == 'openvino':
            profile['cpu_allocation'] = 'quota'


def chosen(record):
    """What runs recognition according to a record."""
    saved = record['deployment'].get('machine_learning') or {}
    return saved.get('acceleration', 'cpu'), saved.get('render_device'), saved.get('gfx_override')


def stop(vmid):
    try:
        run('pct', 'shutdown', str(vmid), '--timeout', '60')
    except RuntimeError:
        run('pct', 'stop', str(vmid))


def apply(root, primary_id, vmid, images, acceleration, render_device, gfx_override):
    """Give the stopped container and the records one choice."""
    configure(vmid, acceleration, render_device, gfx_override)
    learning = instances.read(root, vmid)
    learning['template']['container_contract']['image']['reference'] = images[acceleration]
    learning['deployment']['machine_learning'] = recorded(learning, acceleration, render_device, gfx_override)
    declare(learning, acceleration, gfx_override)
    instances.write(instances.location(root, vmid), learning)
    primary = instances.read(root, primary_id)
    primary['stack']['deployment']['machine_learning'] = recorded(
        {'deployment': primary['stack']['deployment']}, acceleration, render_device, gfx_override)
    intent = (primary.get('native_stack_intent') or {}).get('deployment')
    if isinstance(intent, dict) and 'machine_learning' in intent:
        intent['machine_learning'] = recorded({'deployment': intent}, acceleration, render_device, gfx_override)
    instances.write(instances.location(root, primary_id), primary)
    oci_stack_modify.register(root, vmid)


def revert(root, primary_id, vmid, images, previous, was_running):
    """Give the container and the records the choice they had. Returns
    whether they have it again."""
    try:
        if oci_stack_modify.is_running(vmid):
            stop(vmid)
        apply(root, primary_id, vmid, images, *previous)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        msg_warn(f"{translate('The previous recognition choice could not be put back:')} {error}")
        return False
    if was_running:
        subprocess.run(['pct', 'start', str(vmid)], capture_output=True, check=False)
    return True


def change(root, primary_id, acceleration, render_device=None, gfx_override=None):
    validate(acceleration, render_device, gfx_override)
    with instances.locked(root):
        primary, found = members(root, primary_id)
        learning = found['machine-learning']
        vmid = learning['vmid']
        if any(record.get('status') != 'installed' or record.get('pending_transaction')
               or record.get('pending_stack_transaction') for record in found.values()):
            raise ValueError(translate('The container has an operation pending; finish or recover it first'))
        if current(learning) == acceleration:
            raise ValueError(translate('Recognition already runs on that choice'))
        images = primary['stack']['template']['proxmox']['application_options']['machine_learning']['profile_images']
        previous = chosen(learning)
        was_running = oci_stack_modify.is_running(vmid)
        try:
            if was_running:
                msg_info(translate('Stopping the container...'))
                stop(vmid)
                msg_ok(translate('Container stopped'))
            msg_info(translate('Preparing the machine learning container for the new choice...'))
            apply(root, primary_id, vmid, images, acceleration, render_device, gfx_override)
            msg_ok(translate('Machine learning container prepared'))
        except BaseException as error:
            error.recognition_kept = revert(root, primary_id, vmid, images, previous, was_running)
            raise
    try:
        # The image of the new choice replaces the one in use, as an update does.
        oci_stack_native.run(primary_id, acknowledge_external_data=True)
    except BaseException as error:
        with instances.locked(root):
            # An update left halfway keeps its own record of what to restore.
            error.recognition_kept = (not instances.read(root, primary_id).get('pending_stack_transaction')
                                      and revert(root, primary_id, vmid, images, previous, was_running))
        raise
    if was_running and not oci_stack_modify.is_running(vmid):
        # An update leaves each container as it found it, and this one was
        # stopped for the change.
        run('pct', 'start', str(vmid))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmid', type=int, help='main container of the application')
    parser.add_argument('--acceleration', required=True, choices=PROFILES)
    parser.add_argument('--render-device')
    parser.add_argument('--gfx-override')
    parser.add_argument('--root', type=Path, default=instances.ROOT)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    try:
        change(args.root, args.vmid, args.acceleration, args.render_device, args.gfx_override)
    except BlockingIOError:
        msg_error(translate('Another OCI operation is using the instance registry. Wait for it to finish.'))
        return 1
    except (OSError, ValueError, KeyError, RuntimeError, StopIteration, subprocess.SubprocessError) as error:
        if not getattr(error, 'oci_reported', False):
            # Only an error raised before anything was touched, or one that
            # was put back, leaves the previous choice in place.
            kept = getattr(error, 'recognition_kept', True)
            message = (translate('The recognition of Immich was not changed:') if kept
                       else translate('The recognition change of Immich did not complete:'))
            msg_error(f"{message} {error}")
        return 1
    msg_ok(translate('Recognition of Immich changed; the application was updated with the new choice.'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
