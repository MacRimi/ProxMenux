import os
import sys
import time
import socket
import subprocess
import json
import psutil
import platform
from datetime import datetime, timedelta

# Cache para evitar llamadas excesivas a la API de Proxmox
_PROXMOX_NODE_CACHE = {"name": None, "timestamp": 0.0}
_PROXMOX_NODE_CACHE_TTL = 300  # 5 minutos

def get_proxmox_node_name() -> str:
    """Recupera el nombre real del nodo Proxmox con caché."""
    now = time.time()
    cached_name = _PROXMOX_NODE_CACHE.get("name")
    cached_ts = _PROXMOX_NODE_CACHE.get("timestamp", 0.0)

    if cached_name and (now - float(cached_ts)) < _PROXMOX_NODE_CACHE_TTL:
        return str(cached_name)

    try:
        result = subprocess.run(
            ["pvesh", "get", "/nodes", "--output-format", "json"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode == 0 and result.stdout:
            nodes = json.loads(result.stdout)
            if isinstance(nodes, list) and nodes:
                node_name = nodes[0].get("node")
                if node_name:
                    _PROXMOX_NODE_CACHE["name"] = node_name
                    _PROXMOX_NODE_CACHE["timestamp"] = now
                    return node_name
    except Exception:
        pass

    hostname = socket.gethostname()
    return hostname.split(".", 1)[0]

def get_uptime():
    """Obtiene el tiempo de actividad del sistema."""
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        return str(timedelta(seconds=int(uptime_seconds)))
    except Exception:
        return "N/A"

def get_cpu_temperature():
    """Obtiene la temperatura de la CPU usando psutil."""
    temp = 0
    try:
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if temps:
                sensor_priority = ['coretemp', 'k10temp', 'cpu_thermal', 'zenpower', 'acpitz']
                for sensor_name in sensor_priority:
                    if sensor_name in temps and temps[sensor_name]:
                        temp = temps[sensor_name][0].current
                        break
                if temp == 0:
                    for name, entries in temps.items():
                        if entries:
                            temp = entries[0].current
                            break
    except Exception:
        pass
    return temp

def get_proxmox_version():
    """Obtiene la versión de Proxmox."""
    try:
        result = subprocess.run(['pveversion'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version_line = result.stdout.strip().split('\n')[0]
            if '/' in version_line:
                return version_line.split('/')[1]
    except Exception:
        pass
    return None

def get_available_updates():
    """Cuenta actualizaciones pendientes."""
    try:
        result = subprocess.run(['apt', 'list', '--upgradable'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            return max(0, len(lines) - 1)
    except Exception:
        pass
    return 0

def get_system_info():
    """Agrega toda la información del sistema."""
    cpu_usage = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory()
    load_avg = os.getloadavg()
    
    return {
        'cpu_usage': round(cpu_usage, 1),
        'memory_usage': round(memory.percent, 1),
        'memory_total': round(memory.total / (1024 ** 3), 1),
        'memory_used': round(memory.used / (1024 ** 3), 1),
        'temperature': get_cpu_temperature(),
        'uptime': get_uptime(),
        'load_average': list(load_avg),
        'hostname': socket.gethostname(),
        'proxmox_node': get_proxmox_node_name(),
        'node_id': socket.gethostname(),
        'timestamp': datetime.now().isoformat(),
        'cpu_cores': psutil.cpu_count(logical=False),
        'cpu_threads': psutil.cpu_count(logical=True),
        'proxmox_version': get_proxmox_version(),
        'kernel_version': platform.release(),
        'available_updates': get_available_updates()
    }

def get_node_metrics(timeframe='week'):
    """Obtiene métricas RRD del nodo."""
    local_node = get_proxmox_node_name()
    zfs_arc_size = 0
    
    try:
        with open('/proc/spl/kstat/zfs/arcstats', 'r') as f:
            for line in f:
                if line.startswith('size'):
                    parts = line.split()
                    if len(parts) >= 3:
                        zfs_arc_size = int(parts[2])
                        break
    except Exception:
        pass

    try:
        result = subprocess.run(
            ['pvesh', 'get', f'/nodes/{local_node}/rrddata', '--timeframe', timeframe, '--output-format', 'json'],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            rrd_data = json.loads(result.stdout)
            if zfs_arc_size > 0:
                for item in rrd_data:
                    if 'zfsarc' not in item or item.get('zfsarc', 0) == 0:
                        item['zfsarc'] = zfs_arc_size
            return {'node': local_node, 'timeframe': timeframe, 'data': rrd_data}
        else:
            return {'error': f"Failed to get RRD data: {result.stderr}"}
    except Exception as e:
        return {'error': str(e)}

def get_logs(limit='200', priority=None, service=None, since_days=None):
    """Obtiene logs del sistema (journalctl)."""
    cmd = ['journalctl', '--output', 'json', '--no-pager']
    
    if since_days:
        try:
            days = int(since_days)
            cmd.extend(['--since', f'{days} days ago'])
        except ValueError:
             cmd.extend(['-n', limit])
    else:
        cmd.extend(['-n', limit])
    
    if priority:
        cmd.extend(['-p', priority])
    if service:
        cmd.extend(['-u', service])
        
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logs = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        entry = json.loads(line)
                        ts_us = int(entry.get('__REALTIME_TIMESTAMP', '0'))
                        timestamp = datetime.fromtimestamp(ts_us / 1000000).strftime('%Y-%m-%d %H:%M:%S')
                        priority_map = {'0': 'emerg', '1': 'alert', '2': 'crit', '3': 'err', '4': 'warning', '5': 'notice', '6': 'info', '7': 'debug'}
                        p_num = str(entry.get('PRIORITY', '6'))
                        
                        logs.append({
                            'timestamp': timestamp,
                            'level': priority_map.get(p_num, 'info'),
                            'service': entry.get('_SYSTEMD_UNIT', entry.get('SYSLOG_IDENTIFIER', 'system')),
                            'message': entry.get('MESSAGE', ''),
                            'source': 'journal',
                            'pid': entry.get('_PID', ''),
                            'hostname': entry.get('_HOSTNAME', '')
                        })
                    except Exception:
                        continue
            return {'logs': logs, 'total': len(logs)}
    except Exception as e:
        return {'logs': [], 'total': 0, 'error': str(e)}
    return {'logs': [], 'total': 0, 'error': 'journalctl failed'}

def generate_log_file(log_type, hours, level, service, since_days):
    """Genera archivo de logs temporal."""
    import tempfile
    cmd = ['journalctl', '--no-pager']
    if since_days: cmd.extend(['--since', f'{since_days} days ago'])
    else: cmd.extend(['--since', f'{hours} hours ago'])
    
    if log_type == 'kernel': cmd.append('-k')
    elif log_type == 'auth': cmd.extend(['-u', 'ssh', '-u', 'sshd'])
    
    if level != 'all': cmd.extend(['-p', level])
    if service != 'all': cmd.extend(['-u', service])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write(f"ProxMenux Log ({log_type}) - Generated: {datetime.now().isoformat()}\n")
            f.write("=" * 80 + "\n\n")
            f.write(result.stdout if result.returncode == 0 else "Error retrieving logs")
            return f.name
    except Exception:
        return None

def get_events(limit='50'):
    """Obtiene eventos de Proxmox."""
    events = []
    try:
        result = subprocess.run(['pvesh', 'get', '/cluster/tasks', '--output-format', 'json'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            tasks = json.loads(result.stdout)
            for task in tasks[:int(limit)]:
                starttime = task.get('starttime', 0)
                endtime = task.get('endtime', 0)
                duration = ''
                if endtime and starttime:
                    d_sec = endtime - starttime
                    if d_sec < 60: duration = f"{d_sec}s"
                    elif d_sec < 3600: duration = f"{d_sec // 60}m {d_sec % 60}s"
                    else: duration = f"{d_sec // 3600}h {(d_sec % 3600) // 60}m"
                
                status = task.get('status', 'unknown')
                level = 'info'
                if status == 'OK': level = 'info'
                elif status in ['stopped', 'error']: level = 'error'
                elif status == 'running': level = 'warning'

                events.append({
                    'upid': task.get('upid', ''),
                    'type': task.get('type', 'unknown'),
                    'status': status,
                    'level': level,
                    'user': task.get('user', 'unknown'),
                    'node': task.get('node', 'unknown'),
                    'vmid': str(task.get('id', '')) if task.get('id') else '',
                    'starttime': datetime.fromtimestamp(starttime).strftime('%Y-%m-%d %H:%M:%S') if starttime else '',
                    'endtime': datetime.fromtimestamp(endtime).strftime('%Y-%m-%d %H:%M:%S') if endtime else 'Running',
                    'duration': duration
                })
    except Exception:
        pass
    return {'events': events, 'total': len(events)}

def get_notifications():
    """Obtiene notificaciones de Proxmox."""
    notifications = []
    try:
        cmd = [
            'journalctl', '-u', 'pve-ha-lrm', '-u', 'pve-ha-crm', '-u', 'pvedaemon', 
            '-u', 'pveproxy', '-u', 'pvestatd', '--grep', 'notification|email|webhook|alert|notify',
            '-n', '100', '--output', 'json', '--no-pager'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        entry = json.loads(line)
                        ts = int(entry.get('__REALTIME_TIMESTAMP', '0'))
                        timestamp = datetime.fromtimestamp(ts / 1000000).strftime('%Y-%m-%d %H:%M:%S')
                        msg = entry.get('MESSAGE', '')
                        ntype = 'info'
                        if 'email' in msg.lower(): ntype = 'email'
                        elif 'webhook' in msg.lower(): ntype = 'webhook'
                        elif 'error' in msg.lower() or 'fail' in msg.lower(): ntype = 'error'
                        elif 'alert' in msg.lower() or 'warning' in msg.lower(): ntype = 'alert'
                        
                        notifications.append({
                            'timestamp': timestamp,
                            'type': ntype,
                            'service': entry.get('_SYSTEMD_UNIT', 'proxmox'),
                            'message': msg,
                            'source': 'journal'
                        })
                    except: continue
        
        # Backups en tareas
        task_res = subprocess.run(['pvesh', 'get', '/cluster/tasks', '--output-format', 'json'], capture_output=True, text=True, timeout=5)
        if task_res.returncode == 0:
            tasks = json.loads(task_res.stdout)
            for task in tasks[:50]:
                if task.get('type') in ['vzdump', 'backup']:
                    status = task.get('status', 'unknown')
                    ntype = 'success' if status == 'OK' else 'error' if status == 'stopped' else 'info'
                    notifications.append({
                        'timestamp': datetime.fromtimestamp(task.get('starttime', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                        'type': ntype,
                        'service': 'backup',
                        'message': f"Backup task {task.get('upid', 'unknown')}: {status}",
                        'source': 'task-log'
                    })
    except: pass
    
    notifications.sort(key=lambda x: x['timestamp'], reverse=True)
    return {'notifications': notifications[:100], 'total': len(notifications)}

def get_prometheus_metrics():
    """Genera métricas Prometheus."""
    node = socket.gethostname()
    timestamp = int(datetime.now().timestamp() * 1000)
    lines = []
    
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    load = os.getloadavg()
    uptime = time.time() - psutil.boot_time()
    
    lines.append(f'proxmox_cpu_usage{{node="{node}"}} {cpu} {timestamp}')
    lines.append(f'proxmox_memory_usage_percent{{node="{node}"}} {mem.percent} {timestamp}')
    lines.append(f'proxmox_load_average{{node="{node}",period="1m"}} {load[0]} {timestamp}')
    lines.append(f'proxmox_uptime_seconds{{node="{node}"}} {uptime} {timestamp}')
    
    temp = get_cpu_temperature()
    if temp:
        lines.append(f'proxmox_cpu_temperature_celsius{{node="{node}"}} {temp} {timestamp}')
    
    return '\n'.join(lines) + '\n', {'Content-Type': 'text/plain; version=0.0.4; charset=utf-8'}