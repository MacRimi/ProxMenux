#!/bin/bash
# ==========================================================
# ProxMenux - Proxmox System Update
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Wrapper that detects the running Proxmox major version and
# delegates to the matching worker script:
#   - PVE 8 -> scripts/global/update-pve8.sh
#   - PVE 9 -> scripts/global/update-pve9_2.sh
# After the worker finishes, runs the post-update cleanup
# (apt-get autoremove + autoclean) and prompts for an immediate
# reboot if the kernel was updated or /var/run/reboot-required
# was created.
#
# Features (delegated to worker scripts):
#   - APT repository hygiene (Proxmox + Debian)
#   - Removal of duplicate / conflicting sources
#   - Switch to the no-subscription Proxmox repository
#   - Full apt update + dist-upgrade
#   - Installs essential packages if missing (zfsutils, chrony, ...)
#   - LVM / storage sanity checks and header repair
#   - Removes conflicting time-sync packages
#   - Post-update system cleanup
#   - Reboot prompt when kernel changed
# ==========================================================
#
# The goal of this script is to simplify and secure the update process for Proxmox,
# reduce manual intervention, and prevent common repository and package errors.
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

    if [[ "$pve_version" -ge 9 ]]; then
        show_proxmenux_logo
        msg_title "$(translate "$SCRIPT_TITLE")"
        bash "$LOCAL_SCRIPTS/global/update-pve9_2.sh"

    else
        show_proxmenux_logo
        msg_title "$(translate "Proxmox system update")"
        bash "$LOCAL_SCRIPTS/global/update-pve8.sh"

    fi


}



check_reboot() {
    NECESSARY_REBOOT=0

    if [ -f /var/run/reboot-required ]; then
        NECESSARY_REBOOT=1
    fi
    if grep -q "linux-image" "$log_file" 2>/dev/null; then
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

    





