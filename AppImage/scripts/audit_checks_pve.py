"""Proxmox-specific checks for Audit & Report.

Importing this module registers its checks. Everything here reads the
host and reports; nothing modifies it.

The checks are deliberately about configuration and posture rather than
transient load. A condition that resolves on its own as usage drops
belongs to the health monitor, which keeps its own catalogue and remains
the source of notifications.
"""
from __future__ import annotations

import re
from pathlib import Path

import audit_store
from audit_checks import (
    AREA_BACKUP, AREA_GUESTS, AREA_SECURITY, AREA_STORAGE, AREA_SYSTEM,
    register,
)

FAIL = audit_store.STATE_FAIL
WARN = audit_store.STATE_WARN
PASS = audit_store.STATE_PASS
NA = audit_store.STATE_NOT_APPLICABLE


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
    for line in text.splitlines():
        if not line.strip():
            continue
        header = re.match(r"^vzdump:\s*(\S+)", line)
        if header:
            current = {"id": header.group(1)}
            jobs.append(current)
            continue
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
    """Guests that no enabled backup job includes.

    A job selects guests by enumerating them (``vmid``), by taking every
    guest (``all 1``), or by pool, and may subtract an ``exclude`` list.
    A job carrying ``enabled 0`` selects nothing: it is defined but never
    runs, which is precisely the situation this check exists to surface,
    since a disabled job looks like coverage in the interface.
    """
    guests = {}
    for vmid in ctx.lxc_configs:
        guests[vmid] = "lxc"
    for vmid in ctx.qemu_configs:
        guests[vmid] = "qemu"
    if not guests:
        return None

    jobs = _parse_vzdump_jobs(ctx.vzdump_jobs)
    if not jobs:
        return {
            "state": FAIL,
            "summary_key": "noJobs",
            "affected": [{"vmid": v, "type": t} for v, t in sorted(guests.items())],
            "evidence": "no job definitions found in /etc/pve/jobs.cfg "
                        "or /etc/vzdump.cron",
        }

    pools = _pool_members(ctx.pve_user_cfg)
    covered: set[int] = set()
    considered: list[str] = []
    skipped: list[str] = []

    for job in jobs:
        if job.get("enabled", "1").strip() == "0":
            skipped.append(f"{job['id']} (disabled)")
            continue
        excluded = {int(x) for x in re.findall(r"\d+", job.get("exclude", ""))}
        selected: set[int] = set()
        if job.get("all", "0").strip() == "1":
            selected = set(guests)
        else:
            selected |= {int(x) for x in re.findall(r"\d+", job.get("vmid", ""))}
            for pool in re.split(r"[,\s]+", job.get("pool", "").strip()):
                if pool:
                    selected |= pools.get(pool, set())
        covered |= selected - excluded
        considered.append(f"{job['id']} -> {sorted(selected - excluded) or 'nothing'}")

    evidence = "enabled jobs:\n  " + ("\n  ".join(considered) or "(none)")
    if skipped:
        evidence += "\nignored jobs:\n  " + "\n  ".join(skipped)

    uncovered = sorted(set(guests) - covered)
    if not uncovered:
        return {
            "state": PASS,
            "summary_key": "covered",
            "summary_params": {"total": len(guests)},
            "evidence": evidence,
        }
    return {
        "state": FAIL,
        "summary_key": "uncovered",
        "summary_params": {"count": len(uncovered), "total": len(guests)},
        "affected": [{"vmid": v, "type": guests[v]} for v in uncovered],
        "evidence": evidence + f"\n\nuncovered: {uncovered}",
    }


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@register("system.pending_reboot", AREA_SYSTEM, "WARNING")
def _pending_reboot(ctx):
    """Kernel or packages installed but not yet in effect."""
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

    if not marker.exists():
        return {
            "state": PASS,
            "summary_key": "none",
            "evidence": f"running kernel: {running}",
        }
    return {
        "state": WARN,
        "summary_key": "pending",
        "affected": [{"package": p} for p in packages.splitlines() if p],
        "evidence": f"running kernel: {running}\n"
                    f"packages requesting a restart:\n{packages or '(not reported)'}",
    }


@register("system.enterprise_repo_without_subscription", AREA_SYSTEM, "WARNING")
def _enterprise_repo(ctx):
    """Enterprise repository enabled on a host without a subscription.

    The combination leaves ``apt update`` failing on every run, which
    tends to be misread as a broken host rather than a licensing state.
    """
    enabled = []
    for path, text in ctx.apt_sources.items():
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if "enterprise.proxmox.com" in stripped:
                enabled.append((path, stripped))
    if not enabled:
        return {
            "state": PASS,
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

    if status in ("active", "new"):
        return {
            "state": PASS,
            "summary_key": "subscribed",
            "evidence": evidence,
        }
    return {
        "state": WARN,
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
    configs = ctx.lxc_configs
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
            "state": PASS,
            "summary_key": "allUnprivileged",
            "summary_params": {"total": len(configs)},
        }
    listed = ", ".join(
        f"{c['vmid']}{' (' + c['name'] + ')' if c['name'] else ''}"
        for c in privileged
    )
    return {
        "state": WARN,
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
    configs = ctx.qemu_configs
    if not configs:
        return None

    missing = []
    for vmid, text in sorted(configs.items()):
        if not re.search(r"^agent:\s*(1|enabled=1)", text, re.M):
            name = ""
            m = re.search(r"^name:\s*(\S+)", text, re.M)
            if m:
                name = m.group(1)
            missing.append({"vmid": vmid, "name": name})

    if not missing:
        return {
            "state": PASS,
            "summary_key": "allHaveAgent",
            "summary_params": {"total": len(configs)},
        }
    listed = ", ".join(
        f"{v['vmid']}{' (' + v['name'] + ')' if v['name'] else ''}"
        for v in missing
    )
    return {
        "state": WARN,
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
    """Proxmox firewall enabled at datacenter and node level.

    Both levels matter: the node rules are not applied while the
    datacenter switch is off, so a node that looks configured can still
    be filtering nothing.
    """
    def enabled_in(path: Path) -> tuple[bool, str]:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return False, f"{path}: not present"
        for line in text.splitlines():
            if re.match(r"^\s*enable:\s*1\s*$", line):
                return True, f"{path}: enable: 1"
        return False, f"{path}: enable not set to 1"

    dc_on, dc_note = enabled_in(Path("/etc/pve/firewall/cluster.fw"))
    try:
        node = Path("/etc/hostname").read_text().strip()
    except OSError:
        node = ""
    node_path = Path(f"/etc/pve/nodes/{node}/host.fw") if node else None
    node_on, node_note = (False, "node firewall file not resolved")
    if node_path:
        node_on, node_note = enabled_in(node_path)

    evidence = f"{dc_note}\n{node_note}"
    if dc_on and node_on:
        return {
            "state": PASS,
            "summary_key": "bothEnabled",
            "evidence": evidence,
        }
    if not dc_on:
        return {
            "state": WARN,
            "summary_key": "datacenterOff",
            "evidence": evidence,
        }
    return {
        "state": WARN,
        "summary_key": "nodeOff",
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

@register("storage.orphaned_volumes", AREA_STORAGE, "WARNING")
def _orphaned_volumes(ctx):
    """Disk images that no guest configuration references.

    A volume survives when a guest is removed without its disks, or when
    a restore leaves the previous copy behind. Nothing reports it and it
    keeps occupying the pool.

    Only storage that is not shared is examined. On shared storage a
    volume may belong to a guest running on another node, which this node
    cannot see, so flagging it would be wrong rather than merely noisy.
    """
    known = set(ctx.lxc_configs) | set(ctx.qemu_configs)
    if not known:
        return None

    candidates = [
        s for s in ctx.storages
        if str(s.get("shared", "0")).strip() != "1"
        and any(c in (s.get("content") or "") for c in ("images", "rootdir"))
    ]
    if not candidates:
        return None

    orphans: list[dict] = []
    inspected: list[str] = []
    for storage in candidates:
        sid = storage["id"]
        rc, out = ctx.run(["pvesm", "list", sid], timeout=15)
        if rc != 0:
            inspected.append(f"{sid}: not readable")
            continue
        count = 0
        for line in (out or "").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 5:
                continue
            volid, vmid_raw = fields[0], fields[-1]
            if not vmid_raw.isdigit():
                continue
            count += 1
            vmid = int(vmid_raw)
            if vmid not in known:
                orphans.append({"volume": volid, "vmid": vmid})
        inspected.append(f"{sid}: {count} volume(s)")

    shared_skipped = [
        s["id"] for s in ctx.storages
        if str(s.get("shared", "0")).strip() == "1"
    ]
    evidence = "inspected:\n  " + "\n  ".join(inspected)
    if shared_skipped:
        evidence += ("\nskipped as shared (ownership not resolvable from this "
                     "node):\n  " + ", ".join(shared_skipped))

    if not orphans:
        return {
            "state": PASS,
            "summary_key": "none",
            "evidence": evidence,
        }
    return {
        "state": WARN,
        "summary_key": "found",
        "summary_params": {"count": len(orphans)},
        "affected": orphans,
        "evidence": evidence + "\n\norphans:\n  " + "\n  ".join(
            f"{o['volume']} (no config for {o['vmid']})" for o in orphans),
    }
