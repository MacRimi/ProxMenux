"""The temporary container that holds the data of an application during an
update is removed when the operation ends: empty after a commit, and with the
disks of the failed attempt after a verified recovery."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_instance_transaction as transaction

EMPTY = b"arch: amd64\nhostname: oci-data-holder\nrootfs: local-lvm:vm-104-disk-0,size=8G\n"
HOLDING = EMPTY + b"mp0: local-lvm:vm-104-disk-1,mp=/transaction-retained/bd021f9e,backup=1,size=32G\n"
STATE = {"id": "4dfbfd9223a440c1b07a0334b08fc4fd", "stage": 104}


class StageReleaseTests(unittest.TestCase):
    def release(self, config, **arguments):
        calls = []
        with patch.object(transaction, "owned", return_value=config) as owned, \
                patch.object(transaction, "stop", side_effect=lambda vmid: calls.append(("stop", vmid))), \
                patch.object(transaction, "run", side_effect=lambda *command: calls.append(command)):
            transaction.release_stage(STATE, **arguments)
        owned.assert_called_once_with(104, "proxmenux-transaction=" + STATE["id"])
        return calls

    def test_after_a_commit_the_empty_container_is_removed(self):
        self.assertEqual(self.release(EMPTY), [("pct", "destroy", "104")])

    def test_a_container_that_still_holds_a_disk_is_kept(self):
        self.assertEqual(self.release(HOLDING), [])
        self.assertEqual(self.release(EMPTY + b"unused0: local-lvm:vm-104-disk-2\n"), [])

    def test_after_a_verified_recovery_it_is_removed_with_what_it_holds(self):
        self.assertEqual(self.release(HOLDING, discard=True), [("stop", 104), ("pct", "destroy", "104")])

    def test_a_container_of_another_operation_is_never_removed(self):
        calls = []
        with patch.object(transaction, "owned", side_effect=ValueError("not ours")), \
                patch.object(transaction, "run", side_effect=lambda *command: calls.append(command)):
            transaction.release_stage(STATE, discard=True)
        self.assertEqual(calls, [])

    def test_an_operation_without_a_temporary_container_does_nothing(self):
        with patch.object(transaction, "owned") as owned:
            transaction.release_stage({"id": "x"}, discard=True)
        owned.assert_not_called()

    def test_a_removal_that_fails_does_not_undo_the_recovery(self):
        with patch.object(transaction, "owned", return_value=HOLDING), \
                patch.object(transaction, "stop"), \
                patch.object(transaction, "run", side_effect=RuntimeError("pct failed with exit code 255")), \
                patch.object(transaction, "log") as logged:
            transaction.discard_stage(STATE)
        self.assertIn("pct failed", logged.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
