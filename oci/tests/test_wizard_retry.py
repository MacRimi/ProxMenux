"""A value the wizard cannot accept asks that question again, with every
earlier answer kept, instead of ending the wizard."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci import cli
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import ADVANCED_MODE
from test_advanced_flow_order import RecordingUI, addresses, storages


class TypoUI(RecordingUI):
    """Types 8o for the cores the first time, and 8 the second."""
    back_enabled = False

    def __init__(self):
        super().__init__()
        self.messages = []
        self.cores = iter(["8o", "8"])

    def ask(self, text, default=None, required=True):
        if text == "CPU cores":
            self.asked.append(text)
            return next(self.cores)
        return super().ask(text, default, required)

    def message(self, text, title=None):
        self.messages.append(text)

    def review(self, text, title=None, question=None, default=True):
        return False


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
@patch("proxmenux_oci.installer.host.gpus", return_value={"intel": [], "amd": [], "nvidia": False})
@patch("proxmenux_oci.installer.access.ask_addresses", side_effect=addresses)
class WizardRetryTests(unittest.TestCase):
    def test_a_mistyped_number_asks_the_same_question_again(self, *_):
        ui = TypoUI()
        cli.install_template(ui, Catalog(ROOT).compose("tandoor"), "tandoor", ADVANCED_MODE)
        self.assertEqual(ui.asked.count("CPU cores"), 2)
        # The answers given before the mistake are replayed, not asked again.
        self.assertEqual(ui.asked.count("Stack name"), 1)
        self.assertEqual(len(ui.messages), 1)
        self.assertIn("The value must be a number: '8o'", ui.messages[0])
        self.assertIn("Enter the value again.", ui.messages[0])

    def test_an_error_before_any_answer_still_ends_the_wizard(self, *_):
        from proxmenux_oci.ui import BacktrackUI
        self.assertFalse(BacktrackUI(TypoUI()).retry_last(ValueError("x")))


if __name__ == "__main__":
    unittest.main()
