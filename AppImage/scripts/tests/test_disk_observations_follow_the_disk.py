"""The observations of a disk belong to its serial number, not to the
connector it is plugged in."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
# The module opens the database of the host when it is imported.
_connect = sqlite3.connect
with patch.object(Path, 'mkdir'), patch('builtins.print'), \
        patch('sqlite3.connect', side_effect=lambda *args, **kwargs: _connect(':memory:')):
    import health_persistence as hp_module


class DiskObservationIdentityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = hp_module.HealthPersistence.__new__(hp_module.HealthPersistence)
        for name, value in vars(hp_module.health_persistence).items():
            setattr(store, name, value)
        store.data_dir = Path(tmp.name)
        store.db_path = store.data_dir / 'health_monitor.db'
        with patch('builtins.print'):
            store._init_database()
        self.store = store

    def record(self, device, serial, signature):
        self.store.register_disk(device, serial)
        self.store.record_disk_observation(device, serial, 'io_error', signature, f'{signature} on {device}')

    def seen(self, device, serial=None):
        return sorted(o['error_signature'] for o in self.store.get_disk_observations(device, serial))

    def set_time(self, table, column, value, where, params):
        conn = self.store._get_conn()
        conn.execute(f'UPDATE {table} SET {column} = ? WHERE {where}', (value, *params))
        conn.commit()
        conn.close()

    def test_a_new_disk_in_the_same_connector_starts_clean(self):
        self.record('sdb', 'OLD-BAD', 'pending_sectors')
        self.record('sdb', 'OLD-BAD', 'read_error')
        # The disk is replaced: the same name, another serial.
        self.store.register_disk('sdb', 'NEW-GOOD', 'WDC', 0)
        self.store.mark_removed_disks(['sdb'], {'sdb': 'NEW-GOOD'})
        self.assertEqual(self.seen('sdb', 'NEW-GOOD'), [])
        self.assertEqual(self.store.count_disk_observations('sdb', 'NEW-GOOD'), 0)
        # Its history is kept, and is back if the disk is.
        self.assertEqual(self.seen('sdb', 'OLD-BAD'), ['pending_sectors', 'read_error'])

    def test_the_interface_asking_without_a_serial_gets_the_disk_that_is_there_now(self):
        self.record('sdb', 'OLD-BAD', 'pending_sectors')
        self.set_time('disk_registry', 'last_seen', '2026-01-01T00:00:00', 'serial = ?', ('OLD-BAD',))
        self.store.register_disk('sdb', 'NEW-GOOD')
        self.store.mark_removed_disks(['sdb'], {'sdb': 'NEW-GOOD'})
        self.assertEqual(self.seen('sdb'), [])
        self.record('sdb', 'NEW-GOOD', 'crc_error')
        self.assertEqual(self.seen('sdb'), ['crc_error'])

    def test_an_error_logged_without_a_serial_goes_to_the_disk_that_is_there_now(self):
        self.record('sdb', 'OLD-BAD', 'pending_sectors')
        self.set_time('disk_registry', 'last_seen', '2026-01-01T00:00:00', 'serial = ?', ('OLD-BAD',))
        self.store.register_disk('sdb', 'NEW-GOOD')
        self.store.mark_removed_disks(['sdb'], {'sdb': 'NEW-GOOD'})
        # The kernel log names the device only.
        self.store.record_disk_observation('sdb', None, 'io_error', 'crc_error', 'crc on sdb')
        self.assertEqual(self.seen('sdb', 'NEW-GOOD'), ['crc_error'])
        self.assertEqual(self.seen('sdb', 'OLD-BAD'), ['pending_sectors'])

    def test_the_history_follows_a_disk_to_another_name(self):
        self.record('nvme4n1', 'SN-A', 'media_error')
        self.store.register_disk('nvme0n1', 'SN-A')
        self.store.register_disk('nvme4n1', 'SN-B')
        self.assertEqual(self.seen('nvme0n1', 'SN-A'), ['media_error'])
        self.assertEqual(self.store.count_disk_observations('nvme0n1', 'SN-A'), 1)
        self.assertEqual(self.seen('nvme4n1', 'SN-B'), [])

    def test_observations_without_a_serial_stay_with_the_only_disk_ever_seen_there(self):
        # Recorded before the serial of the disk was known.
        self.store.record_disk_observation('sdc', None, 'io_error', 'early_error', 'early')
        self.store.register_disk('sdc', 'ONLY-ONE')
        self.assertEqual(self.seen('sdc', 'ONLY-ONE'), ['early_error'])

    def test_observations_without_a_serial_older_than_the_previous_disk_are_not_the_new_one(self):
        self.store.record_disk_observation('sdc', None, 'io_error', 'old_unnamed', 'old')
        self.set_time('disk_observations', 'last_occurrence', '2026-01-01T00:00:00', '1 = 1', ())
        self.store.register_disk('sdc', 'PREVIOUS')
        self.set_time('disk_registry', 'last_seen', '2026-02-01T00:00:00', 'serial = ?', ('PREVIOUS',))
        self.store.register_disk('sdc', 'CURRENT')
        self.assertEqual(self.seen('sdc', 'CURRENT'), [])
        self.store.record_disk_observation('sdc', None, 'io_error', 'new_error', 'new')
        self.assertEqual(self.seen('sdc', 'CURRENT'), ['new_error'])

    def test_an_unread_serial_identifies_no_disk(self):
        self.record('sda', 'Unknown', 'error_on_sda')
        self.record('sdd', 'Unknown', 'error_on_sdd')
        self.assertEqual(self.seen('sda', 'Unknown'), ['error_on_sda'])
        self.assertEqual(self.seen('sdd'), ['error_on_sdd'])
        self.assertEqual(self.store.count_disk_observations('sda', 'Unknown'), 1)

    def test_each_different_observation_is_a_row_and_a_repeated_one_adds_to_its_count(self):
        self.record('sdb', 'SN-1', 'read_error')
        self.record('sdb', 'SN-1', 'read_error')
        self.record('sdb', 'SN-1', 'read_error')
        self.record('sdb', 'SN-1', 'crc_error')
        listed = {o['error_signature']: o['occurrence_count'] for o in self.store.get_disk_observations('sdb', 'SN-1')}
        self.assertEqual(listed, {'read_error': 3, 'crc_error': 1})
        self.assertEqual(self.store.count_disk_observations('sdb', 'SN-1'), 2)

    def test_an_observation_cannot_be_dismissed(self):
        for name in ('dismiss_disk_observation', 'cleanup_stale_observations', 'cleanup_orphan_observations'):
            self.assertFalse(hasattr(self.store, name), name)
        self.record('sdb', 'SN-1', 'read_error')
        self.assertNotIn('dismissed', self.store.get_disk_observations('sdb', 'SN-1')[0])
        routes = (SCRIPTS / 'flask_health_routes.py').read_text() + (SCRIPTS / 'flask_server.py').read_text()
        self.assertNotIn('cleanup_orphan_observations', routes)
        self.assertNotIn('cleanup_stale_observations', routes)
        panel = (SCRIPTS.parent / 'components/storage-overview.tsx').read_text()
        self.assertNotIn('obs.dismissed', panel)

    def test_an_old_observation_is_never_hidden(self):
        self.record('sdb', 'SN-1', 'read_error')
        self.set_time('disk_observations', 'last_occurrence', '2020-01-01T00:00:00', '1 = 1', ())
        self.assertEqual(self.seen('sdb', 'SN-1'), ['read_error'])
        self.assertEqual(self.store.count_disk_observations('sdb', 'SN-1'), 1)

    def test_what_earlier_versions_hid_is_in_the_history_again(self):
        self.record('sdb', 'SN-1', 'read_error')
        conn = self.store._get_conn()
        conn.execute('UPDATE disk_observations SET dismissed = 1')
        conn.execute("DELETE FROM user_settings WHERE setting_key = 'observation_history_version'")
        conn.commit()
        conn.close()
        # Listed whatever the old mark says, and the mark is taken off.
        self.assertEqual(self.seen('sdb', 'SN-1'), ['read_error'])
        self.assertEqual(self.store.count_disk_observations('sdb', 'SN-1'), 1)
        with patch('builtins.print'):
            self.store._init_database()
        conn = self.store._get_conn()
        marked = conn.execute('SELECT COUNT(*) FROM disk_observations WHERE dismissed = 1').fetchone()[0]
        conn.close()
        self.assertEqual(marked, 0)


class AuditAttributionTests(unittest.TestCase):
    def test_the_audit_lists_the_events_of_the_disk_that_is_there_now(self):
        import types
        import audit_inventory
        asked = []

        def getter(name=None, serial=None):
            asked.append((name, serial))
            return [{'error_type': 'io_error', 'severity': 'warning', 'occurrence_count': 3,
                     'first_occurrence': '2026-10-01T00:00:00', 'last_occurrence': '2026-10-02T00:00:00',
                     'raw_message': 'crc'}] if serial == 'NEW-GOOD' else []
        server = types.SimpleNamespace(health_persistence=types.SimpleNamespace(get_disk_observations=getter))
        by_name = {'sdb': [{'type': 'io_error', 'count': 99, 'message': 'of the previous disk'}]}
        with patch.dict(sys.modules, {'flask_server': server}):
            entries = audit_inventory._observations_of('sdb', 'NEW-GOOD', by_name)
        self.assertEqual(asked, [('sdb', 'NEW-GOOD')])
        self.assertEqual([(e['type'], e['count']) for e in entries], [('io_error', 3)])


if __name__ == '__main__':
    unittest.main()
