#!/usr/bin/env python3
"""Explicit stopped-CT NVIDIA refresh. Never changes the desired deployment."""
from __future__ import annotations

import argparse
import copy
import os
from pathlib import Path
import subprocess

import oci_instances as instances
import oci_nvidia_runtime as nv
from oci_ui import translate, msg_info, msg_ok, msg_error


def destination(root, name):
    if not name.startswith('/') or '..' in Path(name).parts:
        raise ValueError(translate('Invalid NVIDIA destination'))
    parent = (root / name.lstrip('/')).parent.resolve()
    if parent != root and root not in parent.parents:
        raise ValueError(translate('The NVIDIA destination escapes the rootfs'))
    return parent / Path(name).name


def prepare(root, plan):
    root = root.resolve()
    # Validate every destination before making any rootfs change.
    files = {name: destination(root, name) for name in plan['inventory']['files']}
    links = {name: destination(root, name) for name in plan['links']}
    for path in list(files.values()) + list(links.values()):
        if path.exists() and not path.is_file() and not path.is_symlink():
            raise ValueError(translate('The NVIDIA destination cannot be replaced'))
    for path in files.values():
        create_parent(path.parent, root)
        if path.is_symlink():
            path.unlink()
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            os.close(fd)
            owner = path.parent.stat()
            os.chown(path, owner.st_uid, owner.st_gid)
    for name, path in links.items():
        create_parent(path.parent, root)
        if path.exists() or path.is_symlink():
            path.unlink()
        path.symlink_to(plan['links'][name])
    # Native LXC cannot mount onto an alias in a usr-merged image.
    lines = []
    for line in plan['config'].decode().splitlines():
        if line.startswith('lxc.mount.entry: '):
            fields = line.split(': ', 1)[1].split()
            fields[1] = str(files['/' + fields[1]].relative_to(root))
            line = 'lxc.mount.entry: ' + ' '.join(fields)
        lines.append(line)
    return ('\n'.join(lines) + '\n').encode()


def create_parent(path, root):
    if path.exists():
        if not path.is_dir():
            raise ValueError(translate('The parent of an NVIDIA destination is not a directory'))
        return
    if path == root:
        raise ValueError(translate('The rootfs is not mounted'))
    create_parent(path.parent, root)
    path.mkdir(mode=0o755)
    owner = path.parent.stat()
    os.chown(path, owner.st_uid, owner.st_gid)


def refresh(root, vmid, apply=False):
    with instances.locked(root):
        record = instances.read(root, vmid)
        if record['status'] != 'installed' or record.get('pending_transaction'):
            raise ValueError(translate('The instance has a pending operation'))
        if not nv.enabled(record['deployment']):
            raise ValueError(translate('The instance does not use NVIDIA'))
        config = instances.command('pct', 'config', str(vmid))
        if (instances.identity(config) != record['installation_id']
                or instances.sha(config) != record['observed']['config_sha256']):
            raise ValueError(translate('The container identity or configuration changed'))
        previous = record['observed']['gpu_devices'][nv.KEY]
        plan = nv.refresh_plan(config, previous)
        journal = instances.location(root, vmid).parent / 'nvidia-refresh.json'
        if journal.exists() or journal.is_symlink():
            raise ValueError(translate('A previous NVIDIA refresh is pending review'))
        if not apply:
            msg_ok(translate('Current NVIDIA inventory resolved: a refresh is required') if plan['changed']
                   else translate('Current NVIDIA inventory resolved: no refresh is required'))
            return
        if not plan['changed']:
            msg_ok(translate('The NVIDIA runtime is up to date; the container is not modified or started'))
            return
        if instances.command('pct', 'status', str(vmid)).strip() != b'status: stopped':
            raise ValueError(translate('Stop the container before the NVIDIA refresh'))
        instances.write(journal, {'phase': 'preparing', 'record': record,
                                  'inventory': plan['inventory']})
        msg_info(translate('Refreshing the NVIDIA runtime...'))
        instances.command('pct', 'mount', str(vmid))
        try:
            candidate = prepare(Path(f'/var/lib/lxc/{vmid}/rootfs'), plan)
        finally:
            instances.command('pct', 'unmount', str(vmid))
        nv.verify(plan['inventory'])
        if instances.command('pct', 'config', str(vmid)) != config:
            raise ValueError(translate('The configuration changed during the NVIDIA refresh'))
        conf = Path(f'/etc/pve/lxc/{vmid}.conf')
        # Same native configuration file used by the common installer.
        conf.write_bytes(candidate)
        instances.write(journal, {'phase': 'validating', 'record': record,
                                  'inventory': plan['inventory']})
        instances.command('pct', 'start', str(vmid))
        try:
            nv.validate_runtime(vmid, plan['inventory'])
        finally:
            instances.command('pct', 'shutdown', str(vmid), '--timeout', '30')
        updated = copy.deepcopy(record)
        updated['observed'] = instances.observe(vmid, record['installation_id'],
            record['observed']['archive_path'], record['observed']['resolved_registry_digest'],
            record['observed']['image'])
        nv.check_mounts(updated['observed']['config'].encode(), plan['inventory'])
        nv.check_devices(updated['observed']['config'].encode(), plan['inventory'])
        if updated['observed']['gpu_devices'][nv.KEY] != plan['inventory']:
            raise ValueError(translate('The observed inventory differs from the validated runtime'))
        nv.verify(plan['inventory'])
        instances.write(instances.location(root, vmid), updated)
        journal.unlink()
        msg_ok(translate('NVIDIA refresh validated; the container is stopped and its settings are kept'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmid', type=int)
    parser.add_argument('--root', type=Path, default=instances.ROOT)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        refresh(args.root, args.vmid, args.apply)
    except BlockingIOError:
        msg_error(translate('Another OCI operation is using the registry. This operation was not started.'))
        raise SystemExit(1)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        msg_error(str(error) if not isinstance(error, KeyError) else
                  translate('The saved OCI record is incomplete or has an unexpected format.'))
        raise SystemExit(1)
