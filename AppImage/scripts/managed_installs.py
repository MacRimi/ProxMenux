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
import sqlite3
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


# ── Coral TPU host driver (PCIe gasket-dkms + USB libedgetpu1) ──
#
# Two install paths share the same registry entry because the user
# thinks of them as one "Coral driver" install. The detector returns
# one entry per path that is actually present on the host, so a system
# with both M.2 and USB Coral devices gets two entries — independent
# update streams (gasket-dkms from feranick/gasket-driver on GitHub,
# libedgetpu1-std from Google's apt repo).


def _detect_coral_host() -> list[dict]:
    out: list[dict] = []

    # PCIe / M.2 — version detection has three sources, tried in this
    # order of trust:
    #
    #   1. The marker file `/var/lib/proxmenux/coral_gasket_version`
    #      written by `install_coral.sh` after a successful DKMS
    #      install — contains the feranick release tag actually
    #      installed (e.g. `1.0-18.4`). This is the only source that
    #      knows the fork's patch level.
    #   2. `dpkg-query gasket-dkms` — the Debian package version, only
    #      present when the user installed via .deb rather than the
    #      ProxMenux script.
    #   3. `dkms status` — the upstream module version registered with
    #      DKMS, which is always the bare `1.0`. Useful as a "modules
    #      are present" indicator but doesn't reveal the fork patch
    #      level, so the update-availability check would always fire a
    #      false positive against feranick's `1.0-N` tags. Reported on
    #      .50 after a successful re-install kept showing the update
    #      notification.
    pcie_version: Optional[str] = None
    try:
        with open("/var/lib/proxmenux/coral_gasket_version",
                  "r", encoding="utf-8", errors="replace") as fh:
            marker = fh.read().strip()
            # Sanity check: the file should hold something that looks
            # like a version tag, not an error message or empty line.
            if marker and re.match(r"^[A-Za-z0-9._+-]+$", marker):
                pcie_version = marker
    except OSError:
        pass

    if not pcie_version:
        try:
            r = subprocess.run(
                ["dpkg-query", "-W", "-f=${Status}|${Version}", "gasket-dkms"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0 and "ok installed" in r.stdout:
                pcie_version = r.stdout.split("|", 1)[1].strip()
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass
    if not pcie_version:
        try:
            r = subprocess.run(
                ["dkms", "status"], capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if line.startswith("gasket"):
                        # "gasket, 1.0, ..." or "gasket/1.0, ..."
                        m = re.match(r"^gasket[, /]([^,\s]+)", line)
                        if m:
                            pcie_version = m.group(1)
                            break
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass
    if pcie_version:
        out.append({
            "id": "coral-host-pcie",
            "type": "coral_host",
            "name": "Coral TPU Driver (gasket-dkms)",
            "current_version": pcie_version,
            "menu_label": "GPU & TPU → Coral TPU",
            "menu_script": "scripts/gpu_tpu/install_coral.sh",
            "_coral_variant": "pcie",
        })

    # USB — libedgetpu1-std (default) or libedgetpu1-max if the user
    # opted into the overclocked runtime. Either one means the USB
    # path is installed.
    usb_version: Optional[str] = None
    usb_pkg: Optional[str] = None
    for pkg in ("libedgetpu1-std", "libedgetpu1-max"):
        try:
            r = subprocess.run(
                ["dpkg-query", "-W", "-f=${Status}|${Version}", pkg],
                capture_output=True, text=True, timeout=3,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and "ok installed" in r.stdout:
            usb_version = r.stdout.split("|", 1)[1].strip()
            usb_pkg = pkg
            break
    if usb_version and usb_pkg:
        out.append({
            "id": "coral-host-usb",
            "type": "coral_host",
            "name": f"Coral TPU Runtime ({usb_pkg})",
            "current_version": usb_version,
            "menu_label": "GPU & TPU → Coral TPU",
            "menu_script": "scripts/gpu_tpu/install_coral.sh",
            "_coral_variant": "usb",
            "_coral_pkg": usb_pkg,
        })

    return out


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


# ── LXC containers (Phase 1: apt-based update detection) ────────────
#
# Each running Debian/Ubuntu CT becomes a registry entry of type "lxc".
# Detection is gated on a dedicated user setting (`lxc_updates.detection_enabled`,
# default ON) configured from Settings → LXC Update Detection. When the
# user flips it OFF, this detector returns [] and any existing type="lxc"
# entries in the registry are purged so the dashboard / API immediately
# stop reporting LXC update state. The notification toggle
# (`lxc_updates_available`) keeps its independent semantics — it only
# decides whether to deliver the notification when detection has actually
# produced new results.
#
# Phase 2 hook: once helper-scripts metadata is integrated, entries can
# carry `_helper_script_app` so the checker swaps generic apt counting
# for app-specific upstream-release tracking (Vaultwarden, Jellyfin,
# etc.). For now every LXC uses the generic apt path.

_PCT_BIN = "/usr/sbin/pct"
_LXC_EXEC_TIMEOUT_SEC = 10
_LXC_OS_PROBE_TIMEOUT_SEC = 5

# User-toggle storage. The setting lives in the same SQLite DB that
# notification_manager uses for user_settings, so we get atomic writes
# and the table is already created at startup by health_persistence.
_USER_SETTINGS_DB = "/usr/local/share/proxmenux/health_monitor.db"
_LXC_DETECTION_SETTING_KEY = "lxc_updates.detection_enabled"


def _lxc_updates_detection_enabled() -> bool:
    """Read the dedicated detection toggle. Default True — existing
    installs predating this setting keep their previous behaviour.

    Read failures (DB missing, locked, corrupt) also default True so a
    transient DB problem never silently disables the feature.
    """
    try:
        if not os.path.exists(_USER_SETTINGS_DB):
            return True
        conn = sqlite3.connect(_USER_SETTINGS_DB, timeout=5)
        try:
            conn.execute("PRAGMA busy_timeout=2000")
            row = conn.execute(
                "SELECT setting_value FROM user_settings WHERE setting_key = ?",
                (_LXC_DETECTION_SETTING_KEY,),
            ).fetchone()
        finally:
            conn.close()
        if row is None or row[0] is None:
            return True
        return str(row[0]).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return True


def set_lxc_updates_detection_enabled(enabled: bool) -> dict:
    """Persist the toggle. Returns ``{ok: bool, purged: int, error?: str}``.

    On OFF, also strip every ``type=lxc`` entry from the registry so the
    dashboard and ``/api/managed-installs`` stop returning stale results
    instantly — without waiting for the next 24h detection cycle.
    """
    val = "true" if enabled else "false"
    try:
        conn = sqlite3.connect(_USER_SETTINGS_DB, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                "INSERT OR REPLACE INTO user_settings (setting_key, setting_value, updated_at) "
                "VALUES (?, ?, ?)",
                (_LXC_DETECTION_SETTING_KEY, val, _now_iso()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "purged": 0, "error": str(e)}

    purged = 0
    if not enabled:
        purged = _purge_lxc_entries_from_registry()
    return {"ok": True, "purged": purged}


def _purge_lxc_entries_from_registry() -> int:
    """Remove every type="lxc" entry from the registry. Returns the
    count of entries removed.

    Used when the user disables LXC update detection — keeps the
    on-disk state consistent with the toggle (zero stale LXC rows in
    ``managed_installs.json``).
    """
    try:
        with _lock:
            reg = _read_registry()
            items = reg.get("items", [])
            if not items:
                return 0
            kept = [
                it for it in items
                if not (isinstance(it, dict) and it.get("type") == "lxc")
            ]
            removed = len(items) - len(kept)
            if removed > 0:
                reg["items"] = kept
                _write_registry(reg)
            return removed
    except Exception as e:
        print(f"[managed_installs] failed to purge LXC entries: {e}")
        return 0


def _lxc_updates_notification_enabled() -> bool:
    """Return True if the user has enabled `lxc_updates_available` on
    at least one configured channel. Used to gate the heavy detection
    + checker work — when disabled we don't touch any CT at all.
    """
    try:
        import notification_manager as _nm_mod
        nm = _nm_mod.notification_manager
        return bool(nm.is_event_enabled("lxc_updates_available"))
    except Exception:
        return False


def _list_pve_lxcs() -> list[dict]:
    """Return basic info per LXC on this node via ``pct list``. Each
    item is ``{vmid, status, name}``. Empty list on any failure — never
    raises so the detector caller can continue.
    """
    try:
        r = subprocess.run(
            [_PCT_BIN, "list"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
    if r.returncode != 0:
        return []

    out: list[dict] = []
    for line in r.stdout.splitlines()[1:]:  # skip header row
        # `pct list` columns: VMID  Status  Lock  Name
        # `Lock` is empty most of the time, so split max 4 ways
        parts = line.split(None, 3)
        if len(parts) < 2:
            continue
        vmid = parts[0]
        status = parts[1]
        # Name is the last column; in unlocked rows the 3rd col may
        # be the name itself if Lock was omitted by the formatter.
        name = parts[-1] if len(parts) >= 3 else ""
        if not vmid.isdigit():
            continue
        out.append({"vmid": vmid, "status": status, "name": name})
    return out


_SUPPORTED_OS_FAMILIES = ("debian", "ubuntu", "alpine")


def _probe_lxc_os(vmid: str) -> Optional[str]:
    """Return a normalized family identifier (``debian`` / ``ubuntu`` /
    ``alpine``) by reading ``/etc/os-release`` inside the running CT.
    Returns None for distributions whose package manager we don't yet
    speak — those CTs are skipped in detection so the framework
    doesn't keep retrying a checker we can't run.

    Cached per CT in the registry — re-probed only when the entry has
    no ``_os_family`` yet, since the OS rarely changes for the life of
    a CT.
    """
    try:
        r = subprocess.run(
            [_PCT_BIN, "exec", vmid, "--", "cat", "/etc/os-release"],
            capture_output=True, text=True,
            timeout=_LXC_OS_PROBE_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    text = r.stdout.lower()
    if "id=ubuntu" in text:
        return "ubuntu"
    if "id=debian" in text or "id_like=debian" in text:
        return "debian"
    if "id=alpine" in text:
        return "alpine"
    # Future Phase 1.5: CentOS/Rocky/Alma (dnf check-update), Arch
    # (checkupdates), openSUSE (zypper list-updates). Each needs a
    # parser similar to apt/apk — skip silently for now.
    return None


def _detect_lxc_containers() -> list[dict]:
    """Enumerate running Debian/Ubuntu CTs as registry entries.

    OS detection is cached in the registry entry (`_os_family`), so the
    expensive ``pct exec cat /etc/os-release`` only runs the first time
    a CT is seen. CT reinstalls with a different OS will keep the old
    family cached until the user resets the registry — acceptable
    trade-off vs paying the probe cost every 24h cycle.

    Detection respects the dedicated `lxc_updates.detection_enabled`
    toggle (Settings → LXC Update Detection). When OFF, this returns []
    and the framework's removed_at logic clears any pre-existing CT
    rows from the registry on the next run — the explicit purge in
    ``set_lxc_updates_detection_enabled`` handles the immediate case.

    The notification toggle (`lxc_updates_available`) only gates the
    *delivery* of the notification (see _check_managed_installs_updates
    in notification_events.py), independently of this detection toggle.
    """
    if not _lxc_updates_detection_enabled():
        return []

    # Read existing registry so we can preserve cached `_os_family`.
    # No lock needed here — we only inspect; the framework holds the
    # write lock when it merges back our results in detect_and_register.
    try:
        existing = _read_registry().get("items", [])
    except Exception:
        existing = []
    existing_by_id = {
        it.get("id"): it for it in existing
        if isinstance(it, dict) and it.get("type") == "lxc"
    }

    cts = _list_pve_lxcs()
    out: list[dict] = []
    for ct in cts:
        if ct["status"] != "running":
            continue
        vmid = ct["vmid"]
        cid = f"lxc:{vmid}"
        prior = existing_by_id.get(cid) or {}
        os_family = prior.get("_os_family")
        if not os_family:
            os_family = _probe_lxc_os(vmid)
            if os_family not in _SUPPORTED_OS_FAMILIES:
                # Distribution we don't yet have a package-manager
                # parser for. Skip silently. The framework marks any
                # existing entry as removed_at if it stops appearing
                # in the detector output.
                continue
        out.append({
            "id": cid,
            "type": "lxc",
            "name": ct.get("name") or f"CT-{vmid}",
            "current_version": None,  # apt has no single version
            "menu_label": None,        # user upgrades inside the CT
            "menu_script": None,
            "_vmid": vmid,
            "_os_family": os_family,
            # Phase 2 hook: populate `_helper_script_app` here once we
            # learn how to read the community-scripts marker.
        })
    return out


# Detectors registered here. Each returns either a single entry dict
# or a list (for sources that yield multiple items, like OCI). The
# framework normalises both shapes.
_DETECTORS: list[Callable[[], Any]] = [
    _detect_nvidia_xfree86,
    _detect_coral_host,
    _detect_oci_apps,
    _detect_lxc_containers,
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


def _parse_apt_list_upgradable(text: str) -> list[dict]:
    """Parse the output of ``apt list --upgradable`` into structured rows.

    Each upgradable line looks like::

        package/release version arch [upgradable from: oldversion]

    Returns a list of ``{name, current, latest, security}``. Lines that
    can't be parsed are skipped; the header ``Listing...`` is ignored
    because it lacks the ``[upgradable`` marker.

    "security" flag is detected from the release/suite name (e.g.
    ``bookworm-security``, ``jammy-security``). Some derivatives don't
    use that naming and will report security=False even when patches
    are present — acceptable for Phase 1, refined later if needed.
    """
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "[upgradable" not in line or "/" not in line:
            continue
        try:
            head, _, tail = line.partition(" ")
            name, _, release = head.partition("/")
            tail_parts = tail.split()
            if not tail_parts:
                continue
            new_ver = tail_parts[0]
            old_ver = ""
            if "from:" in line:
                old_ver = line.split("from:", 1)[1].strip().rstrip("]").strip()
            release_lower = release.lower()
            is_security = "-security" in release_lower or "/security" in release_lower
            rows.append({
                "name": name,
                "current": old_ver,
                "latest": new_ver,
                "security": is_security,
            })
        except Exception:
            continue
    return rows


def _parse_apk_list_upgradable(text: str) -> list[dict]:
    """Parse the output of ``apk list -u`` into structured rows.

    Lines look like::

        busybox-1.36.1-r29 x86_64 {busybox} (GPL-2.0-only) [upgradable from: busybox-1.36.1-r28]

    apk smashes name + version into the leading token, so reliable
    name/version splitting requires walking from the right (versions
    end in ``-r<num>``). For the badge + notification we only need a
    count and a representative sample, so we keep the parser tolerant
    and surface the raw token as the package "name". Alpine's main
    repos don't expose a separate "security" suite via apk metadata,
    so we mark every row as ``security=False`` — security==0 always.
    """
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "[upgradable" not in line:
            continue
        try:
            first_tok = line.split(" ", 1)[0]
            old = ""
            if "from:" in line:
                old = line.split("from:", 1)[1].strip().rstrip("]").strip()
            rows.append({
                "name": first_tok,
                "current": old,
                "latest": first_tok,
                "security": False,
            })
        except Exception:
            continue
    return rows


def _run_pct_pkg_listing(vmid: str, cmd: str) -> tuple[bool, str, str]:
    """Run a package-listing command inside ``vmid`` via ``pct exec``.
    Returns ``(ok, stdout, error_message)``. Centralises the timeout
    and stderr handling so apt/apk callers stay symmetric.
    """
    try:
        r = subprocess.run(
            [_PCT_BIN, "exec", vmid, "--", "sh", "-c", cmd],
            capture_output=True, text=True,
            timeout=_LXC_EXEC_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"{cmd.split()[0]} listing timed out"
    except (FileNotFoundError, OSError) as e:
        return False, "", str(e)
    if r.returncode != 0:
        return False, "", (r.stderr or "package listing failed").strip()[:200]
    return True, r.stdout, ""


# Refresh thresholds for the package-manager metadata cache. Threshold is
# 24h to match the rest of the check cycle: if a CT was last refreshed
# longer ago than that, we assume `apt list --upgradable` cannot reflect
# the upstream state and proactively refresh once before listing.
_LXC_CACHE_STALE_THRESHOLD_SEC = 24 * 3600
_LXC_CACHE_REFRESH_TIMEOUT_SEC = 60


def _refresh_lxc_pkg_cache_if_stale(vmid: str, family: str) -> dict:
    """Best-effort refresh of the CT's package-manager metadata cache.

    If the local cache is older than ``_LXC_CACHE_STALE_THRESHOLD_SEC``,
    run ``apt-get update`` / ``apk update`` from outside the CT once
    before the upgradable listing. Any failure (no network, broken
    repo, timeout) is swallowed silently — the listing below still
    runs against whatever cache exists, so the detector can never make
    the situation worse than the pre-existing CT state.

    Returns a small diagnostics dict consumed by ``_check_lxc_updates``
    to populate ``_cache_age_seconds`` / ``_cache_refreshed`` on the
    registry entry (visible in the dashboard / managed-installs API).
    """
    if family in ("debian", "ubuntu"):
        # apt's authoritative timestamp is the mtime of pkgcache.bin,
        # which `apt-get update` rewrites on every successful run.
        # We `printf %Y` to get the mtime as a unix timestamp and `||
        # echo 0` so a missing file (fresh CT, broken state) is treated
        # as infinitely old and triggers the refresh.
        cmd_age = "stat -c '%Y' /var/cache/apt/pkgcache.bin 2>/dev/null || echo 0"
        cmd_refresh = "apt-get update -qq"
    elif family == "alpine":
        # apk writes index files under /var/lib/apk/. The
        # `installed` file timestamp moves on package installs, but
        # `apk update` rewrites the cached APKINDEX bundles under
        # /var/cache/apk/*.tar.gz — take the newest mtime there as
        # the authoritative "last update" marker. If the cache dir
        # doesn't exist (apk default with caching disabled), fall
        # back to the index files in /etc/apk/.
        cmd_age = (
            "ls -t /var/cache/apk/*.tar.gz 2>/dev/null | head -1 "
            "| xargs -r stat -c '%Y' 2>/dev/null "
            "|| stat -c '%Y' /etc/apk/world 2>/dev/null || echo 0"
        )
        cmd_refresh = "apk update"
    else:
        return {"refreshed": False, "was_stale": False, "cache_age_seconds": None, "error": None}

    ok, stdout, _ = _run_pct_pkg_listing(vmid, cmd_age)
    if not ok:
        return {"refreshed": False, "was_stale": False, "cache_age_seconds": None, "error": "stat failed"}
    try:
        # Use the last numeric line in case the command emitted stderr
        # noise that snuck into stdout (e.g. some shells route warnings).
        cache_mtime = 0
        for ln in stdout.strip().splitlines():
            try:
                cache_mtime = int(ln.strip())
                break
            except ValueError:
                continue
    except Exception:
        cache_mtime = 0

    now = int(time.time())
    cache_age = (now - cache_mtime) if cache_mtime > 0 else None
    was_stale = cache_age is None or cache_age > _LXC_CACHE_STALE_THRESHOLD_SEC

    if not was_stale:
        return {
            "refreshed": False, "was_stale": False,
            "cache_age_seconds": cache_age, "error": None,
        }

    try:
        r = subprocess.run(
            [_PCT_BIN, "exec", vmid, "--", "sh", "-c", cmd_refresh],
            capture_output=True, text=True,
            timeout=_LXC_CACHE_REFRESH_TIMEOUT_SEC,
        )
        if r.returncode == 0:
            return {
                "refreshed": True, "was_stale": True,
                "cache_age_seconds": cache_age, "error": None,
            }
        return {
            "refreshed": False, "was_stale": True,
            "cache_age_seconds": cache_age,
            "error": (r.stderr or "refresh failed").strip()[:200],
        }
    except subprocess.TimeoutExpired:
        return {
            "refreshed": False, "was_stale": True,
            "cache_age_seconds": cache_age, "error": "refresh timed out",
        }
    except (FileNotFoundError, OSError) as e:
        return {
            "refreshed": False, "was_stale": True,
            "cache_age_seconds": cache_age, "error": str(e),
        }


def _check_lxc_updates(entry: dict) -> dict:
    """Inspect pending package updates inside the LXC and report them.

    Dispatches to the right package-manager parser based on the cached
    ``_os_family``. If the CT's local apt/apk metadata cache is older
    than 24h, runs a best-effort refresh first via
    ``_refresh_lxc_pkg_cache_if_stale`` — without this, CTs that no
    one ever runs ``apt update`` in (long-running appliances) report
    0 pending updates even when upstream has hundreds queued.

    The dedup fingerprint (``latest``) combines count, security count
    and the sorted top package names so a stable set of pending
    updates doesn't re-notify daily, while a meaningfully different
    update set does.
    """
    vmid = entry.get("_vmid")
    family = (entry.get("_os_family") or "").lower()
    if not vmid:
        return {
            "available": False, "latest": None,
            "last_check": _now_iso(), "error": "no vmid in entry",
        }

    refresh_diag = _refresh_lxc_pkg_cache_if_stale(vmid, family)

    if family in ("debian", "ubuntu"):
        ok, stdout, err = _run_pct_pkg_listing(
            vmid, "apt list --upgradable 2>/dev/null"
        )
        packages = _parse_apt_list_upgradable(stdout) if ok else []
    elif family == "alpine":
        ok, stdout, err = _run_pct_pkg_listing(
            vmid, "apk list -u 2>/dev/null"
        )
        packages = _parse_apk_list_upgradable(stdout) if ok else []
    else:
        return {
            "available": False, "latest": None,
            "last_check": _now_iso(),
            "error": f"unsupported family: {family}",
        }

    if not ok:
        return {
            "available": False, "latest": None,
            "last_check": _now_iso(), "error": err,
        }

    count = len(packages)
    sec_count = sum(1 for p in packages if p.get("security"))
    available = count > 0
    latest_fp = None
    if available:
        top_names = ",".join(sorted(p["name"] for p in packages)[:5])
        latest_fp = f"{count}:{sec_count}:{top_names}"

    return {
        "available": available,
        "latest": latest_fp,
        "last_check": _now_iso(),
        "error": None,
        "_count": count,
        "_security_count": sec_count,
        "_packages": packages[:30],  # cap to keep the registry compact
        "_cache_age_seconds": refresh_diag.get("cache_age_seconds"),
        "_cache_refreshed": refresh_diag.get("refreshed"),
        "_cache_refresh_error": refresh_diag.get("error"),
    }


# ── Coral driver checker ──
#
# Two upstreams to track:
#
#   PCIe (gasket-dkms) → feranick/gasket-driver on GitHub. The fork is
#       actively maintained; releases are tagged like "v1.0-22". We pull
#       the latest tag from the GitHub API and compare against the
#       installed gasket-dkms Debian version. Because the Debian version
#       string ("1.0-18") doesn't perfectly match the upstream tag
#       ("v1.0-22"), we normalise both sides to the trailing "-N" build
#       number for the comparison. Strict semver isn't workable here.
#
#   USB (libedgetpu1-std/-max) → Google's apt repo. `apt-cache policy`
#       reports installed + candidate versions in one shot, no internet
#       round-trip required (apt's own cache is the canonical answer).
#
# Cache TTL for the GitHub call is 7 days — feranick's release cadence
# is roughly monthly, matching NVIDIA's pattern. The cache lives in
# memory so AppImage restarts refresh it for free.

_CORAL_GASKET_REPO = "feranick/gasket-driver"
_CORAL_CACHE_TTL = 7 * 86400
_coral_gasket_cache: dict[str, Any] = {"latest_tag": None, "fetched_at": 0}


def _coral_build_number(s: str) -> int:
    """Extract the trailing build number from a Coral version string.

    Handles both upstream tag form (``v1.0-22``, ``1.0-22``) and the
    Debian package form (``1.0-22``, ``1.0-18+pmx1``). Returns 0 if no
    trailing ``-N`` segment exists — that pushes "no build number"
    versions to the lowest rank so any tagged release shows as newer.
    """
    if not s:
        return 0
    m = re.search(r"-(\d+)", s)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except (ValueError, TypeError):
        return 0


def _fetch_gasket_latest_tag(force: bool = False) -> Optional[str]:
    now = time.time()
    if not force and _coral_gasket_cache["latest_tag"] and \
       now - _coral_gasket_cache["fetched_at"] < _CORAL_CACHE_TTL:
        return _coral_gasket_cache["latest_tag"]
    url = f"https://api.github.com/repos/{_CORAL_GASKET_REPO}/tags?per_page=5"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ProxMenux-Monitor/1.0",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            tags = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"[ProxMenux] gasket-driver tag fetch failed: {e}")
        return _coral_gasket_cache.get("latest_tag")
    if not isinstance(tags, list) or not tags:
        return _coral_gasket_cache.get("latest_tag")
    # Pick the tag with the highest trailing build number — feranick's
    # tags are not strictly chronological, occasionally rebuilt.
    best: Optional[str] = None
    best_n = -1
    for t in tags:
        if not isinstance(t, dict):
            continue
        name = t.get("name") or ""
        n = _coral_build_number(name)
        if n > best_n:
            best_n = n
            best = name
    if best:
        _coral_gasket_cache["latest_tag"] = best
        _coral_gasket_cache["fetched_at"] = now
    return best


def _apt_cache_candidate(pkg: str) -> Optional[str]:
    """Return the candidate (newest available) version for ``pkg`` from
    the local apt cache. Caller is responsible for the package existing —
    a missing package returns None silently.
    """
    try:
        r = subprocess.run(
            ["apt-cache", "policy", pkg],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("Candidate:"):
            cand = line.split(":", 1)[1].strip()
            if cand and cand != "(none)":
                return cand
    return None


def _check_coral_host(entry: dict) -> dict:
    variant = entry.get("_coral_variant") or ""
    current = entry.get("current_version") or ""

    if variant == "pcie":
        latest_tag = _fetch_gasket_latest_tag()
        if not latest_tag:
            return {"available": False, "latest": None,
                    "last_check": _now_iso(),
                    "error": "could not fetch gasket-driver tags"}
        cur_n = _coral_build_number(current)
        new_n = _coral_build_number(latest_tag)
        available = new_n > cur_n
        return {
            "available": available,
            "latest": latest_tag if available else None,
            "last_check": _now_iso(),
            "error": None,
            "_coral_variant": "pcie",
        }

    if variant == "usb":
        pkg = entry.get("_coral_pkg") or "libedgetpu1-std"
        candidate = _apt_cache_candidate(pkg)
        if not candidate:
            return {"available": False, "latest": None,
                    "last_check": _now_iso(),
                    "error": f"apt-cache policy returned no candidate for {pkg}"}
        # Use plain string compare via the same build-number heuristic
        # apt uses dpkg version compare upstream, but for the libedgetpu
        # packages a trailing "-N" build number is the only thing that
        # ever moves, so the build-number compare is enough here too.
        # If it ever isn't, dpkg --compare-versions is the right call.
        try:
            cmp = subprocess.run(
                ["dpkg", "--compare-versions", current, "lt", candidate],
                capture_output=True, timeout=3,
            )
            available = cmp.returncode == 0
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            available = candidate != current
        return {
            "available": available,
            "latest": candidate if available else None,
            "last_check": _now_iso(),
            "error": None,
            "_coral_variant": "usb",
            "_coral_pkg": pkg,
        }

    return {"available": False, "latest": None,
            "last_check": _now_iso(),
            "error": f"unknown coral variant: {variant}"}


_CHECKERS: dict[str, Callable[[dict], dict]] = {
    "oci_app": _check_oci_app,
    "nvidia_xfree86": _check_nvidia_xfree86,
    "coral_host": _check_coral_host,
    "lxc": _check_lxc_updates,
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
            # Per-checker extras carried through into the persisted
            # `update_check` blob. Add new keys here when a future
            # checker needs to surface fields beyond available/latest.
            # `_count` + `_security_count` were missing originally, so
            # the LXC checker's counts dropped on the floor and the
            # frontend badge couldn't render.
            for extra_key in ("_packages", "_upgrade_kind", "_kernel",
                              "_kernel_note", "_count", "_security_count",
                              "_coral_variant", "_coral_pkg"):
                if extra_key in result:
                    it["update_check"][extra_key] = result[extra_key]

            if it["update_check"]["available"]:
                updates_available.append(it)

        reg["items"] = items
        reg["last_check_run"] = _now_iso()
        _write_registry(reg)

    return updates_available
