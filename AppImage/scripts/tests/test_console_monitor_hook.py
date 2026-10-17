"""Check the Monitor console publisher glue without importing Flask."""

import ast
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


SERVER_SOURCE = Path(__file__).resolve().parents[1] / "flask_server.py"


def load_server_functions(*names):
    tree = ast.parse(SERVER_SOURCE.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in names}
    missing = set(names) - functions.keys()
    if missing:
        raise AssertionError(f"Missing production functions: {sorted(missing)}")
    module = ast.Module(body=[functions[name] for name in names], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"subprocess": subprocess, "json": json, "open": open}
    exec(compile(module, str(SERVER_SOURCE), "exec"), namespace)
    return namespace


class ConsoleMonitorHookTests(unittest.TestCase):
    def test_run_pvesh_uses_exact_command_and_parses_list(self):
        namespace = load_server_functions("_console_run_pvesh")
        expected = [{"type": "node", "name": "pve-01"}]
        run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(expected)))
        namespace["subprocess"] = SimpleNamespace(run=run)
        self.assertEqual(namespace["_console_run_pvesh"](), expected)
        run.assert_called_once_with(
            ["pvesh", "get", "/cluster/status", "--output-format", "json"],
            capture_output=True, text=True, timeout=10,
        )

    def test_run_pvesh_raises_on_nonzero_exit(self):
        namespace = load_server_functions("_console_run_pvesh")
        namespace["subprocess"] = SimpleNamespace(
            run=Mock(return_value=SimpleNamespace(returncode=1, stdout="[]")))
        with self.assertRaises(OSError):
            namespace["_console_run_pvesh"]()

    def test_read_language_handles_config_and_bad_documents(self):
        namespace = load_server_functions("_console_read_language")
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            namespace["open"] = lambda _path, **kwargs: config.open(**kwargs)
            self.assertIsNone(namespace["_console_read_language"]())
            for document, expected in (({"language": "es"}, "es"),
                                       ("invalid JSON", None),
                                       (["en"], None)):
                config.write_text(json.dumps(document) if not isinstance(document, str)
                                  else document, encoding="utf-8")
                self.assertEqual(namespace["_console_read_language"](), expected)

    def test_publisher_hook_is_module_level_and_guarded(self):
        tree = ast.parse(SERVER_SOURCE.read_text(encoding="utf-8"))
        expected_args = ["get_proxmox_node_name", "get_cached_pvesh_cluster_resources",
                         "_console_run_pvesh", "_console_read_language"]
        matches = []
        for node in tree.body:
            if not isinstance(node, ast.Try):
                continue
            calls = [child for statement in node.body for child in ast.walk(statement)
                     if isinstance(child, ast.Call)
                     and isinstance(child.func, ast.Attribute)
                     and child.func.attr == "ensure_publisher"]
            for call in calls:
                matches.append((node, call))
        self.assertEqual(len(matches), 1)
        guard, call = matches[0]
        self.assertTrue(any(isinstance(handler.type, ast.Name)
                            and handler.type.id == "Exception" for handler in guard.handlers))
        self.assertEqual([argument.id for argument in call.args], expected_args)
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        self.assertIsInstance(keywords["get_pve_version"], ast.Name)
        self.assertEqual(keywords["get_pve_version"].id, "get_proxmox_version")


if __name__ == "__main__":
    unittest.main()
