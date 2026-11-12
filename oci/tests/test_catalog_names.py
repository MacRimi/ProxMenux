"""Every image of a project is listed under the project's own name, spelt as
the project spells it; who publishes the image is shown apart."""

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"


def installable():
    index = json.loads((CATALOG / "index.json").read_text(encoding="utf-8"))
    return [a for a in index["applications"] if not a.get("hidden") and a.get("automatic_install_candidate")]


class CatalogNameTests(unittest.TestCase):
    def test_the_index_keeps_the_name_of_the_overlay(self):
        titles = {a["id"]: a["title"] for a in json.loads((CATALOG / "index.json").read_text(encoding="utf-8"))["applications"]}
        for path in sorted((CATALOG / "overlays").glob("*.json")):
            title = (json.loads(path.read_text(encoding="utf-8")).get("catalog_ui", {}).get("title") or {}).get("en_US")
            if title and path.stem in titles:
                self.assertEqual(titles[path.stem], title, path.stem)

    def test_no_name_says_it_is_the_official_image(self):
        self.assertEqual([a["title"] for a in installable() if re.search(r"\bofficial\b", a["title"], re.I)], [])

    def test_the_images_of_a_project_share_one_spelling(self):
        spellings = {}
        for app in installable():
            key = re.sub(r"[^a-z0-9]+", "", app["title"].casefold())
            spellings.setdefault(key, set()).add(app["title"])
        self.assertEqual({key: names for key, names in spellings.items() if len(names) > 1}, {})


if __name__ == "__main__":
    unittest.main()
