"""Regression tests for catalog options added after an OCI installation."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.recreation import refresh_template


class ConfirmingUI:
    def confirm(self, _message, _default=False):
        return True

    def info(self, _message):
        pass

    def ask(self, _message, default=''):
        return default


class RecreationCatalogTests(unittest.TestCase):
    def test_catalog_index_has_no_unused_template_hashes(self):
        applications = Catalog(ROOT).load_index()['applications']
        self.assertTrue(applications)
        self.assertTrue(all('content_hash' not in item for item in applications))

    def test_internal_template_id_resolves_current_catalog_template(self):
        catalog = Catalog(ROOT)
        previous = catalog.load_template('chromium', generate_if_missing=False)
        self.assertEqual(previous['id'], 'linuxserver-chromium')
        previous = copy.deepcopy(previous)
        previous['catalog_ui']['title']['en_US'] = 'Old Chromium'
        candidate = {'template': previous, 'deployment': {
            'rootfs': {'storage': 'local-lvm'},
            'mounts': [{'container_path': '/config'}],
            'environment': [{'name': item['name'], 'value': item.get('example') or 'value',
                             'sensitive': item['sensitive']}
                            for item in previous['container_contract']['environment']
                            if item['required']],
            'security': {},
        }}

        refresh_template(candidate, ConfirmingUI())

        self.assertEqual(candidate['template']['catalog_ui']['title']['en_US'],
                         catalog.compose('chromium')['catalog_ui']['title']['en_US'])

    def test_navidrome_baseurl_is_optional(self):
        catalog = Catalog(ROOT)
        template = catalog.compose('navidrome')
        base_url = next(item for item in template['container_contract']['environment']
                        if item['name'] == 'ND_BASEURL')
        self.assertFalse(base_url['required'])
        self.assertEqual(base_url['example'], '')

        regenerated = copy.deepcopy(template)
        target = next(item for item in regenerated['container_contract']['environment']
                      if item['name'] == 'ND_BASEURL')
        target['required'] = True
        catalog._preserve_optional_environment('navidrome', regenerated)
        self.assertFalse(target['required'])


if __name__ == '__main__':
    unittest.main()
