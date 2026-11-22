"""Read-only validation of a coordinated stack operation, before host changes."""
import copy
import oci_stack_public_routes as public_routes
import re
import uuid

from oci_ui import translate


def validate_job_check(check, record=None):
    """Validate a completion proof request without treating STOPPED as success."""
    failure = translate('Invalid service check arguments')
    if not isinstance(check, dict) or check.get('type') != 'completed':
        raise ValueError(failure)
    job = check.get('job')
    if not isinstance(job, dict):
        raise ValueError(failure)
    try:
        identity = str(uuid.UUID(job['installation_id']))
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise ValueError(failure) from error
    timeout = job.get('timeout_seconds')
    if (type(timeout) is not int or not 30 <= timeout <= 3600
            or type(check.get('timeout_seconds')) is not int or check['timeout_seconds'] != timeout
            or not isinstance(job.get('image_digest'), str)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', job['image_digest'])
            or not isinstance(job.get('expected_config_fingerprint'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', job['expected_config_fingerprint'])):
        raise ValueError(failure)
    if record is not None and (record.get('installation_id') != identity
            or record.get('observed', {}).get('resolved_registry_digest') != job['image_digest']):
        raise ValueError(failure)
    return job


def validate_public_route_members(primary_id, records):
    """A route may name only the frontends of this exact recorded stack."""
    for vmid, record in records.items():
        spec = public_routes.validate(record.get('deployment', {}), vmid, record['installation_id'])
        if spec is None:
            continue
        primary = records.get(primary_id)
        if (primary is None or spec['primary_vmid'] != primary_id
                or spec['stack_id'] != primary['installation_id']):
            raise ValueError(translate('Invalid stack contract'))
        members = {member['vmid']: member['installation_id']
                   for member in primary.get('stack', {}).get('members', [])}
        if members.get(vmid) != record['installation_id']:
            raise ValueError(translate('Invalid stack contract'))
        for route in spec['routes']:
            target = records.get(route['target_vmid'])
            if (target is None or target['installation_id'] != route['target_installation_id']
                    or members.get(route['target_vmid']) != route['target_installation_id']):
                raise ValueError(translate('Invalid stack contract'))


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
    validate_public_route_members(primary['vmid'], records)
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
        service = next(service for service in services if service['vmid'] == vmid)
        if service.get('healthcheck', {}).get('type') == 'completed':
            validate_job_check(service['healthcheck'], current)
            if (vmid == primary['vmid'] or current.get('deployment', {}).get('onboot')
                    or current.get('deployment', {}).get('watchdog')
                    or current.get('deployment', {}).get('execution_mode') != 'one-shot'):
                raise ValueError(translate('Invalid service check arguments'))
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
