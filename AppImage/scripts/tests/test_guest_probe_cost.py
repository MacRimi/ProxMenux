"""Background probes of guests avoid starting a Perl client per guest: commands
inside a container go through lxc-attach, `pvesm status` is shared between
containers, and the backups of every guest come from one read per storage."""

import ast
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import guest_exec  # noqa: E402
import lxc_mount_points  # noqa: E402


def completed(stdout, returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class GuestExecTests(unittest.TestCase):
    def test_a_command_runs_through_lxc_attach_as_pct_exec_does(self):
        argv = guest_exec.command(101, ["cat", "/etc/os-release"])
        self.assertEqual(argv, ["/usr/bin/env", "-u", "SSL_CERT_FILE", "-u", "SSL_CERT_DIR",
                                "PATH=/sbin:/bin:/usr/sbin:/usr/bin", "/usr/bin/lxc-attach", "-n", "101",
                                "--keep-env", "--", "cat", "/etc/os-release"])
        self.assertTrue(guest_exec.is_command(argv))
        self.assertFalse(guest_exec.is_command(["pct", "status", "101"]))

    def test_status_reads_state_and_init_pid_from_lxc_info(self):
        with patch.object(guest_exec.subprocess, "run", return_value=completed("State:          RUNNING\nPID:            4242\n")) as run:
            self.assertEqual(guest_exec.status(101), (True, "4242"))
        self.assertEqual(run.call_args.args[0], ["/usr/bin/lxc-info", "-n", "101", "-s", "-p"])
        with patch.object(guest_exec.subprocess, "run", return_value=completed("State:          STOPPED\n")):
            self.assertEqual(guest_exec.status(101), (False, ""))
        with patch.object(guest_exec.subprocess, "run", side_effect=subprocess.TimeoutExpired("lxc-info", 5)):
            self.assertEqual(guest_exec.status(101), (False, ""))

    def test_no_background_probe_starts_pct_exec(self):
        for name in ("lxc_apps.py", "managed_installs.py", "native_app_discovery.py",
                     "docker_app_discovery.py", "lxc_mount_points.py"):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            for spelling in ('"pct", "exec"', "'pct', 'exec'", '_PCT_BIN, "exec"', '_PCT, "exec"'):
                self.assertNotIn(spelling, text, name)


class SharedStorageStatusTests(unittest.TestCase):
    def setUp(self):
        lxc_mount_points._storages_cache.update(at=0.0, value=None)
        self.addCleanup(lxc_mount_points._storages_cache.update, at=0.0, value=None)

    def test_pvesm_status_is_read_once_for_every_container_within_a_minute(self):
        output = "Name Type Status Total Used Available %\nlocal dir active 100 40 60 40.00%\n"
        with patch.object(lxc_mount_points.subprocess, "run", return_value=completed(output)) as run:
            first = lxc_mount_points._list_pve_storages()
            second = lxc_mount_points._list_pve_storages()
        self.assertEqual(first, second)
        self.assertEqual(first["local"]["total_kib"], 100)
        self.assertEqual(run.call_count, 1)

    def test_a_failed_read_is_not_kept(self):
        with patch.object(lxc_mount_points.subprocess, "run", return_value=completed("", 1)) as run:
            lxc_mount_points._list_pve_storages()
            lxc_mount_points._list_pve_storages()
        self.assertEqual(run.call_count, 2)


def backup_functions(run):
    names = ("_backup_entry", "_scan_backup_storages", "_guest_backups_payload")
    nodes = [node for node in ast.parse((SCRIPTS / "flask_server.py").read_text(encoding="utf-8")).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"subprocess": type("S", (), {"run": staticmethod(run)}), "json": json,
                 "datetime": datetime, "format_bytes": lambda size: f"{size} B",
                 "get_proxmox_node_name": lambda: "pve",
                 "get_cached_pvesh_storage_list": lambda: [
                     {"storage": "local", "content": "iso,backup"},
                     {"storage": "pbs", "type": "pbs", "content": ""},
                     {"storage": "data", "content": "images"}]}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "flask_server.py", "exec"), namespace)
    return namespace


class BackupScanTests(unittest.TestCase):
    def test_every_guest_comes_from_one_read_of_each_backup_storage(self):
        calls = []
        listings = {
            "local": [{"content": "backup", "vmid": 100, "volid": "local:backup/vzdump-lxc-100-a.tar.zst",
                       "size": 10, "ctime": 1}],
            "pbs": [{"content": "backup", "vmid": 100, "volid": "pbs:backup/ct/100/b", "subtype": "lxc",
                     "size": 20, "ctime": 2},
                    {"content": "backup", "vmid": 200, "volid": "pbs:backup/vm/200/c", "subtype": "qemu",
                     "size": 30, "ctime": 3}],
        }

        def run(command, **_kwargs):
            calls.append(command)
            return completed(json.dumps(listings[command[2].split("/")[4]]))

        functions = backup_functions(run)
        found = functions["_scan_backup_storages"]()
        self.assertEqual(sorted(found), [100, 200])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("--vmid" not in command and command[3:5] == ["--content", "backup"] for command in calls))
        payload = functions["_guest_backups_payload"](100, found[100])
        self.assertEqual([item["storage"] for item in payload["backups"]], ["pbs", "local"])
        self.assertEqual(payload["backups"][1]["type"], "lxc")

    def test_one_guest_is_asked_by_its_id(self):
        calls = []

        def run(command, **_kwargs):
            calls.append(command)
            return completed("[]")

        backup_functions(run)["_scan_backup_storages"](105)
        self.assertTrue(all(command[5:7] == ["--vmid", "105"] for command in calls))


if __name__ == "__main__":
    unittest.main()
