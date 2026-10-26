"""Tests for reading zram metrics from injectable proc and sys paths."""

import importlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

class ZramMetricsTests(unittest.TestCase):
    def test_reader_module_is_available(self):
        module_spec = importlib.util.find_spec("zram_metrics")
        self.assertIsNotNone(module_spec)
        module = importlib.import_module("zram_metrics")
        self.assertTrue(callable(getattr(module, "read_zram_metrics", None)))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.block_root = self.root / "sys" / "block"
        self.block_root.mkdir(parents=True)
        self.swaps_path = self.root / "proc" / "swaps"
        self.swaps_path.parent.mkdir(parents=True)
        self.swaps_path.write_text(
            "Filename\tType\tSize\tUsed\tPriority\n", encoding="utf-8"
        )

    def add_device(self, name="zram0", mm_stat="2097152 1048576 1179648 0"):
        device = self.block_root / name
        device.mkdir()
        (device / "disksize").write_text("1073741824\n", encoding="utf-8")
        (device / "mm_stat").write_text(mm_stat + "\n", encoding="utf-8")
        (device / "comp_algorithm").write_text(
            "lzo lzo-rle [zstd] lz4\n", encoding="utf-8"
        )
        return device

    def read_metrics(self):
        from zram_metrics import read_zram_metrics

        return read_zram_metrics(self.block_root, self.swaps_path)

    def test_no_zram_devices_reports_unavailable(self):
        (self.block_root / "sda").mkdir()

        self.assertEqual(self.read_metrics(), {"available": False, "devices": []})

    def test_reads_capacity_swap_usage_and_compression_counters(self):
        self.add_device()
        self.swaps_path.write_text(
            "Filename\tType\tSize\tUsed\tPriority\n"
            "/dev/zram0\tpartition\t1048576\t1024\t100\n",
            encoding="utf-8",
        )

        self.assertEqual(
            self.read_metrics(),
            {
                "available": True,
                "devices": [
                    {
                        "name": "zram0",
                        "active": True,
                        "capacity_bytes": 1073741824,
                        "swap_used_bytes": 1048576,
                        "original_bytes": 2097152,
                        "compressed_bytes": 1048576,
                        "memory_used_bytes": 1179648,
                        "algorithm": "zstd",
                        "compression_ratio": 2.0,
                        "saved_bytes": 917504,
                    }
                ],
            },
        )

    def test_zero_compressed_bytes_has_null_ratio(self):
        self.add_device(mm_stat="2097152 0 0 0")

        result = self.read_metrics()

        self.assertTrue(result["available"])
        self.assertEqual(len(result["devices"]), 1)
        self.assertFalse(result["devices"][0]["active"])
        self.assertEqual(result["devices"][0]["swap_used_bytes"], 0)
        self.assertIsNone(result["devices"][0]["compression_ratio"])

    def test_malformed_or_short_mm_stat_omits_device(self):
        for mm_stat in ("not-a-number 1048576 1179648", "2097152 1048576"):
            with self.subTest(mm_stat=mm_stat):
                device = self.block_root / "zram0"
                if device.exists():
                    (device / "mm_stat").write_text(mm_stat + "\n", encoding="utf-8")
                else:
                    self.add_device(mm_stat=mm_stat)

                result = self.read_metrics()

                self.assertFalse(result["available"])
                self.assertEqual(result["devices"], [])


if __name__ == "__main__":
    unittest.main()
