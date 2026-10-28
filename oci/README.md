# OCI manager Apps

OCI manager Apps runs official OCI images, the ones published for Docker, as native Proxmox VE LXC containers. No Docker engine is installed inside them: Proxmox VE imports the filesystem and the process metadata of the image, and the application becomes the main process of an LXC that is managed like any other container of the node.

The image stays the one its maintainer publishes. What ProxMenux adds is the environment Docker Compose would have created around it: persistent data, network, variables, devices and start order, written with Proxmox VE primitives.

This document describes the engine in this directory: how it is organised, how a container is created and updated, how a Compose file or a `docker run` command becomes an `oci-compose`, and how to write an `oci-compose` by hand and install it. The user documentation, with screenshots, is the [OCI manager Apps section](https://proxmenux.com/en/docs/oci-manager) of the ProxMenux documentation.

- [The model](#the-model)
- [Structure](#structure)
- [How a container is created](#how-a-container-is-created)
- [Update, modify, recreate and remove](#update-modify-recreate-and-remove)
- [Private image registries](#private-image-registries)
- [From a Compose file or a docker run command to an oci-compose](#from-a-compose-file-or-a-docker-run-command-to-an-oci-compose)
- [The oci-compose, block by block](#the-oci-compose-block-by-block)
- [Writing and testing an oci-compose](#writing-and-testing-an-oci-compose)
- [Adding an application to the catalog](#adding-an-application-to-the-catalog)
- [Design and laboratory notes](#design)

## The model

One OCI image becomes one native LXC.

| Requirement | Docker expresses it as | OCI manager Apps turns it into |
|---|---|---|
| Run the application | `image`, `entrypoint`, `command` | The rootfs built from the image and the main process of the LXC |
| Keep data | `volumes` | A container disk (`mpN`) included in the backup, or a host directory |
| Publish the service | `ports` | An address of its own for the LXC; the service answers on its original port |
| Use hardware | `devices`, `group_add`, `runtime: nvidia` | `devN` entries with the group of the host device, and a reviewed profile |
| Connect dependencies | `networks`, `depends_on` | One LXC per service, a private bridge, fixed addresses, start order and healthchecks |
| Update | `pull` and recreate | A new rootfs with the same data, network and devices |

A Compose key with no safe equivalent is not dropped: it is listed as a blocker and the application is not offered for installation until it is resolved.

## Structure

```
oci/
├── catalog/
│   ├── index.json            list of applications shown by the menu
│   ├── apps/<app>.json       the oci-compose generated for each image
│   ├── curated/<app>.json    an oci-compose written and reviewed by hand
│   ├── overlays/<app>.json   adjustments laid over a generated oci-compose
│   ├── categories.json       category of each application
│   ├── volume-policy.json    which paths hold content of the user
│   └── verification.json     applications tested for real
├── examples/                 oci-compose files written by hand
├── schemas/                  the JSON schema every oci-compose follows
├── src/proxmenux_oci/        menu, converter and deployment plan
├── remote/                   what creates and maintains the LXC on the node
└── tests/
```

An **oci-compose** is the JSON file an application is installed from. Its `kind` is `proxmenux.oci-template`. It says which image runs, which ports, variables and volumes it has, what the installation asks, and how each thing is done in Proxmox VE.

There are three places an oci-compose comes from:

- **The catalog.** The converter writes `catalog/apps/<app>.json` from the Compose file the project of the image publishes. When that file needs something Compose cannot say, such as a question, a generated password or a GPU profile, it goes in `catalog/overlays/<app>.json` and is laid over the generated file each time it is read. An application whose definition is written whole by hand lives in `catalog/curated/`.
- **A definition given at the moment.** The option *Install an image that is not in the catalog* translates a Compose file, a `docker run` command or an image reference with the same converter.
- **A file written by hand**, read by the same option. It is described in [Writing and testing an oci-compose](#writing-and-testing-an-oci-compose).

On a node, the engine is installed in `/usr/local/share/proxmenux/oci/engine/`. Every installation keeps its record in `/usr/local/share/proxmenux/oci/instances/<VMID>/oci-compose.json`: the oci-compose it was installed from, under `template`, together with the answers given during the installation and the configuration Proxmox VE ended with. Updates, changes and removals read that record.

## Private image registries

Open **OCI manager Apps → Registry accounts** on the Proxmox node. Sign in
with a registry hostname (for example `ghcr.io` or `registry.example.com:5443`),
a username and a password or token with image pull permission. Passwords are
entered in hidden fields and confirmed before the registry is contacted.

Select a saved account to check access to an image, download it to template
storage, install it with the existing LXC wizard, update its credentials or
remove them. Image references retain their tag or full `sha256` digest.
The normal custom-image importer can also use the saved credentials, including
Compose files whose services come from private registries. When a registry
refuses an image there, the importer offers to sign in on the spot and reads
the image again. Updates, Modify, Recreate, the watchdog and the update check
of the Monitor use the saved accounts too.

ProxMenux keeps the accounts in `/etc/pve/priv/proxmenux/registry-auth.json`,
where Proxmox keeps its own storage passwords: readable only by root and shared
by every node of the cluster. The host backup includes it, and uninstalling
ProxMenux removes it. A `REGISTRY_AUTH_FILE` set by the user is respected;
without the cluster filesystem, Skopeo's default `/root/.config/containers/auth.json`
is used. The
credential directory must be owned by root with mode `700`, and the file with
mode `600`. Basic credentials are base64 encoded, not encrypted. Configured
Skopeo credential helpers use their own stores. Failed sign-in attempts leave
the previous file credentials intact; removing an account leaves running
applications unchanged. Other Skopeo/Docker authentication files are managed
separately and may still grant access.

TLS verification remains enabled. Install a private registry CA in
`/etc/containers/certs.d/REGISTRY[:PORT]/ca.crt` when required, on each node
that pulls images. Registry credentials are not written into the application
template or copied into its LXC.

Image access checks have a 30-second timeout per request; sign-in has a 45-second
timeout. Errors identify rejected credentials, missing images, incompatible
architectures, network/TLS failures, rate limits and registry outages. Downloads
reuse the native update cache and layer integrity checks. Damaged cached images
are downloaded again, and storage failures leave existing applications alone.

## How a container is created

Selecting an application, or giving a definition, opens the same sequence.

1. **Read.** The oci-compose is composed and checked against the schema. One with blockers is not offered.
2. **Ask.** *Install with default settings* asks what every installation decides: where the data of the user goes, the address, required values with no default, and whether it starts with the node. *Install with advanced settings* opens every decision: VMID, cores, memory, storage of each path, bridge, optional variables and devices.
3. **Review.** A summary shows image, resources, storage, each path and where it goes, network, acceleration, security and variables, with secrets masked. Nothing has been created yet.
4. **Resolve.** The registry is queried, the architecture of the host is selected and the digest the tag points to at that moment is fixed.
5. **Download and verify.** Skopeo downloads the image as an OCI archive. Every layer is checked against its digest before anything is created.
6. **Build.** `pct create` builds the rootfs from the archive and imports `Entrypoint`, `Cmd`, `Env`, `User`, `WorkingDir` and `StopSignal` from the image.
7. **Connect.** The volumes are added as mount points, then the devices, the environment, the network and the security settings the oci-compose declares.
8. **Prepare.** Each new volume is made ready for the first start: `lost+found` is removed and the directory is given to the user the application writes with. The files the oci-compose asks to write are written.
9. **Start and check.** The container starts, an address is waited for, the settings that need the running application are applied, and the service is checked. A failed first start is reported as a failed installation.
10. **Register.** The record of the installation is written, and a copy travels inside the container so that a backup carries it.

The result is an ordinary LXC:

```
entrypoint: /jellyfin/jellyfin
hostname: jellyfin
cores: 2
memory: 2048
unprivileged: 1
rootfs: local-zfs:subvol-126-disk-0,size=8G
mp0: local-zfs:subvol-126-disk-1,mp=/config,backup=1,size=16G
mp1: local-zfs:subvol-126-disk-2,mp=/cache,backup=1,size=16G
mp2: local-zfs:subvol-126-disk-3,mp=/media,backup=1,size=32G
dev0: path=/dev/dri/renderD128,mode=0660,deny-write=0,gid=993
net0: name=eth0,bridge=vmbr0,firewall=1,host-managed=1,ip=dhcp,type=veth
tags: media;oci;proxmenux
```

An application made of several images is one entry of the catalog and one installation. It creates one LXC per service on a private bridge, with fixed addresses and the names the services use to find each other, and starts them in order.

## Update, modify, recreate and remove

The OCI menu has a **Check for updates** entry. Checking changes that same
entry to **Checking for updates (completed/total)**, then **Updates available (N)** when
newer images are found. Progress counts applications, including coordinated
applications with several containers, and advances as each finishes. When finished, the entry shows only
**Updates available (N)** or **Check for updates**. Only registry metadata is read; no image layers are
downloaded and no containers are changed. The menu remains usable during the
check. Leaving the OCI menu closes its request; the Monitor may finish
metadata queries already in progress before stopping the remaining checks.

Open **Updates available (N)** to choose applications with Space. Nothing is
preselected, even when there is only one update. **Select all** at the top
includes every listed application. After reviewing the selection, each
application uses the existing update workflow, including its identity checks,
backup prompts and recovery. Cancelling or failing an update stops the batch.
The selection screen has only **Update** and **Cancel** buttons.

Opening the menu reads the Monitor's existing `/etc/proxmenux/apps` results
without contacting registries. Its daily checks and the manual menu check use
the same `lxc_apps.check_app` implementation, cache and registry credentials.
There is no second checker, private update-status cache or fallback checker.
Manual checks run in the Monitor process through a root-only local Unix
socket, preserving its locks and registry retries without changing web
authentication. ProxMenux Monitor must be installed, running and include the
menu integration for manual checks.

Manual checks run up to sixteen applications in parallel. The native checker
holds its shared cache lock only while reading or publishing a result; each
app has its own check lock. Before saving it re-reads the app and installation
record, discards answers for a concurrently edited/replaced app, and preserves
unrelated registrations and schedules. A fresh tag/index lookup that confirms
the same platform digest reuses its immutable version/build metadata. Changed
digests still fetch and verify the new metadata; installs and updates retain
the full image-contract verification path. Checks therefore still consult the
registry rather than returning a cached verdict as a new check.

Results older than 24 hours or for a different installed image or reference
are not offered as current. Network failures retain the Monitor's existing
result and retry state, or remain unknown when no previous result exists.
Coordinated applications count once and follow the Monitor's existing policy:
update availability is tracked on the primary container, while secondary
containers are updated together with it. The menu does not add independent
update tracking for secondary images. A reference pinned to an immutable
digest does not follow newer tags.

*Manage installed OCI applications* lists the registered installations. Before any action a container is compared with its record; one that no longer matches is neither modified nor deleted.

| Operation | What changes | What is kept |
|---|---|---|
| **Update** | The rootfs is replaced by the image the saved tag publishes today | Record, container disks, host directories, network and devices |
| **Modify** | Edit and confirm the configuration; supported native settings apply directly, while other changes use the existing recreation flow | Native edits keep the installed image and rootfs; both paths preserve persistent data |
| **Recreate** (multi-container) | Every container is rebuilt from the image it was installed with | Data, network and devices |
| **Watchdog** | Whether the application is started again when it stops on its own | Everything; only the choice is saved |
| **Remove** | The LXC, or every container of the application, its disks and its record | Host directories, with their content |

An update is a transaction:

1. The tag is resolved. When the registry still serves the installed digest, nothing is downloaded and the container is not touched.
2. The new image is downloaded and verified, and the operation checks that the backup fits, before the container stops.
3. The container is stopped and backed up.
4. The new rootfs is imported and the record is applied again: mount points, environment, network, devices and security.
5. The application is checked. When it answers, the record is published with the new digest. When it does not, the previous container is restored from the backup.

Settings changed in Proxmox VE after the installation, such as memory, cores or start with the node, are carried into the new record. An operation interrupted by a closed terminal or a reboot is detected the next time the menu opens, and the previous installation can be recovered. A container restored from a backup on another host is registered again from the copy of the record it carries.

A rolling tag is not an unattended update: the digest changes only through an explicit update.

For standalone applications, CPU and RAM changes apply live. Supported network settings, environment overrides, directory mounts, additional managed volumes and native devices use a controlled stop/start when needed. Modify does not query the registry or download an image for these native edits, even if the cached archive has already been cleaned. Removing a managed mount detaches its disk without deleting its data; subsequent image updates park that unused disk and return it to the container. An optional retained backup does not force recreation.

The native path checks the saved configuration and installation identity, keeps a private before/after journal, and restores the original settings if applying them or checking the restarted service fails. It refuses to overwrite concurrent edits. Changes that require installer adaptations, such as NVIDIA runtime changes, GPU permission/environment setup, file mounts, completion notes or a refreshed catalog template, use the existing validated recreation flow. The route is chosen before applying any settings, so one proposal is not partially applied by both paths. The recreation flow reuses a verified cached archive when it matches the resolved image; it downloads an image when a suitable archive is unavailable. Image changes and coordinated stack operations retain their separate update flow.

## From a Compose file or a docker run command to an oci-compose

The converter reads Compose files with one or several services. Multi-service
files use the native stack compiler: each service runs in its own LXC, with
dependency ordering and a private network. The first service that publishes a
port is selected as the main service, unless `x-casaos.main` selects another one.
Every image is checked for registry access before installation; written tags,
digests and image entrypoints are preserved.

The file importer resolves an explicitly selected project `.env` and service
`env_file` files, then applies Compose interpolation and service overrides. It
does not silently import the host process environment. Missing required values
are requested before installation, and summaries hide secret values. An inline
Compose definition can also supply an environment file or enter values through
the assistant.

Published web services receive individual LAN addresses. The main web check uses
the same LAN URL shown to the user; private backend aliases stay on the internal
network. Internal services can use declared or inherited image health checks,
exposed TCP ports, or a clearly labelled process-running check. A running process
alone does not satisfy `service_healthy`.

Repeated identical volume sources share one host directory, selected once;
separate configuration volumes stay independent. Host directories are not part
of a normal Proxmox container backup. Newly created private data volumes use the
imported image user unless an explicit volume owner or PUID/PGID overrides it.
SELinux `z`/`Z` labels are reported as not applied on a non-enforcing host; an
enforcing host is refused rather than silently losing their protection.

An explicit Compose `stop_signal` overrides the image's stop signal through
`lxc.signal.halt`. Without it, the image signal stays unchanged, including when
Compose replaces its entrypoint. A worker sharing a web image may therefore
need its own declared stop signal. Native updates abort safely if a service
does not stop; they do not silently force termination to replace its disks.
Some programs ignore termination signals when running as PID 1. Setting a signal
does not add an init process or guarantee graceful shutdown; an explicit
`SIGKILL` requests forced termination, not a graceful stop.

A dependency declared with `service_completed_successfully` runs as a one-shot
job. Its original command must finish with a verified exit code of zero before
the dependent service starts. Such jobs are excluded from onboot and watchdog
restarts. Update and restore invalidate the completion proof when the image,
runtime configuration or recovery identity changes. A migration update is
refused when database or unclassified backend data lives in host directories
that the transaction cannot safely restore.
The native exit-status monitor currently accepts LXC 7.0.0, the verified protocol
version. Other versions refuse one-shot execution rather than treating a stopped
container as proof of success.

The bridges are local to the installation node; they are not a cluster SDN.
Unsupported network and runtime semantics are reported before installation.
Support for several services does not imply complete Docker Compose compatibility.
A `docker run` command or image reference is converted to Compose first and
follows the same importer.

Starting from this definition:

```yaml
services:
  app:
    image: ghcr.io/example/app:latest
    ports:
      - 8080:8080
    volumes:
      - ./config:/config
    environment:
      - TZ=Europe/Madrid
      - API_KEY=
    restart: unless-stopped
```

each key becomes a field of the oci-compose:

| Compose key | Field of the oci-compose | Result in Proxmox VE |
|---|---|---|
| `image` | `container_contract.image` | The image that is downloaded; its tag is resolved to a digest at each installation |
| `ports` | `container_contract.ports`, `first_run.endpoints`, `catalog_ui.launch` | The LXC has its own address, so the published port is not used: the service answers on the container port. The first TCP port is taken as the web address |
| `volumes` | `container_contract.volumes`, `proxmox.installer_profile.volume_preparations` | A container disk or a host directory for each path |
| `environment` | `container_contract.environment` | Variables of the LXC. A name that reads as a password, token or key is asked as a secret |
| `restart` | `container_contract.restart` | The watchdog is proposed by default |
| `mem_limit` | `proxmox.installer_profile.resources.memory_default_mb` | The memory proposed for the LXC |
| `cpu_shares` | `proxmox.installer_profile.resources.cpu_shares` | `cpuunits` of the LXC |
| `ulimits` | `proxmox.installer_profile.resources.rlimits` | `lxc.prlimit.*` |
| `shm_size` | `proxmox.installer_profile.tmpfs_mounts` | A tmpfs at `/dev/shm` of that size |
| `user`, `working_dir`, `entrypoint`, `command`, `hostname`, `group_add` | `proxmox.installer_profile.runtime` | The process the LXC starts, its user, directory and groups |
| `extra_hosts` | `proxmox.installer_profile.extra_hosts` | Entries of `/etc/hosts` in the container |
| `devices` | `proxmox.installer_profile.device_requests` | A `devN` entry for each device, confirmed during the installation |
| `runtime: nvidia` | `proxmox.installer_profile.device_requests` | The NVIDIA devices and the driver files of the host |
| `healthcheck` | `proxmox.installer_profile.startup_healthcheck` | The check of the first start. It runs during installations and updates, not continuously |
| `cap_add`, `sysctls`, `security_opt` | `proxmox.installer_profile.security` | Capabilities checked against the LXC model, `lxc.sysctl` entries and AppArmor or seccomp settings, each confirmed |
| `privileged` | `proxmox.security_profile` | The LXC stays unprivileged; the privileged mode is offered as an explicit choice |
| `network_mode` | `proxmox.installer_profile.network` | `host`, `bridge` and `default` all mean the network of the LXC, never the one of the Proxmox host |
| `stop_grace_period` | `proxmox.defaults.shutdown_timeout_seconds` | The time a shutdown waits |
| `labels`, `logging` | Kept in `container_contract.original_compose` only | Not applied: they are read by Docker tools |

What has no translation stops the installation and is named: `pid: host`, `configs`, external secrets, a `build` section without a published image, and shell substitutions such as `$(command)`.

Besides those fields, the converter writes the blocks that describe the translation itself: where the definition came from, the keys it understood, the adaptations it applied and the state of each validation. They are listed in [Blocks ProxMenux writes](#blocks-proxmenux-writes).

## The oci-compose, block by block

A complete oci-compose has around 550 lines, and most of them are written by the converter. One written by hand contains only what its author decides; ProxMenux completes the rest when it reads the file.

A file written this way describes one image. An application made of several images is read from its complete file, which carries the `compose_stack` block with its services.

Two files of [`examples/`](examples/) are used below. Both install the same as the entry of the catalog with the same name:

- [`jellyfin-official.oci-compose.json`](examples/jellyfin-official.oci-compose.json): two ports, an optional variable, three volumes with different owners, a GPU profile, a setting applied after the first start and a check of the service.
- [`duplicati-official.oci-compose.json`](examples/duplicati-official.oci-compose.json): two secrets generated during the installation and the credentials shown at the end.

The smallest valid file names the image and nothing else:

```json
{
  "kind": "proxmenux.oci-template",
  "container_contract": {
    "image": { "reference": "traefik/whoami:latest" }
  }
}
```

### `kind`

Always `"proxmenux.oci-template"`. It is how the file is recognised.

### `catalog_ui`: how the application is presented

```json
"catalog_ui": {
  "title": { "en_US": "Jellyfin Official" },
  "tagline": { "en_US": "Official Jellyfin image with optional VA-API or NVIDIA acceleration." },
  "category": "media",
  "icon": "https://raw.githubusercontent.com/linuxserver/docker-templates/master/linuxserver.io/img/jellyfin-icon.png",
  "website": "https://jellyfin.org/",
  "documentation": "https://jellyfin.org/docs/general/installation/container/",
  "repository": "https://github.com/jellyfin/jellyfin-packaging"
}
```

| Field | What it is |
|---|---|
| `title` | The name shown in the menu, in the notes of the container and in ProxMenux Monitor. The name of the installation is taken from it |
| `tagline`, `description` | One line and a longer text, shown on the page of the application |
| `category` | One of the keys of `catalog/categories.json`: `media`, `backup`, `network`, `databases`, `documents`, `downloads`, `sharing`, `monitoring`, `smarthome`, `security`, `ai`, `tools`, `misc` and the others listed there |
| `icon` | Address of the logo, used in the notes of the container and in the Monitor |
| `website`, `documentation`, `repository` | Links of the project. The installation shows the documentation link when it asks about an optional variable or names a service the application needs |
| `launch` | `scheme`, `port` and `path` of the web interface. `"port": null` declares a service with no web interface, together with an empty `first_run.endpoints` |

Without this block the title is taken from the name of the image and the category is `misc`.

### `container_contract`: what the image needs

This block is the equivalent of the service of a Compose file.

```json
"container_contract": {
  "service_name": "jellyfin",
  "container_name": "jellyfin",
  "image": { "reference": "jellyfin/jellyfin:latest" },
  "ports": [
    { "container_port": 8096 },
    { "container_port": 7359, "protocol": "udp", "required": false }
  ],
  "environment": [
    { "name": "JELLYFIN_PublishedServerUrl", "required": false,
      "prompt": "Optional published URL for Jellyfin" }
  ],
  "volumes": [
    { "container_path": "/config" },
    { "container_path": "/cache" },
    { "container_path": "/media", "default": "host-bind", "managed_volume": { "default_size_gb": 32 } }
  ],
  "restart": "unless-stopped"
}
```

**`image.reference`** is the only required field of the file: the image as it would be written after `docker pull`, with its tag. The registry, the repository and the tag are worked out from it.

**`service_name`** and **`container_name`** are the name of the service and the hostname proposed for the LXC. Without them both come from the title.

**`ports`**. One entry for each port the application listens on.

| Field | Default | What it is |
|---|---|---|
| `container_port` | — | The port inside the container. It is the one the service answers on |
| `protocol` | `tcp` | `tcp` or `udp` |
| `required` | `true` | `false` marks a port the application works without; the summary shows it as optional |

The first TCP port is taken as the web address unless `first_run.endpoints` says otherwise.

**`environment`**. One entry for each variable the installation sets.

| Field | Default | What it is |
|---|---|---|
| `name` | — | The name of the variable |
| `example` | empty | The value proposed. A variable with a value is installed with it in default mode and can be changed in advanced mode |
| `required` | `true` | A required variable with no value is asked in both modes. An optional one is offered only in advanced mode |
| `sensitive` | `false` | `true` asks the value hidden, asks it twice and masks it in the summary |
| `prompt` | the name | The text of the question |
| `container_address` | — | A value built from the address the container gets, written with the mark `@CONTAINER_ADDRESS@`, for example `"http://@CONTAINER_ADDRESS@"`. With a static address it is known before the installation; with DHCP it is resolved when the container gets its lease |

The variables the image itself defines are imported with it and are not written here.

**`volumes`**. One entry for each path that has to survive an update.

| Field | Default | What it is |
|---|---|---|
| `container_path` | — | The path inside the container |
| `installation_choice` | see below | Where the path may go: `managed-volume` (a container disk), `host-bind` (a host directory) |
| `default` | `managed-volume` | The choice proposed |
| `managed_volume.default_size_gb` | 16, or 8 for a path with content of the user | The size proposed for the container disk |
| `managed_volume.backup` | `true` | Whether the disk is part of the backup of the container |
| `read_only` | `false` | Mounts the path read-only |

Where a path goes follows one rule. A path that holds content of the user, such as `/media`, `/downloads`, `/music` or `/backups`, is offered as a container disk or as a host directory, and the installation asks which. The list is in `catalog/volume-policy.json`. Every other path is state of the application and goes to a container disk without asking. Writing `"installation_choice": ["managed-volume", "host-bind"]` or `"default": "host-bind"` on a volume offers the host directory for a path that is not in that list.

**`restart`**. With `unless-stopped`, `always` or `on-failure`, the watchdog is proposed by default: an application that stops on its own is started again.
Its running history belongs to the installation UUID, not just the VMID. Before
restarting a guest, it rechecks the saved record and the live ProxMenux identity
under the registry operation lock. A stale record therefore cannot start an
unrelated guest or a temporary `oci-data-holder` that reused the same VMID.
Updates, removals, intentional stops and guests first seen stopped remain left alone.

### `first_run`: what is shown when the installation ends

```json
"first_run": {
  "endpoints": [
    { "label": "Jellyfin WebUI", "scheme": "http", "port": 8096, "path": "/",
      "source": "official-container-documentation" }
  ]
}
```

**`endpoints`** are the addresses printed at the end, written in the notes of the container and opened from the Monitor. Each one needs `label`, `scheme`, `port`, `path` and `source`, a free text that says where the address is documented. An empty list declares a service with no web interface: its ports are then shown as `IP:port` text and no link is offered.

**`credentials`** are the logins printed at the end. From the Duplicati example:

```json
"credentials": [
  { "label": "Duplicati web interface (password only)",
    "type": "configured-or-installer-generated",
    "username": "Not required (password only)", "password": null,
    "password_environment": "DUPLICATI__WEBSERVICE_PASSWORD",
    "change_required": false, "source": "duplicati-documentation", "retrieval": null }
]
```

| `type` | Meaning |
|---|---|
| `static-default` | A login the image documents, written in `username` and `password` |
| `configured-or-installer-generated` | The value of the variable named in `password_environment`, typed or generated during the installation |
| `runtime-generated` | A password the application prints at its first start; `retrieval` says how it is read |

### `proxmox.defaults`: the container that is proposed

```json
"proxmox": {
  "defaults": { "memory_mb": 2048 }
}
```

Only what differs from the defaults is written. The defaults are 2 cores, 1024 MB of memory, 512 MB of swap, an 8 GB rootfs, an unprivileged LXC with `nesting=1`, DHCP on `vmbr0`, the firewall on, and no start with the node. The fields are `cores`, `memory_mb`, `swap_mb`, `rootfs_size_gb`, `unprivileged`, `features`, `onboot` and `shutdown_timeout_seconds`. The storage and the bridge proposed are the ones of the node.

### `proxmox.installer_profile`: what Compose cannot say

This block holds the decisions of the installation. Each part is optional.

**`generated_sensitive_environment`**: secrets the installation generates.

```json
"generated_sensitive_environment": {
  "SETTINGS_ENCRYPTION_KEY": { "strategy": "token-hex", "bytes": 16, "prompt": false },
  "DUPLICATI__WEBSERVICE_PASSWORD": { "strategy": "token-hex", "bytes": 12, "prompt": true }
}
```

The variable is declared in `environment` with `"sensitive": true`. In default mode its value is generated. In advanced mode a variable with `"prompt": true` is asked, and left empty it is generated. The generated value is shown at the end when `first_run.credentials` names the variable.

**`volume_preparations`**: who owns each new volume.

```json
"volume_preparations": [
  { "container_path": "/config", "remove_lost_found": true,
    "owner_strategy": "mapped-root", "only_when_mount_type": "managed-volume" },
  { "container_path": "/media", "remove_lost_found": true,
    "owner_strategy": "mapped-application-user", "only_when_mount_type": "managed-volume" }
]
```

A new container disk is an empty filesystem owned by root that carries a `lost+found` directory. `owner_strategy` gives it to `mapped-root`, the root of the container, for an image that starts as root and takes ownership of its directories itself, or to `mapped-application-user`, the user 1000 the application writes with. Without this list every volume is prepared for `mapped-application-user`.

**`startup_healthcheck`**: how the first start is checked.

```json
"startup_healthcheck": {
  "scheme": "http", "port": 8096, "path": "/System/Info/Public",
  "timeout_seconds": 180, "request_timeout_seconds": 10,
  "stability_seconds": 4, "verify_tls": false
}
```

The installation and every update wait up to `timeout_seconds` for that address to answer, and then `stability_seconds` more to see that it keeps answering. An update that does not pass the check is undone. Without this block the web address is checked, or that the container keeps running when there is no web address.

**`hardware_acceleration`**: the choice of GPU.

```json
"hardware_acceleration": {
  "prompt": "Hardware acceleration for Jellyfin",
  "default": "none",
  "profiles": [
    { "id": "none", "label": "No acceleration (CPU)", "device_requests": [] },
    { "id": "vaapi", "label": "Intel/AMD (VA-API)",
      "device_requests": [
        { "id": "vaapi-render", "kind": "character-device", "purpose": "vaapi",
          "path_prompt": "GPU render device", "host_path_default": "/dev/dri/renderD128",
          "container_path_strategy": "same-as-host", "mode": "0660", "deny_write": false,
          "gid_strategy": "host-device-gid",
          "environment": [
            { "name": "LIBVA_DRIVER_NAME", "prompt": "VA-API driver",
              "choices": ["auto", "radeonsi", "iHD", "i965"], "default": "auto", "omit_values": ["auto"] }
          ] }
      ] },
    { "id": "nvidia", "label": "NVIDIA (NVENC/NVDEC)",
      "device_requests": [
        { "id": "nvidia-runtime", "kind": "nvidia-runtime", "purpose": "nvidia-cuda-nvenc-nvdec",
          "device_selection": "all-requested-by-compose" }
      ],
      "environment": [ { "name": "NVIDIA_VISIBLE_DEVICES", "value": "all" } ] }
  ]
}
```

The installation shows one option for each profile the host can serve: a profile whose device is not on the host is not listed. Each profile declares the devices it passes and the variables it sets.

| Field of a device request | What it is |
|---|---|
| `kind` | `character-device` for a device node such as a render node, or `nvidia-runtime` for an NVIDIA GPU with the driver files of the host |
| `host_path_default`, `path_prompt` | The device proposed and the text that asks for it |
| `container_path_strategy` | `same-as-host` keeps the path of the host inside the container |
| `mode`, `gid_strategy` | The permissions of the device. `host-device-gid` reads the group from the device of the host, so no fixed `video` or `render` number is assumed |
| `environment` | Variables asked with the device, with `choices` and the values that are left unset (`omit_values`) |

A profile may also change the image, with `image`, for projects that publish one tag for each GPU vendor, and apply settings once the application is running, with `post_start_configurations`. In the Jellyfin example the VA-API and NVIDIA profiles write the transcoding and tone mapping settings to `encoding.xml` after Jellyfin creates it.

**Other parts of the profile.**

| Part | What it does |
|---|---|
| `completion_notes` | A list of texts printed when the installation ends, for what is left to do by hand |
| `external_services` | Names of services the application needs already running, such as `["MariaDB"]`. They are announced before the installation asks how to reach them |
| `generated_files` | Files written in the container before its first start, each with `container_path`, `content`, `owner` and `mode`. With `"only_if_missing": true` a file that already exists in a kept volume is not replaced |
| `volume_owner` | `uid` and `gid` of the user the application writes with, when it is not 1000 |
| `tmpfs_mounts` | Volatile paths with a size and mount options. An optional `owner_strategy` sets ownership to `mapped-root`, `mapped-application-user` (using `uid`/`gid` or `PUID`/`PGID`-style variables), or `image-user` (the effective `lxc.init.uid`/`lxc.init.gid`); `mode` sets permissions. The exact `/run` path requires an owner strategy. |
| `non_persistent_image_volumes` | Paths the image declares as volumes that are left inside the rootfs |
| `runtime`, `resources`, `security`, `device_requests`, `extra_hosts` | What the Compose keys of the [translation table](#from-a-compose-file-or-a-docker-run-command-to-an-oci-compose) become |

### `proxmox.security_profile`: privileges

Without this block the LXC is unprivileged with the default AppArmor profile. `"optional_privileged_lxc": true` offers the privileged mode as a choice that defaults to no; `"requires_privileged_lxc": true` asks for it with a confirmation that states the risk. A GPU, a USB device or a serial port are passed as individual devices and need neither.

### Blocks ProxMenux writes

These blocks are part of every complete oci-compose. They are not written by hand: when a file does not bring them, they are added as the converter writes them for the same image, ports, variables and volumes.

| Block | What it holds |
|---|---|
| `schema_version`, `id`, `status` | The version of the format, the identifier and the state of the review. `laboratory-validated` is given only by `catalog/verification.json`: a file that declares itself verified is read as not verified |
| `source` | Where the definition came from and when it was generated |
| `container_contract.original_compose` | The Compose file the oci-compose was translated from |
| `compose_stack` | The services of the application, their order and their private network. For one image it describes a single service |
| `compatibility` | The Compose keys that were understood and the blockers left |
| `proxmox.adaptations` | Each difference with Docker, its reason and its effect |
| `validation`, `lifecycle` | The state of each test and how updates are detected |

What the author writes always wins over what is added.

## Writing and testing an oci-compose

1. **Write the file.** Start from one of the [`examples/`](examples/) or from the smallest file above, and add the blocks the application needs. Any file of `catalog/apps/` or `catalog/curated/` is also a valid starting point.
2. **Take it to the node.** It can be pasted in the terminal, copied to the node, for example to `/root/oci-compose.json`, or published where the node can download it.
3. **Open OCI manager Apps** from the ProxMenux menu and choose *Install an image that is not in the catalog*.
4. **Choose how it is given**: *Paste an oci-compose in the terminal*, *Read an oci-compose from a file of this host* or *Download an oci-compose from an address*.
5. **Read the result.** A file with errors is not installed, and each error names the field:

   ```
   The oci-compose has errors:
     container_contract/ports: array
     container_contract/volumes/3/container_path: required
     first_run/endpoints/0: 'label' is a required property
   ```

   A file that is not valid JSON reports the line and the column of the fault.
6. **Review.** A valid file shows what it installs: image, web address, ports, persistent paths, the variables the installation asks for and the files it writes. The image is looked up in its registry, and its architectures are listed. Answering no leaves the node untouched.
7. **Install** with default or advanced settings. The installation is the one of any application of the catalog.
8. **Adjust.** Remove the test installation from *Manage installed OCI applications*, edit the file and read it again.

An oci-compose decides what is mounted and with which privileges, so the review says it before installing. Install only files that come from a source you trust.

The record of an installation, `/usr/local/share/proxmenux/oci/instances/<VMID>/oci-compose.json`, can be read the same way: only its `template` block is used, as it was installed, and none of the answers of that installation. That record also holds the values typed during the installation, passwords included, so it is not a file to publish as it is.

The checks of the engine run with:

```bash
cd oci
python3 -m unittest discover -s tests -p 'test_*.py'
```

`tests/test_install_from_oci_compose.py` checks, among other things, that the two files of `examples/` install what the catalog installs.

## Adding an application to the catalog

An application reaches the catalog in three steps.

1. **Suggest it** in the thread [Suggest an application for the OCI catalog](https://github.com/MacRimi/ProxMenux/discussions/440) with the image, the registry it is published in and the category.
2. **Try it.** Installing it from its Compose file or its `docker run` command shows whether the image runs as a native LXC. When it needs something Compose cannot say, an oci-compose written by hand lets that be tested as well. The file that worked, attached to the suggestion, is what the entry of the catalog is written from.
3. **Validate it.** An application tested for real is recorded in `catalog/verification.json` and shown as verified in the installer. [VALIDATION.md](VALIDATION.md) lists the verified applications and describes a test: install, check that it works, restart, update and remove.

---

The sections that follow are the design and laboratory notes of the engine.

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

The catalog is generated rather than written by hand. A contributor adding an
application runs the orchestrator directly from this directory:

```bash
export PYTHONPATH=src
python3 -m proxmenux_oci sync
python3 -m proxmenux_oci list --filter sonarr
python3 -m proxmenux_oci generate sonarr
python3 -m proxmenux_oci show sonarr
GITHUB_TOKEN=github_pat_xxx python3 -m proxmenux_oci generate-all
```

`generate` writes one application's template from its published recipe; `show`
prints what the installation would create, which is the fastest way to see
whether a translation came out right before installing anything.

It needs `python3-yaml` and `python3-jsonschema`. On Debian and Proxmox both
are distribution packages; install them with APT before generating the catalog.

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

Before creating an LXC, the installer shows the installation summary with every
secret masked and asks for confirmation: `Install with this configuration?` in
the menu and `Install? [y/N]` in the `install` command. Remote credentials are
handled by normal SSH; they are never placed in a template or command argument.

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

Real tests are recorded in `catalog/verification.json`, which the catalog
reads when it loads and applies on top of the generated templates and the
overlays, so a new entry shows without regenerating and a regeneration keeps
it: `"status": "laboratory-validated"` for an application tested in the
ProxMenux lab, or `"community_tested": {"by": "<GitHub user>", "date":
"<YYYY-MM-DD>", "report": "<link to the report>"}` for one tested by the
community. Both show as verified in the OCI installer.

[VALIDATION.md](VALIDATION.md) lists the verified applications and explains
how to take part. It is generated from `catalog/verification.json` with
`python3 .github/scripts/oci_validation.py render`, and CI checks that it is
current.

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
`/etc/pve/proxmenux/host-monitor`. `/etc/pve/proxmenux` is the same on every node
of a cluster, unlike `/etc/pve/lxc`, which is the folder of the local node, so a
migrated container finds it. It is NOT included in a CT vzdump: copy it when
restoring outside the cluster, in addition to restoring managed volumes.
Installations made before this keep `/etc/pve/lxc/proxmenux-host-monitor`. Full restore/image replacement
have not been tested. No custom supervisor or image entrypoint is introduced.

DeepSeek OCR remains deferred at the user's request: registry inspection on
2026-09-14 found only `v2.2.0` for both IceWhaleTech images and no `latest` tag.
No fixed-version exception or deployment has been introduced.
