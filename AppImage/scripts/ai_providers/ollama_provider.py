"""Ollama provider implementation.

Ollama enables 100% local AI execution with no costs and complete privacy.
No internet connection required - perfect for sensitive enterprise environments.
"""
from typing import Optional
from .base import AIProvider, AIProviderError


def ollama_headers(api_key: str = "") -> dict:
    """Authenticate protected Ollama gateways without requiring a key locally."""
    if not isinstance(api_key, str) or len(api_key) > 512 or '\r' in api_key or '\n' in api_key:
        raise AIProviderError("Invalid Ollama API key")
    headers = {'Content-Type': 'application/json'}
    if api_key.strip():
        headers['Authorization'] = f'Bearer {api_key.strip()}'
    return headers


class OllamaProvider(AIProvider):
    """Ollama provider for local AI execution."""
    
    NAME = "ollama"
    REQUIRES_API_KEY = False
    DEFAULT_URL = "http://localhost:11434"
    
    def __init__(self, api_key: str = "", model: str = "", base_url: str = ""):
        """Initialize Ollama provider.
        
        Args:
            api_key: Optional Bearer token for an authenticated Ollama gateway
            model: Model name (user must select from loaded models)
            base_url: Ollama server URL (default: http://localhost:11434)
        """
        super().__init__(api_key, model, base_url)
        # Use default URL if not provided
        if not self.base_url:
            self.base_url = self.DEFAULT_URL
    
    def generate(self, system_prompt: str, user_message: str,
                 max_tokens: int = 200) -> Optional[str]:
        """Generate a response using local Ollama server.
        
        Args:
            system_prompt: System instructions
            user_message: User message to process
            max_tokens: Maximum response length (maps to num_predict)
            
        Returns:
            Generated text or None if failed
            
        Raises:
            AIProviderError: If Ollama server is unreachable
        """
        url = f"{self.base_url.rstrip('/')}/api/chat"
        
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_message},
            ],
            'stream': False,
            'options': {
                'num_predict': max_tokens,
                'temperature': 0.3,
            }
        }
        
        headers = ollama_headers(self.api_key)
        
        # Cloud models (e.g., kimi-k2.5:cloud, minimax-m2.7:cloud) need longer timeout
        # because requests go through: ProxMenux -> Ollama -> Cloud Provider -> back
        # Local models also need generous timeout for slower hardware (e.g., low-end CPUs,
        # no GPU acceleration, larger models like 8B parameters)
        is_cloud_model = ':cloud' in self.model.lower()
        timeout = 120 if is_cloud_model else 90  # 2 minutes for cloud, 90s for local
        
        try:
            result = self._make_request(url, payload, headers, timeout=timeout)
        except AIProviderError as e:
            if "Connection" in str(e) or "refused" in str(e).lower():
                raise AIProviderError(
                    f"Cannot connect to Ollama at {self.base_url}. "
                    "Make sure Ollama is running (ollama serve)"
                )
            raise
        
        try:
            message = result.get('message', {})
            return message.get('content', '').strip()
        except (KeyError, AttributeError) as e:
            raise AIProviderError(f"Unexpected response format: {e}")
    
    def test_connection(self):
        """Test connection to Ollama server.
        
        Also checks if the specified model is available.
        """
        import json
        import urllib.request
        import urllib.error
        
        # First check if server is running
        try:
            url = f"{self.base_url.rstrip('/')}/api/tags"
            headers = {'User-Agent': 'ProxMenux/1.0', **ollama_headers(self.api_key)}
            req = urllib.request.Request(url, method='GET', headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                
                # Get full model names (with tags) for comparison
                full_model_names = [m.get('name', '') for m in data.get('models', [])]
                # Also get base names (without tags) for fallback matching
                base_model_names = [name.split(':')[0] for name in full_model_names]
                
                # Check if the requested model matches any available model
                # Match by: exact name, base name, or requested model without tag
                requested_base = self.model.split(':')[0] if ':' in self.model else self.model
                
                model_found = (
                    self.model in full_model_names or  # Exact match (e.g., "llama3.2:latest")
                    self.model in base_model_names or  # Base name match (e.g., "llama3.2")
                    requested_base in base_model_names  # Requested base matches available base
                )
                
                if not model_found:
                    display_models = full_model_names[:5] if full_model_names else ['none']
                    return {
                        'success': False,
                        'message': f"Model '{self.model}' not found. Available: {', '.join(display_models)}{'...' if len(full_model_names) > 5 else ''}",
                        'model': self.model
                    }
        except urllib.error.HTTPError as error:
            message = (
                f"HTTP {error.code}: Ollama authentication failed. Check the optional API key."
                if error.code in (401, 403)
                else f"HTTP {error.code}: Ollama request failed"
            )
            return {'success': False, 'message': message, 'model': self.model}
        except urllib.error.URLError:
            return {
                'success': False,
                'message': f"Cannot connect to Ollama at {self.base_url}. Make sure Ollama is running.",
                'model': self.model
            }
        except Exception as e:
            return {
                'success': False,
                'message': f"Error checking Ollama: {str(e)}",
                'model': self.model
            }
        
        # If server is up and model exists, do the actual test
        # For cloud models, we skip the full test (which sends a message)
        # because it would take too long. The model availability check above is sufficient.
        is_cloud_model = ':cloud' in self.model.lower()
        if is_cloud_model:
            return {
                'success': True,
                'message': f"Cloud model '{self.model}' is available via Ollama",
                'model': self.model
            }
        
        return super().test_connection()
