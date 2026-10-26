"""Read-only validation of a coordinated stack operation, before host changes."""
import copy

from oci_ui import translate


def build(primary, records, inventory, operation):
    """Inventory maps VMIDs to installation UUIDs, including unrelated guests.

    Missing members are reported, not authorized for creation: their persistent
    volumes still require separate verification before any destructive operation.
    """
    if operation not in ('update', 'recreate'):
        raise ValueError(translate('Invalid stack operation'))
    stack = primary.get('stack')
    if not stack or not stack.get('members'):
        raise ValueError(translate('This is not a coordinated stack'))
    snapshots = stack['members']
    ids = [member['vmid'] for member in snapshots]
    if any(type(vmid) is not int or vmid < 100 for vmid in ids) or len(set(ids)) != len(ids):
        raise ValueError(translate('Duplicated or invalid stack VMID'))
    if primary['vmid'] not in ids:
        raise ValueError(translate('The main member of the stack is missing'))
    if stack.get('id') != primary['installation_id']:
        raise ValueError(translate('Inconsistent stack identity'))
    services = stack.get('deployment', {}).get('services', [])
    order = [service['vmid'] for service in services]
    if len(order) != len(ids) or set(order) != set(ids):
        raise ValueError(translate('Incomplete dependency order'))
    members, missing, blockers = [], [], []
    for snapshot in snapshots:
        vmid = snapshot['vmid']
        identity = snapshot['installation_id']
        current = records.get(vmid, snapshot)
        if current.get('installation_id') != identity:
            raise ValueError(f"{translate('The saved record was replaced for')} CT {vmid}")
        membership = current.get('stack_member', {})
        if membership.get('stack_id') != stack['id'] or membership.get('primary_vmid') != primary['vmid']:
            raise ValueError(f"{translate('Inconsistent stack membership for')} CT {vmid}")
        if current.get('status') != 'installed':
            raise ValueError(f"{translate('A pending operation exists for')} CT {vmid}")
        if vmid in inventory:
            if inventory[vmid] != identity:
                raise ValueError(f"{translate('Another instance uses')} VMID {vmid}")
            if vmid not in records:
                raise ValueError(f"{translate('The current record is missing for')} CT {vmid}")
        else:
            missing.append(vmid)
        if current.get('deployment', {}).get('rootfs_adaptation_replay_required'):
            blockers.append({'vmid': vmid, 'reason': 'dedicated-adapter-replay-required'})
        members.append(copy.deepcopy(current))
    if missing and operation == 'update':
        raise ValueError(translate('Stack members are missing; recreate them after verifying their volumes'))
    dependencies = [vmid for vmid in order if vmid != primary['vmid']]
    return {
        'operation': operation, 'primary_vmid': primary['vmid'],
        'members': members, 'missing_members': missing,
        'start_order': dependencies + [primary['vmid']],
        'stop_order': [primary['vmid']] + list(reversed(dependencies)),
        'blockers': blockers, 'volume_verification_required': bool(missing),
    }
