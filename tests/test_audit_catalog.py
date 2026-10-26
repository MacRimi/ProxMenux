"""All 43 checks against a declared fixture host, plus boundary/failure cases.

No subprocesses, network connections or real host paths are consulted.
"""
import json
from pathlib import PurePosixPath
from types import SimpleNamespace
import sys
import time
import unittest
from unittest.mock import patch

from test_audit_report import Context, evaluate, HEADER
import audit_checks as engine
import audit_checks_pve as checks
import audit_policy
import audit_profiles

NOW = 1788700000
VM_CMD = ("pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json")
TASK_CMD = ("pvesh", "get", "/nodes/fixture/tasks", "--typefilter", "vzdump", "--limit", "200", "--output-format", "json")
PBS_CMD = ("pvesh", "get", "/nodes/fixture/storage/pbs/content", "--output-format", "json")
DF_CMD = ("df", "--output=target,pcent,ipcent,size,avail", "/", "/var", "/var/log", "/var/lib/vz")
FINDMNT_CMD = ("findmnt", "-rno", "TARGET,OPTIONS")
LVS_CMD = ("lvs", "--noheadings", "--units", "b", "--nosuffix", "--separator", "|", "-o",
           "vg_name,lv_name,lv_size,pool_lv,lv_attr,data_percent,metadata_percent")

# Explicit identities, not just a count: swapping an old check for a new
# one must not let this contract pass accidentally.
EXPECTED = {
    "backup.guest_coverage": "conformant", "backup.last_backup_age": "conformant",
    "backup.retention_defined": "conformant", "backup.verification_state": "conformant",
    "backup.job_results": "conformant", "storage.connected_storage": "conformant",
    "storage.orphaned_volumes": "conformant", "storage.thin_pool_overprovisioning": "conformant",
    "storage.zfs_arc_max": "conformant", "storage.zfs_scrub_age": "conformant",
    "storage.pool_integrity": "conformant", "system.pending_reboot": "conformant",
    "system.kernel_current": "conformant", "system.security_updates": "conformant",
    "system.enterprise_repo_without_subscription": "observation", "system.memory_overcommit": "conformant",
    "system.time_synchronisation": "conformant", "system.journal_size": "conformant",
    "system.swap_configured": "conformant", "system.filesystem_capacity": "conformant",
    "system.update_chain": "conformant", "system.notification_delivery": "conformant",
    "guests.privileged_containers": "conformant", "guests.qemu_without_agent": "conformant",
    "guests.autostart": "conformant", "guests.stuck_snapshots": "conformant",
    "guests.cpu_host_type": "conformant", "guests.replication_state": "conformant",
    "network.bond_members": "conformant", "network.bridge_without_ports": "conformant",
    "security.host_firewall_enabled": "conformant", "security.ssh_root_login": "conformant",
    "security.certificate_expiry": "conformant", "security.lynis_warnings": "conformant",
    "hardware.disk_service_life": "conformant",
    "backup.host_recovery": "conformant", "system.cluster_quorum": "conformant",
    "hardware.disk_errors": "warning", "system.boot_loader": "conformant",
    "system.failed_units": "conformant", "storage.ceph_health": "conformant",
    "storage.array_integrity": "conformant", "system.ha_state": "conformant",
}

# A three-node cluster over two corosync rings, so the check has both a
# membership to compare and a link count that is not the bare minimum.
COROSYNC_CONF = """totem {
  cluster_name: fixture-cluster
  interface { linknumber: 0 }
}
nodelist {
  node { name: fixture ring0_addr: 10.0.0.1 ring1_addr: 10.1.0.1 nodeid: 1 }
  node { name: second  ring0_addr: 10.0.0.2 ring1_addr: 10.1.0.2 nodeid: 2 }
  node { name: third   ring0_addr: 10.0.0.3 ring1_addr: 10.1.0.3 nodeid: 3 }
}
"""

PVECM_NODES = """Membership information
----------------------
    Nodeid      Votes Name
         1          1 fixture (local)
         2          1 second
         3          1 third
"""

TIMERS = ("NEXT LEFT LAST PASSED UNIT ACTIVATES\n"
          "Sun 2026-09-07 - - - proxmenux-backup-hostcfg-daily.timer "
          "proxmenux-backup-hostcfg-daily.service\n")


class FixturePath:
    def __init__(self, owner, value):
        self.owner, self.value = owner, str(value)
    def __str__(self): return self.value
    def __truediv__(self, name): return FixturePath(self.owner, self.value.rstrip('/') + '/' + name)
    @property
    def name(self): return PurePosixPath(self.value).name
    def exists(self): return self.value in self.owner.ctx.files or self.is_dir()
    def is_file(self): return self.value in self.owner.ctx.files
    def is_dir(self): return self.value in self.owner.directories
    def read_text(self, **kwargs):
        if self.value not in self.owner.ctx.files: raise FileNotFoundError(self.value)
        return self.owner.ctx.files[self.value]
    def stat(self):
        if not self.exists(): raise FileNotFoundError(self.value)
        return SimpleNamespace(st_mtime=self.owner.stamps.get(self.value, NOW))
    def glob(self, pattern):
        return [FixturePath(self.owner, p) for p in sorted(self.owner.ctx.files)
                if str(PurePosixPath(p).parent) == self.value and PurePosixPath(p).match(pattern)]
    def iterdir(self): return self.glob('*')


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.ctx = Context(lxc_configs={101: 'unprivileged: 1\nonboot: 1\nmemory: 512\n'},
                           qemu_configs={200: 'agent: 1\nonboot: 1\nmemory: 1024\ncpu: kvm64\n'},
                           storages=[{'id': 'backups', 'type': 'dir', 'content': 'backup', 'prune-backups': 'keep-last=3'},
                                     {'id': 'pbs', 'type': 'pbs', 'content': 'backup'},
                                     {'id': 'local', 'type': 'dir', 'content': 'images'}])
        self.ctx.storage_snapshot = {'rows': [{'name': s['id'], 'node': 'fixture', 'status': 'available',
                                              'total': 100, 'used': 20} for s in self.ctx.storages]}
        self.ctx.lynis_report = {'complete': True, 'warnings': [], 'suggestions': [], 'hardening_index': 80, 'mtime': NOW}
        self.ctx.monitor_snapshot = {'smart': {'sda': (NOW, {'power_on_hours': 12})}}
        stamp = time.strftime('%Y_%m_%d-%H_%M_%S', time.localtime(NOW - 3600))
        self.ctx.responses.update({
            ('pvesm', 'list', 'backups'): (0, HEADER + ''.join(
                f'backups:backup/vzdump-{kind}-{vmid}-{stamp}.tar.zst zst backup 1024 {vmid}\n'
                for kind, vmid in [('lxc', 101), ('qemu', 200)])),
            ('uname', '-r'): (0, '6.8.12-1-pve'),
            ('dpkg-query', '-W', '-f=${db:Status-Status} ${Package}\n'): (0, 'installed proxmox-kernel-6.8.12-1-pve-signed\n'),
            ('proxmox-boot-tool', 'kernel', 'list'): (0, 'Automatically selected kernels:\n6.8.12-1-pve\nPinned kernel:\n6.8.12-1-pve\n'),
            ('cat', '/proc/meminfo'): (0, 'MemTotal: 16777216 kB\nMemAvailable: 10000000 kB\n'),
            ('timedatectl', 'show', '-p', 'NTP', '-p', 'NTPSynchronized'): (0, 'NTP=yes\nNTPSynchronized=yes\n'),
            ('apt-get', '-s', 'upgrade'): (0, 'Reading package lists...\n0 upgraded, 0 newly installed\n'),
            ('openssl', 'x509', '-enddate', '-noout', '-in', '/etc/pve/local/pve-ssl.pem'): (0, 'notAfter=fixture'),
            ('date', '-d', 'fixture', '+%s'): (0, str(NOW + 90 * 86400)),
            ('sshd', '-T'): (0, 'permitrootlogin prohibit-password\npasswordauthentication yes\nkbdinteractiveauthentication no\n'),
            ('journalctl', '--disk-usage'): (0, 'Archived and active journals take up 1.0M in the file system.'),
            ('swapon', '--show=NAME,SIZE,TYPE', '--bytes', '--noheadings'): (0, '/dev/swap 1048576 partition'),
            ('zpool', 'list', '-H', '-o', 'name'): (0, 'tank\n'),
            ('zpool', 'list', '-H', '-o', 'name,health'): (0, 'tank\tONLINE\n'),
            ('zpool', 'status', 'tank'): (0, '  state: ONLINE\n  scan: scrub repaired 0B in 1h with 0 errors on ' + time.ctime(NOW) + '\n  disk ONLINE 0 0 0\n'),
            ('pvesh', 'get', '/nodes/fixture/replication', '--output-format', 'json'): (0, json.dumps([{'id':'101-0', 'last_sync':NOW-60, 'schedule':'daily'}])),
            TASK_CMD: (0, json.dumps([{'type': 'vzdump', 'id': '101', 'status': 'OK'}])),
            PBS_CMD: (0, json.dumps([self.snapshot()])),
            DF_CMD: (0, 'Mounted on Use% IUse% 1K-blocks Avail\n/ 20% 10% 100 80\n/ 20% 10% 100 80\n'),
            FINDMNT_CMD: (0, '/ rw,relatime\n/var/log rw,relatime\n'),
            LVS_CMD: (0, 'pve|data|1000000000||twi-a-tz--|20|5\npve|vm-101-disk-0|100000000|data|Vwi-a-tz--||\n'),
            ('ceph', '-s', '--format', 'json'): (0, json.dumps(
                {'health': {'status': 'HEALTH_OK', 'checks': {}},
                 'quorum_names': ['a', 'b', 'c']})),

            ('ha-manager', 'status'): (0,
                'quorum OK\nmaster fixture (active, Mon Jan 1 00:00:00 2026)\n'
                'lrm fixture (active, Mon Jan 1 00:00:00 2026)\n'
                'service vm:100 (fixture, started)\n'),
            ('systemctl', 'list-units', '--state=failed', '--no-legend',
             '--no-pager', '--plain'): (0, ''),
            ('systemctl', 'is-active', 'pve-cluster', 'pvedaemon',
             'pveproxy', 'pvestatd'): (0, 'active\nactive\nactive\nactive\n'),
            ('proxmox-boot-tool', 'status'): (0,
                "System currently booted with uefi\n"
                "654E-D6BD is configured with: uefi (versions: 6.8.12-1-pve)\n"
                "6550-5CBE is configured with: uefi (versions: 6.8.12-1-pve)\n"),
            ('pvecm', 'status'): (0, 'Quorate: Yes\nExpected votes: 3\nTotal votes: 3\n'),
            ('pvecm', 'nodes'): (0, PVECM_NODES),
            ('systemctl', 'list-timers', '--all', '--no-pager'): (0, TIMERS),
        })
        archive = 'hostcfg-daily-20260906_000017.tar.zst'
        self.ctx.files.update({
            f'/var/lib/vz/dump/{archive}': 'fixture archive',
            f'/var/lib/vz/dump/{archive}.proxmenux.json': json.dumps({
                'schema_version': 1, 'kind': 'scheduled', 'job_id': 'hostcfg-daily',
                'hostname': 'fixture', 'archive': archive, 'archive_size': 4377756725,
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(NOW - 3600)),
            }),
        })
        self.ctx.files.update({
            '/etc/kernel/proxmox-boot-uuids':'654E-D6BD\n6550-5CBE\n',
            '/etc/pve/ceph.conf':'[global]\n',
            '/etc/pve/ha/resources.cfg':'vm: 100\n',
            '/proc/mdstat':('Personalities : [raid1]\n'
                            'md0 : active raid1 sda1[0] sdb1[1]\n'
                            '      976630464 blocks super 1.2 [2/2] [UU]\n'),
            '/etc/pve/firewall/cluster.fw':'[OPTIONS]\nenable: 1\n',
            '/etc/pve/local/pve-ssl.pem':'fixture certificate',
            '/etc/corosync/corosync.conf': COROSYNC_CONF,
            '/etc/systemd/journald.conf':'SystemMaxUse=1G\n',
            '/etc/network/interfaces':'iface vmbr0 inet static\n bridge-ports eth0\n',
            '/etc/pve/replication.cfg':'local: 101-0\n target other\n',
            '/proc/spl/kstat/zfs/arcstats':'c_min 4 1048576\nc_max 4 1073741824\nsize 4 5000000\n',
            '/sys/module/zfs/parameters/zfs_arc_max':'1073741824',
            '/var/lib/apt/periodic/update-success-stamp':'',
            '/proc/net/bonding/bond0':'Bonding Mode: active-backup\nSlave Interface: eth0\nMII Status: up\n',
        })
        self.directories = {'/sys/module/zfs', '/proc/net/bonding', '/etc/modprobe.d',
                            '/var/lib/vz/dump'}
        self.stamps = {}
        self.channels = {'telegram': {'enabled': True, 'configured': True}}
        self.histories = {'telegram': {'history': [{'channel':'telegram','success':1,'sent_at':NOW}]}}
        self.manager = SimpleNamespace(list_channels=lambda: {'channels': self.channels},
                                       get_history=lambda **kw: self.histories[kw['channel']])
        # A disk that reported something long ago and has been quiet since:
        # a record exists, and nothing in it is current.
        self.observations = [{'device_name': '/dev/sda', 'error_type': 'smart_error',
                              'severity': 'WARNING', 'occurrence_count': 2,
                              'first_occurrence': NOW - 90 * 86400,
                              'last_occurrence': NOW - 60 * 86400,
                              'raw_message': 'fixture'}]
        self.persistence = SimpleNamespace(
            get_disk_observations=lambda: self.observations)
        for p in (patch.object(checks, 'Path', side_effect=lambda v: FixturePath(self, v)),
                  patch.object(checks.time, 'time', return_value=NOW),
                  patch.dict(sys.modules, {'flask_server': SimpleNamespace(
                      notification_manager=self.manager,
                      health_persistence=self.persistence)})):
            p.start(); self.addCleanup(p.stop)

    def snapshot(self, state='ok', **kwargs):
        return {'vmid':101, 'content':'backup', 'ctime':NOW-100, 'volid':'pbs:backup/ct/101/date',
                'verification':{'state':state}, **kwargs}

    def result(self, fn): return evaluate(fn, self.ctx)

    def test_every_one_of_the_43_checks_has_a_real_fixture(self):
        self.assertEqual({c.check_id for c in engine.registered_checks()}, set(EXPECTED))
        for c in engine.registered_checks():
            with self.subTest(check=c.check_id):
                result = self.result(c.evaluate)
                self.assertIsNotNone(result, 'This fixture must exercise the check, not skip it')
                self.assertEqual(result['classification'], EXPECTED[c.check_id])

    def test_reboot_marker_is_evidence_even_with_no_package_named(self):
        """Something wrote the marker and did not say what.

        Reporting that as unverified described the reading rather than
        the host, which had plainly asked for a restart.
        """
        self.ctx.files['/var/run/reboot-required'] = ''
        for pkgs in ('', None):
            if pkgs is None:
                self.ctx.files.pop('/var/run/reboot-required.pkgs', None)
            else:
                self.ctx.files['/var/run/reboot-required.pkgs'] = pkgs
            rows = self.result(checks._pending_reboot)['affected']
            self.assertEqual([(r['reason_key'], r['classification']) for r in rows],
                             [('rebootMarkerWithoutPackages', 'observation')])
        # A named package still describes itself.
        self.ctx.files['/var/run/reboot-required.pkgs'] = 'libc6\n'
        rows = self.result(checks._pending_reboot)['affected']
        self.assertEqual(rows[0]['reason_key'], 'packageAwaitingRestart')

    def test_essential_state_must_be_one_word_per_service(self):
        """`systemctl is-active` prints one word per unit; anything else
        is prose, and zipping prose onto the names made every word of it
        a critical finding."""
        active = ('systemctl', 'is-active', 'pve-cluster', 'pvedaemon',
                  'pveproxy', 'pvestatd')
        self.ctx.responses[('systemctl', 'list-units', '--state=failed',
                            '--no-legend', '--no-pager', '--plain')] = (0, '')
        for output in ('Unit pvedaemon.service could not be found.',
                       'active\nactive\n', ''):
            self.ctx.responses[active] = (1, output)
            result = self.result(checks._failed_units)
            self.assertEqual(result['classification'], 'unverified',
                             f'prose became a verdict: {output!r}')
        self.ctx.responses[active] = (0, 'active\nactive\nactive\nactive\n')
        self.assertEqual(self.result(checks._failed_units)['classification'],
                         'conformant')

    def test_verification_ignores_guests_that_are_not_on_this_node(self):
        """A shared backup server holds every node's copies, and keeps
        those of guests that no longer exist anywhere."""
        # 101 is local (see the fixture); 999 belongs to somebody else.
        self.ctx.responses[PBS_CMD] = (0, json.dumps([
            self.snapshot(state='failed', vmid=999),
            self.snapshot(state='ok', vmid=101)]))
        result = self.result(checks._backup_verification)
        self.assertEqual(result['classification'], 'conformant',
                         "another node's failed snapshot was graded here")

    def test_ceph_reports_its_own_verdict_and_the_checks_behind_it(self):
        """Ceph grades its own state better than anything outside could;
        what is added is putting that verdict where the host's is read."""
        cmd = ('ceph', '-s', '--format', 'json')
        self.ctx.responses[cmd] = (0, json.dumps({'health': {
            'status': 'HEALTH_ERR', 'checks': {
                'PG_DAMAGED': {'severity': 'HEALTH_ERR',
                               'summary': {'message': '1 pg inconsistent'}},
                'OSD_NEARFULL': {'severity': 'HEALTH_WARN',
                                 'summary': {'message': '1 osd nearfull'}}}}}))
        rows = self.result(checks._ceph_health)['affected']
        self.assertEqual({r['name']: r['classification'] for r in rows},
                         {'PG_DAMAGED': 'critical', 'OSD_NEARFULL': 'warning'})
        # A warning cluster is a warning even with no check named.
        self.ctx.responses[cmd] = (0, json.dumps(
            {'health': {'status': 'HEALTH_WARN', 'checks': {}}}))
        self.assertEqual(
            self.result(checks._ceph_health)['affected'][0]['classification'], 'warning')
        # The client binary ships with Proxmox; a node without a cluster
        # configuration has nothing to report.
        del self.ctx.files['/etc/pve/ceph.conf']
        self.assertIsNone(self.result(checks._ceph_health))

    def test_array_short_of_devices_is_not_an_array_that_stopped(self):
        """Both keep serving; only one has lost what it was built for."""
        def grade(mdstat):
            self.ctx.files['/proc/mdstat'] = mdstat
            r = self.result(checks._array_integrity)
            return [(a['name'], a['reason_key'], a['classification'])
                    for a in r.get('affected', [])] or [(r['summary_key'],)]
        self.assertEqual(grade('Personalities : [raid1]\n'
                               'md0 : active raid1 sda1[0] sdb1[1]\n'
                               '      976630464 blocks super 1.2 [2/1] [U_]\n'),
                         [('md0', 'arrayDegraded', 'warning')])
        # Rebuilding is the array doing what it should.
        self.assertEqual(grade('Personalities : [raid1]\n'
                               'md0 : active raid1 sda1[0] sdb1[1]\n'
                               '      976630464 blocks super 1.2 [2/1] [U_]\n'
                               '      [==>..]  recovery = 12.0% (1/9) finish=2min\n'),
                         [('md0', 'arrayRebuilding', 'warning')])
        self.assertEqual(grade('Personalities : [raid1]\n'
                               'md0 : inactive sda1[0]\n'), 
                         [('md0', 'arrayNotActive', 'critical')])
        # No array and no multipath tool is nothing to report on.
        self.ctx.files['/proc/mdstat'] = 'Personalities :\nunused devices: <none>\n'
        self.assertIsNone(self.result(checks._array_integrity))

    def test_ha_reads_what_quorum_does_not_answer(self):
        """Quorum has its own check; this is the half it cannot answer."""
        cmd = ('ha-manager', 'status')
        self.ctx.responses[cmd] = (0,
            'quorum OK\nmaster fixture (active, Mon Jan 1 00:00:00 2026)\n'
            'lrm fixture (wait_for_agent_lock, Mon Jan 1 00:00:00 2026)\n'
            'service vm:100 (fixture, error)\n')
        rows = {r['name']: (r['reason_key'], r['classification'])
                for r in self.result(checks._ha_state)['affected']}
        self.assertEqual(rows['vm:100'], ('haServiceError', 'critical'))
        self.assertEqual(rows['fixture'], ('haManagerNotReady', 'warning'))
        # Nothing decides where a service runs without a master.
        self.ctx.responses[cmd] = (0, 'quorum OK\nlrm fixture (idle, x)\n'
                                      'service vm:100 (fixture, started)\n')
        self.assertIn('haNoMaster',
                      {r['reason_key'] for r in self.result(checks._ha_state)['affected']})
        # No declared resources is nothing to move.
        del self.ctx.files['/etc/pve/ha/resources.cfg']
        self.assertIsNone(self.result(checks._ha_state))

    def test_essential_service_down_outranks_a_peripheral_unit(self):
        """A node that keeps its guests and refuses every management
        operation looks healthy from every other angle."""
        failed = ('systemctl', 'list-units', '--state=failed', '--no-legend',
                  '--no-pager', '--plain')
        active = ('systemctl', 'is-active', 'pve-cluster', 'pvedaemon',
                  'pveproxy', 'pvestatd')
        self.ctx.responses[failed] = (
            1, 'smartd.service loaded failed failed Self-Monitoring daemon\n')
        rows = self.result(checks._failed_units)['affected']
        self.assertEqual([(r['name'], r['classification']) for r in rows],
                         [('smartd.service', 'warning')])
        # An inactive essential service is not always a failed unit, and
        # the outcome is the same, so it is asked for by name.
        self.ctx.responses[failed] = (0, '')
        self.ctx.responses[active] = (3, 'active\ninactive\nactive\nactive\n')
        rows = self.result(checks._failed_units)['affected']
        self.assertEqual([(r['name'], r['classification']) for r in rows],
                         [('pvedaemon', 'critical')])

    def test_filesystem_critical_needs_exhaustion_not_a_high_percentage(self):
        """Ninety-one per cent is a risk; nothing left is the failure.

        A fixed high percentage would not prove an interruption either,
        so the critical result comes from zero bytes, no inodes, or a
        mount the kernel reports read-only.
        """
        def grade(df, mounts='/ rw,relatime\n'):
            self.ctx.responses[DF_CMD] = (0, 'Mounted on Use% IUse% 1K-blocks Avail\n' + df)
            self.ctx.responses[FINDMNT_CMD] = (0, mounts)
            r = self.result(checks._filesystem_capacity)
            return [(a['reason_key'], a['classification']) for a in r.get('affected', [])] \
                or [(r.get('summary_key'), r['classification'])]

        self.assertEqual(grade('/ 95% 10% 100 5\n'),
                         [('filesystemNearlyFull', 'warning')])
        # Full to the last byte, whatever the rounded percentage says.
        self.assertEqual(grade('/ 100% 10% 100 0\n'),
                         [('filesystemExhausted', 'critical')])
        self.assertEqual(grade('/ 40% 100% 100 60\n'),
                         [('inodesExhausted', 'critical')])
        # Already refusing writes, and no percentage says so.
        self.assertEqual(grade('/ 40% 10% 100 60\n', '/ ro,relatime\n'),
                         [('filesystemReadOnly', 'critical')])
        # `ro` inside another option must not be mistaken for read-only.
        self.assertEqual(grade('/ 40% 10% 100 60\n', '/ rw,errors=remount-ro\n'),
                         [('withinLimits', 'conformant')])

    def test_boot_partitions_out_of_step_are_not_redundancy(self):
        """Two partitions carrying different kernels is redundancy on paper.

        The surviving disk starts something other than what this one
        would, which is exactly the case the pair exists to cover. The
        kernel check reads which version boots and says it does not
        verify the loader's installation; this is that half.
        """
        cmd = ('proxmox-boot-tool', 'status')
        self.ctx.responses[cmd] = (0,
            "System currently booted with uefi\n"
            "654E-D6BD is configured with: uefi (versions: 6.8.12-1-pve)\n"
            "6550-5CBE is configured with: uefi (versions: 6.7.0-1-pve)\n")
        reasons = {r['reason_key'] for r in self.result(checks._boot_loader)['affected']}
        self.assertIn('bootEspOutOfSync', reasons)
        self.assertIn('bootEspMissingNewest', reasons)
        # One partition is a working boot with a single point of failure.
        self.ctx.responses[cmd] = (0,
            "System currently booted with uefi\n"
            "654E-D6BD is configured with: uefi (versions: 6.8.12-1-pve)\n")
        single = self.result(checks._boot_loader)['affected'][0]
        self.assertEqual(single['reason_key'], 'bootSingleEsp')
        self.assertEqual(single['classification'], 'observation')
        # A host that does not use the tool keeps its loader elsewhere.
        del self.ctx.files['/etc/kernel/proxmox-boot-uuids']
        self.assertIsNone(self.result(checks._boot_loader))

    def test_disk_errors_are_warnings_separate_from_current_smart_health(self):
        def grade(severity, days_ago):
            self.observations[:] = [{'device_name': '/dev/sdh', 'error_type': 'io_error',
                                     'severity': severity, 'occurrence_count': 284252,
                                     'first_occurrence': NOW - 110 * 86400,
                                     'last_occurrence': NOW - days_ago * 86400,
                                     'raw_message': 'ata8.00: error: { IDNF }'}]
            result = self.result(checks._disk_errors)
            return result['affected'][0]['classification'] if result.get('affected') \
                else result['classification']

        # A recorded event asks for attention, but it does not override
        # the separate current SMART/Proxmox health result or assert a
        # present disk failure.
        for severity, days in [('CRITICAL', 0), ('CRITICAL', 60),
                               ('WARNING', 0), ('WARNING', 60)]:
            self.assertEqual(grade(severity, days), 'warning',
                             f'{severity} {days}d was not reported as a warning')
        # The observation log writes ISO strings while other Monitor
        # tables write epoch seconds. Reading only one of them made an
        # error happening now look like one that stopped long ago.
        import datetime as _dt
        iso = _dt.datetime.fromtimestamp(NOW - 3600).isoformat()
        self.observations[:] = [{'device_name': '/dev/sdh', 'error_type': 'io_error',
                                 'severity': 'critical', 'occurrence_count': 284340,
                                 'first_occurrence': iso, 'last_occurrence': iso,
                                 'raw_message': 'ata8.00: error: { IDNF }'}]
        row = self.result(checks._disk_errors)['affected'][0]
        self.assertEqual(row['classification'], 'warning')
        self.assertEqual(row['reason_key'], 'diskErrorsActive')
        # An empty store and a store the reader emptied look the same,
        # and neither supports "no disk reported an error".
        self.observations[:] = []
        result = self.result(checks._disk_errors)
        self.assertEqual(result['classification'], 'not_applicable')
        self.assertEqual(result['summary_key'], 'noEvents')

    def test_thin_pool_unknown_usage_does_not_pass(self):
        for row, expected in [('vg|thin|100||twi|10|?', 'unverified'),
                              ('vg|thin|0||twi|10|10', 'unverified'),
                              ('vg|thin|100||twi|nan|10', 'unverified'),
                              ('vg|thin|100||twi|95|?', 'warning')]:
            self.ctx.responses[LVS_CMD] = (0, row)
            result = self.result(checks._thin_overprovisioning)
            self.assertEqual(result['classification'], expected)
            self.assertTrue(result['incomplete'])

    def test_replication_status_types_and_missing_error_text(self):
        cmd = ('pvesh','get','/nodes/fixture/replication','--output-format','json')
        for fields, expected in [({'disable':'0', 'fail_count':2}, 'warning'),
                                 ({'disable':'1', 'fail_count':2}, 'observation'),
                                 ({'last_sync':NOW+500}, 'unverified'),
                                 ({'disable':'unknown'}, 'unverified')]:
            self.ctx.responses[cmd]=(0,json.dumps([{'id':'101-0','last_sync':NOW-100, **fields}]))
            self.assertEqual(self.result(checks._replication_state)['classification'], expected)
        for body in ('{}', 'null', '[3]'):
            self.ctx.responses[cmd]=(0,body)
            self.assertEqual(self.result(checks._replication_state)['classification'], 'unverified')

    def test_old_snapshot_cpu_is_not_current_cpu(self):
        self.ctx.qemu_configs={200:'name: fixture\n[snapshot]\ncpu: host\n'}
        self.assertEqual(self.result(checks._cpu_host_type)['classification'], 'conformant')

    def test_lynis_report_age_qualifies_the_warnings_it_came_with(self):
        """The age describes the report, not the host, so it rides with
        the warnings it qualifies instead of standing as a check.

        Reading "no warnings" without knowing the audit ran in June is
        reading something else entirely.
        """
        with patch.dict(self.ctx.lynis_report, {'mtime': NOW - 90 * 86400}):
            result = self.result(checks._lynis_warnings)
            self.assertEqual(result['summary_key'], 'noneStale')
            self.assertEqual(result['affected'][0]['reason_key'], 'lynisReportStale')
            self.assertEqual(result['affected'][0]['classification'], 'observation')
        # A recent report with nothing to report is simply conformant.
        self.assertEqual(self.result(checks._lynis_warnings)['classification'],
                         'conformant')
        # An unusable date does not become an age, and does not stop the
        # warnings from being reported.
        for fields in ({'mtime': NOW + 86400}, {'complete': False}):
            with patch.dict(self.ctx.lynis_report, fields):
                result = self.result(checks._lynis_warnings)
                self.assertNotIn('Stale', str(result.get('summary_key')))

    def test_profiles_cover_their_declared_scope(self):
        all_checks = engine.registered_checks()
        for name, spec in audit_profiles.PROFILES.items():
            actual = {c.check_id for c in audit_profiles.selected_checks(name, all_checks)}
            expected = set(EXPECTED) if spec['areas'] is None else {
                c.check_id for c in all_checks if c.area in spec['areas'] or c.check_id in spec['include']}
            self.assertEqual(actual, expected, name)

    def test_backup_verification_newest_not_oldest_and_each_destination(self):
        """The newest copy is what is graded, and never as critical.

        The audit performs no restore, so it cannot demonstrate that
        recovery is impossible; what it can say is whether anything
        else verified.
        """
        for older, newest, expected in [('failed','ok','conformant'), ('ok','failed','warning')]:
            self.ctx.responses[PBS_CMD]=(0,json.dumps([self.snapshot(older,ctime=NOW-500), self.snapshot(newest)]))
            self.assertEqual(self.result(checks._backup_verification)['classification'], expected)
        self.ctx.storages.append({'id':'second','type':'pbs'})
        self.ctx.responses[tuple(x.replace('/pbs/', '/second/') for x in PBS_CMD)] = (1,'unavailable')
        result = self.result(checks._backup_verification)
        self.assertEqual(result['classification'], 'warning')
        self.assertTrue(result['incomplete'])

    def test_verification_empty_missing_unknown_and_malformed(self):
        for body in ('{}', 'null', 'invalid', '[3]'):
            self.ctx.responses[PBS_CMD]=(0,body)
            self.assertEqual(self.result(checks._backup_verification)['classification'], 'unverified')
        for state, expected in [('none','observation'), ('unexpected','unverified')]:
            self.ctx.responses[PBS_CMD]=(0,json.dumps([self.snapshot(state)]))
            self.assertEqual(self.result(checks._backup_verification)['classification'], expected)
        self.ctx.responses[PBS_CMD]=(0,'[]')
        self.assertIsNone(self.result(checks._backup_verification))

    def test_backup_tasks_do_not_count_unknown_status_as_success(self):
        for status, expected in [('','unverified'),('running','unverified'),('job errors','warning'),('OK','conformant')]:
            self.ctx.responses[TASK_CMD]=(0,json.dumps([{'type':'vzdump','status':status}]))
            self.assertEqual(self.result(checks._backup_job_results)['classification'], expected)
        self.ctx.responses[TASK_CMD]=(1,'offline')
        self.assertEqual(self.result(checks._backup_job_results)['classification'], 'unverified')

    def test_backup_task_recovers_guest_from_upid(self):
        upid = 'UPID:fixture:001234:00ABCDEF:68BD1234:vzdump:106:root@pam:'
        self.ctx.responses[TASK_CMD] = (0, json.dumps([{
            'type': 'vzdump', 'status': 'job errors', 'upid': upid,
            'starttime': NOW - 60,
        }]))
        result = self.result(checks._backup_job_results)
        self.assertEqual(result['affected'][0]['vmid'], 106)
        self.assertEqual(result['affected'][0]['upid'], upid)

    def test_filesystem_partial_data_keeps_known_pressure(self):
        for row, expected in [('/ 91% 10% 100 9','warning'),('/ 20% 95% 100 80','warning'),('/ 20% - 100 80','unverified')]:
            self.ctx.responses[DF_CMD]=(0,'header\n'+row+'\n')
            self.assertEqual(self.result(checks._filesystem_capacity)['classification'], expected)
        self.ctx.responses[DF_CMD]=(1,'header\n/ 91% 10% 100 9\ndf: missing path\n')
        result=self.result(checks._filesystem_capacity)
        self.assertEqual(result['classification'],'warning'); self.assertTrue(result['incomplete'])
        self.ctx.responses[DF_CMD]=(1,'df: failure')
        self.assertEqual(self.result(checks._filesystem_capacity)['classification'],'unverified')

    def test_pool_status_failure_is_not_healthy(self):
        self.ctx.responses[('zpool','status','tank')]=(1,'unavailable')
        self.assertEqual(self.result(checks._pool_integrity)['classification'],'unverified')
        self.ctx.responses[('zpool','list','-H','-o','name,health')]=(0,'tank\tFAULTED\n')
        result=self.result(checks._pool_integrity)
        self.assertEqual(result['classification'],'critical'); self.assertTrue(result['incomplete'])

    def test_pool_counters_are_reported_without_claiming_current_failure(self):
        self.ctx.responses[('zpool','status','tank')]=(0,'state: ONLINE\n disk ONLINE 0 0 7\n')
        result=self.result(checks._pool_integrity)
        self.assertEqual(result['classification'],'warning')
        self.assertIn('not necessarily',result['evidence'])

    def test_cache_rebuild_is_not_a_repository_refresh(self):
        self.ctx.files.pop('/var/lib/apt/periodic/update-success-stamp')
        self.ctx.files['/var/cache/apt/pkgcache.bin']='rebuilt just now'
        self.assertEqual(self.result(checks._update_chain)['classification'],'unverified')
        self.ctx.files['/var/lib/apt/periodic/update-success-stamp']=''
        self.stamps['/var/lib/apt/periodic/update-success-stamp']=NOW-8*86400
        self.assertEqual(self.result(checks._update_chain)['classification'],'warning')
        self.stamps['/var/lib/apt/periodic/update-success-stamp']=NOW+86400
        self.assertEqual(self.result(checks._update_chain)['classification'],'unverified')

    def test_notification_no_history_or_error_does_not_prove_delivery(self):
        for payload in ({'history':[]}, {'history':[], 'error':'locked'}, {'history':[{'channel':'telegram','success':'0'}]}):
            self.histories['telegram']=payload
            self.assertEqual(self.result(checks._notification_delivery)['classification'],'unverified')

    def test_notification_recovery_and_disabled_channel(self):
        self.histories['telegram']['history'].append({'channel':'telegram','success':0,'sent_at':NOW-10})
        self.channels['email']={'enabled':False,'configured':True}
        self.assertEqual(self.result(checks._notification_delivery)['classification'],'conformant')
        self.histories['telegram']['history'].insert(0,{'channel':'telegram','success':0,'error_message':'fixture error'})
        result=self.result(checks._notification_delivery)
        self.assertEqual(result['classification'],'warning')
        self.assertEqual(result['affected'][0]['last_error'],'fixture error')

    def test_notification_misconfiguration_and_unknown_channel_results(self):
        self.channels['email']={'enabled':True,'configured':False}
        self.histories['telegram']={'history':[]}
        result=self.result(checks._notification_delivery)
        self.assertEqual(result['classification'],'warning'); self.assertTrue(result['incomplete'])
        self.channels={}
        self.assertEqual(self.result(checks._notification_delivery)['classification'],'observation')

    def test_certificate_just_expired_is_expired(self):
        self.ctx.responses[('date','-d','fixture','+%s')]=(0,str(NOW-1))
        result=self.result(checks._certificate_expiry)
        self.assertEqual(result['classification'],'warning')
        self.assertEqual(result['summary_key'],'expired')

    def test_kernel_next_boot_is_the_pin_or_the_newest_retained(self):
        """Without a pin the boot tool starts the newest kernel it keeps.

        Reading that as undetermined made the check unverifiable on every
        host that never pinned one, which is most of them.
        """
        cmd=('proxmox-boot-tool','kernel','list')
        # Retained across both lists; the newest of them is what boots.
        self.ctx.responses[cmd]=(0,'Manually selected kernels:\n6.9.0-1-pve\nAutomatically selected kernels:\n6.8.12-1-pve\n')
        result = self.result(checks._kernel_current)
        self.assertEqual(result['summary_key'],'newerSelected')
        self.assertIn('6.9.0-1-pve', result['evidence'])
        # The running kernel already being the newest retained is the
        # ordinary state of a host that rebooted after its last upgrade.
        self.ctx.responses[cmd]=(0,'Automatically selected kernels:\n6.8.12-1-pve\n6.7.0-1-pve\n')
        self.assertEqual(self.result(checks._kernel_current)['classification'],'conformant')
        # An explicit pin still wins over the retention lists.
        self.ctx.responses[cmd]=(0,'Pinned kernel:\n6.8.12-1-pve\nKernel pinned on next-boot:\n6.9.0-1-pve\n')
        self.assertEqual(self.result(checks._kernel_current)['summary_key'],'newerSelected')

    def test_empty_ntp_and_ssh_output_do_not_prove_configuration(self):
        self.ctx.responses[('timedatectl','show','-p','NTP','-p','NTPSynchronized')]=(0,'')
        self.assertEqual(self.result(checks._time_sync)['classification'],'unverified')
        self.ctx.responses[('sshd','-T')]=(0,'permitrootlogin yes\n')
        self.assertEqual(self.result(checks._ssh_root_login)['classification'],'unverified')

    def test_bond_unknown_member_not_claimed_as_link_failure(self):
        self.ctx.files['/proc/net/bonding/bond0']='Slave Interface: eth0\n'
        self.assertEqual(self.result(checks._bond_members)['classification'],'unverified')
        self.ctx.files['/proc/net/bonding/bond0']='Slave Interface: eth0\nMII Status: down\n'
        self.assertEqual(self.result(checks._bond_members)['classification'],'critical')

    def test_policy_exemption_and_unstated_backups(self):
        self.ctx.policy=audit_policy.Policy({'defaults':{'backup':'not_required'}})
        self.assertIsNone(self.result(checks._last_backup_age))
        self.ctx.policy=audit_policy.Policy()
        self.ctx.vzdump_jobs=''
        self.assertEqual(self.result(checks._guest_coverage)['classification'],'observation')
        self.ctx.policy=audit_policy.Policy({'defaults':{'backup':'required'}})
        self.assertEqual(self.result(checks._guest_coverage)['classification'],'warning')


if __name__ == '__main__': unittest.main()
