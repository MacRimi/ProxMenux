"""Proxmox VE accounts sign in to the Monitor with their own tickets.

The local Proxmox VE API is simulated: tickets, permissions on `/`, realms and
a TOTP second factor. Real auth_manager on temporary files, real routes."""
import json
import logging
import logging.handlers
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from flask import Flask, jsonify, request

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth_manager  # noqa: E402
import pve_auth  # noqa: E402
from jwt_middleware import require_auth, require_admin_scope  # noqa: E402
from test_access_modes import QuietHandler, functions, PASSWORD  # noqa: E402

SIG = "c2lnbmF0dXJl" * 4
ADMIN = f"PVE:root@pam:6AF78F9D::{SIG}"
AUDITOR = f"PVE:auditor@pve:6AF78F9D::{SIG}"
NOBODY = f"PVE:guest@pve:6AF78F9D::{SIG}"
TFA_USER = f"PVE:tfa@pve:6AF78F9D::{SIG}"
PBS_AUDITOR = f"PBS:auditor@pbs:6AF78F9D::{SIG}"
PRIVILEGES = {ADMIN: {"Sys.Modify": 1, "Sys.Audit": 1, "Sys.Console": 1},
              AUDITOR: {"Sys.Audit": 1}, NOBODY: {"VM.Audit": 1}, TFA_USER: {"Sys.Modify": 1}}
# As Proxmox VE writes it: the colons of the JSON are percent-encoded.
CHALLENGE = 'PVE:!tfa!{"totp"%3Atrue,"recovery"%3A[0,1]}:6AF78F9D::sig'


def fake_pve(method, path, data=None, ticket=None):
    if path.startswith("/access/permissions"):
        return (200, {"/": PRIVILEGES[ticket]}) if ticket in PRIVILEGES else (401, None)
    if path == "/access/domains":
        return 200, [{"realm": "pam", "type": "pam", "comment": "Linux PAM"},
                     {"realm": "pve", "type": "pve", "default": 1}]
    if path == "/access/ticket":
        user, password = data["username"], data["password"]
        if "tfa-challenge" in data:
            ok = data["tfa-challenge"] == CHALLENGE and password in ("totp:123456", "recovery:abcd-efgh")
            return (200, {"ticket": TFA_USER, "username": user}) if ok else (401, None)
        if password in PRIVILEGES:  # renewal: the ticket as password
            return 200, {"ticket": password, "username": user}
        logins = {("root@pam", "root-pass"): ADMIN, ("auditor@pve", "audit-pass"): AUDITOR,
                  ("guest@pve", "guest-pass"): NOBODY}
        if (user, password) == ("tfa@pve", "tfa-pass"):
            return 200, {"ticket": CHALLENGE, "NeedTFA": 1, "username": user}
        return (200, {"ticket": logins[(user, password)], "username": user}) if (user, password) in logins else (401, None)
    return 404, None


class PVEAccounts(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.code_file = self.root / "monitor-setup-code"
        for patch in (mock.patch.multiple(auth_manager, CONFIG_DIR=self.root, AUTH_CONFIG_FILE=self.root / "auth.json",
                                          SETUP_CODE_FILE=self.code_file),
                      mock.patch.object(pve_auth, "_request", side_effect=fake_pve)):
            patch.start()
            self.addCleanup(patch.stop)
        pve_auth._cache.clear()
        auth_manager._invalidate_revoked_cache()
        with mock.patch.object(logging, "FileHandler", QuietHandler), \
                mock.patch.object(logging.handlers, "SysLogHandler", QuietHandler):
            import importlib.util
            spec = importlib.util.spec_from_file_location("pve_auth_routes", SCRIPTS / "flask_auth_routes.py")
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
            return jsonify(ok=True)

        @app.route("/api/admin", methods=["POST"])
        @require_admin_scope
        def admin():
            return jsonify(ok=True)

        self.client = app.test_client()

    def test_guest_rule_keeps_pve_user_and_uses_csrf(self):
        path = "/nodes/fixture/lxc/100/firewall/rules/0"
        parameters = {"type": "in", "action": "ACCEPT", "enable": 0}
        native = mock.Mock(side_effect=[(200, {"ticket": ADMIN, "CSRFPreventionToken": "test-csrf"}), (200, None)])
        with mock.patch.object(pve_auth, "_request", native):
            self.assertEqual(pve_auth.write_firewall_rule(path, parameters, ADMIN, method="PUT"), 200)
        self.assertEqual(native.call_args_list, [
            mock.call("POST", "/access/ticket", {"username": "root@pam", "password": ADMIN}),
            mock.call("PUT", path, data=parameters, ticket=ADMIN, csrf="test-csrf"),
        ])
        native.reset_mock(side_effect=True)
        native.side_effect = [(200, {"ticket": ADMIN, "CSRFPreventionToken": "test-csrf"}), (200, None)]
        with mock.patch.object(pve_auth, "_request", native):
            self.assertEqual(pve_auth.write_firewall_rule(path, {"digest": "a" * 40}, ADMIN, method="DELETE"), 200)
        native.assert_called_with("DELETE", f"{path}?digest={'a' * 40}", data=None, ticket=ADMIN, csrf="test-csrf")
        with mock.patch.object(pve_auth, "_request", return_value=(
                200, {"ticket": AUDITOR, "CSRFPreventionToken": "test-csrf"})) as native:
            self.assertEqual(pve_auth.write_firewall_rule(path, parameters, ADMIN, method="PUT"), 503)
        self.assertEqual(native.call_count, 1)

    def as_ticket(self, ticket):
        return {"Authorization": f"Bearer {ticket}"}

    def proxmox_mode(self):
        self.assertTrue(auth_manager.set_pve_auth(True)[0])
        self.assertEqual(auth_manager.access_mode(), "proxmox")

    # ── the ticket and what it gives ─────────────────────────────────
    def test_privileges_on_root_decide_the_access(self):
        self.assertEqual(pve_auth.validate(ADMIN), ("root@pam", "full_admin"))
        self.assertEqual(pve_auth.validate(AUDITOR), ("auditor@pve", "read_only"))
        self.assertEqual(pve_auth.validate(NOBODY), (None, None))
        self.assertEqual(pve_auth.validate("PVE:root@pam:6AF78F9D::forged-but-unknown"), (None, None))
        self.assertEqual(pve_auth.validate(CHALLENGE), (None, None))  # half a login is no ticket

    def test_a_checked_ticket_is_asked_again_after_a_minute(self):
        pve_auth.validate(ADMIN)
        with mock.patch.object(pve_auth, "_request", side_effect=AssertionError("cached")):
            self.assertEqual(pve_auth.validate(ADMIN)[1], "full_admin")
        with mock.patch.object(pve_auth.time, "monotonic", return_value=10 ** 9):
            with mock.patch.object(pve_auth, "_request", return_value=(401, None)):
                self.assertEqual(pve_auth.validate(ADMIN), (None, None))  # expired in Proxmox VE

    # ── signing in ───────────────────────────────────────────────────
    def test_sign_in_with_user_password_and_realm(self):
        self.proxmox_mode()
        signed = self.client.post("/api/auth/pve/login", json={"username": "root", "password": "root-pass", "realm": "pam"})
        self.assertEqual((signed.status_code, signed.json["ticket"], signed.json["scope"]), (200, ADMIN, "full_admin"))
        realms = self.client.get("/api/auth/pve/realms").json["realms"]
        self.assertEqual([r["realm"] for r in realms], ["pam", "pve"])
        refused = self.client.post("/api/auth/pve/login", json={"username": "root@pam", "password": "wrong", "realm": "pve"})
        self.assertEqual(refused.status_code, 401)
        no_access = self.client.post("/api/auth/pve/login", json={"username": "guest", "password": "guest-pass", "realm": "pve"})
        self.assertEqual(no_access.status_code, 401)

    def test_a_second_factor_completes_the_sign_in(self):
        self.proxmox_mode()
        first = self.client.post("/api/auth/pve/login", json={"username": "tfa", "password": "tfa-pass", "realm": "pve"}).json
        self.assertTrue(first["need_tfa"])
        self.assertEqual(first["methods"], ["recovery", "totp"])
        for code in ("123456", "abcd-efgh"):
            done = self.client.post("/api/auth/pve/login", json={"username": first["username"],
                                                                  "challenge": first["challenge"], "code": code})
            self.assertEqual((done.status_code, done.json["ticket"]), (200, TFA_USER))
        wrong = self.client.post("/api/auth/pve/login", json={"username": first["username"],
                                                               "challenge": first["challenge"], "code": "000000"})
        self.assertEqual(wrong.status_code, 401)

    def test_the_web_interface_session_is_shared_and_renewed(self):
        self.proxmox_mode()
        self.client.set_cookie("PVEAuthCookie", AUDITOR)
        shared = self.client.get("/api/auth/pve/session").json
        self.assertEqual((shared["ticket"], shared["scope"]), (AUDITOR, "read_only"))
        renewed = self.client.post("/api/auth/pve/renew", headers=self.as_ticket(ADMIN))
        self.assertEqual(renewed.json["ticket"], ADMIN)
        self.client.set_cookie("PVEAuthCookie", NOBODY)
        self.assertEqual(self.client.get("/api/auth/pve/session").status_code, 401)

    def test_on_a_backup_server_its_own_web_session_is_shared(self):
        self.proxmox_mode()
        with mock.patch.object(pve_auth, "_product", return_value=pve_auth.PRODUCTS["pbs"]):
            PRIVILEGES[PBS_AUDITOR] = {"Sys.Audit": 1}
            self.addCleanup(PRIVILEGES.pop, PBS_AUDITOR, None)
            pve_auth._cache.clear()
            self.client.set_cookie("PVEAuthCookie", AUDITOR)
            self.assertEqual(self.client.get("/api/auth/pve/session").status_code, 404)
            self.client.set_cookie("PBSAuthCookie", PBS_AUDITOR)
            shared = self.client.get("/api/auth/pve/session").json
            self.assertEqual((shared["ticket"], shared["scope"]), (PBS_AUDITOR, "read_only"))

    # ── what a ticket can do in the Monitor ──────────────────────────
    def test_tickets_follow_the_privileges_and_status_names_the_account(self):
        self.proxmox_mode()
        self.assertEqual(self.client.get("/api/read").status_code, 401)
        self.assertEqual(self.client.get("/api/read", headers=self.as_ticket(AUDITOR)).status_code, 200)
        self.assertEqual(self.client.post("/api/admin", headers=self.as_ticket(AUDITOR)).status_code, 403)
        self.assertEqual(self.client.post("/api/admin", headers=self.as_ticket(ADMIN)).status_code, 200)
        self.assertEqual(self.client.get("/api/read", headers=self.as_ticket(NOBODY)).status_code, 401)
        status = self.client.get("/api/auth/status", headers=self.as_ticket(AUDITOR)).json
        self.assertEqual((status["access_mode"], status["auth_enabled"], status["local_account"]), ("proxmox", True, False))
        self.assertEqual((status["username"], status["auth_method"], status["capabilities"]["terminal"]),
                         ("auditor@pve", "pve", False))

    def test_tickets_mean_nothing_while_the_accounts_are_off(self):
        self.assertTrue(auth_manager.setup_auth("admin", PASSWORD)[0])
        self.assertEqual(self.client.get("/api/read", headers=self.as_ticket(ADMIN)).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/pve/login",
                                          json={"username": "root", "password": "root-pass", "realm": "pam"}).status_code, 404)
        self.client.set_cookie("PVEAuthCookie", ADMIN)
        self.assertEqual(self.client.get("/api/auth/pve/session").status_code, 404)

    # ── choosing them ────────────────────────────────────────────────
    def test_a_new_installation_chooses_them_with_its_setup_code(self):
        self.code_file.write_text("ABCD-EFGH-JKLM")
        self.assertEqual(self.client.post("/api/auth/mode", json={"mode": "proxmox"}).status_code, 403)
        chosen = self.client.post("/api/auth/mode", json={"mode": "proxmox", "setup_code": "ABCD-EFGH-JKLM"})
        self.assertEqual((chosen.status_code, auth_manager.access_mode()), (200, "proxmox"))
        self.assertFalse(self.code_file.exists())

    def test_only_a_full_session_adds_a_local_account_or_leaves_them(self):
        self.proxmox_mode()
        account = {"username": "local", "password": PASSWORD}
        self.assertEqual(self.client.post("/api/auth/setup", json=account).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/setup", json=account, headers=self.as_ticket(AUDITOR)).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/mode", json={"mode": "open"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/setup", json=account, headers=self.as_ticket(ADMIN)).status_code, 200)
        # Both now sign in; leaving the accounts off is fine with a local one.
        self.assertEqual(auth_manager.access_mode(), "password")
        self.assertTrue(auth_manager.set_pve_auth(False)[0])

    # ── profiles for Proxmox VE users and groups ─────────────────────
    def test_rules_give_users_and_groups_a_profile(self):
        self.proxmox_mode()
        cfg = self.root / "user.cfg"
        cfg.write_text("user:root@pam:1:0::::::\nuser:auditor@pve:1:0::::::\nuser:tfa@pve:1:0::::::\n"
                       "group:ops:auditor@pve,tfa@pve::\ngroup:viewers:tfa@pve::\ngroup:admins:root@pam::\n")
        patch = mock.patch.dict(pve_auth.PRODUCTS["pve"], {"users": str(cfg)})
        patch.start()
        self.addCleanup(patch.stop)
        pve_auth._directory["mtime"] = None
        rules = [{"kind": "group", "name": "viewers", "profile": "observer"},
                 {"kind": "group", "name": "ops", "profile": "operator"},
                 {"kind": "user", "name": "auditor@pve", "profile": "custom",
                  "custom": {"areas": ["backup"], "actions": ["backup"]}}]
        # Only an administrator reads or changes them.
        self.assertEqual(self.client.get("/api/auth/pve/profiles", headers=self.as_ticket(AUDITOR)).status_code, 403)
        saved = self.client.put("/api/auth/pve/profiles", json={"rules": rules}, headers=self.as_ticket(ADMIN))
        self.assertEqual(saved.status_code, 200, saved.json)
        listed = self.client.get("/api/auth/pve/profiles", headers=self.as_ticket(ADMIN)).json
        self.assertEqual((listed["users"], listed["groups"]),
                         (["auditor@pve", "root@pam", "tfa@pve"], ["admins", "ops", "viewers"]))
        # The rule of the user wins; then the first rule of one of their groups.
        # A rule applies whole: Sys.Audit lets the user in, the rule decides the rest.
        self.assertEqual(auth_manager.profile_for("proxmox", "auditor@pve", "read_only"), "custom:backup:backup")
        self.assertEqual(auth_manager.profile_for("proxmox", "tfa@pve", "full_admin"), "observer")
        rules[0], rules[1] = rules[1], rules[0]  # now ops comes first for tfa@pve
        self.assertTrue(auth_manager.set_pve_rules(rules)[0])
        self.assertEqual(auth_manager.profile_for("proxmox", "tfa@pve", "read_only"), "operator")
        # Whoever saves the rules never takes their own administration away.
        demoted = self.client.put("/api/auth/pve/profiles", headers=self.as_ticket(ADMIN),
                                  json={"rules": rules + [{"kind": "group", "name": "admins", "profile": "observer"}]})
        self.assertEqual(demoted.status_code, 400)
        self.assertEqual(auth_manager.profile_for("proxmox", "root@pam", "full_admin"), "admin")
        # Without a rule, the privileges decide.
        self.assertTrue(auth_manager.set_pve_rules([])[0])
        self.assertEqual(auth_manager.profile_for("proxmox", "root@pam", "full_admin"), "admin")
        self.assertEqual(auth_manager.profile_for("proxmox", "auditor@pve", "read_only"), "observer")
        # A rule never lets in a user Proxmox VE gives no privileges on /.
        self.assertTrue(auth_manager.set_pve_rules([{"kind": "user", "name": "guest@pve", "profile": "admin"}])[0])
        self.assertEqual(self.client.get("/api/read", headers=self.as_ticket(NOBODY)).status_code, 401)

    def test_rules_are_checked(self):
        for rules in ([{"kind": "user", "name": "noRealm", "profile": "admin"}],
                      [{"kind": "group", "name": "a:b", "profile": "admin"}],
                      [{"kind": "role", "name": "ops", "profile": "admin"}],
                      [{"kind": "group", "name": "ops", "profile": "observer"}, {"kind": "group", "name": "ops", "profile": "admin"}],
                      [{"kind": "group", "name": "ops", "profile": "custom", "custom": {"areas": [], "actions": []}}],
                      "rules"):
            with self.subTest(rules=rules):
                self.assertFalse(auth_manager.set_pve_rules(rules)[0])

    def test_the_monitor_never_ends_with_no_way_in(self):
        self.proxmox_mode()
        self.assertFalse(auth_manager.set_pve_auth(False)[0])
        self.assertEqual(auth_manager.access_mode(), "proxmox")
        chosen = self.client.post("/api/auth/mode", json={"mode": "read_only"}, headers=self.as_ticket(ADMIN))
        self.assertEqual((chosen.status_code, auth_manager.access_mode()), (200, "read_only"))
        self.assertFalse(json.loads((self.root / "auth.json").read_text())["pve_auth"])


class BackupServerAccounts(unittest.TestCase):
    """On a Proxmox Backup Server the same accounts are those of its own API:
    port 8007, `PBS:` tickets, the PBSAuthCookie of its web interface and the
    sections of /etc/proxmox-backup/user.cfg, which has no groups."""

    def setUp(self):
        patch = mock.patch.object(pve_auth, "_product", return_value=pve_auth.PRODUCTS["pbs"])
        patch.start()
        self.addCleanup(patch.stop)

    def test_only_tickets_of_this_product_are_tickets(self):
        self.assertTrue(pve_auth.is_ticket(PBS_AUDITOR))
        self.assertFalse(pve_auth.is_ticket(AUDITOR))
        self.assertEqual(pve_auth.cookie_name(), "PBSAuthCookie")

    def test_requests_go_to_the_backup_server_api(self):
        seen = {}

        class Answer:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, *args):
                return b'{"data": []}'

        def fake_urlopen(request, **kwargs):
            seen["url"], seen["cookie"] = request.full_url, request.get_header("Cookie")
            return Answer()

        with mock.patch.object(pve_auth.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(pve_auth._request("GET", "/access/domains", ticket=PBS_AUDITOR), (200, []))
        self.assertTrue(seen["url"].startswith("https://127.0.0.1:8007/api2/json/access/domains"))
        self.assertTrue(seen["cookie"].startswith("PBSAuthCookie=PBS%3Aauditor%40pbs"))

    def test_users_come_from_the_backup_server_file(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Path(directory) / "user.cfg"
            cfg.write_text("user: root@pam\n\temail root@localhost\n\n"
                           "token: root@pam!monitor\n\n"
                           "user: auditor@pbs\n\tcomment Read only\n")
            with mock.patch.dict(pve_auth.PRODUCTS["pbs"], {"users": str(cfg)}):
                pve_auth._directory["mtime"] = None
                self.assertEqual(pve_auth.directory(), {"users": ["auditor@pbs", "root@pam"], "groups": []})
                self.assertEqual(pve_auth.groups_of("auditor@pbs"), set())

    def test_the_second_factor_answers_a_challenge_of_this_product(self):
        with mock.patch.object(pve_auth, "_request", return_value=(401, None)) as request:
            with self.assertRaises(pve_auth.PVEAuthError):
                pve_auth.second_factor("auditor@pbs", CHALLENGE, "123456")
            request.assert_not_called()
            with self.assertRaises(pve_auth.PVEAuthError):
                pve_auth.second_factor("auditor@pbs", CHALLENGE.replace("PVE:", "PBS:", 1), "123456")
            request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
