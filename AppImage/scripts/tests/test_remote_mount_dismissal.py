"""Remote mount checks carry the key their dismissal is saved under."""
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

_health_persistence_module = ModuleType("health_persistence")
_health_persistence_module.health_persistence = SimpleNamespace(cleanup_old_errors=lambda: None)
_health_persistence_module.disk_base_name = lambda name: str(name).replace("/dev/", "")
sys.modules.setdefault("health_persistence", _health_persistence_module)
sys.modules.setdefault("psutil", ModuleType("psutil"))
sys.modules.setdefault("flask_server", SimpleNamespace(
    get_proxmox_node_name=lambda: "fixture",
    get_cached_pvesh_cluster_resources_vm=lambda: [],
    get_cached_vm_disk=lambda _vmid: None,
))

import health_monitor  # noqa: E402


class _Persistence:
    def __init__(self):
        self.recorded = []

    def record_error(self, **kwargs):
        self.recorded.append(kwargs)

    def get_active_errors(self, *args, **kwargs):
        return []

    def clear_error(self, key):
        pass


class RemoteMountDismissal(unittest.TestCase):
    def check(self, host, lxc=()):
        persistence = _Persistence()
        mounts = SimpleNamespace(scan_remote_mounts=lambda force: list(host),
                                 scan_lxc_mounts=lambda force: list(lxc))
        with patch.object(health_monitor, "MOUNT_MONITOR_AVAILABLE", True), \
                patch.object(health_monitor, "mount_monitor", mounts, create=True), \
                patch.object(health_monitor, "health_persistence", persistence):
            result = health_monitor.HealthMonitor._check_remote_mounts(SimpleNamespace())
        return result, persistence

    def test_stale_and_read_only_mounts_carry_their_saved_key(self):
        result, persistence = self.check(
            [{"target": "/mnt/pve/nas", "status": "stale", "fstype": "nfs4"},
             {"target": "/mnt/share", "status": "ok", "fstype": "cifs"}],
            [{"target": "/media", "status": "readonly", "fstype": "nfs4", "lxc_id": "120", "lxc_name": "app"}])
        checks = result["checks"]
        self.assertEqual(checks["/mnt/pve/nas"]["error_key"], "mount_stale_/mnt/pve/nas")
        self.assertEqual(checks["CT 120 (app) /media"]["error_key"], "mount_readonly_ct120:/media")
        self.assertTrue(checks["/mnt/pve/nas"]["dismissable"])
        self.assertTrue(checks["CT 120 (app) /media"]["dismissable"])
        self.assertNotIn("error_key", checks["/mnt/share"])
        self.assertEqual({entry["error_key"] for entry in persistence.recorded},
                         {"mount_stale_/mnt/pve/nas", "mount_readonly_ct120:/media"})


if __name__ == "__main__":
    unittest.main()
