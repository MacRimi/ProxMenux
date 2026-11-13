"""How the Monitor is reached: undecided, password, read-only or open.

A new installation serves nothing but its first-run screen until someone
chooses, with the setup code when the installer wrote one. Read-only access
sees and runs nothing else. Real auth_manager on temporary files; the global
gate and the WebSocket check are taken from their modules as written."""
import ast
import importlib.util
import json
import logging
import logging.handlers
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

from flask import Flask, jsonify, request

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import auth_manager  # noqa: E402
import jwt_middleware  # noqa: E402
from jwt_middleware import require_auth, require_admin_scope, has_full_access  # noqa: E402

PASSWORD = "Fixture-Passw0rd!"


class QuietHandler(logging.NullHandler):
    def __init__(self, *args, **kwargs):
        super().__init__()


def functions(path, *names, **scope):
    """Top-level statements of a module, by name, run in `scope`."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    nodes = [n for n in tree.body
             if (isinstance(n, ast.FunctionDef) and n.name in names)
             or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in names for t in n.targets))]
    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []  # registered by the test instead
    namespace = dict(scope)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class AccessModes(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.code_file = self.root / "monitor-setup-code"
        patch = mock.patch.multiple(auth_manager, CONFIG_DIR=self.root, AUTH_CONFIG_FILE=self.root / "auth.json",
                                    SETUP_CODE_FILE=self.code_file)
        patch.start()
        self.addCleanup(patch.stop)
        auth_manager._invalidate_revoked_cache()

        # The auth routes log failures to /var/log; here to nowhere.
        with mock.patch.object(logging, "FileHandler", QuietHandler), \
                mock.patch.object(logging.handlers, "SysLogHandler", QuietHandler):
            spec = importlib.util.spec_from_file_location("access_auth_routes", SCRIPTS / "flask_auth_routes.py")
            self.routes = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.routes)

        app = Flask(__name__)
        app.register_blueprint(self.routes.auth_bp)
        gate = functions(SCRIPTS / "flask_server.py", "_UNDECIDED_ROUTES", "require_access_decision",
                         request=request, jsonify=jsonify)
        app.before_request(gate["require_access_decision"])

        @app.route("/api/read")
        @require_auth
        def read():
            return jsonify(full=has_full_access())

        @app.route("/api/write", methods=["POST"])
        @require_auth
        def write():
            return jsonify(ok=True)

        @app.route("/api/admin")
        @require_admin_scope
        def admin():
            return jsonify(ok=True)

        @app.route("/api/internal/event", methods=["POST"])
        def internal():
            return jsonify(ok=True)

        @app.route("/_next/static/app.js")
        def static_file():
            return "static"

        self.client = app.test_client()

    # ── helpers ──────────────────────────────────────────────────────
    def write_config(self, **values):
        (self.root / "auth.json").write_text(json.dumps(values))

    def account(self):
        self.assertTrue(auth_manager.setup_auth("admin", PASSWORD)[0])
        return auth_manager.generate_token("admin")

    def statuses(self, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return (self.client.get("/api/read", headers=headers).status_code,
                self.client.post("/api/write", headers=headers).status_code,
                self.client.get("/api/admin", headers=headers).status_code)

    def ws_check(self, ticket_ok=False):
        terminal = functions(SCRIPTS / "flask_terminal_routes.py", "_ws_auth_check",
                             request=types.SimpleNamespace(args={"ticket": "t"}),
                             _consume_terminal_ticket=lambda ticket, need: ticket_ok)
        return terminal["_ws_auth_check"]("terminal")

    # ── the mode a configuration describes ───────────────────────────
    def test_modes_from_existing_configurations(self):
        self.assertEqual(auth_manager.access_mode(), "undecided")  # no file: never opened
        for config, mode in (({"enabled": False, "configured": False}, "undecided"),
                             ({"enabled": False, "declined": True, "configured": True}, "open"),
                             ({"enabled": True, "username": "a", "password_hash": "h"}, "password"),
                             ({"enabled": False, "access_mode": "read_only"}, "read_only"),
                             ({"enabled": False, "access_mode": "open"}, "open")):
            with self.subTest(config=config):
                self.assertEqual(auth_manager.access_mode(config), mode)

    def test_capabilities_follow_the_mode_and_the_token(self):
        everything = dict.fromkeys(("view", "execute", "guests", "backup", "update", "terminal", "admin"), True)
        view = dict(dict.fromkeys(everything, False), view=True)
        self.assertEqual(auth_manager.capabilities("open"), everything)
        self.assertEqual(auth_manager.capabilities("password", "full_admin"), everything)
        self.assertEqual(auth_manager.capabilities("password", "read_only"), view)
        self.assertEqual(auth_manager.capabilities("read_only"), view)
        self.assertFalse(any(auth_manager.capabilities("undecided").values()))
        self.assertFalse(any(auth_manager.capabilities("password").values()))

    # ── undecided ────────────────────────────────────────────────────
    def test_an_undecided_monitor_serves_only_its_first_run_screen(self):
        self.assertEqual(self.statuses(), (403, 403, 403))
        self.assertEqual(self.client.get("/api/read").json["error"], "setup_required")
        self.assertEqual(self.client.get("/api/auth/status").status_code, 200)
        self.assertEqual(self.client.get("/_next/static/app.js").status_code, 200)
        self.assertEqual(self.client.post("/api/internal/event").status_code, 200)
        self.assertFalse(self.ws_check(ticket_ok=True))

    def test_a_new_installation_asks_for_its_setup_code(self):
        self.code_file.write_text("ABCD-EFGH-JKLM\n")
        status = self.client.get("/api/auth/status").json
        self.assertTrue(status["setup_code_required"])
        refused = self.client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
        self.assertEqual((refused.status_code, refused.json["error"]), (403, "setup_code_invalid"))
        refused = self.client.post("/api/auth/mode", json={"mode": "open", "setup_code": "WRONG-CODE-0000"})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(auth_manager.access_mode(), "undecided")
        # Case, spaces and dashes do not matter; the code is used once.
        created = self.client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD,
                                                             "setup_code": "abcd efgh jklm"})
        self.assertEqual(created.status_code, 200)
        self.assertEqual(auth_manager.access_mode(), "password")
        self.assertFalse(self.code_file.exists())

    def test_wrong_codes_are_limited_like_logins(self):
        self.code_file.write_text("ABCD-EFGH-JKLM")
        codes = [self.client.post("/api/auth/mode", json={"mode": "open", "setup_code": "nope"}).status_code
                 for _ in range(6)]
        self.assertEqual(codes, [403] * 5 + [429])

    def test_an_existing_installation_without_code_chooses_freely(self):
        self.assertFalse(self.client.get("/api/auth/status").json["setup_code_required"])
        chosen = self.client.post("/api/auth/mode", json={"mode": "read_only"})
        self.assertEqual((chosen.status_code, auth_manager.access_mode()), (200, "read_only"))

    def test_skip_and_decline_still_mean_open_and_only_once(self):
        self.assertEqual(self.client.post("/api/auth/skip").status_code, 200)
        self.assertEqual(auth_manager.access_mode(), "open")
        self.assertEqual(self.client.post("/api/auth/skip").status_code, 403)
        self.assertEqual(self.client.post("/api/auth/decline").status_code, 403)

    # ── read-only ────────────────────────────────────────────────────
    def test_read_only_reads_and_nothing_else(self):
        auth_manager.choose_access_mode("read_only")
        self.assertEqual(self.statuses(), (200, 403, 403))
        self.assertFalse(self.client.get("/api/read").json["full"])
        self.assertFalse(self.ws_check(ticket_ok=True))
        status = self.client.get("/api/auth/status").json
        self.assertEqual((status["access_mode"], status["capabilities"]["terminal"]), ("read_only", False))
        # A token from an earlier account is not looked at.
        self.write_config(enabled=False, access_mode="read_only")
        self.assertEqual(self.statuses(auth_manager.generate_token("admin")), (200, 403, 403))

    def test_leaving_read_only_needs_a_setup_code(self):
        auth_manager.choose_access_mode("read_only")
        self.assertEqual(self.client.post("/api/auth/mode", json={"mode": "open"}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/setup",
                                          json={"username": "x", "password": PASSWORD}).status_code, 403)
        self.code_file.write_text("ABCD-EFGH-JKLM")
        created = self.client.post("/api/auth/setup", json={"username": "x", "password": PASSWORD,
                                                             "setup_code": "ABCD-EFGH-JKLM"})
        self.assertEqual((created.status_code, auth_manager.access_mode()), (200, "password"))

    # ── open ─────────────────────────────────────────────────────────
    def test_open_lets_everything_through_as_chosen(self):
        auth_manager.choose_access_mode("open")
        self.assertEqual(self.statuses(), (200, 200, 200))
        self.assertTrue(self.ws_check())
        self.assertTrue(self.client.get("/api/read").json["full"])

    # ── password ─────────────────────────────────────────────────────
    def test_password_mode_needs_a_token_and_full_scope_to_act(self):
        token = self.account()
        self.assertEqual(self.statuses(), (401, 401, 401))
        self.assertEqual(self.statuses(token), (200, 200, 200))
        reader = auth_manager.generate_token("admin")
        with mock.patch.object(jwt_middleware, "verify_token_full", return_value=("admin", "read_only")):
            self.assertEqual(self.statuses(reader), (200, 403, 403))
        self.assertTrue(self.ws_check(ticket_ok=True))
        self.assertFalse(self.ws_check(ticket_ok=False))

    def test_status_names_the_account_only_to_its_session(self):
        token = self.account()
        anonymous = self.client.get("/api/auth/status").json
        self.assertIsNone(anonymous["username"])
        self.assertFalse(any(anonymous["capabilities"].values()))
        signed_in = self.client.get("/api/auth/status", headers={"Authorization": f"Bearer {token}"}).json
        self.assertEqual((signed_in["username"], signed_in["capabilities"]["terminal"]), ("admin", True))

    def test_an_account_is_never_claimed_or_replaced_from_outside(self):
        self.account()
        self.assertEqual(self.client.post("/api/auth/setup",
                                          json={"username": "x", "password": PASSWORD}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/mode", json={"mode": "open"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/enable").status_code, 401)
        self.assertEqual(auth_manager.access_mode(), "password")

    def test_removing_the_password_leaves_read_only_or_open_never_undecided(self):
        token = self.account()
        headers = {"Authorization": f"Bearer {token}"}
        removed = self.client.post("/api/auth/disable", headers=headers, json={})
        self.assertEqual((removed.status_code, auth_manager.access_mode()), (200, "read_only"))
        self.write_config()
        token = self.account()
        self.client.post("/api/auth/mode", headers={"Authorization": f"Bearer {token}"}, json={"mode": "open"})
        self.assertEqual(auth_manager.access_mode(), "open")


if __name__ == "__main__":
    unittest.main()
