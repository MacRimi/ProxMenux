"""Catalog delivery is atomic, offline-safe, and never acknowledges unseen apps."""
import json
import gc
import errno
import http.server
import itertools
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from proxmenux_oci.catalog import Catalog
from proxmenux_oci import catalog_refresh as refresh


class CatalogRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "oci" / "engine"
        self.root.mkdir(parents=True)
        shutil.copytree(ROOT / "schemas", self.root / "schemas")
        index = json.loads((ROOT / "catalog/index.json").read_text())
        self.item = next(x for x in index["applications"]
                         if x.get("template_family") == "curated-profile"
                         and x.get("automatic_install_candidate") and not x.get("hidden"))
        self.files = {}
        for name in ("categories.json", "volume-policy.json", "exclusions.json", "verification.json"):
            self.files[name] = (ROOT / "catalog" / name).read_bytes()
        for name in (f'apps/{self.item["id"]}.json', self.item['curated_path'].removeprefix("catalog/")):
            self.files[name] = (ROOT / "catalog" / name).read_bytes()
        self.files["index.json"] = json.dumps({"kind": "proxmenux.oci-catalog-index",
                                                "applications": [self.item]}).encode()
        for name, data in self.files.items():
            file = self.root / "catalog" / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        self.revision = "a" * 40
        self.requests = []

    def fetch(self, url, etag=None):
        self.requests.append((url, etag))
        if "/commits?" in url:
            return json.dumps([{"sha": self.revision}]).encode(), '"catalog-etag"'
        if "/git/trees/" in url:
            entries = [{"path": "oci/catalog/" + name, "type": "blob", "mode": "100644",
                        "sha": refresh.git_blob(data), "size": len(data)}
                       for name, data in self.files.items()]
            schema = (self.root / "schemas/oci-template.schema.json").read_bytes()
            entries.append({"path": "oci/schemas/oci-template.schema.json", "type": "blob",
                            "sha": refresh.git_blob(schema)})
            return json.dumps({"tree": entries, "truncated": False}).encode(), None
        name = url.split("/oci/catalog/", 1)[1]
        return self.files[name], None

    def sync(self):
        return refresh.synchronize(self.root, "main", self.fetch)

    def add_app(self):
        item = dict(self.item, id="sample-added", template_id="image-sample-added",
                    curated_path="catalog/curated/sample-added.json", template="apps/sample-added.json")
        recipe = json.loads(self.files[self.item["curated_path"].removeprefix("catalog/")])
        recipe["id"] = item["template_id"]
        for name in ("apps/sample-added.json", "curated/sample-added.json"):
            self.files[name] = json.dumps(recipe).encode()
        index = json.loads(self.files["index.json"])
        index["applications"].append(item)
        self.files["index.json"] = json.dumps(index).encode()

    def future_profile(self, app_id):
        index = json.loads(self.files["index.json"])
        item = next(x for x in index["applications"] if x["id"] == app_id)
        path = item["curated_path"].removeprefix("catalog/")
        recipe = json.loads(self.files[path])
        recipe.setdefault("proxmox", {}).setdefault("installer_profile", {})["future_engine_key"] = True
        self.files[path] = json.dumps(recipe).encode()

    def test_new_unknown_profile_key_is_silent_and_not_counted(self):
        self.sync()
        baseline = Catalog(self.root)
        status = refresh.CatalogRefresh(self.root, baseline)
        self.revision = "b" * 40
        self.add_app()
        self.future_profile("sample-added")
        self.assertTrue(self.sync())
        catalog = Catalog(self.root)
        self.assertNotIn("sample-added", refresh.visible_recipes(catalog))
        self.assertEqual(set(refresh.visible_recipes(catalog)), set(status.recipes))
        status.recipes = refresh.visible_recipes(catalog)
        self.assertEqual(status.new_ids(), [])

    def test_compatibility_gate_uses_effective_menu_visibility(self):
        self.add_app()
        self.future_profile("sample-added")
        index = json.loads(self.files["index.json"])
        added = next(x for x in index["applications"] if x["id"] == "sample-added")
        added.update(hidden=True, automatic_install_candidate=False)
        self.files["index.json"] = json.dumps(index).encode()
        # The app template makes this stale index entry visible/installable;
        # use the same rule as Catalog.load_index(), not the raw index flags.
        self.sync()
        self.assertNotIn("sample-added", refresh.visible_recipes(Catalog(self.root)))

    def test_incompatible_existing_app_retains_complete_previous_contract(self):
        self.sync()
        old = Catalog(self.root).compose(self.item["id"])
        old_visible = refresh.visible_recipes(Catalog(self.root))
        self.revision = "b" * 40
        self.future_profile(self.item["id"])
        # A new policy must not mutate the retained contract.
        policy = json.loads(self.files["volume-policy.json"])
        policy["shared_paths"] = [v["container_path"] for v in old["container_contract"].get("volumes", [])]
        self.files["volume-policy.json"] = json.dumps(policy).encode()
        self.sync()
        self.assertEqual(Catalog(self.root).compose(self.item["id"]), old)
        self.assertEqual(refresh.visible_recipes(Catalog(self.root)), old_visible)
        # A later incompatible revision still retains the same original contract.
        self.revision = "c" * 40
        self.sync()
        self.assertEqual(Catalog(self.root).compose(self.item["id"]), old)

    def test_engine_capability_update_rechecks_same_revision_without_etag(self):
        self.add_app()
        self.future_profile("sample-added")
        self.sync()
        self.assertNotIn("sample-added", refresh.visible_recipes(Catalog(self.root)))
        bundled = self.root / "catalog" / self.item["curated_path"].removeprefix("catalog/")
        value = json.loads(bundled.read_text())
        value.setdefault("proxmox", {}).setdefault("installer_profile", {})["future_engine_key"] = True
        bundled.write_text(json.dumps(value))
        self.requests.clear()
        self.assertTrue(self.sync())
        self.assertIsNone(self.requests[0][1])
        self.assertIn("sample-added", refresh.visible_recipes(Catalog(self.root)))

    def test_known_profile_key_accepts_new_values(self):
        self.add_app()
        path = "curated/sample-added.json"
        value = json.loads(self.files[path])
        self.assertIn("completion_notes", refresh.supported_profile_keys(self.root))
        value["proxmox"]["installer_profile"]["completion_notes"].append("A new supported setting")
        self.files[path] = json.dumps(value).encode()
        self.sync()
        self.assertIn("sample-added", refresh.visible_recipes(Catalog(self.root)))

    def test_all_incompatible_apps_can_produce_empty_visible_catalog(self):
        self.future_profile(self.item["id"])
        # No compatible old recipe exists on this host.
        path = self.root / "catalog" / self.item["curated_path"].removeprefix("catalog/")
        value = json.loads(path.read_text())
        value["proxmox"]["installer_profile"].pop("future_engine_key", None)
        # Use a new ID instead of retaining the bundled application.
        self.add_app()
        self.future_profile("sample-added")
        index = json.loads(self.files["index.json"])
        index["applications"] = [x for x in index["applications"] if x["id"] == "sample-added"]
        self.files["index.json"] = json.dumps(index).encode()
        self.sync()
        self.assertNotEqual(refresh.current_catalog(self.root), self.root / "catalog")
        self.assertEqual(refresh.visible_recipes(Catalog(self.root)), {})

    def test_pruning_preserves_active_and_leased_snapshots_then_reclaims_reader(self):
        self.sync()
        old = Catalog(self.root)
        old_directory = old.catalog_dir
        self.revision = "b" * 40
        self.add_app()
        self.sync()
        refresh.prune_snapshots(self.root)
        self.assertTrue(old_directory.exists())
        self.assertEqual(old.compose(self.item["id"])["id"], self.item["template_id"])
        del old
        gc.collect()
        refresh.prune_snapshots(self.root)
        self.assertFalse(old_directory.exists())
        self.assertTrue(refresh.current_catalog(self.root).exists())

    def test_pruning_preserves_both_channels_and_unlinks_orphan_lease(self):
        self.sync()
        main = refresh.current_catalog(self.root, "main")
        self.revision = "b" * 40
        refresh.synchronize(self.root, "develop", self.fetch)
        orphan = refresh.cache_root(self.root) / "snapshots" / ("c" * 40)
        orphan.mkdir()
        refresh.prune_snapshots(self.root)
        self.assertTrue(main.exists())
        self.assertTrue(refresh.current_catalog(self.root, "develop").exists())
        self.assertFalse(orphan.exists())
        self.assertFalse((refresh.cache_root(self.root) / "leases" / orphan.name).exists())

    def test_worker_prunes_even_when_no_change_or_network_failure(self):
        self.sync()
        for error in (None, OSError("offline")):
            orphan = refresh.cache_root(self.root) / "snapshots" / ("c" * 40)
            orphan.mkdir()
            with patch.object(refresh, "synchronize", side_effect=error, return_value=False):
                refresh.worker(self.root, "main")
            self.assertFalse(orphan.exists())

    def test_reader_process_exit_releases_lease_without_pid_cleanup(self):
        import subprocess
        self.sync()
        directory = refresh.current_catalog(self.root)
        code = ("import fcntl,sys,time; "
                "f=open(sys.argv[1], 'a'); fcntl.flock(f,fcntl.LOCK_SH); "
                "print('ready',flush=True); time.sleep(30)")
        leases = refresh.cache_root(self.root) / "leases"
        leases.mkdir(exist_ok=True)
        child = subprocess.Popen([sys.executable, "-c", code, str(leases / directory.name)],
                                 stdout=subprocess.PIPE, text=True)
        self.addCleanup(child.stdout.close)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.assertEqual(child.stdout.readline().strip(), "ready")
        self.revision = "b" * 40
        self.sync()
        refresh.prune_snapshots(self.root)
        self.assertTrue(directory.exists())
        child.kill()
        child.wait(timeout=3)
        refresh.prune_snapshots(self.root)
        self.assertFalse(directory.exists())

    def test_menu_pin_does_not_wait_for_network_worker_lock(self):
        self.sync()
        lock = (refresh.cache_root(self.root) / "refresh.lock").open("a")
        self.addCleanup(lock.close)
        refresh.fcntl.flock(lock, refresh.fcntl.LOCK_EX)
        catalog = Catalog(self.root)
        self.assertEqual(catalog.compose(self.item["id"])["id"], self.item["template_id"])

    def test_complete_catalog_is_selected_atomically_without_redownloading_unchanged_files(self):
        self.assertTrue(self.sync())
        directory = refresh.current_catalog(self.root, "main")
        self.assertEqual(directory.name, self.revision)
        self.assertEqual(Catalog(self.root).compose(self.item["id"])["id"], self.item["template_id"])
        self.assertFalse(any("raw.githubusercontent" in url for url, _ in self.requests))
        self.assertTrue((self.root / "catalog/index.json").exists())

    def test_changed_file_uses_immutable_commit_and_updates_recipe(self):
        name = self.item["curated_path"].removeprefix("catalog/")
        recipe = json.loads(self.files[name]); recipe["catalog_ui"]["tips"].append("New setup tip")
        self.files[name] = json.dumps(recipe).encode()
        self.sync()
        self.assertTrue(any(f"/{self.revision}/oci/catalog/{name}" in u for u, _ in self.requests))
        self.assertIn("New setup tip", Catalog(self.root).compose(self.item["id"])["catalog_ui"]["tips"])

    def test_unchanged_revision_does_not_fetch_tree_or_recipes(self):
        self.sync(); self.requests.clear()
        self.assertFalse(self.sync())
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][1], '"catalog-etag"')

    def test_not_modified_uses_cached_snapshot(self):
        self.sync()
        fetch = Mock(return_value=(None, '"catalog-etag"'))
        self.assertFalse(refresh.synchronize(self.root, "main", fetch))
        self.assertEqual(fetch.call_count, 1)

    def test_formatting_and_unrelated_categories_do_not_count_as_recipe_updates(self):
        before = refresh.visible_recipes(Catalog(self.root))
        for name in self.files:
            path = self.root / 'catalog' / name
            value = json.loads(path.read_text())
            if name == 'categories.json':
                value['applications']['unrelated-app'] = 'misc'
            path.write_text(json.dumps(value, indent=4) + '\n')
        self.assertEqual(refresh.visible_recipes(Catalog(self.root)), before)

    def test_failure_keeps_previous_catalog_and_does_not_commit_remote_etag(self):
        self.sync()
        old = refresh.current_catalog(self.root)
        self.revision = "b" * 40
        self.files[self.item["curated_path"].removeprefix("catalog/")] = b'{}'
        with self.assertRaises(Exception):
            self.sync()
        self.assertEqual(refresh.current_catalog(self.root), old)
        self.assertFalse((refresh.cache_root(self.root) / "snapshots" / self.revision).exists())

    def test_missing_recipe_cannot_publish_index_alone(self):
        self.files.pop(self.item["curated_path"].removeprefix("catalog/"))
        with self.assertRaises(Exception):
            self.sync()
        self.assertEqual(refresh.current_catalog(self.root), self.root / "catalog")

    def test_hash_mismatch_is_rejected(self):
        real = self.fetch
        def corrupt(url, etag=None):
            body, tag = real(url, etag)
            if "/git/trees/" in url:
                tree = json.loads(body)
                tree["tree"][0]["sha"] = "f" * 40
                body = json.dumps(tree).encode()
            return body, tag
        with self.assertRaisesRegex(ValueError, "integrity"):
            refresh.synchronize(self.root, "main", corrupt)
        self.assertEqual(refresh.current_catalog(self.root), self.root / "catalog")

    def test_schema_mismatch_requires_engine_update(self):
        real = self.fetch
        def incompatible(url, etag=None):
            body, tag = real(url, etag)
            if "/git/trees/" in url:
                tree = json.loads(body); tree["tree"][-1]["sha"] = "f" * 40
                body = json.dumps(tree).encode()
            return body, tag
        with self.assertRaisesRegex(ValueError, "schema changed"):
            refresh.synchronize(self.root, "main", incompatible)

    def test_new_engine_api_requires_engine_update(self):
        self.files["compatibility.json"] = b'{"engine_api": 999}'
        with self.assertRaisesRegex(ValueError, "newer OCI engine"):
            self.sync()

    def test_paths_and_symlink_entries_are_rejected(self):
        for name in ("../index.json", "/index.json", "apps/../../secret.json", "remote/install.sh"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                refresh.catalog_path(name)

    def test_offline_worker_keeps_local_catalog(self):
        with patch.object(refresh, "synchronize", side_effect=OSError("Network unavailable")):
            refresh.worker(self.root, "main")
        self.assertFalse(refresh.read_json(refresh.cache_root(self.root) / "main-result.json")["ok"])
        self.assertEqual(refresh.current_catalog(self.root), self.root / "catalog")

    def test_first_visit_has_no_new_apps_and_opening_their_list_acknowledges_them(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        self.assertEqual((status.new_ids(), status.label()), ([], "Refresh catalog"))
        status.recipes["new-app"] = "new-recipe-hash"
        self.assertEqual((status.new_ids(), status.label()), (["new-app"], "New applications (1)"))
        # A new application stays new on later visits until its list is opened.
        later = refresh.CatalogRefresh(self.root, Catalog(self.root))
        later.recipes = status.recipes.copy()
        self.assertEqual(later.new_ids(), ["new-app"])
        later.mark_seen()
        same = refresh.CatalogRefresh(self.root, Catalog(self.root))
        same.recipes = status.recipes.copy()
        self.assertEqual(same.new_ids(), [])

    def test_new_apps_are_counted_by_id_not_net_growth_or_changed_recipes(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        original = self.item["id"]
        status.baseline = {original: "old-recipe", "removed-app": "hash"}
        status.recipes["new-app"] = "hash"
        self.assertEqual(status.new_ids(), ["new-app"])
        self.assertEqual(status.label(), "New applications (1)")

    def test_exit_before_download_finishes_does_not_acknowledge_remote_apps(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        status.mark_seen()
        status.process = Mock(); status.process.poll.return_value = None
        with patch.object(refresh.threading, "Thread"):
            status.__exit__(None, None, None)
        status.process.terminate.assert_not_called()
        self.add_app()
        self.sync()
        next_visit = refresh.CatalogRefresh(self.root, Catalog(self.root))
        self.assertEqual(len(next_visit.new_ids()), 1)

    def test_the_download_never_closes_the_open_menu_and_shows_on_the_next_draw(self):
        from proxmenux_oci import cli, updates
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        status.process = Mock(returncode=0)
        status.process.poll.return_value = None
        screens = []
        owner = self
        class UI:
            live_refresh = True
            def choose(self, text, entries, default, **kwargs):
                screens.append((text, dict(entries)))
                if len(screens) == 1:
                    # The catalog finishes downloading while the menu is open:
                    # nothing may close it, so no refresh is watched.
                    owner.assertNotIn('refresh', kwargs)
                    owner.assertNotIn('Refreshing the application catalog', text)
                    owner.add_app()
                    owner.sync()
                    refresh.write_json(refresh.cache_root(owner.root) / 'main-result.json',
                                       {"ok": True, "changed": True})
                    status.process.poll.return_value = 0
                    return 'search'  # any action brings the user back to the menu
                return None
        checker = Mock(active=False)
        checker.status.return_value = {"available": []}
        checker.notice.return_value = ""
        checker.label.return_value = "Check for updates"
        checker.changed.return_value = False
        checker_context = Mock()
        checker_context.__enter__ = Mock(return_value=checker)
        checker_context.__exit__ = Mock(return_value=False)
        original_class = refresh.CatalogRefresh
        with patch.object(original_class, '__enter__', return_value=status), \
                patch.object(refresh, 'CatalogRefresh', return_value=status), \
                patch.object(cli, 'PROJECT_ROOT', self.root), \
                patch.object(cli, 'interactive_ui', return_value=UI()), \
                patch.object(cli, '_search'), \
                patch.object(updates, 'UpdateCheck', return_value=checker_context):
            self.assertEqual(cli.interactive(Catalog(self.root)), 0)
        # The header is one line; the catalog entry names the new application.
        self.assertEqual(screens[0][0], cli.translate('Select a category or search for applications:'))
        self.assertEqual(screens[0][1]['refresh'], cli.translate('Refresh catalog'))
        self.assertRegex(screens[1][1]['refresh'], r' {2,}\(  1\)$')
        self.assertIn('(  2)', screens[1][1]['all'])
        next_visit = original_class(self.root, Catalog(self.root))
        # Seeing the menu does not acknowledge it: only opening the list does.
        self.assertEqual(len(next_visit.new_ids()), 1)

    def test_menu_snapshot_hit_does_not_read_and_parse_recipes_again(self):
        catalog = Catalog(self.root)
        expected = refresh.menu_catalog(catalog)
        with patch.object(Catalog, 'load_index', side_effect=AssertionError('duplicate catalog scan')), \
                patch.object(refresh, 'visible_recipes', side_effect=AssertionError('duplicate recipe hash')):
            self.assertEqual(refresh.menu_catalog(Catalog(self.root)), expected)

    def test_menu_snapshot_invalidates_recipe_overlay_and_policy_changes(self):
        refresh.menu_catalog(Catalog(self.root))
        for relative in (f'apps/{self.item["id"]}.json', f'overlays/{self.item["id"]}.json',
                         'categories.json', 'verification.json', 'volume-policy.json', 'index.json'):
            path = self.root / 'catalog' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text((path.read_text() if path.exists() else '{}') + ' ')
            original = Catalog.load_index
            calls = []
            def load(instance):
                calls.append(True)
                return original(instance)
            with self.subTest(path=relative), patch.object(Catalog, 'load_index', load):
                refresh.menu_catalog(Catalog(self.root))
                self.assertTrue(calls)

    def test_menu_snapshot_handles_corrupt_or_unwritable_cache(self):
        expected = refresh.menu_catalog(Catalog(self.root))
        cache = refresh.cache_root(self.root) / ('menu-' + refresh.channel_for(self.root) + '.json')
        cache.write_text('{broken')
        with patch.object(refresh, 'write_json', side_effect=OSError('read-only fixture')):
            self.assertEqual(refresh.menu_catalog(Catalog(self.root)), expected)

    def test_malformed_menu_cache_is_rebuilt_for_the_next_visit(self):
        expected = refresh.menu_catalog(Catalog(self.root))
        cache = refresh.cache_root(self.root) / ('menu-' + refresh.channel_for(self.root) + '.json')
        value = json.loads(cache.read_text());value['index'] = []
        cache.write_text(json.dumps(value))
        self.assertEqual(refresh.menu_catalog(Catalog(self.root)), expected)
        with patch.object(Catalog, 'load_index', side_effect=AssertionError('cache was not repaired')):
            self.assertEqual(refresh.menu_catalog(Catalog(self.root)), expected)

    def test_menu_snapshot_restores_local_only_app_identity(self):
        self.add_app()
        for name, data in self.files.items():
            path = self.root / 'catalog' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        index = json.loads(self.files['index.json']);index['applications'] = [self.item]
        self.files['index.json'] = json.dumps(index).encode()
        for name in ('apps/sample-added.json', 'curated/sample-added.json'):
            self.files.pop(name)
        with patch.object(refresh, 'source_settings', return_value={'local_apps': ['sample-added']}):
            self.sync()
            refresh.menu_catalog(Catalog(self.root))
            catalog = Catalog(self.root)
            refresh.menu_catalog(catalog)
            self.assertEqual(catalog.local_app_ids, {'sample-added'})
            path = self.root / 'catalog/apps/sample-added.json'
            path.write_text(path.read_text() + ' ')
            original = Catalog.load_index
            with patch.object(Catalog, 'load_index', autospec=True, side_effect=original) as load:
                refresh.menu_catalog(Catalog(self.root))
                self.assertTrue(load.called)

    def test_menu_recipe_fingerprints_reuse_the_displayed_index(self):
        catalog = Catalog(self.root)
        applications = catalog.load_index()["applications"]
        expected = refresh.visible_recipes(catalog)
        with patch.object(catalog, 'load_index', side_effect=AssertionError('duplicate catalog scan')):
            self.assertEqual(refresh.visible_recipes(catalog, applications), expected)
            self.assertEqual(refresh.CatalogRefresh(self.root, catalog, applications).recipes, expected)
            self.assertEqual(refresh.visible_recipes(catalog, []), {})

    def test_existing_local_app_does_not_load_the_entire_bundled_catalog(self):
        self.sync()
        catalog = Catalog(self.root)
        original = Catalog._enrich_index_from_templates
        scanned = []
        def enrich(instance, payload):
            scanned.append(instance.catalog_dir)
            return original(instance, payload)
        with patch.object(refresh, 'source_settings', return_value={'local_apps': [self.item['id']]}), \
                patch.object(Catalog, '_enrich_index_from_templates', enrich):
            result = catalog.load_index()
        self.assertEqual(scanned, [catalog.catalog_dir])
        self.assertEqual(len(result['applications']), 1)

    def test_invalid_local_app_entries_do_not_break_the_menu(self):
        self.sync()
        catalog = Catalog(self.root)
        with patch.object(refresh, 'source_settings', return_value={'local_apps': [{}, [], None]}):
            self.assertEqual(len(catalog.load_index()['applications']), 1)
            self.assertEqual(catalog.local_app_ids, set())

    def test_explicit_local_apps_survive_refresh_without_preventing_upstream_removal(self):
        # This app is a local preview, not a member of the upstream manifest.
        self.add_app()
        for name, data in self.files.items():
            file = self.root / 'catalog' / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        index = json.loads(self.files['index.json'])
        index['applications'] = [self.item]
        self.files['index.json'] = json.dumps(index).encode()
        for name in ('apps/sample-added.json', 'curated/sample-added.json'):
            self.files.pop(name)
        with patch.object(refresh, 'source_settings', return_value={'local_apps': ['sample-added']}):
            self.sync()
            catalog = Catalog(self.root)
            self.assertIn('sample-added', refresh.visible_recipes(catalog))
            self.assertEqual(catalog.compose('sample-added')['id'], 'image-sample-added')
        self.assertNotIn('sample-added', refresh.visible_recipes(Catalog(self.root)))

    def test_channel_switch_does_not_use_other_channel_snapshot(self):
        self.sync()
        self.assertEqual(refresh.current_catalog(self.root, "develop"), self.root / "catalog")

    def test_engine_schema_change_invalidates_cached_catalog(self):
        self.sync()
        schema = self.root / "schemas/oci-template.schema.json"
        schema.write_text(schema.read_text() + "\n")
        self.assertEqual(refresh.current_catalog(self.root), self.root / "catalog")

    def test_corrupted_cached_index_falls_back_to_bundled_catalog(self):
        self.sync()
        snapshot = refresh.current_catalog(self.root)
        (snapshot / 'index.json').write_text('{broken json')
        self.assertEqual(refresh.current_catalog(self.root), self.root / 'catalog')

    def test_refresh_process_is_started_without_waiting(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        with patch.object(refresh.subprocess, "Popen") as spawn:
            spawn.return_value.poll.return_value = None
            with patch.object(refresh.threading, "Thread") as thread:
                with status:
                    self.assertTrue(status.active)
                    # The download is transparent: the open menu does not announce it.
                    self.assertEqual(status.label(), "Refresh catalog")
                thread.return_value.start.assert_called_once()
                spawn.return_value.wait.assert_not_called()

    def test_manual_refresh_does_not_duplicate_worker_and_can_retry_failure(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        with patch.object(refresh.subprocess, 'Popen') as spawn:
            spawn.return_value.poll.return_value = None
            self.assertTrue(status.start())
            self.assertFalse(status.start())
            self.assertEqual(spawn.call_count, 1)
            spawn.return_value.poll.return_value = 0
            spawn.return_value.returncode = 0
            refresh.write_json(refresh.cache_root(self.root) / 'main-result.json', {'ok': False})
            self.assertFalse(status.consume())
            self.assertTrue(status.failed)
            self.assertTrue(status.start())
            self.assertFalse(status.failed)
            self.assertEqual(spawn.call_count, 2)

    def test_manual_refresh_is_offered_in_the_main_menu(self):
        from proxmenux_oci.cli import _catalog_options
        options = dict(_catalog_options(Catalog(self.root))[-1])
        self.assertEqual(options['refresh'], 'Refresh catalog')

    def test_sequence_new_app_failed_update_retry_and_withdrawal(self):
        self.sync()
        old = Catalog(self.root)
        status = refresh.CatalogRefresh(self.root, old)
        status.mark_seen()
        self.revision = 'b' * 40
        self.add_app()
        self.assertTrue(self.sync())
        self.assertIn('sample-added', refresh.visible_recipes(Catalog(self.root)))
        self.assertNotIn('sample-added', refresh.visible_recipes(old))  # Wizard remains pinned.
        next_visit = refresh.CatalogRefresh(self.root, Catalog(self.root))
        self.assertEqual(len(next_visit.new_ids()), 1)
        next_visit.mark_seen()
        self.revision = 'c' * 40
        recipe_path = self.item['curated_path'].removeprefix('catalog/')
        good = self.files[recipe_path]
        self.files[recipe_path] = b'{invalid-json'
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(refresh.current_catalog(self.root).name, 'b' * 40)
        self.files[recipe_path] = good
        self.assertTrue(self.sync())
        index = json.loads(self.files['index.json'])
        index['applications'] = [self.item]
        self.files['index.json'] = json.dumps(index).encode()
        for name in ('apps/sample-added.json', 'curated/sample-added.json'):
            self.files.pop(name)
        self.revision = 'd' * 40
        self.assertTrue(self.sync())
        current = Catalog(self.root)
        self.assertNotIn('sample-added', refresh.visible_recipes(current))
        self.assertFalse((current.catalog_dir / 'curated/sample-added.json').exists())
        self.assertEqual(refresh.CatalogRefresh(self.root, current).new_ids(), [])

    def test_http_errors_and_timeouts_keep_snapshot_then_retry_succeeds(self):
        self.sync()
        old = refresh.current_catalog(self.root)
        errors = [TimeoutError('timeout'), urllib.error.URLError('DNS unavailable')]
        errors += [urllib.error.HTTPError('https://api.github.com', code, 'test', {}, None)
                   for code in (403, 404, 429, 500, 503)]
        for error in errors:
            if isinstance(error, urllib.error.HTTPError): self.addCleanup(error.close)
        self.revision = 'b' * 40
        for error in errors:
            with self.subTest(error=str(error)), self.assertRaises(Exception):
                refresh.synchronize(self.root, 'main', Mock(side_effect=error))
            self.assertEqual(refresh.current_catalog(self.root), old)
        self.assertTrue(self.sync())

    def test_failed_file_transfer_does_not_publish_partial_download(self):
        self.sync(); old = refresh.current_catalog(self.root)
        self.revision = 'b' * 40; self.add_app()
        def interrupted(url, etag=None):
            if 'raw.githubusercontent' in url:
                raise TimeoutError('Connection lost during download')
            return self.fetch(url, etag)
        with self.assertRaises(TimeoutError):
            refresh.synchronize(self.root, 'main', interrupted)
        self.assertEqual(refresh.current_catalog(self.root), old)
        self.assertFalse(list((refresh.cache_root(self.root) / 'snapshots').glob('.download-*')))
        self.assertTrue(self.sync())

    def test_disk_full_and_pointer_permission_failure_preserve_previous_revision_and_etag(self):
        for error in (OSError(errno.ENOSPC, 'Disk full'), PermissionError('Read only')):
            with self.subTest(error=error):
                self.sync()
                pointer = refresh.cache_root(self.root) / 'main-current.json'
                before = pointer.read_bytes()
                old = refresh.current_catalog(self.root)
                self.revision = 'b' * 40
                real = refresh.write_json
                def fail(path, value):
                    if Path(path) == pointer:
                        raise error
                    return real(path, value)
                with patch.object(refresh, 'write_json', side_effect=fail), self.assertRaises(OSError):
                    self.sync()
                self.assertEqual(pointer.read_bytes(), before)
                self.assertEqual(refresh.current_catalog(self.root), old)
                self.assertTrue(self.sync())
                self.revision = 'c' * 40

    def test_manual_force_repairs_corrupted_recipe_at_same_revision(self):
        self.sync()
        old = refresh.current_catalog(self.root)
        recipe = old / self.item['curated_path'].removeprefix('catalog/')
        recipe.write_text('{}')
        self.requests.clear()
        self.assertTrue(refresh.synchronize(self.root, 'main', self.fetch, force=True))
        self.assertIsNone(self.requests[0][1])
        self.assertNotEqual(refresh.current_catalog(self.root), old)
        self.assertEqual(Catalog(self.root).compose(self.item['id'])['id'], self.item['template_id'])
        self.assertFalse(refresh.synchronize(self.root, 'main', self.fetch, force=True))

    def test_corrupt_cached_index_can_be_repaired_by_automatic_refresh(self):
        self.sync()
        old = refresh.current_catalog(self.root)
        (old / 'index.json').write_text('{broken')
        self.assertTrue(self.sync())
        self.assertNotEqual(refresh.current_catalog(self.root), self.root / 'catalog')
        self.assertEqual(Catalog(self.root).compose(self.item['id'])['id'], self.item['template_id'])

    def test_second_session_result_cannot_hide_successful_update(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        self.sync()
        status.process = Mock(returncode=0)
        status.process.poll.return_value = 0
        # Another session checked the newly installed revision and found no change.
        refresh.write_json(refresh.cache_root(self.root) / 'main-result.json',
                           {'ok': True, 'changed': False})
        self.assertTrue(status.consume())

    def test_crashed_worker_does_not_trust_stale_success(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        status.process = Mock(returncode=1); status.process.poll.return_value = 1
        refresh.write_json(refresh.cache_root(self.root) / 'main-result.json',
                           {'ok': True, 'changed': True})
        self.assertFalse(status.consume())
        self.assertTrue(status.failed)

    def test_force_manual_refresh_passes_flag_to_worker(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        with patch.object(refresh.subprocess, 'Popen') as spawn:
            self.assertTrue(status.start(force=True))
            self.assertIn('--force', spawn.call_args.args[0])

    def test_duplicate_manifest_path_symlink_and_truncated_tree_are_rejected(self):
        for change in ('duplicate', 'symlink', 'truncated'):
            def bad_tree(url, etag=None):
                body, tag = self.fetch(url, etag)
                if '/git/trees/' in url:
                    tree = json.loads(body)
                    if change == 'duplicate': tree['tree'].append(tree['tree'][0])
                    elif change == 'symlink': tree['tree'][0]['mode'] = '120000'
                    else: tree['truncated'] = True
                    body = json.dumps(tree).encode()
                return body, tag
            with self.subTest(change=change), self.assertRaises(ValueError):
                refresh.synchronize(self.root, 'main', bad_tree)
            self.assertEqual(refresh.current_catalog(self.root), self.root / 'catalog')

    def test_bad_channel_config_falls_back_without_crashing_menu(self):
        config = self.root.parent / 'catalog-source.json'
        for value in ([], None, 'invalid', {'channel': 'other'}, {'beta_program': 'invalid'}):
            config.write_text(json.dumps(value))
            self.assertEqual(refresh.channel_for(self.root), 'main')

    def test_full_disk_during_file_write_leaves_no_partial_catalog(self):
        self.sync(); old = refresh.current_catalog(self.root)
        self.revision = 'b' * 40; self.add_app()
        real = Path.write_bytes
        def full(path, data):
            if any(part.startswith('.download-') for part in path.parts):
                raise OSError(errno.ENOSPC, 'Disk full')
            return real(path, data)
        with patch.object(Path, 'write_bytes', new=full), self.assertRaises(OSError):
            self.sync()
        self.assertEqual(refresh.current_catalog(self.root), old)
        self.assertFalse(list((refresh.cache_root(self.root) / 'snapshots').glob('.download-*')))

    def test_orphaned_download_is_removed_before_retry(self):
        partial = refresh.cache_root(self.root) / 'snapshots/.download-crashed'
        partial.mkdir(parents=True); (partial/'partial.json').write_text('{}')
        synchronize = refresh.synchronize
        with patch.object(refresh, 'synchronize', side_effect=lambda *a, **kw:
                          synchronize(self.root, 'main', self.fetch)):
            refresh.worker(self.root, 'main')
        self.assertFalse(partial.exists())
        self.assertTrue(refresh.read_json(refresh.cache_root(self.root)/'main-result.json')['ok'])

    def test_request_rejects_oversized_response_and_handles_304(self):
        context = Mock()
        context.__enter__ = Mock(return_value=Mock(read=Mock(return_value=b'oversized')))
        context.__exit__ = Mock(return_value=False)
        with patch.object(refresh.urllib.request, 'urlopen', return_value=context), self.assertRaises(ValueError):
            refresh.request('https://api.github.com/test', limit=2)
        error = urllib.error.HTTPError('https://api.github.com', 304, 'unchanged', {}, None)
        with patch.object(refresh.urllib.request, 'urlopen', side_effect=error):
            self.assertEqual(refresh.request('https://api.github.com/test', etag='old'), (None, 'old'))

    def test_unwritable_seen_state_does_not_crash_menu(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        with patch.object(refresh, 'write_json', side_effect=PermissionError('Read only')):
            status.mark_seen()
        self.assertFalse(status.failed)

    def test_concurrent_workers_serialize_the_catalog_transaction(self):
        barrier = threading.Barrier(2)
        guard = threading.Lock()
        active = maximum = 0
        errors = []
        def operation(*args, **kwargs):
            nonlocal active, maximum
            with guard:
                active += 1; maximum = max(maximum, active)
            time.sleep(0.03)
            with guard: active -= 1
            return False
        def run():
            try:
                barrier.wait(timeout=2)
                refresh.worker(self.root, 'main')
            except Exception as error:
                errors.append(error)
        with patch.object(refresh, 'synchronize', side_effect=operation):
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=3)
        self.assertFalse(errors)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(maximum, 1)

    def test_download_deadline_preserves_previous_catalog(self):
        self.sync(); old = refresh.current_catalog(self.root)
        self.revision = 'b' * 40; self.add_app()
        with patch.object(refresh.time, 'monotonic', side_effect=itertools.chain([0], itertools.repeat(100))), \
                self.assertRaises(TimeoutError):
            self.sync()
        self.assertEqual(refresh.current_catalog(self.root), old)

    def test_http_end_to_end_new_release_outage_retry_manual_refresh_and_repair(self):
        owner = self
        unavailable = False
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if unavailable:
                    self.send_error(503); return
                etag = '"' + owner.revision + '"'
                if self.headers.get('If-None-Match') == etag:
                    self.send_response(304); self.end_headers(); return
                host = ('https://api.github.com' if self.path.startswith('/repos/')
                        else 'https://raw.githubusercontent.com')
                body, _ = owner.fetch(host + self.path)
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('ETag', etag)
                self.end_headers(); self.wfile.write(body)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def fetch(url, etag=None):
            original = urllib.parse.urlsplit(url)
            path = original.path + ('?' + original.query if original.query else '')
            return refresh.request(f'http://127.0.0.1:{server.server_port}' + path, etag)
        try:
            self.assertTrue(refresh.synchronize(self.root, 'main', fetch))
            self.assertFalse(refresh.synchronize(self.root, 'main', fetch))
            first = refresh.current_catalog(self.root)
            unavailable = True
            self.revision = 'b' * 40; self.add_app()
            with self.assertRaises(urllib.error.HTTPError):
                refresh.synchronize(self.root, 'main', fetch)
            self.assertEqual(refresh.current_catalog(self.root), first)
            unavailable = False
            self.assertTrue(refresh.synchronize(self.root, 'main', fetch))
            current = Catalog(self.root)
            self.assertEqual(len(refresh.visible_recipes(current)), 2)
            self.assertFalse(refresh.synchronize(self.root, 'main', fetch, force=True))
            (current.catalog_dir / 'curated/sample-added.json').write_text('{}')
            self.assertTrue(refresh.synchronize(self.root, 'main', fetch, force=True))
            self.assertEqual(Catalog(self.root).compose('sample-added')['id'], 'image-sample-added')
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
