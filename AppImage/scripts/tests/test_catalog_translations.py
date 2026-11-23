"""The Catalog tab translates the texts of a refreshed catalog with the
translations that catalog brought, over the installed language file."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import catalog_tab  # noqa: E402


class CatalogTranslationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        (root / "lang").mkdir()
        (root / "lang/es.json").write_text(json.dumps({"Old tagline": "Frase antigua", "Shared": "Instalada"}))
        self.snapshot = root / "snapshot"
        (self.snapshot / "lang").mkdir(parents=True)
        (self.snapshot / "lang/es.json").write_text(json.dumps({"New tagline": "Frase nueva", "Shared": "Nueva",
                                                                "Empty": ""}))
        for target, value in ((catalog_tab, "_LANG_DIR"), (catalog_tab, "_lang_cache")):
            patcher = mock.patch.object(target, value, str(root / "lang") if value == "_LANG_DIR" else {})
            patcher.start()
            self.addCleanup(patcher.stop)

    def table(self, language, catalog):
        with mock.patch.object(catalog_tab.lxc_apps, "oci_catalog_dir", return_value=str(catalog)):
            return catalog_tab._translations(language)

    def test_the_refreshed_catalog_translations_win(self):
        table = self.table("es", self.snapshot)
        self.assertEqual(table["New tagline"], "Frase nueva")
        self.assertEqual(table["Shared"], "Nueva")
        self.assertEqual(table["Old tagline"], "Frase antigua")
        self.assertNotIn("Empty", table)

    def test_the_bundled_catalog_uses_the_installed_file(self):
        table = self.table("es", self.snapshot.parent / "bundled")
        self.assertEqual(table, {"Old tagline": "Frase antigua", "Shared": "Instalada"})

    def test_english_and_odd_languages_have_no_table(self):
        self.assertEqual(self.table("en", self.snapshot), {})
        self.assertEqual(self.table("../es", self.snapshot), {})


if __name__ == "__main__":
    unittest.main()
