#!/bin/bash

# ==========================================================
# ProxMenux - Customizable Post-Install Script
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.3
# ==========================================================
# Description:
# Interactive post-installation configurator for Proxmox VE.
# Groups ~30 optimizations into 10 categories (Basic Settings,
# System, Virtualization, Network, Storage, Security,
# Customization, Monitoring, Performance, Optional) and presents
# a checklist per category so the user picks exactly what to
# apply. Every change is registered in installed_tools.json for
# later reversal from Uninstall Optimizations.
#
# Features:
# - Checklist UI per category (10 categories, ~30 tools total).
# - Superset of the Automated script: includes the 13 baseline
#   optimizations plus opt-in items (IOMMU/VFIO, Fastfetch,
#   Figurine, Ceph repo, HA, AMD fixes, pigz, ZFS ARC, …).
# - Idempotent: safe to run repeatedly.
# - Registration + rollback: every tool has a reverse function
#   in uninstall-tools.sh.
#
# Credits:
# Incorporates ideas and snippets originally published under BSD
# by Adrian Jon Kriel (eXtremeSHOK) in xshok-proxmox, and elements
# of the Proxmox VE Post Install script from the Proxmox VE
# Helper-Scripts Community (MIT).
#   https://github.com/extremeshok/xshok-proxmox
#   https://github.com/community-scripts/ProxmoxVE
# ==========================================================


# Configuration
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# Load shared global functions
if [[ -f "$LOCAL_SCRIPTS/global/common-functions.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/common-functions.sh"
fi
if [[ -f "$LOCAL_SCRIPTS/global/utils-install-functions.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/utils-install-functions.sh"
fi
# ==========================================================


OS_CODENAME="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs )"
RAM_SIZE_GB=$(( $(vmstat -s | grep -i "total memory" | xargs | cut -d" " -f 1) / 1024 / 1000))
NECESSARY_REBOOT=0
SCRIPT_TITLE="Customizable post-installation optimization script"

TOOLS_JSON="/usr/local/share/proxmenux/installed_tools.json"

# Sprint 12A: customizable_post_install.sh always emits source=custom so
# the update detector knows to re-run the customizable flow (which asks
# the user for parameters again) instead of the silent auto flow.
SCRIPT_SOURCE="custom"

ensure_tools_json() {
  [ -f "$TOOLS_JSON" ] || echo "{}" > "$TOOLS_JSON"
}

# Sprint 12A: register_tool accepts (key, state, version, source).
# Each function declares `local FUNC_VERSION="X.Y"` on its first line and
# passes "$FUNC_VERSION" here. We use `local` rather than a `# version:`
# comment because bash's `declare -f` strips comments — comments would be
# silently lost when the update wrapper sourced the script and re-ran a
# function, leaving the registered version stuck at the default. See
# auto_post_install.sh for the full contract.
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


enable_kexec() {
    local FUNC_VERSION="1.0"
    # description: Install kexec-tools and add a Ctrl+Alt+K hotkey + systemd unit for fast reboots that skip BIOS/POST.
    msg_info2 "$(translate "Configuring kexec for quick reboots...")"
    NECESSARY_REBOOT=1

    # Set default answers for debconf
    echo "kexec-tools kexec-tools/load_kexec boolean false" | debconf-set-selections > /dev/null 2>&1

    msg_info "$(translate "Installing kexec-tools...")"
    # Install kexec-tools without showing output
    if ! dpkg -s kexec-tools >/dev/null 2>&1; then
        /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install kexec-tools > /dev/null 2>&1
        msg_ok "$(translate "kexec-tools installed successfully")"
    else
        msg_ok "$(translate "kexec-tools installed successfully")"
    fi

    # Create systemd service file
    local service_file="/etc/systemd/system/kexec-pve.service"
    if [ ! -f "$service_file" ]; then
        cat <<'EOF' > "$service_file"
[Unit]
Description=Loading new kernel into memory
Documentation=man:kexec(8)
DefaultDependencies=no
Before=reboot.target
RequiresMountsFor=/boot
#Before=shutdown.target umount.target final.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/kexec -d -l /boot/pve/vmlinuz --initrd=/boot/pve/initrd.img --reuse-cmdline

[Install]
WantedBy=default.target
EOF
        msg_ok "$(translate "kexec-pve service file created")"
    else
        msg_ok "$(translate "kexec-pve service file created")"
    fi

    # Enable the service
    if ! systemctl is-enabled kexec-pve.service > /dev/null 2>&1; then
        systemctl enable kexec-pve.service > /dev/null 2>&1
        msg_ok "$(translate "kexec-pve service enabled")"
    else
        msg_ok "$(translate "kexec-pve service enabled")"
    fi
    
    if [ ! -f /root/.bash_profile ]; then
    touch /root/.bash_profile
    fi
    
    if ! grep -q "alias reboot-quick='systemctl kexec'" /root/.bash_profile; then
        echo "alias reboot-quick='systemctl kexec'" >> /root/.bash_profile
        msg_ok "$(translate "reboot-quick alias added")"
    else
        msg_ok "$(translate "reboot-quick alias added")"
    fi

    msg_success "$(translate "kexec configured successfully. Use the command: reboot-quick")"
    register_tool "kexec" true "$FUNC_VERSION"
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

    
    msg_success "$(translate "Proxmox repository configuration completed")"
}




# ==========================================================





optimize_journald() {
    local FUNC_VERSION="1.0"
    # description: Cap journald size, raise rate limit and force info-level logging so the log viewer and Fail2Ban work.
    msg_info2 "$(translate "Limiting size and optimizing journald")"
    NECESSARY_REBOOT=1
    local journald_conf="/etc/systemd/journald.conf"
    local config_changed=false

    msg_info "$(translate "Configuring journald...")"

    # Create a temporary configuration
    cat <<EOF > /tmp/journald.conf.new
[Journal]
# Store on disk
Storage=persistent
# Don't split Journald logs by user
SplitMode=none
# Reasonable rate limits (evita spam en kernel/auditd)
RateLimitIntervalSec=30s
RateLimitBurst=1000
# Disable Journald forwarding to syslog
ForwardToSyslog=no
# Don't forward to wall (para evitar mensajes en terminales)
ForwardToWall=no
# Disable signing of the logs, save cpu resources
Seal=no
Compress=yes
# Fix the log size
SystemMaxUse=64M
RuntimeMaxUse=60M
# Optimize the logging and speed up tasks
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

    # Compare the current configuration with the new one
    if ! cmp -s "$journald_conf" "/tmp/journald.conf.new"; then
        mv "/tmp/journald.conf.new" "$journald_conf"
        config_changed=true
    else
        rm "/tmp/journald.conf.new"
    fi

    if [ "$config_changed" = true ]; then
        systemctl restart systemd-journald.service > /dev/null 2>&1
        msg_ok "$(translate "Journald configuration updated and service restarted")"
    else
        msg_ok "$(translate "Journald configuration is already optimized")"
    fi

    # Clean and rotate logs
    journalctl --vacuum-size=64M --vacuum-time=1d > /dev/null 2>&1
    journalctl --rotate > /dev/null 2>&1

    msg_success "$(translate "Journald optimization completed")"
    register_tool "journald" true "$FUNC_VERSION"
}





# ==========================================================






# ==========================================================



configure_kernel_panic() {
    local FUNC_VERSION="1.0"
    # description: Auto-reboot on kernel panic / oops / hardlockup; write crash dumps to /var/crash.
    msg_info2 "$(translate "Configuring kernel panic behavior")"
    NECESSARY_REBOOT=1

    local config_file="/etc/sysctl.d/99-kernelpanic.conf"

    msg_info "$(translate "Updating kernel panic configuration...")"

    # Create or update the configuration file
    cat <<EOF > "$config_file"
# Enable restart on kernel panic, kernel oops and hardlockup
kernel.core_pattern = /var/crash/core.%t.%p
# Reboot on kernel panic after 10s
kernel.panic = 10
# Panic on kernel oops, kernel exploits generally create an oops
kernel.panic_on_oops = 1
# Panic on a hardlockup
kernel.hardlockup_panic = 1
EOF


    msg_ok "$(translate "Kernel panic configuration updated and applied")"
    register_tool "kernel_panic" true "$FUNC_VERSION"
    msg_success "$(translate "Kernel panic behavior configuration completed")"
}




# ==========================================================




increase_system_limits() {
    local FUNC_VERSION="1.1"
    # description: Raise inotify watches, file descriptors, process keys and PID limits to enterprise levels.
    msg_info2 "$(translate "Increasing various system limits...")"
    NECESSARY_REBOOT=1
    
    # Function to safely append or replace configuration
    append_or_replace() {
        local file="$1"
        local content="$2"
        local temp_file=$(mktemp)

        if [ -f "$file" ]; then
            grep -vF "# ProxMenux configuration" "$file" > "$temp_file"
        fi
        echo -e "# ProxMenux configuration\n$content" >> "$temp_file"
        mv "$temp_file" "$file"
    }

    # Increase max user watches
    msg_info "$(translate "Configuring max user watches...")"
    append_or_replace "/etc/sysctl.d/99-maxwatches.conf" "
fs.inotify.max_user_watches = 1048576
fs.inotify.max_user_instances = 1048576
fs.inotify.max_queued_events = 1048576"
    msg_ok "$(translate "Max user watches configured")"

    # Increase max FD limit / ulimit
    msg_info "$(translate "Configuring max FD limit / ulimit...")"
    append_or_replace "/etc/security/limits.d/99-limits.conf" "
* soft     nproc          1048576
* hard     nproc          1048576
* soft     nofile         1048576
* hard     nofile         1048576
root soft     nproc          unlimited
root hard     nproc          unlimited
root soft     nofile         unlimited
root hard     nofile         unlimited"
    msg_ok "$(translate "Max FD limit / ulimit configured")"

    # Increase kernel max Key limit
    msg_info "$(translate "Configuring kernel max Key limit...")"
    append_or_replace "/etc/sysctl.d/99-maxkeys.conf" "
kernel.keys.root_maxkeys=1000000
kernel.keys.maxkeys=1000000"
    msg_ok "$(translate "Kernel max Key limit configured")"

    # Set systemd ulimits
    msg_info "$(translate "Setting systemd ulimits...")"
    for file in /etc/systemd/system.conf /etc/systemd/user.conf; do
        if ! grep -q "^DefaultLimitNOFILE=" "$file"; then
            echo "DefaultLimitNOFILE=1048576" >> "$file"
        fi
    done
    msg_ok "$(translate "Systemd ulimits set")"

    # Configure PAM limits
    msg_info "$(translate "Configuring PAM limits...")"
    for file in /etc/pam.d/common-session /etc/pam.d/runuser-l; do
        if ! grep -q "^session required pam_limits.so" "$file"; then
            echo 'session required pam_limits.so' >> "$file"
        fi
    done
    msg_ok "$(translate "PAM limits configured")"

    # Set ulimit for the shell user
    msg_info "$(translate "Setting ulimit for the shell user...")"
    if ! grep -q "ulimit -n 1048576" /root/.profile; then
        sed -i '/ulimit -n 256000/d' /root/.profile 2>/dev/null
        echo "ulimit -n 1048576" >> /root/.profile
    fi
    msg_ok "$(translate "Shell user ulimit set")"

    # Configure swappiness
    msg_info "$(translate "Configuring kernel swappiness...")"
    append_or_replace "/etc/sysctl.d/99-swap.conf" "
vm.swappiness = 10
vm.vfs_cache_pressure = 100"
    msg_ok "$(translate "Swappiness configuration created successfully")"

    # Increase Max FS open files
    msg_info "$(translate "Increasing maximum file system open files...")"
    append_or_replace "/etc/sysctl.d/99-fs.conf" "
fs.nr_open = 2097152
fs.file-max = 2097152
fs.aio-max-nr = 1048576"

    msg_ok "$(translate "Max FS open files configuration created successfully")"
    register_tool "system_limits" true "$FUNC_VERSION"
    msg_success "$(translate "System limits increase completed.")"
}



# ==========================================================





skip_apt_languages() {
    local FUNC_VERSION="1.0"
    # description: Stop APT from downloading translation files to speed up updates.
    msg_info2 "$(translate "Configuring APT to skip downloading additional languages")"

    # 1. Detect locale
    local default_locale=""
    if [ -f /etc/default/locale ]; then
        default_locale=$(grep '^LANG=' /etc/default/locale | cut -d= -f2 | tr -d '"')
    elif [ -f /etc/environment ]; then
        default_locale=$(grep '^LANG=' /etc/environment | cut -d= -f2 | tr -d '"')
    fi

    # Fallback
    default_locale="${default_locale:-en_US.UTF-8}"

    # Normalize for comparison (en_US.UTF-8 → en_US.utf8)
    local normalized_locale
    normalized_locale=$(echo "$default_locale" | tr 'A-Z' 'a-z' | sed 's/utf-8/utf8/;s/-/_/')

    # 2. Only generate if missing
    if ! locale -a | grep -qi "^$normalized_locale$"; then
        # Only add to locale.gen if missing
        if ! grep -qE "^${default_locale}[[:space:]]+UTF-8" /etc/locale.gen; then
            echo "$default_locale UTF-8" >> /etc/locale.gen
        fi
        msg_info "$(translate "Generating missing locale:") $default_locale"
        locale-gen "$default_locale"
        msg_ok "$(translate "Locale generated")"
    fi

    # 3. Set APT to skip language downloads
    local config_file="/etc/apt/apt.conf.d/99-disable-translations"
    local config_content='Acquire::Languages "none";'

    msg_info "$(translate "Setting APT language configuration...")"
    if [ -f "$config_file" ] && grep -Fxq "$config_content" "$config_file"; then
        msg_ok "$(translate "APT language configuration already set")"
    else
        echo "$config_content" > "$config_file"
        msg_ok "$(translate "APT language configuration updated")"
    fi

    register_tool "apt_languages" true "$FUNC_VERSION"
    msg_success "$(translate "APT configured to skip downloading additional languages")"
}






# ==========================================================







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
































# ==========================================================




# configure_entropy removed — modern kernels (5.6+) have built-in entropy generation
# haveged is no longer needed and adds unnecessary overhead





# ==========================================================












apply_amd_fixes() {
    local FUNC_VERSION="1.0"
    # description: Detect AMD EPYC/Ryzen CPUs and apply microcode + IOMMU + KVM-specific kernel boot params.
    msg_info2 "$(translate "Detecting AMD CPU and applying fixes if necessary...")"
    NECESSARY_REBOOT=1

    local cpu_model
    cpu_model=$(grep -i -m 1 "model name" /proc/cpuinfo || true)

    if echo "$cpu_model" | grep -qiE "EPYC|Ryzen"; then
        msg_ok "$(translate "AMD CPU detected")"
    else
        msg_ok "$(translate "No AMD CPU detected. Skipping AMD fixes.")"
        return 0
    fi

    msg_info "$(translate "Applying AMD-specific fixes...")"


    local cmdline_file="/etc/kernel/cmdline"
    local grub_file="/etc/default/grub"
    local added_param="idle=nomwait"
    local uses_zfs=false

    if grep -q "root=ZFS=" "$cmdline_file" 2>/dev/null; then
        uses_zfs=true
    fi

    if $uses_zfs && [[ -f "$cmdline_file" ]]; then
        # ZFS/systemd-boot 
        if ! grep -qw "$added_param" "$cmdline_file"; then
            cp "$cmdline_file" "${cmdline_file}.bak"

            sed -i "s|\s*$| $added_param|" "$cmdline_file"
            msg_ok "$(translate "Added '$added_param' to /etc/kernel/cmdline")"
        else
            msg_ok "$(translate "'$added_param' already present in /etc/kernel/cmdline")"
        fi

        if command -v proxmox-boot-tool >/dev/null 2>&1; then
            proxmox-boot-tool refresh >/dev/null 2>&1 && \
            msg_ok "$(translate "proxmox-boot-tool refreshed")" || \
            msg_warn "$(translate "Failed to refresh proxmox-boot-tool")"
        fi
    else
        # GRUB (no ZFS)
        if [[ -f "$grub_file" ]]; then

            grep -q '^GRUB_CMDLINE_LINUX_DEFAULT="' "$grub_file" || echo 'GRUB_CMDLINE_LINUX_DEFAULT=""' >> "$grub_file"

            if ! grep -q 'GRUB_CMDLINE_LINUX_DEFAULT=' "$grub_file"; then
                msg_warn "$(translate "GRUB_CMDLINE_LINUX_DEFAULT not found in GRUB config")"
            else
                if ! grep -q "GRUB_CMDLINE_LINUX_DEFAULT=.*\b$added_param\b" "$grub_file"; then
                    cp "$grub_file" "${grub_file}.bak"
                    sed -i "s/^\(GRUB_CMDLINE_LINUX_DEFAULT=\"[^\"]*\)\"/\1 $added_param\"/" "$grub_file"
                    msg_ok "$(translate "Added '$added_param' to GRUB_CMDLINE_LINUX_DEFAULT")"
                else
                    msg_ok "$(translate "'$added_param' already present in GRUB_CMDLINE_LINUX_DEFAULT")"
                fi
                update-grub >/dev/null 2>&1 && \
                msg_ok "$(translate "GRUB configuration updated")" || \
                msg_warn "$(translate "Failed to update GRUB")"
            fi
        else
            msg_warn "$(translate "GRUB config file not found; skipping GRUB changes")"
        fi
    fi


    local kvm_conf="/etc/modprobe.d/kvm.conf"
    touch "$kvm_conf"

    if ! grep -q "^options kvm " "$kvm_conf"; then
        echo "options kvm ignore_msrs=Y report_ignored_msrs=N" >> "$kvm_conf"
        msg_ok "$(translate "KVM MSR options added to /etc/modprobe.d/kvm.conf")"
    else

        if ! grep -q "ignore_msrs=" "$kvm_conf"; then
            sed -i 's/^options kvm /options kvm ignore_msrs=Y /' "$kvm_conf"
        else
            sed -i 's/ignore_msrs=[YNyn]/ignore_msrs=Y/' "$kvm_conf"
        fi
        if ! grep -q "report_ignored_msrs=" "$kvm_conf"; then
            sed -i 's/^options kvm .*/& report_ignored_msrs=N/' "$kvm_conf"
        else
            sed -i 's/report_ignored_msrs=[YNyn]/report_ignored_msrs=N/' "$kvm_conf"
        fi
        msg_ok "$(translate "KVM MSR options ensured in /etc/modprobe.d/kvm.conf")"
    fi

    msg_success "$(translate "AMD CPU fixes applied successfully")"
    register_tool "amd_fixes" true "$FUNC_VERSION"
}







# ==========================================================




force_apt_ipv4() {
    local FUNC_VERSION="1.0"
    # description: Force APT to use IPv4 to avoid stalls on hosts with broken IPv6 connectivity.
    msg_info2 "$(translate "Configuring APT to use IPv4...")"

    local config_file="/etc/apt/apt.conf.d/99-force-ipv4"
    local config_content="Acquire::ForceIPv4 \"true\";"

    if [ -f "$config_file" ] && grep -q "$config_content" "$config_file"; then
        msg_ok "$(translate "APT configured to use IPv4")"
    else
        msg_info "$(translate "Creating APT configuration to force IPv4...")"
        if echo -e "$config_content\n" > "$config_file"; then
        msg_ok "$(translate "APT configured to use IPv4")"
        fi
    fi

    register_tool "apt_ipv4" true "$FUNC_VERSION"
    msg_success "$(translate "APT IPv4 configuration completed")"
}





# ==========================================================





apply_network_optimizations() {
    local FUNC_VERSION="1.0"
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

# rp_filter=2 (loose) instead of the kernel default 1 (strict). Loose
# allows asymmetric routing typical of a Proxmox host with VMs on
# multiple bridges — strict mode would drop legitimate VM traffic when
# the reverse path differs. Trade-off: slightly weaker spoofing
# protection from local LAN. Document this choice rather than the
# default.
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2

# ICMP
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1

# TCP/IP
# Wider ephemeral port range than Debian's default 32768-60999 so
# Proxmox hosts handing out NAT/forward ports for many VMs/CTs don't
# run out under load. Privileged-port range (1-1023) is still protected
# by capabilities — the kernel won't actually pick one for an
# unprivileged ephemeral allocation.
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


    local interfaces_file="/etc/network/interfaces"
    if ! grep -q 'source /etc/network/interfaces.d/*' "$interfaces_file"; then
        echo "source /etc/network/interfaces.d/*" >> "$interfaces_file"
    fi

    msg_ok "$(translate "Network optimization completed")"
    register_tool "network_optimization" true "$FUNC_VERSION"
}






# ==========================================================





install_openvswitch() {
    local FUNC_VERSION="1.0"
    # description: Install OpenVSwitch for software-defined networking inside VMs and containers.
    msg_info2 "$(translate "Installing OpenVSwitch for virtual internal network...")"
    


    # Install OpenVSwitch
    msg_info "$(translate "Installing OpenVSwitch packages...")"
    (
        /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install openvswitch-switch openvswitch-common 2>&1 | \
        while IFS= read -r line; do
            if [[ $line == *"Installing"* ]] || [[ $line == *"Unpacking"* ]]; then
                printf "\r%-$(($(tput cols)-1))s\r" " "  # Clear current line
                printf "\r%s" "$line"
            fi
        done
    )

    if [ $? -eq 0 ]; then
        printf "\r%-$(($(tput cols)-1))s\r" " "  # Clear final line
        msg_ok "$(translate "OpenVSwitch installed successfully")"
    else
        printf "\r%-$(($(tput cols)-1))s\r" " "  # Clear final line
        msg_warn "$(translate "Failed to install OpenVSwitch")"
    fi

    # Verify installation
    if command -v ovs-vsctl >/dev/null 2>&1; then
        msg_success "$(translate "OpenVSwitch is ready to use")"
        register_tool "openvswitch" true "$FUNC_VERSION"
    else
        msg_warn "$(translate "OpenVSwitch installation could not be verified")"
    fi

}





# ==========================================================




enable_tcp_fast_open() {
    local FUNC_VERSION="1.0"
    # description: Enable TCP Fast Open (clients + server) and BBR congestion control for better latency under load.
    msg_info2 "$(translate "Configuring TCP optimizations...")"

    local bbr_conf="/etc/sysctl.d/99-kernel-bbr.conf"
    local tfo_conf="/etc/sysctl.d/99-tcp-fastopen.conf"
    local reboot_needed=0

    # Enable Google TCP BBR congestion control
    msg_info "$(translate "Enabling Google TCP BBR congestion control...")"
    if [ ! -f "$bbr_conf" ] || ! grep -q "net.ipv4.tcp_congestion_control = bbr" "$bbr_conf"; then
        cat <<EOF > "$bbr_conf"
# TCP BBR congestion control
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
EOF
        msg_ok "$(translate "TCP BBR configuration created successfully")"
        reboot_needed=1
    else
        msg_ok "$(translate "TCP BBR configuration created successfully")"
    fi

    # Enable TCP Fast Open
    msg_info "$(translate "Enabling TCP Fast Open...")"
    if [ ! -f "$tfo_conf" ] || ! grep -q "net.ipv4.tcp_fastopen = 3" "$tfo_conf"; then
        cat <<EOF > "$tfo_conf"
# TCP Fast Open (TFO)
net.ipv4.tcp_fastopen = 3
EOF
        msg_ok "$(translate "TCP Fast Open configuration created successfully")"
    else
        msg_ok "$(translate "TCP Fast Open configuration created successfully")"
    fi

    # Apply changes
    sysctl --system > /dev/null 2>&1

    if [ "$reboot_needed" -eq 1 ]; then
        NECESSARY_REBOOT=1
    fi

    msg_success "$(translate "TCP optimizations configuration completed")"
    register_tool "tcp_optimizations" true "$FUNC_VERSION"
}




# ==========================================================







install_ceph() {
    local FUNC_VERSION="1.0"
    # description: Install Ceph (client + server packages) for distributed RBD/CephFS storage; PVE 8/9 aware repo selection.
    msg_info2 "$(translate "Installing Ceph support...")"
    

    local pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)
    local current_codename=$(lsb_release -cs 2>/dev/null || echo "bookworm")
    local is_pve9=false
    local ceph_version="squid"
    local target_codename="bookworm"
    

    if [ "$pve_version" -ge 9 ] 2>/dev/null || [ "$current_codename" = "trixie" ]; then
        is_pve9=true
        target_codename="trixie"
        ceph_version="squid"  
        msg_info2 "$(translate "Detected Proxmox VE 9.x - Installing Ceph Squid for Debian Trixie")"
    else
        target_codename="$current_codename"
        ceph_version="squid" 
        msg_info2 "$(translate "Detected Proxmox VE 8.x - Installing Ceph Squid for Debian") $target_codename"
    fi

    if pveceph status &>/dev/null; then
        msg_ok "$(translate "Ceph is already installed")"
        msg_success "$(translate "Ceph installation check completed")"
        return 0
    fi
    
    # Configure Ceph repository based on version
    msg_info "$(translate "Configuring Ceph repository for PVE") $pve_version..."
    
    if [ "$is_pve9" = true ]; then
        # ==========================================
        # CEPH CONFIGURATION FOR PROXMOX VE 9
        # ==========================================
        

        [ -f /etc/apt/sources.list.d/ceph-squid.list ] && rm -f /etc/apt/sources.list.d/ceph-squid.list
        [ -f /etc/apt/sources.list.d/ceph.list ] && rm -f /etc/apt/sources.list.d/ceph.list
        
        # Create new deb822 format Ceph repository for PVE 9
        msg_info "$(translate "Creating Ceph repository for PVE 9 (deb822 format)...")"
        cat > /etc/apt/sources.list.d/ceph.sources << EOF
Types: deb
URIs: https://download.proxmox.com/debian/ceph-${ceph_version}
Suites: ${target_codename}
Components: no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
        msg_ok "$(translate "Ceph repository configured for PVE 9")"
        
    else
        # ==========================================
        # CEPH CONFIGURATION FOR PROXMOX VE 8
        # ==========================================
        
        # Use legacy format for PVE 8
        msg_info "$(translate "Creating Ceph repository for PVE 8 (legacy format)...")"
        echo "deb https://download.proxmox.com/debian/ceph-${ceph_version} ${target_codename} no-subscription" > /etc/apt/sources.list.d/ceph-${ceph_version}.list
        msg_ok "$(translate "Ceph repository configured for PVE 8")"
    fi
    
 
    msg_info "$(translate "Updating package lists...")"
    
    update_output=$(apt-get update 2>&1)
    update_exit_code=$?
    
    if [ $update_exit_code -eq 0 ]; then
        msg_ok "$(translate "Package lists updated successfully")"
    else
        msg_warn "$(translate "Package update had issues, checking details...")"
        

        if echo "$update_output" | grep -q "NO_PUBKEY\|GPG error"; then
            msg_info "$(translate "Fixing GPG key issues...")"

            apt-key adv --keyserver keyserver.ubuntu.com --recv-keys $(echo "$update_output" | grep "NO_PUBKEY" | sed 's/.*NO_PUBKEY //' | head -1) 2>/dev/null

            if apt-get update > /dev/null 2>&1; then
                msg_ok "$(translate "Package lists updated after GPG fix")"
            else
                msg_warn "$(translate "Package update still has issues, continuing anyway...")"
            fi
        elif echo "$update_output" | grep -q "404\|Failed to fetch"; then
            msg_warn "$(translate "Some repositories are not available, continuing with available ones...")"
        else
            msg_warn "$(translate "Package update completed with warnings, continuing...")"
        fi
    fi
    

    msg_info "$(translate "Verifying Ceph packages availability...")"
    if apt-cache search ceph-common | grep -q "ceph-common"; then
        msg_ok "$(translate "Ceph packages are available")"
    else
        msg_warn "$(translate "Ceph packages may not be available, but continuing installation...")"
    fi
    
    

    tput civis
    tput sc
    
    (pveceph install 2>&1 | \
    while IFS= read -r line; do
        if [[ $line == *"Installing"* ]] || [[ $line == *"Unpacking"* ]] || [[ $line == *"Setting up"* ]] || [[ $line == *"Processing"* ]]; then

            package_name=$(echo "$line" | sed -E 's/.*(Installing|Unpacking|Setting up|Processing) ([^ ]+).*/\2/' | head -c 30)
            [ -z "$package_name" ] && package_name="$(translate "Ceph components")"
            
            tput rc
            tput ed
            row=$(( $(tput lines) - 4 ))
            tput cup $row 0; echo "$(translate "Installing Ceph packages...")"
            tput cup $((row + 1)) 0; echo "──────────────────────────────────────────────"
            tput cup $((row + 2)) 0; echo "$(translate "Current"): $package_name"
            tput cup $((row + 3)) 0; echo "──────────────────────────────────────────────"
        fi
    done)
    
    ceph_install_exit_code=$?
    tput rc
    tput ed
    tput cnorm
    

    msg_info "$(translate "Verifying Ceph installation...")"
    

    sleep 3
    
    if pveceph status &>/dev/null; then
        msg_ok "$(translate "Ceph packages installed and verified successfully")"

        local ceph_version_info=$(ceph --version 2>/dev/null | head -1 || echo "$(translate "Version info not available")")
        msg_ok "$(translate "Installed"): $ceph_version_info"
        

        if [ "$is_pve9" = true ]; then
            if pveceph pool ls &>/dev/null 2>&1 || [ $? -eq 2 ]; then 
                msg_ok "$(translate "Ceph integration with PVE 9 verified")"
            else
                msg_warn "$(translate "Ceph installed but integration may need configuration")"
            fi
            msg_success "$(translate "Ceph installation completed successfully")"
        fi
        
        
        
    elif command -v ceph >/dev/null 2>&1; then

        msg_warn "$(translate "Ceph packages installed but service verification failed")"
        msg_info2 "$(translate "This may be normal for a fresh installation")"
        msg_success "$(translate "Ceph installation process completed")"
        
    else
        msg_warn "$(translate "Ceph installation could not be verified")"
        msg_info2 "$(translate "You may need to run 'pveceph install' manually")"
        msg_success "$(translate "Ceph installation process finished with warnings")"
    fi

    # Track install in the registry so the Uninstall menu can offer
    # `apt purge ceph-*` + repo removal. Audit Tier 6 — `install_ceph` /
    # `enable_ha` sin `register_tool` ni uninstall.
    register_tool "ceph" true "$FUNC_VERSION"
}







# ==========================================================





optimize_zfs_arc() {
    local FUNC_VERSION="1.0"
    # description: Cap ZFS ARC to a sensible fraction of host RAM so VMs don't fight the kernel for memory.
    msg_info2 "$(translate "Optimizing ZFS ARC size according to available memory...")"

    # Check if ZFS is installed
    if ! command -v zfs > /dev/null; then
        msg_warn "$(translate "ZFS not detected. Skipping ZFS ARC optimization.")"
        return 0
    fi

    # Ensure RAM_SIZE_GB is set
    if [ -z "$RAM_SIZE_GB" ]; then
        RAM_SIZE_GB=$(free -g | awk '/^Mem:/{print $2}')
        if [ -z "$RAM_SIZE_GB" ] || [ "$RAM_SIZE_GB" -eq 0 ]; then
            msg_warn "$(translate "Failed to detect RAM size. Using default value of 16GB for ZFS ARC optimization.")"
            RAM_SIZE_GB=16  # Default to 16GB if detection fails
        fi
    fi

    msg_ok "$(translate "Detected RAM size: ${RAM_SIZE_GB} GB")"

    # Calculate ZFS ARC sizes
    if [[ "$RAM_SIZE_GB" -le 16 ]]; then
        MY_ZFS_ARC_MIN=536870911  # 512MB
        MY_ZFS_ARC_MAX=536870912  # 512MB
    elif [[ "$RAM_SIZE_GB" -le 32 ]]; then
        MY_ZFS_ARC_MIN=1073741823  # 1GB
        MY_ZFS_ARC_MAX=1073741824  # 1GB
    else
        # Use 1/16 of RAM for min and 1/8 for max
        MY_ZFS_ARC_MIN=$((RAM_SIZE_GB * 1073741824 / 16))
        MY_ZFS_ARC_MAX=$((RAM_SIZE_GB * 1073741824 / 8))
    fi

    # Enforce the minimum values
    MY_ZFS_ARC_MIN=$((MY_ZFS_ARC_MIN > 536870911 ? MY_ZFS_ARC_MIN : 536870911))
    MY_ZFS_ARC_MAX=$((MY_ZFS_ARC_MAX > 536870912 ? MY_ZFS_ARC_MAX : 536870912))

    # Apply ZFS tuning parameters
    local zfs_conf="/etc/modprobe.d/99-zfsarc.conf"
    local config_changed=false

    if [ -f "$zfs_conf" ]; then
        msg_info "$(translate "Checking existing ZFS ARC configuration...")"
        if ! grep -q "zfs_arc_min=$MY_ZFS_ARC_MIN" "$zfs_conf" || \
           ! grep -q "zfs_arc_max=$MY_ZFS_ARC_MAX" "$zfs_conf"; then
            msg_ok "$(translate "Changes detected. Updating ZFS ARC configuration...")"
            cp "$zfs_conf" "${zfs_conf}.bak"
            config_changed=true
        else
            msg_ok "$(translate "ZFS ARC configuration is up to date")"
        fi
    else
        msg_info "$(translate "Creating new ZFS ARC configuration...")"
        config_changed=true
    fi

    if $config_changed; then
        cat <<EOF > "$zfs_conf"
# ZFS tuning
# Use 1/8 RAM for MAX cache, 1/16 RAM for MIN cache, or 512MB/1GB for systems with <= 32GB RAM
options zfs zfs_arc_min=$MY_ZFS_ARC_MIN
options zfs zfs_arc_max=$MY_ZFS_ARC_MAX

# Enable prefetch method
options zfs l2arc_noprefetch=0

# Set max write speed to L2ARC (500MB)
options zfs l2arc_write_max=524288000
options zfs zfs_txg_timeout=60
EOF

        if [ $? -eq 0 ]; then
            msg_ok "$(translate "ZFS ARC configuration file created/updated successfully")"
            NECESSARY_REBOOT=1
        else
            msg_error "$(translate "Failed to create/update ZFS ARC configuration file")"
        fi
    fi

    msg_success "$(translate "ZFS ARC optimization completed")"
    register_tool "zfs_arc" true "$FUNC_VERSION"
}




# ==========================================================





install_zfs_auto_snapshot() {
    local FUNC_VERSION="1.0"
    # description: Install zfs-auto-snapshot with cron schedules for hourly/daily/weekly/monthly snapshots.
    msg_info2 "$(translate "Installing and configuring ZFS auto-snapshot...")"

    # Check if zfs-auto-snapshot is already installed
    if command -v zfs-auto-snapshot >/dev/null 2>&1; then
        msg_ok "$(translate "zfs-auto-snapshot is already installed")"
    else
        # Install zfs-auto-snapshot
        msg_info "$(translate "Installing zfs-auto-snapshot package...")"
        if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install zfs-auto-snapshot > /dev/null 2>&1; then
            msg_ok "$(translate "zfs-auto-snapshot installed successfully")"
        else
            msg_error "$(translate "Failed to install zfs-auto-snapshot")"
            return 1
        fi
    fi

    # Configure snapshot schedules
    config_zfs_auto_snapshot

    msg_success "$(translate "ZFS auto-snapshot installation and configuration completed")"
    register_tool "zfs_auto_snapshot" true "$FUNC_VERSION"
}

config_zfs_auto_snapshot() {
    msg_info "$(translate "Configuring snapshot schedules...")"

    # Update 15-minute snapshots
    update_snapshot_schedule "/etc/cron.d/zfs-auto-snapshot" "frequent" "4" "*/15"

    # Update other snapshot schedules
    update_snapshot_schedule "/etc/cron.hourly/zfs-auto-snapshot" "hourly" "1"
    update_snapshot_schedule "/etc/cron.daily/zfs-auto-snapshot" "daily" "1"
    update_snapshot_schedule "/etc/cron.weekly/zfs-auto-snapshot" "weekly" "1"
    update_snapshot_schedule "/etc/cron.monthly/zfs-auto-snapshot" "monthly" "1"
}

update_snapshot_schedule() {
    local config_file="$1"
    local schedule_type="$2"
    local keep_value="$3"
    local frequency="$4"

    if [ -f "$config_file" ]; then
        if ! grep -q ".*--keep=$keep_value" "$config_file"; then
            if [ -n "$frequency" ]; then
                sed -i "s|^\*/[0-9]*.*--keep=[0-9]*|$frequency * * * * root /usr/sbin/zfs-auto-snapshot --quiet --syslog --label=$schedule_type --keep=$keep_value|" "$config_file"
            else
                sed -i "s|--keep=[0-9]*|--keep=$keep_value|g" "$config_file"
            fi
            msg_ok "$(translate "Updated $schedule_type snapshot schedule")"
        else
            msg_ok "$(translate "$schedule_type snapshot schedule already configured")"
        fi
    fi
}




# ==========================================================





disable_rpc() {
    msg_info2 "$(translate "Disabling portmapper/rpcbind for security...")"

    msg_info "$(translate "Disabling and stopping rpcbind service...")"

    # Disable and stop rpcbind
    systemctl disable rpcbind > /dev/null 2>&1
    systemctl stop rpcbind > /dev/null 2>&1

    msg_ok "$(translate "rpcbind service has been disabled and stopped")"

    msg_success "$(translate "portmapper/rpcbind has been disabled and removed")"
}




# ==========================================================




configure_pigz() {
    local FUNC_VERSION="1.0"
    # description: Replace gzip with pigz (parallel implementation) for faster vzdump backup compression.
    msg_info2 "$(translate "Configuring pigz as a faster replacement for gzip...")"

    # Enable pigz in vzdump configuration
    msg_info "$(translate "Enabling pigz in vzdump configuration...")"
    if ! grep -q "^pigz: 1" /etc/vzdump.conf; then
        sed -i "s/#pigz:.*/pigz: 1/" /etc/vzdump.conf
        msg_ok "$(translate "pigz enabled in vzdump configuration")"
    else
        msg_ok "$(translate "pigz enabled in vzdump configuration")"
    fi

    # Install pigz
    if ! dpkg -s pigz >/dev/null 2>&1; then
        msg_info "$(translate "Installing pigz...")"
        if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install pigz > /dev/null 2>&1; then
            msg_ok "$(translate "pigz installed successfully")"
        else
            msg_error "$(translate "Failed to install pigz")"
            return 1
        fi
    else
        msg_ok "$(translate "pigz installed successfully")"
    fi

    # Create pigz wrapper script
    msg_info "$(translate "Creating pigz wrapper script...")"
    if [ ! -f /bin/pigzwrapper ] || ! cmp -s /bin/pigzwrapper - <<EOF
#!/bin/sh
PATH=/bin:\$PATH
GZIP="-1"
exec /usr/bin/pigz "\$@"
EOF
    then
        cat <<EOF > /bin/pigzwrapper
#!/bin/sh
PATH=/bin:\$PATH
GZIP="-1"
exec /usr/bin/pigz "\$@"
EOF
        chmod +x /bin/pigzwrapper
        msg_ok "$(translate "pigz wrapper script created")"
    else
        msg_ok "$(translate "pigz wrapper script created")"
    fi

    # Replace gzip with pigz wrapper
    msg_info "$(translate "Replacing gzip with pigz wrapper...")"
    if [ ! -f /bin/gzip.original ]; then
        mv -f /bin/gzip /bin/gzip.original && \
        cp -f /bin/pigzwrapper /bin/gzip && \
        chmod +x /bin/gzip
        msg_ok "$(translate "gzip replaced with pigz wrapper successfully")"
    else
        msg_ok "$(translate "gzip replaced with pigz wrapper successfully")"
    fi

    msg_success "$(translate "pigz configuration completed")"
    register_tool "pigz" true "$FUNC_VERSION"
}





# ==========================================================


















# ==========================================================











# ==========================================================





install_guest_agent() {
    local FUNC_VERSION="1.0"
    # description: Detect the host's hypervisor (qemu/vmware/hyperv/virtualbox) and install the matching guest agent.
    msg_info2 "$(translate "Detecting virtualization and installing  guest agent...")"
    NECESSARY_REBOOT=1

    local virt_env=""
    local guest_agent=""

    # Detect virtualization environment
    if [ "$(dmidecode -s system-manufacturer | xargs)" == "QEMU" ] || [ "$(systemd-detect-virt | xargs)" == "kvm" ]; then
        virt_env="QEMU/KVM"
        guest_agent="qemu-guest-agent"
    elif [ "$(systemd-detect-virt | xargs)" == "vmware" ]; then
        virt_env="VMware"
        guest_agent="open-vm-tools"
    elif [ "$(systemd-detect-virt | xargs)" == "oracle" ]; then
        virt_env="VirtualBox"
        guest_agent="virtualbox-guest-utils"
    else
        msg_ok "$(translate "Guest agent detection completed")"
        msg_success "$(translate "Guest agent installation process completed")"
        return
    fi

    # Install guest agent
    if [ -n "$guest_agent" ]; then
        msg_info "$(translate "Installing $guest_agent for $virt_env...")"
        if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install $guest_agent > /dev/null 2>&1; then
            msg_ok "$(translate "$guest_agent installed successfully")"
            # Persist which package was installed so the uninstaller knows
            # what to apt purge later (different per hypervisor).
            mkdir -p /usr/local/share/proxmenux 2>/dev/null
            echo "$guest_agent" > /usr/local/share/proxmenux/guest_agent.pkg
            register_tool "guest_agent" true "$FUNC_VERSION"
        else
            msg_error "$(translate "Failed to install $guest_agent")"
        fi
    fi

    msg_success "$(translate "Guest agent installation process completed")"
}




# ==========================================================










# ==========================================================








enable_vfio_iommu() {
    local FUNC_VERSION="1.0"
    # description: Enable IOMMU and load VFIO modules to allow GPU/PCI passthrough into VMs.
    msg_info2 "$(translate "Enabling IOMMU and configuring VFIO for PCI passthrough...")"
    NECESSARY_REBOOT=1
    
    # Detect if system uses ZFS/systemd-boot (Proxmox)
    local uses_zfs=false
    local cmdline_file="/etc/kernel/cmdline"
    if [[ -f "$cmdline_file" ]] && grep -qE 'root=ZFS=|root=ZFS/' "$cmdline_file"; then
        uses_zfs=true
    fi

    if [[ "$uses_zfs" == true ]] && [[ -f "$cmdline_file" ]]; then
        msg_info "$(translate "Cleaning up duplicate parameters...")"
        cp "$cmdline_file" "${cmdline_file}.cleanup.bak"
        
        sed -i 's/intel_iommu=on[[:space:]]*intel_iommu=on/intel_iommu=on/g' "$cmdline_file"
        sed -i 's/amd_iommu=on[[:space:]]*amd_iommu=on/amd_iommu=on/g' "$cmdline_file"
        sed -i 's/iommu=pt[[:space:]]*iommu=pt/iommu=pt/g' "$cmdline_file"
        
        msg_ok "$(translate "Duplicate parameters cleaned")"
    fi
    
    # Detect CPU type and set IOMMU parameter
    local cpu_info=$(cat /proc/cpuinfo)
    local iommu_param=""
    local grub_file="/etc/default/grub"
    local additional_params="pcie_acs_override=downstream,multifunction"
    
    if [[ "$cpu_info" == *"GenuineIntel"* ]]; then
        msg_info "$(translate "Detected Intel CPU")"
        iommu_param="intel_iommu=on"
    elif [[ "$cpu_info" == *"AuthenticAMD"* ]]; then
        msg_info "$(translate "Detected AMD CPU")"
        iommu_param="amd_iommu=on"
    else
        msg_warning "$(translate "Unknown CPU type. IOMMU might not be properly enabled.")"
        return 1
    fi
    
    # Configure /etc/kernel/cmdline or GRUB
    if [[ "$uses_zfs" == true ]]; then
        # SYSTEMD-BOOT - Verificación mejorada
        local needs_iommu_param=false
        local needs_iommu_pt=false
        local needs_additional=false
        
        # Verificar qué parámetros faltan
        if ! grep -q "$iommu_param" "$cmdline_file"; then
            needs_iommu_param=true
        fi
        
        if ! grep -q "iommu=pt" "$cmdline_file"; then
            needs_iommu_pt=true
        fi
        
        if ! grep -q "pcie_acs_override=" "$cmdline_file"; then
            needs_additional=true
        fi
        
        # Solo agregar lo que falta
        if [[ "$needs_iommu_param" == true ]] || [[ "$needs_iommu_pt" == true ]] || [[ "$needs_additional" == true ]]; then
            cp "$cmdline_file" "${cmdline_file}.bak"
            
            local params_to_add=""
            [[ "$needs_iommu_param" == true ]] && params_to_add+=" $iommu_param"
            [[ "$needs_iommu_pt" == true ]] && params_to_add+=" iommu=pt"
            [[ "$needs_additional" == true ]] && params_to_add+=" $additional_params"
            
            sed -i "s|\s*$|$params_to_add|" "$cmdline_file"
            msg_ok "$(translate "IOMMU parameters added to /etc/kernel/cmdline")"
        else
            msg_ok "$(translate "IOMMU already configured in /etc/kernel/cmdline")"
        fi
        
    else
        # GRUB - Verificación mejorada
        local needs_update=false
        
        if ! grep -q "$iommu_param" "$grub_file" || ! grep -q "iommu=pt" "$grub_file"; then
            needs_update=true
        fi
        
        if [[ "$needs_update" == true ]]; then
            cp "$grub_file" "${grub_file}.bak"
            
            # Agregar parámetros que falten
            local current_line=$(grep "GRUB_CMDLINE_LINUX_DEFAULT=" "$grub_file")
            local params_to_add=""
            
            if ! echo "$current_line" | grep -q "$iommu_param"; then
                params_to_add+=" $iommu_param"
            fi
            
            if ! echo "$current_line" | grep -q "iommu=pt"; then
                params_to_add+=" iommu=pt"
            fi
            
            if ! echo "$current_line" | grep -q "pcie_acs_override="; then
                params_to_add+=" $additional_params"
            fi
            
            sed -i "/GRUB_CMDLINE_LINUX_DEFAULT=/ s|\"$|$params_to_add\"|" "$grub_file"
            msg_ok "$(translate "IOMMU enabled in GRUB configuration")"
        else
            msg_ok "$(translate "IOMMU already enabled in GRUB configuration")"
        fi
    fi
    
    # Configure VFIO modules
    local modules_file="/etc/modules"
    msg_info "$(translate "Checking VFIO modules...")"
    # vfio_virqfd was merged into the vfio module in kernel 6.2+
    # Adding it as a separate module on kernel >= 6.2 generates warnings
    local kernel_major kernel_minor
    kernel_major=$(uname -r | cut -d. -f1)
    kernel_minor=$(uname -r | cut -d. -f2)
    local vfio_modules=("vfio" "vfio_iommu_type1" "vfio_pci")
    if (( kernel_major < 6 || ( kernel_major == 6 && kernel_minor < 2 ) )); then
        vfio_modules+=("vfio_virqfd")
    fi

    for module in "${vfio_modules[@]}"; do
        if ! grep -q "^$module" "$modules_file"; then
            echo "$module" >> "$modules_file"
        fi
    done
    msg_ok "$(translate "VFIO modules configured.")"
    
    # Blacklist conflicting drivers (sin cambios)
    local blacklist_file="/etc/modprobe.d/blacklist.conf"
    msg_info "$(translate "Checking conflicting drivers blacklist...")"
    touch "$blacklist_file"
    
    local blacklist_drivers=("nouveau" "lbm-nouveau" "radeon" "nvidia" "nvidiafb")
    for driver in "${blacklist_drivers[@]}"; do
        if ! grep -q "^blacklist $driver" "$blacklist_file"; then
            echo "blacklist $driver" >> "$blacklist_file"
        fi
    done
    
    if ! grep -q "options nouveau modeset=0" "$blacklist_file"; then
        echo "options nouveau modeset=0" >> "$blacklist_file"
    fi
    msg_ok "$(translate "Conflicting drivers blacklisted successfully.")"
    
    # Update initramfs and bootloader
    msg_info "$(translate "Updating initramfs, GRUB, and EFI boot, patience...")"
    update-initramfs -u -k all > /dev/null 2>&1
    
    if [[ "$uses_zfs" == true ]]; then
        proxmox-boot-tool refresh > /dev/null 2>&1
    else
        update-grub > /dev/null 2>&1
    fi
    
    msg_success "$(translate "IOMMU and VFIO setup completed")"
    register_tool "vfio_iommu" true "$FUNC_VERSION"
}




# ==========================================================









customize_bashrc() {
    local FUNC_VERSION="1.0"
    # description: Inject the ProxMenux core bashrc block (aliases, prompt, history) into root's .bashrc, idempotent via begin/end markers.
    msg_info2 "$(translate "Customizing bashrc for root user...")"
    
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




setup_motd() {
    msg_info2 "$(translate "Configuring MOTD (Message of the Day) banner...")"

    local motd_file="/etc/motd"
    local custom_message="    This system is optimised by: ProxMenux"
    local changes_made=false

    msg_info "$(translate "Checking MOTD configuration...")"

    # Check if the custom message already exists
    if grep -q "$custom_message" "$motd_file"; then
        msg_ok "$(translate "Custom message added to MOTD")"
    else
        # Create a backup of the original MOTD file
        if [ ! -f "${motd_file}.bak" ]; then
            cp "$motd_file" "${motd_file}.bak"
            msg_ok "$(translate "Backup of original MOTD created")"
        fi

        # Add the custom message at the beginning of the file
        echo -e "$custom_message\n\n$(cat $motd_file)" > "$motd_file"
        changes_made=true
        msg_ok "$(translate "Custom message added to MOTD")"
    fi

    sed -i '/^$/N;/^\n$/D' "$motd_file"

    if $changes_made; then
        msg_success "$(translate "MOTD configuration updated successfully")"
    else
        msg_success "$(translate "MOTD configuration updated successfully")"
    fi
}





# ==========================================================





optimize_logrotate() {
    local FUNC_VERSION="1.1"
    # description: Replace logrotate.conf with a Log2RAM-friendly profile (daily rotation, copytruncate).
    msg_info2 "$(translate "Optimizing logrotate configuration...")"

    local logrotate_conf="/etc/logrotate.conf"
    local backup_conf="${logrotate_conf}.bak"

    cp -n "$logrotate_conf" "$backup_conf" 2>/dev/null || true

    msg_info "$(translate "Applying optimized logrotate configuration...")"
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
    msg_ok "$(translate "Logrotate service restarted successfully")"
    register_tool "logrotate" true "$FUNC_VERSION"
    msg_success "$(translate "Logrotate optimization completed")"
}





# ==========================================================





remove_subscription_banner() {
    local FUNC_VERSION="1.0"
    # description: Patch the Proxmox web UI to suppress the "no valid subscription" dialog (PVE 8 + 9 variants supported).
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

    if [[ -z "$pve_version" ]]; then
        msg_error "Unable to detect Proxmox version."
        return 1
    fi

    if [[ "$pve_version" -ge 9 ]]; then

        bash "$LOCAL_SCRIPTS/global/remove-banner-pve-v3.sh"
    else

        bash "$LOCAL_SCRIPTS/global/remove-banner-pve8.sh"
    fi
    register_tool "subscription_banner" true "$FUNC_VERSION"
}





# ==========================================================





optimize_memory_settings() {
    local FUNC_VERSION="1.1"
    # description: Tune swappiness, dirty page ratios, overcommit and compaction proactiveness for VM hosts.
    msg_info2 "$(translate "Optimizing memory settings...")"
    NECESSARY_REBOOT=1

    local sysctl_conf="/etc/sysctl.d/99-memory.conf"


    if [ -f "$sysctl_conf" ] && grep -q "Memory Optimising" "$sysctl_conf"; then
        msg_info "$(translate "Old memory configuration detected. Replacing with balanced optimization...")"
    else
        msg_info "$(translate "Applying balanced memory optimization settings...")"
    fi

    cat <<EOF > "$sysctl_conf"
# Balanced Memory Optimization
# Improve responsiveness without excessive memory reservation

# Avoid unnecessary swapping
vm.swappiness = 10

# Lower dirty memory thresholds to free memory faster
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5

# Allow memory overcommit to reduce allocation issues
vm.overcommit_memory = 1

# Avoid excessive virtual memory areas (safe for most applications)
vm.max_map_count = 262144
EOF

    if [ -f /proc/sys/vm/compaction_proactiveness ]; then
        echo "vm.compaction_proactiveness = 20" >> "$sysctl_conf"
        msg_ok "$(translate "Enabled memory compaction proactiveness")"
    fi

    msg_ok "$(translate "Memory settings optimized successfully")"
    msg_success "$(translate "Memory optimization completed.")"
    register_tool "memory_settings" true "$FUNC_VERSION"
}





# ==========================================================





optimize_vzdump() {
    local FUNC_VERSION="1.0"
    # description: Lift vzdump bandwidth/IO limits so backups run at the storage's real throughput.
    msg_info2 "$(translate "Optimizing vzdump backup speed...")"

    local vzdump_conf="/etc/vzdump.conf"

    # Backup the current config so the uninstall path can restore the
    # user's original values. The previous code edited in-place with no
    # backup; users with custom bwlimit/ionice lost them silently.
    if [[ -f "$vzdump_conf" && ! -f "${vzdump_conf}.bak" ]]; then
        cp -p "$vzdump_conf" "${vzdump_conf}.bak"
    fi

    # Configure bandwidth limit
    msg_info "$(translate "Configuring bandwidth limit for vzdump...")"
    if ! grep -q "^bwlimit: 0" "$vzdump_conf"; then
        sed -i '/^#*bwlimit:/d' "$vzdump_conf"
        echo "bwlimit: 0" >> "$vzdump_conf"
    fi
    msg_ok "$(translate "Bandwidth limit configured")"

    # Configure I/O priority
    msg_info "$(translate "Configuring I/O priority for vzdump...")"
    if ! grep -q "^ionice: 5" "$vzdump_conf"; then
        sed -i '/^#*ionice:/d' "$vzdump_conf"
        echo "ionice: 5" >> "$vzdump_conf"
    fi
    msg_ok "$(translate "I/O priority configured")"

    msg_success "$(translate "vzdump backup speed optimization completed")"
    register_tool "vzdump_speed" true "$FUNC_VERSION"
}





# ==========================================================





install_ovh_rtm() {
    local FUNC_VERSION="1.0"
    # description: Detect OVH-rented hardware via whois lookup and install OVH Real-Time Monitoring (no-op on non-OVH).
    msg_info2 "$(translate "Detecting if this is an OVH server and installing OVH RTM if necessary...")"

    # Get the public IP and check if it belongs to OVH
    msg_info "$(translate "Checking if the server belongs to OVH...")"
    public_ip=$(curl -s ipinfo.io/ip)
    # `--` ends whois client option parsing so "-t IP" reaches the cymru server
    # as the query string. Previous form had a leading space inside the quotes
    # ("\" -t IP\"") that mangled the query and caused detection to never match.
    is_ovh=$(whois -h v4.whois.cymru.com -- "-t $public_ip" | tail -n 1 | cut -d'|' -f3 | grep -i "ovh")

    if [ -n "$is_ovh" ]; then
        msg_ok "$(translate "OVH server detected")"

        msg_info "$(translate "Installing OVH RTM (Real Time Monitoring)...")"
        if wget -qO - https://last-public-ovh-infra-yak.snap.mirrors.ovh.net/yak/archives/apply.sh | OVH_PUPPET_MANIFEST=distribyak/catalog/master/puppet/manifests/common/rtmv2.pp bash > /dev/null 2>&1; then
            msg_ok "$(translate "OVH RTM installed successfully")"
            register_tool "ovh_rtm" true "$FUNC_VERSION"
        else
            msg_error "$(translate "Failed to install OVH RTM")"
        fi
    else
        msg_ok "$(translate "Not an OVH server, skipping RTM installation")"
    fi
    msg_success "$(translate "OVH server detection and RTM installation process completed")"
}




# ==========================================================



enable_ha() {
    local FUNC_VERSION="1.0"
    # description: Enable the Proxmox HA stack (pve-ha-lrm, pve-ha-crm, corosync) for cluster failover.
    msg_info2 "$(translate "Enabling High Availability (HA) services...")"
    NECESSARY_REBOOT=1

    msg_info "$(translate "Enabling High Availability (HA) services...")"
    # Enable all necessary services
    systemctl enable -q --now pve-ha-lrm pve-ha-crm corosync &>/dev/null


    msg_ok "$(translate "High Availability services have been enabled successfully")"
    msg_success "$(translate "High Availability setup completed")"

    register_tool "ha" true "$FUNC_VERSION"
}




# ==========================================================






configure_fastfetch() {
    local FUNC_VERSION="1.1"
    # description: Install Fastfetch system summary tool with the ProxMenux logo + status block as the SSH login banner.
    msg_info2 "$(translate "Installing and configuring Fastfetch...")"


    # Define paths
    local fastfetch_bin="/usr/local/bin/fastfetch"
    local fastfetch_config_dir="$HOME/.config/fastfetch"
    local logos_dir="/usr/local/share/fastfetch/logos"
    local fastfetch_config="$fastfetch_config_dir/config.jsonc"

    # Ensure directories exist
    mkdir -p "$fastfetch_config_dir"
    mkdir -p "$logos_dir"

    
    if command -v fastfetch &> /dev/null; then
        apt-get remove --purge -y fastfetch > /dev/null 2>&1
        rm -f /usr/bin/fastfetch /usr/local/bin/fastfetch
    fi

    
    msg_info "$(translate "Downloading the latest Fastfetch release...")"
    # `--connect-timeout`/`--max-time` so a slow GitHub API call doesn't
    # hang the menu indefinitely. `FASTFETCH_PIN_TAG` env var lets the
    # caller pin to a known release if upstream introduces a breaking
    # change. Audit Tier 6 — recursos remotos sin pinning de versión.
    local fastfetch_deb_url=""
    if [[ -n "${FASTFETCH_PIN_TAG:-}" ]]; then
        fastfetch_deb_url="https://github.com/fastfetch-cli/fastfetch/releases/download/${FASTFETCH_PIN_TAG}/fastfetch-linux-amd64.deb"
    else
        fastfetch_deb_url=$(curl -s --connect-timeout 5 --max-time 15 https://api.github.com/repos/fastfetch-cli/fastfetch/releases/latest |
            jq -r '.assets[] | select(.name | test("fastfetch-linux-amd64.deb")) | .browser_download_url')
    fi

    if [[ -z "$fastfetch_deb_url" ]]; then
        msg_error "$(translate "Failed to retrieve Fastfetch download URL.")"
        return 1
    fi
   msg_ok "$(translate "Fastfetch download URL retrieved successfully.")"

    
    wget -qO /tmp/fastfetch.deb "$fastfetch_deb_url"
    if dpkg -i /tmp/fastfetch.deb > /dev/null 2>&1; then
        apt-get install -f -y  > /dev/null 2>&1 
        msg_ok "$(translate "Fastfetch installed successfully")"
    else
        msg_error "$(translate "Failed to install Fastfetch.")"
        return 1
    fi

    
    rm -f /tmp/fastfetch.deb

    
    if ! command -v fastfetch &> /dev/null; then
        msg_error "$(translate "Fastfetch is not installed correctly.")"
        return 1
    fi

    
    if [ ! -f "$fastfetch_config" ]; then
        echo '{"$schema": "https://github.com/fastfetch-cli/fastfetch/raw/dev/doc/json_schema.json", "modules": []}' > "$fastfetch_config"
    fi

    fastfetch --gen-config-force > /dev/null 2>&1

    while true; do
        # Define logo options
        local logo_options=("ProxMenux" "Proxmox (default)" "JC Channel" "Comunidad Helper-Scripts" "Home-Labs-Club" "Proxmology" "Custom")
        local choice

        choice=$(whiptail --title "$(translate "Fastfetch Logo Selection")" --menu "$(translate "Choose a logo for Fastfetch:")" 20 78 7 \
            "1" "${logo_options[0]}" \
            "2" "${logo_options[1]}" \
            "3" "${logo_options[2]}" \
            "4" "${logo_options[3]}" \
            "5" "${logo_options[4]}" \
            "6" "${logo_options[5]}" \
            "7" "${logo_options[6]}" \
            3>&1 1>&2 2>&3)

        case $choice in
            1)
                msg_info "$(translate "Downloading ProxMenux logo...")"
                local proxmenux_logo_path="$logos_dir/ProxMenux.txt"
                if wget -qO "$proxmenux_logo_path" "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logos_txt/logo.txt"; then
                    jq --arg path "$proxmenux_logo_path" '. + {logo: $path}' "$fastfetch_config" > "${fastfetch_config}.tmp" && mv "${fastfetch_config}.tmp" "$fastfetch_config"
                    msg_ok "$(translate "ProxMenux logo applied")"
                else
                    msg_error "$(translate "Failed to download ProxMenux logo")"
                fi
                break
                ;;
            2)
                msg_info "$(translate "Using default Proxmox logo...")"
                jq 'del(.logo)' "$fastfetch_config" > "${fastfetch_config}.tmp" && mv "${fastfetch_config}.tmp" "$fastfetch_config"
                msg_ok "$(translate "Default Proxmox logo applied")"
                break
                ;;
            3)
                msg_info "$(translate "Downloading JC Channel logo...")"
                local jc_channel_logo_path="$logos_dir/jc_channel.txt"
                if wget -qO "$jc_channel_logo_path" "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logos_txt/jc_channel.txt"; then
                    jq --arg path "$jc_channel_logo_path" '. + {logo: $path}' "$fastfetch_config" > "${fastfetch_config}.tmp" && mv "${fastfetch_config}.tmp" "$fastfetch_config"
                    msg_ok "$(translate "JC Channel logo applied")"
                else
                    msg_error "$(translate "Failed to download JC Channel logo")"
                fi
                break
                ;;
            4)
                msg_info "$(translate "Downloading Helper-Scripts logo...")"
                local helper_scripts_logo_path="$logos_dir/Helper_Scripts.txt"
                if wget -qO "$helper_scripts_logo_path" "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logos_txt/Helper_Scripts.txt"; then
                    jq --arg path "$helper_scripts_logo_path" '. + {logo: $path}' "$fastfetch_config" > "${fastfetch_config}.tmp" && mv "${fastfetch_config}.tmp" "$fastfetch_config"
                    msg_ok "$(translate "Helper-Scripts logo applied")"
                else
                    msg_error "$(translate "Failed to download Helper-Scripts logo")"
                fi
                break
                ;;
            5)
                msg_info "$(translate "Downloading Home-Labs-Club logo...")"
                local home_lab_club_logo_path="$logos_dir/home_labsclub.txt"
                if wget -qO "$home_lab_club_logo_path" "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logos_txt/home_labsclub.txt"; then
                    jq --arg path "$home_lab_club_logo_path" '. + {logo: $path}' "$fastfetch_config" > "${fastfetch_config}.tmp" && mv "${fastfetch_config}.tmp" "$fastfetch_config"
                    msg_ok "$(translate "Home-Lab-Club logo applied")"
                else
                    msg_error "$(translate "Failed to download Home-Lab-Club logo")"
                fi
                break
                ;;
            6)
                msg_info "$(translate "Downloading Proxmology logo...")"
                local proxmology_logo_path="$logos_dir/proxmology.txt"
                if wget -qO "$proxmology_logo_path" "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logos_txt/proxmology.txt"; then
                    jq --arg path "$proxmology_logo_path" '. + {logo: $path}' "$fastfetch_config" > "${fastfetch_config}.tmp" && mv "${fastfetch_config}.tmp" "$fastfetch_config"
                    msg_ok "$(translate "Proxmology logo applied")"
                else
                    msg_error "$(translate "Failed to download Proxmology logo")"
                fi
                break
                ;;
            7)
                whiptail --title "$(translate "Custom Logo Instructions")" --msgbox "$(translate "To use a custom Fastfetch logo, place your ASCII logo file in:\n\n/usr/local/share/fastfetch/logos/\n\nThe file should not exceed 35 lines to fit properly in the terminal.\n\nPress OK to continue and select your logo.")" 15 70

                local logo_files=($(ls "$logos_dir"/*.txt 2>/dev/null))
                
                if [ ${#logo_files[@]} -eq 0 ]; then
                    whiptail --title "$(translate "No Custom Logos Found")" --msgbox "$(translate "No custom logos were found in /usr/local/share/fastfetch/logos/.\n\nPlease add a logo and try again.")" 10 60
                    continue
                fi

                local menu_items=()
                local index=1
                for file in "${logo_files[@]}"; do
                    menu_items+=("$index" "$(basename "$file")")
                    index=$((index+1))
                done

                local selected_logo_index
                selected_logo_index=$(whiptail --title "$(translate "Select a Custom Logo")" --menu "$(translate "Choose a custom logo:")" 20 70 10 "${menu_items[@]}" 3>&1 1>&2 2>&3)

                if [ -z "$selected_logo_index" ]; then
                    continue
                fi

                local selected_logo="${logo_files[$((selected_logo_index-1))]}"
                jq --arg path "$selected_logo" '. + {logo: $path}' "$fastfetch_config" > "${fastfetch_config}.tmp" && mv "${fastfetch_config}.tmp" "$fastfetch_config"
                msg_ok "$(translate "Custom logo applied: $(basename "$selected_logo")")"
                break
                ;;
            *)
                msg_warn "$(translate "You must select a logo to continue.")"
                ;;
        esac
    done

    # Modify Fastfetch modules to display custom title
    msg_info "$(translate "Modifying Fastfetch configuration...")"

    jq '.modules |= map(select(. != "title"))' "$fastfetch_config" > "${fastfetch_config}.tmp" && mv "${fastfetch_config}.tmp" "$fastfetch_config"

    jq 'del(.modules[] | select(type == "object" and .type == "custom"))' "$fastfetch_config" > "${fastfetch_config}.tmp" && mv "${fastfetch_config}.tmp" "$fastfetch_config"

    jq '.modules |= [{"type": "custom", "format": "\u001b[1;38;5;166mSystem optimised by ProxMenux\u001b[0m"}] + .' "$fastfetch_config" > "${fastfetch_config}.tmp" && mv "${fastfetch_config}.tmp" "$fastfetch_config"

    msg_ok "$(translate "Fastfetch now displays: System optimised by: ProxMenux")"

    fastfetch --gen-config > /dev/null 2>&1
    msg_ok "$(translate "Fastfetch configuration updated")"


    sed -i '/fastfetch/d' ~/.profile /etc/profile 2>/dev/null
    rm -f /etc/update-motd.d/99-fastfetch

    sed -i '/# BEGIN FASTFETCH/,/# END FASTFETCH/d' "$HOME/.bashrc" 2>/dev/null

if ! grep -q '# BEGIN FASTFETCH' "$HOME/.bashrc"; then
    cat << 'EOF' >> "$HOME/.bashrc"

# BEGIN FASTFETCH
# Run Fastfetch only in interactive sessions
if [[ $- == *i* ]] && command -v fastfetch &>/dev/null; then
    clear
    fastfetch
fi
# END FASTFETCH
EOF
fi

msg_ok "$(translate "Fastfetch will start automatically in the console")"
msg_success "$(translate "Fastfetch installation and configuration completed")"
register_tool "fastfetch" true "$FUNC_VERSION"

}






# ==========================================================









# ==========================================================











configure_figurine() {
    local FUNC_VERSION="1.1"
    # description: Install Figurine (ASCII-art hostname banner) and wire it into the SSH login flow.
    msg_info2 "$(translate "Installing and configuring Figurine...")"
    # `FIGURINE_VERSION` env var allows pinning to a specific release;
    # default tracks the last tested upstream tag. Audit Tier 6 —
    # recursos remotos sin pinning de versión.
    local version="${FIGURINE_VERSION:-2.0.0}"
    local file="figurine_linux_amd64_v${version}.tar.gz"
    local url="https://github.com/arsham/figurine/releases/download/v${version}/${file}"
    local temp_dir; temp_dir=$(mktemp -d)
    local install_dir="/usr/local/bin"
    local profile_script="/etc/profile.d/figurine.sh"
    local bin_path="${install_dir}/figurine"
    local bashrc="/root/.bashrc"

    cleanup_dir() { rm -rf "$temp_dir" 2>/dev/null || true; }
    trap cleanup_dir EXIT

    [[ -f "$bashrc" ]] || touch "$bashrc"

    if command -v figurine &>/dev/null; then
        msg_info "$(translate "Updating Figurine binary...")"
    else
        msg_info "$(translate "Downloading Figurine v${version}...")"
    fi

    if ! wget -qO "${temp_dir}/${file}" "$url"; then
        msg_error "$(translate "Failed to download Figurine")"
        return 1
    fi

    if ! tar -xf "${temp_dir}/${file}" -C "${temp_dir}"; then
        msg_error "$(translate "Failed to extract package")"
        return 1
    fi
    msg_ok "$(translate "Extraction successful")"

    if [[ ! -f "${temp_dir}/deploy/figurine" ]]; then
        msg_error "$(translate "Binary not found in extracted content.")"
        return 1
    fi

    msg_info "$(translate "Installing binary to ${install_dir}...")"
    install -m 0755 -o root -g root "${temp_dir}/deploy/figurine" "$bin_path"


    cat > "$profile_script" << 'EOF'
/usr/local/bin/figurine -f "3d.flf" $(hostname)
EOF
    chmod +x "$profile_script"


    ensure_aliases() {
    local bashrc="/root/.bashrc"
    [[ -f "$bashrc" ]] || touch "$bashrc"

    if ! grep -q "shopt -s expand_aliases" "$bashrc" 2>/dev/null; then
        echo "shopt -s expand_aliases" >> "$bashrc"
    fi

    local -a ALIASES=(
        "aptup=apt update && apt dist-upgrade"
        "lxcclean=bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/clean-lxcs.sh)\""
        "lxcupdate=bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/update-lxcs.sh)\""
        "kernelclean=bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/kernel-clean.sh)\""
        "cpugov=bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/scaling-governor.sh)\""
        "lxctrim=bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/fstrim.sh)\""
        "updatecerts=pvecm updatecerts"
        "seqwrite=sync; fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4M --size=32G --readwrite=write --ramp_time=4"
        "seqread=sync;  fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4M --size=32G --readwrite=read  --ramp_time=4"
        "ranwrite=sync; fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4k --size=4G --readwrite=randwrite --ramp_time=4"
        "ranread=sync;  fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4k --size=4G --readwrite=randread  --ramp_time=4"
    )

    for entry in "${ALIASES[@]}"; do
        local name="${entry%%=*}"
        local cmd="${entry#*=}"

        local safe_cmd=${cmd//\'/\'\\\'\'}

        sed -i -E "/^[[:space:]]*alias[[:space:]]+${name}=.*/d" "$bashrc"

        printf "alias %s='%s'\n" "$name" "$safe_cmd" >> "$bashrc"
    done

    . "$bashrc"
    }


    ensure_aliases
    msg_ok "$(translate "Aliases added to .bashrc")"

    msg_success "$(translate "Figurine installation and configuration completed successfully.")"
    register_tool "figurine" true "$FUNC_VERSION"
}










# ==========================================================





update_pve_appliance_manager() {
    msg_info "$(translate "Updating PVE application manager...")"
    if pveam update > /dev/null 2>&1; then
        msg_ok "$(translate "PVE application manager updated")"
    else
        msg_warn "$(translate "No updates or failed to fetch templates")"
    fi
}




# ==========================================================











configure_log2ram() {
    local FUNC_VERSION="1.2"
    # description: Install Log2RAM with user-chosen RAM size; prompts for size and SSD/M.2 awareness before applying.
    msg_info2 "$(translate "Preparing Log2RAM configuration")"
    sleep 1


    RAM_SIZE_GB=$(free -g | awk '/^Mem:/{print $2}')
    [[ -z "$RAM_SIZE_GB" || "$RAM_SIZE_GB" -eq 0 ]] && RAM_SIZE_GB=4

    if (( RAM_SIZE_GB <= 8 )); then
        DEFAULT_SIZE="128"   # MiB
        DEFAULT_HOURS="1"
    elif (( RAM_SIZE_GB <= 16 )); then
        DEFAULT_SIZE="256"
        DEFAULT_HOURS="3"
    else
        DEFAULT_SIZE="512"
        DEFAULT_HOURS="6"
    fi


    USER_SIZE=$(whiptail --title "Log2RAM" --inputbox \
        "$(translate "Enter the maximum size (in MB) to allocate for /var/log in RAM (e.g. 128, 256, 512):")\n\n$(translate "Recommended for $RAM_SIZE_GB GB RAM:") ${DEFAULT_SIZE}M" \
        12 70 "$DEFAULT_SIZE" 3>&1 1>&2 2>&3) || return 0

    if ! [[ "$USER_SIZE" =~ ^[0-9]+$ ]]; then
        msg_error "$(translate "Invalid size. Please enter a number in MB (e.g., 128, 256, 512).")"
        return 1
    fi
    (( USER_SIZE < 64 ))  && USER_SIZE=64      # mínimo razonable
    (( USER_SIZE > 8192 )) && USER_SIZE=8192   # límite de seguridad
    LOG2RAM_SIZE="${USER_SIZE}M"

   
    CRON_HOURS=$(whiptail --title "Log2RAM" --radiolist \
        "$(translate "Select the sync interval (in hours):")\n\n$(translate "Suggested interval: every $DEFAULT_HOURS hour(s)")" \
        15 70 5 \
        "1"  "$(translate "Every hour")"     $([[ "$DEFAULT_HOURS" = "1"  ]] && echo ON || echo OFF) \
        "3"  "$(translate "Every 3 hours")"  $([[ "$DEFAULT_HOURS" = "3"  ]] && echo ON || echo OFF) \
        "6"  "$(translate "Every 6 hours")"  $([[ "$DEFAULT_HOURS" = "6"  ]] && echo ON || echo OFF) \
        "12" "$(translate "Every 12 hours")" OFF \
        3>&1 1>&2 2>&3) || return 0

 
    if whiptail --title "Log2RAM" --yesno "$(translate "Enable auto-sync if /var/log exceeds 90% of its size?")" 10 60; then
        ENABLE_AUTOSYNC=true
    else
        ENABLE_AUTOSYNC=false
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

    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl restart cron >/dev/null 2>&1 || true
    msg_ok "$(translate "Previous installation cleaned")"

   
    msg_info "$(translate "Installing Log2RAM from GitHub...")"
    if ! command -v git >/dev/null 2>&1; then
        msg_info "$(translate "Installing required package: git")"
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y git >/dev/null 2>&1
    fi

    rm -rf /tmp/log2ram 2>/dev/null || true
    # Pin to a tested release — `master` could ship breaking changes
    # without notice. `LOG2RAM_TAG` env var lets the caller upgrade.
    local LOG2RAM_TAG="${LOG2RAM_TAG:-1.7.0}"
    if ! git clone --depth 1 --branch "$LOG2RAM_TAG" \
            https://github.com/azlux/log2ram.git /tmp/log2ram \
            >/dev/null 2>>/tmp/log2ram_install.log \
       && ! git clone --depth 1 https://github.com/azlux/log2ram.git /tmp/log2ram \
            >/dev/null 2>>/tmp/log2ram_install.log; then
        msg_error "$(translate "Failed to clone log2ram repository. Check /tmp/log2ram_install.log")"
        return 1
    fi

    cd /tmp/log2ram || { msg_error "$(translate "Failed to access log2ram directory")"; return 1; }
    if ! bash install.sh >>/tmp/log2ram_install.log 2>&1; then
        msg_error "$(translate "Failed to run log2ram installer. Check /tmp/log2ram_install.log")"
        return 1
    fi

    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl enable --now log2ram >/dev/null 2>&1 || true

    if [[ -f /etc/log2ram.conf ]] && command -v log2ram >/dev/null 2>&1; then
        msg_ok "$(translate "Log2RAM installed successfully")"
    else
        msg_error "$(translate "Log2RAM installation verification failed. Check /tmp/log2ram_install.log")"
        return 1
    fi

  
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

   
    if [[ "$ENABLE_AUTOSYNC" == true ]]; then
        cat > /usr/local/bin/log2ram-check.sh <<'EOF'
#!/usr/bin/env bash
# v1.2 — `log2ram write` only copies tmpfs→disk; it does NOT shrink
# the tmpfs. When journald or pveproxy/access.log grow past their
# limits the tmpfs hit 100% and PVE crashed with "No space left on
# device" on Shell open (community-reported: JC Miñarro, Nicolás P.
# de A., 17-18/05). We now vacuum the journal and truncate the
# non-rotating logs that actually consume the tmpfs before calling
# `log2ram write`.
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

# `log2ram write` alone leaves the tmpfs full. Real recovery requires:
# (a) journal vacuum — journald respects --vacuum-size unconditionally,
#     unlike SystemMaxUse which only enforces on rotation boundaries;
# (b) truncating logs that aren't rotated by logrotate (pveproxy, pveam);
# (c) THEN syncing to disk so the persistent copy reflects reality.
if (( USED_BYTES > EMERGENCY_BYTES )); then
    SAFE_JOURNAL_MB=$(( SIZE_MiB * 5 / 100 ))
    [[ "$SAFE_JOURNAL_MB" -lt 16 ]] && SAFE_JOURNAL_MB=16
    journalctl --vacuum-size="${SAFE_JOURNAL_MB}M" >/dev/null 2>&1 || true
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
*/5 * * * * root /usr/local/bin/log2ram-check.sh >/dev/null 2>&1
EOF
        chmod 0644 /etc/cron.d/log2ram-auto-sync
        chown root:root /etc/cron.d/log2ram-auto-sync
        msg_ok "$(translate "Auto-sync enabled when /var/log exceeds 80% of") $LOG2RAM_SIZE"
    else
        rm -f /usr/local/bin/log2ram-check.sh /etc/cron.d/log2ram-auto-sync 2>/dev/null || true
        msg_info2 "$(translate "Auto-sync was not enabled")"
    fi

    # --- Ajuste de systemd-journald proporcional al tamaño de Log2RAM ---
    msg_info "$(translate "Adjusting systemd-journald limits to match Log2RAM size...")"

    if [[ -f /etc/systemd/journald.conf ]]; then
        cp -n /etc/systemd/journald.conf "/etc/systemd/journald.conf.bak.$(date +%Y%m%d-%H%M%S)"
        BAK_OK=$?
    fi

    SIZE_MB=$(echo "$LOG2RAM_SIZE" | tr -dc '0-9')
    # Repartos: 55% persistente / 10% libre / 25% runtime   (pisos mínimos)
    USE_MB=$(( SIZE_MB * 55 / 100 ))
    KEEP_MB=$(( SIZE_MB * 10 / 100 ))
    RUNTIME_MB=$(( SIZE_MB * 25 / 100 ))
    [ "$USE_MB"     -lt 80 ] && USE_MB=80
    [ "$RUNTIME_MB" -lt 32 ] && RUNTIME_MB=32
    [ "$KEEP_MB"    -lt 8  ] && KEEP_MB=8

    # Reescribir bloque [Journal] de forma segura
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

    systemctl restart systemd-journald >/dev/null 2>&1 || true
    [[ "$BAK_OK" = "0" ]] && msg_ok "$(translate "Backup created:") /etc/systemd/journald.conf.bak.$(date +%Y%m%d-%H%M%S)"
    msg_ok "$(translate "Journald configuration adjusted to") ${USE_MB}M (Log2RAM ${LOG2RAM_SIZE})"

    mkdir -p /var/log/pveproxy
    chown -R www-data:www-data /var/log/pveproxy
    chmod 0750 /var/log/pveproxy

    mkdir -p /var/log.hdd/pveproxy
    chown -R www-data:www-data /var/log.hdd/pveproxy
    chmod 0750 /var/log.hdd/pveproxy

    systemctl restart cron >/dev/null 2>&1 || true
    systemctl restart log2ram >/dev/null 2>&1 || true


    log2ram write >/dev/null 2>&1 || true
    log2ram clean >/dev/null 2>&1 || true
    systemctl restart rsyslog >/dev/null 2>&1 || true

    msg_success "$(translate "Log2RAM installation and configuration completed successfully.")"
    register_tool "log2ram" true "$FUNC_VERSION"
}










# ==========================================================




setup_persistent_network() {
    local FUNC_VERSION="1.0"
    # description: Pin NIC names to MAC addresses via systemd .link files so kernel updates don't shuffle interface names.
    local LINK_DIR="/etc/systemd/network"
    local BACKUP_DIR="/etc/systemd/network/backup-$(date +%Y%m%d-%H%M%S)"
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

    msg_info "$(translate "Setting up persistent network interfaces")"
    sleep 2

    # Detect legacy `/etc/network/interfaces` setups that depend on the
    # default udev naming. If the file references `allow-hotplug` rules
    # or uses physical interface names directly, the .link rules below
    # could rename interfaces and break network on reboot. Warn loudly so
    # the user can review before continuing. Audit Tier 6 —
    # `setup_persistent_network` no detecta conflicto con legacy.
    if [[ -f /etc/network/interfaces ]]; then
        if grep -qE '^[[:space:]]*allow-hotplug[[:space:]]' /etc/network/interfaces 2>/dev/null; then
            msg_warn "$(translate '/etc/network/interfaces uses allow-hotplug. Renaming interfaces via systemd .link can break that flow — review the file after reboot.')"
        fi
    fi

    mkdir -p "$LINK_DIR"


    if ls "$LINK_DIR"/*.link >/dev/null 2>&1; then
        mkdir -p "$BACKUP_DIR"
        cp "$LINK_DIR"/*.link "$BACKUP_DIR"/ 2>/dev/null || true
    fi
    
    # Process physical interfaces
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
        # In PVE9, systemd-networkd is the native network backend and udev processes
        # .link files directly. Reloading udev rules makes the new .link files effective
        # immediately for any interface added later (hotplug, new NICs) without waiting
        # for a full reboot. On PVE8 (ifupdown2), names are resolved at boot anyway.
        if [[ "$pve_version" -ge 9 ]]; then
            udevadm control --reload-rules 2>/dev/null || true
            msg_ok "$(translate "PVE9: udev rules reloaded — new interfaces will get correct names without reboot")"
        fi
        msg_ok "$(translate "Changes will apply after reboot.")"
    else
        msg_warn "$(translate "No physical interfaces found")"
    fi
    msg_success "$(translate "Setting up persistent network interfaces successfully.")"
    register_tool "persistent_network" true "$FUNC_VERSION"
    NECESSARY_REBOOT=1
}







# ==========================================================






# ==========================================================
#        Auxiliary help functions
# ==========================================================











# ==========================================================








install_system_utils() {
    msg_info2 "$(translate "Installing system utilities...")"

    # Build checklist from global PROXMENUX_UTILS array
    local checklist_items=()
    for util_entry in "${PROXMENUX_UTILS[@]}"; do
        IFS=':' read -r pkg cmd desc <<< "$util_entry"
        checklist_items+=("$pkg" "$(translate "$desc")" "OFF")
    done

    exec 3>&1
    local selected
    selected=$(dialog --clear --backtitle "ProxMenux" \
        --title "$(translate "Select utilities to install")" \
        --checklist "$(translate "Use SPACE to select, ENTER to confirm")" \
        25 80 20 "${checklist_items[@]}" 2>&1 1>&3)
    local dialog_exit=$?
    exec 3>&-

    if [[ $dialog_exit -ne 0 || -z "$selected" ]]; then
        msg_warn "$(translate "No utilities selected")"
        return 0
    fi

    clear
    show_proxmenux_logo

    if ! ensure_repositories; then
        msg_error "$(translate "Failed to configure repositories. Installation aborted.")"
        return 1
    fi

    local success=0 failed=0 warning=0
    local selected_array
    IFS=' ' read -ra selected_array <<< "$selected"

    for util in "${selected_array[@]}"; do
        util=$(echo "$util" | tr -d '"')
        local pkg_cmd="$util" pkg_desc="$util"
        for util_entry in "${PROXMENUX_UTILS[@]}"; do
            IFS=':' read -r epkg ecmd edesc <<< "$util_entry"
            if [[ "$epkg" == "$util" ]]; then
                pkg_cmd="$ecmd"
                pkg_desc="$edesc"
                break
            fi
        done
        install_single_package "$util" "$pkg_cmd" "$pkg_desc"
        case $? in
            0) success=$((success + 1)) ;;
            1) failed=$((failed + 1)) ;;
            2) warning=$((warning + 1)) ;;
        esac
    done

    hash -r 2>/dev/null
    echo
    msg_info2 "$(translate "Installation summary"):"
    [[ $success -gt 0 ]] && msg_ok "$(translate "Successful"): $success"
    [[ $warning -gt 0 ]] && msg_warn "$(translate "With warnings"): $warning"
    [[ $failed -gt 0 ]] && msg_error "$(translate "Failed"): $failed"
    msg_success "$(translate "Utilities installation completed")"
}




# Main menu function
main_menu() {
  local HEADER
  if [[ "$LANGUAGE" == "es" ]]; then
    HEADER="Seleccione las opciones a configurar:\n\n           Descripción                                  | Categoría"
  else
    HEADER="$(translate "Choose options to configure:")\n\n           Description                                | Category"
  fi

  declare -A category_order=(
    ["Basic Settings"]=1 ["System"]=2 ["Hardware"]=3 ["Virtualization"]=4
    ["Network"]=5 ["Storage"]=6 ["Security"]=7 ["Customization"]=8
    ["Monitoring"]=9 ["Performance"]=10 ["Optional"]=11
  )

  local options=(
    "Basic Settings|Update and upgrade system|APTUPGRADE"
    "Basic Settings|Synchronize time automatically|TIMESYNC"
    "Basic Settings|Skip downloading additional languages|NOAPTLANG"
    "Basic Settings|Install common system utilities|UTILS"
    "System|Optimize journald|JOURNALD"
    "System|Optimize logrotate|LOGROTATE"
    "System|Increase various system limits|LIMITS"
    # Entropy (haveged) removed — modern kernels 5.6+ have built-in entropy generation
    "System|Optimize Memory|MEMORYFIXES"
    "System|Enable fast reboots|KEXEC"
    "System|Enable restart on kernel panic|KERNELPANIC"
    "Optional|Apply AMD CPU fixes|AMDFIXES"
    "Virtualization|Install relevant guest agent|GUESTAGENT"
    "Virtualization|Enable VFIO IOMMU support|VFIO_IOMMU"
    "Network|Force APT to use IPv4|APTIPV4"
    "Network|Apply network optimizations|NET"
    "Network|Install Open vSwitch|OPENVSWITCH"
    "Network|Enable TCP BBR/Fast Open control|TCPFASTOPEN"
    "Network|Interface Names (persistent)|PERSISNET"
    "Storage|Optimize ZFS ARC size|ZFSARC"
    "Storage|Install ZFS auto-snapshot|ZFSAUTOSNAPSHOT"
    "Storage|Increase vzdump backup speed|VZDUMP"
    "Security|Disable portmapper/rpcbind|DISABLERPC"
    "Customization|Customize bashrc|BASHRC"
    "Customization|Set up custom MOTD banner|MOTD"
    "Customization|Remove subscription banner|NOSUBBANNER"
    "Monitoring|Install OVH Real Time Monitoring|OVHRTM"
    "Performance|Use pigz for faster gzip compression|PIGZ"
    "Optional|Install and configure Fastfetch|FASTFETCH"
    "Optional|Update Proxmox VE Appliance Manager|PVEAM"
    "Optional|Add latest Ceph support|CEPH"
    "Optional|Enable High Availability services|ENABLE_HA"
    "Optional|Install Figurine|FIGURINE"
    "Optional|Install and configure Log2RAM|LOG2RAM"
  )

  IFS=$'\n' sorted_options=($(for option in "${options[@]}"; do
    IFS='|' read -r category description function_name <<< "$option"
    printf "%d|%s|%s|%s\n" "${category_order[$category]:-999}" "$category" "$description" "$function_name"
  done | sort -n | cut -d'|' -f2-))
  unset IFS

  local max_desc_length=0
  local temp_descriptions=()
  
  for option in "${sorted_options[@]}"; do
    IFS='|' read -r category description function_name <<< "$option"
    local desc_translated="$(translate "$description")"
    temp_descriptions+=("$desc_translated")
    
    local desc_length=${#desc_translated}
    if [ $desc_length -gt $max_desc_length ]; then
      max_desc_length=$desc_length
    fi
  done
  
  if [ $max_desc_length -gt 50 ]; then
    max_desc_length=50
  fi

  local checklist_items=()
  local i=1
  local desc_index=0
  local previous_category=""

  for option in "${sorted_options[@]}"; do
    IFS='|' read -r category description function_name <<< "$option"
    

    if [[ "$category" != "$previous_category" && "$category" == "Optional" && -n "$previous_category" ]]; then
      checklist_items+=("" "==============================================================" "")
    fi
    
    local desc_translated="${temp_descriptions[$desc_index]}"
    desc_index=$((desc_index + 1))
    

    if [ ${#desc_translated} -gt $max_desc_length ]; then
      desc_translated="${desc_translated:0:$((max_desc_length-3))}..."
    fi
    

    local spaces_needed=$((max_desc_length - ${#desc_translated}))
    local padding=""
    for ((j=0; j<spaces_needed; j++)); do
      padding+=" "
    done
    
    local line="${desc_translated}${padding}      | ${category}"

    checklist_items+=("$i" "$line" "off")
    i=$((i + 1))
    previous_category="$category"
  done

  exec 3>&1
  selected_indices=$(dialog --clear \
    --backtitle "ProxMenux" \
    --title "$(translate "Post-Installation Options")" \
    --checklist "$HEADER" 22 80 15 \
    "${checklist_items[@]}" \
    2>&1 1>&3)

  local dialog_exit=$?
  exec 3>&-

  if [[ $dialog_exit -ne 0 || -z "$selected_indices" ]]; then
    exit 0
  fi




declare -A selected_functions
read -ra indices_array <<< "$selected_indices"

for index in "${indices_array[@]}"; do
  if [[ -z "$index" ]] || ! [[ "$index" =~ ^[0-9]+$ ]]; then
    continue
  fi
  

  local item_index=$(( (index - 1) * 3 + 1 ))
  if [[ $item_index -lt ${#checklist_items[@]} ]]; then
    local selected_line="${checklist_items[$item_index]}"
    if [[ "$selected_line" =~ ^.*(\-\-\-|===+).*$ ]]; then
       return 1
    fi
  fi
  

  option=${sorted_options[$((index - 1))]}
  IFS='|' read -r _ description function_name <<< "$option"
  selected_functions[$function_name]=1
  [[ "$function_name" == "FASTFETCH" ]] && selected_functions[MOTD]=0
done




  
  clear
  show_proxmenux_logo
  msg_title "$SCRIPT_TITLE"

  for option in "${sorted_options[@]}"; do
    IFS='|' read -r _ description function_name <<< "$option"
    if [[ ${selected_functions[$function_name]} -eq 1 ]]; then
      case $function_name in
        APTUPGRADE) apt_upgrade ;;
        TIMESYNC) configure_time_sync ;;
        NOAPTLANG) skip_apt_languages ;;
        UTILS) install_system_utils ;;
        JOURNALD) optimize_journald ;;
        LOGROTATE) optimize_logrotate ;;
        LIMITS) increase_system_limits ;;
        # ENTROPY removed — modern kernels 5.6+ have built-in entropy
        MEMORYFIXES) optimize_memory_settings ;;
        KEXEC) enable_kexec ;;
        KERNELPANIC) configure_kernel_panic ;;
        AMDFIXES) apply_amd_fixes ;;
        GUESTAGENT) install_guest_agent ;;
        VFIO_IOMMU) enable_vfio_iommu ;;
        APTIPV4) force_apt_ipv4 ;;
        NET) apply_network_optimizations ;;
        OPENVSWITCH) install_openvswitch ;;
        TCPFASTOPEN) enable_tcp_fast_open ;;
        ZFSARC) optimize_zfs_arc ;;
        ZFSAUTOSNAPSHOT) install_zfs_auto_snapshot ;;
        VZDUMP) optimize_vzdump ;;
        DISABLERPC) disable_rpc ;;
        BASHRC) customize_bashrc ;;
        MOTD) setup_motd ;;
        NOSUBBANNER) remove_subscription_banner ;;
        OVHRTM) install_ovh_rtm ;;
        PIGZ) configure_pigz ;;
        FASTFETCH) configure_fastfetch ;;
        CEPH) install_ceph ;;
        ENABLE_HA) enable_ha ;;
        FIGURINE) configure_figurine ;;
        LOG2RAM) configure_log2ram ;;
        PVEAM) update_pve_appliance_manager ;;
        PERSISNET) setup_persistent_network ;;
        *) echo "Option $function_name not implemented yet" ;;
      esac
    fi
  done

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

  msg_success "$(translate "All changes applied. No reboot required.")"
  msg_success "$(translate "Press Enter to return to menu...")"
  read -r
  clear
}



# Sprint 12B: only run the interactive menu when this script is invoked
# directly. When sourced from another script (e.g. the post-install
# update wrapper that re-runs a single function), don't trigger the
# extremeshok warning or the main menu.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    check_extremeshok_warning
    main_menu
fi
