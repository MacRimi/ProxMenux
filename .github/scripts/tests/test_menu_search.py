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
import unittest.mock

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
        # Product names, which the menus show as they are.
        names = {"ZimaOS", "Synology DSM", "TrueNAS SCALE", "TrueNAS CORE", "OpenMediaVault", "XigmaNAS",
                 "Rockstor", "FygoOS", "Umbrel OS", "Home Assistant OS", "Docker VM", "Nextcloud VM",
                 "Windows (UUP Dump)", "Windows (ISO)", "Ubuntu", "Debian", "Fedora", "Arch Linux", "Rocky Linux",
                 "Linux Mint", "openSUSE", "Alpine Linux", "Kali Linux", "Manjaro", "Linux (ISO)",
                 "AlmaLinux", "CentOS Stream", "Oracle Linux", "Pop!_OS", "Zorin OS", "CachyOS", "NixOS",
                 "PVE Host Backup", "proxmox_toolbox", "proxsave"}
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
            if isinstance(argument, str) and not argument.isdigit():
                self.assertIn(argument, script, f"{item['script']}: {argument}")

    def test_a_system_named_after_its_type_is_one_its_selector_opens(self):
        selectors = {"1": "vm/select_nas_iso.sh", "2": "vm/select_windows_iso.sh",
                     "3": "vm/select_linux_iso.sh", "5": "vm/select_linux_iso.sh"}
        for item in self.index:
            argument = item.get("argument")
            if not isinstance(argument, list):
                continue
            self.assertEqual(item["script"], "menus/create_vm_menu.sh", item["title"])
            system_type, system = argument
            selector = (SCRIPTS / selectors[system_type]).read_text()
            self.assertRegex(selector, rf'(?m)(^\s*{re.escape(system)}\) |== "{re.escape(system)}")', item["title"])


class RegistryTests(unittest.TestCase):
    """Every VM the menu creates is an application of the Monitor's Catalog
    tab: its logo, category, summary and default settings."""

    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((SCRIPTS / "menus/search_index.json").read_text(encoding="utf-8"))
        cls.apps = [item for item in cls.index if item.get("group") == "app"]
        oci = json.loads((ROOT / "oci/catalog/index.json").read_text(encoding="utf-8"))
        helpers = json.loads((ROOT / "json/helpers_cache.json").read_text(encoding="utf-8"))
        cls.categories = {item.get("category_label") for item in oci.get("applications", [])}
        cls.categories |= {name for entry in helpers for name in entry.get("category_names") or []}

    def test_every_vm_the_menu_creates_is_an_application(self):
        creators = [item for item in self.index
                    if item["script"] in ("vm/synology.sh", "vm/zimaos.sh")
                    or isinstance(item.get("argument"), list)]
        self.assertGreater(len(creators), 20)
        self.assertEqual([item["title"] for item in creators if item.get("group") != "app"], [])

    def test_screenshots_are_secure_links_and_files_carry_their_credit(self):
        for item in self.index:
            if "screenshots" in item:
                with self.subTest(item["title"]):
                    self.assertIsInstance(item["screenshots"], list)
                    for shot in item["screenshots"]:
                        url = shot.get("url") if isinstance(shot, dict) else shot
                        self.assertTrue(str(url).startswith("https://"))
                        # A file taken from a library of free media names its
                        # author, its license and its page.
                        if "wikimedia.org" in str(url):
                            self.assertTrue(all(shot.get(key) for key in ("author", "license", "page")), url)

    def test_every_application_has_its_card(self):
        for item in self.apps:
            with self.subTest(item["title"]):
                self.assertEqual(item.get("type"), "vm")
                self.assertIn(item.get("category"), self.categories)
                self.assertTrue(item.get("summary", "").endswith("."))
                if not item.get("via"):
                    self.assertTrue(item.get("about", "").endswith("."), "a VM says what the system is")
                self.assertTrue(item.get("docs"))
                self.assertRegex(item.get("icon", ""), r"^(https://cdn\.jsdelivr\.net/gh/[^\s]+\.webp)?$")

    def test_a_system_is_not_found_by_the_name_of_another(self):
        # Searching "ubuntu" finds Ubuntu, not the systems based on it nor the
        # menus that list it: each system has an entry of its own.
        generic = {"linux", "os", "vm", "nas", "server", "desktop", "iso", "lts", "scale", "core",
                   "home", "assistant", "docker", "cloud"}
        def words(text):
            return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]
        names = {}
        for item in self.apps:
            for word in words(item.get("name") or item["title"]):
                if word not in generic and len(word) > 2:
                    names.setdefault(word, set()).add(item["title"])
        systems = [item for item in self.index if item.get("group") == "app"
                   or item["script"] == "menus/create_vm_menu.sh" and not item.get("argument")
                   or item.get("argument") in ("1", "2", "3", "5")]
        for item in systems:
            own = set(words(item.get("name") or item["title"]))
            with self.subTest(item["title"]):
                others = [word for word in item.get("keywords", "").lower().split()
                          if word in names and word not in own and item["title"] not in names[word]]
                self.assertEqual(others, [])

    def test_every_linux_distribution_is_found_as_linux(self):
        for item in self.index:
            argument = item.get("argument")
            if isinstance(argument, list) and argument[0] == "3":
                with self.subTest(item["title"]):
                    self.assertIn("linux", f"{item['title']} {item.get('keywords', '')}".lower().split())

    def test_every_system_links_to_its_own_pages(self):
        for item in self.apps:
            if item.get("via") or item["title"] == "Linux (ISO)":
                continue
            with self.subTest(item["title"]):
                links = item.get("links") or {}
                self.assertTrue(links.get("website", "").startswith("https://"))
                self.assertTrue(all(url.startswith("https://") for url in links.values()))

    def test_every_linux_distribution_lists_the_releases_of_its_selector(self):
        search = load()
        for item in search.own_entries():
            if item["action"][2:3] == ["3"] and len(item["action"]) > 3 and item["action"][3] != "iso":
                with self.subTest(item["title"]):
                    self.assertTrue(item["releases"])

    def test_a_vm_proxmenux_configures_shows_its_default_settings(self):
        for item in self.apps:
            if item.get("via") or item["title"].startswith("Create VM System macOS"):
                continue
            with self.subTest(item["title"]):
                resources = item.get("resources") or {}
                self.assertEqual(set(resources), {"cores", "memory_mb", "disk_gb"})


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

    def test_each_word_of_a_name_joined_with_capitals_is_found(self):
        titles = [item["title"] for item in self.found("craft")]
        for name in ("CADCraft", "DeckCraft", "PdfCraft", "WordCraft"):
            self.assertIn(name, titles)
        self.assertIn("CADCraft", [item["title"] for item in self.found("cad")])

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


class CatalogTabTests(unittest.TestCase):
    """The Monitor's Catalog tab lists the menu's own options and opens them."""

    @classmethod
    def setUpClass(cls):
        cls.search = load()
        cls.own = cls.search.own_entries() + cls.search.utility_entries() + cls.search.post_install_entries()
        cls.index = json.loads((SCRIPTS / "menus/search_index.json").read_text(encoding="utf-8"))

    def test_every_option_has_a_key_of_its_own(self):
        keys = [self.search.option_key(item["id"]) for item in self.own]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{16}", key) for key in keys))

    def test_the_page_every_option_links_to_is_in_the_docs_file(self):
        docs = json.loads((SCRIPTS / "menus/option_docs.json").read_text(encoding="utf-8"))
        missing = sorted({item["docs"] for item in self.own if item["docs"] and item["docs"] not in docs})
        self.assertEqual(missing, [])
        self.assertTrue(all("en" in texts for texts in docs.values()))

    def placed(self):
        return self.search.catalog_placement([dict(item) for item in self.own])

    def test_the_sections_are_the_main_menu_without_its_settings_and_catalogs(self):
        names = [section["name"] for section in self.search.catalog_sections()]
        self.assertEqual(names[:3], ["Settings post-install Proxmox", "Hardware: GPUs and Coral-TPU",
                                     "Create VM from template or script"])
        self.assertTrue({"Community Scripts", "OCI manager Apps (Technology Preview)", "Settings"}.isdisjoint(names))
        self.assertIn("Help and Info Commands", names)

    def test_every_section_lists_what_its_menu_lists(self):
        placed = self.placed()
        for section in self.search.catalog_sections():
            listed = [item for item in placed if item["section"] == section["name"] and item["browse"]]
            self.assertTrue(listed, section["name"])

    def test_options_come_in_the_order_of_their_menu(self):
        network = sorted((item for item in self.placed() if item["section"] == "Network Management" and item["browse"]),
                         key=lambda item: item["order"])
        self.assertEqual(network[0]["english"], "Real-time network usage (iftop)")
        create = [item["english"] for item in sorted((item for item in self.placed()
                  if item["section"] == "Create VM from template or script" and item["browse"]), key=lambda item: item["order"])]
        self.assertEqual(create[0], "Create VM System NAS")
        self.assertNotIn("ZimaOS", create)

    def test_an_option_below_a_section_is_only_found_by_a_search(self):
        placed = self.placed()
        for item in placed:
            if item["id"].startswith(("post:", "utility:")):
                self.assertTrue(item["section"] and not item["browse"], item["id"])

    def test_a_section_lists_the_community_scripts_its_menu_offers(self):
        external = {section["name"]: section["external"] for section in self.search.catalog_sections(self.placed())}
        # On a Backup Server the menu offers the PBS ones; the Monitor keeps
        # those of the product it runs on.
        self.assertEqual(external["Settings post-install Proxmox"],
                         ["cs:post-pve-install", "cs:microcode", "cs:post-pbs-install", "cs:pbs-microcode"])
        self.assertEqual(external["Network Management"], ["cs:nic-offloading-fix"])

    def test_a_menu_of_external_scripts_gives_way_to_its_scripts(self):
        placed = self.placed()
        external = {section["name"]: section["external"] for section in self.search.catalog_sections(placed)}
        macos = next(item for item in placed if item.get("english") == "Create VM System macOS (OSX-PROXMOX)")
        self.assertEqual(external["Create VM from template or script"],
                         [f"pmx:{self.search.option_key(macos['id'])}", "cs:haos-vm", "cs:docker-vm", "cs:nextcloud-vm"])
        others = next(item for item in placed if item.get("english") == "Create VM System Others (based Linux)")
        self.assertTrue(others["apart"])

    def test_every_community_scripts_option_names_a_script_the_menus_run(self):
        code = "\n".join(path.read_text(errors="ignore") for path in SCRIPTS.rglob("*.sh") if "tests" not in path.parts)
        for item in self.index:
            if item.get("via") == "community-scripts":
                self.assertTrue(item.get("cs"), item["title"])
                self.assertIn(f"/{item['cs']}.sh", code, item["title"])

    def test_every_third_party_script_the_menus_run_is_declared(self):
        # A script downloaded from outside the ProxMenux repository, to run it
        # or to keep its address for later, belongs to a known third party.
        declared = [prefix for entry in self.search.THIRD_PARTY.values() for prefix in entry["scripts"]]
        address = re.compile(r"https?://[A-Za-z0-9./_-]+\.sh\b|https://install\.[a-z.-]+")
        runs = re.compile(r"(curl|wget)[^\n]*(https?://\S+)[^\n]*\|\s*([A-Z_]+=\S+\s+)*(bash|sh)\b")
        unknown = set()
        for path in SCRIPTS.rglob("*.sh"):
            if "tests" in path.parts:
                continue
            for line in path.read_text(errors="ignore").splitlines():
                if line.lstrip().startswith("#"):
                    continue
                urls = set(address.findall(line)) | {m.group(2) for m in runs.finditer(line)}
                for url in urls:
                    if "MacRimi/ProxMenux" not in url and not any(url.startswith(prefix) for prefix in declared):
                        unknown.add(f"{path.relative_to(SCRIPTS)}: {url}")
        self.assertEqual(sorted(unknown), [])

    def test_every_third_party_is_named_by_the_option_that_runs_it(self):
        named = {item.get("third_party") for item in self.index} - {None}
        named |= {name for item in self.index for name in item.get("uses") or []}
        named |= {name for names in self.search.POST_INSTALL_USES.values() for name in names}
        self.assertTrue(named <= set(self.search.THIRD_PARTY), named - set(self.search.THIRD_PARTY))
        self.assertEqual(sorted(set(self.search.THIRD_PARTY) - named), [])

    def test_a_third_party_option_says_who_maintains_it(self):
        macos = next(item for item in self.own if item.get("english") == "Create VM System macOS (OSX-PROXMOX)")
        self.assertEqual(macos["third_party"]["name"], "OSX-PROXMOX")
        nvidia = next(item for item in self.own if item.get("english") == "Install/Update NVIDIA Drivers (Host + LXC)")
        self.assertEqual([m["name"] for m in nvidia["uses"]], ["keylase/nvidia-patch"])

    def test_the_backup_section_lists_its_menu_and_its_external_scripts_apart(self):
        backup = sorted((item for item in self.placed() if item["section"] == "Host Backup & Restore" and item["browse"]),
                        key=lambda item: item["order"])
        self.assertEqual(len([item for item in backup if not item["apart"]]), 6)
        self.assertEqual([item["english"] for item in backup if item["apart"]], ["proxmox_toolbox", "proxsave"])
        external = {section["name"]: section["external"] for section in self.search.catalog_sections(self.placed())}
        self.assertEqual(external["Host Backup & Restore"][0], "cs:host-backup")
        self.assertEqual(len(external["Host Backup & Restore"]), 3)
        menu = (SCRIPTS / "backup_restore/backup_host.sh").read_text()
        for item in self.index:
            if item["script"] == "backup_restore/backup_host.sh" and item.get("argument"):
                self.assertIn(f"        {item['argument']}) ", menu)

    def test_every_setting_of_the_post_install_is_explained_by_its_section(self):
        docs = json.loads((SCRIPTS / "menus/option_docs.json").read_text(encoding="utf-8"))
        tokens = {token for _, _, token in self.search.post_install_settings()}
        # The repositories have no section of their own in the documentation.
        self.assertEqual(sorted(tokens - set(self.search.POST_INSTALL_SECTIONS)), ["REPOS"])
        self.assertEqual(sorted(set(self.search.POST_INSTALL_SECTIONS) - tokens), [])
        self.assertEqual([s for s in self.search.POST_INSTALL_SECTIONS.values() if "en" not in docs.get(s, {})], [])

    def test_the_automated_post_install_lists_every_setting_it_applies(self):
        auto = (SCRIPTS / "post_install/auto_post_install.sh").read_text()
        body = re.search(r"^run_complete_optimization\(\)\s*\{\n(.*?)^\}", auto, re.M | re.S).group(1)
        calls = re.findall(r"^\s*([a-z0-9_]+)\s*$", body, re.M)
        listed = self.search.automated_post_install_tokens()
        self.assertEqual(len(listed), len(set(listed)))
        not_settings = {"show_proxmenux_logo", "ensure_tools_json", "reboot", "else", "fi"}
        self.assertEqual(len(listed), len([call for call in calls if call not in not_settings]))
        automated = next(item for item in self.own if item["docs"] == "post-install/automated")
        self.assertEqual(len(automated["includes"][0]["items"]), len(listed))

    def test_the_customizable_post_install_lists_every_setting_by_category(self):
        custom = next(item for item in self.own if item["docs"] == "post-install/customizable")
        groups = custom["includes"]
        self.assertEqual(len(groups), len({g["group"] for g in groups}))
        self.assertEqual(sum(len(g["items"]) for g in groups), len(self.search.post_install_settings()))

    def test_the_docs_file_matches_the_documentation(self):
        result = subprocess.run(["python3", str(ROOT / ".github/scripts/build_option_docs.py"), "--check"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_only_an_option_of_the_list_is_opened(self):
        with self.assertRaises(SystemExit):
            with unittest.mock.patch("sys.argv", ["search_menu.py", "--run", "bash -c id"]), \
                    unittest.mock.patch.object(self.search, "own_entries", lambda: self.own[:1]), \
                    unittest.mock.patch.object(self.search, "utility_entries", lambda: []), \
                    unittest.mock.patch.object(self.search, "post_install_entries", lambda: []), \
                    unittest.mock.patch.object(self.search.os, "execvp") as execvp:
                self.search.main()
        execvp.assert_not_called()


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

    def test_the_summary_of_every_application_is_found(self):
        extractor = runpy.run_path(str(ROOT / ".github/scripts/build_translation_cache.py"))
        found = set(extractor["extract_menu_index_texts"](SCRIPTS))
        index = json.loads((SCRIPTS / "menus/search_index.json").read_text(encoding="utf-8"))
        texts = {text for item in index for text in [item.get("summary"), item.get("about"), *(item.get("notes") or [])] if text}
        self.assertTrue(texts)
        self.assertEqual(sorted(texts - found), [])

    def test_a_change_in_the_search_runs_the_workflow(self):
        self.assertIn("'scripts/**/*.py'", self.triggers)


if __name__ == "__main__":
    unittest.main()
