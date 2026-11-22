"""Opt-in, local ZFS recovery points; ordinary vzdump remains the fallback.

All members stop before one atomic snapshot set. Recovery clones are promoted
so destroying the original CT cannot destroy the recovery point. Restore still
uses pct's native configuration restore, with existing cloned volumes and a
small metadata archive. These points are not portable/offsite backups.
"""
import io
import functools
import time
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import uuid

import oci_instances as instances
from oci_installation_state import parse_config, private_directory

KIND = 'proxmenux.zfs-recovery.v1'
SUFFIX = '.zfs.tar'
TAG = 'org.proxmenux:recovery'
MANIFEST = './etc/vzdump/proxmenux-zfs.json'
PROPERTIES = ('acltype', 'aclmode', 'aclinherit', 'xattr', 'recordsize', 'compression',
              'atime', 'relatime', 'exec', 'setuid', 'devices', 'refquota', 'quota', 'dnodesize')


def api():
    import oci_instance_transaction
    return oci_instance_transaction


def run(*args):
    return api().run(*args).decode().strip()


def enabled():
    return os.environ.get('PROXMENUX_OCI_RECOVERY', 'backup') == 'auto' and shutil.which('zfs') is not None


def is_fast(path):
    return str(path).endswith(SUFFIX)


def properties(dataset, names):
    text = run('zfs', 'get', '-Hp', '-o', 'property,value', ','.join(names), dataset)
    values = dict(line.split('\t', 1) for line in text.splitlines())
    if set(values) != set(names):
        raise ValueError('Incomplete ZFS recovery properties')
    return values


def exists(dataset):
    import subprocess
    result = subprocess.run(['zfs', 'list', '-H', '-o', 'name', dataset], capture_output=True, timeout=30)
    if result.returncode == 0:
        return True
    if b'dataset does not exist' in result.stderr:
        return False
    raise RuntimeError('Could not check ZFS recovery dataset: ' + result.stderr.decode(errors='replace'))


def tagged(dataset, token, guid=None):
    p = properties(dataset, (TAG, 'guid'))
    if p[TAG] != token or (guid and p['guid'] != guid):
        raise ValueError('ZFS recovery identity changed; nothing is removed')
    return p['guid']


def plan(records):
    """Read-only eligibility. Any unsupported layout retains conventional backup."""
    try:
        if not records or not enabled():
            return None
        tx = api()
        storages, volumes, configs, raw_configs = {}, [], {}, {}
        jobs = json.loads(run('pvesh', 'get', '/cluster/replication', '--output-format', 'json'))
        if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
            return None
        if any(any(str(j.get('guest', '')) == str(v) or str(j.get('id', '')).startswith(f'{v}-')
                   for v in records) for j in jobs):
            return None
        for vmid, record in records.items():
            config = tx.owned(vmid, record['installation_id'])
            cfg = parse_config(config)
            raw = Path(f'/etc/pve/lxc/{vmid}.conf').read_bytes()
            if (b'\n[' in raw or any(re.fullmatch(r'unused\d+', key) for key in cfg)
                    or cfg.get('lock') or cfg.get('template') == '1'):
                return None
            if tx.owned(vmid, record['installation_id']) != config:
                return None
            configs[vmid], raw_configs[vmid] = config.decode(), raw.decode()
            for key, value in cfg.items():
                if key != 'rootfs' and not re.fullmatch(r'mp\d+', key):
                    continue
                volume = value.split(',', 1)[0]
                if volume.startswith('/') and key != 'rootfs':
                    continue  # Same acknowledged external-data boundary as vzdump.
                fields = dict(p.split('=', 1) for p in value.split(',')[1:] if '=' in p)
                if fields.get('backup', '1') != '1' or fields.get('ro', '0') != '0':
                    return None
                match = re.fullmatch(r'([A-Za-z0-9._-]+):(subvol-' + str(vmid) + r'-[A-Za-z0-9._-]+)', volume)
                if not match:
                    return None
                storage, name = match.groups()
                if storage not in storages:
                    storages[storage] = json.loads(run('pvesh', 'get', '/storage/' + storage, '--output-format', 'json'))
                info = storages[storage]
                if info.get('type') != 'zfspool' or info.get('shared'):
                    return None
                dataset = info['pool'] + '/' + name
                if not valid_dataset(dataset):
                    return None
                p = properties(dataset, ('guid', 'origin', 'encryption', 'readonly', 'mountpoint', *PROPERTIES))
                if p['origin'] != '-' or p['encryption'] != 'off' or p['readonly'] != 'off':
                    return None
                if run('zfs', 'list', '-H', '-r', '-t', 'snapshot', '-o', 'name', dataset):
                    return None
                if run('zfs', 'list', '-H', '-r', '-o', 'name', dataset).splitlines() != [dataset]:
                    return None
                native_path = run('pvesm', 'path', volume)
                parent_path = properties(info['pool'], ('mountpoint',))['mountpoint']
                if p['mountpoint'] != native_path or parent_path.rstrip('/') + '/' + name != native_path:
                    return None
                volumes.append({'vmid': vmid, 'key': key, 'source': dataset, 'source_guid': p['guid'],
                                'storage': storage, 'pool': info['pool'], 'options': value.split(',', 1)[1] if ',' in value else '',
                                'properties': {k: p[k] for k in PROPERTIES}})
            if not any(v['vmid'] == vmid and v['key'] == 'rootfs' for v in volumes):
                return None
        if len({v['source_guid'] for v in volumes}) != len(volumes):
            return None
        if len({v['pool'].split('/')[0] for v in volumes}) != 1:
            return None
        pool = volumes[0]['pool'].split('/')[0]
        if run('zpool', 'list', '-H', '-o', 'health', pool) != 'ONLINE':
            return None
        check_space(volumes)
        return {'volumes': volumes, 'configs': configs, 'raw_configs': raw_configs}
    except Exception:
        # Eligibility is read-only; any unsupported backend falls back to vzdump.
        return None


def check_space(volumes):
    """Reserve a complete rewrite of retained data, plus 1 GiB per dataset pool.

    This is a preflight bound, not a promise about indefinitely retained points.
    Check again after stopping and immediately before creating snapshots.
    """
    required = {}
    for volume in volumes:
        values = properties(volume['source'], ('referenced', 'logicalreferenced'))
        size = max(int(values['referenced']), int(values['logicalreferenced']))
        required[volume['pool']] = required.get(volume['pool'], 1024**3) + int(size * 1.1)
    physical = {}
    for pool, needed in required.items():
        if int(properties(pool, ('available',))['available']) < needed:
            raise ValueError('Insufficient available space for ZFS recovery')
        physical_pool = pool.split('/', 1)[0]
        physical[physical_pool] = physical.get(physical_pool, 0) + needed
    # Distinct storage datasets can each report the same shared free pool bytes.
    # Check their combined reserve too, rather than spending that space twice.
    for pool, needed in physical.items():
        if int(properties(pool, ('available',))['available']) < needed:
            raise ValueError('Insufficient shared pool space for ZFS recovery')


def backup_name(volume, token):
    # Deliberately outside PVE's subvol-<vmid>-* managed-volume namespace.
    return f"{volume['pool']}/proxmenux-oci-recovery-{token}-{volume['vmid']}-{volume['key']}"


def valid_backup(volume, token):
    # Continue to recover/clean points created by the initial opt-in prototype.
    legacy = f"{volume['pool']}/subvol-{volume['vmid']}-oci-recovery-{token}-{volume['key']}"
    return volume['backup'] in (backup_name(volume, token), legacy)


def clone_options(volume):
    options = []
    for key, value in volume['properties'].items():
        setting = 'none' if key in ('quota', 'refquota') and value == '0' else value
        options += ['-o', key + '=' + setting]
    return options


def metadata_tar(path, config, firewall=None, manifest=None):
    private_directory(path.parent)
    with path.open('xb') as output:
        path.chmod(0o600)
        with tarfile.open(fileobj=output, mode='w') as tar:
            entries = {'./etc/vzdump/pct.conf': config.encode()}
            if firewall is not None:
                entries['./etc/vzdump/pct.fw'] = firewall.encode()
            if manifest is not None:
                entries[MANIFEST] = json.dumps(manifest, sort_keys=True).encode()
            for name, data in entries.items():
                item = tarfile.TarInfo(name); item.size = len(data); item.mode = 0o600
                tar.addfile(item, io.BytesIO(data))
        output.flush(); os.fsync(output.fileno())


def load(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 4 * 1024**2:
        raise ValueError('Unsafe ZFS recovery metadata')
    with tarfile.open(path) as tar:
        members = tar.getmembers()
        names = [m.name.removeprefix('./') for m in members]
        allowed = {'etc/vzdump/pct.conf', 'etc/vzdump/pct.fw', MANIFEST.removeprefix('./')}
        if len(set(names)) != len(names) or not set(names) <= allowed or any(not m.isfile() for m in members):
            raise ValueError('Unsafe ZFS recovery metadata')
        if MANIFEST.removeprefix('./') not in names or 'etc/vzdump/pct.conf' not in names:
            raise ValueError('Incomplete ZFS recovery metadata')
        entry = next(m for m in members if m.name.removeprefix('./') == MANIFEST.removeprefix('./'))
        data = json.loads(tar.extractfile(entry).read())
        config_entry = next(m for m in members if m.name.removeprefix('./') == 'etc/vzdump/pct.conf')
        if data.get('config') != tar.extractfile(config_entry).read().decode():
            raise ValueError('ZFS recovery configuration changed')
    validate(data)
    return data


def valid_dataset(name):
    return isinstance(name, str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*(?:/[A-Za-z0-9][A-Za-z0-9_.:-]*)*', name)) and not any(x in ('.', '..') for x in name.split('/'))


def _validate(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid ZFS recovery metadata')
    token, vmid = data.get('token', ''), data.get('vmid')
    if data.get('kind') != KIND or not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{32}', token) or type(vmid) is not int or vmid < 100:
        raise ValueError('Invalid ZFS recovery metadata')
    uuid.UUID(data['installation_id'])
    if not isinstance(data.get('config'), str) or data['installation_id'] not in data['config']:
        raise ValueError('ZFS recovery installation identity missing')
    volumes = data.get('volumes')
    if not isinstance(volumes, list) or not volumes or len({v['key'] for v in volumes}) != len(volumes) or 'rootfs' not in {v['key'] for v in volumes}:
        raise ValueError('Invalid ZFS recovery volumes')
    for v in volumes:
        if (v['vmid'] != vmid or not valid_backup(v, token) or v['snapshot'] != 'oci-' + token
                or not re.fullmatch(r'rootfs|mp\d+', v['key']) or not valid_dataset(v['pool'])
                or not valid_dataset(v['source']) or not v['source'].startswith(v['pool'] + '/subvol-' + str(vmid) + '-')
                or not re.fullmatch(r'[A-Za-z0-9._-]+', v['storage'])
                or set(v['properties']) != set(PROPERTIES)
                or any(not isinstance(x, str) or '\n' in x for x in v['properties'].values())
                or not isinstance(v['options'], str)
                or any(not re.fullmatch(r'[0-9]+', str(v[k])) for k in ('source_guid', 'snapshot_guid', 'backup_guid'))):
            raise ValueError('Invalid ZFS recovery volume identity')


def validate(data):
    try:
        _validate(data)
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ValueError('Invalid ZFS recovery metadata') from error


def verify(path):
    data = load(path)
    for v in data['volumes']:
        tagged(v['backup'], data['token'], v['backup_guid'])
        p = properties(v['backup'] + '@' + v['snapshot'], ('guid', TAG))
        if p['guid'] != v['snapshot_guid'] or p[TAG] != data['token']:
            raise ValueError('ZFS recovery snapshot changed')
        if properties(v['backup'], ('origin',))['origin'] != '-':
            raise ValueError('ZFS recovery clone is not independent')
    return data


def timed(label):
    def decorate(function):
        @functools.wraps(function)
        def measured(*args, **kwargs):
            started = time.monotonic()
            ok = False
            try:
                result = function(*args, **kwargs)
                ok = True
                return result
            finally:
                api().log('ZFS recovery: ' + json.dumps({'phase': label, 'seconds': round(time.monotonic() - started, 3), 'ok': ok}))
        return measured
    return decorate


@timed('protect')
def create(records, directory, prepared):
    """Durably own all planned assets before the atomic stopped snapshot set."""
    tx = api(); directory = Path(directory); private_directory(directory)
    token = uuid.uuid4().hex
    state = {'kind': KIND, 'token': token, 'records': {str(v): r['installation_id'] for v, r in records.items()},
             'volumes': prepared['volumes'], 'released': False}
    path = directory / 'zfs-build.json'
    for v in state['volumes']:
        v.update(backup=backup_name(v, token), snapshot='oci-' + token)
    instances.write(path, state)
    for vmid, record in records.items():
        if tx.owned(vmid, record['installation_id']).decode() != prepared['configs'][vmid]:
            raise ValueError('Container changed before its ZFS recovery point')
        if run('pct', 'status', str(vmid)) != 'status: stopped':
            raise ValueError('Every application member must be stopped before snapshotting')
    for v in state['volumes']:
        if properties(v['source'], ('guid', 'origin')) != {'guid': v['source_guid'], 'origin': '-'}:
            raise ValueError('Source volume changed before snapshotting')
    check_space(state['volumes'])
    for v in state['volumes']:
        if run('zfs', 'list', '-H', '-r', '-t', 'snapshot', '-o', 'name', v['source']):
            raise ValueError('Source acquired snapshots before recovery protection')
    run('zfs', 'snapshot', '-o', TAG + '=' + token,
        *[v['source'] + '@' + v['snapshot'] for v in state['volumes']])
    for v in state['volumes']:
        v['snapshot_guid'] = properties(v['source'] + '@' + v['snapshot'], ('guid',))['guid']
        instances.write(path, state)
        # Exercise every restore property before any promotion/replacement.
        run('zfs', 'clone', *clone_options(v), '-o', 'mountpoint=none', '-o', 'canmount=off',
            '-o', 'com.sun:auto-snapshot=false', '-o', TAG + '=' + token,
            v['source'] + '@' + v['snapshot'], v['backup'])
        v['backup_guid'] = tagged(v['backup'], token)
        instances.write(path, state)
    for v in state['volumes']:
        if run('zfs', 'list', '-H', '-r', '-t', 'snapshot', '-o', 'name', v['source']).splitlines() != [v['source'] + '@' + v['snapshot']]:
            raise ValueError('Source acquired external snapshots before promotion')
        run('zfs', 'promote', v['backup'])
    result = {}
    for vmid, record in records.items():
        target = directory / f'backup-{vmid}' / f'vzdump-lxc-{vmid}-{token}{SUFFIX}'
        data = {'kind': KIND, 'token': token, 'vmid': vmid, 'installation_id': record['installation_id'],
                'volumes': [v for v in state['volumes'] if v['vmid'] == vmid],
                'config': prepared['raw_configs'][vmid]}
        firewall = Path(f'/etc/pve/firewall/{vmid}.fw')
        metadata_tar(target, data['config'], firewall.read_text() if firewall.exists() else None, data)
        verify(target)
        result[vmid] = target
    state['complete'] = True
    instances.write(path, state)
    return result


@timed('restore-clones')
def restore(path, vmid):
    """Return native pct restore arguments using new, unreferenced cloned volumes."""
    data = verify(path)
    if data['vmid'] != vmid:
        raise ValueError('ZFS recovery VMID differs')
    directory = Path(path).parent
    progress = directory / 'zfs-restore.json'
    if progress.is_symlink():
        raise ValueError('Unsafe ZFS restore journal')
    restored = json.loads(progress.read_text()) if progress.exists() else {'token': data['token'], 'attempts': []}
    if restored['token'] != data['token']:
        raise ValueError('ZFS restore belongs to another operation')
    attempt = {'id': uuid.uuid4().hex, 'volumes': {}}
    restored['attempts'].append(attempt)
    instances.write(progress, restored)
    args = []
    for v in data['volumes']:
        name = f"subvol-{vmid}-oci-restored-{data['token']}-{attempt['id']}-{v['key']}"
        ds = v['pool'] + '/' + name
        vol = v['storage'] + ':' + name
        target = attempt['volumes'].setdefault(v['key'], {'dataset': ds, 'guid': None, 'backup': v['backup'], 'snapshot': v['snapshot'], 'vmid': vmid, 'pool': v['pool'], 'storage': v['storage']})
        if target['dataset'] != ds:
            raise ValueError('ZFS restore target changed')
        instances.write(progress, restored)
        if not exists(ds):
            # Inherit the parent mountpoint exactly like native ZFS allocation.
            # A local mountpoint would become stale when PVE moves/renames mpN.
            options = ['-o', 'canmount=on', '-o', TAG + '=' + data['token']]
            options += clone_options(v)
            run('zfs', 'clone', *options, v['backup'] + '@' + v['snapshot'], ds)
        target['guid'] = tagged(ds, data['token'], target['guid'])
        if properties(ds, ('origin',))['origin'] != v['backup'] + '@' + v['snapshot']:
            raise ValueError('ZFS restore origin changed')
        if properties(ds, ('mountpoint',))['mountpoint'] != run('pvesm', 'path', vol):
            raise ValueError('ZFS restore mountpoint differs from native storage path')
        if properties(ds, PROPERTIES) != v['properties']:
            raise ValueError('ZFS restore properties changed')
        instances.write(progress, restored)
        args += ['--' + v['key'], vol + (',' + v['options'] if v['options'] else '')]
    clean = directory / 'zfs-restore-metadata.tar'
    # Recreate from the already verified archive; never trust a stale restore tar.
    if clean.is_symlink():
        raise ValueError('Unsafe ZFS restore metadata')
    if clean.exists():
        clean.unlink()
    with tarfile.open(path) as original:
        fw = next((m for m in original.getmembers() if m.name.removeprefix('./') == 'etc/vzdump/pct.fw'), None)
        firewall = original.extractfile(fw).read().decode() if fw else None
    metadata_tar(clean, data['config'], firewall)
    managed = {v['key'] for v in data['volumes']}
    for key, value in parse_config(data['config'].encode()).items():
        if re.fullmatch(r'mp\d+', key) and key not in managed:
            args += ['--' + key, value]
    return clean, args


def cleanup_restore_attempts(directory, state):
    # A retry may leave a clone created before native pct restore was reached.
    # Only unreferenced clones owned by this operation are eligible for removal.
    for journal in directory.rglob('zfs-restore.json'):
        if journal.is_symlink():
            raise ValueError('Unsafe ZFS restore journal')
        data = json.loads(journal.read_text())
        if data.get('token') != state['token']:
            continue
        for attempt in data['attempts']:
            if not re.fullmatch(r'[a-f0-9]{32}', attempt['id']):
                raise ValueError('Invalid ZFS restore attempt')
            for key, v in attempt['volumes'].items():
                original = next(item for item in state['volumes'] if item['vmid'] == v['vmid'] and item['key'] == key)
                name = f"subvol-{v['vmid']}-oci-restored-{state['token']}-{attempt['id']}-{key}"
                ds = original['pool'] + '/' + name
                if v['dataset'] != ds or v['backup'] != original['backup']:
                    raise ValueError('Invalid ZFS restore cleanup target')
                if not exists(ds):
                    continue
                tagged(ds, state['token'], v.get('guid'))
                ref = original['storage'] + ':' + name
                attached = any(ref in config.read_text() for config in Path('/etc/pve/lxc').glob('*.conf'))
                if attached:
                    continue
                if properties(ds, ('origin',))['origin'] != original['backup'] + '@' + original['snapshot']:
                    raise ValueError('Unexpected ZFS restore cleanup origin')
                run('zfs', 'destroy', ds)


def cleanup(directory):
    """Release owned recovery parents only after their dependent live clone is known."""
    directory = Path(directory)
    for path in directory.rglob('zfs-build.json'):
        if path.is_symlink():
            raise ValueError('Unsafe ZFS recovery journal')
        state = json.loads(path.read_text())
        if state.get('kind') != KIND or state.get('released'):
            continue
        token = state['token']
        if not re.fullmatch(r'[a-f0-9]{32}', token):
            raise ValueError('Invalid ZFS recovery token')
        cleanup_restore_attempts(path.parent, state)
        for v in state['volumes']:
            backup, snap = v['backup'], v['snapshot']
            if not valid_backup(v, token) or snap != 'oci-' + token:
                raise ValueError('Invalid recovery cleanup target')
            if not exists(backup):
                # An early failure may only have created the owned source snapshot.
                live = v.get('cleanup_live', {'dataset': v['source'], 'guid': v['source_guid']})
                original = live['dataset'] + '@' + snap
                if exists(original):
                    if properties(live['dataset'], ('guid',))['guid'] != live['guid']:
                        raise ValueError('Snapshot source identity changed')
                    tagged(original, token, v.get('snapshot_guid'))
                    run('zfs', 'destroy', original)
                continue
            tagged(backup, token, v.get('backup_guid'))
            origin = properties(backup, ('origin',))['origin']
            if origin != '-':
                # Clone created but not yet promoted, or cleanup already promoted
                # the live child. Both origins must be this owned snapshot.
                live = v.get('cleanup_live', {'dataset': v['source'], 'guid': v['source_guid']})
                if origin != live['dataset'] + '@' + snap or properties(live['dataset'], ('guid',))['guid'] != live['guid']:
                    raise ValueError('Unexpected recovery clone origin')
                tagged(origin, token, v.get('snapshot_guid'))
                run('zfs', 'destroy', backup)
                run('zfs', 'destroy', origin)
                continue
            point = backup + '@' + snap
            if not exists(point):
                # Cleanup may have removed the last snapshot just before a
                # crash. Only the exact owned, snapshot-free parent is freed.
                if run('zfs', 'list', '-H', '-r', '-t', 'snapshot', '-o', 'name', backup):
                    raise ValueError('Recovery dataset has untracked snapshots')
                run('zfs', 'destroy', backup)
                continue
            tagged(point, token, v.get('snapshot_guid'))
            if run('zfs', 'list', '-H', '-r', '-t', 'snapshot', '-o', 'name', backup).splitlines() != [point]:
                raise ValueError('Recovery dataset has untracked snapshots')
            children = properties(point, ('clones',))['clones']
            if children != '-':
                clones = children.split(',')
                if len(clones) != 1:
                    raise ValueError('Recovery still has retained or external dependent volumes')
                live = clones[0]
                current = api().owned(v['vmid'], state['records'][str(v['vmid'])])
                refs = [line.split(': ', 1)[1].split(',', 1)[0] for line in current.decode().splitlines()
                        if re.match(r'(?:rootfs|mp\d+): ', line)]
                live_name = live.rsplit('/', 1)[-1]
                if not any(ref == v['storage'] + ':' + live_name for ref in refs):
                    raise ValueError('Dependent recovery volume is not attached to the application')
                if properties(live, ('origin',))['origin'] != point:
                    raise ValueError('Dependent recovery origin changed')
                v['cleanup_live'] = {'dataset': live, 'guid': properties(live, ('guid',))['guid']}
                instances.write(path, state)
                run('zfs', 'promote', live)
                run('zfs', 'destroy', backup)
                run('zfs', 'destroy', live + '@' + snap)
            else:
                if run('zfs', 'list', '-H', '-r', '-t', 'snapshot', '-o', 'name', backup).splitlines() != [point]:
                    raise ValueError('Recovery dataset has untracked snapshots')
                run('zfs', 'destroy', point)
                run('zfs', 'destroy', backup)
        state['released'] = True
        instances.write(path, state)
        api().log('ZFS recovery: ' + json.dumps({'phase': 'released', 'volumes': len(state['volumes'])}))
