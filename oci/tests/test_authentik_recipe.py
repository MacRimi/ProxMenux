"""Authentik keeps the vendor's three-service deployment as native OCI LXCs."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.installer import DEFAULT_MODE
from proxmenux_oci.stack import DefaultsUI, build_stack


class AuthentikRecipeTests(unittest.TestCase):
    def setUp(self):
        self.curated = json.loads(
            (ROOT / "catalog/curated/authentik.json").read_text(encoding="utf-8")
        )
        self.generated = json.loads(
            (ROOT / "catalog/apps/authentik.json").read_text(encoding="utf-8")
        )
        self.services = {
            service["name"]: service
            for service in self.curated["compose_stack"]["services"]
        }

    def test_generated_catalog_copy_matches_curated_profile(self):
        self.assertEqual(self.curated, self.generated)

    def test_official_three_service_stack_uses_pinned_images_and_order(self):
        self.assertEqual(set(self.services), {"postgresql", "server", "worker"})
        self.assertEqual(self.curated["compose_stack"]["main_service"], "server")
        self.assertEqual(
            self.services["server"]["image"], "ghcr.io/goauthentik/server:2026.8.5"
        )
        self.assertEqual(
            self.services["worker"]["image"], "ghcr.io/goauthentik/server:2026.8.5"
        )
        self.assertEqual(
            self.services["postgresql"]["image"],
            "docker.io/library/postgres:16-alpine",
        )
        self.assertEqual(self.services["server"]["depends_on"], ["postgresql"])
        self.assertEqual(self.services["worker"]["depends_on"], ["postgresql"])

    def test_generated_database_and_application_secrets_are_shared_correctly(self):
        services = {
            name: service["compose"].get("environment", {})
            for name, service in self.services.items()
        }
        self.assertEqual(
            services["postgresql"]["POSTGRES_PASSWORD"], "${GENERATED_PG_PASS}"
        )
        for name in ("server", "worker"):
            self.assertEqual(
                services[name]["AUTHENTIK_POSTGRESQL__PASSWORD"],
                "${GENERATED_PG_PASS}",
            )
            self.assertEqual(
                services[name]["AUTHENTIK_SECRET_KEY"],
                "${GENERATED_AUTHENTIK_SECRET_KEY}",
            )
        generated = self.curated["compose_stack"]["installer_inputs"][
            "generated_secrets"
        ]
        self.assertEqual({secret["id"] for secret in generated}, {
            "pg-pass",
            "authentik-secret-key",
        })

    def test_persistent_mounts_and_database_healthcheck_are_preserved(self):
        mounts = {
            name: service["compose"].get("volumes", [])
            for name, service in self.services.items()
        }
        self.assertIn(
            {"source": "database", "target": "/var/lib/postgresql/data", "read_only": False},
            mounts["postgresql"],
        )
        self.assertIn(
            {"source": "./data", "target": "/data", "read_only": False},
            mounts["server"],
        )
        self.assertIn(
            {"source": "./data", "target": "/data", "read_only": False},
            mounts["worker"],
        )
        self.assertIn(
            {"source": "./custom-templates", "target": "/templates", "read_only": False},
            mounts["server"],
        )
        self.assertIn(
            {"source": "./custom-templates", "target": "/templates", "read_only": False},
            mounts["worker"],
        )
        self.assertIn(
            {"source": "./certs", "target": "/certs", "read_only": False},
            mounts["worker"],
        )
        check = self.services["postgresql"]["compose"]["healthcheck"]["test"]
        self.assertEqual(
            check,
            ["CMD-SHELL", "pg_isready -h 127.0.0.1 -d authentik -U authentik"],
        )

    def test_cross_lxc_data_and_templates_are_host_shared_and_backed_up_separately(self):
        shared = [
            item
            for item in self.curated["compose_stack"]["storage"]
            if item["container_path"] in ("/data", "/templates")
        ]
        self.assertEqual(len(shared), 4)
        self.assertTrue(all(item["mode"] == "host-bind" for item in shared))
        self.assertTrue(all(item["shared_with_other_lxc"] for item in shared))
        self.assertTrue(all(item["backup"] is False for item in shared))
        self.assertTrue(
            all(
                volume["default"] == "host-bind"
                and volume["managed_volume"]["backup"] is False
                for volume in self.curated["container_contract"]["volumes"]
            )
        )

    def test_docker_socket_is_not_mounted_and_both_web_ports_are_exposed(self):
        all_mounts = [
            mount
            for service in self.services.values()
            for mount in service["compose"].get("volumes", [])
        ]
        self.assertFalse(any("docker.sock" in mount for mount in all_mounts))
        self.assertEqual(
            self.services["server"]["compose"]["ports"],
            ["9000:9000", "9443:9443"],
        )

    def test_worker_gets_lan_interface_while_postgresql_stays_private(self):
        selected = {"worker": "192.0.2.21/24", "server": "192.0.2.22/24"}
        with patch("proxmenux_oci.installer.ask_storage", return_value="local-zfs"), \
             patch("proxmenux_oci.installer.ask_bridge", return_value="vmbr0"), \
             patch("proxmenux_oci.host.timezone", return_value="UTC"), \
             patch("proxmenux_oci.network.ask_addresses", return_value=(selected, "192.0.2.1")) as ask_addresses:
            plan = build_stack(self.curated, DefaultsUI(), DEFAULT_MODE)

        services = {service["name"]: service for service in plan["services"]}
        self.assertEqual(ask_addresses.call_args.args[2], ["worker", "server"])
        self.assertTrue(services["worker"]["frontend"])
        self.assertEqual(services["worker"]["frontend_ipv4"], selected["worker"])
        self.assertTrue(services["server"]["frontend"])
        self.assertEqual(services["server"]["frontend_ipv4"], selected["server"])
        self.assertNotIn("frontend", services["postgresql"])

    def test_first_run_discloses_the_initial_admin_setup_without_faking_a_password(self):
        first_run = self.curated["first_run"]
        self.assertEqual(first_run["endpoints"][0]["port"], 9000)
        credential = first_run["credentials"][0]
        self.assertEqual(credential["username"], "akadmin")
        self.assertIsNone(credential["password"])
        self.assertTrue(credential["change_required"])


if __name__ == "__main__":
    unittest.main()
