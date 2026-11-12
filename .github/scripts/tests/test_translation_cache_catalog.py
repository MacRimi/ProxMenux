"""The language cache collects what the Catalog tab shows of every OCI
application, while the terminal checks keep their own set of strings."""

import json
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
EXTRACT = runpy.run_path(str(ROOT / ".github/scripts/build_translation_cache.py"))["extract_catalog_texts"]


class CatalogDescriptionTexts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        catalog = Path(self.temporary.name)
        (catalog / "apps").mkdir()
        (catalog / "apps/demo.json").write_text(json.dumps({"catalog_ui": {
            "tagline": {"en_US": "A short tagline"},
            "description": {"en_US": "What the application is."},
            "tips": ["A note of the recipe."],
        }}))
        (catalog / "index.json").write_text(json.dumps({"applications": [
            {"id": "demo", "description": "The summary of its card."},
            {"id": "gone", "hidden": True, "description": "A hidden application."},
        ]}))
        self.catalog = catalog

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_terminal_set_keeps_the_tagline_only(self):
        texts = EXTRACT([self.catalog])
        self.assertIn("A short tagline", texts)
        for text in ("What the application is.", "A note of the recipe.", "The summary of its card."):
            self.assertNotIn(text, texts)

    def test_the_language_cache_also_takes_descriptions_and_notes(self):
        texts = EXTRACT([self.catalog], descriptions=True)
        for text in ("A short tagline", "What the application is.", "A note of the recipe.", "The summary of its card."):
            self.assertIn(text, texts)
        self.assertNotIn("A hidden application.", texts)


if __name__ == "__main__":
    unittest.main()
