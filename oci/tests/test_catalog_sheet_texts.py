"""The catalog keeps two texts for an application: the short line of its card
and the longer description of its sheet. Every image of an application shows
the same two texts."""

import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog  # noqa: E402


def overlay_ui(app_id):
    path = CATALOG / "overlays" / f"{app_id}.json"
    return json.loads(path.read_text(encoding="utf-8")).get("catalog_ui", {}) if path.exists() else {}


def english(value):
    return (value or {}).get("en_US")


class CatalogSheetTextTests(unittest.TestCase):
    def test_the_card_takes_the_short_line_of_the_overlay(self):
        payload = {"applications": [{"id": "spoolman", "description": "Upstream summary."}]}
        Catalog(ROOT)._enrich_index_from_templates(payload)
        self.assertEqual(payload["applications"][0]["description"], english(overlay_ui("spoolman")["tagline"]))
        self.assertNotEqual(english(overlay_ui("spoolman")["tagline"]), english(overlay_ui("spoolman")["description"]))

    def test_the_index_shows_the_short_line(self):
        index = json.loads((CATALOG / "index.json").read_text(encoding="utf-8"))
        for app in index["applications"]:
            ui = overlay_ui(app["id"])
            expected = english(ui.get("tagline")) or english(ui.get("description"))
            if expected:
                self.assertEqual(app["description"], expected, app["id"])

    def test_every_image_of_an_application_has_the_same_texts(self):
        index = json.loads((CATALOG / "index.json").read_text(encoding="utf-8"))
        texts = {}
        for app in index["applications"]:
            if app.get("hidden") or not app.get("automatic_install_candidate"):
                continue
            recipe = CATALOG / (app.get("template") or "")
            recipe_ui = json.loads(recipe.read_text(encoding="utf-8")).get("catalog_ui", {}) if recipe.is_file() else {}
            text = english(overlay_ui(app["id"]).get("description")) or english(recipe_ui.get("description"))
            key = re.sub(r"[^a-z0-9]+", "", app["title"].casefold())
            texts.setdefault(key, {})[app["id"]] = (app["description"], text)
        differing = {key: ids for key, ids in texts.items() if len(set(ids.values())) > 1}
        self.assertEqual(differing, {})


if __name__ == "__main__":
    unittest.main()
