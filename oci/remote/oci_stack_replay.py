"""Capture only declared, generated rootfs adapters; never application data."""
import hashlib
import copy
from pathlib import Path
import re
import stat
import shlex
import os

from oci_ui import translate


def nextcloud_menu_ready(primary):
    """Offer only captured members whose declared persistence is fully covered."""
    return captured_menu_ready(primary, 'install_nextcloud_stack.sh', nextcloud_record,
                               {'application', 'database', 'cache'})


def paperless_menu_ready(primary):
    return captured_menu_ready(primary, 'install_paperless_stack.sh', paperless_record,
                               {'application', 'database', 'broker'})


def tandoor_menu_ready(primary):
    return captured_menu_ready(primary, 'install_tandoor_stack.sh', tandoor_record,
                               {'application', 'database'})


def immich_menu_ready(primary):
    try:
        return captured_menu_ready(primary, 'install_immich_stack.sh', immich_record,
                                   {'server', 'database', 'valkey', 'machine-learning'})
    except (RuntimeError, OSError):
        return False


def immich_prerequisites(rootfs, role, image):
    required = {
        'server': ('/bin/bash', 'tini', 'node', 'start.sh', 'grep', 'seq', 'sleep'),
        'database': ('/bin/sh', '/usr/local/bin/immich-docker-entrypoint.sh', 'postgres', 'pg_isready'),
        'valkey': ('/bin/sh', 'docker-entrypoint.sh', 'valkey-server', 'valkey-cli'),
        'machine-learning': ('/bin/sh', 'env', 'tini', 'python'),
    }
    # PostgreSQL's official entrypoint generates its configuration at startup.
    return adapter_prerequisites(rootfs, role, image, 'install_immich_stack.sh', required)


def immich_record(record):
    projection = normalize(record)
    recipe = record['deployment']['rootfs_replay']
    if recipe['adapter'] != 'install_immich_stack.sh':
        raise ValueError(translate('Unrecognized Immich adapter'))
    role = recipe['role']
    # PostgreSQL's saved listen address is private, never guessed from the host.
    net0 = projection['deployment']['network']['ipv4'].split('/')[0]
    expected = {
        'server': ['tini', '--', '/usr/local/bin/immich-lxc-start'],
        'database': ['/usr/local/bin/immich-docker-entrypoint.sh', 'postgres', '-c',
                     'config_file=/etc/postgresql/postgresql.conf', '-c',
                     'listen_addresses=127.0.0.1,' + net0],
        'valkey': ['docker-entrypoint.sh', 'valkey-server'],
        'machine-learning': ['env', 'LD_PRELOAD=/usr/lib/libmimalloc.so.2', 'tini', '--',
                             'python', '-m', 'immich_ml'],
    }
    runtime = projection['runtime']
    if shlex.split(runtime.get('entrypoint', '')) != expected[role]:
        raise ValueError(translate('The Immich startup was modified or cannot be reproduced'))
    acceleration = record['deployment'].get('machine_learning', {}).get('acceleration', 'cpu')
    if role == 'machine-learning' and acceleration not in ('cpu', 'openvino', 'cuda'):
        raise ValueError(translate('Immich GPU profile not validated'))
    cuda = role == 'machine-learning' and acceleration == 'cuda'
    devices = [{'kind': 'nvidia-runtime', 'runtime_mode': 'dynamic'}] if cuda else []
    for item in projection['native_devices']:
        fields = dict(p.split('=', 1) for p in item['value'].split(',') if '=' in p)
        path = fields.get('path')
        if cuda and path and path.startswith('/dev/nvidia'):
            continue
        if not path or not re.fullmatch(r'/dev/dri/renderD[0-9]+', path):
            raise ValueError(translate('Immich device without a validated translation'))
        devices.append({'kind': 'character-device', 'host_path': path, 'container_path': path,
                        'gid_strategy': 'host-device-gid', 'mode': fields.get('mode', '0660'),
                        'drm_vendor_ids': ['0x8086'] if role == 'machine-learning' else ['0x8086', '0x1002']})
    if projection['preserved_raw_runtime'] and not cuda:
        raise ValueError(translate('Immich runtime without a validated translation'))
    if cuda:
        import oci_accelerators
        candidate = {'devices': devices, 'environment': [
            {'name': 'NVIDIA_DRIVER_CAPABILITIES', 'value': 'compute,utility'}]}
        oci_accelerators.check(record['observed']['config'].encode(), candidate)
    translated = {'compose_entrypoint': expected[role], 'command': []}
    for native, target in (('lxc.init.cwd', 'working_directory'), ('lxc.signal.halt', 'halt_signal')):
        if native in runtime:
            translated[target] = runtime[native]
    result = portable_record(record, {'generated_files': projection['generated_files'], 'runtime': translated})
    result['deployment']['devices'] = devices
    if cuda:
        result['deployment']['environment'] = [e for e in result['deployment']['environment']
                                             if e['name'] != 'NVIDIA_DRIVER_CAPABILITIES']
        result['deployment']['environment'].append({'name': 'NVIDIA_DRIVER_CAPABILITIES', 'value': 'compute,utility'})
    result['deployment']['machine_learning'] = copy.deepcopy(record['deployment'].get('machine_learning', {}))
    return result


def captured_menu_ready(primary, adapter, convert, expected_roles):
    if primary.get('native_stack_intent', {}).get('adapter', {}).get('name') != adapter:
        return False
    members = primary.get('stack', {}).get('members', [])
    if len(members) != len(expected_roles):
        return False
    try:
        converted = [convert(member) for member in members]
        roles = {r['deployment']['replay_profile']['role'] for r in converted}
        if roles != expected_roles:
            return False
        for member in converted:
            targets = [m['container_path'] for m in member['deployment']['mounts']]
            declared = member['observed']['image']['defaults'].get('Volumes') or {}
            if any(not any(p == target or p.startswith(target.rstrip('/') + '/') for target in targets)
                   for p in declared):
                return False
    except (ValueError, KeyError, TypeError):
        return False
    return True


def image_executable(rootfs, path, executable=True):
    """Resolve container symlinks inside its root, never against the host root."""
    root = Path(rootfs)
    pending = list(Path(path).parts[1:])
    resolved, links = [], 0
    while pending:
        part = pending.pop(0)
        if part in ('', '.'):
            continue
        if part == '..':
            if not resolved:
                raise ValueError(translate('Symbolic link outside the rootfs of the new image'))
            resolved.pop()
            continue
        destination = root.joinpath(*resolved, part)
        info = destination.lstat()
        if stat.S_ISLNK(info.st_mode):
            links += 1
            if links > 40:
                raise ValueError(translate('Symbolic link loop in the new image'))
            target = os.readlink(destination)
            if target.startswith('/'):
                resolved = []
            pending = [p for p in target.split('/') if p] + pending
        else:
            resolved.append(part)
    info = root.joinpath(*resolved).stat()
    if not stat.S_ISREG(info.st_mode) or not info.st_mode & (0o111 if executable else 0o444):
        raise ValueError(translate('The new image does not keep a required executable'))
    return '/' + '/'.join(resolved)


def nextcloud_prerequisites(rootfs, role, image):
    required = {
        'application': ('/bin/sh', '/entrypoint.sh', '/cron.sh', 'apache2-foreground', 'php'),
        'database': ('/bin/sh', 'docker-entrypoint.sh', 'postgres', 'pg_isready'),
        'cache': ('/bin/sh', 'docker-entrypoint.sh', 'redis-server', 'redis-cli'),
    }
    return adapter_prerequisites(rootfs, role, image, 'install_nextcloud_stack.sh', required)


def paperless_prerequisites(rootfs, role, image):
    required = {
        'application': ('/bin/sh', '/init', 'python3'),
        'database': ('/bin/sh', 'docker-entrypoint.sh', 'postgres', 'pg_isready'),
        'broker': ('/bin/sh', 'tini', 'docker-entrypoint.sh', 'valkey-server', 'valkey-cli'),
    }
    return adapter_prerequisites(rootfs, role, image, 'install_paperless_stack.sh', required)


def tandoor_prerequisites(rootfs, role, image):
    defaults = image.get('defaults', {})
    entrypoint = defaults.get('Entrypoint') or defaults.get('Cmd') or []
    if role == 'application' and (not isinstance(entrypoint, list) or not entrypoint
                                 or not isinstance(entrypoint[0], str) or not entrypoint[0]):
        raise ValueError(translate('The official Tandoor startup executable is missing'))
    required = {
        'application': ('/bin/sh', entrypoint[0] if entrypoint else '/bin/sh', 'python3'),
        'database': ('/bin/sh', 'docker-entrypoint.sh', 'postgres', 'pg_isready'),
    }
    return adapter_prerequisites(rootfs, role, image, 'install_tandoor_stack.sh', required)


def adapter_prerequisites(rootfs, role, image, adapter, required):
    if role not in required:
        raise ValueError(translate('Unknown adapter role'))
    defaults = image.get('defaults', {})
    if defaults.get('User') not in (None, '', 'root', '0', '0:0'):
        raise ValueError(translate('The image changes the user expected by the adapter'))
    path = next((entry[5:] for entry in defaults.get('Env') or []
                 if entry.startswith('PATH=')), '')
    directories = path.split(':') if path else []
    if any(not directory.startswith('/') or '..' in Path(directory).parts for directory in directories):
        raise ValueError(translate('The PATH of the new image is outside the reproducible profile'))
    checked = []
    for command in required[role]:
        paths = [command] if command.startswith('/') else [directory.rstrip('/') + '/' + command for directory in directories]
        for candidate in paths:
            try:
                checked.append(image_executable(rootfs, candidate))
                break
            except FileNotFoundError:
                continue
        else:
            raise ValueError(translate('An executable required by the adapter is missing in the new image'))
    for path in FILES[adapter][role]:
        current = Path(rootfs)
        for part in Path(path).parts[1:]:
            current /= part
            if current.is_symlink():
                raise ValueError(translate('The new image adds a symbolic link in a generated path'))
    return checked


def nextcloud_record(record):
    """Build portable desired state from evidence, without writing the registry."""
    return portable_record(record, nextcloud_installer_profile(record))


def paperless_record(record):
    """Translate captured Paperless state; native activation remains separate."""
    return portable_record(record, paperless_installer_profile(record))


def tandoor_record(record):
    """Project the two-member Tandoor recipe without activating replacement."""
    return portable_record(record, tandoor_installer_profile(record))


def portable_record(record, profile):
    """Preserve data mounts and provenance without first-install preparations."""
    projection = normalize(record)
    saved = record['deployment'].get('member_replay_projection')
    if saved is not None and saved != projection:
        raise ValueError(translate('The saved projection does not match the native evidence'))
    result = copy.deepcopy(record)
    deployment = projection['deployment']
    native = projection['preserved_native']
    for mount in deployment['mounts']:
        mount.pop('existing_volume_id', None)
    template_storage = record['deployment'].get('archive_volume', 'local:').split(':', 1)[0]
    if template_storage.startswith('/'):
        raise ValueError(translate('The OCI image storage was not kept'))
    deployment.update(template_storage=template_storage, features=native.get('features', '').split(',')
                      if native.get('features') else [], stack_managed=True,
                      rootfs_adaptation_replay_required=False,
                      replay_profile=copy.deepcopy(record['deployment']['replay_profile']),
                      rootfs_replay=copy.deepcopy(record['deployment']['rootfs_replay']))
    if 'cpuunits' in native:
        deployment['resources']['cpu_units'] = int(native['cpuunits'])
    # Unknown settings cannot be silently lost during the first migration.
    if native.get('ostype') == 'unmanaged':
        deployment['ostype'] = 'unmanaged'
    result['deployment'] = deployment
    template = result['template']
    template.setdefault('schema_version', '0.5.0')
    template.setdefault('kind', 'proxmenux.oci-template')
    template.setdefault('status', 'generated-unvalidated')
    template.setdefault('catalog_ui', {}).update(
        architectures=[record['observed']['image']['architecture']], category='productivity')
    template.setdefault('source', {}).setdefault('provider', 'official')
    template['source'].setdefault('revision', record['observed']['image']['manifest_digest'])
    template['container_contract']['volumes'] = [
        {'container_path': m['container_path'], 'required': True}
        for m in deployment['mounts']]
    if deployment['resources'].get('cpu_allocation') == 'quota':
        profile = copy.deepcopy(profile)
        profile['cpu_allocation'] = 'quota'
    template.setdefault('proxmox', {})['installer_profile'] = profile
    if 'native_stack_intent' in result:
        result['dedicated_stack_recipe'] = result.pop('native_stack_intent')
    return result


def paperless_installer_profile(record):
    return official_application_profile(record, 'install_paperless_stack.sh', {
        'database': ['/usr/local/bin/paperless-postgres-lxc-start'],
        'broker': ['tini', '--', 'docker-entrypoint.sh', 'valkey-server'],
    })


def tandoor_installer_profile(record):
    return official_application_profile(record, 'install_tandoor_stack.sh', {
        'database': ['/usr/local/bin/tandoor-postgres-lxc-start'],
    })


def official_application_profile(record, adapter, adapted_entrypoints):
    projection = normalize(record)
    recipe = record['deployment']['rootfs_replay']
    if recipe['adapter'] != adapter:
        raise ValueError(translate('Stack adapter not recognized by the translator'))
    if projection.get('native_devices') or projection.get('preserved_raw_runtime'):
        raise ValueError(translate('The stack contains devices or directives without a translation'))
    runtime = projection['runtime']
    entrypoint = runtime.get('entrypoint', '')
    if not entrypoint or '\0' in entrypoint or '\n' in entrypoint:
        raise ValueError(translate('A reproducible native startup is missing'))
    arguments = shlex.split(entrypoint)
    role = recipe['role']
    if role in adapted_entrypoints:
        expected = adapted_entrypoints[role]
    else:
        defaults = record['observed']['image']['defaults']
        inherited = defaults.get('Entrypoint') or []
        command = defaults.get('Cmd') or []
        if not isinstance(inherited, list) or not isinstance(command, list):
            raise ValueError(translate('The official startup cannot be reproduced'))
        expected = inherited + command
        if not expected or any(not isinstance(arg, str) for arg in expected):
            raise ValueError(translate('The official startup of the application is missing'))
    if arguments != expected:
        raise ValueError(translate('The startup differs from the declared adapter'))
    # The application follows the new image defaults, not the old entrypoint.
    translated = {} if role == 'application' else {'compose_entrypoint': arguments, 'command': []}
    for native, target in (('lxc.init.cwd', 'working_directory'),
                           ('lxc.signal.halt', 'halt_signal')):
        if native in runtime:
            translated[target] = runtime[native]
    return {'generated_files': copy.deepcopy(projection['generated_files']),
            'runtime': translated}


def nextcloud_installer_profile(record):
    """Translate captured startup settings, without authorizing replacement.

    Never include first-install volume preparations: existing database and
    application disks must not be reseeded during image replacement.
    """
    projection = normalize(record)
    recipe = record['deployment']['rootfs_replay']
    if recipe['adapter'] != 'install_nextcloud_stack.sh':
        raise ValueError(translate('This translator only supports the Nextcloud stack'))
    if projection.get('native_devices') or projection.get('preserved_raw_runtime'):
        raise ValueError(translate('The stack contains devices or directives without a translation'))
    runtime = projection['runtime']
    entrypoint = runtime.get('entrypoint', '')
    if not entrypoint or '\0' in entrypoint or '\n' in entrypoint:
        raise ValueError(translate('A reproducible native startup is missing'))
    try:
        arguments = shlex.split(entrypoint)
    except ValueError as exc:
        raise ValueError(translate('Invalid native entrypoint')) from exc
    role = recipe['role']
    expected = {
        'application': ['/usr/local/bin/nextcloud-lxc-start'],
        'database': ['/usr/local/bin/nextcloud-postgres-lxc-start'],
        'cache': ['docker-entrypoint.sh', 'redis-server'],
    }[role]
    if arguments != expected:
        raise ValueError(translate('The startup differs from the declared Nextcloud adapter'))
    translated = {'compose_entrypoint': arguments, 'command': []}
    for native, target in (('lxc.init.cwd', 'working_directory'),
                           ('lxc.signal.halt', 'halt_signal')):
        if native in runtime:
            translated[target] = runtime[native]
    return {'generated_files': copy.deepcopy(projection['generated_files']),
            'runtime': translated}


FILES = {
    'install_immich_stack.sh': {
        'database': (), 'valkey': (), 'machine-learning': (),
        'server': ('/usr/local/bin/immich-lxc-start',),
    },
    'install_nextcloud_stack.sh': {
        'database': ('/usr/local/bin/nextcloud-postgres-lxc-start',),
        'cache': (), 'application': ('/usr/local/bin/nextcloud-lxc-start',),
    },
    'install_paperless_stack.sh': {
        'database': ('/usr/local/bin/paperless-postgres-lxc-start',),
        'broker': (), 'application': (),
    },
    'install_tandoor_stack.sh': {
        'database': ('/usr/local/bin/tandoor-postgres-lxc-start',),
        'application': (),
    },
}


def capture(rootfs, adapter, role, mounts):
    if adapter not in FILES or role not in FILES[adapter]:
        raise ValueError(translate('Unrecognized stack adapter or role'))
    root = Path(rootfs)
    if root.is_symlink() or not root.is_dir():
        raise ValueError(translate('Unsafe rootfs for the capture'))
    files = []
    for path in FILES[adapter][role]:
        if any(path == m['container_path'] or path.startswith(m['container_path'].rstrip('/') + '/')
               for m in mounts):
            raise ValueError(translate('A rootfs adaptation is stored in persistent storage'))
        destination = root
        for part in Path(path).parts[1:]:
            destination = destination / part
            if destination.is_symlink():
                raise ValueError(translate('Symbolic link in the path of an adaptation'))
        info = destination.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022
                or stat.S_IMODE(info.st_mode) != 0o755
                or info.st_uid != 100000 or info.st_gid != 100000):
            raise ValueError(translate('Adaptation file with unexpected permissions or owner'))
        if info.st_size > 65536:
            raise ValueError(translate('Adaptation file too large'))
        content = destination.read_text()
        if not content.startswith(('#!/bin/sh\n', '#!/bin/bash\n')) or '\0' in content:
            raise ValueError(translate('Unrecognized adaptation format'))
        files.append({'container_path': path, 'mode': '0755', 'owner': 'mapped-root',
                      'content': content, 'sha256': hashlib.sha256(content.encode()).hexdigest()})
    return {'schema_version': 1, 'adapter': adapter, 'role': role, 'files': files}


def validate(recipe):
    adapter, role = recipe.get('adapter'), recipe.get('role')
    if recipe.get('schema_version') != 1 or adapter not in FILES or role not in FILES[adapter]:
        raise ValueError(translate('Unrecognized adaptation recipe'))
    files = recipe.get('files', [])
    if [item.get('container_path') for item in files] != list(FILES[adapter][role]):
        raise ValueError(translate('Incomplete file recipe or unknown paths'))
    for item in files:
        content = item.get('content', '')
        if (item.get('mode') != '0755' or item.get('owner') != 'mapped-root'
                or not content.startswith(('#!/bin/sh\n', '#!/bin/bash\n'))
                or len(content.encode()) > 65536 or '\0' in content
                or hashlib.sha256(content.encode()).hexdigest() != item.get('sha256')):
            raise ValueError(translate('The adaptation content was modified'))
    return files


def normalize(record):
    """Project a dedicated member into common desired state, without enabling it.

    Raw native config remains authoritative. The projection is evidence for the
    future replay adapter, not authorization to discard unsupported directives.
    """
    deployment = record['deployment']
    recipe = deployment['rootfs_replay']
    files = validate(recipe)
    if deployment.get('replay_profile') != {'adapter': recipe['adapter'], 'role': recipe['role']}:
        raise ValueError(translate('Inconsistent adaptation profile and recipe'))
    config = record['observed']['config']
    config_hash = hashlib.sha256(config.encode()).hexdigest()
    if record['observed'].get('config_sha256') != config_hash:
        raise ValueError(translate('The configuration evidence does not match'))
    values, environment, mount_lines = {}, [], []
    names = set()
    def add_environment(value):
        name, equals, content = value.partition('=')
        if not equals or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) or name in names:
            raise ValueError(translate('Ambiguous or invalid environment variable'))
        names.add(name)
        environment.append({'name': name, 'value': content})
    for line in config.splitlines():
        key, sep, value = line.partition(': ')
        if not sep:
            if line.strip():
                raise ValueError(translate('Unrecognized native configuration'))
            continue
        if key == 'lxc.environment.runtime':
            add_environment(value)
        elif key == 'env':
            for variable in value.split('\0'):
                add_environment(variable)
        elif re.fullmatch(r'mp[0-9]+', key):
            mount_lines.append((key, value))
        else:
            values.setdefault(key, []).append(value)
    def single(key, default=None):
        matches = values.get(key, [])
        if len(matches) > 1:
            raise ValueError(f"{translate('Duplicated native directive:')} {key}")
        if not matches:
            if default is not None:
                return default
            raise ValueError(f"{translate('Missing native directive:')} {key}")
        return matches[0]
    def options(value):
        result = {}
        for part in value.split(','):
            key, equals, content = part.partition('=')
            if equals:
                if key in result:
                    raise ValueError(translate('Duplicated native option'))
                result[key] = content
        return result
    def size(value):
        match = re.fullmatch(r'([0-9]+)([GMT])', value or '')
        if not match:
            raise ValueError(translate('The disk size cannot be reproduced'))
        number, unit = int(match[1]), match[2]
        if unit == 'M':
            if number % 1024:
                raise ValueError(translate('The size of existing disks is not rounded'))
            number //= 1024
        if unit == 'T':
            number *= 1024
        if number < 1:
            raise ValueError(translate('Disk too small for the common profile'))
        return number
    if single('unprivileged') != '1':
        raise ValueError(translate('The native unprivileged idmap is required'))
    rootfs = single('rootfs')
    source = rootfs.split(',', 1)[0]
    if source.startswith('/') or ':' not in source:
        raise ValueError(translate('The rootfs is not managed by Proxmox'))
    net = options(single('net0'))
    if not net.get('bridge') or not net.get('ip') or not net.get('hwaddr'):
        raise ValueError(translate('Incomplete primary network'))
    mounts, targets = [], set()
    for key, value in mount_lines:
        source = value.split(',', 1)[0]
        opts = options(value)
        target = opts.get('mp', '')
        if (not target.startswith('/') or target == '/' or '..' in Path(target).parts
                or str(Path(target)) != target or any(target == other or target.startswith(other + '/')
                                                     or other.startswith(target + '/') for other in targets)):
            raise ValueError(translate('Invalid or duplicated mount path'))
        targets.add(target)
        mount = {'container_path': target, 'read_only': opts.get('ro', '0') == '1'}
        if source.startswith('/'):
            if opts.get('backup', '0') != '0':
                raise ValueError(translate('A host bind mount cannot be included in vzdump'))
            mount.update(type='host-bind', source=source, backup=False, create_if_missing=False)
        else:
            if ':' not in source or opts.get('backup') != '1':
                raise ValueError(translate('A managed volume with backup enabled is required'))
            mount.update(type='managed-volume', source=source.split(':', 1)[0], backup=True,
                         size_gb=size(opts.get('size')), existing_volume_id=source)
        mounts.append(mount)
    quota = recipe['adapter'] == 'install_immich_stack.sh' and 'cores' not in values
    if quota:
        limit = single('cpulimit')
        if not re.fullmatch(r'[1-9][0-9]*', limit):
            raise ValueError(translate('The Immich CPU quota cannot be reproduced'))
        cores = int(limit)
    else:
        cores = int(single('cores'))
    resources = {'cores': cores, 'memory_mb': int(single('memory')),
                 'swap_mb': int(single('swap', '0'))}
    if quota:
        resources['cpu_allocation'] = 'quota'
    if resources['cores'] < 1 or resources['memory_mb'] < 1 or resources['swap_mb'] < 0:
        raise ValueError(translate('Invalid resources'))
    defaults = dict(item.split('=', 1) for item in record['observed'].get('image', {}).get('defaults', {}).get('Env', [])
                    if isinstance(item, str) and '=' in item)
    overrides = [item for item in environment if defaults.get(item['name']) != item['value']]
    plan = {'vmid': record['vmid'], 'hostname': single('hostname'),
            'rootfs': {'storage': rootfs.split(':', 1)[0], 'size_gb': size(options(rootfs).get('size'))},
            'resources': resources, 'security': {'unprivileged': True},
            'network': {'bridge': net['bridge'], 'ipv4': net['ip'], 'mac_address': net['hwaddr'],
                        'firewall': net.get('firewall', '0') == '1'},
            'onboot': single('onboot', '0') == '1', 'start_after_create': False,
            'shutdown_timeout_seconds': 60, 'mounts': mounts, 'environment': overrides}
    if net.get('gw'):
        plan['network']['gateway'] = net['gw']
    runtime = {key: single(key) for key in ('entrypoint', 'lxc.init.cwd', 'lxc.signal.halt') if key in values}
    preserved = {key: single(key) for key in ('arch', 'ostype', 'cmode', 'console', 'tty', 'cpuunits',
                 'net0', 'net1', 'startup', 'hookscript', 'features', 'tags') if key in values}
    devices = [{'key': key, 'value': single(key)} for key in values if re.fullmatch(r'dev[0-9]+', key)]
    # The console log line is not replayed: the installer that rebuilds the
    # member sets it itself, and replaying it too would leave two of them.
    raw_runtime = [line for line in config.splitlines() if line.startswith('lxc.')
                   and line.partition(': ')[0] not in ('lxc.environment.runtime', 'lxc.init.cwd',
                                                       'lxc.signal.halt', 'lxc.console.logfile')]
    return {'schema_version': 1, 'deployment': plan, 'runtime': runtime,
            'preserved_native': preserved, 'generated_files': copy.deepcopy(files),
            'native_devices': devices, 'preserved_raw_runtime': raw_runtime,
            'observed_environment': environment,
            'native_config_sha256': config_hash,
            'activation_requires_native_compatibility_check': True}
