"""An advanced installation of a multi-container application asks the CPU and
the memory of its application container; a default one keeps the recipe."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.cli import _deployment_summary_text
from proxmenux_oci.installer import ADVANCED_MODE, DEFAULT_MODE, InstallError, build_deployment
from test_advanced_flow_order import RecordingUI, addresses, storages

SPECIAL = {"nextcloud-stack": (2, 2048), "paperless-ngx": (2, 2048), "tandoor": (2, 2048), "immich": (4, 3072)}
REMOTE = {"nextcloud-stack": "nextcloud", "paperless-ngx": "paperless", "tandoor": "tandoor", "immich": "immich"}


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
@patch("proxmenux_oci.installer.access.ask_addresses", side_effect=addresses)
class StackResourceTests(unittest.TestCase):
    catalog = Catalog(ROOT)

    def test_the_advanced_installation_asks_cpu_and_memory_before_the_storage(self, *_):
        for app in SPECIAL:
            ui = RecordingUI({"CPU cores": "6", "Memory in MB": "4096"})
            template = self.catalog.compose(app)
            plan = build_deployment(template, ui, ADVANCED_MODE)
            self.assertEqual((plan["resources"]["cores"], plan["resources"]["memory_mb"]), (6, 4096), app)
            self.assertLess(ui.asked.index("Memory in MB"), ui.asked.index("Storage for rootfs"), app)
            self.assertIn("6 CPU, 4096 MB RAM", _deployment_summary_text(template, plan), app)

    def test_the_default_installation_keeps_the_resources_of_the_recipe(self, *_):
        for app, expected in SPECIAL.items():
            ui = RecordingUI()
            plan = build_deployment(self.catalog.compose(app), ui, DEFAULT_MODE)
            self.assertEqual((plan["resources"]["cores"], plan["resources"]["memory_mb"]), expected, app)
            self.assertNotIn("CPU cores", ui.asked, app)

    def test_resources_that_cannot_run_the_application_are_refused(self, *_):
        ui = RecordingUI({"CPU cores": "0"})
        with self.assertRaises(InstallError):
            build_deployment(self.catalog.compose("tandoor"), ui, ADVANCED_MODE)

    def test_the_installers_create_the_application_with_the_chosen_resources(self, *_):
        for app, (cores, memory) in SPECIAL.items():
            script = (ROOT / f"remote/install_{REMOTE[app]}_stack.sh").read_text()
            self.assertIn(f"jqr '.resources.cores // {cores}'", script, app)
            self.assertIn(f"jqr '.resources.memory_mb // {memory}'", script, app)
            self.assertIn('--cores "$APPLICATION_CORES" --memory "$APPLICATION_MEMORY"', script, app)


if __name__ == "__main__":
    unittest.main()
