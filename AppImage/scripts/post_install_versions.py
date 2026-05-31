"""Sprint 12A: Detect ProxMenux post-install function updates.

Parses /usr/local/share/proxmenux/scripts/post_install/{auto,customizable}_post_install.sh,
extracting the ``# version: X.Y`` and ``# description: ...`` comments
declared inside each top-level function. Compares the parsed versions
against the per-tool entries in ``installed_tools.json`` and returns the
list of tools where the on-disk script has bumped past what the user
installed.

The detection runs once at AppImage startup, before the rest of the
update-check pipeline kicks in, and the result is cached in memory and
persisted to ``updates_available.json`` so the bash menu and the
notification poller can read it without re-parsing.

Backward compatibility: ``installed_tools.json`` was originally a flat
dict of ``{key: bool}``. Sprint 12A adds the structured
``{key: {installed, version, source}}`` shape. Legacy booleans are read
as installed (true) at version ``1.0`` with source unknown. Unknown
source means the detector still flags an available update, but the UI
falls back to asking the user which flow (auto vs custom) to run.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

_BASE = Path("/usr/local/share/proxmenux")
_POST_INSTALL_DIR = _BASE / "scripts" / "post_install"
_AUTO_SCRIPT = _POST_INSTALL_DIR / "auto_post_install.sh"
_CUSTOM_SCRIPT = _POST_INSTALL_DIR / "customizable_post_install.sh"
_INSTALLED_JSON = _BASE / "installed_tools.json"
_UPDATES_JSON = _BASE / "updates_available.json"

# Match a top-level bash function definition:  func_name() {
_FN_DEF_RE = re.compile(r"^(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\s*\(\)\s*\{\s*$")
# Sprint 12A v2: read `local FUNC_VERSION="X.Y"` rather than a
# `# version:` comment. Bash's `declare -f` strips comments at parse
# time, so the comment-based version was lost the moment the update
# wrapper sourced the script and re-ran the function — register_tool
# always saw the default 1.0 fallback. A `local` assignment survives
# `declare -f` round-trip and runs at function invocation time.
_VERSION_RE = re.compile(r'local\s+FUNC_VERSION\s*=\s*"([0-9]+(?:\.[0-9]+)+)"')
_DESC_RE = re.compile(r"#\s*description\s*:\s*([^\n]+)")
_REGISTER_RE = re.compile(r'\bregister_tool\s+"([^"]+)"\s+true\b')

# In-memory cache of the last scan. Sprint 12A uses a single startup scan
# plus on-demand re-scan via the API; no automatic refresh.
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {
    "scanned_at": 0.0,
    "auto": {},          # tool_key -> {function, version, description}
    "custom": {},        # same shape
    "installed": {},     # normalized installed_tools.json
    "updates": [],       # list of update dicts
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _version_tuple(value: str) -> tuple[int, ...]:
    """Convert "1.2.3" → (1, 2, 3) for safe ordered comparison.

    Non-numeric segments are dropped silently so a stray "1.0a" doesn't
    crash the comparator. An empty/None input returns (0,) so missing
    metadata is treated as the lowest possible version.
    """
    if not value:
        return (0,)
    parts: list[int] = []
    for chunk in str(value).split("."):
        m = re.match(r"\d+", chunk)
        if m:
            parts.append(int(m.group(0)))
    return tuple(parts) if parts else (0,)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Bash script parser
# ---------------------------------------------------------------------------

def parse_post_install_script(path: Path) -> dict[str, dict[str, str]]:
    """Walk a post-install bash script and return ``{tool_key: meta}``.

    For each top-level ``func_name() {`` block, scan the body for the
    first ``# version:`` and ``# description:`` comments and the first
    ``register_tool "key" true`` call. The tool key is taken from that
    register_tool — bash function names like ``install_log2ram_auto``
    don't match the user-facing key ``log2ram`` directly, so we use the
    register_tool argument as the source of truth.

    Returns an empty dict if the file is missing or unparseable so the
    detector keeps running on partial installs.
    """
    text = _read_text(path)
    if not text:
        return {}

    lines = text.splitlines()
    result: dict[str, dict[str, str]] = {}

    i = 0
    while i < len(lines):
        line = lines[i]
        match = _FN_DEF_RE.match(line)
        if not match:
            i += 1
            continue

        func_name = match.group("name")
        # Find the matching closing brace at column 0. Bash post-install
        # scripts use the convention `}` on its own line at the start of
        # the line to close top-level functions, so we scan until that.
        body_start = i + 1
        body_end = body_start
        while body_end < len(lines) and not lines[body_end].rstrip() == "}":
            body_end += 1

        body = "\n".join(lines[body_start:body_end])

        version_match = _VERSION_RE.search(body)
        desc_match = _DESC_RE.search(body)
        register_match = _REGISTER_RE.search(body)

        if register_match:
            tool_key = register_match.group(1)
            entry = {
                "function": func_name,
                "version": version_match.group(1) if version_match else "1.0",
                "description": desc_match.group(1).strip() if desc_match else "",
            }
            # If the same tool key is registered by multiple functions
            # within the same script (rare — usually a tool has one
            # canonical install function per script), keep the highest
            # version — that's the one the user would land on after a
            # full re-run.
            existing = result.get(tool_key)
            if existing is None or _version_tuple(entry["version"]) > _version_tuple(existing["version"]):
                result[tool_key] = entry

        i = body_end + 1

    return result


# ---------------------------------------------------------------------------
# Installed tools loader (backward compat)
# ---------------------------------------------------------------------------

def load_installed_tools(path: Path = _INSTALLED_JSON) -> dict[str, dict[str, Any]]:
    """Load installed_tools.json normalising both the legacy boolean
    shape and the new structured object shape.

    Returns ``{tool_key: {"installed": bool, "version": str, "source": str}}``.
    Legacy ``true`` entries become ``{installed: true, version: "1.0",
    source: ""}``. Legacy ``false`` entries (uninstalled marker) come
    back as ``{installed: false, ...}`` and the detector skips them.
    """
    try:
        raw = json.loads(_read_text(path) or "{}")
    except json.JSONDecodeError:
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, bool):
            normalized[key] = {
                "installed": value,
                "version": "1.0" if value else "",
                "source": "",
            }
        elif isinstance(value, dict):
            normalized[key] = {
                "installed": bool(value.get("installed", False)),
                "version": str(value.get("version", "1.0")) or "1.0",
                "source": str(value.get("source", "") or ""),
            }
        else:
            # Unknown shape — treat as not installed rather than crash.
            normalized[key] = {"installed": False, "version": "", "source": ""}
    return normalized


# ---------------------------------------------------------------------------
# Detection logic
# ---------------------------------------------------------------------------

def _detect_updates(
    auto_meta: dict[str, dict[str, str]],
    custom_meta: dict[str, dict[str, str]],
    installed: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare declared versions vs installed versions for each tool.

    The source recorded in installed_tools.json picks which script to
    compare against:

    - source == "auto"   → auto_meta[key]
    - source == "custom" → custom_meta[key]
    - source missing     → falls back to whichever script declares the
      tool. If both do, prefer auto (the simpler flow). The UI can
      still ask the user which flow to run on update — Sprint 12A only
      exposes the available version, not the runner.
    """
    updates: list[dict[str, Any]] = []

    for key, info in installed.items():
        if not info.get("installed"):
            continue

        installed_version = info.get("version") or "1.0"
        source = info.get("source") or ""

        meta = None
        chosen_source = source
        if source == "auto":
            meta = auto_meta.get(key)
        elif source == "custom":
            meta = custom_meta.get(key)
        else:
            meta = auto_meta.get(key) or custom_meta.get(key)
            chosen_source = "auto" if key in auto_meta else ("custom" if key in custom_meta else "")

        if not meta:
            # Tool is installed but not declared in either script (could
            # be from a global helper script — see Sprint 12A scope
            # notes). Skip silently rather than flag a phantom update.
            continue

        declared_version = meta.get("version", "1.0")
        if _version_tuple(declared_version) > _version_tuple(installed_version):
            updates.append({
                "key": key,
                "function": meta.get("function", ""),
                "description": meta.get("description", ""),
                "current_version": installed_version,
                "available_version": declared_version,
                "source": chosen_source,
                "source_certain": bool(source),
            })

    # Stable ordering helps the UI render a deterministic list.
    updates.sort(key=lambda u: u["key"])
    return updates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan(persist: bool = True) -> dict[str, Any]:
    """Run a full scan and refresh the in-memory cache.

    Parses both post-install scripts, reads the installed_tools JSON,
    computes the update list, and (optionally) writes the result to
    ``updates_available.json`` for non-Python consumers (the bash menu
    in Sprint 12C).
    """
    auto_meta = parse_post_install_script(_AUTO_SCRIPT)
    custom_meta = parse_post_install_script(_CUSTOM_SCRIPT)
    installed = load_installed_tools()
    updates = _detect_updates(auto_meta, custom_meta, installed)

    snapshot = {
        "scanned_at": time.time(),
        "auto": auto_meta,
        "custom": custom_meta,
        "installed": installed,
        "updates": updates,
    }

    with _cache_lock:
        _cache.update(snapshot)

    if persist:
        try:
            _UPDATES_JSON.parent.mkdir(parents=True, exist_ok=True)
            _UPDATES_JSON.write_text(
                json.dumps(
                    {"scanned_at": snapshot["scanned_at"], "updates": updates},
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            # Writing the on-disk cache is best-effort. If /usr/local
            # is read-only (some hardened setups) the in-memory cache
            # still serves the API.
            pass

    return snapshot


def scan_at_startup() -> dict[str, Any]:
    """Convenience wrapper called from flask_server startup.

    Wraps ``scan()`` with broad exception handling so a parse failure
    can never break the AppImage boot sequence — the rest of the
    update-check pipeline (Proxmox upgrade scan, ProxMenux self-update)
    must run regardless of whether post-install detection works.
    """
    try:
        return scan(persist=True)
    except Exception as e:  # noqa: BLE001 — startup best-effort
        print(f"[post_install_versions] startup scan failed: {e}")
        return {"scanned_at": time.time(), "updates": []}


def _ensure_fresh_cache() -> None:
    """Re-run a scan when any of the inputs to the last scan have been
    modified since it completed.

    The relevant inputs are:
      • ``installed_tools.json`` — bumped by ``register_tool`` in bash
        after a successful install/update. Without this, the badge count
        would lag a successful update until the next 24h cycle.
      • ``auto_post_install.sh`` / ``customizable_post_install.sh`` —
        bumped when the user pulls a new version of the ProxMenux repo
        (or when ``scripts/`` is rsynced). Without this, scripts on
        disk could declare a newer ``FUNC_VERSION`` than the cached
        scan saw, so updates would silently fail to surface until the
        AppImage is restarted.
    """
    latest_input_mtime = 0.0
    for path in (_INSTALLED_JSON, _AUTO_SCRIPT, _CUSTOM_SCRIPT):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_input_mtime:
            latest_input_mtime = mtime
    if latest_input_mtime == 0.0:
        return
    with _cache_lock:
        last_scanned = _cache.get("scanned_at", 0.0)
    if latest_input_mtime > last_scanned:
        try:
            scan(persist=True)
        except Exception as e:  # noqa: BLE001 — best-effort refresh
            print(f"[post_install_versions] auto-refresh scan failed: {e}")


def get_updates() -> list[dict[str, Any]]:
    """Return the cached update list (most recent scan)."""
    _ensure_fresh_cache()
    with _cache_lock:
        return list(_cache.get("updates", []))


def get_snapshot() -> dict[str, Any]:
    """Return a shallow copy of the entire cache snapshot."""
    _ensure_fresh_cache()
    with _cache_lock:
        return {
            "scanned_at": _cache.get("scanned_at", 0.0),
            "auto": dict(_cache.get("auto", {})),
            "custom": dict(_cache.get("custom", {})),
            "installed": dict(_cache.get("installed", {})),
            "updates": list(_cache.get("updates", [])),
        }


def get_metadata_for_tool(key: str) -> dict[str, str] | None:
    """Return ``{version, description, function, source}`` for a tool.

    Used by the existing ``/api/proxmenux/installed-tools`` endpoint so
    it can serve the live declared version + description instead of the
    hard-coded TOOL_METADATA table. Picks the entry that matches the
    installed source when available; falls back to whichever script
    declares the tool.
    """
    snapshot = get_snapshot()
    installed = snapshot["installed"].get(key, {})
    source = installed.get("source") or ""
    auto = snapshot["auto"].get(key)
    custom = snapshot["custom"].get(key)

    if source == "auto" and auto:
        chosen, chosen_source = auto, "auto"
    elif source == "custom" and custom:
        chosen, chosen_source = custom, "custom"
    elif auto:
        chosen, chosen_source = auto, "auto"
    elif custom:
        chosen, chosen_source = custom, "custom"
    else:
        return None

    return {
        "version": chosen.get("version", "1.0"),
        "description": chosen.get("description", ""),
        "function": chosen.get("function", ""),
        "source": chosen_source,
    }
