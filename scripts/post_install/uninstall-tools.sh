#!/bin/bash
# ==========================================================
# ProxMenux - Complete Uninstall Optimizations Script
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 06/07/2025
# ==========================================================
# Description:
# This script provides a complete uninstallation and rollback system 
# for all post-installation optimizations applied by ProxMenux.
#
# It allows administrators to safely revert any changes made during the 
# optimization process, restoring the system to its original state.
#
# This ensures full control over system configurations and gives users 
# the confidence to apply, test, and undo ProxMenux enhancements as needed.
# ==========================================================


REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
RETURN_SCRIPT="$REPO_URL/scripts/menus/menu_post_install.sh"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
TOOLS_JSON="$BASE_DIR/installed_tools.json"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# Tool registration system
ensure_tools_json() {
    [ -f "$TOOLS_JSON" ] || echo "{}" > "$TOOLS_JSON"
}

register_tool() {
    local tool="$1"
    local state="$2"
    ensure_tools_json
    jq --arg t "$tool" --argjson v "$state" '.[$t]=$v' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
}

################################################################

uninstall_fastfetch() {
    if ! command -v fastfetch &>/dev/null && [[ ! -f /usr/local/bin/fastfetch ]]; then
        msg_warn "$(translate "Fastfetch is not installed.")"
        return 0
    fi

    msg_info2 "$(translate "Uninstalling Fastfetch...")"
    rm -f /usr/local/bin/fastfetch /usr/bin/fastfetch
    rm -rf "$HOME/.config/fastfetch"
    rm -rf /usr/local/share/fastfetch
    sed -i '/fastfetch/d' "$HOME/.bashrc" "$HOME/.profile" /etc/profile 2>/dev/null
    rm -f /etc/profile.d/fastfetch.sh /etc/update-motd.d/99-fastfetch
    dpkg -r fastfetch &>/dev/null

    msg_ok "$(translate "Fastfetch removed from system")"
    register_tool "fastfetch" false
}

################################################################

uninstall_figurine() {
    if ! command -v figurine &>/dev/null; then
        msg_warn "$(translate "Figurine is not installed.")"
        return 0
    fi

    msg_info2 "$(translate "Uninstalling Figurine...")"
    rm -f /usr/local/bin/figurine
    rm -f /etc/profile.d/figurine.sh
    sed -i '/figurine/d' "$HOME/.bashrc" "$HOME/.profile" 2>/dev/null

    msg_ok "$(translate "Figurine removed from system")"
    register_tool "figurine" false
}

################################################################

uninstall_kexec() {
    if ! dpkg -s kexec-tools >/dev/null 2>&1 && [ ! -f /etc/systemd/system/kexec-pve.service ]; then
        msg_warn "$(translate "kexec-tools is not installed or already removed.")"
        return 0
    fi

    msg_info2 "$(translate "Uninstalling kexec-tools and removing custom service...")"
    systemctl disable --now kexec-pve.service &>/dev/null
    rm -f /etc/systemd/system/kexec-pve.service
    sed -i "/alias reboot-quick='systemctl kexec'/d" /root/.bash_profile
    apt-get purge -y kexec-tools >/dev/null 2>&1

    msg_ok "$(translate "kexec-tools and related settings removed")"
    register_tool "kexec" false
}

################################################################

uninstall_apt_upgrade() {
    msg_info "$(translate "Restoring enterprise repositories...")"
    
    # Re-enable enterprise repos
    if [ -f /etc/apt/sources.list.d/pve-enterprise.list ]; then
        sed -i "s/^#deb/deb/g" /etc/apt/sources.list.d/pve-enterprise.list
    fi
    
    if [ -f /etc/apt/sources.list.d/ceph.list ]; then
        sed -i "s/^#deb/deb/g" /etc/apt/sources.list.d/ceph.list
    fi
    
    # Remove public repo
    rm -f /etc/apt/sources.list.d/pve-public-repo.list
    
    # Remove firmware warning config
    rm -f /etc/apt/apt.conf.d/no-bookworm-firmware.conf
    
    apt-get update > /dev/null 2>&1
    
    msg_ok "$(translate "Enterprise repositories restored")"
    register_tool "apt_upgrade" false
}

################################################################

uninstall_subscription_banner() {
    msg_info "$(translate "Restoring subscription banner...")"
    
    # Remove APT hook
    rm -f /etc/apt/apt.conf.d/no-nag-script
    
    # Reinstall proxmox-widget-toolkit to restore original
    apt --reinstall install proxmox-widget-toolkit -y >/dev/null 2>&1
    
    msg_ok "$(translate "Subscription banner restored")"
    register_tool "subscription_banner" false
}

################################################################

uninstall_time_sync() {
    msg_info "$(translate "Resetting time synchronization...")"
    
    # Reset to UTC (safe default)
    timedatectl set-timezone UTC >/dev/null 2>&1
    
    msg_ok "$(translate "Time synchronization reset to UTC")"
    register_tool "time_sync" false
}

################################################################

uninstall_apt_languages() {
    msg_info "$(translate "Restoring APT language downloads...")"
    
    # Remove the configuration that disables translations
    rm -f /etc/apt/apt.conf.d/99-disable-translations
    
    msg_ok "$(translate "APT language downloads restored")"
    register_tool "apt_languages" false
}

################################################################

uninstall_journald() {
    msg_info "$(translate "Restoring default journald configuration...")"
    
    # Restore default journald configuration
    cat > /etc/systemd/journald.conf << 'EOF'
#  This file is part of systemd.
#
#  systemd is free software; you can redistribute it and/or modify it
#  under the terms of the GNU Lesser General Public License as published by
#  the Free Software Foundation; either version 2.1 of the License, or
#  (at your option) any later version.
#
# Entries in this file show the compile time defaults.
# You can change settings by editing this file.
# Defaults can be restored by simply deleting this file.
#
# See journald.conf(5) for details.

[Journal]
#Storage=auto
#Compress=yes
#Seal=yes
#SplitMode=uid
#SyncIntervalSec=5m
#RateLimitInterval=30s
#RateLimitBurst=1000
#SystemMaxUse=
#SystemKeepFree=
#SystemMaxFileSize=
#RuntimeMaxUse=
#RuntimeKeepFree=
#RuntimeMaxFileSize=
#MaxRetentionSec=
#MaxFileSec=1month
#ForwardToSyslog=yes
#ForwardToKMsg=no
#ForwardToConsole=no
#ForwardToWall=yes
#TTYPath=/dev/console
#MaxLevelStore=debug
#MaxLevelSyslog=debug
#MaxLevelKMsg=notice
#MaxLevelConsole=info
#MaxLevelWall=emerg
EOF
    
    systemctl restart systemd-journald.service >/dev/null 2>&1
    
    msg_ok "$(translate "Default journald configuration restored")"
    register_tool "journald" false
}

################################################################

uninstall_logrotate() {
    msg_info "$(translate "Restoring original logrotate configuration...")"
    
    # Restore from backup if it exists
    if [ -f /etc/logrotate.conf.bak ]; then
        mv /etc/logrotate.conf.bak /etc/logrotate.conf
        systemctl restart logrotate >/dev/null 2>&1
        msg_ok "$(translate "Original logrotate configuration restored")"
    else
        msg_warn "$(translate "No backup found, logrotate configuration not changed")"
    fi
    
    register_tool "logrotate" false
}

################################################################

uninstall_system_limits() {
    msg_info "$(translate "Removing system limits optimizations...")"
    
    # Remove ProxMenux sysctl configurations
    rm -f /etc/sysctl.d/99-maxwatches.conf
    rm -f /etc/sysctl.d/99-maxkeys.conf
    rm -f /etc/sysctl.d/99-swap.conf
    rm -f /etc/sysctl.d/99-fs.conf
    
    # Remove ProxMenux limits configuration
    rm -f /etc/security/limits.d/99-limits.conf
    
    # Remove systemd limits (restore defaults)
    for file in /etc/systemd/system.conf /etc/systemd/user.conf; do
        if [ -f "$file" ]; then
            sed -i '/^DefaultLimitNOFILE=256000/d' "$file"
        fi
    done
    
    # Remove PAM limits
    for file in /etc/pam.d/common-session /etc/pam.d/runuser-l; do
        if [ -f "$file" ]; then
            sed -i '/^session required pam_limits.so/d' "$file"
        fi
    done
    
    # Remove ulimit from profile
    if [ -f /root/.profile ]; then
        sed -i '/ulimit -n 256000/d' /root/.profile
    fi
    
    # Reload sysctl
    sysctl --system >/dev/null 2>&1
    
    msg_ok "$(translate "System limits optimizations removed")"
    register_tool "system_limits" false
}

################################################################

uninstall_entropy() {
    msg_info "$(translate "Removing entropy generation optimization...")"
    
    # Stop and disable haveged
    systemctl stop haveged >/dev/null 2>&1
    systemctl disable haveged >/dev/null 2>&1
    
    # Remove haveged package
    apt-get purge -y haveged >/dev/null 2>&1
    
    # Remove configuration
    rm -f /etc/default/haveged
    
    msg_ok "$(translate "Entropy generation optimization removed")"
    register_tool "entropy" false
}

################################################################

uninstall_memory_settings() {
    msg_info "$(translate "Removing memory optimizations...")"
    
    # Remove ProxMenux memory configuration
    rm -f /etc/sysctl.d/99-memory.conf
    
    # Reload sysctl
    sysctl --system >/dev/null 2>&1
    
    msg_ok "$(translate "Memory optimizations removed")"
    register_tool "memory_settings" false
}

################################################################

uninstall_kernel_panic() {
    msg_info "$(translate "Removing kernel panic configuration...")"
    
    # Remove ProxMenux kernel panic configuration
    rm -f /etc/sysctl.d/99-kernelpanic.conf
    
    # Reload sysctl
    sysctl --system >/dev/null 2>&1
    
    msg_ok "$(translate "Kernel panic configuration removed")"
    register_tool "kernel_panic" false
}

################################################################

uninstall_apt_ipv4() {
    msg_info "$(translate "Removing APT IPv4 configuration...")"
    
    # Remove IPv4 force configuration
    rm -f /etc/apt/apt.conf.d/99-force-ipv4
    
    msg_ok "$(translate "APT IPv4 configuration removed")"
    register_tool "apt_ipv4" false
}

################################################################

uninstall_network_optimization() {
    msg_info "$(translate "Removing network optimizations...")"
    
    # Remove ProxMenux network configuration
    rm -f /etc/sysctl.d/99-network.conf
    
    # Remove interfaces.d source line if we added it
    local interfaces_file="/etc/network/interfaces"
    if [ -f "$interfaces_file" ]; then
        # Only remove if it's the last line and looks like our addition
        if tail -1 "$interfaces_file" | grep -q "^source /etc/network/interfaces.d/\*$"; then
            sed -i '$d' "$interfaces_file"
        fi
    fi
    
    # Reload sysctl
    sysctl --system >/dev/null 2>&1
    
    msg_ok "$(translate "Network optimizations removed")"
    register_tool "network_optimization" false
}

################################################################

uninstall_disable_rpc() {
    msg_info "$(translate "Re-enabling RPC services...")"
    
    # Re-enable and start rpcbind
    systemctl enable rpcbind >/dev/null 2>&1
    systemctl start rpcbind >/dev/null 2>&1
    
    msg_ok "$(translate "RPC services re-enabled")"
    register_tool "disable_rpc" false
}

################################################################

uninstall_bashrc_custom() {
    msg_info "$(translate "Restoring original bashrc...")"
    
    # Restore original bashrc from backup
    if [ -f /root/.bashrc.bak ]; then
        mv /root/.bashrc.bak /root/.bashrc
        msg_ok "$(translate "Original bashrc restored")"
    else
        # Remove ProxMenux customizations manually
        if [ -f /root/.bashrc ]; then
            # Remove our customization block
            sed -i '/# ProxMenux customizations/,/source \/etc\/profile\.d\/bash_completion\.sh/d' /root/.bashrc
        fi
        msg_ok "$(translate "ProxMenux customizations removed from bashrc")"
    fi
    
    # Remove bash_profile source line if we added it
    if [ -f /root/.bash_profile ]; then
        sed -i '/source \/root\/\.bashrc/d' /root/.bash_profile
    fi
    
    register_tool "bashrc_custom" false
}

################################################################

uninstall_log2ram() {
    if [[ ! -f /etc/log2ram.conf ]] && ! systemctl list-units --all | grep -q log2ram; then
        msg_warn "$(translate "log2ram is not installed.")"
        return 0
    fi

    msg_info "$(translate "Uninstalling log2ram...")"

    # Stop and disable services and timers
    systemctl stop log2ram >/dev/null 2>&1
    systemctl disable log2ram >/dev/null 2>&1
    systemctl stop log2ram-daily.timer >/dev/null 2>&1
    systemctl disable log2ram-daily.timer >/dev/null 2>&1

    # Remove cron jobs
    rm -f /etc/cron.d/log2ram
    rm -f /etc/cron.d/log2ram-auto-sync

    # Remove config and binaries
    rm -f /usr/local/bin/log2ram-check.sh
    rm -f /usr/sbin/log2ram
    rm -f /etc/log2ram.conf*
    rm -f /etc/systemd/system/log2ram.service
    rm -f /etc/systemd/system/log2ram-daily.timer
    rm -f /etc/systemd/system/log2ram-daily.service

    # Clean up log2ram mount if active
    if [ -d /var/log.hdd ]; then
        if [ -d /var/log ] && mountpoint -q /var/log; then
            rsync -a /var/log/ /var/log.hdd/ >/dev/null 2>&1
            umount /var/log >/dev/null 2>&1
        fi
        rm -rf /var/log.hdd
    fi

    systemctl daemon-reexec >/dev/null 2>&1
    systemctl daemon-reload >/dev/null 2>&1

    msg_ok "$(translate "log2ram completely removed")"
    register_tool "log2ram" false
}


################################################################

uninstall_persistent_network() {
    local LINK_DIR="/etc/systemd/network"
    
    msg_info "$(translate "Removing all .link files from") $LINK_DIR"
    sleep 2
    
    if ! ls "$LINK_DIR"/*.link >/dev/null 2>&1; then
        msg_warn "$(translate "No .link files found in") $LINK_DIR"
        return 0
    fi

    rm -f "$LINK_DIR"/*.link

    msg_ok "$(translate "Removed all .link files from") $LINK_DIR"
    msg_info "$(translate "Interface names will return to default systemd behavior.")"
    register_tool "persistent_network" false
}



################################################################

migrate_installed_tools() {
    if [[ -f "$TOOLS_JSON" ]]; then
        return
    fi
    
    clear
    show_proxmenux_logo
    msg_info "$(translate 'Detecting previous optimizations...')"
    
    echo "{}" > "$TOOLS_JSON"
    local updated=false
    

    
    # APT configurations
    if [[ -f /etc/apt/apt.conf.d/99-force-ipv4 ]]; then
        jq '. + {"apt_ipv4": true}' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
        updated=true
    fi
    
    if [[ -f /etc/apt/apt.conf.d/99-disable-translations ]]; then
        jq '. + {"apt_languages": true}' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
        updated=true
    fi
    
    # System configurations
    if [[ -f /etc/sysctl.d/99-memory.conf ]]; then
        jq '. + {"memory_settings": true}' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
        updated=true
    fi
    
    if [[ -f /etc/sysctl.d/99-network.conf ]]; then
        jq '. + {"network_optimization": true}' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
        updated=true
    fi
    
    if [[ -f /etc/sysctl.d/99-kernelpanic.conf ]]; then
        jq '. + {"kernel_panic": true}' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
        updated=true
    fi
    
    if [[ -f /etc/security/limits.d/99-limits.conf ]]; then
        jq '. + {"system_limits": true}' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
        updated=true
    fi
    
    # Services
    if systemctl is-active --quiet log2ram 2>/dev/null; then
        jq '. + {"log2ram": true}' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
        updated=true
    fi
    
    if dpkg -l | grep -q haveged; then
        jq '. + {"entropy": true}' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
        updated=true
    fi
    
    # Bashrc customization
    if grep -q "# ProxMenux customizations" /root/.bashrc 2>/dev/null; then
        jq '. + {"bashrc_custom": true}' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
        updated=true
    fi
    
    # Subscription banner
    if [[ -f /etc/apt/apt.conf.d/no-nag-script ]]; then
        jq '. + {"subscription_banner": true}' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
        updated=true
    fi
    
    if [[ "$updated" == true ]]; then
        sleep 2
        msg_ok "$(translate 'Optimizations detected and ready to revert.')"
        sleep 1
    fi
}

################################################################

show_uninstall_menu() {
    ensure_tools_json
    migrate_installed_tools
    
    mapfile -t tools_installed < <(jq -r 'to_entries | map(select(.value==true)) | .[].key' "$TOOLS_JSON")
    
    if [[ ${#tools_installed[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "ProxMenux" \
               --msgbox "\n\n$(translate "No optimizations detected to uninstall.")" 10 60
        return 0
    fi
    
    local menu_options=()
    for tool in "${tools_installed[@]}"; do
        case "$tool" in
            lvm_repair) desc="LVM PV Headers Repair";;
            repo_cleanup) desc="Repository Cleanup";;
            apt_upgrade) desc="APT Upgrade & Repository Config";;
            subscription_banner) desc="Subscription Banner Removal";;
            time_sync) desc="Time Synchronization";;
            apt_languages) desc="APT Language Skip";;
            journald) desc="Journald Optimization";;
            logrotate) desc="Logrotate Optimization";;
            system_limits) desc="System Limits Increase";;
            entropy) desc="Entropy Generation (haveged)";;
            memory_settings) desc="Memory Settings Optimization";;
            kernel_panic) desc="Kernel Panic Configuration";;
            apt_ipv4) desc="APT IPv4 Force";;
            kexec) desc="kexec for quick reboots";;
            network_optimization) desc="Network Optimizations";;
            disable_rpc) desc="RPC/rpcbind Disable";;
            bashrc_custom) desc="Bashrc Customization";;
            figurine) desc="Figurine";;
            fastfetch) desc="Fastfetch";;
            log2ram) desc="Log2ram (SSD Protection)";;
            persistent_network) desc="Setting persistent network interfaces";;
            *) desc="$tool";;
        esac
        menu_options+=("$tool" "$desc" "off")
    done
    
    selected_tools=$(dialog --backtitle "ProxMenux" \
                           --title "$(translate "Uninstall Optimizations")" \
                           --checklist "$(translate "Select optimizations to uninstall:")" 20 70 12 \
                           "${menu_options[@]}" 3>&1 1>&2 2>&3)
    
    local dialog_result=$?
    if [[ $dialog_result -ne 0 || -z "$selected_tools" ]]; then
        return 0
    fi
    
    # Show confirmation
    if ! dialog --backtitle "ProxMenux" \
                --title "$(translate "Confirm Uninstallation")" \
                --yesno "\n\n$(translate "Are you sure you want to uninstall the selected optimizations.")" 10 60; then
        return 0
    fi
    
    # Execute uninstallations
    for tool in $selected_tools; do
        tool=$(echo "$tool" | tr -d '"')
        if declare -f "uninstall_$tool" > /dev/null 2>&1; then
            clear
            show_proxmenux_logo
            "uninstall_$tool"
        else
            msg_warn "$(translate "No uninstaller found for:") $tool"
        fi
    done
    
    msg_success "$(translate "Selected optimizations have been uninstalled.")"
    msg_warn "$(translate "A system reboot is recommended to ensure all changes take effect.")"
    
    if dialog --backtitle "ProxMenux" \
              --title "$(translate "Reboot Recommended")" \
              --yesno "$(translate "Do you want to reboot now?")" 8 50; then
        reboot
    fi
}

################################################################

show_uninstall_menu
