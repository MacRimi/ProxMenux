"""Pure regression tests: no imports that probe the host, no production writes."""
import ast
import re
import unittest
from types import SimpleNamespace
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "AppImage/scripts"


def functions(file, names):
    tree = ast.parse((SCRIPTS / file).read_text())
    wanted = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"re": re, "_WEEKDAYS": {day: i for i, day in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])},
                 "_SHORTHAND": {"daily": 86400, "weekly": 604800}}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), file, "exec"), namespace)
    return namespace


class AuditPresentationTests(unittest.TestCase):
    def test_enterprise_configuration_is_not_conformance(self):
        tree = ast.parse((SCRIPTS / "audit_checks_pve.py").read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_enterprise_repo")
        node.decorator_list = []
        ns = {"re": re, **{f"CLASS_{s.upper()}": s for s in ("observation", "conformant", "warning", "unverified")}}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "enterprise", "exec"), ns)
        check = ns["_enterprise_repo"]
        for source in ({}, {"pve.list": "# deb https://enterprise.proxmox.com/debian/pve stable pve-enterprise"},
                       {"pve.sources": "URIs: https://enterprise.proxmox.com/debian/pve\nEnabled: no\n"}):
            ctx = SimpleNamespace(apt_sources=source, run=lambda *_: self.fail("Disabled repository must not query subscription"))
            self.assertEqual(check(ctx)["classification"], "observation")
        for source in ({"pve.list": "deb https://enterprise.proxmox.com/debian/pve stable pve-enterprise"},
                       {"pve.sources": "URIs: https://enterprise.proxmox.com/debian/pve\nEnabled: yes\n"}):
            for rc, status, expected in [(0,"active","observation"), (0,"new","observation"),
                                         (0,"notfound","warning"), (0,"invalid","warning"),
                                         (0,"expired","warning"), (0,"suspended","warning"),
                                         (1,"active","unverified"), (0,"","unverified"),
                                         (0,"unexpected","unverified")]:
                with self.subTest(source=source, rc=rc, status=status):
                    ctx = SimpleNamespace(apt_sources=source, run=lambda *_: (rc, f"status: {status}"))
                    self.assertEqual(check(ctx)["classification"], expected)

    def test_lynis_current_message_and_details_are_distinct(self):
        parse = functions("security_manager.py", {"_parse_lynis_warning"})["_parse_lynis_warning"]
        row = parse("NETW-3015|Found promiscuous interface|tap106i0|text:upstream text|")
        self.assertEqual(row["description"], "Found promiscuous interface")
        self.assertEqual(row["details"], "tap106i0")
        self.assertEqual(row["severity"], "")
        self.assertEqual(parse("PKGS-7392|Actual warning|-|-|")["description"], "Actual warning")
        self.assertEqual(parse("PKGS-7392|Actual warning|-|-|")["details"], "")
        self.assertEqual(parse("OLD-0001|H|Legacy warning|legacy solution")["description"], "Legacy warning")
        self.assertIsNone(parse("broken"))

    def test_audit_does_not_surface_upstream_solutions(self):
        entry = functions("audit_checks_pve.py", {"_lynis_entry"})["_lynis_entry"]
        row = entry({"test_id": "NETW-3015", "description": "Found promiscuous interface", "details": "tap1", "solution": "DO SOMETHING"})
        self.assertNotIn("solution", row)
        self.assertEqual(row["details"], "tap1")

    def test_longest_gap_respects_each_scheduled_instant(self):
        names = {"_weekday_set", "_longest_gap", "_schedule_interval", "_schedule_age_limit"}
        ns = functions("audit_checks_pve.py", names)
        interval = ns["_schedule_interval"]
        for schedule, hours in [("sun 07:00", 168), ("sun 01:00,13:00", 156),
                                ("01:00,02:00", 23), ("01:00,01:00", 24),
                                ("mon..fri 07:00", 72), ("mon,wed 01:00", 120)]:
            with self.subTest(schedule=schedule):
                self.assertEqual(interval(schedule), hours * 3600)
        self.assertIsNone(interval("01:00:99"))
        self.assertIsNone(interval("mon..fri */2:00"))
        self.assertEqual(ns["_schedule_age_limit"]("sun 07:00"), 252 * 3600)


if __name__ == "__main__":
    unittest.main()
