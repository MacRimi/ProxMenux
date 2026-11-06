#!/usr/bin/env python3
"""Give Proxmox's mapped OCI reader access without publishing a private cache.

Ordinary readable templates use the existing zero-copy path. An inaccessible
archive gets a short-lived copy (reflink where supported), owned by root and
readable only by the mapped root group. Never chmod/chown the source image,
its parents, registry credentials, or the caller's process umask.
"""
from contextlib import contextmanager
import errno
import ctypes
import fcntl
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

STAGING_ROOT = Path('/var/tmp')  # Deliberately independent of a private TMPDIR.
FICLONE = 0x40049409


def reader_ids(options):
    """Fresh pct creates use PVE's standard idmap, not a restored custom map."""
    unprivileged = False
    for index, option in enumerate(options):
        if option == '--unprivileged':
            unprivileged = index + 1 == len(options) or options[index + 1] not in ('0', 'false')
        elif option.startswith('--unprivileged='):
            unprivileged = option.partition('=')[2] not in ('0', 'false')
    return (100000, 100000) if unprivileged else (0, 0)


def _allowed(path, uid, gid, required):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return False
    shift = 6 if info.st_uid == uid else 3 if info.st_gid == gid else 0
    return bool((info.st_mode >> shift) & required)


def readable(path, uid, gid):
    """Conservative DAC check: an ACL or symlink may make staging unnecessary,
    but never justify publishing the cache or broadening a storage directory."""
    path = Path(os.path.abspath(path))
    if uid == 0:
        return path.is_file()
    return (_allowed(path, uid, gid, 4)
            and all(_allowed(parent, uid, gid, 1) for parent in path.parents))


def _copy(source, target):
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL), str(source))
        with os.fdopen(source_fd, 'rb', closefd=False) as incoming, target.open('xb') as outgoing:
            try:
                fcntl.ioctl(outgoing.fileno(), FICLONE, incoming.fileno())
            except OSError as error:
                # A confined reader may be allowed normal file I/O while
                # its filesystem denies cloning. Reflink is only an
                # optimization; the open descriptors still enforce access.
                if error.errno not in (errno.EXDEV, errno.EOPNOTSUPP, errno.ENOTTY,
                                      errno.EINVAL, errno.ENOSYS, errno.EPERM):
                    raise
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
    finally:
        os.close(source_fd)


def trusted_staging_root(uid, gid):
    base = STAGING_ROOT
    info = base.lstat()
    ancestors = (base, *base.parents)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or any(p.lstat().st_uid != 0 or
                   (p.lstat().st_mode & 0o022 and not p.lstat().st_mode & stat.S_ISVTX)
                   for p in ancestors)
            or not all(_allowed(p, uid, gid, 1) for p in ancestors)):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(base))
    return base


@contextmanager
def import_archive(source, original, uid, gid):
    source = Path(source)
    if readable(source, uid, gid):
        yield original
        return
    base = trusted_staging_root(uid, gid)
    # mkdtemp is 0700 even if the caller's umask is permissive. Publish group
    # traversal only after the root-owned, read-only copy is complete.
    directory = Path(tempfile.mkdtemp(prefix='proxmenux-oci-import-', dir=base))
    try:
        target = directory / 'image.tar'
        _copy(source.resolve(strict=True), target)
        os.chown(target, 0, gid)
        target.chmod(0o440)
        os.chown(directory, 0, gid)
        directory.chmod(0o750)
        yield str(target)
    finally:
        shutil.rmtree(directory)


def create(vmid, original, source, options):
    uid, gid = reader_ids(options)
    with import_archive(source, original, uid, gid) as archive:
        result = subprocess.run(['pct', 'create', vmid, archive, *options],
                                close_fds=True, umask=0o022)
        return 128 - result.returncode if result.returncode < 0 else result.returncode


def main():
    # A catchable interruption must unwind the staging context. subprocess.run
    # terminates its child when the handler raises; no background pct is orphaned.
    for caught in (signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
        signal.signal(caught, lambda signum, frame: sys.exit(128 + signum))
    if sys.platform == 'linux':
        parent = os.getppid()
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
        if os.getppid() != parent:
            return 143
    try:
        return create(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
