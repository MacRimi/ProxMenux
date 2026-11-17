"""An item of the Monitor's Catalog tab ends where its own flow does, and the
commands it runs get no variable that bash reads on its own: `pct` and `qm`
run in Perl's taint mode, which refuses to run any command with BASH_ENV set."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
UTILS = ROOT / "scripts" / "utils.sh"


class CatalogItemTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        menus = Path(temp.name) / "scripts" / "menus"
        menus.mkdir(parents=True)
        self.target, self.other = menus / "target.sh", menus / "other.sh"
        for script in (self.target, self.other):
            script.write_text(f'source "{UTILS}"\necho drawn\n')

    def run_menu(self, script, catalog=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith("PROXMENUX_CATALOG")}
        if catalog:
            env.update(PROXMENUX_CATALOG="1", PROXMENUX_CATALOG_TARGET=str(self.target))
        return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=30)

    def test_the_menu_the_item_opened_is_drawn(self):
        self.assertIn("drawn", self.run_menu(self.target).stdout)

    def test_any_other_menu_ends_instead_of_being_drawn(self):
        result = self.run_menu(self.other)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("drawn", result.stdout)

    def test_outside_the_catalog_every_menu_is_drawn(self):
        self.assertIn("drawn", self.run_menu(self.other, catalog=False).stdout)

    def test_the_item_passes_down_no_bash_env(self):
        launcher = (ROOT / "scripts" / "catalog" / "run_item.sh").read_text(encoding="utf-8")
        self.assertNotIn("export BASH_ENV", launcher)
        self.assertFalse((ROOT / "scripts" / "catalog" / "catalog_env.sh").exists())


if __name__ == "__main__":
    unittest.main()
