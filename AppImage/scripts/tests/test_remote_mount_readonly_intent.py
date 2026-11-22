"""A remote mount asked to be read-only is healthy; only one whose
configuration asks for read-write and is read-only is reported."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import mount_monitor  # noqa: E402
from health_fixture_modules import load_health_modules  # noqa: E402


class _Config(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mount-intent-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'lxc').mkdir()
        (self.root / 'systemd').mkdir()
        self.write('storage.cfg', (
            'dir: local\n\tpath /var/lib/vz\n\n'
            'nfs: Public\n\tserver 10.0.0.2\n\texport /public\n\toptions vers=4.2,ro\n\n'
            'cifs: Archivos\n\tserver 10.0.0.2\n\tshare archivos\n\n'
        ))
        self.write('fstab', '# comment\n//nas/media /mnt/media cifs ro,credentials=/root/c 0 0\n'
                            'nas:/data /mnt/data nfs defaults 0 0\n')
        self.write('systemd/mnt-backup.mount', '[Mount]\nWhat=nas:/backup\nWhere=/mnt/backup\nOptions=ro,vers=4\n')
        for name, value in (('_STORAGE_CFG', 'storage.cfg'), ('_FSTAB', 'fstab'),
                            ('_SYSTEMD_MOUNT_DIR', 'systemd'), ('_LXC_CONF_DIR', 'lxc')):
            patcher = patch.object(mount_monitor, name, str(self.root / value))
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


class ConfiguredReadOnly(_Config):
    def test_storage_options_decide_for_proxmox_mounts(self):
        self.assertIs(mount_monitor.configured_readonly('/mnt/pve/Public'), True)
        self.assertIs(mount_monitor.configured_readonly('/mnt/pve/Archivos'), False)

    def test_fstab_and_systemd_units_decide_for_their_mounts(self):
        self.assertIs(mount_monitor.configured_readonly('/mnt/media'), True)
        self.assertIs(mount_monitor.configured_readonly('/mnt/data/'), False)
        self.assertIs(mount_monitor.configured_readonly('/mnt/backup'), True)

    def test_a_mount_no_configuration_names_is_taken_as_asked(self):
        self.assertIsNone(mount_monitor.configured_readonly('/mnt/manual'))

    def test_container_mount_points(self):
        self.write('lxc/120.conf', 'arch: amd64\nmp0: /mnt/pve/Public,mp=/public,ro=1\n'
                                   'mp1: /mnt/pve/Archivos/docs,mp=/docs\n'
                                   'mp2: /mnt/data,mp=/data/\n'
                                   '[snap]\nmp3: /mnt/x,mp=/old,ro=1\n')
        host = [{'target': '/mnt/pve/Archivos', 'readonly': True},
                {'target': '/mnt/data', 'readonly': False}]
        self.assertIs(mount_monitor.configured_readonly('/public', '120', '', host), True)
        # Inherited from a read-only host mount: the host mount is the one to report.
        self.assertIsNone(mount_monitor.configured_readonly('/docs', '120', '', host))
        self.assertIs(mount_monitor.configured_readonly('/data', '120', '', host), False)
        # Snapshot sections are history, not configuration.
        self.assertIsNone(mount_monitor.configured_readonly('/old', '120', '', host))

    def test_a_mount_made_inside_the_container_follows_its_fstab(self):
        self.write('proc/77/root/etc/fstab', 'nas:/share /share nfs ro 0 0\nnas:/rw /rw nfs rw 0 0\n')
        real = mount_monitor._fstab_options

        def fstab(path):
            return real(str(self.root) + path if path.startswith('/proc/') else path)

        with patch.object(mount_monitor, '_fstab_options', fstab):
            self.assertIs(mount_monitor.configured_readonly('/share', '121', '77'), True)
            self.assertIs(mount_monitor.configured_readonly('/rw', '121', '77'), False)
            self.assertIsNone(mount_monitor.configured_readonly('/other', '121', '77'))


class MountStatus(_Config):
    def test_read_only_is_reported_only_against_a_read_write_configuration(self):
        status = mount_monitor.mount_status
        self.assertEqual(status({'target': '/mnt/pve/Public', 'readonly': True}, True), 'ok')
        self.assertEqual(status({'target': '/mnt/manual', 'readonly': True}, True), 'ok')
        self.assertEqual(status({'target': '/mnt/pve/Archivos', 'readonly': True}, True), 'readonly')
        self.assertEqual(status({'target': '/mnt/pve/Archivos', 'readonly': False}, True), 'ok')
        self.assertEqual(status({'target': '/mnt/pve/Public', 'readonly': True}, False), 'stale')


class _Persistence:
    def __init__(self):
        self.recorded = []

    def record_error(self, **kwargs):
        self.recorded.append(kwargs)

    def get_active_errors(self, *args, **kwargs):
        return [{'error_key': 'mount_readonly_/mnt/pve/Public'}]

    def clear_error(self, key):
        self.cleared = key

    def get_excluded_storage_names(self, *args):
        return set()


class HealthCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='mount-intent-health-')
        cls.addClassCleanup(temporary.cleanup)
        cls.health_monitor, _, _ = load_health_modules(temporary.name)

    def test_a_mount_asked_read_only_is_healthy_and_clears_an_old_warning(self):
        persistence = _Persistence()
        mounts = SimpleNamespace(
            scan_remote_mounts=lambda force: [{'target': '/mnt/pve/Public', 'status': 'ok',
                                               'readonly': True, 'fstype': 'nfs4'}],
            scan_lxc_mounts=lambda force: [],
            storage_for_mount=lambda target, source, host_mounts=None: None)
        with patch.object(self.health_monitor, 'MOUNT_MONITOR_AVAILABLE', True), \
                patch.object(self.health_monitor, 'mount_monitor', mounts, create=True), \
                patch.object(self.health_monitor, 'health_persistence', persistence):
            result = self.health_monitor.HealthMonitor._check_remote_mounts(SimpleNamespace())
        check = result['checks']['/mnt/pve/Public']
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(check['status'], 'OK')
        self.assertEqual(check['detail'], 'nfs4 mount reachable, read-only')
        self.assertTrue(check['readonly'])
        self.assertEqual(persistence.recorded, [])
        self.assertEqual(persistence.cleared, 'mount_readonly_/mnt/pve/Public')


if __name__ == '__main__':
    unittest.main()
