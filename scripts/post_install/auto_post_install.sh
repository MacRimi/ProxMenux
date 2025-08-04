#!/bin/bash
# ==========================================================
# ProxMenux - Complete Post-Installation Script with Registration
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
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
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
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
SCRIPT_TITLE="Customizable post-installation optimization script"

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
lvm_repair_check() {
    msg_info "$(translate "Checking and repairing old LVM PV headers (if needed)...")"
    pvs_output=$(LC_ALL=C pvs -v 2>&1 | grep "old PV header")
    if [ -z "$pvs_output" ]; then
        msg_ok "$(translate "No PVs with old headers found.")"
        register_tool "lvm_repair" true
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
    
    msg_ok "$(translate "LVM PV headers check completed")"

}

# ==========================================================
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
    local pve_content="deb http://download.proxmox.com/debian/pve ${OS_CODENAME} pve-no-subscription"
    local pve_public_repo="/etc/apt/sources.list.d/pve-public-repo.list"
    local pve_public_repo_exists=false
    
    if [ -f "$pve_public_repo" ] && grep -q "^deb.*pve-no-subscription" "$pve_public_repo"; then
        pve_public_repo_exists=true
    fi
    
    for file in "${pve_files[@]}"; do
        if [ -f "$file" ] && grep -q "^deb.*pve-no-subscription" "$file"; then
            if ! $pve_public_repo_exists && [[ "$file" == "$pve_public_repo" ]]; then
                sed -i 's/^# *deb/deb/' "$file"
                pve_public_repo_exists=true
            elif [[ "$file" != "$pve_public_repo" ]]; then
                sed -i 's/^deb/# deb/' "$file"
                cleaned_count=$((cleaned_count + 1))
            fi
        fi
    done
    
    apt update

}



apt_upgrade() {


    NECESSARY_REBOOT=1 


    if [ -f /etc/apt/sources.list.d/pve-enterprise.list ] && grep -q "^deb" /etc/apt/sources.list.d/pve-enterprise.list; then
        msg_info "$(translate "Disabling enterprise Proxmox repository...")"
        sed -i "s/^deb/#deb/g" /etc/apt/sources.list.d/pve-enterprise.list
        msg_ok "$(translate "Enterprise Proxmox repository disabled")"
    fi


    if [ -f /etc/apt/sources.list.d/ceph.list ] && grep -q "^deb" /etc/apt/sources.list.d/ceph.list; then
        msg_info "$(translate "Disabling enterprise Proxmox Ceph repository...")"
        sed -i "s/^deb/#deb/g" /etc/apt/sources.list.d/ceph.list
        msg_ok "$(translate "Enterprise Proxmox Ceph repository disabled")"
    fi


    if [ ! -f /etc/apt/sources.list.d/pve-public-repo.list ] || ! grep -q "pve-no-subscription" /etc/apt/sources.list.d/pve-public-repo.list; then
        msg_info "$(translate "Enabling free public Proxmox repository...")"
        echo "deb http://download.proxmox.com/debian/pve ${OS_CODENAME} pve-no-subscription" > /etc/apt/sources.list.d/pve-public-repo.list
        msg_ok "$(translate "Free public Proxmox repository enabled")"
    fi



    sources_file="/etc/apt/sources.list"
    need_update=false


    sed -i 's|ftp.es.debian.org|deb.debian.org|g' "$sources_file"


    if grep -q "^deb http://security.debian.org ${OS_CODENAME}-security main contrib" "$sources_file"; then
        sed -i "s|^deb http://security.debian.org ${OS_CODENAME}-security main contrib|deb http://security.debian.org/debian-security ${OS_CODENAME}-security main contrib non-free non-free-firmware|" "$sources_file"
        msg_ok "$(translate "Replaced security repository with full version")"
        need_update=true
    fi


    if ! grep -q "deb http://security.debian.org/debian-security ${OS_CODENAME}-security" "$sources_file"; then
        echo "deb http://security.debian.org/debian-security ${OS_CODENAME}-security main contrib non-free non-free-firmware" >> "$sources_file"
        need_update=true
    fi


    if ! grep -q "deb http://deb.debian.org/debian ${OS_CODENAME} " "$sources_file"; then
        echo "deb http://deb.debian.org/debian ${OS_CODENAME} main contrib non-free non-free-firmware" >> "$sources_file"
        need_update=true
    fi


    if ! grep -q "deb http://deb.debian.org/debian ${OS_CODENAME}-updates" "$sources_file"; then
        echo "deb http://deb.debian.org/debian ${OS_CODENAME}-updates main contrib non-free non-free-firmware" >> "$sources_file"
        need_update=true
    fi

        msg_ok "$(translate "Debian repositories configured correctly")"

# ===================================================


    if [ ! -f /etc/apt/apt.conf.d/no-bookworm-firmware.conf ]; then
        msg_info "$(translate "Disabling non-free firmware warnings...")"
        echo 'APT::Get::Update::SourceListWarnings::NonFreeFirmware "false";' > /etc/apt/apt.conf.d/no-bookworm-firmware.conf
        msg_ok "$(translate "Non-free firmware warnings disabled")"
    fi


    msg_info "$(translate "Updating package lists...")"
    if apt-get update > /dev/null 2>&1; then
        msg_ok "$(translate "Package lists updated")"
    else
        msg_error "$(translate "Failed to update package lists")"
        return 1
    fi


    msg_info "$(translate "Removing conflicting utilities...")"
    if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' purge ntp openntpd systemd-timesyncd > /dev/null 2>&1; then
        msg_ok "$(translate "Conflicting utilities removed")"
    else
        msg_error "$(translate "Failed to remove conflicting utilities")"
    fi

    

    msg_info "$(translate "Performing packages upgrade...")"
    apt-get install pv -y > /dev/null 2>&1
    total_packages=$(apt-get -s dist-upgrade | grep "^Inst" | wc -l)
    
    if [ "$total_packages" -eq 0 ]; then
        total_packages=1  
    fi
    msg_ok "$(translate "Packages upgrade successfull")"
    tput civis  
    tput sc     

    
    (
        /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' dist-upgrade 2>&1 | \
        while IFS= read -r line; do
            if [[ "$line" =~ ^(Setting up|Unpacking|Preparing to unpack|Processing triggers for) ]]; then
              
                package_name=$(echo "$line" | sed -E 's/.*(Setting up|Unpacking|Preparing to unpack|Processing triggers for) ([^ ]+).*/\2/')

                
                [ -z "$package_name" ] && package_name="$(translate "Unknown")"

               
                tput rc
                tput ed

               
                row=$(( $(tput lines) - 6 ))
                tput cup $row 0; echo "$(translate "Installing packages...")"
                tput cup $((row + 1)) 0; echo "──────────────────────────────────────────────"
                tput cup $((row + 2)) 0; echo "Package: $package_name"
                tput cup $((row + 3)) 0; echo "Progress: [                                                  ] 0%"
                tput cup $((row + 4)) 0; echo "──────────────────────────────────────────────"

               
                for i in $(seq 1 10); do
                    progress=$((i * 10))
                    tput cup $((row + 3)) 9 
                    printf "[%-50s] %3d%%" "$(printf "#%.0s" $(seq 1 $((progress/2))))" "$progress"
                      
                done
            fi
        done
    )

    if [ $? -eq 0 ]; then
        tput rc
        tput ed
        msg_ok "$(translate "System upgrade completed")"
    fi

   

    msg_info "$(translate "Installing additional Proxmox packages...")"
    if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install zfsutils-linux proxmox-backup-restore-image chrony > /dev/null 2>&1; then
        msg_ok "$(translate "Additional Proxmox packages installed")"
    else
        msg_error "$(translate "Failed to install additional Proxmox packages")"
    fi

    lvm_repair_check

    cleanup_duplicate_repos

    msg_ok "$(translate "Proxmox update completed")"

}

# ==========================================================

remove_subscription_banner_() {
    local JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
    local GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
    local APT_HOOK="/etc/apt/apt.conf.d/no-nag-script"

    # Detect if already applied
    if grep -q "NoMoreNagging" "$JS_FILE" 2>/dev/null && [[ -f "$APT_HOOK" ]]; then
        # Already applied, just reapply silently
        :
    else
        # Ask user
        if ! whiptail --title "$(translate "Proxmox Subscription Banner")" \
            --yesno "$(translate "Do you want to remove the Proxmox subscription banner from the web interface?")" 10 60; then
            msg_warn "$(translate "Banner removal cancelled by user.")"
            return 1
        fi
    fi

    msg_info "$(translate "Removing Proxmox subscription nag banner...")"

    if [[ ! -f "$APT_HOOK" ]]; then
        cat <<'EOF' > "$APT_HOOK"
DPkg::Post-Invoke { "dpkg -V proxmox-widget-toolkit | grep -q '/proxmoxlib\.js$'; if [ $? -eq 1 ]; then { echo 'Removing subscription nag from UI...'; sed -i '/.*data\.status.*{/{s/\!//;s/active/NoMoreNagging/;s/Active/NoMoreNagging/}' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js; rm -f /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz; }; fi"; };
EOF
    fi

    if [[ -f "$JS_FILE" ]]; then
        sed -i '/.*data\.status.*{/{s/\!//;s/active/NoMoreNagging/;s/Active/NoMoreNagging/}' "$JS_FILE"
        [[ -f "$GZ_FILE" ]] && rm -f "$GZ_FILE"
        touch "$JS_FILE"
    fi

    apt --reinstall install proxmox-widget-toolkit -y > /dev/null 2>&1

    msg_ok "$(translate "Subscription nag banner removed successfully")"
    register_tool "subscription_banner" true
}


remove_subscription_banner() {
    local JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
    local GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
    local APT_HOOK="/etc/apt/apt.conf.d/no-nag-script"


    if ! whiptail --title "Proxmox Subscription Banner" \
        --yesno "Do you want to remove the Proxmox subscription banner from the web interface?" 10 60; then
        msg_warn "Banner removal cancelled by user."
        return 1
    fi

    for f in /etc/apt/apt.conf.d/*nag*; do 
        [[ -e "$f" ]] && rm -f "$f"
    done


    msg_info "Applying patches to remove subscription banner..."

    sed -i "s/res\.data\.status\.toLowerCase() !== 'NoMoreNagging'/false/g" "$JS_FILE"
    sed -i "s/res\.data\.status\.toLowerCase() !== \"NoMoreNagging\"/false/g" "$JS_FILE"
    sed -i "s/res\.data\.status\.toLowerCase() !== 'active'/false/g" "$JS_FILE"
    sed -i "s/res\.data\.status !== 'Active'/false/g" "$JS_FILE"
    sed -i "s/subscription = !(/subscription = false \&\& (/g" "$JS_FILE"
    
    sed -i '/checked_command: function/,/},$/c\
        checked_command: function (orig_cmd) {\
            orig_cmd();\
        },' "$JS_FILE"

    sed -i "s/title: gettext('No valid subscription')/title: gettext('Subscription Active')/g" "$JS_FILE"
    sed -i "s/icon: Ext\.Msg\.WARNING/icon: Ext.Msg.INFO/g" "$JS_FILE"
    
    sed -i '/check_subscription: function/,/},$/c\
        check_subscription: function () {\
            let me = this;\
            let vm = me.getViewModel();\
            vm.set("subscriptionActive", true);\
            me.getController().updateState();\
        },' "$JS_FILE"

    [[ -f "$GZ_FILE" ]] && rm -f "$GZ_FILE"

    find /var/cache/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/lib/pve-manager/ -name "*.js*" -delete 2>/dev/null || true

    [[ -f "$APT_HOOK" ]] && rm -f "$APT_HOOK"
    cat > "$APT_HOOK" << 'EOF'
DPkg::Post-Invoke {
    "test -e /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && sed -i 's/res\\.data\\.status\\.toLowerCase() !== \\'NoMoreNagging\\'/false/g' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js || true";
    "test -e /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && sed -i 's/res\\.data\\.status\\.toLowerCase() !== \\'active\\'/false/g' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js || true";
    "test -e /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && sed -i 's/subscription = !(/subscription = false \\&\\& (/g' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js || true";
    "rm -f /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz || true";
};
EOF

    chmod 644 "$APT_HOOK"

    apt --reinstall install proxmox-widget-toolkit -y > /dev/null 2>&1

    local changes_applied=0
    if ! grep -q "res\.data\.status\.toLowerCase() !== 'NoMoreNagging'" "$JS_FILE"; then
        ((changes_applied++))
    fi
    if ! grep -q "title: gettext('No valid subscription')" "$JS_FILE"; then
        ((changes_applied++))
    fi

    if [[ $changes_applied -gt 0 ]]; then
        msg_ok "Subscription banner removed successfully."
    else
        msg_warn "Patches may not have been applied correctly. Please verify manually."
    fi

    register_tool "subscription_banner" true
}


   

# ==========================================================


configure_time_sync() {
    msg_info "$(translate "Configuring system time settings...")"

    this_ip=$(dig +short myip.opendns.com @resolver1.opendns.com)
    if [ -z "$this_ip" ]; then
        msg_warn "$(translate "Failed to obtain public IP address")"
        timezone="UTC"
    else

        timezone=$(curl -s "https://ipapi.co/${this_ip}/timezone")
        if [ -z "$timezone" ]; then
            msg_warn "$(translate "Failed to determine timezone from IP address")"
            timezone="UTC"
        else
            msg_ok "$(translate "Found timezone $timezone for IP $this_ip")"
        fi
    fi

    msg_info "$(translate "Enabling automatic time synchronization...")"
    if timedatectl set-ntp true; then
        msg_ok "$(translate "Time settings configured - Timezone:") $timezone"
        register_tool "time_sync" true
    else
        msg_error "$(translate "Failed to enable automatic time synchronization")"
    fi

}

# ==========================================================
skip_apt_languages() {
    msg_info "$(translate "Configuring APT to skip downloading additional languages...")"
    local default_locale=""
    
    if [ -f /etc/default/locale ]; then
        default_locale=$(grep '^LANG=' /etc/default/locale | cut -d= -f2 | tr -d '"')
    elif [ -f /etc/environment ]; then
        default_locale=$(grep '^LANG=' /etc/environment | cut -d= -f2 | tr -d '"')
    fi
    
    default_locale="${default_locale:-en_US.UTF-8}"
    local normalized_locale=$(echo "$default_locale" | tr 'A-Z' 'a-z' | sed 's/utf-8/utf8/;s/-/_/')
    
    if ! locale -a | grep -qi "^$normalized_locale$"; then
        if ! grep -qE "^${default_locale}[[:space:]]+UTF-8" /etc/locale.gen; then
            echo "$default_locale UTF-8" >> /etc/locale.gen
        fi
        locale-gen "$default_locale" > /dev/null 2>&1
    fi
    
    echo 'Acquire::Languages "none";' > /etc/apt/apt.conf.d/99-disable-translations
    
    msg_ok "$(translate "APT configured to skip additional languages")"
    register_tool "apt_languages" true
}

# ==========================================================
optimize_journald() {
    msg_info "$(translate "Limiting size and optimizing journald...")"
    NECESSARY_REBOOT=1
    
    cat <<EOF > /etc/systemd/journald.conf
[Journal]
Storage=persistent
SplitMode=none
RateLimitInterval=0
RateLimitIntervalSec=0
RateLimitBurst=0
ForwardToSyslog=no
ForwardToWall=yes
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
    
    cat <<EOF > /etc/sysctl.d/99-network.conf
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
    
    local interfaces_file="/etc/network/interfaces"
    if ! grep -q 'source /etc/network/interfaces.d/*' "$interfaces_file"; then
        echo "source /etc/network/interfaces.d/*" >> "$interfaces_file"
    fi
    
    msg_ok "$(translate "Network optimization completed")"
    register_tool "network_optimization" true
}

# ==========================================================
disable_rpc() {
    msg_info "$(translate "Disabling portmapper/rpcbind for security...")"
    
    systemctl disable rpcbind > /dev/null 2>&1
    systemctl stop rpcbind > /dev/null 2>&1
    
    msg_ok "$(translate "portmapper/rpcbind has been disabled and removed")"
    register_tool "disable_rpc" true
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

install_log2ram_auto_() {
    msg_info "$(translate "Checking if system disk is SSD or M.2...")"

    ROOT_PART=$(lsblk -no NAME,MOUNTPOINT | grep ' /$' | awk '{print $1}')
    SYSTEM_DISK=$(lsblk -no PKNAME /dev/$ROOT_PART 2>/dev/null)
    SYSTEM_DISK=${SYSTEM_DISK:-sda}

    if [[ "$SYSTEM_DISK" == nvme* || "$(cat /sys/block/$SYSTEM_DISK/queue/rotational 2>/dev/null)" == "0" ]]; then
        msg_ok "$(translate "System disk ($SYSTEM_DISK) is SSD or M.2. Proceeding with Log2RAM setup.")"
    else
        msg_warn "$(translate "System disk ($SYSTEM_DISK) is not SSD/M.2. Skipping Log2RAM installation.")"
        return 0
    fi

    # Clean up previous state
    rm -rf /tmp/log2ram
    rm -f /etc/systemd/system/log2ram*
    rm -f /etc/systemd/system/log2ram-daily.*
    rm -f /etc/cron.d/log2ram*
    rm -f /usr/sbin/log2ram
    rm -f /etc/log2ram.conf
    rm -f /usr/local/bin/log2ram-check.sh
    rm -rf /var/log.hdd
    systemctl daemon-reexec >/dev/null 2>&1
    systemctl daemon-reload >/dev/null 2>&1

    msg_info "$(translate "Installing log2ram from GitHub...")"

    if ! command -v git >/dev/null 2>&1; then
    apt-get update -qq >/dev/null 2>&1
    apt-get install -y git >/dev/null 2>&1
    fi

    git clone https://github.com/azlux/log2ram.git /tmp/log2ram >/dev/null 2>>/tmp/log2ram_install.log
    cd /tmp/log2ram || return 1
    bash install.sh >>/tmp/log2ram_install.log 2>&1

    if [[ -f /etc/log2ram.conf ]] && systemctl list-units --all | grep -q log2ram; then
        msg_ok "$(translate "Log2RAM installed successfully")"
    else
        msg_error "$(translate "Failed to install Log2RAM. See /tmp/log2ram_install.log")"
        return 1
    fi

    # Detect RAM
    RAM_SIZE_GB=$(free -g | awk '/^Mem:/{print $2}')
    [[ -z "$RAM_SIZE_GB" || "$RAM_SIZE_GB" -eq 0 ]] && RAM_SIZE_GB=4

    if (( RAM_SIZE_GB <= 8 )); then
        LOG2RAM_SIZE="128M"
        CRON_HOURS=1
    elif (( RAM_SIZE_GB <= 16 )); then
        LOG2RAM_SIZE="256M"
        CRON_HOURS=3
    else
        LOG2RAM_SIZE="512M"
        CRON_HOURS=6
    fi

    msg_ok "$(translate "Detected RAM:") $RAM_SIZE_GB GB — $(translate "Log2RAM size set to:") $LOG2RAM_SIZE"

    sed -i "s/^SIZE=.*/SIZE=$LOG2RAM_SIZE/" /etc/log2ram.conf
    rm -f /etc/cron.hourly/log2ram
    echo "0 */$CRON_HOURS * * * root /usr/sbin/log2ram write" > /etc/cron.d/log2ram
    msg_ok "$(translate "log2ram write scheduled every") $CRON_HOURS $(translate "hour(s)")"

    cat << 'EOF' > /usr/local/bin/log2ram-check.sh
#!/bin/bash
CONF_FILE="/etc/log2ram.conf"
LIMIT_KB=$(grep '^SIZE=' "$CONF_FILE" | cut -d'=' -f2 | tr -d 'M')000
USED_KB=$(df /var/log --output=used | tail -1)
THRESHOLD=$(( LIMIT_KB * 90 / 100 ))
if (( USED_KB > THRESHOLD )); then
    /usr/sbin/log2ram write
fi
EOF

    chmod +x /usr/local/bin/log2ram-check.sh
    echo "*/5 * * * * root /usr/local/bin/log2ram-check.sh" > /etc/cron.d/log2ram-auto-sync
    msg_ok "$(translate "Auto-sync enabled when /var/log exceeds 90% of") $LOG2RAM_SIZE"


    register_tool "log2ram" true
}




install_log2ram_auto() {
    msg_info "$(translate "Checking if system disk is SSD or M.2...")"

    ROOT_PART=$(lsblk -no NAME,MOUNTPOINT | grep ' /$' | awk '{print $1}')
    SYSTEM_DISK=$(lsblk -no PKNAME /dev/$ROOT_PART 2>/dev/null)
    SYSTEM_DISK=${SYSTEM_DISK:-sda}

    if [[ "$SYSTEM_DISK" == nvme* || "$(cat /sys/block/$SYSTEM_DISK/queue/rotational 2>/dev/null)" == "0" ]]; then
        msg_ok "$(translate "System disk ($SYSTEM_DISK) is SSD or M.2. Proceeding with Log2RAM setup.")"
    else
        msg_warn "$(translate "System disk ($SYSTEM_DISK) is not SSD/M.2. Skipping Log2RAM installation.")"
        return 0
    fi


    if [[ -f /etc/log2ram.conf ]] && command -v log2ram >/dev/null 2>&1 && systemctl list-units --all | grep -q log2ram; then
        msg_ok "$(translate "Log2RAM is already installed and configured correctly.")"
        register_tool "log2ram" true
        return 0
    fi
    
    msg_info "$(translate "Log2RAM proceeding with installation...")"
    

    if [[ -d /tmp/log2ram ]]; then
        rm -rf /tmp/log2ram
    fi
    

    [[ -f /etc/systemd/system/log2ram.service ]] && rm -f /etc/systemd/system/log2ram*
    [[ -f /etc/systemd/system/log2ram-daily.service ]] && rm -f /etc/systemd/system/log2ram-daily.*
    [[ -f /etc/cron.d/log2ram ]] && rm -f /etc/cron.d/log2ram*
    [[ -f /usr/sbin/log2ram ]] && rm -f /usr/sbin/log2ram
    [[ -f /etc/log2ram.conf ]] && rm -f /etc/log2ram.conf
    [[ -f /usr/local/bin/log2ram-check.sh ]] && rm -f /usr/local/bin/log2ram-check.sh
    [[ -d /var/log.hdd ]] && rm -rf /var/log.hdd
    
    systemctl daemon-reexec >/dev/null 2>&1 || true
    systemctl daemon-reload >/dev/null 2>&1 || true
    
    

    if ! command -v git >/dev/null 2>&1; then
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y git >/dev/null 2>&1
        msg_ok "$(translate "Git installed successfully")"
    fi
    
    if ! git clone https://github.com/azlux/log2ram.git /tmp/log2ram >/dev/null 2>>/tmp/log2ram_install.log; then
        msg_error "$(translate "Failed to clone log2ram repository. Check /tmp/log2ram_install.log")"
        return 1
    fi
    
    cd /tmp/log2ram || {
        msg_error "$(translate "Failed to access log2ram directory")"
        return 1
    }
    
    if ! bash install.sh >>/tmp/log2ram_install.log 2>&1; then
        msg_error "$(translate "Failed to run log2ram installer. Check /tmp/log2ram_install.log")"
        return 1
    fi
    

    if [[ -f /etc/log2ram.conf ]] && command -v log2ram >/dev/null 2>&1; then
        msg_ok "$(translate "Log2RAM installed successfully")"
    else
        msg_error "$(translate "Log2RAM installation verification failed. Check /tmp/log2ram_install.log")"
        return 1
    fi
    

    RAM_SIZE_GB=$(free -g | awk '/^Mem:/{print $2}')
    [[ -z "$RAM_SIZE_GB" || "$RAM_SIZE_GB" -eq 0 ]] && RAM_SIZE_GB=4
    
    if (( RAM_SIZE_GB <= 8 )); then
        LOG2RAM_SIZE="128M"
        CRON_HOURS=1
    elif (( RAM_SIZE_GB <= 16 )); then
        LOG2RAM_SIZE="256M"
        CRON_HOURS=3
    else
        LOG2RAM_SIZE="512M"
        CRON_HOURS=6
    fi
    
    msg_ok "$(translate "Detected RAM:") $RAM_SIZE_GB GB — $(translate "Log2RAM size set to:") $LOG2RAM_SIZE"
    

    sed -i "s/^SIZE=.*/SIZE=$LOG2RAM_SIZE/" /etc/log2ram.conf
    

    rm -f /etc/cron.hourly/log2ram
    echo "0 */$CRON_HOURS * * * root /usr/sbin/log2ram write" > /etc/cron.d/log2ram
    msg_ok "$(translate "log2ram write scheduled every") $CRON_HOURS $(translate "hour(s)")"
    

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
    clear
    show_proxmenux_logo
    msg_title "$(translate "ProxMenux Optimization Post-Installation")"
    
    ensure_tools_json
    
    apt_upgrade
    remove_subscription_banner
    configure_time_sync
    skip_apt_languages
    optimize_journald
    optimize_logrotate
    increase_system_limits
    configure_entropy
    optimize_memory_settings
    configure_kernel_panic
    force_apt_ipv4
    apply_network_optimizations
    disable_rpc
    customize_bashrc
    install_log2ram_auto
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
