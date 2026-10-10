"""A host directory is mounted with what the host has mounted inside it, as
the network shares under /mnt/pve: Proxmox mounts the directory alone, and the
container would find an empty folder in the place of each share."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_nested_mounts as nested
import oci_runtime_settings as runtime_settings
import oci_stack_replay

CONFIG = """arch: amd64
hostname: duplicati
mp0: local-lvm:vm-113-disk-1,mp=/config,backup=1,size=16G
mp1: /mnt/pve,mp=/source,backup=0,ro=1
mp2: /mnt/backups,mp=/backups,backup=0
unprivileged: 1
"""
READ_WRITE = "lxc.mount.entry: /mnt/backups backups none rbind,rslave,create=dir 0 0"
READ_ONLY = "lxc.mount.entry: /mnt/pve source none rbind,rslave,ro,create=dir 0 0"
HOOK = ("lxc.hook.mount: /bin/sh -c 'mount -o remount,bind,ro=recursive "
        "\"$LXC_ROOTFS_MOUNT/source\"'")


def lines(config):
    return [line for group in nested.groups(config.encode()) for line in group]


class LinesTests(unittest.TestCase):
    def test_every_host_directory_gets_an_entry_that_follows_the_host(self):
        self.assertEqual(lines(CONFIG), [READ_WRITE, READ_ONLY, HOOK])

    def test_a_volume_gets_none(self):
        self.assertEqual(lines("mp0: local-lvm:vm-113-disk-1,mp=/config,backup=1,size=16G\n"), [])

    def test_read_only_reaches_what_is_mounted_inside(self):
        self.assertIn("ro=recursive", HOOK)
        self.assertEqual(lines("mp0: /mnt/pve,mp=/source,backup=0,ro=1\n"), [READ_ONLY, HOOK])

    def test_the_kernel_trees_of_a_host_monitor_stay_as_the_recipe_lays_them_out(self):
        config = ("mp0: /proc,mp=/host/proc,backup=0,ro=1\nmp1: /sys,mp=/host/sys,backup=0,ro=1\n"
                  "mp2: /sys/fs/cgroup,mp=/host/sys/fs/cgroup,backup=0,ro=1\n")
        self.assertEqual(lines(config), [])

    def test_a_path_that_would_break_the_entry_keeps_the_plain_mount_point(self):
        for source in ("/mnt/it's", "/mnt/a$b", "/mnt/a`b", '/mnt/a"b', "/mnt/a\\040b"):
            self.assertEqual(lines(f"mp0: {source},mp=/data,backup=0\n"), [], source)

    def test_a_directory_goes_before_the_ones_mounted_inside_it(self):
        config = "mp0: /mnt/pve/media,mp=/data/media,backup=0\nmp1: /mnt/pve,mp=/data,backup=0\n"
        self.assertEqual([line.split()[2] for line in lines(config)], ["data", "data/media"])


class CheckTests(unittest.TestCase):
    def config(self, *extra):
        return (CONFIG + "".join(line + "\n" for line in extra)).encode()

    def test_the_lines_of_the_mount_points_are_accepted(self):
        nested.check(self.config(READ_WRITE, READ_ONLY, HOOK))

    def test_a_container_installed_before_has_none_and_is_accepted(self):
        nested.check(self.config())

    def test_an_entry_without_its_mount_point_is_refused(self):
        with self.assertRaises(ValueError):
            nested.check(self.config("lxc.mount.entry: /etc secrets none rbind,rslave,create=dir 0 0"))

    def test_an_entry_that_is_not_read_only_as_its_mount_point_is_refused(self):
        with self.assertRaises(ValueError):
            nested.check(self.config("lxc.mount.entry: /mnt/pve source none rbind,rslave,create=dir 0 0"))

    def test_a_read_only_entry_without_its_hook_is_refused(self):
        with self.assertRaises(ValueError):
            nested.check(self.config(READ_ONLY))

    def test_a_repeated_entry_is_refused(self):
        with self.assertRaises(ValueError):
            nested.check(self.config(READ_WRITE, READ_WRITE))


class OtherChecksTests(unittest.TestCase):
    def test_they_are_not_seen_as_part_of_an_acceleration_profile(self):
        config = (CONFIG + READ_WRITE + "\n" + READ_ONLY + "\n" + HOOK + "\n").encode()
        left = runtime_settings.filter_config(config, {"mounts": []}).decode()
        self.assertNotIn("lxc.mount.entry", left)
        self.assertNotIn("lxc.hook.mount", left)
        self.assertIn("mp1: /mnt/pve", left)

    def test_another_hook_is_not_taken_for_one_of_these(self):
        other = "lxc.hook.mount: /usr/local/lib/proxmenux/oci/nvidia-mount-" + "a" * 64 + ".sh"
        self.assertFalse(nested.own(other))
        self.assertIn(other.encode(), nested.without((CONFIG + other + "\n" + HOOK + "\n").encode()))

    def test_a_rebuilt_stack_member_does_not_replay_them(self):
        source = Path(oci_stack_replay.__file__).read_text()
        self.assertIn("not oci_nested_mounts.own(line)", source)


class FollowTests(unittest.TestCase):
    def follow(self, text):
        with tempfile.TemporaryDirectory() as directory:
            conf = Path(directory) / "113.conf"
            conf.write_text(text)
            with patch.object(nested, "Path", lambda value: conf):
                nested.follow(113)
            return conf.read_text()

    def test_the_lines_are_written_after_the_rest_of_the_configuration(self):
        self.assertEqual(self.follow(CONFIG), CONFIG + READ_WRITE + "\n" + READ_ONLY + "\n" + HOOK + "\n")

    def test_writing_them_again_changes_nothing(self):
        once = self.follow(CONFIG)
        self.assertEqual(self.follow(once), once)

    def test_the_lines_of_a_removed_mount_point_go_with_it(self):
        once = self.follow(CONFIG)
        removed = once.replace("mp1: /mnt/pve,mp=/source,backup=0,ro=1\n", "")
        self.assertEqual(self.follow(removed), removed.replace(READ_ONLY + "\n" + HOOK + "\n", ""))

    def test_they_come_after_the_line_that_clears_the_hooks_of_a_host_monitor(self):
        text = self.follow(CONFIG + HOOK + "\nlxc.hook.mount: \n")
        self.assertLess(text.index("lxc.hook.mount: \n"), text.index(HOOK))
        self.assertEqual(text.count(HOOK), 1)

    def test_a_snapshot_section_is_left_as_it_is(self):
        snapshot = "\n[before]\narch: amd64\nmp1: /mnt/old,mp=/old,backup=0\n"
        text = self.follow(CONFIG + snapshot)
        self.assertTrue(text.endswith(snapshot))
        self.assertNotIn("/mnt/old old", text)


if __name__ == "__main__":
    unittest.main()
