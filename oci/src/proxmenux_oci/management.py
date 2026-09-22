"""Local PVE instance selection and explicit recovery UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from . import images
from .i18n import N_, source_text, translate

STATUS_LABELS = {'installed': N_('installed'), 'failed': N_('failed'), 'updating': N_('updating'),
                 'recovering': N_('recovering'), 'installing': N_('installing'),
                 'assembling': N_('assembling')}


def public_row(record, decision):
    return {'vmid': record['vmid'], 'hostname': record.get('deployment', {}).get('hostname',
            f'OCI {record["vmid"]}'),
            'title': source_text(record.get('template', {}).get('catalog_ui', {}).get('title')),
            'image': str(record.get('template', {}).get('container_contract', {}).get('image', {})
                         .get('reference', '')).split('@', 1)[0].rsplit('/', 1)[-1],
            'status': record['status'], 'reason': decision.get('reason'),
            'pending': bool(record.get('pending_transaction')),
            'stack_pending': bool(record.get('pending_stack_transaction')),
            'stack': bool(record.get('stack') or record.get('stack_member')
                          or record.get('native_stack_intent'))}


def inventory(project, progress=None):
    sys.path.insert(0, str(project / 'remote'))
    import oci_instances as instances
    with instances.locked(instances.ROOT):
        resources = json.loads(instances.command('pvesh', 'get', '/cluster/resources',
            '--type', 'vm', '--output-format', 'json'))
        registered = set()
        for directory in instances.ROOT.iterdir():
            if directory.name.isdecimal() and instances.has_contract(instances.ROOT, int(directory.name)):
                vmid = int(directory.name)
                registered.add(vmid)
                record = instances.read(instances.ROOT, vmid)
                registered.update(member['vmid'] for member in record.get('stack', {}).get('members', []))
        configs = {}
        selected = [row for row in resources if row.get('type') == 'lxc'
                    and int(row['vmid']) in registered]
        for index, row in enumerate(selected, 1):
            if progress:
                progress(f"{translate('Checking OCI')} {index}/{len(selected)}: CT {row['vmid']}...")
            if row.get('type') == 'lxc':
                configs[int(row['vmid'])] = instances.command('pvesh', 'get',
                    f'/nodes/{row["node"]}/lxc/{row["vmid"]}/config', '--output-format', 'json')
        decisions = instances.reconcile(instances.ROOT, resources, configs)
        return [public_row(instances.read(instances.ROOT, d['vmid']), d)
                for d in decisions if d['action'] == 'keep']


def saved_inventory(project):
    """Open the selector without invoking Proxmox or changing saved contracts."""
    sys.path.insert(0, str(project / 'remote'))
    import oci_instances as instances
    with instances.locked(instances.ROOT):
        rows = []
        for directory in sorted(instances.ROOT.iterdir(), key=lambda path: path.name.zfill(10)):
            if not (directory.name.isdecimal() and instances.has_contract(instances.ROOT, int(directory.name))
                    and instances.guest_exists(int(directory.name))):
                continue
            record = instances.read(instances.ROOT, int(directory.name))
            row = public_row(record, {'reason': 'not-yet-checked'})
            row['title'] = row['title'] or _stack_title(instances, record)
            if row['hostname'] == f"OCI {record['vmid']}":
                row['hostname'] = _config_hostname(record['vmid']) or row['hostname']
            rows.append(row)
        return rows


def _stack_title(instances, record):
    """Members of a dedicated stack keep a minimal template: name them after the stack."""
    primary_id = record.get('stack_member', {}).get('primary_vmid', record['vmid'])
    try:
        primary = record if primary_id == record['vmid'] else instances.read(instances.ROOT, primary_id)
    except (OSError, ValueError, KeyError):
        return ''
    for source in (primary.get('stack', {}), primary.get('native_stack_intent', {})):
        title = source_text(source.get('template', {}).get('catalog_ui', {}).get('title'))
        if title:
            role = record.get('deployment', {}).get('role') or record.get('stack_member', {}).get('name')
            return f"{title} · {role}" if role and primary_id != record['vmid'] else title
    return ''


def _config_hostname(vmid):
    for path in Path('/etc/pve/nodes').glob(f'*/lxc/{vmid}.conf'):
        try:
            for line in path.read_text().splitlines():
                if line.startswith('hostname:'):
                    return line.split(':', 1)[1].strip()
                if line.startswith('['):
                    break
        except OSError:
            continue
    return ''


def check_selected(project, row):
    """Validate only the chosen container; lifecycle backends validate its stack."""
    sys.path.insert(0, str(project / 'remote'))
    import oci_instances as instances
    with instances.locked(instances.ROOT):
        record = instances.read(instances.ROOT, row['vmid'])
        config = instances.command('pct', 'config', str(row['vmid']))
        marker = instances.identity(config)
        reason = 'matched' if marker == record['installation_id'] else 'identity-unconfirmed'
        return public_row(record, {'reason': reason})


def _run_lifecycle(command, title):
    """The lifecycle programs print their own steps: they run on a clean screen
    and their result stays readable until the user returns to the menu."""
    from . import console
    console.show_logo()
    console.msg_title(title)
    environment = dict(os.environ, OCI_SPINNER='1' if sys.stdout.isatty() else '0')
    completed = subprocess.run(command, env=environment, check=False)
    console.wait_for_enter(translate('Press Enter to return to the menu...'))
    return completed.returncode == 0


def interactive_management(project, ui):
    try:
        _interactive_management(project, ui)
    except BlockingIOError:
        ui.message(translate('Another OCI operation is using the instance registry. Wait for it to finish and open this menu again; no container is modified.'),
                   translate('OCI management'))
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
        ui.message(translate('OCI management could not be completed. Check the backend status; no additional cleanup has been authorized.'), translate('OCI management'))


def _interactive_management(project, ui):
    if os.geteuid() != 0 or not shutil.which('pct'):
        ui.message(translate('This interface runs on the Proxmox node as root. Open proxmenux-oci.sh on the Proxmox host.'), translate('OCI management'))
        return
    rows = saved_inventory(project)
    if not rows:
        ui.message(translate('No OCI instances are registered.'), translate('OCI management'))
        return
    # Same layout as the catalog lists; only an unusual state is shown.
    tag_width = max(len(str(r['vmid'])) for r in rows)
    header = f" {'CT':<{tag_width + 2}}{translate('Application')[:32]:<32} {translate('Image')}"
    options = []
    for r in rows:
        line = f"{(r['title'] or r['hostname'])[:32]:<32} "
        if r['status'] == 'installed':
            line += r['image'][:30]
        else:
            line += f"\\Z1{translate(STATUS_LABELS.get(r['status'], r['status']))}\\Zn"
        options.append((str(r['vmid']), f"{line:<72}"))
    selection = ui.choose(header, options, size=(22, 75, 15), colors=True,
                          title=translate('Manage installed OCI applications'))
    if selection is None:
        return
    row = next(r for r in rows if str(r['vmid']) == selection)
    row = check_selected(project, row)
    if row['reason'] != 'matched':
        ui.message(translate('The selected CT does not match its OCI record. Its configuration will not be modified or deleted.'), translate('OCI management'))
        return
    if row['stack']:
        _manage_stack(project, ui, row)
        return
    if not row['pending']:
        if row['status'] != 'installed' or row['reason'] != 'matched':
            ui.message(translate('The instance identity or status must be reviewed before updating.'), translate('OCI management'))
            return
        action = ui.choose(translate('Manage OCI'), [('update', translate('Update the image with the saved configuration')),
                                                     ('recreate', translate('Recreate: edit resources, network, paths and GPU')),
                                                     ('remove', translate('Remove: delete the application and its containers'))], 'update')
        if action is None:
            return
        sys.path.insert(0, str(project / 'remote'))
        import oci_instances as instances
        record = instances.read(instances.ROOT, row['vmid'])
        if action == 'remove':
            _remove(project, ui, row['vmid'])
            return
        proposal = None
        if action == 'recreate':
            from .recreation import edit_recreation
            from .cli import _deployment_summary_text
            proposal = edit_recreation(record, ui)
            if not ui.review(_deployment_summary_text(proposal['candidate']['template'],
                             proposal['candidate']['deployment']), translate('Recreate OCI'),
                             question=translate('Recreate with these options?'), default=True):
                return
        elif not ui.review(translate('The current image of the saved channel will be checked and downloaded. Resources, paths and GPU are kept. The CT is stopped during the replacement and a native backup is created first.'),
                           translate('Update OCI'), question=translate('Update now?'), default=True):
            return
        command = [sys.executable, str(project / 'remote/oci_update_current.py'), str(row['vmid'])]
        desired = proposal['candidate'] if proposal else record
        if any(m['type'] == 'host-bind' for m in desired['deployment'].get('mounts', [])):
            if not ui.confirm(translate('Shared host data is not reverted by the backup. Continue?'), False):
                return
            command.append('--acknowledge-external-data')
        title = translate('Recreate OCI') if proposal else translate('Update OCI')
        if proposal is None:
            completed = _run_lifecycle(command, title)
        else:
            # Saved environment/secrets must never be passed on the command line.
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as file:
                json.dump(proposal, file)
                file.flush()
                completed = _run_lifecycle(command + ['--proposal', file.name], title)
        if completed:
            images.offer_removal(ui, [row['vmid']])
        return
    action = ui.choose(translate('Interrupted operation'), [('status', translate('View status')),
                                                        ('recover', translate('Recover the previous installation'))], 'status')
    if action is None:
        return
    if action == 'recover' and not ui.review(
            translate('The previous native backup will be restored. Shared host directories are not reverted. Displaced disks are kept.'),
            translate('Recover OCI'), question=translate('Recover now?'), default=True):
        return
    _run_lifecycle([sys.executable, str(project / 'remote/oci_instance_transaction.py'),
                    action, str(row['vmid'])],
                   translate('Recover OCI') if action == 'recover' else translate('OCI management'))


def _removal_summary(project, vmid):
    """What the removal deletes and what it keeps, read from the containers
    themselves. A container of a multi-container application is never removed
    on its own."""
    sys.path.insert(0, str(project / 'remote'))
    import oci_instances as instances
    import oci_remove
    from oci_installation_state import parse_config
    primary_id, primary, members = oci_remove.members_of(instances.ROOT, vmid)
    titles = [(primary.get('template') or {}).get('catalog_ui', {}).get('title'),
              ((primary.get('stack') or {}).get('template') or {}).get('catalog_ui', {}).get('title')]
    application = next((source_text(title) for title in titles if source_text(title)), f'CT {primary_id}')
    lines, volumes, kept = [], [], []
    for member in members:
        try:
            record = instances.read(instances.ROOT, member)
        except (OSError, ValueError, KeyError):
            record = {}
        config = oci_remove.guest_config(member)
        cfg = parse_config(config) if config else {}
        name = (cfg.get('hostname') or (record.get('stack_member') or {}).get('name')
                or record.get('deployment', {}).get('hostname') or '')
        lines.append(f'  CT {member}  {name}')
        size = re.search(r'size=(\S+)', cfg.get('rootfs', ''))
        volumes.append(f"  CT {member}: rootfs {size.group(1) if size else '-'}")
        for key, value in cfg.items():
            if not re.fullmatch(r'mp[0-9]+', key):
                continue
            source, *rest = value.split(',')
            options = dict(item.split('=', 1) for item in rest if '=' in item)
            target = options.get('mp', '')
            if source.startswith('/'):
                kept.append(source)
            else:
                volumes.append(f"  CT {member}: {target} ({options.get('size', '-')})")
    for path in oci_remove.host_directories(instances.ROOT, members):
        if path not in kept:
            kept.append(path)
    bridge = oci_remove.private_bridge(primary)
    text = []
    if len(members) > 1 and vmid == primary_id:
        text += [f"{application} {translate('runs in')} {len(members)} {translate('containers')}. "
                 f"{translate('All of them are removed.')}", '']
    elif len(members) > 1:
        alone = translate('It cannot be removed on its own, because the application would stop '
                          'working: continuing removes the whole application.')
        text += [f"CT {vmid} {translate('is one of the')} {len(members)} "
                 f"{translate('containers of')} {application}. {alone}", '']
    text += [translate('Containers that are removed:'), *lines, '',
             translate('Data that is deleted with them:'), *volumes]
    if bridge:
        text += ['', f"{translate('Private network of the application that is released:')} {bridge}"]
    if kept:
        text += ['', translate('Host directories that are kept, with their content:'),
                 *[f'  {path}' for path in kept]]
    else:
        text += ['', translate('No host directory is used by this application.')]
    return '\n'.join(text)


def _remove(project, ui, vmid):
    try:
        summary = _removal_summary(project, vmid)
    except (OSError, ValueError, KeyError) as error:
        ui.message(f"{translate('The removal could not be prepared:')} {error}", translate('Remove OCI'))
        return
    if not ui.review(summary, translate('Remove OCI'),
                     question=translate('Remove it? The data of its containers cannot be recovered afterwards.'),
                     default=False):
        return
    _run_lifecycle([sys.executable, str(project / 'remote/oci_remove.py'), str(vmid)],
                   translate('Remove OCI'))


def _manage_stack(project, ui, row):
    sys.path.insert(0, str(project / 'remote'))
    import oci_instances as instances
    record = instances.read(instances.ROOT, row['vmid'])
    primary_id = record.get('stack_member', {}).get('primary_vmid', row['vmid'])
    primary = instances.read(instances.ROOT, primary_id)
    pending = primary.get('pending_stack_transaction')
    if not pending:
        members = primary.get('stack', {}).get('members', [])
        import oci_stack_replay
        needs_replay = any(m.get('native_stack_intent') or
                m.get('deployment', {}).get('rootfs_adaptation_replay_required') for m in members)
        if not members or (needs_replay and not (
                oci_stack_replay.nextcloud_menu_ready(primary) or
                oci_stack_replay.paperless_menu_ready(primary) or
                oci_stack_replay.tandoor_menu_ready(primary) or
                oci_stack_replay.immich_menu_ready(primary))):
            ui.message(translate('This stack requires replaying specific rootfs adaptations. Coordinated updates are not yet enabled for it.'), translate('OCI stack management'))
            return
        action = ui.choose(translate('Manage OCI stack'),
                           [('update', translate('Update every container of the application')),
                            ('remove', translate('Remove: delete the application and its containers'))], 'update')
        if action is None:
            return
        if action == 'remove':
            _remove(project, ui, primary_id)
            return
        if not ui.review(f"{translate('All stack members are updated together. Main CT:')} {primary_id}, "
                f"{translate('members:')} {len(members)}. "
                f"{translate('All images are downloaded and verified first, and native backups are taken with the stack stopped. Contracts are published after the whole set is checked. If anything fails, all members are recovered.')}",
                translate('Update OCI stack'), question=translate('Update the whole stack?'), default=True):
            return
    else:
        if not ui.review(translate('A coordinated operation is pending. The whole previous stack will be recovered, not only the selected member. If the operation already finished, the cleanup of its markers is completed.'), translate('Recover OCI stack'),
                question=translate('Recover or complete the operation?'), default=True):
            return
        import json
        members = json.loads(Path(pending).read_text())['plan']['members']
    command = [sys.executable, str(project / 'remote/oci_stack_native.py'), str(primary_id)]
    if pending:
        command.append('--recover')
    if any(mount['type'] == 'host-bind' for member in members
           for mount in member.get('deployment', {}).get('mounts', [])):
        if not ui.confirm(translate('Shared host data is not reverted by the backups. Continue?'), False):
            return
        command.append('--acknowledge-external-data')
    completed = _run_lifecycle(command, translate('Recover OCI stack') if pending else translate('Update OCI stack'))
    if completed and not pending:
        images.offer_removal(ui, [int(member['vmid']) for member in members])
