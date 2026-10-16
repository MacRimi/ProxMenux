"""Frozen conservative recovery: update the fixture only after explicit review.

Run offline with Python unittest and Node >=22.14 on PATH (or NODE_BINARY).
The consumer test executes only extracted pure lookup functions, not the UI.
"""
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

from test_build_i18n_messages import MODULE, SCRIPT

ROOT = SCRIPT.parents[2]
FIXTURE = json.loads((Path(__file__).parent / "fixtures/command_descriptions.json").read_text())


def require_node():
    diagnostic = "Node >=22.14 is required; install Node 22 LTS or set NODE_BINARY to its executable"
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        raise AssertionError(diagnostic)
    try:
        result = subprocess.run([node, "--version"], capture_output=True, text=True)
    except OSError as exc:
        raise AssertionError(f"{diagnostic}; cannot execute {node}: {exc}") from exc
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", result.stdout.strip())
    if result.returncode or not version or tuple(map(int, version.groups())) < (22, 14, 0):
        raise AssertionError(f"{diagnostic}; found {result.stdout.strip() or result.stderr.strip()!r}")
    return node


def catalog(lang):
    return json.loads((ROOT / f"AppImage/messages/{lang}/common.json").read_text())


class NodeRuntimeTests(unittest.TestCase):
    def test_missing_node_reports_setup_instructions(self):
        with mock.patch.dict(os.environ, {"PATH": "", "NODE_BINARY": ""}):
            with self.assertRaisesRegex(AssertionError, r"Node >=22\.14.*NODE_BINARY"):
                require_node()

    def test_invalid_override_reports_setup_instructions(self):
        with mock.patch.dict(os.environ, {"NODE_BINARY": "/nonexistent/f05-node"}):
            with self.assertRaisesRegex(AssertionError, r"Node >=22\.14.*NODE_BINARY"):
                require_node()

    def test_older_node_reports_detected_version(self):
        with mock.patch.dict(os.environ, {"NODE_BINARY": "node"}), \
                mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
                    ["node", "--version"], 0, "v20.19.0\n", "")):
            with self.assertRaisesRegex(AssertionError, r"Node >=22\.14.*v20\.19\.0"):
                require_node()


class CommandDescriptionsTests(unittest.TestCase):
    def test_real_catalogs_exact_indexed_recovery_and_source_order(self):
        self.assertEqual(catalog("en")["terminal"]["commandDescriptions"], FIXTURE["english"])
        consumer = (ROOT / "AppImage/components/terminal-panel.tsx").read_text()
        commands = re.search(r"const proxmoxCommands = (\[.*?\])", consumer, re.S).group(1)
        commands = json.loads(re.sub(r",\s*\]$", "]", commands))
        self.assertEqual(commands, FIXTURE["commands"])
        self.assertIn('desc: t(`terminal.commandDescriptions.${index}`)', consumer)
        for lang, expected in FIXTURE["locales"].items():
            with self.subTest(locale=lang):
                actual = catalog(lang)["terminal"]["commandDescriptions"]
                self.assertIsInstance(actual, list)
                self.assertEqual(len(actual), len(commands))
                self.assertEqual(actual, expected)
                self.assertTrue(all(isinstance(x, str) and x for x in actual))
        # Explicit English recovery values are frozen locale text, not live fallback.
        for index in FIXTURE["fallback_indices"]:
            self.assertEqual(catalog("sv")["terminal"]["commandDescriptions"][index],
                             FIXTURE["locales"]["sv"][index])

    def assert_completed_catalogs_are_stable(self, *, future_messages=None):
        workflow = (ROOT / ".github/workflows/build-i18n-messages.yml").read_text()
        languages = re.search(r'LANGS="\$\{LANGS:-(.*?)\}"', workflow).group(1)
        self.assertEqual(languages.split(","), list(MODULE.DEFAULT_LANGUAGES))
        locales = ["en", *languages.split(",")]
        shipped = {ROOT / f"AppImage/messages/{lang}/common.json": catalog(lang) for lang in locales}
        original_bytes = {path: path.read_bytes() for path in shipped}

        def strings(node, path=()):
            # Independent traversal: every existing nonempty string, including
            # explicit English and obsolete human keys, must survive completion.
            if isinstance(node, str) and node:
                yield path, node
            elif isinstance(node, dict):
                for key, value in node.items():
                    yield from strings(value, (*path, key))
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    yield from strings(value, (*path, index))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for path in shipped:
                destination = root / path.parent.name / "common.json"
                destination.parent.mkdir()
                shutil.copyfile(path, destination)
            if future_messages is not None:
                source = json.loads((root / "en/common.json").read_text())
                source["futureFeatureFixture"] = future_messages
                (root / "en/common.json").write_text(json.dumps(source))

            argv = [str(SCRIPT), "--source", str(root / "en/common.json"),
                    "--messages-dir", str(root), "--languages", languages, "--sleep", "0"]
            output = io.StringIO()
            # Establish steady state with the real generator and a deterministic
            # offline provider. Translation happens only in disposable catalogs;
            # adding an EN-only feature never needs a hand-maintained seed list.
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(MODULE, "translate_one", side_effect=lambda text, lang, *_: f"TEST {lang} {text}") as seed, \
                    mock.patch.object(MODULE, "write_json", wraps=MODULE.write_json) as initial_writer, \
                    redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(MODULE.main(), 0, output.getvalue())
            self.assertNotRegex(output.getvalue(), r"(?m)^Completed with [0-9]+ translation failures")
            self.assertTrue(all(call.args[0].is_relative_to(root) for call in initial_writer.call_args_list))
            for path, original in shipped.items():
                completed = json.loads((root / path.parent.name / "common.json").read_text())
                for keys, value in strings(original):
                    actual = completed
                    for key in keys:
                        actual = actual[key]
                    self.assertEqual(actual, value, f"{path.parent.name}: {keys}")
                # The recovered arrays remain exact, including frozen English.
                if path.parent.name != "en":
                    self.assertEqual(completed["terminal"]["commandDescriptions"],
                                     FIXTURE["locales"].get(path.parent.name,
                                         original["terminal"]["commandDescriptions"]))
                if future_messages is not None and path.parent.name != "en":
                    self.assertEqual(completed["futureFeatureFixture"], {
                        "title": f"TEST {path.parent.name} Future feature {{count}}",
                        "items": [f"TEST {path.parent.name} First item", {"label": f"TEST {path.parent.name} Second item"}],
                        "enabled": False, "count": 2, "empty": [],
                    })
            if future_messages is not None:
                self.assertGreaterEqual(seed.call_count, 3 * len(languages.split(",")))
            before = {p: p.read_bytes() for p in root.glob("*/common.json")}
            output = io.StringIO()
            # Keep the original strict assertion: once completed, any provider
            # call or catalog write is a regression. No production locale edits.
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(MODULE, "translate_one", side_effect=AssertionError("provider forbidden")) as provider, \
                    mock.patch.object(MODULE, "write_json", side_effect=AssertionError("writes forbidden")) as writer, \
                    redirect_stdout(output), redirect_stderr(output):
                result = MODULE.main()
            self.assertEqual(result, 0, output.getvalue())
            provider.assert_not_called()
            writer.assert_not_called()
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            for lang in languages.split(","):
                self.assertIn(f"{lang}: nothing to translate", output.getvalue())
        self.assertEqual(original_bytes, {path: path.read_bytes() for path in shipped})

    def test_workflow_default_catalogs_rerun_without_provider_or_writes(self):
        self.assert_completed_catalogs_are_stable()

    def test_new_english_feature_preserves_curated_values_and_reruns_without_writes(self):
        self.assert_completed_catalogs_are_stable(future_messages={
            "title": "Future feature {count}",
            "items": ["First item", {"label": "Second item"}],
            "enabled": False, "count": 2, "empty": [],
        })

    def test_actual_consumer_lookup_null_fallback_and_explicit_english(self):
        node = require_node()
        source = (ROOT / "AppImage/lib/i18n/provider.tsx").read_text()
        functions = source[source.index("function getMessage("):source.index("export function I18nProvider(")]
        lookup = re.search(r"      const localized =.*?return interpolate\(.*?\)\n", source, re.S).group(0)
        catalogs = {lang: catalog(lang) for lang in ["en", *FIXTURE["locales"]]}
        script = ('import assert from "node:assert/strict";\n'
                  'type MessageTree = Record<string, unknown>;\n'
                  'type TranslationParams = Record<string, string | number>;\n' + functions +
                  '\nconst MESSAGE_CATALOG = ' + json.dumps(catalogs) + ';\n' +
                  'function t(language: string, key: string, params?: TranslationParams) {\n' + lookup + '}\n' +
                  'const fixture = ' + json.dumps(FIXTURE) + ';\n' + '''
fixture.english.forEach((text, i) => {
  assert.equal(t("en", `terminal.commandDescriptions.${i}`), text);
});
for (const [lang, texts] of Object.entries(fixture.locales)) {
  texts.forEach((text, i) => {
    const key = `terminal.commandDescriptions.${i}`;
    assert.equal(getMessage(MESSAGE_CATALOG[lang], key), text);
    assert.equal(t(lang, key), text);
  });
}
for (const i of fixture.fallback_indices) {
  const key = `terminal.commandDescriptions.${i}`;
  const selected = MESSAGE_CATALOG.sv.terminal.commandDescriptions[i];
  MESSAGE_CATALOG.en.terminal.commandDescriptions[i] = "CHANGED EN";
  assert.equal(t("sv", key), selected); // Explicit English is a locale value.
  MESSAGE_CATALOG.sv.terminal.commandDescriptions[i] = null;
  assert.equal(t("sv", key), "CHANGED EN"); // Null would dynamically fall back.
  MESSAGE_CATALOG.sv.terminal.commandDescriptions[i] = "";
  assert.equal(t("sv", key), ""); // Empty strings do NOT fall back.
}
assert.equal(t("sv", "missing.key"), "missing.key");
console.log("390 indexed consumer lookups; 15 explicit-English/null/empty cases passed");
''')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "consumer.ts"
            path.write_text(script)
            result = subprocess.run([node, "--experimental-strip-types", str(path)],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("390 indexed consumer lookups", result.stdout)


if __name__ == "__main__":
    unittest.main()
