"""Apply CPU/RAM-only proposals to the existing guest, without an image archive."""
import copy
import hashlib
from pathlib import Path
import uuid

import oci_instances as instances
import oci_instance_transaction as transaction
from oci_installation_state import parse_config, sha
from oci_ui import translate, msg_info, msg_ok, msg_warn

CONFIG_DIR = Path('/etc/pve/lxc')


def changes(record, candidate, config):
    """Return a narrow native edit, or None when the normal installer is needed."""
    previous = transaction.with_default_healthcheck(copy.deepcopy(record))
    candidate = transaction.with_default_healthcheck(copy.deepcopy(candidate))
    old, new = previous['deployment'], candidate['deployment']
    if previous['template'] != candidate['template'] or old.get('host_monitor'):
        return None
    if {k: v for k, v in old.items() if k != 'resources'} != {
            k: v for k, v in new.items() if k != 'resources'}:
        return None
    original, desired = old.get('resources', {}), new.get('resources', {})
    changed = {key for key in original.keys() | desired.keys() if original.get(key) != desired.get(key)}
    if not changed or changed - {'cores', 'memory_mb'}:
        return None
    cfg = parse_config(config)
    cpu = 'cpulimit' if 'cpulimit' in cfg and 'cores' not in cfg else 'cores'
    parameters = {}
    for key in sorted(changed):
        value = desired.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < (128 if key == 'memory_mb' else 1):
            return None
        native = 'memory' if key == 'memory_mb' else cpu
        if native not in cfg:
            return None
        parameters[native] = str(value)
    return parameters


def guarded_set(vmid, installation_id, expected, parameters):
    # pct uses this SHA1 under its own configuration lock. Sample the native
    # file before checking pct's view, so a concurrent edit cannot be accepted
    # accidentally by taking a fresh digest after validation.
    native = (CONFIG_DIR / f'{vmid}.conf').read_bytes()
    current = instances.command('pct', 'config', str(vmid))
    if current != expected or instances.identity(current) != installation_id:
        raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
    command = ['pct', 'set', str(vmid), '--digest', hashlib.sha1(native).hexdigest()]
    for key, value in sorted(parameters.items()):
        command += ['--' + key, value]
    transaction.run(*command)


def expected_config(before, after, parameters):
    def unrelated(config):
        return b''.join(line for line in config.splitlines(keepends=True)
                        if line.split(b':', 1)[0].decode() not in parameters)
    new = parse_config(after)
    return unrelated(before) == unrelated(after) and all(new.get(key) == value for key, value in parameters.items())


def apply(root, record, candidate, config, parameters):
    """The caller holds the instance lock and has checked image identity/preflight."""
    if changes(record, candidate, config) != parameters:
        raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
    vmid = record['vmid']
    directory = instances.location(root, vmid).parent / 'modifications' / uuid.uuid4().hex
    instances.write(directory / 'before.json', {'record': record, 'config': config.decode()})
    transaction.open_log(directory)
    msg_info(translate('Applying CPU and RAM changes without rebuilding the container...'))
    applied = False
    after = None
    try:
        guarded_set(vmid, record['installation_id'], config, parameters)
        applied = True
        after = instances.command('pct', 'config', str(vmid))
        if not expected_config(config, after, parameters):
            raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
        observed = record['observed']
        fresh = instances.observe(vmid, record['installation_id'], observed['archive_path'],
                                  observed['resolved_registry_digest'], observed['image'])
        if fresh['config_sha256'] != sha(after):
            raise ValueError(translate('The instance changed while it was being edited; open Modify again'))
        updated = copy.deepcopy(record)
        updated.update(deployment=copy.deepcopy(candidate['deployment']), observed=fresh)
        instances.write(instances.location(root, vmid), updated)
    except Exception:
        if applied:
            try:
                current = instances.command('pct', 'config', str(vmid))
                if not expected_config(config, current, parameters):
                    raise ValueError('Concurrent configuration change; resource rollback refused')
                previous = parse_config(config)
                guarded_set(vmid, record['installation_id'], current,
                            {key: previous[key] for key in parameters})
                instances.write(instances.location(root, vmid), record)
            except Exception as error:
                transaction.log(f'resource rollback: {type(error).__name__}')
                msg_warn(translate('The resource edit could not be fully rolled back. Open Manage again to review and import the current Proxmox settings.'))
        raise
    # Updating the carried record is best effort here, as it is after other
    # management operations. The normal menu also refreshes it on return.
    try:
        import oci_carried_record
        oci_carried_record.carry(root, vmid, mount_stopped=False)
    except (OSError, ValueError, RuntimeError):
        transaction.log('carried record will be refreshed on the next management entry')
    msg_ok(translate('Changes applied. Data kept.'))
    return directory
