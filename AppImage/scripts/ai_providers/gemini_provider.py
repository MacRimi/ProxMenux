"""Google Gemini provider implementation.

Google's Gemini models offer a free tier and excellent quality/price ratio.
Models are loaded dynamically from the API - no hardcoded model names.
"""
from typing import Optional, List
import json
import urllib.request
import urllib.error
from .base import AIProvider, AIProviderError


class GeminiProvider(AIProvider):
    """Google Gemini provider using the Generative Language API."""
    
    NAME = "gemini"
    REQUIRES_API_KEY = True
    API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
    
    # Patterns to exclude from model list (experimental, preview, specialized)
    EXCLUDED_PATTERNS = [
        'computer-use', 'deep-research',
        'image', 'embedding', 'aqa', 'tts',
        'learnlm', 'imagen', 'veo'
    ]
    
    # Deprecated models that may still appear in API but return 404
    DEPRECATED_MODELS = [
        'gemini-2.0-flash',
        'gemini-1.0-pro',
        'gemini-pro',
    ]

    @staticmethod
    def _has_thinking_mode(model: str) -> bool:
        """True for Gemini variants that enable "thinking" by default.

        Gemini 2.5+ and 3.x Pro/Flash models spend output tokens on
        internal reasoning before emitting the final answer. With a small
        max_tokens budget (≤250) that consumes the whole allowance and
        leaves an empty reply. For the short translate/explain use case
        in ProxMenux we want direct output, so we disable thinking for
        these. Lite variants (flash-lite) do NOT have thinking enabled
        and are safe to leave alone.
        """
        m = model.lower()
        if 'lite' in m:
            return False
        return m.startswith('gemini-2.5') or m.startswith('gemini-3')
    
    def list_models(self) -> List[str]:
        """List available Gemini models that support generateContent.
        
        Filters to only stable text generation models, excluding:
        - Preview/experimental models
        - Image generation models
        - Embedding models
        - Specialized models (computer-use, deep-research, etc.)
        
        Returns:
            List of model IDs available for text generation.
        """
        if not self.api_key:
            return []
        
        try:
            url = f"{self.API_BASE}?key={self.api_key}"
            req = urllib.request.Request(url, method='GET', headers={'User-Agent': 'ProxMenux/1.0'})
            
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            
            models = []
            for model in data.get('models', []):
                model_name = model.get('name', '')
                # Extract just the model ID (e.g., "models/gemini-pro" -> "gemini-pro")
                if model_name.startswith('models/'):
                    model_id = model_name[7:]
                else:
                    model_id = model_name
                
                # Only include models that support generateContent
                supported_methods = model.get('supportedGenerationMethods', [])
                if 'generateContent' not in supported_methods:
                    continue
                
                # Exclude experimental, preview, and specialized models
                model_lower = model_id.lower()
                if any(pattern in model_lower for pattern in self.EXCLUDED_PATTERNS):
                    continue
                
                # Exclude deprecated models that return 404
                if model_id in self.DEPRECATED_MODELS:
                    continue
                
                models.append(model_id)
            
            # Sort with recommended models first (flash-lite, flash, pro)
            def sort_key(m):
                m_lower = m.lower()
                if 'flash-lite' in m_lower:
                    return (0, m)  # Best for notifications (fast, cheap)
                if 'flash' in m_lower:
                    return (1, m)
                if 'pro' in m_lower:
                    return (2, m)
                return (3, m)
            
            return sorted(models, key=sort_key)
        except Exception as e:
            print(f"[GeminiProvider] Failed to list models: {e}")
            return []
    
    def generate(self, system_prompt: str, user_message: str,
                 max_tokens: int = 200) -> Optional[str]:
        """Generate a response using Google's Gemini API.
        
        Note: Gemini uses a different API format. System instructions
        go in a separate systemInstruction field.
        
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
            raise AIProviderError("API key required for Gemini")
        
        url = f"{self.API_BASE}/{self.model}:generateContent?key={self.api_key}"
        
        # Gemini uses a specific format with contents array
        gen_config = {
            'maxOutputTokens': max_tokens,
            'temperature': 0.3,
        }

        # Disable thinking on 2.5+ / 3.x pro & flash models so the limited
        # output budget actually produces visible text. thinkingBudget=0
        # is the official switch for this; lite variants and legacy
        # models don't need (and ignore) the field.
        if self._has_thinking_mode(self.model):
            gen_config['thinkingConfig'] = {'thinkingBudget': 0}

        payload = {
            'systemInstruction': {
                'parts': [{'text': system_prompt}]
            },
            'contents': [
                {
                    'role': 'user',
                    'parts': [{'text': user_message}]
                }
            ],
            'generationConfig': gen_config,
        }
        
        headers = {
            'Content-Type': 'application/json',
        }
        
        result = self._make_request(url, payload, headers)
        
        try:
            # Gemini returns candidates array with content parts
            candidates = result.get('candidates', [])
            if not candidates:
                # Check for blocked content or other issues
                prompt_feedback = result.get('promptFeedback', {})
                block_reason = prompt_feedback.get('blockReason', '')
                if block_reason:
                    raise AIProviderError(f"Content blocked by Gemini: {block_reason}")
                raise AIProviderError("No candidates in response - model may be overloaded")
            
            # Check if response was blocked
            finish_reason = candidates[0].get('finishReason', '')
            if finish_reason == 'SAFETY':
                safety_ratings = candidates[0].get('safetyRatings', [])
                blocked_categories = [r.get('category', 'UNKNOWN') for r in safety_ratings 
                                     if r.get('blocked', False)]
                raise AIProviderError(f"Response blocked by safety filter: {blocked_categories}")
            
            content = candidates[0].get('content', {})
            parts = content.get('parts', [])
            if parts:
                text = parts[0].get('text', '').strip()
                if text:
                    return text
            
            # No text content - check if it's a known issue
            if finish_reason == 'MAX_TOKENS':
                # MAX_TOKENS with no content could mean prompt too long OR model overload
                raise AIProviderError("No response generated (MAX_TOKENS). Model may be overloaded - try again.")
            elif finish_reason == 'STOP':
                # Normal stop but no content - unusual
                raise AIProviderError("Model returned empty response")
            else:
                raise AIProviderError(f"No response from model (reason: {finish_reason}). Try again later.")
        except AIProviderError:
            raise
        except (KeyError, IndexError) as e:
            raise AIProviderError(f"Unexpected response format: {e}")
