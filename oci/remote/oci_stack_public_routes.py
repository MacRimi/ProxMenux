#!/usr/bin/env python3
"""Owned /32 routes to a stack's own frontends, installed before OCI init."""
import argparse
import copy
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import uuid

DIRECTORY = Path('/etc/pve/priv/proxmenux-stack-public-routes')
HELPER = Path('/usr/local/share/proxmenux/oci/engine/remote/oci_stack_public_routes.py')
CONFIGS = Path('/etc/pve/lxc')
ROOT_UID = 0
PRIVATE = ipaddress.ip_network('10.77.0.0/16')
IP = '/usr/sbin/ip'
NSENTER = '/usr/bin/nsenter'
NS_GET_NSTYPE = 0xb703
CLONE_NEWNET = 0x40000000


class RouteError(ValueError):
    pass


def _vmid(value):
    if type(value) is not int or not 100 <= value < 1000000000:
        raise RouteError('Invalid public route VMID')
    return value


def _identity(value):
    try:
        result = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise RouteError('Invalid public route identity') from error
    if result != value:
        raise RouteError('Invalid public route identity')
    return result


def include_path(vmid):
    return DIRECTORY / f'{_vmid(vmid)}.conf'


def contract_path(vmid):
    return DIRECTORY / f'{_vmid(vmid)}.json'


def _address(value):
    if not isinstance(value, str):
        raise RouteError('Invalid public route address')
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError) as error:
        raise RouteError('Invalid public route address') from error
    if address.is_loopback or address.is_multicast or address.is_unspecified or address.is_link_local:
        raise RouteError('Invalid public route address')
    return address


def validate(deployment, vmid, identity=None):
    spec = deployment.get('stack_public_routes')
    if spec is None:
        return None
    required = {'schema', 'stack_id', 'primary_vmid', 'vmid', 'installation_id',
                'private_bridge', 'private_address', 'routes'}
    if not isinstance(spec, dict) or set(spec) != required or type(spec['schema']) is not int or spec['schema'] != 1:
        raise RouteError('Invalid public route contract')
    if _vmid(spec['vmid']) != _vmid(vmid):
        raise RouteError('Public route owner differs')
    _vmid(spec['primary_vmid'])
    _identity(spec['stack_id'])
    if _identity(spec['installation_id']) != (identity or spec['installation_id']):
        raise RouteError('Public route owner identity differs')
    if not isinstance(spec['private_bridge'], str) or not re.fullmatch(r'vmbr[0-9]+', spec['private_bridge']):
        raise RouteError('Invalid public route bridge')
    if not isinstance(spec['private_address'], str):
        raise RouteError('Invalid public route private address')
    try:
        source = ipaddress.IPv4Interface(spec['private_address'])
    except (ValueError, TypeError) as error:
        raise RouteError('Invalid public route private address') from error
    if source.network.prefixlen != 24 or source.ip not in PRIVATE or source.ip in (source.network.network_address, source.network.broadcast_address):
        raise RouteError('Invalid public route private address')
    routes = spec['routes']
    if not isinstance(routes, list) or not routes or len(routes) > 64:
        raise RouteError('Invalid public route list')
    destinations = set()
    for route in routes:
        if not isinstance(route, dict) or set(route) != {'destination', 'via', 'target_vmid', 'target_installation_id'}:
            raise RouteError('Invalid public route entry')
        destination, via = _address(route['destination']), _address(route['via'])
        if (destination in source.network or destination in destinations or via not in source.network
                or via in (source.ip, source.network.network_address, source.network.broadcast_address)
                or _vmid(route['target_vmid']) == vmid):
            raise RouteError('Invalid public route destination or next hop')
        _identity(route['target_installation_id'])
        destinations.add(destination)
    return copy.deepcopy(spec)


def include_content():
    return f'lxc.hook.start-host = /usr/bin/python3 -I {HELPER} start\n'


def own(line, vmid):
    if isinstance(line, bytes):
        line = line.decode()
    return line.rstrip('\n') == f'lxc.include: {include_path(vmid)}'


def renumber_line(line, old, new):
    binary = isinstance(line, bytes)
    text = line.decode() if binary else line
    if own(text, old):
        text = f'lxc.include: {include_path(new)}' + ('\n' if text.endswith('\n') else '')
    return text.encode() if binary else text


def _read(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022:
        raise RouteError('Unsafe managed public route file')
    if info.st_size > 262144:
        raise RouteError('Managed public route file is too large')
    return path.read_bytes()


def _managed_directory(path, create=False):
    if create:
        path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022:
        raise RouteError('Unsafe managed public route directory')


def _write(path, data, mode=0o600):
    _managed_directory(path.parent, create=True)
    if path.is_symlink():
        raise RouteError('Managed public route path is a symbolic link')
    fd, temporary = tempfile.mkstemp(prefix='.public-routes-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        # pmxcfs supplies the permissions of files below its private directory.
        if Path('/etc/pve') not in path.parents:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(deployment, vmid, identity=None):
    spec = validate(deployment, vmid, identity)
    if spec is None:
        return
    # The installed engine is the authority; upgrades replace it normally.
    _managed_directory(HELPER.parent)
    _read(HELPER)
    _write(contract_path(vmid), (json.dumps(spec, sort_keys=True) + '\n').encode())
    _write(include_path(vmid), include_content().encode())
    return f'lxc.include: {include_path(vmid)}'


restore = install
publish = install


def check(config, deployment, vmid, identity=None, require_host_assets=True):
    spec = validate(deployment, vmid, identity)
    text = config.decode() if isinstance(config, bytes) else config
    includes = [line for line in text.splitlines() if line.startswith('lxc.include: ')
                and str(DIRECTORY) + '/' in line]
    expected = [f'lxc.include: {include_path(vmid)}'] if spec else []
    if includes != expected:
        raise RouteError('Managed public route include differs from the contract')
    if spec and require_host_assets:
        _managed_directory(DIRECTORY)
        _managed_directory(HELPER.parent)
        if _read(include_path(vmid)) != include_content().encode():
            raise RouteError('Managed public route include was changed')
        if json.loads(_read(contract_path(vmid))) != spec:
            raise RouteError('Managed public route contract was changed')
        _read(HELPER)
    return spec


def remove(vmid, identity=None):
    path = contract_path(vmid)
    if not path.exists() and not path.is_symlink():
        if include_path(vmid).exists() or include_path(vmid).is_symlink():
            raise RouteError('Public route include has no ownership contract')
        return False
    _managed_directory(DIRECTORY)
    spec = json.loads(_read(path))
    validate({'stack_public_routes': spec}, vmid, identity)
    include = include_path(vmid)
    if include.exists() or include.is_symlink():
        if _read(include) != include_content().encode():
            raise RouteError('Managed public route include was changed')
        include.unlink()
    path.unlink()
    return True


def _config(vmid):
    text = _read(CONFIGS / f'{_vmid(vmid)}.conf').decode()
    matches = re.findall(r'proxmenux-instance=([0-9a-f-]{36})(?![0-9a-f-])', text)
    if len(set(matches)) != 1:
        raise RouteError('Public route container identity is unknown')
    values = {}
    for line in text.splitlines():
        if line.startswith('#') or ': ' not in line:
            continue
        key, value = line.split(': ', 1)
        if key in ('net0', 'net1'):
            if key in values:
                raise RouteError('Ambiguous public route network')
            parts = [part.split('=', 1) for part in value.split(',') if '=' in part]
            if len({key for key, _ in parts}) != len(parts):
                raise RouteError('Ambiguous public route network')
            values[key] = dict(parts)
    return matches[0], values, text


def live_contract(spec):
    """Validate actual PVE ownership and both ends of every generated route."""
    vmid = spec['vmid']
    identity, networks, text = _config(vmid)
    check(text, {'stack_public_routes': spec}, vmid, identity)
    source = networks.get('net0', {})
    if source.get('bridge') != spec['private_bridge'] or source.get('ip') != spec['private_address'] or source.get('name') != 'eth0':
        raise RouteError('Public route private interface differs')
    primary_identity, primary_networks, _ = _config(spec['primary_vmid'])
    if primary_identity != spec['stack_id'] or primary_networks.get('net0', {}).get('bridge') != spec['private_bridge']:
        raise RouteError('Public route stack ownership differs')
    for route in spec['routes']:
        target_identity, target_networks, _ = _config(route['target_vmid'])
        private, frontend = target_networks.get('net0', {}), target_networks.get('net1', {})
        try:
            private_ip = ipaddress.IPv4Interface(private.get('ip'))
            public_ip = ipaddress.IPv4Interface(frontend.get('ip'))
        except (ValueError, TypeError) as error:
            raise RouteError('Public route target is not a static frontend') from error
        if (target_identity != route['target_installation_id'] or private.get('bridge') != spec['private_bridge']
                or private_ip.network != ipaddress.IPv4Interface(spec['private_address']).network
                or str(private_ip.ip) != route['via'] or str(public_ip.ip) != route['destination']):
            raise RouteError('Public route target ownership or addresses differ')
    mac = source.get('hwaddr', '').lower()
    if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac):
        raise RouteError('Public route private hardware address is unknown')
    return mac


def namespace_fd(path):
    if not isinstance(path, str) or not re.fullmatch(r'/proc/[1-9][0-9]*/(?:fd/[0-9]+|ns/net)', path):
        raise RouteError('LXC did not provide a network namespace')
    fd = os.open(path, os.O_RDONLY)
    try:
        if fcntl.ioctl(fd, NS_GET_NSTYPE) != CLONE_NEWNET:
            raise RouteError('LXC namespace is not a network namespace')
        info, host = os.fstat(fd), os.stat('/proc/self/ns/net')
        if (info.st_dev, info.st_ino) == (host.st_dev, host.st_ino):
            raise RouteError('Refusing to configure the host network namespace')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _namespace_command(fd, *args):
    process = subprocess.run([NSENTER, f'--net=/proc/self/fd/{fd}', '--', IP, *args],
                             pass_fds=(fd,), capture_output=True, check=True, timeout=15)
    return process.stdout


def apply(spec, fd, mac):
    source = ipaddress.IPv4Interface(spec['private_address'])
    interfaces = json.loads(_namespace_command(fd, '-j', 'address', 'show', 'dev', 'eth0'))
    if (len(interfaces) != 1 or interfaces[0].get('address', '').lower() != mac
            or not any(item.get('family') == 'inet' and item.get('local') == str(source.ip)
                       and item.get('prefixlen') == source.network.prefixlen
                       for item in interfaces[0].get('addr_info', []))):
        raise RouteError('Network namespace does not belong to the public route owner')
    for route in spec['routes']:
        _namespace_command(fd, '-4', 'route', 'replace', route['destination'] + '/32',
                           'via', route['via'], 'dev', 'eth0', 'src', str(source.ip))


def start():
    if os.geteuid() != 0:
        raise RouteError('Public routes require root')
    name = os.environ.get('LXC_NAME', '')
    if not re.fullmatch(r'[1-9][0-9]*', name):
        raise RouteError('LXC did not provide its container identity')
    vmid = _vmid(int(name))
    spec = json.loads(_read(contract_path(vmid)))
    validate({'stack_public_routes': spec}, vmid)
    mac = live_contract(spec)
    pid = os.environ.get('LXC_PID', '')
    if not re.fullmatch(r'[1-9][0-9]*', pid):
        raise RouteError('LXC did not provide its init process identity')
    fd = namespace_fd(f'/proc/{pid}/ns/net')
    try:
        apply(spec, fd, mac)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    start_parser = commands.add_parser('start')
    start_parser.add_argument('hook_arguments', nargs='*')
    install_parser = commands.add_parser('install')
    install_parser.add_argument('vmid', type=int)
    install_parser.add_argument('--deployment', required=True)
    install_parser.add_argument('--installation-id', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RouteError('Public routes require root')
    if args.operation == 'start':
        # Proxmox's network scripts use the default LXC version-0 hook ABI.
        expected = [os.environ.get('LXC_NAME', ''), 'lxc', 'start-host']
        if args.hook_arguments != expected:
            raise RouteError('Unexpected public route hook invocation')
        start()
    else:
        line = install(json.loads(Path(args.deployment).read_text()), args.vmid, args.installation_id)
        if line:
            print(line)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        detail = str(error)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            output = error.stderr.decode(errors='replace') if isinstance(error.stderr, bytes) else error.stderr
            detail += ': ' + output.strip()[:1000]
        raise SystemExit('Managed public routes failed: ' + detail)
