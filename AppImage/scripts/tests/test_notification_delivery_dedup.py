import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import notification_manager  # noqa: E402
from notification_events import NotificationEvent  # noqa: E402


class RecordingChannel:
    def __init__(self, results=None):
        self.results = list(results or [True])
        self.calls = 0
        self.lock = threading.Lock()

    def send(self, title, body, severity, data):
        with self.lock:
            self.calls += 1
            success = self.results.pop(0) if self.results else True
        time.sleep(0.1)
        return {'success': success, 'error': '' if success else 'temporary failure'}


class NotificationDeliveryDedupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / 'health_monitor.db'
        conn = sqlite3.connect(str(self.db_path))
        conn.execute('''
            CREATE TABLE notification_last_sent (
                fingerprint TEXT PRIMARY KEY,
                last_sent_ts INTEGER NOT NULL,
                count INTEGER DEFAULT 1
            )
        ''')
        conn.execute('''
            CREATE TABLE notification_history (
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
        conn.commit()
        conn.close()
        self.db_patch = mock.patch.object(
            notification_manager, 'DB_PATH', self.db_path,
        )
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.ai_context_patch = mock.patch.object(
            notification_manager, 'enrich_context_for_ai', return_value='',
        )
        self.ai_context_patch.start()
        self.addCleanup(self.ai_context_patch.stop)
        self.ai_rewrite_patch = mock.patch.object(
            notification_manager, '_format_with_ai_bounded', return_value=None,
        )
        self.ai_rewrite_patch.start()
        self.addCleanup(self.ai_rewrite_patch.stop)

    def _manager(self, channel):
        manager = notification_manager.NotificationManager()
        manager._enabled = True
        manager._config = {
            'email.enabled': 'true',
            'email.rich_format': 'false',
            'ai_enabled': 'false',
        }
        manager._channels = {'email': channel}
        return manager

    @staticmethod
    def _event():
        return NotificationEvent(
            event_type='lxc_update_applied',
            severity='INFO',
            data={
                'hostname': 'pve-test',
                'vmid': 210,
                'ct_name': 'docker-frontend',
                'target': 'Docker Engine',
                'result': 'succeeded',
                'duration': '10s',
                'details': 'Update completed',
            },
            source='manual',
            entity='ct',
            entity_id='210:same-run',
        )

    def test_concurrent_managers_deliver_same_fingerprint_once(self):
        channel = RecordingChannel()
        managers = [self._manager(channel), self._manager(channel)]
        barrier = threading.Barrier(3)

        def dispatch(manager):
            barrier.wait()
            manager._dispatch_event(self._event())

        threads = [
            threading.Thread(target=dispatch, args=(manager,))
            for manager in managers
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(channel.calls, 1)
        conn = sqlite3.connect(str(self.db_path))
        history_count = conn.execute(
            'SELECT COUNT(*) FROM notification_history WHERE success = 1'
        ).fetchone()[0]
        claim_count = conn.execute(
            'SELECT COUNT(*) FROM notification_delivery_claims'
        ).fetchone()[0]
        conn.close()
        self.assertEqual(history_count, 1)
        self.assertEqual(claim_count, 0)

    def test_failed_delivery_releases_claim_for_retry(self):
        channel = RecordingChannel([False, True])
        manager = self._manager(channel)

        manager._dispatch_event(self._event())
        manager._dispatch_event(self._event())

        self.assertEqual(channel.calls, 2)
        conn = sqlite3.connect(str(self.db_path))
        successes = conn.execute(
            'SELECT success FROM notification_history ORDER BY id'
        ).fetchall()
        claim_count = conn.execute(
            'SELECT COUNT(*) FROM notification_delivery_claims'
        ).fetchone()[0]
        conn.close()
        self.assertEqual(successes, [(0,), (1,)])
        self.assertEqual(claim_count, 0)


if __name__ == '__main__':
    unittest.main()
