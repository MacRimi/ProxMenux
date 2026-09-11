"""ProxMenux change journal — reading side.

The scripts that change this host write one small JSON file per change
into a spool directory, and copy whatever they replaced into a content
store keyed by digest. Nothing there needs a database, a daemon or a
network: recording has to work during a first installation, before
anything else exists, and it must never be the reason an operation fails.

This module is the other half. It consolidates the spool into a table
that can be queried, and answers the question the whole thing exists
for: *what did ProxMenux change on this machine, and what was there
before.*

Two distinctions are load-bearing and are kept throughout:

  * **What was changed** against **what was run.** A post-install
    function that rewrites a file authored that change. An upgrade
    launched from a menu did not: apt decided what changed, and claiming
    it would be taking credit and blame for someone else's work. Both are
    recorded; they are not the same kind of entry.

  * **How well the previous state is known.** A change recorded as it
    happened carries the original. A function re-applied on a host that
    was already modified carries what was there at the time, which is not
    the original. Anything applied before the journal existed carries
    nothing at all. A reader who is deciding whether to revert needs to
    know which of the three they are looking at.
"""
from __future__ import annotations

import difflib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path("/usr/local/share/proxmenux/changes")
SPOOL = ROOT / "spool"
OBJECTS = ROOT / "objects"
DB_PATH = Path("/usr/local/share/proxmenux/changes.db")

# What kind of act an entry records.
CLASS_CONFIGURATION = "configuration"   # ProxMenux changed this
CLASS_INSTALLATION = "installation"     # ProxMenux put this here
CLASS_EXECUTION = "execution"           # ProxMenux ran this; it did not decide the outcome
CLASS_REGISTRATION = "registration"     # applied, with no record of what changed

CLASSES = (CLASS_CONFIGURATION, CLASS_INSTALLATION,
           CLASS_EXECUTION, CLASS_REGISTRATION)

# How much of the previous state is actually known.
CAPTURE_PRESENT = "present"   # what was there when the change was made
CAPTURE_CREATED = "created"   # nothing was there; the change created it
CAPTURE_UNKNOWN = "unknown"   # applied before the journal, or unknowable
CAPTURE_NONE = "none"         # nothing to capture (an execution)

# A file large enough that keeping it whole in the journal would cost
# more than the answer is worth; the digest and size are still recorded.
MAX_OBJECT_BYTES = 2 * 1024 * 1024

# Diffs are for reading, not for archiving: past this many lines the
# reader is better served by the counts than by the hunks.
MAX_DIFF_LINES = 400

_lock = threading.Lock()
_ready = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    global _ready
    with _lock:
        if _ready:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        first = not DB_PATH.exists()
        conn = _connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS changes (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at   INTEGER NOT NULL,
                    ingested_at   INTEGER NOT NULL,
                    class         TEXT NOT NULL,
                    operation     TEXT NOT NULL,
                    source        TEXT,
                    function      TEXT,
                    function_version TEXT,
                    target        TEXT,
                    before_ref    TEXT,
                    after_ref     TEXT,
                    capture       TEXT,
                    revert        TEXT,
                    exactness     TEXT,
                    result        TEXT,
                    detail        TEXT,
                    -- The spool file this came from, so an entry is
                    -- ingested once however often the reader runs.
                    origin        TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_changes_time
                    ON changes(recorded_at DESC);
                CREATE INDEX IF NOT EXISTS idx_changes_function
                    ON changes(function);
                CREATE INDEX IF NOT EXISTS idx_changes_identity
                    ON changes(function, target, operation);
                CREATE INDEX IF NOT EXISTS idx_changes_install
                    ON changes(class, target);
            """)
            conn.commit()
        finally:
            conn.close()
        if first:
            try:
                DB_PATH.chmod(0o600)
            except OSError:
                pass
        _ready = True


def object_path(digest: str) -> Optional[Path]:
    """Where a captured content lives, if it is still there."""
    if not digest or len(digest) < 4 or not digest.isalnum():
        return None
    path = OBJECTS / digest[:2] / digest
    return path if path.is_file() else None


def read_object(digest: str) -> Optional[str]:
    """Captured content as text, or None when it is gone or too large."""
    path = object_path(digest)
    if path is None:
        return None
    try:
        if path.stat().st_size > MAX_OBJECT_BYTES:
            return None
        return path.read_text(errors="replace")
    except OSError:
        return None


def record_install(packages: str, source: str = "monitor",
                   function: str = "monitor") -> bool:
    """Record a package the Monitor installed on the host, so it appears in the
    installed-packages section like anything the scripts install. The Monitor
    is Python and cannot use the bash primitives, so it drops a spool entry in
    the same shape they write; ingest() picks it up and dedupes it by package.
    """
    packages = (packages or "").strip()
    if not packages:
        return False
    entry = {
        "recorded_at": int(time.time()),
        "class": CLASS_INSTALLATION,
        "operation": "install_package",
        "source": source,
        "function": function,
        "function_version": "1.0",
        "target": packages,
        "installed": packages,
        "before": "",
        "after": "",
        "capture": "created",
        "revert": "purge",
        "exactness": "none",
        "result": "ok",
    }
    try:
        SPOOL.mkdir(parents=True, exist_ok=True)
        path = SPOOL / f"{entry['recorded_at']}-{os.getpid()}-{os.urandom(4).hex()}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entry), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def ingest(limit: int = 5000) -> int:
    """Move what the scripts wrote into the table.

    A malformed entry is dropped rather than allowed to stop the rest:
    the spool is written by shell running under conditions this process
    cannot see, and one bad file must not cost the reader every other
    change on the host.
    """
    init_db()
    if not SPOOL.is_dir():
        return 0
    try:
        pending = sorted(p for p in SPOOL.iterdir()
                         if p.suffix == ".json" and p.is_file())[:limit]
    except OSError:
        return 0
    if not pending:
        return 0

    rows, consumed = [], []
    for path in pending:
        try:
            entry = json.loads(path.read_text(errors="replace"))
        except (OSError, ValueError):
            # Keep it out of the way but do not delete it: a file that
            # could not be read is evidence of its own.
            _quarantine(path)
            continue
        if not isinstance(entry, dict):
            _quarantine(path)
            continue
        rows.append((
            int(entry.get("recorded_at") or time.time()),
            int(time.time()),
            str(entry.get("class") or CLASS_CONFIGURATION),
            str(entry.get("operation") or "unknown"),
            str(entry.get("source") or ""),
            str(entry.get("function") or ""),
            str(entry.get("function_version") or ""),
            str(entry.get("target") or ""),
            str(entry.get("before") or ""),
            str(entry.get("after") or ""),
            str(entry.get("capture") or CAPTURE_UNKNOWN),
            str(entry.get("revert") or "none"),
            str(entry.get("exactness") or "none"),
            str(entry.get("result") or "ok"),
            json.dumps({k: v for k, v in entry.items()
                        if k not in ("recorded_at", "class", "operation", "source",
                                     "function", "function_version", "target",
                                     "before", "after", "capture", "revert",
                                     "exactness", "result")}, ensure_ascii=False),
            path.name,
        ))
        consumed.append(path)

    if not rows:
        return 0

    # A change is identified by what it changed, not by when. Re-applying a
    # post-install function, re-running a script or re-installing a package
    # updates the existing entry instead of adding another — the original
    # "before" is preserved, only the "after" and the timestamp move forward,
    # so an entry always reads as origin -> current state. Intermediate states
    # are dropped: the latest is how the host stands now, and it superseded
    # whatever came between.
    rows.sort(key=lambda r: r[0])  # oldest first, so the original lands first
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for r in rows:
            if r[2] == CLASS_INSTALLATION:
                # A package is one entry however often, or by whichever helper,
                # it is installed.
                found = conn.execute(
                    "SELECT id FROM changes WHERE class = ? AND target = ?",
                    (CLASS_INSTALLATION, r[7])).fetchone()
            elif r[2] == CLASS_CONFIGURATION:
                # A file is one entry no matter which function touched it — a
                # feature and its re-apply helper both land here — so it always
                # reads as origin -> current, not once per code path.
                found = conn.execute(
                    "SELECT id FROM changes WHERE class = ? AND target = ?",
                    (CLASS_CONFIGURATION, r[7])).fetchone()
            else:
                found = conn.execute(
                    "SELECT id FROM changes WHERE function = ? AND target = ? "
                    "AND operation = ?", (r[5], r[7], r[3])).fetchone()
            if found:
                # Only what reflects the current state moves forward; the
                # original attribution, operation, capture and before_ref stay,
                # so the entry keeps reading as how the host came versus now.
                conn.execute(
                    "UPDATE changes SET recorded_at = ?, ingested_at = ?, "
                    "source = ?, function_version = ?, after_ref = ?, "
                    "result = ?, detail = ?, origin = ? WHERE id = ?",
                    (r[0], r[1], r[4], r[6], r[9], r[13], r[14], r[15], found[0]))
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO changes (recorded_at, ingested_at, class, "
                    "operation, source, function, function_version, target, before_ref, "
                    "after_ref, capture, revert, exactness, result, detail, origin) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", r)
        conn.commit()
    finally:
        conn.close()
    for path in consumed:
        try:
            path.unlink()
        except OSError:
            pass
    return len(rows)


def _quarantine(path: Path) -> None:
    bad = ROOT / "unreadable"
    try:
        bad.mkdir(parents=True, exist_ok=True)
        path.rename(bad / path.name)
    except OSError:
        pass


def diff_of(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    """What changed in a file, as the difference and nothing else.

    A function may run to four hundred lines and alter two values; the
    reader is owed the two values, not the function. Where the content is
    gone or too large to hold, the absence is reported rather than
    guessed at.
    """
    if entry.get("class") != CLASS_CONFIGURATION:
        return None
    before_ref, after_ref = entry.get("before_ref"), entry.get("after_ref")
    # A service enable/disable changes state, not file content: it carries
    # before_state/after_state, no refs. With nothing to diff, there is no
    # difference block to show — the state transition speaks for itself.
    if not before_ref and not after_ref:
        return None
    before = read_object(before_ref) if before_ref else ""
    after = read_object(after_ref) if after_ref else ""
    if before is None or after is None:
        return {"available": False,
                "reason": "content no longer stored or too large to show"}

    before_lines = before.splitlines()
    after_lines = after.splitlines()
    hunks = list(difflib.unified_diff(before_lines, after_lines,
                                      lineterm="", n=2))[2:]
    added = sum(1 for l in hunks if l.startswith("+"))
    removed = sum(1 for l in hunks if l.startswith("-"))
    return {
        "available": True,
        "added": added,
        "removed": removed,
        "before_lines": len(before_lines),
        "after_lines": len(after_lines),
        "truncated": len(hunks) > MAX_DIFF_LINES,
        "hunks": hunks[:MAX_DIFF_LINES],
    }


def changes(limit: int = 200, offset: int = 0,
            function: str = "", klass: str = "") -> list[dict[str, Any]]:
    """Recorded changes, newest first."""
    init_db()
    ingest()
    query = "SELECT * FROM changes WHERE 1=1"
    params: list[Any] = []
    if function:
        query += " AND function = ?"
        params.append(function)
    if klass:
        query += " AND class = ?"
        params.append(klass)
    query += " ORDER BY recorded_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(query, params)]
    finally:
        conn.close()
    for row in rows:
        try:
            row["detail"] = json.loads(row.get("detail") or "{}")
        except ValueError:
            row["detail"] = {}
        # Whether the previous state can still be shown at all, which is
        # what decides if a revert is even discussable.
        row["recoverable"] = bool(row.get("before_ref")
                                  and object_path(row["before_ref"]))
    return rows


def summary() -> dict[str, Any]:
    """What the host has been through, in the shape the page opens with."""
    init_db()
    ingest()
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        by_class = {row["class"]: row["n"] for row in conn.execute(
            "SELECT class, COUNT(*) AS n FROM changes GROUP BY class")}
        functions = [dict(row) for row in conn.execute(
            "SELECT function, source, MAX(function_version) AS version, "
            "COUNT(*) AS changes, MAX(recorded_at) AS last_change, "
            "MIN(recorded_at) AS first_change "
            "FROM changes WHERE function <> '' "
            "GROUP BY function ORDER BY last_change DESC")]
        total = sum(by_class.values())
    finally:
        conn.close()
    return {
        "total": total,
        "by_class": by_class,
        "functions": functions,
        # Where the journal itself stands, so a host with nothing recorded
        # can say why rather than looking like a host nothing touched.
        "journal_started": _journal_started(),
    }


def _journal_started() -> Optional[int]:
    """When this host first recorded anything, if it ever has."""
    conn = _connect()
    try:
        row = conn.execute("SELECT MIN(recorded_at) AS first FROM changes").fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def prune(keep_days: int = 365) -> int:
    """Drops entries and their content past the retention window.

    Content is only removed once no entry references it, since the same
    original may be shared by several changes.
    """
    init_db()
    cutoff = int(time.time()) - keep_days * 86400
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        removed = conn.execute("DELETE FROM changes WHERE recorded_at < ?",
                               (cutoff,)).rowcount
        referenced = {row[0] for row in conn.execute(
            "SELECT before_ref FROM changes WHERE before_ref <> '' "
            "UNION SELECT after_ref FROM changes WHERE after_ref <> ''")}
        conn.commit()
    finally:
        conn.close()
    if OBJECTS.is_dir():
        for shard in OBJECTS.iterdir():
            if not shard.is_dir():
                continue
            for obj in shard.iterdir():
                if obj.name not in referenced:
                    try:
                        obj.unlink()
                    except OSError:
                        pass
    return removed
