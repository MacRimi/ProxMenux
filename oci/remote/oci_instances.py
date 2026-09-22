#!/usr/bin/env python3
"""Private OCI instance contracts. Does not recreate or update containers."""
from __future__ import annotations

import argparse
import contextlib
import copy
from contextlib import contextmanager
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

from oci_installation_state import command, image_from_archive, private_directory, sha
from oci_host_mounts import capture_sources
from oci_accelerators import capture as capture_gpu_devices
from oci_ui import translate, msg_error, msg_ok

ROOT = Path('/usr/local/share/proxmenux/oci/apps')
MARKER = 'proxmenux-instance='
ACTIVE = {'installing', 'assembling', 'updating', 'recovering'}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def location(root, vmid):
    if not isinstance(vmid, int) or vmid < 100:
        raise ValueError(translate('Invalid VMID'))
    path = root / str(vmid)
    if path.is_symlink():
        raise ValueError(translate('Unsafe instance directory'))
    return path / 'oci-compose.json'


@contextmanager
def locked(root):
    private_directory(root)
    path = root / '.lock'
    if path.is_symlink():
        raise ValueError(translate('Unsafe registry lock'))
    inherited = os.environ.get('PROXMENUX_INSTANCE_LOCK_FD')
    if inherited:
        fd = int(inherited)
        if os.fstat(fd).st_ino != path.stat().st_ino or os.fstat(fd).st_dev != path.stat().st_dev:
            raise ValueError(translate('Wrong inherited registry lock'))
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    else:
        with path.open('a') as lock:
            os.chmod(path, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield


def write(path, value):
    private_directory(path.parent)
    if path.is_symlink():
        raise ValueError(translate('Unsafe instance record'))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.compose-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read(root, vmid):
    path = location(root, vmid)
    if path.is_symlink():
        raise ValueError(translate('Unsafe instance record'))
    value = json.loads(path.read_text())
    if value.get('schema_version') != 1 or value.get('vmid') != vmid:
        raise ValueError(translate('Incompatible instance record'))
    uuid.UUID(value['installation_id'])
    return value


def has_contract(root, vmid):
    path = location(root, vmid)
    if path.is_symlink():
        raise ValueError(translate('Unsafe instance record'))
    if path.parent.exists() and not path.parent.is_dir():
        raise ValueError(translate('Incompatible instance directory'))
    return path.exists()


def guest_exists(vmid):
    nodes = Path('/etc/pve/nodes')
    return any(nodes.glob(f'*/lxc/{vmid}.conf')) or any(nodes.glob(f'*/qemu-server/{vmid}.conf'))


def release_orphan(root, vmid):
    """A record whose guest no longer exists on any node does not own the VMID:
    a failed install, or a container deleted from the Proxmox UI. An update or
    recovery left halfway keeps it, because its backup may still be needed.
    The record stays in the same directory as history."""
    path = location(root, vmid)
    if not path.exists():
        return True
    previous = read(root, vmid)
    if (previous.get('status') in ('updating', 'recovering')
            or previous.get('pending_transaction') or previous.get('pending_stack_transaction')
            or guest_exists(vmid)):
        return False
    path.replace(path.with_name(f"retired-{previous['installation_id']}.json"))
    return True


def prepare(root, vmid, template, deployment):
    path = location(root, vmid)
    if not release_orphan(root, vmid):
        raise ValueError(f"VMID {vmid} {translate('belongs to another OCI installation')}")
    deployment = dict(deployment, vmid=vmid)
    value = {'schema_version': 1, 'vmid': vmid, 'installation_id': str(uuid.uuid4()),
             'created_at': now(), 'status': 'installing', 'template': template,
             'deployment': deployment, 'observed': None,
             'automatic_update_enabled': False}
    write(path, value)
    return value


def observe(vmid, installation_id, archive, digest, image=None):
    """Collect evidence before changing the current desired-state contract.
    An installation observed again passes its saved image metadata, since the
    downloaded archive may have been removed."""
    config = command('pct', 'config', str(vmid))
    if identity(config) != installation_id:
        raise ValueError(translate('The container identity does not match'))
    resources = json.loads(command('pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'))
    node = next(r['node'] for r in resources if r.get('type') == 'lxc' and int(r['vmid']) == vmid)
    api_config = command('pvesh', 'get', f'/nodes/{node}/lxc/{vmid}/config', '--output-format', 'json')
    observed = {
        'config': config.decode(), 'config_sha256': sha(config), 'api_config_sha256': api_hash(api_config),
        'image': image if image is not None else image_from_archive(archive), 'archive_path': archive,
        'resolved_registry_digest': digest}
    sources = capture_sources(config)
    if sources:
        observed['host_bind_sources'] = sources
    gpu = capture_gpu_devices(config)
    if gpu:
        observed['gpu_devices'] = gpu
    return observed


def finish(root, vmid, archive, digest):
    value = read(root, vmid)
    observed = observe(vmid, value['installation_id'], archive, digest)
    value.update(status='assembling' if value['deployment'].get('stack_managed') else 'installed',
                 completed_at=now(), observed=observed)
    write(location(root, vmid), value)


def publish_stack(root, primary_id, template, deployment, members):
    """Preserve each recipe AND a complete, nonrecursive copy in the principal."""
    records = {}
    for member in members:
        vmid = int(member['vmid'])
        record = read(root, vmid)
        if identity(command('pct', 'config', str(vmid))) != record['installation_id']:
            raise ValueError(translate('A stack member has a different identity'))
        records[vmid] = record
    if primary_id is not None and primary_id not in records:
        raise ValueError(translate('The main member of the stack is missing'))
    stack_id = records[primary_id]['installation_id'] if primary_id is not None else None
    for member in members:
        vmid = int(member['vmid'])
        record = records[vmid]
        if 'deployment' in member:
            record['deployment'] = copy.deepcopy(member['deployment'])
            record['deployment']['vmid'] = vmid
        record['deployment']['stack_managed'] = primary_id is not None
        write(location(root, vmid), record)
        finish(root, vmid, record['observed']['archive_path'], record['observed']['resolved_registry_digest'])
        record = read(root, vmid)
        record['status'] = 'installed'
        if stack_id:
            record['stack_member'] = {'stack_id': stack_id, 'primary_vmid': primary_id, 'name': member['name']}
        records[vmid] = record
    if primary_id is not None:
        recipes = [copy.deepcopy(records[int(m['vmid'])]) for m in members]
        for recipe in recipes:
            recipe.pop('stack', None)
        records[primary_id]['stack'] = {
            'id': stack_id, 'template': copy.deepcopy(template),
            'deployment': copy.deepcopy(deployment), 'members': recipes,
            'reconstruction_requires_volume_verification': True,
        }
        records[primary_id]['stack']['deployment']['services'] = copy.deepcopy(members)
        # Persist recovery recipes first, before publishing member completion.
        write(location(root, primary_id), records[primary_id])
    for vmid, record in records.items():
        if vmid != primary_id:
            write(location(root, vmid), record)


def identity(config):
    # Description is URL-escaped by pct; UUID characters remain unchanged.
    text = config.decode()
    try:
        description = json.loads(text).get('description', '')
    except ValueError:
        description = next((line[len('description: '):] for line in text.splitlines()
                            if line.startswith('description: ')), '')
    match = re.search(r'proxmenux-instance=([0-9a-f-]{36})(?![0-9a-f-])', description)
    return match.group(1) if match else None


def save_assembly(root, primary_id, template, deployment, members):
    path = location(root, primary_id).parent / 'stack-assembly.json'
    if path.exists() or path.is_symlink():
        raise ValueError(translate('A pending stack assembly already exists; it is not overwritten'))
    ids = [int(m['vmid']) for m in members]
    if primary_id not in ids or len(set(ids)) != len(ids):
        raise ValueError(translate('Invalid stack members'))
    expected = {str(vmid): read(root, vmid)['installation_id'] for vmid in ids}
    write(path, {'schema_version': 1, 'primary_vmid': primary_id, 'created_at': now(),
                 'expected_installation_ids': expected, 'template': template,
                 'deployment': deployment, 'services': members})


def resume_assembly(root, primary_id):
    path = location(root, primary_id).parent / 'stack-assembly.json'
    if path.is_symlink():
        raise ValueError(translate('Unsafe stack assembly'))
    saved = json.loads(path.read_text())
    ids = [int(m['vmid']) for m in saved['services']]
    if (saved.get('schema_version') != 1 or saved['primary_vmid'] != primary_id
            or primary_id not in ids or len(set(ids)) != len(ids)
            or set(saved['expected_installation_ids']) != {str(vmid) for vmid in ids}):
        raise ValueError(translate('Incompatible stack assembly'))
    for vmid in ids:
        expected = saved['expected_installation_ids'][str(vmid)]
        if read(root, vmid)['installation_id'] != expected:
            raise ValueError(translate('The record of a member was replaced; the assembly is not resumed'))
        if identity(command('pct', 'config', str(vmid))) != expected:
            raise ValueError(translate('The container of a member was replaced; the assembly is not resumed'))
    publish_stack(root, primary_id, saved['template'], saved['deployment'], saved['services'])
    path.unlink()


def api_hash(config):
    return sha(json.dumps(json.loads(config), sort_keys=True, separators=(',', ':')).encode())


def reconcile(root, resources, configs):
    """Caller holds lock and fetched a complete cluster inventory and configs."""
    if not isinstance(resources, list):
        raise ValueError(translate('Invalid Proxmox inventory'))
    for resource in resources:
        if (not isinstance(resource, dict) or resource.get('type') not in ('lxc', 'qemu')
                or not isinstance(resource.get('vmid'), int)):
            raise ValueError(translate('Incomplete or incompatible Proxmox inventory'))
    present = {int(r['vmid']): r for r in resources if r.get('type') in ('lxc', 'qemu')}
    decisions = []
    pending = set()
    for directory in root.iterdir():
        if directory.name.isdecimal():
            journal = location(root, int(directory.name)).parent / 'stack-assembly.json'
            if journal.is_symlink():
                raise ValueError(translate('Unsafe stack assembly'))
            if journal.exists():
                saved = json.loads(journal.read_text())
                if saved.get('schema_version') != 1:
                    raise ValueError(translate('Incompatible stack assembly'))
                pending.update(int(vmid) for vmid in saved['expected_installation_ids'])
    # Plan everything before removing anything: malformed records fail closed.
    for directory in sorted(root.iterdir()):
        if not directory.name.isdecimal():
            continue
        vmid = int(directory.name)
        if not has_contract(root, vmid):
            # Orphan cleanup intentionally retains transaction history/backups.
            continue
        value = read(root, vmid)
        row = {'vmid': vmid, 'status': value['status'], 'action': 'keep'}
        if value['status'] in ACTIVE or vmid in pending or value.get('pending_stack_transaction'):
            row['reason'] = 'operation-in-progress'
        elif vmid not in present or present[vmid]['type'] != 'lxc':
            row.update(action='delete', reason='container-absent-or-replaced')
        else:
            config = configs[vmid]
            marker = identity(config)
            if marker and marker != value['installation_id']:
                row.update(action='delete', reason='different-installation')
            elif not marker:
                row['reason'] = 'identity-unconfirmed'
            else:
                row['reason'] = 'matched'
                baseline = (value.get('observed') or {}).get('api_config_sha256')
                row['configuration_changed'] = api_hash(config) != baseline if baseline else None
        decisions.append(row)
        if value.get('stack'):
            row['missing_members'] = [m['vmid'] for m in value['stack']['members']
                                      if m['vmid'] not in present]
            row['replaced_members'] = [m['vmid'] for m in value['stack']['members']
                if m['vmid'] in present and (present[m['vmid']]['type'] != 'lxc' or
                    (m['vmid'] in configs and identity(configs[m['vmid']]) not in (None, m['installation_id'])))]
    for row in decisions:
        if row['action'] == 'delete':
            path = location(root, row['vmid'])
            path.unlink()
            # Never recursively delete history, backups, or unexpected files.
            try:
                path.parent.rmdir()
            except OSError:
                pass
    return decisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('prepare', 'complete', 'failed'):
        p = sub.add_parser(action)
        p.add_argument('vmid', type=int)
        if action == 'prepare':
            p.add_argument('--template', required=True)
            p.add_argument('--deployment', required=True)
        if action == 'complete':
            p.add_argument('--archive', required=True)
            p.add_argument('--digest', required=True)
    sub.add_parser('reconcile')
    resume = sub.add_parser('resume-stack-recording')
    resume.add_argument('vmid', type=int)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    try:
        with locked(args.root):
            if args.action == 'resume-stack-recording':
                resume_assembly(args.root, args.vmid)
                msg_ok(translate('Stack records saved; no container was reinstalled.'))
            elif args.action == 'prepare':
                value = prepare(args.root, args.vmid, json.loads(Path(args.template).read_text()),
                                json.loads(Path(args.deployment).read_text()))
                print(value['installation_id'])
            elif args.action == 'complete':
                finish(args.root, args.vmid, args.archive, args.digest)
            elif args.action == 'failed':
                value = read(args.root, args.vmid)
                value.update(status='failed', failed_at=now())
                write(location(args.root, args.vmid), value)
            else:
                resources = json.loads(command('pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'))
                configs = {}
                wanted = set()
                for directory in args.root.iterdir():
                    if directory.name.isdecimal():
                        if not has_contract(args.root, int(directory.name)):
                            continue
                        record = read(args.root, int(directory.name))
                        wanted.add(record['vmid'])
                        wanted.update(m['vmid'] for m in record.get('stack', {}).get('members', []))
                for r in resources:
                    if r.get('type') == 'lxc' and int(r['vmid']) in wanted:
                        configs[int(r['vmid'])] = command('pvesh', 'get', f"/nodes/{r['node']}/lxc/{r['vmid']}/config", '--output-format', 'json')
                # pvesh JSON contains the description and all repeated LXC entries.
                print(json.dumps(reconcile(args.root, resources, configs), indent=2))
        return 0
    except (OSError, ValueError, KeyError, StopIteration, RuntimeError, subprocess.TimeoutExpired) as exc:
        # stdout carries data read by the installers; the error goes to stderr.
        with contextlib.redirect_stdout(sys.stderr):
            msg_error(f"{translate('The instance record operation did not complete; no container was modified.')} ({exc})")
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
