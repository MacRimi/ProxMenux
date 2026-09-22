"""Compile supported Compose stacks into the existing single-LXC installer contract."""
from __future__ import annotations

import copy
import base64
import re
import secrets
from urllib.parse import urlsplit, urlunsplit, quote

import yaml

from .casaos import convert_casaos_compose, canonical_image_repository
from .converter import ConversionError
from .converter import _split_short_mount
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
    return repo if repo in {'postgres', 'redis', 'valkey/valkey', 'mariadb', 'linuxserver/mariadb', 'mongo', 'getmeili/meilisearch'} else 'application'


DEPENDENCY_VOLUMES = {'mariadb':['/var/lib/mysql'], 'linuxserver/mariadb':['/config'], 'mongo':['/data/db','/data/configdb'],
                      'getmeili/meilisearch':['/meili_data']}


def authenticated_redis(service):
    c = service['compose']
    return (kind(service['image']) == 'redis' and not c.get('entrypoint')
            and c.get('command') == ['redis-server','--requirepass','${REDISCLI_AUTH}']
            and bool(environment(c.get('environment')).get('REDISCLI_AUTH')))


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
                if condition not in {'service_started', 'service_healthy'}:
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
    targets = {m['target'] for m in mounts}
    for target in DEPENDENCY_VOLUMES.get(kind(service['image']), []):
        if not any(target == t or target.startswith(t.rstrip('/')+'/') for t in targets):
            mounts.append({'type':'volume','target':target})
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
    single['container_contract']['image']['reference'] = service['image']
    single['container_contract']['environment'] = [
        {'name': k, 'example': v, 'required': True, 'sensitive': True, 'prompt_user': False}
        for k, v in c['environment'].items()
    ]
    # Only the main service reports the credentials of the application.
    single['first_run'] = {'endpoints': [],
                           'credentials': copy.deepcopy(parent.get('first_run', {}).get('credentials', [])) if main else []}
    single['proxmox'].setdefault('installer_profile', {}).pop('startup_healthcheck', None)
    return single


def assess(template):
    """Reject untranslated semantics before any host resources are allocated."""
    errors = []
    try:
        services = ordered_services(template)
        top = template['compose_stack'].get('top_level', {})
        if any(k not in {'name', 'networks', 'volumes', 'version'} for k in top):
            raise StackError(translate('Top-level configs, secrets and other global options are not yet supported'))
        networks = top.get('networks', {})
        if len(networks) > 1 or any(v and any(not ((k == 'driver' and x == 'bridge') or (k == 'name' and isinstance(x,str))) for k,x in v.items()) for v in networks.values()):
            raise StackError(translate('Multiple networks or external networks are not yet supported'))
        if any(v for v in top.get('volumes', {}).values()):
            raise StackError(translate('Top-level volume options are not yet supported'))
        seen_sources = set()
        for s in services:
            c = s['compose']
            for key in ('profiles','build','configs','secrets','env_file','pid','privileged','devices','runtime','cap_add','security_opt','network_mode','extra_hosts'):
                if c.get(key):
                    errors.append(f"{s['name']}: {key} {translate('needs stack review')}")
            if s['name'] != template['compose_stack']['main_service'] and kind(s['image']) == 'application':
                errors.append(f"{s['name']}: {translate('health and persistence profile not yet defined')}")
            if kind(s['image']) != 'application' and (c.get('command') or c.get('entrypoint')) and not authenticated_redis(s):
                errors.append(f"{s['name']}: {translate('custom dependency commands are not yet supported')}")
            for m in normalized_mounts(c.get('volumes', [])):
                source = m.get('source')
                if source is not None and source in seen_sources:
                    errors.append(translate('Volumes shared between services are not yet supported'))
                if source is not None:
                    seen_sources.add(source)
                if set(m) - {'type','source','target','read_only'} or m.get('read_only'):
                    errors.append(translate('Volume options are not yet supported'))
                if m['target'].startswith(('/etc/', '/var/run/', '/run/', '/dev/', '/proc/', '/sys/')):
                    errors.append(translate('System path mounts are not yet supported'))
            env = environment(c.get('environment'))
            for k,v in env.items():
                for a,b in VARIABLE.findall(v):
                    variable = a or b
                    if variable not in {'TZ','PUID','PGID'} and not variable.startswith('GENERATED_'):
                        errors.append(f'{s["name"]}: {translate("unsupported variable")} {variable}')
                    if variable.startswith('GENERATED_') and re.search(r'API_KEY|CLIENT_SECRET|CREDENTIALS_ENABLED', variable):
                        errors.append(f'{s["name"]}: {translate("unsupported external credential or boolean")} {variable}')
            single = service_template(template,s)
            errors.extend(f'{s["name"]}: {b}' for b in single['compatibility']['untranslated_blockers'])
        if not template['first_run'].get('endpoints'):
            errors.append(translate('Main endpoint not yet defined'))
        resolve_environments(services, 'UTC', template.get('proxmox', {}).get('stack_generators', {}))
    except (ValueError, KeyError, TypeError, ConversionError) as e:
        errors.append(str(e))
    return sorted(set(errors))


def resolve_environments(services, timezone, generators=None):
    tokens = {'TZ': timezone, 'PUID': '1000', 'PGID': '1000'}
    resolved = {}
    for s in services:
        env = environment(s['compose'].get('environment'))
        def replace(match):
            name = match.group(1) or match.group(2)
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
    # Bind URL credentials using the destination service, never a global text replacement.
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
    def ask(self, text, default=None, required=True):
        return default if default is not None else ''
    def choose(self, text, options, default=None):
        return default
    def confirm(self, text, default=False):
        return default
    def info(self, text):
        pass


def build_stack(template, ui):
    from .installer import build_deployment, _hostname_default
    problems = assess(template)
    if problems:
        raise StackError('; '.join(problems))
    services = copy.deepcopy(ordered_services(template))
    defaults = template['proxmox']['defaults']
    name = _hostname_default(ui.ask(translate('Stack name'), template['compose_stack']['project_name']))
    vmid = ui.ask(translate('Base VMID (empty = next free block)'), '', required=False)
    from . import host
    from . import network as access
    from .installer import ask_bridge, ask_storage
    root = ask_storage(ui, translate('Storage for rootfs'), 'rootdir', defaults['rootfs_storage'])
    volumes = ask_storage(ui, translate('Storage for persistent data'), 'rootdir', defaults['volume_storage'])
    cache = ask_storage(ui, translate('Storage for the OCI image cache'), 'vztmpl', defaults['template_storage'])
    bridge = ask_bridge(ui, translate('Access bridge'), defaults['bridge'])
    addresses, gateway = access.ask_addresses(ui, bridge, [''])
    timezone = ui.ask(translate('Timezone'), host.timezone())
    onboot = ui.confirm(translate('Start the stack with Proxmox'), False)
    envs = resolve_environments(services, timezone, template.get('proxmox', {}).get('stack_generators', {}))
    for group in template.get('proxmox', {}).get('stack_optional_environment', []):
        service_name = group['service']
        if service_name not in envs:
            raise StackError(f"{translate('Unknown credential service:')} {service_name}")
        if not ui.confirm(f"{translate('Configure')} {group['label']} ({translate('optional')})", False):
            continue
        for field in group['fields']:
            if field['name'] not in envs[service_name] or envs[service_name][field['name']] != '':
                raise StackError(f"{translate('External field not reserved:')} {field['name']}")
            value = (ui.password(field['label'], required=True) if field.get('sensitive',True)
                     else ui.ask(field['label'], required=True))
            if not value or any(c in value for c in '\r\n'):
                raise StackError(translate('External credential is empty or spans multiple lines'))
            envs[service_name][field['name']] = value
    plans = []
    for index, s in enumerate(services):
        main = s['name'] == template['compose_stack']['main_service']
        env = envs[s['name']]
        # Public application URLs cannot retain localhost in a remote deployment.
        for key,value in list(env.items()):
            if value.startswith(('http://localhost', 'http://127.0.0.1', 'http://0.0.0.0')):
                url = urlsplit(value)
                endpoint = template['first_run']['endpoints'][0]
                env[key] = urlunsplit((url.scheme, '@STACK_LAN_IP@:'+str(endpoint['port']), url.path, url.query, url.fragment))
        s['compose']['environment'] = env
        single = service_template(template, s, main)
        k = kind(s['image'])
        if k == 'postgres':
            # Official PostgreSQL 18+ stores versioned PGDATA under this parent.
            for m in single['container_contract']['volumes']:
                if m['container_path'] == '/var/lib/postgresql/data' and s['image'].endswith(':latest'):
                    m['container_path'] = '/var/lib/postgresql'
        for e in single['container_contract']['environment']:
            e['required'] = bool(e['example'])
            e['example'] = 'stack-resolved-value' if e['example'] else ''
        plan = build_deployment(single, DefaultsUI())
        # Values are already resolved; do not reinterpret user credentials as Compose variables.
        plan['environment'] = [{'name':key,'value':value,'sensitive':True} for key,value in env.items() if value != '']
        plan.update(hostname=_hostname_default(name+'-'+s['name']), template_storage=cache,
                    onboot=onboot, start_after_create=False)
        plan['rootfs']['storage'] = root
        if 'memory_default_mb' not in single['proxmox'].get('installer_profile', {}).get('resources', {}):
            plan['resources']['memory_mb'] = max(1024 if k in {'postgres','mariadb','linuxserver/mariadb','mongo','getmeili/meilisearch'} else 512, plan['resources']['memory_mb'])
        for m in plan['mounts']:
            mode = ui.choose(f"{s['name']}: {m['container_path']}", [('managed-volume',translate('Container volume (included in backups)')),('host-bind',translate('Host directory'))], 'managed-volume')
            if mode is None:
                raise StackError(translate('Storage selection cancelled'))
            m.update(type=mode, source=volumes, backup=mode=='managed-volume')
            if mode == 'host-bind':
                m['source'] = ui.ask(translate('Host directory'), '/mnt/oci-shared/'+name+'/'+s['name']+'/'+m['container_path'].strip('/').replace('/','-'))
                m['size_gb'] = None
            else:
                m['size_gb'] = int(ui.ask(translate('Volume size in GB'), str(max(8,m['size_gb'] or 8))))
            if m['size_gb'] is not None and m['size_gb'] < 1:
                raise StackError(translate('Invalid volume size'))
        from .custom_mounts import ask_custom_mounts
        plan['mounts'] = ask_custom_mounts(ui, plan['mounts'], volumes)
        if k == 'postgres':
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
            endpoint = template['first_run']['endpoints'][0]
            health = {'type':'http','timeout_seconds':360,'endpoint':endpoint}
        plans.append({'name':s['name'],'main':main,'kind':k,'offset':0 if main else len(plans)+1,
                      'aliases':list(dict.fromkeys([s['name'],s['compose'].get('container_name',s['name'])])),
                      'template':single,'deployment':plan,'healthcheck':health})
        if main:
            plans[-1]['frontend_ipv4'] = addresses['']
    return {'deployment_kind':'generic-multi-lxc-stack','stack_name':name,'base_vmid':int(vmid) if vmid else None,
            'completion_notes':template.get('proxmox',{}).get('stack_completion_notes',[]),
            'rootfs_storage':root,'template_storage':cache,'onboot':onboot,'start_after_create':True,
            'network':{'frontend_bridge':bridge,'frontend_gateway':gateway,'private_allocation':'automatic','private_bridge':'vmbr10','private_subnet':'10.77.0.0/24','private_host_address':'10.77.0.1/24'},
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
    template['proxmox']['installer_profile'] = {'stack_driver':'generic-multi-lxc-stack'}
    template['compatibility']['untranslated_blockers'] = []
    template['compatibility']['automatic_install_candidate'] = True
    template['status'] = 'generated-unvalidated'
    template['lifecycle']['dependency_lifecycle'] = {'implementation':'proxmox-hookscript','trigger':'main-lxc-pre-start','waits_for_dependency_healthchecks':True,'stops_dependencies_with_main':False}
