"""Server-side safety boundary for plain stopped-LXC removal."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SCRIPTS)]

import flask_lxc_removal_routes as routes
import jwt_middleware
import lxc_check_job


VMID = 100
NODE = "fixture"
TASK = "UPID:fixture:0000000A:0000000B:0000000C:vzdestroy:100:root@pam:"


class LxcRemoveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.conf = self.root / "lxc"
        self.conf.mkdir()
        self.oci = self.root / "oci"
        self.oci.mkdir()
        self.write_config()
        self.resources = [dict(vmid=VMID, type="lxc", node=NODE, name="plain-test", status="stopped")]
        self.ha, self.replication, self.pending, self.active_tasks = [], [], [], []
        self.storages, self.storage_content = [], {}
        self.delete_calls = []
        self.task_state = {"status": "running"}
        self.remove_completed = False
        self.run = Mock(side_effect=self.pvesh)
        self.enterContext(patch.object(routes, "CONF_DIR", self.conf))
        self.enterContext(patch.object(routes, "OCI_INSTANCE_ROOT", self.oci))
        self.enterContext(patch.object(routes, "_local_node", return_value=NODE))
        self.enterContext(patch.object(routes, "is_pbs_host", return_value=False))
        self.enterContext(patch.object(routes, "_get_jwt_secret", return_value="fixture-secret"))
        self.enterContext(patch.object(routes, "subprocess", SimpleNamespace(
            run=self.run, TimeoutExpired=subprocess.TimeoutExpired,
        )))
        self.enterContext(patch.object(jwt_middleware, "load_auth_config", return_value={}))
        self.enterContext(patch.object(jwt_middleware, "access_mode", return_value="password"))
        self.enterContext(patch.object(jwt_middleware, "verify_token_full",
                                       side_effect=lambda token: (token, "full") if token in {"admin", "observer"} else (None, None)))
        self.enterContext(patch.object(jwt_middleware, "profile_for",
                                       side_effect=lambda _mode, user=None, _scope=None: "admin" if user == "admin" else "observer"))
        app = Flask(__name__)
        app.testing = True
        app.register_blueprint(routes.lxc_removal_bp)
        self.client = app.test_client()

    def write_config(self, extra=""):
        (self.conf / f"{VMID}.conf").write_text(
            "arch: amd64\nhostname: plain-test\nrootfs: local-lvm:subvol-100-disk-0,size=8G\n" + extra,
            encoding="utf-8",
        )

    def result(self, payload, code=0):
        return subprocess.CompletedProcess([], code, json.dumps(payload), "")

    def pvesh(self, argv, **_kwargs):
        self.assertEqual(argv[0], "pvesh")
        if argv[:4] == ["pvesh", "get", "/cluster/resources", "--type"]:
            return self.result(self.resources)
        path = argv[2] if len(argv) > 2 else ""
        if path == "/cluster/ha/resources":
            return self.result(self.ha)
        if path == "/storage":
            return self.result(self.storages)
        if path == f"/nodes/{NODE}/lxc/{VMID}/replication":
            return self.result(self.replication)
        if path == f"/nodes/{NODE}/lxc/{VMID}/pending":
            return self.result(self.pending)
        if path == f"/nodes/{NODE}/tasks":
            return self.result(self.active_tasks)
        if path.startswith(f"/nodes/{NODE}/storage/") and path.endswith("/content"):
            storage = path.split("/")[4]
            payload = self.storage_content.get(storage, [])
            return self.result(payload)
        if path == f"/nodes/{NODE}/tasks/{TASK}/status":
            if self.remove_completed and self.task_state.get("status") == "stopped" and self.task_state.get("exitstatus") == "OK":
                self.resources = []
                try:
                    (self.conf / f"{VMID}.conf").unlink()
                except FileNotFoundError:
                    pass
            return self.result(self.task_state)
        if argv[:2] == ["pvesh", "delete"]:
            self.delete_calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, TASK + "\n", "")
        raise AssertionError(f"unexpected pvesh call: {argv}")

    def call(self, method, path, body=None, token="admin"):
        return self.client.open(path, method=method, json=body,
                                headers={"Authorization": f"Bearer {token}"})

    def preview(self):
        response = self.call("GET", f"/api/vms/{VMID}/remove-preview")
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def fake_lock(self):
        lock = Mock()
        return lock, SimpleNamespace(
            acquire=Mock(return_value=lock), begin_control=Mock(), retain_control=Mock(),
        )

    def test_preview_reports_only_a_stopped_plain_lxc_and_unverified_archives(self):
        self.storages = [{"storage": "backup", "content": "backup", "type": "dir"}]
        self.storage_content["backup"] = [{"content": "backup", "subtype": "lxc",
                                          "volid": "backup:vzdump-lxc-100-1", "ctime": 42, "size": 12}]
        data = self.preview()
        self.assertTrue(data["eligible"])
        self.assertEqual(data["target"], {"vmid": VMID, "name": "plain-test", "node": NODE, "status": "stopped"})
        self.assertEqual(data["disk"], {"storage": "local-lvm", "volume": "local-lvm:subvol-100-disk-0", "size": "8G"})
        self.assertEqual(data["backup"]["state"], "unverified")
        self.assertFalse(self.delete_calls)

    def test_preview_blocks_each_unsafe_target_without_a_delete(self):
        cases = {
            "running": lambda: self.resources.__setitem__(0, {**self.resources[0], "status": "running"}),
            "protected": lambda: self.write_config("protection: 1\n"),
            "locked": lambda: self.write_config("lock: backup\n"),
            "mount": lambda: self.write_config("mp0: local-lvm:subvol-100-disk-1,mp=/data\n"),
            "unused": lambda: self.write_config("unused0: local-lvm:subvol-100-disk-1\n"),
            "bind": lambda: self.write_config("lxc.mount.entry: /srv data none bind 0 0\n"),
            "custom-lxc": lambda: self.write_config("lxc.apparmor.profile: unconfined\n"),
            "oci-marker": lambda: self.write_config("# proxmenux-instance=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\n"),
            "ha": lambda: setattr(self, "ha", [{"sid": "ct:100"}]),
            "replication": lambda: setattr(self, "replication", [{"id": "job"}]),
            "pending": lambda: setattr(self, "pending", [{"key": "memory", "value": "2048"}]),
            "backup-active": lambda: setattr(self, "active_tasks", [{"id": "100", "upid": "UPID:test"}]),
        }
        for name, prepare in cases.items():
            with self.subTest(name=name):
                self.write_config()
                self.resources = [dict(vmid=VMID, type="lxc", node=NODE, name="plain-test", status="stopped")]
                self.ha, self.replication, self.pending, self.active_tasks = [], [], [], []
                prepare()
                response = self.call("GET", f"/api/vms/{VMID}/remove-preview")
                self.assertEqual(response.status_code, 200, response.json)
                self.assertFalse(response.json["eligible"])
                self.assertTrue(response.json["reasons"])
                self.assertFalse(self.delete_calls)

    def test_preview_error_and_observer_have_zero_destructive_calls(self):
        self.storages = [{"storage": "backup", "content": "backup"}]
        original = self.pvesh
        def unavailable(argv, **kwargs):
            if argv[2] == f"/nodes/{NODE}/storage/backup/content":
                return subprocess.CompletedProcess(argv, 1, "", "offline")
            return original(argv, **kwargs)
        self.run.side_effect = unavailable
        self.assertEqual(self.call("GET", f"/api/vms/{VMID}/remove-preview").status_code, 503)
        self.run.reset_mock()
        self.assertEqual(self.call("GET", f"/api/vms/{VMID}/remove-preview", token="observer").status_code, 403)
        self.assertEqual(self.run.call_count, 0)
        self.assertFalse(self.delete_calls)

    def test_remove_requires_exact_vmid_and_a_no_backup_ack_before_the_one_native_delete(self):
        check = self.preview()["check"]
        lock, module = self.fake_lock()
        with patch.dict(sys.modules, {"lxc_check_job": module}):
            for body in ({"check": check, "confirm_vmid": "99"}, {"check": check, "confirm_vmid": "100"}):
                response = self.call("POST", f"/api/vms/{VMID}/remove", body)
                self.assertIn(response.status_code, (409, 422), response.json)
            self.assertFalse(self.delete_calls)
            response = self.call("POST", f"/api/vms/{VMID}/remove", {
                "check": check, "confirm_vmid": "100", "confirm_no_backup": True,
            })
        self.assertEqual(response.status_code, 202, response.json)
        self.assertEqual(response.json, {"state": "running", "task": TASK, "node": NODE})
        self.assertEqual(len(self.delete_calls), 1)
        self.assertEqual(self.delete_calls[0], ["pvesh", "delete", f"/nodes/{NODE}/lxc/{VMID}"])
        self.assertNotIn("--force", self.delete_calls[0])
        self.assertNotIn("--purge", self.delete_calls[0])
        module.begin_control.assert_called_once_with(lock, NODE)
        module.retain_control.assert_called_once_with(VMID, TASK, lock)

    def test_changed_config_or_duplicate_submit_never_reaches_native_delete(self):
        check = self.preview()["check"]
        self.write_config("memory: 2048\n")
        _lock, module = self.fake_lock()
        with patch.dict(sys.modules, {"lxc_check_job": module}):
            changed = self.call("POST", f"/api/vms/{VMID}/remove", {
                "check": check, "confirm_vmid": "100", "confirm_no_backup": True,
            })
        self.assertEqual(changed.status_code, 409, changed.json)
        self.assertEqual(changed.json["error"], "target_changed")
        self.assertFalse(self.delete_calls)
        check = self.preview()["check"]
        _lock, busy = self.fake_lock()
        busy.acquire.side_effect = BlockingIOError
        with patch.dict(sys.modules, {"lxc_check_job": busy}):
            duplicate = self.call("POST", f"/api/vms/{VMID}/remove", {
                "check": check, "confirm_vmid": "100", "confirm_no_backup": True,
            })
        self.assertEqual(duplicate.status_code, 409, duplicate.json)
        self.assertFalse(self.delete_calls)

    def test_missing_upid_is_unknown_and_never_retries(self):
        check = self.preview()["check"]
        lock, module = self.fake_lock()
        self.run.side_effect = lambda argv, **kwargs: (
            subprocess.CompletedProcess(argv, 0, "", "") if argv[:2] == ["pvesh", "delete"] else self.pvesh(argv, **kwargs)
        )
        with patch.dict(sys.modules, {"lxc_check_job": module}):
            response = self.call("POST", f"/api/vms/{VMID}/remove", {
                "check": check, "confirm_vmid": "100", "confirm_no_backup": True,
            })
        self.assertEqual((response.status_code, response.json["state"]), (202, "unknown"))
        self.assertEqual(len([call for call in self.run.call_args_list if call.args[0][:2] == ["pvesh", "delete"]]), 1)
        module.retain_control.assert_not_called()
        module.begin_control.assert_called_once_with(lock, NODE)

    def test_task_status_tracks_the_original_destroy_task_and_checks_reuse(self):
        bad = self.call("GET", f"/api/vms/{VMID}/remove-task/UPID:other")
        self.assertEqual(bad.status_code, 400)
        self.run.assert_not_called()
        self.task_state = {"status": "running"}
        self.assertEqual(self.call("GET", f"/api/vms/{VMID}/remove-task/{TASK}").json["state"], "running")
        self.task_state = {"status": "stopped", "exitstatus": "OK"}
        self.resources = [dict(vmid=VMID, type="lxc", node=NODE, status="stopped")]
        warning = self.call("GET", f"/api/vms/{VMID}/remove-task/{TASK}").json
        self.assertEqual((warning["state"], warning["reason"]), ("warning", "vmid_still_present"))
        self.resources = [dict(vmid=VMID, type="lxc", node=NODE, status="stopped")]
        self.write_config()
        self.task_state = {"status": "stopped", "exitstatus": "OK"}
        self.remove_completed = True
        succeeded = self.call("GET", f"/api/vms/{VMID}/remove-task/{TASK}").json
        self.assertEqual(succeeded["state"], "succeeded")
        self.assertFalse((self.conf / f"{VMID}.conf").exists())
        self.assertFalse(self.delete_calls, "status reads never issue a second delete")

    def test_failed_task_and_task_read_failure_never_claim_success(self):
        self.task_state = {"status": "stopped", "exitstatus": "destroy failed"}
        failed = self.call("GET", f"/api/vms/{VMID}/remove-task/{TASK}").json
        self.assertEqual((failed["state"], failed["exitstatus"]), ("failed", "destroy failed"))
        original = self.pvesh
        self.run.side_effect = lambda argv, **kwargs: (
            subprocess.CompletedProcess(argv, 1, "", "") if "/tasks/" in argv[2] else original(argv, **kwargs)
        )
        unknown = self.call("GET", f"/api/vms/{VMID}/remove-task/{TASK}").json
        self.assertEqual(unknown["state"], "unknown")
        self.assertFalse(self.delete_calls)

    def test_shared_lxc_mutex_accepts_only_the_original_destroy_task(self):
        lock_path = self.root / "control.lock"
        with lock_path.open("w+") as stream:
            lxc_check_job._write_control(stream, {"node": NODE, "task": TASK})
            done = subprocess.CompletedProcess([], 0, json.dumps({"status": "stopped", "exitstatus": "OK"}), "")
            with patch.object(lxc_check_job.subprocess, "run", return_value=done) as command:
                lxc_check_job.check_control_task(VMID, stream)
        self.assertEqual(lock_path.read_text(), "")
        self.assertEqual(command.call_args.args[0][2], f"/nodes/{NODE}/tasks/{TASK}/status")


if __name__ == "__main__":
    unittest.main()
