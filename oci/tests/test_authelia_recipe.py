"""The Authelia profile bootstraps a usable single-image authentication portal."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog


class AutheliaRecipeTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "catalog/curated/authelia.json"
        self.recipe = json.loads(self.path.read_text(encoding="utf-8"))
        self.index_copy = json.loads(
            (ROOT / "catalog/apps/authelia.json").read_text(encoding="utf-8")
        )
        self.profile = self.recipe["proxmox"]["installer_profile"]
        self.generated = {
            item["container_path"]: item
            for item in self.profile["generated_files"]
        }

    def test_local_catalog_lists_and_loads_the_curated_recipe(self):
        catalog = Catalog(ROOT)
        item = catalog.find_item("authelia")
        self.assertEqual(item["template_family"], "curated-profile")
        self.assertEqual(catalog.compose("authelia")["id"], "image-authelia")
        self.assertEqual(self.recipe, self.index_copy)

    def test_official_image_tag_icon_and_supported_architectures_are_declared(self):
        self.assertEqual(
            self.recipe["container_contract"]["image"]["reference"],
            "docker.io/authelia/authelia:4.39.28",
        )
        self.assertEqual(self.recipe["catalog_ui"]["architectures"], ["amd64", "arm64"])
        self.assertEqual(
            self.recipe["catalog_ui"]["icon"],
            "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/authelia.webp",
        )

    def test_sensitive_secrets_are_generated_and_domain_settings_are_prompted(self):
        environment = {
            item["name"]: item
            for item in self.recipe["container_contract"]["environment"]
        }
        for name in (
            "PROXMENUX_ADMIN_PASSWORD",
            "AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET",
            "AUTHELIA_SESSION_SECRET",
            "AUTHELIA_STORAGE_ENCRYPTION_KEY",
        ):
            self.assertTrue(environment[name]["sensitive"])
            self.assertEqual(self.profile["generated_sensitive_environment"][name]["strategy"], "token-hex")
        self.assertTrue(environment["PROXMENUX_AUTHELIA_COOKIE_DOMAIN"]["required"])
        self.assertTrue(environment["PROXMENUX_AUTHELIA_URL"]["required"])
        self.assertIn("cookie domain", environment["PROXMENUX_AUTHELIA_COOKIE_DOMAIN"]["prompt"])
        self.assertIn("HTTPS URL", environment["PROXMENUX_AUTHELIA_URL"]["prompt"])
        self.assertEqual(environment["PROXMENUX_AUTHELIA_COOKIE_DOMAIN"]["example"], "")
        self.assertEqual(environment["PROXMENUX_AUTHELIA_URL"]["example"], "")
        self.assertEqual(environment["X_AUTHELIA_CONFIG_FILTERS"]["example"], "template")

    def test_config_is_persistent_and_has_a_working_initial_policy(self):
        config = self.generated["/config/configuration.yml"]["content"]
        self.assertIn("path: '/config/users_database.yml'", config)
        self.assertIn("path: '/config/db.sqlite3'", config)
        self.assertIn("filename: '/config/notification.txt'", config)
        self.assertIn("default_policy: 'one_factor'", config)
        self.assertIn('{{ env \"PROXMENUX_AUTHELIA_COOKIE_DOMAIN\" }}', config)
        self.assertIn('{{ env \"PROXMENUX_AUTHELIA_URL\" }}', config)
        self.assertTrue(self.generated["/config/configuration.yml"]["only_if_missing"])
        volume = self.recipe["container_contract"]["volumes"][0]
        self.assertEqual(volume["container_path"], "/config")
        self.assertEqual(volume["installation_choice"], ["managed-volume"])
        self.assertTrue(volume["managed_volume"]["backup"])

    def test_bootstrap_hashes_initial_password_and_never_ships_a_default_password(self):
        bootstrap = self.generated["/usr/local/bin/proxmenux-authelia-bootstrap"]["content"]
        self.assertIn("authelia crypto hash generate argon2", bootstrap)
        self.assertIn("unset PROXMENUX_ADMIN_PASSWORD", bootstrap)
        self.assertIn("exec /app/entrypoint.sh", bootstrap)
        self.assertNotIn("password: authelia", bootstrap)
        self.assertEqual(
            self.recipe["first_run"]["credentials"][0]["password_environment"],
            "PROXMENUX_ADMIN_PASSWORD",
        )

    def test_healthcheck_uses_authelias_documented_endpoint_and_profile_remains_unvalidated(self):
        healthcheck = self.profile["startup_healthcheck"]
        self.assertEqual((healthcheck["port"], healthcheck["path"]), (9091, "/api/health"))
        self.assertFalse(self.recipe["compatibility"]["validated"])
        self.assertEqual(self.recipe["status"], "generated-unvalidated")


if __name__ == "__main__":
    unittest.main()
