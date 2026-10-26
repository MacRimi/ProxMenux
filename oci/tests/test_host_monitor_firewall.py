"""The host-monitor firewall plan is opt-in and bound to its selected bridge."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess
import json


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

from proxmenux_oci.installer import (InstallError, confirm_host_monitor_firewall,
                                     host_monitor_firewall_plan)
import oci_remove


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
    def test_netdata_declares_its_host_web_port_for_the_firewall_plan(self):
        catalog = json.loads((ROOT / "catalog" / "overlays" / "netdata.json").read_text(encoding="utf-8"))
        profile = catalog["proxmox"]["installer_profile"]
        self.assertEqual(profile["host_monitor"], "netdata")
        self.assertEqual(profile["host_monitor_firewall"],
                         {"protocol": "tcp", "web_port": 19999})

    def test_remote_installer_revalidates_and_uses_proxmox_rule_api(self):
        source = (ROOT / "remote" / "install_oci.sh").read_text(encoding="utf-8")
        self.assertIn("validate_host_monitor_firewall", source)
        self.assertIn("The host-monitor firewall subnet changed; no firewall rule was added", source)
        self.assertIn('pvesh create "/nodes/${node}/firewall/rules"', source)
        self.assertIn("--dport \"$HOST_FIREWALL_PORT\" --source \"$HOST_FIREWALL_SOURCE\"", source)
        self.assertIn('--enable 1 --comment "$comment"', source)
        self.assertIn("only the original, separately confirmed installation", source)
        self.assertIn('comment="ProxMenux OCI firewall ${INSTANCE_ID}"', source)
        self.assertIn('if ! pvesh create "/nodes/${node}/firewall/rules"', source)

    def test_removal_only_targets_a_uniquely_owned_firewall_rule(self):
        source = (ROOT / "remote" / "oci_remove.py").read_text(encoding="utf-8")
        self.assertIn("def remove_owned_host_firewall(record):", source)
        self.assertIn("ProxMenux OCI firewall {installation_id}", source)
        self.assertIn("len(matches) != 1", source)
        self.assertIn("firewall/rules/{matches[0]['pos']}", source)

    def test_removal_deletes_only_the_exact_rule_owned_by_the_installation(self):
        record = {"installation_id": "123e4567-e89b-12d3-a456-426614174000",
                  "deployment": {"host_firewall": {"source": "192.0.2.0/24", "port": 61208}}}
        rules = [{"pos": 7, "comment": "ProxMenux OCI firewall 123e4567-e89b-12d3-a456-426614174000",
                  "type": "in", "action": "ACCEPT", "proto": "tcp", "source": "192.0.2.0/24",
                  "dport": "61208"},
                 {"pos": 8, "comment": "manual rule", "type": "in", "action": "ACCEPT",
                  "proto": "tcp", "source": "192.0.2.0/24", "dport": "61208"}]
        with patch("oci_remove.subprocess.run", side_effect=[
                CompletedProcess([], 0, json.dumps(rules), ""), CompletedProcess([], 0, "", "")]) as run:
            oci_remove.remove_owned_host_firewall(record)
        self.assertIn("/firewall/rules/7", run.call_args_list[1].args[0][-1])

    def test_removal_keeps_an_unowned_matching_rule(self):
        record = {"installation_id": "123e4567-e89b-12d3-a456-426614174000",
                  "deployment": {"host_firewall": {"source": "192.0.2.0/24", "port": 61208}}}
        rules = [{"pos": 8, "comment": "manual rule", "type": "in", "action": "ACCEPT",
                  "proto": "tcp", "source": "192.0.2.0/24", "dport": "61208"}]
        with patch("oci_remove.subprocess.run", return_value=CompletedProcess([], 0, json.dumps(rules), "")) as run:
            oci_remove.remove_owned_host_firewall(record)
        run.assert_called_once()

    def test_oci_menu_wrapper_does_not_hide_engine_errors_with_the_main_menu(self):
        wrapper = (ROOT.parent / "scripts" / "oci" / "oci_manager_apps.sh").read_text(encoding="utf-8")
        self.assertIn('OCI_STATUS=$?', wrapper)
        self.assertIn('exit "$OCI_STATUS"', wrapper)


if __name__ == "__main__":
    unittest.main()
