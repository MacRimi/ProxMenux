"""Who did what with the access to the Monitor.

Sign-ins and their failures, the account and access mode, users and their
profiles, the rules of Proxmox VE accounts, the OpenID Connect settings, API
tokens, and every action a profile refused, each with the account that did
it and its address. Passwords, codes and tokens are never written here.

Recording never makes an operation fail: an error writing the log is
dropped. The log sits next to auth.json and keeps RETENTION_DAYS.
"""

import json
import os
import sqlite3
import threading
import time

RETENTION_DAYS = 90
# A refusal repeated by the same account on the same route and permission is
# written once per this many seconds: a script retrying in a loop does not
# fill the log.
REPEAT_SECONDS = 60

_lock = threading.Lock()
_ready_for = None
_writes = 0
_last_refusal = {}


def _path():
    import auth_manager
    return auth_manager.CONFIG_DIR / "access-log.db"


def _connect():
    global _ready_for
    path = _path()
    connection = sqlite3.connect(str(path), timeout=5)
    if _ready_for != str(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at INTEGER NOT NULL,
            event TEXT NOT NULL,
            actor TEXT,
            target TEXT,
            detail TEXT,
            ip TEXT,
            ok INTEGER NOT NULL DEFAULT 1)""")
        connection.execute("CREATE INDEX IF NOT EXISTS events_at ON events(at)")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        _ready_for = str(path)
    return connection


def client_ip():
    """The address of the current request, as the sign-in limits see it."""
    try:
        from flask import request
    except ImportError:
        return None
    try:
        if os.environ.get("PROXMENUX_TRUST_PROXY", "0") == "1":
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()[:64]
            real_ip = request.headers.get("X-Real-IP", "")
            if real_ip:
                return real_ip.strip()[:64]
        address = request.remote_addr or ""
        # An IPv4 client of a dual-stack socket reads as ::ffff:a.b.c.d.
        if address.startswith("::ffff:") and "." in address:
            address = address[len("::ffff:"):]
        return address[:64] or None
    except RuntimeError:
        return None  # outside a request


def record(event, actor=None, target=None, detail=None, ok=True, ip=None):
    """Write one event. `detail` is a small dict of what changed, without secrets."""
    global _writes
    try:
        if ip is None:
            ip = client_ip()
        text = json.dumps(detail, ensure_ascii=False, sort_keys=True)[:2000] if detail else None
        with _lock:
            connection = _connect()
            try:
                connection.execute(
                    "INSERT INTO events (at, event, actor, target, detail, ip, ok) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (int(time.time()), str(event)[:64], (str(actor)[:128] if actor else None),
                     (str(target)[:256] if target else None), text, ip, 1 if ok else 0))
                _writes += 1
                if _writes % 500 == 1:
                    connection.execute("DELETE FROM events WHERE at < ?",
                                       (int(time.time()) - RETENTION_DAYS * 86400,))
                connection.commit()
            finally:
                connection.close()
    except Exception:
        pass


def refused(actor, method, rule, permission):
    """An action the profile of `actor` does not allow."""
    key = (actor, method, rule, permission)
    now = time.monotonic()
    with _lock:
        if now - _last_refusal.get(key, -REPEAT_SECONDS) < REPEAT_SECONDS:
            return
        if len(_last_refusal) > 4096:
            _last_refusal.clear()
        _last_refusal[key] = now
    record("access.refused", actor, f"{method} {rule}", {"permission": permission}, ok=False)


def events(limit=100, before=None):
    """The newest events first; `before` is the id to continue from."""
    limit = max(1, min(int(limit or 100), 500))
    try:
        with _lock:
            connection = _connect()
            try:
                if before:
                    rows = connection.execute(
                        "SELECT id, at, event, actor, target, detail, ip, ok FROM events WHERE id < ? "
                        "ORDER BY id DESC LIMIT ?", (int(before), limit)).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT id, at, event, actor, target, detail, ip, ok FROM events "
                        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            finally:
                connection.close()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return []
    result = []
    for row in rows:
        try:
            detail = json.loads(row[5]) if row[5] else None
        except ValueError:
            detail = None
        result.append({"id": row[0], "at": row[1], "event": row[2], "actor": row[3], "target": row[4],
                       "detail": detail, "ip": row[6], "ok": bool(row[7])})
    return result
