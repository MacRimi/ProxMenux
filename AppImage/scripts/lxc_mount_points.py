"""Sprint 13.29: per-LXC mount points enumeration.

The Mount Points tab in the LXC modal calls
``GET /api/lxc/<vmid>/mount-points`` which delegates here. We parse the
container config (``/etc/pve/lxc/<vmid>.conf``) for ``mpX:`` entries —
the rootfs is intentionally excluded (the user asked for *user-added*
mounts, not the container's own disk).

Each ``mpX:`` is classified into one of three types based on the source
syntax:

  * ``pve_volume`` — ``storage_id:vol-id`` (block device assigned from a
    PVE storage; appears as a separate volume, not a path)
  * ``pve_storage_bind`` — absolute path under ``/mnt/pve/<storage>``
    that resolves to a registered PVE storage (typical NFS/CIFS share
    bound into the container)
  * ``host_bind`` — any other absolute path on the host

For each entry we resolve the source-side capacity (so the value is
available even when the LXC is stopped) and, when the LXC is running,
enrich with runtime fields read from ``/proc/<pid>/mounts``: the
filesystem actually mounted on the target, mount options, and a
stale-detection stat with timeout.

Ad-hoc mounts done inside the container (NFS/CIFS mounted from inside
the CT, not via ``mpX:``) are listed alongside the configured ones with
a ``ad_hoc`` type so the user sees the complete picture.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Optional

_LXC_CONF_DIR = Path("/etc/pve/lxc")
_PCT = "/usr/sbin/pct"
_PVESH = "/usr/sbin/pvesh"
_PVESM = "/usr/sbin/pvesm"

_MP_LINE_RE = re.compile(r"^(?P<key>mp\d+):\s*(?P<rest>.+)$")
_REMOTE_FS_RE = re.compile(r"^(nfs|cifs|smb)", re.IGNORECASE)

# Hard timeouts so a stuck `pct exec` or `pvesm status` never freezes
# the request. Same defaults as mount_monitor.
_EXEC_TIMEOUT = int(os.environ.get("PROXMENUX_LXC_EXEC_TIMEOUT", "3"))
_STAT_TIMEOUT = int(os.environ.get("PROXMENUX_MOUNT_STAT_TIMEOUT", "2"))


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def _parse_mp_line(rest: str) -> dict[str, Any]:
    """Parse the value side of an ``mpX:`` line.

    Format: ``<source>,mp=<target>[,opt1=val1,opt2,...]``

    The first comma-separated token is the source — either an absolute
    path (host bind) or ``storage_id:vol-id`` (PVE volume). Subsequent
    tokens are key=value pairs; ``mp=`` carries the target path inside
    the CT, the rest are mount options (acl, backup, ro, replicate,
    quota, shared, size, etc).
    """
    parts = rest.strip().split(",")
    if not parts:
        return {}
    source = parts[0].strip()
    out: dict[str, Any] = {"source": source}
    options: list[str] = []
    for token in parts[1:]:
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            k, v = token.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k == "mp":
                out["target"] = v
            else:
                # Numeric-looking values pass through as strings. Frontend
                # treats them as opaque badges.
                out.setdefault("config_options", {})[k] = v
        else:
            options.append(token)
    if options:
        out.setdefault("config_flags", []).extend(options)
    return out


def _read_lxc_config(vmid: str) -> list[dict[str, Any]]:
    """Return the parsed mpX entries from /etc/pve/lxc/<vmid>.conf.

    Skips comment lines and the rootfs entry (per Sprint 13.29 scope).
    Stops at the first snapshot section header (``[snapshot_name]``)
    because mp lines below that point are config history, not active.
    """
    conf = _LXC_CONF_DIR / f"{vmid}.conf"
    out: list[dict[str, Any]] = []
    try:
        text = conf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            # Snapshot section — stop reading active config.
            break
        if not line or line.startswith("#"):
            continue
        m = _MP_LINE_RE.match(line)
        if not m:
            continue
        parsed = _parse_mp_line(m.group("rest"))
        parsed["mp_index"] = m.group("key")  # mp0, mp1, ...
        out.append(parsed)
    return out


# ---------------------------------------------------------------------------
# Type classification + source resolution
# ---------------------------------------------------------------------------


def _list_pve_storages() -> dict[str, dict[str, Any]]:
    """Map storage_id → ``{type, content, total_kib, used_kib, avail_kib}``
    from ``pvesm status``. One subprocess call covers every classifier
    decision below."""
    out: dict[str, dict[str, Any]] = {}
    try:
        proc = subprocess.run(
            [_PVESM, "status"],
            capture_output=True, text=True, timeout=_EXEC_TIMEOUT,
        )
        if proc.returncode != 0:
            return out
        # Header: Name Type Status Total(KiB) Used Available %
        for line in proc.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) < 6:
                continue
            try:
                out[parts[0]] = {
                    "type": parts[1],
                    "status": parts[2],
                    "total_kib": int(parts[3]),
                    "used_kib": int(parts[4]),
                    "avail_kib": int(parts[5]),
                }
            except ValueError:
                continue
    except (subprocess.TimeoutExpired, OSError):
        pass
    return out


def _classify(source: str, pve_storages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Decide whether ``source`` is a PVE volume, a PVE-storage bind,
    or a plain host-directory bind. Returns the classification dict
    that ends up on the response."""
    # `<storage>:<vol-id>` syntax → PVE volume (block device).
    if ":" in source and not source.startswith("/"):
        sid = source.split(":", 1)[0]
        st = pve_storages.get(sid, {})
        return {
            "type": "pve_volume",
            "origin_storage": sid,
            "origin_storage_type": st.get("type", ""),
            "origin_label": source,
        }

    if source.startswith("/mnt/pve/"):
        rest = source[len("/mnt/pve/"):]
        sid = rest.split("/", 1)[0] if "/" in rest else rest
        if sid in pve_storages:
            st = pve_storages[sid]
            return {
                "type": "pve_storage_bind",
                "origin_storage": sid,
                "origin_storage_type": st.get("type", ""),
                "origin_label": source,
            }

    # Anything else absolute is a plain host bind. Origin label is the
    # path itself; capacity comes from `df` of that path.
    return {
        "type": "host_bind",
        "origin_storage": "",
        "origin_storage_type": "",
        "origin_label": source,
    }


# ---------------------------------------------------------------------------
# Capacity lookup
# ---------------------------------------------------------------------------


def _df_path(path: str) -> dict[str, Optional[int]]:
    """``df`` against a host path with timeout. Same pattern as
    mount_monitor — used here for ``host_bind`` origins."""
    empty = {"total_bytes": None, "used_bytes": None, "available_bytes": None}
    try:
        proc = subprocess.run(
            ["df", "-B1", "--output=size,used,avail", path],
            capture_output=True, text=True, timeout=_STAT_TIMEOUT,
        )
        if proc.returncode != 0:
            return empty
        lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            return empty
        parts = lines[-1].split()
        if len(parts) < 3:
            return empty
        try:
            return {
                "total_bytes": int(parts[0]),
                "used_bytes": int(parts[1]),
                "available_bytes": int(parts[2]),
            }
        except ValueError:
            return empty
    except (subprocess.TimeoutExpired, OSError):
        return empty


def _capacity_for(source: str, classification: dict[str, Any],
                  pve_storages: dict[str, dict[str, Any]]) -> dict[str, Optional[int]]:
    """Return total/used/available bytes for the *source* of a mount.

    ``pve_volume`` and ``pve_storage_bind`` reuse the numbers from
    ``pvesm status`` (already loaded once). ``host_bind`` falls back to
    ``df`` of the host path. None values mean the lookup didn't
    succeed and the UI will render n/a.
    """
    ctype = classification.get("type")
    if ctype in ("pve_volume", "pve_storage_bind"):
        sid = classification.get("origin_storage", "")
        st = pve_storages.get(sid)
        if not st:
            return {"total_bytes": None, "used_bytes": None, "available_bytes": None}
        # pvesm reports KiB; multiply by 1024 to keep the contract with
        # the host-side mount monitor (which returns bytes from `df`).
        return {
            "total_bytes": st["total_kib"] * 1024 if st.get("total_kib") is not None else None,
            "used_bytes": st["used_kib"] * 1024 if st.get("used_kib") is not None else None,
            "available_bytes": st["avail_kib"] * 1024 if st.get("avail_kib") is not None else None,
        }
    if ctype == "host_bind":
        return _df_path(source)
    return {"total_bytes": None, "used_bytes": None, "available_bytes": None}


# ---------------------------------------------------------------------------
# Runtime state (LXC running)
# ---------------------------------------------------------------------------


def _ct_status(vmid: str) -> tuple[bool, str]:
    """Return (running, init_pid). pid is empty string when stopped."""
    try:
        proc = subprocess.run(
            [_PCT, "status", vmid, "--verbose"],
            capture_output=True, text=True, timeout=_EXEC_TIMEOUT,
        )
        if proc.returncode != 0:
            return False, ""
        running = False
        pid = ""
        for line in proc.stdout.splitlines():
            low = line.strip().lower()
            if low.startswith("status:"):
                running = "running" in low
            elif low.startswith("pid:"):
                pid = line.split(":", 1)[1].strip()
        return running, pid
    except (subprocess.TimeoutExpired, OSError):
        return False, ""


def _read_ct_proc_mounts(host_pid: str) -> list[dict[str, Any]]:
    """Read /proc/<pid>/mounts from the host side — works because the
    kernel exposes every namespace's mount table under that path. We
    don't need a second pct exec.
    """
    out: list[dict[str, Any]] = []
    if not host_pid:
        return out
    try:
        with open(f"/proc/{host_pid}/mounts", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 4:
                    continue
                source, target, fstype, options = parts[0], parts[1], parts[2], parts[3]
                out.append({
                    "rt_source": source,
                    "rt_target": target,
                    "rt_fstype": fstype,
                    "rt_options": options,
                    "rt_readonly": "ro" in set(options.split(",")),
                })
    except OSError:
        pass
    return out


def _stat_via_host(host_pid: str, ct_target: str,
                   timeout: int = _STAT_TIMEOUT) -> dict[str, Any]:
    """Stat the container-internal target through /proc/<pid>/root —
    detects stale NFS without another pct exec round-trip."""
    if not host_pid:
        return {"reachable": False, "error": "CT pid unknown"}
    full = f"/proc/{host_pid}/root{ct_target}"
    try:
        result = subprocess.run(
            ["stat", "-c", "%i", full],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            return {"reachable": True, "error": None}
        err = (result.stderr or result.stdout).strip() or "stat returned non-zero"
        return {"reachable": False, "error": err}
    except subprocess.TimeoutExpired:
        return {"reachable": False, "error": f"stat timed out after {timeout}s"}
    except OSError as e:
        return {"reachable": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_lxc_mount_points(vmid: str) -> dict[str, Any]:
    """Top-level entry point used by the Flask route.

    Returns:
      - ``ok`` (bool)
      - ``running`` (bool)
      - ``mount_points`` — list of configured mp0/mp1/... entries
      - ``ad_hoc`` — list of NFS/CIFS/SMB mounts found inside the running
        CT that aren't backed by an mp config line
    """
    # Validate vmid format — the value comes from a URL parameter, so
    # we keep it strict to avoid path-traversal weirdness.
    if not re.match(r"^\d+$", vmid):
        return {"ok": False, "error": "invalid vmid"}

    config_entries = _read_lxc_config(vmid)
    pve_storages = _list_pve_storages()
    running, host_pid = _ct_status(vmid)
    rt_mounts = _read_ct_proc_mounts(host_pid) if running else []

    # Index runtime mounts by their CT-side target path so we can
    # match a config entry to its current realised state in O(1).
    rt_by_target: dict[str, dict[str, Any]] = {m["rt_target"]: m for m in rt_mounts}

    out: list[dict[str, Any]] = []
    matched_targets: set[str] = set()

    for entry in config_entries:
        source = entry.get("source", "")
        target = entry.get("target", "")
        cls = _classify(source, pve_storages)
        cap = _capacity_for(source, cls, pve_storages)

        item: dict[str, Any] = {
            "mp_index": entry.get("mp_index", ""),
            "source": source,
            "target": target,
            "type": cls["type"],
            "origin_storage": cls.get("origin_storage", ""),
            "origin_storage_type": cls.get("origin_storage_type", ""),
            "origin_label": cls.get("origin_label", source),
            "config_options": entry.get("config_options", {}),
            "config_flags": entry.get("config_flags", []),
            **cap,
        }

        # Runtime enrichment when CT is up.
        if running and target and target in rt_by_target:
            rt = rt_by_target[target]
            health = _stat_via_host(host_pid, target)
            item.update({
                "runtime_mounted": True,
                "runtime_source": rt["rt_source"],
                "runtime_fstype": rt["rt_fstype"],
                "runtime_options": rt["rt_options"],
                "runtime_readonly": rt["rt_readonly"],
                "runtime_reachable": health["reachable"],
                "runtime_error": health["error"],
            })
            matched_targets.add(target)
        elif running:
            # CT is running but the configured mount isn't in
            # /proc/<pid>/mounts — divergence. Could be a startup
            # error, missing source, ACL problem, etc.
            item["runtime_mounted"] = False
            item["runtime_error"] = "configured but not mounted"
        else:
            item["runtime_mounted"] = None  # CT down — no runtime info

        out.append(item)

    # Ad-hoc remote mounts inside the running CT (NFS/CIFS/SMB) that
    # don't correspond to any mpX config entry — these are mounts the
    # user did from inside the CT (e.g. `mount -t nfs ...`) and the
    # original Sprint 13.24 issue revolves around catching them.
    ad_hoc: list[dict[str, Any]] = []
    if running:
        for rt in rt_mounts:
            target = rt["rt_target"]
            if target in matched_targets:
                continue
            if not _REMOTE_FS_RE.match(rt["rt_fstype"]):
                continue
            health = _stat_via_host(host_pid, target)
            ad_hoc.append({
                "mp_index": "",
                "source": rt["rt_source"],
                "target": target,
                "type": "ad_hoc",
                "origin_storage": "",
                "origin_storage_type": "",
                "origin_label": rt["rt_source"],
                "config_options": {},
                "config_flags": [],
                "total_bytes": None,
                "used_bytes": None,
                "available_bytes": None,
                "runtime_mounted": True,
                "runtime_source": rt["rt_source"],
                "runtime_fstype": rt["rt_fstype"],
                "runtime_options": rt["rt_options"],
                "runtime_readonly": rt["rt_readonly"],
                "runtime_reachable": health["reachable"],
                "runtime_error": health["error"],
            })

    return {
        "ok": True,
        "vmid": vmid,
        "running": running,
        "mount_points": out,
        "ad_hoc": ad_hoc,
    }
