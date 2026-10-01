"""Facts read from the local Proxmox node: storages, bridges, the timezone and
its USB devices."""
from __future__ import annotations

import ipaddress
import json
import re
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


def ipv4_subnet(bridge: str) -> str | None:
    """The IPv4 subnet configured on ``bridge``, if it has one.

    This is deliberately taken from the node's bridge configuration instead
    of guessing from a container address.  A host-monitor shares the host
    network namespace, so its firewall source scope must be the selected
    host bridge's network.
    """
    row = next((item for item in bridges(include_private=True)
                if item.get("iface") == bridge), None)
    try:
        interface = ipaddress.ip_interface(str((row or {}).get("cidr") or ""))
    except ValueError:
        return None
    return str(interface.network) if interface.version == 4 else None


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



def address_answers(address: str, bridge: str) -> bool:
    """Whether a device of the network already answers on this address. The
    neighbour table tells, so a device that drops pings is found too; without a
    host address on that network nothing can be asked and nothing is assumed."""
    try:
        subprocess.run(["ping", "-c", "1", "-W", "1", "-I", bridge, address],
                       capture_output=True, timeout=5, check=False)
        result = subprocess.run(["ip", "-4", "neigh", "show", address, "dev", bridge],
                                capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return " lladdr " in f" {result.stdout} "

# USB classes as the Monitor labels them.
_USB_CLASSES = {
    "01": "Audio", "02": "Communications", "03": "HID", "06": "Imaging", "07": "Printer",
    "0a": "CDC Data", "0b": "Smart Card", "0e": "Video", "10": "Audio/Video",
    "e0": "Wireless Controller", "ef": "Miscellaneous", "fe": "Application Specific",
    "ff": "Vendor Specific",
}
# UPS makers, whose devices report the HID class.
_USB_UPS_VENDORS = {"0463", "051d", "0764", "0d9f", "06da", "09ae", "047c", "075d", "10af", "0665"}
_USB_LEFT_OUT = {"08", "09"}  # storage and hubs are not handed to an LXC as a device node
_SERIAL_NODE = re.compile(r"tty(?:ACM|USB)[0-9]+")
_LSUSB_LINE = re.compile(r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+[0-9a-f]{4}:[0-9a-f]{4}\s*(.*)", re.IGNORECASE)


def _sysfs(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def usb_devices(root: Path = Path("/"), lsusb: str | None = None) -> list[dict[str, str]]:
    """USB peripherals of this node an LXC can receive, named as the Monitor
    names them: a serial adapter by its tty node, any other device by its bus
    node."""
    if lsusb is None:
        try:
            lsusb = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5,
                                   check=False).stdout
        except (OSError, subprocess.TimeoutExpired):
            lsusb = ""
    names = {}
    for line in lsusb.splitlines():
        match = _LSUSB_LINE.match(line)
        if match:
            names[(int(match[1]), int(match[2]))] = match[3].strip()
    serial: dict[str, list[str]] = {}
    for tty in sorted((root / "sys/class/tty").glob("tty*")):
        if not _SERIAL_NODE.fullmatch(tty.name):
            continue
        device = (tty / "device").resolve()
        while device != device.parent and not (device / "idVendor").exists():
            device = device.parent
        if (device / "idVendor").exists():
            serial.setdefault(device.name, []).append(tty.name)
    rows = []
    for device in sorted((root / "sys/bus/usb/devices").glob("*")):
        vendor = _sysfs(device / "idVendor").lower()
        if ":" in device.name or not vendor or vendor == "1d6b":
            continue
        device_class = _sysfs(device / "bDeviceClass").lower() or "00"
        if device_class == "00":
            device_class = _sysfs(device / f"{device.name}:1.0" / "bInterfaceClass").lower()
        if device_class in _USB_LEFT_OUT:
            continue
        kind = "UPS" if device_class == "03" and vendor in _USB_UPS_VENDORS else _USB_CLASSES.get(device_class, "USB")
        try:
            bus, number = int(_sysfs(device / "busnum")), int(_sysfs(device / "devnum"))
        except ValueError:
            continue
        name = (_sysfs(device / "product") or names.get((bus, number))
                or f"{vendor}:{_sysfs(device / 'idProduct').lower()}")
        for node in serial.get(device.name) or [f"bus/usb/{bus:03d}/{number:03d}"]:
            rows.append({"path": f"/dev/{node}", "name": name, "kind": kind})
    return rows
