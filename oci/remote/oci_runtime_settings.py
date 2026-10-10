"""Validate declared volatile mounts and native network sysctl includes."""
import os
from pathlib import Path
import re
import stat
import tempfile

import oci_nested_mounts as nested_mounts
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
    # Proxmox does not take this setting in the configuration of a container.
    if (deployment.get('security', {}).get('options') or {}).get('no_new_privileges'):
        result.append('lxc.no_new_privs = 1\n')
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


# /etc/pve/lxc is the folder of the local node only; this one is the same on
# every node of a cluster, so a migrated container still finds its include.
CLUSTER_DIR = Path('/etc/pve/proxmenux')


def include_path(vmid):
    return CLUSTER_DIR / f'{int(vmid)}.sysctls'


def legacy_include_path(vmid):
    """Where installations made before the cluster folder keep the include."""
    return Path(f'/etc/pve/lxc/{int(vmid)}.proxmenux-sysctls')


# A host monitor shares the process and network namespaces of the host. Proxmox
# takes those two settings from an include, the same for every monitor.
HOST_MONITOR_INCLUDES = (CLUSTER_DIR / 'host-monitor', Path('/etc/pve/lxc/proxmenux-host-monitor'))
HOST_MONITOR_CONTENT = 'lxc.namespace.share.pid = 1\nlxc.namespace.share.net = 1\n'


def host_monitor_include(includes):
    """Whether the includes are the one of a host monitor, unchanged."""
    if len(includes) != 1 or Path(includes[0]) not in HOST_MONITOR_INCLUDES:
        return False
    try:
        return Path(includes[0]).read_text() == HOST_MONITOR_CONTENT
    except OSError:
        return False


def seccomp_path(vmid):
    """The seccomp profile the installer writes for a container that asks for
    it relaxed."""
    return Path(f'/etc/pve/lxc/{int(vmid)}.proxmenux-seccomp')


def check(config, deployment, vmid):
    expected = tmpfs_lines(deployment)
    lines = config.decode().splitlines()
    actual = [line.split(': ',1)[1] for line in lines if line.startswith('lxc.mount.entry: tmpfs ')]
    if sorted(actual) != sorted(expected):
        raise ValueError(translate('The tmpfs mounts of the container differ from the saved record'))
    includes = [line.split(': ',1)[1] for line in lines if line.startswith('lxc.include: ')]
    if deployment.get('host_monitor'):
        if not host_monitor_include(includes):
            raise ValueError(translate('The host monitor include is unknown or differs from the saved record'))
        return
    content = sysctl_content(deployment)
    allowed = [[str(include_path(vmid))], [str(legacy_include_path(vmid))]] if content else [[]]
    if includes not in allowed:
        raise ValueError(translate('The sysctl include is unknown or differs from the saved record'))
    if content:
        path = Path(includes[0])
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(translate('The sysctl include is not a safe host file'))
        if path.read_text() != content:
            raise ValueError(translate('The sysctl content was modified outside the saved record'))


FILE_BIND = re.compile(r'(/\S+) \S+ none bind,create=file(,ro)? 0 0')


def file_binds(config):
    """The host files mounted in the container: {source: read only}. Proxmox
    takes a directory as a mount point and a single file as a raw LXC entry,
    so these are not among the mount points."""
    found = {}
    for line in config.decode().splitlines():
        match = FILE_BIND.fullmatch(line.split(': ', 1)[1]) if line.startswith('lxc.mount.entry: ') else None
        if match:
            found[match.group(1)] = bool(match.group(2))
    return found


def filter_config(config, deployment):
    """The configuration without the entries of the mounts the deployment
    declares itself: what is left belongs to the acceleration profile."""
    config = nested_mounts.without(config)
    declared = set(tmpfs_lines(deployment))
    files = {m['source'] for m in deployment.get('mounts', []) if m.get('type') == 'host-bind'}

    def own(line):
        entry = line.decode().strip().split(': ', 1)[1]
        match = FILE_BIND.fullmatch(entry)
        return entry in declared or bool(match and match.group(1) in files)
    return b''.join(line for line in config.splitlines(keepends=True)
                    if not line.startswith(b'lxc.include: ') and not (
                        line.startswith(b'lxc.mount.entry: ') and own(line)))


def check_recovery(config, state):
    plans = [state.get(key, {}).get('deployment', {}) for key in ('record', 'candidate_contract')]
    permitted = {line for plan in plans for line in tmpfs_lines(plan)}
    for line in config.decode().splitlines():
        if line.startswith('lxc.mount.entry: tmpfs ') and line.split(': ', 1)[1] not in permitted:
            raise ValueError(translate('A tmpfs mount is not part of the journal; recovery blocked'))
        if line.startswith('lxc.include: '):
            path = Path(line.split(': ', 1)[1])
            if any(plan.get('host_monitor') for plan in plans) and host_monitor_include([str(path)]):
                continue
            if path not in (include_path(state['vmid']), legacy_include_path(state['vmid'])):
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
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.oci-sysctl-')
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        # pmxcfs uses fixed permissions; ordinary filesystem fixtures still
        # receive an explicit restrictive mode.
        if Path('/etc/pve') not in path.parents:
            os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
