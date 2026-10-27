"""Static install contracts for the next OCI catalog profiles."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


PROFILES = {
    "chhoto-url": {
        "image": "sintan1729/chhoto-url:latest",
        "data_path": "/data",
        "port": 4567,
        "health_path": "/",
    },
    "openhabittracker": {
        "image": "jinjinov/openhabittracker:latest",
        "data_path": "/app/.OpenHabitTracker",
        "port": 8080,
        "health_path": "/login",
    },
    "watcharr": {
        "image": "ghcr.io/sbondco/watcharr:latest",
        "data_path": "/data",
        "port": 3080,
        "health_path": "/",
    },
    "ech0": {
        "image": "sn0wl1n/ech0:latest",
        "data_path": "/app/data",
        "port": 6277,
        "health_path": "/",
    },
    "restic-rest-server": {
        "image": "restic/rest-server:latest",
        "data_path": "/data",
        "port": 8000,
        "health_path": "/",
    },
}


def load_profile(app_id):
    path = ROOT / "catalog" / "apps" / f"{app_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class Next10BProfiles(unittest.TestCase):
    def test_each_profile_is_one_image_with_an_icon_and_persistent_data(self):
        for app_id, expected in PROFILES.items():
            with self.subTest(app=app_id):
                profile = load_profile(app_id)
                services = profile["compose_stack"]["services"]
                image = profile["container_contract"]["image"]["reference"]

                self.assertEqual(profile["compose_stack"]["service_count"], 1)
                self.assertEqual(len(services), 1)
                self.assertEqual(services[0]["image"], expected["image"])
                self.assertEqual(image, expected["image"])
                self.assertEqual(services[0]["depends_on"], [])

                icon = profile["catalog_ui"].get("icon")
                self.assertIsInstance(icon, str)
                self.assertTrue(icon.startswith("https://"), icon)

                mount_paths = {
                    volume["container_path"]
                    for volume in profile["container_contract"]["volumes"]
                }
                self.assertIn(expected["data_path"], mount_paths)

    def test_each_profile_has_a_matching_first_start_check(self):
        for app_id, expected in PROFILES.items():
            with self.subTest(app=app_id):
                profile = load_profile(app_id)
                check = profile["proxmox"]["installer_profile"]["startup_healthcheck"]

                self.assertEqual(check["scheme"], "http")
                self.assertEqual(check["port"], expected["port"])
                self.assertEqual(check["path"], expected["health_path"])
                self.assertTrue(check["accept_any_status"])

    def test_chhoto_url_uses_generated_password_and_data_database(self):
        profile = load_profile("chhoto-url")
        environment = {
            item["name"]: item
            for item in profile["container_contract"]["environment"]
        }
        generated = profile["proxmox"]["installer_profile"]["generated_sensitive_environment"]
        credential = profile["first_run"]["credentials"][0]

        self.assertIn("CHHOTO_PASSWORD", environment)
        self.assertTrue(environment["CHHOTO_PASSWORD"]["sensitive"])
        self.assertIn("CHHOTO_PASSWORD", generated)
        self.assertEqual(credential["password_environment"], "CHHOTO_PASSWORD")
        self.assertEqual(environment["CHHOTO_DB_URL"]["example"], "/data/urls.sqlite")
        self.assertEqual(environment["CHHOTO_SQLITE_USE_WAL_MODE"]["example"], "True")

    def test_openhabittracker_prompts_for_user_and_generates_password_and_jwt(self):
        profile = load_profile("openhabittracker")
        environment = {
            item["name"]: item
            for item in profile["container_contract"]["environment"]
        }
        generated = profile["proxmox"]["installer_profile"]["generated_sensitive_environment"]
        credential = profile["first_run"]["credentials"][0]

        self.assertIn("prompt", environment["AppSettings__UserName"])
        self.assertIn("prompt", environment["AppSettings__Email"])
        self.assertIn("AppSettings__Password", generated)
        self.assertIn("AppSettings__JwtSecret", generated)
        self.assertEqual(credential["username_environment"], "AppSettings__UserName")
        self.assertEqual(credential["password_environment"], "AppSettings__Password")

    def test_watcharr_first_registered_user_becomes_admin(self):
        profile = load_profile("watcharr")
        credentials = profile["first_run"]["credentials"]

        self.assertEqual(profile["container_contract"]["environment"], [])
        self.assertEqual(len(credentials), 1)
        self.assertIn("administrator", credentials[0]["label"].lower())
        self.assertIn("first-run setup", credentials[0]["username"].lower())

    def test_ech0_generates_jwt_and_marks_first_user_as_owner(self):
        profile = load_profile("ech0")
        generated = profile["proxmox"]["installer_profile"]["generated_sensitive_environment"]
        credentials = profile["first_run"]["credentials"]

        self.assertIn("JWT_SECRET", generated)
        self.assertEqual(profile["container_contract"]["environment"][0]["name"], "JWT_SECRET")
        self.assertEqual(len(credentials), 1)
        self.assertIn("Owner", credentials[0]["label"])
        self.assertIn("first-run setup", credentials[0]["username"].lower())

    def test_restic_server_is_an_api_without_a_browser_endpoint(self):
        profile = load_profile("restic-rest-server")
        credentials = profile["first_run"]["credentials"]
        ui = profile["catalog_ui"]

        self.assertEqual(profile["first_run"]["endpoints"], [])
        self.assertIsNone(ui["launch"]["port"])
        self.assertIn("no web interface", ui["tagline"]["en_US"].lower())
        self.assertIn("not a browser-based application", ui["description"]["en_US"].lower())
        self.assertEqual(len(credentials), 1)
        self.assertIn("create_user", credentials[0]["username"])
        self.assertIsNone(credentials[0]["password"])
        self.assertEqual(
            profile["container_contract"]["environment"][0]["example"],
            "--private-repos",
        )


if __name__ == "__main__":
    unittest.main()
