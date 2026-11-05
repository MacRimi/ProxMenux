"""Real socket control/URB tests with disposable sysfs-shaped device objects."""

import importlib.util
import os
from pathlib import Path
import socket
import socketserver
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "usbip_protocol", ROOT / "scripts/devices/usbip_protocol.py"
)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def descriptor(
    name="2-1", bus=2, number=3, vendor=0x1D6B, product=0x0104, interfaces=1
):
    return p.DEVICE.pack(
        b"/sys/devices/disposable",
        name.encode(),
        bus,
        number,
        3,
        vendor,
        product,
        0x0100,
        0,
        0,
        0,
        1,
        1,
        interfaces,
    )


def exact(connection, count):
    result = bytearray()
    while len(result) < count:
        block = connection.recv(count - len(result))
        if not block:
            break
        result.extend(block)
    return bytes(result)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="usbip-gate-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sysfs = self.root / "sysfs"
        self.sysfs.mkdir()
        self.device("original")
        self.selected = {
            "2-1": {
                "id": "abcdef123456",
                "vendor": "1d6b",
                "product": "0104",
                "serial": "selected-serial",
            }
        }
        self.calls = []
        self.reply = descriptor()
        self.listed = [
            (descriptor(), b"\x02\x02\x01\0"),
            (descriptor("3-1", bus=3, number=4), b"\x02\x02\x01\0"),
        ]
        self.hook = lambda: None
        self.header_override = None
        fixture = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    header = exact(self.request, 8)
                    if len(header) != 8:
                        return
                    _, code, _ = p.HEADER.unpack(header)
                    request = header + (
                        exact(self.request, 32) if code == p.IMPORT else b""
                    )
                    fixture.calls.append(request)
                    fixture.hook()
                    self.request.sendall(
                        fixture.header_override
                        or p.HEADER.pack(p.VERSION, code & 0x7FFF, 0)
                    )
                    if code == p.DEVLIST:
                        self.request.sendall(struct.pack("!I", len(fixture.listed)))
                        for raw, interfaces in fixture.listed:
                            self.request.sendall(raw + interfaces)
                        return
                    self.request.sendall(fixture.reply)
                    while True:
                        block = self.request.recv(65536)
                        if not block:
                            self.request.shutdown(socket.SHUT_WR)
                            return
                        self.request.sendall(block)
                except OSError:
                    return

        class Backend(socketserver.ThreadingMixIn, socketserver.TCPServer):
            daemon_threads = True

        self.backend = Backend(("127.0.0.1", 0), Handler)
        self.backend_thread = threading.Thread(
            target=self.backend.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self.backend_thread.start()
        self.addCleanup(self.backend.server_close)
        self.addCleanup(self.backend.shutdown)
        # Production calls this as root; these protocol tests do not alter users.
        with patch.object(p.os, "chown"):
            self.gate = p.Gate(
                self.root / "gate.sock",
                os.getgid(),
                lambda name: self.selected.get(name),
                self.sysfs,
                self.backend.server_address,
                max_connections=2,
            )
        self.addCleanup(self.gate.terminate)

    def device(self, directory, serial="selected-serial", number=3):
        device = self.root / directory
        device.mkdir()
        for name, value in {
            "idVendor": "1d6b",
            "idProduct": "0104",
            "serial": serial,
            "busnum": "2",
            "devnum": str(number),
            "bDeviceClass": "00",
        }.items():
            (device / name).write_text(value)
        interface = device / "2-1:1.0"
        interface.mkdir()
        (interface / "bInterfaceClass").write_text("02")
        (device / "driver").symlink_to("/sys/bus/usb/drivers/usbip-host")
        link = self.sysfs / "2-1"
        link.unlink(missing_ok=True)
        link.symlink_to(device, target_is_directory=True)
        return device

    def connect(self):
        connection = socket.socket(socket.AF_UNIX)
        connection.settimeout(3)
        connection.connect(str(self.gate.path))
        self.addCleanup(connection.close)
        return connection

    def request(self, name=b"2-1\0", code=p.IMPORT):
        return p.HEADER.pack(p.VERSION, code, 0) + (
            name.ljust(32, b"\0") if code == p.IMPORT else b""
        )

    def reject(self, request):
        connection = self.connect()
        connection.sendall(request)
        result = exact(connection, 8)
        self.assertTrue(not result or p.HEADER.unpack(result)[2] != 0, result)
        self.assertEqual(connection.recv(1), b"")
        return result

    def test_fragmented_selected_import_and_large_binary_full_duplex(self):
        connection = self.connect()
        for value in self.request():
            connection.sendall(bytes([value]))
        self.assertEqual(
            exact(connection, 320), p.HEADER.pack(p.VERSION, 3, 0) + self.reply
        )
        payload = bytes(range(256)) * 4096
        writer = threading.Thread(target=connection.sendall, args=(payload,))
        writer.start()
        self.assertEqual(exact(connection, len(payload)), payload)
        writer.join(3)
        self.assertFalse(writer.is_alive())
        connection.shutdown(socket.SHUT_WR)
        self.assertEqual(connection.recv(1), b"")

    def test_foreign_device_is_rejected_before_native_backend_import(self):
        self.reject(self.request(b"3-1\0"))
        self.assertEqual(self.calls, [])

    def test_malformed_busids_never_reach_backend(self):
        for value in (b"2-1\0x", b"../../etc\0", b"2-1\xff\0", b"x" * 32):
            with self.subTest(value=value):
                self.reject(self.request(value))
        self.assertEqual(self.calls, [])

    def test_unsupported_control_headers_never_reach_backend(self):
        for header in (
            p.HEADER.pack(0x0110, p.IMPORT, 0),
            p.HEADER.pack(p.VERSION, 0x8001, 0),
            p.HEADER.pack(p.VERSION, p.IMPORT, 1),
        ):
            self.reject(header)
        self.assertEqual(self.calls, [])

    def test_devlist_filters_unselected_export_and_preserves_interface_records(self):
        connection = self.connect()
        connection.sendall(self.request(code=p.DEVLIST))
        reply = exact(connection, 12)
        self.assertEqual(reply, p.HEADER.pack(p.VERSION, 5, 0) + struct.pack("!I", 1))
        self.assertEqual(exact(connection, 316), self.reply + b"\x02\x02\x01\0")
        self.assertEqual(connection.recv(1), b"")

    def test_changed_selection_during_import_receives_no_success_payload(self):
        self.hook = self.selected.clear
        self.reject(self.request())
        self.assertEqual(len(self.calls), 1)

    def test_mutated_callback_dictionary_cannot_rewrite_saved_selection(self):
        self.hook = lambda: self.selected["2-1"].update(id="fedcba654321")
        self.reject(self.request())

    def test_replaced_sysfs_object_cannot_use_identical_reply_metadata(self):
        self.hook = lambda: self.device("replacement")
        self.reject(self.request())

    def test_driver_change_during_import_is_rejected(self):
        def replace():
            driver = self.root / "original/driver"
            driver.unlink()
            driver.symlink_to("/sys/bus/usb/drivers/usb")

        self.hook = replace
        self.reject(self.request())

    def test_descriptor_identity_and_devnum_must_match_pinned_object(self):
        for reply in (
            descriptor(number=4),
            descriptor(vendor=0x05AC),
            descriptor("3-1"),
            descriptor(bus=3),
        ):
            self.reply = reply
            self.reject(self.request())

    def test_composite_storage_or_hub_device_is_rejected_before_backend(self):
        for name in ("bDeviceClass", "2-1:1.0/bInterfaceClass"):
            path = self.root / "original" / name
            old = path.read_text()
            for value in ("08", "09"):
                path.write_text(value)
                self.reject(self.request())
            path.write_text(old)
        self.assertEqual(self.calls, [])

    def test_unicode_serial_is_valid_without_changing_busid_encoding(self):
        serial = "selected-ñ-设备"
        (self.root / "original/serial").write_text(serial)
        self.selected["2-1"]["serial"] = serial
        connection = self.connect()
        connection.sendall(self.request())
        self.assertEqual(
            exact(connection, 320), p.HEADER.pack(p.VERSION, 3, 0) + self.reply
        )

    def test_backend_response_version_opcode_and_status_are_validated(self):
        for header in (
            p.HEADER.pack(0x0110, 3, 0),
            p.HEADER.pack(p.VERSION, 5, 0),
            p.HEADER.pack(p.VERSION, 3, 0xFFFFFFFF),
        ):
            self.header_override = header
            self.reject(self.request())

    def test_incomplete_header_times_out_but_accepted_idle_stream_does_not(self):
        with patch.object(p, "CONTROL_SECONDS", 0.1):
            partial = self.connect()
            partial.sendall(b"\x01")
            self.assertEqual(partial.recv(1), b"")
            connection = self.connect()
            connection.sendall(self.request())
            self.assertEqual(len(exact(connection, 320)), 320)
            time.sleep(0.2)
            connection.sendall(b"idle-still-works")
            self.assertEqual(exact(connection, 16), b"idle-still-works")

    def test_stop_closes_idle_backend_and_client_and_removes_listener(self):
        connection = self.connect()
        connection.sendall(self.request())
        self.assertEqual(len(exact(connection, 320)), 320)
        self.gate.terminate()
        self.assertEqual(connection.recv(1), b"")
        self.assertFalse(self.gate.path.exists())
        self.assertIsNotNone(self.gate.poll())


if __name__ == "__main__":
    unittest.main()
