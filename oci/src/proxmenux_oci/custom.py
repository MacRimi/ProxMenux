"""An image that is not in the catalog: its Compose file, or the image itself,
is translated into the same template the catalog applications use."""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from . import console
from .casaos import convert_casaos_compose, normalize_app_id
from .cli import install_template
from .i18n import source_text
from .installer import ADVANCED_MODE, DEFAULT_MODE
from .converter import ConversionError
from .i18n import translate
from .ui import UserCancelled

IMAGE_REFERENCE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?(?:@sha256:[a-f0-9]{64})?$')
MAX_COMPOSE_BYTES = 256 * 1024


class _Dumper(yaml.SafeDumper):
    """Compose written the way it is read: lists indented under their key, so
    the #optional markers of the documentation keep their meaning."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _dump(document: dict[str, Any]) -> str:
    return yaml.dump(document, Dumper=_Dumper, default_flow_style=False, sort_keys=True)


def _services(compose: dict[str, Any]) -> dict[str, Any]:
    services = compose.get('services')
    if not isinstance(services, dict) or not services:
        raise ConversionError(translate('The Compose file declares no service'))
    return services


def _published_port(service: dict[str, Any]) -> str | None:
    for item in service.get('ports') or []:
        if isinstance(item, dict):
            published = item.get('published') or item.get('target')
        else:
            parts = str(item).split('/', 1)[0].split(':')
            published = parts[-2] if len(parts) > 1 else parts[-1]
        if str(published or '').isdigit():
            return str(published)
    return None


# Directories of the host that no application receives this way. The two time
# settings are the usual exception and are harmless.
HOST_SYSTEM_PATHS = ('/', '/bin', '/boot', '/dev', '/etc', '/lib', '/lib64', '/proc',
                     '/root', '/run', '/sbin', '/sys', '/usr', '/var')
TIME_SETTINGS = ('/etc/localtime', '/etc/timezone')


def _check_mounts(service: dict[str, Any]) -> None:
    """A Compose file that reaches into the host or into the Docker engine is
    refused before anything else, with the reason."""
    for item in service.get('volumes') or []:
        if isinstance(item, dict):
            source, target = str(item.get('source') or ''), str(item.get('target') or '')
        else:
            parts = str(item).split(':')
            source, target = (parts[0], parts[1]) if len(parts) > 1 else ('', parts[0])
        if 'docker.sock' in source or 'docker.sock' in target:
            raise ConversionError(translate('It works through the Docker engine of the host, '
                                            'and a native OCI container does not have one.'))
        for path in (source, target):
            clean = path.rstrip('/') or '/'
            if clean in TIME_SETTINGS or not clean.startswith('/'):
                continue
            if clean in HOST_SYSTEM_PATHS:
                raise ConversionError(
                    f"{translate('It asks for a system directory of the host:')} {clean}. "
                    f"{translate('ProxMenux does not give a container the system of its host.')}")


def _keep_reference(template: dict[str, Any], reference: str) -> None:
    """The catalog normalizes every image to its latest tag; an image given by
    hand keeps the tag or the digest that was written."""
    repository, _, digest = reference.partition('@')
    tag = ''
    if ':' in repository.rsplit('/', 1)[-1]:
        repository, _, tag = repository.rpartition(':')
    image = template['container_contract']['image']
    image['reference'] = reference if (tag or digest) else f'{repository}:latest'
    image['repository'] = repository
    image['tag'] = tag or ('' if digest else 'latest')
    image['digest'] = f'@{digest}' if digest else None
    if tag or digest:
        image['pull_policy'] = 'resolve-written-reference-to-architecture-digest-at-install'


def template_from_compose(text: str, title: str | None = None) -> dict[str, Any]:
    """The template of a Compose file with a single service. The metadata the
    importer expects is taken from the service itself."""
    try:
        compose = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConversionError(f"{translate('The Compose file is not valid YAML:')} {error}") from error
    if not isinstance(compose, dict):
        raise ConversionError(translate('The Compose file does not contain a Compose document'))
    services = _services(compose)
    if len(services) > 1:
        raise ConversionError(
            f"{translate('The Compose file describes several services:')} {', '.join(services)}. "
            f"{translate('Only one service at a time can be installed this way.')}")
    name = next(iter(services))
    service = services[name] or {}
    if not service.get('image'):
        raise ConversionError(f"{translate('The service declares no image:')} {name}")
    if service.get('build'):
        raise ConversionError(translate('The service builds its own image; only a published image can be installed'))
    _check_mounts(service)
    identifier = normalize_app_id(str(compose.get('name') or title or name))
    metadata: dict[str, Any] = {'main': name, 'title': {'en_US': title or name}}
    port = _published_port(service)
    if port:
        metadata.update(port_map=port, scheme='http', index='/')
    if compose.get('x-casaos'):
        document = text
    else:
        document = text.rstrip('\n') + '\n' + _dump({'x-casaos': metadata})
    template = convert_casaos_compose(document, 'local', '',
                                      f'local/{identifier}/docker-compose.yml', '')
    _keep_reference(template, str(service['image']))
    # The container takes its time settings from Proxmox, so the time files of
    # the host are not attached to it.
    contract = template['container_contract']
    contract['volumes'] = [volume for volume in contract.get('volumes', [])
                           if volume['container_path'] not in TIME_SETTINGS]
    profile = template.setdefault('proxmox', {}).setdefault('installer_profile', {})
    preparations = []
    for volume in contract.get('volumes', []):
        # Docker marks paths as read-only in its own command; the container
        # here gets them read and write, and the user decides where they go.
        volume['read_only'] = False
        # A fresh ext4 volume carries lost+found, which stops the images that
        # take ownership of their own directories.
        preparations.append({'container_path': volume['container_path'],
                             'remove_lost_found': True,
                             'owner_strategy': 'mapped-application-user',
                             'only_when_mount_type': 'managed-volume'})
    if preparations:
        profile['volume_preparations'] = preparations
    files = [volume['container_path'] for volume in template['container_contract'].get('volumes', [])
             if Path(volume['container_path']).suffix]
    if files:
        raise ConversionError(
            f"{translate('These container mount paths have an extension-like suffix:')} {', '.join(files)}. "
            f"{translate('This import rejects these paths without checking whether they are files or directories.')}")
    return template


def compose_from_image(reference: str, title: str | None = None) -> str:
    """A Compose file written from what the image declares: its ports, its
    persistent paths and its variables."""
    if not IMAGE_REFERENCE.fullmatch(reference):
        raise ConversionError(f"{translate('This is not a valid image reference:')} {reference}")
    result = subprocess.run(['skopeo', 'inspect', '--config', f'docker://{reference}'],
                            capture_output=True, text=True, check=False, timeout=120)
    if result.returncode != 0:
        raise ConversionError(f"{translate('The image could not be read from its registry:')} "
                              f"{(result.stderr or '').strip().splitlines()[-1] if result.stderr else reference}")
    config = (json.loads(result.stdout) or {}).get('config') or {}
    name = normalize_app_id(title or reference.rsplit('/', 1)[-1].split(':', 1)[0].split('@', 1)[0])
    service: dict[str, Any] = {'image': reference}
    ports = [port.split('/', 1)[0] for port in (config.get('ExposedPorts') or {})
             if port.endswith('/tcp') or '/' not in port]
    if ports:
        service['ports'] = [f'{port}:{port}' for port in ports]
    volumes = sorted(config.get('Volumes') or {})
    if volumes:
        service['volumes'] = [f'./{Path(path).name or "data"}:{path}' for path in volumes]
    environment = [item for item in (config.get('Env') or [])
                   if '=' in item and item.split('=', 1)[0] not in {'PATH', 'HOME', 'TERM'}]
    if environment:
        service['environment'] = environment
    return _dump({'name': name, 'services': {name: service}})


DOCKER_RUN_VALUE_FLAGS = {
    '--name': 'container_name', '--hostname': 'hostname', '-h': 'hostname',
    '--restart': 'restart', '--user': 'user', '-u': 'user',
    '--workdir': 'working_dir', '-w': 'working_dir', '--entrypoint': 'entrypoint',
    '--shm-size': 'shm_size', '--network': 'network_mode', '--net': 'network_mode',
    '--ipc': 'ipc', '--runtime': 'runtime', '--memory': 'mem_limit', '-m': 'mem_limit',
    '--stop-timeout': 'stop_grace_period',
}
DOCKER_RUN_LIST_FLAGS = {
    '-p': 'ports', '--publish': 'ports', '-v': 'volumes', '--volume': 'volumes',
    '-e': 'environment', '--env': 'environment', '--device': 'devices',
    '--cap-add': 'cap_add', '--sysctl': 'sysctls', '--group-add': 'group_add',
    '--add-host': 'extra_hosts', '--label': 'labels', '--security-opt': 'security_opt',
}
DOCKER_RUN_IGNORED = {'-d', '--detach', '--rm', '-i', '--interactive', '-t', '--tty',
                      '-it', '-ti', '--init', '--pull', '--quiet', '-q'}


def compose_from_docker_run(command: str, title: str | None = None) -> str:
    """The Compose file of a `docker run` command, which is how many images
    are documented."""
    # Documentation writes optional lines as `#optional`, a shell comment that
    # produces nothing when the command runs; here it is removed as well.
    text = re.sub(r'`\s*#\s*optional\s*`', ' \x00optional\x00 ', command, flags=re.I)
    text = re.sub(r'`[^`]*`', ' ', text).replace('\\\n', ' ').replace('\\', ' ')
    # `-u $(id -u)` runs the container as the user who types the command; the
    # LXC takes the user of the image instead, and its volumes are owned by it.
    text, host_user = re.subn(r'(?:-u|--user)\s+\$\([^)]*\)(?::\$\([^)]*\))?', ' ', text)
    remaining = re.search(r'\$\([^)]*\)', text)
    if remaining:
        raise ConversionError(f"{translate('The command works out a value by running another command:')} "
                              f"{remaining.group(0)}. {translate('Write the value it produces instead.')}")
    tokens = [token for token in shlex.split(text) if not token.startswith('#')]
    optional: set[str] = set()
    for position, token in enumerate(tokens):
        if token == '\x00optional\x00' and position:
            optional.add(tokens[position - 1])
    tokens = [token for token in tokens if token != '\x00optional\x00']
    while tokens and tokens[0] in {'sudo', 'docker', 'podman', 'container', 'run'}:
        tokens.pop(0)
    service: dict[str, Any] = {}
    unsupported: list[str] = []
    image = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith('-'):
            image = token
            arguments = tokens[index + 1:]
            if arguments:
                service['command'] = arguments
            break
        flag, _, inline = token.partition('=')
        value = inline if inline else None
        if flag in DOCKER_RUN_IGNORED or token in DOCKER_RUN_IGNORED:
            index += 1
            continue
        if flag in DOCKER_RUN_VALUE_FLAGS or flag in DOCKER_RUN_LIST_FLAGS:
            if value is None:
                index += 1
                value = tokens[index] if index < len(tokens) else ''
            if flag in DOCKER_RUN_VALUE_FLAGS:
                service[DOCKER_RUN_VALUE_FLAGS[flag]] = value
            else:
                service.setdefault(DOCKER_RUN_LIST_FLAGS[flag], []).append(value)
        elif flag == '--privileged':
            service['privileged'] = True
        elif flag == '--gpus':
            if value is None and index + 1 < len(tokens) and not tokens[index + 1].startswith('-'):
                index += 1
            service['deploy'] = {'resources': {'reservations': {'devices': [
                {'driver': 'nvidia', 'count': 'all', 'capabilities': ['gpu']}]}}}
        elif flag in {'--env-file'}:
            raise ConversionError(translate('The command reads its variables from a file; '
                                            'write them in the command or use a Compose file'))
        else:
            unsupported.append(flag)
        index += 1
    if unsupported:
        raise ConversionError(f"{translate('The command uses options that cannot be translated:')} "
                              f"{', '.join(sorted(set(unsupported)))}")
    if not image:
        raise ConversionError(translate('The command does not name an image'))
    if not IMAGE_REFERENCE.fullmatch(image):
        raise ConversionError(f"{translate('This is not a valid image reference:')} {image}")
    service['image'] = image
    name = normalize_app_id(title or service.get('container_name')
                            or image.rsplit('/', 1)[-1].split(':', 1)[0].split('@', 1)[0])
    document = _dump({'name': name, 'services': {name: service}})
    if host_user:
        note = translate('The command runs the container as the user of the host; the container '
                         'uses the user of its image instead.')
        document = f'#note: {note}\n' + document
    if not optional:
        return document
    lines = []
    for line in document.splitlines():
        value = line.strip().lstrip('- ').strip().strip('\'"')
        lines.append(f'{line} #optional' if value and value in optional else line)
    return '\n'.join(lines) + '\n'


def _read_url(url: str) -> str:
    if not url.startswith(('http://', 'https://')):
        raise ConversionError(translate('The address must start with http:// or https://'))
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - the user gives the address
        return response.read(MAX_COMPOSE_BYTES + 1).decode('utf-8', errors='replace')


def _read_file(path: str) -> str:
    file = Path(path).expanduser()
    if not file.is_file():
        raise ConversionError(f"{translate('The file does not exist:')} {file}")
    if file.stat().st_size > MAX_COMPOSE_BYTES:
        raise ConversionError(translate('The file is too large to be a Compose file'))
    return file.read_text(encoding='utf-8', errors='replace')


def _read_pasted(ui, title: str | None = None) -> str:
    """The definition is pasted in the terminal: dialog cannot take it."""
    console.show_logo()
    console.msg_title(title or translate('Compose file of the application'))
    console.msg_info2(translate('Paste it here and press Ctrl+D on an empty line.'))
    print()
    text = sys.stdin.read(MAX_COMPOSE_BYTES + 1)
    if not text.strip():
        raise UserCancelled(translate('No docker run command was given') if title is not None
                            else translate('No Compose file was given'))
    return text


def read_definition(ui) -> tuple[str, str]:
    """The Compose file of the application and where it came from."""
    from .cli import MENU_SIZE
    source = ui.choose(translate('How is the image described?'), [
        ('paste', translate('Paste its Compose file in the terminal')),
        ('file', translate('Read its Compose file from a file of this host')),
        ('url', translate('Download its Compose file from an address')),
        ('run', translate('Paste its docker run command in the terminal')),
        ('image', translate('Only the image reference, with no Compose file')),
    ], 'paste', title=translate('Image that is not in the catalog'), size=MENU_SIZE)
    if source is None:
        raise UserCancelled(translate('Image selection was cancelled'))
    if source == 'paste':
        return _read_pasted(ui), translate('pasted Compose file')
    if source == 'file':
        return _read_file(ui.ask(translate('Path of the Compose file'), '/root/docker-compose.yml')), \
            translate('Compose file of this host')
    if source == 'url':
        return _read_url(ui.ask(translate('Address of the Compose file'), '')), translate('downloaded Compose file')
    if source == 'run':
        return compose_from_docker_run(_read_pasted(ui, translate('docker run command of the application'))), \
            translate('docker run command')
    reference = ui.ask(translate('Image reference (for example ghcr.io/user/application:latest)'), '')
    return compose_from_image(reference), translate('image itself')


BLOCKER_TEXTS = {
    'multi-service-compose': 'it describes more than one image',
    'native-multi-lxc-orchestrator-not-yet-implemented': 'it describes more than one image',
    'top-level-configs': 'it uses Compose configs, which have no equivalent here',
    'devices-format': 'the devices it asks for are not written in a way that can be read',
    'healthcheck-format': 'its health check is not written in a way that can be read',
    'stop-grace-period-format': 'its stop timeout is not written in a way that can be read',
    'shm-size-format': 'its shared memory size is not written in a way that can be read',
    'ulimits-format-or-resource': 'the resource limits it asks for cannot be applied',
    'mem-limit-format-or-below-proxmox-minimum': 'the memory limit it asks for cannot be applied',
    'mem-limit-deploy-consistency-review': 'it asks for two different memory limits',
}


def blocker_text(code: str) -> str:
    """The reason a definition cannot be installed, in plain words."""
    code = re.sub(r'^service:[^:]+:', '', code)
    if code in BLOCKER_TEXTS:
        return translate(BLOCKER_TEXTS[code])
    if code.startswith('compose-key:'):
        return f"{translate('it uses the Compose option')} {code.split(':', 1)[1]}"
    if code.startswith('device-mapping:'):
        return f"{translate('a device it asks for cannot be translated:')} {code.split(':', 1)[1]}"
    if code.endswith(':missing-image'):
        return translate('one of its services declares no image')
    if code.endswith(':invalid-definition'):
        return translate('one of its services is not written as a service')
    return code


def ignored_settings(text: str) -> list[str]:
    """Settings of the definition that only mean something in Docker and are
    not applied here; the user should know they were read and left aside."""
    try:
        compose = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(compose, dict):
        return []
    notes = []
    for service in (compose.get('services') or {}).values():
        if not isinstance(service, dict):
            continue
        deploy = service.get('deploy') or {}
        swarm = sorted(set(deploy) - {'resources'}) if isinstance(deploy, dict) else []
        if swarm:
            notes.append(f"{translate('Only a Docker Swarm uses these settings, so they are not applied:')} "
                         f"deploy.{', deploy.'.join(swarm)}")
        if service.get('labels'):
            notes.append(translate('Its labels are not applied: they are read by other Docker tools.'))
    for service in (compose.get('services') or {}).values():
        if isinstance(service, dict) and any(
                str(item).split(':')[0].rstrip('/') in TIME_SETTINGS for item in service.get('volumes') or []
                if not isinstance(item, dict)):
            notes.append(translate('The container takes its time zone from Proxmox, so the time files '
                                   'of the host are not attached to it.'))
            break
    if compose.get('networks') or compose.get('volumes'):
        notes.append(translate('The container gets its own address and its own volumes, so the networks '
                               'and volumes declared in the file are not used.'))
    return notes


def registry_report(reference: str) -> tuple[bool, str]:
    """Whether the image really exists in its registry, and for which
    architectures. A name written by hand is easy to get wrong."""
    result = subprocess.run(['skopeo', 'inspect', '--raw', f'docker://{reference}'],
                            capture_output=True, text=True, check=False, timeout=120)
    if result.returncode != 0:
        return False, f"{translate('Could not inspect the image in its registry:')} {reference}"
    try:
        document = json.loads(result.stdout)
    except ValueError:
        return True, translate('The image is in its registry.')
    manifests = document.get('manifests')
    if not manifests:
        # The image publishes a single manifest: its architecture is in the image itself.
        detail = subprocess.run(['skopeo', 'inspect', f'docker://{reference}'],
                                capture_output=True, text=True, check=False, timeout=120)
        try:
            architecture = json.loads(detail.stdout).get('Architecture') if detail.returncode == 0 else None
        except ValueError:
            architecture = None
        if not architecture:
            return True, translate('The image is in its registry, for one architecture.')
        return True, (f"{translate('The image is in its registry:')} {architecture} "
                      f"({translate('it publishes no other architecture')})")
    architectures = sorted({item.get('platform', {}).get('architecture', '')
                            for item in manifests} - {'', 'unknown'})
    return True, f"{translate('The image is in its registry:')} {', '.join(architectures)}"


def describe(template: dict[str, Any]) -> str:
    """What the translation understood, in the words of the installer, with
    everything that changes how the container is created."""
    contract = template['container_contract']
    proxmox = template.get('proxmox', {}) or {}
    profile = proxmox.get('installer_profile', {}) or {}
    security = proxmox.get('security_profile', {}) or {}
    lines = [f"{translate('Image') + ':':<14} {contract['image']['reference']}"]
    endpoints = template.get('first_run', {}).get('endpoints') or []
    if endpoints:
        # The address is read from the published port; the image does not say
        # whether it answers over http or https.
        lines.append(f"{translate('Web access') + ':':<14} " + ', '.join(
            f"{item.get('scheme', 'http')}://<IP>:{item.get('port')}{item.get('path') or '/'}" for item in endpoints)
            + f" ({translate('https if the image serves TLS')})")
    # The container has its own address, so the port Docker publishes on the
    # host is not used: the application answers on its own port.
    ports = []
    republished = False
    for port in contract.get('ports') or []:
        ports.append(str(port['container_port']) + ('' if port.get('required', True)
                                                    else f" ({translate('optional')})"))
        republished = republished or (port.get('published_example')
                                      and int(port['published_example']) != int(port['container_port']))
    if ports:
        lines.append(f"{translate('Ports') + ':':<14} {', '.join(ports)}")
        if republished:
            own = translate('the container has its own address, so the port Docker published '
                            'on the host is not needed')
            lines.append(f"{'':<14} {own}")
    if (profile.get('network') or {}).get('compose_mode') == 'host':
        # Docker shares the network of the host; in Proxmox the container has
        # its own address, which is what the installation gives it.
        lines.append(f"{translate('Network') + ':':<14} "
                     f"{translate('it asks for the network of the host; the container gets its own address instead')}")
    volumes = contract.get('volumes') or []
    if volumes:
        lines += ['', translate('Persistent data:')]
        lines += [f"  {volume['container_path']}"
                  + ('' if volume.get('default') != 'skip' else f" ({translate('optional')})")
                  for volume in volumes]
    environment = contract.get('environment') or []
    if environment:
        lines += ['', translate('Variables the installation asks for:')]
        lines += [f"  {item['name']}"
                  + (f" = {item['example']}" if item.get('example') and not item['sensitive'] else '')
                  + ('' if item.get('required', True) else f" ({translate('optional')})")
                  for item in environment]
    devices = profile.get('device_requests') or []
    if devices:
        lines += ['', translate('Devices of the host it asks for:')]
        lines += [f"  {translate(str(item.get('enable_prompt') or item.get('purpose') or item.get('id')))}"
                  for item in devices]
    warnings = []
    if security.get('requires_privileged_lxc'):
        warnings.append(translate('This profile requires a privileged LXC, which reduces isolation from the host.'))
    elif security.get('source_requests_privileged_lxc') or security.get('optional_privileged_lxc'):
        warnings.append(translate('Its Compose file asks for privileged mode; the container is created '
                                  'unprivileged and that mode is only offered as an option.'))
    if security.get('requires_relaxed_confinement') or security.get('source_requests_relaxed_confinement'):
        warnings.append(translate('A relaxed AppArmor or seccomp profile is requested; this may be optional.'))
    if security.get('requires_host_pid_namespace'):
        warnings.append(translate('It asks to see the processes of the host.'))
    if warnings:
        lines += ['', translate('Worth knowing before installing it:')] + [f'  {text}' for text in warnings]
    blockers = template.get('compatibility', {}).get('untranslated_blockers') or []
    if blockers:
        lines += ['', translate('What cannot be translated:')] + [f'  {blocker_text(blocker)}' for blocker in blockers]
    return '\n'.join(lines)


# A value that looks like a secret is asked during the installation instead of
# being taken from the definition, where it is usually the documented example.
SECRET_NAME = re.compile(r'(?:^|_)(pass|passwd|password|pwd?|secret|token|apikey|api_key|key)$', re.I)


def _ask_secrets(template: dict[str, Any]) -> list[str]:
    asked = []
    for item in template['container_contract'].get('environment', []):
        if SECRET_NAME.search(item['name']) and not item['sensitive']:
            item.update(sensitive=True, example='', required=True)
            asked.append(item['name'])
    return asked


def _name(ui, template: dict[str, Any]) -> str:
    default = normalize_app_id(source_text(template['catalog_ui'].get('title'))
                               or template['container_contract'].get('container_name') or 'oci-app')
    name = normalize_app_id(ui.ask(translate('Name for this application'), default))
    if not name:
        raise UserCancelled(translate('No name was given'))
    template['catalog_ui']['title'] = {'en_US': name}
    template['container_contract']['container_name'] = name
    return name


def explore(ui) -> None:
    """Reads a Compose file, a docker run command or an image reference,
    reports what ProxMenux would install from it and installs it."""
    text, origin = read_definition(ui)
    notes = [line.partition(':')[2].strip() for line in text.splitlines() if line.startswith('#note:')]
    notes += ignored_settings(text)
    template = template_from_compose(text)
    title = translate('Image that is not in the catalog')
    summary = describe(template)
    available, report = registry_report(template['container_contract']['image']['reference'])
    summary += '\n\n' + report
    if notes:
        summary += '\n\n' + '\n'.join(notes)
    if not available:
        advice = translate('Check the image reference and registry access. If the registry is unavailable, '
                           'try again later. A private registry needs credentials, which are not supported yet.')
        ui.message(f'{summary}\n\n{advice}', title)
        return
    if not template.get('compatibility', {}).get('automatic_install_candidate'):
        ui.message(f"{translate('This image cannot be installed as it is described:')}\n\n{summary}", title)
        return
    secrets = _ask_secrets(template)
    if secrets:
        summary += ('\n\n' + translate('These values are asked during the installation:') + ' '
                    + ', '.join(secrets))
    if not ui.review(f"{translate('This is what ProxMenux understood from the')} {origin}:\n\n{summary}",
                     title, question=translate('Install this image?'), default=False):
        return
    mode = ui.choose(translate('How is it installed?'),
                     [(DEFAULT_MODE, translate('Default: only what the application needs')),
                      (ADVANCED_MODE, translate('Advanced: every setting of the container'))],
                     DEFAULT_MODE, title=title)
    if mode is None:
        return
    # The record of the instance keeps the whole template, which is what an
    # update, a recreation or a removal read later.
    install_template(ui, template, _name(ui, template), mode)
