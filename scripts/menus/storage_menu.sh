#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.1
# Last Updated: 15/04/2025
# ==========================================================


# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
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
            bash "$LOCAL_SCRIPTS/storage/disk-passthrough.sh"
            ;;
        2)
            bash "$LOCAL_SCRIPTS/storage/disk-passthrough_ct.sh"
            ;;
        3)
            bash "$LOCAL_SCRIPTS/storage/import-disk-image.sh"
            ;;
        4)
            exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
            ;;
        *)
            exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
            ;;
    esac
done
