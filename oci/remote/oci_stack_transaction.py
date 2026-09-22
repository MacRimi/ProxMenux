"""Durable coordination protocol; native PVE adapters are supplied explicitly.

This module does not enable stack updates by itself. The adapter must hold the
instance registry lock, verify guest identities on every call, and implement
idempotent restore/publication using the transaction ID. No individual member
may publish its contract from replace(). All adapter results must be JSON data.
"""
import copy
import fcntl
import json
import os
from pathlib import Path
import stat
import uuid

from oci_installation_state import private_directory
from oci_instances import write
import oci_instance_transaction as member_tx
from oci_ui import translate, msg_info, msg_ok, msg_warn


TERMINAL = {'committed', 'rolled-back'}
PHASES = {'prepared', 'preparing', 'stopping', 'backing-up', 'replacing',
          'starting', 'checking', 'publishing', 'recovering',
          'recovery-failed'} | TERMINAL


def save(path, state, phase):
    if state.get('phase') != phase:
        member_tx.log(f'stack phase: {phase}')
    state['phase'] = phase
    write(path, state)


def member(adapter, vmid):
    describe = getattr(adapter, 'describe', None)
    return describe(vmid) if describe else f'CT {vmid}'


def validate_plan(plan):
    if plan.get('operation') not in ('update', 'recreate'):
        raise ValueError(translate('Invalid stack operation'))
    if plan.get('blockers') or plan.get('missing_members'):
        raise ValueError(translate('The stack needs member adaptations or a verification of missing volumes'))
    members = plan.get('members', [])
    ids = [member['vmid'] for member in members]
    if not ids or any(type(vmid) is not int or vmid < 100 for vmid in ids):
        raise ValueError(translate('Invalid stack members'))
    if len(set(ids)) != len(ids) or plan.get('primary_vmid') not in ids:
        raise ValueError(translate('Invalid main member or duplicated members'))
    for key in ('start_order', 'stop_order'):
        order = plan.get(key, [])
        if len(order) != len(ids) or set(order) != set(ids):
            raise ValueError(translate('Incomplete stack order'))
    if plan['start_order'][-1] != plan['primary_vmid'] or plan['stop_order'][0] != plan['primary_vmid']:
        raise ValueError(translate('The main member must stop first and start last'))


def recover_state(path, state, adapter):
    """Recover every private backup once replacement could have begun.

    A dependency may receive database writes even when only the frontend was
    replaced. Consequently rollback never restores just the failing member.
    External host files are deliberately outside this recovery protocol.
    """
    if state['phase'] in TERMINAL:
        if hasattr(adapter, 'finalize'):
            adapter.finalize(state)
        return state
    ids = {str(vmid) for vmid in state['plan']['start_order']}
    if (set(state.get('running', {})) != ids
            or any(type(value) is not bool for value in state['running'].values())
            or type(state.get('stop_intent')) is not bool
            or type(state.get('replacement_intent')) is not bool):
        raise ValueError(translate('The journal has an incomplete recovery state'))
    if state['replacement_intent'] and (not state['stop_intent'] or set(state.get('backups', {})) != ids):
        raise ValueError(translate('Stack backups are missing; a partial restore is not allowed'))
    adapter.validate(state['plan'])
    if state['replacement_intent'] and hasattr(adapter, 'verify_backups'):
        msg_info(translate('Verifying the backups...'))
        adapter.verify_backups(state['backups'])
        msg_ok(translate('Backups verified'))
    save(path, state, 'recovering')
    try:
        if state['stop_intent']:
            msg_info(translate('Stopping the stack...'))
            for vmid in state['plan']['stop_order']:
                adapter.stop(vmid)
            msg_ok(translate('Stack stopped'))
        if state['replacement_intent']:
            for vmid in state['plan']['start_order']:
                backup = state['backups'].get(str(vmid))
                if backup is None:
                    raise ValueError(translate('A stack backup is missing; a partial restore is not allowed'))
            for vmid in state['plan']['start_order']:
                msg_info(f"{translate('Restoring')} {member(adapter, vmid)}...")
                adapter.restore(vmid, state['backups'][str(vmid)], state['id'])
                msg_ok(f"{translate('Restored:')} {member(adapter, vmid)}")
            msg_info(translate('Restoring the stack records...'))
            adapter.restore_contracts(state['plan'], state['id'])
            msg_ok(translate('Stack records restored'))
        if state['stop_intent']:
            msg_info(translate('Returning the containers to their previous state...'))
            adapter.restore_running_state(state['running'], state['plan']['start_order'])
            msg_ok(translate('Containers returned to their previous state'))
        save(path, state, 'rolled-back')
    except Exception:
        save(path, state, 'recovery-failed')
        raise
    if hasattr(adapter, 'finalize'):
        adapter.finalize(state)
    return state


def _apply(path, plan, adapter):
    validate_plan(plan)
    if path.exists():
        raise ValueError(translate('A journal already exists; review or recover it before trying again'))
    adapter.validate(plan)
    running = {str(vmid): adapter.is_running(vmid) for vmid in plan['start_order']}
    if any(type(value) is not bool for value in running.values()):
        raise ValueError(translate('Invalid running state'))
    state = {'schema_version': 1, 'id': str(uuid.uuid4()),
             'plan': copy.deepcopy(plan), 'running': running,
             'prepared': {}, 'backups': {}, 'stop_intent': False,
             'replacement_intent': False}
    save(path, state, 'prepared')
    try:
        # Resolve/download/verify every candidate before stopping any service.
        save(path, state, 'preparing')
        for candidate in plan['members']:
            state['prepared'][str(candidate['vmid'])] = adapter.prepare(candidate, plan['operation'])
            save(path, state, 'preparing')
        adapter.validate(plan)
        state['stop_intent'] = True
        save(path, state, 'stopping')
        msg_info(translate('Stopping the stack...'))
        for vmid in plan['stop_order']:
            adapter.stop(vmid)
        msg_ok(translate('Stack stopped'))
        save(path, state, 'backing-up')
        for vmid in plan['start_order']:
            msg_info(f"{translate('Creating a backup of')} {member(adapter, vmid)}...")
            state['backups'][str(vmid)] = adapter.backup(vmid, state['id'])
            save(path, state, 'backing-up')
            msg_ok(f"{translate('Backup created:')} {member(adapter, vmid)}")
        # The adapter must verify all archives, free space and device identities.
        msg_info(translate('Verifying the backups...'))
        adapter.verify_backups(state['backups'])
        adapter.validate(plan)
        msg_ok(translate('Backups verified'))
        state['replacement_intent'] = True
        save(path, state, 'replacing')
        for vmid in plan['start_order']:
            msg_info(f"{translate('Updating')} {member(adapter, vmid)}...")
            adapter.replace(vmid, state['prepared'][str(vmid)], state['id'])
            msg_ok(f"{translate('Updated:')} {member(adapter, vmid)}")
        save(path, state, 'starting')
        for vmid in plan['start_order']:
            msg_info(f"{translate('Starting')} {member(adapter, vmid)}...")
            adapter.start(vmid)
            adapter.healthcheck(vmid)
            msg_ok(f"{translate('Service responding:')} {member(adapter, vmid)}")
        save(path, state, 'checking')
        msg_info(translate('Checking the updated stack...'))
        adapter.validate_candidates(state)
        adapter.restore_running_state(running, plan['start_order'])
        msg_ok(translate('Updated stack checked'))
        save(path, state, 'publishing')
        msg_info(translate('Saving the stack records...'))
        adapter.publish(state)
        save(path, state, 'committed')
        msg_ok(translate('Stack records saved'))
    except Exception as error:
        member_tx.report_error(error)
        try:
            error.oci_reported = True
        except AttributeError:
            pass
        if state['stop_intent']:
            msg_warn(translate('Restoring the previous state of the stack...'))
        recover_state(path, state, adapter)
        raise
    if hasattr(adapter, 'finalize'):
        adapter.finalize(state)
    return state


def execute(journal, adapter, plan=None):
    """Apply when plan is supplied; otherwise explicitly recover an old journal."""
    path = Path(journal)
    private_directory(path.parent)
    lock = path.with_name(path.name + '.lock')
    if path.is_symlink() or lock.is_symlink():
        raise ValueError(translate('Unsafe journal or lock file'))
    with lock.open('a') as handle:
        lock.chmod(0o600)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if plan is not None:
            return _apply(path, plan, adapter)
        attributes = path.lstat()
        if (not stat.S_ISREG(attributes.st_mode) or attributes.st_uid != os.geteuid()
                or attributes.st_mode & 0o077):
            raise ValueError(translate('The private journal has an unsafe owner or permissions'))
        state = json.loads(path.read_text())
        if state.get('schema_version') != 1 or state.get('phase') not in PHASES:
            raise ValueError(translate('Invalid stack journal'))
        validate_plan(state['plan'])
        return recover_state(path, state, adapter)
