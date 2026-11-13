# Native OCI import compatibility

Proxmox's OCI extractor rejects absolute tar member names. Some publisher images
contain ordinary directories and regular files named `/usr/local/bin/...`, even
though their files belong at that same location inside the container.

The common native import entry point prepares a temporary compatible copy for
these cases. It streams layers without extracting them onto the host, removes
the leading slash from supported member names, preserves file bytes and metadata,
and recalculates layer digests, uncompressed diff IDs, config and manifest
references. The resulting complete OCI archive passes the normal integrity
verifier and the native Proxmox extractor. The original publisher archive and
registry identity remain intact; the copy is an import adaptation, not a new
upstream release.

Standalone updates and coordinated updates prepare the copy before stopping
existing applications. The journal binds it to the source and result SHA-256
hashes; they are checked again before creation. The native create wrapper binds the already-prepared source to the active pending journal/VMID/identity and skips its redundant layer-path scan during downtime. Fresh installs and legacy or unrelated callers keep normal preparation. Numeric-user compatibility and native extraction checks still run. Images with canonical paths need
no rewritten copy, and unchanged-image updates retain their early return. Fresh
installations and dedicated stack installers also use the common import wrapper.
The existing numeric-user database adaptation composes with path compatibility.

Only ordinary absolute directory/file names are rewritten. Parent components,
ambiguous aliases, absolute link member names, absolute hard-link targets and unsupported sparse entries
are refused. Symlink targets are preserved for Proxmox to validate.
No native extraction checks are disabled. Images that cannot be prepared are
rejected during update preparation while the current application still runs.

The normal transaction cleanup removes import copies; interrupted operations
retain their journal/recovery material under the existing cleanup policy. The
container's rootfs and backups are self-contained and never depend on the copy.
The helper streams gzip, uncompressed and zstd layers and uses temporary disk
space only when a rewrite is required. It does not download a replacement image.

Tests: `cd oci && python3 -m unittest discover -s tests`.
Focused coverage is in `test_layer_paths.py`, `test_native_import_access.py` and
`test_modify_review_transaction.py` (failure before stop/backup).
