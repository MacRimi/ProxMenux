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
import select # Added for non-blocking read
import shutil # Added for shutil.which
import xml.etree.ElementTree as ET  # Added for XML parsing
import math # Imported math for format_bytes function
import urllib.parse # Added for URL encoding
import platform # Added for platform.release()

app = Flask(__name__)
CORS(app)  # Enable CORS for Next.js frontend

def identify_gpu_type(name, vendor=None, bus=None, driver=None):
    """
    Returns: 'Integrated' or 'PCI' (discrete)
    - name: full device name (e.g. 'AMD/ATI Phoenix3 (rev b3)')
    - vendor: 'Intel', 'AMD', 'NVIDIA', 'ASPEED', 'Matrox'... (optional)
    - bus: address such as '0000:65:00.0' or '65:00.0' (optional)
    - driver: e.g. 'i915', 'amdgpu', 'nvidia' (optional)
    """

    n = (name or "").lower()
    v = (vendor or "").lower()
    d = (driver or "").lower()
    b = (bus or "")

    bmc_keywords = ['aspeed', 'ast', 'matrox g200', 'g200e', 'g200eh', 'mgag200']
    if any(k in n for k in bmc_keywords) or v in ['aspeed', 'matrox']:
        return 'Integrated'

    intel_igpu_words = ['uhd graphics', 'iris', 'integrated graphics controller']
    if v == 'intel' or 'intel corporation' in n:
        if d == 'i915' or any(w in n for w in intel_igpu_words):
            return 'Integrated'
        if b.startswith('0000:00:02.0') or b.startswith('00:02.0'):
            return 'Integrated'
        return 'Integrated'

    amd_apu_keywords = [
        'phoenix', 'rembrandt', 'cezanne', 'lucienne', 'renoir', 'picasso', 'raven',
        'dali', 'barcelo', 'van gogh', 'mendocino', 'hawk point', 'strix point',
        'radeon 780m', 'radeon 760m', 'radeon 680m', 'radeon 660m',
        'vega 3', 'vega 6', 'vega 7', 'vega 8', 'vega 10', 'vega 11'
    ]
    if v.startswith('advanced micro devices') or v == 'amd' or 'amd/ati' in n:
        if any(k in n for k in amd_apu_keywords):
            return 'Integrated'
        if 'radeon graphics' in n:
            return 'Integrated'
        discrete_markers = ['rx ', 'rx-', 'radeon pro', 'w5', 'w6', 'polaris', 'navi', 'xt ', 'xt-']
        if d == 'amdgpu' and not any(m in n for m in discrete_markers):
            return 'Integrated'
        return 'PCI'

    if v == 'nvidia' or 'nvidia corporation' in n:
        if 'tegra' in n:
            return 'Integrated'
        return 'PCI'

    soc_keywords = ['tegra', 'mali', 'adreno', 'powervr', 'videocore']
    if any(k in n for k in soc_keywords):
        return 'Integrated'

    if b.startswith('0000:00:') or b.startswith('00:'):
        return 'Integrated'

    # Fallback
    return 'PCI'


# Helper function to format bytes into human-readable string
def format_bytes(size_in_bytes):
    """Converts bytes to a human-readable string (KB, MB, GB, TB)."""
    if size_in_bytes is None:
        return "N/A"
    if size_in_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_in_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_in_bytes / p, 2)
    return f"{s} {size_name[i]}"

# Helper functions for system info
def get_cpu_temperature():
    """Get CPU temperature using psutil if available, otherwise return 0."""
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
        print(f"Warning: Error reading temperature sensors: {e}")
    return temp

def get_uptime():
    """Get system uptime in a human-readable format."""
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        return str(timedelta(seconds=int(uptime_seconds)))
    except Exception as e:
        print(f"Warning: Error getting uptime: {e}")
        return "N/A"

def get_proxmox_version():
    """Get Proxmox version if available."""
    proxmox_version = None
    try:
        result = subprocess.run(['pveversion'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Parse output like "pve-manager/9.0.6/..."
            version_line = result.stdout.strip().split('\n')[0]
            if '/' in version_line:
                proxmox_version = version_line.split('/')[1]
    except FileNotFoundError:
        print("Warning: pveversion command not found - Proxmox may not be installed.")
    except Exception as e:
        print(f"Warning: Error getting Proxmox version: {e}")
    return proxmox_version

def get_available_updates():
    """Get the number of available package updates."""
    available_updates = 0
    try:
        # Use apt list --upgradable to count available updates
        result = subprocess.run(['apt', 'list', '--upgradable'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            # Count lines minus the header line
            lines = result.stdout.strip().split('\n')
            available_updates = max(0, len(lines) - 1)
    except FileNotFoundError:
        print("Warning: apt command not found - cannot check for updates.")
    except Exception as e:
        print(f"Warning: Error checking for updates: {e}")
    return available_updates

# AGREGANDO FUNCIÓN PARA PARSEAR PROCESOS DE INTEL_GPU_TOP (SIN -J)
def get_intel_gpu_processes_from_text():
    """Parse processes from intel_gpu_top text output (more reliable than JSON)"""
    try:
        print(f"[v0] Executing intel_gpu_top (text mode) to capture processes...", flush=True)
        process = subprocess.Popen(
            ['intel_gpu_top'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        # Wait 2 seconds for intel_gpu_top to collect data
        time.sleep(2)
        
        # Terminate and get output
        process.terminate()
        try:
            stdout, _ = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, _ = process.communicate()
        
        processes = []
        lines = stdout.split('\n')
        
        # Find the process table header
        header_found = False
        for i, line in enumerate(lines):
            if 'PID' in line and 'NAME' in line and 'Render/3D' in line:
                header_found = True
                # Process lines after header
                for proc_line in lines[i+1:]:
                    proc_line = proc_line.strip()
                    if not proc_line or proc_line.startswith('intel-gpu-top'):
                        continue
                    
                    # Parse process line
                    # Format: PID MEM RSS Render/3D Blitter Video VideoEnhance NAME
                    parts = proc_line.split()
                    if len(parts) >= 8:
                        try:
                            pid = parts[0]
                            mem_str = parts[1]  # e.g., "177568K"
                            rss_str = parts[2]  # e.g., "116500K"
                            
                            # Convert memory values (remove 'K' and convert to bytes)
                            mem_total = int(mem_str.replace('K', '')) * 1024 if 'K' in mem_str else 0
                            mem_resident = int(rss_str.replace('K', '')) * 1024 if 'K' in rss_str else 0
                            
                            # Find the process name (last element)
                            name = parts[-1]
                            
                            # Parse engine utilization from the bars
                            # The bars are between the memory and name
                            # We'll estimate utilization based on bar characters
                            bar_section = ' '.join(parts[3:-1])
                            
                            # Simple heuristic: count █ characters for each engine section
                            engines = {}
                            engine_names = ['Render/3D', 'Blitter', 'Video', 'VideoEnhance']
                            bar_sections = bar_section.split('||')
                            
                            for idx, engine_name in enumerate(engine_names):
                                if idx < len(bar_sections):
                                    bar_str = bar_sections[idx]
                                    # Count filled bar characters
                                    filled_chars = bar_str.count('█') + bar_str.count('▎') * 0.25
                                    # Estimate percentage (assuming ~50 chars = 100%)
                                    utilization = min(100.0, (filled_chars / 50.0) * 100.0)
                                    if utilization > 0:
                                        engines[engine_name] = f"{utilization:.1f}%"
                                        
                                    if engine_name == 'Render/3D' and utilization > 0:
                                        engine_names[0] = f"Render/3D ({utilization:.1f}%)"
                                    elif engine_name == 'Blitter' and utilization > 0:
                                        engine_names[1] = f"Blitter ({utilization:.1f}%)"
                                    elif engine_name == 'Video' and utilization > 0:
                                        engine_names[2] = f"Video ({utilization:.1f}%)"
                                    elif engine_name == 'VideoEnhance' and utilization > 0:
                                        engine_names[3] = f"VideoEnhance ({utilization:.1f}%)"

                            if engines:  # Only add if there's some GPU activity
                                process_info = {
                                    'name': name,
                                    'pid': pid,
                                    'memory': {
                                        'total': mem_total,
                                        'shared': 0,  # Not available in text output
                                        'resident': mem_resident
                                    },
                                    'engines': engines
                                }
                                processes.append(process_info)
                                print(f"[v0] Found process from text: {name} (PID: {pid}) with {len(engines)} active engines", flush=True)
                        except (ValueError, IndexError) as e:
                            print(f"[v0] Error parsing process line: {e}", flush=True)
                            continue
                break
        
        if not header_found:
            print(f"[v0] No process table found in intel_gpu_top output", flush=True)
        
        return processes
    except Exception as e:
        print(f"[v0] Error getting processes from intel_gpu_top text: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return []

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
    """Get VM and LXC names from Proxmox API (only from local node)"""
    vm_lxc_map = {}
    
    try:
        local_node = socket.gethostname()
        
        result = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            resources = json.loads(result.stdout)
            for resource in resources:
                node = resource.get('node', '')
                if node != local_node:
                    continue
                
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

# Moved helper functions for system info up
# def get_system_info(): ... (moved up)

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
                        
                        disk_size_kb = disk_size_bytes / 1024
                        
                        if disk_size_tb >= 1:
                            size_str = f"{disk_size_tb:.1f}T"
                        else:
                            size_str = f"{disk_size_gb:.1f}G"
                        
                        physical_disks[disk_name] = {
                            'name': disk_name,
                            'size': disk_size_kb,  # In KB for formatMemory() in Storage Summary
                            'size_formatted': size_str,  # Added formatted size string for Storage section
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
                            'rotation_rate': smart_data.get('rotation_rate', 0),  # Added
                            'power_cycles': smart_data.get('power_cycles', 0),   # Added
                            'percentage_used': smart_data.get('percentage_used'), # Added
                            'media_wearout_indicator': smart_data.get('media_wearout_indicator'), # Added
                            'wear_leveling_count': smart_data.get('wear_leveling_count'), # Added
                            'total_lbas_written': smart_data.get('total_lbas_written'), # Added
                            'ssd_life_left': smart_data.get('ssd_life_left') # Added
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
            
            zfs_disks = set()
            
            for partition in disk_partitions:
                try:
                    # Skip special filesystems
                    if partition.fstype in ['tmpfs', 'devtmpfs', 'squashfs', 'overlay']:
                        continue
                    
                    if partition.fstype == 'zfs':
                        print(f"[v0] Skipping ZFS filesystem {partition.mountpoint}, will count from pool data")
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
            
            try:
                result = subprocess.run(['zpool', 'list', '-H', '-p', '-o', 'name,size,alloc,free,health'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            parts = line.split('\t')
                            if len(parts) >= 5:
                                pool_name = parts[0]
                                pool_size_bytes = int(parts[1])
                                pool_alloc_bytes = int(parts[2])
                                pool_free_bytes = int(parts[3])
                                pool_health = parts[4]
                                
                                total_used += pool_alloc_bytes
                                total_available += pool_free_bytes
                                
                                print(f"[v0] ZFS Pool {pool_name}: allocated={pool_alloc_bytes / (1024**3):.2f}GB, free={pool_free_bytes / (1024**3):.2f}GB")
                                
                                def format_zfs_size(size_bytes):
                                    size_tb = size_bytes / (1024**4)
                                    size_gb = size_bytes / (1024**3)
                                    if size_tb >= 1:
                                        return f"{size_tb:.1f}T"
                                    else:
                                        return f"{size_gb:.1f}G"
                                
                                pool_info = {
                                    'name': pool_name,
                                    'size': format_zfs_size(pool_size_bytes),
                                    'allocated': format_zfs_size(pool_alloc_bytes),
                                    'free': format_zfs_size(pool_free_bytes),
                                    'health': pool_health
                                }
                                storage_data['zfs_pools'].append(pool_info)
                                
                                try:
                                    pool_status = subprocess.run(['zpool', 'status', pool_name], 
                                                               capture_output=True, text=True, timeout=5)
                                    if pool_status.returncode == 0:
                                        for status_line in pool_status.stdout.split('\n'):
                                            for disk_name in physical_disks.keys():
                                                if disk_name in status_line:
                                                    zfs_disks.add(disk_name)
                                except Exception as e:
                                    print(f"Error getting ZFS pool status for {pool_name}: {e}")
                                    
            except FileNotFoundError:
                print("[v0] Note: ZFS not installed")
            except Exception as e:
                print(f"[v0] Note: ZFS not available or no pools: {e}")
            
            storage_data['used'] = round(total_used / (1024**3), 1)
            storage_data['available'] = round(total_available / (1024**3), 1)
            
            print(f"[v0] Total storage used: {storage_data['used']}GB (including ZFS pools)")
            
        except Exception as e:
            print(f"Error getting partition info: {e}")
        
        storage_data['disks'] = list(physical_disks.values())
        
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
        'percentage_used': None,  # NVMe: Percentage Used (0-100)
        'media_wearout_indicator': None,  # SSD: Media Wearout Indicator (Intel/Samsung)
        'wear_leveling_count': None,  # SSD: Wear Leveling Count
        'total_lbas_written': None,  # SSD/NVMe: Total LBAs Written
        'ssd_life_left': None,  # SSD: SSD Life Left percentage
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
        
        process = None # Initialize process to None
        for cmd_index, cmd in enumerate(commands_to_try):
            print(f"[v0] Attempt {cmd_index + 1}/{len(commands_to_try)}: Running command: {' '.join(cmd)}")
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                # Use communicate with a timeout to avoid hanging if the process doesn't exit
                stdout, stderr = process.communicate(timeout=15)
                result_code = process.returncode
                
                print(f"[v0] Command return code: {result_code}")
                
                if stderr:
                    stderr_preview = stderr[:200].replace('\n', ' ')
                    print(f"[v0] stderr: {stderr_preview}")
                
                has_output = stdout and len(stdout.strip()) > 50
                
                if has_output:
                    print(f"[v0] Got output ({len(stdout)} bytes), attempting to parse...")
                    
                    # Try JSON parsing first (if -j flag was used)
                    if '-j' in cmd:
                        try:
                            print(f"[v0] Attempting JSON parse...")
                            data = json.loads(stdout)
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
                                if 'percentage_used' in nvme_data:
                                    smart_data['percentage_used'] = nvme_data['percentage_used']
                                    print(f"[v0] NVMe Percentage Used: {smart_data['percentage_used']}%")
                                if 'data_units_written' in nvme_data:
                                    # data_units_written está en unidades de 512KB
                                    data_units = nvme_data['data_units_written']
                                    # Convertir a GB (data_units * 512KB / 1024 / 1024)
                                    total_gb = (data_units * 512) / (1024 * 1024)
                                    smart_data['total_lbas_written'] = round(total_gb, 2)
                                    print(f"[v0] NVMe Total Data Written: {smart_data['total_lbas_written']} GB")
                            
                            # Parse ATA SMART attributes
                            if 'ata_smart_attributes' in data and 'table' in data['ata_smart_attributes']:
                                print(f"[v0] Parsing ATA SMART attributes...")
                                for attr in data['ata_smart_attributes']['table']:
                                    attr_id = attr.get('id')
                                    raw_value = attr.get('raw', {}).get('value', 0)
                                    normalized_value = attr.get('value', 0)  # Normalized value (0-100)
                                    
                                    if attr_id == 9:  # Power_On_Hours
                                        smart_data['power_on_hours'] = raw_value
                                        print(f"[v0] Power On Hours (ID 9): {raw_value}")
                                    elif attr_id == 12:  # Power_Cycle_Count
                                        smart_data['power_cycles'] = raw_value
                                        print(f"[v0] Power Cycles (ID 12): {raw_value}")
                                    elif attr_id == 194:  # Temperature_Celsius
                                        if smart_data['temperature'] == 0:
                                            smart_data['temperature'] = raw_value
                                            print(f"[v0] Temperature (ID 194): {smart_data['temperature']}°C")
                                    elif attr_id == 190:  # Airflow_Temperature_Cel
                                        if smart_data['temperature'] == 0:
                                            smart_data['temperature'] = raw_value
                                            print(f"[v0] Airflow Temperature (ID 190): {smart_data['temperature']}°C")
                                    elif attr_id == 5:  # Reallocated_Sector_Ct
                                        smart_data['reallocated_sectors'] = raw_value
                                        print(f"[v0] Reallocated Sectors (ID 5): {smart_data['reallocated_sectors']}")
                                    elif attr_id == 197:  # Current_Pending_Sector
                                        smart_data['pending_sectors'] = raw_value
                                        print(f"[v0] Pending Sectors (ID 197): {smart_data['pending_sectors']}")
                                    elif attr_id == 199:  # UDMA_CRC_Error_Count
                                        smart_data['crc_errors'] = raw_value
                                        print(f"[v0] CRC Errors (ID 199): {smart_data['crc_errors']}")
                                    elif attr_id == '230': 
                                        try:
                                            wear_used = None
                                            rv = str(raw_value).strip()

                                            if rv.startswith("0x") and len(rv) >= 8:
                                                # 0x001c0014... -> '001c' -> 0x001c = 28
                                                wear_hex = rv[4:8]
                                                wear_used = int(wear_hex, 16)
                                            else:
                                                wear_used = int(rv)

                                            if wear_used is None or wear_used < 0 or wear_used > 100:
                                                wear_used = max(0, min(100, 100 - int(normalized_value)))

                                            smart_data['media_wearout_indicator'] = wear_used                   
                                            smart_data['ssd_life_left'] = max(0, 100 - wear_used)              
                                            print(f"[v0] Media Wearout Indicator (ID 230): {wear_used}% used, {smart_data['ssd_life_left']}% life left")
                                        except Exception as e:
                                            print(f"[v0] Error parsing Media_Wearout_Indicator (ID 230): {e}")    
                                    elif attr_id == '233':  # Media_Wearout_Indicator (Intel/Samsung SSD)
                                        # Valor normalizado: 100 = nuevo, 0 = gastado
                                        # Invertimos para mostrar desgaste: 0% = nuevo, 100% = gastado
                                        smart_data['media_wearout_indicator'] = 100 - normalized_value
                                        print(f"[v0] Media Wearout Indicator (ID 233): {smart_data['media_wearout_indicator']}% used")
                                    elif attr_id == '177':  # Wear_Leveling_Count
                                        # Valor normalizado: 100 = nuevo, 0 = gastado
                                        smart_data['wear_leveling_count'] = 100 - normalized_value
                                        print(f"[v0] Wear Leveling Count (ID 177): {smart_data['wear_leveling_count']}% used")
                                    elif attr_id == '202':  # Percentage_Lifetime_Remain (algunos fabricantes)
                                        # Valor normalizado: 100 = nuevo, 0 = gastado
                                        smart_data['ssd_life_left'] = normalized_value
                                        print(f"[v0] SSD Life Left (ID 202): {smart_data['ssd_life_left']}%")
                                    elif attr_id == '231':  # SSD_Life_Left (algunos fabricantes)
                                        smart_data['ssd_life_left'] = normalized_value
                                        print(f"[v0] SSD Life Left (ID 231): {smart_data['ssd_life_left']}%")
                                    elif attr_id == '241':  # Total_LBAs_Written
                                        # Convertir a GB (raw_value es en sectores de 512 bytes)
                                        try:
                                            raw_int = int(raw_value.replace(',', ''))
                                            total_gb = (raw_int * 512) / (1024 * 1024 * 1024)
                                            smart_data['total_lbas_written'] = round(total_gb, 2)
                                            print(f"[v0] Total LBAs Written (ID 241): {smart_data['total_lbas_written']} GB")
                                        except ValueError:
                                            pass
                            
                            # If we got good data, break out of the loop
                            if smart_data['model'] != 'Unknown' and smart_data['serial'] != 'Unknown':
                                print(f"[v0] Successfully extracted complete data from JSON (attempt {cmd_index + 1})")
                                break
                                
                        except json.JSONDecodeError as e:
                            print(f"[v0] JSON parse failed: {e}, trying text parsing...")
                    
                    if smart_data['model'] == 'Unknown' or smart_data['serial'] == 'Unknown' or smart_data['temperature'] == 0:
                        print(f"[v0] Parsing text output (model={smart_data['model']}, serial={smart_data['serial']}, temp={smart_data['temperature']})...")
                        output = stdout
                        
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
                                        elif attr_id == '230': 
                                            try:
                                                wear_used = None
                                                raw_str = str(raw_value).strip()

                                                if raw_str.startswith("0x") and len(raw_str) >= 8:
      
                                                    wear_hex = raw_str[4:8]
                                                    wear_used = int(wear_hex, 16)
                                                else:
                                                    wear_used = int(raw_str)

                                                if wear_used is None or wear_used < 0 or wear_used > 100:
                                                    normalized_value = int(parts[3]) if len(parts) > 3 else 100
                                                    wear_used = max(0, min(100, 100 - normalized_value))

                                                smart_data['media_wearout_indicator'] = wear_used
                                                smart_data['ssd_life_left'] = max(0, 100 - wear_used)
                                                print(f"[v0] Media Wearout Indicator (ID 230): {wear_used}% used, {smart_data['ssd_life_left']}% life left")
                                            except Exception as e:
                                                print(f"[v0] Error parsing Media_Wearout_Indicator (ID 230): {e}")    
                                        elif attr_id == '233':  # Media_Wearout_Indicator (Intel/Samsung SSD)
                                            normalized_value = int(parts[3]) if len(parts) > 3 else 100
                                            smart_data['media_wearout_indicator'] = 100 - normalized_value
                                            print(f"[v0] Media Wearout Indicator (ID 233): {smart_data['media_wearout_indicator']}% used")
                                        elif attr_id == '177':  # Wear_Leveling_Count
                                            # Valor normalizado: 100 = nuevo, 0 = gastado
                                            normalized_value = int(parts[3]) if len(parts) > 3 else 100
                                            smart_data['wear_leveling_count'] = 100 - normalized_value
                                            print(f"[v0] Wear Leveling Count (ID 177): {smart_data['wear_leveling_count']}% used")
                                        elif attr_id == '202':  # Percentage_Lifetime_Remain (algunos fabricantes)
                                            # Valor normalizado: 100 = nuevo, 0 = gastado
                                            normalized_value = int(parts[3]) if len(parts) > 3 else 100
                                            smart_data['ssd_life_left'] = normalized_value
                                            print(f"[v0] SSD Life Left (ID 202): {smart_data['ssd_life_left']}%")
                                        elif attr_id == '231':  # SSD_Life_Left (algunos fabricantes)
                                            normalized_value = int(parts[3]) if len(parts) > 3 else 100
                                            smart_data['ssd_life_left'] = normalized_value
                                            print(f"[v0] SSD Life Left (ID 231): {smart_data['ssd_life_left']}%")
                                        elif attr_id == '241':  # Total_LBAs_Written
                                            # Convertir a GB (raw_value es en sectores de 512 bytes)
                                            try:
                                                raw_int = int(raw_value.replace(',', ''))
                                                total_gb = (raw_int * 512) / (1024 * 1024 * 1024)
                                                smart_data['total_lbas_written'] = round(total_gb, 2)
                                                print(f"[v0] Total LBAs Written (ID 241): {smart_data['total_lbas_written']} GB")
                                            except ValueError:
                                                pass
                                            
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
                    print(f"[v0] No usable output (return code {result_code}), trying next command...")
            
            except subprocess.TimeoutExpired:
                print(f"[v0] Command timeout for attempt {cmd_index + 1}, trying next...")
                if process and process.returncode is None:
                    process.kill()
                continue
            except Exception as e:
                print(f"[v0] Error in attempt {cmd_index + 1}: {type(e).__name__}: {e}")
                if process and process.returncode is None:
                    process.kill()
                continue
            finally:
                # Ensure the process is terminated if it's still running
                if process and process.poll() is None: 
                    try:
                        process.kill()
                        print(f"[v0] Process killed for command: {' '.join(cmd)}")
                    except Exception as kill_err:
                        print(f"[v0] Error killing process: {kill_err}")


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
        print(f"[v0] ERROR: smartctl not found - install smartmontools for disk monitoring.")
    except Exception as e:
        print(f"[v0] ERROR: Unexpected exception for {disk_name}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"[v0] ===== Final SMART data for /dev/{disk_name}: {smart_data} =====")
    return smart_data

# START OF CHANGES FOR get_proxmox_storage
def get_proxmox_storage():
    """Get Proxmox storage information using pvesh (filtered by local node)"""
    try:
        local_node = socket.gethostname()
        print(f"[v0] Getting Proxmox storage for local node: {local_node}")
        
        result = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'storage', '--output-format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            print(f"[v0] pvesh command failed with return code {result.returncode}")
            print(f"[v0] stderr: {result.stderr}")
            return {
                'error': 'pvesh command not available or failed',
                'storage': []
            }
        
        storage_list = []
        resources = json.loads(result.stdout)
        
        for resource in resources:
            node = resource.get('node', '')
            
            # Filtrar solo storage del nodo local
            if node != local_node:
                print(f"[v0] Skipping storage {resource.get('storage')} from remote node: {node}")
                continue
            
            name = resource.get('storage', 'unknown')
            storage_type = resource.get('plugintype', 'unknown')
            status = resource.get('status', 'unknown')
            
            try:
                total = int(resource.get('maxdisk', 0))
                used = int(resource.get('disk', 0))
                available = total - used if total > 0 else 0
            except (ValueError, TypeError):
                print(f"[v0] Skipping storage {name} - invalid numeric data")
                continue
            
            # Si total es 0, significa que hay un error de conexión o el datastore no está disponible
            if total == 0:
                print(f"[v0] Skipping storage {name} - invalid data (total=0, likely connection error)")
                continue
            
            # Si el status es "inactive", también lo omitimos
            if status.lower() != "available":
                print(f"[v0] Skipping storage {name} - status is not available: {status}")
                continue
            
            # Calcular porcentaje
            percent = (used / total * 100) if total > 0 else 0.0
            
            # Convert bytes to GB
            total_gb = round(total / (1024**3), 2)
            used_gb = round(used / (1024**3), 2)
            available_gb = round(available / (1024**3), 2)
            
            storage_info = {
                'name': name,
                'type': storage_type,
                'status': 'active',  # Normalizar status para compatibilidad con frontend
                'total': total_gb,
                'used': used_gb,
                'available': available_gb,
                'percent': round(percent, 2),
                'node': node  # Incluir información del nodo
            }
            
            print(f"[v0] Found storage on {node}: {name} ({storage_type}) - {used_gb}/{total_gb} GB ({percent:.2f}%)")
            storage_list.append(storage_info)
        
        print(f"[v0] Total storage entries on local node {local_node}: {len(storage_list)}")
        return {'storage': storage_list}
        
    except FileNotFoundError:
        print("[v0] pvesh command not found - Proxmox not installed or not in PATH")
        return {
            'error': 'pvesh command not found - Proxmox not installed',
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
# END OF CHANGES FOR get_proxmox_storage

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
            network_data['traffic']['packet_loss_out'] = round((io_stats.dropout / total_packets_out) * 100, 2)
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
    """Get Proxmox VM and LXC information (requires pvesh command) - only from local node"""
    try:
        all_vms = []
        
        try:
            local_node = socket.gethostname()
            print(f"[v0] Local node detected: {local_node}")
            
            result = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                resources = json.loads(result.stdout)
                for resource in resources:
                    node = resource.get('node', '')
                    if node != local_node:
                        print(f"[v0] Skipping VM {resource.get('vmid')} from remote node: {node}")
                        continue
                    
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
                
                print(f"[v0] Total VMs/LXCs on local node {local_node}: {len(all_vms)}")
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


# START OF CHANGES FOR get_ups_info
def get_ups_info():
    """Get UPS information from NUT (upsc) - supports both local and remote UPS"""
    ups_list = []
    
    try:
        configured_ups = {}
        try:
            with open('/etc/nut/upsmon.conf', 'r') as f:
                for line in f:
                    line = line.strip()
                    # Look for MONITOR lines: MONITOR ups@host powervalue username password type
                    if line.startswith('MONITOR') and not line.startswith('#'):
                        parts = line.split()
                        if len(parts) >= 2:
                            ups_spec = parts[1]  # Format: upsname@hostname or just upsname
                            if '@' in ups_spec:
                                ups_name, ups_host = ups_spec.split('@', 1)
                                configured_ups[ups_spec] = {
                                    'name': ups_name,
                                    'host': ups_host,
                                    'is_remote': ups_host not in ['localhost', '127.0.0.1', '::1']
                                }
                            else:
                                configured_ups[ups_spec] = {
                                    'name': ups_spec,
                                    'host': 'localhost',
                                    'is_remote': False
                                }
        except FileNotFoundError:
            print("[v0] /etc/nut/upsmon.conf not found")
        except Exception as e:
            print(f"[v0] Error reading upsmon.conf: {e}")
        
        # Get list of locally available UPS
        local_ups = []
        try:
            result = subprocess.run(['upsc', '-l'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                local_ups = [ups.strip() for ups in result.stdout.strip().split('\n') if ups.strip()]
        except Exception as e:
            print(f"[v0] Error listing local UPS: {e}")
        
        all_ups = {}
        
        # Add configured UPS first (priority)
        for ups_spec, ups_info in configured_ups.items():
            ups_name = ups_info['name']
            all_ups[ups_name] = (ups_spec, ups_info['host'], ups_info['is_remote'])
        
        # Add local UPS only if not already in configured list
        for ups_name in local_ups:
            if ups_name not in all_ups:
                all_ups[ups_name] = (ups_name, 'localhost', False)
        
        # Get detailed info for each UPS
        for ups_name, (ups_spec, ups_host, is_remote) in all_ups.items():
            try:
                ups_data = {
                    'name': ups_spec.split('@')[0] if '@' in ups_spec else ups_spec,
                    'host': ups_host,
                    'is_remote': is_remote,
                    'connection_type': 'Remote (NUT)' if is_remote else 'Local'
                }
                
                # Get detailed UPS info using upsc
                cmd = ['upsc', ups_spec] if '@' in ups_spec else ['upsc', ups_spec, ups_host] if is_remote else ['upsc', ups_spec]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if ':' in line:
                            key, value = line.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # Store all UPS variables for detailed modal
                            ups_data[key] = value
                            
                            # Map common variables for quick access
                            if key == 'device.model':
                                ups_data['model'] = value
                            elif key == 'device.mfr':
                                ups_data['manufacturer'] = value
                            elif key == 'device.serial':
                                ups_data['serial'] = value
                            elif key == 'device.type':
                                ups_data['device_type'] = value
                            elif key == 'ups.status':
                                ups_data['status'] = value
                            elif key == 'battery.charge':
                                ups_data['battery_charge'] = f"{value}%"
                                try:
                                    ups_data['battery_charge_raw'] = float(value)
                                except ValueError:
                                    ups_data['battery_charge_raw'] = None
                            elif key == 'battery.runtime':
                                try:
                                    runtime_sec = int(value)
                                    runtime_min = runtime_sec // 60
                                    ups_data['time_left'] = f"{runtime_min} minutes"
                                    ups_data['time_left_seconds'] = runtime_sec
                                except ValueError:
                                    ups_data['time_left'] = value
                                    ups_data['time_left_seconds'] = None
                            elif key == 'battery.voltage':
                                ups_data['battery_voltage'] = f"{value}V"
                            elif key == 'battery.date':
                                ups_data['battery_date'] = value
                            elif key == 'ups.load':
                                ups_data['load_percent'] = f"{value}%"
                                try:
                                    ups_data['load_percent_raw'] = float(value)
                                except ValueError:
                                    ups_data['load_percent_raw'] = None
                            elif key == 'input.voltage':
                                ups_data['input_voltage'] = f"{value}V"
                            elif key == 'input.frequency':
                                ups_data['input_frequency'] = f"{value}Hz"
                            elif key == 'output.voltage':
                                ups_data['output_voltage'] = f"{value}V"
                            elif key == 'output.frequency':
                                ups_data['output_frequency'] = f"{value}Hz"
                            elif key == 'ups.realpower':
                                ups_data['real_power'] = f"{value}W"
                            elif key == 'ups.power':
                                ups_data['apparent_power'] = f"{value}VA"
                            elif key == 'ups.firmware':
                                ups_data['firmware'] = value
                            elif key == 'driver.name':
                                ups_data['driver'] = value
                    
                    ups_list.append(ups_data)
                    print(f"[v0] UPS found: {ups_data.get('model', 'Unknown')} ({ups_data['connection_type']})")
                else:
                    print(f"[v0] Failed to get info for UPS: {ups_spec}")
                    
            except Exception as e:
                print(f"[v0] Error getting UPS info for {ups_spec}: {e}")
        
    except FileNotFoundError:
        print("[v0] upsc not found")
    except Exception as e:
        print(f"[v0] Error in get_ups_info: {e}")
    
    return ups_list
# END OF CHANGES FOR get_ups_info


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


# --- GPU Monitoring Functions ---

def get_detailed_gpu_info(gpu):
    """Get detailed monitoring information for a GPU"""
    vendor = gpu.get('vendor', '').lower()
    slot = gpu.get('slot', '')
    
    print(f"[v0] ===== get_detailed_gpu_info called for GPU {slot} (vendor: {vendor}) =====", flush=True)
    
    detailed_info = {
        'has_monitoring_tool': False,
        'temperature': None,
        'fan_speed': None,
        'fan_unit': None,
        'utilization_gpu': None,
        'utilization_memory': None,
        'memory_used': None,
        'memory_total': None,
        'memory_free': None,
        'power_draw': None,
        'power_limit': None,
        'clock_graphics': None,
        'clock_memory': None,
        'processes': [],
        'engine_render': None,
        'engine_blitter': None,
        'engine_video': None,
        'engine_video_enhance': None,
        # Added for NVIDIA/AMD specific engine info if available
        'engine_encoder': None,
        'engine_decoder': None,
        'driver_version': None # Added driver_version
    }
    
    # Intel GPU monitoring with intel_gpu_top
    if 'intel' in vendor:
        print(f"[v0] Intel GPU detected, checking for intel_gpu_top...", flush=True)
        
        intel_gpu_top_path = None
        system_paths = ['/usr/bin/intel_gpu_top', '/usr/local/bin/intel_gpu_top']
        for path in system_paths:
            if os.path.exists(path):
                intel_gpu_top_path = path
                print(f"[v0] Found system intel_gpu_top at: {path}", flush=True)
                break
        
        # Fallback to shutil.which if not found in system paths
        if not intel_gpu_top_path:
            intel_gpu_top_path = shutil.which('intel_gpu_top')
            if intel_gpu_top_path:
                print(f"[v0] Using intel_gpu_top from PATH: {intel_gpu_top_path}", flush=True)
        
        if intel_gpu_top_path:
            print(f"[v0] intel_gpu_top found, executing...", flush=True)
            try:
                print(f"[v0] Current user: {os.getenv('USER', 'unknown')}, UID: {os.getuid()}, GID: {os.getgid()}", flush=True)
                print(f"[v0] Current working directory: {os.getcwd()}", flush=True)
                
                drm_devices = ['/dev/dri/card0', '/dev/dri/renderD128']
                for drm_dev in drm_devices:
                    if os.path.exists(drm_dev):
                        stat_info = os.stat(drm_dev)
                        readable = os.access(drm_dev, os.R_OK)
                        writable = os.access(drm_dev, os.W_OK)
                        print(f"[v0] {drm_dev}: mode={oct(stat_info.st_mode)}, uid={stat_info.st_uid}, gid={stat_info.st_gid}, readable={readable}, writable={writable}", flush=True)
                
                # Prepare environment with all necessary variables
                env = os.environ.copy()
                env['TERM'] = 'xterm'  # Ensure terminal type is set
                
                cmd = f'{intel_gpu_top_path} -J' # Use the found path
                print(f"[v0] Executing command: {cmd}", flush=True)
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    shell=True,
                    env=env,
                    cwd='/'  # Ejecutar desde root en lugar de dentro del AppImage
                )
                
                print(f"[v0] Process started with PID: {process.pid}", flush=True)
                
                print(f"[v0] Waiting 1 second for intel_gpu_top to initialize and detect processes...", flush=True)
                time.sleep(1)
                
                start_time = time.time()
                timeout = 3
                json_objects = []
                buffer = ""
                brace_count = 0
                in_json = False
                
                print(f"[v0] Reading output from intel_gpu_top...", flush=True)
                
                while time.time() - start_time < timeout:
                    if process.poll() is not None:
                        print(f"[v0] Process terminated early with code: {process.poll()}", flush=True)
                        break
                    
                    try:
                        # Use non-blocking read with select to avoid hanging
                        ready, _, _ = select.select([process.stdout], [], [], 0.1)
                        if process.stdout in ready:
                            line = process.stdout.readline()
                            if not line:
                                time.sleep(0.01)
                                continue
                        else:
                            time.sleep(0.01)
                            continue

                        for char in line:
                            if char == '{':
                                if brace_count == 0:
                                    in_json = True
                                    buffer = char
                                else:
                                    buffer += char
                                brace_count += 1
                            elif char == '}':
                                buffer += char
                                brace_count -= 1
                                if brace_count == 0 and in_json:
                                    try:
                                        json_data = json.loads(buffer)
                                        json_objects.append(json_data)
                                        print(f"[v0] Found JSON object #{len(json_objects)} ({len(buffer)} chars)", flush=True)
                                        print(f"[v0] JSON keys: {list(json_data.keys())}", flush=True)
                                        
                                        if 'clients' in json_data:
                                            client_count = len(json_data['clients'])
                                            print(f"[v0] *** FOUND CLIENTS SECTION with {client_count} client(s) ***", flush=True)
                                            for client_id, client_data in json_data['clients']:
                                                client_name = client_data.get('name', 'Unknown')
                                                client_pid = client_data.get('pid', 'Unknown')
                                                print(f"[v0]   - Client: {client_name} (PID: {client_pid})", flush=True)
                                        else:
                                            print(f"[v0] No 'clients' key in this JSON object", flush=True)
                                        
                                        if len(json_objects) >= 5:
                                            print(f"[v0] Collected 5 JSON objects, stopping...", flush=True)
                                            break
                                    except json.JSONDecodeError:
                                        pass
                                    buffer = ""
                                    in_json = False
                            elif in_json:
                                buffer += char
                    except Exception as e:
                        print(f"[v0] Error reading line: {e}", flush=True)
                        break
                
                # Terminate process
                try:
                    process.terminate()
                    _, stderr_output = process.communicate(timeout=0.5) # Use communicate with a smaller timeout
                    if stderr_output:
                        print(f"[v0] intel_gpu_top stderr: {stderr_output}", flush=True)
                except subprocess.TimeoutExpired:
                    process.kill()
                    print("[v0] Process killed after terminate timeout.", flush=True)
                except Exception as e:
                    print(f"[v0] Error during process termination: {e}", flush=True)

                print(f"[v0] Collected {len(json_objects)} JSON objects total", flush=True)
                
                best_json = None
                
                # First priority: Find JSON with populated clients
                for json_obj in reversed(json_objects):
                    if 'clients' in json_obj:
                        clients_data = json_obj['clients']
                        if clients_data and len(clients_data) > 0:
                            print(f"[v0] Found JSON with {len(clients_data)} client(s)!", flush=True)
                            best_json = json_obj
                            break
                
                # Second priority: Use most recent JSON
                if not best_json and json_objects:
                    best_json = json_objects[-1]
                    print(f"[v0] No clients found, using most recent JSON for current GPU state", flush=True)

                if best_json:
                    print(f"[v0] Parsing selected JSON object...", flush=True)
                    data_retrieved = False
                    
                    # Initialize engine totals
                    engine_totals = {
                        'Render/3D': 0.0,
                        'Blitter': 0.0,
                        'Video': 0.0,
                        'VideoEnhance': 0.0
                    }
                    client_engine_totals = {
                        'Render/3D': 0.0,
                        'Blitter': 0.0,
                        'Video': 0.0,
                        'VideoEnhance': 0.0
                    }
                    
                    # Parse clients section (processes using GPU)
                    if 'clients' in best_json:
                        print(f"[v0] Parsing clients section...", flush=True)
                        clients = best_json['clients']
                        processes = []
                        
                        for client_id, client_data in clients:
                            process_info = {
                                'name': client_data.get('name', 'Unknown'),
                                'pid': client_data.get('pid', 'Unknown'),
                                'memory': {
                                    'total': client_data.get('memory', {}).get('system', {}).get('total', 0),
                                    'shared': client_data.get('memory', {}).get('system', {}).get('shared', 0),
                                    'resident': client_data.get('memory', {}).get('system', {}).get('resident', 0)
                                },
                                'engines': {}
                            }
                            
                            # Parse engine utilization for this process
                            engine_classes = client_data.get('engine-classes', {})
                            for engine_name, engine_data in engine_classes.items():
                                busy_value = float(engine_data.get('busy', 0))
                                process_info['engines'][engine_name] = f"{busy_value:.1f}%"
                                
                                # Sum up engine utilization across all processes
                                if engine_name in client_engine_totals:
                                    client_engine_totals[engine_name] += busy_value
                            
                            processes.append(process_info)
                            print(f"[v0] Added process: {process_info['name']} (PID: {process_info['pid']})", flush=True)
                        
                        detailed_info['processes'] = processes
                        print(f"[v0] Total processes found: {len(processes)}", flush=True)
                    else:
                        print(f"[v0] WARNING: No 'clients' section in selected JSON", flush=True)
                    
                    # Parse global engines section
                    if 'engines' in best_json:
                        print(f"[v0] Parsing engines section...", flush=True)
                        engines = best_json['engines']
                        
                        for engine_name, engine_data in engines.items():
                            # Remove the /0 suffix if present
                            clean_name = engine_name.replace('/0', '')
                            busy_value = float(engine_data.get('busy', 0))
                            
                            if clean_name in engine_totals:
                                engine_totals[clean_name] = busy_value
                    
                    # Use client engine totals if available, otherwise use global engines
                    final_engines = client_engine_totals if any(v > 0 for v in client_engine_totals.values()) else engine_totals
                    
                    detailed_info['engine_render'] = f"{final_engines['Render/3D']:.1f}%"
                    detailed_info['engine_blitter'] = f"{final_engines['Blitter']:.1f}%"
                    detailed_info['engine_video'] = f"{final_engines['Video']:.1f}%"
                    detailed_info['engine_video_enhance'] = f"{final_engines['VideoEnhance']:.1f}%"
                    
                    # Calculate overall GPU utilization (max of all engines)
                    max_utilization = max(final_engines.values())
                    detailed_info['utilization_gpu'] = f"{max_utilization:.1f}%"
                    
                    # Parse frequency
                    if 'frequency' in best_json:
                        freq_data = best_json['frequency']
                        actual_freq = freq_data.get('actual', 0)
                        detailed_info['clock_graphics'] = f"{actual_freq} MHz"
                        data_retrieved = True
                    
                    # Parse power
                    if 'power' in best_json:
                        power_data = best_json['power']
                        gpu_power = power_data.get('GPU', 0)
                        package_power = power_data.get('Package', 0)
                        # Use Package power as the main power draw since GPU is always 0.0 for integrated GPUs
                        detailed_info['power_draw'] = f"{package_power:.2f} W"
                        # Keep power_limit as a separate field (could be used for TDP limit in the future)
                        detailed_info['power_limit'] = f"{package_power:.2f} W"
                        data_retrieved = True
                    
                    if data_retrieved:
                        detailed_info['has_monitoring_tool'] = True
                        print(f"[v0] Intel GPU monitoring successful", flush=True)
                        print(f"[v0] - Utilization: {detailed_info['utilization_gpu']}", flush=True)
                        print(f"[v0] - Engines: R={detailed_info['engine_render']}, B={detailed_info['engine_blitter']}, V={detailed_info['engine_video']}, VE={detailed_info['engine_video_enhance']}", flush=True)
                        print(f"[v0] - Processes: {len(detailed_info['processes'])}", flush=True)
                        
                        if len(detailed_info['processes']) == 0:
                            print(f"[v0] No processes found in JSON, trying text output...", flush=True)
                            text_processes = get_intel_gpu_processes_from_text()
                            if text_processes:
                                detailed_info['processes'] = text_processes
                                print(f"[v0] Found {len(text_processes)} processes from text output", flush=True)
                    else:
                        print(f"[v0] WARNING: No data retrieved from intel_gpu_top", flush=True)
                else:
                    print(f"[v0] WARNING: No valid JSON objects found", flush=True)
                    # CHANGE: Evitar bloqueo al leer stderr - usar communicate() con timeout
                    try:
                        # Use communicate() with timeout instead of read() to avoid blocking
                        _, stderr_output = process.communicate(timeout=0.5)
                        if stderr_output:
                            print(f"[v0] intel_gpu_top stderr: {stderr_output}", flush=True)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        print(f"[v0] Process killed after timeout", flush=True)
                    except Exception as e:
                        print(f"[v0] Error reading stderr: {e}", flush=True)
            
            except Exception as e:
                print(f"[v0] Error running intel_gpu_top: {e}", flush=True)
                import traceback
                traceback.print_exc()
        else:
            print(f"[v0] intel_gpu_top not found in PATH", flush=True)
            # Fallback to text parsing if JSON parsing fails or -J is not available
            print("[v0] Trying intel_gpu_top text output for process parsing...", flush=True)
            detailed_info['processes'] = get_intel_gpu_processes_from_text()
            if detailed_info['processes']:
                detailed_info['has_monitoring_tool'] = True
                print(f"[v0] Intel GPU process monitoring (text mode) successful.", flush=True)
            else:
                print(f"[v0] Intel GPU process monitoring (text mode) failed.", flush=True)

    # NVIDIA GPU monitoring with nvidia-smi
    elif 'nvidia' in vendor:
        print(f"[v0] NVIDIA GPU detected, checking for nvidia-smi...", flush=True)
        if shutil.which('nvidia-smi'):
            print(f"[v0] nvidia-smi found, executing with XML output...", flush=True)
            try:
                cmd = ['nvidia-smi', '-q', '-x']
                print(f"[v0] Executing command: {' '.join(cmd)}", flush=True)
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                
                if result.returncode == 0 and result.stdout.strip():
                    print(f"[v0] nvidia-smi XML output received, parsing...", flush=True)
                    
                    try:
                        # Parse XML
                        root = ET.fromstring(result.stdout)
                        
                        # Get first GPU (assuming single GPU or taking first one)
                        gpu_elem = root.find('gpu')
                        
                        if gpu_elem is not None:
                            print(f"[v0] Processing NVIDIA GPU XML data...", flush=True)
                            data_retrieved = False
                            
                            driver_version_elem = gpu_elem.find('.//driver_version')
                            if driver_version_elem is not None and driver_version_elem.text:
                                detailed_info['driver_version'] = driver_version_elem.text.strip()
                                print(f"[v0] Driver Version: {detailed_info['driver_version']}", flush=True)
                            
                            # Parse temperature
                            temp_elem = gpu_elem.find('.//temperature/gpu_temp')
                            if temp_elem is not None and temp_elem.text:
                                try:
                                    # Remove ' C' suffix and convert to int
                                    temp_str = temp_elem.text.replace(' C', '').strip()
                                    detailed_info['temperature'] = int(temp_str)
                                    print(f"[v0] Temperature: {detailed_info['temperature']}°C", flush=True)
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse fan speed
                            fan_elem = gpu_elem.find('.//fan_speed')
                            if fan_elem is not None and fan_elem.text and fan_elem.text != 'N/A':
                                try:
                                    # Remove ' %' suffix and convert to int
                                    fan_str = fan_elem.text.replace(' %', '').strip()
                                    detailed_info['fan_speed'] = int(fan_str)
                                    detailed_info['fan_unit'] = '%'
                                    print(f"[v0] Fan Speed: {detailed_info['fan_speed']}%", flush=True)
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse power draw
                            power_elem = gpu_elem.find('.//gpu_power_readings/power_state')
                            instant_power_elem = gpu_elem.find('.//gpu_power_readings/instant_power_draw')
                            if instant_power_elem is not None and instant_power_elem.text and instant_power_elem.text != 'N/A':
                                try:
                                    # Remove ' W' suffix and convert to float
                                    power_str = instant_power_elem.text.replace(' W', '').strip()
                                    detailed_info['power_draw'] = float(power_str)
                                    print(f"[v0] Power Draw: {detailed_info['power_draw']} W", flush=True)
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse power limit
                            power_limit_elem = gpu_elem.find('.//gpu_power_readings/current_power_limit')
                            if power_limit_elem is not None and power_limit_elem.text and power_limit_elem.text != 'N/A':
                                try:
                                    power_limit_str = power_limit_elem.text.replace(' W', '').strip()
                                    detailed_info['power_limit'] = float(power_limit_str)
                                    print(f"[v0] Power Limit: {detailed_info['power_limit']} W", flush=True)
                                except ValueError:
                                    pass
                            
                            # Parse GPU utilization
                            gpu_util_elem = gpu_elem.find('.//utilization/gpu_util')
                            if gpu_util_elem is not None and gpu_util_elem.text:
                                try:
                                    util_str = gpu_util_elem.text.replace(' %', '').strip()
                                    detailed_info['utilization_gpu'] = int(util_str)
                                    print(f"[v0] GPU Utilization: {detailed_info['utilization_gpu']}%", flush=True)
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse memory utilization
                            mem_util_elem = gpu_elem.find('.//utilization/memory_util')
                            if mem_util_elem is not None and mem_util_elem.text:
                                try:
                                    mem_util_str = mem_util_elem.text.replace(' %', '').strip()
                                    detailed_info['utilization_memory'] = int(mem_util_str)
                                    print(f"[v0] Memory Utilization: {detailed_info['utilization_memory']}%", flush=True)
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse encoder utilization
                            encoder_util_elem = gpu_elem.find('.//utilization/encoder_util')
                            if encoder_util_elem is not None and encoder_util_elem.text and encoder_util_elem.text != 'N/A':
                                try:
                                    encoder_str = encoder_util_elem.text.replace(' %', '').strip()
                                    detailed_info['engine_encoder'] = int(encoder_str)
                                    print(f"[v0] Encoder Utilization: {detailed_info['engine_encoder']}%", flush=True)
                                except ValueError:
                                    pass
                            
                            # Parse decoder utilization
                            decoder_util_elem = gpu_elem.find('.//utilization/decoder_util')
                            if decoder_util_elem is not None and decoder_util_elem.text and decoder_util_elem.text != 'N/A':
                                try:
                                    decoder_str = decoder_util_elem.text.replace(' %', '').strip()
                                    detailed_info['engine_decoder'] = int(decoder_str)
                                    print(f"[v0] Decoder Utilization: {detailed_info['engine_decoder']}%", flush=True)
                                except ValueError:
                                    pass
                            
                            # Parse clocks
                            graphics_clock_elem = gpu_elem.find('.//clocks/graphics_clock')
                            if graphics_clock_elem is not None and graphics_clock_elem.text:
                                try:
                                    clock_str = graphics_clock_elem.text.replace(' MHz', '').strip()
                                    detailed_info['clock_graphics'] = int(clock_str)
                                    print(f"[v0] Graphics Clock: {detailed_info['clock_graphics']} MHz", flush=True)
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            mem_clock_elem = gpu_elem.find('.//clocks/mem_clock')
                            if mem_clock_elem is not None and mem_clock_elem.text:
                                try:
                                    mem_clock_str = mem_clock_elem.text.replace(' MHz', '').strip()
                                    detailed_info['clock_memory'] = int(mem_clock_str)
                                    print(f"[v0] Memory Clock: {detailed_info['clock_memory']} MHz", flush=True)
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse memory usage
                            mem_total_elem = gpu_elem.find('.//fb_memory_usage/total')
                            if mem_total_elem is not None and mem_total_elem.text:
                                try:
                                    mem_total_str = mem_total_elem.text.replace(' MiB', '').strip()
                                    detailed_info['memory_total'] = int(mem_total_str)
                                    print(f"[v0] Memory Total: {detailed_info['memory_total']} MB", flush=True)
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            mem_used_elem = gpu_elem.find('.//fb_memory_usage/used')
                            if mem_used_elem is not None and mem_used_elem.text:
                                try:
                                    mem_used_str = mem_used_elem.text.replace(' MiB', '').strip()
                                    detailed_info['memory_used'] = int(mem_used_str)
                                    print(f"[v0] Memory Used: {detailed_info['memory_used']} MB", flush=True)
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            mem_free_elem = gpu_elem.find('.//fb_memory_usage/free')
                            if mem_free_elem is not None and mem_free_elem.text:
                                try:
                                    mem_free_str = mem_free_elem.text.replace(' MiB', '').strip()
                                    detailed_info['memory_free'] = int(mem_free_str)
                                    print(f"[v0] Memory Free: {detailed_info['memory_free']} MB", flush=True)
                                except ValueError:
                                    pass
                            
                            if (detailed_info['utilization_memory'] is None or detailed_info['utilization_memory'] == 0) and \
                               detailed_info['memory_used'] is not None and detailed_info['memory_total'] is not None and \
                               detailed_info['memory_total'] > 0:
                                mem_util = (detailed_info['memory_used'] / detailed_info['memory_total']) * 100
                                detailed_info['utilization_memory'] = round(mem_util, 1)
                                print(f"[v0] Memory Utilization (calculated): {detailed_info['utilization_memory']}%", flush=True)
                            
                            # Parse processes
                            processes_elem = gpu_elem.find('.//processes')
                            if processes_elem is not None:
                                processes = []
                                for process_elem in processes_elem.findall('process_info'):
                                    try:
                                        pid_elem = process_elem.find('pid')
                                        name_elem = process_elem.find('process_name')
                                        mem_elem = process_elem.find('used_memory')
                                        type_elem = process_elem.find('type')
                                        
                                        if pid_elem is not None and name_elem is not None and mem_elem is not None:
                                            pid = pid_elem.text.strip()
                                            name = name_elem.text.strip()
                                            
                                            # Parse memory (format: "362 MiB")
                                            mem_str = mem_elem.text.replace(' MiB', '').strip()
                                            memory_mb = int(mem_str)
                                            
                                            memory_kb = memory_mb * 1024
                                            
                                            # Get process type (C=Compute, G=Graphics)
                                            proc_type = type_elem.text.strip() if type_elem is not None else 'C'
                                            
                                            process_info = {
                                                'pid': pid,
                                                'name': name,
                                                'memory': memory_kb,  # Now in KB instead of MB
                                                'engines': {}  # Leave engines empty for NVIDIA since we don't have per-process utilization
                                            }
                                            
                                            # The process type (C/G) is informational only
                                            
                                            processes.append(process_info)
                                            print(f"[v0] Found process: {name} (PID: {pid}, Memory: {memory_mb} MB)", flush=True)
                                    except (ValueError, AttributeError) as e:
                                        print(f"[v0] Error parsing process: {e}", flush=True)
                                        continue
                                
                                detailed_info['processes'] = processes
                                print(f"[v0] Found {len(processes)} NVIDIA GPU processes", flush=True)
                            
                            if data_retrieved:
                                detailed_info['has_monitoring_tool'] = True
                                print(f"[v0] NVIDIA GPU monitoring successful", flush=True)
                            else:
                                print(f"[v0] NVIDIA GPU monitoring failed - no data retrieved", flush=True)
                        else:
                            print(f"[v0] No GPU element found in XML", flush=True)
                    
                    except ET.ParseError as e:
                        print(f"[v0] Error parsing nvidia-smi XML: {e}", flush=True)
                        import traceback
                        traceback.print_exc()
                else:
                    print(f"[v0] nvidia-smi returned error or empty output", flush=True)

            except subprocess.TimeoutExpired:
                print(f"[v0] nvidia-smi timed out - marking tool as unavailable", flush=True)
            except Exception as e:
                print(f"[v0] Error running nvidia-smi: {e}", flush=True)
                import traceback
                traceback.print_exc()
        else:
            print(f"[v0] nvidia-smi not found in PATH", flush=True)

    # AMD GPU monitoring (placeholder, requires radeontop or similar)
    elif 'amd' in vendor:
        print(f"[v0] AMD GPU detected, checking for amdgpu_top...", flush=True)
        
        amdgpu_top_path = shutil.which('amdgpu_top')
        
        if amdgpu_top_path:
            print(f"[v0] amdgpu_top found at: {amdgpu_top_path}, executing...", flush=True)
            try:
                # Execute amdgpu_top with JSON output and single snapshot
                cmd = [amdgpu_top_path, '--json', '-n', '1']
                print(f"[v0] Executing command: {' '.join(cmd)}", flush=True)
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    print(f"[v0] amdgpu_top output received, parsing JSON...", flush=True)
                    
                    try:
                        amd_data = json.loads(result.stdout)
                        print(f"[v0] JSON parsed successfully", flush=True)
                        
                        # Check if we have devices array
                        if 'devices' in amd_data and len(amd_data['devices']) > 0:
                            device = amd_data['devices'][0]  # Get first device
                            print(f"[v0] Processing AMD GPU device data...", flush=True)
                            
                            data_retrieved = False
                            
                            # Parse temperature (Edge Temperature from sensors)
                            if 'sensors' in device:
                                sensors = device['sensors']
                                if 'Edge Temperature' in sensors:
                                    edge_temp = sensors['Edge Temperature']
                                    if 'value' in edge_temp:
                                        detailed_info['temperature'] = int(edge_temp['value'])
                                        print(f"[v0] Temperature: {detailed_info['temperature']}°C", flush=True)
                                        data_retrieved = True
                                
                                # Parse power draw (GFX Power or average_socket_power)
                                if 'GFX Power' in sensors:
                                    gfx_power = sensors['GFX Power']
                                    if 'value' in gfx_power:
                                        detailed_info['power_draw'] = f"{gfx_power['value']:.2f} W"
                                        print(f"[v0] Power Draw: {detailed_info['power_draw']}", flush=True)
                                        data_retrieved = True
                                elif 'average_socket_power' in sensors:
                                    socket_power = sensors['average_socket_power']
                                    if 'value' in socket_power:
                                        detailed_info['power_draw'] = f"{socket_power['value']:.2f} W"
                                        print(f"[v0] Power Draw: {detailed_info['power_draw']}", flush=True)
                                        data_retrieved = True
                            
                            # Parse clocks (GFX_SCLK for graphics, GFX_MCLK for memory)
                            if 'Clocks' in device:
                                clocks = device['Clocks']
                                if 'GFX_SCLK' in clocks:
                                    gfx_clock = clocks['GFX_SCLK']
                                    if 'value' in gfx_clock:
                                        detailed_info['clock_graphics'] = f"{gfx_clock['value']} MHz"
                                        print(f"[v0] Graphics Clock: {detailed_info['clock_graphics']}", flush=True)
                                        data_retrieved = True
                                
                                if 'GFX_MCLK' in clocks:
                                    mem_clock = clocks['GFX_MCLK']
                                    if 'value' in mem_clock:
                                        detailed_info['clock_memory'] = f"{mem_clock['value']} MHz"
                                        print(f"[v0] Memory Clock: {detailed_info['clock_memory']} MHz", flush=True)
                                        data_retrieved = True
                            
                            # Parse GPU activity (gpu_activity.GFX)
                            if 'gpu_activity' in device:
                                gpu_activity = device['gpu_activity']
                                if 'GFX' in gpu_activity:
                                    gfx_activity = gpu_activity['GFX']
                                    if 'value' in gfx_activity:
                                        utilization = gfx_activity['value']
                                        detailed_info['utilization_gpu'] = f"{utilization:.1f}%"
                                        detailed_info['engine_render'] = f"{utilization:.1f}%"
                                        print(f"[v0] GPU Utilization: {detailed_info['utilization_gpu']}", flush=True)
                                        data_retrieved = True
                            
                            # Parse VRAM usage
                            if 'VRAM' in device:
                                vram = device['VRAM']
                                if 'Total VRAM Usage' in vram:
                                    total_usage = vram['Total VRAM Usage']
                                    if 'value' in total_usage:
                                        # Value is in MB
                                        mem_used_mb = int(total_usage['value'])
                                        detailed_info['memory_used'] = f"{mem_used_mb} MB"
                                        print(f"[v0] VRAM Used: {detailed_info['memory_used']}", flush=True)
                                        data_retrieved = True
                                
                                if 'Total VRAM' in vram:
                                    total_vram = vram['Total VRAM']
                                    if 'value' in total_vram:
                                        # Value is in MB
                                        mem_total_mb = int(total_vram['value'])
                                        detailed_info['memory_total'] = f"{mem_total_mb} MB"
                                        
                                        # Calculate free memory
                                        if detailed_info['memory_used']:
                                            mem_used_mb = int(detailed_info['memory_used'].replace(' MB', ''))
                                            mem_free_mb = mem_total_mb - mem_used_mb
                                            detailed_info['memory_free'] = f"{mem_free_mb} MB"
                                        
                                        print(f"[v0] VRAM Total: {detailed_info['memory_total']}", flush=True)
                                        data_retrieved = True
                            
                            # Calculate memory utilization percentage
                            if detailed_info['memory_used'] and detailed_info['memory_total']:
                                mem_used = int(detailed_info['memory_used'].replace(' MB', ''))
                                mem_total = int(detailed_info['memory_total'].replace(' MB', ''))
                                if mem_total > 0:
                                    mem_util = (mem_used / mem_total) * 100
                                    detailed_info['utilization_memory'] = round(mem_util, 1)
                                    print(f"[v0] Memory Utilization: {detailed_info['utilization_memory']}%", flush=True)
                            
                            # Parse GRBM (Graphics Register Bus Manager) for engine utilization
                            if 'GRBM' in device:
                                grbm = device['GRBM']
                                
                                # Graphics Pipe (similar to Render/3D)
                                if 'Graphics Pipe' in grbm:
                                    gfx_pipe = grbm['Graphics Pipe']
                                    if 'value' in gfx_pipe:
                                        detailed_info['engine_render'] = f"{gfx_pipe['value']:.1f}%"
                                
                                # Texture Pipe (similar to Video)
                                if 'Texture Pipe' in grbm:
                                    tex_pipe = grbm['Texture Pipe']
                                    if 'value' in tex_pipe:
                                        detailed_info['engine_video'] = f"{tex_pipe['value']:.1f}%"
                            
                            # Parse GRBM2 for additional engine info
                            if 'GRBM2' in device:
                                grbm2 = device['GRBM2']
                                
                                # Texture Cache (similar to Blitter)
                                if 'Texture Cache' in grbm2:
                                    tex_cache = grbm2['Texture Cache']
                                    if 'value' in tex_cache:
                                        detailed_info['engine_blitter'] = f"{tex_cache['value']:.1f}%"
                            
                            # Parse processes (fdinfo)
                            if 'fdinfo' in device:
                                fdinfo = device['fdinfo']
                                processes = []
                                
                                print(f"[v0] Parsing fdinfo with {len(fdinfo)} entries", flush=True)
                                
                                # CHANGE: Corregir parseo de fdinfo con estructura anidada
                                # fdinfo es un diccionario donde las claves son los PIDs (como strings)
                                for pid_str, proc_data in fdinfo.items():
                                    try:
                                        process_info = {
                                            'name': proc_data.get('name', 'Unknown'),
                                            'pid': pid_str,  # El PID ya es la clave
                                            'memory': {},
                                            'engines': {}
                                        }
                                        
                                        print(f"[v0] Processing fdinfo entry: PID={pid_str}, Name={process_info['name']}", flush=True)
                                        
                                        # La estructura real es: proc_data -> usage -> usage -> datos
                                        # Acceder al segundo nivel de 'usage'
                                        usage_outer = proc_data.get('usage', {})
                                        usage_data = usage_outer.get('usage', {})
                                        
                                        print(f"[v0]   Usage data keys: {list(usage_data.keys())}", flush=True)
                                        
                                        # Parse VRAM usage for this process (está dentro de usage.usage)
                                        if 'VRAM' in usage_data:
                                            vram_data = usage_data['VRAM']
                                            if isinstance(vram_data, dict) and 'value' in vram_data:
                                                vram_mb = vram_data['value']
                                                process_info['memory'] = {
                                                    'total': int(vram_mb * 1024 * 1024),  # MB to bytes
                                                    'shared': 0,
                                                    'resident': int(vram_mb * 1024 * 1024)
                                                }
                                                print(f"[v0]   VRAM: {vram_mb} MB", flush=True)
                                        
                                        # Parse GTT (Graphics Translation Table) usage (está dentro de usage.usage)
                                        if 'GTT' in usage_data:
                                            gtt_data = usage_data['GTT']
                                            if isinstance(gtt_data, dict) and 'value' in gtt_data:
                                                gtt_mb = gtt_data['value']
                                                # Add GTT to total memory if not already counted
                                                if 'total' not in process_info['memory']:
                                                    process_info['memory']['total'] = int(gtt_mb * 1024 * 1024)
                                                else:
                                                    # Add GTT to existing VRAM
                                                    process_info['memory']['total'] += int(gtt_mb * 1024 * 1024)
                                                print(f"[v0]   GTT: {gtt_mb} MB", flush=True)
                                        
                                        # Parse engine utilization for this process (están dentro de usage.usage)
                                        # GFX (Graphics/Render)
                                        if 'GFX' in usage_data:
                                            gfx_usage = usage_data['GFX']
                                            if isinstance(gfx_usage, dict) and 'value' in gfx_usage:
                                                val = gfx_usage['value']
                                                if val > 0:
                                                    process_info['engines']['Render/3D'] = f"{val:.1f}%"
                                                    print(f"[v0]     GFX: {val}%", flush=True)
                                        
                                        # Compute
                                        if 'Compute' in usage_data:
                                            comp_usage = usage_data['Compute']
                                            if isinstance(comp_usage, dict) and 'value' in comp_usage:
                                                val = comp_usage['value']
                                                if val > 0:
                                                    process_info['engines']['Compute'] = f"{val:.1f}%"
                                                    print(f"[v0]     Compute: {val}%", flush=True)
                                        
                                        # DMA (Direct Memory Access)
                                        if 'DMA' in usage_data:
                                            dma_usage = usage_data['DMA']
                                            if isinstance(dma_usage, dict) and 'value' in dma_usage:
                                                val = dma_usage['value']
                                                if val > 0:
                                                    process_info['engines']['DMA'] = f"{val:.1f}%"
                                                    print(f"[v0]     DMA: {val}%", flush=True)
                                        
                                        # Decode (Video Decode)
                                        if 'Decode' in usage_data:
                                            dec_usage = usage_data['Decode']
                                            if isinstance(dec_usage, dict) and 'value' in dec_usage:
                                                val = dec_usage['value']
                                                if val > 0:
                                                    process_info['engines']['Video'] = f"{val:.1f}%"
                                                    print(f"[v0]     Decode: {val}%", flush=True)
                                        
                                        # Encode (Video Encode)
                                        if 'Encode' in usage_data:
                                            enc_usage = usage_data['Encode']
                                            if isinstance(enc_usage, dict) and 'value' in enc_usage:
                                                val = enc_usage['value']
                                                if val > 0:
                                                    process_info['engines']['VideoEncode'] = f"{val:.1f}%"
                                                    print(f"[v0]     Encode: {val}%", flush=True)
                                        
                                        # Media (Media Engine)
                                        if 'Media' in usage_data:
                                            media_usage = usage_data['Media']
                                            if isinstance(media_usage, dict) and 'value' in media_usage:
                                                val = media_usage['value']
                                                if val > 0:
                                                    process_info['engines']['Media'] = f"{val:.1f}%"
                                                    print(f"[v0]     Media: {val}%", flush=True)
                                        
                                        # CPU (CPU usage by GPU driver)
                                        if 'CPU' in usage_data:
                                            cpu_usage = usage_data['CPU']
                                            if isinstance(cpu_usage, dict) and 'value' in cpu_usage:
                                                val = cpu_usage['value']
                                                if val > 0:
                                                    process_info['engines']['CPU'] = f"{val:.1f}%"
                                                    print(f"[v0]     CPU: {val}%", flush=True)
                                        
                                        # VCN_JPEG (JPEG Decode)
                                        if 'VCN_JPEG' in usage_data:
                                            jpeg_usage = usage_data['VCN_JPEG']
                                            if isinstance(jpeg_usage, dict) and 'value' in jpeg_usage:
                                                val = jpeg_usage['value']
                                                if val > 0:
                                                    process_info['engines']['JPEG'] = f"{val:.1f}%"
                                                    print(f"[v0]     VCN_JPEG: {val}%", flush=True)
                                        
                                        # Add the process even if it has no active engines at this moment
                                        # (may have allocated memory but is not actively using the GPU)
                                        if process_info['memory'] or process_info['engines']:
                                            processes.append(process_info)
                                            print(f"[v0] Added AMD GPU process: {process_info['name']} (PID: {process_info['pid']}) - Memory: {process_info['memory']}, Engines: {process_info['engines']}", flush=True)
                                        else:
                                            print(f"[v0] Skipped process {process_info['name']} - no memory or engine usage", flush=True)
                                    
                                    except Exception as e:
                                        print(f"[v0] Error parsing fdinfo entry for PID {pid_str}: {e}", flush=True)
                                        import traceback
                                        traceback.print_exc()
                                
                                detailed_info['processes'] = processes
                                print(f"[v0] Total AMD GPU processes: {len(processes)}", flush=True)
                            else:
                                print(f"[v0] No fdinfo section found in device data", flush=True)
                                detailed_info['processes'] = []
                            
                            if data_retrieved:
                                detailed_info['has_monitoring_tool'] = True
                                print(f"[v0] AMD GPU monitoring successful", flush=True)
                            else:
                                print(f"[v0] WARNING: No data retrieved from amdgpu_top", flush=True)
                        else:
                            print(f"[v0] WARNING: No devices found in amdgpu_top output", flush=True)
                    
                    except json.JSONDecodeError as e:
                        print(f"[v0] Error parsing amdgpu_top JSON: {e}", flush=True)
                        print(f"[v0] Raw output: {result.stdout[:500]}", flush=True)
            
            except subprocess.TimeoutExpired:
                print(f"[v0] amdgpu_top timed out", flush=True)
            except Exception as e:
                print(f"[v0] Error running amdgpu_top: {e}", flush=True)
                import traceback
                traceback.print_exc()
        else:
            print(f"[v0] amdgpu_top not found in PATH", flush=True)
            print(f"[v0] To enable AMD GPU monitoring, install amdgpu_top:", flush=True)
            print(f"[v0]   wget -O amdgpu-top_0.11.0-1_amd64.deb https://github.com/Umio-Yasuno/amdgpu_top/releases/download/v0.11.0/amdgpu-top_0.11.0-1_amd64.deb", flush=True)
            print(f"[v0]   apt install ./amdgpu-top_0.11.0-1_amd64.deb", flush=True)
        
    else:
        print(f"[v0] Unsupported GPU vendor: {vendor}", flush=True)

    print(f"[v0] ===== Exiting get_detailed_gpu_info for GPU {slot} =====", flush=True)
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
        
        # Now get driver information with lspci -k
        result_k = subprocess.run(['lspci', '-k', '-s', pci_slot], 
                                capture_output=True, text=True, timeout=5)
        if result_k.returncode == 0:
            for line in result_k.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Kernel driver in use:'):
                    pci_info['driver'] = line.split(':', 1)[1].strip()
                elif line.startswith('Kernel modules:'):
                    pci_info['kernel_module'] = line.split(':', 1)[1].strip()
                    
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
        
        # Get interface name and status
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
    """Detect and return information about GPUs in the system"""
    gpus = []
    
    try:
        result = subprocess.run(['lspci'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                # Match VGA, 3D, Display controllers
                if any(keyword in line for keyword in ['VGA compatible controller', '3D controller', 'Display controller']):

                    parts = line.split(' ', 1)
                    if len(parts) >= 2:
                        slot = parts[0].strip()  
                        remaining = parts[1]
                        
                        if ':' in remaining:
                            class_and_name = remaining.split(':', 1)
                            gpu_name = class_and_name[1].strip() if len(class_and_name) > 1 else remaining.strip()
                        else:
                            gpu_name = remaining.strip()
                        
                        # Determine vendor
                        vendor = 'Unknown'
                        if 'NVIDIA' in gpu_name or 'nVidia' in gpu_name:
                            vendor = 'NVIDIA'
                        elif 'AMD' in gpu_name or 'ATI' in gpu_name or 'Radeon' in gpu_name:
                            vendor = 'AMD'
                        elif 'Intel' in gpu_name:
                            vendor = 'Intel'
                        elif 'Matrox' in gpu_name:
                            vendor = 'Matrox'
                        
                        gpu = {
                            'slot': slot,
                            'name': gpu_name,
                            'vendor': vendor,
                            'type': identify_gpu_type(gpu_name)
                        }
                        
                        pci_info = get_pci_device_info(slot)
                        if pci_info:
                            gpu['pci_class'] = pci_info.get('class', '')
                            gpu['pci_driver'] = pci_info.get('driver', '')
                            gpu['pci_kernel_module'] = pci_info.get('kernel_module', '')
                        
                        # detailed_info = get_detailed_gpu_info(gpu) # Removed this call here
                        # gpu.update(detailed_info)             # It will be called later in api_gpu_realtime
                        
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
        result = subprocess.run(['lsblk', '-d', '-n', '-o', 'NAME,ROTA,TYPE'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 2 and parts[0] == disk_name:
                    rota = parts[1]
                    disk_info['type'] = 'HDD' if rota == '1' else 'SSD'
                    if disk_name.startswith('nvme'):
                        disk_info['type'] = 'NVMe SSD'
                    break # Found the correct disk
        
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
                        # Ensure only modules with size and not 'No Module Installed' are appended
                        if current_module and current_module.get('size') and current_module.get('size') != 'No Module Installed' and current_module.get('size') != 0:
                            hardware_data['memory_modules'].append(current_module)
                        current_module = {}
                    elif line.startswith('Size:'):
                        size_str = line.split(':', 1)[1].strip()
                        if size_str and size_str != 'No Module Installed' and size_str != 'Not Specified':
                            try:
                                # Parse size like "32768 MB" or "32 GB"
                                parts = size_str.split()
                                if len(parts) >= 2:
                                    value = float(parts[0])
                                    unit = parts[1].upper()
                                    
                                    # Convert to KB
                                    if unit == 'GB':
                                        size_kb = value * 1024 * 1024
                                    elif unit == 'MB':
                                        size_kb = value * 1024
                                    elif unit == 'KB':
                                        size_kb = value
                                    else:
                                        size_kb = value  # Assume KB if no unit
                                    
                                    current_module['size'] = size_kb
                                    print(f"[v0] Parsed memory size: {size_str} -> {size_kb} KB")
                                else:
                                    # Handle cases where unit might be missing but value is present
                                    current_module['size'] = float(size_str) if size_str else 0
                                    print(f"[v0] Parsed memory size (no unit): {size_str} -> {current_module['size']} KB")
                            except (ValueError, IndexError) as e:
                                print(f"[v0] Error parsing memory size '{size_str}': {e}")
                                current_module['size'] = 0 # Default to 0 if parsing fails
                        else:
                            current_module['size'] = 0 # Default to 0 if no size or explicitly 'No Module Installed'
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
                
                # Append the last module if it's valid
                if current_module and current_module.get('size') and current_module.get('size') != 'No Module Installed' and current_module.get('size') != 0:
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
            result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.used,temperature.gpu,power.draw,utilization.gpu,utilization.memory,clocks.graphics,clocks.memory', '--format=csv,noheader,nounits'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for i, line in enumerate(result.stdout.strip().split('\n')):
                    if line:
                        parts = line.split(',')
                        if len(parts) >= 9: # Adjusted to match the query fields
                            gpu_name = parts[0].strip()
                            mem_total = parts[1].strip()
                            mem_used = parts[2].strip()
                            temp = parts[3].strip() if parts[3].strip() != 'N/A' else None
                            power = parts[4].strip() if parts[4].strip() != 'N/A' else None
                            gpu_util = parts[5].strip() if parts[5].strip() != 'N/A' else None
                            mem_util = parts[6].strip() if parts[6].strip() != 'N/A' else None
                            graphics_clock = parts[7].strip() if parts[7].strip() != 'N/A' else None
                            memory_clock = parts[8].strip() if parts[8].strip() != 'N/A' else None
                            
                            # Try to find the corresponding PCI slot using nvidia-smi -L
                            try:
                                list_gpus_cmd = ['nvidia-smi', '-L']
                                list_gpus_result = subprocess.run(list_gpus_cmd, capture_output=True, text=True, timeout=5)
                                pci_slot = None
                                if list_gpus_result.returncode == 0:
                                    for gpu_line in list_gpus_result.stdout.strip().split('\n'):
                                        if gpu_name in gpu_line:
                                            slot_match = re.search(r'PCI Device (\S+):', gpu_line)
                                            if slot_match:
                                                pci_slot = slot_match.group(1)
                                                break
                            except:
                                pass # Ignore errors here, pci_slot will remain None
                            
                            hardware_data['graphics_cards'].append({
                                'name': gpu_name,
                                'vendor': 'NVIDIA',
                                'slot': pci_slot,
                                'memory_total': mem_total,
                                'memory_used': mem_used,
                                'temperature': int(temp) if temp else None,
                                'power_draw': power,
                                'utilization_gpu': gpu_util,
                                'utilization_memory': mem_util,
                                'clock_graphics': graphics_clock,
                                'clock_memory': memory_clock,
                            })
            
            # Always check lspci for all GPUs (integrated and discrete)
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
                            elif 'Matrox' in gpu_name:
                                vendor = 'Matrox'
                            
                            # Check if this GPU is already in the list (from nvidia-smi)
                            already_exists = False
                            for existing_gpu in hardware_data['graphics_cards']:
                                if gpu_name in existing_gpu['name'] or existing_gpu['name'] in gpu_name:
                                    already_exists = True
                                    # Update vendor if it was previously unknown
                                    if existing_gpu['vendor'] == 'Unknown':
                                        existing_gpu['vendor'] = vendor
                                    # Update slot if not already set
                                    if not existing_gpu.get('slot') and slot:
                                        existing_gpu['slot'] = slot
                                    break
                            
                            if not already_exists:
                                hardware_data['graphics_cards'].append({
                                    'name': gpu_name,
                                    'vendor': vendor,
                                    'slot': slot
                                })
                                print(f"[v0] Found GPU: {gpu_name} ({vendor}) at slot {slot}")
            
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
                                    
                                    # Placeholder for identify_fan - needs implementation
                                    # identified_name = identify_fan(sensor_name, current_adapter) 
                                    identified_name = sensor_name # Use original name for now
                                    
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
        
        # Enrich PCI devices with GPU info where applicable
        for pci_device in hardware_data['pci_devices']:
            if pci_device.get('type') == 'Graphics Card':
                for gpu in hardware_data['gpus']:
                    if pci_device.get('slot') == gpu.get('slot'):
                        pci_device['gpu_info'] = gpu # Add the detected GPU info directly
                        break
        
        return hardware_data
        
    except Exception as e:
        print(f"[v0] Error in get_hardware_info: {e}")
        import traceback
        traceback.print_exc()
        return {}


@app.route('/api/system', methods=['GET'])
def api_system():
    """Get system information including CPU, memory, and temperature"""
    try:
        cpu_usage = psutil.cpu_percent(interval=0.5)
        
        memory = psutil.virtual_memory()
        memory_used_gb = memory.used / (1024 ** 3)
        memory_total_gb = memory.total / (1024 ** 3)
        memory_usage_percent = memory.percent
        
        # Get temperature
        temp = get_cpu_temperature()
        
        # Get uptime
        uptime = get_uptime()
        
        # Get load average
        load_avg = os.getloadavg()
        
        # Get CPU cores
        cpu_cores = psutil.cpu_count(logical=False)
        
        cpu_threads = psutil.cpu_count(logical=True)
        
        # Get Proxmox version
        proxmox_version = get_proxmox_version()
        
        # Get kernel version
        kernel_version = platform.release()
        
        # Get available updates
        available_updates = get_available_updates()
        
        return jsonify({
            'cpu_usage': round(cpu_usage, 1),
            'memory_usage': round(memory_usage_percent, 1),
            'memory_total': round(memory_total_gb, 1),
            'memory_used': round(memory_used_gb, 1),
            'temperature': temp,
            'uptime': uptime,
            'load_average': list(load_avg),
            'hostname': socket.gethostname(),
            'node_id': socket.gethostname(),
            'timestamp': datetime.now().isoformat(),
            'cpu_cores': cpu_cores,
            'cpu_threads': cpu_threads,
            'proxmox_version': proxmox_version,
            'kernel_version': kernel_version,
            'available_updates': available_updates
        })
    except Exception as e:
        print(f"Error getting system info: {e}")
        return jsonify({'error': str(e)}), 500

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

@app.route('/api/vms/<int:vmid>/metrics', methods=['GET'])
def api_vm_metrics(vmid):
    """Get historical metrics (RRD data) for a specific VM/LXC"""
    try:
        timeframe = request.args.get('timeframe', 'week')  # hour, day, week, month, year
        
        # Validate timeframe
        valid_timeframes = ['hour', 'day', 'week', 'month', 'year']
        if timeframe not in valid_timeframes:
            return jsonify({'error': f'Invalid timeframe. Must be one of: {", ".join(valid_timeframes)}'}), 400
        
        # Get local node name
        local_node = socket.gethostname()
        
        # First, determine if it's a qemu VM or lxc container
        result = subprocess.run(['pvesh', 'get', f'/nodes/{local_node}/qemu/{vmid}/status/current', '--output-format', 'json'],
                              capture_output=True, text=True, timeout=10)
        
        vm_type = 'qemu'
        if result.returncode != 0:
            # Try LXC
            result = subprocess.run(['pvesh', 'get', f'/nodes/{local_node}/lxc/{vmid}/status/current', '--output-format', 'json'],
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                vm_type = 'lxc'
            else:
                return jsonify({'error': f'VM/LXC {vmid} not found'}), 404
        
        # Get RRD data
        rrd_result = subprocess.run(['pvesh', 'get', f'/nodes/{local_node}/{vm_type}/{vmid}/rrddata', 
                                    '--timeframe', timeframe, '--output-format', 'json'],
                                   capture_output=True, text=True, timeout=10)
        
        if rrd_result.returncode == 0:
            rrd_data = json.loads(rrd_result.stdout)
            return jsonify({
                'vmid': vmid,
                'type': vm_type,
                'timeframe': timeframe,
                'data': rrd_data
            })
        else:
            return jsonify({'error': f'Failed to get RRD data: {rrd_result.stderr}'}), 500
            
    except Exception as e:
        print(f"Error getting VM metrics: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs', methods=['GET'])
def api_logs():
    """Get system logs"""
    try:
        limit = request.args.get('limit', '200')
        priority = request.args.get('priority', None)  # 0-7 (0=emerg, 3=err, 4=warning, 6=info)
        service = request.args.get('service', None)
        since_days = request.args.get('since_days', None)
        
        if since_days:
            try:
                days = int(since_days)
                cmd = ['journalctl', '--since', f'{days} days ago', '--output', 'json', '--no-pager']
                print(f"[API] Filtering logs since {days} days ago (no limit)")
            except ValueError:
                print(f"[API] Invalid since_days value: {since_days}")
                cmd = ['journalctl', '-n', limit, '--output', 'json', '--no-pager']
        else:
            cmd = ['journalctl', '-n', limit, '--output', 'json', '--no-pager']
        
        # Add priority filter if specified
        if priority:
            cmd.extend(['-p', priority])
        
        # Add service filter if specified
        if service:
            cmd.extend(['-u', service])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            logs = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        log_entry = json.loads(line)
                        # Convert timestamp from microseconds to readable format
                        timestamp_us = int(log_entry.get('__REALTIME_TIMESTAMP', '0'))
                        timestamp = datetime.fromtimestamp(timestamp_us / 1000000).strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Map priority to level name
                        priority_map = {
                            '0': 'emergency', '1': 'alert', '2': 'critical', '3': 'error',
                            '4': 'warning', '5': 'notice', '6': 'info', '7': 'debug'
                        }
                        priority_num = str(log_entry.get('PRIORITY', '6'))
                        level = priority_map.get(priority_num, 'info')
                        
                        logs.append({
                            'timestamp': timestamp,
                            'level': level,
                            'service': log_entry.get('_SYSTEMD_UNIT', log_entry.get('SYSLOG_IDENTIFIER', 'system')),
                            'message': log_entry.get('MESSAGE', ''),
                            'source': 'journal',
                            'pid': log_entry.get('_PID', ''),
                            'hostname': log_entry.get('_HOSTNAME', '')
                        })
                    except (json.JSONDecodeError, ValueError) as e:
                        continue
            return jsonify({'logs': logs, 'total': len(logs)})
        else:
            return jsonify({
                'error': 'journalctl not available or failed',
                'logs': [],
                'total': 0
            })
    except Exception as e:
        print(f"Error getting logs: {e}")
        return jsonify({
            'error': f'Unable to access system logs: {str(e)}',
            'logs': [],
            'total': 0
        })

@app.route('/api/logs/download', methods=['GET'])
def api_logs_download():
    """Download system logs as a text file"""
    try:
        log_type = request.args.get('type', 'system')
        hours = int(request.args.get('hours', '48'))
        level = request.args.get('level', 'all')
        service = request.args.get('service', 'all')
        since_days = request.args.get('since_days', None)
        
        if since_days:
            days = int(since_days)

            cmd = ['journalctl', '--since', f'{days} days ago', '--no-pager']
        else:
            cmd = ['journalctl', '--since', f'{hours} hours ago', '--no-pager']
        
        if log_type == 'kernel':
            cmd.extend(['-k'])
            filename = 'kernel.log'
        elif log_type == 'auth':
            cmd.extend(['-u', 'ssh', '-u', 'sshd'])
            filename = 'auth.log'
        else:
            filename = 'system.log'
        
        # Apply level filter
        if level != 'all':
            cmd.extend(['-p', level])
        
        # Apply service filter
        if service != 'all':
            cmd.extend(['-u', service])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
                f.write(result.stdout)
                temp_path = f.name
            
            return send_file(
                temp_path,
                mimetype='text/plain',
                as_attachment=True,
                download_name=f'proxmox_{filename}'
            )
        else:
            return jsonify({'error': 'Failed to generate log file'}), 500
            
    except Exception as e:
        print(f"Error downloading logs: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/notifications', methods=['GET'])
def api_notifications():
    """Get Proxmox notification history"""
    try:
        notifications = []
        
        # 1. Get notifications from journalctl (Proxmox notification service)
        try:
            cmd = [
                'journalctl',
                '-u', 'pve-ha-lrm',
                '-u', 'pve-ha-crm',
                '-u', 'pvedaemon',
                '-u', 'pveproxy',
                '-u', 'pvestatd',
                '--grep', 'notification|email|webhook|alert|notify',
                '-n', '100',
                '--output', 'json',
                '--no-pager'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        try:
                            log_entry = json.loads(line)
                            timestamp_us = int(log_entry.get('__REALTIME_TIMESTAMP', '0'))
                            timestamp = datetime.fromtimestamp(timestamp_us / 1000000).strftime('%Y-%m-%d %H:%M:%S')
                            
                            message = log_entry.get('MESSAGE', '')
                            
                            # Determine notification type from message
                            notif_type = 'info'
                            if 'email' in message.lower():
                                notif_type = 'email'
                            elif 'webhook' in message.lower():
                                notif_type = 'webhook'
                            elif 'alert' in message.lower() or 'warning' in message.lower():
                                notif_type = 'alert'
                            elif 'error' in message.lower() or 'fail' in message.lower():
                                notif_type = 'error'
                            
                            notifications.append({
                                'timestamp': timestamp,
                                'type': notif_type,
                                'service': log_entry.get('_SYSTEMD_UNIT', 'proxmox'),
                                'message': message,
                                'source': 'journal'
                            })
                        except (json.JSONDecodeError, ValueError):
                            continue
        except Exception as e:
            print(f"Error reading notification logs: {e}")
        
        # 2. Try to read Proxmox notification configuration
        try:
            notif_config_path = '/etc/pve/notifications.cfg'
            if os.path.exists(notif_config_path):
                with open(notif_config_path, 'r') as f:
                    config_content = f.read()
                    # Parse notification targets (emails, webhooks, etc.)
                    for line in config_content.split('\n'):
                        if line.strip() and not line.startswith('#'):
                            notifications.append({
                                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                'type': 'config',
                                'service': 'notification-config',
                                'message': f'Notification target configured: {line.strip()}',
                                'source': 'config'
                            })
        except Exception as e:
            print(f"Error reading notification config: {e}")
        
        # 3. Get backup notifications from task log
        try:
            cmd = ['pvesh', 'get', '/cluster/tasks', '--output-format', 'json']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                tasks = json.loads(result.stdout)
                for task in tasks:
                    if task.get('type') in ['vzdump', 'backup']:
                        status = task.get('status', 'unknown')
                        notif_type = 'success' if status == 'OK' else 'error' if status == 'stopped' else 'info'
                        
                        notifications.append({
                            'timestamp': datetime.fromtimestamp(task.get('starttime', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                            'type': notif_type,
                            'service': 'backup',
                            'message': f"Backup task {task.get('upid', 'unknown')}: {status}",
                            'source': 'task-log'
                        })
        except Exception as e:
            print(f"Error reading task notifications: {e}")
        
        # Sort by timestamp (newest first)
        notifications.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return jsonify({
            'notifications': notifications[:100],  # Limit to 100 most recent
            'total': len(notifications)
        })
        
    except Exception as e:
        print(f"Error getting notifications: {e}")
        return jsonify({
            'error': str(e),
            'notifications': [],
            'total': 0
        })

@app.route('/api/notifications/download', methods=['GET'])
def api_notifications_download():
    """Download complete log for a specific notification"""
    try:
        timestamp = request.args.get('timestamp', '')
        
        if not timestamp:
            return jsonify({'error': 'Timestamp parameter required'}), 400
        
        from datetime import datetime, timedelta
        
        try:
            # Parse timestamp format: "2025-10-11 14:27:35"
            dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            # Use a very small time window (2 minutes) to get just this notification
            since_time = (dt - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
            until_time = (dt + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            # If parsing fails, use a default range
            since_time = "2 minutes ago"
            until_time = "now"
        
        # Get logs around the specific timestamp
        cmd = [
            'journalctl',
            '--since', since_time,
            '--until', until_time,
            '-n', '50',  # Limit to 50 lines around the notification
            '--no-pager'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
                f.write(f"Notification Log - {timestamp}\n")
                f.write(f"Time Window: {since_time} to {until_time}\n")
                f.write("=" * 80 + "\n\n")
                f.write(result.stdout)
                temp_path = f.name
            
            return send_file(
                temp_path,
                mimetype='text/plain',
                as_attachment=True,
                download_name=f'notification_{timestamp.replace(":", "_").replace(" ", "_")}.log'
            )
        else:
            return jsonify({'error': 'Failed to generate log file'}), 500
            
    except Exception as e:
        print(f"Error downloading logs: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/backups', methods=['GET'])
def api_backups():
    """Get list of all backup files from Proxmox storage"""
    try:
        backups = []
        
        # Get list of storage locations
        try:
            result = subprocess.run(['pvesh', 'get', '/storage', '--output-format', 'json'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                storages = json.loads(result.stdout)
                
                # For each storage, get backup files
                for storage in storages:
                    storage_id = storage.get('storage')
                    storage_type = storage.get('type')
                    
                    # Only check storages that can contain backups
                    if storage_type in ['dir', 'nfs', 'cifs', 'pbs']:
                        try:
                            # Get content of storage
                            content_result = subprocess.run(
                                ['pvesh', 'get', f'/nodes/localhost/storage/{storage_id}/content', '--output-format', 'json'],
                                capture_output=True, text=True, timeout=10)
                            
                            if content_result.returncode == 0:
                                contents = json.loads(content_result.stdout)
                                
                                for item in contents:
                                    if item.get('content') == 'backup':
                                        # Parse backup information
                                        volid = item.get('volid', '')
                                        size = item.get('size', 0)
                                        ctime = item.get('ctime', 0)
                                        
                                        # Extract VMID from volid (format: storage:backup/vzdump-qemu-100-...)
                                        vmid = None
                                        backup_type = None
                                        if 'vzdump-qemu-' in volid:
                                            backup_type = 'qemu'
                                            try:
                                                vmid = volid.split('vzdump-qemu-')[1].split('-')[0]
                                            except:
                                                pass
                                        elif 'vzdump-lxc-' in volid:
                                            backup_type = 'lxc'
                                            try:
                                                vmid = volid.split('vzdump-lxc-')[1].split('-')[0]
                                            except:
                                                pass
                                        
                                        backups.append({
                                            'volid': volid,
                                            'storage': storage_id,
                                            'vmid': vmid,
                                            'type': backup_type,
                                            'size': size,
                                            'size_human': format_bytes(size),
                                            'created': datetime.fromtimestamp(ctime).strftime('%Y-%m-%d %H:%M:%S'),
                                            'timestamp': ctime
                                        })
                        except Exception as e:
                            print(f"Error getting content for storage {storage_id}: {e}")
                            continue
        except Exception as e:
            print(f"Error getting storage list: {e}")
        
        # Sort by creation time (newest first)
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return jsonify({
            'backups': backups,
            'total': len(backups)
        })
        
    except Exception as e:
        print(f"Error getting backups: {e}")
        return jsonify({
            'error': str(e),
            'backups': [],
            'total': 0
        })

@app.route('/api/events', methods=['GET'])
def api_events():
    """Get recent Proxmox events and tasks"""
    try:
        limit = request.args.get('limit', '50')
        events = []
        
        try:
            result = subprocess.run(['pvesh', 'get', '/cluster/tasks', '--output-format', 'json'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                tasks = json.loads(result.stdout)
                
                for task in tasks[:int(limit)]:
                    upid = task.get('upid', '')
                    task_type = task.get('type', 'unknown')
                    status = task.get('status', 'unknown')
                    node = task.get('node', 'unknown')
                    user = task.get('user', 'unknown')
                    vmid = task.get('id', '')
                    starttime = task.get('starttime', 0)
                    endtime = task.get('endtime', 0)
                    
                    # Calculate duration
                    duration = ''
                    if endtime and starttime:
                        duration_sec = endtime - starttime
                        if duration_sec < 60:
                            duration = f"{duration_sec}s"
                        elif duration_sec < 3600:
                            duration = f"{duration_sec // 60}m {duration_sec % 60}s"
                        else:
                            hours = duration_sec // 3600
                            minutes = (duration_sec % 3600) // 60
                            duration = f"{hours}h {minutes}m"
                    
                    # Determine level based on status
                    level = 'info'
                    if status == 'OK':
                        level = 'info'
                    elif status in ['stopped', 'error']:
                        level = 'error'
                    elif status == 'running':
                        level = 'warning'
                    
                    events.append({
                        'upid': upid,
                        'type': task_type,
                        'status': status,
                        'level': level,
                        'node': node,
                        'user': user,
                        'vmid': str(vmid) if vmid else '',
                        'starttime': datetime.fromtimestamp(starttime).strftime('%Y-%m-%d %H:%M:%S') if starttime else '',
                        'endtime': datetime.fromtimestamp(endtime).strftime('%Y-%m-%d %H:%M:%S') if endtime else 'Running',
                        'duration': duration
                    })
        except Exception as e:
            print(f"Error getting events: {e}")
        
        return jsonify({
            'events': events,
            'total': len(events)
        })
        
    except Exception as e:
        print(f"Error getting events: {e}")
        return jsonify({
            'error': str(e),
            'events': [],
            'total': 0
        })

@app.route('/api/task-log/<path:upid>')
def get_task_log(upid):
    """Get complete task log from Proxmox using UPID"""
    try:
        print(f"[v0] Getting task log for UPID: {upid}")
        
        # Proxmox stores files without trailing :: but API may include them
        upid_clean = upid.rstrip(':')
        print(f"[v0] Cleaned UPID: {upid_clean}")
        
        # Parse UPID to extract node name and calculate index
        # UPID format: UPID:node:pid:pstart:starttime:type:id:user:
        parts = upid_clean.split(':')
        if len(parts) < 5:
            print(f"[v0] Invalid UPID format: {upid_clean}")
            return jsonify({'error': 'Invalid UPID format'}), 400
        
        node = parts[1]
        starttime = parts[4]
        
        # Calculate index (last character of starttime in hex, lowercase)
        index = starttime[-1].lower()
        
        print(f"[v0] Extracted node: {node}, starttime: {starttime}, index: {index}")
        
        # Try with cleaned UPID (no trailing colons)
        log_file_path = f"/var/log/pve/tasks/{index}/{upid_clean}"
        print(f"[v0] Trying log file: {log_file_path}")
        
        if os.path.exists(log_file_path):
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_text = f.read()
            print(f"[v0] Successfully read {len(log_text)} bytes from log file")
            return log_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
        
        # Try with single trailing colon
        log_file_path_single = f"/var/log/pve/tasks/{index}/{upid_clean}:"
        print(f"[v0] Trying alternative path with single colon: {log_file_path_single}")
        
        if os.path.exists(log_file_path_single):
            with open(log_file_path_single, 'r', encoding='utf-8', errors='ignore') as f:
                log_text = f.read()
            print(f"[v0] Successfully read {len(log_text)} bytes from alternative log file")
            return log_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
        
        # Try with uppercase index
        log_file_path_upper = f"/var/log/pve/tasks/{index.upper()}/{upid_clean}"
        print(f"[v0] Trying uppercase index path: {log_file_path_upper}")
        
        if os.path.exists(log_file_path_upper):
            with open(log_file_path_upper, 'r', encoding='utf-8', errors='ignore') as f:
                log_text = f.read()
            print(f"[v0] Successfully read {len(log_text)} bytes from uppercase index log file")
            return log_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
        
        # List available files in the directory for debugging
        tasks_dir = f"/var/log/pve/tasks/{index}"
        if os.path.exists(tasks_dir):
            available_files = os.listdir(tasks_dir)
            print(f"[v0] Available files in {tasks_dir}: {available_files[:10]}")  # Show first 10
            
            upid_prefix = ':'.join(parts[:5])  # Get first 5 parts of UPID
            for filename in available_files:
                if filename.startswith(upid_prefix):
                    matched_file = f"{tasks_dir}/{filename}"
                    print(f"[v0] Found matching file by prefix: {matched_file}")
                    with open(matched_file, 'r', encoding='utf-8', errors='ignore') as f:
                        log_text = f.read()
                    print(f"[v0] Successfully read {len(log_text)} bytes from matched file")
                    return log_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
        else:
            print(f"[v0] Tasks directory does not exist: {tasks_dir}")
        
        print(f"[v0] Log file not found after trying all variations")
        return jsonify({'error': 'Log file not found', 'tried_paths': [log_file_path, log_file_path_single, log_file_path_upper]}), 404
            
    except Exception as e:
        print(f"[v0] Error fetching task log for UPID {upid}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

@app.route('/api/prometheus', methods=['GET'])
def api_prometheus():
    """Export metrics in Prometheus format"""
    try:
        metrics = []
        timestamp = int(datetime.now().timestamp() * 1000)
        node = socket.gethostname()
        
        # Get system data
        cpu_usage = psutil.cpu_percent(interval=0.5)
        memory = psutil.virtual_memory()
        load_avg = os.getloadavg()
        uptime_seconds = time.time() - psutil.boot_time()
        
        # System metrics
        metrics.append(f'# HELP proxmox_cpu_usage CPU usage percentage')
        metrics.append(f'# TYPE proxmox_cpu_usage gauge')
        metrics.append(f'proxmox_cpu_usage{{node="{node}"}} {cpu_usage} {timestamp}')
        
        metrics.append(f'# HELP proxmox_memory_total_bytes Total memory in bytes')
        metrics.append(f'# TYPE proxmox_memory_total_bytes gauge')
        metrics.append(f'proxmox_memory_total_bytes{{node="{node}"}} {memory.total} {timestamp}')
        
        metrics.append(f'# HELP proxmox_memory_used_bytes Used memory in bytes')
        metrics.append(f'# TYPE proxmox_memory_used_bytes gauge')
        metrics.append(f'proxmox_memory_used_bytes{{node="{node}"}} {memory.used} {timestamp}')
        
        metrics.append(f'# HELP proxmox_memory_usage_percent Memory usage percentage')
        metrics.append(f'# TYPE proxmox_memory_usage_percent gauge')
        metrics.append(f'proxmox_memory_usage_percent{{node="{node}"}} {memory.percent} {timestamp}')
        
        metrics.append(f'# HELP proxmox_load_average System load average')
        metrics.append(f'# TYPE proxmox_load_average gauge')
        metrics.append(f'proxmox_load_average{{node="{node}",period="1m"}} {load_avg[0]} {timestamp}')
        metrics.append(f'proxmox_load_average{{node="{node}",period="5m"}} {load_avg[1]} {timestamp}')
        metrics.append(f'proxmox_load_average{{node="{node}",period="15m"}} {load_avg[2]} {timestamp}')
        
        metrics.append(f'# HELP proxmox_uptime_seconds System uptime in seconds')
        metrics.append(f'# TYPE proxmox_uptime_seconds counter')
        metrics.append(f'proxmox_uptime_seconds{{node="{node}"}} {uptime_seconds} {timestamp}')
        
        # Temperature
        temp = get_cpu_temperature()
        if temp:
            metrics.append(f'# HELP proxmox_cpu_temperature_celsius CPU temperature in Celsius')
            metrics.append(f'# TYPE proxmox_cpu_temperature_celsius gauge')
            metrics.append(f'proxmox_cpu_temperature_celsius{{node="{node}"}} {temp} {timestamp}')
        
        # Storage metrics
        storage_info = get_storage_info()
        for disk in storage_info.get('disks', []):
            disk_name = disk.get('name', 'unknown')
            metrics.append(f'# HELP proxmox_disk_total_bytes Total disk space in bytes')
            metrics.append(f'# TYPE proxmox_disk_total_bytes gauge')
            metrics.append(f'proxmox_disk_total_bytes{{node="{node}",disk="{disk_name}"}} {disk.get("total", 0)} {timestamp}')
            
            metrics.append(f'# HELP proxmox_disk_used_bytes Used disk space in bytes')
            metrics.append(f'# TYPE proxmox_disk_used_bytes gauge')
            metrics.append(f'proxmox_disk_used_bytes{{node="{node}",disk="{disk_name}"}} {disk.get("used", 0)} {timestamp}')
            
            metrics.append(f'# HELP proxmox_disk_usage_percent Disk usage percentage')
            metrics.append(f'# TYPE proxmox_disk_usage_percent gauge')
            metrics.append(f'proxmox_disk_usage_percent{{node="{node}",disk="{disk_name}"}} {disk.get("percent", 0)} {timestamp}')
        
        # Network metrics
        network_info = get_network_info()
        if 'traffic' in network_info:
            metrics.append(f'# HELP proxmox_network_bytes_sent_total Total bytes sent')
            metrics.append(f'# TYPE proxmox_network_bytes_sent_total counter')
            metrics.append(f'proxmox_network_bytes_sent_total{{node="{node}"}} {network_info["traffic"].get("bytes_sent", 0)} {timestamp}')
            
            metrics.append(f'# HELP proxmox_network_bytes_received_total Total bytes received')
            metrics.append(f'# TYPE proxmox_network_bytes_received_total counter')
            metrics.append(f'proxmox_network_bytes_received_total{{node="{node}"}} {network_info["traffic"].get("bytes_recv", 0)} {timestamp}')
        
        # Per-interface network metrics
        for interface in network_info.get('interfaces', []):
            iface_name = interface.get('name', 'unknown')
            if interface.get('status') == 'up':
                metrics.append(f'# HELP proxmox_interface_bytes_sent_total Bytes sent per interface')
                metrics.append(f'# TYPE proxmox_interface_bytes_sent_total counter')
                metrics.append(f'proxmox_interface_bytes_sent_total{{node="{node}",interface="{iface_name}"}} {interface.get("bytes_sent", 0)} {timestamp}')
                
                metrics.append(f'# HELP proxmox_interface_bytes_received_total Bytes received per interface')
                metrics.append(f'# TYPE proxmox_interface_bytes_received_total counter')
                metrics.append(f'proxmox_interface_bytes_received_total{{node="{node}",interface="{iface_name}"}} {interface.get("bytes_recv", 0)} {timestamp}')
        
        # VM metrics
        vms_data = get_proxmox_vms()
        if isinstance(vms_data, list):
            vms = vms_data
            total_vms = len(vms)
            running_vms = sum(1 for vm in vms if vm.get('status') == 'running')
            stopped_vms = sum(1 for vm in vms if vm.get('status') == 'stopped')
            
            metrics.append(f'# HELP proxmox_vms_total Total number of VMs and LXCs')
            metrics.append(f'# TYPE proxmox_vms_total gauge')
            metrics.append(f'proxmox_vms_total{{node="{node}"}} {total_vms} {timestamp}')
            
            metrics.append(f'# HELP proxmox_vms_running Number of running VMs and LXCs')
            metrics.append(f'# TYPE proxmox_vms_running gauge')
            metrics.append(f'proxmox_vms_running{{node="{node}"}} {running_vms} {timestamp}')
            
            metrics.append(f'# HELP proxmox_vms_stopped Number of stopped VMs and LXCs')
            metrics.append(f'# TYPE proxmox_vms_stopped gauge')
            metrics.append(f'proxmox_vms_stopped{{node="{node}"}} {stopped_vms} {timestamp}')
            
            # Per-VM metrics
            for vm in vms:
                vmid = vm.get('vmid', 'unknown')
                vm_name = vm.get('name', f'vm-{vmid}')
                vm_status = 1 if vm.get('status') == 'running' else 0
                
                metrics.append(f'# HELP proxmox_vm_status VM status (1=running, 0=stopped)')
                metrics.append(f'# TYPE proxmox_vm_status gauge')
                metrics.append(f'proxmox_vm_status{{node="{node}",vmid="{vmid}",name="{vm_name}"}} {vm_status} {timestamp}')
                
                if vm.get('status') == 'running':
                    metrics.append(f'# HELP proxmox_vm_cpu_usage VM CPU usage')
                    metrics.append(f'# TYPE proxmox_vm_cpu_usage gauge')
                    metrics.append(f'proxmox_vm_cpu_usage{{node="{node}",vmid="{vmid}",name="{vm_name}"}} {vm.get("cpu", 0)} {timestamp}')
                    
                    metrics.append(f'# HELP proxmox_vm_memory_used_bytes VM memory used in bytes')
                    metrics.append(f'# TYPE proxmox_vm_memory_used_bytes gauge')
                    metrics.append(f'proxmox_vm_memory_used_bytes{{node="{node}",vmid="{vmid}",name="{vm_name}"}} {vm.get("mem", 0)} {timestamp}')
                    
                    metrics.append(f'# HELP proxmox_vm_memory_max_bytes VM memory max in bytes')
                    metrics.append(f'# TYPE proxmox_vm_memory_max_bytes gauge')
                    metrics.append(f'proxmox_vm_memory_max_bytes{{node="{node}",vmid="{vmid}",name="{vm_name}"}} {vm.get("maxmem", 0)} {timestamp}')
        
        # Hardware metrics (temperature, fans, UPS, GPU)
        try:
            hardware_info = get_hardware_info()
            
            # Disk temperatures
            for device in hardware_info.get('storage_devices', []):
                if device.get('temperature'):
                    disk_name = device.get('name', 'unknown')
                    metrics.append(f'# HELP proxmox_disk_temperature_celsius Disk temperature in Celsius')
                    metrics.append(f'# TYPE proxmox_disk_temperature_celsius gauge')
                    metrics.append(f'proxmox_disk_temperature_celsius{{node="{node}",disk="{disk_name}"}} {device["temperature"]} {timestamp}')
            
            # Fan speeds
            all_fans = hardware_info.get('sensors', {}).get('fans', [])
            all_fans.extend(hardware_info.get('ipmi_fans', []))
            for fan in all_fans:
                fan_name = fan.get('name', 'unknown').replace(' ', '_')
                if fan.get('speed') is not None:
                    metrics.append(f'# HELP proxmox_fan_speed_rpm Fan speed in RPM')
                    metrics.append(f'# TYPE proxmox_fan_speed_rpm gauge')
                    metrics.append(f'proxmox_fan_speed_rpm{{node="{node}",fan="{fan_name}"}} {fan["speed"]} {timestamp}')
            
            # GPU metrics
            for gpu in hardware_info.get('gpus', []): # Changed from pci_devices to gpus
                gpu_name = gpu.get('name', 'unknown').replace(' ', '_')
                gpu_vendor = gpu.get('vendor', 'unknown')
                gpu_slot = gpu.get('slot', 'unknown') # Use slot for matching
                
                # GPU Temperature
                if gpu.get('temperature') is not None:
                    metrics.append(f'# HELP proxmox_gpu_temperature_celsius GPU temperature in Celsius')
                    metrics.append(f'# TYPE proxmox_gpu_temperature_celsius gauge')
                    metrics.append(f'proxmox_gpu_temperature_celsius{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {gpu["temperature"]} {timestamp}')
                
                # GPU Utilization
                if gpu.get('utilization_gpu') is not None:
                    metrics.append(f'# HELP proxmox_gpu_utilization_percent GPU utilization percentage')
                    metrics.append(f'# TYPE proxmox_gpu_utilization_percent gauge')
                    metrics.append(f'proxmox_gpu_utilization_percent{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {gpu["utilization_gpu"]} {timestamp}')
                
                # GPU Memory
                if gpu.get('memory_used') and gpu.get('memory_total'):
                    try:
                        # Extract numeric values from strings like "1024 MiB"
                        mem_used = float(gpu['memory_used'].split()[0])
                        mem_total = float(gpu['memory_total'].split()[0])
                        mem_used_bytes = mem_used * 1024 * 1024  # Convert MiB to bytes
                        mem_total_bytes = mem_total * 1024 * 1024
                        
                        metrics.append(f'# HELP proxmox_gpu_memory_used_bytes GPU memory used in bytes')
                        metrics.append(f'# TYPE proxmox_gpu_memory_used_bytes gauge')
                        metrics.append(f'proxmox_gpu_memory_used_bytes{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {mem_used_bytes} {timestamp}')
                        
                        metrics.append(f'# HELP proxmox_gpu_memory_total_bytes GPU memory total in bytes')
                        metrics.append(f'# TYPE proxmox_gpu_memory_total_bytes gauge')
                        metrics.append(f'proxmox_gpu_memory_total_bytes{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {mem_total_bytes} {timestamp}')
                    except (ValueError, IndexError):
                        pass
                
                # GPU Power Draw (NVIDIA only)
                if gpu.get('power_draw'):
                    try:
                        # Extract numeric value from string like "75.5 W"
                        power_draw = float(gpu['power_draw'].split()[0])
                        metrics.append(f'# HELP proxmox_gpu_power_draw_watts GPU power draw in watts')
                        metrics.append(f'# TYPE proxmox_gpu_power_draw_watts gauge')
                        metrics.append(f'proxmox_gpu_power_draw_watts{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {power_draw} {timestamp}')
                    except (ValueError, IndexError):
                        pass
                
                # GPU Clock Speeds (NVIDIA only)
                if gpu.get('clock_graphics'):
                    try:
                        # Extract numeric value from string like "1500 MHz"
                        clock_speed = float(gpu['clock_graphics'].split()[0])
                        metrics.append(f'# HELP proxmox_gpu_clock_speed_mhz GPU clock speed in MHz')
                        metrics.append(f'# TYPE proxmox_gpu_clock_speed_mhz gauge')
                        metrics.append(f'proxmox_gpu_clock_speed_mhz{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {clock_speed} {timestamp}')
                    except (ValueError, IndexError):
                        pass
                
                if gpu.get('clock_memory'):
                    try:
                        # Extract numeric value from string like "5001 MHz"
                        mem_clock = float(gpu['clock_memory'].split()[0])
                        metrics.append(f'# HELP proxmox_gpu_memory_clock_mhz GPU memory clock speed in MHz')
                        metrics.append(f'# TYPE proxmox_gpu_memory_clock_mhz gauge')
                        metrics.append(f'proxmox_gpu_memory_clock_mhz{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {mem_clock} {timestamp}')
                    except (ValueError, IndexError):
                        pass
            
            # UPS metrics
            ups = hardware_info.get('ups')
            if ups:
                ups_name = ups.get('name', 'ups').replace(' ', '_')
                
                if ups.get('battery_charge') is not None:
                    metrics.append(f'# HELP proxmox_ups_battery_charge_percent UPS battery charge percentage')
                    metrics.append(f'# TYPE proxmox_ups_battery_charge_percent gauge')
                    metrics.append(f'proxmox_ups_battery_charge_percent{{node="{node}",ups="{ups_name}"}} {ups["battery_charge_raw"]} {timestamp}')
                
                if ups.get('load') is not None:
                    metrics.append(f'# HELP proxmox_ups_load_percent UPS load percentage')
                    metrics.append(f'# TYPE proxmox_ups_load_percent gauge')
                    metrics.append(f'proxmox_ups_load_percent{{node="{node}",ups="{ups_name}"}} {ups["load_percent_raw"]} {timestamp}')
                
                if ups.get('time_left_seconds') is not None: # Use seconds for counter
                    metrics.append(f'# HELP proxmox_ups_runtime_seconds UPS runtime in seconds')
                    metrics.append(f'# TYPE proxmox_ups_runtime_seconds gauge') # Use gauge if it's current remaining time
                    metrics.append(f'proxmox_ups_runtime_seconds{{node="{node}",ups="{ups_name}"}} {ups["time_left_seconds"]} {timestamp}')
                
                if ups.get('input_voltage') is not None:
                    metrics.append(f'# HELP proxmox_ups_input_voltage_volts UPS input voltage in volts')
                    metrics.append(f'# TYPE proxmox_ups_input_voltage_volts gauge')
                    metrics.append(f'proxmox_ups_input_voltage_volts{{node="{node}",ups="{ups_name}"}} {ups["input_voltage"]} {timestamp}')
        except Exception as e:
            print(f"[v0] Error getting hardware metrics for Prometheus: {e}")
        
        # Return metrics in Prometheus format
        return '\n'.join(metrics) + '\n', 200, {'Content-Type': 'text/plain; version=0.0.4; charset=utf-8'}
        
    except Exception as e:
        print(f"Error generating Prometheus metrics: {e}")
        import traceback
        traceback.print_exc()
        return f'# Error generating metrics: {str(e)}\n', 500, {'Content-Type': 'text/plain; charset=utf-8'}

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
            '/api/vms/<vmid>/metrics', # Added endpoint for RRD data
            '/api/logs',
            '/api/health',
            '/api/hardware',
            '/api/gpu/<slot>/realtime', # Added endpoint for GPU monitoring
            '/api/backups', # Added backup endpoint
            '/api/events', # Added events endpoint
            '/api/notifications', # Added notifications endpoint
            '/api/task-log/<upid>', # Added task log endpoint
            '/api/prometheus' # Added prometheus endpoint
        ]
    })

@app.route('/api/hardware', methods=['GET'])
def api_hardware():
    """Get hardware information"""
    try:
        hardware_info = get_hardware_info()
        
        all_fans = hardware_info.get('sensors', {}).get('fans', [])
        ipmi_fans = hardware_info.get('ipmi_fans', [])
        all_fans.extend(ipmi_fans)
        
        # Format data for frontend
        formatted_data = {
            'cpu': hardware_info.get('cpu', {}),
            'motherboard': hardware_info.get('motherboard', {}), # Corrected: use hardware_info
            'bios': hardware_info.get('motherboard', {}).get('bios', {}), # Extract BIOS info
            'memory_modules': hardware_info.get('memory_modules', []),
            'storage_devices': hardware_info.get('storage_devices', []), # Fixed: use hardware_info
            'pci_devices': hardware_info.get('pci_devices', []),
            'temperatures': hardware_info.get('sensors', {}).get('temperatures', []),
            'fans': all_fans, # Return combined fans (sensors + IPMI)
            'power_supplies': hardware_info.get('ipmi_power', {}).get('power_supplies', []),
            'power_meter': hardware_info.get('power_meter'),
            'ups': hardware_info.get('ups') if hardware_info.get('ups') else None,
            'gpus': hardware_info.get('gpus', [])
        }
        
        print(f"[v0] /api/hardware returning data")
        print(f"[v0] - CPU: {formatted_data['cpu'].get('model', 'Unknown')}")
        print(f"[v0] - Temperatures: {len(formatted_data['temperatures'])} sensors")
        print(f"[v0] - Fans: {len(formatted_data['fans'])} fans") # Includes IPMI fans
        print(f"[v0] - Power supplies: {len(formatted_data['power_supplies'])} PSUs")
        print(f"[v0] - Power meter: {'Yes' if formatted_data['power_meter'] else 'No'}")
        print(f"[v0] - UPS: {'Yes' if formatted_data['ups'] else 'No'}")
        print(f"[v0] - GPUs: {len(formatted_data['gpus'])} found")
        
        return jsonify(formatted_data)
    except Exception as e:
        print(f"[v0] Error in api_hardware: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/gpu/<slot>/realtime', methods=['GET'])
def api_gpu_realtime(slot):
    """Get real-time GPU monitoring data for a specific GPU"""
    try:
        print(f"[v0] /api/gpu/{slot}/realtime - Getting GPU info...")
        
        gpus = get_gpu_info()
        
        gpu = None
        for g in gpus:
            # Match by slot or if the slot is a substring of the GPU's slot (e.g., '00:01.0' matching '00:01')
            if g.get('slot') == slot or slot in g.get('slot', ''):
                gpu = g
                break
        
        if not gpu:
            print(f"[v0] GPU with slot matching '{slot}' not found")
            return jsonify({'error': 'GPU not found'}), 404
        
        print(f"[v0] Getting detailed monitoring data for GPU at slot {gpu.get('slot')}...")
        detailed_info = get_detailed_gpu_info(gpu)
        gpu.update(detailed_info)
        
        # Extract only the monitoring-related fields
        realtime_data = {
            'has_monitoring_tool': gpu.get('has_monitoring_tool', False),
            'temperature': gpu.get('temperature'),
            'fan_speed': gpu.get('fan_speed'),
            'fan_unit': gpu.get('fan_unit'),
            'utilization_gpu': gpu.get('utilization_gpu'),
            'utilization_memory': gpu.get('utilization_memory'),
            'memory_used': gpu.get('memory_used'),
            'memory_total': gpu.get('memory_total'),
            'memory_free': gpu.get('memory_free'),
            'power_draw': gpu.get('power_draw'),
            'power_limit': gpu.get('power_limit'),
            'clock_graphics': gpu.get('clock_graphics'),
            'clock_memory': gpu.get('clock_memory'),
            'processes': gpu.get('processes', []),
            # Intel/AMD specific engine utilization
            'engine_render': gpu.get('engine_render'),
            'engine_blitter': gpu.get('engine_blitter'),
            'engine_video': gpu.get('engine_video'),
            'engine_video_enhance': gpu.get('engine_video_enhance'),
            # Added for NVIDIA/AMD specific engine info if available
            'engine_encoder': gpu.get('engine_encoder'),
            'engine_decoder': gpu.get('engine_decoder'),
            'driver_version': gpu.get('driver_version') # Added driver_version
        }
        
        print(f"[v0] /api/gpu/{slot}/realtime returning data")
        print(f"[v0] - Vendor: {gpu.get('vendor')}")
        print(f"[v0] - has_monitoring_tool: {realtime_data['has_monitoring_tool']}")
        print(f"[v0] - utilization_gpu: {realtime_data['utilization_gpu']}")
        print(f"[v0] - temperature: {realtime_data['temperature']}")
        print(f"[v0] - processes: {len(realtime_data['processes'])} found")
        print(f"[v0] - engines: render={realtime_data['engine_render']}, blitter={realtime_data['engine_blitter']}, video={realtime_data['engine_video']}, video_enhance={realtime_data['engine_video_enhance']}")
        
        return jsonify(realtime_data)
    except Exception as e:
        print(f"[v0] Error getting real-time GPU data: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/vms/<int:vmid>', methods=['GET'])
def api_vm_details(vmid):
    """Get detailed information for a specific VM/LXC"""
    try:
        result = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'], 
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
                        capture_output=True, text=True, timeout=10)
                    
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
                capture_output=True, text=True, timeout=10)
            
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
                capture_output=True, text=True, timeout=30)
            
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
            return jsonify({'error': 'Failed to get VM details'}), 500
    except Exception as e:
        print(f"Error controlling VM: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # API endpoints available at: /api/system, /api/system-info, /api/storage, /api/proxmox-storage, /api/network, /api/vms, /api/logs, /api/health, /api/hardware, /api/prometheus
    
    import sys
    import logging
    
    # Silence werkzeug logger
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    # Silence Flask CLI banner (removes "Serving Flask app", "Debug mode", "WARNING" messages)
    cli = sys.modules['flask.cli']
    cli.show_server_banner = lambda *x: None
    
    # Print only essential information
    print("API endpoints available at: /api/system, /api/system-info, /api/storage, /api/proxmox-storage, /api/network, /api/vms, /api/logs, /api/health, /api/hardware, /api/prometheus")
    
    app.run(host='0.0.0.0', port=8008, debug=False)
