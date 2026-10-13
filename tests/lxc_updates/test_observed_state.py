"""Actual Flask routes and registry writes, with only PVE transports mocked.

Run with Flask installed. AST loading avoids starting Monitor's host workers;
route decorators remain intact, authentication is a fixture passthrough.
"""
import ast
import builtins
from concurrent.futures import ThreadPoolExecutor
import datetime
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "AppImage/scripts"))
import managed_installs as managed

SERVER = ROOT / "AppImage/scripts/flask_server.py"
FUNCTIONS = {
    "_get_lxc_ip_info_cached", "_remember_lxc_ip", "_invalidate_lxc_ip",
    "_get_lxc_primary_ip_cached", "_normalise_lxc_ips", "_lxc_runtime_details",
    "_vm_cache_get", "_vm_cache_put", "_vm_conf_signature",
    "_vm_conf_cache_get", "_vm_conf_cache_put", "_vm_cache_invalidate",
    "_read_pve_conf_fast", "_detect_vm_type_local", "_get_lxc_update_status_map",
    "get_proxmox_vms", "api_vms", "get_vm_config", "api_lxc_updates_check",
    "api_managed_installs_refresh", "api_managed_installs_get",
    "api_vms_modal_cache_all", "api_lxc_mount_points",
}
GLOBALS = {
    "_NUMERIC_CONF_KEYS", "_LXC_IP_TTL", "_LXC_IP_RETRY_TTL", "_lxc_ip_cache",
    "_lxc_ip_cache_lock", "_lxc_os_info_cache", "_LXC_OS_INFO_TTL",
    "_vm_details_cache", "_vm_modal_cache_lock", "_vm_conf_built",
    "_VM_CACHE_INDEFINITE", "_VM_DETAILS_TTL", "_lxc_update_check_lock",
    "_lxc_update_check_attempts", "_lxc_update_check_inflight",
    "_LXC_UPDATE_CHECK_INTERVAL",
    "_vm_backups_cache", "_VM_BACKUPS_TTL", "_vm_mounts_cache", "_VM_MOUNTS_TTL",
    "_vm_app_suggestions_cache", "_VM_APP_SUGGESTIONS_TTL", "_vm_schedule_cache", "_VM_SCHEDULE_TTL",
}


class ObservedStateRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.conf = Path(self.temp.name) / "100.conf"
        self.conf.write_text("onboot: 0\nnet0: name=eth0,ip=dhcp\ntags: old\n")
        self.clock = Mock(time=Mock(return_value=1000), monotonic=Mock(return_value=1000))
        real_open = builtins.open

        def mapped(path):
            if str(path) == "/etc/pve/lxc/100.conf":
                return self.conf
            if str(path).startswith("/etc/pve/"):
                return Path(self.temp.name) / "missing"
            return path

        self.app = Flask(__name__)
        self.scope = {
            "app": self.app, "jsonify": jsonify, "require_auth": lambda fn: fn,
            "time": self.clock, "threading": threading,
            "os": SimpleNamespace(stat=lambda p: os.stat(mapped(p)),
                                  path=SimpleNamespace(exists=lambda p: os.path.exists(mapped(p)))),
            "open": lambda p, *a, **kw: real_open(mapped(p), *a, **kw),
            "subprocess": subprocess,
        }
        nodes = []
        for node in ast.parse(SERVER.read_text()).body:
            if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
                nodes.append(node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id in GLOBALS for t in targets):
                    nodes.append(node)
        self.assertEqual({n.name for n in nodes if isinstance(n, ast.FunctionDef)}, FUNCTIONS)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER), "exec"), self.scope)
        self.running = True
        self.ip = "10.100.100.222"
        self.release = 'ID="debian"\nVERSION_ID="13.7"\nPRETTY_NAME="Debian GNU/Linux 13"\n'
        self.ip_probe = Mock(side_effect=lambda _id: {
            "primary_ip": self.ip, "real_ips": [self.ip],
            "all_ips": [self.ip, self.ip, "172.17.0.1"], "docker_ips": ["172.17.0.1"],
        })
        self.scope.update({
            "get_lxc_ip_from_lxc_info": self.ip_probe,
            "get_proxmox_node_name": lambda: "fixture-pve",
            "_fast_guest_status": lambda *_: "running" if self.running else "stopped",
            "_get_cached_vm_list_search_notes": lambda *_: {},
            "_get_lxc_app_watch_map": lambda: {},
            "_get_lxc_docker_inventory_map": lambda: {},
            "get_cached_vm_disk": lambda _: None,
            "_guest_lifecycle_lock": threading.RLock(),
            "_guest_modal_cache_revision": {}, "_guest_modal_cache_epoch": 1,
            "parse_lxc_hardware_config": lambda *_: {"privileged": False},
            "get_cached_pvesh_cluster_resources_vm": lambda: [
                {"type": "lxc", "node": "fixture-pve", "vmid": 100, "name": "dev-trixie",
                 "status": "running" if self.running else "stopped"},
            ],
        })
        self.commands = []

        def run(command, **_):
            self.commands.append(command)
            if command[-2:] == ["cat", "/etc/os-release"]:
                return SimpleNamespace(returncode=0, stdout=self.release, stderr="")
            if command[-1] == "apt list --upgradable 2>/dev/null":
                return SimpleNamespace(returncode=0, stdout="Listing...\n", stderr="")
            raise AssertionError(f"Unexpected guest command: {command}")

        for ctx in (
            patch.object(subprocess, "run", side_effect=run),
            patch.object(managed, "_DB_DIR", self.temp.name),
            patch.object(managed, "_REGISTRY_PATH", str(Path(self.temp.name) / "registry.json")),
            patch.object(managed, "_lxc_updates_detection_enabled", return_value=True),
            patch.object(managed, "_list_pve_lxcs", return_value=[
                {"vmid": "100", "name": "dev-trixie", "status": "running"},
            ]),
            patch.object(managed, "_get_oci_managed_vmids", return_value={}),
            patch.object(managed, "_probe_lxc_is_oci", return_value=False),
            patch.object(managed, "_identify_helper_slug", return_value=(None, None)),
        ):
            ctx.start()
            self.addCleanup(ctx.stop)
        managed._write_registry({"items": [
            {"id": "lxc:100", "type": "lxc", "_vmid": "100", "_os_family": "ubuntu",
             "update_check": {"available": True, "_count": 51, "_security_count": 24,
                              "_packages": [{"name": "old"}], "last_check": "2020-01-01T00:00:00Z"}},
            {"id": "other", "type": "unhandled", "update_check": {"_count": 7}},
        ]})
        self.client = self.app.test_client()

    def row(self):
        response = self.client.get("/api/vms")
        self.assertEqual(response.status_code, 200, response.json)
        return response.json[0]

    def test_dhcp_change_after_ttl_without_lifecycle_and_api_compatibility(self):
        first = self.row()
        self.assertEqual(first["ip"], "10.100.100.222")
        self.assertEqual(first["ips"], ["10.100.100.222", "172.17.0.1"])
        self.ip = "10.100.100.220"
        self.clock.monotonic.return_value = 1059
        self.assertEqual(self.row()["ip"], "10.100.100.222")
        self.ip_probe.assert_called_once_with(100)
        self.clock.monotonic.return_value = 1060
        current = self.row()
        self.assertEqual(current["ip"], "10.100.100.220")
        self.assertEqual(current["ips"], ["10.100.100.220", "172.17.0.1"])
        self.assertEqual(self.ip_probe.call_count, 2)
        self.assertEqual(self.commands, [])

    def test_repeated_list_get_is_read_only_and_does_not_refresh_registry(self):
        before = managed.get_registry()
        for _ in range(10):
            self.assertTrue(self.row()["update_check"]["stale"])
        self.assertEqual(managed.get_registry(), before)
        self.assertEqual(self.commands, [])
        self.ip_probe.assert_called_once()

    def test_concurrent_expired_ip_reads_share_one_probe(self):
        self.scope["_get_lxc_ip_info_cached"](100)
        self.clock.monotonic.return_value += 60
        self.ip = "10.100.100.220"
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(self.scope["_get_lxc_primary_ip_cached"], [100] * 16))
        self.assertEqual(set(values), {self.ip})
        self.assertEqual(self.ip_probe.call_count, 2)

    def test_package_listing_failure_stores_error_without_reusing_old_count(self):
        with patch.object(managed, "_run_pct_pkg_listing", return_value=(False, "", "APT metadata unreadable")):
            response = self.client.post("/api/vms/100/updates/check")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["update_check"]["error"], "APT metadata unreadable")
        self.assertNotIn("_count", managed.get_registry()["items"][0]["update_check"])

    def test_onboot_network_and_tags_external_edit_rebuilds_next_detail(self):
        first = self.client.get("/api/vms/100").json
        self.assertEqual(first["config"]["onboot"], 0)
        # Ensure distinct metadata even on coarse temporary filesystems.
        self.conf.write_text("onboot: 1\nnet0: name=eth0,ip=dhcp,bridge=vmbr1\ntags: new;test\n")
        os.utime(self.conf, ns=(2_000_000_000, 2_000_000_000))
        current = self.client.get("/api/vms/100")
        self.assertEqual(current.status_code, 200, current.json)
        self.assertEqual(current.json["config"]["onboot"], 1)
        self.assertEqual(current.json["config"]["tags"], "new;test")
        self.assertIn("vmbr1", current.json["config"]["net0"])
        self.assertEqual(current.json["vm_type"], "lxc")
        self.assertIn("digest", current.json["config"])
        self.assertEqual(current.json["lxc_ip_info"]["primary_ip"], self.ip)
        self.assertEqual(current.json["os_info"]["version_id"], "13.7")

    def test_runtime_ip_and_os_expire_even_with_unchanged_conf(self):
        self.release = 'ID=ubuntu\nVERSION_ID=24.04\n'
        self.assertEqual(self.client.get("/api/vms/100").json["os_info"]["id"], "ubuntu")
        self.release = 'ID=debian\nVERSION_ID=13.7\n'
        self.ip = "10.100.100.220"
        self.clock.time.return_value += 60
        self.clock.monotonic.return_value += 60
        current = self.client.get("/api/vms/100").json
        self.assertEqual(current["os_info"]["id"], "debian")
        self.assertEqual(current["lxc_ip_info"]["primary_ip"], self.ip)
        self.assertEqual(current["config"]["onboot"], 0)

    def test_same_size_same_mtime_onboot_edit_is_visible_through_route(self):
        self.assertEqual(self.client.get("/api/vms/100").json["config"]["onboot"], 0)
        old = self.conf.stat()
        self.conf.write_text(self.conf.read_text().replace("onboot: 0", "onboot: 1"))
        os.utime(self.conf, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.assertEqual(self.conf.stat().st_size, old.st_size)
        self.assertEqual(self.conf.stat().st_mtime_ns, old.st_mtime_ns)
        self.assertEqual(self.client.get("/api/vms/100").json["config"]["onboot"], 1)

    def test_bulk_cache_consumer_rejects_changed_config_without_live_probes(self):
        import lxc_apps
        self.client.get("/api/vms/100")
        count = len(self.commands)
        with patch.object(lxc_apps, "load_sidecar", return_value={"vmid": 100, "apps": []}):
            response = self.client.get("/api/vms/modal-cache-all")
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json["guests"][0]["details"]["config"]["onboot"], 0)
            self.conf.write_text("onboot: 1\n")
            response = self.client.get("/api/vms/modal-cache-all")
            self.assertIsNone(response.json["guests"][0]["details"])
        self.assertEqual(len(self.commands), count, "bulk cache remains a snapshot-only reader")
        self.assertEqual(self.client.get("/api/vms/100").json["config"]["onboot"], 1)

    def test_mount_cache_consumer_rebuilds_after_external_config_change(self):
        provider = Mock(return_value={"ok": True, "mount_points": [{"target": "/old"}]})
        with patch.dict(sys.modules, {"lxc_mount_points": SimpleNamespace(get_lxc_mount_points_static=provider)}):
            path = "/api/lxc/100/mount-points"
            self.assertEqual(self.client.get(path).json["mount_points"][0]["target"], "/old")
            self.client.get(path)
            provider.assert_called_once_with("100")
            self.conf.write_text("onboot: 0\nmp0: local:100/vm-100-disk-1.raw,mp=/new\n")
            provider.return_value = {"ok": True, "mount_points": [{"target": "/new"}]}
            self.assertEqual(self.client.get(path).json["mount_points"][0]["target"], "/new")
            self.assertEqual(provider.call_count, 2)

    def test_read_only_post_replaces_ubuntu_51_with_debian_zero(self):
        response = self.client.post("/api/vms/100/updates/check")
        self.assertEqual(response.status_code, 200, response.json)
        uc = response.json["update_check"]
        self.assertEqual(uc["os_family"], "debian")
        self.assertEqual((uc["count"], uc["security_count"], uc["packages"]), (0, 0, []))
        self.assertFalse(uc["available"])
        self.assertFalse(uc["stale"])
        self.assertIsNone(uc["error"])
        reg = managed.get_registry()
        self.assertEqual(reg["items"][0]["_os_family"], "debian")
        self.assertEqual(reg["items"][1]["update_check"]["_count"], 7)
        self.assertEqual(self.row()["update_check"], uc)
        self.assertEqual(len(self.commands), 2)
        self.assertIn("apt list --upgradable", self.commands[1][-1])
        self.assertFalse(any("apt-get" in str(cmd) or "upgrade" in str(cmd) and "upgradable" not in str(cmd)
                             for cmd in self.commands))

    def test_per_guest_cooldown_and_inflight(self):
        self.assertEqual(self.client.post("/api/vms/100/updates/check").status_code, 200)
        count = len(self.commands)
        denied = self.client.post("/api/vms/100/updates/check")
        self.assertEqual(denied.status_code, 429)
        self.assertGreater(int(denied.headers["Retry-After"]), 0)
        self.assertEqual(len(self.commands), count)
        self.clock.monotonic.return_value += 60
        self.scope["_lxc_update_check_inflight"].add(100)
        self.assertEqual(self.client.post("/api/vms/100/updates/check").status_code, 429)
        self.scope["_lxc_update_check_inflight"].clear()
        self.assertEqual(self.client.post("/api/vms/100/updates/check").status_code, 200)

    def test_disabled_stopped_missing_and_get_action_are_rejected(self):
        with patch.object(managed, "_lxc_updates_detection_enabled", return_value=False):
            self.assertEqual(self.client.post("/api/vms/100/updates/check").status_code, 403)
        self.running = False
        self.assertEqual(self.client.post("/api/vms/100/updates/check").status_code, 409)
        self.assertEqual(self.row()["ips"], [])
        self.assertNotIn("os_info", self.client.get("/api/vms/100").json)
        self.assertEqual(self.client.post("/api/vms/999/updates/check").status_code, 404)
        self.assertEqual(self.client.get("/api/vms/100/updates/check").status_code, 405)
        self.assertEqual(self.commands, [])

    def test_readable_unsupported_os_replaces_old_family_without_claiming_zero(self):
        self.release = "ID=unsupported\n"
        response = self.client.post("/api/vms/100/updates/check")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json["update_check"]["os_family"])
        self.assertTrue(response.json["update_check"]["error"])
        self.assertNotIn("_count", managed.get_registry()["items"][0]["update_check"])
        self.assertEqual(len(self.commands), 1)

    def test_unreadable_os_keeps_last_known_family_but_clears_old_update_count(self):
        failures = [subprocess.TimeoutExpired('pct', 5), OSError('transport failed'),
                    SimpleNamespace(returncode=1, stdout='', stderr='read failed'),
                    SimpleNamespace(returncode=0, stdout='', stderr='')]
        for failure in failures:
            with self.subTest(failure=failure):
                self.clock.monotonic.return_value += 60
                with patch.object(subprocess, 'run') as run:
                    if isinstance(failure, Exception):
                        run.side_effect = failure
                    else:
                        run.return_value = failure
                    response = self.client.post('/api/vms/100/updates/check')
                self.assertEqual(response.status_code, 200, response.json)
                self.assertEqual(response.json['update_check']['os_family'], 'ubuntu')
                self.assertTrue(response.json['update_check']['error'])
                stored = managed.get_registry()['items'][0]
                self.assertEqual(stored['_os_family'], 'ubuntu')
                self.assertNotIn('_count', stored['update_check'])
                run.assert_called_once()

    def test_daily_and_global_refresh_keep_os_hint_on_read_failure(self):
        for global_route in (False, True):
            with self.subTest(global_route=global_route), \
                    patch.object(subprocess, 'run', side_effect=OSError('unreadable')), \
                    patch.object(managed, '_DETECTORS', [managed._detect_lxc_containers]), \
                    patch.object(managed, '_refresh_lxc_pkg_cache_if_stale') as refresh:
                if global_route:
                    self.assertEqual(self.client.post('/api/managed-installs/refresh').status_code, 200)
                else:
                    managed.check_for_updates()
                stored = managed.get_registry()['items'][0]
                self.assertEqual(stored['_os_family'], 'ubuntu')
                self.assertTrue(stored['update_check']['error'])
                self.assertNotIn('_count', stored['update_check'])
                refresh.assert_not_called()

    def test_legacy_os_detection_returns_none_on_transport_failure(self):
        with patch.object(subprocess, 'run', side_effect=OSError('unreadable')):
            self.assertIsNone(managed._probe_lxc_os('100'))

    def test_new_oci_detection_and_check_never_probe_os(self):
        managed._write_registry({'items': []})
        for is_oci, membership in ((True, {}), (False, {'100': 'secure-gateway'})):
            with self.subTest(is_oci=is_oci), \
                    patch.object(managed, '_probe_lxc_is_oci', return_value=is_oci), \
                    patch.object(managed, '_get_oci_managed_vmids', return_value=membership), \
                    patch.object(managed, '_probe_lxc_os', side_effect=AssertionError('OCI OS probe forbidden')):
                entry = managed._detect_lxc_containers(only_vmid=100)[0]
                self.assertIsNone(entry['_os_family'])
                self.assertEqual(managed._check_lxc_updates(entry)['_count'], 0)

    def test_registry_write_failure_is_reported_and_releases_inflight(self):
        with patch.object(managed, "_write_registry", return_value=False):
            self.assertEqual(self.client.post("/api/vms/100/updates/check").status_code, 500)
        self.assertNotIn(100, self.scope["_lxc_update_check_inflight"])
        self.assertEqual(managed.get_registry()["items"][0]["_os_family"], "ubuntu")

    def test_daily_checker_reprobes_os_and_preserves_existing_index_refresh(self):
        with patch.object(managed, "_refresh_lxc_pkg_cache_if_stale", return_value={}) as refresh:
            managed.check_for_updates()
        refresh.assert_called_once_with("100", "debian")
        self.assertEqual(managed.get_registry()["items"][0]["_os_family"], "debian")
        self.assertEqual(self.row()["update_check"]["count"], 0)

    def test_existing_global_refresh_route_keeps_its_collector_contract(self):
        with patch.object(managed, "_DETECTORS", [managed._detect_lxc_containers]), \
                patch.object(managed, "_refresh_lxc_pkg_cache_if_stale", return_value={}) as refresh:
            response = self.client.post("/api/managed-installs/refresh")
        self.assertEqual(response.status_code, 200, response.json)
        refresh.assert_called_once_with("100", "debian")
        self.assertEqual(managed.get_registry()["items"][0]["_os_family"], "debian")

    def test_existing_lifecycle_refresh_keeps_index_refresh_default(self):
        with patch.object(managed, "_refresh_lxc_pkg_cache_if_stale", return_value={}) as refresh:
            item = managed.refresh_lxc(100)
        refresh.assert_called_once_with("100", "debian")
        self.assertEqual(item["update_check"]["_count"], 0)

    def test_other_lxc_has_independent_ip_cache_and_manual_rate_limit(self):
        conf200 = Path(self.temp.name) / "200.conf"
        conf200.write_text("onboot: 1\n")
        original_open = self.scope["open"]
        self.scope["open"] = lambda path, *args, **kw: (
            builtins.open(conf200, *args, **kw) if path == "/etc/pve/lxc/200.conf"
            else original_open(path, *args, **kw))
        original_exists = self.scope["os"].path.exists
        self.scope["os"].path.exists = lambda path: path == "/etc/pve/lxc/200.conf" or original_exists(path)
        self.assertEqual(self.client.post("/api/vms/100/updates/check").status_code, 200)
        with patch.object(managed, "_list_pve_lxcs", return_value=[
                {"vmid": "200", "name": "other-ct", "status": "running"}]):
            response = self.client.post("/api/vms/200/updates/check")
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["vmid"], 200)
        self.assertEqual(response.json["update_check"]["count"], 0)
        self.scope["_get_lxc_ip_info_cached"](100)
        self.scope["_get_lxc_ip_info_cached"](200)
        self.assertEqual(set(self.scope["_lxc_ip_cache"]), {100, 200})
        self.assertEqual(self.client.post("/api/vms/100/updates/check").status_code, 429)

    def test_oci_and_managed_apps_never_run_generic_package_check(self):
        for flags in ({"_is_oci": True}, {"_managed_oci_app": "secure-gateway"}):
            with self.subTest(flags=flags):
                entry = {"_vmid": "100", "_os_family": "ubuntu", **flags}
                before = len(self.commands)
                result = managed._check_lxc_updates(entry, refresh_package_cache=False)
                self.assertEqual(result["_count"], 0)
                self.assertEqual(entry["_os_family"], "ubuntu")
                self.assertEqual(len(self.commands) - before, 0)

    def test_lifecycle_invalidation_still_forces_probe_and_negative_cache_is_bounded(self):
        self.row()
        self.ip = "10.100.100.220"
        self.scope["_invalidate_lxc_ip"]("100")
        self.assertEqual(self.row()["ip"], self.ip)
        self.ip_probe.return_value = None
        self.ip_probe.side_effect = None
        self.scope["_invalidate_lxc_ip"](100)
        for _ in range(5):
            self.assertNotIn("ip", self.row())
        self.assertEqual(self.ip_probe.call_count, 3)
        self.clock.monotonic.return_value += 5
        self.row()
        self.assertEqual(self.ip_probe.call_count, 4)


class FreshnessTests(unittest.TestCase):
    def test_old_missing_invalid_and_future_timestamps_are_stale(self):
        for stamp in (None, "", "bad", "2020-01-01T00:00:00Z", "2999-01-01T00:00:00Z"):
            self.assertTrue(managed.lxc_update_freshness({"last_check": stamp})["stale"])

    def test_recent_check_and_threshold(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        with patch.object(managed.datetime, 'datetime', wraps=datetime.datetime) as clock:
            clock.now.return_value = now
            for age, stale in ((60, False), (86400 + 600, False), (172799, False),
                               (172800, True), (172801, True)):
                observation = {"last_check": (now - datetime.timedelta(seconds=age)).isoformat()}
                result = managed.lxc_update_freshness(observation)
                self.assertEqual(result["stale"], stale)
                self.assertEqual(result["stale_after_seconds"], 172800)


if __name__ == "__main__":
    unittest.main()
