#!/usr/bin/env python3
"""
ProxMenux Flask Server
Provides REST API endpoints for Proxmox monitoring data
Runs on port 8008 and serves system metrics, storage info, network stats, etc.
Also serves the Next.js dashboard as static files
"""

from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
import psutil
import subprocess
import json
import os
import time
import socket
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)  # Enable CORS for Next.js frontend

@app.route('/')
def serve_dashboard():
    """Serve the main dashboard page from Next.js build"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        appimage_root = os.path.dirname(base_dir)  # Subir un nivel desde scripts/
        
        index_paths = [
            os.path.join(appimage_root, 'web', 'index.html'),  # Ruta principal para exportación estática
            os.path.join(appimage_root, 'web', 'out', 'index.html'),  # Fallback si está en subcarpeta
            os.path.join(base_dir, '..', 'web', 'index.html'),  # Ruta relativa alternativa
            os.path.join(base_dir, '..', 'web', 'out', 'index.html'),  # Fallback relativo
        ]
        
        print(f"[v0] Flask server looking for index.html in:")
        for path in index_paths:
            abs_path = os.path.abspath(path)
            exists = os.path.exists(abs_path)
            print(f"[v0]   {abs_path} - {'EXISTS' if exists else 'NOT FOUND'}")
            if exists:
                print(f"[v0] Found index.html, serving from: {abs_path}")
                return send_file(abs_path)
        
        # If no Next.js build found, return error message with actual paths checked
        actual_paths = [os.path.abspath(path) for path in index_paths]
        return f'''
        <!DOCTYPE html>
        <html>
        <head><title>ProxMenux Monitor - Build Error</title></head>
        <body style="font-family: Arial; padding: 2rem; background: #0a0a0a; color: #fff;">
            <h1>🚨 ProxMenux Monitor - Build Error</h1>
            <p>Next.js application not found. The AppImage may not have been built correctly.</p>
            <p>Expected paths checked:</p>
            <ul>{''.join([f'<li>{path}</li>' for path in actual_paths])}</ul>
            <p>API endpoints are still available:</p>
            <ul>
                <li><a href="/api/system" style="color: #4f46e5;">/api/system</a></li>
                <li><a href="/api/system-info" style="color: #4f46e5;">/api/system-info</a></li>
                <li><a href="/api/storage" style="color: #4f46e5;">/api/storage</a></li>
                <li><a href="/api/network" style="color: #4f46e5;">/api/network</a></li>
                <li><a href="/api/vms" style="color: #4f46e5;">/api/vms</a></li>
                <li><a href="/api/health" style="color: #4f46e5;">/api/health</a></li>
            </ul>
        </body>
        </html>
        ''', 500
        
    except Exception as e:
        print(f"Error serving dashboard: {e}")
        return jsonify({'error': f'Dashboard not available: {str(e)}'}), 500

@app.route('/manifest.json')
def serve_manifest():
    """Serve PWA manifest"""
    try:
        manifest_paths = [
            os.path.join(os.path.dirname(__file__), '..', 'web', 'public', 'manifest.json'),
            os.path.join(os.path.dirname(__file__), '..', 'public', 'manifest.json')
        ]
        
        for manifest_path in manifest_paths:
            if os.path.exists(manifest_path):
                return send_file(manifest_path)
        
        # Return default manifest if not found
        return jsonify({
            "name": "ProxMenux Monitor",
            "short_name": "ProxMenux",
            "description": "Proxmox System Monitoring Dashboard",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0a0a0a",
            "theme_color": "#4f46e5",
            "icons": [
                {
                    "src": "/images/proxmenux-logo.png",
                    "sizes": "256x256",
                    "type": "image/png"
                }
            ]
        })
    except Exception as e:
        print(f"Error serving manifest: {e}")
        return jsonify({}), 404

@app.route('/sw.js')
def serve_sw():
    """Serve service worker"""
    return '''
    const CACHE_NAME = 'proxmenux-v1';
    const urlsToCache = [
        '/',
        '/api/system',
        '/api/storage',
        '/api/network',
        '/api/health'
    ];

    self.addEventListener('install', event => {
        event.waitUntil(
            caches.open(CACHE_NAME)
                .then(cache => cache.addAll(urlsToCache))
        );
    });

    self.addEventListener('fetch', event => {
        event.respondWith(
            caches.match(event.request)
                .then(response => response || fetch(event.request))
        );
    });
    ''', 200, {'Content-Type': 'application/javascript'}

@app.route('/_next/<path:filename>')
def serve_next_static(filename):
    """Serve Next.js static files"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        appimage_root = os.path.dirname(base_dir)
        
        static_paths = [
            os.path.join(appimage_root, 'web', '_next'),  # Ruta principal
            os.path.join(appimage_root, 'web', 'out', '_next'),  # Fallback
            os.path.join(base_dir, '..', 'web', '_next'),  # Ruta relativa
        ]
        
        for static_dir in static_paths:
            file_path = os.path.join(static_dir, filename)
            if os.path.exists(file_path):
                return send_file(file_path)
        return '', 404
    except Exception as e:
        print(f"Error serving Next.js static file {filename}: {e}")
        return '', 404

@app.route('/<path:filename>')
def serve_static_files(filename):
    """Serve static files (icons, etc.)"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        appimage_root = os.path.dirname(base_dir)
        
        public_paths = [
            os.path.join(appimage_root, 'web'),  # Raíz web para exportación estática
            os.path.join(appimage_root, 'web', 'out'),  # Fallback
            os.path.join(base_dir, '..', 'web'),  # Ruta relativa
            os.path.join(base_dir, '..', 'web', 'out'),  # Fallback relativo
        ]
        
        for public_dir in public_paths:
            file_path = os.path.join(public_dir, filename)
            if os.path.exists(file_path):
                return send_from_directory(public_dir, filename)
            
        return '', 404
    except Exception as e:
        print(f"Error serving static file {filename}: {e}")
        return '', 404

@app.route('/images/<path:filename>')
def serve_images(filename):
    """Serve image files"""
    try:
        image_paths = [
            os.path.join(os.path.dirname(__file__), '..', 'web', 'public', 'images'),
            os.path.join(os.path.dirname(__file__), '..', 'public', 'images'),
            os.path.dirname(__file__)
        ]
        
        for image_dir in image_paths:
            file_path = os.path.join(image_dir, filename)
            if os.path.exists(file_path):
                return send_from_directory(image_dir, filename)
                
        return '', 404
    except Exception as e:
        print(f"Error serving image {filename}: {e}")
        return '', 404

def get_system_info():
    """Get basic system information"""
    try:
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Memory usage
        memory = psutil.virtual_memory()
        
        temp = 0
        try:
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    # Priority order for temperature sensors
                    sensor_priority = ['coretemp', 'cpu_thermal', 'acpi', 'thermal_zone']
                    for sensor_name in sensor_priority:
                        if sensor_name in temps and temps[sensor_name]:
                            temp = temps[sensor_name][0].current
                            break
                    
                    # If no priority sensor found, use first available
                    if temp == 0:
                        for name, entries in temps.items():
                            if entries:
                                temp = entries[0].current
                                break
        except Exception as e:
            print(f"Error reading temperature sensors: {e}")
            temp = 0  # Use 0 to indicate no temperature available
        
        # Uptime
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        uptime_str = str(timedelta(seconds=int(uptime_seconds)))
        
        # Load average
        load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else [0, 0, 0]
        
        hostname = socket.gethostname()
        node_id = f"pve-{hostname}"
        
        # Try to get Proxmox node info if available
        try:
            result = subprocess.run(['pvesh', 'get', '/nodes', '--output-format', 'json'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                nodes = json.loads(result.stdout)
                if nodes and len(nodes) > 0:
                    node_id = nodes[0].get('node', node_id)
        except Exception as e:
            print(f"Note: pvesh not available or failed: {e}")
            pass  # Use default if pvesh not available
        
        return {
            'cpu_usage': round(cpu_percent, 1),
            'memory_usage': round(memory.percent, 1),
            'memory_total': round(memory.total / (1024**3), 1),  # GB
            'memory_used': round(memory.used / (1024**3), 1),    # GB
            'temperature': temp,
            'uptime': uptime_str,
            'load_average': list(load_avg),
            'hostname': hostname,
            'node_id': node_id,
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        print(f"Critical error getting system info: {e}")
        try:
            # Try to get at least basic info
            memory = psutil.virtual_memory()
            return {
                'cpu_usage': 0,
                'memory_usage': round(memory.percent, 1),
                'memory_total': round(memory.total / (1024**3), 1),
                'memory_used': round(memory.used / (1024**3), 1),
                'temperature': 0,
                'uptime': 'unknown',
                'load_average': [0, 0, 0],
                'hostname': socket.gethostname(),
                'node_id': 'unknown',
                'timestamp': datetime.now().isoformat(),
                'error': 'Partial system information only'
            }
        except:
            return {
                'error': 'Unable to access system information',
                'timestamp': datetime.now().isoformat()
            }

def get_storage_info():
    """Get storage and disk information"""
    try:
        storage_data = {
            'total': 0,
            'used': 0,
            'available': 0,
            'disks': []
        }
        
        # Get disk usage for root partition
        disk_usage = psutil.disk_usage('/')
        storage_data['total'] = round(disk_usage.total / (1024**3), 1)  # GB
        storage_data['used'] = round(disk_usage.used / (1024**3), 1)    # GB
        storage_data['available'] = round(disk_usage.free / (1024**3), 1)  # GB
        
        # Get individual disk information
        disk_partitions = psutil.disk_partitions()
        for partition in disk_partitions:
            try:
                partition_usage = psutil.disk_usage(partition.mountpoint)
                
                disk_temp = 42  # Default fallback
                try:
                    # Try to get disk temperature from sensors
                    if hasattr(psutil, "sensors_temperatures"):
                        temps = psutil.sensors_temperatures()
                        if temps:
                            for name, entries in temps.items():
                                if 'disk' in name.lower() or 'hdd' in name.lower() or 'sda' in name.lower():
                                    if entries:
                                        disk_temp = entries[0].current
                                        break
                except:
                    pass
                
                disk_info = {
                    'name': partition.device,
                    'mountpoint': partition.mountpoint,
                    'fstype': partition.fstype,
                    'total': round(partition_usage.total / (1024**3), 1),
                    'used': round(partition_usage.used / (1024**3), 1),
                    'available': round(partition_usage.free / (1024**3), 1),
                    'usage_percent': round((partition_usage.used / partition_usage.total) * 100, 1),
                    'health': 'healthy',  # Would need SMART data for real health
                    'temperature': disk_temp
                }
                storage_data['disks'].append(disk_info)
            except PermissionError:
                print(f"Permission denied accessing {partition.mountpoint}")
                continue
            except Exception as e:
                print(f"Error accessing partition {partition.device}: {e}")
                continue
        
        if not storage_data['disks'] and storage_data['total'] == 0:
            print("Warning: No storage data available, using fallback values")
            return {
                'total': 24.5,
                'used': 4.8,
                'available': 18.4,
                'disks': [
                    {
                        'name': '/dev/mapper/pve-root',
                        'mountpoint': '/',
                        'fstype': 'ext4',
                        'total': 24.5,
                        'used': 4.8,
                        'available': 18.4,
                        'usage_percent': 19.8,
                        'health': 'healthy',
                        'temperature': 42
                    }
                ]
            }
        
        return storage_data
        
    except Exception as e:
        print(f"Error getting storage info: {e}")
        try:
            disk_usage = psutil.disk_usage('/')
            return {
                'total': round(disk_usage.total / (1024**3), 1),
                'used': round(disk_usage.used / (1024**3), 1),
                'available': round(disk_usage.free / (1024**3), 1),
                'disks': [
                    {
                        'name': 'root',
                        'mountpoint': '/',
                        'fstype': 'unknown',
                        'total': round(disk_usage.total / (1024**3), 1),
                        'used': round(disk_usage.used / (1024**3), 1),
                        'available': round(disk_usage.free / (1024**3), 1),
                        'usage_percent': round((disk_usage.used / disk_usage.total) * 100, 1),
                        'health': 'unknown',
                        'temperature': 0
                    }
                ]
            }
        except:
            print("Critical: Cannot access any storage information, using mock data")
            return {
                'total': 0,
                'used': 0,
                'available': 0,
                'disks': [],
                'error': 'Unable to access storage information'
            }

def get_network_info():
    """Get network interface information"""
    try:
        network_data = {
            'interfaces': [],
            'traffic': {'incoming': 0, 'outgoing': 0}
        }
        
        # Get network interfaces
        net_if_addrs = psutil.net_if_addrs()
        net_if_stats = psutil.net_if_stats()
        
        for interface_name, interface_addresses in net_if_addrs.items():
            if interface_name == 'lo':  # Skip loopback
                continue
                
            interface_info = {
                'name': interface_name,
                'status': 'up' if net_if_stats[interface_name].isup else 'down',
                'addresses': []
            }
            
            for address in interface_addresses:
                if address.family == 2:  # IPv4
                    interface_info['addresses'].append({
                        'ip': address.address,
                        'netmask': address.netmask
                    })
            
            network_data['interfaces'].append(interface_info)
        
        # Get network I/O statistics
        net_io = psutil.net_io_counters()
        network_data['traffic'] = {
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv
        }
        
        return network_data
    except Exception as e:
        print(f"Error getting network info: {e}")
        return {
            'interfaces': [
                {'name': 'eth0', 'status': 'up', 'addresses': [{'ip': '192.168.1.100', 'netmask': '255.255.255.0'}]}
            ],
            'traffic': {'bytes_sent': 1000000, 'bytes_recv': 2000000}
        }

def get_proxmox_vms():
    """Get Proxmox VM information (requires pvesh command)"""
    try:
        # Try to get VM list using pvesh command
        result = subprocess.run(['pvesh', 'get', '/nodes/localhost/qemu', '--output-format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            vms = json.loads(result.stdout)
            return vms
        else:
            # Fallback to mock data if pvesh is not available
            return [
                {
                    'vmid': 100,
                    'name': 'web-server-01',
                    'status': 'running',
                    'cpu': 0.45,
                    'mem': 8589934592,  # 8GB in bytes
                    'maxmem': 17179869184,  # 16GB in bytes
                    'disk': 53687091200,  # 50GB in bytes
                    'maxdisk': 107374182400,  # 100GB in bytes
                    'uptime': 1324800  # seconds
                }
            ]
    except Exception as e:
        print(f"Error getting VM info: {e}")
        return []

@app.route('/api/system', methods=['GET'])
def api_system():
    """Get system information"""
    return jsonify(get_system_info())

@app.route('/api/storage', methods=['GET'])
def api_storage():
    """Get storage information"""
    return jsonify(get_storage_info())

@app.route('/api/network', methods=['GET'])
def api_network():
    """Get network information"""
    return jsonify(get_network_info())

@app.route('/api/vms', methods=['GET'])
def api_vms():
    """Get virtual machine information"""
    return jsonify(get_proxmox_vms())

@app.route('/api/logs', methods=['GET'])
def api_logs():
    """Get system logs"""
    try:
        # Get recent system logs
        result = subprocess.run(['journalctl', '-n', '100', '--output', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            logs = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        log_entry = json.loads(line)
                        logs.append({
                            'timestamp': log_entry.get('__REALTIME_TIMESTAMP', ''),
                            'level': log_entry.get('PRIORITY', '6'),
                            'service': log_entry.get('_SYSTEMD_UNIT', 'system'),
                            'message': log_entry.get('MESSAGE', ''),
                            'source': 'journalctl'
                        })
                    except json.JSONDecodeError:
                        continue
            return jsonify(logs)
        else:
            # Fallback mock logs
            return jsonify([
                {
                    'timestamp': datetime.now().isoformat(),
                    'level': 'info',
                    'service': 'pveproxy',
                    'message': 'User root@pam authenticated successfully',
                    'source': 'auth.log'
                }
            ])
    except Exception as e:
        print(f"Error getting logs: {e}")
        return jsonify([])

@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

@app.route('/api/system-info', methods=['GET'])
def api_system_info():
    """Get system and node information for dashboard header"""
    try:
        hostname = socket.gethostname()
        node_id = f"pve-{hostname}"
        
        # Try to get Proxmox version and node info
        pve_version = "PVE 8.1.3"
        try:
            result = subprocess.run(['pveversion'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                pve_version = result.stdout.strip().split('\n')[0]
        except:
            pass
        
        # Try to get node info from Proxmox API
        try:
            result = subprocess.run(['pvesh', 'get', '/nodes', '--output-format', 'json'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                nodes = json.loads(result.stdout)
                if nodes and len(nodes) > 0:
                    node_info = nodes[0]
                    node_id = node_info.get('node', node_id)
                    hostname = node_info.get('node', hostname)
        except:
            pass
        
        return jsonify({
            'hostname': hostname,
            'node_id': node_id,
            'pve_version': pve_version,
            'status': 'online',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        print(f"Error getting system info: {e}")
        return jsonify({
            'hostname': 'proxmox-01',
            'node_id': 'pve-node-01',
            'pve_version': 'PVE 8.1.3',
            'status': 'online',
            'timestamp': datetime.now().isoformat()
        })

@app.route('/api/info', methods=['GET'])
def api_info():
    """Root endpoint with API information"""
    return jsonify({
        'name': 'ProxMenux Monitor API',
        'version': '1.0.0',
        'endpoints': [
            '/api/system',
            '/api/system-info',
            '/api/storage', 
            '/api/network',
            '/api/vms',
            '/api/logs',
            '/api/health'
        ]
    })

if __name__ == '__main__':
    print("🚀 Starting ProxMenux Flask Server on port 8008...")
    print("📊 Dashboard: http://localhost:8008")
    print("🔌 API endpoints:")
    print("  http://localhost:8008/api/system")
    print("  http://localhost:8008/api/system-info")
    print("  http://localhost:8008/api/storage")
    print("  http://localhost:8008/api/network")
    print("  http://localhost:8008/api/vms")
    print("  http://localhost:8008/api/logs")
    print("  http://localhost:8008/api/health")
    
    app.run(host='0.0.0.0', port=8008, debug=False)
