"""Read-only OVSDB topology; Linux bridges continue to use their sysfs path.

OVS does not publish Linux bridge brif/master links, and an OVSBond has
no kernel netdev. Read the three OVSDB tables once per short cache window
instead of guessing from names or changing the host's network config.
"""
import json
import shutil
import subprocess
import threading
import time

_CACHE_SECONDS = 15
_lock = threading.Lock()
_cached_at = 0
_cached = {}


def _value(value):
    if isinstance(value, list) and len(value) == 2:
        if value[0] in ('uuid', 'named-uuid'):
            return value[1]
        if value[0] == 'set':
            return [_value(item) for item in value[1]]
    return value


def _rows(table):
    return [{key: _value(value) for key, value in zip(table['headings'], row)}
            for row in table['data']]


def _list(value):
    return value if isinstance(value, list) else [] if value is None or value == '' else [value]


def parse_topology(bridges, ports, interfaces):
    """Normalize OVSDB UUID references, including singleton sets and bonds."""
    iface_by_id = {row['_uuid']: row for row in _rows(interfaces)}
    port_by_id = {row['_uuid']: row for row in _rows(ports)}
    topology = {'types': {}, 'owners': {}, 'bridges': {}, 'bonds': {}, 'ports': {}}
    for bridge in _rows(bridges):
        name = bridge['name']
        topology['types'][name] = 'bridge'
        members = []
        for port_id in _list(bridge.get('ports')):
            port = port_by_id.get(port_id)
            if not port:
                continue
            port_name = port['name']
            ifaces = [iface_by_id[i] for i in _list(port.get('interfaces')) if i in iface_by_id]
            # The bridge's own internal port is not a downstream member.
            if port_name == name:
                continue
            members.append(port_name)
            detail = {'bridge_owner': name, 'network_backend': 'ovs',
                      'ovs_tag': next(iter(_list(port.get('tag'))), None),
                      'ovs_trunks': _list(port.get('trunks'))}
            topology['ports'][port_name] = detail
            topology['owners'][port_name] = name
            is_bond = len(ifaces) > 1
            if is_bond:
                topology['types'][port_name] = 'bond'
                mode = port.get('bond_mode') or 'balance-slb'
                topology['bonds'][port_name] = {
                    'bond_mode': mode, 'bond_slaves': [i['name'] for i in ifaces],
                    # OVSDB alone does not tell us which slave is active.
                    'bond_active_slave': None, 'bond_supports_failover': False,
                    'bond_slave_status': {}, **detail}
            for iface in ifaces:
                iface_name = iface['name']
                topology['owners'][iface_name] = name
                topology['ports'][iface_name] = detail
                if is_bond:
                    topology['ports'][iface_name] = {**detail, 'bond_master': port_name,
                                                    'bond_role': 'member'}
                elif iface.get('type') == 'internal' and not iface_name.startswith(('fwpr', 'fwln')):
                    topology['types'][iface_name] = 'vlan'
        topology['bridges'][name] = members
    return topology


def get_topology():
    """Bounded, cached reads; missing OVS or an unavailable daemon is harmless."""
    global _cached_at, _cached
    with _lock:
        now = time.monotonic()
        if now - _cached_at < _CACHE_SECONDS:
            return _cached
        binary = shutil.which('ovs-vsctl')
        result = {}
        if binary:
            try:
                tables = []
                for table, columns in (
                    ('Bridge', '_uuid,name,ports'),
                    ('Port', '_uuid,name,interfaces,bond_mode,tag,trunks'),
                    ('Interface', '_uuid,name,type'),
                ):
                    proc = subprocess.run(
                        [binary, '--timeout=1', '--format=json', f'--columns={columns}', 'list', table],
                        capture_output=True, text=True, timeout=2, check=True)
                    tables.append(json.loads(proc.stdout))
                result = parse_topology(*tables)
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
                # Do not keep stale ownership when OVS disappears or is reconfigured.
                result = {}
        _cached, _cached_at = result, now
        return _cached
