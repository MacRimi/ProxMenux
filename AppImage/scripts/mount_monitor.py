"""Sprint 13: detect remote mount issues that PVE storage monitoring misses.

Parses ``/proc/mounts`` filtering NFS/CIFS/SMB entries, then for each
one runs a timeout-bounded ``stat`` to catch stale handles. Stale NFS
is the typical failure mode that broke a user's LXC: the mount looks
present in ``/proc/mounts`` but any access either blocks indefinitely
or returns ``ESTALE``. Meanwhile any app in the LXC that keeps writing
to that path appends to the underlying directory on the local
filesystem (because the mount is effectively gone), which silently
fills up the LXC's root disk and eventually kills the container.

This module sits next to ``proxmox_storage_monitor.py`` (which only
covers PVE-registered storages) and complements it for arbitrary
remote mounts done outside PVE (e.g. ``/etc/fstab`` entries, ad-hoc
``mount -t cifs``, etc.).

Scope for Sprint 13:
- Host-only. Mounts done inside running LXCs are out of scope —
  reaching them needs ``pct exec`` per container which is slow and
  can hang on a corrupted guest. That's tracked as a follow-up.
- Detects: stale (timeout/ESTALE), read-only although its configuration
  asks for read-write, plain reachable.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from typing import Any, Optional

# `nfs`, `nfs4`, `cifs`, `smbfs`, `smb3`, etc. — any FS type whose name
# starts with one of the three remote families. Keeps the filter
# permissive without listing every variant.
_REMOTE_FS_RE = re.compile(r'^(nfs|cifs|smb)', re.IGNORECASE)

# Per-mount stat timeout. Configurable via env var so an admin running
# on a slow link can bump it without waiting for a code change. Default
# is 2 seconds — long enough that a healthy NFS over LAN responds, short
# enough that a stale mount doesn't block the health-check pipeline.
_STAT_TIMEOUT_SEC = int(os.environ.get('PROXMENUX_MOUNT_STAT_TIMEOUT', '2'))

# Top-level cache TTL: 60 s. Each scan is cheap (one stat per mount)
# but we don't want to re-stat on every API hit either, especially when
# the dashboard polls every 5 s.
_CACHE_TTL_SEC = 60

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {
    'scanned_at': 0.0,
    'mounts': [],
}


def _read_proc_mounts() -> list[dict[str, Any]]:
    """Parse /proc/mounts and return only NFS/CIFS/SMB entries.

    Each entry: source, target, fstype, options (raw string), readonly.
    Anything that fails to parse is skipped silently — this is a
    monitor, not a validator, and a malformed line shouldn't crash the
    health pipeline.
    """
    out: list[dict[str, Any]] = []
    try:
        with open('/proc/mounts', 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 4:
                    continue
                source, target, fstype, options = parts[0], parts[1], parts[2], parts[3]
                if not _REMOTE_FS_RE.match(fstype):
                    continue
                opts_set = set(options.split(','))
                out.append({
                    'source': source,
                    'target': target,
                    'fstype': fstype,
                    'options': options,
                    'readonly': 'ro' in opts_set,
                })
    except OSError:
        pass
    return out


def _check_reachable(target: str, timeout: int = _STAT_TIMEOUT_SEC) -> dict[str, Any]:
    """Run ``stat`` against the mount target with a hard timeout.

    Returns ``{reachable: bool, error: str | None}``. We use the
    external ``stat`` binary rather than ``os.stat`` because the C
    syscall blocks the GIL when an NFS mount is stale, and a hung
    syscall would freeze the entire health monitor thread —
    subprocess gives us a real timeout we can enforce.
    """
    try:
        result = subprocess.run(
            ['stat', '-c', '%i', target],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return {'reachable': True, 'error': None}
        err = (result.stderr or result.stdout).strip() or 'stat returned non-zero'
        return {'reachable': False, 'error': err}
    except subprocess.TimeoutExpired:
        return {
            'reachable': False,
            'error': f'stat timed out after {timeout}s (likely stale NFS handle)',
        }
    except OSError as e:
        return {'reachable': False, 'error': str(e)}


def _disk_usage(target: str, timeout: int = _STAT_TIMEOUT_SEC) -> dict[str, Any]:
    """Run ``df`` against the mount target with a hard timeout.

    Like ``_check_reachable``, we shell out so a stale NFS doesn't
    freeze the calling thread. Returns ``{total, used, available}`` in
    bytes when the call succeeds, ``None`` for each field when it
    times out or fails — the modal renders "n/a" in that case.
    """
    empty = {'total_bytes': None, 'used_bytes': None, 'available_bytes': None}
    try:
        result = subprocess.run(
            ['df', '-B1', '--output=size,used,avail', target],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return empty
        # Output: header + 1 data line. Splitting on whitespace gives 3
        # ints when df succeeds.
        lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            return empty
        parts = lines[-1].split()
        if len(parts) < 3:
            return empty
        try:
            return {
                'total_bytes': int(parts[0]),
                'used_bytes': int(parts[1]),
                'available_bytes': int(parts[2]),
            }
        except ValueError:
            return empty
    except (subprocess.TimeoutExpired, OSError):
        return empty


def _is_proxmox_managed(target: str) -> bool:
    """True when the mount target lives under ``/mnt/pve/``.

    PVE auto-mounts every NFS/CIFS storage at ``/mnt/pve/<storage_id>``
    and that directory is owned by ``pveproxy`` — no other tool uses
    it. So a target starting with that prefix is reliably a
    PVE-managed mount and the dashboard can flag it as such without
    paying a ``pvesh`` round-trip per mount.
    """
    return target.startswith('/mnt/pve/')


def storage_for_mount(target: str, source: str,
                      host_mounts: Optional[list[dict[str, Any]]] = None) -> Optional[str]:
    """The Proxmox storage a remote mount belongs to, or None.

    A host mount under ``/mnt/pve/<storage_id>`` is that storage. A mount
    inside a container that shows the same source as one of those host
    mounts (a bind mount of the storage, or the same share mounted again)
    belongs to it as well, so the storage exclusions reach it too.
    """
    if target.startswith('/mnt/pve/'):
        return target.split('/')[3] or None
    if not source:
        return None
    if host_mounts is None:
        try:
            host_mounts = scan_remote_mounts()
        except Exception:
            return None
    for mount in host_mounts:
        host_target = mount.get('target', '')
        if mount.get('source') == source and host_target.startswith('/mnt/pve/'):
            return host_target.split('/')[3] or None
    return None


# Where a remote mount is asked to be read-only. An NFS or CIFS mount is
# read-only only because the mount request said so (the client does not
# switch to read-only on its own), so a read-only mount is a problem only
# when the configuration that mounts it asks for read-write.
_STORAGE_CFG = '/etc/pve/storage.cfg'
_FSTAB = '/etc/fstab'
_SYSTEMD_MOUNT_DIR = '/etc/systemd/system'
_LXC_CONF_DIR = '/etc/pve/lxc'


def _requests_ro(options: str) -> bool:
    return 'ro' in {o.strip() for o in (options or '').split(',')}


def _read_lines(path: str) -> list[str]:
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read().splitlines()
    except OSError:
        return []


def _storage_options() -> dict[str, str]:
    """The mount options of each storage in storage.cfg, by storage id."""
    out: dict[str, str] = {}
    current = None
    for line in _read_lines(_STORAGE_CFG):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line[0].isspace():
            current = line.split(':', 1)[1].strip() if ':' in line else None
            if current:
                out[current] = ''
            continue
        parts = line.split(None, 1)
        if current and parts[0] == 'options':
            out[current] = parts[1].strip() if len(parts) > 1 else ''
    return out


def _fstab_options(path: str) -> dict[str, str]:
    """The options of each fstab entry, by mount point."""
    out: dict[str, str] = {}
    for line in _read_lines(path):
        parts = line.split()
        if len(parts) >= 4 and not parts[0].startswith('#'):
            out[parts[1].rstrip('/') or '/'] = parts[3]
    return out


def _systemd_mount_options() -> dict[str, str]:
    """The options of each systemd mount unit, by mount point."""
    out: dict[str, str] = {}
    try:
        names = [n for n in os.listdir(_SYSTEMD_MOUNT_DIR) if n.endswith('.mount')]
    except OSError:
        return out
    for name in names:
        where, options = None, ''
        for line in _read_lines(os.path.join(_SYSTEMD_MOUNT_DIR, name)):
            key, _, value = line.strip().partition('=')
            if key == 'Where':
                where = value.strip()
            elif key == 'Options':
                options = value.strip()
        if where:
            out[where.rstrip('/') or '/'] = options
    return out


def _lxc_mount_points(vmid: str) -> dict[str, dict[str, Any]]:
    """The mount points of a container, by target: source and ro flag."""
    out: dict[str, dict[str, Any]] = {}
    for line in _read_lines(os.path.join(_LXC_CONF_DIR, f'{vmid}.conf')):
        line = line.strip()
        if line.startswith('['):
            break
        match = re.match(r'^mp\d+:\s*(.+)$', line)
        if not match:
            continue
        parts = [p.strip() for p in match.group(1).split(',')]
        values = dict(p.split('=', 1) for p in parts[1:] if '=' in p)
        if values.get('mp'):
            out[values['mp'].rstrip('/') or '/'] = {
                'source': parts[0],
                'ro': values.get('ro', '0').lower() in ('1', 'yes', 'true', 'on'),
            }
    return out


def configured_readonly(target: str, lxc_vmid: str = '', ct_pid: str = '',
                        host_mounts: Optional[list[dict[str, Any]]] = None) -> Optional[bool]:
    """Whether the configuration that mounts ``target`` asks for read-only.

    True or False when a Proxmox storage, fstab, a systemd mount unit or a
    container mount point names the mount; None when none of them does (a
    mount made by hand or by another tool), which is taken as asked for.
    A container mount point that binds a host mount which is itself
    read-only inherits it, so it is None too: the host mount is the one
    reported if that is wrong.
    """
    key = target.rstrip('/') or '/'
    if lxc_vmid:
        mount_point = _lxc_mount_points(lxc_vmid).get(key)
        if mount_point:
            if mount_point['ro']:
                return True
            source = mount_point['source']
            for host in host_mounts or []:
                host_target = host.get('target', '')
                if host.get('readonly') and (source == host_target or source.startswith(host_target.rstrip('/') + '/')):
                    return None
            return False
        if ct_pid:
            options = _fstab_options(f'/proc/{ct_pid}/root/etc/fstab').get(key)
            if options is not None:
                return _requests_ro(options)
        return None
    if key.startswith('/mnt/pve/'):
        options = _storage_options().get(key.split('/')[3])
        if options is not None:
            return _requests_ro(options)
    for table in (_fstab_options(_FSTAB), _systemd_mount_options()):
        if key in table:
            return _requests_ro(table[key])
    return None


def mount_status(mount: dict[str, Any], reachable: bool, lxc_vmid: str = '', ct_pid: str = '',
                 host_mounts: Optional[list[dict[str, Any]]] = None) -> str:
    """``stale``, ``readonly`` (read-only although configured read-write) or ``ok``."""
    if not reachable:
        return 'stale'
    if mount.get('readonly') and configured_readonly(
            mount.get('target', ''), lxc_vmid, ct_pid, host_mounts) is False:
        return 'readonly'
    return 'ok'


def scan_remote_mounts(force: bool = False) -> list[dict[str, Any]]:
    """Top-level scan: list each remote mount with its health status.

    Cached for ``_CACHE_TTL_SEC`` so back-to-back API hits don't all
    pay the stat cost. Pass ``force=True`` to bypass the cache (used
    by the health monitor to make sure each poll round sees fresh
    state).

    Each entry adds:
    - ``reachable``: bool
    - ``error``: str | None
    - ``status``: 'ok' | 'stale' | 'readonly'
        ``stale`` wins over ``readonly`` when both apply — a stale
        mount is a higher-severity issue.
    """
    now = time.time()
    if not force:
        with _cache_lock:
            if now - _cache.get('scanned_at', 0) < _CACHE_TTL_SEC:
                return list(_cache.get('mounts', []))

    raw = _read_proc_mounts()
    enriched: list[dict[str, Any]] = []
    for m in raw:
        health = _check_reachable(m['target'])
        entry = dict(m)
        entry['reachable'] = health['reachable']
        entry['error'] = health['error']
        entry['proxmox_managed'] = _is_proxmox_managed(m['target'])
        # df only when the mount is reachable — running df on a stale
        # mount blocks until the same timeout as stat, doubling the
        # delay for nothing useful.
        if health['reachable']:
            entry.update(_disk_usage(m['target']))
        else:
            entry.update({'total_bytes': None, 'used_bytes': None, 'available_bytes': None})
        entry['status'] = mount_status(m, health['reachable'])
        enriched.append(entry)

    with _cache_lock:
        _cache['scanned_at'] = now
        _cache['mounts'] = enriched
    return enriched


def get_unhealthy_mounts() -> list[dict[str, Any]]:
    """Convenience: only return mounts whose status is not ``ok``."""
    return [m for m in scan_remote_mounts() if m.get('status') != 'ok']


# ---------------------------------------------------------------------------
# LXC mount scanning (Sprint 13.24)
# ---------------------------------------------------------------------------
#
# The case the user reported was an NFS mount **inside** an LXC going stale:
# the host doesn't see the mount in its own /proc/mounts, so the host scan
# above misses it entirely. The container, meanwhile, keeps writing to the
# stale path which silently fills its rootfs.
#
# We list running LXCs via `pct list`, then peek into each one's
# /proc/self/mounts via `pct exec`. Both calls carry a hard timeout
# (`pct exec` blocks until forever on a corrupted CT) so the health
# monitor thread never freezes here.
#
# Stale detection runs from the host using `/proc/<pid>/root/<target>`
# rather than `pct exec stat`, which avoids spawning a second exec per
# mount and is also faster.

# Per-CT timeout. `pct exec` first contacts the container's pveproxy
# socket and then runs the command; 3s covers a healthy CT comfortably.
_LXC_EXEC_TIMEOUT_SEC = int(os.environ.get('PROXMENUX_LXC_EXEC_TIMEOUT', '3'))

_lxc_cache_lock = threading.Lock()
_lxc_cache: dict[str, Any] = {
    'scanned_at': 0.0,
    'mounts': [],
}


def _has_any_running_lxc() -> bool:
    """Cheap "is at least one CT running?" probe.

    Walks ``/proc`` looking for any process whose ``comm`` is
    ``lxc-start`` (the init shim that spawns CT pid 1). Bails on the
    first match. Costs ~1-5ms even on hosts with thousands of
    processes. Used as a short-circuit before the much more expensive
    `pct list` chain in `scan_lxc_mounts`.
    """
    try:
        for entry in os.scandir('/proc'):
            if not entry.name.isdigit():
                continue
            try:
                with open(f'/proc/{entry.name}/comm', 'r') as f:
                    if f.read().strip() == 'lxc-start':
                        return True
            except (OSError, IOError):
                continue
    except OSError:
        # If /proc is unreadable something is very wrong; let the
        # caller proceed with the full scan rather than silently
        # claiming no CTs run.
        return True
    return False


def _read_lxc_name(vmid: str) -> str:
    """Look up the CT hostname from /etc/pve/lxc/<vmid>.conf without
    invoking ``pct``. Returns '' if the file is unreadable."""
    for path in (f'/etc/pve/lxc/{vmid}.conf', f'/var/lib/lxc/{vmid}/config'):
        try:
            with open(path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('hostname:'):
                        return line.split(':', 1)[1].strip()
                    if line.startswith('lxc.uts.name'):
                        # `lxc.uts.name = foo`
                        return line.split('=', 1)[1].strip()
        except (OSError, IOError):
            continue
    return ''


def _list_running_lxcs() -> list[dict[str, str]]:
    """Return ``[{vmid, name, pid}]`` for every running LXC.

    We need ``pid`` (the init process inside the CT, visible to the
    host) so we can stat the mount target via ``/proc/<pid>/root/...``
    without entering the container with another ``pct exec``.

    Implementation walks ``/proc`` for ``lxc-start -F -n <vmid>``
    processes — the userspace shim that supervises each running CT —
    and resolves the CT init pid via ``lxc-info -p`` (~2 ms) instead
    of the previous ``pct status --verbose`` chain (~500 ms per CT).
    On a 7-CT host this collapses ~7 seconds of subprocess churn into
    a single /proc walk plus seven 2 ms calls, dropping the full
    ``scan_lxc_mounts`` cost from ~8 s to <100 ms.
    """
    out: list[dict[str, str]] = []
    try:
        proc_entries = list(os.scandir('/proc'))
    except OSError:
        return out

    for entry in proc_entries:
        if not entry.name.isdigit():
            continue
        try:
            with open(f'/proc/{entry.name}/comm', 'r') as f:
                if f.read().strip() != 'lxc-start':
                    continue
            with open(f'/proc/{entry.name}/cmdline', 'rb') as f:
                cmdline = f.read().split(b'\x00')
        except (OSError, IOError):
            continue

        # cmdline like [b'/usr/bin/lxc-start', b'-F', b'-n', b'<vmid>', b'']
        vmid = ''
        try:
            idx = cmdline.index(b'-n')
            if idx + 1 < len(cmdline):
                vmid = cmdline[idx + 1].decode('utf-8', errors='replace').strip()
        except ValueError:
            continue
        if not vmid:
            continue

        # v1.2.1.4 perf audit: previously this called `lxc-info -n <vmid> -p`
        # for every running CT on every scan tick. With N CTs that's N
        # subprocesses per cycle (lxc-info forks + execs + parses its own
        # config to give us a single number we can read directly). The CT's
        # init PID is the first child of the supervising lxc-start process
        # we just identified — readable from /proc with zero subprocess
        # cost.
        pid = ''
        try:
            with open(f'/proc/{entry.name}/task/{entry.name}/children', 'r') as f:
                children = f.read().split()
            if children:
                pid = children[0]
        except (OSError, IOError):
            # Fallback to lxc-info only if the /proc read failed — keeps
            # behaviour identical for any edge case where the children
                # file is unreadable (race with CT stop, kernel without
                # CONFIG_PROC_CHILDREN, etc.).
            try:
                p2 = subprocess.run(
                    ['lxc-info', '-n', vmid, '-p'],
                    capture_output=True, text=True, timeout=2,
                )
                if p2.returncode == 0:
                    for ln in p2.stdout.splitlines():
                        if ln.strip().lower().startswith('pid:'):
                            pid = ln.split(':', 1)[1].strip()
                            break
            except (subprocess.TimeoutExpired, OSError):
                pass

        out.append({'vmid': vmid, 'name': _read_lxc_name(vmid), 'pid': pid})

    # Stable ordering by vmid for deterministic output.
    out.sort(key=lambda c: int(c['vmid']) if c['vmid'].isdigit() else 0)
    return out


def _read_lxc_mounts(ct: dict[str, str]) -> list[dict[str, Any]]:
    """Read remote FS mounts inside a running CT.

    Uses ``/proc/<host_pid>/mounts`` (the kernel exposes every running
    process's mount namespace there), so the host can read the CT's
    full mount table directly with no ``pct exec`` subprocess. Returns
    ``[]`` on any failure rather than raising — a single bad CT
    shouldn't break the scan of the rest.

    Accepts a ``ct`` dict (from `_list_running_lxcs`) instead of a
    bare vmid because we need the host PID, which is only available
    after the lxc-info lookup.
    """
    out: list[dict[str, Any]] = []
    pid = ct.get('pid')
    if not pid:
        return out
    try:
        with open(f'/proc/{pid}/mounts', 'r') as f:
            mount_lines = f.read().splitlines()
    except (OSError, IOError):
        return out
    for line in mount_lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        source, target, fstype, options = parts[0], parts[1], parts[2], parts[3]
        if not _REMOTE_FS_RE.match(fstype):
            continue
        out.append({
            'source': source,
            'target': target,
            'fstype': fstype,
            'options': options,
            'readonly': 'ro' in set(options.split(',')),
        })
    return out


# Pseudo / virtual filesystems we never want to surface as a "mount
# nearing capacity" — these are kernel-managed and the numbers from
# statvfs are either nonsense (cgroup, sysfs) or change too fast to
# alert on (tmpfs).
_PSEUDO_FS = frozenset({
    'proc', 'sysfs', 'devpts', 'devtmpfs', 'tmpfs', 'mqueue', 'pstore',
    'cgroup', 'cgroup2', 'bpf', 'tracefs', 'debugfs', 'configfs',
    'securityfs', 'fuse.lxcfs', 'fusectl', 'autofs', 'binfmt_misc',
    'hugetlbfs', 'efivarfs', 'rpc_pipefs', 'nsfs', 'overlay',
})


def scan_lxc_mount_capacity(force: bool = False) -> list[dict[str, Any]]:
    """Capacity scan of mountpoints inside every running LXC.

    Sibling of `scan_lxc_mounts` — same /proc-walk and lxc-info pattern
    — but enumerates ALL real filesystems (not just NFS/CIFS/SMB) and
    returns capacity numbers via ``os.statvfs`` on the host-side
    namespace path ``/proc/<host_pid>/root/<target>``. Used by the
    Phase 3 ``_check_lxc_mount_capacity`` health check.

    Skips:
      - Pseudo-filesystems (proc, sysfs, tmpfs, cgroup, lxcfs, …) —
        their capacity numbers are kernel bookkeeping, not user data.
      - The CT rootfs (``/``) — already covered by ``_check_lxc_disk_usage``.
      - Mounts that fail statvfs (stale handle, perms): silently
        skipped so a hung NFS doesn't blow up the entire scan.

    Returns ``[{vmid, name, mount, fstype, total_bytes, used_bytes,
    available_bytes, usage_percent}, …]``. The 60s cache is shared
    with ``scan_lxc_mounts`` to avoid duplicate /proc walks; the LXC
    list is scanned once, the per-mount data is cheap (statvfs is
    a syscall, not subprocess) so we don't add a second cache layer.
    """
    if not force and not _has_any_running_lxc():
        return []

    out: list[dict[str, Any]] = []
    for ct in _list_running_lxcs():
        host_pid = ct.get('pid')
        vmid = ct.get('vmid')
        name = ct.get('name', '')
        if not host_pid or not vmid:
            continue
        try:
            with open(f'/proc/{host_pid}/mounts', 'r') as f:
                lines = f.read().splitlines()
        except (OSError, IOError):
            continue

        for line in lines:
            parts = line.split()
            if len(parts) < 4:
                continue
            source, target, fstype, options = parts[0], parts[1], parts[2], parts[3]

            # Skip pseudo-filesystems and the CT rootfs.
            if fstype in _PSEUDO_FS or fstype.startswith('fuse.'):
                continue
            if target == '/':
                continue

            # statvfs through the CT's mount namespace.
            host_path = f'/proc/{host_pid}/root{target}'
            try:
                st = os.statvfs(host_path)
            except (OSError, FileNotFoundError):
                continue
            if st.f_blocks == 0:
                continue  # zero-size mount (sometimes an empty cgroup)

            total = st.f_blocks * st.f_frsize
            available = st.f_bavail * st.f_frsize
            used = total - (st.f_bfree * st.f_frsize)
            pct = (used / total) * 100 if total > 0 else 0.0

            out.append({
                'vmid': vmid,
                'name': name,
                'mount': target,
                'source': source,
                'fstype': fstype,
                'readonly': 'ro' in set(options.split(',')),
                'total_bytes': total,
                'used_bytes': used,
                'available_bytes': available,
                'usage_percent': round(pct, 1),
            })
    return out


def _check_reachable_from_host(host_pid: str, ct_target: str,
                               timeout: int = _STAT_TIMEOUT_SEC) -> dict[str, Any]:
    """Stat a CT-internal path through ``/proc/<pid>/root``.

    The Linux kernel exposes every running process's mount namespace
    under ``/proc/<pid>/root``, so the host can reach the CT's view of
    a path without spawning a second ``pct exec``. Same timeout
    semantics as the host-side ``_check_reachable``.
    """
    if not host_pid:
        return {'reachable': False, 'error': 'CT pid unknown'}
    full_path = f'/proc/{host_pid}/root{ct_target}'
    try:
        result = subprocess.run(
            ['stat', '-c', '%i', full_path],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            return {'reachable': True, 'error': None}
        err = (result.stderr or result.stdout).strip() or 'stat returned non-zero'
        return {'reachable': False, 'error': err}
    except subprocess.TimeoutExpired:
        return {
            'reachable': False,
            'error': f'stat timed out after {timeout}s (likely stale handle inside CT)',
        }
    except OSError as e:
        return {'reachable': False, 'error': str(e)}


def scan_lxc_mounts(force: bool = False) -> list[dict[str, Any]]:
    """Top-level scan of remote mounts inside every running LXC.

    Cached for the same TTL as ``scan_remote_mounts``. Each entry
    follows the same shape as host mounts plus three CT-specific
    fields: ``lxc_id``, ``lxc_name``, ``lxc_pid``. ``proxmox_managed``
    is always ``False`` for LXC mounts (PVE doesn't manage mounts done
    inside containers).
    """
    now = time.time()
    if not force:
        with _lxc_cache_lock:
            if now - _lxc_cache.get('scanned_at', 0) < _CACHE_TTL_SEC:
                return list(_lxc_cache.get('mounts', []))

    # Cheap pre-check: skip the whole pct invocation chain when there
    # are no running CTs at all. `pct list` alone takes ~700ms on a
    # typical Proxmox host (perl startup + cluster file lock), so on
    # nodes that only run VMs (or none at all) this short-circuit was
    # accounting for ~0.23% of baseline CPU every 5 minutes for a result
    # that is always empty.
    #
    # Detection: walk /proc looking for any `lxc-start` process. This
    # is the actual init for a running CT. `/run/lxc/` always contains
    # `lock/` and `var/` admin dirs even with zero CTs, so it can't be
    # used as a count signal. /proc walk costs ~1-5ms and bails on the
    # first match.
    if not _has_any_running_lxc():
        with _lxc_cache_lock:
            _lxc_cache['scanned_at'] = now
            _lxc_cache['mounts'] = []
        return []

    enriched: list[dict[str, Any]] = []
    host_mounts = _read_proc_mounts()
    for ct in _list_running_lxcs():
        ct_mounts = _read_lxc_mounts(ct)
        for m in ct_mounts:
            health = _check_reachable_from_host(ct['pid'], m['target'])
            entry = dict(m)
            entry['lxc_id'] = ct['vmid']
            entry['lxc_name'] = ct['name']
            entry['lxc_pid'] = ct['pid']
            entry['proxmox_managed'] = False
            entry['reachable'] = health['reachable']
            entry['error'] = health['error']
            # Disk usage on a CT mount: needs running df *inside* the CT
            # (host's df can't traverse into /proc/<pid>/root/<target> for
            # non-bind-mounted FS). Skip for now — costs another pct exec
            # per mount and the dashboard's "Capacity" section would be
            # misleading for stale mounts anyway.
            entry['total_bytes'] = None
            entry['used_bytes'] = None
            entry['available_bytes'] = None
            entry['status'] = mount_status(m, health['reachable'], ct['vmid'], ct['pid'], host_mounts)
            enriched.append(entry)

    with _lxc_cache_lock:
        _lxc_cache['scanned_at'] = now
        _lxc_cache['mounts'] = enriched
    return enriched
