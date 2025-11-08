"""
ProxMenux Health Monitor Module
Provides comprehensive, lightweight health checks for Proxmox systems.
Optimized for minimal system impact with intelligent thresholds and hysteresis.

Author: MacRimi
Version: 1.1 (Optimized for minimal overhead)
"""

import psutil
import subprocess
import json
import time
import os
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime, timedelta
from collections import defaultdict

class HealthMonitor:
    """
    Monitors system health across multiple components with minimal impact.
    Implements hysteresis, intelligent caching, and progressive escalation.
    Only reports problems, not verbose OK statuses.
    """
    
    # CPU Thresholds
    CPU_WARNING = 85
    CPU_CRITICAL = 95
    CPU_RECOVERY = 75
    CPU_WARNING_DURATION = 60
    CPU_CRITICAL_DURATION = 120
    CPU_RECOVERY_DURATION = 120
    
    # Memory Thresholds
    MEMORY_WARNING = 85
    MEMORY_CRITICAL = 95
    MEMORY_DURATION = 60
    SWAP_WARNING_DURATION = 300
    SWAP_CRITICAL_PERCENT = 5
    SWAP_CRITICAL_DURATION = 120
    
    # Storage Thresholds
    STORAGE_WARNING = 85
    STORAGE_CRITICAL = 95
    
    # Temperature Thresholds
    TEMP_WARNING = 80
    TEMP_CRITICAL = 90
    
    # Network Thresholds
    NETWORK_LATENCY_WARNING = 100
    NETWORK_LATENCY_CRITICAL = 300
    NETWORK_TIMEOUT = 0.9
    NETWORK_INACTIVE_DURATION = 600
    
    # Log Thresholds
    LOG_ERRORS_WARNING = 5
    LOG_ERRORS_CRITICAL = 10
    LOG_WARNINGS_WARNING = 15
    LOG_WARNINGS_CRITICAL = 30
    LOG_CHECK_INTERVAL = 300
    
    # Updates Thresholds
    UPDATES_WARNING = 10
    UPDATES_CRITICAL = 30
    
    # Critical keywords for immediate escalation
    CRITICAL_LOG_KEYWORDS = [
        'I/O error', 'EXT4-fs error', 'XFS', 'LVM activation failed',
        'md/raid: device failed', 'Out of memory', 'kernel panic',
        'filesystem read-only', 'cannot mount', 'failed to start',
        'task hung', 'oom_kill'
    ]
    
    # PVE Critical Services
    PVE_SERVICES = ['pveproxy', 'pvedaemon', 'pvestatd', 'pve-cluster']
    
    def __init__(self):
        """Initialize health monitor with state tracking"""
        self.state_history = defaultdict(list)
        self.last_check_times = {}
        self.cached_results = {}
        self.network_baseline = {}
        self.io_error_history = defaultdict(list)
        self.failed_vm_history = set()  # Track VMs that failed to start
        
    def get_system_info(self) -> Dict[str, Any]:
        """
        Get lightweight system info for header display.
        Returns: hostname, uptime, and cached health status.
        This is extremely lightweight and uses cached health status.
        """
        try:
            # Get hostname
            hostname = os.uname().nodename
            
            # Get uptime (very cheap operation)
            uptime_seconds = time.time() - psutil.boot_time()
            
            # Get cached health status (no expensive checks)
            health_status = self.get_cached_health_status()
            
            return {
                'hostname': hostname,
                'uptime_seconds': int(uptime_seconds),
                'uptime_formatted': self._format_uptime(uptime_seconds),
                'health': health_status,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'hostname': 'unknown',
                'uptime_seconds': 0,
                'uptime_formatted': 'Unknown',
                'health': {'status': 'UNKNOWN', 'summary': f'Error: {str(e)}'},
                'timestamp': datetime.now().isoformat()
            }
    
    def _format_uptime(self, seconds: float) -> str:
        """Format uptime in human-readable format"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
    def get_cached_health_status(self) -> Dict[str, str]:
        """
        Get cached health status without running expensive checks.
        Returns the last calculated status or triggers a check if too old.
        """
        cache_key = 'overall_health'
        current_time = time.time()
        
        # If cache exists and is less than 60 seconds old, return it
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 60:
                return self.cached_results.get(cache_key, {'status': 'OK', 'summary': 'System operational'})
        
        # Otherwise, calculate and cache
        status = self.get_overall_status()
        self.cached_results[cache_key] = {
            'status': status['status'],
            'summary': status['summary']
        }
        self.last_check_times[cache_key] = current_time
        
        return self.cached_results[cache_key]
    
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
        OPTIMIZED: Only shows problems, not verbose OK messages.
        """
        details = {}
        critical_issues = []
        warning_issues = []
        
        # Priority 1: Services PVE
        services_status = self._check_pve_services()
        if services_status['status'] != 'OK':
            details['services'] = services_status
            if services_status['status'] == 'CRITICAL':
                critical_issues.append(services_status.get('reason', 'Service failure'))
            elif services_status['status'] == 'WARNING':
                warning_issues.append(services_status.get('reason', 'Service issue'))
        
        storage_status = self._check_storage_optimized()
        if storage_status and storage_status.get('status') != 'OK':
            details['storage'] = storage_status
            if storage_status.get('status') == 'CRITICAL':
                critical_issues.append(storage_status.get('reason', 'Storage failure'))
            elif storage_status.get('status') == 'WARNING':
                warning_issues.append(storage_status.get('reason', 'Storage issue'))
        
        disks_status = self._check_disks_optimized()
        if disks_status and disks_status.get('status') != 'OK':
            details['disks'] = disks_status
            if disks_status.get('status') == 'CRITICAL':
                critical_issues.append(disks_status.get('reason', 'Disk failure'))
            elif disks_status.get('status') == 'WARNING':
                warning_issues.append(disks_status.get('reason', 'Disk issue'))
        
        vms_status = self._check_vms_cts_optimized()
        if vms_status and vms_status.get('status') != 'OK':
            details['vms'] = vms_status
            if vms_status.get('status') == 'CRITICAL':
                critical_issues.append(vms_status.get('reason', 'VM/CT failure'))
            elif vms_status.get('status') == 'WARNING':
                warning_issues.append(vms_status.get('reason', 'VM/CT issue'))
        
        network_status = self._check_network_optimized()
        if network_status and network_status.get('status') != 'OK':
            details['network'] = network_status
            if network_status.get('status') == 'CRITICAL':
                critical_issues.append(network_status.get('reason', 'Network failure'))
            elif network_status.get('status') == 'WARNING':
                warning_issues.append(network_status.get('reason', 'Network issue'))
        
        # Priority 5: CPU/RAM (solo si hay problemas)
        cpu_status = self._check_cpu_with_hysteresis()
        if cpu_status.get('status') != 'OK':
            details['cpu'] = cpu_status
            if cpu_status.get('status') == 'WARNING':
                warning_issues.append(cpu_status.get('reason', 'CPU high'))
            elif cpu_status.get('status') == 'CRITICAL':
                critical_issues.append(cpu_status.get('reason', 'CPU critical'))
        
        memory_status = self._check_memory_comprehensive()
        if memory_status.get('status') != 'OK':
            details['memory'] = memory_status
            if memory_status.get('status') == 'CRITICAL':
                critical_issues.append(memory_status.get('reason', 'Memory critical'))
            elif memory_status.get('status') == 'WARNING':
                warning_issues.append(memory_status.get('reason', 'Memory high'))
        
        # Priority 6: Logs (solo errores críticos)
        logs_status = self._check_logs_lightweight()
        if logs_status.get('status') != 'OK':
            details['logs'] = logs_status
            if logs_status.get('status') == 'CRITICAL':
                critical_issues.append(logs_status.get('reason', 'Critical log errors'))
            elif logs_status.get('status') == 'WARNING':
                warning_issues.append(logs_status.get('reason', 'Log warnings'))
        
        updates_status = self._check_updates()
        if updates_status and updates_status.get('status') != 'OK':
            details['updates'] = updates_status
            if updates_status.get('status') == 'WARNING':
                warning_issues.append(updates_status.get('reason', 'Updates pending'))
        
        # Priority 7: Security (solo problemas)
        security_status = self._check_security()
        if security_status.get('status') != 'OK':
            details['security'] = security_status
            if security_status.get('status') == 'WARNING':
                warning_issues.append(security_status.get('reason', 'Security issue'))
        
        # Determine overall status
        if critical_issues:
            overall = 'CRITICAL'
            summary = '; '.join(critical_issues[:3])
        elif warning_issues:
            overall = 'WARNING'
            summary = '; '.join(warning_issues[:3])
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
        """Check CPU with hysteresis to avoid flapping alerts"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            current_time = time.time()
            
            state_key = 'cpu_usage'
            self.state_history[state_key].append({
                'value': cpu_percent,
                'time': current_time
            })
            
            self.state_history[state_key] = [
                entry for entry in self.state_history[state_key]
                if current_time - entry['time'] < 300
            ]
            
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
            
            if critical_duration >= 2:
                status = 'CRITICAL'
                reason = f'CPU >{self.CPU_CRITICAL}% for {self.CPU_CRITICAL_DURATION}s'
            elif warning_duration >= 2 and recovery_duration < 2:
                status = 'WARNING'
                reason = f'CPU >{self.CPU_WARNING}% for {self.CPU_WARNING_DURATION}s'
            else:
                status = 'OK'
                reason = None
            
            temp_status = self._check_cpu_temperature()
            
            result = {
                'status': status,
                'usage': round(cpu_percent, 1),
                'cores': psutil.cpu_count()
            }
            
            if reason:
                result['reason'] = reason
            
            if temp_status and temp_status.get('status') != 'UNKNOWN':
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
    
    def _check_cpu_temperature(self) -> Optional[Dict[str, Any]]:
        """Check CPU temperature (cached, max 1 check per minute)"""
        cache_key = 'cpu_temp'
        current_time = time.time()
        
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 60:
                return self.cached_results.get(cache_key)
        
        try:
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
            
            return None
            
        except Exception:
            return None
    
    def _check_memory_comprehensive(self) -> Dict[str, Any]:
        """Check memory including RAM and swap with sustained thresholds"""
        try:
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            current_time = time.time()
            
            mem_percent = memory.percent
            swap_percent = swap.percent if swap.total > 0 else 0
            swap_vs_ram = (swap.used / memory.total * 100) if memory.total > 0 else 0
            
            state_key = 'memory_usage'
            self.state_history[state_key].append({
                'mem_percent': mem_percent,
                'swap_percent': swap_percent,
                'swap_vs_ram': swap_vs_ram,
                'time': current_time
            })
            
            self.state_history[state_key] = [
                entry for entry in self.state_history[state_key]
                if current_time - entry['time'] < 600
            ]
            
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
    
    def _check_storage_optimized(self) -> Optional[Dict[str, Any]]:
        """
        Optimized storage check - only reports problems.
        Checks critical mounts, LVM, and Proxmox storages.
        """
        issues = []
        storage_details = {}
        
        # Check critical filesystems
        critical_mounts = ['/', '/var/lib/vz']
        
        for mount_point in critical_mounts:
            if not os.path.exists(mount_point):
                issues.append(f'{mount_point} not mounted')
                storage_details[mount_point] = {
                    'status': 'CRITICAL',
                    'reason': 'Not mounted'
                }
                continue
            
            fs_status = self._check_filesystem(mount_point)
            if fs_status['status'] != 'OK':
                issues.append(f"{mount_point}: {fs_status['reason']}")
                storage_details[mount_point] = fs_status
        
        # Check LVM
        lvm_status = self._check_lvm()
        if lvm_status and lvm_status.get('status') != 'OK':
            issues.append(lvm_status.get('reason', 'LVM issue'))
            storage_details['lvm'] = lvm_status
        
        # Check Proxmox storages (PBS, NFS, etc)
        pve_storages = self._check_proxmox_storages()
        for storage_name, storage_data in pve_storages.items():
            if storage_data.get('status') != 'OK':
                issues.append(f"{storage_name}: {storage_data.get('reason', 'Storage issue')}")
                storage_details[storage_name] = storage_data
        
        # If no issues, return None (optimized)
        if not issues:
            return {'status': 'OK'}
        
        # Determine overall status
        has_critical = any(d.get('status') == 'CRITICAL' for d in storage_details.values())
        
        return {
            'status': 'CRITICAL' if has_critical else 'WARNING',
            'reason': '; '.join(issues[:3]),
            'details': storage_details
        }
    
    def _check_filesystem(self, mount_point: str) -> Dict[str, Any]:
        """Check individual filesystem for space and mount status"""
        try:
            result = subprocess.run(
                ['mountpoint', '-q', mount_point],
                capture_output=True,
                timeout=2
            )
            
            if result.returncode != 0:
                return {
                    'status': 'CRITICAL',
                    'reason': 'Not mounted'
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
                'usage_percent': round(percent, 1)
            }
            
            if reason:
                result['reason'] = reason
            
            return result
            
        except Exception as e:
            return {
                'status': 'WARNING',
                'reason': f'Check failed: {str(e)}'
            }
    
    def _check_lvm(self) -> Optional[Dict[str, Any]]:
        """Check LVM volumes, especially local-lvm"""
        try:
            result = subprocess.run(
                ['lvs', '--noheadings', '--options', 'lv_name,vg_name,lv_attr'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode != 0:
                return None
            
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
            
            if volumes and not local_lvm_found:
                return {
                    'status': 'CRITICAL',
                    'reason': 'local-lvm volume not found'
                }
            
            return {'status': 'OK'}
            
        except Exception:
            return None
    
    def _check_proxmox_storages(self) -> Dict[str, Any]:
        """Check Proxmox-specific storages (only report problems)"""
        storages = {}
        
        try:
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
                                if not os.path.exists(path):
                                    storages[f'storage_{current_storage}'] = {
                                        'status': 'CRITICAL',
                                        'reason': 'Directory does not exist',
                                        'type': 'dir',
                                        'path': path
                                    }
                            
                            current_storage = None
                            storage_type = None
        except Exception:
            pass
        
        return storages
    
    def _check_disks_optimized(self) -> Optional[Dict[str, Any]]:
        """
        Optimized disk check - only reports I/O errors and SMART issues.
        """
        current_time = time.time()
        disk_issues = {}
        
        try:
            # Check dmesg for I/O errors
            result = subprocess.run(
                ['dmesg', '-T', '--level=err,warn', '--since', '5 minutes ago'],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    if any(keyword in line_lower for keyword in ['i/o error', 'ata error', 'scsi error']):
                        for part in line.split():
                            if part.startswith('sd') or part.startswith('nvme') or part.startswith('hd'):
                                disk_name = part.rstrip(':,')
                                self.io_error_history[disk_name].append(current_time)
                
                # Clean old history
                for disk in list(self.io_error_history.keys()):
                    self.io_error_history[disk] = [
                        t for t in self.io_error_history[disk]
                        if current_time - t < 300
                    ]
                    
                    error_count = len(self.io_error_history[disk])
                    
                    if error_count >= 3:
                        disk_issues[f'/dev/{disk}'] = {
                            'status': 'CRITICAL',
                            'reason': f'{error_count} I/O errors in 5 minutes'
                        }
                    elif error_count >= 1:
                        disk_issues[f'/dev/{disk}'] = {
                            'status': 'WARNING',
                            'reason': f'{error_count} I/O error(s) in 5 minutes'
                        }
            
            # If no issues, return OK
            if not disk_issues:
                return {'status': 'OK'}
            
            has_critical = any(d.get('status') == 'CRITICAL' for d in disk_issues.values())
            
            return {
                'status': 'CRITICAL' if has_critical else 'WARNING',
                'reason': f"{len(disk_issues)} disk(s) with errors",
                'details': disk_issues
            }
            
        except Exception:
            return None
    
    def _check_network_optimized(self) -> Optional[Dict[str, Any]]:
        """
        Optimized network check - only reports problems.
        Checks interfaces down, no connectivity.
        """
        try:
            issues = []
            interface_details = {}
            
            net_if_stats = psutil.net_if_stats()
            
            for interface, stats in net_if_stats.items():
                if interface == 'lo':
                    continue
                
                # Check if important interface is down
                if not stats.isup:
                    if interface.startswith('vmbr') or interface.startswith('eth') or interface.startswith('ens'):
                        issues.append(f'{interface} is DOWN')
                        interface_details[interface] = {
                            'status': 'CRITICAL',
                            'reason': 'Interface DOWN'
                        }
            
            # Check connectivity
            latency_status = self._check_network_latency()
            if latency_status and latency_status.get('status') not in ['OK', 'UNKNOWN']:
                issues.append(latency_status.get('reason', 'Network latency issue'))
                interface_details['connectivity'] = latency_status
            
            # If no issues, return OK
            if not issues:
                return {'status': 'OK'}
            
            has_critical = any(d.get('status') == 'CRITICAL' for d in interface_details.values())
            
            return {
                'status': 'CRITICAL' if has_critical else 'WARNING',
                'reason': '; '.join(issues[:2]),
                'details': interface_details
            }
            
        except Exception:
            return None
    
    def _check_network_latency(self) -> Optional[Dict[str, Any]]:
        """Check network latency to 1.1.1.1 (cached)"""
        cache_key = 'network_latency'
        current_time = time.time()
        
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 60:
                return self.cached_results.get(cache_key)
        
        try:
            result = subprocess.run(
                ['ping', '-c', '1', '-W', '1', '1.1.1.1'],
                capture_output=True,
                text=True,
                timeout=self.NETWORK_TIMEOUT
            )
            
            if result.returncode == 0:
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
            
            packet_loss_result = {
                'status': 'CRITICAL',
                'reason': 'Packet loss or timeout'
            }
            self.cached_results[cache_key] = packet_loss_result
            self.last_check_times[cache_key] = current_time
            return packet_loss_result
            
        except Exception:
            return None
    
    def _check_vms_cts_optimized(self) -> Optional[Dict[str, Any]]:
        """
        Optimized VM/CT check - only reports failed starts.
        Checks logs for VMs/CTs that failed to start.
        """
        try:
            issues = []
            vm_details = {}
            
            # Check logs for failed VM/CT starts
            result = subprocess.run(
                ['journalctl', '--since', '10 minutes ago', '--no-pager', '-u', 'pve*'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    
                    # Detect VM/CT start failures
                    if 'failed to start' in line_lower or 'error starting' in line_lower or \
                       'start error' in line_lower or 'cannot start' in line_lower:
                        # Extract VM/CT ID
                        for word in line.split():
                            if word.isdigit() and len(word) <= 4:
                                vmid = word
                                if vmid not in self.failed_vm_history:
                                    self.failed_vm_history.add(vmid)
                                    issues.append(f'VM/CT {vmid} failed to start')
                                    vm_details[f'vmct_{vmid}'] = {
                                        'status': 'CRITICAL',
                                        'reason': 'Failed to start'
                                    }
                                break
            
            # If no issues, return OK
            if not issues:
                return {'status': 'OK'}
            
            return {
                'status': 'CRITICAL',
                'reason': '; '.join(issues[:3]),
                'details': vm_details
            }
            
        except Exception:
            return None
    
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
        
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < self.LOG_CHECK_INTERVAL:
                return self.cached_results.get(cache_key, {'status': 'OK'})
        
        try:
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
                    
                    for keyword in self.CRITICAL_LOG_KEYWORDS:
                        if keyword.lower() in line_lower:
                            critical_keywords_found.append(keyword)
                            errors_5m += 1
                            break
                    else:
                        if 'error' in line_lower or 'critical' in line_lower or 'fatal' in line_lower:
                            errors_5m += 1
                        elif 'warning' in line_lower or 'warn' in line_lower:
                            warnings_5m += 1
                
                if critical_keywords_found:
                    status = 'CRITICAL'
                    reason = f'Critical errors: {", ".join(set(critical_keywords_found[:3]))}'
                elif errors_5m >= self.LOG_ERRORS_CRITICAL:
                    status = 'CRITICAL'
                    reason = f'{errors_5m} errors in 5 minutes'
                elif warnings_5m >= self.LOG_WARNINGS_CRITICAL:
                    status = 'WARNING'
                    reason = f'{warnings_5m} warnings in 5 minutes'
                elif errors_5m >= self.LOG_ERRORS_WARNING:
                    status = 'WARNING'
                    reason = f'{errors_5m} errors in 5 minutes'
                elif warnings_5m >= self.LOG_WARNINGS_WARNING:
                    status = 'WARNING'
                    reason = f'{warnings_5m} warnings in 5 minutes'
                else:
                    status = 'OK'
                    reason = None
                
                log_result = {'status': status}
                if reason:
                    log_result['reason'] = reason
                
                self.cached_results[cache_key] = log_result
                self.last_check_times[cache_key] = current_time
                return log_result
            
            ok_result = {'status': 'OK'}
            self.cached_results[cache_key] = ok_result
            self.last_check_times[cache_key] = current_time
            return ok_result
            
        except Exception:
            return {'status': 'OK'}
    
    def _check_updates(self) -> Optional[Dict[str, Any]]:
        """Check for pending system updates (cached, checked every 10 minutes)"""
        cache_key = 'updates_check'
        current_time = time.time()
        
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 600:
                return self.cached_results.get(cache_key)
        
        try:
            # Check apt updates
            result = subprocess.run(
                ['apt', 'list', '--upgradable'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                # First line is header
                update_count = len([l for l in lines if l and not l.startswith('Listing')])
                
                if update_count >= self.UPDATES_CRITICAL:
                    status = 'WARNING'
                    reason = f'{update_count} updates pending (≥{self.UPDATES_CRITICAL})'
                elif update_count >= self.UPDATES_WARNING:
                    status = 'WARNING'
                    reason = f'{update_count} updates pending'
                else:
                    status = 'OK'
                    reason = None
                
                update_result = {
                    'status': status,
                    'count': update_count
                }
                if reason:
                    update_result['reason'] = reason
                
                self.cached_results[cache_key] = update_result
                self.last_check_times[cache_key] = current_time
                return update_result
            
            return None
            
        except Exception:
            return None
    
    def _check_security(self) -> Dict[str, Any]:
        """Check security-related items (certificates, uptime)"""
        try:
            issues = []
            
            # Check uptime (warning if >180 days)
            try:
                uptime_seconds = time.time() - psutil.boot_time()
                uptime_days = uptime_seconds / 86400
                
                if uptime_days > 180:
                    issues.append(f'Uptime {int(uptime_days)} days (>180)')
            except Exception:
                pass
            
            # Check SSL certificates
            cert_status = self._check_certificates()
            if cert_status and cert_status.get('status') != 'OK':
                issues.append(cert_status.get('reason', 'Certificate issue'))
            
            if issues:
                return {
                    'status': 'WARNING',
                    'reason': '; '.join(issues[:2])
                }
            
            return {'status': 'OK'}
            
        except Exception:
            return {'status': 'OK'}
    
    def _check_certificates(self) -> Optional[Dict[str, Any]]:
        """Check SSL certificate expiration (cached, checked once per day)"""
        cache_key = 'certificates'
        current_time = time.time()
        
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 86400:
                return self.cached_results.get(cache_key)
        
        try:
            cert_path = '/etc/pve/local/pve-ssl.pem'
            
            if os.path.exists(cert_path):
                result = subprocess.run(
                    ['openssl', 'x509', '-enddate', '-noout', '-in', cert_path],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if result.returncode == 0:
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
            
            return None
            
        except Exception:
            return None


# Global instance
health_monitor = HealthMonitor()
