"""Supply missing resolver/hosts files for unmanaged OCI images before boot.

PVE's unmanaged setup deliberately does not create these runtime files. Keep
image-provided files, symlinks, explicit mounts and PVE ignore markers intact.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re

from oci_carried_record import mapped_root
from oci_installation_state import parse_config


def resolver_fields(text):
    fields = {'nameserver': [], 'search': [], 'options': []}
    for line in text.splitlines():
        words = line.split('#', 1)[0].split(';', 1)[0].split()
        if len(words) < 2:
            continue
        if words[0] == 'nameserver':
            fields['nameserver'].append(str(ipaddress.ip_address(words[1])))
        elif words[0] in ('search', 'domain'):
            fields['search'] = words[1:]
        elif words[0] == 'options':
            fields['options'] = words[1:]
    return fields


def domains(value):
    result = re.split(r'[\s,;]+', value.strip()) if value.strip() else []
    if any(len(name) > 253 or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', name)
           for name in result):
        raise ValueError('Invalid DNS search domain')
    return result


def network_content(config, host_resolver, upstream_resolver=''):
    host = resolver_fields(host_resolver)
    search = domains(config.get('searchdomain', ' '.join(host['search'])))
    if config.get('nameserver'):
        servers = [str(ipaddress.ip_address(value))
                   for value in re.split(r'[\s,;]+', config['nameserver'].strip())]
    else:
        servers = host['nameserver']
        if config.get('lxc.net.0.type') != 'none':
            # A resolver listening on the host's loopback is not in the LXC's
            # network namespace. systemd-resolved publishes its real upstreams.
            servers = [s for s in servers if not ipaddress.ip_address(s).is_loopback]
            if not servers:
                servers = [s for s in resolver_fields(upstream_resolver)['nameserver']
                           if not ipaddress.ip_address(s).is_loopback]
    servers = list(dict.fromkeys(servers))
    if not servers or any(ipaddress.ip_address(s).is_unspecified for s in servers):
        raise ValueError('No usable DNS server: configure container DNS or a non-loopback host resolver')
    options = host['options']
    if any(not re.fullmatch(r'[A-Za-z0-9_:=-]+', value) for value in options):
        raise ValueError('Invalid resolver option')
    resolver = ''.join(f'nameserver {server}\n' for server in servers[:3])
    if search:
        resolver += 'search ' + ' '.join(search) + '\n'
    if options:
        resolver += 'options ' + ' '.join(options) + '\n'
    return resolver, search


def explicit_mount(deployment, target):
    return any((path := mount.get('container_path', '').rstrip('/'))
               and (path == target or target.startswith(path + '/'))
               for mount in deployment.get('mounts', []))


def present(directory, name):
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def create(directory, name, content, owner):
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o644, dir_fd=directory)
    except FileExistsError:
        return False
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o644)
        os.fchown(stream.fileno(), *owner)
        stream.write(content)
    return True


def prepare(rootfs, config_text, deployment, host_resolver, upstream_resolver=''):
    config = parse_config(config_text.encode())
    if config.get('ostype') != 'unmanaged' or explicit_mount(deployment, '/etc'):
        return []
    kept = deployment.get('kept_proxmox_settings') or {}
    for key in ('nameserver', 'searchdomain', 'hostname'):
        if key in kept:
            config[key] = str(kept[key])
    owner = mapped_root(config_text)
    # The installer passes the trusted mounted rootfs. Never follow an image's
    # /etc symlink when creating a file from the host namespace.
    root = os.open(rootfs, os.O_RDONLY | os.O_DIRECTORY)
    try:
        created = False
        try:
            os.mkdir('etc', mode=0o755, dir_fd=root)
            created = True
        except FileExistsError:
            pass
        directory = os.open('etc', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    finally:
        os.close(root)
    try:
        if created:
            os.fchmod(directory, 0o755)
            os.fchown(directory, *owner)
        wanted = [name for name in ('resolv.conf', 'hosts')
                  if not explicit_mount(deployment, '/etc/' + name)
                  and not present(directory, name)
                  and not present(directory, '.pve-ignore.' + name)]
        if not wanted:
            return []
        resolver, search = ('', [])
        if 'resolv.conf' in wanted:
            resolver, search = network_content(config, host_resolver, upstream_resolver)
        else:
            search = domains(config.get('searchdomain', ''))
        hostname = config.get('hostname', '')
        if hostname and (len(hostname) > 253 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', hostname)):
            raise ValueError('Invalid container hostname')
        hosts = '127.0.0.1 localhost\n::1 localhost ip6-localhost ip6-loopback\n'
        if hostname:
            names = [hostname + '.' + search[0], hostname] if '.' not in hostname and search else [hostname]
            hosts += '127.0.1.1 ' + ' '.join(names) + '\n'
        contents = {'resolv.conf': resolver, 'hosts': hosts}
        return [name for name in wanted if create(directory, name, contents[name], owner)]
    finally:
        os.close(directory)


def read_optional(path):
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return ''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rootfs', type=Path)
    parser.add_argument('config', type=Path)
    parser.add_argument('deployment', type=Path)
    args = parser.parse_args()
    prepare(args.rootfs, args.config.read_text(), json.loads(args.deployment.read_text()),
            read_optional('/etc/resolv.conf'), read_optional('/run/systemd/resolve/resolv.conf'))
