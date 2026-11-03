"""Catalog delivery is atomic, offline-safe, and never acknowledges unseen apps."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
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

    def test_first_visit_has_zero_new_apps_and_second_visit_clears_acknowledged_news(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        self.assertIn("New applications since your last visit: 0", status.describe())
        status.recipes["new-app"] = "new-recipe-hash"
        self.assertIn("New applications since your last visit: 1", status.describe())
        status.mark_seen()
        same = refresh.CatalogRefresh(self.root, Catalog(self.root))
        same.recipes = status.recipes.copy()
        self.assertIn("New applications since your last visit: 0", same.describe())

    def test_new_app_count_is_not_net_growth_and_modified_recipes_are_separate(self):
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        original = self.item["id"]
        status.baseline = {original: "old-recipe", "removed-app": "hash"}
        status.recipes["new-app"] = "hash"
        self.assertIn("Available applications: 2", status.describe())
        self.assertIn("New applications since your last visit: 1", status.describe())
        self.assertIn("Updated recipes since your last visit: 1", status.describe())

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
        self.assertIn("New applications since your last visit: 1", next_visit.describe())

    def test_main_menu_redraws_totals_and_news_after_background_refresh(self):
        from proxmenux_oci import cli, updates
        from proxmenux_oci.ui import MenuRefresh
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
                    owner.add_app()
                    owner.sync()
                    refresh.write_json(refresh.cache_root(owner.root) / 'main-result.json',
                                       {"ok": True, "changed": True})
                    status.process.poll.return_value = 0
                    self_refreshed = kwargs['refresh']()
                    owner.assertTrue(self_refreshed)
                    raise MenuRefresh()
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
                patch.object(updates, 'UpdateCheck', return_value=checker_context):
            self.assertEqual(cli.interactive(Catalog(self.root)), 0)
        self.assertIn('Available applications: 1', screens[0][0])
        self.assertIn('Available applications: 2', screens[1][0])
        self.assertIn('New applications since your last visit: 1', screens[1][0])
        self.assertIn('(  2)', screens[1][1]['all'])
        next_visit = original_class(self.root, Catalog(self.root))
        self.assertIn('New applications since your last visit: 0', next_visit.describe())

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
                    self.assertIn("Refreshing", status.describe())
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
        self.assertEqual(options['catalog-refresh'], 'Refresh catalog')


if __name__ == "__main__":
    unittest.main()
