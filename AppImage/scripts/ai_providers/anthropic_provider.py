"""Anthropic (Claude) provider implementation.

Anthropic's Claude models are excellent for text generation and translation.
Models are addressed by their pinned IDs (the "-latest" aliases were retired).
"""
from typing import Optional, List
from .base import AIProvider, AIProviderError


class AnthropicProvider(AIProvider):
    """Anthropic provider using their Messages API."""
    
    NAME = "anthropic"
    REQUIRES_API_KEY = True
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"
    
    # Current Claude API model IDs (per docs at
    # platform.claude.com/docs/en/docs/about-claude/models). Kept as a
    # runtime fallback for `/api/notifications/provider-models` when
    # `verified_ai_models.json` has no Anthropic entry; the JSON is the
    # authoritative UI-facing list. Refreshed 2026-10-26 against the live
    # Models API. Ordered cheapest → most capable so the first entry is a
    # safe default.
    KNOWN_MODELS = [
        "claude-haiku-5-5",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5-5",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-opus-5-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-opus-4-5-20251101",
        "claude-fable-5",
        "claude-fable-5-1",
    ]

    # Newer models (Opus 5.x, Fable) may think before answering and the
    # thinking counts against max_tokens, so a small cap can end the turn
    # with no text at all. max_tokens is a ceiling, not a cost.
    MIN_MAX_TOKENS = 1024
    
    def list_models(self) -> List[str]:
        """Return known Anthropic model IDs."""
        return self.KNOWN_MODELS
    
    def generate(self, system_prompt: str, user_message: str,
                 max_tokens: int = 200) -> Optional[str]:
        """Generate a response using Anthropic's API.
        
        Note: Anthropic uses a different API format than OpenAI.
        The system prompt goes in a separate field, not in messages.
        
        Args:
            system_prompt: System instructions
            user_message: User message to process
            max_tokens: Maximum response length
            
        Returns:
            Generated text or None if failed
            
        Raises:
            AIProviderError: If API key is missing or request fails
        """
        if not self.api_key:
            raise AIProviderError("API key required for Anthropic")
        
        # Anthropic uses a different format - system is a top-level field
        payload = {
            'model': self.model,
            'system': system_prompt,
            'messages': [
                {'role': 'user', 'content': user_message},
            ],
            'max_tokens': max(max_tokens, self.MIN_MAX_TOKENS),
        }
        
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': self.api_key,
            'anthropic-version': self.API_VERSION,
        }
        
        result = self._make_request(self.API_URL, payload, headers)
        
        # A safety classifier can decline even benign notifications
        # (HTTP 200, stop_reason "refusal", empty content). Raising lets the
        # caller fall back to the original, untranslated notification.
        if result.get('stop_reason') == 'refusal':
            category = (result.get('stop_details') or {}).get('category')
            raise AIProviderError(f"Request declined by Anthropic (category: {category})")
        
        # Content is a list of blocks; thinking blocks may come before the
        # text, so take the first text block rather than content[0].
        content = result.get('content')
        if not isinstance(content, list):
            raise AIProviderError("Unexpected response format: missing content")
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'text':
                return block.get('text', '').strip()
        raise AIProviderError(
            f"No text in response (stop_reason: {result.get('stop_reason')})")
