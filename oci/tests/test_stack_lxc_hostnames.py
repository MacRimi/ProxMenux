"""Stack LXC names use the stack name once and readable dependency suffixes."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import DEFAULT_MODE
from proxmenux_oci.stack import DefaultsUI, build_stack, stack_lxc_hostname


class StackLxcHostnameTests(unittest.TestCase):
    def test_main_service_uses_stack_name_without_repeating_service_name(self):
        self.assertEqual(stack_lxc_hostname("TeslaMate", "teslamate", True), "teslamate")

    def test_database_uses_db_suffix_and_other_services_keep_their_names(self):
        self.assertEqual(stack_lxc_hostname("teslamate", "database"), "teslamate-db")
        self.assertEqual(stack_lxc_hostname("teslamate", "grafana"), "teslamate-grafana")
        self.assertEqual(stack_lxc_hostname("teslamate", "mosquitto"), "teslamate-mosquitto")

    def test_service_already_prefixed_with_stack_name_does_not_repeat_it(self):
        self.assertEqual(stack_lxc_hostname("blinko", "blinko-postgres"), "blinko-postgres")

    def test_teslamate_build_plan_contains_the_expected_proxmox_names(self):
        template = Catalog(ROOT).compose("teslamate")
        with patch("proxmenux_oci.host.default_storage", return_value="local-zfs"), \
             patch("proxmenux_oci.host.default_bridge", return_value="vmbr0"), \
             patch("proxmenux_oci.network.ask_addresses",
                   side_effect=lambda ui, bridge, labels: ({label: "dhcp" for label in labels}, None)), \
             patch("proxmenux_oci.host.timezone", return_value="UTC"):
            result = build_stack(template, DefaultsUI(), DEFAULT_MODE)

        actual = {service["name"]: service["deployment"]["hostname"]
                  for service in result["services"]}
        self.assertEqual(actual, {
            "database": "teslamate-db",
            "grafana": "teslamate-grafana",
            "mosquitto": "teslamate-mosquitto",
            "teslamate": "teslamate",
        })


if __name__ == "__main__":
    unittest.main()
