#!/bin/bash

# ProxMenux - Coral TPU Installer (PVE 9.x)
# =========================================
# Author      : MacRimi
# License     : MIT
# Version     : 1.1 (PVE9)
# Last Updated: 25/09/2025
# =========================================

REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# Prompt before installation
pre_install_prompt() {
    if ! dialog --title "$(translate 'Coral TPU Installation')" --yesno "$(translate 'Installing Coral TPU drivers requires rebooting the server after installation. Do you want to proceed?')" 10 70; then
        msg_warn "$(translate 'Installation cancelled by user.')"
        exit 0
    fi
}

# Function to install Coral TPU drivers on PVE 9
install_coral_host() {
    show_proxmenux_logo

    msg_info "$(translate 'Installing build dependencies...')"
    apt-get update -qq
    apt-get install -y git devscripts dh-dkms dkms proxmox-headers-$(uname -r) >/dev/null 2>&1

    cd /tmp
    rm -rf gasket-driver
    git clone https://github.com/google/gasket-driver.git
    if [ $? -ne 0 ]; then
        msg_error "$(translate 'Error: Could not clone the repository.')"
        exit 1
    fi

    cd gasket-driver/

    # === Apply kernel compatibility patches ===
    msg_info "$(translate 'Patching source for kernel compatibility...')"
    # Fix no_llseek -> noop_llseek
    sed -i 's/\.llseek = no_llseek/\.llseek = noop_llseek/' src/gasket_core.c
    # Fix DMA_BUF namespace (with quotes)
    sed -i 's/^MODULE_IMPORT_NS(DMA_BUF);/MODULE_IMPORT_NS("DMA_BUF");/' src/gasket_page_table.c
    # Patch debian/control for Proxmox headers
    sed -i "s/linux-headers-686-pae | linux-headers-amd64 | linux-headers-generic | linux-headers/linux-headers-686-pae | linux-headers-amd64 | linux-headers-generic | linux-headers | proxmox-headers-$(uname -r) | pve-headers-$(uname -r)/" debian/control

    # === Build DKMS package ===
    msg_info "$(translate 'Building DKMS package...')"
    debuild -us -uc -tc -b
    if [ $? -ne 0 ]; then
        msg_error "$(translate 'Error: Failed to build driver packages.')"
        exit 1
    fi

    # === Install DKMS package ===
    msg_info "$(translate 'Installing DKMS package...')"
    dpkg -i ../gasket-dkms_*.deb || true

    # === Compile with DKMS ===
    msg_info "$(translate 'Compiling Coral TPU drivers for current kernel...')"
    dkms add -m gasket -v 1.0 || true
    dkms build -m gasket -v 1.0 -k "$(uname -r)"
    dkms install -m gasket -v 1.0 -k "$(uname -r)"

    # Load modules immediately
    modprobe gasket 2>/dev/null
    modprobe apex 2>/dev/null

    if lsmod | grep -q apex; then
        msg_success "$(translate 'Coral TPU drivers installed and loaded successfully.')"
    else
        msg_warn "$(translate 'Installation finished but drivers are not loaded. Please check dmesg.')"
    fi

    echo -e
}

# Prompt for reboot after installation
restart_prompt() {
    if whiptail --title "$(translate 'Coral TPU Installation')" --yesno "$(translate 'The installation requires a server restart to apply changes. Do you want to restart now?')" 10 70; then
        msg_warn "$(translate 'Restarting the server...')"
        reboot
    else
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
    fi
}

# Main
pre_install_prompt
install_coral_host
restart_prompt
