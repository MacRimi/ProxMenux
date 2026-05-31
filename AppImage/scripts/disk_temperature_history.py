"""Sprint 14: per-disk temperature history.

Mirrors the CPU ``temperature_history`` infrastructure in flask_server,
but keyed by disk name so each physical drive gets its own time series.
Same SQLite DB (``/usr/local/share/proxmenux/monitor.db``), same 30-day
retention, same downsampling buckets the CPU history endpoint uses
(hour=raw / day=5min / week=30min / month=2h).

The sampler is a single function meant to be called once per minute
from flask_server's existing ``_temperature_collector_loop``, so we
don't add another background thread.

Performance — three caches keep the steady-state cost flat on big JBODs:

  * ``_disk_list_cache``    — lsblk + USB filter, refreshed every 5 min.
  * ``_disk_probe_cache``   — remembers which ``smartctl -d <type>``
                              variant works for each disk so we skip
                              the 4-attempt fallback chain.
  * ``_disk_fail_backoff``  — drives that never report a temperature
                              are rate-limited to one re-probe per hour
                              instead of every minute.

The actual smartctl calls run in a ThreadPoolExecutor, so a 24-disk host
spends ~max(per-disk time) per sample instead of sum.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

# Use the same DB the CPU temperature pipeline writes to so we share
# the WAL file and the periodic vacuum that flask_server already runs.
_DB_DIR = "/usr/local/share/proxmenux"
_DB_PATH = os.path.join(_DB_DIR, "monitor.db")

# Retention window for raw samples. Matches CPU history.
_RETENTION_DAYS = 30

# How long ``lsblk`` and each ``smartctl`` call are allowed to run.
# A single hung drive should not block the rest of the batch.
_LSBLK_TIMEOUT = 5
_SMARTCTL_TIMEOUT = 5

# ---------------------------------------------------------------------------
# Caching strategy (Sprint 14 perf pass)
#
# On a 24-disk host the naive sampler can spend several seconds per minute
# just iterating smartctl. Three caches keep the steady-state cost flat:
#
#   _disk_list_cache       — the (lsblk + USB filter) result. Disks don't
#                            appear/disappear between samples, so we only
#                            re-enumerate every _DISK_LIST_TTL seconds.
#
#   _disk_probe_cache      — once we know `/dev/sdX` answers to e.g. the
#                            `-d sat` invocation, we skip the other 3
#                            fallback variants on every subsequent sample.
#
#   _disk_fail_backoff     — drives that consistently report no temperature
#                            (USB-bridges that don't pass SMART through,
#                            virtual SR-IOV NVMe namespaces, etc.) get
#                            backed off for a long window so we don't keep
#                            re-probing them every minute.
#
# All three are guarded by a single lock — contention is irrelevant because
# the sampler runs once a minute, but the cache is also read by request
# handlers that can race with the collector.
# ---------------------------------------------------------------------------

_DISK_LIST_TTL = 300        # 5 minutes
_FAIL_BACKOFF_SECONDS = 3600  # 1 hour
_FAIL_THRESHOLD = 3         # consecutive failures before backoff kicks in
_MAX_WORKERS = 16           # cap concurrency for huge JBODs

_cache_lock = threading.Lock()
_disk_list_cache: Optional[tuple[float, list[str]]] = None
# Maps disk_name -> probe key: 'auto' | 'nvme' | 'ata' | 'sat'.
# Only successful probes get cached.
_disk_probe_cache: dict[str, str] = {}
# Maps disk_name -> consecutive_failures count (cleared on success).
_disk_fail_counts: dict[str, int] = {}
# Maps disk_name -> next-allowed-retry timestamp once backoff trips.
_disk_fail_backoff: dict[str, float] = {}


def _invalidate_disk_list_cache() -> None:
    """Force the next sample to re-run lsblk. Call this from anywhere
    that knows topology has changed (hot-swap, manual rescan, etc.)."""
    global _disk_list_cache
    with _cache_lock:
        _disk_list_cache = None


def reset_disk_caches() -> None:
    """Drop every cached entry. Useful for diagnostics and tests."""
    global _disk_list_cache
    with _cache_lock:
        _disk_list_cache = None
        _disk_probe_cache.clear()
        _disk_fail_counts.clear()
        _disk_fail_backoff.clear()


def get_cache_stats() -> dict[str, Any]:
    """Snapshot of the internal caches — surfaced via flask_server for
    operators to confirm the optimisations are doing what they should."""
    now = time.time()
    with _cache_lock:
        list_cached = _disk_list_cache is not None and _disk_list_cache[0] > now
        list_size = len(_disk_list_cache[1]) if _disk_list_cache else 0
        list_expires_in = max(0, int(_disk_list_cache[0] - now)) if _disk_list_cache else 0
        return {
            "disk_list": {
                "cached": list_cached,
                "size": list_size,
                "expires_in_seconds": list_expires_in,
                "ttl_seconds": _DISK_LIST_TTL,
            },
            "probe_cache": dict(_disk_probe_cache),
            "fail_counts": dict(_disk_fail_counts),
            "backoff": {
                d: max(0, int(retry - now))
                for d, retry in _disk_fail_backoff.items()
                if retry > now
            },
            "max_workers": _MAX_WORKERS,
        }


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_disk_temperature_db() -> bool:
    """Create the table + index. Idempotent — safe to call on every
    AppImage start."""
    try:
        os.makedirs(_DB_DIR, exist_ok=True)
        conn = _db_connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS disk_temperature_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                disk_name TEXT NOT NULL,
                value REAL NOT NULL
            )
            """
        )
        # Composite index — queries always filter by disk_name + timestamp.
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_disk_temp_disk_ts
            ON disk_temperature_history(disk_name, timestamp)
            """
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[ProxMenux] Disk temperature DB init failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Disk enumeration + temperature read
# ---------------------------------------------------------------------------

# Match the modal's filter: USB drives are excluded. The hardware tab
# already hides them in the per-disk list and the user's cluster
# storage doesn't run on USB-attached disks anyway. Including them
# would clutter the history table for thumbdrives plugged in once
# during a recovery session.
def _is_usb_disk(disk_name: str) -> bool:
    """Return True for disks attached over USB. Mirrors the heuristic
    in `get_disk_connection_type` in flask_server — checks the realpath
    of /sys/block/<name> for `usb` in the bus chain."""
    try:
        link = os.path.realpath(f"/sys/block/{disk_name}")
        return "/usb" in link
    except OSError:
        return False


def _enumerate_target_disks() -> list[str]:
    """Run ``lsblk`` + USB filter. The expensive part is the realpath
    walks in ``_is_usb_disk``; both are short-lived but we still amortise
    them via the disk-list cache so they only run every few minutes."""
    out: list[str] = []
    try:
        proc = subprocess.run(
            ["lsblk", "-d", "-n", "-o", "NAME,TYPE"],
            capture_output=True, text=True, timeout=_LSBLK_TIMEOUT,
        )
        if proc.returncode != 0:
            return out
        for line in proc.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            name, dtype = parts[0], parts[1]
            if dtype != "disk":
                continue
            # Skip virtual/loop devices that lsblk still reports as type=disk.
            if name.startswith("loop") or name.startswith("zd"):
                continue
            if _is_usb_disk(name):
                continue
            out.append(name)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return out


def _list_target_disks() -> list[str]:
    """Cached wrapper around ``_enumerate_target_disks``. Topology is
    re-read every ``_DISK_LIST_TTL`` seconds; in between we serve the
    list from memory."""
    global _disk_list_cache
    now = time.time()
    with _cache_lock:
        if _disk_list_cache is not None and _disk_list_cache[0] > now:
            return list(_disk_list_cache[1])
    fresh = _enumerate_target_disks()
    with _cache_lock:
        _disk_list_cache = (now + _DISK_LIST_TTL, list(fresh))
    return fresh


def _smartctl_cmd_for(disk_name: str, probe: str) -> list[str]:
    """Build the smartctl invocation for a given probe key."""
    cmd = ["smartctl", "-A", "-j"]
    if probe != "auto":
        cmd.extend(["-d", probe])
    cmd.append(f"/dev/{disk_name}")
    return cmd


def _try_probe(disk_name: str, probe: str) -> Optional[float]:
    """Run a single smartctl invocation and parse the temperature."""
    try:
        proc = subprocess.run(
            _smartctl_cmd_for(disk_name, probe),
            capture_output=True, text=True, timeout=_SMARTCTL_TIMEOUT,
        )
        # smartctl returns non-zero on warnings (bit 0x40 etc.) even when
        # JSON is fully populated. Don't gate on returncode — parse the
        # body regardless.
        if not proc.stdout:
            return None
        data = json.loads(proc.stdout)
        return _extract_temperature(data)
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        return None


def _read_temperature(disk_name: str) -> Optional[float]:
    """Pull the current temperature from ``smartctl -A -j``.

    Caching strategy:
      * If we've previously found a working probe for this disk we go
        straight to it — no fallback chain.
      * If the probe-cache entry stops working (kernel upgrade swapped
        the auto-detect path, etc.) we fall through to the full chain
        and update the cache with whatever does work.
      * Disks that never report a temperature get rate-limited via the
        backoff table so we don't smartctl them every minute forever.
    """
    now = time.time()

    # Backoff: skip drives that recently failed too many times.
    with _cache_lock:
        retry_at = _disk_fail_backoff.get(disk_name, 0)
        cached_probe = _disk_probe_cache.get(disk_name)
    if retry_at > now:
        return None

    # Fast path: cached probe.
    if cached_probe is not None:
        temp = _try_probe(disk_name, cached_probe)
        if temp is not None and temp > 0:
            with _cache_lock:
                _disk_fail_counts.pop(disk_name, None)
                _disk_fail_backoff.pop(disk_name, None)
            return temp
        # Cached probe stopped working — fall through and re-detect.

    # Slow path: try every probe and remember the first one that works.
    for probe in ("auto", "nvme", "ata", "sat"):
        if probe == cached_probe:
            continue  # already tried above
        temp = _try_probe(disk_name, probe)
        if temp is not None and temp > 0:
            with _cache_lock:
                _disk_probe_cache[disk_name] = probe
                _disk_fail_counts.pop(disk_name, None)
                _disk_fail_backoff.pop(disk_name, None)
            return temp

    # All probes failed. Bump the failure counter and trip the backoff
    # if we've crossed the threshold.
    with _cache_lock:
        n = _disk_fail_counts.get(disk_name, 0) + 1
        _disk_fail_counts[disk_name] = n
        if n >= _FAIL_THRESHOLD:
            _disk_fail_backoff[disk_name] = now + _FAIL_BACKOFF_SECONDS
            # Drop the stale probe cache so the next attempt re-detects.
            _disk_probe_cache.pop(disk_name, None)
    return None


def _extract_temperature(data: dict[str, Any]) -> Optional[float]:
    """Pull the current temperature out of the smartctl JSON payload.

    smartctl exposes temperature in different places depending on disk
    class:

    - SATA/SAS:   ``temperature.current``
    - NVMe:       ``nvme_smart_health_information_log.temperature`` (in K
      on some firmwares, °C on most modern ones — 250 is the sentinel
      for "value too high to be plausible degrees C", treat as Kelvin)
    - SAS legacy: ``ata_smart_attributes.table[id=190 or 194]``
    """
    # Modern path — works for almost every disk class.
    cur = data.get("temperature", {}).get("current")
    if isinstance(cur, (int, float)):
        return float(cur)

    # NVMe-specific path.
    nvme = data.get("nvme_smart_health_information_log", {})
    if isinstance(nvme, dict):
        n_temp = nvme.get("temperature")
        if isinstance(n_temp, (int, float)):
            # Some NVMe firmwares report Kelvin (273.15+). Anything > 200
            # has to be Kelvin since no SSD survives 200 °C.
            return float(n_temp - 273) if n_temp > 200 else float(n_temp)

    # Legacy ATA SMART attribute table fallback.
    ata = data.get("ata_smart_attributes", {})
    if isinstance(ata, dict):
        for row in ata.get("table", []) or []:
            try:
                attr_id = row.get("id")
                if attr_id in (190, 194):
                    raw = row.get("raw", {}).get("value")
                    if isinstance(raw, (int, float)) and 0 < raw < 200:
                        return float(raw)
            except (AttributeError, TypeError):
                continue

    return None


# ---------------------------------------------------------------------------
# Public API — sampler + history query
# ---------------------------------------------------------------------------


def record_all_disk_temperatures() -> int:
    """Sample every non-USB disk and persist its temperature.

    Sampling fans out across a thread pool so a host with N disks pays
    roughly the time of the slowest single ``smartctl`` call instead of
    N × that. ``smartctl`` is mostly waiting on a kernel IOCTL, so
    threading is enough — no need for asyncio. Returns the number of
    rows actually written.
    """
    disks = _list_target_disks()
    if not disks:
        return 0
    now = int(time.time())
    workers = min(len(disks), _MAX_WORKERS)
    rows: list[tuple[int, str, float]] = []
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="disktemp") as pool:
            for disk_name, temp in zip(disks, pool.map(_read_temperature, disks)):
                if temp is None or temp <= 0:
                    continue
                rows.append((now, disk_name, round(temp, 1)))
    except Exception as e:
        # If the pool itself blows up, log and bail — better to skip a
        # sample than to crash the collector loop.
        print(f"[ProxMenux] Disk temperature pool failed: {e}")
        return 0
    if not rows:
        return 0
    try:
        conn = _db_connect()
        conn.executemany(
            "INSERT INTO disk_temperature_history (timestamp, disk_name, value) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()
        return len(rows)
    except Exception as e:
        print(f"[ProxMenux] Disk temperature record failed: {e}")
        return 0


def cleanup_old_disk_temperature_data() -> None:
    """Drop rows older than the retention window. Cheap — runs in
    milliseconds against the indexed timestamp column."""
    try:
        cutoff = int(time.time()) - (_RETENTION_DAYS * 86400)
        conn = _db_connect()
        conn.execute(
            "DELETE FROM disk_temperature_history WHERE timestamp < ?",
            (cutoff,),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# Whitelist regex for disk names to make sure a malicious URL parameter
# can never trip the SQL or land arbitrary text in WHERE clauses. The
# module is otherwise parameterised, so this is belt-and-braces.
_DISK_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def get_disk_temperature_history(disk_name: str, timeframe: str = "hour") -> dict[str, Any]:
    """Return per-disk history with the same shape and downsampling
    as the CPU temperature endpoint.

    Timeframes:
      - hour:  last 1 h, raw points (~60)
      - day:   last 24 h, 5-minute averages (288 points)
      - week:  last 7 days, 30-minute averages (336 points)
      - month: last 30 days, 2-hour averages (360 points)
    """
    empty = {"data": [], "stats": {"min": 0, "max": 0, "avg": 0, "current": 0}}
    if not _DISK_NAME_RE.match(disk_name or ""):
        return empty

    now = int(time.time())
    if timeframe == "day":
        since, interval = now - 86400, 300
    elif timeframe == "week":
        since, interval = now - 7 * 86400, 1800
    elif timeframe == "month":
        since, interval = now - 30 * 86400, 7200
    else:  # hour or unknown
        since, interval = now - 3600, None

    try:
        conn = _db_connect()
        if interval is None:
            cursor = conn.execute(
                """
                SELECT timestamp, value
                FROM disk_temperature_history
                WHERE disk_name = ? AND timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (disk_name, since),
            )
            rows = cursor.fetchall()
            data = [{"timestamp": r[0], "value": r[1]} for r in rows]
        else:
            cursor = conn.execute(
                """
                SELECT (timestamp / ?) * ? as bucket,
                       ROUND(AVG(value), 1) as avg_val,
                       ROUND(MIN(value), 1) as min_val,
                       ROUND(MAX(value), 1) as max_val
                FROM disk_temperature_history
                WHERE disk_name = ? AND timestamp >= ?
                GROUP BY bucket
                ORDER BY bucket ASC
                """,
                (interval, interval, disk_name, since),
            )
            rows = cursor.fetchall()
            data = [
                {"timestamp": r[0], "value": r[1], "min": r[2], "max": r[3]}
                for r in rows
            ]
        conn.close()
    except Exception:
        return empty

    if not data:
        return empty

    values = [d["value"] for d in data]
    if interval is not None and "min" in data[0]:
        actual_min = min(d["min"] for d in data)
        actual_max = max(d["max"] for d in data)
    else:
        actual_min = min(values)
        actual_max = max(values)
    stats = {
        "min": round(actual_min, 1),
        "max": round(actual_max, 1),
        "avg": round(sum(values) / len(values), 1),
        "current": values[-1],
    }
    return {"data": data, "stats": stats}
