"""Validate complete catalogs without rejecting intentional English fallback."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "check_web_docs_catalogs.py"


class WebDocsCatalogTests(unittest.TestCase):
    def run_check(self, root, *options):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--messages-dir", str(root),
             "--languages", "de", *options],
            capture_output=True, text=True,
        )

    def write_catalog(self, root, locale, content):
        file = root / locale / "common.json"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(content), encoding="utf-8")

    def test_partial_catalog_keeps_fallback_but_complete_mode_reports_gap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_catalog(root, "en", {"title": "Updates", "body": "Check the host."})
            self.write_catalog(root, "de", {"title": "Aktualisierungen"})
            partial = self.run_check(root)
            self.assertEqual(partial.returncode, 0, partial.stdout + partial.stderr)
            self.assertIn("missing=1", partial.stdout)
            complete = self.run_check(root, "--require-complete")
            self.assertEqual(complete.returncode, 1, complete.stdout + complete.stderr)
            self.assertIn("schema differs", complete.stdout)

    def test_translated_code_is_rejected_in_both_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_catalog(root, "en", {"body": "Run <code>apt update</code>."})
            self.write_catalog(root, "de", {"body": "Führe <code>apt aktualisieren</code> aus."})
            for options in ((), ("--require-complete",)):
                with self.subTest(options=options):
                    result = self.run_check(root, *options)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_literal_metadata_is_required_but_labels_can_be_localized(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_catalog(root, "en", {"label": "Updates", "tone": "blue"})
            self.write_catalog(root, "de", {"label": "Aktualisierungen", "tone": "blau"})
            invalid = self.run_check(root, "--require-complete")
            self.assertEqual(invalid.returncode, 1, invalid.stdout + invalid.stderr)
            self.assertIn("rendering metadata differ", invalid.stdout)
            self.write_catalog(root, "de", {"label": "Aktualisierungen", "tone": "blue"})
            valid = self.run_check(root, "--require-complete")
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
