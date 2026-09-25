#!/usr/bin/env python3
"""Proxmox console of a native OCI container: a shell through lxc-attach.

An OCI image starts its own entrypoint as PID 1 and runs no login service, so
the default `cmode: console` attaches to a tty nothing answers on. `cmode:
shell` makes Proxmox open `lxc-attach --clear-env` instead: a new process in
the container's namespaces, with PID 1 and the image untouched. It is the
equivalent of `docker exec` — root inside that container, without a password,
for whoever Proxmox lets open its console.

lxc-attach runs the shell /etc/passwd gives root, and falls back to /bin/sh
only when root has no entry at all. An image whose root is set to nologin, or
that ships no shell, keeps `cmode: console` rather than offering a console
that closes as soon as it opens.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys

NO_LOGIN = ('nologin', 'false')
LOG_DIR = Path('/var/log/proxmenux/oci')
LOGROTATE = Path('/etc/logrotate.d/proxmenux-oci')
# copytruncate, because liblxc keeps the file open for as long as the
# container runs; moving it away would leave the application writing into the
# rotated copy. The threshold is checked by the host's daily logrotate run, so
# it is a rotation threshold, not a hard cap.
LOGROTATE_POLICY = """/var/log/proxmenux/oci/*.console.log {
    size 10M
    rotate 3
    missingok
    notifempty
    copytruncate
    compress
}
"""


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=60)


def _running_pid(vmid: int) -> str | None:
    result = _run('lxc-info', '-n', str(vmid), '-pH')
    pid = result.stdout.strip()
    return pid if result.returncode == 0 and pid.isdigit() else None


@contextlib.contextmanager
def _rootfs(vmid: int):
    """The container's root filesystem, read from the host.

    A running container is read through its init process, which needs no
    mount. A stopped one is mounted for the duration of the check and
    unmounted afterwards.
    """
    pid = _running_pid(vmid)
    if pid:
        yield Path(f'/proc/{pid}/root')
        return
    mounted = _run('pct', 'mount', str(vmid))
    if mounted.returncode != 0:
        yield None
        return
    try:
        yield Path(f'/var/lib/lxc/{vmid}/rootfs')
    finally:
        _run('pct', 'unmount', str(vmid))


def _executable(root: Path, path: str) -> bool:
    candidate = root / path.lstrip('/')
    try:
        return candidate.is_file() and os.access(candidate, os.X_OK)
    except OSError:
        return False


def root_shell(root: Path) -> str | None:
    """The shell lxc-attach would start as root, if it can start one."""
    shell = None
    try:
        for line in (root / 'etc/passwd').read_text(errors='replace').splitlines():
            fields = line.split(':')
            if len(fields) >= 7 and fields[0] == 'root':
                shell = fields[6].strip()
                break
    except OSError:
        pass
    if shell is None:
        shell = '/bin/sh'
    if not shell or any(shell.endswith(name) for name in NO_LOGIN):
        return None
    return shell if _executable(root, shell) else None


def _cmode(vmid: int) -> str:
    result = _run('pct', 'config', str(vmid))
    for line in result.stdout.splitlines():
        if line.startswith('cmode:'):
            return line.split(':', 1)[1].strip()
    return 'tty'


def status(vmid: int) -> dict:
    with _rootfs(vmid) as root:
        shell = root_shell(root) if root else None
    cmode = _cmode(vmid)
    return {'vmid': vmid, 'cmode': cmode, 'shell': shell, 'terminal': cmode == 'shell'}


def enable_terminal(vmid: int) -> dict:
    """Open the Proxmox console as a shell, when the image has one."""
    state = status(vmid)
    if state['shell'] and state['cmode'] != 'shell':
        if _run('pct', 'set', str(vmid), '--cmode', 'shell').returncode == 0:
            state.update(cmode='shell', terminal=True)
    return state


def disable_terminal(vmid: int) -> dict:
    if _cmode(vmid) == 'shell':
        _run('pct', 'set', str(vmid), '--cmode', 'console')
    return status(vmid)


def log_path(vmid: int) -> Path:
    return LOG_DIR / f'{int(vmid)}.console.log'


def _ensure_logrotate() -> None:
    try:
        if LOGROTATE.read_text() == LOGROTATE_POLICY:
            return
    except OSError:
        pass
    LOGROTATE.write_text(LOGROTATE_POLICY)
    os.chmod(LOGROTATE, 0o644)


def enable_log(vmid: int) -> Path:
    """Keep what the container writes to its console, the way `docker logs` does.

    liblxc copies the console of the container — the stdout and stderr of its
    entrypoint — into the file named by `lxc.console.logfile`, from the moment
    the container starts and across restarts, without touching the image.
    It is the only one of the lxc.console options the Proxmox configuration
    layer keeps; size and rotation are left to logrotate.

    The file starts empty on every creation: a new container, whether freshly
    installed or rebuilt by an update, has its own log, and the installer reads
    the first-boot credentials from it without finding a previous one's.
    """
    LOG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = log_path(vmid)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(descriptor)
    os.chmod(path, 0o600)
    conf = Path(f'/etc/pve/lxc/{int(vmid)}.conf')
    text = conf.read_text()
    current, _, snapshots = text.partition('\n[')
    wanted = f'lxc.console.logfile: {path}'
    kept = [line for line in current.splitlines() if not line.startswith('lxc.console.logfile:')]
    kept.append(wanted)
    rebuilt = '\n'.join(kept) + '\n'
    if snapshots:
        rebuilt += '\n[' + snapshots
    if rebuilt != text:
        conf.write_text(rebuilt)
    _ensure_logrotate()
    return path


def configure(vmid: int) -> dict:
    """Console log and Proxmox terminal of a container being created."""
    path = enable_log(vmid)
    state = enable_terminal(vmid)
    state['log'] = str(path)
    return state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('action', choices=('status', 'configure', 'enable-terminal', 'disable-terminal'))
    parser.add_argument('vmid', type=int, nargs='+')
    args = parser.parse_args(argv)
    action = {'status': status, 'configure': configure, 'enable-terminal': enable_terminal,
              'disable-terminal': disable_terminal}[args.action]
    results = [action(vmid) for vmid in args.vmid]
    print(json.dumps(results if len(results) > 1 else results[0]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
