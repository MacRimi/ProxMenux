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
# Local Proxmox inventory and transport for the plain LXC command.
# Keeps planning reads separate from explicitly confirmed native actions.
# ==========================================================
"""Read local Proxmox inventory and dispatch only the three v1 mutations."""

import json
from copy import deepcopy
import os
from pathlib import Path
import platform
import re
import subprocess
import stat
import sys
from urllib.parse import urlsplit

from plain_lxc_spec import ARCHIVE, BRIDGE, GIB, LxcError, MIB, NODE, STORAGE, strict_json
from plain_lxc_resources import discover_devices, bind_identity, device_assignments, checked_identity, profiles, selected_hardware, OCI_REMOTE
sys.path.insert(0, str(OCI_REMOTE))
from oci_image_names import is_oci_archive


class Proxmox:
    def __init__(self):
        self.bridge = Path(__file__).with_name("plain_lxc_pve.pl")

    def run(self, command, body=None, timeout=12):
        try:
            result = subprocess.run(command, input=body if body is not None else b"",
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                                    check=True, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8"})
            return result.stdout
        except (OSError, subprocess.SubprocessError):
            raise LxcError("pve_unavailable") from None

    def read(self, path, **params):
        command = ["/usr/bin/pvesh", "--noproxy", "get", path, "--output-format", "json"]
        for key, value in params.items():
            command.extend((f"--{key}", str(value)))
        return strict_json(self.run(command))

    def dispatch(self, action, node, params):
        body = json.dumps({"action": action, "node": node, "params": params}).encode()
        timeout = 24 if action in ("inventory", "inspect") else 12
        return strict_json(self.run(["/usr/bin/perl", str(self.bridge)], body, timeout=timeout))

    def archive_checksum(self, volume):
        raw = self.run(["/usr/sbin/pvesm", "path", volume]).rstrip(b"\n")
        if not raw.startswith(b"/") or any(char in raw for char in (b"\n", b"\r", b"\0")):
            raise LxcError("pve_output_invalid")
        try:
            regular = stat.S_ISREG(Path(os.fsdecode(raw)).lstat().st_mode)
        except OSError:
            raise LxcError('template_unavailable', 'template.volume_id') from None
        if not regular:
            raise LxcError('template_unavailable', 'template.volume_id')
        output = self.run(["/usr/bin/sha512sum", "--", os.fsdecode(raw)], timeout=45)
        match = re.match(rb"([0-9a-f]{128}) ", output)
        if not match:
            raise LxcError("pve_output_invalid")
        return match[1].decode("ascii")

    def architecture(self):
        arch = platform.machine()
        return {"x86_64": "amd64", "aarch64": "arm64"}.get(arch, arch)

    def hardware_inventory(self):
        return discover_devices()

    def bind_identity(self, source):
        return bind_identity(source)

    def device_assignments(self, paths, vmid):
        return device_assignments(paths, vmid)


def rows(value):
    if type(value) is not list or any(type(item) is not dict for item in value):
        raise LxcError("pve_output_invalid")
    return value


def identifier(value, pattern):
    if type(value) is not str or not re.fullmatch(pattern, value):
        raise LxcError("pve_output_invalid")
    return value


def quantity(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise LxcError("pve_output_invalid")
    return value


def flag(value):
    if type(value) not in (int, bool) or value not in (0, 1):
        raise LxcError("pve_output_invalid")
    return bool(value)


def local_node(api):
    return node_from_status(api.read("/cluster/status"))


def node_from_status(data):
    nodes = [row for row in rows(data)
             if row.get("type") == "node" and flag(row.get("local", 0))]
    if len(nodes) != 1 or not flag(nodes[0].get("online", 0)):
        raise LxcError("node_unavailable")
    return identifier(nodes[0].get("name"), NODE)


def official_catalog(data, arch):
    catalog = {}
    for row in rows(data):
        if row.get("type") != "lxc" or row.get("architecture") != arch:
            continue
        source = row.get('source')
        origin = 'system' if source in ('http://download.proxmox.com/images', 'https://download.proxmox.com/images') else (
            'turnkey' if source == 'https://releases.turnkeylinux.org/pve' else None)
        if origin is None or (origin == 'system' and row.get('section') != 'system'):
            continue
        name, checksum = row.get("template"), row.get("sha512sum")
        if (type(name) is not str or len(name) > 180 or not re.fullmatch(ARCHIVE, name) or '..' in name
                or type(checksum) is not str or not re.fullmatch(r"[a-fA-F0-9]{128}", checksum)):
            continue
        location = row.get('location')
        if type(location) is not str:
            continue
        try:
            url = urlsplit(location)
        except ValueError:
            continue
        valid_location = location in (f'http://download.proxmox.com/images/system/{name}',
                                      f'https://download.proxmox.com/images/system/{name}') if origin == 'system' else (
            (re.fullmatch(r'https://releases\.turnkeylinux\.org/pve/(?:[A-Za-z0-9_.+-]+/)*'+re.escape(name),location)
             or re.fullmatch(r'https?://mirror\.turnkeylinux\.org/turnkeylinux/images/proxmox/'+re.escape(name),location))
            and '..' not in url.path.split('/'))
        if not valid_location:
            continue
        if name in catalog:
            raise LxcError("pve_output_invalid")
        catalog[name] = {"catalog_id": name, "sha512": checksum.lower(), "architecture": arch, 'origin': origin}
    return catalog


def current_inventory(api, expected=None, vmid=None):
    """One fresh native initialization; never reuse a previously checked result."""
    if api.architecture() not in ("amd64", "arm64"):
        raise LxcError("architecture_unsupported")
    response = api.dispatch("inspect", expected or "localhost", {} if vmid is None else {"vmid": vmid})
    if type(response) is not dict or "nodes" not in response:
        raise LxcError("pve_output_invalid")
    node = node_from_status(response["nodes"])
    if expected is not None and node != expected:
        raise LxcError("node_not_local", "node")
    raw = response.get("inventory")
    if type(raw) is not dict:
        raise LxcError("pve_output_invalid")
    context = inventory(api, node, vmid, raw=raw)
    if vmid is None:
        context["next_vmid"] = next_id(response.get("nextid"))
    return context


def inventory(api, node, vmid=None, *, raw=None):
    arch = api.architecture()
    if arch not in ("amd64", "arm64"):
        raise LxcError("architecture_unsupported")
    if raw is None:
        raw = api.dispatch("inventory", node, {} if vmid is None else {"vmid": vmid})
    if type(raw) is not dict or "bridge_vlans" not in raw:
        raise LxcError("pve_output_invalid")
    status = raw.get("status")
    if type(status) is not dict or any(type(status.get(key)) is not dict for key in ("cpuinfo", "memory")):
        raise LxcError("pve_output_invalid")
    limits = {
        "cores": quantity(status["cpuinfo"].get("cpus"), 1),
        "ram_mib": quantity(status["memory"].get("total"), MIB) // MIB,
    }
    catalog_state = "available"
    try:
        catalog = official_catalog(raw.get("catalog"), arch)
        if not catalog:
            catalog_state = "empty"
    except LxcError:
        catalog, catalog_state = {}, "unavailable"

    stores, templates, volumes, unavailable = {}, {}, set(), []
    for row in rows(raw.get("storages")):
        name = identifier(row.get("storage"), STORAGE)
        if row.get("state") == "unavailable":
            unavailable.append(name)
            continue
        types = row.get("content")
        if (row.get("state") != "available" or type(types) is not list or not types
                or any(item not in ("rootdir", "vztmpl") for item in types)):
            raise LxcError("pve_output_invalid")
        stores[name] = {"id": name, "content": types, "type": identifier(row.get("type"), STORAGE),
                        "available_bytes": quantity(row.get("avail"))}
        if "vztmpl" not in types:
            continue
        for item in rows(row.get("templates")):
            volume = item.get("volid")
            if type(volume) is not str or not volume.startswith(f"{name}:vztmpl/"):
                raise LxcError("pve_output_invalid")
            volumes.add(volume)
            basename = volume.split("/", 1)[1]
            if not re.fullmatch(ARCHIVE, basename) or len(volume) > 255 or is_oci_archive(basename):
                continue
            if basename in catalog:
                templates[volume] = {**catalog[basename], "volume_id": volume, "storage": name,
                                     "size_bytes": quantity(item.get("size"))}
            else:
                templates[volume] = {'volume_id': volume, 'storage': name, 'origin': 'local',
                                     'architecture': None, 'sha512': None, 'size_bytes': quantity(item.get('size'))}

    active_bridges = [row for row in rows(raw.get("network"))
                      if row.get("type") in ("bridge", "OVSBridge") and flag(row.get("active", 0))]
    linux_vlans = raw["bridge_vlans"]
    if linux_vlans is not None and type(linux_vlans) is not dict:
        raise LxcError("pve_output_invalid")
    bridges = {}
    for row in active_bridges:
        kind = row["type"]
        name = identifier(row.get("iface"), BRIDGE)
        vlan_supported = kind == "OVSBridge"
        if kind == "bridge":
            vlan_supported = (flag(row.get("bridge_vlan_aware", 0)) if linux_vlans is None
                              else flag(linux_vlans.get(name, 0)))
        bridges[name] = {"id": name, "type": kind, "vlan_supported": vlan_supported}
    context = {
        "node": node, "architecture": arch, "limits": limits, "catalog_state": catalog_state,
        "catalog": catalog, "templates": templates, "volumes": volumes, "storages": stores,
        "unavailable_storages": unavailable, "bridges": bridges,
    }
    capabilities = raw.get('capabilities', {})
    if type(capabilities) is not dict:
        raise LxcError('pve_output_invalid')
    context['capabilities'] = {key:min(16,quantity(capabilities.get(key, 0))) for key in ('mount_points','devices')}
    context['devices'] = api.hardware_inventory() if context['capabilities']['devices'] else {}
    if type(context['devices']) is not dict:
        raise LxcError('pve_output_invalid')
    context['hardware'] = profiles(context['devices'])
    context['hardware_errors'] = sorted(set(getattr(context['devices'],'errors',[])))
    if vmid is not None:
        if vmid in occupied_ids(raw.get("guests")):
            raise LxcError("vmid_in_use", "vmid")
        next_id(raw.get("nextid"), vmid)
    return context


def occupied_ids(data):
    occupied = set()
    for row in rows(data):
        vmid = quantity(row.get("vmid"), 100)
        if row.get("type") not in ("lxc", "qemu") or vmid > 999999999:
            raise LxcError("pve_output_invalid")
        occupied.add(vmid)
    return occupied


def next_id(data, vmid=None):
    if data is None:
        raise LxcError("pve_unavailable")
    if type(data) is str and re.fullmatch(r"[0-9]{3,9}", data):
        data = int(data)
    result = quantity(data, 100)
    if result > 999999999 or (vmid is not None and vmid != result):
        raise LxcError("pve_output_invalid")
    return result


def storage_for(context, name, content):
    storage = context["storages"].get(name)
    if storage is None or content not in storage["content"]:
        raise LxcError("storage_unavailable", name)
    return storage


def checked_plan(api, spec, context):
    volume = spec["template"]["volume_id"]
    template = context["templates"].get(volume)
    if template is None:
        code = "catalog_unavailable" if context["catalog_state"] == "unavailable" else "template_unverified"
        raise LxcError(code, "template.volume_id")
    rootfs = spec["rootfs"]
    storage = storage_for(context, rootfs["storage"], "rootdir")
    architecture = spec['template'].get('architecture', template['architecture'])
    if architecture is None:
        raise LxcError('template_architecture_required', 'template.architecture')
    if architecture != context['architecture'] or (template['architecture'] is not None and architecture != template['architecture']):
        raise LxcError('template_architecture_mismatch', 'template.architecture')
    # LXC on ZFS is a subvol with refquota, not a VM zvol controlled by
    # storage.sparse. LVM-thin also allocates data on write. Native extraction
    # can still fail on actual capacity and must report that task honestly.
    logical_overcommit = rootfs['size_gib'] * GIB > storage['available_bytes']
    thin = storage['type'] in ('lvmthin', 'zfspool')
    if storage['available_bytes'] < max(1, template['size_bytes']) or (logical_overcommit and not thin):
        raise LxcError("disk_space_insufficient", "rootfs.size_gib")
    if (spec["cpu"]["cores"] > context["limits"]["cores"]
            or spec["memory"]["ram_mib"] > context["limits"]["ram_mib"]):
        raise LxcError("node_capacity_exceeded")
    bridge = None
    if spec["network"] is not None:
        bridge = context["bridges"].get(spec["network"]["bridge"])
        if bridge is None or ("vlan_tag" in spec["network"] and not bridge["vlan_supported"]):
            raise LxcError("bridge_unavailable", "network.bridge")
    checksum = api.archive_checksum(volume)
    if template['origin'] != 'local' and checksum != template["sha512"]:
        raise LxcError("template_checksum_mismatch", "template.volume_id")
    warnings = ["no_network"] if spec["network"] is None else []
    if template['origin'] == 'local':
        warnings.append('custom_template')
    if logical_overcommit:
        warnings.append('storage_overcommit')
    if spec["nesting"]:
        warnings.append("nesting_enabled")
    if spec.get('hardware') and not context['capabilities']['devices']:
        raise LxcError('resource_unsupported')
    chosen = selected_hardware(spec['hardware'], context['hardware']) if 'hardware' in spec else []
    devices = [device for item in chosen for device in item['devices']] if 'hardware' in spec else spec['devices']
    attachments = {'mounts':[], 'devices':[]}
    if chosen:
        attachments['hardware'] = deepcopy(chosen)
    if len(spec['mounts']) > context['capabilities']['mount_points'] or len(devices) > context['capabilities']['devices']:
        raise LxcError('resource_unsupported')
    allocations = {rootfs['storage']:rootfs['size_gib']}
    for mount in spec['mounts']:
        if mount['type'] == 'volume':
            target = storage_for(context, mount['storage'], 'rootdir')
            allocations[mount['storage']] = allocations.get(mount['storage'], 0) + mount['size_gib']
            attachments['mounts'].append({**mount, 'storage_type':target['type']})
        else:
            attachments['mounts'].append({**mount, 'identity':checked_identity(api.bind_identity(mount['source']))})
            if 'bind_mount' not in warnings:
                warnings.append('bind_mount')
    for device in devices:
        candidate = context['devices'].get(device['path'])
        if type(candidate) is not dict or candidate.get('path') != device['path'] or type(candidate.get('identity')) is not dict:
            raise LxcError('resource_unavailable', 'devices.path')
        attachments['devices'].append({**device, 'identity':deepcopy(checked_identity(candidate['identity']))})
    if devices:
        warnings.append('device_passthrough')
    assignments = api.device_assignments([item['path'] for item in devices], spec['vmid'])
    for name, size in allocations.items():
        target = context['storages'][name]
        overcommit = size*GIB > target['available_bytes']
        if target['available_bytes'] <= 0 or (overcommit and target['type'] not in ('lvmthin','zfspool')):
            raise LxcError('disk_space_insufficient', 'mounts' if name != rootfs['storage'] or spec['mounts'] else 'rootfs.size_gib')
        if overcommit and 'storage_overcommit' not in warnings:
            warnings.append('storage_overcommit')
    return {"spec": spec, "unprivileged": True, "nesting": spec["nesting"], "warnings": warnings,
            "resources": {"template": {**template, 'architecture': architecture, 'sha512': checksum},
                          "rootfs_type": storage["type"], "bridge": bridge, 'attachments':attachments,
                          'device_assignments':assignments}}
