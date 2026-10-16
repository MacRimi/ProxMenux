"""Exercise the static-export language repair on real HTML files."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_command_descriptions import require_node


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "web/scripts/localize-export.mjs"


class WebExportLanguageTests(unittest.TestCase):
    def test_locales_nested_pages_preserved_content_and_idempotence(self):
        node = require_node()
        html = '<!doctype html><html lang="en" class="dark"><body><h1>Text</h1><script>const example=\'<html lang="en">\';</script></body></html>'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locales = ["en", "es", "de", "fr", "it", "pt", "sk", "sv"]
            for locale in locales:
                file = root / "out" / locale / "docs/monitor/index.html"
                file.parent.mkdir(parents=True)
                file.write_text(html)
            for relative in ["out/index.html", "out/assets/index.html"]:
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(html)
            result = subprocess.run([node, str(SCRIPT)], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("8 localized pages", result.stdout)
            for locale in locales:
                actual = (root / "out" / locale / "docs/monitor/index.html").read_text()
                self.assertEqual(actual, html.replace('<html lang="en"', f'<html lang="{locale}"', 1))
            for relative in ["out/index.html", "out/assets/index.html"]:
                self.assertEqual((root / relative).read_text(), html)
            tracked = root / "out/de/docs/monitor/index.html"
            before = tracked.stat().st_mtime_ns
            second = subprocess.run([node, str(SCRIPT)], cwd=root, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(tracked.stat().st_mtime_ns, before)
