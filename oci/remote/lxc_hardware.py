"""Shared native LXC hardware reads. Standard library only; no registry or installer."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
from typing import Any

# USB classes as the Monitor labels them.
_USB_CLASSES = {
    "01": "Audio", "02": "Communications", "03": "HID", "06": "Imaging", "07": "Printer",
    "0a": "CDC Data", "0b": "Smart Card", "0e": "Video", "10": "Audio/Video",
    "e0": "Wireless Controller", "ef": "Miscellaneous", "fe": "Application Specific",
    "ff": "Vendor Specific",
}
# UPS makers, whose devices report the HID class.
_USB_UPS_VENDORS = {"0463", "051d", "0764", "0d9f", "06da", "09ae", "047c", "075d", "10af", "0665"}
_USB_LEFT_OUT = {"08", "09"}  # storage and hubs are not handed to an LXC as a device node
_SERIAL_NODE = re.compile(r"tty(?:ACM|USB)[0-9]+")
_LSUSB_LINE = re.compile(r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+[0-9a-f]{4}:[0-9a-f]{4}\s*(.*)", re.IGNORECASE)


def _sysfs(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def gpus(root: Path = Path("/")) -> dict[str, Any]:
    """The GPUs an installation can use: the render nodes of each Intel and
    AMD GPU, and whether NVIDIA is usable on the host."""
    vendors = {"0x8086": "intel", "0x1002": "amd"}
    found: dict[str, Any] = {"intel": [], "amd": [], "nvidia": False, "amd_gfx_target": None}
    for node in sorted((root / "sys/class/drm").glob("renderD*")):
        vendor = vendors.get(_sysfs(node / "device/vendor").lower())
        if vendor:
            found[vendor].append(f"/dev/dri/{node.name}")
    # NVIDIA is usable when its driver answers and the Container Toolkit is installed.
    if shutil.which("nvidia-smi") and shutil.which("nvidia-container-cli"):
        try:
            found["nvidia"] = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True,
                                             timeout=15, check=False).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            found["nvidia"] = False
    found["amd_gfx_target"] = amd_gfx_target(root)
    return found


def amd_gfx_target(root: Path = Path("/")) -> int | None:
    """The generation of the AMD GPU as its compute driver reports it: 90012
    for gfx90c (Vega integrated graphics), 100300 for gfx1030 (RDNA2). None
    when the driver exposes no compute device."""
    best = None
    for path in sorted((root / "sys/class/kfd/kfd/topology/nodes").glob("*/properties")):
        match = re.search(r"^gfx_target_version (\d+)$", _sysfs(path), re.MULTILINE)
        if match and int(match[1]) > 0:
            best = max(best or 0, int(match[1]))
    return best




def usb_devices(root: Path = Path("/"), lsusb: str | None = None) -> list[dict[str, str]]:
    """USB peripherals of this node an LXC can receive, named as the Monitor
    names them: a serial adapter by its tty node, any other device by its bus
    node."""
    if lsusb is None:
        try:
            lsusb = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5,
                                   check=False).stdout
        except (OSError, subprocess.TimeoutExpired):
            lsusb = ""
    names = {}
    for line in lsusb.splitlines():
        match = _LSUSB_LINE.match(line)
        if match:
            names[(int(match[1]), int(match[2]))] = match[3].strip()
    serial: dict[str, list[str]] = {}
    for tty in sorted((root / "sys/class/tty").glob("tty*")):
        if not _SERIAL_NODE.fullmatch(tty.name):
            continue
        device = (tty / "device").resolve()
        while device != device.parent and not (device / "idVendor").exists():
            device = device.parent
        if (device / "idVendor").exists():
            serial.setdefault(device.name, []).append(tty.name)
    rows = []
    for device in sorted((root / "sys/bus/usb/devices").glob("*")):
        vendor = _sysfs(device / "idVendor").lower()
        if ":" in device.name or not vendor or vendor == "1d6b":
            continue
        device_class = _sysfs(device / "bDeviceClass").lower() or "00"
        if device_class == "00":
            device_class = _sysfs(device / f"{device.name}:1.0" / "bInterfaceClass").lower()
        if device_class in _USB_LEFT_OUT:
            continue
        kind = "UPS" if device_class == "03" and vendor in _USB_UPS_VENDORS else _USB_CLASSES.get(device_class, "USB")
        try:
            bus, number = int(_sysfs(device / "busnum")), int(_sysfs(device / "devnum"))
        except ValueError:
            continue
        name = (_sysfs(device / "product") or names.get((bus, number))
                or f"{vendor}:{_sysfs(device / 'idProduct').lower()}")
        for node in serial.get(device.name) or [f"bus/usb/{bus:03d}/{number:03d}"]:
            rows.append({"path": f"/dev/{node}", "name": name, "kind": kind})
    return rows


def gpu_path(path):
    return isinstance(path, str) and (re.fullmatch(r'/dev/dri/(renderD|card)[0-9]+', path) is not None or path == '/dev/kfd')


def peripheral_path(path):
    """Coral, NPU (/dev/accel), USB and serial nodes, identified by their sysfs path."""
    return isinstance(path, str) and re.fullmatch(
        r'/dev/(apex_[0-9]+|accel/accel[0-9]+|ttyUSB[0-9]+|ttyACM[0-9]+|bus/usb/[0-9]{3}/[0-9]{3})', path) is not None


def system_path(path):
    """Fixed nodes the kernel always presents the same way. They carry no
    identity beyond their device numbers, so there is no sysfs to interrogate:
    the numbers and the permissions are the whole record."""
    return isinstance(path, str) and re.fullmatch(
        r'/dev/(kvm|fuse|net/tun|video[0-9]+|sg[0-9]+)', path) is not None


def block_path(path):
    return isinstance(path, str) and re.fullmatch(r'/dev/sr[0-9]+', path) is not None


def known_path(path):
    return gpu_path(path) or peripheral_path(path) or system_path(path) or block_path(path)


def device_snapshot(path):
    if not known_path(path):
        raise ValueError('Device node outside the supported profiles')
    info = Path(path).stat()
    if block_path(path):
        if not stat.S_ISBLK(info.st_mode):
            raise ValueError('The selected device is not a block device')
    elif not stat.S_ISCHR(info.st_mode):
        raise ValueError('The selected device is not a character device')
    value = {'path': str(Path(path).resolve()), 'major': os.major(info.st_rdev),
             'minor': os.minor(info.st_rdev), 'uid': info.st_uid, 'gid': info.st_gid,
             'mode': stat.S_IMODE(info.st_mode)}
    if peripheral_path(path):
        sysfs = Path('/sys/dev/char') / f'{value["major"]}:{value["minor"]}'
        value['sysfs_path'] = str(sysfs.resolve(strict=True))
        if '/bus/usb/' in path:
            for name in ('idVendor', 'idProduct', 'serial'):
                field = sysfs / name
                if field.is_file():
                    value[name] = field.read_text().strip()
    elif gpu_path(path) and path != '/dev/kfd':
        sysfs = Path('/sys/class/drm') / Path(path).name / 'device'
        value.update(vendor=(sysfs / 'vendor').read_text().strip(), pci_path=str(sysfs.resolve()))
        if value['vendor'] not in ('0x1002', '0x8086'):
            raise ValueError('The DRM node is not an Intel or AMD GPU; NVIDIA requires its library profile')
    return value




def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()




QUERY = '--query-gpu=uuid,pci.bus_id,driver_version'

def nvidia_snapshot(command):
    gpus = sorted(line.strip() for line in command('nvidia-smi', QUERY, '--format=csv,noheader').splitlines() if line.strip())
    if not gpus:
        raise ValueError('No working NVIDIA GPU was found')
    version = command('nvidia-container-cli', '--version')
    paths = command('nvidia-container-cli', 'list', '--device', 'all', '--libraries', '--binaries', '--firmwares', '--ipcs')
    devices, files, links = {}, {}, {}
    for name in sorted(set(paths.splitlines())):
        if not name.startswith('/') or str(PurePosixPath(name)) != name or any(c.isspace() or c == ',' for c in name):
            raise ValueError('Invalid path in the NVIDIA inventory')
        path = Path(name)
        info = path.stat()
        basic = {'source': str(path.resolve()), 'uid': info.st_uid,
                 'gid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode)}
        if stat.S_ISCHR(info.st_mode):
            if not name.startswith('/dev/nvidia'):
                raise ValueError('NVIDIA device outside the expected native profile')
            devices[name] = dict(basic, major=os.major(info.st_rdev), minor=os.minor(info.st_rdev))
        elif stat.S_ISREG(info.st_mode):
            files[name] = dict(basic, size=info.st_size, sha256=digest(path))
            if name.startswith('/usr/lib/'):
                for link in path.parent.iterdir():
                    if link.is_symlink() and str(link.resolve()) == basic['source']:
                        links[str(link)] = os.readlink(link)
        # The common installer intentionally does not publish IPC sockets.
    if not devices or not files:
        raise ValueError('Incomplete NVIDIA inventory')
    versions = [l for l in version.splitlines() if l.startswith(('cli-version:', 'lib-version:'))]
    if len(versions) != 2:
        raise ValueError('The NVIDIA Container Toolkit version cannot be identified')
    return {'gpus': gpus, 'toolkit_version': versions,
            'devices': devices, 'files': files, 'links': links}




def read_command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False,
                            env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C.UTF-8'})
    if result.returncode:
        raise ValueError('hardware_inventory_unavailable')
    return result.stdout


def amd_compute_target(render_path, root=Path('/')):
    """KFD exports drm_render_minor alongside gfx_target_version per GPU.

    See Linux drivers/gpu/drm/amd/amdkfd/kfd_topology.c. Do not borrow the
    highest generation of a different GPU in a multi-GPU host.
    """
    minor = int(Path(render_path).name.removeprefix('renderD'))
    targets = []
    for properties in (root/'sys/class/kfd/kfd/topology/nodes').glob('*/properties'):
        rows = dict(line.split() for line in properties.read_text().splitlines() if len(line.split()) == 2)
        if rows.get('drm_render_minor') == str(minor):
            target = int(rows.get('gfx_target_version','0'))
            if target > 0:
                targets.append(target)
    return targets[0] if len(targets) == 1 else None


def parse_config(data):
    values = {}
    for line in data.decode().splitlines():
        if line and not line.startswith('#') and ': ' in line:
            key, value = line.split(': ', 1)
            values[key] = value
    return values
