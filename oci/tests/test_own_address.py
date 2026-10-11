"""An application that has to be told its own address is not asked for it: the
container has one, fixed or given by DHCP, and the installation uses that."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import CONTAINER_ADDRESS, own_address_value
import oci_instances

# Application, its variable and the value it takes at 192.168.1.50.
OWN_ADDRESS = {
    "bookstack": ("APP_URL", "http://192.168.1.50"),
    "healthchecks": ("SITE_ROOT", "http://192.168.1.50:8000"),
    "speedtest-tracker": ("APP_URL", "http://192.168.1.50"),
    "netbox": ("ALLOWED_HOST", "192.168.1.50"),
}


class OwnAddressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog = Catalog(ROOT)
        cls.variables = {}
        for app, (name, _) in OWN_ADDRESS.items():
            environment = catalog.compose(app)["container_contract"]["environment"]
            cls.variables[app] = next(item for item in environment if item["name"] == name)

    def test_a_fixed_address_is_used_as_it_is(self):
        for app, (_, expected) in OWN_ADDRESS.items():
            with self.subTest(app=app):
                pattern = self.variables[app]["container_address"]
                self.assertEqual(own_address_value(pattern, "192.168.1.50/24"), expected)

    def test_dhcp_leaves_the_mark_for_the_installation(self):
        for app in OWN_ADDRESS:
            with self.subTest(app=app):
                pattern = self.variables[app]["container_address"]
                self.assertIn(CONTAINER_ADDRESS, own_address_value(pattern, "dhcp"))

    def test_the_address_is_that_of_the_port_the_application_listens_on(self):
        catalog = Catalog(ROOT)
        for app, (_, expected) in OWN_ADDRESS.items():
            with self.subTest(app=app):
                endpoint = catalog.compose(app)["first_run"]["endpoints"][0]
                if not expected.startswith("http"):
                    continue  # A bare address names the machine, not a port.
                port = "" if endpoint["port"] == 80 else f":{endpoint['port']}"
                self.assertEqual(expected, f"{endpoint['scheme']}://192.168.1.50{port}")

    def test_the_installer_resolves_the_mark_before_the_first_start(self):
        script = (ROOT / "remote/install_oci.sh").read_text()
        self.assertIn(f"OWN_ADDRESS_MARK='{CONTAINER_ADDRESS}'", script)
        self.assertLess(script.index("\napply_own_address\n"), script.index('msg_info "$(translate "Starting the container...")"'))
        self.assertEqual(oci_instances.ADDRESS_MARK, CONTAINER_ADDRESS)

    def test_the_record_keeps_the_address_and_not_the_mark(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record = {"schema_version": 1, "vmid": 900, "installation_id": "00000000-0000-4000-8000-000000000000", "status": "installing",
                      "deployment": {"environment": [{"name": "APP_URL", "value": f"http://{CONTAINER_ADDRESS}"},
                                                     {"name": "TZ", "value": "Europe/Madrid"}]}}
            path = oci_instances.location(root, 900)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record))
            observe, oci_instances.observe = oci_instances.observe, lambda *args, **kwargs: {"config": ""}
            try:
                oci_instances.finish(root, 900, "archive", "digest", "192.168.1.50")
            finally:
                oci_instances.observe = observe
            saved = json.loads(path.read_text())["deployment"]["environment"]
            self.assertEqual(saved[0]["value"], "http://192.168.1.50")
            self.assertEqual(saved[1]["value"], "Europe/Madrid")


if __name__ == "__main__":
    unittest.main()
