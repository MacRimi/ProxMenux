"""A port that does not speak HTTP is not announced as a web address: the link
would open nothing, and an update would wait on it for an answer that never
comes and undo itself."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

from proxmenux_oci.catalog import Catalog
import oci_description
import oci_instance_transaction

# Application and the port its recipe was generated with as web address.
SERVICES = {
    "mariadb": 3306,
    "ngircd": 6667,
    "openssh-server": 2222,
    "syslog-ng": 6601,
    "faster-whisper": 10300,
    "piper": 10200,
}


class ServicePortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog = Catalog(ROOT)
        cls.templates = {app: catalog.compose(app) for app in SERVICES}

    def test_no_web_address_is_announced(self):
        for app, template in self.templates.items():
            with self.subTest(app=app):
                self.assertEqual(template["first_run"]["endpoints"], [])
                self.assertIsNone(template["catalog_ui"]["launch"]["port"])

    def test_the_port_is_still_the_one_of_the_container(self):
        for app, port in SERVICES.items():
            with self.subTest(app=app):
                ports = [item["container_port"] for item in self.templates[app]["container_contract"]["ports"]]
                self.assertIn(port, ports)

    def test_an_update_checks_that_the_container_keeps_running(self):
        for app, template in self.templates.items():
            with self.subTest(app=app):
                self.assertEqual(oci_instance_transaction.effective_healthcheck(template)["type"], "running")

    def test_the_notes_give_the_address_as_text(self):
        notes = oci_description.render(self.templates["mariadb"], "sha256:" + "0" * 64, "instance", "192.168.1.50")
        self.assertIn("<code>192.168.1.50:3306</code>", notes)
        self.assertNotIn("Web UI", notes)
        self.assertNotIn("http://192.168.1.50", notes)
        notes = oci_description.render(self.templates["syslog-ng"], "sha256:" + "0" * 64, "instance", "192.168.1.50")
        self.assertIn("<code>192.168.1.50:5514/udp</code>", notes)

    def test_a_web_application_keeps_its_link_in_the_notes(self):
        template = Catalog(ROOT).compose("bookstack")
        notes = oci_description.render(template, "sha256:" + "0" * 64, "instance", "192.168.1.50")
        self.assertIn("http://192.168.1.50:80/", notes)
        self.assertNotIn("<code>192.168.1.50:", notes)

    def test_the_summary_gives_the_address_of_a_service_only(self):
        script = (ROOT / "remote/install_oci.sh").read_text()
        self.assertIn("service_addresses:$service_addresses", script)
        cli = (ROOT / "src/proxmenux_oci/cli.py").read_text()
        self.assertIn("translate('Service:')", cli)

    def test_mariadb_says_how_to_connect(self):
        notes = self.templates["mariadb"]["proxmox"]["installer_profile"]["completion_notes"]
        self.assertTrue(any("port 3306" in note for note in notes))
        self.assertTrue(any("without a password" in note for note in notes))


if __name__ == "__main__":
    unittest.main()
