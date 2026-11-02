"""Guard the Unbound catalog contract against upstream image behavior."""

import json
from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

from proxmenux_oci.catalog import Catalog
import oci_instance_transaction


class UnboundRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.curated = json.loads((ROOT / "catalog/curated/unbound.json").read_text(encoding="utf-8"))
        cls.app = json.loads((ROOT / "catalog/apps/unbound.json").read_text(encoding="utf-8"))
        cls.composed = Catalog(ROOT).compose("unbound")
        cls.index = json.loads((ROOT / "catalog/index.json").read_text(encoding="utf-8"))
        cls.index_entry = next(item for item in cls.index["applications"] if item["id"] == "unbound")
        cls.original_compose = yaml.safe_load(cls.curated["container_contract"]["original_compose"])

    def test_both_catalog_templates_and_image_metadata_match_upstream(self):
        self.assertEqual(self.curated, self.app)
        image = self.curated["container_contract"]["image"]
        self.assertEqual(image["reference"], "klutchell/unbound:main")
        self.assertEqual(image["registry"], "docker.io")
        self.assertEqual(image["repository"], "klutchell/unbound")
        self.assertEqual(image["tag"], "main")
        self.assertIsNone(image["digest"])  # resolve the selected tag for each host architecture at install time
        self.assertEqual(
            image["pull_policy"],
            "resolve-selected-tag-to-architecture-digest-at-install",
        )
        self.assertEqual(
            self.curated["source"]["repository"],
            "https://github.com/klutchell/unbound-docker",
        )
        self.assertEqual(
            self.curated["source"]["revision"],
            "1efbea960bf9462b6fb6dd71aa702ad32d6820d7",
        )

    def test_icon_and_supported_architectures_are_in_both_catalog_views(self):
        icon = "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/unbound.webp"
        self.assertEqual(self.curated["catalog_ui"]["icon"], icon)
        self.assertEqual(self.index_entry["icon"], icon)
        self.assertEqual(self.index_entry["template_id"], "image-unbound")
        # The upstream manifest has amd64, arm64, arm/v7 and arm/v6. The catalog
        # normalizes the two 32-bit ARM variants to armhf; the install index
        # only lists the architectures currently supported by ProxMenux.
        self.assertEqual(self.curated["catalog_ui"]["architectures"], ["amd64", "arm64", "armhf"])
        self.assertEqual(self.index_entry["architectures"], ["amd64", "arm64"])

    def test_dns_listener_publishes_tcp_and_udp_53(self):
        expected = {("tcp", 53), ("udp", 53)}
        contract_ports = {
            (port["protocol"], port["container_port"])
            for port in self.curated["container_contract"]["ports"]
        }
        self.assertEqual(contract_ports, expected)

        original = self.original_compose["services"]["unbound"]
        self.assertEqual(set(original["ports"]), {"53:53/tcp", "53:53/udp"})
        profile_service = self.curated["compose_stack"]["services"][0]["compose"]
        self.assertEqual(set(profile_service["ports"]), {"53:53/tcp", "53:53/udp"})

    def test_upstream_entrypoint_is_preserved_and_health_uses_running_fallback(self):
        image_policy = self.curated["proxmox"]["image_metadata_policy"]
        self.assertEqual(image_policy["entrypoint"], "import-from-oci-image")
        self.assertEqual(image_policy["cmd"], "import-from-oci-image")

        # Upstream Dockerfile sets ENTRYPOINT ["unbound"] and no HEALTHCHECK.
        # Preserve the image command; check process stability on install/update,
        # then verify DNS answers separately with a query to port 53.
        for service in (self.original_compose["services"]["unbound"],
                        self.curated["compose_stack"]["services"][0]["compose"]):
            self.assertNotIn("entrypoint", service)
            self.assertNotIn("command", service)
            self.assertNotIn("healthcheck", service)
        self.assertEqual(self.curated["catalog_ui"]["launch"]["port"], None)
        self.assertEqual(self.curated["first_run"]["endpoints"], [])
        check = self.composed["proxmox"]["installer_profile"]["startup_healthcheck"]
        self.assertEqual(check, {"type": "running", "timeout_seconds": 90, "stability_seconds": 20})
        self.assertEqual(oci_instance_transaction.effective_healthcheck(self.composed), check)

    def test_custom_configuration_mount_is_persistent_and_exposes_both_storage_modes(self):
        path = "/etc/unbound/custom.conf.d"
        volume = next(v for v in self.curated["container_contract"]["volumes"]
                      if v["container_path"] == path)
        self.assertFalse(volume["read_only"])
        self.assertFalse(volume["required"])
        self.assertEqual(volume["installation_choice"], ["managed-volume", "host-bind"])
        self.assertEqual(volume["default"], "host-bind")
        self.assertTrue(volume["managed_volume"]["backup"])

        original_service = self.original_compose["services"]["unbound"]
        self.assertIn("./config:/etc/unbound/custom.conf.d", original_service["volumes"])
        profile_service = self.curated["compose_stack"]["services"][0]["compose"]
        self.assertIn("./config:/etc/unbound/custom.conf.d", profile_service["volumes"])

        storage = next(v for v in self.curated["compose_stack"]["storage"]
                       if v["container_path"] == path)
        self.assertEqual(storage["mode"], "user-selectable")
        self.assertEqual(storage["installation_choice"], ["managed-volume", "host-bind"])
        self.assertTrue(storage["backup"])

        prepared = next(v for v in self.composed["proxmox"]["installer_profile"]["volume_preparations"]
                        if v["container_path"] == path)
        self.assertEqual(prepared["owner_strategy"], "mapped-application-user")

    def test_dns_service_remains_unprivileged_and_data_is_not_misrepresented_as_web_ui(self):
        self.assertTrue(self.curated["proxmox"]["defaults"]["unprivileged"])
        self.assertFalse(self.index_entry["requires_privileged_lxc"])
        self.assertEqual(self.curated["catalog_ui"]["launch"]["port"], None)
        self.assertTrue(any("no web interface" in tip.casefold()
                            for tip in self.curated["catalog_ui"]["tips"]))
        self.assertTrue(any("do not expose recursive dns publicly" in tip.casefold()
                            for tip in self.curated["catalog_ui"]["tips"]))


if __name__ == "__main__":
    unittest.main()
