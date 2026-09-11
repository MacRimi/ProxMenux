"""Proxmox-specific checks for Audit & Report.

Importing this module registers its checks. Everything here reads the
host and reports; nothing modifies it.

The checks are deliberately about configuration and posture rather than
transient load. A condition that resolves on its own as usage drops
belongs to the health monitor, which keeps its own catalogue and remains
the source of notifications.
"""
from __future__ import annotations

import calendar
from datetime import datetime
import math
import json
import shlex
import socket
import sys
import re
import time
from pathlib import Path

import audit_store
from audit_checks import (
    AREA_BACKUP, AREA_GUESTS, AREA_HARDWARE, AREA_NETWORK, AREA_SECURITY,
    AREA_STORAGE, AREA_SYSTEM, LYNIS_RUN_BUDGET, register,
)
import audit_policy

CLASS_CRITICAL = audit_store.CLASS_CRITICAL
CLASS_WARNING = audit_store.CLASS_WARNING
CLASS_OBSERVATION = audit_store.CLASS_OBSERVATION
CLASS_CONFORMANT = audit_store.CLASS_CONFORMANT
CLASS_UNVERIFIED = audit_store.CLASS_UNVERIFIED
CLASS_NOT_APPLICABLE = audit_store.CLASS_NOT_APPLICABLE


def _unverified(evidence, **extra):
    return {"classification": CLASS_UNVERIFIED, "summary_key": "evaluationFailed",
            "incomplete": True, "evidence": str(evidence), **extra}


def _current_config(text):
    """Snapshots and pending sections must not override effective settings."""
    return re.split(r"^\[", text, maxsplit=1, flags=re.M)[0]


def _guest_configs(configs):
    return {v: _current_config(t) for v, t in configs.items()
            if not re.search(r"^template:\s*1\s*$", _current_config(t), re.M)}


def _local_enabled(item, ctx):
    nodes = re.split(r"[,;\s]+", item.get("nodes", item.get("node", "")).strip())
    node = getattr(ctx, "node", socket.gethostname().split(".")[0])
    return (item.get("enabled", "1").strip() != "0" and
            item.get("disable", "0").strip() != "1" and
            (nodes == [""] or node in nodes))


def _job_guests(job, guests, pools):
    selected = set(guests) if job.get("all", "0").strip() == "1" else {
        int(x) for x in re.findall(r"\d+", job.get("vmid", ""))}
    for pool in re.split(r"[,\s]+", job.get("pool", "").strip()):
        selected |= pools.get(pool, set())
    return (selected - {int(x) for x in re.findall(r"\d+", job.get("exclude", ""))}) & set(guests)


def _backup_exclusions(ctx):
    excluded = []
    for kind, configs in (("lxc", ctx.lxc_configs), ("qemu", ctx.qemu_configs)):
        for vmid, text in _guest_configs(configs).items():
            for line in text.splitlines():
                m = re.match(r"^(rootfs|mp\d+|(?:scsi|sata|ide|virtio)\d+):\s*(.*)", line)
                if not m:
                    continue
                disk, value = m.groups()
                if "media=cdrom" in value:
                    continue
                source = value.split(",", 1)[0]
                if (re.search(r"(?:^|,)backup=0(?:,|$)", value) or
                    (kind == "lxc" and disk.startswith("mp") and
                     (source.startswith("/") or not re.search(r"(?:^|,)backup=1(?:,|$)", value)))):
                    excluded.append({"vmid": vmid, "type": kind, "volume": disk,
                                     "source": source, "reason": "data excluded from guest backup"})
    return excluded


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def _parse_vzdump_jobs(text: str) -> list[dict]:
    """Split ``jobs.cfg`` into one entry per backup job.

    A job opens with ``vzdump: <id>`` and its settings follow as indented
    ``key value`` lines. Values are kept verbatim; interpretation belongs
    to the caller.
    """
    jobs: list[dict] = []
    current: dict | None = None
    for line_number, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace() and re.search(r"(?:^|\s)(?:/\S*/)?vzdump\s", line):
            parts = shlex.split(line)
            pos = next(i for i, p in enumerate(parts) if p.rsplit("/", 1)[-1] == "vzdump")
            job = {"id": f"legacy-{line_number}", "schedule": "cron: " + " ".join(parts[:5])}
            args = parts[pos + 1:]
            index = 0
            while index < len(args):
                value = args[index]
                if value.isdigit():
                    job["vmid"] = (job.get("vmid", "") + " " + value).strip()
                elif value.startswith("--"):
                    key, sep, val = value[2:].partition("=")
                    if not sep and index + 1 < len(args) and not args[index + 1].startswith("--"):
                        index += 1
                        val = args[index]
                    job[key] = val or "1"
                index += 1
            jobs.append(job)
            current = None
            continue
        header = re.match(r"^vzdump:\s*(\S+)", line)
        if header:
            current = {"id": header.group(1)}
            jobs.append(current)
            continue
        if re.match(r"^\S+:\s", line):
            current = None
        if current is None or not line[:1].isspace():
            continue
        parts = line.strip().split(None, 1)
        if parts:
            current[parts[0]] = parts[1] if len(parts) > 1 else ""
    return jobs


def _pool_members(text: str) -> dict[str, set[int]]:
    """Map pool name to member guest identifiers from ``user.cfg``.

    Pool entries are colon-separated: ``pool:<name>:<comment>:<vmids>:``.
    """
    pools: dict[str, set[int]] = {}
    for line in (text or "").splitlines():
        if not line.startswith("pool:"):
            continue
        fields = line.split(":")
        if len(fields) < 4:
            continue
        pools[fields[1]] = {int(x) for x in re.findall(r"\d+", fields[3])}
    return pools


@register("backup.guest_coverage", AREA_BACKUP, "CRITICAL")
def _guest_coverage(ctx):
    """Which guests an enabled backup job selects, and which none does.

    A job selects guests by enumerating them (``vmid``), by taking every
    guest (``all 1``), or by pool, and may subtract an ``exclude`` list.
    A job carrying ``enabled 0`` selects nothing: it is defined but never
    runs, which is precisely the situation this check exists to surface,
    since a disabled job looks like coverage in the interface.

    What it does not know is whether an unselected guest was meant to be
    protected. A machine built for an afternoon and a production database
    look identical from here, so an absence is reported as an observation
    until somebody declares the expectation. Where the declaration says a
    guest must be protected and no job selects it, that is a warning: an
    expected protection is missing. Where it says the guest is exempt, it
    leaves the count entirely rather than appearing as something to
    justify.
    """
    guests = {}
    for vmid in _guest_configs(ctx.lxc_configs):
        guests[vmid] = "lxc"
    for vmid in _guest_configs(ctx.qemu_configs):
        guests[vmid] = "qemu"
    if not guests:
        return None

    policy = ctx.policy
    jobs = _parse_vzdump_jobs(ctx.vzdump_jobs)
    pools = _pool_members(ctx.pve_user_cfg)
    covered: set[int] = set()
    considered: list[str] = []
    skipped: list[str] = []

    for job in jobs:
        if not _local_enabled(job, ctx):
            skipped.append(f"{job['id']} (disabled or assigned to another node)")
            continue
        selected = _job_guests(job, guests, pools)
        covered |= selected
        considered.append(f"{job['id']} -> {sorted(selected) or 'nothing'}; "
                          f"storage={job.get('storage', 'node default')}; "
                          f"schedule={job.get('schedule', 'unknown')}")

    evidence = "enabled jobs:\n  " + ("\n  ".join(considered) or "(none)")
    if skipped:
        evidence += "\nignored jobs:\n  " + "\n  ".join(skipped)
    evidence += ("\nTemplates excluded. Configured coverage does not prove a "
                 "stored or restorable backup.")

    uncovered, exempt = [], []
    for vmid in sorted(set(guests) - covered):
        expectation = policy.backup_required(vmid)
        if expectation == audit_policy.NOT_REQUIRED:
            exempt.append({"vmid": vmid, "type": guests[vmid],
                           "note": policy.guest_note(vmid),
                           "classification": CLASS_NOT_APPLICABLE,
                           "decision": audit_store.DECISION_BY_DESIGN,
                           "reason_key": "exemptByPolicy"})
            continue
        uncovered.append({
            "vmid": vmid, "type": guests[vmid],
            "classification": (CLASS_WARNING
                               if expectation == audit_policy.REQUIRED
                               else CLASS_OBSERVATION),
            "reason_key": ("expectedButUncovered"
                           if expectation == audit_policy.REQUIRED
                           else "noJobSelectsGuest"),
        })

    if exempt:
        evidence += ("\nDeclared as not requiring a backup: "
                     + ", ".join(str(g["vmid"]) for g in exempt))

    # Data a job deliberately leaves out is reported separately from a
    # guest nothing protects: one is a decision recorded in the guest's
    # own configuration, the other is an absence of any decision.
    exclusions = _backup_exclusions(ctx)
    if exclusions:
        evidence += "\nExcluded data:\n" + json.dumps(exclusions, indent=2)
        for row in exclusions:
            row.setdefault("classification", CLASS_OBSERVATION)
            row.setdefault("reason_key", "dataExcludedFromBackup")

    if not jobs:
        # No job at all is different from a guest that no job selects:
        # nothing on this node is scheduled to be protected.
        required = [g for g in uncovered
                    if g["classification"] == CLASS_WARNING]
        return {
            "classification": CLASS_WARNING if required else CLASS_OBSERVATION,
            "summary_key": "noJobs",
            "summary_params": {"total": len(guests)},
            "affected": uncovered,
            "evidence": evidence + "\nNo job definitions found in "
                                   "/etc/pve/jobs.cfg or /etc/vzdump.cron.",
        }

    affected = uncovered + exclusions + exempt
    if not uncovered and not exclusions:
        return {
            "classification": CLASS_CONFORMANT,
            "summary_key": "covered",
            "summary_params": {"total": len(guests), "exempt": len(exempt)},
            "evidence": evidence,
        }
    if not uncovered:
        return {"classification": CLASS_OBSERVATION, "summary_key": "excludedData",
                "affected": exclusions + exempt,
                "summary_params": {"count": len(exclusions)},
                "evidence": evidence}

    required = [g for g in uncovered if g["classification"] == CLASS_WARNING]
    return {
        # The finding takes the gravity of its gravest guest; with nothing
        # declared, that is an observation.
        "summary_key": "uncoveredExpected" if required else "uncovered",
        "summary_params": {"count": len(uncovered), "total": len(guests),
                           "required": len(required), "exempt": len(exempt)},
        "affected": affected,
        "evidence": evidence + "\nuncovered: "
                    + ", ".join(str(g["vmid"]) for g in uncovered),
    }


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@register("system.pending_reboot", AREA_SYSTEM, "WARNING")
def _pending_reboot(ctx):
    """What is installed but not yet running.

    Two things say the same thing in different ways: the marker Debian
    writes when a package needs a restart, and a kernel that is installed
    and selected but not the one running. They are read together because
    they are one question — is there work waiting for a reboot — and
    reporting them separately counts the same maintenance twice.

    The absence of the marker does not prove nothing needs restarting,
    only that nothing asked for it, so a clean result says exactly that.
    """
    marker = Path("/var/run/reboot-required")
    packages = ""
    pkg_file = Path("/var/run/reboot-required.pkgs")
    if pkg_file.exists():
        try:
            packages = pkg_file.read_text(errors="replace").strip()
        except OSError:
            packages = ""

    rc, running = ctx.run(["uname", "-r"])
    running = running.strip()
    # A newer kernel installed and not running is the running-kernel
    # check's subject: it reads the boot selection as well and can say
    # whether the host would even start it. Counting it here too put the
    # same fact in two findings and in two counters.
    newer = None

    pending = []
    for name in packages.splitlines():
        if name.strip():
            pending.append({"package": name.strip(),
                            "classification": CLASS_OBSERVATION,
                            "reason_key": "packageAwaitingRestart"})
    if newer:
        pending.append({"kernel": newer, "running": running,
                        "classification": CLASS_OBSERVATION,
                        "reason_key": "kernelAwaitingReboot"})

    installed = _newer_kernel_installed(ctx, running)
    evidence = f"running kernel: {running}\n"
    evidence += (f"reboot marker: {'present' if marker.exists() else 'absent'}\n")
    evidence += f"packages requesting a restart:\n{packages or '(none reported)'}"
    if installed:
        evidence += (f"\nnewest installed kernel: {installed}, reported by the "
                     "running-kernel check, which reads the boot selection too")
    evidence += ("\nA kernel may be held deliberately, and the absence of the "
                 "marker does not prove that nothing needs restarting.")

    if not marker.exists() and not newer:
        return {"classification": CLASS_CONFORMANT, "summary_key": "none",
                "evidence": evidence}
    if marker.exists() and not pending:
        # The marker is the evidence. Something wrote it and did not say
        # what; reporting that as unverified described the reading rather
        # than the host, which had plainly asked for a restart.
        pending.append({"name": "reboot-required",
                        "classification": CLASS_OBSERVATION,
                        "reason_key": "rebootMarkerWithoutPackages"})
    return {"summary_key": "pending", "summary_params": {"count": len(pending)},
            "affected": pending, "evidence": evidence}


def _newer_kernel_installed(ctx, running: str):
    """The newest installed kernel, when it is newer than the running one."""
    rc, out = ctx.run(["dpkg-query", "-W", "-f=${db:Status-Status} ${Package}\n"])
    installed = set()
    for line in (out or "").splitlines():
        m = re.search(r"^installed (?:proxmox|pve)-kernel-(\d[\w.\-]*?)(?:-signed)?$",
                      line.strip())
        if m:
            installed.add(m.group(1))
    if not installed or not running:
        return None
    newest = max(installed, key=_version_key)
    return newest if _version_key(newest) > _version_key(running) else None


@register("system.enterprise_repo_without_subscription", AREA_SYSTEM, "WARNING")
def _enterprise_repo(ctx):
    """Describe repository/subscription configuration, not host conformance."""
    enabled = []
    for path, text in ctx.apt_sources.items():
        if path.endswith(".sources"):
            for stanza in re.split(r"\n\s*\n", text):
                if re.search(r"^Enabled:\s*(?:no|false|0)\s*$", stanza, re.M | re.I):
                    continue
                for line in stanza.splitlines():
                    if re.match(r"^URIs:", line, re.I) and "enterprise.proxmox.com" in line:
                        enabled.append((path, line.strip()))
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if re.match(r"^deb(?:-src)?\s", stripped) and "enterprise.proxmox.com" in stripped:
                enabled.append((path, stripped))
    if not enabled:
        return {
            "classification": CLASS_OBSERVATION,
            "summary_key": "notEnabled",
        }

    rc, out = ctx.run(["pvesubscription", "get"])
    status = ""
    for line in (out or "").splitlines():
        if line.lower().startswith("status:"):
            status = line.split(":", 1)[1].strip().lower()
            break

    evidence = "\n".join(f"{p}: {l}" for p, l in enabled)
    evidence += f"\n\npvesubscription status: {status or '(unavailable)'}"

    if rc != 0 or status not in ("active", "new", "notfound", "invalid", "expired", "suspended"):
        return {
            "classification": CLASS_UNVERIFIED,
            "summary_key": "evaluationFailed",
            "evidence": evidence,
        }
    if status in ("active", "new"):
        return {
            "classification": CLASS_OBSERVATION,
            "summary_key": "subscribed",
            "evidence": evidence,
        }
    return {
        "classification": CLASS_WARNING,
        "summary_key": "unsubscribed",
        "affected": [{"file": p, "line": l} for p, l in enabled],
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Guests
# ---------------------------------------------------------------------------

@register("guests.privileged_containers", AREA_GUESTS, "WARNING")
def _privileged_containers(ctx):
    """Containers running privileged.

    A privileged container shares the host's user namespace, so a process
    that escapes it is already root on the hypervisor. Proxmox creates
    containers unprivileged by default; a container is privileged when
    ``unprivileged: 1`` is absent from its configuration.
    """
    configs = _guest_configs(ctx.lxc_configs)
    if not configs:
        return None

    privileged = []
    for vmid, text in sorted(configs.items()):
        if not re.search(r"^unprivileged:\s*1\s*$", text, re.M):
            name = ""
            m = re.search(r"^hostname:\s*(\S+)", text, re.M)
            if m:
                name = m.group(1)
            privileged.append({"vmid": vmid, "name": name})

    if not privileged:
        return {
            "classification": CLASS_CONFORMANT,
            "summary_key": "allUnprivileged",
            "summary_params": {"total": len(configs)},
        }
    listed = ", ".join(
        f"{c['vmid']}{' (' + c['name'] + ')' if c['name'] else ''}"
        for c in privileged
    )
    # Some workloads need the privilege. Reporting it is useful; calling
    # it a fault would be telling the reader to undo a deliberate choice.
    for row in privileged:
        row["classification"] = CLASS_OBSERVATION
        row["reason_key"] = "runsPrivileged"
    return {
        "summary_key": "privileged",
        "summary_params": {"count": len(privileged), "total": len(configs)},
        "affected": privileged,
        "evidence": f"privileged containers: {listed}",
    }


@register("guests.qemu_without_agent", AREA_GUESTS, "INFO")
def _qemu_without_agent(ctx):
    """Virtual machines with no guest agent declared.

    Without it the host cannot request a clean shutdown, quiesce the
    filesystem for a snapshot, or report real disk usage.
    """
    configs = _guest_configs(ctx.qemu_configs)
    if not configs:
        return None

    missing = []
    for vmid, text in sorted(configs.items()):
        agent = re.search(r"^agent:\s*(.*)$", text, re.M)
        if not agent or not re.search(r"(?:^|,)(?:enabled=)?1(?:,|$)", agent.group(1)):
            name = ""
            m = re.search(r"^name:\s*(\S+)", text, re.M)
            if m:
                name = m.group(1)
            missing.append({"vmid": vmid, "name": name})

    if not missing:
        return {
            "classification": CLASS_CONFORMANT,
            "summary_key": "allHaveAgent",
            "summary_params": {"total": len(configs)},
        }
    listed = ", ".join(
        f"{v['vmid']}{' (' + v['name'] + ')' if v['name'] else ''}"
        for v in missing
    )
    # The configuration says the agent is declared, never that it
    # answers. Either way its absence describes how the guest is set up.
    for row in missing:
        row["classification"] = CLASS_OBSERVATION
        row["reason_key"] = "agentNotDeclared"
    return {
        "summary_key": "missingAgent",
        "summary_params": {"count": len(missing), "total": len(configs)},
        "affected": missing,
        "evidence": f"without agent: {listed}",
    }


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

@register("security.host_firewall_enabled", AREA_SECURITY, "WARNING")
def _host_firewall(ctx):
    """Effective enable options; this does not prove every traffic path is filtered."""
    def option(path, default):
        text = ctx.read(path, optional=True)
        section = ""
        value = default
        for line in text.splitlines():
            if line.strip().startswith("["):
                section = line.strip().upper()
            m = re.match(r"^\s*enable:\s*([01])\s*$", line)
            if section == "[OPTIONS]" and m:
                value = m.group(1) == "1"
        return value
    def has_rules(path):
        # A `[RULES]` heading with something under it. Proxmox ships the
        # node switch on and the datacenter switch off, so the switch
        # alone says nothing about whether anyone wrote a rule.
        text = ctx.read(path, optional=True)
        section, rules = "", 0
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                section = stripped.upper()
            elif section == "[RULES]" and re.match(
                    r"^\|?\s*(IN|OUT|GROUP)\b", stripped, re.I):
                # A rule declares a direction. Anything else under the
                # heading is a stray key, not something being filtered.
                rules += 1
        return rules

    dc_on = option("/etc/pve/firewall/cluster.fw", False)
    node_on = option(f"/etc/pve/nodes/{ctx.node}/host.fw", True)
    written = (has_rules("/etc/pve/firewall/cluster.fw")
               + has_rules(f"/etc/pve/nodes/{ctx.node}/host.fw"))
    evidence = (f"datacenter enable: {dc_on} (default false)\n"
                f"host enable: {node_on} (default true)\n"
                f"rules written: {written}\n"
                "Configuration assessment only; runtime filtering and guest rules are not validated.")
    # These options say the firewall is switched on, not that any rule
    # filters anything, and a firewall elsewhere in the path is a valid
    # design. What is enabled is reported; what it achieves is not
    # something this can demonstrate.
    # A node with its own rules while the datacenter switch is off is
    # not a host without a firewall: it is a host whose rules the
    # administrator believes are applied and are not. That gap is a
    # warning; a firewall simply not turned on is a stated fact unless
    # the site declared it should be on.
    declared = ctx.policy.host_expectation("firewall")
    overridden = bool(written) and node_on and not dc_on
    gravity = (CLASS_CONFORMANT if dc_on and node_on
               else CLASS_WARNING if overridden or declared == audit_policy.REQUIRED
               else CLASS_OBSERVATION)
    return {"classification": gravity,
            "summary_key": "bothEnabled" if dc_on and node_on else "datacenterOff" if not dc_on else "nodeOff",
            "evidence": evidence}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

@register("storage.orphaned_volumes", AREA_STORAGE, "WARNING")
def _orphaned_volumes(ctx):
    """Unreferenced candidates only: never a deletion recommendation."""
    # Include snapshots, pending configuration and unusedN entries. A disk
    # disconnected from the current boot configuration is still owned.
    configs = list(ctx.lxc_configs.values()) + list(ctx.qemu_configs.values())
    if hasattr(ctx, "cluster_configs"):
        configs += list(ctx.cluster_configs.values())
    references = set()
    for text in configs:
        for line in text.splitlines():
            if re.match(r"^(?:rootfs|mp\d+|unused\d+|(?:scsi|sata|ide|virtio)\d+|efidisk\d+|tpmstate\d+|vmstate):", line):
                value = line.split(":", 1)[1].strip()
                references.add(value.split(",", 1)[0])
    shared_types = {"rbd", "cephfs", "nfs", "cifs", "glusterfs", "iscsi", "iscsidirect"}
    candidates = [s for s in ctx.storages if _local_enabled(s, ctx)
                  and s.get("shared", "0") != "1" and s["type"] not in shared_types
                  and set((s.get("content") or "").split(",")) & {"images", "rootdir"}]
    if not candidates:
        return None
    orphans, inspected, failed = [], [], []
    for storage in candidates:
        sid = storage["id"]
        rc, out = ctx.run(["pvesm", "list", sid], timeout=15)
        if rc != 0:
            failed.append(sid)
            continue
        if not re.search(r"^Volid\s", out.strip()):
            failed.append(sid + " (unrecognised inventory)")
            continue
        count, ignored = 0, 0
        for line in out.splitlines()[1:]:
            fields = line.split()
            # pvesm reports Volid, Format, Type, Size and, for guest
            # volumes, VMID. A mixed storage also lists backups, ISOs and
            # templates, which are content this check is not about: they
            # are skipped, not treated as rows it failed to read.
            if len(fields) < 4:
                failed.append(sid + " (unrecognised row)")
                continue
            content = fields[2]
            if content not in ("images", "rootdir"):
                ignored += 1
                continue
            if len(fields) < 5 or not fields[-1].isdigit():
                failed.append(sid + " (guest volume without a VMID)")
                continue
            volume = fields[0]
            count += 1
            # Template bases may be referenced indirectly by linked clones.
            if "/base-" in volume or ":base-" in volume:
                continue
            if volume not in references:
                orphans.append({"volume": volume, "vmid": int(fields[-1]),
                                "storage": sid,
                                "classification": CLASS_OBSERVATION,
                                "reason_key": "noConfigurationReference"})
        inspected.append(f"{sid}: {count} guest volume(s)"
                         + (f", {ignored} other content skipped" if ignored else ""))
    evidence = "\n".join(inspected) + "\nShared/remote storage and template bases excluded. No deletion is proposed."
    if failed:
        evidence += "\nNot verified: " + ", ".join(failed)
    # An unreferenced volume is a candidate for review, never a
    # recommendation to delete: the reference may live somewhere this
    # check cannot see, and the data may still matter.
    if orphans:
        return {"summary_key": "found", "summary_params": {"count": len(orphans)},
                "affected": orphans, "incomplete": bool(failed), "evidence": evidence}
    return {"classification": CLASS_UNVERIFIED if failed else CLASS_CONFORMANT,
            "summary_key": "evaluationFailed" if failed else "none",
            "summary_params": {"count": 0}, "incomplete": bool(failed),
            "evidence": evidence}


# ---------------------------------------------------------------------------
# Lynis
# ---------------------------------------------------------------------------

# A Lynis report describes the system as it was when the audit ran. Past
# this many days it is treated as no longer representative.


def _lynis_entry(raw: str) -> dict:
    """Split a Lynis record into its test identifier and message.

    Records are pipe-separated and begin with the test id, which is kept
    so a finding can be traced back to the Lynis test that produced it.
    """
    if isinstance(raw, dict):
        return {"test": raw.get("test_id", ""), "message": raw.get("description", ""),
                "details": raw.get("details", "")}
    parts = raw.split("|")
    return {
        "test": parts[0].strip() if parts else "",
        "message": parts[1].strip() if len(parts) > 1 else "",
    }


@register("security.lynis_warnings", AREA_SECURITY, "WARNING",
          budget=LYNIS_RUN_BUDGET)
def _lynis_warnings(ctx):
    """Warnings recorded by the most recent Lynis audit.

    Suggestions are not reported here. Lynis emits them by the dozen and
    they describe optional hardening rather than a defect, so folding them
    in would bury the warnings among them.
    """
    report = ctx.lynis_report
    if report is None:
        return None
    if not report["complete"]:
        # Say which of the two happened: an audit this assessment ran and
        # that did not finish, or a stored report left behind by one.
        detail = (report.get("run_error")
                  or ("this assessment ran an audit and it wrote no hardening "
                      "index, which a finished audit always writes"
                      if report.get("produced_here")
                      else "the stored report has no hardening index, which a "
                           "finished audit always writes"))
        return {
            "classification": CLASS_UNVERIFIED,
            "summary_key": "incomplete",
            "incomplete": True,
            "evidence": f"Lynis report unusable: {detail}.",
        }

    warnings = [_lynis_entry(w) for w in report["warnings"]]
    index = report["hardening_index"]

    # How old the report is describes the report, not the host — which
    # is why it is a row here rather than a check of its own. It belongs
    # beside the warnings it qualifies: reading "no warnings" without
    # knowing the audit ran in June is reading the wrong thing.
    stamp, age_days = report.get("mtime"), None
    if (report.get("complete") and not isinstance(stamp, bool)
            and isinstance(stamp, (int, float)) and math.isfinite(stamp)
            and 0 < stamp <= time.time() + 300):
        age_days = max(0, int((time.time() - stamp) / 86400))
    stale = (age_days is not None
             and age_days >= ctx.policy.threshold("lynis_report_days"))

    evidence = (f"Lynis version: {report.get('version', 'unknown')}\n"
                f"report written: "
                + (time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))
                   if age_days is not None else "not determined")
                + (f" ({age_days} day(s) ago)\n" if age_days is not None else "\n")
                + f"source collected at: {report.get('mtime')}\n"
                f"lynis hardening index: {index}\n"
                f"warnings: {len(warnings)}\n"
                f"suggestions: {len(report['suggestions'])}")

    aged = [{"name": "lynis", "days": age_days,
             "classification": CLASS_OBSERVATION,
             "reason_key": "lynisReportStale"}] if stale else []
    if not warnings:
        if aged:
            return {"summary_key": "noneStale",
                    "summary_params": {"days": str(age_days)},
                    "affected": aged, "evidence": evidence}
        return {
            "classification": CLASS_CONFORMANT,
            "summary_key": "none",
            "evidence": evidence,
        }
    # Lynis is a source, not a verdict. Its warnings are worth reading
    # and vary in how much they apply to a Proxmox host, so they are
    # reported as observations rather than folded into this host's
    # problem count; SSH, the firewall and certificates have checks of
    # their own here and are not double-counted through Lynis.
    for row in warnings:
        row["classification"] = CLASS_OBSERVATION
        row["reason_key"] = "lynisWarning"
    return {
        "summary_key": "foundStale" if stale else "found",
        "summary_params": {"count": len(warnings), "days": str(age_days)},
        "affected": warnings + aged,
        "evidence": evidence + "\n\n" + "\n".join(
            f"{w['test']}: {w['message']}" for w in warnings),
    }


# ---------------------------------------------------------------------------
# Memory, ZFS, certificates and time
# ---------------------------------------------------------------------------

# Allocating more memory than the host owns is a deliberate technique when
# guests do not peak together. This is the ratio past which the margin is
# reported rather than assumed.

# Certificate lifetimes are reported before they lapse, not once they have.


def _host_memory_bytes(ctx) -> int:
    for line in (ctx.run(["cat", "/proc/meminfo"])[1] or "").splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024
    return 0


@register("system.memory_overcommit", AREA_SYSTEM, "WARNING")
def _memory_overcommit(ctx):
    """Memory assigned to guests compared with the host's physical memory.

    Each guest contributes the ``memory`` value from its configuration,
    which is its ceiling. Containers consume what they need up to that
    limit while virtual machines without ballooning reserve it, so the
    two are reported separately.
    """
    total = _host_memory_bytes(ctx)
    if not total:
        return None

    def assigned(configs):
        out = 0
        for text in configs.values():
            m = re.search(r"^memory:\s*(\d+)", text, re.M)
            if m:
                out += int(m.group(1)) * 1024 * 1024
        return out

    lxc = assigned(_guest_configs(ctx.lxc_configs))
    qemu = assigned(_guest_configs(ctx.qemu_configs))
    if not (lxc or qemu):
        return None

    gib = 1024 ** 3
    ratio = (lxc + qemu) / total
    evidence = (f"host memory: {total / gib:.1f} GiB\n"
                f"assigned to virtual machines: {qemu / gib:.1f} GiB\n"
                f"assigned to containers: {lxc / gib:.1f} GiB\n"
                f"ratio: {ratio * 100:.0f}%\n"
                "Configured maximums include stopped guests; this is not measured RAM use.\n")
    meminfo = ctx.run(["cat", "/proc/meminfo"])[1]
    evidence += "\n".join(l for l in meminfo.splitlines() if l.startswith(("MemAvailable:", "SwapTotal:", "SwapFree:")))
    rc, resource_text = ctx.run(["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"])
    if rc == 0:
        resources = json.loads(resource_text)
        active = {int(r["vmid"]) for r in resources if r.get("node") == ctx.node and r.get("status") == "running"}
        active_bytes = assigned({v: t for v, t in _guest_configs(ctx.lxc_configs).items() if v in active})
        active_bytes += assigned({v: t for v, t in _guest_configs(ctx.qemu_configs).items() if v in active})
        evidence += f"\nRunning guests configured maximum: {active_bytes / gib:.1f} GiB"
    params = {"percent": round(ratio * 100)}

    # Assigning more than the host owns is a technique, not a fault:
    # guests rarely peak together and containers take what they use. The
    # ratio is reported as planning information; sustained pressure is a
    # different measurement, and the health monitor makes it.
    if ratio <= ctx.policy.threshold("memory_overcommit_ratio"):
        return {"classification": CLASS_CONFORMANT, "summary_key": "withinRatio",
                "summary_params": params, "evidence": evidence}
    return {"classification": CLASS_OBSERVATION, "summary_key": "aboveRatio",
            "summary_params": params, "evidence": evidence}


@register("storage.zfs_arc_max", AREA_STORAGE, "WARNING")
def _zfs_arc_max(ctx):
    """Effective ARC bounds, not assumptions about a version's defaults."""
    if not Path("/sys/module/zfs").exists():
        return None
    text = ctx.read("/proc/spl/kstat/zfs/arcstats")
    stats = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] in {"c_min", "c_max", "size"} and fields[-1].isdigit():
            stats[fields[0]] = int(fields[-1])
    total = _host_memory_bytes(ctx)
    if not total or not all(k in stats for k in ("c_min", "c_max", "size")):
        return {"classification": CLASS_UNVERIFIED, "summary_key": "evaluationFailed", "evidence": text}
    settings = {}
    for path in sorted(Path("/etc/modprobe.d").glob("*.conf")):
        lines = [l for l in ctx.read(path).splitlines()
                 if re.match(r"^\s*options\s+zfs\s", l) and re.search(r"zfs_arc_(?:min|max)=", l)]
        if lines:
            settings[str(path)] = lines
    parameter = ctx.read("/sys/module/zfs/parameters/zfs_arc_max").strip()
    declared = set(re.findall(
        r"zfs_arc_max=(\d+)",
        "\n".join(l for rows in settings.values() for l in rows)))
    share = stats["c_max"] / total
    loaded = int(parameter) if parameter.isdigit() else None

    findings = []
    # Two files disagreeing about the same parameter is a configuration
    # that cannot all be true.
    if len(declared) > 1:
        findings.append({"setting": "zfs_arc_max", "values": sorted(declared),
                         "classification": CLASS_WARNING,
                         "reason_key": "arcConflictingSettings"})
    if stats["c_min"] > stats["c_max"]:
        findings.append({"setting": "arc bounds", "classification": CLASS_WARNING,
                         "reason_key": "arcMinAboveMax"})
    # A persistent value the running module does not carry is a change
    # waiting for the next boot, which is worth stating and is not a
    # fault: the reader may have just made it.
    if declared and loaded is not None:
        only = next(iter(declared)) if len(declared) == 1 else None
        if only is not None and int(only) != loaded:
            findings.append({"setting": "zfs_arc_max",
                             "configured": int(only), "loaded": loaded,
                             "classification": CLASS_OBSERVATION,
                             "reason_key": "arcPendingReboot"})

    evidence = json.dumps({"arc_bytes": stats, "host_bytes": total,
                           "module_parameter": parameter,
                           "persistent_settings": settings,
                           "c_max_share_percent": round(share * 100, 1)}, indent=2)
    evidence += ("\nA module parameter of 0 selects the default; c_max is the "
                 "effective limit. ARC is a ceiling, not a reservation: the "
                 "memory is reclaimable, so a high limit is not evidence of "
                 "memory pressure.")
    if not findings:
        return {"classification": CLASS_CONFORMANT, "summary_key": "bounded",
                "summary_params": {"percent": round(share * 100)},
                "evidence": evidence}
    return {"summary_key": "conflicting" if any(
                f["classification"] == CLASS_WARNING for f in findings) else "pending",
            "summary_params": {"percent": round(share * 100),
                               "count": len(findings)},
            "affected": findings, "evidence": evidence}


@register("security.certificate_expiry", AREA_SECURITY, "WARNING")
def _certificate_expiry(ctx):
    """Remaining validity of the certificate served by pveproxy.

    The custom certificate takes precedence when present; otherwise the
    one Proxmox generates is examined.
    """
    for name in ("pveproxy-ssl.pem", "pve-ssl.pem"):
        path = Path("/etc/pve/local") / name
        if path.exists():
            break
    else:
        return None

    rc, out = ctx.run(["openssl", "x509", "-enddate", "-noout", "-in", str(path)])
    if rc != 0 or "notAfter=" not in (out or ""):
        return None
    raw = out.split("notAfter=", 1)[1].strip().splitlines()[0]

    rc2, epoch_out = ctx.run(["date", "-d", raw, "+%s"])
    if rc2 != 0 or not epoch_out.strip().lstrip("-").isdigit():
        return None
    remaining = int(epoch_out.strip()) - time.time()
    days = math.floor(remaining / 86400)

    evidence = f"certificate: {path}\nexpires: {raw}\nremaining: {days} day(s)"
    params = {"days": days}
    if remaining <= 0:
        return {"classification": CLASS_WARNING, "summary_key": "expired",
                "summary_params": {"days": abs(days)}, "evidence": evidence}
    if days < ctx.policy.threshold("certificate_expiry_days"):
        return {"classification": CLASS_OBSERVATION, "summary_key": "expiring",
                "summary_params": params, "evidence": evidence}
    return {"classification": CLASS_CONFORMANT, "summary_key": "valid",
            "summary_params": params, "evidence": evidence}


@register("system.time_synchronisation", AREA_SYSTEM, "WARNING")
def _time_sync(ctx):
    """Whether the host clock is disciplined by a time source.

    Proxmox relies on agreeing clocks for cluster membership, certificate
    validation and the ordering of log entries.
    """
    rc, out = ctx.run(["timedatectl", "show",
                       "-p", "NTP", "-p", "NTPSynchronized"])
    if rc != 0:
        return _unverified(out)
    values = {}
    for line in (out or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()

    if any(values.get(k) not in ("yes", "no") for k in ("NTP", "NTPSynchronized")):
        return _unverified(out or "NTP state missing")

    enabled = values.get("NTP") == "yes"
    synced = values.get("NTPSynchronized") == "yes"
    clustered = Path("/etc/corosync/corosync.conf").exists()
    evidence = (f"NTP: {values.get('NTP', 'unknown')}\n"
                f"NTPSynchronized: {values.get('NTPSynchronized', 'unknown')}\n"
                f"node belongs to a cluster: {'yes' if clustered else 'no'}")

    if enabled and synced:
        return {"classification": CLASS_CONFORMANT, "summary_key": "synchronised",
                "evidence": evidence}
    if not enabled:
        # Another mechanism may be disciplining the clock, so this
        # states what timedatectl reports rather than concluding the
        # clock is wrong.
        return {"classification": CLASS_OBSERVATION, "summary_key": "disabled",
                "evidence": evidence}
    # Synchronisation enabled and not achieved is a drift that will keep
    # growing, and cluster membership and backup timestamps depend on it.
    return {"classification": CLASS_WARNING, "summary_key": "notSynchronised",
            "evidence": evidence}


@register("guests.autostart", AREA_GUESTS, "INFO")
def _autostart(ctx):
    """Guests that do not start with the host.

    A guest without ``onboot: 1`` stays down after a host restart until
    someone starts it.
    """
    guests = {}
    for vmid, text in _guest_configs(ctx.lxc_configs).items():
        guests[vmid] = ("lxc", text)
    for vmid, text in _guest_configs(ctx.qemu_configs).items():
        guests[vmid] = ("qemu", text)
    if not guests:
        return None

    ha = ctx.read("/etc/pve/ha/resources.cfg", optional=True)
    ha_guests = {int(v) for v in re.findall(r"^(?:vm|ct):\s*(\d+)", ha, re.M)}
    missing = []
    for vmid, (kind, text) in sorted(guests.items()):
        if vmid in ha_guests:
            continue
        if not re.search(r"^onboot:\s*1\s*$", text, re.M):
            name = ""
            m = re.search(r"^(?:hostname|name):\s*(\S+)", text, re.M)
            if m:
                name = m.group(1)
            missing.append({"vmid": vmid, "name": name, "type": kind})

    # A machine that is meant to come back by itself and does not is a
    # missing protection; one nobody said that about is a configuration.
    policy = ctx.policy
    for row in missing:
        expected = policy.autostart_required(row["vmid"])
        row["classification"] = (CLASS_WARNING if expected == audit_policy.REQUIRED
                                 else CLASS_OBSERVATION)
        row["reason_key"] = ("expectedToAutostart" if expected == audit_policy.REQUIRED
                             else "noAutostart")
    missing = [row for row in missing
               if policy.autostart_required(row["vmid"]) != audit_policy.NOT_REQUIRED]
    if not missing:
        return {"classification": CLASS_CONFORMANT, "summary_key": "allAutostart",
                "summary_params": {"total": len(guests)}}
    return {
        "summary_key": "notAutostart",
        "summary_params": {"count": len(missing), "total": len(guests)},
        "affected": missing,
        "evidence": "without onboot: " + ", ".join(
            f"{g['vmid']}{' (' + g['name'] + ')' if g['name'] else ''}"
            for g in missing),
    }


# ---------------------------------------------------------------------------
# Kernel and disk service life
# ---------------------------------------------------------------------------

# Typical service life used to separate disks that are within their
# expected working period from those that have outlived it.


def _version_key(value: str) -> list:
    """Sort key for a kernel version, comparing numeric parts as numbers."""
    return [int(p) if p.isdigit() else p
            for p in re.split(r"[.\-]", value) if p]


@register("system.kernel_current", AREA_SYSTEM, "WARNING")
def _kernel_current(ctx):
    """Which kernel is running, and which one the host would boot.

    Whether a newer kernel is waiting is reported by the pending-restart
    check, which reads that together with the packages asking for one.
    What this adds is the comparison the other cannot make: the kernel
    running now against the kernel the host has selected for its next
    boot. Those differing after a reboot is a boot that did not take, and
    that is worth knowing; a newer kernel merely installed is not, since
    it may be held on purpose.
    """
    rc, running = ctx.run(["uname", "-r"])
    running = running.strip()
    if rc != 0 or not running:
        return None

    # What the boot loader would start next. Where it cannot be read the
    # check says so rather than falling back to the package list, which
    # answers a different question.
    rc2, out = ctx.run(["proxmox-boot-tool", "kernel", "list"],
                       timeout=15, allowed_codes=(0, 1, 127))
    if rc2 != 0:
        # A host that does not use proxmox-boot-tool selects its kernel
        # elsewhere; there is nothing here to compare.
        return None

    # Retained kernel lists are not boot selection. Only a declared pin
    # identifies the intended kernel; a next-boot pin takes precedence.
    manual, automatic, pinned, next_boot, section = [], [], [], [], ""
    for line in (out or "").splitlines():
        lowered = line.strip().lower()
        if lowered.startswith("manually selected"):
            section = "manual"
            continue
        if lowered.startswith("automatically selected"):
            section = "automatic"
            continue
        if lowered.startswith("pinned kernel:"):
            section = "pinned"
            continue
        if lowered.startswith("kernel pinned on next-boot:"):
            section = "next_boot"
            continue
        m = re.match(r"^\s*(\d[\w.\-]+)\s*$", line)
        if m:
            {"manual": manual, "automatic": automatic, "pinned": pinned,
             "next_boot": next_boot}.get(section, []).append(m.group(1))
    candidates = next_boot or pinned
    origin = "pinned for next boot" if next_boot else "pinned" if pinned else ""
    selected = candidates[0] if len(candidates) == 1 else None
    if selected is None:
        # No pin is not an unknown: proxmox-boot-tool boots the newest of
        # the kernels it keeps. Reading that is the whole point of the
        # check, and calling it undetermined left every unpinned host —
        # which is most of them — with a finding nobody could act on.
        retained = manual + automatic
        if retained:
            selected = max(retained, key=_version_key)
            origin = "newest kernel retained, no pin declared"

    evidence = (f"running: {running}\nnext boot: {selected or 'not determined'}"
                f"{f' ({origin})' if origin else ''}\n"
                f"manually selected: {', '.join(manual) or 'none'}\n"
                f"automatically selected: {', '.join(automatic) or 'none'}\n"
                "Next boot is what the boot tool reports it would start; "
                "the boot loader's installation on each disk is not verified.")
    if selected is None:
        return {"classification": CLASS_UNVERIFIED, "summary_key": "bootTargetUnknown",
                "summary_params": {"version": running}, "evidence": evidence}
    if _version_key(selected) == _version_key(running):
        return {"classification": CLASS_CONFORMANT, "summary_key": "current",
                "summary_params": {"version": running}, "evidence": evidence}
    if _version_key(selected) < _version_key(running):
        # Running something newer than the host would boot means a fall
        # back to an older kernel is queued for the next restart.
        return {"classification": CLASS_WARNING, "summary_key": "wouldDowngrade",
                "summary_params": {"running": running, "selected": selected},
                "evidence": evidence}
    return {"classification": CLASS_OBSERVATION, "summary_key": "newerSelected",
            "summary_params": {"running": running, "selected": selected},
            "evidence": evidence}


@register("hardware.disk_service_life", AREA_HARDWARE, "INFO")
def _disk_service_life(ctx):
    """Planning information from the Monitor's SMART readings."""
    cached = ctx.monitor_snapshot.get("smart", {})
    service_life_hours = ctx.policy.threshold("disk_service_life_hours")
    aged, readings, skipped = [], [], []
    for dev, entry in sorted(cached.items()):
        collected_at, data = entry if isinstance(entry, (list, tuple)) else (None, entry)
        hours = data.get("power_on_hours")
        if data.get("smart_status") == "unknown" or not isinstance(hours, (int, float)) \
                or hours <= 0:
            skipped.append(dev)
            continue
        row = {"device": dev, "hours": hours, "collected_at": collected_at,
               "percentage_used": data.get("percentage_used"),
               "ssd_life_left": data.get("ssd_life_left"),
               "health": data.get("health")}
        readings.append(row)
        if hours >= service_life_hours:
            aged.append({"device": dev, "hours": hours})

    evidence = json.dumps(readings, indent=2) + \
        "\nAge is planning information, not a failure or replacement criterion."
    if skipped:
        evidence += "\nDisks reporting no usable SMART data: " + ", ".join(skipped)

    # A disk that exposes no SMART counters — a USB enclosure, a device
    # behind a RAID controller — is outside what this check can read, not
    # a gap in the evaluation of the disks that did answer.
    if not readings:
        return {"classification": CLASS_UNVERIFIED, "summary_key": "noReadings",
                "summary_params": {"skipped": len(skipped)},
                "incomplete": True, "evidence": evidence}

    # Age is planning information. A disk does not become defective at a
    # birthday; media errors and device warnings are what demonstrate a
    # defect, and the health monitor reports those.
    for row in aged:
        row["classification"] = CLASS_OBSERVATION
        row["reason_key"] = "pastServiceLife"
    return {"classification": CLASS_OBSERVATION if aged else CLASS_CONFORMANT,
            "summary_key": "pastLife" if aged else "withinLife",
            "summary_params": {"count": len(aged), "total": len(readings),
                               "skipped": len(skipped)},
            "affected": aged, "observations": readings,
            "evidence": evidence}


# ---------------------------------------------------------------------------
# Backup results
# ---------------------------------------------------------------------------

def _backup_storages(ctx) -> list[dict]:
    return [s for s in ctx.storages if "backup" in (s.get("content") or "").split(",")
            and _local_enabled(s, ctx)]


def _volid_timestamp(volid: str):
    """Epoch of a backup volume, read from its identifier.

    Proxmox Backup Server snapshots end in an ISO instant; vzdump archives
    carry the date in the file name.
    """
    m = re.search(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})Z", volid)
    if m:
        try:
            return calendar.timegm(time.strptime(
                f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}Z",
                "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            return None
    m = re.search(r"(\d{4})_(\d{2})_(\d{2})-(\d{2})_(\d{2})_(\d{2})", volid)
    if m:
        try:
            return time.mktime(time.strptime("-".join(m.groups()),
                                             "%Y-%m-%d-%H-%M-%S"))
        except ValueError:
            return None
    return None


@register("storage.connected_storage", AREA_STORAGE, "CRITICAL")
def _destination_reachable(ctx):
    """All configured storage, using PVE's observations, not remote IO probes."""
    configured = ctx.storages
    storages = [s for s in configured if _local_enabled(s, ctx)]
    if not storages:
        return None
    snapshot = ctx.storage_snapshot
    resources = {r.get("name"): r for r in snapshot.get("rows", [])
                 if r.get("node") == ctx.node}
    jobs = [j for j in _parse_vzdump_jobs(ctx.vzdump_jobs) if _local_enabled(j, ctx)]
    policy = ctx.policy
    usage_limit = policy.threshold("storage_usage_percent")
    dependencies = {s["id"]: [] for s in storages}
    running: set[int] = set()
    rc, resource_text = ctx.run(
        ["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"],
        timeout=20)
    if rc == 0:
        try:
            running = {int(r["vmid"]) for r in json.loads(resource_text)
                       if r.get("node") == ctx.node and r.get("status") == "running"}
        except (ValueError, KeyError, TypeError):
            running = set()
    for kind, configs in (("lxc", ctx.lxc_configs), ("qemu", ctx.qemu_configs)):
        for vmid, text in configs.items():
            for line in _current_config(text).splitlines():
                m = re.match(r"^(rootfs|mp\d+|(?:scsi|sata|ide|virtio|efidisk|tpmstate)\d+|unused\d+):\s*([^,]+)", line)
                if m and ":" in m[2]:
                    sid = m[2].split(":", 1)[0]
                    if sid in dependencies:
                        dependencies[sid].append({"vmid": vmid, "type": kind,
                                                  "disk": m[1], "volume": m[2]})
    observations, affected, unknown = [], [], []
    for storage in storages:
        sid = storage["id"]
        resource = resources.get(sid, {})
        status = resource.get("status", "unknown")
        if resource.get("status_detail") == "not_found":
            status = "unknown"  # Missing PVE observation is not a confirmed outage.
        row = {"storage": sid, "type": storage["type"], "status": status,
               "content": storage.get("content", ""), "dependencies": dependencies[sid],
               "jobs": [j["id"] for j in jobs if j.get("storage") == sid],
               "source": snapshot.get("source", "unavailable"),
               "collected_at": snapshot.get("collected_at"),
               "remote_internals": "not checked: disks/RAID, PBS verification/pruning, remote permissions",
               "io_test": "not performed; availability is reported by PVE"}
        # Explicit allowlist: never persist credentials or the raw storage configuration.
        row["configuration"] = {k: storage[k] for k in
                                ("path", "pool", "vgname", "thinpool", "datastore", "namespace", "shared", "nodes")
                                if k in storage}
        reasons = []
        if status in ("error", "unavailable", "inactive", "offline"):
            reasons.append("PVE reports storage unavailable")
        elif status not in ("active", "available", "namespace_restricted"):
            unknown.append(sid)
        try:
            total, used = float(resource["total"]), float(resource["used"])
            if not (0 < total and 0 <= used <= total):
                raise ValueError("capacity unknown")
            percent = used * 100 / total
            row.update(total=total, used=used, units=snapshot.get("units"),
                       used_percent=round(percent, 2), capacity_known=True)
            if percent >= usage_limit:
                reasons.append(f"capacity usage at or above the "
                               f"{usage_limit:g}% review threshold")
        except (KeyError, ValueError, TypeError):
            row["capacity_known"] = False
            # Restricted PBS namespaces and block backends can omit capacity.
            # Unknown capacity is not proof of a full or failed storage.
        if reasons:
            # A storage backing a guest that is running right now cannot
            # be lost without the guest noticing; one holding nothing in
            # use can.
            serves_running = any(dep["vmid"] in running
                                 for dep in dependencies[sid])
            # Being unreachable is what can interrupt something; being
            # full is a margin running out. Capacity is never critical on
            # its own, however essential the storage.
            offline = status in ("error", "unavailable", "inactive", "offline")
            role = policy.storage_role(sid)
            if not offline:
                gravity = CLASS_WARNING
            elif role == audit_policy.ROLE_OPTIONAL:
                gravity = CLASS_OBSERVATION
            elif role == audit_policy.ROLE_ESSENTIAL or serves_running:
                gravity = CLASS_CRITICAL
            else:
                gravity = CLASS_WARNING
            affected.append({"storage": sid, "type": storage["type"],
                             "classification": gravity, "status": status,
                             "role": role,
                             "reason_key": ("storageUnreachable" if offline
                                            else "storageNearlyFull"),
                             "reason": "; ".join(reasons)})
        observations.append(row)
    evidence_payload = {"storages": observations}
    if unknown:
        evidence_payload["status_not_verified"] = unknown
    excluded = [s["id"] for s in configured if not _local_enabled(s, ctx)]
    if excluded:
        evidence_payload["excluded_disabled_or_other_node"] = excluded
    evidence_payload["scope"] = (
        "PVE-side observations only; shared volumes are not classified as orphans here")
    if not affected:
        return {"classification": CLASS_UNVERIFIED if unknown else CLASS_CONFORMANT,
                "summary_key": "evaluationFailed" if unknown else "available",
                "summary_params": {"count": 0, "total": len(storages)},
                "observations": observations, "incomplete": bool(unknown),
                "evidence": json.dumps(evidence_payload, indent=2)}
    return {"summary_key": "attention",
            "summary_params": {"count": len(affected), "total": len(storages)},
            "affected": affected, "observations": observations, "incomplete": bool(unknown),
            "evidence": json.dumps(evidence_payload, indent=2)}


@register("backup.last_backup_age", AREA_BACKUP, "WARNING")
def _last_backup_age(ctx):
    """Stored backups for every non-template guest, including missing copies."""
    guests = set(_guest_configs(ctx.lxc_configs)) | set(_guest_configs(ctx.qemu_configs))
    if not guests:
        return None
    policy = ctx.policy
    guests = {v for v in guests if policy.backup_required(v) != audit_policy.NOT_REQUIRED}
    if not guests:
        return None
    storages = _backup_storages(ctx)
    newest, failed = {}, []
    unreadable = set()
    unattributed = []
    for storage in storages:
        rc, out = ctx.run(["pvesm", "list", storage["id"]], timeout=25)
        if rc != 0:
            failed.append(storage["id"])
            unreadable.add(storage["id"])
            continue
        if not re.search(r"^Volid\s", out.strip()):
            failed.append(storage["id"] + " (unrecognised inventory)")
            unreadable.add(storage["id"])
            continue
        for line in out.splitlines()[1:]:
            fields = line.split()
            # Mixed storage may also list ISOs/templates without a VMID.
            if len(fields) >= 4 and fields[2] != "backup":
                continue
            if len(fields) == 4 and fields[2] == "backup":
                match = re.search(r"(?:^|/)vzdump-(?:qemu|lxc)-(\d+)-", fields[0])
                if match:
                    fields.append(match[1])
                else:
                    # e.g. host configuration archives: never count as a guest copy.
                    unattributed.append({"storage": storage["id"], "volume": fields[0]})
                    continue
            if len(fields) != 5 or not fields[-1].isdigit():
                failed.append(storage["id"] + " (unrecognised row)")
                unreadable.add(storage["id"])
                continue
            vmid = int(fields[-1])
            if vmid not in guests:
                continue
            when = _volid_timestamp(fields[0])
            key = (vmid, storage["id"])
            if when is None:
                failed.append(storage["id"] + " (unrecognised backup date)")
                unreadable.add(storage["id"])
            elif key not in newest or when > newest[key][0]:
                newest[key] = (when, storage["id"], fields[0])
    pools = _pool_members(ctx.pve_user_cfg)
    jobs = [j for j in _parse_vzdump_jobs(ctx.vzdump_jobs) if _local_enabled(j, ctx)]
    stale, missing, observations = [], [], []
    now = time.time()
    expectations = []
    for vmid in sorted(guests):
        selected = [j for j in jobs if vmid in _job_guests(j, guests, pools)]
        # Evaluate each explicitly scheduled destination independently. A current
        # copy in PBS A must not mask a missing or old copy in PBS B.
        targets = sorted({j.get("storage", "") for j in selected}) or [""]
        expectations.extend((vmid, target, [j for j in selected if j.get("storage", "") == target])
                            for target in targets)
    available_ids = {s["id"] for s in storages}
    for vmid, target, selected in expectations:
        grace = policy.threshold("backup_schedule_grace_ratio")
        limits = [_schedule_age_limit(j.get("schedule", ""), grace) for j in selected]
        known_limits = [n for n in limits if n is not None]
        # What bounds the age of a guest's newest copy, in order of how
        # much it is worth: a recovery objective somebody declared, then
        # the schedule its jobs actually run on, and only then a stated
        # fallback that stands in for a policy nobody has expressed.
        declared = policy.recovery_objective_hours(vmid)
        if declared:
            limit, basis = declared * 3600, "declared recovery objective"
        elif known_limits:
            limit, basis = min(known_limits), "schedule and grace"
        else:
            limit = policy.threshold("backup_fallback_days") * 86400
            basis = "fallback; no recovery objective declared and schedule not read"
        row = {"vmid": vmid, "expected_storage": target or "any visible destination (no explicit target)",
               "jobs": [j["id"] for j in selected],
               "schedules": [j.get("schedule", "unknown") for j in selected],
               "max_age_hours": round(limit / 3600, 1),
               "age_policy": basis,
               "verification": "not queried; existence is not a restore test"}
        candidates = [value for (guest, sid), value in newest.items()
                      if guest == vmid and (not target or sid == target)]
        latest = max(candidates, key=lambda value: value[0]) if candidates else None
        uncertain = target in unreadable if target else bool(unreadable)
        if target and target not in available_ids:
            row["backup"] = "scheduled destination disabled, missing or outside this node"
            missing.append({"vmid": vmid, "storage": target,
                            "classification": CLASS_WARNING,
                            "reason_key": "destinationUnavailable"})
            observations.append(row)
            continue
        if selected and not target:
            failed.append(f"{vmid}: job destination not explicitly resolved")
        if latest is None:
            row["backup"] = "unknown: destination unreadable" if uncertain else "none found"
            if not uncertain:
                # An expected copy that is not there is a missing
                # protection; where nothing was expected of the guest it
                # is the absence of a schedule, already reported by
                # coverage, and here it is only an observation.
                expected = policy.backup_required(vmid)
                missing.append({
                    "vmid": vmid, "storage": target or "any",
                    "classification": (CLASS_WARNING
                                       if selected or expected == audit_policy.REQUIRED
                                       else CLASS_OBSERVATION),
                    "reason_key": ("noStoredBackup" if selected
                                   else "noStoredBackupUnscheduled"),
                })
        else:
            when, storage, volume = latest
            row.update(last_backup=int(when), storage=storage, volume=volume,
                       age_hours=round((now - when) / 3600, 1))
            if when > now + 300:
                failed.append(f"{vmid}: backup timestamp is in the future")
            elif now - when > limit and not uncertain:
                stale.append({"vmid": vmid, "days": int((now - when) / 86400),
                              "storage": storage, "classification": (
                                  CLASS_WARNING if declared or known_limits or policy.backup_required(vmid) == audit_policy.REQUIRED
                                  else CLASS_OBSERVATION),
                              "reason_key": ("olderThanObjective" if declared
                                             else "olderThanSchedule" if known_limits
                                             else "olderThanFallback")})
        observations.append(row)
    evidence = json.dumps(observations, indent=2)
    if unattributed:
        evidence += "\nArchives without guest attribution (not counted): " + json.dumps(unattributed)
    if failed:
        evidence += "\nNot verified: " + ", ".join(sorted(set(failed)))
    affected = missing + stale
    if not affected:
        return {"classification": CLASS_UNVERIFIED if failed else CLASS_CONFORMANT,
                "summary_key": "evaluationFailed" if failed else "recent",
                "summary_params": {"count": 0, "total": len(expectations)},
                "observations": observations, "incomplete": bool(failed),
                "evidence": evidence}
    warnings = sum(1 for a in affected if a["classification"] == CLASS_WARNING)
    return {"summary_key": "attention",
            "summary_params": {"count": len(affected), "total": len(expectations),
                               "warnings": warnings},
            "affected": affected, "observations": observations,
            "incomplete": bool(failed), "evidence": evidence}


_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

_SHORTHAND = {"hourly": 3600, "daily": 86400, "weekly": 7 * 86400,
              "monthly": 31 * 86400, "yearly": 366 * 86400,
              "annually": 366 * 86400, "quarterly": 92 * 86400,
              "semiannually": 184 * 86400, "minutely": 60}


def _weekday_set(spec: str):
    """Days named by a Proxmox schedule, as indexes.

    Accepts the forms Proxmox writes: ``mon``, ``mon,wed``, ``mon..fri``
    and combinations of the two. Returns None when the text is not a day
    specification at all, so the caller can tell "no days named" from
    "days that could not be read".
    """
    days: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ".." in part:
            first, _, last = part.partition("..")
            if first not in _WEEKDAYS or last not in _WEEKDAYS:
                return None
            start, end = _WEEKDAYS[first], _WEEKDAYS[last]
            # A range may wrap around the end of the week.
            index = start
            while True:
                days.add(index)
                if index == end:
                    break
                index = (index + 1) % 7
        elif part in _WEEKDAYS:
            days.add(_WEEKDAYS[part])
        else:
            return None
    return days or None


def _longest_gap(days: set[int], times: list[str]) -> float:
    """Seconds between consecutive runs, at their widest.

    A job that runs on Monday and Friday has a three-day gap and a
    four-day gap; what bounds the age of the newest backup is the wider
    of the two.
    """
    offsets = set()
    for clock in times:
        parts = [int(p) for p in clock.split(":")]
        seconds = parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0)
        offsets.update(day * 86400 + seconds for day in days)
    ordered = sorted(offsets)
    week = 7 * 86400
    return float(max((ordered[(i + 1) % len(ordered)] - value) % week or week
                     for i, value in enumerate(ordered)))


def _schedule_interval(schedule: str):
    """How often a Proxmox calendar event fires, in seconds.

    Reads the calendar forms Proxmox actually writes — ``sun 07:00``,
    ``mon..fri 05:30``, ``*-*-* 03:00``, ``mon,wed 01:00``, ``daily`` —
    rather than recognising a handful of keywords and treating everything
    else as unknown. Anything genuinely unreadable still returns None, so
    an interval is never invented.
    """
    text = (schedule or "").strip().lower()
    if not text:
        return None
    if text in _SHORTHAND:
        return float(_SHORTHAND[text])

    # A repeat specification (``*-*-* 03:00/6``) is left unread rather
    # than approximated.
    body = text
    if body.startswith("*-*-*"):
        body = body[5:].strip()
    elif re.match(r"^\*-\*-\*\s", body):
        body = body.split(None, 1)[1]

    def clock_values(token: str):
        # A time token may itself be a list: "01:00,13:00".
        values = [v for v in token.split(",") if v]
        if not values or not all(
                re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", v) for v in values):
            return None
        for value in values:
            hour, minute = value.split(":")[:2]
            if int(hour) > 23 or int(minute) > 59 or (len(value.split(":")) == 3 and int(value.split(":")[2]) > 59):
                return None
        return values

    parts = body.split()
    times: list[str] = []
    day_spec: list[str] = []
    for token in parts:
        values = clock_values(token)
        if values is None:
            day_spec.append(token)
        else:
            times.extend(values)
    if not times:
        return None

    if not day_spec:
        # Times only: every day at those times.
        return _longest_gap(set(range(7)), times)
    if len(day_spec) > 1:
        return None
    days = _weekday_set(day_spec[0])
    if days is None:
        return None
    return _longest_gap(days, times)


def _schedule_age_limit(schedule, grace_ratio: float = 0.5):
    """How old the newest backup may be before the schedule was missed.

    The limit is one full interval plus a margin, so a job that has just
    run and one that ran a little late are both within it. A schedule
    that could not be read yields None, and the caller falls back to a
    stated policy rather than to an invented one.
    """
    interval = _schedule_interval(schedule)
    if interval is None:
        return None
    return interval + max(3600.0, interval * grace_ratio)


# ---------------------------------------------------------------------------
# Snapshots, pools, SSH and bonds
# ---------------------------------------------------------------------------

# ZFS ships a monthly scrub schedule; this allows one full period plus
# margin before the last scrub is reported as overdue.


def _snapshot_sections(text: str) -> list[tuple[str, str]]:
    """Return each snapshot section of a guest configuration.

    A configuration keeps its live settings first and then one ``[name]``
    section per snapshot.
    """
    out = []
    name = None
    body: list[str] = []
    for line in text.splitlines():
        header = re.match(r"^\[([^\]]+)\]", line)
        if header:
            if name is not None:
                out.append((name, "\n".join(body)))
            name, body = header.group(1), []
            continue
        if name is not None:
            body.append(line)
    if name is not None:
        out.append((name, "\n".join(body)))
    return out


@register("guests.stuck_snapshots", AREA_GUESTS, "WARNING")
def _stuck_snapshots(ctx):
    """Snapshots left mid-operation.

    ``snapstate`` is written while a snapshot is being created or removed
    and cleared when the operation finishes. A section that still carries
    it was interrupted: the snapshot occupies space and further snapshot
    operations on that guest are refused until it is resolved.
    """
    configs = {}
    configs.update({v: ("lxc", t) for v, t in ctx.lxc_configs.items()})
    configs.update({v: ("qemu", t) for v, t in ctx.qemu_configs.items()})
    if not configs:
        return None

    stuck, total = [], 0
    for vmid, (kind, text) in sorted(configs.items()):
        for name, body in _snapshot_sections(text):
            total += 1
            m = re.search(r"^snapstate:\s*(\S+)", body, re.M)
            if m:
                stuck.append({"vmid": vmid, "snapshot": name,
                              "state": m.group(1), "type": kind})

    if total == 0:
        return {"classification": CLASS_CONFORMANT, "summary_key": "noSnapshots"}
    evidence = f"snapshots found: {total}"
    if stuck:
        evidence += "\n\nleft mid-operation:\n  " + "\n  ".join(
            f"{s['vmid']} [{s['snapshot']}] snapstate={s['state']}" for s in stuck)
    if not stuck:
        return {"classification": CLASS_CONFORMANT, "summary_key": "allComplete",
                "summary_params": {"total": total}, "evidence": evidence}
    rc, active_text = ctx.run(["pvesh", "get", f"/nodes/{ctx.node}/tasks",
                               "--source", "active", "--output-format", "json"])
    if rc != 0:
        return {"classification": CLASS_UNVERIFIED, "summary_key": "evaluationFailed",
                "incomplete": True, "evidence": evidence}
    active = json.loads(active_text)
    # Only a task that could be holding the snapshot suspends the
    # finding. Any running task for the same guest used to do it, so a
    # long console session or a migration hid a snapshot that really was
    # stuck — the one case this check exists to catch.
    RELATED = ("vzdump", "qmsnapshot", "vzsnapshot", "qmdelsnapshot",
               "vzdelsnapshot", "qmrollback", "vzrollback", "qmmove", "backup")
    active_ids = {str(task.get("id", "")) for task in active
                  if any(str(task.get("type", "")).lower().startswith(k)
                         or k in str(task.get("type", "")).lower() for k in RELATED)}
    suspicious, uncertain = [], []
    for snapshot in stuck:
        text = configs[snapshot["vmid"]][1]
        body = next(b for n, b in _snapshot_sections(text) if n == snapshot["snapshot"])
        stamp = re.search(r"^snaptime:\s*(\d+)", body, re.M)
        if str(snapshot["vmid"]) in active_ids or not stamp or time.time() - int(stamp.group(1)) < 3600:
            uncertain.append(snapshot)
        else:
            suspicious.append(snapshot)
    return {
        "classification": CLASS_WARNING if suspicious else CLASS_UNVERIFIED,
        "summary_key": "stuck" if suspicious else "evaluationFailed",
        "summary_params": {"count": len(suspicious), "total": total},
        "affected": suspicious,
        "incomplete": bool(uncertain),
        "evidence": evidence + "\nRecent, undated, or held by a running snapshot"
                    " or backup task, so not classified as interrupted: "
                    + json.dumps(uncertain),
    }


@register("storage.zfs_scrub_age", AREA_STORAGE, "WARNING")
def _zfs_scrub_age(ctx):
    """A resilver is not evidence of a completed scrub."""
    if not Path("/sys/module/zfs").exists():
        return None
    rc, out = ctx.run(["zpool", "list", "-H", "-o", "name"], timeout=15)
    if rc != 0:
        return {"classification": CLASS_UNVERIFIED, "summary_key": "evaluationFailed",
                "incomplete": True, "evidence": out}
    pools = out.split()
    if not pools:
        return None
    overdue, observations, unknown = [], [], []
    for pool in pools:
        rc, status = ctx.run(["zpool", "status", pool], timeout=20)
        scan = re.search(r"^\s*scan:\s*(.+)$", status, re.M)
        row = {"pool": pool, "scan": scan.group(1) if scan else "unavailable"}
        observations.append(row)
        if rc != 0 or not scan:
            unknown.append(pool)
            continue
        if "none requested" in row["scan"]:
            overdue.append({"pool": pool, "reason": "no scrub recorded"})
            continue
        m = re.search(r"^scrub repaired .* on\s+(.+)$", row["scan"])
        if not m:
            # In-progress scrub or last scan was a resilver: last completed
            # scrub date is not available here, not proved absent.
            unknown.append(pool)
            continue
        try:
            when = time.mktime(time.strptime(" ".join(m.group(1).split()), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            unknown.append(pool)
            continue
        days = int((time.time() - when) / 86400)
        row["days"] = days
        if days < 0:
            unknown.append(pool)
        elif days >= ctx.policy.threshold("zfs_scrub_days"):
            overdue.append({"pool": pool, "days": days})
    for row in overdue:
        row["classification"] = CLASS_WARNING
        row["reason_key"] = "scrubOverdue"
    return {"classification": None if overdue
                              else CLASS_UNVERIFIED if unknown else CLASS_CONFORMANT,
            "summary_key": "overdue" if overdue else "evaluationFailed" if unknown else "recent",
            "summary_params": {"count": len(overdue), "total": len(pools)},
            "affected": overdue, "observations": observations, "incomplete": bool(unknown),
            "evidence": json.dumps(observations, indent=2)}


@register("security.ssh_root_login", AREA_SECURITY, "WARNING")
def _ssh_root_login(ctx):
    """How the SSH daemon admits the root account.

    Proxmox ships ``PermitRootLogin yes``, which accepts a password.
    ``prohibit-password`` keeps root access while requiring a key.
    """
    rc, out = ctx.run(["sshd", "-T"], timeout=15)
    if rc != 0:
        return None
    value = ""
    for line in (out or "").splitlines():
        if line.lower().startswith("permitrootlogin"):
            parts = line.split()
            value = parts[1].lower() if len(parts) > 1 else ""
            break
    if not value:
        return _unverified(out)

    options = dict(line.split(None, 1) for line in out.splitlines() if len(line.split(None, 1)) == 2)
    password = options.get("passwordauthentication", "unknown")
    interactive = options.get("kbdinteractiveauthentication", "unknown")
    methods = options.get("authenticationmethods", "any")
    evidence = (f"PermitRootLogin: {value}\nPasswordAuthentication: {password}\n"
                f"KbdInteractiveAuthentication: {interactive}\nAuthenticationMethods: {methods}\n"
                "Default sshd context only; Match rules and each client/source are not evaluated.")
    if value == "yes" and (password == "yes" or interactive == "yes"):
        # Proxmox ships `yes`, so every stock install would otherwise
        # carry a warning. Reporting the shipped state as a fault makes
        # this a hardening policy of our own; declaring the access
        # unwanted is what turns it into one.
        declared = ctx.policy.host_expectation("ssh_root_login")
        return {"classification": CLASS_WARNING if declared == audit_policy.NOT_REQUIRED
                                  else CLASS_OBSERVATION,
                "summary_key": "password",
                "evidence": evidence}
    if value in ("prohibit-password", "without-password", "forced-commands-only") or (
            value == "yes" and password == "no" and interactive == "no"):
        return {"classification": CLASS_CONFORMANT, "summary_key": "keyOnly",
                "evidence": evidence}
    if value == "no":
        return {"classification": CLASS_CONFORMANT, "summary_key": "denied",
                "evidence": evidence}
    return _unverified(evidence)


@register("network.bond_members", AREA_NETWORK, "WARNING")
def _bond_members(ctx):
    """Each bond's members, and what their state costs.

    A bond keeps working while members fail, so the loss is not otherwise
    visible from the host — but losing one link of four and losing the
    only live link are not the same event. In active-backup a standby
    member reports as up and carries nothing, which is the mode working
    as designed, so the reading here is how many links remain, not how
    many are passing traffic.
    """
    base = Path("/proc/net/bonding")
    if not base.is_dir():
        return None
    bonds = sorted(p.name for p in base.iterdir() if p.is_file())
    if not bonds:
        return None

    down, lines, unreadable = [], [], []
    for bond in bonds:
        text = ctx.read(base / bond)
        if not text:
            unreadable.append(bond)
            continue
        mode = ""
        m = re.search(r"^Bonding Mode:\s*(.+)$", text, re.M)
        if m:
            mode = m.group(1).strip()
        members = re.findall(
            r"^Slave Interface:\s*(\S+)(.*?)(?=^Slave Interface:|\Z)",
            text, re.M | re.S)
        up, failed, unknown = [], [], []
        for name, body in members:
            status = re.search(r"^MII Status:\s*(\S+)", body, re.M)
            state = status.group(1) if status else "unknown"
            if state == "up":
                up.append(name)
            elif state == "down":
                failed.append({"bond": bond, "interface": name,
                               "status": state, "mode": mode})
            else:
                unknown.append(name)
        if unknown or not members:
            unreadable.append(bond)
        lines.append(f"{bond} ({mode}): {len(up)}/{len(members)} member(s) up")

        for entry in failed:
            # No link left is a connectivity loss; some link left is a
            # redundancy loss, which is serious but not an interruption.
            if not up and not unknown:
                entry["classification"] = CLASS_CRITICAL
                entry["reason_key"] = "bondNoMembersUp"
            else:
                entry["classification"] = CLASS_WARNING
                entry["reason_key"] = "bondRedundancyLost"
        down.extend(failed)

    if not lines:
        return _unverified("Bond state could not be read")
    evidence = "\n".join(lines)
    if down:
        evidence += "\n\nnot up:\n  " + "\n  ".join(
            f"{d['bond']}/{d['interface']}: {d['status']}" for d in down)

    if not down:
        if unreadable:
            return _unverified(evidence)
        return {"classification": CLASS_CONFORMANT, "summary_key": "allUp",
                "summary_params": {"total": len(bonds)}, "evidence": evidence}
    return {
        "summary_key": "membersDown",
        "summary_params": {"count": len(down), "total": len(bonds)},
        "affected": down,
        "incomplete": bool(unreadable),
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Remaining catalogue
# ---------------------------------------------------------------------------

# A thin pool serves writes from its own capacity, so allocating beyond it
# only holds while guests leave space unwritten.

# Journald keeps growing until it reaches its configured cap; past this it
# is reported so the cap can be confirmed as deliberate.


@register("system.security_updates", AREA_SYSTEM, "WARNING")
def _security_updates(ctx):
    """Pending package updates that come from a security repository."""
    rc, out = ctx.run(["apt-get", "-s", "upgrade"], timeout=40)
    if rc != 0:
        return None
    lines = [l for l in (out or "").splitlines() if l.startswith("Inst ")]
    if not lines:
        return {"classification": CLASS_CONFORMANT, "summary_key": "none"}
    security = [l for l in lines if re.search(r"security", l, re.I)]
    evidence = f"pending updates: {len(lines)}\nfrom a security repository: {len(security)}"
    if security:
        evidence += "\n\n" + "\n".join(
            l.split()[1] for l in security[:25] if len(l.split()) > 1)
    if not security:
        return {"classification": CLASS_CONFORMANT, "summary_key": "noSecurity",
                "summary_params": {"total": len(lines)}, "evidence": evidence}
    return {
        "classification": CLASS_WARNING,
        "summary_key": "pending",
        "summary_params": {"count": len(security), "total": len(lines)},
        "affected": [{"package": l.split()[1]} for l in security if len(l.split()) > 1],
        "evidence": evidence,
    }


@register("guests.cpu_host_type", AREA_GUESTS, "INFO")
def _cpu_host_type(ctx):
    """Virtual machines pinned to the host processor model.

    ``cpu: host`` exposes the physical processor's feature set. A guest
    started this way can only migrate to a node offering the same
    features.

    The constraint only has an effect where there is somewhere to migrate
    to, so on a node that belongs to no cluster this is not assessed.
    Reporting it there would flag the setting that gives the best
    performance on a standalone host.
    """
    configs = {vmid: _current_config(text) for vmid, text in ctx.qemu_configs.items()}
    if not configs:
        return None
    if not Path("/etc/corosync/corosync.conf").exists():
        return None
    pinned = []
    for vmid, text in sorted(configs.items()):
        m = re.search(r"^cpu:\s*([^\s,]+)", text, re.M)
        if m and m.group(1).strip() == "host":
            name = ""
            n = re.search(r"^name:\s*(\S+)", text, re.M)
            if n:
                name = n.group(1)
            pinned.append({"vmid": vmid, "name": name})
    if not pinned:
        return {"classification": CLASS_CONFORMANT, "summary_key": "none",
                "summary_params": {"total": len(configs)}}
    # Pinning to the host processor is correct on plenty of clusters. It
    # constrains migration, which is worth stating; incompatibility with
    # a particular destination is not something this can demonstrate.
    for row in pinned:
        row["classification"] = CLASS_OBSERVATION
        row["reason_key"] = "pinnedToHostCpu"
    return {
        "summary_key": "pinned",
        "summary_params": {"count": len(pinned), "total": len(configs)},
        "affected": pinned,
        "evidence": "cpu: host — " + ", ".join(
            f"{p['vmid']}{' (' + p['name'] + ')' if p['name'] else ''}"
            for p in pinned),
    }


@register("backup.retention_defined", AREA_BACKUP, "WARNING")
def _retention_defined(ctx):
    """Where each job's retention comes from, without guessing at the rest.

    Retention is resolved in the order Proxmox applies it: the job's own
    setting, then the storage's, then the node default in
    ``/etc/vzdump.conf``. Keeping every copy can be deliberate, so a job
    with no explicit policy is reported as configuration rather than as a
    defect. A PBS destination prunes on the server, under jobs this node
    cannot see, so its retention is reported as not read here — which is
    a limit of the vantage point, not a finding about the job.
    """
    jobs = [j for j in _parse_vzdump_jobs(ctx.vzdump_jobs) if _local_enabled(j, ctx)]
    if not jobs:
        return None
    defaults = {}
    for line in ctx.read("/etc/vzdump.conf", optional=True).splitlines():
        m = re.match(r"^\s*([\w-]+):\s*(.+)", line)
        if m:
            defaults[m.group(1)] = m.group(2)
    storages = {s["id"]: s for s in ctx.storages}
    undeclared, remote, rows = [], [], []
    for job in jobs:
        sid = job.get("storage") or defaults.get("storage")
        storage = storages.get(sid, {})
        retention, source = None, None
        for name, settings in (("job", job), ("storage", storage), ("node", defaults)):
            retention = settings.get("prune-backups") or settings.get("maxfiles")
            if retention:
                source = name
                break
        row = {"job": job["id"], "storage": sid, "policy": retention, "source": source}
        if not retention:
            if storage.get("type") == "pbs" or not storage:
                row["status"] = "pruned on the backup server; not read from this node"
                remote.append({"job": job["id"], "storage": sid,
                               "classification": CLASS_OBSERVATION,
                               "reason_key": "retentionOnServer"})
            else:
                row["status"] = "no explicit retention; every copy is kept"
                undeclared.append({"job": job["id"], "storage": sid,
                                   "classification": CLASS_OBSERVATION,
                                   "reason_key": "retentionNotDeclared"})
        rows.append(row)

    affected = undeclared + remote
    if not affected:
        return {"classification": CLASS_CONFORMANT, "summary_key": "allDefined",
                "summary_params": {"total": len(jobs)}, "observations": rows,
                "evidence": json.dumps(rows, indent=2)}
    return {"summary_key": "notDeclared" if undeclared else "onServer",
            "summary_params": {"count": len(affected), "total": len(jobs)},
            "affected": affected, "observations": rows,
            "evidence": json.dumps(rows, indent=2)}


@register("storage.thin_pool_overprovisioning", AREA_STORAGE, "WARNING")
def _thin_overprovisioning(ctx):
    """Virtual capacity handed out by each thin pool against its own size.

    A thin pool serves writes from its real capacity. Allocating beyond it
    holds only while guests leave space unwritten; once they do not, writes
    to the pool fail.
    """
    # An explicit separator is required: a thin pool leaves pool_lv empty,
    # and splitting on whitespace would collapse the gap and shift every
    # field after it.
    rc, out = ctx.run(
        ["lvs", "--noheadings", "--units", "b", "--nosuffix",
         "--separator", "|",
         "-o", "vg_name,lv_name,lv_size,pool_lv,lv_attr,data_percent,metadata_percent"],
        timeout=20)
    if rc != 0:
        return _unverified(out or "Thin-pool inventory could not be read.")
    if not (out or "").strip():
        return None

    overprovision_limit = ctx.policy.threshold("thin_overprovision_ratio")
    fill_limit = ctx.policy.threshold("thin_pool_usage_percent")
    pools: dict[tuple, int] = {}
    used_percent: dict[tuple, str] = {}
    metadata_percent: dict[tuple, str] = {}
    allocated: dict[tuple, int] = {}
    unreadable = []
    for line in out.splitlines():
        f = [c.strip() for c in line.split("|")]
        if len(f) < 5:
            unreadable.append("Malformed logical-volume inventory row.")
            continue
        vg, lv, size_raw, pool, attr = f[0], f[1], f[2], f[3], f[4]
        try:
            size_number = float(size_raw)
            if not math.isfinite(size_number) or size_number <= 0:
                raise ValueError("invalid size")
            size = int(size_number)
        except (ValueError, OverflowError):
            unreadable.append(f"{vg}/{lv}: capacity could not be read.")
            continue
        if attr.startswith("t"):
            pools[(vg, lv)] = size
            used_percent[(vg, lv)] = f[5] if len(f) > 5 and f[5] else "?"
            metadata_percent[(vg, lv)] = f[6] if len(f) > 6 and f[6] else "?"
        elif pool:
            key = (vg, pool)
            allocated[key] = allocated.get(key, 0) + size
    if not pools:
        return _unverified("\n".join(unreadable)) if unreadable else None

    over, rows, pressure = [], [], []
    for key, size in sorted(pools.items()):
        used = allocated.get(key, 0)
        ratio = used / size if size else 0
        # The allocation ratio alone does not describe the risk: what
        # matters is how much of the pool the volumes have actually
        # written. Both figures are reported so the reader can judge.
        rows.append({"pool": f"{key[0]}/{key[1]}",
                     "allocated_bytes": used, "pool_bytes": size,
                     "allocation_percent": round(ratio * 100, 2),
                     "data_percent": used_percent.get(key, "?"),
                     "metadata_percent": metadata_percent.get(key, "?")})
        for metric, readings in (("data", used_percent), ("metadata", metadata_percent)):
            try:
                percent = float(readings.get(key, "?"))
                if not math.isfinite(percent) or not 0 <= percent <= 100:
                    raise ValueError("invalid percentage")
            except ValueError:
                unreadable.append(f"{key[0]}/{key[1]}: {metric} usage could not be read.")
                continue
            if percent >= fill_limit:
                # Written space is the figure that runs out. Metadata
                # exhaustion takes a pool read-only, which is graver than
                # data running low.
                pressure.append({"pool": f"{key[0]}/{key[1]}", "metric": metric,
                                 "percent": percent,
                                 "classification": CLASS_WARNING,
                                 "reason_key": ("thinMetadataPressure"
                                                if metric == "metadata"
                                                else "thinDataPressure")})
        if ratio > overprovision_limit:
            # Handing out more virtual capacity than the pool has is the
            # point of thin provisioning. On its own it describes the
            # design, not a risk.
            over.append({"pool": f"{key[0]}/{key[1]}",
                         "percent": round(ratio * 100),
                         "classification": CLASS_OBSERVATION,
                         "reason_key": "overprovisioned"})
    evidence = json.dumps(rows, indent=2)
    if unreadable:
        evidence += "\nNot verified: " + ", ".join(unreadable)
    evidence += (f"\nReview thresholds: {overprovision_limit:g}x allocated capacity; "
                 f"{fill_limit:g}% written data or metadata.")
    affected = pressure + over
    if unreadable and not pressure:
        return _unverified(evidence, affected=affected)
    if not affected:
        return {"classification": CLASS_CONFORMANT, "summary_key": "withinRatio",
                "summary_params": {"total": len(pools)}, "evidence": evidence}
    return {
        "summary_key": "pressure" if pressure else "aboveRatio",
        "summary_params": {"count": len(affected), "total": len(pools),
                           "pressure": len(pressure)},
        "affected": affected,
        "evidence": evidence,
        "incomplete": bool(unreadable),
    }


def _size_to_mb(value: str):
    """A systemd size specification in MiB, or None when unreadable."""
    m = re.fullmatch(r"\s*([\d.]+)\s*([KMGT])?\s*", value or "", re.I)
    if not m:
        return None
    scale = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}
    return float(m.group(1)) * scale.get((m.group(2) or "M").upper(), 1)


@register("system.journal_size", AREA_SYSTEM, "INFO")
def _journal_size(ctx):
    """Space held by the systemd journal against its configured cap."""
    rc, out = ctx.run(["journalctl", "--disk-usage"], timeout=20)
    if rc != 0:
        return None
    m = re.search(r"take up ([\d.]+)([KMG])", out or "")
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2)
    mb = value * {"K": 1 / 1024, "M": 1, "G": 1024}[unit]

    # The cap may be set in the main file or overridden by a drop-in; the
    # last assignment encountered is the effective one.
    candidates = [Path("/etc/systemd/journald.conf")]
    drop_in = Path("/etc/systemd/journald.conf.d")
    if drop_in.is_dir():
        candidates.extend(sorted(drop_in.glob("*.conf")))

    cap = ""
    for path in candidates:
        try:
            for line in path.read_text(errors="replace").splitlines():
                if re.match(r"^\s*SystemMaxUse=", line):
                    cap = line.split("=", 1)[1].strip()
        except OSError:
            continue
    # What matters is the journal against the cap that applies to it, not
    # against a number chosen here. journald keeps to SystemMaxUse where
    # it is set, and otherwise to a tenth of the filesystem it lives on,
    # so a 2 GiB journal on a large volume is within its bounds and a
    # small one on a full volume may not be.
    cap_mb = _size_to_mb(cap) if cap else None
    if cap_mb is None:
        rc_fs, fs_out = ctx.run(["df", "-B1", "--output=size", "/var/log"], timeout=10)
        sizes = [int(v) for v in (fs_out or "").split() if v.isdigit()]
        cap_mb = (sizes[0] / (1024 * 1024)) * 0.10 if sizes else None
        cap_source = "journald default: 10% of the filesystem"
    else:
        cap_source = f"SystemMaxUse={cap}"

    share = (mb / cap_mb * 100) if cap_mb else None
    evidence = (f"journal on disk: {value:.1f}{unit}\n"
                f"effective cap: {cap_source}"
                + (f"\ncap: {cap_mb:.0f} MiB, in use: {share:.0f}%"
                   if cap_mb else "\ncap: not determined"))
    params = {"size": f"{value:.1f}{unit}",
              "percent": str(round(share)) if share is not None else "?"}

    if share is None:
        return {"classification": CLASS_UNVERIFIED, "summary_key": "capUnknown",
                "summary_params": params, "evidence": evidence}
    if share >= ctx.policy.threshold("journal_usage_percent"):
        return {"classification": CLASS_OBSERVATION, "summary_key": "nearCap",
                "summary_params": params, "evidence": evidence}
    return {"classification": CLASS_CONFORMANT, "summary_key": "bounded",
            "summary_params": params, "evidence": evidence}


@register("guests.replication_state", AREA_GUESTS, "WARNING")
def _replication_state(ctx):
    """Replication jobs and what their last run actually reported.

    Read from the API rather than from the status table: matching the
    words "error" or "fail" in formatted output cannot tell a failing job
    from one whose target is named ``failover``, and it cannot see a job
    that has never run at all. The API reports the failure count, the
    last error and the last successful synchronisation, which is what the
    question needs.
    """
    try:
        text = Path("/etc/pve/replication.cfg").read_text(errors="replace")
    except OSError:
        return None
    if not re.search(r"^local:\s*\S+", text, re.M):
        return None

    rc, out = ctx.run(["pvesh", "get", f"/nodes/{ctx.node}/replication",
                       "--output-format", "json"], timeout=25)
    if rc != 0:
        return {"classification": CLASS_UNVERIFIED, "summary_key": "statusUnavailable",
                "incomplete": True, "evidence": (out or "")[:2000]}
    try:
        jobs = json.loads(out)
        if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
            raise ValueError("invalid replication inventory")
    except ValueError:
        return {"classification": CLASS_UNVERIFIED, "summary_key": "statusUnavailable",
                "incomplete": True, "evidence": (out or "")[:2000]}
    if not jobs:
        return None

    now = time.time()
    affected, rows, unreadable = [], [], []
    for job in jobs:
        try:
            fail_count = int(job.get("fail_count", 0))
            last_sync = float(job.get("last_sync") or 0)
            disabled = job.get("disable", 0)
            if (fail_count < 0 or not math.isfinite(last_sync) or last_sync < 0
                    or last_sync > now + 300 or disabled not in (0, 1, "0", "1", False, True)):
                raise ValueError("invalid replication status")
        except (ValueError, TypeError, OverflowError):
            unreadable.append(str(job.get("id", "unknown job")))
            continue
        row = {"job": job.get("id"), "guest": job.get("guest"),
               "target": job.get("target"), "schedule": job.get("schedule"),
               "fail_count": fail_count,
               "last_sync": last_sync,
               "next_sync": job.get("next_sync"),
               "disabled": disabled in (1, "1", True)}
        rows.append(row)
        if row["disabled"]:
            # A paused job is a decision, and it is worth seeing: it looks
            # like protection in the interface and provides none.
            affected.append({"job": row["job"], "guest": row["guest"],
                             "classification": CLASS_OBSERVATION,
                             "reason_key": "replicationDisabled"})
            continue
        if job.get("error") or fail_count > 0:
            row["error"] = str(job.get("error") or "")[:400]
            affected.append({"job": row["job"], "guest": row["guest"],
                             "fail_count": row["fail_count"],
                             "classification": CLASS_WARNING,
                             "reason_key": "replicationFailing"})
            continue
        if not row["last_sync"]:
            affected.append({"job": row["job"], "guest": row["guest"],
                             "classification": CLASS_WARNING,
                             "reason_key": "replicationNeverRan"})
            continue
        # Overdue against the schedule the job itself declares, with the
        # same grace the backup age check applies.
        limit = _schedule_age_limit(
            row["schedule"] or "", ctx.policy.threshold("backup_schedule_grace_ratio"))
        if limit and now - row["last_sync"] > limit:
            affected.append({"job": row["job"], "guest": row["guest"],
                             "hours": round((now - row["last_sync"]) / 3600, 1),
                             "classification": CLASS_WARNING,
                             "reason_key": "replicationOverdue"})

    evidence = json.dumps(rows, indent=2)
    if unreadable:
        evidence += "\nUnreadable job status: " + ", ".join(unreadable)
        if not any(obj["classification"] == CLASS_WARNING for obj in affected):
            return _unverified(evidence, affected=affected, observations=rows)
    if not affected:
        return {"classification": CLASS_CONFORMANT, "summary_key": "healthy",
                "summary_params": {"total": len(jobs)}, "observations": rows,
                "evidence": evidence}
    return {"summary_key": "failing",
            "summary_params": {"count": len(affected), "total": len(jobs)},
            "affected": affected, "observations": rows, "evidence": evidence,
            "incomplete": bool(unreadable)}


@register("network.bridge_without_ports", AREA_NETWORK, "INFO")
def _bridge_without_ports(ctx):
    """Bridges that carry no physical interface.

    Such a bridge connects guests to each other but not to the network
    beyond the host. That is a valid internal network and also what a
    bridge looks like when its port was removed or renamed.
    """
    try:
        text = Path("/etc/network/interfaces").read_text(errors="replace")
    except OSError:
        return None

    bridges, current = {}, None
    for line in text.splitlines():
        m = re.match(r"^iface\s+(\S+)", line)
        if m:
            current = m.group(1) if m.group(1).startswith("vmbr") else None
            if current:
                bridges[current] = ""
            continue
        if current and re.match(r"^\s+bridge[-_]ports\s+", line):
            bridges[current] = line.split(None, 1)[1].strip()
    if not bridges:
        return None

    isolated = [{"bridge": b} for b, ports in sorted(bridges.items())
                if not ports or ports == "none"]
    evidence = "\n".join(f"{b}: {p or 'none'}" for b, p in sorted(bridges.items()))
    if not isolated:
        return {"classification": CLASS_CONFORMANT, "summary_key": "allConnected",
                "summary_params": {"total": len(bridges)}, "evidence": evidence}
    # A bridge without a physical port is how an internal network is
    # built; without a stated expectation of where it should reach, there
    # is nothing here to contradict.
    for row in isolated:
        row["classification"] = CLASS_OBSERVATION
        row["reason_key"] = "noPhysicalPort"
    return {
        "summary_key": "isolated",
        "summary_params": {"count": len(isolated), "total": len(bridges)},
        "affected": isolated,
        "evidence": evidence,
    }


@register("system.swap_configured", AREA_SYSTEM, "INFO")
def _swap_configured(ctx):
    """Swap available to the host and its size against physical memory."""
    rc, out = ctx.run(["swapon", "--show=NAME,SIZE,TYPE", "--bytes",
                       "--noheadings"], timeout=15)
    total_mem = _host_memory_bytes(ctx)
    entries = []
    swap_total = 0
    for line in (out or "").splitlines():
        f = line.split()
        if len(f) >= 2 and f[1].isdigit():
            entries.append({"device": f[0], "bytes": int(f[1])})
            swap_total += int(f[1])

    gib = 1024 ** 3
    if not entries:
        # Running without swap is a legitimate design, and no ratio to
        # RAM is required by anything. Memory pressure is a separate
        # question, answered by the memory analysis.
        return {"classification": CLASS_OBSERVATION, "summary_key": "none",
                "evidence": f"no swap active\nhost memory: {total_mem / gib:.1f} GiB"
                            if total_mem else "no swap active"}
    evidence = "\n".join(f"{e['device']}: {e['bytes'] / gib:.1f} GiB" for e in entries)
    if total_mem:
        evidence += f"\nhost memory: {total_mem / gib:.1f} GiB"
    return {
        "classification": CLASS_CONFORMANT,
        "summary_key": "active",
        "summary_params": {"size": f"{swap_total / gib:.1f} GiB"},
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Recoverability, capacity and the chain that keeps a host maintainable
#
# What the catalogue above establishes is that a copy was scheduled and
# that one exists. Neither says it can be restored. These read the
# evidence Proxmox already keeps about whether the protection works, what
# the host is running out of, and whether the mechanisms that would warn
# somebody are themselves working.
# ---------------------------------------------------------------------------

@register("backup.verification_state", AREA_BACKUP, "WARNING")
def _backup_verification(ctx):
    """The verification result each stored backup carries.

    Proxmox Backup Server records, per snapshot, whether a verification
    job has read it back and found it intact. That is the nearest thing
    to evidence that a copy is restorable that can be had without
    restoring it, and it is already stored — so an audit that reports
    only that a backup exists is leaving the better fact unread.

    A snapshot nothing has verified is not a damaged snapshot. It is one
    whose integrity has not been established, which is what the report
    says.
    """
    destinations = [s for s in ctx.storages
                    if s.get("type") == "pbs" and _local_enabled(s, ctx)]
    if not destinations:
        return None

    # A shared backup server holds the copies of every node that writes
    # to it, and keeps the copies of guests that no longer exist. Grading
    # all of them made this node answerable for another node's snapshots
    # and for guests nobody could restore anywhere.
    local = set(ctx.lxc_configs) | set(ctx.qemu_configs)
    if not local:
        return None

    failed, unverified, verified, unreadable = [], [], 0, []
    for storage in destinations:
        sid = storage["id"]
        rc, out = ctx.run(["pvesh", "get", f"/nodes/{ctx.node}/storage/{sid}/content",
                           "--output-format", "json"], timeout=30)
        if rc != 0:
            unreadable.append(sid)
            continue
        try:
            entries = json.loads(out)
            if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
                raise ValueError("invalid backup inventory")
        except ValueError:
            unreadable.append(sid)
            continue
        # Only the newest snapshot of each guest is judged: an older one
        # that was never verified is history, not present protection.
        newest: dict = {}
        for entry in entries:
            vmid = entry.get("vmid")
            if vmid is None or entry.get("content") != "backup":
                continue
            try:
                if int(vmid) not in local:
                    continue
            except (TypeError, ValueError):
                continue
            when = entry.get("ctime")
            if (str(vmid).isdigit() and type(when) in (int, float)
                    and math.isfinite(when) and 0 < when <= time.time() + 300):
                vmid = int(vmid)
            else:
                unreadable.append(sid + " (snapshot identity/date not verified)")
                continue
            current = newest.get(vmid)
            if current is None or when > current["ctime"]:
                newest[vmid] = entry

        # Whether an earlier copy of the same guest did verify. A newest
        # copy that failed while a verified one is still held is a
        # different situation from one where nothing verified at all,
        # and the same result told both stories.
        fallback = set()
        for entry in entries:
            vmid = entry.get("vmid")
            if vmid is None or entry.get("content") != "backup":
                continue
            try:
                vmid = int(vmid)
            except (TypeError, ValueError):
                continue
            if vmid not in newest or entry is newest.get(vmid):
                continue
            verification = entry.get("verification")
            if isinstance(verification, dict) and str(
                    verification.get("state", "")).lower() == "ok":
                fallback.add(vmid)

        for vmid, entry in sorted(newest.items()):
            verification = entry.get("verification")
            if verification is None:
                state = "none"
            elif isinstance(verification, dict) and isinstance(verification.get("state"), str):
                state = verification["state"].lower()
            else:
                unreadable.append(sid + f" (verification not read for {vmid})")
                continue
            row = {"vmid": vmid, "storage": sid,
                   "volume": entry.get("volid"), "verification": state}
            if state == "ok":
                verified += 1
            elif state == "failed":
                # Never critical: the audit performs no restore, so it
                # cannot demonstrate that recovery is impossible. What it
                # can say is whether anything else verified.
                failed.append({**row, "classification": CLASS_WARNING,
                               "reason_key": "verificationFailedWithFallback"
                               if vmid in fallback else "verificationFailedOnly"})
            elif state in ("none", "pending"):
                unverified.append({**row, "classification": CLASS_OBSERVATION,
                                   "reason_key": "verificationNotRun"})
            else:
                unreadable.append(sid + f" (unknown verification state for {vmid}: {state})")

    total = verified + len(failed) + len(unverified)
    if not total and not unreadable:
        return None
    evidence = (f"destinations: {', '.join(s['id'] for s in destinations)}\n"
                f"guests on this node: {len(local)}\n"
                f"verified: {verified}\nfailed: {len(failed)}\n"
                f"not verified: {len(unverified)}\n"
                "Verification reads a stored copy back; it is not a restore test.")
    if unreadable:
        evidence += "\nNot read: " + ", ".join(unreadable)

    affected = failed + unverified
    if not affected:
        return {"classification": CLASS_UNVERIFIED if unreadable else CLASS_CONFORMANT,
                "summary_key": "evaluationFailed" if unreadable else "allVerified",
                "summary_params": {"total": str(verified)},
                "incomplete": bool(unreadable), "evidence": evidence}
    return {"summary_key": "failed" if failed else "notVerified",
            "summary_params": {"failed": str(len(failed)),
                               "pending": str(len(unverified)), "total": str(total)},
            "affected": affected, "incomplete": bool(unreadable), "evidence": evidence}


@register("backup.job_results", AREA_BACKUP, "WARNING")
def _backup_job_results(ctx):
    """How the recorded backup runs ended.

    A schedule that fires and fails leaves the configuration looking
    correct, and the age check only notices once the newest copy has
    aged past its limit. The task log says what happened at the time.
    """
    rc, out = ctx.run(["pvesh", "get", f"/nodes/{ctx.node}/tasks",
                       "--typefilter", "vzdump", "--limit", "200", "--output-format", "json"], timeout=30)
    if rc != 0:
        return _unverified(out)
    try:
        tasks = json.loads(out)
        if not isinstance(tasks, list) or any(not isinstance(t, dict) for t in tasks):
            raise ValueError("invalid task inventory")
    except ValueError:
        return _unverified(out)

    runs = [t for t in tasks if str(t.get("type", "")).startswith("vzdump")]
    if not runs:
        return None

    def guest_of(task):
        # `/nodes/<node>/tasks` does not populate `id` consistently,
        # although the same guest identifier is part of the UPID.
        vmid = task.get("id")
        upid = str(task.get("upid") or "")
        if vmid in (None, "") and upid.startswith("UPID:"):
            parts = upid.split(":")
            if len(parts) > 6 and parts[6].isdigit():
                vmid = int(parts[6])
        return vmid

    # The last run is what describes the present. A failure four months
    # ago followed by success every night since says the backup works,
    # and counting both in one number said the opposite for as long as
    # the task log kept the old one.
    latest, unknown, recovered = {}, [], []
    for task in sorted(runs, key=lambda t: t.get("starttime") or 0):
        status = str(task.get("status") or "")
        if not status or status.lower() in ("running", "unknown"):
            unknown.append(task.get("upid", "unknown task"))
            continue
        key = guest_of(task)
        previous = latest.get(key)
        if previous is not None and previous["status"] != "OK" and status == "OK":
            recovered.append(previous)
        latest[key] = {"status": status[:200], "when": task.get("starttime"),
                       "upid": str(task.get("upid") or ""), "vmid": key}

    failures = [{"job": r["upid"], "upid": r["upid"], "vmid": r["vmid"],
                 "status": r["status"], "when": r["when"],
                 "classification": CLASS_WARNING, "reason_key": "backupRunFailed"}
                for r in latest.values() if r["status"] != "OK"]
    # A failure the next run cleared is history, not a finding.
    healed = [{"job": r["upid"], "upid": r["upid"], "vmid": r["vmid"],
               "status": r["status"], "when": r["when"],
               "classification": CLASS_OBSERVATION, "reason_key": "backupRunRecovered"}
              for r in recovered]

    evidence = (f"recorded backup runs: {len(runs)}\n"
                f"guests with a recorded run: {len(latest)}\n"
                f"latest run failed for: {len(failures)}\n"
                f"earlier failures a later run cleared: {len(recovered)}\n"
                "Only the most recent run of each guest is graded: an earlier "
                "failure followed by a success is not a current failure. Read "
                "from the node's task log, which is retained for a limited "
                "period; runs older than that are not visible here.")
    if unknown:
        evidence += "\nResults not verified: " + ", ".join(unknown)
    if not failures:
        if unknown and not latest:
            return _unverified(evidence)
        if healed:
            return {"summary_key": "recovered",
                    "summary_params": {"count": str(len(healed)),
                                       "total": str(len(latest))},
                    "affected": healed, "incomplete": bool(unknown),
                    "evidence": evidence}
        return {"classification": CLASS_CONFORMANT, "summary_key": "allSucceeded",
                "summary_params": {"total": str(len(latest))}, "evidence": evidence}
    return {"summary_key": "someFailed",
            "summary_params": {"count": str(len(failures)), "total": str(len(latest))},
            "affected": failures + healed, "incomplete": bool(unknown),
            "evidence": evidence}


@register("system.filesystem_capacity", AREA_SYSTEM, "CRITICAL")
def _filesystem_capacity(ctx):
    """Space and inodes on the filesystems the host itself needs.

    PVE reports the capacity of its own storage; it says nothing about
    the root filesystem, /var or /var/log, which is where a host stops
    being able to write logs, take a snapshot or run an upgrade. Inodes
    are read alongside: a filesystem with free space and no inodes left
    fails exactly the same way, and nothing else here would see it.
    """
    mounts = ["/", "/var", "/var/log", "/var/lib/vz"]
    limit = ctx.policy.threshold("filesystem_usage_percent")
    inode_limit = ctx.policy.threshold("filesystem_inode_percent")

    # A filesystem remounted read-only has already stopped accepting
    # writes; nothing about its percentage says so. Read from the kernel
    # rather than inferred from how full it looks.
    readonly = set()
    rc0, mountinfo = ctx.run(["findmnt", "-rno", "TARGET,OPTIONS"],
                             timeout=15, allowed_codes=(0, 1))
    for line in (mountinfo or "").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and re.search(r"(^|,)ro(,|$)", parts[1]):
            readonly.add(parts[0])

    rc, out = ctx.run(["df", "--output=target,pcent,ipcent,size,avail"] + mounts,
                      timeout=15, allowed_codes=(0, 1))
    if rc not in (0, 1):
        return _unverified(out)
    rows, affected, seen = [], [], set()
    incomplete = rc != 0
    for line in (out or "").splitlines()[1:]:
        fields = line.rsplit(None, 4)
        if len(fields) != 5:
            incomplete = True
            continue
        target, used, inodes = fields[0], fields[1].rstrip("%"), fields[2].rstrip("%")
        if (not target.startswith("/") or not used.isdigit()
                or not (inodes.isdigit() or inodes == "-")):
            incomplete = True
            continue
        if inodes == "-":
            incomplete = True
        # Several of the paths often live on one filesystem; reporting it
        # once is the truth, four times is noise.
        if target in seen:
            continue
        seen.add(target)
        available = fields[4].strip()
        exhausted = available.isdigit() and int(available) == 0
        row = {"mount": target, "used_percent": used, "inode_percent": inodes,
               "available_kb": int(available) if available.isdigit() else None,
               "read_only": target in readonly}
        rows.append(row)

        # Crossing a review threshold is a risk; having nothing left is
        # the failure itself. Ninety-one per cent and a hundred per cent
        # are not the same event, and a fixed high percentage would not
        # prove one either — zero bytes, no inodes or a read-only mount
        # do.
        if target in readonly:
            affected.append({"mount": target,
                             "classification": CLASS_CRITICAL,
                             "reason_key": "filesystemReadOnly"})
        elif exhausted:
            affected.append({"mount": target, "percent": int(used or 100),
                             "classification": CLASS_CRITICAL,
                             "reason_key": "filesystemExhausted"})
        elif used.isdigit() and int(used) >= limit:
            affected.append({"mount": target, "percent": int(used),
                             "classification": CLASS_WARNING,
                             "reason_key": "filesystemNearlyFull"})
        if inodes.isdigit() and int(inodes) >= 100:
            affected.append({"mount": target, "percent": int(inodes),
                             "classification": CLASS_CRITICAL,
                             "reason_key": "inodesExhausted"})
        elif inodes.isdigit() and int(inodes) >= inode_limit:
            affected.append({"mount": target, "percent": int(inodes),
                             "classification": CLASS_WARNING,
                             "reason_key": "inodesNearlyExhausted"})
    if not rows:
        return _unverified(out or "No filesystem readings")

    evidence = json.dumps(rows, indent=2) + (
        f"\nReview thresholds: {limit:g}% space, {inode_limit:g}% inodes. "
        "A critical result is not a higher percentage: it is no space "
        "left, no inodes left, or a mount the kernel reports read-only.")
    if not affected:
        if incomplete:
            return _unverified(evidence)
        return {"classification": CLASS_CONFORMANT, "summary_key": "withinLimits",
                "summary_params": {"total": str(len(rows))}, "evidence": evidence}
    return {"summary_key": "pressure",
            "summary_params": {"count": str(len(affected))},
            "affected": affected, "observations": rows, "incomplete": incomplete, "evidence": evidence}


@register("storage.pool_integrity", AREA_STORAGE, "CRITICAL")
def _pool_integrity(ctx):
    """Redundancy and error counters of each ZFS pool.

    Age of a disk is planning information; a pool that is degraded, or
    that is counting read, write or checksum errors, is the thing that
    actually threatens the data on it. Both the pool state and the
    counters come from the same `zpool status` this catalogue already
    reads for scrub age.
    """
    if not Path("/sys/module/zfs").exists():
        return None
    rc, out = ctx.run(["zpool", "list", "-H", "-o", "name,health"], timeout=20)
    if rc != 0:
        return _unverified(out)
    pools = [line.split("\t") for line in (out or "").splitlines() if line.strip()]
    if not pools:
        return None

    affected, rows, unreadable = [], [], []
    for entry in pools:
        name = entry[0]
        health = entry[1] if len(entry) > 1 else "UNKNOWN"
        rc2, status = ctx.run(["zpool", "status", name], timeout=25)
        if rc2 != 0 or not re.search(r"^\s*state:\s*\S+", status, re.M):
            unreadable.append(name)
            status = ""
        errors = []
        for line in (status or "").splitlines():
            # Device lines carry three counters; anything non-zero is a
            # device that has been having trouble.
            m = re.match(r"^\s+(\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", line)
            if m and any(int(m.group(i)) for i in (3, 4, 5)):
                errors.append({"device": m.group(1), "state": m.group(2),
                               "read": int(m.group(3)), "write": int(m.group(4)),
                               "checksum": int(m.group(5))})
        rows.append({"pool": name, "health": health, "devices_with_errors": errors})

        if health not in ("ONLINE", "DEGRADED", "FAULTED", "UNAVAIL", "REMOVED", "OFFLINE", "SUSPENDED"):
            unreadable.append(name + " (unknown health)")
        elif health != "ONLINE":
            affected.append({"pool": name, "state": health,
                             "classification": CLASS_CRITICAL if health in
                                 ("FAULTED", "UNAVAIL", "REMOVED") else CLASS_WARNING,
                             "reason_key": "poolNotOnline"})
        for device in errors:
            affected.append({"pool": name, "device": device["device"],
                             "read": device["read"], "write": device["write"],
                             "checksum": device["checksum"],
                             "classification": CLASS_WARNING,
                             "reason_key": "poolDeviceErrors"})

    evidence = json.dumps(rows, indent=2) + (
        "\nCounters are cumulative since the last `zpool clear`; a non-zero "
        "count is a device that had trouble, not necessarily one having it now.")
    if unreadable:
        evidence += "\nNot verified: " + ", ".join(unreadable)
    if not affected:
        if unreadable:
            return _unverified(evidence)
        return {"classification": CLASS_CONFORMANT, "summary_key": "healthy",
                "summary_params": {"total": str(len(pools))}, "evidence": evidence}
    return {"summary_key": "degraded",
            "summary_params": {"count": str(len(affected)), "total": str(len(pools))},
            "affected": affected, "observations": rows, "incomplete": bool(unreadable), "evidence": evidence}


@register("system.update_chain", AREA_SYSTEM, "WARNING")
def _update_chain(ctx):
    """How recently the host learned what updates exist.

    An empty list of pending updates means one of two things: the host is
    current, or nothing has told it otherwise in weeks. They look
    identical from the package list alone, so what is read here is when
    apt last rebuilt its picture — every update check in this catalogue
    inherits the age of that picture.

    Whether each repository can still be reached is not tested: finding
    out means refreshing the indexes, and an assessment that only reads
    does not do that.
    """
    # pkgcache.bin is rebuilt from files already on disk, so its date
    # says nothing about contacting a repository. These three do, in
    # descending order of how directly they say it. The success stamp is
    # written by apt's own periodic job and is absent on a plain Proxmox
    # install, which is why it cannot be the only source: relying on it
    # alone left this check unverifiable on every host that never
    # installed unattended-upgrades.
    # An index file's own mtime is the date the repository published it —
    # identical on every host that fetched the same file — so it says
    # nothing about this host. Its ctime is when apt put it here, which
    # only happens when a fetch succeeded. The partial directory is
    # touched by the attempt itself, so it proves apt tried and not that
    # anything arrived.
    lists = Path("/var/lib/apt/lists")
    newest, origin, meaning = 0.0, "", ""
    for index in (list(lists.glob("*_InRelease")) + list(lists.glob("*_Release"))
                  + list(lists.glob("*_Packages")) if lists.is_dir() else []):
        try:
            stamp = index.stat().st_ctime
        except OSError:
            continue
        if stamp > newest:
            newest, origin = stamp, str(index)
            meaning = "when apt last installed an index file here"
    for path, description in (
            (Path("/var/lib/apt/periodic/update-success-stamp"),
             "a refresh apt recorded as successful"),
            (Path("/var/lib/apt/lists"),
             "the last time a file was added or replaced in the index directory")):
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        if stamp > newest:
            newest, origin, meaning = stamp, str(path), description

    attempted = None
    try:
        attempted = (lists / "partial").stat().st_mtime
    except OSError:
        pass
    if not newest:
        return {"classification": CLASS_UNVERIFIED, "summary_key": "indexAgeUnknown",
                "incomplete": True,
                "evidence": "No index file in /var/lib/apt/lists carries a "
                            "placement date, and neither the directory nor "
                            "apt's success stamp could be read."}

    age_days = (time.time() - newest) / 86400
    if age_days < 0:
        return _unverified("APT refresh timestamp is in the future", summary_key="indexAgeUnknown")
    limit = ctx.policy.threshold("package_index_days")
    evidence = (f"package indexes last refreshed: "
                f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(newest))}\n"
                f"age: {age_days:.1f} day(s)\nread from: {origin}\n"
                f"what that date is: {meaning}\n"
                + (f"last fetch apt started: "
                   f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(attempted))}"
                   " (an attempt, not a result)\n" if attempted else "")
                + "A repository that answers \"not modified\" leaves its index "
                "untouched, so this is when an index last changed here rather "
                "than when apt last succeeded. Repository reachability is not "
                "tested: establishing it would mean refreshing the indexes, "
                "which this assessment does not do.")
    if age_days < limit:
        return {"classification": CLASS_CONFORMANT, "summary_key": "current",
                "summary_params": {"days": str(int(age_days))}, "evidence": evidence}
    return {"summary_key": "stale", "summary_params": {"days": str(int(age_days))},
            "affected": [{"indexes": "apt", "days": int(age_days),
                          "classification": CLASS_WARNING,
                          "reason_key": "indexesStale"}],
            "evidence": evidence}


@register("system.notification_delivery", AREA_SYSTEM, "WARNING")
def _notification_delivery(ctx):
    """Observed delivery outcomes for currently enabled channels; never sends."""
    server = sys.modules.get("flask_server") or sys.modules.get("__main__")
    manager = getattr(server, "notification_manager", None)
    lister = getattr(manager, "list_channels", None)
    if not callable(lister):
        return _unverified("Notification configuration is unavailable")
    try:
        payload = lister()
        channels = payload.get("channels") if isinstance(payload, dict) else None
        if not isinstance(channels, dict) or payload.get("error"):
            raise ValueError("Notification configuration is unreadable")
    except Exception as exc:
        return _unverified(exc)
    enabled = {name: info for name, info in channels.items()
               if isinstance(info, dict) and info.get("enabled")}
    if not enabled:
        return {"classification": CLASS_OBSERVATION, "summary_key": "noChannels",
                "evidence": "No notification channel is enabled.\nConfigured channel types: "
                            + (", ".join(sorted(channels)) or "(none)")}

    affected, observations, unreadable = [], [], []
    reader = getattr(manager, "get_history", None)
    for name, info in enabled.items():
        row = {"channel": name, "configured": bool(info.get("configured"))}
        observations.append(row)
        if not info.get("configured"):
            affected.append({"channel": name, "classification": CLASS_WARNING,
                             "reason_key": "channelIncomplete"})
            continue
        try:
            if not callable(reader):
                raise ValueError("Notification history is unavailable")
            payload = reader(limit=100, channel=name)
            history = payload.get("history") if isinstance(payload, dict) else None
            if payload.get("error") or not isinstance(history, list):
                raise ValueError("Notification history is unreadable")
            history = [r for r in history if isinstance(r, dict) and r.get("channel") == name]
            if not history:
                raise ValueError("No retained delivery for this enabled channel")
            latest = history[0]  # get_history guarantees descending sent_at.
            if type(latest.get("success")) not in (bool, int) or latest["success"] not in (0, 1):
                raise ValueError("Unrecognised delivery result")
            row.update(last_success=bool(latest["success"]), when=latest.get("sent_at"),
                       records_examined=len(history))
            if not latest["success"]:
                affected.append({"channel": name, "classification": CLASS_WARNING,
                                 "reason_key": "deliveryFailing", "when": latest.get("sent_at"),
                                 "last_error": str(latest.get("error_message") or "")[:200]})
        except Exception as exc:
            row["not_verified"] = str(exc)
            unreadable.append(name)
    evidence = json.dumps(observations, indent=2) + (
        "\nLatest retained outcome per enabled channel; not a delivery test "
        "or a guarantee of future delivery. Disabled channels are outside scope.")
    if affected:
        return {"summary_key": "failing",
                "summary_params": {"count": str(len(affected)), "total": str(len(enabled))},
                "affected": affected, "observations": observations,
                "incomplete": bool(unreadable), "evidence": evidence}
    if unreadable:
        return _unverified(evidence, observations=observations)
    return {"classification": CLASS_CONFORMANT, "summary_key": "delivering",
            "summary_params": {"total": str(len(enabled))},
            "observations": observations, "evidence": evidence}


HB_STATE_DIR = "/usr/local/share/proxmenux"
DUMP_DIR = "/var/lib/vz/dump"


def _escrow_mode() -> str:
    """How the site has chosen to protect the backup encryption key.

    Only the recorded mode is read. The keyfile itself is never opened
    and its content never leaves this function's absence.
    """
    try:
        value = (Path(HB_STATE_DIR) / "pbs-key.mode").read_text().strip()
    except OSError:
        return "full"          # absent means an install from before the setting
    return value if value in ("none", "local", "full") else "full"


def _host_backup_jobs() -> list[dict]:
    """What ProxMenux recorded about the host backups it ran.

    Its own job log is the authority here, not a directory listing. The
    runner writes wherever the job's backend says — the local dump
    directory, a mounted share, a backup server — and names the archive
    after the job. Looking for files called ``hostcfg-*`` in one
    directory therefore missed every manual job and every job whose
    destination was somewhere else, and then reported their absence as
    the absence of any backup at all.
    """
    log_dir = Path("/var/log/proxmenux/backup-jobs")
    if not log_dir.is_dir():
        return []
    jobs = []
    for status in sorted(log_dir.glob("*-last.status")):
        try:
            fields = dict(
                line.split("=", 1) for line in status.read_text(errors="replace").splitlines()
                if "=" in line)
        except OSError:
            continue
        archive, backend, profile = "", "", ""
        log_path = fields.get("LOG_FILE", "").strip()
        if log_path:
            try:
                for line in Path(log_path).read_text(errors="replace").splitlines():
                    if line.startswith("LOCAL_ARCHIVE="):
                        archive = line.split("=", 1)[1].strip()
                    elif line.startswith("Backend:"):
                        backend = line.split(":", 1)[1].strip()
                    elif line.startswith("Profile:"):
                        profile = line.split(":", 1)[1].strip()
            except OSError:
                pass
        jobs.append({
            "job": fields.get("JOB_ID", status.stem).strip(),
            "run_at": fields.get("RUN_AT", "").strip(),
            "result": fields.get("RESULT", "").strip(),
            "backend": backend, "profile": profile,
            "archive": archive,
            # A job whose destination is a backup server names no local
            # path: absent is not the same as unreadable from here.
            "stored": Path(archive).is_file() if archive else None,
        })
    return jobs


@register("backup.host_recovery", AREA_BACKUP, "CRITICAL", budget=40)
def _host_recovery(ctx):
    """Whether this node could be rebuilt, not just its guests.

    Guest backups restore workloads onto a working node. They do not
    restore the node: the storage definitions that say where those
    guests live, the network that reaches them, the cluster membership,
    the certificates.
    """
    jobs = _host_backup_jobs()

    # Sidecars describe archives the local dump directory holds, and add
    # the size the job log does not record. Archives already named by a
    # job record are not repeated.
    dump_dir = Path(DUMP_DIR)
    known = {j["archive"] for j in jobs if j["archive"]}
    if dump_dir.is_dir():
        for sidecar in sorted(dump_dir.glob("*.proxmenux.json"), key=lambda f: f.name):
            try:
                meta = json.loads(sidecar.read_text(errors="replace"))
            except (OSError, ValueError):
                continue
            name = str(meta.get("archive") or "")
            path = str(dump_dir / name) if name else ""
            if not path or path in known:
                continue
            jobs.append({
                "job": meta.get("job_id") or meta.get("kind") or sidecar.name,
                "run_at": meta.get("created_at", ""), "result": "ok",
                "backend": "local", "profile": meta.get("profile") or "",
                "archive": path, "size_bytes": meta.get("archive_size"),
                "stored": (dump_dir / name).is_file(),
            })

    rc, timers = ctx.run(["systemctl", "list-timers", "--all", "--no-pager"],
                         timeout=20, allowed_codes=(0, 1))
    scheduled = sorted({part for line in (timers or "").splitlines()
                        for part in line.split()
                        if part.startswith("proxmenux-backup-")
                        and part.endswith(".timer")})

    # Encryption is reported through the mode the site recorded. Whether
    # a key exists bears on recoverability; what it contains does not.
    keys = sorted(p.name for p in Path("/etc/pve/priv/storage").glob("*.enc")) \
        if Path("/etc/pve/priv/storage").is_dir() else []
    if (Path(HB_STATE_DIR) / "pbs-key.conf").is_file():
        keys.append("pbs-key.conf")
    mode = _escrow_mode() if keys else ""

    now = time.time()
    for job in jobs:
        job["days"] = None
        age = _event_age_days(job.get("run_at"), now)
        if age is not None:
            job["days"] = round(age, 1)

    limit_days = ctx.policy.threshold("backup_fallback_days")
    # A copy this check can still account for: stored where it said, or
    # sent to a destination it cannot read but has no evidence against.
    retrievable = [j for j in jobs
                   if j["result"] == "ok" and j["stored"] is not False
                   and j["days"] is not None]
    newest = min(retrievable, key=lambda j: j["days"]) if retrievable else None

    evidence = json.dumps({"jobs": jobs, "scheduled_timers": scheduled,
                           "encryption_keys_present": len(keys),
                           "key_escrow_mode": mode or None,
                           "age_limit_days": limit_days},
                          indent=2, ensure_ascii=False, default=str)
    evidence += ("\nRead from the job records ProxMenux writes for every host "
                 "backup it runs, and from the sidecars in " + DUMP_DIR + ". A "
                 "job whose destination is a backup server names no local "
                 "path, so whether its copy is still held there is not "
                 "established from this node. Restoring the node's own "
                 "configuration is a separate operation from restoring a "
                 "guest, and neither the presence of an archive nor this "
                 "check is a restore test. Encryption keys are reported by "
                 "count and recorded escrow mode only; no key is read.")

    if not jobs:
        if scheduled:
            return {"classification": CLASS_OBSERVATION,
                    "summary_key": "scheduledOnly",
                    "summary_params": {"count": str(len(scheduled))},
                    "evidence": evidence}
        # A host-configuration backup is a ProxMenux feature the operator
        # may simply not have set up; its absence is not a fault of the
        # host. Reported as an observation, not a warning.
        return {"classification": CLASS_OBSERVATION, "summary_key": "noHostBackup",
                "evidence": evidence}

    affected = []
    for job in jobs:
        name = job["archive"].rsplit("/", 1)[-1] or job["job"]
        if job["result"] and job["result"] != "ok":
            affected.append({"name": name, "job": job["job"],
                             "classification": CLASS_WARNING,
                             "reason_key": "hostBackupJobFailed"})
        elif job["stored"] is False:
            # Recorded as produced and no longer at the path it named:
            # bookkeeping left behind by a copy removed elsewhere.
            affected.append({"name": name, "job": job["job"],
                             "classification": CLASS_OBSERVATION,
                             "reason_key": "hostArchiveMissing"})

    if newest is None:
        affected.append({"name": "hostcfg", "classification": CLASS_WARNING,
                         "reason_key": "hostNoRetrievableCopy"})
    elif newest["days"] > limit_days:
        affected.append({"name": newest["archive"].rsplit("/", 1)[-1] or newest["job"],
                         "hours": newest["days"] * 24,
                         "classification": CLASS_WARNING,
                         "reason_key": "hostBackupStale"})
    if not scheduled:
        affected.append({"name": "hostcfg", "classification": CLASS_OBSERVATION,
                         "reason_key": "hostBackupUnscheduled"})
    if keys and mode == "none":
        affected.append({"name": "pbs-key", "classification": CLASS_OBSERVATION,
                         "reason_key": "recoveryKeyLocalOnly"})

    if not affected:
        return {"classification": CLASS_CONFORMANT, "summary_key": "protected",
                "summary_params": {"total": str(len(retrievable))},
                "observations": jobs, "evidence": evidence}
    return {"summary_key": "attention",
            "summary_params": {"count": str(len(affected)),
                               "total": str(len(jobs))},
            "affected": affected, "observations": jobs, "evidence": evidence}


@register("system.cluster_quorum", AREA_SYSTEM, "CRITICAL", budget=40)
def _cluster_quorum(ctx):
    """Quorum, membership and the redundancy of what carries them.

    A node that loses quorum keeps its guests running and stops being
    able to change anything: no start, no migration, no write to the
    cluster filesystem. Corosync on a single link means one switch, one
    cable or one NIC decides whether the cluster stays whole, which is
    worth stating while everything still works rather than after.
    """
    conf = Path("/etc/pve/corosync.conf")
    if not conf.exists():
        conf = Path("/etc/corosync/corosync.conf")
    if not conf.exists():
        return {"classification": CLASS_NOT_APPLICABLE,
                "summary_key": "standalone",
                "evidence": "No corosync configuration is present: this node "
                            "is not a member of a cluster."}

    try:
        text = conf.read_text(errors="replace")
    except OSError as exc:
        return _unverified(exc)

    # Nodes the cluster is configured to have, and the links it is
    # configured to carry them over.
    configured = re.findall(r"\bname:\s*(\S+)", text)
    rings = len({m for m in re.findall(r"ring(\d+)_addr", text)}) or 1

    rc, status = ctx.run(["pvecm", "status"], timeout=20, allowed_codes=(0, 2))
    quorate = expected = total = None
    for line in (status or "").splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "quorate":
            quorate = value.lower() == "yes"
        elif key == "expected votes":
            expected = value
        elif key == "total votes":
            total = value

    # Members corosync currently sees. A configured node that is absent
    # is not a spare: it is a vote the cluster is not counting.
    seen = set()
    rc2, members = ctx.run(["pvecm", "nodes"], timeout=20, allowed_codes=(0, 2))
    for line in (members or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit():
            seen.add(parts[-2] if parts[-1] == "(local)" else parts[-1])

    evidence = (f"quorate: {quorate}\nexpected votes: {expected}\n"
                f"total votes: {total}\n"
                f"nodes configured: {len(configured)} ({', '.join(configured)})\n"
                f"nodes seen: {len(seen)} ({', '.join(sorted(seen))})\n"
                f"corosync links: {rings}\n"
                "Losing quorum leaves running guests running and blocks every "
                "change to the cluster. Link count is read from the "
                "configuration; the links are not probed.")

    if quorate is None:
        return _unverified(evidence)

    affected = []
    if not quorate:
        affected.append({"name": ctx.node, "classification": CLASS_CRITICAL,
                         "reason_key": "clusterInquorate"})
    for name in configured:
        if seen and name not in seen:
            affected.append({"name": name, "classification": CLASS_WARNING,
                             "reason_key": "clusterMemberAbsent"})
    if rings < 2 and len(configured) > 1:
        # One link is a working cluster with a single point of failure:
        # a fact about how it was built, not a fault in how it runs.
        affected.append({"name": "corosync", "classification": CLASS_OBSERVATION,
                         "reason_key": "clusterSingleLink"})

    if not affected:
        return {"classification": CLASS_CONFORMANT, "summary_key": "quorate",
                "summary_params": {"total": str(len(configured)),
                                   "links": str(rings)},
                "evidence": evidence}
    return {"summary_key": "attention",
            "summary_params": {"count": str(len(affected)),
                               "total": str(len(configured))},
            "affected": affected, "evidence": evidence}


def _event_age_days(value, now: float):
    """Age of a recorded event, whichever way the store wrote its date.

    The observation log keeps ISO strings, while other Monitor tables
    keep epoch seconds. Reading only one of the two silently produced an
    unknown age, and an unknown age turns an error happening this
    morning into one that stopped months ago.
    """
    if value in (None, ""):
        return None
    try:
        return (now - float(value)) / 86400
    except (TypeError, ValueError):
        pass
    try:
        text = str(value).replace("Z", "+00:00")
        stamp = datetime.fromisoformat(text)
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone().replace(tzinfo=None)
        return (now - time.mktime(stamp.timetuple())) / 86400
    except (TypeError, ValueError):
        return None


def _recorded_disk_events() -> list[dict]:
    """Disk events the Monitor recorded, flattened per device.

    Read from the same store the inventory prints, so the assessment and
    the inventory can never disagree about what happened to a disk.
    """
    server = sys.modules.get("flask_server") or sys.modules.get("__main__")
    getter = getattr(getattr(server, "health_persistence", None),
                     "get_disk_observations", None)
    if getter is None:
        return []
    try:
        return list(getter() or [])
    except Exception:
        return []


@register("hardware.disk_errors", AREA_HARDWARE, "WARNING", budget=20)
def _disk_errors(ctx):
    """Historical disk events recorded independently of current SMART health.

    SMART answers "does the device consider itself healthy", and it
    keeps answering yes while the kernel logs read failures. ProxMenux
    keeps this log because those failures happened and nothing else was
    writing them down.

    These recorded events are warnings because their occurrence was
    verified. They do not override the device's current
    SMART self-assessment or Proxmox's current health result, and they do
    not assert that the disk is presently failing.
    """
    records = _recorded_disk_events()
    if not records:
        # An empty store and a store whose entries were all dismissed
        # look the same from here, and neither supports the claim that
        # no disk reported an error. Saying which of the two it is is
        # not possible; saying there is nothing to grade is.
        return {"classification": CLASS_NOT_APPLICABLE,
                "summary_key": "noEvents",
                "evidence": "The health monitor holds no undismissed disk "
                            "event. A dismissed observation is dropped by "
                            "the monitor and is not read back here."}

    now = time.time()
    recent_days = ctx.policy.threshold("disk_error_recent_days")
    affected, observations = [], []
    for record in records:
        device = (record.get("device_name") or "").replace("/dev/", "")
        if not device:
            continue
        last = record.get("last_occurrence")
        age_days = _event_age_days(last, now)
        severity = str(record.get("severity") or "").upper()
        count = record.get("occurrence_count") or 0
        active = age_days is not None and age_days <= recent_days


        # Carries what the inventory's own observation table shows, so
        # the finding and the inventory read as one account of the disk
        # rather than as a summary and a table that repeat each other.
        row = {"name": device, "type": record.get("error_type", ""),
               "severity": severity.lower(), "count": count,
               "first_seen": record.get("first_occurrence"), "last_seen": last,
               "message": (record.get("raw_message") or "")[:400],
               "days": None if age_days is None else round(age_days, 1)}
        observations.append(row)

        severe = severity == "CRITICAL"
        affected.append({**row, "classification": CLASS_WARNING,
                         "reason_key": ("diskErrorsActive" if severe and active else
                                        "diskErrorsPast" if severe else
                                        "diskWarningsActive" if active else
                                        "diskWarningsPast")})

    devices = sorted({r["name"] for r in observations})
    evidence = json.dumps({"devices": devices, "events": observations,
                           "recent_within_days": recent_days},
                          indent=2, ensure_ascii=False, default=str)
    evidence += ("\nRecorded because Linux reported them; neither SMART nor "
                 "Proxmox surfaces these, and both may report the device as "
                 "healthy. Stated as separate warnings without overriding "
                 "that current health result. Events the reader dismissed are not "
                 "listed: the "
                 "monitor drops them and this reads what the monitor keeps. "
                 "Recorded by the health monitor as events occurred. SMART "
                 "reports the device's present opinion of itself and is read "
                 "by a separate check; a device can report healthy while its "
                 "reads fail. Counts are cumulative since the record was "
                 "opened, not a rate.")

    # Every retained record becomes a row, so there is no path to a
    # conformant result here: a host with nothing recorded returned not
    # applicable above. Claiming "no disk reported an error" would be an
    # assertion this check never gets to make.
    with_events = sorted({a["name"] for a in affected})
    return {"classification": CLASS_WARNING, "summary_key": "recorded",
            "summary_params": {"count": str(len(with_events)),
                               "total": str(len(devices))},
            "affected": affected, "observations": observations,
            "evidence": evidence}


@register("system.boot_loader", AREA_SYSTEM, "WARNING", budget=25)
def _boot_loader(ctx):
    """Whether the loader that would start the kernel is on every disk.

    The kernel check reads which version the host would boot and says,
    in as many words, that it does not verify the boot loader's
    installation. This is that half. Proxmox keeps one EFI partition per
    boot disk and synchronises the kernels into all of them, so the
    machine survives losing any one of them. When one falls behind, the
    redundancy is nominal: the surviving disk boots an older kernel, or
    does not boot.

    A host that does not use proxmox-boot-tool keeps its loader
    elsewhere and there is nothing here to compare.
    """
    if not Path("/etc/kernel/proxmox-boot-uuids").exists():
        return None

    rc, out = ctx.run(["proxmox-boot-tool", "status"], timeout=25,
                      allowed_codes=(0, 1))
    booted = ""
    partitions, problems = [], []
    for line in (out or "").splitlines():
        line = line.strip()
        if line.startswith("System currently booted with"):
            booted = line.rsplit(" ", 1)[-1]
            continue
        # `<UUID> is configured with: <mode> (versions: a, b, c)`
        m = re.match(r"^([0-9A-Fa-f-]+)\s+is configured with:\s*(\S+)"
                     r"(?:\s*\(versions:\s*(.*?)\))?\s*$", line)
        if m:
            partitions.append({
                "partition": m.group(1), "mode": m.group(2),
                "versions": [v.strip() for v in (m.group(3) or "").split(",") if v.strip()],
            })
        elif line.startswith("E:") or " is " in line and "configured" not in line:
            problems.append(line)

    if not partitions:
        return _unverified(
            "proxmox-boot-tool reported no configured partition.\n" + (out or "").strip())

    rc2, running = ctx.run(["uname", "-r"])
    running = (running or "").strip()
    sets = {tuple(sorted(p["versions"])) for p in partitions}
    newest = max((v for p in partitions for v in p["versions"]),
                 key=_version_key, default="")

    evidence = json.dumps({"booted_with": booted or None, "partitions": partitions,
                           "running_kernel": running, "messages": problems},
                          indent=2, ensure_ascii=False)
    evidence += ("\nEach partition is an EFI system partition Proxmox keeps in "
                 "step so the host survives losing any one boot disk. The "
                 "kernel each would start is read from the tool's own report; "
                 "no partition is mounted and no boot is attempted.")

    affected = []
    for message in problems:
        affected.append({"name": "proxmox-boot-tool", "detail": message,
                         "classification": CLASS_WARNING,
                         "reason_key": "bootToolReported"})
    if len(sets) > 1:
        # Redundancy that only exists on paper: the surviving disk would
        # start something other than what this one would.
        for entry in partitions:
            if tuple(sorted(entry["versions"])) != tuple(sorted(
                    max(sets, key=len))):
                affected.append({"name": entry["partition"],
                                 "classification": CLASS_WARNING,
                                 "reason_key": "bootEspOutOfSync"})
    for entry in partitions:
        if newest and newest not in entry["versions"]:
            affected.append({"name": entry["partition"],
                             "classification": CLASS_WARNING,
                             "reason_key": "bootEspMissingNewest"})
    if len(partitions) == 1:
        affected.append({"name": partitions[0]["partition"],
                         "classification": CLASS_OBSERVATION,
                         "reason_key": "bootSingleEsp"})

    # Duplicates arise when a partition is both out of step and missing
    # the newest kernel, which is one fact told twice.
    seen, unique = set(), []
    for row in affected:
        key = (row["name"], row["reason_key"])
        if key not in seen:
            seen.add(key)
            unique.append(row)

    if not unique:
        return {"classification": CLASS_CONFORMANT, "summary_key": "synchronised",
                "summary_params": {"total": str(len(partitions))},
                "observations": partitions, "evidence": evidence}
    return {"summary_key": "attention",
            "summary_params": {"count": str(len({r["name"] for r in unique})),
                               "total": str(len(partitions))},
            "affected": unique, "observations": partitions, "evidence": evidence}


# The services Proxmox needs to answer at all. A node whose pvedaemon is
# down still runs its guests and stops being manageable, which no other
# check here would notice.
PVE_ESSENTIAL = ("pve-cluster", "pvedaemon", "pveproxy", "pvestatd")


@register("system.failed_units", AREA_SYSTEM, "CRITICAL", budget=25)
def _failed_units(ctx):
    """Units systemd has given up on, and the ones Proxmox needs.

    A failed unit is not an opinion: systemd tried, exhausted its
    restarts and stopped. Most of what fails on a host is peripheral,
    so the list is reported as it stands — except for the services that
    answer the API and hold the cluster filesystem, where a node that
    keeps its guests running while refusing every management operation
    looks healthy from every other angle.
    """
    rc, out = ctx.run(["systemctl", "list-units", "--state=failed",
                       "--no-legend", "--no-pager", "--plain"],
                      timeout=20, allowed_codes=(0, 1))
    if rc not in (0, 1):
        return _unverified(out)

    failed = []
    for line in (out or "").splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0].endswith((".service", ".socket", ".mount",
                                                  ".timer", ".target", ".path")):
            failed.append({"unit": parts[0], "load": parts[1],
                           "active": parts[2], "sub": parts[3],
                           "description": parts[4] if len(parts) > 4 else ""})

    # Asked separately: an essential service can be inactive without
    # systemd counting it as failed, and that is the same outcome.
    # `systemctl is-active` prints one word per unit and exits non-zero
    # when any is not active. Anything else — a usage error, a message
    # about a unit it could not find — is prose, and zipping prose onto
    # the service names turned every word of it into a critical finding.
    KNOWN = {"active", "inactive", "failed", "activating", "deactivating",
             "reloading", "unknown", "maintenance"}
    rc2, states = ctx.run(["systemctl", "is-active", *PVE_ESSENTIAL],
                          timeout=20, allowed_codes=(0, 1, 3))
    tokens = (states or "").split()
    essential, essential_error = {}, ""
    if len(tokens) == len(PVE_ESSENTIAL) and all(t in KNOWN for t in tokens):
        essential = dict(zip(PVE_ESSENTIAL, tokens))
    else:
        essential_error = (states or "").strip()[:300] or "no state was returned"

    evidence = json.dumps({"failed_units": failed,
                           "essential_services": essential or None,
                           "essential_services_error": essential_error or None},
                          indent=2, ensure_ascii=False)
    evidence += ("\nA failed unit is one systemd stopped retrying, not one that "
                 "reported an error and recovered. The essential services are "
                 "read by name because an inactive one is not always a failed "
                 "one, and the outcome is the same. What each unit does is not "
                 "interpreted here.")

    affected = []
    for unit, state in essential.items():
        if state and state != "active":
            affected.append({"name": unit, "state": state,
                             "classification": CLASS_CRITICAL,
                             "reason_key": "essentialServiceDown"})
    for entry in failed:
        if entry["unit"].split(".")[0] in PVE_ESSENTIAL:
            continue
        affected.append({"name": entry["unit"], "detail": entry["description"],
                         "classification": CLASS_WARNING,
                         "reason_key": "unitFailed"})

    if essential_error and not affected:
        return _unverified(evidence)
    if not affected:
        return {"classification": CLASS_CONFORMANT, "summary_key": "allRunning",
                "summary_params": {"total": str(len(essential))},
                "evidence": evidence}
    return {"summary_key": "attention",
            "summary_params": {"count": str(len(affected))},
            "affected": affected, "observations": failed,
            "incomplete": bool(essential_error), "evidence": evidence}


@register("storage.ceph_health", AREA_STORAGE, "CRITICAL", budget=30)
def _ceph_health(ctx):
    """Ceph's own verdict on itself, and the checks behind it.

    Ceph already grades its own state and does it far better than
    anything read from outside could: it knows which placement groups
    are short of replicas and which OSDs stopped answering. What is
    added here is putting that verdict where the rest of the host's
    state is read, with the named checks that produced it, so a cluster
    in HEALTH_WARN does not go unseen because nobody opened its
    dashboard. Its tests are not reimplemented.

    A node with no Ceph configuration has nothing to report: the client
    binary ships with Proxmox whether or not a cluster was ever created.
    """
    if not Path("/etc/pve/ceph.conf").exists():
        return None

    rc, out = ctx.run(["ceph", "-s", "--format", "json"], timeout=30,
                      allowed_codes=(0, 1))
    if rc != 0:
        return _unverified(f"ceph status could not be read: {(out or '').strip()[:400]}")
    try:
        status = json.loads(out)
        health = status.get("health") or {}
        state = str(health.get("status") or "")
    except (ValueError, AttributeError):
        return _unverified(out)
    if not state:
        return _unverified(out)

    named = health.get("checks") or {}
    rows = []
    for key, body in (named.items() if isinstance(named, dict) else []):
        summary = ""
        if isinstance(body, dict):
            summary = str((body.get("summary") or {}).get("message") or "")
        rows.append({"name": key, "severity": str((body or {}).get("severity", "")),
                     "message": summary[:300]})

    evidence = json.dumps({"status": state, "checks": rows,
                           "monitors": (status.get("quorum_names") or []),
                           "osds": (status.get("osdmap") or {})},
                          indent=2, ensure_ascii=False, default=str)
    evidence += ("\nCeph's own health verdict and the checks it named. Its "
                 "tests are not reimplemented here and no pool, placement "
                 "group or OSD is queried separately.")

    if state == "HEALTH_OK":
        return {"classification": CLASS_CONFORMANT, "summary_key": "healthy",
                "evidence": evidence}
    gravity = CLASS_CRITICAL if state == "HEALTH_ERR" else CLASS_WARNING
    affected = [{"name": r["name"], "detail": r["message"],
                 "classification": (CLASS_CRITICAL
                                    if str(r["severity"]).upper().endswith("ERR")
                                    else CLASS_WARNING),
                 "reason_key": "cephCheckRaised"} for r in rows]
    if not affected:
        affected = [{"name": state, "classification": gravity,
                     "reason_key": "cephCheckRaised"}]
    return {"summary_key": "degraded",
            "summary_params": {"state": state, "count": str(len(affected))},
            "affected": affected, "evidence": evidence}


@register("storage.array_integrity", AREA_STORAGE, "CRITICAL", budget=25)
def _array_integrity(ctx):
    """Redundancy below the filesystems: software RAID and multipath.

    ZFS pools have their own check. What neither it nor PVE reports is
    an mdadm array running on fewer devices than it was built with, or a
    multipath map down to its last path — both of which keep serving
    while the redundancy they exist for is gone, and neither of which
    appears anywhere else in this report.
    """
    arrays, paths = [], []

    try:
        mdstat = Path("/proc/mdstat").read_text(errors="replace")
    except OSError:
        mdstat = ""
    current = None
    for line in mdstat.splitlines():
        header = re.match(r"^(md\d+)\s*:\s*(\S+)\s+(\S+)", line)
        if header:
            current = {"array": header.group(1), "state": header.group(2),
                       "level": header.group(3), "devices": "", "healthy": None,
                       "rebuilding": False}
            arrays.append(current)
            continue
        if current is None:
            continue
        # `      2929890304 blocks super 1.2 [3/2] [UU_]`
        blocks = re.search(r"\[(\d+)/(\d+)\]\s+\[([U_]+)\]", line)
        if blocks:
            current["devices"] = f"{blocks.group(2)}/{blocks.group(1)}"
            current["healthy"] = "_" not in blocks.group(3)
            current["present"] = int(blocks.group(2))
            current["expected"] = int(blocks.group(1))
        if re.search(r"(resync|recovery|reshape)\s*=", line):
            current["rebuilding"] = True

    # Asked of the filesystem rather than of a shell. `command -v` exits
    # 127 when the tool is absent, which the runner recorded as a failed
    # source — turning the ordinary case, a host with neither RAID nor
    # multipath, into an unverified finding with an error attached.
    if any((Path(d) / "multipath").exists()
           for d in ("/sbin", "/usr/sbin", "/bin", "/usr/bin")):
        rc, out = ctx.run(["multipath", "-ll"], timeout=25, allowed_codes=(0, 1))
        mapname = None
        for line in (out or "").splitlines():
            if line and not line[0].isspace() and not line.startswith(("size=", "|", "`")):
                mapname = line.split()[0]
                paths.append({"map": mapname, "active": 0, "failed": 0})
            elif paths and re.search(r"\b(active|failed|faulty|offline|shaky)\b", line):
                if re.search(r"\b(failed|faulty|offline)\b", line):
                    paths[-1]["failed"] += 1
                elif re.search(r"\bactive\b", line) and ":" in line:
                    paths[-1]["active"] += 1

    if not arrays and not paths:
        return None

    evidence = json.dumps({"md_arrays": arrays, "multipath_maps": paths},
                          indent=2, ensure_ascii=False)
    evidence += ("\nRead from /proc/mdstat and, where the tool is installed, "
                 "`multipath -ll`. An array rebuilding is doing what it should; "
                 "an array short of devices is serving without the redundancy it "
                 "was built with. ZFS pools are reported by their own check.")

    affected = []
    for array in arrays:
        if array["state"] != "active":
            affected.append({"name": array["array"], "classification": CLASS_CRITICAL,
                             "reason_key": "arrayNotActive"})
        elif array.get("healthy") is False:
            affected.append({"name": array["array"], "detail": array["devices"],
                             "classification": CLASS_WARNING,
                             "reason_key": "arrayRebuilding" if array["rebuilding"]
                                           else "arrayDegraded"})
    for entry in paths:
        if entry["failed"] and entry["active"] == 0:
            affected.append({"name": entry["map"], "classification": CLASS_CRITICAL,
                             "reason_key": "multipathNoPath"})
        elif entry["failed"]:
            affected.append({"name": entry["map"],
                             "detail": f"{entry['active']}/{entry['active'] + entry['failed']}",
                             "classification": CLASS_WARNING,
                             "reason_key": "multipathPathDown"})

    if not affected:
        return {"classification": CLASS_CONFORMANT, "summary_key": "intact",
                "summary_params": {"total": str(len(arrays) + len(paths))},
                "observations": arrays + paths, "evidence": evidence}
    return {"summary_key": "degraded",
            "summary_params": {"count": str(len(affected)),
                               "total": str(len(arrays) + len(paths))},
            "affected": affected, "observations": arrays + paths,
            "evidence": evidence}


@register("system.ha_state", AREA_SYSTEM, "CRITICAL", budget=25)
def _ha_state(ctx):
    """Whether HA could actually move the workloads it promises to move.

    Quorum belongs to the cluster check and is not graded again here.
    What this adds is the half quorum does not answer: a resource
    manager that is idle or gone cannot start anything anywhere, a
    service left in an error state has stopped being managed, and both
    look like a healthy cluster from every other angle. A node with no
    HA resources declared has nothing to move.
    """
    if not Path("/etc/pve/ha/resources.cfg").exists():
        return None
    rc, out = ctx.run(["ha-manager", "status"], timeout=25, allowed_codes=(0, 1, 2))
    if rc not in (0, 1, 2) or not (out or "").strip():
        return _unverified(out or "ha-manager reported nothing")

    quorum, master, managers, services = "", "", [], []
    for line in (out or "").splitlines():
        line = line.strip()
        if line.startswith("quorum "):
            quorum = line.split(None, 1)[1]
        elif line.startswith("master "):
            master = line.split(None, 1)[1]
        elif line.startswith("lrm "):
            body = line.split(None, 1)[1]
            name = body.split()[0]
            state = re.search(r"\((\w+)", body)
            managers.append({"node": name, "state": state.group(1) if state else ""})
        elif line.startswith("service "):
            body = line.split(None, 1)[1]
            name = body.split()[0]
            state = re.search(r"\(([^,)]+),\s*([^)]+)\)", body)
            services.append({"service": name,
                             "node": state.group(1).strip() if state else "",
                             "state": state.group(2).strip() if state else body})

    if not services and not managers:
        return None

    evidence = json.dumps({"quorum": quorum, "master": master,
                           "resource_managers": managers, "services": services},
                          indent=2, ensure_ascii=False)
    evidence += ("\nRead from `ha-manager status`. Quorum is reported by the "
                 "cluster check and is not graded twice; it appears here as "
                 "context. No service is started, stopped or migrated, and "
                 "whether a migration would succeed is not established.")

    affected = []
    if not master:
        # Without a manager nothing decides where a service should run.
        affected.append({"name": "master", "classification": CLASS_CRITICAL,
                         "reason_key": "haNoMaster"})
    for entry in services:
        state = entry["state"].lower()
        if "error" in state or "fence" in state:
            affected.append({"name": entry["service"], "detail": entry["state"],
                             "classification": CLASS_CRITICAL,
                             "reason_key": "haServiceError"})
        elif state.startswith("request") or "queued" in state:
            affected.append({"name": entry["service"], "detail": entry["state"],
                             "classification": CLASS_OBSERVATION,
                             "reason_key": "haServiceTransitioning"})
    for manager in managers:
        # `idle` is the resting state of a node holding no service;
        # anything that is neither active nor idle cannot take one.
        if manager["state"] not in ("active", "idle", ""):
            affected.append({"name": manager["node"], "detail": manager["state"],
                             "classification": CLASS_WARNING,
                             "reason_key": "haManagerNotReady"})

    if not affected:
        return {"classification": CLASS_CONFORMANT, "summary_key": "managed",
                "summary_params": {"total": str(len(services)),
                                   "nodes": str(len(managers))},
                "observations": services, "evidence": evidence}
    return {"summary_key": "attention",
            "summary_params": {"count": str(len(affected)),
                               "total": str(len(services))},
            "affected": affected, "observations": services, "evidence": evidence}
