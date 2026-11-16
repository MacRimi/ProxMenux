# Plain LXC command

The installed entry point is `/usr/bin/python3 -I -B /usr/local/share/proxmenux/scripts/lxc/plain_lxc.py`.
It runs as root on the local Proxmox VE node. The console and any future
adapter send one UTF-8 JSON object on stdin. Every request has
`schema_version` (1 or 2) and an `action`. The console uses version 2;
the JSON reply/progress envelope remains version 1 for both request versions,
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
  "schema_version": 2,
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

The console uses schema version 2 for context, plan and create. `mounts`
and `hardware` default to empty lists, each bounded by native PVE capacity.
Choose a profile and selection_id returned by context.hardware, for example:

```json
{"schema_version":2,"action":"plan","spec":{
  "node":"pve","vmid":240,"hostname":"debian-13",
  "template":{"volume_id":"local:vztmpl/debian-13-standard_amd64.tar.zst"},
  "access":{"mode":"ssh_key","ssh_public_keys":["<public key>"]},
  "rootfs":{"storage":"local-lvm"},"network":null,
  "hardware":[{"profile":"intel-drm","selection_id":"<ID from context.hardware>"}]
}}
```

The profiles are intel-drm, amd-drm, amd-rocm, nvidia-runtime, coral, npu and
usb. The engine resolves them to exact native nodes, UID 0, each host node's
GID and mode 0660. NVIDIA preserves the host device permissions of its
existing OCI runtime profile. The wizard never asks for numeric permissions.
A host GID is a number, not a promise that the system template gives its group
the same name or that an application user belongs to it.

Intel/AMD render nodes are identified by sysfs vendor and PCI identity. AMD
compute adds /dev/kfd only with a matching KFD render-minor topology. It does
not install ROCm or import catalog application disk-size limits or overrides.
USB uses the shared named inventory, tty for serial peripherals, and records
vendor/product/serial/port/sysfs identity. Reconnection can change paths:
a changed device requires a fresh reviewed plan. GPU sharing and exclusive
USB/TPU/NPU ownership guards also cover existing LXC/QEMU assignments.

NVIDIA requires an already working driver and Container Toolkit. The entire
existing unprivileged OCI runtime profile covers all host NVIDIA GPUs, native
devN nodes and the same content-addressed mount hook. Toolkit resolves driver
libraries at each start. Only the exact declared hook/environment is allowed;
arbitrary raw LXC settings remain rejected. The hook remains an experimental
runtime boundary that requires physical-host verification. It does not imply
GPU workload validation on hardware absent from the test host.

Hardware preparation is separate from optional system preparation and is
journaled even when prepare_system=false and start_after_create=false.
Results distinguish hardware_prepared from system_prepared. Failed or unknown
preparation never starts or replays a missed operation. Persistent NVIDIA
runtime helpers are outside the replaceable install tree; uninstall must not
break an existing container's start dependency.

Version 1 without hardware remains supported. New V1 devices requests must
use a fresh V2 hardware plan; already admitted V1 requests remain observable
and recoverable with their original request ID. V2 rejects a simultaneous
devices field, duplicate selections and overlapping device profiles.

Mount volumes and read-only host data directories retain the existing native
checks, storage budgets, protected-path exclusions and identity rechecks.
Drivers, host permissions, id maps, VFIO, initramfs and security policy are
never changed by hardware discovery or planning.

Known OCI cache archive names are excluded from the system-template choices
and direct CLI plans, using the same predicate as OCI cache management.
They remain occupied volumes, and no cached files are moved or deleted.
Official, TurnKey and custom system templates retain their existing checks.

## Operation journal and upgrades

New state lives in `/usr/local/share/proxmenux/state/plain-lxc`, outside the
replaceable `scripts` and language directories. It is private to the invoking
root process. An ephemeral lock under `/run/proxmenux-plain-lxc` coordinates
mutations and uninstall; it contains no journal or credentials.

The earlier draft's legacy-state migration was never released and has been
removed. No old directory or alias is deleted automatically. Uninstall checks
the installed journal before removal and again while holding the runtime lock
exclusively through removal. Active controllers, pending or unreadable state
stop uninstall; errors in the progress pipeline must propagate. Containers,
templates and their volumes are never deleted by this check.

## Console navigation

The existing Create VM menu includes plain LXC as visible option 4. Search,
Catalog and direct CLI arguments keep their existing VM routes (`4` for macOS,
`5` for Others); `plain-lxc` is the explicit new console argument.
The wizard suggests a hostname after choosing the template, preserves custom
names and field values on Back, and never prefills a password. Esc cancels the
current collection/edit as before. One complete review precedes a short,
default-No creation confirmation. Progress/results keep their dialog UI.
