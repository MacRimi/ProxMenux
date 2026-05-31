"""Base class for AI providers."""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List


class AIProviderError(Exception):
    """Exception for AI provider errors."""
    pass


# Shared urllib3 PoolManager for AI providers. urllib's `urlopen` does
# NOT pool connections — each call does a fresh TCP+TLS handshake (~100-
# 300ms wasted per call). PoolManager keeps connections alive within the
# `cleanup` window per (scheme, host, port). Providers can opt into this
# by calling `pooled_request(...)` instead of `urllib.request.urlopen`.
# Audit Tier 7 — Sin HTTP connection pooling.
try:
    import urllib3 as _urllib3
    _HTTP_POOL = _urllib3.PoolManager(
        num_pools=8,           # one slot per provider host (groq, openai, ...)
        maxsize=4,             # parallel connections per host
        timeout=_urllib3.Timeout(connect=5, read=30),
        retries=False,         # we handle retries at the dispatcher level
    )
    _POOL_AVAILABLE = True
except Exception:
    _HTTP_POOL = None
    _POOL_AVAILABLE = False


def pooled_request(method, url, headers=None, body=None, timeout=None):
    """Issue an HTTP request through the shared pool. Returns urllib3.HTTPResponse.

    Falls back to a plain urllib call if urllib3 isn't available, so the
    AppImage still works on systems without it. Callers that need the
    legacy `urllib.request.urlopen()` semantics can still use that
    directly — this helper is opt-in.
    """
    if _POOL_AVAILABLE and _HTTP_POOL is not None:
        return _HTTP_POOL.request(method, url, headers=headers or {}, body=body,
                                  timeout=timeout)
    # Fallback: plain urllib.
    import urllib.request
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    return urllib.request.urlopen(req, timeout=timeout if timeout else 10)


class AIProvider(ABC):
    """Abstract base class for AI providers.
    
    All provider implementations must inherit from this class and implement
    the generate() method.
    """
    
    # Provider metadata (override in subclasses)
    NAME = "base"
    REQUIRES_API_KEY = True
    
    def __init__(self, api_key: str = "", model: str = "", base_url: str = ""):
        """Initialize the AI provider.
        
        Args:
            api_key: API key for authentication (not required for local providers)
            model: Model name to use (required - user selects from loaded models)
            base_url: Base URL for API calls (used by Ollama and custom endpoints)
        """
        self.api_key = api_key
        self.model = model  # Model must be provided by user after loading from provider
        self.base_url = base_url
    
    @abstractmethod
    def generate(self, system_prompt: str, user_message: str, 
                 max_tokens: int = 200) -> Optional[str]:
        """Generate a response from the AI model.
        
        Args:
            system_prompt: System instructions for the model
            user_message: User message/query to process
            max_tokens: Maximum tokens in the response
            
        Returns:
            Generated text or None if failed
            
        Raises:
            AIProviderError: If there's an error communicating with the provider
        """
        pass
    
    def test_connection(self) -> Dict[str, Any]:
        """Test the connection to the AI provider.
        
        Sends a simple test message to verify the provider is accessible
        and the API key is valid.
        
        Returns:
            Dictionary with:
                - success: bool indicating if connection succeeded
                - message: Human-readable status message
                - model: Model name being used
        """
        try:
            response = self.generate(
                system_prompt="You are a test assistant. Respond with exactly: CONNECTION_OK",
                user_message="Test connection",
                max_tokens=50  # Some providers (Gemini) need more tokens to return any content
            )
            if response:
                # Require the sentinel to mark the connection as truly OK.
                # Previous code accepted any non-empty response, so a typo in
                # `ollama_url` that hit some other HTTP service would still
                # report "Connected (response received)" — masking a real
                # misconfiguration. Audit Tier 6 — `test_connection`
                # heuristic.
                if "CONNECTION_OK" in response.upper() or "CONNECTION" in response.upper():
                    return {
                        'success': True,
                        'message': 'Connection successful',
                        'model': self.model
                    }
                preview = response.strip()
                if len(preview) > 200:
                    preview = preview[:200] + '...'
                return {
                    'success': False,
                    'message': f'Endpoint responded but not as an LLM (no sentinel). Response preview: {preview}',
                    'model': self.model
                }
            return {
                'success': False,
                'message': 'No response received from provider',
                'model': self.model
            }
        except AIProviderError as e:
            return {
                'success': False,
                'message': str(e),
                'model': self.model
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Unexpected error: {str(e)}',
                'model': self.model
            }
    
    def list_models(self) -> List[str]:
        """List available models from the provider.
        
        Returns:
            List of model IDs available for use.
            Returns empty list if the provider doesn't support listing.
        """
        # Default implementation - subclasses should override
        return []
    
    def get_recommended_model(self) -> str:
        """Get the recommended model for this provider.
        
        Checks if the current model is available. If not, returns
        the first available model from the provider's model list.
        This is fully dynamic - no hardcoded fallback models.
        
        Returns:
            Recommended model ID, or empty string if no models available
        """
        available = self.list_models()
        if not available:
            # Can't get model list - keep current model and hope it works
            return self.model
        
        # Check if current model is available
        if self.model and self.model in available:
            return self.model
        
        # Current model not available - return first available model
        # Models are typically sorted, so first one is usually a good default
        return available[0]
    
    def _make_request(self, url: str, payload: dict, headers: dict,
                      timeout: int = 15, max_retries: int = 2) -> dict:
        """Make HTTP request to AI provider API with retry/backoff on 429/5xx.

        Retries with exponential backoff (1s, 2s, 4s) on transient failures:
          - HTTP 429 (rate limit) — provider asks us to slow down.
          - HTTP 5xx (server error) — provider hiccup, often resolves quickly.
          - URLError (DNS / connection refused / timeout).
        4xx errors other than 429 are returned without retry — those are bugs
        in our request, not transient.

        Error bodies are NOT echoed into the exception message: provider
        responses can contain PII from our own prompt being reflected back,
        and that ends up in journald where any reader sees it. Audit Tier 3.2
        #5 (retry/backoff) and #6 (PII leak via error body).
        """
        import json
        import time as _time
        import urllib.request
        import urllib.error

        # Ensure User-Agent is set (Cloudflare blocks requests without it - error 1010)
        if 'User-Agent' not in headers:
            headers['User-Agent'] = 'ProxMenux/1.0'

        data = json.dumps(payload).encode('utf-8')

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method='POST')
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                # Drain the body so we can decide whether to retry, but NEVER
                # include it in the raised exception (PII / API key in echo).
                try:
                    e.read()
                except Exception:
                    pass
                # Retry on 429 (rate limit) and 5xx (server error).
                retryable = e.code == 429 or 500 <= e.code < 600
                last_error = AIProviderError(f"HTTP {e.code}: {e.reason}")
                if retryable and attempt < max_retries:
                    backoff = 2 ** attempt  # 1, 2, 4 seconds
                    _time.sleep(backoff)
                    continue
                raise last_error
            except urllib.error.URLError as e:
                last_error = AIProviderError(f"Connection error: {e.reason}")
                if attempt < max_retries:
                    backoff = 2 ** attempt
                    _time.sleep(backoff)
                    continue
                raise last_error
            except json.JSONDecodeError as e:
                # Not retryable — provider sent malformed response.
                raise AIProviderError(f"Invalid JSON response: {e}")
            except Exception as e:
                raise AIProviderError(f"Request failed: {type(e).__name__}")
        # Should be unreachable; keep mypy happy.
        if last_error:
            raise last_error
        raise AIProviderError("Request failed after retries")
