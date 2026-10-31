"""Compile supported Compose stacks into the existing single-LXC installer contract."""
from __future__ import annotations

import copy
import base64
import re
import secrets
import hashlib
import math
import shlex
from urllib.parse import urlsplit, urlunsplit, quote

import yaml

from .casaos import convert_casaos_compose, canonical_image_repository
from .converter import ConversionError
from .converter import _image_contract, _split_short_mount, _port_contract
from .i18n import translate


class StackError(ValueError):
    pass


VARIABLE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)')


def normalized_mounts(mounts):
    result = []
    for mount in mounts:
        if isinstance(mount, str):
            source, target, mode = _split_short_mount(mount)
            if mode not in (None, 'rw', 'ro'):
                raise StackError(f"{translate('Unsupported volume options:')} {mode}")
            mount = {'source': source, 'target': target, 'read_only': mode == 'ro'}
        if not isinstance(mount, dict):
            raise StackError(translate('Unrecognized volume definition'))
        target = mount.get('target', '')
        if not target.startswith('/') or '..' in target.split('/') or target == '/':
            raise StackError(translate('Invalid volume target'))
        result.append(copy.deepcopy(mount))
    return result


def environment(value):
    if isinstance(value, list):
        if any('=' not in item for item in value):
            raise StackError(translate('Environment entry without an explicit value'))
        value = dict(item.split('=', 1) for item in value)
    if any(v is None for v in (value or {}).values()):
        raise StackError(translate('Environment entry without an explicit value'))
    return {k: str(v) for k, v in (value or {}).items()}


def kind(image):
    repo = canonical_image_repository(image)
    for prefix in ('docker.io/', 'index.docker.io/', 'registry-1.docker.io/'):
        if repo.startswith(prefix):
            repo = repo[len(prefix):]
            break
    if repo.startswith('library/'):
        repo = repo[len('library/'):]
    return repo if repo in {'postgres', 'redis', 'valkey/valkey', 'mariadb', 'linuxserver/mariadb', 'mongo', 'getmeili/meilisearch'} else 'application'


DEPENDENCY_VOLUMES = {'mariadb':['/var/lib/mysql'], 'linuxserver/mariadb':['/config'], 'mongo':['/data/db','/data/configdb'],
                      'getmeili/meilisearch':['/meili_data']}


def normalized_dependency_mount_path(container_path, image):
    """PostgreSQL 18+ 'postgres:latest' stores versioned PGDATA directly
    under /var/lib/postgresql instead of /var/lib/postgresql/data (the path
    declared in the source Compose file). Both the volume rename below and
    volume_preparations matching in service_template() must agree on this
    one normalized path, or a preparation keyed to either form gets
    silently dropped or ends up orphaned against the renamed mount."""
    if container_path == '/var/lib/postgresql/data' and str(image).endswith(':latest'):
        return '/var/lib/postgresql'
    return container_path


def authenticated_redis(service):
    c = service['compose']
    return (kind(service['image']) == 'redis' and not c.get('entrypoint')
            and c.get('command') == ['redis-server','--requirepass','${REDISCLI_AUTH}']
            and bool(environment(c.get('environment')).get('REDISCLI_AUTH')))


def custom_dependency_command(service, image_entrypoint=None):
    """Known server commands may add flags; another executable is not equivalent."""
    if service['compose'].get('entrypoint'):
        return False
    command = service['compose'].get('command')
    if not command:
        return True
    try:
        argv = shlex.split(command) if isinstance(command, str) else command
    except ValueError:
        return False
    if (not isinstance(argv, list) or not argv or any(not isinstance(arg, str) for arg in argv)):
        return False
    allowed = {'postgres': {'postgres'}, 'redis': {'redis-server'},
               'valkey/valkey': {'valkey-server'}, 'mariadb': {'mariadbd', 'mysqld'},
               'linuxserver/mariadb': {'mariadbd', 'mysqld'}, 'mongo': {'mongod'},
               'getmeili/meilisearch': {'meilisearch'}}
    # Password-protected Redis still needs its own validated auth check.
    if kind(service['image']) in {'redis', 'valkey/valkey'} and any(
            arg.split('=', 1)[0] in {'--requirepass', '--masterauth', '--aclfile'} for arg in argv):
        return authenticated_redis(service)
    if argv[0].startswith('-'):
        # Docker passes options through the actual image entrypoint. Do not
        # guess or prepend a database executable on behalf of the image.
        return (isinstance(image_entrypoint, list) and bool(image_entrypoint)
                and all(isinstance(arg, str) and arg for arg in image_entrypoint))
    return argv[0] in allowed.get(kind(service['image']), set())


def completed_services(template):
    """Jobs are declared by Compose's successful-completion dependency condition."""
    jobs = set()
    for service in template.get('compose_stack', {}).get('services', []):
        dependencies = service['compose'].get('depends_on') or {}
        if isinstance(dependencies, dict):
            for name, requirement in dependencies.items():
                if isinstance(requirement, dict) and requirement.get('condition') == 'service_completed_successfully':
                    jobs.add(name)
    return jobs


def ordered_services(template):
    stack = template['compose_stack']
    services = {s['name']: copy.deepcopy(s) for s in stack['services']}
    for name, values in template.get('proxmox', {}).get('stack_environment_overrides', {}).items():
        if name not in services:
            raise StackError(f"{translate('Environment override for an unknown service:')} {name}")
        env = environment(services[name]['compose'].get('environment'))
        env.update(values)
        services[name]['compose']['environment'] = env
    for name, command in template.get('proxmox', {}).get('stack_command_overrides', {}).items():
        if name not in services:
            raise StackError(f"{translate('Command override for an unknown service:')} {name}")
        services[name]['compose']['command'] = copy.deepcopy(command)
    done, visiting, ordered = set(), set(), []

    def visit(name):
        if name not in services:
            raise StackError(f"{translate('Unknown dependency:')} {name}")
        if name in visiting:
            raise StackError(f"{translate('Circular dependency:')} {name}")
        if name in done:
            return
        visiting.add(name)
        raw = services[name]['compose'].get('depends_on', [])
        for dep in raw:
            if isinstance(raw, dict):
                condition = raw[dep].get('condition', 'service_started')
                allowed = {'service_started', 'service_healthy'}
                if template.get('proxmox', {}).get('custom_compose_stack'):
                    allowed.add('service_completed_successfully')
                if condition not in allowed:
                    raise StackError(f"{name}: {translate('unsupported dependency condition')} {condition}")
                if raw[dep].get('required', True) is False:
                    raise StackError(f"{name}: {translate('optional dependencies are not yet supported')}")
            visit(dep)
        visiting.remove(name)
        done.add(name)
        ordered.append(services[name])

    for name in services:
        visit(name)
    main = stack['main_service']
    if any(main in s['compose'].get('depends_on', []) for s in services.values()):
        raise StackError(translate('Services that depend on the main service are not yet supported'))
    return [s for s in ordered if s['name'] != main] + [services[main]]


def service_template(parent, service, main=False):
    c = copy.deepcopy(service['compose'])
    mounts = normalized_mounts(c.get('volumes', []))
    explicit_targets = {m['target'] for m in mounts}
    for target in DEPENDENCY_VOLUMES.get(kind(service['image']), []):
        if not any(target == t or target.startswith(t.rstrip('/')+'/') for t in explicit_targets):
            mounts.append({'type':'volume','target':target})
    targets = {m['target'] for m in mounts}
    c['volumes'] = mounts
    for key in ('depends_on', 'networks', 'healthcheck', 'expose'):
        c.pop(key, None)
    c['environment'] = environment(c.get('environment'))
    if authenticated_redis(service):
        c['command'] = ['redis-server','--requirepass',c['environment']['REDISCLI_AUTH']]
    single = convert_casaos_compose(
        yaml.safe_dump({'name': service['name'], 'services': {service['name']: c},
                        'x-casaos': {'main': service['name'], 'title': {'en_US': service['name']}}}),
        parent['source']['revision'], parent['source']['repository'],
        service['name'], '', parent['catalog_ui']['category'],
        parent['catalog_ui'].get('category_label'), service['name'],
    )
    # Preserve selected image and resolved stack values; the importer normalizes secrets.
    image = _image_contract(service['image'])
    if image.get('digest') or ':' in service['image'].split('@', 1)[0].rsplit('/', 1)[-1]:
        image['pull_policy'] = 'resolve-written-reference-to-architecture-digest-at-install'
    single['container_contract']['image'] = image
    single['container_contract']['environment'] = [
        {'name': k, 'example': v, 'required': True, 'sensitive': True, 'prompt_user': False}
        for k, v in c['environment'].items()
    ]
    # Only the main service reports the credentials of the application.
    single['first_run'] = {'endpoints': [],
                           'credentials': copy.deepcopy(parent.get('first_run', {}).get('credentials', [])) if main else []}
    single['proxmox'].setdefault('installer_profile', {}).pop('startup_healthcheck', None)
    parent_preparations = parent.get('proxmox', {}).get('installer_profile', {}).get('volume_preparations', [])
    normalized_targets = {normalized_dependency_mount_path(t, service['image']) for t in targets}
    own_preparations = []
    for p in parent_preparations:
        normalized_path = normalized_dependency_mount_path(p.get('container_path'), service['image'])
        if normalized_path in normalized_targets:
            entry = copy.deepcopy(p)
            entry['container_path'] = normalized_path
            own_preparations.append(entry)
    if own_preparations:
        single['proxmox'].setdefault('installer_profile', {})['volume_preparations'] = own_preparations
    return single


def service_endpoint(service, include_expose=False):
    """Return a TCP port; only a published port implies a web frontend here."""
    ports = list(service['compose'].get('ports') or [])
    if include_expose:
        ports += list(service['compose'].get('expose') or [])
    for port in ports:
        if isinstance(port, dict):
            protocol = port.get('protocol', 'tcp')
            target = port.get('target')
        else:
            raw, _, protocol = str(port).partition('/')
            protocol = protocol or 'tcp'
            target = raw.rsplit(':', 1)[-1]
        if protocol == 'tcp' and str(target).isdigit() and 0 < int(target) < 65536:
            return {'scheme': 'http', 'port': int(target), 'path': '/'}
    return None


def public_environment_bindings(services, main_name, environments=None):
    """Bind loopback URL origins to the service publishing their Compose host port."""
    frontends = [service for service in services if service_endpoint(service)]
    result = {}
    for service in services:
        bindings = {}
        values = (environments or {}).get(service['name'], environment(service['compose'].get('environment')))
        for key, value in values.items():
            words = key.upper().split('_')
            if not ({'PUBLIC', 'EXTERNAL'} & set(words[:-1]) and words[-1] in {'URL', 'URI', 'ORIGIN'}):
                continue
            if not re.match(r'^https?://', value, re.I):
                continue
            url = urlsplit(value)
            if url.scheme not in {'http', 'https'} or url.hostname not in {'localhost', '127.0.0.1', '0.0.0.0', '::1'}:
                continue
            try:
                origin_port = url.port or (443 if url.scheme == 'https' else 80)
            except ValueError as error:
                raise StackError(translate('Invalid service check URL')) from error
            matches = set()
            for target in frontends:
                for port in _port_contract(target['compose'].get('ports'), set()):
                    if (port['protocol'] == 'tcp' and port.get('published_example') == origin_port
                            and not port.get('container_port_end') and not port.get('published_example_end')):
                        matches.add((target['name'], port['container_port']))
            if len(matches) > 1:
                raise StackError(f"{service['name']}: {key}: {translate('Ambiguous local public URL; use an explicit URL')}")
            if not matches:
                raise StackError(f"{service['name']}: {key}: {translate('Local public URL has no matching published port; use an explicit URL')}")
            target_name, target_port = next(iter(matches))
            credentials = url.netloc.rpartition('@')[0]+'@' if '@' in url.netloc else ''
            rendered = urlunsplit((url.scheme, credentials+'@STACK_LAN_IP@:'+str(target_port),
                                   url.path, url.query, url.fragment))
            bindings[key] = {'target_service': target_name, 'container_port': target_port, 'value': rendered}
        if bindings:
            result[service['name']] = bindings
    return result


def _check_duration(value, default):
    if value is None:
        return default
    text = str(value).strip().lower()
    parts = list(re.finditer(r'(\d+(?:\.\d+)?)(ns|us|ms|h|m|s)', text))
    if not parts or ''.join(item.group() for item in parts) != text:
        raise StackError(translate('Invalid service check timeout'))
    factors = {'ns': 1e-9, 'us': 1e-6, 'ms': 1e-3, 's': 1, 'm': 60, 'h': 3600}
    duration = sum(float(item.group(1)) * factors[item.group(2)] for item in parts)
    if not math.isfinite(duration) or duration < 0 or duration > 3600:
        raise StackError(translate('Invalid service check timeout'))
    return duration


def compose_healthcheck(service):
    """An explicit worker readiness command executed inside its own LXC."""
    raw = service['compose'].get('healthcheck')
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise StackError(translate('Invalid service check arguments'))
    if raw.get('disable') is True:
        return None
    test = raw.get('test')
    if test == ['NONE']:
        return None
    if isinstance(test, str):
        test = ['CMD-SHELL', test]
    if (not isinstance(test, list) or len(test) < 2
            or any(not isinstance(arg, str) or any(ch in arg for ch in '\0\n\r') for arg in test)):
        raise StackError(translate('Invalid service check arguments'))
    if test[0] == 'CMD':
        argv = test[1:]
    elif test[0] == 'CMD-SHELL' and len(test) == 2 and test[1].strip():
        # pct exec does not promise the image PID1 environment. Reject checks
        # that would silently evaluate an unset runtime variable.
        reference = re.search(r'\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[^}]+\})', test[1])
        if reference:
            raise StackError(f"healthcheck: {translate('needs stack review')}: {reference.group(0)}")
        argv = ['sh', '-c', test[1]]
    else:
        raise StackError(translate('Invalid service check arguments'))
    if not argv or not argv[0].strip():
        raise StackError(translate('Empty exec service check'))
    interval = _check_duration(raw.get('interval'), 30)
    request = _check_duration(raw.get('timeout'), 5)
    start_period = _check_duration(raw.get('start_period'), 0)
    retries = raw.get('retries', 3)
    if (type(retries) is not int or retries < 1 or retries > 1000
            or interval <= 0 or request <= 0):
        raise StackError(translate('Invalid service check timeout'))
    total = max(30, math.ceil(start_period + (interval + request) * retries))
    if total > 3600:
        raise StackError(translate('Invalid service check timeout'))
    return {'type': 'exec', 'argv': argv, 'timeout_seconds': total}


def readiness_mode(service):
    """A declared healthy check is distinct from port liveness or running only."""
    if compose_healthcheck(service) or kind(service['image']) != 'application':
        return 'exec'
    if service_endpoint(service):
        return 'http'
    if service_endpoint(service, include_expose=True):
        return 'tcp'
    return 'running'


def _entrypoint_for(template, service):
    entries = template.get('proxmox', {}).get('stack_image_entrypoints', {})
    reference = service['image']
    return entries.get(reference) or (entries.get(reference[:-7]) if reference.endswith(':latest') else None)


def shared_sources(services):
    """Source identities mounted more than once, before storage is chosen."""
    users = {}
    for service in services:
        for mount in normalized_mounts(service['compose'].get('volumes', [])):
            source = mount.get('source')
            if source:
                users.setdefault(source, []).append(service['name'])
    return {source for source, names in users.items() if len(names) > 1}


def assess(template):
    """Reject untranslated semantics before any host resources are allocated."""
    errors = []
    custom = template.get('proxmox', {}).get('custom_compose_stack', False)
    try:
        services = ordered_services(template)
        literal = template.get('proxmox', {}).get('custom_compose_interpolated', False)
        top = template['compose_stack'].get('top_level', {})
        if any(k not in {'name', 'networks', 'volumes', 'version'}
               and not (custom and str(k).startswith('x-')) for k in top):
            raise StackError(translate('Top-level configs, secrets and other global options are not yet supported'))
        networks = top.get('networks', {})
        if len(networks) > 1 or any(v and any(not ((k == 'driver' and x == 'bridge') or (k == 'name' and isinstance(x,str))) for k,x in v.items()) for v in networks.values()):
            raise StackError(translate('Multiple networks or external networks are not yet supported'))
        if any(v for v in top.get('volumes', {}).values()):
            raise StackError(translate('Top-level volume options are not yet supported'))
        healthy_required = set()
        # Short-form dependencies mean service_started; collect long-form
        # healthy requirements even when other services use the short form.
        for service in services:
            dependencies = service['compose'].get('depends_on') or {}
            if isinstance(dependencies, dict):
                healthy_required.update(name for name, condition in dependencies.items()
                                        if isinstance(condition, dict) and condition.get('condition') == 'service_healthy')
        jobs = completed_services(template) if custom else set()
        if custom:
            public_environment_bindings(services, template['compose_stack']['main_service'])
        if template['compose_stack']['main_service'] in jobs or jobs & healthy_required:
            raise StackError(translate('unsupported dependency condition') + ': service_completed_successfully')
        for service in services:
            if service['name'] in jobs and service['compose'].get('restart') not in (None, 'no'):
                raise StackError(translate('unsupported dependency condition') + ': restart')
        seen_sources = set()
        for s in services:
            c = s['compose']
            for key in ('profiles','build','configs','secrets','env_file','pid','privileged','devices','runtime','cap_add','security_opt','network_mode','extra_hosts'):
                if c.get(key):
                    errors.append(f"{s['name']}: {key} {translate('needs stack review')}")
            try:
                explicit_check = compose_healthcheck(s) if custom else None
            except StackError as error:
                errors.append(f"{s['name']}: {error}")
                explicit_check = None
            if (custom and s['name'] == template['compose_stack']['main_service']
                    and explicit_check and service_endpoint(s) is None):
                errors.append(f"{s['name']}: {translate('Main endpoint not yet defined')}")
            if s['name'] != template['compose_stack']['main_service'] and kind(s['image']) == 'application':
                if not custom:
                    errors.append(f"{s['name']}: {translate('health and persistence profile not yet defined')}")
                elif s['name'] in healthy_required and explicit_check is None:
                    errors.append(f"{s['name']}: service_healthy {translate('needs stack review')}: "
                                  f"{translate('health and persistence profile not yet defined')}")
            if (kind(s['image']) != 'application' and (c.get('command') or c.get('entrypoint'))
                    and not authenticated_redis(s) and not (custom and custom_dependency_command(s, _entrypoint_for(template, s)))):
                errors.append(f"{s['name']}: {translate('custom dependency commands are not yet supported')}")
            for m in normalized_mounts(c.get('volumes', [])):
                source = m.get('source')
                if source is not None and source in seen_sources and not custom:
                    errors.append(translate('Volumes shared between services are not yet supported'))
                if source is not None:
                    seen_sources.add(source)
                if set(m) - {'type','source','target','read_only'} or (m.get('read_only') and not custom):
                    errors.append(translate('Volume options are not yet supported'))
                if m['target'].startswith(('/etc/', '/var/run/', '/run/', '/dev/', '/proc/', '/sys/')):
                    errors.append(translate('System path mounts are not yet supported'))
            env = environment(c.get('environment'))
            for k,v in env.items():
                for a,b in VARIABLE.findall(v):
                    variable = a or b
                    if not literal and variable not in {'TZ','PUID','PGID'} and not variable.startswith('GENERATED_'):
                        errors.append(f'{s["name"]}: {translate("unsupported variable")} {variable}')
                    if variable.startswith('GENERATED_') and re.search(r'API_KEY|CLIENT_SECRET|CREDENTIALS_ENABLED', variable):
                        errors.append(f'{s["name"]}: {translate("unsupported external credential or boolean")} {variable}')
            single = service_template(template,s)
            errors.extend(f'{s["name"]}: {b}' for b in single['compatibility']['untranslated_blockers'])
        if custom:
            for source in shared_sources(services):
                owners = set()
                for service in services:
                    if any(m.get('source') == source for m in normalized_mounts(service['compose'].get('volumes', []))):
                        env = environment(service['compose'].get('environment'))
                        owners.add((env.get('PUID', '1000'), env.get('PGID', '1000')))
                if len(owners) > 1:
                    errors.append(f"{source}: {translate('Volumes shared between services are not yet supported')}")
        if not template['first_run'].get('endpoints'):
            errors.append(translate('Main endpoint not yet defined'))
        resolve_environments(services, 'UTC', template.get('proxmox', {}).get('stack_generators', {}), literal=literal)
    except (ValueError, KeyError, TypeError, ConversionError) as e:
        errors.append(str(e))
    return sorted(set(errors))


def resolve_environments(services, timezone, generators=None, literal=False):
    tokens = {'TZ': timezone, 'PUID': '1000', 'PGID': '1000'}
    resolved = {}
    for s in services:
        env = environment(s['compose'].get('environment'))
        def replace(match):
            name = match.group(1) or match.group(2)
            if literal:
                return match.group(0)
            if name.startswith('GENERATED_'):
                if name not in tokens:
                    generator = (generators or {}).get(name)
                    if generator:
                        if generator != {'encoding':'base64','bytes':32,'prefix':'base64:'}:
                            raise StackError(f"{translate('Unsupported secret generator:')} {name}")
                        tokens[name] = 'base64:'+base64.b64encode(secrets.token_bytes(32)).decode()
                    else:
                        tokens[name] = secrets.token_hex(32)
            if name not in tokens:
                raise StackError(f"{translate('Unresolved variable:')} {name}")
            return tokens[name]
        resolved[s['name']] = {k: VARIABLE.sub(replace, v) for k,v in env.items()}
    if literal:
        return resolved
    # Catalog-generated credentials are bound only for legacy catalog definitions.
    # A fully interpolated custom Compose keeps its explicit connection strings.
    databases = {}
    for s in services:
        if kind(s['image']) == 'postgres':
            env = resolved[s['name']]
            for alias in (s['name'], s['compose'].get('container_name', s['name'])):
                databases[alias] = env
    for env in resolved.values():
        for key, value in list(env.items()):
            if value.startswith(('postgres://', 'postgresql://')):
                url = urlsplit(value)
                db = databases.get(url.hostname)
                if db is None:
                    raise StackError(f"{translate('PostgreSQL URL without an associated service:')} {key}")
                user = db.get('POSTGRES_USER', 'postgres')
                password = db.get('POSTGRES_PASSWORD')
                if not password:
                    raise StackError(translate('PostgreSQL requires a password'))
                host = url.hostname + (f':{url.port}' if url.port else '')
                env[key] = urlunsplit((url.scheme, quote(user, safe='')+':'+quote(password,safe='')+'@'+host, url.path, url.query, url.fragment))
    return resolved


class DefaultsUI:
    """Answers every question with the value of the recipe. `real` is the
    interface the installer uses for the few questions a default installation
    still asks."""
    def __init__(self, real=None):
        self.real = real
    def ask(self, text, default=None, required=True):
        return default if default is not None else ''
    def choose(self, text, options, default=None):
        return default
    def confirm(self, text, default=False):
        return default
    def info(self, text):
        pass
    def message(self, text):
        pass


def stack_lxc_hostname(stack_name, service_name, main=False):
    """Give the main LXC the stack name and avoid repeating it in members."""
    from .installer import _hostname_default

    stack = _hostname_default(stack_name)
    if main:
        return stack

    suffix = _hostname_default(service_name)
    prefix = stack + '-'
    if suffix.startswith(prefix):
        suffix = suffix[len(prefix):]
    if suffix == 'database':
        suffix = 'db'
    return _hostname_default(f'{stack}-{suffix}')


def _service_plan(template, service):
    """The single-container template and plan of one stack member."""
    from .installer import build_deployment, DEFAULT_MODE
    single = service_template(template, service, service['name'] == template['compose_stack']['main_service'])
    if kind(service['image']) == 'postgres':
        # Official PostgreSQL 18+ stores versioned PGDATA under this parent.
        for m in single['container_contract']['volumes']:
            if m['container_path'] == '/var/lib/postgresql/data' and service['image'].endswith(':latest'):
                m['container_path'] = normalized_dependency_mount_path(m['container_path'], service['image'])
    for e in single['container_contract']['environment']:
        e['required'] = bool(e['example'])
        e['example'] = 'stack-resolved-value' if e['example'] else ''
    return single, build_deployment(single, DefaultsUI(), DEFAULT_MODE)


def build_stack(template, ui, mode='advanced'):
    from .installer import _hostname_default, DEFAULT_MODE
    problems = assess(template)
    if problems:
        raise StackError('; '.join(problems))
    services = copy.deepcopy(ordered_services(template))
    defaults = template['proxmox']['defaults']
    custom = template.get('proxmox', {}).get('custom_compose_stack', False)
    jobs = completed_services(template) if custom else set()
    shared = shared_sources(services) if custom else set()
    shared_paths = {}
    # A default installation takes the name, the VMID and the settings from the
    # recipe; it still asks the storage, the address and how the stack starts.
    quiet = DefaultsUI() if mode == DEFAULT_MODE else ui
    # An imported Compose file was already named before its installation.
    name = _hostname_default((DefaultsUI() if custom else quiet).ask(translate('Stack name'), template['compose_stack']['project_name']))
    vmid = quiet.ask(translate('Base VMID (empty = next free block)'), '', required=False)
    from . import host
    from . import network as access
    from .installer import _ask_size, ask_bridge, ask_storage
    if mode == DEFAULT_MODE:
        root = ask_storage(ui, translate('Storage for the containers and their data'), 'rootdir',
                           defaults['rootfs_storage'])
    else:
        root = ask_storage(ui, translate('Storage for rootfs'), 'rootdir', defaults['rootfs_storage'])
    cache = ask_storage(ui, translate('Storage for the OCI image cache'), 'vztmpl', defaults['template_storage'], mode)
    generators = template.get('proxmox', {}).get('stack_generators', {})
    literal = template.get('proxmox', {}).get('custom_compose_interpolated', False)
    # The data paths of every member are settled before the network and the settings.
    volumes = root
    draft_envs = resolve_environments(copy.deepcopy(services), host.timezone(), generators, literal=literal)
    drafts = []
    selected_resources = {}
    for s in services:
        draft = copy.deepcopy(s)
        draft['compose']['environment'] = draft_envs[s['name']]
        _, plan = _service_plan(template, draft)
        if mode != DEFAULT_MODE and (custom or s['name'] == template['compose_stack']['main_service']):
            prefix = s['name']+': ' if custom and s['name'] != template['compose_stack']['main_service'] else ''
            resources = {'cores': int(ui.ask(prefix+translate('CPU cores'), str(plan['resources']['cores']))),
                         'memory_mb': int(ui.ask(prefix+translate('Memory in MB'), str(plan['resources']['memory_mb'])))}
            if resources['cores'] < 1 or resources['memory_mb'] < 256:
                raise StackError(translate('Invalid resources'))
            selected_resources[s['name']] = resources
        # The paths of the application itself hold the user's data, so where
        # they go is asked in a default installation too; the databases and
        # caches beside it keep the values of the recipe.
        asked = mode != DEFAULT_MODE or s['name'] == template['compose_stack']['main_service']
        source_mounts = {m['target']: m for m in normalized_mounts(s['compose'].get('volumes', []))}
        for m in plan['mounts']:
            label = f"{s['name']}: {m['container_path']}"
            source_mount = source_mounts.get(m['container_path'], {})
            source = source_mount.get('source')
            if source in shared:
                if source not in shared_paths:
                    slug = re.sub(r'[^A-Za-z0-9_.-]+', '-', source).strip('.-') or 'data'
                    identity = hashlib.sha256(source.encode()).hexdigest()[:8]
                    default_path = source if source.startswith('/') else '/mnt/oci-shared/'+name+'/shared/'+slug+'-'+identity
                    shared_paths[source] = ui.ask(f"{translate('Host path for')} {source}", default_path)
                    chosen = shared_paths[source]
                    if not chosen.startswith('/') or any(c in chosen for c in ',\n\r') or '..' in chosen.split('/'):
                        raise StackError(translate('Invalid volume target'))
                    if chosen.rstrip('/') in {'', '/etc', '/var', '/usr', '/root', '/dev', '/proc', '/sys', '/run', '/boot', '/bin', '/sbin', '/lib', '/lib64'}:
                        raise StackError(translate('Invalid volume target'))
                env = draft_envs[s['name']]
                m.update(type='host-bind', source=shared_paths[source], backup=False, size_gb=None,
                         read_only=bool(source_mount.get('read_only')))
                # Without an explicit PUID/PGID, use the imported image user
                # when creating the directory, just like private volumes.
                if 'PUID' in env or 'PGID' in env:
                    uid, gid = env.get('PUID', '1000'), env.get('PGID', '1000')
                    if not str(uid).isdigit() or not str(gid).isdigit() or int(uid) > 65535 or int(gid) > 65535:
                        raise StackError(translate('Invalid resources'))
                    offset = 100000 if plan.get('security', {}).get('unprivileged', True) else 0
                    m['host_owner'] = [int(uid)+offset, int(gid)+offset]
                continue
            mount_mode = (ui.choose(f"{translate('Where to store')} {label}",
                                    [('managed-volume', translate('Container volume (included in backups)')),
                                     ('host-bind', translate('Host directory (not included in Proxmox backups)'))],
                                    'managed-volume') if asked else 'managed-volume')
            if mount_mode is None:
                raise StackError(translate('Storage selection cancelled'))
            m.update(type=mount_mode, source=volumes, backup=mount_mode=='managed-volume')
            if mount_mode == 'host-bind':
                m['source'] = ui.ask(f"{translate('Host path for')} {label}",
                                     '/mnt/oci-shared/'+name+'/'+s['name']+'/'+m['container_path'].strip('/').replace('/','-'))
                m['size_gb'] = None
            elif asked:
                if mode != DEFAULT_MODE:
                    volumes = ask_storage(ui, f"{translate('Storage for')} {label}", 'rootdir', volumes)
                    m['source'] = volumes
                m['size_gb'] = _ask_size(ui, label, max(8, m['size_gb'] or 8))
            if m['size_gb'] is not None and m['size_gb'] < 1:
                raise StackError(translate('Invalid volume size'))
        drafts.append({'name': s['name'], 'main': s['name'] == template['compose_stack']['main_service'],
                       'deployment': {'mounts': plan['mounts']}})
    if mode != DEFAULT_MODE:
        from .custom_mounts import ask_stack_custom_mounts
        ask_stack_custom_mounts(ui, drafts, volumes)
    bridge = ask_bridge(ui, translate('Access bridge'), defaults['bridge'], mode)
    vlan_tag = access.ask_vlan_tag(quiet)
    frontend_names = [
        s['name'] for s in services
        if (s['name'] == template['compose_stack']['main_service']
            or s.get('frontend_network') is True
            or (custom and service_endpoint(s)))
    ]
    labelled_frontends = custom or len(frontend_names) > 1
    address_labels = frontend_names if labelled_frontends else ['']
    addresses, gateway = access.ask_addresses(ui, bridge, address_labels)
    timezone = quiet.ask(translate('Timezone'), host.timezone())
    envs = resolve_environments(services, timezone, generators, literal=literal)
    for group in template.get('proxmox', {}).get('stack_optional_environment', []):
        service_name = group['service']
        if service_name not in envs:
            raise StackError(f"{translate('Unknown credential service:')} {service_name}")
        if not quiet.confirm(f"{translate('Configure')} {translate(group['label'])} ({translate('optional')})", False):
            continue
        for field in group['fields']:
            if field['name'] not in envs[service_name] or envs[service_name][field['name']] != '':
                raise StackError(f"{translate('External field not reserved:')} {field['name']}")
            value = (ui.password(translate(field['label']), required=True) if field.get('sensitive',True)
                     else ui.ask(translate(field['label']), required=True))
            if not value or any(c in value for c in '\r\n'):
                raise StackError(translate('External credential is empty or spans multiple lines'))
            envs[service_name][field['name']] = value
    public_bindings = public_environment_bindings(services, template['compose_stack']['main_service'], envs) if custom else {}
    if any(addresses[binding['target_service']] == 'dhcp' for bindings in public_bindings.values() for binding in bindings.values()):
        raise StackError(translate('Automatic public URLs require static frontend addresses or explicit URLs'))
    plans = []
    for index, s in enumerate(services):
        main = s['name'] == template['compose_stack']['main_service']
        env = envs[s['name']]
        # Public application URLs cannot retain localhost in a remote deployment.
        for key,value in list(env.items()):
            if custom and key in public_bindings.get(s['name'], {}):
                env[key] = public_bindings[s['name']][key]['value']
            elif not custom and value.startswith(('http://localhost', 'http://127.0.0.1', 'http://0.0.0.0')):
                url = urlsplit(value)
                endpoint = template['first_run']['endpoints'][0]
                env[key] = urlunsplit((url.scheme, '@STACK_LAN_IP@:'+str(endpoint['port']), url.path, url.query, url.fragment))
        s['compose']['environment'] = env
        single, plan = _service_plan(template, s)
        k = kind(s['image'])
        # Values are already resolved; do not reinterpret user credentials as Compose variables.
        plan['environment'] = [{'name':key,'value':value,'sensitive':True} for key,value in env.items() if value != '' or literal]
        plan.update(hostname=stack_lxc_hostname(name, s['name'], main), template_storage=cache,
                    start_after_create=False)
        plan['rootfs']['storage'] = root
        if 'memory_default_mb' not in single['proxmox'].get('installer_profile', {}).get('resources', {}):
            plan['resources']['memory_mb'] = max(1024 if k in {'postgres','mariadb','linuxserver/mariadb','mongo','getmeili/meilisearch'} else 512, plan['resources']['memory_mb'])
        plan['mounts'] = drafts[index]['deployment']['mounts']
        if s['name'] in selected_resources:
            plan['resources'].update(selected_resources[s['name']])
        explicit_check = compose_healthcheck(s) if custom else None
        if s['name'] in jobs:
            health = {'type': 'completed', 'timeout_seconds': 300}
            plan['execution_mode'] = 'one-shot'
        elif explicit_check:
            health = explicit_check
            if main:
                endpoint = service_endpoint(s)
                if endpoint is None:
                    raise StackError(f"{s['name']}: {translate('Main endpoint not yet defined')}")
                health['endpoint'] = endpoint
        elif k == 'postgres':
            health = {'type':'exec','timeout_seconds':180,'argv':['pg_isready','-h','127.0.0.1','-U',env.get('POSTGRES_USER','postgres'),'-d',env.get('POSTGRES_DB',env.get('POSTGRES_USER','postgres'))]}
        elif k == 'mariadb':
            health = {'type':'exec','timeout_seconds':240,'argv':['healthcheck.sh','--connect','--innodb_initialized']}
        elif k == 'linuxserver/mariadb':
            if not all(env.get(key) for key in ('MYSQL_PASSWORD','MYSQL_USER','MYSQL_DATABASE')):
                raise StackError(translate('LinuxServer MariaDB requires a user, database and password'))
            check = "MYSQL_PWD=${MYSQL_PASSWORD:-$(tr '\\000' '\\n' < /proc/1/environ | sed -n 's/^MYSQL_PASSWORD=//p')}; export MYSQL_PWD; [ \"$(mariadb --protocol=tcp -h127.0.0.1 -u\"$1\" -D\"$2\" --batch --skip-column-names -e 'SELECT 1')\" = 1 ]"
            health = {'type':'exec','timeout_seconds':240,'argv':['sh','-c',check,'healthcheck',env['MYSQL_USER'],env['MYSQL_DATABASE']]}
        elif k == 'mongo':
            health = {'type':'exec','timeout_seconds':180,'argv':['mongosh','--quiet','--host','127.0.0.1','--eval','quit(db.adminCommand({ping:1}).ok === 1 ? 0 : 1)']}
        elif k == 'getmeili/meilisearch':
            health = {'type':'http','timeout_seconds':180,'endpoint':{'scheme':'http','port':7700,'path':'/health'}}
        elif k in {'redis','valkey/valkey'}:
            cli = 'redis-cli' if k=='redis' else 'valkey-cli'
            check = '[ "$('+cli+' --raw ping)" = PONG ]'
            if authenticated_redis(s):
                check = "REDISCLI_AUTH=${REDISCLI_AUTH:-$(tr '\\000' '\\n' < /proc/1/environ | sed -n 's/^REDISCLI_AUTH=//p')}; export REDISCLI_AUTH; " + check
            health = {'type':'exec','timeout_seconds':90,'argv':['sh','-c',check]}
        else:
            endpoint = service_endpoint(s, include_expose=not main) if custom else template['first_run']['endpoints'][0]
            if endpoint is None:
                if main or not custom:
                    raise StackError(f"{s['name']}: {translate('Main endpoint not yet defined')}")
                health = {'type': 'running', 'timeout_seconds': 30}
            elif custom and not main and service_endpoint(s) is None:
                health = {'type': 'tcp', 'timeout_seconds': 180, 'port': endpoint['port']}
            else:
                health = {'type':'http','timeout_seconds':360,'endpoint':endpoint}
        plans.append({'name':s['name'],'main':main,'kind':k,'offset':0 if main else len(plans)+1,
                      'aliases':list(dict.fromkeys([s['name'],s['compose'].get('container_name',s['name'])])),
                      'template':single,'deployment':plan,'healthcheck':health})
        if public_bindings.get(s['name']):
            plans[-1]['public_environment_bindings'] = public_bindings[s['name']]
        if s['name'] in frontend_names and s['name'] not in jobs:
            plans[-1]['frontend'] = True
            plans[-1]['frontend_ipv4'] = addresses[s['name']] if labelled_frontends else addresses['']
    if mode != DEFAULT_MODE:
        from .extra_devices import ask_stack_extra_devices
        ask_stack_extra_devices(ui, plans)
    onboot = ui.confirm(translate('Start the stack with Proxmox'), False)
    for plan in plans:
        plan['deployment']['onboot'] = onboot and plan['name'] not in jobs
    return {'deployment_kind':'generic-multi-lxc-stack','stack_name':name,'base_vmid':int(vmid) if vmid else None,
            'completion_notes':template.get('proxmox',{}).get('stack_completion_notes',[]),
            'rootfs_storage':root,'template_storage':cache,'onboot':onboot,'start_after_create':True,
            'network':{'frontend_bridge':bridge,'frontend_gateway':gateway,**({'frontend_vlan_tag':vlan_tag} if vlan_tag else {}),'private_allocation':'automatic','private_bridge':'vmbr10','private_subnet':'10.77.0.0/24','private_host_address':'10.77.0.1/24'},
            'services':plans}


def apply_stack_support(template):
    """Only promote pending imported stacks that the compiler can represent."""
    driver = template.get('proxmox',{}).get('installer_profile',{}).get('stack_driver')
    if driver != 'generic-multi-lxc-stack' and 'native-multi-lxc-orchestrator-not-yet-implemented' not in template.get('compatibility',{}).get('untranslated_blockers',[]):
        return
    errors = assess(template)
    if errors:
        template['proxmox']['generic_stack_review'] = errors
        if driver == 'generic-multi-lxc-stack':
            template['compatibility']['automatic_install_candidate'] = False
            template['compatibility']['untranslated_blockers'] = errors
            template['status'] = 'generated-review-required'
        return
    template['proxmox'].pop('generic_stack_review',None)
    preserved_preparations = template['proxmox'].get('installer_profile',{}).get('volume_preparations')
    template['proxmox']['installer_profile'] = {'stack_driver':'generic-multi-lxc-stack'}
    if preserved_preparations:
        template['proxmox']['installer_profile']['volume_preparations'] = preserved_preparations
    template['compatibility']['untranslated_blockers'] = []
    template['compatibility']['automatic_install_candidate'] = True
    template['status'] = 'generated-unvalidated'
    template['lifecycle']['dependency_lifecycle'] = {'implementation':'proxmox-hookscript','trigger':'main-lxc-pre-start','waits_for_dependency_healthchecks':True,'stops_dependencies_with_main':False}
