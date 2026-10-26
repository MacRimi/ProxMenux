"""Regression tests for volume_preparations coverage across generated and
curated-profile catalog entries.

Covers the original OCI lost+found fix: a fresh ext4 managed volume carries
a lost+found directory, which stops images that take ownership of their own
data directories. volume_preparations (remove_lost_found +
only_when_mount_type: managed-volume) must be present for every persistent
mount, for both regular generated apps/*.json entries and curated-profile
entries (curated/*.json) — the curated-profile gap (Jellyfin Official first
surfaced it) is exactly what this suite guards against regressing.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog


class VolumePreparationsCoverageTests(unittest.TestCase):
    def _preparations_by_path(self, template):
        preparations = template["proxmox"]["installer_profile"].get("volume_preparations", [])
        return {item["container_path"]: item for item in preparations}

    def test_generated_app_volume_preparations_match_persistent_mounts(self):
        """Regular generated app (Uptime Kuma, apps/uptimekuma.json): every
        declared volume has a matching volume_preparations entry, and every
        entry is scoped to only_when_mount_type: managed-volume."""
        template = Catalog(ROOT).compose("uptimekuma")

        volume_paths = {v["container_path"] for v in template["container_contract"].get("volumes", [])}
        preparations = self._preparations_by_path(template)

        self.assertTrue(volume_paths, "fixture app must declare at least one volume")
        self.assertEqual(set(preparations.keys()), volume_paths)
        for path, entry in preparations.items():
            self.assertTrue(entry.get("remove_lost_found"))
            self.assertEqual(entry.get("only_when_mount_type"), "managed-volume")

    def test_curated_profile_app_volume_preparations_match_persistent_mounts(self):
        """Curated-profile app (Jellyfin Official, curated/jellyfin-official.json,
        3 mounts: /config, /cache, /media): same coverage requirement as
        generated apps. This is the regression guard for the gap first found
        via live testing — the original fix only touched apps/*.json and
        missed curated/*.json entirely."""
        template = Catalog(ROOT).compose("jellyfin-official")

        volume_paths = {v["container_path"] for v in template["container_contract"].get("volumes", [])}
        preparations = self._preparations_by_path(template)

        self.assertEqual(volume_paths, {"/config", "/cache", "/media"})
        self.assertEqual(set(preparations.keys()), volume_paths)
        for path, entry in preparations.items():
            self.assertTrue(entry.get("remove_lost_found"))
            self.assertEqual(entry.get("only_when_mount_type"), "managed-volume")


    def test_overlay_app_volume_preparations_match_the_overlay_remapped_mount(self):
        """PocketBase (apps/pocketbase.json + overlays/pocketbase.json): the
        overlay remaps the container_path from /pb_data to
        /pocketbase/pb_data. volume_preparations must follow the overlay's
        remapped path, not the pre-overlay source path — this is the
        regression guard for the overlay/mount desync first found via
        read-only audit (2026-09-29)."""
        template = Catalog(ROOT).compose("pocketbase")

        volume_paths = {v["container_path"] for v in template["container_contract"].get("volumes", [])}
        preparations = self._preparations_by_path(template)

        self.assertEqual(volume_paths, {"/pocketbase/pb_data"})
        self.assertEqual(set(preparations.keys()), volume_paths)
        for path, entry in preparations.items():
            self.assertTrue(entry.get("remove_lost_found"))
            self.assertEqual(entry.get("only_when_mount_type"), "managed-volume")


if __name__ == "__main__":
    unittest.main()
