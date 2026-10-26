"""Some images are only the application and expect a database that is already
running. The installation says so before its first question, with the address
of the image documentation, and asks for the connection in plain words."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci import i18n
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import external_services_notice


def asked_without_a_proposal(template):
    return [item["name"] for item in template["container_contract"]["environment"]
            if item["required"] and item["name"] not in ("PUID", "PGID", "TZ")
            and not item["sensitive"] and item.get("example") in (None, "")]


class ExternalServicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.language, i18n._language = getattr(i18n, "_language", None), "en"
        cls.catalog = Catalog(ROOT)

    @classmethod
    def tearDownClass(cls):
        i18n._language = cls.language

    def test_the_notice_names_the_services_and_the_image_documentation(self):
        notice = external_services_notice(self.catalog.compose("manyfold"))
        self.assertIn("Manyfold needs these external services, already running: Redis/Valkey", notice)
        self.assertIn("ProxMenux does not install them", notice)
        self.assertIn("https://docs.linuxserver.io/images/docker-manyfold/", notice)

    def test_an_application_that_needs_nothing_else_has_no_notice(self):
        self.assertIsNone(external_services_notice(self.catalog.compose("duplicati")))
        self.assertIsNone(external_services_notice(self.catalog.compose("lychee")))

    def test_every_connection_question_says_what_it_asks_for(self):
        for app in ("manyfold", "bookstack", "netbox"):
            template = self.catalog.compose(app)
            self.assertTrue(external_services_notice(template), app)
            for item in template["container_contract"]["environment"]:
                if item["name"] in asked_without_a_proposal(template):
                    self.assertTrue(item.get("prompt"), f"{app}: {item['name']}")

    def test_no_default_installation_asks_for_a_value_without_saying_what_it_is(self):
        from proxmenux_oci.installer import _example_default
        unexplained = {}
        for item in self.catalog.load_index()["applications"]:
            if item.get("hidden") or not item.get("automatic_install_candidate"):
                continue
            template = self.catalog.compose(item["id"])
            for variable in template["container_contract"].get("environment", []):
                if (variable["required"] and not variable["sensitive"] and not variable.get("prompt")
                        and variable.get("prompt_user", True) is not False
                        and variable["name"] not in ("PUID", "PGID", "TZ")
                        and _example_default(variable["name"], variable["example"], "Etc/UTC") in (None, "")):
                    unexplained.setdefault(item["id"], []).append(variable["name"])
        self.assertEqual(unexplained, {})

    def test_an_image_with_a_database_of_its_own_installs_without_asking_for_one(self):
        self.assertEqual(asked_without_a_proposal(self.catalog.compose("lychee")), [])
        database = {item["name"]: item for item in self.catalog.compose("lychee")["container_contract"]["environment"]}
        self.assertEqual(database["DB_CONNECTION"]["example"], "sqlite")
        self.assertFalse(database["DB_HOST"]["required"])


if __name__ == "__main__":
    unittest.main()
