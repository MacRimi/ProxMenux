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
import managed_installs


class IconThemesTests(unittest.TestCase):
    def themes(self, applications):
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.json"
            index.write_text(json.dumps({"applications": applications}))
            with patch.object(lxc_apps, "_OCI_CATALOG_INDEX", str(index)), \
                    patch.object(lxc_apps, "_oci_icon_themes_cache", None), \
                    patch.object(managed_installs, "_fetch_helpers_cache", return_value=getattr(self, "helpers", {})):
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
                patch.object(lxc_apps, "_oci_icon_themes_cache", None), \
                patch.object(managed_installs, "_fetch_helpers_cache", return_value={}):
            self.assertEqual(lxc_apps.oci_icon_themes(), {})

    def test_community_scripts_logos_are_served_too(self):
        self.helpers = {
            "cockpit": {"logo": "https://icons.invalid/cockpit.webp", "logo_dark": "https://icons.invalid/cockpit-light.webp"},
            "plain": {"logo": "https://icons.invalid/plain.webp", "logo_dark": ""},
            "same": {"logo": "https://icons.invalid/a.webp", "logo_dark": "invert"},
        }
        self.assertEqual(self.themes([
            {"id": "a", "icon": "https://icons.invalid/a.webp", "icon_dark": "https://icons.invalid/a-light.webp"},
        ]), {"https://icons.invalid/a.webp": "https://icons.invalid/a-light.webp",
             "https://icons.invalid/cockpit.webp": "https://icons.invalid/cockpit-light.webp"})


class ActiveCatalogTests(unittest.TestCase):
    """The Monitor reads the catalog the engine uses, refreshed or shipped."""

    def resolve(self, run):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "engine/src").mkdir(parents=True)
            (root / "engine/catalog").mkdir()
            (root / "engine/catalog/index.json").write_text("{}")
            snapshot = root / "catalog-cache/snapshots/abc"
            snapshot.mkdir(parents=True)
            (snapshot / "index.json").write_text("{}")
            with patch.object(lxc_apps, "_OCI_ENGINE_DIR", str(root / "engine")), \
                    patch.object(lxc_apps, "_OCI_CATALOG_INDEX", str(root / "engine/catalog/index.json")), \
                    patch.object(lxc_apps, "_oci_catalog_dir_cache", None), \
                    patch.object(lxc_apps.subprocess, "run", side_effect=lambda *a, **k: run(snapshot)):
                return lxc_apps.oci_catalog_dir(), root

    def test_a_refreshed_catalog_is_the_one_read(self):
        found, root = self.resolve(lambda snapshot: type("R", (), {"returncode": 0, "stdout": f"{snapshot}\n"})())
        self.assertEqual(found, str(root / "catalog-cache/snapshots/abc"))

    def test_the_shipped_catalog_is_kept_when_the_engine_does_not_answer(self):
        def fail(snapshot):
            raise lxc_apps.subprocess.TimeoutExpired("python3", 15)
        found, root = self.resolve(fail)
        self.assertEqual(found, str(root / "engine/catalog"))

    def test_an_answer_without_a_catalog_is_ignored(self):
        found, root = self.resolve(lambda snapshot: type("R", (), {"returncode": 0, "stdout": "/nonexistent\n"})())
        self.assertEqual(found, str(root / "engine/catalog"))


if __name__ == "__main__":
    unittest.main()
