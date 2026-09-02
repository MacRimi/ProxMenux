"""Self-contained API wrappers for AI-model verification.

Kept independent from the ProxMenux AppImage's ai_providers module so
this tool can live in a private repo with no import coupling to the
public project. Uses only the Python standard library.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import List, Optional


class ProviderError(Exception):
    pass


class Provider:
    """Base class. Subclasses implement list_models() and generate()."""
    name = "base"

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url

    def list_models(self) -> List[str]:
        raise NotImplementedError

    def generate(self, model: str, system: str, user: str,
                 max_tokens: int = 250, timeout: int = 30) -> str:
        raise NotImplementedError

    # ── HTTP helpers ────────────────────────────────────────────

    # Cloudflare in front of api.groq.com (and probably other providers
    # over time) returns 403 "error code: 1010" for the default
    # `Python-urllib/3.x` User-Agent — the "browser signature ban" rule.
    # A plain identifier is enough to get through; we're not spoofing a
    # browser, just avoiding a naive UA fingerprint match.
    _USER_AGENT = "ProxMenux-AI-Verifier/1.0"

    def _post_json(self, url: str, payload: dict, headers: dict,
                   timeout: int = 30) -> dict:
        data = json.dumps(payload).encode("utf-8")
        headers = {**headers, "User-Agent": self._USER_AGENT}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get_json(self, url: str, headers: dict, timeout: int = 30) -> dict:
        headers = {**headers, "User-Agent": self._USER_AGENT}
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


# ══════════════════════════════════════════════════════════════════
# OpenAI-compatible family (OpenAI, Groq, OpenRouter, LiteLLM, LM
# Studio, vLLM, LocalAI, etc.). They all speak the same endpoints.
# ══════════════════════════════════════════════════════════════════

class OpenAICompatProvider(Provider):
    name = "openai-compat"
    default_base = "https://api.openai.com"
    models_path = "/v1/models"
    chat_path = "/v1/chat/completions"

    def _base(self) -> str:
        return (self.base_url or self.default_base).rstrip("/")

    @staticmethod
    def _is_reasoning_model(model: str) -> bool:
        """True for OpenAI reasoning models (o-series + non-chat gpt-5+).

        Must be kept in sync with the matching helper in ProxMenux's
        openai_provider.py — same rule, same consequence:
          - send max_completion_tokens instead of max_tokens
          - omit temperature (default is the only accepted value).
        """
        m = model.lower()
        if len(m) >= 2 and m[0] == "o" and m[1].isdigit():
            return True
        if m.startswith("gpt-5") and "-chat" not in m:
            return True
        return False

    def list_models(self) -> List[str]:
        url = f"{self._base()}{self.models_path}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = self._get_json(url, headers)
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    def generate(self, model: str, system: str, user: str,
                 max_tokens: int = 250, timeout: int = 30) -> str:
        url = f"{self._base()}{self.chat_path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self._is_reasoning_model(model):
            # Reasoning models spend budget on internal reasoning by
            # default, which yields empty replies at small max_tokens.
            # reasoning_effort=minimal keeps that overhead low so the
            # whole budget reaches the user, aligned with the short
            # translate+explain task ProxMenux uses. Mirror this in
            # ProxMenux's openai_provider.py.
            payload["max_completion_tokens"] = max_tokens
            payload["reasoning_effort"] = "minimal"
        else:
            payload["max_tokens"] = max_tokens
            payload["temperature"] = 0.3
        data = self._post_json(url, payload, headers, timeout)
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"unexpected response: {exc} // {str(data)[:200]}")


class OpenAIProvider(OpenAICompatProvider):
    name = "openai"
    default_base = "https://api.openai.com"


class GroqProvider(OpenAICompatProvider):
    name = "groq"
    default_base = "https://api.groq.com/openai"


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"
    default_base = "https://openrouter.ai/api"


# ══════════════════════════════════════════════════════════════════
# Gemini — different endpoint shape, keyed via ?key=... query param.
# ══════════════════════════════════════════════════════════════════

class GeminiProvider(Provider):
    name = "gemini"
    default_base = "https://generativelanguage.googleapis.com/v1beta"

    @staticmethod
    def _has_thinking_mode(model: str) -> bool:
        """True for Gemini variants that enable "thinking" by default.

        Kept in sync with ProxMenux's gemini_provider.py. 2.5+ pro/flash
        and 3.x pro/flash consume output tokens on reasoning, which
        yields empty replies when max_tokens is small. We pass
        thinkingBudget=0 to disable thinking so the short translate+
        explain test sees actual text. Lite variants don't have thinking
        enabled and are not flagged here.
        """
        m = model.lower()
        if "lite" in m:
            return False
        return m.startswith("gemini-2.5") or m.startswith("gemini-3")

    def list_models(self) -> List[str]:
        url = f"{self.default_base}/models?key={self.api_key}"
        data = self._get_json(url, {})
        names = []
        for m in data.get("models", []):
            raw = m.get("name", "")
            if raw.startswith("models/"):
                raw = raw[len("models/"):]
            # Only keep text-generation capable models.
            if "generateContent" in m.get("supportedGenerationMethods", []):
                names.append(raw)
        return names

    def generate(self, model: str, system: str, user: str,
                 max_tokens: int = 250, timeout: int = 30) -> str:
        url = f"{self.default_base}/models/{model}:generateContent?key={self.api_key}"
        gen_config = {
            "maxOutputTokens": max_tokens,
            "temperature": 0.3,
        }
        if self._has_thinking_mode(model):
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": gen_config,
        }
        data = self._post_json(url, payload, {"Content-Type": "application/json"}, timeout)
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"unexpected response: {exc} // {str(data)[:200]}")


# ══════════════════════════════════════════════════════════════════
# Anthropic — own schema and headers.
# ══════════════════════════════════════════════════════════════════

class AnthropicProvider(Provider):
    name = "anthropic"
    default_base = "https://api.anthropic.com"
    version = "2023-06-01"

    def list_models(self) -> List[str]:
        url = f"{self.default_base}/v1/models"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.version,
        }
        try:
            data = self._get_json(url, headers)
            return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        except urllib.error.HTTPError:
            # Older keys don't have the endpoint; caller decides what to do.
            return []

    def generate(self, model: str, system: str, user: str,
                 max_tokens: int = 250, timeout: int = 30) -> str:
        url = f"{self.default_base}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.version,
            "Content-Type": "application/json",
        }
        # ProxMenux's real anthropic_provider.py does NOT send `temperature`,
        # and Anthropic's newest generation (Claude Sonnet 5, Opus 4.7 /
        # 4.8, Fable 5) now rejects it with:
        #   invalid_request_error: `temperature` is deprecated for this model.
        # Omitting it here aligns the verifier with production behaviour so
        # the newest-gen models can be reached during verification.
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data = self._post_json(url, payload, headers, timeout)
        try:
            return data["content"][0]["text"].strip()
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"unexpected response: {exc} // {str(data)[:200]}")


PROVIDERS = {
    "openai": OpenAIProvider,
    "groq": GroqProvider,
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "openrouter": OpenRouterProvider,
}


def make_provider(name: str, api_key: str,
                  base_url: Optional[str] = None) -> Provider:
    cls = PROVIDERS.get(name)
    if not cls:
        raise ValueError(f"unknown provider: {name}")
    return cls(api_key, base_url=base_url)
