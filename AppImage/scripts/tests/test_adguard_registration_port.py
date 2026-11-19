"""AdGuard Home installed from its OCI image serves its interface on :80 and,
until its first-run setup is done, the setup on :3000. Its automatic
registration shows what the App tab shows: :80 always, and :3000 as "Config"
only while it still answers. A port the user added is left alone."""
import copy
from pathlib import Path
import sys
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import lxc_apps  # noqa: E402

SETUP = {"port": 3000, "scheme": "http", "web_path": "/", "category": "Adblock & DNS", "description": ""}
UI = dict(SETUP, port=80)
CONFIG = dict(SETUP, description="Config")


def registration(*apps):
    return {"vmid": 104, "apps": [copy.deepcopy(app) for app in apps]}


class FollowSetupTests(unittest.TestCase):
    def follow(self, sidecar, answering, ip="192.0.2.37", template="image-adguard-home"):
        written, probes = [], []
        with mock.patch.object(lxc_apps, "_oci_instance_meta", return_value={"template_id": template}), \
                mock.patch.object(lxc_apps, "_read_sidecar", side_effect=lambda vmid: copy.deepcopy(sidecar)), \
                mock.patch.object(lxc_apps, "_write_sidecar",
                                  side_effect=lambda vmid, data, copies=False: written.append(data) or True), \
                mock.patch.object(lxc_apps, "_guest_ipv4", return_value=ip), \
                mock.patch.object(lxc_apps, "_answers_http",
                                  side_effect=lambda host, port: probes.append(port) or port in answering):
            lxc_apps._follow_adguard_setup(104)
        self.probes = probes
        return written

    def test_a_configured_adguard_keeps_only_its_interface(self):
        written = self.follow(registration({"installed_via": "oci_image", "ports": [SETUP]}), answering={80})
        self.assertEqual(written[0]["apps"][0]["ports"], [UI])

    def test_while_set_up_it_shows_the_interface_and_the_setup(self):
        written = self.follow(registration({"installed_via": "oci_image", "ports": [SETUP]}), answering={3000})
        self.assertEqual(written[0]["apps"][0]["ports"], [UI, CONFIG])

    def test_a_stopped_container_gets_the_interface_and_keeps_the_setup(self):
        written = self.follow(registration({"installed_via": "oci_image", "ports": [SETUP]}),
                              answering=set(), ip=None)
        self.assertEqual(written[0]["apps"][0]["ports"], [UI, CONFIG])

    def test_the_setup_goes_once_it_is_done(self):
        written = self.follow(registration({"installed_via": "oci_image", "ports": [UI, CONFIG]}), answering={80})
        self.assertEqual(written[0]["apps"][0]["ports"], [UI])

    def test_a_registration_already_in_step_is_not_rewritten(self):
        self.assertEqual(self.follow(registration({"installed_via": "oci_image", "ports": [UI, CONFIG]}),
                                     answering={80, 3000}), [])
        self.assertEqual(self.follow(registration({"installed_via": "oci_image", "ports": [UI]}),
                                     answering={80}), [])
        self.assertEqual(self.probes, [])

    def test_a_port_added_by_the_user_is_left_alone(self):
        self.assertEqual(self.follow(registration({"installed_via": "manual", "ports": [SETUP]}),
                                     answering={80}), [])

    def test_other_applications_are_not_probed(self):
        written = self.follow(registration({"installed_via": "oci_image", "ports": [SETUP]}),
                              answering={80}, template="image-grafana")
        self.assertEqual((written, self.probes), ([], []))


if __name__ == "__main__":
    unittest.main()
