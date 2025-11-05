"""
ProxMenux Health Monitor Module
Provides comprehensive, lightweight health checks for Proxmox systems.
Optimized for minimal system impact with intelligent thresholds and hysteresis.

Author: MacRimi
Version: 1.0 (Light Health Logic)
"""

import psutil
import subprocess
import json
import time
import os
from typing import Dict, List, Any, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

class HealthMonitor:
    """
    Monitors system health across multiple components with minimal impact.
    Implements hysteresis, intelligent caching, and progressive escalation.
    """
    
    # CPU Thresholds
    CPU_WARNING = 85
    CPU_CRITICAL = 95
    CPU_RECOVERY = 75
    CPU_WARNING_DURATION = 60  # seconds
    CPU_CRITICAL_DURATION = 120  # seconds
    CPU_RECOVERY_DURATION = 120  # seconds
    
    # Memory Thresholds
    MEMORY_WARNING = 85
    MEMORY_CRITICAL = 95
    MEMORY_DURATION = 60  # seconds
    SWAP_WARNING_DURATION = 300  # 5 minutes
    SWAP_CRITICAL_PERCENT = 5  # 5% of RAM
    SWAP_CRITICAL_DURATION = 120  # 2 minutes
    
    # Storage Thresholds
    STORAGE_WARNING = 85
    STORAGE_CRITICAL = 95
    
    # Temperature Thresholds
    TEMP_WARNING = 80
    TEMP_CRITICAL = 90
    
    # Network Thresholds
    NETWORK_LATENCY_WARNING = 100  # ms
    NETWORK_LATENCY_CRITICAL = 300  # ms
    NETWORK_TIMEOUT = 0.9  # seconds
    NETWORK_INACTIVE_DURATION = 600  # 10 minutes
    
    # Log Thresholds
    LOG_ERRORS_WARNING = 5
    LOG_ERRORS_CRITICAL = 6
    LOG_WARNINGS_WARNING = 10
    LOG_WARNINGS_CRITICAL = 30
    LOG_CHECK_INTERVAL = 300  # 5 minutes
    
    # Critical keywords for immediate escalation
    CRITICAL_LOG_KEYWORDS = [
        'I/O error', 'EXT4-fs error', 'XFS', 'LVM activation failed',
        'md/raid: device failed', 'Out of memory', 'kernel panic',
        'filesystem read-only', 'cannot mount'
    ]
    
    # PVE Critical Services
    PVE_SERVICES = ['pveproxy', 'pvedaemon', 'pvestatd', 'pve-cluster']
    
    def __init__(self):
        """Initialize health monitor with state tracking"""
        self.state_history = defaultdict(list)  # For hysteresis
        self.last_check_times = {}  # Cache check times
        self.cached_results = {}  # Cache results
        self.network_baseline = {}  # Network traffic baseline
        self.io_error_history = defaultdict(list)  # I/O error tracking
        
    def get_overall_status(self) -> Dict[str, Any]:
        """Get overall health status summary with minimal overhead"""
        details = self.get_detailed_status()
        
        overall_status = details.get('overall', 'OK')
        summary = details.get('summary', '')
        
        # Count statuses
        critical_count = 0
        warning_count = 0
        ok_count = 0
        
        for category, data in details.get('details', {}).items():
            if isinstance(data, dict):
                status = data.get('status', 'OK')
                if status == 'CRITICAL':
                    critical_count += 1
                elif status == 'WARNING':
                    warning_count += 1
                elif status == 'OK':
                    ok_count += 1
        
        return {
            'status': overall_status,
            'summary': summary,
            'critical_count': critical_count,
            'warning_count': warning_count,
            'ok_count': ok_count,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_detailed_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status with all checks.
        Returns JSON structure matching the specification.
        """
        details = {}
        critical_issues = []
        warning_issues = []
        
        # Priority 1: Services PVE / FS / Storage
        services_status = self._check_pve_services()
        details['services'] = services_status
        if services_status['status'] == 'CRITICAL':
            critical_issues.append(services_status.get('reason', 'Service failure'))
        elif services_status['status'] == 'WARNING':
            warning_issues.append(services_status.get('reason', 'Service issue'))
        
        storage_status = self._check_storage_comprehensive()
        details['storage'] = storage_status
        for storage_name, storage_data in storage_status.items():
            if isinstance(storage_data, dict):
                if storage_data.get('status') == 'CRITICAL':
                    critical_issues.append(f"{storage_name}: {storage_data.get('reason', 'Storage failure')}")
                elif storage_data.get('status') == 'WARNING':
                    warning_issues.append(f"{storage_name}: {storage_data.get('reason', 'Storage issue')}")
        
        # Priority 2: Disks / I/O
        disks_status = self._check_disks_io()
        details['disks'] = disks_status
        for disk_name, disk_data in disks_status.items():
            if isinstance(disk_data, dict):
                if disk_data.get('status') == 'CRITICAL':
                    critical_issues.append(f"{disk_name}: {disk_data.get('reason', 'Disk failure')}")
                elif disk_data.get('status') == 'WARNING':
                    warning_issues.append(f"{disk_name}: {disk_data.get('reason', 'Disk issue')}")
        
        # Priority 3: VM/CT
        vms_status = self._check_vms_cts()
        details['vms'] = vms_status
        if vms_status.get('status') == 'CRITICAL':
            critical_issues.append(vms_status.get('reason', 'VM/CT failure'))
        elif vms_status.get('status') == 'WARNING':
            warning_issues.append(vms_status.get('reason', 'VM/CT issue'))
        
        # Priority 4: Network
        network_status = self._check_network_comprehensive()
        details['network'] = network_status
        if network_status.get('status') == 'CRITICAL':
            critical_issues.append(network_status.get('reason', 'Network failure'))
        elif network_status.get('status') == 'WARNING':
            warning_issues.append(network_status.get('reason', 'Network issue'))
        
        # Priority 5: CPU/RAM
        cpu_status = self._check_cpu_with_hysteresis()
        details['cpu'] = cpu_status
        if cpu_status.get('status') == 'WARNING':
            warning_issues.append(cpu_status.get('reason', 'CPU high'))
        
        memory_status = self._check_memory_comprehensive()
        details['memory'] = memory_status
        if memory_status.get('status') == 'CRITICAL':
            critical_issues.append(memory_status.get('reason', 'Memory critical'))
        elif memory_status.get('status') == 'WARNING':
            warning_issues.append(memory_status.get('reason', 'Memory high'))
        
        # Priority 6: Logs
        logs_status = self._check_logs_lightweight()
        details['logs'] = logs_status
        if logs_status.get('status') == 'CRITICAL':
            critical_issues.append(logs_status.get('reason', 'Critical log errors'))
        elif logs_status.get('status') == 'WARNING':
            warning_issues.append(logs_status.get('reason', 'Log warnings'))
        
        # Priority 7: Extras (Security, Certificates, Uptime)
        security_status = self._check_security()
        details['security'] = security_status
        if security_status.get('status') == 'WARNING':
            warning_issues.append(security_status.get('reason', 'Security issue'))
        
        # Determine overall status
        if critical_issues:
            overall = 'CRITICAL'
            summary = '; '.join(critical_issues[:3])  # Top 3 critical issues
        elif warning_issues:
            overall = 'WARNING'
            summary = '; '.join(warning_issues[:3])  # Top 3 warnings
        else:
            overall = 'OK'
            summary = 'All systems operational'
        
        return {
            'overall': overall,
            'summary': summary,
            'details': details,
            'timestamp': datetime.now().isoformat()
        }
    
    def _check_cpu_with_hysteresis(self) -> Dict[str, Any]:
        """
        Check CPU with hysteresis to avoid flapping alerts.
        Requires sustained high usage before triggering.
        """
        try:
            # Get CPU usage (1 second sample to minimize impact)
            cpu_percent = psutil.cpu_percent(interval=1)
            current_time = time.time()
            
            # Track state history
            state_key = 'cpu_usage'
            self.state_history[state_key].append({
                'value': cpu_percent,
                'time': current_time
            })
            
            # Keep only recent history (last 5 minutes)
            self.state_history[state_key] = [
                entry for entry in self.state_history[state_key]
                if current_time - entry['time'] < 300
            ]
            
            # Check for sustained high usage
            critical_duration = sum(
                1 for entry in self.state_history[state_key]
                if entry['value'] >= self.CPU_CRITICAL and
                current_time - entry['time'] <= self.CPU_CRITICAL_DURATION
            )
            
            warning_duration = sum(
                1 for entry in self.state_history[state_key]
                if entry['value'] >= self.CPU_WARNING and
                current_time - entry['time'] <= self.CPU_WARNING_DURATION
            )
            
            recovery_duration = sum(
                1 for entry in self.state_history[state_key]
                if entry['value'] < self.CPU_RECOVERY and
                current_time - entry['time'] <= self.CPU_RECOVERY_DURATION
            )
            
            # Determine status with hysteresis
            if critical_duration >= 2:  # 2+ readings in critical range
                status = 'CRITICAL'
                reason = f'CPU >{self.CPU_CRITICAL}% for {self.CPU_CRITICAL_DURATION}s'
            elif warning_duration >= 2 and recovery_duration < 2:
                status = 'WARNING'
                reason = f'CPU >{self.CPU_WARNING}% for {self.CPU_WARNING_DURATION}s'
            else:
                status = 'OK'
                reason = None
            
            # Get temperature if available (checked once per minute max)
            temp_status = self._check_cpu_temperature()
            
            result = {
                'status': status,
                'usage': round(cpu_percent, 1),
                'cores': psutil.cpu_count()
            }
            
            if reason:
                result['reason'] = reason
            
            if temp_status:
                result['temperature'] = temp_status
                if temp_status.get('status') == 'CRITICAL':
                    result['status'] = 'CRITICAL'
                    result['reason'] = temp_status.get('reason')
                elif temp_status.get('status') == 'WARNING' and status == 'OK':
                    result['status'] = 'WARNING'
                    result['reason'] = temp_status.get('reason')
            
            return result
            
        except Exception as e:
            return {'status': 'UNKNOWN', 'reason': f'CPU check failed: {str(e)}'}
    
    def _check_cpu_temperature(self) -> Dict[str, Any]:
        """Check CPU temperature (cached, max 1 check per minute)"""
        cache_key = 'cpu_temp'
        current_time = time.time()
        
        # Check cache
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 60:
                return self.cached_results.get(cache_key, {})
        
        try:
            # Try lm-sensors first
            result = subprocess.run(
                ['sensors', '-A', '-u'],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                temps = []
                for line in result.stdout.split('\n'):
                    if 'temp' in line.lower() and '_input' in line:
                        try:
                            temp = float(line.split(':')[1].strip())
                            temps.append(temp)
                        except:
                            continue
                
                if temps:
                    max_temp = max(temps)
                    
                    if max_temp >= self.TEMP_CRITICAL:
                        status = 'CRITICAL'
                        reason = f'CPU temperature {max_temp}°C ≥{self.TEMP_CRITICAL}°C'
                    elif max_temp >= self.TEMP_WARNING:
                        status = 'WARNING'
                        reason = f'CPU temperature {max_temp}°C ≥{self.TEMP_WARNING}°C'
                    else:
                        status = 'OK'
                        reason = None
                    
                    temp_result = {
                        'status': status,
                        'value': round(max_temp, 1),
                        'unit': '°C'
                    }
                    if reason:
                        temp_result['reason'] = reason
                    
                    self.cached_results[cache_key] = temp_result
                    self.last_check_times[cache_key] = current_time
                    return temp_result
            
            # If sensors not available, return UNKNOWN (doesn't penalize)
            unknown_result = {'status': 'UNKNOWN', 'reason': 'No temperature sensors available'}
            self.cached_results[cache_key] = unknown_result
            self.last_check_times[cache_key] = current_time
            return unknown_result
            
        except Exception:
            unknown_result = {'status': 'UNKNOWN', 'reason': 'Temperature check unavailable'}
            self.cached_results[cache_key] = unknown_result
            self.last_check_times[cache_key] = current_time
            return unknown_result
    
    def _check_memory_comprehensive(self) -> Dict[str, Any]:
        """Check memory including RAM and swap with sustained thresholds"""
        try:
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            current_time = time.time()
            
            mem_percent = memory.percent
            swap_percent = swap.percent if swap.total > 0 else 0
            swap_vs_ram = (swap.used / memory.total * 100) if memory.total > 0 else 0
            
            # Track memory state
            state_key = 'memory_usage'
            self.state_history[state_key].append({
                'mem_percent': mem_percent,
                'swap_percent': swap_percent,
                'swap_vs_ram': swap_vs_ram,
                'time': current_time
            })
            
            # Keep only recent history
            self.state_history[state_key] = [
                entry for entry in self.state_history[state_key]
                if current_time - entry['time'] < 600
            ]
            
            # Check sustained high memory
            mem_critical = sum(
                1 for entry in self.state_history[state_key]
                if entry['mem_percent'] >= self.MEMORY_CRITICAL and
                current_time - entry['time'] <= self.MEMORY_DURATION
            )
            
            mem_warning = sum(
                1 for entry in self.state_history[state_key]
                if entry['mem_percent'] >= self.MEMORY_WARNING and
                current_time - entry['time'] <= self.MEMORY_DURATION
            )
            
            # Check swap usage
            swap_critical = sum(
                1 for entry in self.state_history[state_key]
                if entry['swap_vs_ram'] > self.SWAP_CRITICAL_PERCENT and
                current_time - entry['time'] <= self.SWAP_CRITICAL_DURATION
            )
            
            swap_warning = sum(
                1 for entry in self.state_history[state_key]
                if entry['swap_percent'] > 0 and
                current_time - entry['time'] <= self.SWAP_WARNING_DURATION
            )
            
            # Determine status
            if mem_critical >= 2:
                status = 'CRITICAL'
                reason = f'RAM >{self.MEMORY_CRITICAL}% for {self.MEMORY_DURATION}s'
            elif swap_critical >= 2:
                status = 'CRITICAL'
                reason = f'Swap >{self.SWAP_CRITICAL_PERCENT}% of RAM for {self.SWAP_CRITICAL_DURATION}s'
            elif mem_warning >= 2:
                status = 'WARNING'
                reason = f'RAM >{self.MEMORY_WARNING}% for {self.MEMORY_DURATION}s'
            elif swap_warning >= 2:
                status = 'WARNING'
                reason = f'Swap active for >{self.SWAP_WARNING_DURATION}s'
            else:
                status = 'OK'
                reason = None
            
            result = {
                'status': status,
                'ram_percent': round(mem_percent, 1),
                'ram_available_gb': round(memory.available / (1024**3), 2),
                'swap_percent': round(swap_percent, 1),
                'swap_used_gb': round(swap.used / (1024**3), 2)
            }
            
            if reason:
                result['reason'] = reason
            
            return result
            
        except Exception as e:
            return {'status': 'UNKNOWN', 'reason': f'Memory check failed: {str(e)}'}
    
    def _check_storage_comprehensive(self) -> Dict[str, Any]:
        """
        Comprehensive storage check including filesystems, mount points,
        LVM, and Proxmox storages.
        """
        storage_results = {}
        
        # Check critical filesystems
        critical_mounts = ['/', '/var', '/var/lib/vz']
        
        for mount_point in critical_mounts:
            if os.path.exists(mount_point):
                fs_status = self._check_filesystem(mount_point)
                storage_results[mount_point] = fs_status
        
        # Check all mounted filesystems
        try:
            partitions = psutil.disk_partitions()
            for partition in partitions:
                if partition.mountpoint not in critical_mounts:
                    try:
                        fs_status = self._check_filesystem(partition.mountpoint)
                        storage_results[partition.mountpoint] = fs_status
                    except PermissionError:
                        continue
        except Exception as e:
            storage_results['partitions_error'] = {
                'status': 'WARNING',
                'reason': f'Could not enumerate partitions: {str(e)}'
            }
        
        # Check LVM (especially local-lvm)
        lvm_status = self._check_lvm()
        if lvm_status:
            storage_results['lvm'] = lvm_status
        
        # Check Proxmox storages
        pve_storages = self._check_proxmox_storages()
        if pve_storages:
            storage_results.update(pve_storages)
        
        return storage_results
    
    def _check_filesystem(self, mount_point: str) -> Dict[str, Any]:
        """Check individual filesystem for space and mount status"""
        try:
            # Check if mounted
            result = subprocess.run(
                ['mountpoint', '-q', mount_point],
                capture_output=True,
                timeout=2
            )
            
            if result.returncode != 0:
                return {
                    'status': 'CRITICAL',
                    'reason': f'Not mounted'
                }
            
            # Check if read-only
            with open('/proc/mounts', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4 and parts[1] == mount_point:
                        options = parts[3].split(',')
                        if 'ro' in options:
                            return {
                                'status': 'CRITICAL',
                                'reason': 'Mounted read-only'
                            }
            
            # Check disk usage
            usage = psutil.disk_usage(mount_point)
            percent = usage.percent
            
            if percent >= self.STORAGE_CRITICAL:
                status = 'CRITICAL'
                reason = f'{percent:.1f}% full (≥{self.STORAGE_CRITICAL}%)'
            elif percent >= self.STORAGE_WARNING:
                status = 'WARNING'
                reason = f'{percent:.1f}% full (≥{self.STORAGE_WARNING}%)'
            else:
                status = 'OK'
                reason = None
            
            result = {
                'status': status,
                'usage_percent': round(percent, 1),
                'free_gb': round(usage.free / (1024**3), 2),
                'total_gb': round(usage.total / (1024**3), 2)
            }
            
            if reason:
                result['reason'] = reason
            
            return result
            
        except Exception as e:
            return {
                'status': 'WARNING',
                'reason': f'Check failed: {str(e)}'
            }
    
    def _check_lvm(self) -> Dict[str, Any]:
        """Check LVM volumes, especially local-lvm"""
        try:
            result = subprocess.run(
                ['lvs', '--noheadings', '--options', 'lv_name,vg_name,lv_attr'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode != 0:
                return {
                    'status': 'WARNING',
                    'reason': 'LVM not available or no volumes'
                }
            
            volumes = []
            local_lvm_found = False
            
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        lv_name = parts[0].strip()
                        vg_name = parts[1].strip()
                        volumes.append(f'{vg_name}/{lv_name}')
                        
                        if 'local-lvm' in lv_name or 'local-lvm' in vg_name:
                            local_lvm_found = True
            
            if not local_lvm_found and volumes:
                return {
                    'status': 'CRITICAL',
                    'reason': 'local-lvm volume not found',
                    'volumes': volumes
                }
            
            return {
                'status': 'OK',
                'volumes': volumes
            }
            
        except Exception as e:
            return {
                'status': 'WARNING',
                'reason': f'LVM check failed: {str(e)}'
            }
    
    def _check_proxmox_storages(self) -> Dict[str, Any]:
        """Check Proxmox-specific storages (NFS, CIFS, PBS)"""
        storages = {}
        
        try:
            # Read Proxmox storage configuration
            if os.path.exists('/etc/pve/storage.cfg'):
                with open('/etc/pve/storage.cfg', 'r') as f:
                    current_storage = None
                    storage_type = None
                    
                    for line in f:
                        line = line.strip()
                        
                        if line.startswith('dir:') or line.startswith('nfs:') or \
                           line.startswith('cifs:') or line.startswith('pbs:'):
                            parts = line.split(':', 1)
                            storage_type = parts[0]
                            current_storage = parts[1].strip()
                        elif line.startswith('path ') and current_storage:
                            path = line.split(None, 1)[1]
                            
                            if storage_type == 'dir':
                                if os.path.exists(path):
                                    storages[f'storage_{current_storage}'] = {
                                        'status': 'OK',
                                        'type': 'dir',
                                        'path': path
                                    }
                                else:
                                    storages[f'storage_{current_storage}'] = {
                                        'status': 'CRITICAL',
                                        'reason': 'Directory does not exist',
                                        'type': 'dir',
                                        'path': path
                                    }
                            
                            current_storage = None
                            storage_type = None
        except Exception as e:
            storages['pve_storage_config'] = {
                'status': 'WARNING',
                'reason': f'Could not read storage config: {str(e)}'
            }
        
        return storages
    
    def _check_disks_io(self) -> Dict[str, Any]:
        """Check disk I/O errors from dmesg (lightweight)"""
        disks = {}
        current_time = time.time()
        
        try:
            # Only check dmesg for recent errors (last 2 seconds of kernel log)
            result = subprocess.run(
                ['dmesg', '-T', '--level=err,warn', '--since', '5 minutes ago'],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                io_errors = defaultdict(int)
                
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    if any(keyword in line_lower for keyword in ['i/o error', 'ata error', 'scsi error']):
                        # Extract disk name
                        for part in line.split():
                            if part.startswith('sd') or part.startswith('nvme') or part.startswith('hd'):
                                disk_name = part.rstrip(':,')
                                io_errors[disk_name] += 1
                                
                                # Track in history
                                self.io_error_history[disk_name].append(current_time)
                
                # Clean old history (keep last 5 minutes)
                for disk in list(self.io_error_history.keys()):
                    self.io_error_history[disk] = [
                        t for t in self.io_error_history[disk]
                        if current_time - t < 300
                    ]
                    
                    error_count = len(self.io_error_history[disk])
                    
                    if error_count >= 3:
                        disks[f'/dev/{disk}'] = {
                            'status': 'CRITICAL',
                            'reason': f'{error_count} I/O errors in 5 minutes'
                        }
                    elif error_count >= 1:
                        disks[f'/dev/{disk}'] = {
                            'status': 'WARNING',
                            'reason': f'{error_count} I/O error(s) in 5 minutes'
                        }
            
            # If no errors found, report OK
            if not disks:
                disks['status'] = 'OK'
            
            return disks
            
        except Exception as e:
            return {
                'status': 'WARNING',
                'reason': f'Disk I/O check failed: {str(e)}'
            }
    
    def _check_network_comprehensive(self) -> Dict[str, Any]:
        """Check network interfaces, bridges, and connectivity"""
        try:
            issues = []
            interface_details = {}
            
            # Check interface status
            net_if_stats = psutil.net_if_stats()
            net_io = psutil.net_io_counters(pernic=True)
            current_time = time.time()
            
            for interface, stats in net_if_stats.items():
                if interface == 'lo':
                    continue
                
                # Check if interface is down (excluding administratively down)
                if not stats.isup:
                    # Check if it's a bridge or important interface
                    if interface.startswith('vmbr') or interface.startswith('eth') or interface.startswith('ens'):
                        issues.append(f'{interface} is DOWN')
                        interface_details[interface] = {
                            'status': 'CRITICAL',
                            'reason': 'Interface DOWN'
                        }
                        continue
                
                # Check bridge traffic (if no traffic for 10 minutes)
                if interface.startswith('vmbr') and interface in net_io:
                    io_stats = net_io[interface]
                    
                    # Initialize baseline if not exists
                    if interface not in self.network_baseline:
                        self.network_baseline[interface] = {
                            'rx_bytes': io_stats.bytes_recv,
                            'tx_bytes': io_stats.bytes_sent,
                            'time': current_time
                        }
                    else:
                        baseline = self.network_baseline[interface]
                        time_diff = current_time - baseline['time']
                        
                        if time_diff >= self.NETWORK_INACTIVE_DURATION:
                            rx_diff = io_stats.bytes_recv - baseline['rx_bytes']
                            tx_diff = io_stats.bytes_sent - baseline['tx_bytes']
                            
                            if rx_diff == 0 and tx_diff == 0:
                                issues.append(f'{interface} no traffic for 10+ minutes')
                                interface_details[interface] = {
                                    'status': 'WARNING',
                                    'reason': 'No traffic for 10+ minutes'
                                }
                            
                            # Update baseline
                            self.network_baseline[interface] = {
                                'rx_bytes': io_stats.bytes_recv,
                                'tx_bytes': io_stats.bytes_sent,
                                'time': current_time
                            }
            
            # Check gateway/DNS latency (lightweight, cached)
            latency_status = self._check_network_latency()
            if latency_status.get('status') != 'OK':
                issues.append(latency_status.get('reason', 'Network latency issue'))
                interface_details['connectivity'] = latency_status
            
            # Determine overall network status
            if any('CRITICAL' in str(detail.get('status')) for detail in interface_details.values()):
                status = 'CRITICAL'
                reason = '; '.join(issues[:2])
            elif issues:
                status = 'WARNING'
                reason = '; '.join(issues[:2])
            else:
                status = 'OK'
                reason = None
            
            result = {'status': status}
            if reason:
                result['reason'] = reason
            if interface_details:
                result['interfaces'] = interface_details
            
            return result
            
        except Exception as e:
            return {
                'status': 'WARNING',
                'reason': f'Network check failed: {str(e)}'
            }
    
    def _check_network_latency(self) -> Dict[str, Any]:
        """Check network latency to gateway/DNS (cached, max 1 check per minute)"""
        cache_key = 'network_latency'
        current_time = time.time()
        
        # Check cache
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 60:
                return self.cached_results.get(cache_key, {'status': 'OK'})
        
        try:
            # Ping default gateway or 1.1.1.1
            result = subprocess.run(
                ['ping', '-c', '1', '-W', '1', '1.1.1.1'],
                capture_output=True,
                text=True,
                timeout=self.NETWORK_TIMEOUT
            )
            
            if result.returncode == 0:
                # Extract latency
                for line in result.stdout.split('\n'):
                    if 'time=' in line:
                        try:
                            latency_str = line.split('time=')[1].split()[0]
                            latency = float(latency_str)
                            
                            if latency > self.NETWORK_LATENCY_CRITICAL:
                                status = 'CRITICAL'
                                reason = f'Latency {latency:.1f}ms >{self.NETWORK_LATENCY_CRITICAL}ms'
                            elif latency > self.NETWORK_LATENCY_WARNING:
                                status = 'WARNING'
                                reason = f'Latency {latency:.1f}ms >{self.NETWORK_LATENCY_WARNING}ms'
                            else:
                                status = 'OK'
                                reason = None
                            
                            latency_result = {
                                'status': status,
                                'latency_ms': round(latency, 1)
                            }
                            if reason:
                                latency_result['reason'] = reason
                            
                            self.cached_results[cache_key] = latency_result
                            self.last_check_times[cache_key] = current_time
                            return latency_result
                        except:
                            pass
            
            # Ping failed
            packet_loss_result = {
                'status': 'CRITICAL',
                'reason': 'Packet loss or timeout'
            }
            self.cached_results[cache_key] = packet_loss_result
            self.last_check_times[cache_key] = current_time
            return packet_loss_result
            
        except Exception as e:
            error_result = {
                'status': 'WARNING',
                'reason': f'Latency check failed: {str(e)}'
            }
            self.cached_results[cache_key] = error_result
            self.last_check_times[cache_key] = current_time
            return error_result
    
    def _check_vms_cts(self) -> Dict[str, Any]:
        """Check VM and CT status for unexpected stops"""
        try:
            issues = []
            vm_details = {}
            
            # Check VMs
            try:
                result = subprocess.run(
                    ['qm', 'list'],
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n')[1:]:
                        if line.strip():
                            parts = line.split()
                            if len(parts) >= 3:
                                vmid = parts[0]
                                vm_status = parts[2]
                                
                                if vm_status == 'stopped':
                                    # Check if unexpected (this is simplified, would need autostart config)
                                    vm_details[f'vm_{vmid}'] = {
                                        'status': 'WARNING',
                                        'reason': 'VM stopped'
                                    }
                                    issues.append(f'VM {vmid} stopped')
            except Exception as e:
                vm_details['vms_check'] = {
                    'status': 'WARNING',
                    'reason': f'Could not check VMs: {str(e)}'
                }
            
            # Check CTs
            try:
                result = subprocess.run(
                    ['pct', 'list'],
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n')[1:]:
                        if line.strip():
                            parts = line.split()
                            if len(parts) >= 2:
                                ctid = parts[0]
                                ct_status = parts[1]
                                
                                if ct_status == 'stopped':
                                    vm_details[f'ct_{ctid}'] = {
                                        'status': 'WARNING',
                                        'reason': 'CT stopped'
                                    }
                                    issues.append(f'CT {ctid} stopped')
            except Exception as e:
                vm_details['cts_check'] = {
                    'status': 'WARNING',
                    'reason': f'Could not check CTs: {str(e)}'
                }
            
            # Determine overall status
            if issues:
                status = 'WARNING'
                reason = '; '.join(issues[:3])
            else:
                status = 'OK'
                reason = None
            
            result = {'status': status}
            if reason:
                result['reason'] = reason
            if vm_details:
                result['details'] = vm_details
            
            return result
            
        except Exception as e:
            return {
                'status': 'WARNING',
                'reason': f'VM/CT check failed: {str(e)}'
            }
    
    def _check_pve_services(self) -> Dict[str, Any]:
        """Check critical Proxmox services"""
        try:
            failed_services = []
            
            for service in self.PVE_SERVICES:
                try:
                    result = subprocess.run(
                        ['systemctl', 'is-active', service],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    
                    if result.returncode != 0 or result.stdout.strip() != 'active':
                        failed_services.append(service)
                except Exception:
                    failed_services.append(service)
            
            if failed_services:
                return {
                    'status': 'CRITICAL',
                    'reason': f'Services inactive: {", ".join(failed_services)}',
                    'failed': failed_services
                }
            
            return {'status': 'OK'}
            
        except Exception as e:
            return {
                'status': 'WARNING',
                'reason': f'Service check failed: {str(e)}'
            }
    
    def _check_logs_lightweight(self) -> Dict[str, Any]:
        """Lightweight log analysis (cached, checked every 5 minutes)"""
        cache_key = 'logs_analysis'
        current_time = time.time()
        
        # Check cache
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < self.LOG_CHECK_INTERVAL:
                return self.cached_results.get(cache_key, {'status': 'OK'})
        
        try:
            # Check journalctl for recent errors and warnings
            result = subprocess.run(
                ['journalctl', '--since', '5 minutes ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                
                errors_5m = 0
                warnings_5m = 0
                critical_keywords_found = []
                
                for line in lines:
                    line_lower = line.lower()
                    
                    # Check for critical keywords
                    for keyword in self.CRITICAL_LOG_KEYWORDS:
                        if keyword.lower() in line_lower:
                            critical_keywords_found.append(keyword)
                            errors_5m += 1
                            break
                    else:
                        # Count errors and warnings
                        if 'error' in line_lower or 'critical' in line_lower or 'fatal' in line_lower:
                            errors_5m += 1
                        elif 'warning' in line_lower or 'warn' in line_lower:
                            warnings_5m += 1
                
                # Determine status
                if critical_keywords_found:
                    status = 'CRITICAL'
                    reason = f'Critical errors: {", ".join(set(critical_keywords_found[:3]))}'
                elif errors_5m >= self.LOG_ERRORS_CRITICAL:
                    status = 'CRITICAL'
                    reason = f'{errors_5m} errors in 5 minutes (≥{self.LOG_ERRORS_CRITICAL})'
                elif warnings_5m >= self.LOG_WARNINGS_CRITICAL:
                    status = 'CRITICAL'
                    reason = f'{warnings_5m} warnings in 5 minutes (≥{self.LOG_WARNINGS_CRITICAL})'
                elif errors_5m >= self.LOG_ERRORS_WARNING:
                    status = 'WARNING'
                    reason = f'{errors_5m} errors in 5 minutes'
                elif warnings_5m >= self.LOG_WARNINGS_WARNING:
                    status = 'WARNING'
                    reason = f'{warnings_5m} warnings in 5 minutes'
                else:
                    status = 'OK'
                    reason = None
                
                log_result = {
                    'status': status,
                    'errors_5m': errors_5m,
                    'warnings_5m': warnings_5m
                }
                if reason:
                    log_result['reason'] = reason
                
                self.cached_results[cache_key] = log_result
                self.last_check_times[cache_key] = current_time
                return log_result
            
            ok_result = {'status': 'OK'}
            self.cached_results[cache_key] = ok_result
            self.last_check_times[cache_key] = current_time
            return ok_result
            
        except Exception as e:
            error_result = {
                'status': 'WARNING',
                'reason': f'Log check failed: {str(e)}'
            }
            self.cached_results[cache_key] = error_result
            self.last_check_times[cache_key] = current_time
            return error_result
    
    def _check_security(self) -> Dict[str, Any]:
        """Check security-related items (fail2ban, certificates, uptime)"""
        try:
            issues = []
            
            # Check fail2ban
            try:
                result = subprocess.run(
                    ['systemctl', 'is-active', 'fail2ban'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if result.returncode != 0 or result.stdout.strip() != 'active':
                    issues.append('fail2ban inactive')
            except Exception:
                pass
            
            # Check uptime (warning if >180 days)
            try:
                uptime_seconds = time.time() - psutil.boot_time()
                uptime_days = uptime_seconds / 86400
                
                if uptime_days > 180:
                    issues.append(f'Uptime {int(uptime_days)} days (>180)')
            except Exception:
                pass
            
            # Check SSL certificates (cached, checked once per day)
            cert_status = self._check_certificates()
            if cert_status.get('status') != 'OK':
                issues.append(cert_status.get('reason', 'Certificate issue'))
            
            if issues:
                return {
                    'status': 'WARNING',
                    'reason': '; '.join(issues[:2])
                }
            
            return {'status': 'OK'}
            
        except Exception as e:
            return {
                'status': 'WARNING',
                'reason': f'Security check failed: {str(e)}'
            }
    
    def _check_certificates(self) -> Dict[str, Any]:
        """Check SSL certificate expiration (cached, checked once per day)"""
        cache_key = 'certificates'
        current_time = time.time()
        
        # Check cache (24 hours)
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 86400:
                return self.cached_results.get(cache_key, {'status': 'OK'})
        
        try:
            # Check PVE certificate
            cert_path = '/etc/pve/local/pve-ssl.pem'
            
            if os.path.exists(cert_path):
                result = subprocess.run(
                    ['openssl', 'x509', '-enddate', '-noout', '-in', cert_path],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if result.returncode == 0:
                    # Parse expiration date
                    date_str = result.stdout.strip().replace('notAfter=', '')
                    
                    try:
                        from datetime import datetime
                        exp_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
                        days_until_expiry = (exp_date - datetime.now()).days
                        
                        if days_until_expiry < 0:
                            status = 'CRITICAL'
                            reason = 'Certificate expired'
                        elif days_until_expiry < 15:
                            status = 'WARNING'
                            reason = f'Certificate expires in {days_until_expiry} days'
                        else:
                            status = 'OK'
                            reason = None
                        
                        cert_result = {'status': status}
                        if reason:
                            cert_result['reason'] = reason
                        
                        self.cached_results[cache_key] = cert_result
                        self.last_check_times[cache_key] = current_time
                        return cert_result
                    except Exception:
                        pass
            
            ok_result = {'status': 'OK'}
            self.cached_results[cache_key] = ok_result
            self.last_check_times[cache_key] = current_time
            return ok_result
            
        except Exception:
            ok_result = {'status': 'OK'}
            self.cached_results[cache_key] = ok_result
            self.last_check_times[cache_key] = current_time
            return ok_result


# Global instance
health_monitor = HealthMonitor()
