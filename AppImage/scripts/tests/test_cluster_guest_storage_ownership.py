import sys
import unittest
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
import tempfile

from health_fixture_modules import load_health_modules
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Dependencies are private to this module's fixture, never published at collection.

flask_server = SimpleNamespace(
    get_proxmox_node_name=lambda: "fixture",
    get_cached_pvesh_cluster_resources_vm=lambda: [],
    get_cached_vm_disk=lambda _vmid: None,
)


def setUpModule():
    global health_monitor, notification_events, health_thresholds
    temporary = tempfile.TemporaryDirectory(prefix='cluster-ownership-')
    unittest.addModuleCleanup(temporary.cleanup)
    health_monitor, notification_events, health_thresholds = load_health_modules(temporary.name)


class _Persistence:
    def __init__(self):
        self.recorded = []
        self.cleared = []

    def record_error(self, **kwargs):
        self.recorded.append(kwargs)

    def get_active_errors(self, *args, **kwargs):
        return []

    def clear_error(self, key):
        self.cleared.append(key)


class ClusterGuestStorageOwnershipTests(unittest.TestCase):
    def setUp(self):
        dependencies = patch.dict(sys.modules, {
            'flask_server': flask_server, 'health_thresholds': health_thresholds,
        })
        dependencies.start()
        self.addCleanup(dependencies.stop)
        self.monitor = health_monitor.HealthMonitor.__new__(health_monitor.HealthMonitor)
        self.persistence = _Persistence()
        self.resources = [
            {
                "type": "lxc", "node": "hades", "status": "running",
                "vmid": 128, "name": "plex", "disk": 94, "maxdisk": 100,
            },
            {
                "type": "lxc", "node": "poseidon", "status": "running",
                "vmid": 129, "name": "remote", "disk": 99, "maxdisk": 100,
            },
        ]

    def test_lxc_capacity_records_only_guests_owned_by_local_node(self):
        with (
            patch.object(health_monitor, "MOUNT_MONITOR_AVAILABLE", False),
            patch.object(health_monitor, "health_persistence", self.persistence),
            patch.object(flask_server, "get_proxmox_node_name", return_value="hades"),
            patch.object(flask_server, "get_cached_pvesh_cluster_resources_vm", return_value=self.resources),
        ):
            result = self.monitor._check_lxc_disk_usage()

        self.assertEqual(result["status"], "WARNING")
        self.assertEqual([row["error_key"] for row in self.persistence.recorded], ["lxc_disk_128"])
        self.assertEqual(self.persistence.recorded[0]["details"]["node"], "hades")
        self.assertNotIn("CT 129", result["checks"])

    def test_vm_capacity_does_not_probe_remote_guest_agent(self):
        resources = [
            {"type": "qemu", "node": "hades", "status": "running", "vmid": 201, "name": "local"},
            {"type": "qemu", "node": "poseidon", "status": "running", "vmid": 202, "name": "remote"},
        ]

        def disk_for(vmid):
            if vmid == 201:
                return (94, 100)
            raise AssertionError("remote VM was probed")

        with (
            patch.object(health_monitor, "health_persistence", self.persistence),
            patch.object(flask_server, "get_proxmox_node_name", return_value="hades"),
            patch.object(flask_server, "get_cached_pvesh_cluster_resources_vm", return_value=resources),
            patch.object(flask_server, "get_cached_vm_disk", side_effect=disk_for),
        ):
            result = self.monitor._check_vm_disk_usage()

        self.assertEqual(result["status"], "WARNING")
        self.assertEqual([row["error_key"] for row in self.persistence.recorded], ["vm_disk_201"])
        self.assertEqual(self.persistence.recorded[0]["details"]["node"], "hades")

    def test_foreign_legacy_record_is_not_a_recovery(self):
        collector = notification_events.PollingCollector(Queue())
        resources = [{"type": "lxc", "node": "poseidon", "vmid": 128}]
        with (
            patch.object(flask_server, "get_proxmox_node_name", return_value="hades"),
            patch.object(flask_server, "get_cached_pvesh_cluster_resources_vm", return_value=resources),
        ):
            foreign = collector._guest_storage_error_is_now_foreign(
                "lxc_disk_128", {"details": {"vmid": "128"}}
            )
        self.assertTrue(foreign)

    def test_local_recovery_remains_a_recovery(self):
        collector = notification_events.PollingCollector(Queue())
        resources = [{"type": "lxc", "node": "hades", "vmid": 128}]
        with (
            patch.object(flask_server, "get_proxmox_node_name", return_value="hades"),
            patch.object(flask_server, "get_cached_pvesh_cluster_resources_vm", return_value=resources),
        ):
            foreign = collector._guest_storage_error_is_now_foreign(
                "lxc_disk_128", {"details": {"vmid": "128", "node": "hades"}}
            )
        self.assertFalse(foreign)


if __name__ == "__main__":
    unittest.main()
