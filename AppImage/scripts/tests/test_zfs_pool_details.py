"""ZFS pool layout parsing for the Storage view; never imports flask_server.

Fixtures are real `zpool status -j --json-int -P` output from PVE 9 /
OpenZFS 2.4.4 hosts, with disk serials and WWNs replaced:
- zpool_status_multi_pool.json: mirror, mirror, raidz2, mirror (one member with
  slow I/Os). Captured without --json-int and normalised to integers.
- zpool_status_single_rpool.json: single disk directly under the root vdev.
- zpool_status_degraded_raidz1.json: file-backed raidz1 with one member
  offlined, plus log, cache and spare devices; never scrubbed.

Run: python3 -m unittest discover -s AppImage/scripts/tests -p test_zfs_pool_details.py -v
"""
import ast
import copy
import json
import posixpath
import re
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "flask_server.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
NAMES = {"_zfs_member_disk", "_zfs_errors", "_zfs_device", "_ZFS_PARITY_RE",
         "_zfs_vdev", "_zfs_pool_details"}


def fake_os(links=None, existing=()):
    """Minimal `os` stand-in: realpath via a symlink map, exists via a set."""
    links = links or {}
    return SimpleNamespace(path=SimpleNamespace(
        realpath=lambda p: links.get(p, p),
        exists=lambda p: p in existing,
        basename=posixpath.basename,
        dirname=posixpath.dirname,
    ))


def load(os_module=None):
    tree = ast.parse(SOURCE.read_text())
    nodes = [n for n in tree.body
             if (isinstance(n, ast.FunctionDef) and n.name in NAMES)
             or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in NAMES for t in n.targets))]
    found = {n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id for n in nodes}
    assert found == NAMES, NAMES - found
    env = {"os": os_module or fake_os(), "re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), env)
    return env


def pools(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())["pools"]


class ZfsPoolDetailsTests(unittest.TestCase):
    def setUp(self):
        self.details = load()["_zfs_pool_details"]

    def test_degraded_raidz1_with_log_cache_and_spare(self):
        pool = self.details(pools("zpool_status_degraded_raidz1")["pmx-test"])

        self.assertEqual([v["class"] for v in pool["vdevs"]], ["normal", "log", "cache", "spare"])
        raidz = pool["vdevs"][0]
        self.assertEqual((raidz["type"], raidz["parity"], raidz["state"]), ("raidz", 1, "DEGRADED"))
        self.assertEqual([d["state"] for d in raidz["devices"]], ["ONLINE", "OFFLINE", "ONLINE"])
        self.assertEqual(pool["vdevs"][3]["state"], "AVAIL")
        self.assertIsNone(pool["scan"])
        self.assertTrue(pool["status"].startswith("One or more devices has been taken offline"))
        self.assertNotIn("\t", pool["status"])
        self.assertNotIn("\n", pool["action"])
        # File vdevs have no block device behind them
        self.assertIsNone(raidz["devices"][0]["disk"])

    def test_single_disk_pool_is_a_disk_vdev(self):
        pool = self.details(pools("zpool_status_single_rpool")["rpool"])

        self.assertEqual(len(pool["vdevs"]), 1)
        vdev = pool["vdevs"][0]
        self.assertEqual((vdev["type"], vdev["class"], vdev["parity"]), ("disk", "normal", None))
        self.assertEqual(len(vdev["devices"]), 1)
        self.assertEqual(vdev["name"], vdev["devices"][0]["path"])

    def test_finished_scrub_has_no_progress_percentage(self):
        pool = self.details(pools("zpool_status_single_rpool")["rpool"])

        self.assertEqual((pool["scan"]["function"], pool["scan"]["state"]), ("SCRUB", "FINISHED"))
        self.assertEqual(pool["scan"]["end_time"], 1791674884)
        # issued/to_examine is 100.1% for this real scrub; only meaningful while running
        self.assertIsNone(pool["scan"]["percent"])

    def test_mirror_raidz2_and_slow_ios(self):
        multi = pools("zpool_status_multi_pool")
        parsed = {name: self.details(pool) for name, pool in multi.items()}

        self.assertEqual(parsed["tank-rz2"]["vdevs"][0]["parity"], 2)
        self.assertEqual(len(parsed["tank-rz2"]["vdevs"][0]["devices"]), 5)
        for name in ("rpool", "tank-m1", "tank-spin-1"):
            self.assertEqual(parsed[name]["vdevs"][0]["type"], "mirror", name)
        slow = [d["slow_ios"] for d in parsed["tank-m1"]["vdevs"][0]["devices"]]
        self.assertEqual(slow, [0, 69])
        # Member paths come from `path`, not the JSON key (which may drop -partN)
        paths = [d["path"] for p in parsed.values() for v in p["vdevs"] for d in v["devices"]]
        self.assertTrue(all(p.startswith("/dev/disk/") for p in paths), paths)

    def test_resilver_with_spare_swapping_in(self):
        # Synthetic: the degraded fixture with d2 FAULTED and the spare
        # attached under spare-1, as `zpool status` shows during a resilver.
        raw = copy.deepcopy(pools("zpool_status_degraded_raidz1")["pmx-test"])
        members = raw["vdevs"]["pmx-test"]["vdevs"]["raidz1-0"]["vdevs"]
        failed = members.pop("/root/zfstest/d2.img")
        failed.update(state="FAULTED", read_errors=12)
        spare = dict(raw["spares"]["/root/zfstest/d6.img"], state="ONLINE")
        members["spare-1"] = {"name": "spare-1", "vdev_type": "spare", "state": "DEGRADED",
                              "vdevs": {"d2": failed, "d6": spare}}
        raw["spares"]["/root/zfstest/d6.img"]["state"] = "INUSE"
        raw["scan_stats"] = {"function": "RESILVER", "state": "SCANNING", "start_time": 1,
                             "end_time": 0, "to_examine": 1000, "issued": 425, "errors": 0,
                             "processed": 0}

        pool = self.details(raw)

        devices = pool["vdevs"][0]["devices"]
        self.assertEqual([d["via"] for d in devices], [None, None, "spare-1", "spare-1"])
        self.assertEqual(devices[2]["read_errors"], 12)
        self.assertEqual(pool["scan"]["percent"], 42.5)
        self.assertEqual(pool["vdevs"][-1]["state"], "INUSE")

    def test_output_is_json_serialisable_without_guids(self):
        for name, pool in pools("zpool_status_multi_pool").items():
            text = json.dumps(self.details(pool))
            self.assertNotIn("guid", text, name)


class ZfsMemberDiskTests(unittest.TestCase):
    def test_partition_resolves_to_parent_disk(self):
        member_disk = load(fake_os(
            links={"/dev/disk/by-partlabel/ssd-t1": "/dev/sdf1",
                   "/sys/class/block/sdf1": "/sys/devices/pci0000:00/0000:02:00.1/ata1/host0/target0:0:0/0:0:0:0/block/sdf/sdf1"},
            existing={"/sys/class/block/sdf1/partition"},
        ))["_zfs_member_disk"]
        self.assertEqual(member_disk("/dev/disk/by-partlabel/ssd-t1"), "sdf")

    def test_nvme_partition_resolves_to_namespace(self):
        member_disk = load(fake_os(
            links={"/dev/disk/by-id/nvme-X-part3": "/dev/nvme0n1p3",
                   "/sys/class/block/nvme0n1p3": "/sys/devices/pci0000:00/0000:08:00.0/nvme/nvme0/nvme0n1/nvme0n1p3"},
            existing={"/sys/class/block/nvme0n1p3/partition"},
        ))["_zfs_member_disk"]
        self.assertEqual(member_disk("/dev/disk/by-id/nvme-X-part3"), "nvme0n1")

    def test_whole_disk_member(self):
        member_disk = load(fake_os(
            links={"/dev/disk/by-id/wwn-0x1": "/dev/sdj"},
            existing={"/sys/class/block/sdj"},
        ))["_zfs_member_disk"]
        self.assertEqual(member_disk("/dev/disk/by-id/wwn-0x1"), "sdj")

    def test_missing_device_and_file_vdev_give_none(self):
        member_disk = load(fake_os())["_zfs_member_disk"]
        self.assertIsNone(member_disk("/dev/disk/by-id/gone"))
        self.assertIsNone(member_disk("/root/zfstest/d1.img"))


if __name__ == "__main__":
    unittest.main()
