#!/usr/bin/env python3

# ==========================================================
# ProxMenux - Plain LXC resource checks
# ==========================================================
# Author      : Vaso73
# GitHub      : github.com/Vaso73
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 15/11/2026
# ==========================================================
# Description:
# Read existing device nodes, PCI safety metadata and guest assignments.
# Validate selected bind directories without changing their permissions.
# No driver installation, mount, guest command or lifecycle operation.
# ==========================================================
"""Read-only host resource discovery and identities, never driver configuration."""
import os
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
import re
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plain_lxc_spec import DEVICE_PATH, LxcError, mount_path
BASE = Path(__file__).resolve().parents[2]
OCI_REMOTE = next((path for path in (BASE/'oci/remote', BASE/'oci/engine/remote')
                   if (path/'lxc_hardware.py').is_file()), BASE/'oci/remote')
sys.path.insert(0,str(OCI_REMOTE))
import lxc_hardware as hardware
import oci_usb_passthrough as usb_passthrough

HOOK = OCI_REMOTE / 'nvidia_lxc_mount_lab.sh'
HOOK_DIRECTORY = Path('/usr/local/lib/proxmenux/oci')
CAPABILITIES = 'compute,utility,video'


class DeviceInventory(dict):
    def __init__(self):
        super().__init__()
        self.errors = []


def pci_identity(pci):
    if (pci/'physfn').exists() or (pci/'physfn').is_symlink():
        raise LxcError('resource_unavailable')
    if (pci/'sriov_numvfs').exists() and (pci/'sriov_numvfs').read_text().strip() != '0':
        raise LxcError('resource_unavailable')
    driver = (pci/'driver').resolve(strict=True).name
    if driver == 'vfio-pci':
        raise LxcError('resource_unavailable')
    return {'pci_path':str(pci.resolve(strict=True)), 'driver':driver}


def nvidia_inventory():
    value = hardware.nvidia_snapshot(hardware.read_command)
    for row in value['gpus']:
        parts = [part.strip() for part in row.split(',')]
        if len(parts) != 3 or not re.fullmatch(r'[0-9A-Fa-f]{4,8}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]', parts[1]):
            raise LxcError('resource_unavailable')
        pci_identity(Path('/sys/bus/pci/devices') / parts[1][-12:].lower())
    return value


def nvidia_runtime(value):
    if HOOK.is_symlink() or not HOOK.is_file():
        raise LxcError('resource_unavailable')
    sha = hashlib.sha256(HOOK.read_bytes()).hexdigest()
    return {'inventory':value, 'hook_sha256':sha,
            'hook_path':str(HOOK_DIRECTORY / ('nvidia-mount-' + sha + '.sh')),
            'capabilities':CAPABILITIES}


# A GPU is given whole, as add_gpu_lxc.sh gives it: its card and render nodes,
# and on AMD the compute interface as well, since what the container will run
# on it is not known.
SHARED_NODES = ('/dev/kfd',)
# A Coral USB Accelerator changes its identity when its runtime loads the
# firmware: both are let in, and that change is not a reconnection.
CORAL_USB = (('1a6e', '089a'), ('18d1', '9302'))


def usb_identity(path, profile, key):
    """How a USB device or serial adapter is passed to the container: by its
    vendor, product, serial number and port, as OCI manager Apps passes it."""
    if profile == 'coral':
        port = usb_passthrough.entry(key, path)['usb']['port']
        return [{'id':f'{key}-{vendor}{product}', 'kind':'usb', 'container_path':'/dev/bus/usb', 'reconnect':False,
                 'usb':{'vendor':vendor, 'product':product, 'port':port}} for vendor, product in CORAL_USB]
    return [usb_passthrough.entry(key, path)]


def profiles(devices):
    result = {}
    for path, row in devices.items():
        kind = row.get('profile')
        if not kind:
            continue
        key = hashlib.sha256((kind + ':' + path).encode()).hexdigest()[:24]
        nodes = [path]
        if kind in ('intel-drm', 'amd-drm'):
            nodes += sorted(other for other, card in devices.items()
                            if card.get('drm_card') and card.get('pci_path') == row.get('pci_path'))
            if kind == 'amd-drm' and '/dev/kfd' in devices:
                nodes.append('/dev/kfd')
        item = {'profile':kind, 'selection_id':key, 'name':row['name'],
                'devices':[{'path':node, 'uid':0, 'gid':devices[node]['identity']['gid'], 'mode':'0660'} for node in nodes],
                'evidence':{node:devices[node] for node in nodes}}
        if usb_passthrough.handled(path):
            try:
                item['usb'] = usb_identity(path, kind, key)
            except (OSError, ValueError):
                # Without a readable identity (or a stable serial link) it
                # could not be found again after a reboot: not offered.
                continue
        result[key] = item
    nvidia = [row for row in devices.values() if row.get('runtime')]
    if nvidia:
        runtime = nvidia[0]['runtime']
        nodes = sorted(runtime['inventory']['devices'])
        if all(path in devices for path in nodes):
            result['nvidia-runtime'] = {'profile':'nvidia-runtime','selection_id':'nvidia-runtime',
                'name':'NVIDIA GPU (all host GPUs)',
                'devices':[{'path':p,'uid':0,'gid':devices[p]['identity']['gid'],
                            'mode':format(devices[p]['identity']['mode'], '04o')} for p in nodes],
                'evidence':{p:{k:v for k,v in devices[p].items() if k != 'runtime'} for p in nodes}, 'runtime':runtime}
    return result


def selected_hardware(selections, available):
    chosen, paths = [], set()
    for selection in selections:
        candidate = available.get(selection['selection_id'])
        if candidate is None or candidate['profile'] != selection['profile']:
            raise LxcError('resource_unavailable', 'hardware')
        nodes = {row['path'] for row in candidate['devices']} - set(SHARED_NODES)
        if paths & nodes:
            raise LxcError('invalid_field','hardware')
        paths.update(nodes)
        chosen.append(candidate)
    return chosen


def usb_deployment(chosen):
    return {'devices':[entry for item in chosen for entry in item.get('usb', [])]}


def runtime_entries(chosen):
    runtime = next((item['runtime'] for item in chosen if item.get('runtime')), None)
    entries = []
    if runtime:
        entries += [['lxc.environment','NVIDIA_VISIBLE_DEVICES=all'],
                    ['lxc.environment','NVIDIA_DRIVER_CAPABILITIES='+runtime['capabilities']],
                    ['lxc.hook.mount',runtime['hook_path']]]
    return entries + [line.split(': ', 1) for line in usb_passthrough.lines(usb_deployment(chosen))]


def comparable(items):
    """The hardware as reviewed, without the permission the container's own
    udev rule gives a USB device passed by its identity."""
    result = json.loads(json.dumps(items))
    for item in result:
        if type(item) is dict and item.get('usb'):
            for row in (item.get('evidence') or {}).values():
                if type(row) is dict and type(row.get('identity')) is dict:
                    row['identity'].pop('mode', None)
    return result


def verify_selected(chosen, vmid):
    if type(chosen) is not list or len(chosen) > 16:
        raise LxcError('resource_unavailable')
    current = profiles(discover_devices())
    selections = [{'profile':item['profile'],'selection_id':item['selection_id']} for item in chosen]
    if comparable(selected_hardware(selections, current)) != comparable(chosen):
        raise LxcError('resource_unavailable')
    device_assignments([d['path'] for item in chosen for d in item['devices']], vmid)
    return runtime_entries(chosen)


def path_identity(path, *, device=False):
    path = Path(path)
    try:
        for part in reversed(path.parents):
            if part.is_symlink():
                raise LxcError('resource_unavailable')
        info = path.lstat()
    except OSError:
        raise LxcError('resource_unavailable') from None
    if not (stat.S_ISCHR(info.st_mode) if device else stat.S_ISDIR(info.st_mode)):
        raise LxcError('resource_unavailable')
    # Filesystem identifiers can exceed JavaScript's exact integer range.
    return {'dev':str(info.st_dev), 'ino':str(info.st_ino), 'rdev':str(info.st_rdev),
            'uid':info.st_uid, 'gid':info.st_gid, 'mode':stat.S_IMODE(info.st_mode)}


def usb_identifiers(path, sysroot=Path('/sys'), identity=None):
    try:
        identity = identity or path_identity(path, device=True)
        number = int(identity['rdev'])
        kernel = (sysroot/'dev/char'/f'{os.major(number)}:{os.minor(number)}').resolve(strict=True)
        usb = next((part for part in (kernel,*kernel.parents) if (part/'idVendor').is_file() and (part/'idProduct').is_file()), None)
        if usb is None or not re.fullmatch(r'[0-9]+-[0-9]+(?:\.[0-9]+)*',usb.name):
            raise LxcError('resource_unavailable')
        vendor, product = ((usb/name).read_text().strip().lower() for name in ('idVendor','idProduct'))
        device_class = (usb/'bDeviceClass').read_text().strip().lower()
        if not re.fullmatch(r'[0-9a-f]{4}',vendor) or not re.fullmatch(r'[0-9a-f]{4}',product) or not re.fullmatch(r'[0-9a-f]{2}',device_class) or device_class == '09':
            raise LxcError('resource_unavailable')
        serial_file = usb/'serial'
        serial = serial_file.read_text().strip() if serial_file.exists() else None
        return {'id':vendor+':'+product,'port':usb.name, 'serial':serial,
                'sysfs_path':str(kernel)}
    except (OSError,ValueError,RuntimeError):
        raise LxcError('resource_unavailable') from None


def device_policy(path, identity, sysroot=Path('/sys')):
    """Keep the existing GPU helper's VF/active-PF/VFIO exclusion policy.

    Unlike its broad globs, selection binds one kernel node. Accelerator nodes
    without an unambiguous PCI parent are not advertised as safe passthrough.
    """
    if path.startswith(('/dev/bus/usb/', '/dev/ttyUSB', '/dev/ttyACM')):
        usb_identifiers(path,sysroot,identity)
        return
    if path.startswith('/dev/nvidia'):
        try:
            if path not in nvidia_inventory()['devices']:
                raise LxcError('resource_unavailable')
            return
        except (OSError, ValueError, subprocess.SubprocessError):
            raise LxcError('resource_unavailable') from None
    if path == '/dev/kfd':
        # The compute interface goes with an AMD GPU whether or not ROCm
        # supports that GPU; it only has to be the driver's working node.
        if not Path('/sys/class/kfd/kfd/topology/nodes').is_dir():
            raise LxcError('resource_unavailable')
        return
    try:
        number = int(identity['rdev'])
        kernel = (sysroot/'dev/char'/f'{os.major(number)}:{os.minor(number)}').resolve(strict=True)
        pci = next((part for part in (kernel,*kernel.parents) if re.fullmatch(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]', part.name)), None)
        if pci is None or (pci/'physfn').is_symlink() or (pci/'physfn').exists():
            raise LxcError('resource_unavailable')
        count = (pci/'sriov_numvfs').read_text().strip() if (pci/'sriov_numvfs').exists() else '0'
        if count != '0' or (pci/'driver').resolve(strict=True).name == 'vfio-pci':
            raise LxcError('resource_unavailable')
    except (OSError, ValueError, RuntimeError):
        raise LxcError('resource_unavailable') from None


USB_TREE = '/dev/bus/usb'
RULE_MATCH = re.compile(r'ATTR\{(idVendor|idProduct|serial)\}=="([^"]*)"')


def usb_claims(vmid, rules=Path('/etc/udev/rules.d')):
    """The USB devices a container holds by identity, read from its ProxMenux
    udev rule, or None when it has no such rule."""
    path = rules / f'99-proxmenux-oci-{int(vmid)}.rules'
    if not path.exists():
        return None
    claims = []
    for line in path.read_text().splitlines():
        if line.startswith('SUBSYSTEM=="usb"') and 'MODE="0666"' in line:
            claims.append(dict(RULE_MATCH.findall(line)))
    return claims


def claimed_by(claims, path, sysroot):
    """Whether one of these identities names the USB device at path."""
    found = usb_identifiers(path, sysroot)
    vendor, product = found['id'].split(':')
    return any(claim.get('idVendor') == vendor and claim.get('idProduct') == product
               and claim.get('serial', found['serial']) == found['serial'] for claim in claims)


def device_assignments(paths, vmid, directory=Path('/etc/pve/lxc'),
                       qemu_directory=Path('/etc/pve/qemu-server'), sysroot=Path('/sys'),
                       rules=Path('/etc/udev/rules.d')):
    if not paths:
        return {}
    if not directory.is_dir():
        raise LxcError('resource_unavailable')
    assigned = {path:[] for path in paths}
    try:
        for config in directory.glob('*.conf'):
            if not config.stem.isdecimal() or int(config.stem) == vmid:
                continue
            active = True
            for line in config.read_text().splitlines():
                if line.startswith('['):
                    active = line.strip() == '[PENDING]'
                    continue
                if not active or not re.match(r'^(?:(?:dev|mp)[0-9]+|lxc\.mount\.entry):\s', line):
                    continue
                raw = line.split(':',1)[1].strip()
                explicit = re.search(r'(?:^|,)path=([^,]+)',raw)
                source = explicit[1] if explicit else raw.split(',',1)[0].split()[0]
                for path in paths:
                    if source == path or ((source == '/dev' or source.startswith('/dev/')) and path.startswith(source+'/')):
                        # A container given USB devices by identity mounts the
                        # whole tree; its rule says which devices it holds. The
                        # tree without a rule is held whole.
                        if source == USB_TREE and path.startswith(USB_TREE + '/'):
                            claims = usb_claims(config.stem, rules)
                            if claims is not None and not claimed_by(claims, path, sysroot):
                                continue
                        if int(config.stem) not in assigned[path]: assigned[path].append(int(config.stem))
        usb_paths = [path for path in paths if path.startswith(('/dev/bus/usb/', '/dev/ttyUSB', '/dev/ttyACM'))]
        if usb_paths:
            if not qemu_directory.is_dir():
                raise LxcError('resource_unavailable')
            identifiers = {}
            for config in qemu_directory.glob('*.conf'):
                active = True
                for line in config.read_text().splitlines():
                    if line.startswith('['):
                        active = line.strip() == '[PENDING]'
                        continue
                    if not active or not re.match(r'^usb[0-9]+:\s',line):
                        continue
                    raw=line.split(':',1)[1].strip()
                    options={}
                    for part in raw.split(','):
                        key,value=part.split('=',1) if '=' in part else ('host',part)
                        if key in options or key not in ('host','mapping','usb3'):
                            raise LxcError('resource_unavailable')
                        options[key]=value
                    if options.get('host','').lower() == 'spice':
                        continue
                    # Cluster USB mappings require a separate native resolver;
                    # never assume they are empty or silently steal the device.
                    if 'mapping' in options or not options.get('host'):
                        raise LxcError('resource_unavailable')
                    host=options['host'].lower()
                    ids=re.fullmatch(r'(?:0x)?([0-9a-f]{4}):(?:0x)?([0-9a-f]{4})',host)
                    if ids: host=ids[1]+':'+ids[2]
                    elif re.fullmatch(r'[0-9]+-[0-9]+(?:\.[0-9]+)*',host):
                        host=re.sub(r'[0-9]+',lambda match:str(int(match[0])),host)
                    else: raise LxcError('resource_unavailable')
                    for path in usb_paths:
                        if path not in identifiers: identifiers[path]=usb_identifiers(path,sysroot)
                        if host in identifiers[path].values():
                            raise LxcError('resource_in_use','devices.path')
    except (OSError, UnicodeError, IndexError):
        raise LxcError('resource_unavailable') from None
    # Sharing a GPU is intentional, as in add_gpu_lxc.sh. USB/serial/TPU/NPU
    # ownership must not silently be duplicated in another CT's configuration.
    for path, owners in assigned.items():
        gpu = path == '/dev/kfd' or path.startswith(('/dev/dri/', '/dev/nvidia'))
        if owners and not gpu:
            raise LxcError('resource_in_use', 'devices.path')
    return assigned


def discover_devices():
    result = DeviceInventory()
    usb = {}
    try:
        listing = hardware.read_command('lsusb') if shutil.which('lsusb') else ''
        usb = {row['path']:row for row in hardware.usb_devices(lsusb=listing)}
    except (OSError, ValueError, subprocess.SubprocessError):
        result.errors.append('usb_inventory_unavailable')
    nv = None
    if shutil.which('nvidia-smi') and shutil.which('nvidia-container-cli'):
        try:
            nv = nvidia_runtime(nvidia_inventory())
        except (OSError, ValueError, LxcError, subprocess.SubprocessError):
            result.errors.append('nvidia_inventory_unavailable')
    patterns = (('GPU','/dev/dri/renderD*'), ('GPU','/dev/dri/card[0-9]*'), ('TPU','/dev/apex_[0-9]*'),
                ('NPU','/dev/accel/accel[0-9]*'), ('USB','/dev/bus/usb/*/*'),
                ('USB','/dev/ttyUSB[0-9]*'), ('USB','/dev/ttyACM[0-9]*'),
                ('GPU','/dev/kfd'))
    candidates = [(kind,str(path)) for kind,pattern in patterns
                  for path in Path('/').glob(pattern.removeprefix('/'))]
    if nv:
        candidates += [('GPU',path) for path in nv['inventory']['devices']]
    for kind,name in candidates:
        if not re.fullmatch(DEVICE_PATH,name):
            continue
        # The shared USB inventory deliberately excludes hubs/storage and
        # exposes serial peripherals only by tty. These are not failed probes.
        if kind == 'USB' and name not in usb:
            continue
        # NVIDIA also has a render node; its GPU is offered by the runtime profile.
        if name.startswith('/dev/dri/') and hardware._sysfs(
                Path('/sys/class/drm') / Path(name).name / 'device/vendor').lower() not in ('0x8086', '0x1002'):
            continue
        try:
            identity = path_identity(name,device=True)
            device_policy(name,identity)
            row = {'path':name,'kind':kind,'identity':identity}
            if name.startswith('/dev/dri/card'):
                # Offered with the render node of the same GPU, never alone.
                gpu = hardware.device_snapshot(name)
                row.update(vendor=gpu['vendor'], pci_path=gpu['pci_path'], drm_card=True,
                           name=('Intel GPU' if gpu['vendor']=='0x8086' else 'AMD GPU')+' · '+Path(gpu['pci_path']).name)
            elif name.startswith('/dev/dri/'):
                gpu = hardware.device_snapshot(name)
                row.update(vendor=gpu['vendor'], pci_path=gpu['pci_path'],
                           profile='intel-drm' if gpu['vendor']=='0x8086' else 'amd-drm',
                           name=('Intel GPU' if gpu['vendor']=='0x8086' else 'AMD GPU')+' · '+Path(gpu['pci_path']).name)
                if gpu['vendor'] == '0x1002':
                    row['gfx_target'] = hardware.amd_compute_target(name)
            elif name.startswith('/dev/nvidia'):
                row.update(name='NVIDIA GPU')
                if name == sorted(nv['inventory']['devices'])[0]:
                    row['runtime'] = nv
            elif name == '/dev/kfd':
                row.update(name='AMD compute interface', topology=hardware.amd_gfx_target())
            elif kind == 'USB':
                meta = usb_identifiers(name,identity=identity)
                row.update(usb=meta,profile='coral' if meta['id'] in ('18d1:9302','1a6e:089a') else 'usb',
                           name=usb[name]['name']+' · '+(meta['serial'] or meta['port']))
            else:
                row.update(profile='coral' if kind=='TPU' else 'npu',
                           name=('Coral TPU' if kind=='TPU' else 'NPU')+' · '+name,
                           sysfs_path=hardware.device_snapshot(name)['sysfs_path'])
            result[name] = row
        except (LxcError,OSError,ValueError,subprocess.SubprocessError):
            result.errors.append('device_inventory_unavailable')
        if len(result) >= 512:
            break
    return result


def bind_identity(source):
    return path_identity(mount_path(source, 'mounts.source', host=True))


def checked_identity(identity):
    if type(identity) is not dict or set(identity) != {'dev','ino','rdev','uid','gid','mode'}:
        raise LxcError('pve_output_invalid')
    if any(type(identity[key]) is not str or not re.fullmatch(r'[0-9]{1,20}',identity[key]) for key in ('dev','ino','rdev')):
        raise LxcError('pve_output_invalid')
    if any(type(identity[key]) is not int or not 0 <= identity[key] <= 4294967295 for key in ('uid','gid')):
        raise LxcError('pve_output_invalid')
    if type(identity['mode']) is not int or not 0 <= identity['mode'] <= 0o7777:
        raise LxcError('pve_output_invalid')
    return identity


def check_hardware_request(request, vmid, prepare=False):
    if type(request) is not dict or set(request) != {'hardware','lxc','devices'} or type(request['lxc']) is not list:
        raise LxcError('invalid_request')
    # Shared nodes, as the AMD compute interface, are attached once; USB
    # devices go by their identity, not as device entries.
    expected_devices = list({device['path']:device for item in request['hardware'] if not item.get('usb')
                             for device in item['devices']}.values())
    if request['devices'] != expected_devices:
        raise LxcError('resource_unavailable')
    entries = verify_selected(request['hardware'], vmid)
    actual = request['lxc']
    if actual and actual != entries:
        raise LxcError('resource_unavailable')
    if not entries and actual:
        raise LxcError('resource_unavailable')
    runtime = next((item['runtime'] for item in request['hardware'] if item.get('runtime')), None)
    usb = usb_deployment(request['hardware'])
    if prepare and usb['devices']:
        usb_passthrough.write_rules(vmid, usb)
    if actual and usb['devices']:
        rule = usb_passthrough.rule_path(vmid)
        if not rule.is_file() or rule.read_text() != usb_passthrough.rules(vmid, usb):
            raise LxcError('resource_unavailable')
    if prepare and runtime:
        installer = HOOK.with_name('lxc_nvidia_setup.sh')
        result = subprocess.run(['/bin/bash',str(installer),'--install-hook',str(HOOK),runtime['hook_sha256']],
                                capture_output=True,text=True,timeout=15,check=False)
        if result.returncode or result.stdout.strip() != runtime['hook_path']:
            raise LxcError('resource_unavailable')
    if actual and runtime:
        hook = Path(runtime['hook_path'])
        info = hook.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or not info.st_mode & 0o111 or hashlib.sha256(hook.read_bytes()).hexdigest() != runtime['hook_sha256']):
            raise LxcError('resource_unavailable')
    return entries


if __name__ == '__main__':
    try:
        if len(sys.argv) != 4 or not re.fullmatch(r'[1-9][0-9]{2,8}',sys.argv[3]):
            raise LxcError('invalid_request')
        if sys.argv[1] == '--check-device':
            if not re.fullmatch(DEVICE_PATH,sys.argv[2]):
                raise LxcError('invalid_request')
            device_policy(sys.argv[2],path_identity(sys.argv[2],device=True))
            device_assignments([sys.argv[2]],int(sys.argv[3]))
        elif sys.argv[1] in ('--check-hardware','--prepare-hardware') and sys.argv[2] == '--json':
            from plain_lxc_spec import strict_json, MAX_BODY
            body = sys.stdin.buffer.read(MAX_BODY+1)
            if len(body) > MAX_BODY:
                raise LxcError('body_too_large')
            entries = check_hardware_request(strict_json(body),int(sys.argv[3]),sys.argv[1]=='--prepare-hardware')
            print(json.dumps(entries))
        else:
            raise LxcError('invalid_request')
    except (LxcError,OSError,ValueError,KeyError,TypeError,StopIteration,subprocess.SubprocessError):
        sys.exit(1)
