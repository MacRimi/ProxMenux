# Plain LXC command

The installed entry point is `/usr/bin/python3 -I -B /usr/local/share/proxmenux/scripts/lxc/plain_lxc.py`.
It runs as root on the local Proxmox VE node. The console and any future
adapter send one UTF-8 JSON object on stdin. Every request has
`"schema_version": 1` and an `action`. The reply has the same version,
`ok`, and either `data` or a stable `error` code with an optional `field`.
An input or preflight error exits with status 1. Once admitted, a request
returns its operation state in `data`.

| Action | Request fields | Result |
| --- | --- | --- |
| `context` | None | Local node, available storage and bridges, official and local template candidates, native mount/device capabilities, existing device nodes, pending operations, limits, defaults and suggested VMID. |
| `plan` | `spec` | Normalized `plan`, `plan_hash`, and warnings. The selected archive is hashed; official candidates must match their catalog SHA-512 checksum. |
| `download_template` | `request_id`, `node`, `catalog_id`, `template_storage`, `confirmed: true` | Download operation status and the target volume ID. |
| `create` | `request_id`, `plan`, `plan_hash`, `accepted_warnings`, `confirmed: true`, and `secret.password` for password access | Creation operation status and VMID. |
| `status` | `request_id` | Latest observed state of the original operation. |
| `operations` | None | The calling UID's pending operation records, without credentials or private controller metadata. |
| `recover` | `request_id`, `confirmed: true` | Check the original operation and, only when safe, close its reservation. Never repeat create/start/download or delete resources. |
| `task_log` | `request_id`, `phase` (`create`, `prepare` or `start`), optional `offset` | Read-only page of the original Proxmox task log, resolved from the recorded operation. |

The following request produces a plan.

```json
{
  "schema_version": 1,
  "action": "plan",
  "spec": {
    "node": "pve",
    "vmid": 240,
    "hostname": "debian-test",
    "template": {"volume_id": "local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst"},
    "access": {"mode": "password"},
    "rootfs": {"storage": "local-lvm"},
    "network": {"bridge": "vmbr0", "vlan_tag": 200}
  }
}
```

Select inventory values from `context`. `access.mode` can be `password`,
`ssh_key`, or `both`. SSH access requires a list of `ssh_public_keys`.
`network: null` requests no network interface. A bridge defaults to DHCP.
The optional VLAN tag is available on OVS, VLAN-aware Linux bridges and
traditional Linux bridges with an uplink eligible for Proxmox VLAN tagging.
For static IPv4, pass `ipv4: {"mode":"static","cidr":"192.0.2.10/24"}` and an
optional `gateway`. The optional `dns` object accepts `nameservers` and
`search_domains` lists. Resource overrides are `rootfs.size_gib`,
`cpu.cores`, `memory.ram_mib` and `memory.swap_mib`. `onboot` and
`start_after_create`, `prepare_system` and `nesting` default to false.
Enabling nesting keeps the container unprivileged but exposes additional
host procfs/sysfs information; the reviewed plan requires explicit acceptance
of `nesting_enabled`. The native bridge permits only `nesting=0` or `nesting=1`,
not arbitrary feature strings. No guest service is silently disabled or masked.

Operation replies retain `task_warnings` and per-phase `task_warning_phases`
across creation and start, including a failed start. These describe Proxmox
task results, not OS health. Both original task logs remain available.

By default, creation uses native PVE template setup without the optional
ProxMenux first-boot modifications.
Without immediate start, no rootfs preparation task is submitted. Immediate
start uses the native PVE start under the same identity/configuration lock,
without running the preparation helper or mounting the rootfs for preparation.

With explicit `prepare_system: true`, the controller submits first-boot
preparation even when `start_after_create` is false. It runs under the native
container lock, on its own stopped, unprivileged rootfs. With immediate start,
preparation and the native `vm_start` share that lock and the `vzstart` log.
Without immediate start, a `vzprepare` task and `prepare` log record the work.
Known certificate units are serialized; the no-network plan can add a native
wait-online condition. Only the root volume is mounted for this step: planned
data volumes, host bind mounts and devices are excluded from that mount config.
Existing customizations are never overwritten. Nothing
executes inside the guest, installs packages or enables nesting automatically.
Preparation or unmount failure returns `partial`, `created: true` and
`preparation_failed`; no start follows. The task log contains diagnostics.
`prepared: true` is reported only after confirmed task success, not as OS health.
Status and request replay only observe tasks; a missed preparation submission
returns `preparation_not_submitted` and requires explicit recovery.

Use a fresh UUID encoded as 32 lowercase hex characters for each confirmed
operation. Send back the plan and its hash without editing them. The
adapter must obtain explicit confirmation and, for create, send the
accepted warning codes from the reviewed plan. The hash checks plan
consistency. A future Monitor adapter must independently verify that
authentication is active and that the session has `full_admin`. It must
bind confirmation and operation lookup to that session.

The local record binds the ID to the invoking UID, action and plan.
Operations report `running`, `succeeded`, `failed`, `partial` or `unknown`.
They include the Proxmox task ID (UPID) when known. Created containers carry
the request ID in their description so a follow-up can identify the
container before issuing a confirmed start. If creation finishes after the
90-second wait and start was requested, status can report that the container
was created and needs a separate start action. After an interrupted call,
use `status` with the same request ID. A pending or ambiguous request keeps
its target reserved. A known terminal task releases its reservation only
after the original controller has left its critical section.

The wizard offers status/recovery for earlier pending requests. `recover`
requires separate confirmation and the request owner's idle controller lock.
A new record known never to have been submitted can be closed immediately.
With a missing UPID or unavailable task status, wait at least five minutes after
its submission deadline. Legacy records with no usable time get a fresh
persisted waiting period. The native check rejects other live dispatchers,
running or uncertain PVE workers, locked targets and conflicting guest identity.
An existing downloaded archive must match the original checksum. An existing
created container is retained and reported for manual review. If a check is
unavailable, the reservation stays in place. No clock alone frees a target,
and neither status, replay nor recovery submits a missed lifecycle phase.
Recovery does not clean leftover volumes; inspect the VMID and storage before
a separately confirmed new request.

The console can invoke the command with `--progress` to receive newline
delimited JSON. Each phase starts with an event such as
`{"schema_version":1,"event":"phase","phase":"create"}`, followed by the
usual reply at the end. Events contain only the phase and are optional.
Invocation without the flag still returns a single JSON object.

The log action uses a zero-based offset and returns `upid`, `phase`,
`lines`, and `next_offset` (null at the end of the current log).
It returns up to 50 printable lines per page and accepts only the
request owner's operation and its recorded task for that phase.
Use the operation status to determine the outcome, even if its
log is empty or unavailable.

Inventory probes already available built-in directory, BTRFS, NFS, CIFS,
CephFS, LVM, LVM-thin, ZFS and RBD storage. It uses read-only storage status
and template listing without activating storage. Official system and TurnKey
templates come from the local Proxmox catalog and its checksum. Local custom
archives require explicit `template.architecture` (`amd64` or `arm64`), matching
the node. Their checksum binds the selected file, not its authenticity; review
the `custom_template` warning. ARM catalog availability and native execution
depend on the installed PVE platform; accepting metadata is not a runtime test.
Unreadable, symlinked or changed archives fail preflight.

LVM-thin and ZFS container subvolumes can have logical limits above physical
free space, with a `storage_overcommit` warning. ZFS container `refquota` is
distinct from the `sparse` flag for VM zvols. Allocation budgets include the
root disk and all new mount volumes on the same storage ID. Zero capacity,
insufficient minimum archive space and unavailable storage still fail; a thin
plan does not guarantee extraction or later writes will fit the physical pool.

## Optional mount points and hardware

`mounts` and `devices` default to empty lists, each limited to 16 and to the
native capabilities advertised by this PVE version. They are part of the same
spec, reviewed plan/hash, create preflight and native start validation.

```json
{
  "mounts": [
    {"type":"volume","storage":"local-lvm","size_gib":8,"path":"/data","backup":true},
    {"type":"bind","source":"/mnt/media","path":"/media","read_only":true}
  ],
  "devices": [
    {"path":"/dev/dri/renderD128","uid":0,"gid":0,"mode":"0660"}
  ]
}
```

Volume mounts allocate new PVE volumes; existing guest volumes cannot be
attached through this schema. Bind sources must already be directories, with
no symlink components or protected host system paths. Targets are absolute,
non-overlapping data paths. Bind mounts default to read-only, are excluded
from CT backups and keep host permissions unchanged. Device/inode and native
volume-owner checks guard against changed sources or another guest's volumes.

Hardware selection lists existing supported character nodes for DRM GPUs,
mapped NVIDIA nodes, Coral/TPU, NPU/accel, USB and USB serial. Native `devN`
support is required; there is no fallback to arbitrary raw LXC configuration.
The GPU helper's SR-IOV VF/active-PF/VFIO exclusions also apply here. Accelerator
nodes without an unambiguous kernel PCI mapping and USB hubs are not offered.
Host drivers must already be configured. This flow never installs drivers,
changes VFIO/initramfs/udev rules, reboots, or installs guest software.

GPU sharing is explicit. Existing CT assignments block duplicate exclusive
USB/TPU/NPU use; VM USB host-port/vendor-product assignments are also checked.
An unresolved VM USB mapping fails closed rather than assuming the device is
free. USB paths can change after reconnection and are rechecked before action.
The final native boundary repeats device policy/assignment checks using the
shared read-only helper. Physical device operation still needs a runtime test.

## Operation journal and upgrades

New state lives in `/usr/local/share/proxmenux/state/plain-lxc`, outside the
replaceable `scripts` and language directories. It is private to the invoking
root process. An ephemeral lock under `/run/proxmenux-plain-lxc` coordinates
mutations, migration and uninstall; it contains no journal or credentials.

For a legacy `/var/lib/proxmenux/plain-lxc` journal, close all wizards and
controllers first. Use the installed command with `--legacy-state` for
`operations`, `status`, `task_log` or confirmed `recover` until no operation
is pending. Then run the installed command with `--migrate-state` instead
of JSON stdin. It atomically exchanges the current journal directory with a
compatibility alias. Existing IDs, actors, results, logs, ownership and permissions
are retained. Old binaries reject that alias instead of making a second DB.
Conflicting stores, active controllers, pending records, unsupported atomic
exchange and cross-filesystem layouts stop migration without copying a DB.

`--rollback-state` atomically moves the current journal back to the legacy
location while idle; it never restores an old snapshot over newer operations.
Uninstall checks pending state before removal, holds the shared runtime lock
exclusively and removes only its verified legacy alias and install-tree state.
It does not delete containers, templates or their volumes. Failed state checks
stop uninstall and must not be reported as successful completion.

## Console navigation

The existing Create VM menu includes plain LXC as visible option 4. Search,
Catalog and direct CLI arguments keep their existing VM routes (`4` for macOS,
`5` for Others); `plain-lxc` is the explicit new console argument.
The wizard suggests a hostname after choosing the template, preserves custom
names and field values on Back, and never prefills a password. Esc cancels the
current collection/edit as before. One complete review precedes a short,
default-No creation confirmation. Progress/results keep their dialog UI.
