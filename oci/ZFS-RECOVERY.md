# Experimental local ZFS recovery points

Conventional verified `vzdump` archives remain the default. This experiment
replaces only the temporary copy used to undo an image replacement. It does
not replace scheduled Proxmox/PBS backups and is not an offsite or portable
backup: recovery needs the original pool and its transaction directory.

Opt in for a local operation by launching the OCI menu with
`PROXMENUX_OCI_RECOVERY=auto`. The native single-container transaction and stack
commands also accept `--recovery-backend auto`. Use `backup` to force the
existing archive path. Recovery detects its saved format independently of the
current environment, including after a new process starts.

The eligible layout is deliberately narrow:

- Every archived managed volume, including rootfs, is a writable local
  `zfspool` filesystem. All members use the same ZFS pool.
- The pool is ONLINE. Datasets have no existing snapshots, clones, child
  datasets or encryption. Guests have no pending/snapshot sections, unused
  disks, maintenance lock, template flag or replication jobs.
- The operation does not request a retained backup or gzip compression.
- Bind-mounted host data keeps the existing external-data boundary: it is
  neither copied nor reverted. Existing source/identity checks still apply.

An unsupported layout or unavailable eligibility query uses the conventional
archive path. Failure **after creation starts** aborts the operation and uses
its recovery journal; it does not silently proceed without protection.
Conservative existing free-space checks are retained.

## Lifecycle

1. Stop every application member, and verify the carried OCI records.
2. Persist the planned asset identities before writing any ZFS resources.
3. Create one atomic snapshot set for the whole application. Clone and promote
   protected recovery datasets so deleting the old CT cannot delete the point.
4. Continue through the existing native image import, data parking, runtime
   checks and coordinated commit.
5. On failure, clone the protected filesystems to new managed volumes, preserve
   their effective filesystem properties, and use native `pct restore` with a
   small configuration archive and explicit existing volumes. Restore all
   members, including an unchanged database that may have received migrations.
6. Release failed-attempt disks before promoting the validated live volumes
   and removing exactly the owned recovery datasets and snapshots.

Recovery metadata and journals are private. Dataset GUIDs, operation tokens,
installation identity and live volume attachments are checked before cleanup.
Unexpected clones/snapshots block deletion. Interrupted creation, restore and
cleanup remain journaled; restore retries use fresh clone names. No recursive
ZFS destroy or forced removal of dependent volumes is used.

Verification checks metadata, dataset/snapshot GUIDs and ownership; it does
not reread every data block as a full archive does. Scheduled backups and the
health of the source pool remain important.

The private transaction log includes `ZFS recovery:` phase timings. Existing
`phase_seconds` still measures the complete lifecycle. Benchmark both complete
operation time and service downtime; point creation alone is not the update
cost. Small applications can be slower because eligibility checks cost more
than copying their data. This mode therefore remains experimental and opt-in.

## Measured experiment (2026-11-11)

Disposable Nginx/Redis stacks on one Proxmox VE 9.2/ZFS host, identical
resources and data within each pair, real native replacement and HTTP polling
at 250 ms (750 ms request timeout). The baseline already contains selective
replacement, minimal data holders and the operation-scoped native read worker.

| Fixture and measurement | Conventional recovery | ZFS recovery |
|---|---:|---:|
| 4 GiB incompressible payload: complete update | 73.348 s | 54.499 s |
| 4 GiB: backups, verification and guards | 31.797 s | 12.975 s |
| 4 GiB: approximate HTTP downtime | 59.770 s | 41.047 s |
| Small stack: complete replacement lifecycle | 48.105 s | 48.887 s |
| Small stack: approximate HTTP downtime | 41.883 s | 42.399 s |

The large fixture included normal registry metadata queries and a warm verified
candidate archive. After a separate registry delay, the small controlled pair
used already resolved, verified archives and excluded registry metadata queries.
Compare within each pair, not across fixtures. Each value is one diagnostic
sample, not a repeated statistical benchmark or a production Immich claim.
The complete large update was 25.7% shorter and its approximate downtime 31.3%
shorter. The small fixture was effectively unchanged. Protected clone creation
itself took 0.374–0.407 s; the surrounding guards still account for most of the
new recovery-preparation phase. The 4 GiB payload's SHA256 matched before and
after both updates.

Live validation also covered standalone update/rollback, coordinated rollback
after writing into an unchanged Redis database, fresh-process recovery with the
experimental mode disabled, partial clone creation failure, an existing-snapshot
fallback and a retained conventional archive. The quota spelling and inherited
mountpoint handling were corrected after early trials, then retested, including
another update after a restore. These trials did not update production services.

### Conservative preflight and retained points

Eligibility falls back to the ordinary backup path on any read-only backend error. Before snapshots, the planner requires enough available ZFS space for a complete rewrite of the currently referenced data (the larger of physical and logical referenced bytes), plus 10% and 1 GiB per dataset pool. Space and absence of external snapshots are checked again immediately before protection. This is a preflight reserve, not a guarantee against unlimited writes or unrelated pool consumers.

All recovery clones exercise the restore property set before any promotion. Recovery datasets use `proxmenux-oci-recovery-…`, outside Proxmox's `subvol-<VMID>-…` disk namespace, and disable automatic snapshots on the clone. Metadata from the earlier experimental naming scheme remains readable. Sources are checked again for external snapshots before promotion.

A blocked cleanup warns and retains its metadata, while other operation directories are still cleaned. Selecting an application shows any unreleased points; these can continue consuming space until the underlying dependency is resolved. Removing an application moves blocked cleanup journals to `instances/retained-zfs-recovery/<VMID>/…` rather than deleting their only description. No recursive ZFS destroy is introduced.
