"""verification.json applies when the catalog loads, without regenerating templates."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci import cli
from proxmenux_oci.catalog import Catalog


class VerificationAtLoadTests(unittest.TestCase):
    def catalog(self, applications, verification):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "catalog").mkdir()
        files = {"index.json": {"applications": applications},
                 "categories.json": {"applications": {}, "labels": {}},
                 "verification.json": {"applications": verification}}
        for name, data in files.items():
            (root / "catalog" / name).write_text(json.dumps(data), encoding="utf-8")
        return {item["id"]: item for item in Catalog(root).load_index()["applications"]}

    def test_new_entries_show_as_verified(self):
        items = self.catalog(
            [{"id": "glances", "automatic_install_candidate": True},
             {"id": "2fauth", "automatic_install_candidate": True},
             {"id": "legacy", "automatic_install_candidate": False},
             {"id": "plex", "automatic_install_candidate": True}],
            {"glances": {"community_tested": {"by": "Vaso73", "date": "2026-09-27",
                                              "report": "https://github.com/MacRimi/ProxMenux/issues/400"}},
             "2fauth": {"status": "laboratory-validated"},
             "legacy": {"status": "laboratory-validated"}})
        self.assertTrue(cli.is_tested(items["glances"]))
        self.assertEqual(items["glances"]["community_tested"]["report"],
                         "https://github.com/MacRimi/ProxMenux/issues/400")
        self.assertTrue(cli.is_tested(items["2fauth"]))
        self.assertFalse(cli.is_tested(items["legacy"]))
        self.assertFalse(cli.is_tested(items["plex"]))

    def test_removed_community_entry_no_longer_shows(self):
        items = self.catalog([{"id": "glances", "automatic_install_candidate": True,
                               "community_tested": {"by": "Vaso73", "date": "2026-09-27"}}], {})
        self.assertNotIn("community_tested", items["glances"])
        self.assertFalse(cli.is_tested(items["glances"]))


if __name__ == "__main__":
    unittest.main()
