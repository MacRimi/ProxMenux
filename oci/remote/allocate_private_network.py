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


def existing_bridges() -> set[str]:
    bridges: set[str] = set()
    for line in command_output("ip", "-o", "link", "show").splitlines():
        match = re.match(r"^\d+: ([^:@]+)", line)
        if match:
            bridges.add(match.group(1))
    for path in Path("/etc/pve/lxc").glob("*.conf"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        bridges.update(re.findall(r"(?:^|,)bridge=([^,\s]+)", text, re.MULTILINE))
    interface_paths = [Path("/etc/network/interfaces")]
    interface_paths.extend(Path("/etc/network/interfaces.d").glob("*"))
    for path in interface_paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        bridges.update(
            re.findall(r"^(?:auto|iface)\s+(vmbr\d+)\b", text, re.MULTILINE)
        )
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
