"""Keep the native Krusader OCI profile aligned with its upstream image."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog


class KrusaderRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.curated = json.loads(
            (ROOT / "catalog/curated/krusader.json").read_text(encoding="utf-8")
        )
        cls.app = json.loads(
            (ROOT / "catalog/apps/krusader.json").read_text(encoding="utf-8")
        )
        cls.template = Catalog(ROOT).compose("krusader")

    def test_catalog_copy_matches_curated_profile(self):
        self.assertEqual(self.curated, self.app)

    def test_upstream_image_and_manifest_architectures_are_recorded(self):
        contract = self.curated["container_contract"]
        self.assertEqual(contract["image"]["reference"], "jlesage/krusader:latest")
        self.assertEqual(self.curated["source"]["provider"], "jlesage")
        self.assertEqual(self.curated["catalog_ui"]["architectures"], ["amd64", "arm64"])

    def test_web_gui_uses_authenticated_https_and_does_not_expose_vnc(self):
        env = {
            entry["name"]: entry.get("example")
            for entry in self.template["container_contract"]["environment"]
        }
        self.assertEqual(env["WEB_AUTHENTICATION"], "1")
        self.assertEqual(env["SECURE_CONNECTION"], "1")
        self.assertEqual(env["VNC_LOCALHOST_ONLY"], "1")
        self.assertEqual(
            self.template["catalog_ui"]["launch"],
            {"scheme": "https", "port": 5800, "path": "/"},
        )
        self.assertEqual(
            [port["container_port"] for port in self.template["container_contract"]["ports"]],
            [5800],
        )
        credential = self.template["first_run"]["credentials"][0]
        self.assertEqual(credential["username"], "admin")
        self.assertEqual(credential["password_environment"], "WEB_AUTHENTICATION_PASSWORD")
        self.assertIn(
            "WEB_AUTHENTICATION_PASSWORD",
            self.template["proxmox"]["installer_profile"]["generated_sensitive_environment"],
        )

    def test_only_config_and_selected_storage_are_persistent(self):
        volumes = {
            volume["container_path"]: volume
            for volume in self.template["container_contract"]["volumes"]
        }
        self.assertEqual(set(volumes), {"/config", "/storage"})
        self.assertEqual(volumes["/config"]["installation_choice"], ["managed-volume"])
        self.assertEqual(volumes["/storage"]["installation_choice"], ["managed-volume", "host-bind"])
        self.assertEqual(volumes["/storage"]["default"], "host-bind")
        self.assertTrue(all(volume["managed_volume"]["backup"] for volume in volumes.values()))
        self.assertEqual(volumes["/config"]["managed_volume"]["default_size_gb"], 4)
        compose = self.template["compose_stack"]["services"][0]["compose"]
        self.assertEqual(compose["image"], "jlesage/krusader:latest")

    def test_storage_directory_offers_host_bind_with_the_image_user_identity(self):
        profile = self.template["proxmox"]["installer_profile"]
        storage = next(
            item for item in self.template["container_contract"]["volumes"]
            if item["container_path"] == "/storage"
        )
        compose_storage = next(
            item for item in self.template["compose_stack"]["storage"]
            if item["container_path"] == "/storage"
        )

        self.assertEqual(storage["installation_choice"], ["managed-volume", "host-bind"])
        self.assertEqual(storage["default"], "host-bind")
        self.assertTrue(compose_storage["user_selectable"])
        self.assertEqual(compose_storage["mode"], "user-selectable")
        self.assertEqual(
            compose_storage["installation_choice"], ["managed-volume", "host-bind"]
        )
        self.assertEqual(
            profile["volume_owner"], {"uid": 1000, "gid": 1000}
        )
        self.assertEqual(
            {entry["name"]: entry["example"] for entry in self.template["container_contract"]["environment"]}
            ["USER_ID"],
            "1000",
        )
        self.assertEqual(
            {entry["name"]: entry["example"] for entry in self.template["container_contract"]["environment"]}
            ["GROUP_ID"],
            "1000",
        )

    def test_partial_live_evidence_does_not_mark_app_as_fully_verified(self):
        self.assertEqual(
            self.curated["validation"]["clean_install"], "passed-first-start"
        )
        self.assertEqual(
            self.curated["validation"]["service_health"],
            "passed-login-page-and-authenticated-session-http-200",
        )
        self.assertEqual(
            self.curated["validation"]["credentials"],
            "passed-generated-password-login-and-session-cookie",
        )
        self.assertEqual(
            self.curated["validation"]["web_authentication"],
            "passed-generated-credential-post-and-session-cookie",
        )
        self.assertEqual(
            self.curated["validation"]["restart_persistence"],
            "passed-container-restart-and-host-bind-write-check",
        )
        self.assertEqual(
            self.curated["validation"]["browser_visual"],
            "pending-self-signed-certificate-review",
        )
        self.assertEqual(self.curated["validation"]["backup_restore"], "pending")
        self.assertEqual(self.curated["validation"]["update_preserves_data"], "pending")
        self.assertEqual(self.curated["status"], "generated-unvalidated")
        self.assertFalse(self.curated["compatibility"]["validated"])


if __name__ == "__main__":
    unittest.main()
