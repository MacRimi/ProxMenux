#!/bin/bash
# ==========================================================
# Proxmox VE Update Script
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

update_pve9() {
    local pve_version
    local start_time=$(date +%s)
    local log_file="/var/log/proxmox-update-$(date +%Y%m%d-%H%M%S).log"
    local changes_made=false
    local OS_CODENAME="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs)"
    local TARGET_CODENAME="trixie"
    
    if [ -z "$OS_CODENAME" ]; then
        OS_CODENAME=$(lsb_release -cs 2>/dev/null || echo "trixie")
    fi

    download_common_functions


    msg_info2 "$(translate "Detected: Proxmox VE $pve_version (Current: $OS_CODENAME, Target: $TARGET_CODENAME)")"
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


disable_sources_repo() {
    local file="$1"
    if [[ -f "$file" ]]; then
        sed -i ':a;/^\n*$/{$d;N;ba}' "$file"

        if grep -q "^Enabled:" "$file"; then
            sed -i 's/^Enabled:.*$/Enabled: false/' "$file"
        else
            echo "Enabled: false" >> "$file"
        fi

        if ! grep -q "^Types: " "$file"; then
            msg_warn "$(translate "Malformed .sources file detected, removing: $(basename "$file")")"
            rm -f "$file"
        fi
        return 0
    fi
    return 1
}




    if disable_sources_repo "/etc/apt/sources.list.d/pve-enterprise.sources"; then
        msg_ok "$(translate "Enterprise Proxmox repository disabled")"
        changes_made=true
    fi

    if disable_sources_repo "/etc/apt/sources.list.d/ceph.sources"; then
        msg_ok "$(translate "Enterprise Proxmox Ceph repository disabled")"
        changes_made=true
    fi

    for legacy_file in /etc/apt/sources.list.d/pve-public-repo.list \
                       /etc/apt/sources.list.d/pve-install-repo.list \
                       /etc/apt/sources.list.d/debian.list; do
        if [[ -f "$legacy_file" ]]; then
            rm -f "$legacy_file"
            msg_ok "$(translate "Removed legacy repository: $(basename "$legacy_file")")"
        fi
    done


    if [[ -f /etc/apt/sources.list.d/debian.sources ]]; then
        rm -f /etc/apt/sources.list.d/debian.sources
        msg_ok "$(translate "Old debian.sources file removed to prevent duplication")"
    fi


    msg_info "$(translate "Creating Proxmox VE 9.x no-subscription repository...")"
    cat > /etc/apt/sources.list.d/proxmox.sources << EOF
Enabled: true
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: ${TARGET_CODENAME}
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
    msg_ok "$(translate "Proxmox VE 9.x no-subscription repository created")"
    changes_made=true



    msg_info "$(translate "Creating Debian ${TARGET_CODENAME} sources file...")"
    cat > /etc/apt/sources.list.d/debian.sources << EOF
Types: deb
URIs: http://deb.debian.org/debian/
Suites: ${TARGET_CODENAME} ${TARGET_CODENAME}-updates
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://security.debian.org/debian-security/
Suites: ${TARGET_CODENAME}-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF



    msg_ok "$(translate "Debian repositories configured for $TARGET_CODENAME")"

    local firmware_conf="/etc/apt/apt.conf.d/no-firmware-warnings.conf"
    if [ ! -f "$firmware_conf" ]; then
        msg_info "$(translate "Disabling non-free firmware warnings...")"
        echo 'APT::Get::Update::SourceListWarnings::NonFreeFirmware "false";' > "$firmware_conf"
        msg_ok "$(translate "Non-free firmware warnings disabled")"
    fi

    update_output=$(apt-get update 2>&1)
    update_exit_code=$?

    if [ $update_exit_code -eq 0 ]; then
        msg_ok "$(translate "Package lists updated successfully")"
    else
        if echo "$update_output" | grep -q "NO_PUBKEY\|GPG error"; then
            msg_info "$(translate "Fixing GPG key issues...")"
            apt-key adv --keyserver keyserver.ubuntu.com --recv-keys $(echo "$update_output" | grep "NO_PUBKEY" | sed 's/.*NO_PUBKEY //' | head -1) 2>/dev/null
            if apt-get update > "$log_file" 2>&1; then
                msg_ok "$(translate "Package lists updated after GPG fix")"
            else
                msg_error "$(translate "Failed to update package lists. Check log: $log_file")"
                return 1
            fi
        elif echo "$update_output" | grep -q "404\|Failed to fetch"; then
            msg_warn "$(translate "Some repositories are not available, continuing with available ones...")"
        else
            msg_error "$(translate "Failed to update package lists. Check log: $log_file")"
            echo "Error details: $update_output"
            return 1
        fi
    fi



    if apt policy 2>/dev/null | grep -q "${TARGET_CODENAME}.*pve-no-subscription"; then
        msg_ok "$(translate "Proxmox VE 9.x repositories verified")"
    else
        msg_warn "$(translate "Proxmox VE 9.x repositories verification inconclusive, continuing...")"
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

    msg_info "$(translate "Cleaning up unused time synchronization services...")"

    if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' purge ntp openntpd systemd-timesyncd > /dev/null 2>&1; then
        msg_ok "$(translate "Old time services removed successfully")"
    else
        msg_warn "$(translate "Some old time services could not be removed (not installed)")"
    fi



    msg_info "$(translate "Updating packages...")"
    apt-get install pv -y > /dev/null 2>&1
    msg_ok "$(translate "Packages updated successfully")"
    
    tput sc
    
    DEBIAN_FRONTEND=noninteractive apt-get -y \
        -o Dpkg::Options::='--force-confdef' \
        -o Dpkg::Options::='--force-confold' \
        dist-upgrade 2>&1 | while IFS= read -r line; do
    
        echo "$line" >> "$log_file"
    
        if [[ "$line" =~ \[[#=\-]+\]\ *[0-9]{1,3}% ]]; then
            continue
        fi
    
        if [[ "$line" =~ ^(Setting\ up|Unpacking|Preparing\ to\ unpack|Processing\ triggers\ for) ]]; then
            package_name=$(echo "$line" | sed -E 's/.*(Setting up|Unpacking|Preparing to unpack|Processing triggers for) ([^ :]+).*/\2/')
            [ -z "$package_name" ] && package_name="$(translate "Unknown")"
    
            row=$(( $(tput lines) - 6 ))
            tput cup $row 0; printf "%s\n" "$(translate "Installing packages...")"
            tput cup $((row + 1)) 0; printf "%s\n" "──────────────────────────────────────────────"
            tput cup $((row + 2)) 0; printf "%s %s\n" "$(translate "Package:")" "$package_name"
            tput cup $((row + 3)) 0; printf "%s\n" "Progress: [                                                  ] 0%"
            tput cup $((row + 4)) 0; printf "%s\n" "──────────────────────────────────────────────"
    
            for i in $(seq 1 10); do
                sleep 0.1
                progress=$((i * 10))
                tput cup $((row + 3)) 9
                printf "[%-50s] %3d%%" "$(printf "#%.0s" $(seq 1 $((progress/2))))" "$progress"
            done
        fi
    done
    
    tput rc
    tput ed
    
    upgrade_exit_code=${PIPESTATUS[0]}




    if [ $upgrade_exit_code -eq 0 ]; then
        msg_ok "$(translate "System upgrade completed successfully")"
    else
        msg_error "$(translate "System upgrade failed. Check log: $log_file")"
        return 1
    fi


    msg_info "$(translate "Installing essential Proxmox packages...")"
    local additional_packages="zfsutils-linux proxmox-backup-restore-image chrony"
    
    if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install $additional_packages >> "$log_file" 2>&1; then
        msg_ok "$(translate "Essential Proxmox packages installed")"
    else
        msg_warn "$(translate "Some essential Proxmox packages may not have been installed")"
    fi

    lvm_repair_check
    cleanup_duplicate_repos

    #msg_info "$(translate "Performing system cleanup...")"
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

    msg_ok "$(translate "Proxmox VE 9.x configuration completed.")"
    
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    update_pve9
fi
