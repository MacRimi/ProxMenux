"""Local PBS maintenance information and remote, read-only PBS monitoring."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

import auth_manager

try:
    from proxmox_platform import detect_platform
except ModuleNotFoundError:
    # Development checkout; AppImage bundles the canonical shared detector.
    _path = Path(__file__).resolve().parents[2] / "scripts/global/proxmox_platform.py"
    _spec = importlib.util.spec_from_file_location("proxmox_platform", _path)
    _platform_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_platform_module)
    detect_platform = _platform_module.detect_platform

_lock = threading.RLock()
_platform_cache = (0, {})
_status_cache = {}
PBS_SERVICES = ("proxmox-backup", "proxmox-backup-proxy")
MAX_RESPONSE = 4 * 1024 * 1024


class PBSError(ValueError):
    pass


def get_platform():
    global _platform_cache
    with _lock:
        if _platform_cache[0] <= time.monotonic():
            _platform_cache = (time.monotonic() + 60, detect_platform())
        return dict(_platform_cache[1])


def is_pbs_host():
    return get_platform().get("product") == "pbs"


def _servers_path():
    return auth_manager.CONFIG_DIR / "pbs_servers.json"


def _load_servers():
    try:
        data = json.loads(_servers_path().read_text())
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise ValueError()
        return data
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise PBSError("Could not read the PBS server configuration.") from exc


def _save_servers(servers):
    auth_manager.ensure_config_dir()
    descriptor, temporary = tempfile.mkstemp(prefix=".pbs-servers-", dir=auth_manager.CONFIG_DIR)
    try:
        with os.fdopen(descriptor, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(servers, handle, indent=2)
        os.replace(temporary, _servers_path())
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    _status_cache.clear()


def public_servers():
    fields = ("id", "name", "url", "token_id", "fingerprint")
    with _lock:
        return [{**{key: row.get(key, "") for key in fields}, "has_token": bool(row.get("token_secret"))}
                for row in _load_servers()]


def _validate_server(data, previous=None):
    if not isinstance(data, dict):
        raise PBSError("Invalid PBS server configuration.")
    previous = previous or {}
    row = {field: data.get(field, previous.get(field, ""))
           for field in ("name", "url", "token_id", "token_secret", "fingerprint")}
    if any(not isinstance(value, str) or len(value) > 4096 for value in row.values()):
        raise PBSError("Invalid PBS connection field.")
    row["name"] = row["name"].strip()
    row["url"] = row["url"].strip().rstrip("/")
    try:
        parts = urlsplit(row["url"])
        parts.port
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment):
            raise ValueError()
    except ValueError as exc:
        raise PBSError("Use an HTTPS PBS URL without embedded credentials, query or fragment.") from exc
    if not row["name"] or len(row["name"]) > 128:
        raise PBSError("A server name of at most 128 characters is required.")
    row["token_id"] = row["token_id"].strip()
    if not re.fullmatch(r"[^\s:!]+@[^\s:!]+![^\s:!]+", row["token_id"]):
        raise PBSError("Enter a PBS API token ID in user@realm!token format.")
    if (not row["token_secret"] or not row["token_secret"].isascii()
            or any(char.isspace() or ord(char) < 32 for char in row["token_secret"])):
        raise PBSError("A valid API token secret is required.")
    if not row["token_id"].isascii():
        raise PBSError("Invalid API token ID.")
    fingerprint = row["fingerprint"].strip().lower().replace(":", "")
    if fingerprint and not re.fullmatch("[a-f0-9]{64}", fingerprint):
        raise PBSError("The certificate fingerprint must be SHA256 (64 hex characters).")
    row["fingerprint"] = fingerprint
    return row


def _remote_get(server, endpoint):
    """Validate the TLS peer BEFORE transmitting the PBS token (no redirects)."""
    parts = urlsplit(server["url"])
    fingerprint = server.get("fingerprint")
    if fingerprint:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # Authenticated by the explicit pin below.
    else:
        context = ssl.create_default_context()
    connection = http.client.HTTPSConnection(parts.hostname, parts.port or 443,
                                              timeout=5, context=context)
    try:
        connection.connect()
        if fingerprint:
            actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if not hmac.compare_digest(actual, fingerprint):
                raise PBSError("PBS certificate fingerprint does not match. No credentials were sent.")
        path = parts.path.rstrip("/") + "/api2/json" + endpoint
        connection.request("GET", path, headers={
            "Accept": "application/json",
            "Authorization": "PBSAPIToken=" + server["token_id"] + ":" + server["token_secret"],
        })
        response = connection.getresponse()
        content = response.read(MAX_RESPONSE + 1)
        if response.status in (401, 403):
            raise PBSError("PBS rejected the API token or its permissions. Check both the user and token ACLs.")
        if response.status != 200 or len(content) > MAX_RESPONSE:
            raise PBSError("PBS returned an invalid response. Redirects are not followed.")
        document = json.loads(content)
        if not isinstance(document, dict) or "data" not in document:
            raise PBSError("PBS returned an invalid JSON document.")
        return document["data"]
    except PBSError:
        raise
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise PBSError("Could not connect to PBS over verified HTTPS. Check the address, certificate and service.") from exc
    finally:
        connection.close()


def save_server(data):
    identifier = data.get("id") if isinstance(data, dict) else None
    if identifier is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(identifier)):
        raise PBSError("Invalid PBS server ID.")
    with _lock:
        previous = next((row for row in _load_servers() if row["id"] == identifier), None)
    row = _validate_server(data, previous)
    # /version may be public; validate credentials on the protected status API.
    usage = _remote_get(row, "/status/datastore-usage")
    if not isinstance(usage, list):
        raise PBSError("PBS returned an invalid datastore list.")
    row.update(id=identifier or "pbs-" + secrets.token_hex(6), revision=secrets.token_hex(16))
    with _lock:
        servers = _load_servers()
        if previous is None and len(servers) >= 32:
            raise PBSError("At most 32 PBS connections may be configured.")
        servers = [existing for existing in servers if existing["id"] != row["id"]]
        _save_servers([*servers, row])
    return row["id"]


def delete_server(identifier):
    with _lock:
        servers = _load_servers()
        remaining = [row for row in servers if row["id"] != identifier]
        if len(remaining) == len(servers):
            raise PBSError("PBS server not found.")
        _save_servers(remaining)


def _cli(*arguments):
    try:
        result = subprocess.run(["proxmox-backup-manager", *arguments, "--output-format", "json"],
                                check=True, text=True, capture_output=True, timeout=8)
        data = json.loads(result.stdout)
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise ValueError()
        return data
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise PBSError("Could not read PBS " + " ".join(arguments[:2]) + ". Check its service and permissions.") from exc


def _local_datastores():
    stores = _cli("datastore", "list")
    result = []
    for store in stores:
        row = {"name": store.get("name"), "path": store.get("path"),
               "maintenance_mode": store.get("maintenance-mode"), "total": None, "used": None, "avail": None}
        path = store.get("path")
        # A removable datastore directory may survive unmounting. Do not report
        # its underlying root filesystem as the missing datastore's capacity.
        inactive = store.get("backing-device") and not (path and os.path.ismount(path))
        if not path or inactive or store.get("maintenance-mode"):
            row["error"] = "Datastore is offline, in maintenance or has no mounted backing device."
        else:
            try:
                capacity = shutil.disk_usage(path)
                row.update(total=capacity.total, used=capacity.used, avail=capacity.free)
            except OSError:
                row["error"] = "Datastore filesystem is not available."
        result.append(row)
    return result


def _local_services():
    result = {}
    for service in PBS_SERVICES:
        try:
            check = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True, timeout=3)
            result[service] = check.stdout.strip() if check.returncode == 0 else "inactive"
        except (OSError, subprocess.SubprocessError):
            result[service] = "unknown"
    return result


def get_status(identifier):
    with _lock:
        cached = _status_cache.get(identifier)
        if cached and cached[0] > time.monotonic():
            return cached[1]
    errors = {}
    if identifier == "local":
        if not is_pbs_host():
            raise PBSError("The local host is not a PBS server.")
        name, version = "Local PBS", get_platform().get("version")
        services = _local_services()
        operations = {"datastores": _local_datastores,
                      "tasks": lambda: _cli("task", "list", "--all", "true", "--limit", "20"),
                      "sync": lambda: _cli("sync-job", "list"),
                      "verify": lambda: _cli("verify-job", "list"),
                      "prune": lambda: _cli("prune-job", "list")}
    else:
        with _lock:
            server = next((row for row in _load_servers() if row["id"] == identifier), None)
        if not server:
            raise PBSError("PBS server not found.")
        metadata = _remote_get(server, "/version")
        name, version = server["name"], metadata.get("version") if isinstance(metadata, dict) else None
        services = {}
        endpoints = {"datastores": "/status/datastore-usage", "tasks": "/nodes/localhost/tasks?limit=20",
                     "sync": "/admin/sync", "verify": "/admin/verify", "prune": "/admin/prune"}
        operations = {key: (lambda endpoint=path: _remote_get(server, endpoint)) for key, path in endpoints.items()}
    result = {"server": identifier, "name": name, "version": version, "services": services,
              "fetched_at": int(time.time()), "errors": errors}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {key: executor.submit(operation) for key, operation in operations.items()}
        for key, future in futures.items():
            try:
                data = future.result()
                if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
                    raise PBSError("PBS returned an invalid list.")
                result[key] = [{**row, "name": row.get("store", row.get("name"))} for row in data] if key == "datastores" else data
            except PBSError as exc:
                result[key] = None  # Unknown/forbidden is never presented as zero.
                errors[key] = str(exc)
    with _lock:
        if len(_status_cache) >= 33:
            _status_cache.clear()
        _status_cache[identifier] = (time.monotonic() + 15, result)
    return result
