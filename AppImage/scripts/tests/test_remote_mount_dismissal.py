"""Remote mount checks carry the key their dismissal is saved under."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
import tempfile
from health_fixture_modules import load_health_modules
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

def setUpModule():
    global health_monitor
    temporary = tempfile.TemporaryDirectory(prefix='remote-mount-')
    unittest.addModuleCleanup(temporary.cleanup)
    health_monitor, _, _ = load_health_modules(temporary.name)


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
