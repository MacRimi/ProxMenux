# ==========================================================
# ProxMenux Monitor - Guest backup archives
# Author      : Jonatan
# GitHub      : github.com/jcastro
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 16/10/2026
# ==========================================================
# Description:
# Deletes explicitly selected VM/CT backups through the native Proxmox
# storage API after a fresh inventory/protection check. Tracks native
# deletion tasks so an accepted operation is not mistaken for completion.
# No filesystem paths or cached inventory authorize deletion.
# ==========================================================

import json
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor


MAX_SELECTION = 20
REMOVED_RE = re.compile(r"Removed volume '[^'\n]+'")
STORAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
NODE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}")
_tasks = {}
_lock = threading.Lock()


class BackupArchiveError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def _pvesh(args, timeout=20):
    try:
        result = subprocess.run(["pvesh", *args, "--output-format", "json"],
                                capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BackupArchiveError("Proxmox command unavailable or timed out; outcome unconfirmed", 502) from error
    if result.returncode:
        raise BackupArchiveError((result.stderr or "Proxmox command failed").strip()[:1000], 502)
    output = result.stdout.strip()
    try:
        # pvesh can print no bytes for the API's successful null result.
        return json.loads(output or "null")
    except (ValueError, TypeError) as error:
        # With --delay, a deletion that ends in time prints the line of its
        # task log instead of JSON. Only that exact line is accepted.
        if args[0] == "delete" and REMOVED_RE.fullmatch(output):
            return output
        raise BackupArchiveError("Invalid Proxmox response; outcome unconfirmed", 502) from error


def _node():
    # Same local storage/node scope as the guest's existing backup list.
    node = socket.gethostname().split(".")[0]
    if not NODE_RE.fullmatch(node):
        raise BackupArchiveError("Invalid local node name", 502)
    return node


def _selection(vmid, data):
    if not 100 <= vmid <= 999999999:
        raise BackupArchiveError("Invalid VM/CT ID")
    if not isinstance(data, dict) or data.get("confirm") is not True:
        raise BackupArchiveError("Explicit confirmation is required")
    selected = data.get("backups")
    if not isinstance(selected, list) or not 1 <= len(selected) <= MAX_SELECTION:
        raise BackupArchiveError(f"Select between 1 and {MAX_SELECTION} backups")
    seen = set()
    for item in selected:
        if not isinstance(item, dict):
            raise BackupArchiveError("Invalid backup selection")
        storage, volid = item.get("storage"), item.get("volid")
        if not isinstance(storage, str) or not STORAGE_RE.fullmatch(storage):
            raise BackupArchiveError("Invalid backup storage")
        if (not isinstance(volid, str) or not volid.startswith(storage + ":")
                or len(volid) > 512 or not re.fullmatch(r"[A-Za-z0-9_:./+@-]+", volid)
                or any(part in ("", ".", "..") for part in volid.split(":", 1)[1].split("/"))):
            raise BackupArchiveError("Invalid backup volume ID")
        if volid in seen:
            raise BackupArchiveError("Duplicate backup selection")
        seen.add(volid)
    return [{"storage": item["storage"], "volid": item["volid"]} for item in selected]


def _protected(value):
    # Fail closed for an unexpected protection value, including the text 'true'.
    return value not in (None, False, 0, "0", "")


def _remember_task(task, vmid, node, volid):
    # These are server-returned task IDs, never arbitrary client paths.
    if (not isinstance(task, str) or not task.startswith(f"UPID:{node}:")
            or ":imgdel:" not in task or "/" in task or len(task) > 1024):
        raise BackupArchiveError("Unexpected deletion task; outcome unconfirmed", 502)
    with _lock:
        now = time.monotonic()
        expired = [key for key, entry in _tasks.items() if now - entry["created"] > 3600]
        for key in expired:
            del _tasks[key]
        # Bound even failed/unpolled jobs; expiry does not cancel a PVE task.
        if len(_tasks) >= 512:
            del _tasks[min(_tasks, key=lambda key: _tasks[key]["created"])]
        _tasks[task] = {"vmid": vmid, "node": node, "volid": volid, "created": now}


def delete_guest_backups(vmid, data):
    selected = _selection(vmid, data)
    node = _node()
    inventory = {}
    # Preflight the entire batch before deleting anything. An unavailable
    # storage or a protected/stale/cross-guest selection fails the whole batch.
    for storage in sorted({item["storage"] for item in selected}):
        entries = _pvesh(["get", f"/nodes/{node}/storage/{storage}/content",
                          "--content", "backup", "--vmid", str(vmid)])
        if not isinstance(entries, list):
            raise BackupArchiveError("Invalid backup inventory", 502)
        for entry in entries:
            if (isinstance(entry, dict) and entry.get("content") == "backup"
                    and isinstance(entry.get("volid"), str)):
                inventory[(storage, entry.get("volid"))] = entry
    for item in selected:
        entry = inventory.get((item["storage"], item["volid"]))
        if entry is None or str(entry.get("vmid")) != str(vmid):
            raise BackupArchiveError("Backup no longer exists or does not belong to this VM/CT", 409)
        if _protected(entry.get("protected")):
            raise BackupArchiveError("Protected backups cannot be deleted", 409)

    def remove(item):
        try:
            # Proxmox also enforces protection at deletion time. It removes
            # associated notes/log files and returns null only after success.
            task = _pvesh(["delete", f'/nodes/{node}/storage/{item["storage"]}/content/{item["volid"]}',
                            "--delay", "1"])
            if isinstance(task, str) and task.startswith("UPID:"):
                _remember_task(task, vmid, node, item["volid"])
                return {**item, "status": "pending", "task": task}
            if task is None or task == f"Removed volume '{item['volid']}'":
                return {**item, "status": "deleted"}
            return {**item, "status": "unconfirmed", "error": "Invalid Proxmox response; outcome unconfirmed"}
        except BackupArchiveError as error:
            return {**item, "status": "unconfirmed", "error": str(error)}

    with ThreadPoolExecutor(max_workers=min(4, len(selected)), thread_name_prefix="backup-delete") as pool:
        results = list(pool.map(remove, selected))
    return {"results": results}


def guest_backup_deletion_status(vmid, task):
    with _lock:
        entry = _tasks.get(task) if isinstance(task, str) else None
        if not entry or entry["vmid"] != vmid or time.monotonic() - entry["created"] > 3600:
            raise BackupArchiveError("Deletion task unknown or expired; refresh the backup list", 409)
        entry = entry.copy()
    status = _pvesh(["get", f'/nodes/{entry["node"]}/tasks/{task}/status'])
    if not isinstance(status, dict) or status.get("status") not in ("running", "stopped"):
        raise BackupArchiveError("Invalid deletion task status", 502)
    result = {"volid": entry["volid"], "status": "pending"}
    if status["status"] == "stopped":
        if status.get("exitstatus") == "OK":
            result["status"] = "deleted"
        else:
            result.update(status="unconfirmed", error=status.get("exitstatus") or "Deletion outcome unconfirmed")
    return result
