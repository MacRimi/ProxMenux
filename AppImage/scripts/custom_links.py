#!/usr/bin/env python3
"""User-defined web links surfaced in the Apps dashboard alongside
LXC-registered apps. Kept in a single sidecar
(/etc/proxmenux/custom_links.json) because the collection is small,
global, and never bound to a specific guest by ProxMenux itself.

Schema of each entry
--------------------
    {
        "id":         "<uuid4>",
        "name":       "<display name>",       # required
        "url":        "<http(s) URL>",        # required
        "logo_url":   "<http(s) URL or ''>",  # optional
        "category":   "<free text or ''>",    # optional
        "binding":    {                       # optional; null when unbound
            "vmid":       <int>,
            "guest_type": "lxc" | "qemu"
        },
        "created_at": <unix ts>,
        "updated_at": <unix ts>
    }

Design notes
------------
* One file (not per-VM). Volume is small; unbound links have no natural
  home; global lookups are O(N) with N tiny.
* All writes go through `save_all` which does the classic
  write-temp+rename dance so a crash mid-save can't corrupt the file.
* Validation is strict at the boundary — the frontend can send whatever;
  the backend refuses anything malformed. Fields that survive are
  exactly the schema above; unknown keys are dropped silently.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from typing import Any, Optional


_CUSTOM_LINKS_PATH = "/etc/proxmenux/custom_links.json"
_lock = threading.RLock()

# In-memory copy of the full list. Populated on first read (or by
# `warmup()` at Monitor startup) and refreshed only when a write goes
# through this module. The sidecar file is our source of truth; the
# cache exists so `/api/apps/custom-links` doesn't hit disk on every
# request. Reads always return a fresh copy so callers can't mutate
# the cached state by accident.
_cached_entries: Optional[list[dict]] = None

# Same character set / max length as the LXC-app editor uses so users
# don't have to learn two different rulesets.
_NAME_RE     = re.compile(r"^[\w\s._+\-()/:,&]{1,80}$", re.UNICODE)
_URL_RE      = re.compile(r"^https?://[\w\-._~:/?#\[\]@!$&'()*+,;=%]{1,510}$")
_CATEGORY_RE = re.compile(r"^[\w\s&/,.\-*+()]{1,60}$", re.UNICODE)
_UUID_RE     = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_GUEST_TYPES = frozenset({"lxc", "qemu"})


def _err(msg: str) -> tuple[bool, str]:
    return False, msg


# ── Persistence ────────────────────────────────────────────────────

def _read_from_disk() -> list[dict]:
    """Actually parse the sidecar file. A missing/empty/corrupt file
    returns [] — we never let bad JSON take down the whole Apps
    dashboard, the user's other data is fine."""
    try:
        with open(_CUSTOM_LINKS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, PermissionError):
        return []
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def load_all() -> list[dict]:
    """Return the current list of custom links from the in-memory
    cache. First call after a Monitor restart pays one disk read
    (~1 ms); every subsequent call is a memory op. Writes go through
    `save_all` which also refreshes the cache, so callers never see
    stale data.
    """
    global _cached_entries
    with _lock:
        if _cached_entries is None:
            _cached_entries = _read_from_disk()
        return [dict(entry) for entry in _cached_entries]


def warmup() -> int:
    """Force the cache to populate now. Invoked from Monitor startup
    so the very first `/api/apps/custom-links` request is served
    straight from memory. Returns the entry count for the log line."""
    global _cached_entries
    with _lock:
        _cached_entries = _read_from_disk()
        return len(_cached_entries)


def save_all(entries: list[dict]) -> None:
    """Persist the full list. Write-temp+rename so a crash cannot
    leave a half-written JSON on disk. Also refreshes the in-memory
    cache so the next `load_all` returns the new state without a
    disk read. Caller must have validated every entry — this
    function trusts its input and writes verbatim.
    """
    global _cached_entries
    directory = os.path.dirname(_CUSTOM_LINKS_PATH)
    os.makedirs(directory, exist_ok=True)
    payload = json.dumps(entries, ensure_ascii=False, indent=2)
    with _lock:
        tmp = f"{_CUSTOM_LINKS_PATH}.tmp.{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
                f.write("\n")
            os.replace(tmp, _CUSTOM_LINKS_PATH)
            _cached_entries = [dict(e) for e in entries]
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass


# ── Validation ─────────────────────────────────────────────────────

def _validate_binding(raw: Any) -> tuple[bool, Any]:
    """Accepts either null (unbound) or {vmid, guest_type}. Coerces
    vmid to int and guest_type to one of the allowed literals."""
    if raw in (None, "", {}):
        return True, None
    if not isinstance(raw, dict):
        return _err("binding must be an object with {vmid, guest_type}")
    vmid_raw = raw.get("vmid")
    try:
        vmid = int(vmid_raw)
    except (TypeError, ValueError):
        return _err("binding.vmid must be an integer")
    if not (0 < vmid <= 999_999_999):
        return _err("binding.vmid out of range")
    guest_type = (raw.get("guest_type") or "").strip().lower()
    if guest_type not in _GUEST_TYPES:
        return _err("binding.guest_type must be 'lxc' or 'qemu'")
    return True, {"vmid": vmid, "guest_type": guest_type}


def validate_entry(raw: Any, existing_id: Optional[str] = None) -> tuple[bool, Any]:
    """Validate a single link payload from the API layer. Returns
    (True, sanitised_dict) or (False, error_string). Fields absent in
    the input default to safe values; unknown keys are ignored."""
    if not isinstance(raw, dict):
        return _err("payload must be a JSON object")

    name = (raw.get("name") or "").strip()
    if not name:
        return _err("name is required")
    if not _NAME_RE.match(name):
        return _err("name contains invalid characters or exceeds 80 chars")

    url = (raw.get("url") or "").strip()
    if not url:
        return _err("url is required")
    if not _URL_RE.match(url):
        return _err("url must be an http(s) URL (max 512 chars)")

    logo_url = (raw.get("logo_url") or "").strip()
    if logo_url and not _URL_RE.match(logo_url):
        return _err("logo_url must be an http(s) URL (max 512 chars)")

    category = (raw.get("category") or "").strip()
    if category and not _CATEGORY_RE.match(category):
        return _err("category contains invalid characters or exceeds 60 chars")

    ok, binding = _validate_binding(raw.get("binding"))
    if not ok:
        return _err(binding)

    entry_id = existing_id or raw.get("id") or str(uuid.uuid4())
    if not _UUID_RE.match(entry_id):
        entry_id = str(uuid.uuid4())

    now = int(time.time())
    return True, {
        "id": entry_id,
        "name": name,
        "url": url,
        "logo_url": logo_url,
        "category": category,
        "binding": binding,
        "created_at": int(raw.get("created_at") or now),
        "updated_at": now,
    }


# ── CRUD helpers used by the Flask endpoints ───────────────────────

def create(payload: dict) -> tuple[bool, Any]:
    """Add a new link. Assigns a fresh UUID and appends to the file."""
    ok, entry = validate_entry(payload)
    if not ok:
        return False, entry
    with _lock:
        current = load_all()
        current.append(entry)
        save_all(current)
    return True, entry


def update(link_id: str, payload: dict) -> tuple[bool, Any]:
    """Replace one link by id. 404 if the id is unknown."""
    if not _UUID_RE.match(link_id or ""):
        return _err("invalid link id")
    with _lock:
        current = load_all()
        for i, existing in enumerate(current):
            if existing.get("id") == link_id:
                merged = dict(existing)
                merged.update(payload)
                merged["id"] = link_id  # id is immutable
                merged["created_at"] = existing.get("created_at")
                ok, entry = validate_entry(merged, existing_id=link_id)
                if not ok:
                    return False, entry
                current[i] = entry
                save_all(current)
                return True, entry
        return _err("link not found")


def delete(link_id: str) -> tuple[bool, Any]:
    """Remove one link by id. Idempotent — deleting an unknown id
    returns success so the UI doesn't have to distinguish."""
    if not _UUID_RE.match(link_id or ""):
        return _err("invalid link id")
    with _lock:
        current = load_all()
        remaining = [e for e in current if e.get("id") != link_id]
        if len(remaining) != len(current):
            save_all(remaining)
    return True, {"deleted": link_id}


def purge_binding_for_vmid(vmid: int) -> int:
    """Clear the `binding` on every link that pointed to a guest that
    no longer exists. Called from the guest lifecycle hook when a VM
    or CT is destroyed so the dashboard never surfaces a dead ID.
    Returns the number of links updated (0 or more)."""
    try:
        target = int(vmid)
    except (TypeError, ValueError):
        return 0
    changed = 0
    with _lock:
        current = load_all()
        for entry in current:
            binding = entry.get("binding") or {}
            if isinstance(binding, dict) and binding.get("vmid") == target:
                entry["binding"] = None
                entry["updated_at"] = int(time.time())
                changed += 1
        if changed:
            save_all(current)
    return changed
