#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.1
# Last Updated: 17/08/2025
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




validate_container_id() {
    if [ -z "$CONTAINER_ID" ]; then
        msg_error "$(translate 'Container ID not defined. Make sure to select a container first.')"
        exit 1
    fi


    if pct status "$CONTAINER_ID" | grep -q "running"; then
        msg_info "$(translate 'Stopping the container before applying configuration...')"
        pct stop "$CONTAINER_ID"
        msg_ok "$(translate 'Container stopped.')"
    fi
}



configure_lxc_for_igpu() {
  validate_container_id

  CONFIG_FILE="/etc/pve/lxc/${CONTAINER_ID}.conf"
  [[ -f "$CONFIG_FILE" ]] || { msg_error "$(translate 'Configuration file for container') $CONTAINER_ID $(translate 'not found.')"; exit 1; }

  
  if [[ ! -d /dev/dri ]]; then
    modprobe i915 2>/dev/null || true
    for _ in {1..5}; do
      [[ -d /dev/dri ]] && break
      sleep 1
    done
  fi

  CT_TYPE=$(pct config "$CONTAINER_ID" | awk '/^unprivileged:/ {print $2}')
  [[ -z "$CT_TYPE" ]] && CT_TYPE="0"  

  msg_info "$(translate 'Configuring Intel iGPU passthrough for container...')"

    for rn in /dev/dri/renderD*; do
    [[ -e "$rn" ]] || continue
    chmod 660 "$rn" 2>/dev/null || true
    chgrp render "$rn" 2>/dev/null || true
    done

    mapfile -t RENDER_NODES < <(find /dev/dri -maxdepth 1 -type c -name 'renderD*' 2>/dev/null || true)
    mapfile -t CARD_NODES   < <(find /dev/dri -maxdepth 1 -type c -name 'card*'    2>/dev/null || true)
    FB_NODE=""
    [[ -e /dev/fb0 ]] && FB_NODE="/dev/fb0"

    if [[ ${#RENDER_NODES[@]} -eq 0 && ${#CARD_NODES[@]} -eq 0 && -z "$FB_NODE" ]]; then
        msg_warn "$(translate 'No VA-API devices found on host (/dev/dri*, /dev/fb0). Is i915 loaded?')"
        return 0
    fi

    if grep -q '^features:' "$CONFIG_FILE"; then
        grep -Eq '^features:.*(^|,)\s*nesting=1(\s|,|$)' "$CONFIG_FILE" || sed -i 's/^features:\s*/&nesting=1, /' "$CONFIG_FILE"
    else
        echo "features: nesting=1" >> "$CONFIG_FILE"
    fi



  if [[ "$CT_TYPE" == "0" ]]; then

        sed -i '/^lxc\.cgroup2\.devices\.allow:\s*c\s*226:/d' "$CONFIG_FILE"
        sed -i '\|^lxc\.mount\.entry:\s*/dev/dri|d' "$CONFIG_FILE"
        sed -i '\|^lxc\.mount\.entry:\s*/dev/fb0|d' "$CONFIG_FILE"

        echo "lxc.cgroup2.devices.allow: c 226:* rwm" >> "$CONFIG_FILE"
        echo "lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir" >> "$CONFIG_FILE"
        [[ -n "$FB_NODE" ]] && echo "lxc.mount.entry: /dev/fb0 dev/fb0 none bind,optional,create=file" >> "$CONFIG_FILE"


    else
        sed -i '/^dev[0-9]\+:/d' "$CONFIG_FILE"

        idx=0
        for c in "${CARD_NODES[@]}"; do
        echo "dev${idx}: $c,gid=44" >> "$CONFIG_FILE"
        idx=$((idx+1))
        done
        for r in "${RENDER_NODES[@]}"; do
        echo "dev${idx}: $r,gid=104" >> "$CONFIG_FILE"
        idx=$((idx+1))
        done

  fi
  msg_ok "$(translate 'iGPU configuration added to container') $CONTAINER_ID."

}





install_igpu_in_container() {

    msg_info2 "$(translate 'Installing iGPU drivers inside the container...')"
    tput sc
    LOG_FILE=$(mktemp)


    pct start "$CONTAINER_ID" >/dev/null 2>&1

    script -q -c "pct exec \"$CONTAINER_ID\" -- bash -c '
    set -e
    getent group video  >/dev/null || groupadd -g 44  video
    getent group render >/dev/null || groupadd -g 104 render
    usermod -aG video,render root || true

    apt-get update >/dev/null 2>&1
    apt-get install -y va-driver-all ocl-icd-libopencl1 intel-opencl-icd vainfo intel-gpu-tools

    chgrp video /dev/dri 2>/dev/null || true
    chmod 755 /dev/dri 2>/dev/null || true
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
msg_title "$(translate "Add HW iGPU acceleration to an LXC")"
configure_lxc_for_igpu
install_igpu_in_container


msg_success "$(translate 'iGPU configuration completed in container') $CONTAINER_ID."
echo -e
msg_success "$(translate "Press Enter to return to menu...")"
read -r
