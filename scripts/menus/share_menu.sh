#!/bin/bash
# ==========================================================
# ProxMenux - Network Storage Manager Menu
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT
# Version     : 1.2
# Last Updated: $(date +%d/%m/%Y)
# ==========================================================

# Configuration
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
    OPTION=$(dialog --clear --backtitle "ProxMenux" \
        --title "$(translate "Network Storage Manager")" \
        --menu "\n$(translate "Select an option:")" 25 80 15 \
        "1" "$(translate "Set up NFS Server in LXC")" \
        "2" "$(translate "Set up Samba Server in LXC")" \
        "3" "$(translate "Configure NFS Client in LXC")" \
        "4" "$(translate "Configure Samba Client in LXC")" \
        "5" "$(translate "Configure NFS Storage on Host (Proxmox)")" \
        "6" "$(translate "Configure Samba Storage on Host (Proxmox)")" \
        "7" "$(translate "Help & Info (commands)")" \
        "8" "$(translate "Return to Main Menu")" \
        2>&1 >/dev/tty)
    
    case $OPTION in
        1)
            bash <(curl -s "$REPO_URL/scripts/share/nfs.sh")
            ;;
        2)
            bash <(curl -s "$REPO_URL/scripts/share/samba.sh")
            ;;
        3)
            bash <(curl -s "$REPO_URL/scripts/share/nfs_client.sh")
            ;;
        4)
            bash <(curl -s "$REPO_URL/scripts/storage/samba_client.sh")
            ;;
        5)
            bash <(curl -s "$REPO_URL/scripts/storage/nfs_host.sh")
            ;;
        6)
            bash <(curl -s "$REPO_URL/scripts/storage/samba_host.sh")
            ;;
        7)
            bash <(curl -s "$REPO_URL/scripts/storage/commands_share.sh")
            ;;
        8)
            exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh")
            ;;
        *)
            exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh")
            ;;
    esac
done
