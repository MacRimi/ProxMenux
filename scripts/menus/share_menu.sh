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
    OPTION=$(dialog --colors --backtitle "ProxMenux" \
        --title "$(translate "Mount and Share Manager")" \
        --menu "\n$(translate "Select an option:")" 25 80 15 \
            "" "\Z4────────────────── $(translate "HOST") ───────────────────\Zn" \
            "1"         "$(translate "Configure NFS shared   on Host")" \
            "2"         "$(translate "Configure Samba shared on Host")" \
            "3"         "$(translate "Configure Local Shared on Host")" \
            ""  "\Z4────────────────── $(translate "LXC") ───────────────────\Zn" \
            "4"         "$(translate "Configure LXC Mount Points    (Host ↔ Container)")" \
            ""          "" \
            "5"         "$(translate "Configure NFS Client in LXC   (only privileged)")" \
            "6"         "$(translate "Configure Samba Client in LXC (only privileged)")" \
            "7"         "$(translate "Set up Samba Server in LXC    (only privileged)")" \
            ""          "" \
            "8"         "$(translate "Help & Info (commands)")" \
            "0"         "$(translate "Return to Main Menu")" \
            2>&1 >/dev/tty
    ) || { exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh"); }

    case "$OPTION" in

        lxctitle|hosttitle)
            continue
            ;;

        1)
            bash <(curl -s "$REPO_URL/scripts/share/nfs_host_auto.sh")
            ;;
        2)
            bash <(curl -s "$REPO_URL/scripts/share/samba_host.sh")
            ;;
        3)
            bash <(curl -s "$REPO_URL/scripts/share/local-shared-manager.sh")
            ;;    
        4)
            bash <(curl -s "$REPO_URL/scripts/share/lxc-mount-manager.sh")
            ;;
        5)
            bash <(curl -s "$REPO_URL/scripts/share/nfs_client.sh")
            ;;    
        6) 
            bash <(curl -s "$REPO_URL/scripts/share/samba_client.sh")
            ;;
        7)
            bash <(curl -s "$REPO_URL/scripts/share/samba.sh")
            ;;
        8)
            bash <(curl -s "$REPO_URL/scripts/share/commands_share.sh")
            ;;
        0)
            exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh")
            ;;
        *)
            exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh")
            ;;
    esac
done
