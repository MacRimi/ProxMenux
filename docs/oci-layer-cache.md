# OCI update layer cache

The optional layer cache lets standalone and coordinated OCI updates reuse
unchanged, SHA-256-addressed blobs instead of downloading those blobs again.
New installations keep their existing image-download path. The updater still
exports a complete OCI archive and runs its normal full integrity check before
using it. Running or restored containers never depend on this cache.

## Enable

For one menu invocation:

```sh
PROXMENUX_OCI_LAYER_CACHE=1 menu
```

The default remains the existing complete-archive transfer. Standalone Update
retains its unchanged-image shortcut, including its return before backup
retention checks. Native Modify fast paths and the existing coordinated-update
lifecycle are unchanged.

The cache is `.proxmenux-oci-layer-cache` beside the template-store image
archives. `PROXMENUX_OCI_LAYER_CACHE_ROOT` can select another private directory.
It must be owned by the updater's user, have mode 0700, and support file locks.

`PROXMENUX_OCI_LAYER_CACHE_BYTES` limits retained blobs; the default is 2 GiB.
Least-recently-used blobs and abandoned temporary layouts are pruned after a
pull, including failed pulls. The exported archive and transient working space
are additional to this retention limit. The preflight budgets both blobs and
the exported archive, checking both filesystems when the cache is elsewhere.

## Integrity and credentials

- Existing blobs are hashed before Skopeo can reuse them. Damaged entries are
  discarded; symlinks and unrecognized cache directories are rejected.
- Installed archives can seed only the candidate's required layer digests.
  Seeded bytes are hashed before atomic publication.
- Skopeo writes an OCI layout using `--dest-shared-blob-dir`. The exported tar
  includes its manifest, config and all referenced layers, with native-import
  readable ownership and permissions. Normal full archive verification stays
  in place; no verification proofs are reused or persisted.
- Shared/exclusive locks protect readers, publication and pruning. Layer reuse itself does not
  add parallel preparation, skip archive verification or change recovery.
- An explicit `REGISTRY_AUTH_FILE` is preserved. Otherwise the cache reader
  discovers `/etc/pve/priv/proxmenux/registry-auth.json` at pull time, including a
  login saved after module import. No credentials are copied into the cache.
- Resolution, pulling and verification remain before services stop. Cache,
  registry or disk-space failures follow the existing preparation-error path.

## Measurement

The initial controlled experiment updated two disposable, native ProxMenux
containers with managed data volumes. Lab images used an official cached
AdGuard filesystem, a shared 64 MiB layer and a changed 1 MiB layer; these were
not newly published AdGuard versions. A loopback registry imposed a shared
16 MiB/s limit and 100 ms request latency. The shared cache started empty;
installed V1 archives were allowed seeds, and complete V2 archives were absent.

| Controlled measurement | Before | Layer cache only |
| --- | ---: | ---: |
| Full update | 101.794 s | 89.455 s |
| Registry response bytes | 196,053,484 | 1,080,542 |
| Preparation phase | 17.751 s | 4.525 s |

That is **12.339 s (12.1%) less total time in this experiment**, not a universal
speedup. The reference included earlier update work at commit `8b96aa14`. This PR is
stacked on #656 and its parents so the existing coordinated-recovery fix stays
in its base: matching container configurations do not prove that migration
writes left data unchanged. The new feature here is layer reuse only. Other
experimental optimizations and their combined measurement are out of scope.
The PR records the additional isolated-branch measurements separately.

## Tests

```sh
cd oci
python3 -m unittest discover -s tests
```

The focused tests are `oci/tests/test_layer_cache.py`. They cover corruption,
seeding, self-contained exports, native-readable tar members, pruning,
ownership/symlinks, initialization races, credentials, space budgets, failed
pull cleanup and resolver integration. The offline no-op regression exercises
both enabled and disabled cache paths without allowing backup or apply.
