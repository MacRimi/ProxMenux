"""The health blueprint needs a session or an API token, except the health
word of /api/system-info that status checkers read: without them it carries
no host name, uptime or security details."""

import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "flask_health_routes.py"
GUARDS = {"require_auth", "require_admin_scope"}


def name(node):
    if isinstance(node, ast.Call):
        node = node.func
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)


class HealthRoutesAuthTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        self.routes = {node.name: node for node in ast.walk(self.tree)
                       if isinstance(node, ast.FunctionDef) and "route" in [name(d) for d in node.decorator_list]}

    def test_every_other_health_route_is_guarded(self):
        self.assertGreater(len(self.routes), 10)
        open_routes = [n for n, node in self.routes.items()
                       if not GUARDS & {name(d) for d in node.decorator_list}]
        self.assertEqual(open_routes, ["get_system_info"])

    def test_system_info_without_permission_returns_only_the_health_word(self):
        body = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), self.routes["get_system_info"])
        self.assertIn("permission_error('view') is not None", body)
        self.assertIn("return jsonify({'health': {'status':", body)
        self.assertLess(body.index("permission_error('view')"), body.index("return jsonify(info)"))


if __name__ == "__main__":
    unittest.main()
