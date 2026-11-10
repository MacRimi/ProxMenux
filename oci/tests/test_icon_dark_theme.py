"""A black icon on a transparent background gets a version for the dark theme,
and every other icon is left as it is."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci import catalog as catalog_module
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.icons import DARK_INVERT, HOMARR_ICON, SELFHST_ICON, IconResolver, is_dark_mark

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - the engine runs without Pillow
    Image = None


def png(draw):
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw(ImageDraw.Draw(image))
    data = io.BytesIO()
    image.save(data, "PNG")
    return data.getvalue()


@unittest.skipIf(Image is None, "Pillow is not installed")
class DarkMarkTests(unittest.TestCase):
    def test_a_black_mark_on_transparent_is_one(self):
        self.assertTrue(is_dark_mark(png(lambda d: d.ellipse((8, 8, 56, 56), fill=(10, 10, 10, 255)))))

    def test_a_white_glyph_on_a_black_tile_shows_on_both_themes(self):
        def tile(d):
            d.rectangle((4, 4, 60, 60), fill=(0, 0, 0, 255))
            d.rectangle((20, 20, 44, 44), fill=(255, 255, 255, 255))
        self.assertFalse(is_dark_mark(png(tile)))

    def test_a_coloured_icon_is_not_one(self):
        self.assertFalse(is_dark_mark(png(lambda d: d.ellipse((8, 8, 56, 56), fill=(30, 90, 200, 255)))))

    def test_an_empty_or_unreadable_icon(self):
        self.assertFalse(is_dark_mark(png(lambda d: None)))
        self.assertIsNone(is_dark_mark(b"not an image"))


def svg(body):
    return f'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 50">{body}</svg>'.encode()


class SvgDarkMarkTests(unittest.TestCase):
    """An SVG is read by the colours it paints with."""

    def test_an_svg_painted_only_in_black_is_one(self):
        self.assertTrue(is_dark_mark(svg('<path d="M0 0h50v50z" fill="#000"/>')))

    def test_a_shape_without_a_fill_or_in_current_colour_draws_black(self):
        self.assertTrue(is_dark_mark(svg('<path d="M0 0h50v50z"/>')))
        self.assertTrue(is_dark_mark(svg('<path d="M0 0h50v50z" fill="currentColor"/>')))

    def test_white_or_coloured_paint_shows_on_the_dark_theme(self):
        self.assertFalse(is_dark_mark(svg('<style>.a{fill:#FFFFFF;}</style><path class="a" d="M0 0h50v50z"/>')))
        self.assertFalse(is_dark_mark(svg('<path d="M0 0h50v50z" fill="#111827"/><path d="M5 5h9v9z" fill="white"/>')))
        self.assertFalse(is_dark_mark(svg('<path d="M0 0h50v50z" fill="#4D6BFE"/>')))


def resolver():
    selfhst = [{"Reference": "anythingllm", "WebP": "Yes", "Light": "Yes", "Dark": "Yes"},
               {"Reference": "immich", "WebP": "Yes", "Light": "Yes", "Dark": "Yes"},
               {"Reference": "calnode", "WebP": "Yes", "Light": "No", "Dark": "No"}]
    homarr = {"webp": ["mark.webp", "mark-light.webp", "plain.webp"]}
    return IconResolver(selfhst, homarr, publishers=[{}, {}])


@unittest.skipIf(Image is None, "Pillow is not installed")
class DarkThemeIconTests(unittest.TestCase):
    black = staticmethod(lambda: png(lambda d: d.rectangle((10, 10, 54, 54), fill=(0, 0, 0, 255))))
    blue = staticmethod(lambda: png(lambda d: d.rectangle((10, 10, 54, 54), fill=(30, 90, 200, 255))))

    def test_a_black_mark_takes_the_light_version_of_its_set(self):
        icons = resolver()
        self.assertEqual(icons.dark_theme_icon(SELFHST_ICON.format(name="anythingllm"), self.black()),
                         SELFHST_ICON.format(name="anythingllm-light"))
        self.assertEqual(icons.dark_theme_icon(HOMARR_ICON.format(name="mark"), self.black()),
                         HOMARR_ICON.format(name="mark-light"))

    def test_without_a_light_version_it_is_inverted(self):
        icons = resolver()
        self.assertEqual(icons.dark_theme_icon(SELFHST_ICON.format(name="calnode"), self.black()), DARK_INVERT)
        self.assertEqual(icons.dark_theme_icon("https://example.invalid/logo.png", self.black()), DARK_INVERT)

    def test_a_coloured_icon_keeps_its_colours_although_a_light_version_exists(self):
        # Most icons with a light version are coloured; that version is plain white.
        self.assertIsNone(resolver().dark_theme_icon(SELFHST_ICON.format(name="immich"), self.blue()))

    def test_an_icon_that_cannot_be_read_is_left_as_it_is(self):
        self.assertIsNone(resolver().dark_theme_icon(SELFHST_ICON.format(name="anythingllm"), None))


class CatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "catalog").mkdir()
        self.index = {"kind": "proxmenux.oci-catalog-index", "applications": [
            {"id": "black", "icon": "https://icons.invalid/black.webp"},
            {"id": "black-again", "icon": "https://icons.invalid/black.webp"},
            {"id": "colour", "icon": "https://icons.invalid/colour.webp", "icon_dark": "invert"},
            {"id": "none"}]}
        (self.root / "catalog/index.json").write_text(json.dumps(self.index))
        self.catalog = Catalog(self.root, catalog_dir=self.root / "catalog")

    def entries(self):
        data = json.loads((self.root / "catalog/index.json").read_text())
        return {item["id"]: item for item in data["applications"]}

    def test_each_entry_gets_or_loses_its_dark_icon_and_each_icon_is_read_once(self):
        fetched = []
        stub = type("Stub", (), {"dark_theme_icon": lambda self, url, data:
                                 "https://icons.invalid/black-light.webp" if data == b"black" else None})()

        def fetch(url):
            fetched.append(url)
            return b"black" if "black" in url else b"colour"
        with patch.object(catalog_module, "_pillow_available", return_value=True):
            self.assertEqual(self.catalog.apply_dark_icons(stub, fetch), {"dark": 2})
        entries = self.entries()
        self.assertEqual(entries["black"]["icon_dark"], "https://icons.invalid/black-light.webp")
        self.assertEqual(entries["black-again"]["icon_dark"], "https://icons.invalid/black-light.webp")
        self.assertNotIn("icon_dark", entries["colour"])
        self.assertNotIn("icon_dark", entries["none"])
        self.assertEqual(sorted(fetched), ["https://icons.invalid/black.webp", "https://icons.invalid/colour.webp"])

    def test_without_pillow_the_index_is_left_as_it_is(self):
        before = (self.root / "catalog/index.json").read_text()
        with patch.object(catalog_module, "_pillow_available", return_value=False):
            self.assertEqual(self.catalog.apply_dark_icons(object(), lambda url: b""), {"dark": -1})
        self.assertEqual((self.root / "catalog/index.json").read_text(), before)


class ShippedIndexTests(unittest.TestCase):
    def test_every_dark_icon_of_the_catalog_is_https_or_inverted(self):
        index = json.loads((ROOT / "catalog/index.json").read_text())
        for item in index["applications"]:
            dark = item.get("icon_dark")
            if dark is not None:
                with self.subTest(app=item["id"]):
                    self.assertTrue(dark == DARK_INVERT or dark.startswith("https://"))
                    self.assertTrue(str(item.get("icon", "")).startswith("https://"))


if __name__ == "__main__":
    unittest.main()
