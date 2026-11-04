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

The server reloads saved selections every three seconds. A live exported device's
match is immediately marked for removal so the kernel rejects a later automatic
probe on that port. Physical unplug/replug remains an **unresolved limitation**:
upstream Linux can retain the match-table slot even after a successful `del`
write. The manager verifies disappearance before forgetting ownership or binding
a new port, and otherwise fails closed with a visible cleanup error. It never
calls `rebind` on an absent device or reloads a module affecting foreign exports.
Automatic reconnect after physical USB removal is therefore not yet guaranteed;
this PR needs maintainer review and a safe kernel-supported cleanup policy.
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

The proxy exposes `/run/proxmenux-usbip-server/usbip.sock` to the dedicated
`proxmenux-usbip` group (0660), inside a root-owned 0750 directory. Root alone
can read or change the managed device/configuration state. A separate group-readable
catalog contains only the selected USB device metadata.

Before enabling the server, choose **Authorize a client SSH public key** and
supply the path to a dedicated client's `.pub` file already copied to the server.
This creates a local system account `proxmenux-usbip` with a disabled password,
no administrative group membership, and a root-owned home and `authorized_keys`.
Each managed key uses OpenSSH `restrict` and a fixed forced command. The command
accepts only `catalog` (read selected devices) and `stream` (connect the one USB/IP
Unix socket). Shell commands, PTY, agent/X11 forwarding and TCP/Unix forwarding
are prohibited. This does not use or modify Proxmox's cluster-wide root keys,
root `authorized_keys`, or SSH server settings. A conflicting pre-existing
account/home is rejected rather than adopted. Authorize keys before starting
the server; `useradd` and an existing OpenSSH server are required.

The client holds its loopback TCP listening socket continuously, then launches
an SSH `stream` session for each connection. It does not release a port probe
and later ask SSH to bind the same port. Unknown or changed host keys and wrong
client keys fail closed. Create a dedicated key, not one used for root access.
Anyone with that key can access **all selected USB/IP exports**; it is not a
per-device authorization policy. Local users of the client can also connect to
the loopback port, so use trusted clients. To revoke a client, remove its managed
line from `/var/lib/proxmenux-usbip/.ssh/authorized_keys` and terminate its active
connections; deleting a key does not disconnect an existing SSH session.

Old configurations using root keys do not silently keep root access: clients
now connect only as `proxmenux-usbip`. Authorize a separate key on the server and
replace the saved client connection if it previously referenced a root key.

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

Generate a dedicated SSH client key (for example `/root/.ssh/id_usbip`) and
authorize its public key through the server menu. Verify the server host-key
fingerprint through a trusted channel and install it in the client's root
`known_hosts` file. Do not attempt an interactive login: the account intentionally
rejects a shell. SSH config aliases and `ProxyJump` settings are not used; enter
the actual address and port.

Then choose **Connect a remote USB device** and provide the server address,
SSH port and absolute path to an existing private key (0400 or 0600). The menu
authenticates and lists the server's configured exports before saving a client.
Choose an unused local port for each device (33240 by default).

Equivalent standalone commands:

```sh
MANAGER=/usr/local/share/proxmenux/scripts/devices/usbip_manager.py
python3 "$MANAGER" remote --host 192.0.2.10 --ssh-port 22 --key /root/.ssh/id_usbip
# Substitute the export ID returned by the server:
python3 "$MANAGER" add-import --host 192.0.2.10 --ssh-port 22 --key /root/.ssh/id_usbip --export-id abcdef123456 --local-port 33240
python3 "$MANAGER" status
```

The client has an enabled systemd service per device. It reconnects the SSH
tunnel and reattaches the device after a network interruption or restart. On
each new attach it resolves the **saved export ID** to the server's current bus
ID; physical port movement is subject to the kernel cleanup limitation above. The client keeps an ownership
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
isolation and restricted SSH sessions with an echo fixture. Physical device
and guest-driver compatibility still requires a real deployment test.

Protocol and transport references:
[Linux USB/IP tools](https://github.com/torvalds/linux/tree/master/tools/usb/usbip),
[Debian usbip manual](https://manpages.debian.org/trixie/usbip/usbip.8.en.html),
[OpenSSH authorized_keys restrictions](https://man.openbsd.org/sshd#AUTHORIZED_KEYS_FILE_FORMAT),
[systemd PrivateNetwork](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#PrivateNetwork=).
