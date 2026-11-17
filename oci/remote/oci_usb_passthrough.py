#!/usr/bin/env python3
"""Pass a USB device to a container by what it is, not by its number.

The kernel numbers a USB device each time it finds it, so after a reboot or a
reconnection /dev/bus/usb/BBB/DDD and /dev/ttyUSBn can name another device, or
none, and a container that lists that node cannot start. A device recorded
here is found by its vendor, product, serial number and physical port:

- a USB device: the container gets the host USB tree and the right to open
  USB devices, and a udev rule of the host lets it write to that device only;
- a USB serial adapter: its stable link under /dev/serial is mounted at the
  path the application expects, with a udev rule for that adapter.

The configuration lines written here are recognized, checked and left out of
the comparisons the way those of the nested mounts are.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess

from oci_ui import translate

USB_ALLOW = 'lxc.cgroup2.devices.allow: c 189:* rwm'
USB_MOUNT = 'lxc.mount.entry: /dev/bus/usb dev/bus/usb none bind,optional,create=dir'
# ttyACM and ttyUSB, the two kinds of USB serial adapters.
SERIAL_MAJORS = (166, 188)
SERIAL_ALLOW = re.compile(r'lxc\.cgroup2\.devices\.allow: c (166|188):\* rwm')
SERIAL_MOUNT = re.compile(r'lxc\.mount\.entry: (/dev/serial/by-(?:id|path)/[A-Za-z0-9._:+-]+) '
                          r'(dev/[A-Za-z0-9._/-]+) none bind,optional,create=file')
USB_NODE = re.compile(r'/dev/bus/usb/[0-9]{3}/[0-9]{3}')
TTY_NODE = re.compile(r'/dev/tty(?:USB|ACM)[0-9]+')
STABLE_LINK = re.compile(r'/dev/serial/by-(?:id|path)/[A-Za-z0-9._:+-]+')
CONTAINER_PATH = re.compile(r'/dev/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*')
HEX4 = re.compile(r'[0-9a-f]{4}')
PORT = re.compile(r'[0-9]+-[0-9]+(?:\.[0-9]+)*')
SERIAL = re.compile(r'[A-Za-z0-9._-]{1,64}')
RULES = Path('/etc/udev/rules.d')
CONF_DIR = Path('/etc/pve/lxc')
SYS = Path('/sys')
DEV = Path('/dev')


def rule_path(vmid):
    return RULES / f'99-proxmenux-oci-{int(vmid)}.rules'


def recorded(device):
    """Whether a device of a deployment is passed the way this module does."""
    return isinstance(device, dict) and device.get('kind') == 'usb'


def handled(path):
    """Whether a host node is a USB device this module passes by identity."""
    return isinstance(path, str) and bool(USB_NODE.fullmatch(path) or TTY_NODE.fullmatch(path)
                                          or STABLE_LINK.fullmatch(path))


def _read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ''


def _device_number(node):
    info = os.stat(node)
    return os.major(info.st_rdev), os.minor(info.st_rdev)


def _usb_directory(node):
    """The sysfs directory of the USB device a node belongs to."""
    major, minor = _device_number(node)
    directory = (SYS / 'dev/char' / f'{major}:{minor}').resolve()
    while directory != directory.parent and not (directory / 'idVendor').is_file():
        directory = directory.parent
    if not (directory / 'idVendor').is_file():
        raise ValueError(f"{translate('The selected device is not a USB device')}: {node}")
    return directory


def _identity(directory):
    serial = _read(directory / 'serial')
    # A serial number made of one repeated character is a placeholder that
    # every unit of a model carries; it tells nothing apart.
    real = bool(SERIAL.fullmatch(serial)) and len(set(serial)) > 1
    value = {'vendor': _read(directory / 'idVendor').lower(), 'product': _read(directory / 'idProduct').lower(),
             'port': directory.name}
    if real:
        value['serial'] = serial
    if not HEX4.fullmatch(value['vendor']) or not HEX4.fullmatch(value['product']) or not PORT.fullmatch(value['port']):
        raise ValueError(translate('The USB device does not report a valid identity'))
    return value


def _stable_link(tty):
    """The link under /dev/serial that names this adapter after a reboot: by
    its serial number when it has one, otherwise by its port."""
    target = os.path.realpath(tty)
    for kind in ('by-id', 'by-path'):
        folder = DEV / 'serial' / kind
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            link = folder / name
            if os.path.realpath(link) == target and STABLE_LINK.fullmatch(f'/dev/serial/{kind}/{name}'):
                return f'/dev/serial/{kind}/{name}'
    raise ValueError(f"{translate('The serial adapter has no stable name under /dev/serial')}: {tty}")


def entry(device_id, host_path, container_path=None):
    """The deployment entry of a USB device chosen by its current node."""
    if not handled(host_path):
        raise ValueError(f"{translate('Choose a specific supported GPU or USB node')}: {host_path}")
    node = os.path.realpath(host_path)
    value = {'id': device_id, 'kind': 'usb', 'usb': _identity(_usb_directory(node))}
    if TTY_NODE.fullmatch(node):
        # The application finds the adapter where it was told to look: its
        # stable name, or the node it had when it was chosen.
        target = container_path or host_path
        if not CONTAINER_PATH.fullmatch(target) or '..' in target:
            raise ValueError(f"{translate('Invalid device path:')} {target}")
        link = host_path if STABLE_LINK.fullmatch(host_path) else _stable_link(node)
        value.update(serial_link=link, container_path=target, major=_device_number(node)[0])
        if value['major'] not in SERIAL_MAJORS:
            raise ValueError(f"{translate('The selected device is not a USB serial adapter')}: {host_path}")
    else:
        value['container_path'] = '/dev/bus/usb'
    return value


def tree_entry(device_id):
    """The whole USB tree, for an application that uses whatever USB devices
    the host has, such as audio outputs. No udev rule widens their access."""
    return {'id': device_id, 'kind': 'usb', 'tree': True, 'container_path': '/dev/bus/usb'}


def converted(device):
    """A device recorded by its node, recorded instead the way this module
    passes it; any other device as it is. Raises OSError when a USB node is
    not there to read its identity from."""
    path = device.get('host_path')
    if (device.get('kind', 'character-device') == 'character-device' and handled(path)
            and not device.get('drm_vendor_ids') and 'uid' not in device
            and not device.get('append_host_device_gid_to_environment')):
        return entry(device['id'], path, device.get('container_path'))
    if device.get('kind') == 'character-device-tree' and path == '/dev/bus/usb':
        return tree_entry(device['id'])
    return device


def migrated(devices):
    """The devices of an installation made when USB devices were passed by
    their node: those plugged in now are passed by their identity from here
    on; one that is not there keeps its entry."""
    result = []
    for device in devices:
        try:
            result.append(converted(device))
        except (OSError, ValueError):
            result.append(device)
    return result


def _valid(device):
    if device.get('tree'):
        if device.get('container_path') != '/dev/bus/usb' or 'usb' in device or 'serial_link' in device:
            raise ValueError(translate('The USB device record is not valid'))
        return
    usb = device.get('usb') or {}
    if not (HEX4.fullmatch(str(usb.get('vendor', ''))) and HEX4.fullmatch(str(usb.get('product', '')))
            and PORT.fullmatch(str(usb.get('port', '')))
            and ('serial' not in usb or SERIAL.fullmatch(str(usb['serial'])))):
        raise ValueError(translate('The USB device does not report a valid identity'))
    if 'serial_link' in device:
        if (not STABLE_LINK.fullmatch(str(device['serial_link'])) or device.get('major') not in SERIAL_MAJORS
                or not CONTAINER_PATH.fullmatch(str(device.get('container_path', '')))
                or '..' in str(device.get('container_path'))):
            raise ValueError(translate('The USB serial adapter record is not valid'))
    elif device.get('container_path') != '/dev/bus/usb':
        raise ValueError(translate('The USB device record is not valid'))


def lines(deployment):
    """The configuration lines the USB devices of a deployment need."""
    devices = [device for device in deployment.get('devices', []) if recorded(device)]
    for device in devices:
        _valid(device)
    result = []
    if any('serial_link' not in device for device in devices):
        result += [USB_ALLOW, USB_MOUNT]
    for major in sorted({device['major'] for device in devices if 'serial_link' in device}):
        result.append(f'lxc.cgroup2.devices.allow: c {major}:* rwm')
    seen = set()
    for device in devices:
        if 'serial_link' in device:
            target = device['container_path'].lstrip('/')
            if target in seen:
                raise ValueError(f"{translate('This device is already attached')}: {device['container_path']}")
            seen.add(target)
            result.append(f"lxc.mount.entry: {device['serial_link']} {target} none bind,optional,create=file")
    return result


def own(line):
    """Whether a configuration line is one of those written here."""
    line = line.strip()
    return line in (USB_ALLOW, USB_MOUNT) or bool(SERIAL_ALLOW.fullmatch(line) or SERIAL_MOUNT.fullmatch(line))


def without(config):
    """The configuration without the lines written here."""
    return b''.join(line for line in config.splitlines(keepends=True) if not own(line.decode()))


def check(config, deployment):
    """The lines written here are exactly those the recorded USB devices need."""
    current = config.decode().split('\n[', 1)[0]
    present = [line.strip() for line in current.splitlines() if own(line)]
    if sorted(present) != sorted(lines(deployment)):
        raise ValueError(translate('The USB devices of the container do not match the saved record'))


def rules(vmid, deployment):
    """The udev rule that lets the container write to its devices, and to no
    other USB device of the host."""
    devices = [device for device in deployment.get('devices', []) if recorded(device) and not device.get('tree')]
    if not devices:
        return ''
    text = [f'# ProxMenux OCI {int(vmid)}: USB devices passed to the container']
    for device in devices:
        _valid(device)
        if device.get('tree'):
            continue
        usb = device['usb']
        # A tty matches the attributes of the USB device above it (ATTRS);
        # the USB device node matches its own (ATTR).
        attr = 'ATTRS' if 'serial_link' in device else 'ATTR'
        match = [f'{attr}{{idVendor}}=="{usb["vendor"]}"', f'{attr}{{idProduct}}=="{usb["product"]}"']
        if usb.get('serial'):
            match.append(f'{attr}{{serial}}=="{usb["serial"]}"')
        head = 'SUBSYSTEM=="tty"' if 'serial_link' in device else 'SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device"'
        text.append(', '.join([head, *match, 'MODE="0666"']))
    return '\n'.join(text) + '\n'


PAIR = re.compile(r'ATTRS?\{idVendor\}=="([0-9a-f]{4})", ATTRS?\{idProduct\}=="([0-9a-f]{4})"')


def _pairs(text):
    """The vendor and product pairs a rule names, with the subsystem of each."""
    found = set()
    for line in text.splitlines():
        match = PAIR.search(line)
        if match:
            found.add(('tty' if line.startswith('SUBSYSTEM=="tty"') else 'usb', *match.groups()))
    return found


def _udev(*args):
    subprocess.run(['udevadm', *args], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _retrigger(pairs, action):
    """Let udev apply the rules again to these devices only. A device no
    longer named by a rule needs an add event to get its default permission
    back; a change event leaves the one it had."""
    for subsystem, vendor, product in sorted(pairs):
        if subsystem == 'tty':
            _udev('trigger', f'--action={action}', '--subsystem-match=tty', f'--property-match=ID_VENDOR_ID={vendor}')
        else:
            _udev('trigger', f'--action={action}', '--subsystem-match=usb',
                  f'--attr-match=idVendor={vendor}', f'--attr-match=idProduct={product}')
    if pairs:
        _udev('settle', '--timeout=10')


def write_rules(vmid, deployment):
    """Write, replace or remove the udev rule of a container."""
    path = rule_path(vmid)
    text = rules(vmid, deployment)
    old = path.read_text() if path.exists() else ''
    if text == old:
        return False
    if text:
        temporary = path.with_name(f'.{path.name}.tmp')
        temporary.write_text(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    else:
        path.unlink(missing_ok=True)
    _udev('control', '--reload-rules')
    _retrigger(_pairs(old) - _pairs(text), 'add')
    _retrigger(_pairs(text), 'change')
    return True


def apply(vmid, deployment):
    """Write the lines and the udev rule of the recorded USB devices, and no
    others. Any snapshot section is left as it is."""
    wanted = lines(deployment)
    conf = CONF_DIR / f'{int(vmid)}.conf'
    text = conf.read_text()
    current, separator, snapshots = text.partition('\n[')
    kept = [line for line in current.splitlines() if not own(line)]
    rebuilt = '\n'.join(kept + wanted) + '\n'
    if separator:
        rebuilt += '\n[' + snapshots
    if rebuilt != text:
        conf.write_text(rebuilt)
    write_rules(vmid, deployment)
    return wanted


def remove(vmid):
    """Remove the udev rule of a container that is gone, and give its devices
    their default permission back."""
    path = rule_path(vmid)
    if path.exists():
        old = path.read_text()
        path.unlink()
        _udev('control', '--reload-rules')
        _retrigger(_pairs(old), 'add')


def present(device):
    """The current host node of a recorded device, or None when it is not
    plugged in: found by its port, then by its serial number."""
    if device.get('tree'):
        return '/dev/bus/usb'
    usb = device.get('usb') or {}
    candidates = []
    for directory in sorted((SYS / 'bus/usb/devices').glob('*')):
        if _read(directory / 'idVendor').lower() != usb.get('vendor') or _read(directory / 'idProduct').lower() != usb.get('product'):
            continue
        if usb.get('serial') and _read(directory / 'serial') != usb['serial']:
            continue
        candidates.append(directory)
    chosen = next((d for d in candidates if d.name == usb.get('port')), None)
    if chosen is None and usb.get('serial') and len(candidates) == 1:
        chosen = candidates[0]
    if chosen is None:
        return None
    if 'serial_link' in device:
        return device['serial_link'] if os.path.exists(device['serial_link']) else None
    return f"/dev/bus/usb/{int(_read(chosen / 'busnum')):03d}/{int(_read(chosen / 'devnum')):03d}"


def main(argv=None):
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('apply', 'remove'))
    parser.add_argument('vmid', type=int)
    parser.add_argument('deployment', nargs='?')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error(translate('Root privileges are required'))
    if args.action == 'apply':
        if not args.deployment:
            parser.error('the deployment file is required')
        apply(args.vmid, json.loads(Path(args.deployment).read_text()))
    else:
        remove(args.vmid)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
