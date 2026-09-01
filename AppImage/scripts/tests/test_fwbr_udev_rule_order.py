import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
AUTO_POST_INSTALL = REPO_ROOT / "scripts/post_install/auto_post_install.sh"
CUSTOM_POST_INSTALL = REPO_ROOT / "scripts/post_install/customizable_post_install.sh"
UNINSTALL_TOOLS = REPO_ROOT / "scripts/post_install/uninstall-tools.sh"

OLD_RULE = "99-proxmenux-fwbr-tune.rules"
NEW_RULE = "99-zz-proxmenux-fwbr-tune.rules"
SYSTEMD_RULE = "99-systemd.rules"


def network_optimization_block(path: Path) -> str:
    source = path.read_text()
    start = source.index("apply_network_optimizations()")
    end = source.index('register_tool "network_optimization"', start)
    return source[start:end]


class FwbrUdevRuleOrderTests(unittest.TestCase):
    def test_new_rule_sorts_after_systemd_rule(self):
        self.assertGreater(NEW_RULE, SYSTEMD_RULE)

    def test_auto_post_install_uses_late_rule_and_removes_legacy_rule(self):
        source = network_optimization_block(AUTO_POST_INSTALL)
        self.assertIn('local FUNC_VERSION="1.2"', source)
        self.assertIn(f"rm -f /etc/udev/rules.d/{OLD_RULE}", source)
        self.assertIn(f"cat > /etc/udev/rules.d/{NEW_RULE}", source)
        self.assertIn(f"chmod 0644 /etc/udev/rules.d/{NEW_RULE}", source)
        self.assertNotIn(f"cat > /etc/udev/rules.d/{OLD_RULE}", source)

    def test_customizable_post_install_uses_late_rule_and_removes_legacy_rule(self):
        source = network_optimization_block(CUSTOM_POST_INSTALL)
        self.assertIn('local FUNC_VERSION="1.2"', source)
        self.assertIn(f"rm -f /etc/udev/rules.d/{OLD_RULE}", source)
        self.assertIn(f"cat > /etc/udev/rules.d/{NEW_RULE}", source)
        self.assertIn(f"chmod 0644 /etc/udev/rules.d/{NEW_RULE}", source)
        self.assertNotIn(f"cat > /etc/udev/rules.d/{OLD_RULE}", source)

    def test_uninstall_removes_new_and_legacy_rule_names(self):
        source = UNINSTALL_TOOLS.read_text()
        self.assertIn(f"/etc/udev/rules.d/{OLD_RULE}", source)
        self.assertIn(f"/etc/udev/rules.d/{NEW_RULE}", source)


if __name__ == "__main__":
    unittest.main()
