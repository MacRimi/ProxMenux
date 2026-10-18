#!/bin/bash
# ==========================================================
# ProxMenux - Proxmox Backup Server menu
# ==========================================================
# PBS exposes compatible host tools and its own post-install profile;
# PVE guest optimizations stay in the PVE menu.
# ==========================================================
BASE_DIR="/usr/local/share/proxmenux"
LOCAL_SCRIPTS="$BASE_DIR/scripts"
source "$BASE_DIR/utils.sh"
source "$LOCAL_SCRIPTS/global/platform-functions.sh"
load_language
initialize_cache

if ! pmx_is_pbs; then
    msg_error "$(translate 'This menu requires Proxmox Backup Server.')"
    exit 1
fi

pbs_show() {
    local title="$1" output
    shift
    output=$(mktemp)
    if "$@" > "$output" 2>&1; then
        dialog --backtitle "ProxMenux" --title "$title" --textbox "$output" 24 110
    else
        dialog --backtitle "ProxMenux" --title "$(translate 'Command failed')" --textbox "$output" 24 110
    fi
    rm -f "$output"
}

while true; do
    choice=$(dialog --clear --backtitle "ProxMenux" --title "Proxmox Backup Server" \
        --menu "$(translate 'Select an option:')" 19 75 9 \
        1 "$(translate "Settings post-install Proxmox")" \
        2 "$(translate 'PBS version and packages')" \
        3 "$(translate 'PBS datastores')" \
        4 "$(translate 'Recent PBS tasks')" \
        5 "$(translate 'System Utilities Installer')" \
        6 "$(translate 'Update PBS using configured repositories')" \
        s "$(translate 'Settings')" \
        0 "$(translate 'Exit')" 2>&1 >/dev/tty) || break
    case "$choice" in
        1) exec bash "$LOCAL_SCRIPTS/menus/menu_post_install.sh" ;;
        2) pbs_show "$(translate 'PBS version and packages')" proxmox-backup-manager versions --verbose ;;
        3) pbs_show "$(translate 'PBS datastores')" proxmox-backup-manager datastore list ;;
        4) pbs_show "$(translate 'Recent PBS tasks')" proxmox-backup-manager task list --all true --limit 20 ;;
        5) bash "$LOCAL_SCRIPTS/utilities/system_utils.sh" ;;
        6) bash "$LOCAL_SCRIPTS/utilities/pbs_update.sh" ;;
        s) exec bash "$LOCAL_SCRIPTS/menus/config_menu.sh" ;;
        0) break ;;
    esac
done
clear
msg_ok "$(translate "Thank you for using ProxMenux. Goodbye!")"
