#!/bin/bash
# ==========================================================
# Proxmox VE 8.x Update Script
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

ensure_tools_json() {
    [ -f "$TOOLS_JSON" ] || echo "{}" > "$TOOLS_JSON"
}

register_tool() {
    local tool="$1"
    local state="$2"
    ensure_tools_json
    jq --arg t "$tool" --argjson v "$state" '.[$t]=$v' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
}

download_common_functions() {
    if ! source <(curl -s "$REPO_URL/scripts/global/common-functions.sh"); then
        return 1
    fi
}

update_pve8() {
    local start_time=$(date +%s)
    local log_file="/var/log/proxmox-update-$(date +%Y%m%d-%H%M%S).log"
    local changes_made=false
    local OS_CODENAME="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs)"
    
    if [ -z "$OS_CODENAME" ]; then
        OS_CODENAME=$(lsb_release -cs 2>/dev/null || echo "bookworm")
    fi

    download_common_functions

    msg_info2 "$(translate "Detected: Proxmox VE 8.x (Debian $OS_CODENAME)")"
    echo

    local available_space=$(df /var/cache/apt/archives | awk 'NR==2 {print int($4/1024)}')
    if [ "$available_space" -lt 1024 ]; then
        msg_error "$(translate "Insufficient disk space. Available: ${available_space}MB")"
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi

    if ! ping -c 1 download.proxmox.com >/dev/null 2>&1; then
        msg_error "$(translate "Cannot reach Proxmox repositories")"
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi


    if [ -f /etc/apt/sources.list.d/pve-enterprise.list ] && grep -q "^deb" /etc/apt/sources.list.d/pve-enterprise.list; then
        sed -i "s/^deb/#deb/g" /etc/apt/sources.list.d/pve-enterprise.list
        msg_ok "$(translate "Enterprise Proxmox repository disabled")"
        changes_made=true
    fi

    if [ -f /etc/apt/sources.list.d/ceph.list ] && grep -q "^deb" /etc/apt/sources.list.d/ceph.list; then
        sed -i "s/^deb/#deb/g" /etc/apt/sources.list.d/ceph.list
        msg_ok "$(translate "Enterprise Proxmox Ceph repository disabled")"
        changes_made=true
    fi


    if [ ! -f /etc/apt/sources.list.d/pve-public-repo.list ] || ! grep -q "pve-no-subscription" /etc/apt/sources.list.d/pve-public-repo.list; then
        echo "deb http://download.proxmox.com/debian/pve $OS_CODENAME pve-no-subscription" > /etc/apt/sources.list.d/pve-public-repo.list
        msg_ok "$(translate "Free public Proxmox repository enabled")"
        changes_made=true
    fi


    local sources_file="/etc/apt/sources.list"
    cp "$sources_file" "${sources_file}.backup.$(date +%Y%m%d_%H%M%S)"

    if grep -q -E "(debian-security -security|debian main$|debian -updates)" "$sources_file"; then
        sed -i '/^deb.*debian-security -security/d' "$sources_file"
        sed -i '/^deb.*debian main$/d' "$sources_file"
        sed -i '/^deb.*debian -updates/d' "$sources_file"
        changes_made=true
        msg_ok "$(translate "Malformed repository entries cleaned")"
    fi

    cat > "$sources_file" << EOF
# Debian $OS_CODENAME repositories
deb http://deb.debian.org/debian $OS_CODENAME main contrib non-free non-free-firmware
deb http://deb.debian.org/debian $OS_CODENAME-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security $OS_CODENAME-security main contrib non-free non-free-firmware
EOF

    msg_ok "$(translate "Debian repositories configured for $OS_CODENAME")"

    local firmware_conf="/etc/apt/apt.conf.d/no-firmware-warnings.conf"
    if [ ! -f "$firmware_conf" ]; then
        echo 'APT::Get::Update::SourceListWarnings::NonFreeFirmware "false";' > "$firmware_conf"
    fi

    cleanup_duplicate_repos

    msg_info "$(translate "Updating package lists...")"
    if apt-get update > "$log_file" 2>&1; then
        msg_ok "$(translate "Package lists updated successfully")"
    else
        msg_error "$(translate "Failed to update package lists. Check log: $log_file")"
        return 1
    fi

    local current_pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    local available_pve_version=$(apt-cache policy pve-manager 2>/dev/null | grep -oP 'Candidate: \K[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    local upgradable=$(apt list --upgradable 2>/dev/null | grep -c "upgradable")
    local security_updates=$(apt list --upgradable 2>/dev/null | grep -c "security")

    show_update_menu() {
        local current_version="$1"
        local target_version="$2"
        local upgradable_count="$3"
        local security_count="$4"

        local menu_text="$(translate "System Update Information")\n\n"
        menu_text+="$(translate "Current PVE Version"): $current_version\n"
        if [ -n "$target_version" ] && [ "$target_version" != "$current_version" ]; then
            menu_text+="$(translate "Available PVE Version"): $target_version\n"
        fi
        menu_text+="\n$(translate "Package Updates Available"): $upgradable_count\n"
        menu_text+="$(translate "Security Updates"): $security_count\n\n"

        if [ "$upgradable_count" -eq 0 ]; then
            menu_text+="$(translate "System is already up to date")"
            whiptail --title "$(translate "Update Status")" --msgbox "$menu_text" 15 70
            return 2
        else
            menu_text+="$(translate "Do you want to proceed with the system update?")"
            if whiptail --title "$(translate "Proxmox Update")" --yesno "$menu_text" 18 70; then
                return 0
            else
                return 1
            fi
        fi
    }

    show_update_menu "$current_pve_version" "$available_pve_version" "$upgradable" "$security_updates"
    MENU_RESULT=$?

    if [[ $MENU_RESULT -eq 1 ]]; then
        msg_info2 "$(translate "Update cancelled by user")"
        apt-get -y autoremove > /dev/null 2>&1 || true
        apt-get -y autoclean > /dev/null 2>&1 || true
        return 0
    elif [[ $MENU_RESULT -eq 2 ]]; then
        msg_ok "$(translate "System is already up to date. No update needed.")"
        apt-get -y autoremove > /dev/null 2>&1 || true
        apt-get -y autoclean > /dev/null 2>&1 || true
        return 0
    fi

    
    local conflicting_packages=$(dpkg -l 2>/dev/null | grep -E "^ii.*(ntp|openntpd|systemd-timesyncd)" | awk '{print $2}')
    if [ -n "$conflicting_packages" ]; then
        msg_info "$(translate "Removing conflicting utilities...")"
        DEBIAN_FRONTEND=noninteractive apt-get -y purge $conflicting_packages >> "$log_file" 2>&1
        msg_ok "$(translate "Conflicting utilities removed")"
    fi






    msg_info "$(translate "Performing packages upgrade...")"
    apt-get install pv -y > /dev/null 2>&1
    total_packages=$(apt-get -s dist-upgrade | grep "^Inst" | wc -l)
    msg_ok "$(translate "Packages upgrade successfull")"
   
    if [ "$total_packages" -eq 0 ]; then
        total_packages=1  
    fi

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

    lvm_repair_check
    cleanup_duplicate_repos

    msg_info "$(translate "Performing system cleanup...")"
    apt-get -y autoremove > /dev/null 2>&1 || true
    apt-get -y autoclean > /dev/null 2>&1 || true
    msg_ok "$(translate "Cleanup finished")"

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))

    echo -e "${TAB}${BGN}$(translate "====== PVE UPDATE COMPLETED ======")${CL}"
    echo -e "${TAB}${GN}⏱️  $(translate "Duration")${CL}: ${BL}${minutes}m ${seconds}s${CL}"
    echo -e "${TAB}${GN}📄 $(translate "Log file")${CL}: ${BL}$log_file${CL}"
    echo -e "${TAB}${GN}📦 $(translate "Packages upgraded")${CL}: ${BL}$upgradable${CL}"
    echo -e "${TAB}${GN}🖥️  $(translate "Proxmox VE")${CL}: ${BL}$target_version (Debian $OS_CODENAME)${CL}"



    msg_ok "$(translate "Proxmox VE 8 system update completed successfully")"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    update_pve8
fi
