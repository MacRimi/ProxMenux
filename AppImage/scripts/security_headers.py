#!/usr/bin/env python3
"""Helpers for ProxMenux HTTP security headers."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse


PRIMARY_FRAME_ANCESTORS_ENV = "PROXMENUX_ALLOWED_FRAME_ANCESTORS"
COMPAT_FRAME_ANCESTORS_ENV = "ALLOWED_FRAME_ANCESTORS"

_FRAME_ANCESTOR_KEYWORDS = {
    "self": "'self'",
    "'self'": "'self'",
}
_UNSAFE_CSP_CHARS = re.compile(r"[\r\n;]")
_FRAME_ANCESTOR_SEPARATOR = re.compile(r"[\s,]+")

_CSP_PREFIX = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss: https:; "
)
_CSP_SUFFIX = "base-uri 'self'; form-action 'self'"


def _split_frame_ancestor_sources(raw_value: str) -> list[str]:
    return [
        source.strip()
        for source in _FRAME_ANCESTOR_SEPARATOR.split(raw_value)
        if source.strip()
    ]


def _normalize_frame_ancestor_source(source: str) -> str | None:
    token = source.strip()
    lowered = token.lower()

    if lowered in _FRAME_ANCESTOR_KEYWORDS:
        return _FRAME_ANCESTOR_KEYWORDS[lowered]

    if not token or _UNSAFE_CSP_CHARS.search(token):
        return None

    # Keep the initial support intentionally narrow: exact HTTP(S) origins.
    # Broad schemes, wildcards, paths, queries, and credentials are rejected.
    if token in {"*", "http:", "https:"}:
        return None

    parsed = urlparse(token)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None

    if parsed.username or parsed.password:
        return None

    try:
        parsed.port
    except ValueError:
        return None

    if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
        return None

    if not parsed.hostname or "*" in parsed.hostname:
        return None

    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def get_allowed_frame_ancestors(environ: dict[str, str] | None = None) -> list[str]:
    """Return sanitized frame-ancestor CSP sources from environment settings."""
    environ = os.environ if environ is None else environ

    raw_value = environ.get(PRIMARY_FRAME_ANCESTORS_ENV, "").strip()
    if not raw_value:
        raw_value = environ.get(COMPAT_FRAME_ANCESTORS_ENV, "").strip()

    sources: list[str] = []
    seen: set[str] = set()

    for raw_source in _split_frame_ancestor_sources(raw_value):
        source = _normalize_frame_ancestor_source(raw_source)
        if source and source not in seen:
            sources.append(source)
            seen.add(source)

    return sources


def build_content_security_policy(frame_ancestors: list[str] | None = None) -> str:
    ancestors_value = " ".join(frame_ancestors or []) or "'none'"
    return _CSP_PREFIX + f"frame-ancestors {ancestors_value}; " + _CSP_SUFFIX


def should_emit_x_frame_options(frame_ancestors: list[str] | None = None) -> bool:
    return not bool(frame_ancestors)
