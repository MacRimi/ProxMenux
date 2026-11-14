"""What each profile can do, route by route.

Every protected route of the Monitor needs one permission (permissions.py).
The routes are read from the modules as written, so a new one that is not
listed fails here; profiles are then applied through the real decorators and
the single-use tickets of the WebSockets and downloads."""
import ast
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from flask import Flask, jsonify

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth_manager  # noqa: E402
import permissions  # noqa: E402
from jwt_middleware import require_auth, require_admin_scope, require_admin_or_ticket  # noqa: E402
from test_access_modes import functions, PASSWORD  # noqa: E402

DECORATORS = {"require_auth", "require_admin_scope", "require_admin_or_ticket"}
ROUTE_CALLS = {"route": None, "get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE", "patch": "PATCH"}


def protected_routes():
    """(rule, method, decorator) of every route a decorator protects."""
    found = []
    for path in sorted(SCRIPTS.glob("flask_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prefix = ""
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Blueprint"):
                for keyword in node.keywords:
                    if keyword.arg == "url_prefix":
                        prefix = keyword.value.value
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            names = {d.id for d in node.decorator_list if isinstance(d, ast.Name)} & DECORATORS
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr in ROUTE_CALLS and decorator.args):
                    continue
                if getattr(decorator.func.value, "id", "") == "sock":
                    continue
                methods = [ROUTE_CALLS[decorator.func.attr] or "GET"]
                for keyword in decorator.keywords:
                    if keyword.arg == "methods":
                        methods = [element.value for element in keyword.value.elts]
                for method in methods:
                    for name in names:
                        found.append((prefix + decorator.args[0].value, method, name))
    return found


class RouteClassification(unittest.TestCase):
    routes = protected_routes()

    def test_the_inventory_finds_the_routes(self):
        self.assertGreater(len(self.routes), 300)

    def test_every_protected_route_is_listed(self):
        unlisted = sorted({(method, rule) for rule, method, _ in self.routes
                           if permissions.classify(rule, method) is None})
        self.assertEqual(unlisted, [], "add these routes to permissions.py")

    def test_nothing_protected_today_is_left_to_observers(self):
        # Changing state, or reading behind require_admin_scope, was never
        # for read-only access: it never needs only `view`.
        loose = sorted({(method, rule) for rule, method, decorator in self.routes
                        if (method != "GET" or decorator != "require_auth")
                        and permissions.classify(rule, method) == "view"})
        self.assertEqual(loose, [])

    def test_every_reading_belongs_to_areas(self):
        unlisted = sorted({rule for rule, method, _ in self.routes
                           if method == "GET" and permissions.classify(rule, method) == "view"
                           and permissions.read_areas(rule) is None})
        self.assertEqual(unlisted, [], "add these readings to _AREA in permissions.py")
        for areas in permissions._AREA.values():
            self.assertTrue(set(areas) <= set(permissions.AREAS), areas)

    def test_some_readings_and_their_areas(self):
        for rule, areas in (("/api/vms", {"general", "guests", "apps"}),
                            ("/api/vms/<int:vmid>/backups", {"guests"}),
                            ("/api/host-backups/jobs", {"backup"}),
                            ("/api/storage/summary", {"general"}),
                            ("/api/storage/smart/<disk_name>", {"node"}),
                            ("/api/node/metrics", {"general", "node"}),
                            ("/api/health/details", set()),
                            ("/api/auth/profile", set())):
            with self.subTest(rule=rule):
                self.assertEqual(set(permissions.read_areas(rule)), areas)
        self.assertEqual(permissions.required("/api/audit/runs", "GET"), "admin")

    def test_every_listed_rule_names_a_route(self):
        rules = {rule for rule, _, _ in self.routes}
        stale = [rule for rule in permissions._READING if rule not in rules]
        stale += [prefix for prefix in (*permissions._ACTION, *permissions._AREA)
                  if not any(rule == prefix or rule.startswith(prefix) for rule in rules)]
        self.assertEqual(stale, [])

    def test_some_routes_and_what_they_need(self):
        for rule, method, need in (
                ("/api/vms/<int:vmid>", "GET", "view"),
                ("/api/vms/<int:vmid>/control", "POST", "guests"),
                ("/api/vms/<int:vmid>/backup", "POST", "backup"),
                ("/api/vms/<int:vmid>/backups/delete", "POST", "backup"),
                ("/api/vms/<int:vmid>/bulk-update/plan", "POST", "update"),
                ("/api/oci/installed/<app_id>/update", "POST", "update"),
                ("/api/oci/installed/<app_id>/update-auth-key", "POST", "guests"),
                ("/api/oci/deploy", "POST", "execute"),
                ("/api/scripts/execute", "POST", "execute"),
                ("/api/host-backups/pbs-encryption/download-keyfile", "GET", "backup"),
                ("/api/notifications/settings", "GET", "admin"),
                ("/api/system/power/reboot", "POST", "admin"),
                ("/api/auth/profile", "PUT", permissions.SELF),
                ("/api/terminal/ticket", "POST", permissions.TICKET),
                ("/api/not-a-route", "POST", "admin")):
            with self.subTest(rule=rule, method=method):
                self.assertEqual(permissions.required(rule, method), need)


class Profiles(unittest.TestCase):
    def test_the_fixed_profiles(self):
        actions = set(permissions.ACTIONS)
        seen = {"view"} | {"area." + area for area in permissions.AREAS}
        self.assertEqual(permissions.permissions_of("admin"), seen | actions)
        self.assertEqual(permissions.permissions_of("observer"), seen)
        self.assertEqual(permissions.permissions_of("operator"), seen | actions - {"admin"})
        self.assertEqual(permissions.permissions_of("operator_no_terminal"),
                         seen | actions - {"admin", "terminal"})
        self.assertEqual(permissions.permissions_of("unknown"), set())

    def test_a_custom_profile_is_its_areas_and_actions_never_administering(self):
        profile = permissions.custom_profile(["backup", "general", "nowhere"], ["backup", "admin", "terminal"])
        self.assertEqual(profile, "custom:general,backup:backup,terminal")
        self.assertEqual(permissions.permissions_of(profile),
                         {"view", "area.general", "area.backup", "backup", "terminal"})
        self.assertIsNone(permissions.custom_profile([], ["backup"]))  # nothing to see
        self.assertEqual(permissions.permissions_of("custom:nowhere:"), set())
        seen = permissions.permissions_of("custom:backup:")
        self.assertTrue(permissions.allows(seen, "view", areas=("backup", "logs")))
        self.assertFalse(permissions.allows(seen, "view", areas=("guests",)))
        self.assertTrue(permissions.allows(seen, "view", areas=permissions.BASE))

    def test_special_needs(self):
        operator = permissions.permissions_of("operator_no_terminal")
        observer = permissions.permissions_of("observer")
        self.assertTrue(permissions.allows(operator, permissions.TICKET))
        self.assertFalse(permissions.allows(observer, permissions.TICKET))
        self.assertTrue(permissions.allows(observer, permissions.SELF, signed_in=True))
        self.assertFalse(permissions.allows(observer, permissions.SELF))  # read-only mode: no account


class Enforcement(unittest.TestCase):
    """A signed-in session with each profile, through the real decorators."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        patch = mock.patch.multiple(auth_manager, CONFIG_DIR=root, AUTH_CONFIG_FILE=root / "auth.json",
                                    SETUP_CODE_FILE=root / "monitor-setup-code")
        patch.start()
        self.addCleanup(patch.stop)
        auth_manager._invalidate_revoked_cache()
        self.assertTrue(auth_manager.setup_auth("admin", PASSWORD)[0])
        self.token = auth_manager.generate_token("admin")

        tickets = functions(SCRIPTS / "flask_terminal_routes.py", "_TERMINAL_TICKETS", "_TICKETS_LOCK",
                            "_TICKET_TTL", "_TICKET_MAX_INFLIGHT", "_issue_terminal_ticket",
                            "_consume_terminal_ticket", "_ws_auth_check",
                            permissions=permissions, secrets=__import__("secrets"),
                            threading=__import__("threading"), time=__import__("time"))
        self.tickets = tickets
        fake_module = types.ModuleType("flask_terminal_routes")
        fake_module._consume_terminal_ticket = tickets["_consume_terminal_ticket"]
        modules = mock.patch.dict(sys.modules, {"flask_terminal_routes": fake_module})
        modules.start()
        self.addCleanup(modules.stop)

        app = Flask(__name__)
        ok = lambda **_: jsonify(ok=True)
        for rule, method, decorator in (
                ("/api/vms/<int:vmid>", "GET", require_auth),
                ("/api/vms/<int:vmid>/control", "POST", require_auth),
                ("/api/system/power/reboot", "POST", require_admin_scope),
                ("/api/notifications/settings", "GET", require_admin_scope),
                ("/api/auth/profile", "PUT", require_auth),
                ("/api/host-backups/pbs-encryption/download-keyfile", "GET", require_admin_or_ticket),
                ("/api/host-backups/jobs", "GET", require_auth),
                ("/api/health", "GET", require_auth),
                ("/api/node/metrics", "GET", require_auth)):
            app.add_url_rule(rule, f"{method} {rule}", decorator(ok), methods=[method])

        from flask import g

        @app.route("/api/terminal/ticket", methods=["POST"])
        @require_admin_scope
        def ticket():
            return jsonify(ticket=tickets["_issue_terminal_ticket"](g.identity["permissions"]))

        self.client = app.test_client()

    def as_profile(self, profile):
        """The session of the account, as if its user had `profile`."""
        import jwt_middleware
        return mock.patch.object(jwt_middleware, "profile_for", lambda mode, username=None, scope=None: profile)

    def call(self, method, path, **kwargs):
        headers = {"Authorization": f"Bearer {self.token}"}
        return self.client.open(path, method=method, headers=headers, **kwargs).status_code

    def test_each_profile_reaches_what_it_may(self):
        expected = {
            "admin": (200, 200, 200, 200, 200),
            "operator": (200, 200, 403, 403, 200),
            "operator_no_terminal": (200, 200, 403, 403, 200),
            "observer": (200, 403, 403, 403, 200),
        }
        for profile, statuses in expected.items():
            with self.subTest(profile=profile), self.as_profile(profile):
                self.assertEqual((self.call("GET", "/api/vms/100"),
                                  self.call("POST", "/api/vms/100/control"),
                                  self.call("POST", "/api/system/power/reboot"),
                                  self.call("GET", "/api/notifications/settings"),
                                  self.call("PUT", "/api/auth/profile")), statuses)

    def test_a_custom_profile_reads_only_its_areas(self):
        with self.as_profile(permissions.custom_profile(["backup", "node"], ["backup"])):
            self.assertEqual((self.call("GET", "/api/host-backups/jobs"),   # backup
                              self.call("GET", "/api/node/metrics"),         # general or node
                              self.call("GET", "/api/health"),               # every page
                              self.call("GET", "/api/vms/100"),              # guests, apps, menux
                              self.call("POST", "/api/vms/100/control"),
                              self.call("PUT", "/api/auth/profile"),         # its own account
                              self.call("POST", "/api/terminal/ticket")),
                             (200, 200, 200, 403, 403, 200, 200))
        with self.as_profile(permissions.custom_profile(["general"], [])):
            self.assertEqual((self.call("GET", "/api/host-backups/jobs"), self.call("GET", "/api/node/metrics"),
                              self.call("POST", "/api/terminal/ticket")), (403, 200, 403))

    def test_a_ticket_carries_the_permissions_of_whoever_asked(self):
        with self.as_profile("operator_no_terminal"):
            ticket = lambda: self.client.post("/api/terminal/ticket",
                                              headers={"Authorization": f"Bearer {self.token}"}).json["ticket"]
            consume = self.tickets["_consume_terminal_ticket"]
            self.assertFalse(consume(ticket(), "terminal"))
            self.assertTrue(consume(ticket(), "execute"))
            download = self.client.get(f"/api/host-backups/pbs-encryption/download-keyfile?ticket={ticket()}")
            self.assertEqual(download.status_code, 200)
            once = ticket()
            self.assertTrue(consume(once, "update"))
            self.assertFalse(consume(once, "update"))  # single use
        with self.as_profile("observer"):
            self.assertEqual(self.call("POST", "/api/terminal/ticket"), 403)


if __name__ == "__main__":
    unittest.main()
