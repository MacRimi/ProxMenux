#!/bin/bash

# ==========================================================
# ProxMenux - Customizable script settings for Proxmox post-installation
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.3
# Last Updated: 30/06/2025
# ==========================================================
# Description:
# This script automates post-installation configurations and optimizations
# for Proxmox Virtual Environment (VE). It allows for a variety of system
# customizations, including kernel optimizations, memory management, network 
# tweaks, and virtualization environment adjustments. The script facilitates
# easy installation of useful tools and security enhancements, including 
# fail2ban, ZFS auto-snapshot, and more.
#
# This script is based on the work of Adrian Jon Kriel from eXtremeSHOK.com,
# and it was originally published as a post-installation script for Proxmox under the 
# BSD License.
#
# Copyright (c) Adrian Jon Kriel :: admin@extremeshok.com
# Script updates can be found at: https://github.com/extremeshok/xshok-proxmox
#
# License: BSD (Berkeley Software Distribution)
#
# Additionally, this script incorporates elements from the 
# Proxmox VE Post Install script from Proxmox VE Helper-Scripts.
#
# Copyright (c) Proxmox VE Helper-Scripts Community
# Script updates can be found at: https://github.com/community-scripts/ProxmoxVE
#
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
#
# Key features:
# - Configures system memory and kernel settings for better performance.
# - Enables IOMMU and VFIO for PCI passthrough and virtualization optimizations.
# - Installs essential tools such as kernel headers, system utilities, and networking tools.
# - Optimizes journald, achievement, and other system services for better efficiency.
# - Enables guest agents for virtualization platforms such as KVM, VMware, and VirtualBox.
# - Updates the system, adds correct repositories, and optimizes system features such as memory, network settings, and more.
# - Provides a wide range of additional options for customization and optimization.
# - Offers interactive selection of features using an easy-to-use menu-driven interface.
# - And many more...
#
# ==========================================================


# Configuration
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
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
RAM_SIZE_GB=$(( $(vmstat -s | grep -i "total memory" | xargs | cut -d" " -f 1) / 1024 / 1000))
NECESSARY_REBOOT=0
SCRIPT_TITLE="Customizable post-installation optimization script"

TOOLS_JSON="/usr/local/share/proxmenux/installed_tools.json"

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


enable_kexec() {
    msg_info2 "$(translate "Configuring kexec for quick reboots...")"
    NECESSARY_REBOOT=1 
    register_tool "kexec" true

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
    register_tool "kexec" true
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

        bash <(curl -fsSL "$REPO_URL/scripts/global/update-pve.sh")
    else

        bash <(curl -fsSL "$REPO_URL/scripts/global/update-pve8.sh")
    fi

    
    msg_success "$(translate "Proxmox repository configuration completed")"
}




# ==========================================================





optimize_journald() {
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
# Disable rate limits
RateLimitInterval=0
RateLimitIntervalSec=0
RateLimitBurst=0
# Disable Journald forwarding to syslog
ForwardToSyslog=no
# Journald forwarding to wall /var/log/kern.log
ForwardToWall=yes
# Disable signing of the logs, save cpu resources
Seal=no
Compress=yes
# Fix the log size
SystemMaxUse=64M
RuntimeMaxUse=60M
# Optimize the logging and speed up tasks
MaxLevelStore=warning
MaxLevelSyslog=warning
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
}





# ==========================================================





install_kernel_headers() {
    msg_info2 "$(translate "Installing kernel headers")"
    NECESSARY_REBOOT=1 

    # Get the current kernel version
    local kernel_version=$(uname -r)
    local headers_package="linux-headers-${kernel_version}"

    # Check if headers are already installed
    if dpkg -s "$headers_package" >/dev/null 2>&1; then
        msg_ok "$(translate "Kernel headers are already installed")"
    else
        msg_info "$(translate "Installing kernel headers...")"
        if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install "$headers_package" > /dev/null 2>&1; then
        msg_ok "$(translate "Kernel headers installed successfully")"
        else
        msg_error "$(translate "Failed to install kernel headers")"
            return 1
        fi
    fi

    msg_success "$(translate "Kernel headers installation process completed")"
}



# ==========================================================



configure_kernel_panic() {
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
    msg_success "$(translate "Kernel panic behavior configuration completed")"
}




# ==========================================================




increase_system_limits() {
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
            echo "DefaultLimitNOFILE=256000" >> "$file"
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
    if ! grep -q "ulimit -n 256000" /root/.profile; then
        echo "ulimit -n 256000" >> /root/.profile
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
fs.nr_open = 12000000
fs.file-max = 9223372036854775807
fs.aio-max-nr = 1048576"

    msg_ok "$(translate "Max FS open files configuration created successfully")"
    msg_success "$(translate "System limits increase completed.")"
}



# ==========================================================




skip_apt_languages_() {
    msg_info2 "$(translate "Configuring APT to skip downloading additional languages")"

    local config_file="/etc/apt/apt.conf.d/99-disable-translations"
    local config_content="Acquire::Languages \"none\";"

    msg_info "$(translate "Setting APT language configuration...")"

    if [ -f "$config_file" ] && grep -q "$config_content" "$config_file"; then
        msg_ok "$(translate "APT language configuration updated")"
    else
        echo -e "$config_content\n" > "$config_file"
        msg_ok "$(translate "APT language configuration updated")"
    fi

    msg_success "$(translate "APT configured to skip downloading additional languages")"
}




skip_apt_languages() {
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

    msg_success "$(translate "APT configured to skip downloading additional languages")"
}






# ==========================================================




configure_time_sync() {
    msg_info2 "$(translate "Configuring system time settings...")"

    # Set timezone
    #    msg_info "$(translate "Attempting to set timezone automatically based on IP address...")"

    # Get public IP address
    this_ip=$(dig +short myip.opendns.com @resolver1.opendns.com)
    if [ -z "$this_ip" ]; then
        msg_warn "$(translate "Failed to obtain public IP address")"
        timezone="UTC"
    else
        # Get timezone based on IP
        timezone=$(curl -s "https://ipapi.co/${this_ip}/timezone")
        if [ -z "$timezone" ]; then
            msg_warn "$(translate "Failed to determine timezone from IP address")"
            timezone="UTC"
        else
            msg_ok "$(translate "Found timezone $timezone for IP $this_ip")"
        fi
    fi

    # Set the timezone
    if timedatectl set-timezone "$timezone"; then
        msg_ok "$(translate "Timezone set to $timezone")"
    else
        msg_error "$(translate "Failed to set timezone to $timezone")"
    fi

    # Configure time synchronization
    msg_info "$(translate "Enabling automatic time synchronization...")"
    if timedatectl set-ntp true; then
        msg_ok "$(translate "Automatic time synchronization enabled")"
    else
        msg_error "$(translate "Failed to enable automatic time synchronization")"
    fi

    msg_success "$(translate "Time settings configuration completed")"
}




# ==========================================================





install_system_utils() {
    command_exists() {
        command -v "$1" >/dev/null 2>&1
    }

ensure_repositories() {
    local sources_file="/etc/apt/sources.list"
    local need_update=false


    if [[ ! -f "$sources_file" ]]; then
        msg_warn "$(translate "sources.list not found, creating default Debian repository...")"
        cat > "$sources_file" << EOF
# Default Debian ${OS_CODENAME} repository
deb http://deb.debian.org/debian ${OS_CODENAME} main contrib non-free non-free-firmware
EOF
        need_update=true
    else

        if ! grep -q "deb.*${OS_CODENAME}.*main" "$sources_file"; then
            echo "deb http://deb.debian.org/debian ${OS_CODENAME} main contrib non-free non-free-firmware" >> "$sources_file"
            need_update=true
        fi
    fi


    if [[ "$need_update" == true ]] || ! apt list --installed >/dev/null 2>&1; then
        msg_info "$(translate "Updating APT package lists...")"
        apt-get update -o Acquire::AllowInsecureRepositories=true >/dev/null 2>&1
    fi

    return 0
}


    install_single_package() {
        local package="$1"
        local command_name="${2:-$package}"
        local description="$3"
        
        msg_info "$(translate "Installing") $package ($description)..."
        local install_success=false
        
        if apt install -y "$package" >/dev/null 2>&1; then
            install_success=true
        fi
            
        cleanup
        
        if [ "$install_success" = true ]; then
            hash -r 2>/dev/null
            sleep 1
            if command_exists "$command_name"; then
                msg_ok "$package $(translate "installed correctly and available")"
                return 0
            else
                msg_warn "$package $(translate "installed but command not immediately available")"
                msg_info2 "$(translate "May need to restart terminal")"
                return 2
            fi
        else
            msg_error "$(translate "Error installing") $package"
            return 1
        fi
    }

    show_utilities_selection() {
        local utilities=(
            "axel" "$(translate "Download accelerator")" "OFF"
            "dos2unix" "$(translate "Convert DOS/Unix text files")" "OFF"
            "grc" "$(translate "Generic log/command colorizer")" "OFF"
            "htop" "$(translate "Interactive process viewer")" "OFF"
            "btop" "$(translate "Modern resource monitor")" "OFF"
            "iftop" "$(translate "Real-time network usage")" "OFF"
            "iotop" "$(translate "Monitor disk I/O usage")" "OFF"
            "iperf3" "$(translate "Network performance testing")" "OFF"
            "ipset" "$(translate "Manage IP sets")" "OFF"
            "iptraf-ng" "$(translate "Network monitoring tool")" "OFF"
            "mlocate" "$(translate "Locate files quickly")" "OFF"
            "msr-tools" "$(translate "Access CPU MSRs")" "OFF"
            "net-tools" "$(translate "Legacy networking tools")" "OFF"
            "sshpass" "$(translate "Non-interactive SSH login")" "OFF"
            "tmux" "$(translate "Terminal multiplexer")" "OFF"
            "unzip" "$(translate "Extract ZIP files")" "OFF"
            "zip" "$(translate "Create ZIP files")" "OFF"
            "libguestfs-tools" "$(translate "VM disk utilities")" "OFF"
            "aria2" "$(translate "Multi-source downloader")" "OFF"
            "cabextract" "$(translate "Extract CAB files")" "OFF"
            "wimtools" "$(translate "Manage WIM images")" "OFF"
            "genisoimage" "$(translate "Create ISO images")" "OFF"
            "chntpw" "$(translate "Edit Windows registry/passwords")" "OFF"
        )
        
        local selected
        selected=$(dialog --clear --backtitle "ProxMenu - $(translate "System Utilities")" \
            --title "$(translate "Select utilities to install")" \
            --checklist "$(translate "Use SPACE to select/deselect, ENTER to confirm")" \
            20 70 12 "${utilities[@]}" 2>&1 >/dev/tty)
        
        echo "$selected"
    }

    install_selected_utilities() {
        local selected="$1"
        
        if [ -z "$selected" ]; then
            dialog --clear --backtitle "ProxMenu" \
                --title "$(translate "No Selection")" \
                --msgbox "$(translate "No utilities were selected")" 8 40
            return
        fi
        
        clear
        show_proxmenux_logo
        msg_title "$SCRIPT_TITLE"
        msg_info2 "$(translate "Installing selected utilities")"
        

        if ! ensure_repositories; then
            msg_error "$(translate "Failed to configure repositories. Installation aborted.")"
            return 1
        fi
        
        local failed=0
        local success=0
        local warning=0
        local selected_array
        IFS=' ' read -ra selected_array <<< "$selected"
        
        declare -A package_to_command=(
            ["mlocate"]="locate"
            ["msr-tools"]="rdmsr"
            ["net-tools"]="netstat"
            ["libguestfs-tools"]="virt-filesystems"
            ["aria2"]="aria2c"
            ["wimtools"]="wimlib-imagex"
        )
        
        for util in "${selected_array[@]}"; do
            util=$(echo "$util" | tr -d '"')
            local verify_command="${package_to_command[$util]:-$util}"
            install_single_package "$util" "$verify_command" "$util"
            local install_result=$?
            
            case $install_result in
                0) success=$((success + 1)) ;;
                1) failed=$((failed + 1)) ;;
                2) warning=$((warning + 1)) ;;
            esac
            sleep 2
        done
        
        if [ -f ~/.bashrc ]; then
            source ~/.bashrc >/dev/null 2>&1
        fi
        
        hash -r 2>/dev/null
        echo
        msg_info2 "$(translate "Installation summary"):"
        msg_ok "$(translate "Successful"): $success"
        if [ $warning -gt 0 ]; then
            msg_warn "$(translate "Warnings"): $warning"
        fi
        if [ $failed -gt 0 ]; then
            msg_error "$(translate "Failed"): $failed"
        fi
        msg_success "$(translate "Common system utilities installation completed")"
    }


    local selected_utilities
    selected_utilities=$(show_utilities_selection)
    if [ -n "$selected_utilities" ]; then
        install_selected_utilities "$selected_utilities"
    fi
}






# ==========================================================




configure_entropy() {
    msg_info2 "$(translate "Configuring entropy generation to prevent slowdowns...")"

    # Install haveged
    msg_info "$(translate "Installing haveged...")"
    /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install haveged > /dev/null 2>&1
    msg_ok "$(translate "haveged installed successfully")"

    # Configure haveged
    msg_info "$(translate "Configuring haveged...")"
    cat <<EOF > /etc/default/haveged
#   -w sets low entropy watermark (in bits)
DAEMON_ARGS="-w 1024"
EOF

    # Reload systemd daemon
    systemctl daemon-reload > /dev/null 2>&1

    # Enable haveged service
    systemctl enable haveged > /dev/null 2>&1
    msg_ok "$(translate "haveged service enabled successfully")"

    msg_success "$(translate "Entropy generation configuration completed")"
}





# ==========================================================




apply_amd_fixes() {
    msg_info2 "$(translate "Detecting AMD CPU and applying fixes if necessary...")"
    NECESSARY_REBOOT=1

    local cpu_model=$(grep -i -m 1 "model name" /proc/cpuinfo)
    if echo "$cpu_model" | grep -qi "EPYC"; then
        msg_info "$(translate "AMD EPYC CPU detected")"
    elif echo "$cpu_model" | grep -qi "Ryzen"; then
        msg_info "$(translate "AMD Ryzen CPU detected")"
    else
        msg_ok "$(translate "No AMD CPU detected. Skipping AMD fixes.")"
        return
    fi

    msg_info "$(translate "Applying AMD-specific fixes...")"

    # Apply kernel fix for random crashing and instability
    local grub_file="/etc/default/grub"
    if ! grep -q "idle=nomwait" "$grub_file"; then
        msg_info "$(translate "Setting kernel parameter: idle=nomwait")"
        if sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="idle=nomwait /g' "$grub_file"; then
            msg_ok "$(translate "Kernel parameter set successfully")"
            if update-grub > /dev/null 2>&1; then
                msg_ok "$(translate "GRUB configuration updated")"
            else
                msg_warn "$(translate "Failed to update GRUB configuration")"
            fi
        else
            msg_warn "$(translate "Failed to set kernel parameter")"
        fi
    else
        msg_info "$(translate "Kernel parameter 'idle=nomwait' already set")"
    fi

    # Add MSR ignore to fix Windows guest on EPYC/Ryzen host
    local kvm_conf="/etc/modprobe.d/kvm.conf"
    msg_info "$(translate "Configuring KVM to ignore MSRs...")"
    if ! grep -q "options kvm ignore_msrs=Y" "$kvm_conf"; then
        echo "options kvm ignore_msrs=Y" >> "$kvm_conf"
        msg_ok "$(translate "KVM ignore_msrs option added")"
    else
        msg_info "$(translate "KVM ignore_msrs option already set")"
    fi
    if ! grep -q "options kvm report_ignored_msrs=N" "$kvm_conf"; then
        echo "options kvm report_ignored_msrs=N" >> "$kvm_conf"
        msg_ok "$(translate "KVM report_ignored_msrs option added")"
    else
        msg_info "$(translate "KVM report_ignored_msrs option already set")"
    fi

    # Install the latest Proxmox VE kernel
    msg_info "$(translate "Checking for Proxmox VE kernel updates...")"
    local current_kernel=$(uname -r | cut -d'-' -f1-2)
    local latest_kernel=$(apt-cache search pve-kernel | grep "^pve-kernel-${current_kernel}" | sort -V | tail -n1 | cut -d' ' -f1)
    
    if [ "$latest_kernel" != "pve-kernel-$current_kernel" ]; then
        msg_info "$(translate "Installing the latest Proxmox VE kernel...")"
        if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install "$latest_kernel" > /dev/null 2>&1; then
            msg_ok "$(translate "Latest Proxmox VE kernel installed successfully")"
        else
            msg_warn "$(translate "Failed to install the latest Proxmox VE kernel")"
        fi
    else
        msg_ok "$(translate "The latest Proxmox VE kernel is already installed")"
    fi

    msg_success "$(translate "AMD CPU fixes applied successfully")"
}





# ==========================================================




force_apt_ipv4() {
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

    msg_success "$(translate "APT IPv4 configuration completed")"
}





# ==========================================================





apply_network_optimizations() {
    msg_info2 "$(translate "Optimizing network settings...")"
    NECESSARY_REBOOT=1

    local sysctl_conf="/etc/sysctl.d/99-network.conf"
    local interfaces_file="/etc/network/interfaces"

    msg_info "$(translate "Applying network optimizations...")"

    # Update sysctl configuration
    cat <<EOF > "$sysctl_conf"
net.core.netdev_max_backlog=8192
net.core.optmem_max=8192
net.core.rmem_max=16777216
net.core.somaxconn=8151
net.core.wmem_max=16777216
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.all.log_martians = 0
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.conf.default.log_martians = 0
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.default.secure_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1
net.ipv4.ip_local_port_range=1024 65535
net.ipv4.tcp_base_mss = 1024
net.ipv4.tcp_challenge_ack_limit = 999999999
net.ipv4.tcp_fin_timeout=10
net.ipv4.tcp_keepalive_intvl=30
net.ipv4.tcp_keepalive_probes=3
net.ipv4.tcp_keepalive_time=240
net.ipv4.tcp_limit_output_bytes=65536
net.ipv4.tcp_max_syn_backlog=8192
net.ipv4.tcp_max_tw_buckets = 1440000
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_rfc1337=1
net.ipv4.tcp_rmem=8192 87380 16777216
net.ipv4.tcp_sack=1
net.ipv4.tcp_slow_start_after_idle=0
net.ipv4.tcp_syn_retries=3
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_tw_recycle = 0
net.ipv4.tcp_tw_reuse = 0
net.ipv4.tcp_wmem=8192 65536 16777216
net.netfilter.nf_conntrack_generic_timeout = 60
net.netfilter.nf_conntrack_helper=0
net.netfilter.nf_conntrack_max = 524288
net.netfilter.nf_conntrack_tcp_timeout_established = 28800
net.unix.max_dgram_qlen = 4096
EOF

    sysctl --system > /dev/null 2>&1

    # Ensure /etc/network/interfaces includes the interfaces.d directory
    if ! grep -q 'source /etc/network/interfaces.d/*' "$interfaces_file"; then
        echo "source /etc/network/interfaces.d/*" >> "$interfaces_file"
    fi

    msg_ok "$(translate "Network optimizations applied")"
    msg_success "$(translate "Network optimization completed")"
}





# ==========================================================





install_openvswitch() {
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
    else
        msg_warn "$(translate "OpenVSwitch installation could not be verified")"
    fi

}





# ==========================================================




enable_tcp_fast_open() {
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
}




# ==========================================================







install_ceph() {
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
    

}







# ==========================================================





optimize_zfs_arc() {
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
}




# ==========================================================





install_zfs_auto_snapshot() {
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
}





# ==========================================================





install_fail2ban() {
    msg_info2 "$(translate "Installing and configuring Fail2Ban to protect the web interface...")"


#    if dpkg -l | grep -qw fail2ban; then
#        msg_info "$(translate "Removing existing Fail2Ban installation...")"
#        apt-get remove --purge -y fail2ban >/dev/null 2>&1
#        rm -rf /etc/fail2ban /var/lib/fail2ban /var/run/fail2ban
#        msg_ok "$(translate "Fail2Ban removed successfully")"
#    else
#        msg_ok "$(translate "Fail2Ban was not installed")"
#    fi

 
    msg_info "$(translate "Installing Fail2Ban...")"
    apt-get update >/dev/null 2>&1 && apt-get install -y fail2ban >/dev/null 2>&1
    if [[ $? -eq 0 ]]; then
        msg_ok "$(translate "Fail2Ban installed successfully")"
    else
        msg_error "$(translate "Failed to install Fail2Ban")"
        return 1
    fi

   
    mkdir -p /etc/fail2ban/jail.d /etc/fail2ban/filter.d

   
    msg_info "$(translate "Configuring Proxmox filter...")"
    cat > /etc/fail2ban/filter.d/proxmox.conf << EOF
[Definition]
failregex = pvedaemon\[.*authentication failure; rhost=<HOST> user=.* msg=.*
ignoreregex =
EOF
    msg_ok "$(translate "Proxmox filter configured")"

  
    msg_info "$(translate "Configuring Proxmox jail...")"
    cat > /etc/fail2ban/jail.d/proxmox.conf << EOF
[proxmox]
enabled = true
port = https,http,8006,8007
filter = proxmox
logpath = /var/log/daemon.log
maxretry = 3
bantime = 3600
findtime = 600
EOF
    msg_ok "$(translate "Proxmox jail configured")"

  
    msg_info "$(translate "Configuring general Fail2Ban settings...")"
    cat > /etc/fail2ban/jail.local << EOF
[DEFAULT]
ignoreip = 127.0.0.1
bantime = 86400
maxretry = 2
findtime = 1800

[ssh-iptables]
enabled = true
filter = sshd
action = iptables[name=SSH, port=ssh, protocol=tcp]
logpath = /var/log/auth.log
maxretry = 2
findtime = 3600
bantime = 32400
EOF
    msg_ok "$(translate "General Fail2Ban settings configured")"

    
    msg_info "$(translate "Stopping Fail2Ban service...")"
    systemctl stop fail2ban >/dev/null 2>&1
    msg_ok "$(translate "Fail2Ban service stopped")"

   
    msg_info "$(translate "Ensuring authentication logs exist...")"
    touch /var/log/auth.log /var/log/daemon.log
    chown root:adm /var/log/auth.log /var/log/daemon.log
    chmod 640 /var/log/auth.log /var/log/daemon.log
    msg_ok "$(translate "Authentication logs verified")"

    
    if [[ ! -f /var/log/auth.log && -f /var/log/secure ]]; then
        msg_warn "$(translate "Using /var/log/secure instead of /var/log/auth.log")"
        sed -i 's|logpath = /var/log/auth.log|logpath = /var/log/secure|' /etc/fail2ban/jail.local
    fi

   
    msg_info "$(translate "Ensuring Fail2Ban runtime directory exists...")"
    mkdir -p /var/run/fail2ban
    chown root:root /var/run/fail2ban
    chmod 755 /var/run/fail2ban
    msg_ok "$(translate "Fail2Ban runtime directory verified")"

    
    msg_info "$(translate "Removing old Fail2Ban database (if exists)...")"
    rm -f /var/lib/fail2ban/fail2ban.sqlite3
    msg_ok "$(translate "Fail2Ban database reset")"

  
    msg_info "$(translate "Reloading systemd and restarting Fail2Ban...")"
    systemctl daemon-reload
    systemctl enable fail2ban >/dev/null 2>&1
    systemctl restart fail2ban >/dev/null 2>&1
    msg_ok "$(translate "Fail2Ban service restarted")"

    
    sleep 3

   
    msg_info "$(translate "Checking Fail2Ban service status...")"
    if systemctl is-active --quiet fail2ban; then
        msg_ok "$(translate "Fail2Ban is running correctly")"
    else
        msg_error "$(translate "Fail2Ban is NOT running! Checking logs...")"
        journalctl -u fail2ban --no-pager -n 20
       
    fi


    msg_info "$(translate "Checking Fail2Ban socket...")"
    if [ -S /var/run/fail2ban/fail2ban.sock ]; then
        msg_ok "$(translate "Fail2Ban socket exists!")"
    else
        msg_warn "$(translate "Warning: Fail2Ban socket does not exist!")"
    fi


    msg_info "$(translate "Testing fail2ban-client...")"
    if fail2ban-client ping >/dev/null 2>&1; then
        msg_ok "$(translate "fail2ban-client successfully communicated with the server")"
    else
        msg_error "$(translate "fail2ban-client could not communicate with the server")"
       
    fi


    msg_info "$(translate "Displaying Fail2Ban status...")"
    fail2ban-client status >/dev/null 2>&1
    msg_ok "$(translate "Fail2Ban status displayed")"

    msg_success "$(translate "Fail2Ban installation and configuration completed successfully!")"
    
}




# ==========================================================




install_lynis_() {
    msg_info2 "$(translate "Installing Lynis security scan tool...")"

    # Install Lynis directly from Debian repositories
    msg_info "$(translate "Installing Lynis packages...")"
    (
        /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install lynis 2>&1 | \
        while IFS= read -r line; do
            if [[ $line == *"Installing"* ]] || [[ $line == *"Unpacking"* ]]; then
                printf "\r%-$(($(tput cols)-1))s\r" " "  # Clear current line
                printf "\r%s" "$line"
            fi
        done
    )

    if [ $? -eq 0 ]; then
        printf "\r%-$(($(tput cols)-1))s\r" " "  # Clear final line
        msg_ok "$(translate "Lynis installed successfully")"
    else
        printf "\r%-$(($(tput cols)-1))s\r" " "  # Clear final line
        msg_warn "$(translate "Failed to install Lynis")"
    fi

    # Verify installation
    if command -v lynis >/dev/null 2>&1; then
        msg_success "$(translate "Lynis is ready to use")"
    else
        msg_warn "$(translate "Lynis installation could not be verified")"
    fi
}


install_lynis() {
    msg_info2 "$(translate "Installing latest Lynis security scan tool...")"

    if ! command -v git >/dev/null 2>&1; then
        msg_info "$(translate "Installing Git as a prerequisite...")"
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y git >/dev/null 2>&1
        msg_ok "$(translate "Git installed")"
    fi

    if [ -d /opt/lynis ]; then
        rm -rf /opt/lynis >/dev/null 2>&1
    fi

    msg_info "$(translate "Cloning Lynis from GitHub...")"
    if git clone --quiet https://github.com/CISOfy/lynis.git /opt/lynis >/dev/null 2>&1; then
        # Create wrapper script instead of symbolic link
        cat << 'EOF' > /usr/local/bin/lynis
#!/bin/bash
cd /opt/lynis && ./lynis "$@"
EOF
        chmod +x /usr/local/bin/lynis
        msg_ok "$(translate "Lynis installed successfully from GitHub")"
    else
        msg_warn "$(translate "Failed to clone Lynis from GitHub")"
        return 1
    fi

    if /usr/local/bin/lynis show version >/dev/null 2>&1; then
        msg_success "$(translate "Lynis is ready to use")"
    else
        msg_warn "$(translate "Lynis installation could not be verified")"
    fi
}






# ==========================================================





install_guest_agent() {
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
        else
            msg_error "$(translate "Failed to install $guest_agent")"
        fi
    fi

    msg_success "$(translate "Guest agent installation process completed")"
}




# ==========================================================





configure_ksmtuned() {
    msg_info2 "$(translate "Installing and configuring KSM (Kernel Samepage Merging) daemon...")"
    NECESSARY_REBOOT=1

    # Install ksm-control-daemon
    msg_info "$(translate "Installing ksm-control-daemon...")"
    if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install ksm-control-daemon > /dev/null 2>&1; then
        msg_ok "$(translate "ksm-control-daemon installed successfully")"
    fi

    # Determine RAM size and set KSM parameters
    if [[ RAM_SIZE_GB -le 16 ]]; then
        KSM_THRES_COEF=50
        KSM_SLEEP_MSEC=80
        msg_info "$(translate "RAM <= 16GB: Setting KSM to start at 50% full")"
    elif [[ RAM_SIZE_GB -le 32 ]]; then
        KSM_THRES_COEF=40
        KSM_SLEEP_MSEC=60
        msg_info "$(translate "RAM <= 32GB: Setting KSM to start at 60% full")"
    elif [[ RAM_SIZE_GB -le 64 ]]; then
        KSM_THRES_COEF=30
        KSM_SLEEP_MSEC=40
        msg_info "$(translate "RAM <= 64GB: Setting KSM to start at 70% full")"
    elif [[ RAM_SIZE_GB -le 128 ]]; then
        KSM_THRES_COEF=20
        KSM_SLEEP_MSEC=20
        msg_info "$(translate "RAM <= 128GB: Setting KSM to start at 80% full")"
    else
        KSM_THRES_COEF=10
        KSM_SLEEP_MSEC=10
        msg_info "$(translate "RAM > 128GB: Setting KSM to start at 90% full")"
    fi
    # Update ksmtuned configuration
    if sed -i -e "s/\# KSM_THRES_COEF=.*/KSM_THRES_COEF=${KSM_THRES_COEF}/g" /etc/ksmtuned.conf && \
       sed -i -e "s/\# KSM_SLEEP_MSEC=.*/KSM_SLEEP_MSEC=${KSM_SLEEP_MSEC}/g" /etc/ksmtuned.conf; then
        msg_ok "$(translate "ksmtuned configuration updated successfully")"
    fi

    # Enable ksmtuned service
    if systemctl enable ksmtuned > /dev/null 2>&1; then
        msg_ok "$(translate "ksmtuned service enabled successfully")"
    fi

    msg_success "$(translate "KSM configuration completed")"
}





# ==========================================================





enable_vfio_iommu_() {
    msg_info2 "$(translate "Enabling IOMMU and configuring VFIO for PCI passthrough...")"
    NECESSARY_REBOOT=1

    # Detect if system uses ZFS
    local uses_zfs=false
    local cmdline_file="/etc/kernel/cmdline"
    if [[ -f "$cmdline_file" && $(grep -q "root=ZFS=" "$cmdline_file") ]]; then
        uses_zfs=true
    fi

    # Enable IOMMU
    local cpu_info=$(cat /proc/cpuinfo)
    local grub_file="/etc/default/grub"
    local iommu_param=""
    local additional_params="pcie_acs_override=downstream,multifunction nofb nomodeset video=vesafb:off,efifb:off"

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

    if [[ "$uses_zfs" == true ]]; then
        if grep -q "$iommu_param" "$cmdline_file"; then
            if ! grep -q "iommu=pt" "$cmdline_file"; then
                cp "$cmdline_file" "${cmdline_file}.bak"
                sed -i "/^.*root=ZFS=/ s|$| iommu=pt|" "$cmdline_file"
                msg_ok "$(translate "Added missing iommu=pt to ZFS configuration")"
            else
                msg_ok "$(translate "IOMMU and additional parameters already configured for ZFS")"
            fi
        else
            cp "$cmdline_file" "${cmdline_file}.bak"
            sed -i "/^.*root=ZFS=/ s|$| $iommu_param iommu=pt|" "$cmdline_file"
            msg_ok "$(translate "IOMMU and additional parameters added for ZFS")"
        fi
    else

        if grep -q "$iommu_param" "$grub_file"; then
            if ! grep -q "iommu=pt" "$grub_file"; then
                cp "$grub_file" "${grub_file}.bak"
                sed -i "/GRUB_CMDLINE_LINUX_DEFAULT=/ s|\"$| iommu=pt\"|" "$grub_file"
                msg_ok "$(translate "Added missing iommu=pt to GRUB configuration")"
            else
                msg_ok "$(translate "IOMMU already enabled in GRUB configuration")"
            fi
        else
            cp "$grub_file" "${grub_file}.bak"
            sed -i "/GRUB_CMDLINE_LINUX_DEFAULT=/ s|\"$| $iommu_param iommu=pt\"|" "$grub_file"
            msg_ok "$(translate "IOMMU enabled in GRUB configuration")"
        fi
    fi

    # Configure VFIO modules (avoid duplicates)
    local modules_file="/etc/modules"
    msg_info "$(translate "Checking VFIO modules...")"
    local vfio_modules=("vfio" "vfio_iommu_type1" "vfio_pci" "vfio_virqfd")

    for module in "${vfio_modules[@]}"; do
        grep -q "^$module" "$modules_file" || echo "$module" >> "$modules_file"
    done
    msg_ok "$(translate "VFIO modules configured.)")"

    # Blacklist conflicting drivers (avoid duplicates)
    local blacklist_file="/etc/modprobe.d/blacklist.conf"
    msg_info "$(translate "Checking conflicting drivers blacklist...")"
    touch "$blacklist_file"
    local blacklist_drivers=("nouveau" "lbm-nouveau" "amdgpu" "radeon" "nvidia" "nvidiafb")

    for driver in "${blacklist_drivers[@]}"; do
        grep -q "^blacklist $driver" "$blacklist_file" || echo "blacklist $driver" >> "$blacklist_file"
    done

    if ! grep -q "options nouveau modeset=0" "$blacklist_file"; then
        echo "options nouveau modeset=0" >> "$blacklist_file"
    fi
    msg_ok "$(translate "Conflicting drivers blacklisted successfully.")"


  # Propagate the settings
    msg_info "$(translate "Updating initramfs, GRUB, and EFI boot, patience...")"
    if update-initramfs -u -k all > /dev/null 2>&1 && \
       update-grub > /dev/null 2>&1 && \
       pve-efiboot-tool refresh > /dev/null 2>&1; then
     msg_ok "$(translate "Initramfs, GRUB, and EFI boot updated successfully")"
    else
        msg_error "$(translate "Failed to update one or more components (initramfs, GRUB, or EFI boot)")"
    fi

    msg_success "$(translate "IOMMU and VFIO setup completed")"
}



enable_vfio_iommu__() {
    msg_info2 "$(translate "Enabling IOMMU and configuring VFIO for PCI passthrough...")"
    NECESSARY_REBOOT=1

    # Detect if system uses ZFS/systemd-boot (Proxmox)
    local uses_zfs=false
    local cmdline_file="/etc/kernel/cmdline"
    if [[ -f "$cmdline_file" ]] && grep -qE 'root=ZFS=|root=ZFS/' "$cmdline_file"; then
        uses_zfs=true
    fi

    # Enable IOMMU
    local cpu_info=$(cat /proc/cpuinfo)
    local grub_file="/etc/default/grub"
    local iommu_param=""
    local additional_params="pcie_acs_override=downstream,multifunction nofb nomodeset video=vesafb:off,efifb:off"

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

    if [[ "$uses_zfs" == true ]]; then
        # --- SYSTEMD-BOOT: /etc/kernel/cmdline ---
        if grep -q "$iommu_param" "$cmdline_file"; then
            msg_ok "$(translate "IOMMU already configured in /etc/kernel/cmdline")"
        else
            cp "$cmdline_file" "${cmdline_file}.bak"
          # sed -i "s|\"$| $iommu_param iommu=pt|" "$cmdline_file"
            sed -i "s|\s*$| $iommu_param iommu=pt|" "$cmdline_file"
            msg_ok "$(translate "IOMMU parameters added to /etc/kernel/cmdline")"
        fi
    else
        # --- GRUB ---
        if grep -q "$iommu_param" "$grub_file"; then
            msg_ok "$(translate "IOMMU already enabled in GRUB configuration")"
        else
            cp "$grub_file" "${grub_file}.bak"
            sed -i "/GRUB_CMDLINE_LINUX_DEFAULT=/ s|\"$| $iommu_param iommu=pt\"|" "$grub_file"
            msg_ok "$(translate "IOMMU enabled in GRUB configuration")"
        fi
    fi

    # Configure VFIO modules (avoid duplicates)
    local modules_file="/etc/modules"
    msg_info "$(translate "Checking VFIO modules...")"
    local vfio_modules=("vfio" "vfio_iommu_type1" "vfio_pci" "vfio_virqfd")
    for module in "${vfio_modules[@]}"; do
        grep -q "^$module" "$modules_file" || echo "$module" >> "$modules_file"
    done
    msg_ok "$(translate "VFIO modules configured.")"

    # Blacklist conflicting drivers (avoid duplicates)
    local blacklist_file="/etc/modprobe.d/blacklist.conf"
    msg_info "$(translate "Checking conflicting drivers blacklist...")"
    touch "$blacklist_file"
    local blacklist_drivers=("nouveau" "lbm-nouveau" "amdgpu" "radeon" "nvidia" "nvidiafb")
    for driver in "${blacklist_drivers[@]}"; do
        grep -q "^blacklist $driver" "$blacklist_file" || echo "blacklist $driver" >> "$blacklist_file"
    done
    if ! grep -q "options nouveau modeset=0" "$blacklist_file"; then
        echo "options nouveau modeset=0" >> "$blacklist_file"
    fi
    msg_ok "$(translate "Conflicting drivers blacklisted successfully.")"

    # Propagate the settings
    msg_info "$(translate "Updating initramfs, GRUB, and EFI boot, patience...")"
    update-initramfs -u -k all > /dev/null 2>&1
    if [[ "$uses_zfs" == true ]]; then
        proxmox-boot-tool refresh > /dev/null 2>&1
    else
        update-grub > /dev/null 2>&1
    fi

    msg_success "$(translate "IOMMU and VFIO setup completed")"
}





enable_vfio_iommu() {
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
    
    # Configure VFIO modules (sin cambios)
    local modules_file="/etc/modules"
    msg_info "$(translate "Checking VFIO modules...")"
    local vfio_modules=("vfio" "vfio_iommu_type1" "vfio_pci" "vfio_virqfd")
    
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
    
    local blacklist_drivers=("nouveau" "lbm-nouveau" "amdgpu" "radeon" "nvidia" "nvidiafb")
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
}




# ==========================================================





customize_bashrc_() {
   msg_info2 "$(translate "Customizing bashrc for root user...")"

    local bashrc="/root/.bashrc"
    local bash_profile="/root/.bash_profile"

    # Backup original .bashrc if it doesn't exist
    if [ ! -f "${bashrc}.bak" ]; then
        cp "$bashrc" "${bashrc}.bak"
    fi

    # Function to add a line if it doesn't exist
    add_line_if_not_exists() {
        local line="$1"
        local file="$2"
        grep -qF -- "$line" "$file" || echo "$line" >> "$file"
    }

    # Add custom configurations to .bashrc
    add_line_if_not_exists 'export HISTTIMEFORMAT="%d/%m/%y %T "' "$bashrc"
    add_line_if_not_exists 'export PS1='"'\u@\h:\W \$ '" "$bashrc"
    add_line_if_not_exists "alias l='ls -CF'" "$bashrc"
    add_line_if_not_exists "alias la='ls -A'" "$bashrc"
    add_line_if_not_exists "alias ll='ls -alF'" "$bashrc"
    add_line_if_not_exists "alias ls='ls --color=auto'" "$bashrc"
    add_line_if_not_exists "alias grep='grep --color=auto'" "$bashrc"
    add_line_if_not_exists "alias fgrep='fgrep --color=auto'" "$bashrc"
    add_line_if_not_exists "alias egrep='egrep --color=auto'" "$bashrc"
    add_line_if_not_exists "source /etc/profile.d/bash_completion.sh" "$bashrc"
    add_line_if_not_exists 'export PS1="\[\e[31m\][\[\e[m\]\[\e[38;5;172m\]\u\[\e[m\]@\[\e[38;5;153m\]\h\[\e[m\] \[\e[38;5;214m\]\W\[\e[m\]\[\e[31m\]]\[\e[m\]\\$ "' "$bashrc"

    msg_ok "$(translate "Custom configurations added to .bashrc")"

    # Ensure .bashrc is sourced in .bash_profile
    add_line_if_not_exists "source /root/.bashrc" "$bash_profile"
    msg_ok "$(translate ".bashrc sourced in .bash_profile")"

    msg_success "$(translate "Bashrc customization completed")"
}







customize_bashrc() {
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
msg_info2 "$(translate "Optimizing logrotate configuration...")"

    local logrotate_conf="/etc/logrotate.conf"
    local backup_conf="${logrotate_conf}.bak"


    if grep -q "# ProxMenux optimized configuration" "$logrotate_conf"; then
        msg_ok "$(translate "Logrotate configuration already optimized.")"
    else
        cp "$logrotate_conf" "$backup_conf"
        
        msg_info "$(translate "Applying optimized logrotate configuration...")"
        cat <<EOF > "$logrotate_conf"
# ProxMenux optimized configuration
daily
su root adm
rotate 7
create
compress
size=10M
delaycompress
copytruncate

include /etc/logrotate.d
EOF

    systemctl restart logrotate > /dev/null 2>&1
    msg_ok "$(translate "Logrotate service restarted successfully")"
   fi
    msg_success "$(translate "Logrotate optimization completed")"
}





# ==========================================================





remove_subscription_banner() {
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

    if [[ -z "$pve_version" ]]; then
        msg_error "Unable to detect Proxmox version."
        return 1
    fi

    if [[ "$pve_version" -ge 9 ]]; then

        bash <(curl -fsSL "$REPO_URL/scripts/global/remove-banner-pve9.sh")
    else

        bash <(curl -fsSL "$REPO_URL/scripts/global/remove-banner-pve8.sh")
    fi
}





# ==========================================================





optimize_memory_settings() {
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
vm.max_map_count = 65530
EOF

    if [ -f /proc/sys/vm/compaction_proactiveness ]; then
        echo "vm.compaction_proactiveness = 20" >> "$sysctl_conf"
        msg_ok "$(translate "Enabled memory compaction proactiveness")"
    fi

    msg_ok "$(translate "Memory settings optimized successfully")"
    msg_success "$(translate "Memory optimization completed.")"
    register_tool "memory_settings" true
}





# ==========================================================





optimize_vzdump() {
    msg_info2 "$(translate "Optimizing vzdump backup speed...")"

    local vzdump_conf="/etc/vzdump.conf"

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
}





# ==========================================================





install_ovh_rtm() {
    msg_info2 "$(translate "Detecting if this is an OVH server and installing OVH RTM if necessary...")"

    # Get the public IP and check if it belongs to OVH
    msg_info "$(translate "Checking if the server belongs to OVH...")"
    public_ip=$(curl -s ipinfo.io/ip)
    is_ovh=$(whois -h v4.whois.cymru.com " -t $public_ip" | tail -n 1 | cut -d'|' -f3 | grep -i "ovh")

    if [ -n "$is_ovh" ]; then
        msg_ok "$(translate "OVH server detected")"

        msg_info "$(translate "Installing OVH RTM (Real Time Monitoring)...")"
        if wget -qO - https://last-public-ovh-infra-yak.snap.mirrors.ovh.net/yak/archives/apply.sh | OVH_PUPPET_MANIFEST=distribyak/catalog/master/puppet/manifests/common/rtmv2.pp bash > /dev/null 2>&1; then
            msg_ok "$(translate "OVH RTM installed successfully")"
        else
            msg_error "$(translate "Failed to install OVH RTM")"
        fi
    fi
    msg_ok "$(translate "Server belongs to OVH")"
    msg_success "$(translate "OVH server detection and RTM installation process completed")"
}




# ==========================================================



enable_ha() {
    msg_info2 "$(translate "Enabling High Availability (HA) services...")"
    NECESSARY_REBOOT=1

    msg_info "$(translate "Enabling High Availability (HA) services...")"
    # Enable all necessary services
    systemctl enable -q --now pve-ha-lrm pve-ha-crm corosync &>/dev/null


    msg_ok "$(translate "High Availability services have been enabled successfully")"
    msg_success "$(translate "High Availability setup completed")"


}




# ==========================================================






configure_fastfetch() {
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
    local fastfetch_deb_url=$(curl -s https://api.github.com/repos/fastfetch-cli/fastfetch/releases/latest |
        jq -r '.assets[] | select(.name | test("fastfetch-linux-amd64.deb")) | .browser_download_url')

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
        local logo_options=("ProxMenux" "Proxmox (default)" "Comunidad Helper-Scripts" "Home-Labs-Club" "Proxmology" "Custom")
        local choice

        choice=$(whiptail --title "$(translate "Fastfetch Logo Selection")" --menu "$(translate "Choose a logo for Fastfetch:")" 20 78 6 \
            "1" "${logo_options[0]}" \
            "2" "${logo_options[1]}" \
            "3" "${logo_options[2]}" \
            "4" "${logo_options[3]}" \
            "5" "${logo_options[4]}" \
            "6" "${logo_options[5]}" \
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
            4)
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
            5)
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
            6)
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
register_tool "fastfetch" true

}






# ==========================================================






add_repo_test() {
 msg_info2 "$(translate "Enable Proxmox testing repository...")"
    # Enable Proxmox testing repository
    if [ ! -f /etc/apt/sources.list.d/pve-testing-repo.list ] || ! grep -q "pvetest" /etc/apt/sources.list.d/pve-testing-repo.list; then
        msg_info "$(translate "Enabling Proxmox testing repository...")"
        echo -e "deb http://download.proxmox.com/debian/pve ${OS_CODENAME} pvetest\\n" > /etc/apt/sources.list.d/pve-testing-repo.list
        msg_ok "$(translate "Proxmox testing repository enabled")"
    fi
 msg_success "$(translate "Proxmox testing repository has been successfully enabled")"
}






# ==========================================================





configure_figurine_() {
    msg_info2 "$(translate "Installing and configuring Figurine...")"

    # Variables
    local version="1.3.0"
    local file="figurine_linux_amd64_v${version}.tar.gz"
    local url="https://github.com/arsham/figurine/releases/download/v${version}/${file}"
    local temp_dir
    temp_dir=$(mktemp -d)
    local install_dir="/usr/local/bin"
    local profile_script="/etc/profile.d/figurine.sh"
    local bin_path="${install_dir}/figurine"

    msg_info "$(translate "Downloading Figurine v${version}...")"
        if command -v figurine &> /dev/null; then
            rm -f "$bin_path" > /dev/null 2>&1
            msg_ok "$(translate "Previous installation removed")"

        fi

    wget -qO "${temp_dir}/${file}" "$url" > /dev/null 2>&1
    msg_ok "$(translate "Download completed")"


    msg_info "$(translate "Extracting package...")"
    tar -xf "${temp_dir}/${file}" -C "${temp_dir}" > /dev/null 2>&1
    msg_ok "$(translate "Extraction successful")"


    if [[ ! -f "${temp_dir}/deploy/figurine" ]]; then
        msg_error "$(translate "Binary not found in extracted content.")"
        return 1
    fi


    msg_info "$(translate "Installing binary to ${install_dir}...")"
    mv "${temp_dir}/deploy/figurine" "$bin_path" > /dev/null 2>&1
    chmod +x "$bin_path" > /dev/null 2>&1
    msg_ok "$(translate "Binary installed")"


    msg_info "$(translate "Creating figurine welcome message at ${profile_script}...")"
    cat << 'EOF' > "$profile_script"
/usr/local/bin/figurine -f "3d.flf" $(hostname)
EOF
    chmod +x "$profile_script" > /dev/null 2>&1
    msg_ok "$(translate "Welcome message script created")"


local bashrc="$HOME/.bashrc"

    if ! grep -q "alias aptup=" "$bashrc"; then
        msg_info "$(translate "Adding useful aliases to ~/.bashrc...")"
        cat <<EOF >> "$bashrc"

# ProxMenux Figurine aliases and tools
alias aptup='apt update && apt dist-upgrade'

alias lxcclean='curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/clean-lxcs.sh | bash'
alias lxcupdate='curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/update-lxcs.sh | bash'
alias kernelclean='curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/kernel-clean.sh | bash'
alias cpugov='curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/scaling-governor.sh | bash'

alias updatecerts='pvecm updatecerts'
alias seqwrite='sync; fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4M --size=32G --readwrite=write --ramp_time=4'
alias seqread='sync; fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4M --size=32G --readwrite=read --ramp_time=4'
alias ranwrite='sync; fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4k --size=4G --readwrite=randwrite --ramp_time=4'
alias ranread='sync; fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4k --size=4G --readwrite=randread --ramp_time=4'
alias l='ls -CF'
alias la='ls -A'
alias ll='ls -alF'
alias ls='ls --color=auto'
alias grep='grep --color=auto'
alias fgrep='fgrep --color=auto'
alias egrep='egrep --color=auto'
EOF
        msg_ok "$(translate "Aliases added to .bashrc")"
        sed -i '/\${marker_begin}/d;/\${marker_end}/d' .bashrc

    else
        msg_info "$(translate "Aliases already present. Skipping addition.")"
        msg_ok "$(translate "Aliases added to .bashrc")"
    fi



    msg_info "$(translate "Cleaning up temporary files...")"
    rm -rf "$temp_dir" > /dev/null 2>&1
    msg_ok "$(translate "Cleanup completed")"

    msg_success "$(translate "Figurine installation and configuration completed successfully.")"
}







configure_figurine() {
    
    msg_info2 "$(translate "Installing and configuring Figurine...")"
    local version="1.3.0"
    local file="figurine_linux_amd64_v${version}.tar.gz"
    local url="https://github.com/arsham/figurine/releases/download/v${version}/${file}"
    local temp_dir
    temp_dir=$(mktemp -d)
    local install_dir="/usr/local/bin"
    local profile_script="/etc/profile.d/figurine.sh"
    local bin_path="${install_dir}/figurine"
    local bashrc="/root/.bashrc"
    local marker_begin="# BEGIN PMX_FIGURINE"
    local marker_end="# END PMX_FIGURINE"
    
 
    cleanup() { 
        rm -rf "$temp_dir" 2>/dev/null || true
    }
    trap cleanup EXIT
    
  
    if command -v figurine &>/dev/null; then
        msg_info "$(translate "Updating Figurine binary...")"
    else
        msg_info "$(translate "Downloading Figurine v${version}...")"
    fi
    
    if ! wget -qO "${temp_dir}/${file}" "$url" > /dev/null 2>&1; then
        msg_error "$(translate "Failed to download Figurine")"
        return 1
    fi

    
    if ! tar -xf "${temp_dir}/${file}" -C "${temp_dir}" > /dev/null 2>&1; then
        msg_error "$(translate "Failed to extract package")"
        return 1
    fi
    msg_ok "$(translate "Extraction successful")"
    
    if [[ ! -f "${temp_dir}/deploy/figurine" ]]; then
        msg_error "$(translate "Binary not found in extracted content.")"
        return 1
    fi
    
    msg_info "$(translate "Installing binary to ${install_dir}...")"

    install -m 0755 -o root -g root "${temp_dir}/deploy/figurine" "$bin_path" > /dev/null 2>&1

    cat > "$profile_script" << 'EOF'
/usr/local/bin/figurine -f "3d.flf" $(hostname)
EOF
    chmod +x "$profile_script" > /dev/null 2>&1

    
   
    if grep -q "^${marker_begin}$" "$bashrc" 2>/dev/null; then
        sed -i "/^${marker_begin}$/,/^${marker_end}$/d" "$bashrc"  
    fi
    
 
    cat >> "$bashrc" << 'EOF'
${marker_begin}
# ProxMenux Figurine aliases and tools
alias aptup='apt update && apt dist-upgrade'
alias lxcclean='curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/clean-lxcs.sh | bash'
alias lxcupdate='curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/update-lxcs.sh | bash'
alias kernelclean='curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/kernel-clean.sh | bash'
alias cpugov='curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/scaling-governor.sh | bash'
alias lxctrim='curl -fsSL -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/fstrim.sh | bash'
alias updatecerts='pvecm updatecerts'
alias seqwrite='sync; fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4M --size=32G --readwrite=write --ramp_time=4'
alias seqread='sync; fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4M --size=32G --readwrite=read --ramp_time=4'
alias ranwrite='sync; fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4k --size=4G --readwrite=randwrite --ramp_time=4'
alias ranread='sync; fio --randrepeat=1 --ioengine=libaio --direct=1 --name=test --filename=test --bs=4k --size=4G --readwrite=randread --ramp_time=4'
${marker_end}
EOF
    msg_ok "$(translate "Aliases added to .bashrc")"
    sed -i '/\${marker_begin}/d;/\${marker_end}/d' .bashrc
    
    msg_success "$(translate "Figurine installation and configuration completed successfully.")"
    register_tool "figurine" true
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

    msg_info2 "$(translate "Preparing Log2RAM configuration")"
    sleep 2


    if [[ -f /etc/log2ram.conf ]] && command -v log2ram >/dev/null 2>&1 && systemctl list-units --all | grep -q log2ram; then
        msg_ok "$(translate "Log2RAM is already installed and configured correctly.")"
        register_tool "log2ram" true
        return 0
    fi

    RAM_SIZE_GB=$(free -g | awk '/^Mem:/{print $2}')
    [[ -z "$RAM_SIZE_GB" || "$RAM_SIZE_GB" -eq 0 ]] && RAM_SIZE_GB=4

    if (( RAM_SIZE_GB <= 8 )); then
        DEFAULT_SIZE="128"
        DEFAULT_HOURS="1"
    elif (( RAM_SIZE_GB <= 16 )); then
        DEFAULT_SIZE="256"
        DEFAULT_HOURS="3"
    else
        DEFAULT_SIZE="512"
        DEFAULT_HOURS="6"
    fi


    USER_SIZE=$(whiptail --title "Log2RAM" --inputbox "$(translate "Enter the maximum size (in MB) to allocate for /var/log in RAM (e.g. 128, 256, 512):")\n\n$(translate "Recommended for $RAM_SIZE_GB GB RAM:") ${DEFAULT_SIZE}M" 12 70 "$DEFAULT_SIZE" 3>&1 1>&2 2>&3) || return 0
    LOG2RAM_SIZE="${USER_SIZE}M"


    CRON_HOURS=$(whiptail --title "Log2RAM" --radiolist "$(translate "Select the sync interval (in hours):")\n\n$(translate "Suggested interval: every $DEFAULT_HOURS hour(s)")" 15 70 5 \
        "1" "$(translate "Every hour")" OFF \
        "3" "$(translate "Every 3 hours")" OFF \
        "6" "$(translate "Every 6 hours")" OFF \
        "12" "$(translate "Every 12 hours")" OFF \
        3>&1 1>&2 2>&3) || return 0

    # Activar auto-sync si se pasa del 90%
    if whiptail --title "Log2RAM" --yesno "$(translate "Enable auto-sync if /var/log exceeds 90% of its size?")" 10 60; then
        ENABLE_AUTOSYNC=true
    else
        ENABLE_AUTOSYNC=false
    fi

    # Instalación
    msg_info "$(translate "Installing Log2RAM from GitHub...")"
    rm -rf /tmp/log2ram

    # Ensure git is available
    if ! command -v git >/dev/null 2>&1; then
        msg_info "$(translate "Installing required package: git")"
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y git >/dev/null 2>&1
    fi

    git clone https://github.com/azlux/log2ram.git /tmp/log2ram >/dev/null 2>&1
    cd /tmp/log2ram || return 1
    bash install.sh >/dev/null 2>&1

    if [[ -f /etc/log2ram.conf ]] && systemctl list-units --all | grep -q log2ram; then
        msg_ok "$(translate "Log2RAM installed successfully")"
    else
        msg_error "$(translate "Failed to install Log2RAM.")"
        return 1
    fi

    # Aplicar configuración
    sed -i "s/^SIZE=.*/SIZE=$LOG2RAM_SIZE/" /etc/log2ram.conf
    rm -f /etc/cron.hourly/log2ram
    echo "0 */$CRON_HOURS * * * root /usr/sbin/log2ram write" > /etc/cron.d/log2ram
    msg_ok "$(translate "Log2RAM write scheduled every") $CRON_HOURS $(translate "hour(s)")"

    # Auto-sync
    if [[ "$ENABLE_AUTOSYNC" == true ]]; then
        cat << 'EOF' > /usr/local/bin/log2ram-check.sh
#!/bin/bash
CONF_FILE="/etc/log2ram.conf"
LIMIT_KB=$(grep '^SIZE=' "$CONF_FILE" | cut -d'=' -f2 | tr -d 'M')000
USED_KB=$(df /var/log --output=used | tail -1)
THRESHOLD=$(( LIMIT_KB * 90 / 100 ))
if (( USED_KB > THRESHOLD )); then
    $(command -v log2ram) write
fi
EOF
        chmod +x /usr/local/bin/log2ram-check.sh
        echo "*/5 * * * * root /usr/local/bin/log2ram-check.sh" > /etc/cron.d/log2ram-auto-sync
        msg_ok "$(translate "Auto-sync enabled when /var/log exceeds 90% of") $LOG2RAM_SIZE"
    else
        rm -f /usr/local/bin/log2ram-check.sh /etc/cron.d/log2ram-auto-sync
        msg_info2 "$(translate "Auto-sync was not enabled")"
    fi

    sleep 1
    systemctl restart log2ram
    msg_success "$(translate "Log2RAM installation and configuration completed successfully.")"
    register_tool "log2ram" true
    # NECESSARY_REBOOT=1
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
        msg_ok "$(translate "Changes will apply after reboot.")"
    else
        msg_warn "$(translate "No physical interfaces found")"
    fi
    msg_success "$(translate "Setting up persistent network interfaces successfully.")"
    register_tool "persistent_network" true
    NECESSARY_REBOOT=1
}







# ==========================================================






# ==========================================================
#        Auxiliary help functions
# ==========================================================

# Rest of the functions remain the same...
cleanup_duplicate_repos() {
    msg_info "$(translate "Cleaning up duplicate repositories...")"
    
    local sources_file="/etc/apt/sources.list"
    local temp_file=$(mktemp)
    local cleaned_count=0
    declare -A seen_repos
    
    # Clean main sources.list
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
    
    # Clean up old Proxmox repository files
    local old_pve_files=(/etc/apt/sources.list.d/pve-*.list)
    for file in "${old_pve_files[@]}"; do
        if [ -f "$file" ] && [[ "$file" != "/etc/apt/sources.list.d/pve-enterprise.list" ]]; then
            # Check if we have the new .sources format
            if [ -f "/etc/apt/sources.list.d/proxmox.sources" ]; then
                msg_info "$(translate "Removing old repository file: $(basename "$file")")"
                rm -f "$file"
                cleaned_count=$((cleaned_count + 1))
            fi
        fi
    done
    
    if [ $cleaned_count -gt 0 ]; then
        msg_ok "$(translate "Cleaned up $cleaned_count duplicate/old repositories")"
        apt-get update > /dev/null 2>&1
    else
        msg_ok "$(translate "No duplicate repositories found")"
    fi
}








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








# ==========================================================








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
    "System|Ensure entropy pools are populated|ENTROPY"
    "System|Optimize Memory|MEMORYFIXES"
    "System|Enable fast reboots|KEXEC"
    "System|Enable restart on kernel panic|KERNELPANIC"
    "System|Install kernel headers|KERNELHEADERS"
    "Optional|Apply AMD CPU fixes|AMDFIXES"
    "Virtualization|Install relevant guest agent|GUESTAGENT"
    "Virtualization|Enable VFIO IOMMU support|VFIO_IOMMU"
    "Virtualization|KSM control daemon|KSMTUNED"
    "Network|Force APT to use IPv4|APTIPV4"
    "Network|Apply network optimizations|NET"
    "Network|Install Open vSwitch|OPENVSWITCH"
    "Network|Enable TCP BBR/Fast Open control|TCPFASTOPEN"
    "Network|Interface Names (persistent)|PERSISNET"
    "Storage|Optimize ZFS ARC size|ZFSARC"
    "Storage|Install ZFS auto-snapshot|ZFSAUTOSNAPSHOT"
    "Storage|Increase vzdump backup speed|VZDUMP"
    "Security|Disable portmapper/rpcbind|DISABLERPC"
    "Security|Protect web interface with fail2ban|FAIL2BAN"
    "Security|Install Lynis security tool|LYNIS"
    "Customization|Customize bashrc|BASHRC"
    "Customization|Set up custom MOTD banner|MOTD"
    "Customization|Remove subscription banner|NOSUBBANNER"
    "Monitoring|Install OVH Real Time Monitoring|OVHRTM"
    "Performance|Use pigz for faster gzip compression|PIGZ"
    "Optional|Install and configure Fastfetch|FASTFETCH"
    "Optional|Update Proxmox VE Appliance Manager|PVEAM"
    "Optional|Add latest Ceph support|CEPH"
    "Optional|Add Proxmox testing repository|REPOTEST"
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
        ENTROPY) configure_entropy ;;
        MEMORYFIXES) optimize_memory_settings ;;
        KEXEC) enable_kexec ;;
        KERNELPANIC) configure_kernel_panic ;;
        KERNELHEADERS) install_kernel_headers ;;
        AMDFIXES) apply_amd_fixes ;;
        GUESTAGENT) install_guest_agent ;;
        VFIO_IOMMU) enable_vfio_iommu ;;
        KSMTUNED) configure_ksmtuned ;;
        APTIPV4) force_apt_ipv4 ;;
        NET) apply_network_optimizations ;;
        OPENVSWITCH) install_openvswitch ;;
        TCPFASTOPEN) enable_tcp_fast_open ;;
        ZFSARC) optimize_zfs_arc ;;
        ZFSAUTOSNAPSHOT) install_zfs_auto_snapshot ;;
        VZDUMP) optimize_vzdump ;;
        DISABLERPC) disable_rpc ;;
        FAIL2BAN) install_fail2ban ;;
        LYNIS) install_lynis ;;
        BASHRC) customize_bashrc ;;
        MOTD) setup_motd ;;
        NOSUBBANNER) remove_subscription_banner ;;
        OVHRTM) install_ovh_rtm ;;
        PIGZ) configure_pigz ;;
        FASTFETCH) configure_fastfetch ;;
        CEPH) install_ceph ;;
        REPOTEST) add_repo_test ;;
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



check_extremeshok_warning
main_menu

