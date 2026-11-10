"""The Community Scripts cache gives each black logo its dark-theme version."""
import importlib.util
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[3]


def load():
    spec = importlib.util.spec_from_file_location("generate_helpers_cache", ROOT / ".github/scripts/generate_helpers_cache.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DarkLogoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = load()

    def icons(self, fetched):
        def fetch_icon(url):
            fetched.append(url)
            return b"black" if "black" in url else b"colour"
        resolver = types.SimpleNamespace(dark_theme_icon=lambda url, data: url.replace(".webp", "-light.webp") if data == b"black" else None)
        return types.SimpleNamespace(fetch_icon=fetch_icon, IconResolver=lambda: resolver)

    def test_new_logos_are_checked_and_known_ones_keep_their_answer(self):
        fetched = []
        cache = [{"slug": "a", "logo": "https://i.invalid/black.webp"}, {"slug": "a2", "logo": "https://i.invalid/black.webp"},
                 {"slug": "b", "logo": "https://i.invalid/colour.webp"}, {"slug": "c", "logo": "https://i.invalid/known.webp"},
                 {"slug": "d", "logo": ""}]
        previous = [{"logo": "https://i.invalid/known.webp", "logo_dark": "invert"}]
        dark = self.generator.apply_dark_logos(cache, previous, self.icons(fetched))
        self.assertEqual(sorted(fetched), ["https://i.invalid/black.webp", "https://i.invalid/colour.webp"])
        self.assertEqual([e.get("logo_dark") for e in cache],
                         ["https://i.invalid/black-light.webp", "https://i.invalid/black-light.webp", "", "invert", None])
        self.assertEqual(dark, 3)

    def test_without_pillow_previous_answers_are_kept_and_nothing_is_fetched(self):
        cache = [{"logo": "https://i.invalid/known.webp"}, {"logo": "https://i.invalid/new.webp"}]
        self.generator.apply_dark_logos(cache, [{"logo": "https://i.invalid/known.webp", "logo_dark": ""}], None)
        self.assertEqual(cache[0]["logo_dark"], "")
        self.assertNotIn("logo_dark", cache[1])


if __name__ == "__main__":
    unittest.main()
