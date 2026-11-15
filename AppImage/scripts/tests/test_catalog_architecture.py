"""On an ARM host the Catalog tab offers only what declares ARM support; an
amd64 host keeps every item."""
from pathlib import Path
import sys
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import catalog_tab  # noqa: E402

SCRIPTS_CS = {
    "adguard": {"slug": "adguard", "name": "AdGuard", "type": "lxc", "has_arm": True, "execute_in": []},
    "plex": {"slug": "plex", "name": "Plex", "type": "lxc", "has_arm": False, "execute_in": []},
}
OCI = [
    {"id": "jellyfin", "title": "Jellyfin", "architectures": ["amd64", "arm64"], "automatic_install_candidate": True},
    {"id": "frigate", "title": "Frigate", "architectures": ["amd64"], "automatic_install_candidate": True},
]


class CatalogArchitectureTests(unittest.TestCase):
    def listed(self, architecture):
        with mock.patch.object(catalog_tab, "_host_architecture", return_value=architecture), \
                mock.patch.object(catalog_tab, "_product", return_value="pve"), \
                mock.patch.object(catalog_tab, "_script_entries", return_value=SCRIPTS_CS), \
                mock.patch.object(catalog_tab, "_oci_index", return_value=OCI), \
                mock.patch.object(catalog_tab, "_translations", return_value={}), \
                mock.patch.object(catalog_tab, "_sections", return_value=[]), \
                mock.patch.object(catalog_tab, "_options", return_value=[]), \
                mock.patch.object(catalog_tab, "_catalog_recipes", return_value=({}, {}, {})), \
                mock.patch.object(catalog_tab, "_shot", return_value=""), \
                mock.patch.object(catalog_tab, "_refresh_catalog", return_value=False), \
                mock.patch.object(catalog_tab.lxc_apps, "oci_catalog_dir", return_value="/catalog/main"):
            return sorted(item["key"] for item in catalog_tab.list_items("en")["items"])

    def test_an_arm_host_is_offered_only_what_runs_on_arm(self):
        self.assertEqual(self.listed("arm64"), ["cs:adguard", "oci:jellyfin"])

    def test_an_amd64_host_keeps_every_item(self):
        self.assertEqual(self.listed("amd64"), ["cs:adguard", "cs:plex", "oci:frigate", "oci:jellyfin"])


class CatalogGpuTests(unittest.TestCase):
    """The sheet says what a recipe needs of a GPU, from the recipe itself."""

    def need(self, app_id):
        import json
        recipe = SCRIPTS.parents[1] / "oci" / "catalog" / "apps" / f"{app_id}.json"
        return catalog_tab._gpu_need(json.loads(recipe.read_text(encoding="utf-8")))

    def test_what_each_recipe_needs(self):
        self.assertEqual(self.need("open-webui-cuda"), "nvidia")
        self.assertEqual(self.need("plex-official"), "optional")
        self.assertEqual(self.need("ollama"), "optional")
        self.assertEqual(self.need("open-webui"), "")
        self.assertEqual(self.need("jellyfin"), "optional")
        self.assertEqual(self.need("convertx"), "")


if __name__ == "__main__":
    unittest.main()
