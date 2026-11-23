"""Tests for user-configurable Vital Signs sampling intervals."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import health_thresholds as ht


class TestHealthSamplingIntervals(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.orig_db_dir = ht._DB_DIR
        self.orig_config_path = ht._CONFIG_PATH
        ht._DB_DIR = self.temporary.name
        ht._CONFIG_PATH = os.path.join(self.temporary.name, "health_thresholds.json")
        ht.invalidate_cache()

    def tearDown(self):
        ht._DB_DIR = self.orig_db_dir
        ht._CONFIG_PATH = self.orig_config_path
        ht.invalidate_cache()

    def test_default_sampling_intervals(self):
        self.assertIn("sampling_intervals", ht.DEFAULTS)
        self.assertEqual(ht.get("sampling_intervals", "cpu"), 5.0)
        self.assertEqual(ht.get("sampling_intervals", "temperature"), 15.0)
        self.assertEqual(ht.get("sampling_intervals", "memory"), 30.0)

    def test_override_sampling_intervals(self):
        payload = {
            "sampling_intervals": {
                "cpu": 15,
                "temperature": 45,
                "memory": 60,
            }
        }
        res = ht.save(payload)
        self.assertTrue(res["sampling_intervals"]["cpu"]["customised"])
        self.assertEqual(res["sampling_intervals"]["cpu"]["value"], 15.0)
        self.assertEqual(ht.get("sampling_intervals", "cpu"), 15.0)
        self.assertEqual(ht.get("sampling_intervals", "temperature"), 45.0)
        self.assertEqual(ht.get("sampling_intervals", "memory"), 60.0)

    def test_validation_out_of_range(self):
        # min for cpu is 1, max is 300
        with self.assertRaises(ht.ThresholdValidationError):
            ht.save({"sampling_intervals": {"cpu": 0}})

        with self.assertRaises(ht.ThresholdValidationError):
            ht.save({"sampling_intervals": {"cpu": 500}})

    def test_reset_sampling_intervals_section(self):
        ht.save({"sampling_intervals": {"cpu": 20}})
        self.assertEqual(ht.get("sampling_intervals", "cpu"), 20.0)

        ht.reset_section("sampling_intervals")
        self.assertEqual(ht.get("sampling_intervals", "cpu"), 5.0)


if __name__ == "__main__":
    unittest.main()
