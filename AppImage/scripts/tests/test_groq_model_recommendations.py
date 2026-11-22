"""Provider model ordering and curated availability, without credentials/network."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_providers.groq_provider import GroqProvider


class GroqModelRecommendationsTests(unittest.TestCase):
    def fetch(self, ids):
        response = io.BytesIO(json.dumps({'data': [{'id': model} for model in ids]}).encode())
        with patch('ai_providers.groq_provider.urllib.request.urlopen', return_value=response) as request:
            models = GroqProvider(api_key='fixture-only').list_models()
        self.assertEqual(request.call_args.kwargs['timeout'], 10)
        return models

    def test_current_verified_models_precede_legacy_and_unknown_families(self):
        listed = ['mixtral-fixture', 'allam-2-7b', 'llama-3.3-70b-versatile',
                  'openai/gpt-oss-120b', 'qwen/qwen3.8-27b', 'openai/gpt-oss-20b']
        self.assertEqual(self.fetch(listed)[:3],
                         ['openai/gpt-oss-20b', 'openai/gpt-oss-120b', 'qwen/qwen3.8-27b'])
        self.assertCountEqual(self.fetch(listed), listed)

    def test_recommendations_never_invent_models_or_remove_arabic_model(self):
        self.assertEqual(self.fetch(['allam-2-7b']), ['allam-2-7b'])
        self.assertEqual(self.fetch([]), [])

    def test_non_chat_models_still_excluded(self):
        self.assertEqual(self.fetch(['whisper-large-v3', 'llama-prompt-guard-2-22m',
                                     'openai/gpt-oss-20b']), ['openai/gpt-oss-20b'])

    def test_missing_credentials_do_not_fetch_models(self):
        with patch('ai_providers.groq_provider.urllib.request.urlopen') as request:
            self.assertEqual(GroqProvider().list_models(), [])
        request.assert_not_called()

    def test_curated_catalog_keeps_verified_default_and_removes_unavailable_free_ids(self):
        catalog = json.loads((Path(__file__).resolve().parents[2] / 'config/verified_ai_models.json').read_text())
        self.assertEqual(GroqProvider.RECOMMENDED_PREFIXES[0], catalog['groq']['recommended'])
        for provider in ('groq', 'openrouter'):
            self.assertIn(catalog[provider]['recommended'], catalog[provider]['models'])
        self.assertNotIn('poolside/laguna-s-2.1:free', catalog['openrouter']['models'])
        self.assertNotIn('nvidia/nemotron-3-super-120b-a12b:free', catalog['openrouter']['models'])
        self.assertIn('allam-2-7b', catalog['groq']['models'])


if __name__ == '__main__':
    unittest.main()
