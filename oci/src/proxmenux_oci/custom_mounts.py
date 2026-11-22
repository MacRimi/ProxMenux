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


def ask_custom_mount(ui, existing, storage):
    """One extra path, with the questions of the installation."""
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
        from .installer import ask_storage
        mount['source'] = ask_storage(ui, translate('Proxmox storage for the volume'), 'rootdir', storage)
        mount['size_gb'] = int(ui.ask(translate('Volume size in GB'), '8'))
    else:
        mount['source'] = ui.ask(translate('Host directory (created if it does not exist)'), '/mnt/oci-shared/custom')
    mount['container_path'] = validate_mount(mount, existing)
    return mount


def ask_custom_mounts(ui, mounts, storage):
    result = list(mounts)
    while ui.confirm(translate('Add an extra custom path'), False):
        result.append(ask_custom_mount(ui, result, storage))
    return result


def describe_path(path):
    """Where the data of a path lives, as the editor of paths shows it."""
    if path['type'] == 'host-bind':
        where = f"{translate('host directory')} {path['source']}"
    else:
        size = f" {path['size']}" if path.get('size') else ''
        where = f"{translate('Container volume')}{size} {translate('on')} {path['source'].split(':', 1)[0]}"
    return where + (f" · {translate('read-only')}" if path.get('read_only') else '')


def edit_paths(ui, paths, storage):
    """Change the paths of one container: the host directory of any path
    mounted from the host, and the read-only mode or the removal of the extra
    paths, which are the only ones that can be removed. New paths are asked as
    the installation asks them.

    `paths` lists every mount as {container_path, type, source, size,
    read_only, extra}. The result says what to remove, what to change on an
    existing path and what to add; nothing is applied here."""
    paths = [dict(path, added=False) for path in paths]
    removed, changed, added = [], {}, []
    selected = 'add'
    while True:
        options = [(path['container_path'], f"{path['container_path']}  →  {describe_path(path)}")
                   for path in paths]
        options += [('add', translate('Add a path')), ('done', translate('Done'))]
        selected = ui.choose(translate('Choose a path to change it, or add a new one.'), options, selected,
                             title=translate('Paths'), show_tags=False)
        if selected is None:
            raise UserCancelled(translate('Custom path cancelled'))
        if selected == 'done':
            return {'remove': removed, 'change': changed, 'add': [path['mount'] for path in paths if path['added']]}
        if selected == 'add':
            mount = ask_custom_mount(ui, [{'container_path': path['container_path']} for path in paths], storage)
            paths.append({'container_path': mount['container_path'], 'type': mount['type'],
                          'source': mount['source'], 'read_only': mount['read_only'],
                          'size': f"{mount['size_gb']} GB" if mount.get('size_gb') else None,
                          'extra': True, 'added': True, 'mount': mount})
            selected = mount['container_path']
            continue
        path = next(item for item in paths if item['container_path'] == selected)
        actions = []
        if path['type'] == 'host-bind':
            actions.append(('source', translate('Change the host directory')))
        if path['extra']:
            actions.append(('read_only', translate('Make it writable') if path['read_only']
                            else translate('Make it read-only')))
            actions.append(('remove', translate('Remove this path')))
        if not actions:
            ui.message(translate('This path keeps the data of the application on a container volume; '
                                 'it cannot be changed or removed.'), translate('Paths'))
            continue
        action = ui.choose(f"{path['container_path']}  →  {describe_path(path)}",
                           actions + [('back', translate('Back'))], actions[0][0],
                           title=translate('Paths'), show_tags=False)
        if action in (None, 'back'):
            continue
        target = path['container_path']
        if action == 'remove':
            if path['added']:
                paths.remove(path)
            elif path['type'] != 'managed-volume' or ui.confirm(
                    f"{translate('Removing this path deletes its container volume and the data in it:')} "
                    f"{target}\n\n{translate('Delete it?')}", False):
                paths.remove(path)
                removed.append(target)
                changed.pop(target, None)
            selected = 'done'
            continue
        if action == 'source':
            value = valid_path(ui.ask(translate('Host directory (created if it does not exist)'), path['source']))
            if value == path['source']:
                continue
            path['source'] = value
        else:
            path['read_only'] = not path['read_only']
        if path['added']:
            path['mount'].update(source=path['source'], read_only=path['read_only'])
        else:
            changed.setdefault(target, {}).update(
                {'source': path['source']} if action == 'source' else {'read_only': path['read_only']})


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
