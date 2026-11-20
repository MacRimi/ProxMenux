#!/usr/bin/env python3

# ==========================================================
# ProxMenux - Plain LXC console creation
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
# Offline first-boot preparation for known units on a stopped rootfs.
# Uses the native controller ownership and mount guards.
# ==========================================================
"""Prepare known first-boot units on a stopped, natively mounted rootfs.

Only host Python runs here. Never chroot into or execute files from a guest.
All filesystem access is relative to no-follow directory descriptors.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

CERT_UNIT = 'proxmox-regenerate-snakeoil.service'
WAIT_UNIT = 'systemd-networkd-wait-online.service'
MANAGED = '90-proxmenux-firstboot.conf'
CERT_DROPIN = b'# Managed by ProxMenux first-boot preparation.\n[Unit]\nWants=ssl-cert.service\nAfter=ssl-cert.service\n'
WAIT_DROPIN = b'# Managed by ProxMenux first-boot preparation.\n[Service]\nExecCondition=/bin/sh /usr/local/libexec/proxmenux-has-network-interface\n'
INTERFACE_HELPER = b'''#!/bin/sh
# Ignore non-interface sysfs files and loopback; missing inventory is an error.
test -d /sys/class/net || exit 255
for link in /sys/class/net/*; do
    test -d "$link" || continue
    test "$link" = /sys/class/net/lo || exit 0
done
exit 1
'''


class PreparationError(Exception):
    pass


class Root:
    def __init__(self, path, uid, gid):
        self.fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.uid, self.gid = uid, gid
        self.created_directories = []
        self.created_files = []

    @contextmanager
    def directory(self, relative, create=False):
        fd = os.dup(self.fd)
        current = []
        try:
            for part in relative.split('/') if relative else []:
                if part in ('', '.', '..'):
                    raise PreparationError('unsafe_path')
                current.append(part)
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, 0o755, dir_fd=fd)
                    self.created_directories.append('/'.join(current))
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        os.fchown(child, self.uid, self.gid)
                        os.fchmod(child, 0o755)
                    except Exception:
                        os.close(child)
                        raise
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)

    def read(self, name):
        parent, leaf = name.rsplit('/', 1)
        try:
            with self.directory(parent) as directory:
                fd = os.open(leaf, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536:
                        raise PreparationError('unsafe_file')
                    data = os.read(fd, 65537)
                    if len(data) > 65536:
                        raise PreparationError('unsafe_file')
                    return data, info
                finally:
                    os.close(fd)
        except FileNotFoundError:
            return None

    def check_dropins(self, unit):
        # Preserve existing administrator overrides; don't guess their semantics.
        for base in ('etc', 'usr/lib', 'lib'):
            if base == 'lib':
                try:
                    if stat.S_ISLNK(os.stat('lib', dir_fd=self.fd, follow_symlinks=False).st_mode):
                        if os.readlink('lib', dir_fd=self.fd) not in ('usr/lib', '/usr/lib'):
                            raise PreparationError('unsafe_path')
                        continue
                except FileNotFoundError:
                    pass
            try:
                with self.directory(base + '/systemd/system/' + unit + '.d') as directory:
                    if any(name.endswith('.conf') and name != MANAGED for name in os.listdir(directory)):
                        raise PreparationError('custom_unit_override')
            except FileNotFoundError:
                pass

    def unit(self, unit):
        for base in ('etc', 'usr/lib', 'lib'):
            value = self.read(base + '/systemd/system/' + unit)
            if value is not None:
                return directives(value[0])
            if base == 'usr/lib':
                # Merged-/usr templates commonly have /lib -> usr/lib. A
                # missing unit there is already a valid absence, not a reason
                # to follow this guest-controlled symlink on the host.
                try:
                    info = os.stat('lib', dir_fd=self.fd, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        break
                except FileNotFoundError:
                    pass
        return None

    def validate_target(self, name, content, mode):
        existing = self.read(name)
        if existing is not None:
            data, info = existing
            if (data != content or stat.S_IMODE(info.st_mode) != mode
                    or (info.st_uid, info.st_gid) != (self.uid, self.gid)):
                raise PreparationError('managed_file_conflict')
        return existing is not None

    def install(self, name, content, mode):
        if self.validate_target(name, content, mode):
            return
        parent, leaf = name.rsplit('/', 1)
        with self.directory(parent, create=True) as directory:
            temporary = '.proxmenux-' + secrets.token_hex(12)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(content)
                    output.flush()
                    os.fchown(output.fileno(), self.uid, self.gid)
                    os.fchmod(output.fileno(), mode)
                    os.fsync(output.fileno())
                    inode = os.fstat(output.fileno()).st_ino
                # Atomic create-only publication, never replace custom files.
                os.link(temporary, leaf, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                self.created_files.append((name, inode))
                os.fsync(directory)
            finally:
                os.unlink(temporary, dir_fd=directory)

    def rollback(self):
        for name, inode in reversed(self.created_files):
            parent, leaf = name.rsplit('/', 1)
            with self.directory(parent) as directory:
                if os.stat(leaf, dir_fd=directory, follow_symlinks=False).st_ino != inode:
                    raise PreparationError('rollback_conflict')
                os.unlink(leaf, dir_fd=directory)
                os.fsync(directory)
        for name in reversed(self.created_directories):
            parent, _, leaf = name.rpartition('/')
            with self.directory(parent) as directory:
                os.rmdir(leaf, dir_fd=directory)


def directives(raw):
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        raise PreparationError('unit_contract_unknown') from None
    section, result = '', {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        elif '=' in line and not line.endswith('\\'):
            key, value = line.split('=', 1)
            result.setdefault((section, key), []).append(value)
        else:
            raise PreparationError('unit_contract_unknown')
    return result


def prepare(path, uid, gid, offline):
    root = Root(path, uid, gid)
    try:
        targets = []
        certificate, ssl = root.unit(CERT_UNIT), root.unit('ssl-cert.service')
        if certificate is not None and ssl is not None:
            if (certificate.get(('Service', 'ExecStart')) != ['make-ssl-cert -f generate-default-snakeoil']
                    or certificate.get(('Unit', 'ConditionFirstBoot')) != ['yes']
                    or certificate.get(('Service', 'Type')) != ['oneshot']
                    or ssl.get(('Service', 'Type')) != ['oneshot']
                    or ssl.get(('Service', 'ExecStart')) != ['-/usr/sbin/make-ssl-cert generate-default-snakeoil --force-overwrite']):
                raise PreparationError('unit_contract_unknown')
            # A locally replaced unit can keep the same ExecStart yet reverse
            # the ordering or add another pre-start command. Don't create a
            # dependency cycle or assume that it is still the native contract.
            for unit in (certificate, ssl):
                if any(section == 'Service' and key not in ('Type', 'ExecStart', 'RemainAfterExit')
                       for section, key in unit):
                    raise PreparationError('unit_contract_unknown')
            if (('Unit', 'After') in certificate
                    or any('ssl-cert.service' in value.split() for value in certificate.get(('Unit', 'Before'), []))
                    or any(
                    key in ssl for key in (('Unit', 'After'), ('Unit', 'Before'), ('Unit', 'Requires'), ('Unit', 'Wants')))):
                raise PreparationError('unit_contract_unknown')
            root.check_dropins(CERT_UNIT)
            root.check_dropins('ssl-cert.service')
            targets.append(('etc/systemd/system/' + CERT_UNIT + '.d/' + MANAGED, CERT_DROPIN, 0o644))
        wait = root.unit(WAIT_UNIT) if offline else None
        if wait is not None:
            if (wait.get(('Service', 'ExecStart')) not in (
                    ['/usr/lib/systemd/systemd-networkd-wait-online'], ['/lib/systemd/systemd-networkd-wait-online'])
                    or wait.get(('Service', 'Type')) != ['oneshot'] or ('Service', 'ExecCondition') in wait):
                raise PreparationError('unit_contract_unknown')
            if any(section == 'Service' and key not in ('Type', 'ExecStart', 'RemainAfterExit') for section, key in wait):
                raise PreparationError('unit_contract_unknown')
            root.check_dropins(WAIT_UNIT)
            targets.extend((('usr/local/libexec/proxmenux-has-network-interface', INTERFACE_HELPER, 0o755),
                            ('etc/systemd/system/' + WAIT_UNIT + '.d/' + MANAGED, WAIT_DROPIN, 0o644)))
        # Preflight every output before writing the first file.
        for name, content, mode in targets:
            root.validate_target(name, content, mode)
        try:
            for name, content, mode in targets:
                root.install(name, content, mode)
        except Exception:
            root.rollback()
            raise
        return {'schema_version': 1, 'prepared_files': [name for name, _, _ in targets]}
    finally:
        os.close(root.fd)


def main():
    try:
        if (os.geteuid() != 0 or len(sys.argv) != 5
                or not re.fullmatch(r'/var/lib/lxc/[1-9][0-9]{2,8}/rootfs', sys.argv[1])
                or any(not re.fullmatch(r'[1-9][0-9]{0,9}', value) for value in sys.argv[2:4])
                or any(int(value) > 4294967294 for value in sys.argv[2:4]) or sys.argv[4] not in ('0', '1')):
            raise PreparationError('invalid_preparation_request')
        result = prepare(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] == '1')
        print(json.dumps(result))
        return 0
    except (PreparationError, OSError) as error:
        print(json.dumps({'schema_version': 1, 'error': str(error) if isinstance(error, PreparationError) else 'preparation_io_failed'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
