"""The KitchenOwl entry follows the upstream two-service Compose deployment."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.custom import template_from_oci_compose
from proxmenux_oci.stack import assess, build_stack, DefaultsUI
from proxmenux_oci.installer import DEFAULT_MODE

CURATED_PATH = ROOT / "catalog/curated/kitchenowl.json"
APPS_PATH = ROOT / "catalog/apps/kitchenowl.json"


def compile_stack(template):
    """Compile the recipe with deterministic answers, without touching Proxmox."""
    with patch("proxmenux_oci.installer.ask_storage", return_value="local-zfs"), \
         patch("proxmenux_oci.installer.ask_bridge", return_value="vmbr0"), \
         patch("proxmenux_oci.host.timezone", return_value="UTC"), \
         patch("proxmenux_oci.network.ask_addresses",
               side_effect=lambda ui, bridge, labels: ({name: "dhcp" for name in labels}, None)):
        return build_stack(template, DefaultsUI(), DEFAULT_MODE)


class KitchenOwlRecipeTests(unittest.TestCase):
    def setUp(self):
        self.curated = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
        self.generated = json.loads(APPS_PATH.read_text(encoding="utf-8"))
        self.index = json.loads((ROOT / "catalog/index.json").read_text(encoding="utf-8"))
        self.services = {
            service["name"]: service
            for service in self.curated["compose_stack"]["services"]
        }

    def test_curated_and_catalog_templates_match_and_validate(self):
        self.assertEqual(self.curated, self.generated)
        schema = json.loads((ROOT / "schemas/oci-template.schema.json").read_text(encoding="utf-8"))
        validate(self.curated, schema)

    def test_official_compose_is_the_two_image_frontend_backend_stack(self):
        self.assertEqual(set(self.services), {"front", "back"})
        self.assertEqual(self.curated["compose_stack"]["service_count"], 2)
        self.assertEqual(self.curated["compose_stack"]["main_service"], "front")
        self.assertEqual(self.services["front"]["image"], "tombursch/kitchenowl-web:latest")
        self.assertEqual(self.services["back"]["image"], "tombursch/kitchenowl-backend:latest")
        self.assertEqual(self.services["front"]["depends_on"], ["back"])
        self.assertEqual(self.curated["compose_stack"]["orchestration"]["start_order"], ["back", "front"])
        self.assertTrue(self.services["front"]["frontend_network"])
        self.assertTrue(self.services["front"]["private_network"])
        self.assertFalse(self.services["back"]["frontend_network"])
        self.assertTrue(self.services["back"]["private_network"])
        self.assertNotIn("postgres", self.services)
        self.assertNotIn("redis", self.services)

    def test_frontend_uses_the_official_backend_alias_and_port(self):
        # BACK_URL is inherited from the official web image (back:5000); leaving
        # the override absent preserves the image default and Compose service alias.
        self.assertNotIn("BACK_URL", self.services["front"]["compose"].get("environment", {}))
        image_policy = self.curated["proxmox"]["image_metadata_policy"]
        self.assertEqual(image_policy["environment"], "import-image-env-then-apply-compose-overrides")
        self.assertEqual(self.curated["container_contract"]["ports"][0]["container_port"], 80)

    def test_backend_data_and_generated_jwt_key_are_preserved_safely(self):
        back = self.services["back"]["compose"]
        self.assertEqual(back["volumes"][0]["target"], "/data")
        self.assertEqual(back["environment"]["JWT_SECRET_KEY"], "${GENERATED_JWT_SECRET_KEY}")
        self.assertNotIn("PLEASE_CHANGE_ME", json.dumps(back))
        secret = self.curated["compose_stack"]["installer_inputs"]["generated_secrets"]
        self.assertEqual(len(secret), 1)
        self.assertEqual(secret[0]["bindings"], [{"service": "back", "environment_variable": "JWT_SECRET_KEY"}])
        volume = next(v for v in self.curated["compose_stack"]["storage"] if v["service"] == "back")
        self.assertEqual(volume["container_path"], "/data")
        self.assertEqual(volume["mode"], "managed-volume")
        self.assertTrue(volume["user_selectable"])
        self.assertTrue(volume["backup"])

    def test_image_healthchecks_and_first_run_setup_are_recorded(self):
        self.assertIn("uwsgi_curl localhost:5000 /api/health/", str(self.services["back"]["compose"]["healthcheck"]))
        self.assertIn("curl -f http://localhost/", str(self.services["front"]["compose"]["healthcheck"]))
        self.assertEqual(self.curated["first_run"]["endpoints"][0]["port"], 80)
        self.assertEqual(self.curated["first_run"]["credentials"], [])
        self.assertTrue(self.curated["proxmox"]["stack_completion_notes"])

    def test_candidate_passes_stack_assessment_and_round_trips_through_catalog_reader(self):
        catalog = Catalog(ROOT)
        template = catalog.compose("kitchenowl")
        self.assertEqual(assess(template), [])
        self.assertEqual(template["compose_stack"]["project_name"], "kitchenowl")
        reloaded = template_from_oci_compose(json.dumps(template))
        expected = dict(template)
        # Reading a pasted/shared recipe deliberately resets trust status; the
        # catalog reapplies laboratory verification only for its own entry.
        expected["status"] = "generated-unvalidated"
        self.assertEqual(reloaded, expected)

    def test_compiled_plan_keeps_private_backend_health_and_persistent_data(self):
        template = Catalog(ROOT).compose("kitchenowl")
        plan = compile_stack(template)
        self.assertEqual(plan["stack_name"], "kitchenowl")
        self.assertEqual(plan["network"]["private_allocation"], "automatic")
        self.assertEqual(plan["network"]["private_bridge"], "vmbr10")

        services = {service["name"]: service for service in plan["services"]}
        self.assertEqual(list(services), ["back", "front"])
        back = services["back"]
        front = services["front"]
        self.assertIn("back", back["aliases"])
        self.assertIn("front", front["aliases"])
        self.assertNotIn("frontend", back)
        self.assertTrue(front["frontend"])

        backend_health = back["healthcheck"]
        self.assertEqual(backend_health["type"], "exec")
        self.assertEqual(backend_health["timeout_seconds"], 189)
        self.assertIn("uwsgi_curl", backend_health["argv"][-1])
        frontend_health = front["healthcheck"]
        self.assertEqual(frontend_health["type"], "exec")
        self.assertEqual(frontend_health["timeout_seconds"], 99)
        self.assertIn("curl -f http://localhost/", frontend_health["argv"][-1])
        self.assertEqual(frontend_health["endpoint"], {"scheme": "http", "port": 80, "path": "/"})

        self.assertEqual([mount["container_path"] for mount in back["deployment"]["mounts"]], ["/data"])
        self.assertEqual(back["deployment"]["mounts"][0]["type"], "managed-volume")
        self.assertTrue(back["deployment"]["mounts"][0]["backup"])
        self.assertEqual(front["deployment"]["mounts"], [])
        preparation = back["template"]["proxmox"]["installer_profile"]["volume_preparations"]
        self.assertEqual(preparation[0]["container_path"], "/data")
        self.assertEqual(preparation[0]["only_when_mount_type"], "managed-volume")
        self.assertEqual(template["compose_stack"]["storage"][0]["service"], "back")
        self.assertFalse(template["compose_stack"]["storage"][0]["shared_with_other_lxc"])

    def test_icon_architectures_and_unvalidated_status_are_accurate(self):
        ui = self.curated["catalog_ui"]
        self.assertEqual(ui["icon"], "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/kitchenowl.webp")
        self.assertEqual(ui["architectures"], ["amd64", "arm64"])
        self.assertEqual(self.curated["status"], "generated-unvalidated")
        self.assertFalse(self.curated["compatibility"]["validated"])
        entry = next(app for app in self.index["applications"] if app["id"] == "kitchenowl")
        self.assertEqual(entry["template"], "apps/kitchenowl.json")
        self.assertTrue(entry["multi_container"])
        self.assertEqual(entry["category"], "productivity")


if __name__ == "__main__":
    unittest.main()
