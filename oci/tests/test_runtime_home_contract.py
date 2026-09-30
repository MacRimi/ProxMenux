"""Regression tests for the native OCI PID 1 HOME fallback."""

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_runtime  # noqa: E402


class RuntimeHomeResolutionTests(unittest.TestCase):
    def passwd(self, content: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "passwd"
        path.write_text(content, encoding="utf-8")
        return path

    def test_root_home_is_resolved_from_passwd(self):
        passwd = self.passwd("root:x:0:0:root:/root:/bin/sh\n")
        self.assertEqual(oci_runtime.home_directory(passwd, 0), "/root")

    def test_non_root_home_is_resolved_from_passwd(self):
        passwd = self.passwd(
            "root:x:0:0:root:/root:/bin/sh\n"
            "app:x:1001:1001:App user:/srv/app:/sbin/nologin\n"
        )
        self.assertEqual(oci_runtime.home_directory(passwd, 1001), "/srv/app")

    def test_unknown_or_unsafe_home_is_not_invented(self):
        passwd = self.passwd(
            "root:x:0:0:root:relative-home:/bin/sh\n"
            "app:x:1001:1001:App user::/sbin/nologin\n"
        )
        self.assertIsNone(oci_runtime.home_directory(passwd, 0))
        self.assertIsNone(oci_runtime.home_directory(passwd, 1001))
        self.assertIsNone(oci_runtime.home_directory(passwd, 1234))


class RuntimeHomeInstallerContractTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "remote" / "install_oci.sh").read_text(encoding="utf-8")

    def test_explicit_home_is_preserved_and_fallback_uses_effective_uid(self):
        self.assertIn("ensure_runtime_home()", self.source)
        self.assertIn("lxc.environment.runtime: HOME=", self.source)
        self.assertIn('uid=${uid:-0}', self.source)
        self.assertIn('home=$(python3 "$OCI_RUNTIME_RESOLVER" --home', self.source)
        self.assertIn('set_runtime_environment HOME "$home"', self.source)

    def test_home_fallback_runs_after_runtime_user_is_applied(self):
        self.assertIn(
            "apply_extra_hosts\napply_installer_profile\nensure_runtime_home\napply_rlimits",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
