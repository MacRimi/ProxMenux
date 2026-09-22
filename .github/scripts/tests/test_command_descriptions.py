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

    def test_workflow_default_catalogs_rerun_without_provider_or_writes(self):
        workflow = (ROOT / ".github/workflows/build-i18n-messages.yml").read_text()
        languages = re.search(r'LANGS="\$\{LANGS:-(.*?)\}"', workflow).group(1)
        self.assertEqual(languages.split(","), list(MODULE.DEFAULT_LANGUAGES))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for lang in ["en", *languages.split(",")]:
                path = root / lang / "common.json"
                path.parent.mkdir()
                shutil.copyfile(ROOT / f"AppImage/messages/{lang}/common.json", path)
                # This steady-state fixture assumes generation already finished.
                # Seed only the keys the two message PRs introduce; keep the
                # recovered command arrays and the repo catalogs exact. Runtime
                # missing-key fallback is covered by the JSX seam tests and by
                # test_storage_messages.cjs.
                if lang != "en":
                    temporary = json.loads(path.read_text())
                    for section, key in (
                        ("archives", "emptyMessage"),
                        ("destinations", "backupsKeptMessage"),
                        ("destinations", "localAttachHelpMessage"),
                    ):
                        temporary["backup"][section].setdefault(
                            key, catalog("en")["backup"][section][key])
                    temporary["storage"].setdefault(
                        "savedSmartData", catalog("en")["storage"]["savedSmartData"])
                    report = temporary["storage"]["smartReport"]
                    source_report = catalog("en")["storage"]["smartReport"]
                    for key in ("passedAssessment", "noReallocatedSectorsReported",
                                "passedMeaningTitle", "passedMeaning"):
                        report.setdefault(key, source_report[key])
                    for key in ("passedTitle", "passedText"):
                        report["recommendations"].setdefault(
                            key, source_report["recommendations"][key])
                    path.write_text(json.dumps(temporary, ensure_ascii=False))
            before = {p: p.read_bytes() for p in root.glob("*/common.json")}
            argv = [str(SCRIPT), "--source", str(root / "en/common.json"),
                    "--messages-dir", str(root), "--languages", languages, "--sleep", "0"]
            output = io.StringIO()
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
