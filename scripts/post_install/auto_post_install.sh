#!/bin/bash
# ==========================================================
# ProxMenux - Automated Post-Install Script
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.1
# ==========================================================
# Description:
# Applies a curated set of 14 safe optimizations to a fresh
# Proxmox VE host without prompts. Reversible changes are registered
# in installed_tools.json so they can be restored later from the
# Uninstall Optimizations menu; package upgrades are intentionally
# excluded because they cannot be rolled back safely.
#
# Features:
# - Zero-interaction baseline: repos, upgrade, banner, APT
#   IPv4, skip translations, kernel limits, memory tuning,
#   kernel-panic behaviour, network stack tuning, bashrc,
#   Log2RAM (SSD-aware), ZFS autotrim, journald, logrotate,
#   persistent NIC names.
# - Hardware-aware: auto-detects SSD/NVMe for Log2RAM and sizes
#   its ramdisk according to host RAM (128M/256M/512M).
# - Registration: tracks each tool in installed_tools.json.
# - Rollback: every tool has a reverse function in uninstall-tools.sh.
#
# Shares the function library with customizable_post_install.sh.
# ==========================================================


# Configuration
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
TOOLS_JSON="/usr/local/share/proxmenux/installed_tools.json"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

# Pull in ensure_repositories + PROXMENUX_UTILS — customizable already
# sources this helper; auto did not, so a function that calls
# `ensure_repositories` (setup_proxmox_repositories below) needs the
# import here too.
if [[ -f "$LOCAL_SCRIPTS/global/utils-install-functions.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/utils-install-functions.sh"
fi
# Recording is part of writing: sourced before any function runs so a
# change made without it is a mistake we can find, not one we can make.
if [[ -f "$LOCAL_SCRIPTS/global/pmx_journal.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/pmx_journal.sh"
fi
if [[ -f "$LOCAL_SCRIPTS/global/log2ram_setup.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/log2ram_setup.sh"
fi

load_language
initialize_cache

if [[ -f "$LOCAL_SCRIPTS/global/platform-functions.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/platform-functions.sh"
fi
# Proxmox Backup Server runs the same host optimizations; repositories,
# package upgrade and the subscription notice follow its own tooling.
PMX_ON_PBS=false
if declare -F pmx_is_pbs >/dev/null && pmx_is_pbs; then
    PMX_ON_PBS=true
fi

# Global variables
OS_CODENAME="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs)"
RAM_SIZE_GB=$(awk '/^MemTotal:/{print int($2/1024/1024)}' /proc/meminfo)
NECESSARY_REBOOT=0
export SCRIPT_TITLE="ProxMenux Optimization Post-Installation"

# Sprint 12A: identify which post-install flow is calling register_tool.
# auto_post_install.sh always emits source=auto; customizable sets "custom".
# The detector uses this to know which function to compare against and
# which one to re-run when applying an update (preserves user's choice
# between the auto and the custom flow of the same tool).
SCRIPT_SOURCE="auto"

# ==========================================================
# Tool registration system
ensure_tools_json() {
    [ -f "$TOOLS_JSON" ] || echo "{}" > "$TOOLS_JSON"
}

# Sprint 12A: register_tool accepts (key, state, version, source).
#   key     — tool identifier (existing)
#   state   — true/false (existing)
#   version — defaults to "1.0"; each function declares its own version as
#             `local FUNC_VERSION="X.Y"` on the first line and passes
#             "$FUNC_VERSION" here. We use a `local` variable rather than a
#             `# version:` comment because bash's `declare -f` strips
#             comments — so a comment-based version was lost when the
#             update wrapper sourced the script and re-ran the function.
#   source  — defaults to $SCRIPT_SOURCE (auto/custom) so the detector
#             knows which flow to compare against and which to re-run on
#             update.
# On install (state=true) the entry becomes a structured object
#   {installed: true, version: "X.Y", source: "auto"|"custom"}
# On uninstall (state=false) we keep the legacy boolean false so the rest
# of the pipeline (uninstall-tools.sh, frontend) keeps working.
register_tool() {
    local tool="$1"
    local state="$2"
    local version="${3:-1.0}"
    local source="${4:-${SCRIPT_SOURCE:-unknown}}"
    ensure_tools_json
    if [[ "$state" == "true" ]]; then
        jq --arg t "$tool" --arg ver "$version" --arg src "$source" \
           '.[$t]={"installed": true, "version": $ver, "source": $src}' \
           "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
    else
        jq --arg t "$tool" '.[$t]=false' \
           "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
    fi
}



check_extremeshok_warning() {
    local marker_file="/etc/extremeshok"

    if [[ -f "$marker_file" ]]; then
        dialog --backtitle "ProxMenux" --title "xshok-proxmox Post-Install Detected" \
        --yesno "\n$(translate "It appears that you have already executed the xshok-proxmox post-install script on this system.")\n\n\
$(translate "If you continue, some adjustments may be duplicated or conflict with those already made by xshok.")\n\n\
$(translate "Do you want to continue anyway?")" 13 70

        local response=$?
        if [[ $response -ne 0 ]]; then
            show_proxmenux_logo
            msg_warn "$(translate "Action cancelled due to previous xshok-proxmox modifications.")"
            echo -e
            msg_success "$(translate "Press Enter to return to menu...")"
            read -r
            exit 1
        fi
    fi
}


# ==========================================================



apt_upgrade() {
    if [[ "$PMX_ON_PBS" == true ]]; then
        bash "$LOCAL_SCRIPTS/global/update-pbs.sh"
        return
    fi
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

    if [[ -z "$pve_version" ]]; then
        msg_error "Unable to detect Proxmox version."
        return 1
    fi

    if [[ "$pve_version" -ge 9 ]]; then

        bash "$LOCAL_SCRIPTS/global/update-pve9_2.sh"
    else

        bash "$LOCAL_SCRIPTS/global/update-pve8.sh"
    fi
}

# ==========================================================








remove_subscription_banner() {
    local FUNC_VERSION="1.0"
    # description: Patch the Proxmox web UI to suppress the subscription dialog and register a successful patch.
    if [[ "$PMX_ON_PBS" == true ]]; then
        stop_spinner
        if ! whiptail --title "$(translate "Proxmox Backup Server Subscription Banner Removal")" \
        --yesno "$(translate "Do you want to remove the Proxmox subscription banner from the Proxmox Backup Server web interface?")\n\n$(translate "Attention: Removing the subscription banner may cause issues in the web interface after a future update.")\n\n$(translate "If this happens, you can restore the backup from the 'Subscription Banner Removal' option in 'Uninstall optimizations'.")\n\n$(translate "Are you sure you want to continue?")" 14 75; then
            msg_warn "$(translate "Banner removal cancelled by user.")"
            return 1
        fi
        if ! bash "$LOCAL_SCRIPTS/global/remove-banner-pve-v3.sh"; then
            msg_error "$(translate "Subscription banner removal failed")"
            return 1
        fi
        register_tool "subscription_banner" true "$FUNC_VERSION"
        return 0
    fi
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

     
    if [[ -z "$pve_version" ]]; then
        msg_error "Unable to detect Proxmox version."
        return 1
    fi

    stop_spinner

    if [[ "$pve_version" -ge 9 ]]; then
        if ! whiptail --title "Proxmox VE ${pve_version} Subscription Banner Removal" \
        --yesno "$(translate "Do you want to remove the Proxmox subscription banner from the web interface for PVE $pve_version?")\n\n$(translate "Attention: Removing the subscription banner may cause issues in the web interface after a future update.")\n\n$(translate "If this happens, you can restore the backup from the 'Subscription Banner Removal' option in 'Uninstall optimizations'.")\n\n$(translate "Are you sure you want to continue?")" 14 75; then
            msg_warn "Banner removal cancelled by user."
            return 1
        fi
        if ! bash "$LOCAL_SCRIPTS/global/remove-banner-pve-v3.sh"; then
            msg_error "$(translate "Subscription banner removal failed")"
            return 1
        fi
    else
        if ! whiptail --title "Proxmox VE 8.x Subscription Banner Removal" \
        --yesno "Do you want to remove the Proxmox subscription banner from the web interface for PVE $pve_version?" 10 70; then
            msg_warn "Banner removal cancelled by user."
            return 1
        fi
        if ! bash "$LOCAL_SCRIPTS/global/remove-banner-pve8.sh"; then
            msg_error "$(translate "Subscription banner removal failed")"
            return 1
        fi
    fi
    register_tool "subscription_banner" true "$FUNC_VERSION"
}





   

# ==========================================================





setup_proxmox_repositories() {
    local FUNC_VERSION="1.1"
# Description: Configure Proxmox + Debian APT repositories (no-subscription)
# and set the correct file permissions.

    msg_info2 "$(translate "Configuring Proxmox APT repositories...")"

    if [[ "$PMX_ON_PBS" == true ]]; then
        if ! ensure_pbs_repositories; then
            msg_error "$(translate "Failed to configure Proxmox Backup Server repositories")"
            register_tool "proxmox_repos" false "$FUNC_VERSION"
            return 1
        fi
        register_tool "proxmox_repos" true "$FUNC_VERSION"
        msg_success "$(translate "Proxmox Backup Server APT repositories configured")"
        return 0
    fi

    if ! ensure_repositories; then
        msg_error "$(translate "Failed to configure Proxmox repositories")"
        register_tool "proxmox_repos" false "$FUNC_VERSION"
        return 1
    fi

    # Defensive re-chmod: if the files already existed with the old 0640
    # permissions there is nothing for `ensure_repositories` to recreate,
    # so we still flip the bits explicitly here.
    local f
    for f in /etc/apt/sources.list.d/proxmox.sources \
             /etc/apt/sources.list.d/debian.sources \
             /etc/apt/sources.list.d/pve-no-subscription.list \
             /etc/apt/sources.list.d/pve-enterprise.list; do
        [[ -f "$f" ]] && chmod 0644 "$f" 2>/dev/null
    done

    register_tool "proxmox_repos" true "$FUNC_VERSION"
    msg_success "$(translate "Proxmox APT repositories configured")"
}


configure_time_sync() {
    local FUNC_VERSION="1.0"
    # description: Detect timezone from public IP and enable systemd time sync (NTP).
    msg_info2 "$(translate "Configuring system time settings...")"

    this_ip=$(dig +short myip.opendns.com @resolver1.opendns.com 2>/dev/null)
    if [ -z "$this_ip" ]; then
        msg_warn "$(translate "Failed to obtain public IP address - keeping current timezone settings")"
        return 0
    fi

    timezone=$(curl -s --connect-timeout 10 "https://ipapi.co/${this_ip}/timezone" 2>/dev/null | tr -d '[:space:]')
    if [ -z "$timezone" ] || [ "$timezone" = "undefined" ]; then
        msg_warn "$(translate "Failed to determine timezone from IP address - keeping current timezone settings")"
        return 0
    fi

    # Validate against the system's IANA timezone database before applying.
    # ipapi.co can return rate-limit JSON, an error string, or stale data; the
    # previous code accepted anything that wasn't literally "undefined" and
    # passed it straight to `timedatectl set-timezone`, which silently kept
    # the old TZ on a bad value.
    if ! timedatectl list-timezones 2>/dev/null | grep -Fxq "$timezone"; then
        msg_warn "$(translate "API returned an invalid timezone") ($timezone) - $(translate "keeping current settings")"
        return 0
    fi

    msg_ok "$(translate "Found timezone $timezone for IP $this_ip")"

    if timedatectl set-timezone "$timezone"; then
        msg_ok "$(translate "Timezone set to $timezone")"
        
        if timedatectl set-ntp true; then
            msg_ok "$(translate "Time settings configured - Timezone:") $timezone"
            register_tool "time_sync" true "$FUNC_VERSION"
            
            systemctl restart postfix 2>/dev/null || true
        else
            msg_warn "$(translate "Failed to enable automatic time synchronization")"
        fi
    else
        msg_warn "$(translate "Failed to set timezone - keeping current settings")"
    fi
}




# ==========================================================

skip_apt_languages() {
  local FUNC_VERSION="1.0"
  pmx_journal_context "skip_apt_languages" "$FUNC_VERSION"
  # description: Stop APT from downloading translation files to speed up updates.
  msg_info "$(translate "Configuring APT to skip downloading additional languages...")"
  pmx_write_file /etc/apt/apt.conf.d/99-disable-translations <<'EOF'
Acquire::Languages "none";
EOF
  msg_ok "$(translate "APT configured to skip additional languages")"
  register_tool "apt_languages" true "$FUNC_VERSION"
}

# ==========================================================
optimize_journald() {
    local FUNC_VERSION="1.0"
    pmx_journal_context "optimize_journald" "$FUNC_VERSION"
    # description: Cap journald size, raise rate limit and force info-level logging so the log viewer and Fail2Ban work.
    if [ -f /etc/log2ram.conf ] || [ -d /var/log.hdd ]; then
    return 0
    fi
    msg_info "$(translate "Limiting size and optimizing journald...")"
    NECESSARY_REBOOT=1

    local jf="/etc/systemd/journald.conf"
    if ! grep -q "ProxMenux optimized journald" "$jf" 2>/dev/null; then
        cp -a "$jf" "${jf}.bak" 2>/dev/null || true
    fi
    
    pmx_write_file /etc/systemd/journald.conf <<EOF
[Journal]
Storage=persistent
SplitMode=none
RateLimitIntervalSec=30s
RateLimitBurst=1000
ForwardToSyslog=no
ForwardToWall=no
Seal=no
Compress=yes
SystemMaxUse=64M
RuntimeMaxUse=60M
# MaxLevelStore=info allows ProxMenux Monitor to display system logs correctly.
# Using "warning" causes the log viewer to show nearly identical entries across
# all date ranges (1d/3d/7d) because most activity is info-level.
# It also prevents Fail2Ban from detecting SSH/Proxmox auth failures via journal.
MaxLevelStore=info
MaxLevelSyslog=info
MaxLevelKMsg=warning
MaxLevelConsole=notice
MaxLevelWall=crit
EOF
    
    systemctl restart systemd-journald.service > /dev/null 2>&1
    journalctl --vacuum-size=64M --vacuum-time=1d > /dev/null 2>&1
    journalctl --rotate > /dev/null 2>&1
    
    msg_ok "$(translate "Journald optimized - Max size: 64M")"
    register_tool "journald" true "$FUNC_VERSION"
}

# ==========================================================
optimize_logrotate() {
    local FUNC_VERSION="1.2"
    pmx_journal_context "optimize_logrotate" "$FUNC_VERSION"
    # description: Replace logrotate.conf with a Log2RAM-friendly profile (daily rotation, copytruncate).
    msg_info "$(translate "Optimizing logrotate configuration...")"
    local logrotate_conf="/etc/logrotate.conf"
    local backup_conf="${logrotate_conf}.bak"

    cp -n "$logrotate_conf" "$backup_conf" 2>/dev/null || true

    pmx_write_file "$logrotate_conf" <<EOF
# ProxMenux optimized configuration (Log2RAM-friendly)
daily
su root adm
rotate 7
size 10M
compress
missingok
notifempty
create 0640 root adm
copytruncate
include /etc/logrotate.d
EOF
    systemctl restart logrotate > /dev/null 2>&1

    msg_ok "$(translate "Logrotate optimization completed")"
    register_tool "logrotate" true "$FUNC_VERSION"
}

# ==========================================================
increase_system_limits() {
    local FUNC_VERSION="1.1"
    pmx_journal_context "increase_system_limits" "$FUNC_VERSION"
    # description: Raise inotify watches, file descriptors, process keys and PID limits to enterprise levels.
    msg_info "$(translate "Increasing various system limits...")"
    NECESSARY_REBOOT=1
    

    pmx_write_file /etc/sysctl.d/99-maxwatches.conf << EOF
# ProxMenux configuration
fs.inotify.max_user_watches = 1048576
fs.inotify.max_user_instances = 1048576
fs.inotify.max_queued_events = 1048576
EOF
    
 
    pmx_write_file /etc/security/limits.d/99-limits.conf << EOF
# ProxMenux configuration
* soft     nproc          1048576
* hard     nproc          1048576
* soft     nofile         1048576
* hard     nofile         1048576
root soft     nproc          unlimited
root hard     nproc          unlimited
root soft     nofile         unlimited
root hard     nofile         unlimited
EOF
    
 
    pmx_write_file /etc/sysctl.d/99-maxkeys.conf << EOF
# ProxMenux configuration
kernel.keys.root_maxkeys=1000000
kernel.keys.maxkeys=1000000
EOF
    
   
    for file in /etc/systemd/system.conf /etc/systemd/user.conf; do
        if ! grep -q "^DefaultLimitNOFILE=" "$file"; then
            echo "DefaultLimitNOFILE=1048576" | pmx_append_file "$file"
        fi
    done
    

    for file in /etc/pam.d/common-session /etc/pam.d/runuser-l; do
        if ! grep -q "^session required pam_limits.so" "$file"; then
            echo 'session required pam_limits.so' | pmx_append_file "$file"
        fi
    done
    

    if ! grep -q "ulimit -n 1048576" /root/.profile; then
        pmx_edit_file /root/.profile '/ulimit -n 256000/d' 2>/dev/null || true
        echo "ulimit -n 1048576" | pmx_append_file /root/.profile
    fi
    

    pmx_write_file /etc/sysctl.d/99-swap.conf << EOF
# ProxMenux configuration
vm.swappiness = 10
vm.vfs_cache_pressure = 100
EOF
    
 
    pmx_write_file /etc/sysctl.d/99-fs.conf << EOF
# ProxMenux configuration
fs.nr_open = 2097152
fs.file-max = 2097152
fs.aio-max-nr = 1048576
EOF
    
    msg_ok "$(translate "System limits increase completed.")"
    register_tool "system_limits" true "$FUNC_VERSION"
}

# ==========================================================
optimize_memory_settings() {
    local FUNC_VERSION="1.2"
    pmx_journal_context "optimize_memory_settings" "$FUNC_VERSION"
    # description: Tune swappiness, dirty page ratios and compaction proactiveness for VM hosts without overriding the kernel's memory-overcommit policy.
    msg_info "$(translate "Optimizing memory settings...")"
    NECESSARY_REBOOT=1
    
    local memory_settings
    memory_settings="$(cat <<EOF
# Balanced Memory Optimization
vm.swappiness = 10
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5
vm.max_map_count = 262144
EOF
)"

    if [ -f /proc/sys/vm/compaction_proactiveness ]; then
        memory_settings+=$'\n''vm.compaction_proactiveness = 20'
    fi
    printf '%s\n' "$memory_settings" | pmx_write_file /etc/sysctl.d/99-memory.conf
    
    msg_ok "$(translate "Memory optimization completed.")"
    register_tool "memory_settings" true "$FUNC_VERSION"
}

# ==========================================================
configure_kernel_panic() {
    local FUNC_VERSION="1.0"
    pmx_journal_context "configure_kernel_panic" "$FUNC_VERSION"
    # description: Auto-reboot on kernel panic / oops / hardlockup; write crash dumps to /var/crash.
    msg_info "$(translate "Configuring kernel panic behavior")"
    NECESSARY_REBOOT=1
    
    pmx_write_file /etc/sysctl.d/99-kernelpanic.conf <<EOF
# Enable restart on kernel panic, kernel oops and hardlockup
kernel.core_pattern = /var/crash/core.%t.%p
kernel.panic = 10
kernel.panic_on_oops = 1
kernel.hardlockup_panic = 1
EOF
    
    msg_ok "$(translate "Kernel panic behavior configuration completed")"
    register_tool "kernel_panic" true "$FUNC_VERSION"
}

# ==========================================================
force_apt_ipv4() {
    local FUNC_VERSION="1.0"
    # description: Force APT to use IPv4 to avoid stalls on hosts with broken IPv6 connectivity.
    msg_info "$(translate "Configuring APT to use IPv4...")"

    echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99-force-ipv4

    msg_ok "$(translate "APT IPv4 configuration completed")"
    register_tool "apt_ipv4" true "$FUNC_VERSION"
}

# ==========================================================

apply_network_optimizations() {
  local FUNC_VERSION="1.2"
  pmx_journal_context "apply_network_optimizations" "$FUNC_VERSION"
  # description: Tune TCP buffers, somaxconn, IPv4 hardening and disable rp_filter on fw bridges (PVE 9 compatible).
  msg_info "$(translate "Optimizing network settings...")"
  NECESSARY_REBOOT=1

  pmx_write_file /etc/sysctl.d/99-network.conf <<'EOF'
# ==========================================================
# ProxMenux - Network tuning (PVE 9 compatible)
# ==========================================================

# Core buffers & queues
net.core.netdev_max_backlog = 8192
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.somaxconn = 8192

# IPv4 hardening 
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.log_martians = 0

net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.conf.default.secure_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.default.log_martians = 0

# rp_filter: 
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2

# ICMP
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1

# TCP/IP
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_rfc1337 = 1
net.ipv4.tcp_sack = 1
net.ipv4.tcp_rmem = 8192 87380 16777216
net.ipv4.tcp_wmem = 8192 65536 16777216

# Unix sockets
net.unix.max_dgram_qlen = 4096
EOF

  sysctl --system > /dev/null 2>&1

  pmx_write_file /usr/local/sbin/proxmenux-fwbr-tune <<'EOF'
#!/usr/bin/env bash
# Set rp_filter=0 and log_martians=0 on Proxmox fw bridge interfaces.
# No arg → sweep every interface currently under /proc/sys/net/ipv4/conf/.
# One arg → tune only that interface (used by the udev rule).
set -u

tune_interface() {
    local iface="$1"
    local sysctl_path="/proc/sys/net/ipv4/conf/${iface}"
    case "$iface" in
        fwbr*|fwln*|fwpr*|tap*)
            [[ -d "$sysctl_path" ]] || return 0
            [[ -w "$sysctl_path/rp_filter"    ]] && printf '0\n' > "$sysctl_path/rp_filter"
            [[ -w "$sysctl_path/log_martians" ]] && printf '0\n' > "$sysctl_path/log_martians"
            ;;
    esac
}

if [[ $# -gt 0 ]]; then
    tune_interface "$1"
else
    for sysctl_path in /proc/sys/net/ipv4/conf/*; do
        [[ -d "$sysctl_path" ]] || continue
        tune_interface "${sysctl_path##*/}"
    done
fi
EOF
  chmod 0755 /usr/local/sbin/proxmenux-fwbr-tune
  chown root:root /usr/local/sbin/proxmenux-fwbr-tune

  pmx_write_file /etc/systemd/system/proxmenux-fwbr-tune.service <<'EOF'
[Unit]
Description=ProxMenux - Tune rp_filter/log_martians on virtual fw bridges
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/proxmenux-fwbr-tune
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

  pmx_remove_file /etc/udev/rules.d/99-proxmenux-fwbr-tune.rules

  pmx_write_file /etc/udev/rules.d/99-zz-proxmenux-fwbr-tune.rules <<'EOF'
ACTION=="add", SUBSYSTEM=="net", KERNEL=="fwbr*", RUN+="/usr/local/sbin/proxmenux-fwbr-tune %k"
ACTION=="add", SUBSYSTEM=="net", KERNEL=="fwln*", RUN+="/usr/local/sbin/proxmenux-fwbr-tune %k"
ACTION=="add", SUBSYSTEM=="net", KERNEL=="fwpr*", RUN+="/usr/local/sbin/proxmenux-fwbr-tune %k"
ACTION=="add", SUBSYSTEM=="net", KERNEL=="tap*",  RUN+="/usr/local/sbin/proxmenux-fwbr-tune %k"
EOF
  chmod 0644 /etc/udev/rules.d/99-zz-proxmenux-fwbr-tune.rules
  chown root:root /etc/udev/rules.d/99-zz-proxmenux-fwbr-tune.rules

  systemctl daemon-reload >/dev/null 2>&1 || true
  udevadm control --reload-rules >/dev/null 2>&1 || true
  pmx_enable_service proxmenux-fwbr-tune.service || true
  /usr/local/sbin/proxmenux-fwbr-tune >/dev/null 2>&1 || true


  local interfaces_file="/etc/network/interfaces"
  if ! grep -q 'source /etc/network/interfaces.d/*' "$interfaces_file"; then
      echo "source /etc/network/interfaces.d/*" | pmx_append_file "$interfaces_file"
  fi

  msg_ok "$(translate "Network optimization completed")"
  register_tool "network_optimization" true "$FUNC_VERSION"
}







# ==========================================================
_migrate_proxmenux_bashrc() {
    local bashrc="$1"
    local mode="${2:-migrate}"

    # Releases up to v1.1.3 appended an unmarked block. A later release
    # accidentally wrote the marker variable names literally because its
    # heredoc was quoted. Remove only those ProxMenux-owned shapes, together
    # with the current marked block, before writing one canonical block.
    python3 - "$bashrc" "$mode" <<'PY'
import os
import stat
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
mode = sys.argv[2] if len(sys.argv) > 2 else "migrate"
if mode not in {"inspect", "migrate"}:
    raise SystemExit(f"invalid Bashrc migration mode: {mode}")
lines = path.read_bytes().decode("utf-8", errors="surrogateescape").splitlines(keepends=True)


def content(line: str) -> str:
    return line.rstrip("\r\n")


def prompt_style(block: list[str]) -> str:
    for line in block:
        if content(line).startswith("export PS1=") and r"\w" in content(line):
            return "full"
    return "short"


legacy_tail = [
    "alias l='ls -CF'",
    "alias la='ls -A'",
    "alias ll='ls -alF'",
    "alias ls='ls --color=auto'",
    "alias grep='grep --color=auto'",
    "alias fgrep='fgrep --color=auto'",
    "alias egrep='egrep --color=auto'",
    "source /etc/profile.d/bash_completion.sh",
]
marker_pairs = (
    ("# BEGIN PMX_CORE_BASHRC", "# END PMX_CORE_BASHRC"),
    ("${marker_begin}", "${marker_end}"),
)

# Pair each family independently: a foreign END must not hide a closing marker.
# A complete span containing any other marker is ambiguous (nested, crossed,
# or unmatched inside). Preserve overlapping spans as a whole before deleting
# anything, so a rerun cannot expose user bytes as an ordinary managed block.
# Unclosed BEGINs create no span; later standalone blocks can still migrate.
marker_ends = dict(marker_pairs)
marker_tokens = {marker for pair in marker_pairs for marker in pair}
open_markers = {end: [] for end in marker_ends.values()}
ambiguous_ranges = []
marker_number = 0
for index, line in enumerate(lines):
    text = content(line)
    if text not in marker_tokens:
        continue
    marker_number += 1
    if text in marker_ends:
        open_markers[marker_ends[text]].append((index, marker_number))
    elif open_markers[text]:
        start, begin_number = open_markers[text].pop()
        if marker_number > begin_number + 1:
            ambiguous_ranges.append((start, index + 1))

preserved_spans = []
for start, end in sorted(ambiguous_ranges):
    if preserved_spans and start < preserved_spans[-1][1]:
        previous_start, previous_end = preserved_spans[-1]
        preserved_spans[-1] = (previous_start, max(previous_end, end))
    else:
        preserved_spans.append((start, end))
preserved_ranges = dict(preserved_spans)

result: list[str] = []
detected_style = "short"
changed = False
i = 0
while i < len(lines):
    if i in preserved_ranges:
        end_index = preserved_ranges[i]
        result.extend(lines[i:end_index])
        i = end_index
        continue
    current = content(lines[i])

    removed = False
    for marker_begin, marker_end in marker_pairs:
        if current != marker_begin:
            continue
        end_index = next(
            (j for j in range(i + 1, min(i + 33, len(lines)))
             if content(lines[j]) == marker_end
             or any(content(lines[j]) == pair[0] for pair in marker_pairs)),
            None,
        )
        # A new BEGIN cannot close an earlier orphan; preserve that prefix.
        if end_index is None or content(lines[end_index]) != marker_end:
            continue
        block = lines[i:end_index + 1]
        if prompt_style(block) == "full":
            detected_style = "full"
        i = end_index + 1
        changed = True
        removed = True
        break
    if removed:
        continue

    # Exact legacy signature: ProxMenux header, history format, coloured
    # prompt, seven stock aliases and bash-completion. Unrelated user blocks
    # cannot match this complete sequence.
    if current == "# ProxMenux customizations" and i + 10 < len(lines):
        candidate = lines[i:i + 11]
        candidate_text = [content(line) for line in candidate]
        ps1 = candidate_text[2]
        if (
            candidate_text[1] == 'export HISTTIMEFORMAT="%d/%m/%y %T "'
            and ps1.startswith('export PS1="')
            and r"\e[38;5;172m" in ps1
            and r"\e[38;5;153m" in ps1
            and r"\e[38;5;214m" in ps1
            and candidate_text[3:] == legacy_tail
        ):
            if prompt_style(candidate) == "full":
                detected_style = "full"
            i += len(candidate)
            changed = True
            continue

    result.append(lines[i])
    i += 1

if changed and mode == "migrate":
    original_stat = path.stat()
    fd, temporary = tempfile.mkstemp(prefix=".bashrc.proxmenux.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
            handle.write("".join(result))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(original_stat.st_mode))
        try:
            os.chown(temporary, original_stat.st_uid, original_stat.st_gid)
        except PermissionError:
            pass
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

print(detected_style)
PY
}


customize_bashrc() {
    local FUNC_VERSION="1.3"
    pmx_journal_context "customize_bashrc" "$FUNC_VERSION"
    # description: Install and safely migrate the managed ProxMenux Bash prompt and aliases while preserving or selecting the short/full working-directory style.
    msg_info "$(translate "Customizing bashrc for root user...")"
    local bashrc="/root/.bashrc"
    local bash_profile="/root/.bash_profile"
    local marker_begin="# BEGIN PMX_CORE_BASHRC"
    local marker_end="# END PMX_CORE_BASHRC"
    local prompt_path_escape='\W'
    local detected_path_style="short"

    [[ -f "$bashrc" ]] || pmx_write_file "$bashrc" < /dev/null || return 1
    if ! detected_path_style="$(_migrate_proxmenux_bashrc "$bashrc" inspect)"; then
        msg_error "$(translate "Failed to inspect the existing ProxMenux Bash configuration.")"
        return 1
    fi

    # Automated installs remain non-interactive. Preserve a previous
    # ProxMenux choice on re-run, including legacy blocks, and use the compact
    # \W style on first use.
    if [[ "$detected_path_style" == "full" ]]; then
        prompt_path_escape='\w'
    fi
    case "${PMX_BASHRC_PATH_STYLE:-}" in
        short) prompt_path_escape='\W' ;;
        "") ;;
        full) prompt_path_escape='\w' ;;
        *)
            msg_error "PMX_BASHRC_PATH_STYLE must be 'short' or 'full'."
            return 1
            ;;
    esac

    [ -f "${bashrc}.bak" ] || cp "$bashrc" "${bashrc}.bak" > /dev/null 2>&1 || return 1
    local migrated_bashrc
    # Build the entire replacement beside the original, then rename once.
    migrated_bashrc="$(mktemp "${bashrc}.proxmenux.XXXXXX")" || return 1
    if ! cp -p "$bashrc" "$migrated_bashrc" ||
       ! _migrate_proxmenux_bashrc "$migrated_bashrc" migrate >/dev/null; then
        rm -f "$migrated_bashrc"
        msg_error "$(translate "Failed to migrate the existing ProxMenux Bash configuration.")"
        return 1
    fi
    if ! cat >> "$migrated_bashrc" << EOF
${marker_begin}
# ProxMenux core customizations
export HISTTIMEFORMAT="%d/%m/%y %T "
export PS1="\[\e[31m\][\[\e[m\]\[\e[38;5;172m\]\u\[\e[m\]@\[\e[38;5;153m\]\h\[\e[m\] \[\e[38;5;214m\]${prompt_path_escape}\[\e[m\]\[\e[31m\]]\[\e[m\]\\$ "
alias l='ls -CF'
alias la='ls -A'
alias ll='ls -alF'
alias ls='ls --color=auto'
alias grep='grep --color=auto'
alias fgrep='fgrep --color=auto'
alias egrep='egrep --color=auto'
source /etc/profile.d/bash_completion.sh
${marker_end}
EOF
    then
        rm -f "$migrated_bashrc"
        msg_error "$(translate "Failed to migrate the existing ProxMenux Bash configuration.")"
        return 1
    fi

    if ! grep -q "source /root/.bashrc" "$bash_profile" 2>/dev/null; then
        if ! echo "source /root/.bashrc" | pmx_append_file "$bash_profile" 2>/dev/null; then
            rm -f "$migrated_bashrc"
            return 1
        fi
    fi

    # Keep the usual file journal, but never truncate the live Bashrc.
    local before after kept
    _pmx_store_object "$bashrc"
    before="$PMX_LAST_DIGEST"; kept="$PMX_LAST_OBJECT_STORED"
    if ! mv -f -- "$migrated_bashrc" "$bashrc"; then
        rm -f "$migrated_bashrc"
        return 1
    fi
    _pmx_store_object "$bashrc"; after="$PMX_LAST_DIGEST"
    if [[ "$before" != "$after" ]]; then
        local -a fields
        mapfile -t fields < <(_pmx_journal_common)
        _pmx_journal_record "${fields[@]}" \
            "class=configuration" "operation=write_file" "target=$bashrc" \
            "before=$before" "after=$after" "existed_raw=true" \
            "capture=present" "revert=restore" \
            "exactness=$([ "$kept" = true ] && echo exact || echo none)"
    fi

    msg_ok "$(translate "Bashrc customization completed")"
    msg_info "$(translate "The new prompt will be used in new terminal sessions.")"
    msg_info "$(translate "To apply it to the current shell now, run:") source /root/.bashrc"
    register_tool "bashrc_custom" true "$FUNC_VERSION"
}



# ==========================================================








_update_existing_log2ram_auto() {
    local func_version="$1"
    pmx_journal_context "_update_existing_log2ram_auto" "$func_version"

    msg_ok "$(translate "Log2RAM already registered — updating to latest configuration")"
    pmx_log2ram_setup "$(pmx_log2ram_current_size)" "$(pmx_log2ram_current_hours)" true || return 1
    NECESSARY_REBOOT=1
    register_tool "log2ram" true "$func_version"
    msg_success "$(translate "Log2RAM installation and configuration completed successfully.")"
}


install_log2ram_auto() {
    local FUNC_VERSION="2.0"
    local existing_log2ram_bin=""
    pmx_journal_context "install_log2ram_auto" "$FUNC_VERSION"

    # description: Fresh installs size Log2RAM from host RAM and ask for confirmation if storage is not detected as SSD. Updates preserve the configured size.

    existing_log2ram_bin="$(command -v log2ram 2>/dev/null || true)"
    if [[ -f /etc/log2ram.conf || -n "$existing_log2ram_bin" \
        || -e /etc/systemd/system/log2ram.service \
        || -d /var/hdd.log || -d /var/log.hdd ]]; then
        _update_existing_log2ram_auto "$FUNC_VERSION"
        return $?
    fi

    if [[ -f "$TOOLS_JSON" ]] && jq -e '.log2ram == true or .log2ram.installed == true' "$TOOLS_JSON" >/dev/null 2>&1; then
        msg_info2 "$(translate "Preparing Log2RAM configuration")"
    else
    # ── First-time install: detect SSD/M.2 ─────────────────────────────────
    msg_info "$(translate "Checking if system disk is SSD or M.2...")"

    local is_ssd=false
    local pool disks disk byid_path dev rot

    if grep -qE '^root=ZFS=' /etc/kernel/cmdline 2>/dev/null || mount | grep -q 'on / type zfs'; then
        pool=$(zfs list -Ho name,mountpoint 2>/dev/null | awk '$2=="/"{print $1}' | cut -d/ -f1)
        disks=$(zpool status "$pool" 2>/dev/null | awk '/ONLINE/ && $1 !~ /:|mirror|raidz|log|spare|config|NAME|rpool|state/ {print $1}' | sort -u)
        is_ssd=true
        for disk in $disks; do
            byid_path=$(readlink -f /dev/disk/by-id/*$disk* 2>/dev/null) || continue
            dev=$(basename "$byid_path" | sed -E 's|[0-9]+$||' | sed -E 's|p$||')
            rot=$(cat /sys/block/$dev/queue/rotational 2>/dev/null)
            [[ "$rot" != "0" ]] && is_ssd=false && break
        done
    else
        ROOT_PART=$(lsblk -no NAME,MOUNTPOINT | grep ' /$' | awk '{print $1}')
        SYSTEM_DISK=$(lsblk -no PKNAME /dev/$ROOT_PART 2>/dev/null | grep -E '^[a-z]+' | head -n1)
        SYSTEM_DISK=${SYSTEM_DISK:-sda}
        if [[ "$SYSTEM_DISK" == nvme* || "$(cat /sys/block/$SYSTEM_DISK/queue/rotational 2>/dev/null)" == "0" ]]; then
            is_ssd=true
        fi
    fi

    if [[ "$is_ssd" == true ]]; then
        msg_ok "$(translate "System disk is SSD or M.2. Proceeding with Log2RAM setup.")"
    else
        stop_spinner
        if whiptail --yesno "$(translate "Do you want to install Log2RAM to reduce log write load?")" 10 70 --title "Log2RAM"; then
            msg_ok "$(translate "Proceeding with Log2RAM setup on non-SSD disk as requested by user.")"
        else
            msg_info2 "$(translate "Log2RAM installation cancelled by user")"
            return 0
        fi
    fi

    fi  # end first-time install block

    pmx_log2ram_setup "$(pmx_log2ram_default_size)" "$(pmx_log2ram_default_hours)" true || return 1
    NECESSARY_REBOOT=1
    register_tool "log2ram" true "$FUNC_VERSION"
}


# ==========================================================
enable_zfs_autotrim() {
    local FUNC_VERSION="1.0"
    # description: Enable ZFS autotrim on detected pools and record only pools changed by ProxMenux.
    local state_file="$BASE_DIR/zfs_autotrim_pools"
    local tmp_file="${state_file}.tmp"
    local pools=()
    local pool current
    local changed=false

    pool_supports_autotrim() {
        local pool_name="$1"
        local vdev dev_path block_device rotational discard_granularity
        local found_device=false

        while read -r vdev; do
            [[ -z "$vdev" ]] && continue
            found_device=true

            dev_path=$(readlink -f "$vdev" 2>/dev/null || true)
            if [[ -z "$dev_path" || ! -b "$dev_path" ]]; then
                return 1
            fi

            block_device=$(lsblk -no PKNAME "$dev_path" 2>/dev/null | head -n1)
            [[ -z "$block_device" ]] && block_device=$(basename "$dev_path")

            rotational=$(cat "/sys/block/$block_device/queue/rotational" 2>/dev/null || true)
            discard_granularity=$(cat "/sys/block/$block_device/queue/discard_granularity" 2>/dev/null || true)

            if [[ "$rotational" != "0" || -z "$discard_granularity" || "$discard_granularity" == "0" ]]; then
                return 1
            fi
        done < <(
            zpool status -P "$pool_name" 2>/dev/null |
                awk '
                    $1 == "NAME" { in_config=1; next }
                    in_config && $1 == "errors:" { exit }
                    in_config && $1 ~ /^\// && $2 ~ /^(ONLINE|DEGRADED|FAULTED|OFFLINE|UNAVAIL|REMOVED)$/ { print $1 }
                '
        )

        [[ "$found_device" == true ]]
    }

    if ! command -v zpool >/dev/null 2>&1; then
        msg_info2 "$(translate "ZFS not detected. Skipping ZFS autotrim.")"
        return 0
    fi

    mapfile -t pools < <(zpool list -H -o name 2>/dev/null)
    if [[ ${#pools[@]} -eq 0 ]]; then
        msg_info2 "$(translate "No ZFS pools detected. Skipping ZFS autotrim.")"
        return 0
    fi

    msg_info "$(translate "Checking ZFS autotrim configuration...")"
    mkdir -p "$BASE_DIR"
    : > "$tmp_file"

    for pool in "${pools[@]}"; do
        current=$(zpool get -H -o value autotrim "$pool" 2>/dev/null || true)

        if [[ "$current" == "on" ]]; then
            msg_ok "$(translate "ZFS autotrim already enabled for pool:") $pool"
            continue
        fi

        if [[ "$current" != "off" ]]; then
            msg_warn "$(translate "ZFS autotrim is not supported for pool:") $pool"
            continue
        fi

        if ! pool_supports_autotrim "$pool"; then
            stop_spinner
            msg_info2 "$(translate "Pool does not appear to use SSD/NVMe devices with discard support. Skipping ZFS autotrim for pool:") $pool"
            continue
        fi

        if zpool set autotrim=on "$pool" >/dev/null 2>&1; then
            printf '%s\n' "$pool" >> "$tmp_file"
            changed=true
            msg_ok "$(translate "ZFS autotrim enabled for pool:") $pool"
        else
            msg_warn "$(translate "Failed to enable ZFS autotrim for pool:") $pool"
        fi
    done

    if [[ "$changed" == true ]]; then
        if [[ -s "$state_file" ]]; then
            sort -u "$state_file" "$tmp_file" > "${tmp_file}.merged"
            mv "${tmp_file}.merged" "$state_file"
            rm -f "$tmp_file"
        else
            mv "$tmp_file" "$state_file"
        fi
        register_tool "zfs_autotrim" true "$FUNC_VERSION"
    else
        rm -f "$tmp_file"
    fi
}








# ==========================================================


setup_persistent_network() {
    local FUNC_VERSION="1.2"
    # description: Pin NIC names to MAC addresses via systemd .link files so kernel updates don't shuffle interface names.
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

    msg_info "$(translate "Setting up persistent network interfaces")"
    sleep 2

    if [[ -f /etc/network/interfaces ]]; then
        if grep -qE '^[[:space:]]*allow-hotplug[[:space:]]' /etc/network/interfaces 2>/dev/null; then
            msg_warn "$(translate '/etc/network/interfaces uses allow-hotplug. Renaming interfaces via systemd .link can break that flow — review the file after reboot.')"
        fi
    fi

    local count=0 removed_stale=0 removed_legacy=0
    while IFS='=' read -r key value; do
        case "$key" in
            COUNT)          count="$value" ;;
            REMOVED_STALE)  removed_stale="$value" ;;
            REMOVED_LEGACY) removed_legacy="$value" ;;
        esac
    done < <(pmx_setup_persistent_network)

    if (( removed_legacy > 0 )); then
        msg_ok "$(translate "Migrated") $removed_legacy $(translate "legacy .link file(s) to the ProxMenux-managed format")"
    fi
    if (( removed_stale > 0 )); then
        msg_ok "$(translate "Reconciled") $removed_stale $(translate "stale entry/entries for interfaces no longer present")"
    fi
    if (( count > 0 )); then
        msg_ok "$(translate "Created persistent names for") $count $(translate "interfaces")"
        if [[ "$pve_version" -ge 9 ]]; then
            udevadm control --reload-rules 2>/dev/null || true
            msg_ok "$(translate "PVE9: udev rules reloaded — new interfaces will get correct names without reboot")"
        fi
        msg_ok "$(translate "Changes will apply after reboot.")"
    else
        msg_warn "$(translate "No physical interfaces found")"
    fi
    register_tool "persistent_network" true "$FUNC_VERSION"
}


# ==========================================================

run_complete_optimization() {
    
    show_proxmenux_logo
    msg_title "$(translate "$SCRIPT_TITLE")"
    
    ensure_tools_json
    
    apt_upgrade
    remove_subscription_banner
    force_apt_ipv4
    #configure_time_sync
    skip_apt_languages
    increase_system_limits
    optimize_memory_settings
    configure_kernel_panic
    apply_network_optimizations
    #disable_rpc
    customize_bashrc
    install_log2ram_auto
    enable_zfs_autotrim
    optimize_journald
    optimize_logrotate
    setup_persistent_network
    

    echo -e
    msg_success "$(translate "Complete post-installation optimization finished!")"
    
    if [[ "$NECESSARY_REBOOT" -eq 1 ]]; then
        whiptail --title "Reboot Required" \
            --yesno "$(translate "Some changes require a reboot to take effect. Do you want to restart now?")" 10 60
        if [[ $? -eq 0 ]]; then
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
        exit 0
        fi
    fi

}

check_extremeshok_warning
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    run_complete_optimization
fi
