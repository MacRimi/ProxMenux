"""Minimal, read-only console snapshot published for the unprivileged TUI.

The web API remains authenticated.  This file contains only guest and cluster
fields intended for the local console; host metrics are collected by the TUI
from procfs so they remain available when this backend is stopped.
"""

import json
import grp
import os
import tempfile
import time
from datetime import datetime, timezone

SCHEMA_VERSION = 1
SNAPSHOT_PATH = "/run/proxmenux-monitor/console.json"


def _snapshot_group_gid():
    return grp.getgrnam("proxmenux-monitor").gr_gid


def _safe_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _safe_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    return None


def build_snapshot(resources, cluster_status, observed_at=None, expected_nodes=None):
    """Build a deliberately small schema; unknown fields stay absent/N-D."""
    resources = resources if isinstance(resources, list) else []
    cluster_status = cluster_status if isinstance(cluster_status, list) else []
    guests = []
    for item in resources:
        if not isinstance(item, dict) or item.get("type") not in ("qemu", "lxc"):
            continue
        guests.append({
            "vmid": str(item.get("vmid", "")),
            "name": str(item.get("name") or item.get("vmid") or "Guest"),
            "type": "VM" if item.get("type") == "qemu" else "CT",
            "node": str(item.get("node") or ""),
            "status": str(item.get("status") or ""),
            "cpu": _safe_number(item.get("cpu")),
            "mem": _safe_number(item.get("mem")),
            "maxmem": _safe_number(item.get("maxmem")),
        })
    nodes = []
    node_resources = {
        str(item.get("node")): item for item in resources
        if isinstance(item, dict) and item.get("type") == "node" and item.get("node")
    }
    storage_by_node = {}
    for item in resources:
        if not isinstance(item, dict) or item.get("type") != "storage" or not item.get("node"):
            continue
        storage_by_node.setdefault(str(item["node"]), []).append({
            "name": str(item.get("storage") or item.get("id") or "storage"),
            # /cluster/resources storage rows use disk/maxdisk. Keep used/total
            # aliases too for fixtures or future API versions.
            "used": _safe_number(item.get("used") if "used" in item else item.get("disk")),
            "total": _safe_number(item.get("total") if "total" in item else item.get("maxdisk")),
        })
    quorum = None
    status_node_names = set()
    for item in cluster_status:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "cluster":
            quorum = _safe_bool(item.get("quorate"))
        elif item.get("type") == "node":
            node_name = str(item.get("name") or "")
            if node_name:
                status_node_names.add(node_name)
            sample = node_resources.get(node_name, {})
            nodes.append({
                "name": node_name,
                "online": _safe_bool(item.get("online")),
                "local": _safe_bool(item.get("local")) or False,
                "cpu": _safe_number(sample.get("cpu")) if sample else None,
                "mem": _safe_number(sample.get("mem")) if sample else None,
                "maxmem": _safe_number(sample.get("maxmem")) if sample else None,
                "maxcpu": _safe_number(sample.get("maxcpu")) if sample else None,
                "storage": storage_by_node.get(node_name, []),
                # PVE's cluster resource API does not expose remote host
                # ZRAM or interface counters; keep those explicitly unknown.
                "zram_used": None,
                "network": None,
            })
    has_cluster = len(nodes) > 1
    resource_node_names = set(node_resources)
    expected = set(expected_nodes) if expected_nodes is not None else status_node_names
    membership_complete = bool(expected) and expected == status_node_names == resource_node_names
    when = observed_at or datetime.now(timezone.utc).isoformat()
    return {"schema_version": SCHEMA_VERSION, "observed_at": when,
            "publisher": "proxmenux-monitor",
            "cluster": {"enabled": has_cluster, "quorum": quorum,
                        "complete": membership_complete, "nodes": nodes}, "guests": guests}


def write_snapshot(snapshot, path=SNAPSHOT_PATH):
    """Atomically replace a group-readable snapshot; fail closed on ownership errors."""
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o750, exist_ok=True)
    gid = _snapshot_group_gid()
    os.chown(parent, 0, gid)
    os.chmod(parent, 0o750)
    fd, temporary = tempfile.mkstemp(prefix=".console-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(snapshot, stream, separators=(",", ":"), ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, 0, gid)
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def refresh_snapshot(resources_reader, status_reader, path=SNAPSHOT_PATH, expected_nodes=None):
    """Keep the last good snapshot on sampling errors; never publish false empty."""
    try:
        resources = resources_reader()
        status = status_reader()
    except Exception:
        return False
    if not isinstance(resources, list) or not isinstance(status, list):
        return False
    # Require node status even when guest resources are present; a partial
    # status response must not replace a useful last sample.
    if not any(isinstance(row, dict) and row.get("type") == "node" for row in status):
        return False
    node_rows = [row for row in resources if isinstance(row, dict) and row.get("type") == "node"]
    if not node_rows:
        return False
    resource_node_names = {str(row.get("node")) for row in node_rows if row.get("node")}
    status_node_names = {str(row.get("name")) for row in status
                         if isinstance(row, dict) and row.get("type") == "node" and row.get("name")}
    expected = set(expected_nodes) if expected_nodes is not None else set()
    if expected and not (resource_node_names == status_node_names == expected):
        return False
    if not expected and resource_node_names != status_node_names:
        return False
    write_snapshot(build_snapshot(resources, status,
                                   expected_nodes=expected_nodes if expected_nodes is not None else []), path)
    return True
