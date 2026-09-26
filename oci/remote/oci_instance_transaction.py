#!/usr/bin/env python3
"""Recoverable, explicit OCI operations using saved instance contracts.

First execution profile: local, unprivileged standalone CTs with backed-up
managed mounts and explicitly acknowledged host directories. No automatic
adoption, stack updates or storage migration.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import stat
import sys
import time
import uuid
from urllib.parse import unquote

import oci_instances as instances
from oci_installation_state import image_from_archive, parse_config, private_directory, sha
from verify_oci_archive import verify_archive
import oci_host_mounts as host_mounts
import oci_accelerators as gpu_devices
import oci_runtime_settings as runtime_settings
import oci_image_cache as image_cache
import oci_ui
from oci_ui import translate, msg_info, msg_ok, msg_warn, msg_error, msg_info2

TERMINAL = {'committed', 'rolled-back'}
BASIC = {'arch', 'cmode', 'console', 'tty', 'cores', 'cpulimit', 'cpuunits', 'description',
         'entrypoint', 'env', 'features', 'hostname', 'memory', 'net0', 'onboot',
         'ostype', 'rootfs', 'swap', 'tags', 'unprivileged',
         'lxc.init.cwd', 'lxc.init.uid', 'lxc.init.gid', 'lxc.init.groups',
         'lxc.signal.halt', 'lxc.environment.runtime',
         # The container's console log, set by the installer on every
         # creation; the rebuilt container gets it again the same way.
         'lxc.console.logfile'}
# Their output is data (and may hold saved secrets); it is never logged.
DATA_COMMANDS = {('pct', 'config'), ('pvesh', 'get')}
LOG_DIR = Path(os.environ.get('OCI_LOG_DIR', '/var/log/proxmenux/oci'))
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
SPINNER_FRAME = re.compile('^ ?[' + ''.join(oci_ui.FRAMES) + ']')
# The private log of this run, the journal that a failure leaves pending and,
# when the shared installer is what failed, its log and last lines.
_run = {'log': None, 'pending': [], 'journal': None, 'failed_log': None, 'failed_lines': None}


def screen_text(line):
    """What a terminal shows for one output line, without colours."""
    parts = [SPINNER_FRAME.sub('', ANSI.sub('', part)).rstrip() for part in line.split('\r')]
    parts = [part for part in parts if part.strip()]
    return parts[-1] if parts else ''


def log(text):
    """Private log of the operation; kept in memory until its directory exists."""
    if _run['log']:
        try:
            oci_ui.log(_run['log'], text)
        except OSError:
            pass
    else:
        _run['pending'].append(text)
        del _run['pending'][:-2000]


def log_output(stdout=None, stderr=None, limit=40):
    for content in (stdout, stderr):
        if not content:
            continue
        if isinstance(content, bytes):
            content = content.decode(errors='replace')
        lines = [text for text in (screen_text(line) for line in content.split('\n')) if text]
        if len(lines) > limit:
            log(f'  ... {len(lines) - limit} earlier lines omitted')
            lines = lines[-limit:]
        for text in lines:
            log('  ' + text[:500])


def _start_log(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a', encoding='utf-8') as output:
        output.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                     f"{Path(sys.argv[0]).name} {' '.join(sys.argv[1:])}\n")
        for line in _run['pending']:
            output.write(line.rstrip('\n') + '\n')
    _run.update(log=path, pending=[])
    # Helpers that follow the OCI_LOG convention (image verification) write here too.
    os.environ['OCI_LOG'] = str(path)


def open_log(directory):
    """transaction.log in the private directory of the operation."""
    if not _run['log']:
        try:
            _start_log(Path(directory) / 'transaction.log')
        except OSError:
            pass
    return _run['log']


def log_file(name):
    """The log of this run; a run that stopped before its transaction
    directory existed gets one in the OCI log directory."""
    if _run['log'] or not _run['pending']:
        return _run['log']
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', name)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        _start_log(LOG_DIR / f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}.log")
    except OSError:
        return None
    return _run['log']


def log_tail(path, count=12):
    with open(path, 'rb') as source:
        source.seek(0, os.SEEK_END)
        source.seek(max(0, source.tell() - 65536))
        data = source.read().decode(errors='replace')
    lines = [screen_text(line) for line in data.split('\n')]
    return [line for line in lines if line and not line.startswith('PROXMENUX_RESULT=')][-count:]


def command_name(cmd):
    if isinstance(cmd, (list, tuple)) and cmd:
        cmd = cmd[0]
    return Path(str(cmd)).name


def error_text(error):
    if isinstance(error, KeyError):
        return translate('The saved OCI record is incomplete or has an unexpected format.')
    if isinstance(error, subprocess.TimeoutExpired):
        return f"{translate('A command did not finish in time:')} {command_name(error.cmd)}"
    if isinstance(error, subprocess.CalledProcessError):
        return f"{command_name(error.cmd)} {translate('failed with exit code')} {error.returncode}"
    if isinstance(error, OSError):
        detail = error.strerror or str(error)
        return f"{translate('System error:')} {detail}" + (f' ({error.filename})' if error.filename else '')
    return str(error) or type(error).__name__


def installer_failure(path, count=10):
    """The error reported by the shared installer and the log lines before it."""
    try:
        lines = [screen_text(line).strip() for line in log_tail(path, 400)]
    except OSError:
        return None, []
    lines = [line for line in lines if line]
    errors = [i for i, line in enumerate(lines) if line.startswith('[ERROR] ')]
    if not errors:
        return None, lines[-count:]
    index = errors[-1]
    # The installer repeats its own log tail after the error; the lines before it suffice.
    first = next((i for i in errors if lines[i] == lines[index]), index)
    return lines[index][len('[ERROR] '):], lines[max(0, first - count):first]


def report_error(error, name='oci-lifecycle'):
    """Error line, the last lines of the private log and its path."""
    msg_error(error_text(error))
    path, lines = _run['failed_log'], _run['failed_lines']
    _run.update(failed_log=None, failed_lines=None)
    if path is None:
        path = log_file(name)
        try:
            lines = log_tail(path) if path else []
        except OSError:
            lines = []
    for line in lines or []:
        print(f'{oci_ui.TAB}  {line}', flush=True)
    if path:
        print(f"{oci_ui.TAB}{translate('Full log:')} {path}", flush=True)
    log(f'error: {type(error).__name__}: {error}')


def pending_journal():
    """The journal of this run when a failure left it open for recovery."""
    journal = _run['journal']
    if journal is None:
        return None
    try:
        phase = json.loads(Path(journal).read_text()).get('phase')
    except (OSError, ValueError):
        return journal
    return None if phase in TERMINAL else journal


def recovery_hint(after_recovery=False):
    if after_recovery:
        msg_warn(translate('The recovery did not complete. Review the log and choose "Recover" again for this container in the OCI management menu.'))
    else:
        msg_warn(translate('The operation stopped halfway. Choose "Recover" for this container in the OCI management menu to restore the previous installation.'))


def recover_untouched(root, journal):
    """Close an operation that failed before the container was changed:
    start the container again and restore its record, so nothing is left to
    recover by hand. Returns whether it did."""
    try:
        state = json.loads(Path(journal).read_text())
        if state.get('coordinated') or state.get('phase') in TERMINAL:
            return False
        if run('pct', 'config', str(state['vmid'])).decode() != state['before_config']:
            return False
        recover(root, Path(journal))
        return True
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        log(f'automatic recovery skipped: {error}')
        return False


def fit(text):
    """A step line that is rewritten in place must not wrap."""
    width = max(shutil.get_terminal_size((80, 24)).columns - 8, 30)
    return text if len(text) <= width else text[:width - 1] + '…'


def run(*args):
    private_description = args[:2] == ('pct', 'set') and '--description' in args
    shown = [str(arg) for arg in args]
    if private_description:
        shown[shown.index('--description') + 1] = '[notes redacted]'
    log('$ ' + shlex.join(shown))
    # OCI extraction enters an unprivileged user namespace; PVE's newly created
    # traversal directories must not inherit a caller's restrictive umask.
    pve_creation = (args[:2] in (('pct', 'create'), ('pct', 'restore'))
                    or args[0] == 'vzdump')
    try:
        result = subprocess.run(args, capture_output=True, timeout=1800, close_fds=True,
                                umask=0o022 if pve_creation else -1)
    except subprocess.TimeoutExpired:
        log('  timeout')
        raise
    if result.returncode:
        log(f'  exit {result.returncode}')
    log_output(None if private_description or tuple(args[:2]) in DATA_COMMANDS else result.stdout,
               None if private_description else result.stderr)
    if result.returncode:
        raise RuntimeError(f"{args[0]} {translate('failed with exit code')} {result.returncode}")
    return result.stdout


def verified_backup(vmid, directory, compression, unidentified, show=False):
    """A stop-mode vzdump of vmid in directory that passes its integrity
    check. An archive that fails the check is written once more before the
    operation gives up."""
    suffix = 'zst' if compression == 'zstd' else 'gz'
    for attempt in (1, 2):
        run('vzdump', str(vmid), '--mode', 'stop', '--compress', compression,
            '--dumpdir', str(directory), '--tmpdir', '/var/tmp')
        backups = list(directory.glob(f'vzdump-lxc-*.tar.{suffix}'))
        if len(backups) != 1:
            raise ValueError(unidentified)
        try:
            run('zstd' if compression == 'zstd' else 'gzip', '-t', str(backups[0]))
            return backups[0]
        except RuntimeError:
            if attempt == 2:
                raise
        log('backup attempt 1/2 failed its integrity check')
        for damaged in directory.glob('vzdump-lxc-*'):
            damaged.unlink()
        if show:
            msg_warn(translate('The backup did not pass its integrity check; creating it again...'))


def filehash(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def checkpoint(path, state, phase):
    state['phase'] = phase
    instances.write(path, state)
    log(f'phase: {phase}')


def mounts(config):
    result = {}
    for key, value in parse_config(config).items():
        if re.fullmatch(r'mp[0-9]+', key):
            source, *options = value.split(',')
            options = dict(item.split('=', 1) for item in options if '=' in item)
            target = options.get('mp')
            if not target or target in result:
                raise ValueError(translate('Ambiguous mount points in the container'))
            result[target] = {'key': key, 'value': value, 'volume': source, **options}
    return result


def effective_healthcheck(template):
    """The template's own health check or, when it has none, one derived from
    its web address: any HTTP answer below 500 means the application is up."""
    profile = template.get('proxmox', {}).get('installer_profile', {})
    check = profile.get('startup_healthcheck')
    if check or profile.get('haos_healthcheck') or profile.get('host_monitor'):
        return check
    for endpoint in template.get('first_run', {}).get('endpoints', []):
        path = str(endpoint.get('path') or '/')
        if (endpoint.get('scheme') in ('http', 'https') and str(endpoint.get('port', '')).isdigit()
                and path.startswith('/') and not any(c.isspace() for c in path)):
            return {'scheme': endpoint['scheme'], 'port': int(endpoint['port']), 'path': path,
                    'timeout_seconds': 300, 'request_timeout_seconds': 10, 'stability_seconds': 4,
                    'verify_tls': False, 'accept_any_status': True}
    # Without a web address, the new image must at least keep the container running.
    return {'type': 'running', 'timeout_seconds': 90, 'stability_seconds': 20}


def with_default_healthcheck(contract):
    check = effective_healthcheck(contract['template'])
    if check:
        contract['template'].setdefault('proxmox', {}).setdefault('installer_profile', {})['startup_healthcheck'] = check
    return contract


def candidate_contract(record, operation, proposal=None):
    if record.get('status') != 'installed':
        raise ValueError(translate('The instance is not ready; review its pending operation'))
    if operation not in ('update', 'recreate'):
        raise ValueError(translate('Unsupported operation'))
    if operation == 'update':
        if proposal is not None:
            raise ValueError(translate('An update does not accept configuration changes'))
        return with_default_healthcheck(copy.deepcopy(record))
    if not isinstance(proposal, dict) or proposal.get('operation') != 'recreate':
        raise ValueError(translate('Recreating requires a confirmed proposal'))
    if (proposal.get('base_config_sha256') is not None
            and proposal['base_config_sha256'] != record['observed']['config_sha256']):
        raise ValueError(translate('The instance changed while it was being edited; configure Recreate again'))
    candidate = proposal['candidate']
    if (candidate.get('vmid') != record['vmid']
            or candidate.get('installation_id') != record['installation_id']
            or candidate['template']['id'] != record['template']['id']
            or candidate['deployment'].get('vmid') != record['vmid']):
        raise ValueError(translate('The proposal changes the identity of the instance'))
    # Only desired state is editable; caller cannot forge observed evidence.
    result = copy.deepcopy(record)
    result.update(template=copy.deepcopy(candidate['template']),
                  deployment=copy.deepcopy(candidate['deployment']))
    return with_default_healthcheck(result)


# Resource settings edited in Proxmox that the new container keeps.
# Proxmox settings the rebuilt container gets back exactly as they are: the
# LAN leg ProxMenux adds to a suite or stack member, and the start order.
KEPT_AS_IS = ('net1', 'startup')
ADOPTABLE = {'memory': ('resources', 'memory_mb'), 'swap': ('resources', 'swap_mb'),
             'cores': ('resources', 'cores'), 'cpulimit': ('resources', 'cores'),
             'cpuunits': ('resources', 'cpu_units'), 'onboot': (None, 'onboot')}


def external_changes(record, config, adopt=True):
    """Settings changed in Proxmox since the last operation, as deployment
    values. Any change the new container cannot keep is refused."""
    if sha(config) == record['observed']['config_sha256']:
        return {}
    before, now = parse_config(record['observed']['config'].encode()), parse_config(config)
    changed = sorted(key for key in before.keys() | now.keys() if before.get(key) != now.get(key))
    if ('description' in changed
            and instances.identity(record['observed']['config'].encode()) == record['installation_id']
            and instances.identity(config) == record['installation_id']):
        changed.remove('description')
    cores_key = 'cpulimit' if 'cpulimit' in before and 'cores' not in before else 'cores'
    values = {}
    for key in changed if adopt else ():
        value = now.get(key)
        if key == 'onboot':
            values[key] = value == '1'
        elif key == 'cpuunits' and value is None:
            values[key] = None
        elif key in ('memory', 'swap', 'cpuunits', cores_key) and value and re.fullmatch(r'[0-9]+', value):
            if int(value) > 0 or key == 'swap':
                values[key] = int(value)
    refused = [key for key in changed if key not in values and key not in KEPT_AS_IS]
    if refused:
        raise ValueError(f"{translate('The container was changed outside ProxMenux and an update would discard those changes:')} "
                         f"{', '.join(refused)}")
    return values


def preflight(record, candidate, config, coordinated=None):
    deployment = record['deployment']
    desired = candidate['deployment']
    if coordinated and (record.get('native_stack_intent') or deployment.get('rootfs_adaptation_replay_required')):
        raise ValueError(translate('The dedicated adapter still requires replaying its rootfs changes'))
    if not coordinated and (any(key in record for key in ('stack', 'stack_member', 'native_stack_intent')) or deployment.get('stack_managed')):
        raise ValueError(translate('Stack members are updated together with their stack'))
    if instances.identity(config) != record['installation_id']:
        raise ValueError(translate('The container identity changed; the container is not replaced'))
    for key, value in external_changes(record, config, adopt=not coordinated).items():
        section, name = ADOPTABLE[key]
        recorded = deployment.get(section, {}) if section else deployment
        target = desired.setdefault(section, {}) if section else desired
        if target.get(name) == recorded.get(name):
            target[name] = value
    cfg = parse_config(config)
    for key in ('lxc.init.uid', 'lxc.init.gid'):
        if key in cfg and not re.fullmatch(r'[0-9]+', cfg[key]):
            raise ValueError(translate('The imported OCI user or group is not numeric'))
    if 'lxc.init.groups' in cfg and not re.fullmatch(r'(?:[0-9]+(?:[ ,][0-9]+)*)?', cfg['lxc.init.groups']):
        raise ValueError(translate('The imported OCI groups are not numeric'))
    keys = {line.split(': ', 1)[0] for line in config.decode().splitlines() if ': ' in line}
    runtime_keys = {'lxc.mount.entry'} if gpu_devices.nvidia.enabled(deployment) else set()
    if gpu_devices.dynamic_mode(deployment):
        runtime_keys = {'lxc.hook.mount', 'lxc.environment'}
    if deployment.get('tmpfs_mounts'):
        runtime_keys.add('lxc.mount.entry')
    if deployment.get('security', {}).get('sysctls'):
        runtime_keys.add('lxc.include')
    runtime_settings.check(config, deployment, record['vmid'])
    coordinated_keys = {'hookscript', *KEPT_AS_IS} if coordinated else set(KEPT_AS_IS)
    if '[' in config.decode() or keys - BASIC - runtime_keys - coordinated_keys - {k for k in keys if re.fullmatch(r'(mp|dev)[0-9]+', k)}:
        raise ValueError(translate('The container has advanced Proxmox settings outside the supported profile'))
    for plan in (deployment, desired):
        security = plan.get('security', {})
        if (security.get('unprivileged') is not True
                or security.get('options') or plan.get('host_monitor')
                or plan.get('resources', {}).get('rlimits')):
            raise ValueError(translate('Updates are not available yet in this beta for applications that use '
                                       'a privileged container or advanced LXC settings'))
        runtime_settings.sysctl_content(plan)
        runtime_settings.tmpfs_lines(plan)
        gpu_devices.planned(plan)
        paths = []
        for mount in plan.get('mounts', []):
            target = host_mounts.valid_path(mount['container_path'])
            if (any(target == p or target.startswith(p.rstrip('/') + '/')
                           or p.startswith(target.rstrip('/') + '/') for p in paths)):
                raise ValueError(translate('Mount paths must not overlap'))
            if mount['type'] == 'managed-volume':
                if mount.get('backup') is not True or not isinstance(mount.get('size_gb'), int) or mount['size_gb'] < 1:
                    raise ValueError(translate('Managed disks must have backup enabled and a valid size'))
            elif mount['type'] == 'host-bind':
                if mount.get('backup') is not False:
                    raise ValueError(translate('Host directories cannot be part of the vzdump backup'))
                host_mounts.valid_path(mount['source'])
            else:
                raise ValueError(translate('Unsupported mount type'))
            paths.append(target)
    if cfg.get('unprivileged') != '1' or ':' not in cfg.get('rootfs', ''):
        raise ValueError(translate('A managed rootfs and an unprivileged container are required'))
    if desired['rootfs'] != deployment['rootfs']:
        raise ValueError(translate('Changing the rootfs or its storage requires a separate migration'))
    actual = mounts(config)
    gpu_devices.check(config, deployment)
    gpu_devices.verify_baseline(record['observed'].get('gpu_devices', {}), deployment)
    old = {m['container_path']: m for m in deployment.get('mounts', [])}
    new = {m['container_path']: m for m in desired.get('mounts', [])}
    if set(actual) != set(old):
        raise ValueError(translate('The container disks do not match the saved record'))
    for target, mount in actual.items():
        host_bind = old[target]['type'] == 'host-bind'
        if ((host_bind and (mount['volume'] != old[target]['source'] or mount.get('backup', '0') != '0'))
                or (not host_bind and (mount.get('backup') != '1' or not mount['volume'].startswith(old[target]['source'] + ':')))
                or mount.get('ro', '0') != ('1' if old[target].get('read_only') else '0')):
            raise ValueError(translate('A container mount has a source, backup or permission different from the saved record'))
    for target in old.keys() & new.keys():
        if any(old[target].get(k) != new[target].get(k) for k in ('type', 'source', 'size_gb')):
            raise ValueError(translate('Changing the storage or size of a disk requires a migration; empty disks are not created'))
    protected = ('/bin', '/sbin', '/etc', '/usr', '/lib', '/lib64', '/proc', '/sys', '/dev', '/run')
    for target in new.keys() - old.keys():
        if any(target == p or target.startswith(p + '/') or p.startswith(target + '/') for p in protected):
            raise ValueError(translate('The additional path hides a system directory'))
    for template, plan in ((record['template'], deployment), (candidate['template'], desired)):
        required = {v['container_path'] for v in template['container_contract'].get('volumes', []) if v.get('required', True)}
        if not required <= {m['container_path'] for m in plan.get('mounts', [])}:
            raise ValueError(translate('Required persistent paths cannot be removed'))
    image_paths = record['observed']['image']['defaults'].get('Volumes') or {}
    if any(not any(p == target or p.startswith(target.rstrip('/') + '/') for target in old) for p in image_paths):
        raise ValueError(translate('The image declares data paths that are still stored in the rootfs'))
    check = effective_healthcheck(candidate['template'])
    if not check and not coordinated:
        raise ValueError(translate('Updates are not available yet for this application in this beta'))
    mac = next((item[7:] for item in cfg['net0'].split(',') if item.startswith('hwaddr=')), None)
    if not mac:
        raise ValueError(translate('The MAC address of the container cannot be kept'))
    return cfg, actual, mac


def freeze_host_sources(record, candidate, acknowledge_external_data):
    old = {m['source'] for m in record['deployment'].get('mounts', []) if m['type'] == 'host-bind'}
    wanted = {m['source']: m for m in candidate['deployment'].get('mounts', []) if m['type'] == 'host-bind'}
    if (old or wanted) and not acknowledge_external_data:
        raise ValueError(translate('Host data is not restored by the backup; confirm it with --acknowledge-external-data'))
    baseline = record['observed'].get('host_bind_sources', {})
    original = {p: host_mounts.validate_source(p) for p in old}
    for source, previous in baseline.items():
        if source in original and not host_mounts.same_source(previous, original[source]):
            raise ValueError(translate('A shared source does not match its recorded identity'))
    desired = {p: original[p] if p in original else
               host_mounts.validate_source(p, allow_missing=m.get('create_if_missing') is True)
               for p, m in wanted.items()}
    if old or wanted:
        log('host directories: not included in the backup and not reverted by a recovery')
    if old - set(baseline):
        log('host directories without a recorded identity: their current identity is pinned')
    return original, desired


def check_runtime_mounts(config, deployment):
    runtime_settings.check(config, deployment, deployment['vmid'])
    actual = mounts(config)
    declared = {m['container_path']: m for m in deployment.get('mounts', [])}
    if actual.keys() != declared.keys():
        raise ValueError(translate('The mounts of the new container do not match the proposal'))
    for target, value in actual.items():
        expected = declared[target]
        source_ok = value['volume'] == expected['source'] if expected['type'] == 'host-bind' else value['volume'].startswith(expected['source'] + ':')
        if (not source_ok or value.get('backup', '0') != ('1' if expected['backup'] else '0')
                or value.get('ro', '0') != ('1' if expected.get('read_only') else '0')):
            raise ValueError(translate('The mount source or options were not kept'))


def pin_host_source(root, vmid, journal, source):
    state = json.loads(journal.read_text())
    record = instances.read(root, vmid)
    if (state['vmid'] != vmid or state['phase'] != 'installing-candidate'
            or record.get('transaction_id') != state['id'] or record.get('pending_transaction') != str(journal)
            or record['installation_id'] != state['record']['installation_id'] or record['status'] != 'updating'):
        raise ValueError(translate('Mount not authorized by the operation'))
    expected = state['desired_host_sources'][source]
    current = host_mounts.validate_source(source)
    if ((expected['exists'] and not host_mounts.same_source(expected, current))
            or current['resolved_path'] != expected['resolved_path']):
        raise ValueError(translate('The host directory changed before it was mounted'))
    path = journal.parent / 'candidate-host-sources.json'
    pinned = json.loads(path.read_text()) if path.exists() else {}
    if source in pinned and not host_mounts.same_source(pinned[source], current):
        raise ValueError(translate('A shared directory was replaced during the installation'))
    pinned[source] = current
    instances.write(path, pinned)


def candidate_host_sources(journal, state):
    expected = state.get('desired_host_sources', {})
    if not expected:
        return {}
    path = journal.parent / 'candidate-host-sources.json'
    pinned = json.loads(path.read_text())
    if pinned.keys() != expected.keys():
        raise ValueError(translate('Not all shared directories were verified'))
    for source, previous in expected.items():
        if previous['exists'] and not host_mounts.same_source(previous, pinned[source]):
            raise ValueError(translate('The mounted source differs from the configured directory'))
    host_mounts.verify_sources(pinned)
    return pinned


def stop(vmid):
    if run('pct', 'status', str(vmid)).strip() == b'status: running':
        run('pct', 'shutdown', str(vmid), '--timeout', '60')
    if run('pct', 'status', str(vmid)).strip() != b'status: stopped':
        raise ValueError(translate('The container did not stop; its disks are not touched'))


def healthcheck(vmid, template):
    check = effective_healthcheck(template)
    if not check:
        return None
    if check.get('type') == 'running':
        stability = int(check.get('stability_seconds', 20))
        started = time.monotonic()
        while time.monotonic() - started < stability:
            if run('pct', 'status', str(vmid)).strip() != b'status: running':
                raise ValueError(translate('The restored service stopped; the recovery is not confirmed'))
            time.sleep(2)
        log(f'container {vmid} kept running for {stability}s')
        return None
    scheme, port, path = check['scheme'], int(check['port']), check['path']
    timeout = int(check.get('timeout_seconds', 120))
    stability = int(check.get('stability_seconds', 0))
    if (scheme not in ('http', 'https') or not 1 <= port <= 65535
            or not path.startswith('/') or any(c.isspace() for c in path)
            or not 0 <= stability < timeout <= 3600):
        raise ValueError(translate('Invalid health check'))
    started, stable_since = time.monotonic(), None
    while time.monotonic() - started < timeout:
        if run('pct', 'status', str(vmid)).strip() != b'status: running':
            raise ValueError(translate('The restored service stopped; the recovery is not confirmed'))
        addresses = run('lxc-info', '-n', str(vmid), '-iH').decode().splitlines()
        ip = next((a for a in addresses if re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', a)), None)
        ok = False
        if ip:
            any_status = check.get('accept_any_status', False)
            args = ['curl', '-sS' if any_status else '-fsS', '--noproxy', '*', '-o', '/dev/null',
                    '--max-time', str(check.get('request_timeout_seconds', 5))]
            if any_status:
                args += ['-w', '%{http_code}']
            if not check.get('verify_tls', False):
                args.append('-k')
            try:
                answer = run(*args, f'{scheme}://{ip}:{port}{path}')
                ok = not any_status or re.fullmatch(rb'[1-4][0-9][0-9]', answer.strip()) is not None
            except RuntimeError:
                pass
        if ok:
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= stability:
                log(f'restored service responding: {scheme}://{ip}:{port}{path}')
                return f'{scheme}://{ip}:{port}{path}'
        else:
            stable_since = None
        log(f'waiting for the restored service: {int(time.monotonic() - started)}s')
        time.sleep(2)
    raise ValueError(translate('The restored service did not pass its health check'))


def owned(vmid, marker):
    data = run('pct', 'config', str(vmid))
    description = parse_config(data).get('description', '')
    if marker not in description:
        raise ValueError(translate('The VMID was reused or its identity is unknown; the operation is blocked'))
    return data


def authorize(root, vmid, journal, template_file, deployment_file):
    state = json.loads(journal.read_text())
    record = instances.read(root, vmid)
    if (state['vmid'] != vmid or state['phase'] != 'installing-candidate'
            or record.get('pending_transaction') != str(journal)
            or record.get('transaction_id') != state['id'] or record['status'] != 'updating'
            or record['installation_id'] != state['record']['installation_id']
            or json.loads(template_file.read_text()) != state['runtime_template']
            or json.loads(deployment_file.read_text()) != state['runtime_deployment']
            or filehash(state['archive']) != state['archive_sha256']):
        raise ValueError(translate('The new container is not authorized by the operation journal'))
    host_mounts.verify_sources(state.get('desired_host_sources', {}))
    gpu_devices.verify(state.get('desired_gpu_devices', {}))
    return record['installation_id']


def child_step(path, position):
    """The last step announced by the shared installer since position."""
    try:
        with open(path, 'rb') as source:
            source.seek(position)
            data = source.read()
    except OSError:
        return position, None
    end = data.rfind(b'\n') + 1
    step = None
    for line in data[:end].decode(errors='replace').split('\n'):
        match = re.fullmatch(r' {4}-(\S.*)', screen_text(line))
        if match:
            step = match.group(1).strip()
    return position + end, step


def install_candidate(root, journal, state, progress=None):
    directory = journal.parent
    template = directory / 'candidate-template.json'
    deployment = directory / 'candidate-deployment.json'
    instances.write(template, state['runtime_template'])
    instances.write(deployment, state['runtime_deployment'])
    installer_log = directory / 'installer.log'
    # The installer writes its steps and command output to its own private log.
    env = dict(os.environ, PROXMENUX_OCI_TRANSACTION=str(journal),
               PROXMENUX_OCI_INSTANCE_ROOT=str(root), OCI_LOG=str(installer_log), OCI_SPINNER='0')
    env.pop('PROXMENUX_INSTANCE_LOCK_FD', None)
    fd = os.open(installer_log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
    log(f'$ install_oci.sh {template} {deployment} (output: {installer_log})')
    with os.fdopen(fd, 'w') as output:
        process = subprocess.Popen(['bash', str(Path(__file__).with_name('install_oci.sh')),
                                   str(template), str(deployment)],
                                   stdout=output, stderr=subprocess.STDOUT, env=env, close_fds=True,
                                   umask=0o022)
        position, shown = 0, None
        while process.poll() is None:
            time.sleep(1)
            if progress:
                position, step = child_step(installer_log, position)
                if step and step != shown:
                    shown = step
                    msg_info(fit(f'{progress} {step}'))
        if process.returncode:
            log(f'  exit {process.returncode}')
            detail, lines = installer_failure(installer_log)
            _run.update(failed_log=installer_log, failed_lines=lines)
            if detail:
                log(f'  installer error: {detail}')
                raise RuntimeError(f"{translate('The new image could not be installed:')} {detail}")
            raise RuntimeError(translate('The new image could not be installed'))


def commit(root, journal, state):
    if state['phase'] not in ('health-passed', 'committing'):
        raise ValueError(translate('The new container did not pass validation'))
    current = instances.read(root, state['vmid'])
    if current.get('last_transaction') == state['id']:
        checkpoint(journal, state, 'committed')
        return
    if current.get('transaction_id') != state['id'] or current.get('pending_transaction') != str(journal):
        raise ValueError(translate('The record no longer belongs to this operation'))
    config = owned(state['vmid'], state['record']['installation_id'])
    if sha(config) != state.get('validated_config_sha256'):
        raise ValueError(translate('The configuration changed after the new container was validated'))
    host_mounts.verify_sources(state.get('candidate_host_sources', {}))
    gpu_devices.verify(state.get('desired_gpu_devices', {}))
    gpu_devices.check(config, state['candidate_contract']['deployment'])
    checkpoint(journal, state, 'committing')
    result = copy.deepcopy(state['candidate_contract'])
    result.update(status='installed', completed_at=instances.now(),
                  last_transaction=state['id'],
                  observed=instances.observe(state['vmid'], result['installation_id'],
                                             state['archive'], state['registry_digest']))
    host_mounts.verify_sources(state.get('candidate_host_sources', {}))
    host_mounts.verify_observation(state.get('candidate_host_sources', {}), result['observed'])
    gpu_devices.verify_observation(state.get('desired_gpu_devices', {}), result['observed'])
    result.pop('pending_transaction', None)
    result.pop('transaction_id', None)
    instances.write(instances.location(root, state['vmid']), result)
    checkpoint(journal, state, 'committed')


def restore_firewall(vmid, state):
    """pct destroy removes the CT firewall rules; the recreated CT gets them back."""
    saved = state.get('firewall_config')
    if saved is not None:
        Path(f'/etc/pve/firewall/{vmid}.fw').write_text(saved)


def original_description(state):
    """Return the user's original Notes, including text added outside ProxMenux."""
    description = state.get('original_description')
    if description is None:
        # Journals created before this safeguard only have pct's escaped config.
        description = unquote(parse_config(state['before_config'].encode()).get('description', ''))
    if not isinstance(description, str) or instances.identity(
            json.dumps({'description': description}).encode()) != state['record']['installation_id']:
        raise ValueError(translate('The container identity changed; nothing was adopted'))
    return description


def restore_description(vmid, state):
    run('pct', 'set', str(vmid), '--description', original_description(state))


def release_stage(state):
    """After a commit the holder CT only keeps its own rootfs: every parked
    volume went back to the application. Anything still attached keeps it."""
    stage = state.get('stage')
    if not stage:
        return
    try:
        config = owned(stage, 'proxmenux-transaction=' + state['id'])
    except (ValueError, RuntimeError, subprocess.CalledProcessError):
        return
    if mounts(config) or any(re.fullmatch(r'unused[0-9]+', key) for key in parse_config(config)):
        return
    run('pct', 'destroy', str(stage))


def gib(size):
    return f'{size / 1024**3:.1f} GB'


def backup_size(vmid):
    """Bytes in use on the volumes that vzdump includes: the rootfs and the
    mount points with backup enabled."""
    cfg = parse_config(run('pct', 'config', str(vmid)))
    included = {'rootfs'} | {key for key, value in cfg.items()
                             if re.fullmatch(r'mp[0-9]+', key) and 'backup=1' in value.split(',')}
    units = {'': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4, 'P': 1024**5}
    total = 0
    for line in run('pct', 'df', str(vmid)).decode().splitlines()[1:]:
        fields = line.split()
        if not fields or fields[0] not in included:
            continue
        match = re.fullmatch(r'([0-9.]+)([KMGTP]?)', fields[3]) if len(fields) > 3 else None
        if not match:
            raise ValueError(translate('The disk usage of the container could not be read'))
        total += int(float(match.group(1)) * units[match.group(2)])
    return total


def require_backup_space(directory, vmids):
    """The data in use on the backed-up volumes, plus a margin, must fit in
    `directory`; data that is already compressed does not shrink."""
    needed = int(sum(backup_size(vmid) for vmid in vmids) * 1.1) + 1024**3
    free = shutil.disk_usage(directory).free
    if free < needed:
        raise ValueError(f"{translate('Not enough free space for the backup')} "
                         f"({translate('needed')}: {gib(needed)}, {translate('free')}: {gib(free)}, {directory})")


def prune_backups(root, vmid):
    """The backups of closed operations are removed once the container works
    with its new image; their journal and log stay."""
    base = instances.location(root, vmid).parent / 'transactions'
    for directory in base.iterdir():
        if directory.is_symlink() or not directory.is_dir():
            continue
        try:
            phase = json.loads((directory / 'transaction.json').read_text()).get('phase')
        except (OSError, ValueError):
            continue
        if phase not in ('committed', 'rolled-back'):
            continue
        for backup in (directory / 'backup').glob('vzdump-lxc-*'):
            if backup.is_file() and not backup.is_symlink():
                backup.unlink()


def check_archive(archive):
    """Full integrity check of the image; its per-blob report goes to the log."""
    report = io.StringIO()
    try:
        with contextlib.redirect_stdout(report), contextlib.redirect_stderr(report):
            verify_archive(archive)
    except RuntimeError as exc:
        log(f'integrity check: {exc}')
        raise RuntimeError(translate('The image did not pass the integrity check')) from exc
    finally:
        log_output(report.getvalue())


def apply(root, vmid, archive, operation, proposal=None, registry_digest=None, interrupt_after=None,
          backup_compression='zstd', acknowledge_external_data=False, coordinated=None, progress=None,
          keep_backup=None):
    # A coordinated member is shown by its stack; progress prefixes the installer steps.
    show = not coordinated
    update = operation == 'update'
    if backup_compression not in ('zstd', 'gzip'):
        raise ValueError(translate('Unsupported backup compression'))
    if coordinated and backup_compression != 'zstd':
        raise ValueError(translate('Coordinated backups require zstd'))
    if show:
        msg_info(translate('Preparing the update...') if update else translate('Preparing the recreation...'))
    record = instances.read(root, vmid)
    if coordinated and any(coordinated.get(flag) for flag in
                           ('nextcloud_replay', 'paperless_replay', 'tandoor_replay', 'immich_replay')):
        import oci_stack_replay
        project = (oci_stack_replay.immich_record if coordinated.get('immich_replay')
                   else oci_stack_replay.tandoor_record if coordinated.get('tandoor_replay')
                   else oci_stack_replay.paperless_record if coordinated.get('paperless_replay')
                   else oci_stack_replay.nextcloud_record)
        record = project(record)
        expected = coordinated['effective_record']
        if any(record.get(key) != expected.get(key) for key in
               ('vmid', 'installation_id', 'template', 'deployment')):
            raise ValueError(translate('The translated recipe changed during the preparation'))
        if 'stack' in expected:
            record['stack'] = copy.deepcopy(expected['stack'])
    candidate = candidate_contract(record, operation, proposal)
    before = run('pct', 'config', str(vmid))
    cfg, actual, mac = preflight(record, candidate, before, coordinated)
    description = original_description({'record': record, 'before_config': before.decode()})
    original_sources, desired_sources = freeze_host_sources(record, candidate, acknowledge_external_data)
    original_gpu = gpu_devices.planned(record['deployment'])
    desired_gpu = gpu_devices.planned(candidate['deployment'])
    resources = json.loads(run('pvesh', 'get', '/cluster/ha/resources', '--output-format', 'json'))
    if any(r.get('sid') == f'ct:{vmid}' for r in resources):
        raise ValueError(translate('High availability resources are not supported by this profile'))
    archive = archive.resolve(strict=True)
    check_archive(archive)
    image = image_from_archive(str(archive))
    previous = record['observed']['image']
    if image['architecture'] != previous['architecture'] or image['os'] != 'linux':
        raise ValueError(translate('Incompatible image platform'))
    if not coordinated and operation == 'update' and image['manifest_digest'] == previous['manifest_digest']:
        msg_ok(translate('The image is already up to date; nothing was changed.'))
        return None
    required = {m['container_path'] for m in candidate['deployment'].get('mounts', [])}
    if any(not any(p == target or p.startswith(target.rstrip('/') + '/') for target in required)
           for p in (image['defaults'].get('Volumes') or {})):
        raise ValueError(translate('The new image requires additional persistent paths; use Recreate'))
    directory = instances.location(root, vmid).parent / 'transactions' / uuid.uuid4().hex
    private_directory(directory)
    open_log(directory)
    if not coordinated:
        require_backup_space(directory, [vmid])
    journal = directory / 'transaction.json'
    runtime_deployment = copy.deepcopy(candidate['deployment'])
    runtime_deployment['network']['mac_address'] = mac
    runtime_deployment.update(onboot=False, start_after_create=not bool(coordinated),
                              transaction_reuse_mounts=[dict(m, container_path=p)
                                  for p, m in actual.items() if p in required and not m['volume'].startswith('/')])
    state = {'schema_version': 1, 'id': directory.name, 'vmid': vmid, 'operation': operation,
             'record': record, 'candidate_contract': candidate, 'before_config': before.decode(),
             'original_description': description,
             'archive': str(archive), 'archive_sha256': filehash(archive),
             'registry_digest': registry_digest or image['manifest_digest'],
             'runtime_template': candidate['template'], 'runtime_deployment': runtime_deployment,
             'backup_compression': backup_compression,
             'original_host_sources': original_sources, 'desired_host_sources': desired_sources,
             'external_data_acknowledged': acknowledge_external_data,
             'original_gpu_devices': original_gpu, 'desired_gpu_devices': desired_gpu,
             'was_running': run('pct', 'status', str(vmid)).strip() == b'status: running'}
    state['kept_config'] = {key: cfg[key] for key in KEPT_AS_IS if key in cfg}
    if not coordinated and state['kept_config']:
        # Applied by the installer before the new container starts, so the
        # application has its LAN leg from the first second.
        state['runtime_deployment']['kept_proxmox_settings'] = state['kept_config']
    if coordinated:
        state['coordinated'] = coordinated
        state['preserved_stack_config'] = {key: cfg[key] for key in ('net1', 'startup', 'hookscript') if key in cfg}
        if operation == 'update':
            state['preserved_stack_config'].update({key: cfg[key] for key in
                ('net0', 'features', 'cmode', 'console', 'tty', 'cpuunits', 'tags') if key in cfg})
    checkpoint(journal, state, 'prepared')
    pending = copy.deepcopy(record)
    pending.update(status='updating', pending_transaction=str(journal), transaction_id=state['id'])
    instances.write(instances.location(root, vmid), pending)
    log(f'journal: {journal}')
    if show:
        _run['journal'] = journal
    host_mounts.verify_sources(original_sources)
    host_mounts.verify_sources(desired_sources)
    gpu_devices.verify(original_gpu)
    gpu_devices.verify(desired_gpu)
    if show:
        msg_ok(translate('Update prepared') if update else translate('Recreation prepared'))
        msg_info(translate('Stopping the container...'))
    stop(vmid)
    if show:
        msg_ok(translate('Container stopped'))
        msg_info(translate('Creating a backup of the container...'))
    checkpoint(journal, state, 'backing-up')
    if coordinated:
        backup = coordinated['backup']
        if filehash(backup['archive']) != backup['sha256']:
            raise ValueError(translate('The coordinated backup was modified'))
        run('zstd', '-t', backup['archive'])
        state.update(backup=backup['archive'], backup_sha256=backup['sha256'])
    else:
        backup_dir = directory / 'backup'
        private_directory(backup_dir)
        backup = verified_backup(vmid, backup_dir, backup_compression,
                                 translate('The backup could not be identified; the image is not replaced'), show)
        state.update(backup=str(backup), backup_sha256=filehash(backup))
    checkpoint(journal, state, 'backup-ready')
    if show:
        msg_ok(translate('Backup created'))
        msg_info(translate('Moving the data volumes aside...'))
    stage = int(run('pvesh', 'get', '/cluster/nextid').strip())
    state['stage'] = stage
    state['runtime_deployment']['transaction_source_vmid'] = stage
    checkpoint(journal, state, 'creating-stage')
    run('pct', 'create', str(stage), str(archive), '--rootfs',
        f"{record['deployment']['rootfs']['storage']}:{record['deployment']['rootfs']['size_gb']}",
        '--hostname', 'oci-data-holder', '--ostype', 'unmanaged', '--unprivileged', '1',
        '--memory', '128', '--cores', '1', '--onboot', '0',
        '--description', 'proxmenux-transaction=' + state['id'])
    checkpoint(journal, state, 'parking-data')
    for mount in actual.values():
        owned(vmid, record['installation_id'])
        host_mounts.verify_sources(original_sources)
        if mount['volume'].startswith('/'):
            run('pct', 'set', str(vmid), '--delete', mount['key'])
        else:
            owned(stage, 'proxmenux-transaction=' + state['id'])
            run('pct', 'move-volume', str(vmid), mount['key'], '--target-vmid', str(stage), '--target-volume', mount['key'])
    checkpoint(journal, state, 'data-parked')
    if show:
        msg_ok(translate('Data volumes protected'))
    if interrupt_after == 'data-parked':
        raise RuntimeError(translate('Lab interruption after protecting the data'))
    if show:
        msg_info(translate('Installing the new image...') if update else translate('Recreating the container...'))
    current = owned(vmid, record['installation_id'])
    expected = b''.join(line for line in before.splitlines(keepends=True)
                        if not re.match(rb'mp[0-9]+: ', line))
    if mounts(current) or current != expected:
        raise ValueError(translate('A concurrent change was detected; the container is not removed'))
    host_mounts.verify_sources(original_sources)
    gpu_devices.verify(original_gpu)
    gpu_devices.verify(desired_gpu)
    firewall = Path(f'/etc/pve/firewall/{vmid}.fw')
    state['firewall_config'] = firewall.read_text() if firewall.exists() else None
    checkpoint(journal, state, 'replacing-root')
    run('pct', 'destroy', str(vmid))
    checkpoint(journal, state, 'installing-candidate')
    if show:
        progress = translate('Installing the new image:') if update else translate('Recreating the container:')
    install_candidate(root, journal, state, progress)
    restore_description(vmid, state)
    restore_firewall(vmid, state)
    if coordinated:
        for key, value in state['preserved_stack_config'].items():
            run('pct', 'set', str(vmid), '--' + key, value)
        check_runtime_mounts(run('pct', 'config', str(vmid)), candidate['deployment'])
        gpu_devices.check(run('pct', 'config', str(vmid)), candidate['deployment'])
        state['staged_config_sha256'] = sha(owned(vmid, record['installation_id']))
        checkpoint(journal, state, 'candidate-installed')
        return journal
    gpu_devices.validate_runtime(vmid, candidate['deployment'])
    state['candidate_host_sources'] = candidate_host_sources(journal, state)
    checkpoint(journal, state, 'candidate-installed')
    msg_ok(translate('New image installed') if update else translate('Container recreated'))
    if interrupt_after == 'candidate-installed':
        raise RuntimeError(translate('Lab interruption after installing the new container'))
    msg_info(translate('Saving the new configuration...'))
    check_runtime_mounts(run('pct', 'config', str(vmid)), candidate['deployment'])
    gpu_devices.check(run('pct', 'config', str(vmid)), candidate['deployment'])
    if not state['was_running']:
        stop(vmid)
    run('pct', 'set', str(vmid), '--onboot', '1' if candidate['deployment']['onboot'] else '0')
    state['validated_config_sha256'] = sha(owned(vmid, record['installation_id']))
    checkpoint(journal, state, 'health-passed')
    commit(root, journal, state)
    cleanup_error = None
    freed = 0
    try:
        release_stage(state)
        if keep_backup and state.get('backup'):
            import oci_keep_backup
            kept = oci_keep_backup.keep(state['backup'], keep_backup)
            if kept:
                msg_ok(f"{translate('Backup kept in')} {keep_backup}: {Path(kept).name}")
        prune_backups(root, vmid)
        for path, size in image_cache.prune(root, lock=False):
            log(f'removed unused image archive: {path}')
            freed += size
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        cleanup_error = exc
        log(f'cleanup: {exc}')
    msg_ok(translate('Update completed. Data kept.') if update
           else translate('Recreation completed. Data kept.'))
    if freed:
        msg_ok(f"{translate('Unused images removed from the cache:')} {gib(freed)}")
    if cleanup_error is not None:
        msg_warn(f"{translate('The final cleanup did not complete:')} {cleanup_error}")
    return journal


def remove_empty_format_directories(rootfs, deployment):
    """Remove only empty, unmapped mkfs lost+found on restored managed disks."""
    root = Path(rootfs)
    for mount in deployment.get('mounts', []):
        if mount.get('type') != 'managed-volume' or not mount.get('backup'):
            continue
        current = root
        for part in Path(mount['container_path']).parts[1:]:
            if part in ('.', '..'):
                raise ValueError(translate('Invalid restored volume path'))
            current /= part
            if current.is_symlink():
                raise ValueError(translate('Symbolic link in a restored volume path'))
        candidate = current / 'lost+found'
        if not candidate.exists() or candidate.is_symlink():
            continue
        info = candidate.lstat()
        if (stat.S_ISDIR(info.st_mode) and info.st_ino == 11
                and info.st_uid == 0 and info.st_gid == 0
                and stat.S_IMODE(info.st_mode) == 0o700):
            if not any(candidate.iterdir()):
                candidate.rmdir()


def cleanup_restored_format_dirs(vmid, deployment, installation_id):
    owned(vmid, installation_id)
    run('pct', 'mount', str(vmid))
    try:
        remove_empty_format_directories(Path('/var/lib/lxc') / str(vmid) / 'rootfs', deployment)
    finally:
        run('pct', 'unmount', str(vmid))


def complete_recovery(root, journal, state):
    vmid = state['vmid']
    show = not state.get('coordinated')
    if show:
        msg_info(translate('Checking the restored installation...'))
    host_mounts.verify_sources(state.get('original_host_sources', {}))
    gpu_devices.verify(state.get('original_gpu_devices', {}))
    config = owned(vmid, state['record']['installation_id'])
    expected = state['restore_config_sha256']
    if sha(config) != expected:
        raise ValueError(translate('The configuration changed after the backup was restored; the recovery is not confirmed'))
    cleanup_restored_format_dirs(vmid, state['record']['deployment'], state['record']['installation_id'])
    runtime_settings.restore(state['record']['deployment'], vmid)
    check_runtime_mounts(config, state['record']['deployment'])
    gpu_devices.check(config, state['record']['deployment'])
    if show:
        msg_ok(translate('Restored installation checked'))
    if not state.get('coordinated') and run('pct', 'status', str(vmid)).strip() == b'status: stopped':
        msg_info(translate('Starting the container...'))
        run('pct', 'start', str(vmid))
        msg_ok(translate('Container started'))
    if not state.get('coordinated'):
        msg_info(translate('Waiting for the application to respond...'))
        url = healthcheck(vmid, state['record']['template'])
        gpu_devices.validate_runtime(vmid, state['record']['deployment'])
        msg_ok(f"{translate('Application responding:')} {url}")
    if not state['was_running']:
        stop(vmid)
    restored = copy.deepcopy(state['record'])
    restored['observed'] = instances.observe(vmid, restored['installation_id'],
        restored['observed']['archive_path'], restored['observed']['resolved_registry_digest'],
        restored['observed']['image'])
    host_mounts.verify_sources(state.get('original_host_sources', {}))
    host_mounts.verify_observation(state.get('original_host_sources', {}), restored['observed'])
    gpu_devices.verify_observation(state.get('original_gpu_devices', {}), restored['observed'])
    restored['recovered_transaction'] = state['id']
    instances.write(instances.location(root, vmid), restored)
    checkpoint(journal, state, 'rolled-back')
    if show:
        msg_ok(translate('Recovery completed. The displaced disks and the backup are kept; nothing was deleted automatically.'))
        if state.get('original_host_sources') or state.get('desired_host_sources'):
            msg_info2(translate('Shared host files are kept as they are; the backup does not restore their content.'))


def recover(root, journal):
    state = json.loads(journal.read_text())
    vmid = state['vmid']
    show = not state.get('coordinated')
    if show:
        msg_info(translate('Checking the interrupted operation...'))
    record = instances.read(root, vmid)
    if state['phase'] in TERMINAL or record.get('last_transaction') == state['id']:
        raise ValueError(translate('The operation already finished; it is not restored automatically'))
    if (record.get('transaction_id') != state['id'] or record.get('pending_transaction') != str(journal)
            or record['installation_id'] != state['record']['installation_id']):
        raise ValueError(translate('The record does not belong to this operation'))
    host_mounts.verify_sources(state.get('original_host_sources', {}))
    gpu_devices.verify(state.get('original_gpu_devices', {}))
    current_path = Path(f'/etc/pve/lxc/{vmid}.conf')
    resources = json.loads(run('pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'))
    if not isinstance(resources, list):
        raise ValueError(translate('Incomplete Proxmox inventory; recovery blocked'))
    for resource in resources:
        if not isinstance(resource, dict) or resource.get('type') not in ('lxc', 'qemu') or not isinstance(resource.get('vmid'), int):
            raise ValueError(translate('Unexpected Proxmox inventory; recovery blocked'))
        if resource['vmid'] == vmid and (resource['type'] != 'lxc' or not current_path.exists()
                or resource.get('node') != socket.gethostname().split('.', 1)[0]):
            raise ValueError(translate('The VMID was reused or the container is on another node; it is not overwritten'))
    if current_path.exists():
        owned(vmid, record['installation_id'])
    backup = state.get('backup')
    # A failure before the container was changed (while backing it up or
    # creating the temporary container) leaves it exactly as it was.
    untouched = current_path.exists() and run('pct', 'config', str(vmid)).decode() == state['before_config']
    if not backup or untouched:
        if not untouched:
            raise ValueError(translate('There is no verified backup; a modified container is not touched'))
        release_stage(state)
        if state['was_running'] and run('pct', 'status', str(vmid)).strip() == b'status: stopped':
            run('pct', 'start', str(vmid))
        instances.write(instances.location(root, vmid), state['record'])
        checkpoint(journal, state, 'rolled-back')
        if show:
            msg_ok(translate('Recovery completed. The container had not been modified yet.'))
        return
    if filehash(backup) != state['backup_sha256']:
        raise ValueError(translate('The backup was altered; recovery blocked'))
    run('gzip' if state.get('backup_compression') == 'gzip' else 'zstd', '-t', backup)
    if show:
        msg_ok(translate('Backup of the previous installation verified'))
    if state['phase'] == 'checking-recovery' and state.get('restore_config_sha256'):
        complete_recovery(root, journal, state)
        return
    if show:
        msg_info(translate('Restoring the previous backup...'))
    stage = state.get('stage')
    if stage and Path(f'/etc/pve/lxc/{stage}.conf').exists():
        held = owned(stage, 'proxmenux-transaction=' + state['id'])
        stop(stage)
    else:
        held = None
    checkpoint(journal, state, 'recovering')
    if current_path.exists():
        stop(vmid)
        current = owned(vmid, record['installation_id'])
        gpu_devices.check_recovery_entries(current, state)
        if any(re.fullmatch(r'unused[0-9]+', k) for k in parse_config(current)):
            raise ValueError(translate('There are extra disks or bind mounts outside the journal; the rootfs is not replaced'))
        known_binds = {(m['source'], m['container_path'])
                       for plan in (state['record']['deployment'], state['candidate_contract']['deployment'])
                       for m in plan.get('mounts', []) if m['type'] == 'host-bind'}
        if any(m['volume'].startswith('/') and (m['volume'], target) not in known_binds
               for target, m in mounts(current).items()):
            raise ValueError(translate('A host mount is not part of the journal; recovery blocked'))
        if any(not m['volume'].startswith('/') for m in mounts(current).values()) and held is None:
            raise ValueError(translate('There is no temporary container of this operation to keep the current disks'))
        used = {m['key'] for m in mounts(held or b'').values()}
        for mount in mounts(current).values():
            if mount['volume'].startswith('/'):
                run('pct', 'set', str(vmid), '--delete', mount['key'])
                continue
            index = next(i for i in range(256) if f'mp{i}' not in used)
            key = f'mp{index}'
            owned(stage, 'proxmenux-transaction=' + state['id'])
            # Unique inert targets make repeated recovery safe even when both the
            # failed candidate and a restored backup contain the same app paths.
            retained_target = '/transaction-retained/' + uuid.uuid4().hex
            run('pct', 'set', str(vmid), '--' + mount['key'],
                f"{mount['volume']},mp={retained_target},backup=1")
            run('pct', 'move-volume', str(vmid), mount['key'], '--target-vmid', str(stage), '--target-volume', key)
            used.add(key)
    checkpoint(journal, state, 'restoring-backup')
    host_mounts.verify_sources(state.get('original_host_sources', {}))
    run('pct', 'restore', str(vmid), backup, '--force', '1', '--storage',
        state['record']['deployment']['rootfs']['storage'])
    state['restore_config_sha256'] = sha(owned(vmid, state['record']['installation_id']))
    checkpoint(journal, state, 'checking-recovery')
    if show:
        msg_ok(translate('Previous installation restored'))
    complete_recovery(root, journal, state)


def phase_label(phase):
    labels = {
        'prepared': translate('Prepared; the container was not modified yet'),
        'backing-up': translate('Creating the backup'),
        'backup-ready': translate('Backup created'),
        'creating-stage': translate('Creating the temporary data container'),
        'parking-data': translate('Moving the data volumes aside'),
        'data-parked': translate('Data volumes protected'),
        'replacing-root': translate('Removing the previous container'),
        'installing-candidate': translate('Installing the new image'),
        'candidate-installed': translate('New image installed, not verified yet'),
        'health-passed': translate('New image verified, not saved yet'),
        'committing': translate('Saving the new configuration'),
        'committed': translate('Completed'),
        'recovering': translate('Recovering the previous installation'),
        'restoring-backup': translate('Restoring the backup'),
        'checking-recovery': translate('Checking the restored installation'),
        'rolled-back': translate('Previous installation restored'),
    }
    return f'{labels[phase]} ({phase})' if phase in labels else str(phase)


def show_status(path, state):
    operations = {'update': translate('Update'), 'recreate': translate('Recreate')}
    msg_info2(f"{translate('Interrupted operation:')} {operations.get(state.get('operation'), state.get('operation'))} (CT {state['vmid']})")
    msg_info2(f"{translate('Stopped at:')} {phase_label(state.get('phase'))}")
    if state.get('stage'):
        msg_info2(f"{translate('Temporary data container:')} CT {state['stage']}")
    if state.get('backup'):
        msg_info2(f"{translate('Backup:')} {state['backup']}")
    log_path = path.parent / 'transaction.log'
    msg_info2(f"{translate('Transaction log:')} {log_path if log_path.exists() else path.parent}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=instances.ROOT)
    parser.add_argument('action', choices=['apply', 'status', 'recover', 'commit', 'authorize-candidate', 'pin-host-source'])
    parser.add_argument('vmid', type=int)
    parser.add_argument('--operation', choices=['update', 'recreate'], default='update')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--proposal', type=Path)
    parser.add_argument('--registry-digest')
    parser.add_argument('--journal', type=Path)
    parser.add_argument('--template', type=Path)
    parser.add_argument('--deployment', type=Path)
    parser.add_argument('--source')
    parser.add_argument('--acknowledge-external-data', action='store_true')
    parser.add_argument('--interrupt-after', choices=['data-parked', 'candidate-installed'])
    parser.add_argument('--backup-compression', choices=['zstd', 'gzip'], default='zstd')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    # The shared installer reads the output of these two actions: their messages go to stderr.
    output = sys.stderr if args.action in ('authorize-candidate', 'pin-host-source') else sys.stdout
    try:
        if args.action == 'authorize-candidate':
            print(authorize(args.root, args.vmid, args.journal, args.template, args.deployment))
            return 0
        if args.action == 'pin-host-source':
            pin_host_source(args.root, args.vmid, args.journal, args.source)
            return 0
        with instances.locked(args.root):
            if args.action == 'apply':
                if args.archive is None:
                    raise ValueError(translate('apply requires the OCI archive of the resolved image'))
                proposal = json.loads(args.proposal.read_text()) if args.proposal else None
                apply(args.root, args.vmid, args.archive, args.operation, proposal,
                      args.registry_digest, args.interrupt_after, args.backup_compression,
                      args.acknowledge_external_data)
            else:
                path = args.journal or Path(instances.read(args.root, args.vmid)['pending_transaction'])
                state = json.loads(path.read_text())
                if state['vmid'] != args.vmid:
                    raise ValueError(translate('The journal belongs to another VMID'))
                if args.action == 'status':
                    show_status(path, state)
                elif args.action == 'recover':
                    if state.get('coordinated'):
                        raise ValueError(translate('This container belongs to a stack; recover the whole stack'))
                    open_log(path.parent)
                    _run['journal'] = path
                    recover(args.root, path)
                else:
                    if state.get('coordinated'):
                        raise ValueError(translate('This container belongs to a stack; publish the whole stack'))
                    commit(args.root, path, state)
        return 0
    except BlockingIOError:
        with contextlib.redirect_stdout(output):
            msg_error(translate('Another OCI operation is using the registry. This operation was not started.'))
        return 1
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        with contextlib.redirect_stdout(output):
            report_error(error, f'oci-{args.action}-{args.vmid}')
            journal = pending_journal()
            if journal and (args.action == 'recover' or not recover_untouched(args.root, journal)):
                recovery_hint(after_recovery=args.action == 'recover')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
