"""Opt-in fresh-QEMU lab: actual generated units, restricted SSH and native USB URBs."""

import contextlib, os, select, shutil, sys, termios, time, tty
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/devices"))
from check_usbip_kernel import m, run, put, gadget, find


def wait(test, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = test()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("timeout")


def transfer(g, serial):
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
            for path in (
                "/dev/ttyGS" + (g / "functions/acm.usb0/port_num").read_text().strip(),
                "/dev/" + client.name,
            )
        ]
        for fd in fds:
            stack.callback(os.close, fd)
            tty.setraw(fd)
            termios.tcflush(fd, termios.TCIOFLUSH)
        for src, dst in ((fds[0], fds[1]), (fds[1], fds[0])):
            payload = b"actual-systemd-ssh-usbip-serial\n"
            os.write(src, payload)
            assert select.select([dst], [], [], 5)[0]
            assert os.read(dst, len(payload)) == payload


def main():
    assert sys.argv[1:] == [
        "--disposable-vm"
    ], "Requires --disposable-vm on a fresh throwaway QEMU VM"
    assert not Path("/etc/proxmenux/usbip").exists()
    assert "QEMU" in Path("/sys/class/dmi/id/sys_vendor").read_text()
    for name in ("usbip_manager.py", "usbip_protocol.py", "usbip_lifetime.py"):
        target = Path("/usr/local/share/proxmenux/scripts/devices") / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(m.SCRIPT.parent / name, target)
    run("modprobe", "dummy_hcd", "num=3")
    run("modprobe", "libcomposite")
    run("modprobe", "usbip-host")
    run("modprobe", "vhci-hcd")
    udcs = sorted(p.name for p in Path("/sys/class/udc").iterdir())
    assert len(udcs) == 3
    assert not list(Path("/sys/kernel/config/usb_gadget").iterdir())
    a = gadget("service-a", "service-a", udcs[0])
    b = gadget("service-b", "service-b", udcs[1])
    time.sleep(0.5)
    key = Path("/root/service-usbip-key")
    run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key))
    m.authorize_key(str(key) + ".pub")
    public = Path("/etc/ssh/ssh_host_ed25519_key.pub").read_text().split()
    Path("/root/.ssh/known_hosts").write_text(
        "127.0.0.1 " + public[0] + " " + public[1] + "\n"
    )
    imports = []
    try:
        m.update_server(True)
        sa = m.add_export(wait(lambda: find("service-a"))["busid"])
        sb = m.add_export(wait(lambda: find("service-b"))["busid"])
        wait(lambda: len([e for e in m.catalog() if e["status"] == "exported"]) == 2)
        remote = m.validate_remote("127.0.0.1", 22, str(key))
        for selected, port in ((sa, 33240), (sb, 33241)):
            imports.append(m.add_import(remote, selected["id"], port))
        wait(lambda: len(m.imported_ports()) == 2)
        transfer(a, "service-a")
        transfer(b, "service-b")
        print(
            "PASS: actual generated server/client systemd units and restricted SSH carry bidirectional native serial on two USBs",
            flush=True,
        )
        for cycle in range(3):
            put(a / "UDC", "\n")
            time.sleep(0.2)
            transfer(b, "service-b")
            put(a / "UDC", udcs[0])
            wait(lambda: find("service-a"))
            time.sleep(0.5)
            # An old vhci port may still exist; wait for the new guest driver and verify data.
            wait(
                lambda: next(
                    (
                        e
                        for e in m.catalog()
                        if e["id"] == sa["id"] and e["status"] == "exported"
                    ),
                    None,
                )
            )
            time.sleep(6)
            transfer(a, "service-a")
            transfer(b, "service-b")
        print(
            "PASS: three physical reconnects automatically reattach through restricted SSH; second serial connection survives",
            flush=True,
        )
        m.remove_export(sa["id"])
        assert find("service-a")["driver"] == "usb"
        transfer(b, "service-b")
        print(
            "PASS: stop-sharing waits for real release and returns local driver while independent client keeps transferring",
            flush=True,
        )
        for item in imports:
            m.remove_import(item["id"])
        imports = []
        m.update_server(False)
        assert not m.read_json(m.state_path(), {})
        assert find("service-b")["driver"] == "usb"
        print(
            "PASS: disable stops listeners, removes owned bindings, leaves both local USB drivers restored",
            flush=True,
        )
    finally:
        for item in imports:
            with contextlib.suppress(Exception):
                m.remove_import(item["id"])
        with contextlib.suppress(Exception):
            m.update_server(False)
        print(
            run("journalctl", "-u", m.SERVER_UNIT, "--no-pager", "-n", "20"), flush=True
        )


if __name__ == "__main__":
    main()
