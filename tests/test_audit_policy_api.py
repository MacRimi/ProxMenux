"""Policy endpoint contracts; authentication and storage are isolated fixtures."""
import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "AppImage/scripts"))
from flask import Flask
import audit_policy as policy
import audit_store as store


class PolicyApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "policy.json"
        original_load, original_save = policy.load, policy.save
        for patcher in (
            patch.object(policy, "load", side_effect=lambda *args: original_load(self.path)),
            patch.object(policy, "save", side_effect=lambda raw, **kw: original_save(raw, self.path, **kw)),
            patch.object(store, "DB_PATH", Path(temp.name) / "audit.db"),
            patch.object(store, "_schema_ready", False),
        ):
            patcher.start(); self.addCleanup(patcher.stop)
        auth = types.ModuleType("auth_manager")
        auth.load_auth_config = lambda: {"enabled": True}
        auth.verify_token = lambda token: "fixture"
        middleware = types.ModuleType("jwt_middleware")
        middleware.require_auth = lambda f: f
        middleware.require_admin_scope = lambda f: f
        with patch.dict(sys.modules, auth_manager=auth, jwt_middleware=middleware):
            sys.modules.pop("flask_audit_routes", None)
            routes = importlib.import_module("flask_audit_routes")
        self.addCleanup(lambda: sys.modules.pop("flask_audit_routes", None))
        app = Flask(__name__)
        app.register_blueprint(routes.audit_bp)
        self.client = app.test_client()

    def test_revision_and_conflict_contract(self):
        first = self.client.get("/api/audit/policy").json
        self.assertEqual(first["summary"]["revision"], "missing")
        self.assertEqual(self.client.put("/api/audit/policy", json={}).status_code, 428)
        payload = {"expected_revision": "missing", "defaults": {"backup": "required"}}
        response = self.client.put("/api/audit/policy", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.put("/api/audit/policy", json=payload).status_code, 409)
        self.assertEqual(self.client.get("/api/audit/policy").json["policy"]["defaults"]["backup"], "required")

    def test_validation_error_is_not_silent_success(self):
        bad = {"expected_revision": "missing", "thresholds": {"storage_usage_percent": True}}
        self.assertEqual(self.client.put("/api/audit/policy", json=bad).status_code, 400)
        self.assertFalse(self.path.exists())

    def test_invalid_file_does_not_open_empty_editor(self):
        self.path.write_text("invalid json")
        self.assertEqual(self.client.get("/api/audit/policy").status_code, 422)


if __name__ == "__main__":
    unittest.main()
