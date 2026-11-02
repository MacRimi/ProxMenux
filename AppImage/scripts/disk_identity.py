"""
Physical disks and a stable identity for each, read without touching them.

Everything here comes from udev's database and /sys through lsblk, which
reads these columns without opening the block device. A drive that is
asleep, or idle and about to be, is not disturbed by being listed.

The identity matters because a kernel name is not one: a USB drive can be
sda on one boot and sdb on the next, so anything the user attaches to a
disk has to follow the disk, not the letter it happened to get.
"""

import re
import subprocess
from typing import Any, Dict, List

_LSBLK_TIMEOUT = 5
_SYS_BLOCK = "/sys/block"
_FIELD_RE = re.compile(r'(\w+)="([^"]*)"')
_SKIP_PREFIXES = ("loop", "zd", "nbd", "ram", "sr")


def disk_key(serial: str, wwn: str, name: str) -> str:
    """Stable identity: the serial where udev knows one, then the WWN,
    and only as a last resort the kernel name."""
    serial = (serial or "").strip()
    wwn = (wwn or "").strip()
    if serial:
        return f"serial:{serial}"
    if wwn:
        return f"wwn:{wwn}"
    return f"name:{name}"


def list_physical_disks() -> List[Dict[str, Any]]:
    """Every physical disk with its identity and the facts the interface
    shows about it. Returns an empty list if lsblk cannot be read."""
    try:
        proc = subprocess.run(
            ["lsblk", "-d", "-n", "-P", "-b", "-o",
             "NAME,TYPE,MODEL,SERIAL,WWN,SIZE,TRAN,ROTA"],
            capture_output=True, text=True, timeout=_LSBLK_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []

    disks: List[Dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        fields = dict(_FIELD_RE.findall(line))
        name = fields.get("NAME", "")
        if fields.get("TYPE") != "disk" or not name or name.startswith(_SKIP_PREFIXES):
            continue
        serial = fields.get("SERIAL", "").strip()
        wwn = fields.get("WWN", "").strip()
        try:
            size = int(fields.get("SIZE") or 0)
        except ValueError:
            size = 0
        disks.append({
            "name": name,
            "key": disk_key(serial, wwn, name),
            "model": fields.get("MODEL", "").strip(),
            "serial": serial,
            "size_bytes": size,
            "transport": fields.get("TRAN", "").strip(),
            "rotational": fields.get("ROTA", "").strip() == "1",
        })
    return disks


def rotation_rate(name: str, reported: Any = None) -> int:
    """The rotation every view of a disk shows: the RPM smartctl reported,
    0 meaning solid state, or else the kernel's flag, where -1 is a spinning
    disk of unknown speed. What smartctl reported wins, because USB-SATA
    bridges mark every disk behind them as rotational."""
    if isinstance(reported, int) and not isinstance(reported, bool) and reported >= 0:
        return reported
    try:
        with open(f"{_SYS_BLOCK}/{name}/queue/rotational") as flag:
            return -1 if flag.read().strip() == "1" else 0
    except OSError:
        return 0


def media_type(name: str, rate: int) -> str:
    """NVMe, SSD or HDD, from a rotation as ``rotation_rate`` returns it."""
    if name.startswith("nvme"):
        return "NVMe"
    return "HDD" if rate else "SSD"


def names_for_keys(keys) -> set:
    """Current kernel names of the disks whose identity is in ``keys``."""
    if not keys:
        return set()
    return {d["name"] for d in list_physical_disks() if d["key"] in keys}
