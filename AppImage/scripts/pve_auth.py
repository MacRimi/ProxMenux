"""Proxmox accounts in the Monitor: those of Proxmox VE, or of Proxmox Backup
Server when the Monitor runs on one.

The Monitor keeps no session of its own for them: the browser holds a ticket of
the local Proxmox API, and every check asks that API what the ticket can do, so
its expiry, realms, second factor and permissions stay those of the product.
Both APIs answer the same calls; they differ in their port, the prefix of their
tickets, the cookie of their web interface and the file of their users. What a
user can do follows their privileges on `/`:

  Sys.Modify  full access
  Sys.Audit   read-only
  otherwise   no access
"""

import hashlib
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# The local API of this host. Its certificate names the node, not the loopback
# address, and nothing between the Monitor and the Proxmox proxy can be
# intercepted on loopback: the connection is not checked against a CA.
PRODUCTS = {
    "pve": {"api": "https://127.0.0.1:8006/api2/json", "prefix": "PVE", "cookie": "PVEAuthCookie",
            "users": "/etc/pve/user.cfg"},
    "pbs": {"api": "https://127.0.0.1:8007/api2/json", "prefix": "PBS", "cookie": "PBSAuthCookie",
            "users": "/etc/proxmox-backup/user.cfg"},
}


def _product():
    """The Proxmox product of this host, as the rest of the Monitor reads it."""
    try:
        from pbs_manager import is_pbs_host
        return PRODUCTS["pbs"] if is_pbs_host() else PRODUCTS["pve"]
    except Exception:
        return PRODUCTS["pve"]


def cookie_name():
    """The cookie the web interface of this host keeps its session in."""
    return _product()["cookie"]


_CONTEXT = ssl.create_default_context()
_CONTEXT.check_hostname = False
_CONTEXT.verify_mode = ssl.CERT_NONE

# A checked ticket is trusted for a minute: a permission removed or a ticket
# expired in Proxmox reaches the Monitor within that time.
CHECK_TTL = 60
_cache = {}
_cache_lock = threading.Lock()

_TICKET = re.compile(r"^(PVE|PBS):[^:!\s]+@[^:\s]+:[0-9A-F]{8}::[A-Za-z0-9+/=]+$")
_USERNAME = re.compile(r"^[^\s:@/]{1,64}$")
_REALM = re.compile(r"^[A-Za-z][A-Za-z0-9.\-_]{1,31}$")


class PVEAuthError(Exception):
    """A refusal to show as it is: never carries the reply of Proxmox."""


def is_ticket(token):
    """A ticket of the Proxmox product of this host."""
    return (isinstance(token, str) and bool(_TICKET.match(token))
            and token.startswith(_product()["prefix"] + ":"))


def _request(method, path, data=None, ticket=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    product = _product()
    request = urllib.request.Request(product["api"] + path, data=body, method=method)
    if ticket:
        request.add_header("Cookie", product["cookie"] + "=" + urllib.parse.quote(ticket, safe=""))
    try:
        with urllib.request.urlopen(request, context=_CONTEXT, timeout=10) as response:
            return response.status, json.loads(response.read(1024 * 1024) or b"{}").get("data")
    except urllib.error.HTTPError as error:
        return error.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def scope_of(privileges):
    """The Monitor scope the privileges on `/` give."""
    if privileges.get("Sys.Modify"):
        return "full_admin"
    if privileges.get("Sys.Audit"):
        return "read_only"
    return None


def validate(ticket):
    """(username, scope) of a valid ticket with access to the Monitor, else
    (None, None)."""
    if not is_ticket(ticket):
        return None, None
    key = hashlib.sha256(ticket.encode()).hexdigest()
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
    status, data = _request("GET", "/access/permissions?path=%2F", ticket=ticket)
    result = (None, None)
    if status == 200 and isinstance(data, dict):
        scope = scope_of(data.get("/") or {})
        if scope:
            result = (ticket.split(":")[1], scope)
    with _cache_lock:
        if len(_cache) > 512:
            _cache.clear()
        _cache[key] = (now + CHECK_TTL, result)
    return result


# The users and groups of the product, from the file it keeps them in on this
# host; read again when it changes. Proxmox VE writes `user:<id>:...` and
# `group:<name>:<members>:...` lines; Proxmox Backup Server writes sections
# such as `user: <id>` and has no groups.
_directory = {"path": None, "mtime": None, "users": [], "groups": {}}
_directory_lock = threading.Lock()


def _read_directory():
    import os
    path = _product()["users"]
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return [], {}
    with _directory_lock:
        if _directory["path"] == path and _directory["mtime"] == mtime:
            return _directory["users"], _directory["groups"]
    users, groups = [], {}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.rstrip("\n")
                if line.startswith("user: "):
                    userid = line[len("user: "):].strip()
                    if userid:
                        users.append(userid)
                    continue
                fields = line.split(":")
                if fields[0] == "user" and len(fields) > 1 and fields[1]:
                    users.append(fields[1])
                elif fields[0] == "group" and len(fields) > 2 and fields[1]:
                    groups[fields[1]] = [member for member in fields[2].split(",") if member]
    except OSError:
        return [], {}
    with _directory_lock:
        _directory.update(path=path, mtime=mtime, users=users, groups=groups)
    return users, groups


def groups_of(userid):
    """The Proxmox groups `userid` belongs to."""
    _users, groups = _read_directory()
    return {name for name, members in groups.items() if userid in members}


def directory():
    """The users and groups to choose from when giving them a profile."""
    users, groups = _read_directory()
    return {"users": sorted(users), "groups": sorted(groups)}


def realms():
    """The realms to choose from, as Proxmox lists them to its login form."""
    status, data = _request("GET", "/access/domains")
    if status != 200 or not isinstance(data, list):
        return []
    return [{"realm": r.get("realm"), "type": r.get("type"), "comment": r.get("comment") or "",
             "default": bool(r.get("default"))}
            for r in data if isinstance(r, dict) and r.get("realm")]


def _granted(data):
    """The answer for a full ticket: refused when it gives no access."""
    ticket = data.get("ticket") if isinstance(data, dict) else None
    username, scope = validate(ticket)
    if not username:
        raise PVEAuthError("This Proxmox account has no access to the Monitor.")
    return {"ticket": ticket, "username": username, "scope": scope}


def login(username, password, realm):
    """First step: a ticket, or the second factor Proxmox asks for."""
    if not isinstance(username, str) or not isinstance(password, str) or not password:
        raise PVEAuthError("Enter the user and password.")
    if "@" in username:
        username, realm = username.rsplit("@", 1)
    if not _USERNAME.match(username or "") or not _REALM.match(realm or ""):
        raise PVEAuthError("Enter the user and realm.")
    status, data = _request("POST", "/access/ticket",
                            {"username": f"{username}@{realm}", "password": password})
    if status != 200 or not isinstance(data, dict):
        raise PVEAuthError("Login failed.")
    if data.get("NeedTFA"):
        challenge = data.get("ticket") or ""
        # PVE:!tfa!<methods as JSON, its colons as %3A>:<time>::<signature> (PBS: alike)
        try:
            offered = json.loads(urllib.parse.unquote(challenge.split("!tfa!", 1)[1].split(":", 1)[0]))
            methods = sorted(offered.keys())
        except (IndexError, ValueError, AttributeError):
            methods = []
        return {"need_tfa": True, "challenge": challenge, "username": f"{username}@{realm}",
                "methods": [m for m in methods if m in ("totp", "recovery", "webauthn", "yubico")]}
    return _granted(data)


def second_factor(username, challenge, code):
    """Second step: a TOTP code (six digits) or a recovery key."""
    if (not isinstance(username, str) or not isinstance(challenge, str)
            or not challenge.startswith(_product()["prefix"] + ":!tfa!") or not isinstance(code, str)):
        raise PVEAuthError("Login failed.")
    code = code.strip().replace(" ", "")
    if not code or len(code) > 64:
        raise PVEAuthError("Enter the code.")
    kind = "totp" if code.isdigit() and len(code) == 6 else "recovery"
    status, data = _request("POST", "/access/ticket",
                            {"username": username, "password": f"{kind}:{code}", "tfa-challenge": challenge})
    if status != 200 or not isinstance(data, dict):
        raise PVEAuthError("Login failed.")
    return _granted(data)


def renew(ticket):
    """A fresh ticket for a valid one, as the Proxmox web interface renews it."""
    if not is_ticket(ticket):
        raise PVEAuthError("Login failed.")
    status, data = _request("POST", "/access/ticket",
                            {"username": ticket.split(":")[1], "password": ticket})
    if status != 200 or not isinstance(data, dict):
        raise PVEAuthError("Login failed.")
    return _granted(data)
