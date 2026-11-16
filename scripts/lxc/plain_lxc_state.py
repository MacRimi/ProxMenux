#!/usr/bin/env python3

# ==========================================================
# ProxMenux - Plain LXC operation state
# ==========================================================
# Author      : Vaso73
# GitHub      : github.com/Vaso73
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 15/11/2026
# ==========================================================
# Description:
# Protect the installation-owned operation journal and uninstall admission.
# ==========================================================
"""Installation-owned journal and fail-closed uninstall checks."""
from contextlib import contextmanager, closing
import fcntl
import os
from pathlib import Path
import sqlite3
import stat

from plain_lxc_spec import LxcError

STATE = Path('/usr/local/share/proxmenux/state/plain-lxc')
RUNTIME = Path('/run/proxmenux-plain-lxc')


def private_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise LxcError('operation_store_unavailable')


@contextmanager
def runtime_lock(*, exclusive=False):
    # Ephemeral lock, separate from the install tree being removed. Never
    # unlink a live lock inode; /run is cleared on reboot. This is not a journal.
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    private_directory(RUNTIME)
    with lock_file(RUNTIME/'controller.lock', exclusive=exclusive):
        yield


@contextmanager
def lock_file(path, *, exclusive=True):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o077:
            raise LxcError('operation_store_unavailable')
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LxcError('operation_controller_active') from None
        yield
    finally:
        os.close(fd)


def installed_directory():
    return STATE


def assert_quiescent_processes():
    # Verify pre-lock controllers and wizards have also exited. Do not print
    # any process arguments (they can belong to unrelated applications).
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal() or int(entry.name) == os.getpid():
            continue
        try:
            args = (entry / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        except PermissionError:
            raise LxcError('operation_controller_active') from None
        if any(value.endswith((b'/plain_lxc.py', b'/plain_lxc_wizard.py', b'/plain_lxc_pve.pl')) for value in args):
            raise LxcError('operation_controller_active')


def pending_count(directory):
    private_directory(directory)
    path = directory / 'operations.sqlite3'
    if not path.exists():
        return 0
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
        raise LxcError('operation_store_unavailable')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if not tables:
            return 0
        if 'operations' not in tables:
            raise LxcError('operation_store_unavailable')
        return db.execute('SELECT count(*) FROM operations WHERE pending=1').fetchone()[0]


def check_uninstall():
    if STATE.is_symlink():
        raise LxcError('operation_store_unavailable')
    if STATE.exists():
        private_directory(STATE)
        with lock_file(STATE / '.controllers.lock'):
            if pending_count(STATE):
                raise LxcError('state_operations_pending')
    assert_quiescent_processes()
    return {'uninstall_safe': True}
