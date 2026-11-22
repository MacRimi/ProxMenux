"""Server-side safety boundary for plain stopped-LXC removal."""

import json
import os
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
import custom_links
import jwt_middleware
import lxc_check_job


VMID = 100
NODE = "fixture"
TASK = "UPID:fixture:0000000A:0000000B:0000000C:vzdestroy:100:root@pam:"
VOLUME = "local-lvm:subvol-100-disk-0"


def current_lxc_options():
    # PVE returns the current configuration even with no pending changes.
    return [
        {"key": "arch", "value": "amd64"},
        {"key": "hostname", "value": "plain-test"},
        {"key": "rootfs", "value": "local-lvm:subvol-100-disk-0,size=8G"},
        {"key": "memory", "value": "2048"},
    ]


def replication_job(guest, **options):
    # GET /cluster/replication returns job configs with the numeric guest ID.
    return {
        "id": f"{guest}-0", "guest": guest, "jobnum": 0, "type": "local",
        "target": "replica", "source": NODE, "schedule": "*/15", **options,
    }


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
        self.write_generation(4)
        (self.root / ".version").write_text(json.dumps({"starttime": 1700000000}))
        self.resources = [dict(vmid=VMID, type="lxc", node=NODE, name="plain-test", status="stopped")]
        self.ha, self.replication = [], []
        self.pending = current_lxc_options()
        self.storage_content = {"local-lvm": [{"volid": VOLUME, "vmid": VMID, "content": "rootdir"}]}
        self.delete_calls = []
        self.protection_calls = []
        self.task_state = {"status": "running"}
        self.dispatch_mode = "accepted"
        self.run = Mock(side_effect=self.pvesh)
        self.enterContext(patch.object(routes, "CONF_DIR", self.conf))
        self.enterContext(patch.object(routes, "CFS_DIR", self.root))
        self.enterContext(patch.object(routes.receipts, "DIRECTORY", self.root / "removals"))
        self.enterContext(patch.object(custom_links, "_CUSTOM_LINKS_PATH", str(self.root / "links.json")))
        self.enterContext(patch.object(custom_links, "_cached_entries", None))
        self.enterContext(patch.object(lxc_check_job, "LOCK_DIR", self.root))
        self.enterContext(patch.object(lxc_check_job, "subprocess", SimpleNamespace(
            run=self.run, TimeoutExpired=subprocess.TimeoutExpired,
        )))
        self.enterContext(patch.object(routes, "_invalidate"))
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

    def write_generation(self, version):
        (self.root / ".vmlist").write_text(json.dumps(
            {"ids": {str(VMID): {"node": NODE, "type": "lxc", "version": version}}}
        ))

    def result(self, payload, code=0):
        return subprocess.CompletedProcess([], code, json.dumps(payload), "")

    def pvesh(self, argv, **_kwargs):
        if argv == ["/usr/bin/perl", routes.NATIVE_BRIDGE]:
            request = json.loads(_kwargs["input"])
            if request["action"] == "disable-protection":
                self.assertEqual(request["node"], NODE)
                self.assertEqual(set(request["params"]), {"vmid", "guard"})
                self.protection_calls.append(request)
                self.write_config()
                return self.result(1)
            if request["action"] == "remove-disk-status":
                self.assertEqual(request["node"], NODE)
                params = request["params"]
                self.assertEqual(set(params), {"vmid", "volume"})
                self.assertEqual(params["vmid"], VMID)
                storage = params["volume"].split(":", 1)[0]
                rows = self.storage_content.get(storage, [])
                match = [row for row in rows if row["volid"] == params["volume"]]
                if len(match) > 1 or (match and match[0]["vmid"] != VMID):
                    return self.result(None, code=1)
                return self.result(int(bool(match)))
            self.assertEqual((request["action"], request["node"]), ("remove", NODE))
            self.assertEqual(set(request["params"]), {
                "guard", "operation", "vmid", "volume", "purge", "destroy_unreferenced_disks",
            })
            self.assertEqual(_kwargs["timeout"], 12)
            self.delete_calls.append(request)
            params = request["params"]
            if self.dispatch_mode == "rejected":
                return self.result(None, code=1)
            if self.dispatch_mode != "delayed":
                (routes.receipts.DIRECTORY / params["operation"] / "result").write_text(TASK + "\n")
            if self.dispatch_mode == "timeout_after_claim":
                raise subprocess.TimeoutExpired(argv, 12)
            return self.result(TASK)
        self.assertEqual(argv[0], "pvesh")
        if argv[:4] == ["pvesh", "get", "/cluster/resources", "--type"]:
            return self.result(self.resources)
        path = argv[2] if len(argv) > 2 else ""
        if path == "/cluster/ha/resources":
            return self.result(self.ha)
        if path == "/cluster/replication":
            self.assertEqual(argv, ["pvesh", "get", "/cluster/replication", "--output-format", "json"])
            return self.result(self.replication)
        if path == f"/nodes/{NODE}/lxc/{VMID}/replication":
            return subprocess.CompletedProcess(argv, 1, "", f"no 'get' handler for '{path}'")
        if path == f"/nodes/{NODE}/lxc/{VMID}/pending":
            return self.result(self.pending)
        if path == f"/nodes/{NODE}/tasks/{TASK}/status":
            return self.result(self.task_state)
        raise AssertionError(f"unexpected pvesh call: {argv}")

    def call(self, method, path, body=None, token="admin"):
        return self.client.open(path, method=method, json=body,
                                headers={"Authorization": f"Bearer {token}"})

    def preview(self):
        response = self.call("GET", f"/api/vms/{VMID}/remove-preview")
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def confirm(self, check, *, vmid=VMID, **options):
        return self.call("POST", f"/api/vms/{vmid}/remove", {
            "check": check, "confirm_vmid": str(vmid), **options,
        })

    def status(self, check, token="admin"):
        return self.client.get(f"/api/vms/{VMID}/remove-operation", headers={
            "Authorization": f"Bearer {token}", "X-LXC-Removal-Check": check,
        })

    def fake_lock(self):
        lock = Mock()
        return lock, SimpleNamespace(
            acquire=Mock(return_value=lock), begin_removal=Mock(),
        )

    def test_preview_reads_identity_without_waiting_for_storage_and_jobs(self):
        data = self.preview()
        self.assertTrue(data["eligible"])
        self.assertEqual(data["target"], {"vmid": VMID, "name": "plain-test", "node": NODE, "status": "stopped"})
        self.assertEqual(data["disk"], {"storage": "local-lvm", "volume": "local-lvm:subvol-100-disk-0", "size": "8G"})
        self.assertNotIn("backup", data)
        self.assertEqual([call.args[0][2] for call in self.run.call_args_list], ["/cluster/resources"])
        self.assertFalse(self.delete_calls)

    def test_protection_confirmation_changes_only_protection_and_needs_a_new_remove_review(self):
        self.write_config("protection: 1\n")
        preview = self.preview()
        self.assertEqual(preview["reasons"], ["container_protected"])
        self.assertIsNone(preview["check"])
        self.assertFalse(self.protection_calls)
        token = preview["protection_check"]
        path = f"/api/vms/{VMID}/disable-removal-protection"
        self.assertEqual(self.confirm(token).status_code, 409)
        self.assertEqual(self.call("POST", path, {"check": token}, token="observer").status_code, 403)
        response = self.call("POST", path, {"check": token})
        self.assertEqual(response.json, {"protection": False})
        self.assertEqual(len(self.protection_calls), 1)
        self.assertFalse(self.delete_calls)
        self.assertIsNotNone(self.preview()["check"])
        self.assertEqual(self.call("POST", path, {"check": token}).status_code, 409)
        self.assertEqual(len(self.protection_calls), 1)

    def test_replacement_or_another_blocker_cannot_use_the_protection_confirmation(self):
        self.write_config("protection: 1\n")
        path = f"/api/vms/{VMID}/disable-removal-protection"
        token = self.preview()["protection_check"]
        self.write_generation(5)
        self.assertEqual(self.call("POST", path, {"check": token}).status_code, 409)
        self.resources[0]["status"] = "running"
        self.assertNotIn("protection_check", self.preview())
        self.assertFalse(self.protection_calls)
        self.assertFalse(self.delete_calls)

    def test_removal_does_not_accept_an_unverified_oci_record(self):
        record = self.oci / str(VMID) / "oci-compose.json"
        record.parent.mkdir()
        record.write_text(json.dumps({"installation_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}))
        response = self.call("GET", f"/api/vms/{VMID}/remove-preview")
        self.assertEqual(response.json, {"error": "oci_identity_unavailable"})

    def test_oci_journal_appearing_after_review_blocks_remove_and_protection(self):
        self.write_config("protection: 1\n")
        protection_check = self.preview()["protection_check"]
        journal = self.oci / str(VMID) / "transactions" / "historic" / "transaction.json"
        journal.parent.mkdir(parents=True)
        journal.write_text(json.dumps({"schema_version": 1, "phase": "recovering"}))
        result = self.call("POST", f"/api/vms/{VMID}/disable-removal-protection",
                           {"check": protection_check})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.protection_calls, [])
        self.write_config()
        journal.write_text(json.dumps({"schema_version": 1, "phase": "committed"}))
        before = self.preview()["check"]
        journal.write_text(json.dumps({"schema_version": 1, "phase": "recovering"}))
        result = self.confirm(before)
        self.assertEqual(result.json, {"error": "oci_identity_unavailable"})
        self.assertFalse(self.delete_calls)

    def test_preview_blocks_each_unsafe_target_without_a_delete(self):
        cases = {
            "running": lambda: self.resources.__setitem__(0, {**self.resources[0], "status": "running"}),
            "protected": lambda: self.write_config("protection: 1\n"),
            "locked": lambda: self.write_config("lock: backup\n"),
            "template": lambda: self.write_config("template: 1\n"),
            "mount": lambda: self.write_config("mp0: local-lvm:subvol-100-disk-1,mp=/data\n"),
            "unused": lambda: self.write_config("unused0: local-lvm:subvol-100-disk-1\n"),
            "bind": lambda: self.write_config("lxc.mount.entry: /srv data none bind 0 0\n"),
            "custom-lxc": lambda: self.write_config("lxc.apparmor.profile: unconfined\n"),
            "oci-marker": lambda: self.write_config("# proxmenux-instance=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\n"),
        }
        for name, prepare in cases.items():
            with self.subTest(name=name):
                self.write_config()
                self.resources = [dict(vmid=VMID, type="lxc", node=NODE, name="plain-test", status="stopped")]
                prepare()
                response = self.call("GET", f"/api/vms/{VMID}/remove-preview")
                self.assertEqual(response.status_code, 200, response.json)
                self.assertFalse(response.json["eligible"])
                self.assertTrue(response.json["reasons"])
                self.assertIsNone(response.json["check"])
                self.assertFalse(self.delete_calls)

    def test_preview_error_and_observer_have_zero_destructive_calls(self):
        self.run.side_effect = lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 1, "", "offline")
        self.assertEqual(self.call("GET", f"/api/vms/{VMID}/remove-preview").status_code, 503)
        self.run.reset_mock()
        self.assertEqual(self.call("GET", f"/api/vms/{VMID}/remove-preview", token="observer").status_code, 403)
        self.assertEqual(self.run.call_count, 0)
        self.assertFalse(self.delete_calls)

    def test_remove_requires_exact_vmid_and_defaults_to_both_options_off(self):
        self.replication = [replication_job(1000)]
        self.pending.append({"key": "onboot", "value": "0", "delete": 0})
        check = self.preview()["check"]
        lock, module = self.fake_lock()
        with patch.dict(sys.modules, {"lxc_check_job": module}):
            for body in ({"check": check, "confirm_vmid": "99"}, {"check": check, "confirm_vmid": 100}):
                response = self.call("POST", f"/api/vms/{VMID}/remove", body)
                self.assertIn(response.status_code, (409, 422), response.json)
            self.assertFalse(self.delete_calls)
            response = self.confirm(check)
        self.assertEqual(response.status_code, 202, response.json)
        self.assertEqual(response.json, {"state": "running", "task": TASK})
        self.assertEqual(len(self.delete_calls), 1)
        self.assertEqual(self.delete_calls[0]["params"]["volume"], VOLUME)
        self.assertEqual(self.delete_calls[0]["params"]["purge"], 0)
        self.assertEqual(self.delete_calls[0]["params"]["destroy_unreferenced_disks"], 0)
        module.begin_removal.assert_called_once_with(lock, NODE, self.delete_calls[0]["params"]["operation"])
        lock.close.assert_called()

    def test_remove_rechecks_actual_replication_and_pending_rows_after_preview(self):
        cases = [
            ("ha", {"sid": "ct:100"}, "ha_managed"),
            ("replication", replication_job(VMID, disable=1), "replication_configured"),
            ("replication", replication_job(VMID, remove_job="local"), "replication_configured"),
            ("pending", {"key": "swap", "value": "512", "pending": "0"}, "pending_changes"),
            ("pending", {"key": "description", "pending": ""}, "pending_changes"),
            ("pending", {"key": "nameserver", "value": "192.0.2.1", "delete": 1}, "pending_changes"),
            ("pending", {"key": "searchdomain", "delete": 2}, "pending_changes"),
        ]
        for attr, row, reason in cases:
            with self.subTest(row=row):
                check = self.preview()["check"]
                rows = getattr(self, attr)
                rows.append(row)
                lock, module = self.fake_lock()
                try:
                    with patch.dict(sys.modules, {"lxc_check_job": module}):
                        response = self.call("POST", f"/api/vms/{VMID}/remove", {
                            "check": check, "confirm_vmid": str(VMID),
                        })
                    self.assertEqual(response.status_code, 409, response.json)
                    self.assertEqual(response.json["error"], "removal_blocked")
                    self.assertIn(reason, response.json["preview"]["reasons"])
                    module.begin_removal.assert_not_called()
                    lock.close.assert_called_once()
                    self.assertFalse(self.delete_calls)
                finally:
                    rows.pop()

    def test_unavailable_or_malformed_checks_block_removal_before_native_delete(self):
        paths = ["/cluster/replication", f"/nodes/{NODE}/lxc/{VMID}/pending"]
        cases = [
            (paths[0], subprocess.CompletedProcess([], 1, "", "replication configuration unavailable")),
            (paths[0], self.result([{"id": "100-0"}])),
            (paths[1], subprocess.CompletedProcess([], 1, "", "configuration unavailable")),
            (paths[1], self.result([{"key": "memory"}])),
            (paths[1], self.result([{"key": "memory", "value": "2048", "delete": None}])),
        ]
        for path, failure in cases:
            with self.subTest(path=path, output=failure.stdout):
                check = self.preview()["check"]
                lock, module = self.fake_lock()
                self.run.side_effect = lambda argv, **kwargs: (
                    failure if len(argv) > 2 and argv[2] == path else self.pvesh(argv, **kwargs)
                )
                try:
                    with patch.dict(sys.modules, {"lxc_check_job": module}):
                        response = self.call("POST", f"/api/vms/{VMID}/remove", {
                            "check": check, "confirm_vmid": str(VMID),
                        })
                    self.assertEqual(response.status_code, 503, response.json)
                    module.begin_removal.assert_not_called()
                    lock.close.assert_called_once()
                    self.assertFalse(self.delete_calls)
                finally:
                    self.run.side_effect = self.pvesh

    def test_changed_config_or_duplicate_submit_never_reaches_native_delete(self):
        check = self.preview()["check"]
        self.write_config("memory: 2048\n")
        _lock, module = self.fake_lock()
        with patch.dict(sys.modules, {"lxc_check_job": module}):
            changed = self.call("POST", f"/api/vms/{VMID}/remove", {
                "check": check, "confirm_vmid": "100",
            })
        self.assertEqual(changed.status_code, 409, changed.json)
        self.assertEqual(changed.json["error"], "target_changed")
        self.assertFalse(self.delete_calls)
        check = self.preview()["check"]
        _lock, busy = self.fake_lock()
        busy.acquire.side_effect = BlockingIOError
        with patch.dict(sys.modules, {"lxc_check_job": busy}):
            duplicate = self.call("POST", f"/api/vms/{VMID}/remove", {
                "check": check, "confirm_vmid": "100",
            })
        self.assertEqual(duplicate.status_code, 409, duplicate.json)
        self.assertFalse(self.delete_calls)

    def test_discarded_post_response_recovers_the_same_task_without_a_second_dispatch(self):
        self.dispatch_mode = "timeout_after_claim"
        check = self.preview()["check"]
        self.confirm(check)
        self.assertEqual(self.status(check).json, {"state": "running", "task": TASK})
        self.assertEqual(self.confirm(check, purge=True, destroy_unreferenced_disks=True).json,
                         {"state": "running", "task": TASK})
        different = self.preview()["check"]
        self.assertEqual(self.confirm(different).json["error"], "operation_pending")
        self.assertEqual(len(self.delete_calls), 1)
        self.assertEqual((self.delete_calls[0]["params"]["purge"],
                          self.delete_calls[0]["params"]["destroy_unreferenced_disks"]), (0, 0))

    def test_definite_rejection_unblocks_shared_lock_and_cannot_replay(self):
        self.dispatch_mode = "rejected"
        check = self.preview()["check"]
        self.assertEqual(self.confirm(check).json, {"state": "failed", "task": None, "reason": "not_started"})
        with lxc_check_job.acquire(VMID) as lock:
            self.assertEqual(lock.read(), "")
        self.assertEqual(self.confirm(check).json["reason"], "not_started")
        self.assertEqual(len(self.delete_calls), 1)

    def test_delayed_receipt_or_expired_dispatch_never_replays(self):
        self.dispatch_mode = "delayed"
        check = self.preview()["check"]
        self.assertEqual(self.confirm(check).json["reason"], "dispatch_pending")
        self.assertEqual(self.status(check).json["reason"], "dispatch_pending")
        marker = routes.receipts.DIRECTORY / self.delete_calls[0]["params"]["operation"]
        with self.assertRaises(BlockingIOError):
            lxc_check_job.acquire(VMID)
        os.utime(marker, (1, 1))
        self.assertEqual(self.status(check).json["reason"], "not_started")
        with lxc_check_job.acquire(VMID) as lock:
            self.assertEqual(lock.read(), "")
        self.assertEqual(self.confirm(check).json["reason"], "not_started")
        self.assertEqual(len(self.delete_calls), 1)

    def test_confirmation_expiring_during_recheck_never_dispatches(self):
        check = self.preview()["check"]
        claims = routes._ticket().loads(check)
        real_preflight = routes._preflight
        real_begin = routes.receipts.begin
        for phase in ("preflight", "reservation"):
            with self.subTest(phase=phase), patch.object(routes.time, "time", wraps=routes.time.time) as clock:
                before = claims["expires"] - 1
                after = claims["expires"]
                clock.return_value = before

                def preflight(vmid):
                    result = real_preflight(vmid)
                    if phase == "preflight":
                        clock.return_value = after
                    return result

                def begin(operation):
                    real_begin(operation)
                    if phase == "reservation":
                        clock.return_value = after

                with patch.object(routes, "_preflight", side_effect=preflight), patch.object(
                    routes.receipts, "begin", side_effect=begin,
                ):
                    self.assertEqual(self.confirm(check).json, {"error": "check_expired"})
                if phase == "reservation":
                    self.assertEqual(self.status(check).json["reason"], "not_started")
        self.assertFalse(self.delete_calls)

    def test_expired_status_seals_against_a_concurrent_confirmation(self):
        check = self.preview()["check"]
        claims = routes._ticket().loads(check)
        real_begin = routes.receipts.begin
        with patch.object(routes.time, "time", wraps=routes.time.time) as clock:
            clock.return_value = claims["expires"] - 1

            def expire_before_reserving(operation):
                self.assertEqual(operation, claims["operation"])
                clock.return_value = claims["expires"]
                with patch.object(routes.receipts, "begin", side_effect=real_begin):
                    self.assertEqual(self.status(check).json["reason"], "not_started")
                real_begin(operation)

            with patch.object(routes.receipts, "begin", side_effect=expire_before_reserving):
                self.assertEqual(self.confirm(check).json["reason"], "not_started")
        self.assertFalse(self.delete_calls)

    def test_task_result_requires_the_original_task_and_removal_of_the_exact_disk(self):
        self.assertEqual(self.status("forged").status_code, 409)
        self.run.assert_not_called()
        check = self.preview()["check"]
        self.assertEqual(self.status(check, token="observer").status_code, 403)
        self.assertEqual(self.confirm(check).json["task"], TASK)
        self.assertEqual(self.status(check).json["state"], "running")
        self.task_state = {"status": "stopped", "exitstatus": "OK"}
        warning = self.status(check).json
        self.assertEqual((warning["state"], warning["reason"]), ("warning", "vmid_still_present"))
        self.resources = []
        self.assertEqual(self.status(check).json["reason"], "configuration_still_present")
        (self.conf / f"{VMID}.conf").unlink()
        self.storage_content["local-lvm"][0]["content"] = "images"
        self.assertEqual(self.status(check).json["reason"], "root_volume_still_present")
        self.resources = [{"vmid": [VMID]}]
        self.assertEqual(self.status(check).json["state"], "unknown")
        self.resources = []
        original = self.pvesh
        self.run.side_effect = lambda argv, **kwargs: (
            self.result(None, 1) if argv == ["/usr/bin/perl", routes.NATIVE_BRIDGE] else original(argv, **kwargs)
        )
        try:
            self.assertEqual(self.status(check).json["state"], "unknown")
        finally:
            self.run.side_effect = original
        self.storage_content["local-lvm"] = []
        self.assertEqual(self.status(check).json["state"], "succeeded")
        routes._invalidate.assert_called_once_with(VMID)
        self.assertEqual(len(self.delete_calls), 1, "status reads never issue a second delete")

    def test_native_failure_warning_and_unknown_status_are_distinct(self):
        check = self.preview()["check"]
        self.confirm(check)
        for exitstatus, state in [
            ("destroy failed", "failed"), ("WARNINGS: 1", "warning"),
            ("unexpected status", "unknown"), ("unable to get last line from task log - IO", "unknown"),
        ]:
            with self.subTest(exitstatus=exitstatus):
                self.task_state = {"status": "stopped", "exitstatus": exitstatus}
                result = self.status(check).json
                self.assertEqual(result["state"], state)
                self.assertEqual(result["task"], TASK)
        with patch.object(self.run, "side_effect", lambda argv, **kwargs: self.result(None, 1)):
            self.assertEqual(self.status(check).json["state"], "unknown")
        self.task_state = {"status": ["stopped"], "exitstatus": "OK"}
        self.assertEqual(self.status(check).json["state"], "unknown")
        self.assertEqual(len(self.delete_calls), 1)

    def test_success_detaches_only_original_bindings_even_if_vmid_was_reused(self):
        binding = {"vmid": VMID, "guest_type": "lxc"}
        old_url = "https://example.test/original"
        _, old = custom_links.create({"name": "Original", "url": old_url, "binding": binding})
        old.pop("binding_revision")  # A link saved before this feature.
        _, rebound = custom_links.create({"name": "Rebound", "url": old_url, "binding": binding})
        _, qemu = custom_links.create({
            "name": "VM", "url": old_url, "binding": {**binding, "guest_type": "qemu"},
        })
        custom_links.save_all([old, rebound, qemu])

        check = self.preview()["check"]
        self.assertEqual(self.confirm(check).json["state"], "running")
        self.assertEqual(custom_links.load_all(), [old, rebound, qemu])
        new_url = "https://example.test/edited"
        self.assertTrue(custom_links.update(old["id"], {"url": new_url})[0])
        self.write_generation(5)
        self.assertTrue(custom_links.update(rebound["id"], {"binding": binding})[0])
        _, new = custom_links.create({"name": "Replacement", "url": old_url, "binding": binding})
        self.task_state = {"status": "stopped", "exitstatus": "OK"}

        routes.reconcile_link_detachments(VMID)
        stored = {entry["id"]: entry for entry in custom_links.load_all()}
        self.assertIsNone(stored[old["id"]]["binding"])
        self.assertEqual(stored[old["id"]]["url"], new_url)
        self.assertEqual(stored[qemu["id"]], qemu)
        self.assertEqual(stored[new["id"]], new)
        self.assertEqual(stored[rebound["id"]]["binding"], binding)
        self.assertEqual(self.status(check).json["reason"], "vmid_still_present")
        self.assertEqual(list(routes.receipts.pending_link_detachments()), [])
        self.assertEqual(len(self.delete_calls), 1)

    def test_unconfirmed_or_failed_destroy_leaves_links_bound(self):
        _, original = custom_links.create({
            "name": "Original", "url": "https://example.test/original",
            "binding": {"vmid": VMID, "guest_type": "lxc"},
        })
        check = self.preview()["check"]
        self.assertEqual(list(routes.receipts.pending_link_detachments()), [])

        self.confirm(check)
        self.task_state = {"status": "stopped", "exitstatus": "unexpected status"}
        self.assertEqual(self.status(check).json["state"], "unknown")
        self.assertEqual(custom_links.load_all(), [original])
        self.task_state["exitstatus"] = "destroy failed"
        self.assertEqual(self.status(check).json["state"], "failed")
        self.assertEqual(custom_links.load_all(), [original])
        self.assertEqual(list(routes.receipts.pending_link_detachments()), [])

    def test_warning_retries_link_detachment_until_guest_absence_is_verifiable(self):
        _, original = custom_links.create({
            "name": "Original", "url": "https://example.test/original",
            "binding": {"vmid": VMID, "guest_type": "lxc"},
        })
        check = self.preview()["check"]
        self.confirm(check)
        self.task_state = {"status": "stopped", "exitstatus": "WARNINGS: 1"}
        self.assertEqual(self.status(check).json["state"], "warning")
        self.assertEqual(custom_links.load_all(), [original])
        self.assertEqual(len(list(routes.receipts.pending_link_detachments())), 1)
        self.resources = []
        self.assertEqual(self.status(check).json["state"], "warning")
        self.assertEqual(custom_links.load_all(), [original])
        (self.conf / f"{VMID}.conf").unlink()
        routes.reconcile_link_detachments(VMID)
        self.assertEqual(self.status(check).json["state"], "warning")
        self.assertEqual(custom_links.load_all()[0]["url"], original["url"])
        self.assertIsNone(custom_links.load_all()[0]["binding"])
        self.assertEqual(list(routes.receipts.pending_link_detachments()), [])

    def test_reused_vmid_with_identical_config_cannot_use_old_confirmation(self):
        check = self.preview()["check"]
        original = self.conf / f"{VMID}.conf"
        replacement = self.conf / "replacement"
        replacement.write_bytes(original.read_bytes())
        os.replace(replacement, original)
        self.write_generation(5)
        self.assertEqual(self.confirm(check).json["error"], "target_changed")
        self.assertEqual(self.delete_calls, [])

    def test_foreign_missing_or_malformed_root_volume_blocks_the_request(self):
        check = self.preview()["check"]
        for rows in (
            [{"volid": "local-lvm:subvol-200-disk-0", "vmid": 200, "content": "rootdir"}],
            [],
            [{"volid": VOLUME, "vmid": 200, "content": "rootdir"}],
        ):
            with self.subTest(rows=rows):
                self.storage_content["local-lvm"] = rows
                self.assertIn(self.confirm(check).status_code, (409, 503))
                self.assertEqual(self.delete_calls, [])
        path = self.conf / f"{VMID}.conf"
        path.write_text(path.read_text().replace("subvol-100", "subvol-200"))
        self.assertIn(self.confirm(self.preview()["check"]).status_code, (409, 503))
        self.assertFalse(self.delete_calls)

    def test_standard_removal_never_checks_archives_or_waits_for_backup_servers(self):
        original = self.pvesh
        with patch.object(self.run, "side_effect", lambda argv, **kwargs:
                          self.result(None, 1) if len(argv) > 2 and argv[2] == "/storage" else original(argv, **kwargs)):
            self.assertEqual(self.confirm(self.preview()["check"]).json["task"], TASK)
        commands = [call.args[0] for call in self.run.call_args_list]
        self.assertFalse(any(len(cmd) > 2 and (cmd[2] == "/storage" or "backup" in cmd) for cmd in commands))
        self.assertEqual(len(self.delete_calls), 1)

    def test_native_options_are_independent_and_strictly_boolean(self):
        check = self.preview()["check"]
        for invalid in ({"purge": 1}, {"destroy_unreferenced_disks": "true"}, {"force": True}):
            self.assertEqual(self.confirm(check, **invalid).status_code, 400)
        self.assertFalse(self.delete_calls)
        for purge, destroy in ((False, True), (True, False), (True, True)):
            with self.subTest(purge=purge, destroy=destroy):
                _lock, module = self.fake_lock()
                with patch.dict(sys.modules, {"lxc_check_job": module}):
                    result = self.confirm(self.preview()["check"], purge=purge, destroy_unreferenced_disks=destroy)
                self.assertEqual(result.json["task"], TASK)
                params = self.delete_calls[-1]["params"]
                self.assertEqual((params["purge"], params["destroy_unreferenced_disks"]), (int(purge), int(destroy)))
        self.assertEqual(len(self.delete_calls), 3)

    def test_only_purge_allows_native_removal_from_ha_and_replication_jobs(self):
        self.ha = [{"sid": "ct:100"}]
        self.replication = [replication_job(VMID)]
        check = self.preview()["check"]
        self.assertEqual(self.confirm(check, destroy_unreferenced_disks=True).json["preview"]["reasons"],
                         ["ha_managed", "replication_configured"])
        self.assertFalse(self.delete_calls)
        self.assertEqual(self.confirm(check, purge=True).json["task"], TASK)
        self.assertEqual(self.delete_calls[0]["params"]["purge"], 1)

    def test_native_options_do_not_bypass_a_new_backup_lock(self):
        check = self.preview()["check"]
        self.write_config("lock: backup\n")
        response = self.confirm(check, purge=True, destroy_unreferenced_disks=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn("container_locked", response.json["preview"]["reasons"])
        self.assertFalse(self.delete_calls)

    def test_appimage_stages_both_route_and_native_dependencies(self):
        appdir = self.root / "AppDir"
        bin_dir = appdir / "usr/bin"
        bin_dir.mkdir(parents=True)
        source = (SCRIPTS / "build_appimage.sh").read_text()
        copy_block = source.split("# Copy Flask server\n", 1)[1].split(
            'cp "$SCRIPT_DIR/ovs_topology.py"', 1
        )[0]
        subprocess.run(["bash", "-ec", copy_block], check=True, capture_output=True, env={
            **os.environ, "SCRIPT_DIR": str(SCRIPTS), "APP_DIR": str(appdir),
        })
        for name in ("flask_server.py", "flask_lxc_removal_routes.py", "lxc_removal_receipts.py",
                     "plain_lxc_pve.pl", "PlainLxcRemoval.pm", "oci_instance_info.py", "oci_console_logs.py"):
            self.assertTrue((bin_dir / name).is_file(), name)
        for name in ("plain_lxc_pve.pl", "PlainLxcRemoval.pm"):
            subprocess.run(["perl", "-c", str(bin_dir / name)], check=True, capture_output=True)

    def test_native_worker_rechecks_under_lock_and_cannot_mutate_after_losing_receipt_claim(self):
        check = routes._ticket().loads(self.preview()["check"])
        module = SCRIPTS.parents[1] / "scripts/lxc/PlainLxcRemoval.pm"
        fixture = Path(__file__).with_name("lxc_removal_worker_fixture.pl")
        for scenario, expect_calls, expected_receipt in [
            ("success", 1, TASK),
            ("generation_changed", 0, TASK),
            ("foreign_disk", 0, TASK),
            ("template_changed", 0, TASK),
            ("storage_changed", 0, TASK),
            ("oci_started", 0, TASK),
            ("oci_lock_busy", 0, TASK),
            ("sealed", 0, routes.receipts.REJECTED),
        ]:
            with self.subTest(scenario=scenario):
                self.write_generation(4)
                oci_root = self.root / scenario
                oci_root.mkdir()
                current = dict(check, operation=routes.uuid4().hex, purge=1, destroy_unreferenced_disks=1)
                reservation = routes.receipts.begin(current["operation"])
                if scenario == "sealed":
                    routes.receipts.seal_unstarted(current["operation"])
                request = {
                    "args": {key: current[key] for key in (
                        "guard", "operation", "vmid", "volume", "purge", "destroy_unreferenced_disks",
                    )},
                    "cfs": str(self.root), "config": str(self.conf / f"{VMID}.conf"),
                    "receipts": str(routes.receipts.DIRECTORY), "scenario": scenario, "task": TASK,
                    "oci_root": str(oci_root), "oci_checker": str(SCRIPTS / "oci_instance_info.py"),
                }
                run = subprocess.run(["perl", str(fixture), str(module)], text=True, check=True,
                                     input=json.dumps(request), capture_output=True)
                result = json.loads(run.stdout)
                self.assertEqual(result["returned_upid"], TASK)
                self.assertEqual(result["before_worker"], 0, "async submit must return before effects")
                self.assertEqual(result["native_calls"], expect_calls)
                self.assertEqual(result["nested_calls"], expect_calls)
                self.assertEqual(result["options"], {"purge": 1, "destroy-unreferenced-disks": 1})
                self.assertEqual((reservation / "result").read_text().strip(), expected_receipt)

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
