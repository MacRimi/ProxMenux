"""Proxmox VE 9.3 refuses to restore a backup over a container with another
identity. When an update fails after the container was replaced, recovery
restores the previous installation over the new container, so it asks Proxmox
to accept the different identity, on the versions that have that check."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "remote"), str(ROOT / "src")]

import oci_instance_transaction as transaction  # noqa: E402

USAGE_93 = ("pct restore <vmid> <ostemplate> [OPTIONS]\n"
            "  --allow-identity-mismatch <boolean>   (default=0)\n"
            "  --force <boolean>\n")
USAGE_92 = "pct restore <vmid> <ostemplate> [OPTIONS]\n  --force <boolean>\n"


def usage(text):
    return mock.patch.object(transaction.subprocess, "run",
                             return_value=subprocess.CompletedProcess(["pct"], 0, text, ""))


class RestoreIdentityTests(unittest.TestCase):
    def setUp(self):
        transaction.restore_identity_args.cache_clear()
        self.addCleanup(transaction.restore_identity_args.cache_clear)

    def test_a_proxmox_with_the_check_accepts_the_previous_installation(self):
        with usage(USAGE_93):
            self.assertEqual(transaction.restore_identity_args(), ("--allow-identity-mismatch", "1"))

    def test_older_versions_restore_as_before(self):
        with usage(USAGE_92):
            self.assertEqual(transaction.restore_identity_args(), ())

    def test_without_pct_nothing_is_added(self):
        with mock.patch.object(transaction.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(transaction.restore_identity_args(), ())

    def test_recovery_restores_with_it(self):
        source = (ROOT / "remote" / "oci_instance_transaction.py").read_text()
        restore = source[source.index("run('pct', 'restore', str(vmid), str(restore_archive)"):]
        self.assertIn("*restore_identity_args()", restore[:restore.index("\n", restore.index("\n") + 1)])


if __name__ == "__main__":
    unittest.main()
