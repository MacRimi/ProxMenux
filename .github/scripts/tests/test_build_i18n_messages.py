"""Offline regression tests for the Monitor catalog generator."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout, redirect_stderr

SCRIPT = Path(__file__).parents[1] / "build_i18n_messages.py"
SPEC = importlib.util.spec_from_file_location("build_i18n_messages", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class I18nMessagesTests(unittest.TestCase):
    def run_generator(self, source, target, *options, provider=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            en = root / "en" / "common.json"
            it = root / "it" / "common.json"
            en.parent.mkdir()
            it.parent.mkdir()
            en.write_text(json.dumps(source), encoding="utf-8")
            it.write_text(json.dumps(target), encoding="utf-8")
            before = it.read_bytes()
            argv = [str(SCRIPT), "--source", str(en), "--messages-dir", str(root),
                    "--languages", "it", "--sleep", "0", *options]
            output = io.StringIO()
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                MODULE, "translate_one", side_effect=provider or (lambda text, *args: "IT " + text)
            ) as translate, redirect_stdout(output), redirect_stderr(output):
                result = MODULE.main()
            return result, json.loads(it.read_text()), translate.call_args_list, output.getvalue(), before == it.read_bytes()

    def test_generator_fills_array_leaves_preserving_existing_values(self):
        source = {"items": ["One", {"title": "Two", "children": ["Three"]}],
                  "empty": [], "object": {}, "enabled": True, "count": 2, "none": None}
        target = {"items": ["Uno"], "extra": {"0": "Keep"}}
        result, actual, calls, _, _ = self.run_generator(source, target, "--save-every", "1")
        self.assertEqual(result, 0)
        self.assertEqual(actual, {**source, "items": ["Uno", {"title": "IT Two", "children": ["IT Three"]}],
                                  "extra": {"0": "Keep"}})
        self.assertEqual([call.args[0] for call in calls], ["Two", "Three"])

    def test_wrong_types_defer_locale_without_calls_or_writes_even_on_refresh(self):
        source = {"new": "New", "terminal": {"commandDescriptions": ["One", "Two"]}}
        for malformed in ["['Uno', 'Due']", '["Uno", "Due"]', "ambiguous human text", {}, None, 7]:
            for options in [(), ("--refresh",)]:
                with self.subTest(malformed=malformed, options=options):
                    target = {"terminal": {"commandDescriptions": malformed}, "human": "Keep"}
                    result, actual, calls, output, unchanged = self.run_generator(source, target, *options)
                    self.assertEqual(result, 1)
                    self.assertEqual(actual, target)
                    self.assertTrue(unchanged)
                    self.assertEqual(calls, [])
                    self.assertIn("/terminal/commandDescriptions", output)
                    self.assertIn("manual", output)

    def test_structure_only_catalog_is_written_without_translation(self):
        source = {"items": ["", [], {}, None, False, 0]}
        result, actual, calls, _, _ = self.run_generator(source, {})
        self.assertEqual(result, 0)
        self.assertEqual(actual, source)
        self.assertEqual(calls, [])

    def test_limit_keeps_array_positions_as_null_fallbacks(self):
        result, actual, calls, _, _ = self.run_generator(
            {"items": ["One", "", "Three", "Four"]}, {}, "--limit", "1")
        self.assertEqual(actual, {"items": ["IT One", "", None, None]})
        self.assertEqual(len(calls), 1)

    def test_existing_nonempty_including_english_and_stale_text_is_unchanged(self):
        source = {"items": ["Changed English", "CPU", "Three"]}
        target = {"items": ["Human translation", "CPU", "Tre", "Extra"]}
        result, actual, calls, _, unchanged = self.run_generator(source, target)
        self.assertEqual(actual, target)
        self.assertEqual(calls, [])
        self.assertTrue(unchanged)

    def test_second_run_retries_null_placeholders_preserving_translations(self):
        source = {"items": ["One", "Two", "", "Three", "Four"]}
        target = {"items": ["Human"], "extra": "Keep"}
        result, first, calls, _, _ = self.run_generator(source, target, "--limit", "1")
        self.assertEqual(result, 0)
        self.assertEqual(first, {"items": ["Human", "IT Two", "", None, None], "extra": "Keep"})
        self.assertEqual([call.args[0] for call in calls], ["Two"])
        result, second, calls, _, _ = self.run_generator(source, first, "--save-every", "1")
        self.assertEqual(result, 0)
        self.assertEqual(second, {"items": ["Human", "IT Two", "", "IT Three", "IT Four"], "extra": "Keep"})
        self.assertEqual([call.args[0] for call in calls], ["Three", "Four"])

    def test_refresh_and_provider_failure_keep_existing_fallback_semantics(self):
        def provider(text, *args):
            if text == "Two":
                raise RuntimeError("offline fixture failure")
            return "IT " + text
        result, actual, calls, output, _ = self.run_generator(
            {"items": ["One", "Two", "Three"]}, {"items": ["Uno", "Due"]},
            "--refresh", "--save-every", "1", provider=provider)
        self.assertEqual(result, 0)
        self.assertEqual(actual, {"items": ["IT One", "Due", "IT Three"]})
        self.assertEqual(len(calls), 3)
        self.assertIn("1 translation failures", output)

    def test_null_and_empty_string_are_filled_and_tokens_restored(self):
        source = {"items": ["Hello {vmid}", "Use Proxmox"]}
        result, actual, calls, _, _ = self.run_generator(source, {"items": [None, ""]})
        self.assertEqual(actual, {"items": ["IT Hello {vmid}", "IT Use Proxmox"]})
        self.assertNotIn("{vmid}", calls[0].args[0])
        self.assertNotIn("Proxmox", calls[1].args[0])

    def test_root_pointer_is_empty_not_empty_key_pointer(self):
        for source, target, pointer in [({"a": "Text"}, [], 'JSON Pointer "" (root)'),
                                        ({"": []}, {"": "Text"}, 'JSON Pointer "/"'),
                                        ({"a~/": []}, {"a~/": "Text"}, 'JSON Pointer "/a~0~1"')]:
            with self.subTest(pointer=pointer):
                result, _, calls, output, unchanged = self.run_generator(source, target)
                self.assertEqual(result, 1)
                self.assertEqual(calls, [])
                self.assertTrue(unchanged)
                self.assertIn(pointer + ": expected", output)

    def test_wrong_scalar_and_nested_types_are_rejected(self):
        for source, target in [({"a": "Text"}, {"a": 42}),
                               ({"a": [{"b": "Text"}]}, {"a": ["human"]}),
                               ({"a": False}, {"a": 0}),
                               ({"a": {}}, {"a": []})]:
            with self.subTest(source=source):
                result, actual, calls, _, unchanged = self.run_generator(source, target)
                self.assertEqual(result, 1)
                self.assertTrue(unchanged)
                self.assertEqual(calls, [])

    def test_real_english_array_round_trip_and_generation(self):
        catalog = json.loads((SCRIPT.parents[2] / "AppImage/messages/en/common.json").read_text())
        descriptions = catalog["terminal"]["commandDescriptions"]
        self.assertIsInstance(descriptions, list)
        self.assertTrue(descriptions)
        self.assertEqual(MODULE.unflatten(MODULE.flatten(catalog)), catalog)
        result, actual, calls, _, _ = self.run_generator({"terminal": {"commandDescriptions": descriptions}}, {})
        self.assertEqual(len(calls), sum(isinstance(text, str) and bool(text) for text in descriptions))
        self.assertEqual(actual["terminal"]["commandDescriptions"], ["IT " + text for text in descriptions])

    def test_preflight_skips_invalid_locales_but_processes_valid_locales(self):
        for options in [(), ("--refresh",)]:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                catalogs = {"en": {"items": ["One", "Two"]},
                            "sk": {"items": ["Human"]},
                            "it": {"items": "Uno"}, "de": {"items": {}}}
                for lang, data in catalogs.items():
                    path = root / lang / "common.json"
                    path.parent.mkdir()
                    path.write_text(json.dumps(data))
                before = {lang: (root / lang / "common.json").read_bytes() for lang in catalogs}
                reads = []
                real_read = MODULE.read_json

                def read(path):
                    reads.append(path.parent.name)
                    return real_read(path)

                def translate(text, lang, *args):
                    self.assertEqual(reads, ["en", "sk", "it", "de"])
                    self.assertEqual(lang, "sk")
                    return "SK " + text

                argv = [str(SCRIPT), "--source", str(root / "en/common.json"),
                        "--messages-dir", str(root), "--languages", "sk,it,de",
                        "--sleep", "0", "--save-every", "1", *options]
                output = io.StringIO()
                with mock.patch.object(sys, "argv", argv), \
                        mock.patch.object(MODULE, "read_json", side_effect=read), \
                        mock.patch.object(MODULE, "translate_one", side_effect=translate) as provider, \
                        mock.patch.object(MODULE, "write_json", wraps=MODULE.write_json) as writer, \
                        redirect_stderr(output), redirect_stdout(output):
                    self.assertEqual(MODULE.main(), 1)
                self.assertEqual(json.loads((root / "sk/common.json").read_text()),
                                 {"items": ["SK One" if options else "Human", "SK Two"]})
                self.assertEqual(provider.call_count, 2 if options else 1)
                self.assertTrue(all(call.args[0].parent.name == "sk" for call in writer.call_args_list))
                for lang in ["en", "it", "de"]:
                    self.assertEqual((root / lang / "common.json").read_bytes(), before[lang])
                self.assertIn("Partial failure: skipped 2 locale(s): it, de", output.getvalue())
                self.assertNotIn("generated successfully", output.getvalue())

    def test_round_trip_preserves_json_types_and_literal_keys(self):
        catalog = {"terminal": {"commandDescriptions": ["One", {"nested": ["Two", [], {}]}]},
                   "0": {"a.b": "literal", "": None}, "flags": [True, False, 2, 1.5]}
        self.assertEqual(MODULE.unflatten(MODULE.flatten(catalog)), catalog)


if __name__ == "__main__":
    unittest.main()
