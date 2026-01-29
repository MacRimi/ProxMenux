import os
import json
import math
import subprocess
import re
import psutil
from system_monitor import get_proxmox_node_name

# Intentar importar el monitor de storage externo si existe
try:
    from proxmox_storage_monitor import proxmox_storage_monitor
except ImportError:
    proxmox_storage_monitor = None

def format_bytes(size_in_bytes):
    if size_in_bytes is None: return "N/A"
    if size_in_bytes == 0: return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB")
    i = int(math.floor(math.log(size_in_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_in_bytes / p, 2)
    return f"{s} {size_name[i]}"

def get_pcie_link_speed(disk_name):
    """Obtiene info PCIe para NVMe."""
    pcie_info = {'pcie_gen': None, 'pcie_width': None}
    try:
        if disk_name.startswith('nvme'):
            match = re.match(r'(nvme\d+)n\d+', disk_name)
            if match:
                controller = match.group(1)
                sys_path = f'/sys/class/nvme/{controller}/device'
                pci_address = None
                
                if os.path.exists(sys_path):
                    pci_address = os.path.basename(os.readlink(sys_path))
                else:
                    alt_path = f'/sys/block/{disk_name}/device/device'
                    if os.path.exists(alt_path):
                        pci_address = os.path.basename(os.readlink(alt_path))
                
                if pci_address:
                    res = subprocess.run(['lspci', '-vvv', '-s', pci_address], capture_output=True, text=True, timeout=5)
                    if res.returncode == 0:
                        for line in res.stdout.split('\n'):
                            if 'LnkSta:' in line:
                                if 'Speed' in line:
                                    m = re.search(r'Speed\s+([\d.]+)GT/s', line)
                                    if m:
                                        gt = float(m.group(1))
                                        if gt <= 8.0: pcie_info['pcie_gen'] = '3.0'
                                        elif gt <= 16.0: pcie_info['pcie_gen'] = '4.0'
                                        else: pcie_info['pcie_gen'] = '5.0'
                                if 'Width' in line:
                                    m = re.search(r'Width\s+x(\d+)', line)
                                    if m: pcie_info['pcie_width'] = f'x{m.group(1)}'
    except Exception: pass
    return pcie_info

def get_smart_data(disk_name):
    """Obtiene datos SMART detallados."""
    smart_data = {
        'temperature': 0, 'health': 'unknown', 'power_on_hours': 0, 'smart_status': 'unknown',
        'model': 'Unknown', 'serial': 'Unknown', 'reallocated_sectors': 0,
        'ssd_life_left': None, 'rotation_rate': 0
    }
    
    cmds = [
        ['smartctl', '-a', '-j', f'/dev/{disk_name}'],
        ['smartctl', '-a', '-j', '-d', 'ata', f'/dev/{disk_name}'],
        ['smartctl', '-a', '-j', '-d', 'nvme', f'/dev/{disk_name}'],
        ['smartctl', '-a', f'/dev/{disk_name}']
    ]
    
    for cmd in cmds:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            if not res.stdout: continue
            
            if '-j' in cmd:
                try:
                    data = json.loads(res.stdout)
                    if 'model_name' in data: smart_data['model'] = data['model_name']
                    elif 'model_family' in data: smart_data['model'] = data['model_family']
                    if 'serial_number' in data: smart_data['serial'] = data['serial_number']
                    if 'rotation_rate' in data: smart_data['rotation_rate'] = data['rotation_rate']
                    
                    if 'temperature' in data and 'current' in data['temperature']:
                        smart_data['temperature'] = data['temperature']['current']
                    if 'smart_status' in data:
                        smart_data['health'] = 'healthy' if data['smart_status'].get('passed') else 'critical'
                        
                    # NVMe
                    if 'nvme_smart_health_information_log' in data:
                        nvme = data['nvme_smart_health_information_log']
                        if 'temperature' in nvme: smart_data['temperature'] = nvme['temperature']
                        if 'power_on_hours' in nvme: smart_data['power_on_hours'] = nvme['power_on_hours']
                        if 'percentage_used' in nvme: smart_data['ssd_life_left'] = 100 - nvme['percentage_used']
                        
                    # ATA
                    if 'ata_smart_attributes' in data:
                        for attr in data['ata_smart_attributes'].get('table', []):
                            aid = attr.get('id')
                            raw = attr.get('raw', {}).get('value', 0)
                            norm = attr.get('value', 0)
                            if aid == 9: smart_data['power_on_hours'] = raw
                            elif aid == 5: smart_data['reallocated_sectors'] = raw
                            elif aid == 194 and smart_data['temperature'] == 0: smart_data['temperature'] = raw
                            elif str(aid) in ['231', '202']: smart_data['ssd_life_left'] = norm
                            
                    if smart_data['model'] != 'Unknown': break
                except json.JSONDecodeError: pass
            
            # Fallback texto
            if smart_data['model'] == 'Unknown':
                for line in res.stdout.split('\n'):
                    if 'Device Model:' in line: smart_data['model'] = line.split(':', 1)[1].strip()
                    elif 'Serial Number:' in line: smart_data['serial'] = line.split(':', 1)[1].strip()
                    elif 'Current Temperature:' in line: 
                        try: smart_data['temperature'] = int(line.split(':')[1].strip().split()[0])
                        except: pass
                if smart_data['model'] != 'Unknown': break
        except: continue

    # Evaluación salud
    if smart_data['reallocated_sectors'] > 0: smart_data['health'] = 'warning'
    if smart_data['temperature'] >= 60: smart_data['health'] = 'warning'
    
    return smart_data

def get_storage_info():
    """Info completa de almacenamiento."""
    data = {'total': 0, 'used': 0, 'available': 0, 'disks': [], 'zfs_pools': [], 'disk_count': 0}
    
    # 1. Discos físicos
    try:
        res = subprocess.run(['lsblk', '-b', '-d', '-n', '-o', 'NAME,SIZE,TYPE'], capture_output=True, text=True, timeout=5)
        for line in res.stdout.strip().split('\n'):
            p = line.split()
            if len(p) >= 3 and p[2] == 'disk':
                name = p[0]
                if name.startswith('zd'): continue
                size = int(p[1])
                smart = get_smart_data(name)
                
                size_tb = size / (1024**4)
                size_str = f"{size_tb:.1f}T" if size_tb >= 1 else f"{size / (1024**3):.1f}G"
                
                data['disks'].append({
                    'name': name,
                    'size': size / 1024, # KB
                    'size_formatted': size_str,
                    'size_bytes': size,
                    'model': smart['model'],
                    'serial': smart['serial'],
                    'temperature': smart['temperature'],
                    'health': smart['health'],
                    'ssd_life_left': smart['ssd_life_left']
                })
                data['total'] += size
                data['disk_count'] += 1
    except: pass
    
    data['total'] = round(data['total'] / (1024**4), 1) # TB
    
    # 2. Uso (Particiones + ZFS)
    used = 0
    avail = 0
    try:
        for part in psutil.disk_partitions():
            if part.fstype not in ['tmpfs', 'overlay', 'zfs']:
                try:
                    u = psutil.disk_usage(part.mountpoint)
                    used += u.used
                    avail += u.free
                except: pass
                
        res = subprocess.run(['zpool', 'list', '-H', '-p', '-o', 'name,size,alloc,free,health'], capture_output=True, text=True)
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n'):
                if line:
                    p = line.split('\t')
                    used += int(p[2])
                    avail += int(p[3])
                    data['zfs_pools'].append({
                        'name': p[0], 'size': format_bytes(int(p[1])),
                        'allocated': format_bytes(int(p[2])), 'free': format_bytes(int(p[3])),
                        'health': p[4]
                    })
    except: pass
    
    data['used'] = round(used / (1024**3), 1)
    data['available'] = round(avail / (1024**3), 1)
    return data

def get_storage_summary():
    """Resumen rápido."""
    return get_storage_info() # Se puede optimizar quitando SMART

def get_proxmox_storage():
    """Storage de Proxmox."""
    node = get_proxmox_node_name()
    storage = []
    try:
        res = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'storage', '--output-format', 'json'], capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            for r in json.loads(res.stdout):
                if r.get('node') == node:
                    tot = int(r.get('maxdisk', 0))
                    usd = int(r.get('disk', 0))
                    storage.append({
                        'name': r.get('storage'),
                        'type': r.get('plugintype'),
                        'status': 'active' if r.get('status')=='available' else 'error',
                        'total': round(tot/(1024**3), 2),
                        'used': round(usd/(1024**3), 2),
                        'percent': round((usd/tot)*100, 1) if tot>0 else 0
                    })
    except: pass
    
    if proxmox_storage_monitor:
        u = proxmox_storage_monitor.get_storage_status().get('unavailable', [])
        exist = {x['name'] for x in storage}
        for x in u:
            if x['name'] not in exist: storage.append(x)
            
    return {'storage': storage}

def get_backups():
    """Lista backups."""
    backups = []
    try:
        res = subprocess.run(['pvesh', 'get', '/storage', '--output-format', 'json'], capture_output=True, text=True)
        if res.returncode == 0:
            for s in json.loads(res.stdout):
                sid = s.get('storage')
                if s.get('type') in ['dir', 'nfs', 'cifs', 'pbs']:
                    c_res = subprocess.run(['pvesh', 'get', f'/nodes/localhost/storage/{sid}/content', '--output-format', 'json'], capture_output=True, text=True)
                    if c_res.returncode == 0:
                        for item in json.loads(c_res.stdout):
                            if item.get('content') == 'backup':
                                volid = item.get('volid', '')
                                vmid = None
                                if 'vzdump-qemu-' in volid:
                                    try: vmid = volid.split('vzdump-qemu-')[1].split('-')[0]
                                    except: pass
                                elif 'vzdump-lxc-' in volid:
                                    try: vmid = volid.split('vzdump-lxc-')[1].split('-')[0]
                                    except: pass
                                    
                                from datetime import datetime
                                backups.append({
                                    'volid': volid, 'storage': sid, 'vmid': vmid,
                                    'size': item.get('size', 0),
                                    'size_human': format_bytes(item.get('size', 0)),
                                    'created': datetime.fromtimestamp(item.get('ctime', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                                    'timestamp': item.get('ctime', 0)
                                })
    except: pass
    backups.sort(key=lambda x: x['timestamp'], reverse=True)
    return {'backups': backups, 'total': len(backups)}