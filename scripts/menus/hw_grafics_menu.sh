#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
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

    while true; do
        OPTION=$(dialog --clear --backtitle "ProxMenux" --title "$(translate "GPUs and Coral-TPU Menu")" \
                        --menu "\n$(translate "Select an option:")" 20 70 8 \
                        "1" "$(translate "Add HW iGPU acceleration to an LXC")" \
                        "2" "$(translate "Add Coral TPU to an LXC")" \
                        "3" "$(translate "Install/Update Coral TPU on the Host")" \
                        "4" "$(translate "Return to Main Menu")" \
                        2>&1 >/dev/tty)

        case $OPTION in
            1)
                bash <(curl -s "$REPO_URL/scripts/configure_igpu_lxc.sh")
                if [ $? -ne 0 ]; then
                    return
                fi
                ;;
            2)
                bash <(curl -s "$REPO_URL/scripts/install_coral_lxc.sh")
                if [ $? -ne 0 ]; then
                    return
                fi
                ;;
            3)
                bash <(curl -s "$REPO_URL/scripts/install_coral_pve.sh")
                if [ $? -ne 0 ]; then
                    return
                fi
                ;;
            4) exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh") ;;
            *) exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh") ;;
        esac
    done
