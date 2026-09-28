"""A migrated container finds what it needs on any node of a cluster."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_console
import oci_runtime_settings as runtime_settings

DEPLOYMENT = {"security": {"sysctls": [{"name": "net.ipv4.ip_unprivileged_port_start", "value": "0"}]}}


class StartHookTests(unittest.TestCase):
    def test_hook_creates_the_log_directory_before_liblxc_opens_it(self):
        hook = oci_console.start_mark_hook(101)
        self.assertTrue(hook.startswith("lxc.hook.pre-start: /bin/sh -c 'mkdir -p /var/log/proxmenux/oci; "))
        self.assertIn("test -x", hook)
        self.assertTrue(hook.endswith("101; exit 0'"))
        self.assertNotIn("[", hook)

    def test_hook_runs_the_installed_engine_not_the_installer_copy(self):
        # The installer runs from a temporary copy that is removed afterwards.
        self.assertIn("test -x /usr/local/share/proxmenux/oci/engine/remote/oci_console_mark.sh && ",
                      oci_console.start_mark_hook(101))
        self.assertTrue((ROOT / "remote/oci_console_mark.sh").is_file())


class SysctlIncludeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        content = runtime_settings.sysctl_content(DEPLOYMENT)
        self.new = self.root / "proxmenux/101.sysctls"
        self.old = self.root / "lxc/101.proxmenux-sysctls"
        for path in (self.new, self.old):
            path.parent.mkdir(parents=True)
            path.write_text(content)
            path.chmod(0o640)
        for name, value in (("include_path", lambda vmid: self.new), ("legacy_include_path", lambda vmid: self.old)):
            patcher = patch.object(runtime_settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def config(self, include):
        return f"arch: amd64\nlxc.include: {include}\n".encode()

    def test_cluster_path_and_the_path_of_earlier_installs_are_accepted(self):
        runtime_settings.check(self.config(self.new), DEPLOYMENT, 101)
        runtime_settings.check(self.config(self.old), DEPLOYMENT, 101)

    def test_any_other_include_is_refused(self):
        with self.assertRaises(ValueError):
            runtime_settings.check(self.config(self.root / "elsewhere"), DEPLOYMENT, 101)

    def test_recovery_accepts_both_paths_only(self):
        state = {"vmid": 101, "record": {"deployment": DEPLOYMENT}}
        runtime_settings.check_recovery(self.config(self.new), state)
        runtime_settings.check_recovery(self.config(self.old), state)
        with self.assertRaises(ValueError):
            runtime_settings.check_recovery(self.config(self.root / "elsewhere"), state)

    def test_restore_writes_the_cluster_path(self):
        self.new.unlink()
        self.new.parent.rmdir()
        runtime_settings.restore(DEPLOYMENT, 101)
        self.assertEqual(self.new.read_text(), runtime_settings.sysctl_content(DEPLOYMENT))

    def test_the_cluster_folder_is_shared_by_every_node(self):
        self.assertEqual(runtime_settings.CLUSTER_DIR, Path("/etc/pve/proxmenux"))
        self.assertNotIn(Path("/etc/pve/lxc"), runtime_settings.CLUSTER_DIR.parents)


if __name__ == "__main__":
    unittest.main()
