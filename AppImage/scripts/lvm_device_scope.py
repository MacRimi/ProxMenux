# ==========================================================
# ProxMenux Monitor - LVM disk read scope
# Author      : Jonatan
# GitHub      : github.com/jcastro
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 16/10/2026
# ==========================================================
# Description:
# Applies the disk exclusions to LVM metadata scans in both Monitor
# readers. Excluded disks receive no power-mode probe and a disk in
# standby is not woken; every device built on them is excluded too. No
# eligible devices means no scan.
# ==========================================================

import json
import re
import subprocess

_NAME = re.compile(r"[A-Za-z0-9._+-]+")


def _topology():
    """Every block device by kernel name: its type, its parents and whether
    it is an LVM physical volume. lsblk reads this from udev, not the disks.
    A RAID or multipath device appears once per member."""
    result = subprocess.run(["lsblk", "-J", "-l", "-o", "KNAME,TYPE,PKNAME,FSTYPE"],
                            capture_output=True, text=True, timeout=5)
    if result.returncode:
        return None
    types, parents, volumes = {}, {}, set()
    for device in json.loads(result.stdout).get("blockdevices") or []:
        name, parent = device.get("kname"), device.get("pkname")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            return None
        types[name] = device.get("type")
        parents.setdefault(name, set())
        if parent is not None:
            if not isinstance(parent, str) or not _NAME.fullmatch(parent):
                return None
            parents[name].add(parent)
        if device.get("fstype") == "LVM2_member" and device.get("type") != "lvm":
            volumes.add(name)
    return types, parents, volumes


def _lvm_filters():
    """LVM's own global_filter and filter, as lists of (accept, pattern).
    An explicit --devices list bypasses them, so a guest's volume group on
    a zvol would otherwise appear on the host."""
    result = subprocess.run(["lvmconfig", "--type", "full", "devices/global_filter", "devices/filter"],
                            capture_output=True, text=True, timeout=5)
    if result.returncode:
        return None
    filters = []
    for line in result.stdout.splitlines():
        name, _, value = line.strip().partition("=")
        if name not in ("global_filter", "filter"):
            continue
        rules = []
        for item in re.findall(r'"((?:[^"\\]|\\.)*)"', value):
            end = item.rfind(item[1]) if len(item) > 2 else -1
            if item[:1] not in ("a", "r") or end <= 1:
                return None
            rules.append((item[0] == "a", re.compile(item[2:end])))
        filters.append(rules)
    return filters


def _accepted(path, filters):
    """The first pattern a path matches decides; no match accepts it."""
    for rules in filters:
        for accept, pattern in rules:
            if pattern.search(path):
                if not accept:
                    return False
                break
    return True


def _disks_under(name, parents, seen=None):
    """The disks a device is built on: itself, or its parents' disks."""
    seen = seen if seen is not None else set()
    if name in seen:
        return set()
    seen.add(name)
    if not parents.get(name):
        return {name}
    found = set()
    for parent in parents[name]:
        found |= _disks_under(parent, parents, seen)
    return found


def lvm_device_args(standby_check):
    """Return [] for an unrestricted scan, --devices args, or None to skip.

    A failed inventory must never fall back to an unrestricted scan. None
    is distinct from []: if every disk is excluded/idle/asleep, callers
    must not start pvs/lvs/vgs at all.
    """
    try:
        from disk_temperature_history import disk_read_policy, excluded_disk_names
        topology = _topology()
        if topology is None:
            return None
        types, parents, volumes = topology
        disks = {name for name, kind in types.items() if kind == "disk"}
        if not disks:
            return None
        excluded = excluded_disk_names()
        blocked = set()
        for disk in sorted(disks):
            # Test the exclusion first: even CHECK POWER MODE is forbidden
            # for an excluded disk. Some USB bridges do not honour -n standby.
            if disk_read_policy(disk, excluded) != "read" or standby_check(disk):
                blocked.add(disk)
        allowed = sorted(f"/dev/{name}" for name in volumes if not (_disks_under(name, parents) & blocked))
        if not blocked:
            return []
        filters = _lvm_filters()
        if filters is None:
            return None
        # An explicit list makes LVM open every device in it, so only the
        # physical volumes are named: a RAID, multipath or encrypted volume
        # built on a blocked disk would read that disk too and stays out.
        allowed = [path for path in allowed if _accepted(path, filters)]
        if not allowed:
            return None
        return ["--devices", ",".join(allowed)]
    except Exception:
        # Unavailable exclusions, topology or policy are not permission to
        # open devices that may have been deliberately excluded.
        return None
