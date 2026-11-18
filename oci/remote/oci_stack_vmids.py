#!/usr/bin/env python3
"""Allocate stack VMIDs without coupling container identity to network offsets."""
from __future__ import annotations

import json
import re
import subprocess
import sys

from oci_ui import translate

MIN_VMID, MAX_VMID = 100, 999999999


def vmid(value):
    if (isinstance(value, bool) or not isinstance(value, (int, str))
            or not re.fullmatch(r'[0-9]+', str(value))
            or not MIN_VMID <= int(value) <= MAX_VMID):
        raise ValueError(translate('VMIDs must be whole numbers from 100 to 999999999'))
    return int(value)


def validate_selection(selection, services):
    """An explicit selection is complete: never silently allocate a missing member."""
    names = {s['name'] for s in services}
    if not isinstance(selection, dict) or set(selection) != names:
        raise ValueError(translate('Choose a VMID for every service in the stack'))
    result = {name: vmid(value) for name, value in selection.items()}
    if len(set(result.values())) != len(result):
        raise ValueError(translate('Each service must have a different VMID'))
    return result


def resolve(deployment, services, occupied, next_id):
    """Resolve either a complete per-service selection or the legacy free block."""
    if 'service_vmids' in deployment:
        result = validate_selection(deployment['service_vmids'], services)
    else:
        base = deployment.get('base_vmid')
        explicit_base = base is not None
        base = vmid(base if explicit_base else next_id())
        while True:
            result = {s['name']: vmid(base + s['offset']) for s in services}
            if not set(result.values()) & occupied:
                break
            if explicit_base:
                raise ValueError(translate('The requested VMID block is already in use'))
            base += 1
    conflicts = sorted(set(result.values()) & occupied)
    if conflicts:
        raise ValueError(translate('These VMIDs are not free:') + ' ' + ', '.join(map(str, conflicts)))
    return result


def allocate(deployment, services):
    """Read the cluster, including VMs and guests on other nodes, before creation."""
    output = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'vm',
                             '--output-format', 'json'], check=True, capture_output=True,
                            text=True, timeout=30).stdout
    rows = json.loads(output)
    if not isinstance(rows, list) or any(not isinstance(row, dict) or 'vmid' not in row for row in rows):
        raise ValueError(translate('Could not read the cluster VMIDs'))
    occupied = {vmid(row['vmid']) for row in rows}

    def next_id():
        return subprocess.run(['pvesh', 'get', '/cluster/nextid'], check=True,
                              capture_output=True, text=True, timeout=30).stdout.strip()

    return resolve(deployment, services, occupied, next_id)


if __name__ == '__main__':
    try:
        with open(sys.argv[1]) as stream:
            deployment = json.load(stream)
        services = [{'name': name, 'offset': offset} for offset, name in enumerate(sys.argv[2:])]
        chosen = allocate(deployment, services)
        print(' '.join(str(chosen[s['name']]) for s in services))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
