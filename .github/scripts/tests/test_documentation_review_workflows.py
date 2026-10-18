"""Keep machine generation explicit without losing automatic validation."""
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]


class DocumentationReviewWorkflowTests(unittest.TestCase):
    def workflow(self, name):
        return yaml.load(
            (ROOT / '.github/workflows' / name).read_text(encoding='utf-8'),
            Loader=yaml.BaseLoader,
        )

    def test_generation_requires_explicit_dispatch(self):
        triggers = self.workflow('build-web-docs-i18n.yml')['on']
        self.assertEqual(set(triggers), {'workflow_dispatch'})

    def test_website_changes_keep_automatic_offline_validation(self):
        triggers = self.workflow('test-i18n.yml')['on']
        for event in ('pull_request', 'push'):
            with self.subTest(event=event):
                self.assertIn('web/**', triggers[event]['paths'])


if __name__ == '__main__':
    unittest.main()
