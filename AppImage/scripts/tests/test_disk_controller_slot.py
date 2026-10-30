"""Disk -> storage controller mapping; never imports flask_server.

The sysfs paths and lspci records are real output from two PVE 9 hosts:
a Broadcom 9400-16i SAS HBA, AMD/ASMedia SATA, an Intel 7 Series SATA
controller left in BIOS IDE mode, USB disks behind a hub, and NVMe drives
behind chipset bridges.

Run: python3 -m unittest discover -s AppImage/scripts/tests -p test_disk_controller_slot.py -v
"""
import ast
import posixpath
import re
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "flask_server.py"
NAMES = {"_PCI_ADDR_RE", "_last_pci_slot", "get_disk_controller_slot", "get_storage_controllers"}

LSPCI_VMM = """Slot:\t01:00.0
Class:\tSerial Attached SCSI controller
Vendor:\tBroadcom / LSI
Device:\tSAS3416 Fusion-MPT Tri-Mode I/O Controller Chip (IOC)
SVendor:\tBroadcom / LSI
SDevice:\tHBA 9400-16i

Slot:\t02:00.1
Class:\tSATA controller
Vendor:\tAdvanced Micro Devices, Inc. [AMD]
Device:\t500 Series Chipset SATA Controller
SVendor:\tASMedia Technology Inc.
SDevice:\tASM1062 Serial ATA Controller

Slot:\t08:00.0
Class:\tNon-Volatile memory controller
Vendor:\tMicron/Crucial Technology
Device:\tP5 Plus NVMe PCIe SSD
SVendor:\tMicron/Crucial Technology
SDevice:\tDevice 0100

Slot:\t00:1f.2
Class:\tIDE interface
Vendor:\tIntel Corporation
Device:\t7 Series/C210 Series Chipset Family 4-port SATA Controller [IDE mode]
SVendor:\tASUSTeK Computer Inc.
SDevice:\tDevice 84ca
"""


def fake_os(links=None, readlinks=None):
    links, readlinks = links or {}, readlinks or {}
    known = set(links) | set(readlinks)
    return SimpleNamespace(
        readlink=lambda p: readlinks[p],
        path=SimpleNamespace(
            realpath=lambda p: links.get(p, p),
            exists=lambda p: p in known,
            basename=posixpath.basename,
        ),
    )


def load(os_module=None, lspci=LSPCI_VMM):
    tree = ast.parse(SOURCE.read_text())
    nodes = [n for n in tree.body
             if (isinstance(n, ast.FunctionDef) and n.name in NAMES)
             or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in NAMES for t in n.targets))]
    found = {n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id for n in nodes}
    assert found == NAMES, NAMES - found
    env = {"os": os_module or fake_os(), "re": re, "get_cached_lspci_vmm": lambda: lspci}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), env)
    return env


class LastPciSlotTests(unittest.TestCase):
    def setUp(self):
        self.slot = load()["_last_pci_slot"]

    def test_controller_is_the_deepest_pci_address(self):
        cases = {
            # SAS HBA, direct attach (no expander)
            "/sys/devices/pci0000:00/0000:00:01.1/0000:01:00.0/host6/port-6:1/end_device-6:1/target6:0:1/6:0:1:0": "01:00.0",
            # Onboard SATA (AHCI)
            "/sys/devices/pci0000:00/0000:00:02.1/0000:02:00.1/ata1/host0/target0:0:0/0:0:0:0": "02:00.1",
            # SATA in BIOS IDE mode (ata_piix)
            "/sys/devices/pci0000:00/0000:00:1f.2/ata1/host0/target0:0:0/0:0:0:0": "00:1f.2",
            # USB disk behind a hub -> the xHCI controller
            "/sys/devices/pci0000:00/0000:00:08.1/0000:0c:00.3/usb3/3-2/3-2.4/3-2.4.1/3-2.4.1:1.0/host7/target7:0:0/7:0:0:0": "0c:00.3",
            # NVMe behind two chipset bridges -> the drive itself
            "/sys/devices/pci0000:00/0000:00:02.1/0000:02:00.2/0000:03:04.0/0000:08:00.0/nvme/nvme0": "08:00.0",
        }
        for path, expected in cases.items():
            self.assertEqual(self.slot(path), expected, path)

    def test_domain_is_kept_when_not_zero(self):
        # Intel VMD exposes NVMe under a 10000: domain, which lspci prints too
        path = "/sys/devices/pci0000:00/0000:00:0e.0/pci10000:e0/10000:e0:1d.0/10000:e1:00.0/nvme/nvme2"
        self.assertEqual(self.slot(path), "10000:e1:00.0")

    def test_path_without_pci_gives_none(self):
        self.assertIsNone(self.slot("/sys/devices/virtual/nvme-subsystem/nvme-subsys0"))


class DiskControllerSlotTests(unittest.TestCase):
    def test_disk_resolves_through_block_device_link(self):
        get_slot = load(fake_os(links={
            "/sys/block/sdf/device": "/sys/devices/pci0000:00/0000:00:02.1/0000:02:00.1/ata1/host0/target0:0:0/0:0:0:0",
        }))["get_disk_controller_slot"]
        self.assertEqual(get_slot("sdf"), "02:00.1")

    def test_nvme_multipath_falls_back_to_controller_link(self):
        get_slot = load(fake_os(links={
            "/sys/block/nvme0n1/device": "/sys/devices/virtual/nvme-subsystem/nvme-subsys0",
            "/sys/class/nvme/nvme0/device": "/sys/devices/pci0000:00/0000:00:02.2/0000:0b:00.0",
        }))["get_disk_controller_slot"]
        self.assertEqual(get_slot("nvme0n1"), "0b:00.0")

    def test_zvol_without_device_link_gives_none(self):
        self.assertIsNone(load()["get_disk_controller_slot"]("zd16"))


class StorageControllersTests(unittest.TestCase):
    def test_describes_only_requested_slots_once(self):
        controllers = load()["get_storage_controllers"](
            iter(["01:00.0", "01:00.0", "02:00.1", None, "99:00.0"]))
        self.assertEqual(set(controllers), {"01:00.0", "02:00.1"})
        self.assertEqual(controllers["01:00.0"]["sdevice"], "HBA 9400-16i")
        self.assertEqual(controllers["01:00.0"]["class"], "Serial Attached SCSI controller")

    def test_ide_mode_controller_is_described(self):
        controllers = load()["get_storage_controllers"](["00:1f.2"])
        self.assertEqual(controllers["00:1f.2"]["class"], "IDE interface")

    def test_lspci_placeholder_subsystem_name_is_dropped(self):
        controllers = load()["get_storage_controllers"](["08:00.0", "00:1f.2"])
        self.assertIsNone(controllers["08:00.0"]["sdevice"])
        self.assertIsNone(controllers["00:1f.2"]["sdevice"])
        self.assertEqual(controllers["08:00.0"]["device"], "P5 Plus NVMe PCIe SSD")

    def test_driver_read_from_sysfs_with_domain_prefix(self):
        controllers = load(fake_os(readlinks={
            "/sys/bus/pci/devices/0000:01:00.0/driver": "../../../bus/pci/drivers/mpt3sas",
        }))["get_storage_controllers"](["01:00.0", "02:00.1"])
        self.assertEqual(controllers["01:00.0"]["driver"], "mpt3sas")
        self.assertIsNone(controllers["02:00.1"]["driver"])

    def test_no_slots_skips_lspci(self):
        def fail():
            raise AssertionError("lspci should not be read")
        env = load()
        env["get_cached_lspci_vmm"] = fail
        self.assertEqual(env["get_storage_controllers"]([None]), {})


if __name__ == "__main__":
    unittest.main()
