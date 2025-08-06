#!/bin/bash
# ==========================================================
# Common Functions for Proxmox Updates
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

lvm_repair_check() {
    msg_info "$(translate "Checking and repairing old LVM PV headers (if needed)...")"
    
    # Check if LVM tools are available
    if ! command -v pvs >/dev/null 2>&1; then
        msg_ok "$(translate "LVM tools not available, skipping LVM check")"
        register_tool "lvm_repair" true
        return
    fi
    
    pvs_output=$(LC_ALL=C pvs -v 2>&1 | grep "old PV header" || true)
    if [ -z "$pvs_output" ]; then
        msg_ok "$(translate "No PVs with old headers found.")"
        register_tool "lvm_repair" true
        return
    fi
    
    declare -A vg_map
    while read -r line; do
        pv=$(echo "$line" | grep -o '/dev/[^ ]*' || true)
        if [ -n "$pv" ]; then
            vg=$(pvs -o vg_name --noheadings "$pv" 2>/dev/null | awk '{print $1}' || true)
            if [ -n "$vg" ]; then
                vg_map["$vg"]=1
            fi
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
    register_tool "lvm_repair" true
}

cleanup_duplicate_repos() {
    local OS_CODENAME="$1"
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
    
    # Clean Proxmox repository files
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
    
    if [ $cleaned_count -gt 0 ]; then
        msg_ok "$(translate "Cleaned up $cleaned_count duplicate repositories")"
    fi
    
    apt update > /dev/null 2>&1
}

show_update_menu() {
    local current_version="$1"
    local target_version="$2"
    local upgradable_count="$3"
    local security_count="$4"
    
    # Build menu text
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
        return 1
    else
        menu_text+="$(translate "Do you want to proceed with the system update?")"
        if whiptail --title "$(translate "Proxmox Update")" --yesno "$menu_text" 18 70; then
            return 0
        else
            return 1
        fi
    fi
}

get_available_pve_version() {
    local current_major="$1"
    local os_codename="$2"
    
    local available_version=""
    
    if [ "$current_major" -eq 8 ]; then
        available_version=$(apt-cache policy pve-manager 2>/dev/null | grep "Candidate:" | awk '{print $2}' | grep -oP '\d+\.\d+\.\d+' || echo "")
    elif [ "$current_major" -eq 9 ]; then
        available_version=$(apt-cache policy pve-manager 2>/dev/null | grep "Candidate:" | awk '{print $2}' | grep -oP '\d+\.\d+\.\d+' || echo "")
    fi
    
    echo "$available_version"
}

perform_final_cleanup() {
    msg_info "$(translate "Performing final system cleanup...")"
    
    apt-get -y autoremove > /dev/null 2>&1
    
    apt-get -y autoclean > /dev/null 2>&1
    
    find /var/cache/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/lib/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    
    msg_ok "$(translate "Final cleanup completed")"
}
