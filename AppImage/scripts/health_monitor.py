"""
Health Monitor Module
Provides comprehensive health checks for the Proxmox system including:
- CPU and Memory usage
- Storage health (pools, disks, remote storage)
- Network health (interface errors)
- VM status
- System events/logs errors
"""

import psutil
import subprocess
import json
from typing import Dict, List, Any

class HealthMonitor:
    """Monitors system health across multiple components"""
    
    # Thresholds
    CPU_WARNING = 75
    CPU_CRITICAL = 90
    MEMORY_WARNING = 75
    MEMORY_CRITICAL = 90
    
    def __init__(self):
        self.checks = []
    
    def get_overall_status(self) -> Dict[str, Any]:
        """Get overall health status summary"""
        checks = self.run_all_checks()
        
        # Determine overall status
        critical_count = sum(1 for c in checks if c['status'] == 'critical')
        warning_count = sum(1 for c in checks if c['status'] == 'warning')
        
        if critical_count > 0:
            overall_status = 'critical'
        elif warning_count > 0:
            overall_status = 'warning'
        else:
            overall_status = 'healthy'
        
        return {
            'status': overall_status,
            'critical_count': critical_count,
            'warning_count': warning_count,
            'healthy_count': len(checks) - critical_count - warning_count,
            'total_checks': len(checks),
            'timestamp': psutil.boot_time()
        }
    
    def get_detailed_status(self) -> Dict[str, Any]:
        """Get detailed health status with all checks"""
        checks = self.run_all_checks()
        overall = self.get_overall_status()
        
        return {
            'overall': overall,
            'checks': checks
        }
    
    def run_all_checks(self) -> List[Dict[str, Any]]:
        """Run all health checks and return results"""
        checks = []
        
        # CPU Check
        checks.append(self.check_cpu())
        
        # Memory Check
        checks.append(self.check_memory())
        
        # Storage Checks
        checks.extend(self.check_storage())
        
        # Network Checks
        checks.extend(self.check_network())
        
        # VM Checks
        checks.extend(self.check_vms())
        
        # Events/Logs Check
        checks.append(self.check_events())
        
        return checks
    
    def check_cpu(self) -> Dict[str, Any]:
        """Check CPU usage"""
        cpu_percent = psutil.cpu_percent(interval=1)
        
        if cpu_percent >= self.CPU_CRITICAL:
            status = 'critical'
            message = f'CPU usage is critically high at {cpu_percent:.1f}%'
        elif cpu_percent >= self.CPU_WARNING:
            status = 'warning'
            message = f'CPU usage is elevated at {cpu_percent:.1f}%'
        else:
            status = 'healthy'
            message = f'CPU usage is normal at {cpu_percent:.1f}%'
        
        return {
            'category': 'System',
            'name': 'CPU Usage',
            'status': status,
            'value': f'{cpu_percent:.1f}%',
            'message': message,
            'details': {
                'usage': cpu_percent,
                'cores': psutil.cpu_count(),
                'warning_threshold': self.CPU_WARNING,
                'critical_threshold': self.CPU_CRITICAL
            }
        }
    
    def check_memory(self) -> Dict[str, Any]:
        """Check memory usage"""
        memory = psutil.virtual_memory()
        mem_percent = memory.percent
        
        if mem_percent >= self.MEMORY_CRITICAL:
            status = 'critical'
            message = f'Memory usage is critically high at {mem_percent:.1f}%'
        elif mem_percent >= self.MEMORY_WARNING:
            status = 'warning'
            message = f'Memory usage is elevated at {mem_percent:.1f}%'
        else:
            status = 'healthy'
            message = f'Memory usage is normal at {mem_percent:.1f}%'
        
        return {
            'category': 'System',
            'name': 'Memory Usage',
            'status': status,
            'value': f'{mem_percent:.1f}%',
            'message': message,
            'details': {
                'usage': mem_percent,
                'total': memory.total,
                'available': memory.available,
                'used': memory.used,
                'warning_threshold': self.MEMORY_WARNING,
                'critical_threshold': self.MEMORY_CRITICAL
            }
        }
    
    def check_storage(self) -> List[Dict[str, Any]]:
        """Check storage health including ZFS pools and disks"""
        checks = []
        
        # Check ZFS pools
        try:
            result = subprocess.run(['zpool', 'status'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                output = result.stdout
                
                # Parse pool status
                pools = self._parse_zpool_status(output)
                for pool in pools:
                    if pool['state'] == 'DEGRADED':
                        status = 'critical'
                        message = f"Pool '{pool['name']}' is degraded"
                    elif pool['state'] == 'FAULTED':
                        status = 'critical'
                        message = f"Pool '{pool['name']}' is faulted"
                    elif pool['state'] == 'OFFLINE':
                        status = 'critical'
                        message = f"Pool '{pool['name']}' is offline"
                    elif pool['errors'] > 0:
                        status = 'warning'
                        message = f"Pool '{pool['name']}' has {pool['errors']} errors"
                    else:
                        status = 'healthy'
                        message = f"Pool '{pool['name']}' is healthy"
                    
                    checks.append({
                        'category': 'Storage',
                        'name': f"ZFS Pool: {pool['name']}",
                        'status': status,
                        'value': pool['state'],
                        'message': message,
                        'details': pool
                    })
        except Exception as e:
            checks.append({
                'category': 'Storage',
                'name': 'ZFS Pools',
                'status': 'warning',
                'value': 'Unknown',
                'message': f'Could not check ZFS pools: {str(e)}',
                'details': {'error': str(e)}
            })
        
        # Check disk partitions
        partitions = psutil.disk_partitions()
        for partition in partitions:
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                percent = usage.percent
                
                if percent >= 95:
                    status = 'critical'
                    message = f"Disk '{partition.mountpoint}' is critically full at {percent:.1f}%"
                elif percent >= 85:
                    status = 'warning'
                    message = f"Disk '{partition.mountpoint}' is getting full at {percent:.1f}%"
                else:
                    status = 'healthy'
                    message = f"Disk '{partition.mountpoint}' has sufficient space ({percent:.1f}% used)"
                
                checks.append({
                    'category': 'Storage',
                    'name': f"Disk: {partition.mountpoint}",
                    'status': status,
                    'value': f'{percent:.1f}%',
                    'message': message,
                    'details': {
                        'device': partition.device,
                        'mountpoint': partition.mountpoint,
                        'fstype': partition.fstype,
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'percent': percent
                    }
                })
            except PermissionError:
                continue
        
        return checks
    
    def check_network(self) -> List[Dict[str, Any]]:
        """Check network interface health (errors, not inactive interfaces)"""
        checks = []
        
        # Get network interface stats
        net_io = psutil.net_io_counters(pernic=True)
        net_if_stats = psutil.net_if_stats()
        
        for interface, stats in net_io.items():
            # Skip loopback
            if interface == 'lo':
                continue
            
            # Only check active interfaces
            if interface in net_if_stats and net_if_stats[interface].isup:
                errors = stats.errin + stats.errout
                drops = stats.dropin + stats.dropout
                
                if errors > 100 or drops > 100:
                    status = 'critical'
                    message = f"Interface '{interface}' has {errors} errors and {drops} dropped packets"
                elif errors > 10 or drops > 10:
                    status = 'warning'
                    message = f"Interface '{interface}' has {errors} errors and {drops} dropped packets"
                else:
                    status = 'healthy'
                    message = f"Interface '{interface}' is operating normally"
                
                checks.append({
                    'category': 'Network',
                    'name': f"Interface: {interface}",
                    'status': status,
                    'value': 'Active',
                    'message': message,
                    'details': {
                        'errors_in': stats.errin,
                        'errors_out': stats.errout,
                        'drops_in': stats.dropin,
                        'drops_out': stats.dropout,
                        'bytes_sent': stats.bytes_sent,
                        'bytes_recv': stats.bytes_recv
                    }
                })
        
        return checks
    
    def check_vms(self) -> List[Dict[str, Any]]:
        """Check VM status"""
        checks = []
        
        try:
            # Get VM list from qm
            result = subprocess.run(['qm', 'list'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                
                running_count = 0
                stopped_count = 0
                error_count = 0
                
                for line in lines:
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 3:
                            vm_status = parts[2]
                            if vm_status == 'running':
                                running_count += 1
                            elif vm_status == 'stopped':
                                stopped_count += 1
                            else:
                                error_count += 1
                
                if error_count > 0:
                    status = 'warning'
                    message = f'{error_count} VMs in unexpected state'
                else:
                    status = 'healthy'
                    message = f'{running_count} running, {stopped_count} stopped'
                
                checks.append({
                    'category': 'Virtual Machines',
                    'name': 'VM Status',
                    'status': status,
                    'value': f'{running_count + stopped_count} total',
                    'message': message,
                    'details': {
                        'running': running_count,
                        'stopped': stopped_count,
                        'errors': error_count
                    }
                })
        except Exception as e:
            checks.append({
                'category': 'Virtual Machines',
                'name': 'VM Status',
                'status': 'warning',
                'value': 'Unknown',
                'message': f'Could not check VM status: {str(e)}',
                'details': {'error': str(e)}
            })
        
        return checks
    
    def check_events(self) -> Dict[str, Any]:
        """Check system events/logs for errors"""
        try:
            # Check journalctl for recent errors
            result = subprocess.run(
                ['journalctl', '-p', 'err', '-n', '100', '--no-pager'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                error_lines = [line for line in result.stdout.split('\n') if line.strip()]
                error_count = len(error_lines)
                
                if error_count > 50:
                    status = 'critical'
                    message = f'{error_count} errors in recent logs'
                elif error_count > 10:
                    status = 'warning'
                    message = f'{error_count} errors in recent logs'
                else:
                    status = 'healthy'
                    message = f'{error_count} errors in recent logs (normal)'
                
                return {
                    'category': 'System Events',
                    'name': 'Error Logs',
                    'status': status,
                    'value': f'{error_count} errors',
                    'message': message,
                    'details': {
                        'error_count': error_count,
                        'recent_errors': error_lines[:5]  # Last 5 errors
                    }
                }
        except Exception as e:
            return {
                'category': 'System Events',
                'name': 'Error Logs',
                'status': 'warning',
                'value': 'Unknown',
                'message': f'Could not check system logs: {str(e)}',
                'details': {'error': str(e)}
            }
    
    def _parse_zpool_status(self, output: str) -> List[Dict[str, Any]]:
        """Parse zpool status output"""
        pools = []
        current_pool = None
        
        for line in output.split('\n'):
            line = line.strip()
            
            if line.startswith('pool:'):
                if current_pool:
                    pools.append(current_pool)
                current_pool = {'name': line.split(':')[1].strip(), 'state': 'UNKNOWN', 'errors': 0}
            elif line.startswith('state:') and current_pool:
                current_pool['state'] = line.split(':')[1].strip()
            elif 'errors:' in line.lower() and current_pool:
                try:
                    error_part = line.split(':')[1].strip()
                    if error_part.lower() != 'no known data errors':
                        current_pool['errors'] = int(error_part.split()[0])
                except:
                    pass
        
        if current_pool:
            pools.append(current_pool)
        
        return pools

# Global instance
health_monitor = HealthMonitor()
