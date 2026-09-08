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
import hashlib
import re
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path("/usr/local/share/proxmenux/audit.db")

# What a check concluded, on one scale.
#
# Severity used to be declared per check and state per run, which meant a
# storage at 90% capacity was labelled "critical" because the check that
# found it is the one that can also find an unreachable storage. Gravity
# belongs to the situation, so the check now returns it with the result,
# and it may differ between the objects one check reports on.
#
# The scale is deliberately short, and each step says what it takes to
# earn it:
#
#   critical       an interruption or an urgent threat to availability,
#                  integrity or recoverability, backed by evidence
#   warning        a verified degradation, an expected protection that is
#                  absent, or a declared policy that is not met
#   observation    a configuration, a limit or planning information; it
#                  does not demonstrate a problem and is not counted as one
#   conformant     the criterion was verified and is met
#   unverified     not enough information to conclude; not a fault
#   not_applicable nothing on this host to evaluate
CLASS_CRITICAL = "critical"
CLASS_WARNING = "warning"
CLASS_OBSERVATION = "observation"
CLASS_CONFORMANT = "conformant"
CLASS_UNVERIFIED = "unverified"
CLASS_NOT_APPLICABLE = "not_applicable"

CLASSIFICATIONS = (CLASS_CRITICAL, CLASS_WARNING, CLASS_OBSERVATION,
                   CLASS_CONFORMANT, CLASS_UNVERIFIED, CLASS_NOT_APPLICABLE)

# Worst first: a finding takes the gravity of its gravest object.
CLASS_ORDER = {name: i for i, name in enumerate(CLASSIFICATIONS)}

# Only these two are problems. An observation is information, and
# unverified is an absence of information; counting either as a problem is
# what made ordinary configurations look like faults.
CLASS_PROBLEMS = (CLASS_CRITICAL, CLASS_WARNING)

# What the reader decided about a finding, kept apart from what the
# assessment concluded. A technical result does not change because someone
# accepted it; only the decision layered over it does.
DECISION_NONE = ""
DECISION_ACCEPTED = "accepted"     # a signed exception over a real finding
DECISION_BY_DESIGN = "by_design"   # declared policy: this object is exempt

# Retained so findings recorded before the scale existed still read, and
# so the interface can be migrated without breaking the stored history.
STATE_FAIL = "fail"
STATE_WARN = "warn"
STATE_PASS = "pass"
STATE_NOT_APPLICABLE = "not_applicable"
STATE_ACCEPTED = "accepted"
STATE_UNKNOWN = "unknown"

# A finding written before the scale is read on the scale, using the
# severity its check declared at the time.
_LEGACY_STATE_MAP = {
    STATE_PASS: CLASS_CONFORMANT,
    STATE_UNKNOWN: CLASS_UNVERIFIED,
    STATE_NOT_APPLICABLE: CLASS_NOT_APPLICABLE,
    STATE_ACCEPTED: CLASS_WARNING,
}


def classification_of(state: str, severity: str) -> str:
    """Read a stored state and severity on the current scale."""
    mapped = _LEGACY_STATE_MAP.get(state)
    if mapped:
        return mapped
    if state == STATE_FAIL:
        return CLASS_CRITICAL if severity == "CRITICAL" else CLASS_WARNING
    if state == STATE_WARN:
        return CLASS_OBSERVATION if severity == "INFO" else CLASS_WARNING
    return CLASS_UNVERIFIED


def state_of(classification: str) -> str:
    """The state a classification would have had, for stored compatibility."""
    return {
        CLASS_CRITICAL: STATE_FAIL,
        CLASS_WARNING: STATE_WARN,
        CLASS_OBSERVATION: STATE_WARN,
        CLASS_CONFORMANT: STATE_PASS,
        CLASS_UNVERIFIED: STATE_UNKNOWN,
        CLASS_NOT_APPLICABLE: STATE_NOT_APPLICABLE,
    }.get(classification, STATE_UNKNOWN)


def worst(classifications) -> str:
    """The gravest of several, or not applicable when there are none."""
    ranked = [c for c in classifications if c in CLASS_ORDER]
    if not ranked:
        return CLASS_NOT_APPLICABLE
    return min(ranked, key=lambda c: CLASS_ORDER[c])

RUN_RUNNING = "running"
RUN_COMPLETE = "complete"
RUN_FAILED = "failed"
RUN_PARTIAL = "partial"

_schema_lock = threading.Lock()
_schema_ready = False


def safe_evidence(value):
    """Redact secrets before persistence; bound individual evidence fields."""
    if isinstance(value, dict):
        return {k: ("[redacted]" if re.search(r"password|secret|token|authorization|private.key", k, re.I)
                    else safe_evidence(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_evidence(v) for v in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r"(?s)-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                   "[private key redacted]", value)
    value = re.sub(r"(https?://)[^/\s@]+@", r"\1[redacted]@", value)
    value = re.sub(r"(?i)((?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*)[^\s&,;]+",
                   r"\1[redacted]", value)
    value = re.sub(r"(?im)(authorization\s*:\s*).*", r"\1[redacted]", value)
    return value if len(value) <= 32768 else value[:32768] + "\n[evidence truncated]"


def finding_scope(finding):
    """Bind decisions to object identity, rule version, host and gravity.

    A decision is about a situation, not about a check. If the same
    objects come back at a different gravity, the situation is not the one
    that was accepted, so the acceptance does not carry over.
    """
    objects = []
    for obj in finding.get("affected") or []:
        identity = {k: obj[k] for k in ("vmid", "type", "volume", "device", "pool",
                    "job", "test", "bridge", "file", "snapshot", "storage", "package") if k in obj}
        objects.append(identity or obj)
    payload = {"objects": sorted(objects, key=lambda v: json.dumps(v, sort_keys=True)),
               "check": finding["check_id"], "version": finding.get("check_version", 1),
               "classification": finding.get("classification", ""),
               "host": finding.get("host", "")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


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
        fd = os.open(DB_PATH, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(DB_PATH, 0o600)
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
            # Additive migration: retain existing runs and decisions.
            for table, columns in {
                "audit_runs": {"metadata": "TEXT", "checks_expected": "INTEGER NOT NULL DEFAULT 0"},
                "audit_findings": {"raw_state": "TEXT", "exception_snapshot": "TEXT",
                    "scope": "TEXT", "details": "TEXT", "classification": "TEXT",
                    "raw_classification": "TEXT", "decision": "TEXT"},
                "audit_exceptions": {"scope": "TEXT"},
            }.items():
                present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                for name, kind in columns.items():
                    if name not in present:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
            conn.execute("""CREATE TABLE IF NOT EXISTS audit_exception_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, check_id TEXT NOT NULL,
                action TEXT NOT NULL, happened_at INTEGER NOT NULL, decision TEXT NOT NULL)""")
            conn.row_factory = sqlite3.Row
            for legacy in conn.execute("SELECT * FROM audit_exceptions WHERE scope IS NULL"):
                exists = conn.execute("SELECT 1 FROM audit_exception_events WHERE check_id = ? LIMIT 1",
                                      (legacy["check_id"],)).fetchone()
                if not exists:
                    conn.execute("INSERT INTO audit_exception_events (check_id, action, happened_at, decision) "
                                 "VALUES (?, 'legacy-unscoped', ?, ?)",
                                 (legacy["check_id"], legacy["accepted_at"], json.dumps(safe_evidence(dict(legacy)))))
            # Old accepted findings have no recoverable technical state.
            conn.execute("UPDATE audit_findings SET raw_state = CASE WHEN state = 'accepted' "
                         "THEN 'unknown' ELSE state END WHERE raw_state IS NULL")
            conn.commit()
            os.chmod(DB_PATH, 0o600)
            _schema_ready = True
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def start_run(profile: str, metadata=None, checks_expected=0) -> str:
    """Open a run and return its identifier."""
    init_db()
    run_id = uuid.uuid4().hex[:16]
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO audit_runs (run_id, profile, started_at, status, metadata, "
            "checks_expected, schema_version) VALUES (?, ?, ?, ?, ?, ?, 2)",
            (run_id, profile, int(time.time()), RUN_RUNNING,
             json.dumps(safe_evidence(metadata or {})), checks_expected),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def update_run_metadata(run_id, metadata, checks_expected):
    init_db()
    conn = _connect()
    try:
        conn.execute("UPDATE audit_runs SET metadata = ?, checks_expected = ? WHERE run_id = ?",
                     (json.dumps(safe_evidence(metadata)), checks_expected, run_id))
        conn.commit()
    finally:
        conn.close()


def finish_run(run_id: str, *, checks_total: int,
               error: Optional[str] = None, partial: bool = False) -> None:
    """Close a run, marking it failed when an error is supplied."""
    init_db()
    conn = _connect()
    try:
        conn.execute(
            "UPDATE audit_runs SET finished_at = ?, status = ?, error = ?, "
            "checks_total = ? WHERE run_id = ?",
            (int(time.time()), RUN_FAILED if error else RUN_PARTIAL if partial else RUN_COMPLETE,
             safe_evidence(error), checks_total, run_id),
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
        return _run_row(row) if row else None
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
        return [_run_row(r) for r in rows]
    finally:
        conn.close()


def _run_row(row) -> dict[str, Any]:
    """A run as its consumers need it, with metadata as an object.

    The column holds JSON text; handing that to an interface means every
    caller parses it, and the one that forgets silently reads nothing
    rather than failing.
    """
    run = dict(row)
    try:
        run["metadata"] = json.loads(run.get("metadata") or "{}")
    except (TypeError, ValueError):
        run["metadata"] = {}
    return run


def latest_run(status: Optional[str] = None) -> Optional[dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        condition = "status = ?" if status else "status != 'running'"
        row = conn.execute(f"SELECT * FROM audit_runs WHERE {condition} "
                           "ORDER BY started_at DESC, rowid DESC LIMIT 1",
                           (status,) if status else ()).fetchone()
        return _run_row(row) if row else None
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
    findings = safe_evidence(findings)
    rows = [
        (
            run_id,
            f["check_id"],
            f["area"],
            f["severity"],
            # state is derived from the classification and kept so a
            # database written by this version still reads on the old
            # columns; the scale is what the interface reads.
            state_of(f["classification"]),
            f.get("summary_key"),
            json.dumps(f.get("summary_params") or {}, ensure_ascii=False),
            json.dumps(f.get("affected") or [], ensure_ascii=False),
            f.get("evidence"),
            f.get("remediable_by"),
            # raw_state stays a state, on the old vocabulary; the scale
            # travels in its own column.
            state_of(f.get("raw_classification", f["classification"])),
            json.dumps(f.get("exception")),
            f.get("scope"),
            json.dumps({k: f[k] for k in ("check_version", "collected_at", "sources",
                                        "incomplete", "observations", "host") if k in f}),
            f["classification"],
            f.get("raw_classification", f["classification"]),
            f.get("decision", DECISION_NONE),
        )
        for f in findings
    ]
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "INSERT INTO audit_findings (run_id, check_id, area, severity, "
            "state, summary_key, summary_params, affected, evidence, "
            "remediable_by, raw_state, exception_snapshot, scope, details, "
            "classification, raw_classification, decision) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            item.update(json.loads(item.pop("details", None) or "{}"))
            item["exception"] = json.loads(item.pop("exception_snapshot", None) or "null")
            # A finding recorded before the scale existed is read on it,
            # from the state and severity it was stored with.
            if not item.get("classification"):
                item["classification"] = classification_of(
                    item.get("state", ""), item.get("severity", ""))
            item["raw_classification"] = (
                item.get("raw_classification")
                or classification_of(item.get("raw_state") or item.get("state", ""),
                                     item.get("severity", "")))
            item.setdefault("decision", DECISION_NONE)
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
                expires_at: Optional[int] = None, *, scope: str) -> None:
    """Record a deliberate decision to leave a finding unresolved.

    A reason is mandatory: an acceptance without one is indistinguishable
    from having silenced the check, which is what this register exists to
    prevent.
    """
    if not (reason or "").strip():
        raise ValueError("an accepted risk requires a reason")
    if not scope:
        raise ValueError("an accepted risk requires an assessed scope")
    if expires_at is not None and expires_at <= time.time():
        raise ValueError("expiry must be in the future")
    init_db()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        decision = dict(check_id=check_id, reason=reason.strip(), accepted_by=accepted_by,
                        accepted_at=int(time.time()), expires_at=expires_at, scope=scope)
        conn.execute(
            "INSERT OR REPLACE INTO audit_exceptions "
            "(check_id, reason, accepted_by, accepted_at, expires_at, scope) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (check_id, reason.strip(), accepted_by, int(time.time()),
             expires_at, scope),
        )
        conn.execute("INSERT INTO audit_exception_events (check_id, action, happened_at, decision) "
                     "VALUES (?, 'accepted', ?, ?)",
                     (check_id, int(time.time()), json.dumps(safe_evidence(decision))))
        conn.commit()
    finally:
        conn.close()


def revoke_risk(check_id: str, actor: str = "local-admin") -> bool:
    init_db()
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT * FROM audit_exceptions WHERE check_id = ?", (check_id,)).fetchone()
        if previous:
            decision = dict(previous)
            decision["revoked_by"] = actor
            conn.execute("INSERT INTO audit_exception_events (check_id, action, happened_at, decision) "
                         "VALUES (?, 'revoked', ?, ?)",
                         (check_id, int(time.time()), json.dumps(safe_evidence(decision))))
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


def effective_findings(run_id):
    """Current decisions over immutable technical results; history stays intact.

    The classification is what the assessment concluded and does not
    change because somebody accepted it. What changes is the decision
    recorded beside it, which is why the two are separate fields: a
    report can still show that a critical finding was accepted, and by
    whom, instead of showing a finding that looks resolved.
    """
    exceptions = active_exceptions()
    findings = get_findings(run_id)
    for f in findings:
        f["classification"] = f["raw_classification"]
        f["state"] = f["raw_state"]
        f["exception"] = None
        f["decision"] = DECISION_NONE
        decision = exceptions.get(f["check_id"])
        if (decision and decision.get("scope") and decision["scope"] == f.get("scope")
                and f["classification"] in CLASS_PROBLEMS and not f.get("incomplete")):
            f["decision"] = DECISION_ACCEPTED
            f["state"] = STATE_ACCEPTED
            f["exception"] = decision
    return findings


def exception_history():
    init_db()
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT * FROM audit_exception_events ORDER BY id DESC LIMIT 200")]
    finally:
        conn.close()


def recover_interrupted_runs():
    """Called at service startup, never during an active assessment."""
    init_db()
    conn = _connect()
    try:
        conn.execute("UPDATE audit_runs SET status = ?, error = ?, finished_at = ? WHERE status = ?",
                     (RUN_FAILED, "Assessment interrupted by Monitor restart", int(time.time()), RUN_RUNNING))
        conn.commit()
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
            "DELETE FROM audit_runs WHERE is_baseline = 0 AND status != 'running' AND run_id NOT IN ("
            "  SELECT run_id FROM audit_runs "
            "  WHERE is_baseline = 0 ORDER BY started_at DESC LIMIT ?"
            ")",
            (keep,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
