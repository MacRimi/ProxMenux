"""Z-Wave JS UI's native OCI profile is safe to start without a radio controller."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

from proxmenux_oci.catalog import Catalog, supported_architectures
import oci_instance_transaction as transaction


class ZWaveJsUIRecipeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog(ROOT)
        self.curated_path = ROOT / "catalog/curated/zwave-js-ui.json"
        self.generated_path = ROOT / "catalog/apps/zwave-js-ui.json"

    def test_generated_template_matches_curated_profile(self):
        self.assertEqual(self.curated_path.read_bytes(), self.generated_path.read_bytes())

    def test_uses_the_official_image_and_only_catalog_supported_architectures(self):
        template = self.catalog.compose("zwave-js-ui")
        self.assertEqual(template["id"], "image-zwave-js-ui")
        self.assertEqual(
            template["container_contract"]["image"]["reference"],
            "docker.io/zwavejs/zwave-js-ui:latest",
        )
        self.assertEqual(
            template["catalog_ui"]["architectures"], ["amd64", "arm64"]
        )
        self.assertEqual(
            supported_architectures(template["catalog_ui"]["architectures"]),
            ["amd64", "arm64"],
        )
        self.assertIn(
            "/c38e0d2cbbb826bf2bab2db596a3452e59ce0e8e/public/apple-touch-icon-180x180.png",
            template["catalog_ui"]["icon"],
        )

    def test_web_ui_is_the_startup_check_when_no_controller_is_attached(self):
        template = self.catalog.compose("zwave-js-ui")
        check = transaction.effective_healthcheck(template)
        self.assertEqual((check["scheme"], check["port"], check["path"]),
                         ("http", 8091, "/"))
        self.assertNotEqual(check["path"], "/health")
        endpoint = template["first_run"]["endpoints"][0]
        self.assertEqual((endpoint["port"], endpoint["path"]), (8091, "/"))
        devices = template["proxmox"]["installer_profile"]["optional_devices"]
        self.assertEqual(len(devices), 1)
        self.assertFalse(devices[0]["enabled_default"])
        self.assertFalse(devices[0]["required_by_compose"])
        self.assertTrue(devices[0]["host_path_default"].startswith("/dev/serial/by-id/"))

    def test_fresh_store_enables_login_and_keeps_generated_credentials_out_of_recipe(self):
        template = self.catalog.compose("zwave-js-ui")
        profile = template["proxmox"]["installer_profile"]
        generated = profile["generated_sensitive_environment"]
        self.assertEqual(generated["SESSION_SECRET"]["bytes"], 32)
        self.assertEqual(generated["DEFAULT_PASSWORD"]["bytes"], 20)
        seeded = next(item for item in profile["generated_files"]
                      if item["container_path"] == "/usr/src/app/store/settings.json")
        self.assertTrue(seeded["only_if_missing"])
        self.assertTrue(seeded["owner"] == "mapped-root")
        self.assertIn('"authEnabled":true', seeded["content"])
        credential = template["first_run"]["credentials"][0]
        self.assertEqual(credential["username"], "admin")
        self.assertIsNone(credential["password"])
        self.assertEqual(credential["password_environment"], "DEFAULT_PASSWORD")
        self.assertNotIn("mysupersecretkey", template["container_contract"]["original_compose"])

    def test_state_is_persisted_on_a_managed_volume(self):
        template = self.catalog.compose("zwave-js-ui")
        volume = template["container_contract"]["volumes"][0]
        self.assertEqual(volume["container_path"], "/usr/src/app/store")
        self.assertEqual(volume["installation_choice"], ["managed-volume"])
        self.assertTrue(volume["managed_volume"]["backup"])
        prep = template["proxmox"]["installer_profile"]["volume_preparations"]
        self.assertEqual(prep[0]["container_path"], "/usr/src/app/store")
        self.assertEqual(prep[0]["owner_strategy"], "mapped-root")

    def test_includes_web_and_optional_zwave_websocket_ports(self):
        template = self.catalog.compose("zwave-js-ui")
        ports = {item["container_port"]: item
                 for item in template["container_contract"]["ports"]}
        self.assertTrue(ports[8091]["required"])
        self.assertFalse(ports[3000]["required"])
        self.assertEqual(ports[8091]["protocol"], "tcp")
        self.assertEqual(ports[3000]["protocol"], "tcp")


if __name__ == "__main__":
    unittest.main()
