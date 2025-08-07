#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 04/07/2025
# ==========================================================
# Description:
# This script safely updates your Proxmox VE system and underlying Debian packages
# through an interactive and automated process.
#
# Main features:
# - Repairs and optimizes APT repositories (Proxmox & Debian)
# - Removes duplicate or conflicting sources
# - Switches to the recommended 'no-subscription' Proxmox repository
# - Updates all Proxmox and Debian system packages
# - Installs essential packages if missing (e.g., zfsutils, chrony)
# - Checks for LVM and storage issues and repairs headers if needed
# - Removes conflicting time sync packages automatically
# - Performs a system cleanup after updating (autoremove, autoclean)
# - Provides a summary and prompts for reboot if necessary
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

# ==========================================================

NECESSARY_REBOOT=1

apt_upgrade() {
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

    if [[ -z "$pve_version" ]]; then
        msg_error "Unable to detect Proxmox version."
        return 1
    fi

    if [[ "$pve_version" -ge 9 ]]; then

        bash <(curl -fsSL "$REPO_URL/scripts/global/update-pve.sh")
        show_proxmenux_logo
        msg_title "$(translate "Proxmox system update")"
    else

        bash <(curl -fsSL "$REPO_URL/scripts/global/update-pve8.sh")
        show_proxmenux_logo
        msg_title "$(translate "Proxmox system update")"
    fi


}

apt_upgrade

    
    if [[ "$NECESSARY_REBOOT" -eq 1 ]]; then
        if command -v whiptail >/dev/null 2>&1; then
            if whiptail --title "$(translate "Reboot Required")" \
                       --yesno "$(translate "Some changes require a reboot to take effect. Do you want to restart now?")" 10 60; then
                
                msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
                apt-get -y autoremove >/dev/null 2>&1
                apt-get -y autoclean >/dev/null 2>&1
                msg_ok "$(translate "Cleanup finished")"
                
                msg_success "$(translate "Press Enter to continue...")"
                read -r
                
                msg_warn "$(translate "Rebooting the system...")"
                reboot
            else
                msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
                apt-get -y autoremove >/dev/null 2>&1
                apt-get -y autoclean >/dev/null 2>&1
                msg_ok "$(translate "Cleanup finished")"
                
                msg_info2 "$(translate "You can reboot later manually.")"
                msg_success "$(translate "Press Enter to continue...")"
                read -r
                return 0
            fi
        else
            # Fallback without whiptail
            echo "$(translate "Reboot now? (y/N): ")"
            read -r -t 30 response
            if [[ "$response" =~ ^[Yy]$ ]]; then
                msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
                apt-get -y autoremove >/dev/null 2>&1
                apt-get -y autoclean >/dev/null 2>&1
                msg_ok "$(translate "Cleanup finished")"
                
                msg_warn "$(translate "Rebooting the system...")"
                sleep 3
                reboot
            else
                msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
                apt-get -y autoremove >/dev/null 2>&1
                apt-get -y autoclean >/dev/null 2>&1
                msg_ok "$(translate "Cleanup finished")"
                
                msg_info2 "$(translate "You can reboot later manually.")"
                return 0
            fi
        fi
    else
        msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
        apt-get -y autoremove >/dev/null 2>&1
        apt-get -y autoclean >/dev/null 2>&1
        msg_ok "$(translate "Cleanup finished")"
        
        msg_success "$(translate "All changes applied. No reboot required.")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
    fi
    

}


