"""The same application from several sources is one group of the Catalog tab
and has one category, that of its OCI image; the groups of categories.json
join the ones whose names differ."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import catalog_tab  # noqa: E402

OCI = [
    {"id": "syncthing", "title": "Syncthing", "provider": "linuxserver.io", "category_label": "Files & Sharing"},
    {"id": "crafty", "title": "Crafty", "provider": "other", "category_label": "Gaming & Leisure"},
    {"id": "open-webui", "title": "Open WebUI", "provider": "other", "category_label": "AI / Coding & Dev-Tools"},
    {"id": "open-webui-cuda", "title": "Open WebUI CUDA", "provider": "other", "category_label": "Tools"},
    {"id": "transmission", "title": "Transmission", "provider": "other", "category_label": "Downloads"},
    {"id": "deluge", "title": "Deluge", "provider": "other", "category_label": "Files & Downloads"},
]
SCRIPTS_CS = [
    {"slug": "syncthing", "name": "Syncthing", "type": "lxc", "category_names": ["Files & Downloads"]},
    {"slug": "crafty-controller", "name": "Crafty Controller", "type": "lxc", "category_names": ["Gaming & Leisure"]},
    {"slug": "openwebui", "name": "Open WebUI", "type": "lxc", "category_names": ["AI / Coding & Dev-Tools"]},
    {"slug": "plex", "name": "Plex Media Server", "type": "lxc", "category_names": ["Media & Streaming"]},
    {"slug": "transmission", "name": "Transmission", "type": "lxc", "category_names": ["Files & Downloads"]},
    {"slug": "minio", "name": "MinIO", "type": "lxc", "category_names": ["Files & Downloads"]},
    {"slug": "aria2", "name": "Aria2", "type": "lxc", "category_names": ["Files & Downloads"]},
    {"slug": "zimaos-vm", "name": "ZimaOS", "type": "vm", "category_names": ["Miscellaneous"]},
    {"slug": "cap", "name": "Cap", "type": "lxc", "category_names": ["Media & Streaming"]},
    {"slug": "cap-captcha", "name": "Cap", "type": "lxc", "category_names": ["Authentication & Security"]},
]
MENU_VMS = [{"key": "zimaos", "name": "ZimaOS", "group": "app", "category": "Operating Systems & Appliances",
             "description": "ZimaOS VM"}]
SAME = [["oci:crafty", "cs:crafty-controller"], ["oci:open-webui", "oci:open-webui-cuda"]]


class SameApplicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "categories.json").write_text(json.dumps({
            "labels": {"downloads": "Downloads"}, "same_application": SAME,
            "community_scripts": {"aria2": "downloads"}, "distinct_application": ["cs:cap-captcha"]}))
        index = [dict(i, hidden=False, automatic_install_candidate=True, architectures=["amd64"]) for i in OCI]
        entries = [dict(e, has_arm=False, execute_in=[]) for e in SCRIPTS_CS]
        for patch in (
                mock.patch.object(catalog_tab.lxc_apps, "oci_catalog_dir", return_value=str(root)),
                mock.patch.object(catalog_tab, "_oci_index", return_value=index),
                mock.patch.object(catalog_tab, "_scripts_raw", return_value=entries),
                mock.patch.object(catalog_tab, "_host_architecture", return_value="amd64"),
                mock.patch.object(catalog_tab, "_product", return_value="pve"),
                mock.patch.object(catalog_tab, "_translations", return_value={}),
                mock.patch.object(catalog_tab, "_sections", return_value=[]),
                mock.patch.object(catalog_tab, "_options", return_value=MENU_VMS),
                mock.patch.object(catalog_tab, "_catalog_recipes", return_value=({}, {}, {})),
                mock.patch.object(catalog_tab, "_shot", return_value=""),
                mock.patch.object(catalog_tab, "_pocketbase", return_value={}),
                mock.patch.object(catalog_tab, "_refresh_catalog", return_value=False)):
            patch.start()
            self.addCleanup(patch.stop)
        self.items = {i["key"]: i for i in catalog_tab.list_items("en")["items"]}

    def test_the_same_name_takes_the_category_of_the_oci_image(self):
        self.assertEqual(self.items["cs:syncthing"]["category"], "Files & Sharing")
        self.assertEqual(self.items["cs:syncthing"]["same"], self.items["oci:syncthing"]["same"])

    def test_a_listed_group_joins_names_that_differ(self):
        self.assertEqual(self.items["cs:crafty-controller"]["same"], self.items["oci:crafty"]["same"])

    def test_a_name_of_a_listed_group_brings_the_other_sources_with_it(self):
        group = {self.items[k]["same"] for k in ("oci:open-webui", "oci:open-webui-cuda", "cs:openwebui")}
        self.assertEqual(len(group), 1)
        # The first image the group names sets the category of all of them.
        self.assertEqual(self.items["oci:open-webui-cuda"]["category"], "AI / Coding & Dev-Tools")

    def test_an_application_only_one_source_has_keeps_its_category(self):
        self.assertEqual(self.items["cs:plex"]["category"], "Media & Streaming")

    def test_downloads_hold_only_download_clients(self):
        self.assertEqual(self.items["cs:transmission"]["category"], "Downloads")
        self.assertEqual(self.items["cs:aria2"]["category"], "Downloads")
        # Storage Community Scripts files with downloads is listed with sharing.
        self.assertEqual(self.items["cs:minio"]["category"], "Files & Sharing")
        # A catalog not yet refreshed still names the category as before.
        self.assertEqual(self.items["oci:deluge"]["category"], "Downloads")

    def test_without_an_oci_image_the_vm_of_the_menu_sets_the_category(self):
        self.assertEqual(self.items["cs:zimaos-vm"]["same"], self.items["pmx:zimaos"]["same"])
        self.assertEqual(self.items["cs:zimaos-vm"]["category"], "Operating Systems & Appliances")

    def test_applications_that_only_share_a_name_stay_apart(self):
        self.assertNotEqual(self.items["cs:cap"]["same"], self.items["cs:cap-captcha"]["same"])
        self.assertEqual(self.items["cs:cap-captcha"]["category"], "Authentication & Security")

    def test_the_sheet_shows_the_same_category_as_the_card(self):
        self.assertEqual(catalog_tab.item_detail("cs", "syncthing", "en")["category"], "Files & Sharing")


if __name__ == "__main__":
    unittest.main()
