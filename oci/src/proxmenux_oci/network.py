"""IPv4 address of the containers on their access bridge: DHCP or static."""
from __future__ import annotations

import ipaddress
import re
from pathlib import Path

from . import host
from .i18n import translate
from .ui import UserCancelled

DHCP = "dhcp"
STATIC = "static"


def usable(address: ipaddress.IPv4Address, interface: ipaddress.IPv4Interface) -> bool:
    network = interface.network
    return (address.version == 4 and not address.is_multicast and not address.is_unspecified
            and not address.is_loopback and address in network
            and (network.prefixlen >= 31
                 or address not in (network.network_address, network.broadcast_address)))


def addresses_in_use() -> set[str]:
    """IPv4 addresses assigned to guests of the cluster and to the bridges of this node."""
    used: set[str] = set()
    for pattern in ("*/lxc/*.conf", "*/qemu-server/*.conf"):
        for path in Path("/etc/pve/nodes").glob(pattern):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            used.update(re.findall(r"(?:^|[,\s])ip=(\d+\.\d+\.\d+\.\d+)/", text, re.MULTILINE))
    for row in host.bridges(include_private=True):
        if row.get("cidr"):
            used.add(row["cidr"].split("/", 1)[0])
    return used


def _bridge(bridge: str) -> dict:
    return next((row for row in host.bridges() if row.get("iface") == bridge), {})


def _example(bridge: str, taken: set[str]) -> str:
    """An address of the bridge subnet that no guest uses, to show the format."""
    try:
        network = ipaddress.ip_interface(_bridge(bridge).get("cidr") or "").network
    except ValueError:
        network = None
    if network is None or network.version != 4 or network.prefixlen > 24:
        return "192.168.1.100/24"
    address = next((a for a in (network.network_address + n for n in range(100, 250))
                    if str(a) not in taken), network.network_address + 100)
    return f"{address}/{network.prefixlen}"


def _static_address(ui, bridge: str, label: str, default: str, taken: set[str]) -> ipaddress.IPv4Interface:
    text = (f"{translate('Static IPv4 address for')} {label}" if label
            else translate("Static IPv4 address"))
    example = _example(bridge, taken)
    text = f"{text} ({translate('with prefix, e.g.')} {example})"
    while True:
        value = ui.ask(text, default).strip()
        try:
            interface = ipaddress.ip_interface(value) if "/" in value else None
        except ValueError:
            interface = None
        if interface is None or interface.version != 4 or not usable(interface.ip, interface):
            ui.message(f"{translate('Enter a usable IPv4 address with its prefix, for example')} {example}")
            continue
        if str(interface.ip) in taken:
            ui.message(f"{translate('The address is already assigned on this host or cluster:')} {interface.ip}")
            continue
        return interface


def _gateway(ui, bridge: str, interfaces: list[ipaddress.IPv4Interface], default: str | None) -> str | None:
    default = default or _bridge(bridge).get("gateway") or ""
    try:
        if default and not all(usable(ipaddress.ip_address(default), i) for i in interfaces):
            default = ""
    except ValueError:
        default = ""
    while True:
        value = ui.ask(translate("IPv4 gateway (empty = no outbound route)"), default, required=False).strip()
        if not value:
            return None
        try:
            gateway = ipaddress.ip_address(value)
        except ValueError:
            gateway = None
        if gateway and all(usable(gateway, i) and gateway != i.ip for i in interfaces):
            return str(gateway)
        ui.message(translate("The gateway must be another usable address in the same subnet."))


def ask_addresses(ui, bridge: str, labels: list[str], current: dict[str, str] | None = None,
                  current_gateway: str | None = None) -> tuple[dict[str, str], str | None]:
    """One DHCP or static choice for the containers named in `labels` on
    `bridge`; static addresses share one gateway."""
    current = current or {}
    static = any(value and value != DHCP for value in current.values())
    title = translate("IPv4 address of the container") if len(labels) == 1 else translate("IPv4 address of the containers")
    mode = ui.choose(title, [(DHCP, translate("DHCP (automatic)")), (STATIC, translate("Static IP"))],
                     STATIC if static else DHCP)
    if mode is None:
        raise UserCancelled(title)
    if mode == DHCP:
        return {label: DHCP for label in labels}, None
    taken = addresses_in_use()
    interfaces: dict[str, ipaddress.IPv4Interface] = {}
    for label in labels:
        own = current.get(label) if current.get(label) != DHCP else None
        if own:
            taken.discard(own.split("/", 1)[0])
        interfaces[label] = _static_address(ui, bridge, label if len(labels) > 1 else "", own or "", taken)
        taken.add(str(interfaces[label].ip))
    gateway = _gateway(ui, bridge, list(interfaces.values()), current_gateway)
    return {label: str(interface) for label, interface in interfaces.items()}, gateway


def ask_ipv4(ui, bridge: str, current: str | None = None,
             current_gateway: str | None = None) -> tuple[str, str | None]:
    addresses, gateway = ask_addresses(ui, bridge, [""], {"": current} if current else None, current_gateway)
    return addresses[""], gateway
