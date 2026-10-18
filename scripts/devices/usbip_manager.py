#!/usr/bin/env python3
"""Manage selected USB/IP exports and Linux clients over authenticated SSH.

The server unit has a private network namespace. OpenSSH reaches its root-only
filesystem Unix socket; usbipd never listens in the host's network namespace.
Only this module's recorded devices and imported ports are released on stop.
"""

import argparse
from contextlib import contextmanager
import copy
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid

CONFIG_DIR = Path("/etc/proxmenux/usbip")
RUN_DIR = Path("/run/proxmenux-usbip")
SERVER_RUN_DIR = Path("/run/proxmenux-usbip-server")
UNIT_DIR = Path("/etc/systemd/system")
SYSFS = Path("/sys/bus/usb/devices")
SCRIPT = Path(__file__).resolve()
REMOTE_SCRIPT = "/usr/local/share/proxmenux/scripts/devices/usbip_manager.py"
REMOTE_SOCKET = "/run/proxmenux-usbip-server/usbip.sock"
SERVER_UNIT = "proxmenux-usbip-server.service"
MARKER = "# Managed by ProxMenux USB/IP"
BUSID = re.compile(r"[0-9]+-[0-9]+(?:\.[0-9]+)*\Z")
IDENTIFIER = re.compile(r"[a-f0-9]{12}\Z")


class USBIPError(Exception):
    pass


def run(args, timeout=20):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise USBIPError(f"Could not run {args[0]}: {type(exc).__name__}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise USBIPError(f"{Path(args[0]).name} failed: {detail}")
    return result.stdout


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".usbip-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path, default):
    try:
        if path.stat().st_size > 1024 * 1024:
            raise USBIPError(f"File is too large: {path}")
        return json.loads(path.read_text())
    except FileNotFoundError:
        return copy.deepcopy(default)
    except (ValueError, OSError) as exc:
        raise USBIPError(f"Cannot read {path}") from exc


def load_config():
    value = read_json(CONFIG_DIR / "config.json", {"server": False, "exports": [], "imports": []})
    if not isinstance(value, dict) or not isinstance(value.get("server"), bool):
        raise USBIPError("Invalid USB/IP configuration")
    for field in ("exports", "imports"):
        if not isinstance(value.get(field), list) or len(value[field]) > 64:
            raise USBIPError("Invalid USB/IP configuration")
        for item in value[field]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not IDENTIFIER.fullmatch(item["id"]):
                raise USBIPError("Invalid USB/IP device identifier")
    return value


@contextmanager
def config_lock():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (CONFIG_DIR / ".lock").open("a") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def attribute(path, name):
    try:
        return (path / name).read_text().strip()[:200]
    except (FileNotFoundError, OSError):
        return ""


def inventory():
    devices = []
    for path in sorted(SYSFS.glob("*")):
        if not BUSID.fullmatch(path.name):
            continue
        vendor, product = attribute(path, "idVendor"), attribute(path, "idProduct")
        if not re.fullmatch(r"[a-fA-F0-9]{4}", vendor) or not re.fullmatch(r"[a-fA-F0-9]{4}", product):
            continue
        classes = {attribute(path, "bDeviceClass").lower()}
        classes.update(attribute(p, "bInterfaceClass").lower() for p in path.glob(f"{path.name}:*"))
        # Interfaces are also symlinked directly below /sys/bus/usb/devices.
        classes.update(attribute(p, "bInterfaceClass").lower() for p in SYSFS.glob(f"{path.name}:*"))
        blocked = "USB hubs cannot be shared" if "09" in classes else (
            "USB mass storage cannot be shared" if "08" in classes else (
                "USB class could not be read" if not re.fullmatch(r"[a-f0-9]{2}", attribute(path, "bDeviceClass").lower()) else ""))
        try:
            driver = (path / "driver").resolve(strict=True).name
        except OSError:
            driver = ""
        devices.append({"busid": path.name, "vendor": vendor.lower(), "product": product.lower(),
                        "serial": attribute(path, "serial"), "name": attribute(path, "product") or f"{vendor}:{product}",
                        "driver": driver, "blocked": blocked})
    return devices


def same_device(expected, device):
    if any(expected.get(k) != device.get(k) for k in ("vendor", "product", "serial")):
        return False
    return bool(expected.get("serial")) or expected.get("busid") == device.get("busid")


def resolve_device(expected, devices):
    matches = [d for d in devices if same_device(expected, d)]
    if len(matches) != 1:
        raise USBIPError("Device is missing or its identity is ambiguous")
    if matches[0]["blocked"]:
        raise USBIPError(matches[0]["blocked"])
    return matches[0]


def state_path():
    return SERVER_RUN_DIR / "exports.json"


def release_export(identifier, owned, devices):
    previous = owned[identifier]
    current = next((d for d in devices if d["busid"] == previous["busid"]), None)
    if current and same_device(previous, current) and current["driver"] == "usbip-host":
        run(["usbip", "unbind", "--busid", current["busid"]])
    del owned[identifier]
    atomic_json(state_path(), owned)


def reconcile_exports(config, owned):
    devices = inventory()
    desired = {item["id"]: item for item in config["exports"]} if config["server"] else {}
    errors = {}
    for identifier in list(owned):
        if identifier not in desired:
            try:
                release_export(identifier, owned, devices)
            except USBIPError as exc:
                errors[identifier] = str(exc)
    for identifier, selected in desired.items():
        try:
            device = resolve_device(selected, devices)
            previous = owned.get(identifier)
            if previous and (previous["busid"] != device["busid"] or not same_device(previous, device)):
                release_export(identifier, owned, devices)
                previous = None
            if device["driver"] == "usbip-host":
                if not previous:
                    raise USBIPError("Device is already exported outside ProxMenux; it was not adopted")
                continue
            # Record intent before binding, so a crash cannot orphan our export.
            owned[identifier] = {k: device[k] for k in ("busid", "vendor", "product", "serial")}
            atomic_json(state_path(), owned)
            run(["usbip", "bind", "--busid", device["busid"]])
        except USBIPError as exc:
            errors[identifier] = str(exc)
    atomic_json(SERVER_RUN_DIR / "status.json", {"errors": errors, "updated": time.time()})
    return errors


def catalog():
    config, devices, owned = load_config(), inventory(), read_json(state_path(), {})
    exports = []
    for selected in config["exports"]:
        row = dict(selected, status="waiting", busid=None)
        try:
            current = resolve_device(selected, devices)
            if config["server"] and selected["id"] in owned and current["driver"] == "usbip-host" and (
                owned[selected["id"]]["busid"] == current["busid"] and same_device(owned[selected["id"]], current)
            ):
                row.update(busid=current["busid"], status="exported")
        except USBIPError as exc:
            row["error"] = str(exc)
        exports.append(row)
    return exports


def systemd_quote(value):
    if any(ord(c) < 32 for c in str(value)):
        raise USBIPError("Control characters are not allowed in systemd arguments")
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def unit_text(role, identifier=None):
    command = f"{systemd_quote(sys.executable)} {systemd_quote(SCRIPT)}"
    if role == "server":
        extra = "PrivateNetwork=yes\nRuntimeDirectory=proxmenux-usbip-server\nRuntimeDirectoryMode=0700\nRuntimeDirectoryPreserve=yes\n"
        start = f"{command} serve"
        module = "usbip-host"
    else:
        if not IDENTIFIER.fullmatch(identifier or ""):
            raise USBIPError("Invalid import identifier")
        start = f"{command} connect {identifier}"
        module = "vhci-hcd"
    import shutil
    modprobe = shutil.which("modprobe")
    if not modprobe:
        raise USBIPError("modprobe is not installed")
    return (f"{MARKER}\n[Unit]\nDescription=ProxMenux USB/IP {role} over SSH\n"
            + ("Wants=network-online.target\nAfter=network-online.target\n" if role == "client" else "")
            + "StartLimitIntervalSec=0\n\n[Service]\nType=simple\nUser=root\nUMask=0077\n"
            + f"ExecStartPre={systemd_quote(modprobe)} {module}\nExecStart={start}\n"
            + "Restart=on-failure\nRestartSec=5\nTimeoutStopSec=30\nPrivateTmp=yes\nNoNewPrivileges=yes\n"
            + (extra if role == "server" else "")
            + "\n[Install]\nWantedBy=multi-user.target\n")


def unit_name(identifier):
    if not IDENTIFIER.fullmatch(identifier):
        raise USBIPError("Invalid import identifier")
    return f"proxmenux-usbip-client-{identifier}.service"


def check_unit_owned(name):
    path = UNIT_DIR / name
    if path.is_symlink() or (path.exists() and not path.read_text().startswith(MARKER + "\n")):
        raise USBIPError(f"Refusing to replace a unit not owned by ProxMenux: {name}")
    return path


def write_unit(name, content):
    path = check_unit_owned(name)
    path.write_text(content)
    path.chmod(0o644)


def enable_unit(name, content):
    path = check_unit_owned(name)
    original = path.read_text() if path.exists() else None
    try:
        write_unit(name, content)
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "enable", "--now", name], timeout=40)
        run(["systemctl", "is-active", "--quiet", name])
    except USBIPError:
        if original is None:
            try:
                run(["systemctl", "disable", "--now", name], timeout=40)
            except USBIPError:
                pass
            path.unlink(missing_ok=True)
        else:
            path.write_text(original)
        run(["systemctl", "daemon-reload"])
        raise


def remove_unit(name):
    path = check_unit_owned(name)
    if path.exists():
        run(["systemctl", "disable", "--now", name], timeout=40)
        path.unlink()
        run(["systemctl", "daemon-reload"])


def validate_remote(host, port, key):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
            raise USBIPError("Enter an IP address or DNS hostname without a username or SSH options")
    if not 1 <= int(port) <= 65535:
        raise USBIPError("Invalid SSH port")
    key_path = Path(key)
    if not key_path.is_absolute() or any(ord(c) < 32 for c in key):
        raise USBIPError("SSH key must be an absolute path")
    try:
        mode = key_path.stat()
        if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.geteuid() or mode.st_mode & 0o077:
            raise USBIPError("SSH key must belong to this user and have permissions 0600 or 0400")
    except OSError as exc:
        raise USBIPError("SSH private key is not readable") from exc
    return {"host": host, "ssh_port": int(port), "key": str(key_path)}


def ssh_args(remote):
    return ["ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
            "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no", "-o", "ControlMaster=no",
            "-o", "ControlPath=none", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", "-o", "ExitOnForwardFailure=yes",
            "-p", str(remote["ssh_port"]), "-i", remote["key"], "-l", "root"]


def remote_catalog(remote):
    # The remote command is fixed. All user input stays in separate local argv.
    output = run(ssh_args(remote) + ["--", remote["host"], f"python3 {REMOTE_SCRIPT} catalog"])
    try:
        result = json.loads(output)
        if not isinstance(result, list) or len(result) > 64:
            raise ValueError()
        for item in result:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not IDENTIFIER.fullmatch(item["id"]):
                raise ValueError()
            if item.get("busid") is not None and (not isinstance(item["busid"], str) or not BUSID.fullmatch(item["busid"])):
                raise ValueError()
        return result
    except (ValueError, TypeError) as exc:
        raise USBIPError("Remote host did not return a valid ProxMenux USB/IP catalog") from exc


def tunnel_args(selected):
    return ssh_args(selected) + ["-N", "-L", f"127.0.0.1:{selected['local_port']}:{REMOTE_SOCKET}",
                                 "--", selected["host"]]


def parse_ports(output):
    ports, current = [], None
    for line in output.splitlines():
        match = re.match(r"Port (\d+): <([^>]+)>", line)
        if match:
            current = {"port": int(match[1]), "status": match[2]}
            continue
        match = re.match(r"\s*(\S+) -> usbip://([^\s/]+):([0-9]+)/([0-9.-]+)\s*$", line)
        if match and current is not None:
            ports.append(dict(current, local_busid=match[1], host=match[2], tcp_port=int(match[3]), busid=match[4]))
            current = None
    return ports


def imported_ports():
    return parse_ports(run(["usbip", "port"]))


def owns_import(saved, current):
    return all(saved.get(k) == current.get(k) for k in ("port", "local_busid", "host", "tcp_port", "busid"))


def release_import(path):
    saved = read_json(path, None)
    if saved:
        for current in imported_ports():
            if owns_import(saved, current):
                run(["usbip", "detach", "--port", str(current["port"])])
    path.unlink(missing_ok=True)


def find_import(selected, busid):
    return next((p for p in imported_ports() if p["host"] == "127.0.0.1" and
                 p["tcp_port"] == selected["local_port"] and p["busid"] == busid), None)


def attach_once(selected, owner):
    saved = read_json(owner, None)
    if saved:
        existing = next((p for p in imported_ports() if owns_import(saved, p)), None)
        if existing and existing["status"] == "Port in Use":
            return existing
        # A kernel port in an error state must be released before retrying.
        release_import(owner)
    remote = next((e for e in remote_catalog(selected) if e["id"] == selected["export_id"]), None)
    if not remote or remote.get("status") != "exported" or not remote.get("busid"):
        raise USBIPError("Remote device is unplugged, disabled or waiting to be exported")
    if find_import(selected, remote["busid"]):
        raise USBIPError("This endpoint has an unowned import; it was not adopted or detached")
    run(["usbip", "--tcp-port", str(selected["local_port"]), "attach", "--remote", "127.0.0.1",
         "--busid", remote["busid"]])
    # The kernel publishes the port record shortly after attach returns.
    attached = None
    for _ in range(20):
        attached = find_import(selected, remote["busid"])
        if attached:
            break
        time.sleep(0.25)
    if not attached:
        raise USBIPError("USB/IP did not report an attached port")
    atomic_json(owner, attached)
    return attached


def require_private_network():
    if os.readlink("/proc/self/ns/net") == os.readlink("/proc/1/ns/net"):
        raise USBIPError("The USB/IP server must run in its systemd PrivateNetwork namespace")


def stop_child(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextmanager
def stop_event():
    import threading
    stopped = threading.Event()
    old = {sig: signal.signal(sig, lambda *_: stopped.set()) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        yield stopped
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


def serve():
    require_private_network()
    SERVER_RUN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    SERVER_RUN_DIR.chmod(0o700)
    socket_path = SERVER_RUN_DIR / "usbip.sock"
    socket_path.unlink(missing_ok=True)
    owned = read_json(state_path(), {})
    daemon = proxy = None
    try:
        daemon = subprocess.Popen(["usbipd", "--ipv4", "--tcp-port", "3240"])
        proxy = subprocess.Popen(["socat", f"UNIX-LISTEN:{socket_path},mode=0600,fork",
                                  "TCP:127.0.0.1:3240"])
        with stop_event() as stopped:
            previous_errors = None
            while not stopped.is_set():
                if daemon.poll() is not None or proxy.poll() is not None:
                    raise USBIPError("USB/IP daemon or Unix proxy exited")
                config = load_config()
                if not config["server"]:
                    break
                errors = reconcile_exports(config, owned)
                if errors != previous_errors:
                    for identifier, error in errors.items():
                        print(f"Export {identifier}: {error}", file=sys.stderr, flush=True)
                    previous_errors = errors
                stopped.wait(3)
    finally:
        devices = inventory()
        for identifier in list(owned):
            try:
                release_export(identifier, owned, devices)
            except USBIPError as exc:
                print(f"Could not release export {identifier}: {exc}", file=sys.stderr, flush=True)
        stop_child(proxy)
        stop_child(daemon)
        socket_path.unlink(missing_ok=True)


def connect(identifier):
    selected = next((i for i in load_config()["imports"] if i["id"] == identifier), None)
    if selected is None:
        raise USBIPError("Import not found")
    validate_remote(selected["host"], selected["ssh_port"], selected["key"])
    RUN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner = RUN_DIR / f"client-{identifier}.json"
    status_path = RUN_DIR / f"client-{identifier}-status.json"
    tunnel, last_error = None, None
    try:
        # Recover only this client's exact previous port after an interrupted run.
        release_import(owner)
        with stop_event() as stopped:
            while not stopped.is_set():
                try:
                    if tunnel is None or tunnel.poll() is not None:
                        release_import(owner)
                        stop_child(tunnel)
                        tunnel = subprocess.Popen(tunnel_args(selected), stdin=subprocess.DEVNULL)
                        if stopped.wait(1):
                            break
                        if tunnel.poll() is not None:
                            raise USBIPError("SSH tunnel failed; check key, host key and forwarding permissions")
                    attached = attach_once(selected, owner)
                    atomic_json(status_path, {"state": "attached", "port": attached["port"], "updated": time.time()})
                    last_error = None
                except USBIPError as exc:
                    atomic_json(status_path, {"state": "waiting", "error": str(exc), "updated": time.time()})
                    if str(exc) != last_error:
                        print(str(exc), file=sys.stderr, flush=True)
                        last_error = str(exc)
                stopped.wait(5)
    finally:
        try:
            release_import(owner)
        finally:
            stop_child(tunnel)
            atomic_json(status_path, {"state": "stopped", "updated": time.time()})


def update_server(enabled):
    with config_lock():
        config = load_config()
        previous = copy.deepcopy(config)
        check_unit_owned(SERVER_UNIT)
        config["server"] = enabled
        atomic_json(CONFIG_DIR / "config.json", config)
        try:
            if enabled:
                enable_unit(SERVER_UNIT, unit_text("server"))
            else:
                remove_unit(SERVER_UNIT)
                # Retry cleanup even if the worker had previously crashed.
                owned = read_json(state_path(), {})
                errors = reconcile_exports(config, owned)
                if errors:
                    raise USBIPError("Server stopped, but some device bindings could not be released; check status and retry disable")
        except USBIPError:
            if enabled:
                atomic_json(CONFIG_DIR / "config.json", previous)
            raise


def add_export(busid):
    if not BUSID.fullmatch(busid):
        raise USBIPError("Invalid USB bus ID")
    with config_lock():
        config = load_config()
        if len(config["exports"]) >= 64:
            raise USBIPError("At most 64 exports can be configured")
        if not config["server"]:
            raise USBIPError("Enable the USB/IP server first")
        device = next((d for d in inventory() if d["busid"] == busid), None)
        if not device:
            raise USBIPError("Device not found")
        if device["blocked"]:
            raise USBIPError(device["blocked"])
        if device["driver"] == "usbip-host":
            raise USBIPError("Device is already exported; it was not adopted")
        if any(same_device(e, device) for e in config["exports"]):
            raise USBIPError("Device is already configured")
        resolve_device(device, inventory())
        selected = {k: device[k] for k in ("busid", "vendor", "product", "serial", "name")}
        selected["id"] = uuid.uuid4().hex[:12]
        config["exports"].append(selected)
        atomic_json(CONFIG_DIR / "config.json", config)
        return selected


def remove_export(identifier):
    with config_lock():
        config = load_config()
        if not any(e["id"] == identifier for e in config["exports"]):
            raise USBIPError("Export not found")
        config["exports"] = [e for e in config["exports"] if e["id"] != identifier]
        atomic_json(CONFIG_DIR / "config.json", config)
        # The server loop releases only its own binding within three seconds.


def add_import(remote, export_id, local_port):
    if not IDENTIFIER.fullmatch(export_id):
        raise USBIPError("Invalid remote export ID")
    if not 1024 <= local_port <= 65535:
        raise USBIPError("Use a local TCP port between 1024 and 65535")
    exports = remote_catalog(remote)  # Authenticate and validate before saving anything.
    if not any(e["id"] == export_id and e.get("status") == "exported" for e in exports):
        raise USBIPError("Remote export is not available; enable the server and select a device first")
    with config_lock():
        config = load_config()
        if len(config["imports"]) >= 64:
            raise USBIPError("At most 64 imports can be configured")
        if any(i["local_port"] == local_port or (i["host"] == remote["host"] and
               i["ssh_port"] == remote["ssh_port"] and i["export_id"] == export_id) for i in config["imports"]):
            raise USBIPError("This remote device or local port is already configured")
        with socket.socket() as check:
            try:
                check.bind(("127.0.0.1", local_port))
            except OSError as exc:
                raise USBIPError("Local tunnel port is already in use") from exc
        previous = copy.deepcopy(config)
        selected = dict(remote, export_id=export_id, local_port=local_port, id=uuid.uuid4().hex[:12])
        config["imports"].append(selected)
        atomic_json(CONFIG_DIR / "config.json", config)
        try:
            enable_unit(unit_name(selected["id"]), unit_text("client", selected["id"]))
        except USBIPError:
            atomic_json(CONFIG_DIR / "config.json", previous)
            raise
        return selected


def remove_import(identifier):
    with config_lock():
        config = load_config()
        if not any(i["id"] == identifier for i in config["imports"]):
            raise USBIPError("Import not found")
        remove_unit(unit_name(identifier))
        # Also recover a port left by a process killed without its finally block.
        release_import(RUN_DIR / f"client-{identifier}.json")
        config["imports"] = [i for i in config["imports"] if i["id"] != identifier]
        atomic_json(CONFIG_DIR / "config.json", config)
        (RUN_DIR / f"client-{identifier}-status.json").unlink(missing_ok=True)


def status():
    config = load_config()
    result = {"server": config["server"], "exports": catalog(), "imports": []}
    def active(unit):
        try:
            run(["systemctl", "is-active", "--quiet", unit])
            return True
        except USBIPError:
            return False
    result["server_active"] = active(SERVER_UNIT)
    result["server_status"] = read_json(SERVER_RUN_DIR / "status.json", {})
    for item in config["imports"]:
        result["imports"].append(dict(item, active=active(unit_name(item["id"])),
                                      status=read_json(RUN_DIR / f"client-{item['id']}-status.json", {"state": "unknown"})))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "catalog", "status", "server-enable", "server-disable", "serve"):
        commands.add_parser(name)
    for name in ("add-export", "remove-export", "remove-import", "connect"):
        commands.add_parser(name).add_argument("identifier")
    for name in ("remote", "add-import"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--host", required=True)
        cmd.add_argument("--ssh-port", type=int, default=22)
        cmd.add_argument("--key", required=True)
        if name == "add-import":
            cmd.add_argument("--export-id", required=True)
            cmd.add_argument("--local-port", type=int, default=33240)
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise USBIPError("Run this manager as root")
        output = None
        if args.command == "inventory":
            output = inventory()
        elif args.command == "catalog":
            output = catalog()
        elif args.command == "status":
            output = status()
        elif args.command in ("server-enable", "server-disable"):
            update_server(args.command == "server-enable")
        elif args.command == "add-export":
            output = add_export(args.identifier)
        elif args.command == "remove-export":
            remove_export(args.identifier)
        elif args.command == "remove-import":
            remove_import(args.identifier)
        elif args.command == "serve":
            serve()
        elif args.command == "connect":
            connect(args.identifier)
        elif args.command in ("remote", "add-import"):
            remote = validate_remote(args.host, args.ssh_port, args.key)
            output = remote_catalog(remote) if args.command == "remote" else add_import(remote, args.export_id, args.local_port)
        if output is not None:
            print(json.dumps(output, indent=2))
    except (USBIPError, OSError) as exc:
        print(f"USB/IP: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
