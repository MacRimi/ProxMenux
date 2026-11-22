import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_runtime_settings


class PowerDNSRecursorProfileTest(unittest.TestCase):
    def test_dns_port_is_available_to_the_non_root_image_only_inside_its_unprivileged_lxc(self):
        curated = json.loads((ROOT / "catalog/curated/pdns-recursor.json").read_text())
        app = json.loads((ROOT / "catalog/apps/pdns-recursor.json").read_text())

        expected_sysctls = [{
            "name": "net.ipv4.ip_unprivileged_port_start",
            "value": "53",
        }]
        self.assertEqual(
            curated["proxmox"]["installer_profile"]["security"]["sysctls"],
            expected_sysctls,
        )
        self.assertEqual(
            app["proxmox"]["installer_profile"]["security"]["sysctls"],
            expected_sysctls,
        )
        self.assertTrue(curated["proxmox"]["defaults"]["unprivileged"])
        self.assertNotIn(
            "required_capabilities",
            curated["proxmox"]["installer_profile"].get("security", {}),
        )
        self.assertEqual(
            oci_runtime_settings.sysctl_content({"security": {"sysctls": expected_sysctls}}),
            "lxc.sysctl.net.ipv4.ip_unprivileged_port_start = 53\n",
        )
        self.assertEqual(
            oci_runtime_settings.include_path(111),
            Path("/etc/pve/proxmenux/111.sysctls"),
        )
        installer = (ROOT / "remote/install_oci.sh").read_text()
        self.assertIn('SYSCTL_INCLUDE="/etc/pve/proxmenux/${VMID}.sysctls"', installer)
        self.assertIn('set_lxc_directive "lxc.include" "$SYSCTL_INCLUDE"', installer)
        self.assertEqual(curated["compatibility"]["validated"], False)
        self.assertEqual(curated["validation"]["clean_install"], "pending")
        self.assertEqual(curated, app)


if __name__ == "__main__":
    unittest.main()
