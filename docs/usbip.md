# USB/IP over SSH

Open **Hardware: GPUs, Coral-TPU and USB/IP → USB/IP over SSH** to share a
selected USB device or connect this Linux machine to a device on another host.
The same menu is available through the main menu search (`usbip`, `zigbee`,
`bluetooth` or `printer`). This implements the host and Linux client setup
requested in [#350](https://github.com/MacRimi/ProxMenux/issues/350).

## Server

1. Enable the USB/IP server. Missing `usbip`, `socat`, `kmod` and `openssh-client`
   packages are offered from the existing Debian repositories. Repository and
   SSH server settings are preserved.
2. Choose **Share a local USB device** and select a device by its bus ID, product
   and serial number. Confirm that it will become unavailable to local programs
   and guests using ordinary USB passthrough.
3. Check **View USB/IP status**. The device should show `exported` and a bus ID.
   Binding errors are reported separately rather than treated as a successful
   export. Inspect the service log for startup errors:

   ```sh
   journalctl -u proxmenux-usbip-server.service
   ```

The server reloads saved selections every three seconds. Devices with a unique
serial number can return on a different physical USB port after reconnecting.
Without a serial number, the vendor/product and original bus ID must match;
the manager will not guess which identical dongle to bind. Duplicate serial
numbers are rejected as ambiguous. USB hubs and mass-storage devices, including
composite devices with a storage interface, are excluded.

**Stop sharing** removes one saved selection and releases its binding on the
next reconciliation. **Disable server** stops the service and releases its
managed exports, retaining selections for the next enable. Devices already
bound by another USB/IP setup are not adopted or unbound by this manager.
Native USB/IP unbind reprobes the device so its normal local driver can return.

## Transport and authentication

USB/IP has no built-in authentication or encryption. The generated server unit
uses systemd `PrivateNetwork=yes`: `usbipd --ipv4 --tcp-port 3240` and its
`socat` proxy run in an isolated network namespace. There is **no USB/IP TCP
listener in the host network namespace**, and this feature does not open a
firewall port. Running the manager's `serve` command outside a private network
namespace is rejected before spawning a listener.

The proxy exposes a filesystem Unix socket at
`/run/proxmenux-usbip-server/usbip.sock`, inside a root-only directory with a
0600 socket. Existing OpenSSH access forwards it to a loopback-only TCP port
on the client. The SSH server must permit stream-local forwarding. Unknown or
changed server host keys, bad SSH credentials and failed forwards are errors;
the manager never disables host-key checking or changes `sshd_config`.

The initial implementation uses **existing root SSH key access**. It does not
create keys or authorize root login. Use this only between machines for which
that access is already appropriate. Private key contents are never copied into
the manager configuration. The local tunnel port is accessible to local users
on the client, so the client machine must be trusted too.

## Linux VM/client

Run the client **inside the Linux VM that needs the device**. Connecting it to
a Proxmox node alone does not make that device migrate with a VM. A supported
Linux kernel must provide `vhci-hcd`; the server needs `usbip-host`. Proxmox
kernel packages normally provide these modules, but activation fails visibly
if they are missing. No out-of-tree kernel modules are installed.

The client can use the menu when ProxMenux is installed, or the standalone
standard-library Python manager. On a Debian Linux guest, install the packages
and copy `scripts/devices/usbip_manager.py` from the reviewed ProxMenux checkout:

```sh
apt-get install usbip openssh-client kmod
install -D -m 0755 usbip_manager.py /usr/local/share/proxmenux/scripts/devices/usbip_manager.py
```

First verify normal root SSH access from the client to the server using the
intended private key and port. Verify the server host-key fingerprint through
a trusted channel, then accept it through that normal SSH session. Automated
connections read root's normal `known_hosts` file. SSH config aliases and
`ProxyJump` settings are not used; enter the actual address and port.

Then choose **Connect a remote USB device** and provide the server address,
SSH port and absolute path to an existing private key (0400 or 0600). The menu
authenticates and lists the server's configured exports before saving a client.
Choose an unused local port for each device (33240 by default).

Equivalent standalone commands:

```sh
MANAGER=/usr/local/share/proxmenux/scripts/devices/usbip_manager.py
python3 "$MANAGER" remote --host 192.0.2.10 --ssh-port 22 --key /root/.ssh/id_ed25519
# Substitute the export ID returned by the server:
python3 "$MANAGER" add-import --host 192.0.2.10 --ssh-port 22 --key /root/.ssh/id_ed25519 --export-id abcdef123456 --local-port 33240
python3 "$MANAGER" status
```

The client has an enabled systemd service per device. It reconnects the SSH
tunnel and reattaches the device after a network interruption or restart. On
each new attach it resolves the **saved export ID** to the server's current bus
ID, so a serial-bearing dongle can move ports. The client keeps an ownership
record of the exact imported kernel port, local bus ID and remote endpoint;
cleanup detaches only a matching owned import. Removing a connection disables
its service, releases its device and removes its saved configuration.

Only **one client at a time** can attach a physical USB device. A device already
in use by another client may be listed as exported, but the kernel rejects a
second attach; the client reports the error and waits. Applications must handle
USB disconnect/reconnect themselves. A brief network interruption can still
reset the USB device and interrupt a Zigbee coordinator, printer or Bluetooth
session; this is not transparent USB high availability.

Unprivileged LXC, Home Assistant OS and non-Linux clients require their own
kernel/device permissions or add-on integration. This feature does not change
LXC privileges, edit VM passthrough settings or deploy HAOS add-ons. A standard
addon that expects raw USB/IP TCP also needs the SSH transport configured; it
cannot directly connect to this server's isolated daemon.

## Files and checks

- Root-only configuration: `/etc/proxmenux/usbip/config.json` (0600).
- Owned server unit: `proxmenux-usbip-server.service`.
- Owned client units: `proxmenux-usbip-client-<id>.service`.
- Server ownership/status: `/run/proxmenux-usbip-server/`.
- Client ownership/status: `/run/proxmenux-usbip/`, independent of server cleanup.
- Menu actions and package installations use the ProxMenux journal when present.

Validation includes fake sysfs/USB commands for identity and ownership, service
rollback and quoting, malformed catalogs, credential failures and reconnects.
The Linux CI also verifies generated units and exercises actual namespace
isolation and encrypted SSH forwarding with an echo fixture. Physical device
and guest-driver compatibility still requires a real deployment test.

Protocol and transport references:
[Linux USB/IP tools](https://github.com/torvalds/linux/tree/master/tools/usb/usbip),
[Debian usbip manual](https://manpages.debian.org/trixie/usbip/usbip.8.en.html),
[OpenSSH local socket forwarding](https://man.openbsd.org/ssh#L),
[systemd PrivateNetwork](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#PrivateNetwork=).
