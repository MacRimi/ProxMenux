"""Native updates must allow the grace period selected by the application's recipe."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'remote'))
import oci_instance_transaction as transaction

class ShutdownGraceTests(unittest.TestCase):
    def test_configured_grace_is_passed_to_proxmox_without_forcing_a_successful_shutdown(self):
        calls=[]
        def run(*args):
            calls.append(args)
            if args[:2]==('pct','status'):
                return b'status: running' if len(calls)==1 else b'status: stopped'
            return b''
        with patch.object(transaction,'run',side_effect=run):transaction.stop(9480,120)
        self.assertIn(('pct','shutdown','9480','--timeout','120'),calls)
        self.assertNotIn(('pct','stop','9480'),calls)

    def test_legacy_default_and_forced_stop_only_after_the_requested_wait_fails(self):
        calls=[]
        def run(*args):
            calls.append(args)
            if args[:2]==('pct','status'):return b'status: running' if len(calls)==1 else b'status: stopped'
            if args[:2]==('pct','shutdown'):raise RuntimeError('shutdown timed out')
            return b''
        with patch.object(transaction,'run',side_effect=run):transaction.stop(9480)
        self.assertEqual(calls[1:3],[('pct','shutdown','9480','--timeout','60'),('pct','stop','9480')])

    def test_invalid_grace_never_starts_a_shutdown(self):
        for value in (0,-1,True,'120',None):
            with self.subTest(value=value),patch.object(transaction,'run')as run:
                with self.assertRaises(ValueError):transaction.stop(9480,value)
                run.assert_not_called()
