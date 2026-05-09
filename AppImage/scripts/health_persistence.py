"""
Health Monitor Persistence Module
Manages persistent error tracking across AppImage updates using SQLite.
Stores errors in /usr/local/share/proxmenux/health_monitor.db
(same directory as monitor.db for temperature history)

Features:
- Persistent error storage (survives AppImage updates)
- Smart error resolution (auto-clear when VM starts, or after 48h)
- Event system for future Telegram notifications
- Manual acknowledgment support

Author: MacRimi
Version: 1.1
"""

import sqlite3
import json
import os
import re
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

# `re` and `subprocess` are used in the SMART AUTO-RESOLVE block of
# `_cleanup_old_errors_impl` (qm/pct status calls + error_key parsing). They
# were not imported, so the entire auto-resolve loop hit NameError every 5
# minutes and got silently swallowed by the surrounding `except Exception:
# pass`. Audit Tier 5 (Health stack — imports faltantes).

import re as _re_disk_base


def disk_base_name(name):
    """Strip a partition suffix from a block device name, namespace-aware.

    The naive `re.sub(r'\\d+$', '', name)` was wrong for NVMe and MMC:
    - sda1         → sda          (correct)
    - nvme0n1      → nvme0n1      (already a base — its `n1` is the
                                   namespace, NOT a partition)
    - nvme0n1p1    → nvme0n1      (strip `pN` suffix)
    - mmcblk0p1    → mmcblk0
    - loop0p1      → loop0
    Audit Tier 7 — NVMe partitions regex.
    """
    if not isinstance(name, str) or not name:
        return name
    # Strip leading /dev/ if present so callers can pass either form.
    bare = name[len('/dev/'):] if name.startswith('/dev/') else name
    m = _re_disk_base.match(r'^(nvme\d+n\d+|mmcblk\d+|loop\d+)(?:p\d+)?$', bare)
    if m:
        return m.group(1)
    m = _re_disk_base.match(r'^([a-z]+)\d+$', bare)
    if m:
        return m.group(1)
    return bare


class HealthPersistence:
    """Manages persistent health error tracking"""
    
    # Default suppression duration when no user setting exists for a category.
    # Users override per-category via the Suppression Duration settings UI.
    DEFAULT_SUPPRESSION_HOURS = 24
    
    # Mapping from error categories to settings keys
    # `cpu` (cpu_usage in health_monitor.py:879/892) and `disk` (disk_space in
    # health_monitor.py:1240) were missing. Without them the per-category
    # suppression durations configured in the UI silently fall back to the
    # 24h default for those error types.
    CATEGORY_SETTING_MAP = {
        'temperature': 'suppress_cpu',
        'cpu': 'suppress_cpu',
        'memory': 'suppress_memory',
        'storage': 'suppress_storage',
        'disk': 'suppress_storage',
        'disks': 'suppress_disks',
        'network': 'suppress_network',
        'vms': 'suppress_vms',
        'pve_services': 'suppress_pve_services',
        'logs': 'suppress_logs',
        'updates': 'suppress_updates',
        'security': 'suppress_security',
    }
    
    def __init__(self):
        """Initialize persistence with database in shared ProxMenux data directory"""
        self.data_dir = Path('/usr/local/share/proxmenux')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_path = self.data_dir / 'health_monitor.db'
        self._db_lock = threading.Lock()
        self._init_database()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get a SQLite connection with timeout and WAL mode for safe concurrency.

        IMPORTANT: Always close the connection when done, preferably using
        the _db_connection() context manager. If not closed explicitly,
        Python's GC will close it, but this is unreliable under load.
        """
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=10000')
        return conn
    
    @contextmanager
    def _db_connection(self, row_factory: bool = False):
        """Context manager for safe database connections (B4 fix).
        
        Ensures connections are always closed, even if exceptions occur.
        Usage:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                ...
        """
        conn = self._get_conn()
        if row_factory:
            conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_database(self):
        """Initialize SQLite database with required tables"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
        except Exception as e:
            print(f"[HealthPersistence] CRITICAL: Failed to connect to database: {e}")
            return
        
        print(f"[HealthPersistence] Initializing database at {self.db_path}")
        
        # Errors table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_key TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                reason TEXT NOT NULL,
                details TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                resolved_at TEXT,
                resolution_type TEXT,
                resolution_reason TEXT,
                acknowledged INTEGER DEFAULT 0,
                acknowledged_at TEXT,
                notification_sent INTEGER DEFAULT 0,
                occurrence_count INTEGER DEFAULT 1,
                suppression_hours INTEGER DEFAULT 24
            )
        ''')
        
        # Events table (for future Telegram notifications)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                error_key TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT
            )
        ''')
        
        # System capabilities table (detected once, cached forever)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_capabilities (
                cap_key TEXT PRIMARY KEY,
                cap_value TEXT NOT NULL,
                detected_at TEXT NOT NULL
            )
        ''')
        
        # User settings table (per-category suppression durations, etc.)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        
        # Notification history table (records all sent notifications)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                channel TEXT NOT NULL,
                title TEXT,
                message TEXT,
                severity TEXT,
                sent_at TEXT NOT NULL,
                success INTEGER DEFAULT 1,
                error_message TEXT,
                source TEXT DEFAULT 'server'
            )
        ''')
        
        # Notification cooldown persistence (survives restarts)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_last_sent (
                fingerprint TEXT PRIMARY KEY,
                last_sent_ts INTEGER NOT NULL,
                count INTEGER DEFAULT 1
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS digest_pending (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_group TEXT NOT NULL,
                severity TEXT NOT NULL,
                ts INTEGER NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL
            )
        ''')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_digest_pending_channel '
            'ON digest_pending(channel, ts)'
        )
        
        # Migration: add missing columns to errors table for existing DBs
        cursor.execute("PRAGMA table_info(errors)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'suppression_hours' not in columns:
            cursor.execute('ALTER TABLE errors ADD COLUMN suppression_hours INTEGER DEFAULT 24')
        
        if 'acknowledged_at' not in columns:
            cursor.execute('ALTER TABLE errors ADD COLUMN acknowledged_at TEXT')
        
        if 'occurrence_count' not in columns:
            cursor.execute('ALTER TABLE errors ADD COLUMN occurrence_count INTEGER DEFAULT 1')
        
        if 'resolution_type' not in columns:
            cursor.execute('ALTER TABLE errors ADD COLUMN resolution_type TEXT')
        
        if 'resolution_reason' not in columns:
            cursor.execute('ALTER TABLE errors ADD COLUMN resolution_reason TEXT')
        
        # Indexes for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_error_key ON errors(error_key)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON errors(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_resolved ON errors(resolved_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_error ON events(error_key)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notif_sent_at ON notification_history(sent_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notif_severity ON notification_history(severity)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_nls_ts ON notification_last_sent(last_sent_ts)')
        
        # ── Disk Observations System ──
        # Registry of all physical disks seen by the system
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS disk_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_name TEXT NOT NULL,
                serial TEXT,
                model TEXT,
                size_bytes INTEGER,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                removed INTEGER DEFAULT 0,
                worst_health TEXT DEFAULT 'healthy',
                worst_health_date TEXT,
                admin_cleared TEXT,
                UNIQUE(device_name, serial)
            )
        ''')
        
        # Migration: add worst_health columns if they don't exist (for existing DBs)
        try:
            cursor.execute('ALTER TABLE disk_registry ADD COLUMN worst_health TEXT DEFAULT "healthy"')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE disk_registry ADD COLUMN worst_health_date TEXT')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE disk_registry ADD COLUMN admin_cleared TEXT')
        except Exception:
            pass
        
        # Observation log: deduplicated error events per disk
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS disk_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                disk_registry_id INTEGER NOT NULL,
                error_type TEXT NOT NULL,
                error_signature TEXT NOT NULL,
                first_occurrence TEXT NOT NULL,
                last_occurrence TEXT NOT NULL,
                occurrence_count INTEGER DEFAULT 1,
                raw_message TEXT,
                severity TEXT DEFAULT 'warning',
                dismissed INTEGER DEFAULT 0,
                FOREIGN KEY(disk_registry_id) REFERENCES disk_registry(id),
                UNIQUE(disk_registry_id, error_type, error_signature)
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_disk_serial ON disk_registry(serial)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_disk_device ON disk_registry(device_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_obs_disk ON disk_observations(disk_registry_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_obs_dismissed ON disk_observations(dismissed)')
        
        # Migration: ensure disk_observations has all required columns
        # Some older DBs may have different column names or missing columns
        cursor.execute('PRAGMA table_info(disk_observations)')
        obs_columns = [col[1] for col in cursor.fetchall()]
        
        # Add missing columns if needed (SQLite doesn't support RENAME COLUMN in older versions)
        if 'error_type' not in obs_columns and 'observation_type' in obs_columns:
            # Old schema had observation_type, but we'll work with it as-is
            pass  # The code should handle both column names
        
        if 'first_occurrence' not in obs_columns and 'first_seen' in obs_columns:
            # Old schema had first_seen/last_seen instead of first_occurrence/last_occurrence
            pass  # The code should handle both column names
        
        if 'occurrence_count' not in obs_columns:
            try:
                cursor.execute('ALTER TABLE disk_observations ADD COLUMN occurrence_count INTEGER DEFAULT 1')
            except Exception:
                pass
        
        if 'raw_message' not in obs_columns:
            try:
                cursor.execute('ALTER TABLE disk_observations ADD COLUMN raw_message TEXT')
            except Exception:
                pass
        
        if 'severity' not in obs_columns:
            try:
                cursor.execute('ALTER TABLE disk_observations ADD COLUMN severity TEXT DEFAULT "warning"')
            except Exception:
                pass
        
        if 'dismissed' not in obs_columns:
            try:
                cursor.execute('ALTER TABLE disk_observations ADD COLUMN dismissed INTEGER DEFAULT 0')
            except Exception:
                pass
        
        # ── Remote Storage Exclusions System ──
        # Allows users to permanently exclude remote storages (PBS, NFS, CIFS, etc.)
        # from health monitoring and notifications
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS excluded_storages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                storage_name TEXT UNIQUE NOT NULL,
                storage_type TEXT NOT NULL,
                excluded_at TEXT NOT NULL,
                exclude_health INTEGER DEFAULT 1,
                exclude_notifications INTEGER DEFAULT 1,
                reason TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_excluded_storage ON excluded_storages(storage_name)')
        
        # Table for excluded network interfaces - allows users to exclude interfaces 
        # (like intentionally disabled bridges) from health monitoring and notifications
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS excluded_interfaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interface_name TEXT UNIQUE NOT NULL,
                interface_type TEXT NOT NULL,
                excluded_at TEXT NOT NULL,
                exclude_health INTEGER DEFAULT 1,
                exclude_notifications INTEGER DEFAULT 1,
                reason TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_excluded_interface ON excluded_interfaces(interface_name)')
        
        conn.commit()
        
        # Verify all required tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        required_tables = {'errors', 'events', 'system_capabilities', 'user_settings', 
                          'notification_history', 'notification_last_sent', 
                          'disk_registry', 'disk_observations', 
                          'excluded_storages', 'excluded_interfaces'}
        missing = required_tables - tables
        if missing:
            print(f"[HealthPersistence] WARNING: Missing tables after init: {missing}")
        else:
            print(f"[HealthPersistence] Database initialized with {len(tables)} tables")

        # ─── Startup migration: clean stale errors from previous bug ───
        # Previous versions had a bug where journal-based errors were
        # re-processed every cycle, causing infinite notification loops.
        # The cleanup wipes any stale entries left over from that buggy
        # behaviour, but it must run **only once per upgrade**, not on every
        # restart. Otherwise a real, ongoing failure (a disk dying for two+
        # hours while the host is rebooted) loses its `first_seen` history
        # and looks "new" again on the next boot. Audit Tier 5 — Health stack.
        #
        # IMPORTANT: Only cleans the `errors` table (health monitor state).
        # The `disk_observations` table is a PERMANENT historical record
        # and must NEVER be auto-modified on startup. Users dismiss
        # observations manually from the disk detail UI.
        #
        # Covers: disk I/O (smart_*, disk_*), VM/CT (vm_*, ct_*, vmct_*),
        # and log errors (log_*) — all journal-sourced categories.
        _STARTUP_CLEANUP_VERSION = '1'
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT setting_value FROM user_settings WHERE setting_key = ?',
                ('startup_cleanup_version',)
            )
            row = cursor.fetchone()
            already_run = row and row[0] == _STARTUP_CLEANUP_VERSION

            if not already_run:
                cutoff = (datetime.now() - timedelta(hours=2)).isoformat()
                cursor.execute('''
                    DELETE FROM errors
                    WHERE (   error_key LIKE 'smart_%'
                           OR error_key LIKE 'disk_%'
                           OR error_key LIKE 'vm_%'
                           OR error_key LIKE 'ct_%'
                           OR error_key LIKE 'vmct_%'
                           OR error_key LIKE 'log_%'
                          )
                      AND resolved_at IS NULL
                      AND acknowledged = 0
                      AND last_seen < ?
                ''', (cutoff,))
                cleaned_errors = cursor.rowcount

                cursor.execute('''
                    INSERT OR REPLACE INTO user_settings
                        (setting_key, setting_value, updated_at)
                    VALUES (?, ?, ?)
                ''', ('startup_cleanup_version', _STARTUP_CLEANUP_VERSION,
                      datetime.now().isoformat()))

                conn.commit()
                if cleaned_errors > 0:
                    print(f"[HealthPersistence] One-time startup cleanup (v{_STARTUP_CLEANUP_VERSION}): "
                          f"removed {cleaned_errors} stale error(s) from health monitor")
        except Exception as e:
            print(f"[HealthPersistence] Startup cleanup warning: {e}")

        conn.close()
    
    def record_error(self, error_key: str, category: str, severity: str, 
                    reason: str, details: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Record or update an error.
        Returns event info (new_error, updated, etc.)
        """
        with self._db_lock:
            return self._record_error_impl(error_key, category, severity, reason, details)
    
    def _record_error_impl(self, error_key, category, severity, reason, details):
        # === RESOURCE EXISTENCE CHECK (before DB access) ===
        # Skip recording errors for resources that no longer exist
        if error_key and (error_key.startswith(('vm_', 'ct_', 'vmct_'))):
            import re
            vmid_match = re.search(r'(?:vm_|ct_|vmct_)(\d+)', error_key)
            if vmid_match:
                vmid = vmid_match.group(1)
                if not self._check_vm_ct_exists(vmid):
                    return {'type': 'skipped', 'needs_notification': False,
                            'reason': f'VM/CT {vmid} no longer exists'}

        if error_key and any(error_key.startswith(p) for p in ('smart_', 'disk_', 'io_error_')):
            import re
            import os
            disk_match = re.search(r'(?:smart_|disk_fs_|disk_|io_error_)(?:/dev/)?([a-z]{2,4}[a-z0-9]*)', error_key)
            if disk_match:
                disk_name = disk_match.group(1)
                base_disk = disk_base_name(disk_name)
                if not os.path.exists(f'/dev/{disk_name}') and not os.path.exists(f'/dev/{base_disk}'):
                    return {'type': 'skipped', 'needs_notification': False,
                            'reason': f'Disk /dev/{disk_name} no longer exists'}

        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            details_json = json.dumps(details) if details else None

            cursor.execute('''
                SELECT id, acknowledged, resolved_at, category, severity, first_seen,
                       notification_sent, suppression_hours, acknowledged_at
                FROM errors WHERE error_key = ?
            ''', (error_key,))
            existing = cursor.fetchone()

            event_info = {'type': 'updated', 'needs_notification': False}

            if existing:
                (err_id, ack, resolved_at, old_cat, old_severity, first_seen,
                 notif_sent, stored_suppression, acknowledged_at) = existing

                if ack == 1:
                    # SAFETY OVERRIDE: Critical CPU temperature ALWAYS re-triggers
                    if error_key == 'cpu_temperature' and severity == 'CRITICAL':
                        cursor.execute('DELETE FROM errors WHERE error_key = ?', (error_key,))
                        cursor.execute('''
                            INSERT INTO errors
                            (error_key, category, severity, reason, details, first_seen, last_seen)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (error_key, category, severity, reason, details_json, now, now))
                        event_info = {'type': 'new', 'needs_notification': True}
                        self._record_event(cursor, 'new', error_key,
                                          {'severity': severity, 'reason': reason,
                                           'note': 'CRITICAL temperature override - safety alert'})
                        conn.commit()
                        return event_info

                    # Check suppression: use per-record stored hours (set at dismiss time)
                    sup_hours = stored_suppression if stored_suppression is not None else self.DEFAULT_SUPPRESSION_HOURS

                    # Permanent dismiss (sup_hours == -1): always suppress
                    if sup_hours == -1:
                        return {'type': 'skipped_acknowledged', 'needs_notification': False}

                    # Time-limited suppression. Prefer `acknowledged_at` as the
                    # reference time — that's what the user-dismiss path writes.
                    # `_acknowledge_error_impl` does NOT touch `resolved_at`, so
                    # falling through to the resolved_at-only check broke the
                    # dismiss for ALL non-journal categories (vms, services,
                    # cpu/memory, network, storage, security, updates): the
                    # detector re-fires every 5 min and the suppression window
                    # never starts. Audit Tier 5 (Health stack — `_record_error_impl`).
                    ref_time_str = acknowledged_at or resolved_at
                    still_suppressed = False
                    if ref_time_str:
                        try:
                            ref_dt = datetime.fromisoformat(ref_time_str)
                            elapsed_hours = (datetime.now() - ref_dt).total_seconds() / 3600
                            still_suppressed = elapsed_hours < sup_hours
                        except Exception:
                            pass

                    if still_suppressed:
                        return {'type': 'skipped_acknowledged', 'needs_notification': False}

                    # Suppression expired — re-trigger uniformly across categories.
                    # Previous code special-cased journal-sourced errors (logs/smart/
                    # disk/io_error) with a DELETE-without-INSERT workaround to dodge
                    # an infinite-notification loop. That loop was a symptom of the
                    # `acknowledged_at` bug fixed in Sprint 7.7 — without it,
                    # suppression never actually started and every cycle re-triggered.
                    # With suppression honoring acknowledged_at, the legitimate
                    # behavior is: when the window expires AND the underlying
                    # condition is still present in the journal, raise it once and
                    # let the user re-dismiss if they want.
                    cursor.execute('DELETE FROM errors WHERE error_key = ?', (error_key,))
                    cursor.execute('''
                        INSERT INTO errors
                        (error_key, category, severity, reason, details, first_seen, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (error_key, category, severity, reason, details_json, now, now))
                    event_info = {'type': 'new', 'needs_notification': True}
                    self._record_event(cursor, 'new', error_key,
                                      {'severity': severity, 'reason': reason,
                                       'note': 'Re-triggered after suppression expired'})
                    conn.commit()
                    return event_info

                # Not acknowledged - update existing active error
                cursor.execute('''
                    UPDATE errors
                    SET last_seen = ?, severity = ?, reason = ?, details = ?
                    WHERE error_key = ? AND acknowledged = 0
                ''', (now, severity, reason, details_json, error_key))

                # Check if severity escalated
                if old_severity == 'WARNING' and severity == 'CRITICAL':
                    event_info['type'] = 'escalated'
                    event_info['needs_notification'] = True
            else:
                # Insert new error
                cursor.execute('''
                    INSERT INTO errors
                    (error_key, category, severity, reason, details, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (error_key, category, severity, reason, details_json, now, now))

                event_info['type'] = 'new'
                event_info['needs_notification'] = True

            # ─── Auto-suppress: if the category has a non-default setting, ───
            if not (error_key == 'cpu_temperature' and severity == 'CRITICAL'):
                setting_key = self.CATEGORY_SETTING_MAP.get(category, '')
                if setting_key:
                    stored = self._get_setting_impl(conn, setting_key)
                    if stored is not None:
                        configured_hours = int(stored)
                        if configured_hours != self.DEFAULT_SUPPRESSION_HOURS:
                            cursor.execute('''
                                UPDATE errors
                                SET acknowledged = 1, acknowledged_at = ?, suppression_hours = ?
                                WHERE error_key = ? AND acknowledged = 0
                            ''', (now, configured_hours, error_key))

                            if cursor.rowcount > 0:
                                self._record_event(cursor, 'auto_suppressed', error_key, {
                                    'severity': severity,
                                    'reason': reason,
                                    'suppression_hours': configured_hours,
                                    'note': 'Auto-suppressed by user settings'
                                })
                                event_info['type'] = 'auto_suppressed'
                                event_info['needs_notification'] = False
                                conn.commit()
                                return event_info

            # Record event
            self._record_event(cursor, event_info['type'], error_key,
                              {'severity': severity, 'reason': reason})

            conn.commit()
        finally:
            conn.close()
        
        return event_info
    
    def resolve_error(self, error_key: str, reason: str = 'auto-resolved'):
        """Mark an error as resolved"""
        with self._db_lock:
            return self._resolve_error_impl(error_key, reason)
    
    def _resolve_error_impl(self, error_key, reason):
        with self._db_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute('''
                UPDATE errors
                SET resolved_at = ?
                WHERE error_key = ? AND resolved_at IS NULL
            ''', (now, error_key))

            if cursor.rowcount > 0:
                self._record_event(cursor, 'resolved', error_key, {'reason': reason})

            conn.commit()
    
    def is_error_active(self, error_key: str, category: Optional[str] = None) -> bool:
        """
        Check if an error is currently active OR suppressed (dismissed but within suppression period).
        Used by checks to avoid re-recording errors that are already tracked or dismissed.
        
        Returns True if:
        - Error is active (unresolved and not acknowledged), OR
        - Error is dismissed but still within its suppression period
        """
        with self._db_connection() as conn:
            cursor = conn.cursor()
            
            # First check: is the error active (unresolved and not acknowledged)?
            if category:
                cursor.execute('''
                    SELECT COUNT(*) FROM errors 
                    WHERE error_key = ? AND category = ?
                      AND resolved_at IS NULL AND acknowledged = 0
                ''', (error_key, category))
            else:
                cursor.execute('''
                    SELECT COUNT(*) FROM errors 
                    WHERE error_key = ? 
                      AND resolved_at IS NULL AND acknowledged = 0
                ''', (error_key,))
            
            active_count = cursor.fetchone()[0]
            if active_count > 0:
                return True
            
            # Second check: is the error dismissed but still within suppression period?
            # This prevents re-recording dismissed errors before their suppression expires
            # Note: acknowledged errors may have resolved_at NULL (dismissed but error still exists)
            # or resolved_at set (error was dismissed AND condition resolved)
            if category:
                cursor.execute('''
                    SELECT acknowledged_at, suppression_hours FROM errors 
                    WHERE error_key = ? AND category = ?
                      AND acknowledged = 1
                    ORDER BY acknowledged_at DESC LIMIT 1
                ''', (error_key, category))
            else:
                cursor.execute('''
                    SELECT acknowledged_at, suppression_hours FROM errors 
                    WHERE error_key = ?
                      AND acknowledged = 1
                    ORDER BY acknowledged_at DESC LIMIT 1
                ''', (error_key,))
            
            row = cursor.fetchone()
        
        if row:
            acknowledged_at_str, suppression_hours = row
            if acknowledged_at_str and suppression_hours:
                try:
                    acknowledged_at = datetime.fromisoformat(acknowledged_at_str)
                    suppression_end = acknowledged_at + timedelta(hours=suppression_hours)
                    if datetime.now() < suppression_end:
                        # Still within suppression period - treat as "active" to prevent re-recording
                        return True
                except (ValueError, TypeError):
                    pass
        
        return False
    
    def clear_error(self, error_key: str):
        """
        Remove/resolve a specific error immediately.
        Used when the condition that caused the error no longer exists
        (e.g., storage became available again, CPU temp recovered).

        For acknowledged errors: if the condition resolved on its own,
        we delete the record entirely so it can re-trigger as a fresh
        event if the condition returns later.

        Acquires `_db_lock` to serialize against concurrent record/cleanup
        writes — without it, SQLite's WAL still serializes the actual write,
        but read-modify-write sequences (the SELECT acknowledged + DELETE/UPDATE
        pair below) could race with another thread mutating the same row in
        between. Audit Tier 5 (Health stack — race conditions sin _db_lock).
        """
        with self._db_lock, self._db_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            # Check if this error was acknowledged (dismissed)
            cursor.execute('''
                SELECT acknowledged FROM errors WHERE error_key = ?
            ''', (error_key,))
            row = cursor.fetchone()

            if row and row[0] == 1:
                # Dismissed error that naturally resolved - delete entirely
                cursor.execute('DELETE FROM errors WHERE error_key = ?', (error_key,))
                if cursor.rowcount > 0:
                    self._record_event(cursor, 'cleared', error_key,
                                      {'reason': 'condition_resolved_after_dismiss'})
            else:
                # Normal active error - mark as resolved
                cursor.execute('''
                    UPDATE errors
                    SET resolved_at = ?
                    WHERE error_key = ? AND resolved_at IS NULL
                ''', (now, error_key))

                if cursor.rowcount > 0:
                    self._record_event(cursor, 'cleared', error_key, {'reason': 'condition_resolved'})

            conn.commit()
    
    def acknowledge_error(self, error_key: str) -> Dict[str, Any]:
        """
        Manually acknowledge an error (dismiss).
        - Looks up the category's configured suppression duration from user settings
        - Stores suppression_hours on the error record (snapshot at dismiss time)
        - Marks as acknowledged so it won't re-appear during the suppression period
        """
        with self._db_lock:
            return self._acknowledge_error_impl(error_key)
    
    def _acknowledge_error_impl(self, error_key):
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        category = ''
        sup_hours = self.DEFAULT_SUPPRESSION_HOURS
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            # Get current error info before acknowledging
            cursor.execute('SELECT * FROM errors WHERE error_key = ?', (error_key,))
            row = cursor.fetchone()

            result = {'success': False, 'error_key': error_key}

            if not row:
                # Error not in DB yet -- create a minimal record so the dismiss persists.
                # Try to infer category from the error_key prefix.
                category = ''
                # Order matters: more specific prefixes MUST come before shorter ones
                # e.g. 'security_updates' (updates) before 'security_' (security)
                for cat, prefix in [('updates', 'security_updates'), ('updates', 'system_age'),
                                    ('updates', 'pending_updates'), ('updates', 'kernel_pve'),
                                    ('security', 'security_'),
                                    ('pve_services', 'pve_service_'), ('vms', 'vmct_'), ('vms', 'vm_'), ('vms', 'ct_'),
                                    ('disks', 'disk_smart_'), ('disks', 'disk_'), ('disks', 'smart_'), ('disks', 'zfs_pool_'),
                                    ('logs', 'log_'), ('network', 'net_'),
                                    ('temperature', 'temp_')]:
                    if error_key == prefix or error_key.startswith(prefix):
                        category = cat
                        break

                # Fallback: if no category matched, try to infer from common patterns
                if not category:
                    if 'disk' in error_key or 'smart' in error_key or 'sda' in error_key or 'sdb' in error_key or 'nvme' in error_key:
                        category = 'disks'
                    else:
                        category = 'general'

                setting_key = self.CATEGORY_SETTING_MAP.get(category, '')
                sup_hours = self.DEFAULT_SUPPRESSION_HOURS
                if setting_key:
                    stored = self._get_setting_impl(conn, setting_key)
                    if stored is not None:
                        try:
                            sup_hours = int(stored)
                        except (ValueError, TypeError):
                            pass

                # Insert as acknowledged but NOT resolved - error remains active
                cursor.execute('''
                    INSERT INTO errors (error_key, category, severity, reason, first_seen, last_seen,
                                        occurrence_count, acknowledged, acknowledged_at, suppression_hours)
                    VALUES (?, ?, 'WARNING', 'Dismissed by user', ?, ?, 1, 1, ?, ?)
                ''', (error_key, category, now, now, now, sup_hours))

                self._record_event(cursor, 'acknowledged', error_key, {
                    'original_severity': 'WARNING',
                    'category': category,
                    'suppression_hours': sup_hours
                })

                result = {
                    'success': True,
                    'error_key': error_key,
                    'original_severity': 'WARNING',
                    'category': category,
                    'suppression_hours': sup_hours,
                    'acknowledged_at': now
                }
                conn.commit()
                return result

            if row:
                error_dict = dict(row)
                original_severity = error_dict.get('severity', 'WARNING')
                category = error_dict.get('category', '')

                # Look up the user's configured suppression for this category
                setting_key = self.CATEGORY_SETTING_MAP.get(category, '')
                sup_hours = self.DEFAULT_SUPPRESSION_HOURS
                if setting_key:
                    stored = self._get_setting_impl(conn, setting_key)
                    if stored is not None:
                        try:
                            sup_hours = int(stored)
                        except (ValueError, TypeError):
                            pass

                # Mark as acknowledged but DO NOT set resolved_at
                cursor.execute('''
                    UPDATE errors
                    SET acknowledged = 1, acknowledged_at = ?, suppression_hours = ?
                    WHERE error_key = ?
                ''', (now, sup_hours, error_key))

                self._record_event(cursor, 'acknowledged', error_key, {
                    'original_severity': original_severity,
                    'category': category,
                    'suppression_hours': sup_hours
                })

                # Cascade acknowledge: when dismissing a group check, also
                # silence the individual children that compose it. Without
                # this, dismissing the aggregate ("an avalanche of log errors")
                # left the per-pattern children active and notifying separately.
                # `log_error_cascade` and `log_error_spike` both group children
                # of the form `log_critical_<hash>` (see _check_logs_with_persistence).
                CASCADE_PREFIXES = {
                    'log_persistent_errors': 'log_persistent_',
                    'log_error_cascade': 'log_critical_',
                    'log_error_spike': 'log_critical_',
                }
                child_prefix = CASCADE_PREFIXES.get(error_key)
                if child_prefix:
                    cursor.execute('''
                        UPDATE errors
                        SET acknowledged = 1, acknowledged_at = ?, suppression_hours = ?
                        WHERE error_key LIKE ? AND acknowledged = 0 AND resolved_at IS NULL
                    ''', (now, sup_hours, child_prefix + '%'))

                result = {
                    'success': True,
                    'error_key': error_key,
                    'original_severity': original_severity,
                    'category': category,
                    'acknowledged_at': now,
                    'suppression_hours': sup_hours
                }

            conn.commit()
        finally:
            conn.close()

        # ── Coordinate with notification cooldowns ──
        if sup_hours != -1:
            if category == 'disks':
                self._clear_disk_io_cooldown(error_key)
            else:
                self._clear_notification_cooldown(error_key)

        return result
    
    def is_error_acknowledged(self, error_key: str) -> bool:
        """Check if an error_key has been acknowledged and is still within suppression window.
        
        Uses acknowledged_at (not resolved_at) to calculate suppression expiration,
        since dismissed errors may have resolved_at = NULL.
        """
        try:
            with self._db_connection(row_factory=True) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT acknowledged, acknowledged_at, suppression_hours FROM errors WHERE error_key = ?',
                    (error_key,))
                row = cursor.fetchone()
                if not row:
                    return False
                if not row['acknowledged']:
                    return False
                # Check if still within suppression window using acknowledged_at
                acknowledged_at = row['acknowledged_at']
                sup_hours = row['suppression_hours'] or self.DEFAULT_SUPPRESSION_HOURS
                
                # -1 means permanently suppressed
                if sup_hours < 0:
                    return True
                
                if acknowledged_at:
                    try:
                        acknowledged_dt = datetime.fromisoformat(acknowledged_at)
                        if datetime.now() > acknowledged_dt + timedelta(hours=sup_hours):
                            return False  # Suppression expired
                    except Exception:
                        pass
                return True
        except Exception:
            return False
    
    def get_active_errors(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all active (unresolved AND not acknowledged) errors, optionally filtered by category.
        
        Acknowledged errors are excluded since they have been dismissed by the user.
        """
        with self._db_connection(row_factory=True) as conn:
            cursor = conn.cursor()
            
            if category:
                cursor.execute('''
                    SELECT * FROM errors 
                    WHERE resolved_at IS NULL AND acknowledged = 0 AND category = ?
                    ORDER BY severity DESC, last_seen DESC
                ''', (category,))
            else:
                cursor.execute('''
                    SELECT * FROM errors 
                    WHERE resolved_at IS NULL AND acknowledged = 0
                    ORDER BY severity DESC, last_seen DESC
                ''')
            
            rows = cursor.fetchall()
        
        errors = []
        for row in rows:
            error_dict = dict(row)
            if error_dict.get('details'):
                error_dict['details'] = json.loads(error_dict['details'])
            errors.append(error_dict)
        
        return errors
    
    def get_error_by_key(self, error_key: str) -> Optional[Dict[str, Any]]:
        """Get a single error record by its unique error_key.
        
        Returns the full row as a dict (including first_seen, last_seen,
        acknowledged, etc.) or None if not found / already resolved.
        Only returns unresolved (active) errors.
        """
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM errors
            WHERE error_key = ? AND resolved_at IS NULL
            LIMIT 1
        ''', (error_key,))
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        error_dict = dict(row)
        if error_dict.get('details'):
            try:
                error_dict['details'] = json.loads(error_dict['details'])
            except (json.JSONDecodeError, TypeError):
                pass
        return error_dict
    
    def cleanup_old_errors(self):
        """Clean up old resolved errors and auto-resolve stale errors"""
        with self._db_lock:
            return self._cleanup_old_errors_impl()
    
    def _cleanup_old_errors_impl(self):
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            now = datetime.now()
            now_iso = now.isoformat()

            # Delete resolved errors older than 7 days
            cutoff_resolved = (now - timedelta(days=7)).isoformat()
            cursor.execute('DELETE FROM errors WHERE resolved_at < ?', (cutoff_resolved,))

            # ── Auto-resolve stale errors using Suppression Duration settings ──
            user_settings = {}
            try:
                cursor.execute(
                    'SELECT setting_key, setting_value FROM user_settings WHERE setting_key LIKE ?',
                    ('suppress_%',)
                )
                for row in cursor.fetchall():
                    user_settings[row[0]] = row[1]
            except Exception:
                pass

            for category, setting_key in self.CATEGORY_SETTING_MAP.items():
                stored = user_settings.get(setting_key)
                try:
                    hours = int(stored) if stored else self.DEFAULT_SUPPRESSION_HOURS
                except (ValueError, TypeError):
                    hours = self.DEFAULT_SUPPRESSION_HOURS

                if hours < 0:
                    continue

                cutoff = (now - timedelta(hours=hours)).isoformat()
                cursor.execute('''
                    UPDATE errors
                    SET resolved_at = ?
                    WHERE category = ?
                      AND resolved_at IS NULL
                      AND last_seen < ?
                      AND acknowledged = 0
                ''', (now_iso, category, cutoff))

            # Catch-all: auto-resolve any error from an unmapped category
            fallback_cutoff = (now - timedelta(hours=self.DEFAULT_SUPPRESSION_HOURS)).isoformat()
            cursor.execute('''
                UPDATE errors
                SET resolved_at = ?
                WHERE resolved_at IS NULL
                  AND acknowledged = 0
                  AND last_seen < ?
            ''', (now_iso, fallback_cutoff))

            # Delete old events (>30 days)
            cutoff_events = (now - timedelta(days=30)).isoformat()
            cursor.execute('DELETE FROM events WHERE timestamp < ?', (cutoff_events,))
        
            # ── SMART AUTO-RESOLVE: Based on system state ──
            try:
                import psutil
                with open('/proc/uptime', 'r') as f:
                    uptime_seconds = float(f.read().split()[0])

                if uptime_seconds > 600:
                    current_cpu = psutil.cpu_percent(interval=0.1)
                    current_mem = psutil.virtual_memory().percent

                    # 1. LOGS: Auto-resolve if not seen in 15 minutes
                    stale_logs_cutoff = (now - timedelta(minutes=15)).isoformat()
                    cursor.execute('''
                        UPDATE errors SET resolved_at = ?
                        WHERE category = 'logs' AND resolved_at IS NULL
                          AND acknowledged = 0 AND last_seen < ?
                    ''', (now_iso, stale_logs_cutoff))

                    # 2. CPU: Auto-resolve if CPU is normal (<75%)
                    if current_cpu < 75:
                        stale_cpu_cutoff = (now - timedelta(minutes=5)).isoformat()
                        cursor.execute('''
                            UPDATE errors SET resolved_at = ?
                            WHERE (category = 'cpu' OR category = 'temperature')
                              AND resolved_at IS NULL AND acknowledged = 0
                              AND last_seen < ?
                              AND (error_key LIKE 'cpu_%' OR reason LIKE '%CPU%')
                        ''', (now_iso, stale_cpu_cutoff))

                    # 3. MEMORY: Auto-resolve if memory is normal (<80%)
                    if current_mem < 80:
                        stale_mem_cutoff = (now - timedelta(minutes=5)).isoformat()
                        cursor.execute('''
                            UPDATE errors SET resolved_at = ?
                            WHERE (category = 'memory' OR category = 'logs')
                              AND resolved_at IS NULL AND acknowledged = 0
                              AND last_seen < ?
                              AND (error_key LIKE '%oom%' OR error_key LIKE '%memory%'
                                   OR reason LIKE '%memory%' OR reason LIKE '%OOM%'
                                   OR reason LIKE '%killed%process%')
                        ''', (now_iso, stale_mem_cutoff))

                    # 4. VMS: Auto-resolve if VM/CT is now running or deleted
                    cursor.execute('''
                        SELECT error_key, category, reason FROM errors
                        WHERE (category IN ('vms', 'vmct') OR error_key LIKE 'vm_%'
                               OR error_key LIKE 'ct_%' OR error_key LIKE 'vmct_%')
                          AND resolved_at IS NULL AND acknowledged = 0
                    ''')
                    vm_errors = cursor.fetchall()
                    for vm_ek, cat, vm_reason in vm_errors:
                        vmid_match = re.search(r'(?:vm_|ct_|vmct_)(\d+)', vm_ek)
                        if vmid_match:
                            vmid = vmid_match.group(1)
                            try:
                                vm_running = False
                                ct_running = False
                                vm_exists = False
                                ct_exists = False

                                result_vm = subprocess.run(
                                    ['qm', 'status', vmid],
                                    capture_output=True, text=True, timeout=2)
                                if result_vm.returncode == 0:
                                    vm_exists = True
                                    vm_running = 'running' in result_vm.stdout.lower()

                                if not vm_exists:
                                    result_ct = subprocess.run(
                                        ['pct', 'status', vmid],
                                        capture_output=True, text=True, timeout=2)
                                    if result_ct.returncode == 0:
                                        ct_exists = True
                                        ct_running = 'running' in result_ct.stdout.lower()

                                if not vm_exists and not ct_exists:
                                    cursor.execute('''
                                        UPDATE errors SET resolved_at = ?
                                        WHERE error_key = ? AND resolved_at IS NULL
                                    ''', (now_iso, vm_ek))
                                elif vm_running or ct_running:
                                    reason_lower = (vm_reason or '').lower()
                                    is_persistent = any(x in reason_lower for x in [
                                        'device', 'missing', 'does not exist', 'permission',
                                        'not found', 'no such', 'invalid'])
                                    if not is_persistent:
                                        cursor.execute('''
                                            UPDATE errors SET resolved_at = ?
                                            WHERE error_key = ? AND resolved_at IS NULL
                                        ''', (now_iso, vm_ek))
                            except Exception:
                                pass

                    # 5. GENERIC: Any error not seen in 30 min while system is healthy
                    if current_cpu < 80 and current_mem < 85:
                        stale_generic_cutoff = (now - timedelta(minutes=30)).isoformat()
                        cursor.execute('''
                            UPDATE errors SET resolved_at = ?
                            WHERE resolved_at IS NULL AND acknowledged = 0
                              AND last_seen < ?
                              AND category NOT IN ('disks', 'storage')
                        ''', (now_iso, stale_generic_cutoff))

            except Exception:
                pass  # If we can't read uptime, skip this cleanup

            conn.commit()
        finally:
            conn.close()

        # Clean up errors for resources that no longer exist (VMs/CTs deleted, disks removed)
        self._cleanup_stale_resources()

        # NOTE: cleanup_orphan_observations() is deliberately NOT invoked here.
        # Running it on the 5-minute auto-resolve cycle silently dismissed legitimate
        # observations (ZFS pool errors, ATA host events, dm-* aliases) before the user
        # could see them in the UI history, even though notifications were already sent.
        # The cleanup is still available as an explicit user action via
        # POST /api/health/cleanup-disconnected-disks (flask_health_routes.py).
    
    def _cleanup_stale_resources(self):
        """Resolve errors for resources that no longer exist.
        
        Comprehensive cleanup for ALL error categories:
        - VMs/CTs: deleted resources (not just stopped)
        - Disks: physically removed devices, ZFS pools, storage
        - Network: removed interfaces, bonds, bridges
        - Services/pve_services: services on deleted CTs, stopped services
        - Logs: persistent/spike/cascade errors older than 48h
        - Cluster: errors when node is no longer in cluster
        - Temperature: sensors that no longer exist
        - Memory/Storage: mount points that no longer exist
        - Updates/Security: acknowledged errors older than 7 days
        - General fallback: any error older than 7 days with no recent activity
        """
        import subprocess
        import re
        
        conn = self._get_conn()
        cursor = conn.cursor()
        now = datetime.now()
        now_iso = now.isoformat()
        
        # Get all active (unresolved) errors with first_seen and last_seen for age checks
        # An error is considered unresolved if resolution_type is NULL or empty
        # (resolved_at alone is not sufficient - it may be in an inconsistent state)
        cursor.execute('''
            SELECT id, error_key, category, reason, first_seen, last_seen, severity FROM errors 
            WHERE resolution_type IS NULL OR resolution_type = ''
        ''')
        active_errors = cursor.fetchall()
        resolved_count = 0
        
        # Cache for expensive checks (avoid repeated subprocess calls)
        _vm_ct_exists_cache = {}
        _cluster_status_cache = None
        _network_interfaces_cache = None
        _zfs_pools_cache = None
        _mount_points_cache = None
        _pve_services_cache = None
        
        def check_vm_ct_cached(vmid):
            if vmid not in _vm_ct_exists_cache:
                _vm_ct_exists_cache[vmid] = self._check_vm_ct_exists(vmid)
            return _vm_ct_exists_cache[vmid]
        
        def get_cluster_status():
            nonlocal _cluster_status_cache
            if _cluster_status_cache is None:
                # Primary signal: presence of `/etc/corosync/corosync.conf`.
                # That file only exists on clustered nodes and is the same
                # check `health_monitor._check_pve_services` uses for the
                # corosync gate. Substring match on "Cluster information"
                # was fragile against locale/translations and PVE upgrades
                # renaming the header. Audit Tier 6 — `_cleanup_stale_resources::get_cluster_status`.
                is_cluster = os.path.isfile('/etc/corosync/corosync.conf')
                nodes_text = ''
                try:
                    result = subprocess.run(
                        ['pvecm', 'status'],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        nodes_text = result.stdout
                        # Confirm via any of multiple section markers that
                        # appear on real cluster nodes, not just one.
                        if not is_cluster:
                            stdout_l = nodes_text.lower()
                            is_cluster = any(
                                marker in stdout_l
                                for marker in ('cluster information',
                                               'quorum information',
                                               'membership information')
                            )
                except Exception:
                    # On error, fall back to corosync.conf signal alone.
                    pass
                _cluster_status_cache = {
                    'is_cluster': is_cluster,
                    'nodes': nodes_text,
                }
            return _cluster_status_cache
        
        def get_network_interfaces():
            nonlocal _network_interfaces_cache
            if _network_interfaces_cache is None:
                try:
                    import psutil
                    _network_interfaces_cache = set(psutil.net_if_stats().keys())
                except Exception:
                    _network_interfaces_cache = set()
            return _network_interfaces_cache
        
        def get_zfs_pools():
            nonlocal _zfs_pools_cache
            if _zfs_pools_cache is None:
                try:
                    result = subprocess.run(
                        ['zpool', 'list', '-H', '-o', 'name'],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        _zfs_pools_cache = set(result.stdout.strip().split('\n'))
                    else:
                        _zfs_pools_cache = set()
                except Exception:
                    _zfs_pools_cache = set()
            return _zfs_pools_cache
        
        def get_mount_points():
            nonlocal _mount_points_cache
            if _mount_points_cache is None:
                try:
                    import psutil
                    _mount_points_cache = set(p.mountpoint for p in psutil.disk_partitions(all=True))
                except Exception:
                    _mount_points_cache = set()
            return _mount_points_cache
        
        def get_pve_services_status():
            nonlocal _pve_services_cache
            if _pve_services_cache is None:
                _pve_services_cache = {}
                try:
                    result = subprocess.run(
                        ['systemctl', 'list-units', '--type=service', '--all', '--no-legend'],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        for line in result.stdout.strip().split('\n'):
                            parts = line.split()
                            if parts:
                                service_name = parts[0].replace('.service', '')
                                _pve_services_cache[service_name] = 'active' in line
                except Exception:
                    pass
            return _pve_services_cache
        
        def extract_vmid_from_text(text):
            """Extract VM/CT ID from error message or key."""
            if not text:
                return None
            # Patterns: "VM 100", "CT 100", "vm_100_", "ct_100_", "VMID 100", "VM/CT 100", "qemu/100", "lxc/100", etc.
            patterns = [
                r'(?:VM|CT|VMID|CTID|vm_|ct_|vmct_)[\s_]?(\d{3,})',  # VM 100, ct_100
                r'VM/CT[\s_]?(\d{3,})',                               # VM/CT 100
                r'(?:qemu|lxc)[/\\](\d{3,})',                         # qemu/100, lxc/100
                r'process.*kvm.*?(\d{3,})',                           # process kvm with vmid
                r'Failed to start.*?(\d{3,})',                        # Failed to start VM/CT
                r'starting.*?(\d{3,}).*failed',                       # starting 100 failed
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1)
            return None
        
        def get_age_hours(timestamp_str):
            """Get age in hours from ISO timestamp string."""
            if not timestamp_str:
                return 0
            try:
                dt = datetime.fromisoformat(timestamp_str)
                return (now - dt).total_seconds() / 3600
            except (ValueError, TypeError):
                return 0
        
        for error_row in active_errors:
            err_id, error_key, category, reason, first_seen, last_seen, severity = error_row
            should_resolve = False
            resolution_reason = None
            age_hours = get_age_hours(first_seen)
            last_seen_hours = get_age_hours(last_seen)
            
            # === VM/CT ERRORS ===
            # Only attempt VMID resolution when the error context is actually VM/CT-related.
            # The loose regex patterns in extract_vmid_from_text (kvm/Failed to start/starting...failed)
            # otherwise match any 3+ digit number in unrelated disk/network/service messages, and the
            # if/elif chain below would short-circuit the legitimate category-specific check.
            is_vm_ct_context = (
                category in ('vms', 'vmct') or
                (error_key and (error_key.startswith('vm_') or error_key.startswith('ct_') or error_key.startswith('vmct_')))
            )
            vmid = None
            if is_vm_ct_context:
                vmid_from_key = extract_vmid_from_text(error_key) if error_key else None
                vmid_from_reason = extract_vmid_from_text(reason) if reason else None
                vmid = vmid_from_key or vmid_from_reason

            if is_vm_ct_context and vmid and not check_vm_ct_cached(vmid):
                should_resolve = True
                resolution_reason = f'VM/CT {vmid} deleted'
            elif is_vm_ct_context:
                # VM/CT context but ID couldn't be extracted - resolve if stale
                if not vmid and last_seen_hours > 1:
                    should_resolve = True
                    resolution_reason = 'VM/CT error stale (>1h, ID not found)'
            
            # === DISK ERRORS ===
            # Check if disk device or ZFS pool still exists
            elif category == 'disks' or category == 'storage':
                if error_key:
                    # Check for ZFS pool errors (e.g., "zfs_pool_rpool_degraded")
                    zfs_match = re.search(r'zfs_(?:pool_)?([a-zA-Z0-9_-]+)', error_key)
                    if zfs_match:
                        pool_name = zfs_match.group(1)
                        pools = get_zfs_pools()
                        if pools and pool_name not in pools:
                            should_resolve = True
                            resolution_reason = 'ZFS pool removed'
                    
                    # Check for disk device errors (e.g., "disk_sdh_io_error", "smart_sda_failing", "disk_fs_sdb1")
                    if not should_resolve:
                        # Match patterns like: smart_sda, disk_sdb, io_error_nvme0n1, disk_fs_sdb1
                        disk_match = re.search(r'(?:disk_fs_|disk_|smart_|io_error_)(?:/dev/)?([a-z]{2,4}[a-z0-9]*)', error_key)
                        if disk_match:
                            disk_name = disk_match.group(1)
                            # Remove partition number for base device check
                            base_disk = disk_base_name(disk_name)
                            disk_path = f'/dev/{disk_name}'
                            base_path = f'/dev/{base_disk}'
                            if not os.path.exists(disk_path) and not os.path.exists(base_path):
                                should_resolve = True
                                resolution_reason = 'Disk device removed'
                    
                    # Check for mount point errors (e.g., "disk_fs_/mnt/data")
                    if not should_resolve and 'disk_fs_' in error_key:
                        mount = error_key.replace('disk_fs_', '').split('_')[0]
                        if mount.startswith('/'):
                            mounts = get_mount_points()
                            if mounts and mount not in mounts:
                                should_resolve = True
                                resolution_reason = 'Mount point removed'
            
            # === NETWORK ERRORS ===
            # Check if network interface still exists
            elif category == 'network':
                if error_key:
                    # Extract interface name (e.g., "net_vmbr1_down" -> "vmbr1", "bond0_slave_error" -> "bond0")
                    iface_match = re.search(r'(?:net_|bond_|vmbr|eth|eno|ens|enp)([a-zA-Z0-9_]+)?', error_key)
                    if iface_match:
                        # Reconstruct full interface name
                        full_match = re.search(r'((?:vmbr|bond|eth|eno|ens|enp)[a-zA-Z0-9]+)', error_key)
                        if full_match:
                            iface = full_match.group(1)
                            interfaces = get_network_interfaces()
                            if interfaces and iface not in interfaces:
                                should_resolve = True
                                resolution_reason = 'Network interface removed'
            
            # === SERVICE ERRORS ===
            # Check if service exists or if it references a deleted CT
            elif category in ('services', 'pve_services'):
                # First check if it references a CT that no longer exists
                vmid = extract_vmid_from_text(reason) or extract_vmid_from_text(error_key)
                if vmid and not check_vm_ct_cached(vmid):
                    should_resolve = True
                    resolution_reason = 'Container deleted'
                
                # For pve_services, check if the service unit exists
                if not should_resolve and category == 'pve_services' and error_key:
                    service_match = re.search(r'service_([a-zA-Z0-9_-]+)', error_key)
                    if service_match:
                        service_name = service_match.group(1)
                        services = get_pve_services_status()
                        if services and service_name not in services:
                            should_resolve = True
                            resolution_reason = 'Service no longer exists'
            
            # === LOG ERRORS ===
            # Auto-resolve log errors after 48h (they represent point-in-time issues)
            elif category == 'logs' or (error_key and error_key.startswith(('log_persistent_', 'log_spike_', 'log_cascade_', 'log_critical_'))):
                if age_hours > 48:
                    should_resolve = True
                    resolution_reason = 'Log error aged out (>48h)'
            
            # === CLUSTER ERRORS ===
            # Resolve cluster/corosync/qdevice errors if node is no longer in a cluster
            # Check both error_key and reason for cluster-related keywords
            cluster_keywords = ('cluster', 'corosync', 'qdevice', 'quorum', 'cman', 'pacemaker')
            is_cluster_error = (
                (error_key and any(x in error_key.lower() for x in cluster_keywords)) or
                (reason and any(x in reason.lower() for x in cluster_keywords))
            )
            if is_cluster_error:
                cluster_info = get_cluster_status()
                if not cluster_info['is_cluster']:
                    should_resolve = True
                    resolution_reason = 'No longer in cluster'
            
            # === TEMPERATURE ERRORS ===
            # Temperature errors - check if sensor still exists (unlikely to change, resolve after 24h of no activity)
            elif category == 'temperature':
                if last_seen_hours > 24:
                    should_resolve = True
                    resolution_reason = 'Temperature error stale (>24h no activity)'
            
            # === UPDATES/SECURITY ERRORS ===
            # These are informational - auto-resolve after 7 days if acknowledged or stale
            elif category in ('updates', 'security'):
                if age_hours > 168:  # 7 days
                    should_resolve = True
                    resolution_reason = 'Update/security notice aged out (>7d)'
            
            # === FALLBACK: ANY STALE ERROR ===
            # Any error that hasn't been seen in 7 days and is older than 7 days
            if not should_resolve and age_hours > 168 and last_seen_hours > 168:
                should_resolve = True
                resolution_reason = 'Stale error (no activity >7d)'
            
            if should_resolve:
                cursor.execute('''
                    UPDATE errors SET resolved_at = ?, resolution_type = 'auto', resolution_reason = ?
                    WHERE id = ?
                ''', (now_iso, resolution_reason, err_id))
                resolved_count += 1
        
        if resolved_count > 0:
            conn.commit()
            print(f"[HealthPersistence] Auto-resolved {resolved_count} errors for stale/deleted resources")
        
        conn.close()
    
    def _check_vm_ct_exists(self, vmid: str) -> bool:
        """Check if a VM or CT exists (not just running, but exists at all).
        
        Uses 'qm config' and 'pct config' which return success even for stopped VMs/CTs,
        but fail if the VM/CT doesn't exist.
        """
        import subprocess
        
        try:
            # Try VM first
            result = subprocess.run(
                ['qm', 'config', vmid],
                capture_output=True,
                text=True,
                timeout=3
            )
            if result.returncode == 0:
                return True
            
            # Try CT
            result = subprocess.run(
                ['pct', 'config', vmid],
                capture_output=True,
                text=True,
                timeout=3
            )
            if result.returncode == 0:
                return True
            
            return False
        except subprocess.TimeoutExpired:
            # On timeout, assume it exists to avoid false positives
            return True
        except Exception as e:
            # On other errors (command not found, etc.), check if it's a "not found" error
            # If we can't determine, assume it doesn't exist to allow cleanup
            return False
    
    def check_vm_running(self, vm_id: str) -> bool:
        """
        Check if a VM/CT is running and resolve TRANSIENT errors if so.
        Also resolves error if VM/CT no longer exists.
        
        Only resolves errors that are likely to be fixed by a restart:
        - QMP command failures
        - Startup failures (generic)
        
        Does NOT resolve persistent configuration errors like:
        - Device missing
        - Permission issues
        
        Returns True if running/resolved, False otherwise.
        """
        import subprocess
        
        try:
            vm_exists = False
            ct_exists = False
            is_running = False
            vm_type = None
            
            # Check qm status for VMs
            result_vm = subprocess.run(
                ['qm', 'status', vm_id],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result_vm.returncode == 0:
                vm_exists = True
                vm_type = 'vm'
                if 'running' in result_vm.stdout.lower():
                    is_running = True
            
            # Check pct status for containers
            if not vm_exists:
                result_ct = subprocess.run(
                    ['pct', 'status', vm_id],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if result_ct.returncode == 0:
                    ct_exists = True
                    vm_type = 'ct'
                    if 'running' in result_ct.stdout.lower():
                        is_running = True
            
            # If neither VM nor CT exists, resolve ALL related errors
            if not vm_exists and not ct_exists:
                self.resolve_error(f'vm_{vm_id}', 'VM/CT deleted')
                self.resolve_error(f'ct_{vm_id}', 'VM/CT deleted')
                self.resolve_error(f'vmct_{vm_id}', 'VM/CT deleted')
                return True
            
            # If running, only resolve TRANSIENT errors (QMP, startup)
            # Do NOT resolve persistent config errors (device missing, permissions)
            if is_running:
                conn = self._get_conn()
                cursor = conn.cursor()
                
                # Get the error details to check if it's a persistent config error
                for prefix in (f'{vm_type}_{vm_id}', f'vmct_{vm_id}'):
                    cursor.execute('''
                        SELECT error_key, reason FROM errors 
                        WHERE error_key = ? AND resolved_at IS NULL
                    ''', (prefix,))
                    row = cursor.fetchone()
                    if row:
                        reason = (row[1] or '').lower()
                        # Check if this is a persistent config error that won't be fixed by restart
                        is_persistent_config = any(indicator in reason for indicator in [
                            'device', 'missing', 'does not exist', 'permission', 
                            'not found', 'no such', 'invalid'
                        ])
                        
                        if not is_persistent_config:
                            # Transient error - resolve it
                            self.resolve_error(prefix, f'{vm_type.upper()} started successfully')
                
                conn.close()
                return True
            
            return False
            
        except Exception:
            return False
    
    def get_dismissed_errors(self) -> List[Dict[str, Any]]:
        """
        Get errors that were acknowledged/dismissed but still within suppression period.
        These are shown as INFO in the frontend with a 'Dismissed' badge.
        """
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM errors
            WHERE acknowledged = 1
            ORDER BY acknowledged_at DESC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        dismissed = []
        now = datetime.now()
        
        for row in rows:
            error_dict = dict(row)
            if error_dict.get('details'):
                try:
                    error_dict['details'] = json.loads(error_dict['details'])
                except (json.JSONDecodeError, TypeError):
                    pass
            
            # Check if still within suppression period using per-record hours
            # Use acknowledged_at as reference (resolved_at may be NULL for dismissed but active errors)
            try:
                ref_time_str = error_dict.get('acknowledged_at') or error_dict.get('resolved_at')
                if not ref_time_str:
                    continue
                ref_dt = datetime.fromisoformat(ref_time_str)
                sup_hours = error_dict.get('suppression_hours')
                if sup_hours is None:
                    sup_hours = self.DEFAULT_SUPPRESSION_HOURS
                
                error_dict['dismissed'] = True
                
                if sup_hours == -1:
                    # Permanent dismiss
                    error_dict['suppression_remaining_hours'] = -1
                    error_dict['permanent'] = True
                    dismissed.append(error_dict)
                else:
                    elapsed_seconds = (now - ref_dt).total_seconds()
                    suppression_seconds = sup_hours * 3600
                    
                    if elapsed_seconds < suppression_seconds:
                        error_dict['suppression_remaining_hours'] = round(
                            (suppression_seconds - elapsed_seconds) / 3600, 1
                        )
                        error_dict['permanent'] = False
                        dismissed.append(error_dict)
            except (ValueError, TypeError):
                pass
        
        return dismissed
    
    def emit_event(self, event_type: str, category: str, severity: str, 
                   data: Optional[Dict] = None) -> int:
        """
        Emit a health event for the notification system.
        Returns the event ID.
        
        Event types: 
        - 'state_change': severity changed (OK->WARNING, WARNING->CRITICAL, etc.)
        - 'new_error': new error detected
        - 'resolved': error resolved
        - 'escalated': severity increased
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        event_data = data or {}
        event_data['category'] = category
        event_data['severity'] = severity
        event_data['needs_notification'] = True
        
        cursor.execute('''
            INSERT INTO events (event_type, error_key, timestamp, data)
            VALUES (?, ?, ?, ?)
        ''', (event_type, f'{category}_{severity}', datetime.now().isoformat(), 
              json.dumps(event_data)))
        
        event_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return event_id
    
    def get_pending_notifications(self) -> List[Dict[str, Any]]:
        """
        Get events that need notification (for future Telegram/Gotify integration).
        Groups by severity for batch notification sending.
        """
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT e.*, err.category as error_category, err.reason as error_reason
            FROM events e
            LEFT JOIN errors err ON e.error_key = err.error_key
            WHERE json_extract(e.data, '$.needs_notification') = 1
            ORDER BY e.timestamp DESC
            LIMIT 100
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        events = []
        for row in rows:
            event_dict = dict(row)
            if event_dict.get('data'):
                try:
                    event_dict['data'] = json.loads(event_dict['data'])
                except (json.JSONDecodeError, TypeError):
                    pass
            events.append(event_dict)
        
        return events
    
    def mark_events_notified(self, event_ids: List[int]):
        """Mark events as notified (notification was sent successfully)"""
        if not event_ids:
            return
        
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Use single UPDATE with IN clause instead of N individual updates
        now = datetime.now().isoformat()
        placeholders = ','.join('?' * len(event_ids))
        cursor.execute(f'''
            UPDATE events
            SET data = json_set(COALESCE(data, '{{}}'), '$.needs_notification', 0, '$.notified_at', ?)
            WHERE id IN ({placeholders})
        ''', [now] + event_ids)
        
        conn.commit()
        conn.close()
    
    def _record_event(self, cursor, event_type: str, error_key: str, data: Dict):
        """Internal: Record an event"""
        cursor.execute('''
            INSERT INTO events (event_type, error_key, timestamp, data)
            VALUES (?, ?, ?, ?)
        ''', (event_type, error_key, datetime.now().isoformat(), json.dumps(data)))
    
    def get_unnotified_errors(self) -> List[Dict[str, Any]]:
        """Get errors that need Telegram notification"""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM errors 
            WHERE notification_sent = 0 
              AND resolved_at IS NULL 
              AND acknowledged = 0
            ORDER BY severity DESC, first_seen ASC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        errors = []
        for row in rows:
            error_dict = dict(row)
            if error_dict.get('details'):
                error_dict['details'] = json.loads(error_dict['details'])
            errors.append(error_dict)
        
        return errors
    
    def mark_notified(self, error_key: str):
        """Mark error as notified"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE errors 
            SET notification_sent = 1
            WHERE error_key = ?
        ''', (error_key,))
        
        conn.commit()
        conn.close()
    
    # ─── System Capabilities Cache ───────────────────────────────
    
    def get_capability(self, cap_key: str) -> Optional[str]:
        """
        Get a cached system capability value.
        Returns None if not yet detected.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT cap_value FROM system_capabilities WHERE cap_key = ?',
            (cap_key,)
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    
    def set_capability(self, cap_key: str, cap_value: str):
        """Store a system capability value (detected once, cached forever)."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO system_capabilities (cap_key, cap_value, detected_at)
            VALUES (?, ?, ?)
        ''', (cap_key, cap_value, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def get_all_capabilities(self) -> Dict[str, str]:
        """Get all cached system capabilities as a dict."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT cap_key, cap_value FROM system_capabilities')
        rows = cursor.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    
    # Note: System capabilities (has_zfs, has_lvm) are now derived at runtime
    # from Proxmox storage types in health_monitor.get_detailed_status()
    # This avoids redundant subprocess calls and ensures immediate detection
    # when the user adds new ZFS/LVM storage via Proxmox.
    
    # ─── User Settings ──────────────────────────────────────────
    
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a user setting value by key."""
        with self._db_connection() as conn:
            return self._get_setting_impl(conn, key, default)
    
    def _get_setting_impl(self, conn, key: str, default: Optional[str] = None) -> Optional[str]:
        """Internal: get setting using existing connection (P4 fix - avoids nested connections)."""
        cursor = conn.cursor()
        cursor.execute(
            'SELECT setting_value FROM user_settings WHERE setting_key = ?', (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else default
    
    def set_setting(self, key: str, value: str):
        """Store a user setting value."""
        with self._db_lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, ?)
            ''', (key, value, datetime.now().isoformat()))
            conn.commit()
            conn.close()
    
    def get_all_settings(self, prefix: Optional[str] = None) -> Dict[str, str]:
        """Get all user settings, optionally filtered by key prefix."""
        conn = self._get_conn()
        cursor = conn.cursor()
        if prefix:
            cursor.execute(
                'SELECT setting_key, setting_value FROM user_settings WHERE setting_key LIKE ?',
                (f'{prefix}%',)
            )
        else:
            cursor.execute('SELECT setting_key, setting_value FROM user_settings')
        rows = cursor.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    
    def sync_dismissed_suppression(self):
        """
        Retroactively update all existing dismissed errors to match current
        user settings. Called when the user saves settings, so changes are
        effective immediately on already-dismissed items.
        
        For each dismissed error, looks up its category's configured hours
        and updates the suppression_hours column to match.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Build reverse map: category -> setting_key
        cat_to_setting = {v['category']: k 
                          for k, v in self._get_category_labels().items()}
        
        # Get all current suppression settings
        current_settings = self.get_all_settings('suppress_')
        
        # Get all dismissed (acknowledged) errors
        cursor.execute('''
            SELECT id, error_key, category, suppression_hours
            FROM errors WHERE acknowledged = 1
        ''')
        dismissed = cursor.fetchall()
        
        updated_count = 0
        for err_id, error_key, category, old_hours in dismissed:
            setting_key = None
            for skey, meta in self._get_category_labels().items():
                if meta['category'] == category:
                    setting_key = skey
                    break
            
            if not setting_key:
                continue
            
            stored = current_settings.get(setting_key)
            new_hours = int(stored) if stored else self.DEFAULT_SUPPRESSION_HOURS
            
            if new_hours != old_hours:
                cursor.execute(
                    'UPDATE errors SET suppression_hours = ? WHERE id = ?',
                    (new_hours, err_id)
                )
                self._record_event(cursor, 'suppression_updated', error_key, {
                    'old_hours': old_hours,
                    'new_hours': new_hours,
                    'reason': 'settings_sync'
                })
                updated_count += 1
        
        conn.commit()
        conn.close()
        return updated_count
    
    def _get_category_labels(self) -> dict:
        """Internal helper for category label metadata."""
        return {
            'suppress_cpu': {'label': 'CPU Usage & Temperature', 'category': 'temperature', 'icon': 'cpu'},
            'suppress_memory': {'label': 'Memory & Swap', 'category': 'memory', 'icon': 'memory'},
            'suppress_storage': {'label': 'Storage Mounts & Space', 'category': 'storage', 'icon': 'storage'},
            'suppress_disks': {'label': 'Disk I/O & Errors', 'category': 'disks', 'icon': 'disk'},
            'suppress_network': {'label': 'Network Interfaces', 'category': 'network', 'icon': 'network'},
            'suppress_vms': {'label': 'VMs & Containers', 'category': 'vms', 'icon': 'vms'},
            'suppress_pve_services': {'label': 'PVE Services', 'category': 'pve_services', 'icon': 'services'},
            'suppress_logs': {'label': 'System Logs', 'category': 'logs', 'icon': 'logs'},
            'suppress_updates': {'label': 'System Updates', 'category': 'updates', 'icon': 'updates'},
            'suppress_security': {'label': 'Security & Certificates', 'category': 'security', 'icon': 'security'},
        }
    
    def get_suppression_categories(self) -> List[Dict[str, Any]]:
        """
        Get all health categories with their current suppression settings.
        Used by the settings page to render the per-category configuration.
        """
        category_labels = self._get_category_labels()
        current_settings = self.get_all_settings('suppress_')
        
        result = []
        for key, meta in category_labels.items():
            stored = current_settings.get(key)
            hours = int(stored) if stored else self.DEFAULT_SUPPRESSION_HOURS
            result.append({
                'key': key,
                'label': meta['label'],
                'category': meta['category'],
                'icon': meta['icon'],
                'hours': hours,
            })
        
        return result
    
    def get_custom_suppressions(self) -> List[Dict[str, Any]]:
        """
        Get only categories with non-default suppression settings.
        Used by the health modal to show a summary of custom suppressions.
        """
        all_cats = self.get_suppression_categories()
        return [c for c in all_cats if c['hours'] != self.DEFAULT_SUPPRESSION_HOURS]
    
    def record_unknown_persistent(self, category: str, reason: str):
        """
        Record a persistent UNKNOWN event when a health check has been
        unable to verify for >= 3 consecutive cycles (~15 min).
        Avoids duplicates by only recording once per 30 min per category.
        """
        with self._db_lock:
            self._record_unknown_persistent_impl(category, reason)
    
    def _record_unknown_persistent_impl(self, category, reason):
        try:
            event_key = f'unknown_persistent_{category}'
            now = datetime.now().isoformat()
            
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # Check if we already recorded this within the last 30 minutes
            # Note: events table has columns (id, event_type, error_key, timestamp, data)
            # We use error_key for deduplication since it contains the category
            cursor.execute('''
                SELECT MAX(timestamp) FROM events 
                WHERE event_type = ? AND error_key = ?
            ''', ('unknown_persistent', event_key))
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    last_recorded = datetime.fromisoformat(row[0])
                    if (datetime.now() - last_recorded).total_seconds() < 1800:
                        conn.close()
                        return  # Already recorded recently
                except (ValueError, TypeError):
                    pass  # If timestamp is malformed, proceed with recording
            
            cursor.execute('''
                INSERT INTO events (event_type, error_key, timestamp, data)
                VALUES (?, ?, ?, ?)
            ''', ('unknown_persistent', event_key, now, 
                  json.dumps({'category': category, 'reason': reason})))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[HealthPersistence] Error recording UNKNOWN persistent: {e}")


    # ────────────────────────────────────────────────────────────────
    #  Disk Observations API
    # ────────────────────────────────────────────────────────────────

    def register_disk(self, device_name: str, serial: Optional[str] = None,
                      model: Optional[str] = None, size_bytes: Optional[int] = None):
        """Register or update a physical disk in the registry.
        
        Uses (device_name, serial) as unique key. If the disk was previously
        marked removed, it's re-activated.
        
        Also consolidates old ATA-named entries: if an observation was recorded
        under 'ata8' and we now know the real block device is 'sdh' with
        serial 'WX72...', update the old entry so observations are linked.
        """
        with self._db_lock:
            now = datetime.now().isoformat()
            try:
                # Use the context-managed connection so a fail in any cursor
                # call below still releases the SQLite handle. The previous
                # pattern only closed inside the success path, so a hardware
                # error or a corrupted row left the connection orphaned with
                # `timeout=30, busy_timeout=10000` — under load that
                # serialised every other writer.
                with self._db_connection() as conn:
                    cursor = conn.cursor()

                    # Consolidate: if serial is known and an old entry exists with
                    # a different device_name (e.g. 'ata8' instead of 'sdh'),
                    # update that entry's device_name so observations carry over.
                    if serial:
                        cursor.execute('''
                            SELECT id, device_name FROM disk_registry
                            WHERE serial = ? AND serial != '' AND device_name != ?
                        ''', (serial, device_name))
                        old_rows = cursor.fetchall()
                        for old_id, old_dev in old_rows:
                            # Only consolidate ATA names -> block device names
                            if old_dev.startswith('ata') and not device_name.startswith('ata'):
                                # Check if target (device_name, serial) already exists
                                cursor.execute(
                                    'SELECT id FROM disk_registry WHERE device_name = ? AND serial = ?',
                                    (device_name, serial))
                                existing = cursor.fetchone()
                                if existing:
                                    # Merge: move observations from old -> existing, then delete old
                                    cursor.execute(
                                        'UPDATE disk_observations SET disk_registry_id = ? WHERE disk_registry_id = ?',
                                        (existing[0], old_id))
                                    cursor.execute('DELETE FROM disk_registry WHERE id = ?', (old_id,))
                                else:
                                    # Rename the old entry to the real block device name
                                    cursor.execute(
                                        'UPDATE disk_registry SET device_name = ?, model = COALESCE(?, model), '
                                        'size_bytes = COALESCE(?, size_bytes), last_seen = ?, removed = 0 '
                                        'WHERE id = ?',
                                        (device_name, model, size_bytes, now, old_id))

                    # If no serial provided, check if a record WITH serial already exists for this device
                    # This prevents creating duplicate entries (one with serial, one without)
                    effective_serial = serial or ''
                    if not serial:
                        cursor.execute('''
                            SELECT serial FROM disk_registry
                            WHERE device_name = ? AND serial != ''
                            ORDER BY last_seen DESC LIMIT 1
                        ''', (device_name,))
                        existing = cursor.fetchone()
                        if existing and existing[0]:
                            effective_serial = existing[0]  # Use the existing serial

                    cursor.execute('''
                        INSERT INTO disk_registry (device_name, serial, model, size_bytes, first_seen, last_seen, removed)
                        VALUES (?, ?, ?, ?, ?, ?, 0)
                        ON CONFLICT(device_name, serial) DO UPDATE SET
                            model = COALESCE(excluded.model, model),
                            size_bytes = COALESCE(excluded.size_bytes, size_bytes),
                            last_seen = excluded.last_seen,
                            removed = 0
                    ''', (device_name, effective_serial, model, size_bytes, now, now))

                    conn.commit()
            except Exception as e:
                print(f"[HealthPersistence] Error registering disk {device_name}: {e}")

    def _get_disk_registry_id(self, cursor, device_name: str,
                               serial: Optional[str] = None,
                               prefer_with_observations: bool = True) -> Optional[int]:
        """Find disk_registry.id, matching by serial first, then device_name.
        
        Also handles ATA-to-block cross-references: if looking for 'sdh' also
        checks entries with ATA names that share the same serial.
        
        When prefer_with_observations=True, prioritizes records that have
        linked observations, which helps with USB disks that may have
        multiple registry entries (one with serial, one without).
        """
        clean_dev = device_name.replace('/dev/', '')
        
        if serial:
            cursor.execute(
                'SELECT id FROM disk_registry WHERE serial = ? AND serial != "" ORDER BY last_seen DESC LIMIT 1',
                (serial,))
            row = cursor.fetchone()
            if row:
                return row[0]
        else:
            # No serial provided - first check if a record WITH serial exists for this device
            # This prevents returning a duplicate record without serial
            cursor.execute('''
                SELECT id FROM disk_registry 
                WHERE device_name = ? AND serial != '' 
                ORDER BY last_seen DESC LIMIT 1
            ''', (clean_dev,))
            row = cursor.fetchone()
            if row:
                return row[0]
        
        # Fallback: match by device_name
        
        if prefer_with_observations:
            # First try to find a registry entry that has observations linked
            # This handles USB disks where errors may be recorded under a different
            # registry entry (e.g., one without serial)
            cursor.execute('''
                SELECT dr.id FROM disk_registry dr
                LEFT JOIN disk_observations do ON dr.id = do.disk_registry_id
                WHERE dr.device_name = ?
                GROUP BY dr.id
                ORDER BY COUNT(do.id) DESC, dr.last_seen DESC
                LIMIT 1
            ''', (clean_dev,))
            row = cursor.fetchone()
            if row:
                return row[0]
        else:
            cursor.execute(
                'SELECT id FROM disk_registry WHERE device_name = ? ORDER BY last_seen DESC LIMIT 1',
                (clean_dev,))
            row = cursor.fetchone()
            if row:
                return row[0]
        
        # Last resort: search for ATA-named entries that might refer to this device
        # This handles cases where observations were recorded under 'ata8'
        # but we're querying for 'sdh'
        if clean_dev.startswith('sd') or clean_dev.startswith('nvme'):
            cursor.execute(
                'SELECT id FROM disk_registry WHERE device_name LIKE "ata%" ORDER BY last_seen DESC')
            # For each ATA entry, we can't resolve here without OS access,
            # so just return None and let the serial-based consolidation
            # in register_disk handle it over time.
            pass
        return None

    # NOTE: update_disk_worst_health, get_disk_health_status, clear_disk_health_history
    # were removed. The disk health badge now shows the CURRENT status from Proxmox/SMART
    # directly, not a persistent "worst_health". Historical observations are preserved
    # in disk_observations table and shown separately via the "X obs." badge.

    def record_disk_observation(self, device_name: str, serial: Optional[str],
                                 error_type: str, error_signature: str,
                                 raw_message: str = '',
                                 severity: str = 'warning'):
        """Record or deduplicate a disk error observation.

        error_type:  'smart_error', 'io_error', 'connection_error'
        error_signature: Normalized unique string for dedup (e.g. 'FailedReadSmartSelfTestLog')

        Serialized via `_db_lock`: this method does PRAGMA introspection +
        UPSERT in the same connection, and runs from journal/polling/webhook
        threads concurrently. Without serialization the dedup UPSERT could
        race with another thread's INSERT and produce duplicate rows in
        `disk_observations` for the same (disk, type, signature). Audit
        Tier 5 (Health stack — race conditions sin _db_lock).
        """
        now = datetime.now().isoformat()
        try:
            with self._db_lock:
                self._record_disk_observation_locked(
                    device_name, serial, error_type, error_signature,
                    raw_message, severity, now,
                )
        except Exception as e:
            print(f"[HealthPersistence] Error recording disk observation: {e}")
            return
        return

    def _record_disk_observation_locked(self, device_name, serial, error_type,
                                         error_signature, raw_message, severity, now):
        """Inner body of `record_disk_observation`, called under _db_lock."""
        # Use the context manager so a thrown exception inside any cursor
        # call still releases the SQLite handle. Mirrors the fix on
        # `register_disk` — both are hot-path writes from the dispatch loop.
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()

                # Auto-register the disk if not present
                clean_dev = device_name.replace('/dev/', '')
                self.register_disk(clean_dev, serial)

                disk_id = self._get_disk_registry_id(cursor, clean_dev, serial)
                if not disk_id:
                    return

                # Detect column names for backward compatibility with older schemas
                cursor.execute('PRAGMA table_info(disk_observations)')
                columns = [col[1] for col in cursor.fetchall()]

                # Map to actual column names (old vs new schema)
                type_col = 'error_type' if 'error_type' in columns else 'observation_type'
                first_col = 'first_occurrence' if 'first_occurrence' in columns else 'first_seen'
                last_col = 'last_occurrence' if 'last_occurrence' in columns else 'last_seen'

                # Upsert observation: if same (disk, type, signature), bump count + update last timestamp.
                # IMPORTANT: Do NOT reset dismissed — if the user dismissed this observation,
                # re-detecting the same journal entry must not un-dismiss it. Also do not
                # increment the occurrence_count on dismissed rows (audit Tier 5 — once
                # the user has dismissed, we don't want the counter to keep growing for
                # journal events that no longer interest them; this also stops the badge
                # from drifting upward for dismissed conditions).
                cursor.execute(f'''
                    INSERT INTO disk_observations
                        (disk_registry_id, {type_col}, error_signature, {first_col},
                         {last_col}, occurrence_count, raw_message, severity, dismissed)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, 0)
                    ON CONFLICT(disk_registry_id, {type_col}, error_signature) DO UPDATE SET
                        {last_col} = excluded.{last_col},
                        occurrence_count = occurrence_count + 1,
                        severity = CASE WHEN excluded.severity = 'critical' THEN 'critical' ELSE severity END
                    WHERE dismissed = 0
                ''', (disk_id, error_type, error_signature, now, now, raw_message, severity))

                conn.commit()
                # Observation recorded - worst_health no longer updated (badge shows current SMART status)

        except Exception as e:
            print(f"[HealthPersistence] Error recording disk observation: {e}")

    def get_disk_observations(self, device_name: Optional[str] = None,
                               serial: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get active (non-dismissed) observations for one disk or all disks.
        
        For USB disks that may have multiple registry entries (one with serial,
        one without), this searches ALL registry entries matching the device_name
        to ensure observations are found regardless of which entry recorded them.
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # Detect column names for backward compatibility with older schemas
            cursor.execute('PRAGMA table_info(disk_observations)')
            columns = [col[1] for col in cursor.fetchall()]
            
            type_col = 'error_type' if 'error_type' in columns else 'observation_type'
            first_col = 'first_occurrence' if 'first_occurrence' in columns else 'first_seen'
            last_col = 'last_occurrence' if 'last_occurrence' in columns else 'last_seen'
            
            if device_name or serial:
                clean_dev = (device_name or '').replace('/dev/', '')
                
                # Get ALL disk_registry IDs that match this device_name
                # This handles USB disks with multiple registry entries
                cursor.execute(
                    'SELECT id FROM disk_registry WHERE device_name = ?',
                    (clean_dev,))
                all_ids = [row[0] for row in cursor.fetchall()]
                
                # Also try to find by serial if provided
                if serial:
                    cursor.execute(
                        'SELECT id FROM disk_registry WHERE serial = ? AND serial != ""',
                        (serial,))
                    serial_ids = [row[0] for row in cursor.fetchall()]
                    all_ids = list(set(all_ids + serial_ids))
                
                if not all_ids:
                    conn.close()
                    return []
                
                # Query observations for ALL matching registry entries
                placeholders = ','.join('?' * len(all_ids))
                cursor.execute(f'''
                    SELECT o.id, o.{type_col}, o.error_signature,
                           o.{first_col}, o.{last_col},
                           o.occurrence_count, o.raw_message, o.severity, o.dismissed,
                           d.device_name, d.serial, d.model
                    FROM disk_observations o
                    JOIN disk_registry d ON o.disk_registry_id = d.id
                    WHERE o.disk_registry_id IN ({placeholders}) AND o.dismissed = 0
                    ORDER BY o.{last_col} DESC
                ''', all_ids)
            else:
                cursor.execute(f'''
                    SELECT o.id, o.{type_col}, o.error_signature,
                           o.{first_col}, o.{last_col},
                           o.occurrence_count, o.raw_message, o.severity, o.dismissed,
                           d.device_name, d.serial, d.model
                    FROM disk_observations o
                    JOIN disk_registry d ON o.disk_registry_id = d.id
                    WHERE o.dismissed = 0
                    ORDER BY o.{last_col} DESC
                ''')
            
            rows = cursor.fetchall()
            conn.close()
            
            return [{
                'id': r[0],
                'error_type': r[1],
                'error_signature': r[2],
                'first_occurrence': r[3],
                'last_occurrence': r[4],
                'occurrence_count': r[5],
                'raw_message': r[6] or '',
                'severity': r[7],
                'dismissed': bool(r[8]),
                'device_name': r[9],
                'serial': r[10],
                'model': r[11],
            } for r in rows]
        except Exception as e:
            print(f"[HealthPersistence] Error getting observations: {e}")
            return []

    def get_all_observed_devices(self) -> List[Dict[str, Any]]:
        """Return a list of unique device_name + serial pairs that have observations.

        `device_name` and `serial` live on `disk_registry`, not on
        `disk_observations` — the original query referenced columns that
        don't exist and silently returned `[]` because the OperationalError
        was swallowed by the broad `except`. Joined to the registry so the
        function actually works.
        """
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT dr.device_name, dr.serial
                    FROM disk_observations o
                    JOIN disk_registry dr ON o.disk_registry_id = dr.id
                    WHERE o.dismissed = 0
                ''')
                rows = cursor.fetchall()
                return [{'device_name': r[0], 'serial': r[1] or ''} for r in rows]
        except Exception as e:
            print(f"[HealthPersistence] get_all_observed_devices failed: {e}")
            return []
    
    def get_disks_observation_counts(self) -> Dict[str, int]:
        """Return {device_name: count} of active observations per disk.
        
        Groups by serial when available to consolidate counts across device name changes
        (e.g., ata8 -> sdh). Also includes serial-keyed entries for cross-device matching.
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # For disks WITH serial: group by serial to consolidate across device renames
            cursor.execute('''
                SELECT d.serial, COUNT(o.id) as cnt
                FROM disk_observations o
                JOIN disk_registry d ON o.disk_registry_id = d.id
                WHERE o.dismissed = 0 AND d.serial IS NOT NULL AND d.serial != ''
                GROUP BY d.serial
            ''')
            serial_counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Get current device_name for each serial (prefer non-ata names)
            cursor.execute('''
                SELECT serial, device_name FROM disk_registry
                WHERE serial IS NOT NULL AND serial != ''
                ORDER BY 
                    CASE WHEN device_name LIKE 'ata%' THEN 1 ELSE 0 END,
                    last_seen DESC
            ''')
            serial_to_device = {}
            for serial, device_name in cursor.fetchall():
                if serial not in serial_to_device:
                    serial_to_device[serial] = device_name
            
            # Build result
            result = {}
            for serial, cnt in serial_counts.items():
                result[f'serial:{serial}'] = cnt
                device_name = serial_to_device.get(serial)
                if device_name:
                    result[device_name] = max(result.get(device_name, 0), cnt)
            
            # For disks WITHOUT serial: group by device_name
            cursor.execute('''
                SELECT d.device_name, COUNT(o.id) as cnt
                FROM disk_observations o
                JOIN disk_registry d ON o.disk_registry_id = d.id
                WHERE o.dismissed = 0 AND (d.serial IS NULL OR d.serial = '')
                GROUP BY d.device_name
            ''')
            for device_name, cnt in cursor.fetchall():
                result[device_name] = max(result.get(device_name, 0), cnt)
            
            conn.close()
            return result
        except Exception as e:
            print(f"[HealthPersistence] Error getting observation counts: {e}")
            return {}

    def dismiss_disk_observation(self, observation_id: int):
        """Mark a single observation as dismissed."""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE disk_observations SET dismissed = 1 WHERE id = ?',
                (observation_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[HealthPersistence] Error dismissing observation: {e}")

    def cleanup_stale_observations(self, max_age_days: int = 30):
        """Auto-dismiss observations not seen in max_age_days."""
        try:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # Detect column name for backward compatibility
            cursor.execute('PRAGMA table_info(disk_observations)')
            columns = [col[1] for col in cursor.fetchall()]
            last_col = 'last_occurrence' if 'last_occurrence' in columns else 'last_seen'
            
            cursor.execute(f'''
                UPDATE disk_observations 
                SET dismissed = 1 
                WHERE dismissed = 0 AND {last_col} < ?
            ''', (cutoff,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[HealthPersistence] Error cleaning stale observations: {e}")

    def mark_removed_disks(self, active_device_names: List[str]):
        """Mark disks not in active_device_names as removed."""
        try:
            now = datetime.now().isoformat()
            conn = self._get_conn()
            cursor = conn.cursor()
            if active_device_names:
                placeholders = ','.join('?' for _ in active_device_names)
                cursor.execute(f'''
                    UPDATE disk_registry SET removed = 1
                    WHERE device_name NOT IN ({placeholders}) AND removed = 0
                ''', active_device_names)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[HealthPersistence] Error marking removed disks: {e}")

    # Logical (non-block) device-name prefixes used as observation keys for events that
    # don't map to a /dev/<name> entry: ZFS pool names, ATA host identifiers (e.g. "ata8"
    # from "ata8.00: exception ..." journal lines), device-mapper aliases, etc. These are
    # never visible in /dev/ by design, so the original presence-based cleanup would
    # always wrongly dismiss them. They are excluded from automatic cleanup; the user's
    # explicit "clean up disconnected disks" action also skips them.
    _LOGICAL_DEVICE_PREFIXES = ('zpool_', 'ata', 'dm-', 'nbd', 'loop', 'sr')

    def cleanup_orphan_observations(self):
        """
        Dismiss observations for devices that no longer exist in /dev/.
        Useful for cleaning up after USB drives or temporary devices are disconnected.

        Observations whose `device_name` uses a logical (non-block) prefix are skipped —
        ZFS pools, ATA hosts and dm-* aliases never appear under /dev/ by design and were
        being silently dismissed by the previous version of this routine.
        """
        import os
        import re
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # Get all active (non-dismissed) observations with device info from disk_registry
            cursor.execute('''
                SELECT do.id, dr.device_name, dr.serial
                FROM disk_observations do
                JOIN disk_registry dr ON do.disk_registry_id = dr.id
                WHERE do.dismissed = 0
            ''')
            observations = cursor.fetchall()

            dismissed_count = 0
            for obs_id, device_name, serial in observations:
                # Skip non-block observations (ZFS pools, ATA hosts, dm-mapper, etc.)
                if device_name and device_name.startswith(self._LOGICAL_DEVICE_PREFIXES):
                    continue
                # Check if device exists
                dev_path = f'/dev/{device_name}'
                # Also check base device (remove partition number)
                base_dev = disk_base_name(device_name)
                base_path = f'/dev/{base_dev}'

                if not os.path.exists(dev_path) and not os.path.exists(base_path):
                    cursor.execute('''
                        UPDATE disk_observations SET dismissed = 1
                        WHERE id = ?
                    ''', (obs_id,))
                    dismissed_count += 1

            conn.commit()
            conn.close()
            if dismissed_count > 0:
                print(f"[HealthPersistence] Cleaned up {dismissed_count} orphan observations")
            return dismissed_count
        except Exception as e:
            print(f"[HealthPersistence] Error cleaning orphan observations: {e}")
            return 0


    # ── Remote Storage Exclusions Methods ──
    
    # Types considered "remote" and eligible for exclusion
    REMOTE_STORAGE_TYPES = {'pbs', 'nfs', 'cifs', 'glusterfs', 'iscsi', 'iscsidirect', 'cephfs', 'rbd'}
    
    def is_remote_storage_type(self, storage_type: str) -> bool:
        """Check if a storage type is considered remote/external."""
        return storage_type.lower() in self.REMOTE_STORAGE_TYPES
    
    def get_excluded_storages(self) -> List[Dict[str, Any]]:
        """Get list of all excluded remote storages."""
        try:
            with self._db_connection(row_factory=True) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT storage_name, storage_type, excluded_at, 
                           exclude_health, exclude_notifications, reason
                    FROM excluded_storages
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[HealthPersistence] Error getting excluded storages: {e}")
            return []
    
    def is_storage_excluded(self, storage_name: str, check_type: str = 'health') -> bool:
        """
        Check if a storage is excluded from monitoring.
        
        Args:
            storage_name: Name of the storage
            check_type: 'health' or 'notifications'
        
        Returns:
            True if storage is excluded for the given check type
        """
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                column = 'exclude_health' if check_type == 'health' else 'exclude_notifications'
                cursor.execute(f'''
                    SELECT {column} FROM excluded_storages 
                    WHERE storage_name = ?
                ''', (storage_name,))
                row = cursor.fetchone()
                return row is not None and row[0] == 1
        except Exception:
            return False
    
    def exclude_storage(self, storage_name: str, storage_type: str, 
                       exclude_health: bool = True, exclude_notifications: bool = True,
                       reason: str = None) -> bool:
        """
        Add a storage to the exclusion list.
        
        Args:
            storage_name: Name of the storage to exclude
            storage_type: Type of storage (pbs, nfs, etc.)
            exclude_health: Whether to exclude from health monitoring
            exclude_notifications: Whether to exclude from notifications
            reason: Optional reason for exclusion
        
        Returns:
            True if successfully excluded
        """
        try:
            now = datetime.now().isoformat()
            with self._db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO excluded_storages 
                    (storage_name, storage_type, excluded_at, exclude_health, exclude_notifications, reason)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(storage_name) DO UPDATE SET
                        exclude_health = excluded.exclude_health,
                        exclude_notifications = excluded.exclude_notifications,
                        reason = excluded.reason
                ''', (storage_name, storage_type, now, 
                      1 if exclude_health else 0, 
                      1 if exclude_notifications else 0, 
                      reason))
                conn.commit()
                return True
        except Exception as e:
            print(f"[HealthPersistence] Error excluding storage: {e}")
            return False
    
    def update_storage_exclusion(self, storage_name: str, 
                                 exclude_health: Optional[bool] = None,
                                 exclude_notifications: Optional[bool] = None) -> bool:
        """
        Update exclusion settings for a storage.
        
        Args:
            storage_name: Name of the storage
            exclude_health: New value for health exclusion (None = don't change)
            exclude_notifications: New value for notifications exclusion (None = don't change)
        
        Returns:
            True if successfully updated
        """
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                
                updates = []
                values = []
                
                if exclude_health is not None:
                    updates.append('exclude_health = ?')
                    values.append(1 if exclude_health else 0)
                
                if exclude_notifications is not None:
                    updates.append('exclude_notifications = ?')
                    values.append(1 if exclude_notifications else 0)
                
                if not updates:
                    return True
                
                values.append(storage_name)
                cursor.execute(f'''
                    UPDATE excluded_storages 
                    SET {', '.join(updates)}
                    WHERE storage_name = ?
                ''', values)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"[HealthPersistence] Error updating storage exclusion: {e}")
            return False
    
    def remove_storage_exclusion(self, storage_name: str) -> bool:
        """Remove a storage from the exclusion list."""
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM excluded_storages WHERE storage_name = ?
                ''', (storage_name,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"[HealthPersistence] Error removing storage exclusion: {e}")
            return False
    
    def get_excluded_storage_names(self, check_type: str = 'health') -> set:
        """
        Get set of storage names excluded for a specific check type.
        
        Args:
            check_type: 'health' or 'notifications'
        
        Returns:
            Set of excluded storage names
        """
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                column = 'exclude_health' if check_type == 'health' else 'exclude_notifications'
                cursor.execute(f'''
                    SELECT storage_name FROM excluded_storages 
                    WHERE {column} = 1
                ''')
                return {row[0] for row in cursor.fetchall()}
        except Exception:
            return set()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # NETWORK INTERFACE EXCLUSION MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_excluded_interfaces(self) -> List[Dict[str, Any]]:
        """Get list of all excluded network interfaces."""
        try:
            with self._db_connection(row_factory=True) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT interface_name, interface_type, excluded_at,
                           exclude_health, exclude_notifications, reason
                    FROM excluded_interfaces
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[HealthPersistence] Error getting excluded interfaces: {e}")
            return []
    
    def is_interface_excluded(self, interface_name: str, check_type: str = 'health') -> bool:
        """
        Check if a network interface is excluded from monitoring.
        
        Args:
            interface_name: Name of the interface (e.g., 'vmbr0', 'eth0')
            check_type: 'health' or 'notifications'
            
        Returns:
            True if the interface is excluded for the given check type
        """
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                column = 'exclude_health' if check_type == 'health' else 'exclude_notifications'
                cursor.execute(f'''
                    SELECT 1 FROM excluded_interfaces 
                    WHERE interface_name = ? AND {column} = 1
                ''', (interface_name,))
                return cursor.fetchone() is not None
        except Exception:
            return False
    
    def exclude_interface(self, interface_name: str, interface_type: str,
                         exclude_health: bool = True, exclude_notifications: bool = True,
                         reason: str = None) -> bool:
        """
        Add a network interface to the exclusion list.
        
        Args:
            interface_name: Name of the interface (e.g., 'vmbr0')
            interface_type: Type of interface ('bridge', 'physical', 'bond', 'vlan')
            exclude_health: Whether to exclude from health monitoring
            exclude_notifications: Whether to exclude from notifications
            reason: Optional reason for exclusion
            
        Returns:
            True if successful
        """
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO excluded_interfaces 
                    (interface_name, interface_type, excluded_at, exclude_health, exclude_notifications, reason)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    interface_name,
                    interface_type,
                    datetime.now().isoformat(),
                    1 if exclude_health else 0,
                    1 if exclude_notifications else 0,
                    reason
                ))
                conn.commit()
                print(f"[HealthPersistence] Interface {interface_name} added to exclusions")
                return True
        except Exception as e:
            print(f"[HealthPersistence] Error excluding interface: {e}")
            return False
    
    def update_interface_exclusion(self, interface_name: str, 
                                   exclude_health: bool, exclude_notifications: bool) -> bool:
        """Update exclusion settings for an interface."""
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE excluded_interfaces 
                    SET exclude_health = ?, exclude_notifications = ?
                    WHERE interface_name = ?
                ''', (1 if exclude_health else 0, 1 if exclude_notifications else 0, interface_name))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"[HealthPersistence] Error updating interface exclusion: {e}")
            return False
    
    def remove_interface_exclusion(self, interface_name: str) -> bool:
        """Remove an interface from the exclusion list."""
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM excluded_interfaces WHERE interface_name = ?', (interface_name,))
                conn.commit()
                removed = cursor.rowcount > 0
                if removed:
                    print(f"[HealthPersistence] Interface {interface_name} removed from exclusions")
                return removed
        except Exception as e:
            print(f"[HealthPersistence] Error removing interface exclusion: {e}")
            return False
    
    def get_excluded_interface_names(self, check_type: str = 'health') -> set:
        """
        Get set of interface names excluded for a specific check type.
        
        Args:
            check_type: 'health' or 'notifications'
            
        Returns:
            Set of excluded interface names
        """
        try:
            with self._db_connection() as conn:
                cursor = conn.cursor()
                column = 'exclude_health' if check_type == 'health' else 'exclude_notifications'
                cursor.execute(f'''
                    SELECT interface_name FROM excluded_interfaces 
                    WHERE {column} = 1
                ''')
                return {row[0] for row in cursor.fetchall()}
        except Exception:
            return set()


    def _clear_notification_cooldown(self, error_key: str):
        """
        Clear notification cooldown from notification_last_sent for non-disk errors.

        This coordinates with PollingCollector's 24h cooldown system.
        When any error is dismissed, we remove the corresponding cooldown entry
        so the error can be re-detected and re-notified after the suppression period expires.

        The PollingCollector uses 'health_' prefix for all its fingerprints.
        Audit Tier 5 (Health stack — `_clear_notification_cooldown` LIKE
        overmatch): the previous implementation had a fallback
        ``DELETE ... WHERE fingerprint LIKE '%<error_key>%'`` which broke as
        soon as two errors shared a substring (e.g. ``vm_1`` matched ``vm_10``,
        ``vm_100``, ``vm_1xyz``...). We drop that catch-all and rely on
        deterministic exact matches.
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # Match all the prefixes the PollingCollector uses for this key.
            # Anchored to the start, no wildcards inside, so we can never
            # over-match a different error.
            fingerprints = (
                error_key,
                f'health_{error_key}',
            )
            placeholders = ','.join('?' for _ in fingerprints)
            cursor.execute(
                f'DELETE FROM notification_last_sent WHERE fingerprint IN ({placeholders})',
                fingerprints,
            )

            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted_count > 0:
                print(f"[HealthPersistence] Cleared notification cooldowns for {error_key}")
        except Exception as e:
            print(f"[HealthPersistence] Error clearing notification cooldown: {e}")
    
    def _clear_disk_io_cooldown(self, error_key: str):
        """
        Clear disk I/O cooldowns from notification_last_sent when an error is dismissed.
        
        This coordinates with BOTH:
        1. JournalWatcher's 24h cooldown system (prefixes: diskio_, fs_, fs_serial_)
        2. PollingCollector's 24h cooldown system (prefix: health_)
        
        When a disk error is dismissed, we remove the corresponding cooldown entries
        so the error can be re-detected and re-notified after the suppression period expires.
        
        Matches fingerprints like:
        - diskio_sdh, diskio_sda, diskio_nvme0n1
        - fs_sdh1, fs_sda2, fs_serial_XXXXX
        - health_disk_smart_sdh, health_disk_io_error_sdh
        - sdh (direct device name used by JournalWatcher)
        """
        try:
            # Extract device name from error_key
            # Common patterns: disk_fs_sdh, disk_smart_sda, disk_io_error_sdh, smart_sdh
            import re
            device_match = re.search(r'(?:disk_fs_|disk_smart_|disk_io_error_|disk_|smart_|io_error_)(?:/dev/)?([a-z]{2,4}[a-z0-9]*)', error_key)
            if not device_match:
                # Try to extract device from error_key directly if no pattern matches
                # e.g., error_key might just be the device name
                device_match = re.match(r'^([a-z]{2,4}[a-z0-9]*)$', error_key)
                if not device_match:
                    return
            
            device = device_match.group(1)
            base_device = disk_base_name(device)  # sdh1 → sdh, nvme0n1p1 → nvme0n1
            
            # Build patterns to match in notification_last_sent
            # JournalWatcher uses: direct device name, diskio_, fs_, fs_serial_
            # PollingCollector uses: health_ prefix
            patterns = [
                # JournalWatcher patterns
                device,  # Direct device name (JournalWatcher._check_disk_io uses this)
                base_device,
                f'diskio_{device}',
                f'diskio_{base_device}',
                f'fs_{device}',
                f'fs_{base_device}',
                # PollingCollector patterns (uses health_ prefix)
                f'health_{error_key}',
                f'health_disk_smart_{device}',
                f'health_disk_smart_{base_device}',
                f'health_disk_io_error_{device}',
                f'health_disk_io_error_{base_device}',
                f'health_disk_fs_{device}',
                f'health_disk_fs_{base_device}',
            ]
            
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # Delete matching cooldown entries
            for pattern in patterns:
                cursor.execute(
                    'DELETE FROM notification_last_sent WHERE fingerprint = ?',
                    (pattern,)
                )
                # Also match with wildcards for serial-based keys
                cursor.execute(
                    'DELETE FROM notification_last_sent WHERE fingerprint LIKE ?',
                    (f'{pattern}%',)
                )
            
            # Also clear fingerprints that contain the device name anywhere
            # This catches edge cases like different fingerprint formats
            cursor.execute(
                'DELETE FROM notification_last_sent WHERE fingerprint LIKE ? OR fingerprint LIKE ?',
                (f'%{device}%', f'%{base_device}%' if base_device != device else f'%{device}%')
            )
            
            conn.commit()
            conn.close()
            print(f"[HealthPersistence] Cleared disk I/O cooldowns for {error_key} (device: {device})")
        except Exception as e:
            print(f"[HealthPersistence] Error clearing disk I/O cooldown: {e}")


# Global instance
health_persistence = HealthPersistence()
