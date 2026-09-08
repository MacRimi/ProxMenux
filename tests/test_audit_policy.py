"""Policy validation and atomic updates. All writes stay in temporary directories."""
import concurrent.futures
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "AppImage/scripts"))
import audit_policy as policy


class AuditPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "policy.json"

    def save(self, raw, **kwargs):
        return policy.save(raw, self.path, **kwargs)

    def test_missing_is_not_declared(self):
        value = policy.load(self.path)
        self.assertFalse(value.declared)
        self.assertIsNone(value.error)
        self.assertEqual(value.revision, "missing")

    def test_inheritance_and_explicit_unspecified_round_trip(self):
        value = self.save({"defaults": {"backup": "required", "autostart": "required",
                                      "storage_role": "essential", "recovery_objective_hours": 48},
                           "guests": {"100": {"backup": "unspecified", "autostart": "not_required"}},
                           "storages": {"local": {"role": "unspecified"}}})
        self.assertEqual(value.backup_required(100), "unspecified")
        self.assertEqual(value.backup_required(101), "required")
        self.assertEqual(value.autostart_required(100), "not_required")
        self.assertEqual(value.storage_role("local"), "unspecified")
        self.assertEqual(value.storage_role("pbs"), "essential")
        self.assertEqual(value.recovery_objective_hours(100), 48)

    def test_invalid_numbers_rejected_without_changing_saved_policy(self):
        self.save({"thresholds": {"storage_usage_percent": 90}})
        before = self.path.read_bytes()
        for value in (True, False, 0, -1, float("nan"), float("inf"), -float("inf"), "12", 10**400):
            for raw in ({"thresholds": {"storage_usage_percent": value}},
                        {"guests": {"100": {"recovery_objective_hours": value}}},
                        {"defaults": {"recovery_objective_hours": value}}):
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    self.save(raw)
                self.assertEqual(before, self.path.read_bytes())

    def test_percentage_bounds_and_positive_fractional_values(self):
        with self.assertRaises(ValueError):
            self.save({"thresholds": {"storage_usage_percent": 101}})
        value = self.save({"thresholds": {"storage_usage_percent": 100, "thin_overprovision_ratio": 2.5},
                           "guests": {"100": {"recovery_objective_hours": 0.5}}})
        self.assertEqual(value.recovery_objective_hours(100), 0.5)
        self.assertEqual(value.threshold("thin_overprovision_ratio"), 2.5)

    def test_invalid_sections_and_defaults_rejected(self):
        for name in ("guests", "storages", "thresholds", "defaults"):
            for value in ([], False, "", None):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.save({name: value})
        for name in ("backup", "autostart", "storage_role"):
            with self.assertRaises(ValueError):
                self.save({"defaults": {name: "invalid"}})

    def test_manual_invalid_file_is_visible_and_not_overwritten(self):
        self.path.write_text('{"thresholds":{"storage_usage_percent":Infinity}}')
        value = policy.load(self.path)
        self.assertTrue(value.error)
        with self.assertRaises(ValueError):
            self.save({}, expected_revision=value.revision)

    def test_stale_editor_is_rejected(self):
        first = self.save({})
        second = self.save({"defaults": {"backup": "required"}}, expected_revision=first.revision)
        with self.assertRaises(policy.PolicyConflict):
            self.save({}, expected_revision=first.revision)
        self.assertEqual(policy.load(self.path).revision, second.revision)

    def test_deleted_file_is_also_a_conflict(self):
        first = self.save({})
        self.path.unlink()
        with self.assertRaises(policy.PolicyConflict):
            self.save({}, expected_revision=first.revision)

    def test_concurrent_editors_only_one_can_save(self):
        revision = self.save({}).revision
        def write(i):
            try:
                self.save({"guests": {str(i): {"backup": "required"}}}, expected_revision=revision)
                return "saved"
            except policy.PolicyConflict:
                return "conflict"
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(write, range(100, 108)))
        self.assertEqual(results.count("saved"), 1)
        self.assertEqual(results.count("conflict"), 7)
        self.assertEqual(len(json.loads(self.path.read_text())["guests"]), 1)
        self.assertEqual(list(self.path.parent.glob(".audit-policy-*")), [])

    def test_failed_replace_preserves_original_and_cleans_temp(self):
        self.save({})
        before = self.path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                self.save({"defaults": {"backup": "required"}})
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(list(self.path.parent.glob(".audit-policy-*")), [])

    def test_private_permissions_and_same_mtime_changes(self):
        first = self.save({})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        stamp = self.path.stat().st_mtime_ns
        self.path.write_text('{"defaults":{"backup":"required"}}')
        os.utime(self.path, ns=(stamp, stamp))
        fresh = policy.load(self.path)
        self.assertNotEqual(first.revision, fresh.revision)
        self.assertEqual(fresh.backup_required(100), "required")


if __name__ == "__main__":
    unittest.main()
