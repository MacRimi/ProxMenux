#!/bin/bash
# ==========================================================
# ProxMenux - Coral TPU Passthrough to LXC
# ==========================================================
# Author      : MacRimi
# Revision    : @Blaspt (USB passthrough via udev rule)
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.4
# Last Updated: 01/04/2026
# ==========================================================
# Description:
# Configures and installs Coral TPU passthrough (USB and
# M.2 / PCIe) in a Proxmox LXC container. Writes the needed
# dev / cgroup / mount entries into the LXC config, then
# boots the container and installs the Edge TPU runtime
# inside it so apps like Frigate can actually use the TPU.
# iGPU (DRI) device nodes are added alongside when present,
# which is the typical Frigate + Quick Sync combo.
#
# Features:
#  - Supports Coral USB Accelerator and Coral M.2 / PCIe
#  - Auto-detects M.2 via lspci (Global Unichip), USB via
#    a persistent udev rule that creates /dev/coral
#  - USB passthrough mounts /dev/bus/usb (not /dev/coral)
#    so the container sees the real node even if the user
#    replugs the device to a different port
#  - PCIe/M.2 uses the PVE dev API (dev<N>: ... ,gid=apex)
#    which handles cgroup2 permissions automatically
#    in both privileged and unprivileged containers
#  - Fallback cgroup2 + mount if /dev/apex_0 not yet present
#    (module not loaded on host — reboot still pending)
#  - Inside container: adds Google Coral APT repo and
#    installs libedgetpu1-std (default) or -max (optional)
#  - Also installs iGPU user-space drivers when DRI nodes
#    are passed, so Quick Sync works out of the box
#  - Idempotent: duplicate entries in the LXC config are
#    cleaned up on every run
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

    if [[ ! -f "$RULE_FILE" ]]; then
        echo "$RULE_CONTENT" > "$RULE_FILE"
        udevadm control --reload-rules && udevadm trigger
        msg_ok "$(translate 'Udev rules for Coral USB devices added and rules reloaded.')"
    elif ! grep -q "18d1.*9302\|1a6e.*089a" "$RULE_FILE"; then
        # Append (>>) instead of overwriting (>) so any user-authored
        # rules in this file survive. Audit Tier 7 — udev rule sobreescribe.
        printf '\n%s\n' "$RULE_CONTENT" >> "$RULE_FILE"
        udevadm control --reload-rules && udevadm trigger
        msg_ok "$(translate 'Udev rules for Coral USB devices appended and rules reloaded.')"
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

# Returns the next available dev index (dev0, dev1, ...) in a container config.
# The PVE dev API (devN: /dev/foo,gid=N) works in both privileged and unprivileged
# containers, handling cgroup2 permissions automatically.
get_next_dev_index() {
    local config="$1"
    local idx=0
    while grep -q "^dev${idx}:" "$config" 2>/dev/null; do
        idx=$((idx + 1))
    done
    echo "$idx"
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

    # Bind-mount the /dev/dri directory so apps can enumerate available devices
    add_mount_if_needed "/dev/dri" "dev/dri" "$CONFIG_FILE"

    # Add each DRI device via the PVE dev API (gid=44 = render group).
    # This approach works in unprivileged containers: PVE manages cgroup2
    # permissions automatically and maps the GID into the container namespace.
    local igpu_dev_idx
    igpu_dev_idx=$(get_next_dev_index "$CONFIG_FILE")
    for dri_dev in /dev/dri/renderD128 /dev/dri/renderD129 /dev/dri/card0 /dev/dri/card1; do
        if [[ -c "$dri_dev" ]]; then
            if ! grep -q ":.*${dri_dev}" "$CONFIG_FILE"; then
                echo "dev${igpu_dev_idx}: ${dri_dev},gid=44" >> "$CONFIG_FILE"
                igpu_dev_idx=$((igpu_dev_idx + 1))
            fi
        fi
    done

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

    # FIX v1.3: Mount /dev/bus/usb instead of the /dev/coral symlink.
    # The udev symlink /dev/coral cannot be safely passed through to LXC because
    # it points to a dynamic path (e.g. /dev/bus/usb/001/005) that changes on
    # reconnect. Mounting the full USB bus tree makes the real device node
    # available inside the container regardless of port or reconnection.
    add_mount_if_needed "/dev/bus/usb" "dev/bus/usb" "$CONFIG_FILE"
    
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

        # Pre-flight: warn if the host driver isn't loaded. Without `apex`
        # the container will see the device file but the TPU won't actually
        # be usable, and Frigate / coral-libs error out at runtime — much
        # later than expected. Audit Tier 6 — `install_coral_lxc.sh` no
        # verifica apex driver cargado.
        if ! lsmod 2>/dev/null | grep -q '^apex'; then
            msg_warn "$(translate 'apex kernel module not loaded on host. Run "Install Coral on Host" first or the container will not see /dev/apex_0.')"
        fi

        local APEX_GID apex_dev_idx
        APEX_GID=$(getent group apex 2>/dev/null | cut -d: -f3 || echo "0")
        apex_dev_idx=$(get_next_dev_index "$CONFIG_FILE")

        if [ -e "/dev/apex_0" ]; then
            # Device is visible — use PVE dev API (works in unprivileged containers).
            # PVE handles cgroup2 permissions automatically.
            if ! grep -q "dev.*apex_0" "$CONFIG_FILE"; then
                echo "dev${apex_dev_idx}: /dev/apex_0,gid=${APEX_GID}" >> "$CONFIG_FILE"
            fi
            msg_ok "$(translate 'Coral M.2 Apex configuration added - device ready')"
        else
            # Device not yet visible (host module not loaded or reboot pending).
            # Use cgroup2 + optional bind-mount as fallback; detect major number
            # dynamically from /proc/devices to avoid hardcoding it.
            local APEX_MAJOR
            APEX_MAJOR=$(awk '/\bapex\b/{print $1}' /proc/devices 2>/dev/null | head -1)
            if [[ -z "$APEX_MAJOR" ]]; then
                # Hardcoded `245` was wrong on kernels that load drivers in
                # different order — dynamic majors vary. Surface the failure
                # so the user knows the cgroup rule won't match and they need
                # to load the apex module first. Audit Tier 6.
                msg_warn "$(translate 'Could not detect apex major number from /proc/devices. Load the apex module first: modprobe apex')"
                APEX_MAJOR=""
            fi
            if [[ -n "$APEX_MAJOR" ]]; then
                if ! grep -q "lxc.cgroup2.devices.allow: c ${APEX_MAJOR}:0 rwm" "$CONFIG_FILE"; then
                    echo "lxc.cgroup2.devices.allow: c ${APEX_MAJOR}:0 rwm # Coral M2 Apex" >> "$CONFIG_FILE"
                fi
            fi
            add_mount_if_needed "/dev/apex_0" "dev/apex_0" "$CONFIG_FILE"
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
        for _ in {1..15}; do
            pct status "$CONTAINER_ID" | grep -q "running" && break
            sleep 1
        done
        if ! pct status "$CONTAINER_ID" | grep -q "running"; then
            msg_error "$(translate 'Container did not start in time.')"; exit 1
        fi
    fi


    stop_spinner

    # Pre-flight: refuse to run on non-Debian-family containers. The
    # apt-get block below would crash with cryptic errors and leave the
    # container half-configured. Audit Tier 6 — `install_coral_lxc.sh`
    # asume Debian/Ubuntu sin distro detection.
    if ! pct exec "$CONTAINER_ID" -- bash -c 'command -v apt-get' &>/dev/null; then
        msg_error "$(translate 'Container does not have apt-get available. Coral driver installation only supports Debian/Ubuntu containers.')"
        return 1
    fi

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
    export DEBIAN_FRONTEND=noninteractive

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