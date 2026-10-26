"""Containers an OCI manager operation is working on.

An update or a recreation stops, backs up and starts its containers. The OCI
engine marks them while it works and reports the result itself, so their
stop, start and backup notices are part of the operation, not news.
"""
import json
import os
import re
import time

MARKERS = '/run/proxmenux/oci-operations'
# The last start of an operation is noticed a little after it returned.
GRACE_SECONDS = 180
# A mark left behind by an operation that died is not trusted for ever.
STALE_SECONDS = 6 * 3600
QUIET_EVENTS = frozenset({
    'vm_start', 'vm_stop', 'vm_shutdown', 'vm_restart',
    'ct_start', 'ct_stop', 'ct_shutdown', 'ct_restart',
    'backup_start', 'backup_complete',
})
_OCI_BACKUP_PATH = '/proxmenux/oci/instances/'


def active(vmid, now=None, root=MARKERS) -> bool:
    try:
        with open(os.path.join(root, str(int(vmid))), encoding='utf-8') as handle:
            mark = json.load(handle)
        started = float(mark.get('started') or 0)
        ended = mark.get('ended')
    except (OSError, ValueError, TypeError):
        return False
    now = time.time() if now is None else now
    if ended is None:
        return now - started < STALE_SECONDS
    return now - float(ended) < GRACE_SECONDS


def _vmids(event) -> set:
    data = event.data or {}
    found = set()
    for value in (data.get('vmid'), getattr(event, 'entity_id', '')):
        if str(value or '').isdigit():
            found.add(int(value))
    if event.event_type.startswith('backup_'):
        text = ' '.join(str(data.get(key) or '') for key in ('reason', 'pve_message', 'vmname', 'guests'))
        found.update(int(value) for value in re.findall(r'\((\d{3,})\)|vzdump-(?:lxc|qemu)-(\d+)-', text)
                     for value in value if value)
    return found


def quiet(event, root=MARKERS) -> bool:
    """Whether the event is a step of a running OCI operation."""
    if event.event_type not in QUIET_EVENTS or event.severity in ('CRITICAL', 'WARNING'):
        return False
    data = event.data or {}
    if event.event_type.startswith('backup_') and any(
            _OCI_BACKUP_PATH in str(data.get(key) or '') for key in ('reason', 'pve_message', 'filename')):
        # The working copy of an update lives in the OCI registry of the host.
        return True
    vmids = _vmids(event)
    return bool(vmids) and all(active(vmid, root=root) for vmid in vmids)
