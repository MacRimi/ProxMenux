#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.1
# Last Updated: 15/04/2025
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
    OPTION=$(dialog --clear --backtitle "ProxMenux" --title "$(translate "Disk and Storage Manager Menu")" \
                    --menu "\n$(translate "Select an option:")" 20 70 10 \
                    "1" "$(translate "Add Disk") Passthrough $(translate "to a VM")" \
                    "2" "$(translate "Add Disk") Passthrough $(translate "to a LXC")" \
                    "3" "$(translate "Import Disk Image to a VM")" \
                    "4" "$(translate "Return to Main Menu")" \
                    2>&1 >/dev/tty) 

    case $OPTION in
        1)  
            bash <(curl -s "$REPO_URL/scripts/storage/disk-passthrough.sh")
            ;;
        2)
            bash <(curl -s "$REPO_URL/scripts/storage/disk-passthrough_ct.sh")
            ;;
        3)
            bash <(curl -s "$REPO_URL/scripts/storage/import-disk-image.sh")
            ;;
        4)
            exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh")
            ;;
        *)
            exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh")
            ;;
    esac
done
