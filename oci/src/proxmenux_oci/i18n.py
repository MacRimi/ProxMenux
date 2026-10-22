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
        (r"The application '(.*)' does not come from LinuxServer", N_("The application '{app_id}' does not come from LinuxServer")),
    ):
        match = re.fullmatch(pattern, text)
        if match:
            return translate(source).format(app_id=match[1])
    exact = {
        'The CasaOS Compose file has no services': N_('The Compose file has no services.'),
        'The Compose file has no services': N_('The Compose file has no services.'),
        'x-casaos.main no identifica un servicio valido': N_('x-casaos.main must name an existing service.'),
        'The main CasaOS service declares no image': N_('The main Compose service has no image.'),
        'El servicio principal no declara una imagen': N_('The main Compose service has no image.'),
        'El servicio no declara una imagen': N_('The service declares no image:'),
        'The CasaOS document is not a Compose mapping': N_('The Compose document must be a mapping.'),
        'The Compose file has no x-casaos metadata': N_('The Compose file has no x-casaos metadata.'),
        'environment must be a list or a mapping': N_('Compose environment must be a list or a mapping.'),
        'volumes must be a list': N_('Compose volumes must be a list.'),
        'ports must be a list': N_('Compose ports must be a list.'),
        'The README has no recognisable docker-compose section': N_('The README has no recognisable docker-compose section'),
        'La seccion docker-compose no contiene un bloque de codigo': N_('The docker-compose section contains no code block'),
        'The docker-compose block is not closed': N_('The docker-compose block is not closed'),
        'The block found does not look like a Docker Compose file': N_('The block found does not look like a Docker Compose file'),
        'No se puede identificar la imagen principal del Compose': N_('The main Compose service cannot be identified unambiguously'),
        'No se puede identificar de forma univoca el servicio principal del Compose': N_('The main Compose service cannot be identified unambiguously'),
        'python3-jsonschema is required to generate templates': N_('python3-jsonschema is required to generate templates'),
        'Bulk generation requires GITHUB_TOKEN to obtain an immutable revision per application': N_('Bulk generation requires GITHUB_TOKEN to obtain an immutable revision per application'),
        'The ProxMenux application catalogue is not a list': N_('The ProxMenux application catalogue is not a list'),
        'GitHub returned a truncated tree for the CasaOS catalogue': N_('GitHub returned a truncated tree for the CasaOS catalogue'),
        'No Compose files were found in the CasaOS catalogue': N_('No Compose files were found in the CasaOS catalogue'),
    }
    if text in exact:
        return translate(exact[text])
    for prefix, source in (
        ('Cannot normalise the CasaOS identifier:', N_('Invalid application identifier:')),
        ('Cannot normalise the identifier:', N_('Invalid application identifier:')),
        ('Docker Compose CasaOS no valido:', N_('The Compose file is not valid YAML:')),
        ('Docker Compose no valido:', N_('The Compose file is not valid YAML:')),
        ('La plantilla generada no cumple el esquema:', N_('The generated template does not match the schema:')),
    ):
        if text.startswith(prefix):
            return translate(source) + text[len(prefix):]
    match = re.fullmatch(r'GitHub returned HTTP 403 for (.+)\. Set GITHUB_TOKEN to raise the API rate limit\.', text)
    if match:
        return translate('GitHub returned HTTP 403 for {url}. Set GITHUB_TOKEN to raise the API rate limit.').format(url=match[1])
    match = re.fullmatch(r'GitHub returned HTTP ([0-9]{3}) (?:for|para) (.+)\.', text)
    if match:
        return translate('GitHub returned HTTP {status} for {url}.').format(status=match[1], url=match[2])
    match = re.fullmatch(r'No se pudo acceder a (.+) despues de 3 intentos: (.*)', text, re.S)
    if match:
        return translate('Could not reach {url} after 3 attempts: {reason}').format(url=match[1], reason=match[2])
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
