"""Prepare interactive decisions first, then run existing lifecycle helpers in order.

This is not a second updater. The native helper owns image checks, locking,
backup, replacement and recovery. Batch reports contain no commands or secrets;
transient proposals stay in a private directory until the queue closes.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from urllib.parse import unquote

from .i18n import N_, translate
from .ui import BackRequested, UserCancelled

CONFIGS = Path('/etc/pve/lxc')
LABELS = {'updated': N_('Updated'), 'unchanged': N_('Already up to date'),
          'failed': N_('Failed'), 'blocked': N_('Needs review'),
          'recovery-required': N_('Recovery required'), 'skipped': N_('Not started'),
          'settings-updated': N_('Updated settings'), 'interrupted': N_('Interrupted'), 'queued': N_('Queued'), 'running': N_('Running')}


class BatchChanged(ValueError):
    pass


class PendingRecovery(BatchChanged):
    pass


def _backend(project):
    sys.path.insert(0, str(Path(project) / 'remote'))
    import oci_instances
    return oci_instances


def _snapshot(project, vmid):
    """Fresh local files, not stale UI/Monitor caches or repeated PVE processes."""
    instances = _backend(project)
    with instances.locked(instances.ROOT):
        selected = instances.read(instances.ROOT, vmid)
        primary_id = selected.get('stack_member', {}).get('primary_vmid', vmid)
        primary = instances.read(instances.ROOT, primary_id)
        members = primary.get('stack', {}).get('members', [])
        ids = [m['vmid'] for m in members] or [primary_id]
        if (primary_id not in ids or len(set(ids)) != len(ids)
                or vmid not in ids or any(type(v) is not int or v < 100 for v in ids)):
            raise BatchChanged(translate('The selected OCI application changed. Prepare the batch again.'))
        expected = {m['vmid']: m['installation_id'] for m in members}
        state = {'primary': primary_id, 'members': {}}
        for member in sorted(ids):
            path = instances.location(instances.ROOT, member)
            raw = path.read_bytes()
            record = instances.read(instances.ROOT, member)
            config = (CONFIGS / f'{member}.conf').read_bytes()
            identity = record['installation_id']
            # PVE stores the description as leading # comments in its native
            # file; pct config exposes a description: field instead. Do not
            # include comments from saved snapshot sections.
            lines = config.decode().split('\n[', 1)[0].splitlines()
            description = next((line.partition(':')[2].lstrip() for line in lines
                                if line.startswith('description:')), None)
            if description is None:
                description = '\n'.join(line[1:] for line in lines if line.startswith('#'))
            identity_config = json.dumps({'description': unquote(description)}).encode()
            if (record['status'] != 'installed' or record.get('pending_transaction')
                    or record.get('pending_stack_transaction')):
                raise PendingRecovery(translate('Finish or recover pending OCI operations before preparing a batch.'))
            image = (record.get('observed') or {}).get('image', {}).get('manifest_digest')
            if (instances.identity(identity_config) != identity
                    or not isinstance(image, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', image)
                    or (expected and expected[member] != identity)
                    or (members and (record.get('stack_member') or {}).get('primary_vmid') != primary_id)):
                raise BatchChanged(translate('The selected OCI application changed. Prepare the batch again.'))
            state['members'][str(member)] = {
                'identity': identity, 'record_sha256': hashlib.sha256(raw).hexdigest(),
                'config_sha256': hashlib.sha256(config).hexdigest(),
                'image': (record.get('observed') or {}).get('image', {}).get('manifest_digest')}
        return state


def _unchanged(project, entry):
    return _snapshot(project, entry['vmid']) == entry['snapshot']


def _failure_status(project, entry):
    try:
        current = _snapshot(project, entry['vmid'])
        same = (current['primary'] == entry['snapshot']['primary']
                and {v: r['identity'] for v, r in current['members'].items()}
                == {v: r['identity'] for v, r in entry['snapshot']['members'].items()})
        return 'failed' if same else 'blocked'
    except PendingRecovery:
        return 'recovery-required'
    except (OSError, ValueError, KeyError, BlockingIOError):
        return 'blocked'


def _collect(folder, steps):
    def collect(command, title):
        command = list(command)
        if '--proposal' in command:
            index = command.index('--proposal') + 1
            proposal = json.loads(Path(command[index]).read_text())
            path = folder / (uuid.uuid4().hex + '.json')
            with path.open('x', encoding='utf-8') as output:
                path.chmod(0o600)
                json.dump(proposal, output)
            command[index] = str(path)
        steps.append({'command': command, 'title': title})
        return True
    return collect


@contextmanager
def _interruptions():
    previous = {}
    def interrupt(_number, _frame):
        raise KeyboardInterrupt()
    if threading.current_thread() is threading.main_thread():
        for number in (signal.SIGTERM, signal.SIGHUP):
            previous[number] = signal.signal(number, interrupt)
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _run_command(command):
    """No stdin, controlling terminal or per-application Enter pauses."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=True,
                               env=dict(os.environ, OCI_SPINNER='1' if sys.stdout.isatty() else '0'))
    try:
        return process.wait()
    except BaseException:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        raise


def _now():
    return datetime.now(timezone.utc).isoformat()


def execute_batch(project, entries, continue_after_failure=False, preparation_seconds=0):
    """Run an approved in-memory queue; never ask a UI question or resume it blindly."""
    from . import console, management
    instances = _backend(project)
    directory = instances.ROOT / 'batch-updates' / uuid.uuid4().hex
    report_path = directory / 'report.json'
    report = {'schema_version': 1, 'status': 'running', 'started_at': _now(),
              'preparation_seconds': round(preparation_seconds, 3),
              'continue_after_failure': bool(continue_after_failure), 'applications': [
                  {'vmid': e['vmid'], 'title': e['title'], 'members': list(e['snapshot']['members']),
                   'status': 'queued', 'seconds': 0, 'steps': []} for e in entries]}
    save = lambda: instances.write(report_path, report)
    started = time.monotonic()
    current = None
    save()
    try:
        with _interruptions():
            # Refuse a change during the final confirmation before any helper starts.
            for entry, result in zip(entries, report['applications']):
                current = result
                if not _unchanged(project, entry):
                    raise BatchChanged()
            current = None
            console.show_logo()
            for index, (entry, result) in enumerate(zip(entries, report['applications']), 1):
                current = result
                if not _unchanged(project, entry):
                    result['status'] = 'blocked'
                    break
                result['status'] = 'running'
                save()
                console.msg_title(f"{translate('Update OCI')} ({index}/{len(entries)}) · {entry['title']}")
                app_started = time.monotonic()
                try:
                    for step in entry['steps']:
                        step_started = time.monotonic()
                        step_result = {'title': step['title'], 'status': 'running', 'exit_code': None, 'seconds': 0}
                        result['steps'].append(step_result)
                        save()
                        try:
                            code = _run_command(step['command'])
                            step_result.update(exit_code=code, status='completed' if code == 0 else 'failed')
                        except KeyboardInterrupt:
                            step_result['status'] = 'interrupted'
                            raise
                        except (OSError, subprocess.SubprocessError):
                            step_result['status'] = 'failed'
                            raise
                        finally:
                            step_result['seconds'] = round(time.monotonic() - step_started, 3)
                            save()
                        if code:
                            result['status'] = 'interrupted' if code < 0 else _failure_status(project, entry)
                            break
                    else:
                        after = _snapshot(project, entry['vmid'])
                        if {v: r['identity'] for v, r in after['members'].items()} != {
                                v: r['identity'] for v, r in entry['snapshot']['members'].items()}:
                            raise BatchChanged()
                        before_images = {v: r['image'] for v, r in entry['snapshot']['members'].items()}
                        if before_images != {v: r['image'] for v, r in after['members'].items()}:
                            result['status'] = 'updated'
                        elif any('--proposal' in step['command'] for step in entry['steps']):
                            result['status'] = 'settings-updated'
                        else:
                            result['status'] = 'unchanged'
                    if result['status'] in ('updated', 'unchanged', 'settings-updated', 'failed'):
                        management.carry_records(project, vmids=[int(v) for v in entry['snapshot']['members']],
                                                 mount_stopped=True)
                except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                    result['status'] = _failure_status(project, entry)
                finally:
                    result['seconds'] = round(time.monotonic() - app_started, 3)
                    save()
                if (result['status'] in ('blocked', 'recovery-required', 'interrupted')
                        or (result['status'] == 'failed' and not continue_after_failure)):
                    break
            report['status'] = ('completed' if all(r['status'] in ('updated', 'unchanged', 'settings-updated')
                                                for r in report['applications']) else 'failed')
    except (BatchChanged, OSError, ValueError, KeyError, BlockingIOError) as error:
        report['status'] = 'failed'
        if current is not None and current['status'] in ('running', 'queued'):
            current['status'] = 'recovery-required' if isinstance(error, PendingRecovery) else 'blocked'
    except KeyboardInterrupt:
        report['status'] = 'interrupted'
        if current is not None and current['status'] == 'running':
            current['status'] = 'interrupted'
    finally:
        if any(r['status'] == 'interrupted' for r in report['applications']):
            report['status'] = 'interrupted'
        for result in report['applications']:
            if result['status'] == 'queued':
                result['status'] = 'skipped'
        report.update(finished_at=_now(), seconds=round(time.monotonic() - started, 3))
        save()
    return report, report_path


def run_batch(project, ui, selected):
    """Reuse all existing reviews and storage choices before executing any helper."""
    from . import management
    prepared_at = time.monotonic()
    try:
        continue_after_failure = ui.confirm(
            translate('Continue with the remaining applications after a safely recovered failure? A pending recovery or changed application always stops the batch.'),
            default=False)
        entries, seen = [], set()
        with tempfile.TemporaryDirectory(prefix='proxmenux-oci-batch-') as directory:
            folder = Path(directory)
            folder.chmod(0o700)
            for index, row in enumerate(selected, 1):
                if row['vmid'] in seen:
                    continue
                steps = []
                heading = f"{translate('Prepare OCI updates')} ({index}/{len(selected)}) · {row['title']}"
                if row.get('pending') or row.get('stack_pending'):
                    raise BatchChanged(translate('Finish or recover pending OCI operations before preparing a batch.'))
                if not management.manage_instance(project, ui, row, action='update', heading=heading,
                                                    runner=_collect(folder, steps)):
                    return None
                snapshot = _snapshot(project, row['vmid'])
                if not steps:
                    raise BatchChanged(translate('No update operation was prepared.'))
                if seen.intersection(map(int, snapshot['members'])):
                    raise BatchChanged(translate('The selected OCI application changed. Prepare the batch again.'))
                seen.update(map(int, snapshot['members']))
                entries.append({'vmid': snapshot['primary'], 'title': row['title'],
                                'snapshot': snapshot, 'steps': steps})
            names = '\n'.join(f"  CT {e['vmid']} · {e['title']}" for e in entries)
            if not entries or not ui.review(names, translate('Update selected OCI applications'),
                    question=translate('Start the prepared batch now? No further questions will be asked. Keep this terminal open until the summary.'), default=False):
                return None
            report, path = execute_batch(project, entries, bool(continue_after_failure),
                                         time.monotonic() - prepared_at)
        heading = (translate('OCI batch completed') if report['status'] == 'completed'
                   else translate('OCI batch stopped or finished with errors'))
        lines = [f"CT {r['vmid']} · {r['title']}: {translate(LABELS[r['status']])} ({r['seconds']:.1f}s)"
                 for r in report['applications']]
        ui.message('\n'.join([translate('Batch execution time: {seconds}s').format(seconds=f"{report['seconds']:.1f}"),
                              '', *lines, '', translate('Batch report: {path}').format(path=path)]), heading)
        return report
    except (UserCancelled, BackRequested):
        return None
    except (OSError, ValueError, KeyError, BlockingIOError) as error:
        ui.message(str(error), translate('OCI batch could not be prepared'))
        return None
