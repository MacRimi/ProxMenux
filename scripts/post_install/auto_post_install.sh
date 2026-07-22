#!/bin/bash
# ==========================================================
# ProxMenux - Automated Post-Install Script
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Applies a curated set of 14 safe optimizations to a fresh
# Proxmox VE host without prompts. Every change is registered
# in installed_tools.json so it can be reversed later from the
# Uninstall Optimizations menu.
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

load_language
initialize_cache

# Global variables
OS_CODENAME="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs)"
RAM_SIZE_GB=$(( $(vmstat -s | grep -i "total memory" | xargs | cut -d" " -f 1) / 1024 / 1000))
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
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

     
    if [[ -z "$pve_version" ]]; then
        msg_error "Unable to detect Proxmox version."
        return 1
    fi

    kill -TERM "$SPINNER_PID" 2>/dev/null
    sleep 1

    if [[ "$pve_version" -ge 9 ]]; then
        if ! whiptail --title "Proxmox VE ${pve_version} Subscription Banner Removal" \
        --yesno "$(translate "Do you want to remove the Proxmox subscription banner from the web interface for PVE $pve_version?")\n\n$(translate "Attention: Removing the subscription banner may cause issues in the web interface after a future update.")\n\n$(translate "If this happens, you can restore the backup from the 'Subscription Banner Removal' option in 'Uninstall optimizations'.")\n\n$(translate "Are you sure you want to continue?")" 14 75; then
            msg_warn "Banner removal cancelled by user."
            return 1
        fi
        bash "$LOCAL_SCRIPTS/global/remove-banner-pve-v3.sh"
    else
        if ! whiptail --title "Proxmox VE 8.x Subscription Banner Removal" \
        --yesno "Do you want to remove the Proxmox subscription banner from the web interface for PVE $pve_version?" 10 70; then
            msg_warn "Banner removal cancelled by user."
            return 1
        fi
        bash "$LOCAL_SCRIPTS/global/remove-banner-pve8.sh"
    fi
}





   

# ==========================================================





setup_proxmox_repositories() {
    local FUNC_VERSION="1.1"
# Description: Configure Proxmox + Debian APT repositories (no-subscription)
# and set the correct file permissions.

    msg_info2 "$(translate "Configuring Proxmox APT repositories...")"

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
  # description: Stop APT from downloading translation files to speed up updates.
  msg_info "$(translate "Configuring APT to skip downloading additional languages...")"
  cat > /etc/apt/apt.conf.d/99-disable-translations <<'EOF'
Acquire::Languages "none";
EOF
  msg_ok "$(translate "APT configured to skip additional languages")"
  register_tool "apt_languages" true "$FUNC_VERSION"
}

# ==========================================================
optimize_journald() {
    local FUNC_VERSION="1.0"
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
    
    cat <<EOF > /etc/systemd/journald.conf
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
    local FUNC_VERSION="1.1"
    # description: Replace logrotate.conf with a Log2RAM-friendly profile (daily rotation, copytruncate).
    msg_info "$(translate "Optimizing logrotate configuration...")"
    local logrotate_conf="/etc/logrotate.conf"
    local backup_conf="${logrotate_conf}.bak"

    cp -n "$logrotate_conf" "$backup_conf" 2>/dev/null || true

    cat <<EOF > "$logrotate_conf"
# ProxMenux optimized configuration (Log2RAM-friendly)
daily
su root adm
rotate 7
size 10M
compress
delaycompress
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
    # description: Raise inotify watches, file descriptors, process keys and PID limits to enterprise levels.
    msg_info "$(translate "Increasing various system limits...")"
    NECESSARY_REBOOT=1
    

    cat > /etc/sysctl.d/99-maxwatches.conf << EOF
# ProxMenux configuration
fs.inotify.max_user_watches = 1048576
fs.inotify.max_user_instances = 1048576
fs.inotify.max_queued_events = 1048576
EOF
    
 
    cat > /etc/security/limits.d/99-limits.conf << EOF
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
    
 
    cat > /etc/sysctl.d/99-maxkeys.conf << EOF
# ProxMenux configuration
kernel.keys.root_maxkeys=1000000
kernel.keys.maxkeys=1000000
EOF
    
   
    for file in /etc/systemd/system.conf /etc/systemd/user.conf; do
        if ! grep -q "^DefaultLimitNOFILE=" "$file"; then
            echo "DefaultLimitNOFILE=1048576" >> "$file"
        fi
    done
    

    for file in /etc/pam.d/common-session /etc/pam.d/runuser-l; do
        if ! grep -q "^session required pam_limits.so" "$file"; then
            echo 'session required pam_limits.so' >> "$file"
        fi
    done
    

    if ! grep -q "ulimit -n 1048576" /root/.profile; then
        sed -i '/ulimit -n 256000/d' /root/.profile 2>/dev/null
        echo "ulimit -n 1048576" >> /root/.profile
    fi
    

    cat > /etc/sysctl.d/99-swap.conf << EOF
# ProxMenux configuration
vm.swappiness = 10
vm.vfs_cache_pressure = 100
EOF
    
 
    cat > /etc/sysctl.d/99-fs.conf << EOF
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
    local FUNC_VERSION="1.1"
    # description: Tune swappiness, dirty page ratios, overcommit and compaction proactiveness for VM hosts.
    msg_info "$(translate "Optimizing memory settings...")"
    NECESSARY_REBOOT=1
    
    cat <<EOF > /etc/sysctl.d/99-memory.conf
# Balanced Memory Optimization
vm.swappiness = 10
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5
vm.overcommit_memory = 1
vm.max_map_count = 262144
EOF
    
    if [ -f /proc/sys/vm/compaction_proactiveness ]; then
        echo "vm.compaction_proactiveness = 20" >> /etc/sysctl.d/99-memory.conf
    fi
    
    msg_ok "$(translate "Memory optimization completed.")"
    register_tool "memory_settings" true "$FUNC_VERSION"
}

# ==========================================================
configure_kernel_panic() {
    local FUNC_VERSION="1.0"
    # description: Auto-reboot on kernel panic / oops / hardlockup; write crash dumps to /var/crash.
    msg_info "$(translate "Configuring kernel panic behavior")"
    NECESSARY_REBOOT=1
    
    cat <<EOF > /etc/sysctl.d/99-kernelpanic.conf
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
  local FUNC_VERSION="1.1"
  # description: Tune TCP buffers, somaxconn, IPv4 hardening and disable rp_filter on fw bridges (PVE 9 compatible).
  msg_info "$(translate "Optimizing network settings...")"
  NECESSARY_REBOOT=1

  cat <<'EOF' > /etc/sysctl.d/99-network.conf
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

  cat > /usr/local/sbin/proxmenux-fwbr-tune <<'EOF'
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

  cat > /etc/systemd/system/proxmenux-fwbr-tune.service <<'EOF'
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

  cat > /etc/udev/rules.d/99-proxmenux-fwbr-tune.rules <<'EOF'
ACTION=="add", SUBSYSTEM=="net", KERNEL=="fwbr*", RUN+="/usr/local/sbin/proxmenux-fwbr-tune %k"
ACTION=="add", SUBSYSTEM=="net", KERNEL=="fwln*", RUN+="/usr/local/sbin/proxmenux-fwbr-tune %k"
ACTION=="add", SUBSYSTEM=="net", KERNEL=="fwpr*", RUN+="/usr/local/sbin/proxmenux-fwbr-tune %k"
ACTION=="add", SUBSYSTEM=="net", KERNEL=="tap*",  RUN+="/usr/local/sbin/proxmenux-fwbr-tune %k"
EOF
  chmod 0644 /etc/udev/rules.d/99-proxmenux-fwbr-tune.rules
  chown root:root /etc/udev/rules.d/99-proxmenux-fwbr-tune.rules

  systemctl daemon-reload >/dev/null 2>&1 || true
  udevadm control --reload-rules >/dev/null 2>&1 || true
  systemctl enable --now proxmenux-fwbr-tune.service >/dev/null 2>&1 || true
  /usr/local/sbin/proxmenux-fwbr-tune >/dev/null 2>&1 || true


  local interfaces_file="/etc/network/interfaces"
  if ! grep -q 'source /etc/network/interfaces.d/*' "$interfaces_file"; then
      echo "source /etc/network/interfaces.d/*" >> "$interfaces_file"
  fi

  msg_ok "$(translate "Network optimization completed")"
  register_tool "network_optimization" true "$FUNC_VERSION"
}







# ==========================================================
customize_bashrc() {
    local FUNC_VERSION="1.0"
    # description: Inject the ProxMenux core bashrc block (aliases, prompt, history) into root's .bashrc, idempotent via begin/end markers.
    msg_info "$(translate "Customizing bashrc for root user...")"
    local bashrc="/root/.bashrc"
    local bash_profile="/root/.bash_profile"
    local marker_begin="# BEGIN PMX_CORE_BASHRC"
    local marker_end="# END PMX_CORE_BASHRC"
    
 
    [ -f "${bashrc}.bak" ] || cp "$bashrc" "${bashrc}.bak" > /dev/null 2>&1
    

    if grep -q "^${marker_begin}$" "$bashrc" 2>/dev/null; then
        sed -i "/^${marker_begin}$/,/^${marker_end}$/d" "$bashrc"  
    fi
    
 
    cat >> "$bashrc" << EOF
${marker_begin}
# ProxMenux core customizations
export HISTTIMEFORMAT="%d/%m/%y %T "
export PS1="\[\e[31m\][\[\e[m\]\[\e[38;5;172m\]\u\[\e[m\]@\[\e[38;5;153m\]\h\[\e[m\] \[\e[38;5;214m\]\W\[\e[m\]\[\e[31m\]]\[\e[m\]\\$ "
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
    

    if ! grep -q "source /root/.bashrc" "$bash_profile" 2>/dev/null; then
        echo "source /root/.bashrc" >> "$bash_profile" 2>/dev/null
    fi
    
    msg_ok "$(translate "Bashrc customization completed")"
    register_tool "bashrc_custom" true "$FUNC_VERSION"
}



# ==========================================================








install_log2ram_auto() {
    local FUNC_VERSION="1.3"

    # description: Install Log2RAM with size auto-tuned to host RAM (128M/256M/512M); SSD/M.2 detection skips on rotational disks.

    if [[ -f "$TOOLS_JSON" ]] && jq -e '.log2ram == true or .log2ram.installed == true' "$TOOLS_JSON" >/dev/null 2>&1; then
        msg_ok "$(translate "Log2RAM already registered — updating to latest configuration")"
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
        kill -TERM "$SPINNER_PID" 2>/dev/null
        sleep 1
        if whiptail --yesno "$(translate "Do you want to install Log2RAM anyway to reduce log write load?")" 10 70 --title "Log2RAM"; then
            msg_ok "$(translate "Proceeding with Log2RAM setup on non-SSD disk as requested by user.")"
        else
            msg_info2 "$(translate "Log2RAM installation cancelled by user")"
            return 0
        fi
    fi

    fi  # end first-time install block

    msg_info "$(translate "Cleaning previous Log2RAM installation...")"

    systemctl stop log2ram log2ram-daily.timer >/dev/null 2>&1 || true
    systemctl disable log2ram log2ram-daily.timer >/dev/null 2>&1 || true

    rm -f /etc/cron.d/log2ram /etc/cron.d/log2ram-auto-sync \
          /etc/cron.hourly/log2ram /etc/cron.daily/log2ram \
          /etc/cron.weekly/log2ram /etc/cron.monthly/log2ram 2>/dev/null || true
    rm -f /usr/local/bin/log2ram-check.sh /usr/local/bin/log2ram /usr/sbin/log2ram 2>/dev/null || true
    rm -f /etc/systemd/system/log2ram.service \
          /etc/systemd/system/log2ram-daily.timer \
          /etc/systemd/system/log2ram-daily.service \
          /etc/systemd/system/sysinit.target.wants/log2ram.service 2>/dev/null || true
    rm -rf /etc/systemd/system/log2ram.service.d 2>/dev/null || true
    rm -f /etc/log2ram.conf* 2>/dev/null || true
    rm -rf /etc/logrotate.d/log2ram /var/log.hdd /tmp/log2ram 2>/dev/null || true

    systemctl daemon-reexec >/dev/null 2>&1 || true
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl restart cron >/dev/null 2>&1 || true

    msg_ok "$(translate "Previous installation cleaned")"
    msg_info "$(translate "Installing Log2RAM from source...")"

    if ! command -v git >/dev/null 2>&1; then
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y git >/dev/null 2>&1
    fi

    rm -rf /tmp/log2ram 2>/dev/null || true
    if ! git clone https://github.com/azlux/log2ram.git /tmp/log2ram >/dev/null 2>>/tmp/log2ram_install.log; then
        msg_error "$(translate "Failed to clone log2ram repository. Check /tmp/log2ram_install.log")"
        return 1
    fi

    cd /tmp/log2ram || { msg_error "$(translate "Failed to access log2ram directory")"; return 1; }

    if ! bash install.sh >>/tmp/log2ram_install.log 2>&1; then
        msg_error "$(translate "Failed to run log2ram installer. Check /tmp/log2ram_install.log")"
        return 1
    fi

    # Drop ACL preservation from the upstream rsync call: some
    # /var/log.hdd filesystems reject POSIX ACLs and log2ram write
    # exits 23 with `set_acl: Operation not supported`. xattrs stay.
    local _l2r_bin
    for _l2r_bin in \
        "$(command -v log2ram 2>/dev/null)" \
        /usr/local/bin/log2ram \
        /usr/sbin/log2ram \
        /usr/bin/log2ram
    do
        [[ -n "$_l2r_bin" && -f "$_l2r_bin" ]] || continue
        if grep -q 'rsync -aAXv ' "$_l2r_bin" 2>/dev/null; then
            cp -a "$_l2r_bin" "${_l2r_bin}.proxmenux.bak"
            sed -i 's/rsync -aAXv /rsync -aXv --no-acls /g' "$_l2r_bin"
        fi
        break
    done

    # Size-based rotation for the PBS API logs — the upstream package
    # ships no logrotate rule and pvestatd's local-datastore poll fills
    # them fast enough to saturate a tmpfs /var/log.
    if dpkg-query -W -f='${Status}' proxmox-backup-server 2>/dev/null \
        | grep -q 'install ok installed'; then
        mkdir -p /var/log/proxmox-backup/api 2>/dev/null || true
        cat > /etc/logrotate.d/proxmox-backup-api <<'EOF'
/var/log/proxmox-backup/api/access.log /var/log/proxmox-backup/api/auth.log {
    size 20M
    rotate 3
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF
        chmod 0644 /etc/logrotate.d/proxmox-backup-api
        chown root:root /etc/logrotate.d/proxmox-backup-api
        cat > /etc/cron.hourly/proxmox-backup-logrotate <<'EOF'
#!/bin/sh
/usr/sbin/logrotate /etc/logrotate.d/proxmox-backup-api >/dev/null 2>&1
EOF
        chmod 0755 /etc/cron.hourly/proxmox-backup-logrotate
        chown root:root /etc/cron.hourly/proxmox-backup-logrotate
        msg_ok "$(translate "PBS API log rotation configured (hourly, size-based)")"
    fi

    systemctl enable --now log2ram >/dev/null 2>&1 || true
    systemctl daemon-reload >/dev/null 2>&1 || true

    if [[ -f /etc/log2ram.conf ]] && command -v log2ram >/dev/null 2>&1; then
        msg_ok "$(translate "Log2RAM installed successfully")"
    else
        msg_error "$(translate "Log2RAM installation verification failed. Check /tmp/log2ram_install.log")"
        return 1
    fi

    RAM_SIZE_GB=$(free -g | awk '/^Mem:/{print $2}')
    [[ -z "$RAM_SIZE_GB" || "$RAM_SIZE_GB" -eq 0 ]] && RAM_SIZE_GB=4

    if (( RAM_SIZE_GB <= 8 )); then
        LOG2RAM_SIZE="128M"; CRON_HOURS=1
    elif (( RAM_SIZE_GB <= 16 )); then
        LOG2RAM_SIZE="256M"; CRON_HOURS=3
    else
        LOG2RAM_SIZE="512M"; CRON_HOURS=6
    fi

    msg_ok "$(translate "Detected RAM:") $RAM_SIZE_GB GB — $(translate "Log2RAM size set to:") $LOG2RAM_SIZE"
    sed -i "s/^SIZE=.*/SIZE=$LOG2RAM_SIZE/" /etc/log2ram.conf

    LOG2RAM_BIN="$(command -v log2ram || echo /usr/sbin/log2ram)"

    cat > /etc/cron.d/log2ram <<EOF
# Log2RAM periodic sync - Created by ProxMenux
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""
0 */$CRON_HOURS * * * root $LOG2RAM_BIN write >/dev/null 2>&1
EOF
    chmod 0644 /etc/cron.d/log2ram
    chown root:root /etc/cron.d/log2ram
    msg_ok "$(translate "Log2RAM write scheduled every") $CRON_HOURS $(translate "hour(s)")"

    cat > /usr/local/bin/log2ram-check.sh <<'EOF'
#!/usr/bin/env bash
# Watch /var/log usage on Log2RAM's tmpfs and act at two thresholds:
#   > 80% → vacuum journald down to ~30% of SIZE, then log2ram write
#   > 92% → aggressive: journal to ~5%, rotate PBS API logs if present,
#           truncate pveproxy/pveam, then log2ram write
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

CONF_FILE="/etc/log2ram.conf"
L2R_BIN="$(command -v log2ram || true)"
[[ -z "$L2R_BIN" && -x /usr/sbin/log2ram ]] && L2R_BIN="/usr/sbin/log2ram"
[[ -z "$L2R_BIN" ]] && exit 0

SIZE_MiB="$(grep -E '^SIZE=' "$CONF_FILE" 2>/dev/null | cut -d'=' -f2 | tr -dc '0-9')"
[[ -z "$SIZE_MiB" ]] && SIZE_MiB=128
LIMIT_BYTES=$(( SIZE_MiB * 1024 * 1024 ))
WARN_BYTES=$(( LIMIT_BYTES * 80 / 100 ))
EMERGENCY_BYTES=$(( LIMIT_BYTES * 92 / 100 ))

USED_BYTES="$(df -B1 --output=used /var/log 2>/dev/null | tail -1 | tr -dc '0-9')"
[[ -z "$USED_BYTES" ]] && exit 0

LOCK="/run/log2ram-check.lock"
exec 9>"$LOCK" 2>/dev/null || exit 0
flock -n 9 || exit 0

if (( USED_BYTES > EMERGENCY_BYTES )); then
    SAFE_JOURNAL_MB=$(( SIZE_MiB * 5 / 100 ))
    [[ "$SAFE_JOURNAL_MB" -lt 16 ]] && SAFE_JOURNAL_MB=16
    journalctl --vacuum-size="${SAFE_JOURNAL_MB}M" >/dev/null 2>&1 || true
    if [[ -x /usr/sbin/logrotate && -f /etc/logrotate.d/proxmox-backup-api ]]; then
        /usr/sbin/logrotate -f /etc/logrotate.d/proxmox-backup-api >/dev/null 2>&1 || true
    fi
    : > /var/log/pveproxy/access.log 2>/dev/null || true
    : > /var/log/pveproxy/error.log 2>/dev/null || true
    : > /var/log/pveam.log 2>/dev/null || true
    "$L2R_BIN" write 2>/dev/null || true
elif (( USED_BYTES > WARN_BYTES )); then
    SOFT_JOURNAL_MB=$(( SIZE_MiB * 30 / 100 ))
    [[ "$SOFT_JOURNAL_MB" -lt 32 ]] && SOFT_JOURNAL_MB=32
    journalctl --vacuum-size="${SOFT_JOURNAL_MB}M" >/dev/null 2>&1 || true
    "$L2R_BIN" write 2>/dev/null || true
fi
EOF
    chmod +x /usr/local/bin/log2ram-check.sh

    cat > /etc/cron.d/log2ram-auto-sync <<'EOF'
# Log2RAM auto-sync based on /var/log usage - Created by ProxMenux
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""
# nice/ionice keep the check off the priority queue for scheduled tasks.
3-59/10 * * * * root nice -n 19 ionice -c 3 /usr/local/bin/log2ram-check.sh >/dev/null 2>&1
EOF
    chmod 0644 /etc/cron.d/log2ram-auto-sync
    chown root:root /etc/cron.d/log2ram-auto-sync

    systemctl restart cron >/dev/null 2>&1 || true
    msg_ok "$(translate "Auto-sync enabled when /var/log exceeds 80% of") $LOG2RAM_SIZE"


    msg_info "$(translate "Adjusting systemd-journald limits to match Log2RAM size...")"


    if [[ -f /etc/systemd/journald.conf ]]; then
        cp -n /etc/systemd/journald.conf /etc/systemd/journald.conf.bak.$(date +%Y%m%d-%H%M%S)

    fi

    SIZE_MB=$(echo "$LOG2RAM_SIZE" | tr -dc '0-9')


    USE_MB=$(( SIZE_MB * 55 / 100 ))    
    KEEP_MB=$(( SIZE_MB * 10 / 100 ))   
    RUNTIME_MB=$(( SIZE_MB * 25 / 100 )) 


    [ "$USE_MB" -lt 80 ] && USE_MB=80
    [ "$RUNTIME_MB" -lt 32 ] && RUNTIME_MB=32
    [ "$KEEP_MB" -lt 8 ] && KEEP_MB=8


    sed -i '/^\[Journal\]/,$d' /etc/systemd/journald.conf 2>/dev/null || true
    tee -a /etc/systemd/journald.conf >/dev/null <<EOF
[Journal]
Storage=persistent
SplitMode=none
RateLimitIntervalSec=30s
RateLimitBurst=1000
ForwardToSyslog=no
ForwardToWall=no
Seal=no
Compress=yes
SystemMaxUse=${USE_MB}M
SystemKeepFree=${KEEP_MB}M
RuntimeMaxUse=${RUNTIME_MB}M
# MaxLevelStore=info: required for ProxMenux Monitor log display and Fail2Ban detection.
# Using "warning" silently discards most system logs making date filters useless.
MaxLevelStore=info
MaxLevelSyslog=info
MaxLevelKMsg=warning
MaxLevelConsole=notice
MaxLevelWall=crit
EOF


    mkdir -p /var/log/pveproxy
    chown -R www-data:www-data /var/log/pveproxy
    chmod 0750 /var/log/pveproxy

    mkdir -p /var/log.hdd/pveproxy
    chown -R www-data:www-data /var/log.hdd/pveproxy
    chmod 0750 /var/log.hdd/pveproxy

    systemctl restart systemd-journald >/dev/null 2>&1 || true
    #msg_ok "$(translate "Backup created:") /etc/systemd/journald.conf.bak.$(date +%Y%m%d-%H%M%S)"
    msg_ok "$(translate "Journald configuration adjusted to") ${USE_MB}M (Log2RAM ${LOG2RAM_SIZE})"

    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl restart log2ram >/dev/null 2>&1 || true
    log2ram clean >/dev/null 2>&1 || true
    log2ram write >/dev/null 2>&1 || true
    systemctl restart rsyslog >/dev/null 2>&1 || true

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
    local FUNC_VERSION="1.1"
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
