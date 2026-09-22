"""Conservative recreation editor: preserve saved state and add data routes."""
import copy
import re
from pathlib import Path, PurePosixPath

from .i18n import translate
from .ui import UserCancelled


def positive_integer(ui, prompt, value, minimum=1):
    result = int(ui.ask(prompt, str(value)))
    if result < minimum:
        raise ValueError(f"{prompt}: {translate('minimum')} {minimum}")
    return result


def absolute_path(value):
    if (not value.startswith('/') or value == '/' or str(PurePosixPath(value)) != value
            or '..' in PurePosixPath(value).parts or any(c.isspace() or c == ',' for c in value)):
        raise ValueError(translate('The path must be absolute and normalized'))
    return value


def edit_network(deployment, ui):
    from . import network as access
    from .installer import ask_bridge
    network = deployment['network']
    bridge = ask_bridge(ui, translate('Access bridge'), network['bridge'])
    ipv4, gateway = access.ask_ipv4(ui, bridge, network.get('ipv4'), network.get('gateway'))
    network.update(bridge=bridge, ipv4=ipv4, gateway=gateway)


def edit_acceleration(candidate, ui):
    from .installer import configure_acceleration
    deployment = candidate['deployment']
    template = candidate.get('template', {})
    installer = template.get('proxmox', {}).get('installer_profile', {})
    hardware = installer.get('hardware_acceleration')
    if not hardware or not ui.confirm(translate('Change GPU acceleration?'), False):
        return
    profiles = hardware.get('profiles', [])
    reference = template.get('container_contract', {}).get('image', {}).get('reference', '')
    linuxserver = reference.split(':')[0].startswith(('lscr.io/linuxserver/', 'linuxserver/', 'docker.io/linuxserver/'))
    if not linuxserver and any(e.get('name') == 'DOCKER_MODS' for p in profiles for e in p.get('environment', [])):
        raise ValueError(translate('Docker Mods are only offered for compatible LinuxServer images'))
    owned_ids = {d['id'] for p in profiles for d in p.get('device_requests', [])}
    owned_configs = {c['id'] for p in profiles for c in p.get('post_start_configurations', [])}
    old_profile = next((p for p in profiles if p['id'] == deployment.get('hardware_profile')), {})
    environment = copy.deepcopy(deployment.get('environment', []))
    for old in old_profile.get('environment', []):
        if old['name'] != 'DOCKER_MODS':
            environment = [e for e in environment if not (e['name'] == old['name'] and str(e['value']) == str(old['value']))]
    owned_names = set(old_profile.get('environment_from_devices', {}))
    owned_names.update(e['name'] for d in old_profile.get('device_requests', []) for e in d.get('environment', []))
    environment = [e for e in environment if e['name'] not in owned_names]
    mods = next((e for e in environment if e['name'] == 'DOCKER_MODS'), None)
    custom_mods = []
    if mods:
        official_mods = {str(e['value']) for p in profiles for e in p.get('environment', []) if e['name'] == 'DOCKER_MODS'}
        custom_mods = [m for m in str(mods['value']).split('|') if m and m not in official_mods]
        environment = [e for e in environment if e['name'] != 'DOCKER_MODS']
    profile = copy.deepcopy(installer)
    profile['optional_devices'] = []
    profile['device_requests'] = []
    profile['hardware_acceleration']['default'] = deployment.get('hardware_profile') or hardware.get('default')
    devices, selected, configurations, environment = configure_acceleration(
        profile, environment, deployment.get('security', {}).get('unprivileged', True), ui)
    new_mods = next((e for e in environment if e['name'] == 'DOCKER_MODS'), None)
    if custom_mods:
        if new_mods:
            new_mods['value'] = '|'.join(dict.fromkeys(custom_mods + str(new_mods['value']).split('|')))
        else:
            environment.append(dict(mods, value='|'.join(custom_mods)))
    deployment['devices'] = [d for d in deployment.get('devices', []) if d.get('id') not in owned_ids] + devices
    from .gpu import apply_profile_image
    apply_profile_image(template, selected)
    deployment['hardware_profile'] = selected
    deployment['environment'] = environment
    deployment['post_start_configurations'] = [c for c in deployment.get('post_start_configurations', []) if c.get('id') not in owned_configs] + configurations
    deployment['device_permissions'] = installer.get('device_permissions') if deployment['devices'] else None


def edit_environment(deployment, ui):
    environment = deployment.setdefault('environment', [])
    while ui.confirm(translate('Change or add an environment variable?'), False):
        name = ui.ask(translate('Variable name'))
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError(translate('Invalid variable name'))
        matches = [e for e in environment if e['name'] == name]
        if len(matches) > 1:
            raise ValueError(translate('Duplicate variable in the contract; review it before editing'))
        old = matches[0] if matches else None
        sensitive = bool(old and old.get('sensitive'))
        if not sensitive:
            sensitive = ui.confirm(translate('Is the value a password or secret?'), True)
        value = ui.password(f"{translate('New value for')} {name}") if sensitive else ui.ask(
            f"{translate('Value for')} {name}", old.get('value', '') if old else '', required=False)
        if '\x00' in value:
            raise ValueError(translate('The value contains an unsupported character'))
        item = dict(old or {}, name=name, value=value, sensitive=sensitive)
        if old:
            environment[environment.index(old)] = item
        else:
            environment.append(item)


def edit_peripherals(deployment, ui, allow_coral=False):
    devices = deployment.setdefault('devices', [])
    label = 'Coral/USB' if allow_coral else 'USB'
    example = '/dev/apex_0, ' if allow_coral else ''
    while ui.confirm(f"{translate('Add or change a device')} ({label})?", False):
        path = ui.ask(f"{translate('Host device node')} ({translate('e.g.')} {example}/dev/ttyACM0, /dev/bus/usb/003/004)")
        if not re.fullmatch(r'/dev/(apex_[0-9]+|ttyUSB[0-9]+|ttyACM[0-9]+|bus/usb/[0-9]{3}/[0-9]{3})', path):
            raise ValueError(translate('Select a specific Coral or USB node, not the whole /dev'))
        if path.startswith('/dev/apex_') and not allow_coral:
            raise ValueError(translate('Coral is only offered for Frigate and CodeProject.AI'))
        if '/bus/usb/' in path:
            ui.info(translate('The USB number can change after reconnecting or rebooting. This profile does not remap it automatically or handle Coral USB re-enumeration. Do not share a dongle already used by another service.'))
        old = next((d for d in devices if d.get('host_path') == path), None)
        mode = ui.ask(translate('Node octal permissions (e.g. 0660)'), (old or {}).get('mode', '0660'))
        if not re.fullmatch(r'0?[0-7]{3}', mode):
            raise ValueError(translate('Invalid octal permissions'))
        item = dict(old or {}, id=(old or {}).get('id', 'peripheral-' + path.removeprefix('/dev/').replace('/', '-')),
                    kind='character-device', host_path=path, container_path=path,
                    mode=mode, gid_strategy='host-device-gid', deny_write=False)
        if old:
            devices[devices.index(old)] = item
        else:
            devices.append(item)


def edit_recreation(record, ui):
    candidate = copy.deepcopy(record)
    refresh_template(candidate, ui)
    deployment = candidate['deployment']
    resources = deployment['resources']
    resources['cores'] = positive_integer(ui, translate('Cores'), resources['cores'])
    resources['memory_mb'] = positive_integer(ui, translate('RAM in MiB'), resources['memory_mb'], 128)
    while ui.confirm(translate('Add a custom data path?'), False):
        target = absolute_path(ui.ask(translate('Path inside the container'), '/data/custom'))
        existing = [m['container_path'].rstrip('/') for m in deployment['mounts']]
        if any(target == p or target.startswith(p + '/') or p.startswith(target + '/') for p in existing):
            raise ValueError(translate('The path overlaps an existing mount'))
        mode = ui.choose(translate('Persistence for the new path'),
                         [('managed-volume', translate('Container volume (included in backups)')),
                          ('host-bind', translate('Host directory (not included in Proxmox backups)'))],
                         'managed-volume')
        if mode is None:
            raise UserCancelled(translate('Custom path cancelled'))
        mount = {'type': mode, 'container_path': target, 'read_only': False}
        if mode == 'managed-volume':
            mount.update(source=ui.ask(translate('Proxmox storage for the volume'), deployment['rootfs']['storage']),
                         size_gb=positive_integer(ui, translate('Volume size in GB'), 4), backup=True)
        else:
            mount.update(source=absolute_path(ui.ask(translate('Host directory'),
                         '/mnt/oci-shared/custom')), size_gb=None, backup=False,
                         create_if_missing=True)
        deployment['mounts'].append(mount)
    if ui.confirm(translate('Change the access network?'), False):
        edit_network(deployment, ui)
    edit_acceleration(candidate, ui)
    reference = candidate.get('template', {}).get('container_contract', {}).get('image', {}).get('reference', '')
    repository = reference.split('@')[0].rsplit(':', 1)[0]
    edit_peripherals(deployment, ui, repository in ('ghcr.io/blakeblackshear/frigate', 'codeproject/ai-server', 'docker.io/codeproject/ai-server'))
    edit_environment(deployment, ui)
    proposal = {'operation': 'recreate', 'candidate': candidate}
    if record.get('observed', {}).get('config_sha256'):
        proposal['base_config_sha256'] = record['observed']['config_sha256']
    return proposal


def refresh_template(candidate, ui):
    from .catalog import Catalog
    old = candidate.get('template', {})
    name = old.get('id', '').removeprefix('image-')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]+', name):
        return
    root = Path(__file__).resolve().parents[2]
    path = root / 'catalog' / 'apps' / (name + '.json')
    if not path.is_file() or not old.get('container_contract', {}).get('image'):
        return
    latest = Catalog(root).load_template(name, generate_if_missing=False)
    if latest == old:
        return
    if not ui.confirm(translate('Apply the options from the current catalog template? Your data and configuration are kept.'), True):
        return
    if latest['id'] != old['id'] or latest['container_contract']['image']['repository'] != old['container_contract']['image']['repository']:
        raise ValueError(translate('The current template changes the image or identity; an explicit migration is required'))
    deployment = candidate['deployment']
    mounted = {m['container_path'] for m in deployment.get('mounts', [])}
    for volume in latest['container_contract'].get('volumes', []):
        if not volume.get('required', True) or volume['container_path'] in mounted:
            continue
        target = absolute_path(volume['container_path'])
        ui.info(f"{translate('The current template requires a new persistent path:')} {target}. "
                f"{translate('It is created empty; existing data is not migrated automatically.')}")
        mode = ui.choose(f"{translate('Persistence for')} {target}",
                         [('managed-volume', translate('Container volume (included in backups)')),
                          ('host-bind', translate('Host directory (not included in Proxmox backups)'))],
                         volume.get('default', 'managed-volume'))
        if mode not in ('managed-volume', 'host-bind'):
            raise UserCancelled(translate('Required new path cancelled'))
        mount = {'container_path': target, 'type': mode, 'read_only': volume.get('read_only', False)}
        if mode == 'managed-volume':
            mount.update(source=ui.ask(translate('Proxmox storage for the volume'), deployment['rootfs']['storage']),
                         size_gb=positive_integer(ui, translate('Volume size in GB'), volume.get('managed_volume', {}).get('default_size_gb', 4)), backup=True)
        else:
            mount.update(source=absolute_path(ui.ask(translate('Host directory'), '/mnt/oci-shared/' + name + '/' + volume.get('id', 'data'))),
                         backup=False, size_gb=None, create_if_missing=True)
        deployment.setdefault('mounts', []).append(mount)
        mounted.add(target)
    for item in latest['container_contract'].get('environment', []):
        if not item.get('required') or any(e['name'] == item['name'] for e in deployment.get('environment', [])):
            continue
        prompt = translate(item.get('prompt', item['name']))
        value = ui.password(prompt) if item['sensitive'] else ui.ask(prompt, item.get('example') or '')
        deployment.setdefault('environment', []).append({'name': item['name'], 'value': value, 'sensitive': item['sensitive']})
    profile = latest.get('proxmox', {}).get('installer_profile', {})
    tmpfs = deployment.get('tmpfs_mounts', [])
    for item in profile.get('tmpfs_mounts', []):
        if any(m['container_path'] == item['container_path'] for m in tmpfs):
            continue
        size = item['default_size_mb']
        if item.get('prompt_size', True):
            size = positive_integer(ui, f"{translate('Tmpfs size in MiB for')} {item['container_path']}", size, item.get('minimum_size_mb', 1))
        tmpfs.append({'container_path': item['container_path'], 'size_mb': size,
                      'mount_options': copy.deepcopy(item.get('mount_options', ['rw', 'nosuid', 'nodev']))})
        deployment['tmpfs_mounts'] = tmpfs
    sysctls = deployment.get('security', {}).get('sysctls', [])
    for item in profile.get('security', {}).get('sysctls', []):
        if not any(s['name'] == item['name'] for s in sysctls):
            sysctls.append(copy.deepcopy(item))
            deployment.setdefault('security', {})['sysctls'] = sysctls
    candidate['template'] = latest
