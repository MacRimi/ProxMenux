"""Explicit native LXC devices beyond an application's curated profile."""
import copy
import re
from pathlib import Path

from .i18n import translate
from .ui import UserCancelled


GPU_NODE = re.compile(r'/dev/dri/(?:renderD|card)[0-9]+|/dev/kfd')
USB_NODE = re.compile(r'/dev/(?:ttyUSB[0-9]+|ttyACM[0-9]+|bus/usb/[0-9]{3}/[0-9]{3})')
CORAL_NODE = re.compile(r'/dev/apex_[0-9]+')


def ask_extra_devices(ui, devices, unprivileged, allow_coral=False):
    """Keep manual attachments separate from image-owned GPU profiles."""
    result = list(devices)
    while ui.confirm(translate('Add another GPU or USB device manually?'), False):
        options = [
            ('gpu', translate('Intel/AMD DRM node (device only)')),
            ('nvidia', translate('NVIDIA runtime (device and host driver libraries)')),
            ('usb', translate('USB or serial device node')),
        ]
        if allow_coral:
            options.append(('coral', translate('Coral PCIe/M.2 device node')))
        kind = ui.choose(translate('Device to attach'), options)
        if kind is None:
            raise UserCancelled(translate('Device configuration cancelled'))
        if kind == 'nvidia':
            if any(item.get('kind') == 'nvidia-runtime' for item in result):
                raise ValueError(translate('NVIDIA is already attached'))
            result.append({'id': 'manual-nvidia', 'kind': 'nvidia-runtime',
                           'device_selection': 'all-requested-by-compose',
                           'runtime_mode': 'dynamic' if unprivileged else 'static'})
            continue
        if kind == 'gpu':
            candidates = sorted(str(path) for path in Path('/dev/dri').glob('renderD*'))
            default = candidates[0] if candidates else '/dev/dri/renderD128'
            path = ui.ask(translate('Host DRM node (e.g. /dev/dri/renderD128)'), default)
            valid = GPU_NODE.fullmatch(path)
        elif kind == 'usb':
            path = ui.ask(translate('Host USB node (e.g. /dev/ttyACM0 or /dev/bus/usb/003/004)'),
                          '/dev/ttyACM0')
            valid = USB_NODE.fullmatch(path)
        else:
            path = ui.ask(translate('Host Coral node (e.g. /dev/apex_0)'), '/dev/apex_0')
            valid = CORAL_NODE.fullmatch(path)
        if not valid:
            raise ValueError(translate('Choose a specific supported GPU or USB node'))
        if any(item.get('host_path') == path for item in result):
            raise ValueError(translate('This device is already attached'))
        if kind == 'usb' and '/bus/usb/' in path:
            ui.info(translate('USB bus numbers can change after reconnecting or rebooting.'))
        result.append({'id': 'manual-' + path.removeprefix('/dev/').replace('/', '-'),
                       'kind': 'character-device', 'host_path': path, 'container_path': path,
                       'mode': '0660', 'deny_write': False,
                       'gid_strategy': 'host-device-gid'})
    return result


def device_permissions(image, devices, existing=None):
    if existing:
        return existing
    repository = image.split('@', 1)[0].rsplit(':', 1)[0]
    if repository.startswith(('lscr.io/linuxserver/', 'linuxserver/', 'docker.io/linuxserver/')) and any(
            item.get('kind') == 'character-device' for item in devices):
        return {'strategy': 'linuxserver-native-init', 'service_user': 'abc',
                'environment': 'ATTACHED_DEVICES_PERMS',
                'paths': 'all-resolved-selected-character-devices'}
    return None


def ask_stack_extra_devices(ui, services):
    """Ask once per device, then select the stack members that need it."""
    devices = ask_extra_devices(ui, [], True)
    if not devices:
        return
    options = [(service['name'], service['name']) for service in services]
    for device in devices:
        selected = ui.checklist(
            f"{translate('Containers that will receive this device')}: "
            f"{device.get('host_path', 'NVIDIA')}", options,
            [service['name'] for service in services if service.get('main')] or [options[-1][0]])
        if not selected or set(selected) - {name for name, _ in options}:
            raise ValueError(translate('Select at least one stack container'))
        for service in services:
            if service['name'] not in selected:
                continue
            plan = service['deployment']
            existing = plan.setdefault('devices', [])
            if any(item.get('host_path') == device.get('host_path') if device.get('host_path')
                   else item.get('kind') == 'nvidia-runtime' for item in existing):
                raise ValueError(translate('This device is already attached'))
            member_device = copy.deepcopy(device)
            if member_device['kind'] == 'nvidia-runtime':
                member_device['runtime_mode'] = (
                    'dynamic' if plan.get('security', {}).get('unprivileged', True) else 'static')
            existing.append(member_device)
            image = service['template']['container_contract']['image']['reference']
            plan['device_permissions'] = device_permissions(
                image, existing, plan.get('device_permissions'))
