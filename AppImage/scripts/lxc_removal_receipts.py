"""One-shot dispatch receipts shared with the native removal worker."""

import os
from pathlib import Path
import re
import stat
import tempfile
import time


DIRECTORY = Path("/run/proxmenux-lxc-removals")
DISPATCH_WINDOW = 25
RECEIPT_AGE = 86400
REJECTED = "not_started"
OPERATION = re.compile(r"[0-9a-f]{32}")
DESTROY_UPID = re.compile(
    r"UPID:(?P<node>[A-Za-z0-9-]+):[0-9A-Fa-f]{8}:[0-9A-Fa-f]{8,9}:[0-9A-Fa-f]{8}:"
    r"vzdestroy:(?P<vmid>[0-9]+):root@pam:"
)


def _path(operation):
    if not isinstance(operation, str) or not OPERATION.fullmatch(operation):
        raise ValueError("Invalid removal operation")
    info = DIRECTORY.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise OSError("Invalid removal receipt directory")
    return DIRECTORY / operation


def begin(operation):
    DIRECTORY.mkdir(mode=0o700, exist_ok=True)
    path = _path(operation)
    path.mkdir(mode=0o700)
    return path


def task_for(value, node, vmid):
    match = DESTROY_UPID.fullmatch(value) if isinstance(value, str) else None
    return value if match and match["node"] == node and match["vmid"] == str(vmid) else None


def outcome(operation):
    """Return (started, result); no write is needed to observe an operation."""
    try:
        path = _path(operation)
        started = path.stat().st_mtime
    except FileNotFoundError:
        return None, None
    try:
        value = (path / "result").read_text(encoding="ascii").strip()
    except FileNotFoundError:
        value = None
    return started, value


def seal_unstarted(operation):
    """Compete with the worker's atomic publication, never overwrite it."""
    path = _path(operation)
    with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", dir=path) as staging:
        staging.write(REJECTED + "\n")
        staging.flush()
        try:
            os.link(staging.name, path / "result")
        except FileExistsError:
            pass
    return outcome(operation)[1]


def shared_task(operation, node, vmid):
    started, value = outcome(operation)
    if started is None:
        raise BlockingIOError("Removal receipt unavailable")
    if value is None and time.time() - started >= DISPATCH_WINDOW:
        value = seal_unstarted(operation)
    if value == REJECTED:
        return None
    task = task_for(value, node, vmid)
    if not task:
        raise BlockingIOError("Removal dispatch is not confirmed")
    return task
