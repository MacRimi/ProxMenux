"""Guard the Campfire recipe contract in the next-10 catalog profiles."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_IMAGE = "ghcr.io/awsomefox/campfire:latest"
EXPECTED_ICON = (
    "https://raw.githubusercontent.com/AwsomeFox/campfire/main/"
    "apps/web/public/pwa-512x512.png"
)


class CampfireProfileTests(unittest.TestCase):
    def test_app_and_curated_profiles_match_the_single_service_contract(self):
        for family in ("apps", "curated"):
            with self.subTest(family=family):
                template = json.loads(
                    (ROOT / "catalog" / family / "campfire.json")
                    .read_text(encoding="utf-8")
                )

                contract = template["container_contract"]
                stack = template["compose_stack"]
                self.assertEqual(contract["image"]["reference"], EXPECTED_IMAGE)
                self.assertEqual(stack["service_count"], 1)
                self.assertEqual(len(stack["services"]), 1)
                service = stack["services"][0]
                self.assertEqual(service["image"], EXPECTED_IMAGE)
                self.assertEqual(service["compose"]["image"], EXPECTED_IMAGE)

                volume_paths = {
                    volume["container_path"] for volume in contract["volumes"]
                }
                self.assertIn("/data", volume_paths)
                self.assertIn("./data-0:/data", service["compose"]["volumes"])

                setup = next(
                    endpoint for endpoint in template["first_run"]["endpoints"]
                    if endpoint["label"] == "Campfire first-run setup"
                )
                self.assertEqual(setup["path"], "/auth/setup")

                healthcheck = template["proxmox"]["installer_profile"][
                    "startup_healthcheck"
                ]
                self.assertEqual(healthcheck["path"], "/readyz")

                self.assertEqual(template["catalog_ui"]["icon"], EXPECTED_ICON)


if __name__ == "__main__":
    unittest.main()
