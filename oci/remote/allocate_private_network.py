#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path

from oci_ui import translate


def command_output(*command: str) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    return result.stdout


def _interface_files() -> list[Path]:
    """Include pending Proxmox network edits and down interface definitions."""
    paths = [Path('/etc/network/interfaces'), Path('/etc/network/interfaces.new')]
    paths.extend(Path('/etc/network/interfaces.d').glob('*'))
    return [path for path in paths if path.is_file()]


def _configured_networks(text: str) -> list[ipaddress.IPv4Network]:
    networks = []
    addresses = []
    netmask = None
    inet = False

    def collect():
        for address in addresses:
            value = address if '/' in address else address+'/'+(netmask or '32')
            try:
                interface = ipaddress.ip_interface(value)
                if interface.version == 4:
                    networks.append(interface.network)
            except ValueError:
                continue

    for line in text.splitlines():
        words = line.partition('#')[0].split()
        if not words:
            continue
        if words[0] == 'iface':
            collect()
            addresses = []
            netmask = None
            inet = len(words) >= 4 and words[2] == 'inet'
        elif inet and len(words) >= 2:
            if words[0] == 'address':
                addresses.append(words[1])
            elif words[0] == 'netmask':
                netmask = words[1]
    collect()
    return networks


def existing_bridges() -> set[str]:
    bridges: set[str] = set()
    for line in command_output("ip", "-o", "link", "show").splitlines():
        match = re.match(r"^\d+: ([^:@]+)", line)
        if match:
            bridges.add(match.group(1))
    for path in Path("/etc/pve/lxc").glob("*.conf"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        bridges.update(re.findall(r"(?:^|,)bridge=([^,\s]+)", text, re.MULTILINE))
    for path in _interface_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            words = line.partition('#')[0].split()
            if words and words[0] in {'auto', 'iface'}:
                names = words[1:] if words[0] == 'auto' else words[1:2]
                bridges.update(name for name in names if re.fullmatch(r'vmbr\d+', name))
    return bridges


def existing_networks() -> list[ipaddress.IPv4Network]:
    networks: list[ipaddress.IPv4Network] = []
    for line in command_output("ip", "-4", "route", "show").splitlines():
        token = line.split(maxsplit=1)[0]
        if token == "default":
            continue
        try:
            networks.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            pass
    for path in Path("/etc/pve/lxc").glob("*.conf"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for address in re.findall(r"(?:^|,)ip=(\d+\.\d+\.\d+\.\d+/\d+)", text, re.MULTILINE):
            try:
                networks.append(ipaddress.ip_interface(address).network)
            except ValueError:
                pass
    for path in _interface_files():
        networks.extend(_configured_networks(path.read_text(encoding='utf-8', errors='ignore')))
    return networks


def allocate_network(
    deployment: dict,
    bridges: set[str],
    occupied: list[ipaddress.IPv4Network],
) -> tuple[str, ipaddress.IPv4Network] | None:
    network = deployment.get("network", {})
    if network.get("private_allocation") != "automatic":
        return None

    original = ipaddress.ip_network(network["private_subnet"], strict=True)
    if original.prefixlen != 24:
        raise ValueError(translate("Automatic private network allocation requires a /24 subnet"))

    selected: tuple[str, ipaddress.IPv4Network] | None = None
    for index in range(0, 178):
        bridge = f"vmbr{10 + index}"
        candidate = ipaddress.ip_network(f"10.77.{index}.0/24")
        if bridge in bridges or any(candidate.overlaps(item) for item in occupied):
            continue
        selected = bridge, candidate
        break
    if selected is None:
        raise SystemExit(translate("No free ProxMenux private /24 network is available"))

    bridge, candidate = selected
    for key, value in list(network.items()):
        if not key.endswith("_address") or not isinstance(value, str):
            continue
        interface = ipaddress.ip_interface(value)
        if interface.ip not in original:
            continue
        host_offset = int(interface.ip) - int(original.network_address)
        network[key] = f"{candidate.network_address + host_offset}/{candidate.prefixlen}"
    network["private_bridge"] = bridge
    network["private_subnet"] = str(candidate)
    network["private_allocation"] = "allocated"
    return bridge, candidate


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: allocate_private_network.py DEPLOYMENT.json")
    path = Path(sys.argv[1])
    deployment = json.loads(path.read_text(encoding="utf-8"))
    try:
        selected = allocate_network(deployment, existing_bridges(), existing_networks())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if selected is None:
        return 0

    bridge, candidate = selected
    path.write_text(json.dumps(deployment, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"{translate('Private network assigned automatically:')} {bridge} ({candidate})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
