"""OVSDB fixtures exercise live ownership, UUID sets, bonds and API output."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import types
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ovs_topology_test', SCRIPTS / 'ovs_topology.py')
ovs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ovs)


def uuid(name):
    return ['uuid', name]


def refs(*names):
    return ['set', [uuid(name) for name in names]]


def table(headings, *rows):
    return {'headings': headings.split(','), 'data': list(rows)}


def fixture():
    # Mixed Linux/OVS host, named bond without a kernel netdev, tagged
    # internal port, direct guest and guest behind a Proxmox firewall.
    return (
        table('_uuid,name,ports', ['b1', 'switch0', refs('p0', 'p1', 'p2', 'p3', 'p4', 'p5')]),
        table('_uuid,name,interfaces,bond_mode,tag,trunks',
              ['p0', 'switch0', uuid('i0'), '', ['set', []], ['set', []]],
              ['p1', 'eno1', uuid('i1'), '', ['set', []], ['set', [10, 20]]],
              ['p2', 'uplink', refs('i2', 'i3'), 'balance-tcp', ['set', []], ['set', []]],
              ['p3', 'vlan100', uuid('i4'), '', 100, ['set', []]],
              ['p4', 'tap103i0', uuid('i5'), '', 100, ['set', []]],
              ['p5', 'fwpr115p0', uuid('i6'), '', 10, ['set', []]]),
        table('_uuid,name,type', ['i0', 'switch0', 'internal'], ['i1', 'eno1', ''],
              ['i2', 'eno2', ''], ['i3', 'eno3', ''], ['i4', 'vlan100', 'internal'],
              ['i5', 'tap103i0', ''], ['i6', 'fwpr115p0', 'internal']))


class OvsTopology(unittest.TestCase):
    def setUp(self):
        ovs._cached_at = 0
        ovs._cached = {}
        self.addCleanup(setattr, ovs, '_cached_at', 0)
        self.addCleanup(setattr, ovs, '_cached', {})

    def test_ovsdb_singletons_bonds_tags_and_internal_ports(self):
        data = ovs.parse_topology(*fixture())
        self.assertEqual(data['types']['switch0'], 'bridge')
        self.assertEqual(data['types']['vlan100'], 'vlan')
        self.assertNotIn('switch0', data['bridges']['switch0'])
        self.assertEqual(data['owners']['tap103i0'], 'switch0')
        self.assertEqual(data['ports']['vlan100']['ovs_tag'], 100)
        self.assertEqual(data['ports']['eno1']['ovs_trunks'], [10, 20])
        self.assertEqual(data['bonds']['uplink']['bond_slaves'], ['eno2', 'eno3'])
        self.assertIsNone(data['bonds']['uplink']['bond_active_slave'])
        self.assertEqual(data['ports']['eno2']['bond_master'], 'uplink')

    def test_zero_vlan_tag_is_preserved(self):
        tables = fixture()
        tables[1]['data'][3][4] = 0
        self.assertEqual(ovs.parse_topology(*tables)['ports']['vlan100']['ovs_tag'], 0)

    def test_no_ovs_does_not_spawn_any_process(self):
        with patch.object(ovs.shutil, 'which', return_value=None), patch.object(ovs.subprocess, 'run') as run:
            self.assertEqual(ovs.get_topology(), {})
            run.assert_not_called()

    def test_read_only_queries_cached_and_failure_drops_stale_topology(self):
        replies = [types.SimpleNamespace(stdout=json.dumps(t)) for t in fixture()]
        with patch.object(ovs.shutil, 'which', return_value='/usr/bin/ovs-vsctl'), \
             patch.object(ovs.subprocess, 'run', side_effect=replies) as run:
            first = ovs.get_topology()
            self.assertEqual(ovs.get_topology(), first)
            self.assertEqual(run.call_count, 3)
            for call in run.call_args_list:
                self.assertEqual(call.args[0][-2], 'list')
                self.assertIn('--timeout=1', call.args[0])
        ovs._cached_at = 0
        with patch.object(ovs.shutil, 'which', return_value='/usr/bin/ovs-vsctl'), \
             patch.object(ovs.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ovs-vsctl', 2)):
            self.assertEqual(ovs.get_topology(), {})

    def test_malformed_or_reconfigured_database_is_harmless(self):
        for payload in ('not-json', '{}', '{"headings": [], "data": [[]]}'):
            ovs._cached_at = 0
            with patch.object(ovs.shutil, 'which', return_value='/usr/bin/ovs-vsctl'), \
                 patch.object(ovs.subprocess, 'run', return_value=types.SimpleNamespace(stdout=payload)):
                self.assertEqual(ovs.get_topology(), {})

    def api_namespace(self):
        names = {'get_network_info', 'get_interface_type', '_resolve_bridge_owner'}
        tree = ast.parse((SCRIPTS / 'flask_server.py').read_text())
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        data = ovs.parse_topology(*fixture())
        names = ['eno1', 'eno2', 'eno3', 'switch0', 'vlan100', 'tap103i0', 'tap115i0', 'vmbr1']
        stats = {name: types.SimpleNamespace(isup=True, speed=1000, duplex=2, mtu=1500) for name in names}
        counter = types.SimpleNamespace(bytes_sent=1000, bytes_recv=2000, packets_sent=10, packets_recv=20,
                                        errin=0, errout=0, dropin=0, dropout=0)
        ns = {'os': os, 'socket': socket,
              'ovs_topology': types.SimpleNamespace(get_topology=lambda: data),
              'get_proxmox_node_name': lambda: 'pve', 'get_vm_lxc_names': lambda: {},
              'psutil': types.SimpleNamespace(net_if_addrs=lambda: dict.fromkeys(names, []),
                                             net_if_stats=lambda: stats,
                                             net_io_counters=lambda **kw: dict.fromkeys(names, counter) if kw else counter),
              '_ensure_net_rate_sampler': lambda: None, '_compute_per_nic_rates_live': lambda _: {},
              '_is_bond_master': lambda _: False, '_is_physical_dev': lambda name: name.startswith('eno'),
              '_ethtool_max_speed': lambda _: 1000,
              '_iface_master': lambda name: {'tap115i0': 'fwbr115i0', 'fwpr115p0': 'ovs-system'}.get(name),
              'extract_vmid_from_interface': lambda name: (103 if '103' in name else 115, 'vm'),
              'get_bridge_info': lambda _: {'members': [], 'physical_interface': None,
                                             'physical_duplex': 'unknown', 'bond_slaves': []}}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'flask_server.py', 'exec'), ns)
        return ns

    def test_api_preserves_linux_bridge_and_assigns_ovs_guests_and_bond(self):
        ns = self.api_namespace()
        with patch('os.path.exists', return_value=True):
            result = ns['get_network_info']()
        self.assertNotIn('error', result)
        self.assertEqual({i['name'] for i in result['bridge_interfaces']}, {'switch0', 'vmbr1'})
        self.assertEqual(result['bond_interfaces'][0]['name'], 'uplink')
        self.assertEqual(result['bond_interfaces'][0]['speed'], 0)
        self.assertIsNone(result['bond_interfaces'][0]['mac_address'])
        self.assertIn('uplink', {i['name'] for i in result['interfaces']})
        for guest in result['vm_lxc_interfaces']:
            self.assertEqual(guest['bridge_owner'], 'switch0')
        self.assertEqual(next(i for i in result['interfaces'] if i['name'] == 'vlan100')['ovs_tag'], 100)
        for nic in result['physical_interfaces']:
            self.assertIn('switch0', nic['used_by_bridges'])

    def test_packaged_module_is_shipped_with_backend(self):
        self.assertIn('cp "$SCRIPT_DIR/ovs_topology.py" "$APP_DIR/usr/bin/"',
                      (SCRIPTS / 'build_appimage.sh').read_text())


if __name__ == '__main__':
    unittest.main()
