"""USB devices are offered by name, as the Monitor shows them, with the node an LXC receives."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci import host
from proxmenux_oci.extra_devices import ask_extra_devices, choose_usb_device

LSUSB = """Bus 003 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 003 Device 002: ID 0463:ffff MGE UPS Systems UPS
Bus 003 Device 003: ID 0658:0200 Sigma Designs, Inc. Aeotec Z-Stick Gen5 (ZW090) - UZB
Bus 003 Device 004: ID 1cf1:0030 Dresden Elektronik ZigBee gateway [ConBee II]
Bus 003 Device 005: ID 0781:5581 SanDisk Corp. Ultra
"""


class UsbDevicesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        pci = self.root / "sys/devices/pci0000:00/usb3"
        self.device(pci, "usb3", "1d6b", "09", 1)
        self.device(pci, "3-3", "0463", "00", 2, product="Ellipse ECO", interface="03")
        self.device(pci, "3-8", "0658", "02", 3, tty="ttyACM1")
        self.device(pci, "3-9", "1cf1", "02", 4, product="ConBee II", tty="ttyACM0")
        self.device(pci, "3-10", "0781", "00", 5, product="Ultra", interface="08")

    def device(self, parent, name, vendor, device_class, number, product="", interface="", tty=""):
        path = parent / name
        path.mkdir(parents=True)
        for key, value in {"idVendor": vendor, "idProduct": "0001", "bDeviceClass": device_class,
                           "busnum": "3", "devnum": str(number)}.items():
            (path / key).write_text(value + "\n")
        if product:
            (path / "product").write_text(product + "\n")
        if interface:
            (path / f"{name}:1.0").mkdir()
            (path / f"{name}:1.0" / "bInterfaceClass").write_text(interface + "\n")
        link = self.root / "sys/bus/usb/devices" / name
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(path, link)
        if tty:
            port = path / f"{name}:1.0" / "tty" / tty
            port.mkdir(parents=True)
            (self.root / "sys/class/tty").mkdir(parents=True, exist_ok=True)
            (self.root / "sys/class/tty" / tty).mkdir()
            os.symlink(path / f"{name}:1.0", self.root / "sys/class/tty" / tty / "device")

    def test_devices_are_named_as_the_monitor_names_them(self):
        rows = host.usb_devices(self.root, LSUSB)
        self.assertEqual(rows, [
            {"path": "/dev/bus/usb/003/002", "name": "Ellipse ECO", "kind": "UPS"},
            {"path": "/dev/ttyACM1", "name": "Sigma Designs, Inc. Aeotec Z-Stick Gen5 (ZW090) - UZB",
             "kind": "Communications"},
            {"path": "/dev/ttyACM0", "name": "ConBee II", "kind": "Communications"},
        ])

    def test_the_menu_lists_the_devices_and_leaves_attached_ones_out(self):
        ui = Mock()
        ui.choose.return_value = "/dev/ttyACM1"
        with patch.object(host, "usb_devices", return_value=host.usb_devices(self.root, LSUSB)):
            self.assertEqual(choose_usb_device(ui, "USB", attached={"/dev/ttyACM0"}), "/dev/ttyACM1")
        tags = [tag for tag, _label in ui.choose.call_args.args[1]]
        self.assertEqual(tags, ["/dev/bus/usb/003/002", "/dev/ttyACM1", "manual"])
        ui.ask.assert_not_called()

    def test_without_devices_the_node_is_typed(self):
        ui = Mock()
        ui.ask.return_value = "/dev/ttyUSB0"
        with patch.object(host, "usb_devices", return_value=[]):
            self.assertEqual(choose_usb_device(ui, "USB"), "/dev/ttyUSB0")
        ui.message.assert_called_once()
        ui.choose.assert_not_called()

    def test_extra_usb_device_comes_from_the_list(self):
        ui = Mock()
        ui.confirm.side_effect = [True, False]
        ui.choose.side_effect = ["usb", "/dev/ttyACM0"]
        with patch.object(host, "usb_devices", return_value=host.usb_devices(self.root, LSUSB)):
            devices = ask_extra_devices(ui, [], True)
        self.assertEqual([(d["host_path"], d["container_path"]) for d in devices],
                         [("/dev/ttyACM0", "/dev/ttyACM0")])


if __name__ == "__main__":
    unittest.main()
