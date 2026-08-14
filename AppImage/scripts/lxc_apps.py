# ==========================================================
# ProxMenux — LXC App Watch
# ==========================================================
# Per-CT user-registered application metadata + upstream version
# tracking. Sidecar-per-CT under /etc/proxmenux/apps/<vmid>.json,
# mode 0600. Each sidecar carries a LIST of apps because a single
# CT may host several services (e.g. Frigate on 5000 + go2rtc on
# 1984, or a media server that also runs a metrics agent).
#
# The four ``installed_via`` methods (dpkg / apk / file / binary /
# docker) all use ``pct exec`` argv-style — NEVER through ``sh -c``,
# so a user-typed package name or image tag can't inject a shell.
#
# Public surface (called by flask_server.py):
#   load_sidecar(vmid) -> dict|None                  {vmid, apps[], …}
#   add_app(vmid, config) -> (bool, saved|error)     appends to list
#   update_app(vmid, app_id, config) -> (bool, …)
#   delete_app(vmid, app_id) -> bool
#   delete_all(vmid) -> bool
#   check_app(vmid, app_id, force=False) -> dict|None
#   check_all(vmid, force=False) -> dict|None
#   get_active_apps() -> {str(vmid): [summary, …]}
#   get_suggestions(vmid) -> {name, port_suggestions[], web_path_hint}
# ==========================================================

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Optional

_APPS_DIR = "/etc/proxmenux/apps"
_PCT_BIN = "/usr/sbin/pct"
_PROBE_TIMEOUT_SEC = 15
_GITHUB_TIMEOUT_SEC = 15
# Aligned with the master LXC update cycle in
# notification_events.PollingCollector (UPDATE_CHECK_INTERVAL = 24 h).
# Previously this was 6 h — half a day out of sync with the apt/apk
# scan — so `refresh_all_apps` inside the 24 h collector would still
# hit GitHub for apps whose upstream TTL had elapsed, doubling
# checks. Unifying both to 24 h means one poll per day drives every
# update flavour (OS packages + community-scripts app upstream).
# Manual "Check" button + post-apply hook still pass force=True and
# ignore this TTL, so the user never has to wait for the timer to
# see a fresh result they explicitly asked for.
_UPSTREAM_CACHE_TTL_SEC = 24 * 3600

_VALID_METHODS = ("dpkg", "apk", "file", "binary",
                  "python_dist", "docker_label", "docker_exec",
                  "command", "manual")
_VALID_SOURCES = ("releases", "tags")

# Max args for binary / docker_exec / command — bounded so a malformed
# hint can't blow up pct exec with megabytes of argv.
_MAX_BINARY_ARGS = 8
_MAX_BINARY_ARG_LEN = 128
# `command` method is more permissive on arg count than binary_args
# (users may need slightly longer pipelines through subcommands).
_MAX_COMMAND_ARGV = 12
_MAX_COMMAND_ARGV_LEN = 256
# `manual` method holds a user-typed version string. Kept small so a
# broken paste can't blow up the sidecar or downstream renderers.
_MAX_MANUAL_VERSION_LEN = 64
_MAX_UPDATE_COMMAND_LEN = 4096
_MAX_UPSTREAM_URL_LEN = 512
_MAX_UPSTREAM_JSON_PATH_LEN = 128
_MAX_DOCKER_IMAGE_LEN = 255
_VALID_UPSTREAM_TYPES = ("github", "http_json", "docker_hub")
# Scheduled updates: cron-driven runs of apply_updates.sh. Config
# lives at the sidecar top level (per-CT, not per-app). Cron parser
# below supports the standard 5-field syntax with `*`, exact numbers,
# `*/N` step, and comma lists — that covers every preset the UI
# exposes and the freeform "custom" text field.
_VALID_SCHEDULE_TARGETS = ("os", "app", "both")
_MAX_CRON_FIELD_LEN = 64
# JSONPath (simplified): letters/digits/dots/underscores/hyphens + [N]
# array indices. Rejects wildcards, filters, .. recursion — we don't
# need JSONPath's full grammar and refusing them keeps parsing tight.
_JSON_PATH_RE = re.compile(r"^[A-Za-z0-9._\-\[\]]+$")
# Docker Hub image: `owner/name` or `name` (defaults to library/name).
# Lowercase per Docker's registry rules; underscore/dash/period allowed.
_DOCKER_IMAGE_RE = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)?$"
)

# Curated tracking hints, keyed by the slug we can recognise for the
# CT (typically the community-scripts slug extracted from
# /usr/bin/update, but any stable identifier works). Each hint carries
# the exact installed_via method + package / binary_path / file
# metadata + GitHub repo + tag_regex we've verified in a real
# container, so the App tab can auto-fill every advanced field.
#
# The map is NOT embedded in this module — it lives in
# json/app_tracking_hints.json in the repo and is fetched at runtime
# with a 7-day cache. Adding a new hint (or fixing a broken one) is
# a commit to that JSON — no AppImage rebuild required, every Monitor
# picks the update up on its next refresh. See _fetch_tracking_hints
# for the fetch pipeline (network → disk cache → bundled fallback).
_TRACKING_HINTS_URL = (
    "https://raw.githubusercontent.com/MacRimi/ProxMenux/"
    "refs/heads/main/json/app_tracking_hints.json"
)
_TRACKING_HINTS_DISK = "/var/lib/proxmenux/app_tracking_hints.json"
_TRACKING_HINTS_TTL = 7 * 24 * 3600
_TRACKING_HINTS_HTTP_TIMEOUT = 10
# Bundled fallback: build_appimage.sh copies the JSON next to this
# module so the very first Monitor startup works even offline / before
# the JSON has been merged to main.
_TRACKING_HINTS_BUNDLED = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "app_tracking_hints.json",
)
_tracking_hints_lock = threading.RLock()
_tracking_hints_cache: Optional[dict] = None
_tracking_hints_ts: float = 0.0


def _load_bundled_hints() -> dict:
    try:
        with open(_TRACKING_HINTS_BUNDLED) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _fetch_tracking_hints() -> dict:
    """Return the curated tracking-hint map (slug → hint dict).

    Fetch order: memory cache (fresh) → GitHub raw → on-disk cache
    from a prior fetch → bundled JSON shipped inside the AppImage.
    Never raises — a total failure returns an empty dict so callers
    can just ``.get(slug)``. Same shape and TTL discipline as
    managed_installs._fetch_helpers_cache.
    """
    global _tracking_hints_cache, _tracking_hints_ts
    with _tracking_hints_lock:
        now = time.time()
        if _tracking_hints_cache is not None and (now - _tracking_hints_ts) < _TRACKING_HINTS_TTL:
            return _tracking_hints_cache
        try:
            req = urllib.request.Request(
                _TRACKING_HINTS_URL,
                headers={"User-Agent": "ProxMenux-Monitor"},
            )
            with urllib.request.urlopen(req, timeout=_TRACKING_HINTS_HTTP_TIMEOUT) as r:
                raw = json.loads(r.read().decode("utf-8"))
            hints = raw if isinstance(raw, dict) else {}
            _tracking_hints_cache = hints
            _tracking_hints_ts = now
            try:
                os.makedirs(os.path.dirname(_TRACKING_HINTS_DISK), exist_ok=True)
                tmp = f"{_TRACKING_HINTS_DISK}.tmp.{os.getpid()}"
                with open(tmp, "w") as f:
                    json.dump({"ts": now, "hints": hints}, f)
                os.replace(tmp, _TRACKING_HINTS_DISK)
            except OSError:
                pass
            return hints
        except Exception:
            if _tracking_hints_cache is not None:
                return _tracking_hints_cache
            try:
                with open(_TRACKING_HINTS_DISK) as f:
                    disk = json.load(f)
                _tracking_hints_cache = disk.get("hints") or {}
                _tracking_hints_ts = float(disk.get("ts") or 0)
                return _tracking_hints_cache
            except (OSError, json.JSONDecodeError):
                bundled = _load_bundled_hints()
                _tracking_hints_cache = bundled
                _tracking_hints_ts = now  # avoid re-hammering
                return _tracking_hints_cache

# Cheap guardrails on user input. Not exhaustive — the point is to
# reject obvious footguns (shell metachars) before the value ends up
# as a pct-exec argv entry. Real safety comes from never using sh -c.
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+@:/\-]{0,127}$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9._/\-+@]{1,255}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+$")
_NAME_RE = re.compile(r"^[\w\s._+\-()/]{1,64}$", re.UNICODE)
# Docker container name / id: lowercase letters/digits/underscore/./-
_DOCKER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]{0,63}$")
_DESC_RE = re.compile(r"^[\w\s._+\-()/:,]{0,64}$", re.UNICODE)
_WEB_PATH_RE = re.compile(r"^/[\w\-._~:/?#\[\]@!$&'()*+,;=%]{0,254}$")
# http(s) URL for the app logo — restrictive scheme allow-list prevents
# javascript:/data:/file: sneak-ins through the App card's <img src>.
_LOGO_URL_RE = re.compile(r"^https?://[\w\-._~:/?#\[\]@!$&'()*+,;=%]{1,510}$")
# Community-scripts slug — lowercase letters/digits/dashes/underscores/dots.
# Same shape helpers_cache uses for its own slug field.
_HELPER_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
# OCI label key (e.g. org.opencontainers.image.version) — reverse-DNS
# style dot-separated identifiers.
_OCI_LABEL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9._\-]{0,127}$")
# PEP 503 Python distribution name — flexible enough for `open-webui`,
# `python_dotenv`, `Werkzeug`, etc. Case is preserved but comparison
# is case-insensitive at pip level.
_PYDIST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")

_cache_lock = threading.RLock()


# ── Storage ────────────────────────────────────────────────────────

def _ensure_dir() -> None:
    try:
        os.makedirs(_APPS_DIR, mode=0o700, exist_ok=True)
    except OSError:
        pass


def _sidecar_path(vmid) -> str:
    return f"{_APPS_DIR}/{int(vmid)}.json"


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _read_sidecar(vmid) -> Optional[dict]:
    path = _sidecar_path(vmid)
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return _migrate_legacy(data)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


def _migrate_legacy(data: dict) -> dict:
    """The Phase 2c.0 shape stored a single {config, state}. Convert
    those files on-read into the new {apps: [...]} shape so upgrades
    don't lose the user's registration."""
    if "apps" in data and isinstance(data["apps"], list):
        return data
    if "config" in data and isinstance(data["config"], dict):
        legacy_cfg = data["config"]
        legacy_state = data.get("state") or {}
        # Move the single port + web_path onto the ports[] array
        port = legacy_cfg.pop("port", None)
        web_path = legacy_cfg.pop("web_path", None)
        ports = []
        if port:
            ports.append({
                "port": int(port),
                "description": "",
                "web_path": web_path or "/",
            })
        migrated = {
            "vmid": data.get("vmid"),
            "apps": [{
                "id": data.get("app_id") or _new_app_id(),
                **legacy_cfg,
                "ports": ports,
                "state": legacy_state,
            }],
            "created_at": data.get("created_at") or _now_iso(),
            "updated_at": data.get("updated_at") or _now_iso(),
        }
        return migrated
    return {"vmid": data.get("vmid"), "apps": [],
            "created_at": data.get("created_at") or _now_iso(),
            "updated_at": data.get("updated_at") or _now_iso()}


def _write_sidecar(vmid, data: dict) -> bool:
    _ensure_dir()
    path = _sidecar_path(vmid)
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        return True
    except OSError as e:
        print(f"[ProxMenux] lxc_apps: could not write sidecar {path}: {e}")
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def _new_app_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Validation ─────────────────────────────────────────────────────

def _err(msg: str) -> tuple[bool, str]:
    return False, msg


def _validate_command_argv(raw: Any) -> tuple[bool, Any]:
    """Validate ``command`` method's argv list. Same shape/rules as
    ``_validate_binary_args`` but with looser count/length limits and
    a REQUIRED non-empty first arg (the command to run). Every arg is
    passed argv-style through ``pct exec`` — no shell interpretation,
    never — so the only guardrails are size and control characters.
    Reference: security policy is "the user typed the command; user
    is responsible for what it does". We reject only what would break
    the pct-exec argv wire format.
    """
    if raw is None or raw == "":
        return _err("command_argv is required (non-empty list)")
    if not isinstance(raw, list) or not raw:
        return _err("command_argv must be a non-empty list of strings")
    if len(raw) > _MAX_COMMAND_ARGV:
        return _err(f"command_argv accepts at most {_MAX_COMMAND_ARGV} entries")
    out: list = []
    for i, item in enumerate(raw):
        if not isinstance(item, str) or not item:
            return _err(f"command_argv[{i}] must be a non-empty string")
        if len(item) > _MAX_COMMAND_ARGV_LEN:
            return _err(f"command_argv[{i}] exceeds {_MAX_COMMAND_ARGV_LEN} chars")
        if "\x00" in item or "\n" in item or "\r" in item:
            return _err(f"command_argv[{i}] contains a forbidden control character")
        out.append(item)
    return True, out


def _validate_binary_args(raw: Any) -> tuple[bool, Any]:
    """Return (True, [args…]) or (False, error). Optional field: an
    empty/None input returns ``(True, [])``. Args are passed through
    ``pct exec`` argv-style — no shell interpretation ever — so the
    guardrails are just count/length + reject null bytes and newlines
    which would confuse the pct-exec argv wire format.
    """
    if raw in (None, ""):
        return True, []
    if not isinstance(raw, list):
        return _err("binary_args must be a list of strings")
    if len(raw) > _MAX_BINARY_ARGS:
        return _err(f"binary_args accepts at most {_MAX_BINARY_ARGS} entries")
    out: list = []
    for i, item in enumerate(raw):
        if not isinstance(item, str) or not item:
            return _err(f"binary_args[{i}] must be a non-empty string")
        if len(item) > _MAX_BINARY_ARG_LEN:
            return _err(f"binary_args[{i}] exceeds {_MAX_BINARY_ARG_LEN} chars")
        if "\x00" in item or "\n" in item or "\r" in item:
            return _err(f"binary_args[{i}] contains a forbidden control character")
        out.append(item)
    return True, out


def _validate_ports(ports_in: Any) -> tuple[bool, Any]:
    """Validate ports[] array: each entry {port: int, description: str,
    scheme: "http"|"https", web_path: str}. Empty list = no port
    assignment (fine)."""
    if ports_in in (None, ""):
        return True, []
    if not isinstance(ports_in, list):
        return _err("ports must be a list of {port, description, scheme}")
    out: list = []
    seen_ports: set = set()
    for i, item in enumerate(ports_in):
        if not isinstance(item, dict):
            return _err(f"ports[{i}] must be an object")
        raw_port = item.get("port")
        if raw_port in (None, "", 0):
            return _err(f"ports[{i}].port is required")
        try:
            p = int(raw_port)
        except (TypeError, ValueError):
            return _err(f"ports[{i}].port must be an integer")
        if not (1 <= p <= 65535):
            return _err(f"ports[{i}].port must be 1-65535")
        if p in seen_ports:
            return _err(f"port {p} appears more than once for this app")
        seen_ports.add(p)
        desc = (item.get("description") or "").strip()
        if desc and not _DESC_RE.match(desc):
            return _err(f"ports[{i}].description has invalid characters")
        scheme = (item.get("scheme") or "http").strip().lower()
        if scheme not in ("http", "https"):
            return _err(f"ports[{i}].scheme must be 'http' or 'https'")
        web = (item.get("web_path") or "/").strip()
        if not _WEB_PATH_RE.match(web):
            return _err(f"ports[{i}].web_path must be a valid URL path (max 255 chars)")
        entry = {"port": p, "description": desc, "scheme": scheme, "web_path": web}
        # Per-link logo — optional. Same http(s) allow-list as the
        # app-level logo. Used to render each Web Link with its own
        # icon (e.g. Portainer on 9000, MakeMKV on 5800).
        link_logo = (item.get("logo_url") or "").strip()
        if link_logo:
            if not _LOGO_URL_RE.match(link_logo):
                return _err(f"ports[{i}].logo_url must be an http(s) URL (max 512 chars)")
            entry["logo_url"] = link_logo
        out.append(entry)
    return True, out


def _parse_cron_field(field: str, min_v: int, max_v: int) -> Optional[set]:
    """Expand a single cron field into the set of integers it covers.
    Supports: ``*`` (all), ``N`` (exact), ``*/N`` (step), and
    comma-separated combinations of those. Returns None on any parse
    failure. Ranges (``1-5``) are deliberately unsupported for now —
    every UI preset boils down to *, N, or */N.
    """
    if not isinstance(field, str) or not field or len(field) > _MAX_CRON_FIELD_LEN:
        return None
    field = field.strip()
    out: set = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            return None
        if part == "*":
            out.update(range(min_v, max_v + 1))
            continue
        if part.startswith("*/"):
            try:
                step = int(part[2:])
            except ValueError:
                return None
            if step <= 0:
                return None
            out.update(range(min_v, max_v + 1, step))
            continue
        try:
            n = int(part)
        except ValueError:
            return None
        if n < min_v or n > max_v:
            return None
        out.add(n)
    return out if out else None


def _validate_cron(expr: str) -> Optional[str]:
    """Return None if `expr` is a valid 5-field cron the internal
    scheduler can honour, else a short error string. Mirrors the
    fields expected by `cron_matches` below."""
    if not isinstance(expr, str):
        return "cron must be a string"
    parts = expr.strip().split()
    if len(parts) != 5:
        return "cron must have exactly 5 space-separated fields (minute hour day month weekday)"
    bounds = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
    for p, (lo, hi) in zip(parts, bounds):
        if _parse_cron_field(p, lo, hi) is None:
            return f"cron field '{p}' is not valid"
    return None


def cron_matches(expr: str, dt: datetime.datetime) -> bool:
    """True when the cron expression matches the given datetime at
    minute granularity. Called every 60s by the scheduler thread; a
    False from the parser (invalid expr) matches nothing so a
    malformed schedule silently no-ops instead of firing anything
    unexpected."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return False
    m_set = _parse_cron_field(parts[0], 0, 59)
    h_set = _parse_cron_field(parts[1], 0, 23)
    d_set = _parse_cron_field(parts[2], 1, 31)
    mon_set = _parse_cron_field(parts[3], 1, 12)
    dow_set = _parse_cron_field(parts[4], 0, 6)
    if not (m_set and h_set and d_set and mon_set and dow_set):
        return False
    # Python weekday(): Monday=0..Sunday=6. Cron: Sunday=0..Saturday=6.
    # Convert Python weekday to cron weekday.
    cron_dow = (dt.weekday() + 1) % 7
    return (dt.minute in m_set
            and dt.hour in h_set
            and dt.day in d_set
            and dt.month in mon_set
            and cron_dow in dow_set)


def validate_schedule(payload: Any) -> tuple[bool, Any]:
    """Validate a schedule config block. Returns
    ``(True, normalised_schedule)`` or ``(False, error)``. Called by
    both the endpoint handler and by config migration so the same
    shape check applies everywhere. When `enabled` is false only the
    minimum fields are required; the rest are kept so re-enabling
    doesn't wipe the operator's cron + toggles."""
    if not isinstance(payload, dict):
        return _err("schedule must be a JSON object")
    enabled = bool(payload.get("enabled"))
    cron = (payload.get("cron") or "").strip()
    if enabled and not cron:
        return _err("cron is required when schedule is enabled")
    if cron:
        err = _validate_cron(cron)
        if err:
            return _err(err)
    target = (payload.get("target") or "both").strip().lower()
    if target not in _VALID_SCHEDULE_TARGETS:
        return _err(f"target must be one of: {', '.join(_VALID_SCHEDULE_TARGETS)}")
    backup = bool(payload.get("backup"))
    restart = bool(payload.get("restart"))
    backup_storage = (payload.get("backup_storage") or "").strip()
    if backup and not backup_storage:
        # Not fatal — the runner falls back to the first vzdump-capable
        # storage the frontend passes at run time. Persist as empty so
        # the UI knows the user relied on the default.
        backup_storage = ""
    if backup_storage and (len(backup_storage) > 64 or not re.match(r"^[A-Za-z0-9._\-]+$", backup_storage)):
        return _err("backup_storage must be a valid PVE storage name")
    out: dict = {
        "enabled": enabled,
        "cron": cron,
        "target": target,
        "backup": backup,
        "backup_storage": backup_storage,
        "restart": restart,
    }
    # Preserve `last_run_at` / `last_run_status` when the caller sent
    # them (typical when the scheduler writes back after firing);
    # otherwise leave the field unset so persisted values survive.
    for k in ("last_run_at", "last_run_status", "last_run_target"):
        v = payload.get(k)
        if v is not None:
            out[k] = v
    return True, out


def validate_config(payload: dict) -> tuple[bool, Any]:
    """Return (True, normalised_config_without_state_id) or
    (False, error). Rejects anything that would give shell-injection
    at check-time. Only the five fixed installed_via methods are
    accepted; each has its own required field set."""
    if not isinstance(payload, dict):
        return _err("payload must be a JSON object")

    name = (payload.get("name") or "").strip()
    if not name or not _NAME_RE.match(name):
        return _err("name is required and must be 1-64 chars of letters/digits/spaces/._+-()/")

    # `installed_via` is OPTIONAL now. When empty, the app is
    # "register-only" — we produce clickable web links but never try
    # to detect a version, never fetch upstream, never emit warnings.
    # This is the default for casual users who just want a link, and
    # for docker apps (whose version lifecycle Docker owns).
    method = (payload.get("installed_via") or "").strip().lower()
    if method and method not in _VALID_METHODS:
        return _err(f"installed_via must be one of: {', '.join(_VALID_METHODS)} or empty")

    conf: dict = {"name": name}
    if method:
        conf["installed_via"] = method

    if method in ("dpkg", "apk"):
        pkg = (payload.get("package") or "").strip()
        if not pkg or not _PACKAGE_RE.match(pkg):
            return _err("package is required (letters/digits/._+@:/ up to 127 chars)")
        conf["package"] = pkg
    elif method == "file":
        fp = (payload.get("file_path") or "").strip()
        if not fp or not _PATH_RE.match(fp):
            return _err("file_path is required and must be an absolute path")
        fr = payload.get("file_regex") or ""
        if not isinstance(fr, str) or not fr.strip():
            return _err("file_regex is required")
        try:
            re.compile(fr)
        except re.error as e:
            return _err(f"file_regex is not a valid regex: {e}")
        conf["file_path"] = fp
        conf["file_regex"] = fr.strip()
    elif method == "binary":
        bp = (payload.get("binary_path") or "").strip()
        if not bp or not _PATH_RE.match(bp):
            return _err("binary_path is required and must be an absolute path")
        conf["binary_path"] = bp
        ok, args = _validate_binary_args(payload.get("binary_args"))
        if not ok:
            return _err(args)
        if args:
            conf["binary_args"] = args
    elif method == "python_dist":
        # importlib.metadata.version(<distribution>) run through the
        # configured venv's python interpreter. Zero shell, argv-only.
        pp = (payload.get("python_path") or "").strip()
        if not pp or not _PATH_RE.match(pp):
            return _err("python_path is required and must be an absolute path")
        dist = (payload.get("distribution") or "").strip()
        if not dist or not _PYDIST_RE.match(dist):
            return _err("distribution is required (PEP 503 name)")
        conf["python_path"] = pp
        conf["distribution"] = dist
    elif method == "docker_label":
        # docker inspect --format '{{index .Config.Labels "<label>"}}' <container>
        cn = (payload.get("container_name") or "").strip()
        if not cn or not _DOCKER_NAME_RE.match(cn):
            return _err("container_name is required (docker naming rules)")
        lbl = (payload.get("label") or "").strip()
        if not lbl or not _OCI_LABEL_RE.match(lbl):
            return _err("label is required (OCI label naming rules)")
        conf["container_name"] = cn
        conf["label"] = lbl
    elif method == "docker_exec":
        # docker exec <container> <binary> [args...]
        cn = (payload.get("container_name") or "").strip()
        if not cn or not _DOCKER_NAME_RE.match(cn):
            return _err("container_name is required (docker naming rules)")
        bp = (payload.get("binary_path") or "").strip()
        # docker_exec binary may be relative (docker resolves PATH inside
        # the container) — validate as either an absolute path OR a bare
        # binary name (letters/digits/dash/underscore/dot).
        if not bp or not (_PATH_RE.match(bp) or re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", bp)):
            return _err("binary_path is required (absolute path or bare command)")
        conf["container_name"] = cn
        conf["binary_path"] = bp
        ok, args = _validate_binary_args(payload.get("binary_args"))
        if not ok:
            return _err(args)
        if args:
            conf["binary_args"] = args
    elif method == "command":
        # Advanced-user escape hatch: an arbitrary argv passed to
        # `pct exec` inside the CT. User-supplied and user-responsible;
        # we validate only size/control-char sanity (see
        # _validate_command_argv). Never sh -c, never string; always
        # argv, always as-typed.
        ok, argv = _validate_command_argv(payload.get("command_argv"))
        if not ok:
            return _err(argv)
        conf["command_argv"] = argv
    elif method == "manual":
        # No probing ever. The user tells us the installed version, we
        # store it verbatim. Version-check flow still fires against
        # `repo` if set — the "update available" notification depends
        # only on comparing this string to the upstream tag. After
        # updating the app, the user edits and updates the string.
        v = (payload.get("installed_version") or "").strip()
        if not v:
            return _err("installed_version is required for the manual method")
        if len(v) > _MAX_MANUAL_VERSION_LEN:
            return _err(f"installed_version exceeds {_MAX_MANUAL_VERSION_LEN} chars")
        # Reject control chars but ALLOW almost anything else — user
        # may have version strings like `1.2.3-beta.4+build.5`.
        if any(ch in v for ch in "\x00\n\r"):
            return _err("installed_version contains a forbidden control character")
        conf["installed_version"] = v

    # Optional installed_regex — separate from tag_regex for cases where
    # local output format differs from the upstream tag (Squid reports
    # "7.6-1" via dpkg while upstream tag is "SQUID_7_6"). Falls back to
    # tag_regex during detection when unset.
    if method:
        ir = (payload.get("installed_regex") or "").strip()
        if ir:
            try:
                re.compile(ir)
            except re.error as e:
                return _err(f"installed_regex is not a valid regex: {e}")
            conf["installed_regex"] = ir

    # Upstream source — optional, and only meaningful when we have a
    # detection method (otherwise there's nothing to compare against).
    # Three types supported (`upstream_type` discriminator):
    #   github     — repo + github_source + tag_regex (original path,
    #                default when `repo` is set and upstream_type is
    #                omitted, so pre-existing sidecars keep working)
    #   http_json  — GET url, walk upstream_json_path in the JSON reply,
    #                optionally squeeze the raw value through tag_regex
    #   docker_hub — list tags for docker_image, filter by tag_regex,
    #                pick the semver-highest match
    if method:
        upstream_type = (payload.get("upstream_type") or "").strip().lower()
        # Backward-compat: legacy sidecars set `repo` without
        # `upstream_type`; treat that as github implicitly.
        if not upstream_type and (payload.get("repo") or "").strip():
            upstream_type = "github"

        if upstream_type:
            if upstream_type not in _VALID_UPSTREAM_TYPES:
                return _err(f"upstream_type must be one of: {', '.join(_VALID_UPSTREAM_TYPES)}")

            # tag_regex is shared across all three types but has
            # different roles: mandatory for github (tag → version),
            # optional post-processing for http_json (extract a version
            # substring from the raw endpoint value), and mandatory
            # filter for docker_hub (pick which tags qualify).
            tag_regex_raw = (payload.get("tag_regex") or "").strip()
            default_tag_regex = r"v?(\d+\.\d+\.\d+)"
            tag_regex = tag_regex_raw or default_tag_regex
            try:
                re.compile(tag_regex)
            except re.error as e:
                return _err(f"tag_regex is not a valid regex: {e}")

            if upstream_type == "github":
                repo = (payload.get("repo") or "").strip()
                if not repo:
                    return _err("repo is required for upstream_type=github")
                if not _REPO_RE.match(repo):
                    return _err("repo must be 'owner/name'")
                source = (payload.get("github_source") or "releases").strip().lower()
                if source not in _VALID_SOURCES:
                    return _err(f"github_source must be one of: {', '.join(_VALID_SOURCES)}")
                conf["upstream_type"] = "github"
                conf["repo"] = repo
                conf["github_source"] = source
                conf["tag_regex"] = tag_regex

            elif upstream_type == "http_json":
                url = (payload.get("upstream_url") or "").strip()
                if not url:
                    return _err("upstream_url is required for upstream_type=http_json")
                if not url.startswith(("http://", "https://")):
                    return _err("upstream_url must be an http(s) URL")
                if len(url) > _MAX_UPSTREAM_URL_LEN:
                    return _err(f"upstream_url exceeds {_MAX_UPSTREAM_URL_LEN} chars")
                path = (payload.get("upstream_json_path") or "").strip()
                if not path:
                    return _err("upstream_json_path is required for upstream_type=http_json")
                if len(path) > _MAX_UPSTREAM_JSON_PATH_LEN:
                    return _err(f"upstream_json_path exceeds {_MAX_UPSTREAM_JSON_PATH_LEN} chars")
                if not _JSON_PATH_RE.match(path):
                    return _err("upstream_json_path uses forbidden characters")
                conf["upstream_type"] = "http_json"
                conf["upstream_url"] = url
                conf["upstream_json_path"] = path
                # tag_regex is optional post-processing here; only
                # persist when the user explicitly set one so the
                # default isn't spuriously applied to raw JSON values
                # that already look like clean versions.
                if tag_regex_raw:
                    conf["tag_regex"] = tag_regex

            elif upstream_type == "docker_hub":
                image = (payload.get("docker_image") or "").strip().lower()
                if not image:
                    return _err("docker_image is required for upstream_type=docker_hub")
                if len(image) > _MAX_DOCKER_IMAGE_LEN:
                    return _err(f"docker_image exceeds {_MAX_DOCKER_IMAGE_LEN} chars")
                if not _DOCKER_IMAGE_RE.match(image):
                    return _err("docker_image must match Docker Hub naming (owner/name or name)")
                conf["upstream_type"] = "docker_hub"
                conf["docker_image"] = image
                if tag_regex_raw:
                    conf["tag_regex"] = tag_regex

    # Ports (list of {port, description, web_path})
    ok, ports = _validate_ports(payload.get("ports"))
    if not ok:
        return _err(ports)
    conf["ports"] = ports

    # Optional health path (single, applied to the first port if any)
    health = (payload.get("health_path") or "").strip()
    if health:
        if not _WEB_PATH_RE.match(health):
            return _err("health_path must be a valid URL path (max 255 chars)")
        conf["health_path"] = health

    # Optional logo URL — either the auto-fill from the catalog/hint
    # or a user-provided URL for a custom app. Restricted to http(s)
    # so the browser can't be tricked into loading javascript: / data:
    # payloads through the App card's <img src>.
    logo = (payload.get("logo_url") or "").strip()
    if logo:
        if not _LOGO_URL_RE.match(logo):
            return _err("logo_url must be an http(s) URL (max 512 chars)")
        conf["logo_url"] = logo

    # Optional helper_slug — set by the frontend when the user picks
    # an auto-detected app (primary or extra). Persisted so we can
    # filter the "also detected" chip list against apps already
    # registered on this CT.
    hs = (payload.get("helper_slug") or "").strip().lower()
    if hs:
        if not _HELPER_SLUG_RE.match(hs):
            return _err("helper_slug must be a lowercase slug (letters/digits/._-)")
        conf["helper_slug"] = hs

    # Optional user-defined update command. Freeform bash that runs
    # under `pct exec vmid -- sh -c "$command"` when the user hits
    # "Apply {app} update" from the Updates tab. This is deliberately
    # NOT sanitised beyond size/null-byte checks — the threat model
    # is "same as if the user typed it via pct exec themselves". The
    # user owns the command; ProxMenux only executes it.
    uc = payload.get("update_command")
    if uc is not None:
        if not isinstance(uc, str):
            return _err("update_command must be a string")
        uc = uc.strip()
        if uc:
            if len(uc) > _MAX_UPDATE_COMMAND_LEN:
                return _err(f"update_command exceeds {_MAX_UPDATE_COMMAND_LEN} chars")
            if "\x00" in uc:
                return _err("update_command contains a null byte")
            conf["update_command"] = uc

    # Optional per-app dismiss flag for the "no update method defined"
    # notice shown in the Updates tab. Only affects the notice card;
    # the App tab keeps its purple update signal regardless.
    hn = payload.get("hide_no_updater_notice")
    if hn is not None:
        conf["hide_no_updater_notice"] = bool(hn)

    # Optional per-app switch for `app_update_available` notifications.
    # Default is True (opt-out). Set to False from the App tab when the
    # user knows an app can't be updated on their box (compat, forked
    # setup, etc.) and wants to keep the "you have updates" badge but
    # silence the outbound notification for THIS app only, without
    # touching the global toggle.
    ne = payload.get("notifications_enabled")
    if ne is not None:
        conf["notifications_enabled"] = bool(ne)

    return True, conf


# ── Version detection: installed side ──────────────────────────────

def _pct_exec(vmid, argv: list[str], timeout: int = _PROBE_TIMEOUT_SEC) -> tuple[int, str, str]:
    """Wrapper around ``pct exec`` argv-style — NEVER through sh -c."""
    cmd = [_PCT_BIN, "exec", str(vmid), "--"] + argv
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except (FileNotFoundError, OSError) as e:
        return 127, "", str(e)


def _extract_version(text: str, pattern: str) -> Optional[str]:
    """Extract a version string from ``text`` using ``pattern``.

    - Zero capture groups → return the full match
    - One capture group → return that group's text (typical case)
    - Multiple capture groups → join with "." — handy for formats like
      Paperless-ngx `__version__ = (2, 9, 0)` where each digit lives
      in its own group. Empty/None groups are dropped from the join.
    """
    try:
        m = re.search(pattern, text)
    except re.error:
        return None
    if not m:
        return None
    groups = [g for g in m.groups() if g]
    if len(groups) > 1:
        return ".".join(groups)
    if len(groups) == 1:
        return groups[0]
    return m.group(0)


def detect_installed_version(vmid, config: dict) -> tuple[Optional[str], Optional[str]]:
    """Run the configured install-check inside the CT and return
    (version, error). Version None + error set on failure.
    Version None + error None means "check ran but produced no
    parseable version"."""
    method = config.get("installed_via")
    # installed_regex is applied to the LOCAL command output; tag_regex
    # is for the upstream tag string. When installed_regex isn't set,
    # tag_regex is reused (backward-compat with older hints).
    pattern = config.get("installed_regex") or config.get("tag_regex") or r"(\d+[.\d]+)"

    if method == "dpkg":
        rc, out, err = _pct_exec(vmid, ["dpkg-query", "-W", "-f=${Version}", config["package"]])
        if rc != 0:
            low = (err or out).lower()
            if "no packages found" in low or "not installed" in low:
                return None, f"{config['package']} is not installed via dpkg"
            return None, (err or out).strip()[:200] or "dpkg-query failed"
        return _extract_version(out, pattern), None

    if method == "apk":
        rc, out, err = _pct_exec(vmid, ["apk", "info", "-v", config["package"]])
        if rc != 0:
            return None, (err or out).strip()[:200] or "apk info failed"
        return _extract_version(out, pattern), None

    if method == "file":
        rc, out, err = _pct_exec(vmid, ["cat", config["file_path"]])
        if rc != 0:
            return None, (err or "").strip()[:200] or f"could not read {config['file_path']}"
        return _extract_version(out, config["file_regex"]), None

    if method == "binary":
        # binary_args defaults to ["--version"] but can be overridden
        # for tools like `grafana-cli`, `myapp version`, etc.
        args = config.get("binary_args") or ["--version"]
        rc, out, err = _pct_exec(vmid, [config["binary_path"], *args])
        combined = out + "\n" + err
        v = _extract_version(combined, pattern)
        if v:
            return v, None
        if rc != 0:
            return None, (err or out).strip()[:200] or "binary invocation failed"
        return None, "no version matched in binary output"

    if method == "python_dist":
        # Runs the venv's python: `python -c 'import importlib.metadata as m;
        # print(m.version("<dist>"))'`. distribution name is a literal
        # arg, no format string, no eval — safe from injection because
        # pct exec never invokes a shell.
        dist = config["distribution"]
        snippet = (
            "import importlib.metadata as m, sys\n"
            f"try:\n    sys.stdout.write(m.version({dist!r}))\n"
            "except Exception as e:\n    sys.stderr.write(str(e))\n    sys.exit(2)\n"
        )
        rc, out, err = _pct_exec(vmid, [config["python_path"], "-c", snippet])
        if rc != 0:
            return None, (err or out).strip()[:200] or "python -c importlib.metadata failed"
        return _extract_version(out, pattern), None

    if method == "docker_label":
        # docker inspect --format '{{index .Config.Labels "<label>"}}' <container>
        fmt = '{{index .Config.Labels "' + config["label"] + '"}}'
        rc, out, err = _pct_exec(vmid, ["docker", "inspect", "--format", fmt, config["container_name"]])
        if rc != 0:
            return None, (err or out).strip()[:200] or "docker inspect failed"
        text = (out or "").strip()
        if not text or text == "<no value>":
            return None, f"container has no {config['label']!r} label"
        # Reject mutable tags disguised as versions.
        if text.lower() in ("latest", "stable", "main", "master", "edge"):
            return None, f"docker label reports {text!r} (mutable tag, not a version)"
        return _extract_version(text, pattern), None

    if method == "docker_exec":
        # docker exec <container> <binary> [args…]
        args = config.get("binary_args") or ["--version"]
        rc, out, err = _pct_exec(vmid, ["docker", "exec", config["container_name"],
                                        config["binary_path"], *args])
        combined = out + "\n" + err
        v = _extract_version(combined, pattern)
        if v:
            return v, None
        if rc != 0:
            return None, (err or out).strip()[:200] or "docker exec failed"
        return None, "no version matched in docker exec output"

    if method == "command":
        # User-supplied argv, run through pct exec. Zero shell, so
        # metachar-injection isn't a class of attack — the user gets
        # exactly the argv they typed. installed_regex extracts the
        # version from combined stdout + stderr; falls back to
        # tag_regex.
        argv = list(config.get("command_argv") or [])
        if not argv:
            return None, "command_argv is empty"
        rc, out, err = _pct_exec(vmid, argv)
        combined = out + "\n" + err
        v = _extract_version(combined, pattern)
        if v:
            return v, None
        if rc != 0:
            return None, (err or out).strip()[:200] or "command failed"
        return None, "no version matched in command output"

    if method == "manual":
        # User-typed installed version, no probe. Returned as-is.
        v = (config.get("installed_version") or "").strip()
        return (v or None), None

    # No method configured → register-only, no detection, no errors.
    if not method:
        return None, None

    return None, f"unsupported method: {method}"


# ── Version detection: upstream side ───────────────────────────────

def _github_pat() -> Optional[str]:
    try:
        from notification_manager import notification_manager
        pat = notification_manager._config.get("github_pat") if notification_manager._config else None
        if not pat:
            return None
        try:
            from notification_manager import decrypt_sensitive_value
            if isinstance(pat, str) and pat.startswith("encrypted:"):
                return decrypt_sensitive_value(pat)
        except Exception:
            pass
        return pat if isinstance(pat, str) else None
    except Exception:
        return None


def fetch_latest_upstream(config: dict) -> tuple[Optional[str], Optional[str]]:
    """Dispatch to the appropriate upstream fetcher based on
    ``upstream_type``. Falls back to github for legacy sidecars that
    only set ``repo``. Returns (version, error) — version None + error
    None means the app has no upstream configured (skip the check)."""
    upstream_type = config.get("upstream_type")
    # Legacy sidecars: repo set, upstream_type not.
    if not upstream_type and config.get("repo"):
        upstream_type = "github"
    if not upstream_type:
        return None, None
    if upstream_type == "github":
        return _fetch_github_latest(config)
    if upstream_type == "http_json":
        return _fetch_http_json_latest(config)
    if upstream_type == "docker_hub":
        return _fetch_docker_hub_latest(config)
    return None, f"unknown upstream_type: {upstream_type}"


def _fetch_github_latest(config: dict) -> tuple[Optional[str], Optional[str]]:
    repo = config.get("repo")
    if not repo:
        return None, None
    source = config.get("github_source") or "releases"
    if source == "releases":
        url = f"https://api.github.com/repos/{urllib.parse.quote(repo, safe='/')}/releases/latest"
    else:
        url = f"https://api.github.com/repos/{urllib.parse.quote(repo, safe='/')}/tags?per_page=30"

    headers = {
        "User-Agent": "ProxMenux-Monitor",
        "Accept": "application/vnd.github+json",
    }
    pat = _github_pat()
    if pat:
        headers["Authorization"] = f"Bearer {pat}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_GITHUB_TIMEOUT_SEC) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, f"{repo}: not found"
        if e.code == 403:
            remaining = e.headers.get("X-RateLimit-Remaining", "1")
            if remaining == "0":
                return None, "github rate limited — configure a PAT in Settings"
            return None, "github rejected the request (403)"
        return None, f"github error {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"network error: {e}"

    pattern = config.get("tag_regex") or r"v?(\d+\.\d+\.\d+)"
    tag = None
    if source == "releases" and isinstance(payload, dict):
        tag = payload.get("tag_name") or payload.get("name")
    elif source == "tags" and isinstance(payload, list):
        for entry in payload:
            candidate = entry.get("name") if isinstance(entry, dict) else None
            if candidate:
                v = _extract_version(candidate, pattern)
                if v:
                    tag = candidate
                    break

    if not tag:
        return None, "no tag / release name in response"
    v = _extract_version(tag, pattern)
    if not v:
        return None, f"tag_regex did not match '{tag}'"
    return v, None


def _resolve_json_path(data: Any, path: str) -> Any:
    """Simple JSONPath walker — supports dotted keys and ``[N]`` array
    indices, e.g. ``computer.Linux.version`` or ``results[0].name``.
    Returns None if any step doesn't resolve. Keeps parsing tight (no
    wildcards, filters, or recursive descent) so the field is safe to
    accept from users."""
    if not path:
        return None
    # Split into path tokens: bare identifiers OR bracketed indices.
    parts = re.findall(r"[^.\[\]]+|\[-?\d+\]", path)
    if not parts:
        return None
    node = data
    for p in parts:
        if p.startswith("["):
            try:
                idx = int(p[1:-1])
            except ValueError:
                return None
            if not isinstance(node, list):
                return None
            try:
                node = node[idx]
            except IndexError:
                return None
        else:
            if not isinstance(node, dict):
                return None
            if p not in node:
                return None
            node = node[p]
    return node


def _fetch_http_json_latest(config: dict) -> tuple[Optional[str], Optional[str]]:
    url = config.get("upstream_url")
    json_path = config.get("upstream_json_path")
    if not url or not json_path:
        return None, None
    req = urllib.request.Request(url, headers={"User-Agent": "ProxMenux-Monitor", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_GITHUB_TIMEOUT_SEC) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return None, f"http error {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"network error: {e}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON response: {e}"
    val = _resolve_json_path(payload, json_path)
    if val is None:
        return None, f"json_path '{json_path}' did not resolve"
    val_str = str(val).strip()
    if not val_str:
        return None, "empty value at json_path"
    # Optional tag_regex extraction — only when the user set one. When
    # unset we trust the endpoint's value as-is (many vendor APIs
    # already publish a clean semver at the target path).
    pattern = config.get("tag_regex")
    if pattern:
        extracted = _extract_version(val_str, pattern)
        if not extracted:
            return None, f"tag_regex did not match '{val_str}'"
        return extracted, None
    return val_str, None


def _fetch_docker_hub_latest(config: dict) -> tuple[Optional[str], Optional[str]]:
    image = config.get("docker_image")
    if not image:
        return None, None
    if "/" not in image:
        image = f"library/{image}"
    url = (
        f"https://hub.docker.com/v2/repositories/{urllib.parse.quote(image, safe='/')}"
        "/tags/?page_size=50&ordering=last_updated"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "ProxMenux-Monitor", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_GITHUB_TIMEOUT_SEC) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, f"docker image '{image}' not found"
        return None, f"docker hub error {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"network error: {e}"
    except json.JSONDecodeError as e:
        return None, f"invalid docker hub JSON: {e}"

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return None, "no tags returned by docker hub"

    tag_names = [t.get("name") for t in results if isinstance(t, dict) and t.get("name")]
    # Optional filter by user tag_regex; if omitted, apply a default
    # that keeps semver-shaped tags and drops moving/floating ones.
    pattern = config.get("tag_regex")
    if pattern:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return None, f"tag_regex is not a valid regex: {e}"
        tag_names = [t for t in tag_names if rx.search(t)]
    else:
        # Drop obvious moving tags — user always overrides with an
        # explicit tag_regex.
        moving = {"latest", "main", "master", "edge", "stable",
                  "nightly", "develop", "dev", "rolling"}
        tag_names = [t for t in tag_names if t.lower() not in moving]
    if not tag_names:
        return None, "no tags matched (docker_hub)"

    # Semver-desc sort: parse each tag's three-part version tuple; tags
    # without a parseable semver land last so a numeric release always
    # wins over a random label.
    def _semver_key(t: str) -> tuple:
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", t)
        if m:
            return (1, int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return (0, 0, 0, 0)
    tag_names.sort(key=_semver_key, reverse=True)
    winner = tag_names[0]
    # If user set a tag_regex with capture groups, run the extraction to
    # normalise "v1.2.3" → "1.2.3" and similar.
    if pattern:
        extracted = _extract_version(winner, pattern)
        if extracted:
            return extracted, None
    return winner, None


# ── Version comparison ────────────────────────────────────────────

def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def compare(installed: Optional[str], latest: Optional[str]) -> Optional[bool]:
    if not installed or not latest:
        return None
    ti, tl = _version_tuple(installed), _version_tuple(latest)
    if not ti or not tl:
        return installed != latest
    return tl > ti


# ── Public API ────────────────────────────────────────────────────

def _empty_state() -> dict:
    return {
        "installed_version": None,
        "latest_version": None,
        "update_available": None,
        "error": None,
        "checked_at": None,
    }


def load_sidecar(vmid) -> Optional[dict]:
    return _read_sidecar(vmid)


def set_dismissed_slug(vmid, slug: str, dismissed: bool) -> tuple[bool, Any]:
    """Add/remove a slug from the per-CT ``dismissed_slugs`` list.

    Dismissed slugs are auto-detected apps the user chose to hide from
    the "Detected on this container" chip list. Persisted so the
    detection doesn't come back on every page reload. Registering an
    app for the same slug afterwards implicitly un-dismisses (the
    filter also excludes registered slugs).
    """
    slug = (slug or "").strip().lower()
    if not slug or not _HELPER_SLUG_RE.match(slug):
        return False, "invalid slug"
    with _cache_lock:
        sidecar = _read_sidecar(vmid) or {
            "vmid": int(vmid), "apps": [],
            "created_at": _now_iso(), "updated_at": _now_iso(),
        }
        current = list(sidecar.get("dismissed_slugs") or [])
        if dismissed:
            if slug not in current:
                current.append(slug)
        else:
            current = [s for s in current if s != slug]
        sidecar["dismissed_slugs"] = current
        sidecar["updated_at"] = _now_iso()
        if not _write_sidecar(vmid, sidecar):
            return False, "could not persist sidecar (permission?)"
    return True, _read_sidecar(vmid)


def _find_app(sidecar: dict, app_id: str) -> Optional[dict]:
    for app in sidecar.get("apps") or []:
        if app.get("id") == app_id:
            return app
    return None


def add_app(vmid, payload: dict) -> tuple[bool, Any]:
    ok, cfg = validate_config(payload)
    if not ok:
        return False, cfg
    with _cache_lock:
        sidecar = _read_sidecar(vmid) or {
            "vmid": int(vmid), "apps": [],
            "created_at": _now_iso(), "updated_at": _now_iso(),
        }
        sidecar.setdefault("apps", [])
        new_id = _new_app_id()
        sidecar["apps"].append({
            "id": new_id,
            **cfg,
            "state": _empty_state(),
            "created_at": _now_iso(),
        })
        sidecar["updated_at"] = _now_iso()
        if not _write_sidecar(vmid, sidecar):
            return False, "could not persist sidecar (permission?)"
    # Kick a first check so the UI shows real numbers immediately
    check_app(vmid, new_id, force=True)
    return True, _read_sidecar(vmid)


def update_app(vmid, app_id: str, payload: dict) -> tuple[bool, Any]:
    ok, cfg = validate_config(payload)
    if not ok:
        return False, cfg
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        if not sidecar:
            return False, "no apps registered for this vmid"
        app = _find_app(sidecar, app_id)
        if not app:
            return False, f"app_id '{app_id}' not found"
        # Preserve id + created_at + state; replace the rest
        state = app.get("state") or _empty_state()
        created = app.get("created_at") or _now_iso()
        idx = sidecar["apps"].index(app)
        sidecar["apps"][idx] = {
            "id": app_id, **cfg, "state": state, "created_at": created,
        }
        sidecar["updated_at"] = _now_iso()
        if not _write_sidecar(vmid, sidecar):
            return False, "could not persist sidecar"
    check_app(vmid, app_id, force=True)
    return True, _read_sidecar(vmid)


def delete_app(vmid, app_id: str) -> bool:
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        if not sidecar:
            return True
        before = len(sidecar.get("apps") or [])
        sidecar["apps"] = [a for a in sidecar.get("apps") or [] if a.get("id") != app_id]
        sidecar["updated_at"] = _now_iso()
        # If the CT has no apps left, remove the sidecar entirely so
        # the empty state shows correctly.
        if not sidecar["apps"]:
            try:
                os.unlink(_sidecar_path(vmid))
                return True
            except OSError:
                pass
        if before != len(sidecar["apps"]):
            _write_sidecar(vmid, sidecar)
        return True


def delete_all(vmid) -> bool:
    try:
        os.unlink(_sidecar_path(vmid))
        return True
    except FileNotFoundError:
        return True
    except OSError as e:
        print(f"[ProxMenux] lxc_apps: delete_all failed: {e}")
        return False


# ── External update-cron detection ─────────────────────────────────
#
# Some users already run the community-scripts host-wide cron
# (`cron-update-lxcs.sh`) to auto-update every LXC on the node. We
# don't try to compete with that or ask them to remove it — the UX
# just reflects "already covered by an external cron" so ProxMenux's
# own per-CT scheduler is offered as an addition, not a replacement.
#
# Scope is DELIBERATELY strict: only patterns tied to community-scripts
# specifically (their published script name + the well-known repo
# path) so we never flag a random user cron that touches `pct` — false
# positives here would just add noise. When community-scripts publishes
# new update scripts, add their identifiers to this list.

# Each entry: (pattern, variant, scope). `scope` describes what the
# cron actually touches — verified by reading each script's source.
# Both known variants only run `apt-get dist-upgrade` / `apk upgrade`
# inside every CT; neither invokes `/usr/bin/update`, so per-app
# helper updates are NOT covered. `scope="os"` reflects that.
_EXTERNAL_CRON_MATCHERS = (
    ("update-lxcs-cron.sh", "community-scripts", "os"),
    ("cron-update-lxcs.sh", "community-scripts", "os"),
    ("tteck/Proxmox",       "tteck-legacy",      "os"),
    ("update-apps.sh",      "unknown",           "unknown"),
    ("community-scripts/ProxmoxVE", "community-scripts", "os"),
)

_EXTERNAL_CRON_LOCATIONS = (
    "/etc/cron.d",
    "/etc/cron.hourly",
    "/etc/cron.daily",
    "/etc/cron.weekly",
    "/etc/cron.monthly",
    "/var/spool/cron/crontabs",
)


def _humanise_cron(cron_5field: str) -> str:
    """Turn a 5-field cron expression into a plain-English label for
    the UI. Falls back to the raw expression when the shape doesn't
    match one of the presets the picker exposes."""
    if not isinstance(cron_5field, str):
        return ""
    parts = cron_5field.strip().split()
    if len(parts) != 5:
        return cron_5field
    m, h, d, mo, w = parts
    def _hhmm() -> str:
        try:
            return f"{int(h):02d}:{int(m):02d}"
        except ValueError:
            return f"{h}:{m}"
    if d == "*" and mo == "*" and w == "*" and m.isdigit() and h.isdigit():
        return f"Daily at {_hhmm()}"
    if d == "*" and mo == "*" and w.isdigit() and m.isdigit() and h.isdigit():
        wdays = ["Sunday", "Monday", "Tuesday", "Wednesday",
                 "Thursday", "Friday", "Saturday"]
        wname = wdays[int(w)] if 0 <= int(w) <= 6 else w
        return f"Weekly ({wname} {_hhmm()})"
    if mo == "*" and w == "*" and d.isdigit() and m.isdigit() and h.isdigit():
        return f"Monthly (day {int(d)} at {_hhmm()})"
    if h == "*" and d == "*" and mo == "*" and w == "*" and m == "0":
        return "Hourly"
    return cron_5field


def _scan_cron_line(line: str) -> Optional[dict]:
    """Try to interpret ``line`` as a cron entry that references one
    of the known external update patterns. Returns
    ``{cron, cron_line, human_schedule, variant, scope}`` or None
    when the line isn't a match. ``variant`` identifies which known
    updater the cron drives (tteck-legacy, community-scripts,
    unknown); ``scope`` is what that variant actually touches (os,
    unknown). Silently skips comments and blank lines."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    matched = None
    for pat, variant, scope in _EXTERNAL_CRON_MATCHERS:
        if pat in line:
            matched = (variant, scope)
            break
    if not matched:
        return None
    tokens = line.split(None, 6)
    if len(tokens) < 6:
        return None
    cron_5 = " ".join(tokens[:5])
    if _validate_cron(cron_5) is not None:
        return None
    return {
        "cron": cron_5,
        "cron_line": line,
        "human_schedule": _humanise_cron(cron_5),
        "variant": matched[0],
        "scope": matched[1],
    }


def detect_external_update_cron() -> Optional[dict]:
    """Walk the well-known cron locations looking for a community-
    scripts update entry. First hit wins and is returned as
    ``{source, cron_line, cron, human_schedule, type}``; None when
    nothing recognised is present. Errors reading a file are ignored
    silently — a permissions issue on one entry shouldn't blow up
    the whole probe."""
    for loc in _EXTERNAL_CRON_LOCATIONS:
        if not os.path.isdir(loc):
            # Might be a single file (cron.hourly is a dir, but
            # `/etc/crontab` — added below — is a file).
            if os.path.isfile(loc):
                try:
                    with open(loc) as f:
                        for raw in f:
                            parsed = _scan_cron_line(raw)
                            if parsed:
                                return {**parsed, "source": loc, "type": parsed["variant"]}
                except OSError:
                    pass
            continue
        try:
            names = sorted(os.listdir(loc))
        except OSError:
            continue
        for name in names:
            path = os.path.join(loc, name)
            if not os.path.isfile(path):
                continue
            try:
                with open(path) as f:
                    for raw in f:
                        parsed = _scan_cron_line(raw)
                        if parsed:
                            return {**parsed, "source": path, "type": parsed["variant"]}
            except OSError:
                continue
    # /etc/crontab (single file at root)
    try:
        with open("/etc/crontab") as f:
            for raw in f:
                parsed = _scan_cron_line(raw)
                if parsed:
                    return {**parsed, "source": "/etc/crontab", "type": parsed["variant"]}
    except OSError:
        pass
    return None


# ── Scheduled updates CRUD ──────────────────────────────────────────

def get_schedule(vmid) -> Optional[dict]:
    """Return the persisted schedule config for this vmid, or None if
    the sidecar has no schedule set. Safe on missing sidecar."""
    sidecar = _read_sidecar(vmid)
    if not sidecar:
        return None
    sched = sidecar.get("schedule")
    return sched if isinstance(sched, dict) else None


def update_schedule(vmid, payload: dict) -> tuple[bool, Any]:
    """Persist a new/updated schedule config. Creates the sidecar if
    the CT hasn't registered any apps yet — a bare CT can still be
    scheduled for OS updates (target=os). Returns (True, sidecar) or
    (False, err_msg)."""
    ok, sched = validate_schedule(payload)
    if not ok:
        return False, sched
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        if not sidecar:
            sidecar = {
                "vmid": vmid,
                "apps": [],
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        # Merge over previous schedule so last_run_at etc. survive an
        # edit that doesn't re-send them.
        prev = sidecar.get("schedule") or {}
        merged = dict(prev)
        merged.update(sched)
        sidecar["schedule"] = merged
        sidecar["updated_at"] = _now_iso()
        if not _write_sidecar(vmid, sidecar):
            return False, "could not persist sidecar"
    return True, sidecar


def delete_schedule(vmid) -> bool:
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        if not sidecar or "schedule" not in sidecar:
            return True
        sidecar.pop("schedule", None)
        sidecar["updated_at"] = _now_iso()
        return _write_sidecar(vmid, sidecar)


def get_all_schedules() -> list:
    """Enumerate every sidecar with a schedule set. Used by the
    scheduler thread every minute to know which CTs to check.
    Returns a list of ``{vmid: int, schedule: dict}`` — one entry per
    CT with a non-empty schedule (enabled OR disabled; the scheduler
    decides whether to fire)."""
    out: list = []
    try:
        entries = os.listdir(_APPS_DIR)
    except (FileNotFoundError, OSError):
        return out
    for name in entries:
        if not name.endswith(".json"):
            continue
        try:
            vmid = int(name[:-5])
        except ValueError:
            continue
        sidecar = _read_sidecar(vmid)
        if not sidecar:
            continue
        sched = sidecar.get("schedule")
        if isinstance(sched, dict) and sched.get("cron"):
            out.append({"vmid": vmid, "schedule": sched})
    return out


def record_schedule_run(vmid, status: str, target: str) -> bool:
    """Called by the scheduler after a fired run completes. Updates
    the schedule with last_run_at + last_run_status so the UI can show
    the outcome. `status` is one of "success" | "failure" |
    "skipped"."""
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        if not sidecar or not isinstance(sidecar.get("schedule"), dict):
            return False
        sidecar["schedule"]["last_run_at"] = _now_iso()
        sidecar["schedule"]["last_run_status"] = status
        sidecar["schedule"]["last_run_target"] = target
        sidecar["updated_at"] = _now_iso()
        return _write_sidecar(vmid, sidecar)


def _fire_update_notification(vmid, app: dict) -> None:
    # Per-app opt-out: user flipped the bell icon off for this specific
    # app (because they know it can't be updated on their box or they
    # just don't care). Field defaults to True — an app registered
    # before this feature landed keeps receiving notifications.
    if app.get("notifications_enabled", True) is False:
        return
    try:
        from notification_manager import notification_manager
        import socket
        state = app.get("state") or {}
        notification_manager.emit_event(
            event_type='app_update_available',
            severity='INFO',
            data={
                'hostname': socket.gethostname(),
                'vmid': int(vmid),
                'ct_name': app.get('name') or f'CT-{vmid}',
                'app_name': app.get('name') or 'app',
                'installed': state.get('installed_version') or 'unknown',
                'latest': state.get('latest_version') or 'unknown',
            },
            source='app_watch',
            entity='ct',
            # vmid + app_id + latest so multi-app CTs don't dedup and
            # subsequent upstream releases still fire.
            entity_id=f"{vmid}:{app.get('id')}:{state.get('latest_version') or ''}",
        )
    except Exception as e:
        print(f"[ProxMenux] lxc_apps: notif emit failed for CT {vmid}: {e}")


def _detect_with_alt_healing(vmid, app: dict) -> tuple:
    """Detect the installed version for an app, falling back to
    ``alt_detectors`` from the hint when the primary detector's target
    isn't present on this CT. On a successful fallback the app dict
    is MUTATED in place to reflect the working detector — the sidecar
    write happens by the caller — so subsequent checks go straight to
    the resolved detector without paying the fallback cost again.

    Returns ``(installed_version, error, healed_bool)`` where
    ``healed_bool`` is True when the working detector was an alt and
    the app dict was rewritten.
    """
    installed, err = detect_installed_version(vmid, app)
    if installed or not err:
        return installed, err, False
    slug = app.get("helper_slug")
    if not slug:
        return installed, err, False
    hint = (_fetch_tracking_hints() or {}).get(slug) or {}
    # Build a unified fallback list from both:
    #   • alt_detectors — cross-method (file→binary, file→dpkg, …)
    #   • file_fallbacks — same-method secondary file paths (legacy
    #     layouts of the same install). Same semantics for auto-heal,
    #     different JSON shape for historical reasons.
    fallbacks: list = []
    for alt in hint.get("alt_detectors") or []:
        if isinstance(alt, dict):
            fallbacks.append(alt)
    for fb in hint.get("file_fallbacks") or []:
        if isinstance(fb, dict) and fb.get("path"):
            fallbacks.append({
                "installed_via": "file",
                "file_path": fb["path"],
                "file_regex": fb.get("regex") or hint.get("file_regex"),
            })
    if not fallbacks:
        return installed, err, False
    # Try each fallback in order; first that produces a parseable
    # version wins. We copy its fields into a probe dict so
    # detect_installed_version can run unchanged.
    for alt in fallbacks:
        method = alt.get("installed_via")
        if method not in _VALID_METHODS:
            continue
        probe = {"installed_via": method}
        for k in _DETECTOR_FIELDS:
            if k in alt:
                probe[k] = alt[k]
        # Inherit the app's tag_regex + installed_regex for output
        # parsing when the alt hasn't overridden them.
        for k in ("tag_regex", "installed_regex"):
            if k in app and k not in probe:
                probe[k] = app[k]
        alt_installed, alt_err = detect_installed_version(vmid, probe)
        if alt_installed:
            # Heal: mutate app with the winning detector's fields.
            # Clear stale fields from the previous method so the
            # sidecar reflects exactly what's being used.
            for k in _DETECTOR_FIELDS:
                app.pop(k, None)
            for k, v in probe.items():
                if k not in ("tag_regex", "installed_regex"):
                    app[k] = v
            return alt_installed, None, True
    return installed, err, False


def check_app(vmid, app_id: str, force: bool = False) -> Optional[dict]:
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        if not sidecar:
            return None
        app = _find_app(sidecar, app_id)
        if not app:
            return None

        # Docker apps are register-only — no version detection, no
        # upstream check, no error emission. Just stamp checked_at so
        # the UI can show "we know about you, we're not tracking you".
        if app.get("installed_via") == "docker":
            app["state"] = {**_empty_state(), "checked_at": _now_iso()}
            sidecar["updated_at"] = _now_iso()
            _write_sidecar(vmid, sidecar)
            return sidecar

        state = app.get("state") or _empty_state()
        checked_at = state.get("checked_at")
        if not force and checked_at:
            try:
                t = datetime.datetime.strptime(checked_at.rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
                age = (datetime.datetime.utcnow() - t).total_seconds()
                if age < _UPSTREAM_CACHE_TTL_SEC:
                    return sidecar
            except (ValueError, TypeError):
                pass

        installed, inst_err, _healed = _detect_with_alt_healing(vmid, app)
        # Trigger the upstream fetch when ANY upstream source is
        # configured. The dispatcher inside `fetch_latest_upstream`
        # returns (None, None) cleanly when nothing is set, so the
        # cheap gate below only skips the no-upstream case and lets
        # http_json / docker_hub (which don't set `repo`) through.
        latest, up_err = (None, None)
        if app.get("repo") or app.get("upstream_type") in ("http_json", "docker_hub"):
            latest, up_err = fetch_latest_upstream(app)

        err = inst_err or up_err
        update_available = compare(installed, latest) if (installed and latest) else None

        app["state"] = {
            "installed_version": installed,
            "latest_version": latest,
            "update_available": update_available,
            "error": err,
            "checked_at": _now_iso(),
        }
        sidecar["updated_at"] = _now_iso()
        _write_sidecar(vmid, sidecar)

        # Emit every time an update is pending. The old `latest !=
        # prev_latest` guard tried to prevent spam by only firing on
        # the first observation of each new upstream version, but it
        # also swallowed the emit whenever the notification setting
        # was toggled off → on after the first observation (the
        # sidecar already had `latest_version` recorded, so subsequent
        # checks looked like "same latest, nothing to do"). Anti-spam
        # is the notification manager's job: it dedups by `entity_id`
        # (vmid + app_id + latest_version) with its cooldown, and only
        # a genuinely new upstream release changes the entity_id and
        # triggers a fresh delivery.
        if update_available and latest:
            _fire_update_notification(vmid, app)

        return sidecar


def emit_all_pending_updates() -> int:
    """Walk every sidecar and emit `app_update_available` for each
    app currently marked with a pending upstream release. Safe to
    call repeatedly — `notification_manager` dedups by entity_id
    (vmid + app_id + latest_version), so a given release only sends
    once until a newer version appears.

    Needed because `check_app(force=False)` short-circuits on a fresh
    `checked_at` and never reaches the emit path. The 24 h
    PollingCollector runs `refresh_all_apps(force=False)`, so without
    this helper the notification only ever fired on the exact tick
    where a new upstream version was FIRST observed — and even that
    was silenced when the user's setting was OFF at the time.
    Returns the number of emits attempted (delivery still depends on
    channel enablement + cooldown + rate limit)."""
    try:
        entries = sorted(os.listdir(_APPS_DIR))
    except (FileNotFoundError, OSError):
        print("[ProxMenux] emit_all_pending_updates: _APPS_DIR missing", flush=True)
        return 0
    n = 0
    print(f"[ProxMenux] emit_all_pending_updates: scanning {len(entries)} sidecar file(s)", flush=True)
    for name in entries:
        if not name.endswith(".json"):
            continue
        try:
            vmid = int(name[:-5])
        except ValueError:
            continue
        try:
            sidecar = _read_sidecar(vmid)
            if not sidecar:
                print(f"[ProxMenux] emit_all_pending_updates: CT {vmid} sidecar empty", flush=True)
                continue
            apps = sidecar.get("apps") or []
            pending = [a for a in apps
                       if (a.get("state") or {}).get("update_available")
                       and (a.get("state") or {}).get("latest_version")]
            print(f"[ProxMenux] emit_all_pending_updates: CT {vmid} apps={len(apps)} pending={len(pending)}", flush=True)
            for app in pending:
                try:
                    _fire_update_notification(vmid, app)
                    n += 1
                    print(f"[ProxMenux] emit_all_pending_updates: CT {vmid} emit '{app.get('name')}'", flush=True)
                except Exception as inner:
                    print(f"[ProxMenux] emit_all_pending_updates: CT {vmid} emit '{app.get('name')}' FAILED: {inner}", flush=True)
        except Exception as e:
            print(f"[ProxMenux] emit_all_pending_updates: CT {vmid} outer failure: {e}", flush=True)
    print(f"[ProxMenux] emit_all_pending_updates: {n} emit(s) attempted total", flush=True)
    return n


def check_all(vmid, force: bool = False) -> Optional[dict]:
    sidecar = _read_sidecar(vmid)
    if not sidecar:
        return None
    for app in (sidecar.get("apps") or []):
        try:
            check_app(vmid, app.get("id"), force=force)
        except Exception as e:
            print(f"[ProxMenux] lxc_apps.check_all: CT {vmid} app {app.get('id')} failed: {e}")
    return _read_sidecar(vmid)


def refresh_all_apps(force: bool = False) -> int:
    """Called from the polling collector's daily cycle so header
    badges stay fresh without needing to open every modal."""
    try:
        entries = os.listdir(_APPS_DIR)
    except (FileNotFoundError, OSError):
        return 0
    n = 0
    for name in entries:
        if not name.endswith(".json"):
            continue
        try:
            vmid = int(name[:-5])
        except ValueError:
            continue
        try:
            check_all(vmid, force=force)
            n += 1
        except Exception as e:
            print(f"[ProxMenux] lxc_apps refresh_all: CT {vmid} failed: {e}")
    return n


def _summarise_app(app: dict) -> dict:
    """Compact summary used by /api/vms to decorate LXC rows without
    forcing the frontend to fetch the full sidecar. Includes ports
    so the modal header can render clickable web links inline."""
    state = app.get("state") or {}
    return {
        "id": app.get("id"),
        "name": app.get("name"),
        "installed_via": app.get("installed_via"),
        "ports": app.get("ports") or [],
        "health_path": app.get("health_path"),
        "installed_version": state.get("installed_version"),
        "latest_version": state.get("latest_version"),
        "update_available": state.get("update_available"),
        "error": state.get("error"),
        "checked_at": state.get("checked_at"),
        "has_repo": bool(app.get("repo")),
        # Updates tab surfaces: whether the user has a custom bash
        # command wired up ("Apply {app}" runs `pct exec sh -c` on
        # it) and whether the "no method" notice is suppressed for
        # this app.
        "update_command": app.get("update_command") or "",
        "hide_no_updater_notice": bool(app.get("hide_no_updater_notice")),
        # Community-scripts slug that the Register-chip flow attaches
        # to the app. Surfaced so the Updates tab helper section can
        # match this registered app against the CT's helper_slug and
        # display its installed/upstream versions.
        "helper_slug": app.get("helper_slug") or "",
    }


def get_catalog() -> list:
    """Return a compact catalog of registerable apps for the frontend
    picker. Sourced from helpers_cache.json (community-scripts, ~700
    apps with name/logo/port/website) enriched with a `has_tracking`
    flag that tells the frontend whether we have a curated tracking
    hint for this slug (→ Register button pre-fills the advanced
    form). Response is small enough (~40-50 KB) to cache client-side.
    """
    try:
        import managed_installs
        cache = managed_installs._fetch_helpers_cache() or {}
    except Exception:
        cache = {}
    hints = _fetch_tracking_hints() or {}
    out: list = []
    for slug, entry in cache.items():
        if not isinstance(entry, dict):
            continue
        out.append({
            "slug": slug,
            "name": entry.get("name") or slug,
            "logo": entry.get("logo") or "",
            "default_port": entry.get("default_port") or 0,
            "has_tracking": slug in hints,
        })
    # Also surface tracking-hint slugs that aren't in helpers_cache
    # (our user-only fallback entries like docker/pihole/wireguard).
    seen = {e["slug"] for e in out}
    for slug, hint in hints.items():
        if slug in seen:
            continue
        out.append({
            "slug": slug,
            "name": (hint.get("name") if isinstance(hint, dict) else None) or slug,
            "logo": (hint.get("logo") if isinstance(hint, dict) else "") or "",
            "default_port": ((hint.get("default_ports") or [0])[0] if isinstance(hint, dict) else 0),
            "has_tracking": True,
        })
    out.sort(key=lambda e: e["name"].lower())
    return out


def get_catalog_entry(slug: str) -> Optional[dict]:
    """Detail for a single catalog slug, including any curated hint
    fields. Called by the frontend when the user picks an app from the
    Combobox — the response seeds the editor with detector metadata
    when we have it."""
    if not slug:
        return None
    slug = slug.strip().lower()
    try:
        import managed_installs
        cache = managed_installs._fetch_helpers_cache() or {}
    except Exception:
        cache = {}
    hints = _fetch_tracking_hints() or {}
    catalog = cache.get(slug) or {}
    hint = hints.get(slug) or {}
    if not catalog and not hint:
        return None

    # Build tracking_suggestion from the hint if present. Resolve
    # file candidates lazily — the endpoint doesn't receive a vmid so
    # we return the primary; auto-heal at check time will pick the
    # working detector.
    tracking = None
    if hint:
        tracking = {k: v for k, v in hint.items()
                    if k not in ("logo", "website", "default_ports",
                                  "file_fallbacks", "alt_detectors")}

    # Enrich port from catalog when hint doesn't specify one.
    default_ports: list = []
    raw_ports = hint.get("default_ports") if isinstance(hint, dict) else None
    if isinstance(raw_ports, list):
        for p in raw_ports:
            try:
                n = int(p)
                if 1 <= n <= 65535:
                    default_ports.append(n)
            except (TypeError, ValueError):
                continue
    if not default_ports and catalog.get("default_port"):
        try:
            n = int(catalog["default_port"])
            if 1 <= n <= 65535:
                default_ports.append(n)
        except (TypeError, ValueError):
            pass

    return {
        "slug": slug,
        "name": catalog.get("name") or (hint.get("name") if isinstance(hint, dict) else None) or slug,
        "logo_url": (
            (hint.get("logo") if isinstance(hint, dict) else "")
            or catalog.get("logo") or ""
        ) or None,
        "website": catalog.get("website") or "",
        "default_ports": default_ports,
        "tracking_suggestion": tracking,
    }


def get_active_apps() -> dict:
    """``{vmid_str: [summary, …]}``. Never triggers a re-check —
    reads persisted state only."""
    out: dict = {}
    try:
        entries = os.listdir(_APPS_DIR)
    except (FileNotFoundError, OSError):
        return out
    for name in entries:
        if not name.endswith(".json"):
            continue
        try:
            vmid = int(name[:-5])
        except ValueError:
            continue
        sidecar = _read_sidecar(vmid)
        if not sidecar:
            continue
        apps = sidecar.get("apps") or []
        if not apps:
            continue
        out[str(vmid)] = [_summarise_app(a) for a in apps]
    return out


# ── Suggestions endpoint helpers ──────────────────────────────────

_KNOWN_WEB_PORTS = {80, 443, 3000, 3001, 4444, 5000, 5001, 5432, 6379,
                    7000, 7878, 8000, 8080, 8081, 8096, 8123, 8181,
                    8384, 8443, 8686, 8787, 8989, 9000, 9090, 9091, 9117}


# Port probing is a `pct exec ss -tlnH` per CT — ~500-800ms wall time
# on a warm host. Memoized per-vmid with a 60s TTL so opening the App
# tab multiple times in quick succession stays snappy; the first open
# still pays the probe cost.
_PORT_PROBE_TTL_SEC = 60
_port_probe_cache: dict = {}
_port_probe_lock = threading.RLock()

# Same TTL discipline for file-existence probes used to resolve
# legacy install layouts (see _resolve_file_candidate).
_file_probe_cache: dict = {}
_file_probe_lock = threading.RLock()


def _first_existing_file(vmid, paths: list) -> Optional[str]:
    """Return the first path from ``paths`` that exists as a regular
    file inside the CT, or None if none exist. Single ``pct exec find``
    (busybox-compatible) so probing a 3-candidate list is one round-
    trip. Memoized per (vmid, tuple(paths)) with a 60 s TTL to keep
    repeated App-tab opens snappy.
    """
    if not paths:
        return None
    key = (str(vmid), tuple(paths))
    now = time.time()
    with _file_probe_lock:
        cached = _file_probe_cache.get(key)
        if cached and (now - cached[0]) < _PORT_PROBE_TTL_SEC:
            return cached[1]
    # `find <paths> -maxdepth 0 -type f -print` — busybox-safe. Missing
    # paths are silently skipped; existing regular files land on stdout.
    rc, out, _ = _pct_exec(vmid, ["find"] + list(paths) + ["-maxdepth", "0", "-type", "f", "-print"])
    found = {l.strip() for l in out.splitlines() if l.strip()} if rc in (0, 1) else set()
    resolved = next((p for p in paths if p in found), None)
    with _file_probe_lock:
        _file_probe_cache[key] = (now, resolved)
    return resolved


# Multi-app detection: probe every hint we have against the CT and
# return the slugs whose install signature is present. The point is
# CTs that host more than one app (helper-scripts install + a manual
# Docker on top, or several apps side by side): the primary detection
# via community-scripts marker + hostname fuzzy only surfaces ONE
# slug, but here we surface every hint whose install is real. All
# probes are batched by method → 3 pct-exec calls per CT max.
#
# Memoized per-vmid with the same 60 s TTL as the port probe.
_detected_apps_cache: dict = {}
_detected_apps_lock = threading.RLock()


_DETECTOR_FIELDS = (
    "package", "file_path", "file_regex", "binary_path", "binary_args",
    "python_path", "distribution", "container_name", "label",
    "command_argv", "installed_version",
)


def _iter_hint_detectors(h: dict):
    """Yield every detector (primary + alt_detectors) for a hint as
    ``{installed_via, ...method-specific fields}`` dicts. Used by
    multi-detect probes and by the version-check auto-heal so an app
    that has moved from its canonical layout (manual install, legacy)
    is still detected via whatever secondary target does exist.
    """
    if not isinstance(h, dict):
        return
    primary = {"installed_via": h.get("installed_via")}
    for k in _DETECTOR_FIELDS:
        if k in h:
            primary[k] = h[k]
    if primary["installed_via"]:
        yield primary
    for alt in h.get("alt_detectors") or []:
        if isinstance(alt, dict) and alt.get("installed_via"):
            yield alt


def _probe_detected_apps_map(vmid) -> dict:
    """Return ``{slug: [detector_dicts_that_matched]}`` — the full
    working-detector map for every hint whose install signature is
    present on the CT. Detectors are kept in the SAME order they
    appear in the hint (primary → alt_detectors → file_fallbacks) so
    callers can just take ``[0]`` as the preferred one for this CT.

    Same batched probes as before; the extra bookkeeping is a dict
    holding the detector dict alongside the slug at each mapping key.
    """
    key = str(vmid)
    now = time.time()
    with _detected_apps_lock:
        cached = _detected_apps_cache.get(key)
        if cached and (now - cached[0]) < _PORT_PROBE_TTL_SEC:
            return {slug: [dict(d) for d in dets]
                    for slug, dets in (cached[1] or {}).items()}

    hints = _fetch_tracking_hints() or {}
    # Each mapping key is (slug, detector_dict) — same target may map
    # to multiple slugs in theory (unlikely) so we store a list.
    binary_paths: dict = {}   # path → [(slug, det), …]
    file_paths: dict = {}
    dpkg_pkgs: dict = {}
    apk_pkgs: dict = {}
    docker_containers: dict = {}

    def _add(bucket, target, slug, det):
        bucket.setdefault(target, []).append((slug, det))

    for slug, h in hints.items():
        if not isinstance(h, dict):
            continue
        # file_fallbacks: same-method secondary paths — synthesize
        # per-fallback detector dicts that inherit the primary's file
        # method so downstream code has full detector context.
        for fb in h.get("file_fallbacks") or []:
            if not isinstance(fb, dict):
                continue
            p = fb.get("path")
            r = fb.get("regex")
            if isinstance(p, str) and p:
                fb_det = {
                    "installed_via": "file",
                    "file_path": p,
                    "file_regex": r or h.get("file_regex", ""),
                }
                _add(file_paths, p, slug, fb_det)
        # Primary + every alt_detector share the same batching logic.
        for det in _iter_hint_detectors(h):
            method = det.get("installed_via")
            if method == "binary":
                bp = det.get("binary_path")
                if isinstance(bp, str) and bp:
                    _add(binary_paths, bp, slug, det)
            elif method == "file":
                fp = det.get("file_path")
                if isinstance(fp, str) and fp:
                    _add(file_paths, fp, slug, det)
            elif method == "dpkg":
                pkg = det.get("package")
                if isinstance(pkg, str) and pkg:
                    _add(dpkg_pkgs, pkg, slug, det)
            elif method == "apk":
                pkg = det.get("package")
                if isinstance(pkg, str) and pkg:
                    _add(apk_pkgs, pkg, slug, det)
            elif method == "python_dist":
                pp = det.get("python_path")
                if isinstance(pp, str) and pp:
                    _add(file_paths, pp, slug, det)
            elif method in ("docker_label", "docker_exec"):
                cn = det.get("container_name")
                if isinstance(cn, str) and cn:
                    _add(docker_containers, cn, slug, det)

    # slug → ordered list of matched detectors (primary preference
    # preserved by natural insertion order from _iter_hint_detectors).
    matched: dict = {}

    def _record(slug, det):
        matched.setdefault(slug, []).append(det)

    def _probe_paths(paths: dict) -> None:
        if not paths:
            return
        rc, out, _ = _pct_exec(vmid, ["find"] + list(paths) + ["-maxdepth", "0", "-type", "f", "-print"])
        if rc not in (0, 1):
            return
        for line in out.splitlines():
            p = line.strip()
            if p in paths:
                for slug, det in paths[p]:
                    _record(slug, det)

    _probe_paths(binary_paths)
    _probe_paths(file_paths)

    if dpkg_pkgs:
        rc, out, _ = _pct_exec(vmid, ["dpkg-query", "-W", "-f", "${Package}\\t${Status}\\n"] + list(dpkg_pkgs))
        if rc in (0, 1):
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and "install ok installed" in parts[1]:
                    pkg = parts[0].strip()
                    if pkg in dpkg_pkgs:
                        for slug, det in dpkg_pkgs[pkg]:
                            _record(slug, det)

    if apk_pkgs:
        rc, out, _ = _pct_exec(vmid, ["apk", "info", "-e"] + list(apk_pkgs))
        if rc == 0:
            for line in out.splitlines():
                pkg = line.strip()
                if pkg in apk_pkgs:
                    for slug, det in apk_pkgs[pkg]:
                        _record(slug, det)

    if docker_containers:
        rc, out, _ = _pct_exec(vmid, ["docker", "ps", "-a", "--format", "{{.Names}}"])
        if rc == 0:
            present = {line.strip() for line in out.splitlines() if line.strip()}
            for cn, entries in docker_containers.items():
                if cn in present:
                    for slug, det in entries:
                        _record(slug, det)

    with _detected_apps_lock:
        _detected_apps_cache[key] = (now, {slug: list(dets) for slug, dets in matched.items()})
    return matched


def _probe_detected_apps(vmid) -> set:
    """Legacy set-returning wrapper — kept for callers that only need
    presence, not detector context."""
    return set(_probe_detected_apps_map(vmid).keys())


def _resolve_file_candidate(vmid, tracking: dict) -> None:
    """Rewrite ``tracking``'s ``file_path`` / ``file_regex`` to the
    first candidate that actually exists on the CT, so the sidecar the
    user saves points at the layout their install produced.

    Enables curated hints to declare legacy fallbacks (e.g. NPM's
    modern `/root/.nginxproxymanager` + legacy `/app/package.json`).
    Each fallback carries its own regex, since legacy layouts often
    stored the version in a very different format (a JSON blob vs a
    single line). If none of the candidates exist, the primary path
    is preserved so the user still gets the auto-fill and can adjust
    manually. Silently strips ``file_fallbacks`` from the returned
    hint — the frontend never sees the candidate list.
    """
    if tracking.get("installed_via") != "file":
        return
    primary = tracking.get("file_path")
    if not primary:
        return
    fallbacks_raw = tracking.pop("file_fallbacks", None)
    if not isinstance(fallbacks_raw, list) or not fallbacks_raw:
        return
    # Build ordered probe list (primary first)
    candidates: list = []
    seen: set = {primary}
    candidates.append({"path": primary, "regex": tracking.get("file_regex", "")})
    for f in fallbacks_raw:
        if not isinstance(f, dict):
            continue
        p = f.get("path")
        r = f.get("regex")
        if not isinstance(p, str) or not p or not isinstance(r, str) or not r:
            continue
        if p in seen:
            continue
        seen.add(p)
        candidates.append({"path": p, "regex": r})
    paths_only = [c["path"] for c in candidates]
    found = _first_existing_file(vmid, paths_only)
    if found and found != primary:
        for c in candidates:
            if c["path"] == found:
                tracking["file_path"] = c["path"]
                tracking["file_regex"] = c["regex"]
                break


def _probe_listening_ports(vmid) -> list[int]:
    key = str(vmid)
    now = time.time()
    with _port_probe_lock:
        cached = _port_probe_cache.get(key)
        if cached and (now - cached[0]) < _PORT_PROBE_TTL_SEC:
            return list(cached[1])
    rc, out, _ = _pct_exec(vmid, ["ss", "-tlnH"], timeout=5)
    if rc != 0:
        rc, out, _ = _pct_exec(vmid, ["netstat", "-tln"], timeout=5)
        if rc != 0:
            with _port_probe_lock:
                _port_probe_cache[key] = (now, [])
            return []
    ports: set = set()
    for line in out.splitlines():
        for token in line.split():
            if ":" not in token:
                continue
            candidate = token.rsplit(":", 1)[-1]
            if candidate.isdigit():
                p = int(candidate)
                if 1 <= p <= 65535:
                    ports.add(p)
    result = sorted(p for p in ports if p not in (22, 53, 5353))
    with _port_probe_lock:
        _port_probe_cache[key] = (now, result)
    return result


def _helper_slug_meta(vmid) -> Optional[dict]:
    try:
        import managed_installs
    except Exception:
        return None
    try:
        items = managed_installs.get_active_items() or []
    except Exception:
        return None
    for it in items:
        if it.get("type") == "lxc" and str(it.get("_vmid")) == str(vmid):
            slug = it.get("_helper_slug")
            name = it.get("_helper_app_name")
            if slug or name:
                return {"slug": slug, "name": name}
    return None


def _catalog_lookup(slug: str) -> Optional[dict]:
    """Fetch the community-scripts catalog entry for a slug.
    Returns {name, updateable, default_port, logo} or None.
    Cached inside managed_installs (7 day TTL, disk-backed)."""
    if not slug:
        return None
    try:
        import managed_installs
        cache = managed_installs._fetch_helpers_cache() or {}
    except Exception:
        return None
    return cache.get(slug)


def _merge_tracking_hints(slug: str) -> Optional[dict]:
    """Return the curated tracking suggestion for a slug.

    Reads from json/app_tracking_hints.json (built in CI by merging
    the audit generator's verified entries with our manual
    overrides). Returns None if the slug has no hint — the frontend's
    "Register with version tracking" flow requires `installed_via`
    to pre-fill the advanced form, so a missing hint means only the
    "Just register a link" path is offered.
    """
    hint = _fetch_tracking_hints().get(slug)
    if not hint:
        return None
    return dict(hint)


def get_suggestions(vmid) -> dict:
    ports = _probe_listening_ports(vmid)
    web_hint = None
    for p in ports:
        if p in _KNOWN_WEB_PORTS:
            web_hint = "/"
            break
    meta = _helper_slug_meta(vmid) or {}
    slug = meta.get("slug")
    # Tracking hint pipeline: catalog + curated hints merged.
    #   • catalog (community-scripts helpers_cache.json) covers ~430
    #     apps with name+repo+port+upstream_version, zero curation
    #     from us — refreshed by generate_helpers_cache.py in CI.
    #   • curated hints (json/app_tracking_hints.json) add
    #     `installed_via` + method data for the apps where we've
    #     hand-verified how to detect the installed version.
    # Together the frontend can pre-fill the full advanced form when
    # both are present, so the user's manual burden shrinks.
    tracking = _merge_tracking_hints(slug) if slug else None

    # Legacy-layout resolution: when a curated hint declares
    # `file_fallbacks`, probe the CT and switch to whichever candidate
    # actually exists. Sidecar entry the user saves therefore points at
    # the file this specific install produced, not the "modern" path
    # the audit assumed. Fallback list is stripped from the returned
    # suggestion so the frontend never sees candidate arrays.
    if tracking:
        _resolve_file_candidate(vmid, tracking)

    # Name suggestion: prefer the catalog's `name` (nicer display) but
    # keep the raw slug metadata as fallback for older entries.
    catalog = _catalog_lookup(slug) if slug else None
    name_sug = (catalog or {}).get("name") or meta.get("name")

    # Logo URL priority: curated hint > catalog. The hint's logo may
    # be an override we set for a mis-detected slug; the catalog is
    # the broad fallback (~735 apps in helpers_cache).
    hint_dict_for_logo = _fetch_tracking_hints().get(slug) if slug else None
    logo_url = ""
    if isinstance(hint_dict_for_logo, dict):
        raw_logo = hint_dict_for_logo.get("logo")
        if isinstance(raw_logo, str) and raw_logo.startswith(("http://", "https://")):
            logo_url = raw_logo
    if not logo_url and catalog:
        raw_logo = catalog.get("logo")
        if isinstance(raw_logo, str) and raw_logo.startswith(("http://", "https://")):
            logo_url = raw_logo

    # Default ports for the editor pre-fill. Priority is:
    #   1. Curated hint's `default_ports` (list, may hold several) —
    #      lets us encode multi-port apps like AdGuard (setup+DNS)
    #      or NPM (81 admin, 80/443 proxy).
    #   2. Catalog's `port` (single) — fallback for slugs we haven't
    #      curated but community-scripts has a port for.
    hint_dict = _fetch_tracking_hints().get(slug) if slug else None
    default_ports: list = []
    if isinstance(hint_dict, dict):
        raw = hint_dict.get("default_ports")
        if isinstance(raw, list):
            for p in raw:
                try:
                    n = int(p)
                    if 1 <= n <= 65535:
                        default_ports.append(n)
                except (TypeError, ValueError):
                    continue
    if not default_ports and catalog:
        raw = catalog.get("default_port")
        try:
            n = int(raw)
            if 1 <= n <= 65535:
                default_ports.append(n)
        except (TypeError, ValueError):
            pass

    # Multi-app detection: probe every hint slug against the CT and
    # surface each installed app the primary detection didn't already
    # cover. This lets an "AgentDVR + Docker" CT show both apps as
    # detected so the user just clicks Register per app instead of
    # typing name/logo/repo by hand.
    #
    # Primary slug is excluded from extras so we don't offer it twice.
    hints_map = _fetch_tracking_hints() or {}
    detected_map = _probe_detected_apps_map(vmid) if hints_map else {}
    # Docker-child suppression: when the user has already registered
    # Docker on this CT, they've chosen to manage every containerised
    # app under that single Docker entry (web links + notes). Any hint
    # whose only matching detector is docker_label/docker_exec would
    # therefore appear as a duplicate — the paperless container that
    # already runs inside Docker gets offered again as "Paperless-ngx
    # detected". Skip those extras so the panel stays honest about
    # what lives natively on the CT vs. inside Docker.
    sidecar_apps = (_read_sidecar(vmid) or {}).get("apps") or []
    docker_registered = any(
        (a.get("helper_slug") == "docker") or (a.get("installed_via") == "binary" and (a.get("binary_path") or "").endswith("/docker"))
        for a in sidecar_apps
    )
    extras: list = []
    for det_slug in sorted(detected_map):
        if slug and det_slug == slug:
            continue
        det_hint = hints_map.get(det_slug) or {}
        det_catalog = _catalog_lookup(det_slug) or {}
        # Use the DETECTOR THAT ACTUALLY MATCHED on this CT, not the
        # hint's primary. Ex: paperless-ngx hint has primary
        # docker_label + alt file; on a native install the file
        # matched → we build tracking_suggestion around that file
        # detector so the form pre-fills the RIGHT method.
        matched_detectors = detected_map.get(det_slug) or []
        working = matched_detectors[0] if matched_detectors else None
        # Skip docker-hosted extras when Docker is registered on the CT.
        # We check ALL matched detectors — if EVERY match is a docker
        # method, this app is exclusively running inside Docker and
        # doesn't warrant a separate registration. If ANY non-docker
        # detector also matched (native install alongside a container),
        # keep the extra so the user can register the native side.
        if docker_registered and matched_detectors:
            all_docker = all(
                d.get("installed_via") in ("docker_label", "docker_exec")
                for d in matched_detectors
            )
            if all_docker:
                continue
        det_tracking = dict(det_hint)
        if working:
            # Overwrite the primary-detector fields with what actually
            # works here, so the user sees the correct method + target
            # in the form. Fields common to all methods (repo,
            # tag_regex, github_source, installed_regex) come from the
            # hint's primary and stay put.
            for k in _DETECTOR_FIELDS + ("installed_via",):
                det_tracking.pop(k, None)
            for k, v in working.items():
                det_tracking[k] = v
        _resolve_file_candidate(vmid, det_tracking)
        # Strip fields the frontend doesn't need in the compact chip
        det_tracking.pop("file_fallbacks", None)
        det_tracking.pop("alt_detectors", None)
        # Name: catalog display first, then slug titlecased fallback
        det_name = det_catalog.get("name") or det_hint.get("name") or det_slug
        # Logo: hint > catalog
        det_logo = ""
        if isinstance(det_hint.get("logo"), str) and det_hint["logo"].startswith(("http://", "https://")):
            det_logo = det_hint["logo"]
        elif isinstance(det_catalog.get("logo"), str) and det_catalog["logo"].startswith(("http://", "https://")):
            det_logo = det_catalog["logo"]
        # default_ports: hint list > catalog single
        det_ports: list = []
        raw_ports = det_hint.get("default_ports")
        if isinstance(raw_ports, list):
            for p in raw_ports:
                try:
                    n = int(p)
                    if 1 <= n <= 65535:
                        det_ports.append(n)
                except (TypeError, ValueError):
                    continue
        if not det_ports and det_catalog.get("default_port"):
            try:
                n = int(det_catalog["default_port"])
                if 1 <= n <= 65535:
                    det_ports.append(n)
            except (TypeError, ValueError):
                pass
        extras.append({
            "slug": det_slug,
            "name": det_name,
            "logo_url": det_logo or None,
            "default_ports": det_ports,
            "tracking_suggestion": det_tracking,
        })

    return {
        "name_suggestion": name_sug,
        "helper_slug": slug,
        "port_suggestions": ports,
        "web_path_hint": web_hint,
        "tracking_suggestion": tracking,
        "default_ports": default_ports,
        "logo_url": logo_url or None,
        "extras": extras,
    }
