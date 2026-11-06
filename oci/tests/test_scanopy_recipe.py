"""Scanopy keeps its three services as native OCI LXCs, without host networking."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScanopyRecipeTests(unittest.TestCase):
    def setUp(self):
        self.curated = json.loads((ROOT / "catalog/curated/scanopy.json").read_text(encoding="utf-8"))
        self.generated = json.loads((ROOT / "catalog/apps/scanopy.json").read_text(encoding="utf-8"))
        self.services = {service["name"]: service for service in self.curated["compose_stack"]["services"]}

    def test_generated_catalog_copy_matches_curated_profile(self):
        self.assertEqual(self.curated, self.generated)

    def test_the_server_is_the_main_service(self):
        self.assertEqual(set(self.services), {"daemon", "postgres", "server"})
        self.assertEqual(self.curated["compose_stack"]["main_service"], "server")
        self.assertEqual(self.services["server"]["depends_on"], ["daemon", "postgres"])

    def test_only_postgres_stays_off_the_lan(self):
        self.assertTrue(self.services["daemon"]["frontend_network"])
        self.assertTrue(self.services["server"]["frontend_network"])
        self.assertFalse(self.services["postgres"]["frontend_network"])

    def test_the_daemon_needs_no_docker_only_settings(self):
        compose = self.services["daemon"]["compose"]
        self.assertNotIn("network_mode", compose)
        self.assertNotIn("privileged", compose)
        self.assertNotIn("docker.sock", json.dumps(compose))

    def test_the_daemon_stops_with_the_signal_it_handles(self):
        self.assertEqual(self.services["daemon"]["compose"]["stop_signal"], "SIGINT")

    def test_the_daemon_is_checked_where_it_answers(self):
        self.assertIn("/api/health", json.dumps(self.services["daemon"]["compose"]["healthcheck"]))

    def test_the_database_password_is_generated_and_shared(self):
        password = "${GENERATED_DB_PASSWORD}"
        self.assertEqual(self.services["postgres"]["compose"]["environment"]["POSTGRES_PASSWORD"], password)
        self.assertIn(password, self.services["server"]["compose"]["environment"]["SCANOPY_DATABASE_URL"])
        secrets = self.curated["compose_stack"]["installer_inputs"]["generated_secrets"]
        self.assertEqual(len(secrets), 1)
        self.assertEqual({binding["service"] for binding in secrets[0]["bindings"]}, {"postgres", "server"})

    def test_no_password_of_the_test_install_remains(self):
        self.assertNotIn("pmxLab", json.dumps(self.curated))


if __name__ == "__main__":
    unittest.main()
