"""What the VM & LXC modal needs to know about an OCI instance.

Read-only view of the installation record OCI manager Apps keeps for every
container it created: whether the container is one, whether it belongs to a
multi-container application, whether it uses host directories (which its
backup does not revert) and whether an operation is pending. Nothing here
changes the record or runs inside the container.
"""
from __future__ import annotations

import json
import os

import oci_console_logs

ROOT = "/usr/local/share/proxmenux/oci/instances"


def _record(vmid: int) -> dict | None:
    path = os.path.join(ROOT, str(int(vmid)), "oci-compose.json")
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _host_dirs(record: dict) -> bool:
    mounts = (record.get("deployment") or {}).get("mounts") or []
    return any(isinstance(m, dict) and m.get("type") == "host-bind" for m in mounts)


def info(vmid: int) -> dict:
    vmid = int(vmid)
    result = {
        "vmid": vmid,
        "oci_instance": False,
        "console_log": oci_console_logs.configured_log(vmid) is not None,
        "stack": False,
        "primary_vmid": vmid,
        "members": [],
        "host_directories": False,
        "pending": False,
    }
    record = _record(vmid)
    if record is None:
        return result
    primary_id = int((record.get("stack_member") or {}).get("primary_vmid") or vmid)
    primary = record if primary_id == vmid else (_record(primary_id) or {})
    members = [int(m["vmid"]) for m in (primary.get("stack") or {}).get("members") or []
               if isinstance(m, dict) and str(m.get("vmid", "")).isdigit()]
    records = [record] if not members else [r for r in (_record(m) for m in members) if r]
    result.update(
        oci_instance=True,
        stack=bool(members) or bool(record.get("stack_member")),
        primary_vmid=primary_id,
        members=members,
        host_directories=any(_host_dirs(r) for r in records),
        pending=bool(record.get("pending_transaction") or primary.get("pending_stack_transaction")),
    )
    return result
