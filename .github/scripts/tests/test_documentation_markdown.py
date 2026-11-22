"""Keep the canonical conduct policy and its English website source in sync."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


class DocumentationMarkdownTests(unittest.TestCase):
    def test_english_conduct_body_matches_canonical_policy(self):
        source = json.loads((ROOT / 'web/messages/en/docs/about/code-of-conduct.json').read_text(encoding='utf-8'))
        self.assertEqual(source['contentMarkdown'], (ROOT / 'CODE_OF_CONDUCT.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
