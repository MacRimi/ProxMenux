"""Frigate offers the object detection devices found on the host, and asks nothing without them."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

from proxmenux_oci.installer import configure_detector, detected_detector_devices
import oci_gpu_devices

PROFILE = json.loads((ROOT / "catalog/curated/frigate.json").read_text())["proxmox"]["installer_profile"]


class ObjectDetectorTests(unittest.TestCase):
    def host(self, nodes, vendors=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for node in nodes:
            (root / node.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
            (root / node.lstrip("/")).touch()
        for sysfs, vendor in (vendors or {}).items():
            (root / sysfs).parent.mkdir(parents=True, exist_ok=True)
            (root / sysfs).write_text(vendor + "\n")
        # Regular files stand in for the character devices of a real host.
        patcher = patch.object(Path, "is_char_device", lambda self: self.is_file())
        patcher.start()
        self.addCleanup(patcher.stop)
        return root

    def test_intel_npu_and_coral_are_found_amd_npu_is_not(self):
        root = self.host(["/dev/accel/accel0", "/dev/accel/accel1", "/dev/apex_0"],
                         {"sys/class/accel/accel0/device/vendor": "0x8086",
                          "sys/class/accel/accel1/device/vendor": "0x1022"})
        found = detected_detector_devices(PROFILE, root)
        self.assertEqual([(item["id"], item["host_path"]) for item in found],
                         [("intel-npu", "/dev/accel/accel0"), ("coral-pcie", "/dev/apex_0")])

    def test_nothing_found_asks_nothing(self):
        root = self.host([])
        ui = Mock()
        self.assertEqual(configure_detector(PROFILE, [], ui, root), ([], []))
        ui.choose.assert_not_called()

    def test_selected_npu_is_attached_with_the_host_gid_and_a_note(self):
        root = self.host(["/dev/accel/accel0"], {"sys/class/accel/accel0/device/vendor": "0x8086"})
        ui = Mock()
        ui.choose.return_value = "/dev/accel/accel0"
        devices, notes = configure_detector(PROFILE, [{"id": "gpu-render", "host_path": "/dev/dri/renderD128"}], ui, root)
        self.assertEqual(devices[-1], {"id": "detector-intel-npu", "kind": "character-device",
                                       "host_path": "/dev/accel/accel0", "container_path": "/dev/accel/accel0",
                                       "mode": "0660", "deny_write": False, "gid_strategy": "host-device-gid"})
        self.assertIn("device: NPU", notes[0])
        self.assertEqual([tag for tag, _label in ui.choose.call_args.args[1]], ["none", "/dev/accel/accel0"])

    def test_no_detector_keeps_the_devices(self):
        root = self.host(["/dev/apex_0"])
        ui = Mock()
        ui.choose.return_value = "none"
        self.assertEqual(configure_detector(PROFILE, [], ui, root), ([], []))

    def test_an_attached_detector_is_not_offered_again(self):
        root = self.host(["/dev/apex_0"])
        ui = Mock()
        devices = [{"id": "detector-coral-pcie", "host_path": "/dev/apex_0"}]
        self.assertEqual(configure_detector(PROFILE, devices, ui, root), (devices, []))
        ui.choose.assert_not_called()

    def test_template_without_detectors_asks_nothing(self):
        ui = Mock()
        self.assertEqual(configure_detector({}, [], ui, self.host(["/dev/apex_0"])), ([], []))
        ui.choose.assert_not_called()

    def test_npu_node_is_a_supported_device_for_updates_and_adoption(self):
        self.assertTrue(oci_gpu_devices.peripheral_path("/dev/accel/accel0"))
        self.assertFalse(oci_gpu_devices.peripheral_path("/dev/accel/accel"))
        self.assertFalse(oci_gpu_devices.peripheral_path("/dev/accel/../kvm"))


if __name__ == "__main__":
    unittest.main()
