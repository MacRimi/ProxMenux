"""Declared policy for Audit & Report.

An assessment can see what a host does; it cannot see what the host is
*for*. Whether a guest needs a backup, whether a service has to come back
by itself after a reboot, whether a storage is essential or convenient —
none of that is discoverable, and guessing at it is what turns an
ordinary configuration into an alarm.

So the audit reports an absence it cannot interpret as an observation,
and only calls it a warning once somebody has declared what was expected.
Nothing here is required: a host with no policy at all still produces a
complete report, just one that describes rather than judges.

The declaration lives in ``/usr/local/share/proxmenux/audit_policy.json``
and is written by hand or by the interface. It is read, never inferred:
if the file is missing, malformed or partial, every unstated question
stays unstated.

A guest marked as exempt is not a risk somebody accepted. It is a guest
outside the scope of the expectation, so it leaves the count entirely
rather than appearing as something to justify.
"""
from __future__ import annotations

import json
import fcntl
import hashlib
import math
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

POLICY_PATH = Path("/usr/local/share/proxmenux/audit_policy.json")

SCHEMA_VERSION = 1

# What a declaration can say about an expectation.
REQUIRED = "required"
NOT_REQUIRED = "not_required"
UNSPECIFIED = "unspecified"

_EXPECTATIONS = (REQUIRED, NOT_REQUIRED, UNSPECIFIED)

# What a site can declare about the host itself, as opposed to about a
# guest. Each is read as "is this expected here": `firewall: required`
# expects the switch on, `ssh_root_login: not_required` expects that
# access not to be available.
HOST_EXPECTATIONS = ("firewall", "ssh_root_login")

# What a storage is for, which decides how gravely its loss reads.
ROLE_ESSENTIAL = "essential"
ROLE_OPTIONAL = "optional"
ROLE_UNSPECIFIED = "unspecified"

_ROLES = (ROLE_ESSENTIAL, ROLE_OPTIONAL, ROLE_UNSPECIFIED)

# Thresholds a site may want to move. The defaults are the values the
# checks used before policy existed, so a host without a declaration
# behaves exactly as it did.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "storage_usage_percent": 90,
    "thin_pool_usage_percent": 90,
    "thin_overprovision_ratio": 2.0,
    "zfs_scrub_days": 35,
    "backup_fallback_days": 30,
    "backup_schedule_grace_ratio": 0.5,
    "certificate_expiry_days": 30,
    "memory_overcommit_ratio": 1.5,
    "disk_service_life_hours": 43800,
    "lynis_report_days": 30,
    "package_index_days": 7,
    "journal_usage_percent": 80,
    "filesystem_usage_percent": 90,
    "filesystem_inode_percent": 90,
    "disk_error_recent_days": 7,
}

_lock = threading.Lock()


class PolicyConflict(ValueError):
    """The declaration changed after the editor read it."""


def _valid_number(value, name: str = "") -> bool:
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and value > 0 and (not name.endswith("_percent") or value <= 100))
    except OverflowError:
        return False


class Policy:
    """One reading of the declaration, answering only what it was told."""

    def __init__(self, raw: Optional[dict] = None, source: str = "",
                 error: Optional[str] = None, revision: str = "missing"):
        raw = raw if isinstance(raw, dict) else {}
        self.source = source
        self.error = error
        self.revision = revision
        self.declared = bool(raw)
        self._guests = raw.get("guests") if isinstance(raw.get("guests"), dict) else {}
        self._storages = raw.get("storages") if isinstance(raw.get("storages"), dict) else {}
        self._defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
        self._host = raw.get("host") if isinstance(raw.get("host"), dict) else {}
        thresholds = raw.get("thresholds") if isinstance(raw.get("thresholds"), dict) else {}
        self._thresholds = {}
        for name, value in thresholds.items():
            # A malformed threshold falls back to the default rather than
            # silently disabling the check it belongs to.
            if name in DEFAULT_THRESHOLDS and _valid_number(value, name):
                self._thresholds[name] = float(value)

    # -- guests ------------------------------------------------------

    def _guest(self, vmid) -> dict:
        entry = self._guests.get(str(vmid))
        return entry if isinstance(entry, dict) else {}

    def expectation(self, vmid, name: str) -> str:
        """Whether something is expected of a guest, as declared.

        Falls back to the site default for that expectation, and to
        ``unspecified`` when neither says anything.
        """
        value = self._guest(vmid).get(name)
        if value not in _EXPECTATIONS:
            value = self._defaults.get(name)
        return value if value in _EXPECTATIONS else UNSPECIFIED

    def backup_required(self, vmid) -> str:
        return self.expectation(vmid, "backup")

    def autostart_required(self, vmid) -> str:
        return self.expectation(vmid, "autostart")

    def guest_note(self, vmid) -> str:
        note = self._guest(vmid).get("note")
        return note if isinstance(note, str) else ""

    def recovery_objective_hours(self, vmid) -> Optional[float]:
        """How old a guest's newest backup may be before it is a warning.

        Declared per guest because it is a property of the workload, not
        of the schedule that happens to protect it.
        """
        value = self._guest(vmid).get("recovery_objective_hours")
        if value is None:
            value = self._defaults.get("recovery_objective_hours")
        return float(value) if _valid_number(value) else None

    # -- the host itself ---------------------------------------------

    def host_expectation(self, name: str) -> str:
        """What the site declares about the host's own configuration.

        Kept apart from ``defaults``, which are per-guest fallbacks. The
        vocabulary is the same one the guest expectations use, read the
        same way: ``ssh_root_login: not_required`` says that access is
        not meant to be available here, and ``firewall: required`` says
        the switch is meant to be on. Undeclared means the check states
        the fact and does not judge it.
        """
        value = self._host.get(name)
        return value if value in _EXPECTATIONS else UNSPECIFIED

    def exempt_guests(self, name: str) -> set:
        """Guests explicitly declared as not needing something."""
        return {vmid for vmid, entry in self._guests.items()
                if isinstance(entry, dict) and entry.get(name) == NOT_REQUIRED}

    # -- storages ----------------------------------------------------

    def storage_role(self, storage_id: str) -> str:
        entry = self._storages.get(storage_id)
        role = entry.get("role") if isinstance(entry, dict) else None
        if role not in _ROLES:
            role = self._defaults.get("storage_role")
        return role if role in _ROLES else ROLE_UNSPECIFIED

    # -- thresholds --------------------------------------------------

    def threshold(self, name: str) -> float:
        if name in self._thresholds:
            return self._thresholds[name]
        return float(DEFAULT_THRESHOLDS[name])

    def is_default(self, name: str) -> bool:
        """Whether a threshold is the shipped value or a declared one."""
        return name not in self._thresholds

    # -- reporting ---------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """What the report says about the policy it applied."""
        return {
            "declared": self.declared,
            "source": self.source or str(POLICY_PATH),
            "guests_declared": len(self._guests),
            "storages_declared": len(self._storages),
            "thresholds_declared": sorted(self._thresholds),
            "host_declared": sorted(k for k in self._host if k in HOST_EXPECTATIONS),
            "error": self.error,
            "revision": self.revision,
        }


def load(path: Path = POLICY_PATH) -> Policy:
    """Read one complete snapshot of the small declaration file.

    An unreadable or malformed file is reported as an error and treated as
    no declaration at all. Falling back to an assumed policy would be
    worse than having none: it would judge the host against expectations
    nobody set.
    """
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return Policy(source=str(path))
    except OSError as exc:
        return Policy(source=str(path), error=f"{type(exc).__name__}: {exc}")
    revision = hashlib.sha256(content).hexdigest()
    try:
        raw = json.loads(content)
        _clean(raw)
        return Policy(raw, source=str(path), revision=revision)
    except (ValueError, UnicodeError, OverflowError) as exc:
        return Policy(source=str(path), error=f"{type(exc).__name__}: {exc}",
                      revision=revision)


def _clean(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("the declaration must be an object")

    cleaned: dict[str, Any] = {"version": SCHEMA_VERSION,
                               "updated_at": int(time.time())}

    guests = raw.get("guests", {})
    if not isinstance(guests, dict):
        raise ValueError("guests must be an object keyed by VMID")
    kept_guests: dict[str, dict] = {}
    for vmid, entry in guests.items():
        if not str(vmid).isdigit() or not isinstance(entry, dict):
            raise ValueError(f"invalid guest declaration: {vmid}")
        kept: dict[str, Any] = {}
        for name in ("backup", "autostart"):
            value = entry.get(name)
            if value in _EXPECTATIONS:
                kept[name] = value
            elif value is not None:
                raise ValueError(f"invalid expectation for guest {vmid}: {name}={value}")
        rpo = entry.get("recovery_objective_hours")
        if rpo is not None:
            if not _valid_number(rpo):
                raise ValueError(f"invalid recovery objective for guest {vmid}: {rpo}")
            kept["recovery_objective_hours"] = float(rpo)
        note = entry.get("note")
        if isinstance(note, str) and note.strip():
            kept["note"] = note.strip()[:500]
        if kept:
            kept_guests[str(vmid)] = kept
    cleaned["guests"] = kept_guests

    storages = raw.get("storages", {})
    if not isinstance(storages, dict):
        raise ValueError("storages must be an object keyed by storage id")
    kept_storages: dict[str, dict] = {}
    for storage_id, entry in storages.items():
        if not isinstance(entry, dict):
            raise ValueError(f"invalid storage declaration: {storage_id}")
        role = entry.get("role")
        if role in _ROLES:
            kept_storages[str(storage_id)] = {"role": role}
        elif role is not None:
            raise ValueError(f"invalid role for storage {storage_id}: {role}")
    cleaned["storages"] = kept_storages

    thresholds = raw.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise ValueError("thresholds must be an object")
    kept_thresholds: dict[str, float] = {}
    for name, value in thresholds.items():
        if name not in DEFAULT_THRESHOLDS:
            raise ValueError(f"unknown threshold: {name}")
        if not _valid_number(value, name):
            raise ValueError(f"invalid value for {name}: {value}")
        kept_thresholds[name] = float(value)
    cleaned["thresholds"] = kept_thresholds

    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("defaults must be an object")
    kept_defaults: dict[str, Any] = {}
    for name in ("backup", "autostart"):
        if defaults.get(name) in _EXPECTATIONS:
            kept_defaults[name] = defaults[name]
        elif defaults.get(name) is not None:
            raise ValueError(f"invalid default expectation: {name}")
    if defaults.get("storage_role") in _ROLES:
        kept_defaults["storage_role"] = defaults["storage_role"]
    elif defaults.get("storage_role") is not None:
        raise ValueError("invalid default storage role")
    if defaults.get("recovery_objective_hours") is not None:
        if not _valid_number(defaults["recovery_objective_hours"]):
            raise ValueError("invalid default recovery objective")
        kept_defaults["recovery_objective_hours"] = float(
            defaults["recovery_objective_hours"])
    cleaned["defaults"] = kept_defaults

    host = raw.get("host", {})
    if not isinstance(host, dict):
        raise ValueError("host must be an object")
    kept_host: dict[str, Any] = {}
    for name in HOST_EXPECTATIONS:
        if host.get(name) in _EXPECTATIONS:
            kept_host[name] = host[name]
        elif host.get(name) is not None:
            raise ValueError(f"invalid host expectation: {name}")
    cleaned["host"] = kept_host
    return cleaned


def save(raw: dict, path: Path = POLICY_PATH,
         expected_revision: Optional[str] = None) -> Policy:
    """Validate and atomically replace a declaration, rejecting stale editors.

    The process lock and flock cover revision comparison and replacement.
    Each writer owns a private 0600 temporary file in the target directory.
    """
    cleaned = _clean(raw)
    content = json.dumps(cleaned, indent=2, ensure_ascii=False, allow_nan=False) + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        lock_fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(lock_fd, "a") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            current = load(path)
            if expected_revision is not None and current.revision != expected_revision:
                raise PolicyConflict("The declaration changed in another session; reload before saving.")
            if current.error:
                raise ValueError(current.error)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                                 dir=path.parent, prefix=".audit-policy-",
                                                 delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return load(path)
