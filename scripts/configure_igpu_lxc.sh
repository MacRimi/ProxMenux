#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 28/01/2025
# ==========================================================
# Description:
# This script automates the process of enabling and configuring Intel Integrated GPU (iGPU) support in Proxmox VE LXC containers.
# Its goal is to simplify the configuration of hardware-accelerated graphical capabilities within containers, allowing for efficient
# use of Intel iGPUs for tasks such as transcoding, rendering, and accelerating graphics-intensive applications.
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



# Select LXC container
select_container() {

    CONTAINERS=$(pct list | awk 'NR>1 {print $1, $3}' | xargs -n2)
    if [ -z "$CONTAINERS" ]; then
        msg_error "$(translate 'No containers available in Proxmox.')"
        exit 1
    fi

    CONTAINER_ID=$(whiptail --title "$(translate 'Select Container')" \
        --menu "$(translate 'Select the LXC container:')" 20 70 10 $CONTAINERS 3>&1 1>&2 2>&3)

    if [ -z "$CONTAINER_ID" ]; then
        msg_error "$(translate 'No container selected. Exiting.')"
        exit 1
    fi

    if ! pct list | awk 'NR>1 {print $1}' | grep -qw "$CONTAINER_ID"; then
        msg_error "$(translate 'Container with ID') $CONTAINER_ID $(translate 'does not exist. Exiting.')"
        exit 1
    fi

    msg_ok "$(translate 'Container selected:') $CONTAINER_ID"
}



# Validate that the selected container is valid
validate_container_id() {
    if [ -z "$CONTAINER_ID" ]; then
        msg_error "$(translate 'Container ID not defined. Make sure to select a container first.')"
        exit 1
    fi

    # Check if the container is running and stop it before configuration
    if pct status "$CONTAINER_ID" | grep -q "running"; then
        msg_info "$(translate 'Stopping the container before applying configuration...')"
        pct stop "$CONTAINER_ID"
        msg_ok "$(translate 'Container stopped.')"
    fi
}



# Configure LXC for iGPU
configure_lxc_for_igpu() {
    validate_container_id
    CONFIG_FILE="/etc/pve/lxc/${CONTAINER_ID}.conf"
    if [ ! -f "$CONFIG_FILE" ]; then
        msg_error "$(translate 'Configuration file for container') $CONTAINER_ID $(translate 'not found.')"
        exit 1
    fi

    if grep -q "^unprivileged: 1" "$CONFIG_FILE"; then
        msg_info "$(translate 'The container is unprivileged. Changing to privileged...')"
        sed -i "s/^unprivileged: 1/unprivileged: 0/" "$CONFIG_FILE"
        STORAGE_TYPE=$(pct config "$CONTAINER_ID" | grep "^rootfs:" | awk -F, '{print $2}' | cut -d'=' -f2)
        if [[ "$STORAGE_TYPE" == "dir" ]]; then
            STORAGE_PATH=$(pct config "$CONTAINER_ID" | grep "^rootfs:" | awk '{print $2}' | cut -d',' -f1)
            chown -R root:root "$STORAGE_PATH"
        fi
        msg_ok "$(translate 'Container changed to privileged.')"
    fi


    if grep -q "^lxc.apparmor.profile" "$CONFIG_FILE"; then
        msg_info "$(translate 'Disabling AppArmor profile to avoid conflicts...')"
        sed -i "/^lxc.apparmor.profile/d" "$CONFIG_FILE"
        msg_ok "$(translate 'AppArmor profile removed.')"
    fi



    # Configure iGPU
    if ! grep -q "features: nesting=1" "$CONFIG_FILE"; then
        echo "features: nesting=1" >> "$CONFIG_FILE"
    fi

    if ! grep -q "c 226:0 rwm" "$CONFIG_FILE"; then
        echo "lxc.cgroup2.devices.allow: c 226:0 rwm # iGPU" >> "$CONFIG_FILE"
        echo "lxc.cgroup2.devices.allow: c 226:128 rwm # iGPU" >> "$CONFIG_FILE"
        echo "lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir" >> "$CONFIG_FILE"
        echo "lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file" >> "$CONFIG_FILE"
    fi

    if ! grep -q "c 29:0 rwm # Framebuffer" "$CONFIG_FILE"; then
        echo "lxc.cgroup2.devices.allow: c 29:0 rwm # Framebuffer" >> "$CONFIG_FILE"
    fi

    if ! grep -q "lxc.mount.entry: /dev/fb0" "$CONFIG_FILE"; then
        echo "lxc.mount.entry: /dev/fb0 dev/fb0 none bind,optional,create=file" >> "$CONFIG_FILE"
    fi


    msg_ok "$(translate 'iGPU configuration added to container') $CONTAINER_ID."
}





configure_lxc_for_igpu_() {
  validate_container_id
  CONFIG_FILE="/etc/pve/lxc/${CONTAINER_ID}.conf"
  [[ -f "$CONFIG_FILE" ]] || { msg_error "$(translate 'Configuration file not found.')"; exit 1; }


  if ! grep -q "^unprivileged:" "$CONFIG_FILE"; then
    echo "unprivileged: 1" >> "$CONFIG_FILE"
  fi


  grep -q "^features: " "$CONFIG_FILE" || echo "features: nesting=1" >> "$CONFIG_FILE"
  grep -q "^lxc.cgroup2.devices.allow: c 226:\* rwm" "$CONFIG_FILE" || \
    echo "lxc.cgroup2.devices.allow: c 226:* rwm" >> "$CONFIG_FILE"
  grep -q "^lxc.mount.entry: /dev/dri " "$CONFIG_FILE" || \
    echo "lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir" >> "$CONFIG_FILE"

  msg_ok "$(translate 'iGPU configuration added to container') $CONTAINER_ID."
}





# Install iGPU drivers in the container
install_igpu_in_container() {

    msg_info2 "$(translate 'Installing iGPU drivers inside the container...')"
    tput sc
    LOG_FILE=$(mktemp)

    #msg_info "$(translate 'Installing iGPU drivers...')"
    pct start "$CONTAINER_ID" >/dev/null 2>&1

    script -q -c "pct exec \"$CONTAINER_ID\" -- bash -c '
    set -e
    apt-get update >/dev/null 2>&1
    apt-get install -y va-driver-all ocl-icd-libopencl1 intel-opencl-icd vainfo intel-gpu-tools
    chgrp video /dev/dri && chmod 755 /dev/dri
    adduser root video && adduser root render
    '" "$LOG_FILE"

    if [ $? -eq 0 ]; then
        tput rc 
        tput ed 
        rm -f "$LOG_FILE"  
        msg_ok "$(translate 'iGPU drivers installed inside the container.')"
    else
        tput rc  
        tput ed  
        msg_error "$(translate 'Failed to install iGPU drivers inside the container.')"
        cat "$LOG_FILE"  
        rm -f "$LOG_FILE"
        exit 1
    fi
}


select_container 
show_proxmenux_logo
configure_lxc_for_igpu
install_igpu_in_container


msg_success "$(translate 'iGPU configuration completed in container') $CONTAINER_ID."
echo -e
msg_success "$(translate "Press Enter to return to menu...")"
read -r
