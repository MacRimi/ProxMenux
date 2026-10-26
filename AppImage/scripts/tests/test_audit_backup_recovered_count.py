"""Offline backup-summary regressions; never import the administrative module.

Run: python3 -m unittest discover -s AppImage/scripts/tests -p test_audit_backup_recovered_count.py -v
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "audit_checks_pve.py"


def load_check(source=SOURCE):
    tree = ast.parse(source.read_text())
    names = {"_backup_job_results", "_unverified"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == names
    for node in nodes:
        node.decorator_list = []
    env = {"json": json, "CLASS_WARNING": "WARNING",
           "CLASS_OBSERVATION": "OBSERVATION", "CLASS_CONFORMANT": "CONFORMANT",
           "CLASS_UNVERIFIED": "UNVERIFIED"}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), env)
    return env["_backup_job_results"]


def evaluate(tasks=None, *, response=None, check=None):
    calls = []

    def run(argv, **kwargs):
        assert argv == ["pvesh", "get", "/nodes/fixture/tasks", "--typefilter",
                        "vzdump", "--limit", "200", "--output-format", "json"], argv
        assert kwargs == {"timeout": 30}, kwargs
        calls.append(argv)
        return response if response is not None else (0, json.dumps(tasks))

    result = (check or load_check())(SimpleNamespace(node="fixture", run=run))
    assert len(calls) == 1, calls
    return result


def runs(vmid, statuses, **extra):
    return [{"type": "vzdump", "id": vmid, "status": status, "starttime": i,
             "upid": f"UPID:fixture:0001:0001:{i:08x}:vzdump:{vmid}:root@pam:",
             **extra} for i, status in enumerate(statuses.split(), 1)]


class BackupRecoveredCountTests(unittest.TestCase):
    def assert_summary(self, tasks, count, total, history, key="recovered", incomplete=False):
        result = evaluate(tasks)
        self.assertEqual(result["summary_key"], key)
        self.assertEqual(result["summary_params"], {"count": str(count), "total": str(total)})
        self.assertEqual(result["incomplete"], incomplete)
        healed = [r for r in result["affected"] if r["reason_key"] == "backupRunRecovered"]
        self.assertEqual([r["when"] for r in healed], history)
        self.assertTrue(all(r["classification"] == "OBSERVATION" for r in healed))
        self.assertIn(f"earlier failures a later run cleared: {len(history)}\n", result["evidence"])
        return result

    def test_repeated_recoveries_count_one_guest_keep_both_events(self):
        tasks = runs(101, "ERROR OK ERROR OK")
        result = self.assert_summary(tasks, 1, 1, [1, 3])
        self.assertEqual([r["upid"] for r in result["affected"]], [tasks[0]["upid"], tasks[2]["upid"]])

    def test_repeated_recovery_plus_clean_guest_is_not_clamped_event_count(self):
        self.assert_summary(runs(101, "ERROR OK ERROR OK") + runs(102, "OK"), 1, 2, [1, 3])

    def test_single_recovery(self):
        self.assert_summary(runs(101, "ERROR OK"), 1, 1, [1])

    def test_two_recovered_guests(self):
        self.assert_summary(runs(101, "ERROR OK") + runs(102, "ERROR OK"), 2, 2, [1, 1])

    def test_repeated_failures_record_only_failure_cleared_by_success(self):
        self.assert_summary(runs(101, "ERROR ERROR OK ERROR ERROR OK"), 1, 1, [2, 5])

    def test_final_failure_retains_precedence_and_history(self):
        result = self.assert_summary(runs(101, "ERROR OK ERROR"), 1, 1, [1], key="someFailed")
        self.assertEqual(result["affected"][0]["when"], 3)
        self.assertEqual(result["affected"][0]["classification"], "WARNING")

    def test_other_guest_failure_retains_precedence(self):
        self.assert_summary(runs(101, "ERROR OK ERROR OK") + runs(102, "ERROR"),
                            1, 2, [1, 3], key="someFailed")

    def test_running_and_unknown_do_not_replace_completed_run(self):
        for status in ("running", "unknown", "", None):
            with self.subTest(status=status):
                tasks = runs(101, "ERROR OK") + [{**runs(101, "OK")[0], "starttime": 3, "status": status}]
                self.assert_summary(tasks, 1, 1, [1], incomplete=True)

    def test_upid_fallback_repeated_recovery(self):
        tasks = runs(101, "ERROR OK ERROR OK")
        for task in tasks:
            del task["id"]
        result = self.assert_summary(tasks, 1, 1, [1, 3])
        self.assertEqual([r["vmid"] for r in result["affected"]], [101, 101])

    def test_reverse_input_is_sorted_chronologically(self):
        self.assert_summary(list(reversed(runs(101, "ERROR OK ERROR OK"))), 1, 1, [1, 3])

    def test_zero_runs_and_nonbackup_tasks(self):
        self.assertIsNone(evaluate([]))
        self.assertIsNone(evaluate(runs(101, "ERROR", type="qmstart")))

    def test_all_successful_has_no_recovery(self):
        result = evaluate(runs(101, "OK OK") + runs(102, "OK"))
        self.assertEqual(result["summary_key"], "allSucceeded")
        self.assertEqual(result["summary_params"], {"total": "2"})
        self.assertEqual(result["classification"], "CONFORMANT")
        self.assertNotIn("affected", result)

    def test_unverified_collection_and_inventory(self):
        for response in ((1, "mock error"), (0, "not json"), (0, "{}"), (0, "[1]")):
            with self.subTest(response=response):
                self.assertEqual(evaluate(response=response), {
                    "classification": "UNVERIFIED", "summary_key": "evaluationFailed",
                    "incomplete": True, "evidence": response[1]})
        result = evaluate(runs(101, "unknown"))
        self.assertEqual(result["summary_key"], "evaluationFailed")
        self.assertTrue(result["incomplete"])

    def test_integer_and_string_ids_remain_distinct(self):
        result = self.assert_summary(runs(101, "ERROR OK") + runs("101", "ERROR OK"), 2, 2, [1, 1])
        self.assertEqual([r["vmid"] for r in result["affected"]], [101, "101"])

    def test_vm_and_ct_type_suffixes_do_not_change_existing_identity(self):
        tasks = runs(101, "ERROR OK", type="vzdump-qemu") + runs(102, "ERROR OK", type="vzdump-lxc")
        self.assert_summary(tasks, 2, 2, [1, 1])
        tasks = runs(101, "ERROR", type="vzdump-qemu") + [
            {**runs(101, "OK", type="vzdump-lxc")[0], "starttime": 2}]
        self.assert_summary(tasks, 1, 1, [1])

    def test_unknown_and_multiguest_identity_are_not_reinterpreted(self):
        # Existing identity contract: no expansion of a multi-guest task,
        # no inference of real guest counts from a missing/nonnumeric ID.
        for vmid, upid in ((None, "UPID:fixture:1:1:1:vzdump::root@pam:"),
                           (None, "malformed"), ("101,102", "batch")):
            with self.subTest(vmid=vmid, upid=upid):
                result = self.assert_summary(runs(vmid, "ERROR OK", upid=upid), 1, 1, [1])
                self.assertEqual(result["affected"][0]["vmid"], vmid)

    def test_explicit_id_takes_precedence_over_upid(self):
        tasks = runs(101, "ERROR OK", upid="UPID:fixture:1:1:1:vzdump:102:root@pam:")
        result = self.assert_summary(tasks, 1, 1, [1])
        self.assertEqual(result["affected"][0]["vmid"], 101)


if __name__ == "__main__":
    unittest.main()
