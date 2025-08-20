#!/bin/bash

# ==========================================================
# ProxMenu - LXC Privileged to Unprivileged Converter
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.1
# Last Updated: 19/08/2025
# ==========================================================
# Description:
# This script converts a privileged LXC container to an unprivileged one
# using the direct conversion method (mount and chown).
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

select_privileged_container() {

    CONTAINERS=$(pct list | awk 'NR>1 {print $1, $3}' | while read id name; do
        if pct config "$id" | grep -q "^unprivileged: 0" || ! pct config "$id" | grep -q "^unprivileged:"; then
            echo "$id" "$name"
        fi
    done | xargs -n2)
    
    if [ -z "$CONTAINERS" ]; then
        msg_error "$(translate 'No privileged containers available in Proxmox.')"
        exit 1
    fi
    cleanup
    CONTAINER_ID=$(whiptail --title "$(translate 'Select Privileged Container')" \
        --menu "$(translate 'Select the privileged LXC container to convert:')" 20 70 10 $CONTAINERS 3>&1 1>&2 2>&3)

    if [ -z "$CONTAINER_ID" ]; then
        msg_error "$(translate 'No container selected. Exiting.')"
        exit 1
    fi

    msg_ok "$(translate 'Privileged container selected:') $CONTAINER_ID"
}

validate_container_id() {
    if [ -z "$CONTAINER_ID" ]; then
        msg_error "$(translate 'Container ID not defined. Make sure to select a container first.')"
        exit 1
    fi


    if pct config "$CONTAINER_ID" | grep -q "^unprivileged: 1"; then
        msg_error "$(translate 'Container') $CONTAINER_ID $(translate 'is already unprivileged.')"
        exit 1
    fi

    if pct status "$CONTAINER_ID" | grep -q "running"; then
        msg_info "$(translate 'Stopping the container before conversion...')"
        pct stop "$CONTAINER_ID"
        msg_ok "$(translate 'Container stopped.')"
    fi
}

show_backup_warning() {
    local message="$(translate 'It is strongly recommended to create a backup of your container before proceeding with the conversion.')"
    message="$message\n\n$(translate 'Do you want to continue with the conversion now, or exit to create a backup first?')"
    message="$message\n\n$(translate 'Continue: Proceed with conversion')"
    message="$message\n$(translate 'Exit: Stop to create backup manually')"
    
    if whiptail --title "$(translate 'Backup Recommendation')" \
        --yes-button "$(translate 'Continue')" \
        --no-button "$(translate 'Exit')" \
        --yesno "$message" 18 80; then
        return 0
    else
        msg_info2 "$(translate 'User chose to exit for manual backup creation.')"
        exit 0
    fi
}

convert_direct_method() {
    msg_info2 "$(translate 'Starting direct conversion of container') $CONTAINER_ID..."
    
    TEMP_DIR="/tmp/lxc_convert_$CONTAINER_ID"
    mkdir -p "$TEMP_DIR"
    

    ROOTFS_CONFIG=$(pct config "$CONTAINER_ID" | grep "^rootfs:")
    if [ -z "$ROOTFS_CONFIG" ]; then
        msg_error "$(translate 'Could not find rootfs configuration for container.')"
        exit 1
    fi
    

    STORAGE_DISK=$(echo "$ROOTFS_CONFIG" | awk '{print $2}' | cut -d, -f1)
    
    msg_ok "$(translate 'Storage disk identifier:') $STORAGE_DISK"
    

    DISK_PATH=$(pvesm path "$STORAGE_DISK" 2>/dev/null)
    
    if [ -n "$DISK_PATH" ] && [ -e "$DISK_PATH" ]; then
        msg_ok "$(translate 'Disk path resolved via pvesm:') $DISK_PATH"
    else

        STORAGE_NAME=$(echo "$STORAGE_DISK" | cut -d: -f1)
        DISK_NAME=$(echo "$STORAGE_DISK" | cut -d: -f2)
        
        msg_info2 "$(translate 'pvesm path failed, trying manual detection...')"
        msg_info2 "$(translate 'Storage:') $STORAGE_NAME, $(translate 'Disk:') $DISK_NAME"
        

        for vg in pve $(vgs --noheadings -o vg_name 2>/dev/null | tr -d ' '); do
            if [ -e "/dev/$vg/$DISK_NAME" ]; then
                DISK_PATH="/dev/$vg/$DISK_NAME"
                break
            fi
        done
        

        if [ -z "$DISK_PATH" ] || [ ! -e "$DISK_PATH" ]; then
            ZFS_PATH="/dev/zvol/$STORAGE_NAME/$DISK_NAME"
            if [ -e "$ZFS_PATH" ]; then
                DISK_PATH="$ZFS_PATH"
            fi
        fi
    fi
    

    if [ -z "$DISK_PATH" ] || [ ! -e "$DISK_PATH" ]; then
        msg_error "$(translate 'Could not determine disk path for:') $STORAGE_DISK"
        msg_error "$(translate 'Tried pvesm path and manual detection methods')"
        msg_info2 "$(translate 'Available storage information:')"
        pvesm status 2>/dev/null || msg_error "$(translate 'pvesm status failed')"
        rmdir "$TEMP_DIR"
        exit 1
    fi
    
    
    msg_ok "$(translate 'Mounting container filesystem')"
    if ! mount "$DISK_PATH" "$TEMP_DIR" 2>/dev/null; then

        if ! mount -o loop "$DISK_PATH" "$TEMP_DIR" 2>/dev/null; then
            msg_error "$(translate 'Failed to mount container filesystem.')"
            msg_error "$(translate 'Disk path:') $DISK_PATH"
            msg_success "$(translate "Press Enter to continue")"
            read -r
            rmdir "$TEMP_DIR"
            return
        fi
    fi
    
    msg_info "$(translate 'Converting file ownership (this may take several minutes)...')"
    

    find "$TEMP_DIR" -type f -print0 | while IFS= read -r -d '' S; do 

        if [ ! -e "$S" ] || [ ! -r "$S" ]; then
            continue
        fi
        

        if STAT_OUTPUT=$(stat -c "%u %g" "$S" 2>/dev/null); then
            U=$(echo "$STAT_OUTPUT" | awk '{print $1}')
            G=$(echo "$STAT_OUTPUT" | awk '{print $2}')
            F=100000
            

            NEW_UID=$((F + U))
            NEW_GID=$((F + G))
            

            if ! chown "$NEW_UID:$NEW_GID" "$S" 2>/dev/null; then

                continue
            fi
        fi
    done
    

    find "$TEMP_DIR" -type d -print0 | while IFS= read -r -d '' S; do 

        if [ ! -e "$S" ] || [ ! -r "$S" ]; then
            continue
        fi
        

        if STAT_OUTPUT=$(stat -c "%u %g" "$S" 2>/dev/null); then
            U=$(echo "$STAT_OUTPUT" | awk '{print $1}')
            G=$(echo "$STAT_OUTPUT" | awk '{print $2}')
            F=100000
            

            NEW_UID=$((F + U))
            NEW_GID=$((F + G))
            

            if ! chown "$NEW_UID:$NEW_GID" "$S" 2>/dev/null; then

                continue
            fi
        fi
    done
    

    [ -e "$TEMP_DIR/var/spool/postfix/dev/-random" ] && rm -f "$TEMP_DIR/var/spool/postfix/dev/-random"
    [ -e "$TEMP_DIR/var/spool/postfix/dev/-urandom" ] && rm -f "$TEMP_DIR/var/spool/postfix/dev/-urandom"
    

    [ -e "$TEMP_DIR/usr/bin/sudo" ] && chmod u+s "$TEMP_DIR/usr/bin/sudo"
    
    umount "$TEMP_DIR"
    rmdir "$TEMP_DIR"
    

    CONFIG_FILE="/etc/pve/lxc/$CONTAINER_ID.conf"
    if ! grep -q "^unprivileged:" "$CONFIG_FILE"; then
        echo "unprivileged: 1" >> "$CONFIG_FILE"
    else
        sed -i 's/^unprivileged:.*/unprivileged: 1/' "$CONFIG_FILE"
    fi
    
    msg_ok "$(translate 'Direct conversion completed for container') $CONTAINER_ID"
}

cleanup_and_finalize() {

    if whiptail --yesno "$(translate 'Do you want to start the converted unprivileged container') $CONTAINER_ID $(translate 'now?')" 10 60; then
        msg_info2 "$(translate 'Starting unprivileged container...')"
        pct start "$CONTAINER_ID"
        msg_ok "$(translate 'Unprivileged container') $CONTAINER_ID $(translate 'started successfully.')"
    fi
}

main() {
    show_proxmenux_logo
    msg_title "$(translate "LXC Privileged to Unprivileged conversion")"
    msg_info "$(translate 'Starting LXC Privileged to Unprivileged conversion process...')"
    
    select_privileged_container
    validate_container_id
    show_backup_warning
    
    convert_direct_method
    cleanup_and_finalize
    
    msg_ok "$(translate 'Converted container ID:') $CONTAINER_ID"
    msg_ok "$(translate 'LXC conversion from privileged to unprivileged completed successfully!')"
    echo -e
    msg_success "$(translate "Press Enter to continue")"
    read -r
    exit 0
}


main
