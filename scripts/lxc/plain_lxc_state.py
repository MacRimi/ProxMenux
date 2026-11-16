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
# Protect the local operation journal and coordinate controllers with
# migration and uninstall. Explicit offline migration preserves current
# records using an atomic Linux exchange, with no guest or PVE actions.
# ==========================================================
"""Installation-owned state and explicit, reversible offline migration.

No Proxmox calls, guest changes, SQL replay or restored database snapshots.
"""
from contextlib import contextmanager, closing
import fcntl
import os
from pathlib import Path
import sqlite3
import stat
import ctypes

from plain_lxc_spec import LxcError

STATE = Path('/usr/local/share/proxmenux/state/plain-lxc')
LEGACY_STATE = Path('/var/lib/proxmenux/plain-lxc')
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


def installed_directory(*, legacy=False):
    old_present = LEGACY_STATE.exists() or LEGACY_STATE.is_symlink()
    alias = LEGACY_STATE.is_symlink() and LEGACY_STATE.resolve() == STATE
    if legacy:
        if not old_present or alias or STATE.exists():
            raise LxcError('state_migration_conflict')
        return LEGACY_STATE
    if old_present and not alias:
        raise LxcError('state_migration_required')
    if alias and not STATE.is_dir():
        raise LxcError('state_migration_conflict')
    return STATE


def assert_quiescent_processes():
    # Pre-option controllers do not know our locks. Explicit migration also
    # requires their installed command and wizard to have exited. Do not print
    # any process arguments (they can belong to unrelated applications).
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal() or int(entry.name) == os.getpid():
            continue
        try:
            args = (entry / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        except PermissionError:
            raise LxcError('state_migration_busy') from None
        if any(value.endswith((b'/plain_lxc.py', b'/plain_lxc_wizard.py', b'/plain_lxc_pve.pl')) for value in args):
            raise LxcError('state_migration_busy')


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


def exchange_directories(source, destination):
    """Linux RENAME_EXCHANGE (linux/fs.h), no interval with a missing source."""
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        exchange = libc.renameat2
    except AttributeError:
        raise LxcError('state_migration_unavailable') from None
    exchange.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    exchange.restype = ctypes.c_int
    first = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        second = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            if exchange(first, os.fsencode(source.name), second, os.fsencode(destination.name), 2):
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error))
        finally:
            os.close(second)
    finally:
        os.close(first)


def migrate_state(source=LEGACY_STATE, destination=STATE, *, rollback=False):
    """Run explicitly with all controllers closed; retain a fail-closed alias.

    Rename is atomic on one filesystem. Cross-filesystem installs fail intact
    instead of publishing a copied/stale DB. Old binaries reject the symlink
    and cannot silently create a second operation store. Rollback moves the
    current DB back; it never restores an earlier snapshot over newer records.
    """
    assert_quiescent_processes()
    if not source.is_absolute() or not destination.is_absolute():
        raise LxcError('state_migration_conflict')
    if rollback:
        if not source.is_symlink() or source.resolve() != destination.resolve():
            raise LxcError('state_migration_conflict')
        active = destination
    else:
        if source.is_symlink() or destination.exists() or destination.is_symlink():
            raise LxcError('state_migration_conflict')
        active = source
    private_directory(active)
    with lock_file(active / '.controllers.lock'):
        if pending_count(active):
            raise LxcError('state_operations_pending')
        db_path = active / 'operations.sqlite3'
        if db_path.exists():
            with closing(sqlite3.connect(db_path.as_uri() + '?mode=rw', uri=True, timeout=1)) as db:
                db.execute('BEGIN EXCLUSIVE')
                has_operations = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operations'").fetchone()
                if has_operations and db.execute('SELECT count(*) FROM operations WHERE pending=1').fetchone()[0]:
                    raise LxcError('state_operations_pending')
                assert_quiescent_processes()
                db.commit()
        if rollback:
            exchange_directories(source,destination)
            destination.unlink()  # the former compatibility alias, never a DB
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(destination)
            try:
                exchange_directories(source,destination)
            except BaseException:
                if destination.is_symlink() and os.readlink(destination) == str(destination):
                    destination.unlink()
                raise
    return {'directory': str(source if rollback else destination), 'migrated': True}


def check_uninstall():
    seen = set()
    for directory in (STATE, LEGACY_STATE):
        if not directory.exists():
            if directory.is_symlink():
                raise LxcError('state_migration_conflict')
            continue
        actual = directory.resolve()
        if actual in seen:
            continue
        seen.add(actual)
        if directory.is_symlink() and not (directory == LEGACY_STATE and actual == STATE):
            raise LxcError('state_migration_conflict')
        if pending_count(actual):
            raise LxcError('state_operations_pending')
        if directory == LEGACY_STATE and not directory.is_symlink():
            raise LxcError('state_migration_required')
    assert_quiescent_processes()
    return {'uninstall_safe': True}


def remove_legacy_alias():
    check_uninstall()
    if LEGACY_STATE.is_symlink():
        # check_uninstall has verified the exact, owned compatibility alias.
        LEGACY_STATE.unlink()
    return {'legacy_alias_removed': True}
