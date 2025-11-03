#!/bin/bash
# ==========================================================
# ProxMenux - Complete Post-Installation Script with Registration
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 06/07/2025
# ==========================================================
# Description:
#
# The script performs system optimizations including:
# - Repository configuration and system upgrades
# - Subscription banner removal and UI enhancements  
# - Advanced memory management and kernel optimizations
# - Network stack tuning and security hardening
# - Storage optimizations including log2ram for SSD protection
# - System limits increases and entropy generation improvements
# - Journald and logrotate optimizations for better log management
# - Security enhancements including RPC disabling and time synchronization
# - Bash environment customization and system monitoring setup
#
# Key Features:
# - Zero-interaction automation: Runs completely unattended
# - Intelligent hardware detection: Automatically detects SSD/NVMe for log2ram
# - RAM-aware configurations: Adjusts settings based on available system memory
# - Comprehensive error handling: Robust installation with fallback mechanisms
# - Registration system: Tracks installed optimizations for easy management
# - Reboot management: Intelligently handles reboot requirements
# - Translation support: Multi-language compatible through ProxMenux framework
# - Rollback compatibility: All optimizations can be reversed using the uninstall script
#
# This script is based on the post-install script cutotomizable
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

load_language
initialize_cache

# Global variables
OS_CODENAME="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs)"
RAM_SIZE_GB=$(( $(vmstat -s | grep -i "total memory" | xargs | cut -d" " -f 1) / 1024 / 1000))
NECESSARY_REBOOT=0
export SCRIPT_TITLE="ProxMenux Optimization Post-Installation"

# ==========================================================
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





configure_time_sync() {
    msg_info2 "$(translate "Configuring system time settings...")"

    this_ip=$(dig +short myip.opendns.com @resolver1.opendns.com 2>/dev/null)
    if [ -z "$this_ip" ]; then
        msg_warn "$(translate "Failed to obtain public IP address - keeping current timezone settings")"
        return 0
    fi

    timezone=$(curl -s --connect-timeout 10 "https://ipapi.co/${this_ip}/timezone" 2>/dev/null)
    if [ -z "$timezone" ] || [ "$timezone" = "undefined" ]; then
        msg_warn "$(translate "Failed to determine timezone from IP address - keeping current timezone settings")"
        return 0
    fi

    msg_ok "$(translate "Found timezone $timezone for IP $this_ip")"
    
    if timedatectl set-timezone "$timezone"; then
        msg_ok "$(translate "Timezone set to $timezone")"
        
        if timedatectl set-ntp true; then
            msg_ok "$(translate "Time settings configured - Timezone:") $timezone"
            register_tool "time_sync" true
            
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
  msg_info "$(translate "Configuring APT to skip downloading additional languages...")"
  cat > /etc/apt/apt.conf.d/99-disable-translations <<'EOF'
Acquire::Languages "none";
EOF
  msg_ok "$(translate "APT configured to skip additional languages")"
  register_tool "apt_languages" true
}

# ==========================================================
optimize_journald() {

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
MaxLevelStore=warning
MaxLevelSyslog=warning
MaxLevelKMsg=warning
MaxLevelConsole=notice
MaxLevelWall=crit
EOF
    
    systemctl restart systemd-journald.service > /dev/null 2>&1
    journalctl --vacuum-size=64M --vacuum-time=1d > /dev/null 2>&1
    journalctl --rotate > /dev/null 2>&1
    
    msg_ok "$(translate "Journald optimized - Max size: 64M")"
    register_tool "journald" true
}

# ==========================================================
optimize_logrotate() {
    msg_info "$(translate "Optimizing logrotate configuration...")"
    local logrotate_conf="/etc/logrotate.conf"
    local backup_conf="${logrotate_conf}.bak"
    
    if ! grep -q "# ProxMenux optimized configuration" "$logrotate_conf"; then
        cp "$logrotate_conf" "$backup_conf"
        cat <<EOF > "$logrotate_conf"
# ProxMenux optimized configuration (Log2RAM-friendly)
daily
su root adm
rotate 7
size=10M
compress
delaycompress
missingok
notifempty
create 0640 root adm
copytruncate
include /etc/logrotate.d
EOF
        systemctl restart logrotate > /dev/null 2>&1
    fi
    
    msg_ok "$(translate "Logrotate optimization completed")"
    register_tool "logrotate" true
}

# ==========================================================
increase_system_limits() {
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
            echo "DefaultLimitNOFILE=256000" >> "$file"
        fi
    done
    

    for file in /etc/pam.d/common-session /etc/pam.d/runuser-l; do
        if ! grep -q "^session required pam_limits.so" "$file"; then
            echo 'session required pam_limits.so' >> "$file"
        fi
    done
    

    if ! grep -q "ulimit -n 256000" /root/.profile; then
        echo "ulimit -n 256000" >> /root/.profile
    fi
    

    cat > /etc/sysctl.d/99-swap.conf << EOF
# ProxMenux configuration
vm.swappiness = 10
vm.vfs_cache_pressure = 100
EOF
    
 
    cat > /etc/sysctl.d/99-fs.conf << EOF
# ProxMenux configuration
fs.nr_open = 12000000
fs.file-max = 9223372036854775807
fs.aio-max-nr = 1048576
EOF
    
    msg_ok "$(translate "System limits increase completed.")"
    register_tool "system_limits" true
}

# ==========================================================
configure_entropy() {
    msg_info "$(translate "Configuring entropy generation to prevent slowdowns...")"
    
    /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install haveged > /dev/null 2>&1
    
    cat <<EOF > /etc/default/haveged
#   -w sets low entropy watermark (in bits)
DAEMON_ARGS="-w 1024"
EOF
    
    systemctl daemon-reload > /dev/null 2>&1
    systemctl enable haveged > /dev/null 2>&1
    
    msg_ok "$(translate "Entropy generation configuration completed")"
    register_tool "entropy" true
}

# ==========================================================
optimize_memory_settings() {
    msg_info "$(translate "Optimizing memory settings...")"
    NECESSARY_REBOOT=1
    
    cat <<EOF > /etc/sysctl.d/99-memory.conf
# Balanced Memory Optimization
vm.swappiness = 10
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5
vm.overcommit_memory = 1
vm.max_map_count = 65530
EOF
    
    if [ -f /proc/sys/vm/compaction_proactiveness ]; then
        echo "vm.compaction_proactiveness = 20" >> /etc/sysctl.d/99-memory.conf
    fi
    
    msg_ok "$(translate "Memory optimization completed.")"
    register_tool "memory_settings" true
}

# ==========================================================
configure_kernel_panic() {
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
    register_tool "kernel_panic" true
}

# ==========================================================
force_apt_ipv4() {
    msg_info "$(translate "Configuring APT to use IPv4...")"
    
    echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99-force-ipv4
    
    msg_ok "$(translate "APT IPv4 configuration completed")"
    register_tool "apt_ipv4" true
}

# ==========================================================

apply_network_optimizations() {
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


  cat >/etc/systemd/system/proxmenux-fwbr-tune.service <<'EOF'
[Unit]
Description=ProxMenux - Tune rp_filter/log_martians on virtual fw bridges
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'for i in /proc/sys/net/ipv4/conf/*; do n=${i##*/}; case "$n" in fwbr*|fwln*|fwpr*|tap*) echo 0 > /proc/sys/net/ipv4/conf/$n/rp_filter; echo 0 > /proc/sys/net/ipv4/conf/$n/log_martians; esac; done'

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now proxmenux-fwbr-tune.service >/dev/null 2>&1 || true


  local interfaces_file="/etc/network/interfaces"
  if ! grep -q 'source /etc/network/interfaces.d/*' "$interfaces_file"; then
      echo "source /etc/network/interfaces.d/*" >> "$interfaces_file"
  fi

  msg_ok "$(translate "Network optimization completed")"
  register_tool "network_optimization" true
}







# ==========================================================
customize_bashrc_() {
    msg_info "$(translate "Customizing bashrc for root user...")"
    local bashrc="/root/.bashrc"
    local bash_profile="/root/.bash_profile"
    
    if [ ! -f "${bashrc}.bak" ]; then
        cp "$bashrc" "${bashrc}.bak"
    fi
    
 
    cat >> "$bashrc" << 'EOF'

# ProxMenux customizations
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
EOF
    
    if ! grep -q "source /root/.bashrc" "$bash_profile"; then
        echo "source /root/.bashrc" >> "$bash_profile"
    fi
    
    msg_ok "$(translate "Bashrc customization completed")"
    register_tool "bashrc_custom" true
}



customize_bashrc() {    
    msg_info "$(translate "Customizing bashrc for root user...")"
    local bashrc="/root/.bashrc"
    local bash_profile="/root/.bash_profile"
    local marker_begin="# BEGIN PMX_CORE_BASHRC"
    local marker_end="# END PMX_CORE_BASHRC"
    
 
    [ -f "${bashrc}.bak" ] || cp "$bashrc" "${bashrc}.bak" > /dev/null 2>&1
    

    if grep -q "^${marker_begin}$" "$bashrc" 2>/dev/null; then
        sed -i "/^${marker_begin}$/,/^${marker_end}$/d" "$bashrc"  
    fi
    
 
    cat >> "$bashrc" << 'EOF'
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
    register_tool "bashrc_custom" true
}



# ==========================================================








install_log2ram_auto() {
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
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

CONF_FILE="/etc/log2ram.conf"
L2R_BIN="$(command -v log2ram || true)"
[[ -z "$L2R_BIN" && -x /usr/sbin/log2ram ]] && L2R_BIN="/usr/sbin/log2ram"
[[ -z "$L2R_BIN" ]] && exit 0

SIZE_MiB="$(grep -E '^SIZE=' "$CONF_FILE" 2>/dev/null | cut -d'=' -f2 | tr -dc '0-9')"
[[ -z "$SIZE_MiB" ]] && SIZE_MiB=128
LIMIT_BYTES=$(( SIZE_MiB * 1024 * 1024 ))
THRESHOLD_BYTES=$(( LIMIT_BYTES * 90 / 100 ))

USED_BYTES="$(df -B1 --output=used /var/log 2>/dev/null | tail -1 | tr -dc '0-9')"
[[ -z "$USED_BYTES" ]] && exit 0

LOCK="/run/log2ram-check.lock"
exec 9>"$LOCK" 2>/dev/null || exit 0
flock -n 9 || exit 0

if (( USED_BYTES > THRESHOLD_BYTES )); then
  "$L2R_BIN" write 2>/dev/null || true
fi
EOF
    chmod +x /usr/local/bin/log2ram-check.sh

    cat > /etc/cron.d/log2ram-auto-sync <<'EOF'
# Log2RAM auto-sync based on /var/log usage - Created by ProxMenux
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""
*/5 * * * * root /usr/local/bin/log2ram-check.sh >/dev/null 2>&1
EOF
    chmod 0644 /etc/cron.d/log2ram-auto-sync
    chown root:root /etc/cron.d/log2ram-auto-sync

    systemctl restart cron >/dev/null 2>&1 || true
    msg_ok "$(translate "Auto-sync enabled when /var/log exceeds 90% of") $LOG2RAM_SIZE"


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
MaxLevelStore=warning
MaxLevelSyslog=warning
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


    register_tool "log2ram" true
}








# ==========================================================


setup_persistent_network() {
    local LINK_DIR="/etc/systemd/network"
    local BACKUP_DIR="/etc/systemd/network/backup-$(date +%Y%m%d-%H%M%S)"
    

 
    msg_info "$(translate "Setting up persistent network interfaces")"
    sleep 2

    mkdir -p "$LINK_DIR"
    
    if ls "$LINK_DIR"/*.link >/dev/null 2>&1; then
        mkdir -p "$BACKUP_DIR"
        cp "$LINK_DIR"/*.link "$BACKUP_DIR"/ 2>/dev/null || true
    fi
    
    local count=0
    for iface in $(ls /sys/class/net/ | grep -vE "lo|docker|veth|br-|vmbr|tap|fwpr|fwln|virbr|bond|cilium|zt|wg"); do
        if [[ -e "/sys/class/net/$iface/device" ]] || [[ -e "/sys/class/net/$iface/phy80211" ]]; then
            local MAC=$(cat /sys/class/net/$iface/address 2>/dev/null)
            
            if [[ "$MAC" =~ ^([a-fA-F0-9]{2}:){5}[a-fA-F0-9]{2}$ ]]; then
                local LINK_FILE="$LINK_DIR/10-$iface.link"
                
                cat > "$LINK_FILE" <<EOF
[Match]
MACAddress=$MAC

[Link]
Name=$iface
EOF
                chmod 644 "$LINK_FILE"
                ((count++))
            fi
        fi
    done
    
    if [[ $count -gt 0 ]]; then
        msg_ok "$(translate "Created persistent names for") $count $(translate "interfaces")"
        msg_ok "$(translate "Changes will apply after reboot.")"
    else
        msg_warn "$(translate "No physical interfaces found")"
    fi
    register_tool "persistent_network" true

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
    configure_entropy
    optimize_memory_settings
    configure_kernel_panic
    apply_network_optimizations
    #disable_rpc
    customize_bashrc
    install_log2ram_auto
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
