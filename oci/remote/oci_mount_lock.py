"""Unmounting the root filesystem of a container mounted with `pct mount`.

`pct mount` locks the container as `mounted` and `pct unmount` removes that
lock only when its unmount succeeds. A failed unmount leaves the lock behind,
and every backup and operation of the container then fails until someone runs
`pct unlock`. The unmount is tried again once; if it still fails, the lock is
removed only when nothing is mounted under the root filesystem any more. With
anything still mounted the lock stays, because it protects that mount.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import time

MOUNTINFO = Path('/proc/self/mountinfo')
CONFIGS = Path('/etc/pve/lxc')
RETRY_SECONDS = 2


def rootfs(vmid) -> str:
    return f'/var/lib/lxc/{int(vmid)}/rootfs'


def _unescape(value: str) -> str:
    return value.replace('\\040', ' ').replace('\\011', '\t').replace('\\012', '\n').replace('\\134', '\\')


def mounted_under(vmid) -> bool:
    """Whether anything is still mounted at or under the root filesystem."""
    point = rootfs(vmid)
    try:
        lines = MOUNTINFO.read_text().splitlines()
    except OSError:
        return True  # Without the list of mounts, nothing is assumed free.
    for line in lines:
        fields = line.split()
        if len(fields) > 4:
            target = _unescape(fields[4])
            if target == point or target.startswith(point + '/'):
                return True
    return False


def lock_of(vmid):
    """The lock in the main section of the container's configuration."""
    try:
        text = (CONFIGS / f'{int(vmid)}.conf').read_text()
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith('['):
            break
        if line.startswith('lock:'):
            return line.partition(':')[2].strip()
    return None


def _ok(run, *args) -> bool:
    """Run with a runner that raises on failure or returns a CompletedProcess."""
    try:
        result = run(*args)
    except Exception:
        return False
    code = getattr(result, 'returncode', None)
    return not isinstance(code, int) or code == 0


def unmount(vmid, run) -> bool:
    """Unmount `vmid`; True when its rootfs is free and unlocked afterwards.
    `run(*args)` either raises or returns a CompletedProcess on failure."""
    vmid = str(int(vmid))
    if _ok(run, 'pct', 'unmount', vmid):
        return True
    time.sleep(RETRY_SECONDS)
    if _ok(run, 'pct', 'unmount', vmid):
        return True
    if mounted_under(vmid) or lock_of(vmid) != 'mounted':
        return False
    return _ok(run, 'pct', 'unlock', vmid)


def release(vmid, run) -> None:
    """Like unmount, for the steps that cannot go on with the rootfs still
    mounted: it raises when the rootfs is not free afterwards."""
    if not unmount(vmid, run):
        try:
            from oci_ui import translate
        except ImportError:  # pragma: no cover - the engine always ships it
            translate = str
        raise ValueError(translate('Could not unmount the container filesystem'))
