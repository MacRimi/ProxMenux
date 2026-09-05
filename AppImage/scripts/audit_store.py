"""Persistence layer for Audit & Report.

Holds assessment runs, their findings, the accepted-risk register and the
designated baseline.

The store lives in its own database rather than alongside health and
notification state. An assessment writes every finding of a run in one
burst and its retention pass deletes whole runs; sharing a file with the
notification dispatcher — which opens ``BEGIN IMMEDIATE`` transactions on
every delivered event — would make those two paths contend for the same
write lock.

Findings persist i18n keys, never rendered text. A report exported today
may be read in a different language than the one active when the
assessment ran, and the printed document renders from the key at
presentation time. Evidence is the exception: it is raw command output
and is stored verbatim.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path("/usr/local/share/proxmenux/audit.db")

# Result of a check within one run. Severity is what the check declares
# for a failure; state is what actually happened this time.
STATE_FAIL = "fail"
STATE_WARN = "warn"
STATE_PASS = "pass"
STATE_NOT_APPLICABLE = "not_applicable"
STATE_ACCEPTED = "accepted"

RUN_RUNNING = "running"
RUN_COMPLETE = "complete"
RUN_FAILED = "failed"

_schema_lock = threading.Lock()
_schema_ready = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create the schema. Safe to call repeatedly."""
    global _schema_ready
    with _schema_lock:
        if _schema_ready:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS audit_runs (
                    run_id        TEXT PRIMARY KEY,
                    profile       TEXT NOT NULL,
                    started_at    INTEGER NOT NULL,
                    finished_at   INTEGER,
                    status        TEXT NOT NULL,
                    error         TEXT,
                    is_baseline   INTEGER NOT NULL DEFAULT 0,
                    checks_total  INTEGER NOT NULL DEFAULT 0,
                    schema_version INTEGER NOT NULL DEFAULT 1
                );

                -- summary_key names a translation entry and summary_params
                -- carries its placeholders. Storing a rendered sentence
                -- instead would freeze a finding in whichever language was
                -- active when the assessment ran, and a report exported
                -- today may well be read in another one.
                CREATE TABLE IF NOT EXISTS audit_findings (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id         TEXT NOT NULL,
                    check_id       TEXT NOT NULL,
                    area           TEXT NOT NULL,
                    severity       TEXT NOT NULL,
                    state          TEXT NOT NULL,
                    summary_key    TEXT,
                    summary_params TEXT,
                    affected       TEXT,
                    evidence       TEXT,
                    remediable_by  TEXT,
                    FOREIGN KEY (run_id) REFERENCES audit_runs(run_id)
                        ON DELETE CASCADE
                );

                -- Accepted risks outlive the run that surfaced them, so they
                -- are keyed by check rather than by finding. expires_at NULL
                -- means the acceptance does not lapse on its own.
                CREATE TABLE IF NOT EXISTS audit_exceptions (
                    check_id      TEXT PRIMARY KEY,
                    reason        TEXT NOT NULL,
                    accepted_by   TEXT NOT NULL,
                    accepted_at   INTEGER NOT NULL,
                    expires_at    INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_audit_findings_run
                    ON audit_findings(run_id);
                CREATE INDEX IF NOT EXISTS idx_audit_findings_check
                    ON audit_findings(check_id);
                CREATE INDEX IF NOT EXISTS idx_audit_runs_started
                    ON audit_runs(started_at);
            """)
            conn.commit()
            _schema_ready = True
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def start_run(profile: str) -> str:
    """Open a run and return its identifier."""
    init_db()
    run_id = uuid.uuid4().hex[:16]
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO audit_runs (run_id, profile, started_at, status) "
            "VALUES (?, ?, ?, ?)",
            (run_id, profile, int(time.time()), RUN_RUNNING),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def finish_run(run_id: str, *, checks_total: int,
               error: Optional[str] = None) -> None:
    """Close a run, marking it failed when an error is supplied."""
    init_db()
    conn = _connect()
    try:
        conn.execute(
            "UPDATE audit_runs SET finished_at = ?, status = ?, error = ?, "
            "checks_total = ? WHERE run_id = ?",
            (int(time.time()), RUN_FAILED if error else RUN_COMPLETE,
             error, checks_total, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_run(run_id: str) -> Optional[dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM audit_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def latest_run(status: str = RUN_COMPLETE) -> Optional[dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM audit_runs WHERE status = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (status,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

def record_findings(run_id: str, findings: list[dict[str, Any]]) -> int:
    """Write a run's findings in a single transaction.

    ``affected`` is stored as JSON so a check that covers several objects
    keeps the per-object detail without emitting one finding per object.
    """
    init_db()
    if not findings:
        return 0
    rows = [
        (
            run_id,
            f["check_id"],
            f["area"],
            f["severity"],
            f["state"],
            f.get("summary_key"),
            json.dumps(f.get("summary_params") or {}, ensure_ascii=False),
            json.dumps(f.get("affected") or [], ensure_ascii=False),
            f.get("evidence"),
            f.get("remediable_by"),
        )
        for f in findings
    ]
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "INSERT INTO audit_findings (run_id, check_id, area, severity, "
            "state, summary_key, summary_params, affected, evidence, "
            "remediable_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def get_findings(run_id: str) -> list[dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_findings WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            try:
                item["affected"] = json.loads(item.get("affected") or "[]")
            except (TypeError, ValueError):
                item["affected"] = []
            try:
                item["summary_params"] = json.loads(
                    item.get("summary_params") or "{}")
            except (TypeError, ValueError):
                item["summary_params"] = {}
            out.append(item)
        return out
    finally:
        conn.close()


def check_history(check_id: str, limit: int = 30) -> list[dict[str, Any]]:
    """Return how one check resolved across recent runs."""
    init_db()
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT f.state, f.severity, r.run_id, r.started_at "
            "FROM audit_findings f JOIN audit_runs r ON r.run_id = f.run_id "
            "WHERE f.check_id = ? ORDER BY r.started_at DESC LIMIT ?",
            (check_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Accepted risks
# ---------------------------------------------------------------------------

def accept_risk(check_id: str, reason: str, accepted_by: str,
                expires_at: Optional[int] = None) -> None:
    """Record a deliberate decision to leave a finding unresolved.

    A reason is mandatory: an acceptance without one is indistinguishable
    from having silenced the check, which is what this register exists to
    prevent.
    """
    if not (reason or "").strip():
        raise ValueError("an accepted risk requires a reason")
    init_db()
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO audit_exceptions "
            "(check_id, reason, accepted_by, accepted_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (check_id, reason.strip(), accepted_by, int(time.time()),
             expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def revoke_risk(check_id: str) -> bool:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM audit_exceptions WHERE check_id = ?", (check_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def active_exceptions() -> dict[str, dict[str, Any]]:
    """Return accepted risks that have not lapsed, keyed by check.

    Lapsed entries are left on disk so the decision remains auditable;
    they simply stop suppressing the finding.
    """
    init_db()
    now = int(time.time())
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_exceptions "
            "WHERE expires_at IS NULL OR expires_at > ?",
            (now,),
        ).fetchall()
        return {r["check_id"]: dict(r) for r in rows}
    finally:
        conn.close()


def all_exceptions() -> list[dict[str, Any]]:
    init_db()
    now = int(time.time())
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_exceptions ORDER BY accepted_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["lapsed"] = bool(
                item["expires_at"] is not None and item["expires_at"] <= now
            )
            out.append(item)
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Baseline and retention
# ---------------------------------------------------------------------------

def set_baseline(run_id: str) -> None:
    """Designate a run as the reference to compare later runs against."""
    init_db()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE audit_runs SET is_baseline = 0")
        conn.execute(
            "UPDATE audit_runs SET is_baseline = 1 WHERE run_id = ?", (run_id,)
        )
        conn.commit()
    finally:
        conn.close()


def get_baseline() -> Optional[dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM audit_runs WHERE is_baseline = 1 LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def prune_runs(keep: int = 30) -> int:
    """Drop the oldest runs beyond ``keep``.

    The baseline is never pruned: it is the reference every comparison is
    measured against and losing it silently would break that comparison
    long after the run that produced it was forgotten.
    """
    init_db()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "DELETE FROM audit_runs WHERE is_baseline = 0 AND run_id NOT IN ("
            "  SELECT run_id FROM audit_runs "
            "  WHERE is_baseline = 0 ORDER BY started_at DESC LIMIT ?"
            ")",
            (keep,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
