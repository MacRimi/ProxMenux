"""Proxmox VE accounts in the Monitor.

The Monitor keeps no session of its own for them: the browser holds a Proxmox
VE ticket, and every check asks the local Proxmox VE API what that ticket can
do, so its expiry, realms, second factor and permissions stay those of
Proxmox VE. What a user can do follows their privileges on `/`:

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

# The local API of this host. Proxmox VE's certificate names the node, not the
# loopback address, and nothing between the Monitor and pveproxy can be
# intercepted on loopback: the connection is not checked against a CA.
PVE_API = "https://127.0.0.1:8006/api2/json"
_CONTEXT = ssl.create_default_context()
_CONTEXT.check_hostname = False
_CONTEXT.verify_mode = ssl.CERT_NONE

# A checked ticket is trusted for a minute: a permission removed or a ticket
# expired in Proxmox VE reaches the Monitor within that time.
CHECK_TTL = 60
_cache = {}
_cache_lock = threading.Lock()

_TICKET = re.compile(r"^PVE:[^:!\s]+@[^:\s]+:[0-9A-F]{8}::[A-Za-z0-9+/=]+$")
_USERNAME = re.compile(r"^[^\s:@/]{1,64}$")
_REALM = re.compile(r"^[A-Za-z][A-Za-z0-9.\-_]{1,31}$")


class PVEAuthError(Exception):
    """A refusal to show as it is: never carries Proxmox VE's reply."""


def is_ticket(token):
    return isinstance(token, str) and bool(_TICKET.match(token))


def _request(method, path, data=None, ticket=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(PVE_API + path, data=body, method=method)
    if ticket:
        request.add_header("Cookie", "PVEAuthCookie=" + urllib.parse.quote(ticket, safe=""))
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


def realms():
    """The realms to choose from, as Proxmox VE lists them to its login form."""
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
        raise PVEAuthError("This Proxmox VE account has no access to the Monitor.")
    return {"ticket": ticket, "username": username, "scope": scope}


def login(username, password, realm):
    """First step: a ticket, or the second factor Proxmox VE asks for."""
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
        # PVE:!tfa!<methods as JSON, its colons as %3A>:<time>::<signature>
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
            or not challenge.startswith("PVE:!tfa!") or not isinstance(code, str)):
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
    """A fresh ticket for a valid one, as the Proxmox VE web interface renews it."""
    if not is_ticket(ticket):
        raise PVEAuthError("Login failed.")
    status, data = _request("POST", "/access/ticket",
                            {"username": ticket.split(":")[1], "password": ticket})
    if status != 200 or not isinstance(data, dict):
        raise PVEAuthError("Login failed.")
    return _granted(data)
