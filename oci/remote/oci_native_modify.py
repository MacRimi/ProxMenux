"""Edit an installed application's LXC configuration, retaining its rootfs/data.

Runtime changes use a controlled stop/start, not pct destroy/create. Values,
including secrets and NUL-separated environment, reach PVE over stdin only.
"""
import copy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import uuid

import oci_instances as instances
import oci_instance_transaction as transaction
import oci_resource_modify as resources
import oci_gpu_devices as devices
import oci_host_mounts as host_mounts
from oci_installation_state import parse_config, sha
from oci_ui import translate, msg_info, msg_ok, msg_warn

PERL_UPDATE = r'''
use strict; use warnings; use JSON::PP;
use PVE::RPCEnvironment; use PVE::INotify; use PVE::API2::LXC::Config;
PVE::RPCEnvironment->setup_default_cli_env();
my $p = decode_json(do { local $/; <STDIN> });
$p->{node} = PVE::INotify::nodename();
PVE::API2::LXC::Config->update_vm($p);
'''


def environment(config):
    result = {}
    entries = []
    for line in config.decode().splitlines():
        if line.startswith('lxc.environment.runtime: '):
            entries.append(line.split(': ', 1)[1])
        elif line.startswith('env: '):
            # pct config exposes PVE's public env property, whereas older
            # observations and native files contain repeated runtime lines.
            entries.extend(line.split(': ', 1)[1].split('\0'))
    for entry in entries:
        name, sep, value = entry.partition('=')
        if not sep or name in result:
            raise ValueError(translate('Duplicate variable in the contract; review it before editing'))
        result[name] = value
    return result


def environment_values(items):
    result = {}
    for item in items:
        name, value = item['name'], str(item['value'])
        if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) or name in result
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError(translate('The value contains an unsupported character'))
        result[name] = value
    return result


def changes(record, candidate, config):
    """Only unchanged recipes and native settings; adapters keep their installer."""
    old = transaction.with_default_healthcheck(copy.deepcopy(record))
    candidate = transaction.with_default_healthcheck(copy.deepcopy(candidate))
    if (old['template'] != candidate['template'] or old['deployment'].get('host_monitor')
            or any(k in record for k in ('stack', 'stack_member', 'native_stack_intent'))
            or old['deployment'].get('stack_managed')):
        return None
    before, after = old['deployment'], candidate['deployment']
    changed = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    allowed = {'resources', 'network', 'environment', 'devices', 'mounts', 'hardware_profile'}
    if not changed or changed - allowed:
        return None
    resource_keys = {k for k in before.get('resources', {}).keys() | after.get('resources', {}).keys()
                     if before.get('resources', {}).get(k) != after.get('resources', {}).get(k)}
    if resource_keys - {'cores', 'memory_mb', 'swap_mb', 'cpu_units'}:
        return None
    if 'devices' in changed:
        if any(d.get('kind', 'character-device') not in ('character-device', 'block-device')
               or d.get('append_host_device_gid_to_environment')
               for plan in (before, after) for d in plan.get('devices', [])):
            return None
        if before.get('device_permissions') or after.get('device_permissions'):
            return None
    if 'mounts' in changed:
        if any(transaction.is_file_bind(m) for plan in (before, after) for m in plan.get('mounts', [])):
            return None
    return changed


def plan(record, candidate, config):
    changed = changes(record, candidate, config)
    if not changed:
        return None
    transaction.preflight(record, candidate, config, in_place=True)
    old, new = record['deployment'], candidate['deployment']
    cfg = parse_config(config)
    values, delete = {}, []
    if 'resources' in changed:
        for key, native, minimum in (('cores', 'cpulimit' if 'cpulimit' in cfg and 'cores' not in cfg else 'cores', 1),
                                     ('memory_mb', 'memory', 128), ('swap_mb', 'swap', 0), ('cpu_units', 'cpuunits', 1)):
            value = new['resources'].get(key)
            if old['resources'].get(key) == value:
                continue
            if value is None and key == 'cpu_units':
                if native in cfg: delete.append(native)
            elif isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(translate('Invalid resource value'))
            else:
                values[native] = str(value)
    if 'network' in changed:
        network = new['network']
        if set(network) - {'bridge', 'ipv4', 'gateway', 'firewall', 'host_managed', 'mac_address'}:
            raise ValueError(translate('Unsupported network settings'))
        if not re.fullmatch(r'[A-Za-z0-9_.:-]+', network['bridge']):
            raise ValueError(translate('Invalid bridge'))
        if not Path('/sys/class/net', network['bridge'], 'bridge').is_dir():
            raise ValueError(translate('The selected bridge does not exist'))
        address = network['ipv4']
        if address not in ('dhcp', 'manual'):
            if ipaddress.ip_interface(address).version != 4:
                raise ValueError(translate('Invalid IPv4 address'))
        gateway = network.get('gateway')
        if gateway and ipaddress.ip_address(gateway).version != 4:
            raise ValueError(translate('Invalid IPv4 gateway'))
        fields = dict(p.split('=', 1) for p in cfg['net0'].split(',') if '=' in p)
        fields.update(bridge=network['bridge'], ip=address)
        if gateway: fields['gw'] = gateway
        else: fields.pop('gw', None)
        for key, native in (('firewall', 'firewall'), ('host_managed', 'host-managed')):
            if old['network'].get(key) != network.get(key):
                fields[native] = '1' if network.get(key) else '0'
        if old['network'].get('mac_address') != network.get('mac_address'):
            raise ValueError(translate('The MAC address of the container cannot be kept'))
        values['net0'] = ','.join(k+'='+v for k, v in fields.items())
    if 'environment' in changed:
        env = environment(config)
        previous = environment_values(old.get('environment', []))
        wanted = environment_values(new.get('environment', []))
        defaults = dict(item.split('=', 1) for item in record['observed']['image'].get('defaults', {}).get('Env', []) if '=' in item)
        for name in previous.keys() - wanted.keys():
            if name in defaults: env[name] = defaults[name]
            else: env.pop(name, None)
        env.update(wanted)
        if env: values['env'] = '\0'.join(k+'='+v for k, v in env.items())
        else: delete.append('env')
    if 'devices' in changed:
        inventory = devices.planned(new)
        existing = {v['path']: k for k, v in ((k, dict(p.split('=', 1) for p in v.split(',')))
                   for k, v in cfg.items() if re.fullmatch(r'dev[0-9]+', k))}
        used = set(existing.values())
        for path, key in existing.items():
            if path not in inventory: delete.append(key)
        for device in new.get('devices', []):
            path = device['host_path']
            key = existing.get(path)
            if not key:
                key = next('dev'+str(n) for n in range(256) if 'dev'+str(n) not in used)
                used.add(key)
            info = inventory[path]
            mode = info['mode'] if device.get('mode') == 'preserve-host' else int(device.get('mode', '0660'), 8)
            values[key] = (f"path={path},mode={mode:04o},uid={int(device.get('uid', 0))},"
                           f"gid={info['gid'] if device['gid_strategy'] == 'host-device-gid' else 0},"
                           f"deny-write={1 if device.get('deny_write') else 0}")
    if 'mounts' in changed:
        actual = transaction.mounts(config)
        used = {m['key'] for m in actual.values()}
        wanted = {m['container_path']: m for m in new.get('mounts', [])}
        for target, mount in actual.items():
            if target not in wanted: delete.append(mount['key'])
        for target, mount in wanted.items():
            if target in actual:
                original = next(m for m in old['mounts'] if m['container_path'] == target)
                if mount == original: continue
                fields = dict(p.split('=', 1) for p in actual[target]['value'].split(',')[1:] if '=' in p)
                fields['ro'] = '1' if mount.get('read_only') else '0'
                values[actual[target]['key']] = actual[target]['volume']+','+','.join(k+'='+v for k, v in fields.items())
                continue
            key = next('mp'+str(n) for n in range(256) if 'mp'+str(n) not in used)
            used.add(key)
            source = mount['source']
            if mount['type'] == 'managed-volume':
                if not re.fullmatch(r'[A-Za-z0-9_-]+', source):
                    raise ValueError(translate('Invalid storage'))
                source += ':'+str(mount['size_gb'])
            else:
                source = host_mounts.valid_path(source)
                if not Path(source).is_dir():
                    if not mount.get('create_if_missing'):
                        raise ValueError(translate('The host directory does not exist'))
            values[key] = (f"{source},mp={target},backup={1 if mount['backup'] else 0},"
                           f"ro={1 if mount.get('read_only') else 0}")
    return {'values': values, 'delete': delete, 'restart': bool(changed - {'resources'}),
            'changed': sorted(changed)}


def verify_values(config, operation):
    """PVE may canonicalize property strings; compare their actual fields."""
    cfg = parse_config(config)
    for key, value in operation['values'].items():
        if key == 'env':
            if environment(config) != dict(item.split('=', 1) for item in value.split('\0')):
                raise ValueError(translate('Proxmox could not apply the container settings'))
        elif re.fullmatch(r'(mp|dev|net)[0-9]+', key):
            desired = dict(p.split('=', 1) for p in value.split(',') if '=' in p)
            actual = dict(p.split('=', 1) for p in cfg.get(key, '').split(',') if '=' in p)
            defaults = {'uid': '0', 'gid': '0', 'deny-write': '0', 'ro': '0', 'backup': '0', 'mode': '0660', 'firewall': '0'}
            def matches(k, v):
                observed = actual.get(k, defaults.get(k))
                if k == 'mode': return observed is not None and int(observed, 8) == int(v, 8)
                return observed == v
            if any(not matches(k, v) for k, v in desired.items()):
                raise ValueError(translate('Proxmox could not apply the container settings'))
        elif cfg.get(key) != value:
            raise ValueError(translate('Proxmox could not apply the container settings'))
    if any(key in cfg or (key == 'env' and environment(config)) for key in operation['delete']):
        raise ValueError(translate('Proxmox could not apply the container settings'))


def set_config(vmid, installation_id, expected, values, delete=()):
    raw = (resources.CONFIG_DIR / f'{vmid}.conf').read_bytes()
    if instances.command('pct', 'config', str(vmid)) != expected or instances.identity(expected) != installation_id:
        raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
    payload = dict(values, vmid=vmid, digest=hashlib.sha1(raw).hexdigest())
    if delete: payload['delete'] = ','.join(delete)
    transaction.log('Applying native settings: '+', '.join(sorted(set(values) | set(delete))))
    process = subprocess.run(['perl', '-e', PERL_UPDATE], input=json.dumps(payload).encode(),
                             capture_output=True, timeout=120)
    # API errors may include secret values. Only keep the exit status.
    if process.returncode:
        raise RuntimeError(translate('Proxmox could not apply the container settings'))


def untouched(before, after, keys):
    keys = set(keys)
    if 'env' in keys: keys.add('lxc.environment.runtime')
    def keep(config):
        return b''.join(line for line in config.splitlines(keepends=True)
                        if line.split(b':', 1)[0].decode() not in keys
                        and not re.match(rb'unused[0-9]+:', line))
    return keep(before) == keep(after)


def restore_settings(root, record, before, now, operation):
    vmid = record['vmid']
    keys = set(operation['values']) | set(operation['delete'])
    if operation['restart']: transaction.stop(vmid)
    original = parse_config(before)
    restore = {k: original[k] for k in keys if k in original and k != 'env'}
    remove = [k for k in keys if k not in original and k != 'env' and k in parse_config(now)]
    if 'env' in keys:
        env = environment(before)
        if env: restore['env'] = '\0'.join(k+'='+v for k, v in env.items())
        elif environment(now): remove.append('env')
    if restore or remove:
        set_config(vmid, record['installation_id'], now, restore, remove)
    restored_config = instances.command('pct', 'config', str(vmid))
    verify_values(restored_config, {'values': restore, 'delete': remove})
    if not untouched(before, restored_config, keys):
        raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
    restored = copy.deepcopy(record)
    obs = record['observed']
    restored['observed'] = instances.observe(vmid, record['installation_id'],
        obs['archive_path'], obs['resolved_registry_digest'], obs['image'])
    if restored['observed']['config_sha256'] != sha(restored_config):
        raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
    return restored


def recover(root, journal):
    """Recover through the normal Manage interrupted-operation menu."""
    state = json.loads(journal.read_text())
    record, operation = state['record'], state['operation_plan']
    vmid = record['vmid']
    current = instances.read(root, vmid)
    if (state['kind'] != 'native-modify' or state['phase'] in ('committed', 'rolled-back')
            or current.get('pending_transaction') != str(journal)
            or current.get('transaction_id') != state['id']
            or current['installation_id'] != record['installation_id']):
        raise ValueError(translate('The record does not belong to this operation'))
    before = state['config'].encode()
    now = instances.command('pct', 'config', str(vmid))
    keys = set(operation['values']) | set(operation['delete'])
    if instances.identity(now) != record['installation_id'] or not untouched(before, now, keys):
        raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
    if state.get('after_config'):
        if now not in (before, state['after_config'].encode()):
            raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
    elif now != before:
        # A crash during the PVE API call is recoverable only when the full
        # planned edit is present. Refuse unknown partial/concurrent changes.
        verify_values(now, operation)
    host_mounts.verify_sources(state.get('original_host_sources', {}))
    tx_record = restore_settings(root, record, before, now, operation) if now != before else copy.deepcopy(record)
    if state['was_running']:
        if transaction.run('pct', 'status', str(vmid)).strip() != b'status: running':
            transaction.run('pct', 'start', str(vmid))
        transaction.healthcheck(vmid, record['template'])
    instances.write(instances.location(root, vmid), tx_record)
    state['phase'] = 'rolled-back'
    instances.write(journal, state)
    msg_ok(translate('Previous installation restored'))


def apply(root, record, candidate, config, acknowledge_external_data=False):
    operation = plan(record, candidate, config)
    if not operation:
        raise ValueError(translate('The changes need the application installer'))
    original_sources, desired_sources = transaction.freeze_host_sources(
        record, candidate, acknowledge_external_data)
    vmid = record['vmid']
    folder = instances.location(root, vmid).parent / 'modifications' / uuid.uuid4().hex
    running = transaction.run('pct', 'status', str(vmid)).strip() == b'status: running'
    journal = {'kind': 'native-modify', 'id': folder.name, 'vmid': vmid, 'operation': 'recreate',
               'record': record, 'config': config.decode(), 'operation_plan': operation,
               'phase': 'prepared', 'was_running': running, 'original_host_sources': original_sources}
    instances.write(folder / 'before.json', journal)
    transaction.open_log(folder)
    transaction._run['journal'] = folder / 'before.json'
    pending = copy.deepcopy(record)
    pending.update(status='updating', transaction_id=folder.name, pending_transaction=str(folder / 'before.json'))
    instances.write(instances.location(root, vmid), pending)
    updated_config = None
    changed = False
    try:
        if operation['restart'] and running:
            transaction.stop(vmid)
        # Do not accept a concurrent edit merely because the service stopped.
        if instances.command('pct', 'config', str(vmid)) != config:
            raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
        host_mounts.verify_sources(desired_sources)
        for mount in candidate['deployment'].get('mounts', []):
            if mount['type'] == 'host-bind' and mount.get('create_if_missing'):
                Path(mount['source']).mkdir(parents=True, exist_ok=True)
        host_mounts.verify_sources(original_sources)
        # Capture newly-created directories before installing their mounts.
        pinned = {p: host_mounts.validate_source(p) for p in desired_sources}
        for path, previous in desired_sources.items():
            if previous['exists'] and not host_mounts.same_source(previous, pinned[path]):
                raise ValueError(translate('A shared source does not match its recorded identity'))
        host_mounts.verify_sources(pinned)
        msg_info(translate('Applying container settings without rebuilding the container...'))
        if operation['values'] or operation['delete']:
            changed = True  # API updates may partially succeed before an error.
            set_config(vmid, record['installation_id'], config, operation['values'], operation['delete'])
        updated_config = instances.command('pct', 'config', str(vmid))
        verify_values(updated_config, operation)
        keys = set(operation['values']) | set(operation['delete'])
        if not untouched(config, updated_config, keys):
            raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
        transaction.preflight(candidate, candidate, updated_config, in_place=True, baseline=False)
        journal.update(phase='configured', after_config=updated_config.decode())
        instances.write(folder / 'before.json', journal)
        if operation['restart'] and running:
            transaction.run('pct', 'start', str(vmid))
            transaction.healthcheck(vmid, candidate['template'])
        observed = record['observed']
        fresh = instances.observe(vmid, record['installation_id'], observed['archive_path'],
                                  observed['resolved_registry_digest'], observed['image'])
        host_mounts.verify_observation(pinned, fresh)
        if fresh['config_sha256'] != sha(updated_config):
            raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
        result = copy.deepcopy(record)
        result.update(deployment=copy.deepcopy(candidate['deployment']), observed=fresh)
        instances.write(instances.location(root, vmid), result)
        journal['phase'] = 'committed'
        instances.write(folder / 'before.json', journal)
    except BaseException:
        try:
            now = instances.command('pct', 'config', str(vmid))
            keys = set(operation['values']) | set(operation['delete'])
            if changed:
                if not untouched(config, now, keys) or (updated_config is not None and now != updated_config):
                    raise ValueError('Concurrent edit; rollback refused')
                restored = restore_settings(root, record, config, now, operation)
            else:
                restored = copy.deepcopy(record)
            if operation['restart'] and running:
                if transaction.run('pct', 'status', str(vmid)).strip() != b'status: running':
                    transaction.run('pct', 'start', str(vmid))
                transaction.healthcheck(vmid, record['template'])
            instances.write(instances.location(root, vmid), restored)
            journal['phase'] = 'rolled-back'
            instances.write(folder / 'before.json', journal)
        except Exception as error:
            transaction.log('native rollback failed: '+type(error).__name__)
            msg_warn(translate('The settings could not be fully rolled back. Review the container and its saved modification before continuing.'))
        raise
    try:
        import oci_carried_record
        oci_carried_record.carry(root, vmid, mount_stopped=False)
    except (OSError, ValueError, RuntimeError):
        transaction.log('carried record will be refreshed on the next management entry')
    msg_ok(translate('Changes applied. Data kept.'))
    return folder
