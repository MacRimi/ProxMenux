"""On an ARM host the OCI menu offers only the applications whose image has
ARM; an amd64 host keeps the whole catalog."""

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "remote")]

from proxmenux_oci import cli

APPS = [
    {"id": "jellyfin", "architectures": ["amd64", "arm64"], "automatic_install_candidate": True},
    {"id": "frigate", "architectures": ["amd64"], "automatic_install_candidate": True},
    {"id": "hidden", "architectures": ["arm64"], "automatic_install_candidate": True, "hidden": True},
    {"id": "pending", "architectures": ["arm64"], "automatic_install_candidate": False},
]


class CliArchitectureTests(unittest.TestCase):
    def installable(self, machine):
        with mock.patch.object(cli.os, "uname", return_value=mock.Mock(machine=machine)):
            return [item["id"] for item in cli._installable(APPS)]

    def test_an_arm_host_is_offered_only_arm_images(self):
        self.assertEqual(self.installable("aarch64"), ["jellyfin"])

    def test_an_amd64_host_keeps_the_whole_catalog(self):
        self.assertEqual(self.installable("x86_64"), ["jellyfin", "frigate"])


if __name__ == "__main__":
    unittest.main()
