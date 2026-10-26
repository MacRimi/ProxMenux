"""Tests for the console snapshot contract and lease-gated publisher."""

import ast
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import console_snapshot


FIXTURES = Path(__file__).parent / "fixtures" / "console"
SERVER_SOURCE = SCRIPTS_DIR / "flask_server.py"
# pvesh get /nodes/<n>/rrddata --timeframe hour --cf AVERAGE, recorded on a
# PVE 9 node: 60 rows at 60 s, the newest at RRD_END.
RRD_END = 1793050560


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def legacy_reader():
    """The snapshot reader deployed with 1537d8f2, frozen below."""
    module = ModuleType("legacy_console_snapshot")
    exec(compile(LEGACY_READER_1537D8F2, "legacy_console_snapshot", "exec"),
         module.__dict__)
    return module


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def cluster_status(names, offline=()):
    return ([{"type": "cluster", "name": "lab", "quorate": 1,
              "nodes": len(names), "version": 1}] +
            [{"type": "node", "name": name, "nodeid": index + 1,
              "online": int(name not in offline), "local": int(index == 0),
              "ip": "node.invalid", "level": ""} for index, name in enumerate(names)])


def cluster_resources(names, offline=()):
    return [{"type": "node", "node": name, "maxcpu": 16,
             "status": "offline" if name in offline else "online"} for name in names]


def node_names(count):
    return [f"pve-{index:02d}" for index in range(1, count + 1)]


class ConsoleSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "monitor" / "console.json"
        self.state_dir = self.root / "console"
        self.resources = fixture("pvesh_cluster_resources.json")
        self.status = fixture("pvesh_cluster_status.json")
        self.rrd_text = (FIXTURES / "rrddata_hour.json").read_text(encoding="utf-8")
        self.rrd_rows = json.loads(self.rrd_text)
        console_snapshot._publisher = None
        self.addCleanup(setattr, console_snapshot, "_publisher", None)

    def publisher(self, resources=None, status=None, version=None, clock=None, **kwargs):
        return console_snapshot.Publisher(
            get_node_name=lambda: "pve-01",
            get_resources=lambda: self.resources if resources is None else resources(),
            run_pvesh=lambda: self.status if status is None else status(),
            read_language=lambda: "es",
            path=self.path,
            state_dir=self.state_dir,
            clock=(lambda: 100.0) if clock is None else clock,
            version=version,
            **kwargs,
        )

    def lease(self, now=100):
        lease = self.state_dir / "client" / "lease"
        lease.parent.mkdir(parents=True, exist_ok=True)
        lease.write_text("", encoding="utf-8")
        os.utime(lease, (now, now))
        return lease

    def document(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def run_ticks(self, publisher, clock, seconds):
        """Drive the publisher loop on a fake clock while the TUI holds its lease."""
        lease = self.lease(clock.now)
        end = clock.now + seconds
        while clock.now <= end:
            os.utime(lease, (clock.now, clock.now))
            clock.advance(publisher.tick())

    def history_cluster(self, names, history, clock, **kwargs):
        """A publisher over `names` whose get_history records (tick start, node).

        state["member_offline"] marks nodes offline in /cluster/status and
        state["resource_offline"] in /cluster/resources.
        """
        state = {"names": names, "member_offline": set(), "resource_offline": set()}
        calls = []
        publisher = None

        def get_history(node):
            calls.append((publisher.last_publish, node))
            return history(node)

        publisher = self.publisher(
            resources=lambda: cluster_resources(state["names"], state["resource_offline"]),
            status=lambda: cluster_status(state["names"], state["member_offline"]),
            clock=clock, get_history=get_history, **kwargs)
        return publisher, calls, state

    def rrd(self, node=None):
        return {"source": "rrddata", "rows": self.rrd_rows}

    # Contract of PR1: resources, cluster status, lease and atomic writes.

    def test_normalizes_complete_resources_and_missing_fields(self):
        result = console_snapshot.normalize_resources(self.resources)
        self.assertEqual(set(result), {"nodes", "guests", "storages", "truncated"})
        self.assertEqual(result["nodes"][0]["name"], "pve-01")
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
        large = [{"type": "node", "node": "pve-01", "status": "online"}] + [
            {"type": "qemu", "vmid": i, "name": "g" * 1000, "cpu": i / 2500, "maxcpu": 2}
            for i in range(2500)]
        publisher = self.publisher(resources=lambda: large, get_history=self.rrd)
        self.lease()
        publisher.publish_once(100.0)
        data = self.document()
        self.assertLessEqual(self.path.stat().st_size, 1024 * 1024)
        self.assertTrue(data["resources"]["truncated"])
        self.assertEqual(data["resources"]["guests"][0]["vmid"], 2499)
        self.assertEqual(data["history"]["status"], "ok")

    def test_initial_snapshot_and_idempotent_ensure(self):
        with mock.patch.object(console_snapshot.threading, "Thread") as thread:
            first = console_snapshot.ensure_publisher(
                lambda: "pve-01", lambda: self.resources, lambda: self.status,
                lambda: "es", path=self.path, state_dir=self.state_dir,
                clock=lambda: 100.0, version="9.9.9", get_history=self.rrd,
            )
            second = console_snapshot.ensure_publisher(
                lambda: "other", lambda: [], lambda: [], lambda: "en",
                path=self.path, state_dir=self.state_dir,
            )
        self.assertIs(first, second)
        self.assertEqual(thread.call_count, 1)
        data = self.document()
        self.assertEqual((data["cluster"]["status"], data["resources"]["status"],
                          data["history"]["status"]), ("starting",) * 3)
        self.assertEqual(data["history"]["nodes"], {})
        self.assertEqual(data["node"]["name"], "pve-01")
        self.assertEqual(data["generator"]["version"], "9.9.9")
        self.assertEqual(data["publish_interval_s"], 10)

    def test_unwritable_snapshot_path_does_not_break_ensure_publisher(self):
        blocked = self.root / "blocked"
        blocked.write_text("", encoding="utf-8")
        with mock.patch.object(console_snapshot.threading, "Thread") as thread:
            publisher = console_snapshot.ensure_publisher(
                lambda: "pve-01", lambda: self.resources, lambda: self.status,
                lambda: "es", path=blocked / "console.json", state_dir=self.state_dir,
                clock=lambda: 100.0,
            )
        self.assertIsInstance(publisher, console_snapshot.Publisher)
        self.assertEqual(thread.call_count, 1)
        thread.return_value.start.assert_called_once_with()

    def test_generator_version_comes_from_caller(self):
        self.lease()
        self.publisher(version="9.9.9").publish_once(100.0)
        data = self.document()
        self.assertEqual(data["generator"]["version"], "9.9.9")
        self.publisher().publish_once(100.0)
        data = self.document()
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
        self.lease(now=109)
        self.assertFalse(publisher.publish_once(109.0))
        self.assertTrue(publisher.publish_once(110.0))
        self.assertEqual(calls, {"resources": 2, "cluster": 1})
        self.lease(now=120)
        self.assertTrue(publisher.publish_once(120.0))
        self.assertEqual(calls, {"resources": 3, "cluster": 1})
        self.lease(now=130)
        self.assertTrue(publisher.publish_once(130.0))
        self.assertEqual(calls, {"resources": 4, "cluster": 2})
        self.assertFalse(publisher.publish_once(145.0))
        self.assertEqual(calls, {"resources": 4, "cluster": 2})

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
        for now in (100, 110, 120, 130):
            self.lease(now=now)
            publisher.publish_once(float(now))
            if now == 100:
                fail = True
            elif now == 110:
                data = self.document()
                self.assertEqual(data["resources"]["status"], "stale")
                self.assertEqual(data["resources"]["observed_at"], 100.0)
                self.assertEqual(len(data["resources"]["error"]), 200)
        data = self.document()
        self.assertEqual(data["resources"]["status"], "error")
        self.assertEqual(len(data["resources"]["guests"]), 2)

    def test_unavailable_before_first_success(self):
        def fail():
            raise RuntimeError("offline")
        publisher = self.publisher(fail, fail)
        self.lease()
        publisher.publish_once(100.0)
        data = self.document()
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
        read = console_snapshot.load_snapshot(self.path, 100)
        self.assertEqual((read.resources["status"], read.history["status"]),
                         ("unavailable", "unavailable"))
        publisher = self.publisher()
        self.lease()
        publisher.publish_once(100.0)
        self.assertEqual(console_snapshot.load_snapshot(self.path, 99).age_s, 0)

    def test_reader_sanitizes_names_tags_and_negative_metrics(self):
        publisher = self.publisher()
        self.lease()
        publisher.publish_once(100.0)
        data = self.document()
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
        data = self.document()
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
            lambda: "pve-01", lambda: self.resources, lambda: self.status,
            lambda: "en", path=self.path, state_dir=self.state_dir,
            get_pve_version=version,
        )
        self.assertEqual(publisher._node(100)["pve_version"], "pve-manager/9.0.3")
        self.assertEqual(publisher._node(399)["pve_version"], "pve-manager/9.0.3")
        self.assertEqual(len(calls), 1)
        publisher._node(400)
        self.assertEqual(len(calls), 2)

    # Revision 4: cadence measured from the start of each tick.

    def test_tick_idles_on_lstat_and_measures_the_interval_from_the_start(self):
        clock = FakeClock(1000.0)
        calls = []
        def resources():
            calls.append(clock.now)
            clock.advance(0.8)
            return self.resources
        publisher = self.publisher(resources, clock=clock)
        self.assertEqual(publisher.tick(), 2.0)
        self.assertEqual(calls, [])
        self.lease(now=clock.now)
        self.assertAlmostEqual(publisher.tick(), 9.2)
        self.assertEqual(calls, [1000.0])
        self.assertEqual(self.document()["publish_interval_s"], 10)
        clock.now = 900.0
        self.lease(now=clock.now)
        publisher.tick()
        self.assertEqual(calls[-1], 900.0, "a clock stepped back is due, not 100 s away")

    def test_publish_interval_is_configurable_and_must_be_positive(self):
        clock = FakeClock(1000.0)
        publisher = self.publisher(clock=clock, publish_interval_s=5)
        self.lease(now=clock.now)
        self.assertEqual(publisher.tick(), 5)
        self.assertEqual(self.document()["publish_interval_s"], 5)
        with self.assertRaises(ValueError):
            self.publisher(publish_interval_s=0)

    def test_document_age_stays_within_one_interval_with_a_slow_pvesh(self):
        """A 0.8 s pvesh on every call keeps the age under 10 s for the 1537d8f2 TUI."""
        clock = FakeClock(1000.0)
        names = node_names(3)
        def slow(value):
            def call(*_args):
                clock.advance(0.8)
                return value()
            return call
        publisher = console_snapshot.Publisher(
            lambda: "pve-01", slow(lambda: cluster_resources(names)),
            slow(lambda: cluster_status(names)), lambda: "en",
            path=self.path, state_dir=self.state_dir, clock=clock,
            get_history=slow(self.rrd))
        stamps, starts = [], []
        write = console_snapshot.write_snapshot
        def record(data, path):
            stamps.append(data["observed_at"])
            if not starts or starts[-1] != publisher.last_publish:
                starts.append(publisher.last_publish)
            write(data, path)
        with mock.patch.object(console_snapshot, "write_snapshot", side_effect=record):
            self.run_ticks(publisher, clock, 300)
        gaps = [later - earlier for earlier, later in zip(stamps, stamps[1:])]
        self.assertLessEqual(max(gaps), 10.0)
        self.assertTrue(all(abs(later - earlier - 10.0) < 1e-6
                            for earlier, later in zip(starts, starts[1:])))
        self.assertEqual(len(starts), 31)
        legacy = legacy_reader().load_snapshot(self.path, stamps[-1] + 10.0)
        self.assertIsNone(legacy.reason)
        self.assertLessEqual(legacy.age_s, 10)

    # Revision 4: history section from the node RRDs.

    def test_pvesh_history_command_timeout_and_node_name(self):
        run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=self.rrd_text))
        result = console_snapshot.pvesh_history("pve-02", run=run)
        run.assert_called_once_with(
            ["pvesh", "get", "/nodes/pve-02/rrddata", "--timeframe", "hour",
             "--cf", "AVERAGE", "--output-format", "json"],
            capture_output=True, text=True, timeout=3.0)
        self.assertEqual((result["source"], len(result["rows"])), ("rrddata", 60))
        run.return_value = SimpleNamespace(returncode=255, stdout="")
        with self.assertRaises(OSError):
            console_snapshot.pvesh_history("pve-02", run=run)
        run.side_effect = subprocess.TimeoutExpired("pvesh", 3.0)
        with self.assertRaises(subprocess.TimeoutExpired):
            console_snapshot.pvesh_history("pve-02", run=run)
        run.reset_mock()
        for name in ("../cluster", "pve 02", "", "-pve", "a" * 64, None):
            with self.assertRaises(ValueError):
                console_snapshot.pvesh_history(name, run=run)
        run.assert_not_called()

    def test_recorded_rrddata_drops_the_minute_in_progress(self):
        newest = self.rrd_rows[-1]
        in_progress = (',\n{"cpu":-nan,"loadavg":-nan,"maxcpu":16,"memtotal":-nan,'
                       '"memused":-nan,"time":%d}\n]\n' % (RRD_END + 60))
        variants = {
            "-nan": self.rrd_text.rstrip().rstrip("]") + in_progress,
            "empty": json.dumps(self.rrd_rows + [{"time": RRD_END + 60}]),
            "complete": self.rrd_text,
        }
        for label, text in variants.items():
            with self.subTest(label):
                run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=text))
                entry = console_snapshot.normalize_history(
                    console_snapshot.pvesh_history("pve-01", run=run))
                self.assertEqual(entry["t_end"], RRD_END)
                self.assertEqual((entry["maxcpu"], entry["memtotal"]), (16, newest["memtotal"]))
                for key in ("cpu", "mem", "load1"):
                    self.assertEqual(len(entry[key]), 60)
                    self.assertNotIn(None, entry[key])
                self.assertEqual(entry["cpu"][-1], round(newest["cpu"], 4))
                self.assertEqual(entry["mem"][-1],
                                 round(newest["memused"] / newest["memtotal"], 4))
                self.assertEqual(entry["load1"][-1], round(newest["loadavg"], 2))
                self.assertEqual(entry["cpu"][0], round(self.rrd_rows[0]["cpu"], 4))

    def test_history_maps_nan_negative_and_missing_values_to_null(self):
        rows = [{"time": RRD_END - 60 * index, "cpu": 0.5, "memused": 2, "memtotal": 8,
                 "loadavg": 1.0, "maxcpu": 4} for index in range(60)]
        rows[0].update(cpu=1.7, memused=9)                     # t_end: capped at 1
        rows[1].update(cpu=-0.1, loadavg=float("nan"), memused=-1)
        rows[2].update(cpu="-nan", memtotal=0)
        rows[3].update(cpu=True, loadavg=float("inf"))
        del rows[4]                                            # a minute the RRD lacks
        entry = console_snapshot.normalize_history({"rows": rows})
        self.assertEqual((entry["cpu"][-1], entry["mem"][-1]), (1.0, 1.0))
        self.assertEqual((entry["cpu"][-2], entry["mem"][-2], entry["load1"][-2]),
                         (None, None, None))
        self.assertEqual((entry["cpu"][-3], entry["mem"][-3], entry["load1"][-3]),
                         (None, None, 1.0))
        self.assertEqual((entry["cpu"][-4], entry["mem"][-4], entry["load1"][-4]),
                         (None, 0.25, None))
        self.assertEqual((entry["cpu"][-5], entry["mem"][-5], entry["load1"][-5]),
                         (None, None, None))
        self.assertEqual((entry["cpu"][0], entry["mem"][0], entry["maxcpu"]), (0.5, 0.25, 4))

    def test_history_clips_to_points_and_aligns_by_t_end(self):
        rows = [{"time": RRD_END - 60 * index + 7, "cpu": index / 100}
                for index in range(70)]
        entry = console_snapshot.normalize_history({"rows": list(reversed(rows))})
        self.assertEqual(entry["t_end"], RRD_END)
        self.assertEqual(entry["cpu"], [index / 100 for index in range(59, -1, -1)])
        short = console_snapshot.normalize_history({"rows": self.rrd_rows[1:]})
        self.assertEqual(short["t_end"], RRD_END)
        self.assertIsNone(short["cpu"][0])
        self.assertEqual(short["cpu"][1], round(self.rrd_rows[1]["cpu"], 4))
        for result in (None, {"rows": "x"}, {"rows": [{"time": RRD_END}]},
                       {"rows": [{"cpu": 0.5}, "row"]}):
            with self.assertRaises(ValueError):
                console_snapshot.normalize_history(result)

    def test_publishes_history_section_from_recorded_rrddata(self):
        clock = FakeClock(1000.0)
        names = node_names(3)
        publisher, calls, _state = self.history_cluster(names, self.rrd, clock)
        self.run_ticks(publisher, clock, 20)
        data = self.document()
        history = data["history"]
        self.assertEqual({key: history[key] for key in
                          ("status", "source", "step_s", "points", "error")},
                         {"status": "ok", "source": "rrddata", "step_s": 60,
                          "points": 60, "error": None})
        self.assertEqual(list(history["nodes"]), names)
        self.assertEqual(history["observed_at"], 1020.0)
        node = history["nodes"]["pve-02"]
        self.assertEqual((node["status"], node["observed_at"], node["t_end"]),
                         ("ok", 1010.0, RRD_END))
        self.assertEqual(set(node), {"status", "observed_at", "t_end", "maxcpu",
                                     "memtotal", "cpu", "mem", "load1"})
        self.assertLess(len(json.dumps(node, separators=(",", ":"))), 2000)
        read = console_snapshot.load_snapshot(self.path, clock.now)
        self.assertEqual(read.history["nodes"]["pve-03"]["cpu"], node["cpu"])
        self.assertEqual(read.history["status"], "ok")

    def test_round_robin_batch_refreshes_every_node_within_sixty_seconds(self):
        for count, batch in ((1, 1), (3, 1), (6, 1), (8, 2), (12, 2), (13, 3)):
            with self.subTest(nodes=count):
                clock = FakeClock(1000.0)
                names = node_names(count)
                publisher, calls, _state = self.history_cluster(names, self.rrd, clock)
                self.run_ticks(publisher, clock, 170)
                per_tick = {}
                for start, _node in calls:
                    per_tick[start] = per_tick.get(start, 0) + 1
                self.assertEqual(max(per_tick.values()), batch)
                for name in names:
                    attempts = [start for start, node in calls if node == name]
                    self.assertLess(attempts[0], 1060.0)
                    self.assertEqual({later - earlier for earlier, later
                                      in zip(attempts, attempts[1:])}, {60.0})
                if count == 3:
                    self.assertEqual([per_tick.get(1000.0 + 10 * tick, 0)
                                      for tick in range(12)],
                                     [1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0])
                if count == 8:
                    self.assertEqual([per_tick.get(1000.0 + 10 * tick, 0)
                                      for tick in range(7)], [2, 2, 2, 2, 0, 0, 2])

    def test_offline_nodes_get_no_pvesh_and_keep_stale_history(self):
        clock = FakeClock(1000.0)
        names = node_names(5)
        publisher, calls, state = self.history_cluster(names, self.rrd, clock)
        state["resource_offline"].add("pve-04")     # quorum member, PVE says offline
        state["member_offline"].add("pve-05")       # PVE says online, member offline
        self.run_ticks(publisher, clock, 20)
        self.assertEqual([node for _start, node in calls], ["pve-01", "pve-02", "pve-03"])
        state["resource_offline"].add("pve-02")
        state["member_offline"].add("pve-02")
        self.run_ticks(publisher, clock, 110)
        called = [node for _start, node in calls]
        self.assertEqual(called.count("pve-02"), 1)
        self.assertEqual((called.count("pve-01"), called.count("pve-03")), (3, 3))
        self.assertNotIn("pve-04", called)
        self.assertNotIn("pve-05", called)
        history = self.document()["history"]
        self.assertEqual({name: entry["status"] for name, entry in history["nodes"].items()},
                         {"pve-01": "ok", "pve-02": "stale", "pve-03": "ok"})
        self.assertEqual(history["nodes"]["pve-02"]["t_end"], RRD_END)
        self.assertEqual(history["status"], "ok")
        state["resource_offline"].discard("pve-02")
        state["member_offline"].discard("pve-02")
        self.run_ticks(publisher, clock, 0)
        self.assertEqual(calls[-1], (1150.0, "pve-02"), "back online: next tick, not 60 s")
        self.assertEqual(self.document()["history"]["nodes"]["pve-02"]["status"], "ok")

    def test_history_left_over_from_an_idle_period_is_stale_until_refreshed(self):
        clock = FakeClock(1000.0)
        publisher, calls, _state = self.history_cluster(node_names(3), self.rrd, clock)
        self.run_ticks(publisher, clock, 20)
        clock.advance(3600)                                   # no console for an hour
        self.run_ticks(publisher, clock, 0)
        self.assertEqual(calls[-1], (4630.0, "pve-01"))
        history = self.document()["history"]
        self.assertEqual({name: entry["status"] for name, entry in history["nodes"].items()},
                         {"pve-01": "ok", "pve-02": "stale", "pve-03": "stale"})
        self.assertEqual(history["status"], "ok")

    def test_history_timeout_fails_only_that_node(self):
        clock = FakeClock(1000.0)
        names = node_names(3)
        timeouts = {"pve-02"}
        def history(node):
            if node in timeouts:
                raise subprocess.TimeoutExpired(["pvesh"], console_snapshot.HISTORY_TIMEOUT_S)
            return self.rrd()
        publisher, calls, _state = self.history_cluster(names, history, clock)
        self.run_ticks(publisher, clock, 10)
        data = self.document()
        self.assertEqual((data["resources"]["status"], data["cluster"]["status"],
                          data["history"]["status"]), ("ok", "ok", "ok"))
        self.assertTrue(data["history"]["error"].startswith("pve-02: "))
        self.run_ticks(publisher, clock, 0)
        data = self.document()
        self.assertEqual(list(data["history"]["nodes"]), ["pve-01", "pve-03"])
        self.assertIsNone(data["history"]["error"])
        timeouts.clear()
        self.run_ticks(publisher, clock, 60)
        self.assertEqual(self.document()["history"]["nodes"]["pve-02"]["status"], "ok")
        timeouts.add("pve-02")
        self.run_ticks(publisher, clock, 60)
        data = self.document()
        self.assertEqual(data["history"]["nodes"]["pve-02"]["status"], "stale")
        self.assertEqual(data["history"]["status"], "ok")

    def test_history_status_follows_the_source_semantics(self):
        clock = FakeClock(1000.0)
        names = node_names(3)
        def fail(_node):
            raise OSError("pvesh exited with 255")
        publisher, _calls, state = self.history_cluster(names, fail, clock)
        publisher.write_initial()
        self.assertEqual(self.document()["history"]["status"], "starting")
        self.run_ticks(publisher, clock, 0)
        self.assertEqual(self.document()["history"]["status"], "unavailable")
        self.run_ticks(publisher, clock, 20)
        history = self.document()["history"]
        self.assertEqual((history["status"], history["nodes"]),  ("error", {}))
        self.assertEqual(history["error"], "pve-03: pvesh exited with 255")

        clock = FakeClock(1000.0)
        publisher, _calls, state = self.history_cluster(["pve-01"], self.rrd, clock)
        self.run_ticks(publisher, clock, 0)
        self.assertEqual(self.document()["history"]["status"], "ok")
        state["resource_offline"].add("pve-01")
        self.run_ticks(publisher, clock, 40)
        history = self.document()["history"]
        self.assertEqual((history["status"], history["nodes"]["pve-01"]["status"]),
                         ("stale", "stale"))

    def test_history_follows_member_order_capped_at_64_nodes(self):
        clock = FakeClock(1000.0)
        names = node_names(70) + ["../evil"]
        publisher, calls, state = self.history_cluster(list(reversed(names)), self.rrd, clock)
        self.run_ticks(publisher, clock, 50)
        nodes = self.document()["history"]["nodes"]
        self.assertEqual(list(nodes), list(reversed(names))[1:65])
        self.assertEqual(len({node for _start, node in calls}), 64)
        state["names"] = state["names"][:3]
        self.run_ticks(publisher, clock, 30)
        self.assertEqual(len(self.document()["history"]["nodes"]), 2)

    def test_publisher_without_get_history_has_no_history_section(self):
        self.lease()
        self.publisher().publish_once(100.0)
        self.assertNotIn("history", self.document())

    # Readers: the one deployed with 1537d8f2 and the revision 4 one.

    def test_legacy_reader_accepts_the_revision_4_document(self):
        clock = FakeClock(1000.0)
        publisher, _calls, _state = self.history_cluster(node_names(3), self.rrd, clock)
        self.run_ticks(publisher, clock, 20)
        legacy = legacy_reader().load_snapshot(self.path, clock.now)
        current = console_snapshot.load_snapshot(self.path, clock.now)
        self.assertIsNone(legacy.reason)
        self.assertNotIn("history", legacy.data)
        for section in ("node", "cluster", "resources"):
            self.assertEqual(legacy.data[section], current.data[section])
        self.assertEqual(legacy.resources["status"], "ok")
        self.assertEqual(current.history["status"], "ok")

    def test_reader_defaults_without_history_or_interval(self):
        self.lease()
        self.publisher().publish_once(100.0)
        data = self.document()
        del data["publish_interval_s"]
        self.path.write_text(json.dumps(data), encoding="utf-8")
        read = console_snapshot.load_snapshot(self.path, 101)
        self.assertIsNone(read.reason)
        self.assertEqual(read.publish_interval_s, 10)
        self.assertEqual((read.history["status"], read.history["nodes"]),
                         ("unavailable", {}))
        unavailable = console_snapshot.Snapshot.unavailable("missing")
        self.assertEqual((unavailable.publish_interval_s, unavailable.history["status"]),
                         (10, "unavailable"))
        for interval in (0, -5, "10", True, 1e9):
            data["publish_interval_s"] = interval
            self.path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(console_snapshot.load_snapshot(self.path, 101).publish_interval_s, 10)

    def test_reader_isolates_an_invalid_history_section(self):
        clock = FakeClock(1000.0)
        publisher, _calls, _state = self.history_cluster(node_names(3), self.rrd, clock)
        self.run_ticks(publisher, clock, 20)
        data = self.document()
        good = data["history"]
        broken = [None, [], "ok", {**good, "status": ["ok"]}, {**good, "points": 0},
                  {**good, "points": 60.0}, {**good, "step_s": True},
                  {**good, "nodes": []}, {**good, "status": "fine"}]
        for history in broken:
            with self.subTest(history=str(history)[:40]):
                data["history"] = history
                self.path.write_text(json.dumps(data), encoding="utf-8")
                read = console_snapshot.load_snapshot(self.path, clock.now)
                self.assertIsNone(read.reason)
                self.assertEqual(read.resources["status"], "ok")
                self.assertEqual((read.history["status"], read.history["nodes"]),
                                 ("unavailable", {}))

    def test_reader_normalizes_history_entries(self):
        clock = FakeClock(1000.0)
        publisher, _calls, _state = self.history_cluster(node_names(3), self.rrd, clock)
        self.run_ticks(publisher, clock, 20)
        data = self.document()
        nodes = data["history"]["nodes"]
        nodes["pve-01"]["cpu"] = [0.5] * 70
        nodes["pve-01"]["mem"] = [0.2, -1, 1.5, "x", None]
        nodes["pve-01"]["load1"] = "garbage"
        nodes["pve-02"]["t_end"] = None
        nodes["pve-03"]["status"] = ["ok"]
        nodes["\x1b[31mpve-04"] = {**nodes["pve-01"], "status": "stale"}
        for index in range(80):
            nodes[f"extra-{index:02d}"] = dict(nodes["pve-01"])
        self.path.write_text(json.dumps(data), encoding="utf-8")
        history = console_snapshot.load_snapshot(self.path, clock.now).history
        self.assertEqual(len(history["nodes"]), 62)
        self.assertNotIn("pve-02", history["nodes"])
        self.assertNotIn("pve-03", history["nodes"])
        self.assertEqual(history["nodes"]["pve-04"]["status"], "stale")
        node = history["nodes"]["pve-01"]
        self.assertEqual(node["cpu"], [0.5] * 60)
        self.assertEqual(node["mem"], [None] * 55 + [0.2, None, 1.0, None, None])
        self.assertEqual(node["load1"], [None] * 60)

    def test_monitor_hook_wires_pvesh_history_with_the_default_interval(self):
        tree = ast.parse(SERVER_SOURCE.read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "ensure_publisher"]
        self.assertEqual(len(calls), 1)
        keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in calls[0].keywords}
        self.assertEqual(keywords["get_history"], "console_snapshot.pvesh_history")
        self.assertNotIn("publish_interval_s", keywords)


# Verbatim reader of AppImage/scripts/console_snapshot.py at 1537d8f2 (the TUI
# deployed before revision 4), kept to prove the new document stays readable.
LEGACY_READER_1537D8F2 = r'''
import json
import math
from pathlib import Path
import re
import time

DEFAULT_PATH = Path("/run/proxmenux-monitor/console.json")
DEFAULT_STATE_DIR = Path("/run/proxmenux-console")
_STATUS = {"starting", "ok", "stale", "unavailable", "error"}
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|.)")

def _empty_cluster():
    return {"status": "starting", "observed_at": None, "is_cluster": None,
            "name": None, "quorate": None, "nodes_total": None,
            "nodes_online": None, "config_version": None, "members": [], "error": None}


def _empty_resources():
    return {"status": "starting", "observed_at": None, "truncated": False,
            "nodes": [], "guests": [], "storages": [], "error": None}

def _text(value, limit):
    if not isinstance(value, str):
        return None
    value = _ANSI.sub("", value)
    return "".join(char for char in value
                   if ord(char) >= 32 and not 127 <= ord(char) <= 159)[:limit]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _boolean(value):
    return value if isinstance(value, bool) else None


def _clean_row(row, fields):
    if not isinstance(row, dict):
        return None
    result = {}
    for name, kind in fields.items():
        value = row.get(name)
        if kind == "name":
            result[name] = _text(value, 64)
        elif kind == "text":
            result[name] = _text(value, 200)
        elif kind == "number":
            result[name] = _number(value)
        elif kind == "bool":
            result[name] = _boolean(value)
    return result


_NODE_FIELDS = {"name": "name", "pve_version": "text", "error": "text"}
_MEMBER_FIELDS = {"name": "name", "nodeid": "number", "online": "bool",
                  "local": "bool", "ip": "text", "level": "text"}
_RESOURCE_NODE_FIELDS = {"name": "name", "status": "text", "cpu": "number",
                         "maxcpu": "number", "mem": "number", "maxmem": "number",
                         "disk": "number", "maxdisk": "number", "uptime": "number",
                         "level": "text", "cgroup_mode": "number"}
_GUEST_FIELDS = {"vmid": "number", "type": "text", "name": "name",
                 "node": "name", "status": "text", "cpu": "number",
                 "maxcpu": "number", "mem": "number", "maxmem": "number",
                 "disk": "number", "maxdisk": "number", "uptime": "number",
                 "netin": "number", "netout": "number", "diskread": "number",
                 "diskwrite": "number", "hastate": "text", "template": "bool",
                 "lock": "text"}
_STORAGE_FIELDS = {"id": "text", "storage": "name", "node": "name",
                   "plugintype": "text", "shared": "bool", "status": "text",
                   "disk": "number", "maxdisk": "number"}


class Snapshot:
    """Validated data with attribute access for top-level sections."""

    def __init__(self, data, age_s, reason=None):
        self.data = data
        self.age_s = age_s
        self.reason = reason

    def __getitem__(self, key):
        return self.data[key]

    def __getattr__(self, key):
        try:
            return self.data[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    @classmethod
    def unavailable(cls, reason):
        return cls({"schema": 1, "generator": {"name": None, "version": None,
                                               "pid": None},
                    "observed_at": None, "publish_interval_s": 5,
                    "language": "en",
                    "node": {"status": "error", "observed_at": None,
                             "name": None, "pve_version": None, "error": reason},
                    "cluster": {**_empty_cluster(), "status": "unavailable"},
                    "resources": {**_empty_resources(), "status": "unavailable"}},
                   None, reason)


def load_snapshot(path=DEFAULT_PATH, now=None):
    """Read untrusted snapshot data without leaking errors to curses."""
    now = time.time() if now is None else now
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
            raise ValueError("unsupported schema")
        if not all(isinstance(data.get(key), dict) for key in
                   ("generator", "node", "cluster", "resources")):
            raise ValueError("invalid sections")
        if not all(isinstance(data["resources"].get(key), list) for key in
                   ("nodes", "guests", "storages")):
            raise ValueError("invalid resource lists")
        if not isinstance(data["cluster"].get("members"), list):
            raise ValueError("invalid members")
        for source in ("cluster", "resources"):
            if data[source].get("status") not in _STATUS:
                raise ValueError("invalid source status")
        if data["node"].get("status") not in ("ok", "error"):
            raise ValueError("invalid node status")
        cleaned = {"schema": 1,
                   "generator": _clean_row(data["generator"],
                                           {"name": "text", "version": "text", "pid": "number"}),
                   "observed_at": _number(data.get("observed_at")),
                   "publish_interval_s": _number(data.get("publish_interval_s")),
                   "language": _text(data.get("language"), 16) or "en"}
        cleaned["node"] = _clean_row(data["node"], _NODE_FIELDS)
        cleaned["node"].update(status=data["node"]["status"],
                               observed_at=_number(data["node"].get("observed_at")))
        cluster = data["cluster"]
        cleaned["cluster"] = _clean_row(cluster,
            {"is_cluster": "bool", "name": "name", "quorate": "bool",
             "nodes_total": "number", "nodes_online": "number",
             "config_version": "number", "error": "text"})
        cleaned["cluster"].update(status=cluster["status"],
            observed_at=_number(cluster.get("observed_at")),
            members=[row for item in cluster["members"][:2000]
                     if (row := _clean_row(item, _MEMBER_FIELDS)) is not None])
        resources = data["resources"]
        cleaned["resources"] = {"status": resources["status"],
                                "observed_at": _number(resources.get("observed_at")),
                                "truncated": _boolean(resources.get("truncated")) or False,
                                "error": _text(resources.get("error"), 200)}
        for key, fields in (("nodes", _RESOURCE_NODE_FIELDS),
                            ("guests", _GUEST_FIELDS), ("storages", _STORAGE_FIELDS)):
            limit = 2000 if key == "guests" else 10000
            cleaned_rows = []
            for item in resources[key][:limit]:
                row = _clean_row(item, fields)
                if row is None:
                    continue
                if key == "guests":
                    tags = item.get("tags")
                    row["tags"] = ([_text(tag, 32) for tag in tags[:16]
                                    if isinstance(tag, str)] if isinstance(tags, list) else [])
                elif key == "storages":
                    content = item.get("content")
                    row["content"] = ([_text(part, 64) for part in content[:32]
                                       if isinstance(part, str)] if isinstance(content, list) else [])
                cleaned_rows.append(row)
            cleaned["resources"][key] = cleaned_rows
        observed = cleaned["observed_at"]
        return Snapshot(cleaned, max(0, now - observed) if observed is not None else None)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return Snapshot.unavailable(str(exc)[:200])
'''


if __name__ == "__main__":
    unittest.main()
