#!/bin/bash
# ==========================================================
# Proxmox VE Update Script - Improved Version (with apt progress)
# ==========================================================

# Configuration
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
TOOLS_JSON="/usr/local/share/proxmenux/installed_tools.json"
APT_ENV="env DEBIAN_FRONTEND=noninteractive LC_ALL=C LANG=C"

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
    if ! source "$LOCAL_SCRIPTS/global/common-functions.sh"; then
        return 1
    fi
}

update_pve9() {
    local pve_version
    pve_version=$(pveversion | awk -F'/' '{print $2}' | cut -d'-' -f1)
    local start_time
    start_time=$(date +%s)
    local log_file="/var/log/proxmox-update-$(date +%Y%m%d-%H%M%S).log"
    local changes_made=false
    local OS_CODENAME
    OS_CODENAME="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs)"
    local TARGET_CODENAME="trixie"
    
    local screen_capture="/tmp/proxmenux_screen_capture_$$.txt"
    
    if [ -z "$OS_CODENAME" ]; then
        OS_CODENAME=$(lsb_release -cs 2>/dev/null || echo "trixie")
    fi

    download_common_functions

    {
        msg_info2 "$(translate "Detected: Proxmox VE $pve_version (Current: $OS_CODENAME, Target: $TARGET_CODENAME)")"
    } | tee -a "$screen_capture"


    local available_space
    available_space=$(df /var/cache/apt/archives | awk 'NR==2 {print int($4/1024)}')
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
        msg_ok "$(translate "Enterprise Proxmox repository disabled")" | tee -a "$screen_capture"
        changes_made=true
    fi

    if disable_sources_repo "/etc/apt/sources.list.d/ceph.sources"; then
        msg_ok "$(translate "Enterprise Proxmox Ceph repository disabled")" | tee -a "$screen_capture"
        changes_made=true
    fi

    for legacy_file in /etc/apt/sources.list.d/pve-public-repo.list \
                       /etc/apt/sources.list.d/pve-install-repo.list \
                       /etc/apt/sources.list.d/debian.list; do
        if [[ -f "$legacy_file" ]]; then
            rm -f "$legacy_file"
            msg_ok "$(translate "Removed legacy repository: $(basename "$legacy_file")")" | tee -a "$screen_capture"
        fi
    done

    if [[ -f /etc/apt/sources.list.d/debian.sources ]]; then
        rm -f /etc/apt/sources.list.d/debian.sources
        msg_ok "$(translate "Old debian.sources file removed to prevent duplication")" | tee -a "$screen_capture"
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
    msg_ok "$(translate "Proxmox VE 9.x no-subscription repository created")" | tee -a "$screen_capture"
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

    # UPDATE: no progress bar here (dpkg is not involved); capture output to parse errors
    update_output=$(apt-get update 2>&1)
    update_exit_code=$?

    if [ $update_exit_code -eq 0 ]; then
        msg_ok "$(translate "Package lists updated successfully")" | tee -a "$screen_capture"
    else
        # Handle common apt errors
        if echo "$update_output" | grep -Eq "NO_PUBKEY|GPG error"; then

            # Extract first missing key (NO_PUBKEY ABCDEF... pattern)
            key=$(echo "$update_output" | sed -n 's/.*NO_PUBKEY \([0-9A-F]\{8,40\}\).*/\1/p' | head -1)

            if [ -n "$key" ]; then
                mkdir -p /etc/apt/keyrings

                if command -v gpg >/dev/null 2>&1; then
                    # Modern approach: receive -> export -> dearmor into /etc/apt/keyrings/<KEY>.gpg
                    if gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "$key" \
                    && gpg --batch --export "$key" | gpg --dearmor -o "/etc/apt/keyrings/${key}.gpg"; then
                        msg_ok "$(translate "Imported missing GPG key: $key")"
                    else
                        msg_warn "$(translate "Keyrings method failed; trying apt-key fallback")"
                        apt-key adv --keyserver keyserver.ubuntu.com --recv-keys "$key" >/dev/null 2>&1 || true
                    fi
                else
                    # Fallback for minimal systems without gpg installed
                    msg_warn "$(translate "gpg not found; trying apt-key fallback")"
                    apt-key adv --keyserver keyserver.ubuntu.com --recv-keys "$key" >/dev/null 2>&1 || true
                fi
            fi

            # Retry update after importing the key
            if apt-get update > "$log_file" 2>&1; then
                msg_ok "$(translate "Package lists updated after GPG fix")" | tee -a "$screen_capture"
            else
                msg_error "$(translate "Failed to update package lists. Check log: $log_file")"
                return 1
            fi

        elif echo "$update_output" | grep -Eq "404|Failed to fetch"; then
            msg_warn "$(translate "Some repositories are not available, continuing with available ones...")"
        else
            msg_error "$(translate "Failed to update package lists. Check log: $log_file")"
            echo "Error details: $update_output"
            return 1
        fi
    fi

    if apt policy 2>/dev/null | grep -q "${TARGET_CODENAME}.*pve-no-subscription"; then
        msg_ok "$(translate "Proxmox VE $pve_version repositories verified")" | tee -a "$screen_capture"
    else
        msg_warn "$(translate "Proxmox VE $pve_version repositories verification inconclusive, continuing...")"
    fi

    local current_pve_version
    current_pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    local available_pve_version
    available_pve_version=$(apt-cache policy pve-manager 2>/dev/null | grep -oP 'Candidate: \K[0-9]+\.[0-9]+\.[0-9]+' | head -1)


    local upgradable
    upgradable=$($APT_ENV apt list --upgradable 2>/dev/null \
        | sed '1d' \
        | sed '/^\s*$/d' \
        | wc -l)

    local security_updates
    security_updates=$($APT_ENV apt list --upgradable 2>/dev/null \
        | sed '1d' \
        | grep -ci '\-security')


    show_update_menu() {
        local current_version="$1"
        local target_version="$2"
        local upgradable_count="$3"
        local security_count="$4"

        local menu_text
        menu_text="$(translate "System Update Information")\n\n"
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

    clear
    show_proxmenux_logo
    msg_title "$(translate "$SCRIPT_TITLE")"
    cat "$screen_capture"

    if [[ $MENU_RESULT -eq 1 ]]; then
        msg_info2 "$(translate "Update cancelled by user")"
        apt-get -y autoremove > /dev/null 2>&1 || true
        apt-get -y autoclean > /dev/null 2>&1 || true
        rm -f "$screen_capture"
        return 0
    elif [[ $MENU_RESULT -eq 2 ]]; then
        msg_ok "$(translate "System is already up to date. No update needed.")"
        apt-get -y autoremove > /dev/null 2>&1 || true
        apt-get -y autoclean > /dev/null 2>&1 || true
        rm -f "$screen_capture"
        return 0
    fi

    msg_info "$(translate "Cleaning up unused time synchronization services...")"
    if /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' purge ntp openntpd systemd-timesyncd > /dev/null 2>&1; then
        msg_ok "$(translate "Old time services removed successfully")"
    else
        msg_warn "$(translate "Some old time services could not be removed (not installed)")"
    fi

    echo -e


    DEBIAN_FRONTEND=noninteractive apt -y \
        -o Dpkg::Options::='--force-confdef' \
        -o Dpkg::Options::='--force-confold' \
        full-upgrade 2> >(tee -a "$log_file" >&2)

    upgrade_exit_code=$?
    echo -e

    clear
    show_proxmenux_logo
    msg_title "$(translate "$SCRIPT_TITLE")"
    cat "$screen_capture"

    if [ $upgrade_exit_code -ne 0 ]; then
        msg_error "$(translate "System upgrade failed. Check log: $log_file")"
        rm -f "$screen_capture"
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

    apt-get -y autoremove > /dev/null 2>&1 || true
    apt-get -y autoclean > /dev/null 2>&1 || true
    msg_ok "$(translate "Cleanup finished")"

    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))

    echo -e "${TAB}${BGN}$(translate "====== PVE UPDATE COMPLETED ======")${CL}"
    echo -e "${TAB}${GN}⏱️  $(translate "Duration")${CL}: ${BL}${minutes}m ${seconds}s${CL}"
    echo -e "${TAB}${GN}📄 $(translate "Log file")${CL}: ${BL}$log_file${CL}"
    echo -e "${TAB}${GN}📦 $(translate "Packages upgraded")${CL}: ${BL}$upgradable${CL}"
    echo -e "${TAB}${GN}🖥️  $(translate "Proxmox VE")${CL}: ${BL}$available_pve_version (Debian $OS_CODENAME)${CL}"

    msg_ok "$(translate "Proxmox VE configuration completed.")"
    
    rm -f "$screen_capture"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    update_pve9
fi
