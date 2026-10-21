"""PBS localization metadata must preserve routes, security and persistence."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
from flask import Flask

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "AppImage/scripts"))
import auth_manager
import pbs_manager as pbs
REAL_REMOTE_REQUEST = pbs._remote_request


class PBSI18nTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for patch in [mock.patch.multiple(auth_manager, CONFIG_DIR=self.root, AUTH_CONFIG_FILE=self.root / "auth.json"),
                      mock.patch.object(pbs, "_remote_get", return_value=[]),
                      mock.patch.object(pbs, "_remote_request"),
                      mock.patch.object(pbs, "local_available", return_value=False)]:
            patch.start(); self.addCleanup(patch.stop)
        (self.root / "auth.json").write_text(json.dumps({"enabled": True, "password_hash": "fixture"}))
        self.server = {"name": "Fixture", "url": "https://pbs.invalid:8007", "token_id": "audit@pbs!monitor", "token_secret": "fake-fixture-secret", "fingerprint": ""}
        self.id = pbs.save_server(self.server)
        pbs._remote_get.reset_mock(); pbs._status_cache.clear()
        auth = types.SimpleNamespace(load_auth_config=auth_manager.load_auth_config, verify_token=lambda _: "fixture",
            verify_token_full=lambda token: ("fixture", "full_admin" if token == "admin" else "read_only"))
        spec = importlib.util.spec_from_file_location("fixture_pbs_jwt", ROOT / "AppImage/scripts/jwt_middleware.py")
        middleware = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"auth_manager": auth}): spec.loader.exec_module(middleware)
        spec = importlib.util.spec_from_file_location("fixture_pbs_routes", ROOT / "AppImage/scripts/flask_pbs_routes.py")
        routes = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"jwt_middleware": middleware}): spec.loader.exec_module(routes)
        app = Flask(__name__); app.register_blueprint(routes.pbs_bp); self.client = app.test_client()

    def send(self, method="POST", path="/api/pbs/servers", data=None, role="admin"):
        return self.client.open(path, method=method, json=data, headers={"Authorization": "Bearer " + role} if role else {})

    def reject(self, data, message, code, path="/api/pbs/servers"):
        before = (self.root / "pbs_servers.json").read_bytes()
        with mock.patch.object(pbs, "_save_servers") as save:
            response = self.send(path=path, data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json, {"error": message, "code": code})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        save.assert_not_called(); pbs._remote_get.assert_not_called(); pbs._remote_request.assert_not_called()
        self.assertEqual((self.root / "pbs_servers.json").read_bytes(), before)

    def test_invalid_input_is_localizable_before_any_remote_or_save_effect(self):
        cases = [
            (None, "Invalid PBS server configuration.", "pbs_invalid_config"),
            ({**self.server, "name": []}, "Invalid PBS connection field.", "pbs_invalid_field"),
            ({**self.server, "url": "http://pbs.invalid"}, "Use an HTTPS PBS URL without embedded credentials, query or fragment.", "pbs_invalid_url"),
            ({**self.server, "name": ""}, "A server name of at most 128 characters is required.", "pbs_name_required"),
            ({**self.server, "token_id": "bad"}, "Enter a PBS API token ID in user@realm!token format.", "pbs_token_id_format"),
            ({**self.server, "token_secret": "bad\nsecret"}, "A valid API token secret is required.", "pbs_token_secret"),
            ({**self.server, "token_id": "človek@pbs!monitor"}, "Invalid API token ID.", "pbs_invalid_token_id"),
            ({**self.server, "fingerprint": "invalid"}, "The certificate fingerprint must be SHA256 (64 hex characters).", "pbs_invalid_fingerprint"),
            ({**self.server, "id": "../../bad"}, "Invalid PBS server ID.", "pbs_invalid_id"),
        ]
        for data, message, code in cases:
            with self.subTest(code=code): self.reject(data, message, code)
        for data, message, code in [
            ({**self.server, "username": "missing-realm", "password": "fake"}, "Enter the PBS user as user@realm, for example root@pam.", "pbs_username"),
            ({**self.server, "username": "root@pam", "password": ""}, "Enter the password of the PBS user.", "pbs_password"),
        ]:
            with self.subTest(code=code): self.reject(data, message, code, "/api/pbs/servers/login")

    def test_authentication_and_scope_guards_precede_all_mutations(self):
        before = (self.root / "pbs_servers.json").read_bytes()
        save_patch = mock.patch.object(pbs, "_save_servers")
        save = save_patch.start(); self.addCleanup(save_patch.stop)
        for path, method in [("/api/pbs/servers", "POST"), ("/api/pbs/servers/login", "POST"), ("/api/pbs/servers/" + self.id, "DELETE")]:
            for role, status in [(None, 401), ("reader", 403)]:
                self.assertEqual(self.send(method, path, self.server, role).status_code, status)
        (self.root / "auth.json").write_text(json.dumps({"enabled": False}))
        for path in ("/api/pbs/servers", "/api/pbs/servers/login"):
            response = self.send(path=path, data=self.server)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json, {"error": "Enable local authentication before saving remote PBS credentials.", "code": "pbs_auth_required"})
        response = self.send("DELETE", "/api/pbs/servers/" + self.id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["code"], "pbs_auth_required")
        pbs._remote_get.assert_not_called(); pbs._remote_request.assert_not_called()
        save.assert_not_called()
        self.assertEqual((self.root / "pbs_servers.json").read_bytes(), before)

    def test_corrupt_configuration_missing_server_and_local_unavailable_keep_status(self):
        response = self.send("DELETE", "/api/pbs/servers/absent")
        self.assertEqual((response.status_code, response.json), (400, {"error": "PBS server not found.", "code": "pbs_not_found"}))
        for identifier, code in [("absent", "pbs_not_found"), ("local", "pbs_local_unavailable")]:
            response = self.send("GET", "/api/pbs/status?server=" + identifier)
            self.assertEqual(response.status_code, 502); self.assertEqual(response.json["code"], code)
        (self.root / "pbs_servers.json").write_text("invalid json")
        response = self.send("GET", "/api/pbs/servers")
        self.assertEqual((response.status_code, response.json), (500, {"error": "Could not read the PBS server configuration.", "code": "pbs_config_read"}))
        pbs._remote_get.assert_not_called(); pbs._remote_request.assert_not_called()

    def test_save_delete_failures_leave_previous_bytes_and_do_not_leak_details(self):
        for path, method, data, code, message in [
            ("/api/pbs/servers", "POST", {**self.server, "id": self.id}, "pbs_save_failed", "Could not save PBS connection."),
            ("/api/pbs/servers/" + self.id, "DELETE", None, "pbs_remove_failed", "Could not remove PBS connection."),
        ]:
            before = (self.root / "pbs_servers.json").read_bytes()
            with self.subTest(method=method), mock.patch.object(pbs.os, "replace", side_effect=OSError("private filesystem detail")):
                response = self.send(method, path, data)
            self.assertEqual((response.status_code, response.json), (500, {"error": message, "code": code}))
            self.assertEqual((self.root / "pbs_servers.json").read_bytes(), before)

    def test_partial_status_preserves_legacy_error_null_and_cache_with_additive_metadata(self):
        def remote(server, endpoint):
            if endpoint == "/version": return {"version": "4.2.5"}
            if endpoint == "/admin/verify": raise pbs.PBSError("Fixture access denied", code="pbs_token_rejected")
            if endpoint == "/admin/prune": return {"invalid": "list"}
            return []
        with mock.patch.object(pbs, "_remote_get", side_effect=remote) as remote_call:
            result = self.send("GET", "/api/pbs/status?server=" + self.id)
            count = remote_call.call_count
            self.assertEqual(self.send("GET", "/api/pbs/status?server=" + self.id).json, result.json)
            self.assertEqual(remote_call.call_count, count)
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json["verify"]); self.assertIsNone(result.json["prune"])
        self.assertEqual(result.json["sync"], [])
        self.assertEqual(result.json["errors"]["verify"], "Fixture access denied")
        self.assertEqual(result.json["error_details"]["verify"], {"code": "pbs_token_rejected"})
        self.assertEqual(result.json["error_details"]["prune"], {"code": "pbs_invalid_list"})

    def test_local_datastore_errors_and_command_errors_keep_legacy_messages(self):
        with mock.patch.object(pbs, "_cli", return_value=[{"name": "offline", "path": "/fixture", "backing-device": "fixture"}]), \
                mock.patch.object(pbs.os.path, "ismount", return_value=False), mock.patch.object(pbs.shutil, "disk_usage") as usage:
            store = pbs._local_datastores()[0]
        self.assertEqual(store["error"], "Datastore is offline, in maintenance or has no mounted backing device.")
        self.assertEqual(store["error_code"], "pbs_datastore_offline"); usage.assert_not_called(); self.assertIsNone(store["total"])
        with mock.patch.object(pbs.subprocess, "run", side_effect=OSError("fixture")):
            for fn, args in [(pbs._cli, ("task", "list")), (pbs._local_api, ("/admin/sync",))]:
                with self.subTest(args=args), self.assertRaises(pbs.PBSError) as caught: fn(*args)
                self.assertEqual(caught.exception.code, "pbs_read_failed")
                self.assertIn("Check its service and permissions.", str(caught.exception))

    def test_remote_failure_codes_follow_the_actual_request_and_keep_english(self):
        cases = [
            (401, b'{}', "pbs_token_rejected", "PBS rejected the API token or its permissions. Check both the user and token ACLs."),
            (302, b'{}', "pbs_invalid_response", "PBS returned an invalid response. Redirects are not followed."),
            (200, b'{}', "pbs_invalid_json", "PBS returned an invalid JSON document."),
            (200, b'invalid-json', "pbs_connect_failed", "Could not connect to PBS over verified HTTPS. Check the address, certificate and service."),
        ]
        for status, body, code, message in cases:
            connection = mock.Mock(); connection.getresponse.return_value.status = status
            connection.getresponse.return_value.read.return_value = body
            with self.subTest(code=code), mock.patch.object(pbs.http.client, "HTTPSConnection", return_value=connection), \
                    self.assertRaises(pbs.PBSError) as caught:
                REAL_REMOTE_REQUEST(self.server, "GET", "/version", {})
            self.assertEqual((str(caught.exception), caught.exception.problem()), (message, {"code": code}))
            connection.close.assert_called_once()
        for code in ("pbs_login_rejected", "pbs_token_create_denied", "pbs_audit_role_denied"):
            connection = mock.Mock(); connection.getresponse.return_value.status = 403
            connection.getresponse.return_value.read.return_value = b'{}'
            with self.subTest(code=code), mock.patch.object(pbs.http.client, "HTTPSConnection", return_value=connection), self.assertRaises(pbs.PBSError) as caught:
                REAL_REMOTE_REQUEST(self.server, "POST", "/access/ticket", {}, rejected="Original context", rejected_code=code)
            self.assertEqual((str(caught.exception), caught.exception.code), ("Original context", code))

    def test_connection_limit_and_invalid_datastore_response_do_not_save(self):
        before = (self.root / "pbs_servers.json").read_bytes()
        with mock.patch.object(pbs, "_save_servers") as save, mock.patch.object(pbs, "_load_servers", return_value=[{"id": str(i)} for i in range(32)]):
            response = self.send(data=self.server)
        self.assertEqual(response.json, {"error": "At most 32 PBS connections may be configured.", "code": "pbs_connection_limit", "params": {"count": 32}})
        self.assertEqual(response.status_code, 400); save.assert_not_called()
        pbs._remote_get.return_value = {}
        response = self.send(data=self.server)
        self.assertEqual(response.json["code"], "pbs_invalid_datastores")
        self.assertEqual((self.root / "pbs_servers.json").read_bytes(), before)

    def test_login_failures_keep_saved_state_and_cleanup_a_created_token(self):
        before = (self.root / "pbs_servers.json").read_bytes()
        login = {"name": "Fixture", "url": "https://pbs.invalid", "username": "root@pam", "password": "fake"}
        for stage, code in [("ticket", "pbs_invalid_login"), ("token", "pbs_invalid_token"), ("acl", "pbs_audit_role_denied")]:
            calls = []
            def request(server, method, endpoint, headers, form=None, rejected="", rejected_code="pbs_token_rejected"):
                calls.append((method, endpoint))
                if endpoint == "/access/ticket": return None if stage == "ticket" else {"ticket": "fake", "CSRFPreventionToken": "fake"}
                if method == "POST": return None if stage == "token" else {"tokenid": "audit@pbs!fixture", "value": "fake"}
                if method == "PUT": raise pbs.PBSError(rejected, code=rejected_code)
            pbs._remote_request.side_effect = request
            response = self.send(path="/api/pbs/servers/login", data=login)
            self.assertEqual(response.status_code, 400); self.assertEqual(response.json["code"], code)
            self.assertEqual((self.root / "pbs_servers.json").read_bytes(), before)
            self.assertEqual(sum(method == "DELETE" for method, _ in calls), 1 if stage == "acl" else 0)


if __name__ == "__main__": unittest.main()
