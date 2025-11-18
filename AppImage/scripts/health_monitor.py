"""
ProxMenux Health Monitor Module
Provides comprehensive, lightweight health checks for Proxmox systems.
Optimized for minimal system impact with intelligent thresholds and hysteresis.

Author: MacRimi
Version: 1.2 (Always returns all 10 categories)
"""

import psutil
import subprocess
import json
import time
import os
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import re

from health_persistence import health_persistence

class HealthMonitor:
    """
    Monitors system health across multiple components with minimal impact.
    Implements hysteresis, intelligent caching, progressive escalation, and persistent error tracking.
    Always returns all 10 health categories.
    """
    
    # CPU Thresholds
    CPU_WARNING = 85
    CPU_CRITICAL = 95
    CPU_RECOVERY = 75
    CPU_WARNING_DURATION = 300  # 5 minutes sustained
    CPU_CRITICAL_DURATION = 300  # 5 minutes sustained
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
    UPDATES_WARNING = 365  # Only warn after 1 year without updates
    UPDATES_CRITICAL = 730  # Critical after 2 years
    
    # Known benign errors from Proxmox that should not trigger alerts
    BENIGN_ERROR_PATTERNS = [
        r'got inotify poll request in wrong process',
        r'auth key pair too old, rotating',
        r'proxy detected vanished client connection',
        r'worker \d+ finished',
        r'connection timed out',
        r'disconnect peer',
    ]
    
    CRITICAL_LOG_KEYWORDS = [
        'out of memory', 'oom_kill', 'kernel panic',
        'filesystem read-only', 'cannot mount',
        'raid.*failed', 'md.*device failed',
        'ext4-fs error', 'xfs.*corruption',
        'lvm activation failed',
        'hardware error', 'mce:',
        'segfault', 'general protection fault'
    ]
    
    WARNING_LOG_KEYWORDS = [
        'i/o error', 'ata error', 'scsi error',
        'task hung', 'blocked for more than',
        'failed to start', 'service.*failed',
        'disk.*offline', 'disk.*removed'
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
        
        try:
            health_persistence.cleanup_old_errors()
        except Exception as e:
            print(f"[HealthMonitor] Cleanup warning: {e}")
    
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
                'uptime': self._format_uptime(uptime_seconds),
                'health': health_status,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'hostname': 'unknown',
                'uptime_seconds': 0,
                'uptime': 'Unknown',
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
        Returns JSON structure with ALL 10 categories always present.
        Now includes persistent error tracking.
        """
        active_errors = health_persistence.get_active_errors()
        persistent_issues = {err['error_key']: err for err in active_errors}
        
        details = {
            'cpu': {'status': 'OK'},
            'memory': {'status': 'OK'},
            'storage': {'status': 'OK'},
            'disks': {'status': 'OK'},
            'network': {'status': 'OK'},
            'vms': {'status': 'OK'},
            'services': {'status': 'OK'},
            'logs': {'status': 'OK'},
            'updates': {'status': 'OK'},
            'security': {'status': 'OK'}
        }
        
        critical_issues = []
        warning_issues = []
        info_issues = []  # Added info_issues to track INFO separately
        
        # Priority 1: Services PVE
        services_status = self._check_pve_services()
        details['services'] = services_status
        if services_status['status'] == 'CRITICAL':
            critical_issues.append(services_status.get('reason', 'Service failure'))
        elif services_status['status'] == 'WARNING':
            warning_issues.append(services_status.get('reason', 'Service issue'))
        
        # Priority 2: Storage
        storage_status = self._check_storage_optimized()
        if storage_status:
            details['storage'] = storage_status
            if storage_status.get('status') == 'CRITICAL':
                critical_issues.append(storage_status.get('reason', 'Storage failure'))
            elif storage_status.get('status') == 'WARNING':
                warning_issues.append(storage_status.get('reason', 'Storage issue'))
        
        # Priority 3: Disks
        disks_status = self._check_disks_optimized()
        if disks_status:
            details['disks'] = disks_status
            if disks_status.get('status') == 'CRITICAL':
                critical_issues.append(disks_status.get('reason', 'Disk failure'))
            elif disks_status.get('status') == 'WARNING':
                warning_issues.append(disks_status.get('reason', 'Disk issue'))
        
        # Priority 4: VMs/CTs - now with persistence
        vms_status = self._check_vms_cts_with_persistence()
        if vms_status:
            details['vms'] = vms_status
            if vms_status.get('status') == 'CRITICAL':
                critical_issues.append(vms_status.get('reason', 'VM/CT failure'))
            elif vms_status.get('status') == 'WARNING':
                warning_issues.append(vms_status.get('reason', 'VM/CT issue'))
        
        # Priority 5: Network
        network_status = self._check_network_optimized()
        if network_status:
            details['network'] = network_status
            if network_status.get('status') == 'CRITICAL':
                critical_issues.append(network_status.get('reason', 'Network failure'))
            elif network_status.get('status') == 'WARNING':
                warning_issues.append(network_status.get('reason', 'Network issue'))
        
        # Priority 6: CPU
        cpu_status = self._check_cpu_with_hysteresis()
        details['cpu'] = cpu_status
        if cpu_status.get('status') == 'WARNING':
            warning_issues.append(cpu_status.get('reason', 'CPU high'))
        elif cpu_status.get('status') == 'CRITICAL':
            critical_issues.append(cpu_status.get('reason', 'CPU critical'))
        
        # Priority 7: Memory
        memory_status = self._check_memory_comprehensive()
        details['memory'] = memory_status
        if memory_status.get('status') == 'CRITICAL':
            critical_issues.append(memory_status.get('reason', 'Memory critical'))
        elif memory_status.get('status') == 'WARNING':
            warning_issues.append(memory_status.get('reason', 'Memory high'))
        
        # Priority 8: Logs - now with persistence
        logs_status = self._check_logs_with_persistence()
        if logs_status:
            details['logs'] = logs_status
            if logs_status.get('status') == 'CRITICAL':
                critical_issues.append(logs_status.get('reason', 'Critical log errors'))
            elif logs_status.get('status') == 'WARNING':
                warning_issues.append(logs_status.get('reason', 'Log warnings'))
        
        # Priority 9: Updates
        updates_status = self._check_updates()
        if updates_status:
            details['updates'] = updates_status
            if updates_status.get('status') == 'WARNING':
                warning_issues.append(updates_status.get('reason', 'Updates pending'))
            elif updates_status.get('status') == 'INFO':
                info_issues.append(updates_status.get('reason', 'Informational update'))
        
        # Priority 10: Security
        security_status = self._check_security()
        details['security'] = security_status
        if security_status.get('status') == 'WARNING':
            warning_issues.append(security_status.get('reason', 'Security issue'))
        elif security_status.get('status') == 'INFO':
            info_issues.append(security_status.get('reason', 'Security info'))
        
        if critical_issues:
            overall = 'CRITICAL'
            summary = '; '.join(critical_issues[:3])
        elif warning_issues:
            overall = 'WARNING'
            summary = '; '.join(warning_issues[:3])
        elif info_issues:
            overall = 'OK'  # INFO is still healthy overall
            summary = '; '.join(info_issues[:3])
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
        """Check CPU with hysteresis to avoid flapping alerts - requires 5min sustained high usage"""
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
                if current_time - entry['time'] < 360
            ]
            
            critical_samples = [
                entry for entry in self.state_history[state_key]
                if entry['value'] >= self.CPU_CRITICAL and
                current_time - entry['time'] <= self.CPU_CRITICAL_DURATION
            ]
            
            warning_samples = [
                entry for entry in self.state_history[state_key]
                if entry['value'] >= self.CPU_WARNING and
                current_time - entry['time'] <= self.CPU_WARNING_DURATION
            ]
            
            recovery_samples = [
                entry for entry in self.state_history[state_key]
                if entry['value'] < self.CPU_RECOVERY and
                current_time - entry['time'] <= self.CPU_RECOVERY_DURATION
            ]
            
            if len(critical_samples) >= 3:
                status = 'CRITICAL'
                reason = f'CPU >{self.CPU_CRITICAL}% sustained for {self.CPU_CRITICAL_DURATION}s'
            elif len(warning_samples) >= 3 and len(recovery_samples) < 2:
                status = 'WARNING'
                reason = f'CPU >{self.CPU_WARNING}% sustained for {self.CPU_WARNING_DURATION}s'
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
        """Check CPU temperature with hysteresis (5 min sustained) - cached, max 1 check per minute"""
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
                    
                    state_key = 'cpu_temp_history'
                    self.state_history[state_key].append({
                        'value': max_temp,
                        'time': current_time
                    })
                    
                    # Keep last 6 minutes of data
                    self.state_history[state_key] = [
                        entry for entry in self.state_history[state_key]
                        if current_time - entry['time'] < 360
                    ]
                    
                    # Check sustained high temperature (5 minutes)
                    critical_temp_samples = [
                        entry for entry in self.state_history[state_key]
                        if entry['value'] >= self.TEMP_CRITICAL and
                        current_time - entry['time'] <= 300
                    ]
                    
                    warning_temp_samples = [
                        entry for entry in self.state_history[state_key]
                        if entry['value'] >= self.TEMP_WARNING and
                        current_time - entry['time'] <= 300
                    ]
                    
                    # Require at least 3 samples over 5 minutes to trigger alert
                    if len(critical_temp_samples) >= 3:
                        status = 'CRITICAL'
                        reason = f'CPU temperature {max_temp}°C ≥{self.TEMP_CRITICAL}°C sustained >5min'
                    elif len(warning_temp_samples) >= 3:
                        status = 'WARNING'
                        reason = f'CPU temperature {max_temp}°C ≥{self.TEMP_WARNING}°C sustained >5min'
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
        """
        Check memory including RAM and swap with realistic thresholds.
        Only alerts on truly problematic memory situations.
        """
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
                if entry['mem_percent'] >= 90 and
                current_time - entry['time'] <= self.MEMORY_DURATION
            )
            
            mem_warning = sum(
                1 for entry in self.state_history[state_key]
                if entry['mem_percent'] >= self.MEMORY_WARNING and
                current_time - entry['time'] <= self.MEMORY_DURATION
            )
            
            swap_critical = sum(
                1 for entry in self.state_history[state_key]
                if entry['swap_vs_ram'] > 20 and
                current_time - entry['time'] <= self.SWAP_CRITICAL_DURATION
            )
            
            
            if mem_critical >= 2:
                status = 'CRITICAL'
                reason = f'RAM >90% for {self.MEMORY_DURATION}s'
            elif swap_critical >= 2:
                status = 'CRITICAL'
                reason = f'Swap >20% of RAM ({swap_vs_ram:.1f}%)'
            elif mem_warning >= 2:
                status = 'WARNING'
                reason = f'RAM >{self.MEMORY_WARNING}% for {self.MEMORY_DURATION}s'
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
    
    def _check_storage_optimized(self) -> Dict[str, Any]:
        """
        Optimized storage check - monitors Proxmox storages from pvesm status.
        Checks for inactive storages, disk health from SMART/events, and ZFS pool health.
        """
        issues = []
        storage_details = {}
        
        try:
            result = subprocess.run(
                ['pvesm', 'status'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 4:
                        storage_name = parts[0]
                        storage_type = parts[1]
                        enabled = parts[2]
                        active = parts[3]
                        
                        if enabled == '1' and active == '0':
                            issues.append(f'{storage_name}: Inactive')
                            storage_details[storage_name] = {
                                'status': 'CRITICAL',
                                'reason': 'Storage inactive',
                                'type': storage_type
                            }
        except Exception as e:
            # If pvesm not available, skip silently
            pass
        
        # Check ZFS pool health status
        zfs_pool_issues = self._check_zfs_pool_health()
        if zfs_pool_issues:
            for pool_name, pool_info in zfs_pool_issues.items():
                issues.append(f'{pool_name}: {pool_info["reason"]}')
                storage_details[pool_name] = pool_info
        
        # Check disk health from Proxmox task log or system logs
        disk_health_issues = self._check_disk_health_from_events()
        if disk_health_issues:
            for disk, issue in disk_health_issues.items():
                issues.append(f'{disk}: {issue["reason"]}')
                storage_details[disk] = issue
        
        critical_mounts = ['/']
        
        for mount_point in critical_mounts:
            try:
                result = subprocess.run(
                    ['mountpoint', '-q', mount_point],
                    capture_output=True,
                    timeout=2
                )
                
                if result.returncode != 0:
                    issues.append(f'{mount_point}: Not mounted')
                    storage_details[mount_point] = {
                        'status': 'CRITICAL',
                        'reason': 'Not mounted'
                    }
                    continue
                
                # Check if read-only
                with open('/proc/mounts', 'r') as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 4 and parts[1] == mount_point:
                            options = parts[3].split(',')
                            if 'ro' in options:
                                issues.append(f'{mount_point}: Mounted read-only')
                                storage_details[mount_point] = {
                                    'status': 'CRITICAL',
                                    'reason': 'Mounted read-only'
                                }
                                break # Found it, no need to check further for this mountpoint
                
                # Check filesystem usage only if not already flagged as critical
                if mount_point not in storage_details or storage_details[mount_point].get('status') == 'OK':
                    fs_status = self._check_filesystem(mount_point)
                    if fs_status['status'] != 'OK':
                        issues.append(f"{mount_point}: {fs_status['reason']}")
                        storage_details[mount_point] = fs_status
            except Exception:
                pass
        
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
    
    def _check_lvm(self) -> Dict[str, Any]:
        """Check LVM volumes - improved detection"""
        try:
            result = subprocess.run(
                ['lvs', '--noheadings', '--options', 'lv_name,vg_name,lv_attr'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode != 0:
                return {'status': 'OK'}
            
            volumes = []
            
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        lv_name = parts[0].strip()
                        vg_name = parts[1].strip()
                        volumes.append(f'{vg_name}/{lv_name}')
            
            return {'status': 'OK', 'volumes': len(volumes)}
            
        except Exception:
            return {'status': 'OK'}
    
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
    
    def _check_disks_optimized(self) -> Dict[str, Any]:
        """
        Optimized disk check - always returns status.
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
            
            if not disk_issues:
                return {'status': 'OK'}
            
            has_critical = any(d.get('status') == 'CRITICAL' for d in disk_issues.values())
            
            return {
                'status': 'CRITICAL' if has_critical else 'WARNING',
                'reason': f"{len(disk_issues)} disk(s) with errors",
                'details': disk_issues
            }
            
        except Exception:
            return {'status': 'OK'}
    
    def _check_network_optimized(self) -> Dict[str, Any]:
        """
        Optimized network check - always returns status.
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
            
            if not issues:
                return {'status': 'OK'}
            
            has_critical = any(d.get('status') == 'CRITICAL' for d in interface_details.values())
            
            return {
                'status': 'CRITICAL' if has_critical else 'WARNING',
                'reason': '; '.join(issues[:2]),
                'details': interface_details
            }
            
        except Exception:
            return {'status': 'OK'}
    
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
    
    def _check_vms_cts_optimized(self) -> Dict[str, Any]:
        """
        Optimized VM/CT check - detects qmp failures and startup errors from logs.
        Improved detection of container and VM errors from journalctl.
        """
        try:
            issues = []
            vm_details = {}
            
            result = subprocess.run(
                ['journalctl', '--since', '10 minutes ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    
                    vm_qmp_match = re.search(r'vm\s+(\d+)\s+qmp\s+command.*(?:failed|unable|timeout)', line_lower)
                    if vm_qmp_match:
                        vmid = vm_qmp_match.group(1)
                        key = f'vm_{vmid}'
                        if key not in vm_details:
                            issues.append(f'VM {vmid}: Communication issue')
                            vm_details[key] = {
                                'status': 'WARNING',
                                'reason': 'QMP command timeout',
                                'id': vmid,
                                'type': 'VM'
                            }
                        continue
                    
                    ct_error_match = re.search(r'(?:ct|container|lxc)\s+(\d+)', line_lower)
                    if ct_error_match and ('error' in line_lower or 'fail' in line_lower or 'device' in line_lower):
                        ctid = ct_error_match.group(1)
                        key = f'ct_{ctid}'
                        if key not in vm_details:
                            if 'device' in line_lower and 'does not exist' in line_lower:
                                device_match = re.search(r'device\s+([/\w\d]+)\s+does not exist', line_lower)
                                if device_match:
                                    reason = f'Device {device_match.group(1)} missing'
                                else:
                                    reason = 'Device error'
                            elif 'failed to start' in line_lower:
                                reason = 'Failed to start'
                            else:
                                reason = 'Container error'
                            
                            issues.append(f'CT {ctid}: {reason}')
                            vm_details[key] = {
                                'status': 'WARNING' if 'device' in reason.lower() else 'CRITICAL',
                                'reason': reason,
                                'id': ctid,
                                'type': 'CT'
                            }
                        continue
                    
                    vzstart_match = re.search(r'vzstart:(\d+):', line)
                    if vzstart_match and ('error' in line_lower or 'fail' in line_lower or 'does not exist' in line_lower):
                        ctid = vzstart_match.group(1)
                        key = f'ct_{ctid}'
                        if key not in vm_details:
                            # Extraer mensaje de error
                            if 'device' in line_lower and 'does not exist' in line_lower:
                                device_match = re.search(r'device\s+([/\w\d]+)\s+does not exist', line_lower)
                                if device_match:
                                    reason = f'Device {device_match.group(1)} missing'
                                else:
                                    reason = 'Device error'
                            else:
                                reason = 'Startup error'
                            
                            issues.append(f'CT {ctid}: {reason}')
                            vm_details[key] = {
                                'status': 'WARNING',
                                'reason': reason,
                                'id': ctid,
                                'type': 'CT'
                            }
                        continue
                    
                    if any(keyword in line_lower for keyword in ['failed to start', 'cannot start', 'activation failed', 'start error']):
                        id_match = re.search(r'\b(\d{3,4})\b', line)
                        if id_match:
                            vmid = id_match.group(1)
                            key = f'vmct_{vmid}'
                            if key not in vm_details:
                                issues.append(f'VM/CT {vmid}: Failed to start')
                                vm_details[key] = {
                                    'status': 'CRITICAL',
                                    'reason': 'Failed to start',
                                    'id': vmid,
                                    'type': 'VM/CT'
                                }
            
            if not issues:
                return {'status': 'OK'}
            
            has_critical = any(d.get('status') == 'CRITICAL' for d in vm_details.values())
            
            return {
                'status': 'CRITICAL' if has_critical else 'WARNING',
                'reason': '; '.join(issues[:3]),
                'details': vm_details
            }
            
        except Exception:
            return {'status': 'OK'}
    
    # Modified to use persistence
    def _check_vms_cts_with_persistence(self) -> Dict[str, Any]:
        """
        Check VMs/CTs with persistent error tracking.
        Errors persist until VM starts or 48h elapsed.
        """
        try:
            issues = []
            vm_details = {}
            
            # Get persistent errors first
            persistent_errors = health_persistence.get_active_errors('vms')
            
            # Check if any persistent VMs/CTs have started
            for error in persistent_errors:
                error_key = error['error_key']
                if error_key.startswith('vm_') or error_key.startswith('ct_'):
                    vm_id = error_key.split('_')[1]
                    if health_persistence.check_vm_running(vm_id):
                        continue  # Error auto-resolved
                
                # Still active
                vm_details[error_key] = {
                    'status': error['severity'],
                    'reason': error['reason'],
                    'id': error.get('details', {}).get('id', 'unknown'),
                    'type': error.get('details', {}).get('type', 'VM/CT'),
                    'first_seen': error['first_seen']
                }
                issues.append(f"{error.get('details', {}).get('type', 'VM')} {error.get('details', {}).get('id', '')}: {error['reason']}")
            
            # Check for new errors in logs
            result = subprocess.run(
                ['journalctl', '--since', '10 minutes ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    
                    # VM QMP errors
                    vm_qmp_match = re.search(r'vm\s+(\d+)\s+qmp\s+command.*(?:failed|unable|timeout)', line_lower)
                    if vm_qmp_match:
                        vmid = vm_qmp_match.group(1)
                        error_key = f'vm_{vmid}'
                        if error_key not in vm_details:
                            # Record persistent error
                            health_persistence.record_error(
                                error_key=error_key,
                                category='vms',
                                severity='WARNING',
                                reason='QMP command timeout',
                                details={'id': vmid, 'type': 'VM'}
                            )
                            issues.append(f'VM {vmid}: Communication issue')
                            vm_details[error_key] = {
                                'status': 'WARNING',
                                'reason': 'QMP command timeout',
                                'id': vmid,
                                'type': 'VM'
                            }
                        continue
                    
                    # Container errors
                    vzstart_match = re.search(r'vzstart:(\d+):', line)
                    if vzstart_match and ('error' in line_lower or 'fail' in line_lower or 'does not exist' in line_lower):
                        ctid = vzstart_match.group(1)
                        error_key = f'ct_{ctid}'
                        
                        if error_key not in vm_details:
                            if 'device' in line_lower and 'does not exist' in line_lower:
                                device_match = re.search(r'device\s+([/\w\d]+)\s+does not exist', line_lower)
                                if device_match:
                                    reason = f'Device {device_match.group(1)} missing'
                                else:
                                    reason = 'Device error'
                            else:
                                reason = 'Startup error'
                            
                            # Record persistent error
                            health_persistence.record_error(
                                error_key=error_key,
                                category='vms',
                                severity='WARNING',
                                reason=reason,
                                details={'id': ctid, 'type': 'CT'}
                            )
                            issues.append(f'CT {ctid}: {reason}')
                            vm_details[error_key] = {
                                'status': 'WARNING',
                                'reason': reason,
                                'id': ctid,
                                'type': 'CT'
                            }
            
            if not issues:
                return {'status': 'OK'}
            
            has_critical = any(d.get('status') == 'CRITICAL' for d in vm_details.values())
            
            return {
                'status': 'CRITICAL' if has_critical else 'WARNING',
                'reason': '; '.join(issues[:3]),
                'details': vm_details
            }
            
        except Exception:
            return {'status': 'OK'}
    
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
    
    def _is_benign_error(self, line: str) -> bool:
        """Check if log line matches benign error patterns"""
        line_lower = line.lower()
        for pattern in self.BENIGN_ERROR_PATTERNS:
            if re.search(pattern, line_lower):
                return True
        return False
    
    def _classify_log_severity(self, line: str) -> Optional[str]:
        """
        Classify log line severity intelligently.
        Returns: 'CRITICAL', 'WARNING', or None (benign)
        """
        line_lower = line.lower()
        
        # Check if benign first
        if self._is_benign_error(line):
            return None
        
        # Check critical keywords
        for keyword in self.CRITICAL_LOG_KEYWORDS:
            if re.search(keyword, line_lower):
                return 'CRITICAL'
        
        # Check warning keywords
        for keyword in self.WARNING_LOG_KEYWORDS:
            if re.search(keyword, line_lower):
                return 'WARNING'
        
        # Generic error/warning classification
        if 'critical' in line_lower or 'fatal' in line_lower:
            return 'CRITICAL'
        elif 'error' in line_lower:
            return 'WARNING'
        elif 'warning' in line_lower or 'warn' in line_lower:
            return None  # Generic warnings are benign
        
        return None

    def _check_logs_with_persistence(self) -> Dict[str, Any]:
        """
        Intelligent log checking with cascade detection.
        Only alerts when there's a real problem (error cascade), not normal background warnings.
        
        Logic:
        - Looks at last 3 minutes (not 10) for immediate issues
        - Detects cascades: ≥5 errors of same type in 3 min = problem
        - Compares to previous period to detect spikes
        - Whitelists known benign Proxmox warnings
        """
        cache_key = 'logs_analysis'
        current_time = time.time()
        
        # Cache for 5 minutes
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < self.LOG_CHECK_INTERVAL:
                persistent_errors = health_persistence.get_active_errors('logs')
                if persistent_errors:
                    return {
                        'status': 'WARNING',
                        'reason': f'{len(persistent_errors)} persistent log issues'
                    }
                return self.cached_results.get(cache_key, {'status': 'OK'})
        
        try:
            result_recent = subprocess.run(
                ['journalctl', '--since', '3 minutes ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            result_previous = subprocess.run(
                ['journalctl', '--since', '6 minutes ago', '--until', '3 minutes ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result_recent.returncode == 0:
                recent_lines = result_recent.stdout.strip().split('\n')
                previous_lines = result_previous.stdout.strip().split('\n') if result_previous.returncode == 0 else []
                
                recent_patterns = defaultdict(int)
                previous_patterns = defaultdict(int)
                critical_errors = {}
                
                for line in recent_lines:
                    if not line.strip():
                        continue
                    
                    # Skip benign errors
                    if self._is_benign_error(line):
                        continue
                    
                    # Classify severity
                    severity = self._classify_log_severity(line)
                    
                    if severity is None:
                        continue
                    
                    # Normalize to pattern
                    pattern = self._normalize_log_pattern(line)
                    
                    if severity == 'CRITICAL':
                        if pattern not in critical_errors:
                            critical_errors[pattern] = line
                            
                            # Record persistent error
                            error_key = f'log_critical_{abs(hash(pattern)) % 10000}'
                            health_persistence.record_error(
                                error_key=error_key,
                                category='logs',
                                severity='CRITICAL',
                                reason=line[:100],
                                details={'pattern': pattern}
                            )
                    
                    recent_patterns[pattern] += 1
                
                for line in previous_lines:
                    if not line.strip() or self._is_benign_error(line):
                        continue
                    
                    severity = self._classify_log_severity(line)
                    if severity is None:
                        continue
                    
                    pattern = self._normalize_log_pattern(line)
                    previous_patterns[pattern] += 1
                
                cascading_errors = {
                    pattern: count for pattern, count in recent_patterns.items()
                    if count >= 10 and self._classify_log_severity(pattern) in ['WARNING', 'CRITICAL']
                }
                
                spike_errors = {}
                for pattern, recent_count in recent_patterns.items():
                    prev_count = previous_patterns.get(pattern, 0)
                    # Spike if: ≥3 errors now AND ≥3x increase
                    if recent_count >= 3 and recent_count >= prev_count * 3:
                        spike_errors[pattern] = recent_count
                
                unique_critical = len(critical_errors)
                cascade_count = len(cascading_errors)
                spike_count = len(spike_errors)
                
                if unique_critical > 0:
                    status = 'CRITICAL'
                    reason = f'{unique_critical} critical error(s): cascade detected'
                elif cascade_count > 0:
                    status = 'WARNING'
                    reason = f'Error cascade detected: {cascade_count} pattern(s) repeating ≥10 times in 3min'
                elif spike_count > 0:
                    status = 'WARNING'
                    reason = f'Error spike detected: {spike_count} pattern(s) increased 3x'
                else:
                    # Normal background warnings, no alert
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
    
    def _normalize_log_pattern(self, line: str) -> str:
        """
        Normalize log line to a pattern for grouping similar errors.
        Removes timestamps, PIDs, IDs, paths, and other variables.
        """
        pattern = re.sub(r'\d{4}-\d{2}-\d{2}', '', line)  # Remove dates
        pattern = re.sub(r'\d{2}:\d{2}:\d{2}', '', pattern)  # Remove times
        pattern = re.sub(r'pid[:\s]+\d+', 'pid:XXX', pattern.lower())  # Normalize PIDs
        pattern = re.sub(r'\b\d{3,6}\b', 'ID', pattern)  # Normalize IDs
        pattern = re.sub(r'/dev/\S+', '/dev/XXX', pattern)  # Normalize devices
        pattern = re.sub(r'/\S+/\S+', '/PATH/', pattern)  # Normalize paths
        pattern = re.sub(r'0x[0-9a-f]+', '0xXXX', pattern)  # Normalize hex
        pattern = re.sub(r'\s+', ' ', pattern).strip()  # Normalize whitespace
        return pattern[:150]  # Keep first 150 chars
    
    def _check_updates(self) -> Optional[Dict[str, Any]]:
        """
        Check for pending system updates with intelligence.
        Now only warns after 365 days without updates.
        Critical security updates and kernel updates trigger INFO status immediately.
        """
        cache_key = 'updates_check'
        current_time = time.time()
        
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 600:
                return self.cached_results.get(cache_key)
        
        try:
            apt_history_path = '/var/log/apt/history.log'
            last_update_days = None
            
            if os.path.exists(apt_history_path):
                try:
                    mtime = os.path.getmtime(apt_history_path)
                    days_since_update = (current_time - mtime) / 86400
                    last_update_days = int(days_since_update)
                except Exception:
                    pass
            
            result = subprocess.run(
                ['apt-get', 'upgrade', '--dry-run'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                
                # Count total updates
                update_count = 0
                security_updates = []
                kernel_updates = []
                
                for line in lines:
                    if line.startswith('Inst '):
                        update_count += 1
                        line_lower = line.lower()
                        
                        # Check for security updates
                        if 'security' in line_lower or 'debian-security' in line_lower:
                            package_name = line.split()[1]
                            security_updates.append(package_name)
                        
                        # Check for kernel or critical PVE updates
                        if any(pkg in line_lower for pkg in ['linux-image', 'pve-kernel', 'pve-manager', 'proxmox-ve']):
                            package_name = line.split()[1]
                            kernel_updates.append(package_name)
                
                if security_updates:
                    status = 'WARNING'
                    reason = f'{len(security_updates)} security update(s) available'
                    # Record persistent error for security updates
                    health_persistence.record_error(
                        error_key='updates_security',
                        category='updates',
                        severity='WARNING',
                        reason=reason,
                        details={'count': len(security_updates), 'packages': security_updates[:5]}
                    )
                elif last_update_days and last_update_days >= 730:
                    # 2+ years without updates - CRITICAL
                    status = 'CRITICAL'
                    reason = f'System not updated in {last_update_days} days (>2 years)'
                    health_persistence.record_error(
                        error_key='updates_730days',
                        category='updates',
                        severity='CRITICAL',
                        reason=reason,
                        details={'days': last_update_days, 'update_count': update_count}
                    )
                elif last_update_days and last_update_days >= 365:
                    # 1+ year without updates - WARNING
                    status = 'WARNING'
                    reason = f'System not updated in {last_update_days} days (>1 year)'
                    health_persistence.record_error(
                        error_key='updates_365days',
                        category='updates',
                        severity='WARNING',
                        reason=reason,
                        details={'days': last_update_days, 'update_count': update_count}
                    )
                elif kernel_updates:
                    status = 'INFO'
                    reason = f'{len(kernel_updates)} kernel/PVE update(s) available'
                elif update_count > 50:
                    status = 'INFO'
                    reason = f'{update_count} updates pending (consider maintenance window)'
                else:
                    status = 'OK'
                    reason = None
                
                update_result = {
                    'status': status,
                    'count': update_count
                }
                if reason:
                    update_result['reason'] = reason
                if last_update_days:
                    update_result['days_since_update'] = last_update_days
                
                self.cached_results[cache_key] = update_result
                self.last_check_times[cache_key] = current_time
                return update_result
            
            return {'status': 'OK', 'count': 0}
            
        except Exception as e:
            return {'status': 'OK', 'count': 0}
    
    def _check_security(self) -> Dict[str, Any]:
        """
        Check security-related items:
        - SSL certificate validity and expiration
        - Failed login attempts
        - Excessive uptime (>365 days = kernel vulnerabilities)
        """
        try:
            issues = []
            
            try:
                uptime_seconds = time.time() - psutil.boot_time()
                uptime_days = uptime_seconds / 86400
                
                if uptime_days > 365:
                    issues.append(f'Uptime {int(uptime_days)} days (>1 year, kernel updates needed)')
            except Exception:
                pass
            
            cert_status = self._check_certificates()
            if cert_status and cert_status.get('status') not in ['OK', 'INFO']:
                issues.append(cert_status.get('reason', 'Certificate issue'))
            
            try:
                result = subprocess.run(
                    ['journalctl', '--since', '24 hours ago', '--no-pager'],
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                
                if result.returncode == 0:
                    failed_logins = 0
                    for line in result.stdout.split('\n'):
                        if 'authentication failure' in line.lower() or 'failed password' in line.lower():
                            failed_logins += 1
                    
                    if failed_logins > 50:
                        issues.append(f'{failed_logins} failed login attempts in 24h')
            except Exception:
                pass
            
            if issues:
                return {
                    'status': 'WARNING',
                    'reason': '; '.join(issues[:2])
                }
            
            return {'status': 'OK'}
            
        except Exception:
            return {'status': 'OK'}
    
    def _check_certificates(self) -> Optional[Dict[str, Any]]:
        """
        Check SSL certificate expiration.
        INFO: Self-signed or no cert configured (normal for internal servers)
        WARNING: Expires <30 days
        CRITICAL: Expired
        """
        cache_key = 'certificates'
        current_time = time.time()
        
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 86400:
                return self.cached_results.get(cache_key)
        
        try:
            cert_path = '/etc/pve/local/pve-ssl.pem'
            
            if not os.path.exists(cert_path):
                cert_result = {
                    'status': 'INFO',
                    'reason': 'Self-signed or default certificate'
                }
                self.cached_results[cache_key] = cert_result
                self.last_check_times[cache_key] = current_time
                return cert_result
            
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
                    elif days_until_expiry < 30:
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
            
            return {'status': 'INFO', 'reason': 'Certificate check inconclusive'}
            
        except Exception:
            return {'status': 'OK'}
    
    def _check_disk_health_from_events(self) -> Dict[str, Any]:
        """
        Check for disk health warnings from Proxmox task log and system logs.
        Returns dict of disk issues found.
        """
        disk_issues = {}
        
        try:
            result = subprocess.run(
                ['journalctl', '--since', '1 hour ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    
                    # Check for SMART warnings
                    if 'smart' in line_lower and ('warning' in line_lower or 'error' in line_lower or 'fail' in line_lower):
                        # Extract disk name
                        disk_match = re.search(r'/dev/(sd[a-z]|nvme\d+n\d+)', line)
                        if disk_match:
                            disk_name = disk_match.group(1)
                            disk_issues[f'/dev/{disk_name}'] = {
                                'status': 'WARNING',
                                'reason': 'SMART warning detected'
                            }
                    
                    # Check for disk errors
                    if any(keyword in line_lower for keyword in ['disk error', 'ata error', 'medium error']):
                        disk_match = re.search(r'/dev/(sd[a-z]|nvme\d+n\d+)', line)
                        if disk_match:
                            disk_name = disk_match.group(1)
                            disk_issues[f'/dev/{disk_name}'] = {
                                'status': 'CRITICAL',
                                'reason': 'Disk error detected'
                            }
        except Exception:
            pass
        
        return disk_issues
    
    def _check_zfs_pool_health(self) -> Dict[str, Any]:
        """
        Check ZFS pool health status using zpool status command.
        Returns dict of pools with non-ONLINE status (DEGRADED, FAULTED, UNAVAIL, etc.)
        """
        zfs_issues = {}
        
        try:
            # First check if zpool command exists
            result = subprocess.run(
                ['which', 'zpool'],
                capture_output=True,
                text=True,
                timeout=1
            )
            
            if result.returncode != 0:
                # ZFS not installed, return empty
                return zfs_issues
            
            # Get list of all pools
            result = subprocess.run(
                ['zpool', 'list', '-H', '-o', 'name,health'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if not line.strip():
                        continue
                    
                    parts = line.split()
                    if len(parts) >= 2:
                        pool_name = parts[0]
                        pool_health = parts[1].upper()
                        
                        # ONLINE is healthy, anything else is a problem
                        if pool_health != 'ONLINE':
                            if pool_health in ['DEGRADED', 'FAULTED', 'UNAVAIL', 'REMOVED']:
                                status = 'CRITICAL'
                                reason = f'ZFS pool {pool_health.lower()}'
                            else:
                                # Any other non-ONLINE state is at least a warning
                                status = 'WARNING'
                                reason = f'ZFS pool status: {pool_health.lower()}'
                            
                            zfs_issues[f'zpool_{pool_name}'] = {
                                'status': status,
                                'reason': reason,
                                'pool_name': pool_name,
                                'health': pool_health
                            }
        except Exception:
            # If zpool command fails, silently ignore
            pass
        
        return zfs_issues


# Global instance
health_monitor = HealthMonitor()
