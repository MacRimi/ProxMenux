#!/bin/bash
# ==========================================================
# ProxMenux - Coral TPU Passthrough to LXC
# ==========================================================
# Author      : MacRimi
# Revision    : @Blaspt (USB passthrough via udev rule)
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.5
# Last Updated: 27/05/2026
# ==========================================================
# Description:
# Configures and installs Coral TPU passthrough (USB and
# M.2 / PCIe) in a Proxmox LXC container. Writes the needed
# dev / cgroup / mount entries into the LXC config, then
# boots the container and installs the Edge TPU runtime
# inside it so apps like Frigate can actually use the TPU.
#
# Scope:
#  - This script is TPU-only. GPU / iGPU passthrough (Intel
#    Quick Sync, AMD VA-API, NVIDIA) is delegated to
#    add_gpu_lxc.sh — the script suggests running it first
#    when a host GPU is detected but the container has no
#    GPU configured.
#
# Features:
#  - Container picker via `dialog` (matches add_gpu_lxc.sh)
#  - Coral USB passthrough only when a Coral USB device is
#    actually present on the host (avoids leaving orphan
#    cgroup/mount entries when only M.2 is used)
#  - Auto-detects M.2 via lspci (Global Unichip)
#  - USB passthrough mounts /dev/bus/usb (not the dynamic
#    /dev/coral symlink) so the CT sees the real node even
#    if the user replugs the device
#  - PCIe/M.2 uses the PVE dev API (devN: /dev/apex_0,gid=apex)
#    which handles cgroup2 permissions automatically for
#    privileged and unprivileged containers
#  - Migrates legacy Coral entries (old cgroup2 + bind mount
#    pairs) to the PVE dev API on every run
#  - Inside container: adds Google Coral APT repo and
#    installs libedgetpu1-std (default) or -max (optional)
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
# CONTAINER SELECTION (dialog — matches add_gpu_lxc.sh)
# ==========================================================

select_container() {
    local menu_items=()
    while IFS= read -r line; do
        [[ "$line" =~ ^VMID ]] && continue
        local ctid status name
        ctid=$(echo "$line" | awk '{print $1}')
        status=$(echo "$line" | awk '{print $2}')
        name=$(echo "$line" | awk '{print $3}')
        [[ -z "$ctid" ]] && continue
        menu_items+=("$ctid" "${name:-CT-${ctid}} (${status})")
    done < <(pct list 2>/dev/null)

    if [[ ${#menu_items[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" \
            --title "$(translate 'Install Coral TPU in LXC')" \
            --msgbox "\n$(translate 'No LXC containers found on this system.')" 8 60
        exit 0
    fi

    CONTAINER_ID=$(dialog --backtitle "ProxMenux" \
        --title "$(translate 'Install Coral TPU in LXC')" \
        --menu "\n$(translate 'Select the LXC container:')" 20 72 12 \
        "${menu_items[@]}" \
        2>&1 >/dev/tty) || exit 0

    if ! pct list | awk 'NR>1 {print $1}' | grep -qw "$CONTAINER_ID"; then
        msg_error "$(translate 'Container with ID') $CONTAINER_ID $(translate 'does not exist. Exiting.')"
        exit 1
    fi
}

validate_container_id() {
    if [ -z "$CONTAINER_ID" ]; then
        msg_error "$(translate 'Container ID not defined. Make sure to select a container first.')"
        exit 1
    fi

    CT_WAS_RUNNING=false
    if pct status "$CONTAINER_ID" | grep -q "running"; then
        CT_WAS_RUNNING=true
        msg_info "$(translate 'Stopping the container before applying configuration...')"
        pct stop "$CONTAINER_ID"
        msg_ok "$(translate 'Container stopped.')"
    fi
}

# ==========================================================
# GPU PASSTHROUGH SUGGESTION
# ==========================================================
# Coral is typically paired with Quick Sync / NVENC for Frigate. If the host
# has a GPU but the container has no GPU configured, suggest the user to run
# Add GPU to LXC first — that's the right script for that job.
# ==========================================================

suggest_gpu_passthrough_if_needed() {
    local cfg="/etc/pve/lxc/${CONTAINER_ID}.conf"
    [[ -f "$cfg" ]] || return 0

    local host_has_gpu=false vendor_label=""
    if lspci 2>/dev/null | grep -iE "VGA compatible|3D controller|Display controller" \
        | grep -qi "Intel"; then
        host_has_gpu=true
        vendor_label="Intel iGPU"
    fi
    if lspci 2>/dev/null | grep -iE "VGA compatible|3D controller|Display controller" \
        | grep -qiE "AMD|Advanced Micro|Radeon"; then
        host_has_gpu=true
        vendor_label="${vendor_label:+$vendor_label / }AMD GPU"
    fi
    if lspci 2>/dev/null | grep -iE "VGA compatible|3D controller|Display controller" \
        | grep -qi "NVIDIA"; then
        host_has_gpu=true
        vendor_label="${vendor_label:+$vendor_label / }NVIDIA GPU"
    fi

    $host_has_gpu || return 0

    # CT already has a GPU configured? Check both the modern dev API and the
    # legacy lxc.mount.entry / cgroup formats. If any GPU device shows up,
    # assume the user already handled it and skip the suggestion.
    if grep -qE '^dev[0-9]+:[[:space:]]*/dev/(dri|nvidia|kfd)' "$cfg" 2>/dev/null \
        || grep -qE '^lxc\.mount\.entry:[[:space:]]*/dev/(dri|nvidia|kfd)' "$cfg" 2>/dev/null \
        || grep -qE '^lxc\.cgroup2\.devices\.allow:[[:space:]]+c[[:space:]]+(226|195):' "$cfg" 2>/dev/null; then
        return 0
    fi

    local msg
    msg="\n$(translate 'Host GPU detected'): ${vendor_label}\n\n"
    msg+="$(translate 'This container has no GPU configured. Coral TPU works best alongside hardware video decoding (Quick Sync, VA-API, NVENC) for apps like Frigate.')\n\n"
    msg+="$(translate 'Recommended: run')  \"$(translate 'Add GPU to LXC')\"  $(translate 'from the GPUs and Coral-TPU menu first, then run this option again.')\n\n"
    msg+="$(translate 'Continue with Coral TPU configuration only?')"

    dialog --backtitle "ProxMenux" \
        --title "$(translate 'GPU Passthrough Not Configured')" \
        --yesno "$msg" 16 78
    [[ $? -ne 0 ]] && exit 0
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
        # rules in this file survive.
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
    local TEMP_FILE
    TEMP_FILE=$(mktemp)

    awk '!seen[$0]++' "$CONFIG_FILE" > "$TEMP_FILE"

    cat "$TEMP_FILE" > "$CONFIG_FILE"
    rm -f "$TEMP_FILE"
}

# ==========================================================
# CLEANUP LEGACY CORAL M.2 ENTRIES
# ==========================================================
# Older versions of this script (and some manual setups) used the legacy
# `lxc.mount.entry: /dev/apex_0 ...` + `lxc.cgroup2.devices.allow: c <maj>:0 rwm`
# pair for Coral M.2. That pair is superseded by the PVE dev API (devN:)
# which handles cgroup2 permissions automatically and works in unprivileged
# containers. Remove the legacy pair so the new dev API entry doesn't stack
# alongside duplicates.
#
# NEVER touch USB-related entries (/dev/coral, /dev/bus/usb, c 189:* rwm)
# and NEVER touch lines unrelated to Coral (ttyUSB, ttyACM, serial, etc.) —
# those belong to the user / other scripts.
# ==========================================================

cleanup_old_coral_m2_entries() {
    local CONFIG_FILE="$1"
    [[ -f "$CONFIG_FILE" ]] || return 0

    # Only run when we just installed (or are about to install) /dev/apex_0
    # via the modern dev API. Without that guard we'd strip the legacy
    # entries on hosts that legitimately still rely on them.
    grep -qE '^dev[0-9]+:[[:space:]]*/dev/apex_0' "$CONFIG_FILE" || return 0

    # Take a one-shot backup so the user can recover if anything goes wrong.
    local BACKUP="${CONFIG_FILE}.proxmenux-coral.bak"
    if [[ ! -f "$BACKUP" ]]; then
        cp -a "$CONFIG_FILE" "$BACKUP"
    fi

    sed -i '/^lxc\.mount\.entry:[[:space:]]*\/dev\/apex_0[[:space:]]/d' "$CONFIG_FILE"
    sed -i '/^lxc\.cgroup2\.devices\.allow:[[:space:]]*c[[:space:]]\+[0-9]\+:0[[:space:]]\+rwm[[:space:]]*#[[:space:]]*Coral M2 Apex/d' "$CONFIG_FILE"
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
# CONFIGURE LXC CORAL PASSTHROUGH
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
    # Enable nesting feature (needed for Coral userspace tooling)
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
    # Coral USB passthrough — kept untouched on purpose. User said this
    # part can stay exactly as-is regardless of whether a Coral USB is
    # connected now: the udev rule + cgroup + /dev/bus/usb mount are
    # harmless if no USB device is present and let the user plug one in
    # later without re-running this script.
    # ============================================================
    msg_info "$(translate 'Configuring Coral USB support...')"

    add_udev_rule_for_coral_usb

    if ! grep -Pq "^lxc.cgroup2.devices.allow: c 189:\\\* rwm" "$CONFIG_FILE"; then
        echo "lxc.cgroup2.devices.allow: c 189:* rwm # Coral USB" >> "$CONFIG_FILE"
    fi

    # FIX v1.3: Mount /dev/bus/usb instead of the /dev/coral symlink.
    # The udev symlink /dev/coral points to a dynamic path
    # (e.g. /dev/bus/usb/001/005) that changes on reconnect — passing
    # it through directly is unreliable. Mounting the USB bus tree
    # makes the real device node available regardless of port.
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
        # later than expected.
        if ! lsmod 2>/dev/null | grep -q '^apex'; then
            msg_warn "$(translate 'apex kernel module not loaded on host. Run "Install Coral on Host" first or the container will not see /dev/apex_0.')"
        fi

        local APEX_GID apex_dev_idx
        APEX_GID=$(getent group apex 2>/dev/null | cut -d: -f3 || echo "0")
        apex_dev_idx=$(get_next_dev_index "$CONFIG_FILE")

        if [ -e "/dev/apex_0" ]; then
            # Device is visible — use PVE dev API (works in unprivileged containers).
            # PVE handles cgroup2 permissions automatically.
            if ! grep -qE "^dev[0-9]+:[[:space:]]*/dev/apex_0" "$CONFIG_FILE"; then
                echo "dev${apex_dev_idx}: /dev/apex_0,gid=${APEX_GID}" >> "$CONFIG_FILE"
            fi
            # Migrate legacy M.2 entries (cgroup2 + bind-mount pair) that
            # pre-dated the dev API on this CT. USB entries are NOT touched.
            cleanup_old_coral_m2_entries "$CONFIG_FILE"
            msg_ok "$(translate 'Coral M.2 Apex configuration added - device ready')"
        else
            # Device not yet visible (host module not loaded or reboot pending).
            # Use cgroup2 + optional bind-mount as fallback; detect major number
            # dynamically from /proc/devices to avoid hardcoding it.
            local APEX_MAJOR
            APEX_MAJOR=$(awk '/\bapex\b/{print $1}' /proc/devices 2>/dev/null | head -1)
            if [[ -z "$APEX_MAJOR" ]]; then
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

    # Final pass: drop any duplicates we may have introduced
    cleanup_duplicate_entries "$CONFIG_FILE"

    msg_ok "$(translate 'Coral hardware configuration completed for container') $CONTAINER_ID"
}

# ==========================================================
# INSTALL CORAL TPU DRIVER INSIDE CONTAINER
# ==========================================================

# Detect the package family inside the container. The PVE passthrough
# config (above) works on any distro, but Google only ships an official
# libedgetpu APT repo for Debian/Ubuntu. For other distros we configure
# the device and skip the runtime install with a clear message.
detect_container_distro() {
    local id_like id
    id=$(pct exec "$CONTAINER_ID" -- sh -c 'awk -F= "/^ID=/{gsub(/\"/, \"\", \$2); print \$2}" /etc/os-release 2>/dev/null' 2>/dev/null | tr -d '\r' | tr '[:upper:]' '[:lower:]')
    id_like=$(pct exec "$CONTAINER_ID" -- sh -c 'awk -F= "/^ID_LIKE=/{gsub(/\"/, \"\", \$2); print \$2}" /etc/os-release 2>/dev/null' 2>/dev/null | tr -d '\r' | tr '[:upper:]' '[:lower:]')
    case "$id" in
        debian|ubuntu|raspbian|linuxmint|pop|kali|devuan) echo "debian"; return ;;
        alpine) echo "alpine"; return ;;
        arch|manjaro|endeavouros|garuda|cachyos) echo "arch"; return ;;
        rhel|centos|rocky|almalinux|fedora|amzn|ol) echo "rhel"; return ;;
        opensuse*|sles|suse) echo "suse"; return ;;
    esac
    case "$id_like" in
        *debian*|*ubuntu*) echo "debian"; return ;;
        *arch*) echo "arch"; return ;;
        *rhel*|*fedora*|*centos*) echo "rhel"; return ;;
        *suse*) echo "suse"; return ;;
    esac
    echo "unknown"
}

install_coral_in_container() {
    msg_info "$(translate 'Installing Coral TPU driver inside the container...')"
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

    # Detect the container distro. Passthrough config (already written to
    # /etc/pve/lxc/<id>.conf above) works on any distro — only the libedgetpu
    # runtime install path is distro-specific, and Google's official APT repo
    # only covers Debian/Ubuntu. For other distros offer an opt-in
    # passthrough-only mode (skip the apt-get install, leave the device
    # visible inside the CT so app-level runtimes can use it, e.g. the
    # Frigate Docker image bundles libedgetpu). If the user declines,
    # behave exactly like the pre-detection version: error out and abort.
    local CT_FAMILY
    CT_FAMILY=$(detect_container_distro)

    if [[ "$CT_FAMILY" != "debian" ]]; then
        rm -f "$LOG_FILE"
        local distro_label
        case "$CT_FAMILY" in
            alpine) distro_label="Alpine" ;;
            arch)   distro_label="Arch / Manjaro" ;;
            rhel)   distro_label="RHEL / Rocky / AlmaLinux / Fedora" ;;
            suse)   distro_label="openSUSE / SLES" ;;
            *)      distro_label="$(translate 'this distribution')" ;;
        esac

        # whiptail (not dialog) — prompt sits in the middle of the install
        # flow. Default is "No" so a user who just presses Enter / Esc lands
        # on the same abort path as the legacy behaviour.
        if ! whiptail --title "$(translate 'Non-Debian container detected')" --defaultno \
            --yesno "$(translate 'Detected:') $distro_label

$(translate 'Google only ships an official libedgetpu APT repository for Debian/Ubuntu. Hardware passthrough is already written to')  /etc/pve/lxc/${CONTAINER_ID}.conf  $(translate '— that part works on any distro and is harmless.')

$(translate 'Would you like to continue in passthrough-only mode? The libedgetpu APT install will be skipped, the Coral device will still be visible inside the container (e.g. /dev/apex_0), and you can install the runtime yourself or use an app container that bundles it (e.g. the Frigate Docker image).')

$(translate 'Choose No to abort and roll back to the legacy refuse behaviour.')" 22 78 \
            3>&1 1>&2 2>&3; then
            msg_error "$(translate 'Container does not have apt-get available. Coral driver installation only supports Debian/Ubuntu containers.')"
            return 1
        fi

        msg_warn "$(translate 'Container distro') ($distro_label) $(translate 'is not supported by the official Google libedgetpu APT repository.')"
        msg_ok "$(translate 'Hardware passthrough is already configured — the Coral device is visible inside the container as /dev/apex_0 (M.2) and/or /dev/bus/usb (USB).')"
        msg_info2 "$(translate 'To use Coral from a regular app, install the libedgetpu runtime via the usual method for your distro (community package or build from source). The simplest path is to run an app container that bundles the runtime — e.g. the Frigate Docker image — passing the device through with')  --device /dev/apex_0:/dev/apex_0"
        return 0
    fi

    # Determine driver package for Coral M.2 (USB always uses -std).
    # whiptail (not dialog) because this prompt appears in the middle of
    # the install flow — project convention is dialog for initial menus,
    # whiptail for mid-flow prompts.
    CORAL_M2=$(lspci | grep -i "Global Unichip")
    if [[ -n "$CORAL_M2" ]]; then
        DRIVER_OPTION=$(whiptail --title "$(translate 'Select driver version')" \
            --menu "$(translate 'Choose the driver version for Coral M.2:')\n\n$(translate 'Caution: Maximum mode generates more heat.')" 15 60 2 \
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

    # Install driver inside container — TPU only, no iGPU userspace.
    # iGPU drivers (va-driver-all, intel-opencl-icd, vainfo, etc.) are
    # the job of add_gpu_lxc.sh. Keeping this script focused on TPU.
    #
    # Repository layout matches install_coral.sh on the host:
    #   keyring  : /etc/apt/keyrings/coral-edgetpu.gpg
    #   list file: /etc/apt/sources.list.d/coral-edgetpu.list
    #   line     : deb [signed-by=<keyring>] https://packages.cloud.google.com/apt coral-edgetpu-stable main
    # `apt-get install` (no version pin) always picks the latest libedgetpu
    # available in the coral-edgetpu-stable channel, in sync with the host.
    script -q -c "pct exec \"$CONTAINER_ID\" -- bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive

    echo \"[1/3] Updating package lists...\"
    apt-get update -qq

    echo \"[2/3] Setting up the Google Coral APT repository...\"
    apt-get install -y -qq gnupg curl ca-certificates
    mkdir -p /etc/apt/keyrings
    if [ ! -s /etc/apt/keyrings/coral-edgetpu.gpg ]; then
        curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
            | gpg --dearmor -o /etc/apt/keyrings/coral-edgetpu.gpg
        chmod 0644 /etc/apt/keyrings/coral-edgetpu.gpg
    fi
    echo \"deb [signed-by=/etc/apt/keyrings/coral-edgetpu.gpg] https://packages.cloud.google.com/apt coral-edgetpu-stable main\" \
        | tee /etc/apt/sources.list.d/coral-edgetpu.list >/dev/null
    apt-get update -qq

    echo \"[3/3] Installing latest Coral TPU runtime ($DRIVER_PACKAGE)...\"
    apt-get install -y -qq $DRIVER_PACKAGE

    '" "$LOG_FILE" 2>&1

    if [ $? -eq 0 ]; then
        tput rc
        tput ed
        rm -f "$LOG_FILE"
        msg_ok "$(translate 'Coral TPU driver installed successfully inside the container.')"
    else
        tput rc
        tput ed
        msg_error "$(translate 'Failed to install Coral TPU driver inside the container.')"
        echo ""
        echo "$(translate 'Installation log:')"
        cat "$LOG_FILE"
        rm -f "$LOG_FILE"
        exit 1
    fi
}

# ==========================================================
# VERIFICATION AND SUMMARY (Coral only)
# ==========================================================

show_configuration_summary() {
    local CONFIG_FILE="/etc/pve/lxc/${CONTAINER_ID}.conf"

    # Coral USB
    if grep -q "c 189:.*rwm.*Coral USB" "$CONFIG_FILE"; then
        if [ -L "/dev/coral" ]; then
            msg_ok2 "✓ Coral USB: $(translate 'Enabled and detected')"
        else
            msg_ok2 "⚠ Coral USB: $(translate 'Enabled but not connected')"
        fi
    fi

    # Coral M.2 — either via dev API or legacy cgroup2 entry
    local m2_configured=false
    if grep -qE "^dev[0-9]+:[[:space:]]*/dev/apex_0" "$CONFIG_FILE"; then
        m2_configured=true
    elif grep -qE "^lxc\.cgroup2\.devices\.allow:[[:space:]]+c[[:space:]]+[0-9]+:0[[:space:]]+rwm.*Coral M2" "$CONFIG_FILE"; then
        m2_configured=true
    fi

    if $m2_configured; then
        if [ -e "/dev/apex_0" ]; then
            msg_ok2 "✓ Coral M.2: $(translate 'Enabled and ready')"
        else
            msg_ok2 "⚠ Coral M.2: $(translate 'Enabled (device pending — load apex module or reboot)')"
        fi
    fi
}

# ==========================================================
# MAIN EXECUTION
# ==========================================================

main() {
    select_container
    suggest_gpu_passthrough_if_needed
    show_proxmenux_logo
    configure_lxc_hardware
    install_coral_in_container
    show_configuration_summary

    # If the CT was running before we started, leave it running. Otherwise
    # stop it again so we don't change the user's previous state.
    if [[ "$CT_WAS_RUNNING" == "false" ]]; then
        if pct status "$CONTAINER_ID" 2>/dev/null | grep -q "running"; then
            pct stop "$CONTAINER_ID" >/dev/null 2>&1 || true
        fi
    fi

    msg_ok "$(translate 'Configuration completed successfully!')"
    echo ""
    msg_success "$(translate 'Press Enter to return to menu...')"
    read -r
}

# Run main function
main
