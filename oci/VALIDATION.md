# OCI application validation

<!-- Generated from oci/catalog/verification.json by .github/scripts/oci_validation.py. Do not edit by hand. -->

42 of 336 applications in the OCI catalog have been tested for real: 40 in the ProxMenux lab and 2 by the community. The OCI installer shows them as verified, with a ✓ in the lists.

Each test describes the scenario that was run and names the image it ran on. It does not cover every possible configuration of the application, and a newer image has not been tested until someone reports it.

## Taking part

Any application that is not listed here is open for testing.

1. Check the [ProxMenux Roadmap](https://github.com/users/MacRimi/projects/1) to see which applications someone is already testing. With access to the board, create a card for the application and move it to In progress while you test it.
2. Test the application with the OCI manager and fill in the [OCI validation report](https://github.com/MacRimi/ProxMenux/issues/new?template=oci-validation.yml). The report records the image and the exact scenario: install mode, storage, network and GPU.
3. A reviewer reads the report and comments `/validated` on it. The application is then added to this list with your GitHub user and shown as verified in the OCI installer, and the report is closed.

Reviewers are listed in [.github/oci-validation-reviewers](../.github/oci-validation-reviewers), and a reviewer does not validate their own report. A validation can also be added with a pull request that adds the entry to `oci/catalog/verification.json` and regenerates this file with `python3 .github/scripts/oci_validation.py render`; CI checks that the entry credits the author of the pull request.

An application that cannot be validated for a reason outside the tester's hands — hardware nobody has, something only Docker provides, a fix still pending in ProxMenux — moves to Blocked on the board, with a line saying why and what would make it worth trying again.

Questions and ideas about OCI testing go in [discussion #360](https://github.com/MacRimi/ProxMenux/discussions/360).

## Tested by the community

| Application | Tested by | Date | Image | Scenario | Report |
|---|---|---|---|---|---|
| Glances | [@Vaso73](https://github.com/Vaso73) | 2026-09-27 | — | — | [Report](https://github.com/MacRimi/ProxMenux/discussions/392#discussioncomment-18623868) |
| PocketBase | [@Vaso73](https://github.com/Vaso73) | 2026-09-27 | — | — | [Report](https://github.com/MacRimi/ProxMenux/discussions/392#discussioncomment-18623868) |

## Tested in the ProxMenux lab

| Application | Category |
|---|---|
| 2FAuth | Authentication & Security |
| AdGuard Home | Adblock & DNS |
| Adguardhome Sync | Adblock & DNS |
| Alby Hub ✨ | Finance & Budgeting |
| Alist | Productivity & Workflows |
| aMule | Files & Downloads |
| Chromium | Browsers & Web Desktops |
| CodeProject.AI Server | AI |
| CopyParty | Files & Downloads |
| Crafty | Gaming & Leisure |
| Ddclient | Adblock & DNS |
| Duplicati | Backup & Recovery |
| Etherpad | Documents & Notes |
| FileBrowser Quantum | Tools |
| FlareSolverr | *Arr Suite |
| Flexget | *Arr Suite |
| Frigate | NVR & Cameras |
| Grafana | Monitoring & Analytics |
| Immich | Media |
| JDownloader | Files & Downloads |
| Jenkins CI/CD | AI / Coding & Dev-Tools |
| Linkwarden | Documents & Notes |
| Memos | Documents & Notes |
| MineOS | Gaming & Leisure |
| Motioneye | NVR & Cameras |
| Nextcloud | Productivity & Workflows |
| Nextcloud Stack | Productivity & Workflows |
| OpenList | Productivity & Workflows |
| Openssh Server | Remote Access & VPN |
| Paperless-ngx | Productivity & Workflows |
| Phpmyadmin | Databases |
| Qbittorrent | Files & Downloads |
| Rclone WebUI | Backup & Recovery |
| Real-Debrid Torrent Client | Files & Downloads |
| SnapOtter | Media & Streaming |
| Tandoor Recipes | Productivity & Workflows |
| Thelounge | Communication & Community |
| Trilium | Documents & Notes |
| Wireguard | Remote Access & VPN |
| WireGuard Easy | Remote Access & VPN |
