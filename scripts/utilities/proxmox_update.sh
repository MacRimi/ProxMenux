#!/bin/bash
# ==========================================================
# ProxMenux - Proxmox System Update
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.1
# ==========================================================
# Description:
# Update wrapper for a Proxmox host ALREADY in production.
# Delegates to `scripts/global/update-pve-safe.sh`, a non-
# invasive worker that only performs operations safe for a
# configured host — no repo overwriting, no service purging,
# no forced package installs. See the header of the worker
# for the full list of what it does and what it deliberately
# refuses to do.
#
# After the worker finishes this script:
#   - Runs apt-get autoremove + autoclean (final cleanup)
#   - Prompts for an immediate reboot when the kernel was
#     updated or /var/run/reboot-required was created
#
# NOTE: For a fresh Proxmox install use post_install
# (scripts/post_install/{auto,customizable}_post_install.sh),
# which invokes the aggressive `update-pve{8,9_2}.sh` workers
# that set up repositories and essentials from scratch.
# ==========================================================

BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

export SCRIPT_TITLE="Proxmox system update"

# ==========================================================

NECESSARY_REBOOT=1

# Suppress the Monitor's `service_fail` notifications while apt is running.
# PVE services (pve-cluster, pveproxy, pvedaemon, corosync…) get killed and
# restarted as part of the upgrade — those events are expected, not real
# failures. `notification_events.is_apt_active_on_host()` reads these
# markers; keep the names in sync between the two files.
_PROXMENUX_UPDATE_MARKER="/var/run/proxmenux-update-in-progress"
_PROXMENUX_UPDATE_FINISHED_MARKER="/var/run/proxmenux-update-just-finished"

_proxmenux_update_cleanup() {
    rm -f "$_PROXMENUX_UPDATE_MARKER"
    # Grace-window marker: journal events landing shortly after apt exits
    # (e.g. the pve-cluster restart) are still gated on this file's mtime.
    touch "$_PROXMENUX_UPDATE_FINISHED_MARKER"
}
trap _proxmenux_update_cleanup EXIT
touch "$_PROXMENUX_UPDATE_MARKER"

apt_upgrade() {
    local pve_version pve_raw
    # Capture both stdout and the rc so a failure is visible in the
    # error message — silent `2>/dev/null` previously hid the real cause
    # (binary missing / output malformed). Audit Tier 6 — `proxmox_update.sh`
    # detección de versión silenciosa.
    pve_raw=$(pveversion 2>&1)
    local pve_rc=$?
    pve_version=$(echo "$pve_raw" | grep -oP 'pve-manager/\K[0-9]+' | head -1)

    if [[ -z "$pve_version" ]]; then
        if (( pve_rc != 0 )); then
            msg_error "Unable to detect Proxmox version (pveversion exit $pve_rc): ${pve_raw:0:200}"
        else
            msg_error "Unable to parse Proxmox version from output: ${pve_raw:0:200}"
        fi
        return 1
    fi

    show_proxmenux_logo
    msg_title "$(translate "$SCRIPT_TITLE")"
    # Single worker for both PVE 8 and 9 — it detects the version itself
    # and only performs operations safe on a production host.
    bash "$LOCAL_SCRIPTS/global/update-pve-safe.sh"


}



check_reboot() {
    NECESSARY_REBOOT=0

    # Standard Debian mechanism — needs `needrestart` (or a package that
    # explicitly creates it in its postinst) to be present. Not shipped
    # by default on many PVE installs, so we complement with the kernel
    # fallback below.
    if [ -f /var/run/reboot-required ]; then
        NECESSARY_REBOOT=1
    fi

    # Fallback: compare the running kernel with the most recent
    # proxmox-kernel-* / pve-kernel-* installed. If a newer kernel package
    # is on disk but the box is still on the old one, a reboot is required
    # regardless of whether needrestart flagged it.
    local running_kernel newest_kernel
    running_kernel=$(uname -r)
    newest_kernel=$(
        dpkg-query -W -f='${Status}\t${Package}\n' 'proxmox-kernel-*-pve-signed' 'pve-kernel-*-pve' 2>/dev/null \
        | awk -F'\t' '/^install ok installed\t/ { print $2 }' \
        | sed -E 's/^(proxmox|pve)-kernel-//; s/-signed$//' \
        | sort -V \
        | tail -1
    )
    if [ -n "$newest_kernel" ] && [ "$newest_kernel" != "$running_kernel" ]; then
        NECESSARY_REBOOT=1
    fi

    if [[ "$NECESSARY_REBOOT" -eq 1 ]]; then
        if whiptail --title "$(translate "Reboot Required")" \
                    --yesno "$(translate "Some changes require a reboot to take effect. Do you want to restart now?")" 10 60; then

            msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
            apt-get -y autoremove >/dev/null 2>&1
            apt-get -y autoclean >/dev/null 2>&1
            msg_ok "$(translate "Cleanup finished")"
            echo -e
            msg_success "$(translate "Press Enter to continue...")"
            read -r

            msg_warn "$(translate "Rebooting the system...")"
            reboot
        else
            msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
            apt-get -y autoremove >/dev/null 2>&1
            apt-get -y autoclean >/dev/null 2>&1
            msg_ok "$(translate "Cleanup finished")"
            echo -e
            msg_info2 "$(translate "You can reboot later manually.")"
            echo -e
            msg_success "$(translate "Press Enter to continue...")"
            read -r
            return 0
        fi
    else
        msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
        apt-get -y autoremove >/dev/null 2>&1
        apt-get -y autoclean >/dev/null 2>&1
        msg_ok "$(translate "Cleanup finished")"
        echo -e
        msg_ok "$(translate "All changes applied. No reboot required.")"
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
    fi
}



apt_upgrade
check_reboot

    





