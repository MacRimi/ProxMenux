"""The record of an installation travels inside its container, so a backup
restored on another host still carries it."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_carried_record as carried


def bundle(**extra):
    return {"schema_version": 1, "kind": carried.KIND, "node": "pve", "vmid": 120,
            "record": {"vmid": 120, "installation_id": "488ed3cb-1145-477a-b90f-c46777d69fb2"}, **extra}


class CarriedRecordTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.rootfs = Path(tmp.name) / "rootfs"
        self.rootfs.mkdir()
        self.outside = Path(tmp.name) / "outside"
        self.outside.mkdir()
        self.owner = (os.getuid(), os.getgid())

    def test_the_copy_is_private_and_read_back_as_written(self):
        carried.write_copy(self.rootfs, bundle(), self.owner)
        path = self.rootfs / carried.DIRECTORY / carried.NAME
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(carried.read_copy(self.rootfs), bundle())
        self.assertEqual(os.listdir(path.parent), [carried.NAME])

    def test_a_newer_record_replaces_the_copy(self):
        carried.write_copy(self.rootfs, bundle(), self.owner)
        carried.write_copy(self.rootfs, bundle(node="other"), self.owner)
        self.assertEqual(carried.read_copy(self.rootfs)["node"], "other")

    def test_a_link_left_in_place_of_the_folder_is_not_followed(self):
        (self.rootfs / carried.DIRECTORY).symlink_to(self.outside)
        with self.assertRaises(OSError):
            carried.write_copy(self.rootfs, bundle(), self.owner)
        self.assertEqual(os.listdir(self.outside), [])
        (self.outside / carried.NAME).write_text(json.dumps(bundle()))
        self.assertIsNone(carried.read_copy(self.rootfs))

    def test_a_link_left_in_place_of_the_copy_is_not_followed(self):
        (self.outside / "secret").write_text(json.dumps(bundle()))
        (self.rootfs / carried.DIRECTORY).mkdir()
        (self.rootfs / carried.DIRECTORY / carried.NAME).symlink_to(self.outside / "secret")
        self.assertIsNone(carried.read_copy(self.rootfs))

    def test_what_is_not_a_copy_is_not_read(self):
        self.assertIsNone(carried.read_copy(self.rootfs))
        folder = self.rootfs / carried.DIRECTORY
        folder.mkdir()
        for content in ("not json", json.dumps([1]), json.dumps(bundle(kind="other")),
                        json.dumps(bundle(schema_version=2)), json.dumps({**bundle(), "record": "text"})):
            (folder / carried.NAME).write_text(content)
            self.assertIsNone(carried.read_copy(self.rootfs), content)

    def test_the_time_it_was_saved_does_not_make_a_copy_different(self):
        self.assertEqual(carried.digest(bundle(saved_at="2026-10-03")), carried.digest(bundle(saved_at="2026-10-04")))
        self.assertEqual(carried.digest(bundle(generation="a")), carried.digest(bundle(generation="b")))
        self.assertNotEqual(carried.digest(bundle()), carried.digest(bundle(node="other")))

    def test_the_owner_is_root_of_the_container(self):
        self.assertEqual(carried.mapped_root("arch: amd64\nunprivileged: 1\n"), (100000, 100000))
        self.assertEqual(carried.mapped_root("arch: amd64\n"), (0, 0))
        custom = "unprivileged: 1\nlxc.idmap: u 0 200000 65536\nlxc.idmap: g 0 300000 65536\nlxc.idmap: u 1000 1000 1\n"
        self.assertEqual(carried.mapped_root(custom), (200000, 300000))


if __name__ == "__main__":
    unittest.main()
