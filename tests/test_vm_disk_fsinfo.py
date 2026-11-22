"""VM disk usage from the QEMU guest agent counts each filesystem once."""
import ast
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "AppImage/scripts"


def compute():
    tree = ast.parse((SCRIPTS / "flask_server.py").read_text())
    nodes = [node for node in tree.body
             if (isinstance(node, ast.FunctionDef) and node.name == "_compute_vm_disk_from_fsinfo")
             or (isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "_VM_FS_SKIP_TYPES" for t in node.targets))]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "flask_server.py", "exec"), namespace)
    return namespace["_compute_vm_disk_from_fsinfo"]


def fs(mountpoint, name, total, used, **disk):
    return {"mountpoint": mountpoint, "name": name, "type": "ext4", "total-bytes": total,
            "used-bytes": used, "disk": [{"bus": 0, "target": 0, "unit": 0, **disk}]}


class VmDiskFromFsinfo(unittest.TestCase):
    def test_partitions_of_one_disk_without_dev_are_all_counted(self):
        # Alpine's agent reports no `dev`: /boot and / share the disk fields.
        result = compute()([fs("/boot", "sda1", 264371200, 29093888), fs("/", "sda3", 27736297472, 6119866368)])
        self.assertEqual(result, (29093888 + 6119866368, 264371200 + 27736297472))

    def test_bind_mounts_of_one_filesystem_are_counted_once(self):
        mounts = [fs(path, "sda8", 1000, 400, dev="/dev/sda8") for path in ("/mnt/data", "/etc/hosts", "/var/lib/docker")]
        self.assertEqual(compute()(mounts), (400, 1000))


if __name__ == "__main__":
    unittest.main()
