"""OCI confirmation buttons use the active language catalog."""
from pathlib import Path
import sys
import unittest
from subprocess import CompletedProcess
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci import console
from proxmenux_oci.ui import DialogUI


def slovak(text: str) -> str:
    return {"Yes": "Áno", "No": "Nie", "Cancel": "Zrušiť"}.get(text, text)


class ConfirmationLabelTests(unittest.TestCase):
    def test_dialog_confirmation_uses_translated_yes_and_no_labels(self):
        with patch("proxmenux_oci.ui.translate", side_effect=slovak):
            with patch("proxmenux_oci.ui.subprocess.run", return_value=CompletedProcess([], 0, "", "")) as run:
                DialogUI().confirm("Continue?")
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--yes-label") + 1], "Áno")
        self.assertEqual(command[command.index("--no-label") + 1], "Nie")

    def test_console_confirmation_uses_translated_yes_and_no_labels(self):
        with patch("proxmenux_oci.console.translate", side_effect=slovak):
            with patch("proxmenux_oci.console.shutil.which", return_value="/usr/bin/whiptail"):
                with patch("proxmenux_oci.console.subprocess.run", return_value=CompletedProcess([], 0)) as run:
                    self.assertTrue(console.ask_yes_no("Continue?"))
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--yes-button") + 1], "Áno")
        self.assertEqual(command[command.index("--no-button") + 1], "Nie")
