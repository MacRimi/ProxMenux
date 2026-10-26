# PR407 repository API evidence

## Authentic capture (unchanged)

`pr407-macrimi-pve9.2-no-subscription.json` is the complete maintainer-provided
`pvesh get /nodes/localhost/apt/repositories --output-format json` attachment.

- Provider: MacRimi; reported host version: PVE 9.2.20.
- Context: <https://github.com/MacRimi/ProxMenux/pull/407#issuecomment-5918280377>
- Original attachment: <https://github.com/user-attachments/files/32873450/pvesh-apt-repositories-pve9.2-no-subscription.json>
- Size: 8403 bytes.
- SHA-256: `dfbc0560e280511ce5cef55b8f059095c57df74e062d149065f2363a80b3847f`.

This is **already a no-subscription configuration**, not a fresh-ISO Enterprise
before capture and not a captured before/after pair. It contains numeric
`Enabled: 0/1`, disabled Enterprise PVE/Ceph stanzas with
`Options: [{"Key": "Enabled", "Values": ["false"]}, ...]`, and an enabled public
PVE stanza whose Enabled option is `true`. Signed-By options remain in the file.
The authentic-capture test verifies both plan/apply preserve paths without any
subscription lookup or API write. The attachment is stored byte-for-byte; tests
parse separate in-memory copies, never rewrite this evidence.

## Generated scenarios (not captured host state)

`RepositoryPolicyTest.simulated_enterprise_capture()` in
`tests/test_repository_preservation.py` transforms an in-memory copy: removes the
public PVE file, enables Enterprise PVE/Ceph, removes their redundant Enabled
options, and labels the global digest `simulated-enterprise-before`. Remaining
capture metadata/file digests are only fixture input, not evidence of that
invented configuration. Tests optionally add a consistent Enabled=true option.

The fake API disables one targeted entry at a time, simulates numeric Enabled and
Enabled-option insertion/update on readback, changes fixture digests, and adds a
synthetic public PVE entry for the standard handle. This verifies policy behavior
and retention of unrelated Signed-By options; it is **not** an observed live API
transition or an authentic Enterprise-before capture. Additional edits simulate
concurrent URI/suite/component/option/enabled changes and malformed/conflicting
readback. They must stop before a second mutation and report partial/unknown
state after the attempted write.

The PVE 8 `.list` cases and other hand-built inventories are explicitly synthetic.
No real Proxmox API command, package operation, or host source-file change is
executed by these tests. Fresh-ISO validation is still required separately.

## Primary implementation references

- [Proxmox subscription CLI/status parsing](https://github.com/proxmox/pve-manager/blob/master/PVE/CLI/pvesubscription.pm)
- [Proxmox parsed APT repository API](https://github.com/proxmox/pve-manager/blob/master/PVE/API2/APT.pm)
- [Proxmox standard repository definitions](https://github.com/proxmox/proxmox-rs/blob/master/proxmox-apt/src/repositories/standard.rs)
- [Proxmox package repositories](https://pve.proxmox.com/wiki/Package_Repositories)

The policy normalizes bool and integer 0/1 only, retaining the normalized Enabled
field as authoritative. A single well-formed Enabled option is redundant only
when consistent with that field. Other options and all unrelated repository
fields remain part of semantic inventory comparison; per-file digests alone are
excluded. Missing/empty Options and omitted/empty Components are semantically
equivalent. Unknown or conflicting Enabled serialization fails closed.
