#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 2.0
# Last Updated: 04/04/2025
# ==========================================================

# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"


if ! command -v dialog &>/dev/null; then
    apt update -qq >/dev/null 2>&1
    apt install -y dialog >/dev/null 2>&1
fi


# ==========================================================
# The legacy "PVE9 + googletrans incompatible" gate that used to live
# here has been removed along with the googletrans runtime. Translations
# are now a static lookup against $BASE_DIR/lang/<lang>.json — there is
# no runtime venv to be incompatible with any PVE version.

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi


if [[ "$PROXMENUX_PVE9_WARNING_SHOWN" = "1" ]]; then

    if ! load_language 2>/dev/null; then
        LANGUAGE="en"
    fi

else
    load_language
    initialize_cache
fi

# ==========================================================

show_menu() {
    local TEMP_FILE
    TEMP_FILE=$(mktemp)

    while true; do

        local menu_title="Main ProxMenux"

        dialog --clear \
            --backtitle "ProxMenux" \
            --title "$(translate "$menu_title")" \
            --menu "\n$(translate "Select an option:")" 21 70 12 \
            1 "$(translate "Settings post-install Proxmox")" \
            2 "$(translate "Hardware: GPUs and Coral-TPU")" \
            3 "$(translate "Create VM from template or script")" \
            4 "$(translate "Disk Manager")" \
            5 "$(translate "Storage & Share Manager")" \
            6 "$(translate "Proxmox VE Helper Scripts")" \
            7 "$(translate "Network Management")" \
            8 "$(translate "Security")" \
            9 "$(translate "Utilities and Tools")" \
            b "$(translate "Host Backup & Restore")" \
            h "$(translate "Help and Info Commands")" \
            s "$(translate "Settings")" \
            0 "$(translate "Exit")" 2>"$TEMP_FILE"

        local EXIT_STATUS=$?

        if [[ $EXIT_STATUS -ne 0 ]]; then
            clear
            msg_ok "$(translate "Thank you for using ProxMenux. Goodbye!")"
            rm -f "$TEMP_FILE"
            exit 0
        fi

        OPTION=$(<"$TEMP_FILE")

        case $OPTION in
            1) exec bash "$LOCAL_SCRIPTS/menus/menu_post_install.sh" ;;
            2) exec bash "$LOCAL_SCRIPTS/menus/hw_grafics_menu.sh" ;;
            3) exec bash "$LOCAL_SCRIPTS/menus/create_vm_menu.sh" ;;
            4) exec bash "$LOCAL_SCRIPTS/menus/storage_menu.sh" ;;
            5) exec bash "$LOCAL_SCRIPTS/menus/share_menu.sh" ;;
            6) exec bash "$LOCAL_SCRIPTS/menus/menu_Helper_Scripts.sh" ;;
            7) exec bash "$LOCAL_SCRIPTS/menus/network_menu.sh" ;;
            8) exec bash "$LOCAL_SCRIPTS/menus/security_menu.sh" ;;
            9) exec bash "$LOCAL_SCRIPTS/menus/utilities_menu.sh" ;;
            b) bash "$LOCAL_SCRIPTS/backup_restore/backup_host.sh" ;;
            h) bash "$LOCAL_SCRIPTS/help_info_menu.sh" ;;
            s) exec bash "$LOCAL_SCRIPTS/menus/config_menu.sh" ;;
            0) clear; msg_ok "$(translate "Thank you for using ProxMenux. Goodbye!")"; rm -f "$TEMP_FILE"; exit 0 ;;
            *) msg_warn "$(translate "Invalid option")"; sleep 2 ;;
        esac
    done
}

show_menu
