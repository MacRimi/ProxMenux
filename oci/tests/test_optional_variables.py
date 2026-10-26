"""Optional image variables are asked with what identifies them, and stay unset by default."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import ADVANCED_MODE, build_deployment
from test_advanced_flow_order import RecordingUI, addresses, storages


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
@patch("proxmenux_oci.installer.access.ask_ipv4", return_value=("dhcp", None))
@patch("proxmenux_oci.installer.access.ask_addresses", side_effect=addresses)
class OptionalVariableTests(unittest.TestCase):
    def build(self, app, ui):
        return build_deployment(Catalog(ROOT).compose(app), ui, ADVANCED_MODE)

    def optional_questions(self, ui):
        return [text for text in ui.asked if "Configure the optional variable" in text]

    def test_first_question_explains_them_and_links_the_documentation(self, *_):
        ui = RecordingUI()
        plan = self.build("amule", ui)
        questions = self.optional_questions(ui)
        self.assertIn("answer No: the image keeps its own value", questions[0])
        self.assertIn("https://github.com/ngosang/docker-amule", questions[0])
        self.assertTrue(all("answer No" not in text for text in questions[1:]))
        restart = next(text for text in questions if "MOD_AUTO_RESTART_ENABLED" in text)
        self.assertIn("Restart aMule automatically on a schedule (true or false)", restart)
        self.assertIn("Example value: true", restart)
        self.assertFalse([e for e in plan["environment"] if e["name"].startswith("MOD_")])

    def test_the_example_is_a_hint_not_a_default(self, *_):
        ui = RecordingUI()
        asked_defaults = {}
        ui.confirm = lambda text, default=False: ui.asked.append(text) or "MOD_AUTO_RESTART_CRON" in text
        ui.ask = lambda text, default=None, required=True: asked_defaults.setdefault(text, default) or ""
        self.build("amule", ui)
        prompt = next(text for text in asked_defaults if text.startswith("Schedule of the automatic restart"))
        self.assertIn(asked_defaults[prompt], (None, ""))

if __name__ == "__main__":
    unittest.main()
