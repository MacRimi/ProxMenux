"""Every application names its category as catalog/categories.json does, so the
Catalog tab, the menu and their translations list it under that one name."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"


class CategoryLabelTests(unittest.TestCase):
    def setUp(self):
        self.labels = json.loads((CATALOG / "categories.json").read_text(encoding="utf-8"))["labels"]

    def test_every_template_names_its_category_as_categories_json(self):
        wrong = []
        for folder in ("apps", "curated"):
            for path in sorted((CATALOG / folder).glob("*.json")):
                ui = json.loads(path.read_text(encoding="utf-8")).get("catalog_ui", {})
                category, label = ui.get("category"), ui.get("category_label")
                if category not in self.labels:
                    wrong.append(f"{folder}/{path.name}: unknown category {category!r}")
                elif label != self.labels[category]:
                    wrong.append(f"{folder}/{path.name}: {label!r} instead of {self.labels[category]!r}")
        self.assertEqual(wrong, [])

    def test_every_index_entry_names_its_category_as_categories_json(self):
        index = json.loads((CATALOG / "index.json").read_text(encoding="utf-8"))
        wrong = [
            f"{item['id']}: {item.get('category_label')!r}"
            for item in index["applications"]
            if item.get("category") in self.labels and item.get("category_label") != self.labels[item["category"]]
        ]
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
