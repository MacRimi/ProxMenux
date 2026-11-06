"""Exercise the shipped routes and persistence; localization is additive."""
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
import monitor_links as links


class MonitorLinksI18nTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "links.json"
        self.previous = {"manual": [{"id": "saved", "name": "Saved", "url": "https://saved.test", "product": "pve"}], "overrides": {}}
        self.path.write_text(json.dumps(self.previous))
        for patch in [mock.patch.object(links, "LINKS_FILE", self.path),
                      mock.patch.object(links, "refresh"), mock.patch.object(links, "_probe")]:
            patch.start()
            self.addCleanup(patch.stop)
        auth_provider = types.SimpleNamespace(
            load_auth_config=lambda: {"enabled": True},
            verify_token=lambda token: "fixture" if token in ("admin", "reader") else None,
            verify_token_full=lambda token: ("fixture", "full_admin" if token == "admin" else "read_only")
            if token in ("admin", "reader") else (None, None))
        middleware_spec = importlib.util.spec_from_file_location("fixture_jwt_middleware", ROOT / "AppImage/scripts/jwt_middleware.py")
        middleware = importlib.util.module_from_spec(middleware_spec)
        # Execute the shipped decorators; only credential verification is faked.
        with mock.patch.dict(sys.modules, {"auth_manager": auth_provider}):
            middleware_spec.loader.exec_module(middleware)
        spec = importlib.util.spec_from_file_location("fixture_monitor_links_routes", ROOT / "AppImage/scripts/flask_monitor_links_routes.py")
        routes = importlib.util.module_from_spec(spec)
        # Import isolation keeps the real JWT module and other suites untouched.
        with mock.patch.dict(sys.modules, {"jwt_middleware": middleware}):
            spec.loader.exec_module(routes)
        app = Flask(__name__)
        app.register_blueprint(routes.monitor_links_bp)
        self.client = app.test_client()

    def send(self, method, path="", payload=None, role="admin"):
        return self.client.open("/api/monitor-links" + path, method=method,
                                json=payload, headers={"Authorization": "Bearer " + role} if role else {})

    def rejected(self, method, path, payload, message, code, params=None):
        before = self.path.read_bytes()
        with mock.patch.object(links, "_save") as save:
            response = self.send(method, path, payload)
        self.assertEqual(response.status_code, 400)
        expected = {"error": message, "code": code}
        if params:
            expected["params"] = params
        self.assertEqual(response.json, expected)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        save.assert_not_called()
        links.refresh.assert_not_called()
        links._probe.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_validation_errors_preserve_english_status_and_have_stable_codes_without_effects(self):
        cases = [
            ("POST", "", None, "Invalid request.", "monitor_link_invalid_request"),
            ("PATCH", "/manual:saved", [], "Invalid request.", "monitor_link_invalid_request"),
            ("POST", "", {"url": " "}, "Enter the address of the Monitor.", "monitor_link_address_required"),
            ("POST", "", {"url": "ftp://example.test"}, "The address must start with http:// or https:// and name a host.", "monitor_link_invalid_address"),
            ("POST", "", {"url": "https://user:pass@example.test"}, "The address must not contain a user or password.", "monitor_link_address_credentials"),
            ("PATCH", "/manual:saved", {"name": "Unsaved", "url": "https://example.test:99999"}, "The port of the address is not valid.", "monitor_link_invalid_port"),
            ("PATCH", "/cluster:node", {"url": "ftp://example.test"}, "The address must start with http:// or https:// and name a host.", "monitor_link_invalid_address"),
            ("POST", "", {"url": "https://saved.test/path"}, "This address is already in the list.", "monitor_link_duplicate"),
            ("PATCH", "/manual:absent", {"url": "https://new.test"}, "Node not found.", "monitor_link_not_found"),
            ("PATCH", "/other:node", {}, "Node not found.", "monitor_link_not_found"),
            ("DELETE", "/cluster:node", None, "Only nodes added by hand can be removed; detected ones can be hidden.", "monitor_link_detected_remove"),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.rejected(*case)

    def test_limit_uses_actual_count_and_preserves_previous_file(self):
        with mock.patch.object(links, "MAX_MANUAL", 1):
            self.rejected("POST", "", {"url": "https://new.test"}, "At most 1 nodes can be added.",
                          "monitor_link_limit", {"count": 1})

    def test_write_failure_is_localizable_without_leaking_filesystem_details(self):
        for method, path, payload in [("POST", "", {"url": "https://new.test"}),
                                      ("PATCH", "/manual:saved", {"name": "Unsaved"}),
                                      ("DELETE", "/manual:saved", None)]:
            with self.subTest(method=method), mock.patch.object(links.os, "replace", side_effect=OSError("private path details")):
                before = self.path.read_bytes()
                response = self.send(method, path, payload)
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json, {"error": "Could not save the node list.", "code": "monitor_links_save_failed"})
                self.assertEqual(self.path.read_bytes(), before)
                links.refresh.assert_not_called()
                links._probe.assert_not_called()

    def test_successful_crud_and_detected_hide_reset_keep_existing_contract(self):
        response = self.send("POST", payload={"name": "New", "url": "new.test:8008/path", "product": "pbs"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {"success", "key"})
        key = response.json["key"]
        self.assertTrue(key.startswith("manual:"))
        row = links._load()["manual"][-1]
        self.assertEqual((row["url"], row["product"]), ("https://new.test:8008", "pbs"))
        self.assertEqual(self.send("PATCH", "/" + key, {"url": "http://changed.test"}).json, {"success": True})
        self.assertEqual(links._load()["manual"][-1]["url"], "http://changed.test")
        self.assertEqual(self.send("PATCH", "/cluster:node", {"url": "https://override.test", "hidden": True}).json, {"success": True})
        self.assertEqual(self.send("PATCH", "/cluster:node", {"url": "", "hidden": False}).json, {"success": True})
        self.assertEqual(links._load()["overrides"], {"cluster:node": {"hidden": False}})
        self.assertEqual(self.send("DELETE", "/" + key).json, {"success": True})
        self.assertEqual(links._load()["manual"], self.previous["manual"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(links.refresh.call_count, 5)
        links._probe.assert_not_called()

    def test_existing_read_and_admin_decorators_still_guard_routes_before_effects(self):
        with mock.patch.object(links, "cached_links", return_value={"self": {}, "links": []}) as cached, \
                mock.patch.object(links, "_save") as save:
            for method, path in [("POST", ""), ("PATCH", "/manual:saved"), ("DELETE", "/manual:saved")]:
                for role, status in [(None, 401), ("reader", 403)]:
                    self.assertEqual(self.send(method, path, {"url": "https://new.test"}, role).status_code, status)
            self.assertEqual(self.send("GET", role=None).status_code, 401)
            self.assertEqual(self.send("GET", "?all=1", role="reader").status_code, 200)
            cached.assert_called_once_with(include_hidden=True)
            save.assert_not_called()
            links.refresh.assert_not_called()
            links._probe.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text()), self.previous)


if __name__ == "__main__":
    unittest.main()
