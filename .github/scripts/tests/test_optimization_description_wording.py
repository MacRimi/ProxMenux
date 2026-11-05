"""Wording contracts through the real metadata parser and exact-match formatter.

No post-install function or scanner is imported or executed. Node 22.6+ is
required, as in test_command_descriptions.py; no npm dependencies are needed.
"""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]


class OptimizationDescriptionWordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Admit only the pure parser and its actual dependencies, not the scanner.
        path = ROOT / "AppImage/scripts/post_install_versions.py"
        functions = {"_read_text", "_version_tuple", "parse_post_install_script"}
        constants = {"_FN_DEF_RE", "_VERSION_RE", "_DESC_RE", "_REGISTER_RE", "_HEREDOC_RE"}
        nodes: list[ast.stmt] = [node for node in ast.parse(path.read_text(encoding="utf-8")).body
                 if (isinstance(node, ast.FunctionDef) and node.name in functions)
                 or (isinstance(node, ast.Assign) and any(
                     isinstance(target, ast.Name) and target.id in constants
                     for target in node.targets))]
        if len(nodes) != len(functions) + len(constants):
            raise AssertionError("Metadata parser seam changed: review its dependencies")
        scope = {"re": re, "Path": Path}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
        cls.metadata = {
            source: scope["parse_post_install_script"](ROOT / "scripts/post_install" / filename)
            for source, filename in (("auto", "auto_post_install.sh"),
                                     ("custom", "customizable_post_install.sh"))
        }
        cls.catalogs = {
            locale: json.loads((ROOT / f"AppImage/messages/{locale}/common.json").read_text(encoding="utf-8"))
            for locale in ("en", "it")
        }
        node = os.environ.get("NODE_BINARY") or shutil.which("node")
        if not node:
            raise AssertionError("Install Node.js 22.6+ or set NODE_BINARY")
        cls.node = node
        version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", version)
        if not match or tuple(map(int, match.groups())) < (22, 6, 0):
            raise AssertionError(f"Node.js 22.6+ required; detected {version.strip()}")
        # Replace only the JSON import; the formatter body executes unchanged.
        formatter = (ROOT / "AppImage/lib/optimization-descriptions.ts").read_text(encoding="utf-8")
        json_import = 'import enMessages from "../messages/en/common.json"'
        if formatter.count(json_import) != 1:
            raise AssertionError("Formatter import seam changed")
        fixture = formatter.replace(json_import, "const enMessages = " + json.dumps(cls.catalogs["en"]))
        fixture += '''
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const [key, description, italian, catalogs] = JSON.parse(readFileSync(0, "utf8"));
for (const locale of ["en", "it"]) {
  const calls: string[] = [];
  const t = (path: string) => {
    calls.push(path);
    return path.split(".").reduce((value, part) => value[part], catalogs[locale]);
  };
  assert.equal(optimizationDescription(description, t), locale === "en" ? description : italian);
  assert.deepEqual(calls, [`settings.optimizations.toolDescriptions.${key}`]);
  calls.length = 0;
  const unknown = description + " [new server wording]";
  assert.equal(optimizationDescription(unknown, t), unknown);
  assert.deepEqual(calls, []);
}
console.log("PASS actual exact lookup: EN/IT and unknown-description fallback");
'''
        cls.directory = tempfile.TemporaryDirectory(prefix="optimization-wording-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.fixture = Path(cls.directory.name) / "formatter.mts"
        cls.fixture.write_text(fixture, encoding="utf-8")

    def assert_description(self, key, source, tool, function, english, italian):
        for locale, expected in (("en", english), ("it", italian)):
            with self.subTest(key=key, locale=locale):
                self.assertEqual(self.catalogs[locale]["settings"]["optimizations"]["toolDescriptions"][key], expected)
        metadata = self.metadata[source][tool]
        self.assertEqual(metadata["function"], function)
        self.assertEqual(metadata["description"], english)
        result = subprocess.run(
            [self.node, "--experimental-strip-types", str(self.fixture)],
            input=json.dumps([key, metadata["description"], italian, self.catalogs]),
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS actual exact lookup", result.stdout)

    def test_log2ram_auto_fresh_install_detection_and_update_size(self):
        self.assert_description(
            "log2ramAuto", "auto", "log2ram", "install_log2ram_auto",
            "Fresh installs size Log2RAM from host RAM and ask for confirmation if storage is not detected as SSD. Updates preserve the configured size.",
            "Alla prima installazione, dimensiona Log2RAM in base alla RAM dell'host e chiede conferma se il dispositivo di archiviazione non viene rilevato come SSD. Gli aggiornamenti mantengono la dimensione configurata.")

    def test_kexec_prepares_unit_and_alias_not_hotkey(self):
        self.assert_description(
            "kexec", "custom", "kexec", "enable_kexec",
            "Install kexec-tools and prepare a systemd unit plus the reboot-quick alias for fast reboots that skip BIOS/POST.",
            "Installa kexec-tools e prepara un'unità systemd e l'alias reboot-quick per riavvii rapidi che saltano BIOS/POST.")

    def test_amd_only_claims_idle_parameter_and_kvm_module_options(self):
        self.assert_description(
            "amd", "custom", "amd_fixes", "apply_amd_fixes",
            "Apply idle=nomwait and KVM module options on AMD EPYC/Ryzen hosts.",
            "Applica idle=nomwait e opzioni del modulo KVM sugli host AMD EPYC/Ryzen.")

    def test_guest_agent_only_lists_supported_environments_and_skip(self):
        self.assert_description(
            "guestAgent", "custom", "guest_agent", "install_guest_agent",
            "Detect QEMU/KVM, VMware or VirtualBox and install the matching guest agent; skip other environments.",
            "Rileva QEMU/KVM, VMware o VirtualBox e installa il guest agent corrispondente; salta gli altri ambienti.")

    def test_backup_describes_global_defaults_without_speed_guarantee(self):
        self.assert_description(
            "backupLimits", "custom", "vzdump_speed", "optimize_vzdump",
            "Set global vzdump defaults to bwlimit: 0 and ionice: 5. This does not guarantee faster backups.",
            "Imposta i valori predefiniti globali di vzdump su bwlimit: 0 e ionice: 5. Questo non garantisce backup più veloci.")

    def test_log2ram_custom_choices_and_update_preservation(self):
        self.assert_description(
            "log2ramCustom", "custom", "log2ram", "configure_log2ram",
            "Install Log2RAM with a chosen size, sync interval and optional autosync. Updates preserve the size and autosync choice.",
            "Installa Log2RAM con dimensione e intervallo di sincronizzazione a scelta e autosync facoltativo. Gli aggiornamenti mantengono la dimensione e la scelta sull'autosync.")


if __name__ == "__main__":
    unittest.main()
