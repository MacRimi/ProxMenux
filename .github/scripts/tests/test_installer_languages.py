"""Every shipped terminal language must be selectable during installation."""
from pathlib import Path
import re
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))
from build_translation_cache import DEFAULT_LANGUAGES


class InstallerLanguageTests(unittest.TestCase):
    def test_both_installers_offer_every_shipped_language(self):
        expected = {'en', *DEFAULT_LANGUAGES}
        for name in ('install_proxmenux.sh', 'install_proxmenux_beta.sh'):
            with self.subTest(installer=name):
                source = (ROOT / name).read_text(encoding='utf-8')
                function = re.search(r'^select_language\(\) \{(.*?)^\}', source, re.M | re.S)
                self.assertIsNotNone(function, 'Missing installer language selector')
                offered = re.findall(r'^\s*"([a-z]{2})"\s+"[^"]+"', function.group(1), re.M)
                self.assertEqual(set(offered), expected)
                self.assertEqual(len(offered), len(expected), 'Duplicate language option')
                # English is the source text in the scripts, not a JSON catalog.
                for language in set(offered) - {'en'}:
                    self.assertTrue((ROOT / 'lang' / f'{language}.json').is_file(), language)


if __name__ == '__main__':
    unittest.main()
