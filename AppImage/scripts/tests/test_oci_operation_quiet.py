"""While the OCI manager updates or recreates an application, the stop, the
backup and the start of its containers are steps of that operation."""
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import oci_operations


def event(kind, vmid=None, severity='INFO', **data):
    if vmid is not None:
        data['vmid'] = str(vmid)
    return SimpleNamespace(event_type=kind, severity=severity, data=data, entity_id=str(vmid or ''))


class OperationQuietTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def mark(self, vmid, started, ended=None):
        Path(self.root, str(vmid)).write_text(json.dumps({'started': started, 'ended': ended}))

    def test_the_steps_of_a_running_operation_are_quiet(self):
        self.mark(115, time.time())
        for kind in ('ct_shutdown', 'ct_stop', 'ct_start', 'ct_restart', 'backup_start', 'backup_complete'):
            self.assertTrue(oci_operations.quiet(event(kind, 115), self.root), kind)

    def test_another_container_is_still_reported(self):
        self.mark(115, time.time())
        self.assertFalse(oci_operations.quiet(event('ct_stop', 200), self.root))
        self.assertFalse(oci_operations.quiet(event('ct_stop'), self.root))

    def test_a_problem_is_never_silenced(self):
        self.mark(115, time.time())
        self.assertFalse(oci_operations.quiet(event('ct_stop', 115, severity='WARNING'), self.root))
        self.assertFalse(oci_operations.quiet(event('ct_fail', 115), self.root))
        self.assertFalse(oci_operations.quiet(event('backup_fail', 115), self.root))

    def test_the_last_start_is_still_quiet_just_after_the_operation(self):
        now = time.time()
        self.mark(115, now - 60, ended=now - 60)
        self.assertTrue(oci_operations.quiet(event('ct_start', 115), self.root))
        self.mark(115, now - 3600, ended=now - 3600)
        self.assertFalse(oci_operations.quiet(event('ct_start', 115), self.root))

    def test_a_mark_left_by_a_dead_operation_expires(self):
        self.mark(115, time.time() - 7 * 3600)
        self.assertFalse(oci_operations.quiet(event('ct_stop', 115), self.root))

    def test_the_working_copy_of_an_update_is_recognised_by_its_path(self):
        archive = ('/usr/local/share/proxmenux/oci/instances/115/stack-transactions/abc/backup-117/'
                   'vzdump-lxc-117-2026_10_02-20_45_41.tar.zst')
        self.assertTrue(oci_operations.quiet(event('backup_complete', pve_message=archive), self.root))
        self.assertFalse(oci_operations.quiet(
            event('backup_complete', pve_message='/var/lib/vz/dump/vzdump-lxc-117-2026.tar.zst'), self.root))

    def test_a_backup_of_several_guests_is_quiet_only_when_all_belong_to_the_operation(self):
        self.mark(115, time.time())
        self.mark(117, time.time())
        both = event('backup_start', reason='VM/CT:\n  CT immich-server (115)\n  CT immich-db (117)')
        mixed = event('backup_start', reason='VM/CT:\n  CT immich-db (117)\n  CT other (200)')
        self.assertTrue(oci_operations.quiet(both, self.root))
        self.assertFalse(oci_operations.quiet(mixed, self.root))


if __name__ == '__main__':
    unittest.main()
