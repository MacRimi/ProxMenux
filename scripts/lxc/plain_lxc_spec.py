#!/usr/bin/env python3

# ==========================================================
# ProxMenux - Plain LXC console creation
# ==========================================================
# Author      : Vaso73
# GitHub      : github.com/Vaso73
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 15/11/2026
# ==========================================================
# Description:
# Schema validation and normalized plans for the plain LXC command.
# This module has no lifecycle or host side effects.
# ==========================================================
"""Validation and the version 1 plan shared by the console and future clients."""

import base64
import hashlib
import ipaddress
import json
import re


GIB = 1024 ** 3
MIB = 1024 ** 2
MAX_BODY = 131072
NODE = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
STORAGE = r"[A-Za-z][A-Za-z0-9_.-]{0,63}"
ARCHIVE = r"[A-Za-z0-9][A-Za-z0-9_.+-]*\.(?:tar(?:\.(?:gz|xz|zst|bz2|lzma))?|tgz)"
BRIDGE = r"[A-Za-z0-9_.-]{1,15}"
REQUEST_ID = r"[a-f0-9]{32}"
DEVICE_PATH = r'/dev/(?:dri/(?:renderD[0-9]+|card[0-9]+)|kfd|apex_[0-9]+|accel/accel[0-9]+|nvidia(?:[0-9]+|ctl|-modeset|-uvm(?:-tools)?)|bus/usb/[0-9]{3}/[0-9]{3}|tty(?:USB|ACM)[0-9]+)'
DEFAULTS = {
    "cpu": {"cores": 1},
    "memory": {"ram_mib": 512, "swap_mib": 512},
    "rootfs": {"size_gib": 8},
    "ipv4": {"mode": "dhcp"},
    "onboot": False,
    "start_after_create": False,
    # As the Proxmox interface does for unprivileged containers: systemd 255
    # and later need it inside the container.
    "nesting": True,
    "prepare_system": False,
}


class LxcError(Exception):
    def __init__(self, code, field=None):
        super().__init__(code)
        self.code = code
        self.field = field


def strict_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError()
            value[key] = item
        return value

    def invalid_constant(_):
        raise ValueError()

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, RecursionError):
        raise LxcError("invalid_request") from None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def fields(value, required, optional="", field="request"):
    required, optional = set(required.split()), set(optional.split())
    if type(value) is not dict or not required <= value.keys() <= required | optional:
        raise LxcError("invalid_field", field)


def integer(value, low, high, field):
    if type(value) is not int or not low <= value <= high:
        raise LxcError("invalid_field", field)
    return value


def string(value, pattern, limit, field):
    if type(value) is not str or len(value) > limit or not re.fullmatch(pattern, value):
        raise LxcError("invalid_field", field)
    return value


def dns_name(value, field):
    string(value, r"[A-Za-z0-9.-]+", 253, field)
    if any(not re.fullmatch(NODE, label) for label in value.rstrip(".").split(".")):
        raise LxcError("invalid_field", field)
    return value.lower().removesuffix(".")


def ssh_keys(raw):
    # Keep the key type and wire-format check from the preview. Comments are
    # optional and have no effect on the configured access.
    if type(raw) is not list or len(raw) > 32:
        raise LxcError("invalid_ssh_key", "access")
    keys = []
    for line in raw:
        string(line, r"[ -~]+", 8192, "access")
        parts = line.split()
        if len(parts) < 2 or not re.fullmatch(
            r"ssh-(?:ed25519|rsa)|ecdsa-sha2-nistp(?:256|384|521)|"
            r"sk-(?:ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com", parts[0]
        ):
            raise LxcError("invalid_ssh_key", "access")
        try:
            decoded = base64.b64decode(parts[1], validate=True)
            length = int.from_bytes(decoded[:4], "big")
            if decoded[4:4 + length] != parts[0].encode() or len(decoded) <= length + 8:
                raise ValueError()
        except ValueError:
            raise LxcError("invalid_ssh_key", "access") from None
        keys.append(" ".join(parts[:2]))
    if sum(len(key) + 1 for key in keys) > 32768:
        raise LxcError("invalid_ssh_key", "access")
    return keys


def normalize_network(network):
    if network is None:
        return None
    fields(network, "bridge", "vlan_tag ipv4", "network")
    result = {"bridge": string(network["bridge"], BRIDGE, 15, "network.bridge")}
    if "vlan_tag" in network:
        result["vlan_tag"] = integer(network["vlan_tag"], 1, 4094, "network.vlan_tag")
    ipv4 = network.get("ipv4", DEFAULTS["ipv4"])
    fields(ipv4, "mode", "cidr gateway", "network.ipv4")
    if ipv4["mode"] == "dhcp" and len(ipv4) == 1:
        result["ipv4"] = {"mode": "dhcp"}
    elif ipv4["mode"] == "static":
        fields(ipv4, "mode cidr", "gateway", "network.ipv4")
        cidr = string(ipv4["cidr"], r"[0-9.]+/[0-9]+", 18, "network.ipv4.cidr")
        try:
            result["ipv4"] = {"mode": "static", "cidr": str(ipaddress.IPv4Interface(cidr))}
            if "gateway" in ipv4:
                gateway = string(ipv4["gateway"], r"[0-9.]+", 15, "network.ipv4.gateway")
                result["ipv4"]["gateway"] = str(ipaddress.IPv4Address(gateway))
        except ValueError:
            raise LxcError("invalid_field", "network.ipv4") from None
    else:
        raise LxcError("invalid_field", "network.ipv4")
    return result


def normalize_dns(dns):
    fields(dns, "", "nameservers search_domains", "dns")
    nameservers, domains = dns.get("nameservers", []), dns.get("search_domains", [])
    if any(type(values) is not list or len(values) > 6 for values in (nameservers, domains)):
        raise LxcError("invalid_field", "dns")
    try:
        nameservers = [
            str(ipaddress.IPv4Address(string(value, r"[0-9.]+", 15, "dns.nameservers")))
            for value in nameservers
        ]
    except ValueError:
        raise LxcError("invalid_field", "dns.nameservers") from None
    return {"nameservers": nameservers, "search_domains": [dns_name(value, "dns") for value in domains]}


def mount_path(value, field, *, host=False):
    string(value, r'/[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*', 255, field)
    protected = ('/etc', '/proc', '/sys', '/dev', '/run', '/boot', '/usr', '/bin', '/sbin', '/lib', '/lib64')
    if host:
        protected += ('/root', '/var/lib/lxc', '/var/lib/pve-cluster', '/var/lib/pve-manager')
    if any(part in ('.', '..') for part in value.split('/')) or any(value == path or value.startswith(path+'/')
            or (host and path.startswith(value+'/')) for path in protected):
        raise LxcError('invalid_field', field)
    return value


def normalize_mounts(mounts):
    if type(mounts) is not list or len(mounts) > 16:
        raise LxcError('invalid_field', 'mounts')
    result = []
    for item in mounts:
        fields(item, 'type path', 'source storage size_gib read_only backup', 'mounts')
        kind = item['type']
        if kind == 'volume':
            fields(item, 'type path storage size_gib', 'read_only backup', 'mounts')
            entry = {'type':kind, 'storage':string(item['storage'], STORAGE, 64, 'mounts.storage'),
                     'size_gib':integer(item['size_gib'], 1, 65536, 'mounts.size_gib')}
        elif kind == 'bind':
            fields(item, 'type path source', 'read_only backup', 'mounts')
            if item.get('backup', False) is not False:
                raise LxcError('invalid_field', 'mounts.backup')
            entry = {'type':kind, 'source':mount_path(item['source'], 'mounts.source', host=True)}
        else:
            raise LxcError('invalid_field', 'mounts.type')
        entry.update(path=mount_path(item['path'], 'mounts.path'),
                     read_only=item.get('read_only', kind == 'bind'), backup=item.get('backup', kind == 'volume'))
        if type(entry['read_only']) is not bool or type(entry['backup']) is not bool:
            raise LxcError('invalid_field', 'mounts')
        if any(entry['path'] == other['path'] or entry['path'].startswith(other['path']+'/')
               or other['path'].startswith(entry['path']+'/') for other in result):
            raise LxcError('invalid_field', 'mounts.path')
        result.append(entry)
    return result


def normalize_devices(devices):
    if type(devices) is not list or len(devices) > 16:
        raise LxcError('invalid_field', 'devices')
    result = []
    for item in devices:
        fields(item, 'path', 'uid gid mode', 'devices')
        entry = {'path':string(item['path'], DEVICE_PATH, 128, 'devices.path'),
                 'uid':integer(item.get('uid', 0), 0, 2147483647, 'devices.uid'),
                 'gid':integer(item.get('gid', 0), 0, 2147483647, 'devices.gid'),
                 'mode':string(item.get('mode', '0660'), r'0[0-7]{3}', 4, 'devices.mode')}
        if entry['path'] in [other['path'] for other in result]:
            raise LxcError('invalid_field', 'devices.path')
        result.append(entry)
    return result


def normalize_hardware(items):
    if type(items) is not list or len(items) > 16:
        raise LxcError('invalid_field','hardware')
    result = []
    for item in items:
        fields(item,'profile selection_id',field='hardware')
        profile = string(item['profile'], r'intel-drm|amd-drm|nvidia-runtime|coral|npu|usb',32,'hardware.profile')
        selection = string(item['selection_id'],r'[a-zA-Z0-9_-]+',64,'hardware.selection_id')
        if any(row['selection_id'] == selection for row in result):
            raise LxcError('invalid_field','hardware')
        result.append({'profile':profile,'selection_id':selection})
    return result


def normalize(spec, schema_version=1):
    fields(spec, "node vmid hostname template access rootfs network",
           "cpu memory dns onboot start_after_create nesting prepare_system mounts devices hardware", "spec")
    if schema_version == 2 and "devices" in spec:
        raise LxcError("invalid_field", "devices")
    if schema_version == 1 and "hardware" in spec:
        raise LxcError("unsupported_schema", "hardware")
    template, access, rootfs = spec["template"], spec["access"], spec["rootfs"]
    cpu, memory = spec.get("cpu", {}), spec.get("memory", {})
    fields(template, "volume_id", "architecture", field="template")
    fields(access, "mode", "ssh_public_keys", "access")
    fields(rootfs, "storage", "size_gib", "rootfs")
    fields(cpu, "", "cores", "cpu")
    fields(memory, "", "ram_mib swap_mib", "memory")
    mode = access["mode"]
    keys = ssh_keys(access.get("ssh_public_keys", []))
    if mode not in ("password", "ssh_key", "both") or bool(keys) != (mode in ("ssh_key", "both")):
        raise LxcError("invalid_field", "access")
    for flag in ("onboot", "start_after_create", "nesting", "prepare_system"):
        if flag in spec and type(spec[flag]) is not bool:
            raise LxcError("invalid_field", flag)
    network = normalize_network(spec["network"])
    dns = normalize_dns(spec.get("dns", {}))
    if network is None and any(dns.values()):
        raise LxcError("invalid_field", "dns")
    return {
        "node": string(spec["node"], NODE, 63, "node"),
        "vmid": integer(spec["vmid"], 100, 999999999, "vmid"),
        "hostname": dns_name(spec["hostname"], "hostname"),
        "template": {"volume_id": string(template["volume_id"], STORAGE + ":vztmpl/" + ARCHIVE,
                                         255, "template.volume_id"),
                     **({'architecture': string(template['architecture'], r'amd64|arm64', 5, 'template.architecture')}
                        if 'architecture' in template else {})},
        "access": {"mode": mode, "ssh_public_keys": keys},
        "rootfs": {
            "storage": string(rootfs["storage"], STORAGE, 64, "rootfs.storage"),
            "size_gib": integer(rootfs.get("size_gib", DEFAULTS["rootfs"]["size_gib"]),
                                1, 65536, "rootfs.size_gib"),
        },
        "cpu": {"cores": integer(cpu.get("cores", DEFAULTS["cpu"]["cores"]), 1, 8192, "cpu.cores")},
        "memory": {
            "ram_mib": integer(memory.get("ram_mib", DEFAULTS["memory"]["ram_mib"]),
                               16, 4194304, "memory.ram_mib"),
            "swap_mib": integer(memory.get("swap_mib", DEFAULTS["memory"]["swap_mib"]),
                                0, 4194304, "memory.swap_mib"),
        },
        "network": network,
        "dns": dns,
        "onboot": spec.get("onboot", DEFAULTS["onboot"]),
        "start_after_create": spec.get("start_after_create", DEFAULTS["start_after_create"]),
        "nesting": spec.get("nesting", DEFAULTS["nesting"]),
        "prepare_system": spec.get("prepare_system", DEFAULTS["prepare_system"]),
        'mounts': normalize_mounts(spec.get('mounts', [])),
        **({'hardware':normalize_hardware(spec.get('hardware',[]))} if schema_version == 2
           else {'devices':normalize_devices(spec.get('devices',[]))}),
    }


def pve_params(spec, password, request_id):
    rootfs, access = spec["rootfs"], spec["access"]
    params = {
        "vmid": spec["vmid"], "hostname": spec["hostname"], "ostemplate": spec["template"]["volume_id"],
        "storage": rootfs["storage"], "rootfs": f'{rootfs["storage"]}:{rootfs["size_gib"]}',
        "cores": spec["cpu"]["cores"], "memory": spec["memory"]["ram_mib"], "swap": spec["memory"]["swap_mib"],
        "unprivileged": 1, "features": f'nesting={int(spec["nesting"])}', "onboot": int(spec["onboot"]), "start": 0,
        "description": f"ProxMenux request {request_id}",
    }
    if 'architecture' in spec['template']:
        params['arch'] = spec['template']['architecture']
    if password is not None:
        params["password"] = password
    if access["ssh_public_keys"]:
        params["ssh-public-keys"] = "\n".join(access["ssh_public_keys"])
    network = spec["network"]
    if network is not None:
        ipv4 = network["ipv4"]
        net = ["name=eth0", "type=veth", f'bridge={network["bridge"]}', f'ip={ipv4.get("cidr", "dhcp")}']
        if "gateway" in ipv4:
            net.append(f'gw={ipv4["gateway"]}')
        if "vlan_tag" in network:
            net.append(f'tag={network["vlan_tag"]}')
        params["net0"] = ",".join(net)
    if spec["dns"]["nameservers"]:
        params["nameserver"] = " ".join(spec["dns"]["nameservers"])
    if spec["dns"]["search_domains"]:
        params["searchdomain"] = " ".join(spec["dns"]["search_domains"])
    for index, mount in enumerate(spec['mounts']):
        source = f"{mount['storage']}:{mount['size_gib']}" if mount['type'] == 'volume' else mount['source']
        params[f'mp{index}'] = f"{source},mp={mount['path']},ro={int(mount['read_only'])},backup={int(mount['backup'])}"
    for index, device in enumerate(spec['devices']):
        params[f'dev{index}'] = f"path={device['path']},uid={device['uid']},gid={device['gid']},mode={device['mode']}"
    return params
