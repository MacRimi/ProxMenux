#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 2.0
# Last Updated: 04/04/2025
# ==========================================================

# Configuration ============================================
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache
# ==========================================================

if ! command -v dialog &>/dev/null; then
    apt update -qq >/dev/null 2>&1
    apt install -y dialog >/dev/null 2>&1
fi

show_menu() {
    local TEMP_FILE
    TEMP_FILE=$(mktemp)

    while true; do
        dialog --clear \
            --backtitle "ProxMenux" \
            --title "$(translate "Main ProxMenux")" \
            --menu "$(translate "Select an option:")" 20 70 10 \
            1 "$(translate "Settings post-install Proxmox")" \
            2 "$(translate "Help and Info Commands")" \
            3 "$(translate "Hardware: GPUs and Coral-TPU")" \
            4 "$(translate "Create VM from template or script")" \
            5 "$(translate "Disk and Storage Manager")" \
            6 "$(translate "Proxmox VE Helper Scripts")" \
            7 "$(translate "Network Management")" \
            8 "$(translate "Utilities and Tools")" \
            9 "$(translate "Settings")" \
            0 "$(translate "Exit")" 2>"$TEMP_FILE"

        local EXIT_STATUS=$?

        if [[ $EXIT_STATUS -ne 0 ]]; then
            # ESC pressed or Cancel
            clear
            msg_ok "$(translate "Thank you for using ProxMenux. Goodbye!")"
            rm -f "$TEMP_FILE"
            exit 0
        fi

        OPTION=$(<"$TEMP_FILE")

        case $OPTION in
            1) exec bash <(curl -s "$REPO_URL/scripts/menus/menu_post_install.sh") ;;
            2) bash <(curl -s "$REPO_URL/scripts/help_info_menu.sh") ;;
            3) exec bash <(curl -s "$REPO_URL/scripts/menus/hw_grafics_menu.sh") ;;
            4) exec bash <(curl -s "$REPO_URL/scripts/menus/create_vm_menu.sh") ;;
            5) exec bash <(curl -s "$REPO_URL/scripts/menus/storage_menu.sh") ;;
            6) exec bash <(curl -s "$REPO_URL/scripts/menus/menu_Helper_Scripts.sh") ;;
            7) exec bash <(curl -s "$REPO_URL/scripts/menus/network_menu.sh") ;;
            8) exec bash <(curl -s "$REPO_URL/scripts/menus/utilities_menu.sh") ;;
            9) exec bash <(curl -s "$REPO_URL/scripts/menus/config_menu.sh") ;;
            0) clear; msg_ok "$(translate "Thank you for using ProxMenu. Goodbye!")"; rm -f "$TEMP_FILE"; exit 0 ;;
            *) msg_warn "$(translate "Invalid option")"; sleep 2 ;;
        esac
    done
}



show_menu
