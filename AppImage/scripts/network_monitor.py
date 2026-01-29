import os
import re
import json
import socket
import psutil
import subprocess
from system_monitor import get_proxmox_node_name

def extract_vmid_from_interface(interface_name):
    """
    Extrae el ID de la VM del nombre de la interfaz.
    Ejemplo: veth100i0 -> 100 (LXC), tap105i0 -> 105 (VM)
    """
    try:
        match = re.match(r'(veth|tap)(\d+)i\d+', interface_name)
        if match:
            vmid = int(match.group(2))
            interface_type = 'lxc' if match.group(1) == 'veth' else 'vm'
            return vmid, interface_type
        return None, None
    except Exception:
        return None, None

def get_vm_lxc_names():
    """
    Crea un mapa de VMIDs a nombres (ej: 100 -> 'Servidor-Web').
    Ayuda a identificar qué interfaz pertenece a qué máquina.
    """
    vm_lxc_map = {}
    try:
        local_node = get_proxmox_node_name()
        # Consultamos pvesh para obtener la lista de VMs
        result = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            resources = json.loads(result.stdout)
            for resource in resources:
                if resource.get('node') == local_node:
                    vmid = resource.get('vmid')
                    if vmid:
                        vm_lxc_map[vmid] = {
                            'name': resource.get('name', f'VM-{vmid}'),
                            'type': 'lxc' if resource.get('type') == 'lxc' else 'vm',
                            'status': resource.get('status', 'unknown')
                        }
    except Exception:
        pass
    return vm_lxc_map

def get_interface_type(interface_name):
    """
    Clasifica la interfaz de red en tipos manejables.
    """
    if interface_name == 'lo': return 'skip'
    if interface_name.startswith(('veth', 'tap')): return 'vm_lxc'
    if interface_name.startswith(('tun', 'vnet', 'docker', 'virbr')): return 'skip'
    if interface_name.startswith('bond'): return 'bond'
    if interface_name.startswith(('vmbr', 'br')): return 'bridge'
    if '.' in interface_name: return 'vlan'
    
    # Verificar si es una interfaz física real
    if os.path.exists(f'/sys/class/net/{interface_name}/device'): return 'physical'
    # Fallback por nombre común
    if interface_name.startswith(('enp', 'eth', 'eno', 'ens', 'enx', 'wlan', 'wlp', 'wlo', 'usb')): return 'physical'
    
    return 'skip'

def get_bond_info(bond_name):
    """Obtiene detalles de una interfaz Bond (agregación de enlaces)."""
    info = {'mode': 'unknown', 'slaves': [], 'active_slave': None}
    try:
        path = f'/proc/net/bonding/{bond_name}'
        if os.path.exists(path):
            with open(path, 'r') as f:
                content = f.read()
                for line in content.split('\n'):
                    if 'Bonding Mode:' in line: info['mode'] = line.split(':', 1)[1].strip()
                    elif 'Slave Interface:' in line: info['slaves'].append(line.split(':', 1)[1].strip())
                    elif 'Currently Active Slave:' in line: info['active_slave'] = line.split(':', 1)[1].strip()
    except Exception: pass
    return info

def get_bridge_info(bridge_name):
    """
    Obtiene los miembros de un Bridge (puente).
    Intenta identificar la interfaz física real detrás del puente.
    """
    info = {'members': [], 'physical_interface': None, 'physical_duplex': 'unknown', 'bond_slaves': []}
    try:
        brif_path = f'/sys/class/net/{bridge_name}/brif'
        if os.path.exists(brif_path):
            members = os.listdir(brif_path)
            info['members'] = members
            
            for member in members:
                # Si el puente usa un bond
                if member.startswith('bond'):
                    info['physical_interface'] = member
                    bond_info = get_bond_info(member)
                    info['bond_slaves'] = bond_info['slaves']
                    if bond_info['active_slave']:
                        try:
                            stats = psutil.net_if_stats().get(bond_info['active_slave'])
                            if stats:
                                info['physical_duplex'] = 'full' if stats.duplex == 2 else 'half' if stats.duplex == 1 else 'unknown'
                        except: pass
                    break
                # Si el puente usa una interfaz física directa
                elif member.startswith(('enp', 'eth', 'eno', 'ens', 'wlan')):
                    info['physical_interface'] = member
                    try:
                        stats = psutil.net_if_stats().get(member)
                        if stats:
                            info['physical_duplex'] = 'full' if stats.duplex == 2 else 'half' if stats.duplex == 1 else 'unknown'
                    except: pass
                    break
    except Exception: pass
    return info

def get_network_info():
    """
    Obtiene información completa y detallada de TODA la red.
    """
    data = {
        'interfaces': [], 'physical_interfaces': [], 'bridge_interfaces': [], 'vm_lxc_interfaces': [],
        'traffic': {}, 'hostname': get_proxmox_node_name(), 'domain': None, 'dns_servers': []
    }
    
    # Leer configuración DNS
    try:
        with open('/etc/resolv.conf', 'r') as f:
            for line in f:
                if line.startswith('nameserver'): data['dns_servers'].append(line.split()[1])
                elif line.startswith('domain'): data['domain'] = line.split()[1]
                elif line.startswith('search') and not data['domain']: 
                    parts = line.split()
                    if len(parts) > 1: data['domain'] = parts[1]
    except: pass
    
    vm_map = get_vm_lxc_names()
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    io_counters = psutil.net_io_counters(pernic=True)
    
    # Contadores
    counts = {'physical': {'active':0, 'total':0}, 'bridge': {'active':0, 'total':0}, 'vm': {'active':0, 'total':0}}
    
    for name, stat in stats.items():
        itype = get_interface_type(name)
        if itype == 'skip': continue
        
        info = {
            'name': name, 'type': itype, 'status': 'up' if stat.isup else 'down',
            'speed': stat.speed, 'mtu': stat.mtu, 
            'duplex': 'full' if stat.duplex == 2 else 'half' if stat.duplex == 1 else 'unknown',
            'addresses': []
        }
        
        # IPs
        if name in addrs:
            for addr in addrs[name]:
                if addr.family == socket.AF_INET: # IPv4
                    info['addresses'].append({'ip': addr.address, 'netmask': addr.netmask})
                elif addr.family == 17: # MAC
                    info['mac_address'] = addr.address

        # Tráfico
        if name in io_counters:
            io = io_counters[name]
            # Si es VM, invertimos perspectiva (tx host = rx vm)
            if itype == 'vm_lxc':
                info.update({'bytes_sent': io.bytes_recv, 'bytes_recv': io.bytes_sent,
                             'packets_sent': io.packets_recv, 'packets_recv': io.packets_sent})
            else:
                info.update({'bytes_sent': io.bytes_sent, 'bytes_recv': io.bytes_recv,
                             'packets_sent': io.packets_sent, 'packets_recv': io.packets_recv})
                
            info.update({'errors_in': io.errin, 'errors_out': io.errout, 
                         'drops_in': io.dropin, 'drops_out': io.dropout})

        # Clasificación
        if itype == 'vm_lxc':
            counts['vm']['total'] += 1
            if stat.isup: counts['vm']['active'] += 1
            
            vmid, _ = extract_vmid_from_interface(name)
            if vmid and vmid in vm_map:
                info.update({'vmid': vmid, 'vm_name': vm_map[vmid]['name'], 
                             'vm_type': vm_map[vmid]['type'], 'vm_status': vm_map[vmid]['status']})
            elif vmid:
                info.update({'vmid': vmid, 'vm_name': f'VM/LXC {vmid}', 'vm_status': 'unknown'})
            
            data['vm_lxc_interfaces'].append(info)
            
        elif itype == 'physical':
            counts['physical']['total'] += 1
            if stat.isup: counts['physical']['active'] += 1
            data['physical_interfaces'].append(info)
            
        elif itype == 'bridge':
            counts['bridge']['total'] += 1
            if stat.isup: counts['bridge']['active'] += 1
            b_info = get_bridge_info(name)
            info['bridge_members'] = b_info['members']
            info['bridge_physical_interface'] = b_info['physical_interface']
            if b_info['physical_duplex'] != 'unknown':
                info['duplex'] = b_info['physical_duplex']
            data['bridge_interfaces'].append(info)
            
        elif itype == 'bond':
            bond_info = get_bond_info(name)
            info.update({'bond_mode': bond_info['mode'], 'bond_slaves': bond_info['slaves'], 
                         'bond_active_slave': bond_info['active_slave']})
            data['interfaces'].append(info)
            
    # Tráfico global
    g_io = psutil.net_io_counters()
    data['traffic'] = {
        'bytes_sent': g_io.bytes_sent, 'bytes_recv': g_io.bytes_recv,
        'packets_sent': g_io.packets_sent, 'packets_recv': g_io.packets_recv,
        'packet_loss_in': 0, 'packet_loss_out': 0
    }
    
    tin = g_io.packets_recv + g_io.dropin
    if tin > 0: data['traffic']['packet_loss_in'] = round((g_io.dropin / tin) * 100, 2)
    tout = g_io.packets_sent + g_io.dropout
    if tout > 0: data['traffic']['packet_loss_out'] = round((g_io.dropout / tout) * 100, 2)
    
    data.update({
        'physical_active_count': counts['physical']['active'], 'physical_total_count': counts['physical']['total'],
        'bridge_active_count': counts['bridge']['active'], 'bridge_total_count': counts['bridge']['total'],
        'vm_lxc_active_count': counts['vm']['active'], 'vm_lxc_total_count': counts['vm']['total']
    })
    
    return data

def get_network_summary():
    """Resumen rápido de red."""
    net_io = psutil.net_io_counters()
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    
    phys_ifaces = []
    bridge_ifaces = []
    counts = {'phys_active':0, 'phys_total':0, 'br_active':0, 'br_total':0}
    
    for name, stat in stats.items():
        if name in ['lo', 'docker0'] or name.startswith(('veth', 'tap', 'fw')): continue
        is_up = stat.isup
        addresses = []
        if name in addrs:
            for addr in addrs[name]:
                if addr.family == socket.AF_INET:
                    addresses.append({'ip': addr.address, 'netmask': addr.netmask})
        info = {'name': name, 'status': 'up' if is_up else 'down', 'addresses': addresses}
        
        if name.startswith(('enp', 'eth', 'eno', 'ens', 'wlan')):
            counts['phys_total'] += 1
            if is_up: counts['phys_active'] += 1
            phys_ifaces.append(info)
        elif name.startswith(('vmbr', 'br')):
            counts['br_total'] += 1
            if is_up: counts['br_active'] += 1
            bridge_ifaces.append(info)
            
    return {
        'physical_active_count': counts['phys_active'], 'physical_total_count': counts['phys_total'],
        'bridge_active_count': counts['br_active'], 'bridge_total_count': counts['br_total'],
        'physical_interfaces': phys_ifaces, 'bridge_interfaces': bridge_ifaces,
        'traffic': {'bytes_sent': net_io.bytes_sent, 'bytes_recv': net_io.bytes_recv,
                    'packets_sent': net_io.packets_sent, 'packets_recv': net_io.packets_recv}
    }

def get_interface_metrics(interface_name, timeframe='day'):
    """Obtiene métricas RRD históricas para una interfaz."""
    local_node = get_proxmox_node_name()
    itype = get_interface_type(interface_name)
    rrd_data = []
    
    try:
        # Si es VM/LXC, sacamos datos del contenedor/VM
        if itype == 'vm_lxc':
            vmid, vm_type = extract_vmid_from_interface(interface_name)
            if vmid:
                res = subprocess.run(['pvesh', 'get', f'/nodes/{local_node}/{vm_type}/{vmid}/rrddata',
                                    '--timeframe', timeframe, '--output-format', 'json'],
                                   capture_output=True, text=True, timeout=10)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    for point in data:
                        item = {'time': point.get('time')}
                        if 'netin' in point: item['netin'] = point['netin']
                        if 'netout' in point: item['netout'] = point['netout']
                        rrd_data.append(item)
        else:
            # Si es física/bridge, sacamos datos del nodo (tráfico total del nodo)
            res = subprocess.run(['pvesh', 'get', f'/nodes/{local_node}/rrddata', 
                                '--timeframe', timeframe, '--output-format', 'json'],
                               capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for point in data:
                    item = {'time': point.get('time')}
                    if 'netin' in point: item['netin'] = point['netin']
                    if 'netout' in point: item['netout'] = point['netout']
                    rrd_data.append(item)
                    
        return {'interface': interface_name, 'type': itype, 'timeframe': timeframe, 'data': rrd_data}
    except Exception as e:
        return {'error': str(e)}