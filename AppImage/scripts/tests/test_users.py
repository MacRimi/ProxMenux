"""Several local users, each with their profile.

The account of an existing installation becomes the first administrator
without anyone signing in again; administrators add users and choose their
profiles, and the Monitor always keeps one administrator. Real auth_manager
on temporary files, real routes."""
import importlib.util
import json
import logging
import logging.handlers
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import jwt
from flask import Flask, jsonify, request

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth_manager  # noqa: E402
from jwt_middleware import require_auth, require_admin_scope  # noqa: E402
from test_access_modes import QuietHandler, functions, PASSWORD  # noqa: E402

OTHER = "Another-Passw0rd!"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class Users(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patch = mock.patch.multiple(auth_manager, CONFIG_DIR=self.root, AUTH_CONFIG_FILE=self.root / "auth.json",
                                    AVATAR_FILE=self.root / "avatar.bin",
                                    AVATAR_CONTENT_TYPE_FILE=self.root / "avatar.type",
                                    SETUP_CODE_FILE=self.root / "monitor-setup-code")
        patch.start()
        self.addCleanup(patch.stop)
        auth_manager._invalidate_revoked_cache()

        with mock.patch.object(logging, "FileHandler", QuietHandler), \
                mock.patch.object(logging.handlers, "SysLogHandler", QuietHandler):
            spec = importlib.util.spec_from_file_location("users_auth_routes", SCRIPTS / "flask_auth_routes.py")
            self.routes = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.routes)
        self.routes._login_limiter.check_and_record = lambda ip: (True, 0)

        app = Flask(__name__)
        app.register_blueprint(self.routes.auth_bp)
        gate = functions(SCRIPTS / "flask_server.py", "_UNDECIDED_ROUTES", "require_access_decision",
                         request=request, jsonify=jsonify)
        app.before_request(gate["require_access_decision"])
        ok = lambda **_: jsonify(ok=True)
        for rule, method, decorator in (("/api/vms/<int:vmid>", "GET", require_auth),
                                        ("/api/vms/<int:vmid>/control", "POST", require_auth),
                                        ("/api/system/power/reboot", "POST", require_admin_scope),
                                        ("/api/terminal/ticket", "POST", require_admin_scope)):
            app.add_url_rule(rule, f"{method} {rule}", decorator(ok), methods=[method])
        self.client = app.test_client()

    # ── helpers ──────────────────────────────────────────────────────
    def config(self):
        return json.loads((self.root / "auth.json").read_text())

    def login(self, username, password=PASSWORD):
        answer = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(answer.status_code, 200, answer.json)
        return answer.json["token"]

    def call(self, method, path, token=None, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.open(path, method=method, headers=headers, **kwargs)

    def admin(self):
        self.assertTrue(auth_manager.setup_auth("admin", PASSWORD)[0])
        return self.login("admin")

    def add(self, token, username, profile, password=OTHER):
        answer = self.call("POST", "/api/auth/users", token,
                           json={"username": username, "password": password, "profile": profile})
        self.assertEqual(answer.status_code, 200, answer.json)
        return self.login(username, password)

    def reach(self, token):
        return (self.call("GET", "/api/vms/100", token).status_code,
                self.call("POST", "/api/vms/100/control", token).status_code,
                self.call("POST", "/api/system/power/reboot", token).status_code,
                self.call("POST", "/api/terminal/ticket", token).status_code)

    # ── an existing installation ─────────────────────────────────────
    def test_the_account_of_an_existing_installation_becomes_the_first_administrator(self):
        secret = "s" * 64
        old_session = jwt.encode({"username": "pedro", "iss": auth_manager.JWT_ISSUER,
                                  "aud": auth_manager.JWT_AUDIENCE, "exp": 4102444800}, secret, algorithm="HS256")
        old_api = jwt.encode({"username": "pedro", "scope": "read_only", "iss": auth_manager.JWT_ISSUER,
                              "aud": auth_manager.JWT_AUDIENCE, "exp": 4102444800}, secret, algorithm="HS256")
        (self.root / "auth.json").write_text(json.dumps({
            "enabled": True, "configured": True, "username": "pedro",
            "password_hash": auth_manager.hash_password(PASSWORD), "display_name": "Pedro",
            "totp_enabled": False, "jwt_secret": secret, "access_mode": "password",
            "api_tokens": [{"id": "old", "name": "Home Assistant", "token_hash": "h"}]}))

        # Nobody signs in again: the session and the API token keep working.
        self.assertEqual(auth_manager.verify_token_full(old_session), ("pedro", "full_admin"))
        self.assertEqual(auth_manager.profile_for("password", "pedro", "full_admin"), "admin")
        self.assertEqual(auth_manager.profile_for("password", "pedro", "read_only"), "observer")
        stored = self.config()
        [user] = stored["users"]
        self.assertEqual((user["username"], user["profile"], user["legacy"], user["display_name"]),
                         ("pedro", "admin", True, "Pedro"))
        self.assertEqual(stored["username"], "pedro")  # still there for an older version
        self.assertEqual(self.reach(old_session), (200, 200, 200, 200))
        self.assertEqual(self.reach(old_api)[:2], (200, 403))
        self.assertEqual(auth_manager.load_auth_config()["users"][0]["uid"], user["uid"])  # migrated once
        self.assertEqual(auth_manager.list_api_tokens()[0]["owner"], "pedro")

    # ── profiles ─────────────────────────────────────────────────────
    def test_each_user_reaches_what_their_profile_allows(self):
        admin = self.admin()
        expected = {"observer": (200, 403, 403, 403), "operator": (200, 200, 403, 200),
                    "operator_no_terminal": (200, 200, 403, 200)}
        for profile, statuses in expected.items():
            with self.subTest(profile=profile):
                token = self.add(admin, f"user-{profile.replace('_', '-')}", profile)
                self.assertEqual(self.reach(token), statuses)
                status = self.call("GET", "/api/auth/status", token).json
                self.assertEqual((status["profile"], status["local_user"]), (profile, True))
                self.assertEqual(status["capabilities"]["terminal"], profile == "operator")
        self.assertEqual(self.reach(admin), (200, 200, 200, 200))

    def test_a_profile_change_applies_to_open_sessions(self):
        admin = self.admin()
        token = self.add(admin, "maria", "operator")
        self.assertEqual(self.call("POST", "/api/vms/100/control", token).status_code, 200)
        self.assertEqual(self.call("PUT", "/api/auth/users/maria", admin, json={"profile": "observer"}).status_code, 200)
        self.assertEqual(self.call("POST", "/api/vms/100/control", token).status_code, 403)

    def test_only_administrators_manage_users(self):
        admin = self.admin()
        operator = self.add(admin, "maria", "operator")
        self.assertEqual(self.call("GET", "/api/auth/users", operator).status_code, 403)
        self.assertEqual(self.call("POST", "/api/auth/users", operator,
                                   json={"username": "x", "password": OTHER, "profile": "admin"}).status_code, 403)
        listed = self.call("GET", "/api/auth/users", admin).json
        self.assertEqual([(u["username"], u["profile"], u["primary"]) for u in listed["users"]],
                         [("admin", "admin", True), ("maria", "operator", False)])
        self.assertNotIn("password_hash", json.dumps(listed))

    def test_new_users_are_checked(self):
        admin = self.admin()
        for body in ({"username": "Admin", "password": OTHER, "profile": "observer"},  # taken, any case
                     {"username": "root@pam", "password": OTHER, "profile": "observer"},
                     {"username": "maria", "password": "short", "profile": "observer"},
                     {"username": "maria", "password": OTHER, "profile": "superuser"}):
            with self.subTest(body=body):
                self.assertEqual(self.call("POST", "/api/auth/users", admin, json=body).status_code, 400)

    # ── always one administrator ─────────────────────────────────────
    def test_the_monitor_always_keeps_an_administrator(self):
        admin = self.admin()
        self.assertEqual(self.call("PUT", "/api/auth/users/admin", admin, json={"profile": "observer"}).status_code, 400)
        self.assertEqual(self.call("DELETE", "/api/auth/users/admin", admin).status_code, 400)
        second = self.add(admin, "maria", "admin")
        self.assertEqual(self.call("DELETE", "/api/auth/users/maria", second).status_code, 400)  # not yourself
        self.assertEqual(self.call("PUT", "/api/auth/users/admin", second, json={"profile": "observer"}).status_code, 200)
        self.assertEqual(self.call("PUT", "/api/auth/users/maria", second, json={"profile": "observer"}).status_code, 400)
        # The top level, for an older version, follows the remaining administrator.
        self.assertEqual(self.config()["username"], "maria")

    # ── removing users ───────────────────────────────────────────────
    def test_a_removed_user_loses_sessions_and_tokens_even_if_created_again(self):
        admin = self.admin()
        token = self.add(admin, "maria", "operator")
        api = self.call("POST", "/api/auth/generate-api-token", token,
                        json={"password": OTHER, "token_name": "script", "scope": "full_admin"}).json["token"]
        self.assertEqual(self.reach(api)[:2], (200, 200))
        self.assertEqual(self.call("DELETE", "/api/auth/users/maria", admin).status_code, 200)
        self.assertEqual(self.call("GET", "/api/vms/100", token).status_code, 401)
        self.assertEqual(self.call("GET", "/api/vms/100", api).status_code, 401)
        self.add(admin, "maria", "operator")
        self.assertEqual(self.call("GET", "/api/vms/100", token).status_code, 401)

    # ── API tokens ───────────────────────────────────────────────────
    def test_api_tokens_never_do_more_than_their_user(self):
        admin = self.admin()
        observer = self.add(admin, "maria", "observer")
        api = self.call("POST", "/api/auth/generate-api-token", observer,
                        json={"password": OTHER, "token_name": "dashboard", "scope": "full_admin"}).json["token"]
        self.assertEqual(self.reach(api), (200, 403, 403, 403))
        own = self.call("GET", "/api/auth/api-tokens", observer).json["tokens"]
        self.assertEqual([(t["owner"], t["scope"]) for t in own], [("maria", "full_admin")])
        self.call("POST", "/api/auth/generate-api-token", admin,
                  json={"password": PASSWORD, "token_name": "admin script"})
        self.assertEqual(len(self.call("GET", "/api/auth/api-tokens", observer).json["tokens"]), 1)
        everyone = self.call("GET", "/api/auth/api-tokens", admin).json["tokens"]
        self.assertEqual(sorted(t["owner"] for t in everyone), ["admin", "maria"])
        admin_token_id = next(t["id"] for t in everyone if t["owner"] == "admin")
        self.assertEqual(self.call("DELETE", f"/api/auth/api-tokens/{admin_token_id}", observer).status_code, 400)

    # ── each user's own account ──────────────────────────────────────
    def test_each_user_keeps_their_own_password_second_factor_and_avatar(self):
        admin = self.admin()
        observer = self.add(admin, "maria", "observer")
        changed = self.call("POST", "/api/auth/change-password", observer,
                            json={"old_password": OTHER, "new_password": "Third-Passw0rd!"})
        self.assertEqual(changed.status_code, 200, changed.json)
        self.login("maria", "Third-Passw0rd!")
        self.login("admin")  # untouched

        self.assertEqual(self.call("POST", "/api/auth/totp/setup", observer).status_code, 200)
        user = auth_manager.find_user("maria")
        import pyotp
        code = pyotp.TOTP(user["totp_secret"]).now()
        self.assertEqual(self.call("POST", "/api/auth/totp/enable", observer, json={"token": code}).status_code, 200)
        self.assertTrue(self.call("GET", "/api/auth/status", observer).json["totp_enabled"])
        self.assertFalse(self.call("GET", "/api/auth/status", admin).json["totp_enabled"])
        self.assertTrue(self.client.post("/api/auth/login", json={"username": "maria", "password": "Third-Passw0rd!"})
                        .json["requires_totp"])

        upload = self.client.post("/api/auth/profile/avatar", data=PNG,
                                  headers={"Authorization": f"Bearer {observer}", "Content-Type": "image/png"})
        self.assertEqual(upload.status_code, 200, upload.json)
        self.assertEqual(self.call("GET", "/api/auth/profile/avatar", observer).data, PNG)
        self.assertEqual(self.call("GET", "/api/auth/profile/avatar", admin).status_code, 404)
        self.assertFalse(auth_manager.AVATAR_FILE.exists())  # the administrator's stays apart
        self.assertEqual(self.call("PUT", "/api/auth/profile", observer, json={"display_name": "María"}).json["display_name"],
                         "María")
        self.assertIsNone(self.call("GET", "/api/auth/profile", admin).json["display_name"])

        # An administrator removes a lost second factor.
        self.assertEqual(self.call("PUT", "/api/auth/users/maria", admin, json={"reset_totp": True}).status_code, 200)
        self.assertFalse(auth_manager.find_user("maria")["totp_enabled"])

    # ── other writers of the file ────────────────────────────────────
    def test_the_menu_reset_and_an_older_version_are_followed(self):
        admin = self.admin()
        self.add(admin, "maria", "operator")
        # An older version changes the administrator's password at the top level.
        stored = self.config()
        stored["password_hash"] = auth_manager.hash_password(OTHER)
        (self.root / "auth.json").write_text(json.dumps(stored))
        self.login("admin", OTHER)
        self.login("maria", OTHER)
        # The menu's Reset Monitor Password clears the top-level account only.
        stored = self.config()
        stored.update(enabled=False, configured=False, username="", password_hash="")
        stored.pop("access_mode", None)
        (self.root / "auth.json").write_text(json.dumps(stored))
        self.assertEqual(auth_manager.access_mode(), "undecided")
        self.assertEqual(auth_manager.load_auth_config()["users"], [])
        self.assertEqual(self.call("GET", "/api/vms/100", admin).status_code, 403)  # setup required
        self.assertTrue(auth_manager.setup_auth("new-owner", PASSWORD)[0])
        self.assertEqual(self.call("GET", "/api/vms/100", admin).status_code, 401)


if __name__ == "__main__":
    unittest.main()
