"""A volume prepared for the application belongs to the user the application
writes with: the user of the image unless the oci-compose, its PUID/PGID-style
variables or volume_owner name another one. It is never root by default."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "remote" / "oci_mount_idmap.py"
INSTALLER = ROOT / "remote" / "install_oci.sh"


def application_ids(deployment, template, config):
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        (folder / "deployment.json").write_text(json.dumps(deployment))
        (folder / "template.json").write_text(json.dumps(template))
        (folder / "ct.conf").write_text(config)
        result = subprocess.run(
            [sys.executable, str(HELPER), "application-ids", "--deployment", str(folder / "deployment.json"),
             "--template", str(folder / "template.json"), "--config", str(folder / "ct.conf")],
            capture_output=True, text=True, check=True, cwd=ROOT / "remote")
    return tuple(map(int, result.stdout.split()))


class ApplicationVolumeOwnerTests(unittest.TestCase):
    def test_an_image_user_without_variables_owns_its_volumes(self):
        config = "arch: amd64\nlxc.init.uid: 1000\nlxc.init.gid: 1000\n"
        self.assertEqual(application_ids({}, {}, config), (1000, 1000))

    def test_an_image_that_starts_as_root_keeps_root(self):
        self.assertEqual(application_ids({}, {}, "arch: amd64\n"), (0, 0))

    def test_variables_and_volume_owner_replace_the_image_user(self):
        config = "lxc.init.uid: 1000\nlxc.init.gid: 1000\n"
        environment = {"environment": [{"name": "PUID", "value": "1500"}, {"name": "PGID", "value": "1501"}]}
        self.assertEqual(application_ids(environment, {}, config), (1500, 1501))
        template = {"proxmox": {"installer_profile": {"volume_owner": {"uid": 2000, "gid": 2001}}}}
        self.assertEqual(application_ids(environment, template, config), (2000, 2001))

    def test_the_installer_takes_the_owner_from_the_same_resolution(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('oci_mount_idmap.py" application-ids', text)
        self.assertNotIn('| last // "0"', text)


if __name__ == "__main__":
    unittest.main()
