"""Coordinated preparation reuses verified installation archives, not stale images.

Registry responses, downloads and PVE calls are mocked; archive validation and
image comparison run against real disposable OCI fixtures. No guests are touched.
"""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))
import oci_stack_native as native
import oci_update_current as update
from oci_installation_state import image_from_archive
from verify_oci_archive import verify_archive

INDEX = "sha256:" + "a" * 64
NEXT_INDEX = "sha256:" + "b" * 64


def archive_fixture(path, version):
    """A small, real OCI archive with one gzip-compressed tar layer."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as layer:
        body = version.encode()
        member = tarfile.TarInfo("version")
        member.size = len(body)
        layer.addfile(member, io.BytesIO(body))
    with tarfile.open(path, "w") as archive:
        def write(name, data):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))

        def blob(data):
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            write("blobs/" + digest.replace(":", "/"), data)
            return {"digest": digest, "size": len(data)}

        layer = blob(gzip.compress(raw.getvalue()))
        layer["mediaType"] = "application/vnd.oci.image.layer.v1.tar+gzip"
        config = blob(json.dumps({"architecture": "amd64", "os": "linux",
                                  "config": {}, "created": "2026-01-01T00:00:00Z",
                                  "rootfs": {"type": "layers", "diff_ids": [
                                      "sha256:" + hashlib.sha256(raw.getvalue()).hexdigest()]}}).encode())
        config["mediaType"] = "application/vnd.oci.image.config.v1+json"
        manifest = blob(json.dumps({"schemaVersion": 2,
                                    "mediaType": "application/vnd.oci.image.manifest.v1+json", "config": config,
                                    "layers": [layer]}).encode())
        manifest["mediaType"] = "application/vnd.oci.image.manifest.v1+json"
        write("index.json", json.dumps({"schemaVersion": 2, "manifests": [manifest]}).encode())
        write("oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
    verify_archive(path)
    return image_from_archive(str(path))


class StackImageCacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.saved = self.root / "original-installation.tar"
        self.old_image = archive_fixture(self.saved, "old")
        self.source = self.root / "registry-download.tar"
        shutil.copyfile(self.saved, self.source)
        self.candidate = dict(self.old_image, registry_digest=INDEX)
        self.record = {
            "vmid": 4900, "installation_id": "fixture-installation",
            "template": {"container_contract": {"image": {"reference": "example/app:latest"}}},
            "deployment": {"mounts": [], "template_storage": "local"},
            "observed": {"archive_path": str(self.saved), "resolved_registry_digest": INDEX,
                         "image": self.old_image},
            "stack": {"deployment": {"services": [{"vmid": 4900, "name": "app"}]}},
        }
        self.downloads = []
        self.lookups = []
        self.verifications = []
        self.registry_error = None

    def prepare(self, operation="update"):
        record = copy.deepcopy(self.record)
        adapter = native.NativeAdapter(self.root / "registry", self.root / "journal", {
            "members": [record], "primary_vmid": 4900, "operation": operation})
        destination = self.root / "update-cache.tar"

        def command(*args):
            if args[:2] == ("pct", "config"):
                return b"arch: amd64\n"
            self.assertEqual(args[:2], ("pvesm", "path"))
            return str(destination).encode()

        def quiet(args, *unused, **kwargs):
            if "-c" in args:
                self.lookups.append(args[-2])
                if self.registry_error:
                    raise self.registry_error
                return json.dumps(self.candidate)
            if args[0] == "skopeo":
                self.downloads.append(args)
                shutil.copyfile(self.source, args[-1].removeprefix("oci-archive:"))
                return b""
            self.assertEqual(Path(args[1]).name, "verify_oci_archive.py")
            self.verifications.append(Path(args[-1]))
            verify_archive(Path(args[-1]))
            return b""

        with patch.object(native.instances, "read", return_value={}), \
                patch.object(native.instances, "write"), \
                patch.object(native.instances, "location", return_value=self.root / "record.json"), \
                patch.object(native.instances, "command", side_effect=command), \
                patch.object(update, "run_quiet", side_effect=quiet), \
                patch.object(update.work_backup, "available", return_value=1024**4), \
                patch.object(update.transaction, "log"):
            return adapter.prepare(record, operation)

    def test_update_reuses_a_verified_original_archive_without_downloading_layers(self):
        result = self.prepare()
        self.assertEqual(result["archive"], str(self.saved))
        self.assertEqual(result["digest"], self.old_image["manifest_digest"])
        self.assertEqual(self.lookups, ["example/app:latest"])
        self.assertIn(self.saved, self.verifications)
        self.assertEqual(self.downloads, [])

    def test_recreate_pins_the_saved_registry_digest_and_reuses_the_original_archive(self):
        result = self.prepare("recreate")
        self.assertEqual(self.lookups, ["example/app@" + INDEX])
        self.assertEqual(result["archive"], str(self.saved))
        self.assertEqual(result["proposal"]["operation"], "recreate")
        self.assertEqual(self.downloads, [])

    def test_changed_image_rejects_the_old_archive_and_downloads_the_new_digest(self):
        new_image = archive_fixture(self.source, "new")
        self.candidate = dict(new_image, registry_digest=NEXT_INDEX)
        before = self.saved.read_bytes()
        result = self.prepare()
        self.assertNotEqual(result["archive"], str(self.saved))
        self.assertEqual(result["digest"], new_image["manifest_digest"])
        self.assertEqual(len(self.downloads), 1)
        self.assertIn("docker://example/app@" + new_image["manifest_digest"], self.downloads[0])
        self.assertEqual(image_from_archive(result["archive"]), new_image)
        self.assertEqual(self.saved.read_bytes(), before)

    def test_corrupt_original_archive_is_kept_and_replaced_by_a_verified_download(self):
        self.saved.write_bytes(b"not an intact OCI archive")
        result = self.prepare()
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual(image_from_archive(result["archive"]), self.old_image)
        self.assertEqual(self.saved.read_bytes(), b"not an intact OCI archive")

    def test_a_record_without_an_archive_uses_the_normal_download_path(self):
        self.record["observed"].pop("archive_path")
        result = self.prepare()
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual(image_from_archive(result["archive"]), self.old_image)

    def test_a_symlink_is_not_used_as_the_saved_archive(self):
        link = self.root / "linked.tar"
        link.symlink_to(self.saved)
        self.record["observed"]["archive_path"] = str(link)
        self.prepare()
        self.assertEqual(len(self.downloads), 1)
        self.assertNotIn(link, self.verifications)
        self.assertTrue(link.is_symlink())

    def test_saved_cache_does_not_hide_a_registry_failure(self):
        self.registry_error = RuntimeError("registry unavailable")
        with self.assertRaisesRegex(RuntimeError, "registry unavailable"):
            self.prepare()
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.verifications, [])


if __name__ == "__main__":
    unittest.main()
