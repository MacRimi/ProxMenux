"""
ProxMenux Notification Event Watchers
Detects Proxmox events from journald, PVE task log, and health monitor.

Architecture:
- JournalWatcher: Real-time stream of journald for critical events
- TaskWatcher: Real-time tail of /var/log/pve/tasks/index for VM/CT/backup events
- PollingCollector: Periodic poll of health_persistence pending notifications

All watchers put events into a shared Queue consumed by NotificationManager.

Author: MacRimi
"""

import os
import re
import json
import time
import hashlib
import socket
import sqlite3
import subprocess
import threading
from queue import Queue
from typing import Optional, Dict, Any, Tuple
from pathlib import Path


# ─── Shared State for Cross-Watcher Coordination ──────────────────

# ─── Startup Grace Period ────────────────────────────────────────────────────
# Import centralized startup grace management
# This provides a single source of truth for all grace period logic
import startup_grace

class _SharedState:
    """Wrapper around centralized startup_grace module for backwards compatibility.
    
    All grace period logic is now in startup_grace.py for consistency across:
    - notification_events.py (this file)
    - health_monitor.py
    - flask_server.py
    """
    
    def mark_shutdown(self):
        """Called when system_shutdown or system_reboot is detected."""
        startup_grace.mark_shutdown()
    
    def is_host_shutting_down(self) -> bool:
        """Check if we're within the shutdown grace period."""
        return startup_grace.is_host_shutting_down()
    
    def is_startup_period(self) -> bool:
        """Check if we're within the startup VM aggregation period (3 min)."""
        return startup_grace.is_startup_vm_period()
    
    def is_startup_health_grace(self) -> bool:
        """Check if we're within the startup health grace period (5 min)."""
        return startup_grace.is_startup_health_grace()
    
    def add_startup_vm(self, vmid: str, vmname: str, vm_type: str):
        """Record a VM/CT start during startup period for later aggregation."""
        startup_grace.add_startup_vm(vmid, vmname, vm_type)
    
    def get_and_clear_startup_vms(self) -> list:
        """Get all recorded startup VMs and clear the list."""
        return startup_grace.get_and_clear_startup_vms()
    
    def has_startup_vms(self) -> bool:
        """Check if there are any startup VMs recorded."""
        return startup_grace.has_startup_vms()
    
    def was_startup_aggregated(self) -> bool:
        """Check if startup aggregation already happened."""
        return startup_grace.was_startup_aggregated()


# Global shared state instance
_shared_state = _SharedState()


# ─── Event Object ─────────────────────────────────────────────────

class NotificationEvent:
    """Represents a detected event ready for notification dispatch.
    
    Fields:
        event_type:   Taxonomy key (e.g. 'vm_fail', 'auth_fail', 'split_brain')
        severity:     INFO | WARNING | CRITICAL
        data:         Payload dict with context (hostname, vmid, reason, etc.)
        source:       Origin: journal | tasks | health | proxmox_hook | cli | api | polling
        entity:       What is affected: node | vm | ct | storage | disk | network | cluster | user
        entity_id:    Specific identifier (vmid, IP, device, pool, interface, etc.)
        raw:          Original payload (webhook JSON or log line), optional
        fingerprint:  Stable dedup key: hostname:entity:entity_id:event_type
        event_id:     Short hash of fingerprint for correlation
        ts_epoch:     time.time() at creation
        ts_monotonic: time.monotonic() at creation (drift-safe for cooldown)
    """
    
    __slots__ = (
        'event_type', 'severity', 'data', 'timestamp', 'source',
        'entity', 'entity_id', 'raw',
        'fingerprint', 'event_id', 'ts_epoch', 'ts_monotonic',
    )
    
    def __init__(self, event_type: str, severity: str = 'INFO',
                 data: Optional[Dict[str, Any]] = None,
                 source: str = 'watcher',
                 entity: str = 'node', entity_id: str = '',
                 raw: Any = None):
        self.event_type = event_type
        self.severity = severity
        self.data = data or {}
        self.source = source
        self.entity = entity
        self.entity_id = entity_id
        self.raw = raw
        self.ts_epoch = time.time()
        self.ts_monotonic = time.monotonic()
        self.timestamp = self.ts_epoch  # backward compat
        
        # Build fingerprint for dedup/cooldown
        hostname = self.data.get('hostname', _hostname())
        if entity_id:
            fp_base = f"{hostname}:{entity}:{entity_id}:{event_type}"
        else:
            # When entity_id is empty, include a hash of title/body for uniqueness
            reason = self.data.get('reason', self.data.get('title', ''))
            stable_extra = hashlib.md5(reason.encode(errors='replace')).hexdigest()[:8] if reason else ''
            fp_base = f"{hostname}:{entity}:{event_type}:{stable_extra}"
        self.fingerprint = fp_base
        self.event_id = hashlib.md5(fp_base.encode()).hexdigest()[:12]
    
    def __repr__(self):
        return f"NotificationEvent({self.event_type}, {self.severity}, fp={self.fingerprint[:40]})"


_HOSTNAME_CACHE: Dict[str, Any] = {'value': None, 'ts': 0.0}
_HOSTNAME_CACHE_TTL = 5.0  # seconds


def _hostname() -> str:
    """Get display hostname for notifications.

    Returns the custom display name from notification settings if configured,
    otherwise falls back to the system FQDN (NOT truncated at the first dot —
    a host called ``px.seeindustry.com`` is rendered in full so multi-host
    deployments stay distinguishable).

    Reads are cached for ~5 s so a burst of events (~tens per cycle) doesn't
    hit the SQLite settings table on every call. The TTL is short enough that
    a freshly-saved alias takes effect within seconds without restarting the
    service — fixes the original behaviour where `self._hostname = _hostname()`
    was cached in `__init__` and never refreshed.
    """
    now = time.time()
    cached = _HOSTNAME_CACHE.get('value')
    if cached is not None and (now - _HOSTNAME_CACHE['ts']) < _HOSTNAME_CACHE_TTL:
        return cached

    resolved = ''
    # Try to read custom display name from notification settings
    try:
        db_path = Path('/usr/local/share/proxmenux/health_monitor.db')
        if db_path.exists():
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.execute('PRAGMA busy_timeout=3000')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT setting_value FROM user_settings WHERE setting_key = ?",
                ('notification.hostname',)
            )
            row = cursor.fetchone()
            conn.close()
            if row and row[0] and row[0].strip():
                resolved = row[0].strip()
    except Exception:
        pass  # Fall back to system hostname

    if not resolved:
        # Use FULL FQDN — never truncate at the first dot. The previous
        # `.split('.')[0]` produced misleading bare labels like "px" when the
        # alias was missing or unreadable, with no way for the operator to
        # tell which of their `px.*.example.com` nodes the notification came
        # from. The Display Name (alias) remains the recommended override.
        try:
            resolved = socket.gethostname()
        except Exception:
            resolved = 'proxmox'

    _HOSTNAME_CACHE['value'] = resolved
    _HOSTNAME_CACHE['ts'] = now
    return resolved


def capture_journal_context(keywords: list, lines: int = 30,
                            since: str = "5 minutes ago") -> str:
    """Capture relevant journal lines for AI context enrichment.
    
    Searches recent journald entries for lines matching any of the
    provided keywords and returns them for AI analysis.
    
    Args:
        keywords: List of terms to filter (e.g., ['sdh', 'ata8', 'I/O error'])
        lines: Maximum number of lines to return (default: 30)
        since: Time window for journalctl (default: "5 minutes ago")
        
    Returns:
        Filtered journal output as string, or empty string if none found
        
    Example:
        context = capture_journal_context(
            keywords=['sdh', 'ata8', 'exception'],
            lines=30
        )
    """
    if not keywords:
        return ""
    
    try:
        # Build grep pattern from keywords
        pattern = "|".join(re.escape(k) for k in keywords if k)
        if not pattern:
            return ""
        
        # Use journalctl with grep to filter relevant lines
        # Use -b 0 to only include logs from the current boot (not previous boots)
        cmd = (
            f"journalctl -b 0 --since='{since}' --no-pager -n 500 2>/dev/null | "
            f"grep -iE '{pattern}' | tail -n {lines}"
        )
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return ""
    except subprocess.TimeoutExpired:
        return ""
    except Exception as e:
        # Silently fail - journal context is optional
        return ""


# ─── smartd observation helper (shared by JournalWatcher & ProxmoxHookWatcher) ──
#
# Both watchers receive smartd messages — JournalWatcher via local journal,
# ProxmoxHookWatcher via the PVE notification webhook. Previously the method
# only existed on JournalWatcher and ProxmoxHookWatcher called `self._record_smartd_observation`,
# raising AttributeError on every PVE webhook with a smartd payload (silently
# turning into a 500). Audit Tier 6 (Notification stack #2).
def _record_smartd_observation_impl(title: str, message: str):
    """Extract device info from a smartd system-mail and record as disk observation."""
    try:
        import re as _re
        from health_persistence import health_persistence

        # Extract device path: "Device: /dev/sdh [SAT]" or "Device: /dev/sda"
        dev_match = _re.search(r'Device:\s*/dev/(\S+?)[\s\[\],]', message)
        device = dev_match.group(1) if dev_match else ''
        if not device:
            return
        # Strip partition suffix and SAT prefix
        base_dev = _re.sub(r'\d+$', '', device)

        # Extract serial: "S/N:WD-WX72A30AA72R"
        sn_match = _re.search(r'S/N:\s*(\S+)', message)
        serial = sn_match.group(1) if sn_match else ''

        # Extract model: appears before S/N on the "Device info:" line
        model = ''
        model_match = _re.search(r'Device info:\s*\n?\s*(.+?)(?:,\s*S/N:)', message)
        if model_match:
            model = model_match.group(1).strip()

        # Extract error signature from title: "SMART error (FailedReadSmartSelfTestLog)"
        sig_match = _re.search(r'SMART error\s*\((\w+)\)', title)
        if sig_match:
            error_signature = sig_match.group(1)
            error_type = 'smart_error'
        else:
            # Fallback: extract the "warning/error logged" line
            warn_match = _re.search(
                r'warning/error was logged.*?:\s*\n?\s*(.+)', message, _re.IGNORECASE)
            if warn_match:
                error_signature = _re.sub(r'[^a-zA-Z0-9_]', '_',
                                          warn_match.group(1).strip())[:80]
            else:
                error_signature = _re.sub(r'[^a-zA-Z0-9_]', '_', title)[:80]
            error_type = 'smart_error'

        # Build a clean raw_message for display
        raw_msg = f"Device: /dev/{base_dev}"
        if model:
            raw_msg += f" ({model})"
        if serial:
            raw_msg += f" S/N:{serial}"
        warn_line_m = _re.search(
            r'The following warning/error.*?:\s*\n?\s*(.+)', message, _re.IGNORECASE)
        if warn_line_m:
            raw_msg += f"\n{warn_line_m.group(1).strip()}"

        health_persistence.record_disk_observation(
            device_name=base_dev,
            serial=serial,
            error_type=error_type,
            error_signature=error_signature,
            raw_message=raw_msg,
            severity='warning',
        )
    except Exception as e:
        print(f"[smartd_observation] Error recording smartd observation: {e}")


# ─── Vzdump activity detector (shared, restart-tolerant) ─────────
#
# A single source of truth for "is a vzdump backup job running on this
# host RIGHT NOW", consultable from any watcher and surviving Monitor
# restarts. Reads `/var/log/pve/tasks/active` directly — PVE writes the
# active UPID there at backup start and removes it on completion, so
# it persists across our process restarts.
#
# Without this, JournalWatcher's in-memory `_last_backup_job_ts` got
# reset by every Monitor restart, and any `Starting Backup of VM X`
# log lines arriving after that point were treated as standalone
# backups — emitting one `backup_start` per guest with `storage=local`
# (the fallback path that doesn't see the parent job's --storage flag).
# Reported by JC Miñarro 18/05 after a Monitor redeploy mid-job.
_VZDUMP_ACTIVE_FILE = '/var/log/pve/tasks/active'
_vzdump_active_cache_ts: float = 0
_vzdump_active_cache_value: bool = False
_VZDUMP_ACTIVE_CACHE_TTL = 5  # seconds


def is_vzdump_active_on_host() -> bool:
    """Return True if `/var/log/pve/tasks/active` contains an active
    vzdump UPID (i.e. backup currently running). Cached 5s to avoid
    hammering the file on every notification.

    Caller-safe: returns False on any I/O / parse error.
    """
    global _vzdump_active_cache_ts, _vzdump_active_cache_value
    now = time.time()
    if now - _vzdump_active_cache_ts < _VZDUMP_ACTIVE_CACHE_TTL:
        return _vzdump_active_cache_value
    found = False
    try:
        with open(_VZDUMP_ACTIVE_FILE, 'r') as f:
            for line in f:
                # tasks/active row layout (whitespace separated):
                #   "<UPID> 1"                                ← running
                #   "<UPID> 1 <endtime_hex> <STATUS>"         ← finished
                # PVE leaves finished rows lingering for hours
                # sometimes — without the field-count check below the
                # PID-recycling case fires a false positive (an
                # unrelated process inherited the old vzdump's PID
                # and `os.kill(pid, 0)` succeeds).
                if ':vzdump:' not in line:
                    continue
                fields = line.split()
                if not fields:
                    continue
                # >2 fields means endtime + status are written → terminated.
                if len(fields) > 2:
                    continue
                upid_parts = fields[0].split(':')
                if len(upid_parts) < 3:
                    continue
                try:
                    pid = int(upid_parts[2], 16)  # PID in UPID is hex
                    os.kill(pid, 0)
                    found = True
                    break
                except (ValueError, ProcessLookupError, PermissionError):
                    continue
    except (OSError, IOError):
        pass
    _vzdump_active_cache_ts = now
    _vzdump_active_cache_value = found
    return found


# ─── Journal Watcher (Real-time) ─────────────────────────────────

class JournalWatcher:
    """Watches journald in real-time for critical system events.
    
    Uses 'journalctl -f -o json' subprocess to stream entries.
    Detects: auth failures, kernel panics, OOM, service crashes,
    disk I/O errors, split-brain, node disconnect, system shutdown,
    fail2ban bans, firewall blocks, permission changes.
    """
    
    def __init__(self, event_queue: Queue):
        self._queue = event_queue
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None
        # `_hostname` is exposed as a @property below so every read returns
        # the *current* alias from the settings DB (TTL-cached for 5 s in
        # _hostname()). The old `__init__`-time cache made a fresh Display
        # Name require a service restart to take effect.
        
        # Dedup: track recent events to avoid duplicates
        self._recent_events: Dict[str, float] = {}
        self._dedup_window = 30  # seconds

        # 24h anti-cascade for disk I/O + filesystem errors. The dict
        # key includes a tier suffix (`sdh:warning`, `sdh:critical`)
        # so a disk in WARNING cooldown can still escalate to CRITICAL
        # within the same 24h if the rate accelerates.
        self._disk_io_notified: Dict[str, float] = {}
        self._DISK_IO_COOLDOWN = 86400  # 24 hours

        # Sliding 24h window of ATA error timestamps per disk, used to
        # decide notification severity tier. Don't blindly trust the
        # SMART firmware self-report — the Google "Failure Trends"
        # paper showed ~36% of failed drives gave no SMART warning.
        # Rate-based escalation catches the dying drives that SMART
        # would never flag until they were already bricked.
        from collections import deque as _deque
        self._disk_error_window: Dict[str, "_deque[float]"] = {}
        self._DISK_ERROR_WINDOW_SECS = 86400  # 24h
        # Tiers calibrated for homelab/SMB Proxmox usage:
        #  * 0-10/24h  → transient noise (cable rattle, sleep/wake,
        #    PHY retrain). Silent observation only.
        #  * 11-100/24h → WARNING. Notify once per 24h.
        #  * 100+/24h   → CRITICAL. Active failure.
        # Hard errors (Buffer I/O, UNC, medium error, unrecovered read)
        # are CRITICAL on the FIRST occurrence regardless of count —
        # those are uncorrectable data losses, not transient noise.
        self._DISK_TIER_WARNING = 10
        self._DISK_TIER_CRITICAL = 100
        # Hard-error pattern: matches any of the kernel-reported
        # signals that mean data was lost or could not be recovered.
        self._DISK_HARD_ERR_RE = re.compile(
            r'(Buffer I/O error|UNC\b|Medium Error|medium error'
            r'|Unrecovered read error|unrecovered read error'
            r'|Sense Key.*Hardware Error)',
            re.IGNORECASE,
        )
        
        # Track when the last full backup job notification was sent
        # so we can suppress per-guest "Starting Backup of VM ..." noise
        self._last_backup_job_ts: float = 0
        self._BACKUP_JOB_SUPPRESS_WINDOW = 7200  # 2h: suppress per-guest during active job

        # NOTE: Service failure batching is handled universally by
        # BurstAggregator in NotificationManager (AGGREGATION_RULES).

    @property
    def _hostname(self) -> str:
        return _hostname()

    def start(self):
        """Start the journal watcher thread."""
        if self._running:
            return
        self._running = True
        self._load_disk_io_notified()  # Restore 24h dedup timestamps from DB
        self._thread = threading.Thread(target=self._watch_loop, daemon=True,
                                        name='journal-watcher')
        self._thread.start()
    
    def _load_disk_io_notified(self):
        """Load disk I/O notification timestamps from DB to survive restarts."""
        try:
            db_path = Path('/usr/local/share/proxmenux/health_monitor.db')
            if not db_path.exists():
                return
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            # Ensure table exists. The schema must match the canonical version
            # in health_persistence.py — 3 cols, INTEGER timestamp + count.
            # Previously this CREATE used `REAL NOT NULL` and 2 cols, racing
            # against notification_manager queries that did `count + 1`.
            # Audit Tier 6 (Notification stack #3 — schema race).
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notification_last_sent (
                    fingerprint TEXT PRIMARY KEY,
                    last_sent_ts INTEGER NOT NULL,
                    count INTEGER DEFAULT 1
                )
            ''')
            conn.commit()
            cursor.execute(
                "SELECT fingerprint, last_sent_ts FROM notification_last_sent "
                "WHERE fingerprint LIKE 'diskio_%' OR fingerprint LIKE 'fs_%'"
            )
            now = time.time()
            for fp, ts in cursor.fetchall():
                # Only load if within the 24h window (don't load stale entries)
                if now - ts < self._DISK_IO_COOLDOWN:
                    self._disk_io_notified[fp] = ts
            conn.close()
        except Exception as e:
            print(f"[JournalWatcher] Failed to load disk_io_notified: {e}")
    
    def _save_disk_io_notified(self, key: str, ts: float):
        """Persist a disk I/O notification timestamp to DB."""
        try:
            db_path = Path('/usr/local/share/proxmenux/health_monitor.db')
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            # Same canonical schema as health_persistence.py / notification_manager.py.
            # Audit Tier 6 (Notification stack #3 — schema race).
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notification_last_sent (
                    fingerprint TEXT PRIMARY KEY,
                    last_sent_ts INTEGER NOT NULL,
                    count INTEGER DEFAULT 1
                )
            ''')
            cursor.execute(
                "INSERT OR REPLACE INTO notification_last_sent (fingerprint, last_sent_ts) VALUES (?, ?)",
                (key, int(ts))
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[JournalWatcher] Failed to save disk_io_notified: {e}")
    
    def _get_disk_io_cooldown_from_db(self, device: str) -> Optional[float]:
        """
        Get disk I/O cooldown timestamp from DB for a device.
        
        Used to re-check DB when user might have dismissed the error,
        which clears the DB entry via health_persistence._clear_disk_io_cooldown().
        
        Returns the timestamp if found and within 24h window, None otherwise.
        """
        try:
            db_path = Path('/usr/local/share/proxmenux/health_monitor.db')
            if not db_path.exists():
                return None
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.execute('PRAGMA busy_timeout=3000')
            cursor = conn.cursor()
            
            # Check for the device with various prefixes
            # JournalWatcher uses direct device names as keys
            cursor.execute(
                "SELECT last_sent_ts FROM notification_last_sent WHERE fingerprint = ?",
                (device,)
            )
            row = cursor.fetchone()
            conn.close()
            
            if row:
                ts = float(row[0])
                # Only return if within 24h window
                if time.time() - ts < self._DISK_IO_COOLDOWN:
                    return ts
            return None
        except Exception:
            return None
    
    def stop(self):
        """Stop the journal watcher."""
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
    
    def _watch_loop(self):
        """Main watch loop with auto-restart on failure."""
        while self._running:
            try:
                self._run_journalctl()
            except Exception as e:
                print(f"[JournalWatcher] Error: {e}")
            if self._running:
                time.sleep(5)  # Wait before restart
    
    def _run_journalctl(self):
        """Run journalctl -f and process output line by line."""
        # Persist the cursor across watcher restarts so we don't lose events
        # in the 5s gap between subprocess crash and respawn. journalctl
        # writes the file with the latest seen cursor and on next start
        # resumes from there. Falls back to -n 0 (start from now) only on
        # the very first run when the cursor file doesn't exist yet.
        cursor_file = '/usr/local/share/proxmenux/journal_cursor.txt'
        try:
            Path(cursor_file).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cmd = ['journalctl', '-f', '-o', 'json', '--no-pager',
               f'--cursor-file={cursor_file}']
        if not Path(cursor_file).exists():
            cmd.extend(['-n', '0'])  # First run: don't replay history

        self._process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1
        )
        
        for line in self._process.stdout:
            if not self._running:
                break
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                self._process_entry(entry)
            except (json.JSONDecodeError, KeyError):
                # Try plain text matching as fallback
                self._process_plain(line)
        
        if self._process:
            self._process.wait()
    
    def _process_entry(self, entry: Dict):
        """Process a parsed journald JSON entry."""
        msg = entry.get('MESSAGE', '')
        if not msg or not isinstance(msg, str):
            return
        
        unit = entry.get('_SYSTEMD_UNIT', '')
        syslog_id = entry.get('SYSLOG_IDENTIFIER', '')
        priority = int(entry.get('PRIORITY', 6))
        
        self._check_auth_failure(msg, syslog_id, entry)
        self._check_fail2ban(msg, syslog_id)
        self._check_kernel_critical(msg, syslog_id, priority)
        self._check_service_failure(msg, unit)
        self._check_disk_io(msg, syslog_id, priority)
        self._check_cluster_events(msg, syslog_id)
        self._check_system_shutdown(msg, syslog_id)
        self._check_permission_change(msg, syslog_id)
        self._check_firewall(msg, syslog_id)
        self._check_backup_start(msg, syslog_id)
    
    def _process_plain(self, line: str):
        """Fallback: process a plain text log line."""
        self._check_auth_failure(line, '', {})
        self._check_fail2ban(line, '')
        self._check_kernel_critical(line, '', 6)
        self._check_cluster_events(line, '')
        self._check_system_shutdown(line, '')
    
    # ── Detection methods ──
    
    def _check_auth_failure(self, msg: str, syslog_id: str, entry: Dict):
        """Detect authentication failures (SSH, PAM, PVE)."""
        patterns = [
            (r'Failed password for (?:invalid user )?(\S+) from (\S+)', 'ssh'),
            (r'authentication failure.*rhost=(\S+).*user=(\S+)', 'pam'),
            (r'pvedaemon\[.*authentication failure.*rhost=(\S+)', 'pve'),
        ]
        
        for pattern, service in patterns:
            match = re.search(pattern, msg, re.IGNORECASE)
            if match:
                groups = match.groups()
                if service == 'ssh':
                    username, source_ip = groups[0], groups[1]
                elif service == 'pam':
                    source_ip, username = groups[0], groups[1]
                else:
                    source_ip = groups[0]
                    username = 'unknown'
                self._emit('auth_fail', 'WARNING', {
                    'source_ip': source_ip,
                    'username': username,
                    'service': service,
                    'hostname': self._hostname,
                }, entity='user', entity_id=source_ip)
                return
    
    def _check_fail2ban(self, msg: str, syslog_id: str):
        """Detect Fail2Ban IP bans."""
        # Only process actual fail2ban action messages, not systemd service events
        if syslog_id not in ('fail2ban-server', 'fail2ban.actions', 'fail2ban'):
            if 'fail2ban' not in msg.lower():
                return
            # Skip systemd service lifecycle messages (start/stop/restart/reload)
            msg_lower = msg.lower()
            if any(x in msg_lower for x in ['service', 'started', 'stopped', 'starting', 
                                             'stopping', 'reloading', 'reloaded', 'unit',
                                             'deactivated', 'activated']):
                return
        
        # Ban detected - match only valid IPv4 or IPv6 addresses
        # IPv4: 192.168.1.100, IPv6: 2001:db8::1 or ::ffff:192.168.1.1
        ban_match = re.search(r'Ban\s+((?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F:]{2,})', msg)
        if ban_match:
            ip = ban_match.group(1)
            # Validate it's a real IP address format
            # IPv4: must have 4 octets separated by dots
            # IPv6: must contain at least one colon
            is_ipv4 = re.match(r'^(\d{1,3}\.){3}\d{1,3}$', ip)
            is_ipv6 = ':' in ip and re.match(r'^[0-9a-fA-F:]+$', ip)
            if not is_ipv4 and not is_ipv6:
                return  # Not a valid IP (e.g., "Service.", "Ban", etc.)
            
            jail_match = re.search(r'\[(\w+)\]', msg)
            jail = jail_match.group(1) if jail_match else 'unknown'
            
            self._emit('ip_block', 'INFO', {
                'source_ip': ip,
                'jail': jail,
                'failures': '',
                'hostname': self._hostname,
            }, entity='user', entity_id=ip)
    
    def _check_kernel_critical(self, msg: str, syslog_id: str, priority: int):
        """Detect kernel panics, OOM, segfaults, hardware errors."""
        # Only process messages from kernel or systemd (not app-level logs)
        if syslog_id and syslog_id not in ('kernel', 'systemd', 'systemd-coredump', ''):
            return
        
        # Filter out normal kernel messages that are NOT problems
        _KERNEL_NOISE = [
            r'vfio-pci\s+\S+:\s*reset',       # PCI passthrough resets (normal during VM start/stop)
            r'vfio-pci\s+\S+:\s*resetting',
            r'entered\s+(?:promiscuous|allmulticast)\s+mode',  # Network bridge ops
            r'entered\s+(?:blocking|forwarding|disabled)\s+state',  # Bridge STP
            r'tap\d+i\d+:',                     # TAP interface events
            r'vmbr\d+:.*port\s+\d+',            # Bridge port events
        ]
        for noise in _KERNEL_NOISE:
            if re.search(noise, msg, re.IGNORECASE):
                return
        
        # NOTE: Disk I/O errors (ATA, SCSI, blk_update_request) are NOT handled
        # here. They are detected exclusively by HealthMonitor._check_disks_optimized
        # which records to health_persistence -> PollingCollector -> notification.
        # This avoids duplicate notifications and ensures the health dashboard
        # stays in sync with notifications.
        # Filesystem errors (EXT4/BTRFS/XFS/ZFS) ARE handled here because they
        # indicate corruption, not just hardware I/O problems.
        
        critical_patterns = {
            r'kernel panic':       ('system_problem', 'CRITICAL', 'Kernel panic'),
            r'Out of memory':      ('system_problem', 'CRITICAL', 'Out of memory killer activated'),
            r'segfault':           ('system_problem', 'WARNING',  'Segmentation fault detected'),
            r'BUG:':               ('system_problem', 'CRITICAL', 'Kernel BUG detected'),
            r'Call Trace:':        ('system_problem', 'WARNING',  'Kernel call trace'),
            r'EXT4-fs error':      ('system_problem', 'CRITICAL', 'Filesystem error'),
            r'BTRFS error':        ('system_problem', 'CRITICAL', 'Filesystem error'),
            r'XFS.*error':         ('system_problem', 'CRITICAL', 'Filesystem error'),
            r'ZFS.*error':         ('system_problem', 'CRITICAL', 'ZFS pool error'),
            r'mce:.*Hardware Error': ('system_problem', 'CRITICAL', 'Hardware error (MCE)'),
        }
        
        for pattern, (event_type, severity, reason) in critical_patterns.items():
            if re.search(pattern, msg, re.IGNORECASE):
                entity = 'node'
                entity_id = ''
                
                # Build a context-rich reason from the journal message.
                enriched = reason
                
                if 'segfault' in pattern:
                    m = re.search(r'(\S+)\[(\d+)\].*segfault', msg)
                    proc_name = m.group(1) if m else ''
                    proc_pid = m.group(2) if m else ''
                    lib_match = re.search(r'\bin\s+(\S+)', msg)
                    lib_name = lib_match.group(1) if lib_match else ''

                    # Dedup by library + offset (deterministic across processes)
                    # rather than by process name. The same root cause crashes
                    # different binaries that load the affected shared lib
                    # (apt-get, pveversion, dpkg, ...) — keying on proc_name
                    # produced 1 cooldown per process and the BurstAggregator
                    # only suppressed within its 90s window, so each new
                    # process fired a fresh single. Falls back to proc_name if
                    # the library/offset can't be parsed.
                    lib_offset_m = re.search(r'\sin\s+([^\s\[]+)\[([0-9a-f]+),', msg)
                    if lib_offset_m:
                        lib_basename = lib_offset_m.group(1)
                        lib_offset = lib_offset_m.group(2)
                        entity_id = f'segfault_{lib_basename}_{lib_offset}'
                    elif proc_name:
                        entity_id = f'segfault_{proc_name}'

                    parts = [reason]
                    if proc_name:
                        parts.append(f"Process: {proc_name}" + (f" (PID {proc_pid})" if proc_pid else ''))
                    if lib_name:
                        parts.append(f"Module: {lib_name}")
                    enriched = '\n'.join(parts)
                
                elif 'Out of memory' in pattern:
                    m = re.search(r'Killed process\s+(\d+)\s+\(([^)]+)\)', msg)
                    if m:
                        enriched = f"{reason}\nKilled: {m.group(2)} (PID {m.group(1)})"
                        entity_id = f'oom_{m.group(2)}'  # Dedup by killed process
                    else:
                        enriched = f"{reason}\n{msg[:300]}"
                
                elif re.search(r'EXT4-fs error|BTRFS error|XFS.*error|ZFS.*error', msg, re.IGNORECASE):
                    # Filesystem errors: extract device, function and human-readable explanation
                    fs_type = 'EXT4'
                    for fs in ['EXT4', 'BTRFS', 'XFS', 'ZFS']:
                        if fs.lower() in msg.lower():
                            fs_type = fs
                            break
                    
                    dev_match = re.search(r'device\s+(\S+?)\)?:', msg)
                    device = dev_match.group(1).rstrip(')') if dev_match else 'unknown'
                    
                    # Dedup by device: all FS errors on sdb1 share ONE notification
                    entity = 'disk'
                    entity_id = f'fs_{device}'
                    
                    # ── Get disk serial for USB-aware cooldown ──
                    # USB disks can change device names (sda->sdb) on reconnect.
                    # Using serial as cooldown key ensures same physical disk
                    # shares one 24h cooldown regardless of device letter.
                    import os as _os
                    base_dev = re.sub(r'\d+$', '', device) if device != 'unknown' else ''
                    disk_serial = ''
                    is_usb_disk = False
                    if base_dev:
                        try:
                            # Check if USB via sysfs
                            sysfs_link = subprocess.run(
                                ['readlink', '-f', f'/sys/block/{base_dev}'],
                                capture_output=True, text=True, timeout=2
                            )
                            is_usb_disk = 'usb' in sysfs_link.stdout.lower()
                            
                            # Get serial from smartctl
                            smart_result = subprocess.run(
                                ['smartctl', '-i', '-j', f'/dev/{base_dev}'],
                                capture_output=True, text=True, timeout=5
                            )
                            if smart_result.returncode in (0, 4):
                                import json
                                smart_data = json.loads(smart_result.stdout)
                                disk_serial = smart_data.get('serial_number', '')
                        except Exception:
                            pass
                    
                    # ── 24h dedup for filesystem errors ──
                    # Use serial for USB disks, device name for others
                    now_fs = time.time()
                    if is_usb_disk and disk_serial:
                        fs_dedup_key = f'fs_serial_{disk_serial}'
                    else:
                        fs_dedup_key = f'fs_{device}'
                    last_fs_notified = self._disk_io_notified.get(fs_dedup_key, 0)
                    if now_fs - last_fs_notified < self._DISK_IO_COOLDOWN:
                        # In-memory says cooldown active. Re-check DB in case
                        # user dismissed the error (which clears DB cooldowns).
                        db_ts = self._get_disk_io_cooldown_from_db(fs_dedup_key)
                        if db_ts is not None and now_fs - db_ts < self._DISK_IO_COOLDOWN:
                            return  # DB confirms cooldown is still active
                        # DB says cooldown was cleared - proceed
                        if fs_dedup_key in self._disk_io_notified:
                            del self._disk_io_notified[fs_dedup_key]
                    
                    # ── Device existence gating ──
                    device_exists = base_dev and _os.path.exists(f'/dev/{base_dev}')
                    
                    if not device_exists and device != 'unknown':
                        # Device not present -- silently ignore (disconnected USB, etc.)
                        return
                    
                    # Cross-reference SMART before deciding severity
                    smart_health = self._quick_smart_health(base_dev) if base_dev else 'UNKNOWN'
                    
                    if smart_health == 'PASSED':
                        # SMART healthy -- transient FS error, don't alarm
                        severity = 'INFO'
                    elif smart_health == 'FAILED':
                        severity = 'CRITICAL'
                    else:
                        # UNKNOWN -- can't verify, be conservative
                        severity = 'WARNING'
                    
                    # Mark dedup timestamp now that we'll send (persist to DB)
                    self._disk_io_notified[fs_dedup_key] = now_fs
                    self._save_disk_io_notified(fs_dedup_key, now_fs)
                    
                    # Identify what this device is (model, type, mountpoint)
                    device_info = self._identify_block_device(device)
                    
                    func_match = re.search(r':\s+(\w+:\d+):', msg)
                    func_info = func_match.group(1) if func_match else ''
                    
                    inode_match = re.search(r'inode\s+#?(\d+)', msg)
                    inode = inode_match.group(1) if inode_match else ''
                    
                    parts = [f'{fs_type} filesystem error on /dev/{device}']
                    if device_info:
                        parts.append(f'Device: {device_info}')
                    else:
                        parts.append(f'Device: /dev/{device}')
                    parts.append(f'SMART status: {smart_health}')
                    if func_info:
                        parts.append(f'Error: {self._translate_fs_function(func_info)}')
                    if inode:
                        inode_hint = 'root directory' if inode == '2' else f'inode #{inode}'
                        parts.append(f'Affected: {inode_hint}')
                    # Note: Specific recommendations are provided by AI when AI Suggestions is enabled
                    # Only include SMART status note (not an action)
                    if smart_health == 'PASSED':
                        parts.append(f'Note: SMART reports disk is healthy. This may be a transient error.')
                    enriched = '\n'.join(parts)
                
                else:
                    # Generic: include the raw journal message for context
                    enriched = f"{reason}\n{msg[:300]}"
                
                data = {'reason': enriched, 'hostname': self._hostname}
                
                self._emit(event_type, severity, data, entity=entity, entity_id=entity_id)
                return
    
    def _identify_block_device(self, device: str) -> str:
        """
        Identify a block device by querying lsblk.
        Returns a human-readable string like:
          "KINGSTON SA400S37960G (SSD, 894.3G) mounted at /mnt/data"
          "ST8000VN004-3CP101 (HDD, 7.3T) -- not mounted"
        Returns empty string if the device is not found.
        """
        if not device or device == 'unknown':
            return ''
        try:
            # Try the device as-is first, then the base disk (sdb1 -> sdb)
            candidates = [device]
            base = re.sub(r'\d+$', '', device) if not ('nvme' in device or 'mmcblk' in device) else device
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
                    tran = (fields[3] if len(fields) > 3 else '').upper()  # sata, usb, nvme
                    mountpoint = fields[4] if len(fields) > 4 and fields[4] else ''
                    rota = fields[5].strip() if len(fields) > 5 else '1'
                    
                    # Determine disk type
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
                        # Check partition mountpoint
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
    
    @staticmethod
    def _translate_fs_function(func_info: str) -> str:
        """Translate EXT4/filesystem function names to plain language."""
        func_name = func_info.split(':')[0] if ':' in func_info else func_info
        translations = {
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
        desc = translations.get(func_name, func_name)
        return desc
    
    def _check_service_failure(self, msg: str, unit: str):
        """Detect critical service failures with enriched context."""
        # Filter out noise -- these are normal systemd transient units,
        # not real service failures worth alerting about.
        _NOISE_PATTERNS = [
            r'session-\d+\.scope',          # SSH/login sessions
            r'user@\d+\.service',           # Per-user service managers
            r'user-runtime-dir@\d+',        # User runtime dirs
            r'systemd-coredump@',           # Coredump handlers (transient)
            r'run-.*\.mount',               # Transient mounts
            r'proxmenux-monitor',           # Self-referential: monitor can't alert about itself
        ]
        for noise in _NOISE_PATTERNS:
            if re.search(noise, msg) or re.search(noise, unit):
                return
        
        service_patterns = [
            r'Failed to start (.+)',
            r'Unit (\S+) (?:entered failed state|failed)',
            r'(\S+)\.service: (?:Main process exited|Failed with result)',
        ]
        
        for pattern in service_patterns:
            match = re.search(pattern, msg)
            if match:
                service_name = match.group(1)
                display_name = service_name
                
                # Enrich PVE VM/CT services with guest name and context
                pve_match = re.match(
                    r'(pve-container|qemu-server)@(\d+)', service_name)
                if pve_match:
                    svc_type = pve_match.group(1)
                    vmid = pve_match.group(2)
                    vm_name = self._resolve_vm_name(vmid)
                    guest_type = 'CT' if svc_type == 'pve-container' else 'VM'
                    display_name = f"{guest_type} {vm_name} ({vmid})" if vm_name else f"{guest_type} {vmid}"
                
                # Emit directly -- the BurstAggregator in NotificationManager
                # will automatically batch multiple service failures that
                # arrive within the aggregation window (90s).
                self._emit('service_fail', 'WARNING', {
                    'service_name': display_name,
                    'reason': msg[:300],
                    'hostname': self._hostname,
                }, entity='node', entity_id=service_name)
                return
    
    def _resolve_vm_name(self, vmid: str) -> str:
        """Try to resolve VMID to a guest name from PVE config files."""
        if not vmid:
            return ''
        # Check QEMU configs
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
    
    def _check_disk_io(self, msg: str, syslog_id: str, priority: int):
        """
        Detect disk I/O errors from kernel messages.
        
        ONLY notifies if ALL conditions are met:
        1. SMART reports FAILED for the affected disk.
        2. The same disk was NOT already notified in the last 24 h.
        
        If SMART is PASSED or UNKNOWN (cannot verify), the error is
        silently ignored -- transient ATA/SCSI bus noise is extremely
        common and does not indicate disk failure.
        """
        if syslog_id != 'kernel' and priority > 3:
            return
        
        io_patterns = [
            r'blk_update_request: I/O error.*dev (\S+)',
            r'Buffer I/O error on device (\S+)',
            r'SCSI error.*sd(\w)',
            r'(ata\d+)[\.\d]*:.*error',
        ]
        
        for pattern in io_patterns:
            match = re.search(pattern, msg)
            if not match:
                continue
            
            raw_device = match.group(1) if match.lastindex else 'unknown'
            
            # Resolve ATA port to physical disk name
            if raw_device.startswith('ata'):
                resolved = self._resolve_ata_to_disk(raw_device)
            else:
                resolved = re.sub(r'\d+$', '', raw_device) if raw_device.startswith('sd') else raw_device
            
            # ── ALWAYS persist the observation, regardless of severity ──
            # The disk_observation_contract is explicit (memory note
            # disk-observation-contract): every kernel-surfaced disk
            # error must be recorded in disk_observations. The modal
            # histogram is the per-disk audit trail; it must reflect
            # everything the kernel saw, even noise.
            self._record_disk_io_observation(resolved, msg)

            # ── Update sliding 24h rate window for this disk ──
            now = time.time()
            from collections import deque as _deque
            window = self._disk_error_window.setdefault(resolved, _deque())
            window.append(now)
            cutoff = now - self._DISK_ERROR_WINDOW_SECS
            while window and window[0] < cutoff:
                window.popleft()
            rate_24h = len(window)

            # ── Decide severity tier ──
            #   * hard error (UNC, Buffer I/O, medium, unrecovered read)
            #       → CRITICAL on first occurrence, no count threshold.
            #       These are uncorrectable: data is gone.
            #   * SMART self-report FAILED → CRITICAL (firmware admits it).
            #   * rate_24h > _DISK_TIER_CRITICAL → CRITICAL (active failure
            #       even if SMART still says PASSED).
            #   * rate_24h > _DISK_TIER_WARNING → WARNING (suspicious,
            #       worth a heads-up).
            #   * Otherwise → silent observation only (transient noise).
            is_hard_error = bool(self._DISK_HARD_ERR_RE.search(msg))
            smart_health = self._quick_smart_health(resolved)
            if is_hard_error or smart_health == 'FAILED' or rate_24h > self._DISK_TIER_CRITICAL:
                tier = 'critical'
            elif rate_24h > self._DISK_TIER_WARNING:
                tier = 'warning'
            else:
                # Silent — observation already saved, that's enough.
                return

            # ── 24h anti-cascade per (device, tier) ──
            # Independent cooldown per tier so a disk that fires WARNING
            # at noon can still escalate to CRITICAL the same day when
            # the rate jumps past _DISK_TIER_CRITICAL — they're
            # different keys.
            cooldown_key = f'{resolved}:{tier}'
            last_notified = self._disk_io_notified.get(cooldown_key, 0)
            if now - last_notified < self._DISK_IO_COOLDOWN:
                # In-memory says cooldown active. Re-verify in DB in
                # case the user dismissed (which clears the DB entry).
                db_ts = self._get_disk_io_cooldown_from_db(cooldown_key)
                if db_ts is not None and now - db_ts < self._DISK_IO_COOLDOWN:
                    return
                # Dismissed → DB cleared → proceed to notify and refresh state.
                del self._disk_io_notified[cooldown_key]

            self._disk_io_notified[cooldown_key] = now
            self._save_disk_io_notified(cooldown_key, now)

            # ── Build enriched notification ──
            device_info = self._identify_block_device(resolved)

            parts = []
            if tier == 'critical':
                if is_hard_error:
                    parts.append(f'Disk /dev/{resolved}: UNRECOVERABLE error detected')
                elif smart_health == 'FAILED':
                    parts.append(f'Disk /dev/{resolved}: SMART reports FAILED')
                else:
                    parts.append(
                        f'Disk /dev/{resolved}: high I/O error rate '
                        f'({rate_24h} errors in last 24h)'
                    )
            else:  # warning
                parts.append(
                    f'Disk /dev/{resolved}: elevated I/O error rate '
                    f'({rate_24h} errors in last 24h)'
                )

            parts.append(f'SMART status: {smart_health}')

            if device_info:
                parts.append(f'Device: {device_info}')
            else:
                parts.append(f'Device: /dev/{resolved}')

            # Translate the raw kernel error code
            detail = self._translate_ata_error(msg)
            if detail:
                parts.append(f'Error detail: {detail}')

            if tier == 'critical':
                parts.append(f'Action: Replace disk /dev/{resolved} as soon as possible.')
            else:
                parts.append(
                    f'Action: Monitor /dev/{resolved} closely. '
                    f'Plan a backup verification and replacement if rate grows.'
                )
            parts.append(f'  Check details: smartctl -a /dev/{resolved}')

            enriched = '\n'.join(parts)
            dev_display = f'/dev/{resolved}'

            # Capture journal context for AI enrichment.
            # `raw_device` is the original ATA-port literal extracted by the regex
            # (e.g. "ata8"). The previous code used a name `ata_port` that was
            # never defined in this scope — every disk I/O event hit a NameError
            # that the JournalWatcher silently swallowed, suppressing critical
            # disk failure alerts. Audit Tier 6 (Notification stack #1).
            journal_ctx = capture_journal_context(
                keywords=[resolved, raw_device, 'I/O error', 'exception', 'SMART'],
                lines=30
            )

            severity = 'CRITICAL' if tier == 'critical' else 'WARNING'
            self._emit('disk_io_error', severity, {
                'device': dev_display,
                'reason': enriched,
                'hostname': self._hostname,
                'smart_status': smart_health,
                'rate_24h': rate_24h,
                'tier': tier,
                '_journal_context': journal_ctx,
            }, entity='disk', entity_id=resolved)
            return
    
    def _resolve_ata_to_disk(self, ata_port: str) -> str:
        """Resolve an ATA port name (ata8) to a physical disk name (sda)."""
        try:
            port_num = re.search(r'ata(\d+)', ata_port)
            if not port_num:
                return ata_port
            num = port_num.group(1)
            # Check /sys/class/ata_port for the mapping
            import glob as _glob
            for path in _glob.glob(f'/sys/class/ata_port/ata{num}/../../host*/target*/*/block/*'):
                disk_name = os.path.basename(path)
                if disk_name.startswith('sd') or disk_name.startswith('nvme'):
                    return disk_name
            # Fallback: try scsi_host mapping
            for path in _glob.glob(f'/sys/class/ata_port/ata{num}/../../host*/scsi_host/host*/../../target*/*/block/*'):
                disk_name = os.path.basename(path)
                if disk_name.startswith('sd'):
                    return disk_name
            return ata_port
        except Exception:
            return ata_port
    
    def _quick_smart_health(self, disk_name: str) -> str:
        """Quick SMART health check. Returns 'PASSED', 'FAILED', or 'UNKNOWN'."""
        if not disk_name or disk_name.startswith('ata') or disk_name.startswith('zram'):
            return 'UNKNOWN'
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
                return 'PASSED'
            elif passed is False:
                return 'FAILED'
            return 'UNKNOWN'
        except Exception:
            return 'UNKNOWN'
    
    def _record_disk_io_observation(self, resolved: str, msg: str):
        """Persist a kernel-journal I/O error as a disk observation.

        Signature classification mirrors HealthMonitor._make_io_obs_signature
        so observations from the real-time journal watcher and the periodic
        dmesg scan dedup into the same row (via the UPSERT on
        disk_registry_id + error_type + error_signature).
        """
        try:
            from health_persistence import health_persistence

            m = msg.lower()
            if re.search(r'exception\s+emask|emask\s+0x|revalidation failed|'
                         r'hard resetting link|serror.*badcrc|comreset|'
                         r'link is slow|status.*drdy', m):
                family = 'ata_connection_error'
            elif re.search(r'i/o error|blk_update_request|medium error|sense key', m):
                family = 'block_io_error'
            elif re.search(r'failed command|fpdma queued', m):
                family = 'ata_failed_command'
            else:
                family = 'generic'

            # Best-effort serial lookup so the observation survives device
            # renames (ata8 -> sdh, USB reconnects, etc.).
            serial = None
            try:
                sm = subprocess.run(
                    ['smartctl', '-i', f'/dev/{resolved}'],
                    capture_output=True, text=True, timeout=3)
                if sm.returncode in (0, 4):
                    for line in sm.stdout.split('\n'):
                        if 'Serial Number' in line or 'Serial number' in line:
                            serial = line.split(':')[-1].strip()
                            break
            except Exception:
                pass

            health_persistence.record_disk_observation(
                device_name=resolved,
                serial=serial,
                error_type='io_error',
                error_signature=f'io_{resolved}_{family}',
                raw_message=f'/dev/{resolved}: {msg.strip()[:200]}',
                severity='critical',
            )
        except Exception as e:
            print(f"[JournalWatcher] Error recording disk io observation: {e}")

    def _record_smartd_observation(self, title: str, message: str):
        """Instance wrapper around the module-level helper.

        See `_record_smartd_observation_impl` below — kept on the class for
        backward compatibility with `JournalWatcher` callers; `ProxmoxHookWatcher`
        also holds its own thin wrapper for the same reason. Audit Tier 6
        (Notification stack #2).
        """
        _record_smartd_observation_impl(title, message)

    @staticmethod
    def _translate_ata_error(msg: str) -> str:
        """Translate common ATA/SCSI error codes to human-readable descriptions."""
        error_codes = {
            'IDNF': 'sector address not found (possible bad sector or cable issue)',
            'UNC': 'uncorrectable read error (bad sector)',
            'ABRT': 'command aborted by drive',
            'AMNF': 'address mark not found (surface damage)',
            'TK0NF': 'track 0 not found (drive hardware failure)',
            'BBK': 'bad block detected',
            'ICRC': 'interface CRC error (cable or connector issue)',
            'MC': 'media changed',
            'MCR': 'media change requested',
            'WP': 'write protected',
        }
        
        parts = []
        for code, description in error_codes.items():
            if code in msg:
                parts.append(description)
        
        if parts:
            return '; '.join(parts)
        
        # Try to extract the Emask/SErr/action codes
        emask = re.search(r'Emask\s+(0x[0-9a-f]+)', msg)
        serr = re.search(r'SErr\s+(0x[0-9a-f]+)', msg)
        action = re.search(r'action\s+(0x[0-9a-f]+)', msg)
        
        if emask or serr:
            info = []
            if emask:
                info.append(f'Error mask: {emask.group(1)}')
            if serr:
                info.append(f'SATA error: {serr.group(1)}')
            if action and action.group(1) == '0x0':
                info.append('auto-recovered')
            return ', '.join(info)
        
        return ''
    
    def _check_backup_start(self, msg: str, syslog_id: str):
        """Detect backup job start from journal messages.
        
        The message "starting new backup job: vzdump ..." is unique and
        definitive -- only a real vzdump invocation produces it.  We match
        purely on message content, regardless of which service emitted it,
        because PVE uses different syslog identifiers depending on how the
        backup was triggered:
          - pvescheduler  (scheduled backups via /etc/pve/jobs.cfg)
          - pvedaemon     (GUI-triggered backups)
          - pvesh         (CLI / API-triggered backups)
          - vzdump        (per-guest "Starting Backup of VM ..." lines)
        
        Trying to maintain a whitelist of syslog_ids is fragile -- new PVE
        versions or plugins may introduce more.  The message pattern itself
        is the reliable indicator.
        """
        
        # Primary pattern: full vzdump command with all arguments
        # Matches both "INFO: starting new backup job: vzdump ..." and
        #               "starting new backup job: vzdump ..."
        match = re.match(r'(?:INFO:\s*)?starting new backup job:\s*vzdump\s+(.*)', msg, re.IGNORECASE)
        
        # Fallback: vzdump also emits per-guest messages like:
        #   "INFO: Starting Backup of VM 104 (lxc)"
        # These fire for EACH guest when a multi-guest vzdump job runs.
        # We SUPPRESS these when a full backup job was recently notified
        # (within 2h window) to avoid spamming one notification per guest.
        # Only use fallback for standalone single-VM backups (manual, no job).
        fallback_guest = None
        if not match:
            fb = re.match(r'(?:INFO:\s*)?Starting Backup of VM (\d+)\s+\((lxc|qemu)\)', msg)
            if fb:
                # If a full job notification was sent recently, suppress per-guest noise
                now = time.time()
                if now - self._last_backup_job_ts < self._BACKUP_JOB_SUPPRESS_WINDOW:
                    return  # Part of an active job -- already notified
                # Restart-tolerant fallback: if the in-memory timestamp was
                # cleared (Monitor restarted mid-job) but PVE still has an
                # active vzdump UPID, this per-guest line is part of that
                # job — drop it instead of emitting a wrong "Backup started
                # on local" with storage default. Reported by JC Miñarro 18/05
                # after a Monitor redeploy during an active PBS backup.
                if is_vzdump_active_on_host():
                    return
                fallback_guest = fb.group(1)
            else:
                return
        
        guests = []
        storage = ''
        mode = ''
        compress = ''
        
        if match:
            raw_args = match.group(1)
            args = raw_args.split()
            i = 0
            while i < len(args):
                arg = args[i]
                if arg.isdigit():
                    guests.append(arg)
                elif arg == '--storage' and i + 1 < len(args):
                    storage = args[i + 1]
                    i += 1
                elif arg == '--mode' and i + 1 < len(args):
                    mode = args[i + 1]
                    i += 1
                elif arg == '--compress' and i + 1 < len(args):
                    compress = args[i + 1]
                    i += 1
                elif arg == '--all' and i + 1 < len(args):
                    if args[i + 1] == '1':
                        guests = ['all']
                    i += 1
                i += 1
        elif fallback_guest:
            guests = [fallback_guest]
        
        # Build the notification body
        reason_parts = []
        
        if guests:
            if guests == ['all']:
                reason_parts.append('VM/CT: All')
            else:
                guest_lines = []
                for gid in guests:
                    # Skip non-guest IDs (0, 1 are not real guests)
                    if gid in ('0', '1'):
                        continue
                    info = self._resolve_vm_info(gid)
                    if info:
                        gname, gtype = info
                        guest_lines.append(f'  {gtype} {gname} ({gid})')
                    else:
                        guest_lines.append(f'  ID {gid}')
                if guest_lines:
                    reason_parts.append('VM/CT:\n' + '\n'.join(guest_lines))
        
        details = []
        if storage:
            details.append(f'\U0001F5C4\uFE0F Storage: {storage}')
        if mode:
            details.append(f'\u2699\uFE0F Mode: {mode}')
        if details:
            reason_parts.append('  |  '.join(details))
        
        reason = '\n'.join(reason_parts) if reason_parts else 'Backup job started'
        
        # Use a stable entity_id that includes the guest list so that
        # different backup jobs produce distinct fingerprints and don't
        # dedup each other, while the SAME job doesn't fire twice.
        guest_key = '_'.join(sorted(guests)) if guests else 'unknown'
        
        # If this was a full job (primary pattern), record timestamp to
        # suppress subsequent per-guest "Starting Backup of VM" messages
        if match:
            self._last_backup_job_ts = time.time()
        
        self._emit('backup_start', 'INFO', {
            'vmid': ', '.join(guests),
            'vmname': '',
            'hostname': self._hostname,
            'user': '',
            'reason': reason,
            'storage': storage or 'local',
        }, entity='backup', entity_id=f'vzdump_{guest_key}')
    
    def _resolve_vm_name(self, vmid: str) -> str:
        """Try to resolve a VMID to its name from PVE config files."""
        info = self._resolve_vm_info(vmid)
        return info[0] if info else ''

    def _resolve_vm_info(self, vmid: str):
        """Resolve a VMID to (name, type) from PVE config files.
        
        Returns tuple (name, 'VM'|'CT') or None if not found.
        type is determined by which config directory the ID was found in:
          /etc/pve/qemu-server -> VM
          /etc/pve/lxc         -> CT
        """
        if not vmid or not vmid.isdigit():
            return None
        type_map = [
            ('/etc/pve/qemu-server', 'VM'),
            ('/etc/pve/lxc', 'CT'),
        ]
        for base, gtype in type_map:
            conf = f'{base}/{vmid}.conf'
            try:
                with open(conf, 'r') as f:
                    for line in f:
                        if line.startswith('name:') or line.startswith('hostname:'):
                            return (line.split(':', 1)[1].strip(), gtype)
            except (OSError, IOError):
                pass
        return None
    
    def _check_cluster_events(self, msg: str, syslog_id: str):
        """Detect cluster split-brain and node disconnect."""
        msg_lower = msg.lower()
        
        # Split-brain
        if any(p in msg_lower for p in ['split-brain', 'split brain',
                                          'fencing required', 'cluster partition']):
            quorum = 'unknown'
            if 'quorum' in msg_lower:
                quorum = 'lost' if 'lost' in msg_lower else 'valid'
            
            self._emit('split_brain', 'CRITICAL', {
                'quorum': quorum,
                'reason': msg[:200],
                'hostname': self._hostname,
            }, entity='cluster', entity_id=self._hostname)
            return
        
        # Node disconnect
        if (('quorum' in msg_lower and 'lost' in msg_lower) or
            ('node' in msg_lower and any(w in msg_lower for w in ['left', 'offline', 'lost']))):
            
            node_match = re.search(r'[Nn]ode\s+(\S+)', msg)
            node_name = node_match.group(1) if node_match else 'unknown'
            
            self._emit('node_disconnect', 'CRITICAL', {
                'node_name': node_name,
                'hostname': self._hostname,
            }, entity='cluster', entity_id=node_name)
    
    def _check_system_shutdown(self, msg: str, syslog_id: str):
        """Detect full-node shutdown or reboot.
        
        ONLY matches definitive signals from PID 1 (systemd) that prove
        the entire node is going down -- NOT individual service restarts.
        
        Severity is INFO, not CRITICAL, because:
        - A planned shutdown/reboot is an administrative action, not an emergency.
        - If the node truly crashes, the monitor dies before it can send anything.
        - Proxmox itself treats these as informational notifications.
        """
        # Strict syslog_id filter: only systemd PID 1 and systemd-logind
        # emit authoritative node-level shutdown messages.
        if syslog_id not in ('systemd', 'systemd-logind'):
            return
        
        msg_lower = msg.lower()
        
        is_reboot = False
        is_shutdown = False
        
        # Reboot signals -- only definitive whole-system messages
        reboot_signals = [
            'system is rebooting',
            'the system will reboot now',
        ]
        for sig in reboot_signals:
            if sig in msg_lower:
                is_reboot = True
                break
        
        # Shutdown/poweroff signals -- only definitive whole-system messages.
        # "shutting down" is deliberately EXCLUDED because many services emit
        # it during normal restarts (e.g. "Shutting down proxy server...").
        # "journal stopped" is EXCLUDED because journald can restart independently.
        if not is_reboot:
            shutdown_signals = [
                'system is powering off',
                'system is halting',
                'the system will power off now',
            ]
            for sig in shutdown_signals:
                if sig in msg_lower:
                    is_shutdown = True
                    break
        
        if is_reboot:
            # Mark shutdown state to suppress VM/CT stop events
            _shared_state.mark_shutdown()
            self._emit('system_reboot', 'INFO', {
                'reason': 'The system is rebooting.',
                'hostname': self._hostname,
            }, entity='node', entity_id='')
        elif is_shutdown:
            # Mark shutdown state to suppress VM/CT stop events
            _shared_state.mark_shutdown()
            self._emit('system_shutdown', 'INFO', {
                'reason': 'The system is shutting down.',
                'hostname': self._hostname,
            }, entity='node', entity_id='')
    
    def _check_permission_change(self, msg: str, syslog_id: str):
        """Detect user permission changes in PVE."""
        permission_patterns = [
            (r'set permissions.*user\s+(\S+)', 'Permission changed'),
            (r'user added to group.*?(\S+)', 'Added to group'),
            (r'user removed from group.*?(\S+)', 'Removed from group'),
            (r'ACL updated.*?(\S+)', 'ACL updated'),
            (r'Role assigned.*?(\S+)', 'Role assigned'),
        ]
        
        for pattern, action in permission_patterns:
            match = re.search(pattern, msg, re.IGNORECASE)
            if match:
                username = match.group(1)
                self._emit('user_permission_change', 'INFO', {
                    'username': username,
                    'change_details': action,
                    'hostname': self._hostname,
                }, entity='user', entity_id=username)
                return
    
    def _check_firewall(self, msg: str, syslog_id: str):
        """Detect firewall issues (not individual drops, but rule errors)."""
        if re.search(r'pve-firewall.*(?:error|failed|unable)', msg, re.IGNORECASE):
            self._emit('firewall_issue', 'WARNING', {
                'reason': msg[:200],
                'hostname': self._hostname,
            }, entity='network', entity_id='')
    
    # ── Emit helper ──
    
    def _emit(self, event_type: str, severity: str, data: Dict,
              entity: str = 'node', entity_id: str = ''):
        """Emit event to queue with short-term deduplication (30s window)."""
        event = NotificationEvent(
            event_type, severity, data, source='journal',
            entity=entity, entity_id=entity_id,
        )
        
        now = time.time()
        last = self._recent_events.get(event.fingerprint, 0)
        if now - last < self._dedup_window:
            return  # Skip duplicate within 30s window

        self._recent_events[event.fingerprint] = now

        # Cleanup old dedup entries periodically
        if len(self._recent_events) > 200:
            cutoff = now - self._dedup_window * 2
            self._recent_events = {
                k: v for k, v in self._recent_events.items() if v > cutoff
            }

        self._queue.put(event)


# ─── Task Watcher (Real-time) ────────────────────────────────────

class TaskWatcher:
    """Watches /var/log/pve/tasks/index for VM/CT and backup events.
    
    The PVE task index file is appended when tasks start/finish.
    Format: UPID:node:pid:pstart:starttime:type:id:user:
    Final status is recorded when task completes.
    """
    
    TASK_LOG = '/var/log/pve/tasks/index'
    TASK_DIR = '/var/log/pve/tasks'
    
    def _get_task_log_reason(self, upid: str, status: str) -> str:
        """Read the task log file to extract the actual error/warning reason.
        
        Returns a human-readable reason extracted from the task log,
        or falls back to the status code if log cannot be read.
        """
        try:
            # Parse UPID to find log file
            # UPID format: UPID:node:pid:pstart:starttime:type:id:user:
            # Example: UPID:pve:0000F234:0000B890:67890ABC:qmstart:100:root@pam:
            parts = upid.split(':')
            if len(parts) < 5:
                return status
            
            # Task logs are stored in /var/log/pve/tasks/X/UPID
            # where X is the LAST character of starttime hex (uppercase)
            # Example: starttime=69CE20CF -> subdirectory is "F"
            # The starttime field (parts[4]) is a hex timestamp
            starttime_hex = parts[4]
            if starttime_hex:
                # LAST character of hex starttime determines subdirectory
                subdir = starttime_hex[-1].upper()
                # The log filename is the full UPID INCLUDING the trailing colon
                # Proxmox names the file exactly as the UPID (with colon at end)
                log_path = os.path.join(self.TASK_DIR, subdir, upid)
                
                if os.path.exists(log_path):
                    with open(log_path, 'r', errors='replace') as f:
                        lines = f.readlines()
                    
                    # Look for error/warning messages in the log
                    # Proxmox uses various patterns: "WARN:", "warning:", "error:", etc.
                    error_lines = []
                    for line in lines:
                        line_strip = line.strip()
                        line_lower = line_strip.lower()
                        
                        # Skip empty lines and status lines at the end
                        if not line_strip or line_strip.startswith('TASK '):
                            continue
                        
                        # Capture warning/error lines with various patterns
                        # Proxmox uses: "WARN: ...", "warning: ...", "error: ...", "ERROR: ..."
                        is_warning_error = any(kw in line_lower for kw in [
                            'warn:', 'warning:', 'error:', 'failed', 'failure',
                            'unable to', 'cannot', 'exception', 'critical',
                            'certificate', 'expired', 'expires'  # EFI cert warnings
                        ])
                        
                        # Also check for lines starting with common prefixes
                        starts_with_prefix = any(line_strip.upper().startswith(p) for p in [
                            'WARN:', 'WARNING:', 'ERROR:', 'CRITICAL:', 'FATAL:'
                        ])
                        
                        if is_warning_error or starts_with_prefix:
                            if len(line_strip) < 300:  # Reasonable length
                                error_lines.append(line_strip)
                    
                    if error_lines:
                        # Return the most relevant lines (up to 5 for better context)
                        return '; '.join(error_lines[:5])
            
            return status
        except Exception as e:
            # Log error for debugging but return status as fallback
            return status
    
    # Map PVE task types to our event types
    TASK_MAP = {
        'qmstart':    ('vm_start',    'INFO'),
        'qmstop':     ('vm_stop',     'INFO'),
        'qmshutdown': ('vm_shutdown', 'INFO'),
        'qmreboot':   ('vm_restart',  'INFO'),
        'qmreset':    ('vm_restart',  'INFO'),
        'vzstart':    ('ct_start',    'INFO'),
        'vzstop':     ('ct_stop',     'INFO'),
        'vzshutdown': ('ct_shutdown', 'INFO'),
        'vzreboot':   ('ct_restart',  'INFO'),
        'vzdump':     ('backup_start', 'INFO'),
        'qmsnapshot': ('snapshot_complete', 'INFO'),
        'vzsnapshot': ('snapshot_complete', 'INFO'),
        'qmigrate':   ('migration_start', 'INFO'),
        'vzmigrate':  ('migration_start', 'INFO'),
    }
    
    def __init__(self, event_queue: Queue):
        self._queue = event_queue
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # `_hostname` is exposed as a @property below so every read returns
        # the *current* alias from the settings DB (TTL-cached for 5 s in
        # _hostname()). The old `__init__`-time cache made a fresh Display
        # Name require a service restart to take effect.
        self._last_position = 0
        # Cache for active vzdump detection
        self._vzdump_active_cache: float = 0  # timestamp of last positive check
        self._vzdump_cache_ttl = 5  # cache result for 5s
        # Internal tracking: when we see a vzdump task without an end status,
        # we mark the timestamp. When we see it complete (status=OK/ERROR),
        # we clear it. This supplements the /var/log/pve/tasks/active check
        # to avoid timing gaps.
        self._vzdump_running_since: float = 0  # 0 = no vzdump tracked
        self._vzdump_grace_period = 120  # seconds after vzdump ends to still suppress
        # Track active-file UPIDs we've already seen, to avoid duplicate backup_start
        self._seen_active_upids: set = set()

    @property
    def _hostname(self) -> str:
        return _hostname()

    def start(self):
        if self._running:
            return
        self._running = True

        # Start at end of file
        if os.path.exists(self.TASK_LOG):
            try:
                self._last_position = os.path.getsize(self.TASK_LOG)
            except OSError:
                self._last_position = 0
        
        # Pre-load active UPIDs so we don't fire backup_start for already-running jobs
        if os.path.exists(self.TASK_ACTIVE):
            try:
                with open(self.TASK_ACTIVE, 'r') as f:
                    for line in f:
                        upid = line.strip().split()[0] if line.strip() else ''
                        if upid:
                            self._seen_active_upids.add(upid)
            except Exception:
                pass
        
        self._thread = threading.Thread(target=self._watch_loop, daemon=True,
                                        name='task-watcher')
        self._thread.start()
    
    def stop(self):
        self._running = False
    
    def _is_vzdump_active(self) -> bool:
        """Check if a vzdump (backup) job is currently running or recently finished.
        
        Two-layer detection:
        1. Internal tracking: TaskWatcher marks vzdump start/end with a grace period
           (covers the case where the VM restart arrives milliseconds after vzdump ends)
        2. /var/log/pve/tasks/active: reads the active task file and verifies PID
        
        This combination eliminates timing gaps that caused false VM notifications.
        """
        now = time.time()
        
        # Layer 1: Internal tracking (most reliable, no file I/O)
        if self._vzdump_running_since > 0:
            elapsed = now - self._vzdump_running_since
            if elapsed < self._vzdump_grace_period:
                return True
            else:
                # Grace period expired -- clear the tracking
                self._vzdump_running_since = 0
        
        # Layer 2: /var/log/pve/tasks/active (catches vzdump started by other nodes or cron)
        # Negative cache: if we recently confirmed NO vzdump, skip the check
        if hasattr(self, '_vzdump_negative_cache') and \
           now - self._vzdump_negative_cache < self._vzdump_cache_ttl:
            return False
        # Positive cache
        if now - self._vzdump_active_cache < self._vzdump_cache_ttl:
            return True
        
        active_file = '/var/log/pve/tasks/active'
        try:
            with open(active_file, 'r') as f:
                for line in f:
                    # UPID format: UPID:node:pid:pstart:starttime:type:id:user:
                    if ':vzdump:' in line:
                        # Verify the PID is still alive
                        parts = line.strip().split(':')
                        if len(parts) >= 3:
                            try:
                                # PID in UPID is HEXADECIMAL
                                pid = int(parts[2], 16)
                                os.kill(pid, 0)  # Signal 0 = just check existence
                                self._vzdump_active_cache = now
                                return True
                            except (ValueError, ProcessLookupError, PermissionError):
                                pass  # PID not found or not a number -- stale entry
        except (OSError, IOError):
            pass
        
        self._vzdump_negative_cache = now
        return False
    
    TASK_ACTIVE = '/var/log/pve/tasks/active'
    
    def _watch_loop(self):
        """Poll task index for completions AND active file for new starts."""
        while self._running:
            try:
                # 1. Check index for completed tasks
                if os.path.exists(self.TASK_LOG):
                    current_size = os.path.getsize(self.TASK_LOG)
                    
                    if current_size < self._last_position:
                        # File was truncated/rotated
                        self._last_position = 0
                    
                    if current_size > self._last_position:
                        with open(self.TASK_LOG, 'r') as f:
                            f.seek(self._last_position)
                            new_lines = f.readlines()
                            self._last_position = f.tell()
                        
                        for line in new_lines:
                            self._process_task_line(line.strip())
                
                # 2. Check active file for newly started tasks (backup start)
                self._check_active_tasks()
                
            except Exception as e:
                print(f"[TaskWatcher] Error reading task log: {e}")
            
            time.sleep(5)  # Check every 5 seconds (reduced from 2s for efficiency)
    
    def _check_active_tasks(self):
        """Scan /var/log/pve/tasks/active to track vzdump for VM suppression.
        
        This does NOT emit backup_start notifications (the JournalWatcher
        handles that via the 'starting new backup job' log message, which
        contains the full guest list and parameters).
        
        This only keeps _vzdump_running_since updated so that
        _is_vzdump_active() can suppress VM start/stop notifications
        during backup operations.
        """
        if not os.path.exists(self.TASK_ACTIVE):
            return
        
        try:
            current_upids = set()
            found_vzdump = False
            with open(self.TASK_ACTIVE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if not parts:
                        continue
                    upid = parts[0]
                    current_upids.add(upid)

                    if ':vzdump:' not in upid:
                        continue

                    # PVE writes each line in tasks/active as:
                    #   "<UPID> 1"                                    ← task still running
                    #   "<UPID> 1 <endtime_hex> <STATUS>"             ← task already finished
                    # PVE doesn't always prune finished rows from this
                    # file (observed on RimegraVE 19/05: 25 OK/error
                    # entries lingering for hours after job end). Just
                    # matching ':vzdump:' kept `_vzdump_running_since`
                    # permanently fresh, which then made
                    # `_is_vzdump_active()` return True forever and
                    # silenced every vm_start / vm_stop / vm_shutdown
                    # via the _BACKUP_NOISE filter. Only treat the row
                    # as a live vzdump when no end-time / status has
                    # been written yet (≤ 2 fields: UPID + version).
                    if len(parts) <= 2:
                        found_vzdump = True

            # Keep _vzdump_running_since fresh as long as vzdump is in active
            if found_vzdump:
                self._vzdump_running_since = time.time()
            
            # Cleanup stale UPIDs
            stale = self._seen_active_upids - current_upids
            self._seen_active_upids -= stale
            # Track new ones
            self._seen_active_upids |= current_upids
            
        except Exception as e:
            print(f"[TaskWatcher] Error reading active tasks: {e}")
    
    def _process_task_line(self, line: str):
        """Process a single task index line.
        
        PVE task index format (space-separated):
        UPID endtime status
        Where UPID = UPID:node:pid:pstart:starttime:type:id:user:
        """
        if not line:
            return
        
        parts = line.split()
        if not parts:
            return
        
        upid = parts[0]
        # Status can be multi-word like "WARNINGS: 1" or "OK"
        # Format: UPID TIMESTAMP STATUS [...]
        # Join everything after timestamp as status
        status = ' '.join(parts[2:]) if len(parts) >= 3 else ''
        
        # Parse UPID
        upid_parts = upid.split(':')
        if len(upid_parts) < 8:
            return
        
        task_type = upid_parts[5]
        vmid = upid_parts[6]
        user = upid_parts[7]
        
        # Get VM/CT name
        vmname = self._get_vm_name(vmid) if vmid else ''
        
        # Map to event type
        event_info = self.TASK_MAP.get(task_type)
        if not event_info:
            return
        
        event_type, default_severity = event_info
        
        # Track vzdump (backup) tasks internally for VM suppression.
        # When a vzdump starts (no status yet), mark it.  When it completes
        # (status = OK or ERROR), keep a grace period for the post-backup
        # VM restart that follows shortly after.
        if task_type == 'vzdump':
            if not status:
                # Backup just started -- track it
                self._vzdump_running_since = time.time()
            else:
                # Backup just finished -- start grace period for VM restarts
                self._vzdump_running_since = time.time()  # will expire via grace_period
        
        # Check if task failed or completed with warnings
        # WARNINGS means the task completed but with non-fatal issues (e.g., EFI cert warnings)
        # The VM/CT DID start successfully, just with caveats
        # Status format can be "WARNINGS: N" where N is the count, so use startswith
        is_warning = status and status.upper().startswith('WARNINGS')
        is_error = status and status != 'OK' and not is_warning and status != ''
        
        if is_error:
            # Override to failure event - task actually failed
            if 'start' in event_type:
                event_type = event_type.replace('_start', '_fail')
            elif 'complete' in event_type:
                event_type = event_type.replace('_complete', '_fail')
            severity = 'CRITICAL'
        elif is_warning:
            # Task completed with warnings - VM/CT started but has issues
            # Use specific warning event types for better messaging
            if event_type == 'vm_start':
                event_type = 'vm_start_warning'
            elif event_type == 'ct_start':
                event_type = 'ct_start_warning'
            elif event_type == 'backup_start':
                event_type = 'backup_warning'  # Backup finished with warnings
            elif event_type == 'migration_start':
                event_type = 'migration_warning'  # Migration finished with warnings
            severity = 'WARNING'
        elif status == 'OK':
            # Task completed successfully
            if event_type == 'backup_start':
                event_type = 'backup_complete'
            elif event_type == 'migration_start':
                event_type = 'migration_complete'
            severity = 'INFO'
        else:
            # Task just started (no status yet)
            severity = default_severity
        
        # Get the actual reason from task log if error or warning
        if is_error or is_warning:
            reason = self._get_task_log_reason(upid, status)
        else:
            reason = ''
        
        data = {
            'vmid': vmid,
            'vmname': vmname or f'ID {vmid}',
            'hostname': self._hostname,
            'user': user,
            'reason': reason,
            'target_node': '',
            'size': '',
            'snapshot_name': '',
        }
        
        # Determine entity type from task type
        entity = 'ct' if task_type.startswith('vz') else 'vm'
        
        # Backup completion/failure and replication events are handled
        # EXCLUSIVELY by the PVE webhook, which delivers richer data (full
        # logs, sizes, durations, filenames).  TaskWatcher skips these to
        # avoid duplicates.
        # NOTE: backup_start and backup_warning are NOT in this set --
        # PVE's webhook only fires when backup FINISHES with OK or ERROR,
        # but WARNINGS come through TaskWatcher with richer context.
        _WEBHOOK_EXCLUSIVE = {'backup_complete', 'backup_fail',
                              'replication_complete', 'replication_fail'}
        if event_type in _WEBHOOK_EXCLUSIVE:
            return
        
        # Suppress VM/CT start/stop/shutdown while a vzdump is active.
        # These are backup-induced operations (mode=stop), not user actions.
        # Exception: if a VM/CT FAILS or has WARNINGS, that IS important.
        # We check BOTH our in-memory tracking (`_is_vzdump_active`) AND
        # `tasks/active` on disk (`is_vzdump_active_on_host`). The disk
        # check survives Monitor restarts mid-backup, which otherwise
        # cleared `_vzdump_running_since` and exposed the post-restart
        # shutdown notifications to the user (JC Miñarro 18/05).
        _BACKUP_NOISE = {'vm_start', 'vm_stop', 'vm_shutdown', 'vm_restart',
                         'ct_start', 'ct_stop', 'ct_shutdown', 'ct_restart'}
        if event_type in _BACKUP_NOISE and not is_error and not is_warning:
            if self._is_vzdump_active() or is_vzdump_active_on_host():
                return
        
        # Suppress VM/CT stop/shutdown during host shutdown/reboot.
        # When the host shuts down, all VMs/CTs stop - that's expected behavior,
        # not something that needs individual notifications.
        # Exception: errors and warnings should still be notified.
        _SHUTDOWN_NOISE = {'vm_stop', 'vm_shutdown', 'ct_stop', 'ct_shutdown'}
        if event_type in _SHUTDOWN_NOISE and not is_error and not is_warning:
            if _shared_state.is_host_shutting_down():
                return
        
        # During startup period, aggregate VM/CT starts into a single message.
        # Instead of N individual "VM X started" messages, collect them and
        # let PollingCollector emit one "System startup: X VMs, Y CTs started".
        # Exception: errors and warnings should NOT be aggregated - notify immediately.
        # Manual starts (onboot=0) within the grace period also bypass the
        # aggregator: a user manually starting a VM right after boot wants
        # the individual confirmation, not their action silently rolled into
        # the autostart summary. Audit Tier 6 — `system_startup` aggregation
        # puede tragar VM starts manuales del usuario durante grace period.
        _STARTUP_EVENTS = {'vm_start', 'ct_start'}
        if event_type in _STARTUP_EVENTS and not is_error and not is_warning:
            if _shared_state.is_startup_period():
                vm_type = 'ct' if event_type == 'ct_start' else 'vm'
                if self._is_autostart_vm(vmid, vm_type):
                    _shared_state.add_startup_vm(vmid, vmname or f'ID {vmid}', vm_type)
                    return
                # else: manual start — fall through to immediate notification
        
        self._queue.put(NotificationEvent(
            event_type, severity, data, source='tasks',
            entity=entity, entity_id=vmid,
        ))
    
    def _get_vm_name(self, vmid: str) -> str:
        """Try to resolve VMID to name via config files."""
        if not vmid:
            return ''

        # Try QEMU
        conf_path = f'/etc/pve/qemu-server/{vmid}.conf'
        name = self._read_name_from_conf(conf_path)
        if name:
            return name

        # Try LXC
        conf_path = f'/etc/pve/lxc/{vmid}.conf'
        name = self._read_name_from_conf(conf_path)
        if name:
            return name

        return ''

    @staticmethod
    def _is_autostart_vm(vmid: str, vm_type: str) -> bool:
        """Return True iff the VM/CT has `onboot: 1` in its PVE config.

        Used to decide whether a start during the boot grace period is part
        of the autostart sweep (aggregate into the summary) or a manual
        action by the user (deliver individually). When in doubt — the
        config can't be read or the line is missing — assume autostart so
        we err on the quiet side.
        """
        if not vmid:
            return True
        conf_path = (
            f'/etc/pve/qemu-server/{vmid}.conf'
            if vm_type == 'vm'
            else f'/etc/pve/lxc/{vmid}.conf'
        )
        try:
            if not os.path.exists(conf_path):
                return True
            with open(conf_path, 'r') as f:
                for line in f:
                    if line.startswith('onboot:'):
                        val = line.split(':', 1)[1].strip()
                        return val == '1'
            # No `onboot` key => default is 0 (not autostart).
            return False
        except (IOError, PermissionError):
            return True
    
    @staticmethod
    def _read_name_from_conf(path: str) -> str:
        """Read 'name:' or 'hostname:' from PVE config file."""
        try:
            if not os.path.exists(path):
                return ''
            with open(path, 'r') as f:
                for line in f:
                    if line.startswith('name:'):
                        return line.split(':', 1)[1].strip()
                    if line.startswith('hostname:'):
                        return line.split(':', 1)[1].strip()
        except (IOError, PermissionError):
            pass
        return ''


# ─── Polling Collector ────────────────────────────────────────────

class PollingCollector:
    """Periodic collector that polls health state independently.
    
    Architecture:
    - Completely independent from Health Monitor's suppression system.
      Suppression Duration only affects the UI health badge; it NEVER blocks
      notifications.
    - Reads ``get_active_errors()`` (ALL active errors, even suppressed ones)
      and decides when to notify based on its own 24-hour cycle.
    - For *new* errors (first_seen within the last poll interval), notifies
      immediately.
    - For *persistent* errors (already known), re-notifies once every 24 h.
    - Update checks run on their own 24-h timer and include security counts.
    
    Tracking is stored in ``notification_last_sent`` (same DB).
    """
    
    DIGEST_INTERVAL = 86400       # 24 h default between re-notifications
    UPDATE_CHECK_INTERVAL = 86400 # 24 h between update scans
    NEW_ERROR_WINDOW = 120        # seconds – errors younger than this are "new"
    
    # Per-category anti-oscillation cooldowns (seconds).
    # When an error resolves briefly and reappears, we still respect this
    # interval before notifying again.  This prevents "semi-cascades" where
    # the same root cause generates many slightly different notifications.
    #
    # Key = health_persistence category name
    # Value = minimum seconds between notifications for the same error_key
    _CATEGORY_COOLDOWNS = {
        # Category cooldown: minimum time between DIFFERENT errors of the same category
        # This prevents notification storms when multiple issues arise together
        'disks':        86400,   # 24h - I/O errors are persistent hardware issues
        'smart':        86400,   # 24h - SMART errors same as I/O
        'zfs':          86400,   # 24h - ZFS pool issues are persistent
        'storage':      3600,    # 1h  - storage availability can oscillate
        'network':      1800,    # 30m - network can flap
        'pve_services': 1800,    # 30m - services can restart/oscillate
        'temperature':  3600,    # 1h  - temp can fluctuate near thresholds
        'logs':         3600,    # 1h  - repeated log patterns
        'vms':          1800,    # 30m - VM state oscillation
        'vmct':         1800,    # 30m - VM/CT state oscillation
        'security':     3600,    # 1h  - auth failures tend to be bursty
        'cpu':          1800,    # 30m - CPU spikes can be transient
        'memory':       1800,    # 30m - memory pressure oscillation
        'disk':         3600,    # 1h  - disk space can fluctuate near threshold
        'updates':      86400,   # 24h - update info doesn't change fast
    }
    
    # Global cooldown: minimum time before the SAME error can be re-notified
    # This is independent of category - same error_key cannot repeat before this time
    SAME_ERROR_COOLDOWN = 86400  # 24 hours
    
    _ENTITY_MAP = {
        'cpu': ('node', ''), 'memory': ('node', ''), 'temperature': ('node', ''),
        'load': ('node', ''),
        'disk': ('storage', ''), 'disks': ('storage', ''), 'smart': ('storage', ''),
        'zfs': ('storage', ''), 'storage': ('storage', ''),
        'network': ('network', ''),
        'pve_services': ('node', ''), 'security': ('user', ''),
        'updates': ('node', ''), 'logs': ('node', ''), 'vms': ('vm', ''),
    }
    
    # Map health-persistence category names to our TEMPLATES event types.
    # These must match keys in notification_templates.TEMPLATES exactly.
    _CATEGORY_TO_EVENT_TYPE = {
        'cpu': 'cpu_high',
        'memory': 'ram_high',
        'load': 'load_high',
        'temperature': 'temp_high',
        'disk': 'disk_space_low',
        'disks': 'disk_io_error',         # I/O errors from health monitor
        'smart': 'disk_io_error',         # SMART errors from health monitor
        'zfs': 'disk_io_error',           # ZFS pool/disk errors
        'storage': 'storage_unavailable',
        'network': 'network_down',
        'pve_services': 'service_fail',
        'security': 'auth_fail',
        'updates': 'update_summary',
        'logs': 'system_problem',
        'vms': 'system_problem',
    }
    
    AI_MODEL_CHECK_INTERVAL = 86400  # 24h between AI model availability checks
    
    def __init__(self, event_queue: Queue, poll_interval: int = 60):
        self._queue = event_queue
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._poll_interval = poll_interval
        # `_hostname` is exposed as a @property below so every read returns
        # the *current* alias from the settings DB (TTL-cached for 5 s in
        # _hostname()). The old `__init__`-time cache made a fresh Display
        # Name require a service restart to take effect.
        self._last_update_check = 0
        self._last_proxmenux_check = 0
        self._last_ai_model_check = 0
        # Sprint 12D: post-install function updates check, on the same
        # 24h cooldown as the Proxmox/ProxMenux update checks. Notify
        # once per *changed set* of update keys — repeating the same
        # notification every 24h forever would be noisy, so we de-dupe
        # against the previously-notified set.
        self._last_post_install_check = 0
        self._notified_post_install_keys: set[str] = set()
        # Sprint 14.7: fingerprint (item_id → latest_version) of the
        # last managed-installs update notification, across all types
        # in the registry. A new notification fires when the
        # fingerprint changes — covers both "different latest version
        # of same item" and "new item appeared in the registry that
        # has an update".
        self._last_managed_check = 0
        self._notified_managed_updates: dict[str, str] = {}
        # LXC notifications are grouped — one event per polling cycle
        # covering every running Debian/Ubuntu CT with pending apt
        # updates. The fingerprint encodes the per-CT state so a stable
        # batch doesn't re-notify while a meaningful change does.
        self._notified_lxc_batch: str | None = None
        # Track notified ProxMenux versions to avoid duplicates
        self._notified_proxmenux_version: str | None = None
        self._notified_proxmenux_beta_version: str | None = None
        # In-memory cache: error_key -> last notification timestamp
        self._last_notified: Dict[str, float] = {}
        # In-memory cache: error_key -> severity actually sent in the last
        # notification. Decoupled from `_known_errors[k].severity` (which
        # always reflects the most-recent DB row) so a recovery message
        # quotes the same severity the user saw. Without this, an error
        # that fired WARNING, silently escalated to CRITICAL during its
        # 24h same-key cooldown, then resolved, would be reported as
        # "previous severity: CRITICAL" — confusing the operator who only
        # ever saw the WARNING. Not persisted across restarts: the
        # post-restart first-poll guard (`_first_poll_done`) already
        # suppresses spurious recoveries.
        self._notified_severity: Dict[str, str] = {}
        # Track known error keys + metadata so we can detect new ones AND emit recovery
        # Dict[error_key, dict(category, severity, reason, first_seen, error_key)]
        self._known_errors: Dict[str, dict] = {}
        self._first_poll_done = False
        # Cache of "is this device on USB?" lookups. Disks don't change bus
        # in runtime, so we can avoid one `readlink -f /sys/block/<dev>`
        # subprocess per disk-with-error per poll cycle. Key: bare device
        # name (no /dev/). Value: bool (True = USB).
        self._is_usb_cache: Dict[str, bool] = {}

    @property
    def _hostname(self) -> str:
        return _hostname()

    def start(self):
        if self._running:
            return
        self._running = True
        self._load_last_notified()
        # Load the previous-poll metadata snapshot so the FIRST poll after a
        # service restart can both (a) treat errors that were already known
        # as known (not new), and (b) emit recovery notifications for errors
        # that resolved during downtime. Without this the watermark resets
        # on every restart and a 7-min restart window is a recovery blind
        # spot. Audit Tier 6 — `PollingCollector` watermark no persiste +
        # primera ejecución no emite recovery.
        self._load_known_errors_meta()
        if self._known_errors:
            # We have a persisted snapshot — first poll is no longer "first"
            # for the purposes of new-error / recovery decisions.
            self._first_poll_done = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True,
                                        name='polling-collector')
        self._thread.start()
    
    def stop(self):
        self._running = False
    
    def _sleep_until_offset(self, cycle_start: float, offset: float):
        """Sleep until the specified offset within the current cycle."""
        target = cycle_start + offset
        now = time.time()
        if now < target:
            time.sleep(target - now)
    
    # ── Main loop ──────────────────────────────────────────────
    
    # Categories where transient errors are suppressed during startup grace period.
    # Now using centralized startup_grace module for consistency.
    
    def _poll_loop(self):
        """Main polling loop."""
        # Initial delay to let health monitor and external services warm up.
        # PBS storage, NFS mounts, VMs with guest agent all need time after boot.
        for _ in range(60):
            if not self._running:
                return
            time.sleep(1)
        
        # Staggered execution: spread checks across the polling interval
        # to avoid CPU spikes when multiple checks run simultaneously.
        # Schedule: health=10s, updates=30s, proxmenux=45s, post_install=47s, ai_model=50s
        STAGGER_HEALTH = 10
        STAGGER_UPDATES = 30
        STAGGER_PROXMENUX = 45
        STAGGER_POST_INSTALL = 47   # Sprint 12D: post-install function updates
        STAGGER_OCI_UPDATES = 48    # Sprint 14.6: Secure Gateway / OCI app updates
        STAGGER_AI_MODEL = 50

        while self._running:
            cycle_start = time.time()

            try:
                # Health check at offset 10s
                self._sleep_until_offset(cycle_start, STAGGER_HEALTH)
                if not self._running:
                    return
                self._check_persistent_health()

                # Updates check at offset 30s
                self._sleep_until_offset(cycle_start, STAGGER_UPDATES)
                if not self._running:
                    return
                self._check_updates()

                # ProxMenux check at offset 45s
                self._sleep_until_offset(cycle_start, STAGGER_PROXMENUX)
                if not self._running:
                    return
                self._check_proxmenux_updates()

                # Sprint 12D: post-install function updates at offset 47s.
                # Runs on the same 24h cooldown as the other update
                # checks; notifies once per changed set of update keys.
                self._sleep_until_offset(cycle_start, STAGGER_POST_INSTALL)
                if not self._running:
                    return
                self._check_post_install_updates()

                # Sprint 14.7: ProxMenux-managed installs (NVIDIA, OCI
                # apps, future Coral / Frigate / etc.) all flow through
                # one generic check. Refresh the registry from the host
                # (auto-detect new manual installs) then run every
                # type-specific checker. The polling loop only emits
                # notifications when the (id, latest) pair hasn't been
                # notified yet — same dedup pattern as the other update
                # channels.
                self._sleep_until_offset(cycle_start, STAGGER_OCI_UPDATES)
                if not self._running:
                    return
                self._check_managed_installs_updates()

                # AI model check at offset 50s
                self._sleep_until_offset(cycle_start, STAGGER_AI_MODEL)
                if not self._running:
                    return
                self._check_ai_model_availability()
                
                # Check if startup period ended and we have aggregated VMs to report
                self._check_startup_aggregation()
                
            except Exception as e:
                print(f"[PollingCollector] Error: {e}")
            
            # Sleep remaining time until next cycle
            elapsed = time.time() - cycle_start
            remaining = max(self._poll_interval - elapsed, 1)
            for _ in range(int(remaining)):
                if not self._running:
                    return
                time.sleep(1)
    
    # ── Health errors (independent of suppression) ─────────────
    
    def _check_persistent_health(self):
        """Read ALL active errors from health_persistence and decide
        whether each one warrants a notification right now.
        
        Rules:
        - A *new* error (not in _known_errors) -> notify immediately
        - A *persistent* error already notified -> re-notify after 24 h
        - Uses its own tracking, NOT the health monitor's needs_notification flag
        """
        try:
            from health_persistence import health_persistence
            errors = health_persistence.get_active_errors()
        except ImportError:
            return
        except Exception as e:
            print(f"[PollingCollector] get_active_errors failed: {e}")
            return
        
        now = time.time()
        current_keys: Dict[str, dict] = {}
        
        for error in errors:
            error_key = error.get('error_key', '')
            if not error_key:
                continue
            
            current_keys[error_key] = {
                'category': error.get('category', ''),
                'severity': error.get('severity', 'WARNING'),
                'reason': error.get('reason', ''),
                'first_seen': error.get('first_seen', ''),
                'error_key': error_key,
            }
            category = error.get('category', '')
            severity = error.get('severity', 'WARNING')
            reason = error.get('reason', '')
            
            # Never notify for INFO/OK severity -- these are informational only
            if severity in ('INFO', 'OK'):
                continue
            
            # Skip dismissed/acknowledged errors -- the user already handled these
            if error.get('acknowledged') == 1:
                continue
            
            # Startup grace period: ignore transient errors from categories that
            # typically need time to stabilize after boot (storage, VMs, network).
            # PBS storage, NFS mounts, VMs with qemu-guest-agent need time to connect.
            # Uses centralized startup_grace module for consistency.
            if startup_grace.should_suppress_category(category):
                continue
            
            # On first poll, seed _last_notified for all existing errors so we
            # don't re-notify old persistent errors that were already sent before
            # a service restart.  Only genuinely NEW errors (appearing after the
            # first poll) will trigger immediate notifications.
            if not self._first_poll_done:
                if error_key not in self._last_notified:
                    self._last_notified[error_key] = now
                continue
            
            # ── Freshness check for re-notifications ──
            # Don't re-notify errors whose last_seen is stale (>2h old).
            # If the health monitor stopped detecting the error, last_seen
            # freezes.  Re-notifying with dated info is confusing.
            _FRESHNESS_WINDOW = 7200  # 2 hours
            last_seen_str = error.get('last_seen', '')
            error_is_stale = False
            if last_seen_str:
                try:
                    from datetime import datetime as _dt
                    ls_epoch = _dt.fromisoformat(last_seen_str).timestamp()
                    if now - ls_epoch > _FRESHNESS_WINDOW:
                        error_is_stale = True
                except (ValueError, TypeError):
                    pass
            
            # Determine if we should notify
            is_new = error_key not in self._known_errors
            last_sent = self._last_notified.get(error_key, 0)
            time_since_last = now - last_sent
            
            # ── SAME ERROR COOLDOWN (24h) ──
            # The SAME error_key cannot be re-notified before 24 hours.
            # This is the PRIMARY deduplication mechanism.
            # EXCEPTION: If user dismissed the error, the cooldown is cleared in DB
            # and we should re-check DB to see if cooldown still applies.
            if time_since_last < self.SAME_ERROR_COOLDOWN:
                # Check if user dismissed this - clears DB cooldown
                db_ts = self._get_cooldown_from_db(error_key)
                if db_ts is not None and now - db_ts < self.SAME_ERROR_COOLDOWN:
                    continue  # DB confirms cooldown still active
                # DB says cooldown was cleared (user dismissed) - remove from memory
                self._last_notified.pop(error_key, None)
                # Continue to the next checks (category cooldown etc.)
            
            # ── CATEGORY COOLDOWN (varies) ──
            # DIFFERENT errors within the same category respect category cooldown.
            # This prevents notification storms when multiple issues arise together.
            cat_cooldown = self._CATEGORY_COOLDOWNS.get(category, self.DIGEST_INTERVAL)
            is_due = time_since_last >= cat_cooldown
            
            if not is_due:
                continue
            
            # For re-notifications (not new): also skip if stale
            if not is_new:
                if error_is_stale:
                    continue
            
            # Map to our event type
            event_type = self._CATEGORY_TO_EVENT_TYPE.get(category, 'system_problem')
            entity, eid = self._ENTITY_MAP.get(category, ('node', ''))

            # Refine the storage event_type from the error_key prefix.
            # The category-only mapping was sending every storage error
            # through the generic `storage_unavailable` template — the
            # specialised templates (lxc_disk_low, mount_stale, etc.)
            # were never reached. Sprint 14.5 adds three new prefixes
            # (lxc_mount_, pve_storage_full_, zfs_pool_full_) and at the
            # same time fixes the dispatch for the existing ones.
            if category == 'storage':
                if error_key.startswith('lxc_disk_'):
                    event_type = 'lxc_disk_low'
                elif error_key.startswith('lxc_mount_'):
                    event_type = 'lxc_mount_low'
                elif error_key.startswith('pve_storage_full_'):
                    event_type = 'pve_storage_full'
                elif error_key.startswith('zfs_pool_full_'):
                    event_type = 'zfs_pool_full'
                elif error_key.startswith('disk_space_'):
                    event_type = 'disk_space_low'
                elif error_key.startswith('storage_unavailable_'):
                    event_type = 'storage_unavailable'
                elif error_key.startswith('mount_stale_'):
                    event_type = 'mount_stale'
                elif error_key.startswith('mount_readonly_'):
                    event_type = 'mount_readonly'
            
            # ── Disk I/O notification policy ──
            # Disk I/O errors are ALWAYS notified (even when SMART says Passed)
            # because recurring I/O errors are real issues that should not be hidden.
            # The 24h cooldown is enforced per-device by NotificationManager
            # (event_type 'disk_io_error' gets 86400s cooldown).
            # For transient/INFO-level disk events (SMART OK, low error count),
            # the health monitor already resolves them, so they won't appear here.
            if category in ('disks', 'smart', 'zfs'):
                details_raw = error.get('details', {})
                if isinstance(details_raw, str):
                    try:
                        details_raw = json.loads(details_raw)
                    except (json.JSONDecodeError, TypeError):
                        details_raw = {}
                if isinstance(details_raw, dict):
                    # Extract device name for a stable entity_id (24h cooldown key)
                    dev = details_raw.get('device', details_raw.get('disk', ''))
                    serial = details_raw.get('serial', '')
                    
                    # For USB disks, use serial as entity_id for stable cooldown
                    # USB disks can change device names (sda->sdb) on reconnect
                    # Using serial ensures same physical disk shares cooldown
                    if serial and dev:
                        bare_dev = dev.replace('/dev/', '')
                        is_usb = self._is_usb_cache.get(bare_dev)
                        if is_usb is None:
                            try:
                                sysfs_result = subprocess.run(
                                    ['readlink', '-f', f'/sys/block/{bare_dev}'],
                                    capture_output=True, text=True, timeout=2
                                )
                                is_usb = 'usb' in sysfs_result.stdout.lower()
                            except Exception:
                                is_usb = False
                            self._is_usb_cache[bare_dev] = is_usb
                        eid = f'disk_serial_{serial}' if is_usb else f'disk_{dev}'
                    elif dev:
                        eid = f'disk_{dev}'  # No serial: use device name
            
            # Updates are always informational notifications except
            # system_age which can be WARNING (365+ days) or CRITICAL (548+ days).
            emit_severity = severity
            if category == 'updates' and error_key != 'system_age':
                emit_severity = 'INFO'
            
            data = {
                'hostname': self._hostname,
                'category': category,
                'reason': reason,
                'error_key': error_key,
                'severity': emit_severity,
                'first_seen': error.get('first_seen', ''),
                'last_seen': error.get('last_seen', ''),
                'is_persistent': not is_new,
            }
            
            # Include extra details if present
            details = error.get('details')
            if isinstance(details, dict):
                data.update(details)
            elif isinstance(details, str):
                try:
                    data.update(json.loads(details))
                except (json.JSONDecodeError, TypeError):
                    pass
            
            self._queue.put(NotificationEvent(
                event_type, emit_severity, data, source='health',
                entity=entity, entity_id=eid or error_key,
            ))
            
            # Track that we notified
            self._last_notified[error_key] = now
            self._persist_last_notified(error_key, now)
            # Snapshot the severity we actually delivered, so a future
            # recovery message quotes the same value the user saw — not
            # whatever silently-escalated severity ended up in the DB
            # during the same-key 24h cooldown window.
            self._notified_severity[error_key] = emit_severity
        
        # ── Emit recovery notifications for errors that resolved ──
        resolved_keys = set(self._known_errors.keys()) - set(current_keys.keys())
        for key in resolved_keys:
            old_meta = self._known_errors.get(key, {})
            category = old_meta.get('category', '')
            reason = old_meta.get('reason', '')
            first_seen = old_meta.get('first_seen', '')

            # Skip recovery for INFO/OK - they never triggered an alert
            if old_meta.get('severity', '') in ('INFO', 'OK'):
                self._last_notified.pop(key, None)
                continue

            # Skip recovery on first poll (we don't know what was before)
            if not self._first_poll_done:
                self._last_notified.pop(key, None)
                continue

            # Skip recovery when the persisted snapshot lost the context
            # for this error (reason / category both empty). Emitting a
            # blank "Resuelto -" message with "Condition resolved" body
            # adds no value — the user can't tell which error went away.
            # Happens after a long Monitor downtime when the snapshot was
            # serialized between polls without reason/category populated,
            # or when a future code path slips a key into _known_errors
            # without the full metadata. Drop the tracking entry silently
            # so we never re-fire on the same incomplete record.
            if not reason and not category:
                self._last_notified.pop(key, None)
                self._notified_severity.pop(key, None)
                continue
            
            # Skip recovery if the error was manually acknowledged (dismissed)
            # by the user. Acknowledged != resolved -- the problem may still
            # exist, the user just chose to suppress notifications for it.
            try:
                if health_persistence.is_error_acknowledged(key):
                    self._last_notified.pop(key, None)
                    continue
            except Exception:
                pass
            
            # Skip recovery notifications for PERMANENT disk events.
            # These indicate physical disk degradation that doesn't truly "recover":
            # - SMART pending/reallocated sectors indicate physical damage
            # - Disk may show 0 pending sectors later but damage history persists
            # - Sending "Resolved" gives false sense of security
            # The worst_health in disk_registry tracks this permanently.
            if category == 'disks':
                reason_lower = (reason or '').lower()
                permanent_indicators = [
                    'pending',           # pending sectors
                    'reallocated',       # reallocated sectors  
                    'unreadable',        # unreadable sectors
                    'smart',             # SMART errors
                    'surface error',     # disk surface errors
                    'bad sector',        # bad sectors
                    'i/o error',         # I/O errors (repeated)
                    'medium error',      # SCSI medium errors
                ]
                if any(indicator in reason_lower for indicator in permanent_indicators):
                    # Don't send recovery - just clean up tracking
                    self._last_notified.pop(key, None)
                    continue
            
            # Calculate duration
            duration = ''
            if first_seen:
                try:
                    from datetime import datetime
                    fs_dt = datetime.fromisoformat(first_seen)
                    delta = datetime.now() - fs_dt
                    total_sec = int(delta.total_seconds())
                    if total_sec < 60:
                        duration = f'{total_sec}s'
                    elif total_sec < 3600:
                        duration = f'{total_sec // 60}m'
                    elif total_sec < 86400:
                        h = total_sec // 3600
                        m = (total_sec % 3600) // 60
                        duration = f'{h}h {m}m'
                    else:
                        d = total_sec // 86400
                        h = (total_sec % 86400) // 3600
                        duration = f'{d}d {h}h'
                except Exception:
                    duration = 'unknown'
            
            entity, eid = self._ENTITY_MAP.get(category, ('node', ''))
            
            # For resolved notifications, use only the first line of reason
            # (the title/summary) to avoid repeating verbose details.
            # Also extract a clean device identifier if present.
            reason_lines = (reason or '').split('\n')
            reason_summary = reason_lines[0] if reason_lines else ''
            
            # Try to extract device info for a clean "Device: xxx (recovered)" line
            device_line = ''
            for line in reason_lines:
                if 'Device:' in line or 'Device not currently' in line or '/dev/' in line:
                    # Extract the most useful device description
                    if 'not currently detected' in line.lower():
                        device_line = 'Device not currently detected -- may be a disconnected USB or temporary device'
                        break
                    elif 'Device:' in line:
                        device_line = line.strip()
                        break
            
            if reason_summary and device_line:
                clean_reason = f'{reason_summary}\n{device_line} (recovered)'
            elif reason_summary:
                clean_reason = f'{reason_summary} (recovered)'
            else:
                clean_reason = 'Condition resolved'
            
            # `original_severity` must match what the user actually saw
            # in the most-recent notification for this error, not the
            # latest DB severity. See `_notified_severity` docstring at
            # __init__ for the failure mode this avoids.
            original_severity = self._notified_severity.get(
                key, old_meta.get('severity', 'WARNING'),
            )
            # Defensive defaults — the template uses `{category}` and
            # `{duration}` in both the title and the body; an empty
            # `category` produced the cosmetic "Resolved - " with a
            # trailing dash (and "The  issue has been resolved" with
            # a double space) on 2026-05-21. The Fix A filter above
            # already drops the worst case (reason AND category empty);
            # this layer fills the remaining edge cases when only one
            # of the two is missing.
            category_label = category or 'health'
            duration_label = duration or 'unknown'
            data = {
                'hostname': self._hostname,
                'category': category_label,
                'reason': clean_reason,
                'error_key': key,
                'severity': 'OK',
                'original_severity': original_severity,
                'first_seen': first_seen,
                'duration': duration_label,
                'is_recovery': True,
            }

            self._queue.put(NotificationEvent(
                'error_resolved', 'OK', data, source='health',
                entity=entity, entity_id=eid or key,
            ))

            self._last_notified.pop(key, None)
            self._notified_severity.pop(key, None)
        
        self._known_errors = current_keys
        self._first_poll_done = True
        # Persist metadata for the next restart's first-poll comparison.
        self._save_known_errors_meta()

    def _check_startup_aggregation(self):
        """Check if startup period ended and emit comprehensive startup report.
        
        At the end of the health grace period, collects:
        - VMs/CTs that started successfully
        - VMs/CTs that failed to start
        - Service status
        - Storage status
        - Journal errors (for AI enrichment)
        
        Emits a single "system_startup" notification with full report data.
        
        IMPORTANT: Only emits if this is a REAL system boot, not a service restart.
        Checks system uptime to distinguish between the two cases.
        """
        # Wait until health grace period is over (5 min) for complete picture
        if startup_grace.is_startup_health_grace():
            return
        
        # Only emit once
        if startup_grace.was_startup_aggregated():
            return
        
        # CRITICAL: Check if this is a real system boot
        # If the system was already running for > 10 min when service started,
        # this is just a service restart, not a system boot - skip notification
        if not startup_grace.is_real_system_boot():
            # Mark as aggregated to prevent future checks, but don't send notification
            startup_grace.mark_startup_aggregated()
            return
        
        # Collect comprehensive startup report
        report = startup_grace.collect_startup_report()
        
        # Generate human-readable summary
        summary = startup_grace.format_startup_summary(report)
        
        # Count totals
        vms_ok = len(report.get('vms_started', []))
        cts_ok = len(report.get('cts_started', []))
        vms_fail = len(report.get('vms_failed', []))
        cts_fail = len(report.get('cts_failed', []))
        total_ok = vms_ok + cts_ok
        total_fail = vms_fail + cts_fail
        
        # Build entity list for backwards compatibility
        entity_names = []
        for vm in report.get('vms_started', [])[:5]:
            entity_names.append(f"{vm['name']} ({vm['vmid']})")
        for ct in report.get('cts_started', [])[:5]:
            entity_names.append(f"{ct['name']} ({ct['vmid']})")
        if total_ok > 10:
            entity_names.append(f"...and {total_ok - 10} more")
        
        # Determine severity based on issues
        has_issues = (
            total_fail > 0 or
            not report.get('services_ok', True) or
            not report.get('storage_ok', True) or
            report.get('health_status') in ['CRITICAL', 'WARNING']
        )
        severity = 'WARNING' if has_issues else 'INFO'
        
        # Build notification data
        data = {
            'hostname': self._hostname,
            'summary': summary,
            
            # VM/CT counts (backwards compatible)
            'vm_count': vms_ok,
            'ct_count': cts_ok,
            'total_count': total_ok,
            'entity_list': ', '.join(entity_names),
            
            # New: failure counts
            'vms_failed_count': vms_fail,
            'cts_failed_count': cts_fail,
            'total_failed': total_fail,
            
            # New: detailed lists
            'vms_started': report.get('vms_started', []),
            'cts_started': report.get('cts_started', []),
            'vms_failed': report.get('vms_failed', []),
            'cts_failed': report.get('cts_failed', []),
            
            # New: system status
            'services_ok': report.get('services_ok', True),
            'services_failed': report.get('services_failed', []),
            'storage_ok': report.get('storage_ok', True),
            'storage_unavailable': report.get('storage_unavailable', []),
            'health_status': report.get('health_status', 'UNKNOWN'),
            'health_issues': report.get('health_issues', []),
            
            # For AI enrichment
            '_journal_context': report.get('_journal_context', ''),
            
            # Metadata
            'startup_duration_seconds': report.get('startup_duration_seconds', 0),
            'has_issues': has_issues,
            'reason': summary.split('\n')[0],  # First line as reason
        }
        
        self._queue.put(NotificationEvent(
            'system_startup', severity, data, source='polling',
            entity='node', entity_id='',
        ))
    
    # ── Update check (enriched) ────────────────────────────────
    
    # Proxmox-related package prefixes used for categorisation
    _PVE_PREFIXES = (
        'pve-', 'proxmox-', 'qemu-server', 'lxc-pve', 'ceph',
        'corosync', 'libpve', 'pbs-', 'pmg-',
    )
    _KERNEL_PREFIXES = ('linux-image', 'pve-kernel', 'pve-firmware')
    _IMPORTANT_PKGS = {
        'pve-manager', 'proxmox-ve', 'qemu-server', 'pve-container',
        'pve-ha-manager', 'pve-firewall', 'pve-storage-iscsi-direct',
        'ceph-common', 'proxmox-backup-client',
    }
    
    # Regex to parse Inst lines from apt-get -s upgrade
    # Inst <pkg> [<cur_ver>] (<new_ver> <repo> [<arch>])
    _RE_INST = re.compile(
        r'^Inst\s+(\S+)\s+\[([^\]]+)\]\s+\((\S+)\s+'
    )
    # Fallback for new installs (no current version):
    # Inst <pkg> (<new_ver> <repo> [<arch>])
    _RE_INST_NEW = re.compile(
        r'^Inst\s+(\S+)\s+\((\S+)\s+'
    )
    
    def _check_updates(self):
        """Check for available system updates every 24 h.
        
        Emits a structured ``update_summary`` notification with categorised
        counts (security, Proxmox-related, kernel, other) and important
        package versions.  If pve-manager has an upgrade, also emits a
        separate ``pve_update`` notification.
        """
        now = time.time()
        if now - self._last_update_check < self.UPDATE_CHECK_INTERVAL:
            return
        
        self._last_update_check = now
        
        try:
            result = subprocess.run(
                ['apt-get', '-s', 'upgrade'],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return
            
            inst_lines = [l for l in result.stdout.split('\n') if l.startswith('Inst ')]
            total = len(inst_lines)
            if total == 0:
                return
            
            # ── Parse every Inst line ──────────────────────────────
            all_pkgs: list[dict] = []   # {name, cur, new}
            security_pkgs: list[dict] = []
            pve_pkgs: list[dict] = []
            kernel_pkgs: list[dict] = []
            pve_manager_info: dict | None = None
            
            for line in inst_lines:
                m = self._RE_INST.match(line)
                if m:
                    info = {'name': m.group(1), 'cur': m.group(2), 'new': m.group(3)}
                else:
                    m2 = self._RE_INST_NEW.match(line)
                    if m2:
                        info = {'name': m2.group(1), 'cur': '', 'new': m2.group(2)}
                    else:
                        pkg_name = line.split()[1] if len(line.split()) > 1 else 'unknown'
                        info = {'name': pkg_name, 'cur': '', 'new': ''}
                
                all_pkgs.append(info)
                name_lower = info['name'].lower()
                line_lower = line.lower()
                
                # Categorise
                if 'security' in line_lower or 'debian-security' in line_lower:
                    security_pkgs.append(info)
                
                if any(name_lower.startswith(p) for p in self._KERNEL_PREFIXES):
                    kernel_pkgs.append(info)
                elif any(name_lower.startswith(p) for p in self._PVE_PREFIXES):
                    pve_pkgs.append(info)
                
                # Detect pve-manager upgrade specifically
                if info['name'] == 'pve-manager':
                    pve_manager_info = info
            
            # ── Build important packages list ──────────────────────
            important_lines = []
            for pkg in all_pkgs:
                if pkg['name'] in self._IMPORTANT_PKGS and pkg['cur']:
                    important_lines.append(
                        f"{pkg['name']} ({pkg['cur']} → {pkg['new']})"
                    )
            
            # ── Emit structured update_summary ─────────────────────
            data = {
                'hostname': self._hostname,
                'total_count': str(total),
                'security_count': str(len(security_pkgs)),
                'pve_count': str(len(pve_pkgs)),
                'kernel_count': str(len(kernel_pkgs)),
                'important_list': '\n'.join(f'  \u2022 {l}' for l in important_lines) if important_lines else 'none',
                'package_list': ', '.join(important_lines[:6]) if important_lines else '',
            }
            
            self._queue.put(NotificationEvent(
                'update_summary', 'INFO', data,
                source='polling', entity='node', entity_id='',
            ))
            
            # ── Emit pve_update if pve-manager has an upgrade ──────
            if pve_manager_info and pve_manager_info['cur'] and pve_manager_info['new']:
                pve_data = {
                    'hostname': self._hostname,
                    'current_version': pve_manager_info['cur'],
                    'new_version': pve_manager_info['new'],
                    'version': pve_manager_info['new'],
                    'details': f"pve-manager {pve_manager_info['cur']} → {pve_manager_info['new']}",
                }
                self._queue.put(NotificationEvent(
                    'pve_update', 'INFO', pve_data,
                    source='polling', entity='node', entity_id='',
                ))
        except Exception:
            pass
    
    # ── ProxMenux update check ────────────────────────────────
    
    PROXMENUX_VERSION_FILE = '/usr/local/share/proxmenux/version.txt'
    PROXMENUX_BETA_VERSION_FILE = '/usr/local/share/proxmenux/beta_version.txt'
    REPO_MAIN_VERSION_URL = 'https://raw.githubusercontent.com/MacRimi/ProxMenux/main/version.txt'
    REPO_DEVELOP_VERSION_URL = 'https://raw.githubusercontent.com/MacRimi/ProxMenux/develop/beta_version.txt'
    
    def _check_proxmenux_updates(self):
        """Check for ProxMenux updates (main and beta channels).
        
        Compares local version files with remote GitHub repository versions
        and emits notifications when updates are available.
        Uses same 24h interval as system updates.
        """
        import urllib.request
        
        now = time.time()
        if now - self._last_proxmenux_check < self.UPDATE_CHECK_INTERVAL:
            return
        
        self._last_proxmenux_check = now
        
        def read_local_version(path: str) -> str | None:
            """Read version from local file."""
            try:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        return f.read().strip()
            except Exception:
                pass
            return None
        
        def read_remote_version(url: str) -> str | None:
            """Fetch version from remote URL."""
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'ProxMenux-Monitor/1.0'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.read().decode('utf-8').strip()
            except Exception:
                pass
            return None
        
        def version_tuple(v: str) -> tuple:
            """Convert version string to tuple for comparison."""
            try:
                return tuple(int(x) for x in v.split('.'))
            except Exception:
                return (0,)
        
        def update_config_json(stable: bool = None, stable_version: str = None, 
                               beta: bool = None, beta_version: str = None):
            """Update update_available status in config.json."""
            config_path = Path('/usr/local/share/proxmenux/config.json')
            try:
                config = {}
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                
                if 'update_available' not in config:
                    config['update_available'] = {
                        'stable': False, 'stable_version': '',
                        'beta': False, 'beta_version': ''
                    }
                
                if stable is not None:
                    config['update_available']['stable'] = stable
                    config['update_available']['stable_version'] = stable_version or ''
                if beta is not None:
                    config['update_available']['beta'] = beta
                    config['update_available']['beta_version'] = beta_version or ''
                
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
            except Exception as e:
                print(f"[PollingCollector] Failed to update config.json: {e}")
        
        try:
            # Check main version
            local_main = read_local_version(self.PROXMENUX_VERSION_FILE)
            if local_main:
                remote_main = read_remote_version(self.REPO_MAIN_VERSION_URL)
                if remote_main and version_tuple(remote_main) > version_tuple(local_main):
                    # Update config.json with stable update status
                    update_config_json(stable=True, stable_version=remote_main)
                    # Only notify if we haven't already notified for this version
                    if self._notified_proxmenux_version != remote_main:
                        self._notified_proxmenux_version = remote_main
                        data = {
                            'hostname': self._hostname,
                            'current_version': local_main,
                            'new_version': remote_main,
                        }
                        self._queue.put(NotificationEvent(
                            'proxmenux_update', 'INFO', data,
                            source='polling', entity='node', entity_id='',
                        ))
                else:
                    # No update available - reset the flag
                    update_config_json(stable=False, stable_version='')
                    self._notified_proxmenux_version = None
            
            # Check beta version (only if user has beta file)
            local_beta = read_local_version(self.PROXMENUX_BETA_VERSION_FILE)
            if local_beta:
                remote_beta = read_remote_version(self.REPO_DEVELOP_VERSION_URL)
                if remote_beta and version_tuple(remote_beta) > version_tuple(local_beta):
                    # Update config.json with beta update status
                    update_config_json(beta=True, beta_version=remote_beta)
                    # Only notify if we haven't already notified for this version
                    if self._notified_proxmenux_beta_version != remote_beta:
                        self._notified_proxmenux_beta_version = remote_beta
                        data = {
                            'hostname': self._hostname,
                            'current_version': local_beta,
                            'new_version': f'{remote_beta} (Beta)',
                        }
                        # Use same event_type - single toggle controls both
                        self._queue.put(NotificationEvent(
                            'proxmenux_update', 'INFO', data,
                            source='polling', entity='node', entity_id='',
                        ))
                else:
                    # No beta update available - reset the flag
                    update_config_json(beta=False, beta_version='')
                    self._notified_proxmenux_beta_version = None
        except Exception:
            pass

    # ── Post-install function updates check (Sprint 12D) ────────────

    def _check_post_install_updates(self):
        """Notify the operator when post-install functions have new versions.

        Sprint 12A's detector runs at AppImage startup and writes
        ``updates_available.json``. This check refreshes the snapshot
        every 24h (matching the other update channels), and emits a
        single ``post_install_update`` event the first time the *set* of
        available updates changes. Repeating the same notification every
        24h forever would be noisy, so we de-dupe against the previously
        notified set of tool keys: only when a new tool joins the list
        (or an existing one disappears) does a fresh notification fire.
        """
        now = time.time()
        if now - self._last_post_install_check < self.UPDATE_CHECK_INTERVAL:
            return
        self._last_post_install_check = now

        try:
            import post_install_versions
            snapshot = post_install_versions.scan(persist=True)
            updates = snapshot.get('updates', []) or []
        except Exception as e:
            print(f"[PollingCollector] post-install update scan failed: {e}")
            return

        if not updates:
            # All caught up. Reset so a future bump triggers a fresh
            # notification instead of being suppressed by stale state.
            self._notified_post_install_keys = set()
            return

        new_keys = {u.get('key', '') for u in updates if u.get('key')}
        if new_keys == self._notified_post_install_keys:
            return  # already notified about this exact set

        self._notified_post_install_keys = new_keys

        # Pre-format the bullet list here so the template can drop it
        # straight in with `{tool_list}` (the renderer is plain
        # `str.format_map`, no Jinja). Format mirrors the Proxmox
        # update notification: just `key (vX → vY)` per bullet, no
        # description — the description was descriptive but redundant
        # with the tool name itself, and the user wanted parity with
        # the Proxmox-update list which only shows the package name.
        tool_list_lines = [
            f"  • {u.get('key', '')} (v{u.get('current_version', '')} → v{u.get('available_version', '')})"
            for u in updates
        ]
        tool_list_str = '\n'.join(tool_list_lines)

        data = {
            'hostname': self._hostname,
            'count': len(updates),
            'tool_list': tool_list_str,
            'tools': [
                {
                    'key': u.get('key', ''),
                    'current_version': u.get('current_version', ''),
                    'available_version': u.get('available_version', ''),
                    'description': u.get('description', ''),
                    'source': u.get('source', ''),
                    'function': u.get('function', ''),
                }
                for u in updates
            ],
        }
        self._queue.put(NotificationEvent(
            'post_install_update', 'INFO', data,
            source='polling', entity='node', entity_id='',
        ))

    # ── Managed-installs update check (Sprint 14.7) ─────────────────

    def _check_managed_installs_updates(self):
        """Generic update-notification emitter on top of the
        ``managed_installs`` registry.

        Refreshes the registry (auto-detects new installs that
        appeared since last cycle), then runs every type-specific
        checker, then emits one event per item whose ``(id,
        latest_version)`` pair hasn't been notified yet. The event_type
        is mapped per item type so each integration gets its own
        template (Tailscale → ``secure_gateway_update_available``,
        NVIDIA driver → ``nvidia_driver_update_available``, etc.).
        """
        now = time.time()

        if now - self._last_managed_check < self.UPDATE_CHECK_INTERVAL:
            return
        self._last_managed_check = now

        try:
            import managed_installs
        except Exception:
            return  # registry module unavailable

        try:
            managed_installs.detect_and_register()
            updates = managed_installs.check_for_updates(force=False) or []
        except Exception as e:
            print(f"[PollingCollector] managed_installs update run failed: {e}")
            return

        # Split LXC updates out of the per-item event stream — they get
        # one grouped notification per cycle instead of one per CT, to
        # avoid spamming the user when 15 CTs have pending updates the
        # same day. Non-LXC types keep their existing per-item flow.
        lxc_updates = [u for u in updates if u.get('type') == 'lxc']
        other_updates = [u for u in updates if u.get('type') != 'lxc']

        seen_ids: set[str] = set()
        for item in other_updates:
            item_id = item.get('id', '')
            if not item_id:
                continue
            seen_ids.add(item_id)

            update = item.get('update_check', {}) or {}
            latest = update.get('latest') or ''
            previously = self._notified_managed_updates.get(item_id)
            if previously == latest:
                continue  # already told the user about this exact version

            self._notified_managed_updates[item_id] = latest

            event_type, data = self._build_managed_install_event(item)
            if not event_type:
                continue

            self._queue.put(NotificationEvent(
                event_type, 'INFO', data,
                source='polling',
                entity='node',
                entity_id=f'managed_{item_id}',
            ))

        # LXC: emit one grouped event with all CTs that have pending
        # updates. The batch fingerprint is recomputed every cycle and
        # compared with the last notified one — if the set of CTs or
        # their per-CT fingerprints changed, we notify again.
        #
        # Detection itself runs unconditionally so the dashboard always
        # shows pending updates; the `lxc_updates_available` toggle only
        # controls whether a notification is *emitted*. If it's off we
        # skip the emit (and the dedup stamp) so re-enabling the toggle
        # later fires the next pending batch immediately.
        try:
            import managed_installs as _mi
            lxc_notif_enabled = _mi._lxc_updates_notification_enabled()
        except Exception:
            lxc_notif_enabled = False

        if lxc_updates and lxc_notif_enabled:
            self._emit_lxc_updates_batch(lxc_updates)
        elif not lxc_updates:
            # Empty batch — clear the dedup so a fresh batch later fires
            # a new notification even with the same CTs/versions.
            self._notified_lxc_batch = None

        # Forget items that no longer have an update available. If
        # the user installs the update and then a later release lands,
        # the dedup state is already cleared so the next notification
        # fires fresh.
        try:
            active = managed_installs.get_active_items()
        except Exception:
            active = []
        active_with_update = {
            it.get('id') for it in active
            if it.get('update_check', {}).get('available')
        }
        for stale_id in list(self._notified_managed_updates.keys()):
            if stale_id not in active_with_update:
                self._notified_managed_updates.pop(stale_id, None)

    def _emit_lxc_updates_batch(self, items: list[dict]) -> None:
        """Build and queue a single ``lxc_updates_available`` event for
        every running CT that currently has pending apt updates.

        The batch fingerprint combines every CT's per-CT fingerprint
        (count + security_count + top package names). A new CT entering
        the set OR an existing CT changing its per-CT fingerprint
        produces a new batch fingerprint, so the cooldown is broken and
        the event fires. A truly stable batch is silenced via the
        equality check below.
        """
        # Stable order so the fingerprint is deterministic
        items_sorted = sorted(items, key=lambda x: x.get('id', ''))

        ct_lines: list[str] = []
        per_ct_fps: list[str] = []
        total_packages = 0
        total_security = 0

        for idx, it in enumerate(items_sorted):
            update = it.get('update_check', {}) or {}
            count = int(update.get('_count') or 0)
            sec_count = int(update.get('_security_count') or 0)
            total_packages += count
            total_security += sec_count

            vmid = it.get('_vmid') or it.get('id', '').removeprefix('lxc:') or '?'
            name = it.get('name') or f'CT {vmid}'
            # Each CT renders across two/three lines so the count and the
            # security count don't compete with the CT label on the same
            # row — much easier to read in Telegram/Discord at a glance.
            # A blank line before every CT except the first separates
            # entries cleanly without a trailing blank at the end.
            if idx > 0:
                ct_lines.append("")
            ct_lines.append(f"🏷️ CT {vmid} ({name}):")
            ct_lines.append(f"    📦 {count} update(s)")
            if sec_count:
                ct_lines.append(f"    🔒 {sec_count} security")
            per_ct_fps.append(f"{it.get('id', '')}={update.get('latest', '')}")

        batch_fingerprint = '|'.join(per_ct_fps)
        if self._notified_lxc_batch == batch_fingerprint:
            return  # same batch as last time — silent
        self._notified_lxc_batch = batch_fingerprint

        data = {
            'hostname': self._hostname,
            'count': len(items_sorted),
            'total_packages': total_packages,
            'security_count': total_security,
            'ct_list': '\n'.join(ct_lines),
        }
        self._queue.put(NotificationEvent(
            'lxc_updates_available', 'INFO', data,
            source='polling',
            entity='node',
            # Hash so different batches get distinct cooldown keys
            entity_id=f'lxc_batch_{abs(hash(batch_fingerprint)) % 10**10}',
        ))

    def _build_managed_install_event(self, item: dict) -> tuple[str, dict]:
        """Translate a registry item into a (event_type, template_data)
        pair. Per-type bodies live here so the registry stays
        type-agnostic and notification_templates only needs to know
        about the final shape."""
        item_type = item.get('type', '')
        update = item.get('update_check', {}) or {}
        common = {
            'hostname': self._hostname,
            'name': item.get('name') or item.get('id'),
            'menu_label': item.get('menu_label') or '',
            'menu_script': item.get('menu_script') or '',
            'current_version': item.get('current_version') or '',
            'latest_version': update.get('latest') or '',
        }

        if item_type == 'oci_app':
            packages = update.get('_packages') or []
            pkg_lines = [
                f"  • {p.get('name', '')}: {p.get('current', '?')}"
                f" → {p.get('latest', '?')}"
                for p in packages
            ]
            data = {
                **common,
                'app_id': item.get('id', '').removeprefix('oci:'),
                'app_name': common['name'],
                'package_count': len(packages),
                'package_list': '\n'.join(pkg_lines) or '  (no detail)',
            }
            return 'secure_gateway_update_available', data

        if item_type == 'nvidia_xfree86':
            kind = update.get('_upgrade_kind')
            if kind == 'branch_upgrade':
                upgrade_reason = (
                    "Your current driver branch is no longer compatible with "
                    f"kernel {update.get('_kernel') or 'this kernel'}. "
                    "Switch to the recommended branch — the installer will "
                    "rebuild against the running kernel."
                )
            else:
                upgrade_reason = (
                    "Same-branch maintenance update with bug/security fixes."
                )
            data = {
                **common,
                'kernel': update.get('_kernel') or '',
                'upgrade_reason': upgrade_reason,
            }
            return 'nvidia_driver_update_available', data

        if item_type == 'coral_host':
            variant = update.get('_coral_variant') or item.get('_coral_variant') or ''
            if variant == 'pcie':
                variant_label = 'gasket-dkms (PCIe / M.2) driver'
                upgrade_reason = (
                    'feranick/gasket-driver has published a newer release. '
                    'The installer rebuilds the gasket + apex kernel modules '
                    'via DKMS against the running kernel.'
                )
                reboot_note = (
                    'Reinstalling rebuilds the DKMS module and requires a '
                    'reboot to load the new driver.'
                )
            elif variant == 'usb':
                pkg = update.get('_coral_pkg') or item.get('_coral_pkg') or 'libedgetpu1'
                variant_label = f'{pkg} runtime (USB Accelerator)'
                upgrade_reason = (
                    'A newer Edge TPU runtime is available from the Google '
                    'Coral apt repository.'
                )
                reboot_note = (
                    'The USB runtime upgrade does not require a reboot.'
                )
            else:
                variant_label = 'Coral TPU driver'
                upgrade_reason = 'A newer Coral driver is available.'
                reboot_note = ''
            data = {
                **common,
                'variant_label': variant_label,
                'upgrade_reason': upgrade_reason,
                'reboot_note': reboot_note,
            }
            return 'coral_driver_update_available', data

        # Unknown type — don't notify (keeps the queue clean if a
        # future detector lands without a corresponding event mapping).
        return '', {}

    # ── AI Model availability check ────────────────────────────

    def _check_ai_model_availability(self):
        """Check if configured AI model is still available (every 24h).
        
        If the model has been deprecated by the provider, automatically
        migrates to the best available fallback and notifies the admin.
        """
        now = time.time()
        if now - self._last_ai_model_check < self.AI_MODEL_CHECK_INTERVAL:
            return
        
        self._last_ai_model_check = now
        
        try:
            from notification_manager import notification_manager
            result = notification_manager.verify_and_update_ai_model()
            
            if result.get('migrated'):
                # Model was deprecated and migrated - notify admin
                old_model = result.get('old_model', 'unknown')
                new_model = result.get('new_model', 'unknown')
                
                event_data = {
                    'old_model': old_model,
                    'new_model': new_model,
                    'provider': notification_manager._config.get('ai_provider', 'unknown'),
                    'message': f"AI model '{old_model}' is no longer available. Automatically migrated to '{new_model}'.",
                }
                
                self._queue.put(NotificationEvent(
                    'ai_model_migrated', 'WARNING', event_data,
                    source='polling', entity='ai', entity_id='model',
                ))
                
                print(f"[PollingCollector] AI model migrated: {old_model} -> {new_model}")
                
        except ImportError:
            pass
        except Exception as e:
            print(f"[PollingCollector] AI model check failed: {e}")
    
    # ── Persistence helpers ────────────────────────────────────
    
    # Hard cap so the JSON serialised in `user_settings` stays bounded
    # even on hosts with many short-lived recurring errors.
    _KNOWN_ERRORS_MAX = 200
    _KNOWN_ERRORS_SETTING_KEY = 'pollingcollector_known_errors_v1'

    def _load_known_errors_meta(self):
        """Restore `_known_errors` from the persisted JSON snapshot.

        Pairs with `_save_known_errors_meta` — together they keep the
        before/after comparison accurate across service restarts so we
        don't lose recoveries that happened during downtime.
        """
        try:
            from health_persistence import health_persistence
            raw = health_persistence.get_setting(self._KNOWN_ERRORS_SETTING_KEY)
            if not raw:
                return
            data = json.loads(raw)
            if not isinstance(data, dict):
                return
            for ek, meta in data.items():
                if isinstance(meta, dict) and ek:
                    self._known_errors[ek] = meta
        except Exception as e:
            print(f"[PollingCollector] Failed to load known_errors meta: {e}")

    def _save_known_errors_meta(self):
        """Persist a JSON snapshot of `_known_errors` for next-restart use."""
        try:
            from health_persistence import health_persistence
            data = self._known_errors
            if len(data) > self._KNOWN_ERRORS_MAX:
                # Keep the most-recent entries by first_seen (best signal we
                # have of "which errors matter most right now").
                sorted_items = sorted(
                    data.items(),
                    key=lambda kv: kv[1].get('first_seen', '') or '',
                    reverse=True,
                )
                data = dict(sorted_items[: self._KNOWN_ERRORS_MAX])
            health_persistence.set_setting(
                self._KNOWN_ERRORS_SETTING_KEY,
                json.dumps(data, default=str),
            )
        except Exception as e:
            print(f"[PollingCollector] Failed to save known_errors meta: {e}")

    def _load_last_notified(self):
        """Load per-error notification timestamps from DB on startup.

        Reads only the per-key cooldown timestamps so the same-key
        24h gate survives a restart. **Does NOT touch `_known_errors`**
        — that snapshot is rebuilt exclusively by `_load_known_errors_meta`
        (which carries the full reason / category / severity payload
        needed to emit a meaningful recovery later).

        The original implementation also injected synthetic rows into
        `_known_errors` from this table, with `{'error_key': ek,
        'first_seen': <epoch int>}` and nothing else. That made the
        startup path believe the host had a populated baseline of
        active errors, so the first post-restart poll computed
        `resolved_keys = synthetic_dummies − current_keys` and emitted
        recovery notifications with empty `reason` / `category` /
        `severity` fields — the &ldquo;Resuelto -&rdquo; / &ldquo;Condición
        resuelta&rdquo; ghosts the user saw on 2026-05-21. Stale rows
        in this table never expire on their own (the bug was eternal:
        every restart re-triggered the ghost), so the fix is to never
        treat this table as a source of `_known_errors` content.
        """
        try:
            db_path = Path('/usr/local/share/proxmenux/health_monitor.db')
            if not db_path.exists():
                return
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT fingerprint, last_sent_ts FROM notification_last_sent "
                "WHERE fingerprint LIKE 'health_%'"
            )
            for fp, ts in cursor.fetchall():
                error_key = fp.replace('health_', '', 1)
                self._last_notified[error_key] = ts
            conn.close()
        except Exception as e:
            print(f"[PollingCollector] Failed to load last_notified: {e}")
    
    def _persist_last_notified(self, error_key: str, ts: float):
        """Save per-error notification timestamp to DB."""
        try:
            db_path = Path('/usr/local/share/proxmenux/health_monitor.db')
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            fp = f'health_{error_key}'
            conn.execute('''
                INSERT OR REPLACE INTO notification_last_sent (fingerprint, last_sent_ts, count)
                VALUES (?, ?, COALESCE(
                    (SELECT count + 1 FROM notification_last_sent WHERE fingerprint = ?), 1
                ))
            ''', (fp, int(ts), fp))
            conn.commit()
            conn.close()
        except Exception:
            pass
    
    def _get_cooldown_from_db(self, error_key: str) -> Optional[float]:
        """
        Get cooldown timestamp from DB for an error_key.
        
        Used to re-check DB when user might have dismissed the error,
        which clears the DB entry via health_persistence._clear_disk_io_cooldown().
        
        Returns the timestamp if found and within 24h window, None otherwise.
        """
        try:
            db_path = Path('/usr/local/share/proxmenux/health_monitor.db')
            if not db_path.exists():
                return None
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.execute('PRAGMA busy_timeout=3000')
            cursor = conn.cursor()
            
            # PollingCollector uses 'health_' prefix for its fingerprints
            fp = f'health_{error_key}'
            cursor.execute(
                "SELECT last_sent_ts FROM notification_last_sent WHERE fingerprint = ?",
                (fp,)
            )
            row = cursor.fetchone()
            conn.close()
            
            if row:
                ts = float(row[0])
                # Only return if within 24h window
                if time.time() - ts < self.SAME_ERROR_COOLDOWN:
                    return ts
            return None
        except Exception:
            return None


# ─── Proxmox Webhook Receiver ───────────────────────────────────

class ProxmoxHookWatcher:
    """Receives native Proxmox VE notifications via local webhook endpoint.
    
    Configured automatically via /etc/pve/notifications.cfg (endpoint +
    matcher blocks). The setup-webhook API writes these blocks on first
    enable. See flask_notification_routes.py for details.
    
    Payload varies by source (storage, replication, cluster, PBS, apt).
    This class normalizes them into NotificationEvent objects.
    """
    
    def __init__(self, event_queue: Queue):
        self._queue = event_queue
        # `_hostname` is exposed as a @property below so every read returns
        # the *current* alias from the settings DB (TTL-cached for 5 s in
        # _hostname()). The old `__init__`-time cache made a fresh Display
        # Name require a service restart to take effect.

    @property
    def _hostname(self) -> str:
        return _hostname()

    def process_webhook(self, payload: dict) -> dict:
        """Process an incoming Proxmox webhook payload.
        
        The PVE webhook is the PRIMARY source for vzdump, replication,
        fencing, package-updates and system-mail events.  PVE sends rich
        detail (full logs, sizes, durations) that TaskWatcher cannot match.
        
        Body template delivers:
          {title, message, severity, timestamp, fields: {type, hostname, job-id}}
        
        Returns: {'accepted': bool, 'event_type': str, 'event_id': str}
        """
        if not payload:
            return {'accepted': False, 'error': 'Empty payload'}
        
        # ── Extract structured PVE fields ──
        fields = payload.get('fields') or {}
        if isinstance(fields, str):
            # Edge case: {{ json fields }} rendered as string instead of dict
            try:
                import json
                fields = json.loads(fields)
            except (json.JSONDecodeError, ValueError):
                fields = {}
        
        pve_type = fields.get('type', '').lower().strip()
        pve_hostname = fields.get('hostname', self._hostname)
        pve_job_id = fields.get('job-id', '')
        
        title = payload.get('title', '')
        message = payload.get('message', payload.get('body', ''))
        severity_raw = payload.get('severity', 'info').lower().strip()
        timestamp = payload.get('timestamp', '')
        
        # ── Classify by PVE type (direct, no heuristics needed) ──
        import re
        event_type, entity, entity_id = self._classify_pve(
            pve_type, severity_raw, title, message
        )
        
        # Discard meta-events
        if event_type == '_skip':
            return {'accepted': False, 'skipped': True, 'reason': 'Meta-event filtered'}
        
        severity = self._map_severity(severity_raw)
        
        # ── Build rich data dict ──
        # For webhook events, PVE's `message` IS the notification body.
        # It contains full vzdump logs, package lists, error details, etc.
        # We pass it as 'pve_message' so templates can use it directly.
        data = {
            'hostname': pve_hostname,
            'pve_type': pve_type,
            'pve_message': message,
            'pve_title': title or event_type,
            'title': title or event_type,
            'job_id': pve_job_id,
        }
        
        # ── Extract clean reason for system-mail events ──
        # smartd and other system mail contains verbose boilerplate.
        # Extract just the actionable warning/error lines.
        if pve_type == 'system-mail' and message:
            clean_lines = []
            for line in message.split('\n'):
                stripped = line.strip()
                # Skip boilerplate lines
                if not stripped:
                    continue
                if stripped.startswith('This message was generated'):
                    continue
                if stripped.startswith('For details see'):
                    continue
                if stripped.startswith('You can also use'):
                    continue
                if stripped.startswith('The original message'):
                    continue
                if stripped.startswith('Another message will'):
                    continue
                if stripped.startswith('host name:') or stripped.startswith('DNS domain:'):
                    continue
                clean_lines.append(stripped)
            data['reason'] = '\n'.join(clean_lines).strip() if clean_lines else message.strip()[:500]
        
        # Extract VMID and VM name from message for vzdump events
        if pve_type == 'vzdump' and message:
            # PVE vzdump messages contain lines like:
            #   "INFO: Starting Backup of VM 100 (qemu)"
            #   "VMID       Name   Status   Time   Size   Filename"
            #   "100   arch-linux    OK    00:05:30   1.2G   /path/to/file"
            vmids = re.findall(r'(?:VM|CT)\s+(\d+)', message, re.IGNORECASE)
            if vmids:
                data['vmid'] = vmids[0]
                entity_id = vmids[0]
            # Try to extract VM name from the table line
            name_m = re.search(r'(\d+)\s+(\S+)\s+(?:OK|ERROR|WARNINGS)', message)
            if name_m:
                data['vmname'] = name_m.group(2)
            # Extract size from "Total size: X"
            size_m = re.search(r'Total size:\s*(.+?)(?:\n|$)', message)
            if size_m:
                data['size'] = size_m.group(1).strip()
            # Extract duration from "Total running time: X"
            dur_m = re.search(r'Total running time:\s*(.+?)(?:\n|$)', message)
            if dur_m:
                data['duration'] = dur_m.group(1).strip()
        
        # Capture journal context for critical/warning events (helps AI provide better context)
        if severity in ('CRITICAL', 'WARNING') and event_type not in ('backup_complete', 'update_available'):
            # Build keywords from available data for journal search
            keywords = ['error', 'fail', 'warning']
            if 'smartd' in message.lower() or 'smart' in title.lower():
                keywords.extend(['smartd', 'SMART', 'ata'])
            if pve_type == 'system-mail':
                keywords.append('smartd')
            if entity_id:
                keywords.append(entity_id)
            
            journal_ctx = capture_journal_context(keywords=keywords, lines=20)
            if journal_ctx:
                data['_journal_context'] = journal_ctx
        
        event = NotificationEvent(
            event_type=event_type,
            severity=severity,
            data=data,
            source='proxmox_hook',
            entity=entity,
            entity_id=entity_id,
            raw=payload,
        )
        
        self._queue.put(event)
        return {'accepted': True, 'event_type': event_type, 'event_id': event.event_id}
    
    def _classify_pve(self, pve_type: str, severity: str,
                      title: str, message: str) -> tuple:
        """Classify using PVE's structured fields.type.
        
        Returns (event_type, entity, entity_id).
        """
        title_lower = (title or '').lower()
        
        # Skip overall/updates status change meta-events
        if 'overall' in title_lower and ('changed' in title_lower or 'status' in title_lower):
            return '_skip', '', ''
        if 'updates' in title_lower and ('changed' in title_lower or 'status' in title_lower):
            return '_skip', '', ''
        
        # ── Direct classification by PVE type ──
        if pve_type == 'vzdump':
            if severity in ('error', 'err'):
                return 'backup_fail', 'vm', ''
            return 'backup_complete', 'vm', ''
        
        if pve_type == 'fencing':
            return 'split_brain', 'node', ''
        
        if pve_type == 'replication':
            return 'replication_fail', 'vm', ''
        
        if pve_type == 'package-updates':
            return 'update_available', 'node', ''
        
        if pve_type == 'system-mail':
            # Parse smartd messages to extract useful info and filter noise.
            # smartd sends system-mail when it detects SMART issues.
            msg_lower = (message or '').lower()
            title_lower_sm = (title or '').lower()
            
            # ── Record disk observation regardless of noise filter ──
            # Even "noise" events are recorded as observations so the user
            # can see them in the Storage UI.  We just don't send notifications.
            # Use the module-level helper because this method only exists on
            # JournalWatcher; calling it via `self` here raised AttributeError
            # on every PVE webhook with a smartd payload. See audit Tier 6 #2.
            _record_smartd_observation_impl(title or '', message or '')
            
            # ── Filter smartd noise (suppress notification, not observation) ──
            smartd_noise = [
                'failedreadsmarterrorlog',
                'failedreadsmartdata',
                'failedopendevice',  # drive was temporarily unavailable
            ]
            for noise in smartd_noise:
                if noise in title_lower_sm or noise in msg_lower:
                    return '_skip', '', ''
            
            return 'system_mail', 'node', ''
        
        # ── Fallback for unknown/empty pve_type ──
        # (e.g. test notifications, future PVE event types)
        msg_lower = (message or '').lower()
        text = f"{title_lower} {msg_lower}"
        
        if 'vzdump' in text or 'backup' in text:
            import re
            m = re.search(r'(?:vm|ct)\s+(\d+)', text, re.IGNORECASE)
            vmid = m.group(1) if m else ''
            if any(w in text for w in ('fail', 'error')):
                return 'backup_fail', 'vm', vmid
            return 'backup_complete', 'vm', vmid
        
        if 'replication' in text:
            return 'replication_fail', 'vm', ''
        
        # Generic fallback
        return 'system_problem', 'node', ''
    
    # Old _classify removed -- replaced by _classify_pve above.
    
    @staticmethod
    def _map_severity(raw: str) -> str:
        raw_l = str(raw).lower()
        if raw_l in ('critical', 'emergency', 'alert', 'crit', 'err', 'error'):
            return 'CRITICAL'
        if raw_l in ('warning', 'warn', 'notice'):
            return 'WARNING'
        return 'INFO'
