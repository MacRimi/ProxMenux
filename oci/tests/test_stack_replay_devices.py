"""A stack update keeps the USB, serial and GPU nodes of a member, and stops on anything else."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_stack_replay


def projection(*values):
    return {"native_devices": [{"key": f"dev{index}", "value": value} for index, value in enumerate(values)]}


class StackReplayDeviceTests(unittest.TestCase):
    def test_usb_serial_and_gpu_nodes_are_translated(self):
        devices = oci_stack_replay.translated_devices(projection(
            "path=/dev/ttyACM1,mode=0660,deny-write=0,gid=20",
            "path=/dev/bus/usb/003/002,mode=0664,deny-write=1",
            "path=/dev/dri/renderD128,mode=0660,gid=104,uid=1000"))
        self.assertEqual(devices[0], {
            "id": "native-ttyACM1", "kind": "character-device", "host_path": "/dev/ttyACM1",
            "container_path": "/dev/ttyACM1", "mode": "0660", "deny_write": False,
            "gid_strategy": "host-device-gid"})
        self.assertEqual((devices[1]["gid_strategy"], devices[1]["deny_write"], devices[1]["mode"]),
                         ("none", True, "0664"))
        self.assertEqual((devices[2]["host_path"], devices[2]["uid"]), ("/dev/dri/renderD128", 1000))

    def test_a_member_without_devices_has_none(self):
        self.assertEqual(oci_stack_replay.translated_devices(projection()), [])

    def test_an_unknown_device_has_no_translation(self):
        for value in ("path=/dev/sda,mode=0660", "path=/dev/nvidia0,mode=0666", "mode=0660"):
            with self.assertRaises(ValueError):
                oci_stack_replay.translated_devices(projection(value))


if __name__ == "__main__":
    unittest.main()
