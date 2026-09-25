#!/usr/bin/env python3
"""Private installation evidence and read-only update diagnostics. No updater."""
from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import uuid

from oci_ui import translate, msg_error, msg_ok

ROOT = Path('/var/lib/proxmenux/oci-installations')
FIELDS = ('Entrypoint', 'Cmd', 'Env', 'User', 'WorkingDir', 'StopSignal', 'Volumes', 'ExposedPorts', 'Healthcheck')
VERSION_ENV_RE = re.compile(r'^([A-Z][A-Z0-9_]*)_VERSION$')
# Repositories whose version variable is not named after the image.
VERSION_ENV_NAMES = {'postgres': 'PG'}


def version_from_environment(repository, environment):
    """The application version an image states in its own environment.

    Official library images publish no labels at all, yet they carry the
    version as NEXTCLOUD_VERSION, REDIS_VERSION, MONGO_VERSION. Most also
    carry their dependencies there — GOSU_VERSION, PHP_VERSION, NJS_VERSION —
    so only a variable that names this image is accepted. A version variable
    that names something else is never taken for the application's, not even
    when it is the only one: an application built on a Python base carries
    PYTHON_VERSION alone, and Paperless-ngx would read as 3.14.7. Anything
    that does not name the image is left to the label.
    """
    found = {}
    for entry in environment or []:
        name, _, value = entry.partition('=')
        match = VERSION_ENV_RE.match(name)
        if match and value.strip():
            found[match.group(1)] = value.strip()
    if not found:
        return None
    basename = repository.rsplit('/', 1)[-1]
    expected = VERSION_ENV_NAMES.get(basename, basename.replace('-', '_')).upper()
    return found.get(expected)


def command(*args):
    result = subprocess.run(args, capture_output=True, timeout=120)
    if result.returncode:
        # Tool errors may contain credentials or environment values.
        raise RuntimeError(f"{args[0]} {translate('failed with exit code')} {result.returncode}")
    return result.stdout


def sha(data):
    return hashlib.sha256(data).hexdigest()


def image_from_archive(path):
    with tarfile.open(path) as archive:
        members = {m.name.removeprefix('./'): m for m in archive.getmembers() if m.isfile()}

        def read(name, digest=None):
            member = members[name]
            if member.size > 16 * 1024 * 1024:
                raise ValueError(translate('OCI metadata too large'))
            data = archive.extractfile(member).read()
            if digest and 'sha256:' + sha(data) != digest:
                raise ValueError(translate('OCI metadata integrity mismatch'))
            return json.loads(data)

        def blob(digest):
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
                raise ValueError(translate('Invalid OCI digest'))
            return read('blobs/sha256/' + digest[7:], digest)

        descriptors = read('index.json')['manifests']
        if len(descriptors) != 1:
            raise ValueError(translate('A single-platform OCI archive is required'))
        digest = descriptors[0]['digest']
        manifest = blob(digest)
        config = blob(manifest['config']['digest'])
        return {'manifest_digest': digest, 'config_digest': manifest['config']['digest'],
                'architecture': config['architecture'], 'os': config.get('os'),
                'defaults': {k: config.get('config', {}).get(k) for k in FIELDS}}


def parse_config(data):
    values = {}
    for line in data.decode().splitlines():
        if line and not line.startswith('#') and ': ' in line:
            key, value = line.split(': ', 1)
            values[key] = value
    return values


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.geteuid():
        raise ValueError(translate('Unsafe registry directory'))
    path.chmod(0o700)


def save_record(root, record):
    private_directory(root)
    with (root / '.lock').open('a') as lock:
        os.chmod(root / '.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / f"{record['vmid']}.json"
        if path.exists() or path.is_symlink():
            if path.is_symlink():
                raise ValueError(translate('Unsafe record'))
            history = root / 'history'
            private_directory(history)
            # Keep the current record present until its replacement is durable.
            os.link(path, history / f"{record['vmid']}-{uuid.uuid4().hex}.json")
        fd, temporary = tempfile.mkstemp(dir=root, prefix='.record-')
        try:
            with os.fdopen(fd, 'w') as out:
                json.dump(record, out, indent=2, ensure_ascii=True)
                out.write('\n')
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def record_install(args):
    template = json.loads(Path(args.template).read_text())
    deployment = json.loads(Path(args.deployment).read_text())
    config = command('pct', 'config', str(args.vmid))
    image = image_from_archive(args.archive)
    record = {'schema_version': 1, 'installation_id': str(uuid.uuid4()), 'vmid': args.vmid,
              'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'provenance': 'installer-completed', 'image': image,
              'reference': template['container_contract']['image']['reference'],
              'resolved_registry_digest': args.digest, 'archive_path': args.archive,
              'template': template, 'deployment': deployment,
              'config_sha256': sha(config), 'config': config.decode(),
              'start_after_create_requested': bool(deployment.get('start_after_create')),
              'automatic_update_enabled': False}
    save_record(args.state_dir, record)


def resolve_candidate(reference, architecture):
    repo = reference.split('@', 1)[0]
    if ':' in repo.rsplit('/', 1)[-1]:
        repo = repo.rsplit(':', 1)[0]
    transport = reference
    if '@' in reference:
        transport = repo + '@' + reference.split('@', 1)[1]
    raw = command('skopeo', 'inspect', '--raw', 'docker://' + transport)
    manifest = json.loads(raw)
    if 'manifests' in manifest:
        matches = [m for m in manifest['manifests'] if m.get('platform', {}).get('architecture') == architecture
                   and m.get('platform', {}).get('os') == 'linux']
        if len(matches) != 1:
            raise ValueError(translate('A single matching image platform cannot be resolved'))
        digest = matches[0]['digest']
        raw = command('skopeo', 'inspect', '--raw', 'docker://' + repo + '@' + digest)
        if 'sha256:' + sha(raw) != digest:
            raise ValueError(translate('The manifest does not match its digest'))
    digest = 'sha256:' + sha(raw)
    config = json.loads(command('skopeo', 'inspect', '--config', 'docker://' + repo + '@' + digest))
    if config.get('architecture') != architecture or config.get('os') != 'linux':
        raise ValueError(translate('Incompatible image platform'))
    labels = config.get('config', {}).get('Labels') or {}
    defaults = {k: config.get('config', {}).get(k) for k in FIELDS}
    # The environment is read first because a self-naming variable cannot be
    # inherited: `org.opencontainers.image.version` is copied from the base
    # image by enough publishers that mongo and rabbitmq both report the
    # Ubuntu release there instead of their own version.
    version = (version_from_environment(repo, defaults.get('Env'))
               or labels.get('org.opencontainers.image.version')
               or labels.get('build_version'))
    # The build date identifies the image as the publisher released it: it is
    # what changes when an image is rebuilt, whether or not the application
    # version inside it moved.
    return {'manifest_digest': digest, 'defaults': defaults, 'version': version,
            'created': config.get('created')}


def compare(record, current, candidate=None):
    blockers = []
    cfg = parse_config(current)
    if sha(current) != record['config_sha256']:
        blockers.append('configuration-drift-or-vmid-reused')
    mounts = []
    for key, value in cfg.items():
        if not re.fullmatch(r'mp\d+', key):
            continue
        parts = value.split(',')
        source = parts[0].removeprefix('volume=')
        options = dict(p.split('=', 1) for p in parts[1:] if '=' in p)
        managed = not source.startswith('/') and ':' in source
        mounts.append(options.get('mp'))
        if not managed or options.get('backup') != '1':
            blockers.append('persistent-mount-needs-backup:' + key)
    declared = set(record['image']['defaults'].get('Volumes') or {})
    declared.update(v['container_path'] for v in record['template'].get('container_contract', {}).get('volumes', []) if v.get('container_path'))
    for path in sorted(declared):
        if path not in mounts:
            blockers.append('image-volume-not-externalized:' + path)
    deployment = record['deployment']
    if deployment.get('stack_managed'):
        blockers.append('stack-member-requires-coordination')
    if deployment.get('deployment_kind') not in (None, 'single-lxc'):
        blockers.append('stack-or-special-deployment-requires-coordination')
    if cfg.get('hookscript'):
        blockers.append('hookscript-requires-coordination')
    if record['template'].get('installer_profile', {}).get('post_start_configurations') or deployment.get('post_start_configurations'):
        blockers.append('rootfs-adaptations-require-replay')
    report = {'vmid': record['vmid'], 'registered': True, 'update_available': None,
              'automatic_update_enabled': False, 'blockers': blockers,
              'requires': ['consistent-backup', 'review-rootfs-only-data', 'transactional-updater-not-implemented']}
    if candidate:
        replaced = candidate['manifest_digest'] != record['image']['manifest_digest']
        report['update_available'] = replaced
        report['candidate_digest'] = candidate['manifest_digest']
        # The two sides read the image configuration through different paths:
        # the record from the archive's own config blob, the candidate from
        # `skopeo inspect --config`, which normalises to the OCI schema and
        # drops Docker extensions such as Healthcheck. A field the candidate
        # cannot report is unknown, not changed, and an identical digest means
        # the configuration is byte-identical whatever either side returns.
        report['changed_image_fields'] = [
            key for key in FIELDS
            if replaced and candidate['defaults'].get(key) is not None
            and record['image']['defaults'].get(key) != candidate['defaults'].get(key)
        ]
        old_env = dict(v.split('=', 1) for v in record['image']['defaults'].get('Env') or [] if '=' in v)
        new_env = dict(v.split('=', 1) for v in candidate['defaults'].get('Env') or [] if '=' in v)
        report['changed_environment_names'] = sorted(
            k for k in old_env.keys() | new_env.keys() if replaced and old_env.get(k) != new_env.get(k))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=ROOT)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('inventory')
    diagnose = sub.add_parser('diagnose')
    diagnose.add_argument('vmid', type=int)
    diagnose.add_argument('--check-registry', action='store_true')
    record = sub.add_parser('record', help='Internal installer operation; not legacy adoption')
    record.add_argument('vmid', type=int)
    for flag in ('template', 'deployment', 'archive', 'digest'):
        record.add_argument('--' + flag, required=True)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error(translate('Run as root on the Proxmox node; the registry contains private data'))
    try:
        if args.action == 'record':
            record_install(args)
            msg_ok(translate('Private installation record saved'))
        elif args.action == 'inventory':
            rows = command('pct', 'list').decode().splitlines()[1:]
            print(json.dumps([{'vmid': int(row.split()[0]), 'registered': (args.state_dir / (row.split()[0] + '.json')).is_file()}
                              for row in rows if row.strip()], indent=2))
        else:
            path = args.state_dir / f'{args.vmid}.json'
            if not path.exists():
                print(json.dumps({'vmid': args.vmid, 'registered': False, 'automatic_update_enabled': False,
                                  'blockers': ['unregistered-installation-no-automatic-adoption']}))
                return 0
            record = json.loads(path.read_text())
            if record.get('schema_version') != 1 or record.get('vmid') != args.vmid:
                raise ValueError(translate('Incompatible record'))
            current = command('pct', 'config', str(args.vmid))
            candidate = resolve_candidate(record['reference'], record['image']['architecture']) if args.check_registry else None
            print(json.dumps(compare(record, current, candidate), indent=2))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired, tarfile.TarError):
        with contextlib.redirect_stdout(sys.stderr):
            msg_error(translate('The record or diagnosis could not be completed; no update was run.'))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
