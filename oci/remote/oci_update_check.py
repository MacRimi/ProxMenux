#!/usr/bin/env python3
"""Adapt the OCI menu to the ProxMenux Monitor checker and its native cache.

This module never contacts a registry or writes an update-status cache.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import time

import oci_instances as instances
from oci_installation_state import parse_config

APPS = Path('/etc/proxmenux/apps')
SOCKET = Path('/run/proxmenux-monitor/oci-check.sock')
MAX_AGE = 24 * 60 * 60
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


def title(record):
    try:
        template = (record.get('stack') or {}).get('template') or record.get('template') or {}
        name = (template.get('catalog_ui') or {}).get('title')
        if isinstance(name, dict):
            name = name.get('en_US') or name.get('en')
        return str(name or record.get('deployment', {}).get('hostname') or f"CT {record['vmid']}")
    except (AttributeError, TypeError):
        return f"CT {record['vmid']}"


def snapshot(root=instances.ROOT, configs=Path('/etc/pve/lxc')):
    """Use local native config files: opening the menu makes no PVE/API calls."""
    records = {}
    if not root.is_dir() or root.is_symlink():
        return []
    for path in sorted(root.iterdir()):
        if not path.name.isdecimal() or int(path.name) < 100:
            continue
        vmid = int(path.name)
        native = configs / f'{vmid}.conf'
        if not native.is_file():
            continue  # Deleted guests and guests on another node are not this host's apps.
        try:
            record = instances.read(root, vmid)
            config = native.read_bytes()
            # On disk, PVE stores the description in # comments, unlike
            # `pct config`. Later [snapshot] and [PENDING] sections describe
            # other configurations and must not supply this guest's identity.
            current = config.split(b'\n[', 1)[0]
            description = '\n'.join(line[1:] for line in current.decode().splitlines() if line.startswith('#'))
            identity = instances.identity(json.dumps({'description': description}).encode())
            architecture = parse_config(current).get('arch')
            reference = record['template']['container_contract']['image']['reference']
            image = (record.get('observed') or {}).get('image') or {}
            ready = (record.get('status') == 'installed'
                     and not record.get('pending_transaction')
                     and not record.get('pending_stack_transaction')
                     and identity == record['installation_id']
                     and architecture in ('amd64', 'arm64')
                     and isinstance(reference, str) and reference
                     and DIGEST.fullmatch(str(image.get('manifest_digest', ''))))
            primary = int((record.get('stack_member') or {}).get('primary_vmid') or vmid)
            records[vmid] = {'vmid': vmid, 'primary': primary, 'record': record,
                             'reference': reference,
                             'architecture': architecture, 'image': image,
                             'ready': bool(ready)}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # Never call an unreadable, incomplete or mismatched guest up to date.
            records[vmid] = {'vmid': vmid, 'primary': vmid, 'record': {'vmid': vmid},
                             'ready': False}
    groups = {}
    for member in records.values():
        groups.setdefault(member['primary'], []).append(member)
    applications = []
    for primary, members in sorted(groups.items()):
        main = records.get(primary)
        try:
            expected = {int(m['vmid']) for m in ((main or {}).get('record', {}).get('stack') or {}).get('members', [])}
            complete = main is not None
        except (ValueError, TypeError, KeyError, AttributeError):
            expected, complete = set(), False
        present = {m['vmid'] for m in members}
        complete = complete and expected.issubset(present)
        applications.append({'vmid': primary, 'title': title((main or members[0])['record']),
                             'members': members,
                             'complete': complete})
    return applications


def cached(root=instances.ROOT, configs=Path('/etc/pve/lxc'), now=None, apps=APPS):
    """Read the Monitor's sidecars; obey its primary-container stack policy."""
    inventory = snapshot(root, configs)
    result = {'checked': False, 'available': [], 'unknown': 0, 'applications': len(inventory)}
    instant = time.time() if now is None else now
    for app in inventory:
        try:
            if not app['complete'] or not all(member['ready'] for member in app['members']):
                raise ValueError('Incomplete installation')
            main = next(member for member in app['members'] if member['vmid'] == app['vmid'])
            path = apps / f"{app['vmid']}.json"
            if path.is_symlink():
                raise ValueError('Invalid cache')
            data = json.loads(path.read_text())
            candidates = [row for row in data['apps'] if row.get('installed_via') == 'oci_image']
            if str(data['vmid']) != str(app['vmid']) or len(candidates) != 1:
                raise ValueError('Ambiguous application')
            state = candidates[0]['state']
            stamp = datetime.datetime.strptime(state['checked_at'], '%Y-%m-%dT%H:%M:%SZ')
            age = instant - stamp.replace(tzinfo=datetime.timezone.utc).timestamp()
            if (not 0 <= age <= MAX_AGE or state.get('error')
                    or state.get('installed_digest') != main['image']['manifest_digest']
                    or state.get('image_reference') != main['reference']
                    or type(state.get('update_available')) is not bool
                    or not DIGEST.fullmatch(str(state.get('latest_digest', '')))):
                raise ValueError('Unusable result')
            result['checked'] = True
            if state['update_available']:
                result['available'].append({'vmid': app['vmid'], 'title': app['title']})
            if state.get('registry_retry'):
                result['unknown'] += 1  # Same retained result and retry as the Monitor.
        except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration):
            result['unknown'] += 1
    return result


def monitor_available(path=SOCKET):
    try:
        parent, endpoint = path.parent.lstat(), path.lstat()
        return (stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0
                and not parent.st_mode & 0o077 and stat.S_ISSOCK(endpoint.st_mode)
                and endpoint.st_uid == 0 and not endpoint.st_mode & 0o077)
    except OSError:
        return False


def check(root=instances.ROOT, configs=Path('/etc/pve/lxc'), progress=None, path=SOCKET):
    """Request the existing checker in its own Monitor process, without HTTP."""
    if not monitor_available(path):
        raise RuntimeError('ProxMenux Monitor checker unavailable')
    inventory = snapshot(root, configs)
    rows = []
    for app in inventory:
        if not app['complete'] or not all(member['ready'] for member in app['members']):
            continue
        main = next(member for member in app['members'] if member['vmid'] == app['vmid'])
        rows.append({'vmid': app['vmid'], 'installation_id': main['record']['installation_id']})
    total, skipped = len(inventory), len(inventory) - len(rows)
    if progress:
        progress(0, total)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(600)  # Native registry timeouts and retries remain authoritative.
        connection.connect(str(path))
        connection.sendall((json.dumps({'applications': rows}) + '\n').encode())
        completed = -1
        with connection.makefile('rb') as stream:
            while True:
                line = stream.readline(4097)
                if not line or len(line) > 4096:
                    raise RuntimeError('Monitor check incomplete')
                event = json.loads(line)
                if event.get('done') is True and completed == len(rows):
                    return
                done, count = event.get('completed'), event.get('total')
                if (type(done) is not int or type(count) is not int
                        or count != len(rows) or not completed <= done <= count or done < 0):
                    raise RuntimeError('Monitor check unavailable')
                completed = done
                if progress:
                    progress(skipped + completed, total)


def emit_progress(completed, total):
    message = (json.dumps({'completed': completed, 'total': total}) + '\n').encode()
    try:
        os.write(sys.stdout.fileno(), message)
    except (BlockingIOError, BrokenPipeError):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=instances.ROOT)
    parser.add_argument('--configs', type=Path, default=Path('/etc/pve/lxc'))
    parser.add_argument('--progress', action='store_true', help='Emit numeric progress for the OCI menu')
    args = parser.parse_args()
    try:
        if args.progress:
            os.set_blocking(sys.stdout.fileno(), False)
        check(args.root, args.configs, progress=emit_progress if args.progress else None)
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
