"""The host-monitor firewall plan is opt-in and bound to its selected bridge."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.installer import (InstallError, confirm_host_monitor_firewall,
                                     host_monitor_firewall_plan)


class ConfirmUI:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def confirm(self, text, default=False):
        self.prompts.append((text, default))
        return self.answer


def template(declared={"protocol": "tcp", "web_port": 61208}):
    profile = {} if declared is None else {"host_monitor_firewall": declared}
    return {"proxmox": {"installer_profile": profile}}


class HostMonitorFirewallPlanTests(unittest.TestCase):
    @patch("proxmenux_oci.installer.host.ipv4_subnet", return_value="192.0.2.0/24")
    def test_uses_selected_bridge_subnet_and_declared_port(self, subnet):
        plan = host_monitor_firewall_plan(template(), "vmbr7")
        self.assertEqual(plan, {"bridge": "vmbr7", "source": "192.0.2.0/24",
                                "protocol": "tcp", "port": 61208, "confirmed": True})
        subnet.assert_called_once_with("vmbr7")

    @patch("proxmenux_oci.installer.host.ipv4_subnet", return_value="198.51.100.0/25")
    def test_confirmation_displays_scope_and_declines_without_plan(self, _subnet):
        ui = ConfirmUI(False)
        self.assertIsNone(confirm_host_monitor_firewall(ui, template(), "vmbr3"))
        self.assertFalse(ui.prompts[0][1])
        self.assertIn("vmbr3", ui.prompts[0][0])
        self.assertIn("198.51.100.0/25", ui.prompts[0][0])
        self.assertIn("61208", ui.prompts[0][0])

    @patch("proxmenux_oci.installer.host.ipv4_subnet", return_value=None)
    def test_refuses_to_guess_a_subnet(self, _subnet):
        with self.assertRaises(InstallError):
            host_monitor_firewall_plan(template(), "vmbr0")

    def test_undeclared_profiles_never_offer_a_firewall_change(self):
        self.assertIsNone(host_monitor_firewall_plan(template(None), "vmbr0"))


class HostMonitorFirewallInstallerContractTests(unittest.TestCase):
    def test_remote_installer_revalidates_and_uses_proxmox_rule_api(self):
        source = (ROOT / "remote" / "install_oci.sh").read_text(encoding="utf-8")
        self.assertIn("validate_host_monitor_firewall", source)
        self.assertIn("The host-monitor firewall subnet changed; no firewall rule was added", source)
        self.assertIn('pvesh create "/nodes/${node}/firewall/rules"', source)
        self.assertIn("--dport \"$HOST_FIREWALL_PORT\" --source \"$HOST_FIREWALL_SOURCE\"", source)
        self.assertIn("only the original, separately confirmed installation", source)

    def test_oci_menu_wrapper_does_not_hide_engine_errors_with_the_main_menu(self):
        wrapper = (ROOT.parent / "scripts" / "oci" / "oci_manager_apps.sh").read_text(encoding="utf-8")
        self.assertIn('OCI_STATUS=$?', wrapper)
        self.assertIn('exit "$OCI_STATUS"', wrapper)


if __name__ == "__main__":
    unittest.main()
