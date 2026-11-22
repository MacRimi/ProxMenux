"""Readers of Proxmox VE's status files, checked against fixed PVE 8 and 9 data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pve_mirror  # noqa: E402


# Lines as pvestatd writes them on PVE 9 (pve-*-9.0) and PVE 8 (pve2*).
RRD_PVE9 = """\
pve-vm-9.0/131:1111752:pbs-lab:running:0:1795290352:2:0.0191:4294967296:2002714624:34359738368:0:2684665593:1535187842:1756802758:20200038400:2485104640:0:0:0:0:0:0
pve-vm-9.0/104:166277:adguard-home:running:0:1795290722:2:9.92760592069421e-05:1073741824:56897536:8350298112:46592000:205202984:10714250:134184960:41140224:U:0.00:0.00:0.00:0.00:0.00:0.00
pve-vm-9.0/135:0:pyroscope:stopped:0:1795290722:2:U:1073741824:U:8589934592:0:U:U:U:U:U:U:U:U:U:U:U
pve-node-9.0/amd:1286709::1795290722:0.15:16:0.0120177863237592:6.00889316187958e-05:16110796800:6330769408:8589930496:552013824:100861726720:64159633408:38622712397:5786326750:9780027392:3840:0.00:0.00:0.00:0.00:0.00
pve-storage-9.0/amd/local:1795290722:100861726720:64159633408
pve-storage-9.0/amd/local-lvm:1795290722:876395626496:139697462863
"""

RRD_PVE8 = """\
pve2.3-vm/100:5000:web:running:0:1700000000:4:0.25:2147483648:1073741824:8589934592:4294967296:1000:2000:3000:4000
pve2.3-vm/101:0:db:stopped:1:1700000000:2:U:1073741824:U:8589934592:0:U:U:U:U
pve2.3-vm/102:0:old:stopped:0:1700000000:2::1073741824::8589934592:0::::
pve2-node/pve1:3600::1700000000:0.5:8:0.1:0:8000000000:4000000000:0:0:50000000000:10000000000:1:2
pve2-storage/pve1/local:1700000000:50000000000:10000000000
"""

STORAGE_CFG = """\
dir: local
\tpath /var/lib/vz
\tcontent vztmpl,iso,backup

lvmthin: local-lvm
\tthinpool data
\tvgname pve
\tcontent rootdir,images

# a comment
nfs: shared
\texport /export
\tpath /mnt/pve/shared
\tserver 10.0.0.15
\tcontent images
\tnodes pve2

pbs: offsite
\tdatastore store1
\tserver 10.0.0.49
\tcontent backup
\tdisable
"""


class MirrorFixture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.pve = self.root / 'pve'
        self.proc = self.root / 'proc'
        self.run = self.root / 'run'
        for path in (self.pve, self.proc / 'net', self.run):
            path.mkdir(parents=True)
        (self.proc / 'net' / 'unix').write_text('Num RefCount Protocol Flags Type St Inode Path\n')
        for name, value in (('PVE_DIR', str(self.pve)), ('PROC_DIR', str(self.proc)),
                            ('QEMU_RUN_DIR', str(self.run))):
            patch = mock.patch.object(pve_mirror, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, relative, text):
        path = self.pve / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def host(self, rrd, guests, nodename='amd', nodelist=None):
        members = {'nodename': nodename, 'version': 1}
        if nodelist is not None:
            members['nodelist'] = nodelist
        self.write('.members', json.dumps(members))
        self.write('.vmlist', json.dumps({'version': 1, 'ids': guests}))
        self.write('.rrd', rrd)
        self.write('storage.cfg', STORAGE_CFG)


class ParsingTests(MirrorFixture):
    def test_rrd_dump_follows_perl_split(self):
        rrd = pve_mirror.parse_rrd('a/1:x::y::\nb/2:only\n:no-key:1\n\nc/3:1:U\n')
        self.assertEqual(rrd, {'a/1': ['x', '', 'y'], 'c/3': ['1', None]})

    def test_numbers_match_perl_json_output(self):
        number = pve_mirror.perl_number
        self.assertEqual([number(None), number(''), number('0'), number('0.00')], [0, 0, 0, 0])
        self.assertEqual(number('4294967296'), 4294967296)
        self.assertIsInstance(number('3.0'), int)
        self.assertEqual(number('9.92760592069421e-05'), 9.92760592069421e-05)
        self.assertEqual(number('0.0191'), 0.0191)
        self.assertIsInstance(number('1e+20'), float)
        with self.assertRaises(pve_mirror.MirrorError):
            number('12abc')

    def test_pve9_guest_rows(self):
        self.host(RRD_PVE9, {'131': {'node': 'amd', 'type': 'qemu'},
                             '104': {'node': 'amd', 'type': 'lxc'},
                             '135': {'node': 'amd', 'type': 'lxc'}})
        self.write('nodes/amd/qemu-server/131.conf',
                   'agent: 1\ntags: proxmenux-test\nlock: backup\n\n[snap]\ntags: old\n')
        self.write('nodes/amd/lxc/104.conf', '#note\ntags:  a;b  \n')
        rows = pve_mirror.cluster_resources_vm()
        self.assertEqual([row['id'] for row in rows], ['lxc/104', 'qemu/131', 'lxc/135'])
        vm = rows[1]
        self.assertEqual(vm, {
            'id': 'qemu/131', 'vmid': 131, 'node': 'amd', 'type': 'qemu', 'status': 'running',
            'uptime': 1111752, 'name': 'pbs-lab', 'template': 0, 'maxcpu': 2, 'cpu': 0.0191,
            'maxmem': 4294967296, 'mem': 2002714624, 'maxdisk': 34359738368, 'disk': 0,
            'netin': 2684665593, 'netout': 1535187842, 'diskread': 1756802758,
            'diskwrite': 20200038400, 'memhost': 2485104640,
            'tags': 'proxmenux-test', 'lock': 'backup',
        })
        self.assertEqual(rows[0]['tags'], 'a;b')
        self.assertEqual(rows[0]['memhost'], 0)
        stopped = rows[2]
        self.assertEqual((stopped['status'], stopped['cpu'], stopped['mem'], stopped['maxmem']),
                         ('stopped', 0, 0, 1073741824))
        self.assertNotIn('tags', stopped)

    def test_pve8_guest_rows(self):
        self.host(RRD_PVE8, {'100': {'node': 'pve1', 'type': 'qemu'},
                             '101': {'node': 'pve1', 'type': 'lxc'},
                             '102': {'node': 'pve1', 'type': 'qemu'}}, nodename='pve1')
        rows = {row['vmid']: row for row in pve_mirror.cluster_resources_vm()}
        self.assertEqual(rows[100], {
            'id': 'qemu/100', 'vmid': 100, 'node': 'pve1', 'type': 'qemu', 'status': 'running',
            'uptime': 5000, 'name': 'web', 'template': 0, 'maxcpu': 4, 'cpu': 0.25,
            'maxmem': 2147483648, 'mem': 1073741824, 'maxdisk': 8589934592, 'disk': 4294967296,
            'netin': 1000, 'netout': 2000, 'diskread': 3000, 'diskwrite': 4000,
        })
        self.assertEqual((rows[101]['template'], rows[101]['status']), (1, 'stopped'))
        self.assertEqual((rows[102]['cpu'], rows[102]['diskwrite']), (0, 0))

    def test_guest_without_status_line_and_vm_ordering(self):
        self.host('', {'1000': {'node': 'amd', 'type': 'qemu'}, '101': {'node': 'amd', 'type': 'lxc'}})
        rows = pve_mirror.cluster_resources_vm()
        self.assertEqual([row['vmid'] for row in rows], [1000, 101])
        self.assertEqual(rows[0], {'id': 'qemu/1000', 'vmid': 1000, 'node': 'amd',
                                   'type': 'qemu', 'status': 'unknown'})

    def test_unknown_status_format_falls_back(self):
        self.host('pve-vm-10.0/100:1:x:running\n', {'100': {'node': 'amd', 'type': 'qemu'}})
        self.assertIsNone(pve_mirror.cluster_resources_vm())
        self.assertIsNone(pve_mirror.cluster_resources_storage())

    def test_unmounted_or_unreadable_files_fall_back(self):
        self.assertFalse(pve_mirror.available())
        self.assertIsNone(pve_mirror.cluster_resources_vm())
        self.assertIsNone(pve_mirror.cluster_nodes())
        self.assertIsNone(pve_mirror.local_guest_status(100))
        self.host(RRD_PVE9, {'100': {'node': 'amd', 'type': 'openvz'}})
        self.assertIsNone(pve_mirror.cluster_resources_vm())
        self.write('.vmlist', '{broken')
        self.assertIsNone(pve_mirror.cluster_resources_vm())

    def test_a_cluster_without_guests_has_an_empty_list(self):
        # pmxcfs writes only the version while there are no guests.
        self.host(RRD_PVE9, {})
        self.write('.vmlist', json.dumps({'version': 3}))
        self.assertEqual(pve_mirror.read_vmlist(), {})
        self.assertEqual(pve_mirror.cluster_resources_vm(), [])
        self.write('.vmlist', json.dumps({'version': 3, 'ids': []}))
        self.assertIsNone(pve_mirror.read_vmlist())

    def test_backup_server_host_never_uses_the_mirror(self):
        self.host(RRD_PVE9, {})
        pbs = mock.Mock(is_pbs_host=mock.Mock(return_value=True))
        with mock.patch.dict(sys.modules, {'pbs_manager': pbs}):
            self.assertFalse(pve_mirror.available())
            self.assertIsNone(pve_mirror.cluster_resources_vm())


class StorageTests(MirrorFixture):
    def test_storage_rows_per_node_pve9(self):
        self.host(RRD_PVE9, {}, nodelist={'amd': {'id': 1, 'online': 1, 'ip': '10.0.0.55'},
                                          'pve2': {'id': 2, 'online': 0, 'ip': '10.0.0.56'}})
        rows = {row['id']: row for row in pve_mirror.cluster_resources_storage()}
        self.assertEqual(sorted(rows), ['storage/amd/local', 'storage/amd/local-lvm',
                                        'storage/pve2/local', 'storage/pve2/local-lvm',
                                        'storage/pve2/shared'])
        self.assertEqual(rows['storage/amd/local'], {
            'id': 'storage/amd/local', 'storage': 'local', 'node': 'amd', 'type': 'storage',
            'plugintype': 'dir', 'status': 'available', 'maxdisk': 100861726720, 'disk': 64159633408,
        })
        self.assertEqual(rows['storage/pve2/shared']['status'], 'unknown')
        self.assertNotIn('maxdisk', rows['storage/pve2/shared'])

    def test_storage_rows_pve8_single_host(self):
        self.host(RRD_PVE8, {}, nodename='pve1')
        rows = {row['id']: row for row in pve_mirror.cluster_resources_storage()}
        self.assertEqual(sorted(rows), ['storage/pve1/local', 'storage/pve1/local-lvm'])
        self.assertEqual((rows['storage/pve1/local']['maxdisk'], rows['storage/pve1/local']['disk']),
                         (50000000000, 10000000000))

    def test_storage_list(self):
        self.host(RRD_PVE9, {})
        rows = {row['storage']: row for row in pve_mirror.storage_list()}
        self.assertEqual(rows['local'], {'storage': 'local', 'type': 'dir',
                                         'content': 'vztmpl,iso,backup', 'path': '/var/lib/vz'})
        self.assertEqual(rows['shared']['nodes'], 'pve2')
        self.assertEqual(rows['offsite']['disable'], 1)
        self.assertNotIn('disable', rows['local-lvm'])

    def test_storage_config_that_needs_pve_defaults_falls_back(self):
        self.host(RRD_PVE9, {})
        for text in ('lvmthin: data\n\tthinpool data\n\tcontent images\n',
                     STORAGE_CFG + '\nglusterfs: gl\n\tserver x\n\tcontent images\n',
                     STORAGE_CFG + '\ncustomplug: c\n\tcontent images\n',
                     STORAGE_CFG.replace('\tpath /var/lib/vz\n', '\tpath /srv\n'),
                     STORAGE_CFG + 'not a property\n'):
            with self.subTest(text=text[-40:]):
                self.write('storage.cfg', text)
                self.assertIsNone(pve_mirror.cluster_resources_storage())
                self.assertIsNone(pve_mirror.storage_list())
        self.write('storage.cfg', STORAGE_CFG + '\nzfspool: tank\n\tpool tank\n')
        self.assertIsNotNone(pve_mirror.cluster_resources_storage())
        self.assertIsNone(pve_mirror.storage_list())


class ClusterAndGuestTests(MirrorFixture):
    def test_cluster_nodes_from_members(self):
        self.host(RRD_PVE9, {}, nodename='pmxlab1', nodelist={
            'pmxlab1': {'id': 1, 'online': 1, 'ip': '10.90.0.11'},
            'pmxlab2': {'id': 2, 'online': 1, 'ip': '10.90.0.12'},
            'pmxlab3': {'id': 3, 'online': 0, 'ip': '10.90.0.13'}})
        self.assertEqual(pve_mirror.cluster_nodes(), [
            {'name': 'pmxlab2', 'ip': '10.90.0.12', 'online': 1},
            {'name': 'pmxlab3', 'ip': '10.90.0.13', 'online': 0}])
        self.host(RRD_PVE9, {})
        self.assertEqual(pve_mirror.cluster_nodes(), [])

    def test_config_properties_and_agent(self):
        text = 'agent: enabled=1,fstrim_cloned_disks=1\nname: x\n[PENDING]\nlock: migrate\n'
        self.assertEqual(pve_mirror.config_properties(text, ('agent', 'lock')),
                         {'agent': 'enabled=1,fstrim_cloned_disks=1'})
        for value, expected in (('1', True), ('enabled=1', True), ('1,type=isa', True),
                                ('on', True), ('0', False), ('enabled=0', False),
                                ('type=virtio', False), ('', False), (None, False)):
            with self.subTest(value=value):
                self.assertEqual(pve_mirror.agent_enabled(value), expected)

    def test_local_guest_status(self):
        self.host(RRD_PVE9, {}, nodename='amd')
        self.write('nodes/amd/qemu-server/131.conf', 'name: vm\n')
        self.write('nodes/amd/qemu-server/132.conf', 'name: stale\n')
        self.write('nodes/amd/lxc/104.conf', 'hostname: ct\n')
        self.write('nodes/amd/lxc/105.conf', 'hostname: ct2\n')
        self.write('nodes/other/qemu-server/200.conf', 'name: remote\n')
        pidfile = str(self.run / '131.pid')
        (self.run / '131.pid').write_text('4242\n')
        (self.run / '132.pid').write_text('4343\n')
        process = self.proc / '4242'
        process.mkdir()
        (process / 'cmdline').write_bytes(b'/usr/bin/kvm\0-id\0131\0-pidfile\0' + pidfile.encode() + b'\0')
        (process / 'stat').write_bytes(b'4242 (kvm) S 1 4242')
        (self.proc / 'net' / 'unix').write_text(
            'Num RefCount Protocol Flags Type St Inode Path\n'
            '00000000b68ba9e7: 00000002 00000000 00010000 0001 01 33453114 @/var/lib/lxc/104/command\n')
        status = pve_mirror.local_guest_status
        self.assertEqual(status(131), {'type': 'qemu', 'status': 'running'})
        self.assertEqual(status('132'), {'type': 'qemu', 'status': 'stopped'})
        self.assertEqual(status(104), {'type': 'lxc', 'status': 'running'})
        self.assertEqual(status(105), {'type': 'lxc', 'status': 'stopped'})
        self.assertEqual(status(200), {})
        self.assertIsNone(status('x'))
        (process / 'stat').write_bytes(b'4242 (kvm) Z 1 4242')
        self.assertEqual(status(131)['status'], 'stopped')



class NodeAndClusterStatusTests(MirrorFixture):
    CLUSTER = {'nodename': 'pmxlab1', 'version': 9,
               'cluster': {'name': 'pmxlab', 'version': 3, 'nodes': 3, 'quorate': 1},
               'nodelist': {'pmxlab1': {'id': 1, 'online': 1, 'ip': '10.90.0.11'},
                            'pmxlab2': {'id': 2, 'online': 1, 'ip': '10.90.0.12'},
                            'pmxlab3': {'id': 3, 'online': 0, 'ip': '10.90.0.13'}}}

    def test_node_rows_pve9_single_host(self):
        self.host(RRD_PVE9, {})
        self.assertEqual(pve_mirror.cluster_resources_node(), [{
            'id': 'node/amd', 'node': 'amd', 'type': 'node', 'status': 'online',
            'uptime': 1286709, 'cpu': 0.0120177863237592, 'mem': 6330769408,
            'disk': 64159633408, 'level': '', 'maxcpu': 16, 'maxmem': 16110796800,
            'maxdisk': 100861726720}])

    def test_node_rows_pve8_and_offline_members(self):
        self.host(RRD_PVE8, {}, nodename='pve1', nodelist={
            'pve1': {'id': 1, 'online': 1}, 'pve2': {'id': 2, 'online': 0}})
        rows = {row['node']: row for row in pve_mirror.cluster_resources_node()}
        self.assertEqual((rows['pve1']['status'], rows['pve1']['cpu'], rows['pve1']['mem'],
                          rows['pve1']['maxmem'], rows['pve1']['maxcpu']),
                         ('online', 0.1, 4000000000, 8000000000, 8))
        self.assertEqual(rows['pve2'], {'id': 'node/pve2', 'node': 'pve2', 'type': 'node',
                                        'status': 'offline'})
        self.host(RRD_PVE8.replace('pve2-node/pve1', 'pve2-node/pve2'), {}, nodename='pve1',
                  nodelist={'pve1': {'id': 1, 'online': 1}, 'pve2': {'id': 2, 'online': 0}})
        rows = {row['node']: row for row in pve_mirror.cluster_resources_node()}
        self.assertEqual(rows['pve1']['status'], 'unknown')
        self.assertEqual((rows['pve2']['status'], rows['pve2']['maxmem']), ('offline', 8000000000))
        self.assertNotIn('cpu', rows['pve2'])

    def test_node_rows_fall_back_with_the_mirror(self):
        self.assertIsNone(pve_mirror.cluster_resources_node())
        self.host(RRD_PVE9.replace('pve-node-9.0', 'pve-node-10.0'), {})
        self.assertIsNone(pve_mirror.cluster_resources_node())

    def test_cluster_status_like_pvesh(self):
        self.host(RRD_PVE9, {})
        self.write('.members', json.dumps(self.CLUSTER))
        self.assertEqual(pve_mirror.cluster_status(), [
            {'type': 'cluster', 'id': 'cluster', 'name': 'pmxlab', 'version': 3, 'nodes': 3,
             'quorate': 1},
            {'type': 'node', 'id': 'node/pmxlab1', 'name': 'pmxlab1', 'nodeid': 1,
             'ip': '10.90.0.11', 'online': 1, 'local': 1},
            {'type': 'node', 'id': 'node/pmxlab2', 'name': 'pmxlab2', 'nodeid': 2,
             'ip': '10.90.0.12', 'online': 1, 'local': 0},
            {'type': 'node', 'id': 'node/pmxlab3', 'name': 'pmxlab3', 'nodeid': 3,
             'ip': '10.90.0.13', 'online': 0, 'local': 0}])
        no_quorum = json.loads(json.dumps(self.CLUSTER))
        no_quorum['cluster']['quorate'] = 0
        self.write('.members', json.dumps(no_quorum))
        self.assertEqual(pve_mirror.cluster_status()[0]['quorate'], 0)

    def test_cluster_status_single_host_and_broken_files(self):
        self.host(RRD_PVE9, {})
        self.assertEqual(pve_mirror.cluster_status(), [
            {'type': 'node', 'id': 'node/amd', 'name': 'amd', 'nodeid': 0, 'local': 1,
             'online': 1}])
        broken = json.loads(json.dumps(self.CLUSTER))
        broken['nodelist']['pmxlab2'] = 'x'
        for text in ('{', json.dumps({'version': 1}), json.dumps(broken)):
            with self.subTest(text=text[:30]):
                self.write('.members', text)
                self.assertIsNone(pve_mirror.cluster_status())

if __name__ == '__main__':
    unittest.main()
