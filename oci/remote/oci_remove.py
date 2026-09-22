#!/usr/bin/env python3
"""Removes an OCI installation: its containers with the volumes they own, the
private network of a multi-container application and its saved record. Host
directories are left exactly as they are."""
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
from oci_ui import translate, msg_info, msg_ok, msg_warn, msg_error

# The private networks ProxMenux creates for multi-container applications.
PRIVATE_STACK_NETWORK = ipaddress.ip_network('10.77.0.0/16')


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
    if not bridge or not re.fullmatch(r'vmbr[0-9]+', bridge):
        return None
    try:
        if not ipaddress.ip_network(subnet).subnet_of(PRIVATE_STACK_NETWORK):
            return None
    except (TypeError, ValueError):
        return None
    return bridge


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
    subprocess.run(['ip', 'link', 'delete', bridge, 'type', 'bridge'], check=False, capture_output=True)
    subprocess.run(['pvesh', 'delete', f'/nodes/{node}/network/{bridge}'], check=False, capture_output=True)


def remove(root, vmid):
    primary_id, primary, members = members_of(root, vmid)
    for member in members:
        record = instances.read(root, member)
        if record.get('pending_transaction') or record.get('pending_stack_transaction'):
            raise ValueError(translate('An operation of this installation has not finished; '
                                       'recover it from the management menu before removing it'))
    kept = host_directories(root, members)
    bridge = private_bridge(primary)
    msg_info(translate('Removing the containers...'))
    for member in members:
        record = instances.read(root, member)
        config = guest_config(member)
        if config is None:
            msg_warn(f"{translate('The container no longer exists:')} CT {member}")
        elif instances.identity(config) != record['installation_id']:
            msg_warn(f"{translate('The VMID belongs to another container now and is not touched:')} CT {member}")
        else:
            subprocess.run(['pct', 'stop', str(member), '--skiplock', '1'], check=False, capture_output=True)
            run('pct', 'destroy', str(member), '--purge', '1', '--destroy-unreferenced-disks', '1')
            msg_ok(f"{translate('Container removed:')} CT {member}")
    if bridge and not bridge_in_use(bridge, set(members)):
        release_bridge(bridge)
        msg_ok(f"{translate('Private network of the application released:')} {bridge}")
    elif bridge:
        msg_warn(f"{translate('The private network is still used by another container and is kept:')} {bridge}")
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
        msg_warn(f"{translate('Host directory kept, with its content:')} {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmid', type=int)
    parser.add_argument('--root', type=Path, default=instances.ROOT)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    try:
        with instances.locked(args.root):
            remove(args.root, args.vmid)
    except BlockingIOError:
        msg_error(translate('Another OCI operation is using the instance registry'))
        return 1
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        msg_error(str(error) or type(error).__name__)
        return 1
    msg_ok(translate('The application was removed'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
