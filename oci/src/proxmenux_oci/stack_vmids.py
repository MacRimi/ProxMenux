"""Optional per-service VMIDs in the advanced stack wizard."""
from pathlib import Path
import subprocess
import sys

from .i18n import translate
from .ui import UserCancelled


def backend():
    remote = str(Path(__file__).resolve().parents[2] / 'remote')
    if remote not in sys.path:
        sys.path.insert(0, remote)
    import oci_stack_vmids
    return oci_stack_vmids


def configure(ui, template, deployment):
    if not ui.confirm(translate('Choose a VMID for each service?'), False):
        return
    services = (deployment['services'] if deployment['deployment_kind'] == 'generic-multi-lxc-stack'
                else [dict(s, offset=s['vmid_offset']) for s in template['compose_stack']['services']])
    services = sorted(services, key=lambda s: s['offset'])
    allocator = backend()
    # Find a free consecutive proposal only after the user opts in. This does
    # not reserve IDs; the installer checks them again under its allocation lock.
    try:
        proposed = allocator.allocate(deployment, services)
    except (OSError, ValueError, subprocess.SubprocessError):
        # An occupied base can still lead to a valid, completely custom choice.
        base = deployment.get('base_vmid')
        proposed = {s['name']: base + s['offset'] if base is not None else '' for s in services}
    while True:
        selected = {}
        try:
            for service in services:
                name = service['name']
                answer = ui.ask(translate('VMID for service:') + ' ' + name, str(proposed[name]))
                if answer is None:
                    raise UserCancelled(translate('VMID selection cancelled'))
                selected[name] = allocator.vmid(answer)
            selected = allocator.validate_selection(selected, services)
        except ValueError as error:
            ui.message(str(error))
            continue
        deployment['service_vmids'] = selected
        return


def ask_service_vmids(ui, template, base_vmid, mode, services=None):
    if mode == 'default':
        return {}
    deployment = {'base_vmid': base_vmid,
                  'deployment_kind': 'generic-multi-lxc-stack' if services is not None else 'dedicated-stack'}
    if services is not None:
        deployment['services'] = services
    configure(ui, template, deployment)
    return ({'service_vmids': deployment['service_vmids']} if 'service_vmids' in deployment else {})
