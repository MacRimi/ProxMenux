"""The Monitor routes use the real console engine with a fake Proxmox node."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask
from itsdangerous import TimestampSigner

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parents[1]
sys.path[:0] = [str(SCRIPTS), str(ROOT / ".github/scripts/tests")]

import flask_plain_lxc_routes as routes
import jwt_middleware
from test_plain_lxc import FakePVE, LxcError, NAME, NODE, Operations, PASSWORD, VMID, VOLUME, execute


class PlainLxcMonitorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)
        self.api = FakePVE(path)
        self.store = Operations(path / "state", os.getuid())
        self.calls = []
        self.mode = "password"
        self.users = {
            "admin-fixture": "admin", "other-fixture": "admin", "observer-fixture": "observer",
            "pve-admin-fixture": "admin", "oidc-admin-fixture": "admin",
        }
        self.enterContext(patch.object(jwt_middleware, "load_auth_config", return_value={}))
        self.enterContext(patch.object(jwt_middleware, "access_mode", side_effect=lambda _: self.mode))
        self.enterContext(patch.object(jwt_middleware, "verify_token_full", side_effect=self.token))
        self.enterContext(patch.object(jwt_middleware, "profile_for", side_effect=self.profile))
        self.enterContext(patch.object(routes, "_get_jwt_secret", return_value="fixture-only-signing-key"))
        self.pbs = False
        self.enterContext(patch.object(routes, "is_pbs_host", side_effect=lambda: self.pbs))
        self.enterContext(patch.object(routes, "subprocess", SimpleNamespace(
            run=self.run_engine, PIPE=subprocess.PIPE, DEVNULL=subprocess.DEVNULL,
            TimeoutExpired=subprocess.TimeoutExpired,
        )))
        app = Flask(__name__)
        app.testing = True
        app.register_blueprint(routes.plain_lxc_bp)
        self.client = app.test_client()
        self.spec = {
            "node": NODE, "vmid": VMID, "hostname": "Test-LXC", "template": {"volume_id": VOLUME},
            "access": {"mode": "password"}, "rootfs": {"storage": "local-lvm"}, "network": None,
        }

    def profile(self, mode, username=None, _scope=None):
        if mode == "open":
            return "admin"
        if mode == "read_only":
            return "observer"
        return self.users.get(username)

    def token(self, token):
        return (token, "full_admin") if token in self.users else (None, None)

    def run_engine(self, command, **kwargs):
        self.assertEqual(command, ["/usr/bin/python3", "-I", "-B", routes.ENGINE])
        body = json.loads(kwargs["input"])
        self.assertEqual(body["schema_version"], 2)
        self.calls.append(body)
        try:
            envelope = {"ok": True, "data": execute(body, self.api, self.store, wait_seconds=0)}
        except LxcError as error:
            envelope = {"ok": False, "error": error.code, "field": error.field}
        return subprocess.CompletedProcess(command, 0 if envelope["ok"] else 1, json.dumps(envelope).encode())

    def request(self, endpoint, *, data=None, token="admin-fixture", receipt=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        if receipt is not None:
            headers["X-ProxMenux-LXC-Receipt"] = receipt
        return self.client.open("/api/plain-lxc/v1/" + endpoint, method="GET" if data is None else "POST",
                                json=data, headers=headers)

    def checked(self):
        response = self.request("plan", data={"spec": self.spec})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def confirm(self, checked, **changes):
        return {"check": checked["check"], "confirmed": True, "password": PASSWORD,
                "accepted_warnings": checked["warnings"], **changes}

    ROUTES = [("context", None), ("plan", {}), ("create", {}), ("status", None), ("log?phase=create", None),
              ("download/plan", {}), ("download", {})]

    def test_every_route_rejects_unsigned_or_observer_before_running_the_engine(self):
        for mode, token, expected in [("read_only", None, 403), ("password", None, 401),
                                      ("proxmox", None, 401), ("password", "observer-fixture", 403)]:
            self.mode = mode
            with self.subTest(mode=mode, token=token):
                for endpoint, data in self.ROUTES:
                    self.assertEqual(self.request(endpoint, data=data, token=token).status_code, expected)
        self.assertEqual(self.calls, [])

    def test_a_backup_server_offers_no_route_before_running_the_engine(self):
        self.pbs = True
        for endpoint, data in self.ROUTES:
            self.assertEqual(self.request(endpoint, data=data).status_code, 404)
        self.mode = "password"
        self.assertEqual(self.request("context", token="observer-fixture").status_code, 403)
        self.assertEqual(self.calls, [])

    def test_an_open_monitor_creates_and_its_receipts_stay_with_open_access(self):
        self.mode = "open"
        self.assertEqual(self.request("context", token=None).status_code, 200)
        checked = self.request("plan", data={"spec": self.spec}, token=None).json
        created = self.request("create", data=self.confirm(checked), token=None)
        self.assertEqual((created.status_code, created.json["status"]), (200, "succeeded"))
        self.assertEqual(self.request("status", receipt=checked["receipt"], token=None).json, created.json)
        self.mode = "password"
        self.assertEqual(self.request("status", receipt=checked["receipt"]).status_code, 403)
        self.assertEqual([action for action, _ in self.api.writes], ["create"])

    def test_mount_points_and_hardware_reach_the_plan_as_the_console_sends_them(self):
        context = self.request("context").json
        self.assertGreater(context["capabilities"]["mount_points"], 0)
        self.assertIsInstance(context["hardware"], list)
        self.assertIs(context["hardware_errors"], False)
        self.spec["mounts"] = [{"type": "volume", "storage": "local-lvm", "size_gib": 4, "path": "/data",
                                "read_only": False, "backup": True}]
        self.spec["hardware"] = []
        checked = self.checked()
        self.assertEqual(checked["summary"]["mounts"][0]["path"], "/data")
        self.assertEqual(checked["summary"]["hardware"], [])
        self.spec["hardware"] = [{"profile": "usb", "selection_id": "not-on-this-host"}]
        self.assertEqual(self.request("plan", data={"spec": self.spec}).json["error"], "resource_unavailable")
        self.assertEqual(self.api.writes, [])

    def test_context_and_planning_admit_only_downloaded_official_system_templates(self):
        response = self.request("context")
        self.assertEqual(response.json["templates"], [VOLUME])
        self.assertEqual(response.json["storages"], ["local-lvm"])
        self.assertEqual(response.json["catalog"], [NAME])
        self.assertEqual(response.json["template_storages"], ["local"])
        self.spec["template"]["volume_id"] = "local:vztmpl/custom.tar.zst"
        self.assertEqual(self.request("plan", data={"spec": self.spec}).json["error"], "template_unverified")
        self.spec["node"] = "another-node"
        self.assertEqual(self.request("plan", data={"spec": self.spec}).json["error"], "node_not_local")
        self.assertEqual([call["action"] for call in self.calls], ["context"] * 3)
        self.assertFalse(self.api.writes)

    def download_selection(self, **changes):
        return {"node": NODE, "catalog_id": NAME, "template_storage": "local", **changes}

    def test_signed_in_proxmox_and_oidc_admins_can_prepare_a_download(self):
        for mode, token in (("proxmox", "pve-admin-fixture"), ("password", "oidc-admin-fixture")):
            self.mode = mode
            self.assertEqual(self.request("context", token=token).status_code, 200)
            response = self.request("download/plan", data=self.download_selection(), token=token)
            self.assertEqual(response.status_code, 200, response.json)
        self.assertFalse(self.api.writes)

    def test_download_rejects_wrong_node_storage_and_sources(self):
        for changes in ({"node": "other-node"}, {"template_storage": "local-lvm"}, {"catalog_id": "custom.tar.zst"}):
            with self.subTest(changes=changes):
                response = self.request("download/plan", data=self.download_selection(**changes))
                self.assertEqual(response.status_code, 422)
        checked = self.request("download/plan", data=self.download_selection()).json
        self.api.catalog.update(
            source="https://releases.turnkeylinux.org/pve",
            location=f"https://releases.turnkeylinux.org/pve/{NAME}",
        )
        self.assertEqual(self.request("context").json["catalog"], [])
        response = self.request("download", data={"check": checked["check"], "confirmed": True})
        self.assertEqual((response.status_code, response.json["error"]), (422, "template_unverified"))
        self.assertNotIn("download_template", [call["action"] for call in self.calls])
        self.assertFalse(self.api.writes)

    def test_download_requires_its_own_fresh_confirmation_and_account(self):
        self.api.present = False
        checked = self.request("download/plan", data=self.download_selection()).json
        payload = {"check": checked["check"], "confirmed": True}
        self.assertEqual(self.request("download", data={**payload, "confirmed": False}).status_code, 422)
        self.assertEqual(self.request("download", data={**payload, "check": "forged"}).status_code, 409)
        self.assertEqual(self.request("download", data=payload, token="other-fixture").status_code, 409)
        self.assertEqual(self.request("create", data=payload).status_code, 409)
        self.assertEqual(self.request("status", receipt=checked["receipt"], token="other-fixture").status_code, 403)
        with patch.object(TimestampSigner, "get_timestamp", return_value=int(time.time()) - routes.PLAN_AGE - 1):
            old = self.request("download/plan", data=self.download_selection()).json
        self.assertEqual(self.request("download", data={**payload, "check": old["check"]}).status_code, 409)
        status = self.request("status", receipt=old["receipt"]).json
        self.assertEqual((status["action"], status["phase"], status["status"]), ("download_template", "download", "awaiting"))
        self.assertFalse(self.api.writes)

    def test_download_to_create_uses_verified_volume_and_stable_receipts(self):
        self.api.present = False
        self.assertEqual(self.request("context").json["templates"], [])
        checked = self.request("download/plan", data=self.download_selection()).json
        payload = {"check": checked["check"], "confirmed": True}
        self.api.task_running = True
        first = self.request("download", data=payload)
        self.assertEqual(first.status_code, 200, first.json)
        self.assertEqual(first.json["status"], "running")
        self.assertEqual(self.request("download", data=payload).json, first.json)
        self.api.task_running = False
        for task in self.api.tasks.values():
            task.update(status="stopped", exitstatus="OK")
        final = self.request("status", receipt=checked["receipt"])
        self.assertEqual((final.json["status"], final.json["volume_id"]), ("succeeded", VOLUME))
        self.assertEqual(self.request("context").json["templates"], [VOLUME])
        created = self.request("create", data=self.confirm(self.checked()))
        self.assertEqual(created.json["status"], "succeeded")
        self.assertEqual([action for action, _params in self.api.writes], ["download_template", "create"])
        self.assertEqual(self.api.boot_attempts, 0)

    def test_download_with_wrong_checksum_has_no_successful_result(self):
        self.api.present = False
        self.api.file.write_bytes(b"corrupt fixture")
        checked = self.request("download/plan", data=self.download_selection()).json
        response = self.request("download", data={"check": checked["check"], "confirmed": True})
        self.assertEqual((response.json["status"], response.json["reason"]), ("partial", "template_checksum_mismatch"))
        self.assertEqual(self.request("status", receipt=checked["receipt"]).json, response.json)
        self.assertEqual([action for action, _params in self.api.writes], ["download_template"])

    def test_unconfirmed_changed_or_foreign_plans_have_no_create_effect(self):
        checked = self.checked()
        self.assertEqual(self.request("create", data=self.confirm(checked, confirmed=False)).status_code, 422)
        self.assertEqual(self.request("create", data=self.confirm(checked, accepted_warnings=[])).status_code, 422)
        self.assertEqual(self.request("create", data=self.confirm(checked, check="changed")).status_code, 409)
        self.assertEqual(self.request("create", data=self.confirm(checked), token="other-fixture").status_code, 409)
        self.assertEqual(self.request("status", receipt=checked["receipt"], token="other-fixture").status_code, 403)
        self.assertNotIn("create", [call["action"] for call in self.calls])
        self.assertNotIn("status", [call["action"] for call in self.calls])
        self.assertFalse(self.api.writes)

    def test_create_and_status_use_original_operation_without_duplicate_writes(self):
        checked = self.checked()
        self.assertEqual(checked["summary"]["hostname"], "test-lxc")
        self.assertIsNone(checked["summary"]["network"])
        self.assertEqual(self.request("status", receipt=checked["receipt"]).json["status"], "awaiting")
        created = self.request("create", data=self.confirm(checked))
        self.assertEqual(created.status_code, 200, created.json)
        self.assertEqual(created.json["status"], "succeeded")
        self.assertEqual(self.request("status", receipt=checked["receipt"]).json, created.json)
        self.assertEqual(self.request("create", data=self.confirm(checked)).json, created.json)
        self.assertEqual([action for action, _ in self.api.writes], ["create"])
        self.assertEqual(self.api.boot_attempts, 0)
        self.assertEqual([call["action"] for call in self.calls if "secret" in call], ["create", "create"])
        self.assertNotIn(PASSWORD, self.store.path.read_bytes().decode(errors="replace"))
        self.assertNotIn(PASSWORD, json.dumps(checked))

    def test_progress_names_each_task_and_its_log_follows_the_receipt(self):
        self.spec.update(start_after_create=True)
        checked = self.checked()
        awaiting = self.request("status", receipt=checked["receipt"]).json
        self.assertEqual((awaiting["steps"], awaiting["warned"]), (["create"], []))
        self.assertEqual(self.request("log?phase=create", receipt=checked["receipt"]).status_code, 404)
        created = self.request("create", data=self.confirm(checked)).json
        self.assertEqual((created["status"], created["steps"], created["preparing"], created["warned"]),
                         ("succeeded", ["create", "start"], False, []))
        self.assertEqual(created["warning_lines"], {})
        create = next(task for task in self.api.tasks if ":vzcreate:" in task)
        self.api.logs[create] = ["extracting archive"] * 50 + ["TASK OK"]
        first = self.request("log?phase=create", receipt=checked["receipt"])
        self.assertEqual((first.status_code, len(first.json["lines"]), first.json["next_offset"]), (200, 50, 50))
        last = self.request("log?phase=create&offset=50", receipt=checked["receipt"]).json
        self.assertEqual(last, {"lines": ["TASK OK"], "next_offset": None})
        for query in ("log", "log?phase=download", "log?phase=create&offset=-1", "log?phase=create&offset=%C2%B2"):
            self.assertEqual(self.request(query, receipt=checked["receipt"]).status_code, 422, query)
        self.assertEqual(self.request("log?phase=create", receipt=checked["receipt"], token="other-fixture").status_code, 403)
        self.assertEqual(self.request("log?phase=create", receipt="forged").status_code, 403)

    def test_changed_archive_cannot_reach_create_side_effect(self):
        checked = self.checked()
        self.api.file.write_bytes(b"different sample archive")
        response = self.request("create", data=self.confirm(checked))
        self.assertEqual((response.status_code, response.json["error"]), (422, "template_checksum_mismatch"))
        self.assertFalse(self.api.writes)

    def test_password_rules_are_enforced_by_the_shared_engine(self):
        checked = self.checked()
        response = self.request("create", data=self.confirm(checked, password="bad\npassword"))
        self.assertEqual((response.status_code, response.json["field"]), (422, "secret.password"))
        self.assertEqual(self.calls[-1]["action"], "create")
        self.assertFalse(self.api.writes)

    def test_expired_confirmation_leaves_receipt_usable_for_observation(self):
        now = int(time.time())
        with patch.object(TimestampSigner, "get_timestamp", return_value=now - routes.PLAN_AGE - 1):
            checked = self.checked()
        self.assertEqual(self.request("create", data=self.confirm(checked)).status_code, 409)
        self.assertEqual(self.request("status", receipt=checked["receipt"]).json["status"], "awaiting")
        self.assertFalse(self.api.writes)

    def test_old_receipt_without_admission_can_be_dismissed(self):
        now = int(time.time())
        with patch.object(TimestampSigner, "get_timestamp", return_value=now - routes.PLAN_AGE - routes.CREATE_TIMEOUT - 1):
            checked = self.checked()
        self.assertEqual(self.request("status", receipt=checked["receipt"]).json["status"], "not_submitted")
        self.assertFalse(self.api.writes)
