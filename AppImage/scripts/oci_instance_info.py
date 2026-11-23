"""What the VM & LXC modal needs to know about an OCI instance.

Read-only view of the installation record OCI manager Apps keeps for every
container it created: whether the container is one, whether it belongs to a
multi-container application, whether it uses host directories (which its
backup does not revert), whether an operation is pending, whether it is
restarted when it stops on its own and whether it was restored from a backup
and is not registered on this host yet. Nothing here
changes the record or runs inside the container.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import time

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


def _installation(vmid: int) -> str | None:
    """The installation the container says it belongs to: the mark OCI manager
    Apps leaves in its notes, which a backup keeps."""
    path = f"/etc/pve/nodes/{socket.gethostname().split('.', 1)[0]}/lxc/{int(vmid)}.conf"
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
    except OSError:
        return None
    return installation_marker(text)


def installation_marker(config: str) -> str | None:
    text = config.split("\n[", 1)[0]
    match = re.search(r"^#.*proxmenux-instance=([0-9a-f-]{36})(?![0-9a-f-])", text, re.MULTILINE)
    return match.group(1) if match else None


OCI_JOURNAL_BYTES = 2 * 1024 * 1024
MAX_OCI_JOURNALS = 256


class OciStateError(Exception):
    """A plain guest action is unsafe until the OCI state is known."""


def check_plain_lxc(config: str, instance: Path, deadline: float) -> None:
    if installation_marker(config):
        raise OciStateError('managed_oci')
    if re.search(r'^#.*proxmenux-instance=|^\s*lxc\.environment\.runtime:', config, re.M):
        raise OciStateError('oci_unknown')

    try:
        instance_mode = instance.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError:
        raise OciStateError('oci_unknown') from None
    if not stat.S_ISDIR(instance_mode):
        raise OciStateError('oci_unknown')
    try:
        for name in ('oci-compose.json', 'stack-assembly.json'):
            try:
                (instance / name).lstat()
            except FileNotFoundError:
                continue
            # An active record without a live marker needs review. This also
            # rejects incomplete installations and broken records or symlinks.
            raise OciStateError('oci_unknown')

        # OCI keeps journals after successful work and rollback. Only these
        # terminal phases prove that the directory contains history.
        checked = 0
        for name in ('transactions', 'stack-transactions'):
            directory = instance / name
            try:
                mode = directory.lstat().st_mode
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(mode):
                raise OciStateError('oci_unknown')
            with os.scandir(directory) as entries:
                for entry in entries:
                    checked += 1
                    if checked > MAX_OCI_JOURNALS or time.monotonic() >= deadline:
                        raise OciStateError('oci_unknown')
                    if not entry.is_dir(follow_symlinks=False):
                        raise OciStateError('oci_unknown')
                    journal = Path(entry.path) / 'transaction.json'
                    fd = os.open(journal, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(fd, 'rb') as handle:
                        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                            raise OciStateError('oci_unknown')
                        raw = handle.read(OCI_JOURNAL_BYTES + 1)
                    if len(raw) > OCI_JOURNAL_BYTES:
                        raise OciStateError('oci_unknown')
                    state = json.loads(raw)
                    if not isinstance(state, dict) or state.get('schema_version') != 1:
                        raise OciStateError('oci_unknown')
                    if state.get('phase') not in ('committed', 'rolled-back'):
                        raise OciStateError('guest_busy')
    except (OSError, ValueError, RecursionError):
        raise OciStateError('oci_unknown') from None


def belongs_to_guest(vmid: int, record: dict) -> bool:
    installation = _installation(vmid)
    return bool(installation and installation == record.get("installation_id"))


def record_signature(vmid: int):
    try:
        info = os.stat(os.path.join(ROOT, str(int(vmid)), "oci-compose.json"))
        return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size
    except FileNotFoundError:
        return None

def _unrecoverable(vmid: int, installation: str) -> bool:
    """A restored container that carries no copy of its record: the menu
    found nothing to recover it from and left it as an ordinary container."""
    try:
        with open(os.path.join(ROOT, ".unrecoverable.json"), encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return False
    return isinstance(value, dict) and value.get(str(int(vmid))) == installation


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
        "restored": False,
        "watchdog": False,
    }
    record = _record(vmid)
    installation = _installation(vmid)
    if installation and (record is None or record.get("installation_id") != installation):
        # Restored from a backup: the record stayed on the host it came from.
        result["restored"] = not _unrecoverable(vmid, installation)
        return result
    if record is None or not installation:
        result["console_log"] = False
        return result
    primary_id = int((record.get("stack_member") or {}).get("primary_vmid") or vmid)
    primary = record if primary_id == vmid else (_record(primary_id) or {})
    if primary_id != vmid and not belongs_to_guest(primary_id, primary):
        primary = {}
    members = [int(m["vmid"]) for m in (primary.get("stack") or {}).get("members") or []
               if isinstance(m, dict) and str(m.get("vmid", "")).isdigit()]
    records = [record] if not members else [r for m in members
                                            if (r := _record(m)) and belongs_to_guest(m, r)]
    result.update(
        oci_instance=True,
        stack=bool(members) or bool(record.get("stack_member")),
        primary_vmid=primary_id,
        members=members,
        host_directories=any(_host_dirs(r) for r in records),
        pending=bool(record.get("pending_transaction") or primary.get("pending_stack_transaction")),
        watchdog=len(records) == (len(members) or 1)
        and all((r.get("deployment") or {}).get("watchdog") is True for r in records),
    )
    return result


if __name__ == "__main__":
    # Native worker runs the same check after acquiring Proxmox's config lock.
    if len(sys.argv) != 3:
        sys.exit(2)
    try:
        with open(sys.argv[2], "rb") as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            sys.exit(1)
        check_plain_lxc(raw.decode("utf-8").split("\n[", 1)[0], Path(sys.argv[1]),
                        time.monotonic() + 3)
    except (OciStateError, OSError, UnicodeError):
        sys.exit(1)
