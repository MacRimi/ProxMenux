"""The search of the main menu finds an option of ProxMenux, an OCI application
or a Helper-Script by its name or by related words, and opens it where it
lives: the scripts it launches are the ones the menus launch."""

import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"


def load():
    spec = importlib.util.spec_from_file_location("search_menu", SCRIPTS / "menus/search_menu.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The repository in the place of the installed copy.
    module.BASE, module.SCRIPTS = ROOT, SCRIPTS
    module.OCI_INDEX = ROOT / "oci/catalog/index.json"
    module.HELPERS_CACHE = ROOT / "json/helpers_cache.json"
    module._translations = {}
    return module


class IndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((SCRIPTS / "menus/search_index.json").read_text(encoding="utf-8"))
        cls.spanish = json.loads((ROOT / "lang/es.json").read_text(encoding="utf-8"))

    def test_every_entry_opens_a_script_that_exists(self):
        missing = sorted({item["script"] for item in self.index if not (SCRIPTS / item["script"]).is_file()})
        self.assertEqual(missing, [])

    def test_every_title_is_a_text_the_menus_already_translate(self):
        names = {"ZimaOS", "Synology DSM"}
        unknown = [item["title"] for item in self.index
                   if item["title"] not in self.spanish and item["title"] not in names]
        self.assertEqual(unknown, [])
        self.assertEqual([item["menu"] for item in self.index if item["menu"] not in self.spanish], [])

    def test_every_script_a_pve_menu_launches_can_be_found(self):
        indexed = {item["script"] for item in self.index}
        launched = set()
        for menu in sorted((SCRIPTS / "menus").glob("*.sh")):
            # PBS replaces the PVE main menu and does not use its search.
            # The exclusive platform dispatch is executed in the test below.
            if menu.name in ("main_menu.sh", "lxc_menu.sh", "pbs_menu.sh"):
                continue
            launched |= set(re.findall(r'bash "\$LOCAL_SCRIPTS/([A-Za-z0-9_./-]+\.sh)"', menu.read_text()))
        launched -= {"menus/main_menu.sh"}
        # Opened from their own menu, which is what the index points at.
        launched -= {"post_install/auto_post_install.sh", "utilities/proxmox_update.sh", "utilities/upgrade_pve8_to_pve9.sh"}
        self.assertEqual(sorted(launched - indexed), [])

    def test_pbs_replaces_the_searchable_pve_menu(self):
        menu = (SCRIPTS / "menus/main_menu.sh").read_text()
        dispatch = menu[menu.rindex('source "$LOCAL_SCRIPTS/global/platform-functions.sh"'):]
        with tempfile.TemporaryDirectory() as directory:
            scripts = Path(directory)
            (scripts / "global").mkdir()
            (scripts / "menus").mkdir()
            helper = scripts / "global/platform-functions.sh"
            helper.write_text(
                "source " + shlex.quote(str(SCRIPTS / "global/platform-functions.sh")) + "\n"
                'pmx_platform_field() { printf "%s" "$TEST_PROXMENUX_PRODUCT"; }\n')
            (scripts / "menus/pbs_menu.sh").write_text('printf "PBS menu\\n"\n')
            harness = 'show_menu() { printf "PVE search menu\\n"; }\n' + dispatch
            for product, expected in (("pve", "PVE search menu"), ("pbs", "PBS menu")):
                with self.subTest(product=product):
                    result = subprocess.run(["bash", "-e", "-c", harness], text=True, capture_output=True,
                                            env={**os.environ, "LOCAL_SCRIPTS": str(scripts),
                                                 "TEST_PROXMENUX_PRODUCT": product})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)

    def test_the_main_menu_offers_the_search_and_opens_what_it_hands_back(self):
        menu = (SCRIPTS / "menus/main_menu.sh").read_text()
        self.assertIn('search "$(translate "Search options and applications")"', menu)
        self.assertIn('search_menu.py" --handoff "$handoff"', menu)
        self.assertIn('[[ "${target[0]:-}" == "$LOCAL_SCRIPTS"/* && -f "${target[0]}" ]]', menu)
        self.assertIn('exec bash "${target[@]}"', menu)

    def test_an_option_inside_a_menu_names_one_that_menu_has(self):
        for item in self.index:
            argument = item.get("argument")
            if not argument:
                continue
            script = (SCRIPTS / item["script"]).read_text()
            self.assertIn("PRESELECTED_OPTION", script, item["script"])
            if not argument.isdigit():
                self.assertIn(argument, script, f"{item['script']}: {argument}")


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.search = load()
        cls.items = cls.search.catalog(refresh=False)

    def found(self, query):
        return self.search.search(self.items, query)

    def test_the_three_sources_are_in_the_catalog(self):
        self.assertEqual({item["source"] for item in self.items}, set(self.search.SOURCES))

    def test_proxmenux_comes_first_then_oci_then_helper_scripts(self):
        sources = [item["source"] for item in self.found("samba")]
        self.assertEqual(sources, sorted(sources, key=self.search.SOURCES.index))
        self.assertEqual(sources[0], "ProxMenux")

    def test_a_name_is_found_by_the_start_of_any_of_its_words(self):
        self.assertIn("Jellyfin", [item["title"] for item in self.found("jelly")])
        self.assertTrue(any(item["source"] == "OCI Manager" for item in self.found("plex")))

    def test_accents_and_case_do_not_matter(self):
        self.assertEqual([item["title"] for item in self.found("NVIDIA")],
                         [item["title"] for item in self.found("nvidia")])

    def test_related_words_find_an_option(self):
        self.assertTrue(any("NFS" in item["title"] for item in self.found("nfs storage")))
        self.assertTrue(any(item["action"][-1].endswith("fail2ban_installer.sh") for item in self.found("fail2ban")))

    def test_a_match_by_category_comes_after_the_names(self):
        matches = self.found("vpn")
        self.assertTrue(any(item["title"] == "Tailscale" for item in matches))
        by_category = False
        for item in matches:
            words = re.findall(r"[a-z0-9]+", self.search.fold(item["terms"]))
            in_name = any(word.startswith("vpn") for word in words)
            self.assertFalse(in_name and by_category)
            by_category = by_category or not in_name

    def test_an_application_is_not_found_by_what_its_description_mentions(self):
        titles = [item["title"] for item in self.found("plex")]
        self.assertNotIn("Jellyfin", titles)
        self.assertTrue(all("plex" in title.casefold() for title in titles))

    def test_nothing_matches_nothing(self):
        self.assertEqual(self.found("zzqqxx"), [])
        self.assertEqual(self.found("   "), [])

    def test_a_sub_menu_is_handed_back_to_the_main_menu(self):
        by_script = {item["action"][1]: item for item in self.items if item["source"] == "ProxMenux"}
        self.assertTrue(by_script[str(SCRIPTS / "menus/network_menu.sh")]["handoff"])
        self.assertFalse(by_script[str(SCRIPTS / "storage/format-disk.sh")]["handoff"])

    def test_an_option_inside_a_menu_is_given_to_that_menu(self):
        zfs = next(item for item in self.items if item["action"][1:] == [str(SCRIPTS / "help_info_menu.sh"), "7"])
        self.assertFalse(zfs["handoff"])
        language = next(item for item in self.items if item["action"][-1] == "change_language")
        self.assertEqual(language["action"][1], str(SCRIPTS / "menus/config_menu.sh"))
        self.assertTrue(language["handoff"])


class OpenedInPlaceTests(unittest.TestCase):
    def test_an_option_of_the_post_install_comes_selected(self):
        script = (SCRIPTS / "post_install/customizable_post_install.sh").read_text()
        self.assertIn('PRESELECTED_OPTION="${1:-}"', script)
        self.assertIn('--default-item "${preselected_item:-1}"', script)

    def test_a_utility_comes_selected(self):
        script = (SCRIPTS / "utilities/system_utils.sh").read_text()
        self.assertIn('PRESELECTED_UTILITY="${1:-}"', script)

    def test_a_helper_script_is_opened_on_its_own(self):
        script = (SCRIPTS / "menus/menu_Helper_Scripts.sh").read_text()
        self.assertIn('run_script_by_slug "$1"', script)

    def test_an_oci_application_opens_its_page(self):
        cli = (ROOT / "oci/src/proxmenux_oci/cli.py").read_text()
        self.assertIn('subparsers.add_parser("open"', cli)


class TranslationTests(unittest.TestCase):
    """What the search and the main menu say reaches the translation workflow,
    read with the folders the workflow itself passes."""

    @classmethod
    def setUpClass(cls):
        workflow = (ROOT / ".github/workflows/build-translation-cache.yml").read_text()
        extractor = runpy.run_path(str(ROOT / ".github/scripts/build_translation_cache.py"))
        folders = [ROOT / folder for folder in re.findall(r"--python-dir (\S+)", workflow)]
        cls.found = set(extractor["extract_python_texts"](folders))
        cls.found |= set(extractor["extract_translate_texts"](SCRIPTS))
        cls.triggers = workflow

    def test_every_text_of_the_search_is_found(self):
        source = (SCRIPTS / "menus/search_menu.py").read_text()
        said = set(re.findall(r"translate\('([^']+)'\)", source))
        self.assertIn("No results", said)
        self.assertEqual(sorted(said - self.found), [])

    def test_the_title_of_the_main_menu_is_found(self):
        self.assertIn("Main menu", self.found)

    def test_a_change_in_the_search_runs_the_workflow(self):
        self.assertIn("'scripts/**/*.py'", self.triggers)


if __name__ == "__main__":
    unittest.main()
