#!/bin/bash
# ==========================================================
# Universal Proxmox VE Update Script
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
    if ! source <(curl -s "$REPO_URL/global/common-functions.sh"); then
        return 1
    fi
}

update_proxmox() {
    local start_time=$(date +%s)
    local log_file="/var/log/proxmox-update-$(date +%Y%m%d-%H%M%S).log"
    

    download_common_functions
    

    local pve_info=$(get_pve_info)
    local pve_full_version=$(echo "$pve_info" | cut -d'|' -f1)
    local pve_major=$(echo "$pve_info" | cut -d'|' -f2)
    local current_codename=$(echo "$pve_info" | cut -d'|' -f3)
    local target_codename=$(echo "$pve_info" | cut -d'|' -f4)
    
    clear
    show_proxmenux_logo
    echo -e
    msg_title "$(translate "Proxmox VE ${pve_major}.x System Update")"
    msg_info2 "$(translate "Detected: Proxmox VE ${pve_major}.x (Current: $current_codename, Target: $target_codename)")"
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


    local changes_made=$(configure_repositories "$pve_major" "$current_codename" "$target_codename")
    

    cleanup_duplicate_repos "$target_codename"


    msg_info "$(translate "Updating package lists...")"
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
                msg_error "$(translate "Failed to update package lists")"
                return 1
            fi
        else
            msg_error "$(translate "Failed to update package lists")"
            return 1
        fi
    fi


    if [ "$pve_major" -ge 9 ] 2>/dev/null; then
        msg_info "$(translate "Verifying Proxmox VE ${pve_major}.x repositories...")"
        if apt policy 2>/dev/null | grep -q "${target_codename}.*pve-no-subscription"; then
            msg_ok "$(translate "Proxmox VE ${pve_major}.x repositories verified")"
        else
            msg_warn "$(translate "Proxmox VE ${pve_major}.x repositories verification inconclusive, continuing...")"
        fi
    fi


    local available_pve_version=$(get_available_pve_version)
    local upgradable=$(apt list --upgradable 2>/dev/null | grep -c "upgradable")
    local security_updates=$(apt list --upgradable 2>/dev/null | grep -c "security")


    if ! show_update_menu "$pve_major" "$pve_full_version" "$available_pve_version" "$upgradable" "$security_updates"; then
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
    if [ "$pve_major" -ge 9 ] 2>/dev/null; then
        apt-get install pv -y > /dev/null 2>&1
    fi

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


    lvm_repair_check


    perform_final_cleanup


    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))

    echo ""
    echo -e "${TAB}${BGN}$(translate "=== PVE ${pve_major} UPDATE COMPLETED ===")${CL}"
    echo -e "${TAB}${GN}$(translate "Duration")${CL}: ${DGN}${minutes}m ${seconds}s${CL}"
    echo -e "${TAB}${GN}$(translate "Log file")${CL}: ${DGN}$log_file${CL}"
    echo -e "${TAB}${GN}$(translate "Packages upgraded")${CL}: ${DGN}$upgradable${CL}"
    echo -e "${TAB}${GN}$(translate "Proxmox VE")${CL}: ${DGN}${pve_major}.x (Debian $target_codename)${CL}"
    echo ""

    msg_ok "$(translate "Proxmox VE ${pve_major}.x system update completed successfully")"


}


if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    update_proxmox
fi
