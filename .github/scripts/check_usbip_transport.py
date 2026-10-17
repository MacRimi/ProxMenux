#!/usr/bin/env python3
"""Linux-only integration: real namespaces, socat and SSH; no USB hardware.

Run as root in the disposable CI runner. All keys, configuration, listeners and
child processes belong to a temporary fixture; no systemd units are installed.
"""
import importlib.util
import os
from pathlib import Path
import pwd
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[2] / "scripts/devices/usbip_manager.py"


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until(test, processes, log, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for process in processes:
            if process.poll() is not None:
                raise AssertionError(f"Fixture exited ({process.returncode}): {log.read_text()}")
        try:
            if test():
                return
        except (ConnectionError, FileNotFoundError, socket.timeout):
            pass
        time.sleep(0.1)
    raise AssertionError(f"Fixture did not become ready: {log.read_text()}")


def echo(sock):
    payload = bytes(range(256)) * 1024
    sock.settimeout(10)
    sock.sendall(payload)
    received = bytearray()
    while len(received) < len(payload):
        chunk = sock.recv(65536)
        if not chunk:
            break
        received.extend(chunk)
    assert bytes(received) == payload, "SSH/Unix/TCP forwarding corrupted the stream"


def main():
    assert sys.platform == "linux" and os.geteuid() == 0, "Use the disposable Linux CI runner as root"
    spec = importlib.util.spec_from_file_location("usbip_manager", SOURCE)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    # A mistaken direct launch must never create a listener in this namespace.
    try:
        manager.require_private_network()
    except manager.USBIPError:
        pass
    else:
        raise AssertionError("Expected the host namespace to be rejected")

    processes = []
    # StrictModes checks every ancestor of AuthorizedKeysFile. A private
    # subdirectory of /tmp still fails because /tmp itself is world writable.
    # Keep the disposable fixture below root's home without changing its SSH
    # configuration, account settings or existing authorized_keys.
    with tempfile.TemporaryDirectory(prefix="pmx-usbip-", dir=pwd.getpwuid(os.geteuid()).pw_dir) as directory:
        root = Path(directory)
        log = root / "transport.log"
        with log.open("w") as log_handle:
            try:
                fake_bin = root / "bin"
                fake_bin.mkdir()
                # The real daemon requires usbip-host and physical devices.
                # Echo stands in only for its TCP endpoint, inside the namespace.
                fake_daemon = fake_bin / "usbipd"
                fake_daemon.write_text("""#!/usr/bin/python3
import socketserver
class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            data = self.request.recv(65536)
            if not data:
                return
            self.request.sendall(data)
socketserver.ThreadingTCPServer.allow_reuse_address = True
socketserver.ThreadingTCPServer(('0.0.0.0', 3240), Echo).serve_forever()
""")
                fake_daemon.chmod(0o755)
                config = root / "config"
                manager.atomic_json(config / "config.json", {"server": True, "exports": [], "imports": []})
                server_run = root / "server"
                runner = root / "server.py"
                runner.write_text(f"""import importlib.util
from pathlib import Path
import subprocess
spec = importlib.util.spec_from_file_location('usbip_manager', {str(SOURCE)!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.CONFIG_DIR = Path({str(config)!r})
m.SERVER_RUN_DIR = Path({str(server_run)!r})
m.SYSFS = Path({str(root / 'no-usb-devices')!r})
subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True)
m.serve()
""")
                server = subprocess.Popen(["unshare", "--net", sys.executable, str(runner)],
                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                    stdout=log_handle, stderr=log_handle, start_new_session=True)
                processes.append(server)
                unix_path = server_run / "usbip.sock"
                wait_until(lambda: unix_path.exists(), [server], log)
                assert os.readlink(f"/proc/{server.pid}/ns/net") != os.readlink("/proc/self/ns/net")
                assert stat.S_IMODE(server_run.stat().st_mode) == 0o700
                assert stat.S_IMODE(unix_path.stat().st_mode) == 0o600
                # Linux /proc/net reflects the caller's network namespace.
                listening = subprocess.check_output(["ss", "-H", "-ltn", "sport", "=", ":3240"], text=True)
                assert not listening.strip(), "Raw USB/IP TCP leaked into the host network namespace"
                # Wait for both the proxy and its private TCP peer.
                def unix_ready():
                    with socket.socket(socket.AF_UNIX) as connection:
                        connection.connect(str(unix_path))
                        echo(connection)
                    return True
                wait_until(unix_ready, [server], log)

                for name in ("host", "client", "wrong-client"):
                    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / name)], check=True)
                authorized = root / "authorized_keys"
                authorized.write_text((root / "client.pub").read_text())
                authorized.chmod(0o600)
                known = root / "known_hosts"
                known.write_text("")
                known.chmod(0o600)
                ssh_port, local_port = port(), port()
                ssh_config = root / "sshd_config"
                ssh_config.write_text(f"""Port {ssh_port}
ListenAddress 127.0.0.1
HostKey {root / 'host'}
PidFile {root / 'sshd.pid'}
AuthorizedKeysFile {authorized}
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
UsePAM yes
StrictModes yes
AllowUsers root
AllowTcpForwarding local
AllowStreamLocalForwarding local
LogLevel VERBOSE
""")
                Path("/run/sshd").mkdir(exist_ok=True, mode=0o755)
                sshd = subprocess.Popen(["/usr/sbin/sshd", "-D", "-e", "-f", str(ssh_config)],
                                        stdout=log_handle, stderr=log_handle, start_new_session=True)
                processes.append(sshd)
                def ssh_ready():
                    with socket.create_connection(("127.0.0.1", ssh_port), timeout=1):
                        return True
                wait_until(ssh_ready, [server, sshd], log)
                remote = manager.validate_remote("127.0.0.1", ssh_port, str(root / "client"))
                extra = ["-o", f"UserKnownHostsFile={known}", "-o", "GlobalKnownHostsFile=/dev/null"]
                def check_ssh(selected):
                    args = manager.ssh_args(selected)
                    args[1:1] = extra
                    return subprocess.run(args + ["--", selected["host"], "true"], capture_output=True, text=True, timeout=15)
                unknown = check_ssh(remote)
                assert unknown.returncode != 0 and "Host key verification failed" in unknown.stderr, unknown.stderr
                host_public = (root / "host.pub").read_text().split()
                known.write_text(f"[127.0.0.1]:{ssh_port} {host_public[0]} {host_public[1]}\n")
                wrong = check_ssh(remote | {"key": str(root / "wrong-client")})
                assert wrong.returncode != 0 and "Permission denied" in wrong.stderr, wrong.stderr
                accepted = check_ssh(remote)
                assert accepted.returncode == 0, accepted.stderr + "\n" + log.read_text()
                manager.REMOTE_SOCKET = str(unix_path)
                args = manager.tunnel_args(remote | {"local_port": local_port})
                args[1:1] = extra
                tunnel = subprocess.Popen(args, stdout=log_handle, stderr=log_handle, start_new_session=True)
                processes.append(tunnel)
                def tunnel_ready():
                    with socket.create_connection(("127.0.0.1", local_port), timeout=1) as connection:
                        echo(connection)
                    return True
                wait_until(tunnel_ready, processes, log)
                listener = subprocess.check_output(["ss", "-H", "-ltn", "sport", "=", f":{local_port}"], text=True)
                assert f"127.0.0.1:{local_port}" in listener and f"0.0.0.0:{local_port}" not in listener, listener
                print("PASS: private namespace, root-only Unix socket, no host USB/IP listener")
                print("PASS: unknown host key and wrong client key rejected; valid key accepted")
                print("PASS: 256 KiB binary stream across real SSH -> Unix socket -> socat -> private TCP")
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                for process in reversed(processes):
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
