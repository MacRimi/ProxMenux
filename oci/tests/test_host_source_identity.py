"""A shared host directory is recognised by its path, its folder and the
filesystem it is on, not by the device number the host gives that filesystem:
the number changes on every boot and every time a disk is connected."""

from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_host_mounts as host_mounts


def source(**changes):
    value = {"resolved_path": "/mnt/pve/usb/media", "exists": True, "device": 2081, "inode": 13,
             "uid": 1000, "gid": 1000, "mode": 0o775,
             "filesystem": "uuid:58a41de6-b98f-481a-9698-aee647fccba3", "fstype": "ext4"}
    value.update(changes)
    return value


def recorded_before(**changes):
    value = source(**changes)
    del value["filesystem"], value["fstype"]
    return value


class SameSourceTests(unittest.TestCase):
    def test_a_disk_that_comes_back_under_another_device_is_the_same_source(self):
        self.assertTrue(host_mounts.same_source(source(), source(device=2097)))

    def test_another_filesystem_in_the_same_place_is_not(self):
        other = source(filesystem="uuid:0c1f6a51-2d3e-4b7a-9f10-3a5b8f2d7c44")
        self.assertFalse(host_mounts.same_source(source(), other))
        # Not even when the host gives it the device number the first one had.
        self.assertFalse(host_mounts.same_source(source(), dict(other, device=2081)))

    def test_another_folder_or_another_path_is_not(self):
        self.assertFalse(host_mounts.same_source(source(), source(inode=14)))
        self.assertFalse(host_mounts.same_source(source(), source(resolved_path="/mnt/pve/usb/other")))
        self.assertFalse(host_mounts.same_source(source(), {"resolved_path": "/mnt/pve/usb/media", "exists": False}))

    def test_permissions_are_not_part_of_the_identity(self):
        self.assertTrue(host_mounts.same_source(source(), source(uid=101000, gid=101000, mode=0o2775)))

    def test_a_filesystem_that_renumbers_its_folders_is_told_by_its_identity(self):
        fat = source(filesystem="uuid:094E-2E73", fstype="exfat", inode=403)
        self.assertTrue(host_mounts.same_source(fat, dict(fat, inode=405)))
        self.assertFalse(host_mounts.same_source(fat, dict(fat, inode=405, filesystem="uuid:7EFB-F094")))

    def test_a_record_made_before_the_filesystem_was_looked_at_has_no_device_to_compare(self):
        self.assertTrue(host_mounts.same_source(recorded_before(), source(device=2097)))
        self.assertFalse(host_mounts.same_source(recorded_before(), source(inode=14)))

    def test_without_an_identity_the_device_number_is_what_is_left(self):
        unknown = source(filesystem=None)
        self.assertTrue(host_mounts.same_source(unknown, source(filesystem=None)))
        self.assertFalse(host_mounts.same_source(unknown, source(filesystem=None, device=2097)))

    def test_two_missing_directories_at_the_same_path_are_the_same(self):
        missing = {"resolved_path": "/mnt/new", "exists": False}
        self.assertTrue(host_mounts.same_source(missing, dict(missing)))


class FilesystemTests(unittest.TestCase):
    MOUNTS = (
        "34 2 252:1 / / rw,relatime shared:1 - ext4 /dev/mapper/pve-root rw\n"
        "314 34 0:68 / /mnt/pve/Public rw,relatime shared:310 - nfs4 192.168.0.15:/volume3/Public rw,vers=4.1\n"
        "90 34 0:44 / /tank/media rw,relatime - zfs tank/media rw,xattr\n"
        "95 34 8:33 / /mnt/pve/usb rw,relatime - ext4 /dev/sdc1 rw\n"
        "96 34 8:49 / /mnt/my\\040disk rw,relatime - exfat /dev/sdd1 rw\n"
    )

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.mounts = Path(directory.name) / "mountinfo"
        self.mounts.write_text(self.MOUNTS)
        patcher = patch.object(host_mounts, "MOUNTINFO", self.mounts)
        patcher.start()
        self.addCleanup(patcher.stop)

    def blocks(self, uuids):
        """The host as seen by the module: these devices exist and have these UUIDs."""
        real = host_mounts.os.stat

        def fake(path, *args, **kwargs):
            if str(path) in uuids:
                return SimpleNamespace(st_mode=stat.S_IFBLK | 0o660, st_rdev=1)
            return real(path, *args, **kwargs)
        return (patch.object(host_mounts.os, "stat", side_effect=fake),
                patch.object(host_mounts, "_uuid", side_effect=lambda device: uuids.get(device)))

    def test_a_network_share_or_a_dataset_is_told_by_what_is_mounted(self):
        self.assertEqual(host_mounts.filesystem("/mnt/pve/Public/films"),
                         ("nfs4:192.168.0.15:/volume3/Public", "nfs4"))
        self.assertEqual(host_mounts.filesystem("/tank/media"), ("zfs:tank/media", "zfs"))

    def test_a_disk_is_told_by_the_uuid_of_its_filesystem(self):
        stat_patch, uuid_patch = self.blocks({"/dev/sdc1": "58a41de6", "/dev/sdd1": "094E-2E73",
                                              "/dev/mapper/pve-root": "93310121"})
        with stat_patch, uuid_patch:
            self.assertEqual(host_mounts.filesystem("/mnt/pve/usb/media"), ("uuid:58a41de6", "ext4"))
            # The longest mount point above the path, with its spaces.
            self.assertEqual(host_mounts.filesystem("/mnt/my disk/photos"), ("uuid:094E-2E73", "exfat"))
            self.assertEqual(host_mounts.filesystem("/mnt/pve/usbstick"), ("uuid:93310121", "ext4"))

    def test_a_disk_whose_uuid_the_host_does_not_tell_has_no_identity(self):
        stat_patch, uuid_patch = self.blocks({"/dev/sdc1": None})
        with stat_patch, uuid_patch:
            self.assertEqual(host_mounts.filesystem("/mnt/pve/usb"), (None, "ext4"))

    def test_the_last_filesystem_mounted_on_a_place_is_the_one_there(self):
        self.mounts.write_text(self.MOUNTS + "97 34 0:70 / /tank/media rw - nfs4 nas:/media rw\n")
        self.assertEqual(host_mounts.filesystem("/tank/media/x"), ("nfs4:nas:/media", "nfs4"))

    def test_a_host_that_does_not_list_its_mounts_gives_no_identity(self):
        self.mounts.unlink()
        self.assertEqual(host_mounts.filesystem("/mnt/pve/usb"), (None, None))

    def test_the_snapshot_of_a_directory_carries_the_identity(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(host_mounts, "filesystem", return_value=("zfs:tank/media", "zfs")):
            value = host_mounts.snapshot(directory)
        self.assertEqual((value["filesystem"], value["fstype"], value["exists"]), ("zfs:tank/media", "zfs", True))
        self.assertIn("device", value)



class UpdateOfAnApplicationWithASharedDirectoryTests(unittest.TestCase):
    """The first thing an update or a modification does with the directories
    the application shares with the host."""

    def freeze(self, directory, recorded):
        import oci_instance_transaction as transaction
        mount = {"type": "host-bind", "source": directory, "container_path": "/media"}
        record = {"deployment": {"mounts": [mount]}, "observed": {"host_bind_sources": {directory: recorded}}}
        with patch.object(transaction, "log") as log:
            original, desired = transaction.freeze_host_sources(record, {"deployment": {"mounts": [mount]}}, True)
        return original, desired, [call.args[0] for call in log.call_args_list]

    def test_the_disk_came_back_under_another_device(self):
        with tempfile.TemporaryDirectory() as directory:
            now = host_mounts.snapshot(directory)
            # As the release before this one recorded it, and with the device it had then.
            recorded = {k: v for k, v in now.items() if k not in ("filesystem", "fstype")}
            recorded["device"] += 16
            original, desired, logged = self.freeze(directory, recorded)
            self.assertEqual(original[directory]["inode"], now["inode"])
            self.assertEqual(desired, original)
            self.assertTrue(any("identity of their filesystem" in line for line in logged))

    def test_another_folder_in_its_place_stops_the_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            recorded = dict(host_mounts.snapshot(directory))
            recorded["inode"] += 1
            with self.assertRaisesRegex(ValueError, "does not match its recorded identity"):
                self.freeze(directory, recorded)

    def test_another_filesystem_in_its_place_stops_the_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(host_mounts, "filesystem", return_value=("uuid:first", "ext4")):
                recorded = host_mounts.snapshot(directory)
            with patch.object(host_mounts, "filesystem", return_value=("uuid:second", "ext4")), \
                    self.assertRaisesRegex(ValueError, "does not match its recorded identity"):
                self.freeze(directory, recorded)


if __name__ == "__main__":
    unittest.main()
