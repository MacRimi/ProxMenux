#!/usr/bin/env python3
"""Register again the OCI applications restored from a backup.

A restored container brings its volumes and its Proxmox configuration, but
not what its installation kept on the host: the record, the private network
of a multi-container application, the hookscript that starts its
dependencies, the includes its configuration points to. This puts them back
for the containers of this node that carry the mark of an installation and
have no record of it here.

The copy of the record a container carries is data the container could have
changed. Nothing is taken from it that the configuration Proxmox restored
does not confirm: the identity, the VMID, the host directories and the
devices. Everything is checked before the host is changed, and an application
that cannot be recovered whole is left as it was found.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile

import oci_carried_record as carried
import oci_console
import oci_instances as instances
import oci_instance_transaction as transaction
import oci_nvidia_refresh
import oci_nvidia_runtime as nvidia
import oci_runtime_settings as runtime_settings
import oci_stack_modify
from oci_host_mounts import capture_sources, validate_source
from oci_accelerators import capture as capture_gpu_devices
from oci_installation_state import parse_config, sha
from oci_ui import msg_error, msg_info, msg_info2, msg_ok, msg_warn, translate

PRIVATE = ipaddress.ip_network('10.77.0.0/16')
ENGINE = Path(__file__).resolve().parent
STACK_HOOK = 'proxmenux-stack-dependencies.sh'
RCLONE_HOOK = re.compile(r':snippets/proxmenux-rclone-[0-9]+-fuse-hook\.sh$')
RCLONE_TEMPLATE = ENGINE.parent / 'catalog' / 'apps' / 'rclone.json'
LIBEXEC = Path('/usr/local/libexec')
# The web port of each host monitor, the only one its firewall rule may allow.
HOST_MONITOR_PORTS = {'glances': 61208, 'netdata': 19999}
HOST_MONITOR = (Path('/etc/pve/proxmenux/host-monitor'), Path('/etc/pve/lxc/proxmenux-host-monitor'))
HOST_MONITOR_CONTENT = 'lxc.namespace.share.pid = 1\nlxc.namespace.share.net = 1\n'
# Containers that carry no copy of their record: there is nothing to recover
# them from, so they are not offered again.
UNRECOVERABLE = '.unrecoverable.json'
# The fields of a record that name a container of the application.
VMID_KEYS = ('vmid', 'primary_vmid', 'base_vmid')


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=300, check=False)


def checked(*args):
    result = run(*args)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ['']
        raise RuntimeError(f"{' '.join(args[:3])}: {detail[0]}")
    return result.stdout


def node():
    return socket.gethostname().split('.', 1)[0]


def local_guests():
    """VMID and saved configuration of every container of this node."""
    result = {}
    for path in (Path('/etc/pve/nodes') / node() / 'lxc').glob('*.conf'):
        if path.stem.isdecimal():
            try:
                result[int(path.stem)] = path.read_text(errors='ignore').split('\n[', 1)[0]
            except OSError:
                continue
    return result


def marker(text):
    match = re.search(r'^#.*proxmenux-instance=([0-9a-f-]{36})(?![0-9a-f-])', text, re.MULTILINE)
    return match[1] if match else None


def registered_identities(root):
    """Installation of every record of this host whose container exists."""
    result = {}
    for vmid in carried.registered(root):
        try:
            record = instances.read(root, vmid)
        except (OSError, ValueError, KeyError):
            continue
        result[vmid] = record['installation_id']
    return result


def unrecoverable(root):
    try:
        value = json.loads((root / UNRECOVERABLE).read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def set_unrecoverable(root, entries):
    value = unrecoverable(root)
    value.update({str(entry['vmid']): entry['installation_id'] for entry in entries})
    guests = local_guests()
    value = {vmid: identity for vmid, identity in value.items()
             if vmid.isdecimal() and marker(guests.get(int(vmid), '')) == identity}
    instances.write(root / UNRECOVERABLE, value)


def pending(root):
    """Containers of this node that carry the mark of an installation and have
    no record of it on this host. A clone of a registered container shares its
    mark and is not one of them."""
    guests = local_guests()
    known = registered_identities(root)
    skipped = unrecoverable(root)
    result = []
    for vmid, text in sorted(guests.items()):
        identity = marker(text)
        if not identity or known.get(vmid) == identity or skipped.get(str(vmid)) == identity:
            continue
        if any(other != vmid and other in guests and marker(guests[other]) == identity
               for other, value in known.items() if value == identity):
            continue
        hostname = re.search(r'^hostname: (.+)$', text, re.MULTILINE)
        result.append({'vmid': vmid, 'installation_id': identity,
                       'hostname': hostname[1].strip() if hostname else f'CT {vmid}'})
    return result


def examine(entry):
    """Read the copy a container carries and check it against its configuration."""
    vmid = entry['vmid']
    result = dict(entry, copy=None, config=None, problem=None, unrecoverable=False, trusted=False)
    done = run('pct', 'config', str(vmid))
    if done.returncode != 0 or instances.identity(done.stdout.encode()) != entry['installation_id']:
        result['problem'] = translate('its configuration could not be read')
        return result
    result['config'] = done.stdout
    with carried.container_root(vmid) as rootfs:
        if rootfs is None:
            result['problem'] = translate('it is locked or its disk could not be mounted')
            return result
        value = carried.read_copy(rootfs)
    # The copy the cluster keeps is the same one when both carry the same
    # mark: it was written with it and no container can change it, so nothing
    # has to be asked. With another mark the content of the container is of
    # another moment, and its own copy is the one that describes it.
    shared = carried.read_cluster(vmid)
    if shared is not None and (shared['record'].get('installation_id') != entry['installation_id']
                               or shared['record'].get('vmid') != vmid):
        shared = None
    if shared is not None and (value is None or value.get('generation') == shared.get('generation')):
        result['trusted'] = value is not None and bool(shared.get('generation'))
        value = shared
    if value is None:
        result['problem'] = translate('its backup was made before ProxMenux kept the record inside the container')
        result['unrecoverable'] = True
        return result
    record = value['record']
    if (record.get('schema_version') != 1 or record.get('installation_id') != entry['installation_id']
            or record.get('status') != 'installed' or not isinstance(record.get('vmid'), int)
            or not isinstance(record.get('deployment'), dict) or not isinstance(record.get('observed'), dict)
            or not isinstance(record['observed'].get('config'), str)):
        result['problem'] = translate('the record it carries does not belong to this container')
        return result
    result['copy'] = value
    return result


def title(record, vmid):
    for template in ((record.get('stack') or {}).get('template') or {}, record.get('template') or {}):
        value = (template.get('catalog_ui') or {}).get('title')
        if isinstance(value, dict):
            value = value.get('en_US') or next(iter(value.values()), '')
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str((record.get('deployment') or {}).get('hostname') or f'CT {vmid}')


def applications(root, found):
    """Group the restored containers by application and say which of its
    containers are here."""
    guests = local_guests()
    where = {}
    for vmid, text in guests.items():
        if marker(text):
            where.setdefault(marker(text), []).append(vmid)
    known = registered_identities(root)
    groups = {}
    for entry in found:
        record = (entry['copy'] or {}).get('record') or {}
        key = (record.get('stack_member') or {}).get('stack_id') or entry['installation_id']
        groups.setdefault(key, []).append(entry)
    plans = []
    for key, entries in groups.items():
        by_identity = {entry['installation_id']: entry for entry in entries}
        primary = by_identity.get(key)
        plan = {'key': key, 'restored': entries, 'blockers': [], 'notes': [], 'hold': False, 'bridges': {}, 'renumbered': {},
                'primary': None, 'members': [], 'title': None}
        for entry in entries:
            if entry['problem']:
                plan['blockers'].append(f"CT {entry['vmid']}: {entry['problem']}")
        stack = None
        if primary and primary['copy']:
            plan['primary'] = primary['vmid']
            plan['title'] = title(primary['copy']['record'], primary['vmid'])
            stack = primary['copy']['record'].get('stack')
        elif key not in by_identity:
            # Only some containers of the application were restored; the main
            # one still has its record here.
            primary_id = next((vmid for vmid, value in known.items() if value == key), None)
            if primary_id is None:
                plan['blockers'].append(translate('The main container of this application is not on this host. Restore it too.'))
            else:
                record = instances.read(root, primary_id)
                plan['primary'], plan['title'], stack = primary_id, title(record, primary_id), record.get('stack')
        expected = [(member.get('vmid'), member.get('installation_id'),
                     (member.get('stack_member') or {}).get('name')) for member in (stack or {}).get('members', [])]
        if not expected:
            expected = [((entry['copy'] or {}).get('record', {}).get('vmid', entry['vmid']),
                         entry['installation_id'], None) for entry in entries]
        plan['title'] = plan['title'] or entries[0]['hostname']
        for vmid, identity, name in expected:
            present = where.get(identity, [])
            member = {'vmid': vmid, 'name': name, 'installation_id': identity,
                      'state': 'restored' if identity in by_identity else 'registered'}
            label = f"CT {vmid}" + (f" ({name})" if name else '')
            if not present:
                member['state'] = 'absent'
                plan['blockers'].append(f"{label}: {translate('this container of the application is not on this host. Restore it too.')}")
            elif len(present) > 1:
                plan['blockers'].append(f"{label}: {translate('several containers of this host carry the same installation:')} "
                                        f"{', '.join(f'CT {v}' for v in sorted(present))}")
            elif present[0] != vmid and member['state'] == 'restored':
                plan['renumbered'][vmid] = present[0]
                member.update(vmid=present[0], recorded=vmid)
            elif member['state'] == 'registered' and known.get(vmid) != identity:
                member['state'] = 'absent'
                plan['blockers'].append(f"{label}: {translate('its record is missing and it was not found among the restored containers')}")
            plan['members'].append(member)
        for entry in entries:
            if entry['copy'] and entry['installation_id'] not in {identity for _, identity, _ in expected}:
                plan['blockers'].append(f"CT {entry['vmid']}: {translate('the record of the application does not list this container')}")
        if plan['renumbered'] and not plan['blockers']:
            renumber_plan(plan)
        plans.append(plan)
    return sorted(plans, key=lambda plan: min(entry['vmid'] for entry in plan['restored']))


def renumber(value, mapping):
    """The same value with the containers of the application under the IDs
    they have on this host. Only the fields that name a container change: a
    timeout of 120 seconds is not CT 120."""
    if isinstance(value, dict):
        return {key: mapping.get(item, item) if key in VMID_KEYS and type(item) is int
                else renumber(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [renumber(item, mapping) for item in value]
    return value


def renumbered_lines(text, old, new):
    """The lines of a configuration that carry the ID of the container: its
    console log, the hook that marks each start in it, its sysctl include and
    the hookscript of an Rclone mount. Proxmox renames the volumes itself."""
    swaps = {f'lxc.console.logfile: {oci_console.log_path(old)}': f'lxc.console.logfile: {oci_console.log_path(new)}',
             oci_console.start_mark_hook(old): oci_console.start_mark_hook(new),
             f'lxc.include: {runtime_settings.include_path(old)}': f'lxc.include: {runtime_settings.include_path(new)}',
             f'lxc.include: {runtime_settings.legacy_include_path(old)}': f'lxc.include: {runtime_settings.include_path(new)}'}
    hook = re.compile(rf'(hookscript: \S+:snippets/proxmenux-rclone-){int(old)}(-fuse-hook\.sh)')
    lines = [hook.sub(rf'\g<1>{int(new)}\g<2>', swaps.get(line, line)) if line.startswith('hookscript: ')
             else swaps.get(line, line) for line in text.split('\n')]
    return '\n'.join(lines)


def renumber_plan(plan):
    """A container restored with another ID keeps its application: the copy
    of the record is read with the IDs of this host."""
    mapping = plan['renumbered']
    for entry in plan['restored']:
        if not entry['copy']:
            continue
        recorded = entry['copy']['record']['vmid']
        value = renumber(entry['copy'], mapping)
        record = value['record']
        if recorded != entry['vmid']:
            entry['recorded'] = recorded
            observed = record['observed']
            observed['config'] = renumbered_lines(observed['config'], recorded, entry['vmid'])
            arguments = record['deployment'].get('create_arguments')
            if isinstance(arguments, list) and arguments[:1] == [str(recorded)]:
                arguments[0] = str(entry['vmid'])
        entry['copy'] = value


def renumber_config(entry):
    """Point the configuration of a container restored with another ID at its
    own console log and sysctl include; the ones it names belong to the ID it
    had, which another container of this host may be using."""
    recorded, vmid = entry.get('recorded'), entry['vmid']
    if recorded is None or recorded == vmid:
        return
    conf = Path('/etc/pve/nodes') / node() / 'lxc' / f'{vmid}.conf'
    text = conf.read_text()
    current, separator, snapshots = text.partition('\n[')
    rebuilt = renumbered_lines(current, recorded, vmid) + separator + snapshots
    if rebuilt != text:
        conf.write_text(rebuilt)
    entry['config'] = checked('pct', 'config', str(vmid))


def host_addresses():
    """IPv4 networks configured on each interface of the host."""
    try:
        links = json.loads(checked('ip', '-j', '-4', 'address', 'show'))
    except (RuntimeError, ValueError):
        return {}
    result = {}
    for link in links:
        result[link['ifname']] = [ipaddress.ip_interface(f"{item['local']}/{item['prefixlen']}")
                                  for item in link.get('addr_info', []) if item.get('family') == 'inet']
    return result


def links():
    return set(re.findall(r'^\d+: ([^:@]+)', checked('ip', '-o', 'link', 'show'), re.MULTILINE))


def defined_network(bridge):
    """The network a bridge has in the configuration of the node, when it is
    defined there and not active."""
    result = run('pvesh', 'get', f'/nodes/{node()}/network/{bridge}', '--output-format', 'json')
    if result.returncode != 0:
        return None
    try:
        return ipaddress.ip_interface(json.loads(result.stdout).get('cidr') or '').network
    except ValueError:
        return False


def routed_networks():
    try:
        routes = json.loads(checked('ip', '-j', '-4', 'route', 'show'))
    except (RuntimeError, ValueError):
        return []
    result = []
    for route in routes:
        with contextlib.suppress(ValueError):
            if route.get('dst') != 'default':
                result.append((route.get('dev', ''), ipaddress.ip_network(route['dst'], strict=False)))
    return result


def networks(config):
    for key, value in parse_config(config.encode()).items():
        if re.fullmatch(r'net[0-9]+', key):
            options = dict(part.split('=', 1) for part in value.split(',') if '=' in part)
            address = None
            try:
                address = ipaddress.ip_interface(options.get('ip', ''))
            except ValueError:
                pass
            yield key, options.get('bridge'), address


def check_networks(plan):
    """The bridges the containers are attached to. A private network of
    ProxMenux that is missing is created again with the same subnet; it is
    never moved to another one, because the containers reach each other by
    fixed addresses."""
    present, addresses, routes = links(), host_addresses(), routed_networks()
    members = {entry['vmid'] for entry in plan['restored']} | {m['vmid'] for m in plan['members']}
    others = {vmid: text for vmid, text in local_guests().items() if vmid not in members}
    for entry in plan['restored']:
        if not entry['config']:
            continue
        for key, bridge, address in networks(entry['config']):
            if not bridge:
                continue
            private = (address is not None and address.version == 4 and address.ip in PRIVATE
                       and re.fullmatch(r'vmbr[0-9]+', bridge))
            label = f"CT {entry['vmid']} {key}"
            if private:
                subnet = address.network
                if any(re.search(rf'(?:^|,)ip={re.escape(str(address.ip))}/', text, re.MULTILINE)
                       for text in others.values()):
                    plan['blockers'].append(f"{label}: {translate('another container of this host already uses the address')} {address.ip}")
                if bridge in present:
                    if not any(item.network == subnet for item in addresses.get(bridge, [])) \
                            and plan['bridges'].get(bridge) != subnet:
                        plan['blockers'].append(
                            f"{label}: {translate('the bridge exists on this host with another network:')} {bridge}. "
                            f"{translate('The application needs it for')} {subnet}.")
                    continue
                if plan['bridges'].setdefault(bridge, subnet) != subnet:
                    plan['blockers'].append(f"{label}: {translate('the containers do not agree on the private network of')} {bridge}")
                    continue
                defined = defined_network(bridge)
                if defined is not None and defined != subnet:
                    plan['blockers'].append(
                        f"{label}: {translate('the bridge exists on this host with another network:')} {bridge}. "
                        f"{translate('The application needs it for')} {subnet}.")
                    continue
                used = sorted({f'{name} ({network})' for name, network in routes if network.overlaps(subnet)}
                              | {f'{name} ({item.network})' for name, items in addresses.items() for item in items
                                 if item.network.overlaps(subnet)})
                if used:
                    plan['blockers'].append(
                        f"{translate('The private network of the application is already in use on this host:')} "
                        f"{subnet} — {', '.join(used)}. {translate('Its addresses are fixed and are not changed.')}")
            elif bridge not in present and defined_network(bridge) is None:
                plan['blockers'].append(
                    f"{label}: {translate('the bridge does not exist on this host:')} {bridge}. "
                    f"{translate('Choose another bridge for the container in Proxmox (Network) and run the recovery again.')}")


def check_host_resources(plan):
    """Host directories, devices, includes and hooks the configuration of
    each container points to."""
    for entry in plan['restored']:
        if not entry['config'] or not entry['copy']:
            continue
        vmid, label = entry['vmid'], f"CT {entry['vmid']}"
        values = parse_config(entry['config'].encode())
        deployment = entry['copy']['record']['deployment']
        directories = [value.split(',', 1)[0] for key, value in values.items()
                       if re.fullmatch(r'mp[0-9]+', key) and value.startswith('/')]
        devices = [oci_stack_modify.device_path(value) for key, value in values.items()
                   if re.fullmatch(r'dev[0-9]+', key)]
        for path in directories:
            if not os.path.isdir(path):
                plan['blockers'].append(
                    f"{label}: {translate('the host directory does not exist:')} {path}. "
                    f"{translate('Mount or create it with its data and run the recovery again.')}")
        for path in devices:
            if not os.path.exists(path):
                plan['blockers'].append(
                    f"{label}: {translate('the device does not exist on this host:')} {path}. "
                    f"{translate('Connect it, or remove it from the container in Proxmox (Resources), and run the recovery again.')}")
        lines = entry['config'].splitlines()
        if any(carried.NVIDIA_HOOK.fullmatch(line.partition(': ')[2]) for line in lines
               if line.startswith('lxc.hook.mount: ')) or any(path.startswith('/dev/nvidia') for path in devices):
            if run('nvidia-smi', '-L').returncode != 0 or run('which', 'nvidia-container-cli').returncode != 0:
                plan['blockers'].append(
                    f"{label}: {translate('it uses an NVIDIA GPU and this host has no working NVIDIA driver and Container Toolkit. Install them and run the recovery again.')}")
        for line in lines:
            key, _, value = line.partition(': ')
            if key == 'lxc.hook.mount' and value:
                hook = carried.NVIDIA_HOOK.fullmatch(value)
                if not hook:
                    plan['blockers'].append(f"{label}: {translate('unknown mount hook:')} {value}")
                elif not Path(value).is_file() and nvidia_hook_source(entry, hook[1]) is None:
                    plan['blockers'].append(f"{label}: {translate('the NVIDIA hook of the container is not available:')} {value}")
        # A privileged container carries one line per file of the driver of
        # the host it was installed on; they are written again for this one.
        nvidia_devices = any(path.startswith('/dev/nvidia') for path in devices)
        hooked = any(carried.NVIDIA_HOOK.fullmatch(line.partition(': ')[2]) for line in lines
                     if line.startswith('lxc.hook.mount: '))
        saved = (entry['copy']['record']['observed'].get('gpu_devices') or {}).get(nvidia.KEY)
        if nvidia_devices and not hooked and isinstance(saved, dict):
            entry['nvidia_static'] = saved
        for line in lines:
            key, _, value = line.partition(': ')
            if key != 'lxc.include':
                continue
            path = Path(value)
            if path in HOST_MONITOR:
                if path.exists() and path.read_text() != HOST_MONITOR_CONTENT:
                    plan['blockers'].append(f"{label}: {translate('a different host monitor include already exists:')} {path}")
            elif path in [include(number) for number in {vmid, entry.get('recorded', vmid)}
                          for include in (runtime_settings.include_path, runtime_settings.legacy_include_path)]:
                try:
                    content = runtime_settings.sysctl_content(deployment)
                except (ValueError, KeyError, TypeError):
                    content = ''
                # With another ID the include is written again under its own name.
                if entry.get('recorded', vmid) != vmid:
                    path = runtime_settings.include_path(vmid)
                if not content:
                    plan['blockers'].append(f"{label}: {translate('the settings of its include are not in the record:')} {path}")
                elif path.exists() and path.read_text() != content:
                    plan['blockers'].append(f"{label}: {translate('its include exists with other content:')} {path}")
            else:
                plan['blockers'].append(f"{label}: {translate('unknown include:')} {path}")
        hookscript = values.get('hookscript', '')
        if hookscript.endswith(f':snippets/{STACK_HOOK}'):
            dependents = {member['vmid'] for member in plan['members']} - {vmid}
            candidates = [entry['copy'].get('stack_contract')]
            current = Path(carried.STACK_CONTRACT.format(vmid))
            if current.is_file():
                with contextlib.suppress(OSError, ValueError):
                    candidates.append(json.loads(current.read_text()))
            contract = next((value for value in candidates if valid_contract(value, dependents)), None)
            if contract is None:
                plan['blockers'].append(f"{label}: {translate('the start order of its dependencies is not in the record')}")
            entry['contract'] = contract
        elif RCLONE_HOOK.search(hookscript):
            mount = rclone_mount(entry['copy'].get('rclone_mount'))
            if mount is not None:
                entry['rclone'] = mount
                plan['notes'].append(
                    f"{label}: {translate('its Rclone mount is published again on this host at')} "
                    f"{mount['shared_mount_root']}/{mount['mount_name']} "
                    f"{translate('and, read-only, at')} {mount['shared_mount_read_only_root']}/{mount['mount_name']}")
            elif not (carried.SNIPPETS / hookscript.rsplit('/', 1)[-1]).is_file():
                plan['hold'] = True
                plan['notes'].append(
                    f"{label}: {translate('its Rclone mount is published by a host script that a backup does not include. Enable the mount again from the Rclone entry of the catalog before starting it.')}")
        elif hookscript:
            path = run('pvesm', 'path', hookscript)
            if path.returncode != 0 or not Path(path.stdout.strip()).is_file():
                plan['blockers'].append(f"{label}: {translate('its hookscript does not exist on this host:')} {hookscript}")
        if deployment.get('host_firewall'):
            rule = firewall_rule(entry, [line for line in lines if line.startswith('lxc.include: ')])
            if rule is None:
                plan['notes'].append(
                    f"{label}: {translate('the host firewall rule of the installation is not added again; allow its port in the firewall of this host if you use it.')}")
            else:
                entry['firewall'] = rule


def firewall_rule(entry, includes):
    """The rule a host monitor had in the host firewall, for this host: its
    own web port, from the subnet its bridge has here. It is added only when
    the user confirms it again."""
    deployment = entry['copy']['record']['deployment']
    saved = deployment.get('host_firewall')
    port = HOST_MONITOR_PORTS.get(deployment.get('host_monitor'))
    if (not isinstance(saved, dict) or port is None or saved.get('port') != port or saved.get('protocol') != 'tcp'
            or not any(Path(line.partition(': ')[2]) in HOST_MONITOR for line in includes)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', str(saved.get('bridge')))):
        return None
    addresses = host_addresses().get(saved['bridge'], [])
    if not addresses:
        return None
    return {'vmid': entry['vmid'], 'port': port, 'source': str(addresses[0].network),
            'comment': f"ProxMenux OCI firewall {entry['installation_id']}"}


def add_firewall_rule(rule):
    """Returns whether the rule is in the host firewall when it ends."""
    path = f'/nodes/{node()}/firewall/rules'
    try:
        rules = json.loads(checked('pvesh', 'get', path, '--output-format', 'json'))
        if any(str(item.get('type', '')).lower() == 'in' and str(item.get('action', '')).upper() == 'ACCEPT'
               and str(item.get('proto', '')).lower() == 'tcp' and item.get('source') == rule['source']
               and str(item.get('dport')) == str(rule['port']) for item in rules):
            return True
        checked('pvesh', 'create', path, '--type', 'in', '--action', 'ACCEPT', '--proto', 'tcp',
                '--dport', str(rule['port']), '--source', rule['source'], '--enable', '1',
                '--comment', rule['comment'])
    except (RuntimeError, ValueError):
        return False
    return True


def rclone_mount(value):
    """The parameters of an Rclone mount the container carries, when they
    describe a mount this host can publish: a plain name and views inside a
    common root that is not a system directory. The scripts come from the
    engine, never from the container."""
    keys = ('mount_name', 'shared_mount_root', 'shared_mount_read_only_root', 'shared_mount_root_parent')
    if not isinstance(value, dict) or not all(isinstance(value.get(key), str) for key in keys):
        return None
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', value['mount_name']) or value['mount_name'] in ('.', '..'):
        return None
    parent = value['shared_mount_root_parent']
    for key in keys[1:]:
        path = value[key]
        if (not path.startswith('/') or path == '/' or '..' in Path(path).parts or re.search(r'[\s,]', path)
                or os.path.normpath(path) != path):
            return None
    if not all(value[key].startswith(parent + '/') for key in keys[1:3]):
        return None
    try:
        validate_source(parent, allow_missing=True)
        assets = json.loads(RCLONE_TEMPLATE.read_text())['proxmox']['laboratory_contract']['generated_assets']
        assets['proxmox-hookscript']['content_template'], assets['mount-publication-waiter']['content']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not (ENGINE / 'rclone_mount_publish.py').is_file():
        return None
    return {key: value[key] for key in keys}


def ensure_local_snippets():
    """A new Proxmox installation accepts no snippets on `local`."""
    listed = run('pvesm', 'status', '--content', 'snippets').stdout.splitlines()[1:]
    if any(line.split()[:1] == ['local'] for line in listed):
        return
    content = json.loads(checked('pvesh', 'get', '/storage/local', '--output-format', 'json')).get('content')
    if not content:
        raise RuntimeError(translate('The local storage does not accept snippets'))
    checked('pvesm', 'set', 'local', '--content', f'{content},snippets')


def restore_rclone_mount(entry):
    """Write again what an Rclone mount keeps on the host: the hookscript of
    the container and the two programs that publish its mount."""
    mount, vmid = entry['rclone'], entry['vmid']
    assets = json.loads(RCLONE_TEMPLATE.read_text())['proxmox']['laboratory_contract']['generated_assets']
    hook = assets['proxmox-hookscript']['content_template']
    for key in ('mount_name', 'shared_mount_root', 'shared_mount_read_only_root', 'shared_mount_root_parent'):
        hook = hook.replace('{{' + key + '}}', mount[key])
    ensure_local_snippets()
    name = f'proxmenux-rclone-{vmid}-fuse-hook.sh'
    for directory in (LIBEXEC, carried.SNIPPETS, Path(mount['shared_mount_root_parent']),
                      Path(mount['shared_mount_root']) / mount['mount_name'],
                      Path(mount['shared_mount_read_only_root']) / mount['mount_name']):
        directory.mkdir(parents=True, exist_ok=True, mode=0o755)
    for path, content in ((LIBEXEC / 'proxmenux-oci-mount-publish', (ENGINE / 'rclone_mount_publish.py').read_text()),
                          (LIBEXEC / 'proxmenux-oci-mount-wait', assets['mount-publication-waiter']['content'] + '\n'),
                          (carried.SNIPPETS / name, hook + '\n')):
        if path.is_symlink():
            raise ValueError(f"{translate('A host script is not written over a symbolic link:')} {path}")
        path.write_text(content)
        path.chmod(0o755)
    volume = f'local:snippets/{name}'
    if parse_config(entry['config'].encode()).get('hookscript') != volume:
        checked('pct', 'set', str(vmid), '--hookscript', volume)
        entry['config'] = checked('pct', 'config', str(vmid))


def valid_contract(contract, dependents):
    if not isinstance(contract, dict) or contract.get('schema') != 1:
        return False
    dependencies = contract.get('dependencies')
    if not isinstance(dependencies, list) or not dependencies:
        return False
    for item in dependencies:
        check = item.get('healthcheck') if isinstance(item, dict) else None
        if (not isinstance(check, dict) or type(item.get('vmid')) is not int or item['vmid'] not in dependents
                or not isinstance(item.get('label'), str) or type(check.get('timeout_seconds')) is not int
                or check['timeout_seconds'] < 1):
            return False
        if check.get('type') == 'exec':
            argv = check.get('argv')
            if not isinstance(argv, list) or not argv or not all(isinstance(part, str) for part in argv):
                return False
        elif check.get('type') == 'http':
            match = re.fullmatch(r'https?://([0-9.]+)(?::[0-9]+)?(?:/\S*)?', str(check.get('url')))
            try:
                if not match or ipaddress.ip_address(match[1]) not in PRIVATE:
                    return False
            except ValueError:
                return False
        elif check.get('type') != 'running':
            return False
    return True


def nvidia_hook_source(entry, digest):
    """The hook the configuration names by its hash: the one of this engine,
    or the one the container carries when it is that same file."""
    shipped = ENGINE / 'nvidia_lxc_mount_lab.sh'
    if shipped.is_file() and sha(shipped.read_bytes()) == digest:
        return shipped.read_text()
    saved = (entry['copy'] or {}).get('nvidia_hook') or {}
    content = saved.get('content')
    if isinstance(content, str) and sha(content.encode()) == digest:
        return content
    return None


def check_records(root, plan):
    for entry in plan['restored']:
        path = instances.location(root, entry['vmid'])
        if not path.exists():
            continue
        try:
            previous = instances.read(root, entry['vmid'])
        except (OSError, ValueError, KeyError):
            plan['blockers'].append(f"CT {entry['vmid']}: {translate('this host keeps an unreadable record for this ID')}")
            continue
        if previous.get('status') in instances.ACTIVE or previous.get('pending_transaction') \
                or previous.get('pending_stack_transaction'):
            plan['blockers'].append(f"CT {entry['vmid']}: {translate('this host keeps a record of another installation with an operation pending')}")


def prepare(root):
    """Every restored application of this node, with what prevents its
    recovery and what the user has to know."""
    plans = applications(root, [examine(entry) for entry in pending(root)])
    for plan in plans:
        check_records(root, plan)
        if not plan['blockers']:
            check_networks(plan)
            check_host_resources(plan)
        # Two containers on the same network report the same problem.
        for key in ('blockers', 'notes'):
            plan[key] = list(dict.fromkeys(plan[key]))
    return plans


def create_bridge(bridge, subnet):
    address = f'{subnet.network_address + 1}/{subnet.prefixlen}'
    if run('pvesh', 'get', f'/nodes/{node()}/network/{bridge}').returncode != 0:
        checked('pvesh', 'create', f'/nodes/{node()}/network', '--iface', bridge, '--type', 'bridge',
                '--autostart', '1', '--cidr', address)
    if run('ip', 'link', 'show', bridge).returncode != 0:
        checked('ip', 'link', 'add', 'name', bridge, 'type', 'bridge')
        checked('ip', 'address', 'add', address, 'dev', bridge)
        checked('ip', 'link', 'set', bridge, 'up')
    if not any(item.network == subnet for item in host_addresses().get(bridge, [])):
        raise RuntimeError(f"{translate('The private bridge does not have the expected address:')} {bridge} ({address})")


def restore_host_files(entry):
    vmid = entry['vmid']
    deployment = entry['copy']['record']['deployment']
    renumber_config(entry)
    for line in entry['config'].splitlines():
        key, _, value = line.partition(': ')
        if key == 'lxc.include':
            path = Path(value)
            if path.exists():
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if path in HOST_MONITOR:
                path.write_text(HOST_MONITOR_CONTENT)
            elif path == runtime_settings.include_path(vmid):
                runtime_settings.restore(deployment, vmid)
            else:
                path.write_text(runtime_settings.sysctl_content(deployment))
        elif key == 'lxc.hook.mount' and value and not Path(value).is_file():
            content = nvidia_hook_source(entry, carried.NVIDIA_HOOK.fullmatch(value)[1])
            Path(value).parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            Path(value).write_text(content)
            Path(value).chmod(0o755)
    if entry.get('rclone'):
        restore_rclone_mount(entry)
    if entry.get('contract'):
        with tempfile.NamedTemporaryFile('w', suffix='.json') as file:
            json.dump(entry['contract'], file)
            file.flush()
            checked('bash', str(ENGINE / 'stack_dependency_hook.sh'), '--install', str(vmid), file.name)


def clean_format_directories(entry):
    """A restore formats the volumes again, and the `lost+found` of each new
    one belongs to the host: an application that walks its data cannot enter
    it and fails to start."""
    mounts = []
    for key, value in parse_config(entry['config'].encode()).items():
        if re.fullmatch(r'mp[0-9]+', key) and not value.startswith('/'):
            target = oci_stack_modify.options(value).get('mp')
            if target:
                mounts.append({'type': 'managed-volume', 'backup': True, 'container_path': target})
    if not mounts:
        return
    with carried.container_root(entry['vmid']) as rootfs:
        if rootfs is not None:
            transaction.remove_empty_format_directories(rootfs, {'mounts': mounts})


def volume_options(value):
    return sorted(part for part in value.split(',')[1:] if not part.startswith('size=')), \
        next((part for part in value.split(',')[1:] if part.startswith('size=')), None)


def restore_related(key, before, now):
    """Whether a difference between two values of a configuration key is what
    a restore changes: where a volume is, the hardware address of an
    interface, or a host directory or a device taken away because this host
    lacks it."""
    if now is None:
        return before is not None and bool(re.fullmatch(r'dev[0-9]+', key)
                                           or (re.fullmatch(r'mp[0-9]+', key) and before.startswith('/')))
    if before is None:
        return False
    if key == 'rootfs' or re.fullmatch(r'mp[0-9]+', key):
        return not before.startswith('/') and not now.startswith('/') \
            and volume_options(before) == volume_options(now)
    if re.fullmatch(r'net[0-9]+', key):
        def without_address(value):
            return sorted(part for part in value.split(',') if not part.startswith('hwaddr='))
        return without_address(before) == without_address(now)
    if key == 'hookscript':
        return before.rsplit(':', 1)[-1] == now.rsplit(':', 1)[-1]
    return False


def adopt_storage(deployment, values):
    """Point the plan of the application at the storage its volumes are on now."""
    def storage(value):
        source = value.split(',', 1)[0]
        return source.split(':', 1)[0] if ':' in source and not source.startswith('/') else None

    current = storage(values.get('rootfs', ''))
    if current and isinstance(deployment.get('rootfs'), dict) and deployment['rootfs'].get('storage'):
        deployment['rootfs']['storage'] = current
    targets = {oci_stack_modify.options(value).get('mp'): storage(value)
               for key, value in values.items() if re.fullmatch(r'mp[0-9]+', key)}
    for mount in deployment.get('mounts', []):
        source = mount.get('source')
        if (mount.get('type') == 'managed-volume' and isinstance(source, str) and ':' not in source
                and targets.get(mount.get('container_path'))):
            mount['source'] = targets[mount['container_path']]


def standalone_record(entry):
    """The record of a single-container application for this host. What a
    restore changes becomes the new reference; any other difference with the
    configuration stays as one, for the next update to treat as it would on
    the host the container comes from."""
    record = copy.deepcopy(entry['copy']['record'])
    config = entry['config'].encode()
    previous = record['observed']
    before, now = parse_config(previous['config'].encode()), parse_config(config)
    changed = {key for key in before.keys() | now.keys() if before.get(key) != now.get(key)}
    if instances.identity(previous['config'].encode()) == record['installation_id']:
        changed.discard('description')
    related = {key for key in changed if restore_related(key, before.get(key), now.get(key))}
    deployment = record['deployment']
    adopt_storage(deployment, now)
    # Only what Proxmox restored: the copy is not trusted to add a host
    # directory or a device to the container.
    attached = {oci_stack_modify.device_path(value) for key, value in now.items() if re.fullmatch(r'dev[0-9]+', key)}
    shared = {os.path.normpath(value.split(',', 1)[0]) for key, value in now.items()
              if re.fullmatch(r'mp[0-9]+', key) and value.startswith('/')}
    if isinstance(deployment.get('devices'), list):
        deployment['devices'] = [device for device in deployment['devices']
                                 if device.get('kind') != 'character-device' or device.get('host_path') in attached]
    if isinstance(deployment.get('mounts'), list):
        deployment['mounts'] = [mount for mount in deployment['mounts'] if mount.get('type') != 'host-bind'
                                or os.path.normpath(str(mount.get('source'))) in shared]
    if entry.get('firewall') and isinstance(deployment.get('host_firewall'), dict):
        deployment['host_firewall']['source'] = entry['firewall']['source']
    if changed == related:
        record['observed'] = instances.observe(entry['vmid'], record['installation_id'], previous.get('archive_path'),
                                               previous.get('resolved_registry_digest'), previous.get('image'))
        if entry.get('nvidia_static'):
            # The driver files the configuration names are those of the host
            # the container comes from, until they are rebuilt for this one.
            record['observed'].setdefault('gpu_devices', {})[nvidia.KEY] = entry['nvidia_static']
        return record
    lines = []
    for line in previous['config'].splitlines():
        key = line.partition(': ')[0]
        if key in related and ': ' in line:
            if now.get(key) is not None:
                lines.append(f'{key}: {now[key]}')
            continue
        lines.append(line)
    patched = ('\n'.join(lines) + '\n').encode()
    observed = dict(previous, config=patched.decode(), config_sha256=sha(patched))
    observed.pop('api_config_sha256', None)
    for name, capture in (('host_bind_sources', capture_sources), ('gpu_devices', capture_gpu_devices)):
        value = capture(config)
        if value:
            observed[name] = value
        else:
            observed.pop(name, None)
    record['observed'] = observed
    return record


def register(root, plan):
    """Write the records of the application. Either all of them are left
    registered or none is."""
    written = []
    try:
        for entry in plan['restored']:
            vmid = entry['vmid']
            record = entry['copy']['record']
            stack = bool(record.get('stack') or record.get('stack_member'))
            value = copy.deepcopy(record) if stack else standalone_record(entry)
            if stack:
                adopt_storage(value['deployment'], parse_config(entry['config'].encode()))
            path = instances.location(root, vmid)
            if path.exists():
                previous = instances.read(root, vmid)
                path.replace(path.with_name(f"retired-{previous['installation_id']}.json"))
            value['recovered_at'] = instances.now()
            value['recovered_from'] = {'node': entry['copy'].get('node'), 'saved_at': entry['copy'].get('saved_at')}
            instances.write(path, value)
            written.append((vmid, stack))
        for vmid, stack in written:
            if stack:
                # A member is recorded as it is now, the way a recreation
                # leaves it; this also proves the stack can still be updated.
                oci_stack_modify.register(root, vmid)
        refresh_service_plans(root, [vmid for vmid, stack in written if stack])
    except BaseException:
        for vmid, _ in written:
            path = instances.location(root, vmid)
            if path.exists():
                path.unlink()
        raise
    return [vmid for vmid, _ in written]


def refresh_service_plans(root, vmids):
    """The main container of an application that was never updated keeps the
    plan each container was installed with. It is left as the containers are
    now, so it names no volume or ID of the host they come from."""
    for vmid in vmids:
        record = instances.read(root, vmid)
        services = ((record.get('stack') or {}).get('deployment') or {}).get('services') or []
        changed = False
        members = (record.get('stack') or {}).get('members') or []
        for index, member in enumerate(members):
            if not isinstance(member, dict) or member.get('vmid') == vmid:
                continue
            try:
                current = instances.read(root, member.get('vmid'))
            except (OSError, ValueError, KeyError, TypeError):
                continue
            current.pop('stack', None)
            if current.get('installation_id') == member.get('installation_id') and current != member:
                members[index] = current
                changed = True
        for service in services:
            if not isinstance(service, dict) or 'deployment' not in service:
                continue
            try:
                member = record if service.get('vmid') == vmid else instances.read(root, service.get('vmid'))
            except (OSError, ValueError, KeyError, TypeError):
                continue
            service['deployment'] = copy.deepcopy(member['deployment'])
            changed = True
        if changed:
            instances.write(instances.location(root, vmid), record)


def start_order(entry):
    order = re.search(r'^startup: .*?order=([0-9]+)', entry['config'], re.MULTILINE)
    return int(order[1]) if order else 9999


def recover(root, plan, start=False, host_firewall=()):
    for bridge, subnet in plan['bridges'].items():
        msg_info(f"{translate('Creating the private network...')} {bridge}")
        create_bridge(bridge, subnet)
        msg_ok(f"{translate('Private network:')} {bridge} ({subnet})")
    for recorded, vmid in sorted(plan['renumbered'].items()):
        msg_ok(f"CT {recorded} {translate('is now')} CT {vmid}")
    for entry in plan['restored']:
        restore_host_files(entry)
        clean_format_directories(entry)
    if any(entry.get('contract') for entry in plan['restored']):
        msg_ok(translate('Start order of the dependencies restored'))
    msg_info(translate('Saving the record of the application...'))
    vmids = register(root, plan)
    for entry in plan['restored']:
        if not entry.get('nvidia_static'):
            continue
        try:
            if oci_nvidia_refresh.rebuild(root, entry['vmid']):
                msg_ok(f"CT {entry['vmid']}: {translate('NVIDIA runtime rebuilt for the driver of this host')}")
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
            plan['hold'] = True
            plan['notes'].append(f"CT {entry['vmid']}: {translate('its NVIDIA runtime could not be rebuilt for the driver of this host; the container will not start until it is installed again:')} {error}")
    for vmid in vmids:
        carried.carry(root, vmid, adopted=True)
    msg_ok(f"{translate('Application registered on this host:')} {', '.join(f'CT {vmid}' for vmid in vmids)}")
    for entry in plan['restored']:
        rule = entry.get('firewall')
        if not rule:
            continue
        text = f"TCP {rule['port']} {translate('from')} {rule['source']}"
        # Each rule is confirmed on its own; one answer does not cover the rest.
        if rule['vmid'] not in host_firewall:
            plan['notes'].append(f"CT {entry['vmid']}: {translate('its host firewall rule was not added:')} {text}")
        elif add_firewall_rule(rule):
            msg_ok(f"{translate('Host firewall rule added:')} {text}")
        else:
            msg_warn(f"{translate('Could not add the confirmed host firewall rule')}: {text}")
    if start and not plan['hold']:
        for entry in sorted(plan['restored'], key=start_order):
            if 'running' in run('pct', 'status', str(entry['vmid'])).stdout:
                continue
            msg_info(f"{translate('Starting the container...')} CT {entry['vmid']}")
            started = run('pct', 'start', str(entry['vmid']))
            if started.returncode != 0:
                detail = (started.stderr or started.stdout).strip().splitlines()[-1:] or ['']
                msg_warn(f"CT {entry['vmid']}: {translate('it could not be started:')} {detail[0]}")
                break
            msg_ok(f"{translate('Container started')}: CT {entry['vmid']}")


def automatic(plan):
    """Whether the application can be registered without asking: every record
    comes from the copy of the cluster, and nothing else has to be created,
    confirmed or reviewed on this host. It is the case of a container that
    migrated to this node."""
    return (not plan['blockers'] and not plan['bridges'] and not plan['renumbered'] and not plan['hold']
            and all(entry.get('trusted') and not entry.get('firewall') and not entry.get('rclone')
                    and not entry.get('contract') and not entry.get('nvidia_static') for entry in plan['restored']))


def describe(plan):
    return {'key': plan['key'], 'title': plan['title'], 'primary': plan['primary'],
            'containers': [{'vmid': entry['vmid'], 'hostname': entry['hostname']} for entry in plan['restored']],
            'members': [{'vmid': m['vmid'], 'name': m['name'], 'state': m['state']} for m in plan['members']],
            'bridges': {bridge: str(subnet) for bridge, subnet in plan['bridges'].items()},
            'renumbered': {str(recorded): vmid for recorded, vmid in plan['renumbered'].items()},
            'automatic': automatic(plan),
            'firewall': [{key: entry['firewall'][key] for key in ('vmid', 'port', 'source')}
                         for entry in plan['restored'] if entry.get('firewall')],
            'blockers': plan['blockers'], 'notes': plan['notes']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('list', 'plan', 'recover'))
    parser.add_argument('--root', type=Path, default=instances.ROOT)
    parser.add_argument('--start', action='store_true')
    parser.add_argument('--host-firewall', type=int, action='append', default=[], metavar='VMID',
                        help='Add the host firewall rule of this container; one option for each confirmed rule')
    parser.add_argument('--automatic', action='store_true',
                        help='Only the applications that need no question: the ones the cluster keeps a record of')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    if args.action == 'list':
        print(json.dumps(pending(args.root)))
        return 0
    try:
        with instances.locked(args.root):
            plans = prepare(args.root)
            if args.action == 'plan':
                print(json.dumps([describe(plan) for plan in plans], indent=2))
                return 0
            if not plans and not args.automatic:
                msg_ok(translate('No restored OCI application is waiting to be recovered.'))
                return 0
            failed = 0
            if args.automatic:
                plans = [plan for plan in plans if automatic(plan)]
                args.start, args.host_firewall = False, []
            for plan in plans:
                containers = ', '.join(f"CT {entry['vmid']}" for entry in plan['restored'])
                msg_info2(f"{plan['title']} · {containers}")
                if plan['blockers']:
                    failed += 1
                    msg_error(translate('This application cannot be recovered yet:'))
                    for line in plan['blockers']:
                        msg_info2(f"  - {line}")
                    lost = [entry for entry in plan['restored'] if entry.get('unrecoverable')]
                    if lost:
                        set_unrecoverable(args.root, lost)
                        msg_info2(translate('A container without its record stays as an ordinary container and is not offered again.'))
                    continue
                try:
                    recover(args.root, plan, args.start, args.host_firewall)
                except (OSError, ValueError, KeyError, RuntimeError, StopIteration, TypeError,
                        subprocess.TimeoutExpired) as error:
                    failed += 1
                    msg_error(f"{translate('The application could not be recovered:')} {error}")
                    continue
                for line in plan['notes']:
                    msg_warn(line)
            return 1 if failed else 0
    except BlockingIOError:
        msg_error(translate('Another OCI operation is using the instance registry. Wait for it to finish.'))
        return 1


if __name__ == '__main__':
    sys.exit(main())
