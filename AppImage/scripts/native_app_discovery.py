#!/usr/bin/env python3
# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# Author      : VAIO73
# GitHub      : github.com/Vaso73
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 14/10/2026
# ==========================================================
# Description:
# On-demand native LXC discovery from service and installation metadata.
# Reads bounded data only; never executes discovered programs, starts guests,
# registers applications or infers their update mechanism.
# ==========================================================
"""Separate from catalog detection: callers must explicitly request a scan."""

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import threading
import time

TOTAL_SECONDS = 20
PROBE_SECONDS = 3
OUTPUT_BYTES = 64 * 1024
MAX_RECORDS = 256
MAX_CANDIDATES = 50
CACHE_SECONDS = 300
LOCAL_CONFIG = Path('/etc/pve/local/lxc')
OCI_ROOT = Path('/usr/local/share/proxmenux/oci/instances')
UPDATE_LOCK_ROOT = Path('/run/lock')
_cache = {}
_locks = {}
_mutex = threading.Lock()
_PATH = re.compile(r'/[A-Za-z0-9_.+/@-]{1,510}\Z')
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.+@-]{0,63}\Z')
_VERSION = re.compile(r'v?\d+(?:\.\d+){1,4}(?:[-+._][A-Za-z0-9.-]+)?\Z')
_SYSTEM = {
    'ssh', 'sshd', 'cron', 'crond', 'postfix', 'rsyslog', 'syslog', 'syslog-ng',
    # Alpine/OpenRC system logging and service supervision are not apps.
    'klogd', 'syslogd', 'openrc-user', 'runit', 'runsvdir', 'runsv', 'supervise-daemon',
    'dbus', 'dbus-broker', 'systemd', 'udev', 'networking', 'network', 'networkmanager',
    'dhcpcd', 'dhclient', 'chrony', 'chronyd', 'ntp', 'ntpd', 'openntpd', 'agetty',
    'getty', 'login', 'polkit', 'polkitd', 'accounts-daemon', 'acpid', 'anacron',
    'docker', 'containerd', 'containerd-shim', 'podman', 'qemu-guest-agent', 'rngd',
    'auditd', 'logrotate', 'local', 'bootmisc', 'hostname', 'hwclock', 'modules', 'master',
    'proxmox-boot-sync', 'pve-container', 'pve-firewall', 'pvefw-logger',
    'pvedaemon', 'pvestatd', 'pveproxy', 'pvescheduler', 'spiceproxy', 'lxc',
    'mount-ro', 'mdev', 'sysctl', 'sysfs', 'devfs', 'cgroups', 'rc', 'rcs', 'swap',
    'sleep', 'true', 'false', 'echo', 'cat', 'head', 'tail', 'tee', 'logger',
    'apt', 'apt-get', 'dpkg', 'dpkg-query', 'apk', 'unattended-upgrades',
    'fstrim', 'fsck', 'fsckd', 'e2scrub', 'e2scrub-all', 'e2scrub-reap',
    'irqbalance', 'smartd', 'smartmontools', 'rpcbind', 'nfs-common', 'nfs-server',
    'rpc-statd', 'rpc-statd-notify', 'rpc-gssd', 'rpc-svcgssd', 'nftables', 'iptables',
    'ip6tables', 'firewalld', 'ufw', 'resolvconf', 'wpa-supplicant', 'modemmanager',
    'console-setup', 'keyboard-setup', 'plymouth', 'halt', 'reboot', 'shutdown',
    'rc-local', 'ntpsec', 'networkd-dispatcher', 'busybox', 'atd', 'uuidd',
    # Common packaged daemons are infrastructure, not a user-managed app.
    'nginx', 'apache', 'apache2', 'httpd', 'lighttpd', 'haproxy', 'traefik',
    'redis', 'redis-server', 'memcached', 'mysql', 'mysqld', 'mariadb', 'mariadbd',
    'postgres', 'postgresql', 'mongod', 'mongodb', 'rabbitmq-server',
    'elasticsearch', 'opensearch', 'fail2ban', 'named', 'bind9', 'dnsmasq',
    'avahi-daemon', 'smbd', 'nmbd', 'samba', 'vsftpd', 'proftpd', 'cups', 'tor',
}
_RUNTIMES = re.compile(r'(?:python[0-9.]*|node(?:js)?|npm|pnpm|yarn|bun|sh|bash|dash|env|java|ruby|perl)\Z')
_PACKAGE_ROOT_RUNTIMES = {'node', 'nodejs', 'npm', 'pnpm', 'yarn', 'bun'}
_HELPER_ROLES = {
    'backup', 'bootstrap', 'bridge', 'cleanup', 'housekeeping', 'maintenance',
    'migrate', 'migration', 'restore', 'rotate', 'update', 'updater', 'upgrade',
    'watch', 'watchdog', 'worker',
}
_HESTIA_NGINX = '/usr/local/hestia/nginx/sbin/hestia-nginx'
_HESTIA_ROOT = '/usr/local/hestia'
_HESTIA_PANEL_PORT = 8083


class ProbeError(Exception):
    """Safe error code only; guest output must never become an API error."""


def bounded_run(argv, deadline):
    """Cap combined stdout/stderr while reading, and kill/reap the process group."""
    remaining = min(PROBE_SECONDS, deadline - time.monotonic())
    if remaining <= 0:
        raise ProbeError('deadline')
    end = time.monotonic() + remaining
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
    except OSError:
        raise ProbeError('unavailable') from None
    outputs = [bytearray(), bytearray()]
    try:
        with selectors.DefaultSelector() as poll:
            for index, stream in enumerate((proc.stdout, proc.stderr)):
                os.set_blocking(stream.fileno(), False)
                poll.register(stream, selectors.EVENT_READ, index)
            while poll.get_map():
                wait = end - time.monotonic()
                if wait <= 0:
                    raise ProbeError('timeout')
                for key, _ in poll.select(wait):
                    block = os.read(key.fileobj.fileno(), 4096)
                    if not block:
                        poll.unregister(key.fileobj)
                        continue
                    if sum(map(len, outputs)) + len(block) > OUTPUT_BYTES:
                        raise ProbeError('output_limit')
                    outputs[key.data].extend(block)
            try:
                proc.wait(timeout=max(0.001, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise ProbeError('timeout') from None
        if proc.returncode:
            raise ProbeError('read_failed')
        return outputs[0].decode('utf-8', errors='strict')
    except UnicodeError:
        raise ProbeError('invalid_data') from None
    finally:
        # Also clean up descendants that outlive a successfully exited wrapper.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()


# These are fixed read-only scripts, not guest-supplied shell or init scripts.
# awk emits only executable/script paths and WorkingDirectory, never arguments
# or environment values. OpenRC files are parsed as data, never sourced.
SERVICE_SCRIPT = r'''
command -v awk >/dev/null && command -v head >/dev/null || exit 1
n=0
for dir in /etc/systemd/system /usr/lib/systemd/system /lib/systemd/system /etc/init.d; do
  [ ! -d "$dir" ] || [ -r "$dir" ] || exit 1
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    case "$dir:$f" in /etc/init.d:*) kind=openrc;; *:*.service) kind=systemd;; *) continue;; esac
    n=$((n+1)); [ "$n" -le 256 ] || { printf 'LIMIT\n'; exit 0; }
    [ -r "$f" ] || exit 1
    content=$(timeout -s KILL 1 head -c 16385 "$f") || exit 1
    [ "${#content}" -le 16384 ] || { printf 'LIMIT\n'; exit 0; }
    printf '%s\n' "$content" | awk -v kind="$kind" -v file="$f" '
      function clean(v) {gsub(/^[ \t]+|[ \t]+$/, "", v); gsub(/^["\047]|["\047]$/, "", v); return v}
      /^ExecStart=/ {v=substr($0,11); sub(/^[-+!:@]+/, "", v); split(v,a,/[ \t]+/); exe=clean(a[1]); script=clean(a[2]); if(script !~ /^\//) script=""}
      /^WorkingDirectory=/ {dir=clean(substr($0,18))}
      /^command=/ {exe=clean(substr($0,9))}
      /^directory=/ {dir=clean(substr($0,11))}
      /^command_args=/ {v=clean(substr($0,14)); split(v,a,/[ \t]+/); script=clean(a[1]); if(script !~ /^\//) script=""}
      END {printf "S\t%s\t%s\t%s\t%s\t%s\n", file, kind, exe, script, dir}'
  done
done
printf 'END\n'
'''
PROCESS_SCRIPT = r'''
command -v readlink >/dev/null && command -v head >/dev/null || exit 1
n=0
for dir in /proc/[0-9]*; do
  [ -d "$dir" ] || continue
  n=$((n+1)); [ "$n" -le "$1" ] || { printf 'LIMIT\n'; exit 0; }
  # Never inspect Docker/OCI child workloads or read cmdline/environ.
  [ -d "$dir" ] || continue
  [ -r "$dir/cgroup" ] || exit 1
  group=$(timeout -s KILL 1 head -c 8193 "$dir/cgroup") || exit 1
  [ "${#group}" -le 8192 ] || { printf 'LIMIT\n'; exit 0; }
  case "$group" in *docker*|*libpod*|*kubepods*|*containerd*) continue;; esac
  # Kernel threads and vanished processes have no application executable.
  [ -L "$dir/exe" ] || continue
  exe=$(timeout -s KILL 1 readlink "$dir/exe") || continue
  cwd=$(timeout -s KILL 1 readlink "$dir/cwd") || continue
  printf 'P\t%s\t%s\t%s\n' "${dir##*/}" "$exe" "$cwd"
done
printf 'END\n'
'''
PORT_SCRIPT = r'''
command -v awk >/dev/null || exit 1
if command -v ss >/dev/null; then
  (timeout -s KILL 1 ss -H -lntp || printf 'FAILED\n') | awk -v cap="$1" '
    /^FAILED$/ {failed=1; exit}
    NR > cap {limited=1; exit}
    {port=$4; sub(/^.*:/,"",port); rest=$0
     # More than one owner is ambiguous; never choose the first arbitrarily.
     if (gsub(/pid=/,"pid=",rest)!=1) next
     if (match(rest,/pid=[0-9]+/)) {pid=substr(rest,RSTART+4,RLENGTH-4); printf "L\t%s\t%s\n",pid,port}}
    END {print failed ? "FAILED" : (limited ? "LIMIT" : "END")}'
elif command -v netstat >/dev/null; then
  (timeout -s KILL 1 netstat -lntp || printf 'FAILED\n') | awk -v cap="$1" '
    /^FAILED$/ {failed=1; exit}
    /^tcp/ {n++; if(n>cap) {limited=1; exit}; port=$4; sub(/^.*:/,"",port)
      pid=$7; sub(/\/.*$/,"",pid); if(pid ~ /^[0-9]+$/) printf "L\t%s\t%s\n",pid,port}
    END {print failed ? "FAILED" : (limited ? "LIMIT" : "END")}'
else
  exit 1
fi
'''
HESTIA_PANEL_SCRIPT = r'''
# The generic process collector intentionally stops after a bounded number of
# records and ignores shared listener ownership.  Hestia's master/worker pair
# can therefore be outside that generic result.  This narrow fallback never
# accepts a name alone: it requires Hestia's exact executable and its panel
# listener on the fixed local port.
[ -x /usr/local/hestia/nginx/sbin/hestia-nginx ] || { printf 'END\n'; exit 0; }
command -v pgrep >/dev/null && command -v readlink >/dev/null && command -v ss >/dev/null && command -v head >/dev/null || exit 1
n=0
for pid in $(pgrep -x hestia-nginx 2>/dev/null | head -n 9); do
  case "$pid" in *[!0-9]*|'') continue;; esac
  n=$((n+1)); [ "$n" -le 8 ] || { printf 'LIMIT\n'; exit 0; }
  exe=$(timeout -s KILL 1 readlink "/proc/$pid/exe") || continue
  [ "$exe" = /usr/local/hestia/nginx/sbin/hestia-nginx ] || continue
  cwd=$(timeout -s KILL 1 readlink "/proc/$pid/cwd") || continue
  if timeout -s KILL 1 ss -H -lntp | awk -v pid="$pid" '
    {port=$4; sub(/^.*:/,"",port)
     if (port == 8083 && index($0, "pid=" pid ",")) found=1}
    END {exit(found ? 0 : 1)}'; then
    printf 'H\t%s\t%s\t%s\t8083\n' "$pid" "$exe" "$cwd"
  fi
done
printf 'END\n'
'''
FOOTPRINT_SCRIPT = r'''
[ -f "$1" ] && [ -r "$1" ] || exit 1
printf 'FILE\n'
if [ -f "$2/package.json" ]; then
  [ -r "$2/package.json" ] || exit 1
  timeout -s KILL 1 head -c 8192 "$2/package.json"
fi
'''
MANIFEST_FOOTPRINT_SCRIPT = r'''
command -v head >/dev/null && command -v readlink >/dev/null || exit 1
# Resolve only the operator-owned working directory and its declared parent.
# A release symlink may change the concrete version directory, but it must not
# escape the bounded custom application root supplied by the host.
workdir=$(timeout -s KILL 1 readlink -f "$1") || exit 1
anchor=$(timeout -s KILL 1 readlink -f "$2") || exit 1
parent=$(timeout -s KILL 1 readlink -f "$3") || exit 1
case "$anchor" in "$parent"/*) ;; *) printf 'OUTSIDE\n'; exit 0;; esac
case "$workdir" in "$anchor"|"$anchor"/*) ;; *) printf 'OUTSIDE\n'; exit 0;; esac
for relative in package.json server/package.json; do
  candidate="$workdir/$relative"
  [ -f "$candidate" ] && [ -r "$candidate" ] || continue
  resolved=$(timeout -s KILL 1 readlink -f "$candidate") || exit 1
  case "$resolved" in "$workdir"/*) ;; *) printf 'OUTSIDE\n'; exit 0;; esac
  printf 'MANIFEST\t%s\n' "$relative"
  timeout -s KILL 1 head -c 8192 "$resolved"
  exit 0
done
printf 'MISSING\n'
'''


def _path(value):
    return bool(isinstance(value, str) and _PATH.fullmatch(value)
                and '..' not in value.split('/'))


def _system(name):
    raw = name.lower().removesuffix('.service')
    stem = raw.split('@')[0]
    return (raw.startswith('user@') or stem in _SYSTEM
            or (raw.startswith('php') and raw.endswith('-fpm'))
            or stem.startswith((
        'systemd-', 'dbus-', 'getty', 'containerd-', 'apt-', 'dpkg-', 'e2scrub',
        'unattended-', 'ifup', 'ifdown', 'user@', 'btrfs-', 'lvm2-', 'lxc-')))


def _helper(name):
    """Reject service roles that support an application but are not one themselves."""
    raw = name.lower().removesuffix('.service')
    if raw.endswith('@'):
        return True  # A systemd template is not a concrete running application.
    return any(part in _HELPER_ROLES for part in re.split(r'[._-]+', raw) if part)


def _hestia_panel_process(executable, ports):
    """Recognize only Hestia's own bound control-panel process.

    Hestia's generated init unit does not expose an ExecStart that the generic
    service parser may treat as an application.  Its panel process and port are
    stable, local runtime metadata, so this stays narrower than accepting
    arbitrary vendor services or a generic web server.
    """
    return executable == _HESTIA_NGINX and _HESTIA_PANEL_PORT in ports


def _custom(path):
    if not _path(path):
        return False
    if path.startswith(('/opt/', '/srv/', '/usr/local/')):
        return True
    # Native apps commonly keep their runtime below /home/<service-user>/<app>.
    # Do not accept a home directory itself: a second path component is required.
    parts = path.split('/')
    return len(parts) >= 4 and parts[1] == 'home' and bool(parts[2]) and bool(parts[3])


def _manifest_bounds(executable, directory):
    """Return a narrow, operator-owned boundary for a runtime manifest probe."""
    try:
        shared = os.path.commonpath((executable, directory))
    except ValueError:
        shared = ''
    anchor = shared if _custom(shared) else directory
    parts = anchor.split('/')
    if anchor.startswith(('/opt/', '/srv/')):
        parent = '/' + parts[1]
    elif anchor.startswith('/usr/local/'):
        parent = '/usr/local'
    elif len(parts) >= 4 and parts[1] == 'home' and parts[2]:
        parent = f'/home/{parts[2]}'
    else:
        return None
    return anchor, parent


def _manifest_footprint(record, run, deadline):
    """Read one of two fixed Node manifest locations without following an escape."""
    output = run(['pct', 'exec', str(record['vmid']), '--', 'timeout', '-s', 'KILL', '2',
                  'sh', '-c', MANIFEST_FOOTPRINT_SCRIPT, 'discovery',
                  record['root'], record['manifest_anchor'], record['manifest_parent']], deadline)
    header, separator, metadata = output.partition('\n')
    if header == 'MISSING':
        if metadata:
            raise ProbeError('invalid_data')
        return None, None
    if header == 'OUTSIDE':
        if metadata:
            raise ProbeError('invalid_data')
        raise ProbeError('unsafe_manifest_root')
    prefix = 'MANIFEST\t'
    relative = header.removeprefix(prefix)
    if not header.startswith(prefix) or relative not in ('package.json', 'server/package.json'):
        raise ProbeError('invalid_data')
    if not separator:
        raise ProbeError('invalid_data')
    candidate_record = dict(record)
    candidate_record['path'] = str(Path(record['root']) / relative)
    return candidate_record, 'FILE\n' + metadata


def parse_records(text, kind):
    lines = text.splitlines()
    if not lines or lines[-1] not in ('END', 'LIMIT'):
        raise ProbeError('incomplete')
    if len(lines) - 1 > MAX_RECORDS:
        raise ProbeError('metadata_limit')
    records = []
    seen_services = set()
    for line in lines[:-1]:
        parts = line.split('\t')
        if kind == 'S' and len(parts) == 6 and parts[0] == 'S':
            _, source, manager, exe, script, directory = parts
            if not _path(source) or manager not in ('systemd', 'openrc'):
                raise ProbeError('invalid_data')
            service = Path(source).name.removesuffix('.service')
            if service in seen_services:
                continue  # /etc overrides vendor units; no duplicate installations.
            seen_services.add(service)
            if (not _NAME.fullmatch(service) or _system(service) or _helper(service)
                    or not _path(exe)):
                continue
            runtime_name = Path(exe).name
            runtime = bool(_RUNTIMES.fullmatch(runtime_name))
            manifest_bounds = None
            if runtime and not _path(script):
                # A Node/npm wrapper may keep its entry point relative to an
                # operator-owned working directory.  Only two fixed manifest
                # locations can prove that root; no argv, environment, recursive
                # search or guest-provided path is ever used.
                if runtime_name not in _PACKAGE_ROOT_RUNTIMES or not _custom(directory):
                    continue
                install = str(Path(directory) / 'package.json')
                manifest_bounds = _manifest_bounds(exe, directory)
                if manifest_bounds is None:
                    continue
            else:
                install = script if runtime else exe
            if (not _path(install) or _system(Path(install).name)
                    or install.startswith(('/usr/lib/systemd/', '/lib/systemd/',
                                           '/usr/lib/udev/', '/lib/udev/', '/usr/lib/apt/'))):
                continue
            # /etc units are operator-owned.  Do not infer an application from an
            # arbitrary packaged systemd unit: without a package-db probe it is
            # impossible to distinguish vendor infrastructure from a user app.
            if (manager == 'systemd'
                    and source.startswith(('/usr/lib/systemd/system/', '/lib/systemd/system/'))
                    and not _custom(install)):
                continue
            root = directory if _custom(directory) else str(Path(install).parent)
            # Generic runtime without an absolute application script is ambiguous.
            if runtime and not _custom(install):
                continue
            record = {'name': service, 'path': install, 'root': root,
                      'service': source, 'manager': manager, 'executable': exe}
            if manifest_bounds:
                record['manifest_anchor'], record['manifest_parent'] = manifest_bounds
            records.append(record)
        elif kind == 'P' and len(parts) == 4 and parts[0] == 'P':
            _, pid, exe, directory = parts
            # A process rooted at / is normally too ambiguous for generic
            # discovery, but it is valid process metadata for the exact Hestia
            # panel signature below.  It never becomes a generic candidate.
            if not pid.isdigit() or not _path(exe) or (directory != '/' and not _path(directory)):
                continue
            records.append({'pid': pid, 'executable': exe, 'root': directory})
        elif kind == 'L' and len(parts) == 3 and parts[0] == 'L':
            _, pid, port = parts
            if pid.isdigit() and port.isdigit() and 0 < int(port) < 65536:
                records.append({'pid': pid, 'port': int(port)})
            else:
                raise ProbeError('invalid_data')
        elif kind == 'H' and len(parts) == 5 and parts[0] == 'H':
            _, pid, exe, directory, port = parts
            if (pid.isdigit() and exe == _HESTIA_NGINX
                    and (directory == '/' or _path(directory))
                    and port == str(_HESTIA_PANEL_PORT)):
                records.append({'pid': pid, 'executable': exe, 'root': directory,
                                'port': _HESTIA_PANEL_PORT})
            else:
                raise ProbeError('invalid_data')
        else:
            raise ProbeError('invalid_data')
    return records, lines[-1] == 'LIMIT', len(lines) - 1


def candidate(vmid, record, footprint):
    if not footprint.startswith('FILE\n'):
        raise ProbeError('invalid_data')
    version, metadata_issue = None, None
    metadata = footprint[5:].strip()
    if metadata:
        try:
            manifest = json.loads(metadata)
        except (ValueError, TypeError):
            manifest = None
        # Only the whitelisted version field leaves this function. Never retain
        # manifest scripts, repository guesses, config or arbitrary extra fields.
        if not isinstance(manifest, dict):
            metadata_issue = 'invalid_metadata'
            manifest = {}
        value = manifest.get('version')
        if (isinstance(value, str) and len(value) <= 64 and _VERSION.fullmatch(value)
                and record['path'].startswith(record['root'].rstrip('/') + '/')):
            version = value
    identity = 'native-' + hashlib.sha256(
        f'{int(vmid)}:{record["path"]}:{record["root"]}'.encode()).hexdigest()[:24]
    evidence = [{'kind': 'installation_file', 'value': record['path']}]
    if record.get('service'):
        evidence.append({'kind': record['manager'], 'value': record['service']})
    else:
        evidence.extend([{'kind': 'process_executable', 'value': record['process']},
                         {'kind': 'working_directory',
                          'value': record.get('process_root', record['root'])}])
    ports = sorted(set(record.get('listening_ports') or []))
    # Hestia's control panel is a narrow, verified exception to generic port
    # inference: its own executable serves the panel on fixed HTTPS port 8083.
    # Keep this declaration on the exact runtime signature so an unrelated
    # application merely listening on 8083 never receives an HTTPS guess.
    hestia_panel = (record['name'] == 'Hestia'
                    and record['path'] == _HESTIA_NGINX
                    and record['root'] == _HESTIA_ROOT
                    and _HESTIA_PANEL_PORT in ports)
    evidence.extend({'kind': 'tcp_listener', 'value': str(port)} for port in ports)
    return {'slug': identity, 'discovery_id': identity, 'source': 'native_metadata',
            'name': record['name'], 'installed_version': version, 'evidence': evidence,
            'installation_path': record['path'],
            'default_ports': [_HESTIA_PANEL_PORT] if hestia_panel else [],
            'listening_ports': ports,
            **({'scheme': 'https'} if hestia_panel else {}),
            'metadata_issue': metadata_issue,
            'tracking_suggestion': ({'installed_via': 'manual', 'installed_version': version,
                                     'detected_version': version, 'detector_verified': True}
                                    if version else None)}


def _guard(vmid, deadline, run):
    # The local node path rejects QEMU, missing and remote CTs before pct exec.
    path = LOCAL_CONFIG / f'{vmid}.conf'
    if not path.is_file():
        raise ProbeError('not_local_lxc')
    # Presence, including a damaged/in-progress record, excludes generic probes.
    try:
        os.lstat(OCI_ROOT / str(vmid))
    except FileNotFoundError:
        pass
    except OSError:
        raise ProbeError('oci_unknown') from None
    else:
        raise ProbeError('managed_oci')
    try:
        with path.open('rb') as handle:
            raw = handle.read(OUTPUT_BYTES + 1)
        if len(raw) > OUTPUT_BYTES:
            raise ProbeError('config_limit')
        config = raw.decode('utf-8')
    except (OSError, UnicodeError):
        raise ProbeError('config_unavailable') from None
    if re.search(r'^lock:', config, re.M):
        raise ProbeError('guest_busy')
    update_lock = UPDATE_LOCK_ROOT / f'proxmenux-lxc-update-{vmid}.lock'
    try:
        with update_lock.open('rb') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ProbeError('guest_busy') from None
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    except FileNotFoundError:
        pass
    except OSError:
        raise ProbeError('lock_unavailable') from None
    if re.search(r'^ostype:\s*unmanaged\s*$', config, re.M):
        raise ProbeError('unsupported_guest')
    if not re.search(r'^ostype:\s*(?:debian|ubuntu|alpine|archlinux|centos|fedora|opensuse|gentoo)\s*$', config, re.M):
        raise ProbeError('unsupported_guest')
    status = run(['pct', 'status', str(vmid)], deadline).strip()
    if status != 'status: running':
        raise ProbeError('guest_stopped' if status == 'status: stopped' else 'status_unknown')


def scan(vmid, run=bounded_run):
    deadline = time.monotonic() + TOTAL_SECONDS
    _guard(vmid, deadline, run)
    records, issues, consumed, processes, listeners, hestia_panels = [], [], 0, [], [], []
    for kind, script in (('S', SERVICE_SCRIPT), ('P', PROCESS_SCRIPT), ('L', PORT_SCRIPT)):
        try:
            if consumed >= MAX_RECORDS:
                issues.append('metadata_limit')
                break
            parsed, limited, count = parse_records(run(
                ['pct', 'exec', str(vmid), '--', 'timeout', '-s', 'KILL', '2',
                 'sh', '-c', script, 'discovery', str(MAX_RECORDS - consumed)], deadline), kind)
            if consumed + count > MAX_RECORDS:
                issues.append('metadata_limit')
                parsed = parsed[:MAX_RECORDS - consumed]
            consumed = min(MAX_RECORDS, consumed + count)
            # The entire collector, not each metadata source, has 256 records.
            capacity = MAX_RECORDS - len(records)
            if kind == 'S':
                records.extend(parsed[:capacity])
            elif kind == 'P':
                processes = parsed[:capacity]
            else:
                listeners = parsed[:capacity]
            if limited or len(parsed) > capacity:
                issues.append('metadata_limit')
        except ProbeError as exc:
            issues.append(str(exc))
    try:
        # This is outside the generic record budget: it returns only an exact,
        # fixed Hestia signature, not additional arbitrary process metadata.
        hestia_panels, limited, _ = parse_records(run(
            ['pct', 'exec', str(vmid), '--', 'timeout', '-s', 'KILL', '2',
             'sh', '-c', HESTIA_PANEL_SCRIPT, 'discovery'], deadline), 'H')
        if limited:
            issues.append('metadata_limit')
    except ProbeError as exc:
        issues.append(str(exc))
    for process in processes:
        exe, directory = process['executable'], process['root']
        related = [record for record in records if record['executable'] == exe and (
            not _RUNTIMES.fullmatch(Path(exe).name) or record['root'] == directory)]
        ports = [entry['port'] for entry in listeners if entry['pid'] == process['pid']]
        if len(related) == 1:
            related[0].setdefault('listening_ports', []).extend(ports)
        elif not related and _hestia_panel_process(exe, ports):
            records.append({'name': 'Hestia', 'path': exe, 'root': _HESTIA_ROOT,
                            'process': exe, 'process_root': directory, 'executable': exe,
                            'listening_ports': ports})
        elif not related and (_custom(exe) and _custom(directory)
                              and not _system(Path(exe).name)
                              and not _helper(Path(exe).name)
                              and not _RUNTIMES.fullmatch(Path(exe).name)
                              and exe.startswith(directory.rstrip('/') + '/')
                              and _NAME.fullmatch(Path(exe).name)):
            records.append({'name': Path(exe).name, 'path': exe, 'root': directory,
                            'process': exe, 'executable': exe, 'listening_ports': ports})
    for panel in hestia_panels:
        records.append({'name': 'Hestia', 'path': panel['executable'], 'root': _HESTIA_ROOT,
                        'process': panel['executable'], 'process_root': panel['root'],
                        'executable': panel['executable'],
                        'listening_ports': [panel['port']]})
    items, seen = [], set()
    for record in records:
        key = (record['path'], record['root'])
        if key in seen:
            continue
        seen.add(key)
        if len(items) >= MAX_CANDIDATES:
            issues.append('candidate_limit')
            break
        try:
            probe_record = dict(record)
            probe_record['vmid'] = vmid
            if 'manifest_anchor' in record:
                probe_record, footprint = _manifest_footprint(probe_record, run, deadline)
                if probe_record is None:
                    continue
            else:
                footprint = run(['pct', 'exec', str(vmid), '--', 'timeout', '-s', 'KILL', '2',
                                 'sh', '-c', FOOTPRINT_SCRIPT,
                                 'discovery', record['path'], record['root']], deadline)
            item = candidate(vmid, probe_record, footprint)
            items.append(item)
            if item['metadata_issue']:
                issues.append(item['metadata_issue'])
        except ProbeError as exc:
            issues.append(str(exc))
            if str(exc) == 'deadline':
                break
    return {'vmid': vmid, 'status': 'partial' if issues else 'complete',
            'candidates': items, 'issues': sorted(set(issues)), 'stale': False,
            'scanned_at': time.time()}


def cached(vmid):
    with _mutex:
        value = copy.deepcopy(_cache.get(int(vmid)))
    if value is None:
        return {'vmid': int(vmid), 'status': 'not_scanned', 'candidates': [], 'stale': False}
    if time.time() - value['scanned_at'] >= CACHE_SECONDS:
        value['stale'] = True
    return value


def mark_stale(vmid):
    """Lifecycle events retire freshness, never collect new guest metadata."""
    with _mutex:
        if int(vmid) in _cache:
            _cache[int(vmid)]['stale'] = True


def discover(vmid):
    vmid = int(vmid)
    with _mutex:
        lock = _locks.setdefault(vmid, threading.Lock())
    if not lock.acquire(blocking=False):
        return {**cached(vmid), 'status': 'busy', 'stale': True}
    try:
        try:
            result = scan(vmid)
        except ProbeError as exc:
            result = {**cached(vmid), 'status': 'error', 'issues': [str(exc)], 'stale': True}
            result.setdefault('scanned_at', time.time())
            with _mutex:
                _cache[vmid] = copy.deepcopy(result)
            return result
        previous = cached(vmid)
        if result['status'] != 'complete' and previous['candidates']:
            # Partial output cannot prove that previously seen apps disappeared.
            ids = {item['discovery_id'] for item in result['candidates']}
            result['candidates'].extend(item for item in previous['candidates']
                                        if item['discovery_id'] not in ids)
            result['candidates'] = result['candidates'][:MAX_CANDIDATES]
            result['stale'] = True
        with _mutex:
            _cache[vmid] = copy.deepcopy(result)
        return result
    finally:
        lock.release()


def filter_candidates(result, suggestions, apps):
    """Pure composition: never run catalog probes, load or write registries."""
    known = [*apps, *(suggestions.get('extras') or []),
             *(suggestions.get('docker_workloads') or [])]
    if suggestions.get('helper_slug'):
        known.append({'name': suggestions.get('name_suggestion'),
                      'helper_slug': suggestions['helper_slug'],
                      'tracking_suggestion': suggestions.get('tracking_suggestion')})
    identities = {a.get('discovery_id') for a in known if a.get('discovery_id')}
    names, paths = set(), set()
    for app in known:
        for field in ('name', 'slug', 'helper_slug', 'package'):
            if app.get(field):
                names.add(str(app[field]).casefold())
        detector = app.get('tracking_suggestion') or app
        for field in ('binary_path', 'file_path'):
            if detector.get(field):
                paths.add(detector[field])
    items = [item for item in result['candidates']
             if item['discovery_id'] not in identities
             and item['name'].casefold() not in names
             and item['installation_path'] not in paths]
    return {**result, 'candidates': items}
