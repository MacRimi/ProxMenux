"""Guest archive deletion contract. No real Proxmox commands or backups."""

import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "AppImage/scripts"
sys.path.insert(0, str(SCRIPTS))
import guest_backup_archives as archives

VOLUME = "local:backup/vzdump-lxc-100-2026_10_16-12_00_00.tar.zst"
OTHER = VOLUME.replace("12_00_00", "13_00_00")
TASK = "UPID:pve1:00000001:00000002:00000003:imgdel:100:root@pam:"


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.node = patch.object(archives, "_node", return_value="pve1")
        self.node.start()
        self.addCleanup(self.node.stop)
        self.inventory = [{"volid": VOLUME, "vmid": 100, "content": "backup", "protected": False}]
        self.calls = []
        self.response = None
        archives._tasks.clear()

    def run_pvesh(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "get" and args[1].endswith("/content"):
            return copy.deepcopy(self.inventory)
        if args[0] == "delete":
            if isinstance(self.response, Exception):
                raise self.response
            return self.response
        return {"status": "stopped", "exitstatus": "OK"}

    def delete(self, volumes=(VOLUME,), **kwargs):
        data = {"confirm": True, "backups": [{"storage": v.split(":")[0], "volid": v} for v in volumes]}
        data.update(kwargs)
        with patch.object(archives, "_pvesh", side_effect=self.run_pvesh):
            return archives.delete_guest_backups(100, data)

    def test_success_uses_guest_filtered_native_inventory_and_delete(self):
        self.assertEqual(self.delete()["results"], [{"storage": "local", "volid": VOLUME, "status": "deleted"}])
        self.assertEqual(self.calls, [
            ["get", "/nodes/pve1/storage/local/content", "--content", "backup", "--vmid", "100"],
            ["delete", f"/nodes/pve1/storage/local/content/{VOLUME}", "--delay", "1"],
        ])

    def test_a_deletion_that_ends_within_the_delay_prints_its_log_and_counts_as_deleted(self):
        # Real pvesh output on a directory storage: the task log, not JSON.
        run = subprocess.CompletedProcess([], 0, stdout=f"Removed volume '{VOLUME}'\n", stderr="")
        with patch.object(archives.subprocess, "run", return_value=run):
            self.assertEqual(archives._pvesh(["delete", f"/nodes/pve1/storage/local/content/{VOLUME}", "--delay", "1"]),
                             f"Removed volume '{VOLUME}'")
        self.response = f"Removed volume '{VOLUME}'"
        self.assertEqual(self.delete()["results"][0]["status"], "deleted")
        self.response = "Removed volume 'local:backup/another-archive.tar.zst'"
        self.assertEqual(self.delete()["results"][0]["status"], "unconfirmed")
        with patch.object(archives.subprocess, "run", return_value=run), self.assertRaises(archives.BackupArchiveError):
            archives._pvesh(["get", "/nodes/pve1/storage/local/content"])

    def test_bad_payloads_and_paths_never_reach_proxmox(self):
        payloads = [None, [], {}, {"confirm": 1}, {"confirm": True, "backups": []},
                    {"confirm": True, "backups": [None]}, {"confirm": True, "backups": [VOLUME]},
                    {"confirm": True, "backups": [{"storage": "local", "volid": VOLUME}] * 21}]
        for volid in ("local:../etc/passwd", "local:backup/../x", "local:/etc/pve/storage.cfg", "local:backup//x",
                      "local:backup/x%2fy", "local:backup/x\n--force", "local:backup/x;touch /tmp/x", "other:backup/x"):
            payloads.append({"confirm": True, "backups": [{"storage": "local", "volid": volid}]})
        for storage in ("../local", "-x", "local\n", 2, None):
            payloads.append({"confirm": True, "backups": [{"storage": storage, "volid": VOLUME}]})
        with patch.object(archives, "_pvesh") as run:
            for data in payloads:
                with self.subTest(data=data), self.assertRaises(archives.BackupArchiveError):
                    archives.delete_guest_backups(100, data)
            for vmid in (0, 99, 1000000000):
                with self.assertRaises(archives.BackupArchiveError):
                    archives.delete_guest_backups(vmid, {"confirm": True, "backups": [{"storage": "local", "volid": VOLUME}]})
        run.assert_not_called()

    def test_duplicate_selection_rejected_before_commands(self):
        with self.assertRaises(archives.BackupArchiveError):
            self.delete((VOLUME, VOLUME))
        self.assertEqual(self.calls, [])

    def test_newly_protected_archives_fail_the_whole_batch(self):
        self.inventory.append({"volid": OTHER, "vmid": 100, "content": "backup", "protected": True})
        for protection in (True, 1, "1", "true", "unexpected"):
            self.inventory[-1]["protected"] = protection
            with self.subTest(protection=protection), self.assertRaises(archives.BackupArchiveError) as error:
                self.delete((VOLUME, OTHER))
            self.assertEqual(error.exception.code, 409)
        self.assertFalse(any(call[0] == "delete" for call in self.calls))

    def test_missing_cross_guest_and_non_backup_volumes_are_never_deleted(self):
        for entries in ([], [{"volid": VOLUME, "vmid": 101, "content": "backup"}],
                        [{"volid": VOLUME, "content": "backup"}],
                        [{"volid": VOLUME, "vmid": 100, "content": "images"}]):
            self.inventory = entries
            with self.subTest(entries=entries), self.assertRaises(archives.BackupArchiveError):
                self.delete()
        self.assertFalse(any(call[0] == "delete" for call in self.calls))

    def test_storage_failure_prevents_every_delete(self):
        def unavailable(args):
            self.assertEqual(args[0], "get")
            raise archives.BackupArchiveError("offline", 502)
        with patch.object(archives, "_pvesh", side_effect=unavailable), self.assertRaises(archives.BackupArchiveError):
            archives.delete_guest_backups(100, {"confirm": True, "backups": [
                {"volid": VOLUME, "storage": "local"}, {"volid": "nas:backup/x", "storage": "nas"}]})

    def test_partial_native_errors_remain_unconfirmed(self):
        self.inventory.append({"volid": OTHER, "vmid": 100, "content": "backup"})
        def native(args):
            if args[0] == "delete" and OTHER in args[1]:
                raise archives.BackupArchiveError("backup is protected", 502)
            return self.run_pvesh(args)
        with patch.object(archives, "_pvesh", side_effect=native):
            result = archives.delete_guest_backups(100, {"confirm": True, "backups": [
                {"volid": v, "storage": "local"} for v in (VOLUME, OTHER)]})
        self.assertEqual([item["status"] for item in result["results"]], ["deleted", "unconfirmed"])
        self.assertIn("protected", result["results"][1]["error"])

    def test_native_task_is_not_a_success_until_exit_ok(self):
        self.response = TASK
        result = self.delete()["results"][0]
        self.assertEqual(result["status"], "pending")
        for native, expected in (({"status": "running"}, "pending"),
                                 ({"status": "stopped", "exitstatus": "OK"}, "deleted"),
                                 ({"status": "stopped", "exitstatus": "cannot delete protected backup"}, "unconfirmed"),
                                 ({"status": "stopped"}, "unconfirmed")):
            with patch.object(archives, "_pvesh", return_value=native) as run:
                answer = archives.guest_backup_deletion_status(100, TASK)
            self.assertEqual(answer["status"], expected)
            run.assert_called_once_with(["get", f"/nodes/pve1/tasks/{TASK}/status"])

    def test_poll_cannot_read_arbitrary_tasks_or_other_guests(self):
        self.response = TASK
        self.delete()
        with patch.object(archives, "_pvesh") as run:
            for vmid, task in ((101, TASK), (100, "../../status"), (100, None), (100, TASK + "x")):
                with self.assertRaises(archives.BackupArchiveError):
                    archives.guest_backup_deletion_status(vmid, task)
            archives._tasks[TASK]["created"] -= 3601
            with self.assertRaises(archives.BackupArchiveError):
                archives.guest_backup_deletion_status(100, TASK)
        run.assert_not_called()

    def test_invalid_native_task_answers_never_claim_success(self):
        for response in ("", {}, [TASK], TASK.replace("imgdel", "vzdump"), TASK.replace("pve1", "pve2")):
            self.response = response
            with self.subTest(response=response):
                self.assertEqual(self.delete()["results"][0]["status"], "unconfirmed")

    def test_pvesh_uses_argv_and_handles_failure_and_timeout(self):
        with patch.object(archives.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout="null")) as run:
            self.assertIsNone(archives._pvesh(["delete", "/native/path"]))
        self.assertEqual(run.call_args.args[0], ["pvesh", "delete", "/native/path", "--output-format", "json"])
        self.assertNotIn("shell", run.call_args.kwargs)
        with patch.object(archives.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout="")):
            self.assertIsNone(archives._pvesh(["delete", "/native/path"]))
        for response in (types.SimpleNamespace(returncode=1, stderr="protected", stdout=""),
                         types.SimpleNamespace(returncode=0, stdout="not JSON")):
            with patch.object(archives.subprocess, "run", return_value=response), self.assertRaises(archives.BackupArchiveError):
                archives._pvesh(["delete", "/native/path"])
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("pvesh", 20)):
            with patch.object(archives.subprocess, "run", side_effect=error), self.assertRaises(archives.BackupArchiveError):
                archives._pvesh(["delete", "/native/path"])


class RouteTests(unittest.TestCase):
    """Compile the real route bodies/decorators without starting host services."""
    def setUp(self):
        auth = types.ModuleType("auth_manager")
        auth.load_auth_config = lambda: {"enabled": True}
        auth.verify_token = lambda token: "tester" if token == "admin" else None
        auth.verify_token_full = lambda token: ("tester", "full_admin" if token == "admin" else "read_only")
        spec = importlib.util.spec_from_file_location("guest_backup_test_middleware", SCRIPTS / "jwt_middleware.py")
        middleware = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, auth_manager=auth):
            spec.loader.exec_module(middleware)
        self.app = Flask(__name__)
        self.service = Mock(return_value={"results": []})
        self.status = Mock(return_value={"volid": VOLUME, "status": "deleted"})
        self.invalidate = Mock()
        self.namespace = {"app": self.app, "require_admin_scope": middleware.require_admin_scope,
                          "request": request, "jsonify": jsonify, "BackupArchiveError": archives.BackupArchiveError,
                          "delete_guest_backups": self.service, "guest_backup_deletion_status": self.status,
                          "_vm_cache_invalidate": self.invalidate, "_vm_backups_cache": {}}
        source = ast.parse((SCRIPTS / "flask_server.py").read_text())
        wanted = {"api_delete_vm_backups", "api_vm_backup_deletion_status"}
        routes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        self.assertEqual(len(routes), 2)
        exec(compile(ast.Module(body=routes, type_ignores=[]), "flask_server.py", "exec"), self.namespace)
        self.client = self.app.test_client()

    def test_both_routes_reject_unauthenticated_and_read_only_requests(self):
        for headers, status in (({}, 401), ({"Authorization": "Bearer reader"}, 403)):
            self.assertEqual(self.client.post("/api/vms/100/backups/delete", json={}, headers=headers).status_code, status)
            self.assertEqual(self.client.get("/api/vms/100/backups/delete-status?task=x", headers=headers).status_code, status)
        self.service.assert_not_called()
        self.status.assert_not_called()
        self.invalidate.assert_not_called()

    def test_admin_route_passes_payload_and_invalidates_even_after_errors(self):
        data = {"confirm": True, "backups": [{"storage": "local", "volid": VOLUME}]}
        headers = {"Authorization": "Bearer admin"}
        self.assertEqual(self.client.post("/api/vms/100/backups/delete", json=data, headers=headers).status_code, 200)
        self.service.assert_called_once_with(100, data)
        self.invalidate.assert_called_once_with(100, {})
        self.service.side_effect = archives.BackupArchiveError("protected", 409)
        self.assertEqual(self.client.post("/api/vms/100/backups/delete", json=data, headers=headers).status_code, 409)
        self.assertEqual(self.invalidate.call_count, 2)

    def test_poll_invalidates_only_after_completion(self):
        headers = {"Authorization": "Bearer admin"}
        self.status.return_value = {"status": "pending"}
        self.client.get("/api/vms/100/backups/delete-status?task=x", headers=headers)
        self.invalidate.assert_not_called()
        self.status.return_value = {"status": "deleted"}
        self.client.get("/api/vms/100/backups/delete-status?task=x", headers=headers)
        self.status.assert_called_with(100, "x")
        self.invalidate.assert_called_once_with(100, {})

    def test_runtime_module_is_shipped(self):
        self.assertIn('cp "$SCRIPT_DIR/guest_backup_archives.py" "$APP_DIR/usr/bin/"', (SCRIPTS / "build_appimage.sh").read_text())


if __name__ == "__main__":
    unittest.main()
