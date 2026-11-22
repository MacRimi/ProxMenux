"""Authorize USB/IP control requests before exposing the native daemon.

The Unix listener runs in the server's private network namespace. Root supplies
current selection/ownership; the forced-command SSH account only reaches this
listener. An accepted import becomes an opaque, bounded, full-duplex URB stream.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import selectors
import socket
import socketserver
import struct
import threading
import time

VERSION = 0x0111
IMPORT = 0x8003
DEVLIST = 0x8005
HEADER = struct.Struct("!HHI")
DEVICE = struct.Struct("!256s32sIIIHHHBBBBBB")
BUSID = re.compile(r"[0-9]+-[0-9]+(?:\.[0-9]+)*\Z")
CONTROL_SECONDS = 5
MAX_DEVICES = 256
MAX_BUFFER = 65536


class ProtocolError(Exception):
    pass


def receive(connection, count, deadline):
    result = bytearray()
    while len(result) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProtocolError("USB/IP control request timed out")
        connection.settimeout(remaining)
        block = connection.recv(count - len(result))
        if not block:
            raise ProtocolError("Incomplete USB/IP control request")
        result.extend(block)
    return bytes(result)


def busid(value):
    """One canonical NUL-terminated 32-byte Linux bus identifier."""
    if len(value) != 32 or b"\0" not in value:
        raise ProtocolError("Invalid USB/IP bus identifier")
    name, padding = value.split(b"\0", 1)
    if any(padding):
        raise ProtocolError("Invalid USB/IP bus identifier padding")
    try:
        name = name.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ProtocolError("Non-ASCII USB/IP bus identifier") from exc
    if not BUSID.fullmatch(name):
        raise ProtocolError("Invalid USB/IP bus identifier")
    return name


class PinnedDevice:
    """Pin the sysfs object used for identity checks across the backend import.

    This does not claim to hold usb_device's kernel lifetime. It detects a
    removed/replaced sysfs object; USBFS lifetime pins belong to the owner.
    """

    def __init__(self, root, name, expected):
        self.path = Path(root) / name
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            self.object = self._object(os.fstat(self.fd))
            self.expected = {
                key: str(expected[key]) for key in ("vendor", "product", "serial")
            }
            self.identity = self._identity()
            self.validate()
        except BaseException:
            os.close(self.fd)
            raise

    @staticmethod
    def _object(info):
        return info.st_dev, info.st_ino

    def read(self, name):
        descriptor = os.open(
            name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=self.fd
        )
        try:
            value = os.read(descriptor, 513)
            if len(value) > 512:
                raise ProtocolError("Oversized USB identity attribute")
            return value.decode("utf-8").strip()
        finally:
            os.close(descriptor)

    def _identity(self):
        try:
            serial = self.read("serial")
        except FileNotFoundError:
            serial = ""
        classes = [int(self.read("bDeviceClass"), 16)]
        for name in os.listdir(self.fd):
            if name.startswith(self.path.name + ":"):
                classes.append(int(self.read(name + "/bInterfaceClass"), 16))
        if any(value in (8, 9) for value in classes):
            raise ProtocolError("USB hubs and mass storage cannot be shared")
        return {
            "vendor": self.read("idVendor").lower(),
            "product": self.read("idProduct").lower(),
            "serial": serial,
            "busnum": int(self.read("busnum")),
            "devnum": int(self.read("devnum")),
            "classes": tuple(sorted(classes)),
        }

    def validate(self, descriptor=None):
        if (
            self.object != self._object(os.stat(self.path))
            or self._identity() != self.identity
        ):
            raise ProtocolError("USB device was removed or replaced")
        if any(self.identity[key] != value for key, value in self.expected.items()):
            raise ProtocolError("USB device identity is not selected")
        if Path(os.readlink("driver", dir_fd=self.fd)).name != "usbip-host":
            raise ProtocolError("Selected USB device is no longer exported")
        if descriptor is not None:
            values = DEVICE.unpack(descriptor)
            if (
                busid(values[1]) != self.path.name
                or values[2] != self.identity["busnum"]
                or values[3] != self.identity["devnum"]
                or values[5] != int(self.identity["vendor"], 16)
                or values[6] != int(self.identity["product"], 16)
            ):
                raise ProtocolError(
                    "USB/IP reply does not describe the selected device"
                )

    def close(self):
        os.close(self.fd)


def relay(client, backend, stopped):
    """Preserve half-close and backpressure without an idle-session timeout."""
    peers = (client, backend)
    queued = [bytearray(), bytearray()]
    reading = [True, True]
    write_closed = [False, False]
    for connection in peers:
        connection.setblocking(False)
    with selectors.DefaultSelector() as selector:
        while not stopped.is_set():
            for index, connection in enumerate(peers):
                other = 1 - index
                if not reading[other] and not queued[index] and not write_closed[index]:
                    connection.shutdown(socket.SHUT_WR)
                    write_closed[index] = True
                events = (
                    selectors.EVENT_READ
                    if reading[index] and len(queued[other]) < MAX_BUFFER
                    else 0
                ) | (selectors.EVENT_WRITE if queued[index] else 0)
                try:
                    selector.get_key(connection)
                except KeyError:
                    if events:
                        selector.register(connection, events, index)
                else:
                    if events:
                        selector.modify(connection, events, index)
                    else:
                        selector.unregister(connection)
            if not selector.get_map():
                return
            for key, events in selector.select(timeout=1):
                index = key.data
                other = 1 - index
                if events & selectors.EVENT_READ:
                    try:
                        block = peers[index].recv(MAX_BUFFER - len(queued[other]))
                    except BlockingIOError:
                        continue
                    if block:
                        queued[other].extend(block)
                    else:
                        reading[index] = False
                if events & selectors.EVENT_WRITE:
                    try:
                        sent = peers[index].send(queued[index])
                    except BlockingIOError:
                        continue
                    if sent == 0:
                        raise ProtocolError("USB/IP connection closed during transfer")
                    del queued[index][:sent]


class Gate:
    """A bounded Unix server with the process-like lifecycle used by serve()."""

    def __init__(
        self,
        path,
        group,
        claim,
        sysfs="/sys/bus/usb/devices",
        backend=("127.0.0.1", 3240),
        max_connections=64,
    ):
        self.path = Path(path)
        self.claim = claim
        self.sysfs = Path(sysfs)
        self.backend = backend
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.connections = set()
        self.slots = threading.BoundedSemaphore(max_connections)
        gate = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                gate.handle(self.request)

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

            def process_request(self, request, address):
                if not gate.slots.acquire(blocking=False):
                    self.shutdown_request(request)
                    return
                try:
                    super().process_request(request, address)
                except BaseException:
                    gate.slots.release()
                    raise

            def process_request_thread(self, request, address):
                try:
                    super().process_request_thread(request, address)
                finally:
                    gate.slots.release()

        self.server = Server(str(self.path), Handler)
        try:
            os.chown(self.path, 0, group)
            self.path.chmod(0o660)
            self.thread = threading.Thread(
                target=self.server.serve_forever,
                kwargs={"poll_interval": 0.1},
                daemon=True,
            )
            self.thread.start()
        except BaseException:
            self.server.server_close()
            self.path.unlink(missing_ok=True)
            raise

    @contextmanager
    def pin(self, name):
        expected = self.selection(name)
        if not expected:
            raise ProtocolError("USB device is not selected for sharing")
        device = PinnedDevice(self.sysfs, name, expected)
        try:
            yield device, expected
        finally:
            device.close()

    def _still_selected(self, name, expected):
        if self.selection(name) != expected:
            raise ProtocolError("USB sharing selection changed")

    def selection(self, name):
        value = self.claim(name)
        if not value:
            return None
        # Freeze the authorization snapshot even when a callback reuses its
        # dictionary; mutable ownership changes must not rewrite this lease.
        return {key: str(value[key]) for key in ("id", "vendor", "product", "serial")}

    @contextmanager
    def tracked(self, connection, close=True):
        with self.lock:
            if self.stopped.is_set():
                connection.close()
                raise ProtocolError("USB/IP server is stopping")
            self.connections.add(connection)
        try:
            yield connection
        finally:
            with self.lock:
                self.connections.discard(connection)
            if close:
                connection.close()

    def _backend(self, request, deadline):
        connection = socket.create_connection(
            self.backend, timeout=max(0.001, deadline - time.monotonic())
        )
        try:
            connection.sendall(request)
            return connection
        except BaseException:
            connection.close()
            raise

    @staticmethod
    def response(connection, code, deadline):
        header = receive(connection, HEADER.size, deadline)
        version, received_code, status = HEADER.unpack(header)
        if version != VERSION or received_code != (code & 0x7FFF) or status > 5:
            raise ProtocolError("Invalid USB/IP backend response")
        return header, status

    def handle(self, client):
        code = None
        try:
            with self.tracked(client, close=False):
                deadline = time.monotonic() + CONTROL_SECONDS
                request = receive(client, HEADER.size, deadline)
                version, code, status = HEADER.unpack(request)
                if version != VERSION or code not in (DEVLIST, IMPORT) or status:
                    code = None
                    raise ProtocolError("Unsupported USB/IP control request")
                if code == IMPORT:
                    raw_name = receive(client, 32, deadline)
                    name = busid(raw_name)
                    with self.pin(name) as (device, expected):
                        with self.tracked(
                            self._backend(request + raw_name, deadline)
                        ) as backend:
                            header, failed = self.response(backend, code, deadline)
                            if failed:
                                code = None
                                client.sendall(header)
                                return
                            descriptor = receive(backend, DEVICE.size, deadline)
                            self._still_selected(name, expected)
                            device.validate(descriptor)
                            code = (
                                None  # Data mode: never append another control header.
                            )
                            client.sendall(header + descriptor)
                            relay(client, backend, self.stopped)
                else:
                    with self.tracked(self._backend(request, deadline)) as backend:
                        header, failed = self.response(backend, code, deadline)
                        if failed:
                            code = None
                            client.sendall(header)
                            return
                        count = struct.unpack("!I", receive(backend, 4, deadline))[0]
                        if count > MAX_DEVICES:
                            raise ProtocolError(
                                "USB/IP backend device count is too large"
                            )
                        allowed = []
                        for _ in range(count):
                            descriptor = receive(backend, DEVICE.size, deadline)
                            values = DEVICE.unpack(descriptor)
                            interfaces = receive(backend, 4 * values[-1], deadline)
                            name = busid(values[1])
                            try:
                                with self.pin(name) as (device, expected):
                                    self._still_selected(name, expected)
                                    device.validate(descriptor)
                                    allowed.append(descriptor + interfaces)
                            except (
                                ProtocolError,
                                OSError,
                                ValueError,
                                KeyError,
                                UnicodeError,
                            ):
                                continue
                        code = None
                        client.sendall(
                            header + struct.pack("!I", len(allowed)) + b"".join(allowed)
                        )
        except (ProtocolError, OSError, ValueError, KeyError, UnicodeError):
            if code in (DEVLIST, IMPORT):
                try:
                    client.sendall(HEADER.pack(VERSION, code & 0x7FFF, 1))
                except OSError:
                    pass
        finally:
            client.close()

    def poll(self):
        return None if not self.stopped.is_set() and self.thread.is_alive() else 1

    def terminate(self):
        self.stopped.set()
        self.server.shutdown()
        with self.lock:
            for connection in self.connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        self.server.server_close()
        self.path.unlink(missing_ok=True)

    def wait(self, timeout=5):
        self.thread.join(timeout)
        return 0
