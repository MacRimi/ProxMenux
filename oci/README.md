# ProxMenux OCI laboratory

Prototype that converts official image documentation and discovered Docker
Compose definitions into one ProxMenux JSON template per distribution or
deployment profile, then optionally installs reviewed images as native Proxmox
VE OCI LXC containers.

This repository is a laboratory. Generated templates are not considered
compatible merely because conversion succeeded.

## Design

- `catalog/index.json` is the lightweight application listing.
- `catalog/apps/<app>.json` is the canonical template for one image.
- `schemas/oci-template.schema.json` validates generated templates.
- `container_contract` preserves the official Compose contract and source text.
- `catalog_ui` contains neutral store metadata and attributes each image to its
  actual image repository or publisher.
- `first_run` records detected web endpoints, documented default credentials,
  and supported methods for recovering credentials generated at runtime.
- `proxmox` contains only native OCI/LXC translation and documented adaptations.
- A multi-image application remains one catalog entry and one user-facing
  installation. Its `compose_stack` creates one native OCI LXC per service,
  allocates a private network automatically and orchestrates dependencies.
- Discovery catalogs are never recorded as image authors or repositories in
  public templates.
- Imported store text keeps only `en_US` and `es_ES`; when Spanish is missing,
  `es_ES` falls back to English instead of retaining unused source locales.
- Distributions and deployment profiles remain separate entries. For example,
  `nextcloud` is the LinuxServer image, `nextcloud-official` is the official
  single-image deployment and `nextcloud-stack` is the laboratory-derived
  Nextcloud, PostgreSQL and Redis profile. The name `nextcloud-aio` is reserved
  for the distinct upstream All-in-One project.
- Hardware choices share one application image: LinuxServer `jellyfin` offers
  CPU, VA-API, AMD/OpenCL, Intel/OpenCL and NVIDIA in its installer profile.
  OpenCL choices use official LinuxServer mods, not separate image variants.
  See [Jellyfin GPU laboratory](docs/jellyfin-gpu-lab.md) for tested capabilities,
  native OCI device permissions and the distinction between VA-API, OpenCL
  and Vulkan tone mapping.
- Curated laboratory profiles can replace a duplicate discovery identifier.
  `jdownloader` uses the maintained JDownloader 2 image from jlesage and
  replaces the less clear discovered name `jdownloader2`; these are not two
  different generations of JDownloader.
- The curated `frigate` profile replaces the generic discovered deployment and
  preserves the AMD VA-API and OpenVINO CPU choices. The installer keeps the
  official rolling `stable` image intact; package substitutions require a
  separate validation on stable hardware and are not enabled automatically.
- The curated `paperless-ngx` profile translates the official PostgreSQL
  Compose into three native LXCs: Paperless-ngx, PostgreSQL and Valkey. Private
  state uses backed-up Proxmox volumes, while `consume` and `export` can use
  either managed volumes or host directories shared with scanners and other
  applications.
- The curated `rclone` profile uses a two-phase workflow. Installation starts
  the official authenticated WebUI so the user can create and authorize a
  private remote. The separate `rclone-mount` action then validates that remote,
  enables the official FUSE mount and publishes distinct read/write and
  recursively read-only paths for other native LXCs.

## Catalog maintenance

The catalog is generated rather than written by hand. `proxmenux-oci.sh` is the
tool that produces and inspects it, and it is what a contributor adding an
application runs:

```bash
./proxmenux-oci.sh sync
./proxmenux-oci.sh list --filter sonarr
./proxmenux-oci.sh generate sonarr
./proxmenux-oci.sh show sonarr
GITHUB_TOKEN=github_pat_xxx ./proxmenux-oci.sh generate-all
```

`generate` writes one application's template from its published recipe; `show`
prints what the installation would create, which is the fastest way to see
whether a translation came out right before installing anything.

On Debian and Proxmox the launcher reuses the distribution packages
`python3-yaml` and `python3-jsonschema` when they are present, so nothing is
installed into the system Python. Where they are absent, install them with APT
before generating the catalog.

`GITHUB_TOKEN` is optional and only raises the public API rate limit, which the
full `generate-all` pass reaches. Never commit a token; `.env` files are
ignored.

## Safety boundary

Automatic installation is allowed only when every Compose behavior has a
reviewed and tested native Proxmox translation. Multi-image applications are
modeled as one installation; generic stacks remain blocked until their native
multi-LXC orchestrator is implemented and validated, while curated Immich,
Nextcloud and Paperless-ngx stacks have dedicated orchestrators. Privileged
mode and relaxed AppArmor/seccomp profiles require an explicit high-risk
confirmation. Security requirements are classified by capability instead of
assuming that every Compose `privileged: true` is an image requirement:

- `requires_privileged_lxc` is reserved for a reviewed profile whose native
  LXC adaptation has proved that broad privilege is necessary.
- `optional_privileged_lxc` records an upstream compatibility request. The
  installer keeps the LXC unprivileged by default and offers the broader mode
  only after explicit confirmation.
- GPU, USB and serial hardware are passed as individual Proxmox devices and do
  not imply a privileged LXC.
- Required Compose AppArmor/seccomp relaxations need explicit confirmation.
  Relaxations marked `#optional` remain disabled by default and are offered as
  individual compatibility choices instead of being labeled as mandatory.
- `pid: host` is tracked separately as host PID namespace access. It remains
  blocked until a safe native LXC translation is validated; it must never be
  mislabeled as ordinary GPU access or silently promoted to privileged mode.

Before creating an LXC, the tool prints a redacted deployment plan and requires
the exact confirmation `INSTALAR`. Remote credentials are handled by normal SSH;
they are never placed in a template or command argument.

Image downloads run in a pseudo-terminal when `script` is available, allowing
Skopeo layer progress to remain visible. The final result lists the detected IP,
one complete URL per documented web endpoint, and any public default login from
the upstream LinuxServer `Application Setup` section. Non-web service ports are
not presented as browser URLs. Public default passwords should be changed after
the first login.

Some images do not publish a static password. For example, qBittorrent prints a
temporary password for `admin` during startup. When this behavior is explicitly
documented upstream, the installer enables a short-lived native LXC console log
for the first boot, extracts the password, removes the log and its temporary
configuration, and prints the credential in the terminal. The generated secret
is never written back to the reusable catalog JSON or to Proxmox metadata.

When run as root directly on a Proxmox node, destination `auto` selects local
execution and does not open an SSH connection back to the same node. Outside
Proxmox, specify `root@<node-address>` using `--host` or the interactive prompt;
the installer never assumes a laboratory address.

## Native Proxmox behavior

Proxmox VE 9 imports OCI `Entrypoint`, `Cmd`, `Env`, `User`, `WorkingDir` and
`StopSignal` when `pct create` extracts the OCI archive. The installer preserves
that behavior and only overlays values explicitly present in Compose.

Proxmox VE 9.2 cannot extract the tested OCI archive directly as a privileged
LXC. When a reviewed profile explicitly requires privileges, the installer
imports it with the standard unprivileged idmap, converts ownership before the
first start while preserving extended attributes, and only then switches the
native LXC configuration to privileged mode. This conversion is never applied
without the user's high-risk confirmation.

Compose `stop_grace_period` is recorded as the timeout for ProxMenux-managed
`pct shutdown` operations. It is not mapped to Proxmox `startup.down`, because
that field controls sequencing between guests rather than the CT stop timeout.

Persistent paths can be installed as:

- Proxmox-managed `mpN` volumes with the image's original container path and
  `backup=1` by default.
- Existing host bind mounts for data intentionally shared with other LXCs.
- Omitted mounts only when LinuxServer marks them optional.

When a host bind is selected, the installer proposes
`/mnt/oci-shared/<application>/<volume>`. Missing data directories are created
automatically with ownership mapped for the unprivileged LXC; existing
directories are never re-owned. System files and runtime sockets are excluded
from automatic creation.

Hardware devices keep their host path and obtain their numeric GID directly
from the selected host device; ProxMenux does not assume fixed `video` or
`render` group IDs. NVIDIA profiles additionally require a working host driver
and NVIDIA Container Toolkit. At installation time, `nvidia-container-cli`
supplies the current device, binary, firmware and driver-library inventory;
ProxMenux translates it to native Proxmox `devN` entries and read-only LXC file
mounts, including the compatibility links expected by the image. No driver
version or library list is hardcoded in the template.

Compose `network_mode: host` means the network namespace of the dedicated LXC,
not the Proxmox host network. `bridge` and `default` use the same native LXC
model because no Docker NAT layer exists. Recognized `cap_add` values are
checked against the LXC capability model instead of using `lxc.cap.keep`, which
would accidentally remove other capabilities. WireGuard images that request
`SYS_MODULE` preload and verify the `wireguard` kernel module on the Proxmox
host while keeping the LXC unprivileged.

Namespaced IPv4/IPv6 Compose sysctls are written to an LXC include profile in
`/etc/pve/lxc/<VMID>.proxmenux-sysctls`; this is required because Proxmox 9.2
does not accept arbitrary network sysctl keys directly in the managed CT
configuration. The profile is stored on the Proxmox cluster filesystem and is
removed on a failed installation. Cross-host backup/restore validation remains
pending, like the versioned NVIDIA host-driver mounts.

`seccomp:unconfined` uses a valid empty LXC denylist profile, never `/dev/null`.
`apparmor:unconfined` is applied with its native LXC directive, and
`no-new-privileges` maps to `lxc.no_new_privs`. Docker's `label:disable` and
logging drivers remain source metadata because the native LXC runtime has no
Docker SELinux label or Docker log object. Compose supplementary groups are
resolved from the image's `/etc/group` and applied through `lxc.init.groups`.

The current laboratory implementation records versioned NVIDIA driver paths in
the LXC configuration. After updating the NVIDIA host driver, those mounts must
be regenerated before affected LXCs are started. Automatic profile refresh is
part of the future update lifecycle and is not yet implemented.

For multi-image applications, users choose only normal deployment values such
as storage destinations, frontend network and shared data paths. ProxMenux must
reserve all VMIDs atomically, create the dependency network, assign internal
addresses and service aliases, generate shared secrets, create every LXC and
start dependencies in health-checked order. Private configuration and database
paths use Proxmox-managed volumes with backup enabled; only intentionally shared
user data uses host bind mounts.

Validated multi-LXC installers attach an official Proxmox hookscript to the
main LXC. ProxMenux only creates this lifecycle configuration during
installation; no ProxMenux daemon remains running. On every later `pre-start`,
Proxmox starts any stopped dependency in declared order and waits for its
healthcheck before allowing the main LXC to start. Stopping the main LXC does
not implicitly stop its dependencies, so a restart cannot interrupt a database
or cache before the application has shut down.

Host bind paths selected by the user are created when missing and need an
independent backup policy; no shared path is created unless `host-bind` was
chosen. The default LXC is unprivileged and uses an 8 GB thin-provisioned
rootfs.

## Validation lifecycle

Generated templates start as `generated-unvalidated`. Promotion requires:

1. Clean installation.
2. Application health check.
3. Restart persistence.
4. Proxmox backup and restore.
5. Image replacement with persistent volumes preserved.
6. Review of every platform adaptation and unsupported feature.

The mini changelog comes from the LinuxServer README `Versions` section. At
installation, the architecture-specific registry digest and image labels are
recorded back into the local app JSON for future update comparisons.

## Generic multi-LXC installer

The generic stack compiler now handles an application with official PostgreSQL
and Redis/Valkey dependencies. It reuses `install_oci.sh` for image verification
and native OCI import. Docmost and Blinko are the first eligible catalog entries;
real installation and restart validation of this new driver remain pending.
Each other stack records its unresolved semantics in `proxmox.generic_stack_review`.

The compiler resolves generated secrets once per stack and binds PostgreSQL URL
credentials to the named database service. The installer allocates a private
network, writes service aliases, creates data volumes with the image's initial
files and ownership, and registers the Proxmox dependency hook before starting
the main LXC. It replaces example localhost public URLs with the assigned LAN IP
after a successful first boot and performs a graceful restart to apply them.
Using a stable DHCP lease or a domain is necessary if that address later changes.
For the rolling official PostgreSQL image, legacy `/var/lib/postgresql/data`
mounts become `/var/lib/postgresql`, preserving its versioned data directory.

Allocation is serialized among ProxMenux installers on the node; native `pct`
creation checks still arbitrate collisions with concurrent external operations.
A failed generic stack keeps completed LXCs and their volumes for diagnosis.
After a partial failure, inspect these resources before starting a new install.
No claim of atomic cross-cluster allocation or coordinated backup is made.
The hook snippet and `/etc/pve/priv/proxmenux-stack-<vmid>.json` are host artifacts;
back them up separately and remap VMIDs/recreate the bridge when restoring a
whole stack on another host. A normal LXC backup alone does not package these
host artifacts. This restoration workflow is still pending validation.

### Suite Arr (selectable media stack)

The `suite-arr` catalog entry offers Prowlarr, Sonarr, Radarr, qBittorrent,
Lidarr, Bazarr, SABnzbd, Seerr and Unpackerr. The first four are checked by
default. A separate single-choice menu offers Jellyfin (default), Plex, Emby
or no media server. Only selected services are created.
It reuses individual image templates, including the official Seerr and Unpackerr
images. Each `/config` (Seerr: `/app/config`) is a separate managed Proxmox volume
with backup enabled. Media applications share a user-selected host directory at
`/data`; media is not included
in container backups. New media directories receive mapped UID/GID 1000 ownership;
existing directories and their permissions are not recursively changed.

Web applications have LAN access and a private address for inter-service APIs.
Unpackerr has only a private address and no WebUI. Its initial start is deferred
until the selected Arr apps have generated API keys, then official `UN_*`
environment variables are persisted in its LXC config. Subsequent starts are independent and controlled by Proxmox onboot on each LXC.
Save the LXC configuration alongside application-volume backups.
The installer reads generated API keys, creates media root folders, and connects
selected Sonarr/Radarr instances to Prowlarr using its API schema. It does not
patch application binaries, add indexers, download content, disable authentication,
or install a VPN. First-login Arr authentication, indexers and quality profiles
still require user configuration. If qBittorrent is not selected, the download
client also needs manual configuration.

The shared tree is `downloads/{tv,movies,music,incomplete,usenet,usenet-incomplete}`
and `media/{movies,series,music}`. Subtitles reside beside their media files.
SABnzbd's new persistent config sets both incomplete and complete download paths
under `/data`; no download content defaults to the container rootfs.
Jellyfin retains its 4 cores, 4096 MB RAM, 16 GB config volume and hardware selector.
Other media servers retain their image's hardware options. Accounts/library setup,
Seerr and Bazarr connections, Lidarr profiles/root folder/download client, SABnzbd
Usenet credentials/client connections and subtitle providers still require user
configuration. These integrations are not claimed as automatic. Gluetun/VPN is
explicitly deferred, not installed or advertised as protecting traffic.

Seerr preserves the upstream non-root image user. Its documented security settings
map to `lxc.no_new_privs: 1` and `lxc.cap.keep: none` after clearing inherited drop
entries. All-capability removal is incompatible with requested additional capabilities.

With qBittorrent selected, the user chooses the password for `admin`. The installer
copies the image's own default configuration into its new `/config` volume and
sets the upstream PBKDF2-SHA512 password hash; existing config is never overwritten.
No image files are patched. The API configures `/data/downloads/`, its `incomplete`
subdirectory, and selected `tv`/`movies` categories. Sonarr/Radarr download clients
are tested before saving. All apps use the same paths, with no remote path mappings.
Login accepts the legacy HTTP 200/`Ok.`/`SID` response or the qBittorrent 5.2
HTTP 204/empty-body/`QBT_SID_<port>` response. A protected preferences request must
also succeed before any settings are changed. The password is masked in deployment
previews and returned in the final terminal credentials; protect terminal output.
It is stored hashed in qBittorrent and by the Arr apps in their private databases.

Suite Arr has no primary container, dependency hook or lifecycle contract. The
installer starts each selected application once to perform initial setup; that
one-time sequence does not couple future starts or stops. The user's onboot
choice is applied to each LXC individually. True dependent stacks (Immich,
Nextcloud and generic multi-image stacks) retain their existing hook lifecycle.
Failure preserves created containers/data. The suite remains unvalidated by a
complete real installation; tests cover compilation, independent startup and APIs.

### Common dependency profiles

The generic stack compiler also supports official `mariadb`, `mongo` and
`getmeili/meilisearch` dependencies. It uses MariaDB's bundled
`healthcheck.sh --connect --innodb_initialized`, MongoDB's `mongosh` ping, and
Meilisearch's `/health` endpoint. Missing implicit data volumes are materialized
as backed-up Proxmox volumes at their official paths; dependencies stay on the
private network with no LAN interface. The Proxmox host can still reach them.

Per-stack `stack_environment_overrides` and `stack_generators` in catalog overlays
correct imported metadata without editing upstream images. Monica gets a 32-byte
base64 application key and a boolean random-root-password switch. Linkwarden gets
boolean credential login and a storage path matching its persisted volume.
Petio's setup should use MongoDB host `mongo`, port `27017`; Plex credentials remain
user-provided. No third-party API credentials are fabricated.

These profiles enable `monica-official`, `petio` and `linkwarden` as installable,
not runtime-validated. Latest image tags remain selected; compatibility between
current upstream releases, initial application setup and restart/restore need
real laboratory testing. In particular, current MongoDB images require compatible
CPU instructions. Profiles do not grant LAN access to database services, enable
unattended upgrades or promise that a new database major version can reuse an old
data directory without migration.

### RomM and optional external credentials

RomM now uses the common MariaDB profile and binds `DB_PASSWD` to the same
installation-generated value as `MARIADB_PASSWORD`. Root credentials remain
independent. The overlay declares optional IGDB, ScreenScraper and SteamGridDB
credential groups via `stack_optional_environment`. They are requested only if
selected; skipped providers have no fabricated credentials. Entered secrets are
preserved literally (including dollar signs) and hidden in deployment summaries.
All five RomM data/configuration volumes default to backed-up private storage;
users may explicitly select shared host directories.

RomM remains installable without runtime validation. The hook starts dependencies
before the main application but does not implement Compose's propagation of an
explicit dependency restart to RomM. Upstream latest versions, first-run setup
and restart/restore behavior still need real installation testing.

### Teable and authenticated Redis

Teable uses three OCI LXC services: the app, PostgreSQL and Redis. The overlay
replaces the malformed imported Redis argument with a reviewed three-argument
`redis-server --requirepass` command, preserving the image entrypoint. The Redis
server password, `REDISCLI_AUTH` and Teable's Redis URI share one generated value.
Only this explicit authenticated Redis command profile is accepted; arbitrary
custom dependency commands remain blocked.

Redis healthchecks now require an exact `PONG` response. The hook does not embed
the password: the authenticated check obtains `REDISCLI_AUTH` inside the LXC.
Credentials remain readable to administrators in native runtime configuration.
A Compose internal network's `name` is treated as a label, not a fixed Proxmox
bridge name; external networks and custom IPAM remain unsupported by this driver.
Teable is installable but not yet runtime-validated; tests include a fake Redis CLI
that returns authentication errors with exit code zero, plus successful PONG.

### LinuxServer multi-image definitions and Kimai

The README converter now retains the full Compose stack instead of only the main
image and dependency names. Translation blockers remain until the generic driver
supports the full stack. Kimai reuses LinuxServer's own MariaDB image and its
/config persistence. Its generated database password matches DATABASE_URL;
readiness executes an authenticated SELECT 1 rather than merely checking a port.
The app uses Doctrine's automatic server-version detection and allows IPv4 host
names for the initial LAN deployment. Configure a specific domain when adding a
reverse proxy. Completion prints upstream instructions for creating the first
administrator inside the Kimai LXC; no default account is invented.

Kimai is installable but runtime-unvalidated. Diskover remains blocked: its
upstream example includes an Elasticsearch dependency and a privileged helper
changing host vm.max_map_count. Host kernel settings and Elasticsearch version
compatibility need separate review, not silent removal of these requirements.

### HAOS One native OCI profile

The community image `qweritos/haos-one:latest` is installable with the laboratory
adaptation: unprivileged LXC, `ostype=unmanaged`, `nesting=1`, `keyctl=1`, and a
managed `/mnt/data` volume included in Proxmox backups (32 GB default, 16 GB
minimum). The image's entrypoint, command and stop signal remain imported from
OCI metadata. No Docker daemon or compatibility proxy is installed by ProxMenux;
the nested runtime belongs to the image itself.

The installer asks for explicit acknowledgement of the experimental profile and
its inner AppArmor limitations. First boot may pull several images. A bounded
20-minute check reports progress and requires healthy/supported Supervisor, the
real Core container rather than the landing page, running CLI/DNS/audio/multicast/
Observer containers, and working Core and Observer HTTP endpoints. The final
Core URL is detected on port 80 or 8123 instead of assumed. A first-boot failure
preserves the LXC, data and root-only console log for diagnosis; it never reports
success. If starting is declined, no unverified URL is printed.

This installer path and the rolling latest image remain runtime-unvalidated.
The historical lab evidence stays in the template; it is not a guarantee for
new releases. Full backup restore, outer-image replacement, USB and multicast
discovery still need explicit tests. See the upstream project:
https://github.com/qweritos/haos-one

### Native Compose resource limits

`mem_limit` now supplies the editable Proxmox RAM default (MiB rounded upwards,
minimum 16 MiB). A conflicting `deploy.resources.limits.memory` remains blocked
for review. Swap is still an independent Proxmox setting, not a claim of exact
Docker swap defaults. `ulimits` maps soft/hard values to native `lxc.prlimit.*`;
`-1` becomes `unlimited`. Invalid resource names, malformed values, duplicate
remote entries and soft limits greater than hard limits are rejected. The
installation summary shows these limits, including per-service stack limits.

No host sysctls, service-manager limits or privileges are silently changed to
make a requested limit succeed. LXC/kernel restrictions still apply. In
particular `nproc` is per real UID, not per container, and is not a replacement
for a cgroup PID limit. Reference: https://linuxcontainers.org/lxc/manpages/man5/lxc.container.conf.5.html

Diskover and RagFlow no longer carry the generic mem_limit/ulimits translation
blockers, but remain unavailable for automatic installation until their other
dependencies, healthchecks and host requirements are adapted. Diskover retains
Elasticsearch 7.17.22 in `original_compose`; the normalized candidate follows the
catalog's `latest` policy. Compatibility and tag availability therefore require
review before promotion, not an unverified Elasticsearch upgrade. The full Compose is now preserved in the active JSON,
as it already is when regenerating from the LinuxServer README.

### Host monitors: experimental native profile

Glances offers an isolated alternative when host access is declined: an
unprivileged LXC with its own IP, default AppArmor, no host mounts, and no extra
capabilities. It monitors only itself, not Proxmox. The final summary states this
scope explicitly. `GLANCES_OPT=-w` remains automatic in either mode. Netdata's
host profile still requires acceptance; this fallback applies only to Glances.

Glances and Netdata have an installable `host_monitor` profile, tested on amd64
Proxmox 9.2.18 on 2026-09-14. Both expose host CPU/RAM/process metrics and survive
a shutdown/start cycle. Netdata also exposes LXC cgroup charts and preserves its
registry identity in a managed volume. Observed image digests and versions are
recorded in each template; rolling tags and arm64 are not universally validated.

The profile uses a privileged LXC, explicitly inherits host PID and
network namespaces, and uses unconfined AppArmor. It requires informed consent;
a compromised monitor could affect the host. Its endpoint uses the host IP and
host firewall, with a port-conflict check before image download. Do not expose
these unauthenticated dashboards to untrusted networks.

Only the monitor's LXCFS mount hook is cleared, to avoid reporting container
CPU/RAM limits as host metrics. Proxmox pre-start/autodev/post-stop hooks are
retained. No Docker socket or host root filesystem is mounted. Netdata's native
`/host` paths receive read-only proc/sys/identity mounts, and its three private
data directories remain managed volumes included in backup. Full filesystem,
SMART, Docker inventory and GPU monitoring are not implied by this profile.
The host cgroup mount is explicitly bound read-only below `/host/sys/fs/cgroup`.
CPU consumption is bounded with `cpulimit` rather than a restricted CPU affinity,
so the monitor sees the host's real processor count.

Proxmox does not accept `lxc.namespace.share.*` directly in CT configuration.
The installer uses supported `lxc.include` referencing the static companion
`/etc/pve/lxc/proxmenux-host-monitor`. This file persists across host reboots but
is NOT included in a CT vzdump. Preserve/recreate it when restoring on another
host, in addition to restoring managed volumes. Full restore/image replacement
have not been tested. No custom supervisor or image entrypoint is introduced.

DeepSeek OCR remains deferred at the user's request: registry inspection on
2026-09-14 found only `v2.2.0` for both IceWhaleTech images and no `latest` tag.
No fixed-version exception or deployment has been introduced.
