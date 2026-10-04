"""The notes Proxmox shows for a multi-container application link to the
address it answers on from the local network, not to its private leg."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_native_stack as stack

TWO_LEGS = "net0: name=eth0,bridge=vmbr0,ip=dhcp,type=veth\nnet1: name=eth1,bridge=vmbr10,ip=10.77.0.10/24,type=veth\n"
PRIVATE_ONLY = "net0: name=eth0,bridge=vmbr10,ip=10.77.0.12/24,type=veth\n"


class AccessAddressTests(unittest.TestCase):
    def address(self, config, *answers, wait=20):
        listed = iter(answers)

        def run(command, **_):
            if command[0] == "pct":
                return SimpleNamespace(stdout=config)
            return SimpleNamespace(stdout=next(listed))

        with patch.object(stack.subprocess, "run", side_effect=run), patch.object(stack.time, "sleep"):
            return stack.access_address(101, wait)

    def test_the_address_of_the_local_network_is_used(self):
        self.assertEqual(self.address(TWO_LEGS, "10.77.0.10\n192.168.0.44\n"), "192.168.0.44")
        self.assertEqual(self.address(TWO_LEGS, "192.168.0.44\n10.77.0.10\n"), "192.168.0.44")

    def test_a_lease_that_has_not_arrived_is_waited_for(self):
        self.assertEqual(self.address(TWO_LEGS, "10.77.0.10\n", "10.77.0.10\n192.168.0.44\n"), "192.168.0.44")

    def test_a_container_with_only_its_private_leg_keeps_that_address(self):
        self.assertEqual(self.address(PRIVATE_ONLY, "10.77.0.12\n"), "10.77.0.12")

    def test_a_container_without_address_has_none(self):
        self.assertEqual(self.address(PRIVATE_ONLY, "\n"), "")
        self.assertEqual(self.address(TWO_LEGS, "10.77.0.10\n", wait=0), "10.77.0.10")


if __name__ == "__main__":
    unittest.main()
