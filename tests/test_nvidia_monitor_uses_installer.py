"""ProxMenux Monitor announces the NVIDIA driver the installer would recommend,
worked out by the same installer function the version menu uses."""
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "scripts/gpu_tpu/nvidia_installer.sh").read_text()
sys.path.insert(0, str(ROOT / "AppImage/scripts"))

import managed_installs  # noqa: E402


def function(name):
    return re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", INSTALLER, re.M | re.S).group(0)


def answer(stdout, returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, "")


class MonitorAsksTheInstallerTests(unittest.TestCase):
    def setUp(self):
        installer = patch.object(managed_installs, "_NVIDIA_INSTALLER", str(ROOT / "scripts/gpu_tpu/nvidia_installer.sh"))
        installer.start()
        self.addCleanup(installer.stop)

    def check(self, current, stdout, returncode=0):
        with patch.object(managed_installs.subprocess, "run", return_value=answer(stdout, returncode)) as run:
            result = managed_installs._check_nvidia_xfree86({"current_version": current})
        return result, run

    def test_an_older_installer_is_not_run(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".sh") as old:
            old.write("main\n"); old.flush()
            with patch.object(managed_installs, "_NVIDIA_INSTALLER", old.name), \
                    patch.object(managed_installs.subprocess, "run") as run:
                result = managed_installs._check_nvidia_xfree86({"current_version": "595.80"})
        run.assert_not_called()
        self.assertFalse(result["available"])
        self.assertIn("older", result["error"])

    def test_the_recommended_version_is_announced_and_the_host_tools_are_used(self):
        with patch.dict(managed_installs.os.environ, {"LD_LIBRARY_PATH": "/appimage/lib"}):
            result, run = self.check("595.80", "595.112.07\n")
        self.assertEqual((result["available"], result["latest"], result["_upgrade_kind"]),
                         (True, "595.112.07", "patch"))
        argv, kwargs = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(argv[-2:], ["--recommended-version", "595.80"])
        self.assertNotIn("LD_LIBRARY_PATH", kwargs["env"])

    def test_nothing_is_announced_when_the_installer_recommends_the_installed_driver(self):
        result, _ = self.check("580.196.07", "580.196.07\n")
        self.assertEqual((result["available"], result["latest"], result["error"]), (False, None, None))

    def test_nothing_is_announced_when_the_installer_offers_nothing(self):
        # A GPU no maintained branch supports: the installer recommends nothing.
        result, _ = self.check("470.256.02", "")
        self.assertEqual((result["available"], result["error"]), (False, None))

    def test_a_failed_version_list_is_an_error_not_an_update(self):
        result, _ = self.check("595.80", "", returncode=2)
        self.assertFalse(result["available"])
        self.assertIn("could not read", result["error"])

    def test_a_branch_change_is_marked(self):
        result, _ = self.check("570.211.01", "595.112.07\n")
        self.assertEqual(result["_upgrade_kind"], "branch")


class OneCalculationTests(unittest.TestCase):
    def test_the_menu_and_the_monitor_mode_share_the_calculation(self):
        self.assertIn("compute_nvidia_offer", function("show_version_menu"))
        self.assertIn("compute_nvidia_offer", function("print_recommended_version"))
        self.assertNotIn("download.nvidia.com", (ROOT / "AppImage/scripts/managed_installs.py").read_text())

    def test_the_monitor_mode_prints_only_the_recommendation(self):
        stubs = ('detect_nvidia_gpus() { NVIDIA_GPU_PRESENT=true; }\n'
                 'compute_nvidia_offer() { NVIDIA_RECOMMENDED_VERSION="595.112.07"; }\n')
        done = subprocess.run(["bash", "-c", stubs + function("print_recommended_version")
                               + "print_recommended_version 595.80"],
                              capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (0, "595.112.07\n"))


if __name__ == "__main__":
    unittest.main()
