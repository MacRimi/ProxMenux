#!/usr/bin/env python3
"""Give its DHCP address back to an OCI container that restarted itself.

Proxmox runs the DHCP client of a host-managed interface from the host and
starts it only when it starts the container. A container that reboots from
inside, as Home Assistant OS does from its settings, is started again by
Proxmox without that client and comes back with no address. The start hook of
every OCI container queues this check: once the container is up, the client
that is missing is started the way Proxmox starts it.

The client lives where the container was started from: one started from the
Monitor ends when the Monitor is restarted, and the address would be lost
when its lease runs out. The Monitor asks for every container when it starts.
"""
from __future__ import annotations

import fcntl
from pathlib import Path
import re
import subprocess
import sys
import time

CONFIGS = Path('/etc/pve/lxc')
HOOKS = Path('/var/lib/lxc')
PROC = Path('/proc')
LOCKS = Path('/run/proxmenux')
# Proxmox starts its own client right after the container; one that just
# started is left to it, and to the check its start hook queued.
SETTLE = 30
NAME_RE = re.compile(r'[A-Za-z0-9_.-]{1,15}')
START = 'PVE::LXC::manage_dhclient("start", $ARGV[0], $ARGV[1], $ARGV[2], "/proc/$ARGV[3]/root")'


def managed(config):
    """The host-managed interfaces of a container configuration that take
    their address by DHCP: [(name, ip version)]."""
    found = []
    for line in config.split('\n[', 1)[0].splitlines():
        match = re.match(r'net\d+:\s*(.*)', line)
        if not match:
            continue
        options = dict(part.split('=', 1) for part in match.group(1).split(',') if '=' in part)
        name = options.get('name', '')
        if options.get('host-managed') != '1' or options.get('link_down') == '1' or not NAME_RE.fullmatch(name):
            continue
        found += [(name, version) for key, version in (('ip', 4), ('ip6', 6)) if options.get(key) == 'dhcp']
    return found


def client_running(vmid, name, version):
    """Whether a DHCP client of the interface runs, with or without a lease yet."""
    mark = f'{HOOKS}/{vmid}/hook/dhclient{version}-{name}.pid'.encode()
    for entry in PROC.glob('[0-9]*/cmdline'):
        try:
            if mark in entry.read_bytes().split(b'\0'):
                return True
        except OSError:
            continue
    return False


def init_pid(vmid):
    result = subprocess.run(['lxc-info', '-n', str(vmid), '-pH'], capture_output=True, text=True, check=False, timeout=30)
    pid = result.stdout.strip()
    return int(pid) if result.returncode == 0 and pid.isdigit() and int(pid) > 0 else None


def running_for(pid):
    """Seconds since the init of the container started."""
    try:
        return time.time() - (PROC / str(pid)).stat().st_ctime
    except OSError:
        return 0.0


def containers():
    """The containers of this node with a host-managed interface on DHCP."""
    found = []
    for path in sorted(CONFIGS.glob('*.conf')):
        try:
            if path.stem.isdigit() and managed(path.read_text(errors='replace')):
                found.append(int(path.stem))
        except OSError:
            continue
    return found


def start_client(vmid, name, version, pid):
    # In a scope of its own: the client stays when this check ends.
    result = subprocess.run(['systemd-run', '--scope', '--quiet', '--collect', 'perl', '-MPVE::LXC', '-e', START,
                             str(vmid), str(version), name, str(pid)],
                            capture_output=True, text=True, check=False, timeout=180)
    return result.returncode == 0


def repair(vmid, settle=0):
    """Start the DHCP clients a running container is missing. Returns the
    interfaces that got one: [(name, ip version)]."""
    try:
        config = (CONFIGS / f'{vmid}.conf').read_text(errors='replace')
    except OSError:
        return []
    wanted = managed(config)
    if not wanted:
        return []
    pid = init_pid(vmid)
    if pid is None or running_for(pid) < settle:
        return []
    started = []
    for name, version in wanted:
        if not client_running(vmid, name, version) and start_client(vmid, name, version, pid):
            started.append((name, version))
    return started


def check(vmid, settle=0):
    with (LOCKS / f'oci-dhcp-lease-{vmid}.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        for name, version in repair(vmid, settle):
            print(f'CT {vmid}: DHCP client of {name} (IPv{version}) started again', flush=True)


def main():
    if len(sys.argv) != 2 or not (sys.argv[1].isdigit() or sys.argv[1] == '--all'):
        print('usage: oci_dhcp_lease.py <vmid> | --all', file=sys.stderr)
        return 2
    LOCKS.mkdir(parents=True, exist_ok=True)
    if sys.argv[1] == '--all':
        for vmid in containers():
            check(vmid, SETTLE)
    else:
        check(int(sys.argv[1]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
