"""A Lynis installed from a package is found and audited, only the copy
ProxMenux installs is removed by it, and reading its version never runs it:
any Lynis run rewrites the report of the last audit."""
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import security_manager  # noqa: E402


class LynisOriginTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.wrapper = self.root / "usr/local/bin/lynis"
        self.clone = self.root / "opt/lynis"
        self.package = self.root / "usr/sbin/lynis"
        paths = (str(self.wrapper), str(self.clone / "lynis"), str(self.package))
        for patch in (mock.patch.object(security_manager, "_LYNIS_PATHS", paths),
                      mock.patch.object(security_manager, "_LYNIS_WRAPPER", str(self.wrapper)),
                      mock.patch.object(security_manager, "_LYNIS_CLONE", str(self.clone)),
                      mock.patch.object(security_manager, "_run_cmd", side_effect=AssertionError("Lynis was run")),
                      mock.patch.object(security_manager, "parse_lynis_report", return_value=None)):
            patch.start()
            self.addCleanup(patch.stop)

    def executable(self, path, text='#!/bin/sh\n    PROGRAM_VERSION="3.1.4"\n'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def test_a_package_lynis_is_found_and_not_managed(self):
        self.executable(self.package)
        self.assertEqual(security_manager._find_lynis_cmd(), str(self.package))
        info = security_manager._detect_lynis()
        self.assertTrue(info["installed"])
        self.assertFalse(info["managed"])
        self.assertEqual(info["version"], "3.1.4")

    def test_a_package_lynis_is_never_uninstalled(self):
        self.executable(self.package)
        package_only = lambda path: path == "/usr/sbin/lynis"
        with mock.patch.object(security_manager.os.path, "exists", side_effect=package_only), \
                mock.patch("shutil.rmtree") as rmtree, mock.patch("os.remove") as remove:
            success, _, partial, outcome = security_manager.uninstall_lynis()
        self.assertEqual((success, partial, outcome), (False, False, "not_managed"))
        rmtree.assert_not_called()
        remove.assert_not_called()
        self.assertTrue(self.package.exists())

    def test_the_copy_proxmenux_installs_is_managed(self):
        self.executable(self.clone / "lynis", '#!/bin/sh\n    PROGRAM_VERSION="3.1.8"\n')
        self.executable(self.wrapper, f"#!/bin/bash\ncd {self.clone} && ./lynis \"$@\"\n")
        self.executable(self.package)
        self.assertEqual(security_manager._find_lynis_cmd(), str(self.wrapper))
        info = security_manager._detect_lynis()
        self.assertTrue(info["managed"])
        # The wrapper has no version line: it is read from the clone.
        self.assertEqual(info["version"], "3.1.8")

    def test_the_wrapper_alone_is_still_the_copy_of_proxmenux(self):
        self.executable(self.wrapper, f"#!/bin/bash\ncd {self.clone} && ./lynis \"$@\"\n")
        self.assertTrue(security_manager._lynis_installed_by_proxmenux())

    def test_the_installer_looks_for_the_package_path(self):
        installer = (SCRIPTS.parents[1] / "scripts/security/lynis_installer.sh").read_text(encoding="utf-8")
        self.assertIn("/usr/sbin/lynis", installer)
        self.assertIn("LYNIS_MANAGED", installer)
        self.assertNotRegex(installer, r'(lynis|LYNIS_CMD)"?\s+show\s+version')


if __name__ == "__main__":
    unittest.main()
