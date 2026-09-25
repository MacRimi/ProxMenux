#!/usr/bin/env python3
"""Instance recording adapter for the existing dedicated stack installers."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import oci_console
import oci_instances as instances
from oci_installation_state import command, image_from_archive, sha
import oci_stack_replay
from oci_ui import translate


def begin(root, primary, template, deployment, members, adapter):
    ids = [int(m[1]) for m in members]
    if primary not in ids or len(set(ids)) != len(ids):
        raise ValueError(translate('Invalid stack members'))
    resources = json.loads(command('pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'))
    if not isinstance(resources, list):
        raise ValueError(translate('Invalid Proxmox inventory'))
    occupied = {int(r['vmid']) for r in resources}
    for vmid in ids:
        if vmid in occupied or not instances.release_orphan(root, vmid):
            raise ValueError(translate('The VMID or its contract is already in use; it is not adopted'))
    adapter_source = Path(adapter).read_text()
    prepared = []
    for name, vmid, reference, archive in members:
        archive_path = archive if archive.startswith('/') else command('pvesm', 'path', archive).decode().strip()
        image = image_from_archive(archive_path)
        child = {'id': template['id'] + '-' + name,
                 'container_contract': {'image': {'reference': reference}}}
        plan = {'deployment_kind': 'dedicated-stack-member', 'stack_managed': True,
                'role': name, 'archive_volume': archive, 'archive_path': archive_path,
                'image': image, 'rootfs_adaptation_replay_required': True,
                'mounts': []}
        if Path(adapter).name == 'install_immich_stack.sh' and name == 'machine-learning':
            plan['machine_learning'] = copy.deepcopy(deployment.get('machine_learning', {'acceleration': 'cpu'}))
        if Path(adapter).name in oci_stack_replay.FILES:
            plan['replay_profile'] = {'adapter': Path(adapter).name, 'role': name}
            if not oci_stack_replay.FILES[Path(adapter).name][name]:
                plan['rootfs_replay'] = {'schema_version': 1, 'adapter': Path(adapter).name,
                                        'role': name, 'files': []}
        prepared.append((int(vmid), child, plan))
    for vmid, child, plan in prepared:
        instances.prepare(root, vmid, child, plan)
    parent = instances.read(root, primary)
    parent['native_stack_intent'] = {
        'template': template, 'deployment': copy.deepcopy(deployment),
        'members': [{'name': m[0], 'vmid': int(m[1])} for m in members],
        'adapter': {'name': Path(adapter).name, 'sha256': sha(adapter_source.encode()),
                    'source': adapter_source},
    }
    parent['native_stack_intent']['deployment']['base_vmid'] = primary
    instances.write(instances.location(root, primary), parent)


def create(root, args):
    vmid = int(args[0])
    record = instances.read(root, vmid)
    if record['status'] != 'installing' or args[1] != record['deployment']['archive_volume']:
        raise ValueError(translate('The container creation does not match the prepared instance'))
    argv = list(args)
    if '--description' in argv:
        index = argv.index('--description')
        del argv[index:index + 2]
    argv += ['--description', instances.MARKER + record['installation_id']]
    record['deployment']['create_arguments'] = argv
    instances.write(instances.location(root, vmid), record)
    # No inherited registry/network locks in long-lived Proxmox processes.
    # Keep PVE extraction directories traversable inside its standard idmap.
    code = subprocess.run(['pct', 'create', *argv], close_fds=True, umask=0o022).returncode
    if code == 0:
        # Every member keeps its console as its own log and opens a Proxmox
        # console as a shell, set before the stack records its configuration
        # so an update rebuilds them the same way.
        oci_console.configure(vmid)
    return code


def capture_rootfs(root, vmid):
    record = instances.read(root, vmid)
    profile = record['deployment'].get('replay_profile')
    if not profile:
        raise ValueError(translate('The stack member has no declared adaptation profile'))
    if record['status'] != 'installing':
        raise ValueError(translate('The rootfs capture only belongs to the running installation'))
    mounts = []
    for line in command('pct', 'config', str(vmid)).decode().splitlines():
        key, sep, value = line.partition(': ')
        if sep and key.startswith('mp') and key[2:].isdigit():
            options = dict(p.split('=', 1) for p in value.split(',')[1:] if '=' in p)
            mounts.append({'container_path': options['mp']})
    record['deployment']['rootfs_replay'] = oci_stack_replay.capture(
        Path('/var/lib/lxc') / str(vmid) / 'rootfs', profile['adapter'], profile['role'], mounts)
    instances.write(instances.location(root, vmid), record)


def finalize(root, primary):
    parent = instances.read(root, primary)
    intent = parent['native_stack_intent']
    services = []
    for member in intent['members']:
        vmid = member['vmid']
        record = instances.read(root, vmid)
        plan = record['deployment']
        from oci_description import render
        presentation = copy.deepcopy(record['template'])
        if vmid == primary:
            stack_ui = intent['template'].get('catalog_ui') or {}
            presentation['catalog_ui'] = {**stack_ui, **(presentation.get('catalog_ui') or {})}
            if not (presentation.get('first_run') or {}).get('endpoints'):
                presentation['first_run'] = intent['template'].get('first_run') or {}
        ip_result = subprocess.run(['lxc-info', '-n', str(vmid), '-iH'],
                                   capture_output=True, text=True, timeout=5)
        ip = next((line.strip() for line in ip_result.stdout.splitlines()
                   if re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', line.strip())), '')
        description = render(presentation, plan['image']['manifest_digest'],
                             record['installation_id'], ip)
        subprocess.run(['pct', 'set', str(vmid), '--description', description], check=True)
        instances.finish(root, vmid, plan['archive_path'], plan['image']['manifest_digest'])
        record = instances.read(root, vmid)
        plan = record['deployment']
        # Store raw config: repeated LXC directives must not be collapsed.
        plan['native_config'] = record['observed']['config']
        if plan.get('rootfs_replay'):
            try:
                plan['member_replay_projection'] = oci_stack_replay.normalize(record)
                plan.pop('member_replay_projection_error', None)
            except (ValueError, KeyError):
                # Recording an unsupported projection must not roll back a
                # healthy installation; it remains blocked for management.
                plan.pop('member_replay_projection', None)
                plan['member_replay_projection_error'] = 'native-config-requires-reviewed-conversion'
        mounts = []
        for line in plan['native_config'].splitlines():
            key, sep, value = line.partition(': ')
            if sep and key.startswith('mp') and key[2:].isdigit():
                parts = value.split(',')
                options = dict(p.split('=', 1) for p in parts[1:] if '=' in p)
                mounts.append({'container_path': options['mp'], 'source': parts[0],
                               'type': 'host-bind' if parts[0].startswith('/') else 'managed-volume',
                               'backup': options.get('backup') == '1',
                               'read_only': options.get('ro') == '1', 'existing_volume': True})
        plan['mounts'] = mounts
        services.append({'name': member['name'], 'vmid': vmid, 'deployment': plan})
    path = instances.location(root, primary).parent / 'stack-assembly.json'
    if not path.exists():
        instances.save_assembly(root, primary, intent['template'], intent['deployment'], services)
    instances.resume_assembly(root, primary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('begin')
    p.add_argument('primary', type=int)
    for option in ('template', 'deployment', 'adapter'):
        p.add_argument('--' + option, required=True)
    p.add_argument('--member', action='append', nargs=4, required=True)
    p = sub.add_parser('create')
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    for action in ('finalize', 'failed'):
        p = sub.add_parser(action)
        p.add_argument('primary', type=int)
    p = sub.add_parser('capture-rootfs')
    p.add_argument('vmid', type=int)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    try:
        with instances.locked(instances.ROOT):
            if args.action == 'begin':
                begin(instances.ROOT, args.primary, json.loads(Path(args.template).read_text()),
                      json.loads(Path(args.deployment).read_text()), args.member, args.adapter)
            elif args.action == 'create':
                return create(instances.ROOT, args.arguments)
            elif args.action == 'finalize':
                finalize(instances.ROOT, args.primary)
            elif args.action == 'capture-rootfs':
                capture_rootfs(instances.ROOT, args.vmid)
            else:
                parent = instances.read(instances.ROOT, args.primary)
                for member in parent['native_stack_intent']['members']:
                    record = instances.read(instances.ROOT, member['vmid'])
                    record['status'] = 'failed'
                    instances.write(instances.location(instances.ROOT, member['vmid']), record)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {translate('The stack registry is incomplete; review the private contracts.')} ({exc})",
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
