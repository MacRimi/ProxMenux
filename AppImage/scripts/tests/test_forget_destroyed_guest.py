"""A destroyed guest takes its App registrations with it, so a new guest
that reuses the VMID does not inherit them."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lxc_apps


class ForgetDestroyedGuestTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.apps = self.root / "apps"
        self.nodes = self.root / "nodes"
        self.apps.mkdir()
        for target, value in (("_APPS_DIR", str(self.apps)), ("_PVE_NODES", str(self.nodes)),
                              ("_OCI_DISMISSED_FILE", str(self.apps / ".oci-dismissed.json"))):
            patcher = mock.patch.object(lxc_apps, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def register(self, vmid):
        (self.apps / f"{vmid}.json").write_text(json.dumps({
            "vmid": vmid, "apps": [{"id": "portainer", "name": "Portainer"}],
            "schedule": {"enabled": True, "target": "both"}}))

    def guest(self, vmid, kind="lxc", node="pve1"):
        folder = self.nodes / node / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{vmid}.conf").write_text("arch: amd64\n")

    def test_a_destroyed_guest_loses_its_applications_and_schedule(self):
        self.register(112)
        self.assertIsNotNone(lxc_apps._read_sidecar(112))
        lxc_apps._docker_inventory_cache["112"] = {"containers": ["portainer"]}
        lxc_apps.forget_guest(112)
        self.assertFalse((self.apps / "112.json").exists())
        self.assertIsNone(lxc_apps._read_sidecar(112))
        self.assertNotIn("112", lxc_apps._docker_inventory_cache)

    def test_its_oci_dismissal_is_dropped_and_others_are_kept(self):
        (self.apps / ".oci-dismissed.json").write_text(json.dumps({"112": "old-id", "130": "other-id"}))
        lxc_apps.forget_guest(112)
        self.assertEqual(json.loads((self.apps / ".oci-dismissed.json").read_text()), {"130": "other-id"})

    def test_guests_removed_while_the_monitor_was_stopped_are_forgotten(self):
        for vmid in (112, 113, 200):
            self.register(vmid)
        self.guest(113)
        self.guest(200, kind="qemu-server", node="pve2")
        lxc_apps.forget_missing_guests()
        self.assertEqual(sorted(p.name for p in self.apps.glob("*.json")), ["113.json", "200.json"])

    def test_nothing_is_forgotten_without_the_cluster_filesystem(self):
        self.register(112)
        lxc_apps.forget_missing_guests()
        self.assertTrue((self.apps / "112.json").exists())

    def test_the_task_watcher_publishes_destroy_tasks(self):
        source = (SCRIPTS_DIR / "notification_events.py").read_text()
        self.assertIn("if task_type in ('vzdestroy', 'qmdestroy'):", source)
        self.assertLess(source.index("if task_type in ('vzdestroy', 'qmdestroy'):"),
                        source.index('event_info = self.TASK_MAP.get(task_type)'))

    def test_the_monitor_keeps_the_applications_of_an_oci_operation(self):
        source = (SCRIPTS_DIR / "flask_server.py").read_text()
        self.assertIn("if action == 'destroy' and not _oci_operation_running(guest_id):", source)
        self.assertIn("/run/proxmenux/oci-operations/", source)


if __name__ == "__main__":
    unittest.main()
