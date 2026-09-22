"""Facts read from the local Proxmox node: storages, bridges and the timezone."""
from __future__ import annotations

import ipaddress
import json
import subprocess
from pathlib import Path
from typing import Any


def _pvesh(path: str, *arguments: str) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(["pvesh", "get", path, "--output-format", "json", *arguments],
                                capture_output=True, text=True, timeout=30, check=False)
        rows = json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def storages(content: str) -> list[dict[str, Any]]:
    """Active storages of this node that accept `content` (rootdir, vztmpl, ...),
    the one with most free space first."""
    rows = [row for row in _pvesh("/nodes/localhost/storage", "--content", content, "--enabled", "1")
            if row.get("active") and row.get("storage")]
    return sorted(rows, key=lambda row: -(row.get("avail") or 0))


def default_storage(content: str, preferred: str) -> str:
    names = [row["storage"] for row in storages(content)]
    if preferred in names or not names:
        return preferred
    return names[0]


# Private networks that ProxMenux creates for multi-container applications.
PRIVATE_STACK_NETWORK = ipaddress.ip_network("10.77.0.0/16")


def _private_stack_bridge(row: dict[str, Any]) -> bool:
    if row.get("bridge_ports") or not row.get("cidr"):
        return False
    try:
        return ipaddress.ip_interface(row["cidr"]).network.subnet_of(PRIVATE_STACK_NETWORK)
    except (TypeError, ValueError):
        return False


def bridges(include_private: bool = False) -> list[dict[str, Any]]:
    """Bridges of this node; the private networks of multi-container
    applications are left out unless `include_private` is set."""
    rows = [row for row in _pvesh("/nodes/localhost/network", "--type", "any_bridge") if row.get("iface")
            and (include_private or not _private_stack_bridge(row))]
    return sorted(rows, key=lambda row: row["iface"])


def default_bridge(preferred: str) -> str:
    names = [row["iface"] for row in bridges()]
    if preferred in names or not names:
        return preferred
    return names[0]


def timezone() -> str:
    try:
        value = Path("/etc/timezone").read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if not value:
        try:
            value = subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"],
                                   capture_output=True, text=True, timeout=10, check=False).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            value = ""
    return value or "Etc/UTC"


def gib(value: Any) -> int:
    try:
        return int(value) // 2**30
    except (TypeError, ValueError):
        return 0
