"""The installed applications of a node are the containers it hosts: one
migrated to another node of the cluster is listed there, not here."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

from proxmenux_oci import management
import oci_instances as instances


def record(vmid):
    return {"vmid": vmid, "status": "installed", "deployment": {"hostname": f"app-{vmid}"}, "template": {}}


class LocalNodeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "instances"
        self.configs = Path(folder.name) / "lxc"
        self.root.mkdir()
        self.configs.mkdir()
        for vmid in range(101, 108):
            (self.root / str(vmid)).mkdir()
        # Only two of the seven stayed on this node.
        for vmid in (101, 104):
            (self.configs / f"{vmid}.conf").write_text(f"hostname: app-{vmid}\n")
        patches = [patch.object(instances, "ROOT", self.root),
                   patch.object(instances, "has_contract", return_value=True),
                   patch.object(instances, "read", side_effect=lambda root, vmid: record(vmid)),
                   patch.object(instances, "guest_exists", return_value=True)]
        original = management.on_this_node
        patches.append(patch.object(management, "on_this_node",
                                    side_effect=lambda vmid: original(vmid, self.configs)))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_the_saved_list_shows_only_the_containers_of_this_node(self):
        rows = management.saved_inventory(ROOT)
        self.assertEqual([row["vmid"] for row in rows], [101, 104])

    def test_the_checked_list_shows_only_the_containers_of_this_node(self):
        decisions = [{"vmid": vmid, "action": "keep"} for vmid in range(101, 108)]
        with patch.object(instances, "command", return_value=b"[]"), \
                patch.object(instances, "reconcile", return_value=decisions):
            rows = management.inventory(ROOT)
        self.assertEqual([row["vmid"] for row in rows], [101, 104])

    def test_the_records_of_the_migrated_containers_are_kept(self):
        management.saved_inventory(ROOT)
        self.assertEqual(sorted(int(path.name) for path in self.root.iterdir() if path.name.isdecimal()), list(range(101, 108)))


if __name__ == "__main__":
    unittest.main()
