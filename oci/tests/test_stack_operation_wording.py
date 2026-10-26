"""The steps of a coordinated operation name the operation that is running."""

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

import oci_stack_transaction as transaction


class StackOperationWording(unittest.TestCase):
    def steps(self, operation):
        plan = {"operation": operation, "primary_vmid": 138, "members": [{"vmid": 138}],
                "start_order": [138], "stop_order": [138]}
        adapter = MagicMock(spec=["validate", "is_running", "prepare", "stop", "backup", "verify_backups", "replace",
                                  "start", "healthcheck", "validate_candidates", "restore_running_state", "publish"])
        adapter.is_running.return_value = False
        adapter.prepare.return_value = {}
        adapter.backup.return_value = "backup"
        said = []
        with patch.object(transaction, "save"), patch.object(transaction, "translate", side_effect=lambda text: text), \
                patch.object(transaction, "msg_info", side_effect=said.append), \
                patch.object(transaction, "msg_ok", side_effect=said.append):
            transaction._apply(Path("/nonexistent/journal.json"), plan, adapter)
        return said

    def test_a_recreation_never_says_it_is_updating(self):
        said = self.steps("recreate")
        self.assertIn("Recreating CT 138...", said)
        self.assertIn("Recreated: CT 138", said)
        self.assertIn("Recreated stack checked", said)
        self.assertEqual([line for line in said if "pdat" in line], [])

    def test_an_update_keeps_its_wording(self):
        said = self.steps("update")
        self.assertIn("Updating CT 138...", said)
        self.assertIn("Updated: CT 138", said)
        self.assertIn("Updated stack checked", said)
        self.assertEqual([line for line in said if "ecreat" in line], [])


if __name__ == "__main__":
    unittest.main()
