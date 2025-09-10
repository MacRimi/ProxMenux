#!/bin/bash

# ==========================================================
# ProxMenux - LXC Unprivileged to Privileged Converter
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 2.0
# Last Updated: 19/08/2025
# ==========================================================
# Description:
# This script converts an unprivileged LXC container to a privileged one
# by directly modifying the configuration file.
# WARNING: This reduces security. Use only when necessary.
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



select_unprivileged_container() {

    CONTAINERS=$(pct list | awk 'NR>1 {print $1, $3}' | while read id name; do
        if pct config "$id" | grep -q "^unprivileged: 1"; then
            echo "$id" "$name"
        fi
    done | xargs -n2)
    
    if [ -z "$CONTAINERS" ]; then
        msg_error "$(translate 'No unprivileged containers available in Proxmox.')"
        exit 1
    fi
    cleanup
    CONTAINER_ID=$(whiptail --title "$(translate 'Select Unprivileged Container')" \
        --menu "$(translate 'Select the unprivileged LXC container to convert:')" 20 70 10 $CONTAINERS 3>&1 1>&2 2>&3)

    if [ -z "$CONTAINER_ID" ]; then
        msg_error "$(translate 'No container selected. Exiting.')"
        exit 1
    fi

    msg_ok "$(translate 'Unprivileged container selected:') $CONTAINER_ID"
}

show_backup_warning() {
    if ! whiptail --title "$(translate 'Backup Recommendation')" \
        --yes-button "$(translate 'Continue')" \
        --no-button "$(translate 'Exit')" \
        --yesno "$(translate 'It is recommended to create a backup before continuing.')" \
        12 70; then
        msg_info "$(translate 'Operation cancelled by user to create backup.')"
        exit 0
    fi
    
}

convert_to_privileged() {
    CONF_FILE="/etc/pve/lxc/$CONTAINER_ID.conf"
    
    CONTAINER_STATUS=$(pct status "$CONTAINER_ID" | awk '{print $2}')
    
    if [ "$CONTAINER_STATUS" == "running" ]; then
        msg_info "$(translate 'Stopping container') $CONTAINER_ID..."
        pct shutdown "$CONTAINER_ID"
        
        # Wait for container to stop
        for i in {1..10}; do
            sleep 1
            if [ "$(pct status "$CONTAINER_ID" | awk '{print $2}')" != "running" ]; then
                break
            fi
        done

        # Verify container stopped
        if [ "$(pct status "$CONTAINER_ID" | awk '{print $2}')" == "running" ]; then
            msg_error "$(translate 'Failed to stop the container.')"
            exit 1
        fi

        msg_ok "$(translate 'Container stopped.')"
    else
        msg_ok "$(translate 'Container is already stopped.')"
    fi
    
    msg_info "$(translate 'Creating backup of configuration file...')"
    cp "$CONF_FILE" "$CONF_FILE.bak"
    msg_ok "$(translate 'Configuration backup created:') $CONF_FILE.bak"
    
    msg_info "$(translate 'Converting container to privileged...')"
    sed -i '/^unprivileged: 1/d' "$CONF_FILE"
    echo "unprivileged: 0" >> "$CONF_FILE"
    
    msg_ok "$(translate 'Container successfully converted to privileged.')"

    echo -e
    msg_success "Press Enter to continue..."
    read -r
}

finalize_conversion() {

    if whiptail --yesno "$(translate 'Do you want to start the privileged container') $CONTAINER_ID $(translate 'now?')" 10 60; then
        msg_info "$(translate 'Starting privileged container...')"
        pct start "$CONTAINER_ID"
        msg_ok "$(translate 'Privileged container') $CONTAINER_ID $(translate 'started successfully.')"
    fi
}

main() {

    show_proxmenux_logo
    msg_title "$(translate "LXC Unprivileged to Privileged conversion")"
    msg_info "$(translate 'Starting LXC Unprivileged to Privileged conversion process...')"
    

    select_unprivileged_container
    show_backup_warning
    convert_to_privileged
    finalize_conversion
    
    msg_ok "$(translate 'LXC conversion from unprivileged to privileged completed successfully!')"
    msg_ok "$(translate 'Converted container ID:') $CONTAINER_ID"
    echo -e
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
    exit 0
}

# Execute main function
main
