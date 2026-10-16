"""Manual console launcher and its install/uninstall wiring.

Run: python3 -m unittest discover -s tests -p test_console_installer.py -v
Requires Bash. The launcher runs with a restricted PATH that holds only a fake
`id`; AppRun is a fake that records its argv (NUL-separated, exact bytes).
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/console/proxmenux-console"
INSTALLERS = ("install_proxmenux.sh", "install_proxmenux_beta.sh")
CONFIG_MENU = "scripts/menus/config_menu.sh"
INSTALL_LINE = re.compile(
    r'^\s*install -m 0755 "\$TEMP_DIR/scripts/console/proxmenux-console" /usr/local/bin/proxmenux-console$',
    re.M)
REMOVE_LINE = re.compile(r'^\s*pmx_remove_file "/usr/local/bin/proxmenux-console"$', re.M)


def function(path, name):
    text = (ROOT / path).read_text()
    match = re.search(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}", text, re.M | re.S)
    assert match, (path, name)
    return match[0]


class Launcher(unittest.TestCase):
    def run_launcher(self, uid, args=(), apprun_exists=True, apprun_executable=True):
        with tempfile.TemporaryDirectory(prefix="pmx-console-") as tmp:
            tmp = Path(tmp)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            fake_id = bin_dir / "id"
            fake_id.write_text(f"#!/bin/sh\necho {uid}\n")
            fake_id.chmod(0o755)
            apprun = tmp / "AppRun"
            if apprun_exists:
                # ${0%/*} instead of dirname: PATH holds only the fake id.
                apprun.write_text(
                    r"""#!/bin/sh
printf '%s\0' "$@" > "${0%/*}/argv"
""")
                apprun.chmod(0o755 if apprun_executable else 0o644)
            env = {"PATH": str(bin_dir), "PMX_CONSOLE_LAUNCHER": str(apprun)}
            result = subprocess.run(["/bin/bash", "--noprofile", "--norc", str(LAUNCHER), *args],
                                    env=env, text=True, capture_output=True, timeout=10)
            argv_file = tmp / "argv"
            argv = argv_file.read_bytes().split(b"\0")[:-1] if argv_file.exists() else None
            return result, argv

    def test_non_root_is_refused_before_apprun(self):
        result, argv = self.run_launcher(uid=1000, args=("x",))
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be run as root", result.stderr)
        self.assertIsNone(argv)

    def test_root_execs_apprun_with_tui_then_exact_args(self):
        args = ("--foo", "two words", "")
        result, argv = self.run_launcher(uid=0, args=args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv, [b"--tui", b"--foo", b"two words", b""])

    def test_missing_apprun_reports_monitor_not_installed(self):
        result, argv = self.run_launcher(uid=0, apprun_exists=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ProxMenux Monitor is not installed", result.stderr)
        self.assertIsNone(argv)

    def test_non_executable_apprun_is_refused(self):
        result, argv = self.run_launcher(uid=0, apprun_executable=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ProxMenux Monitor is not installed", result.stderr)
        self.assertIsNone(argv)


class InstallerWiring(unittest.TestCase):
    def test_installers_copy_launcher_in_monitor_install(self):
        for name in INSTALLERS:
            with self.subTest(installer=name):
                body = function(name, "install_proxmenux_monitor")
                matches = list(INSTALL_LINE.finditer(body))
                self.assertEqual(len(matches), 1)
                line = matches[0].start()
                extract = body.index('extract_appimage_to_runtime_dir "$target_path"')
                service = body.index('if [ "$service_exists" = false ]')
                self.assertLess(extract, line)
                self.assertLess(line, service)

    def test_uninstall_paths_remove_launcher(self):
        monitor = function(CONFIG_MENU, "uninstall_proxmenux_monitor")
        self.assertRegex(monitor, REMOVE_LINE)
        full = function(CONFIG_MENU, "uninstall_proxmenu")
        self.assertRegex(full, REMOVE_LINE)
        self.assertLess(REMOVE_LINE.search(full).start(), full.index('rm -rf "$BASE_DIR"'))


if __name__ == "__main__":
    unittest.main()
