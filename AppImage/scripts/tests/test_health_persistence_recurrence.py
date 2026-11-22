"""Offline recurrence tests against the complete, real persistence module.

From the repository root (stdlib only; no broad test discovery):
    python3 -I -m unittest discover \
        -s AppImage/scripts/tests -p test_health_persistence_recurrence.py -v

Each test creates and removes its own private temporary directory.
No temporary-directory environment variable is required.
Only the data-directory Path boundary and datetime clock are redirected, before
module execution (including the real global constructor). No persistence method
is stubbed. Every test has its own real SQLite DB. Audit guards constrain DB
connections and file opens, restrict mkdir/remove/rmdir/rename to the fixture,
and reject subprocess/socket operations. Metadata/existence probes (for example
os.path.exists) are not comprehensively guarded; synthetic keys avoid VM/disk
resource-existence checks. Read opens are limited to fixture/source/stdlib paths
except the nonexistent synthetic traceback filename described in the guard.
These are synthetic recorder tests, not transport, UI or deployment validation.
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch


# Keep import bytecode writes outside the offline fixture from tripping the guard.
sys.dont_write_bytecode = True

# Use the concrete platform class while pathlib.Path is temporarily replaced.
# Python 3.11's abstract Path.__new__ consults the patched module-level name.
Path = type(Path())
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'AppImage/scripts/health_persistence.py'
_AUDIT_SCOPE = None


class BoundaryViolation(RuntimeError):
    pass


def _audit_guard(event, args):
    scope = _AUDIT_SCOPE
    if scope is None:
        return

    def reject():
        scope['blocked'].append((event, repr(args)))
        raise BoundaryViolation('Offline fixture rejected ' + event)

    def inside(path, directory):
        return Path(os.fsdecode(path)).resolve().is_relative_to(directory)

    if event.startswith(('socket.', 'subprocess.', 'os.system', 'os.exec',
                         'os.spawn', 'os.fork', 'pty.')):
        reject()
    if event == 'sqlite3.connect':
        if Path(os.fsdecode(args[0])).resolve() != scope['db']:
            reject()
        scope['connections'].append(str(args[0]))
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, int):
            reject()
        writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
            isinstance(flags, int) and flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        if writing:
            if not inside(path, scope['root']):
                reject()
        elif not any(inside(path, directory) for directory in (
                scope['root'], ROOT, Path(sys.base_prefix) / 'lib')):
            # unittest traceback formatting may ask tokenize to read this exact
            # synthetic name. Permit only the harmless missing-file read; an
            # existing file or even a dangling symlink must still be rejected.
            if not (path == '<unknown>' and mode == 'rb' and flags == 0
                    and not os.path.lexists(path)):
                reject()
    if event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.rename'):
        paths = args[:2] if event == 'os.rename' else args[:1]
        if not all(inside(path, scope['root']) for path in paths):
            reject()


sys.addaudithook(_audit_guard)


class FrozenDatetime(datetime):
    current = datetime(2026, 10, 1, 12)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            raise AssertionError('Unexpected timezone request')
        return cls.current


class HealthPersistenceRecurrenceTests(unittest.TestCase):
    def setUp(self):
        global _AUDIT_SCOPE
        temporary = tempfile.TemporaryDirectory(prefix='health-recurrence-')
        self.addCleanup(temporary.cleanup)
        self.data_dir = Path(temporary.name)
        self.scope = {'root': self.data_dir, 'db': self.data_dir / 'health_monitor.db',
                      'blocked': [], 'connections': []}
        _AUDIT_SCOPE = self.scope
        self.addCleanup(self.finish_isolation)
        FrozenDatetime.current = datetime(2026, 10, 1, 12)

        def redirected_path(*args, **kwargs):
            if args == ('/usr/local/share/proxmenux',):
                return self.data_dir
            return Path(*args, **kwargs)

        spec = importlib.util.spec_from_file_location('offline_health_persistence', SOURCE)
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        with patch('pathlib.Path', redirected_path), \
                patch('datetime.datetime', FrozenDatetime), \
                contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(self.module)
        self.db = self.module.health_persistence
        self.assertEqual(self.db.db_path, self.scope['db'])

    def finish_isolation(self):
        global _AUDIT_SCOPE
        _AUDIT_SCOPE = None
        self.assertEqual(self.scope['blocked'], [], 'Even swallowed boundary violations fail')
        self.assertTrue(self.scope['connections'], 'The real SQLite constructor must run')

    def advance(self, **kwargs):
        FrozenDatetime.current += timedelta(**kwargs)

    def record(self, key='security_updates', category='updates', severity='INFO',
               reason='Synthetic condition', details=None):
        return self.db.record_error(key, category, severity, reason, details)

    def snapshot(self):
        # Independent fresh SQLite connection verifies durable, committed state.
        conn = sqlite3.connect(str(self.db.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = [dict(row) for row in conn.execute('SELECT * FROM errors ORDER BY id')]
            events = [dict(row) for row in conn.execute('SELECT * FROM events ORDER BY id')]
            for event in events:
                event['data'] = json.loads(event['data'])
            return rows, events
        finally:
            conn.close()

    def test_notified_resolved_condition_returns_as_a_fresh_episode(self):
        key = 'security_updates'
        self.assertEqual(self.record(), {'type': 'new', 'needs_notification': True})
        self.db.mark_notified(key)
        self.advance(minutes=1)
        self.db.resolve_error(key, 'Synthetic condition absent')
        self.assertEqual(self.db.get_active_errors(), [])
        self.assertEqual(self.db.get_unnotified_errors(), [])
        self.advance(minutes=1)
        details = {'name': 'offline fixture', 'synthetic': True, 'pending': 3}
        result = self.record(reason='Synthetic condition returned', details=details)
        rows, events = self.snapshot()
        self.assertIsNone(rows[0]['resolved_at'], 'Resolved condition must reactivate')
        self.assertEqual(result, {'type': 'new', 'needs_notification': True})
        row = rows[0]
        self.assertEqual(len(rows), 1)
        self.assertEqual(row['first_seen'], FrozenDatetime.current.isoformat())
        self.assertEqual(row['last_seen'], FrozenDatetime.current.isoformat())
        self.assertEqual(row['notification_sent'], 0)
        self.assertEqual(row['acknowledged'], 0)
        self.assertIsNone(row['resolution_type'])
        self.assertIsNone(row['resolution_reason'])
        self.assertEqual(json.loads(row['details']), details)
        self.assertTrue(self.db.is_error_active(key, 'updates'))
        self.assertEqual(self.db.get_error_by_key(key)['reason'], 'Synthetic condition returned')
        self.assertEqual([e['error_key'] for e in self.db.get_active_errors('updates')], [key])
        self.assertEqual([e['error_key'] for e in self.db.get_unnotified_errors()], [key])
        self.assertEqual([event['event_type'] for event in events], ['new', 'resolved', 'new'])
        self.assertEqual(events[-1]['data']['details'], details)
        self.assertEqual(events[-1]['data']['entity'], 'offline fixture')

    def test_resolve_and_clear_recurrence_matrix(self):
        for severity in ('INFO', 'WARNING', 'CRITICAL'):
            for route in ('resolve_error', 'clear_error'):
                for notified in (False, True):
                    key = f'fixture_{severity}_{route}_{notified}'
                    with self.subTest(severity=severity, route=route, notified=notified):
                        self.record(key=key, severity=severity)
                        if notified:
                            self.db.mark_notified(key)
                        self.advance(minutes=1)
                        getattr(self.db, route)(key)
                        self.assertFalse(self.db.is_error_active(key))
                        self.advance(minutes=1)
                        self.assertEqual(self.record(key=key, severity=severity),
                                         {'type': 'new', 'needs_notification': True})
                        row = self.db.get_error_by_key(key)
                        self.assertIsNotNone(row)
                        for field in ('resolved_at', 'resolution_type', 'resolution_reason',
                                      'acknowledged_at'):
                            self.assertIsNone(row[field], field)
                        self.assertEqual(row['notification_sent'], 0)
                        self.assertEqual(row['acknowledged'], 0)
                        self.assertEqual(row['first_seen'], FrozenDatetime.current.isoformat())
                        self.assertEqual(row['last_seen'], row['first_seen'])
                        self.assertIn(key, [e['error_key'] for e in self.db.get_unnotified_errors()])
                        rows, events = self.snapshot()
                        self.assertEqual(sum(row['error_key'] == key for row in rows), 1)
                        self.assertEqual([e['event_type'] for e in events if e['error_key'] == key],
                                         ['new', 'resolved' if route == 'resolve_error' else 'cleared', 'new'])

    def test_repeated_polls_after_reopening_rearm_only_once(self):
        key = 'security_updates'
        self.record()
        self.db.mark_notified(key)
        self.db.resolve_error(key)
        self.advance(minutes=1)
        self.assertEqual(self.record(), {'type': 'new', 'needs_notification': True})
        first_seen = self.db.get_error_by_key(key)['first_seen']
        for poll in range(4):
            self.advance(minutes=1)
            self.assertEqual(self.record(), {'type': 'updated', 'needs_notification': False})
            self.assertEqual(self.db.get_error_by_key(key)['first_seen'], first_seen)
            self.assertEqual(self.db.get_error_by_key(key)['notification_sent'], int(poll > 0))
            if poll == 0:
                self.db.mark_notified(key)
        rows, events = self.snapshot()
        self.assertEqual(len(rows), 1)
        self.assertEqual([e['event_type'] for e in events],
                         ['new', 'resolved', 'new'] + ['updated'] * 4)
        self.assertEqual(self.db.get_unnotified_errors(), [])
        # A second real constructor sees exactly the same committed episode/history.
        with contextlib.redirect_stdout(io.StringIO()):
            self.db = self.module.HealthPersistence()
        self.assertEqual(self.snapshot(), (rows, events))
        self.assertTrue(self.db.is_error_active(key))
        self.assertEqual(self.db.get_unnotified_errors(), [])

    def test_same_key_can_resolve_and_recur_twice(self):
        key = 'security_updates'
        self.record()
        for _ in range(2):
            self.db.mark_notified(key)
            self.advance(minutes=1)
            self.db.resolve_error(key, 'Synthetic recovery')
            resolved = self.snapshot()
            self.db.resolve_error(key, 'Duplicate recovery poll')
            self.assertEqual(self.snapshot(), resolved)
            self.advance(minutes=1)
            self.assertEqual(self.record(), {'type': 'new', 'needs_notification': True})
            self.assertEqual(self.db.get_error_by_key(key)['notification_sent'], 0)
        rows, events = self.snapshot()
        self.assertEqual(len(rows), 1)
        self.assertEqual([e['event_type'] for e in events],
                         ['new', 'resolved', 'new', 'resolved', 'new'])
        self.assertEqual([e['data']['reason'] for e in events if e['event_type'] == 'resolved'],
                         ['Synthetic recovery', 'Synthetic recovery'])

    def test_active_polls_preserve_existing_episode_and_notification_state(self):
        for severity in ('INFO', 'WARNING'):
            for notified in (False, True):
                key = f'fixture_active_{severity}_{notified}'
                with self.subTest(severity=severity, notified=notified):
                    self.record(key=key, severity=severity)
                    if notified:
                        self.db.mark_notified(key)
                    before = self.db.get_error_by_key(key)
                    self.advance(minutes=1)
                    self.assertEqual(self.record(key=key, severity=severity, reason='Next poll'),
                                     {'type': 'updated', 'needs_notification': False})
                    after = self.db.get_error_by_key(key)
                    for field in ('first_seen', 'notification_sent', 'acknowledged',
                                  'resolved_at', 'resolution_type', 'resolution_reason'):
                        self.assertEqual(after[field], before[field], field)
                    self.assertEqual(after['last_seen'], FrozenDatetime.current.isoformat())
                    self.assertEqual(after['reason'], 'Next poll')

    def test_active_warning_escalation_is_unchanged(self):
        self.record(severity='WARNING')
        self.db.mark_notified('security_updates')
        before = self.db.get_error_by_key('security_updates')
        self.advance(minutes=1)
        self.assertEqual(self.record(severity='CRITICAL'),
                         {'type': 'escalated', 'needs_notification': True})
        after = self.db.get_error_by_key('security_updates')
        self.assertEqual(after['first_seen'], before['first_seen'])
        self.assertEqual(after['notification_sent'], 1)
        self.assertIsNone(after['resolved_at'])

    def test_acknowledged_rows_within_window_are_untouched(self):
        for resolved in (False, True):
            key = f'fixture_timed_{resolved}'
            with self.subTest(resolved=resolved):
                self.record(key=key, severity='WARNING')
                self.db.mark_notified(key)
                self.db.acknowledge_error(key, suppression_hours=24)
                if resolved:
                    self.db.resolve_error(key)
                before = self.snapshot()
                self.advance(hours=23)
                self.assertEqual(self.record(key=key, severity='CRITICAL'),
                                 {'type': 'skipped_acknowledged', 'needs_notification': False})
                self.assertEqual(self.snapshot(), before)
                self.assertTrue(self.db.is_error_acknowledged(key))
                self.assertTrue(self.db.is_error_active(key))

    def test_permanent_dismissal_survives_recovery_and_recurrence(self):
        for resolved_before_dismiss in (False, True):
            key = f'fixture_permanent_{resolved_before_dismiss}'
            with self.subTest(resolved_before_dismiss=resolved_before_dismiss):
                self.db.set_setting('suppress_updates', '24')
                self.record(key=key, severity='WARNING')
                self.db.mark_notified(key)
                if resolved_before_dismiss:
                    self.db.resolve_error(key)
                self.db.acknowledge_error(key, suppression_hours=-1)
                before = self.snapshot()
                self.db.clear_error(key)
                self.db.resolve_error(key)
                self.advance(days=30)
                self.db.set_setting('suppress_updates', '48')
                self.assertEqual(self.record(key=key, severity='CRITICAL'),
                                 {'type': 'skipped_acknowledged', 'needs_notification': False})
                self.assertEqual(self.snapshot(), before)
                self.assertTrue(self.db.is_error_permanently_acknowledged(key))
                self.assertEqual(self.db.get_active_errors(), [])
                self.assertEqual(self.db.get_unnotified_errors(), [])

    def test_expired_resolved_dismissal_rearms_once(self):
        key = 'security_updates'
        self.record(severity='WARNING')
        self.db.mark_notified(key)
        self.db.acknowledge_error(key, suppression_hours=24)
        self.db.resolve_error(key)
        self.advance(hours=25)
        self.assertEqual(self.record(severity='WARNING'),
                         {'type': 'new', 'needs_notification': True})
        row = self.db.get_error_by_key(key)
        self.assertEqual(row['first_seen'], FrozenDatetime.current.isoformat())
        self.assertIsNone(row['resolved_at'])
        self.assertEqual(row['acknowledged'], 0)
        self.assertEqual(row['notification_sent'], 0)
        self.assertEqual(self.record(severity='WARNING'),
                         {'type': 'updated', 'needs_notification': False})
        self.assertEqual([e['event_type'] for e in self.snapshot()[1]],
                         ['new', 'acknowledged', 'resolved', 'new', 'updated'])

    def test_recurrence_uses_current_category_auto_suppression(self):
        for category, setting in (('updates', 'suppress_updates'), ('memory', 'suppress_memory')):
            for hours in (48, -1):
                key = f'fixture_auto_{category}_{hours}'
                with self.subTest(category=category, hours=hours):
                    # Establish each case independently, even if an earlier
                    # subtest failed before it could restore shared settings.
                    self.db.set_setting(setting, '24')
                    self.record(key=key, category=category, severity='WARNING')
                    self.db.mark_notified(key)
                    self.db.resolve_error(key)
                    self.db.set_setting(setting, str(hours))
                    self.advance(minutes=1)
                    self.assertEqual(self.record(key=key, category=category, severity='WARNING'),
                                     {'type': 'auto_suppressed', 'needs_notification': False})
                    rows, events = self.snapshot()
                    row = next(row for row in rows if row['error_key'] == key)
                    self.assertIsNone(row['resolved_at'])
                    self.assertIsNone(row['resolution_type'])
                    self.assertIsNone(row['resolution_reason'])
                    self.assertEqual(row['notification_sent'], 0)
                    self.assertEqual(row['acknowledged'], 1)
                    self.assertEqual(row['suppression_hours'], hours)
                    self.assertEqual(row['first_seen'], FrozenDatetime.current.isoformat())
                    self.assertEqual(row['acknowledged_at'], row['first_seen'])
                    self.assertEqual([e['event_type'] for e in events if e['error_key'] == key],
                                     ['new', 'resolved', 'auto_suppressed'])
                    before = self.snapshot()
                    self.assertEqual(self.record(key=key, category=category, severity='WARNING'),
                                     {'type': 'skipped_acknowledged', 'needs_notification': False})
                    self.assertEqual(self.snapshot(), before)
                    self.assertNotIn(key, [e['error_key'] for e in self.db.get_active_errors()])
                    self.assertNotIn(key, [e['error_key'] for e in self.db.get_unnotified_errors()])
                    self.db.set_setting(setting, '24')

    def test_critical_cpu_recurrence_bypasses_category_auto_suppression(self):
        key = 'cpu_temperature'
        self.record(key=key, category='temperature', severity='WARNING')
        self.db.mark_notified(key)
        self.db.resolve_error(key)
        self.db.set_setting('suppress_cpu', '-1')
        self.advance(minutes=1)
        self.assertEqual(self.record(key=key, category='temperature', severity='CRITICAL'),
                         {'type': 'new', 'needs_notification': True})
        row = self.db.get_error_by_key(key)
        self.assertEqual(row['acknowledged'], 0)
        self.assertEqual(row['notification_sent'], 0)
        self.assertIsNone(row['resolved_at'])
        self.assertEqual(self.record(key=key, category='temperature', severity='CRITICAL'),
                         {'type': 'updated', 'needs_notification': False})

    def test_critical_cpu_override_of_permanent_dismissal_is_unchanged(self):
        key = 'cpu_temperature'
        self.record(key=key, category='temperature', severity='WARNING')
        self.db.acknowledge_error(key, suppression_hours=-1)
        self.db.clear_error(key)
        self.db.resolve_error(key)
        self.db.set_setting('suppress_cpu', '-1')
        self.advance(minutes=1)
        self.assertEqual(self.record(key=key, category='temperature', severity='CRITICAL'),
                         {'type': 'new', 'needs_notification': True})
        row = self.db.get_error_by_key(key)
        self.assertEqual(row['acknowledged'], 0)
        self.assertEqual(row['notification_sent'], 0)
        self.assertIsNone(row['resolved_at'])
        self.assertEqual([e['event_type'] for e in self.snapshot()[1]],
                         ['new', 'acknowledged', 'new'])

    def test_reopening_one_key_preserves_other_rows_and_delivery_state(self):
        self.record()
        self.record(key='security_updates_other', severity='WARNING')
        self.db.mark_notified('security_updates_other')
        self.db.resolve_error('security_updates')
        other = self.db.get_error_by_key('security_updates_other')
        conn = sqlite3.connect(str(self.db.db_path))
        try:
            conn.execute('INSERT INTO notification_delivery_claims VALUES (?, ?, ?)',
                         ('health_security_updates', 'in-flight-token', 123))
            conn.execute('INSERT INTO notification_last_sent VALUES (?, ?, ?)',
                         ('health_security_updates', 123, 1))
            conn.commit()
            self.advance(minutes=1)
            self.record()
            self.assertEqual(self.db.get_error_by_key('security_updates_other'), other)
            self.assertEqual(conn.execute('SELECT * FROM notification_delivery_claims').fetchall(),
                             [('health_security_updates', 'in-flight-token', 123)])
            self.assertEqual(conn.execute('SELECT * FROM notification_last_sent').fetchall(),
                             [('health_security_updates', 123, 1)])
        finally:
            conn.close()

    def test_failed_reopening_rolls_back_without_losing_resolved_episode(self):
        self.record()
        self.db.mark_notified('security_updates')
        self.db.resolve_error('security_updates')
        before = self.snapshot()
        conn = sqlite3.connect(str(self.db.db_path))
        try:
            conn.execute('''CREATE TRIGGER fixture_reject_new_episode BEFORE INSERT ON errors
                            BEGIN SELECT RAISE(ABORT, 'fixture rejects insert'); END''')
            conn.commit()
        finally:
            conn.close()
        self.advance(minutes=1)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'fixture rejects insert'):
            self.record()
        self.assertEqual(self.snapshot(), before)

    def test_failed_new_event_rolls_back_reopened_row_and_history(self):
        self.record()
        self.db.mark_notified('security_updates')
        self.db.resolve_error('security_updates')
        before = self.snapshot()
        old_id = before[0][0]['id']
        self.assertEqual([event['event_type'] for event in before[1]], ['new', 'resolved'])
        conn = sqlite3.connect(str(self.db.db_path))
        try:
            # Fail at the later durable-event insert, only after the old row
            # has been replaced by the fresh episode within this transaction.
            conn.execute(f'''CREATE TRIGGER fixture_reject_new_event BEFORE INSERT ON events
                             WHEN NEW.event_type = 'new' AND NEW.error_key = 'security_updates'
                             BEGIN
                                 SELECT RAISE(ABORT, 'fixture rejects new event')
                                 WHERE EXISTS (
                                     SELECT 1 FROM errors
                                     WHERE error_key = NEW.error_key AND id <> {old_id}
                                       AND resolved_at IS NULL AND first_seen = NEW.timestamp
                                 );
                             END''')
            conn.commit()
        finally:
            conn.close()
        self.advance(minutes=1)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'fixture rejects new event'):
            self.record()
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
