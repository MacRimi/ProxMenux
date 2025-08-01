#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 04/07/2025
# ==========================================================
# Description:
# This script safely updates your Proxmox VE system and underlying Debian packages
# through an interactive and automated process.
#
# Main features:
# - Repairs and optimizes APT repositories (Proxmox & Debian)
# - Removes duplicate or conflicting sources
# - Switches to the recommended 'no-subscription' Proxmox repository
# - Updates all Proxmox and Debian system packages
# - Installs essential packages if missing (e.g., zfsutils, chrony)
# - Checks for LVM and storage issues and repairs headers if needed
# - Removes conflicting time sync packages automatically
# - Performs a system cleanup after updating (autoremove, autoclean)
# - Provides a summary and prompts for reboot if necessary
#
# The goal of this script is to simplify and secure the update process for Proxmox,
# reduce manual intervention, and prevent common repository and package errors.
# ==========================================================

BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# ==========================================================




OS_CODENAME="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs )"


if [ -z "$OS_CODENAME" ]; then
    OS_CODENAME=$(lsb_release -cs 2>/dev/null || echo "bookworm")
fi

# ======================================================
# Auxiliary functions
# ======================================================

lvm_repair_check() {
    msg_info "$(translate "Checking and repairing old LVM PV headers (if needed)...")"
    
    pvs_output=$(LC_ALL=C pvs -v 2>&1 | grep "old PV header")
    
    if [ -z "$pvs_output" ]; then
        msg_ok "$(translate "No PVs with old headers found.")"
        return
    fi
    
    declare -A vg_map
    
    while read -r line; do
        pv=$(echo "$line" | grep -o '/dev/[^ ]*')
        vg=$(pvs -o vg_name --noheadings "$pv" | awk '{print $1}')
        if [ -n "$vg" ]; then
            vg_map["$vg"]=1
        fi
    done <<< "$pvs_output"
    
    for vg in "${!vg_map[@]}"; do
        msg_warn "$(translate "Old PV header(s) found in VG $vg. Updating metadata...")"
        vgck --updatemetadata "$vg"
        vgchange -ay "$vg"
        if [ $? -ne 0 ]; then
            msg_warn "$(translate "Metadata update failed for VG $vg. Review manually.")"
        else
            msg_ok "$(translate "Metadata updated successfully for VG $vg")"
        fi
    done
}

cleanup_duplicate_repos() {
    local sources_file="/etc/apt/sources.list"
    local temp_file=$(mktemp)
    local cleaned_count=0
    
    declare -A seen_repos
    
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then
            echo "$line" >> "$temp_file"
            continue
        fi
        
        if [[ "$line" =~ ^deb ]]; then
            read -r _ url dist components <<< "$line"
            local key="${url}_${dist}"
            
            if [[ -v "seen_repos[$key]" ]]; then
                echo "# $line" >> "$temp_file"
                cleaned_count=$((cleaned_count + 1))
            else
                echo "$line" >> "$temp_file"
                seen_repos[$key]="$components"
            fi
        else
            echo "$line" >> "$temp_file"
        fi
    done < "$sources_file"
    
    mv "$temp_file" "$sources_file"
    chmod 644 "$sources_file"
    
    local pve_files=(/etc/apt/sources.list.d/*proxmox*.list /etc/apt/sources.list.d/*pve*.list)
    local pve_public_repo="/etc/apt/sources.list.d/pve-public-repo.list"
    local pve_public_repo_exists=false
    local pve_repo_count=0
    
    if [ -f "$pve_public_repo" ] && grep -q "^deb.*pve-no-subscription" "$pve_public_repo"; then
        pve_public_repo_exists=true
        pve_repo_count=1
    fi
    
    for file in "${pve_files[@]}"; do
        if [ -f "$file" ] && grep -q "^deb.*pve-no-subscription" "$file"; then
            if ! $pve_public_repo_exists && [[ "$file" == "$pve_public_repo" ]]; then
                sed -i 's/^# *deb/deb/' "$file"
                pve_public_repo_exists=true
                pve_repo_count=1
            elif [[ "$file" != "$pve_public_repo" ]]; then
                sed -i 's/^deb/# deb/' "$file"
                cleaned_count=$((cleaned_count + 1))
            fi
        fi
    done
    
    if [ $cleaned_count -gt 0 ]; then
        msg_ok "$(translate "Duplicate repositories cleaned: $cleaned_count")"
    fi
    apt update
}

apt_upgrade() {
    local start_time=$(date +%s)
    local log_file="/var/log/proxmox-update-$(date +%Y%m%d-%H%M%S).log"
    local changes_made=false
    

    clear
    show_proxmenux_logo
    echo -e
    msg_title "$(translate "Proxmox system update")"
    

    # ======================================================
    # Basic checks
    # ======================================================
    
    # Check minimum disk space
    local available_space=$(df /var/cache/apt/archives | awk 'NR==2 {print int($4/1024)}')
    if [ "$available_space" -lt 1024 ]; then
        msg_error "$(translate "Insufficient disk space. Available: ${available_space}MB")"
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi
    
    # Check connectivity
    if ! ping -c 1 download.proxmox.com >/dev/null 2>&1; then
        msg_error "$(translate "Cannot reach Proxmox repositories")"
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi
    
    # ======================================================
    # Proxmox repository configuration
    # ======================================================
    
    # Disable enterprise Proxmox repository
    if [ -f /etc/apt/sources.list.d/pve-enterprise.list ] && grep -q "^deb" /etc/apt/sources.list.d/pve-enterprise.list; then
        msg_info "$(translate "Disabling enterprise Proxmox repository...")"
        sed -i "s/^deb/#deb/g" /etc/apt/sources.list.d/pve-enterprise.list
        msg_ok "$(translate "Enterprise Proxmox repository disabled")"
        changes_made=true
    fi
    
    # Disable enterprise Ceph repository
    if [ -f /etc/apt/sources.list.d/ceph.list ] && grep -q "^deb" /etc/apt/sources.list.d/ceph.list; then
        msg_info "$(translate "Disabling enterprise Ceph repository...")"
        sed -i "s/^deb/#deb/g" /etc/apt/sources.list.d/ceph.list
        msg_ok "$(translate "Enterprise Ceph repository disabled")"
        changes_made=true
    fi
    
    # Enable free public repository
    if [ ! -f /etc/apt/sources.list.d/pve-public-repo.list ] || ! grep -q "pve-no-subscription" /etc/apt/sources.list.d/pve-public-repo.list; then
        msg_info "$(translate "Enabling free public Proxmox repository...")"
        echo "deb http://download.proxmox.com/debian/pve ${OS_CODENAME} pve-no-subscription" > /etc/apt/sources.list.d/pve-public-repo.list
        msg_ok "$(translate "Free public Proxmox repository enabled")"
        changes_made=true
    fi
    
    # ======================================================
    # Debian repository configuration
    # ======================================================
    
    local sources_file="/etc/apt/sources.list"
    local debian_changes=false
    
    # Clean up malformed entries first
    if grep -q -E "(debian-security -security|debian main$|debian -updates)" "$sources_file"; then
        msg_info "$(translate "Cleaning malformed repository entries...")"
        
        # Remove malformed lines that cause 404 errors
        sed -i '/^deb.*debian-security -security/d' "$sources_file"
        sed -i '/^deb.*debian main$/d' "$sources_file"
        sed -i '/^deb.*debian -updates/d' "$sources_file"
        debian_changes=true
        msg_ok "$(translate "Cleaning malformed repository sucefull")"
    fi
    
    # Replace old mirrors
    if grep -q "ftp.es.debian.org" "$sources_file"; then
        sed -i 's|ftp.es.debian.org|deb.debian.org|g' "$sources_file"
        debian_changes=true
    fi
    
    # Fix incomplete security repository line
    if grep -q "^deb http://security.debian.org ${OS_CODENAME}-security main contrib$" "$sources_file"; then
        sed -i "s|^deb http://security.debian.org ${OS_CODENAME}-security main contrib$|deb http://security.debian.org/debian-security ${OS_CODENAME}-security main contrib non-free non-free-firmware|" "$sources_file"
        debian_changes=true
    fi
    

    local temp_sources=$(mktemp)
    

    grep -E '^[[:space:]]*#|^[[:space:]]*$' "$sources_file" > "$temp_sources"
    

    cat >> "$temp_sources" << EOF

# Debian ${OS_CODENAME} repositories
deb http://deb.debian.org/debian ${OS_CODENAME} main contrib non-free non-free-firmware
deb http://deb.debian.org/debian ${OS_CODENAME}-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security ${OS_CODENAME}-security main contrib non-free non-free-firmware
EOF
    

    if ! cmp -s "$sources_file" "$temp_sources"; then
        cp "$sources_file" "${sources_file}.backup-$(date +%Y%m%d-%H%M%S)"
        mv "$temp_sources" "$sources_file"
        debian_changes=true
        msg_ok "$(translate "Debian repositories updated")"
    else
        rm "$temp_sources"
    fi
    

    if [ ! -f /etc/apt/apt.conf.d/no-bookworm-firmware.conf ]; then
        echo 'APT::Get::Update::SourceListWarnings::NonFreeFirmware "false";' > /etc/apt/apt.conf.d/no-bookworm-firmware.conf
        debian_changes=true
    fi
    
    if [ "$debian_changes" = true ]; then
        changes_made=true
    fi
    
    # ======================================================
    # Clean duplicate repositories
    # ======================================================
    
    cleanup_duplicate_repos
    
    # ======================================================
    # System update
    # ======================================================
    
    # Update package lists
    if [ "$changes_made" = true ]; then
        msg_info "$(translate "Updating package lists...")"
    else
        msg_info "$(translate "Checking for available updates...")"
    fi
    
    if apt-get update > "$log_file" 2>&1; then
        msg_ok "$(translate "Package lists updated")"
    else
        msg_error "$(translate "Failed to update package lists. Check log: $log_file")"

        echo "$(translate "Repository errors found:")"
        grep -E "Err:|E:" "$log_file" | head -5
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi
    
    # Remove conflicting packages
    local conflicting_packages=$(dpkg -l 2>/dev/null | grep -E "^ii.*(ntp|openntpd|systemd-timesyncd)" | awk '{print $2}')
    if [ -n "$conflicting_packages" ]; then
        msg_info "$(translate "Removing conflicting packages...")"
        DEBIAN_FRONTEND=noninteractive apt-get -y purge $conflicting_packages >> "$log_file" 2>&1
        msg_ok "$(translate "Conflicting packages removed")"
    fi
    
    # Show update information
    local upgradable=$(apt list --upgradable 2>/dev/null | grep -c "upgradable")
    if [ "$upgradable" -gt 0 ]; then
        
        # Show with dialog if available
        if command -v whiptail >/dev/null 2>&1; then
            if whiptail --title "$(translate "Proxmox Update")" \
                       --yesno "$(translate "Found $upgradable packages to upgrade.\n\nProceed with system update?")" 10 60; then
                msg_info "$(translate "Performing system upgrade. This process may take several minutes...")"
            else
                msg_info2 "$(translate "Update cancelled by user")"
                echo -e
                msg_success "$(translate "Press Enter to return to menu...")"
                read -r
                return 0
            fi
        fi
    else
        msg_success "$(translate "System is already up to date")"
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 0
    fi
    
    # Perform update
#    msg_info "$(translate "Performing system upgrade...")"
#    echo "$(translate "This process may take several minutes...")"
    
    # Update with logging
    if DEBIAN_FRONTEND=noninteractive apt-get -y \
        -o Dpkg::Options::='--force-confdef' \
        -o Dpkg::Options::='--force-confold' \
        dist-upgrade >> "$log_file" 2>&1; then
        
        msg_ok "$(translate "System upgrade completed successfully")"
    else
        msg_error "$(translate "System upgrade failed. Check log: $log_file")"
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi
    
    # Install essential Proxmox packages if missing
    local essential_packages=("zfsutils-linux" "proxmox-backup-restore-image" "chrony")
    local missing_packages=()
    
    for package in "${essential_packages[@]}"; do
        if ! dpkg -l 2>/dev/null | grep -q "^ii  $package "; then
            missing_packages+=("$package")
        fi
    done
    
    if [ ${#missing_packages[@]} -gt 0 ]; then
        msg_info "$(translate "Installing essential Proxmox packages...")"
        DEBIAN_FRONTEND=noninteractive apt-get -y install "${missing_packages[@]}" >> "$log_file" 2>&1
        msg_ok "$(translate "Essential Proxmox packages installed")"
    fi
    
    # Check LVM
    lvm_repair_check
    
    # ======================================================
    # Final summary - BEFORE reboot logic
    # ======================================================
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))
    
    echo ""
    echo "$(translate "=== UPDATE COMPLETED ===")"
    echo "$(translate "Duration"): ${minutes}m ${seconds}s"
    echo "$(translate "Log file"): $log_file"
    echo "$(translate "Packages upgraded"): $upgradable"
    echo ""
    
    msg_success "$(translate "Proxmox system update completed successfully")"
    
    
    # ======================================================
    # Reboot logic - After summary
    # ======================================================
    
    # Check if reboot is needed (kernel updates, system packages, etc.)
    NECESSARY_REBOOT=0
    
    # Check for reboot-required file
    if [ -f /var/run/reboot-required ]; then
        NECESSARY_REBOOT=1
    fi
    
    # Check if kernel was updated
    if grep -q "linux-image" "$log_file" 2>/dev/null; then
        NECESSARY_REBOOT=1
    fi
    
    # For system updates, it's generally safer to reboot
    if [ "$upgradable" -gt 0 ]; then
        NECESSARY_REBOOT=1
    fi
    
    if [[ "$NECESSARY_REBOOT" -eq 1 ]]; then
        if command -v whiptail >/dev/null 2>&1; then
            if whiptail --title "$(translate "Reboot Required")" \
                       --yesno "$(translate "Some changes require a reboot to take effect. Do you want to restart now?")" 10 60; then
                
                msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
                apt-get -y autoremove >/dev/null 2>&1
                apt-get -y autoclean >/dev/null 2>&1
                msg_ok "$(translate "Cleanup finished")"
                
                msg_success "$(translate "Press Enter to continue...")"
                read -r
                
                msg_warn "$(translate "Rebooting the system...")"
                reboot
            else
                msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
                apt-get -y autoremove >/dev/null 2>&1
                apt-get -y autoclean >/dev/null 2>&1
                msg_ok "$(translate "Cleanup finished")"
                
                msg_info2 "$(translate "You can reboot later manually.")"
                msg_success "$(translate "Press Enter to continue...")"
                read -r
                return 0
            fi
        else
            # Fallback without whiptail
            echo "$(translate "Reboot now? (y/N): ")"
            read -r -t 30 response
            if [[ "$response" =~ ^[Yy]$ ]]; then
                msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
                apt-get -y autoremove >/dev/null 2>&1
                apt-get -y autoclean >/dev/null 2>&1
                msg_ok "$(translate "Cleanup finished")"
                
                msg_warn "$(translate "Rebooting the system...")"
                sleep 3
                reboot
            else
                msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
                apt-get -y autoremove >/dev/null 2>&1
                apt-get -y autoclean >/dev/null 2>&1
                msg_ok "$(translate "Cleanup finished")"
                
                msg_info2 "$(translate "You can reboot later manually.")"
                return 0
            fi
        fi
    else
        msg_info "$(translate "Removing no longer required packages and purging old cached updates...")"
        apt-get -y autoremove >/dev/null 2>&1
        apt-get -y autoclean >/dev/null 2>&1
        msg_ok "$(translate "Cleanup finished")"
        
        msg_success "$(translate "All changes applied. No reboot required.")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
    fi
    
    return 0
}

# Function to show available update information
check_updates_available() {
    msg_info "$(translate "Checking for available updates...")"
    
    apt-get update >/dev/null 2>&1
    local upgradable=$(apt list --upgradable 2>/dev/null | grep -c "upgradable")
    local security_updates=$(apt list --upgradable 2>/dev/null | grep -c "security")
    
    if [ "$upgradable" -gt 0 ]; then
        echo "$(translate "Updates available"): $upgradable"
        echo "$(translate "Security updates"): $security_updates"
        cleanup 
        if command -v whiptail >/dev/null 2>&1; then
            whiptail --title "$(translate "Updates Available")" \
                    --msgbox "$(translate "Updates available: $upgradable\nSecurity updates: $security_updates\n\nUse the update option to proceed.")" 12 60
        fi
    else
        msg_ok "$(translate "System is up to date")"
    fi
}

# Execute function based on parameter
case "${1:-}" in
    "check")
        check_updates_available
        ;;
    "")
        apt_upgrade
        ;;
    *)
        echo "$(translate "Usage: $0 [check]")"
        echo "$(translate "  check - Check for available updates")"
        echo "$(translate "  (no args) - Perform full system update")"
        ;;
esac