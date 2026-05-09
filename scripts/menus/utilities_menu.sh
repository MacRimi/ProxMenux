#!/bin/bash
# ==========================================================
# ProxMenux - Utilities Menu
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Dispatcher for the Utilities & Tools section. Six options that
# cover ISO creation, system utility installation, Proxmox updates,
# major-version upgrade (PVE 8 → 9) and VM portability (OVA / OVF).
#
# Features:
#   - UUP Dump ISO creator: build official Windows ISOs from UUP
#     Dump using a shared link.
#   - System Utilities Installer: 26 curated CLI tools (htop, btop,
#     iperf3, jq, tmux, ...) in custom-pick or predefined groups.
#   - Proxmox System Update: repos hygiene + apt update + apt
#     dist-upgrade with reboot prompt (delegates to per-version
#     worker scripts in global/).
#   - Upgrade PVE 8 to PVE 9: automated or interactive major-version
#     upgrade with pre-checks, repo migration and post-upgrade
#     validation. Manual guide alternative also exposed.
#   - Export VM to OVA / OVF: convert a Proxmox VM to a portable
#     OVA archive or OVF directory (VMware / VirtualBox / etc).
#   - Import VM from OVA / OVF: import a VMware / VirtualBox /
#     ProxMenux export back into Proxmox.
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
                        --menu "\n$(translate "Select an option:")" 20 70 11 \
                        "1" "$(translate "UUp Dump ISO creator Custom")" \
                        "2" "$(translate "System Utilities Installer")" \
                        "3" "$(translate "Proxmox System Update")" \
                        "4" "$(translate "Upgrade PVE 8 to PVE 9")" \
                        "5" "$(translate "Export VM to OVA or OVF")" \
                        "6" "$(translate "Import VM from OVA or OVF")" \
                        "7" "$(translate "Return to Main Menu")" \
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
            5)
                bash "$LOCAL_SCRIPTS/utilities/export_vm_ova_ovf.sh"
                if [ $? -ne 0 ]; then
                    return
                fi
                ;;
            6)
                bash "$LOCAL_SCRIPTS/utilities/import_vm_ova_ovf.sh"
                if [ $? -ne 0 ]; then
                    return
                fi
                ;;
            7) exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh" ;;
            *) exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh" ;;
        esac
    done
    
