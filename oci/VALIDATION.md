# OCI application validation

<!-- Generated from oci/catalog/verification.json by .github/scripts/oci_validation.py. Do not edit by hand. -->

75 of 579 applications in the OCI catalog have been tested for real: 56 in the ProxMenux lab and 19 by the community. The OCI installer shows them as verified, with a ✓ in the lists.

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
| Ente Photos | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `5224466c15f7` | PVE 9.2 amd64/ZFS; default/advanced; browser page, real OTP auth and Museum-configured S3; managed/host data; restart/Modify; cached refresh and automatic readiness rollback; five-CT backup/restore/Manage. S3 host data external; browser password/SRP and uploads not tested. | — |
| GitLab CE | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `60fc37e470ac` | PVE 9.2 amd64/ZFS; default/advanced managed storage; browser/root login; restart; CPU/RAM/timezone Modify; cached recreation; native failed-candidate recovery; backup/restore/Manage; Remove/PBS audit. Host-bind not offered. CLI trigger and cross-release upgrades not E2E-tested. | — |
| Glances | [@Vaso73](https://github.com/Vaso73) | 2026-09-27 | — | — | [Report](https://github.com/MacRimi/ProxMenux/discussions/392#discussioncomment-18623868) |
| Lastboard | [@jcastro](https://github.com/jcastro) | 2026-11-06 | `33501ce2e281` | PVE 9.2/amd64/ZFS: default/advanced OCI-compose install; browser login; managed/host data, PUID/PGID, restart, Modify, 1.10.1 to 1.10.2 update, failed-health rollback, managed backup/restore to new VMID/Manage, removal. ARM64 manifest only; optional integrations untested. | — |
| listmonk | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `7fb5a41120ab` | PVE 9.2 amd64/ZFS; default/advanced; generated login, lists/media; managed/host data; restart/Modify; 6.1 to 6.2 and controlled rollback using verified official cached images; full-group backup/restore/Manage; Remove/PBS cleanup. | — |
| macOS | [@jcastro](https://github.com/jcastro) | 2026-11-08 | `08d1bcaac74a` | PVE 9.2 Intel amd64/ZFS; Sequoia Recovery, KVM/browser, guest HTTPS and APFS file; default/advanced, managed/host storage; restart/CPU-RAM Modify; 3.11 to 3.12, backup/restore/Manage and readiness rollback. Full desktop installation/login, AMD and GPU not tested. | — |
| miniserve | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `70de52ea4754` | PVE 9.2/amd64/ZFS: default/advanced; browser and HTTP files; managed/host persistence, restart, Modify; 0.34.0 to 0.35.0 update/no-op/rollback; managed backup/restore to new VMID/Manage; Remove. ARM64 manifest only; optional authentication untested. | — |
| PocketBase | [@Vaso73](https://github.com/Vaso73) | 2026-09-27 | — | — | [Report](https://github.com/MacRimi/ProxMenux/discussions/392#discussioncomment-18623868) |
| Recyclarr | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `1a8370c4e830` | PVE 9.2/amd64/ZFS: default/advanced OCI-compose; cron/CLI and sync to temporary Radarr; managed/host persistence, UID 1000, restart, Modify; 8.7.3 to 8.8.1 update/no-op/rollback; managed backup/restore to new VMID/Manage; Remove. Internet required. ARM64 manifest only. | — |
| Restreamer | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `9bced1da8a42` | PVE 9.2/amd64/ZFS: default/advanced; browser/API login; config/media persistence, restart, Modify; 2.11.0 to 2.12.0 update (served JS changed), no-op/rollback; managed backup/restore to new VMID/Manage; Remove. ARM64 manifest only; GPU/publishing untested. | — |
| Semaphore UI | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `426816c986cc` | PVE 9.2 amd64/ZFS; default and advanced; managed/host persistence; browser login; restart/Modify; 2.19.16 to 2.19.17; rollback; backup/restore/Manage; removal and PBS cleanup. | — |
| Snipe-IT | [@jcastro](https://github.com/jcastro) | 2026-11-07 | `2917d721b97e` | PVE 9.2 amd64/ZFS; default/advanced; browser login and inventory; managed/host uploads; restart/Modify; native 8.8.2 to 8.8.3; rollback; full-group backup/restore/Manage; removal/PBS cleanup. | — |
| StopLiga | [@jcastro](https://github.com/jcastro) | 2026-11-08 | `9332aa8ad286` | PVE 9.2 amd64/ZFS; UniFi dry-run authentication/health; default/advanced, managed data, restart/Modify, 0.1.29 to 0.1.30, rollback, backup/restore/Manage and removal. No router writes or arm64 runtime test. | — |
| TeslaMate | [@jcastro](https://github.com/jcastro) | 2026-10-29 | `c85b3d447502` | MS03/amd64: default and advanced install, browser login, volumes/restart, Modify, 4.3 to 4.4 update, controlled rollback, native backup/restore to new VMIDs and removal. No vehicle tokens used. | — |
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
| aMule | Files & Downloads |
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
| JDownloader | Files & Downloads |
| Jenkins CI/CD | AI / Coding & Dev-Tools |
| Linkwarden | Documents & Notes |
| MariaDB | Databases |
| Memos | Documents & Notes |
| Mindwtr | Productivity & Workflows |
| MineOS | Gaming & Leisure |
| Motioneye | NVR & Cameras |
| Navidrome | Media & Streaming |
| Nextcloud | Productivity & Workflows |
| Nextcloud Stack | Productivity & Workflows |
| OpenList | Files & Sharing |
| OpenSSH Server | Remote Access & VPN |
| Paperless-ngx | Productivity & Workflows |
| phpMyAdmin | Databases |
| Prowlarr | *Arr Suite |
| Proxmox Backup Server | Backup & Recovery |
| Proxmox Datacenter Manager | Host Management |
| Proxmox Mail Gateway | Authentication & Security |
| qBittorrent | Files & Downloads |
| Rclone WebUI | Backup & Recovery |
| Real-Debrid Torrent Client | Files & Downloads |
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
