"""Structural inventory for Audit & Report.

Composes what the node is, what it holds and how those pieces connect,
from the collectors the Monitor already runs. Nothing here probes the
host: every section reads material that exists for another purpose.

The value of an inventory is not the lists but the relations between
them. Enumerating interfaces and enumerating guests does not say which
path a guest's traffic takes to the wire, nor which device a virtual
disk actually lives on. Those chains are resolved here:

  guest -> disk -> storage -> backing device
  guest -> interface -> bridge -> bond -> physical NIC
  guest -> backup job -> destination
  guest -> passthrough device -> IOMMU group -> controller
  node -> uplink -> measured latency to gateway and to the internet

Sections degrade independently. A source that cannot be read leaves its
section marked unavailable with the reason, rather than dropping the
whole inventory or presenting a gap as an empty result.
"""
from __future__ import annotations

import copy
import re
import sys
import time
from typing import Any, Optional

SCHEMA_VERSION = 2

# Disk entries in a guest configuration: rootfs and mpN for containers,
# the bus-prefixed keys for virtual machines.
_DISK_KEYS = re.compile(
    r"^(rootfs|mp\d+|scsi\d+|virtio\d+|sata\d+|ide\d+|efidisk\d+|tpmstate\d+):",
    re.M)


def _kv(text: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def _parse_options(value: str) -> dict[str, str]:
    """Split a Proxmox option string into its comma-separated pairs."""
    out: dict[str, str] = {}
    for part in value.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _guest_disks(text: str) -> list[dict[str, Any]]:
    """Disks declared by a guest, resolved to their storage.

    A volume reads as ``storage:volume,option=value``. Anything without
    that shape is a passthrough or a raw device path and is reported as
    such rather than being attributed to a storage that does not own it.
    """
    disks = []
    for line in text.splitlines():
        m = _DISK_KEYS.match(line)
        if not m:
            continue
        key = m.group(1)
        value = line.split(":", 1)[1].strip()
        head = value.split(",", 1)[0]
        options = _parse_options(value)
        entry: dict[str, Any] = {"slot": key, "size": options.get("size", "")}
        if ":" in head and not head.startswith("/"):
            storage, volume = head.split(":", 1)
            entry.update(storage=storage, volume=volume)
        else:
            entry.update(storage=None, volume=head, passthrough=True)
        disks.append(entry)
    return disks


def _guest_interfaces(text: str) -> list[dict[str, Any]]:
    """Network devices declared by a guest, with the bridge each uses."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^(net\d+):\s*(.+)$", line)
        if not m:
            continue
        options = _parse_options(m.group(2))
        out.append({
            "slot": m.group(1),
            "name": options.get("name", ""),
            "bridge": options.get("bridge", ""),
            "mac": options.get("hwaddr") or options.get("macaddr", ""),
            "vlan": options.get("tag", ""),
            "model": next((p for p in m.group(2).split(",") if "=" not in p), ""),
        })
    return out


def _network_topology() -> Optional[dict[str, Any]]:
    """Physical path from each bridge to the wire.

    Built from the Monitor's own per-interface resolvers rather than from
    the aggregate network payload: ``get_bridge_info`` already reports a
    bridge's uplink and, when that uplink is a bond, its member
    interfaces. Absent those resolvers the chain is left unresolved
    rather than guessed.
    """
    server = sys.modules.get("flask_server") or sys.modules.get("__main__")
    bridge_info = getattr(server, "get_bridge_info", None)
    bond_info = getattr(server, "get_bond_info", None)
    if not callable(bridge_info):
        return None

    try:
        from pathlib import Path
        # fwbr* bridges are created by Proxmox per guest interface to
        # attach its firewall. They are plumbing rather than part of the
        # host's configured topology, so the inventory omits them.
        names = sorted(p.name for p in Path("/sys/class/net").iterdir()
                       if (p / "bridge").is_dir()
                       and not p.name.startswith("fwbr"))
    except OSError:
        return None

    bridges: dict[str, Any] = {}
    bonds: dict[str, Any] = {}
    for name in names:
        try:
            info = copy.deepcopy(bridge_info(name))
        except Exception:
            continue
        if not isinstance(info, dict):
            continue
        uplink = info.get("physical_interface")
        vlan = info.get("vlan_interface")
        chain: list[dict[str, str]] = []
        if uplink:
            slaves = info.get("bond_slaves") or []
            if slaves:
                mode = ""
                if callable(bond_info):
                    try:
                        detail = bond_info(uplink) or {}
                        mode = detail.get("mode_detail") or detail.get("mode", "")
                        bonds[uplink] = detail
                    except Exception:
                        mode = ""
                chain.append({"kind": "bond", "id": uplink, "mode": mode})
                chain.extend({"kind": "nic", "id": s} for s in slaves)
            else:
                chain.append({"kind": "nic", "id": uplink})
        bridges[name] = {
            "parent": uplink,
            "vlan_interface": vlan,
            # Guest taps are excluded upstream, so members here are the
            # bridge's own ports rather than every attached guest.
            "members": info.get("members") or [],
            "uplink": chain,
        }
    return {"bridges": bridges, "bonds": bonds}


def _latency(ctx) -> Optional[dict[str, Any]]:
    """Network latency over the last day, from the Monitor's own history.

    The Monitor samples the gateway and two public resolvers
    continuously. A report that describes a node's network without
    saying how it behaves is describing the wiring, not the network, so
    the measurements already on disk are carried here. Nothing is probed:
    the samples exist whether or not anyone asks for them.
    """
    server = sys.modules.get("flask_server") or sys.modules.get("__main__")
    history = getattr(server, "get_latency_history", None)
    if not callable(history):
        return None

    targets = []
    for name in ("gateway", "cloudflare", "google"):
        try:
            result = history(name, "day") or {}
        except Exception:
            continue
        stats = result.get("stats") or {}
        samples = result.get("data") or []
        if not samples:
            continue
        losses = [s.get("packet_loss") for s in samples
                  if isinstance(s.get("packet_loss"), (int, float))]
        targets.append({
            "target": name,
            "samples": len(samples),
            "min_ms": stats.get("min"),
            "avg_ms": stats.get("avg"),
            "max_ms": stats.get("max"),
            "current_ms": stats.get("current"),
            "packet_loss": round(sum(losses) / len(losses), 2) if losses else None,
            # Kept for the chart: one point per sample, oldest first.
            # The peak travels with the average because a chart of
            # averages alone contradicts the maximum in the table.
            "series": [{"t": s.get("timestamp"), "v": s.get("value"),
                        "max": s.get("max")}
                       for s in samples if s.get("value") is not None],
        })
    if not targets:
        return None
    return {"window": "day", "targets": targets}


def _backup_map(ctx) -> dict[int, list[dict[str, str]]]:
    """Which enabled backup job selects each guest, and where it writes."""
    import audit_checks_pve as pve

    guests = set(ctx.lxc_configs) | set(ctx.qemu_configs)
    pools = pve._pool_members(ctx.pve_user_cfg)
    out: dict[int, list[dict[str, str]]] = {}
    for job in pve._parse_vzdump_jobs(ctx.vzdump_jobs):
        if job.get("enabled", "1").strip() == "0":
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
        entry = {"job": job["id"], "storage": job.get("storage", ""),
                 "schedule": job.get("schedule", ""),
                 "retention": job.get("prune-backups") or job.get("maxfiles", "")}
        for vmid in selected - excluded:
            out.setdefault(vmid, []).append(entry)
    return out


def _identity(ctx) -> dict[str, Any]:
    rc, version = ctx.run(["pveversion"], timeout=10)
    rc2, kernel = ctx.run(["uname", "-r"], timeout=10)
    rc3, sub = ctx.run(["pvesubscription", "get"], timeout=10)
    status = ""
    for line in (sub or "").splitlines():
        if line.lower().startswith("status:"):
            status = line.split(":", 1)[1].strip()
            break
    cluster = ""
    try:
        from pathlib import Path
        corosync = Path("/etc/corosync/corosync.conf")
        if corosync.exists():
            m = re.search(r"cluster_name:\s*(\S+)",
                          corosync.read_text(errors="replace"))
            cluster = m.group(1) if m else "unnamed"
    except OSError:
        cluster = ""
    return {
        "node": ctx.node,
        "pve_version": (version or "").strip().splitlines()[0] if version else "",
        "kernel": (kernel or "").strip(),
        "subscription": status or "unknown",
        "cluster": cluster or None,
    }


def _storages(ctx) -> list[dict[str, Any]]:
    out = []
    for storage in ctx.storages:
        out.append({
            "id": storage.get("id"),
            "type": storage.get("type"),
            "content": storage.get("content", ""),
            "shared": str(storage.get("shared", "0")).strip() == "1",
            "path": storage.get("path") or storage.get("export") or "",
            "server": storage.get("server", ""),
        })
    return sorted(out, key=lambda s: s["id"] or "")


def _guests(ctx, topology, backups) -> list[dict[str, Any]]:
    """Every local guest with its disks, interfaces and protection resolved."""
    entries = []
    for kind, configs in (("lxc", ctx.lxc_configs), ("qemu", ctx.qemu_configs)):
        for vmid, text in configs.items():
            interfaces = _guest_interfaces(text)
            for nic in interfaces:
                if topology is None:
                    # Distinguish a bridge with no uplink from one whose
                    # path could not be read: the first is a fact about
                    # the host, the second is a gap in this inventory.
                    nic["uplink"] = None
                else:
                    bridge = topology["bridges"].get(nic["bridge"])
                    nic["uplink"] = bridge["uplink"] if bridge else []
            entries.append({
                "vmid": vmid,
                "type": kind,
                "name": _kv(text, "hostname") or _kv(text, "name"),
                "cores": _kv(text, "cores"),
                "memory": _kv(text, "memory"),
                "ostype": _kv(text, "ostype"),
                "onboot": _kv(text, "onboot") == "1",
                "tags": _kv(text, "tags"),
                "protected": _kv(text, "protection") == "1",
                "unprivileged": _kv(text, "unprivileged") == "1" if kind == "lxc" else None,
                "features": _kv(text, "features") if kind == "lxc" else None,
                "agent": bool(_kv(text, "agent")) if kind == "qemu" else None,
                "cpu": _kv(text, "cpu") if kind == "qemu" else None,
                "disks": _guest_disks(text),
                "interfaces": interfaces,
                "backups": backups.get(vmid, []),
            })
    return sorted(entries, key=lambda g: g["vmid"])


def collect(ctx, sections: Optional[tuple] = None) -> dict[str, Any]:
    """Assemble the inventory, keeping each section independent.

    A section that raises is recorded with its error so the rest of the
    document still describes what could be read. An inventory that fails
    as a whole because one source was unavailable is less useful than one
    that says which part is missing.
    """
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}

    wanted = None if sections is None else set(sections)

    def section(name, producer):
        # A section the profile did not ask for is absent rather than
        # empty, so a reader never takes an omission for a finding.
        if wanted is not None and name not in wanted:
            return
        try:
            out[name] = producer()
        except Exception as exc:
            out[name] = None
            errors[name] = f"{type(exc).__name__}: {exc}"

    topology = None
    try:
        topology = _network_topology()
        if topology is None:
            errors["network"] = ("the Monitor's network view is not reachable "
                                 "from this process, so bridge uplinks are "
                                 "unresolved")
    except Exception as exc:
        errors["network"] = f"{type(exc).__name__}: {exc}"

    backups: dict[int, list] = {}
    try:
        backups = _backup_map(ctx)
    except Exception as exc:
        errors["backup_map"] = f"{type(exc).__name__}: {exc}"

    section("identity", lambda: _identity(ctx))
    section("hardware", lambda: _hardware(ctx))
    section("cluster", lambda: _cluster(ctx))
    section("storages", lambda: _storages(ctx))
    section("guests", lambda: _guests(ctx, topology, backups))
    section("passthrough", lambda: _passthrough(ctx))
    section("applications", lambda: _applications(ctx))
    section("custom_links", _custom_links)
    section("proxmenux", lambda: _proxmenux(ctx))
    section("latency", lambda: _latency(ctx))
    if wanted is None or "network" in wanted:
        out["network"] = topology

    return {
        "schema_version": SCHEMA_VERSION,
        "collected_at": int(time.time()),
        "node": ctx.node,
        "sections": out,
        # Named so a reader can tell an empty section from an unread one.
        "unavailable": errors,
    }


# ---------------------------------------------------------------------------
# Passthrough, applications and hardware
# ---------------------------------------------------------------------------

def _iommu_groups() -> dict[str, str]:
    """Map each PCI address to the IOMMU group that contains it.

    A device can only be handed to a guest together with everything else
    in its group, so the group is what determines whether a passthrough
    is possible at all.
    """
    from pathlib import Path
    out: dict[str, str] = {}
    base = Path("/sys/kernel/iommu_groups")
    if not base.is_dir():
        return out
    for group in base.iterdir():
        devices = group / "devices"
        if not devices.is_dir():
            continue
        for device in devices.iterdir():
            out[device.name] = group.name
    return out


def _passthrough(ctx) -> list[dict[str, Any]]:
    """PCI devices assigned to a guest, with their IOMMU group.

    ``hostpci`` may name a function (``0000:03:00.0``) or a whole device
    (``0000:03:00``). Both are reported as written and resolved against
    the groups, so a reader sees what was configured rather than a
    normalised form that no longer matches the configuration.
    """
    groups = _iommu_groups()
    out = []
    for vmid, text in sorted(ctx.qemu_configs.items()):
        name = _kv(text, "name")
        for line in text.splitlines():
            m = re.match(r"^(hostpci\d+):\s*(.+)$", line)
            if not m:
                continue
            value = m.group(2)
            address = value.split(",", 1)[0].strip()
            # A device written without its function covers every function
            # of that device, so the group is looked up through them.
            candidates = ([address] if address.count(".") else
                          [f"{address}.{fn}" for fn in range(8)])
            found = {groups[c] for c in candidates if c in groups}
            out.append({
                "vmid": vmid,
                "guest": name,
                "slot": m.group(1),
                "address": address,
                "options": _parse_options(value),
                "iommu_groups": sorted(found) or None,
                "shared_group_devices": sorted(
                    d for d, gid in groups.items()
                    if gid in found and d not in candidates) or [],
            })
    return out


def _applications(ctx) -> list[dict[str, Any]]:
    """Applications registered inside each container and their web links.

    Read from the sidecars the App tab maintains, which is where a
    container's real purpose is recorded; the configuration alone only
    says how much memory it has.
    """
    import json as _json
    from pathlib import Path
    base = Path("/etc/proxmenux/apps")
    out = []
    if not base.is_dir():
        return out
    for path in sorted(base.glob("*.json")):
        try:
            data = _json.loads(path.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        vmid = data.get("vmid")
        for app in data.get("apps", []) or []:
            # Detection results live under `state`, separate from the
            # registration itself, and carry the moment they were taken.
            # A version that could not be detected is stored as null, so
            # the value is coerced rather than defaulted: a key present
            # with no value would otherwise pass a default straight through.
            state = app.get("state") or {}
            out.append({
                "vmid": vmid,
                "name": app.get("name") or "",
                "slug": app.get("helper_slug") or app.get("slug") or "",
                "installed_via": app.get("installed_via") or "",
                "version": state.get("installed_version") or "",
                "available": state.get("latest_version") or "",
                "update_available": bool(state.get("update_available")),
                "checked_at": state.get("checked_at") or "",
                "ports": [
                    {"port": p.get("port"), "path": p.get("web_path", ""),
                     "scheme": p.get("scheme", ""),
                     "category": p.get("category", ""),
                     "url": p.get("custom_url", "")}
                    for p in (app.get("ports") or [])
                ],
            })
    return out


def _custom_links() -> list[dict[str, Any]]:
    """User-defined web links, including those pointing inside guests."""
    import json as _json
    from pathlib import Path
    try:
        data = _json.loads(
            Path("/etc/proxmenux/custom_links.json").read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    entries = data if isinstance(data, list) else data.get("links", [])
    return [{"name": e.get("name", ""), "url": e.get("url", ""),
             "category": e.get("category", ""), "vmid": e.get("vmid")}
            for e in entries if isinstance(e, dict)]


def _memory_modules(ctx) -> dict[str, Any]:
    """Populated and empty slots, so remaining capacity is visible.

    dmidecode reports every slot the board has; a slot without a module
    carries the literal "No Module Installed" as its size.
    """
    rc, out = ctx.run(["dmidecode", "-t", "memory"], timeout=15)
    devices: list[dict[str, str]] = []
    current: Optional[dict[str, str]] = None
    for line in (out or "").splitlines():
        stripped = line.strip()
        if stripped == "Memory Device":
            current = {}
            devices.append(current)
            continue
        if current is None or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        current[key.strip()] = value.strip()

    modules, empty = [], 0
    for dev in devices:
        size = dev.get("Size", "")
        if not size or size.lower().startswith("no module"):
            empty += 1
            continue
        modules.append({
            "locator": dev.get("Locator", ""),
            "size": size,
            "type": dev.get("Type", ""),
            "form_factor": dev.get("Form Factor", ""),
            "speed": dev.get("Configured Memory Speed") or dev.get("Speed", ""),
            "manufacturer": dev.get("Manufacturer", ""),
            "part_number": dev.get("Part Number", ""),
        })
    return {"slots": len(devices) or None, "populated": len(modules),
            "empty": empty, "modules": modules}


def _lsblk_pairs(ctx) -> list[dict[str, str]]:
    """lsblk key="value" output; model strings contain spaces."""
    rc, out = ctx.run(
        ["lsblk", "-dn", "-P", "-b", "-o",
         "NAME,MODEL,SERIAL,SIZE,ROTA,TRAN,TYPE"], timeout=15)
    rows = []
    for line in (out or "").splitlines():
        fields = dict(re.findall(r'(\w+)="([^"]*)"', line))
        # zd* are ZFS volumes: guest disks the kernel exposes as block
        # devices. They are not hardware and report no SMART.
        if fields.get("TYPE") == "disk" and not fields.get("NAME", "").startswith("zd"):
            rows.append(fields)
    return rows


def _disk_observations() -> dict[str, list[dict[str, Any]]]:
    """Recorded disk events, keyed by device.

    The Monitor keeps these because a transient error that clears is
    still part of a disk's history: SMART reports the present state,
    the observation log reports what happened. A report that only shows
    the present state hides the pattern that precedes a failure.
    """
    server = sys.modules.get("flask_server") or sys.modules.get("__main__")
    store = getattr(server, "health_persistence", None)
    getter = getattr(store, "get_disk_observations", None)
    if getter is None:
        return {}
    try:
        records = getter() or []
    except Exception:
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        device = (record.get("device_name") or "").replace("/dev/", "")
        if not device:
            continue
        grouped.setdefault(device, []).append({
            "type": record.get("error_type", ""),
            "severity": record.get("severity", ""),
            "count": record.get("occurrence_count", 0),
            "first_seen": record.get("first_occurrence"),
            "last_seen": record.get("last_occurrence"),
            "message": (record.get("raw_message") or "")[:400],
        })
    for entries in grouped.values():
        entries.sort(key=lambda e: e.get("last_seen") or 0, reverse=True)
    return grouped


def _physical_disks(ctx) -> list[dict[str, Any]]:
    observations = _disk_observations()
    # The SMART cache is keyed by device, each entry a (collected_at, data)
    # pair as the Monitor stores it.
    smart = {}
    cached = (getattr(ctx, "monitor_snapshot", None) or {}).get("smart") or {}
    for device, value in cached.items():
        data = value[1] if isinstance(value, (list, tuple)) and len(value) == 2 else value
        if isinstance(data, dict):
            smart[str(device).replace("/dev/", "")] = data

    disks = []
    for row in _lsblk_pairs(ctx):
        size = row.get("SIZE", "")
        name = row.get("NAME", "")
        health = smart.get(name) or {}
        disks.append({
            "name": name,
            "model": (row.get("MODEL") or "").strip(),
            "serial": (row.get("SERIAL") or "").strip(),
            "size_bytes": int(size) if size.isdigit() else None,
            "rotational": row.get("ROTA") == "1",
            "bus": (row.get("TRAN") or "").strip(),
            "health": health.get("smart_status"),
            "temperature": health.get("temperature"),
            "power_on_hours": health.get("power_on_hours"),
            "observations": observations.get(name, []),
        })
    return sorted(disks, key=lambda d: d["name"])


def _network_adapters() -> list[dict[str, Any]]:
    """Physical adapters only: an interface backed by a real device."""
    from pathlib import Path as _Path

    def read(path):
        try:
            return _Path(path).read_text(errors="replace").strip()
        except OSError:
            return ""

    adapters = []
    try:
        entries = sorted(_Path("/sys/class/net").iterdir())
    except OSError:
        return adapters
    for iface in entries:
        device = iface / "device"
        if not device.exists():
            continue
        speed = read(iface / "speed")
        driver = ""
        try:
            driver = (device / "driver").resolve().name
        except OSError:
            pass
        pci = ""
        try:
            pci = device.resolve().name
        except OSError:
            pass
        adapters.append({
            "name": iface.name,
            "mac": read(iface / "address"),
            "state": read(iface / "operstate"),
            # An interface that is down reports -1, which is not a speed.
            "speed_mbps": int(speed) if speed.lstrip("-").isdigit()
                          and int(speed) > 0 else None,
            "driver": driver,
            "pci": pci,
        })
    return adapters


# Device classes worth naming in a report: what moves the storage and
# what a guest could be given directly.
_CONTROLLER_CLASSES = (
    "RAID bus controller", "Serial Attached SCSI controller",
    "SATA controller", "SCSI storage controller",
    "Non-Volatile memory controller", "Fibre Channel",
    "VGA compatible controller", "3D controller", "Display controller",
    "Ethernet controller", "Network controller",
)


def _controllers(ctx) -> list[dict[str, Any]]:
    rc, out = ctx.run(["lspci", "-D"], timeout=15)
    devices = []
    for line in (out or "").splitlines():
        if " " not in line:
            continue
        slot, rest = line.split(" ", 1)
        if ":" not in rest:
            continue
        klass, name = rest.split(":", 1)
        klass = klass.strip()
        if klass in _CONTROLLER_CLASSES:
            devices.append({"slot": slot, "class": klass, "name": name.strip()})
    return devices


def _cluster(ctx) -> Optional[dict[str, Any]]:
    """The cluster this node belongs to, or None when it stands alone.

    Membership is read from corosync's own configuration; quorum state
    comes from pvecm, which reports what the node currently sees.
    """
    from pathlib import Path as _Path

    conf = _Path("/etc/pve/corosync.conf")
    if not conf.exists():
        conf = _Path("/etc/corosync/corosync.conf")
    if not conf.exists():
        return None
    try:
        text = conf.read_text(errors="replace")
    except OSError:
        return None

    name = ""
    m = re.search(r"cluster_name:\s*(\S+)", text)
    if m:
        name = m.group(1)

    nodes = []
    for block in re.findall(r"node\s*{([^}]*)}", text):
        entry = {
            "name": _kv(block, r"\s*name") or _kv(block, r"\s*ring0_addr"),
            "nodeid": _kv(block, r"\s*nodeid"),
            "ring0_addr": _kv(block, r"\s*ring0_addr"),
            "ring1_addr": _kv(block, r"\s*ring1_addr") or None,
        }
        entry["local"] = entry["name"] == ctx.node
        nodes.append(entry)

    quorate, expected, total = None, None, None
    rc, status = ctx.run(["pvecm", "status"], timeout=15, allowed_codes=(0, 2))
    for line in (status or "").splitlines():
        low = line.lower()
        if low.startswith("quorate:"):
            quorate = line.split(":", 1)[1].strip().lower() == "yes"
        elif low.startswith("expected votes:"):
            expected = line.split(":", 1)[1].strip()
        elif low.startswith("total votes:"):
            total = line.split(":", 1)[1].strip()

    # pvecm lists the members it currently sees; a configured node absent
    # from that list is configured but not reachable right now.
    online = set()
    rc2, members = ctx.run(["pvecm", "nodes"], timeout=15, allowed_codes=(0, 2))
    for line in (members or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit():
            # The local node is marked with a trailing "(local)" token.
            online.add(parts[-2] if parts[-1] == "(local)" else parts[-1])
    if online:
        for node in nodes:
            node["online"] = node["name"] in online

    return {"name": name or "unnamed", "nodes": sorted(nodes, key=lambda n: n["name"]),
            "quorate": quorate, "expected_votes": expected, "total_votes": total,
            "links": 2 if any(n.get("ring1_addr") for n in nodes) else 1}


def _hardware(ctx) -> dict[str, Any]:
    """System identity and processor, from data the host already exposes."""
    def dmi(field):
        rc, out = ctx.run(["dmidecode", "-s", field], timeout=10)
        value = (out or "").strip().splitlines()
        value = value[-1].strip() if value else ""
        # dmidecode returns these placeholders when a board ships without
        # the field populated; they are not identities.
        return "" if value.lower() in ("default string", "to be filled by o.e.m.",
                                       "not specified", "unknown") else value

    cpu_model, sockets, cores, threads = "", 0, 0, 0
    physical: set[str] = set()
    rc, cpuinfo = ctx.run(["cat", "/proc/cpuinfo"], timeout=10)
    for line in (cpuinfo or "").splitlines():
        if line.startswith("model name") and not cpu_model:
            cpu_model = line.split(":", 1)[1].strip()
        elif line.startswith("physical id"):
            physical.add(line.split(":", 1)[1].strip())
        elif line.startswith("processor"):
            threads += 1
        elif line.startswith("cpu cores") and not cores:
            cores = int(line.split(":", 1)[1].strip() or 0)
    sockets = len(physical) or 1

    virt = ""
    if cpuinfo:
        if " vmx" in cpuinfo:
            virt = "vmx"
        elif " svm" in cpuinfo:
            virt = "svm"

    return {
        "system": {"manufacturer": dmi("system-manufacturer"),
                   "product": dmi("system-product-name"),
                   "serial": dmi("system-serial-number")},
        "board": {"manufacturer": dmi("baseboard-manufacturer"),
                  "product": dmi("baseboard-product-name")},
        "bios": {"vendor": dmi("bios-vendor"), "version": dmi("bios-version"),
                 "date": dmi("bios-release-date")},
        "cpu": {"model": cpu_model, "sockets": sockets,
                "cores_per_socket": cores, "threads": threads,
                "virtualisation": virt or None},
        "memory_bytes": _host_memory(ctx),
        "memory": _memory_modules(ctx),
        "disks": _physical_disks(ctx),
        "adapters": _network_adapters(),
        "controllers": _controllers(ctx),
        "iommu_groups": len(set(_iommu_groups().values())) or None,
    }


def _host_memory(ctx) -> int:
    rc, out = ctx.run(["cat", "/proc/meminfo"], timeout=10)
    for line in (out or "").splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024
    return 0


def _proxmenux(ctx) -> dict[str, Any]:
    """What ProxMenux itself has applied to this host."""
    import json as _json
    from pathlib import Path

    def load(path):
        try:
            return _json.loads(Path(path).read_text(errors="replace"))
        except (OSError, ValueError):
            return None

    from post_install_versions import load_installed_tools
    installed = load_installed_tools()
    updates = load("/usr/local/share/proxmenux/updates_available.json") or {}
    tools = []
    for key in sorted(installed):
        value = installed[key]
        if not value.get("installed", False):
            continue
        version = value.get("version")
        tools.append({"key": key, "version": str(version) if version is not None else ""})
    return {
        "optimizations": tools,
        "pending_updates": [
            {"key": u.get("key"), "current": u.get("current_version"),
             "available": u.get("available_version")}
            for u in (updates.get("updates") or [])
        ],
    }
