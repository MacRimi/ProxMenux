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
import copy
import concurrent.futures
import hashlib
import json
import os
import re
import signal
import shlex
import socket
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
_DETECTOR_FIELDS = (
    "package", "file_path", "file_regex", "binary_path", "binary_args",
    "python_path", "distribution", "container_name", "label",
    "command_argv", "installed_version",
)
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
_SCHEDULE_TARGET_ID_RE = re.compile(
    r"^(?:os|apps|app:[A-Za-z0-9_-]{1,64}|docker-engine|docker-(?:compose|container):[A-Za-z0-9][A-Za-z0-9_.-]{0,127}|docker-unit:[a-f0-9]{20})$"
)
_BULK_TARGET_ID_RE = re.compile(
    r"^(?:os|app:[A-Za-z0-9_-]{1,64}|docker-engine|docker-unit:[a-f0-9]{20})$"
)
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
_DOCKER_COMPOSE_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

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
# Runtime-verified detector overrides ship with the AppImage.  Unlike the
# regular catalog, they are deliberately not fetched from main: an installed
# Monitor may otherwise download an older catalog entry that resurrects a
# stale helper marker over a detector verified on a real container.
_RUNTIME_VERIFIED_OVERRIDES_BUNDLED = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "runtime_verified_overrides.json",
)
_tracking_hints_lock = threading.RLock()
_tracking_hints_cache: Optional[dict] = None
_tracking_hints_ts: float = 0.0

# Docker Hub tag previews are requested while the user edits a form.
# Cache the raw repository tag list (not the regex result) so changing
# filters does not create another external request.  Sixty seconds is
# enough to absorb typing bursts while still feeling live.
_DOCKER_HUB_TAG_CACHE_TTL_SEC = 60
_DOCKER_HUB_TAG_PREVIEW_LIMIT = 5
_DEFAULT_DOCKER_HUB_TAG_REGEX = (
    r"(?i)^v?(\d+\.\d+\.\d+(?:[-+._][0-9A-Za-z.-]+)?)$"
)
_MOVING_DOCKER_TAGS = {
    "latest", "main", "master", "edge", "stable", "nightly",
    "develop", "dev", "rolling", "lts",
}
_docker_hub_tag_cache_lock = threading.RLock()
_docker_hub_tag_cache: dict[str, dict[str, Any]] = {}

# Docker image inventory is deliberately separate from App Watch.  The
# Docker engine version and the applications delivered by its images have
# different lifecycles: updating docker-ce does not update a Portainer or
# LinuxServer image.  Inventory checks are read-only (docker image ls +
# registry manifest HEAD), cached only in process memory, and never
# pull/recreate anything. Do not create runtime files outside ProxMenux's
# owned application directory just to preserve this derived inventory.
# Docker registry drift follows the same daily rolling check as registered
# application releases.  Opening the Updates tab reads this in-memory value;
# only the daily collector, an explicit user check or a completed update forces
# a new registry comparison.
_DOCKER_INVENTORY_TTL_SEC = 24 * 3600
_DOCKER_REGISTRY_TIMEOUT_SEC = 8
_DOCKER_MAX_IMAGES = 50
_DOCKER_MANIFEST_ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
))
# Reading the remote image config is content-addressed: every document is
# requested BY DIGEST and verified against it, so the answer cannot be
# swapped for another image. A digest never changes content, so the cache
# has no TTL — only a bound.
_DOCKER_REMOTE_CONFIG_MAX_BYTES = 1 << 20
_DOCKER_REMOTE_CONFIG_CACHE_MAX = 500
_DOCKER_INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
_DOCKER_IMAGE_CONFIG_MEDIA_TYPES = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}
_docker_remote_config_lock = threading.RLock()
_docker_remote_config_cache: dict[tuple, dict] = {}
_docker_remote_config_flights = [threading.Lock() for _ in range(16)]
# Optional labels must never hold up the usable local/digest inventory.
_docker_metadata_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
_docker_metadata_slots = threading.BoundedSemaphore(64)
_docker_metadata_context = threading.local()
_docker_slug_index_cache = (None, {})
_docker_inventory_lock = threading.RLock()
_docker_inventory_cache: dict[str, dict] = {}


def _load_bundled_hints() -> dict:
    try:
        with open(_TRACKING_HINTS_BUNDLED) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_runtime_verified_overrides() -> dict:
    """Load optional live-detector promotions packaged with the Monitor."""
    try:
        with open(_RUNTIME_VERIFIED_OVERRIDES_BUNDLED) as f:
            data = json.load(f)
        apps = data.get("apps") if isinstance(data, dict) else None
        return apps if isinstance(apps, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _is_helper_marker_detector(detector: dict) -> bool:
    return (
        detector.get("installed_via") == "file"
        and bool(re.fullmatch(
            r"/root/\.[A-Za-z0-9_.-]+", str(detector.get("file_path") or "")
        ))
    )


def _apply_runtime_verified_overrides(hints: dict, overrides: dict) -> dict:
    """Promote packaged, runtime-proven detectors over a remote catalog.

    The remote catalog remains the normal no-rebuild update channel.  Entries
    marked non-operational are skipped; all other runtime-verified entries
    replace detector fields. Presentation metadata and non-conflicting
    fallbacks remain intact. A legacy ``/root/.<app>`` primary is retained as
    a fallback so older helper layouts do not lose their only version source.
    """
    result = {
        slug: dict(hint) for slug, hint in (hints or {}).items()
        if isinstance(slug, str) and isinstance(hint, dict)
    }
    for slug, spec in (overrides or {}).items():
        if not isinstance(slug, str) or not isinstance(spec, dict):
            continue
        detector = spec.get("detector")
        if not bool(spec.get("operational", True)) or not isinstance(detector, dict):
            continue
        method = detector.get("installed_via")
        if method not in _VALID_METHODS:
            continue

        current = dict(result.get(slug) or {})
        marker_fallbacks = []
        if _is_helper_marker_detector(current):
            marker_fallbacks.append({
                "path": current["file_path"],
                "regex": current.get("file_regex") or current.get("installed_regex") or "",
                "source": "helper_marker",
            })

        # Detector and upstream fields must be replaced as one coherent set;
        # retaining e.g. an old file_path next to a binary detector is what
        # previously kept stale helper marker versions alive.
        for key in _DETECTOR_FIELDS + (
            "installed_via", "repo", "github_source", "tag_regex",
            "installed_regex", "upstream_type", "upstream_url",
            "upstream_json_path", "docker_image",
        ):
            current.pop(key, None)
        current.update(detector)

        fallbacks = []
        for candidate in (current.get("file_fallbacks") or []):
            if isinstance(candidate, dict) and candidate.get("path"):
                fallbacks.append(dict(candidate))
        spec_fallbacks = spec.get("file_fallbacks")
        if not isinstance(spec_fallbacks, list):
            spec_fallbacks = []
        for candidate in spec_fallbacks + marker_fallbacks:
            if isinstance(candidate, dict) and candidate.get("path"):
                fallbacks.append(dict(candidate))
        if fallbacks:
            unique_fallbacks = []
            known_paths = set()
            for candidate in fallbacks:
                path = candidate.get("path")
                if path in known_paths:
                    continue
                known_paths.add(path)
                unique_fallbacks.append(candidate)
            current["file_fallbacks"] = unique_fallbacks

        # These optional fields are explicitly allowed to update runtime
        # behavior too, while ordinary catalog presentation remains untouched.
        for key in ("alt_detectors", "default_ports", "logo", "website"):
            if key in spec:
                current[key] = spec[key]
        result[slug] = current
    return result


def _fetch_tracking_hints() -> dict:
    """Return the curated tracking-hint map (slug → hint dict).

    Fetch order: memory cache (fresh) → GitHub raw merged with the bundled
    catalog → on-disk cache → bundled JSON.  Packaged runtime-verified
    overrides are then applied to every source.  They prevent a stale remote
    catalog from downgrading a detector already proven live, while all normal
    catalog updates continue to arrive without an AppImage rebuild. Never
    raises — a total failure returns an empty dict so callers can just
    ``.get(slug)``.
    """
    global _tracking_hints_cache, _tracking_hints_ts
    with _tracking_hints_lock:
        now = time.time()
        if _tracking_hints_cache is not None and (now - _tracking_hints_ts) < _TRACKING_HINTS_TTL:
            return _tracking_hints_cache
        bundled = _load_bundled_hints()
        runtime_overrides = _load_runtime_verified_overrides()
        try:
            req = urllib.request.Request(
                _TRACKING_HINTS_URL,
                headers={"User-Agent": "ProxMenux-Monitor"},
            )
            with urllib.request.urlopen(req, timeout=_TRACKING_HINTS_HTTP_TIMEOUT) as r:
                raw = json.loads(r.read().decode("utf-8"))
            remote = raw if isinstance(raw, dict) else {}
            if len(remote) >= len(bundled):
                hints = dict(bundled)
                hints.update(remote)
            else:
                hints = dict(remote)
                hints.update(bundled)
            hints = _apply_runtime_verified_overrides(hints, runtime_overrides)
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
                _tracking_hints_cache = _apply_runtime_verified_overrides(
                    disk.get("hints") or {}, runtime_overrides
                )
                _tracking_hints_ts = float(disk.get("ts") or 0)
                return _tracking_hints_cache
            except (OSError, json.JSONDecodeError):
                _tracking_hints_cache = _apply_runtime_verified_overrides(
                    bundled, runtime_overrides
                )
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
# Web Link category — free-text label the user picks from the presets
# built from helpers_cache.category_names, or types freely. Keep the
# charset permissive enough for community-scripts labels ("Media &
# Streaming", "*Arr Suite", "AI / Coding & Dev-Tools").
_CATEGORY_RE = re.compile(r"^[\w\s&/,.\-*+()]{1,60}$", re.UNICODE)
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


_sidecar_cache: dict = {}
_sidecar_cache_lock = threading.RLock()
_sidecar_revision = 0


def _sidecar_signature(stat) -> tuple:
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)


def _publish_sidecar_snapshot(path: str, data: dict, signature: tuple) -> dict:
    """Publish under _sidecar_cache_lock; revisions exist only in memory."""
    global _sidecar_revision
    _sidecar_revision = max(_sidecar_revision + 1, int(time.time() * 1000))
    snapshot = _migrate_legacy(copy.deepcopy(data))
    _migrate_update_methods(snapshot)
    snapshot['_revision'] = _sidecar_revision
    _sidecar_cache[path] = (signature, snapshot)
    return snapshot


def _read_sidecar(vmid) -> Optional[dict]:
    path = _sidecar_path(vmid)
    with _sidecar_cache_lock:
        try:
            signature = _sidecar_signature(os.stat(path))
            cached = _sidecar_cache.get(path)
            if cached is not None and cached[0] == signature:
                return copy.deepcopy(cached[1])
            with open(path) as f:
                data = json.load(f)
                signature = _sidecar_signature(os.fstat(f.fileno()))
            if isinstance(data, dict):
                snapshot = _publish_sidecar_snapshot(path, data, signature)
                return copy.deepcopy(snapshot)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        _sidecar_cache.pop(path, None)
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


def _migrate_update_methods(data: dict) -> None:
    """Preserve saved choices, never turn detection into updater consent.

    Old commands and explicitly saved bulk/enabled schedule selections keep
    working. New registrations always carry update_method, so an old `apps`
    wildcard cannot opt newly registered applications into Helper-Scripts.
    Projection is read-only; the next normal sidecar write persists it.
    """
    schedule = data.get("schedule") or {}
    selected = set((data.get("bulk_update") or {}).get("targets") or [])
    if schedule.get("enabled"):
        targets = schedule.get("targets")
        if not targets:
            targets = ["apps"] if schedule.get("target", "both") in ("app", "both") else []
        selected.update(targets)
    for app in data.get("apps") or []:
        if "update_method" in app:
            continue
        if (app.get("update_command") or "").strip():
            app["update_method"] = "custom"
        elif (app.get("helper_slug") and app.get("helper_slug") not in ("docker", "adguard")
              and ("apps" in selected or f"app:{app.get('id')}" in selected)):
            app["update_method"] = "helper"
        else:
            app["update_method"] = "none"


def protect_download_update_command(command: str) -> str:
    """Guard the historical downloaded-shell launcher at execution time.

    Only a literal, standalone wget/curl + shell -c launcher is recognised.
    Other custom commands are returned byte-for-byte, never evaluated here.
    Saved configuration is not rewritten. Grouping preserves && composition.
    """
    launcher = re.fullmatch(
        r'''\s*(?P<prefix>PHS_SILENT=[01][ \t]+)?(?P<shell>(?:/bin/|/usr/bin/)?(?:bash|sh))[ \t]+-c[ \t]+"\$\((?P<fetch>[^\n]+)\)"\s*''',
        command,
    )
    if not launcher:
        return command
    fetch = re.fullmatch(
        r'''(?P<tool>wget|curl)[ \t]+(?P<flags>-qLO[ \t]+-|-qO[ \t]+-|-qO-|-fsSL|-fSL)[ \t]+(?P<quote>['"]?)(?P<url>https?://[A-Za-z0-9_./:%?=&+#@,~!;-]+)(?P=quote)''',
        launcher['fetch'],
    )
    if not fetch:
        return command
    # Require the original shell token to be literal too. Unquoted shell
    # operators or glob patterns are not this known launcher format.
    if not fetch['quote'] and any(c in fetch['url'] for c in '&;?'):
        return command
    flags = fetch['flags'].split()
    if ((fetch['tool'] == 'wget' and flags not in (['-qLO', '-'], ['-qO', '-'], ['-qO-']))
            or (fetch['tool'] == 'curl' and flags not in (['-fsSL'], ['-fSL']))):
        return command
    fetch_command = shlex.join([fetch['tool'], *flags, fetch['url']])
    invocation = (launcher['prefix'] or '') + launcher['shell']
    return (
        '(\n'
        f'_proxmenux_updater=$({fetch_command}) || {{\n'
        '  echo "ERROR: updater download failed; nothing was executed." >&2\n'
        '  exit 1\n'
        '}\n'
        '[ -n "$_proxmenux_updater" ] || {\n'
        '  echo "ERROR: downloaded updater is empty; nothing was executed." >&2\n'
        '  exit 1\n'
        '}\n'
        f'{invocation} -c "$_proxmenux_updater"\n'
        ')'
    )


def helper_update_selected(vmid, slug: str, targets=None) -> bool:
    """Execution-time consent check, shared with the shell runner.

    Wrapper provenance is independently verified by the caller. Duplicate
    registrations with different choices must not run a CT-wide helper.
    """
    apps = (_read_sidecar(vmid) or {}).get("apps") or []
    matching = [app for app in apps if app.get("helper_slug") == slug
                and not app.get("managed_oci_app_id")]
    if not matching or any(app.get("update_method") != "helper"
                           or (app.get("update_command") or "").strip() for app in matching):
        return False
    if targets is None or "apps" in targets:
        return True
    return any(f"app:{app.get('id')}" in targets for app in matching)


def _write_sidecar(vmid, data: dict) -> bool:
    _migrate_update_methods(data)
    _ensure_dir()
    path = _sidecar_path(vmid)
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w") as f:
            json.dump({k: v for k, v in data.items() if k != '_revision'}, f, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        with _sidecar_cache_lock:
            os.replace(tmp, path)
            snapshot = _publish_sidecar_snapshot(path, data, _sidecar_signature(os.stat(path)))
            data['_revision'] = snapshot['_revision']
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
        # Per-link category — optional free-text label the user picks
        # from the presets sourced from helpers_cache.category_names.
        # Powers the Apps dashboard (filter/group by category).
        category = (item.get("category") or "").strip()
        if category:
            if not _CATEGORY_RE.match(category):
                return _err(f"ports[{i}].category has invalid characters or is too long")
            entry["category"] = category
        # Optional custom URL — takes precedence over the ip:port
        # composition when present. Used for apps reached through a
        # reverse-proxy domain (e.g. https://vault.example.com) so the
        # Apps dashboard opens the public URL instead of the internal
        # ip:port. Same http(s) allow-list as the app-level logo.
        custom_url = (item.get("custom_url") or "").strip()
        if custom_url:
            if not _LOGO_URL_RE.match(custom_url):
                return _err(f"ports[{i}].custom_url must be an http(s) URL (max 512 chars)")
            entry["custom_url"] = custom_url
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
    targets_raw = payload.get("targets")
    if targets_raw is None:
        # Backward-compatible migration for schedules saved before the
        # per-app selector existed. `apps` means every eligible registered
        # app and is expanded by the runner at execution time.
        targets = (["os"] if target in ("os", "both") else []) + (["apps"] if target in ("app", "both") else [])
    else:
        if not isinstance(targets_raw, list):
            return _err("targets must be a JSON array")
        targets = []
        for value in targets_raw:
            item = str(value or "").strip()
            if not _SCHEDULE_TARGET_ID_RE.match(item):
                return _err(f"invalid schedule target: {item[:80]}")
            if item not in targets:
                targets.append(item)
        if len(targets) > 128:
            return _err("targets may contain at most 128 items")
    if enabled and not targets:
        return _err("at least one schedule target is required when enabled")
    target = "both" if "os" in targets and any(item != "os" for item in targets) else ("os" if targets == ["os"] else "app")
    backup = bool(payload.get("backup"))
    restart = bool(payload.get("restart"))
    release_delay_raw = payload.get("release_delay_days", 0)
    try:
        release_delay_days = int(release_delay_raw)
    except (TypeError, ValueError):
        return _err("release_delay_days must be an integer from 0 to 365")
    if release_delay_days < 0 or release_delay_days > 365:
        return _err("release_delay_days must be an integer from 0 to 365")
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
        "targets": targets,
        "backup": backup,
        "backup_storage": backup_storage,
        "restart": restart,
        "release_delay_days": release_delay_days,
    }
    # Preserve `last_run_at` / `last_run_status` when the caller sent
    # them (typical when the scheduler writes back after firing);
    # otherwise leave the field unset so persisted values survive.
    for k in ("last_run_at", "last_run_status", "last_run_target", "last_run_reason"):
        v = payload.get(k)
        if v is not None:
            out[k] = v
    return True, out


def validate_bulk_update(payload: Any) -> tuple[bool, Any]:
    """Validate the reusable manual bulk-update selection.

    This configuration is deliberately independent from ``schedule``:
    changing what a manual bulk run does must never rewrite the operator's
    cron automation.  ``os`` is mandatory and at least one additional,
    explicit update method must be selected.
    """
    if not isinstance(payload, dict):
        return _err("bulk_update must be a JSON object")
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, list):
        return _err("targets must be a JSON array")
    targets: list[str] = []
    for value in raw_targets:
        item = str(value or "").strip()
        if not _BULK_TARGET_ID_RE.match(item):
            return _err(f"invalid bulk update target: {item[:80]}")
        if item not in targets:
            targets.append(item)
    if len(targets) > 128:
        return _err("targets may contain at most 128 items")
    if "os" not in targets:
        return _err("the OS target is required for a bulk update")
    if not any(item != "os" for item in targets):
        return _err("at least one application target is required for a bulk update")
    return True, {"targets": ["os", *sorted(item for item in targets if item != "os")]}


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

    # Optional update delegation. An application running inside Docker is a
    # real application — it has a name, a logo, links and an installed
    # version — but it is not updated on its own: the update is a pull and a
    # recreate of the image it comes from, which the Docker inventory already
    # knows how to do. Marking it here keeps ONE update path for one fact:
    # this app reports its identity and its installed version, and the image
    # row reports whether there is a new one. Upstream fields are rejected
    # rather than stripped, so nobody registers an app that silently checks
    # GitHub behind a delegation that says it will not.
    uv = (payload.get("update_via") or "").strip().lower()
    if uv:
        if uv != "docker":
            return _err("update_via only accepts 'docker'")
        if method not in ("docker_label", "docker_exec"):
            return _err("update_via=docker requires a docker_label or docker_exec detector")
        for field in ("repo", "upstream_type", "upstream_url", "docker_image"):
            if (payload.get(field) or "").strip():
                return _err(f"update_via=docker cannot be combined with {field}")
        conf["update_via"] = uv

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
            # A custom command is the application updater. It always
            # replaces /usr/bin/update for that same app. Ignore legacy
            # two-step strategy payloads and normalize them on write.
            conf["update_strategy"] = "custom_override"

    method = payload.get("update_method", "custom" if conf.get("update_command") else "none")
    if method not in ("none", "helper", "custom"):
        return _err("update_method must be none, helper or custom")
    if method == "custom" and not conf.get("update_command"):
        return _err("update_command is required for update_method=custom")
    if method != "custom" and conf.get("update_command"):
        return _err("update_command is only allowed for update_method=custom")
    if method == "helper" and (not hs or hs in ("docker", "adguard")):
        return _err("a supported helper_slug is required for update_method=helper")
    conf["update_method"] = method
    if conf.get("update_via") == "docker" and method != "none":
        return _err("Docker-delegated apps update through their image, not a separate app updater")

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

    # Optional per-app switch for the CT's aggregate updates badge.
    # Default is False (include). Set to True when the user knowingly
    # keeps a specific version (e.g. qBittorrent pinned to the version
    # their private tracker requires) and doesn't want the LXC list
    # badge blinking about an "available" update that doesn't apply to
    # them. Independent from `notifications_enabled` on purpose — a
    # user may still want the outbound notification and just hide the
    # counter, or the reverse. The App tab itself always shows the
    # real state (purple update signal, editor version fields).
    efb = payload.get("exclude_from_badge")
    if efb is not None:
        conf["exclude_from_badge"] = bool(efb)

    return True, conf


# ── Version detection: installed side ──────────────────────────────

def _pct_exec(vmid, argv: list[str], timeout: int = _PROBE_TIMEOUT_SEC) -> tuple[int, str, str]:
    """Wrapper around ``pct exec`` argv-style — NEVER through sh -c.

    ``subprocess.run(timeout=...)`` only kills the immediate ``pct`` process.
    A command inside the CT can retain the captured stdout/stderr pipes, which
    makes Python wait for that command long after the advertised timeout. This
    is especially visible while a restored CT is waiting for
    ``network-online.target``: ``docker version`` used to keep a request open
    for five minutes despite an eight-second timeout. Run ``pct`` in its own
    process group and terminate the complete local execution tree so the
    deadline is real.
    """
    cmd = [_PCT_BIN, "exec", str(vmid), "--"] + argv
    process: Optional[subprocess.Popen[str]] = None
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout or "", stderr or ""
    except subprocess.TimeoutExpired:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    process.kill()
                except (ProcessLookupError, OSError):
                    pass
            try:
                process.communicate(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                pass
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
    Version None + error None is reserved for configurations without
    an installed-version method.  A configured probe that runs but
    does not match its regex returns an explicit error; otherwise the
    editor cannot distinguish a bad regex from an unconfigured app."""
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
        version = _extract_version(out, pattern)
        if not version:
            return None, "no version matched in dpkg output"
        return version, None

    if method == "apk":
        rc, out, err = _pct_exec(vmid, ["apk", "info", "-v", config["package"]])
        if rc != 0:
            return None, (err or out).strip()[:200] or "apk info failed"
        version = _extract_version(out, pattern)
        if not version:
            return None, "no version matched in apk output"
        return version, None

    if method == "file":
        rc, out, err = _pct_exec(vmid, ["cat", config["file_path"]])
        if rc != 0:
            return None, (err or "").strip()[:200] or f"could not read {config['file_path']}"
        version = _extract_version(out, config["file_regex"])
        if not version:
            return None, f"file_regex did not match {config['file_path']}"
        return version, None

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
        version = _extract_version(out, pattern)
        if not version:
            return None, "no version matched in Python distribution output"
        return version, None

    if method == "docker_label":
        fmt = '{{index .Config.Labels "' + config["label"] + '"}}'
        if config.get('update_via') == 'docker':
            # A protected recreation preserves user container labels. Those
            # can include the previous image's version, so delegated apps
            # must read the immutable image actually used by the container.
            rc, image_id, err = _pct_exec(vmid, ["docker", "inspect", "--format", "{{.Image}}", config["container_name"]])
            image_id = image_id.strip()
            if rc != 0 or not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id):
                return None, "could not resolve the container's installed image"
            argv = ["docker", "image", "inspect", "--format", fmt, image_id]
        else:
            argv = ["docker", "inspect", "--format", fmt, config["container_name"]]
        rc, out, err = _pct_exec(vmid, argv)
        if rc != 0:
            return None, (err or out).strip()[:200] or "docker inspect failed"
        text = (out or "").strip()
        if not text or text == "<no value>":
            return None, f"container has no {config['label']!r} label"
        # Reject mutable tags disguised as versions.
        if text.lower() in ("latest", "stable", "main", "master", "edge"):
            return None, f"docker label reports {text!r} (mutable tag, not a version)"
        version = _extract_version(text, pattern)
        if not version:
            return None, "no version matched in docker label output"
        return version, None

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


def _detector_probe_config(hint: dict, detector: dict) -> dict:
    """Build a complete probe from one detector in a catalog hint.

    Alternative detectors intentionally contain only method-specific fields.
    Local/upstream regexes and upstream metadata live on the primary hint, so
    they must be inherited before calling ``detect_installed_version``.
    """
    probe = {"installed_via": detector.get("installed_via")}
    for key in _DETECTOR_FIELDS:
        if key in detector:
            probe[key] = detector[key]
    for key in ("installed_regex", "tag_regex"):
        if key in detector:
            probe[key] = detector[key]
        elif key in hint:
            probe[key] = hint[key]
    return probe


def _ordered_hint_detectors(hint: dict):
    """Yield primary, cross-method alternatives and file fallbacks.

    ``/root/.<slug>`` is the maintained version contract for modern
    community-scripts installs. It is reported as ``helper_marker`` so the UI
    can distinguish it from canonical application/package probes; legacy and
    manual installs continue through the other detectors.
    """
    if not isinstance(hint, dict):
        return
    primary = {"installed_via": hint.get("installed_via")}
    for key in _DETECTOR_FIELDS:
        if key in hint:
            primary[key] = hint[key]
    if primary.get("installed_via"):
        primary_source = (
            "helper_marker"
            if primary.get("installed_via") == "file"
            and re.fullmatch(r"/root/\.[A-Za-z0-9_.-]+", str(primary.get("file_path") or ""))
            else "primary"
        )
        yield primary, primary_source
    for alt in hint.get("alt_detectors") or []:
        if isinstance(alt, dict) and alt.get("installed_via"):
            yield alt, "alternative"
    for fallback in hint.get("file_fallbacks") or []:
        if not isinstance(fallback, dict) or not fallback.get("path"):
            continue
        detector = {
            "installed_via": "file",
            "file_path": fallback["path"],
            "file_regex": fallback.get("regex") or hint.get("file_regex", ""),
        }
        fallback_source = (
            "helper_marker"
            if fallback.get("source") == "helper_marker"
            or re.fullmatch(r"/root/\.[A-Za-z0-9_.-]+", str(fallback.get("path") or ""))
            else "legacy_fallback"
        )
        yield detector, fallback_source


def _select_working_hint_detector(vmid, hint: dict) -> tuple[dict, Optional[str], str, Optional[str]]:
    """Return the first detector that produces a parseable real version.

    Presence alone is insufficient: a stale file, similarly named package or
    helper marker can exist without representing the running app.  The return
    tuple is ``(tracking_config, version, source, last_error)``.  If no probe
    succeeds the unchanged primary hint is returned as a catalog candidate,
    with source ``candidate`` so the UI can stay transparent.
    """
    original = dict(hint) if isinstance(hint, dict) else {}
    last_error: Optional[str] = None
    for detector, source in _ordered_hint_detectors(original):
        probe = _detector_probe_config(original, detector)
        try:
            version, error = detect_installed_version(vmid, probe)
        except (KeyError, TypeError, ValueError) as exc:
            version, error = None, str(exc)
        if version:
            selected = dict(original)
            for key in _DETECTOR_FIELDS + ("installed_via",):
                selected.pop(key, None)
            selected.update(detector)
            selected["detected_version"] = version
            selected["detector_source"] = source
            selected["detector_verified"] = True
            return selected, version, source, None
        if error:
            last_error = error
    original["detector_source"] = "candidate"
    original["detector_verified"] = False
    if last_error:
        original["detector_error"] = last_error[:200]
    return original, None, "candidate", last_error


# ── Version detection: upstream side ───────────────────────────────

def _github_pat() -> Optional[str]:
    try:
        from notification_manager import notification_manager
        # The notification manager owns the shared encrypted settings store.
        # During very early calls its runtime cache may not have been loaded
        # yet, so initialise it before reading the optional GitHub token.
        if not notification_manager._config:
            notification_manager._load_config()
        pat = notification_manager._config.get("github_pat")
        return pat.strip() if isinstance(pat, str) and pat.strip() else None
    except Exception:
        return None


def fetch_latest_upstream(config: dict) -> tuple[Optional[str], Optional[str]]:
    """Dispatch to the appropriate upstream fetcher based on
    ``upstream_type``. Falls back to github for legacy sidecars that
    only set ``repo``. Returns (version, error) — version None + error
    None means the app has no upstream configured (skip the check)."""
    version, error, _published_at = fetch_latest_upstream_details(config)
    return version, error


def fetch_latest_upstream_details(config: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Like :func:`fetch_latest_upstream`, plus the upstream publish date.

    The date is intentionally optional.  GitHub releases expose a reliable
    ``published_at`` value; tag lists and arbitrary JSON endpoints often do
    not.  Scheduled release holds treat an unavailable date conservatively.
    """
    upstream_type = config.get("upstream_type")
    # Legacy sidecars: repo set, upstream_type not.
    if not upstream_type and config.get("repo"):
        upstream_type = "github"
    if not upstream_type:
        return None, None, None
    if upstream_type == "github":
        return _fetch_github_latest_details(config)
    if upstream_type == "http_json":
        version, error = _fetch_http_json_latest(config)
        return version, error, None
    if upstream_type == "docker_hub":
        version, error = _fetch_docker_hub_latest(config)
        return version, error, None
    return None, f"unknown upstream_type: {upstream_type}", None


def _fetch_github_latest(config: dict) -> tuple[Optional[str], Optional[str]]:
    version, error, _published_at = _fetch_github_latest_details(config)
    return version, error


def _fetch_github_latest_details(config: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    repo = config.get("repo")
    if not repo:
        return None, None, None
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
            return None, f"{repo}: not found", None
        if e.code == 403:
            remaining = e.headers.get("X-RateLimit-Remaining", "1")
            if remaining == "0":
                return None, "github rate limited — configure a PAT in Settings → GitHub API", None
            return None, "github rejected the request (403)", None
        return None, f"github error {e.code}", None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"network error: {e}", None

    pattern = config.get("tag_regex") or r"v?(\d+\.\d+\.\d+)"
    tag = None
    published_at = None
    if source == "releases" and isinstance(payload, dict):
        tag = payload.get("tag_name") or payload.get("name")
        published_at = payload.get("published_at") or payload.get("created_at")
    elif source == "tags" and isinstance(payload, list):
        for entry in payload:
            candidate = entry.get("name") if isinstance(entry, dict) else None
            if candidate:
                v = _extract_version(candidate, pattern)
                if v:
                    tag = candidate
                    break

    if not tag:
        return None, "no tag / release name in response", None
    v = _extract_version(tag, pattern)
    if not v:
        return None, f"tag_regex did not match '{tag}'", None
    return v, None, published_at if isinstance(published_at, str) else None


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


def _docker_hub_tag_records(image: str) -> tuple[list[dict], Optional[str]]:
    """Fetch recent Docker Hub tag names and their immutable digests.

    Keeping the digest lets the Docker inventory resolve a moving tag such as
    ``latest`` to a real version tag only when both point at the exact same
    manifest. This is deliberately stricter than selecting the numerically
    greatest tag, which could silently cross release channels or variants.
    """
    if "/" not in image:
        image = f"library/{image}"
    now = time.time()
    with _docker_hub_tag_cache_lock:
        cached = _docker_hub_tag_cache.get(image)
        if (
            cached
            and now - float(cached.get("ts") or 0) < _DOCKER_HUB_TAG_CACHE_TTL_SEC
            and isinstance(cached.get("records"), list)
        ):
            return [dict(item) for item in cached["records"] if isinstance(item, dict)], None
    url = (
        f"https://hub.docker.com/v2/repositories/{urllib.parse.quote(image, safe='/')}"
        "/tags/?page_size=100&ordering=last_updated"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "ProxMenux-Monitor", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_GITHUB_TIMEOUT_SEC) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return [], f"docker image '{image}' not found"
        if e.code == 429:
            return [], "docker hub rate limited the request"
        return [], f"docker hub error {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return [], f"network error: {e}"
    except json.JSONDecodeError as e:
        return [], f"invalid docker hub JSON: {e}"

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return [], "no tags returned by docker hub"

    records = [
        {
            "name": str(item.get("name")),
            "digest": str(item.get("digest")) if item.get("digest") else None,
        }
        for item in results
        if isinstance(item, dict) and item.get("name")
    ]
    with _docker_hub_tag_cache_lock:
        _docker_hub_tag_cache[image] = {"ts": now, "records": records}
    return records, None


def _docker_hub_tag_names(image: str) -> tuple[list[str], Optional[str]]:
    """Fetch at most 100 recent Docker Hub tag names, cached per repository."""
    records, error = _docker_hub_tag_records(image)
    if error:
        return [], error
    return [str(item["name"]) for item in records if item.get("name")], None


def _docker_tag_semver_key(tag: str) -> tuple:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", tag)
    if match:
        return (1, int(match.group(1)), int(match.group(2)), int(match.group(3)), tag)
    return (0, 0, 0, 0, tag)


_DOCKER_DISPLAY_VERSION_RE = re.compile(
    r"(?i)^v?((?:\d+\.){1,3}\d+(?:[-+._][0-9A-Za-z.-]+)?)$"
)


def _normalise_docker_display_version(value: Any) -> Optional[str]:
    """Return a display-safe version only when the whole value is versioned."""
    if not isinstance(value, (str, int, float)):
        return None
    candidate = str(value).strip()
    if not candidate or len(candidate) > 128 or candidate.lower() in _MOVING_DOCKER_TAGS:
        return None
    match = _DOCKER_DISPLAY_VERSION_RE.fullmatch(candidate)
    return match.group(1) if match else None


def _docker_version_from_labels(
    labels: dict,
    keys: tuple = ("Version", "version", "org.opencontainers.image.version"),
) -> tuple[Optional[str], Optional[str]]:
    """Resolve a version from image labels, in the caller's order of trust.

    Shared by the local image inspect and by the remote image config so both
    sides of the comparison read the same labels through the same filter.
    """
    for key in keys:
        version = _normalise_docker_display_version((labels or {}).get(key))
        if version:
            return version, f"image_label:{key}"
    return None, None


def _docker_version_from_image_inspect(parsed: dict, inspected: dict) -> tuple[Optional[str], Optional[str]]:
    """Resolve an installed image version from local, immutable evidence."""
    direct_tag = _normalise_docker_display_version(parsed.get("tag"))
    if direct_tag:
        return direct_tag, "reference_tag"

    labels = ((inspected.get("Config") or {}).get("Labels") or {})
    # Application-specific labels take precedence over OCI labels because a
    # few publishers put the base distribution version in the latter.
    version, source = _docker_version_from_labels(labels, ("Version", "version"))
    if version:
        return version, source

    # A moving tag often shares an image ID with an explicit release tag
    # already present locally (for example frigate:stable + frigate:0.17.2).
    alternate_versions: list[str] = []
    for repo_tag in inspected.get("RepoTags") or []:
        if not isinstance(repo_tag, str) or ":" not in repo_tag:
            continue
        alt_repo, alt_tag = repo_tag.rsplit(":", 1)
        alt = _parse_docker_reference(alt_repo, alt_tag)
        if not alt:
            continue
        if alt.get("registry") != parsed.get("registry") or alt.get("repository") != parsed.get("repository"):
            continue
        version = _normalise_docker_display_version(alt_tag)
        if version:
            alternate_versions.append(version)
    if alternate_versions:
        alternate_versions.sort(key=_docker_tag_semver_key, reverse=True)
        return alternate_versions[0], "local_equivalent_tag"

    return _docker_version_from_labels(labels, ("org.opencontainers.image.version",))


def _docker_hub_version_for_digest(records: list[dict], digest: Optional[str]) -> Optional[str]:
    """Find a version tag whose Docker Hub digest exactly matches ``digest``."""
    if not digest:
        return None
    versions = []
    for item in records:
        if item.get("digest") != digest:
            continue
        version = _normalise_docker_display_version(item.get("name"))
        if version:
            versions.append(version)
    if not versions:
        return None
    versions.sort(key=_docker_tag_semver_key, reverse=True)
    return versions[0]


def preview_docker_hub_tags(image: str, pattern: str | None, limit: int = _DOCKER_HUB_TAG_PREVIEW_LIMIT) -> tuple[bool, Any]:
    """Return real tags matching an editor draft without tracking a CT.

    Moving tags remain visible in the preview but are flagged because their
    update state must be determined by image digest, not version comparison.
    """
    image = (image or "").strip().lower()
    if not image or len(image) > _MAX_DOCKER_IMAGE_LEN or not _DOCKER_IMAGE_RE.match(image):
        return False, "docker_image must match Docker Hub naming (owner/name or name)"
    pattern = (pattern or "").strip() or _DEFAULT_DOCKER_HUB_TAG_REGEX
    if len(pattern) > 512:
        return False, "tag_regex exceeds 512 chars"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return False, f"tag_regex is not a valid regex: {exc}"

    tag_names, error = _docker_hub_tag_names(image)
    if error:
        return False, error
    matched = [tag for tag in tag_names if regex.search(tag)]
    matched.sort(key=_docker_tag_semver_key, reverse=True)
    entries = []
    for tag in matched[:max(1, min(int(limit), 10))]:
        entries.append({
            "tag": tag,
            "version": _extract_version(tag, pattern),
            "moving": tag.lower() in _MOVING_DOCKER_TAGS,
        })
    return True, {
        "image": image if "/" in image else f"library/{image}",
        "regex": pattern,
        "tags": entries,
        "matched_count": len(matched),
        "scanned_count": len(tag_names),
        "cached_for_seconds": _DOCKER_HUB_TAG_CACHE_TTL_SEC,
    }


def _fetch_docker_hub_latest(config: dict) -> tuple[Optional[str], Optional[str]]:
    image = config.get("docker_image")
    if not image:
        return None, None
    tag_names, error = _docker_hub_tag_names(image)
    if error:
        return None, error

    pattern = config.get("tag_regex") or _DEFAULT_DOCKER_HUB_TAG_REGEX
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return None, f"tag_regex is not a valid regex: {e}"
    tag_names = [tag for tag in tag_names if rx.search(tag)]
    if not tag_names:
        return None, "no tags matched (docker_hub)"

    versioned_tags = [tag for tag in tag_names if tag.lower() not in _MOVING_DOCKER_TAGS]
    if not versioned_tags:
        return None, "tag_regex matched only moving tags; use Docker image digest tracking"

    versioned_tags.sort(key=_docker_tag_semver_key, reverse=True)
    winner = versioned_tags[0]
    # If user set a tag_regex with capture groups, run the extraction to
    # normalise "v1.2.3" → "1.2.3" and similar.
    if pattern:
        extracted = _extract_version(winner, pattern)
        if extracted:
            return extracted, None
    return winner, None


# ── Docker image inventory ────────────────────────────────────────

def _parse_docker_reference(repository: str, tag: str) -> Optional[dict]:
    """Normalise a Docker CLI repository/tag into registry API parts."""
    repository = (repository or "").strip()
    tag = (tag or "").strip()
    if not repository or repository == "<none>" or not tag or tag == "<none>":
        return None
    first, sep, rest = repository.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        registry, path = first.lower(), rest
    else:
        registry = "docker.io"
        path = repository
    if registry in ("docker.io", "index.docker.io", "registry-1.docker.io"):
        registry = "docker.io"
        if "/" not in path:
            path = f"library/{path}"
        api_host = "registry-1.docker.io"
    else:
        api_host = registry
    if not path or any(ch in path for ch in "\x00\r\n"):
        return None
    return {
        "registry": registry,
        "api_host": api_host,
        "repository": path,
        "tag": tag,
        "reference": f"{repository}:{tag}",
    }


def _normalise_docker_container_reference(reference: str) -> str:
    """Match Docker's implicit ``latest`` tag to ``docker image ls`` rows."""
    reference = str(reference or "").strip()
    if not reference or "@" in reference:
        return reference
    final_component = reference.rsplit("/", 1)[-1]
    if ":" not in final_component:
        return f"{reference}:latest"
    return reference


def _docker_reference_identity(reference: str) -> Optional[tuple]:
    """Canonical mutable tag, not another alias sharing the same image ID."""
    reference = _normalise_docker_container_reference(reference)
    if not reference or '@' in reference or reference.startswith('sha256:'):
        return None
    repository, tag = reference.rsplit(':', 1)
    parsed = _parse_docker_reference(repository, tag)
    return (parsed['registry'], parsed['repository'], parsed['tag']) if parsed else None


def _parse_bearer_challenge(value: str) -> Optional[dict]:
    if not isinstance(value, str) or not value.lower().startswith("bearer "):
        return None
    params = {}
    for key, quoted, bare in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', value[7:]):
        params[key.lower()] = quoted or bare
    realm = params.get("realm")
    if not realm or not realm.startswith("https://"):
        return None
    return params


class _DockerNoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx instead of following it.

    urllib re-sends ``Authorization`` to the redirect target; registries hand
    blobs off to signed-URL storage that rejects a second auth mechanism, and
    the official Docker client drops the header on a host change. Following
    the hop by hand is the only way to drop it.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_docker_no_redirect_opener = urllib.request.build_opener(_DockerNoRedirect)


def _registry_bearer_token(challenge: dict) -> tuple[Optional[str], Optional[str]]:
    """Exchange a parsed ``WWW-Authenticate`` challenge for a pull token."""
    query = {
        key: challenge[key]
        for key in ("service", "scope") if challenge.get(key)
    }
    token_url = challenge["realm"]
    if query:
        token_url += ("&" if "?" in token_url else "?") + urllib.parse.urlencode(query)
    token_req = urllib.request.Request(
        token_url,
        headers={"User-Agent": "ProxMenux-Monitor", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(token_req, timeout=_docker_registry_timeout()) as response:
            body = response.read(65537)
            if len(body) > 65536:
                return None, "registry token response exceeded the size limit"
            token_payload = json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return None, f"registry HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return None, f"registry network error: {exc}"
    if not isinstance(token_payload, dict):
        return None, "registry token response was not an object"
    token = token_payload.get("token") or token_payload.get("access_token")
    if not isinstance(token, str) or not token:
        return None, "registry token response was empty"
    return token, None


def _docker_registry_timeout():
    deadline = getattr(_docker_metadata_context, 'deadline', None)
    if deadline is None:
        return _DOCKER_REGISTRY_TIMEOUT_SEC
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('registry metadata budget exhausted')
    return min(_DOCKER_REGISTRY_TIMEOUT_SEC, remaining)


def _registry_open(url: str, headers: dict, method: str, max_bytes: int):
    """One registry request. Returns (headers, body, status, location, error)."""
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with _docker_no_redirect_opener.open(req, timeout=_docker_registry_timeout()) as response:
            body = None
            if max_bytes > 0:
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    return None, None, None, None, "registry response exceeded the size limit"
            return response.headers, body, 200, None, None
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            return exc.headers, None, exc.code, exc.headers.get("Location"), None
        if exc.code == 401:
            return exc.headers, None, 401, None, None
        return None, None, exc.code, None, f"registry HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, None, None, None, f"registry network error: {exc}"


def _registry_request(url: str, headers: dict, method: str = "HEAD",
                      token: Optional[str] = None, max_bytes: int = 0,
                      follow_redirect: bool = True):
    """Registry request resolving a Bearer challenge once.

    Returns (headers, body, token, error). The token is returned so a caller
    walking manifest -> manifest -> blob pays for a single challenge.
    """
    attempt_headers = dict(headers)
    if token:
        attempt_headers["Authorization"] = f"Bearer {token}"
    response_headers, body, status, location, error = _registry_open(
        url, attempt_headers, method, max_bytes,
    )
    if error:
        return None, None, token, error
    if status == 401:
        challenge = _parse_bearer_challenge((response_headers or {}).get("WWW-Authenticate", ""))
        if not challenge:
            return None, None, token, "registry authentication required"
        token, token_error = _registry_bearer_token(challenge)
        if token_error:
            return None, None, None, token_error
        attempt_headers["Authorization"] = f"Bearer {token}"
        response_headers, body, status, location, error = _registry_open(
            url, attempt_headers, method, max_bytes,
        )
        if error:
            return None, None, token, error
        if status == 401:
            return None, None, token, "registry HTTP 401"
    if location:
        if not follow_redirect:
            return None, None, token, "registry redirected unexpectedly"
        if not location.startswith("https://"):
            return None, None, token, "registry redirect was not https"
        cdn_headers = {
            key: value for key, value in headers.items()
            if key.lower() != "authorization"
        }
        response_headers, body, status, location, error = _registry_open(
            location, cdn_headers, method, max_bytes,
        )
        if error:
            return None, None, token, error
        if location:
            return None, None, token, "registry redirected more than once"
        if status == 401:
            return None, None, token, "registry HTTP 401"
    return response_headers, body, token, None


def _registry_digest_request(url: str, headers: dict) -> tuple[Optional[str], Optional[str]]:
    response_headers, _body, _token, error = _registry_request(url, headers, method="HEAD")
    if error:
        return None, error
    return (response_headers or {}).get("Docker-Content-Digest"), None


def _fetch_registry_manifest_digest(parsed: dict) -> tuple[Optional[str], Optional[str]]:
    repo = urllib.parse.quote(parsed["repository"], safe="/")
    tag = urllib.parse.quote(parsed["tag"], safe="._-")
    url = f"https://{parsed['api_host']}/v2/{repo}/manifests/{tag}"
    return _registry_digest_request(url, {
        "User-Agent": "ProxMenux-Monitor",
        "Accept": _DOCKER_MANIFEST_ACCEPT,
    })


def _verify_content_digest(body: bytes, digest: str) -> bool:
    """Every registry document is named by its own sha256; check it."""
    algorithm, _, want = str(digest or "").partition(":")
    if algorithm != "sha256" or not want or body is None:
        return False
    return hashlib.sha256(body).hexdigest() == want


def _select_platform_manifest(index: dict, platform: dict) -> Optional[str]:
    """Return the manifest digest matching the locally installed platform.

    Multi-arch indexes also carry attestation manifests, which advertise
    ``unknown/unknown``: their config is an SLSA provenance document, not an
    image. Picking "the first entry" would read that instead. A missing match
    yields None rather than a fallback — if the index has no build for this
    host, a pull would fail and there is no version to report.
    """
    def _norm(entry: dict) -> tuple:
        if not isinstance(entry, dict):
            return '', '', ''
        os_name = str(entry.get("os") or "").lower()
        architecture = str(entry.get("architecture") or "").lower()
        variant = str(entry.get("variant") or "").lower()
        # arm64/v8 and bare arm64 name the same build.
        if architecture == "arm64" and variant == "v8":
            variant = ""
        return os_name, architecture, variant

    want = _norm(platform or {})
    if not want[0] or not want[1]:
        return None
    for entry in (index or {}).get("manifests") or []:
        if not isinstance(entry, dict):
            continue
        annotations = entry.get("annotations") or {}
        if not isinstance(annotations, dict) or annotations.get("vnd.docker.reference.type"):
            continue
        candidate = _norm(entry.get("platform") or {})
        if candidate[0] in ("", "unknown") or candidate[1] in ("", "unknown"):
            continue
        if candidate != want:
            continue
        digest = str(entry.get("digest") or "")
        if digest.startswith("sha256:"):
            return digest
    return None


def _registry_get_document(base: str, digest: str, headers: dict, token: Optional[str],
                           ) -> tuple[Optional[dict], Optional[str], Optional[str]]:
    """GET a registry document by digest and verify it. Returns (json, token, error)."""
    _response, body, token, error = _registry_request(
        f"{base}/manifests/{urllib.parse.quote(digest, safe=':')}", headers,
        method="GET", token=token, max_bytes=_DOCKER_REMOTE_CONFIG_MAX_BYTES,
    )
    if error:
        return None, token, error
    if not _verify_content_digest(body, digest):
        return None, token, "remote manifest digest mismatch"
    try:
        document = json.loads(body.decode("utf-8"))
        if not isinstance(document, dict):
            return None, token, "remote manifest was not an object"
        return document, token, None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, token, "remote manifest was not valid JSON"


def _remote_image_config_labels(parsed: dict, remote_digest: str, platform: dict,
                                ) -> tuple[Optional[dict], Optional[str]]:
    base = f"https://{parsed.get('api_host')}/v2/{urllib.parse.quote(parsed.get('repository') or '', safe='/')}"
    headers = {"User-Agent": "ProxMenux-Monitor", "Accept": _DOCKER_MANIFEST_ACCEPT}

    manifest, token, error = _registry_get_document(base, remote_digest, headers, None)
    if error:
        return None, error
    media_type = str(manifest.get("mediaType") or "")
    if media_type in _DOCKER_INDEX_MEDIA_TYPES or "manifests" in manifest:
        platform_digest = _select_platform_manifest(manifest, platform)
        if not platform_digest:
            return None, "remote_platform_missing"
        manifest, token, error = _registry_get_document(base, platform_digest, headers, token)
        if error:
            return None, error
    config = manifest.get("config") or {}
    if not isinstance(config, dict):
        return None, "remote_unsupported_manifest"
    config_digest = str(config.get("digest") or "")
    if (str(config.get("mediaType") or "") not in _DOCKER_IMAGE_CONFIG_MEDIA_TYPES
            or not config_digest.startswith("sha256:")):
        # Schema v1 manifests and non-image OCI artifacts (Helm charts,
        # signatures) have no image config to read.
        return None, "remote_unsupported_manifest"
    _response, body, _token, error = _registry_request(
        f"{base}/blobs/{urllib.parse.quote(config_digest, safe=':')}",
        {"User-Agent": "ProxMenux-Monitor", "Accept": "*/*"},
        method="GET", token=token, max_bytes=_DOCKER_REMOTE_CONFIG_MAX_BYTES,
    )
    if error:
        return None, error
    if not _verify_content_digest(body, config_digest):
        return None, "remote config digest mismatch"
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "remote config was not valid JSON"
    if not isinstance(payload, dict) or not isinstance(payload.get("config"), dict):
        return None, "remote config was not an image config object"
    labels = payload['config'].get('Labels') or {}
    if not isinstance(labels, dict) or any(not isinstance(v, str) for v in labels.values()):
        return None, "remote labels were not a string map"
    return labels, None


def _fetch_remote_image_config_labels(parsed: dict, remote_digest: str, platform: dict,
                                      ) -> tuple[Optional[dict], Optional[str]]:
    """Cached read of the labels carried by the image a pull would install."""
    cache_key = (
        str(parsed.get("api_host") or ""),
        str(parsed.get("repository") or ""),
        str(remote_digest or ""),
        str((platform or {}).get("os") or ""),
        str((platform or {}).get("architecture") or ""),
        str((platform or {}).get("variant") or ""),
    )
    with _docker_remote_config_flights[hash(cache_key) % len(_docker_remote_config_flights)]:
        with _docker_remote_config_lock:
            cached = _docker_remote_config_cache.get(cache_key)
        if cached is not None:
            return cached.get("labels"), cached.get("error")
        try:
            labels, error = _remote_image_config_labels(parsed, remote_digest, platform)
        except Exception as exc:
            return None, f"remote metadata unavailable: {type(exc).__name__}"
        # Errors are retryable at the next explicit/lifecycle/daily refresh.
        # Successful content is immutable because the key contains its digest.
        if error is None:
            with _docker_remote_config_lock:
                if len(_docker_remote_config_cache) >= _DOCKER_REMOTE_CONFIG_CACHE_MAX:
                    _docker_remote_config_cache.clear()
                _docker_remote_config_cache[cache_key] = {"labels": labels, "error": None}
        return labels, error


_DOCKER_AVAILABLE_VERSION_REASONS = {
    "remote_platform_missing", "remote_unsupported_manifest", "remote_no_labels",
}


def _docker_available_version_from_registry(item: dict) -> tuple[Optional[str], str]:
    """Version of the image that pulling this same tag would install.

    This is deliberately not "the latest upstream release": the update action
    this project generates re-pulls the SAME tag, so the honest number is the
    one the registry is serving for it right now. Anything that cannot be
    established returns no version and a reason, keeping the existing contract
    that a new digest is reported without claiming a version number.
    """
    remote_digest = item.get("remote_digest")
    if not remote_digest:
        return None, "remote_fetch_error"
    labels, error = _fetch_remote_image_config_labels(
        item, remote_digest, item.get("platform") or {},
    )
    if error:
        return None, error if error in _DOCKER_AVAILABLE_VERSION_REASONS else "remote_fetch_error"
    version, source = _docker_version_from_labels(labels or {})
    if not version:
        return None, "remote_no_labels"
    installed_source = str(item.get("installed_version_source") or "")
    if installed_source.startswith("image_label:") and installed_source != source:
        # Comparing one publisher's label against a different one invents a
        # difference that is not there.
        return None, "version_source_mismatch"
    installed = item.get("installed_version")
    if installed and compare(installed, version) is not True:
        # Same version rebuilt, retagged, or an unusable pair: the digest
        # already says there is a new image; no number is the honest answer.
        return None, "version_not_comparable"
    return version, f"remote_{source}"


def _parse_compose_depends_on(value: Any) -> list[str]:
    """Return service names from Compose's ``depends_on`` label.

    Compose serialises entries as comma-separated
    ``service:condition:restart`` tuples.  Older releases may emit just the
    service name.  Invalid names are ignored because they must never reach a
    generated shell command.
    """
    dependencies: list[str] = []
    for raw in str(value or "").split(","):
        service = raw.strip().split(":", 1)[0].strip()
        if not service or not _DOCKER_COMPOSE_PROJECT_RE.match(service):
            continue
        if service not in dependencies:
            dependencies.append(service)
    return sorted(dependencies)


def _docker_compose_update_command(
    working_dir: str,
    config_files: list[str],
    services: list[str],
) -> str:
    prefix = ["docker", "compose", "--project-directory", working_dir]
    for config_file in config_files:
        prefix.extend(["-f", config_file])
    pull = " ".join(shlex.quote(arg) for arg in [*prefix, "pull", *services])
    recreate = " ".join(shlex.quote(arg) for arg in [
        *prefix, "up", "-d", "--no-deps", *services,
    ])
    return f"{pull} && {recreate}"


def _docker_update_unit_id(kind: str, *parts: str) -> str:
    identity = "\0".join([kind, *parts]).encode("utf-8")
    return f"docker-unit:{hashlib.sha256(identity).hexdigest()[:20]}"


def _build_docker_update_units(images: list[dict]) -> list[dict]:
    """Build reusable Docker selections for manual bulk updates.

    Independent services remain independent even when they share a Compose
    project.  A root service includes only the transitive services named by
    its real ``depends_on`` labels.  This mirrors the user's mental model of
    selecting an app while still recreating its declared database/cache
    dependencies exactly once.
    """
    projects: dict[str, dict] = {}
    for image in images:
        for target in image.get("update_targets") or []:
            project = str(target.get("project") or "").strip()
            working_dir = str(target.get("working_dir") or "").strip()
            config_files = [str(value) for value in target.get("config_files") or []]
            if not project or not working_dir or not config_files:
                continue
            project_entry = projects.get(project)
            if project_entry and (
                project_entry["working_dir"] != working_dir
                or project_entry["config_files"] != config_files
            ):
                continue
            project_entry = projects.setdefault(project, {
                "working_dir": working_dir,
                "config_files": config_files,
                "services": {},
            })
            dependencies = target.get("dependencies") or {}
            for service in target.get("services") or []:
                service = str(service or "").strip()
                if not _DOCKER_COMPOSE_PROJECT_RE.match(service):
                    continue
                project_entry["services"].setdefault(service, {
                    "reference": image.get("reference"),
                    "display_name": image.get("display_name"),
                    "logo_url": image.get("logo_url"),
                    "update_available": image.get("update_available"),
                    "depends_on": [],
                })
                service_entry = project_entry["services"][service]
                service_entry["depends_on"] = sorted(set(
                    service_entry.get("depends_on") or []
                ) | {
                    str(dep) for dep in dependencies.get(service) or []
                    if _DOCKER_COMPOSE_PROJECT_RE.match(str(dep))
                })

    units: list[dict] = []
    for project in sorted(projects):
        project_entry = projects[project]
        service_map: dict[str, dict] = project_entry["services"]
        if not service_map:
            continue
        known_services = set(service_map)
        for info in service_map.values():
            info["depends_on"] = [
                dep for dep in info.get("depends_on") or [] if dep in known_services
            ]
        depended_on = {
            dep for info in service_map.values() for dep in info.get("depends_on") or []
        }
        roots = sorted(known_services - depended_on)

        def closure(root: str) -> list[str]:
            found: set[str] = set()
            pending = [root]
            while pending:
                service = pending.pop()
                if service in found or service not in service_map:
                    continue
                found.add(service)
                pending.extend(service_map[service].get("depends_on") or [])
            return sorted(found)

        # A cycle has no root.  Represent each disconnected cyclic component
        # once instead of silently dropping it or emitting duplicate units.
        if not roots:
            roots = [min(known_services)]
        covered: set[str] = set()
        root_closures: list[tuple[str, list[str]]] = []
        for root in roots:
            services = closure(root)
            root_closures.append((root, services))
            covered.update(services)
        for service in sorted(known_services - covered):
            services = closure(service)
            root_closures.append((service, services))
            covered.update(services)

        for root, services in root_closures:
            primary = service_map[root]
            references = sorted({
                str(service_map[service].get("reference") or "")
                for service in services if service_map[service].get("reference")
            })
            states = [service_map[service].get("update_available") for service in services]
            update_available: Optional[bool]
            if any(state is True for state in states):
                update_available = True
            elif states and all(state is False for state in states):
                update_available = False
            else:
                update_available = None
            units.append({
                "id": _docker_update_unit_id("compose", project, root),
                "kind": "compose",
                "project": project,
                "primary_service": root,
                "services": services,
                "dependent_services": [service for service in services if service != root],
                "references": references,
                "primary_reference": primary.get("reference"),
                "display_name": primary.get("display_name") or root,
                "logo_url": primary.get("logo_url"),
                "working_dir": project_entry["working_dir"],
                "config_files": project_entry["config_files"],
                "update_command": _docker_compose_update_command(
                    project_entry["working_dir"], project_entry["config_files"], services,
                ),
                "standalone_containers": [],
                "update_available": update_available,
            })

    for image in images:
        containers = sorted(set(image.get("standalone_containers") or []))
        reference = str(image.get("reference") or "").strip()
        if not containers or not reference:
            continue
        units.append({
            "id": _docker_update_unit_id("standalone", reference),
            "kind": "standalone",
            "project": None,
            "primary_service": containers[0],
            "services": [],
            "dependent_services": [],
            "references": [reference],
            "primary_reference": reference,
            "display_name": image.get("display_name") or reference,
            "logo_url": image.get("logo_url"),
            "working_dir": None,
            "config_files": [],
            "update_command": "",
            "standalone_containers": containers,
            "update_available": image.get("update_available"),
        })
    return sorted(units, key=lambda unit: (
        str(unit.get("display_name") or "").lower(), unit["id"],
    ))


def resolve_docker_image_for_app(app: dict, inventory: dict) -> dict:
    """Find the Docker image that owns a delegated app.

    The bridge is the container the app declares, not its name or its image:
    Immich's compose service and image are both "immich-server" while the
    application is "immich", and matching on names would also let a container
    that merely shares a word with a catalog entry claim it. The inventory is
    backed by ``docker ps -a``, so a stopped container still resolves.

    Returns ``{image_reference, error}`` with ``error`` naming the reason when
    it cannot be resolved, so the UI can say why instead of silently showing
    nothing.
    """
    container = str(app.get("container_name") or "").strip()
    if not container:
        return {"image_reference": None, "error": "no_container_declared"}
    if not inventory or not inventory.get("available"):
        return {"image_reference": None, "error": "inventory_unavailable"}
    for image in inventory.get("images") or []:
        if container in (image.get("used_by") or []):
            return {"image_reference": image.get("reference"), "error": None}
    return {"image_reference": None, "error": "container_not_in_inventory"}


def docker_inventory_for_apps(apps: list, inventory: dict) -> dict:
    """Expose only Docker workloads the user registered (or the whole Docker stack)."""
    if not inventory or any(app.get('helper_slug') == 'docker' for app in apps):
        return inventory or {}
    references = {
        image.get('reference') for image in inventory.get('images') or []
        if any(app.get('update_via') == 'docker'
               and app.get('container_name') in (image.get('used_by') or []) for app in apps)
    }
    images = [image for image in inventory.get('images') or [] if image.get('reference') in references]
    return {**inventory, 'images': images,
            'update_count': sum(image.get('update_available') is True for image in images),
            'update_units': [unit for unit in inventory.get('update_units') or []
                             if references.intersection(unit.get('references') or [])],
            'compose_projects': _aggregate_docker_compose_projects(images)}


def annotate_delegated_apps(apps: list, docker_inventory: dict) -> None:
    """Attach the image-resolved version to apps that delegate to Docker.

    Decoration only, and deliberately fail-safe: this adds a version number
    to an app card and must never be able to cost the caller its response.
    The fields are namespaced so they cannot feed the CT badge or the update
    counters, where the image already contributes.
    """
    if not apps:
        return
    try:
        for app in apps:
            if not isinstance(app, dict) or app.get('update_via') != 'docker':
                continue
            # Cleared before every resolution, not only written on success:
            # these dicts live in caches invalidated by events rather than
            # time, so a container renamed or removed would otherwise keep
            # showing the version of an image it no longer runs.
            app['docker_available_version'] = None
            app['docker_update_available'] = None
            link = resolve_docker_image_for_app(app, docker_inventory)
            app['docker_image_reference'] = link.get('image_reference')
            app['docker_binding_error'] = link.get('error')
            reference = link.get('image_reference')
            if not reference:
                continue
            for image in docker_inventory.get('images') or []:
                if image.get('reference') != reference:
                    continue
                app['docker_available_version'] = image.get('available_version')
                app['docker_update_available'] = image.get('update_available')
                break
    except Exception:
        pass


def _aggregate_docker_compose_projects(images: list[dict]) -> list[dict]:
    """Merge per-image Compose targets into one safe action per project.

    One Compose project can contain several services whose images all moved.
    The image rows intentionally retain their narrow, service-specific action;
    scheduled and bulk updates use this aggregate so the project is pulled and
    recreated once with the union of affected services.
    """
    projects: dict[str, dict] = {}
    for image in images:
        for target in image.get("update_targets") or []:
            project = str(target.get("project") or "").strip()
            working_dir = str(target.get("working_dir") or "").strip()
            config_files = [str(value) for value in target.get("config_files") or []]
            if not project or not working_dir or not config_files:
                continue
            existing = projects.get(project)
            if existing and (
                existing["working_dir"] != working_dir
                or existing["config_files"] != config_files
            ):
                # Compose project names should be unique on one engine. If
                # provenance conflicts, keep the first verified project rather
                # than combining commands from unrelated working directories.
                continue
            entry = projects.setdefault(project, {
                "kind": "compose",
                "project": project,
                "working_dir": working_dir,
                "config_files": config_files,
                "services": [],
            })
            entry["services"] = sorted(set(entry["services"]) | {
                str(service) for service in target.get("services") or [] if service
            })
    result = []
    for project in sorted(projects):
        target = projects[project]
        if not target["services"]:
            continue
        target["update_command"] = _docker_compose_update_command(
            target["working_dir"], target["config_files"], target["services"],
        )
        result.append(target)
    return result


def _docker_inventory_from_ct(vmid) -> dict:
    checked_at = _now_iso()
    rc, out, err = _pct_exec(
        vmid, ["docker", "version", "--format", "{{.Server.Version}}"], timeout=10
    )
    if rc != 0:
        return {
            "vmid": int(vmid), "available": False, "engine_version": None,
            "images": [], "update_count": 0, "checked_at": checked_at,
            "error": (err or out).strip()[:200] or "Docker is not available",
        }
    engine_version = out.strip()
    rc_cont, containers_out, _ = _pct_exec(
        vmid,
        ["docker", "ps", "-a", "--no-trunc", "--format",
         "{{.Names}}\t{{.Image}}\t{{.Status}}"],
        timeout=10,
    )
    if rc_cont != 0:
        return {
            "vmid": int(vmid), "available": False,
            "refreshing": False, "engine_version": engine_version,
            "images": [], "update_count": 0, "checked_at": checked_at,
            "error": "docker container inventory is not ready",
        }
    containers: list[dict] = []
    for line in containers_out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            containers.append({"name": parts[0], "image": parts[1], "status": parts[2]})

    # Compose provenance is the safe bridge from read-only detection to
    # reproducible updates. Docker Compose writes these labels on every
    # service container; unlike guessing a docker-run command, they point
    # back to the declarative project, service and config file(s).
    if containers:
        inspect_argv = [
            "docker", "inspect", "--format", "{{json .}}",
            *[item["name"] for item in containers],
        ]
        rc_inspect, inspect_out, _ = _pct_exec(vmid, inspect_argv, timeout=20)
        inspected: dict[str, dict] = {}
        if rc_inspect == 0:
            for raw in inspect_out.splitlines():
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                name = str(obj.get("Name") or "").lstrip("/")
                if name:
                    inspected[name] = obj
        for item in containers:
            obj = inspected.get(item["name"]) or {}
            config = obj.get("Config") or {}
            labels = config.get("Labels") or {}
            item["image_reference"] = _normalise_docker_container_reference(
                str(config.get("Image") or item.get("image") or "")
            )
            item["image_id"] = str(obj.get("Image") or "").strip()
            project = str(labels.get("com.docker.compose.project") or "").strip()
            service = str(labels.get("com.docker.compose.service") or "").strip()
            working_dir = str(labels.get("com.docker.compose.project.working_dir") or "").strip()
            raw_files = str(labels.get("com.docker.compose.project.config_files") or "").strip()
            config_files = [p.strip() for p in raw_files.split(",") if p.strip()]
            depends_on = _parse_compose_depends_on(
                labels.get("com.docker.compose.depends_on")
            )
            compose_valid = (
                bool(project and service and working_dir and config_files)
                and bool(_DOCKER_COMPOSE_PROJECT_RE.match(project))
                and bool(_DOCKER_COMPOSE_PROJECT_RE.match(service))
                and working_dir.startswith("/")
                and all(path.startswith("/") for path in config_files)
                and all("\x00" not in value and "\n" not in value for value in [working_dir, *config_files])
            )
            item["compose"] = ({
                "project": project,
                "service": service,
                "working_dir": working_dir,
                "config_files": config_files,
                "depends_on": depends_on,
            } if compose_valid else None)

    rc_img, images_out, images_err = _pct_exec(
        vmid,
        ["docker", "image", "ls", "--no-trunc", "--digests", "--format",
         "{{.Repository}}\t{{.Tag}}\t{{.Digest}}\t{{.ID}}"],
        timeout=15,
    )
    if rc_img != 0:
        return {
            "vmid": int(vmid), "available": False,
            "refreshing": False, "engine_version": engine_version,
            "images": [], "update_count": 0, "checked_at": checked_at,
            "error": (images_err or images_out).strip()[:200] or "docker image ls failed",
        }

    raw_image_rows: list[tuple[str, str, str, str]] = []
    for line in images_out.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            raw_image_rows.append(tuple(part.strip() for part in parts))

    inspected_images: dict[str, dict] = {}
    unique_image_ids = list(dict.fromkeys([
        *(row[3] for row in raw_image_rows if row[3]),
        *(item['image_id'] for item in containers if item.get('image_id')),
    ]))
    if unique_image_ids:
        rc_image_inspect, image_inspect_out, _ = _pct_exec(
            vmid,
            ["docker", "image", "inspect", "--format", "{{json .}}", *unique_image_ids],
            timeout=30,
        )
        if rc_image_inspect == 0:
            for raw in image_inspect_out.splitlines():
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                image_key = str(obj.get("Id") or "").strip()
                if image_key:
                    inspected_images[image_key] = obj
                    inspected_images[image_key.removeprefix("sha256:")] = obj

    images: list[dict] = []
    seen: set[str] = set()
    for repository, tag, digest, image_id in raw_image_rows:
        parsed = _parse_docker_reference(repository, tag)
        if not parsed or parsed["reference"] in seen:
            continue
        seen.add(parsed["reference"])
        used_by = sorted({
            item["name"] for item in containers
            if _docker_reference_identity(str(item.get("image_reference") or item.get("image") or ""))
            == (parsed['registry'], parsed['repository'], parsed['tag'])
        })
        if not used_by:
            # Skip orphan images (no container — running or stopped —
            # references them). They are residual `docker pull` artifacts
            # that would report bogus "update available" entries for tags
            # no live workload uses. The user manages orphan cleanup with
            # `docker image prune` / `docker rmi` outside of ProxMenux.
            continue
        used_containers = [item for item in containers if item.get("name") in used_by]
        # A pull can move the local tag before its containers are recreated.
        # Inspect the image actually used by the container, not that new tag.
        running_ids = [str(item.get('image_id') or '') for item in used_containers if item.get('image_id')]
        actual_id = next((value for value in running_ids if value != image_id), None)
        if actual_id:
            image_id = actual_id
            digest = ''
            actual_image = inspected_images.get(actual_id) or {}
            for repo_digest in actual_image.get('RepoDigests') or []:
                repository_name, _, candidate_digest = repo_digest.partition('@')
                candidate = _parse_docker_reference(repository_name, tag)
                if candidate and (candidate['registry'], candidate['repository']) == (parsed['registry'], parsed['repository']):
                    digest = candidate_digest
                    break
        compose_targets: dict[str, dict] = {}
        standalone_containers: list[str] = []
        for container in used_containers:
            compose = container.get("compose")
            if not compose:
                standalone_containers.append(container["name"])
                continue
            project = compose["project"]
            target = compose_targets.setdefault(project, {
                "kind": "compose",
                "project": project,
                "working_dir": compose["working_dir"],
                "config_files": compose["config_files"],
                "services": [],
                "dependencies": {},
            })
            if compose["service"] not in target["services"]:
                target["services"].append(compose["service"])
            target["dependencies"][compose["service"]] = compose.get("depends_on") or []
        for target in compose_targets.values():
            target["services"].sort()
            target["update_command"] = _docker_compose_update_command(
                target["working_dir"], target["config_files"], target["services"],
            )
        inspected_image = (
            inspected_images.get(image_id)
            or inspected_images.get(image_id.removeprefix("sha256:"))
            or {}
        )
        installed_version, installed_version_source = _docker_version_from_image_inspect(
            parsed, inspected_image,
        )
        primary_container = used_containers[0] if used_containers else {}
        primary_compose = primary_container.get("compose") or {}
        display_meta = _docker_service_catalog_meta(
            str(primary_compose.get("service") or ""),
            str(primary_container.get("name") or ""),
            parsed["reference"],
        )
        images.append({
            **parsed,
            "local_digest": digest if digest.startswith("sha256:") else None,
            "remote_digest": None,
            "image_id": image_id,
            "used_by": used_by,
            "update_targets": sorted(compose_targets.values(), key=lambda target: target["project"]),
            "standalone_containers": sorted(standalone_containers),
            "display_name": display_meta.get("name"),
            "logo_url": display_meta.get("logo_url"),
            "installed_version": installed_version,
            "installed_version_source": installed_version_source,
            # The platform of the image actually installed here. A multi-arch
            # index must be resolved to this exact build before its config can
            # be read; anything else would describe a different binary.
            "platform": {
                "os": str(inspected_image.get("Os") or ""),
                "architecture": str(inspected_image.get("Architecture") or ""),
                "variant": str(inspected_image.get("Variant") or ""),
            },
            "available_version": None,
            "available_version_source": None,
            "update_available": None,
            "error": None,
        })
        if len(images) >= _DOCKER_MAX_IMAGES:
            break

    def _check(item: dict) -> tuple[str, Optional[str], Optional[str]]:
        remote, error = _fetch_registry_manifest_digest(item)
        return item["reference"], remote, error

    if images:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(images))) as pool:
            results = list(pool.map(_check, images))
        by_ref = {ref: (digest, error) for ref, digest, error in results}
        for item in images:
            remote, remote_error = by_ref.get(item["reference"], (None, None))
            item["remote_digest"] = remote
            item["error"] = remote_error
            if item["local_digest"] and remote:
                item["update_available"] = item["local_digest"] != remote

        # Docker Hub exposes the digest for each tag. Resolve versions only
        # when an explicit version tag has the exact local/remote digest;
        # otherwise leave the value empty and let the UI report a new image
        # without claiming a version number.
        hub_repositories = sorted({
            item["repository"]
            for item in images
            if item.get("registry") == "docker.io"
            and (not item.get("installed_version") or item.get("update_available") is True)
        })
        hub_records: dict[str, list[dict]] = {}
        if hub_repositories:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(hub_repositories))) as pool:
                fetched = list(pool.map(_docker_hub_tag_records, hub_repositories))
            for repository, (records, _error) in zip(hub_repositories, fetched):
                hub_records[repository] = records
        for item in images:
            records = hub_records.get(item.get("repository")) or []
            if not records:
                continue
            if not item.get("installed_version"):
                local_version = _docker_hub_version_for_digest(records, item.get("local_digest"))
                if local_version:
                    item["installed_version"] = local_version
                    item["installed_version_source"] = "docker_hub_digest_tag"
            if item.get("update_available") is True:
                available_version = _docker_hub_version_for_digest(records, item.get("remote_digest"))
                if available_version and available_version != item.get("installed_version"):
                    item["available_version"] = available_version
                    item["available_version_source"] = "docker_hub_digest_tag"

        # The shortcut above only covers docker.io, and only when a version
        # tag happens to share the digest. Everywhere else — ghcr.io, lscr.io,
        # quay.io — an available update had no version number at all. The
        # image a pull would install carries its own version label, so read it
        # from the registry by digest, over the same protocol and Bearer
        # challenge the digest comparison already uses. Hub keeps priority on
        # docker.io because its tag API is not a pull and does not consume the
        # anonymous pull-rate budget, and because official images carry no
        # labels at all.
        pending = [
            item for item in images
            if item.get("update_available") is True
            and not item.get("available_version")
            and item.get("remote_digest")
        ]
        for item in pending:
            item["available_version_source"] = "remote_metadata_pending"

    return {
        "vmid": int(vmid),
        "available": True,
        "refreshing": False,
        "engine_version": engine_version,
        "containers": containers,
        "images": images,
        "compose_projects": _aggregate_docker_compose_projects(images),
        "update_units": _build_docker_update_units(images),
        "update_count": sum(1 for item in images if item.get("update_available") is True),
        "checked_at": checked_at,
        "truncated": len(seen) >= _DOCKER_MAX_IMAGES,
        "error": None,
    }


def get_docker_inventory(vmid, force: bool = False) -> dict:
    """Return cached/read-only Docker image update state for one CT."""
    key = str(int(vmid))
    with _docker_inventory_lock:
        cached = _docker_inventory_cache.get(key)
        if cached and not force:
            age = time.time() - float(cached.get("checked_at_unix") or 0)
            # Retry unavailable/stopped CTs quickly.  A full 24-hour
            # negative cache made Docker stay unavailable after the user
            # started the container from the VM page.
            cache_ttl = _DOCKER_INVENTORY_TTL_SEC if cached.get("available") else 30
            if age < cache_ttl:
                return dict(cached)
    result = _docker_inventory_from_ct(vmid)
    result["checked_at_unix"] = time.time()
    # A restored CT can expose the Docker binary and socket before the daemon
    # has finished waiting for network-online.target and loading its image
    # store. Never replace a useful inventory (and the stable docker-unit IDs
    # referenced by bulk updates) with that transient failure. The snapshot is
    # marked as refreshing and uses the short negative TTL, so the next normal
    # request retries instead of keeping stale data for 24 hours.
    if (
        not result.get("available")
        and cached
        and (
            cached.get("refreshing")
            or cached.get("images")
            or cached.get("update_units")
        )
    ):
        pending = dict(cached)
        pending.update({
            "available": False,
            "refreshing": True,
            "error": result.get("error") or "Docker is not ready",
            "checked_at_unix": result["checked_at_unix"],
        })
        result = pending
    with _docker_inventory_lock:
        _docker_inventory_cache[key] = result
    _queue_docker_metadata(key, result)
    return dict(result)


def _queue_docker_metadata(key: str, snapshot: dict) -> None:
    """Enrich a published snapshot, never an inventory from a later CT boot.

    Only a real inventory refresh schedules work. Reading a tab/cache does
    not contact registries. Queue and concurrency are bounded globally.
    """
    def enrich(index, item):
        try:
            _docker_metadata_context.deadline = time.monotonic() + 20
            version, source = _docker_available_version_from_registry(item)
            with _docker_inventory_lock:
                if _docker_inventory_cache.get(key) is not snapshot:
                    return
                images = list(snapshot['images'])
                images[index] = {**images[index], 'available_version_source': source}
                if version and version != item.get('installed_version'):
                    images[index]['available_version'] = version
                snapshot['images'] = images
        except Exception:
            # Optional metadata cannot turn a successful digest scan into an error.
            with _docker_inventory_lock:
                if _docker_inventory_cache.get(key) is snapshot:
                    images = list(snapshot['images'])
                    images[index] = {**images[index], 'available_version_source': 'remote_fetch_error'}
                    snapshot['images'] = images
        finally:
            _docker_metadata_context.deadline = None
            _docker_metadata_slots.release()

    if not snapshot.get('available'):
        return
    for index, item in enumerate(snapshot.get('images') or []):
        if item.get('available_version_source') != 'remote_metadata_pending':
            continue
        if not _docker_metadata_slots.acquire(blocking=False):
            item['available_version_source'] = 'remote_metadata_deferred'
            continue
        try:
            _docker_metadata_pool.submit(enrich, index, dict(item))
        except Exception:
            _docker_metadata_slots.release()
            item['available_version_source'] = 'remote_metadata_deferred'


def mark_docker_inventory_refreshing(vmid) -> dict:
    """Publish a non-destructive lifecycle transition for one Docker CT.

    Restores and starts invalidate the meaning of the previous digest result,
    but its update-unit IDs are still required to render the user's saved bulk
    selection. Keep that structural metadata while explicitly marking every
    update state as pending until the daemon becomes usable.
    """
    key = str(int(vmid))
    now = time.time()
    with _docker_inventory_lock:
        previous = dict(_docker_inventory_cache.get(key) or {})
        previous_images = [
            {**item, "update_available": None}
            for item in (previous.get("images") or [])
            if isinstance(item, dict)
        ]
        previous_units = [
            {**item, "update_available": None}
            for item in (previous.get("update_units") or [])
            if isinstance(item, dict)
        ]
        pending = {
            "vmid": int(vmid),
            "available": False,
            "refreshing": True,
            "engine_version": previous.get("engine_version"),
            "containers": previous.get("containers") or [],
            "images": previous_images,
            "compose_projects": previous.get("compose_projects") or [],
            "update_units": previous_units,
            "update_count": 0,
            "checked_at": previous.get("checked_at"),
            "checked_at_unix": now,
            "truncated": bool(previous.get("truncated")),
            "error": None,
        }
        _docker_inventory_cache[key] = pending
    return dict(pending)


def get_cached_docker_inventories() -> dict:
    """Return in-memory inventories without probing CTs or registries."""
    with _docker_inventory_lock:
        return {key: dict(value) for key, value in _docker_inventory_cache.items()}


def invalidate_docker_inventory(vmid) -> None:
    """Drop one CT's Docker snapshot before a lifecycle refresh.

    Restoring a container backup can roll Docker Engine, images and Compose
    state backwards. Keeping the pre-restore digest snapshot visible while
    that CT boots would falsely report the restored workloads as current.
    """
    key = str(int(vmid))
    with _docker_inventory_lock:
        _docker_inventory_cache.pop(key, None)


def refresh_docker_inventories(force: bool = False) -> int:
    """Daily best-effort scan of running LXC containers that host Docker."""
    try:
        import managed_installs
        items = managed_installs.get_active_items() or []
    except Exception:
        items = []
    vmids: set[int] = set()
    for item in items:
        if item.get("type") != "lxc" or item.get("_vmid") is None:
            continue
        vmid = int(item["_vmid"])
        # Cheap local signature also covers manual Docker installs whose CT
        # has no community-scripts slug.
        rc, _, _ = _pct_exec(vmid, ["test", "-x", "/usr/bin/docker"], timeout=5)
        if rc == 0:
            vmids.add(vmid)
    count = 0
    for vmid in sorted(vmids):
        try:
            get_docker_inventory(vmid, force=force)
            count += 1
        except Exception as exc:
            print(f"[ProxMenux] Docker inventory CT {vmid} failed: {exc}")
    return count


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
        "latest_published_at": None,
        "update_available": None,
        "error": None,
        "checked_at": None,
    }


def test_config(vmid, payload: dict) -> tuple[bool, Any]:
    """Validate and execute an app-tracking draft without persisting it.

    This is the editor's diagnostic contract.  It deliberately returns
    the installed and upstream outcomes separately so a user can tell a
    bad local detector from a bad repository/tag filter.  Probe output is
    never returned: a user-selected file or command could contain secrets.
    """
    ok, config = validate_config(payload)
    if not ok:
        return False, config

    method = config.get("installed_via")
    upstream_type = config.get("upstream_type")
    if not upstream_type and config.get("repo"):
        upstream_type = "github"

    installed_version, installed_error = detect_installed_version(vmid, config)
    latest_version, upstream_error, latest_published_at = fetch_latest_upstream_details(config)
    effective_regex = None
    if method:
        effective_regex = (
            config.get("file_regex") if method == "file"
            else config.get("installed_regex")
            or config.get("tag_regex")
            or r"(\d+[.\d]+)"
        )

    return True, {
        "valid": True,
        "persisted": False,
        "checked_at": _now_iso(),
        "installed": {
            "configured": bool(method),
            "method": method,
            "effective_regex": effective_regex,
            "version": installed_version,
            "error": installed_error,
        },
        "upstream": {
            "configured": bool(upstream_type),
            "type": upstream_type,
            "version": latest_version,
            "published_at": latest_published_at,
            "error": upstream_error,
        },
        "update_available": compare(installed_version, latest_version),
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


def mark_manual_versions_unverified(vmid, app_ids) -> int:
    """Invalidate manual version claims after their own updater succeeds.

    A custom update command is intentionally arbitrary shell owned by the
    operator.  Its exit code says that the command completed, not which
    version is now installed.  For manually tracked applications, retaining
    the old typed value would create a false update warning (or a false
    "current" result).  Mark only explicitly targeted manual apps so a
    helper-wide update never changes unrelated registrations.
    """
    wanted = {
        str(app_id).strip()
        for app_id in (app_ids or [])
        if isinstance(app_id, str) and str(app_id).strip()
    }
    if not wanted:
        return 0
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        if not sidecar:
            return 0
        changed = 0
        for app in sidecar.get("apps") or []:
            if app.get("id") not in wanted or app.get("installed_via") != "manual":
                continue
            if not app.get("manual_version_needs_confirmation"):
                app["manual_version_needs_confirmation"] = True
                changed += 1
        if changed:
            sidecar["updated_at"] = _now_iso()
            _write_sidecar(vmid, sidecar)
        return changed


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


# ── Manual bulk updates CRUD ───────────────────────────────────────

def get_bulk_update(vmid) -> Optional[dict]:
    """Return the persisted manual bulk selection, if configured."""
    sidecar = _read_sidecar(vmid)
    if not sidecar:
        return None
    bulk = sidecar.get("bulk_update")
    return bulk if isinstance(bulk, dict) else None


def update_bulk_update(vmid, payload: dict) -> tuple[bool, Any]:
    """Persist a reusable bulk selection independently from cron options."""
    ok, bulk = validate_bulk_update(payload)
    if not ok:
        return False, bulk
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        if not sidecar:
            sidecar = {
                "vmid": vmid,
                "apps": [],
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        previous = sidecar.get("bulk_update") or {}
        now = _now_iso()
        bulk["configured_at"] = previous.get("configured_at") or now
        bulk["updated_at"] = now
        sidecar["bulk_update"] = bulk
        sidecar["updated_at"] = now
        if not _write_sidecar(vmid, sidecar):
            return False, "could not persist sidecar"
    return True, sidecar


def delete_bulk_update(vmid) -> bool:
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        if not sidecar or "bulk_update" not in sidecar:
            return True
        sidecar.pop("bulk_update", None)
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


def partition_scheduled_release_targets(
    targets: list[str],
    apps: list[dict],
) -> tuple[set[str], list[str]]:
    """Split scheduled targets by whether the release-age hold applies.

    Only registered applications with an installed-version detector are
    release-gated.  Web-Link-only apps with a custom updater, Docker targets
    and OS packages remain executable on every scheduled occurrence.  The
    second return value is the target list to use when the gated applications
    must be deferred.  Legacy ``apps`` wildcards are expanded to explicit
    untracked registrations so those commands are not accidentally blocked.
    """
    raw_targets = [str(value) for value in (targets or [])]
    select_all_apps = "apps" in raw_targets
    selected_app_ids = {
        value.split(":", 1)[1]
        for value in raw_targets
        if value.startswith("app:")
    }
    gated_ids: set[str] = set()
    eligible_apps: list[dict] = []
    for app in apps or []:
        app_id = str(app.get("id") or "").strip()
        # A delegated app has no updater of its own and never resolves a
        # release date, so including it would hold the whole schedule back
        # waiting for a date that will never arrive.
        if (not app_id or app.get("managed_oci_app_id")
                or app.get("helper_slug") == "docker"
                or app.get("update_via") == "docker"):
            continue
        if not select_all_apps and app_id not in selected_app_ids:
            continue
        eligible_apps.append(app)
        if app.get("installed_via"):
            gated_ids.add(app_id)

    remaining: list[str] = []

    def add(target_id: str) -> None:
        if target_id and target_id not in remaining:
            remaining.append(target_id)

    for target_id in raw_targets:
        if target_id == "apps":
            for app in eligible_apps:
                app_id = str(app.get("id") or "").strip()
                if app_id and app_id not in gated_ids:
                    add(f"app:{app_id}")
            continue
        if target_id.startswith("app:") and target_id.split(":", 1)[1] in gated_ids:
            continue
        add(target_id)
    return gated_ids, remaining


def scheduled_app_release_gate(
    vmid,
    delay_days: int,
    now: Optional[datetime.datetime] = None,
    app_ids: Optional[set[str]] = None,
) -> dict:
    """Decide whether a scheduled app updater may run after a release hold.

    Manual updates never call this function.  A non-zero hold first refreshes
    every registered detector, then permits automation only when at least one
    update is known and every pending release has a trustworthy publish date
    old enough for the configured delay.  This is deliberately conservative:
    a CT-wide helper updater cannot skip one young application safely.
    """
    try:
        days = int(delay_days)
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        return {"allowed": True, "status": "ready", "reason": None}

    try:
        check_all(vmid, force=True)
    except Exception as exc:
        return {"allowed": False, "status": "deferred", "reason": f"version refresh failed: {exc}"}
    sidecar = _read_sidecar(vmid) or {}
    tracked = [
        app for app in (sidecar.get("apps") or [])
        if app.get("installed_via") and not app.get("managed_oci_app_id")
        and (app_ids is None or app.get("id") in app_ids)
    ]
    if not tracked:
        return {
            "allowed": False,
            "status": "deferred",
            "reason": "release hold requires at least one version-tracked app",
        }

    unknown = [app for app in tracked if (app.get("state") or {}).get("update_available") is None]
    if unknown:
        names = ", ".join(str(app.get("name") or "app") for app in unknown[:3])
        return {
            "allowed": False,
            "status": "deferred",
            "reason": f"release date/update state unavailable for: {names}",
        }

    pending = [app for app in tracked if (app.get("state") or {}).get("update_available") is True]
    if not pending:
        return {"allowed": False, "status": "skipped", "reason": "no pending app updates"}

    current = now or datetime.datetime.now(datetime.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    for app in pending:
        state = app.get("state") or {}
        raw_date = state.get("latest_published_at")
        if not isinstance(raw_date, str) or not raw_date.strip():
            return {
                "allowed": False,
                "status": "deferred",
                "reason": f"upstream publish date unavailable for {app.get('name') or 'app'}",
            }
        try:
            published = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            return {
                "allowed": False,
                "status": "deferred",
                "reason": f"invalid upstream publish date for {app.get('name') or 'app'}",
            }
        eligible_at = published + datetime.timedelta(days=days)
        if current < eligible_at:
            return {
                "allowed": False,
                "status": "deferred",
                "reason": f"release hold active until {eligible_at.isoformat()}",
            }
    return {"allowed": True, "status": "ready", "reason": None}


def record_schedule_run(
    vmid,
    status: str,
    target: str,
    reason: Optional[str] = None,
    *,
    log_name: Optional[str] = None,
    reboot_required: Optional[bool] = None,
    reboot_packages: Optional[list[str]] = None,
) -> bool:
    """Called by the scheduler after a fired run completes. Updates
    the schedule with last_run_at + last_run_status so the UI can show
    the outcome. `status` is one of "success" | "failure" |
    "partial" | "deferred" | "skipped"."""
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        if not sidecar or not isinstance(sidecar.get("schedule"), dict):
            return False
        sidecar["schedule"]["last_run_at"] = _now_iso()
        sidecar["schedule"]["last_run_status"] = status
        sidecar["schedule"]["last_run_target"] = target
        if reason:
            sidecar["schedule"]["last_run_reason"] = str(reason)[:300]
        else:
            sidecar["schedule"].pop("last_run_reason", None)
        if log_name:
            sidecar["schedule"]["last_run_log"] = os.path.basename(str(log_name))[:220]
        else:
            sidecar["schedule"].pop("last_run_log", None)
        if reboot_required is None:
            sidecar["schedule"].pop("last_run_reboot_required", None)
        else:
            sidecar["schedule"]["last_run_reboot_required"] = bool(reboot_required)
        packages = [
            str(package).strip()[:160]
            for package in (reboot_packages or [])[:32]
            if str(package).strip()
        ]
        if reboot_required and packages:
            sidecar["schedule"]["last_run_reboot_packages"] = packages
        else:
            sidecar["schedule"].pop("last_run_reboot_packages", None)
        sidecar["updated_at"] = _now_iso()
        return _write_sidecar(vmid, sidecar)


def clear_schedule_reboot_required(vmid) -> bool:
    """Clear a persisted reboot warning after the CT starts or reboots."""
    with _cache_lock:
        sidecar = _read_sidecar(vmid)
        schedule = (sidecar or {}).get("schedule")
        if not isinstance(schedule, dict):
            return False
        if schedule.get("last_run_reboot_required") is not True:
            return True
        schedule["last_run_reboot_required"] = False
        schedule.pop("last_run_reboot_packages", None)
        sidecar["updated_at"] = _now_iso()
        return _write_sidecar(vmid, sidecar)


def _fire_update_notification(vmid, app: dict) -> None:
    # Per-app opt-out: user flipped the bell icon off for this specific
    # app (because they know it can't be updated on their box or they
    # just don't care). Field defaults to True — an app registered
    # before this feature landed keeps receiving notifications.
    if app.get("notifications_enabled", True) is False:
        return
    if app.get("helper_slug") == "docker":
        return
    # Delegated apps are announced by their Docker image's own event; a
    # second one for the same release would land in a different event type
    # and therefore escape deduplication.
    if app.get("update_via") == "docker":
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


def _docker_stack_notification_payload(
    vmid: int, docker_app: dict, inventory: dict, ct_name: str,
) -> Optional[dict]:
    state = docker_app.get('state') or {}
    engine_pending = bool(
        state.get('update_available')
        and state.get('latest_version')
    )
    pending_images = sorted(
        (
            image for image in (inventory.get('images') or [])
            if image.get('update_available') is True
        ),
        key=lambda image: str(image.get('reference') or ''),
    )
    if not engine_pending and not pending_images:
        return None

    identity = {
        'engine': ({
            'installed': state.get('installed_version'),
            'latest': state.get('latest_version'),
        } if engine_pending else None),
        'images': [
            {
                'reference': image.get('reference'),
                'remote_digest': image.get('remote_digest'),
            }
            for image in pending_images
        ],
    }
    signature = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()[:20]
    lines = []
    if engine_pending:
        installed = state.get('installed_version') or 'unknown'
        latest = state.get('latest_version') or 'unknown'
        lines.append(f'• Docker Engine: {installed} → {latest}')
    for image in pending_images[:12]:
        reference = image.get('reference') or 'Docker image'
        # Lead with the application when the catalog resolved one: the alert
        # is read on a phone, where "vaultwarden/server:latest" is a worse
        # answer to "what needs updating" than "Vaultwarden". The reference
        # stays, because it is what the user acts on. The deduplication
        # signature above keeps using the reference alone.
        display_name = str(image.get('display_name') or '').strip()
        label = f'{display_name} ({reference})' if display_name and display_name != reference else reference
        installed = image.get('installed_version')
        available = image.get('available_version')
        if installed and available and installed != available:
            lines.append(f'• {label}: {installed} → {available}')
        else:
            lines.append(f'• {label}: new registry digest')
    if len(pending_images) > 12:
        lines.append(f'• +{len(pending_images) - 12} additional image update(s)')
    return {
        'hostname': socket.gethostname(),
        'vmid': int(vmid),
        'ct_name': ct_name or f'CT-{vmid}',
        'count': len(pending_images) + (1 if engine_pending else 0),
        'details': '\n'.join(lines),
        'signature': signature,
    }


def emit_all_pending_docker_stacks() -> int:
    """Emit one cached Docker update event per registered container."""
    inventories = get_cached_docker_inventories()
    if not inventories:
        return 0
    names: dict[int, str] = {}
    try:
        import managed_installs
        names = {
            int(item['_vmid']): str(item.get('name') or f"CT-{item['_vmid']}")
            for item in (managed_installs.get_active_items() or [])
            if item.get('type') == 'lxc' and item.get('_vmid') is not None
        }
    except Exception:
        names = {}

    emitted = 0
    for raw_vmid, inventory in sorted(inventories.items(), key=lambda item: int(item[0])):
        try:
            vmid = int(raw_vmid)
        except (TypeError, ValueError):
            continue
        sidecar = _read_sidecar(vmid) or {}
        docker_app = next(
            (
                app for app in (sidecar.get('apps') or [])
                if app.get('helper_slug') == 'docker'
            ),
            None,
        )
        if docker_app:
            if docker_app.get('notifications_enabled', True) is False:
                continue
        else:
            # No automatic Docker registration: notify only images explicitly
            # followed by delegated apps, honoring each app's notification choice.
            references = {
                resolve_docker_image_for_app(app, inventory).get('image_reference')
                for app in sidecar.get('apps') or []
                if app.get('update_via') == 'docker'
                and app.get('notifications_enabled', True) is not False
            } - {None}
            if not references:
                continue
            inventory = {**inventory, 'images': [
                image for image in inventory.get('images') or []
                if image.get('reference') in references
            ]}
            docker_app = {}
        payload = _docker_stack_notification_payload(
            vmid, docker_app, inventory, names.get(vmid) or f'CT-{vmid}',
        )
        if not payload:
            continue
        try:
            from notification_manager import notification_manager
            signature = payload.pop('signature')
            notification_manager.emit_event(
                event_type='docker_stack_update_available',
                severity='INFO',
                data=payload,
                source='polling',
                entity='ct',
                entity_id=f'{vmid}:{signature}',
            )
            emitted += 1
        except Exception as exc:
            print(f'[ProxMenux] Docker update notification for CT {vmid} failed: {exc}')
    return emitted


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
    slug = app.get("helper_slug")

    # An app whose updates are delegated to its Docker image must keep its
    # docker detector. Healing it onto a leftover /root/.<app> marker would
    # silently turn it into a native app that then checks its own upstream —
    # the exact duplication the delegation exists to prevent.
    if app.get("update_via") == "docker":
        version, error = detect_installed_version(vmid, app)
        return version, error, False

    hint = (_fetch_tracking_hints() or {}).get(slug) or {}

    # A modern Community Scripts marker (/root/.<app>) is a useful
    # fallback, but it is not a live process probe.  It can stay behind when
    # an operator upgrades an application outside the helper script.  When a
    # later runtime-verified catalog entry promotes a non-marker primary
    # detector, migrate existing marker-backed registrations to that stronger
    # detector on their next check.  This is deliberately generic: adding a
    # verified runtime override for another helper app automatically repairs
    # its already-saved sidecars too.
    is_helper_marker = (
        app.get("installed_via") == "file"
        and re.fullmatch(r"/root/\.[A-Za-z0-9_.-]+", str(app.get("file_path") or ""))
    )
    if is_helper_marker and isinstance(hint, dict):
        primary = {"installed_via": hint.get("installed_via")}
        for key in _DETECTOR_FIELDS:
            if key in hint:
                primary[key] = hint[key]
        primary_probe = _detector_probe_config(hint, primary)
        primary_is_marker = (
            primary_probe.get("installed_via") == "file"
            and re.fullmatch(r"/root/\.[A-Za-z0-9_.-]+", str(primary_probe.get("file_path") or ""))
        )
        if primary_probe.get("installed_via") and not primary_is_marker:
            primary_installed, _primary_error = detect_installed_version(vmid, primary_probe)
            if primary_installed:
                # Keep user-owned presentation and updater fields, replacing
                # only the detector configuration that was previously a stale
                # helper marker.  The hint continues to supply its marker as
                # a fallback if the live probe disappears on an older layout.
                for key in _DETECTOR_FIELDS:
                    app.pop(key, None)
                app.update(primary_probe)
                return primary_installed, None, True

    if app.get("installed_via") == "manual" and app.get("manual_version_needs_confirmation"):
        # A successful arbitrary user command does not prove what version it
        # installed.  Never present the previously typed manual value as a
        # fresh observation; the user can save the app again once they have a
        # trustworthy version source or value.
        return None, None, False

    installed, err = detect_installed_version(vmid, app)
    if installed or not err:
        return installed, err, False
    if not slug:
        return installed, err, False
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
        latest, up_err, latest_published_at = (None, None, None)
        if app.get("repo") or app.get("upstream_type") in ("http_json", "docker_hub"):
            latest, up_err, latest_published_at = fetch_latest_upstream_details(app)

        err = inst_err or up_err
        update_available = compare(installed, latest) if (installed and latest) else None

        app["state"] = {
            "installed_version": installed,
            "latest_version": latest,
            "latest_published_at": latest_published_at,
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
        "update_via": app.get("update_via"),
        "container_name": app.get("container_name"),
        "ports": app.get("ports") or [],
        # Keep the application-level logo in the compact /api/vms
        # projection. Consumers can prefer a per-link logo and fall
        # back to this one when the Web Link intentionally leaves its
        # own logo empty.
        "logo_url": app.get("logo_url") or None,
        "health_path": app.get("health_path"),
        "installed_version": state.get("installed_version"),
        "latest_version": state.get("latest_version"),
        "latest_published_at": state.get("latest_published_at"),
        "update_available": state.get("update_available"),
        "error": state.get("error"),
        "checked_at": state.get("checked_at"),
        "has_repo": bool(app.get("repo")),
        # Updates tab surfaces: whether the user has a custom bash
        # command wired up ("Apply {app}" runs `pct exec sh -c` on
        # it) and whether the "no method" notice is suppressed for
        # this app.
        "update_command": app.get("update_command") or "",
        "update_method": app.get("update_method", "custom" if app.get("update_command") else "none"),
        # Compatibility field for older clients. The only supported
        # strategy is now replacement; legacy sidecars are normalized
        # in the API even before their next write.
        "update_strategy": "custom_override",
        "hide_no_updater_notice": bool(app.get("hide_no_updater_notice")),
        # Whether this app should be counted in the CT's aggregate
        # updates badge (default: yes). See validator for full context.
        "exclude_from_badge": bool(app.get("exclude_from_badge")),
        "notifications_enabled": app.get("notifications_enabled", True) is not False,
        # Community-scripts slug that the Register-chip flow attaches
        # to the app. Surfaced so the Updates tab helper section can
        # match this registered app against the CT's helper_slug and
        # display its installed/upstream versions.
        "helper_slug": app.get("helper_slug") or "",
    }


def get_category_presets() -> list:
    """Return the sorted list of unique category names sourced from
    helpers_cache. Powers the "Categoría" dropdown in the Web Link
    editor and the Apps dashboard filter. If the cache is missing or
    empty, returns a short built-in fallback so the UI never shows an
    empty preset list.
    """
    fallback = [
        "Adblock & DNS", "Authentication & Security", "Automation & Scheduling",
        "Backup & Recovery", "Containers & Docker", "Databases",
        "Documents & Notes", "Files & Downloads", "Media & Streaming",
        "Miscellaneous", "Monitoring & Analytics", "Network & Firewall",
    ]
    try:
        import managed_installs
        cache = managed_installs._fetch_helpers_cache() or {}
    except Exception:
        return fallback
    seen: set = set()
    for entry in cache.values():
        if not isinstance(entry, dict):
            continue
        for name in entry.get("category_names") or []:
            if isinstance(name, str) and name.strip():
                seen.add(name.strip())
    return sorted(seen) if seen else fallback


def suggest_category_for(name_or_slug: str) -> Optional[str]:
    """Look up a category preset by app name/slug against helpers_cache.
    Powers the auto-fill in the Web Link editor — when the user types
    a name that matches a catalog entry, the category dropdown
    pre-selects the first category_names value. Returns None when the
    name has no match or the cache is unavailable.
    """
    if not name_or_slug:
        return None
    needle = name_or_slug.strip().lower()
    if not needle:
        return None
    try:
        import managed_installs
        cache = managed_installs._fetch_helpers_cache() or {}
    except Exception:
        return None
    for slug, entry in cache.items():
        if not isinstance(entry, dict):
            continue
        if slug == needle or (entry.get("name") or "").lower() == needle:
            cats = entry.get("category_names") or []
            if cats and isinstance(cats[0], str) and cats[0].strip():
                return cats[0].strip()
            return None
    return None


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


def get_catalog_entry(slug: str, vmid=None) -> Optional[dict]:
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

    # When the caller supplies a CT, return the detector that actually
    # extracts a version there.  This makes catalog search work for manual
    # and legacy layouts too, not only for the helper-derived primary slug.
    tracking = None
    if hint:
        resolved = dict(hint)
        if vmid is not None:
            resolved, _version, _source, _error = _select_working_hint_detector(vmid, resolved)
        tracking = {k: v for k, v in resolved.items()
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

    # First category name from helpers_cache — auto-fills the port's
    # Categoría field when the user picks this app from the catalog.
    category = None
    cat_names = catalog.get("category_names") or []
    if cat_names and isinstance(cat_names[0], str) and cat_names[0].strip():
        category = cat_names[0].strip()

    return {
        "slug": slug,
        "name": catalog.get("name") or (hint.get("name") if isinstance(hint, dict) else None) or slug,
        "logo_url": (
            (hint.get("logo") if isinstance(hint, dict) else "")
            or catalog.get("logo") or ""
        ) or None,
        "website": catalog.get("website") or "",
        "default_ports": default_ports,
        "category": category,
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
        out[str(vmid)] = [
            {**_summarise_app(a), 'state_revision': sidecar.get('_revision')}
            for a in apps
        ]
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

# Docker-published endpoints are a different concept from applications
# installed natively in the LXC.  Keep a short-lived, read-only cache of
# container → host-port mappings so the App editor can offer web links under
# the Docker entry without registering every container as an independent LXC
# application.
_docker_web_links_cache: dict = {}
_docker_web_links_lock = threading.RLock()

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
    executable_paths: dict = {}   # path → [(slug, det), …]
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
                    _add(executable_paths, bp, slug, det)
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
                    _add(executable_paths, pp, slug, det)
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
        # No ``-type f``: venv/bin/python and /usr/bin tools are commonly
        # symlinks.  Actual version execution below rejects broken/wrong
        # targets, so existence is only a cheap batching pre-filter.
        rc, out, _ = _pct_exec(vmid, ["find"] + list(paths) + ["-maxdepth", "0", "-print"])
        if rc not in (0, 1):
            return
        for line in out.splitlines():
            p = line.strip()
            if p in paths:
                for slug, det in paths[p]:
                    _record(slug, det)

    _probe_paths(executable_paths)
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

    docker_runtime_available = False
    if docker_containers:
        rc, out, _ = _pct_exec(vmid, ["docker", "ps", "-a", "--format", "{{.Names}}"])
        if rc == 0:
            docker_runtime_available = True
            present = {line.strip() for line in out.splitlines() if line.strip()}
            for cn, entries in docker_containers.items():
                if cn in present:
                    for slug, det in entries:
                        _record(slug, det)

    # A path/package/container-name match is only a candidate.  Prove it by
    # extracting a real version with that detector before surfacing an app to
    # the user.  This eliminates the generic /root/.slug false positives and
    # stale files left behind by migrations.
    verified: dict = {}
    for slug, detectors in matched.items():
        hint = hints.get(slug) or {}
        for detector in detectors:
            probe = _detector_probe_config(hint, detector)
            try:
                version, _error = detect_installed_version(vmid, probe)
            except (KeyError, TypeError, ValueError):
                version = None
            if not version:
                continue
            enriched = dict(detector)
            enriched["detected_version"] = version
            enriched["detector_verified"] = True
            verified.setdefault(slug, []).append(enriched)

    # A just-started CT can answer ``docker ps`` a moment after the initial
    # batched ``find /usr/bin/docker`` probe failed.  In that narrow window a
    # Docker child such as Portainer used to be cached as a native LXC app for
    # 60 seconds.  A successful Docker API call proves the parent runtime is
    # available, so retry Docker's normal curated detector and only publish it
    # when it also yields a real version.
    if docker_runtime_available and "docker" not in verified:
        docker_hint = hints.get("docker") or {}
        for detector, _source in _ordered_hint_detectors(docker_hint):
            probe = _detector_probe_config(docker_hint, detector)
            try:
                version, _error = detect_installed_version(vmid, probe)
            except (KeyError, TypeError, ValueError):
                version = None
            if not version:
                continue
            enriched = dict(detector)
            enriched["detected_version"] = version
            enriched["detector_verified"] = True
            verified["docker"] = [enriched]
            break

    with _detected_apps_lock:
        _detected_apps_cache[key] = (now, {slug: list(dets) for slug, dets in verified.items()})
    return verified


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


def _docker_container_slug_index() -> dict:
    """Map a declared ``container_name`` to the catalog slug that declares it.

    Only detectors carrying curated runtime evidence appear here, which keeps
    the mapping conservative: a container merely called "postgres" is not
    claimed by an app, because no verified detector says it is.
    """
    global _docker_slug_index_cache
    hints = _fetch_tracking_hints()
    with _docker_remote_config_lock:
        previous, index = _docker_slug_index_cache
        if previous is hints:
            return index
    index = {}
    for slug, hint in (hints or {}).items():
        for detector in _iter_hint_detectors(hint):
            if detector.get("installed_via") not in ("docker_label", "docker_exec"):
                continue
            name = str(detector.get("container_name") or "").strip().lower()
            if name:
                index.setdefault(name, slug)
    with _docker_remote_config_lock:
        _docker_slug_index_cache = (hints, index)
    return index


def _docker_service_catalog_meta(service: str, container: str, image: str) -> dict:
    """Best-effort display metadata for a Docker workload.

    Identity remains the real container/image reported by Docker.  Catalog
    matching is used only for a friendly label/logo; a failed match never
    hides a published endpoint or turns the workload into an App Watch.
    """
    image_base = image.split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0]
    raw_candidates = [service, container, image_base]
    candidates: list[str] = []
    # A curated docker detector names the container it runs in, which is the
    # only reliable bridge from a container to its catalog entry: Immich's
    # service is "immich-server" and its image is "immich-server", but the
    # application is "immich". Heuristic name matching never gets there.
    declared = _docker_container_slug_index().get(str(container or "").strip().lower())
    if declared:
        candidates.append(declared)
    for raw in raw_candidates:
        candidate = re.sub(r"[^a-z0-9._-]+", "-", str(raw or "").strip().lower()).strip("-._")
        if candidate and candidate not in candidates:
            candidates.append(candidate)
        for suffix in ("-ce", "-ee"):
            if candidate.endswith(suffix):
                base = candidate[:-len(suffix)]
                if base and base not in candidates:
                    candidates.append(base)

    hints = _fetch_tracking_hints() or {}
    for candidate in candidates:
        hint = hints.get(candidate) or {}
        catalog = _catalog_lookup(candidate) or {}
        if hint or catalog:
            logo = hint.get("logo") or catalog.get("logo")
            return {
                "slug": candidate,
                "name": catalog.get("name") or hint.get("name") or service or container,
                "logo_url": logo if isinstance(logo, str) and logo.startswith(("http://", "https://")) else None,
            }
    return {"slug": None, "name": service or container, "logo_url": None}


def _probe_docker_web_links(vmid) -> list[dict]:
    """Return running Docker workloads that publish TCP ports on the LXC.

    The result is suggestion-only.  No sidecar entry is written and no port is
    assumed to be HTTP until the user explicitly adds it in the editor.  IPv4
    and IPv6 bindings of the same host port are deduplicated; loopback-only
    bindings are omitted because they cannot form a usable remote LXC link.
    """
    key = str(vmid)
    now = time.time()
    with _docker_web_links_lock:
        cached = _docker_web_links_cache.get(key)
        if cached and (now - cached[0]) < _PORT_PROBE_TTL_SEC:
            return [dict(item) for item in cached[1]]

    rc, out, _ = _pct_exec(vmid, ["docker", "ps", "-q"], timeout=10)
    if rc != 0:
        result: list[dict] = []
    else:
        container_ids = [line.strip() for line in out.splitlines() if line.strip()][:_DOCKER_MAX_IMAGES]
        result = []
        if container_ids:
            rc, inspect_out, _ = _pct_exec(
                vmid,
                ["docker", "inspect", "--format", "{{json .}}", *container_ids],
                timeout=20,
            )
            if rc == 0:
                for raw in inspect_out.splitlines():
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    container = str(obj.get("Name") or "").lstrip("/")
                    config = obj.get("Config") or {}
                    image = str(config.get("Image") or "").strip()
                    labels = config.get("Labels") or {}
                    service = str(labels.get("com.docker.compose.service") or container).strip()
                    meta = _docker_service_catalog_meta(service, container, image)
                    ports = (obj.get("NetworkSettings") or {}).get("Ports") or {}
                    seen_host_ports: set[int] = set()
                    for container_endpoint, bindings in ports.items():
                        if not str(container_endpoint).endswith("/tcp") or not isinstance(bindings, list):
                            continue
                        try:
                            container_port = int(str(container_endpoint).split("/", 1)[0])
                        except (TypeError, ValueError):
                            continue
                        for binding in bindings:
                            if not isinstance(binding, dict):
                                continue
                            host_ip = str(binding.get("HostIp") or "").strip()
                            if host_ip in {"127.0.0.1", "::1"}:
                                continue
                            try:
                                host_port = int(binding.get("HostPort"))
                            except (TypeError, ValueError):
                                continue
                            if not (1 <= host_port <= 65535) or host_port in seen_host_ports:
                                continue
                            seen_host_ports.add(host_port)
                            scheme = "https" if host_port in {443, 4443, 8443, 9443} or container_port in {443, 4443, 8443, 9443} else "http"
                            result.append({
                                "container_name": container,
                                "service_name": meta["name"],
                                "service_slug": meta["slug"],
                                "image": image,
                                "host_port": host_port,
                                "container_port": container_port,
                                "scheme": scheme,
                                "web_path": "/",
                                "logo_url": meta["logo_url"],
                            })
        result.sort(key=lambda item: (str(item.get("service_name") or "").lower(), int(item.get("host_port") or 0)))

    with _docker_web_links_lock:
        _docker_web_links_cache[key] = (now, result)
    return [dict(item) for item in result]


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


def invalidate_suggestion_probes(vmid) -> None:
    """Discard the short-lived discovery probes for one container."""
    key = str(vmid)
    with _detected_apps_lock:
        _detected_apps_cache.pop(key, None)
    with _cache_lock:
        _port_probe_cache.pop(key, None)
    with _docker_web_links_lock:
        _docker_web_links_cache.pop(key, None)
    with _file_probe_lock:
        stale = [cache_key for cache_key in _file_probe_cache if cache_key[0] == key]
        for cache_key in stale:
            _file_probe_cache.pop(cache_key, None)


def get_suggestions(vmid, force: bool = False) -> dict:
    if force:
        invalidate_suggestion_probes(vmid)
    ports = _probe_listening_ports(vmid)
    web_hint = None
    for p in ports:
        if p in _KNOWN_WEB_PORTS:
            web_hint = "/"
            break
    meta = _helper_slug_meta(vmid) or {}
    slug = meta.get("slug")
    # Suppress base-OS helper slugs from the suggestion pipeline.
    # community-scripts publishes bare-OS templates (alpine, debian,
    # ubuntu, fedora, archlinux, gentoo, opensuse) under the same
    # helpers_cache the App tab uses to seed detection, so a CT that
    # only has the OS installed was showing up as "detected app:
    # Alpine Linux" and inviting the user to register the OS as if
    # it were an application. These are not trackable apps — treat
    # the slug as absent for suggestion purposes so the panel goes
    # straight to the empty state instead.
    if slug in {"alpine", "archlinux", "archlinux-vm", "debian", "fedora", "gentoo", "opensuse", "ubuntu"}:
        slug = None
        meta = {}
    # Resolve all verified runtime detectors before building the primary
    # suggestion.  On a cold Docker CT, legacy helper identity can briefly
    # name a child container (for example Portainer).  If that child is proven
    # to be Docker-hosted and Docker Engine is also proven, Docker is the LXC
    # application; the child remains a workload/link beneath it.
    hints_map = _fetch_tracking_hints() or {}
    detected_map = _probe_detected_apps_map(vmid) if hints_map else {}
    primary_matches = detected_map.get(slug) or []
    primary_is_docker_workload = bool(primary_matches) and all(
        detector.get("installed_via") in ("docker_label", "docker_exec")
        for detector in primary_matches
    )
    if "docker" in detected_map and primary_is_docker_workload:
        slug = "docker"
        meta = {"slug": "docker", "name": "Docker"}
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
        tracking, _detected_version, _detector_source, _detector_error = (
            _select_working_hint_detector(vmid, tracking)
        )
        # Candidate arrays remain in the server-side catalog for auto-heal;
        # the editor only needs the detector selected for this CT.
        tracking.pop("file_fallbacks", None)
        tracking.pop("alt_detectors", None)

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
    # Docker workloads are not native LXC applications.  Once Docker is
    # detected (or already registered), docker_label/docker_exec matches are
    # represented as published service links under Docker rather than generic
    # application chips.  Native matches remain visible and existing
    # independently registered apps are never modified.
    docker_workload_detected = any(
        det_slug != "docker" and detectors and all(
            detector.get("installed_via") in ("docker_label", "docker_exec")
            for detector in detectors
        )
        for det_slug, detectors in detected_map.items()
    )
    docker_host_detected = (
        docker_registered or slug == "docker" or "docker" in detected_map
        or docker_workload_detected
    )
    docker_web_links = _probe_docker_web_links(vmid) if docker_host_detected else []
    extras: list = []
    # Applications proven to run inside Docker are not registrable apps — see
    # the skip below — but discarding them entirely made the panel answer "no
    # applications detected" for a container whose version had just been read
    # successfully. They are reported separately so the UI can show what is in
    # there without offering a second, competing update path.
    docker_workloads: list = []
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
        if docker_host_detected and matched_detectors:
            all_docker = all(
                d.get("installed_via") in ("docker_label", "docker_exec")
                for d in matched_detectors
            )
            if all_docker:
                workload_name = det_catalog.get("name") or det_hint.get("name") or det_slug
                workload_logo = ""
                for candidate in (det_hint.get("logo"), det_catalog.get("logo")):
                    if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                        workload_logo = candidate
                        break
                workload_container = (working or {}).get("container_name") or ""
                # The detector that actually matched, minus everything that
                # would make this app check an upstream of its own: the image
                # it runs on is what says whether there is a new version.
                workload_tracking = {
                    key: value for key, value in (working or {}).items()
                    if key in _DETECTOR_FIELDS or key == "installed_via"
                }
                workload_tracking["installed_regex"] = (
                    (working or {}).get("installed_regex")
                    or det_hint.get("installed_regex")
                    or det_hint.get("tag_regex")
                    or ""
                )
                workload_tracking["detector_verified"] = True
                workload_tracking["detector_source"] = "runtime_probe"
                workload_tracking["detected_version"] = (working or {}).get("detected_version") or ""
                workload_tracking["update_via"] = "docker"
                docker_workloads.append({
                    "slug": det_slug,
                    "name": workload_name,
                    "logo_url": workload_logo or None,
                    "container_name": workload_container,
                    "installed_version": (working or {}).get("detected_version") or None,
                    "installed_via": (working or {}).get("installed_via") or None,
                    "tracking_suggestion": workload_tracking,
                    "default_ports": sorted({
                        link["host_port"] for link in docker_web_links
                        if link.get("container_name") == workload_container
                        and isinstance(link.get("host_port"), int)
                    }),
                    "category": suggest_category_for(det_slug),
                })
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
            det_tracking["detected_version"] = working.get("detected_version")
            det_tracking["detector_verified"] = True
            det_tracking["detector_source"] = "runtime_probe"
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
        # Auto-fill Categoría preset from helpers_cache for extras too
        # so the Register button pre-selects the category on the port.
        det_category = None
        det_cat_names = det_catalog.get("category_names") or []
        if det_cat_names and isinstance(det_cat_names[0], str) and det_cat_names[0].strip():
            det_category = det_cat_names[0].strip()
        extras.append({
            "slug": det_slug,
            "name": det_name,
            "logo_url": det_logo or None,
            "default_ports": det_ports,
            "category": det_category,
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
        # Categoría preset for the primary detection — same lookup as
        # get_catalog_entry so the Register button pre-selects it.
        "category": suggest_category_for(slug),
        "extras": extras,
        "docker_workloads": sorted(docker_workloads, key=lambda item: item["name"].lower()),
        "docker_web_links": docker_web_links,
    }
