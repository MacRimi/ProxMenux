#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 28/01/2025
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


show_menu() {

while true; do
        OPTION=$(whiptail --title "$(translate "Main ProxMenux")" --menu "$(translate "Select an option:")" 18 70 10 \
            "1" "$(translate "Settings post-install Proxmox")" \
            "2" "$(translate "Hardware: GPUs and Coral-TPU")" \
            "3" "$(translate "Create VM from template or script")" \
            "4" "$(translate "Hard Drives, Disk Images, and Storage")" \
            "5" "$(translate "Essential Proxmox VE Helper-Scripts")" \
            "6" "$(translate "Network")" \
            "7" "$(translate "Settings")" \
            "8" "$(translate "Exit")" 3>&1 1>&2 2>&3)



    case $OPTION in
        1) exec bash <(curl -s "$REPO_URL/scripts/menus/menu_post_install.sh") ;;
        2) exec bash <(curl -s "$REPO_URL/scripts/menus/hw_grafics_menu.sh") ;;
        3) exec bash <(curl -s "$REPO_URL/scripts/menus/create_vm_menu.sh") ;;
        4) exec bash <(curl -s "$REPO_URL/scripts/menus/storage_menu.sh") ;;
        5) exec bash <(curl -s "$REPO_URL/scripts/menus/menu_Helper_Scripts.sh") ;;
        6) exec bash <(curl -s "$REPO_URL/scripts/repair_network.sh") ;;
        7) exec bash <(curl -s "$REPO_URL/scripts/menus/config_menu.sh") ;;
        8) clear; msg_ok "$(translate "Thank you for using ProxMenu. Goodbye!")"; exit 0 ;;
        *) msg_warn "$(translate "Invalid option")"; sleep 2 ;;
    esac
    
done
}

show_proxmenux_logo
show_menu

