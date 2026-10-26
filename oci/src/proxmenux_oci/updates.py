"""OCI menu update status and explicit, user-selected updates."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from .i18n import translate
from .ui import UserCancelled, menu_size


class UpdateCheck:
    def __init__(self, project):
        self.project = Path(project)
        sys.path.insert(0, str(self.project / 'remote'))
        self.backend = importlib.import_module('oci_update_check')
        self.process = None
        self.failed = False
        self.failed_applications = set()
        self.completed = self.total = 0
        self._progress_buffer = b''
        self._shown_progress = (0, 0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    @property
    def active(self):
        # A finished child still needs one redraw to publish its final cache.
        return self.process is not None

    def ready(self):
        return self.process is not None and self.process.poll() is not None

    def _read_progress(self):
        if self.process is None or self.process.stdout is None:
            return
        try:
            while chunk := os.read(self.process.stdout.fileno(), 8192):
                self._progress_buffer += chunk
                while b'\n' in self._progress_buffer:
                    line, self._progress_buffer = self._progress_buffer.split(b'\n', 1)
                    try:
                        data = json.loads(line)
                        if isinstance(data.get('failed'), list):
                            self.failed_applications = {vmid for vmid in data['failed'] if type(vmid) is int}
                            continue
                        completed, total = data['completed'], data['total']
                        if type(completed) is int and type(total) is int and 0 <= completed <= total:
                            self.completed, self.total = completed, total
                    except (ValueError, TypeError, KeyError):
                        pass  # Never display worker output as UI text.
                if len(self._progress_buffer) > 8192:
                    self._progress_buffer = b''
        except (BlockingIOError, OSError):
            pass

    def changed(self):
        self._read_progress()
        return self.ready() or (self.completed, self.total) != self._shown_progress

    def _close_output(self):
        if self.process is not None and self.process.stdout is not None:
            self.process.stdout.close()

    def status(self):
        self._read_progress()
        if self.ready():
            self.failed = self.process.wait() != 0
            self._close_output()
            self.process = None
        try:
            state = self.backend.cached(failed=self.failed_applications)
        except (OSError, ValueError, KeyError, TypeError):
            state = {'checked': False, 'available': [], 'unknown': 0, 'applications': 0}
        if self.failed:
            # A failed worker must not present an older successful check as
            # the outcome of the new request, or keep its old update list.
            state = dict(state, checked=True, available=[], unknown=state['applications'])
        return state

    def start(self):
        if self.running:
            return
        if not self.backend.monitor_available():
            raise ValueError(translate('The ProxMenux Monitor update checker is not available. Start or update ProxMenux Monitor and try again.'))
        state = self.status()
        self.failed = False
        self.failed_applications = set()
        self.completed, self.total = 0, state['applications']
        self._progress_buffer = b''
        self.process = subprocess.Popen(
            [sys.executable, str(self.project / 'remote/oci_update_check.py'), '--progress'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True, bufsize=0)
        os.set_blocking(self.process.stdout.fileno(), False)

    def wait(self):
        if self.process is not None:
            while True:
                self._read_progress()
                try:
                    self.process.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    pass

    def close(self):
        if self.process is None:
            return
        # Close only this client. The Monitor finishes its current metadata
        # request and stops the remaining checks when the connection closes.
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
        self._close_output()
        self.process = None

    def label(self, state):
        self._read_progress()
        if self.active:
            self._shown_progress = self.completed, self.total
            return translate('Checking for updates ({completed}/{total})').format(
                completed=self.completed, total=self.total)
        count = len(state['available'])
        return f"{translate('Updates available')} ({count})" if count else translate('Check for updates')

    def notice(self, state):
        if self.active:
            return ''
        if self.failed:
            return translate('The update check could not be completed. Try again later.')
        if self.failed_applications:
            return translate('Some applications could not be checked ({count}). Try again later.').format(
                count=len(self.failed_applications))
        return ''


def select_updates(project, ui, available):
    """Nothing is preselected, including when exactly one update is available."""
    choices = [('all', translate('Select all'))]
    choices += [(str(row['vmid']), f"CT {row['vmid']} · {row['title']}") for row in available]
    defaults = []
    while True:
        try:
            picked = ui.checklist(
                translate('Press Space to select applications to update. Select all includes every application in this list.'),
                choices, defaults, title=translate('Updates available'), ok_label=translate('Update'),
                size=menu_size())
        except UserCancelled:
            return False
        selected = [row for row in available if 'all' in picked or str(row['vmid']) in picked]
        if not selected:
            return False
        defaults = [str(row['vmid']) for row in selected]
        names = '\n'.join(f"  CT {row['vmid']} · {row['title']}" for row in selected)
        if ui.review(names, translate('Update selected OCI applications'),
                     question=translate('Review and update these applications?'), default=False):
            break
    from .management import manage_instance, saved_inventory
    # A change/removal since the check invalidates that application's result.
    checker = UpdateCheck(project)
    still_available = {row['vmid'] for row in checker.status()['available']}
    current = {row['vmid']: row for row in saved_inventory(project)}
    for row in selected:
        vmid = row['vmid']
        if vmid not in still_available or vmid not in current:
            ui.message(translate('An application changed since the update check. Check for updates again.'),
                       translate('Updates available'))
            return False
    for index, row in enumerate(selected, 1):
        # Keep the existing identity checks, backup/storage prompts, update
        # confirmation, coordinated stack update and recovery path.
        heading = f"{translate('Update OCI')} ({index}/{len(selected)}) · {row['title']}"
        if not manage_instance(project, ui, current[row['vmid']], action='update', heading=heading):
            break  # A cancellation or failure never updates later selections.
    return False
