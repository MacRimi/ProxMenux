"""The Changes view files a change under the post-install section by the name
its script records itself with. Both post-install scripts have to be known to
it, or what one of them changes is shown as the work of an unnamed script."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
VIEW = (ROOT / "AppImage/components/audit-changes.tsx").read_text()
SCRIPTS = ("scripts/post_install/auto_post_install.sh", "scripts/post_install/customizable_post_install.sh")


class PostInstallSourcesTests(unittest.TestCase):
    def setUp(self):
        declared = re.search(r"const POST_INSTALL_SOURCES = new Set\(\[([^\]]*)\]\)", VIEW)
        self.assertIsNotNone(declared)
        self.known = set(re.findall(r'"([^"]+)"', declared.group(1)))

    def test_every_post_install_script_is_known_by_the_name_it_records(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                source = re.search(r'^SCRIPT_SOURCE="([^"]+)"', (ROOT / script).read_text(), re.M)
                self.assertIsNotNone(source)
                self.assertIn(source.group(1), self.known)

    def test_no_name_is_listed_that_no_script_records(self):
        recorded = {re.search(r'^SCRIPT_SOURCE="([^"]+)"', (ROOT / script).read_text(), re.M).group(1)
                    for script in SCRIPTS}
        self.assertEqual(self.known, recorded)

    def test_figurine_and_fastfetch_have_a_name_in_the_view(self):
        for function in ("configure_figurine", "configure_fastfetch"):
            self.assertRegex(VIEW, rf'\b{function}: "')


if __name__ == "__main__":
    unittest.main()
