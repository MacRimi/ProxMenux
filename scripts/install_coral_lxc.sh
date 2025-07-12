#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Revision    : @Blaspt (USB passthrough via udev rule with persistent /dev/coral)
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.1
# Last Updated: 16/05/2025
# ==========================================================
# Description:
# This script automates the configuration and installation of
# Coral TPU and iGPU support in Proxmox VE containers. It:
# - Configures a selected LXC container for hardware acceleration
# - Installs and sets up Coral TPU drivers on the Proxmox host
# - Installs necessary drivers inside the container
# - Manages required system and container restarts
#
# Supports Coral USB and Coral M.2 (PCIe) devices.
# Includes USB passthrough enhancement using persistent udev alias (/dev/coral).
# ==========================================================

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


add_udev_rule_for_coral_usb_() {
    RULE_FILE="/etc/udev/rules.d/99-coral-usb.rules"
    RULE_CONTENT='SUBSYSTEM=="usb", ATTRS{idVendor}=="18d1", ATTRS{idProduct}=="9302", MODE="0666", TAG+="uaccess"'

    if [[ ! -f "$RULE_FILE" ]] || ! grep -qF "$RULE_CONTENT" "$RULE_FILE"; then
        echo "$RULE_CONTENT" > "$RULE_FILE"
        udevadm control --reload-rules && udevadm trigger
        msg_ok "$(translate 'Udev rule for Coral USB added and rules reloaded.')"
    else
        msg_ok "$(translate 'Udev rule for Coral USB already exists.')"
    fi
}


add_udev_rule_for_coral_usb() {
    RULE_FILE="/etc/udev/rules.d/99-coral-usb.rules"
    RULE_CONTENT='# Coral USB Accelerator
SUBSYSTEM=="usb", ATTRS{idVendor}=="18d1", ATTRS{idProduct}=="9302", MODE="0666", TAG+="uaccess", SYMLINK+="coral"
# Coral Dev Board / Mini PCIe
SUBSYSTEM=="usb", ATTRS{idVendor}=="1a6e", ATTRS{idProduct}=="089a", MODE="0666", TAG+="uaccess", SYMLINK+="coral"'

    if [[ ! -f "$RULE_FILE" ]] || ! grep -q "18d1.*9302\|1a6e.*089a" "$RULE_FILE"; then
        echo "$RULE_CONTENT" > "$RULE_FILE"
        udevadm control --reload-rules && udevadm trigger
        msg_ok "$(translate 'Udev rules for Coral USB devices added and rules reloaded.')"
    else
        msg_ok "$(translate 'Udev rules for Coral USB devices already exist.')"
    fi
}


add_mount_if_needed() {
    local DEVICE="$1"
    local DEST="$2"
    local CONFIG_FILE="$3"
    if [ -e "$DEVICE" ] && ! grep -q "lxc.mount.entry: $DEVICE" "$CONFIG_FILE"; then
        echo "lxc.mount.entry: $DEVICE $DEST none bind,optional,create=$( [ -c "$DEVICE" ] && echo file || echo dir )" >> "$CONFIG_FILE"
    fi
}



configure_lxc_hardware() {
    validate_container_id
    CONFIG_FILE="/etc/pve/lxc/${CONTAINER_ID}.conf"
    if [ ! -f "$CONFIG_FILE" ]; then
        msg_error "$(translate 'Configuration file for container') $CONTAINER_ID $(translate 'not found.')"
        exit 1
    fi

    # Privileged container
    if grep -q "^unprivileged: 1" "$CONFIG_FILE"; then
        msg_info "$(translate 'The container is unprivileged. Changing to privileged...')"
        sed -i "s/^unprivileged: 1/unprivileged: 0/" "$CONFIG_FILE"
        STORAGE_TYPE=$(pct config "$CONTAINER_ID" | grep "^rootfs:" | awk -F, '{print $2}' | cut -d'=' -f2)
        if [[ "$STORAGE_TYPE" == "dir" ]]; then
            STORAGE_PATH=$(pct config "$CONTAINER_ID" | grep "^rootfs:" | awk '{print $2}' | cut -d',' -f1)
            chown -R root:root "$STORAGE_PATH"
        fi
        msg_ok "$(translate 'Container changed to privileged.')"
    else
        msg_ok "$(translate 'The container is already privileged.')"
    fi
    

    sed -i '/^dev[0-9]\+:/d' "$CONFIG_FILE"

    # Enable nesting feature
    if ! grep -q "features: nesting=1" "$CONFIG_FILE"; then
        echo "features: nesting=1" >> "$CONFIG_FILE"
    fi

    # iGPU support
    if ! grep -q "c 226:0 rwm" "$CONFIG_FILE"; then
        echo "lxc.cgroup2.devices.allow: c 226:0 rwm # iGPU" >> "$CONFIG_FILE"
        echo "lxc.cgroup2.devices.allow: c 226:128 rwm # iGPU" >> "$CONFIG_FILE"
    fi


    add_mount_if_needed "/dev/dri" "dev/dri" "$CONFIG_FILE"
    add_mount_if_needed "/dev/dri/renderD128" "dev/dri/renderD128" "$CONFIG_FILE"
    add_mount_if_needed "/dev/dri/card0" "dev/dri/card0" "$CONFIG_FILE"

    # Framebuffer support
    if ! grep -q "c 29:0 rwm # Framebuffer" "$CONFIG_FILE"; then
        echo "lxc.cgroup2.devices.allow: c 29:0 rwm # Framebuffer" >> "$CONFIG_FILE"
    fi
    add_mount_if_needed "/dev/fb0" "dev/fb0" "$CONFIG_FILE"


     # ----------------------------------------------------------
    # Coral USB passthrough (via udev + /dev/coral)
    # ----------------------------------------------------------
    add_udev_rule_for_coral_usb
    if ! grep -Pq "^lxc.cgroup2.devices.allow: c 189:\* rwm # Coral USB$" "$CONFIG_FILE"; then
        echo "lxc.cgroup2.devices.allow: c 189:* rwm # Coral USB" >> "$CONFIG_FILE"
    fi
    add_mount_if_needed "/dev/coral" "dev/coral" "$CONFIG_FILE"


    # ----------------------------------------------------------
    # Coral M.2 (PCIe) support
    # ----------------------------------------------------------
    if lspci | grep -iq "Global Unichip"; then
        if ! grep -Pq "^lxc.cgroup2.devices.allow: c 245:0 rwm # Coral M2 Apex$" "$CONFIG_FILE"; then
            echo "lxc.cgroup2.devices.allow: c 245:0 rwm # Coral M2 Apex" >> "$CONFIG_FILE"
        fi
        add_mount_if_needed "/dev/apex_0" "dev/apex_0" "$CONFIG_FILE"
    fi


    msg_ok "$(translate 'Coral TPU and iGPU configuration added to container') $CONTAINER_ID."
}

install_coral_in_container() {
    msg_info2 "$(translate 'Installing iGPU and Coral TPU drivers inside the container...')"
    tput sc
    LOG_FILE=$(mktemp)

    pct start "$CONTAINER_ID"

    CORAL_M2=$(lspci | grep -i "Global Unichip")
    if [[ -n "$CORAL_M2" ]]; then
        DRIVER_OPTION=$(whiptail --title "$(translate 'Select driver version')" \
            --menu "$(translate 'Choose the driver version for Coral M.2:\n\nCaution: Maximum mode generates more heat.')" 15 60 2 \
            1 "libedgetpu1-std ($(translate 'standard performance'))" \
            2 "libedgetpu1-max ($(translate 'maximum performance'))" 3>&1 1>&2 2>&3)

        case "$DRIVER_OPTION" in
            1) DRIVER_PACKAGE="libedgetpu1-std" ;;
            2) DRIVER_PACKAGE="libedgetpu1-max" ;;
            *) DRIVER_PACKAGE="libedgetpu1-std" ;;
        esac
    else
        DRIVER_PACKAGE="libedgetpu1-std"
    fi

    script -q -c "pct exec \"$CONTAINER_ID\" -- bash -c '
    set -e
    echo \"- Updating package lists...\"
    apt-get update
    echo \"- Installing iGPU drivers...\"
    apt-get install -y va-driver-all ocl-icd-libopencl1 intel-opencl-icd vainfo intel-gpu-tools
    chgrp video /dev/dri && chmod 755 /dev/dri
    adduser root video && adduser root render

    echo \"- Installing Coral TPU dependencies...\"
    apt-get install -y gnupg python3 python3-pip python3-venv

    echo \"- Adding Coral TPU repository...\"
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/coral-edgetpu.gpg
    echo \"deb [signed-by=/usr/share/keyrings/coral-edgetpu.gpg] https://packages.cloud.google.com/apt coral-edgetpu-stable main\" | tee /etc/apt/sources.list.d/coral-edgetpu.list

    echo \"- Updating package lists again...\"
    apt-get update
    echo \"- Installing Coral TPU driver ($DRIVER_PACKAGE)...\"
    apt-get install -y $DRIVER_PACKAGE
    '" "$LOG_FILE"

    if [ $? -eq 0 ]; then
        tput rc
        tput ed
        rm -f "$LOG_FILE"
        msg_ok "$(translate 'iGPU and Coral TPU drivers installed inside the container.')"
    else
        msg_error "$(translate 'Failed to install iGPU and Coral TPU drivers inside the container.')"
        cat "$LOG_FILE"
        rm -f "$LOG_FILE"
        exit 1
    fi
}

select_container
show_proxmenux_logo
configure_lxc_hardware
install_coral_in_container

msg_ok "$(translate 'Configuration completed.')"
echo -e
msg_success "$(translate "Press Enter to return to menu...")"
read -r
