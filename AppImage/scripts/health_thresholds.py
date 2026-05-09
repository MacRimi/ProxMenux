"""User-configurable Health Monitor thresholds.

Until now every threshold the Health Monitor (and the notification stack
that hangs off it) compares against was a hardcoded constant in
``health_monitor.py`` and a few helper modules. Operators repeatedly
asked for the ability to tune them per host — for example, a small
homelab user is fine with the rootfs filling to 92 % before being
nagged, while a production node owner wants the alert at 80 %.

This module is the single source of truth for those thresholds. The
JSON file at ``/usr/local/share/proxmenux/health_thresholds.json``
holds only the *overrides* the user has made; anything missing falls
back to the recommended default below. That keeps forward compatibility
trivial: new thresholds added in a later version are absent from older
JSON files and just resolve to their recommended value.

Public surface:

    DEFAULTS          — nested dict of recommended values + per-field metadata
    get(section, key) — read effective value (override or default)
    load()            — return the user-configured overrides (no defaults applied)
    load_effective()  — return a fully-merged config (defaults + overrides)
    save(payload)     — validate & persist a partial or full config
    reset_section(s)  — clear all overrides for one section
    reset_all()       — wipe every override
    invalidate_cache()— force the next ``get`` to re-read from disk

Every public function is safe to call from request handlers and from
the background health collector concurrently. A 5-second in-memory
cache avoids disk reads on the hot path; the cache is invalidated on
save/reset.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Recommended defaults + metadata
#
# Each leaf entry is a dict with at least ``value``. The other keys
# describe validation and UI hints so the frontend can render the
# right input type without round-tripping schema info separately.
#
# Sections are designed to match the UI subsections one-to-one:
#   cpu              — CPU usage %
#   memory           — RAM and swap %
#   host_storage     — host filesystems (rootfs, /var/lib/vz, /mnt/*)
#   lxc_rootfs       — per-CT root disk %
#   cpu_temperature  — CPU °C
#   disk_temperature — per-disk-class °C (hdd / ssd / nvme / sas)
#
# Phase 3 will add: lxc_mount, pve_storage, zfs_pool.
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "cpu": {
        "warning": {"value": 85, "unit": "%", "min": 1, "max": 100, "step": 1},
        "critical": {"value": 95, "unit": "%", "min": 1, "max": 100, "step": 1},
    },
    "memory": {
        "warning": {"value": 85, "unit": "%", "min": 1, "max": 100, "step": 1},
        "critical": {"value": 95, "unit": "%", "min": 1, "max": 100, "step": 1},
        "swap_critical": {"value": 5, "unit": "%", "min": 1, "max": 100, "step": 1},
    },
    "host_storage": {
        "warning": {"value": 85, "unit": "%", "min": 1, "max": 100, "step": 1},
        "critical": {"value": 95, "unit": "%", "min": 1, "max": 100, "step": 1},
    },
    "lxc_rootfs": {
        "warning": {"value": 85, "unit": "%", "min": 1, "max": 100, "step": 1},
        "critical": {"value": 95, "unit": "%", "min": 1, "max": 100, "step": 1},
    },
    "cpu_temperature": {
        "warning": {"value": 80, "unit": "°C", "min": 30, "max": 120, "step": 1},
        "critical": {"value": 90, "unit": "°C", "min": 30, "max": 120, "step": 1},
    },
    "disk_temperature": {
        "hdd": {
            "warning": {"value": 60, "unit": "°C", "min": 30, "max": 100, "step": 1},
            "critical": {"value": 65, "unit": "°C", "min": 30, "max": 100, "step": 1},
        },
        "ssd": {
            "warning": {"value": 70, "unit": "°C", "min": 30, "max": 100, "step": 1},
            "critical": {"value": 75, "unit": "°C", "min": 30, "max": 100, "step": 1},
        },
        "nvme": {
            "warning": {"value": 80, "unit": "°C", "min": 30, "max": 110, "step": 1},
            "critical": {"value": 85, "unit": "°C", "min": 30, "max": 110, "step": 1},
        },
        "sas": {
            "warning": {"value": 55, "unit": "°C", "min": 30, "max": 100, "step": 1},
            "critical": {"value": 65, "unit": "°C", "min": 30, "max": 100, "step": 1},
        },
    },
    # ── Phase 3: capacity checks added in this sprint ──────────────────
    # These three sections drive new health checks that didn't exist
    # before. Defaults match the host-storage thresholds so users who
    # never customise see consistent alerting across all storage layers.
    "lxc_mount": {
        # Capacity of mountpoints inside running LXCs (mp0, mp1, NFS,
        # bind mounts, etc.). Excludes pseudo-filesystems and the CT
        # rootfs (already covered by `lxc_rootfs`).
        "warning": {"value": 85, "unit": "%", "min": 1, "max": 100, "step": 1},
        "critical": {"value": 95, "unit": "%", "min": 1, "max": 100, "step": 1},
    },
    "pve_storage": {
        # Capacity of PVE-registered storages that are not surfaced as
        # a host filesystem (LVM/LVM-thin/RBD/ZFS-pool/PBS). Filesystem
        # storages (dir/nfs/cifs) are already covered by `host_storage`
        # via the underlying mount.
        "warning": {"value": 85, "unit": "%", "min": 1, "max": 100, "step": 1},
        "critical": {"value": 95, "unit": "%", "min": 1, "max": 100, "step": 1},
    },
    "zfs_pool": {
        # ZFS pool fill level via `zpool list -H -p -o capacity`. Runs
        # independently of PVE so pools that aren't registered as PVE
        # storage (e.g. rpool, dedicated backup pools) still get
        # monitored.
        "warning": {"value": 85, "unit": "%", "min": 1, "max": 100, "step": 1},
        "critical": {"value": 95, "unit": "%", "min": 1, "max": 100, "step": 1},
    },
}


# ---------------------------------------------------------------------------
# Storage & cache
# ---------------------------------------------------------------------------

_DB_DIR = "/usr/local/share/proxmenux"
_CONFIG_PATH = os.path.join(_DB_DIR, "health_thresholds.json")

_CACHE_TTL = 5  # seconds — cheap enough to skip disk reads on every comparison
_lock = threading.Lock()
_cache: dict[str, Any] = {"data": None, "time": 0.0}


def _read_disk() -> dict:
    """Load the JSON override file. Returns {} on first run / missing /
    parse error so callers always see a valid dict."""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ProxMenux] health_thresholds: read failed ({e}); using defaults")
        return {}


def _write_disk(data: dict) -> bool:
    """Persist the override dict atomically (write-and-rename so a
    crash mid-write can't leave a half-written JSON behind)."""
    try:
        os.makedirs(_DB_DIR, exist_ok=True)
        tmp = _CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _CONFIG_PATH)
        return True
    except OSError as e:
        print(f"[ProxMenux] health_thresholds: write failed: {e}")
        return False


def invalidate_cache() -> None:
    """Force the next ``get`` to re-read from disk."""
    with _lock:
        _cache["data"] = None
        _cache["time"] = 0.0


def _cached_overrides() -> dict:
    """Return the current overrides dict, hitting disk at most every
    ``_CACHE_TTL`` seconds. Lock ensures multiple threads don't race
    to read the same file."""
    now = time.time()
    with _lock:
        if _cache["data"] is None or now - _cache["time"] >= _CACHE_TTL:
            _cache["data"] = _read_disk()
            _cache["time"] = now
        return _cache["data"]


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------

def get(section: str, *path: str, default: Optional[float] = None) -> Optional[float]:
    """Read an effective threshold value.

    Examples::

        get("cpu", "warning")               -> 85 (or user override)
        get("disk_temperature", "nvme", "warning") -> 80 (or override)

    Order: user override (if present and valid) → recommended default →
    the ``default`` argument. Returns a number, not the metadata dict.
    """
    overrides = _cached_overrides()

    # Walk the override tree
    node: Any = overrides
    for p in (section,) + path:
        if not isinstance(node, dict):
            node = None
            break
        node = node.get(p)
    if isinstance(node, (int, float)):
        return float(node)

    # Fall back to recommended
    node = DEFAULTS
    for p in (section,) + path:
        if not isinstance(node, dict):
            return default
        node = node.get(p)
        if node is None:
            return default
    if isinstance(node, dict) and "value" in node:
        return float(node["value"])
    if isinstance(node, (int, float)):
        return float(node)
    return default


def load() -> dict:
    """Return the raw user overrides (no defaults merged in). Use this
    for the GET endpoint when the frontend wants to know what's
    customised vs untouched."""
    return _cached_overrides()


def load_effective() -> dict:
    """Return a fully-merged tree (defaults + overrides), shaped like
    DEFAULTS but with the leaf ``value`` replaced by the effective
    threshold and an extra ``customised`` boolean per leaf."""
    overrides = _cached_overrides()

    def merge(default_node: Any, override_node: Any) -> Any:
        if isinstance(default_node, dict) and "value" in default_node:
            # Leaf
            ov = override_node if isinstance(override_node, (int, float)) else None
            return {
                **default_node,
                "value": float(ov) if ov is not None else default_node["value"],
                "recommended": default_node["value"],
                "customised": ov is not None,
            }
        if isinstance(default_node, dict):
            ov_dict = override_node if isinstance(override_node, dict) else {}
            return {k: merge(v, ov_dict.get(k)) for k, v in default_node.items()}
        return default_node

    return merge(DEFAULTS, overrides)


# ---------------------------------------------------------------------------
# Validation + write API
# ---------------------------------------------------------------------------

class ThresholdValidationError(ValueError):
    """Raised when a save() payload violates the defaults' min/max range."""


def _validate(section: str, path: tuple[str, ...], value: Any) -> float:
    """Resolve metadata for the given leaf path, coerce ``value`` to
    float, and check it against min/max. Raises ThresholdValidationError
    on any problem."""
    meta: Any = DEFAULTS
    for p in (section,) + path:
        if not isinstance(meta, dict) or p not in meta:
            raise ThresholdValidationError(f"Unknown threshold: {section}.{'.'.join(path)}")
        meta = meta[p]
    if not isinstance(meta, dict) or "value" not in meta:
        raise ThresholdValidationError(f"Path {section}.{'.'.join(path)} is not a leaf")

    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ThresholdValidationError(
            f"{section}.{'.'.join(path)} must be a number, got {value!r}"
        )

    if v != v or v in (float("inf"), float("-inf")):
        raise ThresholdValidationError(f"{section}.{'.'.join(path)}: NaN/Inf not allowed")

    lo = meta.get("min")
    hi = meta.get("max")
    if lo is not None and v < lo:
        raise ThresholdValidationError(
            f"{section}.{'.'.join(path)}: {v} < min {lo}"
        )
    if hi is not None and v > hi:
        raise ThresholdValidationError(
            f"{section}.{'.'.join(path)}: {v} > max {hi}"
        )
    return v


def _walk_and_validate(payload: dict, defaults_subtree: Any, path: tuple[str, ...]) -> dict:
    """Recursively walk ``payload`` mirroring ``defaults_subtree``'s
    shape. Returns a clean dict with only valid leaves and validated
    floats, or raises on the first problem."""
    cleaned: dict[str, Any] = {}
    if not isinstance(defaults_subtree, dict):
        return cleaned
    for key, value in payload.items():
        if key not in defaults_subtree:
            raise ThresholdValidationError(f"Unknown key: {'.'.join(path + (key,))}")
        sub_default = defaults_subtree[key]
        if isinstance(sub_default, dict) and "value" in sub_default:
            # Leaf — validate value
            cleaned[key] = _validate(path[0], path[1:] + (key,), value)
        elif isinstance(sub_default, dict):
            if not isinstance(value, dict):
                raise ThresholdValidationError(
                    f"{'.'.join(path + (key,))} expected dict, got {type(value).__name__}"
                )
            sub = _walk_and_validate(value, sub_default, path + (key,))
            if sub:
                cleaned[key] = sub
    return cleaned


def save(payload: dict) -> dict:
    """Validate and persist a partial or full payload. Only the keys
    present in ``payload`` are touched — existing overrides for other
    sections survive. Returns the new effective tree (same shape as
    ``load_effective``).

    Raises ThresholdValidationError on any invalid value; nothing is
    persisted in that case.

    Sanity rules beyond min/max are enforced here too:
      - critical >= warning for every section that has both
    """
    if not isinstance(payload, dict):
        raise ThresholdValidationError("payload must be an object")

    # Walk and produce a cleaned, fully-validated subset
    new_overrides: dict[str, Any] = {}
    for section_key, section_payload in payload.items():
        if section_key not in DEFAULTS:
            raise ThresholdValidationError(f"Unknown section: {section_key}")
        if not isinstance(section_payload, dict):
            raise ThresholdValidationError(f"Section {section_key} must be an object")
        cleaned = _walk_and_validate(section_payload, DEFAULTS[section_key], (section_key,))
        if cleaned:
            new_overrides[section_key] = cleaned

    # Cross-field check: critical must not be lower than warning.
    # Computed against the *effective* tree (existing overrides + this
    # payload + defaults) so a partial save like "only warning=70" is
    # checked against the existing critical value.
    existing = _cached_overrides()
    merged = _merge_overrides(existing, new_overrides)
    _check_warn_le_crit(merged)

    # Merge into the on-disk overrides (preserve sections not touched
    # by this payload). Empty values inside cleaned mean "remove that
    # leaf" — handled by _merge_overrides.
    final = _merge_overrides(existing, new_overrides)

    if not _write_disk(final):
        raise ThresholdValidationError("Failed to persist thresholds to disk")

    invalidate_cache()
    return load_effective()


def _merge_overrides(existing: dict, incoming: dict) -> dict:
    """Deep-merge ``incoming`` into ``existing``. Keys in ``incoming``
    overwrite; keys absent from ``incoming`` are preserved from
    ``existing``."""
    out: dict[str, Any] = {k: v for k, v in existing.items() if isinstance(v, dict)}
    # Also copy non-dict roots verbatim (shouldn't exist, but be tolerant)
    for k, v in existing.items():
        if k not in out:
            out[k] = v
    for k, v in incoming.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_overrides(out[k], v)
        else:
            out[k] = v
    return out


def _check_warn_le_crit(merged: dict) -> None:
    """Enforce critical >= warning for every section/sub-section that
    exposes both. ``merged`` is a flat overrides tree — we walk both
    it and DEFAULTS to resolve the effective values."""

    def effective(node_default: Any, node_over: Any, key: str) -> Optional[float]:
        if isinstance(node_over, dict) and isinstance(node_over.get(key), (int, float)):
            return float(node_over[key])
        leaf = node_default.get(key) if isinstance(node_default, dict) else None
        if isinstance(leaf, dict) and "value" in leaf:
            return float(leaf["value"])
        return None

    def walk(default_subtree: Any, override_subtree: Any, path_str: str) -> None:
        if not isinstance(default_subtree, dict):
            return
        # If this dict has both "warning" and "critical" leaves, check.
        if "warning" in default_subtree and "critical" in default_subtree and \
           isinstance(default_subtree["warning"], dict) and "value" in default_subtree["warning"]:
            warn = effective(default_subtree, override_subtree, "warning")
            crit = effective(default_subtree, override_subtree, "critical")
            if warn is not None and crit is not None and crit < warn:
                raise ThresholdValidationError(
                    f"{path_str}: critical ({crit}) must be >= warning ({warn})"
                )
        # Recurse into nested groups (disk_temperature.hdd etc.)
        for k, v in default_subtree.items():
            if isinstance(v, dict) and "value" not in v:
                ov = override_subtree.get(k) if isinstance(override_subtree, dict) else None
                walk(v, ov, f"{path_str}.{k}" if path_str else k)

    for section, section_default in DEFAULTS.items():
        ov = merged.get(section, {})
        walk(section_default, ov, section)


def reset_section(section: str) -> dict:
    """Drop every override under ``section`` (so it falls back to
    recommended). Returns the new effective tree."""
    if section not in DEFAULTS:
        raise ThresholdValidationError(f"Unknown section: {section}")
    existing = _cached_overrides()
    if section in existing:
        existing = {k: v for k, v in existing.items() if k != section}
        if not _write_disk(existing):
            raise ThresholdValidationError("Failed to persist thresholds to disk")
    invalidate_cache()
    return load_effective()


def reset_all() -> dict:
    """Wipe every override; everything falls back to recommended."""
    if not _write_disk({}):
        raise ThresholdValidationError("Failed to persist thresholds to disk")
    invalidate_cache()
    return load_effective()
