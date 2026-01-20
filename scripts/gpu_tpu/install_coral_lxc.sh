#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Revision    : @Blaspt (USB passthrough via udev rule with persistent /dev/coral)
# Copyright   : (c) 2024 MacRimi
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.2
# Last Updated: 20/01/2025
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
#
# Changelog v1.2:
# - Fixed symlink detection for /dev/coral (create=dir for symlinks)
# - Fixed /dev/apex_0 not being mounted in PVE 9 (device existence not required)
# - Fixed grep patterns to avoid matching commented lines
# - Improved device type inference for non-existent devices
# - Added duplicate entry cleanup
# - Better error handling and logging
# ==========================================================

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
# CONTAINER SELECTION AND VALIDATION
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

# ==========================================================
# UDEV RULES FOR CORAL USB
# ==========================================================

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

# ==========================================================
# MOUNT CONFIGURATION HELPER
# ==========================================================

add_mount_if_needed() {
    local DEVICE="$1"
    local DEST="$2"
    local CONFIG_FILE="$3"
    
    if grep -q "lxc.mount.entry: $DEVICE" "$CONFIG_FILE"; then
        return 0
    fi
    
    local create_type="dir"
    
    if [ -e "$DEVICE" ]; then
        if [ -L "$DEVICE" ]; then
            create_type="dir"
        elif [ -c "$DEVICE" ]; then
            create_type="file"
        elif [ -d "$DEVICE" ]; then
            create_type="dir"
        fi
    else
        case "$DEVICE" in
            */apex_*|*/fb*|*/renderD*|*/card*)
                create_type="file"
                ;;
            */coral)
                create_type="dir"
                ;;
            */dri|*/bus/usb*)
                create_type="dir"
                ;;
            *)
                create_type="dir"
                ;;
        esac
    fi
    
    echo "lxc.mount.entry: $DEVICE $DEST none bind,optional,create=$create_type" >> "$CONFIG_FILE"
}

# ==========================================================
# CLEANUP DUPLICATE ENTRIES
# ==========================================================

cleanup_duplicate_entries() {
    local CONFIG_FILE="$1"
    local TEMP_FILE=$(mktemp)
    
    awk '!seen[$0]++' "$CONFIG_FILE" > "$TEMP_FILE"
    
    cat "$TEMP_FILE" > "$CONFIG_FILE"
    rm -f "$TEMP_FILE"
}

# ==========================================================
# CONFIGURE LXC HARDWARE PASSTHROUGH
# ==========================================================

configure_lxc_hardware() {
    validate_container_id
    CONFIG_FILE="/etc/pve/lxc/${CONTAINER_ID}.conf"
    
    if [ ! -f "$CONFIG_FILE" ]; then
        msg_error "$(translate 'Configuration file for container') $CONTAINER_ID $(translate 'not found.')"
        exit 1
    fi

    cleanup_duplicate_entries "$CONFIG_FILE"

    # ============================================================
    # Convert to privileged container if needed
    # ============================================================
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

    # ============================================================
    # Enable nesting feature
    # ============================================================
    if ! grep -Pq "^features:.*nesting=1" "$CONFIG_FILE"; then
        if grep -Pq "^features:" "$CONFIG_FILE"; then

            sed -i 's/^features: \(.*\)/features: nesting=1,\1/' "$CONFIG_FILE"
        else

            echo "features: nesting=1" >> "$CONFIG_FILE"
        fi
        msg_ok "$(translate 'Nesting feature enabled')"
    fi

    # ============================================================
    # iGPU support
    # ============================================================
    msg_info "$(translate 'Configuring iGPU support...')"
    
    if ! grep -Pq "^lxc.cgroup2.devices.allow: c 226:0 rwm" "$CONFIG_FILE"; then
        echo "lxc.cgroup2.devices.allow: c 226:0 rwm # iGPU" >> "$CONFIG_FILE"
    fi
    
    if ! grep -Pq "^lxc.cgroup2.devices.allow: c 226:128 rwm" "$CONFIG_FILE"; then
        echo "lxc.cgroup2.devices.allow: c 226:128 rwm # iGPU" >> "$CONFIG_FILE"
    fi

    add_mount_if_needed "/dev/dri" "dev/dri" "$CONFIG_FILE"
    add_mount_if_needed "/dev/dri/renderD128" "dev/dri/renderD128" "$CONFIG_FILE"
    add_mount_if_needed "/dev/dri/card0" "dev/dri/card0" "$CONFIG_FILE"
    
    msg_ok "$(translate 'iGPU configuration added')"

    # ============================================================
    # Framebuffer support
    # ============================================================
    if [ -e "/dev/fb0" ]; then
        msg_info "$(translate 'Configuring Framebuffer support...')"
        
        if ! grep -Pq "^lxc.cgroup2.devices.allow: c 29:0 rwm" "$CONFIG_FILE"; then
            echo "lxc.cgroup2.devices.allow: c 29:0 rwm # Framebuffer" >> "$CONFIG_FILE"
        fi
        
        add_mount_if_needed "/dev/fb0" "dev/fb0" "$CONFIG_FILE"
        msg_ok "$(translate 'Framebuffer configuration added')"
    fi

    # ============================================================
    # Coral USB passthrough
    # ============================================================
    msg_info "$(translate 'Configuring Coral USB support...')"
    
    add_udev_rule_for_coral_usb
    
    if ! grep -Pq "^lxc.cgroup2.devices.allow: c 189:\\\* rwm" "$CONFIG_FILE"; then
        echo "lxc.cgroup2.devices.allow: c 189:* rwm # Coral USB" >> "$CONFIG_FILE"
    fi
    
    add_mount_if_needed "/dev/coral" "dev/coral" "$CONFIG_FILE"
    
    if [ -L "/dev/coral" ]; then
        msg_ok "$(translate 'Coral USB configuration added - device detected')"
    else
        msg_ok "$(translate 'Coral USB configured but device not currently connected')"
    fi

    # ============================================================
    # Coral M.2 (PCIe) support
    # ============================================================
    stop_spinner

    if lspci | grep -iq "Global Unichip"; then
        msg_info "$(translate 'Coral M.2 Apex detected, configuring...')"
        

        if ! grep -Pq "^lxc.cgroup2.devices.allow: c 245:0 rwm" "$CONFIG_FILE"; then
            echo "lxc.cgroup2.devices.allow: c 245:0 rwm # Coral M2 Apex" >> "$CONFIG_FILE"
        fi
        

        add_mount_if_needed "/dev/apex_0" "dev/apex_0" "$CONFIG_FILE"
        
        if [ -e "/dev/apex_0" ]; then
            msg_ok "$(translate 'Coral M.2 Apex configuration added - device ready')"
        else
            msg_ok "$(translate 'Coral M.2 Apex configuration added - device will be available after reboot')"
        fi
    fi


    cleanup_duplicate_entries "$CONFIG_FILE"
    
    msg_ok "$(translate 'Hardware configuration completed for container') $CONTAINER_ID"
}

# ==========================================================
# INSTALL DRIVERS INSIDE CONTAINER
# ==========================================================

install_coral_in_container() {
    msg_info "$(translate 'Installing iGPU and Coral TPU drivers inside the container...')"
    tput sc
    LOG_FILE=$(mktemp)


    if ! pct status "$CONTAINER_ID" | grep -q "running"; then
        pct start "$CONTAINER_ID"
        sleep 5
    fi


    stop_spinner

    # Determine driver package for Coral M.2
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

    # Install drivers inside container
    script -q -c "pct exec \"$CONTAINER_ID\" -- bash -c '
    set -e
    
    echo \"[1/6] Updating package lists...\"
    apt-get update -qq
    
    echo \"[2/6] Installing iGPU drivers...\"
    apt-get install -y -qq va-driver-all ocl-icd-libopencl1 intel-opencl-icd vainfo intel-gpu-tools
    
    echo \"[3/6] Configuring DRI permissions...\"
    if [ -e /dev/dri ]; then
        chgrp video /dev/dri 2>/dev/null || true
        chmod 755 /dev/dri 2>/dev/null || true
    fi
    
    echo \"[4/6] Adding users to video/render groups...\"
    adduser root video 2>/dev/null || true
    adduser root render 2>/dev/null || true
    
    echo \"[5/6] Installing Coral TPU dependencies...\"
    apt-get install -y -qq gnupg curl ca-certificates
    
    echo \"[6/6] Adding Coral TPU repository...\"
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/coral-edgetpu.gpg
    echo \"deb [signed-by=/usr/share/keyrings/coral-edgetpu.gpg] https://packages.cloud.google.com/apt coral-edgetpu-stable main\" | tee /etc/apt/sources.list.d/coral-edgetpu.list >/dev/null
    
    echo \"\"
    echo \"Updating package lists for Coral repository...\"
    apt-get update -qq
    
    echo \"Installing Coral TPU driver ($DRIVER_PACKAGE)...\"
    apt-get install -y -qq $DRIVER_PACKAGE
    
    '" "$LOG_FILE" 2>&1

    if [ $? -eq 0 ]; then
        tput rc
        tput ed
        rm -f "$LOG_FILE"
        msg_ok "$(translate 'iGPU and Coral TPU drivers installed successfully inside the container.')"
    else
        tput rc
        tput ed
        msg_error "$(translate 'Failed to install drivers inside the container.')"
        echo ""
        echo "$(translate 'Installation log:')"
        cat "$LOG_FILE"
        rm -f "$LOG_FILE"
        exit 1
    fi
}

# ==========================================================
# VERIFICATION AND SUMMARY
# ==========================================================

show_configuration_summary() {
    local CONFIG_FILE="/etc/pve/lxc/${CONTAINER_ID}.conf"
    
    
    # iGPU
    if grep -q "c 226:0 rwm" "$CONFIG_FILE"; then
        msg_ok2 "✓ iGPU support: $(translate 'Enabled')"
    fi
    
    # Coral USB
    if grep -q "c 189:.*rwm.*Coral USB" "$CONFIG_FILE"; then
        if [ -L "/dev/coral" ]; then
            msg_ok2 "✓ Coral USB: $(translate 'Enabled and detected')"
        else
            msg_ok2 "⚠ Coral USB: $(translate 'Enabled but not connected')"
        fi
    fi
    
    # Coral M.2
    if grep -q "c 245:0 rwm.*Coral M2" "$CONFIG_FILE"; then
        if [ -e "/dev/apex_0" ]; then
            msg_ok2 "✓ Coral M.2: $(translate 'Enabled and ready')"
        else
            msg_ok2 "⚠ Coral M.2: $(translate 'Enabled (device pending)')"
        fi
    fi
    
}

# ==========================================================
# MAIN EXECUTION
# ==========================================================

main() {
    select_container
    show_proxmenux_logo
    configure_lxc_hardware
    install_coral_in_container
    show_configuration_summary
    
    msg_ok "$(translate 'Configuration completed successfully!')"
    echo ""
    msg_success "$(translate 'Press Enter to return to menu...')"
    read -r
}

# Run main function
main