"""A remote mount of an excluded storage never alerts, on the host or in a CT."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from health_fixture_modules import load_health_modules  # noqa: E402
import mount_monitor  # noqa: E402

SHARE = '//192.168.1.20/backups'
HOST = [{'target': '/mnt/pve/smb-windows', 'source': SHARE, 'status': 'stale', 'fstype': 'cifs'},
        {'target': '/mnt/pve/nas', 'source': '192.168.1.30:/nas', 'status': 'stale', 'fstype': 'nfs4'}]
LXC = [{'target': '/mnt/datastore', 'source': SHARE, 'status': 'stale', 'fstype': 'cifs',
        'lxc_id': '107', 'lxc_name': 'pbs'}]


def setUpModule():
    global health_monitor
    temporary = tempfile.TemporaryDirectory(prefix='mount-exclusion-')
    unittest.addModuleCleanup(temporary.cleanup)
    health_monitor, _, _ = load_health_modules(temporary.name)


class _Persistence:
    def __init__(self, excluded, active=()):
        self.excluded, self.active = set(excluded), list(active)
        self.recorded, self.cleared = [], []

    def get_excluded_storage_names(self, check_type='health'):
        return self.excluded

    def record_error(self, **kwargs):
        self.recorded.append(kwargs)

    def get_active_errors(self, *args, **kwargs):
        return self.active

    def clear_error(self, key):
        self.cleared.append(key)


class StorageForMount(unittest.TestCase):
    def test_host_mount_is_its_storage_and_a_ct_mount_of_the_same_share_too(self):
        self.assertEqual(mount_monitor.storage_for_mount('/mnt/pve/smb-windows', SHARE, HOST), 'smb-windows')
        self.assertEqual(mount_monitor.storage_for_mount('/mnt/datastore', SHARE, HOST), 'smb-windows')
        self.assertIsNone(mount_monitor.storage_for_mount('/mnt/other', '//10.0.0.9/x', HOST))
        self.assertIsNone(mount_monitor.storage_for_mount('/mnt/other', '', HOST))


class RemoteMountExclusion(unittest.TestCase):
    def check(self, excluded, active=()):
        persistence = _Persistence(excluded, active)
        mounts = SimpleNamespace(scan_remote_mounts=lambda force: [dict(m) for m in HOST],
                                 scan_lxc_mounts=lambda force: [dict(m) for m in LXC],
                                 storage_for_mount=mount_monitor.storage_for_mount)
        with mock.patch.object(health_monitor, 'MOUNT_MONITOR_AVAILABLE', True), \
                mock.patch.object(health_monitor, 'mount_monitor', mounts, create=True), \
                mock.patch.object(health_monitor, 'health_persistence', persistence):
            result = health_monitor.HealthMonitor._check_remote_mounts(SimpleNamespace())
        return result, persistence

    def test_excluded_storage_mounts_are_informational_on_the_host_and_in_the_container(self):
        old = [{'error_key': 'mount_stale_/mnt/pve/smb-windows'}, {'error_key': 'mount_stale_ct107:/mnt/datastore'}]
        result, persistence = self.check({'smb-windows'}, old)
        checks = result['checks']
        self.assertEqual(checks['/mnt/pve/smb-windows']['status'], 'INFO')
        self.assertEqual(checks['CT 107 (pbs) /mnt/datastore']['status'], 'INFO')
        self.assertEqual([e['error_key'] for e in persistence.recorded], ['mount_stale_/mnt/pve/nas'])
        self.assertEqual(set(persistence.cleared), {e['error_key'] for e in old})
        self.assertEqual(persistence.recorded[0]['details']['storage_name'], 'nas')

    def test_without_exclusions_every_stale_mount_alerts_with_its_storage(self):
        result, persistence = self.check(set())
        self.assertEqual(result['status'], 'CRITICAL')
        names = {e['error_key']: e['details']['storage_name'] for e in persistence.recorded}
        self.assertEqual(names, {'mount_stale_/mnt/pve/smb-windows': 'smb-windows',
                                 'mount_stale_/mnt/pve/nas': 'nas',
                                 'mount_stale_ct107:/mnt/datastore': 'smb-windows'})


class NotificationExclusion(unittest.TestCase):
    def dispatched(self, event_type, data, excluded):
        import notification_manager
        from notification_events import NotificationEvent
        manager = notification_manager.NotificationManager.__new__(notification_manager.NotificationManager)
        manager._enabled = True
        manager._config = {}
        claims = []
        manager._claim_delivery = lambda event: claims.append(event) or None
        persistence = SimpleNamespace(is_storage_excluded=lambda name, kind: kind == 'notifications' and name in excluded)
        with mock.patch.dict(sys.modules, {'health_persistence': SimpleNamespace(health_persistence=persistence)}):
            manager._dispatch_event(NotificationEvent(event_type, 'CRITICAL', dict(data), source='health'))
        return bool(claims)

    def test_alert_and_recovery_of_an_excluded_mount_are_silent(self):
        alert = {'mount_target': '/mnt/pve/smb-windows', 'mount_source': SHARE, 'storage_name': 'smb-windows'}
        self.assertFalse(self.dispatched('mount_stale', alert, {'smb-windows'}))
        self.assertFalse(self.dispatched('error_resolved', dict(alert, alert_event_type='mount_stale'), {'smb-windows'}))
        self.assertTrue(self.dispatched('mount_stale', alert, set()))

    def test_recovery_recorded_before_the_storage_name_existed_is_silent_too(self):
        old = {'mount_target': '/mnt/pve/smb-windows', 'mount_source': SHARE, 'alert_event_type': 'mount_stale'}
        self.assertFalse(self.dispatched('error_resolved', old, {'smb-windows'}))


if __name__ == '__main__':
    unittest.main()
