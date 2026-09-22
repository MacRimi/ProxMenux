"""Validate declared volatile mounts and native network sysctl includes."""
import os
from pathlib import Path
import re
import stat
import tempfile

from oci_ui import translate


def sysctl_content(deployment):
    result = []
    seen = set()
    for item in deployment.get('security', {}).get('sysctls', []):
        name, value = item['name'], str(item['value'])
        if (not re.fullmatch(r'net\.(ipv4|ipv6)\.[A-Za-z0-9_.-]+', name)
                or name in seen or not value or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError(translate('Invalid or duplicated network sysctl'))
        seen.add(name)
        result.append(f'lxc.sysctl.{name} = {value}\n')
    return ''.join(result)


def tmpfs_lines(deployment):
    result = []
    targets = set()
    persistent = [m['container_path'].rstrip('/') for m in deployment.get('mounts', [])]
    for item in deployment.get('tmpfs_mounts', []):
        target, size = item['container_path'], item['size_mb']
        if (not re.fullmatch(r'/[A-Za-z0-9_./-]+', target) or '..' in target.split('/')
                or '//' in target or target.endswith('/') or target in ('/etc','/usr','/bin','/lib','/lib64','/sbin','/proc','/sys','/dev','/run')
                or not (target.startswith(('/run/', '/tmp/', '/var/cache/')) or target == '/dev/shm')
                or isinstance(size, bool) or not isinstance(size, int) or size < 1):
            raise ValueError(translate('The tmpfs path or size is outside the supported profile'))
        if any(target == p or target.startswith(p+'/') or p.startswith(target+'/') for p in [*persistent,*targets]):
            raise ValueError(translate('A tmpfs mount overlaps another mount'))
        options = item.get('mount_options', [])
        if not options or any(not re.fullmatch(r'rw|ro|nosuid|nodev|noexec|mode=0[0-7]{3}', opt) for opt in options):
            raise ValueError(translate('Unsupported tmpfs options'))
        if len(options) != len(set(options)) or ('rw' in options and 'ro' in options):
            raise ValueError(translate('Contradictory tmpfs options'))
        targets.add(target)
        result.append(f'tmpfs {target.lstrip("/")} tmpfs {",".join(options)},size={size}M,create=dir 0 0')
    return result


def include_path(vmid):
    return Path(f'/etc/pve/lxc/{int(vmid)}.proxmenux-sysctls')


def check(config, deployment, vmid):
    expected = tmpfs_lines(deployment)
    lines = config.decode().splitlines()
    actual = [line.split(': ',1)[1] for line in lines if line.startswith('lxc.mount.entry: tmpfs ')]
    if sorted(actual) != sorted(expected):
        raise ValueError(translate('The tmpfs mounts of the container differ from the saved record'))
    includes = [line.split(': ',1)[1] for line in lines if line.startswith('lxc.include: ')]
    content = sysctl_content(deployment)
    if includes != ([str(include_path(vmid))] if content else []):
        raise ValueError(translate('The sysctl include is unknown or differs from the saved record'))
    if content:
        path = include_path(vmid)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(translate('The sysctl include is not a safe host file'))
        if path.read_text() != content:
            raise ValueError(translate('The sysctl content was modified outside the saved record'))


def filter_config(config, deployment):
    declared = set(tmpfs_lines(deployment))
    return b''.join(line for line in config.splitlines(keepends=True)
                    if not line.startswith(b'lxc.include: ') and not (
                        line.startswith(b'lxc.mount.entry: ')
                        and line.decode().strip().split(': ',1)[1] in declared))


def check_recovery(config, state):
    plans = [state.get(key, {}).get('deployment', {}) for key in ('record', 'candidate_contract')]
    permitted = {line for plan in plans for line in tmpfs_lines(plan)}
    for line in config.decode().splitlines():
        if line.startswith('lxc.mount.entry: tmpfs ') and line.split(': ', 1)[1] not in permitted:
            raise ValueError(translate('A tmpfs mount is not part of the journal; recovery blocked'))
        if line.startswith('lxc.include: '):
            path = include_path(state['vmid'])
            if line.split(': ', 1)[1] != str(path):
                raise ValueError(translate('An include is not part of the journal; recovery blocked'))
            contents = {sysctl_content(plan) for plan in plans} - {''}
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                    or path.read_text() not in contents):
                raise ValueError(translate('An include was modified outside the journal; recovery blocked'))


def restore(deployment, vmid):
    content = sysctl_content(deployment)
    if not content:
        return
    path = include_path(vmid)
    if path.is_symlink():
        raise ValueError(translate('The sysctl include is not restored over a symbolic link'))
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.oci-sysctl-')
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        # pmxcfs uses fixed permissions; ordinary filesystem fixtures still
        # receive an explicit restrictive mode.
        if path.parent != Path('/etc/pve/lxc'):
            os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
