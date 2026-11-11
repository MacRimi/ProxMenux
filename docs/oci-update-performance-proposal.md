# Proposal: faster OCI application updates

Status: design discussion. This document proposes improvements; it does not
implement them or claim measured speedups.

Updating a multi-container application such as Immich can take a long time.
The goal is to reduce both total update time and service downtime while keeping
data, configuration, device access and coordinated rollback intact.

## Current behavior

The coordinated updater already resolves, downloads and verifies candidates
before stopping services. Preparation and replacement are sequential, and every
member is backed up and recreated, including members whose image is unchanged.
Standalone updates already have an unchanged-image shortcut.

The resolver can reuse complete verified archives. It currently performs full
archive verification before comparing the cached image with the candidate.
Backup verification also occurs at multiple points in the coordinated path.
Whether these dominate a particular update needs measurement.

Relevant code:

- [Stack coordination](../oci/remote/oci_stack_transaction.py)
- [Native stack adapter](../oci/remote/oci_stack_native.py)
- [Image resolution and archive reuse](../oci/remote/oci_update_current.py)
- [Member transactions and backup verification](../oci/remote/oci_instance_transaction.py)

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

Compare the existing and proposed paths on equivalent disposable stacks:

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

Report total duration, downtime, downloaded bytes, verification time and members
recreated. There is no measured speedup or implementation validation in this
documentation-only proposal. The suggested first implementation is instrumentation
plus unchanged-image and selective-replacement paths; cache and snapshot changes
can follow separately after reviewing the measurements and recovery design.
