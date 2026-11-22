"""Every view of a disk takes its rotation and type from disk_identity."""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "AppImage/scripts"))
import disk_identity
import audit_inventory


class DiskMediaTypeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name, flag in (("sda", "1"), ("sdb", "0"), ("nvme0n1", "0")):
            (self.root / name / "queue").mkdir(parents=True)
            (self.root / name / "queue/rotational").write_text(flag + "\n")
        sys_block = patch.object(disk_identity, "_SYS_BLOCK", str(self.root))
        sys_block.start()
        self.addCleanup(sys_block.stop)

    def test_the_kernel_flag_answers_when_smartctl_did_not(self):
        self.assertEqual(disk_identity.rotation_rate("sda"), -1)
        self.assertEqual(disk_identity.rotation_rate("sdb"), 0)
        self.assertEqual(disk_identity.rotation_rate("sdz"), 0)

    def test_what_smartctl_reported_wins(self):
        self.assertEqual(disk_identity.rotation_rate("sda", 0), 0)
        self.assertEqual(disk_identity.rotation_rate("sdb", 5400), 5400)
        self.assertEqual(disk_identity.rotation_rate("sda", None), -1)

    def test_media_type(self):
        self.assertEqual(disk_identity.media_type("sda", -1), "HDD")
        self.assertEqual(disk_identity.media_type("sda", 7200), "HDD")
        self.assertEqual(disk_identity.media_type("sdb", 0), "SSD")
        self.assertEqual(disk_identity.media_type("nvme0n1", 0), "NVMe")

    def test_the_inventory_agrees_with_the_monitor(self):
        rows = ('NAME="sda" MODEL="WDC WD7500BPVT" SERIAL="WX1" SIZE="750156374016" ROTA="1" TRAN="usb" TYPE="disk"\n'
                'NAME="sdb" MODEL="Samsung SSD" SERIAL="S1" SIZE="500107862016" ROTA="0" TRAN="sata" TYPE="disk"\n')
        ctx = types.SimpleNamespace(run=lambda *a, **k: (0, rows),
                                    monitor_snapshot={"smart": {"/dev/sda": [0, {"rotation_rate": 0}]}})
        with patch.object(audit_inventory, "_disk_observations", return_value={}):
            disks = {d["name"]: d["rotational"] for d in audit_inventory._physical_disks(ctx)}
        # The USB bridge marks sda rotational; smartctl, through the Monitor, says solid state.
        self.assertEqual(disks, {"sda": False, "sdb": False})

    def _card(self, disk, **fields):
        device = self.root / disk / "device"
        device.mkdir(parents=True)
        for field, value in fields.items():
            (device / field).write_text(value + "\n")

    def test_an_sd_card_reports_its_name_serial_and_kind(self):
        self._card("mmcblk0", name="SC32G", serial="0x1a2b3c4d", type="SD")
        self.assertEqual(disk_identity.mmc_card("mmcblk0"),
                         {"model": "SC32G", "serial": "0x1a2b3c4d", "interface": "SD"})

    def test_an_emmc_is_told_apart_from_an_sd_card(self):
        self._card("mmcblk1", name="BJTD4R", serial="0x00000abc", type="MMC")
        self.assertEqual(disk_identity.mmc_card("mmcblk1")["interface"], "MMC")

    def test_missing_or_empty_fields_are_left_out(self):
        self._card("mmcblk2", name="", type="SD")
        self.assertEqual(disk_identity.mmc_card("mmcblk2"), {"interface": "SD"})
        self.assertEqual(disk_identity.mmc_card("mmcblk9"), {})

    def test_other_disks_are_not_cards(self):
        self._card("sdc", name="SC32G", serial="0x1", type="SD")
        self.assertEqual(disk_identity.mmc_card("sdc"), {})
        self.assertEqual(disk_identity.mmc_card("nvme0n1"), {})


if __name__ == "__main__":
    unittest.main()
