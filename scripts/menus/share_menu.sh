#!/bin/bash
# ==========================================================
# ProxMenux - Storage & Share Manager Menu
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.2
# ==========================================================
# Description:
# Dispatcher for the Storage & Share Manager menu. Two blocks:
# HOST (register external or local storage as Proxmox storage,
# plus the local shared directory helper) and LXC (bind mount
# manager, NFS / Samba client and server for privileged CTs).
# ==========================================================

# Configuration
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
    OPTION=$(dialog --colors --backtitle "ProxMenux" \
        --title "$(translate "Storage & Share Manager")" \
        --menu "\n$(translate "Select an option:")" 28 78 17 \
            "" "\Z4──────────────────────── HOST ─────────────────────────\Zn" \
            "1"         "$(translate "Add NFS share    as Proxmox Storage")" \
            "2"         "$(translate "Add Samba share  as Proxmox Storage")" \
            "3"         "$(translate "Add iSCSI Target as Proxmox Storage")" \
            "4"         "$(translate "Add Local Disk   as Proxmox Storage")" \
            ""          "" \
            ""  "\Z4─────────────── Host-only resources ──────────────────\Zn" \
            "5"         "$(translate "Add Shared Directory on Host")" \
            ""          "" \
            ""  "\Z4──────────────────────── LXC ─────────────────────────\Zn" \
            "6"         "$(translate "Configure LXC Mount Points    (Host ↔ Container)")" \
            ""          "" \
            "7"         "$(translate "Configure NFS   Client in LXC (only privileged)")" \
            "8"         "$(translate "Configure Samba Client in LXC (only privileged)")" \
            "9"         "$(translate "Configure NFS   Server in LXC (only privileged)")" \
            "10"        "$(translate "Configure Samba Server in LXC (only privileged)")" \
            ""          "" \
            "h"         "$(translate "Help & Info (commands)")" \
            "0"         "$(translate "Return to Main Menu")" \
            2>&1 >/dev/tty
    ) || { exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"; }

    case "$OPTION" in

        lxctitle|hosttitle)
            continue
            ;;

        1)
            bash "$LOCAL_SCRIPTS/share/nfs_host.sh"
            ;;
        2)
            bash "$LOCAL_SCRIPTS/share/samba_host.sh"
            ;;
        3)
            bash "$LOCAL_SCRIPTS/share/iscsi_host.sh"
            ;;
        4)
            bash "$LOCAL_SCRIPTS/share/disk_host.sh"
            ;;
        5)
            bash "$LOCAL_SCRIPTS/share/local-shared-manager.sh"
            ;;
        6)
            bash "$LOCAL_SCRIPTS/share/lxc-mount-manager_minimal.sh"
            ;;
        7)
            bash "$LOCAL_SCRIPTS/share/nfs_client.sh"
            ;;
        8)
            bash "$LOCAL_SCRIPTS/share/samba_client.sh"
            ;;
        9)
            bash "$LOCAL_SCRIPTS/share/nfs_lxc_server.sh"
            ;;
        10)
            bash "$LOCAL_SCRIPTS/share/samba_lxc_server.sh"
            ;;
        h)
            bash "$LOCAL_SCRIPTS/share/commands_share.sh"
            ;;
        0)
            exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
            ;;
        *)
            exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
            ;;
    esac
done
