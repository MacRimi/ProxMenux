#!/usr/bin/env python3
"""Native, coordinated updates of portable generic OCI stacks on the local node."""
import argparse
import copy
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import time
import uuid

import oci_image_cache as image_cache
import oci_instances as instances
import oci_instance_transaction as member_tx
import oci_stack_plan
import oci_stack_transaction as stack_tx
import oci_stack_replay as replay
from oci_installation_state import image_from_archive, parse_config, private_directory, sha
from oci_update_current import resolve_archive
from oci_ui import translate, msg_info, msg_ok, msg_warn, msg_error


def validate_database_transition(previous, candidate):
    def major(image):
        values = image.get('defaults', {}).get('Env') or []
        return next((value.split('=', 1)[1] for value in values
                     if isinstance(value, str) and value.startswith('PG_MAJOR=')), None)
    old, new = major(previous), major(candidate)
    if old is not None and old != new:
        raise ValueError(translate('The new image changes the PostgreSQL major version; the data must be migrated before updating'))


def nextcloud_plan(primary, records, inventory, lifecycle):
    """Translate only the known three-member stack and retain rollback contracts."""
    intent = primary.get('native_stack_intent', {})
    if intent.get('adapter', {}).get('name') != 'install_nextcloud_stack.sh':
        raise ValueError(f"{translate('Unrecognized stack adapter:')} Nextcloud")
    translated = {vmid: replay.nextcloud_record(record) for vmid, record in records.items()}
    roles = {record['deployment']['replay_profile']['role']: vmid
             for vmid, record in translated.items()}
    if len(translated) != 3 or set(roles) != {'application', 'cache', 'database'} or roles['application'] != primary['vmid']:
        raise ValueError(f"{translate('Unrecognized stack structure:')} Nextcloud")
    dependencies = lifecycle.get('dependencies', [])
    if (lifecycle.get('schema') != 1
            or [d.get('vmid') for d in dependencies] != [roles['database'], roles['cache']]):
        raise ValueError(f"{translate('Unrecognized dependency order of the stack:')} Nextcloud")
    services = [{'vmid': d['vmid'], 'name': d['label'], 'healthcheck': copy.deepcopy(d['healthcheck'])}
                for d in dependencies]
    services.append({'vmid': primary['vmid'], 'name': 'Nextcloud', 'healthcheck': {
        'type': 'exec', 'timeout_seconds': 600, 'argv': ['php', '-r',
            '$s=json_decode(file_get_contents("http://127.0.0.1/status.php"),true);'
            'exit(is_array($s)&&!empty($s["installed"])&&empty($s["maintenance"])'
            '&&empty($s["needsDbUpgrade"])?0:1);']}})
    parent = translated[primary['vmid']]
    parent['stack']['deployment']['services'] = services
    parent['stack']['members'] = []
    for service in services:
        snapshot = copy.deepcopy(translated[service['vmid']])
        snapshot.pop('stack', None)
        parent['stack']['members'].append(snapshot)
    plan = oci_stack_plan.build(parent, translated, inventory, 'update')
    plan['original_members'] = copy.deepcopy(list(records.values()))
    plan['nextcloud_replay'] = True
    return plan


def paperless_plan(primary, records, inventory, lifecycle):
    """Prepare the known Paperless stack without publishing translated recipes."""
    if primary.get('native_stack_intent', {}).get('adapter', {}).get('name') != 'install_paperless_stack.sh':
        raise ValueError(f"{translate('Unrecognized stack adapter:')} Paperless")
    translated = {vmid: replay.paperless_record(record) for vmid, record in records.items()}
    roles = {r['deployment']['replay_profile']['role']: vmid for vmid, r in translated.items()}
    if len(translated) != 3 or set(roles) != {'application', 'database', 'broker'} or roles['application'] != primary['vmid']:
        raise ValueError(f"{translate('Unrecognized stack structure:')} Paperless")
    dependencies = lifecycle.get('dependencies', [])
    if lifecycle.get('schema') != 1 or [d.get('vmid') for d in dependencies] != [roles['database'], roles['broker']]:
        raise ValueError(f"{translate('Unrecognized dependency order of the stack:')} Paperless")
    services = [{'vmid': d['vmid'], 'name': d['label'], 'healthcheck': copy.deepcopy(d['healthcheck'])}
                for d in dependencies]
    services.append({'vmid': primary['vmid'], 'name': 'Paperless', 'healthcheck': {
        'type': 'exec', 'timeout_seconds': 600, 'argv': ['python3', '-c',
            'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/", timeout=10).read(1)']}})
    parent = translated[primary['vmid']]
    parent['stack']['deployment']['services'] = services
    parent['stack']['members'] = []
    for service in services:
        snapshot = copy.deepcopy(translated[service['vmid']])
        snapshot.pop('stack', None)
        parent['stack']['members'].append(snapshot)
    plan = oci_stack_plan.build(parent, translated, inventory, 'update')
    plan['original_members'] = copy.deepcopy(list(records.values()))
    plan['paperless_replay'] = True
    return plan


def tandoor_plan(primary, records, inventory, lifecycle):
    """Prepare exactly the application and PostgreSQL without publishing state."""
    if primary.get('native_stack_intent', {}).get('adapter', {}).get('name') != 'install_tandoor_stack.sh':
        raise ValueError(f"{translate('Unrecognized stack adapter:')} Tandoor")
    translated = {vmid: replay.tandoor_record(record) for vmid, record in records.items()}
    roles = {r['deployment']['replay_profile']['role']: vmid for vmid, r in translated.items()}
    if len(translated) != 2 or set(roles) != {'application', 'database'} or roles['application'] != primary['vmid']:
        raise ValueError(f"{translate('Unrecognized stack structure:')} Tandoor")
    dependencies = lifecycle.get('dependencies', [])
    if lifecycle.get('schema') != 1 or [d.get('vmid') for d in dependencies] != [roles['database']]:
        raise ValueError(f"{translate('Unrecognized dependency order of the stack:')} Tandoor")
    services = [{'vmid': d['vmid'], 'name': d['label'], 'healthcheck': copy.deepcopy(d['healthcheck'])}
                for d in dependencies]
    services.append({'vmid': primary['vmid'], 'name': 'Tandoor', 'healthcheck': {
        'type': 'exec', 'timeout_seconds': 600, 'argv': ['python3', '-c',
            'import urllib.request; urllib.request.urlopen("http://127.0.0.1/", timeout=10).read(1)']}})
    parent = translated[primary['vmid']]
    parent['stack']['deployment']['services'] = services
    parent['stack']['members'] = []
    for service in services:
        snapshot = copy.deepcopy(translated[service['vmid']])
        snapshot.pop('stack', None)
        parent['stack']['members'].append(snapshot)
    plan = oci_stack_plan.build(parent, translated, inventory, 'update')
    plan['original_members'] = copy.deepcopy(list(records.values()))
    plan['tandoor_replay'] = True
    return plan


def immich_plan(primary, records, inventory, lifecycle):
    if primary.get('native_stack_intent', {}).get('adapter', {}).get('name') != 'install_immich_stack.sh':
        raise ValueError(f"{translate('Unrecognized stack adapter:')} Immich")
    translated = {vmid: replay.immich_record(record) for vmid, record in records.items()}
    roles = {r['deployment']['replay_profile']['role']: vmid for vmid, r in translated.items()}
    if len(translated) != 4 or set(roles) != {'server', 'database', 'valkey', 'machine-learning'} or roles['server'] != primary['vmid']:
        raise ValueError(f"{translate('Unrecognized stack structure:')} Immich")
    dependencies = lifecycle.get('dependencies', [])
    if lifecycle.get('schema') != 1 or [d.get('vmid') for d in dependencies] != [roles['database'], roles['valkey'], roles['machine-learning']]:
        raise ValueError(f"{translate('Unrecognized dependency order of the stack:')} Immich")
    services = [{'vmid': d['vmid'], 'name': d['label'], 'healthcheck': copy.deepcopy(d['healthcheck'])} for d in dependencies]
    services.append({'vmid': primary['vmid'], 'name': 'Immich', 'healthcheck': {
        'type': 'exec', 'timeout_seconds': 600, 'argv': ['node', '-e',
            'fetch("http://127.0.0.1:2283/api/server/ping").then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))']}})
    parent = translated[primary['vmid']]
    parent['stack']['deployment']['services'] = services
    parent['stack']['members'] = []
    for service in services:
        snapshot = copy.deepcopy(translated[service['vmid']])
        snapshot.pop('stack', None)
        parent['stack']['members'].append(snapshot)
    plan = oci_stack_plan.build(parent, translated, inventory, 'update')
    plan['original_members'] = copy.deepcopy(list(records.values()))
    plan['immich_replay'] = True
    return plan


class NativeAdapter:
    def __init__(self, root, journal, plan, acknowledge_external_data=False):
        self.root, self.journal, self.plan = root, Path(journal), plan
        self.records = {m['vmid']: copy.deepcopy(m) for m in plan['members']}
        self.original_records = {m['vmid']: copy.deepcopy(m)
                                 for m in plan.get('original_members', plan['members'])}
        primary = self.records[plan['primary_vmid']]
        self.services = {s['vmid']: s for s in primary['stack']['deployment']['services']}
        self.acknowledge = acknowledge_external_data

    def state(self):
        return json.loads(self.journal.read_text())

    def describe(self, vmid):
        name = self.services.get(vmid, {}).get('name')
        return f'{name} (CT {vmid})' if name else f'CT {vmid}'

    def validate(self, plan):
        resources = json.loads(instances.command('pvesh', 'get', '/cluster/resources',
            '--type', 'vm', '--output-format', 'json'))
        if not isinstance(resources, list):
            raise ValueError(translate('Incomplete Proxmox inventory'))
        inventory = {}
        for row in resources:
            if (not isinstance(row, dict) or type(row.get('vmid')) is not int
                    or row.get('type') not in ('lxc', 'qemu')):
                raise ValueError(translate('Invalid Proxmox inventory'))
            if row['vmid'] in inventory:
                raise ValueError(translate('Duplicated VMID in the Proxmox inventory'))
            inventory[row['vmid']] = row
        for vmid, record in self.records.items():
            row = inventory.get(vmid)
            if row:
                if row['type'] != 'lxc' or row.get('node') != socket.gethostname().split('.')[0]:
                    raise ValueError(translate('A member VMID is in use by another guest or is on another node'))
                config = instances.command('pct', 'config', str(vmid))
                if instances.identity(config) != record['installation_id']:
                    raise ValueError(translate('The identity of a member was replaced'))
                if (not self.journal.exists() or not self.state().get('replacement_intent')) and sha(config) != record['observed']['config_sha256']:
                    raise ValueError(translate('A member configuration changed during the preparation'))
            else:
                if Path('/etc/pve/lxc/%s.conf' % vmid).exists():
                    raise ValueError(translate('The Proxmox inventory and the local configurations differ'))
                if not self.journal.exists() or not self.state().get('replacement_intent'):
                    raise ValueError(translate('A member is missing before the replacement'))
            current = instances.read(self.root, vmid)
            if current['installation_id'] != record['installation_id']:
                raise ValueError(translate('The record belongs to another container'))
            pending = current.get('pending_stack_transaction')
            if pending and pending != str(self.journal):
                raise ValueError(translate('Another stack operation is pending'))

    def preflight(self):
        self.validate(self.plan)
        ha = json.loads(instances.command('pvesh', 'get', '/cluster/ha/resources', '--output-format', 'json'))
        if not isinstance(ha, list) or any(r.get('sid') == 'ct:%s' % vmid for r in ha for vmid in self.records):
            raise ValueError(translate('High availability resources are not supported for stacks'))
        for vmid, record in self.records.items():
            if record.get('pending_transaction') or record.get('pending_stack_transaction'):
                raise ValueError(translate('A member has a pending operation'))
            if record['deployment'].get('post_start_configurations'):
                raise ValueError(translate('The recipe requires configuration at startup; its coordinated replay is not available'))
            config = instances.command('pct', 'config', str(vmid))
            member_tx.preflight(record, record, config, coordinated=True)
            member_tx.freeze_host_sources(record, record, self.acknowledge)
            check = self.services[vmid].get('healthcheck', {})
            if check.get('type') not in ('exec', 'http', 'running'):
                raise ValueError(translate('A member has no reproducible service check'))
            if check['type'] == 'exec' and not check.get('argv'):
                raise ValueError(translate('Empty exec service check'))
            if check['type'] == 'exec' and (not isinstance(check['argv'], list)
                    or any(not isinstance(arg, str) or not arg or '\0' in arg for arg in check['argv'])):
                raise ValueError(translate('Invalid service check arguments'))
            if check['type'] == 'http' and not check.get('url'):
                raise ValueError(translate('HTTP service check without a saved URL'))
            if check['type'] == 'http' and not check['url'].startswith(('http://', 'https://')):
                raise ValueError(translate('Invalid service check URL'))
            if not 0 < int(check.get('timeout_seconds', 120)) <= 3600:
                raise ValueError(translate('Invalid service check timeout'))
        primary_id = self.plan['primary_vmid']
        cfg = parse_config(instances.command('pct', 'config', str(primary_id)))
        volume = cfg.get('hookscript', '')
        if not volume.endswith(':snippets/proxmenux-stack-dependencies.sh'):
            raise ValueError(translate('The stack does not have the expected native hook'))
        hook = Path(instances.command('pvesm', 'path', volume).decode().strip())
        info = hook.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or hook.read_bytes() != Path(__file__).with_name('stack_dependency_hook.sh').read_bytes()):
            raise ValueError(translate('The dependency hook was modified; review it before updating'))
        lifecycle = Path('/etc/pve/priv/proxmenux-stack-%s.json' % primary_id)
        info = lifecycle.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError(translate('Unsafe dependency hook contract'))
        spec = json.loads(lifecycle.read_text())
        expected = [{'vmid': s['vmid'], 'label': s['name'], 'healthcheck': s['healthcheck']}
                    for s in self.services.values() if s['vmid'] != primary_id and not s.get('deferred_setup')]
        if spec.get('schema') != 1 or spec.get('dependencies') != expected:
            raise ValueError(translate('The dependency hook and the stack recipe differ'))
        member_tx.require_backup_space(self.journal.parent, list(self.records))

    def is_running(self, vmid):
        return instances.command('pct', 'status', str(vmid)).strip() == b'status: running'

    def prepare(self, record, operation):
        for vmid in self.records:
            current = instances.read(self.root, vmid)
            current['pending_stack_transaction'] = str(self.journal)
            instances.write(instances.location(self.root, vmid), current)
        config = instances.command('pct', 'config', str(record['vmid']))
        archive, digest = resolve_archive(record, config)
        image = image_from_archive(str(archive))
        old = record['observed']['image']
        validate_database_transition(old, image)
        if image['architecture'] != old['architecture'] or image['os'] != 'linux':
            raise ValueError(translate('Incompatible image platform'))
        paths = [m['container_path'] for m in record['deployment'].get('mounts', [])]
        if any(not any(p == target or p.startswith(target.rstrip('/') + '/') for target in paths)
               for p in (image['defaults'].get('Volumes') or {})):
            raise ValueError(translate('The new image requires additional persistent paths'))
        profile = record['deployment'].get('replay_profile', {})
        if profile.get('adapter') in ('install_nextcloud_stack.sh', 'install_paperless_stack.sh', 'install_tandoor_stack.sh', 'install_immich_stack.sh'):
            msg_info(f"{translate('Checking the new image without starting it:')} {self.describe(record['vmid'])}")
            self.probe_nextcloud_image(record, archive, image)
            msg_ok(f"{translate('New image compatible:')} {self.describe(record['vmid'])}")
        return {'archive': str(archive), 'digest': digest}

    def probe_nextcloud_image(self, record, archive, image):
        """Import but never start a disposable rootfs before stopping the stack."""
        vmid = int(instances.command('pvesh', 'get', '/cluster/nextid').strip())
        marker = 'proxmenux-image-probe=' + uuid.uuid4().hex
        directory = self.journal.parent / 'image-probes'
        private_directory(directory)
        descriptor = directory / ('%s.json' % vmid)
        instances.write(descriptor, {'vmid': vmid, 'marker': marker})
        mounted = False
        try:
            member_tx.log('image probe: CT %s' % record['vmid'])
            root = record['deployment']['rootfs']
            member_tx.run('pct', 'create', str(vmid), str(archive), '--rootfs',
                '%s:%s' % (root['storage'], root['size_gb']), '--hostname', 'oci-image-probe',
                '--ostype', 'unmanaged', '--unprivileged', '1', '--memory', '128',
                '--cores', '1', '--onboot', '0', '--description', marker)
            member_tx.owned(vmid, marker)
            member_tx.run('pct', 'mount', str(vmid))
            mounted = True
            profile = record['deployment']['replay_profile']
            check = {'install_paperless_stack.sh': replay.paperless_prerequisites,
                     'install_nextcloud_stack.sh': replay.nextcloud_prerequisites,
                     'install_tandoor_stack.sh': replay.tandoor_prerequisites,
                     'install_immich_stack.sh': replay.immich_prerequisites}[profile['adapter']]
            check(Path('/var/lib/lxc') / str(vmid) / 'rootfs', profile['role'], image)
        finally:
            if mounted:
                member_tx.run('pct', 'unmount', str(vmid))
            if Path('/etc/pve/lxc/%s.conf' % vmid).exists():
                member_tx.owned(vmid, marker)
                member_tx.run('pct', 'destroy', str(vmid))
            descriptor.unlink()

    def stop(self, vmid):
        self.validate(self.plan)
        if Path('/etc/pve/lxc/%s.conf' % vmid).exists():
            member_tx.stop(vmid)

    def backup(self, vmid, identity):
        self.validate(self.plan)
        directory = self.journal.parent / ('backup-%s' % vmid)
        private_directory(directory)
        member_tx.run('vzdump', str(vmid), '--mode', 'stop', '--compress', 'zstd',
                      '--dumpdir', str(directory), '--tmpdir', '/var/tmp')
        backups = list(directory.glob('vzdump-lxc-*.tar.zst'))
        if len(backups) != 1:
            raise ValueError(translate('The backup of a member could not be identified'))
        member_tx.run('zstd', '-t', str(backups[0]))
        return {'archive': str(backups[0]), 'sha256': member_tx.filehash(backups[0])}

    def verify_backups(self, backups):
        for backup in backups.values():
            if member_tx.filehash(backup['archive']) != backup['sha256']:
                raise ValueError(translate('A backup was modified'))
            member_tx.run('zstd', '-t', backup['archive'])

    def replace(self, vmid, prepared, identity):
        self.validate(self.plan)
        state = self.state()
        context = {'journal': str(self.journal), 'id': identity,
                   'backup': state['backups'][str(vmid)]}
        if self.plan.get('nextcloud_replay'):
            context.update(nextcloud_replay=True, effective_record=self.records[vmid])
        if self.plan.get('paperless_replay'):
            context.update(paperless_replay=True, effective_record=self.records[vmid])
        if self.plan.get('tandoor_replay'):
            context.update(tandoor_replay=True, effective_record=self.records[vmid])
        if self.plan.get('immich_replay'):
            context.update(immich_replay=True, effective_record=self.records[vmid])
        member_tx.apply(self.root, vmid, Path(prepared['archive']), 'update',
            registry_digest=prepared['digest'], acknowledge_external_data=self.acknowledge,
            coordinated=context, progress=f"{translate('Updating')} {self.describe(vmid)}:")

    def start(self, vmid):
        self.validate(self.plan)
        if not self.is_running(vmid):
            member_tx.run('pct', 'start', str(vmid))

    def healthcheck(self, vmid):
        check = self.services[vmid]['healthcheck']
        timeout = int(check.get('timeout_seconds', 120))
        if not 0 < timeout <= 3600:
            raise ValueError(translate('Invalid service check timeout'))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running(vmid):
                raise ValueError(f"{translate('A member stopped:')} {self.describe(vmid)}")
            try:
                if check['type'] == 'exec':
                    member_tx.run('pct', 'exec', str(vmid), '--', *check['argv'])
                elif check['type'] == 'http':
                    member_tx.run('curl', '-fsS', '--noproxy', '*', '--max-time', '5', check['url'])
                member_tx.gpu_devices.validate_runtime(vmid, self.records[vmid]['deployment'])
                deployment = self.records[vmid]['deployment']
                if deployment.get('replay_profile') == {'adapter': 'install_immich_stack.sh', 'role': 'machine-learning'}:
                    acceleration = deployment.get('machine_learning', {}).get('acceleration', 'cpu')
                    if acceleration in ('openvino', 'cuda'):
                        member_tx.run('pct', 'exec', str(vmid), '--', 'python', '-c',
                            'import sys,ctypes,onnxruntime as ort; p=sys.argv[1]; '
                            'assert ("OpenVINOExecutionProvider" if p=="openvino" else "CUDAExecutionProvider") '
                            'in ort.get_available_providers(); '
                            'assert (any(d.startswith("GPU") for d in ort.capi._pybind_state.get_available_openvino_device_ids()) '
                            'if p=="openvino" else ctypes.CDLL("libcuda.so.1").cuInit(0)==0)', acceleration)
                return
            except RuntimeError:
                time.sleep(2)
        raise ValueError(f"{translate('A member did not pass its service check:')} {self.describe(vmid)}")

    def validate_candidates(self, state):
        self.validate(self.plan)
        for vmid, original in self.records.items():
            current = instances.read(self.root, vmid)
            journal = Path(current['pending_transaction'])
            child = json.loads(journal.read_text())
            if child.get('coordinated', {}).get('id') != state['id']:
                raise ValueError(translate('A member operation does not belong to the stack'))
            config = instances.command('pct', 'config', str(vmid))
            if sha(config) != child.get('staged_config_sha256'):
                raise ValueError(translate('The configuration of a new member changed after it was created'))
            member_tx.check_runtime_mounts(config, original['deployment'])
            member_tx.gpu_devices.check(config, original['deployment'])
            child['candidate_host_sources'] = member_tx.candidate_host_sources(journal, child)
            child['validated_config_sha256'] = sha(config)
            instances.write(journal, child)

    def restore_running_state(self, running, order):
        for vmid in order:
            if running[str(vmid)]:
                self.start(vmid)
        for vmid in order:
            if running[str(vmid)]:
                self.healthcheck(vmid)
        # Starting the primary can start dependencies through its native hook.
        for vmid in reversed(order):
            if not running[str(vmid)]:
                self.stop(vmid)
        if not self.state()['replacement_intent']:
            self.restore_contracts(self.plan, self.state()['id'])

    def publish(self, state):
        for vmid, original in self.records.items():
            current = instances.read(self.root, vmid)
            journal = Path(current['pending_transaction'])
            child = json.loads(journal.read_text())
            before = member_tx.owned(vmid, original['installation_id'])
            if sha(before) != child.get('validated_config_sha256'):
                raise ValueError(translate('A member configuration changed after the stack was checked'))
            # Keep child journals available even if publication is interrupted.
            links = self.journal.parent / ('member-%s.json' % vmid)
            instances.write(links, {'journal': str(journal)})
            member_tx.run('pct', 'set', str(vmid), '--onboot', '1' if original['deployment']['onboot'] else '0')
            after = member_tx.owned(vmid, original['installation_id'])
            if ([line for line in before.splitlines() if not line.startswith(b'onboot: ')]
                    != [line for line in after.splitlines() if not line.startswith(b'onboot: ')]):
                raise ValueError(translate('Concurrent change while restoring the start at boot setting'))
            child['validated_config_sha256'] = sha(after)
            member_tx.checkpoint(journal, child, 'health-passed')
            member_tx.commit(self.root, journal, child)
        primary_id = self.plan['primary_vmid']
        primary = instances.read(self.root, primary_id)
        primary['stack']['members'] = []
        for vmid in self.plan['start_order']:
            record = instances.read(self.root, vmid)
            record.pop('stack', None)
            record.pop('pending_stack_transaction', None)
            primary['stack']['members'].append(record)
        instances.write(instances.location(self.root, primary_id), primary)

    def restore(self, vmid, backup, identity):
        self.validate(self.plan)
        original = self.records[vmid]
        current = instances.read(self.root, vmid)
        link = self.journal.parent / ('member-%s.json' % vmid)
        child_path = current.get('pending_transaction')
        if not child_path and link.exists():
            child_path = json.loads(link.read_text())['journal']
        if child_path:
            journal = Path(child_path)
            synthetic = self.journal.parent / ('recovery-%s' % vmid) / 'transaction.json'
            if (not journal.resolve().is_relative_to(instances.location(self.root, vmid).parent.resolve())
                    and journal.resolve() != synthetic.resolve()):
                raise ValueError(translate('The member journal is outside the registry'))
            child = json.loads(journal.read_text())
            if child.get('coordinated', {}).get('id') != identity:
                raise ValueError(translate('The member journal belongs to another stack operation'))
            if child['phase'] == 'rolled-back':
                if sha(member_tx.owned(vmid, original['installation_id'])) != child['restore_config_sha256']:
                    raise ValueError(translate('A member was modified after it was recovered'))
                member_tx.cleanup_restored_format_dirs(vmid, original['deployment'], original['installation_id'])
                return
        else:
            directory = self.journal.parent / ('recovery-%s' % vmid)
            private_directory(directory)
            journal = directory / 'transaction.json'
            if journal.exists():
                child = json.loads(journal.read_text())
            else:
                sources, _ = member_tx.freeze_host_sources(original, original, self.acknowledge)
                child = {'id': uuid.uuid4().hex, 'vmid': vmid, 'record': original,
                    'candidate_contract': original, 'before_config': original['observed']['config'],
                    'backup': backup['archive'], 'backup_sha256': backup['sha256'],
                    'backup_compression': 'zstd', 'was_running': False,
                    'original_host_sources': sources,
                    'original_gpu_devices': member_tx.gpu_devices.planned(original['deployment']),
                    'coordinated': {'id': identity}, 'phase': 'backup-ready'}
                instances.write(journal, child)
            instances.write(link, {'journal': str(journal)})
        if not child.get('stage'):
            child['stage'] = int(instances.command('pvesh', 'get', '/cluster/nextid').strip())
            instances.write(journal, child)
        stage = child['stage']
        if not Path('/etc/pve/lxc/%s.conf' % stage).exists():
            archive = self.state()['prepared'][str(vmid)]['archive']
            member_tx.run('pct', 'create', str(stage), archive, '--rootfs',
                '%s:%s' % (original['deployment']['rootfs']['storage'], original['deployment']['rootfs']['size_gb']),
                '--hostname', 'oci-stack-recovery-holder', '--ostype', 'unmanaged',
                '--unprivileged', '1', '--memory', '128', '--cores', '1', '--onboot', '0',
                '--description', 'proxmenux-transaction=' + child['id'])
        pending = copy.deepcopy(original)
        pending.update(status='updating', pending_transaction=str(journal), transaction_id=child['id'],
                       pending_stack_transaction=str(self.journal))
        instances.write(instances.location(self.root, vmid), pending)
        child['record'] = copy.deepcopy(child['record'])
        child['record']['pending_stack_transaction'] = str(self.journal)
        child.update(backup=backup['archive'], backup_sha256=backup['sha256'], backup_compression='zstd')
        child['phase'] = 'backup-ready'
        instances.write(journal, child)
        member_tx.recover(self.root, journal)

    def restore_contracts(self, plan, identity):
        self.validate(plan)
        for vmid, original in self.original_records.items():
            record = copy.deepcopy(original)
            config = member_tx.owned(vmid, record['installation_id'])
            record['observed'] = instances.observe(vmid, record['installation_id'],
                original['observed']['archive_path'], original['observed']['resolved_registry_digest'],
                original['observed']['image'])
            if any(self.plan.get(flag) for flag in ('nextcloud_replay', 'paperless_replay', 'tandoor_replay', 'immich_replay')):
                record['deployment']['native_config'] = record['observed']['config']
                record['deployment']['member_replay_projection'] = replay.normalize(record)
            record['pending_stack_transaction'] = str(self.journal)
            instances.write(instances.location(self.root, vmid), record)
        primary_id = plan['primary_vmid']
        primary = instances.read(self.root, primary_id)
        snapshots = []
        for vmid in plan['start_order']:
            snapshot = instances.read(self.root, vmid)
            snapshot.pop('stack', None)
            snapshot.pop('pending_stack_transaction', None)
            snapshots.append(snapshot)
        primary['stack']['members'] = snapshots
        instances.write(instances.location(self.root, primary_id), primary)

    def finalize(self, state):
        if state['phase'] not in stack_tx.TERMINAL:
            raise ValueError(translate('The stack operation has not finished yet'))
        self.validate(self.plan)
        probes = self.journal.parent / 'image-probes'
        if probes.exists():
            for descriptor in probes.glob('*.json'):
                probe = json.loads(descriptor.read_text())
                vmid, marker = probe['vmid'], probe['marker']
                if type(vmid) is not int or not marker.startswith('proxmenux-image-probe='):
                    raise ValueError(translate('Invalid image probe descriptor'))
                if Path('/etc/pve/lxc/%s.conf' % vmid).exists():
                    member_tx.owned(vmid, marker)
                    if self.is_running(vmid):
                        raise ValueError(translate('An image probe container was started externally'))
                    if os.path.ismount('/var/lib/lxc/%s/rootfs' % vmid):
                        member_tx.run('pct', 'unmount', str(vmid))
                    member_tx.run('pct', 'destroy', str(vmid))
                descriptor.unlink()
        # Clear the primary last so interrupted cleanup remains discoverable.
        order = [vmid for vmid in self.records if vmid != self.plan['primary_vmid']]
        order.append(self.plan['primary_vmid'])
        for vmid in order:
            record = instances.read(self.root, vmid)
            record.pop('pending_stack_transaction', None)
            instances.write(instances.location(self.root, vmid), record)
        try:
            self.release_stages()
            self.prune_backups(include_current=state['phase'] == 'committed')
            for path, _ in image_cache.prune(self.root, lock=False):
                member_tx.log(f'removed unused image archive: {path}')
        except (OSError, ValueError) as exc:
            member_tx.log(f'cleanup: {exc}')

    def release_stages(self):
        """The temporary containers that held the data of each member; one
        that still has a disk attached is kept."""
        for vmid in self.records:
            folder = instances.location(self.root, vmid).parent / 'transactions'
            for member_journal in folder.glob('*/transaction.json'):
                try:
                    state = json.loads(member_journal.read_text())
                except (OSError, ValueError):
                    continue
                if (state.get('coordinated') or {}).get('journal') == str(self.journal):
                    member_tx.release_stage(state)

    def prune_backups(self, include_current):
        """The backups of closed operations are removed, those of this one
        when the stack works with its new images; journals and logs stay."""
        for directory in self.journal.parent.parent.iterdir():
            if ((directory == self.journal.parent and not include_current)
                    or directory.is_symlink() or not directory.is_dir()):
                continue
            try:
                phase = json.loads((directory / 'transaction.json').read_text()).get('phase')
            except (OSError, ValueError):
                continue
            if phase in stack_tx.TERMINAL:
                for backup in directory.glob('backup-*/vzdump-lxc-*'):
                    if backup.is_file() and not backup.is_symlink():
                        backup.unlink()


# The stack journal of this run, for the summary after a failure.
_current = {'journal': None, 'primary': None}


def run(vmid, recover=False, acknowledge_external_data=False):
    root = instances.ROOT
    msg_info(translate('Checking the interrupted stack operation...') if recover
             else translate('Checking the stack before the update...'))
    with instances.locked(root):
        selected = instances.read(root, vmid)
        primary_id = selected.get('stack_member', {}).get('primary_vmid', vmid)
        primary = instances.read(root, primary_id)
        _current['primary'] = primary_id
        if recover:
            journal = Path(primary['pending_stack_transaction'])
            if not journal.resolve().is_relative_to(instances.location(root, primary_id).parent.resolve()):
                raise ValueError(translate('The stack journal is outside the registry'))
            member_tx.open_log(journal.parent)
            _current['journal'] = journal
            state = json.loads(journal.read_text())
            if state.get('plan', {}).get('primary_vmid') != primary_id:
                raise ValueError(translate('The journal belongs to another stack'))
            if any(mount['type'] == 'host-bind' for member in state['plan']['members']
                   for mount in member.get('deployment', {}).get('mounts', [])) and not acknowledge_external_data:
                raise ValueError(translate('Confirm that host data is not reverted'))
            adapter = NativeAdapter(root, journal, state['plan'], acknowledge_external_data)
            if state.get('phase') in stack_tx.TERMINAL:
                msg_ok(translate('The stack operation had already finished'))
                msg_info(translate('Completing its final cleanup...'))
                result = stack_tx.execute(journal, adapter)
                msg_ok(translate('Final cleanup of the stack operation completed'))
                return result
            msg_ok(translate('Interrupted stack operation found'))
            result = stack_tx.execute(journal, adapter)
            msg_ok(translate('Stack recovery completed; every member is back to its previous installation.'))
            return result
        records, inventory = {}, {}
        for snapshot in primary['stack']['members']:
            member_id = snapshot['vmid']
            records[member_id] = instances.read(root, member_id)
            inventory[member_id] = instances.identity(instances.command('pct', 'config', str(member_id)))
        adapter_name = primary.get('native_stack_intent', {}).get('adapter', {}).get('name')
        builders = {'install_nextcloud_stack.sh': nextcloud_plan,
                    'install_paperless_stack.sh': paperless_plan,
                    'install_tandoor_stack.sh': tandoor_plan,
                    'install_immich_stack.sh': immich_plan}
        if adapter_name in builders:
            lifecycle = Path('/etc/pve/priv/proxmenux-stack-%s.json' % primary_id)
            info = lifecycle.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
                raise ValueError(translate('Unsafe dependency contract'))
            builder = builders[adapter_name]
            plan = builder(primary, records, inventory, json.loads(lifecycle.read_text()))
        else:
            plan = oci_stack_plan.build(primary, records, inventory, 'update')
        stack_tx.validate_plan(plan)
        directory = instances.location(root, primary_id).parent / 'stack-transactions' / uuid.uuid4().hex
        private_directory(directory)
        member_tx.open_log(directory)
        journal = directory / 'transaction.json'
        _current['journal'] = journal
        adapter = NativeAdapter(root, journal, plan, acknowledge_external_data)
        adapter.preflight()
        msg_ok(f"{translate('Stack checked:')} {len(plan['members'])} {translate('containers')}")
        if any(mount['type'] == 'host-bind' for member in plan['members']
               for mount in member.get('deployment', {}).get('mounts', [])):
            msg_warn(translate('Host directories are not included in the backups and are not reverted by a recovery.'))
        result = stack_tx.execute(journal, adapter, plan)
        msg_ok(translate('Stack update completed. Data kept.'))
        return result


def failure_summary(recovering):
    """What state the stack was left in after a failure, and what to do next."""
    journal = _current['journal']
    if journal is None or not journal.exists():
        return
    try:
        state = json.loads(journal.read_text())
    except (OSError, ValueError):
        state = {}
    phase = state.get('phase')
    try:
        pending = instances.read(instances.ROOT, _current['primary']).get('pending_stack_transaction') == str(journal)
    except (OSError, ValueError, KeyError):
        pending = True
    if phase == 'rolled-back':
        if recovering or state.get('stop_intent'):
            msg_warn(translate('Every member of the stack is back to its previous installation.'))
        else:
            msg_warn(translate('No container of the stack was modified.'))
    elif phase == 'committed':
        msg_warn(translate('The stack update was saved.'))
    else:
        msg_warn(translate('The stack operation stopped halfway. Select the stack again in the OCI management menu to recover it.'))
        return
    if pending:
        msg_warn(translate('Its final cleanup did not complete. Select the stack again in the OCI management menu to complete it.'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmid', type=int)
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--acknowledge-external-data', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges on the Proxmox node are required'))
    try:
        run(args.vmid, args.recover, args.acknowledge_external_data)
        return 0
    except BlockingIOError:
        msg_error(translate('Another OCI operation is using the registry. This operation was not started.'))
        return 1
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        # An error that started an automatic recovery was already shown before it.
        if not getattr(error, 'oci_reported', False):
            member_tx.report_error(error, f'stack-{args.vmid}')
        failure_summary(args.recover)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
