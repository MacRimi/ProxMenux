#!/usr/bin/env python3
"""What the Monitor is told about an update or a recreation.

While the operation runs, every container it touches is stopped, backed up
and started again. Those steps belong to the operation, so the containers are
marked for the Monitor to keep their stop, start and backup notices to itself,
and one notification with the result is sent when it ends.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import socket
import ssl
import time
import urllib.request

MARKERS = Path('/run/proxmenux/oci-operations')
ENDPOINTS = ('http://127.0.0.1:8008/api/internal/oci-event', 'https://127.0.0.1:8008/api/internal/oci-event')


def _write(vmid, data):
    try:
        MARKERS.mkdir(parents=True, exist_ok=True)
        path = MARKERS / str(int(vmid))
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data))
        temporary.replace(path)
    except OSError:
        pass


def begin(vmids):
    started = time.time()
    for vmid in vmids:
        _write(vmid, {'started': started, 'ended': None})


def end(vmids):
    # The notices of the last start can arrive after the operation returned;
    # the Monitor keeps the mark for a short while after `ended`.
    ended = time.time()
    for vmid in vmids:
        _write(vmid, {'started': ended, 'ended': ended})


def notify(event, data):
    """Best effort: the operation never depends on the Monitor answering."""
    payload = json.dumps({'event': event, 'hostname': socket.gethostname(), **data}).encode()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    for url in ENDPOINTS:
        request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=5, context=context if url.startswith('https') else None):
                return True
        except (OSError, ValueError):
            continue
    return False


@contextlib.contextmanager
def operation(vmids, kind, application, primary=None):
    """Mark the containers for the length of an operation and report how it
    ended. `kind` is 'update', 'modify' or 'recreate'."""
    vmids = [int(vmid) for vmid in vmids]
    data = {'app_name': str(application), 'vmid': int(primary if primary is not None else vmids[0]),
            'containers': ', '.join(f'CT {vmid}' for vmid in vmids)}
    begin(vmids)
    try:
        yield
    except BaseException as error:
        end(vmids)
        notify(f'oci_{kind}_failed', {**data, 'reason': str(error) or type(error).__name__})
        raise
    end(vmids)
    notify(f'oci_{kind}_completed', data)
