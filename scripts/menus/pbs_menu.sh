#!/bin/bash
# PBS exposes compatible host tools; PVE guest/repository optimizations stay in the PVE menu.
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
    local output
    output=$(mktemp)
    if "$@" > "$output" 2>&1; then
        dialog --backtitle "ProxMenux · PBS" --title "Proxmox Backup Server" --textbox "$output" 24 100
    else
        dialog --backtitle "ProxMenux · PBS" --title "$(translate 'Command failed')" --textbox "$output" 24 100
    fi
    rm -f "$output"
}

while true; do
    choice=$(dialog --clear --backtitle "ProxMenux · PBS" --title "Proxmox Backup Server" \
        --menu "$(translate 'Select an option:')" 20 80 10 \
        status "$(translate 'PBS version and packages')" \
        stores "$(translate 'PBS datastores')" \
        tasks "$(translate 'Recent PBS tasks')" \
        utilities "$(translate 'System Utilities Installer')" \
        update "$(translate 'Update PBS using configured repositories')" \
        settings "$(translate 'Settings')" \
        exit "$(translate 'Exit')" 2>&1 >/dev/tty) || break
    case "$choice" in
        status) pbs_show proxmox-backup-manager versions --verbose --output-format json-pretty ;;
        stores) pbs_show proxmox-backup-manager datastore list --output-format json-pretty ;;
        tasks) pbs_show proxmox-backup-manager task list --all true --limit 20 --output-format json-pretty ;;
        utilities) bash "$LOCAL_SCRIPTS/utilities/system_utils.sh" ;;
        update) bash "$LOCAL_SCRIPTS/utilities/pbs_update.sh" ;;
        settings) bash "$LOCAL_SCRIPTS/menus/config_menu.sh" ;;
        exit) break ;;
    esac
done
clear
