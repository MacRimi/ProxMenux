"""Focused tests for the console snapshot contract and safe TUI rendering."""

import importlib.util
import json
import curses
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import monitor_console

spec = importlib.util.spec_from_file_location("monitor_tui", SCRIPTS / "proxmenux_monitor_tui.py")
tui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tui)


class SnapshotTests(unittest.TestCase):
    def test_cpu_busy_excludes_guest_columns_already_in_user_time(self):
        self.assertEqual(tui.cpu_busy_percent(
            [110, 0, 0, 110, 0, 0, 0, 0, 60, 0],
            [100, 0, 0, 100, 0, 0, 0, 0, 50, 0]), 50.0)

    def test_network_filter_excludes_vlan_children_and_non_host_links(self):
        self.assertTrue(tui.is_host_network_interface("bond0", False, False))
        self.assertTrue(tui.is_host_network_interface("enp2s0", True, False))
        self.assertFalse(tui.is_host_network_interface("bond0.10", False, False))
        self.assertFalse(tui.is_host_network_interface("enp2s0.100", True, True))
        self.assertFalse(tui.is_host_network_interface("vmbr0", False, False))

    def test_storage_lists_physical_sata_nvme_virtio_and_root_devices(self):
        names = ["nvme0n1", "nvme0n1p1", "sda", "sda1", "vda", "loop0", "zram0", "dm-0"]
        sizes = {
            "/sys/block/nvme0n1/size": "2048",
            "/sys/block/sda/size": "4096",
            "/sys/block/vda/size": "8192",
        }
        stat = type("Stat", (), {"f_blocks": 100, "f_frsize": 4096, "f_bavail": 50})()
        def read_size(path, encoding=None):
            return sizes[str(path)]
        def exists(path):
            return str(path) in ("/sys/block/nvme0n1p1/partition", "/sys/block/sda1/partition")
        with patch.object(tui.os, "listdir", return_value=names), \
             patch.object(tui.os.path, "exists", side_effect=exists), \
             patch.object(tui.Path, "read_text", read_size), \
             patch.object(tui.os, "statvfs", return_value=stat):
            result = tui.LocalSampler.storage()
        self.assertEqual([item["name"] for item in result], ["nvme0n1", "sda", "vda", "/"])

    def test_guest_lists_sort_unknown_values_after_reported_values(self):
        guests = [{"vmid":"1", "cpu":None, "mem":10},
                  {"vmid":"2", "cpu":0.1, "mem":None},
                  {"vmid":"3", "cpu":0.8, "mem":40}]
        self.assertEqual([g["vmid"] for g in tui.sorted_guests(guests, "cpu")], ["3", "2", "1"])
        self.assertEqual([g["vmid"] for g in tui.sorted_guests(guests, "mem")], ["3", "1", "2"])

    def test_schema_keeps_unknown_fields_absent_and_separates_nodes(self):
        snapshot = monitor_console.build_snapshot(
            [
                {"type": "node", "node": "p3-01", "cpu": 0.25, "mem": 10, "maxmem": 20, "maxcpu": 8},
                {"type": "node", "node": "p3-02", "cpu": 0.5, "mem": 12, "maxmem": 20, "maxcpu": 8},
                {"type": "qemu", "vmid": 100, "name": "vm\x1b[31m", "node": "p3-01", "cpu": 0.5, "mem": 11},
            ],
            [{"type": "cluster", "quorate": True}, {"type": "node", "name": "p3-01", "online": 1},
             {"type": "node", "name": "p3-02", "online": 1}],
            "2026-10-17T12:00:00+00:00",
        )
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["publisher"], "proxmenux-monitor")
        self.assertTrue(snapshot["cluster"]["enabled"])
        self.assertEqual(snapshot["cluster"]["nodes"][0]["cpu"], 0.25)
        self.assertEqual(snapshot["cluster"]["nodes"][0]["storage"], [])
        self.assertIsNone(snapshot["guests"][0]["maxmem"])
        self.assertNotIn("network", snapshot["guests"][0])

    def test_cluster_node_summary_carries_only_reported_storage_fields(self):
        snapshot = monitor_console.build_snapshot(
            [{"type":"node","node":"n1","cpu":0.2,"mem":10,"maxmem":20,"maxcpu":4},
             {"type":"storage","node":"n1","storage":"rpool","disk":100,"maxdisk":200}],
            [{"type":"cluster","quorate":True},{"type":"node","name":"n1","online":1}],
            expected_nodes=["n1"])
        node = snapshot["cluster"]["nodes"][0]
        self.assertEqual(node["storage"], [{"name":"rpool","used":100.0,"total":200.0}])
        self.assertIsNone(node["zram_used"])
        self.assertIsNone(node["network"])

    def test_standalone_host_is_not_misidentified_as_cluster(self):
        snapshot = monitor_console.build_snapshot(
            [{"type": "qemu", "vmid": 101, "cpu": 0.1}],
            [{"type": "cluster", "quorate": True},
             {"type": "node", "name": "standalone", "online": 1}],
        )
        self.assertFalse(snapshot["cluster"]["enabled"])
        self.assertEqual(len(snapshot["guests"]), 1)

    def test_failed_sampling_preserves_last_good_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            before = {"schema_version": 1, "observed_at": "old", "guests": []}
            path.write_text(json.dumps(before), encoding="utf-8")
            def fail():
                raise OSError("no quorum")
            self.assertFalse(monitor_console.refresh_snapshot(fail, lambda: [], str(path)))
            self.assertEqual(json.loads(path.read_text()), before)

    def test_reader_exceptions_and_partial_responses_preserve_last_good_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            before = {"schema_version": 1, "observed_at": "last-good", "guests": [{"vmid": "7"}]}
            path.write_text(json.dumps(before), encoding="utf-8")
            updated = monitor_console.refresh_snapshot(
                lambda: {"error": "temporary failure"},
                lambda: [{"type": "node", "name": "n1", "online": 1}],
                str(path),
            )
            self.assertFalse(updated)
            self.assertEqual(json.loads(path.read_text()), before)
            self.assertFalse(monitor_console.refresh_snapshot(
                lambda: (_ for _ in ()).throw(OSError("no quorum")), lambda: [], str(path)))
            self.assertEqual(json.loads(path.read_text()), before)

    def test_empty_resource_response_preserves_last_good_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            before = monitor_console.build_snapshot(
                [{"type":"node", "node":"n1", "cpu":0.2, "mem":10, "maxmem":20, "maxcpu":4}],
                [{"type":"node", "name":"n1", "online":1}],
                observed_at="last-good",
            )
            path.write_text(json.dumps(before), encoding="utf-8")
            updated = monitor_console.refresh_snapshot(
                lambda: [], lambda: [{"type":"node", "name":"n1", "online":1}], str(path))
            self.assertFalse(updated)
            self.assertEqual(json.loads(path.read_text()), before)

    def test_guest_only_partial_resources_preserve_last_good_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            before = {"schema_version":1, "observed_at":"last-good", "guests":[{"vmid":"7"}]}
            path.write_text(json.dumps(before), encoding="utf-8")
            updated = monitor_console.refresh_snapshot(
                lambda: [{"type":"qemu", "vmid":7, "cpu":0.5}],
                lambda: [{"type":"node", "name":"n1", "online":1}], str(path))
            self.assertFalse(updated)
            self.assertEqual(json.loads(path.read_text()), before)

    def test_node_only_response_refreshes_valid_empty_guest_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            before = monitor_console.build_snapshot(
                [{"type":"node", "node":"n1"}, {"type":"qemu", "vmid":7, "cpu":0.3}],
                [{"type":"node", "name":"n1", "online":1}], observed_at="last-good")
            path.write_text(json.dumps(before), encoding="utf-8")
            with patch.object(monitor_console, "_snapshot_group_gid", return_value=os.getgid()), \
                 patch.object(monitor_console.os, "chown"):
                self.assertTrue(monitor_console.refresh_snapshot(
                    lambda: [{"type":"node", "node":"n1"}],
                    lambda: [{"type":"node", "name":"n1", "online":1}], str(path),
                    expected_nodes=["n1"]))
            after = json.loads(path.read_text())
            self.assertNotEqual(after["observed_at"], "last-good")
            self.assertEqual(after["guests"], [])

    def test_partial_cluster_membership_preserves_last_good_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            before = {"publisher":"proxmenux-monitor", "schema_version":1,
                      "observed_at":"last-good", "guests":[]}
            path.write_text(json.dumps(before), encoding="utf-8")
            self.assertFalse(monitor_console.refresh_snapshot(
                lambda: [{"type":"node", "node":"n1"}],
                lambda: [{"type":"cluster", "quorate":True},
                         {"type":"node", "name":"n1", "online":1}],
                str(path), expected_nodes=["n1", "n2", "n3"]))
            self.assertEqual(json.loads(path.read_text()), before)

    def test_huge_numeric_api_value_becomes_unknown(self):
        snapshot = monitor_console.build_snapshot(
            [{"type":"node", "node":"n1", "cpu":10**1000}],
            [{"type":"node", "name":"n1", "online":1}],
        )
        self.assertIsNone(snapshot["cluster"]["nodes"][0]["cpu"])

    def test_atomic_snapshot_has_no_temporary_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run" / "console.json"
            with patch.object(monitor_console, "_snapshot_group_gid", return_value=os.getgid()), \
                 patch.object(monitor_console.os, "chown"):
                monitor_console.write_snapshot({"schema_version": 1}, str(path))
            self.assertEqual(json.loads(path.read_text())["schema_version"], 1)
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["console.json"])

    def test_snapshot_ownership_failure_does_not_replace_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run" / "console.json"
            path.parent.mkdir()
            before = {"schema_version":1, "observed_at":"last-good"}
            path.write_text(json.dumps(before), encoding="utf-8")
            with patch.object(monitor_console, "_snapshot_group_gid", return_value=os.getgid()), \
                 patch.object(monitor_console.os, "chown", side_effect=PermissionError("ownership denied")):
                with self.assertRaises(PermissionError):
                    monitor_console.write_snapshot({"schema_version":1, "observed_at":"new"}, str(path))
            self.assertEqual(json.loads(path.read_text()), before)
            self.assertEqual(sorted(item.name for item in path.parent.iterdir()), ["console.json"])

    def test_stale_snapshot_is_labeled_and_escape_controls_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            stamp = datetime.now(timezone.utc) - timedelta(seconds=120)
            path.write_text(json.dumps({"schema_version": 1, "observed_at": stamp.isoformat(),
                                        "publisher": "proxmenux-monitor",
                                        "cluster": {"enabled": True, "quorum": None, "nodes": []},
                                        "guests": []}))
            data, freshness = tui.read_snapshot(str(path))
            self.assertIsNotNone(data)
            self.assertTrue(freshness.startswith("stale"))
        self.assertEqual(tui.clean_text("guest\x1b[2J\x07name"), "guest?[2J?name")

    def test_malformed_remote_schema_is_rejected_without_killing_local_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            path.write_text(json.dumps({"schema_version": 1, "publisher":"proxmenux-monitor", "observed_at": datetime.now(timezone.utc).isoformat(), "cluster": [], "guests": []}))
            self.assertEqual(tui.read_snapshot(str(path))[1], "schema")
            path.write_text(json.dumps({"schema_version": 1, "publisher":"proxmenux-monitor", "observed_at": datetime.now(timezone.utc).isoformat(), "cluster": {"enabled":True,"quorum":None,"nodes": [{}]}, "guests": []}))
            self.assertEqual(tui.read_snapshot(str(path))[1], "schema")

    def test_pve_cpu_fraction_and_guest_units_remain_numeric(self):
        result = monitor_console.build_snapshot(
            [{"type": "qemu", "vmid": 202, "cpu": "0.75", "mem": "1024"}],
            [{"type": "cluster", "quorate": False}, {"type": "node", "name": "n1", "online": 1}],
        )
        self.assertEqual(result["guests"][0]["cpu"], 0.75)
        self.assertFalse(result["cluster"]["quorum"])

    def test_boolean_metrics_are_unknown_not_numeric(self):
        result = monitor_console.build_snapshot(
            [{"type":"node", "node":"n1", "cpu":True, "mem":False, "maxmem":20, "maxcpu":8}],
            [{"type":"cluster", "quorate":True}, {"type":"node", "name":"n1", "online":True}],
        )
        self.assertIsNone(result["cluster"]["nodes"][0]["cpu"])
        self.assertIsNone(result["cluster"]["nodes"][0]["mem"])

    def test_empty_status_response_preserves_last_good_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            before = {"publisher":"proxmenux-monitor", "schema_version":1,
                      "observed_at":"last-good", "guests":[]}
            path.write_text(json.dumps(before), encoding="utf-8")
            resources = [{"type":"qemu", "vmid":1, "cpu":0.2}]
            self.assertFalse(monitor_console.refresh_snapshot(lambda: resources, lambda: [], str(path)))
            self.assertEqual(json.loads(path.read_text()), before)

    def test_far_future_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            now = datetime.now(timezone.utc)
            path.write_text(json.dumps({
                "schema_version":1, "publisher":"proxmenux-monitor",
                "observed_at":(now+timedelta(minutes=2)).isoformat(),
                "cluster":{"enabled":True,"quorum":None,"nodes":[]}, "guests":[],
            }))
            data, freshness = tui.read_snapshot(str(path), now=now)
            self.assertIsNone(data)
            self.assertEqual(freshness, "future")

    def test_huge_integer_snapshot_is_rejected_without_crashing_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            path.write_text(json.dumps({
                "schema_version":1, "publisher":"proxmenux-monitor",
                "observed_at":datetime.now(timezone.utc).isoformat(),
                "cluster":{"enabled":True,"quorum":True,"nodes":[{
                    "name":"n1","online":True,"cpu":10**1000,"maxcpu":8,"mem":1,"maxmem":2}]},
                "guests":[],
            }), encoding="utf-8")
            data, freshness = tui.read_snapshot(str(path))
            self.assertIsNone(data)
            self.assertEqual(freshness, "unavailable")

    def test_no_quorum_never_qualifies_for_cluster_aggregate(self):
        snapshot = monitor_console.build_snapshot(
            [{"type": "node", "node": "n1", "cpu": 0.5, "mem": 100, "maxmem": 200, "maxcpu": 8}],
            [{"type": "cluster", "quorate": False}, {"type": "node", "name": "n1", "online": 1}],
        )
        cluster = snapshot["cluster"]
        self.assertFalse(cluster["quorum"])
        self.assertIsNotNone(cluster["nodes"][0]["cpu"])

    def test_cluster_renderer_withholds_totals_without_quorum(self):
        class Screen:
            def __init__(self): self.rows = {}
            def getmaxyx(self): return (24, 80)
            def erase(self): self.rows = {}
            def addnstr(self, row, col, value, width, attr=0):
                old = self.rows.get(row, "")
                self.rows[row] = (old + " " * max(0, col-len(old)) + value)[:80]
            def refresh(self): pass
        class Sampler:
            def sample(self):
                snapshot = monitor_console.build_snapshot(
                    [
                        {"type":"node", "node":"n1", "cpu":0.2, "mem":100, "maxmem":200, "maxcpu":4},
                        {"type":"node", "node":"n2", "cpu":0.3, "mem":110, "maxmem":220, "maxcpu":4},
                        {"type":"node", "node":"n3", "cpu":0.4, "mem":120, "maxmem":240, "maxcpu":4},
                    ],
                    [{"type":"cluster", "quorate":False},
                     {"type":"node", "name":"n1", "online":1},
                     {"type":"node", "name":"n2", "online":1},
                     {"type":"node", "name":"n3", "online":1}],
                )
                return {"cpu":{"cpu":12.0,"cpu0":12.0}, "load":(1,1,1),
                        "memory":{"MemTotal":200,"MemAvailable":100}, "arc":{},
                        "zram":{"available":False,"devices":[]}, "storage":[], "network":{},
                        "snapshot":(snapshot,"fresh 0s")}
        screen = Screen()
        tui.render(screen, Sampler(), "CLUSTER")
        rendered = " ".join(screen.rows.values())
        self.assertIn("no quorum", rendered)
        self.assertIn("n3", rendered)
        self.assertIn("totals withheld", rendered)
        self.assertNotIn("Cluster total CPU", rendered)
        self.assertIn("Z:N/D", rendered)
        self.assertIn("S:N/D", rendered)
        self.assertIn("N:N/D", rendered)

    def test_cluster_renderer_withholds_totals_for_zero_capacity(self):
        class Screen:
            def __init__(self): self.rows = {}
            def getmaxyx(self): return (24, 80)
            def erase(self): self.rows = {}
            def addnstr(self, row, col, value, width, attr=0):
                old = self.rows.get(row, "")
                self.rows[row] = (old + " " * max(0, col-len(old)) + value)[:80]
            def refresh(self): pass
        class Sampler:
            def sample(self):
                snapshot = monitor_console.build_snapshot(
                    [{"type":"node", "node":"n1", "cpu":0.2, "mem":100, "maxmem":0, "maxcpu":0},
                     {"type":"node", "node":"n2", "cpu":0.2, "mem":50, "maxmem":100, "maxcpu":4}],
                    [{"type":"cluster", "quorate":True}, {"type":"node", "name":"n1", "online":1},
                     {"type":"node", "name":"n2", "online":1}],
                )
                return {"cpu":{"cpu":1},"load":(),"memory":{},"arc":{},"zram":{},
                        "storage":[],"network":{},"snapshot":(snapshot,"fresh 0s")}
        screen = Screen()
        tui.render(screen, Sampler(), "CLUSTER")
        self.assertIn("totals withheld", " ".join(screen.rows.values()))

    def test_cluster_node_truncation_keeps_totals_lists_and_footer_separate(self):
        class Screen:
            def __init__(self): self.rows = {}
            def getmaxyx(self): return (24, 80)
            def erase(self): self.rows = {}
            def addnstr(self, row, col, value, width, attr=0):
                old = self.rows.get(row, "")
                self.rows[row] = (old + " " * max(0, col-len(old)) + value)[:80]
            def refresh(self): pass
        class Sampler:
            def sample(self):
                nodes = [{"type":"node", "node":f"n{i}", "cpu":0.2, "mem":100,
                          "maxmem":200, "maxcpu":8} for i in range(20)]
                status = [{"type":"cluster", "quorate":True}]
                status.extend({"type":"node", "name":f"n{i}", "online":1} for i in range(20))
                snapshot = monitor_console.build_snapshot(
                    nodes, status, expected_nodes=[f"n{i}" for i in range(20)])
                return {"cpu":{"cpu":12.0,"cpu0":12.0}, "load":(1,1,1),
                        "memory":{"MemTotal":200,"MemAvailable":100}, "arc":{},
                        "zram":{"available":False,"devices":[]}, "storage":[], "network":{},
                        "snapshot":(snapshot,"fresh 0s")}
        screen = Screen()
        tui.render(screen, Sampler(), "CLUSTER")
        self.assertIn("+ 16 nodes not shown", screen.rows[14])
        self.assertIn("Cluster total CPU", screen.rows[15])
        self.assertIn("TOP CPU", screen.rows[17])
        self.assertIn("q quit", screen.rows[23])

    def test_empty_and_standalone_view_keeps_only_local_metrics(self):
        class Screen:
            def __init__(self): self.rows = {}
            def getmaxyx(self): return (24, 80)
            def erase(self): self.rows = {}
            def addnstr(self, row, col, value, width, attr=0):
                old = self.rows.get(row, "")
                self.rows[row] = (old + " " * max(0, col-len(old)) + value)[:80]
            def refresh(self): pass
        class Sampler:
            def sample(self):
                empty = monitor_console.build_snapshot(
                    [], [{"type":"node", "name":"standalone", "online":1}],
                )
                return {"cpu":{"cpu":None}, "load":(), "memory":{}, "arc":{},
                        "zram":{"available":False,"devices":[]}, "storage":[], "network":{},
                        "snapshot":(empty,"fresh 0s")}
        screen = Screen()
        with patch.object(tui, "cluster_configured", return_value=False):
            tui.render(screen, Sampler(), "NODE")
        rendered = " ".join(screen.rows.values())
        self.assertIn("STANDALONE", rendered)
        self.assertIn("N/D", rendered)
        self.assertNotIn("remote", rendered.lower())

    def test_non_dict_zram_and_full_guest_rows_do_not_crash_or_hide_capacity(self):
        class Screen:
            def __init__(self): self.rows = {}
            def getmaxyx(self): return (24, 80)
            def erase(self): self.rows = {}
            def addnstr(self, row, col, value, width, attr=0):
                old = self.rows.get(row, "")
                self.rows[row] = (old + " " * max(0, col-len(old)) + value)[:80]
            def refresh(self): pass
        class Sampler:
            def sample(self):
                guests = [{"vmid":str(i), "type":"VM", "name":f"guest{i}", "cpu":i/100, "mem":i}
                          for i in range(15)]
                return {"cpu":{"cpu":1}, "load":(), "memory":{}, "arc":{},
                        "zram":None, "storage":[], "network":{},
                        "snapshot":({"cluster":{"enabled":False}, "guests":guests}, "fresh 0s")}
        screen = Screen()
        with patch.object(tui, "cluster_configured", return_value=False):
            tui.render(screen, Sampler(), "NODE")
        self.assertIn("TOP CPU", screen.rows[11])
        self.assertIn("guest4", screen.rows[22])

    def test_cluster_switch_on_standalone_stays_a_clean_local_view(self):
        class Screen:
            def __init__(self): self.rows = {}
            def getmaxyx(self): return (24, 80)
            def erase(self): self.rows = {}
            def addnstr(self, row, col, value, width, attr=0):
                old = self.rows.get(row, "")
                self.rows[row] = (old + " " * max(0, col-len(old)) + value)[:80]
            def refresh(self): pass
        class Sampler:
            def sample(self):
                snapshot = monitor_console.build_snapshot(
                    [], [{"type":"node", "name":"standalone", "online":1}],
                )
                return {"cpu":{"cpu":None}, "load":(), "memory":{}, "arc":{},
                        "zram":{"available":False,"devices":[]}, "storage":[], "network":{},
                        "snapshot":(snapshot,"fresh 0s")}
        screen = Screen()
        with patch.object(tui, "cluster_configured", return_value=False):
            tui.render(screen, Sampler(), "CLUSTER")
        rendered = " ".join(screen.rows.values())
        self.assertIn("STANDALONE", rendered)
        self.assertNotIn("CLUSTER unavailable", rendered)
        self.assertNotIn("remote", rendered.lower())

    def test_cluster_local_view_labels_guests_from_each_node(self):
        class Screen:
            def __init__(self): self.rows = {}
            def getmaxyx(self): return (24, 80)
            def erase(self): self.rows = {}
            def addnstr(self, row, col, value, width, attr=0):
                old = self.rows.get(row, "")
                self.rows[row] = (old + " " * max(0, col-len(old)) + value)[:80]
            def refresh(self): pass
        class Sampler:
            def sample(self):
                snapshot = monitor_console.build_snapshot(
                    [{"type":"node","node":"n1","cpu":0.2,"mem":100,"maxmem":200,"maxcpu":4},
                     {"type":"qemu","node":"n1","vmid":100,"name":"guest","cpu":0.2,"mem":50}],
                    [{"type":"cluster","quorate":True},{"type":"node","name":"n1","online":1}],
                    expected_nodes=["n1"])
                return {"cpu":{"cpu":1},"load":(),"memory":{},"arc":{},
                        "zram":{"available":False,"devices":[]},"storage":[],"network":{},
                        "snapshot":(snapshot,"fresh 0s")}
        screen = Screen()
        with patch.object(tui, "cluster_configured", return_value=True):
            tui.render(screen, Sampler(), "NODE")
        self.assertIn("Local view", screen.rows[9])
        self.assertIn("n1 VM 100 guest", screen.rows[12])

    def test_local_cpu_view_labels_all_sixteen_logical_cpu_values(self):
        class Screen:
            def __init__(self): self.rows = {}
            def getmaxyx(self): return (24, 80)
            def erase(self): self.rows = {}
            def addnstr(self, row, col, value, width, attr=0): self.rows[row] = value[:width]
            def refresh(self): pass
        class Sampler:
            def sample(self):
                cpu = {"cpu":50.0}
                cpu.update({f"cpu{i}":float(i) for i in range(16)})
                return {"cpu":cpu,"load":(1,1,1),"memory":{},"arc":{},
                        "zram":{"available":False,"devices":[]},"storage":[],"network":{},
                        "snapshot":(None,"unavailable")}
        screen = Screen()
        with patch.object(tui, "cluster_configured", return_value=False):
            tui.render(screen, Sampler(), "NODE")
        self.assertIn("CPU total", screen.rows[2])
        self.assertIn("Cores CPU0-15", screen.rows[3])
        self.assertIn("15", screen.rows[3])

    def test_small_terminal_shows_size_requirement_without_overlapping_views(self):
        class Screen:
            def __init__(self): self.rows = {}
            def getmaxyx(self): return (12, 40)
            def erase(self): self.rows = {}
            def addnstr(self, row, col, value, width, attr=0): self.rows[row] = value
            def refresh(self): pass
        class Sampler:
            def sample(self): raise AssertionError("small terminal must be rejected before sampling")
        screen = Screen()
        tui.render(screen, Sampler())
        self.assertIn("needs 80x24", screen.rows[0])
        self.assertEqual(len(screen.rows), 1)

    def test_tui_has_no_privileged_proxmox_or_web_api_client(self):
        source = (SCRIPTS / "proxmenux_monitor_tui.py").read_text(encoding="utf-8")
        self.assertNotIn("pvesh", source)
        self.assertNotIn("/api/system", source)

    def test_ctrl_c_is_swallowed_after_curses_restores_terminal(self):
        with patch.object(tui.curses, "setupterm"), \
             patch.object(tui.curses, "wrapper", side_effect=KeyboardInterrupt):
            self.assertIsNone(tui.main())


if __name__ == "__main__":
    unittest.main()
