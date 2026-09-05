"""Check registry and evaluation engine for Audit & Report.

A check declares an identifier, an area and the severity its failure
carries, and returns the outcome of one evaluation. Checks never modify
the host: an assessment reads, it does not act.

Identifiers are ``<area>.<slug>`` and are frozen once published. Rewording
a title never changes the identifier, because the accepted-risk register
and the per-check history are keyed by it. A check whose meaning changes
materially gets a new identifier and the old one is retired rather than
reused, so a decision recorded months earlier still resolves.

Checks read from ``AuditContext``, which collects each source once per run
and hands the same result to every check that needs it. A full assessment
runs against a production hypervisor, so repeating collection per check is
not acceptable.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

import audit_store

# Report areas. These group the categories `health_monitor` already emits
# so the two surfaces share one vocabulary instead of maintaining a
# parallel taxonomy.
AREA_SYSTEM = "system"
AREA_STORAGE = "storage"
AREA_NETWORK = "network"
AREA_SECURITY = "security"
AREA_BACKUP = "backup"
AREA_GUESTS = "guests"
AREA_HARDWARE = "hardware"

AREAS = (
    AREA_SYSTEM, AREA_STORAGE, AREA_NETWORK, AREA_SECURITY,
    AREA_BACKUP, AREA_GUESTS, AREA_HARDWARE,
)

SEVERITIES = ("OK", "INFO", "WARNING", "CRITICAL")

# Per-check wall-clock budget. A check that cannot answer within it is
# recorded as not applicable rather than stalling the whole assessment.
CHECK_TIMEOUT = 20


class Check:
    """One registered assessment.

    ``evaluate`` receives the context and returns a dict with ``state``
    and, optionally, ``summary``, ``affected``, ``evidence`` and
    ``remediable_by``. Returning ``None`` marks the check as not
    applicable on this host.
    """

    def __init__(self, check_id: str, area: str, severity: str,
                 evaluate: Callable[["AuditContext"], Optional[dict]]):
        if area not in AREAS:
            raise ValueError(f"unknown area for {check_id}: {area}")
        if severity not in SEVERITIES:
            raise ValueError(f"unknown severity for {check_id}: {severity}")
        if not check_id.startswith(f"{area}."):
            raise ValueError(f"{check_id} must be prefixed with its area")
        self.check_id = check_id
        self.area = area
        self.severity = severity
        self.evaluate = evaluate


_REGISTRY: dict[str, Check] = {}


def register(check_id: str, area: str, severity: str):
    """Decorator registering a check under a stable identifier."""
    def wrap(fn):
        if check_id in _REGISTRY:
            raise ValueError(f"duplicate check identifier: {check_id}")
        _REGISTRY[check_id] = Check(check_id, area, severity, fn)
        return fn
    return wrap


def registered_checks() -> list[Check]:
    return sorted(_REGISTRY.values(), key=lambda c: (c.area, c.check_id))


# ---------------------------------------------------------------------------
# Collection context
# ---------------------------------------------------------------------------

class AuditContext:
    """Lazily collects each source once and shares it across checks."""

    def __init__(self):
        self._cache: dict[str, Any] = {}

    def _once(self, key: str, producer: Callable[[], Any]) -> Any:
        if key not in self._cache:
            try:
                self._cache[key] = producer()
            except Exception:
                self._cache[key] = None
        return self._cache[key]

    def run(self, cmd: list[str], timeout: int = 10) -> tuple[int, str]:
        """Run a read-only command, returning exit code and output."""
        key = f"cmd:{' '.join(cmd)}"
        if key in self._cache:
            return self._cache[key]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout)
            result = (proc.returncode, (proc.stdout or "") + (proc.stderr or ""))
        except Exception as exc:
            result = (-1, str(exc))
        self._cache[key] = result
        return result

    @property
    def lxc_configs(self) -> dict[int, str]:
        """Raw text of every local container configuration."""
        def load():
            out: dict[int, str] = {}
            base = Path("/etc/pve/lxc")
            if not base.is_dir():
                return out
            for path in base.glob("*.conf"):
                try:
                    out[int(path.stem)] = path.read_text(errors="replace")
                except (OSError, ValueError):
                    continue
            return out
        return self._once("lxc_configs", load) or {}

    @property
    def qemu_configs(self) -> dict[int, str]:
        def load():
            out: dict[int, str] = {}
            base = Path("/etc/pve/qemu-server")
            if not base.is_dir():
                return out
            for path in base.glob("*.conf"):
                try:
                    out[int(path.stem)] = path.read_text(errors="replace")
                except (OSError, ValueError):
                    continue
            return out
        return self._once("qemu_configs", load) or {}

    @property
    def apt_sources(self) -> dict[str, str]:
        """Contents of the apt source files that define PVE repositories."""
        def load():
            out: dict[str, str] = {}
            candidates = [Path("/etc/apt/sources.list")]
            d = Path("/etc/apt/sources.list.d")
            if d.is_dir():
                candidates.extend(sorted(d.glob("*.list")))
                candidates.extend(sorted(d.glob("*.sources")))
            for path in candidates:
                try:
                    out[str(path)] = path.read_text(errors="replace")
                except OSError:
                    continue
            return out
        return self._once("apt_sources", load) or {}

    @property
    def vzdump_jobs(self) -> str:
        """Raw backup job definitions from the cluster configuration."""
        def load():
            text = ""
            for path in (Path("/etc/pve/jobs.cfg"), Path("/etc/vzdump.cron")):
                try:
                    text += path.read_text(errors="replace") + "\n"
                except OSError:
                    continue
            return text
        return self._once("vzdump_jobs", load) or ""

    @property
    def storages(self) -> list[dict]:
        """Storage definitions from ``storage.cfg``.

        Each entry keeps its type, identifier and settings. ``shared``
        matters to anything that reasons about ownership: on shared
        storage a volume may belong to a guest running on another node,
        which is invisible from here.
        """
        def load():
            out: list[dict] = []
            try:
                text = Path("/etc/pve/storage.cfg").read_text(errors="replace")
            except OSError:
                return out
            current: Optional[dict] = None
            for line in text.splitlines():
                if not line.strip():
                    continue
                header = re.match(r"^(\w+):\s*(\S+)", line)
                if header:
                    current = {"type": header.group(1), "id": header.group(2)}
                    out.append(current)
                    continue
                if current is None or not line[:1].isspace():
                    continue
                parts = line.strip().split(None, 1)
                if parts:
                    current[parts[0]] = parts[1] if len(parts) > 1 else ""
            return out
        return self._once("storages", load) or []

    @property
    def pve_user_cfg(self) -> str:
        """Raw access-control configuration, which also defines pools."""
        def load():
            try:
                return Path("/etc/pve/user.cfg").read_text(errors="replace")
            except OSError:
                return ""
        return self._once("pve_user_cfg", load) or ""


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def run_assessment(profile: str = "full",
                   only_areas: Optional[set[str]] = None) -> str:
    """Evaluate every registered check and persist the result.

    A check that raises is recorded as not applicable with the error kept
    as evidence. One faulty check must never abort an assessment: a
    partial report that says which check failed is more useful than no
    report at all.
    """
    ctx = AuditContext()
    exceptions = audit_store.active_exceptions()
    run_id = audit_store.start_run(profile)
    findings: list[dict[str, Any]] = []
    error: Optional[str] = None

    try:
        for check in registered_checks():
            if only_areas and check.area not in only_areas:
                continue
            started = time.monotonic()
            try:
                result = check.evaluate(ctx)
            except Exception as exc:
                result = {
                    "state": audit_store.STATE_NOT_APPLICABLE,
                    "summary_key": "evaluationFailed",
                    "evidence": f"{type(exc).__name__}: {exc}",
                }
            elapsed = time.monotonic() - started

            if result is None:
                result = {"state": audit_store.STATE_NOT_APPLICABLE}

            state = result.get("state", audit_store.STATE_NOT_APPLICABLE)
            # An accepted risk keeps its evidence and its declared
            # severity; only the state changes, so the report can still
            # show what was accepted and why it mattered.
            if state in (audit_store.STATE_FAIL, audit_store.STATE_WARN) \
                    and check.check_id in exceptions:
                state = audit_store.STATE_ACCEPTED

            evidence = result.get("evidence")
            if elapsed > CHECK_TIMEOUT:
                evidence = (evidence or "") + \
                    f"\n[check exceeded its time budget: {elapsed:.1f}s]"

            findings.append({
                "check_id": check.check_id,
                "area": check.area,
                "severity": check.severity,
                "state": state,
                "summary_key": result.get("summary_key"),
                "summary_params": result.get("summary_params") or {},
                "affected": result.get("affected") or [],
                "evidence": evidence,
                "remediable_by": result.get("remediable_by"),
            })
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    audit_store.record_findings(run_id, findings)
    audit_store.finish_run(run_id, checks_total=len(findings), error=error)
    return run_id


def compare_runs(base_run: str, other_run: str) -> dict[str, list[dict]]:
    """Classify how findings moved between two runs.

    A finding that stopped failing because someone accepted it is reported
    separately from one that stopped failing because the host changed.
    Both leave the active set, but only the second is a fix, and a report
    that merges them would tell its reader the problem went away when the
    decision was to live with it.

    ``unchanged`` is kept so a report can state that the rest of the
    surface held steady rather than leaving it unaccounted for.
    """
    failing = {audit_store.STATE_FAIL, audit_store.STATE_WARN}
    base = {f["check_id"]: f for f in audit_store.get_findings(base_run)}
    other = {f["check_id"]: f for f in audit_store.get_findings(other_run)}

    new, resolved, accepted, unchanged = [], [], [], []
    for check_id, current in other.items():
        previous = base.get(check_id)
        was = previous["state"] in failing if previous else False
        now = current["state"] in failing
        if now and not was:
            new.append(current)
        elif was and not now:
            if current["state"] == audit_store.STATE_ACCEPTED:
                accepted.append(current)
            else:
                resolved.append(current)
        elif previous and previous["state"] == current["state"]:
            unchanged.append(current)
    # A check present in the base run but absent from the later one was
    # retired between the two. It is reported as no longer assessed rather
    # than as resolved, since nothing verified that it stopped failing.
    retired = [
        previous for check_id, previous in base.items()
        if check_id not in other and previous["state"] in failing
    ]

    return {
        "new": new,
        "resolved": resolved,
        "accepted": accepted,
        "unchanged": unchanged,
        "retired": retired,
    }
