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
import hashlib # Added for MD5 hashing
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import re

from health_persistence import health_persistence, disk_base_name

try:
    from proxmox_storage_monitor import proxmox_storage_monitor
    PROXMOX_STORAGE_AVAILABLE = True
except ImportError:
    PROXMOX_STORAGE_AVAILABLE = False

# Sprint 13: arbitrary remote mount monitoring (NFS/CIFS/SMB) for
# mounts done outside PVE — complements proxmox_storage_monitor which
# only sees PVE-registered storages.
try:
    import mount_monitor
    MOUNT_MONITOR_AVAILABLE = True
except ImportError:
    MOUNT_MONITOR_AVAILABLE = False

# ============================================================================
# PERFORMANCE DEBUG FLAG - Set to True to log timing of each health check
# To analyze: grep "\[PERF\]" /var/log/proxmenux-monitor.log | sort -t'=' -k2 -n
# Set to False or remove this section after debugging
# ============================================================================
DEBUG_PERF = False

# ─── Startup Grace Period ────────────────────────────────────────────────────
# Import centralized startup grace management for consistent behavior
import startup_grace

def _is_startup_health_grace() -> bool:
    """Check if we're within the startup health grace period (5 min).
    
    Uses centralized startup_grace module for consistency across all components.
    """
    return startup_grace.is_startup_health_grace()

def _perf_log(section: str, elapsed_ms: float):
    """Log performance timing for a section. Only logs if DEBUG_PERF is True."""
    if DEBUG_PERF:
        print(f"[PERF] {section} = {elapsed_ms:.1f}ms")

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
    MEMORY_DURATION = 300  # 5 minutes sustained (aligned with CPU)
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
    NETWORK_TIMEOUT = 2
    NETWORK_INACTIVE_DURATION = 600
    
    # Log Thresholds
    LOG_ERRORS_WARNING = 5
    LOG_ERRORS_CRITICAL = 10
    LOG_WARNINGS_WARNING = 15
    LOG_WARNINGS_CRITICAL = 30
    # Aligned with the rest of the health checks (5 min). Was 57 min, but the
    # journalctl windows below are 5 min each, so the previous interval left a
    # ~52 min gap per cycle in which 95% of the journal was never inspected.
    LOG_CHECK_INTERVAL = 300
    
    # Updates Thresholds
    UPDATES_WARNING = 365   # Only warn after 1 year without updates (system_age)
    UPDATES_CRITICAL = 548  # Critical after 18 months without updates
    SECURITY_WARN_DAYS = 360  # Security updates only become WARNING after 360 days unpatched
    
    BENIGN_ERROR_PATTERNS = [
        # ── Proxmox API / proxy operational noise ──
        r'got inotify poll request in wrong process',
        r'auth key pair too old, rotating',
        r'proxy detected vanished client connection',
        r'worker \d+ finished',
        r'connection timed out',
        r'disconnect peer',
        r'task OK',
        r'backup finished',
        # PVE ticket / auth transient errors (web UI session expiry, API token
        # refresh, brute-force bots). These are logged at WARNING/ERR level
        # but are NOT system problems -- they are access-control events.
        r'invalid PVE ticket',
        r'authentication failure.*pve',
        r'permission denied.*ticket',
        r'no ticket',
        r'CSRF.*failed',
        r'pveproxy\[\d+\]: authentication failure',
        r'pvedaemon\[\d+\]: authentication failure',
        # PVE cluster/corosync normal chatter
        r'corosync.*retransmit',
        r'corosync.*delivering',
        r'pmxcfs.*update',
        r'pve-cluster\[\d+\]:.*status',
        
        # ── Systemd informational messages ──
        r'(started|starting|stopped|stopping) session',
        r'session \d+ logged (in|out)',
        r'new session \d+ of user',
        r'removed session \d+',
        r'user@\d+\.service:',
        r'user runtime directory',
        # Systemd service restarts (normal lifecycle)
        r'systemd\[\d+\]: .+\.service: (Scheduled restart|Consumed)',
        r'systemd\[\d+\]: .+\.service: Deactivated successfully',
        
        # ── Network transient errors (common and usually self-recovering) ──
        r'dhcp.*timeout',
        r'temporary failure in name resolution',
        r'network is unreachable',
        r'no route to host',
        
        # ── Backup and sync normal warnings ──
        r'rsync.*vanished',
        r'backup job .* finished',
        r'vzdump backup .* finished',
        
        # ── ZFS informational ──
        r'zfs.*scrub (started|finished|in progress)',
        r'zpool.*resilver',
        
        # ── LXC/Container normal operations ──
        r'lxc.*monitor',
        r'systemd\[1\]: (started|stopped) .*\.scope',
        
        # ── ATA/SCSI transient bus errors ──
        # These are logged at ERR level but are common on SATA controllers
        # during hot-plug, link renegotiation, or cable noise. They are NOT
        # indicative of disk failure unless SMART also reports problems.
        # NOTE: patterns are matched against line.lower(), so use lowercase.
        r'ata\d+.*serror.*badcrc',
        r'ata\d+.*emask 0x10.*ata bus error',
        r'failed command: (read|write) fpdma queued',
        r'ata\d+.*hard resetting link',
        r'ata\d+.*link is slow',
        r'ata\d+.*comreset',
        
        # ── ProxMenux self-referential noise ──
        # The monitor reporting its OWN service failures is circular --
        # it cannot meaningfully alert about itself.
        # NOTE: patterns are matched against line.lower(), so use lowercase.
        r'proxmenux-monitor\.service.*failed',
        r'proxmenux-monitor\.service.*exit-code',
        r'proxmenux-monitor.*failed at step exec',
        r'proxmenux-monitor\.appimage',
        
        # ── PVE scheduler operational noise ──
        # pvescheduler emits "could not update job state" every minute
        # when a scheduled job reference is stale.  This is cosmetic,
        # not a system problem.
        r'pvescheduler.*could not update job state',
        r'pvescheduler.*no such task',
        
        # ── GPU passthrough / vfio operational noise ──
        # When a GPU is passed through to a VM using vfio-pci, the host
        # NVIDIA driver will log errors because it cannot access the GPU.
        # This is expected behavior, NOT an error - the passthrough is working.
        r'NVRM.*GPU.*already bound to vfio-pci',
        r'NVRM.*GPU.*is not supported',
        r'NVRM.*failed to enable MSI',
        r'NVRM.*RmInitAdapter failed',
        r'NVRM.*rm_init_adapter failed',
        r'nvidia.*probe.*failed',
        r'vfio-pci.*\d+:\d+:\d+\.\d+.*reset',
        r'vfio-pci.*enabling device',
        r'vfio_pci.*cannot assign irq',
    ]
    
    CRITICAL_LOG_KEYWORDS = [
        # OOM and memory errors
        'out of memory', 'oom_kill', 'oom-kill', 'invoked oom-killer',
        'memory cgroup out of memory', 'cannot allocate memory', 'oom_reaper',
        # Kernel panics and critical faults
        'kernel panic', 'general protection fault', 'trap invalid opcode',
        # Filesystem critical errors
        'filesystem read-only', 'read-only file system', 'cannot mount',
        'ext4-fs error', 'ext4_abort', 'xfs.*corruption', 'btrfs.*error',
        # RAID/Storage critical
        'raid.*failed', 'md.*device failed', 'lvm activation failed',
        'zpool.*faulted', 'state: faulted',
        # Hardware errors
        'hardware error', 'mce:',
        # Cluster critical
        'quorum lost', 'split brain',
    ]
    
    # Segfault is WARNING, not CRITICAL -- only PVE-critical process
    # segfaults are escalated to CRITICAL in _classify_log_severity.
    PVE_CRITICAL_PROCESSES = {
        'pveproxy', 'pvedaemon', 'pvestatd', 'pve-cluster',
        'corosync', 'qemu-system', 'lxc-start', 'ceph-osd',
        'ceph-mon', 'pmxcfs', 'kvm',
    }
    
    WARNING_LOG_KEYWORDS = [
        # Storage I/O errors
        'i/o error', 'buffer i/o error', 'ata error', 'scsi error',
        'disk.*offline', 'disk.*removed',
        # CPU/IO blocking
        'task hung', 'blocked for more than', 'soft lockup',
        # Service failures
        'failed to start', 'service.*failed',
        'entering failed state', 'code=exited, status=', 'code=killed',
        # Process crashes (WARNING by default; escalated to CRITICAL for PVE processes)
        'segfault',
        # Cluster/Network warnings
        'corosync.*failed', 'corosync.*timeout',
        'connection lost', 'totem.*failed',
        'entered disabled state', 'entered blocking state',
    ]
    
    # PVE Critical Services
    PVE_SERVICES = ['pveproxy', 'pvedaemon', 'pvestatd', 'pve-cluster']
    
    # P2 fix: Pre-compiled regex patterns for performance (avoid re-compiling on every line)
    _BENIGN_RE = None
    _CRITICAL_RE = None
    _WARNING_RE = None
    
    @classmethod
    def _get_compiled_patterns(cls):
        """Lazily compile regex patterns once"""
        if cls._BENIGN_RE is None:
            cls._BENIGN_RE = re.compile("|".join(cls.BENIGN_ERROR_PATTERNS), re.IGNORECASE)
            cls._CRITICAL_RE = re.compile("|".join(cls.CRITICAL_LOG_KEYWORDS), re.IGNORECASE)
            cls._WARNING_RE = re.compile("|".join(cls.WARNING_LOG_KEYWORDS), re.IGNORECASE)
        return cls._BENIGN_RE, cls._CRITICAL_RE, cls._WARNING_RE
    
    def _refresh_thresholds(self):
        """Pull user-configured thresholds from `health_thresholds` and
        overlay them on the class defaults as instance attributes.

        Called at the start of every check cycle so a save() in the UI
        propagates within one tick (5 min worst case for the background
        loop, instant for direct API hits). Sections that aren't
        configured fall back to the class constants — that's why this
        method only writes when the JSON has an override.

        We deliberately overlay onto the *instance*, not the class, so
        the original class constants stay as a safety net (and the
        codebase keeps a readable list of recommended values up top).
        """
        try:
            import health_thresholds as _ht
        except Exception:
            return
        try:
            mapping = (
                # (section, key) -> instance attribute on self
                (("cpu", "warning"), "CPU_WARNING"),
                (("cpu", "critical"), "CPU_CRITICAL"),
                (("memory", "warning"), "MEMORY_WARNING"),
                (("memory", "critical"), "MEMORY_CRITICAL"),
                (("memory", "swap_critical"), "SWAP_CRITICAL_PERCENT"),
                (("host_storage", "warning"), "STORAGE_WARNING"),
                (("host_storage", "critical"), "STORAGE_CRITICAL"),
                (("cpu_temperature", "warning"), "TEMP_WARNING"),
                (("cpu_temperature", "critical"), "TEMP_CRITICAL"),
            )
            for path, attr in mapping:
                v = _ht.get(*path)
                if v is not None:
                    setattr(self, attr, v)
        except Exception as e:
            print(f"[HealthMonitor] threshold refresh failed: {e}")

    def __init__(self):
        """Initialize health monitor with state tracking"""
        self.state_history = defaultdict(list)
        self.last_check_times = {}
        self.cached_results = {}
        self.network_baseline = {}
        self.io_error_history = defaultdict(list)
        self.failed_vm_history = set()  # Track VMs that failed to start
        self.persistent_log_patterns = defaultdict(lambda: {'count': 0, 'first_seen': 0, 'last_seen': 0})
        self._unknown_counts = {}  # Track consecutive UNKNOWN cycles per category
        self._last_cleanup_time = 0  # Throttle cleanup_old_errors calls
        
        # SMART check cache - reduces disk queries from every 5 min to every 30 min
        self._smart_cache = {}  # {disk_name: {'result': 'PASSED', 'time': timestamp}}
        self._SMART_CACHE_TTL = 1620  # 27 min - offset to avoid sync with other processes
        # Disk identity cache - avoids repeated smartctl -i calls for serial/model
        self._disk_identity_cache: Dict[str, Dict[str, str]] = {}  # {disk_name: {'serial': ..., 'model': ...}}
        
        # Journalctl 24h cache - reduces full log reads from every 5 min to every 1 hour
        self._journalctl_24h_cache = {'count': 0, 'time': 0}
        self._JOURNALCTL_24H_CACHE_TTL = 3600  # 1 hour - login attempts aggregate slowly
        
        # Journalctl 10min cache - shared across checks to avoid duplicate calls
        # Multiple checks (cpu_temp, vms_cts) use the same journalctl query
        self._journalctl_10min_cache = {'output': '', 'time': 0}
        self._JOURNALCTL_10MIN_CACHE_TTL = 120  # 2 minutes - covers full health check cycle
        
        # Journalctl 1hour cache - for disk health events (SMART warnings, I/O errors)
        self._journalctl_1hour_cache = {'output': '', 'time': 0}
        self._JOURNALCTL_1HOUR_CACHE_TTL = 300  # 5 min cache - disk events don't need real-time
        # Timestamp watermark: track last successfully processed journalctl entry
        # to avoid re-processing old entries on subsequent checks. Persisted via
        # health_persistence.set_setting('disk_journal_last_ts', ...) so that
        # restarts don't re-read the last hour of journal and re-emit events
        # that were already notified. Audit Tier 5 (Health stack).
        try:
            from health_persistence import health_persistence as _hp_init
            self._disk_journal_last_ts: Optional[str] = _hp_init.get_setting('disk_journal_last_ts')
        except Exception:
            self._disk_journal_last_ts = None
        
        # System capabilities - derived from Proxmox storage types at runtime (Priority 1.5)
        # SMART detection still uses filesystem check on init (lightweight)
        has_smart = os.path.exists('/usr/sbin/smartctl') or os.path.exists('/usr/bin/smartctl')
        self.capabilities = {'has_zfs': False, 'has_lvm': False, 'has_smart': has_smart}
        
        try:
            health_persistence.cleanup_old_errors()
        except Exception as e:
            print(f"[HealthMonitor] Cleanup warning: {e}")
    
    def _get_journalctl_10min_warnings(self) -> str:
        """Get journalctl warnings from last 10 minutes, cached to avoid duplicate calls.
        
        Multiple health checks need the same journalctl data (cpu_temp, vms_cts, etc).
        This method caches the result for 60 seconds to reduce subprocess overhead.
        """
        current_time = time.time()
        cache = self._journalctl_10min_cache
        
        # Return cached result if fresh
        if cache['output'] and (current_time - cache['time']) < self._JOURNALCTL_10MIN_CACHE_TTL:
            return cache['output']
        
        # Execute journalctl and cache result
        # Use -b 0 to only include logs from the current boot
        try:
            result = subprocess.run(
                ['journalctl', '-b', '0', '--since', '10 minutes ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                cache['output'] = result.stdout
                cache['time'] = current_time
                return cache['output']
        except subprocess.TimeoutExpired:
            print("[HealthMonitor] journalctl 10min cache: timeout")
        except Exception as e:
            print(f"[HealthMonitor] journalctl 10min cache error: {e}")
        
        return cache.get('output', '')  # Return stale cache on error
    
    def _get_journalctl_1hour_warnings(self) -> str:
        """Get journalctl warnings since last check, cached for disk health checks.

        Used by _check_disk_health_from_events for SMART warnings and I/O errors.
        Uses a timestamp watermark (_disk_journal_last_ts) to only read NEW entries
        since the last successful check, preventing re-processing of old errors.
        On first run (no watermark), reads the last 10 minutes to catch recent events
        without pulling in stale history.
        Cached for 5 minutes since disk events don't require real-time detection.
        """
        current_time = time.time()
        cache = self._journalctl_1hour_cache

        # Return cached result if fresh
        if cache['output'] is not None and cache['time'] > 0 and (current_time - cache['time']) < self._JOURNALCTL_1HOUR_CACHE_TTL:
            return cache['output']

        # Determine --since value: use watermark if available, otherwise 10 minutes
        if self._disk_journal_last_ts:
            since_arg = self._disk_journal_last_ts
        else:
            since_arg = '10 minutes ago'

        try:
            result = subprocess.run(
                ['journalctl', '-b', '0', '--since', since_arg, '--no-pager', '-p', 'warning',
                 '--output=short-precise'],
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode == 0:
                output = result.stdout
                cache['output'] = output
                cache['time'] = current_time
                # Advance watermark to "now" so next check only gets new
                # entries, AND persist it so a restart resumes from this point
                # instead of re-reading the last hour of journal.
                from datetime import datetime as _dt
                new_ts = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
                self._disk_journal_last_ts = new_ts
                try:
                    from health_persistence import health_persistence as _hp_save
                    _hp_save.set_setting('disk_journal_last_ts', new_ts)
                except Exception:
                    pass  # Don't break the disk check if persistence fails
                return output
        except subprocess.TimeoutExpired:
            print("[HealthMonitor] journalctl disk cache: timeout")
        except Exception as e:
            print(f"[HealthMonitor] journalctl disk cache error: {e}")

        return cache.get('output', '')  # Return stale cache on error
    
    # ─── Lightweight sampling methods for the dedicated vital-signs thread ───
    # These ONLY append data to state_history without triggering evaluation,
    # persistence, or subprocess-heavy operations.
    
    def _sample_cpu_usage(self):
        """Lightweight CPU sample: read usage % and append to history. ~30ms cost."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0)
            current_time = time.time()
            state_key = 'cpu_usage'
            self.state_history[state_key].append({
                'value': cpu_percent,
                'time': current_time
            })
            # Prune entries older than 6 minutes
            self.state_history[state_key] = [
                e for e in self.state_history[state_key]
                if current_time - e['time'] < 360
            ]
        except Exception:
            pass  # Sampling must never crash the thread
    
    def _sample_memory_usage(self):
        """Lightweight memory sample: read RAM/swap % and append to history. ~1ms cost."""
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
            # Prune entries older than 10 minutes
            self.state_history[state_key] = [
                e for e in self.state_history[state_key]
                if current_time - e['time'] < 600
            ]
        except Exception:
            pass  # Sampling must never crash the thread

    def _sample_cpu_temperature(self):
        """Lightweight temperature sample: read sensor and append to history.

        Switched from `subprocess.run(['sensors', '-A', '-u'])` to
        `psutil.sensors_temperatures()` for the vital-signs sampler
        (called every 15s). The subprocess fork + lm-sensors binary
        startup + parse loop takes ~6ms per call on AppImage hosts;
        psutil reads the same /sys/class/hwmon entries directly in
        ~3ms with no fork. Cumulatively at 4 calls/min × N hosts the
        savings matter for the 60s collector duty cycle. Behaviour is
        unchanged — we still aggregate every reported `*_input` value
        and persist the max in `state_history`.
        """
        try:
            temps_dict = psutil.sensors_temperatures()
            if not temps_dict:
                return

            temps = []
            for entries in temps_dict.values():
                for entry in entries:
                    val = getattr(entry, 'current', None)
                    if isinstance(val, (int, float)) and val > 0:
                        temps.append(float(val))

            if temps:
                max_temp = max(temps)
                current_time = time.time()
                state_key = 'cpu_temp_history'
                self.state_history[state_key].append({
                    'value': max_temp,
                    'time': current_time
                })
                # Prune entries older than 4 minutes
                self.state_history[state_key] = [
                    e for e in self.state_history[state_key]
                    if current_time - e['time'] < 240
                ]
        except Exception:
            pass  # Sampling must never crash the thread
    
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
        The background health collector keeps '_bg_overall' always fresh (every 5 min).
        Falls back to calculating on demand if background data is stale or unavailable.
        """
        current_time = time.time()
        
        # 1. Check background collector cache (updated every 5 min by _health_collector_loop)
        bg_key = '_bg_overall'
        if bg_key in self.last_check_times:
            age = current_time - self.last_check_times[bg_key]
            if age < 360:  # 6 min (5 min interval + 1 min tolerance)
                return self.cached_results.get(bg_key, {'status': 'OK', 'summary': 'System operational'})
        
        # 2. Check regular cache (updated by modal fetches or on-demand)
        cache_key = 'overall_health'
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 60:
                return self.cached_results.get(cache_key, {'status': 'OK', 'summary': 'System operational'})
        
        # 3. No fresh cache - calculate on demand (happens only on first load before bg thread runs)
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
        # Pick up any threshold changes the user saved in Settings since
        # the last cycle. Cheap (cached read) — see health_thresholds.
        self._refresh_thresholds()

        # Run cleanup with throttle (every 5 min) so stale errors are auto-resolved
        # using the user-configured Suppression Duration (single source of truth).
        current_time = time.time()
        if current_time - self._last_cleanup_time > 300:  # 5 minutes
            try:
                health_persistence.cleanup_old_errors()
                self._last_cleanup_time = current_time
            except Exception:
                pass
        
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
        _t_total = time.time()  # [PERF] Total health check timing
        
        # Priority 1: Critical PVE Services
        _t = time.time()
        services_status = self._check_pve_services()
        _perf_log("services", (time.time() - _t) * 1000)
        details['services'] = services_status
        if services_status['status'] == 'CRITICAL':
            critical_issues.append(f"PVE Services: {services_status.get('reason', 'Service failure')}")
        elif services_status['status'] == 'WARNING':
            warning_issues.append(f"PVE Services: {services_status.get('reason', 'Service issue')}")
        
        # Priority 1.5: Proxmox Storage Check (External Module)
        _t = time.time()
        proxmox_storage_result = self._check_proxmox_storage()
        _perf_log("proxmox_storage", (time.time() - _t) * 1000)
        if proxmox_storage_result: # Only process if the check ran (module available)
            details['storage'] = proxmox_storage_result
            if proxmox_storage_result.get('status') == 'CRITICAL':
                critical_issues.append(proxmox_storage_result.get('reason', 'Proxmox storage unavailable'))
            elif proxmox_storage_result.get('status') == 'WARNING':
                warning_issues.append(proxmox_storage_result.get('reason', 'Proxmox storage issue'))

            # Derive capabilities from Proxmox storage types (immediate, no extra checks)
            storage_checks = proxmox_storage_result.get('checks', {})
            storage_types = {v.get('detail', '').split(' ')[0].lower() for v in storage_checks.values() if isinstance(v, dict)}
            self.capabilities['has_zfs'] = any(t in ('zfspool', 'zfs') for t in storage_types)
            self.capabilities['has_lvm'] = any(t in ('lvm', 'lvmthin') for t in storage_types)

        # Priority 1.6: Sprint 13 — remote-mount health (NFS/CIFS/SMB).
        # Catches the case PVE storage monitor misses: ad-hoc mounts
        # (fstab, manual mount commands) that go stale and silently
        # redirect writes to the underlying directory, filling local
        # disk. Stale mounts are CRITICAL, unexpected read-only is
        # WARNING.
        _t = time.time()
        remote_mount_result = self._check_remote_mounts()
        _perf_log("remote_mounts", (time.time() - _t) * 1000)
        if remote_mount_result:
            details['remote_mounts'] = remote_mount_result
            if remote_mount_result.get('status') == 'CRITICAL':
                critical_issues.append(remote_mount_result.get('reason', 'Remote mount stale'))
            elif remote_mount_result.get('status') == 'WARNING':
                warning_issues.append(remote_mount_result.get('reason', 'Remote mount issue'))

        # Priority 1.7: Sprint 13.30 — per-LXC rootfs disk usage.
        # Same WARN/CRIT thresholds as the host disk check (85/95).
        # The classic failure mode: CT rootfs sized too small + log
        # accumulation = CT goes 100% and stops booting.
        _t = time.time()
        lxc_disk_result = self._check_lxc_disk_usage()
        _perf_log("lxc_disk_usage", (time.time() - _t) * 1000)
        if lxc_disk_result:
            details['lxc_disk'] = lxc_disk_result
            if lxc_disk_result.get('status') == 'CRITICAL':
                critical_issues.append(lxc_disk_result.get('reason', 'LXC rootfs near full'))
            elif lxc_disk_result.get('status') == 'WARNING':
                warning_issues.append(lxc_disk_result.get('reason', 'LXC rootfs filling up'))

        # Phase 3 capacity checks added on top of the existing storage
        # ones. Each is independently configurable via Settings →
        # Health Thresholds; defaults are 85/95 to align with the host
        # disk check. They sit on the same priority level because they
        # all fail in the same way (storage filling up).
        _t = time.time()
        lxc_mount_result = self._check_lxc_mount_capacity()
        _perf_log("lxc_mount_capacity", (time.time() - _t) * 1000)
        if lxc_mount_result:
            details['lxc_mounts'] = lxc_mount_result
            if lxc_mount_result.get('status') == 'CRITICAL':
                critical_issues.append(lxc_mount_result.get('reason', 'LXC mount near full'))
            elif lxc_mount_result.get('status') == 'WARNING':
                warning_issues.append(lxc_mount_result.get('reason', 'LXC mount filling up'))

        _t = time.time()
        pve_storage_cap_result = self._check_pve_storage_capacity()
        _perf_log("pve_storage_capacity", (time.time() - _t) * 1000)
        if pve_storage_cap_result:
            details['pve_storage_capacity'] = pve_storage_cap_result
            if pve_storage_cap_result.get('status') == 'CRITICAL':
                critical_issues.append(pve_storage_cap_result.get('reason', 'PVE storage near full'))
            elif pve_storage_cap_result.get('status') == 'WARNING':
                warning_issues.append(pve_storage_cap_result.get('reason', 'PVE storage filling up'))

        _t = time.time()
        zfs_pool_cap_result = self._check_zfs_pool_capacity()
        _perf_log("zfs_pool_capacity", (time.time() - _t) * 1000)
        if zfs_pool_cap_result:
            details['zfs_pool_capacity'] = zfs_pool_cap_result
            if zfs_pool_cap_result.get('status') == 'CRITICAL':
                critical_issues.append(zfs_pool_cap_result.get('reason', 'ZFS pool near full'))
            elif zfs_pool_cap_result.get('status') == 'WARNING':
                warning_issues.append(zfs_pool_cap_result.get('reason', 'ZFS pool filling up'))

        # Roll the storage-related sub-checks (pve_storage_capacity,
        # zfs_pool_capacity, lxc_disk, lxc_mounts, remote_mounts) up
        # into details['storage'] so the front-end Health Status modal
        # can render the worst severity in the storage category badge
        # AND surface the offending storage entry inside the expanded
        # category list. Sub-checks whose error_key has been
        # acknowledged by the user are tagged `dismissed=True` and
        # excluded from the aggregate status calculation — otherwise
        # the category would stay WARNING after the user clicked
        # Dismiss, defeating the dismiss flow.
        if 'storage' in details:
            _SEV_RANK = {'OK': 0, 'INFO': 1, 'WARNING': 2, 'CRITICAL': 3}
            storage_block = details['storage']
            cur_status = storage_block.get('status', 'OK')
            cur_rank = _SEV_RANK.get(cur_status, 0)
            extra_reasons = []

            def _annotate_dismissed(check_dict):
                """Mutate check_dict in place to add `dismissed=True` if
                its error_key is currently acknowledged in the DB. When the
                dismiss was permanent (suppression_hours == -1) also tags
                ``permanent=True`` so the UI can render a "🔒 Permanent"
                badge distinct from the time-limited countdown.
                Returns True when the check should NOT contribute to the
                aggregate status."""
                if not isinstance(check_dict, dict):
                    return False
                ek = check_dict.get('error_key')
                if not ek:
                    return False
                try:
                    if health_persistence.is_error_acknowledged(ek):
                        check_dict['dismissed'] = True
                        if health_persistence.is_error_permanently_acknowledged(ek):
                            check_dict['permanent'] = True
                        return True
                except Exception:
                    pass
                return False

            for sub_key in ('pve_storage_capacity', 'zfs_pool_capacity',
                            'lxc_disk', 'lxc_mounts', 'remote_mounts'):
                sub = details.get(sub_key)
                if not isinstance(sub, dict):
                    continue
                sub_status = sub.get('status', 'OK')
                sub_rank = _SEV_RANK.get(sub_status, 0)
                # When the sub-block's headline status is non-OK, look
                # at its individual checks: if every offending one is
                # acknowledged, the block doesn't push the aggregate
                # up — the user already told us they know about it.
                sub_contributes = sub_status not in ('WARNING', 'CRITICAL')
                if sub_status in ('WARNING', 'CRITICAL'):
                    inner_checks = sub.get('checks') or {}
                    if isinstance(inner_checks, dict):
                        for inner in inner_checks.values():
                            if not isinstance(inner, dict):
                                continue
                            inner_status = inner.get('status', 'OK')
                            if inner_status not in ('WARNING', 'CRITICAL'):
                                continue
                            if not _annotate_dismissed(inner):
                                sub_contributes = True
                if sub_contributes and sub_rank > cur_rank:
                    cur_status = sub_status
                    cur_rank = sub_rank
                if sub_contributes and sub_status in ('WARNING', 'CRITICAL'):
                    sub_reason = sub.get('reason')
                    if sub_reason:
                        extra_reasons.append(sub_reason)
                # Merge sub-checks (storage names) so each entry
                # carries its real severity in the expanded list.
                # Sub-results sometimes name the same storage with a
                # type suffix (e.g. proxmox_storage uses "PBS-Cloud"
                # while pve_storage_capacity uses "PBS-Cloud (pbs)") —
                # normalising on the bare-name part lets the worst
                # severity win without splitting one storage into two
                # rows in the UI. Defensive `dict()` to avoid mutating
                # the source.
                sub_checks = sub.get('checks') or {}
                if not isinstance(sub_checks, dict):
                    continue
                target_checks = storage_block.setdefault('checks', {})

                def _bare_name(name):
                    # "PBS-Cloud (pbs)" → "PBS-Cloud"
                    if ' (' in name and name.endswith(')'):
                        return name.rsplit(' (', 1)[0]
                    return name

                target_lookup = {_bare_name(k): k for k in target_checks}
                for ck_name, ck_data in sub_checks.items():
                    if not isinstance(ck_data, dict):
                        continue
                    canonical = _bare_name(ck_name)
                    target_key = target_lookup.get(canonical)
                    if target_key is None:
                        target_checks[canonical] = dict(ck_data)
                        target_lookup[canonical] = canonical
                        continue
                    existing = target_checks.get(target_key) or {}
                    existing_rank = _SEV_RANK.get(
                        existing.get('status', 'OK'), 0)
                    new_rank = _SEV_RANK.get(
                        ck_data.get('status', 'OK'), 0)
                    if new_rank > existing_rank:
                        merged = dict(existing)
                        merged.update(ck_data)
                        target_checks[target_key] = merged
            if cur_status != storage_block.get('status', 'OK'):
                storage_block['status'] = cur_status
                base_reason = storage_block.get('reason', '').strip()
                combined = '; '.join(
                    [r for r in [base_reason] + extra_reasons if r]
                )
                if combined:
                    storage_block['reason'] = combined

        # Priority 2: Disk/Filesystem Health (Internal checks: usage, ZFS, SMART, IO errors)
        _t = time.time()
        storage_status = self._check_storage_optimized()
        _perf_log("storage_optimized", (time.time() - _t) * 1000)
        details['disks'] = storage_status # Use 'disks' for filesystem/disk specific issues
        if storage_status.get('status') == 'CRITICAL':
            critical_issues.append(f"Storage/Disks: {storage_status.get('reason', 'Disk/Storage failure')}")
        elif storage_status.get('status') == 'WARNING':
            warning_issues.append(f"Storage/Disks: {storage_status.get('reason', 'Disk/Storage issue')}")
        
        # Priority 3: VMs/CTs Status (with persistence)
        _t = time.time()
        vms_status = self._check_vms_cts_with_persistence()
        _perf_log("vms_cts", (time.time() - _t) * 1000)
        details['vms'] = vms_status
        if vms_status.get('status') == 'CRITICAL':
            critical_issues.append(f"VMs/CTs: {vms_status.get('reason', 'VM/CT failure')}")
        elif vms_status.get('status') == 'WARNING':
            warning_issues.append(f"VMs/CTs: {vms_status.get('reason', 'VM/CT issue')}")
        
        # Priority 4: Network Connectivity
        _t = time.time()
        network_status = self._check_network_optimized()
        _perf_log("network", (time.time() - _t) * 1000)
        details['network'] = network_status
        if network_status.get('status') == 'CRITICAL':
            critical_issues.append(f"Network: {network_status.get('reason', 'Network failure')}")
        elif network_status.get('status') == 'WARNING':
            warning_issues.append(f"Network: {network_status.get('reason', 'Network issue')}")
        
        # Priority 5: CPU Usage (with hysteresis)
        _t = time.time()
        cpu_status = self._check_cpu_with_hysteresis()
        _perf_log("cpu", (time.time() - _t) * 1000)
        details['cpu'] = cpu_status
        if cpu_status.get('status') == 'CRITICAL':
            critical_issues.append(f"CPU: {cpu_status.get('reason', 'CPU critical')}")
        elif cpu_status.get('status') == 'WARNING':
            warning_issues.append(f"CPU: {cpu_status.get('reason', 'CPU high')}")
        
        # Priority 6: Memory Usage (RAM and Swap)
        _t = time.time()
        memory_status = self._check_memory_comprehensive()
        _perf_log("memory", (time.time() - _t) * 1000)
        details['memory'] = memory_status
        if memory_status.get('status') == 'CRITICAL':
            critical_issues.append(f"Memory: {memory_status.get('reason', 'Memory critical')}")
        elif memory_status.get('status') == 'WARNING':
            warning_issues.append(f"Memory: {memory_status.get('reason', 'Memory high')}")
        
        # Priority 7: Log Analysis (with persistence)
        _t = time.time()
        logs_status = self._check_logs_with_persistence()
        _perf_log("logs", (time.time() - _t) * 1000)
        details['logs'] = logs_status
        if logs_status.get('status') == 'CRITICAL':
            critical_issues.append(f"Logs: {logs_status.get('reason', 'Critical log errors')}")
        elif logs_status.get('status') == 'WARNING':
            warning_issues.append(f"Logs: {logs_status.get('reason', 'Log warnings')}")
        
        # Priority 8: System Updates
        _t = time.time()
        updates_status = self._check_updates()
        _perf_log("updates", (time.time() - _t) * 1000)
        details['updates'] = updates_status
        if updates_status.get('status') == 'CRITICAL':
            critical_issues.append(f"Updates: {updates_status.get('reason', 'System not updated')}")
        elif updates_status.get('status') == 'WARNING':
            warning_issues.append(f"Updates: {updates_status.get('reason', 'Updates pending')}")
        elif updates_status.get('status') == 'INFO':
            info_issues.append(f"Updates: {updates_status.get('reason', 'Informational update notice')}")
        
        # Priority 9: Security Checks
        _t = time.time()
        security_status = self._check_security()
        _perf_log("security", (time.time() - _t) * 1000)
        details['security'] = security_status
        if security_status.get('status') == 'WARNING':
            warning_issues.append(f"Security: {security_status.get('reason', 'Security issue')}")
        elif security_status.get('status') == 'INFO':
            info_issues.append(f"Security: {security_status.get('reason', 'Security information')}")
        
        # Log total time for all checks
        _perf_log("TOTAL_HEALTH_CHECK", (time.time() - _t_total) * 1000)
        
        # --- Track UNKNOWN counts and persist if >= 3 consecutive cycles ---
        unknown_issues = []
        for cat_key, cat_data in details.items():
            cat_status = cat_data.get('status', 'OK')
            if cat_status == 'UNKNOWN':
                count = self._unknown_counts.get(cat_key, 0) + 1
                self._unknown_counts[cat_key] = min(count, 10)  # Cap to avoid unbounded growth
                unknown_issues.append(f"{cat_key}: {cat_data.get('reason', 'Check unavailable')}")
                if count == 3:  # Only persist on the exact 3rd cycle, not every cycle after
                    try:
                        health_persistence.record_unknown_persistent(
                            cat_key, cat_data.get('reason', 'Check unavailable'))
                    except Exception:
                        pass
            else:
                self._unknown_counts[cat_key] = 0
        
        # --- Determine Overall Status ---
        # Severity: CRITICAL > WARNING > UNKNOWN (capped at WARNING) > INFO > OK
        if critical_issues:
            overall = 'CRITICAL'
            summary = '; '.join(critical_issues[:3])
        elif warning_issues:
            overall = 'WARNING'
            summary = '; '.join(warning_issues[:3])
        elif unknown_issues:
            overall = 'WARNING'  # UNKNOWN caps at WARNING, never escalates to CRITICAL
            summary = '; '.join(unknown_issues[:3])
        elif info_issues:
            overall = 'OK'  # INFO statuses don't degrade overall health
            summary = '; '.join(info_issues[:3])
        else:
            overall = 'OK'
            summary = 'All systems operational'
        
        # --- Emit events for state changes (Bloque A: Notification prep) ---
        try:
            previous_overall = getattr(self, '_last_overall_status', None)
            if previous_overall and previous_overall != overall:
                # Overall status changed - emit event
                health_persistence.emit_event(
                    event_type='state_change',
                    category='overall',
                    severity=overall,
                    data={
                        'previous': previous_overall,
                        'current': overall,
                        'summary': summary
                    }
                )
            
            # Track per-category state changes
            previous_details = getattr(self, '_last_category_statuses', {})
            for cat_key, cat_data in details.items():
                cat_status = cat_data.get('status', 'OK')
                prev_status = previous_details.get(cat_key, 'OK')
                if prev_status != cat_status and cat_status in ('WARNING', 'CRITICAL'):
                    health_persistence.emit_event(
                        event_type='state_change',
                        category=cat_key,
                        severity=cat_status,
                        data={
                            'previous': prev_status,
                            'current': cat_status,
                            'reason': cat_data.get('reason', '')
                        }
                    )
            
            self._last_overall_status = overall
            self._last_category_statuses = {k: v.get('status', 'OK') for k, v in details.items()}
        except Exception:
            pass  # Event emission should never break health checks
        
        return {
            'overall': overall,
            'summary': summary,
            'details': details,
            'timestamp': datetime.now().isoformat()
        }
    
    def _check_cpu_with_hysteresis(self) -> Dict[str, Any]:
        """Check CPU with hysteresis to avoid flapping alerts - requires sustained high usage.
        
        With samples every ~10 seconds:
        - CRITICAL: 30 samples >= 95% in 300s window = 5 min sustained
        - WARNING: 30 samples >= 85% in 300s window = 5 min sustained  
        - RECOVERY: 12 samples < 75% in 120s window = 2 min below threshold
        """
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)  # 100ms sample - sufficient for health check
            current_time = time.time()
            
            state_key = 'cpu_usage'
            # Add this reading as well (supplements the sampler thread)
            self.state_history[state_key].append({
                'value': cpu_percent,
                'time': current_time
            })
            
            # Snapshot the list for thread-safe reading (sampler may append concurrently)
            cpu_snapshot = list(self.state_history[state_key])
            # Prune old entries via snapshot replacement (atomic assignment)
            self.state_history[state_key] = [
                entry for entry in cpu_snapshot
                if current_time - entry['time'] < 360
            ]
            
            # Count samples in the monitoring windows
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
            
            # Require enough samples to cover the sustained period
            # With ~10s sampling interval: 300s = ~30 samples, 120s = ~12 samples
            # Using slightly lower thresholds to account for timing variations
            CRITICAL_MIN_SAMPLES = 25  # ~250s of sustained high CPU
            WARNING_MIN_SAMPLES = 25   # ~250s of sustained elevated CPU
            RECOVERY_MIN_SAMPLES = 10  # ~100s of recovery
            
            if len(critical_samples) >= CRITICAL_MIN_SAMPLES:
                # Calculate actual duration from oldest to newest sample
                oldest = min(s['time'] for s in critical_samples)
                actual_duration = int(current_time - oldest)
                status = 'CRITICAL'
                reason = f'CPU >{self.CPU_CRITICAL}% sustained for {actual_duration}s'
                # Record the error
                health_persistence.record_error(
                    error_key='cpu_usage',
                    category='cpu',
                    severity='CRITICAL',
                    reason=reason,
                    details={'cpu_percent': cpu_percent, 'duration': actual_duration}
                )
            elif len(warning_samples) >= WARNING_MIN_SAMPLES and len(recovery_samples) < RECOVERY_MIN_SAMPLES:
                oldest = min(s['time'] for s in warning_samples)
                actual_duration = int(current_time - oldest)
                status = 'WARNING'
                reason = f'CPU >{self.CPU_WARNING}% sustained for {actual_duration}s'
                # Record the warning
                health_persistence.record_error(
                    error_key='cpu_usage',
                    category='cpu',
                    severity='WARNING',
                    reason=reason,
                    details={'cpu_percent': cpu_percent, 'duration': actual_duration}
                )
            else:
                status = 'OK'
                reason = None
                # CPU is normal - auto-resolve any existing CPU errors
                health_persistence.resolve_error('cpu_usage', 'CPU usage returned to normal')
            
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
            
            # Build checks dict for frontend expandable section
            checks = {
                'cpu_usage': {
                    'status': status,
                    'detail': 'Sustained high CPU usage' if status != 'OK' else 'Normal'
                }
            }
            if temp_status and temp_status.get('status') != 'UNKNOWN':
                t_status = temp_status.get('status', 'OK')
                checks['cpu_temperature'] = {
                    'status': t_status,
                    'detail': 'Temperature elevated' if t_status != 'OK' else 'Normal'
                }
            else:
                checks['cpu_temperature'] = {
                    'status': 'INFO',
                    'detail': 'No temperature sensor detected - install lm-sensors if hardware supports it',
                }
            
            result['checks'] = checks
            return result
            
        except Exception as e:
            return {'status': 'UNKNOWN', 'reason': f'CPU check failed: {str(e)}', 'dismissable': True}
    
    def _check_cpu_temperature(self) -> Optional[Dict[str, Any]]:
        """
        Check CPU temperature with temporal logic:
        - WARNING if temp >80°C sustained for >3 minutes
        - Auto-clears if temp ≤80°C for 30 seconds
        - No dismiss button (non-dismissable)
        """
        cache_key = 'cpu_temp'
        current_time = time.time()
        
        # Check every 10 seconds instead of 60
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 10:
                return self.cached_results.get(cache_key)
        
        try:
            # Read temperature directly from sensors command (not journalctl)
            result = subprocess.run(
                ['sensors', '-u'],
                capture_output=True, text=True, timeout=3
            )
            
            temps = []
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.split('\n'):
                    # Look for temperature input lines like "temp1_input: 42.000"
                    if '_input' in line and 'temp' in line.lower():
                        try:
                            temp = float(line.split(':')[1].strip())
                            if 0 < temp < 150:  # Sanity check for valid temp range
                                temps.append(temp)
                        except:
                            continue
            
            if temps:
                max_temp = max(temps)
                
                state_key = 'cpu_temp_history'
                # Add this reading (supplements the sampler thread)
                self.state_history[state_key].append({
                    'value': max_temp,
                    'time': current_time
                })
                
                # Snapshot for thread-safe reading, then atomic prune
                temp_snapshot = list(self.state_history[state_key])
                self.state_history[state_key] = [
                    entry for entry in temp_snapshot
                    if current_time - entry['time'] < 240
                ]
                
                # Check if temperature >80°C for more than 3 minutes (180 seconds)
                high_temp_samples = [
                    entry for entry in self.state_history[state_key]
                    if entry['value'] > 80 and current_time - entry['time'] <= 180
                ]
                
                # Check if temperature ≤80°C for last 30 seconds (recovery)
                recovery_samples = [
                    entry for entry in self.state_history[state_key]
                    if entry['value'] <= 80 and current_time - entry['time'] <= 30
                ]
                
                # Require at least 18 samples over 3 minutes (one every 10 seconds) to trigger alert
                if len(high_temp_samples) >= 18:
                    # Temperature has been >80°C for >3 minutes - calculate actual duration
                    oldest = min(s['time'] for s in high_temp_samples)
                    actual_duration = int(current_time - oldest)
                    actual_minutes = actual_duration // 60
                    actual_seconds = actual_duration % 60
                    duration_str = f'{actual_minutes}m {actual_seconds}s' if actual_minutes > 0 else f'{actual_seconds}s'
                    
                    status = 'WARNING'
                    reason = f'CPU temperature {max_temp}°C >80°C sustained for {duration_str}'
                    
                    # Record non-dismissable error
                    health_persistence.record_error(
                        error_key='cpu_temperature',
                        category='temperature',
                        severity='WARNING',
                        reason=reason,
                        details={'temperature': max_temp, 'duration': actual_duration, 'dismissable': False}
                    )
                elif len(recovery_samples) >= 3:
                    # Temperature has been ≤80°C for 30 seconds - clear the error
                    status = 'OK'
                    reason = None
                    health_persistence.resolve_error('cpu_temperature', 'Temperature recovered')
                else:
                    # Temperature is elevated but not long enough, or recovering but not yet cleared
                    # Check if we already have an active error
                    if health_persistence.is_error_active('cpu_temperature', category='temperature'):
                        # Keep the warning active
                        status = 'WARNING'
                        reason = f'CPU temperature {max_temp}°C still elevated'
                    else:
                        # No active warning yet
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
            
            mem_critical_samples = [
                entry for entry in self.state_history[state_key]
                if entry['mem_percent'] >= 90 and
                current_time - entry['time'] <= self.MEMORY_DURATION
            ]

            mem_warning_samples = [
                entry for entry in self.state_history[state_key]
                if entry['mem_percent'] >= self.MEMORY_WARNING and
                current_time - entry['time'] <= self.MEMORY_DURATION
            ]

            swap_critical = sum(
                1 for entry in self.state_history[state_key]
                if entry['swap_vs_ram'] > 20 and
                current_time - entry['time'] <= self.SWAP_CRITICAL_DURATION
            )

            # Require sustained high usage across most of the 300s window.
            # With ~30s sampling: 300s = ~10 samples, so 8 ≈ 240s sustained.
            # Mirrors CPU's ~83% coverage threshold (25/30).
            MEM_CRITICAL_MIN_SAMPLES = 8
            MEM_WARNING_MIN_SAMPLES = 8

            mem_critical_count = len(mem_critical_samples)
            mem_warning_count = len(mem_warning_samples)

            if mem_critical_count >= MEM_CRITICAL_MIN_SAMPLES:
                oldest = min(s['time'] for s in mem_critical_samples)
                actual_duration = int(current_time - oldest)
                status = 'CRITICAL'
                reason = f'RAM >90% sustained for {actual_duration}s'
            elif swap_critical >= 2:
                status = 'CRITICAL'
                reason = f'Swap >20% of RAM ({swap_vs_ram:.1f}%)'
            elif mem_warning_count >= MEM_WARNING_MIN_SAMPLES:
                oldest = min(s['time'] for s in mem_warning_samples)
                actual_duration = int(current_time - oldest)
                status = 'WARNING'
                reason = f'RAM >{self.MEMORY_WARNING}% sustained for {actual_duration}s'
            else:
                status = 'OK'
                reason = None
            
            ram_avail_gb = round(memory.available / (1024**3), 2)
            ram_total_gb = round(memory.total / (1024**3), 2)
            swap_used_gb = round(swap.used / (1024**3), 2)
            swap_total_gb = round(swap.total / (1024**3), 2)
            
            # Determine per-sub-check status
            ram_status = 'CRITICAL' if mem_percent >= 90 and mem_critical_count >= MEM_CRITICAL_MIN_SAMPLES else ('WARNING' if mem_percent >= self.MEMORY_WARNING and mem_warning_count >= MEM_WARNING_MIN_SAMPLES else 'OK')
            swap_status = 'CRITICAL' if swap_critical >= 2 else 'OK'
            
            result = {
                'status': status,
                'ram_percent': round(mem_percent, 1),
                'ram_available_gb': ram_avail_gb,
                'swap_percent': round(swap_percent, 1),
                'swap_used_gb': swap_used_gb,
                'checks': {
                    'ram_usage': {
                        'status': ram_status,
                        'detail': 'High RAM usage sustained' if ram_status != 'OK' else 'Normal'
                    },
                    'swap_usage': {
                        'status': swap_status,
                        'detail': 'Excessive swap usage' if swap_status != 'OK' else ('Normal' if swap.total > 0 else 'No swap configured')
                    }
                }
            }
            
            if reason:
                result['reason'] = reason
            
            return result
            
        except Exception as e:
            return {'status': 'UNKNOWN', 'reason': f'Memory check failed: {str(e)}', 'dismissable': True}
    
    def _check_storage_optimized(self) -> Dict[str, Any]:
        """
        Optimized storage check - monitors Proxmox storages from pvesm status.
        Checks for inactive storages, disk health from SMART/events, and ZFS pool health.
        """
        issues = []
        storage_details = {}
        
        # Check disk usage and mount status for important mounts.
        # We detect actual mountpoints dynamically rather than hard-coding.
        critical_mounts = set()
        critical_mounts.add('/')
        try:
            for part in psutil.disk_partitions(all=False):
                mp = part.mountpoint
                # Include standard system mounts and PVE storage
                if mp in ('/', '/var', '/tmp', '/boot', '/boot/efi') or \
                   mp.startswith('/var/lib/vz') or mp.startswith('/mnt/'):
                    critical_mounts.add(mp)
        except Exception:
            pass
        critical_mounts = sorted(critical_mounts)
        
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
                    error_key = f'disk_space_{mount_point}'
                    if fs_status['status'] != 'OK':
                        issues.append(f"{mount_point}: {fs_status['reason']}")
                        storage_details[mount_point] = fs_status
                        # Record persistent error for notifications
                        usage = psutil.disk_usage(mount_point)
                        avail_gb = usage.free / (1024**3)
                        if avail_gb >= 1:
                            avail_str = f"{avail_gb:.1f} GiB"
                        else:
                            avail_str = f"{usage.free / (1024**2):.0f} MiB"
                        health_persistence.record_error(
                            error_key=error_key,
                            category='disk',
                            severity=fs_status['status'],
                            reason=f'{mount_point}: {fs_status["reason"]}',
                            details={
                                'mount': mount_point,
                                'used': str(round(usage.percent, 1)),
                                'available': avail_str,
                                'dismissable': False,
                            }
                        )
                    else:
                        # Space recovered -- clear any previous alert
                        health_persistence.clear_error(error_key)
            except Exception:
                pass # Silently skip if mountpoint check fails
        
        # Check ZFS pool health status
        zfs_pool_issues = self._check_zfs_pool_health()
        if zfs_pool_issues:
            for pool_name, pool_info in zfs_pool_issues.items():
                issues.append(f'{pool_name}: {pool_info["reason"]}')
                storage_details[pool_name] = pool_info
                
                # Record error for notification system
                real_pool = pool_info.get('pool_name', pool_name)
                zfs_error_key = f'zfs_pool_{real_pool}'
                zfs_reason = f'ZFS pool {real_pool}: {pool_info["reason"]}'
                try:
                    if not health_persistence.is_error_active(zfs_error_key, category='disks'):
                        health_persistence.record_error(
                            error_key=zfs_error_key,
                            category='disks',
                            severity=pool_info.get('status', 'WARNING'),
                            reason=zfs_reason,
                            details={
                                'pool_name': real_pool,
                                'health': pool_info.get('health', ''),
                                'device': f'zpool:{real_pool}',
                                'dismissable': False,
                            }
                        )
                except Exception:
                    pass
                
                # Record as permanent disk observation
                try:
                    health_persistence.record_disk_observation(
                        device_name=f'zpool_{real_pool}',
                        serial=None,
                        error_type='zfs_pool_error',
                        error_signature=f'zfs_{real_pool}_{pool_info.get("health", "unknown")}',
                        raw_message=zfs_reason,
                        severity=pool_info.get('status', 'WARNING').lower(),
                    )
                except Exception:
                    pass
        else:
            # ZFS pools are healthy -- clear any previously recorded ZFS errors
            if self.capabilities.get('has_zfs'):
                try:
                    active_errors = health_persistence.get_active_errors()
                    for error in active_errors:
                        if error.get('error_key', '').startswith('zfs_pool_'):
                            health_persistence.clear_error(error['error_key'])
                except Exception:
                    pass
        
        # Check disk health from Proxmox task log or system logs (SMART, etc.)
        disk_health_issues = self._check_disk_health_from_events()
        smart_warnings_found = False
        if disk_health_issues:
            for disk, issue in disk_health_issues.items():
                # Only add if not already covered by critical mountpoint issues
                if disk not in storage_details or storage_details[disk].get('status') == 'OK':
                    issues.append(f'{disk}: {issue["reason"]}')
                    storage_details[disk] = issue
                
                # Track if any SMART warnings were found (for smart_health sub-check)
                if issue.get('smart_lines'):
                    smart_warnings_found = True
                
                # Record error with full details for notification system
                # Avoid duplicate: if dmesg I/O errors already cover this disk
                # (disk_{device}), skip the journal SMART notification to prevent
                # the user getting two alerts for the same underlying problem.
                device = issue.get('device', disk.replace('/dev/', ''))
                io_error_key = f'disk_{device}'
                error_key = f'smart_{device}'
                reason = f'{disk}: {issue["reason"]}'
                severity = issue.get('status', 'WARNING')
                
                # Get serial for this disk (cached to avoid repeated smartctl calls)
                disk_id = self._get_disk_identity(device)
                disk_serial = disk_id['serial']
                disk_model = disk_id['model']
                
                try:
                    if (not health_persistence.is_error_active(io_error_key, category='disks') and
                        not health_persistence.is_error_active(error_key, category='disks')):
                        health_persistence.record_error(
                            error_key=error_key,
                            category='disks',
                            severity=severity,
                            reason=reason,
                            details={
                                'disk': device,
                                'device': disk,
                                'block_device': device,
                                'serial': disk_serial,
                                'model': disk_model,
                                'smart_status': 'WARNING',
                                'smart_lines': issue.get('smart_lines', []),
                                'io_lines': issue.get('io_lines', []),
                                'sample': issue.get('sample', ''),
                                'source': 'journal',
                                'dismissable': True,
                            }
                        )
                    # Register the disk for observation tracking (worst_health no longer used)
                    if disk_serial:
                        health_persistence.register_disk(device, disk_serial, disk_model, 0)
                except Exception:
                    pass
        
        # Check LVM status
        lvm_status = self._check_lvm()
        if lvm_status.get('status') == 'WARNING':
            # LVM volumes might be okay but indicate potential issues
            issues.append(f"LVM check: {lvm_status.get('reason')}")
            storage_details['lvm_check'] = lvm_status
        
        # Check dmesg for real-time I/O errors (dmesg-based, complements journalctl SMART checks)
        dmesg_io_result = self._check_disks_optimized()
        if dmesg_io_result.get('status') != 'OK':
            dmesg_details = dmesg_io_result.get('details', {})
            for disk_path, disk_info in dmesg_details.items():
                if disk_path not in storage_details or storage_details[disk_path].get('status') == 'OK':
                    issues.append(f'{disk_path}: {disk_info.get("reason", "I/O errors")}')
                    storage_details[disk_path] = disk_info
                
                device = disk_path.replace('/dev/', '')
                io_severity = disk_info.get('status', 'WARNING').lower()
                
                # Get serial for proper disk tracking (cached)
                io_id = self._get_disk_identity(device)
                io_serial = io_id['serial']
                io_model = io_id['model']
                
                # Register the disk for observation tracking (worst_health no longer used)
                try:
                    if io_serial:
                        health_persistence.register_disk(device, io_serial, io_model, 0)
                except Exception:
                    pass
        
        # Build checks dict from storage_details
        # We consolidate disk error entries (like /Dev/Sda) into physical disk entries
        # and only show disks with problems (not healthy ones).
        checks = {}
        disk_errors_by_device = {}  # Collect disk errors for consolidation
        
        for key, val in storage_details.items():
            # Check if this is a disk device entry (e.g., /Dev/Sda, /dev/sda, sda)
            key_lower = key.lower()
            is_disk_entry = (
                key_lower.startswith('/dev/') or 
                key_lower.startswith('dev/') or
                (len(key_lower) <= 10 and (key_lower.startswith('sd') or 
                 key_lower.startswith('nvme') or key_lower.startswith('hd')))
            )
            
            if is_disk_entry:
                # Extract device name and collect for consolidation
                device_name = key_lower.replace('/dev/', '').replace('dev/', '').strip('/')
                if device_name and len(device_name) <= 15:
                    if device_name not in disk_errors_by_device:
                        disk_errors_by_device[device_name] = {
                            'status': val.get('status', 'WARNING'),
                            'detail': val.get('reason', ''),
                            'error_key': val.get('error_key'),
                            'dismissable': val.get('dismissable', True),
                        }
                    else:
                        # Merge: keep worst status
                        existing = disk_errors_by_device[device_name]
                        if val.get('status') == 'CRITICAL':
                            existing['status'] = 'CRITICAL'
                        # Append detail if different - with smart deduplication
                        new_detail = val.get('reason', '')
                        existing_detail = existing.get('detail', '')
                        if new_detail and new_detail not in existing_detail:
                            # Check for semantic duplicates by extracting key info
                            # Extract device references and key metrics from both
                            new_parts = set(p.strip() for p in new_detail.replace(';', '\n').split('\n') if p.strip())
                            existing_parts = set(p.strip() for p in existing_detail.replace(';', '\n').split('\n') if p.strip())
                            
                            # Find truly new information (parts not already present)
                            unique_new_parts = []
                            for part in new_parts:
                                is_duplicate = False
                                # Check if this part's core content exists in any existing part
                                part_lower = part.lower()
                                for ex_part in existing_parts:
                                    ex_lower = ex_part.lower()
                                    # If >60% of words overlap, consider it duplicate
                                    part_words = set(part_lower.split())
                                    ex_words = set(ex_lower.split())
                                    if part_words and ex_words:
                                        overlap = len(part_words & ex_words) / min(len(part_words), len(ex_words))
                                        if overlap > 0.6:
                                            is_duplicate = True
                                            break
                                if not is_duplicate:
                                    unique_new_parts.append(part)
                            
                            # Only append truly unique parts
                            if unique_new_parts:
                                unique_text = '; '.join(unique_new_parts)
                                existing['detail'] = f"{existing_detail}; {unique_text}".strip('; ')
                    continue  # Don't add raw disk error entry, we'll add consolidated later
            
            # Non-disk entries go directly to checks
            checks[key] = {
                'status': val.get('status', 'OK'),
                'detail': val.get('reason', 'OK'),
                **{k: v for k, v in val.items() if k not in ('status', 'reason')}
            }
        
        # Get physical disk info for matching errors to disks
        # This uses the same detection as flask_server.py /api/storage/info
        physical_disks = {}
        try:
            result = subprocess.run(
                ['lsblk', '-b', '-d', '-n', '-o', 'NAME,SIZE,TYPE,TRAN'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] == 'disk':
                        disk_name = parts[0]
                        # Skip virtual devices
                        if disk_name.startswith(('zd', 'zram', 'loop', 'ram', 'dm-')):
                            continue
                        tran = parts[3].upper() if len(parts) > 3 else ''
                        is_usb = tran == 'USB'
                        is_nvme = disk_name.startswith('nvme')
                        
                        # Get serial from smartctl
                        serial = ''
                        model = ''
                        try:
                            smart_result = subprocess.run(
                                ['smartctl', '-i', '-j', f'/dev/{disk_name}'],
                                capture_output=True, text=True, timeout=5
                            )
                            if smart_result.returncode in (0, 4):  # 4 = SMART not available but info OK
                                import json
                                smart_data = json.loads(smart_result.stdout)
                                serial = smart_data.get('serial_number', '')
                                model = smart_data.get('model_name', '') or smart_data.get('model_family', '')
                        except Exception:
                            pass
                        
                        physical_disks[disk_name] = {
                            'serial': serial,
                            'model': model,
                            'is_usb': is_usb,
                            'is_nvme': is_nvme,
                            'disk_type': 'USB' if is_usb else ('NVMe' if is_nvme else 'SATA'),
                        }
        except Exception:
            pass
        
        # NOTE: disk_observations is the PERMANENT historical record of disk events
        # and must NOT be used as a source for Health Monitor warnings.
        # Only the `errors` table (active alerts) drives the Health Monitor view.
        # Observations are visible separately in the disk detail UI, where users
        # can review the full history and dismiss individual entries if desired.
        #
        # Previous behavior read disk_observations here and created phantom warnings
        # that persisted even after the underlying error was gone — conflating the
        # permanent history with the current health state.
        
        # Add consolidated disk entries (only for disks with errors)
        for device_name, error_info in disk_errors_by_device.items():
            # Try to find this disk in physical_disks for enriched info
            disk_info = physical_disks.get(device_name, {})
            
            # If not found by name, try to match by serial (from error details)
            if not disk_info:
                error_serial = error_info.get('serial', '')
                if error_serial:
                    for dk, di in physical_disks.items():
                        if di.get('serial', '').lower() == error_serial.lower():
                            disk_info = di
                            device_name = dk  # Update device name to matched disk
                            break
            
            # Determine disk type
            disk_type = disk_info.get('disk_type', 'SATA')
            if not disk_info:
                # Fallback detection
                if device_name.startswith('nvme'):
                    disk_type = 'NVMe'
                else:
                    # Check if USB via sysfs
                    try:
                        usb_check = subprocess.run(
                            ['readlink', '-f', f'/sys/block/{device_name}'],
                            capture_output=True, text=True, timeout=2
                        )
                        if 'usb' in usb_check.stdout.lower():
                            disk_type = 'USB'
                    except Exception:
                        pass
            
            serial = disk_info.get('serial', '')
            model = disk_info.get('model', '')
            
            # Use current status directly from Proxmox/SMART - no persistent worst_health
            # Historical observations are preserved separately in disk_observations table
            current_status = error_info.get('status', 'WARNING')
            final_status = current_status
            
            # Build detail string with serial/model if available
            detail = error_info.get('detail', error_info.get('reason', 'Unknown error'))
            if serial and serial not in detail:
                detail = f"{serial} - {detail}"
            
            # Create consolidated disk entry
            check_key = f'/dev/{device_name}'
            checks[check_key] = {
                'status': final_status,
                'detail': detail,
                'disk_type': disk_type,
                'device': f'/dev/{device_name}',
                'serial': serial,
                'model': model,
                'error_key': error_info.get('error_key') or f'disk_smart_{device_name}',
                'dismissable': error_info.get('dismissable', True),
                'is_disk_entry': True,
            }
            
            # Add to issues array if WARNING or CRITICAL (ensures category status is correct)
            if final_status in ('WARNING', 'CRITICAL'):
                issue_msg = f'{check_key}: {detail}'
                if issue_msg not in issues:
                    issues.append(issue_msg)
            
            # Register disk in persistence if not already (for worst_health tracking)
            try:
                health_persistence.register_disk(device_name, serial if serial else None, model, 0)
            except Exception:
                pass
        
        # ALWAYS add descriptive entries for capabilities this server has.
        # When everything is OK, they show as OK.  When there are issues,
        # they still appear so the user can see the full picture (e.g.
        # LVM is OK even though I/O errors exist on a disk).
        if 'root_filesystem' not in checks:
            checks['root_filesystem'] = checks.pop('/', None) or {'status': 'OK', 'detail': 'Mounted read-write, space OK'}
        if 'io_errors' not in checks:
            # Only add OK if no disk I/O errors are present in checks
            has_io = any(v.get('error_count') or 'I/O' in str(v.get('detail', '')) for v in checks.values())
            if not has_io:
                checks['io_errors'] = {'status': 'OK', 'detail': 'No I/O errors in dmesg'}
        if self.capabilities.get('has_smart') and 'smart_health' not in checks:
            if not smart_warnings_found:
                checks['smart_health'] = {'status': 'OK', 'detail': 'No SMART warnings in journal'}
            # When smart_warnings_found is True, the per-disk sub-checks
            # (/Dev/Sda etc.) already carry all the detail and dismiss logic.
            # Adding a separate smart_health WARNING would just duplicate them.
        if self.capabilities.get('has_zfs') and 'zfs_pools' not in checks:
            checks['zfs_pools'] = {'status': 'OK', 'detail': 'ZFS pools healthy'}
        if self.capabilities.get('has_lvm') and 'lvm_volumes' not in checks and 'lvm_check' not in checks:
            checks['lvm_volumes'] = {'status': 'OK', 'detail': 'LVM volumes OK'}
        
        if not issues:
            return {'status': 'OK', 'checks': checks}
        
        # ── Mark dismissed checks ──
        # If an error_key in a check has been acknowledged (dismissed) in the
        # persistence DB, mark the check as dismissed so the frontend renders
        # it in blue instead of showing WARNING + Dismiss button.
        # Also recalculate category status: if ALL warning/critical checks are
        # dismissed, downgrade the category to OK.
        try:
            all_dismissed = True
            for check_key, check_val in checks.items():
                ek = check_val.get('error_key')
                if not ek:
                    continue
                check_status = (check_val.get('status') or 'OK').upper()
                if check_status in ('WARNING', 'CRITICAL'):
                    if health_persistence.is_error_acknowledged(ek):
                        check_val['dismissed'] = True
                    else:
                        all_dismissed = False
            
            # If every non-OK check is dismissed, downgrade the category
            non_ok_checks = [v for v in checks.values()
                             if (v.get('status') or 'OK').upper() in ('WARNING', 'CRITICAL')]
            if non_ok_checks and all(v.get('dismissed') for v in non_ok_checks):
                # All issues are dismissed -- category shows as OK to avoid
                # persistent WARNING after user has acknowledged.
                return {
                    'status': 'OK',
                    'reason': '; '.join(issues[:3]),
                    'details': storage_details,
                    'checks': checks,
                    'all_dismissed': True,
                }
        except Exception:
            pass
        
        # Determine overall status
        has_critical = any(
            d.get('status') == 'CRITICAL' for d in storage_details.values()
        )
        
        return {
            'status': 'CRITICAL' if has_critical else 'WARNING',
            'reason': '; '.join(issues[:3]),
            'details': storage_details,
            'checks': checks
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
    
    @staticmethod
    def _make_io_obs_signature(disk: str, sample: str) -> str:
        """Create a stable observation signature for I/O errors on a disk.
        
        All ATA errors on the same disk (exception Emask, revalidation failed,
        hard resetting link, SError, etc.) map to ONE signature per error family.
        This ensures that "Emask 0x1 SAct 0xc1000000" and "Emask 0x1 SAct 0x804000"
        and "revalidation failed" all dedup into the same observation.
        """
        if not sample:
            return f'io_{disk}_generic'
        
        s = sample.lower()
        
        # Classify into error families (order matters: first match wins)
        families = [
            # ATA controller errors: exception, emask, revalidation, reset
            # All these are symptoms of the same underlying connection issue
            (r'exception\s+emask|emask\s+0x|revalidation failed|hard resetting link|'
             r'serror.*badcrc|comreset|link is slow|status.*drdy',
             'ata_connection_error'),
            # SCSI / block-layer errors
            (r'i/o error|blk_update_request|medium error|sense key',
             'block_io_error'),
            # Failed commands (READ/WRITE FPDMA QUEUED)
            (r'failed command|fpdma queued',
             'ata_failed_command'),
        ]
        
        for pattern, family in families:
            if re.search(pattern, s):
                return f'io_{disk}_{family}'
        
        # Fallback: generic per-disk
        return f'io_{disk}_generic'

    def _resolve_ata_to_disk(self, ata_port: str) -> str:
        """Resolve an ATA controller name (e.g. 'ata8') to a block device (e.g. 'sda').
        
        Uses /sys/class/ata_port/ symlinks and /sys/block/ to find the mapping.
        Falls back to parsing dmesg for 'ata8: SATA link up' -> 'sd 7:0:0:0: [sda]'.
        """
        if not ata_port or not ata_port.startswith('ata'):
            return ata_port
        
        port_num = ata_port.replace('ata', '')
        
        # Method 1: Walk /sys/class/ata_port/ -> host -> target -> block
        try:
            ata_path = f'/sys/class/ata_port/{ata_port}'
            if os.path.exists(ata_path):
                device_path = os.path.realpath(ata_path)
                # Walk up to find the SCSI host, then find block devices
                # Path: /sys/devices/.../ataX/hostY/targetY:0:0/Y:0:0:0/block/sdZ
                for root, dirs, files in os.walk(os.path.dirname(device_path)):
                    if 'block' in dirs:
                        block_path = os.path.join(root, 'block')
                        devs = os.listdir(block_path)
                        if devs:
                            return devs[0]  # e.g. 'sda'
        except (OSError, IOError):
            pass
        
        # Method 2: Parse dmesg for ATA link messages
        try:
            result = subprocess.run(
                ['dmesg', '--notime'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                # Look for "ata8: SATA link up" followed by "sd X:0:0:0: [sda]"
                lines = result.stdout.split('\n')
                host_num = None
                for line in lines:
                    m = re.search(rf'{ata_port}:\s+SATA link', line)
                    if m:
                        # ata port number maps to host(N-1) typically
                        host_num = int(port_num) - 1
                    if host_num is not None:
                        m2 = re.search(rf'sd\s+{host_num}:\d+:\d+:\d+:\s+\[(\w+)\]', line)
                        if m2:
                            return m2.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass
        
        # Method 3: Use /sys/block/sd* and trace back to ATA host number
        # ata8 => host7 (N-1) or host8 depending on controller numbering
        try:
            for sd in sorted(os.listdir('/sys/block')):
                if not sd.startswith('sd'):
                    continue
                # /sys/block/sdX/device -> ../../hostN/targetN:0:0/N:0:0:0
                dev_link = f'/sys/block/{sd}/device'
                if os.path.islink(dev_link):
                    real_path = os.path.realpath(dev_link)
                    # Check if 'ataX' appears in the device path
                    if f'/{ata_port}/' in real_path or f'/ata{port_num}/' in real_path:
                        return sd
                    # Also check host number mapping: ata8 -> host7 (N-1 convention)
                    for offset in (0, -1):
                        host_n = int(port_num) + offset
                        if host_n >= 0 and f'/host{host_n}/' in real_path:
                            # Verify: check if ataX appears in the chain
                            parent = real_path
                            while parent and parent != '/':
                                parent = os.path.dirname(parent)
                                if os.path.basename(parent) == ata_port:
                                    return sd
                                # Check 1 level: /sys/devices/.../ataX/hostY/...
                                ata_check = os.path.join(os.path.dirname(parent), ata_port)
                                if os.path.exists(ata_check):
                                    return sd
        except (OSError, IOError, ValueError):
            pass
        
        return ata_port  # Return original if resolution fails
    
    def _identify_block_device(self, device: str) -> str:
        """
        Identify a block device by querying lsblk.
        Returns a human-readable string like:
          "KINGSTON SA400S37960G (SSD, 894.3G) mounted at /mnt/data"
        Returns empty string if the device is not found in lsblk.
        """
        if not device or device == 'unknown':
            return ''
        try:
            candidates = [device]
            base = disk_base_name(device)
            if base != device:
                candidates.append(base)
            
            for dev in candidates:
                dev_path = f'/dev/{dev}' if not dev.startswith('/') else dev
                result = subprocess.run(
                    ['lsblk', '-ndo', 'NAME,MODEL,SIZE,TRAN,MOUNTPOINT,ROTA', dev_path],
                    capture_output=True, text=True, timeout=3
                )
                if result.returncode == 0 and result.stdout.strip():
                    fields = result.stdout.strip().split(None, 5)
                    name = fields[0] if len(fields) > 0 else dev
                    model = fields[1] if len(fields) > 1 and fields[1] else 'Unknown model'
                    size = fields[2] if len(fields) > 2 else '?'
                    tran = (fields[3] if len(fields) > 3 else '').upper()
                    mountpoint = fields[4] if len(fields) > 4 and fields[4] else ''
                    rota = fields[5].strip() if len(fields) > 5 else '1'
                    
                    if tran == 'USB':
                        disk_type = 'USB'
                    elif tran == 'NVME' or 'nvme' in name:
                        disk_type = 'NVMe'
                    elif rota == '0':
                        disk_type = 'SSD'
                    else:
                        disk_type = 'HDD'
                    
                    info = f'{model} ({disk_type}, {size})'
                    if mountpoint:
                        info += f' mounted at {mountpoint}'
                    elif dev != device:
                        part_result = subprocess.run(
                            ['lsblk', '-ndo', 'MOUNTPOINT', f'/dev/{device}'],
                            capture_output=True, text=True, timeout=2
                        )
                        part_mount = part_result.stdout.strip() if part_result.returncode == 0 else ''
                        if part_mount:
                            info += f' partition {device} mounted at {part_mount}'
                        else:
                            info += ' -- not mounted'
                    else:
                        info += ' -- not mounted'
                    return info
            return ''
        except Exception:
            return ''
    
    def _device_fingerprint(self, disk_name: str):
        """Cheap stat-based fingerprint to detect hot-swap.

        udev removes and recreates /dev/sdX when a disk is hot-swapped, so the
        device node's ctime + size changes. Returns None if the device is gone.
        """
        try:
            dev_path = f'/dev/{disk_name}' if not disk_name.startswith('/') else disk_name
            st = os.stat(dev_path)
            return (st.st_ctime_ns, st.st_rdev)
        except OSError:
            return None

    def _get_disk_identity(self, disk_name: str) -> Dict[str, str]:
        """Get disk serial/model with caching. Avoids repeated smartctl -i calls.

        Returns {'serial': '...', 'model': '...'} or empty values on failure.
        Cache is invalidated if the underlying device node fingerprint changes
        (hot-swap), and also drops the matching SMART cache entry so the new
        drive isn't masked by the previous drive's status.
        """
        fp = self._device_fingerprint(disk_name)
        cached = self._disk_identity_cache.get(disk_name)

        if fp is None:
            # Device removed - drop any stale entries so a re-added disk re-reads
            self._disk_identity_cache.pop(disk_name, None)
            self._smart_cache.pop(disk_name, None)
            return {'serial': '', 'model': ''}

        if cached and cached.get('_fp') == fp:
            return {'serial': cached.get('serial', ''), 'model': cached.get('model', '')}

        if cached:
            # Hot-swap detected - drop SMART cache so we don't report old drive's health
            self._smart_cache.pop(disk_name, None)

        result = {'serial': '', 'model': '', '_fp': fp}
        try:
            dev_path = f'/dev/{disk_name}' if not disk_name.startswith('/') else disk_name
            proc = subprocess.run(
                ['smartctl', '-i', '-j', dev_path],
                capture_output=True, text=True, timeout=5
            )
            if proc.returncode in (0, 4):
                import json as _json
                data = _json.loads(proc.stdout)
                result['serial'] = data.get('serial_number', '')
                result['model'] = data.get('model_name', '') or data.get('model_family', '')
        except Exception:
            pass

        self._disk_identity_cache[disk_name] = result
        return {'serial': result['serial'], 'model': result['model']}

    def _quick_smart_health(self, disk_name: str) -> str:
        """Quick SMART health check for a single disk. Returns 'PASSED', 'FAILED', or 'UNKNOWN'.

        Results are cached for 30 minutes to reduce disk queries - SMART status rarely changes.
        """
        if not disk_name or disk_name.startswith('ata') or disk_name.startswith('zram'):
            return 'UNKNOWN'
        
        # Check cache first (and evict stale entries periodically)
        current_time = time.time()
        cache_key = disk_name
        # Hot-swap guard: if the device node was recreated, ignore the cached
        # result so a new drive isn't shadowed by the previous one's status.
        fp = self._device_fingerprint(disk_name)
        cached = self._smart_cache.get(cache_key)
        if cached and current_time - cached['time'] < self._SMART_CACHE_TTL and cached.get('fp') == fp:
            return cached['result']
        # Evict expired entries to prevent unbounded growth
        if len(self._smart_cache) > 50:
            self._smart_cache = {
                k: v for k, v in self._smart_cache.items()
                if current_time - v['time'] < self._SMART_CACHE_TTL * 2
            }
        
        try:
            dev_path = f'/dev/{disk_name}' if not disk_name.startswith('/') else disk_name
            result = subprocess.run(
                ['smartctl', '--health', '-j', dev_path],
                capture_output=True, text=True, timeout=5
            )
            import json as _json
            data = _json.loads(result.stdout)
            passed = data.get('smart_status', {}).get('passed', None)
            if passed is True:
                smart_result = 'PASSED'
            elif passed is False:
                smart_result = 'FAILED'
            else:
                smart_result = 'UNKNOWN'
            
            # Cache the result with the device fingerprint for hot-swap invalidation
            self._smart_cache[cache_key] = {'result': smart_result, 'time': current_time, 'fp': fp}
            return smart_result
        except Exception:
            return 'UNKNOWN'

    def _check_all_disks_smart(self, fallback: str = 'UNKNOWN') -> str:
        """Check SMART health of ALL physical disks.
        
        Used when an ATA port can't be resolved to a specific /dev/sdX.
        If ALL disks report PASSED, returns 'PASSED' (errors are transient).
        If ANY disk reports FAILED, returns 'FAILED'.
        Otherwise returns the fallback value.
        """
        try:
            # List all block devices (exclude partitions, loop, zram, dm)
            result = subprocess.run(
                ['lsblk', '-dnpo', 'NAME,TYPE'],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode != 0:
                return fallback
            
            disks = []
            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 2 and parts[1] == 'disk':
                    disks.append(parts[0])  # e.g. /dev/sda
            
            if not disks:
                return fallback
            
            all_passed = True
            any_failed = False
            checked = 0
            
            for dev in disks:
                health = self._quick_smart_health(dev)
                if health == 'PASSED':
                    checked += 1
                elif health == 'FAILED':
                    any_failed = True
                    break
                else:
                    all_passed = False  # Can't confirm this disk
            
            if any_failed:
                return 'FAILED'
            if all_passed and checked > 0:
                return 'PASSED'
            return fallback
        except Exception:
            return fallback
    
    def _reconcile_stale_disk_warnings(self) -> None:
        """
        Reconcile persisted disk_<name> warnings against the current host
        state before each disk scan.

        The disk-scan loop only resolves an error when the device appears
        in the current dmesg window with zero events. After a reboot,
        dmesg is empty for that device, so the loop never iterates it,
        and a `disk_<name>` WARNING recorded as "SMART: unavailable"
        during a noisy shutdown can stay active forever — the dashboard
        keeps showing an orange "Warning" badge for a disk whose SMART
        is in fact PASSED.

        This pass walks the active disk_* errors (skipping disk_fs_*,
        which is already reconciled separately below) and:

          - device gone from /dev/ → resolve as "Device no longer present"
          - device present + SMART now PASSED → resolve as "Transient
            I/O cleared, SMART now healthy"
          - device present + SMART still unavailable → leave warning
            active (the original condition is still ambiguous)
          - device present + SMART FAILED → leave warning active (the
            main loop will pick it up and may upgrade to CRITICAL)
        """
        try:
            active = health_persistence.get_active_errors(category='disks')
        except Exception:
            return
        for err in active:
            err_key = err.get('error_key', '') or ''
            # Skip the filesystem-mount errors — the dedicated block
            # below handles them with its own reconciliation rules.
            if not err_key.startswith('disk_') or err_key.startswith('disk_fs_'):
                continue
            # Don't disturb errors the user explicitly acknowledged.
            if err.get('acknowledged') == 1:
                continue
            details = err.get('details', {})
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except Exception:
                    details = {}
            # Recover the block device name. Prefer the structured
            # `block_device` field; fall back to `disk` or derive from
            # the error_key (`disk_nvme2n1` → `nvme2n1`).
            base_disk = (
                details.get('block_device') or
                details.get('disk') or
                err_key[len('disk_'):]
            )
            if not base_disk:
                continue
            dev_path = f'/dev/{base_disk}'
            if not os.path.exists(dev_path):
                try:
                    health_persistence.resolve_error(
                        err_key, 'Device no longer present in system')
                except Exception:
                    pass
                continue
            # Device exists — query SMART. _quick_smart_health returns
            # 'PASSED' / 'FAILED' / 'UNKNOWN'.
            try:
                smart_health = self._quick_smart_health(base_disk)
            except Exception:
                smart_health = 'UNKNOWN'
            if smart_health == 'PASSED':
                try:
                    health_persistence.resolve_error(
                        err_key,
                        'Transient I/O cleared, SMART now reports healthy')
                except Exception:
                    pass
            # else: smart UNKNOWN or FAILED — leave active and let the
            # main loop classify it on the next dmesg window.

    def _check_disks_optimized(self) -> Dict[str, Any]:
        """
        Disk I/O error check -- the SINGLE source of truth for disk errors.

        Reads dmesg for I/O/ATA/SCSI errors, counts per device, records in
        health_persistence, and returns status for the health dashboard.
        Resolves ATA controller names (ata8) to physical disks (sda).

        Cross-references SMART health to avoid false positives from transient
        ATA controller errors. If SMART reports PASSED, dmesg errors are
        downgraded to INFO (transient).
        """
        # Reconcile any disk_<name> warnings persisted across a noisy
        # shutdown / reboot before the main scan starts. Without this
        # pass the main loop only resolves errors for devices that show
        # fresh events in the current dmesg window — devices that simply
        # disappeared from dmesg stay flagged indefinitely.
        self._reconcile_stale_disk_warnings()

        current_time = time.time()
        disk_results = {}  # Single dict for both WARNING and CRITICAL
        
        # Common transient ATA patterns that auto-recover and are not real disk failures.
        # These are bus/controller level events, NOT media errors:
        #   action 0x0 = no action needed (fully recovered)
        #   action 0x6 = hard reset + port reinit (common cable/connector recovery)
        #   SError with BadCRC/Dispar = signal integrity issue (cable, not disk)
        #   Emask 0x10 = ATA bus error (controller/interconnect, not media)
        TRANSIENT_PATTERNS = [
            re.compile(r'exception\s+emask.*action\s+0x[06]', re.IGNORECASE),
            re.compile(r'serror.*=.*0x[0-9a-f]+\s*\(', re.IGNORECASE),
            re.compile(r'SError:.*\{.*(?:BadCRC|Dispar|CommWake).*\}', re.IGNORECASE),
            re.compile(r'emask\s+0x10\s+\(ATA bus error\)', re.IGNORECASE),
            re.compile(r'failed command:\s*READ FPDMA QUEUED', re.IGNORECASE),
        ]
        
        try:
            # Check dmesg for I/O errors in the last 5 minutes
            result = subprocess.run(
                ['dmesg', '-T', '--level=err,warn', '--since', '5 minutes ago'],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            # Collect a sample line per device for richer error messages
            disk_samples = {}
            # Track if ALL errors for a device are transient patterns
            disk_transient_only = {}
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    # Detect various disk error formats
                    is_disk_error = any(kw in line_lower for kw in [
                        'i/o error', 'scsi error', 'medium error',
                        'failed command:', 'exception emask',
                    ])
                    ata_match = re.search(r'(ata\d+)[\.\d]*:.*(?:error|failed|exception)', line_lower)
                    if ata_match:
                        is_disk_error = True
                    
                    if is_disk_error:
                        # Check if this specific line is a known transient pattern
                        is_transient = any(p.search(line) for p in TRANSIENT_PATTERNS)
                        
                        # Extract device from multiple formats
                        raw_device = None
                        for dev_re in [
                            r'dev\s+(sd[a-z]+)',          # dev sdb
                            r'\[(sd[a-z]+)\]',            # [sda]
                            r'/dev/(sd[a-z]+)',            # /dev/sda
                            r'(nvme\d+n\d+)',             # nvme0n1
                            r'device\s+(sd[a-z]+\d*)',    # device sda1
                            r'(ata\d+)',                  # ata8 (ATA controller)
                        ]:
                            dm = re.search(dev_re, line)
                            if dm:
                                raw_device = dm.group(1)
                                break
                        
                        if raw_device:
                            # Resolve ATA port to physical disk name
                            if raw_device.startswith('ata'):
                                resolved = self._resolve_ata_to_disk(raw_device)
                                disk_name = resolved
                            else:
                                disk_name = raw_device.rstrip('0123456789') if raw_device.startswith('sd') else raw_device
                            
                            self.io_error_history[disk_name].append(current_time)
                            if disk_name not in disk_samples:
                                clean = re.sub(r'^\[.*?\]\s*', '', line.strip())
                                disk_samples[disk_name] = clean[:200]
                            
                            # Track transient status: if ANY non-transient error is found, mark False
                            if disk_name not in disk_transient_only:
                                disk_transient_only[disk_name] = is_transient
                            elif not is_transient:
                                disk_transient_only[disk_name] = False
                
                # Clean old history and evaluate per-disk status
                for disk in list(self.io_error_history.keys()):
                    self.io_error_history[disk] = [
                        t for t in self.io_error_history[disk]
                        if current_time - t < 300
                    ]
                    # Remove empty entries to prevent unbounded dict growth
                    if not self.io_error_history[disk]:
                        del self.io_error_history[disk]
                        continue

                    error_count = len(self.io_error_history[disk])
                    error_key = f'disk_{disk}'
                    sample = disk_samples.get(disk, '')
                    display = f'/dev/{disk}' if not disk.startswith('/') else disk
                    all_transient = disk_transient_only.get(disk, False)
                    
                    if error_count >= 1:
                        # Cross-reference with SMART to determine real severity
                        smart_health = self._quick_smart_health(disk)
                        
                        # If SMART is UNKNOWN (unresolved ATA port), check ALL
                        # physical disks.  If every disk passes SMART, the ATA
                        # errors are transient bus/controller noise.
                        if smart_health == 'UNKNOWN':
                            smart_health = self._check_all_disks_smart(smart_health)
                        
                        smart_ok = smart_health == 'PASSED'
                        
                        # Resolve ATA name to block device early so we can use it
                        # in both record_error details AND record_disk_observation.
                        resolved_block = disk
                        resolved_serial = None
                        # Reuse the cached identity from `_get_disk_identity`
                        # instead of calling `smartctl -i` inline twice. The
                        # cache already holds serial+model and is invalidated
                        # on hot-swap (Sprint 10A.9), so the inline subprocess
                        # was a redundant 1 fork-per-disk-with-error per cycle.
                        if disk.startswith('ata'):
                            resolved_block = self._resolve_ata_to_disk(disk)
                            if resolved_block and resolved_block != disk:
                                resolved_serial = self._get_disk_identity(resolved_block).get('serial') or None
                        else:
                            resolved_serial = self._get_disk_identity(disk).get('serial') or None
                        
                        # ── Record disk observation (always, even if transient) ──
                        # Signature must be stable across cycles: strip volatile
                        # data (hex values, counts, timestamps) to dedup properly.
                        # e.g. "ata8.00: exception Emask 0x1 SAct 0xc1000000"
                        # and  "ata8.00: revalidation failed (errno=-2)"
                        # both map to the same per-device I/O observation.
                        try:
                            obs_sig = self._make_io_obs_signature(disk, sample)
                            obs_severity = 'critical' if smart_health == 'FAILED' else 'warning'
                            health_persistence.record_disk_observation(
                                device_name=resolved_block,
                                serial=resolved_serial,
                                error_type='io_error',
                                error_signature=obs_sig,
                                raw_message=f'{display}: {error_count} I/O event(s) in 5 min (SMART: {smart_health})\n{sample}',
                                severity=obs_severity,
                            )
                        except Exception:
                            pass
                        
                        # Transient-only errors (e.g. SError with auto-recovery)
                        # are always INFO regardless of SMART
                        if all_transient:
                            reason = f'{display}: {error_count} transient ATA event(s) in 5 min (auto-recovered)'
                            if sample:
                                reason += f'\n{sample}'
                            health_persistence.resolve_error(error_key, 'Transient ATA events, auto-recovered')
                            disk_results[display] = {
                                'status': 'INFO',
                                'reason': reason,
                                'device': disk,
                                'error_count': error_count,
                                'smart_status': smart_health,
                                'dismissable': False,
                                'error_key': error_key,
                            }
                        elif smart_ok:
                            # SMART is healthy -> dmesg errors are informational only
                            # The disk is fine; these are transient controller/bus events
                            reason = f'{display}: {error_count} I/O event(s) in 5 min (SMART: OK)'
                            if sample:
                                reason += f'\n{sample}'
                            
                            # Resolve any previous error since SMART confirms disk is healthy
                            health_persistence.resolve_error(error_key, 'SMART healthy, I/O events are transient')
                            
                            disk_results[display] = {
                                'status': 'INFO',
                                'reason': reason,
                                'device': disk,
                                'error_count': error_count,
                                'smart_status': smart_health,
                                'dismissable': False,
                                'error_key': error_key,
                            }
                        elif smart_health == 'FAILED':
                            # SMART confirms a real disk failure
                            severity = 'CRITICAL'
                            reason = f'{display}: {error_count} I/O error(s) in 5 min (SMART: FAILED)'
                            if sample:
                                reason += f'\n{sample}'
                            
                            health_persistence.record_error(
                                error_key=error_key,
                                category='disks',
                                severity=severity,
                                reason=reason,
                                details={'disk': disk, 'device': display,
                                         'block_device': resolved_block,
                                         'serial': resolved_serial or '',
                                         'error_count': error_count,
                                         'smart_status': smart_health,
                                         'sample': sample, 'dismissable': False}
                            )
                            disk_results[display] = {
                                'status': severity,
                                'reason': reason,
                                'device': disk,
                                'error_count': error_count,
                                'smart_status': smart_health,
                                'dismissable': False,
                                'error_key': error_key,
                            }
                        else:
                            # SMART is genuinely UNKNOWN (no disk resolved, no
                            # smartctl at all) -- treat as WARNING, not CRITICAL.
                            # These are likely transient and will auto-resolve.
                            severity = 'WARNING'
                            reason = f'{display}: {error_count} I/O event(s) in 5 min (SMART: unavailable)'
                            if sample:
                                reason += f'\n{sample}'
                            
                            # Only record to persistence ONCE.  If the error is
                            # already active, don't call record_error again --
                            # that would keep updating last_seen and preventing
                            # the freshness check from detecting it as stale.
                            if not health_persistence.is_error_active(error_key, category='disks'):
                                health_persistence.record_error(
                                    error_key=error_key,
                                    category='disks',
                                    severity=severity,
                                    reason=reason,
                                    details={'disk': disk, 'device': display,
                                             'block_device': resolved_block,
                                             'serial': resolved_serial or '',
                                             'error_count': error_count,
                                             'smart_status': smart_health,
                                             'sample': sample, 'dismissable': True}
                                )
                            
                            disk_results[display] = {
                                'status': severity,
                                'reason': reason,
                                'device': disk,
                                'error_count': error_count,
                                'smart_status': smart_health,
                                'dismissable': True,
                                'error_key': error_key,
                            }
                    else:
                        health_persistence.resolve_error(error_key, 'Disk errors cleared')
            
            # Also include active filesystem errors (detected by _check_log_analysis
            # and cross-referenced to the 'disks' category)
            try:
                fs_errors = health_persistence.get_active_errors(category='disks')
                for err in fs_errors:
                    err_key = err.get('error_key', '')
                    if not err_key.startswith('disk_fs_'):
                        continue  # Only filesystem cross-references
                    
                    # Skip acknowledged/dismissed errors
                    if err.get('acknowledged') == 1:
                        continue
                    
                    details = err.get('details', {})
                    if isinstance(details, str):
                        try:
                            import json as _json
                            details = _json.loads(details)
                        except Exception:
                            details = {}
                    
                    device = details.get('device', err_key.replace('disk_fs_', '/dev/'))
                    base_disk = details.get('disk', '')
                    
                    # Check if the device still exists.  If not, auto-resolve
                    # the error -- it was likely a disconnected USB/temp device.
                    dev_path = f'/dev/{base_disk}' if base_disk else device
                    
                    # Also extract base disk from partition (e.g., sdb1 -> sdb)
                    if not base_disk and device:
                        # Remove /dev/ prefix and partition number (NVMe-aware)
                        dev_name = device.replace('/dev/', '')
                        base_disk = disk_base_name(dev_name)
                        if base_disk:
                            dev_path = f'/dev/{base_disk}'
                    
                    # Check both the specific device and the base disk
                    device_exists = os.path.exists(dev_path)
                    if not device_exists and device and device != dev_path:
                        device_exists = os.path.exists(device)
                    
                    if not device_exists:
                        health_persistence.resolve_error(
                            err_key, 'Device no longer present in system')
                        continue
                    
                    # Cross-reference with SMART: if SMART is healthy for
                    # this disk, downgrade to INFO (transient fs error).
                    severity = err.get('severity', 'WARNING')
                    if base_disk:
                        smart_health = self._quick_smart_health(base_disk)
                        if smart_health == 'PASSED' and severity == 'CRITICAL':
                            severity = 'WARNING'
                    
                    if device not in disk_results:
                        disk_results[device] = {
                            'status': severity,
                            'reason': err.get('reason', 'Filesystem error'),
                            'device': base_disk,
                            'error_count': 1,
                            'error_type': 'filesystem',
                            'dismissable': True,
                            'error_key': err_key,
                        }
            except Exception:
                pass
            
            if not disk_results:
                return {'status': 'OK'}
            
            # Overall status: only count WARNING+ (skip INFO)
            active_results = {k: v for k, v in disk_results.items() if v.get('status') not in ('OK', 'INFO')}
            if not active_results:
                return {
                    'status': 'OK',
                    'reason': 'Transient ATA events only (SMART healthy)',
                    'details': disk_results
                }
            
            has_critical = any(d.get('status') == 'CRITICAL' for d in active_results.values())
            
            return {
                'status': 'CRITICAL' if has_critical else 'WARNING',
                'reason': f"{len(active_results)} disk(s) with errors",
                'details': disk_results
            }
        
        except Exception as e:
            print(f"[HealthMonitor] Disk/IO check failed: {e}")
            return {'status': 'UNKNOWN', 'reason': f'Disk check unavailable: {str(e)}', 'checks': {}, 'dismissable': True}
    
    def _check_network_optimized(self) -> Dict[str, Any]:
        """
        Optimized network check - only alerts for interfaces that are actually in use.
        Avoids false positives for unused physical interfaces.
        Respects interface exclusions configured by the user.
        """
        try:
            issues = []
            interface_details = {}
            
            net_if_stats = psutil.net_if_stats()
            
            try:
                net_io_per_nic = psutil.net_io_counters(pernic=True)
            except Exception:
                net_io_per_nic = {}
            
            try:
                net_if_addrs = psutil.net_if_addrs()
            except Exception:
                net_if_addrs = {}
            
            # Get excluded interfaces (for health checks)
            excluded_interfaces = health_persistence.get_excluded_interface_names('health')
            
            active_interfaces = set()
            
            for interface, stats in net_if_stats.items():
                if interface == 'lo':
                    continue
                
                # Skip excluded interfaces
                if interface in excluded_interfaces:
                    interface_details[interface] = {
                        'status': 'EXCLUDED',
                        'reason': 'Excluded from monitoring',
                        'is_up': stats.isup,
                        'dismissable': True
                    }
                    continue
                
                # Check if important interface is down
                if not stats.isup:
                    should_alert = False
                    alert_reason = None
                    
                    # Check if it's a bridge interface (always important for VMs/LXCs)
                    if interface.startswith('vmbr'):
                        should_alert = True
                        alert_reason = 'Bridge interface DOWN (VMs/LXCs may be affected)'
                    
                    # Check if physical interface has configuration or traffic
                    elif interface.startswith(('eth', 'ens', 'enp', 'eno')):
                        # Check if interface has IP address (configured)
                        has_ip = False
                        if interface in net_if_addrs:
                            for addr in net_if_addrs[interface]:
                                if addr.family == 2:  # IPv4
                                    has_ip = True
                                    break
                        
                        # Check if interface has traffic (has been used)
                        has_traffic = False
                        if interface in net_io_per_nic:
                            io_stats = net_io_per_nic[interface]
                            # If interface has sent or received any data, it's being used
                            if io_stats.bytes_sent > 0 or io_stats.bytes_recv > 0:
                                has_traffic = True
                        
                        # Only alert if interface is configured or has been used
                        if has_ip:
                            should_alert = True
                            alert_reason = 'Configured interface DOWN (has IP address)'
                        elif has_traffic:
                            should_alert = True
                            alert_reason = 'Active interface DOWN (was handling traffic)'
                    
                    if should_alert:
                        issues.append(f'{interface} is DOWN')
                        
                        error_key = interface
                        health_persistence.record_error(
                            error_key=error_key,
                            category='network',
                            severity='CRITICAL',
                            reason=alert_reason or 'Interface DOWN',
                            details={'interface': interface, 'dismissable': False}
                        )
                        
                        interface_details[interface] = {
                            'status': 'CRITICAL',
                            'reason': alert_reason or 'Interface DOWN',
                            'dismissable': False
                        }
                else:
                    active_interfaces.add(interface)
                    if interface.startswith('vmbr') or interface.startswith(('eth', 'ens', 'enp', 'eno')):
                        health_persistence.resolve_error(interface, 'Interface recovered')
            
            # Check connectivity (latency) - reads from gateway monitor database
            latency_status = self._check_network_latency()
            connectivity_check = {'status': 'OK', 'detail': 'Not tested'}
            if latency_status:
                latency_ms = latency_status.get('latency_ms', 'N/A')
                latency_sev = latency_status.get('status', 'OK')
                interface_details['connectivity'] = latency_status
                detail_text = f'Latency {latency_ms}ms to gateway' if isinstance(latency_ms, (int, float)) else latency_status.get('reason', 'Unknown')
                connectivity_check = {
                    'status': latency_sev if latency_sev not in ['UNKNOWN'] else 'OK',
                    'detail': detail_text,
                }
                if latency_sev not in ['OK', 'INFO', 'UNKNOWN']:
                    issues.append(latency_status.get('reason', 'Network latency issue'))
            
            # Build checks dict
            checks = {}
            for iface in active_interfaces:
                checks[iface] = {'status': 'OK', 'detail': 'UP'}
            for iface, detail in interface_details.items():
                if iface != 'connectivity':
                    checks[iface] = {
                        'status': detail.get('status', 'OK'),
                        'detail': detail.get('reason', 'DOWN'),
                        'dismissable': detail.get('dismissable', False)
                    }
            checks['connectivity'] = connectivity_check
            
            if not issues:
                return {'status': 'OK', 'checks': checks}
            
            has_critical = any(d.get('status') == 'CRITICAL' for d in interface_details.values())
            
            return {
                'status': 'CRITICAL' if has_critical else 'WARNING',
                'reason': '; '.join(issues[:2]),
                'details': interface_details,
                'checks': checks
            }
        
        except Exception as e:
            print(f"[HealthMonitor] Network check failed: {e}")
            return {'status': 'UNKNOWN', 'reason': f'Network check unavailable: {str(e)}', 'checks': {}, 'dismissable': True}
    
    def _check_network_latency(self) -> Optional[Dict[str, Any]]:
        """Check network latency by reading from the gateway latency monitor database.
        
        Reads the most recent gateway latency measurement from the SQLite database
        that is updated every 60 seconds by the latency monitor thread.
        This avoids redundant ping operations and uses the existing monitoring data.
        """
        cache_key = 'network_latency'
        current_time = time.time()
        
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 60:
                return self.cached_results.get(cache_key)
        
        try:
            import sqlite3
            db_path = "/usr/local/share/proxmenux/monitor.db"
            
            # Check if database exists
            if not os.path.exists(db_path):
                return {'status': 'UNKNOWN', 'reason': 'Latency monitor database not available', 'dismissable': True}
            
            conn = sqlite3.connect(db_path, timeout=5)
            cursor = conn.execute(
                """SELECT latency_avg, latency_min, latency_max, packet_loss, timestamp
                   FROM latency_history 
                   WHERE target = 'gateway' 
                   ORDER BY timestamp DESC 
                   LIMIT 1"""
            )
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0] is not None:
                avg_latency = row[0]
                min_latency = row[1]
                max_latency = row[2]
                packet_loss = row[3] or 0
                data_age = current_time - row[4]
                
                # If data is older than 2 minutes, consider it stale
                if data_age > 120:
                    stale_result = {
                        'status': 'UNKNOWN',
                        'reason': 'Latency data is stale (>2 min old)'
                    }
                    self.cached_results[cache_key] = stale_result
                    self.last_check_times[cache_key] = current_time
                    return stale_result
                
                # Check for packet loss first
                if packet_loss >= 100:
                    loss_result = {
                        'status': 'CRITICAL',
                        'reason': 'Packet loss to gateway (100% loss)',
                        'latency_ms': None,
                        'packet_loss': packet_loss
                    }
                    self.cached_results[cache_key] = loss_result
                    self.last_check_times[cache_key] = current_time
                    return loss_result
                
                # Evaluate latency thresholds
                # During startup grace period, downgrade CRITICAL/WARNING to INFO
                # to avoid false alerts from transient boot-time latency spikes
                in_grace_period = _is_startup_health_grace()
                
                if avg_latency > self.NETWORK_LATENCY_CRITICAL:
                    if in_grace_period:
                        status = 'INFO'
                        reason = f'Latency {avg_latency:.1f}ms (startup grace, will stabilize)'
                    else:
                        status = 'CRITICAL'
                        reason = f'Latency {avg_latency:.1f}ms to gateway >{self.NETWORK_LATENCY_CRITICAL}ms'
                elif avg_latency > self.NETWORK_LATENCY_WARNING:
                    if in_grace_period:
                        status = 'INFO'
                        reason = f'Latency {avg_latency:.1f}ms (startup grace, will stabilize)'
                    else:
                        status = 'WARNING'
                        reason = f'Latency {avg_latency:.1f}ms to gateway >{self.NETWORK_LATENCY_WARNING}ms'
                else:
                    status = 'OK'
                    reason = None
                
                latency_result = {
                    'status': status,
                    'latency_ms': round(avg_latency, 1),
                    'latency_min': round(min_latency, 1) if min_latency else None,
                    'latency_max': round(max_latency, 1) if max_latency else None,
                    'packet_loss': packet_loss,
                }
                if reason:
                    latency_result['reason'] = reason
                
                self.cached_results[cache_key] = latency_result
                self.last_check_times[cache_key] = current_time
                return latency_result
            
            # No data in database yet
            no_data_result = {
                'status': 'UNKNOWN',
                'reason': 'No gateway latency data available yet'
            }
            self.cached_results[cache_key] = no_data_result
            self.last_check_times[cache_key] = current_time
            return no_data_result
            
        except Exception as e:
            return {'status': 'UNKNOWN', 'reason': f'Latency check failed: {str(e)}', 'dismissable': True}
    
    def _is_vzdump_active(self) -> bool:
        """Check if a vzdump (backup) job is currently running."""
        try:
            with open('/var/log/pve/tasks/active', 'r') as f:
                for line in f:
                    if ':vzdump:' in line:
                        return True
        except (OSError, IOError):
            pass
        return False
    
    def _resolve_vm_name(self, vmid: str) -> str:
        """Resolve VMID to guest name from PVE config files."""
        if not vmid:
            return ''
        for base in ['/etc/pve/qemu-server', '/etc/pve/lxc']:
            conf = os.path.join(base, f'{vmid}.conf')
            try:
                with open(conf) as f:
                    for line in f:
                        if line.startswith('hostname:') or line.startswith('name:'):
                            return line.split(':', 1)[1].strip()
            except (OSError, IOError):
                continue
        return ''
    
    def _vm_ct_exists(self, vmid: str) -> bool:
        """Check if a VM or CT exists by verifying its config file."""
        import os
        # Check VM config
        vm_conf = f'/etc/pve/qemu-server/{vmid}.conf'
        if os.path.exists(vm_conf):
            return True
        # Check CT config (local node and cluster nodes)
        for base in ['/etc/pve/lxc', '/etc/pve/nodes']:
            if base == '/etc/pve/lxc':
                ct_conf = f'{base}/{vmid}.conf'
                if os.path.exists(ct_conf):
                    return True
            else:
                # Check all cluster nodes
                if os.path.isdir(base):
                    for node in os.listdir(base):
                        ct_conf = f'{base}/{node}/lxc/{vmid}.conf'
                        if os.path.exists(ct_conf):
                            return True
        return False
    
    def _is_vm_running(self, vmid: str) -> bool:
        """Check if a VM or CT is currently running."""
        import subprocess
        try:
            # Check VM status
            result = subprocess.run(
                ['qm', 'status', vmid],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and 'running' in result.stdout.lower():
                return True
            # Check CT status
            result = subprocess.run(
                ['pct', 'status', vmid],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and 'running' in result.stdout.lower():
                return True
        except Exception:
            pass
        return False
    
    def _check_vms_cts_optimized(self) -> Dict[str, Any]:
        """
        Optimized VM/CT check - detects qmp failures and startup errors from logs.
        Improved detection of container and VM errors from journalctl.
        """
        try:
            # First: auto-resolve any persisted VM/CT errors where the guest
            # is now running.  This clears stale "Failed to start" / QMP
            # errors that are no longer relevant.
            try:
                active_vm_errors = health_persistence.get_active_errors('vms')
                for err in active_vm_errors:
                    details = err.get('details') or {}
                    vmid = details.get('id', '')
                    if vmid:
                        health_persistence.check_vm_running(vmid)
            except Exception:
                pass
            
            issues = []
            vm_details = {}
            
            # Use shared journalctl cache to avoid duplicate calls
            journalctl_output = self._get_journalctl_10min_warnings()
            
            # Check if vzdump is running -- QMP timeouts during backup are normal
            _vzdump_running = self._is_vzdump_active()
            
            if journalctl_output:
                for line in journalctl_output.split('\n'):
                    line_lower = line.lower()
                    
                    vm_qmp_match = re.search(r'vm\s+(\d+)\s+qmp\s+command.*(?:failed|unable|timeout)', line_lower)
                    if vm_qmp_match:
                        if _vzdump_running:
                            continue  # Normal during backup
                        vmid = vm_qmp_match.group(1)
                        # Skip if VM no longer exists (stale journal entry)
                        if not self._vm_ct_exists(vmid):
                            continue
                        # Skip if VM is now running - the QMP error is stale/resolved
                        # This prevents re-detecting old journal entries after VM recovery
                        if self._is_vm_running(vmid):
                            # Auto-resolve any existing error for this VM
                            health_persistence.check_vm_running(vmid)
                            continue
                        vm_name = self._resolve_vm_name(vmid)
                        display = f"VM {vmid} ({vm_name})" if vm_name else f"VM {vmid}"
                        key = f'vm_{vmid}'
                        if key not in vm_details:
                            issues.append(f'{display}: QMP communication issue')
                            vm_details[key] = {
                                'status': 'WARNING',
                                'reason': f'{display}: QMP command failed or timed out.\n{line.strip()[:200]}',
                                'id': vmid,
                                'vmname': vm_name,
                                'type': 'VM'
                            }
                        continue
                    
                    ct_error_match = re.search(r'(?:ct|container|lxc)\s+(\d+)', line_lower)
                    if ct_error_match and ('error' in line_lower or 'fail' in line_lower or 'device' in line_lower):
                        ctid = ct_error_match.group(1)
                        # Skip if CT no longer exists (stale journal entry)
                        if not self._vm_ct_exists(ctid):
                            continue
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
                            
                            ct_name = self._resolve_vm_name(ctid)
                            display = f"CT {ctid} ({ct_name})" if ct_name else f"CT {ctid}"
                            full_reason = f'{display}: {reason}\n{line.strip()[:200]}'
                            issues.append(f'{display}: {reason}')
                            vm_details[key] = {
                                'status': 'WARNING' if 'device' in reason.lower() else 'CRITICAL',
                                'reason': full_reason,
                                'id': ctid,
                                'vmname': ct_name,
                                'type': 'CT'
                            }
                        continue
                    
                    vzstart_match = re.search(r'vzstart:(\d+):', line)
                    if vzstart_match and ('error' in line_lower or 'fail' in line_lower or 'does not exist' in line_lower):
                        ctid = vzstart_match.group(1)
                        # Skip if CT no longer exists (stale journal entry)
                        if not self._vm_ct_exists(ctid):
                            continue
                        key = f'ct_{ctid}'
                        if key not in vm_details:
                            # Resolve CT name for better context
                            ct_name = self._resolve_vm_name(ctid)
                            ct_display = f"CT {ctid} ({ct_name})" if ct_name else f"CT {ctid}"
                            
                            # Extract specific error reason
                            if 'device' in line_lower and 'does not exist' in line_lower:
                                device_match = re.search(r'device\s+([/\w\d]+)\s+does not exist', line_lower)
                                if device_match:
                                    error_detail = f'Device {device_match.group(1)} missing'
                                else:
                                    error_detail = 'Device error'
                            else:
                                error_detail = 'Startup error'
                            
                            # Include CT ID in reason for clarity in notifications
                            reason = f'{ct_display}: {error_detail}'
                            issues.append(reason)
                            vm_details[key] = {
                                'status': 'WARNING',
                                'reason': reason,
                                'id': ctid,
                                'vmname': ct_name,
                                'type': 'CT'
                            }
                        continue
                    
                    if any(keyword in line_lower for keyword in ['failed to start', 'cannot start', 'activation failed', 'start error']):
                        id_match = re.search(r'\b(\d{3,4})\b', line)
                        if id_match:
                            vmid = id_match.group(1)
                            # Skip if VM/CT no longer exists (stale journal entry)
                            if not self._vm_ct_exists(vmid):
                                continue
                            key = f'vmct_{vmid}'
                            if key not in vm_details:
                                vm_name = self._resolve_vm_name(vmid)
                                display = f"VM/CT {vmid} ({vm_name})" if vm_name else f"VM/CT {vmid}"
                                full_reason = f'{display}: Failed to start\n{line.strip()[:200]}'
                                issues.append(f'{display}: Failed to start')
                                vm_details[key] = {
                                    'status': 'CRITICAL',
                                    'reason': full_reason,
                                    'id': vmid,
                                    'vmname': vm_name,
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
        
        except Exception as e:
            print(f"[HealthMonitor] VMs/CTs check failed: {e}")
            return {'status': 'UNKNOWN', 'reason': f'VM/CT check unavailable: {str(e)}', 'checks': {}, 'dismissable': True}
    
    # Modified to use persistence
    def _check_vms_cts_with_persistence(self) -> Dict[str, Any]:
        """
        Check VMs/CTs with persistent error tracking.
        Errors persist until VM starts or 48h elapsed.
        """
        try:
            issues = []
            vm_details = {}
            
            # Get active (non-dismissed) errors
            persistent_errors = health_persistence.get_active_errors('vms')
            
            # Also get dismissed errors to show them as INFO
            dismissed_errors = health_persistence.get_dismissed_errors()
            dismissed_vm_errors = [e for e in dismissed_errors if e.get('category') == 'vms']
            
            # Process active errors
            for error in persistent_errors:
                error_key = error['error_key']
                
                if error_key.startswith(('vm_', 'ct_', 'vmct_')):
                    vm_id = error_key.split('_', 1)[1]
                    # Check if VM is running using persistence helper
                    if health_persistence.check_vm_running(vm_id):
                        continue  # Error auto-resolved if VM is now running
                
                # Still active, add to details
                vm_details[error_key] = {
                    'status': error['severity'],
                    'reason': error['reason'],
                    'id': error.get('details', {}).get('id', 'unknown'),
                    'type': error.get('details', {}).get('type', 'VM/CT'),
                    'first_seen': error['first_seen'],
                    'dismissed': False,
                }
                issues.append(f"{error.get('details', {}).get('type', 'VM')} {error.get('details', {}).get('id', '')}: {error['reason']}")
            
            # Process dismissed errors (show as INFO)
            for error in dismissed_vm_errors:
                error_key = error['error_key']
                if error_key not in vm_details:  # Don't overwrite active errors
                    vm_details[error_key] = {
                        'status': 'INFO',
                        'reason': error['reason'],
                        'id': error.get('details', {}).get('id', 'unknown'),
                        'type': error.get('details', {}).get('type', 'VM/CT'),
                        'first_seen': error['first_seen'],
                        'dismissed': True,
                    }
            
            # Check for new errors in logs
            # Using shared journalctl cache to avoid duplicate calls
            journalctl_output = self._get_journalctl_10min_warnings()
            
            _vzdump_running = self._is_vzdump_active()
            
            if journalctl_output:
                for line in journalctl_output.split('\n'):
                    line_lower = line.lower()
                    
                    # VM QMP errors (skip during active backup -- normal behavior)
                    vm_qmp_match = re.search(r'vm\s+(\d+)\s+qmp\s+command.*(?:failed|unable|timeout)', line_lower)
                    if vm_qmp_match:
                        if _vzdump_running:
                            continue  # Normal during backup
                        vmid = vm_qmp_match.group(1)
                        
                        # Skip if VM no longer exists (deleted after error occurred)
                        if not self._vm_ct_exists(vmid):
                            continue
                        
                        # Skip if VM is now running - the QMP error is stale/resolved
                        # This prevents re-detecting old journal entries after VM recovery
                        if self._is_vm_running(vmid):
                            # Auto-resolve any existing error for this VM
                            health_persistence.check_vm_running(vmid)
                            continue
                        
                        vm_name = self._resolve_vm_name(vmid)
                        display = f"VM {vmid} ({vm_name})" if vm_name else f"VM {vmid}"
                        error_key = f'vm_{vmid}'
                        if error_key not in vm_details:
                            rec_result = health_persistence.record_error(
                                error_key=error_key,
                                category='vms',
                                severity='WARNING',
                                reason=f'{display}: QMP command failed or timed out.\n{line.strip()[:200]}',
                                details={'id': vmid, 'vmname': vm_name, 'type': 'VM'}
                            )
                            if not rec_result or rec_result.get('type') != 'skipped_acknowledged':
                                issues.append(f'{display}: QMP communication issue')
                                vm_details[error_key] = {
                                    'status': 'WARNING',
                                    'reason': f'{display}: QMP command failed or timed out',
                                    'id': vmid,
                                    'vmname': vm_name,
                                    'type': 'VM'
                                }
                        continue
                    
                    # Container errors (including startup issues via vzstart)
                    vzstart_match = re.search(r'vzstart:(\d+):', line)
                    if vzstart_match and ('error' in line_lower or 'fail' in line_lower or 'does not exist' in line_lower):
                        ctid = vzstart_match.group(1)
                        
                        # Skip if CT no longer exists (deleted after error occurred)
                        if not self._vm_ct_exists(ctid):
                            continue
                        
                        error_key = f'ct_{ctid}'
                        
                        if error_key not in vm_details:
                            # Resolve CT name for better context
                            ct_name = self._resolve_vm_name(ctid)
                            ct_display = f"CT {ctid} ({ct_name})" if ct_name else f"CT {ctid}"
                            
                            if 'device' in line_lower and 'does not exist' in line_lower:
                                device_match = re.search(r'device\s+([/\w\d]+)\s+does not exist', line_lower)
                                if device_match:
                                    error_detail = f'Device {device_match.group(1)} missing'
                                else:
                                    error_detail = 'Device error'
                            else:
                                error_detail = 'Startup error'
                            
                            # Include CT ID in reason for clarity
                            reason = f'{ct_display}: {error_detail}'
                            
                            # Record persistent error
                            rec_result = health_persistence.record_error(
                                error_key=error_key,
                                category='vms',
                                severity='WARNING',
                                reason=reason,
                                details={'id': ctid, 'vmname': ct_name, 'type': 'CT'}
                            )
                            if not rec_result or rec_result.get('type') != 'skipped_acknowledged':
                                issues.append(reason)
                                vm_details[error_key] = {
                                    'status': 'WARNING',
                                    'reason': reason,
                                    'id': ctid,
                                    'vmname': ct_name,
                                    'type': 'CT'
                                }
                    
                    # Generic failed to start for VMs and CTs
                    if any(keyword in line_lower for keyword in ['failed to start', 'cannot start', 'activation failed', 'start error']):
                        # Try contextual VMID patterns first (more precise), then fallback to generic
                        id_match = (
                            re.search(r'(?:VMID|vmid|VM|CT|qemu|lxc|pct|qm)[:\s=/]+(\d{3,5})\b', line) or
                            re.search(r'\b(\d{3,5})\.conf\b', line) or
                            re.search(r'\b(\d{3,5})\b', line)
                        )
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
                                vm_name = self._resolve_vm_name(vmid_ctid)
                                display = f"{vm_type} {vmid_ctid}"
                                if vm_name:
                                    display = f"{vm_type} {vmid_ctid} ({vm_name})"
                                reason = f'{display}: Failed to start\n{line.strip()[:200]}'
                                # Record persistent error
                                rec_result = health_persistence.record_error(
                                    error_key=error_key,
                                    category='vms',
                                    severity='CRITICAL',
                                    reason=reason,
                                    details={'id': vmid_ctid, 'vmname': vm_name, 'type': vm_type}
                                )
                                if not rec_result or rec_result.get('type') != 'skipped_acknowledged':
                                    issues.append(f'{display}: Failed to start')
                                    vm_details[error_key] = {
                                        'status': 'CRITICAL',
                                        'reason': reason,
                                        'id': vmid_ctid,
                                        'vmname': vm_name,
                                        'type': vm_type
                                    }
            
            # Build checks dict from vm_details
            # 'key' is the persistence error_key (e.g. 'qmp_110', 'ct_101', 'vm_110')
            checks = {}
            for key, val in vm_details.items():
                vm_label = f"{val.get('type', 'VM')} {val.get('id', key)}"
                is_dismissed = val.get('dismissed', False)
                checks[vm_label] = {
                    'status': 'INFO' if is_dismissed else val.get('status', 'WARNING'),
                    'detail': val.get('reason', 'Error'),
                    'dismissable': True,
                    'dismissed': is_dismissed,
                    'error_key': key  # Must match the persistence DB key
                }
            
            if not issues:
                # No active (non-dismissed) issues
                if not checks:
                    checks['qmp_communication'] = {'status': 'OK', 'detail': 'No QMP timeouts detected'}
                    checks['container_startup'] = {'status': 'OK', 'detail': 'No container startup errors'}
                    checks['vm_startup'] = {'status': 'OK', 'detail': 'No VM startup failures'}
                    checks['oom_killer'] = {'status': 'OK', 'detail': 'No OOM events detected'}
                return {'status': 'OK', 'checks': checks}
            
            # Only consider non-dismissed items for overall severity
            active_details = {k: v for k, v in vm_details.items() if not v.get('dismissed')}
            has_critical = any(d.get('status') == 'CRITICAL' for d in active_details.values())
            
            return {
                'status': 'CRITICAL' if has_critical else 'WARNING',
                'reason': '; '.join(issues[:3]),
                'details': vm_details,
                'checks': checks
            }
            
        except Exception as e:
            print(f"[HealthMonitor] VMs/CTs persistence check failed: {e}")
            return {'status': 'UNKNOWN', 'reason': f'VM/CT check unavailable: {str(e)}', 'checks': {}, 'dismissable': True}
    
    def _check_pve_services(self) -> Dict[str, Any]:
        """
        Check critical Proxmox services with persistence tracking.
        - Checks the base PVE_SERVICES list
        - Dynamically adds corosync if a cluster config exists
        - Records failed services in persistence for tracking/dismiss
        - Auto-clears when services recover
        """
        try:
            # Build service list: base PVE services + corosync if clustered
            services_to_check = list(self.PVE_SERVICES)
            is_cluster = os.path.exists('/etc/corosync/corosync.conf')
            if is_cluster and 'corosync' not in services_to_check:
                services_to_check.append('corosync')
            
            failed_services = []
            service_details = {}

            for service in services_to_check:
                try:
                    result = subprocess.run(
                        ['systemctl', 'is-active', service],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )

                    status = result.stdout.strip()
                    if result.returncode != 0 or status != 'active':
                        failed_services.append(service)
                        service_details[service] = status or 'inactive'
                except Exception:
                    failed_services.append(service)
                    service_details[service] = 'error'

            # Auto-clear errors for services that are healthy this cycle.
            # Lifted out of the `if failed_services:` branch so it runs
            # unconditionally — otherwise a service that recovered while
            # ALL other failed services are user-dismissed kept its error
            # active forever (the dismissed-only path returned before the
            # cleanup loop). Audit Tier 5 — Health stack.
            for svc in services_to_check:
                if svc not in failed_services:
                    error_key = f'pve_service_{svc}'
                    if health_persistence.is_error_active(error_key):
                        health_persistence.clear_error(error_key)
            
            # Build checks dict with status per service
            checks = {}
            for svc in services_to_check:
                error_key = f'pve_service_{svc}'
                if svc in failed_services:
                    state = service_details.get(svc, 'inactive')
                    checks[svc] = {
                        'status': 'CRITICAL',
                        'detail': f'Service is {state}',
                        'error_key': error_key,
                        'dismissable': True,
                    }
                else:
                    checks[svc] = {
                        'status': 'OK',
                        'detail': 'Active',
                        'error_key': error_key,
                    }
            
            if is_cluster:
                checks['cluster_mode'] = {
                    'status': 'OK',
                    'detail': 'Cluster detected (corosync.conf present)',
                }
            
            if failed_services:
                reason = f'Services inactive: {", ".join(failed_services)}'
                
                # Record each failed service in persistence, respecting dismiss
                active_failed = []
                for svc in failed_services:
                    error_key = f'pve_service_{svc}'
                    rec_result = health_persistence.record_error(
                        error_key=error_key,
                        category='pve_services',
                        severity='CRITICAL',
                        reason=f'PVE service {svc} is {service_details.get(svc, "inactive")}',
                        details={'service': svc, 'state': service_details.get(svc, 'inactive')}
                    )
                    if rec_result and rec_result.get('type') == 'skipped_acknowledged':
                        # Mark as dismissed in checks for frontend
                        if svc in checks:
                            checks[svc]['dismissed'] = True
                    else:
                        active_failed.append(svc)

                # (recovered-services cleanup happens earlier, before this
                # branch — see the unconditional loop above.)

                # If all failed services are dismissed, return OK
                if not active_failed:
                    return {
                        'status': 'OK',
                        'reason': None,
                        'failed': [],
                        'is_cluster': is_cluster,
                        'services_checked': len(services_to_check),
                        'checks': checks
                    }
                
                return {
                    'status': 'CRITICAL',
                    'reason': f'Services inactive: {", ".join(active_failed)}',
                    'failed': active_failed,
                    'is_cluster': is_cluster,
                    'services_checked': len(services_to_check),
                    'checks': checks
                }
            
            # All OK — recovered-services cleanup already ran above.
            return {
                'status': 'OK',
                'is_cluster': is_cluster,
                'services_checked': len(services_to_check),
                'checks': checks
            }
            
        except Exception as e:
            return {
                'status': 'WARNING',
                'reason': f'Service check command failed: {str(e)}'
            }
    
    def _is_benign_error(self, line: str) -> bool:
        """Check if log line matches benign error patterns (uses pre-compiled regex)"""
        benign_re, _, _ = self._get_compiled_patterns()
        return bool(benign_re.search(line.lower()))
    
    def _enrich_critical_log_reason(self, line: str) -> str:
        """
        Transform a raw kernel/system log line into a human-readable reason
        for notifications and the health dashboard.
        """
        line_lower = line.lower()
        
        # EXT4/BTRFS/XFS/ZFS filesystem errors
        if 'ext4-fs error' in line_lower or 'btrfs error' in line_lower or 'xfs' in line_lower and 'error' in line_lower:
            fs_type = 'EXT4' if 'ext4' in line_lower else ('BTRFS' if 'btrfs' in line_lower else 'XFS')
            dev_match = re.search(r'device\s+(\S+?)\)?:', line)
            device = dev_match.group(1).rstrip(')') if dev_match else 'unknown'
            func_match = re.search(r':\s+(\w+):\d+:', line)
            func_name = func_match.group(1) if func_match else ''
            inode_match = re.search(r'inode\s+#?(\d+)', line)
            inode = inode_match.group(1) if inode_match else ''
            
            # Translate function name
            func_translations = {
                'ext4_find_entry': 'directory lookup failed (possible directory corruption)',
                'ext4_lookup': 'file lookup failed (possible metadata corruption)',
                'ext4_journal_start': 'journal transaction failed (journal corruption)',
                'ext4_readdir': 'directory read failed (directory data corrupted)',
                'ext4_get_inode_loc': 'inode location failed (inode table corruption)',
                '__ext4_get_inode_loc': 'inode location failed (inode table corruption)',
                'ext4_xattr_get': 'extended attributes read failed',
                'ext4_iget': 'inode read failed (possible inode corruption)',
                'ext4_mb_generate_buddy': 'block allocator error',
                'ext4_validate_block_bitmap': 'block bitmap corrupted',
                'ext4_validate_inode_bitmap': 'inode bitmap corrupted',
                'htree_dirblock_to_tree': 'directory index tree corrupted',
            }
            
            # Identify the device
            device_info = self._identify_block_device(device)
            
            reason = f'{fs_type} filesystem error on /dev/{device}'
            if device_info:
                reason += f'\nDevice: {device_info}'
            else:
                reason += f'\nDevice: /dev/{device} (not currently detected -- may be a disconnected USB or temporary device)'
            if func_name:
                desc = func_translations.get(func_name, func_name)
                reason += f'\nError: {desc}'
            if inode:
                inode_hint = 'root directory' if inode == '2' else f'inode #{inode}'
                reason += f'\nAffected: {inode_hint}'
            # Note: Action/recommendations are provided by AI when AI Suggestions is enabled
            return reason
        
        # Out of memory
        if 'out of memory' in line_lower or 'oom_kill' in line_lower:
            m = re.search(r'Killed process\s+\d+\s+\(([^)]+)\)', line)
            process = m.group(1) if m else 'unknown'
            return f'Out of memory - system killed process "{process}" to free RAM'
        
        # Kernel panic
        if 'kernel panic' in line_lower:
            return 'Kernel panic - system halted. Reboot required.'
        
        # Segfault
        if 'segfault' in line_lower:
            m = re.search(r'(\S+)\[\d+\].*segfault', line)
            process = m.group(1) if m else 'unknown'
            is_critical_proc = any(p in process.lower() for p in self.PVE_CRITICAL_PROCESSES)
            if is_critical_proc:
                return f'Critical process "{process}" crashed (segmentation fault) -- PVE service affected'
            return f'Process "{process}" crashed (segmentation fault)'
        
        # Hardware error
        if 'hardware error' in line_lower or 'mce:' in line_lower:
            return f'Hardware error detected (MCE) - check CPU/RAM health'
        
        # RAID failure
        if 'raid' in line_lower and 'fail' in line_lower:
            md_match = re.search(r'(md\d+)', line)
            md_dev = md_match.group(1) if md_match else 'unknown'
            return f'RAID array {md_dev} degraded or failed - check disk status'
        
        # Fallback: clean up the raw line
        clean = re.sub(r'^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+', '', line)
        clean = re.sub(r'\[\d+\]:\s*', '', clean)
        return clean[:150]
    
    def _classify_log_severity(self, line: str) -> Optional[str]:
        """
        Classify log line severity intelligently.
        Returns: 'CRITICAL', 'WARNING', or None (benign/info)
        
        Design principles:
        - CRITICAL must be reserved for events that require IMMEDIATE action
          (data loss risk, service outage, hardware failure confirmed by SMART).
        - WARNING is for events worth investigating but not urgent.
        - Everything else is None (benign/informational).
        """
        line_lower = line.lower()
        
        # Check if benign first -- fast path for known noise
        if self._is_benign_error(line):
            return None
        
        # Check critical keywords (hard failures: OOM, panic, FS corruption, etc.)
        for keyword in self.CRITICAL_LOG_KEYWORDS:
            if re.search(keyword, line_lower):
                return 'CRITICAL'
        
        # Check warning keywords (includes segfault, I/O errors, etc.)
        for keyword in self.WARNING_LOG_KEYWORDS:
            if re.search(keyword, line_lower):
                # Special case: segfault of a PVE-critical process is CRITICAL
                if 'segfault' in line_lower:
                    for proc in self.PVE_CRITICAL_PROCESSES:
                        if proc in line_lower:
                            return 'CRITICAL'
                return 'WARNING'
        
        # Generic classification -- very conservative to avoid false positives.
        # Only escalate if the line explicitly uses severity-level keywords
        # from the kernel or systemd (not just any line containing "error").
        if 'kernel panic' in line_lower or ('fatal' in line_lower and 'non-fatal' not in line_lower):
            return 'CRITICAL'
        
        # Lines from priority "err" that don't match any keyword above are
        # likely informational noise (e.g. "error response from daemon").
        # Return None to avoid flooding the dashboard with non-actionable items.
        return None

    def _check_logs_with_persistence(self) -> Dict[str, Any]:
        """
        Intelligent log checking with cascade detection and persistence.
        Focuses on detecting significant error patterns rather than transient warnings.
        
        New thresholds:
        - CASCADE: ≥15 errors (increased from 10)
        - SPIKE: ≥5 errors AND 4x increase (more restrictive)
        - PERSISTENT: Same error in 3 consecutive checks
        """
        cache_key = 'logs_analysis'
        current_time = time.time()
        
        # Cache the result for 5 minutes to avoid excessive journalctl calls
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < self.LOG_CHECK_INTERVAL:
                # Return the full cached result (which includes 'checks' dict)
                cached = self.cached_results.get(cache_key)
                if cached:
                    return cached
                return {'status': 'OK', 'checks': {
                    'log_error_cascade': {'status': 'OK', 'detail': 'No cascading errors'},
                    'log_error_spike': {'status': 'OK', 'detail': 'No error spikes'},
                    'log_persistent_errors': {'status': 'OK', 'detail': 'No persistent patterns'},
                    'log_critical_errors': {'status': 'OK', 'detail': 'No critical errors'}
                }}
        
        try:
            # Fetch logs from the last 5 minutes — matches LOG_CHECK_INTERVAL so
            # adjacent cycles are contiguous (no blind gap). -b 0 limits to the
            # current boot to avoid pre-reboot OOM/crash errors from persisting.
            result_recent = subprocess.run(
                ['journalctl', '-b', '0', '--since', '5 minutes ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=20
            )

            # Previous 5-min window (5-10 min ago) for spike/cascade comparison.
            result_previous = subprocess.run(
                ['journalctl', '-b', '0', '--since', '10 minutes ago', '--until', '5 minutes ago', '--no-pager', '-p', 'warning'],
                capture_output=True,
                text=True,
                timeout=20
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
                        pattern_hash = hashlib.md5(pattern.encode()).hexdigest()[:8]
                        error_key = f'log_critical_{pattern_hash}'
                        
                        # ── SMART cross-reference for disk/FS errors ──
                        # Filesystem and disk errors are only truly CRITICAL if
                        # the underlying disk is actually failing.  We check:
                        #  1. Device exists? No -> WARNING (disconnected USB, etc.)
                        #  2. SMART PASSED? -> WARNING (transient error, not disk failure)
                        #  3. SMART FAILED? -> CRITICAL (confirmed hardware problem)
                        #  4. SMART UNKNOWN? -> WARNING (can't confirm, err on side of caution)
                        fs_dev_match = re.search(
                            r'(?:ext4-fs|btrfs|xfs|zfs)\s+error.*?device\s+(\S+?)\)?[:\s]',
                            line, re.IGNORECASE
                        )
                        smart_status_for_log = None
                        if fs_dev_match:
                            fs_dev = fs_dev_match.group(1).rstrip(')')
                            base_dev = disk_base_name(fs_dev)
                            if not os.path.exists(f'/dev/{base_dev}'):
                                # Device not present -- almost certainly a disconnected drive
                                severity = 'WARNING'
                                smart_status_for_log = 'DEVICE_ABSENT'
                            elif self.capabilities.get('has_smart'):
                                smart_health = self._quick_smart_health(base_dev)
                                smart_status_for_log = smart_health
                                if smart_health == 'PASSED':
                                    # SMART says disk is healthy -- transient FS error
                                    severity = 'WARNING'
                                elif smart_health == 'UNKNOWN':
                                    # Can't verify -- be conservative, don't alarm
                                    severity = 'WARNING'
                                # smart_health == 'FAILED' -> keep CRITICAL
                        
                        if pattern not in critical_errors_found:
                            # Only count as "critical" if severity wasn't downgraded
                            if severity == 'CRITICAL':
                                critical_errors_found[pattern] = line
                            # Build a human-readable reason from the raw log line
                            enriched_reason = self._enrich_critical_log_reason(line)
                            
                            # Append SMART context to the reason if we checked it
                            if smart_status_for_log == 'PASSED':
                                enriched_reason += '\nSMART: Passed (disk is healthy -- error is likely transient)'
                            elif smart_status_for_log == 'FAILED':
                                enriched_reason += '\nSMART: FAILED -- disk is failing, replace immediately'
                            elif smart_status_for_log == 'DEVICE_ABSENT':
                                enriched_reason += '\nDevice not currently detected -- may be a disconnected USB or temporary device'
                            
                            # Record persistent error if it's not already active
                            if not health_persistence.is_error_active(error_key, category='logs'):
                                health_persistence.record_error(
                                    error_key=error_key,
                                    category='logs',
                                    severity=severity,
                                    reason=enriched_reason,
                                    details={'pattern': pattern, 'raw_line': line[:200],
                                             'smart_status': smart_status_for_log,
                                             'dismissable': True}
                                )
                            
                            # Cross-reference: filesystem errors also belong in the disks category
                            # so they appear in the Storage/Disks dashboard section
                            fs_match = re.search(r'(?:ext4-fs|btrfs|xfs|zfs)\s+error.*?(?:device\s+(\S+?)\)?[:\s])', line, re.IGNORECASE)
                            if fs_match:
                                fs_device = fs_match.group(1).rstrip(')') if fs_match.group(1) else 'unknown'
                                # Centralised NVMe-aware partition strip.
                                base_device = disk_base_name(fs_device)
                                disk_error_key = f'disk_fs_{fs_device}'
                                
                                # Use the SMART-aware severity we already determined above
                                device_exists = os.path.exists(f'/dev/{base_device}')
                                if not device_exists:
                                    # Device no longer exists (USB disconnected, removed disk)
                                    # Skip creating error - it's a stale journal entry
                                    continue
                                elif smart_status_for_log == 'PASSED':
                                    fs_severity = 'WARNING'  # SMART healthy -> transient
                                elif smart_status_for_log == 'FAILED':
                                    fs_severity = 'CRITICAL'  # SMART failing -> real problem
                                else:
                                    fs_severity = 'WARNING'  # Can't confirm -> conservative
                                
                                if not health_persistence.is_error_active(disk_error_key, category='disks'):
                                    health_persistence.record_error(
                                        error_key=disk_error_key,
                                        category='disks',
                                        severity=fs_severity,
                                        reason=enriched_reason,
                                        details={
                                            'disk': base_device,
                                            'device': f'/dev/{fs_device}',
                                            'block_device': base_device,
                                            'error_type': 'filesystem',
                                            'error_count': 1,
                                            'sample': line[:200],
                                            'smart_status': smart_status_for_log,
                                            'dismissable': True,
                                            'device_exists': True,  # Always true here (non-existent devices skip above)
                                        }
                                    )
                                
                                # Record filesystem error as permanent disk observation
                                try:
                                    obs_serial = None
                                    try:
                                        sm = subprocess.run(
                                            ['smartctl', '-i', f'/dev/{base_device}'],
                                            capture_output=True, text=True, timeout=3)
                                        if sm.returncode in (0, 4):
                                            for sline in sm.stdout.split('\n'):
                                                if 'Serial Number' in sline or 'Serial number' in sline:
                                                    obs_serial = sline.split(':')[-1].strip()
                                                    break
                                    except Exception:
                                        pass
                                    health_persistence.record_disk_observation(
                                        device_name=base_device,
                                        serial=obs_serial,
                                        error_type='filesystem_error',
                                        error_signature=f'fs_error_{fs_device}_{pattern_hash}',
                                        raw_message=enriched_reason[:500],
                                        severity=fs_severity.lower(),
                                    )
                                except Exception:
                                    pass
                    
                    recent_patterns[pattern] += 1
                    
                    if pattern in self.persistent_log_patterns:
                        self.persistent_log_patterns[pattern]['count'] += 1
                        self.persistent_log_patterns[pattern]['last_seen'] = current_time
                    else:
                        self.persistent_log_patterns[pattern] = {
                            'count': 1,
                            'first_seen': current_time,
                            'last_seen': current_time,
                            'sample': line.strip()[:200],  # Original line for display
                        }
                
                for line in previous_lines:
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
                    previous_patterns[pattern] += 1
                
                cascading_errors = {
                    pattern: count for pattern, count in recent_patterns.items()
                    if count >= 15 and self._classify_log_severity(pattern) in ['WARNING', 'CRITICAL']
                }
                
                spike_errors = {}
                for pattern, recent_count in recent_patterns.items():
                    prev_count = previous_patterns.get(pattern, 0)
                    if recent_count >= 5 and recent_count >= prev_count * 4:
                        spike_errors[pattern] = recent_count
                
                # Helper: get human-readable samples from normalized patterns
                def _get_samples(error_dict, max_items=3):
                    """Return list of readable sample lines for error patterns."""
                    samples = []
                    for pattern in list(error_dict.keys())[:max_items]:
                        pdata = self.persistent_log_patterns.get(pattern, {})
                        sample = pdata.get('sample', pattern)
                        # Trim timestamp prefix if present (e.g. "Feb 27 16:03:35 host ")
                        clean = re.sub(r'^[A-Z][a-z]{2}\s+\d+\s+[\d:]+\s+\S+\s+', '', sample)
                        samples.append(clean[:120])
                    return samples
                
                persistent_errors = {}
                for pattern, data in self.persistent_log_patterns.items():
                    time_span = current_time - data['first_seen']
                    if data['count'] >= 3 and time_span >= 900:  # 15 minutes
                        persistent_errors[pattern] = data['count']
                        
                        # Record as warning if not already recorded
                        pattern_hash = hashlib.md5(pattern.encode()).hexdigest()[:8]
                        error_key = f'log_persistent_{pattern_hash}'
                        if not health_persistence.is_error_active(error_key, category='logs'):
                            # Use the original sample line for the notification,
                            # not the normalized pattern (which has IDs replaced).
                            sample = data.get('sample', pattern)
                            # Strip journal timestamp prefix so the stored reason
                            # doesn't contain dated information that confuses
                            # re-notifications.
                            clean_sample = re.sub(
                                r'^[A-Z][a-z]{2}\s+\d+\s+[\d:]+\s+\S+\s+', '', sample
                            )
                            health_persistence.record_error(
                                error_key=error_key,
                                category='logs',
                                severity='WARNING',
                                reason=f'Recurring error ({data["count"]}x): {clean_sample[:150]}',
                                details={'pattern': pattern, 'sample': sample,
                                         'dismissable': True, 'occurrences': data['count']}
                            )
                
                patterns_to_remove = [
                    p for p, data in self.persistent_log_patterns.items()
                    if current_time - data['last_seen'] > 1800
                ]
                for pattern in patterns_to_remove:
                    del self.persistent_log_patterns[pattern]
                
                # B5 fix: Cap size to prevent unbounded memory growth under high error load
                MAX_LOG_PATTERNS = 500
                if len(self.persistent_log_patterns) > MAX_LOG_PATTERNS:
                    sorted_patterns = sorted(
                        self.persistent_log_patterns.items(),
                        key=lambda x: x[1]['last_seen'],
                        reverse=True
                    )
                    self.persistent_log_patterns = defaultdict(
                        lambda: {'count': 0, 'first_seen': 0, 'last_seen': 0},
                        dict(sorted_patterns[:MAX_LOG_PATTERNS])
                    )
                
                unique_critical_count = len(critical_errors_found)
                cascade_count = len(cascading_errors)
                spike_count = len(spike_errors)
                persistent_count = len(persistent_errors)
                
                if unique_critical_count > 0:
                    status = 'CRITICAL'
                    # Use enriched reason from the first critical error for the summary
                    representative_line = next(iter(critical_errors_found.values()))
                    enriched = self._enrich_critical_log_reason(representative_line)
                    if unique_critical_count == 1:
                        reason = enriched
                    else:
                        reason = f'{unique_critical_count} critical error(s):\n{enriched}'
                elif cascade_count > 0:
                    status = 'WARNING'
                    samples = _get_samples(cascading_errors, 3)
                    reason = f'Error cascade ({cascade_count} patterns repeating):\n' + '\n'.join(f'  - {s}' for s in samples)
                elif spike_count > 0:
                    status = 'WARNING'
                    samples = _get_samples(spike_errors, 3)
                    reason = f'Error spike ({spike_count} patterns with 4x increase):\n' + '\n'.join(f'  - {s}' for s in samples)
                elif persistent_count > 0:
                    status = 'WARNING'
                    samples = _get_samples(persistent_errors, 3)
                    reason = f'Persistent errors ({persistent_count} patterns over 15+ min):\n' + '\n'.join(f'  - {s}' for s in samples)
                else:
                    # No significant issues found
                    status = 'OK'
                    reason = None
                
                # Record/clear persistent errors for each log sub-check so Dismiss works
                cascade_samples = _get_samples(cascading_errors, 2) if cascade_count else []
                spike_samples = _get_samples(spike_errors, 2) if spike_count else []
                persist_samples = _get_samples(persistent_errors, 2) if persistent_count else []
                
                log_sub_checks = {
                    'log_error_cascade': {'active': cascade_count > 0, 'severity': 'WARNING',
                        'reason': f'{cascade_count} pattern(s) repeating >=15 times:\n' + '\n'.join(f'  - {s}' for s in cascade_samples) if cascade_count else ''},
                    'log_error_spike': {'active': spike_count > 0, 'severity': 'WARNING',
                        'reason': f'{spike_count} pattern(s) with 4x increase:\n' + '\n'.join(f'  - {s}' for s in spike_samples) if spike_count else ''},
                    'log_persistent_errors': {'active': persistent_count > 0, 'severity': 'WARNING',
                        'reason': f'{persistent_count} recurring pattern(s) over 15+ min:\n' + '\n'.join(f'  - {s}' for s in persist_samples) if persistent_count else ''},
                    'log_critical_errors': {'active': unique_critical_count > 0, 'severity': 'CRITICAL',
                        'reason': f'{unique_critical_count} critical error(s) found', 'dismissable': False},
                }
                
                # Track which sub-checks were dismissed
                dismissed_keys = set()
                for err_key, info in log_sub_checks.items():
                    if info['active']:
                        is_dismissable = info.get('dismissable', True)
                        result = health_persistence.record_error(
                            error_key=err_key,
                            category='logs',
                            severity=info['severity'],
                            reason=info['reason'],
                            details={'dismissable': is_dismissable}
                        )
                        if result and result.get('type') == 'skipped_acknowledged':
                            dismissed_keys.add(err_key)
                    elif health_persistence.is_error_active(err_key):
                        health_persistence.clear_error(err_key)
                
                # Build checks dict - downgrade dismissed items to INFO
                def _log_check_status(key, active, severity):
                    if not active:
                        return 'OK'
                    if key in dismissed_keys:
                        return 'INFO'
                    return severity
                
                # Build detail strings that include the actual error samples
                # so the user can see exactly WHAT is triggering the warning.
                if cascade_count > 0:
                    cascade_detail = f'{cascade_count} pattern(s) repeating >=15 times: ' + '; '.join(cascade_samples)
                else:
                    cascade_detail = 'No cascading errors'
                
                if spike_count > 0:
                    spike_detail = f'{spike_count} pattern(s) with 4x increase: ' + '; '.join(spike_samples)
                else:
                    spike_detail = 'No error spikes'
                
                if persistent_count > 0:
                    persist_detail = f'{persistent_count} recurring pattern(s) over 15+ min: ' + '; '.join(persist_samples)
                else:
                    persist_detail = 'No persistent patterns'
                
                log_checks = {
                    'log_error_cascade': {
                        'status': _log_check_status('log_error_cascade', cascade_count > 0, 'WARNING'),
                        'detail': cascade_detail,
                        'dismissable': True,
                        'dismissed': 'log_error_cascade' in dismissed_keys,
                        'error_key': 'log_error_cascade'
                    },
                    'log_error_spike': {
                        'status': _log_check_status('log_error_spike', spike_count > 0, 'WARNING'),
                        'detail': spike_detail,
                        'dismissable': True,
                        'dismissed': 'log_error_spike' in dismissed_keys,
                        'error_key': 'log_error_spike'
                    },
                    'log_persistent_errors': {
                        'status': _log_check_status('log_persistent_errors', persistent_count > 0, 'WARNING'),
                        'detail': persist_detail,
                        'dismissable': True,
                        'dismissed': 'log_persistent_errors' in dismissed_keys,
                        'error_key': 'log_persistent_errors'
                    },
                    'log_critical_errors': {
                        'status': _log_check_status('log_critical_errors', unique_critical_count > 0, 'CRITICAL'),
                        'detail': reason if unique_critical_count > 0 else 'No critical errors',
                        'dismissable': False,
                        'error_key': 'log_critical_errors'
                    }
                }
                
                # Recalculate overall status considering dismissed items
                active_issues = {k: v for k, v in log_checks.items() if v['status'] in ('WARNING', 'CRITICAL')}
                if not active_issues:
                    status = 'OK'
                    reason = None
                else:
                    # Recalculate status and reason from only non-dismissed sub-checks
                    has_critical = any(v['status'] == 'CRITICAL' for v in active_issues.values())
                    status = 'CRITICAL' if has_critical else 'WARNING'
                    # Rebuild reason from active (non-dismissed) checks only
                    active_reasons = []
                    for k, v in active_issues.items():
                        detail = v.get('detail', '')
                        if detail:
                            active_reasons.append(detail)
                    reason = '; '.join(active_reasons[:3]) if active_reasons else None
                
                log_result = {'status': status, 'checks': log_checks}
                if reason:
                    log_result['reason'] = reason
                
                self.cached_results[cache_key] = log_result
                self.last_check_times[cache_key] = current_time
                return log_result
            
            # If journalctl command failed or returned no data
            ok_result = {'status': 'OK', 'checks': {
                'log_error_cascade': {'status': 'OK', 'detail': 'No cascading errors'},
                'log_error_spike': {'status': 'OK', 'detail': 'No error spikes'},
                'log_persistent_errors': {'status': 'OK', 'detail': 'No persistent patterns'},
                'log_critical_errors': {'status': 'OK', 'detail': 'No critical errors'}
            }}
            self.cached_results[cache_key] = ok_result
            self.last_check_times[cache_key] = current_time
            return ok_result
            
        except Exception as e:
            print(f"[HealthMonitor] Log check failed: {e}")
            return {'status': 'UNKNOWN', 'reason': f'Log check unavailable: {str(e)}', 'checks': {}, 'dismissable': True}
    
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
        # Up to 9 digits — modern Linux PIDs go up to 4 194 304 (7 digits)
        # under default kernel.pid_max, and namespaced PIDs in cgroups can
        # be even wider. The previous `\d{3,6}` left those un-normalised so
        # the same recurring error appeared as N distinct patterns.
        pattern = re.sub(r'\b\d{3,9}\b', 'ID', pattern)
        pattern = re.sub(r'/dev/\S+', '/dev/XXX', pattern)  # Normalize device paths
        pattern = re.sub(r'/\S+/\S+', '/PATH/', pattern)  # Normalize general paths
        pattern = re.sub(r'0x[0-9a-f]+', '0xXXX', pattern)  # Normalize hex values
        pattern = re.sub(r'\b(uuid|guid|hash)[:=]\s*[\w-]+\b', r'\1=XXX', pattern.lower()) # Normalize UUIDs/GUIDs
        pattern = re.sub(r'\s+', ' ', pattern).strip()  # Normalize whitespace
        
        return pattern[:150]  # Keep first 150 characters to avoid overly long patterns
    
    # Regex to parse Inst lines: Inst <pkg> [<cur>] (<new> <repo> [<arch>])
    _RE_INST = re.compile(r'^Inst\s+(\S+)\s+\[([^\]]+)\]\s+\((\S+)\s+')
    _RE_INST_NEW = re.compile(r'^Inst\s+(\S+)\s+\((\S+)\s+')
    
    _PVE_PREFIXES = (
        'pve-', 'proxmox-', 'qemu-server', 'lxc-pve', 'ceph',
        'corosync', 'libpve', 'pbs-', 'pmg-',
    )
    # Kernel-package prefixes for categorisation. Order matters: the matcher
    # in update parsing checks KERNEL first and PVE second, so `proxmox-kernel`
    # must appear here before the generic `proxmox-` falls through to
    # _PVE_PREFIXES. Bug #208 — PVE 9.x ships kernels as `proxmox-kernel-*`
    # (Debian 13 base), not `pve-kernel-*` as in older Proxmox; without the
    # `proxmox-kernel` prefix every kernel update was mis-categorised as a
    # generic PVE update and the dashboard reported "Kernel/PVE up to date"
    # even with a kernel patch waiting for the running CT.
    _KERNEL_PREFIXES = (
        'linux-image',
        'pve-kernel',
        'proxmox-kernel',
        'pve-firmware',
        'proxmox-firmware',
    )
    _IMPORTANT_PKGS = {
        'pve-manager', 'proxmox-ve', 'qemu-server', 'pve-container',
        'pve-ha-manager', 'pve-firewall', 'ceph-common',
        'proxmox-backup-client',
    }
    
    def _check_updates(self) -> Optional[Dict[str, Any]]:
        """
        Check for pending system updates.
        - INFO: Any updates available (including security updates).
        - WARNING: Security updates pending 360+ days unpatched, or system not updated >1 year (365 days).
        - CRITICAL: System not updated >18 months (548 days).
        
        Updates are always informational unless they represent a prolonged
        unpatched state.  Detects PVE version upgrades from pve-manager
        Inst lines and exposes them as an INFO sub-check.
        """
        cache_key = 'updates_check'
        current_time = time.time()
        apt_history_path = '/var/log/apt/history.log'

        # Detect a manual `apt install/upgrade` since the last check by
        # comparing /var/log/apt/history.log's mtime against the cache
        # timestamp. apt appends to this file on every transaction, so a
        # newer mtime means the local package state changed and the cached
        # pending-updates list is stale. Reported by Alberto (14/5): the
        # dashboard tile kept showing pending updates ~hours after he ran
        # `apt upgrade` manually. Cheap stat call; runs at most once per
        # /api/health/full request.
        history_mtime = None
        try:
            if os.path.exists(apt_history_path):
                history_mtime = os.path.getmtime(apt_history_path)
        except Exception:
            history_mtime = None

        if cache_key in self.last_check_times:
            cache_ts = self.last_check_times[cache_key]
            history_changed = (history_mtime is not None and history_mtime > cache_ts)
            if not history_changed and current_time - cache_ts < 600:
                return self.cached_results.get(cache_key)

        try:
            last_update_days = None
            sec_result = None
            age_result = None

            if history_mtime is not None:
                try:
                    days_since_update = (current_time - history_mtime) / 86400
                    last_update_days = int(days_since_update)
                except Exception:
                    pass
            
            # Perform a dry run of apt-get dist-upgrade to see pending
            # packages. `dist-upgrade` (a.k.a. `full-upgrade`) is what the
            # Proxmox VE web UI's Updates tab runs internally, and unlike
            # plain `apt-get upgrade` it surfaces kernel updates packaged
            # as NEW installs (e.g. `proxmox-kernel-6.14.11-9-pve-signed`
            # showing up as `Inst` when the running CT is on -4). Bug #208
            # — without dist-upgrade these updates never appeared in the
            # `Inst` list at all, so the Kernel/PVE sub-check stayed
            # green even when the running kernel had a patch waiting.
            try:
                result = subprocess.run(
                    ['apt-get', 'dist-upgrade', '--dry-run'],
                    capture_output=True, text=True, timeout=30
                )
            except subprocess.TimeoutExpired:
                print("[HealthMonitor] apt-get upgrade --dry-run timed out")
                return {
                    'status': 'UNKNOWN',
                    'reason': 'apt-get timed out - repository may be unreachable',
                    'count': 0, 'checks': {}
                }
            
            status = 'OK'
            reason = None
            update_count = 0
            security_pkgs: list = []
            kernel_pkgs: list = []
            pve_pkgs: list = []
            running_kernel_pkgs: list = []  # {name, cur, new} — kernel(s) matching `uname -r`
            important_pkgs: list = []   # {name, cur, new}
            pve_manager_info = None     # {cur, new} or None
            sec_result = None
            sec_severity = 'INFO'
            sec_days_unpatched = 0

            # Read the running kernel release (e.g. `7.0.2-5-pve`) so we can
            # distinguish a kernel update that REPLACES the kernel the host
            # is currently booted from (urgent, requires reboot) from one
            # that only touches an older kernel still present in the
            # bootloader or the meta-package pointers. Bug #208.
            #
            # `running_kernel_branch` extracts the major.minor branch from
            # the running release — e.g. `7.0.2-5-pve` → `7.0`. We use it
            # to detect updates to the branch META package
            # (`proxmox-kernel-7.0` / `pve-kernel-7.0`), which when
            # upgraded pull in the latest kernel of that branch and so
            # also replace the running kernel on the next boot.
            running_kernel = ''
            running_kernel_branch = ''
            try:
                running_kernel = os.uname().release
                rk_low = running_kernel.lower()
                m = re.match(r'^(\d+\.\d+)', rk_low)
                if m:
                    running_kernel_branch = m.group(1)
            except Exception:
                pass

            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line.startswith('Inst '):
                        continue
                    update_count += 1

                    # Parse package name, current and new versions
                    m = self._RE_INST.match(line)
                    if m:
                        pkg_name, cur_ver, new_ver = m.group(1), m.group(2), m.group(3)
                    else:
                        m2 = self._RE_INST_NEW.match(line)
                        if m2:
                            pkg_name, cur_ver, new_ver = m2.group(1), '', m2.group(2)
                        else:
                            parts = line.split()
                            pkg_name = parts[1] if len(parts) > 1 else 'unknown'
                            cur_ver, new_ver = '', ''

                    # Strip arch suffix (e.g. package:amd64)
                    pkg_name = pkg_name.split(':')[0]
                    name_lower = pkg_name.lower()
                    line_lower = line.lower()

                    # Categorise
                    if 'security' in line_lower or 'debian-security' in line_lower:
                        security_pkgs.append(pkg_name)

                    if any(name_lower.startswith(p) for p in self._KERNEL_PREFIXES):
                        kernel_pkgs.append(pkg_name)
                        # Does this package match the currently running
                        # kernel? Proxmox kernels are named
                        # `proxmox-kernel-<release>` and `pve-kernel-<release>`,
                        # plus their `-signed` variant. Compare against
                        # `uname -r` to flag updates the operator should
                        # reboot for. Bug #208.
                        if running_kernel:
                            stripped = name_lower
                            if stripped.endswith('-signed'):
                                stripped = stripped[:-len('-signed')]
                            for k_prefix in ('proxmox-kernel-', 'pve-kernel-', 'linux-image-'):
                                if stripped.startswith(k_prefix):
                                    suffix = stripped[len(k_prefix):]
                                    # Two cases both count as "this update
                                    # will replace the running kernel":
                                    #   a) exact match — the in-place
                                    #      package of the running release
                                    #      (e.g. `proxmox-kernel-7.0.2-5-pve`
                                    #      upgrading from 7.0.2-5 to -6).
                                    #   b) branch meta — the meta package
                                    #      pointing at the latest of the
                                    #      running branch (e.g. running
                                    #      `6.14.11-4-pve`, upgradable
                                    #      `proxmox-kernel-6.14` pulls a
                                    #      newer 6.14.x on next boot).
                                    is_exact = (suffix == running_kernel.lower())
                                    is_branch_meta = (
                                        running_kernel_branch
                                        and suffix == running_kernel_branch
                                    )
                                    if is_exact or is_branch_meta:
                                        running_kernel_pkgs.append({
                                            'name': pkg_name,
                                            'cur': cur_ver,
                                            'new': new_ver,
                                            'match': 'exact' if is_exact else 'branch',
                                        })
                                    break
                    elif any(name_lower.startswith(p) for p in self._PVE_PREFIXES):
                        pve_pkgs.append(pkg_name)
                    
                    # Collect important packages with version info
                    if pkg_name in self._IMPORTANT_PKGS and cur_ver:
                        important_pkgs.append({
                            'name': pkg_name, 'cur': cur_ver, 'new': new_ver
                        })
                    
                    # Detect pve-manager upgrade -> PVE version upgrade
                    if pkg_name == 'pve-manager' and cur_ver and new_ver:
                        pve_manager_info = {'cur': cur_ver, 'new': new_ver}
                
                # ── Determine overall status ──────────────────────
                if security_pkgs:
                    sec_days_unpatched = 0
                    try:
                        existing = health_persistence.get_error_by_key('security_updates')
                        if existing and existing.get('first_seen'):
                            from datetime import datetime
                            first_dt = datetime.fromisoformat(existing['first_seen'])
                            sec_days_unpatched = (datetime.now() - first_dt).days
                    except Exception:
                        pass
                    
                    if sec_days_unpatched >= self.SECURITY_WARN_DAYS:
                        status = 'WARNING'
                        reason = f'{len(security_pkgs)} security update(s) pending for {sec_days_unpatched} days'
                        sec_severity = 'WARNING'
                    else:
                        status = 'INFO'
                        reason = f'{len(security_pkgs)} security update(s) pending'
                        sec_severity = 'INFO'
                    
                    sec_result = health_persistence.record_error(
                        error_key='security_updates',
                        category='updates',
                        severity=sec_severity,
                        reason=reason,
                        details={'count': len(security_pkgs), 'packages': security_pkgs[:5],
                                 'dismissable': sec_severity == 'WARNING',
                                 'days_unpatched': sec_days_unpatched}
                    )
                    if sec_result and sec_result.get('type') == 'skipped_acknowledged':
                        status = 'INFO'
                        reason = None
                
                elif last_update_days and last_update_days >= 548:
                    status = 'CRITICAL'
                    reason = f'System not updated in {last_update_days} days (>18 months)'
                    health_persistence.record_error(
                        error_key='system_age', category='updates',
                        severity='CRITICAL', reason=reason,
                        details={'days': last_update_days, 'update_count': update_count, 'dismissable': False}
                    )
                elif last_update_days and last_update_days >= 365:
                    status = 'WARNING'
                    reason = f'System not updated in {last_update_days} days (>1 year)'
                    age_result = health_persistence.record_error(
                        error_key='system_age', category='updates',
                        severity='WARNING', reason=reason,
                        details={'days': last_update_days, 'update_count': update_count, 'dismissable': True}
                    )
                    if age_result and age_result.get('type') == 'skipped_acknowledged':
                        status = 'INFO'
                        reason = None
                elif running_kernel_pkgs:
                    # Running kernel has an update available. Bug #208.
                    # Reported as INFO — the Updates section never
                    # escalates to WARNING for pending updates; WARNING /
                    # CRITICAL on this section are reserved for time-based
                    # gates (system_age >= 365d / 548d, security_updates
                    # unpatched >= SECURITY_WARN_DAYS).
                    status = 'INFO'
                    reason = f'Kernel update available for running {running_kernel}'
                elif kernel_pkgs or pve_pkgs:
                    status = 'INFO'
                    reason = f'{len(kernel_pkgs)} kernel + {len(pve_pkgs)} Proxmox update(s) available'
                elif update_count > 0:
                    status = 'INFO'
                    reason = f'{update_count} package update(s) pending'
            
            elif result.returncode != 0:
                status = 'WARNING'
                reason = 'Failed to check for updates (apt-get error)'

            # ── Build checks dict ─────────────────────────────────
            age_dismissed = bool(age_result and age_result.get('type') == 'skipped_acknowledged')
            update_age_status = 'CRITICAL' if (last_update_days and last_update_days >= 548) else (
                'INFO' if age_dismissed else ('WARNING' if (last_update_days and last_update_days >= 365) else 'OK'))
            
            sec_dismissed = security_pkgs and sec_result and sec_result.get('type') == 'skipped_acknowledged'
            if sec_dismissed:
                sec_status = 'INFO'
            elif security_pkgs:
                sec_status = sec_severity
            else:
                sec_status = 'OK'
            
            sec_detail = f'{len(security_pkgs)} security update(s) pending'
            if security_pkgs and sec_days_unpatched >= self.SECURITY_WARN_DAYS:
                sec_detail += f' ({sec_days_unpatched} days unpatched)'
            
            # Kernel/PVE sub-check. Bug #208: distinguish three cases.
            # All non-OK results stay at INFO — the Updates section never
            # raises WARNING for pending updates; WARNING / CRITICAL on
            # this section is reserved for time-based gates (system_age,
            # security_updates unpatched too long).
            #
            #   1) Update for the running kernel → INFO with explicit
            #      "Running kernel update available, reboot required to
            #      apply" wording. Bug #208 — without this, the row read
            #      "Kernel/PVE up to date" even when the running kernel
            #      had a patch pending.
            #   2) Kernel updates exist but only for non-running kernels
            #      (older kernels still present in the bootloader, meta-
            #      packages like `proxmox-kernel-7.0` pointing to the
            #      latest 7.0.x, signed variants of already-installed
            #      kernels) → INFO with explicit wording.
            #   3) No kernel updates → OK.
            if running_kernel_pkgs:
                rk_count = len(running_kernel_pkgs)
                # Keep the row text tight — on mobile the System Updates
                # modal renders this string in a single line and longer
                # wording wrapped awkwardly. Just `<pkg> <cur> -> <new>`
                # is enough to convey "your running kernel has an update";
                # the row's INFO icon already signals that no action is
                # forced.
                first = running_kernel_pkgs[0]
                if first.get('cur') and first.get('new'):
                    rk_detail = f"{first['name']} {first['cur']} -> {first['new']}"
                else:
                    rk_detail = first['name']
                if rk_count > 1:
                    rk_detail += f" (+{rk_count - 1} more)"
                kernel_status = 'INFO'
                kernel_detail = rk_detail
            elif kernel_pkgs:
                kernel_status = 'INFO'
                kernel_detail = (
                    f"{len(kernel_pkgs)} kernel update(s) available "
                    f"(none for running kernel"
                    + (f" {running_kernel}" if running_kernel else "")
                    + ")"
                )
            else:
                kernel_status = 'OK'
                kernel_detail = 'Kernel/PVE up to date'

            checks = {
                'kernel_pve': {
                    'status': kernel_status,
                    'detail': kernel_detail,
                    'error_key': 'kernel_pve',
                },
                'pending_updates': {
                    'status': 'INFO' if update_count > 0 else 'OK',
                    'detail': f'{update_count} package(s) pending',
                    'error_key': 'pending_updates'
                },
                'security_updates': {
                    'status': sec_status,
                    'detail': sec_detail if security_pkgs else 'No security updates pending',
                    'dismissable': sec_status == 'WARNING' and not sec_dismissed,
                    'dismissed': bool(sec_dismissed),
                    'error_key': 'security_updates'
                },
                'system_age': {
                    'status': update_age_status,
                    'detail': f'Last updated {last_update_days} day(s) ago' if last_update_days is not None else 'Unknown',
                    'dismissable': update_age_status == 'WARNING' and not age_dismissed,
                    'dismissed': bool(age_dismissed),
                    'error_key': 'system_age'
                },
            }
            
            # PVE version sub-check (always INFO)
            if pve_manager_info:
                checks['pve_version'] = {
                    'status': 'INFO',
                    'detail': f"PVE {pve_manager_info['cur']} -> {pve_manager_info['new']} available",
                    'error_key': 'pve_version'
                }
            else:
                checks['pve_version'] = {
                    'status': 'OK',
                    'detail': 'Proxmox VE is up to date',
                    'error_key': 'pve_version'
                }
            
            # Construct result dictionary
            update_result = {
                'status': status,
                'count': update_count,
                'checks': checks,
            }
            if reason:
                update_result['reason'] = reason
            if last_update_days is not None:
                update_result['days_since_update'] = last_update_days
            # Attach categorised counts for the frontend
            update_result['security_count'] = len(security_pkgs)
            update_result['pve_count'] = len(pve_pkgs)
            update_result['kernel_count'] = len(kernel_pkgs)
            update_result['running_kernel'] = running_kernel
            update_result['running_kernel_update_count'] = len(running_kernel_pkgs)
            update_result['running_kernel_packages'] = running_kernel_pkgs[:5]
            update_result['important_packages'] = important_pkgs[:8]
            
            self.cached_results[cache_key] = update_result
            self.last_check_times[cache_key] = current_time
            return update_result
            
        except Exception as e:
            print(f"[HealthMonitor] Updates check failed: {e}")
            return {'status': 'UNKNOWN', 'reason': f'Updates check unavailable: {str(e)}', 'count': 0, 'checks': {}, 'dismissable': True}
    
    def _check_fail2ban_bans(self) -> Dict[str, Any]:
        """
        Check if fail2ban is installed and if there are currently banned IPs.
        Cached for 60 seconds to avoid hammering fail2ban-client.
        
        Returns:
          {'installed': bool, 'active': bool, 'status': str, 'detail': str,
           'banned_count': int, 'jails': [...], 'banned_ips': [...]}
        """
        cache_key = 'fail2ban_bans'
        current_time = time.time()
        
        if cache_key in self.last_check_times:
            if current_time - self.last_check_times[cache_key] < 60:
                return self.cached_results.get(cache_key, {'installed': False, 'status': 'OK', 'detail': 'Not installed'})
        
        result = {'installed': False, 'active': False, 'status': 'OK', 'detail': 'Not installed', 'banned_count': 0, 'jails': [], 'banned_ips': []}
        
        try:
            # Check if fail2ban-client exists
            which_result = subprocess.run(
                ['which', 'fail2ban-client'],
                capture_output=True, text=True, timeout=2
            )
            if which_result.returncode != 0:
                self.cached_results[cache_key] = result
                self.last_check_times[cache_key] = current_time
                return result
            
            result['installed'] = True
            
            # Check if fail2ban service is active
            active_check = subprocess.run(
                ['systemctl', 'is-active', 'fail2ban'],
                capture_output=True, text=True, timeout=2
            )
            if active_check.stdout.strip() != 'active':
                result['detail'] = 'Fail2Ban installed but service not active'
                self.cached_results[cache_key] = result
                self.last_check_times[cache_key] = current_time
                return result
            
            result['active'] = True
            
            # Get list of active jails
            jails_result = subprocess.run(
                ['fail2ban-client', 'status'],
                capture_output=True, text=True, timeout=3
            )
            
            jails = []
            if jails_result.returncode == 0:
                for line in jails_result.stdout.split('\n'):
                    if 'Jail list:' in line:
                        jail_str = line.split('Jail list:')[1].strip()
                        jails = [j.strip() for j in jail_str.split(',') if j.strip()]
                        break
            
            if not jails:
                result['detail'] = 'Fail2Ban active, no jails configured'
                self.cached_results[cache_key] = result
                self.last_check_times[cache_key] = current_time
                return result
            
            result['jails'] = jails
            
            # Check each jail for banned IPs
            total_banned = 0
            all_banned_ips = []
            jails_with_bans = []
            
            for jail in jails:
                try:
                    jail_result = subprocess.run(
                        ['fail2ban-client', 'status', jail],
                        capture_output=True, text=True, timeout=2
                    )
                    if jail_result.returncode == 0:
                        for line in jail_result.stdout.split('\n'):
                            if 'Currently banned:' in line:
                                try:
                                    count = int(line.split('Currently banned:')[1].strip())
                                    if count > 0:
                                        total_banned += count
                                        jails_with_bans.append(jail)
                                except (ValueError, IndexError):
                                    pass
                            elif 'Banned IP list:' in line:
                                ips_str = line.split('Banned IP list:')[1].strip()
                                if ips_str:
                                    ips = [ip.strip() for ip in ips_str.split() if ip.strip()]
                                    all_banned_ips.extend(ips[:10])  # Limit to 10 IPs per jail
                except Exception:
                    pass
            
            result['banned_count'] = total_banned
            result['banned_ips'] = all_banned_ips[:20]  # Max 20 total
            
            if total_banned > 0:
                jails_str = ', '.join(jails_with_bans)
                msg = f'{total_banned} IP(s) currently banned by Fail2Ban (jails: {jails_str})'
                result['status'] = 'WARNING'
                result['detail'] = msg
                # Persistence handled by _check_security caller via security_fail2ban key
            else:
                result['detail'] = f'Fail2Ban active ({len(jails)} jail(s), no current bans)'
                # Auto-resolve if previously banned IPs are now gone
                if health_persistence.is_error_active('fail2ban'):
                    health_persistence.clear_error('fail2ban')
            
        except Exception as e:
            result['detail'] = f'Unable to check Fail2Ban: {str(e)[:50]}'
        
        self.cached_results[cache_key] = result
        self.last_check_times[cache_key] = current_time
        return result
    
    def _check_security(self) -> Dict[str, Any]:
        """
        Check security-related items with detailed sub-item breakdown:
        - Uptime check: >1 year without kernel update indicates vulnerability
        - SSL certificates: PVE certificate expiration
        - Login attempts: Excessive failed logins (brute force detection)
        - Fail2Ban: Currently banned IPs (if fail2ban is installed)
        
        Returns a result with 'checks' dict containing per-item status.
        """
        try:
            issues = []
            checks = {
            'uptime': {'status': 'OK', 'detail': ''},
            'certificates': {'status': 'OK', 'detail': ''},
            'login_attempts': {'status': 'OK', 'detail': ''},
            }
            
            # Sub-check 1: Uptime for potential kernel vulnerabilities
            try:
                uptime_seconds = time.time() - psutil.boot_time()
                uptime_days = uptime_seconds / 86400
                
                if uptime_days > 365:
                    updates_data = self.cached_results.get('updates_check')
                    if updates_data and updates_data.get('days_since_update', 9999) > 365:
                        msg = f'Uptime {int(uptime_days)} days (>1 year, consider updating kernel/system)'
                        issues.append(msg)
                        checks['uptime'] = {'status': 'WARNING', 'detail': msg, 'days': int(uptime_days), 'dismissable': True}
                    else:
                        checks['uptime'] = {'status': 'OK', 'detail': f'Uptime {int(uptime_days)} days, system recently updated'}
                else:
                    checks['uptime'] = {'status': 'OK', 'detail': f'Uptime {int(uptime_days)} days'}
            except Exception:
                checks['uptime'] = {'status': 'OK', 'detail': 'Unable to determine uptime'}
            
            # Sub-check 2: SSL certificates
            cert_status = self._check_certificates()
            if cert_status:
                cert_sev = cert_status.get('status', 'OK')
                cert_reason = cert_status.get('reason', '')
                checks['certificates'] = {
                    'status': cert_sev,
                    'detail': cert_reason if cert_reason else 'Certificate valid',
                    'dismissable': True if cert_sev not in ['OK', 'INFO'] else False
                }
                if cert_sev not in ['OK', 'INFO']:
                    issues.append(cert_reason or 'Certificate issue')
            
            # Sub-check 3: Failed login attempts (brute force detection)
            # Cached for 1 hour to avoid reading 24h of logs every 5 minutes
            try:
                current_time = time.time()
                
                # Check if we have a valid cached result
                if self._journalctl_24h_cache['time'] > 0 and \
                   current_time - self._journalctl_24h_cache['time'] < self._JOURNALCTL_24H_CACHE_TTL:
                    failed_logins = self._journalctl_24h_cache['count']
                else:
                    # Cache expired or first run - read full 24h logs
                    result = subprocess.run(
                        ['journalctl', '--since', '24 hours ago', '--no-pager',
                         '-g', 'authentication failure|failed password|invalid user',
                         '--output=cat', '-n', '5000'],
                        capture_output=True,
                        text=True,
                        timeout=20
                    )
                    
                    failed_logins = 0
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            line_lower = line.lower()
                            if 'authentication failure' in line_lower or 'failed password' in line_lower or 'invalid user' in line_lower:
                                failed_logins += 1
                    
                    # Cache the result
                    self._journalctl_24h_cache = {'count': failed_logins, 'time': current_time}
                
                if failed_logins > 50:
                    msg = f'{failed_logins} failed login attempts in 24h'
                    issues.append(msg)
                    checks['login_attempts'] = {'status': 'WARNING', 'detail': msg, 'count': failed_logins, 'dismissable': True}
                elif failed_logins > 0:
                    checks['login_attempts'] = {'status': 'OK', 'detail': f'{failed_logins} failed attempts in 24h (within threshold)', 'count': failed_logins}
                else:
                    checks['login_attempts'] = {'status': 'OK', 'detail': 'No failed login attempts in 24h', 'count': 0}
            except Exception:
                checks['login_attempts'] = {'status': 'OK', 'detail': 'Unable to check login attempts'}
            
            # Sub-check 4: Fail2Ban ban detection (only show if installed)
            try:
                f2b = self._check_fail2ban_bans()
                if f2b.get('installed', False):
                    f2b_status = f2b.get('status', 'OK')
                    checks['fail2ban'] = {
                        'status': f2b_status,
                        'dismissable': True if f2b_status not in ['OK'] else False,
                        'detail': f2b.get('detail', ''),
                        'installed': True,
                        'banned_count': f2b.get('banned_count', 0)
                    }
                    if f2b.get('status') == 'WARNING':
                        issues.append(f2b.get('detail', 'Fail2Ban bans detected'))
                # If not installed, simply don't add it to checks
            except Exception:
                pass
            
            # Persist errors and respect dismiss for each sub-check
            dismissed_keys = set()
            security_sub_checks = {
                'security_login_attempts': 'login_attempts',
                'security_certificates': 'certificates',
                'security_uptime': 'uptime',
                'security_fail2ban': 'fail2ban',
            }
            
            # Inject error_key into each check so the frontend knows which DB key to use
            for err_key, check_name in security_sub_checks.items():
                if check_name in checks:
                    checks[check_name]['error_key'] = err_key
            
            for err_key, check_name in security_sub_checks.items():
                check_info = checks.get(check_name, {})
                check_status = check_info.get('status', 'OK')
                if check_status not in ('OK', 'INFO'):
                    is_dismissable = check_info.get('dismissable', True)
                    rec_result = health_persistence.record_error(
                        error_key=err_key,
                        category='security',
                        severity=check_status,
                        reason=check_info.get('detail', ''),
                        details={'dismissable': is_dismissable}
                    )
                    if rec_result and rec_result.get('type') == 'skipped_acknowledged':
                        dismissed_keys.add(err_key)
                elif health_persistence.is_error_active(err_key):
                    health_persistence.clear_error(err_key)
            
            # Rebuild issues excluding dismissed sub-checks
            key_to_check = {
                'security_login_attempts': 'login_attempts',
                'security_certificates': 'certificates',
                'security_uptime': 'uptime',
                'security_fail2ban': 'fail2ban',
            }
            active_issues = []
            for err_key, check_name in key_to_check.items():
                if err_key in dismissed_keys:
                    # Mark as dismissed in checks for the frontend
                    if check_name in checks:
                        checks[check_name]['dismissed'] = True
                    continue
                check_info = checks.get(check_name, {})
                if check_info.get('status', 'OK') not in ('OK', 'INFO'):
                    active_issues.append(check_info.get('detail', ''))
            
            # Determine overall security status from non-dismissed issues only
            if active_issues:
                has_critical = any(
                    c.get('status') == 'CRITICAL'
                    for k, c in checks.items()
                    if f'security_{k}' not in dismissed_keys
                )
                overall_status = 'CRITICAL' if has_critical else 'WARNING'
                return {
                    'status': overall_status,
                    'reason': '; '.join(active_issues[:2]),
                    'checks': checks
                }
            
            return {
                'status': 'OK',
                'checks': checks
            }
            
        except Exception as e:
            print(f"[HealthMonitor] Security check failed: {e}")
            return {'status': 'UNKNOWN', 'reason': f'Security check unavailable: {str(e)}', 'checks': {}, 'dismissable': True}
    
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
        Looks for SMART warnings, smartd messages, and specific disk errors.
        
        Returns dict keyed by '/dev/sdX' with detailed issue info including
        the actual log lines that triggered the warning, so notifications
        and the health monitor show actionable information.
        """
        disk_issues: Dict[str, Any] = {}
        
        try:
            # Use cached journalctl output to avoid repeated subprocess calls
            journalctl_output = self._get_journalctl_1hour_warnings()
            
            if not journalctl_output:
                return disk_issues
            
            # Collect all relevant lines per disk
            # disk_lines[disk_name] = {'smart_lines': [], 'io_lines': [], 'severity': 'WARNING'}
            disk_lines: Dict[str, Dict] = {}
            
            for line in journalctl_output.split('\n'):
                if not line.strip():
                    continue
                line_lower = line.lower()
                
                # Extract disk name -- multiple patterns for different log formats:
                #   /dev/sdh, /dev/nvme0n1
                #   Device: /dev/sdh [SAT]  (smartd format)
                #   smartd[1234]: Device: /dev/sdh ...
                disk_match = re.search(
                    r'(?:/dev/|Device:?\s*/dev/)(sd[a-z]+|nvme\d+n\d+|hd[a-z]+)',
                    line)
                if not disk_match:
                    # Fallback for smartd messages that reference disk names differently
                    if 'smartd' in line_lower or 'smart' in line_lower:
                        disk_match = re.search(r'\b(sd[a-z]+|nvme\d+n\d+)\b', line)
                if not disk_match:
                    continue
                disk_name = disk_match.group(1)
                
                if disk_name not in disk_lines:
                    disk_lines[disk_name] = {
                        'smart_lines': [], 'io_lines': [],
                        'severity': 'WARNING'
                    }
                
                # Classify the log line
                # SMART warnings: smartd messages, SMART attribute warnings, etc.
                if ('smart' in line_lower and
                    any(kw in line_lower for kw in
                        ['warning', 'error', 'fail', 'exceeded', 'threshold',
                         'reallocat', 'pending', 'uncorrect', 'crc', 'offline',
                         'temperature', 'current_pending', 'reported_uncorrect'])):
                    # Extract the meaningful part of the log line (after hostname)
                    msg_part = line.split(': ', 2)[-1] if ': ' in line else line
                    disk_lines[disk_name]['smart_lines'].append(msg_part.strip())
                
                # smartd daemon messages (e.g. "smartd[1234]: Device: /dev/sdh ...")
                elif 'smartd' in line_lower:
                    msg_part = line.split(': ', 2)[-1] if ': ' in line else line
                    disk_lines[disk_name]['smart_lines'].append(msg_part.strip())
                
                # Disk I/O / medium errors
                elif any(kw in line_lower for kw in
                         ['disk error', 'ata error', 'medium error', 'io error',
                          'i/o error', 'blk_update_request', 'sense key']):
                    msg_part = line.split(': ', 2)[-1] if ': ' in line else line
                    disk_lines[disk_name]['io_lines'].append(msg_part.strip())
                    disk_lines[disk_name]['severity'] = 'CRITICAL'
            
            # Build issues with detailed reasons
            for disk_name, info in disk_lines.items():
                dev_path = f'/dev/{disk_name}'
                smart_lines = info['smart_lines']
                io_lines = info['io_lines']
                severity = info['severity']
                
                if not smart_lines and not io_lines:
                    continue
                
                # Skip if disk no longer exists (stale journal entries)
                if not os.path.exists(dev_path):
                    # Also check base device for partitions — NVMe-aware.
                    base_disk = disk_base_name(disk_name)
                    base_path = f'/dev/{base_disk}'
                    if not os.path.exists(base_path):
                        continue  # Disk was removed, skip this error
                
                # Build a descriptive reason from the actual log entries
                # Deduplicate similar messages (keep unique ones)
                seen_msgs = set()
                unique_smart = []
                for msg in smart_lines:
                    # Normalize for dedup: strip timestamps and volatile parts
                    norm = re.sub(r'\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}', '', msg).strip()
                    if norm not in seen_msgs:
                        seen_msgs.add(norm)
                        unique_smart.append(msg)
                
                unique_io = []
                for msg in io_lines:
                    norm = re.sub(r'\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}', '', msg).strip()
                    if norm not in seen_msgs:
                        seen_msgs.add(norm)
                        unique_io.append(msg)
                
                # Compose the reason with actual details
                parts = []
                if unique_smart:
                    if len(unique_smart) == 1:
                        parts.append(unique_smart[0])
                    else:
                        parts.append(f'{len(unique_smart)} SMART warnings')
                        # Include the first 3 most relevant entries
                        for entry in unique_smart[:3]:
                            parts.append(f'  - {entry}')
                
                if unique_io:
                    if len(unique_io) == 1:
                        parts.append(unique_io[0])
                    else:
                        parts.append(f'{len(unique_io)} I/O errors')
                        for entry in unique_io[:3]:
                            parts.append(f'  - {entry}')
                
                reason = '\n'.join(parts) if parts else 'SMART/disk warning in system logs'
                
                # Keep first sample line for observation recording
                sample_line = (unique_smart[0] if unique_smart else
                               unique_io[0] if unique_io else '')
                
                disk_issues[dev_path] = {
                    'status': severity,
                    'reason': reason,
                    'device': disk_name,
                    'smart_lines': unique_smart[:5],
                    'io_lines': unique_io[:5],
                    'sample': sample_line,
                    'source': 'journal',
                    'dismissable': True,
                    'error_key': f'smart_{disk_name}',
                }
                
                # Record as disk observation for the permanent history
                try:
                    obs_type = 'smart_error' if unique_smart else 'io_error'
                    # Build a stable signature from the error family, not the volatile details
                    if unique_smart:
                        sig_base = 'smart_journal'
                        # Classify SMART warnings by type
                        all_text = ' '.join(unique_smart).lower()
                        if any(kw in all_text for kw in ['reallocat', 'pending', 'uncorrect']):
                            sig_base = 'smart_sector_issues'
                        elif 'temperature' in all_text:
                            sig_base = 'smart_temperature'
                        elif 'crc' in all_text or 'udma' in all_text:
                            sig_base = 'smart_crc_errors'
                        elif 'fail' in all_text:
                            sig_base = 'smart_test_failed'
                    else:
                        sig_base = 'journal_io_error'
                    
                    obs_sig = f'{sig_base}_{disk_name}'
                    
                    # Get serial for proper cross-referencing (cached)
                    obs_id = self._get_disk_identity(disk_name)
                    obs_serial = obs_id['serial'] or None
                    
                    health_persistence.record_disk_observation(
                        device_name=disk_name,
                        serial=obs_serial,
                        error_type=obs_type,
                        error_signature=obs_sig,
                        raw_message=f'/dev/{disk_name}: {reason}',
                        severity=severity.lower(),
                    )
                except Exception:
                    pass
        
        except Exception as e:
            print(f"[HealthMonitor] Error checking disk health from events: {e}")
        
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
            
            # Get list of all pools and their health status.
            result = subprocess.run(
                ['zpool', 'list', '-H', '-o', 'name,health'], # -H for no header
                capture_output=True,
                text=True,
                timeout=5
            )

            # Fallback: when a pool is SUSPENDED `zpool list` can return non-zero
            # (the suspended pool is unreadable through `list`). Falling back to
            # `zpool status -x` reports faulted/suspended pools regardless. Audit
            # Tier 5 (Health stack — `_check_zfs_pool_health` no detecta SUSPENDED).
            if result.returncode != 0:
                try:
                    status = subprocess.run(
                        ['zpool', 'status', '-x'],
                        capture_output=True, text=True, timeout=5,
                    )
                    text = (status.stdout or '') + '\n' + (status.stderr or '')
                    # `zpool status -x` outputs "all pools are healthy" when fine.
                    if status.returncode == 0 and 'all pools are healthy' in text.lower():
                        return zfs_issues
                    # Otherwise scan for "pool: <name>" + "state: <STATE>" pairs.
                    import re as _re
                    for m in _re.finditer(r'pool:\s*(\S+).*?state:\s*(\S+)', text, _re.DOTALL):
                        pool_name = m.group(1)
                        pool_health = m.group(2).upper()
                        if pool_health == 'ONLINE':
                            continue
                        zfs_issues[f'zpool_{pool_name}'] = {
                            'status': 'CRITICAL',
                            'reason': f'ZFS pool {pool_health.lower()} (detected via zpool status)',
                            'pool_name': pool_name,
                            'health': pool_health,
                        }
                    return zfs_issues
                except Exception:
                    return zfs_issues

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
        
        Respects storage exclusions: excluded storages are reported as INFO, not CRITICAL.
        
        During startup grace period (first 5 minutes after boot):
        - Storage errors are reported as INFO instead of CRITICAL
        - No persistent errors are recorded
        This prevents false positives when NFS/PBS/remote storage is still mounting.
        """
        if not PROXMOX_STORAGE_AVAILABLE:
            return None
        
        # Check if we're in startup grace period
        in_grace_period = _is_startup_health_grace()
        
        try:
            # Reload configuration to ensure we have the latest storage definitions
            proxmox_storage_monitor.reload_configuration()
            
            # Get the current status of all configured storages
            storage_status = proxmox_storage_monitor.get_storage_status()
            unavailable_storages = storage_status.get('unavailable', [])
            
            # Get excluded storage names for health monitoring
            excluded_names = health_persistence.get_excluded_storage_names('health')
            
            # Separate excluded storages from real issues
            excluded_unavailable = [s for s in unavailable_storages if s.get('name', '') in excluded_names]
            real_unavailable = [s for s in unavailable_storages if s.get('name', '') not in excluded_names]
            
            if not real_unavailable:
                # All non-excluded storages are available. Clear any previously recorded storage errors.
                active_errors = health_persistence.get_active_errors()
                for error in active_errors:
                    if error.get('category') == 'storage' and error.get('error_key', '').startswith('storage_unavailable_'):
                        # Only clear if not an excluded storage
                        storage_name = error.get('error_key', '').replace('storage_unavailable_', '')
                        if storage_name not in excluded_names:
                            health_persistence.clear_error(error['error_key'])
                
                # Build checks from all configured storages for descriptive display
                available_storages = storage_status.get('available', [])
                checks = {}
                for st in available_storages:
                    st_name = st.get('name', 'unknown')
                    st_type = st.get('type', 'unknown')
                    # Sprint 11.6: PBS namespace-restricted storages are reachable
                    # but the API hides the datastore size — surface as INFO so
                    # the operator understands why size columns read 0.
                    if st.get('status') == 'namespace_restricted':
                        checks[st_name] = {
                            'status': 'INFO',
                            'detail': f'{st_type} storage reachable (namespace-restricted: datastore size hidden by ACL)'
                        }
                    else:
                        checks[st_name] = {
                            'status': 'OK',
                            'detail': f'{st_type} storage available'
                        }
                
                # Add excluded unavailable storages as INFO (not CRITICAL)
                for st in excluded_unavailable:
                    st_name = st.get('name', 'unknown')
                    st_type = st.get('type', 'unknown')
                    checks[st_name] = {
                        'status': 'INFO',
                        'detail': f'{st_type} storage excluded from monitoring',
                        'excluded': True
                    }
                
                if not checks:
                    checks['proxmox_storages'] = {'status': 'OK', 'detail': 'All storages available'}
                return {'status': 'OK', 'checks': checks}
            
            storage_details = {}
            # Only process non-excluded unavailable storages as errors
            for storage in real_unavailable:
                storage_name = storage['name']
                error_key = f'storage_unavailable_{storage_name}'
                status_detail = storage.get('status_detail', 'unavailable')
                
                # Formulate a descriptive reason for the issue
                if status_detail == 'not_found':
                    reason = f"Storage '{storage_name}' is configured but not found on the server."
                elif status_detail == 'unavailable':
                    reason = f"Storage '{storage_name}' is not available (connection error or backend issue)."
                else:
                    reason = f"Storage '{storage_name}' has status: {status_detail}."
                
                # During grace period, don't record persistent errors (storage may still be mounting)
                # After grace period, record as CRITICAL
                if not in_grace_period:
                    health_persistence.record_error(
                        error_key=error_key,
                        category='storage',
                        severity='CRITICAL',
                        reason=reason,
                        details={
                            'storage_name': storage_name,
                            'storage_type': storage.get('type', 'unknown'),
                            'status_detail': status_detail,
                            'dismissable': False
                        }
                    )
                
                # Add to details dict with dismissable false for frontend
                storage_details[storage_name] = {
                    'reason': reason,
                    'type': storage.get('type', 'unknown'),
                    'status': status_detail,
                    'dismissable': False
                }
            
            # Build checks from storage_details
            # During grace period, report as INFO instead of CRITICAL
            checks = {}
            for st_name, st_info in storage_details.items():
                if in_grace_period:
                    checks[st_name] = {
                        'status': 'INFO',
                        'detail': f"[Startup] {st_info.get('reason', 'Unavailable')} (checking...)",
                        'dismissable': False,
                        'grace_period': True
                    }
                else:
                    checks[st_name] = {
                        'status': 'CRITICAL',
                        'detail': st_info.get('reason', 'Unavailable'),
                        'dismissable': False
                    }
            
            # Add excluded unavailable storages as INFO (not as errors)
            for st in excluded_unavailable:
                st_name = st.get('name', 'unknown')
                st_type = st.get('type', 'unknown')
                checks[st_name] = {
                    'status': 'INFO',
                    'detail': f'{st_type} storage excluded from monitoring (offline)',
                    'excluded': True
                }
            
            # Also add available storages
            available_list = storage_status.get('available', [])
            unavail_names = {s['name'] for s in unavailable_storages}
            for st in available_list:
                if st.get('name') not in unavail_names and st.get('name') not in checks:
                    checks[st['name']] = {
                        'status': 'OK',
                        'detail': f'{st.get("type", "unknown")} storage available'
                    }
            
            # Determine overall status based on non-excluded issues only
            if real_unavailable:
                # During grace period, return INFO instead of CRITICAL
                if in_grace_period:
                    return {
                        'status': 'INFO',
                        'reason': f'{len(real_unavailable)} storage(s) not yet available (startup)',
                        'details': storage_details,
                        'checks': checks,
                        'grace_period': True
                    }
                else:
                    return {
                        'status': 'CRITICAL',
                        'reason': f'{len(real_unavailable)} Proxmox storage(s) unavailable',
                        'details': storage_details,
                        'checks': checks
                    }
            else:
                # Only excluded storages are unavailable - this is OK
                return {
                    'status': 'OK',
                    'reason': 'All monitored storages available',
                    'checks': checks
                }
        
        except Exception as e:
            print(f"[HealthMonitor] Error checking Proxmox storage: {e}")
            # Return None on exception to indicate the check could not be performed, not necessarily a failure.
            return None

    def _check_remote_mounts(self) -> Optional[Dict[str, Any]]:
        """Sprint 13: per-mount NFS/CIFS/SMB health.

        Stale mounts get a CRITICAL — they're the failure mode that
        actually breaks user workflows (writes silently redirect to the
        local FS and fill the disk). Read-only that wasn't requested
        gets a WARNING. The persistence/clear logic mirrors the
        Proxmox-storage check so the same Health → details panel can
        render the result, and so notifications go through the same
        pipeline (events.py / templates.py) with the standard 1h
        cooldown.

        Returns ``None`` (not OK) when the module isn't importable, so
        the orchestrator skips the section entirely on hosts where the
        helper failed to load.
        """
        if not MOUNT_MONITOR_AVAILABLE:
            return None

        try:
            host_mounts = mount_monitor.scan_remote_mounts(force=True)
        except Exception as e:
            print(f"[HealthMonitor] mount_monitor.scan failed: {e}")
            host_mounts = []

        # Sprint 13.27: also pick up mounts inside running LXCs. Wrapped
        # separately so a stuck `pct exec` doesn't blank the host result.
        try:
            lxc_mounts_list = mount_monitor.scan_lxc_mounts(force=True)
        except Exception as e:
            print(f"[HealthMonitor] mount_monitor.scan_lxc_mounts failed: {e}")
            lxc_mounts_list = []

        mounts = list(host_mounts) + list(lxc_mounts_list)

        if not mounts:
            # No remote mounts on this host — nothing to monitor and
            # nothing to clear. Skip the section so it doesn't render
            # as an empty card on the dashboard.
            return None

        checks: Dict[str, Dict[str, Any]] = {}
        critical_targets: list[str] = []
        warning_targets: list[str] = []

        for m in mounts:
            target = m.get('target', '?')
            status = m.get('status', 'ok')
            fstype = m.get('fstype', '?')
            error = m.get('error') or ''
            lxc_id = m.get('lxc_id', '') or ''
            lxc_name = m.get('lxc_name', '') or ''

            # Disambiguate same-target across host vs LXCs (e.g. /mnt/nas
            # could exist both on host and inside CT 101). Without the
            # CT prefix, both would share an error_key and one entry's
            # recovery would clear the other's alert.
            if lxc_id:
                key_target = f'ct{lxc_id}:{target}'
                ct_label = f'CT {lxc_id}' + (f" ({lxc_name})" if lxc_name else '')
                check_label = f'{ct_label} {target}'
                # Pre-formatted suffix the notification body inserts as
                # `{lxc_scope}` — leading space included so the rendered
                # sentence reads "...is stale inside CT 101 (nginx)."
                lxc_scope = f' inside {ct_label}'
            else:
                key_target = target
                ct_label = ''
                check_label = target
                lxc_scope = ''
            error_key = f'mount_{status}_{key_target}'

            if status == 'stale':
                checks[check_label] = {
                    'status': 'CRITICAL',
                    'detail': f'{fstype} mount stale: {error or "unreachable"}',
                    'fstype': fstype,
                    'source': m.get('source', ''),
                    'lxc_id': lxc_id,
                    'lxc_name': lxc_name,
                }
                critical_targets.append(check_label)
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage',
                    severity='CRITICAL',
                    reason=(
                        f'Remote mount {target} inside {ct_label} is stale ({fstype})'
                        if lxc_id else
                        f'Remote mount {target} is stale ({fstype})'
                    ),
                    details={
                        'mount_target': target,
                        'mount_source': m.get('source', ''),
                        'fstype': fstype,
                        'error': error,
                        'lxc_id': lxc_id,
                        'lxc_name': lxc_name,
                        'lxc_scope': lxc_scope,
                    },
                )
            elif status == 'readonly':
                checks[check_label] = {
                    'status': 'WARNING',
                    'detail': f'{fstype} mount unexpectedly read-only',
                    'fstype': fstype,
                    'source': m.get('source', ''),
                    'lxc_id': lxc_id,
                    'lxc_name': lxc_name,
                }
                warning_targets.append(check_label)
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage',
                    severity='WARNING',
                    reason=(
                        f'Remote mount {target} inside {ct_label} is read-only'
                        if lxc_id else
                        f'Remote mount {target} is read-only'
                    ),
                    details={
                        'mount_target': target,
                        'mount_source': m.get('source', ''),
                        'fstype': fstype,
                        'lxc_id': lxc_id,
                        'lxc_name': lxc_name,
                        'lxc_scope': lxc_scope,
                    },
                )
            else:
                checks[check_label] = {
                    'status': 'OK',
                    'detail': f'{fstype} mount reachable',
                    'fstype': fstype,
                    'source': m.get('source', ''),
                    'lxc_id': lxc_id,
                    'lxc_name': lxc_name,
                }

        # Clear errors for mounts that recovered. error_key shape is
        # "mount_<status>_<key_target>" where key_target is either the
        # plain path (host mount) or "ct<id>:<path>" (LXC mount).
        # Build the set of currently-active "bad" keys this round so
        # any previously-recorded mount_* error not in that set means
        # the mount is now OK and can be cleared.
        active_errors = health_persistence.get_active_errors() or []
        emitted_keys: set[str] = set()
        for m in mounts:
            status = m.get('status', 'ok')
            if status not in ('stale', 'readonly'):
                continue
            target = m.get('target', '?')
            lxc_id = m.get('lxc_id', '') or ''
            key_target = f'ct{lxc_id}:{target}' if lxc_id else target
            emitted_keys.add(f'mount_{status}_{key_target}')

        for err in active_errors:
            ek = err.get('error_key', '')
            if not ek.startswith('mount_'):
                continue
            if ek not in emitted_keys:
                health_persistence.clear_error(ek)

        if critical_targets:
            return {
                'status': 'CRITICAL',
                'reason': f'{len(critical_targets)} remote mount(s) stale: {", ".join(critical_targets[:3])}',
                'checks': checks,
            }
        if warning_targets:
            return {
                'status': 'WARNING',
                'reason': f'{len(warning_targets)} remote mount(s) read-only: {", ".join(warning_targets[:3])}',
                'checks': checks,
            }
        return {
            'status': 'OK',
            'reason': f'{len(mounts)} remote mount(s) healthy',
            'checks': checks,
        }

    def _check_lxc_disk_usage(self) -> Optional[Dict[str, Any]]:
        """Sprint 13.30: rootfs disk usage per LXC.

        The classic failure mode this catches: a CT's rootfs is sized
        at 2 GB, the app inside writes logs continuously, and one day
        the CT runs out of space and stops booting. We pull
        per-resource ``disk`` / ``maxdisk`` from
        ``pvesh /cluster/resources --type vm`` (cheap, already cached
        upstream by Proxmox) and emit a WARNING at 85% / CRITICAL at
        95% — the same thresholds the host disk check uses, so the
        operator's mental model is consistent.

        Notification cooldown is the standard 1h via the storage
        category, so a CT teetering at 96% won't spam the channel.
        """
        # Cheap pre-check: bail out when there are no running LXCs. On
        # nodes without CTs, the previous version still paid ~860ms per
        # cycle for a `pvesh /cluster/resources` call that produced no
        # actionable data. We reuse the `lxc-start` /proc walk that
        # `mount_monitor` already exposes — costs ~1-5ms regardless of
        # process count.
        if MOUNT_MONITOR_AVAILABLE and not mount_monitor._has_any_running_lxc():
            return None

        # Reuse the flask_server-level pvesh cache instead of running our
        # own subprocess. The shared helper holds the result for 2s and
        # is also consumed by `_check_vms_cts_optimized` and the VMs/LXCs
        # API route, so within a single health-collector cycle we get
        # this for free instead of paying ~860ms per pvesh invocation.
        try:
            import flask_server  # deferred — avoids circular import at module load
            resources = flask_server.get_cached_pvesh_cluster_resources_vm() or []
        except Exception as e:
            print(f"[HealthMonitor] LXC disk check failed: {e}")
            return None

        # User-configurable LXC rootfs thresholds (defaults 85 / 95).
        try:
            import health_thresholds as _ht
            WARN_PCT = _ht.get("lxc_rootfs", "warning", default=85)
            CRIT_PCT = _ht.get("lxc_rootfs", "critical", default=95)
        except Exception:
            WARN_PCT = 85
            CRIT_PCT = 95

        checks: Dict[str, Dict[str, Any]] = {}
        critical_cts: list[str] = []
        warning_cts: list[str] = []
        emitted_keys: set[str] = set()

        for r in resources:
            if r.get('type') != 'lxc':
                continue
            if r.get('status') != 'running':
                # Stopped CTs — `disk` reads as 0 from pvesh because the
                # rootfs isn't mounted. Skip rather than report a
                # misleading 0%.
                continue
            try:
                disk = int(r.get('disk') or 0)
                maxdisk = int(r.get('maxdisk') or 0)
            except (TypeError, ValueError):
                continue
            if maxdisk <= 0:
                continue
            pct = (disk / maxdisk) * 100
            vmid = str(r.get('vmid', ''))
            name = r.get('name', '') or ''
            label = f'CT {vmid}' + (f' ({name})' if name else '')

            entry: Dict[str, Any] = {
                'detail': f'rootfs {pct:.1f}% used ({disk // (1024**2)} MB / {maxdisk // (1024**2)} MB)',
                'usage_percent': round(pct, 1),
                'disk_bytes': disk,
                'maxdisk_bytes': maxdisk,
                'vmid': vmid,
                'name': name,
            }
            error_key = f'lxc_disk_{vmid}'

            if pct >= CRIT_PCT:
                entry['status'] = 'CRITICAL'
                entry['error_key'] = error_key
                entry['dismissable'] = True
                checks[label] = entry
                critical_cts.append(label)
                emitted_keys.add(error_key)
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage',
                    severity='CRITICAL',
                    reason=f'{label} rootfs at {pct:.1f}% ({disk // (1024**2)} MB / {maxdisk // (1024**2)} MB)',
                    details=entry,
                )
            elif pct >= WARN_PCT:
                entry['status'] = 'WARNING'
                entry['error_key'] = error_key
                entry['dismissable'] = True
                checks[label] = entry
                warning_cts.append(label)
                emitted_keys.add(error_key)
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage',
                    severity='WARNING',
                    reason=f'{label} rootfs at {pct:.1f}% ({disk // (1024**2)} MB / {maxdisk // (1024**2)} MB)',
                    details=entry,
                )
            else:
                entry['status'] = 'OK'
                checks[label] = entry

        # Clear errors for CTs that recovered (disk freed up below
        # warning threshold, or CT stopped).
        for err in (health_persistence.get_active_errors() or []):
            ek = err.get('error_key', '')
            if not ek.startswith('lxc_disk_'):
                continue
            if ek not in emitted_keys:
                health_persistence.clear_error(ek)

        if not checks:
            return None
        if critical_cts:
            return {
                'status': 'CRITICAL',
                'reason': f'{len(critical_cts)} CT(s) at >{CRIT_PCT}% rootfs: {", ".join(critical_cts[:3])}',
                'checks': checks,
            }
        if warning_cts:
            return {
                'status': 'WARNING',
                'reason': f'{len(warning_cts)} CT(s) at >{WARN_PCT}% rootfs: {", ".join(warning_cts[:3])}',
                'checks': checks,
            }
        return {
            'status': 'OK',
            'reason': f'{len(checks)} running CT(s) within safe rootfs usage',
            'checks': checks,
        }

    # ─── Phase 3 capacity checks ─────────────────────────────────────────────
    #
    # Three sibling methods that all share the same shape:
    #   - Bail fast when the dependency isn't available (no CTs running,
    #     no PVE storage module, no `zpool` binary).
    #   - Read user-configured thresholds (or fall back to defaults).
    #   - Iterate the relevant entities, classify each, persist any
    #     critical/warning errors via health_persistence so the
    #     notification stack picks them up, clear stale ones.
    #   - Return None when there's literally nothing to monitor — that
    #     keeps the dashboard from rendering an empty card.

    def _read_capacity_thresholds(self, section: str, fb_warn: float = 85, fb_crit: float = 95) -> tuple[float, float]:
        """Resolve (warning, critical) for a capacity section, falling
        back to the safe 85/95 default. Tiny helper to avoid copy-paste
        across the three checks below."""
        try:
            import health_thresholds as _ht
            warn = _ht.get(section, "warning", default=fb_warn)
            crit = _ht.get(section, "critical", default=fb_crit)
            return float(warn), float(crit)
        except Exception:
            return float(fb_warn), float(fb_crit)

    def _check_lxc_mount_capacity(self) -> Optional[Dict[str, Any]]:
        """Capacity of mountpoints inside running LXCs.

        Catches the failure mode of "CT had a 50G NFS mount full of
        photos and now the app can't write" — distinct from the rootfs
        check (already covered) because those are usually large data
        mounts whose fill rate is driven by user content, not log spam.
        """
        if not MOUNT_MONITOR_AVAILABLE:
            return None
        try:
            mounts = mount_monitor.scan_lxc_mount_capacity()
        except Exception as e:
            print(f"[HealthMonitor] LXC mount capacity scan failed: {e}")
            return None
        if not mounts:
            return None

        warn_pct, crit_pct = self._read_capacity_thresholds("lxc_mount")
        checks: Dict[str, Dict[str, Any]] = {}
        critical_labels: list[str] = []
        warning_labels: list[str] = []
        emitted_keys: set[str] = set()

        for m in mounts:
            pct = float(m.get('usage_percent', 0))
            vmid = str(m.get('vmid', ''))
            mount = m.get('mount', '')
            label = f"CT {vmid}:{mount}"
            entry = {
                'usage_percent': pct,
                'mount': mount,
                'vmid': vmid,
                'name': m.get('name', ''),
                'fstype': m.get('fstype', ''),
                'total_bytes': m.get('total_bytes', 0),
                'used_bytes': m.get('used_bytes', 0),
                'available_bytes': m.get('available_bytes', 0),
            }
            error_key = f'lxc_mount_{vmid}_{mount}'
            if pct >= crit_pct:
                entry['status'] = 'CRITICAL'
                entry['error_key'] = error_key
                entry['dismissable'] = True
                checks[label] = entry
                critical_labels.append(label)
                emitted_keys.add(error_key)
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage',
                    severity='CRITICAL',
                    reason=f'{label} at {pct:.1f}% used',
                    details=entry,
                )
            elif pct >= warn_pct:
                entry['status'] = 'WARNING'
                entry['error_key'] = error_key
                entry['dismissable'] = True
                checks[label] = entry
                warning_labels.append(label)
                emitted_keys.add(error_key)
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage',
                    severity='WARNING',
                    reason=f'{label} at {pct:.1f}% used',
                    details=entry,
                )
            else:
                entry['status'] = 'OK'
                checks[label] = entry

        # Clear any previously-flagged mounts that are now under threshold
        # (e.g. user freed up space). Without this the alert sticks
        # forever in the persistence DB.
        for active in health_persistence.get_active_errors('storage'):
            ek = active.get('error_key', '')
            if ek.startswith('lxc_mount_') and ek not in emitted_keys:
                health_persistence.clear_error(ek)

        if critical_labels:
            return {
                'status': 'CRITICAL',
                'reason': f'{len(critical_labels)} CT mount(s) ≥{crit_pct:.0f}%: {", ".join(critical_labels[:3])}',
                'checks': checks,
            }
        if warning_labels:
            return {
                'status': 'WARNING',
                'reason': f'{len(warning_labels)} CT mount(s) ≥{warn_pct:.0f}%: {", ".join(warning_labels[:3])}',
                'checks': checks,
            }
        return {
            'status': 'OK',
            'reason': f'{len(checks)} CT mount(s) within safe usage',
            'checks': checks,
        }

    def _check_pve_storage_capacity(self) -> Optional[Dict[str, Any]]:
        """Capacity of PVE-registered storages that are NOT surfaced as
        a host filesystem (LVM, LVM-thin, RBD, ZFS-pool, PBS).

        Why filter: filesystem-style storages (dir / nfs / cifs) appear
        under /mnt/pve/* and are already covered by the host disk
        check via _check_filesystem. Re-alerting on the same condition
        through two channels just clutters the inbox.
        """
        if not PROXMOX_STORAGE_AVAILABLE:
            return None
        try:
            from proxmox_storage_monitor import proxmox_storage_monitor as psm
            storage_status = psm.get_storage_status()
        except Exception as e:
            print(f"[HealthMonitor] PVE storage capacity fetch failed: {e}")
            return None

        # Storage types that don't surface as a host mount → these are
        # the ones we want to monitor here.
        BLOCK_TYPES = {'lvm', 'lvmthin', 'rbd', 'zfspool', 'cephfs', 'pbs'}

        warn_pct, crit_pct = self._read_capacity_thresholds("pve_storage")
        available_storages = storage_status.get('available', []) or []
        checks: Dict[str, Dict[str, Any]] = {}
        critical_labels: list[str] = []
        warning_labels: list[str] = []
        emitted_keys: set[str] = set()

        for st in available_storages:
            stype = (st.get('type') or '').lower()
            if stype not in BLOCK_TYPES:
                continue
            total = int(st.get('total', 0) or 0)
            used = int(st.get('used', 0) or 0)
            if total <= 0:
                continue
            pct = (used / total) * 100
            name = st.get('name', 'unknown')
            label = f'{name} ({stype})'
            entry = {
                'usage_percent': round(pct, 1),
                'storage_name': name,
                'storage_type': stype,
                'total_bytes': total,
                'used_bytes': used,
            }
            error_key = f'pve_storage_full_{name}'
            # If the user already dismissed this exact error (within the
            # suppression window), don't count it toward the category
            # severity badge. Without this guard the storage section stayed
            # WARNING/CRITICAL forever even after dismiss because the
            # underlying % is unchanged — `record_error` correctly returned
            # `skipped_acknowledged` to silence the notification side, but
            # the dashboard counter ignored that signal and the user saw
            # "Storage: 1 Warning" with no way to clear it. Reported on
            # the community channel re: PBS-lleno (17-18/05).
            is_dismissed = health_persistence.is_error_acknowledged(error_key)
            if pct >= crit_pct:
                entry['status'] = 'CRITICAL' if not is_dismissed else 'INFO'
                entry['error_key'] = error_key
                entry['dismissable'] = True
                entry['dismissed'] = is_dismissed
                checks[label] = entry
                if not is_dismissed:
                    critical_labels.append(label)
                emitted_keys.add(error_key)
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage',
                    severity='CRITICAL',
                    reason=f'PVE storage {label} at {pct:.1f}% used',
                    details=entry,
                )
            elif pct >= warn_pct:
                entry['status'] = 'WARNING' if not is_dismissed else 'INFO'
                entry['error_key'] = error_key
                entry['dismissable'] = True
                entry['dismissed'] = is_dismissed
                checks[label] = entry
                if not is_dismissed:
                    warning_labels.append(label)
                emitted_keys.add(error_key)
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage',
                    severity='WARNING',
                    reason=f'PVE storage {label} at {pct:.1f}% used',
                    details=entry,
                )
            else:
                entry['status'] = 'OK'
                checks[label] = entry

        for active in health_persistence.get_active_errors('storage'):
            ek = active.get('error_key', '')
            if ek.startswith('pve_storage_full_') and ek not in emitted_keys:
                health_persistence.clear_error(ek)

        if not checks:
            return None  # No block storages on this host
        if critical_labels:
            return {
                'status': 'CRITICAL',
                'reason': f'{len(critical_labels)} PVE storage(s) ≥{crit_pct:.0f}%: {", ".join(critical_labels[:3])}',
                'checks': checks,
            }
        if warning_labels:
            return {
                'status': 'WARNING',
                'reason': f'{len(warning_labels)} PVE storage(s) ≥{warn_pct:.0f}%: {", ".join(warning_labels[:3])}',
                'checks': checks,
            }
        return {
            'status': 'OK',
            'reason': f'{len(checks)} PVE block storage(s) within safe usage',
            'checks': checks,
        }

    def _check_zfs_pool_capacity(self) -> Optional[Dict[str, Any]]:
        """ZFS pool fill level.

        Independent from `_check_pve_storage_capacity` so pools that
        aren't registered as PVE storage (rpool, dedicated backup
        pools, etc.) still raise alerts. `zpool list -H -p -o
        name,capacity` is one cheap subprocess call regardless of
        pool count — capacity is an integer percent already, no math
        needed.
        """
        try:
            proc = subprocess.run(
                ['zpool', 'list', '-H', '-p', '-o', 'name,capacity'],
                capture_output=True, text=True, timeout=5,
            )
        except FileNotFoundError:
            return None  # ZFS not installed
        except Exception as e:
            print(f"[HealthMonitor] zpool list failed: {e}")
            return None
        if proc.returncode != 0:
            return None
        rows = [ln.split() for ln in proc.stdout.strip().splitlines() if ln.strip()]
        if not rows:
            return None

        warn_pct, crit_pct = self._read_capacity_thresholds("zfs_pool")
        checks: Dict[str, Dict[str, Any]] = {}
        critical_labels: list[str] = []
        warning_labels: list[str] = []
        emitted_keys: set[str] = set()

        for row in rows:
            if len(row) < 2:
                continue
            name = row[0]
            try:
                pct = float(row[1])
            except ValueError:
                continue
            entry = {
                'usage_percent': pct,
                'pool_name': name,
            }
            error_key = f'zfs_pool_full_{name}'
            # Same dismiss-respect as `_check_pve_storage_capacity`. A pool
            # that the user dismissed keeps its underlying % but should no
            # longer flip the category badge to WARNING/CRITICAL.
            is_dismissed = health_persistence.is_error_acknowledged(error_key)
            if pct >= crit_pct:
                entry['status'] = 'CRITICAL' if not is_dismissed else 'INFO'
                entry['error_key'] = error_key
                entry['dismissable'] = True
                entry['dismissed'] = is_dismissed
                checks[name] = entry
                if not is_dismissed:
                    critical_labels.append(name)
                emitted_keys.add(error_key)
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage',
                    severity='CRITICAL',
                    reason=f'ZFS pool {name} at {pct:.1f}% used',
                    details=entry,
                )
            elif pct >= warn_pct:
                entry['status'] = 'WARNING' if not is_dismissed else 'INFO'
                entry['error_key'] = error_key
                entry['dismissable'] = True
                entry['dismissed'] = is_dismissed
                checks[name] = entry
                if not is_dismissed:
                    warning_labels.append(name)
                emitted_keys.add(error_key)
                health_persistence.record_error(
                    error_key=error_key,
                    category='storage',
                    severity='WARNING',
                    reason=f'ZFS pool {name} at {pct:.1f}% used',
                    details=entry,
                )
            else:
                entry['status'] = 'OK'
                checks[name] = entry

        for active in health_persistence.get_active_errors('storage'):
            ek = active.get('error_key', '')
            if ek.startswith('zfs_pool_full_') and ek not in emitted_keys:
                health_persistence.clear_error(ek)

        if critical_labels:
            return {
                'status': 'CRITICAL',
                'reason': f'{len(critical_labels)} ZFS pool(s) ≥{crit_pct:.0f}%: {", ".join(critical_labels[:3])}',
                'checks': checks,
            }
        if warning_labels:
            return {
                'status': 'WARNING',
                'reason': f'{len(warning_labels)} ZFS pool(s) ≥{warn_pct:.0f}%: {", ".join(warning_labels[:3])}',
                'checks': checks,
            }
        return {
            'status': 'OK',
            'reason': f'{len(checks)} ZFS pool(s) within safe usage',
            'checks': checks,
        }

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
    
    # Duplicate get_detailed_status was removed during refactor (v1.1)


# Global instance
health_monitor = HealthMonitor()
