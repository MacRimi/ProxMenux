"""ProxMenux text lookup, with the same cache and rules as translate() in utils.sh.

The language comes from /usr/local/share/proxmenux/config.json and the
translations from lang/<language>.json, both maintained by ProxMenux. English
is the source language: a missing translation returns the English text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

BASE_DIR = Path("/usr/local/share/proxmenux")

_language: str | None = None
_cache: dict[str, str] | None = None


def language() -> str:
    global _language
    if _language is None:
        try:
            value = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8")).get("language")
        except (OSError, ValueError, AttributeError):
            value = None
        _language = value if isinstance(value, str) and value else "en"
    return _language


def N_(text: str) -> str:
    """Marks a literal kept in a table for the translation cache; the text is
    translated where it is displayed."""
    return text


def translate(text: str) -> str:
    global _cache
    if language() == "en":
        return text
    if _cache is None:
        try:
            data = json.loads((BASE_DIR / "lang" / f"{language()}.json").read_text(encoding="utf-8"))
            _cache = {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _cache = {}
    return _cache.get(text) or text


def diagnostic(error: Any) -> str:
    """Translate legacy diagnostics only when presenting them to a person.

    The catalog's exception types and original messages remain stable for
    internal callers; identifiers are inserted after the translation lookup.
    """
    text = str(error)
    for pattern, source in (
        (r"No template is available for '(.*)'", N_("No template is available for '{app_id}'")),
        (r"The application '(.*)' is not in the index", N_("The application '{app_id}' is not in the index")),
    ):
        match = re.fullmatch(pattern, text)
        if match:
            return translate(source).format(app_id=match[1])
    return text


def source_text(value: Any) -> str:
    """The English a catalog field was written in.

    Catalog text used to be stored per locale, which meant a second
    translation system beside `translate()` and, in practice, one language
    of the eight. The catalog now carries the source text only: whatever is
    shown to the reader goes through `translate()` like every other string
    in ProxMenux.
    """
    # Stripped: the translation cache stores its keys stripped, so a field
    # that carries a stray trailing newline would never find its translation
    # and would silently render in English.
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    return str(value.get("en_US") or "").strip()
