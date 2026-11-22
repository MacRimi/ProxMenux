# Automatic catalog refresh

Opening OCI Manager displays its local catalog immediately and starts a separate
worker. The menu shows the available total, additions since the last displayed
catalog, and changed recipes. Returning from a search or installation does not
start another download. A running wizard keeps the catalog it started with.
The menu also offers **Refresh catalog** to check again manually or retry after
a connection failure. Selecting it during a refresh does not start a second worker.
Manual refresh bypasses the conditional check and verifies the complete manifest,
allowing it to repair damaged cached files even when the upstream revision has not
changed. A repaired snapshot gets a separate immutable directory so existing
readers retain their original snapshot until they return to the menu. Each
Catalog reader holds an OS file-lock lease. Every worker run, including unchanged
checks and failed downloads, prunes snapshots that are neither a channel's active
snapshot nor leased by an open reader. Reader exit or a crash releases its lease
automatically. Snapshot selection, publication and pruning share a short local
lock; opening a menu never waits for the worker's network lock.

The worker checks the latest commit affecting `oci/catalog` in the official
MacRimi/ProxMenux repository. GitHub's ETag avoids repeated transfers. When the
revision changes, its immutable Git tree supplies the file manifest. Only changed
JSON files are downloaded from that commit; Git blob hashes and sizes are checked.
The complete snapshot, including overlays, categories, volume policy and
verification records, is validated before publishing its pointer atomically.
Runtime Python or shell files are never downloaded by catalog refresh.

State and snapshots live in `/usr/local/share/proxmenux/oci/catalog-cache`, outside
the engine replaced by the normal ProxMenux updater. The bundled catalog remains
the fallback. A network failure, incomplete manifest, invalid recipe, different
template schema or unsupported catalog engine API leaves the previous catalog
active. The private `CHANNEL-result.json` records the diagnostic.
The revision, snapshot and ETag are committed together in one atomic pointer;
failure to publish it cannot acknowledge an update that was not applied.

The channel follows `install_branch`, an active beta program or `beta_version.txt`;
otherwise it is `main`. A host can explicitly select `main` or `develop` with
`/usr/local/share/proxmenux/oci/catalog-source.json`:

```json
{"channel": "develop", "local_apps": ["my-local-preview"]}
```

`local_apps` optionally keeps explicitly named bundled preview recipes available
when they are absent upstream. These are local overrides, not automatic retention
of withdrawn upstream applications. An upstream recipe with the same ID wins.

The first visit uses the bundled/current catalog as its baseline. Additions are
compared by application ID, not net growth, and only visible installable entries
are counted, using the same rule as the existing menu. A downloaded catalog is
acknowledged only after the menu displays it. Exiting during a download therefore
preserves its news for the next visit. The new-app count remains visible throughout
the current visit and becomes zero on the next visit after acknowledgement.

Downloaded recipes are also checked against the top-level `installer_profile`
keys used by the engine's bundled apps, curated recipes and overlays. A new app
using an unknown key is silently excluded; an existing app retains its previous
compatible, fully composed recipe and its matching settings. Hidden entries do
not contribute to the available/new counters, and retaining an old recipe does
not count it as an update. When a ProxMenux update adds support for that key, the
next background check re-evaluates the catalog even at the same remote revision.
This is a conservative key-presence gate, not validation of new values or nested
options of an already known key. Changes in meaning still require `engine_api`.

Catalog maintainers must increase `catalog/compatibility.json`'s `engine_api` when
recipes require incompatible runtime capabilities. The consumer currently
supports API 1. Changes to the template schema also require a ProxMenux engine
update. Catalog delivery alone neither changes installed CTs nor applies a new
recipe to an existing deployment; the established management actions remain in
charge of those changes.
