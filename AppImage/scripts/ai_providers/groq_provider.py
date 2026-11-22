"""Groq AI provider implementation.

Groq provides fast inference with a generous free tier (30 requests/minute).
Uses the OpenAI-compatible API format.
"""
from typing import Optional, List
import json
import urllib.request
import urllib.error
from .base import AIProvider, AIProviderError


class GroqProvider(AIProvider):
    """Groq AI provider using their OpenAI-compatible API."""
    
    NAME = "groq"
    REQUIRES_API_KEY = True
    API_URL = "https://api.groq.com/openai/v1/chat/completions"
    MODELS_URL = "https://api.groq.com/openai/v1/models"
    
    # Exclude non-chat models
    EXCLUDED_PATTERNS = ['whisper', 'tts', 'guard', 'tool-use']
    
    # Prefer the verified default and current GPT-OSS models. Llama remains
    # available for accounts with access; retired Mixtral/Gemma families have
    # no recommendation priority. Sorting never adds IDs to the API response.
    RECOMMENDED_PREFIXES = [
        'openai/gpt-oss-20b', 'openai/gpt-oss-120b', 'qwen/qwen3.8-27b',
        'llama-3.3', 'llama-3.1-8b',
    ]
    
    def list_models(self) -> List[str]:
        """List available Groq models for chat completions.
        
        Filters out non-chat models (whisper, guard, etc.)
        
        Returns:
            List of model IDs suitable for chat completions.
        """
        if not self.api_key:
            return []
        
        try:
            req = urllib.request.Request(
                self.MODELS_URL,
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'User-Agent': 'ProxMenux/1.0'  # Cloudflare blocks requests without User-Agent
                },
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
                
                # Exclude non-chat models
                if any(pattern in model_lower for pattern in self.EXCLUDED_PATTERNS):
                    continue
                
                models.append(model_id)
            
            # Sort with recommended models first
            def sort_key(m):
                m_lower = m.lower()
                for i, prefix in enumerate(self.RECOMMENDED_PREFIXES):
                    if m_lower.startswith(prefix):
                        return (i, m)
                return (len(self.RECOMMENDED_PREFIXES), m)
            
            return sorted(models, key=sort_key)
        except Exception as e:
            print(f"[GroqProvider] Failed to list models: {e}")
            return []
    
    def generate(self, system_prompt: str, user_message: str,
                 max_tokens: int = 200) -> Optional[str]:
        """Generate a response using Groq's API.
        
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
            raise AIProviderError("API key required for Groq")
        
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_message},
            ],
            'max_tokens': max_tokens,
            'temperature': 0.3,
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        }
        
        result = self._make_request(self.API_URL, payload, headers)
        
        try:
            return result['choices'][0]['message']['content'].strip()
        except (KeyError, IndexError) as e:
            raise AIProviderError(f"Unexpected response format: {e}")
