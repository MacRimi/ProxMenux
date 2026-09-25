import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))

from oci_description import render
from oci_instances import identity


CATALOG = Path(__file__).resolve().parents[1] / 'catalog' / 'apps'
INSTANCE = '978b58f3-d8b1-41a6-b7aa-a7ecac76b57f'


class DescriptionTests(unittest.TestCase):
    def test_adguard_notes_keep_identity_and_both_access_links(self):
        template = json.loads((CATALOG / 'adguard-home.json').read_text())
        notes = render(template, 'sha256:abc', INSTANCE, '192.168.0.42')
        self.assertEqual(identity(('description: ' + notes.replace('\n', '\\n') + '\n').encode()), INSTANCE)
        self.assertIn('/docs/oci-manager', notes)
        self.assertIn('hub.docker.com/r/adguard/adguardhome', notes)
        self.assertIn('http://192.168.0.42:3000/', notes)
        self.assertIn('http://192.168.0.42:80/', notes)
        self.assertNotIn('Digest:', notes)
        self.assertIn('img.shields.io/badge/%F0%9F%93%9A_Docs-blue', notes)
        self.assertIn('img.shields.io/badge/%F0%9F%92%BB_Code-green', notes)
        self.assertIn('img.shields.io/badge/%E2%98%95_Ko--fi-red', notes)
        self.assertIn('Image: <code>adguard/adguardhome:latest</code> ', notes)
        self.assertIn('>Image</a> &middot; ', notes)
        self.assertIn('>App</a>', notes)
        self.assertIn('href="http://192.168.0.42:3000/" target="_blank" rel="noopener noreferrer">Setup (first run)</a>', notes)
        self.assertIn('>http://192.168.0.42:3000/</a>', notes)
        self.assertIn('href="http://192.168.0.42:80/" target="_blank" rel="noopener noreferrer">Web UI (after setup)</a>', notes)
        self.assertIn('>http://192.168.0.42:80/</a>', notes)

    def test_missing_ip_does_not_publish_placeholder_links(self):
        template = json.loads((CATALOG / 'adguard-home.json').read_text())
        notes = render(template, '', INSTANCE)
        self.assertNotIn('http://:3000', notes)
        self.assertIn('proxmenux-instance=' + INSTANCE, notes)

    def test_untrusted_title_is_escaped(self):
        template = {'id': 'example', 'catalog_ui': {'title': {'en_US': '<script>x</script>'}},
                    'container_contract': {'image': {'reference': 'example:latest'}}}
        notes = render(template, '', INSTANCE)
        self.assertNotIn('<script>', notes)
        self.assertIn('&lt;script&gt;', notes)


if __name__ == '__main__':
    unittest.main()
