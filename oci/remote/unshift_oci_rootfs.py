#!/usr/bin/env python3
"""Convert an OCI rootfs imported with the default LXC idmap to host IDs."""

from __future__ import annotations

import os
import stat
import sys

from oci_ui import log, translate


def iter_paths(root: str):
    yield root
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        for name in names:
            yield os.path.join(directory, name)
        for name in files:
            yield os.path.join(directory, name)


def note(text: str) -> None:
    """Progress goes to the run log; without one, to stderr."""
    path = os.environ.get("OCI_LOG")
    try:
        if path:
            log(path, text)
            return
    except OSError:
        pass
    print(text, file=sys.stderr, flush=True)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"{translate('Usage:')} {sys.argv[0]} ROOTFS", file=sys.stderr)
        return 2
    root = os.path.realpath(sys.argv[1])
    if not root.startswith("/var/lib/lxc/") or not root.endswith("/rootfs"):
        print(f"{translate('Refusing an unexpected rootfs path:')} {root}", file=sys.stderr)
        return 2
    root_device = os.lstat(root).st_dev
    shifted = 0
    for path in iter_paths(root):
        metadata = os.lstat(path)
        if metadata.st_dev != root_device:
            continue
        uid = metadata.st_uid - 100000 if 100000 <= metadata.st_uid < 165536 else metadata.st_uid
        gid = metadata.st_gid - 100000 if 100000 <= metadata.st_gid < 165536 else metadata.st_gid
        if uid == metadata.st_uid and gid == metadata.st_gid:
            continue
        attributes: dict[str, bytes] = {}
        for name in os.listxattr(path, follow_symlinks=False):
            attributes[name] = os.getxattr(path, name, follow_symlinks=False)
        os.chown(path, uid, gid, follow_symlinks=False)
        for name, value in attributes.items():
            os.setxattr(path, name, value, follow_symlinks=False)
        shifted += 1
        if shifted % 10000 == 0:
            note(f"  Owners converted: {shifted}")
    note(f"OCI rootfs converted to privileged: {shifted} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
