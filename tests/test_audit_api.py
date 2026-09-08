"""Flask API contracts with stubbed authentication, temporary DB, no probes."""
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from flask import Flask
except ImportError:
    Flask = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "AppImage/scripts"))
import audit_store as store


@unittest.skipIf(Flask is None, "Flask runtime required")
class AuditApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dbpatch = patch.object(store, "DB_PATH", Path(self.temp.name) / "audit.db")
        self.dbpatch.start()
        self.addCleanup(self.dbpatch.stop)
        store._schema_ready = False
        self.addCleanup(lambda: setattr(store, "_schema_ready", False))
        auth = types.ModuleType("auth_manager")
        auth.load_auth_config = lambda: {"enabled": True}
        auth.verify_token = lambda token: "verified-operator"
        middleware = types.ModuleType("jwt_middleware")
        middleware.require_auth = lambda f: f
        middleware.require_admin_scope = lambda f: f
        with patch.dict(sys.modules, auth_manager=auth, jwt_middleware=middleware):
            sys.modules.pop("flask_audit_routes", None)
            self.routes = importlib.import_module("flask_audit_routes")
        self.addCleanup(lambda: sys.modules.pop("flask_audit_routes", None))
        self.app = Flask(__name__)
        self.app.register_blueprint(self.routes.audit_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer fixture"}
        self.finding = {"check_id": "guests.privileged_containers", "area": "guests",
                        "severity": "WARNING", "state": "warn", "raw_state": "warn",
                        "classification": "warning", "raw_classification": "warning",
                        "affected": [{"vmid": 101}], "scope": "fixture-scope"}
        self.run = store.start_run("full")
        store.record_findings(self.run, [self.finding])
        store.finish_run(self.run, checks_total=1)

    def accept(self, **extra):
        return self.client.post("/api/audit/exceptions", headers=self.headers, json={
            "check_id": self.finding["check_id"], "reason": "intentional lab", "run_id": self.run,
            "accepted_by": "forged-author", **extra})

    def test_actor_is_from_authentication_and_live_view_updates(self):
        self.assertEqual(self.accept().status_code, 200)
        row = self.client.get(f"/api/audit/runs/{self.run}?effective=1").json["findings"][0]
        self.assertEqual(row["state"], "accepted")
        self.assertEqual(row["exception"]["accepted_by"], "verified-operator")
        self.assertEqual(row["classification"], "warning")
        self.assertEqual(row["raw_classification"], "warning")
        historical = self.client.get(f"/api/audit/runs/{self.run}").json["findings"][0]
        self.assertEqual(historical["state"], "warn")
        status = self.client.get("/api/audit/status").json
        self.assertEqual(status["summary"], {"accepted": 1})

    def test_revoke_is_immediate(self):
        self.accept()
        self.client.delete(f"/api/audit/exceptions/{self.finding['check_id']}", headers=self.headers)
        self.assertEqual(self.client.get("/api/audit/status").json["summary"], {"warning": 1})
        self.assertEqual(len(self.client.get("/api/audit/exceptions").json["history"]), 2)

    def test_expiry_must_be_positive_integer(self):
        for days in (0, False, -1, 1.5, True, 999999, "invalid"):
            with self.subTest(days=days):
                self.assertEqual(self.accept(expires_in_days=days).status_code, 400)

    def test_stale_run_cannot_accept_new_results(self):
        self.assertEqual(self.accept(run_id="old-run").status_code, 409)

    def test_observation_cannot_be_accepted_as_a_risk(self):
        finding = {**self.finding, 'classification':'observation', 'raw_classification':'observation'}
        self.run = store.start_run('full')
        store.record_findings(self.run, [finding])
        store.finish_run(self.run, checks_total=1)
        self.assertEqual(self.accept().status_code, 400)
        self.assertFalse(store.active_exceptions())

    def test_invalid_profile_or_area_never_starts_worker(self):
        with patch.object(self.routes.threading, "Thread") as worker:
            for body in ({"profile": "invented"}, {"areas": ["invented"]}, {"areas": []}, {"areas": "system"}):
                self.assertEqual(self.client.post("/api/audit/run", json=body).status_code, 400)
            worker.assert_not_called()

    def test_run_returns_id_before_worker_finishes(self):
        with patch.object(self.routes.threading, "Thread"):
            response = self.client.post("/api/audit/run", json={"profile": "full"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json["run_id"])
            self.assertEqual(self.client.post("/api/audit/run", json={}).status_code, 409)

    def test_audit_database_failure_does_not_prevent_monitor_startup(self):
        with patch.object(store, "recover_interrupted_runs", side_effect=OSError("read-only filesystem")):
            another_app = Flask("audit-startup-failure")
            another_app.register_blueprint(self.routes.audit_bp)
        self.assertEqual(self.client.get("/api/audit/status").status_code, 500)
        self.assertEqual(self.client.post("/api/audit/run", json={}).status_code, 500)


if __name__ == "__main__":
    unittest.main()
