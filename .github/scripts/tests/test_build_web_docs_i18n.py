import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "build_web_docs_i18n.py"
SPEC = importlib.util.spec_from_file_location("build_web_docs_i18n", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class WebDocsI18nTests(unittest.TestCase):
    def run_generator(self, root, provider):
        source_root = root / "messages" / "en"
        messages_root = root / "messages"
        state_path = messages_root / ".docs-i18n-source-state.json"
        argv = [
            str(SCRIPT),
            "--source-dir",
            str(source_root),
            "--messages-dir",
            str(messages_root),
            "--languages",
            "de",
            "--source-state",
            str(state_path),
            "--workers",
            "1",
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            MODULE, "provider_function", return_value=provider
        ):
            return MODULE.main()

    def test_protected_contract_round_trip(self):
        source = (
            "Run <code>systemctl restart pveproxy</code> in Proxmox VE, "
            "then open <link>Settings</link> at {host}."
        )
        protected, mapping = MODULE.protect_text(source)
        self.assertIn("<code>systemctl restart pveproxy</code>", protected)
        self.assertNotIn("Proxmox VE", protected)
        self.assertIn("<code>", protected)
        self.assertIn("</code>", protected)
        self.assertIn("<link>", protected)
        self.assertIn("</link>", protected)
        self.assertNotIn("<code>", mapping.values())
        self.assertNotIn("</code>", mapping.values())
        self.assertNotIn("systemctl", mapping.values())
        self.assertEqual(MODULE.restore_text(protected, mapping), source)

    def test_human_translation_is_not_pending(self):
        source = {"title": "Updates", "url": "https://example.com"}
        target = {"title": "Actualizaciones", "url": "https://example.com"}
        self.assertEqual(MODULE.pending_leaves(source, target), [])

    def test_rendering_metadata_is_copied_but_visible_labels_are_translated(self):
        for key, value in (("tone", "amber"), ("variant", "source"),
                           ("accent", "border-blue-300 bg-blue-50"),
                           ("iconBg", "bg-blue-100 text-blue-700"),
                           ("color", "green")):
            with self.subTest(key=key):
                self.assertTrue(MODULE.should_copy(value, ("steps", 0, key)))
                self.assertFalse(MODULE.should_copy(value, ("label",)))
                self.assertEqual(MODULE.merge_tree({key: value}, {key: "translated"}, {}), {key: value})
        self.assertFalse(MODULE.should_copy("Translation", ("type",)))
        self.assertFalse(MODULE.should_copy("English", ("lang",)))
        for value in ("loader", "dedicated"):
            self.assertTrue(MODULE.should_copy(value, ("cards", 0, "flow")))
            self.assertFalse(MODULE.should_copy(value, ("label",)))

    def test_literal_only_examples_and_api_routes_are_not_translation_gaps(self):
        for source in ("<code>apt update</code>",
                       "<code>net0</code> / <code>net1</code>.",
                       "/api/task-log/&lt;upid&gt;", "/api/vms/<vmid>/config"):
            with self.subTest(source=source):
                self.assertTrue(MODULE.should_copy(source, ("cell",)))
        self.assertFalse(MODULE.should_copy("Run <code>apt update</code> first.", ("body",)))
        self.assertFalse(MODULE.should_copy("After running the command, check its output.", ("afterCode",)))
        self.assertFalse(MODULE.should_copy("Before running the command, read this.", ("beforeCode",)))
        self.assertTrue(MODULE.should_copy("curl http://localhost:8008/api/health", ("curlCode",)))

    def test_inline_identifiers_and_encoded_delimiters_round_trip(self):
        source = "Set RS_SKIP_PATHS, call _rs_apply_hot and keep localStorage at &lt;host&gt;."
        protected, mapping = MODULE.protect_text(source)
        for literal in ("RS_SKIP_PATHS", "_rs_apply_hot", "localStorage", "&lt;", "&gt;"):
            self.assertIn(literal, mapping.values())
            self.assertNotIn(literal, protected)
        self.assertEqual(MODULE.restore_text(protected, mapping), source)

    def test_literal_only_changes_sync_without_retranslating_human_prose(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "messages/en/common.json"
            target = root / "messages/de/common.json"
            source.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            source.write_text(json.dumps({"title": "Updates", "code": "tool --version=2", "tone": "blue"}))
            target.write_text(json.dumps({"title": "Aktualisierungen", "code": "tool --version=1", "tone": "blau"}))
            provider = mock.Mock(side_effect=AssertionError("Existing prose must not be retranslated"))
            self.assertEqual(self.run_generator(root, provider), 0)
            self.assertEqual(json.loads(target.read_text()), {
                "title": "Aktualisierungen", "code": "tool --version=2", "tone": "blue",
            })
            provider.assert_not_called()
            before = target.stat().st_mtime_ns
            self.assertEqual(self.run_generator(root, provider), 0)
            self.assertEqual(target.stat().st_mtime_ns, before)
            provider.assert_not_called()

    def test_changed_source_text_is_pending_even_with_existing_translation(self):
        source = {"title": "Updated installation guidance"}
        target = {"title": "Vorherige Installationsanleitung"}
        token = MODULE.leaf_token(("title",))
        leaves = MODULE.pending_leaves(
            source,
            target,
            forced_tokens={token},
        )
        self.assertEqual([leaf.path for leaf in leaves], [("title",)])

    def test_source_fingerprints_change_per_leaf(self):
        before = MODULE.source_fingerprints({"title": "One", "body": "Same"})
        after = MODULE.source_fingerprints({"title": "Two", "body": "Same"})
        self.assertNotEqual(
            before[MODULE.leaf_token(("title",))],
            after[MODULE.leaf_token(("title",))],
        )
        self.assertEqual(
            before[MODULE.leaf_token(("body",))],
            after[MODULE.leaf_token(("body",))],
        )

    def test_schema_mismatch_detects_removed_keys(self):
        self.assertFalse(
            MODULE.schema_matches(
                {"title": "Title"},
                {"title": "Título", "removed": "Old"},
            )
        )

    def test_schema_mismatch_detects_changed_structural_values(self):
        self.assertFalse(
            MODULE.schema_matches(
                {"enabled": True, "retries": 2},
                {"enabled": False, "retries": 2},
            )
        )

    def test_schema_allows_localized_string_values(self):
        self.assertTrue(
            MODULE.schema_matches(
                {"title": "Updates"},
                {"title": "Aktualisierungen"},
            )
        )

    def test_translatable_rich_tags_use_opaque_names(self):
        source = (
            "Keep <strong>this</strong>, <em>that</em> and "
            "<code>systemctl restart pveproxy</code>."
        )
        protected, mapping = MODULE.protect_rich_tags(source)
        self.assertIn("<pmxrich0000>this</pmxrich0000>", protected)
        self.assertIn("<pmxrich0001>that</pmxrich0001>", protected)
        self.assertIn("<code>systemctl restart pveproxy</code>", protected)
        self.assertEqual(MODULE.restore_rich_tags(protected, mapping), source)

    def test_source_schema_drives_output(self):
        source = {"title": "Title", "items": ["One", "Two"]}
        target = {
            "title": "Título",
            "items": ["Uno", "Dos", "Obsoleto"],
            "removed": "Old",
        }
        translated = {
            ("items", 0): "Uno",
            ("items", 1): "Dos",
        }
        self.assertEqual(
            MODULE.merge_tree(source, target, translated),
            {"title": "Título", "items": ["Uno", "Dos"]},
        )

    def test_translation_memory_ignores_conflicts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "messages" / "en"
            target_root = root / "messages" / "es"
            source_root.mkdir(parents=True)
            target_root.mkdir(parents=True)
            (source_root / "one.json").write_text(
                json.dumps({"label": "Settings"}), encoding="utf-8"
            )
            (target_root / "one.json").write_text(
                json.dumps({"label": "Ajustes"}), encoding="utf-8"
            )
            (source_root / "two.json").write_text(
                json.dumps({"label": "Settings"}), encoding="utf-8"
            )
            (target_root / "two.json").write_text(
                json.dumps({"label": "Configuración"}), encoding="utf-8"
            )
            memory = MODULE.collect_memory(source_root, root / "messages", "es")
            self.assertNotIn("Settings", memory)

    def test_source_state_retranslates_an_existing_changed_leaf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "messages" / "en" / "page.json"
            target_path = root / "messages" / "de" / "page.json"
            source_path.parent.mkdir(parents=True)
            target_path.parent.mkdir(parents=True)
            source_path.write_text(json.dumps({"title": "Original"}), encoding="utf-8")
            target_path.write_text(json.dumps({"title": "Ursprünglich"}), encoding="utf-8")

            self.assertEqual(
                self.run_generator(root, lambda *_: self.fail("provider called during baseline")),
                0,
            )
            self.assertEqual(read_json_file(target_path), {"title": "Ursprünglich"})

            source_path.write_text(json.dumps({"title": "Changed"}), encoding="utf-8")
            calls = []

            def provider(text, language):
                calls.append((text, language))
                return "Geändert"

            self.assertEqual(self.run_generator(root, provider), 0)
            self.assertEqual(calls, [("Changed", "de")])
            self.assertEqual(read_json_file(target_path), {"title": "Geändert"})

    def test_new_leaf_preserves_translation_supplied_with_source_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "messages" / "en" / "page.json"
            target_path = root / "messages" / "de" / "page.json"
            source_path.parent.mkdir(parents=True)
            target_path.parent.mkdir(parents=True)
            source_path.write_text(json.dumps({"title": "Original"}), encoding="utf-8")
            target_path.write_text(json.dumps({"title": "Ursprünglich"}), encoding="utf-8")
            self.assertEqual(self.run_generator(root, lambda *_: "unused"), 0)

            source_path.write_text(
                json.dumps({"title": "Original", "new": "New text"}),
                encoding="utf-8",
            )
            target_path.write_text(
                json.dumps({"title": "Ursprünglich", "new": "Neuer Text"}),
                encoding="utf-8",
            )
            self.assertEqual(
                self.run_generator(root, lambda *_: self.fail("manual translation overwritten")),
                0,
            )
            self.assertEqual(
                read_json_file(target_path),
                {"title": "Ursprünglich", "new": "Neuer Text"},
            )


def read_json_file(path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
