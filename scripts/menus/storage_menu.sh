#!/bin/bash
# ==========================================================
# ProxMenux - Storage Menu
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 2.0
# Last Updated: 07/04/2026
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_SCRIPTS_DEFAULT="/usr/local/share/proxmenux/scripts"
LOCAL_SCRIPTS="$LOCAL_SCRIPTS_DEFAULT"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
if [[ -f "$LOCAL_SCRIPTS_LOCAL/utils.sh" ]]; then
    LOCAL_SCRIPTS="$LOCAL_SCRIPTS_LOCAL"
    UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
elif [[ ! -f "$UTILS_FILE" ]]; then
    UTILS_FILE="$BASE_DIR/utils.sh"
fi

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
load_language
initialize_cache

while true; do
    OPTION=$(dialog --colors --backtitle "ProxMenux" \
        --title "$(translate "Disk Manager")" \
        --menu "\n$(translate "Select an option:")" 24 78 16 \
            ""  "\Zb\Z4                           VM\Zn" \
            "1" "$(translate "Import Disk to VM")" \
            "2" "$(translate "Import Disk Image to VM")" \
            "3" "$(translate "Add Controller or NVMe PCIe to VM")" \
            ""  "" \
            ""  "\Zb\Z4                          LXC\Zn" \
            "4" "$(translate "Import Disk to LXC")" \
            ""  "" \
            ""  "\Z4────────────────────── Utilities ───────────────────────\Zn" \
            "5" "$(translate "Format / Wipe Physical Disk (Safe)")" \
            "6" "$(translate "SMART Disk Health & Test")" \
            "7" "$(translate "Manual CLI Guide (Disk and Storage Manager)")" \
            ""  "" \
            "0" "$(translate "Return to Main Menu")" \
            2>&1 >/dev/tty
    ) || { exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"; }

    case "$OPTION" in
        1)
            bash "$LOCAL_SCRIPTS/storage/disk-passthrough.sh"
            ;;
        2)
            bash "$LOCAL_SCRIPTS/storage/import-disk-image.sh"
            ;;
        3)
            bash "$LOCAL_SCRIPTS/storage/add_controller_nvme_vm.sh"
            ;;
        4)
            bash "$LOCAL_SCRIPTS/storage/disk-passthrough_ct.sh"
            ;;
        5)
            bash "$LOCAL_SCRIPTS/storage/format-disk.sh"
            ;;
        6)
            bash "$LOCAL_SCRIPTS/storage/smart-disk-test.sh"
            ;;
        7)
            bash "$LOCAL_SCRIPTS/storage/disk-storage-manual-guide.sh"
            ;;
        0)
            exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
            ;;
        *)
            exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
            ;;
    esac
done
