"""Catalog links agree with the configured service and preserve suite choices."""

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import DEFAULT_MODE, build_deployment
from proxmenux_oci.stack import StackError
from test_advanced_flow_order import RecordingUI, addresses, storages
import oci_description
import oci_instance_transaction as transaction


class CatalogWebLinks(unittest.TestCase):
    catalog = Catalog(ROOT)

    def test_jdownloader_launch_matches_its_secure_web_service(self):
        template = self.catalog.compose("jdownloader")
        environment = {entry["name"]: entry.get("example")
                       for entry in template["container_contract"]["environment"]}
        self.assertEqual(environment["SECURE_CONNECTION"], "1")
        launch = template["catalog_ui"]["launch"]
        self.assertEqual(launch, {"scheme": "https", "port": 5800, "path": "/"})
        endpoint = template["first_run"]["endpoints"][0]
        self.assertEqual({key: endpoint[key] for key in launch}, launch)
        self.assertIn('href="https://192.0.2.10:5800/"',
                      oci_description.render(template, "", "test-installation", "192.0.2.10"))

    def test_shipped_templates_keep_the_curated_link_contract(self):
        for app in ("jdownloader", "suite-arr"):
            with self.subTest(app=app):
                curated = json.loads((ROOT / "catalog/curated" / (app + ".json")).read_text())
                generated = json.loads((ROOT / "catalog/apps" / (app + ".json")).read_text())
                self.assertEqual(curated["catalog_ui"]["launch"], generated["catalog_ui"]["launch"])
                self.assertEqual(curated["first_run"], generated["first_run"])

    def test_suite_parent_names_the_documented_prowlarr_web_endpoint(self):
        template = self.catalog.compose("suite-arr")
        endpoints = template["first_run"]["endpoints"]
        self.assertEqual(len(endpoints), 1)
        endpoint = endpoints[0]
        self.assertEqual((endpoint["scheme"], endpoint["port"], endpoint["path"]),
                         ("http", 9696, "/"))
        self.assertEqual(endpoint["label"], "Web UI")
        self.assertNotEqual(endpoint["source"], transaction.GUESSED_ENDPOINT)
        check = transaction.effective_healthcheck(template)
        self.assertEqual((check["scheme"], check["port"]), ("http", 9696))
        self.assertNotIn("accept_non_http", check)

    @patch("proxmenux_oci.installer.host.gpus", return_value={"intel": [], "amd": [], "nvidia": False})
    @patch("proxmenux_oci.i18n.language", return_value="en")
    @patch("proxmenux_oci.installer.host.storages", side_effect=storages)
    @patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.1/24"}])
    @patch("proxmenux_oci.installer.host.timezone", return_value="Etc/UTC")
    @patch("proxmenux_oci.installer.access.ask_ipv4", return_value=("dhcp", None))
    @patch("proxmenux_oci.installer.access.ask_addresses", side_effect=addresses)
    def test_suite_members_keep_their_own_links_with_or_without_prowlarr(self, *_):
        template = self.catalog.compose("suite-arr")
        before = copy.deepcopy(template)
        with patch("subprocess.run") as command:
            for selected in (["prowlarr", "sonarr"], ["sonarr"]):
                ui = RecordingUI({"Arr suite: applications to install": selected,
                                  "Media server": "none"})
                plan = build_deployment(copy.deepcopy(template), ui, DEFAULT_MODE)
                self.assertEqual([member["name"] for member in plan["services"]], selected)
                for member in plan["services"]:
                    port = 9696 if member["name"] == "prowlarr" else 8989
                    endpoint = member["template"]["first_run"]["endpoints"][0]
                    self.assertEqual(endpoint["port"], port)
                    self.assertEqual(member["healthcheck"]["endpoint"]["port"], port)
                    notes = oci_description.render(member["template"], "", "test-installation", "192.0.2.10")
                    self.assertIn(f':{port}/"', notes)
                    if port != 9696:
                        self.assertNotIn(':9696/"', notes)
            command.assert_not_called()
        self.assertEqual(template, before)

    def test_empty_suite_selection_has_no_host_or_runtime_effect(self):
        template = self.catalog.compose("suite-arr")
        before = copy.deepcopy(template)
        ui = RecordingUI({"Arr suite: applications to install": [], "Media server": "none"})
        with patch("proxmenux_oci.i18n.language", return_value="en"), \
                patch("proxmenux_oci.installer.host.storages") as host, \
                patch("subprocess.run") as command:
            with self.assertRaises(StackError):
                build_deployment(template, ui, DEFAULT_MODE)
            host.assert_not_called()
            command.assert_not_called()
        self.assertEqual(template, before)


if __name__ == "__main__":
    unittest.main()
