"""Absent-slot recovery must require a verified pin and completed kernel removal."""

import importlib.util
import errno
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[3] / "scripts/devices/usbip_lifetime.py"
spec = importlib.util.spec_from_file_location("usbip_lifetime", SOURCE)
l = importlib.util.module_from_spec(spec)
spec.loader.exec_module(l)


class LifetimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        lease = l.Lease.__new__(l.Lease)
        lease.path = self.root / "1-2"
        lease.devpath = "/devices/test/usb1/1-2"
        lease.bus = 1
        lease.number = 3
        lease.sequence = 100
        lease.ready = True
        lease.removed = False
        lease.fds = []
        lease.events = Mock()
        lease.events.recvmsg.side_effect = BlockingIOError()
        self.lease = lease
        self.match = Mock()
        self.match.parent = self.root
        self.match.read_text.side_effect = lambda: (
            "" if (self.root / "rebind").exists() else "1-2"
        )

    def event(self, **changes):
        values = {
            "ACTION": "remove",
            "DEVTYPE": "usb_device",
            "DEVPATH": self.lease.devpath,
            "BUSNUM": "001",
            "DEVNUM": "003",
            "SEQNUM": "101",
        } | changes
        return b"\0".join(f"{k}={v}".encode() for k, v in values.items()) + b"\0"

    def test_no_rebind_without_a_verified_lifetime_pin(self):
        self.lease.ready = False
        self.lease.removed = True
        with self.assertRaises(l.LifetimeError):
            self.lease.release(self.match, Mock())
        self.assertFalse((self.root / "rebind").exists())

    def test_rebind_requires_completed_removal_not_only_missing_sysfs(self):
        with patch.object(
            self.lease, "validate", side_effect=FileNotFoundError()
        ), patch.object(l.time, "monotonic", side_effect=[0, 3, 4]):
            with self.assertRaisesRegex(l.LifetimeError, "Waiting"):
                self.lease.release(self.match, Mock())
        self.assertFalse((self.root / "rebind").exists())

    def test_unrelated_or_userspace_events_do_not_authorize_slot_recovery(self):
        packets = [
            (self.event(SEQNUM="99"), [], 0, (0, 1)),
            (self.event(DEVNUM="004"), [], 0, (0, 1)),
            (self.event(DEVPATH="/devices/other"), [], 0, (0, 1)),
            (self.event(), [], 0, (12345, 1)),
            (self.event(DEVTYPE="usb_interface"), [], 0, (0, 1)),
            BlockingIOError(),
        ]
        self.lease.events.recvmsg.side_effect = packets
        self.assertFalse(self.lease.poll_removed())

    def test_lost_or_truncated_events_invalidate_recovery(self):
        for fault in (
            OSError(errno.ENOBUFS, "overflow"),
            (self.event(), [], socket.MSG_TRUNC, (0, 1)),
        ):
            self.lease.ready = True
            self.lease.events.recvmsg.side_effect = [fault]
            with self.assertRaises(l.LifetimeError):
                self.lease.poll_removed()
            self.assertFalse(self.lease.ready)
            self.assertFalse((self.root / "rebind").exists())

    def test_pinned_completed_removal_cleans_only_its_slot(self):
        self.lease.events.recvmsg.side_effect = [
            (self.event(), [], 0, (0, 1)),
            BlockingIOError(),
        ]
        unbind = Mock()
        self.lease.release(self.match, unbind)
        unbind.assert_not_called()
        self.assertEqual((self.root / "rebind").read_text(), "1-2")
        self.assertFalse(self.lease.ready)

    def test_present_device_uses_native_unbind_not_absent_recovery(self):
        self.match.read_text.return_value = ""
        self.match.read_text.side_effect = None
        unbind = Mock()
        with patch.object(self.lease, "validate"):
            self.lease.release(self.match, unbind)
        unbind.assert_called_once_with("1-2")
        self.assertFalse((self.root / "rebind").exists())


if __name__ == "__main__":
    unittest.main()
