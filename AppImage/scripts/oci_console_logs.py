"""Console output of a native OCI container, read from the host.

ProxMenux creates every OCI container with `lxc.console.logfile` pointing at
`/var/log/proxmenux/oci/<vmid>.console.log`: liblxc copies the stdout and
stderr of the image's entrypoint there, the way `docker logs` keeps them. The
file already exists on the host, so nothing here runs inside the container.

The path is derived from the VMID and confirmed against the container's own
configuration; no caller can name a file. Reads are bounded — the last lines
on first open, then only what was appended since the offset the viewer holds —
and a file that got shorter or was replaced (logrotate's copytruncate, a
container rebuilt by an update) resets the viewer instead of returning garbage.
"""
from __future__ import annotations

import os
import re

LOG_DIR = "/var/log/proxmenux/oci"
TAIL_READ_LIMIT = 2 * 1024 * 1024     # bytes scanned to find the last lines
FOLLOW_READ_LIMIT = 512 * 1024        # bytes returned per follow request
MAX_LINES = 2000

# CSI sequences (colours, cursor), OSC sequences (window titles) and the lone
# ESC-letter codes some programs emit. Stripped, never rendered: the text goes
# to the page as text.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def log_path(vmid: int) -> str:
    return os.path.join(LOG_DIR, f"{int(vmid)}.console.log")


def configured_log(vmid: int) -> str | None:
    """The console log the container declares, when it is the ProxMenux one."""
    try:
        with open(f"/etc/pve/lxc/{int(vmid)}.conf", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("["):
                    break
                if line.startswith("lxc.console.logfile:"):
                    value = line.split(":", 1)[1].strip()
                    return value if value == log_path(vmid) else None
    except (OSError, ValueError):
        return None
    return None


def terminal_state(vmid: int) -> dict:
    """Whether the Proxmox console of the container opens a shell."""
    mode = "tty"
    try:
        with open(f"/etc/pve/lxc/{int(vmid)}.conf", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("["):
                    break
                if line.startswith("cmode:"):
                    mode = line.split(":", 1)[1].strip()
    except (OSError, ValueError):
        pass
    return {"cmode": mode, "shell": mode == "shell"}


def clean(text: str) -> list[str]:
    """Readable lines from raw console output.

    CRLF becomes a line end. A lone carriage return is how a progress bar
    redraws itself in place, so only what was written after the last one on a
    line is kept — the state the terminal would have shown.
    """
    text = _ANSI_RE.sub("", text).replace("\r\n", "\n")
    lines = []
    for raw in text.split("\n"):
        if "\r" in raw:
            raw = raw.rsplit("\r", 1)[-1]
        lines.append(_CONTROL_RE.sub("", raw))
    return lines


def _read_tail(handle, size: int, lines: int) -> tuple[list[str], bool]:
    start = max(0, size - TAIL_READ_LIMIT)
    handle.seek(start)
    data = handle.read(size - start).decode("utf-8", errors="replace")
    result = clean(data)
    if start > 0 and result:
        result = result[1:]   # the first line was cut by the read window
    if result and result[-1] == "":
        result = result[:-1]
    head_cut = start > 0 or len(result) > lines
    return result[-lines:], head_cut


def read(vmid: int, lines: int = 200, offset: int | None = None, inode: int | None = None) -> dict:
    """The last `lines` lines, or what was appended after `offset`.

    `lines=0` reads nothing: it only says whether the container has a
    console log, which is what decides if the viewer is offered at all.
    """
    lines = max(0, min(int(lines), MAX_LINES))
    path = configured_log(vmid)
    base = {"ok": True, "vmid": int(vmid), **terminal_state(vmid)}
    if not path:
        return {**base, "enabled": False, "lines": [], "size": 0, "offset": 0, "inode": None}
    try:
        stat = os.stat(path)
    except OSError:
        return {**base, "enabled": True, "path": path, "lines": [], "size": 0, "offset": 0, "inode": None}
    size = stat.st_size
    base.update(enabled=True, path=path, size=size, inode=stat.st_ino)
    if lines == 0 and offset is None:
        return {**base, "lines": [], "offset": size}
    with open(path, "rb") as handle:
        replaced = inode is not None and inode != stat.st_ino
        if offset is None or replaced or offset > size:
            # First open, or the file the viewer followed is gone: rotated by
            # copytruncate, or recreated with the container.
            result, head_cut = _read_tail(handle, size, max(lines, 1))
            return {**base, "lines": result, "offset": size, "reset": offset is not None,
                    "head_truncated": head_cut}
        handle.seek(offset)
        chunk = handle.read(min(size - offset, FOLLOW_READ_LIMIT))
    # Only whole lines are returned; an unfinished last line is left for the
    # next read, where it arrives complete.
    cut = chunk.rfind(b"\n")
    if cut < 0:
        return {**base, "lines": [], "offset": offset, "reset": False}
    complete = chunk[:cut + 1]
    result = clean(complete.decode("utf-8", errors="replace"))
    if result and result[-1] == "":
        result = result[:-1]
    return {**base, "lines": result, "offset": offset + len(complete), "reset": False}
