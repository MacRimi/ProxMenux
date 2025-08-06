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
    local common_file="$BASE_DIR/common-functions.sh"
    
    if [[ ! -f "$common_file" ]]; then
        if ! curl -s "$REPO_URL/global/common-functions.sh" -o "$common_file"; then
            return 1
        fi
    fi

    source "$common_file"
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

    clear
    show_proxmenux_logo
    echo -e
    msg_title "$(translate "Proxmox VE 8.x System Update")"
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
        msg_info "$(translate "Disabling enterprise Proxmox repository...")"
        sed -i "s/^deb/#deb/g" /etc/apt/sources.list.d/pve-enterprise.list
        msg_ok "$(translate "Enterprise Proxmox repository disabled")"
        changes_made=true
    fi

    if [ -f /etc/apt/sources.list.d/ceph.list ] && grep -q "^deb" /etc/apt/sources.list.d/ceph.list; then
        msg_info "$(translate "Disabling enterprise Proxmox Ceph repository...")"
        sed -i "s/^deb/#deb/g" /etc/apt/sources.list.d/ceph.list
        msg_ok "$(translate "Enterprise Proxmox Ceph repository disabled")"
        changes_made=true
    fi


    if [ ! -f /etc/apt/sources.list.d/pve-public-repo.list ] || ! grep -q "pve-no-subscription" /etc/apt/sources.list.d/pve-public-repo.list; then
        msg_info "$(translate "Enabling free public Proxmox repository...")"
        echo "deb http://download.proxmox.com/debian/pve $OS_CODENAME pve-no-subscription" > /etc/apt/sources.list.d/pve-public-repo.list
        msg_ok "$(translate "Free public Proxmox repository enabled")"
        changes_made=true
    fi


    local sources_file="/etc/apt/sources.list"
    cp "$sources_file" "${sources_file}.backup.$(date +%Y%m%d_%H%M%S)"


    if grep -q -E "(debian-security -security|debian main$|debian -updates)" "$sources_file"; then
        msg_info "$(translate "Cleaning malformed repository entries...")"
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


    cleanup_duplicate_repos "$OS_CODENAME"


    msg_info "$(translate "Updating package lists...")"
    if apt-get update > "$log_file" 2>&1; then
        msg_ok "$(translate "Package lists updated successfully")"
    else
        msg_error "$(translate "Failed to update package lists. Check log: $log_file")"
        return 1
    fi


    local current_pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    local available_pve_version=$(get_available_pve_version 8 "$OS_CODENAME")
    local upgradable=$(apt list --upgradable 2>/dev/null | grep -c "upgradable")
    local security_updates=$(apt list --upgradable 2>/dev/null | grep -c "security")


    if ! show_update_menu "$current_pve_version" "$available_pve_version" "$upgradable" "$security_updates"; then
        msg_info2 "$(translate "Update cancelled by user")"
        perform_final_cleanup
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 0
    fi


    msg_info "$(translate "Removing conflicting utilities...")"
    local conflicting_packages=$(dpkg -l 2>/dev/null | grep -E "^ii.*(ntp|openntpd|systemd-timesyncd)" | awk '{print $2}')
    if [ -n "$conflicting_packages" ]; then
        DEBIAN_FRONTEND=noninteractive apt-get -y purge $conflicting_packages >> "$log_file" 2>&1
        msg_ok "$(translate "Conflicting utilities removed")"
    fi


    msg_info "$(translate "Performing system upgrade...")"
    if DEBIAN_FRONTEND=noninteractive apt-get -y \
        -o Dpkg::Options::='--force-confdef' \
        -o Dpkg::Options::='--force-confold' \
        dist-upgrade >> "$log_file" 2>&1; then
        msg_ok "$(translate "System upgrade completed successfully")"
    else
        msg_error "$(translate "System upgrade failed. Check log: $log_file")"
        return 1
    fi


    msg_info "$(translate "Installing essential Proxmox packages...")"
    local essential_packages=("zfsutils-linux" "proxmox-backup-restore-image" "chrony")
    local missing_packages=()
     
    for package in "${essential_packages[@]}"; do
        if ! dpkg -l 2>/dev/null | grep -q "^ii  $package "; then
            missing_packages+=("$package")
        fi
    done

    if [ ${#missing_packages[@]} -gt 0 ]; then
        DEBIAN_FRONTEND=noninteractive apt-get -y install "${missing_packages[@]}" >> "$log_file" 2>&1
        msg_ok "$(translate "Essential Proxmox packages installed")"
    fi
    cleanup

    lvm_repair_check


    perform_final_cleanup


    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))


    echo -e "${TAB}${BGN}$(translate "=== PVE 8 UPDATE COMPLETED ===")${CL}"
    echo -e "${TAB}${GN}$(translate "Duration")${CL}: ${DGN}${minutes}m ${seconds}s${CL}"
    echo -e "${TAB}${GN}$(translate "Log file")${CL}: ${DGN}$log_file${CL}"
    echo -e "${TAB}${GN}$(translate "Packages upgraded")${CL}: ${DGN}$upgradable${CL}"
    echo -e "${TAB}${GN}$(translate "Proxmox VE")${CL}: ${DGN}8.x (Debian $OS_CODENAME)${CL}"

    msg_ok "$(translate "Proxmox VE 8 system update completed successfully")"



}


if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    update_pve8
fi
