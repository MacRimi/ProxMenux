"""
Health Monitor Persistence Module
Manages persistent error tracking across AppImage updates using SQLite.
Stores errors in /root/.config/proxmenux-monitor/health_monitor.db

Features:
- Persistent error storage (survives AppImage updates)
- Smart error resolution (auto-clear when VM starts, or after 48h)
- Event system for future Telegram notifications
- Manual acknowledgment support

Author: MacRimi
Version: 1.0
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

class HealthPersistence:
    """Manages persistent health error tracking"""
    
    # Error retention periods (seconds)
    VM_ERROR_RETENTION = 48 * 3600  # 48 hours
    LOG_ERROR_RETENTION = 24 * 3600  # 24 hours
    DISK_ERROR_RETENTION = 48 * 3600  # 48 hours
    
    def __init__(self):
        """Initialize persistence with database in config directory"""
        self.data_dir = Path('/root/.config/proxmenux-monitor')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_path = self.data_dir / 'health_monitor.db'
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database with required tables"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
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
                acknowledged INTEGER DEFAULT 0,
                notification_sent INTEGER DEFAULT 0
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
        
        # Indexes for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_error_key ON errors(error_key)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON errors(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_resolved ON errors(resolved_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_error ON events(error_key)')
        
        conn.commit()
        conn.close()
    
    def record_error(self, error_key: str, category: str, severity: str, 
                    reason: str, details: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Record or update an error.
        Returns event info (new_error, updated, etc.)
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        details_json = json.dumps(details) if details else None
        
        cursor.execute('''
            SELECT acknowledged, resolved_at 
            FROM errors 
            WHERE error_key = ? AND acknowledged = 1
        ''', (error_key,))
        ack_check = cursor.fetchone()
        
        if ack_check and ack_check[1]:  # Has resolved_at timestamp
            try:
                resolved_dt = datetime.fromisoformat(ack_check[1])
                hours_since_ack = (datetime.now() - resolved_dt).total_seconds() / 3600
                
                if hours_since_ack < 24:
                    # Skip re-adding recently acknowledged errors (within 24h)
                    conn.close()
                    return {'type': 'skipped_acknowledged', 'needs_notification': False}
            except Exception:
                pass
        
        cursor.execute('''
            SELECT id, first_seen, notification_sent, acknowledged, resolved_at 
            FROM errors WHERE error_key = ?
        ''', (error_key,))
        existing = cursor.fetchone()
        
        event_info = {'type': 'updated', 'needs_notification': False}
        
        if existing:
            error_id, first_seen, notif_sent, acknowledged, resolved_at = existing
            
            if acknowledged == 1:
                conn.close()
                return {'type': 'skipped_acknowledged', 'needs_notification': False}
            
            # Update existing error (only if NOT acknowledged)
            cursor.execute('''
                UPDATE errors 
                SET last_seen = ?, severity = ?, reason = ?, details = ?
                WHERE error_key = ? AND acknowledged = 0
            ''', (now, severity, reason, details_json, error_key))
            
            # Check if severity escalated
            cursor.execute('SELECT severity FROM errors WHERE error_key = ?', (error_key,))
            old_severity_row = cursor.fetchone()
            if old_severity_row:
                old_severity = old_severity_row[0]
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
        
        # Record event
        self._record_event(cursor, event_info['type'], error_key, 
                          {'severity': severity, 'reason': reason})
        
        conn.commit()
        conn.close()
        
        return event_info
    
    def resolve_error(self, error_key: str, reason: str = 'auto-resolved'):
        """Mark an error as resolved"""
        conn = sqlite3.connect(str(self.db_path))
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
        conn.close()
    
    def acknowledge_error(self, error_key: str):
        """
        Manually acknowledge an error (won't notify again or re-appear for 24h).
        Also marks as resolved so it disappears from active errors.
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        cursor.execute('''
            UPDATE errors 
            SET acknowledged = 1, resolved_at = ?
            WHERE error_key = ?
        ''', (now, error_key))
        
        self._record_event(cursor, 'acknowledged', error_key, {})
        
        conn.commit()
        conn.close()
    
    def get_active_errors(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all active (unresolved) errors, optionally filtered by category"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if category:
            cursor.execute('''
                SELECT * FROM errors 
                WHERE resolved_at IS NULL AND category = ?
                ORDER BY severity DESC, last_seen DESC
            ''', (category,))
        else:
            cursor.execute('''
                SELECT * FROM errors 
                WHERE resolved_at IS NULL
                ORDER BY severity DESC, last_seen DESC
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
    
    def cleanup_old_errors(self):
        """Clean up old resolved errors and auto-resolve stale errors"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        now = datetime.now()
        
        # Delete resolved errors older than 7 days
        cutoff_resolved = (now - timedelta(days=7)).isoformat()
        cursor.execute('DELETE FROM errors WHERE resolved_at < ?', (cutoff_resolved,))
        
        # Auto-resolve VM/CT errors older than 48h
        cutoff_vm = (now - timedelta(seconds=self.VM_ERROR_RETENTION)).isoformat()
        cursor.execute('''
            UPDATE errors 
            SET resolved_at = ?
            WHERE category = 'vms' 
              AND resolved_at IS NULL 
              AND first_seen < ?
              AND acknowledged = 0
        ''', (now.isoformat(), cutoff_vm))
        
        # Auto-resolve log errors older than 24h
        cutoff_logs = (now - timedelta(seconds=self.LOG_ERROR_RETENTION)).isoformat()
        cursor.execute('''
            UPDATE errors 
            SET resolved_at = ?
            WHERE category = 'logs' 
              AND resolved_at IS NULL 
              AND first_seen < ?
              AND acknowledged = 0
        ''', (now.isoformat(), cutoff_logs))
        
        # Delete old events (>30 days)
        cutoff_events = (now - timedelta(days=30)).isoformat()
        cursor.execute('DELETE FROM events WHERE timestamp < ?', (cutoff_events,))
        
        conn.commit()
        conn.close()
    
    def check_vm_running(self, vm_id: str) -> bool:
        """
        Check if a VM/CT is running and resolve error if so.
        Returns True if running and error was resolved.
        """
        import subprocess
        
        try:
            # Check qm status for VMs
            result = subprocess.run(
                ['qm', 'status', vm_id],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0 and 'running' in result.stdout.lower():
                self.resolve_error(f'vm_{vm_id}', 'VM started')
                return True
            
            # Check pct status for containers
            result = subprocess.run(
                ['pct', 'status', vm_id],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0 and 'running' in result.stdout.lower():
                self.resolve_error(f'ct_{vm_id}', 'Container started')
                return True
            
            return False
            
        except Exception:
            return False
    
    def _record_event(self, cursor, event_type: str, error_key: str, data: Dict):
        """Internal: Record an event"""
        cursor.execute('''
            INSERT INTO events (event_type, error_key, timestamp, data)
            VALUES (?, ?, ?, ?)
        ''', (event_type, error_key, datetime.now().isoformat(), json.dumps(data)))
    
    def get_unnotified_errors(self) -> List[Dict[str, Any]]:
        """Get errors that need Telegram notification"""
        conn = sqlite3.connect(str(self.db_path))
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
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE errors 
            SET notification_sent = 1
            WHERE error_key = ?
        ''', (error_key,))
        
        conn.commit()
        conn.close()


# Global instance
health_persistence = HealthPersistence()
