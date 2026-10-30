import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import oci_manager  # noqa: E402

HEADER = "Name Type Status Total Used Available %\n"


class TemplateStorage(unittest.TestCase):
    """The Alpine template goes to a storage Proxmox can use."""

    def storage(self, listing, rc=0):
        with patch.object(oci_manager, "_run_pve_cmd", return_value=(rc, HEADER + listing, "")):
            return oci_manager._template_storage()

    def test_local_is_used_while_it_is_active(self):
        self.assertEqual(self.storage("local dir active 1 1 1 1%\nnas nfs active 1 1 1 1%\n"), "local")

    def test_another_storage_is_used_when_local_is_disabled(self):
        # On a BTRFS installation `local` is disabled and not listed.
        self.assertEqual(self.storage("local-btrfs btrfs active 1 1 1 1%\n"), "local-btrfs")
        self.assertEqual(self.storage("nas nfs inactive 0 0 0 0%\nlocal-btrfs btrfs active 1 1 1 1%\n"), "local-btrfs")

    def test_an_unreadable_status_keeps_local(self):
        self.assertEqual(self.storage("", rc=1), "local")


if __name__ == "__main__":
    unittest.main()
