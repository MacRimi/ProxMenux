#!/usr/bin/env python3
"""Show in a container what the host has mounted inside a shared directory.

Proxmox mounts the directory of a mount point alone: a filesystem mounted
inside it, as a network share under /mnt/pve, is left out and the container
finds an empty folder in its place. Next to each of those mount points goes a
raw LXC entry that mounts the same directory with everything inside it, and
keeps following what the host mounts and unmounts while the container runs.
"""
import argparse
import os
from pathlib import Path
import re

from oci_installation_state import parse_config
from oci_ui import translate

ENTRY = re.compile(r'lxc\.mount\.entry: (/\S*) (\S+) none rbind,rslave(,ro)?,create=dir 0 0')
# Read only reaches the directory alone; this takes it to what is inside.
HOOK = re.compile(r"""lxc\.hook\.mount: /bin/sh -c 'mount -o remount,bind,ro=recursive "\$LXC_ROOTFS_MOUNT/(\S+)"'""")
READ_ONLY = "lxc.hook.mount: /bin/sh -c 'mount -o remount,bind,ro=recursive \"$LXC_ROOTFS_MOUNT/{}\"'"
# Trees of the kernel, mounted as the recipe of a host monitor lays them out.
SYSTEM_TREES = ('/proc', '/sys', '/dev', '/run')
# Characters with a meaning of their own in an LXC entry or in the hook.
UNSAFE = re.compile(r'''[\s\\'"$`]''')


def own(line):
    """Whether a configuration line is one of those written here."""
    return bool(ENTRY.fullmatch(line) or HOOK.fullmatch(line))


def groups(config):
    """The lines of each host directory among the mount points, a directory
    before the ones mounted inside it."""
    found = {}
    for key, value in parse_config(config).items():
        if not re.fullmatch(r'mp[0-9]+', key) or not value.startswith('/'):
            continue
        source, *rest = value.split(',')
        options = dict(item.split('=', 1) for item in rest if '=' in item)
        target = options.get('mp', '').strip('/')
        if (not target or UNSAFE.search(source) or UNSAFE.search(target) or source == '/'
                or any(source == tree or source.startswith(tree + '/') for tree in SYSTEM_TREES)):
            continue
        if options.get('ro') == '1':
            found[target] = [f'lxc.mount.entry: {source} {target} none rbind,rslave,ro,create=dir 0 0',
                             READ_ONLY.format(target)]
        else:
            found[target] = [f'lxc.mount.entry: {source} {target} none rbind,rslave,create=dir 0 0']
    return [found[target] for target in sorted(found)]


def without(config):
    """The configuration without the lines written here."""
    return b''.join(line for line in config.splitlines(keepends=True) if not own(line.decode().strip()))


def check(config):
    """Every line of this kind belongs to a mount point of the container, and
    none of a mount point is missing while another of it is there."""
    present = [line for line in config.decode().splitlines() if own(line)]
    expected = [line for group in groups(config) if any(line in present for line in group) for line in group]
    if sorted(present) != sorted(expected):
        raise ValueError(translate('A container mount has a source, backup or permission different from the saved record'))


def follow(vmid):
    """Write the lines of the mount points the container has now, and no
    others. Any snapshot section is left as it is."""
    conf = Path(f'/etc/pve/lxc/{int(vmid)}.conf')
    text = conf.read_text()
    current, _, snapshots = text.partition('\n[')
    kept = [line for line in current.splitlines() if not own(line)]
    wanted = [line for group in groups(current.encode()) for line in group]
    rebuilt = '\n'.join(kept + wanted) + '\n'
    if snapshots:
        rebuilt += '\n[' + snapshots
    if rebuilt != text:
        conf.write_text(rebuilt)
    return wanted


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('follow',))
    parser.add_argument('vmid', type=int)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    follow(args.vmid)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
