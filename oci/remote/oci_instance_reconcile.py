"""Explicitly adopt supported Proxmox mounts and devices into an OCI instance."""
from __future__ import annotations

import copy
import re
import uuid

import oci_instances as instances
import oci_gpu_devices as gpu_devices
import oci_host_mounts as host_mounts
import oci_instance_transaction as transaction
import oci_native_modify as native_modify
from oci_installation_state import parse_config, sha
from oci_ui import translate


def _managed_size(value):
    match = re.fullmatch(r'([1-9][0-9]*)([GMT])', value or '')
    if not match:
        raise ValueError(translate('The added disk needs a whole-GiB size recorded by Proxmox'))
    amount, unit = int(match[1]), match[2]
    if unit == 'M':
        if amount % 1024:
            raise ValueError(translate('The added disk size is not a whole GiB'))
        return amount // 1024
    return amount * (1024 if unit == 'T' else 1)


def _mount(key, value, vmid):
    source, *parts = value.split(',')
    if not source or not parts or any('=' not in part for part in parts):
        raise ValueError(f'{key}: {translate("Incomplete mount configuration")}')
    options = dict(part.split('=', 1) for part in parts)
    if len(options) != len(parts) or set(options) - {'mp', 'size', 'backup', 'ro'}:
        raise ValueError(f'{key}: {translate("Unsupported mount options")}')
    target = host_mounts.valid_path(options.get('mp'))
    read_only = options.get('ro', '0') == '1'
    if options.get('ro', '0') not in ('0', '1'):
        raise ValueError(f'{key}: {translate("Invalid read-only option")}')
    if source.startswith('/'):
        if options.get('backup', '0') != '0' or 'size' in options:
            raise ValueError(f'{key}: {translate("Host directories cannot be included in vzdump")}')
        host_mounts.validate_source(source)
        return {'type': 'host-bind', 'container_path': target, 'source': source,
                'size_gb': None, 'backup': False, 'read_only': read_only,
                'create_if_missing': False}
    if options.get('backup') != '1' or ':' not in source:
        raise ValueError(f'{key}: {translate("Proxmox volume adoption requires backup=1 and a volume ID")}')
    storage, volume = source.split(':', 1)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', storage) or not volume:
        raise ValueError(f'{key}: {translate("Invalid Proxmox volume ID")}')
    if not re.search(rf'(?:^|/)(?:vm|subvol)-{vmid}-disk-[0-9]+(?:\.|$)', volume):
        raise ValueError(f'{key}: {translate("The volume ID does not contain a disk name for this CT; automatic adoption is unsafe")}')
    return {'type': 'managed-volume', 'container_path': target, 'source': storage,
            'size_gb': _managed_size(options.get('size')), 'backup': True,
            'read_only': read_only}


def _device(key, value):
    parts = value.split(',')
    if any('=' not in part for part in parts):
        raise ValueError(f'{key}: {translate("Incomplete device configuration")}')
    fields = dict(part.split('=', 1) for part in parts)
    if len(fields) != len(parts) or set(fields) - {'path', 'mode', 'gid', 'uid', 'deny-write'}:
        raise ValueError(f'{key}: {translate("Unsupported device options")}')
    path = fields.get('path')
    if not (gpu_devices.gpu_path(path) or gpu_devices.peripheral_path(path)):
        raise ValueError(f'{key}: {translate("Only Intel/AMD DRM, Coral, NPU and USB nodes can be adopted automatically")}')
    snapshot = gpu_devices.snapshot(path)
    mode = fields.get('mode', '0660')
    if not re.fullmatch(r'0?[0-7]{3}', mode):
        raise ValueError(f'{key}: {translate("Invalid device mode")}')
    gid = int(fields.get('gid', '0'))
    if gid not in (0, snapshot['gid']):
        raise ValueError(f'{key}: {translate("Device GID does not match the host")}')
    if fields.get('deny-write', '0') not in ('0', '1'):
        raise ValueError(f'{key}: {translate("Invalid device permissions")}')
    uid = int(fields.get('uid', '0'))
    if uid < 0 or uid >= 4294967295:
        raise ValueError(f'{key}: {translate("Invalid device UID")}')
    device = {'id': 'adopted-' + path.removeprefix('/dev/').replace('/', '-'),
              'kind': 'character-device', 'host_path': path, 'container_path': path,
              'mode': mode, 'gid_strategy': 'host-device-gid' if gid == snapshot['gid'] else 'none',
              'deny_write': fields.get('deny-write', '0') == '1'}
    if uid:
        device['uid'] = uid
    if gpu_devices.gpu_path(path) and path != '/dev/kfd':
        device['drm_vendor_ids'] = [snapshot['vendor']]
    return device


ENVIRONMENT_KEYS = ('env', 'lxc.environment.runtime')


def _environment(record, config):
    """Variables changed in Proxmox since the last operation. Values are
    applied but never listed: they may be passwords. A variable the image
    defines and the user removed comes back with its value, as in Docker."""
    before = native_modify.environment(record['observed']['config'].encode())
    now = native_modify.environment(config)
    removed = sorted(before.keys() - now.keys())
    changed = sorted(name for name in now if before.get(name) != now[name])
    return {name: now[name] for name in changed}, removed


def _adopt_environment(deployment, values, removed):
    items = deployment.setdefault('environment', [])
    details = []
    for name, value in values.items():
        matches = [item for item in items if item['name'] == name]
        if len(matches) > 1:
            raise ValueError(translate('Duplicate variable in the contract; review it before editing'))
        if matches:
            matches[0]['value'] = value
            details.append(f"env {name}: {translate('value changed in Proxmox')}")
        else:
            items.append({'name': name, 'value': value, 'sensitive': True})
            details.append(f"env {name}: {translate('added in Proxmox')}")
    for name in removed:
        items[:] = [item for item in items if item['name'] != name]
        details.append(f"env {name}: {translate('removed in Proxmox')}")
    return details


def _storage_change(key, value, deployment, vmid):
    """A disk resized or moved in Proxmox: the record follows it."""
    if key == 'rootfs':
        storage = value.split(':', 1)[0]
        size = dict(part.split('=', 1) for part in value.split(',')[1:] if '=' in part).get('size')
        deployment['rootfs'].update(storage=storage, size_gb=_managed_size(size))
        return
    current = _mount(key, value, vmid)
    for mount in deployment.get('mounts', []):
        if mount.get('container_path') == current['container_path']:
            mount.update({field: current[field] for field in ('source', 'size_gb', 'read_only')})


def propose(record, config, member=False):
    if (record.get('status') != 'installed' or (not member and (
            record.get('stack') or record.get('stack_member') or record.get('native_stack_intent')
            or record.get('deployment', {}).get('stack_managed')))):
        raise ValueError(translate('Only an installed standalone OCI instance can adopt external changes'))
    if instances.identity(config) != record['installation_id']:
        raise ValueError(translate('The container identity changed; nothing was adopted'))
    if transaction.nested_mounts.stale(config):
        transaction.nested_mounts.follow(record['vmid'])
        config = instances.command('pct', 'config', str(record['vmid']))
    before, current = transaction.settings(record['observed']['config'].encode()), transaction.settings(config)
    changed = sorted(key for key in before.keys() | current.keys() if before.get(key) != current.get(key))
    # Notes do not describe a mount, device or runtime setting. The OCI marker
    # was checked above, so a presentation-only change needs no adoption.
    if 'description' in changed:
        changed.remove('description')
    environment = None
    if any(key in ENVIRONMENT_KEYS for key in changed):
        changed = [key for key in changed if key not in ENVIRONMENT_KEYS]
        environment = _environment(record, config)
    custom = transaction.custom_lxc(record, config)
    custom_keys = {line.split(': ', 1)[0] for line in (*custom, *record['deployment'].get('custom_lxc', []))}
    custom_changed = sorted(custom) != sorted(record['deployment'].get('custom_lxc', []))
    changed = [key for key in changed if key not in custom_keys]
    new_keys = [key for key in changed if key not in before and re.fullmatch(r'(mp|dev)[0-9]+', key)]
    storage = [key for key in changed if key in current and key in before and re.fullmatch(r'rootfs|mp[0-9]+', key)]
    detached = [key for key in changed if key not in current and (
        re.fullmatch(r'dev[0-9]+', key) or (re.fullmatch(r'mp[0-9]+', key) and before[key].startswith('/')))]
    unsupported = [key for key in changed if key not in new_keys and key not in storage and key not in detached
                   and key != 'net0'
                   and key not in transaction.ADOPTABLE and key not in transaction.KEPT_AS_IS]
    if unsupported:
        raise ValueError(f"{translate('These manual changes cannot be adopted safely:')} {', '.join(unsupported)}")
    if not member and not (new_keys or storage or detached or custom_changed or environment is not None
                           or {'net0', 'hostname', 'entrypoint'} & set(changed)):
        return None
    candidate = copy.deepcopy(record)
    deployment = candidate['deployment']
    if custom:
        deployment['custom_lxc'] = custom
    else:
        deployment.pop('custom_lxc', None)
    details = _adopt_environment(deployment, *environment) if environment else []
    for key in storage:
        _storage_change(key, current[key], deployment, record['vmid'])
    # A host directory or a device taken away in Proxmox holds no data of the container.
    for key in detached:
        fields = dict(part.split('=', 1) for part in before[key].split(',') if '=' in part)
        if key.startswith('mp'):
            deployment['mounts'] = [mount for mount in deployment.get('mounts', [])
                                    if mount.get('container_path') != fields.get('mp')]
        else:
            path = fields.get('path') or before[key].split(',', 1)[0]
            deployment['devices'] = [device for device in deployment.get('devices', [])
                                     if device.get('host_path') != path]
    for key in new_keys:
        if key.startswith('mp'):
            mount = _mount(key, current[key], record['vmid'])
            deployment.setdefault('mounts', []).append(mount)
            details.append(f"{key}: {mount['container_path']} <- {current[key].split(',', 1)[0]} "
                           f"({mount['type']}, backup={int(mount['backup'])})")
        else:
            device = _device(key, current[key])
            deployment.setdefault('devices', []).append(device)
            kind = 'GPU' if gpu_devices.gpu_path(device['host_path']) else 'USB/Coral/NPU'
            details.append(f"{key}: {device['host_path']} ({kind})")
    skipped = [*new_keys, *storage, *detached, *custom_keys, *(ENVIRONMENT_KEYS if environment else ())]
    filtered = b'\n'.join(line for line in config.splitlines()
                          if not any(line.startswith(key.encode() + b': ') for key in skipped))
    if environment or storage or detached or custom_keys:
        filtered += b''.join(b'\n' + line for line in record['observed']['config'].encode().splitlines()
                             if any(line.startswith(key.encode() + b': ')
                                    for key in (*storage, *detached, *custom_keys,
                                                *(ENVIRONMENT_KEYS if environment else ()))))
    filtered += b'\n'
    for key, value in transaction.external_changes(record, filtered).items():
        section, name = transaction.ADOPTABLE[key]
        target = deployment.setdefault(section, {}) if section else deployment
        target[name] = value
    candidate['observed']['config'] = config.decode()
    candidate['observed']['config_sha256'] = sha(config)
    candidate['observed']['gpu_devices'] = gpu_devices.capture(config)
    candidate['observed']['host_bind_sources'] = host_mounts.capture_sources(config)
    transaction.preflight(candidate, copy.deepcopy(candidate), config, coordinated=member)
    # A disk or a device is reviewed; the rest is what the user already decided.
    return {'candidate': candidate, 'details': details, 'review': bool(new_keys),
            'previous_record_hash': sha(instances.location(instances.ROOT, record['vmid']).read_bytes()),
            'config_sha256': sha(config)}


def commit(root, vmid, proposal):
    with instances.locked(root):
        return commit_locked(root, vmid, proposal)


def commit_locked(root, vmid, proposal, member=False):
    record = instances.read(root, vmid)
    path = instances.location(root, vmid)
    if sha(path.read_bytes()) != proposal['previous_record_hash']:
        raise ValueError(translate('The OCI contract changed while reviewing; nothing was adopted'))
    config = instances.command('pct', 'config', str(vmid))
    if sha(config) != proposal['config_sha256']:
        raise ValueError(translate('The LXC changed while reviewing; nothing was adopted'))
    checked = propose(record, config, member)
    if checked is None or checked['details'] != proposal['details']:
        raise ValueError(translate('The proposed changes no longer match; nothing was adopted'))
    candidate = checked['candidate']
    observed = instances.observe(vmid, record['installation_id'], record['observed']['archive_path'],
                                 record['observed']['resolved_registry_digest'], record['observed']['image'])
    if observed['config_sha256'] != proposal['config_sha256']:
        raise ValueError(translate('The LXC changed during verification; nothing was adopted'))
    candidate['observed'] = observed
    history = path.parent / 'history'
    instances.write(history / f'before-reconciliation-{uuid.uuid4().hex}.json', record)
    instances.write(path, candidate)
    return candidate
