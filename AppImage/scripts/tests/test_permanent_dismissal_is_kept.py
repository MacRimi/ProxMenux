"""An alert dismissed permanently stays dismissed until the user re-enables
it: not seeing it for a while, the condition recovering or a change of the
suppression settings does not bring it back."""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from health_fixture_modules import load_health_persistence

KEY = 'pve_storage_full_local-lvm'


class PermanentDismissalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.module = load_health_persistence(tmp.name)
        self.store = self.module.health_persistence

    def seen(self):
        return self.store.record_error(KEY, 'storage', 'WARNING', 'PVE storage local-lvm (lvmthin) at 96.0% used',
                                       {'storage_name': 'local-lvm'})

    def days_pass(self, days):
        """Moves every date of the record back, as if that time had gone by."""
        conn = self.store._get_conn()
        row = conn.execute('SELECT first_seen, last_seen, acknowledged_at, resolved_at FROM errors WHERE error_key = ?',
                           (KEY,)).fetchone()
        if row:
            moved = [(datetime.fromisoformat(v) - timedelta(days=days)).isoformat() if v else None for v in row]
            conn.execute('UPDATE errors SET first_seen = ?, last_seen = ?, acknowledged_at = ?, resolved_at = ? '
                         'WHERE error_key = ?', (*moved, KEY))
            conn.commit()
        conn.close()

    def cleanup(self):
        with patch('builtins.print'), \
                patch('subprocess.run', side_effect=OSError('no host tools in the test')), \
                patch.dict(sys.modules, {'psutil': ModuleType('psutil')}), \
                patch.object(self.module, 'open', side_effect=OSError('no host probes in the test'), create=True):
            self.store.cleanup_old_errors()

    def test_it_is_still_dismissed_weeks_later(self):
        self.assertTrue(self.seen()['needs_notification'])
        self.store.acknowledge_error(KEY, suppression_hours=-1)
        for _ in range(6):
            self.days_pass(8)
            self.cleanup()
            self.assertFalse(self.seen()['needs_notification'])
        self.assertTrue(self.store.is_error_permanently_acknowledged(KEY))

    def test_a_condition_that_recovers_and_returns_stays_dismissed(self):
        self.seen()
        self.store.acknowledge_error(KEY, suppression_hours=-1)
        self.store.clear_error(KEY)
        self.store.resolve_error(KEY, 'condition recovered')
        self.days_pass(8)
        self.cleanup()
        self.assertFalse(self.seen()['needs_notification'])
        self.assertTrue(self.store.is_error_permanently_acknowledged(KEY))

    def test_a_record_already_closed_for_its_age_is_kept(self):
        self.seen()
        self.store.acknowledge_error(KEY, suppression_hours=-1)
        conn = self.store._get_conn()
        closed = (datetime.now() - timedelta(days=8)).isoformat()
        conn.execute("UPDATE errors SET resolved_at = ?, resolution_type = 'auto', "
                     "resolution_reason = 'Stale error (no activity >7d)' WHERE error_key = ?", (closed, KEY))
        conn.commit()
        conn.close()
        self.cleanup()
        self.assertFalse(self.seen()['needs_notification'])

    def test_saving_the_suppression_settings_leaves_it_permanent(self):
        self.seen()
        self.store.acknowledge_error(KEY, suppression_hours=-1)
        with patch('builtins.print'):
            self.store.sync_dismissed_suppression()
        self.assertTrue(self.store.is_error_permanently_acknowledged(KEY))

    def test_re_enabling_it_brings_the_alert_back(self):
        self.seen()
        self.store.acknowledge_error(KEY, suppression_hours=-1)
        self.store.unacknowledge_error(KEY)
        self.assertFalse(self.store.is_error_permanently_acknowledged(KEY))

    def test_a_timed_dismissal_still_ends(self):
        self.seen()
        self.store.acknowledge_error(KEY, suppression_hours=24)
        self.days_pass(2)
        self.assertTrue(self.seen()['needs_notification'])


if __name__ == '__main__':
    unittest.main()
