#!/usr/bin/env python3
"""Removes an OCI installation: its containers with the volumes they own, the
private network of a multi-container application, its saved record and what
it left on the host for those containers. Host directories are left exactly
as they are."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys

import oci_image_cache as image_cache
import oci_instances as instances
from oci_installation_state import parse_config
import oci_console
import oci_runtime_settings as runtime_settings
from oci_ui import translate, msg_info, msg_ok, msg_warn, msg_error

# The private networks ProxMenux creates for multi-container applications.
PRIVATE_STACK_NETWORK = ipaddress.ip_network('10.77.0.0/16')
CLUSTER_NODES = Path('/etc/pve/nodes')
SNIPPETS = Path('/var/lib/vz/snippets')
# The App tab of ProxMenux Monitor keeps one file per VMID.
MONITOR_APPS = Path('/etc/proxmenux/apps')
CLUSTER_RECORDS = Path('/etc/pve/priv/proxmenux/oci')
HOST_MONITOR_INCLUDES = (Path('/etc/pve/proxmenux/host-monitor'), Path('/etc/pve/lxc/proxmenux-host-monitor'))
STACK_HOOK = 'proxmenux-stack-dependencies.sh'


def run(*args):
    subprocess.run(args, check=True, capture_output=True)


def guest_config(vmid):
    try:
        return instances.command('pct', 'config', str(vmid))
    except (subprocess.CalledProcessError, RuntimeError, OSError):
        return None


def members_of(root, vmid):
    """Every container of the installation: one, or the whole stack when the
    selected container belongs to one. The main container is removed last."""
    record = instances.read(root, vmid)
    primary_id = (record.get('stack_member') or {}).get('primary_vmid', vmid)
    try:
        primary = instances.read(root, primary_id)
    except (OSError, ValueError, KeyError):
        primary, primary_id = record, vmid
    stack = primary.get('stack') or {}
    members = [int(member['vmid']) for member in stack.get('members', []) if member.get('vmid')]
    if primary_id not in members:
        members.append(primary_id)
    if vmid not in members:
        members.append(vmid)
    ordered = [member for member in members if member != primary_id] + [primary_id]
    return primary_id, primary, ordered


def host_directories(root, members):
    """The host directories the containers were using, which are kept."""
    paths = []
    for vmid in members:
        try:
            record = instances.read(root, vmid)
        except (OSError, ValueError, KeyError):
            continue
        for mount in record.get('deployment', {}).get('mounts', []):
            if mount.get('type') == 'host-bind' and mount.get('source') not in paths:
                paths.append(mount['source'])
    return paths


def private_bridge(primary):
    network = (primary.get('stack') or {}).get('deployment', {}).get('network', {})
    bridge = network.get('private_bridge')
    subnet = network.get('private_subnet')
    if not bridge:
        # An application of the Arr suite has no stack record: each one is
        # independent, and its own leg is on the network the suite shares.
        own = primary.get('deployment', {}).get('network', {})
        bridge = own.get('bridge')
        try:
            subnet = str(ipaddress.ip_interface(own.get('ipv4')).network)
        except (TypeError, ValueError):
            return None
    if not bridge or not re.fullmatch(r'vmbr[0-9]+', bridge):
        return None
    try:
        if not ipaddress.ip_network(subnet).subnet_of(PRIVATE_STACK_NETWORK):
            return None
    except (TypeError, ValueError):
        return None
    return bridge


def guest_node(vmid):
    """The cluster node that holds the container's configuration, if any.
    `pct config` sees only the local node; a migrated container is elsewhere."""
    for path in CLUSTER_NODES.glob(f'*/lxc/{int(vmid)}.conf'):
        return path.parent.parent.name
    return None


def _unlink(path):
    try:
        if path.is_file() and not path.is_symlink():
            path.unlink()
    except OSError:
        pass


def remove_host_state(vmid):
    """What the installation kept on the host for a container that is gone:
    its sysctl include, the Rclone mount hookscript and the views it
    published, and its registration in the App tab of ProxMenux Monitor."""
    for include in (runtime_settings.include_path(vmid), runtime_settings.legacy_include_path(vmid)):
        _unlink(include)
    hook = SNIPPETS / f'proxmenux-rclone-{int(vmid)}-fuse-hook.sh'
    if hook.is_file() and not hook.is_symlink():
        unit = f'proxmenux-rclone-publish-{int(vmid)}.service'
        for action in ('stop', 'reset-failed'):
            subprocess.run(['systemctl', action, unit], check=False, capture_output=True)
        views = re.findall(r'^published(?:_ro)?=(/\S+)$', hook.read_text(errors='ignore'), re.MULTILINE)
        for view in views:
            # Only an empty directory that is no longer a mount point.
            if os.path.isdir(view) and not os.path.ismount(view):
                try:
                    os.rmdir(view)
                except OSError:
                    pass
        _unlink(hook)
    _unlink(CLUSTER_RECORDS / f'{int(vmid)}.json')
    _unlink(MONITOR_APPS / f'{int(vmid)}.json')
    dismissed = MONITOR_APPS / '.oci-dismissed.json'
    try:
        entries = json.loads(dismissed.read_text())
    except (OSError, ValueError):
        return
    if isinstance(entries, dict) and entries.pop(str(int(vmid)), None) is not None:
        temporary = dismissed.with_name(dismissed.name + '.tmp')
        temporary.write_text(json.dumps(entries, indent=2))
        os.replace(temporary, dismissed)


def _guest_configs():
    texts = []
    for pattern in ('*/lxc/*.conf', '*/qemu-server/*.conf'):
        for path in CLUSTER_NODES.glob(pattern):
            texts.append(path.read_text(encoding='utf-8', errors='ignore'))
    return '\n'.join(texts)


def release_shared_host_files(hookscripts):
    """Files several installations share, once no guest of the cluster uses
    them: the host-monitor include and the stack dependency hookscript."""
    remaining = _guest_configs()
    for include in HOST_MONITOR_INCLUDES:
        if include.is_file() and f'lxc.include: {include}' not in remaining:
            _unlink(include)
    for volume in set(hookscripts):
        if STACK_HOOK not in volume or f'hookscript: {volume}' in remaining:
            continue
        try:
            path = Path(instances.command('pvesm', 'path', volume).decode().strip())
        except (subprocess.CalledProcessError, RuntimeError, OSError):
            continue
        if path.name == STACK_HOOK:
            _unlink(path)


def _leftovers(vmid):
    """Whether anything of the container is still on the host."""
    paths = [runtime_settings.include_path(vmid), runtime_settings.legacy_include_path(vmid),
             SNIPPETS / f'proxmenux-rclone-{int(vmid)}-fuse-hook.sh', MONITOR_APPS / f'{int(vmid)}.json',
             CLUSTER_RECORDS / f'{int(vmid)}.json',
             *oci_console.LOG_DIR.glob(f'{int(vmid)}.console.log*')]
    return any(path.exists() for path in paths)


def sweep_orphans(root):
    """Leftovers of containers that exist on no node of the cluster: the
    record of one deleted from the Proxmox interface, and files an earlier
    removal left behind. A record with an operation left halfway is kept,
    because its backup may still be needed. Returns the VMIDs cleaned."""
    found = {int(d.name) for d in root.iterdir() if d.name.isdecimal()} if root.is_dir() else set()
    for directory, pattern in ((runtime_settings.include_path(0).parent, r'([0-9]+)\.sysctls'),
                               (runtime_settings.legacy_include_path(0).parent, r'([0-9]+)\.proxmenux-sysctls'),
                               (oci_console.LOG_DIR, r'([0-9]+)\.console\.log.*'),
                               (SNIPPETS, r'proxmenux-rclone-([0-9]+)-fuse-hook\.sh'),
                               (CLUSTER_RECORDS, r'([0-9]+)\.json')):
        if directory.is_dir():
            found.update(int(m.group(1)) for m in (re.fullmatch(pattern, p.name) for p in directory.iterdir()) if m)
    # Only the App tab registrations of OCI installs; the other ones belong to
    # ordinary containers.
    for path in MONITOR_APPS.glob('*.json') if MONITOR_APPS.is_dir() else []:
        try:
            apps = json.loads(path.read_text()).get('apps') or []
        except (OSError, ValueError, AttributeError):
            continue
        if path.stem.isdecimal() and any(app.get('installed_via') == 'oci_image' for app in apps):
            found.add(int(path.stem))
    cleaned = []
    for vmid in sorted(found):
        if instances.guest_exists(vmid):
            continue
        record = instances.has_contract(root, vmid)
        if record and not instances.release_orphan(root, vmid):
            continue
        if not (record or _leftovers(vmid)):
            continue
        oci_console.remove_log(vmid)
        remove_host_state(vmid)
        cleaned.append(vmid)
    if cleaned:
        release_shared_host_files([])
    return cleaned


def bridge_in_use(bridge, removed):
    """Whether a guest that is not being removed still uses the bridge."""
    for path in Path('/etc/pve/nodes').glob('*/lxc/*.conf'):
        if int(path.stem) in removed:
            continue
        if re.search(rf'(?:^|[,\s])bridge={re.escape(bridge)}(?:[,\s]|$)',
                     path.read_text(encoding='utf-8', errors='ignore'), re.MULTILINE):
            return True
    for path in Path('/etc/pve/nodes').glob('*/qemu-server/*.conf'):
        if re.search(rf'(?:^|[,\s])bridge={re.escape(bridge)}(?:[,\s]|$)',
                     path.read_text(encoding='utf-8', errors='ignore'), re.MULTILINE):
            return True
    return False


def release_bridge(bridge):
    node = socket.gethostname().split('.', 1)[0]
    succeeded = []
    for command in (['ip', 'link', 'delete', bridge, 'type', 'bridge'],
                    ['pvesh', 'delete', f'/nodes/{node}/network/{bridge}']):
        try:
            succeeded.append(subprocess.run(command, check=False, capture_output=True).returncode == 0)
        except (OSError, subprocess.CalledProcessError):
            succeeded.append(False)
    return all(succeeded)


def remove_owned_host_firewall(record):
    """Remove only the narrowly scoped rule created by this installation.

    A matching port alone is never evidence of ownership: administrators and
    other applications may legitimately use it.  Older CT-number comments are
    deliberately left alone as well.
    """
    plan = record.get('deployment', {}).get('host_firewall') or {}
    if not plan:
        return True
    installation_id = record.get('installation_id', '')
    if not isinstance(plan, dict) or not re.fullmatch(r'[0-9a-f-]{36}', installation_id):
        msg_warn(translate('Could not verify removal of the managed host firewall rule.'))
        return False
    source, port = plan.get('source'), plan.get('port')
    if not isinstance(source, str) or not isinstance(port, int):
        msg_warn(translate('Could not verify removal of the managed host firewall rule.'))
        return False
    comment = f'ProxMenux OCI firewall {installation_id}'
    node = socket.gethostname().split('.', 1)[0]
    try:
        result = subprocess.run(['pvesh', 'get', f'/nodes/{node}/firewall/rules', '--output-format', 'json'],
                                check=True, capture_output=True, text=True)
        rules = json.loads(result.stdout)
        matches = [rule for rule in rules if rule.get('comment') == comment
                   and str(rule.get('dport')) == str(port)
                   and rule.get('source') == source
                   and str(rule.get('proto', '')).lower() == 'tcp'
                   and str(rule.get('type', '')).lower() == 'in'
                   and str(rule.get('action', '')).upper() == 'ACCEPT']
        if not matches:
            return True
        if len(matches) != 1 or not isinstance(matches[0].get('pos'), int):
            msg_warn(translate('Could not verify removal of the managed host firewall rule.'))
            return False
        subprocess.run(['pvesh', 'delete', f"/nodes/{node}/firewall/rules/{matches[0]['pos']}"],
                       check=True, capture_output=True)
        msg_ok(f"{translate('Host firewall rule removed:')} TCP {port} {translate('from')} {source}")
        return True
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError):
        # A firewall API failure must not abort remaining record cleanup;
        # report the unverified outcome without claiming the rule survived.
        msg_warn(translate('Could not verify removal of the managed host firewall rule.'))
        return False


def remove(root, vmid):
    primary_id, primary, members = members_of(root, vmid)
    for member in members:
        record = instances.read(root, member)
        if record.get('pending_transaction') or record.get('pending_stack_transaction'):
            raise ValueError(translate('An operation of this installation has not finished; '
                                       'recover it from the management menu before removing it'))
        node = guest_node(member) if guest_config(member) is None else None
        if node:
            raise ValueError(f"{translate('The container runs on another node of the cluster; migrate it back to this node to remove it:')} "
                             f"CT {member} ({node})")
    kept = host_directories(root, members)
    bridge = private_bridge(primary)
    incomplete = False
    msg_info(translate('Removing the containers...'))
    hookscripts = []
    for member in members:
        record = instances.read(root, member)
        config = guest_config(member)
        if config is None:
            msg_warn(f"{translate('The container no longer exists:')} CT {member}")
            incomplete = True
            oci_console.remove_log(member)
            remove_host_state(member)
        elif instances.identity(config) != record['installation_id']:
            msg_warn(f"{translate('The VMID belongs to another container now and is not touched:')} CT {member}")
            incomplete = True
        else:
            hookscripts += re.findall(r'^hookscript: (\S+)$', config.decode(errors='ignore'), re.MULTILINE)
            subprocess.run(['pct', 'stop', str(member), '--skiplock', '1'], check=False, capture_output=True)
            run('pct', 'destroy', str(member), '--purge', '1', '--destroy-unreferenced-disks', '1')
            oci_console.remove_log(member)
            remove_host_state(member)
            msg_ok(f"{translate('Container removed:')} CT {member}")
    if bridge and not bridge_in_use(bridge, set(members)):
        released = release_bridge(bridge)
        msg_ok(f"{translate('Private network release attempted:')} {bridge}")
        if not released:
            msg_warn(f"{translate('Could not complete private network release:')} {bridge}")
            incomplete = True
    elif bridge:
        msg_info(f"{translate('The private network is still used by another guest and is kept:')} {bridge}")
    if not remove_owned_host_firewall(primary):
        incomplete = True
    release_shared_host_files(hookscripts)
    lifecycle = Path(f'/etc/pve/priv/proxmenux-stack-{primary_id}.json')
    if lifecycle.exists() and not lifecycle.is_symlink():
        lifecycle.unlink()
    for member in members:
        directory = instances.location(root, member).parent
        if directory.is_dir() and not directory.is_symlink():
            shutil.rmtree(directory)
    msg_ok(translate('Saved record removed'))
    for path, size in image_cache.prune(root, lock=False):
        msg_ok(f"{translate('Unused image removed from the cache:')} {path.name}")
    for path in kept:
        msg_info(f"{translate('Host directory listed in saved records (not targeted for removal):')} {path}")
    return incomplete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmid', type=int)
    parser.add_argument('--root', type=Path, default=instances.ROOT)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    try:
        with instances.locked(args.root):
            incomplete = remove(args.root, args.vmid)
    except BlockingIOError:
        msg_error(translate('Another OCI operation is using the instance registry'))
        return 1
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        msg_error(str(error) or type(error).__name__)
        return 1
    msg_ok(translate('Removal command finished; review any warnings above.') if incomplete
           else translate('The application was removed'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
