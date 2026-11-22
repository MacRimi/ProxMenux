"""An update stops before anything is touched when the new image declares a
relative entrypoint, and a record left pending by an operation that already
ended is freed only when the container is exactly as recorded."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_instance_transaction as transaction
import oci_instances as instances

VMID = 4810
IDENTITY = '5b0c1f3e-7a2d-4c9b-9e41-2f6a8d0c7b11'
CONFIG = ('arch: amd64\ndescription: <!-- proxmenux-instance=' + IDENTITY + ' -->\n'
          'hostname: pihole\nnet0: name=eth0,bridge=vmbr0\n')


def runtime(**values):
    return {'proxmox': {'installer_profile': {'runtime': values}}}


class RuntimeCheckTests(unittest.TestCase):
    def test_a_relative_entrypoint_or_working_directory_is_refused(self):
        for template in (runtime(entrypoint='start.sh'), runtime(entrypoint='/usr/bin/start.sh\nrm'),
                         runtime(working_directory='app'), runtime(working_directory='/srv/my app')):
            with self.subTest(template=template), self.assertRaises(ValueError):
                transaction.check_runtime(template)

    def test_absolute_values_or_none_pass(self):
        for template in (None, {}, runtime(), runtime(entrypoint='/usr/bin/start.sh', working_directory='/app'),
                         runtime(entrypoint='', working_directory='')):
            with self.subTest(template=template):
                transaction.check_runtime(template)


class StaleMarkerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'registry'
        self.journal = Path(temp.name) / 'journal.json'
        self.config = CONFIG
        record = {'schema_version': 1, 'vmid': VMID, 'installation_id': IDENTITY, 'status': 'updating', 'deployment': {},
                  'observed': {'config': CONFIG}, 'pending_transaction': str(self.journal),
                  'transaction_id': 'tx-1'}
        instances.write(instances.location(self.root, VMID), record)
        for name, value in (('run', lambda *args: self.config.encode()), ('msg_ok', lambda *_: None),
                            ('log', lambda *_: None)):
            patcher = mock.patch.object(transaction, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def release(self):
        return transaction.release_stale_marker(self.root, VMID, self.journal)

    def record(self):
        return instances.read(self.root, VMID)

    def test_a_missing_journal_frees_an_unchanged_container(self):
        self.assertTrue(self.release())
        record = self.record()
        self.assertEqual(record['status'], 'installed')
        self.assertNotIn('pending_transaction', record)
        self.assertNotIn('transaction_id', record)

    def test_a_finished_or_unreadable_journal_frees_it_too(self):
        for content in (json.dumps({'id': 'tx-1', 'phase': 'rolled-back'}), '{not json'):
            with self.subTest(content=content):
                self.setUp()
                self.journal.write_text(content)
                self.assertTrue(self.release())

    def test_an_operation_still_in_progress_is_left_to_the_recovery(self):
        self.journal.write_text(json.dumps({'id': 'tx-1', 'phase': 'replaced'}))
        self.assertFalse(self.release())
        self.assertEqual(self.record()['pending_transaction'], str(self.journal))

    def test_a_changed_container_or_a_stack_operation_is_not_freed(self):
        self.config = CONFIG.replace('hostname: pihole', 'hostname: other')
        self.assertFalse(self.release())
        self.config = CONFIG
        self.journal.write_text(json.dumps({'id': 'tx-1', 'phase': 'committed', 'coordinated': True}))
        self.assertFalse(self.release())
        self.assertEqual(self.record()['status'], 'updating')

    def test_a_marker_of_another_journal_is_not_touched(self):
        self.assertFalse(transaction.release_stale_marker(self.root, VMID, self.journal.with_name('other.json')))


if __name__ == '__main__':
    unittest.main()
