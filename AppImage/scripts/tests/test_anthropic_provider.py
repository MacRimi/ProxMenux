import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ai_providers.anthropic_provider import AnthropicProvider
from ai_providers.base import AIProviderError


class CannedAnthropicProvider(AnthropicProvider):
    def __init__(self, response):
        super().__init__(api_key="test-key", model="claude-opus-5-5")
        self.response = response
        self.captured_payload = None

    def _make_request(self, url, payload, headers):
        self.captured_payload = payload
        return self.response


class AnthropicProviderTests(unittest.TestCase):
    def test_skips_thinking_block_before_text(self):
        provider = CannedAnthropicProvider({
            "stop_reason": "end_turn",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "x"},
                {"type": "text", "text": "  Hola  "},
            ],
        })
        self.assertEqual(provider.generate("system", "user"), "Hola")

    def test_thinking_only_response_raises(self):
        provider = CannedAnthropicProvider({
            "stop_reason": "max_tokens",
            "content": [{"type": "thinking", "thinking": "", "signature": "x"}],
        })
        with self.assertRaises(AIProviderError):
            provider.generate("system", "user")

    def test_refusal_with_empty_content_raises(self):
        provider = CannedAnthropicProvider({
            "stop_reason": "refusal",
            "stop_details": {"type": "refusal", "category": "cyber"},
            "content": [],
        })
        with self.assertRaisesRegex(AIProviderError, "cyber"):
            provider.generate("system", "user")

    def test_small_max_tokens_is_raised_to_floor(self):
        provider = CannedAnthropicProvider({
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "CONNECTION_OK"}],
        })
        provider.generate("system", "user", max_tokens=50)
        self.assertEqual(provider.captured_payload["max_tokens"], AnthropicProvider.MIN_MAX_TOKENS)
        provider.generate("system", "user", max_tokens=4000)
        self.assertEqual(provider.captured_payload["max_tokens"], 4000)


if __name__ == "__main__":
    unittest.main()
