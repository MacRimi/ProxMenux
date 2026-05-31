#!/bin/bash
# ==========================================================
# ProxMenux - Uninstall Optimizations
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Reverses post-install optimizations previously applied by
# ProxMenux. Reads the installed_tools.json registry to detect
# which tools were applied, exposes them in a checklist, and
# runs their dedicated uninstall function — restoring original
# configs from their .bak backups where applicable.
#
# Features:
# - Registry-driven: only shows tools currently applied.
# - Per-tool reverse functions (one for each entry in the
#   auto / customizable scripts).
# - Restores /etc configs from .bak backups when they exist.
# - Reboot prompt for changes that require it (VFIO, kernel
#   cmdline, persistent NIC names, …).
# ==========================================================


LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
RETURN_SCRIPT="$LOCAL_SCRIPTS/menus/menu_post_install.sh"
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
    sed -i '/# BEGIN FASTFETCH/,/# END FASTFETCH/d' "$HOME/.bashrc"
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

    sed -i '/lxcclean/d;/lxcupdate/d;/kernelclean/d;/cpugov/d;/updatecerts/d;/seqwrite/d;/seqread/d;/ranwrite/d;/ranread/d' "$HOME/.bashrc" "$HOME/.profile" 2>/dev/null
    sed -i '/# ProxMenux Figurine aliases and tools/,+20d' "$HOME/.bashrc" "$HOME/.profile" 2>/dev/null
    sed -i '/# BEGIN PROXMENUX ALIASES/,/# END PROXMENUX ALIASES/d' "$HOME/.bashrc" "$HOME/.profile" 2>/dev/null

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
    
    local JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
    local MOBILE_UI_FILE="/usr/share/pve-yew-mobile-gui/index.html.tpl"
    local PATCH_BIN="/usr/local/bin/pve-remove-nag-v3.sh"
    local BASE_DIR="/usr/local/share/proxmenux"
    local MIN_JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.min.js"
    local GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
    
    local restored=false
    

    for hook in /etc/apt/apt.conf.d/*nag*; do
        if [[ -e "$hook" ]]; then
            rm -f "$hook"
            msg_ok "$(translate "Removed APT hook: $hook")"
        fi
    done
    
    if [[ -f "$PATCH_BIN" ]]; then
        rm -f "$PATCH_BIN"
        msg_ok "$(translate "Removed patch script: $PATCH_BIN")"
    fi
    
    if [[ -d "$BASE_DIR/backups" ]]; then
        local backup_file
        backup_file=$(ls -t "$BASE_DIR/backups"/proxmoxlib.js.backup.* 2>/dev/null | head -1)
        
        if [[ -n "$backup_file" && -f "$backup_file" ]]; then
            # Verify backup integrity before restoring
            if [[ -s "$backup_file" ]] && grep -q "Ext\|function" "$backup_file" && ! grep -q $'\0' "$backup_file"; then
                cp -a "$backup_file" "$JS_FILE"
                msg_ok "$(translate "Restored desktop UI from backup: $backup_file")"
                restored=true
            else
                msg_warn "$(translate "Backup file appears corrupted, will reinstall packages")"
            fi
        else
            msg_warn "$(translate "No desktop UI backup found, will reinstall packages")"
        fi
        
        local mobile_backup
        mobile_backup=$(ls -t "$BASE_DIR/backups"/index.html.tpl.backup.* 2>/dev/null | head -1)
        
        if [[ -n "$mobile_backup" && -f "$mobile_backup" && -f "$MOBILE_UI_FILE" ]]; then
            if [[ -s "$mobile_backup" ]]; then
                cp -a "$mobile_backup" "$MOBILE_UI_FILE"
                msg_ok "$(translate "Restored mobile UI from backup: $mobile_backup")"
            fi
        fi
    fi
    
    if [[ "$restored" == false ]]; then
        msg_info "$(translate "Performing complete package reinstallation...")"
        
        # Update package lists
        apt-get update >/dev/null 2>&1
        
        # Reinstall packages with force-confnew to restore original configs
        if apt-get --reinstall -o Dpkg::Options::="--force-confnew" install \
            pve-manager proxmox-widget-toolkit libjs-extjs libpve-http-server-perl -y >/dev/null 2>&1; then
            msg_ok "$(translate "Reinstalled Proxmox packages successfully")"
            restored=true
        else
            msg_error "$(translate "Failed to reinstall packages")"
        fi
        
        # Clean package update cache
        rm -rf /var/lib/pve-manager/pkgupdates /var/cache/pve-manager 2>/dev/null || true
        
        # Second pass reinstallation to ensure everything is clean
        apt-get update >/dev/null 2>&1
        apt-get --reinstall install proxmox-widget-toolkit pve-manager libjs-extjs libpve-http-server-perl -y >/dev/null 2>&1 || true
    fi
    
    msg_info "$(translate "Cleaning cached files...")"
    rm -f "$MIN_JS_FILE" "$GZ_FILE" 2>/dev/null || true
    rm -rf /var/lib/pve-manager/pkgupdates /var/cache/pve-manager 2>/dev/null || true
    find /var/cache/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/lib/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/cache/nginx/ -type f -delete 2>/dev/null || true
    

    #systemctl restart pveproxy pvedaemon pvestatd 2>/dev/null || true
    
    register_tool "subscription_banner" false
    
    if [[ "$restored" == true ]]; then
        msg_ok "$(translate "Subscription banner restored successfully (desktop and mobile)")"
        msg_ok "$(translate "Refresh your browser to see changes (server restart may be required)")"
    else
        msg_error "$(translate "Failed to restore subscription banner completely")"
        return 1
    fi
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

    [ -f /etc/logrotate.d/pveproxy ] && rm -f /etc/logrotate.d/pveproxy

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
    
    rm -f /etc/sysctl.d/99-network.conf

    local interfaces_file="/etc/network/interfaces"
    if [ -f "$interfaces_file" ]; then
        sed -i '/^source \/etc\/network\/interfaces\.d\/\*/d' "$interfaces_file"
    fi
    
    rm -f /etc/sysctl.d/97-proxmenux-fwbr.conf \
        /etc/sysctl.d/98-proxmenux-rpf.conf

    systemctl disable --now proxmenux-fwbr-tune.service >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/proxmenux-fwbr-tune.service

    systemctl daemon-reload >/dev/null 2>&1 || true
    sysctl --system >/dev/null 2>&1 || true

    
    msg_ok "$(translate "Network optimizations removed")"
    register_tool "network_optimization" false
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
            # Remove the customization block using the markers written by customize_bashrc
            sed -i '/# BEGIN PMX_CORE_BASHRC/,/# END PMX_CORE_BASHRC/d' /root/.bashrc
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
    msg_info "$(translate "Uninstalling log2ram (all versions)...")"

    systemctl stop log2ram log2ram-daily.timer log2ram-daily.service >/dev/null 2>&1 || true
    systemctl disable log2ram log2ram-daily.timer log2ram-daily.service >/dev/null 2>&1 || true

    rm -f /etc/cron.d/log2ram \
          /etc/cron.d/log2ram-auto-sync \
          /etc/cron.d/log2ram-sync \
          /etc/cron.hourly/log2ram \
          /etc/cron.daily/log2ram \
          /etc/cron.weekly/log2ram \
          /etc/cron.monthly/log2ram 2>/dev/null || true

    rm -f /usr/local/bin/log2ram-check.sh \
          /usr/local/bin/log2ram \
          /usr/local/bin/log2ram-sync \
          /usr/sbin/log2ram \
          /usr/bin/log2ram 2>/dev/null || true

    rm -f /etc/systemd/system/log2ram.service \
          /etc/systemd/system/log2ram-daily.timer \
          /etc/systemd/system/log2ram-daily.service \
          /etc/systemd/system/sysinit.target.wants/log2ram.service \
          /etc/systemd/system/timers.target.wants/log2ram-daily.timer \
          /lib/systemd/system/log2ram.service \
          /lib/systemd/system/log2ram-daily.timer \
          /lib/systemd/system/log2ram-daily.service 2>/dev/null || true
    rm -rf /etc/systemd/system/log2ram.service.d 2>/dev/null || true

    rm -f /etc/log2ram.conf \
          /etc/log2ram.conf.dpkg-old \
          /etc/log2ram.conf.bak \
          /etc/log2ram.conf.save 2>/dev/null || true

    rm -rf /etc/logrotate.d/log2ram 2>/dev/null || true

    if mountpoint -q /var/log 2>/dev/null; then
        if [[ -d /var/log.hdd ]]; then
            msg_info "$(translate "Preserving logs to /var/log.hdd before unmounting...")"
            rsync -a /var/log/ /var/log.hdd/ >/dev/null 2>&1 || true
        fi
        umount /var/log >/dev/null 2>&1 || true
    fi

    [[ -d /var/log.hdd ]] && rm -rf /var/log.hdd
    [[ -d /tmp/log2ram ]] && rm -rf /tmp/log2ram
    [[ -d /var/hdd.log ]] && rm -rf /var/hdd.log
    [[ -f /tmp/log2ram_install.log ]] && rm -f /tmp/log2ram_install.log

    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl reset-failed >/dev/null 2>&1 || true
    systemctl restart cron >/dev/null 2>&1 || true

    if dpkg -l 2>/dev/null | grep -q '^ii  log2ram'; then
        msg_info "$(translate "Purging log2ram apt package...")"
        apt-get purge -y log2ram >/dev/null 2>&1 || true
        apt-get autoremove -y >/dev/null 2>&1 || true
    fi

    if [[ -f /etc/log2ram.conf ]] || \
       command -v log2ram >/dev/null 2>&1 || \
       systemctl list-units --all 2>/dev/null | grep -q log2ram || \
       [[ -f /etc/cron.d/log2ram-auto-sync ]]; then
        msg_warn "$(translate "Some log2ram files may still exist. Manual cleanup may be required.")"
    else
        msg_ok "$(translate "log2ram completely removed from system")"
    fi

    register_tool "log2ram" false
    NECESSARY_REBOOT=1
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
    NECESSARY_REBOOT=1
}





uninstall_vfio_iommu() {
    msg_info2 "$(translate "Reverting IOMMU/VFIO configuration...")"
    NECESSARY_REBOOT=1

    # Remove VFIO modules from /etc/modules
    local modules_file="/etc/modules"
    if [ -f "$modules_file" ]; then
        sed -i '/^vfio$/d;/^vfio_iommu_type1$/d;/^vfio_pci$/d;/^vfio_virqfd$/d' "$modules_file"
        msg_ok "$(translate "VFIO modules removed from /etc/modules")"
    fi

    # Remove driver blacklists added by ProxMenux
    local blacklist_file="/etc/modprobe.d/blacklist.conf"
    if [ -f "$blacklist_file" ]; then
        sed -i '/^blacklist nouveau$/d;/^blacklist lbm-nouveau$/d;/^blacklist radeon$/d;/^blacklist nvidia$/d;/^blacklist nvidiafb$/d;/^options nouveau modeset=0$/d' "$blacklist_file"
        [ ! -s "$blacklist_file" ] && rm -f "$blacklist_file"
        msg_ok "$(translate "Driver blacklist entries removed")"
    fi

    # Remove IOMMU kernel parameters
    local cmdline_file="/etc/kernel/cmdline"
    if [[ -f "$cmdline_file" ]] && grep -qE 'root=ZFS=|root=ZFS/' "$cmdline_file"; then
        # systemd-boot / ZFS
        if grep -qE 'intel_iommu=on|amd_iommu=on|iommu=pt|pcie_acs_override=' "$cmdline_file"; then
            cp "$cmdline_file" "${cmdline_file}.bak.$(date +%Y%m%d_%H%M%S)"
            sed -i -E 's/\b(intel_iommu=on|amd_iommu=on|iommu=pt|pcie_acs_override=[^ ]*)\b//g' "$cmdline_file"
            sed -i -E 's/[[:space:]]+/ /g; s/^ //; s/ $//' "$cmdline_file"
            command -v proxmox-boot-tool >/dev/null 2>&1 && proxmox-boot-tool refresh >/dev/null 2>&1 || true
            msg_ok "$(translate "IOMMU parameters removed from /etc/kernel/cmdline")"
        fi
    else
        # GRUB
        local grub_file="/etc/default/grub"
        if [[ -f "$grub_file" ]] && grep -qE 'intel_iommu=on|amd_iommu=on|iommu=pt|pcie_acs_override=' "$grub_file"; then
            cp "$grub_file" "${grub_file}.bak.$(date +%Y%m%d_%H%M%S)"
            sed -i -E 's/\b(intel_iommu=on|amd_iommu=on|iommu=pt|pcie_acs_override=[^ "]*)\b//g' "$grub_file"
            awk -F\" 'BEGIN{OFS="\""} /GRUB_CMDLINE_LINUX_DEFAULT=/{gsub(/[[:space:]]+/," ",$2);sub(/^ /,"",$2);sub(/ $/,"",$2)}1' \
                "$grub_file" > "${grub_file}.tmp" && mv "${grub_file}.tmp" "$grub_file"
            update-grub >/dev/null 2>&1 || true
            msg_ok "$(translate "IOMMU parameters removed from GRUB")"
        fi
    fi
    
    msg_info "$(translate 'Updating initramfs (this may take a minute)...')"

    update-initramfs -u -k all >/dev/null 2>&1 || true

    msg_ok "$(translate "IOMMU/VFIO configuration reverted")"
    register_tool "vfio_iommu" false
}

################################################################

uninstall_amd_fixes() {
    msg_info2 "$(translate "Reverting AMD (Ryzen/EPYC) fixes...")"
    NECESSARY_REBOOT=1


    if grep -q "root=ZFS=" /proc/cmdline 2>/dev/null; then

        cmdline_file="/etc/kernel/cmdline"
        if [[ -f "$cmdline_file" ]] && grep -q "idle=nomwait" "$cmdline_file"; then
            cp "$cmdline_file" "${cmdline_file}.bak.$(date +%Y%m%d_%H%M%S)" || {
                msg_error "$(translate "Failed to backup $cmdline_file")"
                return 1
            }

            sed -i 's/\bidle=nomwait\b//g; s/[[:space:]]\+/ /g; s/^ //; s/ $//' "$cmdline_file"

            if command -v proxmox-boot-tool >/dev/null 2>&1; then
                proxmox-boot-tool refresh >/dev/null 2>&1 || {
                    msg_error "$(translate "Failed to refresh boot configuration")"
                    return 1
                }
            fi
            msg_ok "$(translate "Removed idle=nomwait from /etc/kernel/cmdline (ZFS)")"
        fi
    else

        grub_file="/etc/default/grub"
        if [[ -f "$grub_file" ]] && grep -q 'GRUB_CMDLINE_LINUX_DEFAULT=' "$grub_file"; then
            if grep -q "idle=nomwait" "$grub_file"; then
                cp "$grub_file" "${grub_file}.bak.$(date +%Y%m%d_%H%M%S)" || {
                    msg_error "$(translate "Failed to backup $grub_file")"
                    return 1
                }

                sed -i -E 's/(GRUB_CMDLINE_LINUX_DEFAULT=")/\1/; s/\bidle=nomwait\b//g' "$grub_file"

                awk -F\" '
                  $1=="GRUB_CMDLINE_LINUX_DEFAULT=" {
                    gsub(/[[:space:]]+/," ",$2); sub(/^ /,"",$2); sub(/ $/,"",$2)
                  }1
                ' OFS="\"" "$grub_file" > "${grub_file}.tmp" && mv "${grub_file}.tmp" "$grub_file"

                update-grub >/dev/null 2>&1 || {
                    msg_error "$(translate "Failed to update GRUB configuration")"
                    return 1
                }
                msg_ok "$(translate "Removed idle=nomwait from GRUB configuration")"
            fi
        fi
    fi


    kvm_conf="/etc/modprobe.d/kvm.conf"
    if [[ -f "$kvm_conf" ]]; then
        if grep -Eq '(ignore_msrs|report_ignored_msrs)' "$kvm_conf"; then
            cp "$kvm_conf" "${kvm_conf}.bak.$(date +%Y%m%d_%H%M%S)" || {
                msg_error "$(translate "Failed to backup $kvm_conf")"
                return 1
            }
            sed -i -E '/ignore_msrs|report_ignored_msrs/d' "$kvm_conf"

            if [[ ! -s "$kvm_conf" ]]; then
                rm -f "$kvm_conf"
                msg_ok "$(translate "Removed empty KVM configuration file")"
            else
                msg_ok "$(translate "Removed KVM MSR options from configuration")"
            fi

            update-initramfs -u -k all >/dev/null 2>&1 || true
        else
            msg_ok "$(translate "KVM MSR options not present, nothing to revert")"
        fi
    fi

    msg_success "$(translate "AMD fixes have been successfully reverted")"
    register_tool "amd_fixes" false
}








################################################################

migrate_installed_tools() {
    if [[ -f "$TOOLS_JSON" ]]; then
        return
    fi
    
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
# Sprint 10P — Uninstallers for items previously missing coverage.
# Each `uninstall_*` mirrors its install function in
# `customizable_post_install.sh` and flips `register_tool "X" false`
# at the end so the entry is removed from the active set.
################################################################

uninstall_ceph() {
    msg_info2 "$(translate 'Uninstalling Ceph...')"
    if dpkg -l 2>/dev/null | grep -qE '^ii\s+ceph'; then
        apt-get purge -y 'ceph-*' 'librados*' 'librbd*' 'libcephfs*' 'python3-ceph*' >/dev/null 2>&1 || true
        apt-get autoremove -y >/dev/null 2>&1 || true
    fi
    rm -f /etc/apt/sources.list.d/ceph.list /etc/apt/sources.list.d/ceph.sources 2>/dev/null
    rm -f /etc/apt/trusted.gpg.d/ceph.asc /etc/apt/trusted.gpg.d/ceph-release.gpg 2>/dev/null
    apt-get update -qq >/dev/null 2>&1 || true
    msg_ok "$(translate 'Ceph packages and repository removed')"
    register_tool "ceph" false
}

uninstall_ha() {
    msg_info2 "$(translate 'Disabling High Availability services...')"
    systemctl disable --now pve-ha-lrm pve-ha-crm corosync >/dev/null 2>&1 || true
    msg_ok "$(translate 'HA services disabled (configs preserved)')"
    register_tool "ha" false
}

uninstall_openvswitch() {
    msg_info2 "$(translate 'Removing OpenVSwitch...')"
    apt-get purge -y openvswitch-switch openvswitch-common >/dev/null 2>&1 || true
    apt-get autoremove -y >/dev/null 2>&1 || true
    msg_ok "$(translate 'OpenVSwitch removed')"
    register_tool "openvswitch" false
}

uninstall_tcp_optimizations() {
    msg_info2 "$(translate 'Reverting TCP BBR + Fast Open...')"
    rm -f /etc/sysctl.d/99-kernel-bbr.conf /etc/sysctl.d/99-tcp-fastopen.conf
    sysctl --system >/dev/null 2>&1 || true
    msg_ok "$(translate 'TCP optimizations reverted (defaults restored on next reboot)')"
    register_tool "tcp_optimizations" false
}

uninstall_guest_agent() {
    msg_info2 "$(translate 'Removing guest agent...')"
    local pkg=""
    if [[ -f /usr/local/share/proxmenux/guest_agent.pkg ]]; then
        pkg=$(cat /usr/local/share/proxmenux/guest_agent.pkg 2>/dev/null)
    fi
    if [[ -n "$pkg" ]]; then
        apt-get purge -y "$pkg" >/dev/null 2>&1 || true
        rm -f /usr/local/share/proxmenux/guest_agent.pkg
        msg_ok "$(translate 'Removed:') $pkg"
    else
        # Fallback: try the typical packages
        for p in qemu-guest-agent open-vm-tools virtualbox-guest-utils; do
            dpkg -s "$p" >/dev/null 2>&1 && apt-get purge -y "$p" >/dev/null 2>&1
        done
        msg_ok "$(translate 'Guest agent packages removed')"
    fi
    register_tool "guest_agent" false
}

uninstall_ovh_rtm() {
    msg_info2 "$(translate 'Removing OVH RTM...')"
    # OVH RTM installs `rtm` packages and a puppet config.
    apt-get purge -y 'ovh-rtm*' 'rtm' 'rtm-*' >/dev/null 2>&1 || true
    rm -rf /etc/rtm 2>/dev/null
    msg_ok "$(translate 'OVH RTM removed (Puppet artefacts may need manual cleanup)')"
    register_tool "ovh_rtm" false
}

uninstall_pigz() {
    msg_info2 "$(translate 'Reverting pigz wrapper...')"
    if [[ -f /bin/gzip.original ]]; then
        mv -f /bin/gzip.original /bin/gzip
        msg_ok "$(translate 'Restored original /bin/gzip')"
    fi
    rm -f /bin/pigzwrapper
    sed -i 's/^pigz: 1/#pigz: 1/' /etc/vzdump.conf 2>/dev/null || true
    apt-get purge -y pigz >/dev/null 2>&1 || true
    msg_ok "$(translate 'pigz removed')"
    register_tool "pigz" false
}

uninstall_zfs_arc() {
    msg_info2 "$(translate 'Reverting ZFS ARC tuning...')"
    if [[ -f /etc/modprobe.d/99-zfsarc.conf.bak ]]; then
        mv -f /etc/modprobe.d/99-zfsarc.conf.bak /etc/modprobe.d/99-zfsarc.conf
        msg_ok "$(translate 'Original ZFS ARC config restored from .bak')"
    else
        rm -f /etc/modprobe.d/99-zfsarc.conf
        msg_ok "$(translate 'ZFS ARC config removed (kernel defaults will apply on reboot)')"
    fi
    register_tool "zfs_arc" false
}

uninstall_zfs_auto_snapshot() {
    msg_info2 "$(translate 'Removing zfs-auto-snapshot...')"
    apt-get purge -y zfs-auto-snapshot >/dev/null 2>&1 || true
    msg_ok "$(translate 'zfs-auto-snapshot removed (existing snapshots preserved on the pool)')"
    register_tool "zfs_auto_snapshot" false
}

uninstall_zfs_autotrim() {
    local state_file="$BASE_DIR/zfs_autotrim_pools"
    local pools=()
    local pool

    msg_info2 "$(translate 'Disabling ZFS autotrim applied by ProxMenux...')"

    if ! command -v zpool >/dev/null 2>&1; then
        msg_warn "$(translate 'ZFS not detected. Nothing to disable.')"
        rm -f "$state_file"
        register_tool "zfs_autotrim" false
        return 0
    fi

    if [[ ! -s "$state_file" ]]; then
        msg_warn "$(translate 'No ProxMenux ZFS autotrim state file found.')"
        register_tool "zfs_autotrim" false
        return 0
    fi

    mapfile -t pools < <(sort -u "$state_file")
    for pool in "${pools[@]}"; do
        if zpool list -H "$pool" >/dev/null 2>&1; then
            if zpool set autotrim=off "$pool" >/dev/null 2>&1; then
                msg_ok "$(translate 'ZFS autotrim disabled for pool:') $pool"
            else
                msg_warn "$(translate 'Failed to disable ZFS autotrim for pool:') $pool"
            fi
        else
            msg_warn "$(translate 'ZFS pool not found:') $pool"
        fi
    done

    rm -f "$state_file"
    register_tool "zfs_autotrim" false
}

uninstall_vzdump_speed() {
    msg_info2 "$(translate 'Reverting vzdump speed tuning...')"
    if [[ -f /etc/vzdump.conf.bak ]]; then
        mv -f /etc/vzdump.conf.bak /etc/vzdump.conf
        msg_ok "$(translate 'Restored original /etc/vzdump.conf from .bak')"
    else
        sed -i '/^bwlimit: 0$/d;/^ionice: 5$/d' /etc/vzdump.conf 2>/dev/null
        msg_ok "$(translate 'Removed bwlimit/ionice tuning (no .bak found)')"
    fi
    register_tool "vzdump_speed" false
}

################################################################

show_uninstall_menu() {
    ensure_tools_json
    migrate_installed_tools
    
    mapfile -t tools_installed < <(jq -r 'to_entries | map(select(.value==true or .value.installed==true)) | .[].key' "$TOOLS_JSON")
    
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
            #apt_upgrade) desc="APT Upgrade & Repository Config";;
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
            bashrc_custom) desc="Bashrc Customization";;
            figurine) desc="Figurine";;
            fastfetch) desc="Fastfetch";;
            log2ram) desc="Log2ram (SSD Protection)";;
            amd_fixes) desc="AMD CPU (Ryzen/EPYC) fixes";;
            vfio_iommu) desc="IOMMU/VFIO PCI Passthrough";;
            persistent_network) desc="Setting persistent network interfaces";;
            ceph) desc="Ceph (squid) packages + repo";;
            ha) desc="High Availability services (corosync/HA)";;
            openvswitch) desc="OpenVSwitch";;
            tcp_optimizations) desc="TCP BBR + Fast Open";;
            guest_agent) desc="Guest agent (qemu/vmware/virtualbox)";;
            ovh_rtm) desc="OVH Real-Time Monitoring";;
            pigz) desc="pigz (parallel gzip wrapper)";;
            zfs_arc) desc="ZFS ARC size tuning";;
            zfs_auto_snapshot) desc="zfs-auto-snapshot package";;
            zfs_autotrim) desc="ZFS autotrim";;
            vzdump_speed) desc="vzdump bwlimit/ionice tuning";;
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
    echo -e
    msg_success "$(translate "Press Enter to continue...")"
    read -r
    
    if dialog --backtitle "ProxMenux" \
              --title "$(translate "Reboot Recommended")" \
              --yesno "$(translate "Do you want to reboot now?")" 8 50; then
        reboot
    fi
}

################################################################

show_uninstall_menu
