"""English safety contract at isolated producer seams; no host-module imports.

Run: python3 -m unittest discover -s tests -p test_audit_safety_wording.py -v
The external boot-tool mount behaviour is documented in the review evidence;
these fixtures exercise ProxMenux's actual command selection and evidence text.
"""
import ast
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCOPE = (
    "The assessment inspects host settings and health. It can write reports and "
    "logs; boot status checks can temporarily mount EFI system partitions."
)
BOOT_EFFECT = (
    "proxmox-boot-tool status can temporarily mount EFI system partitions; "
    "no boot is attempted."
)


def boot_check(present, output):
    """Extract only the check and its two pure helpers, with all I/O replaced."""
    source = ROOT / "AppImage/scripts/audit_checks_pve.py"
    tree = ast.parse(source.read_text())
    names = {"_boot_loader", "_version_key", "_unverified"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == names
    for node in nodes:
        node.decorator_list = []
    commands = []

    def path(value):
        assert value == "/etc/kernel/proxmox-boot-uuids", value
        return SimpleNamespace(exists=lambda: present)

    def run(argv, **kwargs):
        commands.append((argv, kwargs))
        if argv == ["proxmox-boot-tool", "status"]:
            return 0, output
        if argv == ["uname", "-r"]:
            return 0, "6.8.12-1-pve"
        raise AssertionError(f"Unmocked command: {argv}")

    env = {"Path": path, "re": re, "json": json,
           "CLASS_CONFORMANT": "conformant", "CLASS_WARNING": "warning",
           "CLASS_OBSERVATION": "observation", "CLASS_UNVERIFIED": "unverified"}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), env)
    return env["_boot_loader"](SimpleNamespace(run=run)), commands


class SafetyWording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads((ROOT / "AppImage/messages/en/common.json").read_text())["audit"]

    def test_boot_evidence_and_rationale_disclose_command_side_effect(self):
        for partitions in (1, 2):
            with self.subTest(partitions=partitions):
                output = "\n".join(
                    f"ABCD-000{i} is configured with: uefi (versions: 6.8.12-1-pve)"
                    for i in range(partitions))
                result, commands = boot_check(True, output)
                self.assertEqual(commands, [
                    (["proxmox-boot-tool", "status"], {"timeout": 25, "allowed_codes": (0, 1)}),
                    (["uname", "-r"], {}),
                ])
                self.assertTrue(result["evidence"].endswith(BOOT_EFFECT), result["evidence"])
                self.assertTrue(self.audit["checks"]["system"]["boot_loader"]["rationale"].endswith(BOOT_EFFECT))
                self.assertEqual(result["summary_params"]["total"], str(partitions))

    def test_absent_boot_configuration_does_not_invoke_tool(self):
        result, commands = boot_check(False, "")
        self.assertIsNone(result)
        self.assertEqual(commands, [])

    def test_unreadable_boot_status_does_not_claim_success(self):
        result, commands = boot_check(True, "E: no configured partitions")
        self.assertEqual(result["classification"], "unverified")
        self.assertEqual(len(commands), 1)

    def test_all_english_scope_surfaces_share_bounded_contract(self):
        # The document currently consumes presentation.readOnlyScope;
        # document.scopeReadOnly is retained for existing consumers.
        for text in (self.audit["readOnlyNotice"],
                     self.audit["presentation"]["readOnlyScope"],
                     self.audit["document"]["scopeReadOnly"]):
            self.assertEqual(text, SCOPE)


if __name__ == "__main__":
    unittest.main()
