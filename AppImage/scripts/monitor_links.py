"""Other ProxMenux Monitors reachable from this one: cluster nodes, PBS servers
and entries added by hand.

Only links are kept here. No credential is stored or sent: the browser opens
the other Monitor, which keeps its own sign-in.
"""

import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pbs_manager

LINKS_FILE = Path(os.environ.get("PROXMENUX_MONITOR_LINKS", "/usr/local/share/proxmenux/monitor_links.json"))
SSL_CONFIG_FILE = Path(os.environ.get("PROXMENUX_SSL_CONFIG", "/etc/proxmenux/ssl_config.json"))
STORAGE_CFG = Path("/etc/pve/storage.cfg")
MONITOR_PORT = 8008
PBS_UI_PORT = 8007
PROBE_TIMEOUT = 3
PROBE_TTL = 300
MAX_MANUAL = 64
PRODUCTS = ("pve", "pbs")

_lock = threading.Lock()
_probe_cache = {}
_snapshot = {"at": 0.0, "data": None}
_refresh_lock = threading.Lock()


class LinkError(ValueError):
    def __init__(self, message, *, code="monitor_links_save_failed", params=None):
        super().__init__(message)
        self.code = code
        self.params = params


def _load():
    try:
        data = json.loads(LINKS_FILE.read_text())
    except (OSError, ValueError):
        return {"manual": [], "overrides": {}}
    manual = data.get("manual") if isinstance(data.get("manual"), list) else []
    overrides = data.get("overrides") if isinstance(data.get("overrides"), dict) else {}
    return {"manual": [row for row in manual if isinstance(row, dict)], "overrides": overrides}


def _save(data):
    LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = LINKS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2))
    os.chmod(temporary, 0o600)
    os.replace(temporary, LINKS_FILE)


def normalize_url(value):
    """Return the origin of an http(s) address, or raise LinkError."""
    if not isinstance(value, str) or not value.strip():
        raise LinkError("Enter the address of the Monitor.", code="monitor_link_address_required")
    text = value.strip()
    if "://" not in text:
        text = "https://" + text
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise LinkError("The address must start with http:// or https:// and name a host.", code="monitor_link_invalid_address")
    if parsed.username or parsed.password:
        raise LinkError("The address must not contain a user or password.", code="monitor_link_address_credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise LinkError("The port of the address is not valid.", code="monitor_link_invalid_port") from exc
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}" + (f":{port}" if port else "")


def _local_scheme():
    try:
        return "https" if json.loads(SSL_CONFIG_FILE.read_text()).get("enabled") else "http"
    except (OSError, ValueError, AttributeError):
        return "http"


def _host_url(host, port, scheme=None):
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{scheme or _local_scheme()}://{host}:{port}"


def _is_private(host):
    """Only addresses in private ranges are probed without being asked to."""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    try:
        return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_private for a in addresses)
    except ValueError:
        return False


def _own_addresses():
    addresses = set()
    try:
        import psutil
        for entries in psutil.net_if_addrs().values():
            for entry in entries:
                if entry.family in (socket.AF_INET, socket.AF_INET6):
                    addresses.add(entry.address.split("%")[0])
    except Exception:
        pass
    return addresses


def _is_this_host(host):
    """A PBS installed next to PVE is named localhost or one of the host's own addresses."""
    try:
        resolved = {info[4][0].split("%")[0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    own = _own_addresses()
    try:
        return bool(resolved) and all(ipaddress.ip_address(a).is_loopback or a in own for a in resolved)
    except ValueError:
        return False


def _cluster_nodes():
    try:
        result = subprocess.run(["pvesh", "get", "/cluster/status", "--output-format", "json"],
                                capture_output=True, text=True, timeout=8)
        rows = json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    nodes = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("type") == "node" and not row.get("local") and row.get("name") and row.get("ip"):
            nodes.append({"key": f"cluster:{row['name']}", "name": str(row["name"]), "product": "pve",
                          "group": "cluster", "host": str(row["ip"])})
    return nodes


def _storage_pbs():
    try:
        text = STORAGE_CFG.read_text()
    except OSError:
        return []
    servers, current = [], None
    for line in text.splitlines():
        header = re.match(r"^(\w+):\s*(\S+)", line)
        if header:
            current = {"name": header.group(2), "port": PBS_UI_PORT} if header.group(1) == "pbs" else None
            if current is not None:
                servers.append(current)
            continue
        option = re.match(r"^\s+(server|port|fingerprint)\s+(\S+)", line)
        if current is not None and option:
            current[option.group(1)] = option.group(2)
    return [row for row in servers if row.get("server")]


def _pbs_servers():
    found = {}
    for row in _storage_pbs():
        host = row["server"]
        port = row.get("port") if str(row.get("port", "")).isdigit() else PBS_UI_PORT
        found.setdefault(host, {"name": row["name"], "native_url": _host_url(host, port, "https")})
    try:
        for row in pbs_manager.public_servers():
            host = urllib.parse.urlsplit(row.get("url", "")).hostname
            if host:
                found.setdefault(host, {"name": row.get("name") or host, "native_url": normalize_url(row["url"])})
    except Exception:
        pass
    servers, local = [], None
    for host, info in found.items():
        if _is_this_host(host):
            # Its web interface is on the address the browser already uses.
            if local is None:
                local = {"key": "pbs:local", "name": info["name"], "product": "pbs", "group": "pbs", "local": True}
                servers.append(local)
            continue
        servers.append({"key": f"pbs:{host}", "name": info["name"], "product": "pbs", "group": "pbs",
                        "host": host, "native_url": info["native_url"]})
    return servers


def _probe(url):
    """True when a ProxMenux Monitor answers at url; nothing is sent but the request."""
    now = time.monotonic()
    with _lock:
        cached = _probe_cache.get(url)
        if cached and cached[0] > now:
            return cached[1]
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # liveness only: no credential or token is ever sent
    online = False
    try:
        request = urllib.request.Request(url + "/api/auth/status", headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT, context=context) as response:
            online = response.status == 200 and "auth_enabled" in json.loads(response.read(4096))
    except Exception:
        online = False
    with _lock:
        if len(_probe_cache) > 256:
            _probe_cache.clear()
        _probe_cache[url] = (now + PROBE_TTL, online)
    return online


def _resolve(entry, override):
    """Pick the Monitor address and its state for one discovered or manual entry."""
    if override.get("url"):
        return override["url"], "online" if _probe(override["url"]) else "offline"
    if entry.get("url"):
        return entry["url"], "online" if _probe(entry["url"]) else "offline"
    if entry.get("local"):
        return None, "local"
    host = entry["host"]
    if not _is_private(host):
        return None, "unknown"
    for scheme in (_local_scheme(), "https" if _local_scheme() == "http" else "http"):
        url = _host_url(host, MONITOR_PORT, scheme)
        if _probe(url):
            return url, "online"
    return _host_url(host, MONITOR_PORT), "offline"


def list_links(include_hidden=False):
    platform = pbs_manager.get_platform()
    data = _load()
    entries = []
    if platform.get("product") != "pbs":
        entries += _cluster_nodes() + _pbs_servers()
    for row in data["manual"]:
        entries.append({"key": f"manual:{row.get('id')}", "name": row.get("name") or row.get("url"),
                        "product": row.get("product") if row.get("product") in PRODUCTS else "pve",
                        "group": "pbs" if row.get("product") == "pbs" else "standalone",
                        "url": row.get("url"), "manual": True})
    visible = [e for e in entries if include_hidden or not data["overrides"].get(e["key"], {}).get("hidden")]
    with ThreadPoolExecutor(max_workers=8) as executor:
        resolved = list(executor.map(lambda e: _resolve(e, data["overrides"].get(e["key"], {})), visible))
    links = []
    for entry, (url, state) in zip(visible, resolved):
        override = data["overrides"].get(entry["key"], {})
        links.append({"key": entry["key"], "name": entry["name"], "product": entry["product"],
                      "group": entry["group"], "url": url, "status": state,
                      "native_url": entry.get("native_url"), "manual": bool(entry.get("manual")),
                      "local": bool(entry.get("local")),
                      "hidden": bool(override.get("hidden")), "custom_url": bool(override.get("url"))})
    return {"self": {"name": platform.get("hostname") or socket.gethostname(), "product": platform.get("product")},
            "links": links}


def refresh():
    """Recompute the list with fresh probes and keep it for the header."""
    with _refresh_lock:
        with _lock:
            _probe_cache.clear()
        data = list_links(include_hidden=True)
        _snapshot.update(at=time.monotonic(), data=data)
        return data


def _refresh_quietly():
    try:
        refresh()
    except Exception:
        pass


def cached_links(include_hidden=False):
    """The last list at once; a stale one is renewed in the background."""
    data = _snapshot["data"]
    if data is None:
        data = refresh()
    elif time.monotonic() - _snapshot["at"] > PROBE_TTL and not _refresh_lock.locked():
        threading.Thread(target=_refresh_quietly, daemon=True, name="monitor-links-refresh").start()
    if include_hidden:
        return data
    return {**data, "links": [row for row in data["links"] if not row["hidden"]]}


def start_prewarmer():
    def loop():
        time.sleep(10)
        while True:
            _refresh_quietly()
            time.sleep(PROBE_TTL)
    threading.Thread(target=loop, daemon=True, name="monitor-links-prewarmer").start()


def add_link(payload):
    if not isinstance(payload, dict):
        raise LinkError("Invalid request.", code="monitor_link_invalid_request")
    name = str(payload.get("name") or "").strip()[:64]
    url = normalize_url(payload.get("url"))
    product = payload.get("product") if payload.get("product") in PRODUCTS else "pve"
    with _lock:
        data = _load()
        if len(data["manual"]) >= MAX_MANUAL:
            raise LinkError(f"At most {MAX_MANUAL} nodes can be added.", code="monitor_link_limit", params={"count": MAX_MANUAL})
        if any(row.get("url") == url for row in data["manual"]):
            raise LinkError("This address is already in the list.", code="monitor_link_duplicate")
        identifier = secrets.token_hex(6)
        data["manual"].append({"id": identifier, "name": name or urllib.parse.urlsplit(url).hostname,
                               "url": url, "product": product})
        _save(data)
    return f"manual:{identifier}"


def update_link(key, payload):
    if not isinstance(payload, dict):
        raise LinkError("Invalid request.", code="monitor_link_invalid_request")
    with _lock:
        data = _load()
        if key.startswith("manual:"):
            row = next((r for r in data["manual"] if f"manual:{r.get('id')}" == key), None)
            if row is None:
                raise LinkError("Node not found.", code="monitor_link_not_found")
            if "name" in payload:
                row["name"] = str(payload["name"] or "").strip()[:64] or row["name"]
            if payload.get("url"):
                row["url"] = normalize_url(payload["url"])
            if payload.get("product") in PRODUCTS:
                row["product"] = payload["product"]
        elif re.fullmatch(r"(cluster|pbs):[\w.:\-\[\]]{1,253}", key):
            override = data["overrides"].setdefault(key, {})
            if "url" in payload:
                if payload["url"]:
                    override["url"] = normalize_url(payload["url"])
                else:
                    override.pop("url", None)
            if "hidden" in payload:
                override["hidden"] = bool(payload["hidden"])
            if not override:
                data["overrides"].pop(key, None)
        else:
            raise LinkError("Node not found.", code="monitor_link_not_found")
        _save(data)


def delete_link(key):
    with _lock:
        data = _load()
        remaining = [r for r in data["manual"] if f"manual:{r.get('id')}" != key]
        if len(remaining) == len(data["manual"]):
            raise LinkError("Only nodes added by hand can be removed; detected ones can be hidden.", code="monitor_link_detected_remove")
        data["manual"] = remaining
        _save(data)
