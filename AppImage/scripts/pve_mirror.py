"""Read Proxmox VE's own status files instead of running its CLI tools.

pvestatd publishes node, guest and storage status in pmxcfs every few
seconds, and `pvesh get /cluster/resources` is built from that same data.
Reading it from /etc/pve costs a file read instead of a Perl process.

Every reader returns None when /etc/pve is not mounted, a file is missing
or a line is not in a known format, so callers keep their pvesh/qm/pct
call for that case. Nothing here writes anything.
"""

import json
import os
import re
import sys

PVE_DIR = '/etc/pve'
PROC_DIR = '/proc'
QEMU_RUN_DIR = '/var/run/qemu-server'

GUEST_TYPES = ('qemu', 'lxc')

# Storage types PVE::Storage registers itself. A section of any other type
# (a third-party plugin, or a type this PVE release dropped) is answered by
# pvesh only, which knows whether the plugin is loaded.
BUILTIN_STORAGE_TYPES = frozenset({
    'dir', 'lvm', 'lvmthin', 'nfs', 'cifs', 'iscsi', 'rbd', 'cephfs',
    'iscsidirect', 'zfspool', 'zfs', 'pbs', 'btrfs', 'esxi',
})

_NUMBER = re.compile(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?')
_SECTION_HEADER = re.compile(r'^(\S+):\s*(\S+)\s*$')
_SECTION_PROPERTY = re.compile(r'^\s+(\S+)(?:\s+(.*\S))?\s*$')


class MirrorError(Exception):
    """The data is not in a shape this module can answer exactly."""


def _path(*parts):
    return os.path.join(PVE_DIR, *parts)


def _read_text(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        return handle.read()


def _is_pbs_host():
    pbs_manager = sys.modules.get('pbs_manager')
    if pbs_manager is None:
        return False
    try:
        return bool(pbs_manager.is_pbs_host())
    except Exception:
        return True


def available():
    """True when pmxcfs is mounted and publishes the status files."""
    if not all(os.path.isfile(_path(name)) for name in ('.members', '.vmlist', '.rrd')):
        return False
    return not _is_pbs_host()


def perl_number(value):
    """`($value || 0) + 0` as PVE::API2Tools does, with Perl's JSON output."""
    if value is None or value == '' or value == '0':
        return 0
    match = _NUMBER.match(value.lstrip())
    if not match or match.end() != len(value.lstrip()):
        raise MirrorError(f'not a number: {value!r}')
    text = match.group(0)
    if re.fullmatch(r'[+-]?\d+', text):
        return int(text)
    number = float(text)
    if number.is_integer() and abs(number) < 2 ** 53:
        return int(number)
    return number


def parse_rrd(text):
    """Parse the `.rrd` dump the way PVE::Cluster::rrd_dump does."""
    result = {}
    for line in text.split('\n'):
        fields = line.split(':')
        # Perl's split drops trailing empty fields.
        while fields and fields[-1] == '':
            fields.pop()
        if not fields or not fields[0]:
            continue
        key, values = fields[0], fields[1:]
        if len(values) <= 1:
            continue
        result[key] = [None if item == 'U' else item for item in values]
    return result


def read_rrd():
    try:
        return parse_rrd(_read_text(_path('.rrd')))
    except OSError:
        return None


def rrd_key(rrd, kind, ident):
    """PVE::API2Tools::get_rrd_key: the PVE 9 key first, then the older one."""
    key = f'pve-{kind}-9.0/{ident}'
    if key in rrd:
        return key
    old = f'pve2.3-vm/{ident}' if kind == 'vm' else f'pve2-{kind}/{ident}'
    if old in rrd:
        return old
    return None


def _known_rrd_prefixes(rrd):
    for key in rrd:
        prefix = key.split('/', 1)[0]
        if prefix not in ('pve-vm-9.0', 'pve2.3-vm', 'pve-node-9.0', 'pve2-node',
                          'pve-storage-9.0', 'pve2-storage'):
            # Other publishers (e.g. SDN, external metrics) are harmless;
            # only a new guest, node or storage format is a problem.
            if re.match(r'^pve[\d.-]*-?(vm|node|storage)', prefix):
                raise MirrorError(f'unknown status format {prefix}')


def _field(values, index):
    return values[index] if index < len(values) else None


def vm_stats(vmid, entry, rrd):
    """PVE::API2Tools::extract_vm_stats for one guest of `.vmlist`."""
    stats = {
        'id': f"{entry['type']}/{vmid}",
        'vmid': int(vmid),
        'node': entry['node'],
        'type': entry['type'],
        'status': 'unknown',
    }
    key = rrd_key(rrd, 'vm', vmid)
    if key is None:
        return stats
    values = rrd[key]
    stats['uptime'] = perl_number(_field(values, 0))
    stats['name'] = _field(values, 1)
    stats['status'] = _field(values, 2)
    stats['template'] = perl_number(_field(values, 3))
    for index, name in enumerate(('maxcpu', 'cpu', 'maxmem', 'mem', 'maxdisk', 'disk',
                                  'netin', 'netout', 'diskread', 'diskwrite'), start=5):
        stats[name] = perl_number(_field(values, index))
    if key.startswith('pve-vm-'):
        stats['memhost'] = perl_number(_field(values, 15))
    return stats


def read_json(name):
    try:
        data = json.loads(_read_text(_path(name)))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_vmlist():
    """Guest id -> {'node', 'type'} from `.vmlist`."""
    data = read_json('.vmlist')
    if data is None or not isinstance(data.get('ids'), dict):
        return None
    guests = {}
    for vmid, entry in data['ids'].items():
        if not str(vmid).isdigit() or not isinstance(entry, dict):
            return None
        if entry.get('type') not in GUEST_TYPES or not isinstance(entry.get('node'), str):
            return None
        guests[str(vmid)] = {'node': entry['node'], 'type': entry['type']}
    return guests


def read_members():
    """`.members`: the local node name and, in a cluster, every node."""
    data = read_json('.members')
    if data is None or not isinstance(data.get('nodename'), str) or not data['nodename']:
        return None
    nodelist = data.get('nodelist')
    if nodelist is not None and not isinstance(nodelist, dict):
        return None
    return {'nodename': data['nodename'], 'nodelist': nodelist}


def node_names(members):
    """PVE::Cluster::get_nodelist."""
    nodelist = members.get('nodelist')
    if not nodelist or members['nodename'] not in nodelist:
        return [members['nodename']]
    return list(nodelist)


def local_node():
    members = read_members() if available() else None
    return members['nodename'] if members else None


def guest_config_path(node, vm_type, vmid):
    folder = 'qemu-server' if vm_type == 'qemu' else 'lxc'
    return _path('nodes', node, folder, f'{int(vmid)}.conf')


def read_guest_config(node, vm_type, vmid):
    """Raw text of a guest config, or None when it does not exist."""
    try:
        return _read_text(guest_config_path(node, vm_type, vmid))
    except FileNotFoundError:
        return None


def config_properties(text, names):
    """Top-level `key: value` pairs of a guest config, as pmxcfs reads them.

    Stops at the first snapshot or pending section; values keep everything
    after the colon except surrounding whitespace.
    """
    wanted = set(names)
    found = {}
    for line in text.split('\n'):
        if line.startswith('['):
            break
        key, sep, value = line.partition(':')
        if sep and key in wanted and key not in found:
            found[key] = value.strip()
    return found


def agent_enabled(value):
    """Whether a qemu-server `agent:` option enables the guest agent."""
    if not value:
        return False
    enabled = None
    for part in str(value).split(','):
        key, sep, item = part.partition('=')
        if not sep:
            enabled = key
        elif key.strip() == 'enabled':
            enabled = item
    return str(enabled or '').strip().lower() in ('1', 'on', 'yes', 'true')


def cluster_resources_vm():
    """`pvesh get /cluster/resources --type vm` without pool and hastate."""
    if not available():
        return None
    guests = read_vmlist()
    rrd = read_rrd()
    if guests is None or rrd is None:
        return None
    try:
        _known_rrd_prefixes(rrd)
        resources = []
        for vmid in sorted(guests):
            entry = guests[vmid]
            stats = vm_stats(vmid, entry, rrd)
            text = read_guest_config(entry['node'], entry['type'], vmid)
            if text is not None:
                stats.update(config_properties(text, ('lock', 'tags')))
            resources.append(stats)
        return resources
    except (MirrorError, OSError, ValueError):
        return None


def parse_storage_config(text):
    """Sections of storage.cfg as ordered (storage id, type, options) tuples."""
    sections = []
    current = None
    for line in text.split('\n'):
        if not line.strip():
            current = None
            continue
        if line.lstrip().startswith('#'):
            continue
        header = _SECTION_HEADER.match(line)
        if header and not line[0].isspace():
            current = {}
            sections.append((header.group(2), header.group(1), current))
            continue
        option = _SECTION_PROPERTY.match(line)
        if option is None or current is None:
            raise MirrorError(f'unexpected storage.cfg line: {line!r}')
        name, value = option.group(1), option.group(2)
        current[name] = '1' if value is None else value
    ids = [section[0] for section in sections]
    if len(ids) != len(set(ids)):
        raise MirrorError('duplicate storage id')
    for _storage, storage_type, _options in sections:
        if storage_type not in BUILTIN_STORAGE_TYPES:
            raise MirrorError(f'storage type {storage_type} needs its plugin')
    local = next((section for section in sections if section[0] == 'local'), None)
    if local is None or local[1] != 'dir' or local[2].get('path', '/var/lib/vz') != '/var/lib/vz':
        # PVE::Storage::Plugin replaces such a `local` with its own default.
        raise MirrorError('storage.cfg has no default local storage')
    return sections


def _storage_enabled_on(storage, options, node):
    """PVE::Storage::storage_check_enabled."""
    if options.get('disable', '0') not in ('0', ''):
        return False
    if storage == 'local' or 'nodes' not in options:
        return True
    return node in [item.strip() for item in options['nodes'].split(',')]


def read_storage_config():
    try:
        return parse_storage_config(_read_text(_path('storage.cfg')))
    except (OSError, MirrorError):
        return None


def storage_list():
    """The fields of `pvesh get /storage` the Monitor reads.

    Each row has storage, type, content and, when set, path, nodes and
    disable. PVE prints content in no fixed order; it is kept as written.
    Returns None when a section leaves its content to the plugin default.
    """
    if not available():
        return None
    sections = read_storage_config()
    if sections is None:
        return None
    rows = []
    for storage, storage_type, options in sections:
        if 'content' not in options:
            return None
        content = []
        for item in options['content'].split(','):
            if item.strip() and item.strip() not in content:
                content.append(item.strip())
        row = {'storage': storage, 'type': storage_type, 'content': ','.join(content)}
        if options.get('path'):
            row['path'] = options['path']
        if options.get('nodes') and storage != 'local':
            row['nodes'] = options['nodes']
        if options.get('disable', '0') not in ('0', ''):
            row['disable'] = 1
        rows.append(row)
    return rows


def cluster_resources_storage():
    """`pvesh get /cluster/resources --type storage` without content and shared."""
    if not available():
        return None
    members = read_members()
    sections = read_storage_config()
    rrd = read_rrd()
    if members is None or sections is None or rrd is None:
        return None
    try:
        _known_rrd_prefixes(rrd)
        resources = []
        nodes = node_names(members)
        for storage, storage_type, options in sections:
            for node in nodes:
                if not _storage_enabled_on(storage, options, node):
                    continue
                entry = {
                    'id': f'storage/{node}/{storage}',
                    'storage': storage,
                    'node': node,
                    'type': 'storage',
                    'plugintype': storage_type,
                    'status': 'unknown',
                }
                key = rrd_key(rrd, 'storage', f'{node}/{storage}')
                if key is not None:
                    values = rrd[key]
                    entry['maxdisk'] = perl_number(_field(values, 1))
                    entry['disk'] = perl_number(_field(values, 2))
                    entry['status'] = 'available'
                resources.append(entry)
        return resources
    except (MirrorError, ValueError):
        return None


def _online_members(members):
    """PVE::Cluster::get_members: a single host counts as its own online member."""
    nodelist = members.get('nodelist')
    if not nodelist or members['nodename'] not in nodelist:
        return {members['nodename']: True}
    return {name: isinstance(entry, dict) and bool(entry.get('online'))
            for name, entry in nodelist.items()}


def cluster_resources_node():
    """`pvesh get /cluster/resources --type node` without cgroup-mode."""
    if not available():
        return None
    members = read_members()
    rrd = read_rrd()
    if members is None or rrd is None:
        return None
    online = _online_members(members)
    try:
        _known_rrd_prefixes(rrd)
        resources = []
        for node in node_names(members):
            entry = {'id': f'node/{node}', 'node': node, 'type': 'node', 'status': 'unknown'}
            key = rrd_key(rrd, 'node', node)
            if key is not None:
                values = rrd[key]
                if online.get(node):
                    entry['uptime'] = perl_number(_field(values, 0))
                    entry['cpu'] = perl_number(_field(values, 5))
                    entry['mem'] = perl_number(_field(values, 8))
                    entry['disk'] = perl_number(_field(values, 12))
                    entry['level'] = _field(values, 1)
                    entry['status'] = 'online'
                entry['maxcpu'] = perl_number(_field(values, 4)) or 1
                entry['maxmem'] = perl_number(_field(values, 7))
                entry['maxdisk'] = perl_number(_field(values, 11))
            if online.get(node) is False:
                entry['status'] = 'offline'
            resources.append(entry)
        return resources
    except (MirrorError, ValueError):
        return None


def cluster_status():
    """`pvesh get /cluster/status` from `.members`, without the subscription level.

    A single host is one local, online node with no cluster entry, as PVE
    answers it.
    """
    if not available():
        return None
    data = read_json('.members')
    members = read_members()
    if data is None or members is None:
        return None
    nodename = members['nodename']
    nodelist = members.get('nodelist')
    if not nodelist or nodename not in nodelist:
        return [{'type': 'node', 'id': f'node/{nodename}', 'name': nodename,
                 'nodeid': 0, 'local': 1, 'online': 1}]
    rows = []
    cluster = data.get('cluster')
    if isinstance(cluster, dict):
        rows.append({'type': 'cluster', 'id': 'cluster', 'name': cluster.get('name'),
                     'version': cluster.get('version'), 'nodes': cluster.get('nodes'),
                     'quorate': cluster.get('quorate')})
    for name, entry in nodelist.items():
        if not isinstance(entry, dict):
            return None
        rows.append({'type': 'node', 'id': f'node/{name}', 'name': name,
                     'nodeid': entry.get('id'), 'ip': entry.get('ip'),
                     'online': 1 if entry.get('online') else 0,
                     'local': 1 if name == nodename else 0})
    return rows


def cluster_nodes():
    """Other members of the cluster as (name, ip, online) from `.members`.

    Same nodes `pvesh get /cluster/status` lists with `local: 0`; an empty
    list on a single host.
    """
    if not available():
        return None
    members = read_members()
    if members is None:
        return None
    nodes = []
    for name, entry in (members.get('nodelist') or {}).items():
        if name == members['nodename'] or not isinstance(entry, dict):
            continue
        nodes.append({'name': name, 'ip': entry.get('ip'), 'online': entry.get('online')})
    return nodes


def qemu_running(vmid):
    """PVE::QemuServer::Helpers::vm_running_locally."""
    pidfile = os.path.join(QEMU_RUN_DIR, f'{int(vmid)}.pid')
    try:
        line = _read_text(pidfile).split('\n', 1)[0]
    except OSError:
        return False
    if not line.isdigit():
        return False
    try:
        with open(os.path.join(PROC_DIR, line, 'cmdline'), 'rb') as handle:
            argv = handle.read().split(b'\0')
        with open(os.path.join(PROC_DIR, line, 'stat'), 'rb') as handle:
            stat = handle.read()
    except OSError:
        return False
    try:
        index = argv.index(b'-pidfile')
    except ValueError:
        return False
    if index + 1 >= len(argv) or argv[index + 1].decode(errors='replace') != pidfile:
        return False
    state = stat.rsplit(b')', 1)[-1].split()
    return bool(state) and state[0] != b'Z'


def running_containers():
    """PVE::LXC::list_active_containers: ids with a live LXC command socket."""
    try:
        text = _read_text(os.path.join(PROC_DIR, 'net', 'unix'))
    except OSError:
        return None
    found = set()
    for match in re.finditer(r'@/var/lib/lxc/(\d+)/command$', text, re.M):
        found.add(match.group(1))
    return found


def local_guest_status(vmid):
    """What `qm status` / `pct status` answer for a guest of this node.

    Returns {'type': 'qemu'|'lxc', 'status': 'running'|'stopped'}, an empty
    dict when the guest has no config on this node, or None when the
    mirror cannot answer.
    """
    try:
        vmid = str(int(vmid))
    except (TypeError, ValueError):
        return None
    node = local_node()
    if node is None:
        return None
    for vm_type in GUEST_TYPES:
        if os.path.isfile(guest_config_path(node, vm_type, vmid)):
            if vm_type == 'qemu':
                running = qemu_running(vmid)
            else:
                active = running_containers()
                if active is None:
                    return None
                running = vmid in active
            return {'type': vm_type, 'status': 'running' if running else 'stopped'}
    return {}
