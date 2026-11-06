"""The NVIDIA installer stops under Secure Boot before removing the driver."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / "scripts/gpu_tpu/nvidia_installer.sh").read_text()


def function(name):
    return re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", SOURCE, re.M | re.S).group(0)


class NvidiaSecureBootTests(unittest.TestCase):
    def state(self, payload):
        with tempfile.NamedTemporaryFile() as efivar:
            efivar.write(payload)
            efivar.flush()
            script = f'SECURE_BOOT_EFIVAR="{efivar.name}"\n{function("secure_boot_enabled")}secure_boot_enabled'
            return subprocess.run(["bash", "-c", script]).returncode

    def test_the_firmware_variable_decides(self):
        self.assertEqual(self.state(b"\x06\x00\x00\x00\x01"), 0)
        self.assertEqual(self.state(b"\x06\x00\x00\x00\x00"), 1)

    def test_a_host_without_the_variable_is_not_blocked(self):
        script = f'SECURE_BOOT_EFIVAR="/nonexistent"\n{function("secure_boot_enabled")}secure_boot_enabled'
        self.assertEqual(subprocess.run(["bash", "-c", script]).returncode, 1)

    def test_the_interactive_install_checks_before_removing_the_driver(self):
        main = function("main")
        install = main[main.index("    install)\n"):main.index("    remove)\n")]
        self.assertLess(install.index("check_secure_boot_for_install"), install.index("complete_nvidia_uninstall"))
        self.assertNotIn("check_secure_boot_for_install", main[main.index("    remove)\n"):])

    def test_the_automatic_reinstall_checks_before_removing_the_driver(self):
        reinstall = function("auto_reinstall_from_state")
        self.assertLess(reinstall.index("secure_boot_enabled"), reinstall.index("complete_nvidia_uninstall"))

    def test_an_installer_failure_is_shown_before_leaving(self):
        main = function("main")
        failure = main[main.index('if ! run_nvidia_installer "$installer"; then'):]
        self.assertLess(failure.index("show_nvidia_install_failure"), failure.index("exit 1"))


if __name__ == "__main__":
    unittest.main()
