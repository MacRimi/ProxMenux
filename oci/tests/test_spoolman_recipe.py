"""Spoolman uses its upstream single-image SQLite deployment in OCI Manager."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import DEFAULT_MODE, build_deployment


class StorageChoiceUI:
    def __init__(self, volume_mode):
        self.volume_mode = volume_mode

    def choose(self, _prompt, options, default=None, **_kwargs):
        available = {key for key, _label in options}
        if self.volume_mode not in available:
            raise AssertionError(f"{self.volume_mode} was not offered; got {available}")
        return self.volume_mode

    def ask(self, _prompt, default="", **_kwargs):
        return default

    def confirm(self, _prompt, default=False):
        return default

    def message(self, *_args, **_kwargs):
        pass


class SpoolmanRecipeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog(ROOT)
        self.recipe = self.catalog.compose("spoolman")
        self.generated = json.loads(
            (ROOT / "catalog/apps/spoolman.json").read_text(encoding="utf-8")
        )
        self.curated = json.loads(
            (ROOT / "catalog/curated/spoolman.json").read_text(encoding="utf-8")
        )

    def test_generated_and_curated_recipes_match(self):
        self.assertEqual(self.generated, self.curated)

    def test_official_image_and_catalog_architectures_match_engine_support(self):
        image = self.recipe["container_contract"]["image"]
        self.assertEqual(image["reference"], "ghcr.io/donkie/spoolman:latest")
        self.assertEqual(image["registry"], "ghcr.io")
        self.assertEqual(image["repository"], "ghcr.io/donkie/spoolman")
        # The OCI catalog currently supports amd64 and arm64. The upstream
        # manifest also has arm/v7, which the current catalog engine does not
        # offer as an installable architecture.
        self.assertEqual(self.recipe["catalog_ui"]["architectures"], ["amd64", "arm64"])
        self.assertEqual(
            self.recipe["source"]["image_repository_url"],
            "https://github.com/Donkie/Spoolman/pkgs/container/spoolman",
        )

    def test_sqlite_is_the_default_and_no_database_service_is_required(self):
        contract = self.recipe["container_contract"]
        self.assertEqual(self.recipe["compose_stack"]["service_count"], 1)
        self.assertEqual(self.recipe["compose_stack"]["services"][0]["image"],
                         "ghcr.io/donkie/spoolman:latest")
        self.assertEqual(contract["related_services"], [])
        env_names = {item["name"] for item in contract["environment"]}
        self.assertNotIn("SPOOLMAN_DB_TYPE", env_names)
        self.assertNotIn("SPOOLMAN_DB_NAME", env_names)
        self.assertNotIn("SPOOLMAN_DIR_DATA", env_names)
        data_path = "/home/app/.local/share/spoolman"
        self.assertEqual([volume["container_path"] for volume in contract["volumes"]],
                         [data_path])
        self.assertIn("SQLite", self.recipe["catalog_ui"]["tagline"]["en_US"])

    def test_web_launch_and_first_start_healthcheck_use_container_port_8000(self):
        self.assertEqual(self.recipe["container_contract"]["ports"][0]["container_port"], 8000)
        self.assertEqual(self.recipe["catalog_ui"]["launch"]["port"], 8000)
        self.assertEqual(self.recipe["first_run"]["endpoints"][0]["port"], 8000)
        health = self.recipe["proxmox"]["installer_profile"]["startup_healthcheck"]
        self.assertEqual((health["scheme"], health["port"], health["path"]),
                         ("http", 8000, "/"))
        self.assertIn("7912:8000", self.recipe["container_contract"]["original_compose"])

    def test_persistent_data_volume_and_application_uid_are_declared(self):
        path = "/home/app/.local/share/spoolman"
        volume = self.recipe["container_contract"]["volumes"][0]
        policy = json.loads(
            (ROOT / "catalog/volume-policy.json").read_text(encoding="utf-8")
        )
        self.assertIn(path, policy["applications"]["spoolman"])
        self.assertEqual(volume["installation_choice"], ["managed-volume", "host-bind"])
        self.assertEqual(volume["default"], "managed-volume")
        preparation = self.recipe["proxmox"]["installer_profile"]["volume_preparations"][0]
        self.assertEqual(preparation["container_path"], path)
        self.assertEqual(preparation["owner_strategy"], "mapped-application-user")
        self.assertEqual(preparation["only_when_mount_type"], "managed-volume")
        self.assertEqual(self.recipe["proxmox"]["installer_profile"]["volume_owner"],
                         {"uid": 1000, "gid": 1000})

    def test_default_install_preserves_data_for_both_storage_choices(self):
        for mode in ("managed-volume", "host-bind"):
            with self.subTest(mode=mode):
                with patch("proxmenux_oci.installer.ask_storage",
                           return_value="local-zfs"), \
                     patch("proxmenux_oci.installer.host.default_bridge",
                           return_value="vmbr0"), \
                     patch("proxmenux_oci.installer.host.timezone",
                           return_value="UTC"), \
                     patch("proxmenux_oci.installer.access.ask_ipv4",
                           return_value=("dhcp", None)):
                    plan = build_deployment(
                        self.recipe, StorageChoiceUI(mode), DEFAULT_MODE
                    )

                self.assertEqual(len(plan["mounts"]), 1)
                mount = plan["mounts"][0]
                self.assertEqual(mount["container_path"],
                                 "/home/app/.local/share/spoolman")
                self.assertEqual(mount["type"], mode)
                self.assertFalse(mount["read_only"])
                if mode == "managed-volume":
                    self.assertEqual(mount["source"], "local-zfs")
                    self.assertEqual(mount["size_gb"], 4)
                    self.assertTrue(mount["backup"])
                else:
                    self.assertEqual(
                        mount["source"],
                        "/mnt/oci-shared/spoolman/home-app-local-share-spoolman",
                    )
                    self.assertIsNone(mount["size_gb"])
                    self.assertFalse(mount["backup"])


if __name__ == "__main__":
    unittest.main()
