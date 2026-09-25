"""Optional user mounts, separate from the image's required persistence."""
from pathlib import PurePosixPath

from .i18n import translate
from .ui import UserCancelled


def valid_path(value):
    if (not value.startswith('/') or value == '/' or
            any(c.isspace() or c in ',\x00' for c in value) or
            any(part in ('.', '..') for part in value.split('/'))):
        raise ValueError(translate('Invalid absolute path; avoid spaces, commas and relative segments'))
    value = str(PurePosixPath(value))
    if value.startswith('//'):
        raise ValueError(translate('Invalid path'))
    return value


def overlaps(a, b):
    return a == b or a.startswith(b.rstrip('/') + '/') or b.startswith(a.rstrip('/') + '/')


def validate_mount(mount, existing):
    target = valid_path(mount['container_path'])
    protected = ('/bin', '/sbin', '/etc', '/usr', '/lib', '/lib64', '/proc', '/sys', '/dev', '/run')
    if any(overlaps(target, p) for p in protected):
        raise ValueError(translate('The custom path cannot hide system directories'))
    if any(overlaps(target, valid_path(m['container_path'])) for m in existing):
        raise ValueError(translate('The custom path overlaps another mount'))
    if mount['type'] == 'managed-volume':
        if int(mount['size_gb']) < 1 or not mount.get('backup'):
            raise ValueError(translate('Invalid internal volume'))
    elif mount['type'] == 'host-bind':
        valid_path(mount['source'])
        if mount.get('backup'):
            raise ValueError(translate('Bind mounts are not included in vzdump'))
    else:
        raise ValueError(translate('Invalid mount type'))
    return target


def ask_custom_mounts(ui, mounts, storage):
    result = list(mounts)
    while ui.confirm(translate('Add an extra custom path'), False):
        target = ui.ask(translate('Path inside the container (e.g. /media-extra)'))
        mode = ui.choose(translate('Data location'), [
            ('managed-volume', translate('Container volume (included in backups)')),
            ('host-bind', translate('Host directory (not included in Proxmox backups)')),
        ], 'managed-volume')
        if mode is None:
            raise UserCancelled(translate('Custom path cancelled'))
        mount = {'type': mode, 'container_path': target, 'custom': True,
                 'source': storage, 'size_gb': None, 'backup': mode == 'managed-volume',
                 'read_only': ui.confirm(translate('Mount read-only'), False),
                 'create_if_missing': mode == 'host-bind'}
        if mode == 'managed-volume':
            mount['source'] = ui.ask(translate('Proxmox storage for the volume'), storage)
            mount['size_gb'] = int(ui.ask(translate('Volume size in GB'), '8'))
        else:
            mount['source'] = ui.ask(translate('Host directory (created if it does not exist)'), '/mnt/oci-shared/custom')
        mount['container_path'] = validate_mount(mount, result)
        result.append(mount)
    return result


def ask_stack_custom_mounts(ui, services, storage):
    """Collect extra paths once, then attach each path to selected stack members."""
    if not ui.confirm(translate('Add extra paths to this stack'), False):
        return
    options = [(service['name'], service['name']) for service in services]
    defaults = [service['name'] for service in services if service.get('main')]
    while True:
        selected = ui.checklist(translate('Containers that will receive this path'),
                                options, defaults or [options[0][0]])
        if not selected or set(selected) - {name for name, _ in options}:
            raise ValueError(translate('Select at least one stack container'))
        mode = ui.choose(translate('Data location'), [
            ('managed-volume', translate('Container volume (included in backups)')),
            ('host-bind', translate('Host directory (not included in Proxmox backups)')),
        ], 'host-bind' if len(selected) > 1 else 'managed-volume')
        if mode is None:
            raise UserCancelled(translate('Custom path cancelled'))
        source = (ui.ask(translate('Proxmox storage for the volume'), storage)
                  if mode == 'managed-volume' else
                  ui.ask(translate('Host directory (created if it does not exist)'), '/mnt/oci-shared/custom'))
        size = int(ui.ask(translate('Volume size in GB'), '8')) if mode == 'managed-volume' else None
        read_only = ui.confirm(translate('Mount read-only'), False)
        default_target = '/media-extra'
        additions = []
        for service in services:
            if service['name'] not in selected:
                continue
            target = ui.ask(f"{service['name']}: {translate('Path inside the container')}", default_target)
            mount = {'type': mode, 'container_path': target, 'custom': True,
                     'source': source, 'size_gb': size, 'backup': mode == 'managed-volume',
                     'read_only': read_only, 'create_if_missing': mode == 'host-bind'}
            mount['container_path'] = validate_mount(mount, service['deployment']['mounts'])
            additions.append((service, mount))
            default_target = target
        for service, mount in additions:
            service['deployment']['mounts'].append(mount)
        if not ui.confirm(translate('Add another extra path to this stack'), False):
            break
