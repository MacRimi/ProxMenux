"""ProxMenux-managed installs registry.

Single source of truth for "things ProxMenux installed (or detected as
already installed) and can check for updates on". Replaces the
type-specific polling we had before — every check now flows through
this module, so adding a new tracked install (Coral driver, Frigate,
etc.) is one entry in DETECTORS + one entry in CHECKERS.

Two operation modes:

* **Detection** — at AppImage startup and every 24h, every registered
  ``DETECTOR`` runs against the host. If the probe finds the thing
  installed and it's not in the registry, we add it (with
  ``installed_by="detected"`` so the operator sees we autodiscovered
  it). If it's in the registry but the probe fails, we mark it
  ``removed_at`` instead of deleting — keeps history and avoids
  spurious notifications when a probe transiently fails.

* **Update check** — for every active entry, the matching ``CHECKER``
  runs and updates ``current_version`` + ``available`` + ``latest``.
  Each checker is responsible for its own per-source cache (the
  Tailscale OCI checker memoises for 24h, NVIDIA for 7 days). The
  notification poll loop reads the registry, emits a notification when
  ``available`` flips false→true for a (type, latest) pair it hasn't
  notified yet.

Persistence is a single JSON file at
``/usr/local/share/proxmenux/managed_installs.json``. Atomic writes
via tmp+rename so a crash mid-write can't leave a half-written file.

The module is concurrency-safe: a single ``threading.RLock`` guards
every read-modify-write so the periodic detector and a request handler
calling ``get_registry()`` can run in parallel without stepping on
each other.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from typing import Any, Callable, Optional

# ─── Storage ──────────────────────────────────────────────────────────────────

_DB_DIR = "/usr/local/share/proxmenux"
_REGISTRY_PATH = os.path.join(_DB_DIR, "managed_installs.json")
_SCHEMA_VERSION = 1

_lock = threading.RLock()


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def _read_registry() -> dict:
    """Load the JSON file. Returns the canonical empty shape on first
    run / parse error / permission issue — callers always see a valid
    dict."""
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        pass
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ProxMenux] managed_installs read failed ({e}); starting fresh")
    return {"version": _SCHEMA_VERSION, "items": []}


def _write_registry(reg: dict) -> bool:
    """Atomic write — tmp + rename. Never raises; returns False on any
    OS-level failure so the caller can decide whether to retry."""
    try:
        os.makedirs(_DB_DIR, exist_ok=True)
        tmp = _REGISTRY_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _REGISTRY_PATH)
        return True
    except OSError as e:
        print(f"[ProxMenux] managed_installs write failed: {e}")
        return False


# ─── Public read API ─────────────────────────────────────────────────────────

def get_registry() -> dict:
    """Return the full registry as a dict. Pure read — the caller can
    inspect ``items`` freely. Don't mutate the returned dict."""
    with _lock:
        return _read_registry()


def get_active_items() -> list[dict]:
    """Items the host actually has installed right now (no
    ``removed_at``). Most callers want this, not the full history."""
    with _lock:
        reg = _read_registry()
    return [it for it in reg.get("items", []) if not it.get("removed_at")]


def get_item(item_id: str) -> Optional[dict]:
    with _lock:
        reg = _read_registry()
    for it in reg.get("items", []):
        if it.get("id") == item_id:
            return it
    return None


# ─── DETECTORS — auto-discovery ──────────────────────────────────────────────
#
# Each detector is a `() -> Optional[dict]` that returns the *partial*
# entry shape (id, type, name, current_version, menu_label,
# menu_script — optional fields too) if the thing is installed on the
# host, or None if it's not. The framework merges this with the
# existing registry entry (preserving history) and rewrites if
# anything changed.


def _detect_nvidia_xfree86() -> Optional[dict]:
    """Detect a host-side NVIDIA driver via `nvidia-smi`."""
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    version = (proc.stdout or "").strip().splitlines()[0].strip() if proc.stdout else ""
    if not re.match(r"^\d+\.\d+(\.\d+)?$", version):
        return None
    return {
        "id": "nvidia-host",
        "type": "nvidia_xfree86",
        "name": "NVIDIA Host Driver",
        "current_version": version,
        "menu_label": "GPU & TPU → NVIDIA Driver",
        "menu_script": "scripts/gpu_tpu/nvidia_installer.sh",
    }


def _detect_oci_apps() -> list[dict]:
    """Bridge to the OCI manager so every OCI-installed app shows up
    in the registry without a per-app detector here. The OCI manager
    is the source of truth for OCI-specific state — we just project a
    subset into our registry shape."""
    try:
        import oci_manager
    except Exception:
        return []
    try:
        installed = oci_manager.list_installed_apps() or []
    except Exception as e:
        print(f"[ProxMenux] managed_installs OCI bridge failed: {e}")
        return []
    out: list[dict] = []
    for app in installed:
        app_id = app.get("app_id") or app.get("id")
        if not app_id:
            continue
        out.append({
            "id": f"oci:{app_id}",
            "type": "oci_app",
            "name": app.get("name") or app_id,
            "current_version": None,  # filled by checker
            "menu_label": "Settings → Secure Gateway",
            "menu_script": None,  # OCI apps update via the dashboard, no bash script
            # Stash the raw app_id so the checker can find it without
            # parsing the prefixed registry id.
            "_oci_app_id": app_id,
        })
    return out


# Detectors registered here. Each returns either a single entry dict
# or a list (for sources that yield multiple items, like OCI). The
# framework normalises both shapes.
_DETECTORS: list[Callable[[], Any]] = [
    _detect_nvidia_xfree86,
    _detect_oci_apps,
]


def _normalise_detector_result(result: Any) -> list[dict]:
    if not result:
        return []
    if isinstance(result, dict):
        return [result]
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    return []


def detect_and_register() -> dict:
    """Run every detector, merge results into the registry, persist.

    Behaviour per item:
      * detected + not in registry → add, ``installed_by="detected"``
      * detected + in registry as removed → reactivate (clear removed_at)
      * detected + already active → refresh ``current_version`` and any
        metadata that changed (e.g. menu_label evolved)
      * not detected + active in registry → mark ``removed_at``

    Returns the new registry.
    """
    discovered: dict[str, dict] = {}
    for detector in _DETECTORS:
        try:
            result = detector()
        except Exception as e:
            print(f"[ProxMenux] managed_installs detector {detector.__name__} failed: {e}")
            continue
        for entry in _normalise_detector_result(result):
            if not entry.get("id"):
                continue
            discovered[entry["id"]] = entry

    with _lock:
        reg = _read_registry()
        items: list[dict] = list(reg.get("items", []))
        index = {it.get("id"): i for i, it in enumerate(items) if it.get("id")}

        now = _now_iso()

        # 1. Add new + reactivate / refresh existing.
        for item_id, entry in discovered.items():
            if item_id in index:
                existing = items[index[item_id]]
                # Reactivate if it was previously removed
                if existing.get("removed_at"):
                    existing.pop("removed_at", None)
                    existing["reactivated_at"] = now
                # Refresh metadata fields that may have evolved
                for k in ("name", "current_version", "menu_label", "menu_script"):
                    if k in entry and entry[k] is not None:
                        existing[k] = entry[k]
                # Preserve internal helpers like `_oci_app_id`
                for k, v in entry.items():
                    if k.startswith("_"):
                        existing[k] = v
                existing["last_seen"] = now
            else:
                # Brand new entry
                new_entry = {
                    "id": entry["id"],
                    "type": entry.get("type", "unknown"),
                    "name": entry.get("name", entry["id"]),
                    "current_version": entry.get("current_version"),
                    "menu_label": entry.get("menu_label"),
                    "menu_script": entry.get("menu_script"),
                    "installed_by": "detected",
                    "first_seen": now,
                    "last_seen": now,
                    "update_check": {
                        "last_check": None,
                        "available": False,
                        "latest": None,
                        "error": None,
                    },
                }
                # Carry over internals (`_oci_app_id` etc.)
                for k, v in entry.items():
                    if k.startswith("_"):
                        new_entry[k] = v
                items.append(new_entry)

        # 2. Mark missing items as removed (don't delete — preserve
        #    history so a reinstall doesn't lose the audit trail).
        for it in items:
            if not it.get("id") or it.get("removed_at"):
                continue
            if it["id"] not in discovered:
                it["removed_at"] = now

        reg["items"] = items
        reg["version"] = _SCHEMA_VERSION
        reg["last_detect"] = now
        _write_registry(reg)
        return reg


# ─── CHECKERS — per-type update probes ───────────────────────────────────────
#
# A checker takes a registry entry and returns the *update* part of
# the registry shape:
#     {available, latest, last_check, error?}
# It must be idempotent and may use its own internal cache so we don't
# pay the upstream cost on every call.


def _check_oci_app(entry: dict) -> dict:
    """Delegate to oci_manager — already has its own 24h cache."""
    app_id = entry.get("_oci_app_id") or entry.get("id", "").removeprefix("oci:")
    if not app_id:
        return {"available": False, "latest": None, "last_check": _now_iso(),
                "error": "no app_id in registry entry"}
    try:
        import oci_manager
        state = oci_manager.check_app_update_available(app_id, force=False)
    except Exception as e:
        return {"available": False, "latest": None, "last_check": _now_iso(),
                "error": str(e)}
    if state.get("error"):
        return {"available": False, "latest": None, "last_check": _now_iso(),
                "error": state["error"]}
    return {
        "available": bool(state.get("available")),
        "latest": state.get("latest_version"),
        "current": state.get("current_version"),
        "last_check": state.get("last_checked_iso") or _now_iso(),
        "error": None,
        "_packages": state.get("packages") or [],
    }


# ── NVIDIA driver checker ──
#
# Source of truth for what's available upstream:
#   `https://download.nvidia.com/XFree86/Linux-x86_64/latest.txt`
#       returns the single newest version, e.g. "580.105.08"
#   `https://download.nvidia.com/XFree86/Linux-x86_64/`
#       HTML directory listing — we scrape it for per-branch latest
#       (so a user on 570.x gets 570.x's latest, not pushed to 580.x
#       unless their kernel forces a branch upgrade).
#
# Cache TTL is 7 days because NVIDIA's release cadence on each branch
# is roughly monthly. The cache is in-memory only; AppImage restarts
# refresh it for free.

_NVIDIA_BASE = "https://download.nvidia.com/XFree86/Linux-x86_64"
_NVIDIA_CACHE_TTL = 7 * 86400
_nvidia_cache: dict[str, Any] = {"versions": [], "fetched_at": 0}


def _nvidia_kernel_compat() -> dict:
    """Python port of `get_kernel_compatibility_info` in the bash
    installer. Returns ``{kernel, min_version, recommended_branch,
    note}``. Kept identical to the bash matrix so the recommendation
    here matches what the installer would do."""
    try:
        kernel = subprocess.run(
            ["uname", "-r"], capture_output=True, text=True, timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        kernel = ""
    parts = kernel.split(".") if kernel else []
    try:
        major = int(parts[0]) if len(parts) >= 1 else 0
        minor = int(parts[1]) if len(parts) >= 2 else 0
    except (ValueError, TypeError):
        major, minor = 0, 0

    if major >= 7 or (major == 6 and minor >= 17):
        return {
            "kernel": kernel,
            "min_version": "580.105.08",
            "recommended_branch": "580",
            "note": (f"Kernel {kernel} requires NVIDIA driver 580.105.08 or "
                     f"newer (older 580.x builds fail to compile)"),
        }
    if major >= 6 and minor >= 8:
        return {"kernel": kernel, "min_version": "550",
                "recommended_branch": "580",
                "note": f"Kernel {kernel} works with NVIDIA driver 550.x or newer"}
    if major >= 6:
        return {"kernel": kernel, "min_version": "535",
                "recommended_branch": "550",
                "note": f"Kernel {kernel} works with NVIDIA driver 535.x or newer"}
    if major == 5 and minor >= 15:
        return {"kernel": kernel, "min_version": "470",
                "recommended_branch": "535",
                "note": f"Kernel {kernel} works with NVIDIA driver 470.x or newer"}
    return {"kernel": kernel, "min_version": "450",
            "recommended_branch": "470",
            "note": "For older kernels, compatibility may vary"}


def _version_tuple(v: str) -> tuple:
    """Convert ``580.105.08`` → ``(580, 105, 8)`` for comparison.
    Pads to 3 components so ``580.82`` < ``580.105.08``."""
    out = []
    for chunk in v.split("."):
        try:
            out.append(int(chunk))
        except (ValueError, TypeError):
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def _fetch_nvidia_versions(force: bool = False) -> list[str]:
    """Return the cached list of all upstream versions, or fetch fresh."""
    now = time.time()
    if not force and _nvidia_cache["versions"] and \
       now - _nvidia_cache["fetched_at"] < _NVIDIA_CACHE_TTL:
        return _nvidia_cache["versions"]
    try:
        req = urllib.request.Request(
            _NVIDIA_BASE + "/",
            headers={"User-Agent": "ProxMenux-Monitor/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[ProxMenux] NVIDIA version fetch failed: {e}")
        return _nvidia_cache.get("versions", [])
    versions = sorted(
        {m.group(1) for m in re.finditer(
            r"""href=['"](\d+\.\d+(?:\.\d+)?)/?['"]""", html)},
        key=_version_tuple,
        reverse=True,
    )
    if versions:
        _nvidia_cache["versions"] = versions
        _nvidia_cache["fetched_at"] = now
    return versions


def _is_compat_with_kernel(version: str, kernel_compat: dict) -> bool:
    """Compare ``version`` (e.g. ``580.105.08``) against the kernel
    compatibility floor. Mirrors the bash ``is_version_compatible``
    helper (full-triple compare when min is dotted, major-only otherwise)."""
    min_str = kernel_compat.get("min_version", "0")
    if "." in min_str and re.match(r"^\d+\.\d+\.\d+$", min_str):
        return _version_tuple(version) >= _version_tuple(min_str)
    # Single-major threshold like "535" or "550"
    try:
        ver_major = int(version.split(".")[0])
        min_major = int(min_str)
    except (ValueError, TypeError):
        return True
    return ver_major >= min_major


def _check_nvidia_xfree86(entry: dict) -> dict:
    """Compute the update state for a host NVIDIA driver entry.

    Policy (Option C from the design discussion):
      1. Same-branch newer version available → notify.
      2. Current branch no longer compatible with current kernel →
         notify a branch upgrade with explicit messaging.
    """
    current = entry.get("current_version")
    if not current or not re.match(r"^\d+\.\d+(\.\d+)?$", current):
        return {"available": False, "latest": None,
                "last_check": _now_iso(), "error": "no installed version"}

    versions = _fetch_nvidia_versions()
    if not versions:
        return {"available": False, "latest": None,
                "last_check": _now_iso(),
                "error": "could not parse upstream version listing"}

    kernel_compat = _nvidia_kernel_compat()
    current_branch = current.split(".")[0]

    same_branch = [v for v in versions if v.split(".")[0] == current_branch
                   and _is_compat_with_kernel(v, kernel_compat)]
    same_branch_latest = same_branch[0] if same_branch else None

    notify_branch_upgrade = False
    branch_upgrade_target: Optional[str] = None
    if not _is_compat_with_kernel(current, kernel_compat):
        # Current branch / version no longer works with current kernel.
        # Recommend the kernel-recommended branch's latest.
        rec_branch = kernel_compat["recommended_branch"]
        rec_branch_versions = [v for v in versions
                                if v.split(".")[0] == rec_branch
                                and _is_compat_with_kernel(v, kernel_compat)]
        if rec_branch_versions:
            branch_upgrade_target = rec_branch_versions[0]
            notify_branch_upgrade = True

    available = False
    latest: Optional[str] = None
    upgrade_kind = None  # "patch" | "branch_upgrade" | None

    if notify_branch_upgrade and branch_upgrade_target:
        latest = branch_upgrade_target
        available = True
        upgrade_kind = "branch_upgrade"
    elif same_branch_latest and \
         _version_tuple(same_branch_latest) > _version_tuple(current):
        latest = same_branch_latest
        available = True
        upgrade_kind = "patch"

    return {
        "available": available,
        "latest": latest,
        "last_check": _now_iso(),
        "error": None,
        "_upgrade_kind": upgrade_kind,
        "_kernel": kernel_compat.get("kernel"),
        "_kernel_note": kernel_compat.get("note"),
    }


_CHECKERS: dict[str, Callable[[dict], dict]] = {
    "oci_app": _check_oci_app,
    "nvidia_xfree86": _check_nvidia_xfree86,
}


def check_for_updates(force: bool = False) -> list[dict]:
    """Run every type-specific checker over active items, persist
    the updated state, return the list of items that have an update
    available right now.

    The notification poller turns the returned list into events; the
    UI reads ``get_active_items()`` to render the inline "update
    available" line.

    ``force`` invalidates the per-source caches (currently only the
    NVIDIA versions list — OCI keeps its own internal cache).
    """
    if force:
        _nvidia_cache["versions"] = []
        _nvidia_cache["fetched_at"] = 0

    updates_available: list[dict] = []
    with _lock:
        reg = _read_registry()
        items = reg.get("items", [])
        for it in items:
            if it.get("removed_at"):
                continue
            checker = _CHECKERS.get(it.get("type"))
            if not checker:
                continue
            try:
                result = checker(it)
            except Exception as e:
                print(f"[ProxMenux] managed_installs checker failed for "
                      f"{it.get('id')}: {e}")
                result = {"available": False, "latest": None,
                          "last_check": _now_iso(), "error": str(e)}

            it["update_check"] = {
                "available": bool(result.get("available")),
                "latest": result.get("latest"),
                "last_check": result.get("last_check") or _now_iso(),
                "error": result.get("error"),
            }
            if result.get("current") and not it.get("current_version"):
                it["current_version"] = result["current"]
            for extra_key in ("_packages", "_upgrade_kind", "_kernel",
                              "_kernel_note"):
                if extra_key in result:
                    it["update_check"][extra_key] = result[extra_key]

            if it["update_check"]["available"]:
                updates_available.append(it)

        reg["items"] = items
        reg["last_check_run"] = _now_iso()
        _write_registry(reg)

    return updates_available
