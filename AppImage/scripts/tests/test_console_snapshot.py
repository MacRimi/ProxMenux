"""Tests for the console snapshot contract and lease-gated publisher."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import console_snapshot


FIXTURES = Path(__file__).parent / "fixtures" / "console"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ConsoleSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "monitor" / "console.json"
        self.state_dir = self.root / "console"
        self.resources = fixture("pvesh_cluster_resources.json")
        self.status = fixture("pvesh_cluster_status.json")
        console_snapshot._publisher = None
        self.addCleanup(setattr, console_snapshot, "_publisher", None)

    def publisher(self, resources=None, status=None, version=None):
        return console_snapshot.Publisher(
            get_node_name=lambda: "p3-01",
            get_resources=lambda: self.resources if resources is None else resources(),
            run_pvesh=lambda: self.status if status is None else status(),
            read_language=lambda: "es",
            path=self.path,
            state_dir=self.state_dir,
            clock=lambda: 100.0,
            version=version,
        )

    def lease(self, now=100):
        lease = self.state_dir / "client" / "lease"
        lease.parent.mkdir(parents=True, exist_ok=True)
        lease.write_text("", encoding="utf-8")
        os.utime(lease, (now, now))
        return lease

    def test_normalizes_complete_resources_and_missing_fields(self):
        result = console_snapshot.normalize_resources(self.resources)
        self.assertEqual(set(result), {"nodes", "guests", "storages", "truncated"})
        self.assertEqual(result["nodes"][0]["name"], "p3-01")
        self.assertEqual(result["nodes"][0]["cgroup_mode"], 2)
        self.assertIsNone(result["nodes"][1]["cpu"])
        self.assertEqual(result["guests"][0]["tags"], ["media", "prod"])
        self.assertIsNone(result["guests"][0]["diskread"])
        self.assertEqual(result["guests"][1]["tags"], ["edge", "\x1b[31mred\nline"])
        self.assertEqual(result["storages"][0]["content"], ["images", "rootdir"])

    def test_cluster_quorum_offline_and_standalone(self):
        cluster = console_snapshot.normalize_cluster_status(self.status)
        self.assertEqual((cluster["is_cluster"], cluster["quorate"]), (True, True))
        self.assertEqual((cluster["nodes_total"], cluster["nodes_online"]), (2, 1))
        self.assertFalse(cluster["members"][1]["online"])
        no_quorum = console_snapshot.normalize_cluster_status(
            fixture("pvesh_no_quorum_status.json"))
        self.assertEqual((no_quorum["quorate"], no_quorum["nodes_online"]),
                         (False, 1))
        standalone = console_snapshot.normalize_cluster_status(fixture("pvesh_standalone_status.json"))
        self.assertEqual((standalone["is_cluster"], standalone["name"]), (False, None))

    def test_truncates_2500_guests_by_cpu_cores_then_memory(self):
        guests = [{"type": "qemu", "vmid": i, "cpu": i / 2500, "maxcpu": 2,
                   "mem": 2500 - i} for i in range(2500)]
        result = console_snapshot.normalize_resources(guests)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["guests"]), 2000)
        self.assertEqual((result["guests"][0]["vmid"], result["guests"][-1]["vmid"]),
                         (2499, 500))

    def test_published_file_stays_within_one_megabyte(self):
        large = [{"type": "qemu", "vmid": i, "name": "g" * 1000,
                  "cpu": i / 2500, "maxcpu": 2} for i in range(2500)]
        publisher = self.publisher(resources=lambda: large)
        self.lease()
        publisher.publish_once(100.0)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertLessEqual(self.path.stat().st_size, 1024 * 1024)
        self.assertTrue(data["resources"]["truncated"])
        self.assertEqual(data["resources"]["guests"][0]["vmid"], 2499)

    def test_initial_snapshot_and_idempotent_ensure(self):
        with mock.patch.object(console_snapshot.threading, "Thread") as thread:
            first = console_snapshot.ensure_publisher(
                lambda: "p3-01", lambda: self.resources, lambda: self.status,
                lambda: "es", path=self.path, state_dir=self.state_dir,
                clock=lambda: 100.0, version="9.9.9",
            )
            second = console_snapshot.ensure_publisher(
                lambda: "other", lambda: [], lambda: [], lambda: "en",
                path=self.path, state_dir=self.state_dir,
            )
        self.assertIs(first, second)
        self.assertEqual(thread.call_count, 1)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((data["cluster"]["status"], data["resources"]["status"]),
                         ("starting", "starting"))
        self.assertEqual(data["node"]["name"], "p3-01")
        self.assertEqual(data["generator"]["version"], "9.9.9")

    def test_unwritable_snapshot_path_does_not_break_ensure_publisher(self):
        blocked = self.root / "blocked"
        blocked.write_text("", encoding="utf-8")
        with mock.patch.object(console_snapshot.threading, "Thread") as thread:
            publisher = console_snapshot.ensure_publisher(
                lambda: "p3-01", lambda: self.resources, lambda: self.status,
                lambda: "es", path=blocked / "console.json", state_dir=self.state_dir,
                clock=lambda: 100.0,
            )
        self.assertIsInstance(publisher, console_snapshot.Publisher)
        self.assertEqual(thread.call_count, 1)
        thread.return_value.start.assert_called_once_with()

    def test_generator_version_comes_from_caller(self):
        self.lease()
        self.publisher(version="9.9.9").publish_once(100.0)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["generator"]["version"], "9.9.9")
        self.publisher().publish_once(100.0)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIsNone(data["generator"]["version"])

    def test_lease_gates_calls_and_publishes_immediately(self):
        calls = {"resources": 0, "cluster": 0}
        def resources():
            calls["resources"] += 1
            return self.resources
        def status():
            calls["cluster"] += 1
            return self.status
        publisher = self.publisher(resources, status)
        self.assertFalse(publisher.publish_once(100.0))
        self.assertEqual(calls, {"resources": 0, "cluster": 0})
        self.lease()
        self.assertTrue(publisher.publish_once(100.0))
        self.assertEqual(calls, {"resources": 1, "cluster": 1})
        self.assertFalse(publisher.publish_once(104.0))
        self.assertTrue(publisher.publish_once(105.0))
        self.assertEqual(calls, {"resources": 2, "cluster": 1})
        self.assertTrue(publisher.publish_once(110.0))
        self.assertEqual(calls, {"resources": 3, "cluster": 2})
        self.assertFalse(publisher.publish_once(115.0))
        self.assertEqual(calls, {"resources": 3, "cluster": 2})

    def test_symlink_and_directory_lease_are_ignored(self):
        publisher = self.publisher()
        lease = self.state_dir / "client" / "lease"
        lease.parent.mkdir(parents=True)
        target = self.root / "target"
        target.write_text("", encoding="utf-8")
        lease.symlink_to(target)
        self.assertFalse(publisher.publish_once(100.0))
        lease.unlink()
        lease.mkdir()
        self.assertFalse(publisher.publish_once(102.0))

    def test_failure_states_preserve_last_success_and_trim_error(self):
        fail = False
        def resources():
            if fail:
                raise RuntimeError("x" * 300)
            return self.resources
        publisher = self.publisher(resources)
        self.lease(now=100)
        publisher.publish_once(100.0)
        fail = True
        publisher.publish_once(105.0)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["resources"]["status"], "stale")
        self.assertEqual(data["resources"]["observed_at"], 100.0)
        self.assertEqual(len(data["resources"]["error"]), 200)
        publisher.publish_once(110.0)
        self.lease(now=115)
        publisher.publish_once(115.0)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["resources"]["status"], "error")
        self.assertEqual(len(data["resources"]["guests"]), 2)

    def test_unavailable_before_first_success(self):
        def fail():
            raise RuntimeError("offline")
        publisher = self.publisher(fail, fail)
        self.lease()
        publisher.publish_once(100.0)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["resources"]["status"], "unavailable")
        self.assertEqual(data["cluster"]["status"], "unavailable")

    def test_atomic_write_and_permissions_with_and_without_group(self):
        data = {"schema": 1}
        with mock.patch.object(console_snapshot.grp, "getgrnam", side_effect=KeyError):
            console_snapshot.write_snapshot(data, self.path)
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        group = mock.Mock(gr_gid=os.getgid())
        with mock.patch.object(console_snapshot.grp, "getgrnam", return_value=group), \
             mock.patch.object(console_snapshot.os, "replace", wraps=os.replace) as replace:
            console_snapshot.write_snapshot(data, self.path)
            self.assertEqual(replace.call_count, 1)
            self.assertEqual(Path(replace.call_args.args[0]).parent, self.path.parent)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o750)

    def test_reader_rejects_bad_schema_corruption_and_clock_skew(self):
        self.assertEqual(console_snapshot.load_snapshot(self.path, 100).resources["status"],
                         "unavailable")
        self.path.parent.mkdir()
        self.path.write_text('{', encoding="utf-8")
        self.assertEqual(console_snapshot.load_snapshot(self.path, 100).resources["status"],
                         "unavailable")
        self.path.write_text('{"schema":2}', encoding="utf-8")
        self.assertEqual(console_snapshot.load_snapshot(self.path, 100).resources["status"],
                         "unavailable")
        publisher = self.publisher()
        self.lease()
        publisher.publish_once(100.0)
        self.assertEqual(console_snapshot.load_snapshot(self.path, 99).age_s, 0)

    def test_reader_sanitizes_names_tags_and_negative_metrics(self):
        publisher = self.publisher()
        self.lease()
        publisher.publish_once(100.0)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        guest = data["resources"]["guests"][0]
        guest["name"] = "\x1b[31m" + "a" * 80
        guest["cpu"] = -1
        guest["tags"] = ["\x1b[31m" + "t" * 40] * 20
        self.path.write_text(json.dumps(data), encoding="utf-8")
        read = console_snapshot.load_snapshot(self.path, 101)
        guest = read.resources["guests"][0]
        self.assertEqual(guest["name"], "a" * 64)
        self.assertIsNone(guest["cpu"])
        self.assertEqual(guest["tags"], ["t" * 32] * 16)

    def test_reader_strips_c1_control_characters(self):
        publisher = self.publisher()
        self.lease()
        publisher.publish_once(100.0)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["resources"]["guests"][0]["name"] = "\u009b31mok\u0080\u009f"
        self.path.write_text(json.dumps(data), encoding="utf-8")
        guest = console_snapshot.load_snapshot(self.path, 101).resources["guests"][0]
        self.assertNotIn("\u009b", guest["name"])
        self.assertEqual(guest["name"], "31mok")

    def test_touch_lease_creates_regular_file_and_refreshes_timestamp(self):
        lease = console_snapshot.touch_lease(self.state_dir, now=100)
        self.assertTrue(lease.is_file())
        self.assertEqual(lease.stat().st_mtime, 100)
        console_snapshot.touch_lease(self.state_dir, now=105)
        self.assertEqual(lease.stat().st_mtime, 105)

    def test_pve_version_callback_is_cached_for_300_seconds(self):
        calls = []
        def version():
            calls.append(1)
            return "pve-manager/9.0.3"
        publisher = console_snapshot.Publisher(
            lambda: "p3-01", lambda: self.resources, lambda: self.status,
            lambda: "en", path=self.path, state_dir=self.state_dir,
            get_pve_version=version,
        )
        self.assertEqual(publisher._node(100)["pve_version"], "pve-manager/9.0.3")
        self.assertEqual(publisher._node(399)["pve_version"], "pve-manager/9.0.3")
        self.assertEqual(len(calls), 1)
        publisher._node(400)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
