"""`install --menu` installs with the dialogs of the menu's page of the
application, as the Monitor's Catalog tab asks, and its exit code tells a
cancelled installation from a failed one."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci import cli
from proxmenux_oci.installer import ADVANCED_MODE, DEFAULT_MODE


class ConfirmUI:
    def __init__(self, answer):
        self.answer = answer
        self.asked = []

    def confirm(self, text, default=False, title=None):
        self.asked.append(text)
        return self.answer


class InstallMenuTests(unittest.TestCase):
    def run_install(self, *extra, result=None, notice=None, answer=True):
        ui = ConfirmUI(answer)
        with patch.object(cli, "interactive_ui", return_value=ui), \
                patch.object(cli, "external_services_notice", return_value=notice), \
                patch.object(cli, "install_template", return_value=result) as install, \
                patch.object(cli, "run_remote_install") as text_install:
            code = cli.main(["install", "tandoor", "--menu", *extra])
        text_install.assert_not_called()
        return code, ui, install

    def test_it_installs_with_the_wizard_of_the_menu(self):
        code, _, install = self.run_install(result={"vmid": 100})
        self.assertEqual(code, 0)
        ui, template, identifier, mode = install.call_args.args
        self.assertEqual((identifier, mode), ("tandoor", DEFAULT_MODE))

    def test_the_advanced_installation_asks_everything(self):
        _, _, install = self.run_install("--advanced", result={"vmid": 100})
        self.assertEqual(install.call_args.args[3], ADVANCED_MODE)

    def test_an_installation_not_approved_is_cancelled(self):
        code, _, _ = self.run_install(result=None)
        self.assertEqual(code, 130)

    def test_a_failed_installation_is_an_error(self):
        code, _, _ = self.run_install(result={})
        self.assertEqual(code, 1)

    def test_the_notice_of_external_services_comes_first(self):
        code, ui, install = self.run_install(notice="Uses an external service.", answer=False)
        self.assertEqual(code, 130)
        self.assertTrue(ui.asked[0].startswith("Uses an external service."))
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
