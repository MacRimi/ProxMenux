"""Explicitly adopt supported Proxmox mounts and devices into an OCI instance."""
from __future__ import annotations

import copy
import re
import uuid

import oci_instances as instances
import oci_gpu_devices as gpu_devices
import oci_host_mounts as host_mounts
import oci_instance_transaction as transaction
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
        raise ValueError(f'{key}: {translate("Only backed-up Proxmox volumes can be adopted")}')
    storage, volume = source.split(':', 1)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', storage) or not volume:
        raise ValueError(f'{key}: {translate("Invalid Proxmox volume ID")}')
    if not re.search(rf'(?:^|/)(?:vm|subvol)-{vmid}-disk-[0-9]+(?:\.|$)', volume):
        raise ValueError(f'{key}: {translate("The disk does not belong to this CT; automatic adoption is unsafe")}')
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
        raise ValueError(f'{key}: {translate("Only Intel/AMD DRM, Coral and USB nodes can be adopted automatically")}')
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


def propose(record, config):
    if (record.get('status') != 'installed' or record.get('stack') or record.get('stack_member')
            or record.get('native_stack_intent') or record.get('deployment', {}).get('stack_managed')):
        raise ValueError(translate('Only an installed standalone OCI instance can adopt external changes'))
    if instances.identity(config) != record['installation_id']:
        raise ValueError(translate('The container identity changed; nothing was adopted'))
    before = parse_config(record['observed']['config'].encode())
    current = parse_config(config)
    changed = sorted(key for key in before.keys() | current.keys() if before.get(key) != current.get(key))
    # Notes do not describe a mount, device or runtime setting. The OCI marker
    # was checked above, so a presentation-only change needs no adoption.
    if 'description' in changed:
        changed.remove('description')
    new_keys = [key for key in changed if key not in before and re.fullmatch(r'(mp|dev)[0-9]+', key)]
    unsupported = [key for key in changed if key not in new_keys and key not in transaction.ADOPTABLE
                   and key not in transaction.KEPT_AS_IS]
    if unsupported:
        raise ValueError(f"{translate('These manual changes cannot be adopted safely:')} {', '.join(unsupported)}")
    if not new_keys:
        return None
    candidate = copy.deepcopy(record)
    deployment = candidate['deployment']
    details = []
    for key in new_keys:
        if key.startswith('mp'):
            mount = _mount(key, current[key], record['vmid'])
            deployment.setdefault('mounts', []).append(mount)
            details.append(f"{key}: {mount['container_path']} <- {current[key].split(',', 1)[0]} "
                           f"({mount['type']}, backup={int(mount['backup'])})")
        else:
            device = _device(key, current[key])
            deployment.setdefault('devices', []).append(device)
            kind = 'GPU' if gpu_devices.gpu_path(device['host_path']) else 'USB/Coral'
            details.append(f"{key}: {device['host_path']} ({kind})")
    filtered = b'\n'.join(line for line in config.splitlines()
                          if not any(line.startswith(key.encode() + b': ') for key in new_keys)) + b'\n'
    for key, value in transaction.external_changes(record, filtered).items():
        section, name = transaction.ADOPTABLE[key]
        target = deployment.setdefault(section, {}) if section else deployment
        target[name] = value
    candidate['observed']['config'] = config.decode()
    candidate['observed']['config_sha256'] = sha(config)
    candidate['observed']['gpu_devices'] = gpu_devices.capture(config)
    candidate['observed']['host_bind_sources'] = host_mounts.capture_sources(config)
    transaction.preflight(candidate, copy.deepcopy(candidate), config)
    return {'candidate': candidate, 'details': details,
            'previous_record_hash': sha(instances.location(instances.ROOT, record['vmid']).read_bytes()),
            'config_sha256': sha(config)}


def commit(root, vmid, proposal):
    with instances.locked(root):
        record = instances.read(root, vmid)
        path = instances.location(root, vmid)
        if sha(path.read_bytes()) != proposal['previous_record_hash']:
            raise ValueError(translate('The OCI contract changed while reviewing; nothing was adopted'))
        config = instances.command('pct', 'config', str(vmid))
        if sha(config) != proposal['config_sha256']:
            raise ValueError(translate('The LXC changed while reviewing; nothing was adopted'))
        checked = propose(record, config)
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
