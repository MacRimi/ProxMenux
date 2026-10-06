#!/usr/bin/env python3
"""Start again an OCI application that stopped on its own.

Proxmox has no restart policy: when the process of an application container
ends, the container stays stopped. This service watches the containers whose
record asks for it and starts again the one that stopped without anybody
asking: a stop, a shutdown, a backup, a migration or a ProxMenux operation is
never undone, and neither is a container that was already stopped when the
service first saw it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import oci_instances as instances
import oci_operation_notice

UNIT = 'proxmenux-oci-watchdog.service'
UNIT_FILE = Path('/etc/systemd/system') / UNIT
JOURNAL = Path('/usr/local/share/proxmenux/scripts/global/pmx_journal.sh')
CGROUPS = Path('/sys/fs/cgroup/lxc')
CONFIGS = Path('/etc/pve/lxc')
HA_RESOURCES = Path('/etc/pve/ha/resources.cfg')
TASKS = (Path('/var/log/pve/tasks/active'), Path('/var/log/pve/tasks/index'))
INTERVAL = 10
# The clock of a task has one second of resolution.
TOLERANCE = 2
# An application that ran this long before stopping is not in a crash loop:
# its restart, such as the one it asks for after saving its settings, is
# immediate however often it happens.
STABLE = 20
# One notice of a restart per application in this time, however often it restarts.
NOTICE_EVERY = 3600
# Wait before each new attempt; after the last one the application is left stopped.
DELAYS = (0, 30, 60, 120, 300)
# The marks of an operation are kept for the notices that arrive after it ends.
OPERATION_GRACE = 120
STOP_TASKS = {'vzstop', 'vzshutdown', 'vzsuspend', 'vzreboot', 'vzdestroy', 'vzmigrate', 'vzrestore', 'vzdump'}
HOST_TASKS = {'stopall', 'migrateall'}


def new_state():
    return {'seen': None, 'since': None, 'attempts': 0, 'retry_at': 0.0, 'settled': False, 'noticed': None}


def notice_due(state, now):
    """Whether to tell that the application was restarted: the first time,
    and then at most once in a while."""
    if state['noticed'] is not None and now - state['noticed'] < NOTICE_EVERY:
        return False
    state['noticed'] = now
    return True


def parse_tasks(text, active):
    """The tasks of a Proxmox task list as (type, id, end); `end` is None
    while the task runs. The list of active tasks carries one more column."""
    tasks = []
    for line in text.splitlines():
        fields = line.split()
        if not fields or not fields[0].startswith('UPID:'):
            continue
        parts = fields[0].split(':')
        if len(parts) < 8:
            continue
        stamp = fields[2:3] if active else fields[1:2]
        try:
            end = int(stamp[0], 16) if stamp else None
        except ValueError:
            continue
        tasks.append((parts[5], parts[6], end))
    return tasks


def stop_requested(tasks, vmid, seen):
    """Whether somebody asked for the container, or for every guest of the
    host, to stop: the request is still running or ended after the container
    was last seen running."""
    return any((kind in HOST_TASKS or (kind in STOP_TASKS and target == str(vmid)))
               and (end is None or end >= seen - TOLERANCE) for kind, target, end in tasks)


def decide(state, running, now, busy, requested):
    """One look at one container. Returns 'start' when it has to be started
    again, 'give-up' when it keeps stopping, or None. `busy` and `requested`
    are only called for a container that was running and no longer is."""
    if running:
        if state['since'] is None:
            state['since'] = now
        if now - state['since'] >= STABLE:
            state['attempts'] = 0
        state.update(seen=now, settled=False)
        return None
    state['since'] = None
    if state['seen'] is None or state['settled']:
        return None
    if busy():
        return None
    if requested(state['seen']):
        state['settled'] = True
        return None
    if now < state['retry_at']:
        return None
    if state['attempts'] >= len(DELAYS):
        state['settled'] = True
        return 'give-up'
    state['attempts'] += 1
    state['retry_at'] = now + (DELAYS[state['attempts']] if state['attempts'] < len(DELAYS) else DELAYS[-1])
    return 'start'


def watched(root):
    """The installed applications that asked for the watchdog: {vmid: name}."""
    found = {}
    for path in sorted(root.glob('*/oci-compose.json')):
        try:
            record = json.loads(path.read_text())
            vmid = int(record['vmid'])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if record.get('status') != 'installed' or record.get('deployment', {}).get('watchdog') is not True:
            continue
        if record.get('pending_stack_transaction') or record.get('pending_transaction'):
            continue
        title = record.get('template', {}).get('catalog_ui', {}).get('title')
        found[vmid] = (title.get('en_US') if isinstance(title, dict) else title) or f'CT {vmid}'
    return found


def is_running(vmid):
    return (CGROUPS / str(vmid)).is_dir()


def is_busy(vmid, now):
    """Something is working on the container or on the host: look again later."""
    try:
        config = (CONFIGS / f'{vmid}.conf').read_text(errors='replace')
    except OSError:
        return True
    if any(line.startswith('lock:') for line in config.split('\n[', 1)[0].splitlines()):
        return True
    try:
        mark = json.loads((oci_operation_notice.MARKERS / str(vmid)).read_text())
        if mark.get('ended') is None or now - float(mark['ended']) < OPERATION_GRACE:
            return True
    except (OSError, ValueError, TypeError, KeyError):
        pass
    try:
        if any(line.split(':', 1)[0].strip() == 'ct' and line.split(':', 1)[1].strip() == str(vmid)
               for line in HA_RESOURCES.read_text().splitlines() if ':' in line):
            return True
    except OSError:
        pass
    state = subprocess.run(['systemctl', 'is-system-running'], capture_output=True, text=True, check=False)
    return state.stdout.strip() == 'stopping'


def read_tasks():
    tasks = []
    for path in TASKS:
        try:
            with path.open('rb') as handle:
                handle.seek(0, 2)
                handle.seek(max(0, handle.tell() - 65536))
                tasks += parse_tasks(handle.read().decode(errors='replace'), path.name == 'active')
        except OSError:
            continue
    return tasks


def start(vmid):
    # In a scope of its own: what Proxmox leaves running for the container,
    # such as its DHCP client, must not end when this service is restarted.
    result = subprocess.run(['systemd-run', '--scope', '--quiet', '--collect', 'pct', 'start', str(vmid)],
                            capture_output=True, text=True, check=False, timeout=300)
    return result.returncode == 0


def look(states, now):
    apps = watched(instances.ROOT)
    for vmid in set(states) - set(apps):
        del states[vmid]
    for vmid, name in apps.items():
        state = states.setdefault(vmid, new_state())
        action = decide(state, is_running(vmid), now, lambda: is_busy(vmid, now),
                        lambda seen: stop_requested(read_tasks(), vmid, seen))
        data = {'app_name': name, 'vmid': vmid, 'containers': f'CT {vmid}'}
        if action == 'start':
            print(f'CT {vmid} ({name}) stopped on its own; starting it again (attempt {state["attempts"]})', flush=True)
            try:
                started = start(vmid)
            except (OSError, subprocess.SubprocessError):
                started = False
            if started and notice_due(state, now):
                oci_operation_notice.notify('oci_watchdog_restarted', data)
        elif action == 'give-up':
            print(f'CT {vmid} ({name}) keeps stopping; it is left stopped', flush=True)
            oci_operation_notice.notify('oci_watchdog_failed', data)


def run():
    states = {}
    while True:
        try:
            look(states, time.time())
        except (OSError, ValueError) as error:
            print(f'watchdog: {error}', file=sys.stderr, flush=True)
        time.sleep(INTERVAL)


def _journaled(unit):
    """Write and enable the unit through the change journal of ProxMenux, so
    the Changes tab of the Monitor shows it. False when the journal is not
    installed on this host."""
    if not JOURNAL.is_file():
        return False
    script = ('source "$1" && pmx_journal_context "oci_watchdog" "1.0" "oci_watchdog.py" '
              '&& pmx_write_file "$2" && systemctl daemon-reload && pmx_enable_service "$3"')
    result = subprocess.run(['bash', '-c', script, 'bash', str(JOURNAL), str(UNIT_FILE), UNIT],
                            input=unit, text=True, capture_output=True, check=False)
    return result.returncode == 0


def ensure_service():
    """Install the service and leave it running. A running one is only
    restarted when its unit changed; the ProxMenux installer restarts it when
    it replaces this program."""
    unit = ('[Unit]\n'
            'Description=ProxMenux OCI watchdog\n'
            'After=pve-guests.service\n\n'
            '[Service]\n'
            'Type=simple\n'
            f'ExecStart=/usr/bin/python3 {Path(__file__).resolve()} run\n'
            'Restart=on-failure\n'
            'RestartSec=30\n\n'
            '[Install]\n'
            'WantedBy=multi-user.target\n')
    changed = not UNIT_FILE.is_file() or UNIT_FILE.read_text() != unit
    if not _journaled(unit):
        if changed:
            UNIT_FILE.write_text(unit)
            subprocess.run(['systemctl', 'daemon-reload'], check=False)
        subprocess.run(['systemctl', 'enable', UNIT], check=False, capture_output=True)
    subprocess.run(['systemctl', 'restart' if changed else 'start', UNIT], check=False, capture_output=True)


def application(root, vmid):
    """The containers of the application `vmid` belongs to: itself, or every
    member of its stack."""
    record = instances.read(root, vmid)
    primary_id = int((record.get('stack_member') or {}).get('primary_vmid') or vmid)
    primary = record if primary_id == vmid else instances.read(root, primary_id)
    members = [int(member['vmid']) for member in (primary.get('stack') or {}).get('members') or []]
    return members or [vmid]


def set_watchdog(root, vmid, enabled):
    """Turn the watchdog of an application on or off. The choice is kept in
    the record of each of its containers, so updates and backups carry it."""
    import oci_carried_record
    with instances.locked(root):
        vmids = application(root, vmid)
        for member in vmids:
            record = instances.read(root, member)
            record.setdefault('deployment', {})['watchdog'] = bool(enabled)
            instances.write(instances.location(root, member), record)
            oci_carried_record.carry(root, member, mount_stopped=False)
    if enabled:
        ensure_service()
    return vmids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('run')
    commands.add_parser('install')
    change = commands.add_parser('set')
    change.add_argument('vmid', type=int)
    change.add_argument('state', choices=['on', 'off'])
    args = parser.parse_args()
    if args.command == 'install':
        ensure_service()
    elif args.command == 'set':
        try:
            vmids = set_watchdog(instances.ROOT, args.vmid, args.state == 'on')
        except BlockingIOError:
            print('Another OCI operation is using the instance registry.', file=sys.stderr)
            return 3
        except (OSError, ValueError, KeyError) as error:
            print(str(error) or type(error).__name__, file=sys.stderr)
            return 1
        print(json.dumps({'vmids': vmids, 'watchdog': args.state == 'on'}))
    else:
        run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
