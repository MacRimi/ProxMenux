"""Every multi-container application offers extra paths in an advanced installation."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.cli import _deployment_summary_text
from proxmenux_oci.installer import ADVANCED_MODE, DEFAULT_MODE, build_deployment
from test_advanced_flow_order import RecordingUI, addresses, storages

EXTRA = "Add an extra custom path"
SPECIAL = ("nextcloud-stack", "paperless-ngx", "tandoor", "immich")


class ExtraPathUI(RecordingUI):
    """Adds one container volume the first time the extra path is offered."""

    def __init__(self):
        super().__init__({"Path inside the container (e.g. /media-extra)": "/media-extra",
                          "Volume size in GB": "20"})
        self.offered = 0

    def confirm(self, text, default=False):
        if text == EXTRA:
            self.asked.append(text)
            self.offered += 1
            return self.offered == 1
        return super().confirm(text, default)


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
@patch("proxmenux_oci.installer.access.ask_addresses", side_effect=addresses)
class StackExtraPathTests(unittest.TestCase):
    catalog = Catalog(ROOT)

    def test_the_advanced_installation_offers_an_extra_path_before_the_network(self, *_):
        for app in SPECIAL:
            ui = ExtraPathUI()
            template = self.catalog.compose(app)
            plan = build_deployment(template, ui, ADVANCED_MODE)
            self.assertEqual(ui.asked.count(EXTRA), 2, app)
            bridge = next(text for text in ui.asked if text.startswith("Access bridge"))
            self.assertLess(ui.asked.index(EXTRA), ui.asked.index(bridge), app)
            self.assertEqual([(m["type"], m["container_path"], m["size_gb"]) for m in plan["extra_mounts"]],
                             [("managed-volume", "/media-extra", 20)], app)
            self.assertIn("/media-extra", _deployment_summary_text(template, plan), app)

    def test_an_extra_path_cannot_hide_the_data_of_the_application(self, *_):
        ui = ExtraPathUI()
        ui.answers["Path inside the container (e.g. /media-extra)"] = "/var/www/html/data"
        with self.assertRaises(ValueError):
            build_deployment(self.catalog.compose("nextcloud-stack"), ui, ADVANCED_MODE)

    def test_the_advanced_installation_offers_usb_devices_for_the_application(self, *_):
        device = "Add another GPU or USB device manually?"
        usb = [{"path": "/dev/ttyACM1", "name": "Z-Stick", "kind": "Communications"}]
        for app in SPECIAL:
            ui = RecordingUI()
            offered = []

            def confirm(text, default=False, ui=ui, offered=offered):
                ui.asked.append(text)
                if text == device:
                    offered.append(text)
                    return len(offered) == 1
                return default

            def choose(text, options, default=None, ui=ui):
                ui.asked.append(text)
                tags = [tag for tag, _label in options]
                if text == "Device to attach":
                    self.assertNotIn("nvidia", tags, app)
                    return "usb"
                return "/dev/ttyACM1" if "/dev/ttyACM1" in tags else default

            ui.confirm, ui.choose = confirm, choose
            template = self.catalog.compose(app)
            with patch("proxmenux_oci.extra_devices.host.usb_devices", return_value=usb):
                plan = build_deployment(template, ui, ADVANCED_MODE)
            self.assertEqual([(d["kind"], d["host_path"], d["gid_strategy"]) for d in plan["extra_devices"]],
                             [("character-device", "/dev/ttyACM1", "host-device-gid")], app)
            self.assertIn("/dev/ttyACM1", _deployment_summary_text(template, plan), app)

    def test_the_default_installation_does_not_ask_it(self, *_):
        for app in SPECIAL:
            ui = RecordingUI()
            plan = build_deployment(self.catalog.compose(app), ui, DEFAULT_MODE)
            self.assertNotIn(EXTRA, ui.asked, app)
            self.assertEqual(plan["extra_mounts"], [], app)
            self.assertEqual(plan["extra_devices"], [], app)
            self.assertNotIn("Add another GPU or USB device manually?", ui.asked, app)


if __name__ == "__main__":
    unittest.main()
