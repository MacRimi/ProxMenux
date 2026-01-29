import json
import subprocess
import os
import re
from system_monitor import get_proxmox_node_name

def parse_lxc_hardware_config(vmid, node):
    """
    Analiza la configuración de un LXC para detectar passthrough de hardware.
    Detecta GPUs, TPUs (Coral), dispositivos USB y estado privilegiado.
    """
    hardware_info = {
        'privileged': None,
        'gpu_passthrough': [],
        'devices': []
    }
    
    try:
        config_path = f'/etc/pve/lxc/{vmid}.conf'
        
        if not os.path.exists(config_path):
            return hardware_info
        
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        # Verificar estado privilegiado
        if 'unprivileged: 1' in config_content:
            hardware_info['privileged'] = False
        elif 'unprivileged: 0' in config_content:
            hardware_info['privileged'] = True
        else:
            # Chequeos adicionales
            if 'lxc.cap.drop:' in config_content and 'lxc.cap.drop: \n' in config_content:
                hardware_info['privileged'] = True
            elif 'lxc.cgroup2.devices.allow: a' in config_content:
                hardware_info['privileged'] = True
        
        # Detección de GPU Passthrough
        gpu_types = []
        if '/dev/dri' in config_content or 'renderD128' in config_content:
            if 'Intel/AMD GPU' not in gpu_types: gpu_types.append('Intel/AMD GPU')
        
        if 'nvidia' in config_content.lower():
            if any(x in config_content for x in ['nvidia0', 'nvidiactl', 'nvidia-uvm']):
                if 'NVIDIA GPU' not in gpu_types: gpu_types.append('NVIDIA GPU')
        
        hardware_info['gpu_passthrough'] = gpu_types
        
        # Detección de otros dispositivos
        devices = []
        if 'apex' in config_content.lower() or 'coral' in config_content.lower(): devices.append('Coral TPU')
        if 'ttyUSB' in config_content or 'ttyACM' in config_content: devices.append('USB Serial Devices')
        if '/dev/bus/usb' in config_content: devices.append('USB Passthrough')
        if '/dev/fb0' in config_content: devices.append('Framebuffer')
        if '/dev/snd' in config_content: devices.append('Audio Devices')
        if '/dev/input' in config_content: devices.append('Input Devices')
        if 'tty7' in config_content: devices.append('TTY Console')
        
        hardware_info['devices'] = devices
        
    except Exception:
        pass
    
    return hardware_info

def get_lxc_ip_from_lxc_info(vmid):
    """
    Obtiene las IPs de un contenedor LXC usando 'lxc-info' (útil para DHCP).
    """
    try:
        result = subprocess.run(['lxc-info', '-n', str(vmid), '-iH'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            ips = result.stdout.strip().split()
            real_ips = [ip for ip in ips if not ip.startswith('172.')] # Filtrar IPs internas de Docker usualmente
            docker_ips = [ip for ip in ips if ip.startswith('172.')]
            
            return {
                'all_ips': ips,
                'real_ips': real_ips,
                'docker_ips': docker_ips,
                'primary_ip': real_ips[0] if real_ips else (docker_ips[0] if docker_ips else ips[0])
            }
    except Exception:
        pass
    return None

def get_proxmox_vms():
    """
    Obtiene la lista de todas las VMs y Contenedores del nodo local.
    """
    local_node = get_proxmox_node_name()
    vms = []
    
    try:
        result = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            for item in json.loads(result.stdout):
                if item.get('node') == local_node:
                    vms.append({
                        'vmid': item.get('vmid'),
                        'name': item.get('name', f"VM-{item.get('vmid')}"),
                        'status': item.get('status', 'unknown'),
                        'type': 'lxc' if item.get('type') == 'lxc' else 'qemu',
                        'cpu': item.get('cpu', 0),
                        'mem': item.get('mem', 0),
                        'maxmem': item.get('maxmem', 0),
                        'disk': item.get('disk', 0),
                        'maxdisk': item.get('maxdisk', 0),
                        'uptime': item.get('uptime', 0),
                        'netin': item.get('netin', 0),
                        'netout': item.get('netout', 0),
                        'diskread': item.get('diskread', 0),
                        'diskwrite': item.get('diskwrite', 0)
                    })
    except Exception:
        pass
    return vms

def get_vm_config(vmid):
    """
    Obtiene la configuración detallada de una VM específica.
    Incluye detección de hardware y SO para LXC.
    """
    node = get_proxmox_node_name()
    
    # Intentar obtener config como QEMU (VM)
    res = subprocess.run(['pvesh', 'get', f'/nodes/{node}/qemu/{vmid}/config', '--output-format', 'json'], 
                         capture_output=True, text=True, timeout=5)
    
    vm_type = 'qemu'
    if res.returncode != 0:
        # Si falla, intentar como LXC (Contenedor)
        res = subprocess.run(['pvesh', 'get', f'/nodes/{node}/lxc/{vmid}/config', '--output-format', 'json'], 
                             capture_output=True, text=True, timeout=5)
        vm_type = 'lxc'
        
    if res.returncode == 0:
        config = json.loads(res.stdout)
        
        # Obtener estado
        status_res = subprocess.run(['pvesh', 'get', f'/nodes/{node}/{vm_type}/{vmid}/status/current', '--output-format', 'json'],
                                  capture_output=True, text=True, timeout=5)
        status = 'stopped'
        if status_res.returncode == 0:
            status = json.loads(status_res.stdout).get('status', 'stopped')
            
        response = {
            'vmid': vmid,
            'config': config,
            'node': node,
            'vm_type': vm_type,
            'status': status
        }
        
        # Enriquecimiento específico para LXC
        if vm_type == 'lxc':
            response['hardware_info'] = parse_lxc_hardware_config(vmid, node)
            if status == 'running':
                ip_info = get_lxc_ip_from_lxc_info(vmid)
                if ip_info: response['lxc_ip_info'] = ip_info
                
                # Intentar leer info del SO
                try:
                    os_res = subprocess.run(['pct', 'exec', str(vmid), '--', 'cat', '/etc/os-release'], 
                                          capture_output=True, text=True, timeout=5)
                    if os_res.returncode == 0:
                        os_info = {}
                        for line in os_res.stdout.split('\n'):
                            if line.startswith('ID='): os_info['id'] = line.split('=', 1)[1].strip('"\'')
                            elif line.startswith('PRETTY_NAME='): os_info['pretty_name'] = line.split('=', 1)[1].strip('"\'')
                        if os_info: response['os_info'] = os_info
                except: pass
                
        return response
    
    return None

def control_vm(vmid, action):
    """
    Ejecuta acciones de control: start, stop, shutdown, reboot.
    """
    if action not in ['start', 'stop', 'shutdown', 'reboot']:
        return {'success': False, 'message': 'Invalid action'}
        
    info = get_vm_config(vmid)
    if not info:
        return {'success': False, 'message': 'VM/LXC not found'}
    
    node = info['node']
    vm_type = info['vm_type']
    
    res = subprocess.run(['pvesh', 'create', f'/nodes/{node}/{vm_type}/{vmid}/status/{action}'], 
                       capture_output=True, text=True, timeout=30)
    
    if res.returncode == 0:
        return {'success': True, 'vmid': vmid, 'action': action, 'message': f'Successfully executed {action}'}
    else:
        return {'success': False, 'error': res.stderr}

def update_vm_config(vmid, description):
    """Actualiza la descripción/notas de la VM."""
    info = get_vm_config(vmid)
    if not info: return {'success': False, 'message': 'VM not found'}
    
    res = subprocess.run(['pvesh', 'set', f'/nodes/{info["node"]}/{info["vm_type"]}/{vmid}/config', '-description', description],
                       capture_output=True, text=True, timeout=30)
                       
    if res.returncode == 0:
        return {'success': True, 'message': 'Configuration updated'}
    return {'success': False, 'error': res.stderr}

def get_vm_metrics(vmid, timeframe='week'):
    """Obtiene métricas RRD históricas."""
    info = get_vm_config(vmid)
    if not info: return {'error': 'VM not found'}
    
    res = subprocess.run(['pvesh', 'get', f'/nodes/{info["node"]}/{info["vm_type"]}/{vmid}/rrddata', 
                        '--timeframe', timeframe, '--output-format', 'json'],
                       capture_output=True, text=True, timeout=10)
    
    if res.returncode == 0:
        return {'vmid': vmid, 'type': info['vm_type'], 'timeframe': timeframe, 'data': json.loads(res.stdout)}
    return {'error': f'Failed to get metrics: {res.stderr}'}

def get_vm_logs(vmid):
    """Obtiene logs internos (consola) de la VM/LXC."""
    info = get_vm_config(vmid)
    if not info: return {'error': 'VM not found'}
    
    res = subprocess.run(['pvesh', 'get', f'/nodes/{info["node"]}/{info["vm_type"]}/{vmid}/log', '--start', '0', '--limit', '1000'],
                       capture_output=True, text=True, timeout=10)
                       
    logs = []
    if res.returncode == 0:
        for i, line in enumerate(res.stdout.split('\n')):
            if line.strip(): logs.append({'n': i, 't': line})
            
    return {'vmid': vmid, 'name': info['config'].get('name'), 'logs': logs}

def get_task_log(upid):
    """Lee un archivo de log de tarea específico de Proxmox."""
    try:
        upid_clean = upid.rstrip(':')
        parts = upid_clean.split(':')
        if len(parts) < 5: return "Invalid UPID format"
        
        starttime = parts[4]
        index = starttime[-1].lower() # El directorio es el último carácter hexadecimal
        
        # Buscar en las rutas posibles
        paths = [
            f"/var/log/pve/tasks/{index}/{upid_clean}",
            f"/var/log/pve/tasks/{index.upper()}/{upid_clean}",
            f"/var/log/pve/tasks/{index}/{upid_clean}:"
        ]
        
        for p in paths:
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
                    
        return "Log file not found on disk"
    except Exception as e:
        return f"Error reading log: {str(e)}"