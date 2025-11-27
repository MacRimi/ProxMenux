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

try:
    from proxmox_storage_monitor import proxmox_storage_monitor
    PROXMOX_STORAGE_AVAILABLE = True
except ImportError:
    PROXMOX_STORAGE_AVAILABLE = False

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
        
        # Priority 1.5: Proxmox Storage Check (uses external monitor)
        proxmox_storage_result = self._check_proxmox_storage()
        if proxmox_storage_result:
            details['storage'] = proxmox_storage_result
            if proxmox_storage_result.get('status') == 'CRITICAL':
                critical_issues.append(proxmox_storage_result.get('reason', 'Proxmox storage unavailable'))
            elif proxmox_storage_result.get('status') == 'WARNING':
                warning_issues.append(proxmox_storage_result.get('reason', 'Proxmox storage issue'))
        
        # Priority 2: Storage (filesystem usage, ZFS, SMART etc.)
        storage_status = self._check_storage_optimized()
        if storage_status:
            details['disks'] = storage_status # Rename from 'storage' to 'disks' for clarity
            if storage_status.get('status') == 'CRITICAL':
                critical_issues.append(storage_status.get('reason', 'Disk/Storage failure'))
            elif storage_status.get('status') == 'WARNING':
                warning_issues.append(storage_status.get('reason', 'Disk/Storage issue'))
        
        # Priority 3: Disks (redundant with storage_optimized, but keeping for now)
        # disks_status = self._check_disks_optimized() # This is now covered by _check_storage_optimized
        # if disks_status:
        #     details['disks'] = disks_status
        #     if disks_status.get('status') == 'CRITICAL':
        #         critical_issues.append(disks_status.get('reason', 'Disk failure'))
        #     elif disks_status.get('status') == 'WARNING':
        #         warning_issues.append(disks_status.get('reason', 'Disk issue'))
        
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
        
        # Check disk usage and mount status first for critical mounts
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
                pass # Silently skip if mountpoint check fails
        
        # Check ZFS pool health status
        zfs_pool_issues = self._check_zfs_pool_health()
        if zfs_pool_issues:
            for pool_name, pool_info in zfs_pool_issues.items():
                issues.append(f'{pool_name}: {pool_info["reason"]}')
                storage_details[pool_name] = pool_info
        
        # Check disk health from Proxmox task log or system logs (SMART, etc.)
        disk_health_issues = self._check_disk_health_from_events()
        if disk_health_issues:
            for disk, issue in disk_health_issues.items():
                # Only add if not already covered by critical mountpoint issues
                if disk not in storage_details or storage_details[disk].get('status') == 'OK':
                    issues.append(f'{disk}: {issue["reason"]}')
                    storage_details[disk] = issue
        
        # Check LVM status
        lvm_status = self._check_lvm()
        if lvm_status.get('status') == 'WARNING':
            # LVM volumes might be okay but indicate potential issues
            issues.append(f"LVM check: {lvm_status.get('reason')}")
            storage_details['lvm_check'] = lvm_status
        
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
            # Check if lvs command is available
            result_which = subprocess.run(
                ['which', 'lvs'],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result_which.returncode != 0:
                return {'status': 'OK'} # LVM not installed

            result = subprocess.run(
                ['lvs', '--noheadings', '--options', 'lv_name,vg_name,lv_attr'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode != 0:
                return {'status': 'WARNING', 'reason': 'lvs command failed'}
            
            volumes = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        lv_name = parts[0].strip()
                        vg_name = parts[1].strip()
                        # Check for 'a' attribute indicating active/available
                        if 'a' in parts[2]:
                            volumes.append(f'{vg_name}/{lv_name}')
            
            # If LVM is configured but no active volumes are found, it might be an issue or just not used
            if not volumes:
                # Check if any VGs exist to determine if LVM is truly unconfigured or just inactive
                vg_result = subprocess.run(
                    ['vgs', '--noheadings', '--options', 'vg_name'],
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                if vg_result.returncode == 0 and vg_result.stdout.strip():
                    return {'status': 'WARNING', 'reason': 'No active LVM volumes detected'}
                else:
                    return {'status': 'OK'} # No VGs found, LVM not in use
            
            return {'status': 'OK', 'volumes': len(volumes)}
            
        except Exception:
            return {'status': 'OK'}
    
    # This function is no longer used in get_detailed_status, but kept for reference if needed.
    # The new _check_proxmox_storage function handles this logic better.
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
                           line.startswith('cifs:') or line.startswith('pbs:') or \
                           line.startswith('rbd:') or line.startswith('cephfs:') or \
                           line.startswith('zfs:') or line.startswith('zfs-send:'):
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
        Checks dmesg for I/O errors and SMART status.
        NOTE: This function is now largely covered by _check_storage_optimized,
              but kept for potential specific disk-level reporting if needed.
              Currently, its primary function is to detect recent I/O errors.
        """
        current_time = time.time()
        disk_issues = {}
        
        try:
            # Check dmesg for I/O errors in the last 5 minutes
            result = subprocess.run(
                ['dmesg', '-T', '--level=err,warn', '--since', '5 minutes ago'],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    if any(keyword in line_lower for keyword in ['i/o error', 'ata error', 'scsi error', 'medium error']):
                        # Try to extract disk name
                        disk_match = re.search(r'/dev/(sd[a-z]|nvme\d+n\d+)', line)
                        if disk_match:
                            disk_name = disk_match.group(1)
                            self.io_error_history[disk_name].append(current_time)
                
                # Clean old history (keep errors from last 5 minutes)
                for disk in list(self.io_error_history.keys()):
                    self.io_error_history[disk] = [
                        t for t in self.io_error_history[disk]
                        if current_time - t < 300
                    ]
                    
                    error_count = len(self.io_error_history[disk])
                    
                    # Report based on recent error count
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
                'reason': f"{len(disk_issues)} disk(s) with recent errors",
                'details': disk_issues
            }
            
        except Exception:
            # If dmesg check fails, return OK as it's not a critical system failure
            return {'status': 'OK'}
    
    def _check_network_optimized(self) -> Dict[str, Any]:
        """
        Optimized network check - always returns status.
        Checks interface status and basic latency.
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
                    # Consider common PVE bridge interfaces and physical NICs as important
                    if interface.startswith('vmbr') or interface.startswith('eth') or interface.startswith('ens') or interface.startswith('enp'):
                        issues.append(f'{interface} is DOWN')
                        interface_details[interface] = {
                            'status': 'CRITICAL',
                            'reason': 'Interface DOWN'
                        }
            
            # Check connectivity (latency)
            latency_status = self._check_network_latency()
            if latency_status and latency_status.get('status') not in ['OK', 'INFO', 'UNKNOWN']:
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
            
            # If ping failed (timeout, unreachable)
            packet_loss_result = {
                'status': 'CRITICAL',
                'reason': 'Packet loss or timeout to 1.1.1.1'
            }
            self.cached_results[cache_key] = packet_loss_result
            self.last_check_times[cache_key] = current_time
            return packet_loss_result
            
        except Exception:
            return {'status': 'UNKNOWN', 'reason': 'Ping command failed'}
    
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
                    # Check if VM is running using persistence helper
                    if health_persistence.check_vm_running(vm_id):
                        continue  # Error auto-resolved if VM is now running
                
                # Still active, add to details
                vm_details[error_key] = {
                    'status': error['severity'],
                    'reason': error['reason'],
                    'id': error.get('details', {}).get('id', 'unknown'),
                    'type': error.get('details', {}).get('type', 'VM/CT'),
                    'first_seen': error['first_seen']
                }
                issues.append(f"{error.get('details', {}).get('type', 'VM')} {error.get('details', {}).get('id', '')}: {error['reason']}")
            
            # Check for new errors in logs
            # Using 'warning' priority to catch potential startup issues
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
                    
                    # Container errors (including startup issues via vzstart)
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
                    
                    # Generic failed to start for VMs and CTs
                    if any(keyword in line_lower for keyword in ['failed to start', 'cannot start', 'activation failed', 'start error']):
                        id_match = re.search(r'\b(\d{3,5})\b', line) # Increased digit count for wider match
                        if id_match:
                            vmid_ctid = id_match.group(1)
                            # Determine if it's a VM or CT based on context, if possible
                            if 'vm' in line_lower or 'qemu' in line_lower:
                                error_key = f'vm_{vmid_ctid}'
                                vm_type = 'VM'
                            elif 'ct' in line_lower or 'lxc' in line_lower:
                                error_key = f'ct_{vmid_ctid}'
                                vm_type = 'CT'
                            else:
                                # Fallback if type is unclear
                                error_key = f'vmct_{vmid_ctid}'
                                vm_type = 'VM/CT'
                            
                            if error_key not in vm_details:
                                reason = 'Failed to start'
                                # Record persistent error
                                health_persistence.record_error(
                                    error_key=error_key,
                                    category='vms',
                                    severity='CRITICAL',
                                    reason=reason,
                                    details={'id': vmid_ctid, 'type': vm_type}
                                )
                                issues.append(f'{vm_type} {vmid_ctid}: {reason}')
                                vm_details[error_key] = {
                                    'status': 'CRITICAL',
                                    'reason': reason,
                                    'id': vmid_ctid,
                                    'type': vm_type
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
                    # If systemctl fails (e.g., command not found or service doesn't exist), treat as failed
                    failed_services.append(service)
            
            if failed_services:
                return {
                    'status': 'CRITICAL',
                    'reason': f'Services inactive: {", ".join(failed_services)}',
                    'failed': failed_services
                }
            
            return {'status': 'OK'}
            
        except Exception as e:
            # If the entire systemctl check fails
            return {
                'status': 'WARNING',
                'reason': f'Service check command failed: {str(e)}'
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
        Returns: 'CRITICAL', 'WARNING', or None (benign/info)
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
        
        # Generic error/warning classification based on common terms
        if 'critical' in line_lower or 'fatal' in line_lower or 'panic' in line_lower:
            return 'CRITICAL'
        elif 'error' in line_lower or 'fail' in line_lower:
            return 'WARNING'
        elif 'warning' in line_lower or 'warn' in line_lower:
            return None  # Generic warnings are often informational and not critical
        
        return None

    def _check_logs_with_persistence(self) -> Dict[str, Any]:
        """
        Intelligent log checking with cascade detection and persistence.
        Focuses on detecting significant error patterns rather than transient warnings.
        """
        cache_key = 'logs_analysis'
        current_time = time.time()
        
        # Cache the result for 5 minutes to avoid excessive journalctl calls
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < self.LOG_CHECK_INTERVAL:
                # Check persistent log errors recorded by health_persistence
                persistent_errors = health_persistence.get_active_errors('logs')
                if persistent_errors:
                    return {
                        'status': 'WARNING', # Or CRITICAL depending on severity of persistent errors
                        'reason': f'{len(persistent_errors)} persistent log issues detected'
                    }
                return self.cached_results.get(cache_key, {'status': 'OK'})
        
        try:
            # Fetch logs from the last 3 minutes for immediate issue detection
            result_recent = subprocess.run(
                ['journalctl', '--since', '3 minutes ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            # Fetch logs from the previous 3-minute interval to detect spikes/cascades
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
                critical_errors_found = {} # To store unique critical error lines for persistence
                
                for line in recent_lines:
                    if not line.strip():
                        continue
                    
                    # Skip benign errors
                    if self._is_benign_error(line):
                        continue
                    
                    # Classify severity
                    severity = self._classify_log_severity(line)
                    
                    if severity is None: # Skip informational or classified benign lines
                        continue
                    
                    # Normalize to a pattern for grouping
                    pattern = self._normalize_log_pattern(line)
                    
                    if severity == 'CRITICAL':
                        # If this critical pattern is new or we haven't logged it recently
                        error_key = f'log_critical_{abs(hash(pattern)) % 10000}'
                        if pattern not in critical_errors_found:
                            critical_errors_found[pattern] = line
                            # Record persistent error if it's not already active and within recent persistence
                            if not health_persistence.is_error_active(error_key, category='logs'):
                                health_persistence.record_error(
                                    error_key=error_key,
                                    category='logs',
                                    severity='CRITICAL',
                                    reason=line[:100], # Truncate reason for brevity
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
                
                # Detect cascades: ≥10 errors of same type in 3 min
                cascading_errors = {
                    pattern: count for pattern, count in recent_patterns.items()
                    if count >= 10 and self._classify_log_severity(pattern) in ['WARNING', 'CRITICAL']
                }
                
                # Detect spikes: ≥3 errors now AND ≥3x increase from previous period
                spike_errors = {}
                for pattern, recent_count in recent_patterns.items():
                    prev_count = previous_patterns.get(pattern, 0)
                    if recent_count >= 3 and recent_count >= prev_count * 3:
                        spike_errors[pattern] = recent_count
                
                unique_critical_count = len(critical_errors_found)
                cascade_count = len(cascading_errors)
                spike_count = len(spike_errors)
                
                if unique_critical_count > 0:
                    status = 'CRITICAL'
                    # Get a representative critical error reason
                    representative_error = next(iter(critical_errors_found.values()))
                    reason = f'Critical error detected: {representative_error[:100]}'
                elif cascade_count > 0:
                    status = 'WARNING'
                    reason = f'Error cascade detected: {cascade_count} pattern(s) repeating ≥10 times in 3min'
                elif spike_count > 0:
                    status = 'WARNING'
                    reason = f'Error spike detected: {spike_count} pattern(s) increased 3x'
                else:
                    # No significant issues found
                    status = 'OK'
                    reason = None
                
                log_result = {'status': status}
                if reason:
                    log_result['reason'] = reason
                
                self.cached_results[cache_key] = log_result
                self.last_check_times[cache_key] = current_time
                return log_result
            
            # If journalctl command failed or returned no data
            ok_result = {'status': 'OK'}
            self.cached_results[cache_key] = ok_result
            self.last_check_times[cache_key] = current_time
            return ok_result
            
        except Exception as e:
            # Log the exception but return OK to avoid alert storms on check failure
            print(f"[HealthMonitor] Error checking logs: {e}")
            return {'status': 'OK'}
    
    def _normalize_log_pattern(self, line: str) -> str:
        """
        Normalize log line to a pattern for grouping similar errors.
        Removes timestamps, PIDs, IDs, paths, and other variables.
        """
        # Remove standard syslog timestamp and process info if present
        pattern = re.sub(r'^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+(\s+\[\d+\])?:\s+', '', line)
        
        pattern = re.sub(r'\d{4}-\d{2}-\d{2}', '', pattern)  # Remove dates
        pattern = re.sub(r'\d{2}:\d{2}:\d{2}', '', pattern)  # Remove times
        pattern = re.sub(r'pid[:\s]+\d+', 'pid:XXX', pattern.lower())  # Normalize PIDs
        pattern = re.sub(r'\b\d{3,6}\b', 'ID', pattern)  # Normalize IDs (common for container/VM IDs)
        pattern = re.sub(r'/dev/\S+', '/dev/XXX', pattern)  # Normalize device paths
        pattern = re.sub(r'/\S+/\S+', '/PATH/', pattern)  # Normalize general paths
        pattern = re.sub(r'0x[0-9a-f]+', '0xXXX', pattern)  # Normalize hex values
        pattern = re.sub(r'\b(uuid|guid|hash)[:=]\s*[\w-]+\b', r'\1=XXX', pattern.lower()) # Normalize UUIDs/GUIDs
        pattern = re.sub(r'\s+', ' ', pattern).strip()  # Normalize whitespace
        
        return pattern[:150]  # Keep first 150 characters to avoid overly long patterns
    
    def _check_updates(self) -> Optional[Dict[str, Any]]:
        """
        Check for pending system updates.
        - WARNING: If security updates are available.
        - CRITICAL: If system not updated in >2 years.
        - INFO: If 1-2 years without updates, or many non-security updates.
        """
        cache_key = 'updates_check'
        current_time = time.time()
        
        # Cache for 10 minutes
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
                    pass # Ignore if mtime fails
            
            # Perform a dry run of apt-get upgrade to see pending packages
            result = subprocess.run(
                ['apt-get', 'upgrade', '--dry-run'],
                capture_output=True,
                text=True,
                timeout=5 # Increased timeout for safety
            )
            
            status = 'OK'
            reason = None
            update_count = 0
            security_updates_packages = []
            kernel_pve_updates_packages = []
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                
                for line in lines:
                    # 'Inst' indicates a package will be installed/upgraded
                    if line.startswith('Inst '):
                        update_count += 1
                        line_lower = line.lower()
                        package_name = line.split()[1].split(':')[0] # Get package name, strip arch if present
                        
                        # Check for security updates (common pattern in repo names)
                        if 'security' in line_lower or 'debian-security' in line_lower:
                            security_updates_packages.append(package_name)
                        
                        # Check for kernel or critical PVE updates
                        if any(pkg in line_lower for pkg in ['linux-image', 'pve-kernel', 'pve-manager', 'proxmox-ve', 'qemu-server', 'pve-api-core']):
                            kernel_pve_updates_packages.append(package_name)
                
                # Determine overall status based on findings
                if security_updates_packages:
                    status = 'WARNING'
                    reason = f'{len(security_updates_packages)} security update(s) available'
                    # Record persistent error for security updates to ensure it's visible
                    health_persistence.record_error(
                        error_key='updates_security',
                        category='updates',
                        severity='WARNING',
                        reason=reason,
                        details={'count': len(security_updates_packages), 'packages': security_updates_packages[:5]}
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
                elif kernel_pve_updates_packages:
                    # Informational: Kernel or critical PVE components need update
                    status = 'INFO'
                    reason = f'{len(kernel_pve_updates_packages)} kernel/PVE update(s) available'
                elif update_count > 50:
                    # Informational: Large number of pending updates
                    status = 'INFO'
                    reason = f'{update_count} updates pending (consider maintenance window)'
            
            # If apt-get upgrade --dry-run failed
            elif result.returncode != 0:
                status = 'WARNING'
                reason = 'Failed to check for updates (apt-get error)'

            # Construct result dictionary
            update_result = {
                'status': status,
                'count': update_count
            }
            if reason:
                update_result['reason'] = reason
            if last_update_days is not None: # Only add if we could determine days_since_update
                update_result['days_since_update'] = last_update_days
            
            self.cached_results[cache_key] = update_result
            self.last_check_times[cache_key] = current_time
            return update_result
            
        except Exception as e:
            print(f"[HealthMonitor] Error checking updates: {e}")
            # Return OK on exception to avoid false alerts
            return {'status': 'OK', 'count': 0}
    
    def _check_security(self) -> Dict[str, Any]:
        """
        Check security-related items:
        - Uptime > 1 year (indicates potential kernel vulnerability if not updated)
        - SSL certificate expiration (non-INFO certs)
        - Excessive failed login attempts
        """
        try:
            issues = []
            
            # Check uptime for potential kernel vulnerabilities (if not updated)
            try:
                uptime_seconds = time.time() - psutil.boot_time()
                uptime_days = uptime_seconds / 86400
                
                # If uptime is over a year and no recent updates, it's a warning
                if uptime_days > 365:
                    # Check if updates check shows recent activity
                    updates_data = self.cached_results.get('updates_check')
                    if updates_data and updates_data.get('days_since_update', 9999) > 365:
                        issues.append(f'Uptime {int(uptime_days)} days (>1 year, consider updating kernel/system)')
            except Exception:
                pass # Ignore if uptime calculation fails
            
            # Check SSL certificates (only report non-OK statuses)
            cert_status = self._check_certificates()
            if cert_status and cert_status.get('status') not in ['OK', 'INFO']:
                issues.append(cert_status.get('reason', 'Certificate issue'))
            
            # Check for excessive failed login attempts in the last 24 hours
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
                        # Common patterns for failed logins in journald
                        if 'authentication failure' in line.lower() or 'failed password' in line.lower() or 'invalid user' in line.lower():
                            failed_logins += 1
                    
                    if failed_logins > 50: # Threshold for significant failed attempts
                        issues.append(f'{failed_logins} failed login attempts in 24h')
            except Exception:
                pass # Ignore if journalctl fails
            
            if issues:
                return {
                    'status': 'WARNING', # Security issues are typically warnings
                    'reason': '; '.join(issues[:2]) # Show up to 2 issues
                }
            
            return {'status': 'OK'}
            
        except Exception as e:
            print(f"[HealthMonitor] Error checking security: {e}")
            return {'status': 'OK'}
    
    def _check_certificates(self) -> Optional[Dict[str, Any]]:
        """
        Check SSL certificate expiration for PVE's default certificate.
        INFO: Self-signed or no cert configured (normal for internal servers)
        WARNING: Expires <30 days
        CRITICAL: Expired
        """
        cache_key = 'certificates'
        current_time = time.time()
        
        # Cache for 1 day (86400 seconds)
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 86400:
                return self.cached_results.get(cache_key)
        
        try:
            cert_path = '/etc/pve/local/pve-ssl.pem'
            
            if not os.path.exists(cert_path):
                cert_result = {
                    'status': 'INFO',
                    'reason': 'Self-signed or default PVE certificate'
                }
                self.cached_results[cache_key] = cert_result
                self.last_check_times[cache_key] = current_time
                return cert_result
            
            # Use openssl to get the expiry date
            result = subprocess.run(
                ['openssl', 'x509', '-enddate', '-noout', '-in', cert_path],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                date_str = result.stdout.strip().replace('notAfter=', '')
                
                try:
                    # Parse the date string (format can vary, e.g., 'Jun 15 10:00:00 2024 GMT')
                    # Attempt common formats
                    exp_date = None
                    try:
                        # Try more detailed format first
                        exp_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
                    except ValueError:
                        # Fallback to simpler format if needed
                        try:
                            exp_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y')
                        except ValueError:
                            # Fallback for "notAfter=..." string itself being the issue
                            if 'notAfter=' in date_str: # If it's the raw string itself
                                pass # Will result in 'INFO' status
                                
                    if exp_date:
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
                except Exception as e:
                    print(f"[HealthMonitor] Error parsing certificate expiry date '{date_str}': {e}")
                    # Fall through to return INFO if parsing fails
            
            # If openssl command failed or date parsing failed
            return {'status': 'INFO', 'reason': 'Certificate check inconclusive'}
            
        except Exception as e:
            print(f"[HealthMonitor] Error checking certificates: {e}")
            return {'status': 'OK'} # Return OK on exception
    
    def _check_disk_health_from_events(self) -> Dict[str, Any]:
        """
        Check for disk health warnings/errors from system logs (journalctl).
        Looks for SMART warnings and specific disk errors.
        Returns dict of disk issues found.
        """
        disk_issues = {}
        
        try:
            # Check journalctl for warnings/errors related to disks in the last hour
            result = subprocess.run(
                ['journalctl', '--since', '1 hour ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    
                    # Check for SMART warnings/errors
                    if 'smart' in line_lower and ('warning' in line_lower or 'error' in line_lower or 'fail' in line_lower):
                        # Extract disk name using regex for common disk identifiers
                        disk_match = re.search(r'/dev/(sd[a-z]|nvme\d+n\d+|hd\d+)', line)
                        if disk_match:
                            disk_name = disk_match.group(1)
                            # Prioritize CRITICAL if already warned, otherwise set to WARNING
                            if disk_name not in disk_issues or disk_issues[f'/dev/{disk_name}']['status'] != 'CRITICAL':
                                disk_issues[f'/dev/{disk_name}'] = {
                                    'status': 'WARNING',
                                    'reason': 'SMART warning detected'
                                }
                    
                    # Check for specific disk I/O or medium errors
                    if any(keyword in line_lower for keyword in ['disk error', 'ata error', 'medium error', 'io error']):
                        disk_match = re.search(r'/dev/(sd[a-z]|nvme\d+n\d+|hd\d+)', line)
                        if disk_match:
                            disk_name = disk_match.group(1)
                            disk_issues[f'/dev/{disk_name}'] = {
                                'status': 'CRITICAL',
                                'reason': 'Disk error detected'
                            }
        except Exception as e:
            print(f"[HealthMonitor] Error checking disk health from events: {e}")
            # Return empty dict on error, as this check isn't system-critical itself
            pass
        
        return disk_issues
    
    def _check_zfs_pool_health(self) -> Dict[str, Any]:
        """
        Check ZFS pool health status using 'zpool status' command.
        Returns dict of pools with non-ONLINE status (DEGRADED, FAULTED, UNAVAIL, etc.).
        """
        zfs_issues = {}
        
        try:
            # First check if 'zpool' command exists to avoid errors on non-ZFS systems
            result_which = subprocess.run(
                ['which', 'zpool'],
                capture_output=True,
                text=True,
                timeout=1
            )
            
            if result_which.returncode != 0:
                # ZFS is not installed or 'zpool' command not in PATH, so no ZFS issues to report.
                return zfs_issues
            
            # Get list of all pools and their health status
            result = subprocess.run(
                ['zpool', 'list', '-H', '-o', 'name,health'], # -H for no header
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
                        pool_health = parts[1].upper() # Ensure uppercase for consistent comparison
                        
                        # 'ONLINE' is the healthy state. Any other status indicates a problem.
                        if pool_health != 'ONLINE':
                            if pool_health in ['DEGRADED', 'FAULTED', 'UNAVAIL', 'REMOVED']:
                                # These are critical states
                                status = 'CRITICAL'
                                reason = f'ZFS pool {pool_health.lower()}'
                            else:
                                # Any other non-ONLINE state is at least a warning
                                status = 'WARNING'
                                reason = f'ZFS pool status: {pool_health.lower()}'
                            
                            # Use a unique key for each pool issue
                            zfs_issues[f'zpool_{pool_name}'] = {
                                'status': status,
                                'reason': reason,
                                'pool_name': pool_name,
                                'health': pool_health
                            }
        except Exception as e:
            print(f"[HealthMonitor] Error checking ZFS pool health: {e}")
            # If 'zpool status' command itself fails, we can't report ZFS issues.
            # Return empty dict as no specific ZFS issues were detected by this check.
            pass
        
        return zfs_issues

    def _check_proxmox_storage(self) -> Optional[Dict[str, Any]]:
        """
        Check Proxmox storage status using the proxmox_storage_monitor module.
        Detects unavailable storages configured in PVE.
        Returns CRITICAL if any configured storage is unavailable.
        Returns None if the module is not available.
        """
        if not PROXMOX_STORAGE_AVAILABLE:
            return None
        
        try:
            # Reload configuration to ensure we have the latest storage definitions
            proxmox_storage_monitor.reload_configuration()
            
            # Get the current status of all configured storages
            storage_status = proxmox_storage_monitor.get_storage_status()
            unavailable_storages = storage_status.get('unavailable', [])
            
            if not unavailable_storages:
                # All storages are available. We should also clear any previously recorded storage errors.
                active_errors = health_persistence.get_active_errors()
                for error in active_errors:
                    # Target errors related to storage unavailability
                    if error.get('category') == 'storage' and error.get('error_key', '').startswith('storage_unavailable_'):
                        health_persistence.clear_error(error['error_key'])
                return {'status': 'OK'}
            
            # If there are unavailable storages, record them as persistent errors and report.
            storage_issues_details = []
            for storage in unavailable_storages:
                storage_name = storage['name']
                error_key = f'storage_unavailable_{storage_name}'
                status_detail = storage.get('status_detail', 'unavailable') # e.g., 'not_found', 'connection_error'
                
                # Formulate a descriptive reason for the issue
                if status_detail == 'not_found':
                    reason = f"Storage '{storage_name}' is configured but not found on the server."
                elif status_detail == 'unavailable':
                    reason = f"Storage '{storage_name}' is not available (connection error or backend issue)."
                else:
                    reason = f"Storage '{storage_name}' has status: {status_detail}."
                
                # Record a persistent CRITICAL error for each unavailable storage
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage', # Category for persistence lookup
                    severity='CRITICAL', # Storage unavailability is always critical
                    reason=reason,
                    details={
                        'storage_name': storage_name,
                        'storage_type': storage.get('type', 'unknown'),
                        'status_detail': status_detail,
                        'dismissable': False  # Storage errors are not dismissable as they impact operations
                    }
                )
                storage_issues_details.append(reason) # Collect reasons for the summary
            
            return {
                'status': 'CRITICAL',
                'reason': f'{len(unavailable_storages)} Proxmox storage(s) unavailable',
                'details': {
                    'unavailable_storages': unavailable_storages,
                    'issues': storage_issues_details
                }
            }
        
        except Exception as e:
            print(f"[HealthMonitor] Error checking Proxmox storage: {e}")
            # Return None on exception to indicate the check could not be performed, not necessarily a failure.
            return None
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Main function to get the comprehensive health status.
        This function orchestrates all individual checks and aggregates results.
        """
        # Trigger all checks, including those with caching
        detailed_status = self.get_detailed_status()
        overall_status = self.get_overall_status()
        system_info = self.get_system_info()
        
        return {
            'system_info': system_info,
            'overall_health': overall_status,
            'detailed_health': detailed_status,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_detailed_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status with all checks.
        Returns JSON structure with ALL 10 categories always present.
        Now includes persistent error tracking.
        """
        active_errors = health_persistence.get_active_errors()
        # No need to create persistent_issues dict here, it's implicitly handled by the checks
        
        details = {
            'cpu': {'status': 'OK'},
            'memory': {'status': 'OK'},
            'storage': {'status': 'OK'}, # This will be overwritten by specific storage checks
            'disks': {'status': 'OK'}, # This will be overwritten by disk/filesystem checks
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
        
        # --- Priority Order of Checks ---
        
        # Priority 1: Critical PVE Services
        services_status = self._check_pve_services()
        details['services'] = services_status
        if services_status['status'] == 'CRITICAL':
            critical_issues.append(f"PVE Services: {services_status.get('reason', 'Service failure')}")
        elif services_status['status'] == 'WARNING':
            warning_issues.append(f"PVE Services: {services_status.get('reason', 'Service issue')}")
        
        # Priority 1.5: Proxmox Storage Check (External Module)
        proxmox_storage_result = self._check_proxmox_storage()
        if proxmox_storage_result: # Only process if the check ran (module available)
            details['storage'] = proxmox_storage_result
            if proxmox_storage_result.get('status') == 'CRITICAL':
                critical_issues.append(proxmox_storage_result.get('reason', 'Proxmox storage unavailable'))
            elif proxmox_storage_result.get('status') == 'WARNING':
                warning_issues.append(proxmox_storage_result.get('reason', 'Proxmox storage issue'))
        
        # Priority 2: Disk/Filesystem Health (Internal checks: usage, ZFS, SMART, IO errors)
        storage_status = self._check_storage_optimized()
        details['disks'] = storage_status # Use 'disks' for filesystem/disk specific issues
        if storage_status.get('status') == 'CRITICAL':
            critical_issues.append(f"Storage/Disks: {storage_status.get('reason', 'Disk/Storage failure')}")
        elif storage_status.get('status') == 'WARNING':
            warning_issues.append(f"Storage/Disks: {storage_status.get('reason', 'Disk/Storage issue')}")
        
        # Priority 3: VMs/CTs Status (with persistence)
        vms_status = self._check_vms_cts_with_persistence()
        details['vms'] = vms_status
        if vms_status.get('status') == 'CRITICAL':
            critical_issues.append(f"VMs/CTs: {vms_status.get('reason', 'VM/CT failure')}")
        elif vms_status.get('status') == 'WARNING':
            warning_issues.append(f"VMs/CTs: {vms_status.get('reason', 'VM/CT issue')}")
        
        # Priority 4: Network Connectivity
        network_status = self._check_network_optimized()
        details['network'] = network_status
        if network_status.get('status') == 'CRITICAL':
            critical_issues.append(f"Network: {network_status.get('reason', 'Network failure')}")
        elif network_status.get('status') == 'WARNING':
            warning_issues.append(f"Network: {network_status.get('reason', 'Network issue')}")
        
        # Priority 5: CPU Usage (with hysteresis)
        cpu_status = self._check_cpu_with_hysteresis()
        details['cpu'] = cpu_status
        if cpu_status.get('status') == 'CRITICAL':
            critical_issues.append(f"CPU: {cpu_status.get('reason', 'CPU critical')}")
        elif cpu_status.get('status') == 'WARNING':
            warning_issues.append(f"CPU: {cpu_status.get('reason', 'CPU high')}")
        
        # Priority 6: Memory Usage (RAM and Swap)
        memory_status = self._check_memory_comprehensive()
        details['memory'] = memory_status
        if memory_status.get('status') == 'CRITICAL':
            critical_issues.append(f"Memory: {memory_status.get('reason', 'Memory critical')}")
        elif memory_status.get('status') == 'WARNING':
            warning_issues.append(f"Memory: {memory_status.get('reason', 'Memory high')}")
        
        # Priority 7: Log Analysis (with persistence)
        logs_status = self._check_logs_with_persistence()
        details['logs'] = logs_status
        if logs_status.get('status') == 'CRITICAL':
            critical_issues.append(f"Logs: {logs_status.get('reason', 'Critical log errors')}")
        elif logs_status.get('status') == 'WARNING':
            warning_issues.append(f"Logs: {logs_status.get('reason', 'Log warnings')}")
        
        # Priority 8: System Updates
        updates_status = self._check_updates()
        details['updates'] = updates_status
        if updates_status.get('status') == 'CRITICAL':
            critical_issues.append(f"Updates: {updates_status.get('reason', 'System not updated')}")
        elif updates_status.get('status') == 'WARNING':
            warning_issues.append(f"Updates: {updates_status.get('reason', 'Updates pending')}")
        elif updates_status.get('status') == 'INFO':
            info_issues.append(f"Updates: {updates_status.get('reason', 'Informational update notice')}")
        
        # Priority 9: Security Checks
        security_status = self._check_security()
        details['security'] = security_status
        if security_status.get('status') == 'WARNING':
            warning_issues.append(f"Security: {security_status.get('reason', 'Security issue')}")
        elif security_status.get('status') == 'INFO':
            info_issues.append(f"Security: {security_status.get('reason', 'Security information')}")
        
        # --- Determine Overall Status ---
        # Use a fixed order of severity: CRITICAL > WARNING > INFO > OK
        if critical_issues:
            overall = 'CRITICAL'
            summary = '; '.join(critical_issues[:3]) # Limit summary to 3 issues
        elif warning_issues:
            overall = 'WARNING'
            summary = '; '.join(warning_issues[:3])
        elif info_issues:
            overall = 'OK'  # INFO statuses don't degrade overall health
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


# Global instance
health_monitor = HealthMonitor()
