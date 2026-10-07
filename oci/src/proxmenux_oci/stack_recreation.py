"""Modify the extra paths and devices of a multi-container application.

Only its application container is restarted. Its own data, its database and
the other containers are never part of this operation."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile

from .custom_mounts import ask_custom_mounts
from .extra_devices import ask_extra_devices
from .i18n import translate

# The paths each recipe mounts in its application container: its own data,
# which Recreate never offers to remove.
RECIPE_PATHS = {
    'install_nextcloud_stack.sh': ('/var/www/html',),
    'install_paperless_stack.sh': ('/usr/src/paperless/data', '/usr/src/paperless/media',
                                   '/usr/src/paperless/consume', '/usr/src/paperless/export'),
    'install_tandoor_stack.sh': ('/opt/recipes/mediafiles', '/opt/recipes/staticfiles'),
    'install_immich_stack.sh': ('/data',),
}
APPLICATION_ROLES = ('application', 'server')
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
    adapter = (deployment.get('replay_profile') or {}).get('adapter')
    if adapter in RECIPE_PATHS:
        return set(RECIPE_PATHS[adapter])
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
                           'extra': target not in own})
        elif re.fullmatch(r'dev[0-9]+', key):
            path = _device_path(value)
            # The video device of Immich belongs to its acceleration profile.
            removable = bool(PERIPHERAL_NODE.fullmatch(path)) or (not immich and bool(GPU_NODE.fullmatch(path)))
            devices.append({'host_path': path, 'removable': removable})
    rootfs = config.get('rootfs', 'local-lvm:').split(':', 1)[0]
    return mounts, devices, rootfs, immich


def _describe(mount):
    if mount['type'] == 'host-bind':
        return f"{translate('host directory')} {mount['source']}"
    return f"{translate('Container volume')} {mount.get('size') or ''} {translate('on')} {mount['source'].split(':', 1)[0]}"


def plan_changes(ui, member):
    """Ask what to remove and what to add. None when nothing changes."""
    mounts, devices, storage, immich = current_state(member)
    changes = {'remove_mounts': [], 'add_mounts': [], 'remove_devices': [], 'add_devices': []}
    extra = [mount for mount in mounts if mount['extra']]
    if extra:
        kept = ui.checklist(translate('Extra paths to keep (unmark one to remove it)'),
                            [(mount['container_path'], _describe(mount)) for mount in extra],
                            [mount['container_path'] for mount in extra])
        if kept is None:
            return None
        for mount in extra:
            if mount['container_path'] in kept:
                continue
            if mount['type'] == 'managed-volume' and not ui.confirm(
                    f"{translate('Removing this path deletes its container volume and the data in it:')} "
                    f"{mount['container_path']}\n\n{translate('Delete it?')}", False):
                continue
            changes['remove_mounts'].append(mount['container_path'])
    remaining = [{'type': mount['type'], 'container_path': mount['container_path']} for mount in mounts
                 if mount['container_path'] not in changes['remove_mounts']]
    changes['add_mounts'] = [mount for mount in ask_custom_mounts(ui, remaining, storage) if mount.get('custom')]
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
    for mount in changes['add_mounts']:
        target = (f"{translate('host directory')} {mount['source']}" if mount['type'] == 'host-bind'
                  else f"{translate('Container volume')} {mount['size_gb']} GB {translate('on')} {mount['source']}")
        lines.append(f"+ {mount['container_path']} → {target}")
    lines += [f"- {path}" for path in changes['remove_mounts']]
    lines += [f"+ {device['host_path']}" for device in changes['add_devices']]
    lines += [f"- {path}" for path in changes['remove_devices']]
    lines += ['', translate('A running container is restarted to apply the changes; a stopped one is left stopped. '
                            'The data of the application, its database and the configuration of the other '
                            'containers are not changed. A container volume removed here is deleted with the '
                            'data in it.')]
    return '\n'.join(lines)


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


def modify_stack(project, ui, primary, run_lifecycle):
    learning = immich_learning(primary)
    if learning is not None:
        what = ui.choose(translate('What to modify'),
                         [('paths', translate('Add or remove extra paths and devices')),
                          ('recognition', translate('Change what runs recognition: CPU or GPU'))], 'paths')
        if what is None:
            return False
        if what == 'recognition':
            return change_recognition(project, ui, primary, learning, run_lifecycle)
    members = application_members(primary)
    if not members:
        ui.message(translate('This stack has no saved members to update.'), translate('OCI stack management'))
        return False
    member = members[0]
    if len(members) > 1:
        options = [(str(m['vmid']), f"CT {m['vmid']} · {(m.get('stack_member') or {}).get('name', '')}")
                   for m in members]
        selected = ui.choose(translate('Container to change'), options, options[0][0])
        if selected is None:
            return False
        member = next(m for m in members if str(m['vmid']) == selected)
    changes = plan_changes(ui, member)
    if changes is None:
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
