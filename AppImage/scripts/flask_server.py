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
import re # Added for regex matching

app = Flask(__name__)
CORS(app)  # Enable CORS for Next.js frontend

def extract_vmid_from_interface(interface_name):
    """Extract VMID from virtual interface name (veth100i0 -> 100, tap105i0 -> 105)"""
    try:
        match = re.match(r'(veth|tap)(\d+)i\d+', interface_name)
        if match:
            vmid = int(match.group(2))
            interface_type = 'lxc' if match.group(1) == 'veth' else 'vm'
            return vmid, interface_type
        return None, None
    except Exception as e:
        print(f"[v0] Error extracting VMID from {interface_name}: {e}")
        return None, None

def get_vm_lxc_names():
    """Get VM and LXC names from Proxmox API"""
    vm_lxc_map = {}
    
    try:
        result = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            resources = json.loads(result.stdout)
            for resource in resources:
                vmid = resource.get('vmid')
                name = resource.get('name', f'VM-{vmid}')
                vm_type = resource.get('type', 'unknown')  # 'qemu' or 'lxc'
                status = resource.get('status', 'unknown')
                
                if vmid:
                    vm_lxc_map[vmid] = {
                        'name': name,
                        'type': 'lxc' if vm_type == 'lxc' else 'vm',
                        'status': status
                    }
                    print(f"[v0] Found {vm_type} {vmid}: {name} ({status})")
        else:
            print(f"[v0] pvesh command failed: {result.stderr}")
    except FileNotFoundError:
        print("[v0] pvesh command not found - Proxmox not installed")
    except Exception as e:
        print(f"[v0] Error getting VM/LXC names: {e}")
    
    return vm_lxc_map

@app.route('/')
def serve_dashboard():
    """Serve the main dashboard page from Next.js build"""
    try:
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            # Fallback: detect from script location
            base_dir = os.path.dirname(os.path.abspath(__file__))
            if base_dir.endswith('usr/bin'):
                # We're in usr/bin/, go up 2 levels to AppImage root
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                # Fallback: assume we're in the root
                appimage_root = os.path.dirname(base_dir)
        
        print(f"[v0] Detected AppImage root: {appimage_root}")
        
        index_path = os.path.join(appimage_root, 'web', 'index.html')
        abs_path = os.path.abspath(index_path)
        
        print(f"[v0] Looking for index.html at: {abs_path}")
        
        if os.path.exists(abs_path):
            print(f"[v0] ✅ Found index.html, serving from: {abs_path}")
            return send_file(abs_path)
        
        # If not found, show detailed error
        print(f"[v0] ❌ index.html NOT found at: {abs_path}")
        print(f"[v0] Checking web directory contents:")
        web_dir = os.path.join(appimage_root, 'web')
        if os.path.exists(web_dir):
            print(f"[v0] Contents of {web_dir}:")
            for item in os.listdir(web_dir):
                print(f"[v0]   - {item}")
        else:
            print(f"[v0] Web directory does not exist: {web_dir}")
        
        return f'''
        <!DOCTYPE html>
        <html>
        <head><title>ProxMenux Monitor - Build Error</title></head>
        <body style="font-family: Arial; padding: 2rem; background: #0a0a0a; color: #fff;">
            <h1>🚨 ProxMenux Monitor - Build Error</h1>
            <p>Next.js application not found. The AppImage may not have been built correctly.</p>
            <p>Expected path: {abs_path}</p>
            <p>APPDIR: {appimage_root}</p>
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
            if base_dir.endswith('usr/bin'):
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                appimage_root = os.path.dirname(base_dir)
        
        static_dir = os.path.join(appimage_root, 'web', '_next')
        file_path = os.path.join(static_dir, filename)
        
        if os.path.exists(file_path):
            return send_file(file_path)
        
        print(f"[v0] ❌ Next.js static file not found: {file_path}")
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
            if base_dir.endswith('usr/bin'):
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                appimage_root = os.path.dirname(base_dir)
        
        web_dir = os.path.join(appimage_root, 'web')
        file_path = os.path.join(web_dir, filename)
        
        if os.path.exists(file_path):
            return send_from_directory(web_dir, filename)
        
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
            if base_dir.endswith('usr/bin'):
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                appimage_root = os.path.dirname(base_dir)
        
        image_dir = os.path.join(appimage_root, 'web', 'images')
        file_path = os.path.join(image_dir, filename)
        abs_path = os.path.abspath(file_path)
        
        print(f"[v0] Looking for image: {filename} at {abs_path}")
        
        if os.path.exists(abs_path):
            print(f"[v0] ✅ Serving image from: {abs_path}")
            return send_from_directory(image_dir, filename)
        
        print(f"[v0] ❌ Image not found: {abs_path}")
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
                        
                        if disk_name.startswith('zd'):
                            print(f"[v0] Skipping ZFS zvol device: {disk_name}")
                            continue
                        
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
                            'crc_errors': smart_data.get('crc_errors', 0),
                            'rotation_rate': smart_data.get('rotation_rate', 0), # Added
                            'power_cycles': smart_data.get('power_cycles', 0) # Added
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
        'crc_errors': 0,
        'rotation_rate': 0,  # Added rotation rate (RPM)
        'power_cycles': 0,   # Added power cycle count
    }
    
    print(f"[v0] ===== Starting SMART data collection for /dev/{disk_name} =====")
    
    try:
        commands_to_try = [
            ['smartctl', '-a', '-j', f'/dev/{disk_name}'],  # JSON output (preferred)
            ['smartctl', '-a', '-j', '-d', 'ata', f'/dev/{disk_name}'],  # JSON with ATA device type
            ['smartctl', '-a', '-j', '-d', 'sat', f'/dev/{disk_name}'],  # JSON with SAT device type
            ['smartctl', '-a', f'/dev/{disk_name}'],  # Text output (fallback)
            ['smartctl', '-a', '-d', 'ata', f'/dev/{disk_name}'],  # Text with ATA device type
            ['smartctl', '-a', '-d', 'sat', f'/dev/{disk_name}'],  # Text with SAT device type
            ['smartctl', '-i', '-H', '-A', f'/dev/{disk_name}'],  # Info + Health + Attributes
            ['smartctl', '-i', '-H', '-A', '-d', 'ata', f'/dev/{disk_name}'],  # With ATA
            ['smartctl', '-i', '-H', '-A', '-d', 'sat', f'/dev/{disk_name}'],  # With SAT
            ['smartctl', '-a', '-j', '-d', 'scsi', f'/dev/{disk_name}'],  # JSON with SCSI device type
            ['smartctl', '-a', '-j', '-d', 'sat,12', f'/dev/{disk_name}'],  # SAT with 12-byte commands
            ['smartctl', '-a', '-j', '-d', 'sat,16', f'/dev/{disk_name}'],  # SAT with 16-byte commands
            ['smartctl', '-a', '-d', 'sat,12', f'/dev/{disk_name}'],  # Text SAT with 12-byte commands
            ['smartctl', '-a', '-d', 'sat,16', f'/dev/{disk_name}'],  # Text SAT with 16-byte commands
        ]
        
        for cmd_index, cmd in enumerate(commands_to_try):
            print(f"[v0] Attempt {cmd_index + 1}/{len(commands_to_try)}: Running command: {' '.join(cmd)}")
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                print(f"[v0] Command return code: {result.returncode}")
                
                if result.stderr:
                    stderr_preview = result.stderr[:200].replace('\n', ' ')
                    print(f"[v0] stderr: {stderr_preview}")
                
                has_output = result.stdout and len(result.stdout.strip()) > 50
                
                if has_output:
                    print(f"[v0] Got output ({len(result.stdout)} bytes), attempting to parse...")
                    
                    # Try JSON parsing first (if -j flag was used)
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
                            
                            if 'rotation_rate' in data:
                                smart_data['rotation_rate'] = data['rotation_rate']
                                print(f"[v0] Rotation Rate: {smart_data['rotation_rate']} RPM")
                            
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
                                    
                                    if attr_id == 9:  # Power_On_Hours
                                        smart_data['power_on_hours'] = raw_value
                                        print(f"[v0] Power On Hours (ID 9): {raw_value}")
                                    elif attr_id == 12:  # Power_Cycle_Count
                                        smart_data['power_cycles'] = raw_value
                                        print(f"[v0] Power Cycles (ID 12): {raw_value}")
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
                                if 'power_cycles' in nvme_data:
                                    smart_data['power_cycles'] = nvme_data['power_cycles']
                                    print(f"[v0] NVMe Power Cycles: {smart_data['power_cycles']}")
                            
                            # If we got good data, break out of the loop
                            if smart_data['model'] != 'Unknown' and smart_data['serial'] != 'Unknown':
                                print(f"[v0] Successfully extracted complete data from JSON (attempt {cmd_index + 1})")
                                break
                                
                        except json.JSONDecodeError as e:
                            print(f"[v0] JSON parse failed: {e}, trying text parsing...")
                    
                    if smart_data['model'] == 'Unknown' or smart_data['serial'] == 'Unknown' or smart_data['temperature'] == 0:
                        print(f"[v0] Parsing text output (model={smart_data['model']}, serial={smart_data['serial']}, temp={smart_data['temperature']})...")
                        output = result.stdout
                        
                        # Get basic info
                        for line in output.split('\n'):
                            line = line.strip()
                            
                            # Model detection
                            if (line.startswith('Device Model:') or line.startswith('Model Number:')) and smart_data['model'] == 'Unknown':
                                smart_data['model'] = line.split(':', 1)[1].strip()
                                print(f"[v0] Found model: {smart_data['model']}")
                            elif line.startswith('Model Family:') and smart_data['model'] == 'Unknown':
                                smart_data['model'] = line.split(':', 1)[1].strip()
                                print(f"[v0] Found model family: {smart_data['model']}")
                            
                            # Serial detection
                            elif line.startswith('Serial Number:') and smart_data['serial'] == 'Unknown':
                                smart_data['serial'] = line.split(':', 1)[1].strip()
                                print(f"[v0] Found serial: {smart_data['serial']}")
                            
                            elif line.startswith('Rotation Rate:') and smart_data['rotation_rate'] == 0:
                                rate_str = line.split(':', 1)[1].strip()
                                if 'rpm' in rate_str.lower():
                                    try:
                                        smart_data['rotation_rate'] = int(rate_str.split()[0])
                                        print(f"[v0] Found rotation rate: {smart_data['rotation_rate']} RPM")
                                    except (ValueError, IndexError):
                                        pass
                                elif 'Solid State Device' in rate_str:
                                    smart_data['rotation_rate'] = 0  # SSD
                                    print(f"[v0] Found SSD (no rotation)")
                            
                            # SMART status detection
                            elif 'SMART overall-health self-assessment test result:' in line:
                                if 'PASSED' in line:
                                    smart_data['smart_status'] = 'passed'
                                    smart_data['health'] = 'healthy'
                                    print(f"[v0] SMART status: PASSED")
                                elif 'FAILED' in line:
                                    smart_data['smart_status'] = 'failed'
                                    smart_data['health'] = 'critical'
                                    print(f"[v0] SMART status: FAILED")
                            
                            # NVMe health
                            elif 'SMART Health Status:' in line:
                                if 'OK' in line:
                                    smart_data['smart_status'] = 'passed'
                                    smart_data['health'] = 'healthy'
                                    print(f"[v0] NVMe Health: OK")
                            
                            # Temperature detection (various formats)
                            elif 'Current Temperature:' in line and smart_data['temperature'] == 0:
                                try:
                                    temp_str = line.split(':')[1].strip().split()[0]
                                    smart_data['temperature'] = int(temp_str)
                                    print(f"[v0] Found temperature: {smart_data['temperature']}°C")
                                except (ValueError, IndexError):
                                    pass
                        
                        # Parse SMART attributes table
                        in_attributes = False
                        for line in output.split('\n'):
                            line = line.strip()
                            
                            if 'ID# ATTRIBUTE_NAME' in line or 'ID#' in line and 'ATTRIBUTE_NAME' in line:
                                in_attributes = True
                                print(f"[v0] Found SMART attributes table")
                                continue
                            
                            if in_attributes:
                                # Stop at empty line or next section
                                if not line or line.startswith('SMART') or line.startswith('==='):
                                    in_attributes = False
                                    continue
                                
                                parts = line.split()
                                if len(parts) >= 10:
                                    try:
                                        attr_id = parts[0]
                                        # Raw value is typically the last column
                                        raw_value = parts[-1]
                                        
                                        # Parse based on attribute ID
                                        if attr_id == '9':  # Power On Hours
                                            raw_clean = raw_value.split()[0].replace('h', '').replace(',', '')
                                            smart_data['power_on_hours'] = int(raw_clean)
                                            print(f"[v0] Power On Hours: {smart_data['power_on_hours']}")
                                        elif attr_id == '12':  # Power Cycle Count
                                            raw_clean = raw_value.split()[0].replace(',', '')
                                            smart_data['power_cycles'] = int(raw_clean)
                                            print(f"[v0] Power Cycles: {smart_data['power_cycles']}")
                                        elif attr_id == '194' and smart_data['temperature'] == 0:  # Temperature
                                            temp_str = raw_value.split()[0]
                                            smart_data['temperature'] = int(temp_str)
                                            print(f"[v0] Temperature (attr 194): {smart_data['temperature']}°C")
                                        elif attr_id == '190' and smart_data['temperature'] == 0:  # Airflow Temperature
                                            temp_str = raw_value.split()[0]
                                            smart_data['temperature'] = int(temp_str)
                                            print(f"[v0] Airflow Temperature (attr 190): {smart_data['temperature']}°C")
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
                                        print(f"[v0] Error parsing attribute line '{line}': {e}")
                                        continue
                        
                        # If we got complete data, break
                        if smart_data['model'] != 'Unknown' and smart_data['serial'] != 'Unknown':
                            print(f"[v0] Successfully extracted complete data from text output (attempt {cmd_index + 1})")
                            break
                        elif smart_data['model'] != 'Unknown' or smart_data['serial'] != 'Unknown':
                            print(f"[v0] Extracted partial data from text output, continuing to next attempt...")
                else:
                    print(f"[v0] No usable output (return code {result.returncode}), trying next command...")
            
            except subprocess.TimeoutExpired:
                print(f"[v0] Command timeout for attempt {cmd_index + 1}, trying next...")
                continue
            except Exception as e:
                print(f"[v0] Error in attempt {cmd_index + 1}: {type(e).__name__}: {e}")
                continue
        
        if smart_data['reallocated_sectors'] > 0 or smart_data['pending_sectors'] > 0:
            if smart_data['health'] == 'healthy':
                smart_data['health'] = 'warning'
            print(f"[v0] Health: WARNING (reallocated/pending sectors)")
        if smart_data['reallocated_sectors'] > 10 or smart_data['pending_sectors'] > 10:
            smart_data['health'] = 'critical'
            print(f"[v0] Health: CRITICAL (high sector count)")
        if smart_data['smart_status'] == 'failed':
            smart_data['health'] = 'critical'
            print(f"[v0] Health: CRITICAL (SMART failed)")
        
        # Temperature-based health (only if we have a valid temperature)
        if smart_data['health'] == 'healthy' and smart_data['temperature'] > 0:
            if smart_data['temperature'] >= 70:
                smart_data['health'] = 'critical'
                print(f"[v0] Health: CRITICAL (temperature {smart_data['temperature']}°C)")
            elif smart_data['temperature'] >= 60:
                smart_data['health'] = 'warning'
                print(f"[v0] Health: WARNING (temperature {smart_data['temperature']}°C)")
            
    except FileNotFoundError:
        print(f"[v0] ERROR: smartctl not found - install smartmontools")
    except Exception as e:
        print(f"[v0] ERROR: Unexpected exception for {disk_name}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"[v0] ===== Final SMART data for /dev/{disk_name}: {smart_data} =====")
    return smart_data

def get_proxmox_storage():
    """Get Proxmox storage information using pvesm status"""
    try:
        print("[v0] Getting Proxmox storage with pvesm status...")
        result = subprocess.run(['pvesm', 'status'], capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            print(f"[v0] pvesm status failed with return code {result.returncode}")
            print(f"[v0] stderr: {result.stderr}")
            return {
                'error': 'pvesm command not available or failed',
                'storage': []
            }
        
        storage_list = []
        lines = result.stdout.strip().split('\n')
        
        # Skip header line
        if len(lines) < 2:
            print("[v0] No storage found in pvesm output")
            return {'storage': []}
        
        # Parse each storage line
        for line in lines[1:]:  # Skip header
            parts = line.split()
            if len(parts) >= 6:
                name = parts[0]
                storage_type = parts[1]
                status = parts[2]
                total = int(parts[3])
                used = int(parts[4])
                available = int(parts[5])
                percent = float(parts[6].rstrip('%')) if len(parts) > 6 else 0.0
                
                # Convert bytes to GB
                total_gb = round(total / (1024**2), 2)
                used_gb = round(used / (1024**2), 2)
                available_gb = round(available / (1024**2), 2)
                
                storage_info = {
                    'name': name,
                    'type': storage_type,
                    'status': status,
                    'total': total_gb,
                    'used': used_gb,
                    'available': available_gb,
                    'percent': round(percent, 2)
                }
                
                print(f"[v0] Found storage: {name} ({storage_type}) - {used_gb}/{total_gb} GB ({percent}%)")
                storage_list.append(storage_info)
        
        return {'storage': storage_list}
        
    except FileNotFoundError:
        print("[v0] pvesm command not found - Proxmox not installed or not in PATH")
        return {
            'error': 'pvesm command not found - Proxmox not installed',
            'storage': []
        }
    except Exception as e:
        print(f"[v0] Error getting Proxmox storage: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return {
            'error': f'Unable to get Proxmox storage: {str(e)}',
            'storage': []
        }

def get_interface_type(interface_name):
    """Detect the type of network interface"""
    try:
        # Skip loopback
        if interface_name == 'lo':
            return 'skip'
        
        if interface_name.startswith(('veth', 'tap')):
            return 'vm_lxc'
        
        # Skip other virtual interfaces
        if interface_name.startswith(('tun', 'vnet', 'docker', 'virbr')):
            return 'skip'
        
        # Check if it's a bond
        if interface_name.startswith('bond'):
            return 'bond'
        
        # Check if it's a bridge (but not virbr which we skip above)
        if interface_name.startswith(('vmbr', 'br')):
            return 'bridge'
        
        # Check if it's a VLAN (contains a dot)
        if '.' in interface_name:
            return 'vlan'
        
        # Check if it's a physical interface
        if interface_name.startswith(('enp', 'eth', 'wlan', 'wlp', 'eno', 'ens')):
            return 'physical'
        
        # Default to skip for unknown types
        return 'skip'
    except Exception as e:
        print(f"[v0] Error detecting interface type for {interface_name}: {e}")
        return 'skip'

def get_bond_info(bond_name):
    """Get detailed information about a bonding interface"""
    bond_info = {
        'mode': 'unknown',
        'slaves': [],
        'active_slave': None
    }
    
    try:
        bond_file = f'/proc/net/bonding/{bond_name}'
        if os.path.exists(bond_file):
            with open(bond_file, 'r') as f:
                content = f.read()
                
                # Parse bonding mode
                for line in content.split('\n'):
                    if 'Bonding Mode:' in line:
                        bond_info['mode'] = line.split(':', 1)[1].strip()
                    elif 'Slave Interface:' in line:
                        slave_name = line.split(':', 1)[1].strip()
                        bond_info['slaves'].append(slave_name)
                    elif 'Currently Active Slave:' in line:
                        bond_info['active_slave'] = line.split(':', 1)[1].strip()
                
                print(f"[v0] Bond {bond_name} info: mode={bond_info['mode']}, slaves={bond_info['slaves']}")
    except Exception as e:
        print(f"[v0] Error reading bond info for {bond_name}: {e}")
    
    return bond_info

def get_bridge_info(bridge_name):
    """Get detailed information about a bridge interface"""
    bridge_info = {
        'members': [],
        'physical_interface': None,
        'physical_duplex': 'unknown',  # Added physical_duplex field
        # Added bond_slaves to show physical interfaces
        'bond_slaves': []
    }
    
    try:
        # Try to read bridge members from /sys/class/net/<bridge>/brif/
        brif_path = f'/sys/class/net/{bridge_name}/brif'
        if os.path.exists(brif_path):
            members = os.listdir(brif_path)
            bridge_info['members'] = members
            
            for member in members:
                # Check if member is a bond first
                if member.startswith('bond'):
                    bridge_info['physical_interface'] = member
                    print(f"[v0] Bridge {bridge_name} connected to bond: {member}")
                    
                    bond_info = get_bond_info(member)
                    if bond_info['slaves']:
                        bridge_info['bond_slaves'] = bond_info['slaves']
                        print(f"[v0] Bond {member} slaves: {bond_info['slaves']}")
                    
                    # Get duplex from bond's active slave
                    if bond_info['active_slave']:
                        try:
                            net_if_stats = psutil.net_if_stats()
                            if bond_info['active_slave'] in net_if_stats:
                                stats = net_if_stats[bond_info['active_slave']]
                                bridge_info['physical_duplex'] = 'full' if stats.duplex == 2 else 'half' if stats.duplex == 1 else 'unknown'
                                print(f"[v0] Bond {member} active slave {bond_info['active_slave']} duplex: {bridge_info['physical_duplex']}")
                        except Exception as e:
                            print(f"[v0] Error getting duplex for bond slave {bond_info['active_slave']}: {e}")
                    break
                # Check if member is a physical interface
                elif member.startswith(('enp', 'eth', 'eno', 'ens', 'wlan', 'wlp')):
                    bridge_info['physical_interface'] = member
                    print(f"[v0] Bridge {bridge_name} physical interface: {member}")
                    
                    # Get duplex from physical interface
                    try:
                        net_if_stats = psutil.net_if_stats()
                        if member in net_if_stats:
                            stats = net_if_stats[member]
                            bridge_info['physical_duplex'] = 'full' if stats.duplex == 2 else 'half' if stats.duplex == 1 else 'unknown'
                            print(f"[v0] Physical interface {member} duplex: {bridge_info['physical_duplex']}")
                    except Exception as e:
                        print(f"[v0] Error getting duplex for {member}: {e}")
                    
                    break
            
            print(f"[v0] Bridge {bridge_name} members: {members}")
    except Exception as e:
        print(f"[v0] Error reading bridge info for {bridge_name}: {e}")
    
    return bridge_info

def get_network_info():
    """Get network interface information - Enhanced with VM/LXC interface separation"""
    try:
        network_data = {
            'interfaces': [],
            'physical_interfaces': [],  # Added separate list for physical interfaces
            'bridge_interfaces': [],    # Added separate list for bridge interfaces
            'vm_lxc_interfaces': [],
            'traffic': {'bytes_sent': 0, 'bytes_recv': 0, 'packets_sent': 0, 'packets_recv': 0}
        }
        
        vm_lxc_map = get_vm_lxc_names()
        
        # Get network interfaces
        net_if_addrs = psutil.net_if_addrs()
        net_if_stats = psutil.net_if_stats()
        
        try:
            net_io_per_nic = psutil.net_io_counters(pernic=True)
        except Exception as e:
            print(f"[v0] Error getting per-NIC stats: {e}")
            net_io_per_nic = {}
        
        physical_active_count = 0
        physical_total_count = 0
        bridge_active_count = 0
        bridge_total_count = 0
        vm_lxc_active_count = 0
        vm_lxc_total_count = 0
        
        for interface_name, interface_addresses in net_if_addrs.items():
            interface_type = get_interface_type(interface_name)
            
            if interface_type == 'skip':
                print(f"[v0] Skipping interface: {interface_name} (type: {interface_type})")
                continue
            
            stats = net_if_stats.get(interface_name)
            if not stats:
                continue
            
            if interface_type == 'vm_lxc':
                vm_lxc_total_count += 1
                if stats.isup:
                    vm_lxc_active_count += 1
            elif interface_type == 'physical':
                physical_total_count += 1
                if stats.isup:
                    physical_active_count += 1
            elif interface_type == 'bridge':
                bridge_total_count += 1
                if stats.isup:
                    bridge_active_count += 1
                
            interface_info = {
                'name': interface_name,
                'type': interface_type,
                'status': 'up' if stats.isup else 'down',
                'speed': stats.speed if stats.speed > 0 else 0,
                'duplex': 'full' if stats.duplex == 2 else 'half' if stats.duplex == 1 else 'unknown',
                'mtu': stats.mtu,
                'addresses': [],
                'mac_address': None,
            }
            
            if interface_type == 'vm_lxc':
                vmid, vm_type = extract_vmid_from_interface(interface_name)
                if vmid and vmid in vm_lxc_map:
                    interface_info['vmid'] = vmid
                    interface_info['vm_name'] = vm_lxc_map[vmid]['name']
                    interface_info['vm_type'] = vm_lxc_map[vmid]['type']
                    interface_info['vm_status'] = vm_lxc_map[vmid]['status']
                elif vmid:
                    interface_info['vmid'] = vmid
                    interface_info['vm_name'] = f'{"LXC" if vm_type == "lxc" else "VM"} {vmid}'
                    interface_info['vm_type'] = vm_type
                    interface_info['vm_status'] = 'unknown'
            
            for address in interface_addresses:
                if address.family == 2:  # IPv4
                    interface_info['addresses'].append({
                        'ip': address.address,
                        'netmask': address.netmask
                    })
                elif address.family == 17:  # AF_PACKET (MAC address on Linux)
                    interface_info['mac_address'] = address.address
            
            if interface_name in net_io_per_nic:
                io_stats = net_io_per_nic[interface_name]
                interface_info['bytes_sent'] = io_stats.bytes_sent
                interface_info['bytes_recv'] = io_stats.bytes_recv
                interface_info['packets_sent'] = io_stats.packets_sent
                interface_info['packets_recv'] = io_stats.packets_recv
                interface_info['errors_in'] = io_stats.errin
                interface_info['errors_out'] = io_stats.errout
                interface_info['drops_in'] = io_stats.dropin
                interface_info['drops_out'] = io_stats.dropout
                
                total_packets_in = io_stats.packets_recv + io_stats.dropin
                total_packets_out = io_stats.packets_sent + io_stats.dropout
                
                if total_packets_in > 0:
                    interface_info['packet_loss_in'] = round((io_stats.dropin / total_packets_in) * 100, 2)
                else:
                    interface_info['packet_loss_in'] = 0
                    
                if total_packets_out > 0:
                    interface_info['packet_loss_out'] = round((io_stats.dropout / total_packets_out) * 100, 2)
                else:
                    interface_info['packet_loss_out'] = 0
            
            if interface_type == 'bond':
                bond_info = get_bond_info(interface_name)
                interface_info['bond_mode'] = bond_info['mode']
                interface_info['bond_slaves'] = bond_info['slaves']
                interface_info['bond_active_slave'] = bond_info['active_slave']
            
            if interface_type == 'bridge':
                bridge_info = get_bridge_info(interface_name)
                interface_info['bridge_members'] = bridge_info['members']
                interface_info['bridge_physical_interface'] = bridge_info['physical_interface']
                interface_info['bridge_physical_duplex'] = bridge_info['physical_duplex']
                interface_info['bridge_bond_slaves'] = bridge_info['bond_slaves']
                # Override bridge duplex with physical interface duplex
                if bridge_info['physical_duplex'] != 'unknown':
                    interface_info['duplex'] = bridge_info['physical_duplex']
            
            if interface_type == 'vm_lxc':
                network_data['vm_lxc_interfaces'].append(interface_info)
            elif interface_type == 'physical':
                network_data['physical_interfaces'].append(interface_info)
            elif interface_type == 'bridge':
                network_data['bridge_interfaces'].append(interface_info)
            else:
                # Keep other types in the general interfaces list for backward compatibility
                network_data['interfaces'].append(interface_info)
        
        network_data['physical_active_count'] = physical_active_count
        network_data['physical_total_count'] = physical_total_count
        network_data['bridge_active_count'] = bridge_active_count
        network_data['bridge_total_count'] = bridge_total_count
        network_data['vm_lxc_active_count'] = vm_lxc_active_count
        network_data['vm_lxc_total_count'] = vm_lxc_total_count
        
        # Keep old counters for backward compatibility
        network_data['active_count'] = physical_active_count + bridge_active_count
        network_data['total_count'] = physical_total_count + bridge_total_count
        
        print(f"[v0] Physical interfaces: {physical_active_count} active out of {physical_total_count} total")
        print(f"[v0] Bridge interfaces: {bridge_active_count} active out of {bridge_total_count} total")
        print(f"[v0] VM/LXC interfaces: {vm_lxc_active_count} active out of {vm_lxc_total_count} total")
        
        # Get network I/O statistics (global)
        net_io = psutil.net_io_counters()
        network_data['traffic'] = {
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv,
            'errin': net_io.errin,
            'errout': net_io.errout,
            'dropin': net_io.dropin,
            'dropout': net_io.dropout
        }
        
        total_packets_in = net_io.packets_recv + net_io.dropin
        total_packets_out = net_io.packets_sent + net_io.dropout
        
        if total_packets_in > 0:
            network_data['traffic']['packet_loss_in'] = round((net_io.dropin / total_packets_in) * 100, 2)
        else:
            network_data['traffic']['packet_loss_in'] = 0
            
        if total_packets_out > 0:
            network_data['traffic']['packet_loss_out'] = round((net_io.dropout / total_packets_out) * 100, 2)
        else:
            network_data['traffic']['packet_loss_out'] = 0
        
        return network_data
    except Exception as e:
        print(f"Error getting network info: {e}")
        import traceback
        traceback.print_exc()
        return {
            'error': f'Unable to access network information: {str(e)}',
            'interfaces': [],
            'physical_interfaces': [],
            'bridge_interfaces': [],
            'vm_lxc_interfaces': [],
            'traffic': {'bytes_sent': 0, 'bytes_recv': 0, 'packets_sent': 0, 'packets_recv': 0},
            'active_count': 0,
            'total_count': 0,
            'physical_active_count': 0,
            'physical_total_count': 0,
            'bridge_active_count': 0,
            'bridge_total_count': 0,
            'vm_lxc_active_count': 0,
            'vm_lxc_total_count': 0
        }

def get_proxmox_vms():
    """Get Proxmox VM and LXC information (requires pvesh command)"""
    try:
        all_vms = []
        
        try:
            result = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                resources = json.loads(result.stdout)
                for resource in resources:
                    vm_data = {
                        'vmid': resource.get('vmid'),
                        'name': resource.get('name', f"VM-{resource.get('vmid')}"),
                        'status': resource.get('status', 'unknown'),
                        'type': 'lxc' if resource.get('type') == 'lxc' else 'qemu',
                        'cpu': resource.get('cpu', 0),
                        'mem': resource.get('mem', 0),
                        'maxmem': resource.get('maxmem', 0),
                        'disk': resource.get('disk', 0),
                        'maxdisk': resource.get('maxdisk', 0),
                        'uptime': resource.get('uptime', 0),
                        'netin': resource.get('netin', 0),
                        'netout': resource.get('netout', 0),
                        'diskread': resource.get('diskread', 0),
                        'diskwrite': resource.get('diskwrite', 0)
                    }
                    all_vms.append(vm_data)
                    print(f"[v0] Found {vm_data['type']}: {vm_data['name']} (VMID: {vm_data['vmid']}, Status: {vm_data['status']})")
                
                return all_vms
            else:
                print(f"[v0] pvesh command failed: {result.stderr}")
                return {
                    'error': 'pvesh command not available or failed',
                    'vms': []
                }
        except Exception as e:
            print(f"[v0] Error getting VM/LXC info: {e}")
            return {
                'error': f'Unable to access VM information: {str(e)}',
                'vms': []
            }
    except Exception as e:
        print(f"Error getting VM info: {e}")
        return {
            'error': f'Unable to access VM information: {str(e)}',
            'vms': []
        }

def get_ipmi_fans():
    """Get fan information from IPMI"""
    fans = []
    try:
        result = subprocess.run(['ipmitool', 'sensor'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'fan' in line.lower() and '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 3:
                        name = parts[0]
                        value_str = parts[1]
                        unit = parts[2] if len(parts) > 2 else ''
                        
                        # Skip "DutyCycle" and "Presence" entries
                        if 'dutycycle' in name.lower() or 'presence' in name.lower():
                            continue
                        
                        try:
                            value = float(value_str)
                            fans.append({
                                'name': name,
                                'speed': value,
                                'unit': unit
                            })
                            print(f"[v0] IPMI Fan: {name} = {value} {unit}")
                        except ValueError:
                            continue
        
        print(f"[v0] Found {len(fans)} IPMI fans")
    except FileNotFoundError:
        print("[v0] ipmitool not found")
    except Exception as e:
        print(f"[v0] Error getting IPMI fans: {e}")
    
    return fans

def get_ipmi_power():
    """Get power supply information from IPMI"""
    power_supplies = []
    power_meter = None
    
    try:
        result = subprocess.run(['ipmitool', 'sensor'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if ('power supply' in line.lower() or 'power meter' in line.lower()) and '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 3:
                        name = parts[0]
                        value_str = parts[1]
                        unit = parts[2] if len(parts) > 2 else ''
                        
                        try:
                            value = float(value_str)
                            
                            if 'power meter' in name.lower():
                                power_meter = {
                                    'name': name,
                                    'watts': value,
                                    'unit': unit
                                }
                                print(f"[v0] IPMI Power Meter: {value} {unit}")
                            else:
                                power_supplies.append({
                                    'name': name,
                                    'watts': value,
                                    'unit': unit,
                                    'status': 'ok' if value > 0 else 'off'
                                })
                                print(f"[v0] IPMI PSU: {name} = {value} {unit}")
                        except ValueError:
                            continue
        
        print(f"[v0] Found {len(power_supplies)} IPMI power supplies")
    except FileNotFoundError:
        print("[v0] ipmitool not found")
    except Exception as e:
        print(f"[v0] Error getting IPMI power: {e}")
    
    return {
        'power_supplies': power_supplies,
        'power_meter': power_meter
    }

def get_ups_info():
    """Get UPS information from NUT (upsc)"""
    ups_data = {}
    
    try:
        # First, list available UPS devices
        result = subprocess.run(['upsc', '-l'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            ups_list = result.stdout.strip().split('\n')
            if ups_list and ups_list[0]:
                ups_name = ups_list[0]
                print(f"[v0] Found UPS: {ups_name}")
                
                # Get detailed UPS info
                result = subprocess.run(['upsc', ups_name], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if ':' in line:
                            key, value = line.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # Map common UPS variables
                            if key == 'device.model':
                                ups_data['model'] = value
                            elif key == 'ups.status':
                                ups_data['status'] = value
                            elif key == 'battery.charge':
                                ups_data['battery_charge'] = f"{value}%"
                            elif key == 'battery.runtime':
                                # Convert seconds to minutes
                                try:
                                    runtime_sec = int(value)
                                    runtime_min = runtime_sec // 60
                                    ups_data['time_left'] = f"{runtime_min} minutes"
                                except ValueError:
                                    ups_data['time_left'] = value
                            elif key == 'ups.load':
                                ups_data['load_percent'] = f"{value}%"
                            elif key == 'input.voltage':
                                ups_data['line_voltage'] = f"{value}V"
                            elif key == 'ups.realpower':
                                ups_data['real_power'] = f"{value}W"
                    
                    print(f"[v0] UPS data: {ups_data}")
    except FileNotFoundError:
        print("[v0] upsc not found")
    except Exception as e:
        print(f"[v0] Error getting UPS info: {e}")
    
    return ups_data

def identify_temperature_sensor(sensor_name, adapter):
    """Identify what a temperature sensor corresponds to"""
    sensor_lower = sensor_name.lower()
    adapter_lower = adapter.lower() if adapter else ""
    
    # CPU/Package temperatures
    if "package" in sensor_lower or "tctl" in sensor_lower or "tccd" in sensor_lower:
        return "CPU Package"
    if "core" in sensor_lower:
        core_num = re.search(r'(\d+)', sensor_name)
        return f"CPU Core {core_num.group(1)}" if core_num else "CPU Core"
    
    # Motherboard/Chipset
    if "temp1" in sensor_lower and ("isa" in adapter_lower or "acpi" in adapter_lower):
        return "Motherboard/Chipset"
    if "pch" in sensor_lower or "chipset" in sensor_lower:
        return "Chipset"
    
    # Storage (NVMe, SATA)
    if "nvme" in sensor_lower or "composite" in sensor_lower:
        return "NVMe SSD"
    if "sata" in sensor_lower or "ata" in sensor_lower:
        return "SATA Drive"
    
    # GPU
    if any(gpu in adapter_lower for gpu in ["nouveau", "amdgpu", "radeon", "i915"]):
        return "GPU"
    
    # Network adapters
    if "pci" in adapter_lower and "temp" in sensor_lower:
        return "PCI Device"
    
    return sensor_name

def get_temperature_info():
    """Get detailed temperature information from sensors command"""
    temperatures = []
    power_meter = None
    
    try:
        result = subprocess.run(['sensors'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            current_adapter = None
            current_sensor = None
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Detect adapter line
                if line.startswith('Adapter:'):
                    current_adapter = line.replace('Adapter:', '').strip()
                    continue
                
                # Detect sensor name (lines without ':' at the start are sensor names)
                if ':' in line and not line.startswith(' '):
                    parts = line.split(':', 1)
                    sensor_name = parts[0].strip()
                    value_part = parts[1].strip()
                    
                    if 'power' in sensor_name.lower() and 'W' in value_part:
                        try:
                            # Extract power value (e.g., "182.00 W" -> 182.00)
                            power_match = re.search(r'([\d.]+)\s*W', value_part)
                            if power_match:
                                power_value = float(power_match.group(1))
                                power_meter = {
                                    'name': sensor_name,
                                    'watts': power_value,
                                    'adapter': current_adapter
                                }
                                print(f"[v0] Power meter sensor: {sensor_name} = {power_value}W")
                        except ValueError:
                            pass
                    
                    # Parse temperature sensors
                    elif '°C' in value_part or 'C' in value_part:
                        try:
                            # Extract temperature value
                            temp_match = re.search(r'([+-]?[\d.]+)\s*°?C', value_part)
                            if temp_match:
                                temp_value = float(temp_match.group(1))
                                
                                # Extract high and critical values if present
                                high_match = re.search(r'high\s*=\s*([+-]?[\d.]+)', value_part)
                                crit_match = re.search(r'crit\s*=\s*([+-]?[\d.]+)', value_part)
                                
                                high_value = float(high_match.group(1)) if high_match else 0
                                crit_value = float(crit_match.group(1)) if crit_match else 0
                                
                                identified_name = identify_temperature_sensor(sensor_name, current_adapter)
                                
                                temperatures.append({
                                    'name': identified_name,
                                    'original_name': sensor_name,
                                    'current': temp_value,
                                    'high': high_value,
                                    'critical': crit_value,
                                    'adapter': current_adapter
                                })
                        except ValueError:
                            pass
        
        print(f"[v0] Found {len(temperatures)} temperature sensors")
        if power_meter:
            print(f"[v0] Found power meter: {power_meter['watts']}W")
            
    except FileNotFoundError:
        print("[v0] sensors command not found")
    except Exception as e:
        print(f"[v0] Error getting temperature info: {e}")
    
    return {
        'temperatures': temperatures,
        'power_meter': power_meter
    }

def identify_fan(fan_name, adapter):
    """Identify what a fan corresponds to"""
    fan_lower = fan_name.lower()
    adapter_lower = adapter.lower() if adapter else ""
    
    # GPU fans
    if any(gpu in adapter_lower for gpu in ["nouveau", "amdgpu", "radeon", "i915"]):
        return "GPU Fan"
    
    # CPU fans
    if "cpu" in fan_lower:
        return "CPU Fan"
    
    # Chassis/System fans
    if "fan1" in fan_lower and "isa" in adapter_lower:
        return "CPU Fan"
    if "fan2" in fan_lower and "isa" in adapter_lower:
        return "Chassis Fan"
    if "fan3" in fan_lower and "isa" in adapter_lower:
        return "Chassis Fan"
    if "sys" in fan_lower or "chassis" in fan_lower:
        return "Chassis Fan"
    
    return fan_name

def get_detailed_gpu_info(gpu):
    """Get detailed GPU information using nvidia-smi, intel_gpu_top, or radeontop"""
    detailed_info = {}
    
    vendor = gpu.get('vendor', '').upper()
    
    if vendor == 'INTEL':
        try:
            check_result = subprocess.run(['which', 'intel_gpu_top'], capture_output=True, timeout=1)
            if check_result.returncode != 0:
                # Tool not found
                detailed_info['has_monitoring_tool'] = False
                print(f"[v0] intel_gpu_top not found for Intel GPU")
                return detailed_info
            else:
                print(f"[v0] intel_gpu_top found for Intel GPU")
        except Exception as e:
            print(f"[v0] Error checking for intel_gpu_top: {e}")
            detailed_info['has_monitoring_tool'] = False
            return detailed_info
        
        data_retrieved = False
        try:
            # Start intel_gpu_top process
            process = subprocess.Popen(
                ['intel_gpu_top', '-s', '100'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait for output with timeout
            try:
                stdout, stderr = process.communicate(timeout=2)
                
                if stdout:
                    output = stdout
                    print(f"[v0] intel_gpu_top output received: {output[:200]}...")
                    
                    # Parse frequency: "0/ 0 MHz"
                    freq_match = re.search(r'(\d+)/\s*(\d+)\s*MHz', output)
                    if freq_match:
                        detailed_info['clock_graphics'] = f"{freq_match.group(1)} MHz"
                        detailed_info['clock_max'] = f"{freq_match.group(2)} MHz"
                        data_retrieved = True
                    
                    # Parse power: "0.00/ 7.23 W"
                    power_match = re.search(r'([\d.]+)/\s*([\d.]+)\s*W', output)
                    if power_match:
                        detailed_info['power_draw'] = f"{power_match.group(1)} W"
                        detailed_info['power_limit'] = f"{power_match.group(2)} W"
                        data_retrieved = True
                    
                    # Parse RC6 (power saving state): "100% RC6"
                    rc6_match = re.search(r'(\d+)%\s*RC6', output)
                    if rc6_match:
                        detailed_info['power_state'] = f"RC6: {rc6_match.group(1)}%"
                        data_retrieved = True
                    
                    # Parse engine utilization
                    engines = {
                        'Render/3D': 'engine_render',
                        'Blitter': 'engine_blitter',
                        'Video': 'engine_video',
                        'VideoEnhance': 'engine_video_enhance'
                    }
                    for engine_name, key in engines.items():
                        pattern = rf'{engine_name}\s+([\d.]+)%'
                        match = re.search(pattern, output)
                        if match:
                            detailed_info[key] = float(match.group(1))
                            data_retrieved = True
                    
                    # Parse IRQ rate
                    irq_match = re.search(r'(\d+)\s*irqs/s', output)
                    if irq_match:
                        detailed_info['irq_rate'] = int(irq_match.group(1))
                        data_retrieved = True
                    
                    print(f"[v0] Intel GPU parsed data: {detailed_info}")
                    
            except subprocess.TimeoutExpired:
                print(f"[v0] intel_gpu_top process timed out, terminating...")
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                detailed_info['has_monitoring_tool'] = False
                print(f"[v0] intel_gpu_top timed out - marking tool as unavailable")
                return detailed_info
            
            if data_retrieved:
                detailed_info['has_monitoring_tool'] = True
                print(f"[v0] Intel GPU monitoring successful")
            else:
                detailed_info['has_monitoring_tool'] = False
                print(f"[v0] Intel GPU monitoring failed - no data retrieved")
                    
        except Exception as e:
            print(f"[v0] Error getting Intel GPU details: {e}")
            detailed_info['has_monitoring_tool'] = False
    
    elif vendor == 'NVIDIA':
        try:
            check_result = subprocess.run(['which', 'nvidia-smi'], capture_output=True, timeout=1)
            if check_result.returncode != 0:
                detailed_info['has_monitoring_tool'] = False
                print(f"[v0] nvidia-smi not found for NVIDIA GPU")
                return detailed_info
            else:
                print(f"[v0] nvidia-smi found for NVIDIA GPU")
        except Exception as e:
            print(f"[v0] Error checking for nvidia-smi: {e}")
            detailed_info['has_monitoring_tool'] = False
            return detailed_info
        
        data_retrieved = False
        try:
            # nvidia-smi query for real-time data
            print(f"[v0] Executing nvidia-smi to get GPU data...")
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=index,name,driver_version,memory.total,memory.used,memory.free,temperature.gpu,power.draw,power.limit,utilization.gpu,utilization.memory,clocks.gr,clocks.mem,pcie.link.gen.current,pcie.link.width.current', 
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5
            )
            print(f"[v0] nvidia-smi return code: {result.returncode}")
            print(f"[v0] nvidia-smi output: {result.stdout[:200] if result.stdout else 'No output'}")
            
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) >= 15:
                            detailed_info['driver_version'] = parts[2] if parts[2] != '[N/A]' else None
                            detailed_info['memory_total'] = int(float(parts[3])) if parts[3] != '[N/A]' else None
                            detailed_info['memory_used'] = int(float(parts[4])) if parts[4] != '[N/A]' else None
                            detailed_info['memory_free'] = int(float(parts[5])) if parts[5] != '[N/A]' else None
                            detailed_info['temperature'] = int(float(parts[6])) if parts[6] != '[N/A]' else None
                            detailed_info['power_draw'] = float(parts[7]) if parts[7] != '[N/A]' else None
                            detailed_info['power_limit'] = float(parts[8]) if parts[8] != '[N/A]' else None
                            detailed_info['utilization_gpu'] = int(float(parts[9])) if parts[9] != '[N/A]' else None
                            detailed_info['utilization_memory'] = int(float(parts[10])) if parts[10] != '[N/A]' else None
                            detailed_info['clock_graphics'] = int(float(parts[11])) if parts[11] != '[N/A]' else None
                            detailed_info['clock_memory'] = int(float(parts[12])) if parts[12] != '[N/A]' else None
                            detailed_info['pcie_gen'] = parts[13] if parts[13] != '[N/A]' else None
                            detailed_info['pcie_width'] = f"x{parts[14]}" if parts[14] != '[N/A]' else None
                            data_retrieved = True
                            print(f"[v0] NVIDIA GPU data retrieved successfully: {detailed_info}")
                            break
            
            # Get running processes
            result = subprocess.run(
                ['nvidia-smi', '--query-compute-apps=pid,process_name,used_memory', '--format=csv,noheader'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                processes = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) >= 3:
                            processes.append({
                                'pid': parts[0],
                                'name': parts[1],
                                'memory': parts[2]
                            })
                detailed_info['processes'] = processes
                print(f"[v0] NVIDIA GPU processes: {len(processes)} found")
            
            if data_retrieved:
                detailed_info['has_monitoring_tool'] = True
                print(f"[v0] NVIDIA GPU monitoring successful")
            else:
                detailed_info['has_monitoring_tool'] = False
                print(f"[v0] NVIDIA GPU monitoring failed - no data retrieved")
                
        except subprocess.TimeoutExpired:
            print(f"[v0] nvidia-smi timed out - marking tool as unavailable")
            detailed_info['has_monitoring_tool'] = False
        except Exception as e:
            print(f"[v0] Error getting NVIDIA GPU details: {e}")
            import traceback
            traceback.print_exc()
            detailed_info['has_monitoring_tool'] = False
    
    elif vendor == 'AMD':
        try:
            check_result = subprocess.run(['which', 'radeontop'], capture_output=True, timeout=1)
            if check_result.returncode != 0:
                detailed_info['has_monitoring_tool'] = False
                print(f"[v0] radeontop not found for AMD GPU")
                return detailed_info
            else:
                print(f"[v0] radeontop found for AMD GPU")
                detailed_info['has_monitoring_tool'] = True
        except Exception as e:
            print(f"[v0] Error checking for radeontop: {e}")
            detailed_info['has_monitoring_tool'] = False
            return detailed_info
    
    return detailed_info

def get_pci_device_info(pci_slot):
    """Get detailed PCI device information for a given slot"""
    pci_info = {}
    try:
        # Use lspci -vmm for detailed information
        result = subprocess.run(['lspci', '-vmm', '-s', pci_slot], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                line = line.strip()
                if ':' in line:
                    key, value = line.split(':', 1)
                    pci_info[key.strip().lower().replace(' ', '_')] = value.strip()
    except Exception as e:
        print(f"[v0] Error getting PCI device info for {pci_slot}: {e}")
    return pci_info

def get_network_hardware_info(pci_slot):
    """Get detailed hardware information for a network interface"""
    net_info = {}
    
    try:
        # Get detailed PCI info
        result = subprocess.run(['lspci', '-v', '-s', pci_slot], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Kernel driver in use:' in line:
                    net_info['driver'] = line.split(':', 1)[1].strip()
                elif 'Kernel modules:' in line:
                    net_info['kernel_modules'] = line.split(':', 1)[1].strip()
                elif 'Subsystem:' in line:
                    net_info['subsystem'] = line.split(':', 1)[1].strip()
                elif 'LnkCap:' in line:
                    # Parse link capabilities
                    speed_match = re.search(r'Speed (\S+)', line)
                    width_match = re.search(r'Width x(\d+)', line)
                    if speed_match:
                        net_info['max_link_speed'] = speed_match.group(1)
                    if width_match:
                        net_info['max_link_width'] = f"x{width_match.group(1)}"
                elif 'LnkSta:' in line:
                    # Parse current link status
                    speed_match = re.search(r'Speed (\S+)', line)
                    width_match = re.search(r'Width x(\d+)', line)
                    if speed_match:
                        net_info['current_link_speed'] = speed_match.group(1)
                    if width_match:
                        net_info['current_link_width'] = f"x{width_match.group(1)}"
        
        # Get network interface name and status
        try:
            result = subprocess.run(['ls', '/sys/class/net/'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                interfaces = result.stdout.strip().split('\n')
                for iface in interfaces:
                    # Check if this interface corresponds to the PCI slot
                    device_path = f"/sys/class/net/{iface}/device"
                    if os.path.exists(device_path):
                        real_path = os.path.realpath(device_path)
                        if pci_slot in real_path:
                            net_info['interface_name'] = iface
                            
                            # Get interface speed
                            speed_file = f"/sys/class/net/{iface}/speed"
                            if os.path.exists(speed_file):
                                with open(speed_file, 'r') as f:
                                    speed = f.read().strip()
                                    if speed != '-1':
                                        net_info['interface_speed'] = f"{speed} Mbps"
                            
                            # Get MAC address
                            mac_file = f"/sys/class/net/{iface}/address"
                            if os.path.exists(mac_file):
                                with open(mac_file, 'r') as f:
                                    net_info['mac_address'] = f.read().strip()
                            
                            break
        except Exception as e:
            print(f"[v0] Error getting network interface info: {e}")
            
    except Exception as e:
        print(f"[v0] Error getting network hardware info: {e}")
    
    return net_info

def get_gpu_info():
    """Get GPU information from lspci and enrich with temperature/fan data from sensors"""
    gpus = []
    
    try:
        result = subprocess.run(['lspci'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                # Match VGA, 3D, Display controllers
                if any(keyword in line for keyword in ['VGA compatible controller', '3D controller', 'Display controller']):
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        slot = parts[0].strip()
                        gpu_name = parts[2].strip()
                        
                        # Determine vendor
                        vendor = 'Unknown'
                        if 'NVIDIA' in gpu_name or 'nVidia' in gpu_name:
                            vendor = 'NVIDIA'
                        elif 'AMD' in gpu_name or 'ATI' in gpu_name or 'Radeon' in gpu_name:
                            vendor = 'AMD'
                        elif 'Intel' in gpu_name:
                            vendor = 'Intel'
                        
                        gpu = {
                            'slot': slot,
                            'name': gpu_name,
                            'vendor': vendor,
                            'type': 'Discrete' if vendor in ['NVIDIA', 'AMD'] else 'Integrated'
                        }
                        
                        pci_info = get_pci_device_info(slot)
                        if pci_info:
                            gpu['pci_class'] = pci_info.get('class', '')
                            gpu['pci_driver'] = pci_info.get('driver', '')
                            gpu['pci_kernel_module'] = pci_info.get('kernel_module', '')
                        
                        detailed_info = get_detailed_gpu_info(gpu)
                        gpu.update(detailed_info)
                        
                        gpus.append(gpu)
                        print(f"[v0] Found GPU: {gpu_name} ({vendor}) at slot {slot}")
    except Exception as e:
        print(f"[v0] Error detecting GPUs from lspci: {e}")
    
    try:
        result = subprocess.run(['sensors'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            current_adapter = None
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Detect adapter line
                if line.startswith('Adapter:'):
                    current_adapter = line.replace('Adapter:', '').strip()
                    continue
                
                # Look for GPU-related sensors (nouveau, amdgpu, radeon, i915)
                if ':' in line and not line.startswith(' '):
                    parts = line.split(':', 1)
                    sensor_name = parts[0].strip()
                    value_part = parts[1].strip()
                    
                    # Check if this is a GPU sensor
                    gpu_sensor_keywords = ['nouveau', 'amdgpu', 'radeon', 'i915']
                    is_gpu_sensor = any(keyword in current_adapter.lower() if current_adapter else False for keyword in gpu_sensor_keywords)
                    
                    if is_gpu_sensor:
                        # Try to match this sensor to a GPU
                        for gpu in gpus:
                            # Match nouveau to NVIDIA, amdgpu/radeon to AMD, i915 to Intel
                            if (('nouveau' in current_adapter.lower() and gpu['vendor'] == 'NVIDIA') or
                                (('amdgpu' in current_adapter.lower() or 'radeon' in current_adapter.lower()) and gpu['vendor'] == 'AMD') or
                                ('i915' in current_adapter.lower() and gpu['vendor'] == 'Intel')):
                                
                                # Parse temperature (only if not already set by nvidia-smi)
                                if 'temperature' not in gpu or gpu['temperature'] is None:
                                    if '°C' in value_part or 'C' in value_part:
                                        temp_match = re.search(r'([+-]?[\d.]+)\s*°?C', value_part)
                                        if temp_match:
                                            gpu['temperature'] = float(temp_match.group(1))
                                            print(f"[v0] GPU {gpu['name']}: Temperature = {gpu['temperature']}°C")
                                
                                # Parse fan speed
                                elif 'RPM' in value_part:
                                    rpm_match = re.search(r'([\d.]+)\s*RPM', value_part)
                                    if rpm_match:
                                        gpu['fan_speed'] = int(float(rpm_match.group(1)))
                                        gpu['fan_unit'] = 'RPM'
                                        print(f"[v0] GPU {gpu['name']}: Fan = {gpu['fan_speed']} RPM")
    except Exception as e:
        print(f"[v0] Error enriching GPU data from sensors: {e}")
    
    return gpus

def get_disk_hardware_info(disk_name):
    """Get detailed hardware information for a disk"""
    disk_info = {}
    
    try:
        # Get disk type (HDD, SSD, NVMe)
        result = subprocess.run(['lsblk', '-d', '-n', '-o', 'NAME,ROTA,TYPE', f'/dev/{disk_name}'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                rota = parts[1]
                disk_info['type'] = 'HDD' if rota == '1' else 'SSD'
                if disk_name.startswith('nvme'):
                    disk_info['type'] = 'NVMe SSD'
        
        # Get driver/kernel module
        try:
            # For NVMe
            if disk_name.startswith('nvme'):
                disk_info['driver'] = 'nvme'
                disk_info['interface'] = 'PCIe/NVMe'
            # For SATA/SAS
            else:
                result = subprocess.run(['udevadm', 'info', '--query=property', f'/dev/{disk_name}'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'ID_BUS=' in line:
                            bus = line.split('=')[1].strip()
                            disk_info['interface'] = bus.upper()
                        if 'ID_MODEL=' in line:
                            model = line.split('=')[1].strip()
                            disk_info['model'] = model
                        if 'ID_SERIAL_SHORT=' in line:
                            serial = line.split('=')[1].strip()
                            disk_info['serial'] = serial
        except Exception as e:
            print(f"[v0] Error getting disk driver info: {e}")
            
        # Get SMART data
        try:
            result = subprocess.run(['smartctl', '-i', f'/dev/{disk_name}'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'Model Family:' in line:
                        disk_info['family'] = line.split(':', 1)[1].strip()
                    elif 'Device Model:' in line or 'Model Number:' in line:
                        disk_info['model'] = line.split(':', 1)[1].strip()
                    elif 'Serial Number:' in line:
                        disk_info['serial'] = line.split(':', 1)[1].strip()
                    elif 'Firmware Version:' in line:
                        disk_info['firmware'] = line.split(':', 1)[1].strip()
                    elif 'Rotation Rate:' in line:
                        disk_info['rotation_rate'] = line.split(':', 1)[1].strip()
                    elif 'Form Factor:' in line:
                        disk_info['form_factor'] = line.split(':', 1)[1].strip()
                    elif 'SATA Version is:' in line:
                        disk_info['sata_version'] = line.split(':', 1)[1].strip()
        except Exception as e:
            print(f"[v0] Error getting SMART info: {e}")
            
    except Exception as e:
        print(f"[v0] Error getting disk hardware info: {e}")
    
    return disk_info

def get_hardware_info():
    """Get comprehensive hardware information"""
    try:
        # Initialize with default structure, including the new power_meter field
        hardware_data = {
            'cpu': {},
            'motherboard': {},
            'memory_modules': [],
            'storage_devices': [],
            'network_cards': [],
            'graphics_cards': [],
            'gpus': [],  # Added dedicated GPU array
            'pci_devices': [],
            'sensors': {
                'temperatures': [],
                'fans': []
            },
            'power': {}, # This might be overwritten by ipmi_power or ups
            'ipmi_fans': [],  # Added IPMI fans
            'ipmi_power': {},  # Added IPMI power
            'ups': {},  # Added UPS info
            'power_meter': None # Added placeholder for sensors power meter
        }
        
        # CPU Information
        try:
            result = subprocess.run(['lscpu'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                cpu_info = {}
                for line in result.stdout.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        if key == 'Model name':
                            cpu_info['model'] = value
                        elif key == 'CPU(s)':
                            cpu_info['total_threads'] = int(value)
                        elif key == 'Core(s) per socket':
                            cpu_info['cores_per_socket'] = int(value)
                        elif key == 'Socket(s)':
                            cpu_info['sockets'] = int(value)
                        elif key == 'CPU MHz':
                            cpu_info['current_mhz'] = float(value)
                        elif key == 'CPU max MHz':
                            cpu_info['max_mhz'] = float(value)
                        elif key == 'CPU min MHz':
                            cpu_info['min_mhz'] = float(value)
                        elif key == 'Virtualization':
                            cpu_info['virtualization'] = value
                        elif key == 'L1d cache':
                            cpu_info['l1d_cache'] = value
                        elif key == 'L1i cache':
                            cpu_info['l1i_cache'] = value
                        elif key == 'L2 cache':
                            cpu_info['l2_cache'] = value
                        elif key == 'L3 cache':
                            cpu_info['l3_cache'] = value
                
                hardware_data['cpu'] = cpu_info
                print(f"[v0] CPU: {cpu_info.get('model', 'Unknown')}")
        except Exception as e:
            print(f"[v0] Error getting CPU info: {e}")
        
        # Motherboard Information
        try:
            result = subprocess.run(['dmidecode', '-t', 'baseboard'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                mb_info = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('Manufacturer:'):
                        mb_info['manufacturer'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Product Name:'):
                        mb_info['model'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Version:'):
                        mb_info['version'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Serial Number:'):
                        mb_info['serial'] = line.split(':', 1)[1].strip()
                
                hardware_data['motherboard'] = mb_info
                print(f"[v0] Motherboard: {mb_info.get('manufacturer', 'Unknown')} {mb_info.get('model', 'Unknown')}")
        except Exception as e:
            print(f"[v0] Error getting motherboard info: {e}")
        
        # BIOS Information
        try:
            result = subprocess.run(['dmidecode', '-t', 'bios'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                bios_info = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('Vendor:'):
                        bios_info['vendor'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Version:'):
                        bios_info['version'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Release Date:'):
                        bios_info['date'] = line.split(':', 1)[1].strip()
                
                hardware_data['motherboard']['bios'] = bios_info
                print(f"[v0] BIOS: {bios_info.get('vendor', 'Unknown')} {bios_info.get('version', 'Unknown')}")
        except Exception as e:
            print(f"[v0] Error getting BIOS info: {e}")
        
        # Memory Modules
        try:
            result = subprocess.run(['dmidecode', '-t', 'memory'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                current_module = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    
                    if line.startswith('Memory Device'):
                        if current_module and current_module.get('size') != 'No Module Installed':
                            hardware_data['memory_modules'].append(current_module)
                        current_module = {}
                    elif line.startswith('Size:'):
                        size = line.split(':', 1)[1].strip()
                        current_module['size'] = size
                    elif line.startswith('Type:'):
                        current_module['type'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Speed:'):
                        current_module['speed'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Manufacturer:'):
                        current_module['manufacturer'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Serial Number:'):
                        current_module['serial'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Locator:'):
                        current_module['slot'] = line.split(':', 1)[1].strip()
                
                if current_module and current_module.get('size') != 'No Module Installed':
                    hardware_data['memory_modules'].append(current_module)
                
                print(f"[v0] Memory modules: {len(hardware_data['memory_modules'])} installed")
        except Exception as e:
            print(f"[v0] Error getting memory info: {e}")
        
        storage_info = get_storage_info()
        for device in storage_info.get('disks', []):
            hw_info = get_disk_hardware_info(device['name'])
            device.update(hw_info)
        hardware_data['storage_devices'] = storage_info.get('disks', [])
        
        # Graphics Cards (from lspci - will be duplicated by new PCI device listing, but kept for now)
        try:
            # Try nvidia-smi first
            result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,temperature.gpu,power.draw', '--format=csv,noheader'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split(',')
                        if len(parts) >= 4:
                            hardware_data['graphics_cards'].append({
                                'name': parts[0].strip(),
                                'memory': parts[1].strip(),
                                'temperature': int(parts[2].strip().split(' ')[0]) if parts[2].strip() != 'N/A' and 'C' in parts[2] else 0,
                                'power_draw': parts[3].strip(),
                                'vendor': 'NVIDIA'
                            })
            
            # Always check lspci for all GPUs (integrated and discrete)
            result = subprocess.run(['lspci'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    # Match VGA, 3D, Display controllers
                    if any(keyword in line for keyword in ['VGA compatible controller', '3D controller', 'Display controller']):
                        parts = line.split(':', 2)
                        if len(parts) >= 3:
                            gpu_name = parts[2].strip()
                            
                            # Determine vendor
                            vendor = 'Unknown'
                            if 'NVIDIA' in gpu_name or 'nVidia' in gpu_name:
                                vendor = 'NVIDIA'
                            elif 'AMD' in gpu_name or 'ATI' in gpu_name or 'Radeon' in gpu_name:
                                vendor = 'AMD'
                            elif 'Intel' in gpu_name:
                                vendor = 'Intel'
                            
                            # Check if this GPU is already in the list (from nvidia-smi)
                            already_exists = False
                            for existing_gpu in hardware_data['graphics_cards']:
                                if gpu_name in existing_gpu['name'] or existing_gpu['name'] in gpu_name:
                                    already_exists = True
                                    # Update vendor if it was previously unknown
                                    if existing_gpu['vendor'] == 'Unknown':
                                        existing_gpu['vendor'] = vendor
                                    break
                            
                            if not already_exists:
                                hardware_data['graphics_cards'].append({
                                    'name': gpu_name,
                                    'vendor': vendor
                                })
                                print(f"[v0] Found GPU: {gpu_name} ({vendor})")
            
            print(f"[v0] Graphics cards: {len(hardware_data['graphics_cards'])} found")
        except Exception as e:
            print(f"[v0] Error getting graphics cards: {e}")
        
        try:
            print("[v0] Getting PCI devices with driver information...")
            # First get basic device info with lspci -vmm
            result = subprocess.run(['lspci', '-vmm'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                current_device = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    
                    if not line:
                        # Empty line = end of device
                        if current_device and 'Class' in current_device:
                            device_class = current_device.get('Class', '')
                            device_name = current_device.get('Device', '')
                            vendor = current_device.get('Vendor', '')
                            slot = current_device.get('Slot', 'Unknown')
                            
                            # Categorize and add important devices
                            device_type = 'Other'
                            include_device = False
                            
                            # Graphics/Display devices
                            if any(keyword in device_class for keyword in ['VGA', 'Display', '3D']):
                                device_type = 'Graphics Card'
                                include_device = True
                            # Storage controllers
                            elif any(keyword in device_class for keyword in ['SATA', 'RAID', 'Mass storage', 'Non-Volatile memory']):
                                device_type = 'Storage Controller'
                                include_device = True
                            # Network controllers
                            elif 'Ethernet' in device_class or 'Network' in device_class:
                                device_type = 'Network Controller'
                                include_device = True
                            # USB controllers
                            elif 'USB' in device_class:
                                device_type = 'USB Controller'
                                include_device = True
                            # Audio devices
                            elif 'Audio' in device_class or 'Multimedia' in device_class:
                                device_type = 'Audio Controller'
                                include_device = True
                            # Special devices (Coral TPU, etc.)
                            elif any(keyword in device_name.lower() for keyword in ['coral', 'tpu', 'edge']):
                                device_type = 'AI Accelerator'
                                include_device = True
                            # PCI bridges (usually not interesting for users)
                            elif 'Bridge' in device_class:
                                include_device = False
                            
                            if include_device:
                                pci_device = {
                                    'slot': slot,
                                    'type': device_type,
                                    'vendor': vendor,
                                    'device': device_name,
                                    'class': device_class
                                }
                                hardware_data['pci_devices'].append(pci_device)
                        
                        current_device = {}
                    elif ':' in line:
                        key, value = line.split(':', 1)
                        current_device[key.strip()] = value.strip()
            
            # Now get driver information with lspci -k
            result_k = subprocess.run(['lspci', '-k'], capture_output=True, text=True, timeout=10)
            if result_k.returncode == 0:
                current_slot = None
                current_driver = None
                current_module = None
                
                for line in result_k.stdout.split('\n'):
                    # Match PCI slot line (e.g., "00:1f.2 SATA controller: ...")
                    if line and not line.startswith('\t'):
                        parts = line.split(' ', 1)
                        if parts:
                            current_slot = parts[0]
                            current_driver = None
                            current_module = None
                    # Match driver lines (indented with tab)
                    elif line.startswith('\t'):
                        line = line.strip()
                        if line.startswith('Kernel driver in use:'):
                            current_driver = line.split(':', 1)[1].strip()
                        elif line.startswith('Kernel modules:'):
                            current_module = line.split(':', 1)[1].strip()
                        
                        # Update the corresponding PCI device
                        if current_slot and (current_driver or current_module):
                            for device in hardware_data['pci_devices']:
                                if device['slot'] == current_slot:
                                    if current_driver:
                                        device['driver'] = current_driver
                                    if current_module:
                                        device['kernel_module'] = current_module
                                    break
            
            print(f"[v0] Total PCI devices found: {len(hardware_data['pci_devices'])}")
        except Exception as e:
            print(f"[v0] Error getting PCI devices: {e}")
        
        # Sensors (Temperature and Fans)
        try:
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    for sensor_name, entries in temps.items():
                        for entry in entries:
                            # Use identify_temperature_sensor to make names more user-friendly
                            identified_name = identify_temperature_sensor(entry.label if entry.label else sensor_name, sensor_name)
                            
                            hardware_data['sensors']['temperatures'].append({
                                'name': identified_name,
                                'original_name': entry.label if entry.label else sensor_name,
                                'current': entry.current,
                                'high': entry.high if entry.high else 0,
                                'critical': entry.critical if entry.critical else 0
                            })
                    
                    print(f"[v0] Temperature sensors: {len(hardware_data['sensors']['temperatures'])} found")
            
            try:
                result = subprocess.run(['sensors'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    current_adapter = None
                    fans = []
                    
                    for line in result.stdout.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Detect adapter line
                        if line.startswith('Adapter:'):
                            current_adapter = line.replace('Adapter:', '').strip()
                            continue
                        
                        # Parse fan sensors
                        if ':' in line and not line.startswith(' '):
                            parts = line.split(':', 1)
                            sensor_name = parts[0].strip()
                            value_part = parts[1].strip()
                            
                            # Look for fan sensors (RPM)
                            if 'RPM' in value_part:
                                rpm_match = re.search(r'([\d.]+)\s*RPM', value_part)
                                if rpm_match:
                                    fan_speed = int(float(rpm_match.group(1)))
                                    
                                    identified_name = identify_fan(sensor_name, current_adapter)
                                    
                                    fans.append({
                                        'name': identified_name,
                                        'original_name': sensor_name,
                                        'speed': fan_speed,
                                        'unit': 'RPM',
                                        'adapter': current_adapter
                                    })
                                    print(f"[v0] Fan sensor: {identified_name} ({sensor_name}) = {fan_speed} RPM")
                    
                    hardware_data['sensors']['fans'] = fans
                    print(f"[v0] Found {len(fans)} fan sensor(s)")
            except Exception as e:
                print(f"[v0] Error getting fan info: {e}")
        except Exception as e:
            print(f"[v0] Error getting psutil sensors: {e}")
        
        # Power Supply / UPS
        try:
            result = subprocess.run(['apcaccess'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                ups_info = {}
                for line in result.stdout.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        if key == 'MODEL':
                            ups_info['model'] = value
                        elif key == 'STATUS':
                            ups_info['status'] = value
                        elif key == 'BCHARGE':
                            ups_info['battery_charge'] = value
                        elif key == 'TIMELEFT':
                            ups_info['time_left'] = value
                        elif key == 'LOADPCT':
                            ups_info['load_percent'] = value
                        elif key == 'LINEV':
                            ups_info['line_voltage'] = value
                
                if ups_info:
                    hardware_data['power'] = ups_info
                    print(f"[v0] UPS found: {ups_info.get('model', 'Unknown')}")
        except FileNotFoundError:
            print("[v0] apcaccess not found - no UPS monitoring")
        except Exception as e:
            print(f"[v0] Error getting UPS info: {e}")
        
        temp_info = get_temperature_info()
        hardware_data['sensors']['temperatures'] = temp_info['temperatures']
        hardware_data['power_meter'] = temp_info['power_meter']
        
        ipmi_fans = get_ipmi_fans()
        if ipmi_fans:
            hardware_data['ipmi_fans'] = ipmi_fans
        
        ipmi_power = get_ipmi_power()
        if ipmi_power['power_supplies'] or ipmi_power['power_meter']:
            hardware_data['ipmi_power'] = ipmi_power
        
        ups_info = get_ups_info()
        if ups_info:
            hardware_data['ups'] = ups_info
        
        hardware_data['gpus'] = get_gpu_info()
        
        return hardware_data
        
    except Exception as e:
        print(f"[v0] Error in get_hardware_info: {e}")
        import traceback
        traceback.print_exc()
        return {}


@app.route('/api/system', methods=['GET'])
def api_system():
    """Get system information"""
    return jsonify(get_system_info())

@app.route('/api/storage', methods=['GET'])
def api_storage():
    """Get storage information"""
    return jsonify(get_storage_info())

@app.route('/api/proxmox-storage', methods=['GET'])
def api_proxmox_storage():
    """Get Proxmox storage information"""
    return jsonify(get_proxmox_storage())

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
            '/api/proxmox-storage',
            '/api/network',
            '/api/vms',
            '/api/logs',
            '/api/health',
            '/api/hardware',
            '/api/gpu/<slot>/realtime' # Added endpoint for GPU monitoring
        ]
    })

@app.route('/api/hardware', methods=['GET'])
def api_hardware():
    """Get comprehensive hardware information"""
    hardware_info = get_hardware_info()
    
    # Format data for frontend
    formatted_data = {
        'cpu': hardware_info.get('cpu', {}),
        'motherboard': hardware_info.get('motherboard', {}),
        'memory_modules': hardware_info.get('memory_modules', []),
        'storage_devices': hardware_info.get('storage_devices', []),
        'pci_devices': hardware_info.get('pci_devices', []),
        'temperatures': hardware_info.get('sensors', {}).get('temperatures', []),
        'fans': hardware_info.get('sensors', {}).get('fans', []), # Use sensors fans
        'power_supplies': hardware_info.get('ipmi_power', {}).get('power_supplies', []), # Use IPMI power supplies
        'power_meter': hardware_info.get('power_meter'),
        'ups': hardware_info.get('ups') if hardware_info.get('ups') else None,
        'gpus': hardware_info.get('gpus', []) # Include GPU data
    }
    
    print(f"[v0] /api/hardware returning data")
    print(f"[v0] - CPU: {formatted_data['cpu'].get('model', 'Unknown')}")
    print(f"[v0] - Temperatures: {len(formatted_data['temperatures'])} sensors")
    print(f"[v0] - Fans: {len(formatted_data['fans'])} fans")
    print(f"[v0] - Power supplies: {len(formatted_data['power_supplies'])} PSUs")
    print(f"[v0] - Power meter: {'Yes' if formatted_data['power_meter'] else 'No'}")
    print(f"[v0] - UPS: {'Yes' if formatted_data['ups'] else 'No'}")
    print(f"[v0] - GPUs: {len(formatted_data['gpus'])} found")
    
    return jsonify(formatted_data)

@app.route('/api/gpu/<slot>/realtime', methods=['GET'])
def api_gpu_realtime(slot):
    """Get real-time GPU monitoring data for a specific GPU"""
    try:
        # Find the GPU by slot
        hardware_info = get_hardware_info()
        gpus = hardware_info.get('gpus', [])
        
        gpu = None
        for g in gpus:
            if g.get('slot') == slot or g.get('slot', '').startswith(slot):
                gpu = g
                break
        
        if not gpu:
            return jsonify({'error': 'GPU not found'}), 404
        
        # Get real-time monitoring data
        realtime_data = get_detailed_gpu_info(gpu)
        
        print(f"[v0] /api/gpu/{slot}/realtime returning data")
        print(f"[v0] - Vendor: {gpu.get('vendor')}")
        print(f"[v0] - Realtime data: {realtime_data}")
        
        return jsonify(realtime_data)
    except Exception as e:
        print(f"[v0] Error getting real-time GPU data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/vms/<int:vmid>', methods=['GET'])
def api_vm_details(vmid):
    """Get detailed information for a specific VM/LXC"""
    try:
        result = subprocess.run(['pvesh', 'get', f'/cluster/resources', '--type', 'vm', '--output-format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            resources = json.loads(result.stdout)
            for resource in resources:
                if resource.get('vmid') == vmid:
                    vm_type = 'lxc' if resource.get('type') == 'lxc' else 'qemu'
                    node = resource.get('node', 'pve')
                    
                    # Get detailed config
                    config_result = subprocess.run(
                        ['pvesh', 'get', f'/nodes/{node}/{vm_type}/{vmid}/config', '--output-format', 'json'],
                        capture_output=True, text=True, timeout=10
                    )
                    
                    config = {}
                    if config_result.returncode == 0:
                        config = json.loads(config_result.stdout)
                    
                    return jsonify({
                        **resource,
                        'config': config,
                        'node': node,
                        'vm_type': vm_type
                    })
            
            return jsonify({'error': f'VM/LXC {vmid} not found'}), 404
        else:
            return jsonify({'error': 'Failed to get VM details'}), 500
    except Exception as e:
        print(f"Error getting VM details: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/vms/<int:vmid>/logs', methods=['GET'])
def api_vm_logs(vmid):
    """Download real logs for a specific VM/LXC (not task history)"""
    try:
        # Get VM type and node
        result = subprocess.run(['pvesh', 'get', f'/cluster/resources', '--type', 'vm', '--output-format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            resources = json.loads(result.stdout)
            vm_info = None
            for resource in resources:
                if resource.get('vmid') == vmid:
                    vm_info = resource
                    break
            
            if not vm_info:
                return jsonify({'error': f'VM/LXC {vmid} not found'}), 404
            
            vm_type = 'lxc' if vm_info.get('type') == 'lxc' else 'qemu'
            node = vm_info.get('node', 'pve')
            
            # Get real logs from the container/VM (last 1000 lines)
            log_result = subprocess.run(
                ['pvesh', 'get', f'/nodes/{node}/{vm_type}/{vmid}/log', '--start', '0', '--limit', '1000'],
                capture_output=True, text=True, timeout=10
            )
            
            logs = []
            if log_result.returncode == 0:
                # Parse as plain text (each line is a log entry)
                for i, line in enumerate(log_result.stdout.split('\n')):
                    if line.strip():
                        logs.append({'n': i, 't': line})
            
            return jsonify({
                'vmid': vmid,
                'name': vm_info.get('name'),
                'type': vm_type,
                'node': node,
                'log_lines': len(logs),
                'logs': logs
            })
        else:
            return jsonify({'error': 'Failed to get VM logs'}), 500
    except Exception as e:
        print(f"Error getting VM logs: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/vms/<int:vmid>/control', methods=['POST'])
def api_vm_control(vmid):
    """Control VM/LXC (start, stop, shutdown, reboot)"""
    try:
        data = request.get_json()
        action = data.get('action')  # start, stop, shutdown, reboot
        
        if action not in ['start', 'stop', 'shutdown', 'reboot']:
            return jsonify({'error': 'Invalid action'}), 400
        
        # Get VM type and node
        result = subprocess.run(['pvesh', 'get', f'/cluster/resources', '--type', 'vm', '--output-format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            resources = json.loads(result.stdout)
            vm_info = None
            for resource in resources:
                if resource.get('vmid') == vmid:
                    vm_info = resource
                    break
            
            if not vm_info:
                return jsonify({'error': f'VM/LXC {vmid} not found'}), 404
            
            vm_type = 'lxc' if vm_info.get('type') == 'lxc' else 'qemu'
            node = vm_info.get('node', 'pve')
            
            # Execute action
            control_result = subprocess.run(
                ['pvesh', 'create', f'/nodes/{node}/{vm_type}/{vmid}/status/{action}'],
                capture_output=True, text=True, timeout=30
            )
            
            if control_result.returncode == 0:
                return jsonify({
                    'success': True,
                    'vmid': vmid,
                    'action': action,
                    'message': f'Successfully executed {action} on {vm_info.get("name")}'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': control_result.stderr
                }), 500
        else:
            return jsonify({'error': 'Failed to control VM'}), 500
    except Exception as e:
        print(f"Error controlling VM: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Starting ProxMenux Flask Server on port 8008...")
    print("Server will be accessible on all network interfaces (0.0.0.0:8008)")
    print("API endpoints available at: /api/system, /api/storage, /api/network, /api/vms, /api/logs, /api/health, /api/hardware")
    
    app.run(host='0.0.0.0', port=8008, debug=False)
.0.0', port=8008, debug=False)
