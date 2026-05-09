"""OpenAI provider implementation.

OpenAI is the industry standard for AI APIs.
Models are loaded dynamically from the API.
"""
from typing import Optional, List
import json
import urllib.request
import urllib.error
from .base import AIProvider, AIProviderError


class OpenAIProvider(AIProvider):
    """OpenAI provider using their Chat Completions API.
    
    Also compatible with OpenAI-compatible APIs like:
    - BytePlus/ByteDance (Kimi K2.5)
    - LocalAI
    - LM Studio
    - vLLM
    - Together AI
    - Any OpenAI-compatible endpoint
    """
    
    NAME = "openai"
    REQUIRES_API_KEY = True
    DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"
    DEFAULT_MODELS_URL = "https://api.openai.com/v1/models"
    
    # Models to exclude (not suitable for chat/text generation)
    EXCLUDED_PATTERNS = [
        'embedding', 'whisper', 'tts', 'dall-e', 'image',
        'instruct', 'realtime', 'audio', 'moderation',
        'search', 'code-search', 'text-similarity', 'babbage', 'davinci',
        'curie', 'ada', 'transcribe'
    ]
    
    # Recommended models for chat (in priority order)
    RECOMMENDED_PREFIXES = ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo', 'gpt-4', 'gpt-3.5-turbo']

    @staticmethod
    def _is_reasoning_model(model: str) -> bool:
        """True for OpenAI reasoning models (o-series + non-chat gpt-5+).

        These use a stricter API contract than chat models:
          - Must use ``max_completion_tokens`` instead of ``max_tokens``
          - ``temperature`` is not accepted (only the default is supported)

        Chat-optimized variants (``gpt-5-chat-latest``,
        ``gpt-5.1-chat-latest``, etc.) keep the classic contract and are
        NOT flagged here.
        """
        m = model.lower()
        # o1, o3, o4, o5 ...  (o<digit>...)
        if len(m) >= 2 and m[0] == 'o' and m[1].isdigit():
            return True
        # gpt-5, gpt-5-mini, gpt-5.1, gpt-5.2-pro ...  EXCEPT *-chat-latest
        if m.startswith('gpt-5') and '-chat' not in m:
            return True
        return False
    
    def list_models(self) -> List[str]:
        """List available models for chat completions.

        Two modes:
        - Official OpenAI (no custom base_url): restrict to GPT chat models,
          excluding embedding/whisper/tts/dall-e/instruct/legacy variants.
        - OpenAI-compatible endpoint (LiteLLM, MLX, LM Studio, vLLM,
          LocalAI, Ollama-proxy, etc.): the "gpt" substring check is
          dropped so user-served models (e.g. ``mlx-community/Llama-3.1-8B``,
          ``Qwen3-32B``, ``mistralai/...``) show up. EXCLUDED_PATTERNS
          still applies — embeddings/whisper/tts aren't chat-capable on
          any backend.

        Returns:
            List of model IDs suitable for chat completions.
        """
        is_custom_endpoint = bool(self.base_url)

        # Custom endpoints (LiteLLM, opencode.ai, vLLM, LocalAI, …) often
        # don't require auth at the /models endpoint — opencode.ai/zen
        # for instance returns the catalogue with no Authorization
        # header. Returning early on empty api_key broke those flows.
        # Issue #11.5 — OpenCode provider Custom Base URL fetch.
        if not self.api_key and not is_custom_endpoint:
            return []

        try:
            # Determine models URL from base_url if set
            if self.base_url:
                base = self.base_url.rstrip('/')
                if not base.endswith('/v1'):
                    base = f"{base}/v1"
                models_url = f"{base}/models"
            else:
                models_url = self.DEFAULT_MODELS_URL

            # Only send Authorization when we actually have a key —
            # sending `Bearer ` (empty) causes some endpoints to 401.
            headers = {}
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'

            req = urllib.request.Request(
                models_url,
                headers=headers,
                method='GET'
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            models = []
            for model in data.get('data', []):
                model_id = model.get('id', '')
                if not model_id:
                    continue

                model_lower = model_id.lower()

                # Official OpenAI: restrict to GPT chat models. Custom
                # endpoints serve arbitrarily named models, so this
                # substring check would drop every valid result there.
                if not is_custom_endpoint and 'gpt' not in model_lower:
                    continue

                # Exclude non-chat models on every backend.
                if any(pattern in model_lower for pattern in self.EXCLUDED_PATTERNS):
                    continue

                models.append(model_id)

            # Sort with recommended models first (only meaningful for OpenAI
            # official; on custom endpoints the prefixes rarely match, so
            # entries fall through to alphabetical order, which is fine).
            def sort_key(m):
                m_lower = m.lower()
                for i, prefix in enumerate(self.RECOMMENDED_PREFIXES):
                    if m_lower.startswith(prefix):
                        return (i, m)
                return (len(self.RECOMMENDED_PREFIXES), m)

            return sorted(models, key=sort_key)
        except Exception as e:
            print(f"[OpenAIProvider] Failed to list models: {e}")
            return []
    
    def _get_api_url(self) -> str:
        """Get the API URL, using custom base_url if provided."""
        if self.base_url:
            # Ensure the URL ends with the correct path
            base = self.base_url.rstrip('/')
            if not base.endswith('/chat/completions'):
                if not base.endswith('/v1'):
                    base = f"{base}/v1"
                base = f"{base}/chat/completions"
            return base
        return self.DEFAULT_API_URL
    
    def generate(self, system_prompt: str, user_message: str,
                 max_tokens: int = 200) -> Optional[str]:
        """Generate a response using OpenAI's API or compatible endpoint.
        
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
            raise AIProviderError("API key required for OpenAI")

        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_message},
            ],
        }

        # Reasoning models (o1/o3/o4/gpt-5*, excluding *-chat-latest) use a
        # different parameter contract: max_completion_tokens instead of
        # max_tokens, and no temperature field. Sending the classic chat
        # parameters to them produces HTTP 400 Bad Request.
        #
        # They also spend output budget on internal reasoning by default,
        # which empties the user-visible reply when max_tokens is small
        # (like the ~200 we use for notifications). reasoning_effort
        # 'minimal' keeps that internal reasoning to a minimum so the
        # entire budget is available for the translation, which is
        # exactly what this pipeline wants. OpenAI documents 'minimal',
        # 'low', 'medium', 'high' — 'minimal' is the right setting for a
        # straightforward translate+explain task.
        if self._is_reasoning_model(self.model):
            payload['max_completion_tokens'] = max_tokens
            payload['reasoning_effort'] = 'minimal'
        else:
            payload['max_tokens'] = max_tokens
            payload['temperature'] = 0.3

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        }
        
        api_url = self._get_api_url()
        result = self._make_request(api_url, payload, headers)
        
        try:
            return result['choices'][0]['message']['content'].strip()
        except (KeyError, IndexError) as e:
            raise AIProviderError(f"Unexpected response format: {e}")
