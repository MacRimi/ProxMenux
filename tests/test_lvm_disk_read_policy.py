"""Automatic LVM readers must not bypass disk exclusions/idle policy."""
import ast
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "AppImage/scripts"
sys.path.insert(0, str(SCRIPTS))
import lvm_device_scope as scope

INVENTORY = "nvme0n1 disk\nnvme0n1p1 part nvme0n1\nsda disk\nsda1 part sda\nsdb disk\nsdb1 part sdb\n"


class LvmScopeTests(unittest.TestCase):
    def setUp(self):
        self.policy = Mock(side_effect=lambda disk, excluded: "excluded" if disk in excluded else "read")
        self.standby = Mock(return_value=False)
        self.excluded = {"sda"}
        self.disk_module = types.ModuleType("disk_temperature_history")
        self.disk_module.disk_read_policy = self.policy
        self.disk_module.excluded_disk_names = lambda: self.excluded
        self.modules = patch.dict(sys.modules, disk_temperature_history=self.disk_module)
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def args(self, inventory=INVENTORY, code=0):
        with patch.object(scope.subprocess, "run", return_value=types.SimpleNamespace(returncode=code, stdout=inventory)) as run:
            args = scope.lvm_device_args(self.standby)
        self.assertEqual(run.call_args.args[0], ["lsblk", "-rno", "NAME,TYPE,PKNAME"])
        return args

    def test_excluded_disks_and_their_partitions_are_not_in_the_scan(self):
        self.assertEqual(self.args(), ["--devices", "/dev/nvme0n1,/dev/nvme0n1p1,/dev/sdb,/dev/sdb1"])
        self.assertNotIn((("sda",), {}), self.standby.call_args_list)
        self.assertEqual({call.args[0] for call in self.standby.call_args_list}, {"nvme0n1", "sdb"})

    def test_idle_disks_receive_no_power_query(self):
        self.excluded = set()
        self.policy.side_effect = lambda disk, excluded: "idle" if disk == "sda" else "read"
        self.assertNotIn("/dev/sda", self.args()[1])
        self.assertEqual({call.args[0] for call in self.standby.call_args_list}, {"nvme0n1", "sdb"})

    def test_a_standby_disk_is_excluded_even_when_its_io_changed(self):
        self.excluded = set()
        self.standby.side_effect = lambda disk: disk == "sdb"
        self.assertEqual(self.args(), ["--devices", "/dev/nvme0n1,/dev/nvme0n1p1,/dev/sda,/dev/sda1"])

    def test_all_allowed_disks_keep_existing_scan_behaviour(self):
        self.excluded = set()
        self.assertEqual(self.args(), [])

    def test_all_blocked_disks_skip_instead_of_falling_back_to_full_scan(self):
        self.excluded = {"nvme0n1", "sda", "sdb"}
        self.assertIsNone(self.args())
        self.standby.assert_not_called()

    def test_all_standby_disks_skip(self):
        self.excluded = set()
        self.standby.return_value = True
        self.assertIsNone(self.args())

    def test_bad_inventory_or_policy_never_authorizes_an_unrestricted_scan(self):
        for inventory, code in (("", 0), (INVENTORY, 1), ("sda1 part sda", 0), ("../sda disk", 0)):
            self.assertIsNone(self.args(inventory, code))
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("lsblk", 5)):
            with patch.object(scope.subprocess, "run", side_effect=error):
                self.assertIsNone(scope.lvm_device_args(self.standby))
        self.policy.side_effect = RuntimeError("policy unavailable")
        self.assertIsNone(self.args())


class LvmReaderTests(unittest.TestCase):
    def extract(self, file, name, owner=None, namespace=None):
        tree = ast.parse((SCRIPTS / file).read_text())
        body = tree.body if owner is None else next(n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
        node = next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == name)
        namespace = dict(namespace or {})
        exec(compile(ast.Module(body=[node], type_ignores=[]), file, "exec"), namespace)
        return namespace[name]

    def test_both_helpers_delegate_to_the_same_policy(self):
        for file in ("flask_server.py", "health_monitor.py"):
            standby = Mock()
            function = self.extract(file, "_lvm_device_args", namespace={"_hdd_in_standby": standby})
            with patch.object(scope, "lvm_device_args", return_value=None) as shared:
                self.assertIsNone(function())
            shared.assert_called_once_with(standby)

    def test_health_skips_lvs_and_vgs_when_no_scan_is_permitted(self):
        run = Mock(return_value=types.SimpleNamespace(returncode=0))
        function = self.extract("health_monitor.py", "_check_lvm", "HealthMonitor", {
            "Dict": dict, "Any": object, "subprocess": types.SimpleNamespace(run=run), "_lvm_device_args": lambda: None,
        })
        result = function(None)
        self.assertEqual(result["status"], "INFO")
        self.assertTrue(result["skipped"])
        self.assertEqual([call.args[0] for call in run.call_args_list], [["which", "lvs"]])

    def test_storage_skips_pvs_when_no_scan_is_permitted(self):
        tree = ast.parse((SCRIPTS / "flask_server.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_system_disks")
        block = next(node for node in function.body if isinstance(node, ast.Try) and "'pvs'" in ast.unparse(node))
        run = Mock(side_effect=AssertionError("pvs must not run"))
        namespace = {"subprocess": types.SimpleNamespace(run=run), "_lvm_device_args": lambda: None}
        exec(compile(ast.Module(body=[block], type_ignores=[]), "flask_server.py", "exec"), namespace)
        run.assert_not_called()

    def test_module_is_shipped(self):
        self.assertIn('cp "$SCRIPT_DIR/lvm_device_scope.py" "$APP_DIR/usr/bin/"', (SCRIPTS / "build_appimage.sh").read_text())


if __name__ == "__main__":
    unittest.main()
