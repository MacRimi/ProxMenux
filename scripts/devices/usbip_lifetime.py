"""Keep kernel USB references until a managed, disarmed match is released.

usbfs descriptors hold usb_device references (including its USB parents).
A kernel remove uevent confirms disconnect finished before absent-slot rebind.
A pathname or a sysfs directory descriptor alone is not a USB lifetime pin.
Lost events, unverified binds and ownership recovered without pins fail closed.
"""

import os
from pathlib import Path
import socket
import stat
import time


class LifetimeError(RuntimeError):
    pass


class Lease:
    def __init__(self, sysfs, busid, expected):
        self.path = Path(sysfs) / busid
        self.fds = []
        self.ready = False
        self.removed = False
        self.events = socket.socket(
            socket.AF_NETLINK, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC, 15
        )
        try:
            self.events.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
            self.events.bind((0, 1))
            self.events.setblocking(False)
            self.directory = os.open(
                self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
            )
            self.fds.append(self.directory)
            self.object = self._object(os.fstat(self.directory))
            self.devpath = str(self.path.resolve()).removeprefix("/sys")
            self.bus = int(self.read("busnum"))
            self.number = int(self.read("devnum"))
            self.identity = {
                key: self.read(name)
                for key, name in [
                    ("vendor", "idVendor"),
                    ("product", "idProduct"),
                    ("serial", "serial"),
                ]
            }
            if self.identity != {key: expected[key] for key in self.identity}:
                raise LifetimeError("USB changed before its lifetime could be pinned")
            # Keep every USB ancestor alive too: do_rebind locks the parent.
            current = self.path.resolve()
            while (current / "busnum").exists():
                bus = int((current / "busnum").read_text())
                number = int((current / "devnum").read_text())
                fd = os.open(
                    f"/dev/bus/usb/{bus:03}/{number:03}",
                    os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                )
                self.fds.append(fd)
                info = os.fstat(fd)
                if not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 189:
                    raise LifetimeError("USB lifetime reference is not a usbfs device")
                if os.minor(info.st_rdev) != (bus - 1) * 128 + number - 1:
                    raise LifetimeError("USB lifetime reference changed")
                current = current.parent
            self.validate()
            # Ignore older queued events, including a previous incarnation with
            # a reused port and USB device number.
            self.sequence = int(Path("/sys/kernel/uevent_seqnum").read_text())
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _object(info):
        return info.st_dev, info.st_ino

    def read(self, name):
        try:
            fd = os.open(
                name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=self.directory
            )
        except FileNotFoundError:
            if name == "serial":
                return ""
            raise
        try:
            return os.read(fd, 1024).decode().strip()
        finally:
            os.close(fd)

    def validate(self):
        if (
            self._object(os.stat(self.path)) != self.object
            or int(self.read("busnum")) != self.bus
            or int(self.read("devnum")) != self.number
            or any(
                self.read(name) != self.identity[key]
                for key, name in [
                    ("vendor", "idVendor"),
                    ("product", "idProduct"),
                    ("serial", "serial"),
                ]
            )
        ):
            raise LifetimeError("Pinned USB was removed or replaced")

    def confirm(self, disarm):
        # REMOV prevents a replacement from overwriting the table's udev pointer.
        # Verify the pinned original is still bound AFTER that transition.
        disarm(self.path.name)
        self.validate()
        if Path(os.readlink("driver", dir_fd=self.directory)).name != "usbip-host":
            raise LifetimeError("Pinned USB was not bound by USB/IP")
        self.read("usbip_status")
        self.ready = True

    def poll_removed(self):
        while True:
            try:
                packet, _, flags, sender = self.events.recvmsg(65536)
            except BlockingIOError:
                return self.removed
            except OSError as exc:
                self.ready = False
                raise LifetimeError(
                    "USB removal events were lost; restart the host before reusing this slot"
                ) from exc
            if flags & socket.MSG_TRUNC:
                self.ready = False
                raise LifetimeError("Truncated USB removal event")
            if sender[0] != 0:
                continue
            fields = dict(
                value.split(b"=", 1) for value in packet.split(b"\0") if b"=" in value
            )
            if (
                fields.get(b"ACTION") == b"remove"
                and fields.get(b"DEVTYPE") == b"usb_device"
                and fields.get(b"DEVPATH") == self.devpath.encode()
                and fields.get(b"BUSNUM") == f"{self.bus:03}".encode()
                and fields.get(b"DEVNUM") == f"{self.number:03}".encode()
                and int(fields.get(b"SEQNUM", b"0")) > self.sequence
            ):
                self.removed = True

    def release(self, match, unbind):
        if not self.ready:
            raise LifetimeError(
                "USB bind was not verified; restart the host before reusing this slot"
            )
        self.poll_removed()
        if not self.removed:
            try:
                self.validate()
            except (OSError, LifetimeError):
                # Enumeration may already have removed sysfs while disconnect is
                # still running. Wait for its completed USB-device remove event.
                deadline = time.monotonic() + 2
                while not self.poll_removed() and time.monotonic() < deadline:
                    time.sleep(0.02)
                if not self.removed:
                    raise LifetimeError(
                        "Waiting for completed USB removal; no slot recovery was attempted"
                    )
            else:
                unbind(self.path.name)
                if self.path.name not in match.read_text().split():
                    self.close()
                    return
                # Physical disconnect can race the native unbind. Only a remove
                # event allows the pinned absent path below.
                if not self.poll_removed():
                    raise LifetimeError("USB/IP unbind did not clear its match")
        # Unlike a stale pathname, these still-open usbfs files pin the exact
        # udev and parent referenced by this verified REMOV slot. No newer probe
        # can overwrite it. Removal notification is emitted after stub_disconnect.
        (match.parent / "rebind").write_text(self.path.name)
        if self.path.name in match.read_text().split():
            raise LifetimeError("Pinned USB/IP match cleanup was not confirmed")
        self.close()

    def close(self):
        for fd in self.fds:
            os.close(fd)
        self.fds.clear()
        self.events.close()
        self.ready = False
