"""Images whose User Proxmox cannot resolve are stopped before pct create."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))
import oci_runtime as runtime


def _tar(entries):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        for name, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                body = b"root:x:0:0::/:/bin/sh\n"
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
    return data.getvalue()


def _blob(archive, data):
    digest = hashlib.sha256(data).hexdigest()
    info = tarfile.TarInfo(f"blobs/sha256/{digest}")
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))
    return f"sha256:{digest}", len(data)


def build(path, layers, user="1000:1000", compression="gzip"):
    """layers: list of entry lists, bottom first."""
    with tarfile.open(path, "w") as archive:
        descriptors, diff_ids = [], []
        for entries in layers:
            raw = _tar(entries)
            diff_ids.append("sha256:" + hashlib.sha256(raw).hexdigest())
            if compression == "gzip":
                data, media = gzip.compress(raw), "application/vnd.oci.image.layer.v1.tar+gzip"
            elif compression == "zstd":
                data = subprocess.run(["zstd", "-q", "-c"], input=raw, capture_output=True, check=True).stdout
                media = "application/vnd.oci.image.layer.v1.tar+zstd"
            else:
                data, media = raw, "application/vnd.oci.image.layer.v1.tar"
            digest, size = _blob(archive, data)
            descriptors.append({"mediaType": media, "digest": digest, "size": size})
        config = {"architecture": "amd64", "os": "linux", "config": {"User": user} if user else {},
                  "rootfs": {"type": "layers", "diff_ids": diff_ids}}
        config_digest, config_size = _blob(archive, json.dumps(config).encode())
        manifest = {"schemaVersion": 2, "config": {"digest": config_digest, "size": config_size},
                    "layers": descriptors}
        manifest_digest, manifest_size = _blob(archive, json.dumps(manifest).encode())
        index = json.dumps({"schemaVersion": 2, "manifests": [
            {"digest": manifest_digest, "size": manifest_size}]}).encode()
        info = tarfile.TarInfo("index.json")
        info.size = len(index)
        archive.addfile(info, io.BytesIO(index))


class UserDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        self.path = self.folder / "image.tar"

    def test_scratch_image_with_a_numeric_user_lacks_both_files(self):
        build(self.path, [[("updater", "dir"), ("updater/app", "file")]])
        self.assertEqual(runtime.missing_user_databases(self.path), ["/etc/passwd", "/etc/group"])

    def test_image_with_its_user_databases_is_accepted(self):
        build(self.path, [[("etc", "dir"), ("etc/passwd", "file"), ("etc/group", "file")], [("app", "file")]])
        self.assertEqual(runtime.missing_user_databases(self.path), [])

    def test_image_without_user_reads_no_layer(self):
        build(self.path, [[("app", "file")]], user="")
        with patch.object(runtime, "_layer_entries", side_effect=AssertionError("layers read")):
            self.assertEqual(runtime.missing_user_databases(self.path), [])

    def test_a_later_layer_that_removes_passwd_is_respected(self):
        build(self.path, [[("etc", "dir"), ("etc/passwd", "file"), ("etc/group", "file")],
                          [("etc/.wh.passwd", "file")]])
        self.assertEqual(runtime.missing_user_databases(self.path), ["/etc/passwd"])

    def test_a_later_layer_that_removes_etc_is_respected(self):
        build(self.path, [[("etc", "dir"), ("etc/passwd", "file"), ("etc/group", "file")],
                          [(".wh.etc", "file")]])
        self.assertEqual(runtime.missing_user_databases(self.path), ["/etc/passwd", "/etc/group"])

    def test_paths_with_a_leading_dot_slash_are_recognised(self):
        build(self.path, [[("./etc/", "dir"), ("./etc/passwd", "file"), ("./etc/group", "file")]])
        self.assertEqual(runtime.missing_user_databases(self.path), [])

    def test_uncompressed_layers_are_read(self):
        build(self.path, [[("etc/passwd", "file"), ("etc/group", "file")]], compression="none")
        self.assertEqual(runtime.missing_user_databases(self.path), [])

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_zstd_layers_are_read(self):
        build(self.path, [[("app", "file")]], compression="zstd")
        self.assertEqual(runtime.missing_user_databases(self.path), ["/etc/passwd", "/etc/group"])

    def test_command_line_reports_missing_files_with_exit_code_3(self):
        build(self.path, [[("app", "file")]])
        result = subprocess.run([sys.executable, str(ROOT / "remote/oci_runtime.py"), "--user-databases",
                                 str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout.split(), ["/etc/passwd", "/etc/group"])

    def test_installer_creates_from_a_copy_with_the_missing_files(self):
        script = (ROOT / "remote/install_oci.sh").read_text()
        check = script.index('--user-databases "$ARCHIVE_PATH"')
        create = script.index('oci_create_container "${CREATE_ARGS[@]}"')
        self.assertLess(check, create)
        block = script[check:create]
        self.assertIn("user_databases_rc == 3", block)
        self.assertIn('--add-user-databases "$ARCHIVE_PATH" "$USER_DATABASES_ARCHIVE"', block)
        self.assertIn("CREATE_ARGS[1]=$USER_DATABASES_ARCHIVE", block)
        self.assertIn('rm -f "$USER_DATABASES_ARCHIVE"', script[create:create + 300])


class AddUserDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        self.source = self.folder / "image.tar"
        self.copy = self.folder / "copy.tar"

    def read(self, path):
        with tarfile.open(path) as archive:
            def blob(digest):
                return archive.extractfile(f"blobs/sha256/{digest.split(':')[1]}").read()
            index = json.load(archive.extractfile("index.json"))
            descriptor = index["manifests"][0]
            manifest_data = blob(descriptor["digest"])
            manifest = json.loads(manifest_data)
            config_data = blob(manifest["config"]["digest"])
            top = blob(manifest["layers"][-1]["digest"])
        return index, descriptor, manifest_data, manifest, config_data, top

    def test_a_scratch_image_gains_both_files_and_the_original_is_kept(self):
        build(self.source, [[("updater", "dir"), ("updater/app", "file")]])
        original = self.source.read_bytes()
        self.assertEqual(runtime.add_user_databases(self.source, self.copy), ["/etc/passwd", "/etc/group"])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(runtime.missing_user_databases(self.copy), [])
        index, descriptor, manifest_data, manifest, config_data, top = self.read(self.copy)
        self.assertEqual(len(index["manifests"]), 1)
        self.assertEqual(descriptor["digest"], "sha256:" + hashlib.sha256(manifest_data).hexdigest())
        self.assertEqual(manifest["config"]["digest"], "sha256:" + hashlib.sha256(config_data).hexdigest())
        config = json.loads(config_data)
        self.assertEqual(config["config"]["User"], "1000:1000")
        self.assertEqual(len(config["rootfs"]["diff_ids"]), len(manifest["layers"]))
        self.assertEqual(config["rootfs"]["diff_ids"][-1], "sha256:" + hashlib.sha256(top).hexdigest())
        with tarfile.open(fileobj=io.BytesIO(top)) as layer:
            self.assertEqual(layer.extractfile("etc/passwd").read(), b"root:x:0:0:root:/root:/sbin/nologin\n")
            self.assertEqual({item.uid for item in layer.getmembers()}, {0})

    def test_only_the_missing_file_is_added(self):
        build(self.source, [[("etc", "dir"), ("etc/passwd", "file")]])
        self.assertEqual(runtime.add_user_databases(self.source, self.copy), ["/etc/group"])
        with tarfile.open(fileobj=io.BytesIO(self.read(self.copy)[5])) as layer:
            self.assertEqual(sorted(layer.getnames()), ["etc", "etc/group"])

    def test_an_image_that_needs_nothing_is_not_copied(self):
        build(self.source, [[("etc/passwd", "file"), ("etc/group", "file")]])
        self.assertEqual(runtime.add_user_databases(self.source, self.copy), [])
        self.assertFalse(self.copy.exists())

    def test_a_named_user_is_not_invented(self):
        for user in ("app", "1000:app"):
            build(self.source, [[("app", "file")]], user=user)
            with self.assertRaises(runtime.RuntimeResolutionError):
                runtime.add_user_databases(self.source, self.copy)
            self.assertFalse(self.copy.exists())
            self.assertEqual(list(self.folder.glob("*.partial")), [])


if __name__ == "__main__":
    unittest.main()
