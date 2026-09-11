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
import json
import socket
import sys
import copy
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

# Shared deadline for all subprocesses in a check, not a fresh timeout
# per device/storage. Exhaustion is unknown, never not applicable.
CHECK_TIMEOUT = 30
RUN_TIMEOUT = 300
CATALOG_VERSION = 14

# A check that has to produce its own evidence — rather than read
# evidence something else already produced — declares how long that
# takes. The budget is still bounded by the run's own deadline.
LYNIS_RUN_BUDGET = 240


class Check:
    """One registered assessment.

    ``evaluate`` receives the context and returns a dict with ``classification``
    and, optionally, ``summary``, ``affected``, ``evidence`` and
    ``remediable_by``. Returning ``None`` marks the check as not
    applicable on this host.
    """

    def __init__(self, check_id: str, area: str, severity: str,
                 evaluate: Callable[["AuditContext"], Optional[dict]],
                 budget: int = CHECK_TIMEOUT):
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
        self.budget = budget
        self.version = CATALOG_VERSION


_REGISTRY: dict[str, Check] = {}


def register(check_id: str, area: str, severity: str,
             budget: int = CHECK_TIMEOUT):
    """Decorator registering a check under a stable identifier."""
    def wrap(fn):
        if check_id in _REGISTRY:
            raise ValueError(f"duplicate check identifier: {check_id}")
        _REGISTRY[check_id] = Check(check_id, area, severity, fn, budget)
        return fn
    return wrap


def registered_checks() -> list[Check]:
    return sorted(_REGISTRY.values(), key=lambda c: (c.area, c.check_id))


# ---------------------------------------------------------------------------
# Collection context
# ---------------------------------------------------------------------------

class AuditContext:
    """Lazily collects each source once and shares it across checks."""

    def __init__(self, run_lynis: bool = False):
        self._cache: dict[str, Any] = {}
        self._source_info = {}
        self._dependencies = {}
        self._sources_used = set()
        self._errors = {}
        self._check_deadline = float("inf")
        self._run_deadline = time.monotonic() + RUN_TIMEOUT
        # Whether this assessment may launch Lynis. The user grants it in
        # the run dialog; without it the audit reads a stored report and
        # never starts one, so a run is fast and predictable.
        self._run_lynis_allowed = run_lynis

    def begin_check(self, budget: int = CHECK_TIMEOUT):
        self._sources_used = set()
        self._check_deadline = min(time.monotonic() + budget, self._run_deadline)

    def source(self, key, *, error=None):
        self._sources_used.add(key)
        self._source_info.setdefault(key, {"source": key, "collected_at": int(time.time())})
        if error:
            self._errors[key] = str(error)
        if key in self._errors:
            self._source_info[key]["error"] = self._errors[key]

    def read(self, path, *, optional=False):
        def load():
            try:
                return Path(path).read_text(errors="replace")
            except FileNotFoundError:
                if optional:
                    return ""
                raise
        return self._once(str(path), load) or ""

    @property
    def node(self):
        return socket.gethostname().split(".")[0]

    @property
    def policy(self):
        """What has been declared about this host, or nothing declared.

        Read once per assessment so every check judges against the same
        declaration, even if the file changes while a run is in progress.
        """
        def load():
            import audit_policy
            value = audit_policy.load()
            if value.error:
                self.source("policy", error=value.error)
            return value
        return self._once("policy", load)

    def _once(self, key: str, producer: Callable[[], Any]) -> Any:
        self.source(key)
        if key not in self._cache:
            parent_sources = self._sources_used
            self._sources_used = {key}
            try:
                self._cache[key] = producer()
            except Exception as exc:
                self._cache[key] = None
                self.source(key, error=exc)
            finally:
                self._dependencies[key] = self._sources_used - {key}
                parent_sources.update(self._sources_used)
                self._sources_used = parent_sources
        else:
            for dependency in self._dependencies.get(key, ()):
                self.source(dependency)
        return self._cache[key]

    def run(self, cmd: list[str], timeout: int = 10, allowed_codes=(0,)) -> tuple[int, str]:
        """Run a read-only command, returning exit code and output."""
        key = "cmd:" + json.dumps(cmd)
        self.source(key)
        if key in self._cache:
            return self._cache[key]
        try:
            remaining = min(timeout, self._check_deadline - time.monotonic(),
                            self._run_deadline - time.monotonic())
            if remaining <= 0:
                raise TimeoutError("assessment time budget exhausted")
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=remaining, env={**os.environ, "LC_ALL": "C", "LANG": "C"})
            result = (proc.returncode, (proc.stdout or "") + (proc.stderr or ""))
        except Exception as exc:
            result = (-1, str(exc))
        if result[0] not in allowed_codes:
            self.source(key, error=f"exit {result[0]}: {result[1][:500]}")
        self._cache[key] = result
        return result

    @property
    def lxc_configs(self) -> dict[int, str]:
        """Raw text of every local container configuration."""
        def load():
            out: dict[int, str] = {}
            base = Path("/etc/pve/lxc")
            if not base.is_dir():
                self.source("lxc_configs", error="local PVE configuration directory unavailable")
                return out
            for path in base.glob("*.conf"):
                try:
                    out[int(path.stem)] = path.read_text(errors="replace")
                except (OSError, ValueError) as exc:
                    self.source("lxc_configs", error=f"{path}: {exc}")
                    continue
            return out
        return self._once("lxc_configs", load) or {}

    @property
    def qemu_configs(self) -> dict[int, str]:
        def load():
            out: dict[int, str] = {}
            base = Path("/etc/pve/qemu-server")
            if not base.is_dir():
                self.source("qemu_configs", error="local PVE configuration directory unavailable")
                return out
            for path in base.glob("*.conf"):
                try:
                    out[int(path.stem)] = path.read_text(errors="replace")
                except (OSError, ValueError) as exc:
                    self.source("qemu_configs", error=f"{path}: {exc}")
                    continue
            return out
        return self._once("qemu_configs", load) or {}

    @property
    def cluster_configs(self):
        """Local pmxcfs view only, to protect volumes referenced by other nodes."""
        def load():
            result = {}
            base = Path("/etc/pve/nodes")
            if not base.is_dir():
                raise OSError("cluster configuration view unavailable")
            for kind in ("lxc", "qemu-server"):
                for path in base.glob(f"*/{kind}/*.conf"):
                    result[str(path)] = path.read_text(errors="replace")
            return result
        return self._once("cluster_configs", load) or {}

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
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    self.source("apt_sources", error=f"{path}: {exc}")
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
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    self.source("vzdump_jobs", error=f"{path}: {exc}")
            return text
        return self._once("vzdump_jobs", load) or ""

    def _run_lynis(self):
        """Produce a Lynis report.

        Returns the parsed report, whether this assessment produced it,
        and why it could not, so a check reports what actually happened
        rather than asserting a run that may never have started.
        """
        from security_manager import (_find_lynis_cmd, get_lynis_audit_status,
                                      parse_lynis_report, run_lynis_audit)
        if not _find_lynis_cmd():
            return None, False, None

        deadline = min(time.monotonic() + LYNIS_RUN_BUDGET, self._run_deadline)
        if not get_lynis_audit_status().get("running"):
            started, message = run_lynis_audit()
            if not started and "already running" not in (message or "").lower():
                reason = message or "Lynis could not be started"
                self.source("lynis:run", error=reason)
                return None, False, reason
        # A quick audit takes about a minute; the wait is bounded by the
        # budget and by the assessment's own deadline.
        while get_lynis_audit_status().get("running"):
            if time.monotonic() >= deadline:
                reason = "Lynis was still running when the time budget ran out"
                self.source("lynis:run", error=reason)
                return None, True, reason
            time.sleep(2)
        self.source("lynis:run")
        return parse_lynis_report(enrich_current=False), True, None

    @property
    def lynis_report(self) -> Optional[dict]:
        """The most recent Lynis audit, running one if there is none.

        An assessment that reports "not verified" because nobody has
        opened the Security page yet is reporting on the Monitor, not on
        the host. Where Lynis is installed and has no usable report — or
        only the remains of an interrupted run — the audit is produced
        here, because that reading is what was asked for. Where Lynis is
        not installed there is nothing to report and the checks do not
        apply.

        The run goes through Security's own entry point, which holds the
        lock that keeps two audits from starting at once, so an audit the
        user launched from that page is waited on rather than duplicated.
        """
        def load():
            from security_manager import parse_lynis_report, _find_lynis_cmd
            parsed = parse_lynis_report(enrich_current=False)
            ran, run_error = False, None
            # Launch Lynis only when the assessment was granted permission
            # (the user chose "with Lynis"). Then run it if there is no
            # usable report, or refresh a stored one that is past the
            # staleness threshold, since running is precisely what the
            # user consented to.
            if self._run_lynis_allowed:
                need_run = parsed is None or not parsed.get("is_complete")
                if not need_run:
                    src = next((p for p in (Path("/var/log/lynis-report.dat"),
                                            Path("/var/log/lynis-output.log"))
                                if p.exists()), None)
                    if src:
                        age_days = (time.time() - src.stat().st_mtime) / 86400
                        need_run = age_days >= self.policy.threshold("lynis_report_days")
                if need_run:
                    produced, ran, run_error = self._run_lynis()
                    if produced is not None:
                        parsed = produced
            if parsed is None:
                # No stored report and none produced. Where Lynis is
                # installed the check should say it was not run rather than
                # that it does not apply, so the reader knows a reading is
                # available on request.
                if not self._run_lynis_allowed and _find_lynis_cmd():
                    return {"mtime": 0, "source": "", "version": None,
                            "warnings": [], "suggestions": [],
                            "hardening_index": None, "complete": False,
                            "produced_here": False,
                            "run_error": "Lynis is installed but was not run "
                                         "for this assessment."}
                return None
            source = next((p for p in (Path("/var/log/lynis-report.dat"),
                                        Path("/var/log/lynis-output.log")) if p.exists()), None)
            return {
                "mtime": source.stat().st_mtime if source else 0,
                "source": str(source), "version": parsed.get("lynis_version"),
                "warnings": parsed.get("warnings", []),
                "suggestions": parsed.get("suggestions", []),
                "hardening_index": parsed.get("hardening_index"),
                "complete": parsed.get("is_complete", False),
                # What the assessment itself did, so a check can say
                # whether it is reporting a stored result or one it
                # produced, and why a produced one is unusable.
                "produced_here": ran,
                "run_error": run_error,
            }
        return self._once("lynis_report", load)

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
                raise
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
            except FileNotFoundError:
                return ""
        return self._once("pve_user_cfg", load) or ""

    @property
    def storage_snapshot(self):
        """Reuse recent Monitor storage observations; one PVE metadata read otherwise.

        Never invoke a mount, activate a volume, or connect to a remote host.
        A successful PVE resource query is not an end-to-end storage IO test.
        """
        def load():
            server = sys.modules.get("flask_server") or sys.modules.get("__main__")
            cache = copy.deepcopy(getattr(server, "_proxmox_storage_cache", {}))
            when = cache.get("time", 0)
            data = cache.get("data")
            if (isinstance(data, dict) and isinstance(data.get("storage"), list)
                    and "error" not in data and 0 <= time.time() - when <= 120):
                return {"rows": data["storage"], "collected_at": when,
                        "source": "Monitor storage cache", "units": "GiB"}
            rc, out = self.run(["pvesh", "get", "/cluster/resources", "--type", "storage",
                                "--output-format", "json"], timeout=10)
            if rc != 0:
                raise RuntimeError("PVE storage resource metadata unavailable")
            resources = json.loads(out)
            if not isinstance(resources, list) or any(not isinstance(r, dict) for r in resources):
                raise ValueError("unrecognised storage resource metadata")
            rows = [{"name": r.get("storage"), "node": r.get("node"),
                     "status": r.get("status", "unknown"), "total": r.get("maxdisk"),
                     "used": r.get("disk"), "type": r.get("plugintype")}
                    for r in resources if r.get("node") == self.node]
            return {"rows": rows, "collected_at": time.time(),
                    "source": "PVE cluster resource metadata", "units": "bytes"}
        return self._once("storage_snapshot", load) or {}

    def _block_devices(self) -> list[str]:
        """Real disks, as the kernel lists them."""
        # zd* are ZFS volumes and dm-* device-mapper targets: guest
        # storage rather than hardware, with no SMART to read.
        skip = ("loop", "ram", "zram", "dm-", "md", "sr", "nbd", "fd", "zd")
        try:
            return sorted(d.name for d in Path("/sys/block").iterdir()
                          if not d.name.startswith(skip))
        except OSError:
            return []

    @property
    def monitor_snapshot(self):
        """Copy existing Monitor data without triggering probes or importing Flask."""
        def load():
            server = sys.modules.get("flask_server") or sys.modules.get("__main__")
            smart = copy.deepcopy(getattr(server, "_smart_result_cache", {}))
            # That cache is filled by whoever last opened the storage view,
            # so an assessment can find it empty and report nothing about
            # disks the interface is already showing wear for. Ask through
            # the Monitor's own accessor for what is missing: it serves a
            # sleeping disk from its last known values rather than waking
            # it, and reuses the same 30 s memoisation the interface hits.
            reader = getattr(server, "get_smart_data", None)
            if callable(reader):
                for device in self._block_devices():
                    if device in smart:
                        continue
                    if time.monotonic() >= self._run_deadline:
                        break
                    try:
                        data = reader(device)
                    except Exception:
                        continue
                    if isinstance(data, dict):
                        smart[device] = (time.time(), data)
            health_module = sys.modules.get("health_monitor")
            monitor = getattr(health_module, "health_monitor", None)
            health = copy.deepcopy(getattr(monitor, "cached_results", {}).get("_bg_detailed"))
            when = getattr(monitor, "last_check_times", {}).get("_bg_detailed")
            return {"smart": smart, "health": health, "health_collected_at": when}
        return self._once("monitor_snapshot", load) or {}

    def metadata(self, checks):
        def local(path):
            try:
                return Path(path).read_text().strip()
            except OSError:
                return None
        version = (local(Path(__file__).resolve().parents[1] / "package.json") or
                   local(Path(__file__).resolve().parents[2] / "package.json"))
        try:
            version = json.loads(version or "{}").get("version")
        except ValueError:
            version = None
        rc, pve = self.run(["pveversion"], timeout=5)
        return {"host": self.node, "kernel": os.uname().release,
                "boot_id": local("/proc/sys/kernel/random/boot_id"),
                "proxmenux_version": version, "pve_version": pve.strip() if rc == 0 else None,
                "catalog_version": CATALOG_VERSION, "scope": "local node; no guest interior probes",
                "checks": [c.check_id for c in checks],
                "policy": self.policy.describe(),
                "health_snapshot": self.monitor_snapshot.get("health"),
                "health_collected_at": self.monitor_snapshot.get("health_collected_at")}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _classification_of(result: dict, check: "Check") -> str:
    """The gravity of a result, from the result itself.

    A check states the gravity of what it found. Where several objects
    were examined and each carries its own, the finding takes the gravest
    of them, because a report that says "observation" over an object it
    marked critical is wrong about the object it matters most for.
    """
    per_object = [o.get("classification") for o in (result.get("affected") or [])
                  if isinstance(o, dict) and o.get("classification")]
    declared = result.get("classification")
    values = ([declared] if declared else []) + per_object
    if result.get("incomplete"):
        values.append(audit_store.CLASS_UNVERIFIED)
    if any(v not in audit_store.CLASSIFICATIONS for v in values):
        values.append(audit_store.CLASS_UNVERIFIED)
    problems = [v for v in values if v in audit_store.CLASS_PROBLEMS]
    if problems:
        return audit_store.worst(problems)
    if audit_store.CLASS_UNVERIFIED in values:
        return audit_store.CLASS_UNVERIFIED
    if values:
        return audit_store.worst(values)
    if declared in audit_store.CLASSIFICATIONS:
        return declared
    # A check that has not been migrated to the scale is read on it from
    # what it used to return, so the catalogue keeps working while the
    # rules are revised one by one.
    return audit_store.classification_of(
        result.get("state", audit_store.STATE_UNKNOWN), check.severity)


def run_assessment(profile: str = "full",
                   only_areas: Optional[set[str]] = None, *, run_id=None,
                   progress=None, run_lynis: bool = False) -> str:
    """Evaluate every registered check and persist the result.

    A check that raises is recorded as unverified with the error kept
    as evidence. One faulty check must never abort an assessment: a
    partial report that says which check failed is more useful than no
    report at all.
    """
    import audit_profiles
    if not audit_profiles.is_known(profile) or (
            only_areas is not None and (not only_areas or not only_areas <= set(AREAS))):
        raise ValueError("unsupported audit profile or areas")
    # The profile narrows the catalogue to its question; an explicit area
    # filter narrows it further within that.
    checks = audit_profiles.selected_checks(profile, registered_checks())
    if only_areas is not None:
        checks = [c for c in checks if c.area in only_areas]
    ctx = AuditContext(run_lynis=run_lynis)
    exceptions = audit_store.active_exceptions()
    metadata = ctx.metadata(checks)
    if run_id is None:
        run_id = audit_store.start_run(profile, metadata, len(checks))
    else:
        audit_store.update_run_metadata(run_id, metadata, len(checks))
    findings: list[dict[str, Any]] = []
    error: Optional[str] = None

    try:
        for check in checks:
            ctx.begin_check(check.budget)
            if progress:
                progress(run_id, len(findings), len(checks), check.check_id)
            started = time.monotonic()
            try:
                if started >= ctx._run_deadline:
                    raise TimeoutError("assessment time budget exhausted")
                result = check.evaluate(ctx)
                if result is not None and (not isinstance(result, dict)
                        or not isinstance(result.get("affected", []), list)
                        or any(not isinstance(obj, dict) for obj in result.get("affected", []))):
                    raise ValueError("invalid check result")
            except Exception as exc:
                result = {
                    "classification": audit_store.CLASS_UNVERIFIED,
                    "summary_key": "evaluationFailed",
                    "evidence": f"{type(exc).__name__}: {exc}",
                }
            elapsed = time.monotonic() - started

            if result is None:
                # No prose here: this sentence reached a report that
                # exists in eight languages. The interface says it in the
                # reader's own, and a check with something specific to
                # say returns its own summary instead of None.
                result = {"classification": audit_store.CLASS_NOT_APPLICABLE}

            errors = [f"{k}: {ctx._errors[k]}" for k in ctx._sources_used if k in ctx._errors]
            if elapsed > check.budget:
                errors.append("check time budget exceeded")
            if errors:
                result["incomplete"] = True
                result["evidence"] = (result.get("evidence") or "") + "\n" + "\n".join(errors)
                # A source that could not be read cannot turn into a clean
                # result, but it must not soften one that already found a
                # problem either: what was found stands, what was missed is
                # named.
                if _classification_of(result, check) not in audit_store.CLASS_PROBLEMS:
                    result.update(classification=audit_store.CLASS_UNVERIFIED,
                                  summary_key="evaluationFailed")

            classification = _classification_of(result, check)
            # An accepted risk keeps its evidence and its declared
            # severity; only the state changes, so the report can still
            # show what was accepted and why it mattered.
            evidence = result.get("evidence")
            # Names already collected by a check are display metadata, not a
            # reason to probe guests again or alter the finding's scope.
            for obj in result.get("affected") or []:
                vmid = obj.get("vmid")
                if vmid is None or obj.get("name"):
                    continue
                for cache_key, field in (("lxc_configs", "hostname"), ("qemu_configs", "name")):
                    config = (getattr(ctx, "_cache", {}).get(cache_key) or {}).get(vmid, "")
                    match = re.search(r"^" + field + r":\s*(.+)$", config, re.MULTILINE)
                    if match:
                        obj["name"] = match.group(1).strip()
                        break
            finding = {
                "check_id": check.check_id,
                "area": check.area,
                # Retained as the gravity the check can reach at worst,
                # which is what the catalogue advertises; the finding's own
                # gravity is its classification.
                "severity": check.severity,
                "classification": classification,
                "summary_key": result.get("summary_key"),
                "summary_params": result.get("summary_params") or {},
                "affected": result.get("affected") or [],
                "evidence": evidence,
                "remediable_by": result.get("remediable_by"),
                "raw_classification": classification,
                "check_version": check.version, "host": ctx.node,
                "collected_at": int(time.time()), "incomplete": result.get("incomplete", False),
                "observations": result.get("observations", []),
                "sources": [ctx._source_info[k] for k in sorted(ctx._sources_used)],
            }
            finding["scope"] = audit_store.finding_scope(finding)
            decision = exceptions.get(check.check_id)
            if (classification in audit_store.CLASS_PROBLEMS and decision
                    and decision.get("scope") == finding["scope"] and not finding["incomplete"]
                    and (decision.get("expires_at") is None or decision["expires_at"] > time.time())):
                finding.update(decision=audit_store.DECISION_ACCEPTED, exception=decision)
            findings.append(finding)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    audit_store.record_findings(run_id, findings)
    audit_store.finish_run(
        run_id, checks_total=len(findings), error=error,
        partial=any(f["classification"] == audit_store.CLASS_UNVERIFIED
                    or f.get("incomplete") for f in findings))
    if progress:
        progress(run_id, len(findings), len(checks), None)
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
    problems = set(audit_store.CLASS_PROBLEMS)
    base = {f["check_id"]: f for f in audit_store.get_findings(base_run)}
    other = {f["check_id"]: f for f in audit_store.get_findings(other_run)}

    new, resolved, accepted, unchanged, unverified = [], [], [], [], []
    for check_id, current in other.items():
        previous = base.get(check_id)
        was = previous["classification"] in problems if previous else False
        now = current["classification"] in problems
        if current["classification"] in (audit_store.CLASS_UNVERIFIED,
                                         audit_store.CLASS_NOT_APPLICABLE) \
                or current.get("incomplete"):
            unverified.append(current)
        elif now and current.get("decision") == audit_store.DECISION_ACCEPTED:
            accepted.append(current)
        elif now and (not was or previous["classification"] != current["classification"]):
            new.append(current)
        elif was and not now:
            if current.get("decision") == audit_store.DECISION_ACCEPTED:
                accepted.append(current)
            elif current["classification"] in (audit_store.CLASS_CONFORMANT,
                                               audit_store.CLASS_OBSERVATION):
                resolved.append(current)
        elif previous and previous["classification"] == current["classification"]:
            unchanged.append(current)
    # A check present in the base run but absent from the later one was
    # retired between the two. It is reported as no longer assessed rather
    # than as resolved, since nothing verified that it stopped failing.
    retired = [
        previous for check_id, previous in base.items()
        if check_id not in other and previous["classification"] in problems
    ]

    return {
        "new": new,
        "resolved": resolved,
        "accepted": accepted,
        "unchanged": unchanged,
        "retired": retired,
        "unverified": unverified,
    }
