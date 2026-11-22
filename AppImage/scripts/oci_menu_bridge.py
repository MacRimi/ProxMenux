"""Root-only local access to the Monitor's existing OCI update checker.

The terminal menu must not run a second registry checker or write sidecars in
another process. Requests execute in the Monitor, using its normal locks,
registration rules, retries and /etc/proxmenux/apps results. No TCP API or
authentication setting is changed.
"""
from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed
import errno
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
import threading

SOCKET = Path('/run/proxmenux-monitor/oci-check.sock')
_check_lock = threading.Lock()
_MAX_REQUEST = 128 * 1024
_CHECK_WORKERS = 16


def _root_peer(connection):
    if not hasattr(socket, 'SO_PEERCRED'):
        return False
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
    return struct.unpack('3i', credentials)[1] == 0


def _applications(request):
    if not isinstance(request, dict) or set(request) != {'applications'}:
        raise ValueError('Invalid request')
    rows = request['applications']
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError('Invalid applications')
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'vmid', 'installation_id'}
                or type(row['vmid']) is not int or not 100 <= row['vmid'] <= 999999999
                or row['vmid'] in seen or not isinstance(row['installation_id'], str)
                or not 1 <= len(row['installation_id']) <= 128):
            raise ValueError('Invalid application')
        seen.add(row['vmid'])
    return rows


def check_applications(module, rows, report):
    """Delegate exclusively to check_app, exactly as the Monitor's Check does."""
    report({'completed': 0, 'total': len(rows)})
    stopped = threading.Event()

    def check_one(row):
        if stopped.is_set():
            return
        vmid = row['vmid']
        record = module._read_oci_record(vmid) or {}
        if (record.get('installation_id') == row['installation_id']
                and record.get('status') == 'installed'
                and not record.get('pending_transaction')
                and not record.get('pending_stack_transaction')
                and not module._oci_secondary_member(record)):
            # Honour dismissals and reuse the Monitor's registration and
            # checker. The menu never invents registrations or notifications.
            module.ensure_oci_registration(vmid)
            sidecar = module.load_sidecar(vmid) or {}
            app = next((app for app in sidecar.get('apps', [])
                        if app.get('installed_via') == 'oci_image'), None)
            if app:
                module.check_app(vmid, app['id'], force=True, notify=False)

    pool = ThreadPoolExecutor(max_workers=_CHECK_WORKERS, thread_name_prefix='oci-check')
    failed = []
    try:
        futures = {pool.submit(check_one, row): row['vmid'] for row in rows}
        for completed, future in enumerate(as_completed(futures), 1):
            try:
                future.result()
            except Exception:
                failed.append(futures[future])  # One failure never stops the other applications.
            report({'completed': completed, 'total': len(rows)})
    finally:
        stopped.set()
        pool.shutdown(wait=True, cancel_futures=True)
    report({'done': True, 'failed': sorted(failed)})


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        if not _root_peer(self.request):
            return
        self.request.settimeout(10)
        acquired = False
        try:
            line = self.rfile.readline(_MAX_REQUEST + 1)
            if len(line) > _MAX_REQUEST or not line.endswith(b'\n'):
                return
            rows = _applications(json.loads(line))
            acquired = _check_lock.acquire(blocking=False)
            if not acquired:
                self.report({'error': 'check_running'})
                return
            check_applications(self.server.apps, rows, self.report)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass  # Closing the menu stops the rest of this request.
        except Exception:
            try:
                self.report({'error': 'check_failed'})
            except OSError:
                pass
        finally:
            if acquired:
                _check_lock.release()

    def report(self, event):
        self.wfile.write((json.dumps(event) + '\n').encode())
        self.wfile.flush()


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    block_on_close = False


def start(apps, path=SOCKET):
    """Start alongside Flask; a private socket avoids web login bypasses."""
    path = Path(path)
    if os.geteuid() != 0:
        return None
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o077:
        raise OSError('Unsafe Monitor runtime directory')
    if path.exists() or path.is_symlink():
        old = path.lstat()
        if not stat.S_ISSOCK(old.st_mode) or old.st_uid != 0:
            raise OSError('Unsafe Monitor socket')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(.2)
            try:
                probe.connect(str(path))
                return None  # Already owned by a running Monitor.
            except OSError as exc:
                if exc.errno not in (errno.ECONNREFUSED, errno.ENOENT):
                    raise
        path.unlink(missing_ok=True)
    server = _Server(str(path), _Handler)
    server.apps = apps
    os.chmod(path, 0o600)
    threading.Thread(target=server.serve_forever, name='oci-menu-check', daemon=True).start()

    def close():
        server.shutdown()
        server.server_close()
        path.unlink(missing_ok=True)
    atexit.register(close)
    return server
