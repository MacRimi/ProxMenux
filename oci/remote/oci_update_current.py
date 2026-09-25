#!/usr/bin/env python3
"""Resolve a saved image channel and invoke the native update transaction."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

import oci_instances as instances
import oci_instance_transaction as transaction
from oci_installation_state import image_from_archive
from oci_ui import translate, msg_info, msg_ok, msg_warn, msg_error, msg_info2


def repository(reference):
    repo = reference.split('@', 1)[0]
    if ':' in repo.rsplit('/', 1)[-1]:
        repo = repo.rsplit(':', 1)[0]
    return repo


def run_quiet(args, error, capture=False):
    """Runs a helper with its output in the private log; error is the message of a failure."""
    transaction.log('$ ' + shlex.join(args))
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=dict(os.environ, PYTHONPATH=str(Path(__file__).parent)))
    try:
        while True:
            try:
                output, errors = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                continue
            if process.returncode:
                transaction.log(f'  exit {process.returncode}')
            transaction.log_output(None if capture else output, errors)
            if process.returncode:
                raise RuntimeError(error)
            return output
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def resolve_archive(desired, config, current=None, check=None):
    # Shared by individual and coordinated operations; no guest mutation here.
    # When the registry still serves the current digest nothing is downloaded.
    reference = desired['template']['container_contract']['image']['reference']
    architecture = transaction.parse_config(config)['arch']
    msg_info(translate('Checking the image in the registry...'))
    transaction.log(f'image: {reference} ({architecture})')
    code = ('import json,sys; from oci_installation_state import resolve_candidate; '
            'print(json.dumps(resolve_candidate(sys.argv[1],sys.argv[2])))')
    candidate = json.loads(run_quiet([sys.executable, '-c', code, reference, architecture],
                                     translate('Could not query the image registry'), capture=True))
    digest = candidate['manifest_digest']
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError(translate('Invalid registry digest'))
    msg_ok(f"{translate('Image:')} {reference} ({candidate.get('version') or digest[7:19]})")
    if digest == current:
        return None, digest
    if check:
        check()
    storage = desired['deployment']['template_storage']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', storage):
        raise ValueError(translate('Invalid template storage'))
    archive = Path(instances.command('pvesm', 'path',
        f'{storage}:vztmpl/proxmenux-update-{architecture}-{digest[7:]}.tar').decode().strip())
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.is_symlink():
        raise ValueError(translate('Unsafe OCI archive path'))
    verifier = Path(__file__).with_name('verify_oci_archive.py')

    def intact(path):
        try:
            run_quiet([sys.executable, str(verifier), str(path)],
                      translate('The image did not pass the integrity check'))
        except RuntimeError:
            return False
        return image_from_archive(str(path))['manifest_digest'] == digest

    if archive.exists():
        msg_info(translate('Verifying the image integrity...'))
        if intact(archive):
            msg_ok(translate('Using the verified image from the cache'))
            return archive, digest
        msg_warn(translate('The cached image is damaged; it will be downloaded again.'))
        archive.unlink()
    # A download can come back complete yet damaged when the connection drops
    # and the transfer resumes; the integrity check catches it, and a second
    # download is what repairs it.
    for attempt in (1, 2):
        msg_info(transaction.fit(f"{translate('Downloading the image:')} {reference}"))
        transaction.log(f'download attempt {attempt}/2')
        fd, name = tempfile.mkstemp(prefix='.proxmenux-update-', suffix='.tar', dir=archive.parent)
        os.close(fd)
        partial = Path(name)
        try:
            run_quiet(['skopeo', 'copy', '--override-arch', architecture,
                'docker://' + repository(reference) + '@' + digest,
                'oci-archive:' + str(partial)], translate('Could not download the image'))
            msg_ok(translate('Image downloaded'))
            msg_info(translate('Verifying the image integrity...'))
            if intact(partial):
                partial.chmod(0o644)
                os.replace(partial, archive)
                msg_ok(translate('Image integrity verified'))
                return archive, digest
        except RuntimeError:
            if attempt == 2:
                raise
        finally:
            partial.unlink(missing_ok=True)
        if attempt == 2:
            raise RuntimeError(translate('Could not obtain an intact image after two attempts'))
        msg_warn(translate('The image download did not complete correctly; downloading it again...'))


def kept_settings(changes, deployment):
    """Names of the settings changed in Proxmox that the new container keeps."""
    labels = {'memory': translate('Memory'), 'swap': translate('Swap'), 'cores': translate('CPU cores'),
              'cpulimit': translate('CPU cores'), 'cpuunits': translate('CPU priority'),
              'onboot': translate('Start with Proxmox')}
    kept = []
    for key, value in changes.items():
        section, name = transaction.ADOPTABLE[key]
        if (deployment.get(section, {}) if section else deployment).get(name) == value:
            kept.append(labels[key])
    return kept


def update(vmid, acknowledge_external_data=False, proposal=None, keep_backup=None):
    operation = 'recreate' if proposal is not None else 'update'
    msg_info(translate('Checking the container before the update...') if operation == 'update'
             else translate('Checking the container before recreating it...'))
    with instances.locked(instances.ROOT):
        record = instances.read(instances.ROOT, vmid)
        if record['status'] != 'installed' or record.get('pending_transaction') or record.get('pending_stack_transaction'):
            raise ValueError(translate('The instance is not ready to be updated'))
        config = instances.command('pct', 'config', str(vmid))
        desired = transaction.candidate_contract(record, operation, proposal)
        changes = transaction.external_changes(record, config)
        transaction.preflight(record, desired, config)
        msg_ok(translate('Container checked'))
        current = record['observed']['image']['manifest_digest'] if operation == 'update' else None
        archive, digest = resolve_archive(desired, config, current, lambda: transaction.require_backup_space(
            instances.location(instances.ROOT, vmid).parent, [vmid]))
        if archive is None:
            msg_ok(translate('The image is already up to date; nothing was changed.'))
            return
        file_storage = None
        if keep_backup:
            import oci_keep_backup
            oci_keep_backup.validate(keep_backup)
            if oci_keep_backup.dump_dir(keep_backup) is None:
                msg_info(f"{translate('Creating a backup in')} {keep_backup}...")
                oci_keep_backup.before_update(vmid, keep_backup)
                msg_ok(f"{translate('Backup created in')} {keep_backup}")
            else:
                file_storage = keep_backup
        kept = kept_settings(changes, desired['deployment'])
        if kept:
            msg_info2(f"{translate('Keeping the settings changed in Proxmox:')} {', '.join(kept)}")
        transaction.apply(instances.ROOT, vmid, archive, operation, proposal=proposal,
                          registry_digest=digest, acknowledge_external_data=acknowledge_external_data,
                          keep_backup=file_storage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vmid', type=int)
    parser.add_argument('--acknowledge-external-data', action='store_true')
    parser.add_argument('--proposal', type=Path)
    parser.add_argument('--keep-backup', metavar='STORAGE')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    try:
        proposal = json.loads(args.proposal.read_text()) if args.proposal else None
        update(args.vmid, args.acknowledge_external_data, proposal, args.keep_backup)
        return 0
    except BlockingIOError:
        msg_error(translate('Another OCI operation is using the registry. This operation was not started.'))
        return 1
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        transaction.report_error(error, f'update-{args.vmid}')
        if transaction.pending_journal():
            transaction.recovery_hint()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
