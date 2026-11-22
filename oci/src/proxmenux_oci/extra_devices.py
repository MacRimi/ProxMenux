"""Explicit native LXC devices beyond an application's curated profile."""
import copy
import re
from pathlib import Path
import sys

from . import host
from .i18n import translate
from .ui import ReadableTags, UserCancelled


GPU_NODE = re.compile(r'/dev/dri/(?:renderD|card)[0-9]+|/dev/kfd')
USB_NODE = re.compile(r'/dev/(?:ttyUSB[0-9]+|ttyACM[0-9]+|bus/usb/[0-9]{3}/[0-9]{3})')
CORAL_NODE = re.compile(r'/dev/apex_[0-9]+')


def usb_passthrough():
    """The module that passes a USB device by its identity, shared with the
    helpers that apply and check it."""
    remote = str(Path(__file__).resolve().parents[2] / 'remote')
    if remote not in sys.path:
        sys.path.insert(0, remote)
    import oci_usb_passthrough
    return oci_usb_passthrough


def by_identity(device, keep_missing=False):
    """A USB device chosen by its current node, recorded by what it is, so the
    container keeps it when the kernel numbers it again. Any other device is
    returned as it is, and so is a recorded one that is not plugged in now
    when ``keep_missing`` is set."""
    try:
        return usb_passthrough().converted(device)
    except OSError:
        if keep_missing:
            return device
        raise ValueError(f"{translate('The USB device is not connected')}: {device.get('host_path')}") from None


def device_node(device):
    """The host node a device has now: its path, or for a USB device recorded
    by its identity the node it was given this time (None when unplugged)."""
    if device.get('host_path'):
        return device['host_path']
    usb = usb_passthrough()
    return usb.present(device) if usb.recorded(device) else None


def device_label(device):
    """How a device reads in a summary."""
    if not usb_passthrough().recorded(device):
        return device.get('host_path') or device.get('kind', '-')
    if device.get('tree'):
        return '/dev/bus/usb'
    identity = device['usb']
    name = f"USB {identity['vendor']}:{identity['product']} · {identity['port']}"
    return f"{device['container_path']} ({name})" if 'serial_link' in device else name


def choose_usb_device(ui, title, default=None, attached=()):
    """A USB device of the host picked by its name, or a node typed by hand."""
    options = [(row['path'], f"{row['name']} · {translate(row['kind'])}")
               for row in host.usb_devices() if row['path'] not in attached]
    manual_prompt = translate('Host USB node (e.g. /dev/ttyACM0 or /dev/bus/usb/003/004)')
    if not options:
        ui.message(translate('No selectable USB device was found. Type the host node by hand.'))
        return ui.ask(manual_prompt, default or '/dev/ttyACM0')
    options.append(('manual', translate('Another node, typed by hand')))
    selected = ui.choose(title, ReadableTags(options), default if default in dict(options) else options[0][0])
    if selected is None:
        raise UserCancelled(translate('Device configuration cancelled'))
    return ui.ask(manual_prompt, default or '/dev/ttyACM0') if selected == 'manual' else selected


def ask_extra_devices(ui, devices, unprivileged, allow_coral=False, kinds=('gpu', 'nvidia', 'usb')):
    """Keep manual attachments separate from image-owned GPU profiles."""
    result = list(devices)
    while ui.confirm(translate('Add another GPU or USB device manually?'), False):
        options = [option for option in (
            ('gpu', translate('Intel/AMD DRM node (device only)')),
            ('nvidia', translate('NVIDIA runtime (device and host driver libraries)')),
            ('usb', translate('USB or serial device node')),
        ) if option[0] in kinds]
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
            path = choose_usb_device(ui, translate('USB device to attach'),
                                     attached={device_node(item) for item in result})
            valid = USB_NODE.fullmatch(path)
        else:
            path = ui.ask(translate('Host Coral node (e.g. /dev/apex_0)'), '/dev/apex_0')
            valid = CORAL_NODE.fullmatch(path)
        if not valid:
            raise ValueError(translate('Choose a specific supported GPU or USB node'))
        if any(device_node(item) == path for item in result):
            raise ValueError(translate('This device is already attached'))
        if kind == 'usb' and '/bus/usb/' in path:
            ui.info(translate('USB devices are passed by their identity: the container keeps them after a reboot, and restarts when one is reconnected.'))
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
    devices = [by_identity(device) for device in ask_extra_devices(ui, [], True)]
    if not devices:
        return
    options = [(service['name'], service['name']) for service in services]
    for device in devices:
        label = 'NVIDIA' if device.get('kind') == 'nvidia-runtime' else device_label(device)
        selected = ui.checklist(
            f"{translate('Containers that will receive this device')}: {label}", options,
            [service['name'] for service in services if service.get('main')] or [options[-1][0]])
        if not selected or set(selected) - {name for name, _ in options}:
            raise ValueError(translate('Select at least one stack container'))
        for service in services:
            if service['name'] not in selected:
                continue
            plan = service['deployment']
            existing = plan.setdefault('devices', [])
            if any(item.get('kind') == 'nvidia-runtime' if device.get('kind') == 'nvidia-runtime'
                   else device_node(item) == device_node(device) for item in existing):
                raise ValueError(translate('This device is already attached'))
            member_device = copy.deepcopy(device)
            if member_device['kind'] == 'nvidia-runtime':
                member_device['runtime_mode'] = (
                    'dynamic' if plan.get('security', {}).get('unprivileged', True) else 'static')
            existing.append(member_device)
            image = service['template']['container_contract']['image']['reference']
            plan['device_permissions'] = device_permissions(
                image, existing, plan.get('device_permissions'))
