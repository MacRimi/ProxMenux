"""Conservative recreation editor: preserve saved state and add data routes."""
import copy
import re
from pathlib import Path, PurePosixPath

from .i18n import translate
from .ui import BacktrackUI, RestartWizard, UserCancelled


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


def edit_acceleration(candidate, ui, confirm=True):
    from .installer import configure_acceleration
    deployment = candidate['deployment']
    template = candidate.get('template', {})
    installer = template.get('proxmox', {}).get('installer_profile', {})
    hardware = installer.get('hardware_acceleration')
    if not hardware or (confirm and not ui.confirm(translate('Change GPU acceleration?'), False)):
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


def modification_options(candidate):
    """Only offer supported settings; never put environment values in the menu."""
    deployment = candidate['deployment']
    resources = deployment['resources']
    profile = candidate.get('template', {}).get('proxmox', {}).get('installer_profile', {})
    network = deployment.get('network', {})
    address = network.get('ipv4', 'dhcp')

    def row(label, value):
        return f"{label:<26} {value}"

    options = [
        ('cores', row(translate('CPU cores'), resources['cores'])),
        ('memory', row(translate('RAM in MiB'), resources['memory_mb'])),
        ('network', row(translate('Network'),
                        f"{network.get('bridge', '-')} · {'DHCP' if address == 'dhcp' else address}")),
        ('paths', row(translate('Extra paths'), len(deployment.get('mounts', [])))),
    ]
    if profile.get('shared_directories'):
        options.append(('shares', translate('Shared directories')))
    if profile.get('hardware_acceleration'):
        hardware = profile['hardware_acceleration']
        selected = next((p for p in hardware.get('profiles', [])
                         if p['id'] == deployment.get('hardware_profile')), {})
        options.append(('acceleration', row(translate('Acceleration'),
                         translate(selected.get('label') or deployment.get('hardware_profile') or 'CPU'))))
    if profile.get('object_detector'):
        options.append(('detector', translate('Object detector')))
    options += [
        ('devices', row(translate('Devices'), len(deployment.get('devices', [])))),
        ('environment', row(translate('Variables'), len(deployment.get('environment', [])))),
        ('catalog', translate('Catalog options')),
        ('apply', translate('Review and apply')),
        ('discard', translate('Discard changes')),
    ]
    return options


def edit_setting(candidate, ui, setting):
    deployment = candidate['deployment']
    template = candidate.get('template', {})
    profile = template.get('proxmox', {}).get('installer_profile', {})
    if setting == 'cores':
        resources = deployment['resources']
        resources['cores'] = positive_integer(ui, translate('Cores'), resources['cores'])
    elif setting == 'memory':
        resources = deployment['resources']
        resources['memory_mb'] = positive_integer(ui, translate('RAM in MiB'), resources['memory_mb'], 128)
    elif setting == 'network':
        edit_network(deployment, ui)
    elif setting == 'shares':
        from .installer import ask_shared_directories
        deployment['mounts'] += ask_shared_directories(
            ui, template, deployment['mounts'], deployment['rootfs']['storage'], True, optional=True,
            unprivileged=deployment.get('security', {}).get('unprivileged', True))
    elif setting == 'paths':
        from .custom_mounts import ask_custom_mounts
        deployment['mounts'] = ask_custom_mounts(ui, deployment['mounts'], deployment['rootfs']['storage'])
    elif setting == 'acceleration':
        edit_acceleration(candidate, ui, confirm=False)
    elif setting == 'detector':
        from .installer import configure_detector
        deployment['devices'], notes = configure_detector(profile, deployment.get('devices', []), ui)
        if notes:
            deployment['completion_notes'] = notes
    elif setting == 'devices':
        from .extra_devices import ask_extra_devices
        reference = template.get('container_contract', {}).get('image', {}).get('reference', '')
        repository = reference.split('@')[0].rsplit(':', 1)[0]
        deployment['devices'] = ask_extra_devices(
            ui, deployment.get('devices', []), deployment.get('security', {}).get('unprivileged', True),
            allow_coral=repository in ('ghcr.io/blakeblackshear/frigate', 'codeproject/ai-server', 'docker.io/codeproject/ai-server'))
    elif setting == 'environment':
        edit_environment(deployment, ui)
    elif setting == 'catalog':
        refresh_template(candidate, ui)
    else:
        raise ValueError(setting)
    if setting in ('acceleration', 'detector', 'devices'):
        from .extra_devices import device_permissions
        reference = candidate.get('template', {}).get('container_contract', {}).get('image', {}).get('reference', '')
        permissions = device_permissions(reference, deployment.get('devices', []), deployment.get('device_permissions'))
        if permissions is not None or 'device_permissions' in deployment:
            deployment['device_permissions'] = permissions


def edit_section(candidate, ui, setting):
    """A cancelled or invalid section cannot leave a half-edited draft."""
    wizard = BacktrackUI(ui)
    try:
        while True:
            edited = copy.deepcopy(candidate)
            try:
                edit_setting(edited, wizard, setting)
                return edited
            except RestartWizard:
                wizard.restart()
            except UserCancelled:
                return candidate
            except ValueError as error:
                if not wizard.retry_last(error):
                    ui.message(str(error), translate('Modify OCI'))
                    return candidate
    finally:
        wizard.close()


def edit_recreation(record, ui):
    """Keep a draft across independently editable settings; apply it once."""
    from .cli import _deployment_summary_text
    candidate = copy.deepcopy(record)
    selected = 'cores'
    while True:
        pending = candidate != record
        status = translate('Unapplied changes') if pending else translate('No pending changes')
        text = (f"CT {record.get('vmid', '-')}: {candidate['deployment'].get('hostname', '')}\n"
                f"{status}\n\n"
                + translate('Choose a setting. Changes are applied only after the final review.'))
        selected = ui.choose(text, modification_options(candidate), selected,
                             title=translate('Modify OCI'), show_tags=False)
        if selected is None or selected == 'discard':
            if not pending or ui.confirm(translate('Discard unapplied changes?'), False):
                return None
            selected = 'apply'
        elif selected == 'apply':
            if not pending:
                ui.message(translate('Nothing was changed.'), translate('Modify OCI'))
                return None
            if ui.review(_deployment_summary_text(candidate['template'], candidate['deployment']),
                         translate('Modify OCI'), question=translate('Apply these changes?'), default=True):
                proposal = {'operation': 'recreate', 'candidate': candidate}
                if record.get('observed', {}).get('config_sha256'):
                    proposal['base_config_sha256'] = record['observed']['config_sha256']
                return proposal
        else:
            candidate = edit_section(candidate, ui, selected)


def refresh_template(candidate, ui):
    from .catalog import Catalog
    old = candidate.get('template', {})
    template_id = old.get('id', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]+', template_id):
        return
    root = Path(__file__).resolve().parents[2]
    if not old.get('container_contract', {}).get('image'):
        return
    catalog = Catalog(root)
    matching = [item for item in catalog.load_index()['applications']
                if item.get('template_id') == template_id]
    if len(matching) != 1:
        return
    name = matching[0]['id']
    latest = catalog.compose(name)
    if latest == old:
        return
    if not ui.confirm(translate('Apply options from the current catalog template? New required paths and settings may be requested. Review the resulting configuration before recreating the CT.'), True):
        return
    if latest['id'] != old['id'] or latest['container_contract']['image']['repository'] != old['container_contract']['image']['repository']:
        raise ValueError(translate('The current template changes the template identity or image repository; an explicit migration is required'))
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
