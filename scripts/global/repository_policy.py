#!/usr/bin/env python3
"""Proxmox VE and Proxmox Backup Server repository policy via their own parsed APT
repository API.

Only `notfound` or `expired` permits an offered switch. Never print raw subscription or
repository API responses: they can contain subscription keys or credentials.
"""
import copy
import json
from pathlib import Path
import re
import subprocess
import string
import sys

ENDPOINT = '/nodes/localhost/apt/repositories'
PVE_CHANNELS = {'pve-enterprise', 'pve-no-subscription', 'pve-test', 'pvetest'}
# Proxmox VE and Proxmox Backup Server share the repository API; each has its
# own command line, channels and place in the web interface.
PRODUCTS = {
    'pve': {'api': ['pvesh'], 'name': 'Proxmox VE', 'short': 'PVE',
            'channels': PVE_CHANNELS, 'enterprise': 'pve-enterprise', 'public': 'pve-no-subscription',
            'test': {'pve-no-subscription', 'pve-test', 'pvetest'},
            'ui': 'Node > Updates > Repositories', 'ceph': True},
    'pbs': {'api': ['proxmox-backup-debug', 'api'], 'name': 'Proxmox Backup Server', 'short': 'PBS',
            'channels': {'pbs-enterprise', 'pbs-no-subscription', 'pbs-test', 'pbstest'},
            'enterprise': 'pbs-enterprise', 'public': 'pbs-no-subscription',
            'test': {'pbs-no-subscription', 'pbs-test', 'pbstest'},
            'ui': 'Administration > Repositories', 'ceph': False},
}
BASE = Path(__file__).resolve().parents[2]


def N_(text):
    """Mark a CLI message without changing the policy's English exception."""
    return text


class PolicyError(ValueError):
    def __init__(self, template, **params):
        self.template = template
        self.params = params
        super().__init__(template.format(**params))


def cli_error(error, product):
    """Localize only PBS CLI diagnostics; policy callers retain English errors."""
    if product != 'pbs' or not isinstance(error, PolicyError):
        return str(error)
    try:
        language = json.loads((BASE / 'config.json').read_text()).get('language', 'en')
        if language not in ('sk', 'de', 'es', 'fr', 'it', 'pt', 'sv'):
            return str(error)
        catalog = json.loads((BASE / 'lang' / f'{language}.json').read_text())
        message = catalog.get(error.template)
        if isinstance(message, str) and message.strip():
            fields = lambda text: {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}
            if fields(message) != fields(error.template) or any(
                spec or conversion for _, _, spec, conversion in string.Formatter().parse(message)
            ):
                return str(error)
            return message.format(**error.params)
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        pass
    return str(error)


def run(args):
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f'Unable to query or change Proxmox repository state ({args[0]}). Check the service and retry.') from exc


def subscription_status(product='pve'):
    if product == 'pbs':
        # Only the status field is read; the answer also carries the server ID.
        try:
            status = json.loads(run(['proxmox-backup-manager', 'subscription', 'get', '--output-format', 'json'])).get('status')
        except (ValueError, AttributeError):
            status = None
        if status not in ('active', 'notfound', 'expired'):
            raise PolicyError(N_('Subscription status is not unambiguously active, notfound or expired. Check proxmox-backup-manager subscription get locally; no repository changed.'))
        return status
    # pvesubscription's CLI get printer emits sorted "key: value" lines,
    # including a secret key and server ID. Only parse the exact status line.
    output = run(['pvesubscription', 'get'])
    statuses = re.findall(r'^status: ([a-z]+)$', output, re.MULTILINE)
    if len(statuses) != 1 or statuses[0] not in ('active', 'notfound', 'expired'):
        raise ValueError('Subscription status is not unambiguously active, notfound or expired. Check pvesubscription get locally; no repository changed.')
    return statuses[0]


def repository_state(suite, product='pve'):
    p = PRODUCTS[product]
    try:
        data = json.loads(run([*p['api'], 'get', ENDPOINT, '--output-format', 'json']))
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
        raise PolicyError(N_('Proxmox APT repository inventory is invalid or reports parse errors. Fix sources in {ui}; no repository changed.'), ui=p['ui']) from exc


def evaluate(suite, apply=False, product='pve'):
    if suite not in ('bookworm', 'trixie'):
        raise PolicyError(N_('Unsupported Proxmox suite; no repository changed.'))
    p = PRODUCTS[product]
    data, entries = repository_state(suite, product)
    pve = []
    ceph = []
    debian = False
    wrong_pve = []
    wrong_ceph = []
    for path, index, row in entries:
        if not row['Enabled'] or 'deb' not in row['Types']:
            continue
        components = set(row['Components'])
        if components & p['channels']:
            if suite not in row['Suites']:
                wrong_pve.append(f"{' '.join(sorted(components & p['channels']))} in {path} (suite {' '.join(row['Suites'])})")
            pve.append((path, index, row))
        if 'main' in components and suite in row['Suites'] and not components & p['channels']:
            debian = True
        if p['ceph'] and 'enterprise' in components and any('/ceph-' in uri for uri in row['URIs']):
            if suite not in row['Suites']:
                wrong_ceph.append(f"{path} (suite {' '.join(row['Suites'])})")
            ceph.append((path, index, row))
    # Name the stale sources, never their URIs: those can carry credentials.
    if wrong_pve:
        raise PolicyError(N_('This host runs {name} on {suite}, but these {name} repositories are for another suite: {details}. Disable or remove them in {ui} and run the update again; no repository changed.'),
                          name=p['name'], suite=suite, details='; '.join(wrong_pve), ui=p['ui'])
    if wrong_ceph:
        raise ValueError(f"This host runs Proxmox VE on {suite}, but these Enterprise Ceph repositories are for another suite: "
                         f"{'; '.join(wrong_ceph)}. Correct them in Node > Updates > Repositories before switching; no repository changed.")

    if any(set(row['Components']) & p['test'] for _, _, row in pve):
        return 'preserve'
    # Entitlement lookup is only needed when considering a switch. Existing
    # public/test channels are the operator's choice, even if lookup fails.
    status = subscription_status(product)  # fail closed before any write
    if status == 'active':
        if not pve:
            raise PolicyError(N_('Host has an active subscription but no active {short} repository. Configure its Enterprise source in {ui}; no repository changed.'), short=p['short'], ui=p['ui'])
        return 'preserve'
    if not debian:
        raise PolicyError(N_('No active Debian base repository for this suite; configure it in the Proxmox repository UI before continuing.'))
    # No active product source or only inaccessible Enterprise. A mixed stanza
    # cannot be disabled without also disabling an unrelated component.
    disable = [item for item in pve if p['enterprise'] in item[2]['Components']] + ceph
    for _, _, row in disable:
        expected = {p['enterprise']} if p['enterprise'] in row['Components'] else {'enterprise'}
        if set(row['Components']) != expected:
            raise PolicyError(N_('Enterprise shares an APT stanza with other components. Split it in the Proxmox repository UI; no repository changed.'))
    handles = [r.get('handle') for r in data['standard-repos'] if r.get('handle') == 'no-subscription']
    if len(handles) != 1:
        raise PolicyError(N_('Proxmox no-subscription standard repository handle unavailable; no repository changed.'))
    if not apply:
        return 'offer'
    # Adopt a refreshed digest only after checking the complete expected
    # inventory: path/index targets are unsafe if another writer changed it.
    expected = copy.deepcopy(data['files'])
    try:
        for path, index, original in disable:
            next(file for file in expected if file['path'] == path)['repositories'][index]['Enabled'] = False
            run([*p['api'], 'create', ENDPOINT, '--path', path, '--index', str(index),
                 '--enabled', '0', '--digest', data['digest']])
            refreshed, current = repository_state(suite, product)
            # Per-file digests change when Proxmox serializes the disabled entry.
            inventory = lambda files: sorted(
                ({key: value for key, value in file.items() if key != 'digest'} for file in files),
                key=lambda file: file['path'])
            if inventory(refreshed['files']) != inventory(expected):
                raise ValueError('Could not verify the expected repository inventory after Enterprise disable; possible concurrent edit. Inspect the Proxmox repository UI before retrying.')
            data = refreshed
        run([*p['api'], 'set', ENDPOINT, '--handle', 'no-subscription', '--digest', data['digest']])
        _, current = repository_state(suite, product)
        if not any(row['Enabled'] and 'deb' in row['Types'] and suite in row['Suites']
                   and p['public'] in row['Components'] for _, _, row in current) \
           or any(p == path and i == index and row['Enabled']
                  for path, index, _ in disable for p, i, row in current):
            raise ValueError('Could not verify the switched repositories; inspect the Proxmox repository UI before retrying.')
    except ValueError as exc:
        raise PolicyError(N_('Could not complete or verify the repository switch; changes may be partial and repository state is unknown. Inspect {ui} before retrying; no automatic rollback was attempted.'), ui=p['ui']) from exc
    return 'changed'


def main():
    product = 'pve'
    try:
        if len(sys.argv) not in (3, 4) or sys.argv[1] not in ('plan', 'apply') \
                or (len(sys.argv) == 4 and sys.argv[3] not in PRODUCTS):
            raise ValueError('Usage: repository_policy.py plan|apply bookworm|trixie [pve|pbs]')
        product = sys.argv[3] if len(sys.argv) == 4 else 'pve'
        print(evaluate(sys.argv[2], apply=sys.argv[1] == 'apply', product=product))
    except ValueError as exc:
        print(cli_error(exc, product), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
