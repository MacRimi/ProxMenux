#!/bin/bash

# ==========================================================
# ProxMenu - LXC Conversion Management Menu
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 19/08/2025
# ==========================================================
# Description:
# This script provides a menu interface for LXC container privilege conversions.
# Allows converting between privileged and unprivileged containers safely.
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

show_main_menu() {
    CHOICE=$(dialog --backtitle "ProxMenux" --title "$(translate 'LXC Management')" \
        --menu "$(translate 'Select conversion option:')" 20 70 10 \
        "1" "$(translate 'Convert Privileged to Unprivileged')" \
        "2" "$(translate 'Convert Unprivileged to Privileged')" \
        "3" "$(translate 'Show Container Privilege Status')" \
        "4" "$(translate 'Exit')" 3>&1 1>&2 2>&3)
    
    case $CHOICE in
        1)
            bash <(curl -fsSL "$REPO_URL/scripts/lcx/lxc-privileged-to-unprivileged.sh")
            ;;
        2)
            convert_unprivileged_to_privileged
            ;;
        3)
            show_container_status
            ;;
        4)
            exit 0
            ;;
        *)
            exit 0
            ;;
    esac
}



convert_unprivileged_to_privileged() {

    bash <(curl -fsSL "$REPO_URL/scripts/lcx/lxc-privileged-to-unprivileged.sh")
    
}

show_container_status() {
    show_proxmenux_logo
    msg_info "$(translate 'Gathering container privilege information...')"
    

    TEMP_FILE=$(mktemp)
    
    echo "$(translate 'LXC Container Privilege Status')" > "$TEMP_FILE"
    echo "=================================" >> "$TEMP_FILE"
    echo "" >> "$TEMP_FILE"

    pct list | awk 'NR>1 {print $1, $3}' | while read id name; do
        if pct config "$id" | grep -q "^unprivileged: 1"; then
            status="$(translate 'Unprivileged')"
        else
            status="$(translate 'Privileged')"
        fi
        
        running_status=$(pct status "$id" | grep -q "running" && echo "$(translate 'Running')" || echo "$(translate 'Stopped')")
        
        printf "ID: %-4s | %-20s | %-12s | %s\n" "$id" "$name" "$status" "$running_status" >> "$TEMP_FILE"
    done
    
    
    cleanup
    dialog --backtitle "ProxMenux" --title "$(translate 'Container Status')" --textbox "$TEMP_FILE" 25 80
    

    rm -f "$TEMP_FILE"
    show_main_menu
    
}




 show_main_menu
