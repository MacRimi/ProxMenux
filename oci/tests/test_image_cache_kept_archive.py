"""The newest archive of an application that is no longer installed is kept,
and an installation without the registry finds it.

Archives are real disposable OCI fixtures; guests are mocked."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import oci_image_cache as cache
from oci_installation_state import image_from_archive
from test_stack_image_cache import archive_fixture

OLD = time.time() - 3 * cache.MIN_AGE_SECONDS


class KeptArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.root, self.folder = base / "instances", base / "cache"
        self.root.mkdir()
        self.folder.mkdir()
        self.existing = set()
        patcher = patch.object(cache.instances, "guest_exists", side_effect=lambda vmid: vmid in self.existing)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temporary.cleanup)

    def archive(self, name, version, age=0):
        path = self.folder / name
        archive_fixture(path, version)
        os.utime(path, (OLD - age, OLD - age))
        return path

    def record(self, vmid, app_id, archive, exists=True):
        directory = self.root / str(vmid)
        directory.mkdir()
        (directory / "oci-compose.json").write_text(json.dumps({
            "vmid": vmid, "status": "installed", "template": {"id": app_id},
            "observed": {"archive_path": str(archive), "image": {"architecture": "amd64"},
                         "resolved_registry_digest": "sha256:" + "c" * 64}}))
        if exists:
            self.existing.add(vmid)

    def unused(self):
        return sorted(path.name for path, _ in cache.unused_archives(self.root))

    def test_the_newest_archive_of_a_removed_application_is_kept(self):
        older = self.archive("image-demo_amd64_" + "1" * 16 + ".tar", "1", age=60)
        newer = self.archive("image-demo_amd64_" + "2" * 16 + ".tar", "2")
        self.record(101, "image-demo", newer, exists=False)
        self.assertEqual(self.unused(), [older.name])

    def test_an_installed_application_keeps_only_the_archive_it_uses(self):
        used = self.archive("proxmenux-update-amd64-" + "d" * 64 + ".tar", "2")
        original = self.archive("image-demo_amd64_" + "1" * 16 + ".tar", "1")
        self.record(101, "image-demo", used)
        self.assertEqual(self.unused(), [original.name])

    def test_update_archives_and_other_applications_follow_their_own_rules(self):
        update = self.archive("proxmenux-update-amd64-" + "e" * 64 + ".tar", "3")
        other = self.archive("image-other_amd64_" + "3" * 16 + ".tar", "1")
        used = self.archive("image-demo_amd64_" + "1" * 16 + ".tar", "1")
        self.record(101, "image-demo", used)
        self.assertEqual(self.unused(), [update.name])
        self.assertTrue(other.exists())

    def test_removing_an_updated_installation_links_its_archive_under_the_application(self):
        digest = "f" * 64
        update = self.archive(f"proxmenux-update-amd64-{digest}.tar", "4")
        target = cache.keep_for_reinstall({"template": {"id": "image-demo"},
                                           "observed": {"archive_path": str(update)}})
        self.assertEqual(target.name, f"image-demo_amd64_{digest[:16]}.tar")
        self.assertEqual(target.stat().st_ino, update.stat().st_ino)
        self.assertIsNone(cache.keep_for_reinstall({"template": {"id": "image-demo"},
                                                    "observed": {"archive_path": str(target)}}))

    def test_an_installation_without_the_registry_uses_the_newest_kept_archive(self):
        self.archive("image-demo_amd64_" + "1" * 16 + ".tar", "1", age=60)
        newer = self.archive("image-demo_amd64_" + "2" * 16 + ".tar", "2")
        self.archive("image-demo-extra_amd64_" + "3" * 16 + ".tar", "3")
        saved = cache.saved_archive(self.folder, "image-demo", "amd64")
        self.assertEqual(saved["archive"], str(newer))
        self.assertEqual(saved["digest"], image_from_archive(newer)["manifest_digest"])

    def test_a_pinned_reference_accepts_only_its_own_image(self):
        self.archive("image-demo_amd64_" + "2" * 16 + ".tar", "2")
        pinned = self.archive("image-demo_amd64_" + "1" * 16 + ".tar", "1", age=60)
        digest = "sha256:" + "1" * 64
        saved = cache.saved_archive(self.folder, "image-demo", "amd64", digest)
        self.assertEqual((saved["archive"], saved["digest"]), (str(pinned), digest))
        self.assertIsNone(cache.saved_archive(self.folder, "image-demo", "amd64", "sha256:" + "9" * 64))

    def test_no_kept_archive_leaves_the_registry_error(self):
        self.assertIsNone(cache.saved_archive(self.folder, "image-demo", "amd64"))
        self.assertIsNone(cache.saved_archive(self.folder, "image-demo", "arm64"))


if __name__ == "__main__":
    unittest.main()
