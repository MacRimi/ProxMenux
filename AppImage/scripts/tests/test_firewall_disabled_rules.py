"""A rule disabled in Proxmox ("|IN ...") is listed, edited and deleted under
the same index, and editing it keeps it disabled."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import security_manager  # noqa: E402

HOST_FW = """[OPTIONS]
enable: 1

[RULES]
IN ACCEPT -p tcp -dport 22 -log nolog
|IN DROP -p tcp -dport 80 -log nolog
IN ACCEPT -p tcp -dport 8006 -log nolog
"""


class DisabledFirewallRuleTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.host_fw = Path(folder.name) / "host.fw"
        self.host_fw.write_text(HOST_FW)
        for name, value in (("HOST_FW_DIR", folder.name), ("CLUSTER_FW", str(Path(folder.name) / "none.fw"))):
            patcher = mock.patch.object(security_manager, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(security_manager, "_pve_firewall_apply", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rules(self):
        return security_manager._parse_firewall_rules()

    def test_disabled_rule_is_parsed_with_its_direction_and_action(self):
        rules = self.rules()
        self.assertEqual([r["rule_index"] for r in rules], [0, 1, 2])
        self.assertEqual((rules[1]["direction"], rules[1]["action"], rules[1]["disabled"]), ("IN", "DROP", True))
        self.assertFalse(rules[0]["disabled"])

    def test_deleting_after_a_disabled_rule_hits_the_listed_rule(self):
        target = self.rules()[2]
        ok, _ = security_manager.delete_firewall_rule(target["rule_index"])
        self.assertTrue(ok)
        self.assertNotIn("8006", self.host_fw.read_text())
        self.assertIn("|IN DROP", self.host_fw.read_text())

    def test_editing_a_disabled_rule_keeps_it_disabled(self):
        ok, _ = security_manager.edit_firewall_rule(1, direction="IN", action="DROP", protocol="tcp", dport="81")
        self.assertTrue(ok)
        lines = self.host_fw.read_text().splitlines()
        self.assertTrue(any(line.startswith("|IN DROP -p tcp -dport 81") for line in lines))
        self.assertIn("IN ACCEPT -p tcp -dport 8006 -log nolog", lines)


if __name__ == "__main__":
    unittest.main()
