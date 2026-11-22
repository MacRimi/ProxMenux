"""Disposable QEMU-only real-kernel USB/IP regression lab. Never use on a host."""

import contextlib, importlib.util, os, select, socket, subprocess, sys, tempfile, termios, time, tty
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/devices"))
import usbip_manager as m
from usbip_protocol import Gate


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result.stdout


def put(p, v):
    Path(p).write_text(v)


def wait(test):
    for _ in range(100):
        value = test()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition timed out")


def gadget(name, serial, udc):
    g = Path("/sys/kernel/config/usb_gadget") / name
    g.mkdir()
    for f, v in [("idVendor", "0x1d6b"), ("idProduct", "0x0104")]:
        put(g / f, v)
    (g / "strings/0x409").mkdir()
    for f, v in [
        ("serialnumber", serial),
        ("manufacturer", "Regression lab"),
        ("product", name),
    ]:
        put(g / "strings/0x409" / f, v)
    (g / "configs/c.1").mkdir()
    (g / "functions/acm.usb0").mkdir()
    (g / "configs/c.1/acm.usb0").symlink_to(g / "functions/acm.usb0")
    put(g / "UDC", udc)
    return g


def find(serial):
    return next((d for d in m.inventory() if d["serial"] == serial), None)


def chosen(serial, id):
    return dict(wait(lambda: find(serial)), id=id)


def control(port, busid):
    import struct

    with socket.create_connection(("127.0.0.1", port)) as s:
        s.sendall(
            struct.pack("!HHI", 0x111, 0x8003, 0) + busid.encode().ljust(32, b"\0")
        )
        reply = s.recv(8)
        assert len(reply) == 8
        return struct.unpack("!HHI", reply)[2]


def main():
    assert sys.argv[1:] == [
        "--disposable-vm"
    ], "Requires --disposable-vm on a fresh throwaway QEMU VM"
    assert (
        os.geteuid() == 0 and "QEMU" in Path("/sys/class/dmi/id/sys_vendor").read_text()
    )
    assert not Path("/sys/kernel/config/usb_gadget").exists() or not list(
        Path("/sys/kernel/config/usb_gadget").iterdir()
    ), "Start with a fresh disposable VM"

    run("modprobe", "dummy_hcd", "num=3")
    run("modprobe", "libcomposite")
    run("modprobe", "usbip-host")
    run("modprobe", "vhci-hcd")
    udcs = sorted(p.name for p in Path("/sys/class/udc").iterdir())
    assert len(udcs) == 3

    a_udc = udcs[0]
    a = gadget("selected-a", "original-a", udcs[0])
    b = gadget("selected-b", "original-b", udcs[1])
    time.sleep(0.5)
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        m.CONFIG_DIR = root / "config"
        m.SERVER_RUN_DIR = root / "run"
        m.RUN_DIR = root / "client"
        selected_a = chosen("original-a", "abcdef123456")
        selected_b = chosen("original-b", "fedcba654321")
        config = {"server": True, "exports": [selected_a, selected_b], "imports": []}
        m.atomic_json(m.CONFIG_DIR / "config.json", config)
        owned = {}
        leases = {}
        daemon = subprocess.Popen(
            ["usbipd", "-4"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        gate = None
        proxy = None
        try:
            assert not (errors := m.reconcile_exports(config, owned, leases)), errors

            def claim(name):
                for selected in config["exports"]:
                    id = selected["id"]
                    lease = leases.get(id)
                    record = owned.get(id)
                    if lease and lease.ready and record and record["busid"] == name:
                        return dict(record, id=id)

            gate = Gate(root / "gate.sock", 0, claim)
            proxy = subprocess.Popen(
                [
                    "socat",
                    "TCP-LISTEN:33240,bind=127.0.0.1,reuseaddr,fork",
                    "UNIX-CONNECT:" + str(root / "gate.sock"),
                ]
            )
            time.sleep(0.2)
            # A native independent client remains attached throughout A's physical cycle.
            print(
                run(
                    "usbip",
                    "--tcp-port",
                    "33240",
                    "attach",
                    "-r",
                    "127.0.0.1",
                    "-b",
                    selected_b["busid"],
                ),
                flush=True,
            )

            def serial_transfer(gadget=b, serial="original-b"):
                # Gadget B's function tty and remote vhci serial port, not local A's tty.
                gadget_tty = (
                    "/dev/ttyGS"
                    + (gadget / "functions/acm.usb0/port_num").read_text().strip()
                )
                client = wait(
                    lambda: next(
                        (
                            p
                            for p in Path("/sys/class/tty").glob("ttyACM*")
                            if "vhci_hcd" in str(p.resolve())
                            and any(
                                (q / "serial").exists()
                                and (q / "serial").read_text().strip() == serial
                                for q in p.resolve().parents
                            )
                        ),
                        None,
                    )
                )
                with contextlib.ExitStack() as stack:
                    fds = [
                        os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                        for path in (gadget_tty, "/dev/" + client.name)
                    ]
                    for fd in fds:
                        stack.callback(os.close, fd)
                        tty.setraw(fd)
                        termios.tcflush(fd, termios.TCIOFLUSH)
                    payload = b"independent-b-still-transferring\n"
                    os.write(fds[0], payload)
                    assert select.select([fds[1]], [], [], 3)[0]
                    assert os.read(fds[1], len(payload)) == payload

            serial_transfer()
            for iteration in range(20):
                put(a / "UDC", "\n")
                time.sleep(0.03)
                m.reconcile_exports(config, owned, leases)
                assert selected_a["busid"] not in m.MATCH_BUSID.read_text().split()
                put(a / "UDC", a_udc)
                wait(lambda: find("original-a"))
                time.sleep(0.25)
                assert not (
                    errors := m.reconcile_exports(config, owned, leases)
                ), errors
                assert leases[selected_a["id"]].ready
                serial_transfer()
            print(
                "PASS: 20 unplug/replug cycles; stale slot removed and original exported; independent native serial transfer survives",
                flush=True,
            )
            put(a / "UDC", "\n")
            time.sleep(0.05)
            m.reconcile_exports(config, owned, leases)
            a_udc = udcs[2]
            put(a / "UDC", a_udc)
            wait(lambda: find("original-a"))
            time.sleep(0.25)
            assert not (errors := m.reconcile_exports(config, owned, leases)), errors
            assert owned[selected_a["id"]]["busid"] != selected_a["busid"]
            serial_transfer()
            print(
                "PASS: moving original to another USB port preserves independent serial transfer",
                flush=True,
            )
            # An unselected replacement returns to a local driver and cannot import.
            put(a / "UDC", "\n")
            time.sleep(0.05)
            put(a / "strings/0x409/serialnumber", "unselected-replacement")
            put(a / "UDC", a_udc)
            replacement = wait(lambda: find("unselected-replacement"))
            errors = m.reconcile_exports(config, owned, leases)
            assert selected_a["id"] in errors
            assert find("unselected-replacement")["driver"] == "usb"
            assert control(33240, replacement["busid"]) != 0
            # Also bind that unselected replacement in a separate native setup: the
            # daemon can see it, but a direct import through our gate must still fail.
            run("usbip", "bind", "-b", replacement["busid"])
            assert replacement["busid"] in run("usbip", "list", "-r", "127.0.0.1")
            assert control(33240, replacement["busid"]) != 0
            m.reconcile_exports(config, owned, leases)
            assert find("unselected-replacement")["driver"] == "usbip-host"
            run("usbip", "unbind", "-b", replacement["busid"])
            serial_transfer()
            print(
                "PASS: same-port replacement stays local, native import rejected, independent serial survives",
                flush=True,
            )
            # Same original then can be selected, imported and exchange native URBs.
            put(a / "UDC", "\n")
            time.sleep(0.1)
            put(a / "strings/0x409/serialnumber", "original-a")
            put(a / "UDC", a_udc)
            wait(lambda: find("original-a"))
            time.sleep(0.25)
            assert not (errors := m.reconcile_exports(config, owned, leases)), errors
            print(
                run(
                    "usbip",
                    "--tcp-port",
                    "33240",
                    "attach",
                    "-r",
                    "127.0.0.1",
                    "-b",
                    find("original-a")["busid"],
                ),
                flush=True,
            )
            wait(lambda: len(m.imported_ports()) == 2)
            serial_transfer(a, "original-a")
            serial_transfer()
            for port in m.imported_ports():
                if port["busid"] == find("original-a")["busid"]:
                    run("usbip", "detach", "-p", str(port["port"]))
            # Simulate losing process-owned descriptors before a present-device
            # release. The manager must acquire and verify fresh usbfs pins.
            leases.pop(selected_a["id"]).close()
            config["exports"] = [selected_b]
            assert not (errors := m.reconcile_exports(config, owned, leases)), errors
            assert find("original-a")["driver"] == "usb"
            serial_transfer()
            print(
                "PASS: original reimport and present-device release restore local driver",
                flush=True,
            )
        finally:
            if proxy:
                proxy.terminate()
                proxy.wait()
            if gate:
                gate.terminate()
            for port in m.imported_ports():
                with contextlib.suppress(Exception):
                    run("usbip", "detach", "-p", str(port["port"]))
            config["exports"] = []
            print("cleanup", m.reconcile_exports(config, owned, leases), flush=True)
            daemon.terminate()
            daemon.wait()
            for lease in leases.values():
                lease.close()
    print("PASS: no Oops/BUG in kernel log", flush=True)
    for g in (a, b):
        if (g / "UDC").read_text().strip():
            put(g / "UDC", "\n")
        (g / "configs/c.1/acm.usb0").unlink()
        (g / "functions/acm.usb0").rmdir()
        (g / "configs/c.1").rmdir()
        (g / "strings/0x409").rmdir()
        g.rmdir()
    assert not any(
        x in run("dmesg") for x in ["BUG:", "Oops:", "general protection fault"]
    )


if __name__ == "__main__":
    main()
