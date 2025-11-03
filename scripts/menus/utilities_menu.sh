#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 02/07/2025
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
        OPTION=$(dialog --clear --backtitle "ProxMenux" --title "$(translate "Utilities Menu")" \
                        --menu "$(translate "Select an option:")" 20 70 8 \
                        "1" "$(translate "UUp Dump ISO creator Custom")" \
                        "2" "$(translate "System Utilities Installer")" \
                        "3" "$(translate "Proxmox System Update")" \
                        "4" "$(translate "Upgrade PVE 8 to PVE 9")" \
                        "5" "$(translate "Return to Main Menu")" \
                        2>&1 >/dev/tty)

        case $OPTION in
            1)
                bash "$LOCAL_SCRIPTS/utilities/uup_dump_iso_creator.sh"
                if [ $? -ne 0 ]; then
                    return
                fi
                ;;
            2)
                bash "$LOCAL_SCRIPTS/utilities/system_utils.sh"
                if [ $? -ne 0 ]; then
                    return
                fi
                ;;
            3)
                proxmox_update_msg="\n"
                proxmox_update_msg+="$(translate "This script will update your Proxmox VE system with advanced options:")\n\n"
                proxmox_update_msg+="• $(translate "Repairs and optimizes repositories")\n"
                proxmox_update_msg+="• $(translate "Cleans duplicate or conflicting sources")\n"
                proxmox_update_msg+="• $(translate "Switches to the free no-subscription repository")\n"
                proxmox_update_msg+="• $(translate "Updates all Proxmox and Debian packages")\n"
                proxmox_update_msg+="• $(translate "Installs essential packages if missing")\n"
                proxmox_update_msg+="• $(translate "Checks for LVM and storage issues")\n"
                proxmox_update_msg+="• $(translate "Performs automatic cleanup after updating")\n\n"
                proxmox_update_msg+="$(translate "Do you want to proceed and run the Proxmox System Update?")"

                dialog --colors --backtitle "ProxMenux" --title "$(translate "Proxmox System Update")" \
                    --yesno "$proxmox_update_msg" 20 70

                dialog_result=$?
                if [[ $dialog_result -eq 0 ]]; then
                    bash "$LOCAL_SCRIPTS/utilities/proxmox_update.sh"
                    if [ $? -ne 0 ]; then
                        return
                    fi
                fi
                ;;
            4)
                bash "$LOCAL_SCRIPTS/utilities/upgrade_pve8_to_pve9.sh"
                if [ $? -ne 0 ]; then
                    return
                fi
                ;;    
            5) exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh" ;;
            *) exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh" ;;
        esac
    done
    