"""Proxmox VE 9.2.33 and later keep a read-only `meta:` line in each guest
configuration (creation time and identity) and renew it on their own. It is
never a change of the user, and a container that has it can still be updated
and modified."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "remote"), str(ROOT / "src")]

import oci_instance_transaction as transaction  # noqa: E402
import oci_instances as instances  # noqa: E402
from oci_installation_state import without_guest_identity  # noqa: E402

MARKER = "proxmenux-instance=11111111-2222-3333-4444-555555555555"
SAVED = (f"arch: amd64\ndescription: {MARKER}\nhostname: app\nmemory: 512\n"
         "net0: name=eth0,bridge=vmbr0,ip=dhcp\nrootfs: local-lvm:vm-130-disk-0,size=4G\n"
         "lxc.init.uid: 1000\nlxc.environment.runtime: A=1\nlxc.environment.runtime: B=2\n").encode()
WITH_META = SAVED.replace(b"memory: 512\n", b"memory: 512\nmeta: ctime=1772444467,rtime=1794320571482,uid=w5qczgiem26qnwzwsoil\n")
RENEWED = WITH_META.replace(b"uid=w5qczgiem26qnwzwsoil", b"uid=ioo24izjjjaxyalxeyz4")


class GuestIdentityTests(unittest.TestCase):
    def test_the_identity_line_is_not_a_setting(self):
        self.assertEqual(without_guest_identity(WITH_META), SAVED)
        self.assertEqual(transaction.settings(WITH_META), transaction.settings(SAVED))
        self.assertIn("meta", transaction.BASIC)

    def test_a_renewed_identity_or_regrouped_variables_are_the_same_configuration(self):
        self.assertEqual(transaction.as_written(RENEWED), transaction.as_written(SAVED))
        apart = SAVED.replace(b"lxc.environment.runtime: B=2\n", b"").replace(
            b"lxc.init.uid: 1000\n", b"lxc.init.uid: 1000\nlxc.environment.runtime: B=2\n")
        apart = apart.replace(b"lxc.environment.runtime: A=1\n", b"") + b"lxc.environment.runtime: A=1\n"
        self.assertNotEqual(transaction.as_written(apart), transaction.as_written(SAVED))
        moved = SAVED.replace(b"lxc.environment.runtime: A=1\nlxc.environment.runtime: B=2\n", b"")
        moved = moved.replace(b"lxc.init.uid: 1000\n",
                              b"lxc.environment.runtime: A=1\nlxc.init.uid: 1000\nlxc.environment.runtime: B=2\n")
        self.assertEqual(transaction.as_written(moved), transaction.as_written(SAVED))

    def test_a_real_change_still_counts(self):
        changed = RENEWED.replace(b"memory: 512", b"memory: 1024")
        self.assertNotEqual(transaction.as_written(changed), transaction.as_written(SAVED))

    def test_the_saved_record_matches_a_configuration_with_identity(self):
        record = {"installation_id": MARKER.split("=", 1)[1], "observed": {"config": SAVED.decode()}}
        self.assertTrue(instances.same_config_except_notes(record, RENEWED))
        self.assertEqual(instances.changed_settings(record, RENEWED), [])
        self.assertEqual(instances.changed_settings(record, RENEWED.replace(b"memory: 512", b"memory: 1024")),
                         ["memory"])

    def test_external_changes_ignore_the_identity(self):
        import hashlib
        record = {"installation_id": MARKER.split("=", 1)[1],
                  "observed": {"config": SAVED.decode(), "config_sha256": hashlib.sha256(SAVED).hexdigest()}}
        self.assertEqual(transaction.external_changes(record, WITH_META), {})


if __name__ == "__main__":
    unittest.main()
