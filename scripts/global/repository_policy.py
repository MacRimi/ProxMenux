#!/usr/bin/env python3
"""Proxmox repository policy via its own parsed APT repository API.

Only `notfound` or `expired` permits an offered switch. Never print raw subscription or
repository API responses: they can contain subscription keys or credentials.
"""
import copy
import json
import re
import subprocess
import sys

ENDPOINT = '/nodes/localhost/apt/repositories'
PVE_CHANNELS = {'pve-enterprise', 'pve-no-subscription', 'pve-test', 'pvetest'}


def run(args):
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f'Unable to query or change Proxmox repository state ({args[0]}). Check the service and retry.') from exc


def subscription_status():
    # pvesubscription's CLI get printer emits sorted "key: value" lines,
    # including a secret key and server ID. Only parse the exact status line.
    output = run(['pvesubscription', 'get'])
    statuses = re.findall(r'^status: ([a-z]+)$', output, re.MULTILINE)
    if len(statuses) != 1 or statuses[0] not in ('active', 'notfound', 'expired'):
        raise ValueError('Subscription status is not unambiguously active, notfound or expired. Check pvesubscription get locally; no repository changed.')
    return statuses[0]


def repository_state(suite):
    try:
        data = json.loads(run(['pvesh', 'get', ENDPOINT, '--output-format', 'json']))
        if not isinstance(data, dict) or not isinstance(data['files'], list) or not isinstance(data['errors'], list) or not isinstance(data['digest'], str) or not isinstance(data['standard-repos'], list):
            raise ValueError()
        if data['errors']:
            raise ValueError()
        entries = []
        for file in data['files']:
            for index, row in enumerate(file['repositories']):
                if not isinstance(row, dict):
                    raise ValueError()
                # Flat repositories (e.g. suite './') legitimately omit this.
                row.setdefault('Components', [])
                # Captured PVE 9.2 JSON uses integer 0/1; older fixtures use bool.
                # Reject float/string coercions and retain the authoritative state.
                if type(row['Enabled']) not in (bool, int) or row['Enabled'] not in (0, 1):
                    raise ValueError()
                row['Enabled'] = bool(row['Enabled'])
                if not all(
                    isinstance(row[k], list) and all(isinstance(value, str) for value in row[k])
                    for k in ('Types', 'URIs', 'Suites', 'Components')
                ):
                    raise ValueError()
                # deb822 write/readback can insert Options/Enabled. It is
                # redundant only when well-formed and consistent with Enabled;
                # never discard the authoritative field or unrelated options.
                options = row.get('Options', [])
                if not isinstance(options, list):
                    raise ValueError()
                remaining = []
                seen_enabled = False
                boolean_options = {'true': True, 'yes': True, '1': True,
                                   'false': False, 'no': False, '0': False}
                for option in options:
                    if not isinstance(option, dict) or not isinstance(option['Key'], str) \
                       or not isinstance(option['Values'], list) \
                       or not all(isinstance(value, str) for value in option['Values']):
                        raise ValueError()
                    if option['Key'].lower() != 'enabled':
                        remaining.append(option)
                        continue
                    if seen_enabled or set(option) != {'Key', 'Values'} or len(option['Values']) != 1:
                        raise ValueError()
                    value = boolean_options.get(option['Values'][0].lower())
                    if value is None or value != row['Enabled']:
                        raise ValueError()
                    seen_enabled = True
                if remaining:
                    row['Options'] = remaining
                else:
                    row.pop('Options', None)
                entries.append((file['path'], index, row))
        return data, entries
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ValueError('Proxmox APT repository inventory is invalid or reports parse errors. Fix sources in Node > Updates > Repositories; no repository changed.') from exc


def evaluate(suite, apply=False):
    if suite not in ('bookworm', 'trixie'):
        raise ValueError('Unsupported Proxmox suite; no repository changed.')
    data, entries = repository_state(suite)
    pve = []
    ceph = []
    debian = False
    for path, index, row in entries:
        if not row['Enabled'] or 'deb' not in row['Types']:
            continue
        components = set(row['Components'])
        if components & PVE_CHANNELS:
            if suite not in row['Suites']:
                raise ValueError('PVE repository suite does not match the installed version; no repository changed.')
            pve.append((path, index, row))
        if 'main' in components and suite in row['Suites'] and not components & PVE_CHANNELS:
            debian = True
        if 'enterprise' in components and any('/ceph-' in uri for uri in row['URIs']):
            if suite not in row['Suites']:
                raise ValueError('Enterprise Ceph repository suite does not match this PVE version; correct it in the Proxmox repository UI before switching.')
            ceph.append((path, index, row))

    if any(set(row['Components']) & {'pve-no-subscription', 'pve-test', 'pvetest'} for _, _, row in pve):
        return 'preserve'
    # Entitlement lookup is only needed when considering a switch. Existing
    # public/test channels are the operator's choice, even if lookup fails.
    status = subscription_status()  # fail closed before any write
    if status == 'active':
        if not pve:
            raise ValueError('Host has an active subscription but no active PVE repository. Configure its Enterprise source in Node > Updates > Repositories; no repository changed.')
        return 'preserve'
    if not debian:
        raise ValueError('No active Debian base repository for this suite; configure it in the Proxmox repository UI before continuing.')
    # No active PVE source or only inaccessible Enterprise. A mixed stanza
    # cannot be disabled without also disabling an unrelated component.
    disable = [item for item in pve if 'pve-enterprise' in item[2]['Components']] + ceph
    for _, _, row in disable:
        expected = {'pve-enterprise'} if 'pve-enterprise' in row['Components'] else {'enterprise'}
        if set(row['Components']) != expected:
            raise ValueError('Enterprise shares an APT stanza with other components. Split it in the Proxmox repository UI; no repository changed.')
    handles = [r.get('handle') for r in data['standard-repos'] if r.get('handle') == 'no-subscription']
    if len(handles) != 1:
        raise ValueError('Proxmox no-subscription standard repository handle unavailable; no repository changed.')
    if not apply:
        return 'offer'
    # Adopt a refreshed digest only after checking the complete expected
    # inventory: path/index targets are unsafe if another writer changed it.
    expected = copy.deepcopy(data['files'])
    try:
        for path, index, original in disable:
            next(file for file in expected if file['path'] == path)['repositories'][index]['Enabled'] = False
            run(['pvesh', 'create', ENDPOINT, '--path', path, '--index', str(index),
                 '--enabled', '0', '--digest', data['digest']])
            refreshed, current = repository_state(suite)
            # Per-file digests change when Proxmox serializes the disabled entry.
            inventory = lambda files: sorted(
                ({key: value for key, value in file.items() if key != 'digest'} for file in files),
                key=lambda file: file['path'])
            if inventory(refreshed['files']) != inventory(expected):
                raise ValueError('Could not verify the expected repository inventory after Enterprise disable; possible concurrent edit. Inspect the Proxmox repository UI before retrying.')
            data = refreshed
        run(['pvesh', 'set', ENDPOINT, '--handle', 'no-subscription', '--digest', data['digest']])
        _, current = repository_state(suite)
        if not any(row['Enabled'] and 'deb' in row['Types'] and suite in row['Suites']
                   and 'pve-no-subscription' in row['Components'] for _, _, row in current) \
           or any(p == path and i == index and row['Enabled']
                  for path, index, _ in disable for p, i, row in current):
            raise ValueError('Could not verify the switched repositories; inspect the Proxmox repository UI before retrying.')
    except ValueError as exc:
        raise ValueError('Could not complete or verify the repository switch; changes may be partial and repository state is unknown. Inspect Node > Updates > Repositories before retrying; no automatic rollback was attempted.') from exc
    return 'changed'


def main():
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in ('plan', 'apply'):
            raise ValueError('Usage: repository_policy.py plan|apply bookworm|trixie')
        print(evaluate(sys.argv[2], apply=sys.argv[1] == 'apply'))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
