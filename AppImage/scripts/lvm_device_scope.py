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
# Applies the automatic disk-read policy to LVM metadata scans in both
# Monitor readers. Excluded and idle disks receive no power-mode probe;
# their partitions are excluded too. No eligible devices means no scan.
# ==========================================================

import re
import subprocess


def lvm_device_args(standby_check):
    """Return [] for an unrestricted scan, --devices args, or None to skip.

    A failed inventory must never fall back to an unrestricted scan. None
    is distinct from []: if every disk is excluded/idle/asleep, callers
    must not start pvs/lvs/vgs at all.
    """
    try:
        from disk_temperature_history import disk_read_policy, excluded_disk_names
        result = subprocess.run(["lsblk", "-rno", "NAME,TYPE,PKNAME"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode:
            return None
        nodes = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2 or parts[1] not in ("disk", "part"):
                continue
            name = parts[0]
            base = name if parts[1] == "disk" else parts[2] if len(parts) > 2 else ""
            if not re.fullmatch(r"[A-Za-z0-9._+-]+", name) or not re.fullmatch(r"[A-Za-z0-9._+-]+", base):
                return None
            nodes.append((name, base))
        disks = {name for name, base in nodes if name == base}
        if not disks or any(base not in disks for _, base in nodes):
            return None
        excluded = excluded_disk_names()
        blocked = set()
        for disk in sorted(disks):
            # Test policy first: even CHECK POWER MODE is forbidden for an
            # excluded/idle disk. Some USB bridges do not honour -n standby.
            if disk_read_policy(disk, excluded) != "read" or standby_check(disk):
                blocked.add(disk)
        if not blocked:
            return []
        devices = [f"/dev/{name}" for name, base in nodes if base not in blocked]
        if not devices:
            return None
        return ["--devices", ",".join(dict.fromkeys(devices))]
    except Exception:
        # Unavailable exclusions, topology or policy are not permission to
        # open devices that may have been deliberately excluded.
        return None
