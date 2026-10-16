"""Characterize the shared pvesh cluster resources cache without Flask imports."""

import ast
import json
import subprocess
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


SERVER_SOURCE = Path(__file__).resolve().parents[1] / "flask_server.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "console"


def load_server_functions(*names):
    """Compile selected production functions without importing host-bound Flask state."""
    tree = ast.parse(SERVER_SOURCE.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    missing = set(names) - functions.keys()
    if missing:
        raise AssertionError(f"Missing production functions: {sorted(missing)}")
    module = ast.Module(body=[functions[name] for name in names], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(SERVER_SOURCE), "exec"), namespace)
    return namespace


class ClusterResourcesCacheTests(unittest.TestCase):
    def setUp(self):
        self.full = json.loads((FIXTURES / "pvesh_resources_full.json").read_text(encoding="utf-8"))
        self.vm = json.loads((FIXTURES / "pvesh_resources_vm.json").read_text(encoding="utf-8"))
        self.clock = Mock(return_value=100.0)
        self.run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(self.full)))
        self.server = load_server_functions(
            "get_cached_pvesh_cluster_resources", "get_cached_pvesh_cluster_resources_vm"
        )
        self.server.update({
            "_pvesh_cache": {
                "cluster_resources": None,
                "cluster_resources_vm_time": 0,
            },
            "_pvesh_cluster_resources_lock": threading.Lock(),
            "_PVESH_CACHE_TTL": 5,
            "time": SimpleNamespace(time=self.clock),
            "subprocess": SimpleNamespace(run=self.run),
            "json": json,
        })

    def full_resources(self):
        return self.server["get_cached_pvesh_cluster_resources"]()

    def vm_resources(self):
        return self.server["get_cached_pvesh_cluster_resources_vm"]()

    def test_one_pvesh_call_serves_full_and_vm_within_ttl(self):
        self.assertEqual(self.full_resources(), self.full)
        self.assertEqual(self.vm_resources(), self.vm)
        self.assertEqual(self.full_resources(), self.full)
        self.assertEqual(self.run.call_count, 1)
        self.run.assert_called_once_with(
            ["pvesh", "get", "/cluster/resources", "--output-format", "json"],
            capture_output=True, text=True, timeout=10,
        )

    def test_vm_filter_matches_type_vm_fixture_exactly_in_original_order(self):
        self.assertEqual(self.vm_resources(), self.vm)
        self.assertEqual([row["id"] for row in self.vm_resources()],
                         ["qemu/101", "lxc/205", "qemu/103"])
        self.assertEqual(self.run.call_count, 1)

    def test_failure_and_timeout_return_last_cache_or_empty_list(self):
        self.run.side_effect = [
            SimpleNamespace(returncode=1, stdout=""),
            subprocess.TimeoutExpired("pvesh", 10),
            SimpleNamespace(returncode=0, stdout=json.dumps(self.full)),
            subprocess.TimeoutExpired("pvesh", 10),
        ]
        self.assertEqual(self.full_resources(), [])
        self.assertEqual(self.vm_resources(), [])
        self.assertEqual(self.full_resources(), self.full)
        self.clock.return_value = 105.0
        self.assertEqual(self.vm_resources(), self.vm)
        self.assertEqual(self.run.call_count, 4)

    def test_concurrent_full_and_vm_reads_share_one_in_flight_call(self):
        entered = threading.Event()
        release = threading.Event()
        results = {}

        def slow_run(*_args, **_kwargs):
            entered.set()
            if not release.wait(2):
                raise AssertionError("pvesh fixture was not released")
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.full))

        self.run.side_effect = slow_run
        full_thread = threading.Thread(target=lambda: results.update(full=self.full_resources()))
        vm_thread = threading.Thread(target=lambda: results.update(vm=self.vm_resources()))
        full_thread.start()
        try:
            self.assertTrue(entered.wait(2))
            vm_thread.start()
        finally:
            release.set()
            full_thread.join(2)
            if vm_thread.ident is not None:
                vm_thread.join(2)

        self.assertFalse(full_thread.is_alive())
        self.assertFalse(vm_thread.is_alive())
        self.assertEqual(results, {"full": self.full, "vm": self.vm})
        self.assertEqual(self.run.call_count, 1)

    def test_ttl_expiry_triggers_exactly_one_refresh(self):
        self.assertEqual(self.vm_resources(), self.vm)
        self.clock.return_value = 104.999
        self.assertEqual(self.full_resources(), self.full)
        self.assertEqual(self.run.call_count, 1)
        self.clock.return_value = 105.0
        self.assertEqual(self.full_resources(), self.full)
        self.assertEqual(self.vm_resources(), self.vm)
        self.assertEqual(self.run.call_count, 2)

    def test_legacy_invalidation_timestamp_refreshes_shared_cache(self):
        self.assertEqual(self.full_resources(), self.full)
        self.server["_pvesh_cache"]["cluster_resources_vm_time"] = 0
        self.assertEqual(self.vm_resources(), self.vm)
        self.assertEqual(self.run.call_count, 2)

    def test_successful_empty_response_is_cached_for_ttl(self):
        self.run.return_value = SimpleNamespace(returncode=0, stdout="[]")
        self.assertEqual(self.full_resources(), [])
        self.assertEqual(self.vm_resources(), [])
        self.assertEqual(self.run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
