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
        # Detectar si estamos ejecutándose desde AppImage
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            # Fallback: intentar detectar desde la ubicación del script
            base_dir = os.path.dirname(os.path.abspath(__file__))
            appimage_root = os.path.dirname(base_dir)  # Subir un nivel desde usr/bin/
        
        index_paths = [
            os.path.join(appimage_root, 'web', 'index.html'),  # Ruta principal para AppImage
            os.path.join(appimage_root, 'usr', 'web', 'index.html'),  # Fallback con usr/
            os.path.join(appimage_root, 'web', 'out', 'index.html'),  # Fallback si está en subcarpeta
            os.path.join(appimage_root, 'usr', 'web', 'out', 'index.html'),  # Fallback con usr/out/
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
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            appimage_root = os.path.dirname(base_dir)
        
        static_paths = [
            os.path.join(appimage_root, 'web', '_next'),  # Ruta principal
            os.path.join(appimage_root, 'usr', 'web', '_next'),  # Fallback con usr/
            os.path.join(appimage_root, 'web', 'out', '_next'),  # Fallback con out/
            os.path.join(appimage_root, 'usr', 'web', 'out', '_next'),  # Fallback con usr/out/
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
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            appimage_root = os.path.dirname(base_dir)
        
        public_paths = [
            os.path.join(appimage_root, 'web'),  # Raíz web para exportación estática
            os.path.join(appimage_root, 'usr', 'web'),  # Fallback con usr/
            os.path.join(appimage_root, 'web', 'out'),  # Fallback con out/
            os.path.join(appimage_root, 'usr', 'web', 'out'),  # Fallback con usr/out/
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
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            appimage_root = os.path.dirname(base_dir)
        
        image_paths = [
            os.path.join(appimage_root, 'web', 'images'),  # Ruta principal para exportación estática
            os.path.join(appimage_root, 'usr', 'web', 'images'),  # Fallback con usr/
            os.path.join(appimage_root, 'web', 'public', 'images'),  # Ruta con public/
            os.path.join(appimage_root, 'usr', 'web', 'public', 'images'),  # Fallback usr/public/
            os.path.join(appimage_root, 'public', 'images'),  # Ruta directa a public
            os.path.join(appimage_root, 'usr', 'public', 'images'),  # Fallback usr/public
        ]
        
        print(f"[v0] Looking for image: {filename}")
        for image_dir in image_paths:
            file_path = os.path.join(image_dir, filename)
            abs_path = os.path.abspath(file_path)
            exists = os.path.exists(abs_path)
            print(f"[v0]   Checking: {abs_path} - {'FOUND' if exists else 'NOT FOUND'}")
            if exists:
                print(f"[v0] Serving image from: {abs_path}")
                return send_from_directory(image_dir, filename)
        
        print(f"[v0] Image not found: {filename}")
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
        
        proxmox_version = None
        try:
            result = subprocess.run(['pveversion'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                # Parse output like "pve-manager/9.0.6/..."
                version_line = result.stdout.strip().split('\n')[0]
                if '/' in version_line:
                    proxmox_version = version_line.split('/')[1]
        except Exception as e:
            print(f"Note: pveversion not available: {e}")
        
        kernel_version = None
        try:
            result = subprocess.run(['uname', '-r'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                kernel_version = result.stdout.strip()
        except Exception as e:
            print(f"Note: uname not available: {e}")
        
        cpu_cores = psutil.cpu_count(logical=False)  # Physical cores only
        
        available_updates = 0
        try:
            result = subprocess.run(['apt', 'list', '--upgradable'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                # Count lines minus header
                lines = result.stdout.strip().split('\n')
                available_updates = max(0, len(lines) - 1)
        except Exception as e:
            print(f"Note: apt list not available: {e}")
        
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
        
        response = {
            'cpu_usage': round(cpu_percent, 1),
            'memory_usage': round(memory.percent, 1),
            'memory_total': round(memory.total / (1024**3), 1),  # GB
            'memory_used': round(memory.used / (1024**3), 1),    # GB
            'temperature': temp,
            'uptime': uptime_str,
            'load_average': list(load_avg),
            'hostname': hostname,
            'node_id': node_id,
            'timestamp': datetime.now().isoformat(),
            'cpu_cores': cpu_cores
        }
        
        if proxmox_version:
            response['proxmox_version'] = proxmox_version
        if kernel_version:
            response['kernel_version'] = kernel_version
        if available_updates > 0:
            response['available_updates'] = available_updates
        
        return response
    except Exception as e:
        print(f"Critical error getting system info: {e}")
        return {
            'error': f'Unable to access system information: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }

def get_storage_info():
    """Get storage and disk information"""
    try:
        storage_data = {
            'total': 0,
            'used': 0,
            'available': 0,
            'disks': [],
            'zfs_pools': [],
            'disk_count': 0,
            'healthy_disks': 0,
            'warning_disks': 0,
            'critical_disks': 0
        }
        
        physical_disks = {}
        total_disk_size_bytes = 0
        
        try:
            # List all block devices
            result = subprocess.run(['lsblk', '-b', '-d', '-n', '-o', 'NAME,SIZE,TYPE'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] == 'disk':
                        disk_name = parts[0]
                        disk_size_bytes = int(parts[1])
                        disk_size_gb = disk_size_bytes / (1024**3)
                        disk_size_tb = disk_size_bytes / (1024**4)
                        
                        total_disk_size_bytes += disk_size_bytes
                        
                        # Get SMART data for this disk
                        print(f"[v0] Getting SMART data for {disk_name}...")
                        smart_data = get_smart_data(disk_name)
                        print(f"[v0] SMART data for {disk_name}: {smart_data}")
                        
                        if disk_size_tb >= 1:
                            size_str = f"{disk_size_tb:.1f}T"
                        else:
                            size_str = f"{disk_size_gb:.1f}G"
                        
                        physical_disks[disk_name] = {
                            'name': disk_name,
                            'size': size_str,
                            'size_bytes': disk_size_bytes,
                            'temperature': smart_data.get('temperature', 0),
                            'health': smart_data.get('health', 'unknown'),
                            'power_on_hours': smart_data.get('power_on_hours', 0),
                            'smart_status': smart_data.get('smart_status', 'unknown'),
                            'model': smart_data.get('model', 'Unknown'),
                            'serial': smart_data.get('serial', 'Unknown'),
                            'reallocated_sectors': smart_data.get('reallocated_sectors', 0),
                            'pending_sectors': smart_data.get('pending_sectors', 0),
                            'crc_errors': smart_data.get('crc_errors', 0)
                        }
                        
                        storage_data['disk_count'] += 1
                        health = smart_data.get('health', 'unknown').lower()
                        if health == 'healthy':
                            storage_data['healthy_disks'] += 1
                        elif health == 'warning':
                            storage_data['warning_disks'] += 1
                        elif health in ['critical', 'failed']:
                            storage_data['critical_disks'] += 1
                            
        except Exception as e:
            print(f"Error getting disk list: {e}")
        
        storage_data['total'] = round(total_disk_size_bytes / (1024**4), 1)
        
        # Get disk usage for mounted partitions
        try:
            disk_partitions = psutil.disk_partitions()
            total_used = 0
            total_available = 0
            
            for partition in disk_partitions:
                try:
                    # Skip special filesystems
                    if partition.fstype in ['tmpfs', 'devtmpfs', 'squashfs', 'overlay']:
                        continue
                    
                    partition_usage = psutil.disk_usage(partition.mountpoint)
                    total_used += partition_usage.used
                    total_available += partition_usage.free
                    
                    # Extract disk name from partition device
                    device_name = partition.device.replace('/dev/', '')
                    if device_name[-1].isdigit():
                        if 'nvme' in device_name or 'mmcblk' in device_name:
                            base_disk = device_name.rsplit('p', 1)[0]
                        else:
                            base_disk = device_name.rstrip('0123456789')
                    else:
                        base_disk = device_name
                    
                    # Find corresponding physical disk
                    disk_info = physical_disks.get(base_disk)
                    if disk_info and 'mountpoint' not in disk_info:
                        disk_info['mountpoint'] = partition.mountpoint
                        disk_info['fstype'] = partition.fstype
                        disk_info['total'] = round(partition_usage.total / (1024**3), 1)
                        disk_info['used'] = round(partition_usage.used / (1024**3), 1)
                        disk_info['available'] = round(partition_usage.free / (1024**3), 1)
                        disk_info['usage_percent'] = round(partition_usage.percent, 1)
                        
                except PermissionError:
                    continue
                except Exception as e:
                    print(f"Error accessing partition {partition.device}: {e}")
                    continue
            
            storage_data['used'] = round(total_used / (1024**3), 1)
            storage_data['available'] = round(total_available / (1024**3), 1)
            
        except Exception as e:
            print(f"Error getting partition info: {e}")
        
        storage_data['disks'] = list(physical_disks.values())
        
        try:
            result = subprocess.run(['zpool', 'list', '-H', '-o', 'name,size,alloc,free,health'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split('\t')
                        if len(parts) >= 5:
                            pool_info = {
                                'name': parts[0],
                                'size': parts[1],
                                'allocated': parts[2],
                                'free': parts[3],
                                'health': parts[4]
                            }
                            storage_data['zfs_pools'].append(pool_info)
        except FileNotFoundError:
            print("Note: ZFS not installed")
        except Exception as e:
            print(f"Note: ZFS not available or no pools: {e}")
        
        return storage_data
        
    except Exception as e:
        print(f"Error getting storage info: {e}")
        return {
            'error': f'Unable to access storage information: {str(e)}',
            'total': 0,
            'used': 0,
            'available': 0,
            'disks': [],
            'zfs_pools': [],
            'disk_count': 0,
            'healthy_disks': 0,
            'warning_disks': 0,
            'critical_disks': 0
        }

def get_smart_data(disk_name):
    """Get SMART data for a specific disk - Enhanced with multiple device type attempts"""
    smart_data = {
        'temperature': 0,
        'health': 'unknown',
        'power_on_hours': 0,
        'smart_status': 'unknown',
        'model': 'Unknown',
        'serial': 'Unknown',
        'reallocated_sectors': 0,
        'pending_sectors': 0,
        'crc_errors': 0
    }
    
    print(f"[v0] ===== Starting SMART data collection for /dev/{disk_name} =====")
    
    try:
        commands_to_try = [
            ['smartctl', '-a', '-j', f'/dev/{disk_name}'],  # JSON output (preferred)
            ['smartctl', '-a', '-j', '-d', 'ata', f'/dev/{disk_name}'],  # JSON with ATA device type
            ['smartctl', '-a', '-j', '-d', 'sat', f'/dev/{disk_name}'],  # JSON with SAT device type
            ['smartctl', '-a', '-j', '-d', 'scsi', f'/dev/{disk_name}'],  # JSON with SCSI device type
            ['smartctl', '-a', f'/dev/{disk_name}'],  # Text output
            ['smartctl', '-a', '-d', 'ata', f'/dev/{disk_name}'],  # Text with ATA device type
            ['smartctl', '-a', '-d', 'sat', f'/dev/{disk_name}'],  # Text with SAT device type
            ['smartctl', '-i', '-H', f'/dev/{disk_name}'],  # Basic info + health only
        ]
        
        for cmd_index, cmd in enumerate(commands_to_try):
            print(f"[v0] Attempt {cmd_index + 1}/{len(commands_to_try)}: Running command: {' '.join(cmd)}")
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                print(f"[v0] Command return code: {result.returncode}")
                
                if result.stderr:
                    stderr_preview = result.stderr[:300].replace('\n', ' ')
                    print(f"[v0] stderr: {stderr_preview}")
                
                # smartctl returns: 0=OK, 2=SMART disabled, 4=threshold exceeded (still valid), 8=error log has errors
                if result.returncode in [0, 2, 4, 8] and result.stdout:
                    print(f"[v0] Got output ({len(result.stdout)} bytes)")
                    
                    # Try JSON parsing first
                    if '-j' in cmd:
                        try:
                            print(f"[v0] Attempting JSON parse...")
                            data = json.loads(result.stdout)
                            print(f"[v0] JSON parse successful!")
                            
                            # Extract model
                            if 'model_name' in data:
                                smart_data['model'] = data['model_name']
                                print(f"[v0] Model: {smart_data['model']}")
                            elif 'model_family' in data:
                                smart_data['model'] = data['model_family']
                                print(f"[v0] Model family: {smart_data['model']}")
                            
                            # Extract serial
                            if 'serial_number' in data:
                                smart_data['serial'] = data['serial_number']
                                print(f"[v0] Serial: {smart_data['serial']}")
                            
                            # Extract SMART status
                            if 'smart_status' in data and 'passed' in data['smart_status']:
                                smart_data['smart_status'] = 'passed' if data['smart_status']['passed'] else 'failed'
                                smart_data['health'] = 'healthy' if data['smart_status']['passed'] else 'critical'
                                print(f"[v0] SMART status: {smart_data['smart_status']}, health: {smart_data['health']}")
                            
                            # Extract temperature
                            if 'temperature' in data and 'current' in data['temperature']:
                                smart_data['temperature'] = data['temperature']['current']
                                print(f"[v0] Temperature: {smart_data['temperature']}°C")
                            
                            # Parse ATA SMART attributes
                            if 'ata_smart_attributes' in data and 'table' in data['ata_smart_attributes']:
                                print(f"[v0] Parsing ATA SMART attributes...")
                                for attr in data['ata_smart_attributes']['table']:
                                    attr_id = attr.get('id')
                                    raw_value = attr.get('raw', {}).get('value', 0)
                                    
                                    # ID mapping from Home Assistant coordinator
                                    if attr_id == 9:  # Power_On_Hours
                                        smart_data['power_on_hours'] = raw_value
                                        print(f"[v0] Power On Hours (ID 9): {raw_value}")
                                    elif attr_id == 194:  # Temperature_Celsius
                                        if smart_data['temperature'] == 0:
                                            smart_data['temperature'] = raw_value
                                            print(f"[v0] Temperature (ID 194): {raw_value}°C")
                                    elif attr_id == 190:  # Airflow_Temperature_Cel
                                        if smart_data['temperature'] == 0:
                                            smart_data['temperature'] = raw_value
                                            print(f"[v0] Airflow Temperature (ID 190): {raw_value}°C")
                                    elif attr_id == 5:  # Reallocated_Sector_Ct
                                        smart_data['reallocated_sectors'] = raw_value
                                        print(f"[v0] Reallocated Sectors (ID 5): {raw_value}")
                                    elif attr_id == 197:  # Current_Pending_Sector
                                        smart_data['pending_sectors'] = raw_value
                                        print(f"[v0] Pending Sectors (ID 197): {raw_value}")
                                    elif attr_id == 199:  # UDMA_CRC_Error_Count
                                        smart_data['crc_errors'] = raw_value
                                        print(f"[v0] CRC Errors (ID 199): {raw_value}")
                            
                            # Parse NVMe SMART data
                            if 'nvme_smart_health_information_log' in data:
                                print(f"[v0] Parsing NVMe SMART data...")
                                nvme_data = data['nvme_smart_health_information_log']
                                if 'temperature' in nvme_data:
                                    smart_data['temperature'] = nvme_data['temperature']
                                    print(f"[v0] NVMe Temperature: {smart_data['temperature']}°C")
                                if 'power_on_hours' in nvme_data:
                                    smart_data['power_on_hours'] = nvme_data['power_on_hours']
                                    print(f"[v0] NVMe Power On Hours: {smart_data['power_on_hours']}")
                            
                            # If we got good data, break out of the loop
                            if smart_data['model'] != 'Unknown' or smart_data['serial'] != 'Unknown':
                                print(f"[v0] Successfully extracted data from JSON (attempt {cmd_index + 1})")
                                break
                                
                        except json.JSONDecodeError as e:
                            print(f"[v0] JSON parse failed: {e}, will try next command...")
                    
                    # Text parsing fallback
                    if smart_data['model'] == 'Unknown' or smart_data['serial'] == 'Unknown':
                        print(f"[v0] Parsing text output...")
                        output = result.stdout
                        
                        # Get basic info
                        for line in output.split('\n'):
                            line = line.strip()
                            if line.startswith('Device Model:') or line.startswith('Model Number:'):
                                smart_data['model'] = line.split(':', 1)[1].strip()
                                print(f"[v0] Found model: {smart_data['model']}")
                            elif line.startswith('Serial Number:'):
                                smart_data['serial'] = line.split(':', 1)[1].strip()
                                print(f"[v0] Found serial: {smart_data['serial']}")
                            elif line.startswith('Model Family:') and smart_data['model'] == 'Unknown':
                                smart_data['model'] = line.split(':', 1)[1].strip()
                                print(f"[v0] Found model family: {smart_data['model']}")
                        
                        # Parse SMART status
                        if 'SMART overall-health self-assessment test result: PASSED' in output:
                            smart_data['smart_status'] = 'passed'
                            smart_data['health'] = 'healthy'
                            print(f"[v0] SMART status: PASSED")
                        elif 'SMART Health Status: OK' in output:  # NVMe
                            smart_data['smart_status'] = 'passed'
                            smart_data['health'] = 'healthy'
                            print(f"[v0] NVMe Health: OK")
                        elif 'SMART overall-health self-assessment test result: FAILED' in output:
                            smart_data['smart_status'] = 'failed'
                            smart_data['health'] = 'critical'
                            print(f"[v0] SMART status: FAILED")
                        
                        # Parse SMART attributes table
                        in_attributes = False
                        for line in output.split('\n'):
                            line = line.strip()
                            
                            if 'ID# ATTRIBUTE_NAME' in line:
                                in_attributes = True
                                print(f"[v0] Found SMART attributes table")
                                continue
                            
                            if in_attributes and line and not line.startswith('SMART'):
                                parts = line.split()
                                if len(parts) >= 10:
                                    try:
                                        attr_id = parts[0]
                                        raw_value = parts[9]
                                        
                                        # Same ID mapping as JSON parsing
                                        if attr_id == '9':  # Power On Hours
                                            # Handle different formats: "12345", "12345h", "12345 hours"
                                            raw_clean = raw_value.split()[0].replace('h', '')
                                            smart_data['power_on_hours'] = int(raw_clean)
                                            print(f"[v0] Power On Hours: {smart_data['power_on_hours']}")
                                        elif attr_id == '194':  # Temperature
                                            temp_str = raw_value.split()[0]
                                            smart_data['temperature'] = int(temp_str)
                                            print(f"[v0] Temperature: {smart_data['temperature']}°C")
                                        elif attr_id == '190':  # Airflow Temperature
                                            if smart_data['temperature'] == 0:
                                                temp_str = raw_value.split()[0]
                                                smart_data['temperature'] = int(temp_str)
                                                print(f"[v0] Airflow Temperature: {smart_data['temperature']}°C")
                                        elif attr_id == '5':  # Reallocated Sectors
                                            smart_data['reallocated_sectors'] = int(raw_value)
                                            print(f"[v0] Reallocated Sectors: {smart_data['reallocated_sectors']}")
                                        elif attr_id == '197':  # Pending Sectors
                                            smart_data['pending_sectors'] = int(raw_value)
                                            print(f"[v0] Pending Sectors: {smart_data['pending_sectors']}")
                                        elif attr_id == '199':  # CRC Errors
                                            smart_data['crc_errors'] = int(raw_value)
                                            print(f"[v0] CRC Errors: {smart_data['crc_errors']}")
                                            
                                    except (ValueError, IndexError) as e:
                                        continue
                        
                        # Try to find temperature in other formats
                        if smart_data['temperature'] == 0:
                            for line in output.split('\n'):
                                if 'Temperature:' in line or 'Temperature_Celsius' in line:
                                    try:
                                        temp_str = line.split(':')[1].strip().split()[0]
                                        smart_data['temperature'] = int(temp_str)
                                        print(f"[v0] Found temperature: {smart_data['temperature']}°C")
                                        break
                                    except (ValueError, IndexError):
                                        pass
                        
                        # If we got some data, break
                        if smart_data['model'] != 'Unknown' or smart_data['serial'] != 'Unknown':
                            print(f"[v0] Successfully extracted data from text output (attempt {cmd_index + 1})")
                            break
                else:
                    print(f"[v0] Command failed with return code {result.returncode}, trying next...")
                
            except subprocess.TimeoutExpired:
                print(f"[v0] Command timeout for attempt {cmd_index + 1}, trying next...")
                continue
            except Exception as e:
                print(f"[v0] Error in attempt {cmd_index + 1}: {type(e).__name__}: {e}")
                continue
        
        if smart_data['reallocated_sectors'] > 0 or smart_data['pending_sectors'] > 0:
            smart_data['health'] = 'warning'
            print(f"[v0] Health: WARNING (reallocated/pending sectors)")
        if smart_data['reallocated_sectors'] > 10 or smart_data['pending_sectors'] > 10:
            smart_data['health'] = 'critical'
            print(f"[v0] Health: CRITICAL (high sector count)")
        if smart_data['smart_status'] == 'failed':
            smart_data['health'] = 'critical'
            print(f"[v0] Health: CRITICAL (SMART failed)")
        
        # Temperature-based health
        if smart_data['health'] == 'healthy' and smart_data['temperature'] > 0:
            if smart_data['temperature'] >= 70:
                smart_data['health'] = 'critical'
            elif smart_data['temperature'] >= 60:
                smart_data['health'] = 'warning'
            
    except FileNotFoundError:
        print(f"[v0] ERROR: smartctl not found - install smartmontools")
    except Exception as e:
        print(f"[v0] ERROR: Unexpected exception for {disk_name}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"[v0] ===== Final SMART data for /dev/{disk_name}: {smart_data} =====")
    return smart_data

def get_network_info():
    """Get network interface information"""
    try:
        network_data = {
            'interfaces': [],
            'traffic': {'bytes_sent': 0, 'bytes_recv': 0}
        }
        
        # Get network interfaces
        net_if_addrs = psutil.net_if_addrs()
        net_if_stats = psutil.net_if_stats()
        
        for interface_name, interface_addresses in net_if_addrs.items():
            # Skip loopback
            if interface_name == 'lo':
                continue
            
            # Skip virtual interfaces that are not bridges
            # Keep: physical interfaces (enp*, eth*, wlan*) and bridges (vmbr*, br*)
            if not (interface_name.startswith(('enp', 'eth', 'wlan', 'vmbr', 'br'))):
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
            'error': f'Unable to access network information: {str(e)}',
            'interfaces': [],
            'traffic': {'bytes_sent': 0, 'bytes_recv': 0, 'packets_sent': 0, 'packets_recv': 0}
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
            return {
                'error': 'pvesh command not available or failed - Proxmox API not accessible',
                'vms': []
            }
    except Exception as e:
        print(f"Error getting VM info: {e}")
        return {
            'error': f'Unable to access VM information: {str(e)}',
            'vms': []
        }

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
            return jsonify({
                'error': 'journalctl not available or failed',
                'logs': []
            })
    except Exception as e:
        print(f"Error getting logs: {e}")
        return jsonify({
            'error': f'Unable to access system logs: {str(e)}',
            'logs': []
        })

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
        pve_version = None
        
        # Try to get Proxmox version
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
        
        response = {
            'hostname': hostname,
            'node_id': node_id,
            'status': 'online',
            'timestamp': datetime.now().isoformat()
        }
        
        if pve_version:
            response['pve_version'] = pve_version
        else:
            response['error'] = 'Proxmox version not available - pveversion command not found'
        
        return jsonify(response)
    except Exception as e:
        print(f"Error getting system info: {e}")
        return jsonify({
            'error': f'Unable to access system information: {str(e)}',
            'hostname': socket.gethostname(),
            'status': 'error',
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
    print("Starting ProxMenux Flask Server on port 8008...")
    print("Server will be accessible on all network interfaces (0.0.0.0:8008)")
    print("API endpoints available at: /api/system, /api/storage, /api/network, /api/vms, /api/logs, /api/health")
    
    app.run(host='0.0.0.0', port=8008, debug=False)
