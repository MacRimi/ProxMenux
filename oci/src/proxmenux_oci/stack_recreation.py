"""Modify one container of a multi-container application: its resources, its
variables, its extra paths and devices, and for Immich what runs recognition.

Only the chosen container is changed. Its own data and the other containers
are never part of this operation."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile

from .custom_mounts import edit_paths
from .extra_devices import ask_extra_devices
from .i18n import translate
from .recreation import edit_environment, positive_integer
from .ui import UserCancelled

APPLICATION_ROLES = ('application', 'server')
# Variables whose value is never shown: the passwords and keys of a stack.
SECRET_NAME = re.compile(r'PASS|SECRET|TOKEN|KEY|PWD', re.I)
GPU_NODE = re.compile(r'/dev/dri/(?:renderD|card)[0-9]+|/dev/kfd')
PERIPHERAL_NODE = re.compile(
    r'/dev/(?:apex_[0-9]+|accel/accel[0-9]+|ttyUSB[0-9]+|ttyACM[0-9]+|bus/usb/[0-9]{3}/[0-9]{3})')


def _config(vmid):
    result = subprocess.run(['pct', 'config', str(vmid)], capture_output=True, text=True, check=True)
    lines = [line.partition(': ') for line in result.stdout.splitlines()]
    return {key: value for key, separator, value in lines if separator}


def _options(value):
    return dict(part.split('=', 1) for part in value.split(',')[1:] if '=' in part)


def _device_path(value):
    fields = dict(part.split('=', 1) for part in value.split(',') if '=' in part)
    return fields.get('path') or value.split(',', 1)[0]


def application_members(primary):
    """The members whose paths and devices can be edited: the application of a
    recipe, the main service of a Compose stack, or every application of a
    suite that has no main one."""
    members = primary.get('stack', {}).get('members', [])
    roles = [m for m in members
             if (m.get('deployment', {}).get('replay_profile') or {}).get('role') in APPLICATION_ROLES]
    if roles:
        return roles
    main = (primary.get('stack', {}).get('template') or {}).get('compose_stack', {}).get('main_service')
    named = [m for m in members if (m.get('stack_member') or {}).get('name') == main]
    return named or members


def recipe_paths(member):
    deployment = member.get('deployment', {})
    profile = deployment.get('replay_profile') or {}
    # The engine declares the data paths of each adapter; the menu loads it
    # from the engine directory before any modification.
    import oci_stack_adapters
    own = oci_stack_adapters.application_paths(profile.get('adapter'))
    if own and profile.get('role') in APPLICATION_ROLES:
        return set(own)
    return {mount['container_path'] for mount in deployment.get('mounts', []) if not mount.get('custom')}


def current_state(member):
    """The mounts and devices of the member now, split into its own and the extra ones."""
    config = _config(member['vmid'])
    own = recipe_paths(member)
    immich = (member.get('deployment', {}).get('replay_profile') or {}).get('adapter') == 'install_immich_stack.sh'
    mounts, devices = [], []
    for key, value in config.items():
        if re.fullmatch(r'mp[0-9]+', key):
            source, target = value.split(',', 1)[0], _options(value).get('mp')
            mounts.append({'container_path': target, 'source': source, 'size': _options(value).get('size'),
                           'type': 'host-bind' if source.startswith('/') else 'managed-volume',
                           'read_only': _options(value).get('ro') == '1', 'extra': target not in own})
        elif re.fullmatch(r'dev[0-9]+', key):
            path = _device_path(value)
            # The video device of Immich belongs to its acceleration profile.
            removable = bool(PERIPHERAL_NODE.fullmatch(path)) or (not immich and bool(GPU_NODE.fullmatch(path)))
            devices.append({'host_path': path, 'removable': removable})
    rootfs = config.get('rootfs', 'local-lvm:').split(':', 1)[0]
    return mounts, devices, rootfs, immich


def plan_changes(ui, member):
    """Ask what to remove and what to add. None when nothing changes."""
    mounts, devices, storage, immich = current_state(member)
    changes = {'remove_mounts': [], 'add_mounts': [], 'change_mounts': {}, 'remove_devices': [], 'add_devices': []}
    paths = edit_paths(ui, mounts, storage)
    changes.update(remove_mounts=paths['remove'], add_mounts=paths['add'], change_mounts=paths['change'])
    removable = [device for device in devices if device['removable']]
    if removable:
        kept = ui.checklist(translate('Devices to keep (unmark one to remove it)'),
                            [(device['host_path'], device['host_path']) for device in removable],
                            [device['host_path'] for device in removable])
        if kept is None:
            return None
        changes['remove_devices'] = [device['host_path'] for device in removable if device['host_path'] not in kept]
    attached = [{'host_path': device['host_path'], 'kind': 'character-device'} for device in devices
                if device['host_path'] not in changes['remove_devices']]
    proposed = ask_extra_devices(ui, attached, True, kinds=('usb',) if immich else ('gpu', 'usb'))
    changes['add_devices'] = proposed[len(attached):]
    return changes if any(changes.values()) else None


def summary(member, changes):
    name = (member.get('stack_member') or {}).get('name') or member['vmid']
    lines = [f"{translate('Container')}: CT {member['vmid']} ({name})", '']
    resources = changes.get('resources') or {}
    if resources:
        now = current_resources(member)
        labels = {'cores': translate('Cores'), 'memory_mb': translate('RAM in MiB'), 'swap_mb': translate('Swap in MiB')}
        lines += [f"{labels[key]}: {now[key]} → {value}" for key, value in resources.items()]
    variables = (changes.get('environment') or {}).get('set') or {}
    lines += [f"{translate('Variable')}: {variable}" for variable in sorted(variables)]
    for mount in changes['add_mounts']:
        target = (f"{translate('host directory')} {mount['source']}" if mount['type'] == 'host-bind'
                  else f"{translate('Container volume')} {mount['size_gb']} GB {translate('on')} {mount['source']}")
        lines.append(f"+ {mount['container_path']} → {target}")
    for path, change in changes.get('change_mounts', {}).items():
        if 'source' in change:
            lines.append(f"~ {path} → {translate('host directory')} {change['source']}")
        if 'read_only' in change:
            lines.append(f"~ {path} → {translate('read-only') if change['read_only'] else translate('writable')}")
    lines += [f"- {path}" for path in changes['remove_mounts']]
    lines += [f"+ {device['host_path']}" for device in changes['add_devices']]
    lines += [f"- {path}" for path in changes['remove_devices']]
    lines += ['', translate('CPU, RAM and swap apply to the running container. Variables, paths and devices '
                            'restart a running container; a stopped one is left stopped. The data of the '
                            'application and the configuration of the other containers are not changed. A '
                            'container volume removed here is deleted with the data in it.')]
    return '\n'.join(lines)


def member_label(member):
    name = (member.get('stack_member') or {}).get('name') or (member.get('deployment', {}).get('replay_profile') or {}).get('role') or ''
    return f"CT {member['vmid']} · {name}" if name else f"CT {member['vmid']}"


def current_resources(member):
    """Cores, RAM and swap the container has now."""
    config = _config(member['vmid'])
    cores = config.get('cores') or config.get('cpulimit') or '1'
    return {'cores': max(1, int(float(cores))), 'memory_mb': int(config.get('memory') or 512),
            'swap_mb': int(config.get('swap') or 0)}


def live_environment(vmid):
    """The variables the container has now, as Proxmox stores them."""
    result = subprocess.run(['pct', 'config', str(vmid)], capture_output=True, check=True).stdout.decode()
    entries = []
    for line in result.splitlines():
        if line.startswith('lxc.environment.runtime: '):
            entries.append(line.split(': ', 1)[1])
        elif line.startswith('env: '):
            entries.extend(line.split(': ', 1)[1].split('\0'))
    return dict(entry.split('=', 1) for entry in entries if '=' in entry)


def edit_resources(ui, member):
    """Ask the new cores, RAM and swap. Only what changes is returned."""
    now = current_resources(member)
    wanted = {'cores': positive_integer(ui, translate('Cores'), now['cores']),
              'memory_mb': positive_integer(ui, translate('RAM in MiB'), now['memory_mb'], 128),
              'swap_mb': positive_integer(ui, translate('Swap in MiB'), now['swap_mb'], 0)}
    return {key: value for key, value in wanted.items() if value != now[key]}


def edit_variables(ui, member):
    """Change or add variables with the same questions as any application.
    Only what changes is returned; values are never listed."""
    now = live_environment(member['vmid'])
    recorded = {item['name']: item for item in member.get('deployment', {}).get('environment', [])}
    draft = {'environment': [{'name': name, 'value': value,
                              'sensitive': recorded.get(name, {}).get('sensitive', bool(SECRET_NAME.search(name)))}
                             for name, value in now.items()]}
    edit_environment(draft, ui)
    return {item['name']: item['value'] for item in draft['environment'] if now.get(item['name']) != item['value']}


def immich_learning(primary):
    """The machine learning container of an Immich, or None for any other application."""
    for member in primary.get('stack', {}).get('members', []):
        if member.get('deployment', {}).get('replay_profile') == {'adapter': 'install_immich_stack.sh',
                                                                  'role': 'machine-learning'}:
            return member
    return None


def recognition_choices(storage):
    """What can run the recognition of Immich on this host, each with the
    devices it needs."""
    from . import host
    found = host.gpus()
    choices = [('cpu', translate('CPU'), {})]
    if found['intel']:
        choices.append(('openvino', 'Intel GPU', {'render': found['intel'][0]}))
    if found['nvidia']:
        choices.append(('cuda', 'NVIDIA GPU', {}))
    if found['amd'] and not host.rocm_blocker(storage):
        experimental = host.rocm_support(found.get('amd_gfx_target')) == 'experimental'
        label = 'AMD GPU' + (f" — {translate('experimental on this GPU')}" if experimental else '')
        choices.append(('rocm', label, {'render': found['amd'][0], 'experimental': experimental,
                                        'override': host.rocm_override(found.get('amd_gfx_target'))}))
    return choices


def change_recognition(project, ui, primary, member, run_lifecycle):
    """Move the recognition of Immich between the CPU and a GPU of the host."""
    from .installer import confirm_experimental_rocm
    current = (member.get('deployment', {}).get('machine_learning') or {}).get('acceleration', 'cpu')
    storage = _config(member['vmid']).get('rootfs', 'local-lvm:').split(':', 1)[0]
    choices = recognition_choices(storage)
    if [tag for tag, _, _ in choices] == ['cpu'] and current == 'cpu':
        ui.message(translate('No usable GPU was found on this host. Recognition stays on the CPU.'),
                   translate('Modify OCI stack'))
        return False
    selected = ui.choose(translate('What runs the recognition of Immich'),
                         [(tag, label) for tag, label, _ in choices], current)
    if selected is None or selected == current:
        ui.message(translate('Nothing was changed.'), translate('Modify OCI stack'))
        return False
    details = next(extra for tag, _, extra in choices if tag == selected)
    if details.get('experimental') and not confirm_experimental_rocm(ui):
        return False
    labels = {tag: label for tag, label, _ in choices}
    text = (f"{translate('Recognition')}: {labels.get(current, current)} → {labels[selected]}\n\n"
            + translate('The machine learning container is rebuilt with the image of the new choice. Its model '
                        'cache, the library and the database are kept. The whole application is stopped and '
                        'updated, as in an update. If the operation fails after a container was changed, the '
                        'previous containers and the previous choice are restored. An operation that stops '
                        'halfway is recovered from the OCI management menu.'))
    if not ui.review(text, translate('Modify OCI stack'), question=translate('Change the recognition now?'), default=True):
        return False
    command = [sys.executable, str(project / 'remote/oci_immich_recognition.py'), str(primary['vmid']),
               '--acceleration', selected]
    if details.get('render'):
        command += ['--render-device', details['render']]
    if details.get('override'):
        command += ['--gfx-override', details['override']]
    return run_lifecycle(command, translate('Modify OCI stack'))


def modify_stack(project, ui, primary, run_lifecycle, member_vmid=None):
    members = primary.get('stack', {}).get('members', [])
    if not members:
        ui.message(translate('This stack has no saved members to update.'), translate('OCI stack management'))
        return False
    member = next((m for m in members if m['vmid'] == member_vmid), None)
    if member is None:
        member = members[0]
        if len(members) > 1:
            # The application first: it is the container most often changed.
            first = application_members(primary)[0]['vmid']
            ordered = sorted(members, key=lambda m: m['vmid'] != first)
            selected = ui.choose(translate('Container to change'),
                                 [(str(m['vmid']), member_label(m)) for m in ordered], str(first))
            if selected is None:
                return False
            member = next(m for m in members if str(m['vmid']) == selected)
    learning = immich_learning(primary)
    options = [('resources', translate('CPU, RAM and swap')),
               ('variables', translate('Environment variables')),
               ('paths', translate('Paths and devices'))]
    if learning is not None and learning['vmid'] == member['vmid']:
        options.append(('recognition', translate('Change what runs recognition: CPU or GPU')))
    what = ui.choose(f"{translate('What to modify')} · {member_label(member)}", options, 'resources')
    if what is None:
        return False
    if what == 'recognition':
        return change_recognition(project, ui, primary, learning, run_lifecycle)
    changes = {'remove_mounts': [], 'add_mounts': [], 'change_mounts': {}, 'remove_devices': [], 'add_devices': [],
               'resources': {}, 'environment': {'set': {}, 'unset': []}}
    try:
        if what == 'resources':
            changes['resources'] = edit_resources(ui, member)
        elif what == 'variables':
            changes['environment']['set'] = edit_variables(ui, member)
        else:
            planned = plan_changes(ui, member)
            if planned:
                changes.update(planned)
    except UserCancelled:
        return False
    except ValueError as error:
        ui.message(str(error), translate('Modify OCI stack'))
        return False
    if not (changes['resources'] or changes['environment']['set']
            or any(changes[key] for key in ('remove_mounts', 'add_mounts', 'change_mounts', 'remove_devices',
                                            'add_devices'))):
        ui.message(translate('Nothing was changed.'), translate('Modify OCI stack'))
        return False
    if not ui.review(summary(member, changes), translate('Modify OCI stack'),
                     question=translate('Apply these changes?'), default=True):
        return False
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as file:
        json.dump(changes, file)
        file.flush()
        return run_lifecycle([sys.executable, str(project / 'remote/oci_stack_modify.py'),
                              str(member['vmid']), '--changes', file.name], translate('Modify OCI stack'))
