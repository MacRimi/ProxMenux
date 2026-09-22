#!/usr/bin/env python3
"""Recoverable nginx laboratory transaction. NOT a general OCI updater."""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from oci_installation_state import image_from_archive, parse_config, private_directory, save_record, sha
from verify_oci_archive import verify_archive, VerificationError


def run(*args):
    print('Paso:', args[0], args[1] if len(args) > 1 else '', flush=True)
    p = subprocess.run(args, capture_output=True, timeout=600)
    if p.returncode:
        raise RuntimeError(f'{args[0]} fallo con codigo {p.returncode}; transaccion conservada')
    return p.stdout


def atomic(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.journal-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def checkpoint(path, state, phase):
    state['phase'] = phase
    atomic(path, state)
    print('Estado:', phase, flush=True)


def filehash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def preflight(record, config):
    cfg = parse_config(config)
    if record['config_sha256'] != sha(config):
        raise ValueError('Configuracion modificada desde el registro')
    if cfg.get('hostname') != 'oci-update-lab' or record['reference'] != 'docker.io/library/nginx:alpine':
        raise ValueError('Solo se admite el nginx de laboratorio')
    allowed = {'arch', 'cores', 'description', 'entrypoint', 'env', 'hostname', 'memory', 'mp0', 'net0',
               'onboot', 'ostype', 'rootfs', 'swap', 'tags', 'unprivileged', 'lxc.init.cwd',
               'lxc.signal.halt', 'cmode', 'console', 'tty'}
    if set(cfg) - allowed or '[' in config.decode():
        raise ValueError('Configuracion avanzada/snapshots no soportada')
    if cfg.get('unprivileged') != '1' or cfg.get('onboot', '0') != '0':
        raise ValueError('El laboratorio requiere unprivileged=1 y onboot=0')
    mp = cfg.get('mp0', '')
    if not mp.startswith('local-lvm:') or 'mp=/usr/share/nginx/html' not in mp or 'backup=1' not in mp:
        raise ValueError('Solo se admite mp0 gestionado y respaldado del laboratorio')
    if not cfg.get('rootfs', '').startswith('local-lvm:'):
        raise ValueError('Storage de laboratorio no soportado')
    return cfg


def health(vmid):
    for _ in range(30):
        try:
            data = run('pct', 'exec', str(vmid), '--', 'wget', '-qO-', 'http://127.0.0.1/')
            if data == b'oci-persistence-proof':
                return
        except RuntimeError:
            pass
        time.sleep(1)
    raise RuntimeError('Healthcheck de datos/HTTP fallido')


def stop(vmid):
    if b'running' in run('pct', 'status', str(vmid)):
        run('pct', 'shutdown', str(vmid), '--timeout', '60')


def create(vmid, archive, cfg, hostname, marker):
    run('pct', 'create', str(vmid), archive, '--rootfs', 'local-lvm:2',
        '--hostname', hostname, '--cores', cfg.get('cores', '1'),
        '--memory', cfg.get('memory', '256'), '--swap', cfg.get('swap', '128'),
        '--unprivileged', '1', '--onboot', '0', '--tags', cfg.get('tags', 'lab'),
        '--net0', cfg['net0'], '--description', marker)


def transaction(args, journal):
    if journal.exists():
        raise ValueError('Ya existe una transaccion; consultar status o recover')
    record = json.loads((args.state_dir / f'{args.vmid}.json').read_text())
    if record.get('vmid') != args.vmid or record.get('schema_version') != 1:
        raise ValueError('Registro incompatible')
    before = run('pct', 'config', str(args.vmid))
    cfg = preflight(record, before)
    # Check HA separately; hostname/tags alone must never authorize mutation.
    resources = json.loads(run('pvesh', 'get', '/cluster/ha/resources', '--output-format', 'json'))
    if any(r.get('sid') == f'ct:{args.vmid}' for r in resources):
        raise ValueError('HA no soportado')
    if shutil.disk_usage(journal.parent).free < 8 * 1024**3:
        raise ValueError('Se requieren 8 GiB libres para esta prueba y su backup')
    archive = str(Path(args.archive).resolve())
    verify_archive(Path(archive))
    candidate = image_from_archive(archive)
    if candidate['architecture'] != record['image']['architecture']:
        raise ValueError('Arquitectura incompatible')
    if candidate['manifest_digest'] == record['image']['manifest_digest']:
        raise ValueError('La imagen ya coincide; no se requiere actualizar')
    # This lab contract has no user runtime overrides or custom entrypoint.
    if candidate['defaults'].get('Entrypoint') != record['image']['defaults'].get('Entrypoint') or candidate['defaults'].get('Cmd') != record['image']['defaults'].get('Cmd'):
        raise ValueError('Cambio de comando fuera del alcance del laboratorio')
    state = {'id': uuid.uuid4().hex, 'vmid': args.vmid, 'record': record, 'cfg': cfg,
             'archive': archive, 'candidate': candidate, 'was_running': b'running' in run('pct', 'status', str(args.vmid))}
    checkpoint(journal, state, 'prepared')
    stop(args.vmid)
    checkpoint(journal, state, 'backing-up')
    backup_dir = journal.parent / state['id']
    private_directory(backup_dir)
    run('vzdump', str(args.vmid), '--mode', 'stop', '--compress', 'zstd', '--dumpdir', str(backup_dir), '--tmpdir', '/var/tmp')
    backups = list(backup_dir.glob('vzdump-lxc-*.tar.zst'))
    if len(backups) != 1:
        raise ValueError('Backup no identificado')
    run('zstd', '-t', str(backups[0]))
    state.update(backup=str(backups[0]), backup_sha256=filehash(backups[0]))
    checkpoint(journal, state, 'backup-ready')
    stage = int(run('pvesh', 'get', '/cluster/nextid').strip())
    state['stage'] = stage
    checkpoint(journal, state, 'creating-stage')
    # Staging never starts, so it can retain the original MAC without collisions.
    create(stage, archive, cfg, 'oci-update-stage', state['id'])
    checkpoint(journal, state, 'parking-data')
    run('pct', 'move-volume', str(args.vmid), 'mp0', '--target-vmid', str(stage), '--target-volume', 'mp0')
    checkpoint(journal, state, 'data-parked')
    if args.interrupt_after == 'data-parked':
        raise RuntimeError('Interrupcion de laboratorio solicitada; ejecutar recover')
    current = parse_config(run('pct', 'config', str(args.vmid)))
    if current != {k: v for k, v in cfg.items() if k != 'mp0'}:
        raise ValueError('Cambio concurrente detectado; no se destruye el CT')
    checkpoint(journal, state, 'replacing-root')
    run('pct', 'destroy', str(args.vmid))
    create(args.vmid, archive, cfg, cfg['hostname'], state['id'])
    checkpoint(journal, state, 'root-replaced')
    if args.interrupt_after == 'root-replaced':
        raise RuntimeError('Interrupcion de laboratorio solicitada; ejecutar recover')
    checkpoint(journal, state, 'returning-data')
    run('pct', 'move-volume', str(stage), 'mp0', '--target-vmid', str(args.vmid), '--target-volume', 'mp0')
    checkpoint(journal, state, 'checking-service')
    run('pct', 'start', str(args.vmid))
    health(args.vmid)
    if not state['was_running']:
        stop(args.vmid)
    updated = copy.deepcopy(record)
    config = run('pct', 'config', str(args.vmid))
    updated.update(image=candidate, archive_path=archive, config=config.decode(), config_sha256=sha(config),
                   installation_id=str(uuid.uuid4()), previous_installation_id=record['installation_id'],
                   resolved_registry_digest=candidate['manifest_digest'], last_update_transaction=state['id'])
    save_record(args.state_dir, updated)
    checkpoint(journal, state, 'committed')


def recover(args, journal):
    state = json.loads(journal.read_text())
    if state['phase'] in ('committed', 'rolled-back'):
        raise ValueError('Transaccion terminada; no se restaura automaticamente')
    backup = state.get('backup')
    if not backup or filehash(backup) != state['backup_sha256']:
        raise ValueError('No hay backup verificado; recuperar manualmente sin destruir datos')
    vmid = state['vmid']
    path = Path(f'/etc/pve/lxc/{vmid}.conf')
    if path.exists():
        config = run('pct', 'config', str(vmid))
        cfg = parse_config(config)
        if state['id'] not in config.decode() and cfg.get('rootfs') != state['cfg']['rootfs']:
            raise ValueError('VMID posiblemente reutilizado; recuperacion bloqueada')
        stop(vmid)
    if state.get('stage') and Path(f"/etc/pve/lxc/{state['stage']}.conf").exists():
        config = run('pct', 'config', str(state['stage']))
        if state['id'] not in config.decode():
            raise ValueError('Staging ajeno; recuperacion bloqueada')
        stop(state['stage'])
    checkpoint(journal, state, 'restoring-backup')
    run('pct', 'restore', str(vmid), backup, '--force', '1', '--storage', 'local-lvm', '--description', state['id'])
    run('pct', 'start', str(vmid))
    health(vmid)
    if not state['was_running']:
        stop(vmid)
    restored = copy.deepcopy(state['record'])
    config = run('pct', 'config', str(vmid))
    restored.update(config=config.decode(), config_sha256=sha(config), recovered_transaction=state['id'])
    save_record(args.state_dir, restored)
    checkpoint(journal, state, 'rolled-back')
    print('Staging y backup conservados, sin limpieza automatica.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'status', 'recover'])
    parser.add_argument('vmid', type=int)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--transaction-dir', type=Path, required=True)
    parser.add_argument('--archive')
    parser.add_argument('--interrupt-after', choices=['data-parked', 'root-replaced'])
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Se requiere root')
    private_directory(args.transaction_dir)
    journal = args.transaction_dir / f'{args.vmid}.json'
    with Path(f'/run/lock/proxmenux-oci-lab-{args.vmid}.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == 'status':
                state = json.loads(journal.read_text())
                print(json.dumps({k: state.get(k) for k in ('id', 'vmid', 'stage', 'phase')}, indent=2))
            elif args.action == 'recover':
                recover(args, journal)
            else:
                if not args.archive:
                    parser.error('apply requiere --archive')
                transaction(args, journal)
        except (OSError, ValueError, RuntimeError, KeyError, VerificationError, subprocess.TimeoutExpired) as error:
            print(f'Proceso detenido ({type(error).__name__}). Diario privado: {journal}. Consultar status/recover.')
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
