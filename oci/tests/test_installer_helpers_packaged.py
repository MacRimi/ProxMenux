"""Every helper the installer copies to its working folder finds the modules
it imports there: a module left out of the copy stops every installation with
ModuleNotFoundError before the container is created."""

import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT / "remote"
INSTALLER = (ROOT / "src/proxmenux_oci/installer.py").read_text(encoding="utf-8")


def packaged():
    """The remote files of each copy the installer makes: the helper lists,
    plus the files it copies one by one."""
    single = set(re.findall(r'"remote" / "([A-Za-z0-9_.]+)"', INSTALLER))
    single |= set(re.findall(r"'remote' / '([A-Za-z0-9_.]+)'", INSTALLER))
    single |= {"install_oci.sh", "install_generic_stack.py"}
    lists = re.findall(r"for helper in \(([^)]*)\):", INSTALLER)
    # The two full copies; the other lists only add the console helpers.
    return [set(re.findall(r"'([^']+)'", body)) | single for body in lists if "oci_instance_transaction.py" in body]


def module_imports(name):
    """The remote modules a file imports when it is loaded, not those imported
    inside a function."""
    tree = ast.parse((REMOTE / name).read_text(encoding="utf-8"))
    found = set()
    for node in tree.body:
        for item in ast.walk(node) if isinstance(node, (ast.If, ast.Try)) else [node]:
            if isinstance(item, ast.Import):
                found |= {alias.name.split(".")[0] + ".py" for alias in item.names}
            elif isinstance(item, ast.ImportFrom) and item.module and item.level == 0:
                found.add(item.module.split(".")[0] + ".py")
    return {module for module in found if (REMOTE / module).is_file()}


class PackagedHelpersTests(unittest.TestCase):
    def test_every_module_a_copied_helper_loads_is_copied_too(self):
        copies = packaged()
        self.assertTrue(copies)
        for copy in copies:
            loaded, pending = set(), [f for f in copy if f.endswith(".py") and (REMOTE / f).is_file()]
            while pending:
                for module in module_imports(pending.pop()):
                    if module not in loaded:
                        loaded.add(module)
                        pending.append(module)
            with self.subTest(copy=sorted(copy)[:3]):
                self.assertEqual(sorted(loaded - copy), [])


if __name__ == "__main__":
    unittest.main()
