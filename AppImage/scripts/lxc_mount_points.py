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


_SIZE_UNIT_TO_BYTES = {
    "": 1, "B": 1,
    "K": 1024, "KB": 1024, "KIB": 1024,
    "M": 1024 ** 2, "MB": 1024 ** 2, "MIB": 1024 ** 2,
    "G": 1024 ** 3, "GB": 1024 ** 3, "GIB": 1024 ** 3,
    "T": 1024 ** 4, "TB": 1024 ** 4, "TIB": 1024 ** 4,
}


def _parse_pve_size(value: str) -> Optional[int]:
    """Convert PVE-style sizes (``150G``, ``32M``, ``2T``) to bytes.

    PVE stores volume sizes in lxc.conf as ``size=<num><unit>`` where
    unit is a single letter from {K,M,G,T} (powers of 1024). Returns
    None for empty/unparseable input — callers fall through to
    pvesm-based totals.
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([KMGT]?I?B?)$", s)
    if not m:
        return None
    try:
        magnitude = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2) or ""
    multiplier = _SIZE_UNIT_TO_BYTES.get(unit)
    if multiplier is None:
        return None
    return int(magnitude * multiplier)


def _df_via_host_pid(host_pid: str, ct_target: str) -> dict[str, Optional[int]]:
    """``df`` the CT-internal path via ``/proc/<pid>/root`` so we get
    the filesystem as the container sees it, including ZFS dataset
    quotas. Used for ``pve_volume`` mounts whose ``pvesm status``
    numbers reflect the whole storage pool instead of the per-subvol
    quota — without this the UI showed 851 GB total for a 150 GB ZFS
    subvol because pvesm reports the rpool's free space.
    """
    empty = {"total_bytes": None, "used_bytes": None, "available_bytes": None}
    if not host_pid or not ct_target:
        return empty
    full = f"/proc/{host_pid}/root{ct_target}"
    try:
        proc = subprocess.run(
            ["df", "-B1", "--output=size,used,avail", full],
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
        return {
            "total_bytes": int(parts[0]),
            "used_bytes": int(parts[1]),
            "available_bytes": int(parts[2]),
        }
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return empty


def _capacity_for(source: str, classification: dict[str, Any],
                  pve_storages: dict[str, dict[str, Any]],
                  config_options: Optional[dict[str, Any]] = None,
                  host_pid: str = "",
                  target: str = "") -> dict[str, Optional[int]]:
    """Return total/used/available bytes for the *source* of a mount.

    ``pve_volume`` quota handling (Sprint 14.x — Ignacio Seijo 10/05):
      A ``mp6: local-zfs:subvol-310-disk-1,size=150G,...`` line carved
      out a 150 GB subvol from a 1 TB pool. The previous code read
      ``pvesm status local-zfs`` and reported 851 GB total / 19% used —
      reflecting the whole pool, not the subvol. We now prefer, in
      order:
        1) ``df`` of ``/proc/<host_pid>/root/<target>`` when the CT is
           up — gives the correct view-from-inside numbers including
           the quota.
        2) ``size=<N>`` from lxc.conf as the total; usage is unknown
           when the CT isn't running, so the UI shows total only.
        3) Fallback to ``pvesm status`` (pool numbers) when the entry
           has no declared size — that's the legacy behaviour for
           sizeless block volumes (lvm raw, rbd).

    ``pve_storage_bind`` mounts (NFS, CIFS at ``/mnt/pve/...``) keep
    the pvesm-based numbers because the storage IS the source of truth
    for those.

    ``host_bind`` falls back to ``df`` of the host path. None values
    mean the lookup didn't succeed and the UI will render n/a.
    """
    ctype = classification.get("type")
    config_options = config_options or {}
    declared_size_bytes = _parse_pve_size(config_options.get("size"))

    if ctype == "pve_volume":
        # 1) Live numbers from inside the CT (respects quota).
        if host_pid and target:
            live = _df_via_host_pid(host_pid, target)
            if live.get("total_bytes") is not None:
                return live
        # 2) CT down (or df failed): expose declared quota as total.
        if declared_size_bytes is not None:
            return {
                "total_bytes": declared_size_bytes,
                "used_bytes": None,
                "available_bytes": None,
            }
        # 3) No quota declared: legacy pool-level numbers.
        sid = classification.get("origin_storage", "")
        st = pve_storages.get(sid)
        if not st:
            return {"total_bytes": None, "used_bytes": None, "available_bytes": None}
        return {
            "total_bytes": st["total_kib"] * 1024 if st.get("total_kib") is not None else None,
            "used_bytes": st["used_kib"] * 1024 if st.get("used_kib") is not None else None,
            "available_bytes": st["avail_kib"] * 1024 if st.get("avail_kib") is not None else None,
        }

    if ctype == "pve_storage_bind":
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


def _host_source_state(source: str) -> dict[str, Any]:
    """Inspect a host-side bind source to detect 'zombie' binds.

    Reported by Ignacio Seijo (11/05): when the host unmounted
    ``/mnt/nas1_con_backup`` the CT kept reporting it as ``mounted``
    because the bind into the CT's mount namespace was still live —
    the kernel doesn't propagate the host-side umount to the child
    namespace. The CT's view becomes a frozen snapshot of whatever
    was under the path at bind time (usually an empty dir).

    Returns ``{exists, is_mountpoint, error}``. ``exists=False`` means
    the source path is gone entirely (e.g. a USB drive that was
    physically removed). ``is_mountpoint=False`` while ``exists=True``
    is the zombie-bind case the UI flags.

    Only meaningful for absolute host paths. Storage-id sources
    (``local-zfs:subvol-...``) return ``{None, None, None}`` since
    there is no host path to inspect.
    """
    empty = {"exists": None, "is_mountpoint": None, "error": None}
    if not source or not source.startswith("/"):
        return empty
    try:
        st_exists = os.path.exists(source)
    except OSError as e:
        return {"exists": None, "is_mountpoint": None, "error": str(e)}
    if not st_exists:
        return {"exists": False, "is_mountpoint": False, "error": "path missing"}
    try:
        proc = subprocess.run(
            ["mountpoint", "-q", source],
            capture_output=True, text=True, timeout=_STAT_TIMEOUT,
        )
        is_mp = (proc.returncode == 0)
        return {"exists": True, "is_mountpoint": is_mp, "error": None}
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"exists": True, "is_mountpoint": None, "error": str(e)}


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

    # Pre-compute per-entry subprocess work in parallel so a CT with
    # many mountpoints doesn't pay N×(_STAT_TIMEOUT + _STAT_TIMEOUT)
    # serialised cost. The previous serial path tripped Caddy's 3s
    # reverse-proxy timeout (Ignacio Seijo 11/05: "/api/lxc/210/
    # mount-points → 502 (3.00s)") on hosts with 5+ binds. ThreadPool
    # is the right primitive — these are all I/O-bound `df`/`stat`
    # calls hitting independent paths.
    from concurrent.futures import ThreadPoolExecutor

    def _gather_one(entry):
        src = entry.get("source", "")
        tgt = entry.get("target", "")
        classification = _classify(src, pve_storages)
        capacity = _capacity_for(
            src, classification, pve_storages,
            config_options=entry.get("config_options", {}),
            host_pid=host_pid if running else "",
            target=tgt,
        )
        host_src = _host_source_state(src)
        live_target = bool(running and tgt and tgt in rt_by_target)
        health = _stat_via_host(host_pid, tgt) if live_target else None
        return entry, classification, capacity, host_src, live_target, health

    max_workers = max(2, min(8, len(config_entries) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        gathered = list(pool.map(_gather_one, config_entries))

    for entry, cls, cap, host_src, live_target, health in gathered:
        source = entry.get("source", "")
        target = entry.get("target", "")

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
            "host_source_exists": host_src["exists"],
            "host_source_is_mountpoint": host_src["is_mountpoint"],
            **cap,
        }

        # Runtime enrichment when CT is up.
        if live_target:
            rt = rt_by_target[target]
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
        ad_hoc_candidates = [
            rt for rt in rt_mounts
            if rt["rt_target"] not in matched_targets
            and _REMOTE_FS_RE.match(rt["rt_fstype"])
        ]
        # Same parallelisation as the configured-mp loop: stat'ing
        # stale NFS exports serially can dominate the request and
        # push it past the proxy timeout.
        if ad_hoc_candidates:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                healths = list(pool.map(
                    lambda rt: _stat_via_host(host_pid, rt["rt_target"]),
                    ad_hoc_candidates,
                ))
            for rt, health in zip(ad_hoc_candidates, healths):
                ad_hoc.append({
                    "mp_index": "",
                    "source": rt["rt_source"],
                    "target": rt["rt_target"],
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
