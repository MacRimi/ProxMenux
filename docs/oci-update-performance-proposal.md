# Proposal: faster OCI application updates

Status: initial implementation plus a roadmap for later work. Following the
[maintainer's measurements and priorities](https://github.com/MacRimi/ProxMenux/pull/651#issuecomment-6801389781),
the initial changes implement minimal data holders, selective stack image
replacement, an unchanged-stack shortcut, reduced repeated Proxmox queries and
active phase timings. A further pass keeps a private native PVE read worker
for one operation, avoiding repeated Perl module startup while refreshing
pmxcfs state for every read. Unattended batches are implemented separately in
[PR #653](https://github.com/MacRimi/ProxMenux/pull/653). Layer caching,
concurrent preparation and snapshot recovery remain follow-up design work.

Updating either a single-image OCI application or a multi-container application
such as Immich can take a long time. Both are explicitly in scope.
The goal is to reduce both total update time and service downtime while keeping
data, configuration, device access and coordinated rollback intact.

## Baseline behavior before these changes

The coordinated updater already resolves, downloads and verifies candidates
before stopping services. Preparation and replacement are sequential, and every
member is backed up and recreated, including members whose image is unchanged.
Standalone updates already have an unchanged-image shortcut and native Modify
paths for supported resource/settings changes. These existing fast paths must
be preserved, not presented as new features.

The resolver can reuse complete verified archives. It currently performs full
archive verification before comparing the cached image with the candidate.
Image and backup verification occurs at multiple points in the lifecycle.
Review the single-container and coordinated paths separately.
Whether these dominate a particular update needs measurement.

Relevant code:

- [Stack coordination](../oci/remote/oci_stack_transaction.py)
- [Native stack adapter](../oci/remote/oci_stack_native.py)
- [Image resolution and archive reuse](../oci/remote/oci_update_current.py)
- [Member transactions and backup verification](../oci/remote/oci_instance_transaction.py)

## Initial implementation

- Standalone and coordinated transactions park volumes in a never-started,
  networkless holder built from a 10 KiB directory-only tar and a 1 GiB rootfs,
  rather than extracting the full application image into the holder.
- Coordinated Update resolves every image first. When none changed, it does not
  stop, back up or recreate guests. Otherwise it recreates changed members and
  replays completion jobs as needed; explicit Recreate still rebuilds all members.
- Every member remains covered by a coherent stopped backup. Recovery restores
  the data of unchanged members too: an unchanged LXC configuration is not proof
  that a database has not received migration writes.
- Single-member stop, backup and start checks read that member's configuration
  rather than every member's. Whole-stack checks remain at transaction boundaries
  and before replacement/recovery. Read-only preflight reuses its validated
  configuration snapshot; destructive operations still obtain fresh evidence.
- Private journals record active phase durations. Recovery in another process
  does not count the interruption as active execution time.

The general optimization ideas below remain useful for both installation types;
only the initial subset above is implemented here. No production Immich speedup
is claimed. Validation details and controlled measurements are in the PR.

## Scope: single-image and multi-image applications

Common optimizations belong in shared resolver and member-transaction code so
both installation types benefit. A single-image app can contain its own database
or run migrations too; it still needs a coherent data recovery point.

| Idea | Single-image OCI | Multi-image OCI |
| --- | --- | --- |
| Phase timings and downtime | Measure its complete update. | Measure each member and the coordinated operation. |
| No-op when the image is unchanged | Preserve and verify the existing shortcut. | Add a whole-stack shortcut when every image is unchanged. |
| Replace only changed images | Keep the existing image when unchanged; preserve native Modify fast paths. | Recreate only changed members while retaining coherent recovery coverage. |
| Metadata-first cache selection | Reject stale archives cheaply before full verification. | Same optimization for each member. |
| Shared layer reuse | Reuse layers between versions of this image. | Also reuse common layers across members and applications. |
| Bounded preparation concurrency | Audit existing Skopeo layer parallelism and independent verification work; do not assume serial layer downloads. | Additionally overlap preparation of independent images. |
| Avoid redundant full checks | Evaluate repeated image/backup checks within its transaction. | Also evaluate checks repeated by the coordinator and member transactions. |
| Prepare before downtime | Already downloads/verifies before stopping; audit remaining safe preparation. | Already downloads/verifies before stopping; audit remaining safe preparation. |
| Snapshot recovery where supported | Quiesce the application and cover its rootfs and required managed data volumes. | Coordinate a consistent recovery point across all affected members. |
| Volumes and readiness | Avoid unnecessary copies, permission walks and fixed waits; retain migration/readiness checks. | Apply the same principles with dependency ordering. |

## Suggested priorities

| Priority | Proposal | Expected benefit and limits |
| --- | --- | --- |
| 1 | Record elapsed time per phase, total time and downtime. | Establish a baseline for registry queries, downloads, verification, backups, replacement and readiness. Show where time is spent before promising a percentage. |
| 1 | Add an unchanged-image shortcut to coordinated updates. | If every member is unchanged, avoid stopping, rebuilding or restarting guests. Keep explicit Recreate behavior and requests to retain a backup meaningful. |
| 1 | Replace only members whose image changed. | Avoid rebuilding the database, cache or ML container when only the application image changes. Preserve whole-stack recovery and dependency ordering. |
| 2 | Compare cached image metadata before verifying all layers. | Reject an obsolete archive without decompressing its entire contents. Fully verify any matching archive before using it. |
| 2 | Prepare independent image downloads with bounded concurrency. | Overlap network transfers and verification before stopping services. Keep guest creation, volume moves, publication and dependency startup coordinated. Budget aggregate disk space and join all workers on failure. |
| 2 | Investigate a shared, digest-addressed layer cache. | Reuse unchanged layers across versions instead of downloading complete archives. Verify support in the actual Skopeo destination workflow; complete-archive reuse alone does not provide this. Define integrity checks, locking, space limits and safe pruning. |
| 2 | Avoid redundant verification within one uninterrupted operation. | Reuse a successful integrity check only while the same file remains unchanged. A modified/replaced file, an interrupted operation or a new process must trigger full verification again. |
| 3 | Evaluate coordinated storage snapshots for rollback. | Potentially reduce full-backup time on supported storage. Quiesce the whole application, cover all required managed volumes, and retain verified archive backups as a fallback. Snapshots are not independent backups. |
| 3 | Audit volume preparation and readiness waits. | Keep existing data volumes attached through the established lifecycle; avoid unnecessary data copies, recursive ownership changes and fixed delays. Continue waiting for actual database migrations and service readiness. |

## Recovery constraints

An unchanged database image does **not** mean its data stays unchanged: the new
application may run migrations. Selective image replacement must therefore
retain a coherent recovery point for every affected service and its data.
Reducing image work must not silently reduce recovery coverage.

Host directories and NAS datasets are outside normal container-backup coverage.
Any snapshot-based design must state that boundary and require the existing
external-data acknowledgement where applicable. Preserve networking, devices,
credentials, resource settings and original running/stopped states.

## Validation before implementation is accepted

Compare the existing and proposed paths on equivalent disposable installations:

- Single-image applications: unchanged and changed images, small and large
  archives, persistent managed volumes, host binds, an embedded database, and
  native Modify changes that must not download or recreate the image.
- Multi-image applications:

- All images unchanged; only the frontend changed; only a dependency changed;
  and all images changed. Include an Immich-like application/ML/database/cache
  stack and a generic multi-service Compose stack.
- Cold and warm caches, corrupted archives, unavailable registries and low disk
  space. Parallel work must finish or be cancelled before recovery proceeds.
- Healthy updates, failed readiness, database migrations, interrupted execution
  and recovery in a fresh process. Check data and settings after rollback.
- Supported snapshot storage, unsupported storage, host binds and external NAS
  data. Confirm backup retention and cleanup behavior.
- Run `cd oci && python3 -m unittest discover -s tests`, applicable offline/i18n
  checks, and real installation/update checks before publishing runtime changes.

Report total duration, downtime, downloaded bytes, verification time and guests
recreated separately for single-image and multi-image applications. Controlled test results must identify their workload, cache state and limits;
they must not be extrapolated into a production Immich speedup. Cache, snapshot
and unattended batch changes should follow separately after reviewing the
initial measurements and recovery design.

## Operation-scoped native PVE reads

Updates use a private Perl child to call the same native read APIs as `pct`
and `pvesh`. It starts lazily and closes with the operation; there is no daemon,
network listener or saved configuration cache. Only the exact existing config,
status, VM inventory and HA-inventory commands are eligible. All writes and
other command forms still use the normal CLI.

Every request calls `PVE::Cluster::cfs_update(1)` before the native API, so
configuration edits, guest creation/deletion, migration and runtime changes
remain visible. Identity/configuration/device checks before destructive steps
are retained. The helper uses Proxmox's own pending-config semantics and
`pct config` rendering, including description escaping and repeated low-level
LXC options; it does not parse native config files itself.

Responses travel only over private inherited pipes. No configuration values
are logged. Reports identify request counts, elapsed reader time and whether
the operation fell back to the CLI. A failed, missing, malformed or stalled
worker is closed and disabled for that operation; subsequent reads run the
ordinary CLI afresh. Previous responses are never reused.

`PROXMENUX_OCI_NATIVE_READS=0` disables this optimization for diagnostics or a
matched benchmark. Unsupported hosts retain the ordinary CLI automatically.
Native API imports are paid once per operation; this change applies to both
standalone and coordinated updates, including automatic standalone recovery.

### Measured native-read follow-up

A paired test compares the first optimized implementation (`6c975ee2`) with the
operation-scoped reader. Both use equivalent disposable Nginx/Redis stacks,
identical resources/data and the same verified warm Nginx 1.28 → 1.29 candidate.

| Measurement | First implementation | Native reads | Change |
| --- | ---: | ---: | ---: |
| Total update | 105.519 s | 55.152 s | 47.7% less |
| Approximate HTTP downtime | 62.030 s | 42.051 s | 32.2% less |
| Fresh read checks | 113 | 113 | All retained |
| Reads through external CLI processes | 113 | 24 | 89 handled by native worker |

The worker handled 53 config, 17 status, 17 VM-inventory and two HA-inventory
reads in 1.152 s, including startup. No fallback occurred during the measured
update. Host process startup is eliminated for these calls, not the underlying
checks. This is one controlled warm-cache sample per variant, not an Immich
benchmark or a prediction for every host. HTTP polling uses 250 ms intervals
and a 750 ms timeout; downtime is approximate.
