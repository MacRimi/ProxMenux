"""The Monitor serves the dark-theme version of the catalog's black icons."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import lxc_apps


class IconThemesTests(unittest.TestCase):
    def themes(self, applications):
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.json"
            index.write_text(json.dumps({"applications": applications}))
            with patch.object(lxc_apps, "_OCI_CATALOG_INDEX", str(index)), \
                    patch.object(lxc_apps, "_oci_icon_themes_cache", None):
                return lxc_apps.oci_icon_themes()

    def test_black_icons_are_keyed_by_the_icon_they_replace(self):
        self.assertEqual(self.themes([
            {"id": "a", "icon": "https://icons.invalid/a.webp", "icon_dark": "https://icons.invalid/a-light.webp"},
            {"id": "b", "icon": "https://icons.invalid/b.png", "icon_dark": "invert"},
            {"id": "c", "icon": "https://icons.invalid/c.webp"},
        ]), {"https://icons.invalid/a.webp": "https://icons.invalid/a-light.webp",
             "https://icons.invalid/b.png": "invert"})

    def test_only_https_icons_and_known_values_are_served(self):
        self.assertEqual(self.themes([
            {"id": "a", "icon": "http://icons.invalid/a.webp", "icon_dark": "invert"},
            {"id": "b", "icon": "https://icons.invalid/b.webp", "icon_dark": "javascript:alert(1)"},
            {"id": "c", "icon": "https://icons.invalid/c.webp", "icon_dark": "http://icons.invalid/c.webp"},
            None,
        ]), {})

    def test_a_missing_or_broken_catalog_serves_nothing(self):
        with patch.object(lxc_apps, "_OCI_CATALOG_INDEX", "/nonexistent/index.json"), \
                patch.object(lxc_apps, "_oci_icon_themes_cache", None):
            self.assertEqual(lxc_apps.oci_icon_themes(), {})


if __name__ == "__main__":
    unittest.main()
