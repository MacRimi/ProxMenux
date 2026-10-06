#!/usr/bin/env python3
"""Add or remove the extra paths and devices of one member of an installed
multi-container application, without rebuilding any of its containers."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import oci_gpu_devices as gpu_devices
import oci_host_mounts as host_mounts
import oci_instance_reconcile as reconcile
import oci_instances as instances
import oci_stack_replay as replay
from oci_ui import msg_error, msg_info, msg_ok, translate

CONVERTERS = {'install_nextcloud_stack.sh': replay.nextcloud_record,
              'install_paperless_stack.sh': replay.paperless_record,
              'install_tandoor_stack.sh': replay.tandoor_record,
              'install_immich_stack.sh': replay.immich_record}


def run(*command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ['']
        raise RuntimeError(f"{' '.join(command[:3])}: {detail[0]}")
    return result.stdout


def entries(vmid, prefix):
    """The `prefix`N lines of the container configuration, in order."""
    result = {}
    for line in run('pct', 'config', str(vmid)).splitlines():
        key, separator, value = line.partition(': ')
        if separator and re.fullmatch(prefix + '[0-9]+', key):
            result[key] = value
    return result


def options(value):
    return dict(part.split('=', 1) for part in value.split(',')[1:] if '=' in part)


def free_key(vmid, prefix):
    used = entries(vmid, prefix)
    return next(f'{prefix}{index}' for index in range(256) if f'{prefix}{index}' not in used)


def device_path(value):
    fields = dict(part.split('=', 1) for part in value.split(',') if '=' in part)
    return fields.get('path') or value.split(',', 1)[0]


def validate(vmid, changes):
    """Everything that can be refused is refused before the container stops."""
    mounts = {options(value).get('mp'): (key, value) for key, value in entries(vmid, 'mp').items()}
    devices = {device_path(value): key for key, value in entries(vmid, 'dev').items()}
    for path in changes['remove_mounts']:
        if path not in mounts:
            raise ValueError(f"{translate('The path to remove is not mounted:')} {path}")
    for path in changes['remove_devices']:
        if path not in devices:
            raise ValueError(f"{translate('The device to remove is not attached:')} {path}")
    kept = [path for path in mounts if path not in changes['remove_mounts']]
    for mount in changes['add_mounts']:
        target = host_mounts.valid_path(mount['container_path'])
        if any(target == other or target.startswith(other.rstrip('/') + '/')
               or other.startswith(target.rstrip('/') + '/') for other in kept):
            raise ValueError(f"{translate('The custom path overlaps another mount')}: {target}")
        kept.append(target)
        if mount['type'] == 'managed-volume':
            if not isinstance(mount.get('size_gb'), int) or mount['size_gb'] < 1 \
                    or not re.fullmatch(r'[A-Za-z0-9_-]+', mount.get('source') or ''):
                raise ValueError(f"{translate('Invalid volume size:')} {target}")
        elif mount['type'] == 'host-bind':
            host_mounts.validate_source(mount['source'], allow_missing=True)
        else:
            raise ValueError(f"{translate('Unsupported mount type:')} {mount['type']}")
    for device in changes['add_devices']:
        path = device.get('host_path')
        if device.get('kind') != 'character-device' or not (
                gpu_devices.gpu_path(path) or gpu_devices.peripheral_path(path)):
            raise ValueError(f"{translate('Device outside the supported profiles; NVIDIA and device trees require another profile')}: {path}")
        if path in devices and path not in changes['remove_devices']:
            raise ValueError(f"{translate('This device is already attached')}: {path}")
        gpu_devices.snapshot(path)


def apply(vmid, changes):
    for mount in changes['add_mounts']:
        target = mount['container_path']
        if mount['type'] == 'managed-volume':
            value = f"{mount['source']}:{mount['size_gb']},mp={target},backup=1"
        else:
            source = Path(mount['source'])
            if not source.exists():
                source.mkdir(parents=True, mode=0o775)
                os.chown(source, 100000, 100000)
            value = f"{source},mp={target},backup=0"
        if mount.get('read_only'):
            value += ',ro=1'
        run('pct', 'set', str(vmid), '--' + free_key(vmid, 'mp'), value)
        msg_ok(f"{translate('Path added:')} {target}")
    for path in changes['remove_devices']:
        key = next(key for key, value in entries(vmid, 'dev').items() if device_path(value) == path)
        run('pct', 'set', str(vmid), '--delete', key)
        msg_ok(f"{translate('Device removed:')} {path}")
    for device in changes['add_devices']:
        path = device['host_path']
        value = (f"path={path},mode={device.get('mode', '0660')},"
                 f"deny-write={'1' if device.get('deny_write') else '0'},gid={os.stat(path).st_gid}")
        run('pct', 'set', str(vmid), '--' + free_key(vmid, 'dev'), value)
        msg_ok(f"{translate('Device added:')} {path}")
    for path in changes['remove_mounts']:
        key, value = next((key, value) for key, value in entries(vmid, 'mp').items()
                          if options(value).get('mp') == path)
        source = value.split(',', 1)[0]
        run('pct', 'set', str(vmid), '--delete', key)
        if not source.startswith('/'):
            # A detached disk would be destroyed with the container on its next
            # update, so the volume of a removed path is deleted here, as confirmed.
            unused = next((key for key, value in entries(vmid, 'unused').items() if value == source), None)
            if unused:
                run('pct', 'set', str(vmid), '--delete', unused)
        msg_ok(f"{translate('Path removed:')} {path}")


def recorded_mounts(vmid):
    """The mounts of a member as its installation recorded them."""
    result = []
    for value in entries(vmid, 'mp').values():
        source = value.split(',', 1)[0]
        mount = options(value)
        result.append({'container_path': mount['mp'], 'source': source,
                       'type': 'host-bind' if source.startswith('/') else 'managed-volume',
                       'backup': mount.get('backup') == '1', 'read_only': mount.get('ro') == '1',
                       'existing_volume': True})
    return result


def register(root, vmid):
    """Record the member as it is now, the way a stack update leaves it, and
    refresh the copy its main container keeps."""
    record = instances.read(root, vmid)
    previous = record['observed']
    record['observed'] = instances.observe(vmid, record['installation_id'], previous['archive_path'],
                                           previous['resolved_registry_digest'], previous['image'])
    plan = record['deployment']
    adapter = (plan.get('replay_profile') or {}).get('adapter')
    if adapter in CONVERTERS:
        if 'native_config' in plan:
            plan['native_config'] = record['observed']['config']
            if 'member_replay_projection' in plan:
                plan['member_replay_projection'] = replay.normalize(record)
            plan['mounts'] = recorded_mounts(vmid)
        else:
            converted = CONVERTERS[adapter](record)
            plan['mounts'] = converted['deployment']['mounts']
            plan['devices'] = converted['deployment'].get('devices', [])
            # The paths an update must find are the ones mounted now.
            record['template']['container_contract']['volumes'] = \
                converted['template']['container_contract']['volumes']
        # The stack must stay updatable with what was just changed.
        CONVERTERS[adapter](record)
    else:
        known = {mount['container_path']: mount for mount in plan.get('mounts', [])}
        plan['mounts'] = [known.get(options(value).get('mp')) or reconcile._mount(key, value, vmid)
                          for key, value in entries(vmid, 'mp').items()]
        attached = {device_path(value): (key, value) for key, value in entries(vmid, 'dev').items()}
        kept = [device for device in plan.get('devices', [])
                if device.get('kind') != 'character-device' or device.get('host_path') in attached]
        listed = {device.get('host_path') for device in kept}
        plan['devices'] = kept + [reconcile._device(key, value) for path, (key, value) in attached.items()
                                  if path not in listed and (gpu_devices.gpu_path(path)
                                                             or gpu_devices.peripheral_path(path))]
    instances.write(instances.location(root, vmid), record)
    primary_id = (record.get('stack_member') or {}).get('primary_vmid', vmid)
    primary = instances.read(root, primary_id)
    snapshot = instances.read(root, vmid)
    snapshot.pop('stack', None)
    members = primary.get('stack', {}).get('members', [])
    for index, member in enumerate(members):
        if member.get('vmid') == vmid:
            members[index] = snapshot
    instances.write(instances.location(root, primary_id), primary)


def is_running(vmid):
    return 'running' in run('pct', 'status', str(vmid))


def modify(root, vmid, changes):
    record = instances.read(root, vmid)
    if record.get('status') != 'installed' or record.get('pending_transaction') \
            or record.get('pending_stack_transaction'):
        raise ValueError(translate('The container has an operation pending; finish or recover it first'))
    if not (record.get('stack_member') or record.get('stack')):
        raise ValueError(translate('This container is not a member of a multi-container application'))
    if instances.identity(instances.command('pct', 'config', str(vmid))) != record['installation_id']:
        raise ValueError(translate('The container identity does not match'))
    validate(vmid, changes)
    backup = instances.location(root, vmid).parent / f"config-before-recreate-{time.strftime('%Y%m%d-%H%M%S')}.conf"
    backup.write_text(run('pct', 'config', str(vmid)))
    backup.chmod(0o600)
    import oci_operation_notice
    import oci_update_current
    primary_id = (record.get('stack_member') or {}).get('primary_vmid', vmid)
    name = oci_update_current.application_name(instances.read(root, primary_id), primary_id)
    with oci_operation_notice.operation([vmid], 'recreate', name, primary_id):
        _modify(root, vmid, changes)


def _modify(root, vmid, changes):
    running = is_running(vmid)
    if running:
        msg_info(translate('Stopping the container...'))
        try:
            run('pct', 'shutdown', str(vmid), '--timeout', '60')
        except RuntimeError:
            run('pct', 'stop', str(vmid))
        msg_ok(translate('Container stopped'))
    try:
        apply(vmid, changes)
        msg_info(translate('Saving the new configuration of the application...'))
        register(root, vmid)
        msg_ok(translate('Configuration saved'))
    finally:
        if running:
            msg_info(translate('Starting the container...'))
            run('pct', 'start', str(vmid))
            msg_ok(translate('Container started'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmid', type=int)
    parser.add_argument('--changes', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=instances.ROOT)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    changes = {'remove_mounts': [], 'add_mounts': [], 'remove_devices': [], 'add_devices': [],
               **json.loads(args.changes.read_text())}
    try:
        with instances.locked(args.root):
            modify(args.root, args.vmid, changes)
    except BlockingIOError:
        msg_error(translate('Another OCI operation is using the instance registry. Wait for it to finish.'))
        return 1
    except (OSError, ValueError, KeyError, RuntimeError, StopIteration, subprocess.TimeoutExpired) as error:
        msg_error(f"{translate('The application could not be modified:')} {error}")
        return 1
    msg_ok(translate('The application has been modified with the new options.'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
