"""Advanced ownership choices for standalone OCI host directories."""
from pathlib import Path
import sys

from .i18n import translate


def backend():
    remote = str(Path(__file__).resolve().parents[2] / 'remote')
    if remote not in sys.path:
        sys.path.insert(0, remote)
    import oci_mount_idmap
    return oci_mount_idmap


def eligible(deployment):
    if (deployment.get('deployment_kind') or deployment.get('replay_profile')
            or deployment.get('native_config') or deployment.get('host_monitor')
            or not deployment.get('security', {}).get('unprivileged', True)):
        return []
    system = ('/dev', '/proc', '/sys', '/run', '/var/run', '/etc', '/usr', '/bin', '/sbin', '/lib', '/lib64')
    files = {'/etc/localtime', '/etc/timezone', '/etc/hosts', '/etc/resolv.conf'}
    return [m for m in deployment.get('mounts', []) if m.get('type') == 'host-bind'
            and m.get('container_path') not in files
            and not any(str(m.get(key, '')) == p or str(m.get(key, '')).startswith(p + '/')
                        for key in ('source', 'container_path') for p in system)]


def application_ids(deployment, profile, config=None):
    return backend().application_ids(deployment, {'proxmox': {'installer_profile': profile}}, config)


def edit_mapping(ui, mount, deployment, profile, config=None):
    """Return only a fully validated answer; cancellation leaves the draft alone."""
    uid, gid = application_ids(deployment, profile, config)
    selected = ui.choose(
        translate('Mount user mapping (idmap)') + f": {mount['container_path']}", [
            ('keep', translate('Keep the current mapping')),
            ('default', translate('Use the standard container mapping')),
            ('root', translate('Map container root to a host user and group')),
            ('application', translate('Map a container user to a host user and group') + f' ({uid}:{gid})'),
            ('custom', translate('Enter a custom idmap')),
        ], 'keep')
    if selected is None or selected == 'keep':
        return
    if selected == 'default':
        mount.pop('idmap', None)
        return
    if selected == 'custom':
        text = ui.ask(translate('idmap (example: u:0:2000:1;g:0:2000:1)'),
                      mount.get('idmap', ''))
    elif selected in ('root', 'application'):
        if selected == 'root':
            uid, gid = 0, 0
        else:
            uid = str(ui.ask(translate('Container user ID (UID)'), str(uid))).strip()
            gid = str(ui.ask(translate('Container group ID (GID)'), str(gid))).strip()
        host_uid = str(ui.ask(translate('Host user ID (UID)'), '2000')).strip()
        host_gid = str(ui.ask(translate('Host group ID (GID)'), '2000')).strip()
        text = f'u:{uid}:{host_uid}:1;g:{gid}:{host_gid}:1'
    else:
        return
    normalized = backend().normalize_idmap(text, unprivileged=True)
    if normalized:
        checked = dict(mount, idmap=normalized)
        backend().check_deployment(dict(deployment, mounts=[checked]),
                                   {'proxmox': {'installer_profile': profile}}, config)
        mount['idmap'] = normalized
    else:
        mount.pop('idmap', None)


def configure(ui, deployment, profile, *, ask=False, config=None):
    mounts = eligible(deployment)
    if not mounts:
        return
    if ask and not ui.confirm(translate('Configure user mapping (idmap) for host directories?'), False):
        return
    ui.info(translate('idmap changes how file owners are seen through this mount. Existing files are not re-owned. Host directories are not included in Proxmox backups.'))
    while True:
        choices = [(str(n), f"{m['container_path']}  ·  {m.get('idmap') or translate('standard mapping')}")
                   for n, m in enumerate(mounts)]
        choices.append(('done', translate('Done')))
        selected = ui.choose(translate('Choose a host directory to map'), choices, 'done')
        if selected is None or selected == 'done':
            return
        if selected.isdigit() and int(selected) < len(mounts):
            edit_mapping(ui, mounts[int(selected)], deployment, profile, config)
