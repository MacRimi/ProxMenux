#!/usr/bin/env python3
"""Clone a FUSE mount from an LXC namespace into the Proxmox host namespace."""

from __future__ import annotations

import ctypes
import os
import platform
import sys


AT_FDCWD = -100
AT_EMPTY_PATH = 0x1000
AT_RECURSIVE = 0x8000
CLONE_NEWNS = 0x00020000
MOVE_MOUNT_F_EMPTY_PATH = 0x00000004
MOUNT_ATTR_RDONLY = 0x00000001
OPEN_TREE_CLONE = 1

SYSCALLS = {
    "x86_64": (428, 429, 442),
    "amd64": (428, 429, 442),
    "aarch64": (428, 429, 442),
    "arm64": (428, 429, 442),
}


class MountAttr(ctypes.Structure):
    _fields_ = [
        ("attr_set", ctypes.c_uint64),
        ("attr_clr", ctypes.c_uint64),
        ("propagation", ctypes.c_uint64),
        ("userns_fd", ctypes.c_uint64),
    ]


def fail(step: str) -> None:
    error = ctypes.get_errno()
    raise OSError(error, f"{step}: {os.strerror(error)}")


def main() -> int:
    if len(sys.argv) != 5 or sys.argv[4] not in {"rw", "ro"}:
        print(f"usage: {sys.argv[0]} PID SOURCE TARGET rw|ro", file=sys.stderr)
        return 2
    machine = platform.machine().lower()
    if machine not in SYSCALLS:
        print(f"unsupported host architecture: {machine}", file=sys.stderr)
        return 2
    open_tree_nr, move_mount_nr, mount_setattr_nr = SYSCALLS[machine]
    pid, source, target, mode = sys.argv[1:]
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.setns.argtypes = (ctypes.c_int, ctypes.c_int)
    libc.setns.restype = ctypes.c_int

    host_ns = os.open("/proc/self/ns/mnt", os.O_RDONLY | os.O_CLOEXEC)
    host_root = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    ct_ns = os.open(f"/proc/{pid}/ns/mnt", os.O_RDONLY | os.O_CLOEXEC)
    ct_root = os.open(f"/proc/{pid}/root", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        if libc.setns(ct_ns, CLONE_NEWNS) != 0:
            fail("enter container namespace")
        os.fchdir(ct_root)
        os.chroot(".")
        os.chdir("/")
        tree = libc.syscall(
            open_tree_nr,
            AT_FDCWD,
            os.fsencode(source),
            OPEN_TREE_CLONE | os.O_CLOEXEC,
        )
        if tree < 0:
            fail("clone source mount tree")
        try:
            if mode == "ro":
                attributes = MountAttr(attr_set=MOUNT_ATTR_RDONLY)
                result = libc.syscall(
                    mount_setattr_nr,
                    tree,
                    ctypes.c_char_p(b""),
                    AT_EMPTY_PATH | AT_RECURSIVE,
                    ctypes.byref(attributes),
                    ctypes.sizeof(attributes),
                )
                if result != 0:
                    fail("make cloned mount tree read-only")
            if libc.setns(host_ns, CLONE_NEWNS) != 0:
                fail("return to host namespace")
            os.fchdir(host_root)
            os.chroot(".")
            os.chdir("/")
            result = libc.syscall(
                move_mount_nr,
                tree,
                ctypes.c_char_p(b""),
                AT_FDCWD,
                os.fsencode(target),
                MOVE_MOUNT_F_EMPTY_PATH,
            )
            if result != 0:
                fail("publish mount tree")
        finally:
            os.close(tree)
    finally:
        for descriptor in (ct_root, ct_ns, host_root, host_ns):
            os.close(descriptor)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
