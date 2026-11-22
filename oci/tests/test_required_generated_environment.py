import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import DEFAULT_MODE, build_deployment


class RecordingUI:
    def __init__(self):
        self.asked = []

    def ask(self, text, default=None, required=True):
        self.asked.append(text)
        return default if default not in (None, "") else "fixture-value"

    def password(self, text, required=True):
        self.asked.append(text)
        return "fixture-password"

    def choose(self, text, options, default=None):
        self.asked.append(text)
        return default

    def confirm(self, text, default=False):
        self.asked.append(text)
        return default

    def checklist(self, text, options, default=None):
        self.asked.append(text)
        return default

    def info(self, text):
        pass

    def message(self, text):
        pass


def _addresses(ui, bridge, names, *args):
    return {name: "dhcp" for name in names}, None


class RequiredGeneratedEnvironmentTests(unittest.TestCase):
    @patch("proxmenux_oci.i18n.language", return_value="en")
    @patch("proxmenux_oci.installer.host.storages", return_value=[
        {"storage": "local-lvm", "type": "lvmthin", "avail": 100 * 2**30}
    ])
    @patch("proxmenux_oci.installer.host.bridges", return_value=[
        {"iface": "vmbr0", "cidr": "192.0.2.10/24"}
    ])
    @patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
    @patch("proxmenux_oci.installer.host.gpus", return_value={"intel": [], "amd": [], "nvidia": False})
    @patch("proxmenux_oci.installer.access.ask_ipv4", return_value=("dhcp", None))
    @patch("proxmenux_oci.installer.access.ask_addresses", side_effect=_addresses)
    @patch("proxmenux_oci.installer.secrets.token_hex", return_value="a1" * 24)
    def test_database_secrets_are_generated_without_a_prompt_or_static_value(self, token_hex, *_):
        requirements = {
            "mysql": "MYSQL_ROOT_PASSWORD",
            "clickhouse": "CLICKHOUSE_PASSWORD",
            "typesense": "TYPESENSE_API_KEY",
        }
        catalog = Catalog(ROOT)

        for app, name in requirements.items():
            with self.subTest(app=app):
                ui = RecordingUI()
                template = catalog.compose(app)
                plan = build_deployment(template, ui, DEFAULT_MODE)
                variable = next(item for item in plan["environment"] if item["name"] == name)

                self.assertTrue(variable["sensitive"])
                self.assertRegex(variable["value"], re.compile(r"^[0-9a-f]{48}$"))
                self.assertNotIn(name, " ".join(ui.asked))
                contract = next(item for item in template["container_contract"]["environment"]
                                if item["name"] == name)
                self.assertNotIn("prompt_user", contract)
                token_hex.assert_called_with(24)
                token_hex.reset_mock()


if __name__ == "__main__":
    unittest.main()
