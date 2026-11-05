"""Guard the Activepieces, Bytebase, Metabase and Kopia OCI recipes."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

EXPECTED = {
    "activepieces": {
        "image": "ghcr.io/activepieces/activepieces:latest",
        "icon": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/activepieces.webp",
        "health": (80, "/api/v1/health"),
        "note_terms": ("personal", "memory"),
    },
    "bytebase": {
        "image": "bytebase/bytebase:latest",
        "icon": "https://cdn.jsdelivr.net/gh/bytebase/bytebase@main/frontend/src/assets/logo-icon.svg",
        "health": (8080, "/healthz"),
        "note_terms": (),
    },
    "metabase": {
        "image": "metabase/metabase:v0.64-lts",
        "icon": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/metabase.webp",
        "health": (3000, "/api/health"),
        "note_terms": ("h2", "postgres"),
    },
    "kopia": {
        "image": "kopia/kopia:latest",
        "icon": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/kopia.webp",
        "health": (51515, "/"),
        "note_terms": ("repository", "password"),
    },
}


def read_profile(family, app):
    path = ROOT / "catalog" / family / f"{app}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class Next10CProfileTests(unittest.TestCase):
    def test_image_single_service_and_icon_match_catalog_contract(self):
        for app, expected in EXPECTED.items():
            with self.subTest(app=app):
                for family in ("apps", "curated"):
                    profile = read_profile(family, app)
                    stack = profile["compose_stack"]
                    service = stack["services"][0]
                    self.assertEqual(
                        profile["container_contract"]["image"]["reference"],
                        expected["image"],
                    )
                    self.assertEqual(stack["service_count"], 1)
                    self.assertEqual(len(stack["services"]), 1)
                    self.assertEqual(service["image"], expected["image"])
                    self.assertEqual(service["compose"]["image"], expected["image"])
                    self.assertEqual(profile["catalog_ui"]["icon"], expected["icon"])
                    self.assertTrue(expected["icon"].startswith("https://"))

    def test_startup_healthcheck_targets_the_documented_service_endpoint(self):
        for app, expected in EXPECTED.items():
            with self.subTest(app=app):
                for family in ("apps", "curated"):
                    profile = read_profile(family, app)
                    health = profile["proxmox"]["installer_profile"][
                        "startup_healthcheck"
                    ]
                    self.assertEqual(health["port"], expected["health"][0])
                    self.assertEqual(health["path"], expected["health"][1])
                    self.assertEqual(health["scheme"], "http")

    def test_required_persistent_paths_are_mounted_by_the_single_service(self):
        for app in EXPECTED:
            with self.subTest(app=app):
                for family in ("apps", "curated"):
                    profile = read_profile(family, app)
                    contract_paths = {
                        volume["container_path"]
                        for volume in profile["container_contract"]["volumes"]
                        if volume.get("required", False)
                    }
                    mounts = profile["compose_stack"]["services"][0]["compose"].get(
                        "volumes", []
                    )
                    mounted_paths = {
                        mount.split(":")[1]
                        for mount in mounts
                        if len(mount.split(":")) >= 2
                    }
                    self.assertTrue(contract_paths, "profile must declare persistent data")
                    self.assertTrue(
                        contract_paths.issubset(mounted_paths),
                        f"required paths missing from Compose mounts: "
                        f"{sorted(contract_paths - mounted_paths)}",
                    )

    def test_secret_environment_is_sensitive_generated_and_wired_to_compose(self):
        for app in EXPECTED:
            with self.subTest(app=app):
                for family in ("apps", "curated"):
                    profile = read_profile(family, app)
                    declared_sensitive = {
                        item["name"]
                        for item in profile["container_contract"].get("environment", [])
                        if item.get("sensitive")
                    }
                    runtime_generated = profile["proxmox"]["installer_profile"].get(
                        "generated_sensitive_environment", {}
                    )
                    generated_bindings = {
                        binding["environment_variable"]
                        for secret in profile["compose_stack"]["installer_inputs"].get(
                            "generated_secrets", []
                        )
                        for binding in secret.get("bindings", [])
                    }
                    compose_environment = profile["compose_stack"]["services"][0][
                        "compose"
                    ].get("environment", {})

                    if app == "bytebase":
                        self.assertEqual(generated_bindings, set())
                        self.assertEqual(runtime_generated, {})
                        self.assertNotIn("HBOX_AUTH_API_KEY_PEPPER", declared_sensitive)
                        self.assertNotIn("HBOX_AUTH_API_KEY_PEPPER", compose_environment)
                        self.assertNotIn("homebox", json.dumps(profile).casefold())
                        continue

                    self.assertTrue(
                        generated_bindings,
                        "profile must document generated credentials/secrets",
                    )
                    self.assertEqual(
                        generated_bindings,
                        set(runtime_generated),
                        "generated secret bindings and runtime generators must match",
                    )
                    self.assertTrue(
                        generated_bindings.issubset(declared_sensitive),
                        "every generated secret must be declared sensitive in the contract",
                    )
                    for variable in generated_bindings:
                        self.assertIn(variable, compose_environment)
                        self.assertIn(variable, str(compose_environment[variable]))

    def test_app_notes_explain_the_key_limitations_or_setup_requirements(self):
        for app, expected in EXPECTED.items():
            with self.subTest(app=app):
                for family in ("apps", "curated"):
                    profile = read_profile(family, app)
                    if app == "bytebase":
                        endpoints = profile["first_run"]["endpoints"]
                        web_ui = next(
                            endpoint for endpoint in endpoints
                            if endpoint["label"] == "Web UI"
                        )
                        self.assertEqual(web_ui["scheme"], "http")
                        self.assertEqual(web_ui["port"], 8080)
                        self.assertEqual(web_ui["path"], "/")
                        self.assertEqual(profile["first_run"]["credentials"], [])
                        self.assertEqual(
                            profile["catalog_ui"]["documentation"],
                            "https://docs.bytebase.com/get-started/self-host/deploy-with-docker",
                        )
                        continue

                    tips = profile["catalog_ui"].get("tips", [])
                    note = " ".join(tips).casefold()
                    self.assertTrue(tips, "profile must include app-specific notes")
                    for term in expected["note_terms"]:
                        self.assertIn(term, note)


if __name__ == "__main__":
    unittest.main()
