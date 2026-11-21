# OCI application validation

<!-- Generated from oci/catalog/verification.json by .github/scripts/oci_validation.py. Do not edit by hand. -->

88 of 595 applications in the OCI catalog have been tested for real: 56 in the ProxMenux lab and 32 by the community. The OCI installer shows them as verified, with a ✓ in the lists.

Each test describes the scenario that was run and names the image it ran on. It does not cover every possible configuration of the application, and a newer image has not been tested until someone reports it.

## Taking part

Any application that is not listed here is open for testing.

1. Check the [ProxMenux Roadmap](https://github.com/users/MacRimi/projects/1) to see which applications someone is already testing. With access to the board, create a card for the application and move it to In progress while you test it.
2. Test the application with the OCI manager and fill in the [OCI validation report](https://github.com/MacRimi/ProxMenux/issues/new?template=oci-validation.yml). The report records the image and the exact scenario: install mode, storage, network and GPU.
3. A reviewer reads the report and comments `/validated` on it. The application is then added to this list with your GitHub user and shown as verified in the OCI installer, and the report is closed.

Reviewers are listed in [.github/oci-validation-reviewers](../.github/oci-validation-reviewers), and a reviewer does not validate their own report. A validation can also be added with a pull request that adds the entry to `oci/catalog/verification.json` and regenerates this file with `python3 .github/scripts/oci_validation.py render`; CI checks that the entry credits the author of the pull request.

An application that cannot be validated for a reason outside the tester's hands — hardware nobody has, something only Docker provides, a fix still pending in ProxMenux — moves to Blocked on the board, with a line saying why and what would make it worth trying again.

Questions and ideas about OCI testing go in [discussion #440](https://github.com/MacRimi/ProxMenux/discussions/440).

## Tested by the community

| Application | Tested by | Date | Image | Scenario | Report |
|---|---|---|---|---|---|
| Apache Guacamole | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `50484043eadd` | PVE 9.2 amd64/ZFS; default/advanced; browser login and real SSH; private guacd/DB; restart/Modify; 1.6 refresh and controlled rollback; four-member backup/restore/Manage; Remove/PBS cleanup; official image mirror verified. | — |
| Baserow | [@jcastro](https://github.com/jcastro) | 2026-11-08 | `d10301e2dc5e` | PVE 9.2 amd64/ZFS; default/advanced static IPv4; browser login/workspace; 256 MiB upload SHA, no OOM; 512 MiB /tmp; delayed restarts/Modify; managed 3-CT backup/restore/Manage; host data. Tested with #619/#620; other architectures/storage untested. | — |
| Dispatcharr | [@jcastro](https://github.com/jcastro) | 2026-11-21 | `3716ebb0aba1` | PVE 9.2.32 amd64/ZFS; default/advanced, Chrome login, channel group/reboot, in-place Modify, cold restore/Manage, same-digest no-op and 0.34.0 to 0.34.1 update preserved data, resources, MAC/IP and storage. PostgreSQL, Redis and Daphne remained on loopback. | — |
| Ente Photos | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `5224466c15f7` | PVE 9.2 amd64/ZFS; default/advanced; browser page, real OTP auth and Museum-configured S3; managed/host data; restart/Modify; cached refresh and automatic readiness rollback; five-CT backup/restore/Manage. S3 host data external; browser password/SRP and uploads not tested. | — |
| GitLab CE | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `60fc37e470ac` | PVE 9.2 amd64/ZFS; default/advanced managed storage; browser/root login; restart; CPU/RAM/timezone Modify; cached recreation; native failed-candidate recovery; backup/restore/Manage; Remove/PBS audit. Host-bind not offered. CLI trigger and cross-release upgrades not E2E-tested. | — |
| Glances | [@Vaso73](https://github.com/Vaso73) | 2026-09-27 | — | — | [Report](https://github.com/MacRimi/ProxMenux/discussions/392#discussioncomment-18623868) |
| HolyArrs | [@jcastro](https://github.com/jcastro) | 2026-11-11 | `112c3f03d8ce` | PVE 9.2 amd64/ZFS; default/advanced/PUID/PGID, managed/host media; owner login, Chrome setup/Explore/movie details and metadata; restart/Modify; 1.0.18 to 1.0.19/no-op; backup/restore/Manage and readiness rollback. Fresh install validates automatic DNS files. Downloads/playback/ARM not tested. | — |
| Jellystat | [@jcastro](https://github.com/jcastro) | 2026-11-21 | `e61c759ec706` | PVE 9.2.32 amd64/ZFS; default/advanced, private PostgreSQL, Chrome and login. Reboot, CPU/RAM Modify, host-bind app backup, native backup/restore of both CTs into OCI Manage and same-digest stack Update passed. Changed digest and rollback were not exercised. | — |
| Joplin Server | [@jcastro](https://github.com/jcastro) | 2026-11-21 | `e99c6fe49c78` | PVE 9.2.32 amd64/ZFS; default/advanced, Chrome admin login, API and profile edit, private PostgreSQL. Dependency-first restart and cold two-CT restore/Manage kept access and profile. CPU/RAM Modify and stock same-digest Update kept both native configs; Remove/PBS checked. | — |
| Lastboard | [@jcastro](https://github.com/jcastro) | 2026-11-06 | `33501ce2e281` | PVE 9.2/amd64/ZFS: default/advanced OCI-compose install; browser login; managed/host data, PUID/PGID, restart, Modify, 1.10.1 to 1.10.2 update, failed-health rollback, managed backup/restore to new VMID/Manage, removal. ARM64 manifest only; optional integrations untested. | — |
| listmonk | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `7fb5a41120ab` | PVE 9.2 amd64/ZFS; default/advanced; generated login, lists/media; managed/host data; restart/Modify; 6.1 to 6.2 and controlled rollback using verified official cached images; full-group backup/restore/Manage; Remove/PBS cleanup. | — |
| macOS | [@jcastro](https://github.com/jcastro) | 2026-11-08 | `08d1bcaac74a` | PVE 9.2 Intel amd64/ZFS; Sequoia Recovery, KVM/browser, guest HTTPS and APFS file; default/advanced, managed/host storage; restart/CPU-RAM Modify; 3.11 to 3.12, backup/restore/Manage and readiness rollback. Full desktop installation/login, AMD and GPU not tested. | — |
| miniserve | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `70de52ea4754` | PVE 9.2/amd64/ZFS: default/advanced; browser and HTTP files; managed/host persistence, restart, Modify; 0.34.0 to 0.35.0 update/no-op/rollback; managed backup/restore to new VMID/Manage; Remove. ARM64 manifest only; optional authentication untested. | — |
| netboot.xyz | [@jcastro](https://github.com/jcastro) | 2026-11-21 | `a3af92f8447d` | PVE 9.2.32 amd64/ZFS; clean DHCP install retried DNS and downloaded menus once. HTTP 200 and TFTP worked after reboot with identical files and timestamps. Prior isolated SeaBIOS PXE reached Debian 13 installer; host-bind, same-digest update and Remove passed. | — |
| OpenProject | [@jcastro](https://github.com/jcastro) | 2026-11-21 | `2d9a77fd8b77` | PVE 9.2.32 amd64/ZFS; default/advanced, admin reset, project/task and host-bind attachment, loopback-only internal ports. Restart, CPU/RAM Modify, stock same-digest Update and cold restore/Manage preserved project/attachment and restarted PostgreSQL with corrected permissions. | — |
| PeerTube | [@jcastro](https://github.com/jcastro) | 2026-11-20 | `8baefef245da` | PVE 9.2.32 amd64/ZFS; advanced install, 32 GiB data, Redis 8 auth and rejected invalid hostnames; HTTPS via Caddy with verified local CA and default proxy trust; admin login, private upload/HLS; cold backup and Manage restore to new IDs, same HTTPS origin, login, media and Redis auth. | — |
| Plik | [@jcastro](https://github.com/jcastro) | 2026-11-21 | `7b450ff320b3` | PVE amd64/ZFS; native install, Chrome, anonymous upload/download confirmed, managed and host volumes, restart, CPU/RAM Modify and same-image no-op. Verified-cache upgrade kept data and settings; cold restore adopted in OCI Manage and served the same upload. | — |
| PocketBase | [@Vaso73](https://github.com/Vaso73) | 2026-09-27 | — | — | [Report](https://github.com/MacRimi/ProxMenux/discussions/392#discussioncomment-18623868) |
| Rallly | [@jcastro](https://github.com/jcastro) | 2026-11-21 | `2c35b8ec567a` | PVE amd64/ZFS; private PostgreSQL 18, SMTP OTP in Chrome, allowlist rejected a nonmatching email, initial admin claimed the role, support email configured. Prior poll persisted through restart, in-place Modify, cold restore and same-image update. | — |
| Recyclarr | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `1a8370c4e830` | PVE 9.2/amd64/ZFS: default/advanced OCI-compose; cron/CLI and sync to temporary Radarr; managed/host persistence, UID 1000, restart, Modify; 8.7.3 to 8.8.1 update/no-op/rollback; managed backup/restore to new VMID/Manage; Remove. Internet required. ARM64 manifest only. | — |
| Restreamer | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `9bced1da8a42` | PVE 9.2/amd64/ZFS: default/advanced; browser/API login; config/media persistence, restart, Modify; 2.11.0 to 2.12.0 update (served JS changed), no-op/rollback; managed backup/restore to new VMID/Manage; Remove. ARM64 manifest only; GPU/publishing untested. | — |
| Roundcube | [@jcastro](https://github.com/jcastro) | 2026-11-21 | `47f63977a1a1` | PVE amd64/ZFS; default setup asked for IMAP/SMTP ports and applied SSL 993/465. Real 1.7.5 to 1.7.6 update retained the generated DES key and endpoints. Earlier browser mail login/read/send, SQLite and restore verified with the disposable mail fixture. | — |
| Seafile CE | [@jcastro](https://github.com/jcastro) | 2026-11-20 | `fe1f111e93f8` | PVE 9.2 amd64/ZFS: default/advanced; active Go file server, browser/API and byte-exact transfers; managed/host storage, restart/Modify; 13.0.29 to 13.0.30 and no-op; backup/restore of all three CTs into Manage; cleanup and PBS check. Host bind stored separately. | — |
| Semaphore UI | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `426816c986cc` | PVE 9.2 amd64/ZFS; default and advanced; managed/host persistence; browser login; restart/Modify; 2.19.16 to 2.19.17; rollback; backup/restore/Manage; removal and PBS cleanup. | — |
| Shlink | [@jcastro](https://github.com/jcastro) | 2026-11-21 | `248d38c8d7fd` | PVE 9.2.32 amd64/ZFS; default/advanced, private PostgreSQL 18, generated key and real link/redirect. Reboot, cold two-CT restore/Manage, writable restored DB, CPU/RAM Modify and stock same-digest Update passed. Remove/disks/PBS checked. | — |
| Snipe-IT | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `2917d721b97e` | PVE 9.2 amd64/ZFS; default/advanced; browser login and inventory; managed/host uploads; restart/Modify; native 8.8.2 to 8.8.3; rollback; full-group backup/restore/Manage; removal/PBS cleanup. | — |
| StopLiga | [@jcastro](https://github.com/jcastro) | 2026-11-08 | `9332aa8ad286` | PVE 9.2 amd64/ZFS; UniFi dry-run authentication/health; default/advanced, managed data, restart/Modify, 0.1.29 to 0.1.30, rollback, backup/restore/Manage and removal. No router writes or arm64 runtime test. | — |
| TeslaMate | [@jcastro](https://github.com/jcastro) | 2026-10-29 | `c85b3d447502` | MS03/amd64: default and advanced install, browser login, volumes/restart, Modify, 4.3 to 4.4 update, controlled rollback, native backup/restore to new VMIDs and removal. No vehicle tokens used. | — |
| Tunarr | [@jcastro](https://github.com/jcastro) | 2026-11-21 | `50919e89db8c` | PVE 9.2.32 amd64/ZFS; default/advanced, Chrome and FFmpeg. The managed SQLite DB and a real channel survived reboot, CPU/RAM Modify, same-digest Update, a 2026.11.1→2026.11.2 image upgrade and cold backup/restore to another VMID in OCI Manage. | — |
| Unmanic | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `b249cba0d773` | PVE 9.2/amd64/ZFS: default/advanced; browser/API; managed/host library, UID/GID 1000/1001, restart, FFmpeg CPU encode, Modify; 0.4.0 to 0.4.1 update/no-op/rollback; managed backup/restore to new VMID/Manage; Remove. ARM64 manifest only; GPU/full plugin flows untested. | — |
| Wizarr | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `5e1b78572088` | PVE 9.2/amd64/ZFS: default and advanced OCI-compose; browser admin login; managed/host data, UID/GID, restart, Modify; 2026.10.0 to 2026.10.1 update/no-op/rollback; managed backup/restore to new VMID/Manage; Remove. ARM64 manifest only; media integrations untested. | — |
| YOURLS | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `774dc1d1f421` | PVE 9.2 amd64/ZFS; default/advanced; browser login and redirect; managed/host data; restart/Modify; live coordinated update; controlled rollback with verified cached images; whole-group backup/restore/Manage; Remove/PBS cleanup. | — |

## Tested in the ProxMenux lab

| Application | Category |
|---|---|
| 2FAuth | Authentication & Security |
| AdGuard Home | Adblock & DNS |
| AdGuard Home Sync | Adblock & DNS |
| Alby Hub ✨ | Finance & Budgeting |
| Alist | Files & Sharing |
| aMule | Downloads |
| Authentik | Authentication & Security |
| ChromeOS Flex | Browsers & Web Desktops |
| Chromium | Browsers & Web Desktops |
| CodeProject.AI Server | AI |
| CopyParty | Files & Sharing |
| Crafty | Gaming & Leisure |
| ddclient | Adblock & DNS |
| Duplicati | Backup & Recovery |
| Etherpad | Documents & Notes |
| FileBrowser Quantum | Files & Sharing |
| FlareSolverr | *Arr Suite |
| FlexGet | *Arr Suite |
| Frigate | NVR & Cameras |
| Grafana | Monitoring & Analytics |
| HAOS One | IoT & Smart Home |
| Immich | Media |
| JDownloader | Downloads |
| Jenkins CI/CD | AI / Coding & Dev-Tools |
| Linkwarden | Documents & Notes |
| MariaDB | Databases |
| Memos | Documents & Notes |
| Mindwtr | Productivity & Workflows |
| MineOS | Gaming & Leisure |
| Motioneye | NVR & Cameras |
| Navidrome | Media & Streaming |
| Nextcloud | Productivity & Workflows |
| Nextcloud + PostgreSQL | Productivity & Workflows |
| OpenList | Files & Sharing |
| OpenSSH Server | Remote Access & VPN |
| Paperless-ngx | Productivity & Workflows |
| phpMyAdmin | Databases |
| Prowlarr | *Arr Suite |
| Proxmox Backup Server | Backup & Recovery |
| Proxmox Datacenter Manager | Host Management |
| Proxmox Mail Gateway | Authentication & Security |
| qBittorrent | Downloads |
| Rclone WebUI | Backup & Recovery |
| Real-Debrid Torrent Client | Downloads |
| Scanopy | Network & Firewall |
| ShareCoveX | Files & Sharing |
| SnapOtter | Media & Streaming |
| Sonarr | *Arr Suite |
| Tandoor Recipes | Productivity & Workflows |
| The Lounge | Communication & Community |
| Trilium | Documents & Notes |
| Vaultwarden | Authentication & Security |
| Vikunja | Productivity & Workflows |
| Windows | Browsers & Web Desktops |
| WireGuard | Remote Access & VPN |
| WireGuard Easy | Remote Access & VPN |
