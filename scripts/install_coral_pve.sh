#!/bin/bash


# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 28/01/2025
# ==========================================================
# Description:
# This script installs the Coral TPU drivers on the Proxmox VE host.
# It ensures that necessary packages are installed and compiles the
# Coral TPU drivers for proper functionality.
# ==========================================================


# Configuration ============================================
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


# Prompt before installation
pre_install_prompt() {
    if ! whiptail --title "$(translate 'Coral TPU Installation')" --yesno "$(translate 'Installing Coral TPU drivers requires rebooting the server after installation. Do you want to proceed?')" 10 70; then
        msg_warn "$(translate 'Installation cancelled by user.')"
        exit 0
    fi
}

# Verify and configure repositories on the host
verify_and_add_repos() {
    msg_info "$(translate 'Configuring necessary repositories on the host...')"
    sleep 2

    if ! grep -q "pve-no-subscription" /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null; then
        echo "deb http://download.proxmox.com/debian/pve $(lsb_release -sc) pve-no-subscription" | tee /etc/apt/sources.list.d/pve-no-subscription.list
        msg_ok "$(translate 'pve-no-subscription repository added.')"
    fi

    if ! grep -q "non-free-firmware" /etc/apt/sources.list; then
        echo "deb http://deb.debian.org/debian $(lsb_release -sc) main contrib non-free-firmware
        deb http://deb.debian.org/debian $(lsb_release -sc)-updates main contrib non-free-firmware
        deb http://security.debian.org/debian-security $(lsb_release -sc)-security main contrib non-free-firmware" | tee -a /etc/apt/sources.list
        msg_ok "$(translate 'non-free-firmware repositories added.')"
    fi

    msg_ok "$(translate 'Added repositories')"
    sleep 2

    msg_info "$(translate 'Verifying repositories...')"
    apt-get update &>/dev/null

    msg_ok "$(translate 'Verified and updated repositories.')"
}

# Function to install Coral TPU drivers on the host
install_coral_host() {
    show_proxmenux_logo
    verify_and_add_repos

    apt-get install -y git devscripts dh-dkms dkms pve-headers-$(uname -r) >/dev/null 2>&1

    cd /tmp
    rm -rf gasket-driver
    git clone https://github.com/google/gasket-driver.git
    if [ $? -ne 0 ]; then
        msg_error "$(translate 'Error: Could not clone the repository.')"
        exit 1
    fi

    cd gasket-driver/
    debuild -us -uc -tc -b
    if [ $? -ne 0 ]; then
        msg_error "$(translate 'Error: Failed to build driver packages.')"
        exit 1
    fi

    dpkg -i ../gasket-dkms_*.deb
    if [ $? -ne 0 ]; then
        msg_error "$(translate 'Error: Failed to install the driver packages.')"
        exit 1
    fi

    msg_success "$(translate 'Coral TPU drivers installed successfully on the host.')"
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


pre_install_prompt
install_coral_host
restart_prompt
