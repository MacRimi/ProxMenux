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
    carry_records(images.PROJECT_ROOT, shown=True)
    if sys.stdin.isatty():
        console.wait_for_enter(translate('Press Enter to return to the menu...'))
    return completed.returncode == 0


def carry_records(project, mount_stopped=True, vmids=None, verify=False, shown=False):
    """Leave inside each container the copy of its record that a restore on
    another host needs. It is refreshed after every operation. Returns what
    was found for each container. Every installed application is looked at,
    which takes a while with many of them: `shown` says so on the screen."""
    from . import console
    sys.path.insert(0, str(project / 'remote'))
    if shown:
        console.msg_info(translate('Updating the copy of the record...'))
    try:
        import oci_carried_record
        return oci_carried_record.sync(oci_carried_record.instances.ROOT, vmids, mount_stopped, verify)
    except (ImportError, OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return {}
    finally:
        if shown:
            console.stop_spinner()


def recover_automatically(project):
    """Register, without asking, the containers whose record the cluster
    keeps: the ones that migrated to this node. Nothing is started."""
    if not restored_applications(project):
        return
    try:
        subprocess.run([sys.executable, str(project / 'remote/oci_restore_recovery.py'), 'recover', '--automatic'],
                       capture_output=True, timeout=600, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def restored_applications(project):
    """Restored containers of this node that have no record on this host."""
    sys.path.insert(0, str(project / 'remote'))
    try:
        import oci_restore_recovery
        return oci_restore_recovery.pending(oci_restore_recovery.instances.ROOT)
    except (ImportError, OSError, ValueError, RuntimeError):
        return []


def _restored_firewall_rules(project):
    """The host firewall rules the restored host monitors had, as they would
    be on this host."""
    try:
        result = subprocess.run([sys.executable, str(project / 'remote/oci_restore_recovery.py'), 'plan'],
                                capture_output=True, text=True, timeout=300, check=False)
        plans = json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    return [rule for plan in plans if not plan.get('blockers') for rule in plan.get('firewall', [])]


def offer_recovery(project, ui):
    """A restored application cannot be managed until this host knows it
    again: offer to register it before the list is shown."""
    found = restored_applications(project)
    if not found:
        return
    lines = '\n'.join(f"  CT {row['vmid']}  {row['hostname']}" for row in found)
    text = (f"{translate('These containers were restored from a backup and this host has no record of their OCI application:')}"
            f"\n\n{lines}\n\n"
            f"{translate('Until they are registered again they cannot be updated or managed from here. The recovery checks first what prevents their registration; an application with such a problem is not registered. A Rclone mount that has to be enabled again does not prevent it, but then the applications are not started automatically.')}"
            f"\n\n{translate('Recover them now?')}")
    if not ui.confirm(text, default=True):
        return
    command = [sys.executable, str(project / 'remote/oci_restore_recovery.py'), 'recover']
    for rule in _restored_firewall_rules(project):
        if ui.confirm(translate('CT {vmid} is a host monitor and had a rule in the host firewall. Allow TCP port {port} from {subnet} through the firewall of this host? Existing firewall rules are not changed.').format(
                vmid=rule['vmid'], port=rule['port'], subnet=rule['source']), default=False):
            command.extend(['--host-firewall', str(rule['vmid'])])
    if ui.confirm(translate('Start the applications once they are registered? Answer No if the original containers are still running on another host: both would use the same addresses.'),
                  default=False):
        command.append('--start')
    _run_lifecycle(command, translate('Recover restored OCI applications'))


def direct_recovery(project):
    """The recovery of restored applications without the list of the menu: the
    entry ProxMenux Monitor uses for its Recover button."""
    from .ui import interactive_ui
    ui = interactive_ui()
    if os.geteuid() != 0 or not shutil.which('pct'):
        ui.message(translate('This interface runs on the Proxmox node as root. Open OCI manager Apps from the ProxMenux menu on the Proxmox host.'), translate('OCI management'))
        return EXIT_FAILED
    if not restored_applications(project):
        ui.message(translate('No restored OCI application is waiting to be recovered.'), translate('Restored OCI applications'))
        return EXIT_DONE
    offer_recovery(project, ui)
    return EXIT_DONE if not restored_applications(project) else EXIT_FAILED


def interactive_management(project, ui):
    try:
        _interactive_management(project, ui)
    except BlockingIOError:
        ui.message(translate('Another OCI operation is using the instance registry. Wait for it to finish and open this menu again; no container is modified.'),
                   translate('OCI management'))
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
        ui.message(translate('OCI management could not be completed. Check the backend status; no additional cleanup has been authorized.'), translate('OCI management'))


def _clean_orphans(project):
    """Remove, silently, what is left of containers that exist on no node of the cluster."""
    sys.path.insert(0, str(project / 'remote'))
    import oci_instances as instances
    import oci_remove
    try:
        with instances.locked(instances.ROOT):
            oci_remove.sweep_orphans(instances.ROOT)
    except (BlockingIOError, OSError, ValueError):
        pass


def _interactive_management(project, ui):
    if os.geteuid() != 0 or not shutil.which('pct'):
        ui.message(translate('This interface runs on the Proxmox node as root. Open OCI manager Apps from the ProxMenux menu on the Proxmox host.'), translate('OCI management'))
        return
    _clean_orphans(project)
    recover_automatically(project)
    offer_recovery(project, ui)
    carry_records(project, mount_stopped=False, shown=True)
    rows = saved_inventory(project)
    if not rows:
        ui.message(translate('No registered OCI containers are available for selection on this host.'), translate('OCI management'))
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
    manage_instance(project, ui, row)


def set_watchdog(project, vmids, enabled):
    """Turn the watchdog of the applications these containers belong to on or
    off. False when the registry is busy or a record cannot be read."""
    sys.path.insert(0, str(project / 'remote'))
    import oci_instances as instances
    import oci_watchdog
    done = set()
    for vmid in vmids:
        if vmid in done:
            continue
        try:
            done.update(oci_watchdog.set_watchdog(instances.ROOT, vmid, enabled))
        except (OSError, ValueError, KeyError):
            return False
    return True


def _work_backup_ready(project, ui, vmid):
    """Before an operation that backs the application up: when the backup
    does not fit on the system disk of the host, the user chooses the storage
    where it is made. False when there is nowhere to make it."""
    if getattr(ui, 'unattended', False):
        # The engine uses the storage chosen earlier, or says why it stops.
        return True
    sys.path.insert(0, str(project / 'remote'))
    import oci_instances as instances
    import oci_work_backup
    try:
        state = oci_work_backup.status(instances.ROOT, vmid)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return True
    if state['fits'] or state['saved_fits']:
        return True
    lacking = (f"{translate('The backup made before changing the application does not fit on the system disk of the host.')} "
               f"{translate('Needed:')} {oci_work_backup.gib(state['needed'])}. {translate('Free:')} {oci_work_backup.gib(state['free'])}.")
    candidates = sorted(state['candidates'], key=lambda item: item['free'], reverse=True)
    if not candidates:
        ui.message(f"{lacking}\n\n{translate('No other storage of this host that accepts backups has that much free space. Free space and try again; the application was not modified.')}",
                   translate('OCI management'))
        return False
    ui.message(f"{lacking}\n\n{translate('It can be made on another storage of this host. This backup is temporary: it is deleted when the operation ends. The choice is remembered for the next operations of this application.')}",
               translate('OCI management'))
    options = [(item['storage'], f"{item['storage']} - {oci_work_backup.gib(item['free'])} {translate('free')}") for item in candidates]
    selected = ui.choose(translate('Storage for the backup of this operation'), options, options[0][0])
    if selected is None:
        return False
    try:
        oci_work_backup.choose(instances.ROOT, vmid, selected)
    except (OSError, ValueError, KeyError):
        ui.message(translate('Another OCI operation is using the instance registry. Wait for it to finish and open this menu again; no container is modified.'),
                   translate('OCI management'))
        return False
    return True


def _toggle_watchdog(project, ui, vmid, enabled):
    """Ask and change the watchdog of an application from its menu."""
    question = (translate('This application is under watchdog: it is restarted automatically when it crashes. Turn the watchdog off?')
                if enabled else
                translate('Put this application under watchdog? It is restarted automatically when it crashes. A stop or a shutdown you ask for is never undone.'))
    if not ui.confirm(question, not enabled):
        return False
    if not set_watchdog(project, [vmid], not enabled):
        ui.message(translate('Another OCI operation is using the instance registry. Wait for it to finish and open this menu again; no container is modified.'),
                   translate('OCI management'))
        return False
    ui.message(translate('Watchdog disabled.') if enabled else translate('Watchdog enabled: the application is restarted when it crashes.'),
               translate('OCI management'))
    return True


def manage_instance(project, ui, row, action=None, lifecycle_args=()):
    """What the menu does with one instance once it is selected. `action`
    skips the choice of operation, as ProxMenux Monitor does; the extra
    `lifecycle_args` are passed to the program that performs it."""
    # A container that came back from another node or from an older backup
    # carries the record that describes it; the one of this host is not used.
    if carry_records(project, vmids=[row['vmid']], verify=True).get(row['vmid']) == 'stale':
        ui.message(translate('This container was restored or came back from another host after its record on this host was written. Open this menu again to recover it; the container was not modified.'),
                   translate('OCI management'))
        return False
    row = check_selected(project, row)
    if row['reason'] != 'matched':
        ui.message(translate('The selected CT does not match its OCI record. Its configuration will not be modified or deleted.'), translate('OCI management'))
        return False
    if row['stack']:
        return _manage_stack(project, ui, row, action, lifecycle_args)
    # Rebuilding as it is exists only for a multi-container application.
    if action == 'recreate':
        return False
    if not row['pending']:
        if row['status'] != 'installed' or row['reason'] != 'matched':
            ui.message(translate('The instance identity or status must be reviewed before updating.'), translate('OCI management'))
            return False
        sys.path.insert(0, str(project / 'remote'))
        import oci_instances as instances
        record = instances.read(instances.ROOT, row['vmid'])
        watched = record.get('deployment', {}).get('watchdog') is True
        watchdog_label = (translate('Watchdog (on): restart the application when it crashes') if watched
                          else translate('Watchdog (off): restart the application when it crashes'))
        if action is None:
            action = ui.choose(translate('Manage OCI'), [('update', translate('Update the image with the saved configuration')),
                                                         ('modify', translate('Modify: edit resources, network, paths and GPU')),
                                                         ('watchdog', watchdog_label),
                                                         ('remove', translate('Remove: delete the application and its containers'))], 'update')
        if action is None:
            return False
        if action == 'watchdog':
            return _toggle_watchdog(project, ui, row['vmid'], watched)
        if action == 'remove':
            return _remove(project, ui, row['vmid'])
        if not _work_backup_ready(project, ui, row['vmid']):
            return False
        record = instances.read(instances.ROOT, row['vmid'])
        import oci_instance_reconcile as reconcile
        try:
            current_config = instances.command('pct', 'config', str(row['vmid']))
            adoption = reconcile.propose(record, current_config)
        except (OSError, ValueError, RuntimeError) as error:
            ui.message(str(error), translate('Review external OCI changes'))
            return False
        if adoption:
            summary = '\n'.join(adoption['details'])
            if not ui.review(
                    f"{translate('These Proxmox resources were added outside ProxMenux:')}\n\n{summary}\n\n"
                    + translate('They will be added to oci-compose before continuing. Unsupported or changed resources are not imported.'),
                    translate('Review external OCI changes'),
                    question=translate('Include these resources in oci-compose?'), default=False):
                return False
            try:
                record = reconcile.commit(instances.ROOT, row['vmid'], adoption)
            except (OSError, ValueError, RuntimeError) as error:
                ui.message(str(error), translate('Review external OCI changes'))
                return False
        proposal = None
        if action == 'modify':
            from .recreation import edit_recreation
            from .cli import _deployment_summary_text
            from .ui import BacktrackUI, RestartWizard
            wizard = BacktrackUI(ui)
            try:
                while True:
                    try:
                        proposal = edit_recreation(record, wizard)
                        approved = wizard.review(_deployment_summary_text(proposal['candidate']['template'],
                                                 proposal['candidate']['deployment']), translate('Modify OCI'),
                                                 question=translate('Apply these changes?'), default=True)
                        break
                    except RestartWizard:
                        wizard.restart()
                    except ValueError as error:
                        if not wizard.retry_last(error):
                            raise
            finally:
                wizard.close()
            if not approved:
                return False
        elif not ui.review(translate('If the image channel has a new version, the CT is stopped, backed up and verified, and replaced with the new image to update the container. If the update fails after the container was changed, the backup is restored. An update that stops halfway is recovered from the OCI management menu.'),
                           translate('Update OCI'), question=translate('Update now?'), default=True):
            return False
        command = [sys.executable, str(project / 'remote/oci_update_current.py'), str(row['vmid']),
                   *lifecycle_args]
        # Host directories are configured by the user, who knows they are
        # outside the container and its backup.
        if '--acknowledge-external-data' not in command:
            command.append('--acknowledge-external-data')
        title = translate('Modify OCI') if proposal else translate('Update OCI')
        if proposal is None:
            completed = _run_lifecycle(command, title)
        else:
            # Saved environment/secrets must never be passed on the command line.
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as file:
                json.dump(proposal, file)
                file.flush()
                completed = _run_lifecycle(command + ['--proposal', file.name], title)
        if completed and not getattr(ui, 'unattended', False):
            images.offer_removal(ui, [row['vmid']])
        return completed
    action = ui.choose(translate('Interrupted operation'), [('status', translate('View status')),
                                                        ('recover', translate('Recover the previous installation'))], 'status')
    if action is None:
        return False
    if action == 'recover' and not ui.review(
            translate('If the container had already been changed, its previous native backup is restored. Shared host directories are not reverted. The disks of the failed attempt are removed when the cleanup succeeds.'),
            translate('Recover OCI'), question=translate('Recover now?'), default=True):
        return False
    return _run_lifecycle([sys.executable, str(project / 'remote/oci_instance_transaction.py'),
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
                 f"{translate('All of them are targeted for removal.')}", '']
    elif len(members) > 1:
        alone = translate('It cannot be removed on its own, because the application would stop '
                          'working: continuing targets the whole application for removal.')
        text += [f"CT {vmid} {translate('is one of the')} {len(members)} "
                 f"{translate('containers of')} {application}. {alone}", '']
    text += [translate('Containers targeted for removal:'), *lines, '',
             translate('Container data targeted for deletion:'), *volumes]
    if bridge and not oci_remove.bridge_in_use(bridge, set(members)):
        text += ['', f"{translate('Private network targeted for release if no other guest uses it:')} {bridge}"]
    elif bridge:
        text += ['', f"{translate('Private network kept, because other guests still use it:')} {bridge}"]
    if (primary.get('deployment') or {}).get('host_firewall'):
        text += ['', translate('A matching managed host firewall rule may also be removed.')]
    if kept:
        text += ['', translate('Host paths found in container configs or saved records (not targeted for removal):'),
                 *[f'  {path}' for path in kept]]
    else:
        text += ['', translate('No host directories found in the available container configs or saved records.')]
    return '\n'.join(text)


def _remove(project, ui, vmid):
    try:
        summary = _removal_summary(project, vmid)
    except (OSError, ValueError, KeyError) as error:
        ui.message(f"{translate('The removal could not be prepared:')} {error}", translate('Remove OCI'))
        return False
    if not ui.review(summary, translate('Remove OCI'),
                     question=translate('Remove the application? Its container disks are deleted, '
                                        'and only a backup can bring them back.'),
                     default=False):
        return False
    return _run_lifecycle([sys.executable, str(project / 'remote/oci_remove.py'), str(vmid)],
                          translate('Remove OCI'))


def _manage_stack(project, ui, row, action=None, lifecycle_args=()):
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
        if not members:
            ui.message(translate('This stack has no saved members to update.'), translate('OCI stack management'))
            return False
        updatable = not needs_replay or (
                oci_stack_replay.nextcloud_menu_ready(primary) or
                oci_stack_replay.paperless_menu_ready(primary) or
                oci_stack_replay.tandoor_menu_ready(primary) or
                oci_stack_replay.immich_menu_ready(primary))
        if not updatable and action in (None, 'update'):
            ui.message(translate('This stack needs rootfs adaptations that coordinated updates cannot replay yet.'), translate('OCI stack management'))
            if action == 'update':
                return False
        if action is None:
            # A stack that cannot be updated can still be removed.
            options = [('update', translate('Update every container of the application'))] if updatable else []
            options.append(('modify', translate('Modify extra paths and devices')))
            if updatable:
                options.append(('recreate', translate('Recreate every container with its saved configuration')))
            watched = primary.get('deployment', {}).get('watchdog') is True
            options.append(('watchdog', translate('Watchdog (on): restart the application when it crashes') if watched
                            else translate('Watchdog (off): restart the application when it crashes')))
            options.append(('remove', translate('Remove: delete the application and its containers')))
            action = ui.choose(translate('Manage OCI stack'), options, options[0][0])
        if action is None:
            return False
        if action == 'watchdog':
            return _toggle_watchdog(project, ui, primary_id, primary.get('deployment', {}).get('watchdog') is True)
        if action == 'remove':
            return _remove(project, ui, primary_id)
        if action == 'modify':
            from .stack_recreation import modify_stack
            return modify_stack(project, ui, primary, _run_lifecycle)
        if action == 'recreate':
            if not ui.review(translate('All {count} containers of the application will be recreated from their saved '
                                       'image digests (main CT: {vmid}). The stack is stopped, every container is '
                                       'backed up and replaced, then checked. If the operation fails after a container was '
                                       'changed, the backups are restored. An operation that stops halfway is recovered from '
                                       'the OCI management menu.')
                             .format(count=len(members), vmid=primary_id), translate('Recreate OCI stack'),
                             question=translate('Recreate the whole stack?'), default=False):
                return False
        else:
            if not ui.review(translate('All {count} containers of the application are updated together (main CT: {vmid}). '
                                       'If there are new versions, all images are downloaded and verified, the application '
                                       'is stopped, each container is backed up and replaced with its new image. If the operation '
                                       'fails after a container was changed, the backups are restored. An operation that stops '
                                       'halfway is recovered from the OCI management menu.').format(count=len(members), vmid=primary_id),
                    translate('Update OCI stack'), question=translate('Update the whole stack?'), default=True):
                return False
    else:
        if not ui.review(translate('A coordinated operation has a saved journal. Continuing attempts to recover the previous stack where needed, or finish cleanup for a completed operation. Recovery or cleanup can fail.'), translate('Recover OCI stack'),
                question=translate('Recover or complete the operation?'), default=True):
            return False
        import json
        members = json.loads(Path(pending).read_text())['plan']['members']
    if not pending and not _work_backup_ready(project, ui, primary_id):
        return False
    command = [sys.executable, str(project / 'remote/oci_stack_native.py'), str(primary_id)]
    if pending:
        command.append('--recover')
    else:
        command.extend(lifecycle_args)
        if action == 'recreate':
            command.extend(['--operation', 'recreate'])
    if '--acknowledge-external-data' not in command:
        command.append('--acknowledge-external-data')
    title = (translate('Recover OCI stack') if pending else translate('Recreate OCI stack')
             if action == 'recreate' else translate('Update OCI stack'))
    completed = _run_lifecycle(command, title)
    if completed and not pending and not getattr(ui, 'unattended', False):
        images.offer_removal(ui, [int(member['vmid']) for member in members])
    return completed


class UnattendedUI:
    """The answers of a scheduled run: a step with a positive default goes on,
    and one that needs a person (adopting external changes) stops the run."""
    unattended = True

    def __init__(self):
        self.declined = None

    def message(self, text, title=None):
        print(f"{title}: {text}" if title else text, flush=True)

    def review(self, text, title=None, question=None, default=False, **_):
        if not default:
            self.declined = title or question
            self.message(text, title)
        return default

    def confirm(self, text, default=False, **_):
        if not default:
            self.declined = text
        return default

    def choose(self, *_, **__):
        return None

    def ask(self, text, *_, **__):
        raise RuntimeError(f"{translate('A scheduled run cannot answer:')} {text}")


# Exit codes of `manage`, read by ProxMenux Monitor.
EXIT_DONE, EXIT_FAILED, EXIT_NOT_OCI, EXIT_BUSY, EXIT_NEEDS_REVIEW, EXIT_TOO_RECENT = 0, 1, 2, 3, 4, 5


def _image_too_recent(project, vmid, min_age_days):
    """Whether a new image of the instance, or of any member of its stack, is
    younger than the given number of days. An unchanged digest is never too
    recent: there is nothing to install."""
    import datetime
    sys.path.insert(0, str(project / 'remote'))
    import oci_instances as instances
    from oci_installation_state import parse_config, resolve_candidate
    record = instances.read(instances.ROOT, vmid)
    primary_id = record.get('stack_member', {}).get('primary_vmid', vmid)
    primary = instances.read(instances.ROOT, primary_id) if primary_id != vmid else record
    members = [m['vmid'] for m in primary.get('stack', {}).get('members', [])] or [vmid]
    limit = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=min_age_days)
    for member in members:
        member_record = instances.read(instances.ROOT, member)
        reference = member_record['template']['container_contract']['image']['reference']
        arch = parse_config(instances.command('pct', 'config', str(member)))['arch']
        candidate = resolve_candidate(reference, arch)
        installed = (member_record.get('observed', {}).get('image') or {}).get('manifest_digest')
        if candidate.get('manifest_digest') == installed or not candidate.get('created'):
            continue
        created = datetime.datetime.fromisoformat(str(candidate['created']).replace('Z', '+00:00'))
        if created.tzinfo is None:
            created = created.replace(tzinfo=datetime.timezone.utc)
        if created > limit:
            return True
    return False


def direct_management(project, vmid, action, lifecycle_args=(), unattended=False, min_image_age_days=0):
    """One operation on one instance, without the list of the menu: the entry
    ProxMenux Monitor uses for its Update and Modify buttons and for
    scheduled updates."""
    from .ui import interactive_ui
    ui = UnattendedUI() if unattended else interactive_ui()
    if os.geteuid() != 0 or not shutil.which('pct'):
        ui.message(translate('This interface runs on the Proxmox node as root. Open OCI manager Apps from the ProxMenux menu on the Proxmox host.'), translate('OCI management'))
        return EXIT_FAILED
    if unattended and action != 'update':
        ui.message(translate('Only the update of the image runs unattended.'), translate('OCI management'))
        return EXIT_FAILED
    try:
        recover_automatically(project)
        row = next((r for r in saved_inventory(project) if r['vmid'] == vmid), None)
        if row is None:
            ui.message(translate('This container is not a registered OCI instance.'), translate('OCI management'))
            return EXIT_NOT_OCI
        if min_image_age_days > 0 and action == 'update' and _image_too_recent(project, vmid, min_image_age_days):
            ui.message(translate('The new image is more recent than the minimum age set for scheduled updates; it is not installed yet.'), translate('Update OCI'))
            return EXIT_TOO_RECENT
        completed = manage_instance(project, ui, row, action, lifecycle_args)
    except BlockingIOError:
        ui.message(translate('Another OCI operation is using the instance registry. Wait for it to finish and open this menu again; no container is modified.'), translate('OCI management'))
        return EXIT_BUSY
    if unattended and ui.declined:
        return EXIT_NEEDS_REVIEW
    return EXIT_DONE if completed else EXIT_FAILED
