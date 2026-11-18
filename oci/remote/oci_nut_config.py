#!/usr/bin/env python3
"""The configuration of a NUT server for every UPS passed to its container.

The NUT image writes its configuration once, at its first start, for a single
UPS and the driver of its DRIVER variable, and leaves it as it is from then
on. For an application whose recipe asks for it, the configuration is written
here instead each time the container is created: one section per UPS with
the driver its vendor needs, the user of the server, and the monitor of every
UPS. The mark the image leaves after its first start is written too, so it
does not add its own section on top.
"""
import argparse
import json
import os
from pathlib import Path
import re

from oci_ui import translate

# The driver each vendor needs. A pair names a model that differs from the
# rest of its vendor. Anything else is a USB HID UPS.
DRIVERS = {('06da', 'ffff'): 'usbhid-ups'}
VENDOR_DRIVERS = {'0665': 'nutdrv_qx', '06da': 'nutdrv_qx', '0001': 'nutdrv_qx', '0f03': 'nutdrv_qx'}
DEFAULT_DRIVER = 'usbhid-ups'
KNOWN_DRIVERS = ('usbhid-ups', 'nutdrv_qx', 'blazer_usb', 'tripplite_usb', 'bcmxcp_usb', 'richcomm_usb',
                 'riello_usb', 'nutdrv_atcl_usb')
NAME = re.compile(r'[A-Za-z0-9_-]{1,32}')
SECRET = re.compile(r'[A-Za-z0-9._@%+=:,/-]{1,128}')
DESCRIPTION = re.compile(r'[^"\\\n\r]{0,64}')


def driver_for(usb):
    """The driver proposed for a UPS by its vendor and product."""
    vendor, product = usb.get('vendor', ''), usb.get('product', '')
    return DRIVERS.get((vendor, product)) or VENDOR_DRIVERS.get(vendor, DEFAULT_DRIVER)


def busport(port):
    """The number NUT gives the port of a device on its hub: the last one of
    its physical path, as 3-3 is port 3 and 1-4.2 port 2."""
    return f'{int(re.split(r"[-.]", port)[-1]):03d}'


def ups_devices(deployment):
    """The UPS passed to the container by their identity."""
    return [device for device in deployment.get('devices', [])
            if device.get('kind') == 'usb' and not device.get('tree') and 'serial_link' not in device]


def ambiguous(devices):
    """UPS of the same model, without a serial number of their own, on ports
    with the same number: NUT cannot tell them apart."""
    seen, result = {}, []
    for device in devices:
        usb = device['usb']
        if usb.get('serial'):
            continue
        key = (usb['vendor'], usb['product'], busport(usb['port']))
        if key in seen:
            result.append((seen[key], device))
        seen.setdefault(key, device)
    return result


def _environment(deployment):
    return {item['name']: str(item.get('value', '')) for item in deployment.get('environment', [])
            if isinstance(item, dict) and item.get('name')}


def render(deployment):
    """The files of the NUT configuration, by their path in the container;
    none when no UPS is passed by its identity."""
    devices = ups_devices(deployment)
    if not devices:
        return {}
    env = _environment(deployment)
    name = env.get('NAME') or 'ups'
    user = env.get('API_USER') or 'upsmon'
    password = env.get('API_PASSWORD', '')
    server = env.get('SERVER') or 'primary'
    description = env.get('DESCRIPTION') or 'UPS'
    if not NAME.fullmatch(name) or not NAME.fullmatch(user) or server not in ('primary', 'master'):
        raise ValueError(translate('The NUT server name or user is not valid'))
    if not SECRET.fullmatch(password):
        raise ValueError(translate('The password of the NUT server user is missing or has characters NUT cannot read'))
    if not DESCRIPTION.fullmatch(description):
        raise ValueError(translate('The description of the UPS has characters NUT cannot read'))
    same_model = {}
    for device in devices:
        key = (device['usb']['vendor'], device['usb']['product'])
        same_model[key] = same_model.get(key, 0) + 1
    sections, monitors = [], []
    for index, device in enumerate(devices, 1):
        usb = device['usb']
        section = name if index == 1 else f'{name}{index}'
        driver = device.get('nut_driver') or driver_for(usb)
        if driver not in KNOWN_DRIVERS:
            raise ValueError(f"{translate('Unsupported NUT driver')}: {driver}")
        lines = [f'[{section}]', f'        driver = {driver}', '        port = auto',
                 f'        vendorid = {usb["vendor"]}', f'        productid = {usb["product"]}']
        if usb.get('serial'):
            lines.append(f'        serial = "{usb["serial"]}"')
        elif same_model[(usb['vendor'], usb['product'])] > 1:
            # Two UPS of one model without a serial number: their port tells them apart.
            lines.append(f'        busport = "{busport(usb["port"])}"')
        label = description if len(devices) == 1 else f'{description} {index}'
        lines.append(f'        desc = "{label}"')
        sections.append('\n'.join(lines))
        monitors.append(f'MONITOR {section}@localhost 1 {user} {password} {server}')
    head = '# Written by ProxMenux each time the container is created.\n'
    return {
        '/etc/nut/ups.conf': head + 'maxretry = 3\n\n' + '\n\n'.join(sections) + '\n',
        '/etc/nut/upsd.conf': head + 'LISTEN 0.0.0.0 3493\n',
        '/etc/nut/upsd.users': head + f'[{user}]\n        password = {password}\n        upsmon {server}\n',
        '/etc/nut/upsmon.conf': head + '\n'.join([
            *monitors, 'MINSUPPLIES 1', 'SHUTDOWNCMD "/sbin/shutdown -h +0"', 'POLLFREQ 5', 'POLLFREQALERT 5',
            'HOSTSYNC 15', 'DEADTIME 15', 'POWERDOWNFLAG "/etc/killpower"', 'FINALDELAY 5', 'RUN_AS_USER nut']) + '\n',
        # The mark of the image: its own first-start configuration is skipped.
        '/etc/nut/.setup': '',
    }


def write(rootfs, deployment, uid, gid):
    """Write the files into the root filesystem of a stopped container, owned
    by its root and readable by no one else."""
    files = render(deployment)
    rootfs = Path(rootfs)
    for path, content in files.items():
        destination = rootfs / path.lstrip('/')
        parent = destination.parent
        if parent.is_symlink() or not parent.is_dir() or destination.is_symlink():
            raise ValueError(f"{translate('The NUT configuration cannot be written in the container')}: {path}")
        temporary = parent / f'.{destination.name}.proxmenux'
        temporary.write_text(content)
        os.chown(temporary, uid, gid)
        os.chmod(temporary, 0o644 if path.endswith('.setup') else 0o640)
        os.replace(temporary, destination)
    return sorted(files)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('write',))
    parser.add_argument('rootfs')
    parser.add_argument('deployment')
    parser.add_argument('uid', type=int)
    parser.add_argument('gid', type=int)
    args = parser.parse_args(argv)
    written = write(args.rootfs, json.loads(Path(args.deployment).read_text()), args.uid, args.gid)
    print(' '.join(written))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
