# Proxmox Backup Server support

ProxMenux detects PBS from the installed **proxmox-backup-server** package.
Installing proxmox-backup-client on PVE or another Debian system does not turn
that host into PBS. Supported maintenance platforms are PBS 3/Debian 12 and
PBS 4/Debian 13; PVE 8/9 detection remains separate. If both server products
are co-installed, PVE takes precedence.

## On a PBS host

The main CLI opens a PBS menu with package/version information, datastores,
recent tasks, the existing system-utility installer, settings and a PBS package
update. Utility installation preserves the operator's APT sources instead of
trying to find a PVE version or enabling PVE/Ceph repositories. Configure a
working subscription or no-subscription PBS repository in PBS itself if APT
reports an error.

The update refreshes configured indexes, displays the simulated full-upgrade
plan and requires confirmation before applying it. It does not run PVE repository
cleanup, major-version migration, kernel cleanup or guest scripts. The automatic
and customizable PVE post-install entry points reject PBS before adjustments.

Monitor opens a PBS dashboard with CPU, RAM, uptime, local PBS status,
datastores, recent tasks and maintenance schedules, plus logs, terminal and
Monitor authentication/HTTPS settings. PVE guest prewarmers, firewall controls
and guest-storage checks are not part of this dashboard. Health checks monitor
proxmox-backup and proxmox-backup-proxy rather than reporting absent PVE daemons.
Monitor can reuse the native PBS proxy.pem/proxy.key pair, including renewal.

Local data is read with proxmox-backup-manager JSON commands. Datastore capacity
is filesystem capacity, not the logical sum of backups; datastores sharing one
filesystem can show the same capacity. An unmounted removable datastore or a
failed check has unknown capacity, not zero/free space.

## Monitor a remote PBS from PVE

Open **Backup → Proxmox Backup Server → Manage PBS connections**. Enable local
Monitor authentication first, then add a named HTTPS endpoint (for example
https://pbs.example:8007), a dedicated API token ID (`user@pbs!monitor`) and its
secret. Give both the user and token the PBS **Audit** role on `/`, with
propagation, to view system tasks and datastore status. Token ACLs cannot exceed
the user's effective permissions. A restricted token may show only its permitted
data; denied sections are displayed as unavailable.

Use a CA-trusted certificate or copy the certificate's SHA256 fingerprint from
the PBS console/a trusted channel. With a pin, Monitor checks the peer certificate
before sending the token. With no pin, the normal system CA and hostname checks
apply. Connections go directly to the configured HTTPS endpoint and do not follow
redirects. A reverse-proxy prefix is supported; omit the port for HTTPS 443 or
include the native PBS port explicitly.

Saving tests an authenticated datastore-status endpoint. Secrets are stored
atomically with mode 0600 in `~/.config/proxmenux-monitor/pbs_servers.json`, never
returned by the API, and retained when the edit form's secret is left empty.
Connection changes require full administrator access; read-only Monitor API tokens
can read monitoring data but cannot change connections. Removing a connection
removes its saved credentials only. Monitoring does not start prune, garbage
collection, verification or sync jobs and does not modify PBS backups.

Status is cached for 15 seconds and the panel refreshes every 30 seconds. Task or
schedule permission failures are shown independently, without hiding successful
datastore data or presenting failed queries as empty healthy results.

References: [PBS command syntax](https://pbs.proxmox.com/docs/command-syntax.html),
[PBS API](https://pbs.proxmox.com/docs/api-viewer/index.html),
[PBS users, tokens and ACLs](https://pbs.proxmox.com/docs/user-management.html).
