"""The notes of a container of a suite or stack carry the address it is reached at."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import install_generic_stack as generic
import oci_native_stack

RECORD = {"installation_id": "22d65764-750c-4aba-b0ef-55f5eb4dda0d",
          "template": {"id": "linuxserver-prowlarr", "catalog_ui": {"title": {"en_US": "Prowlarr"},
                                                                    "launch": {"scheme": "http", "port": 9696, "path": "/"}},
                       "container_contract": {"image": {"reference": "lscr.io/linuxserver/prowlarr:latest"}}}}


class GenericStackNotes(unittest.TestCase):
    def refresh(self, listed, status="status: running\n"):
        calls = []

        def run(*args, **_):
            calls.append([str(arg) for arg in args])
            return status if args[:2] == ("pct", "status") else ""

        def info(command, **_):
            if command[0] == "lxc-info":
                return subprocess.CompletedProcess(command, 0, stdout=listed, stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="net0: name=eth0,bridge=vmbr11,ip=10.77.1.30/24,type=veth\n"
                                               "net1: name=eth1,bridge=vmbr0,ip=dhcp,type=veth\n", stderr="")
        with patch.object(generic, "run", side_effect=run), patch.object(generic.oci_instances, "read", return_value=RECORD), \
                patch.object(oci_native_stack.subprocess, "run", side_effect=info), \
                patch.object(oci_native_stack.time, "sleep"):
            generic.refresh_notes([{"vmid": 180}])
        written = [call for call in calls if call[:2] == ["pct", "set"]]
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0][2:4], ["180", "--description"])
        return written[0][4]

    def test_the_local_network_address_is_written_not_the_one_of_the_private_network(self):
        notes = self.refresh("10.77.1.30\n192.168.0.78\n")
        self.assertIn("http://192.168.0.78:9696/", notes)
        self.assertNotIn("10.77.1.30", notes)

    def test_it_does_not_depend_on_the_range_of_the_local_network(self):
        notes = self.refresh("10.77.1.30\n10.0.1.141\n")
        self.assertIn("http://10.0.1.141:9696/", notes)
        self.assertNotIn("10.77.1.30", notes)

    def test_a_stopped_container_gets_its_notes_without_an_address(self):
        notes = self.refresh("", status="status: stopped\n")
        self.assertNotIn("http://10.", notes)
        self.assertIn("Prowlarr OCI", notes)
        self.assertIn("proxmenux-instance=22d65764-750c-4aba-b0ef-55f5eb4dda0d", notes)

    def test_a_container_whose_notes_cannot_be_written_does_not_stop_the_installation(self):
        with patch.object(generic, "run", side_effect=subprocess.CalledProcessError(1, "pct")), \
                patch.object(generic.oci_instances, "read", return_value=RECORD), patch.object(generic, "log") as log:
            generic.refresh_notes([{"vmid": 180}])
        self.assertIn("CT 180", log.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
