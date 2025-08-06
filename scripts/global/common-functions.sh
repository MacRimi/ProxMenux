#!/bin/bash
# ==========================================================
# Common Functions for Proxmox VE Scripts
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


get_pve_info() {
    local pve_full_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    local pve_major=$(echo "$pve_full_version" | cut -d. -f1)
    local os_codename="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs)"
    
    if [ -z "$os_codename" ]; then
        os_codename=$(lsb_release -cs 2>/dev/null)
    fi
    

    local target_codename
    if [ "$pve_major" -ge 9 ] 2>/dev/null; then
        target_codename="trixie"
    else
        target_codename="$os_codename"
        if [ -z "$target_codename" ]; then
            target_codename="bookworm"
        fi
    fi
    
    echo "$pve_full_version|$pve_major|$os_codename|$target_codename"
}


lvm_repair_check() {
    msg_info "$(translate "Checking and repairing old LVM PV headers (if needed)...")"
    
    if ! command -v pvs >/dev/null 2>&1; then
        msg_info "$(translate "LVM tools not available, skipping LVM check")"
        return
    fi
    
    pvs_output=$(LC_ALL=C pvs -v 2>&1 | grep "old PV header" || true)
    if [ -z "$pvs_output" ]; then
        msg_ok "$(translate "No PVs with old headers found.")"
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
        vgck --updatemetadata "$vg" 2>/dev/null
        vgchange -ay "$vg" 2>/dev/null
        if [ $? -ne 0 ]; then
            msg_warn "$(translate "Metadata update failed for VG $vg. Review manually.")"
        else
            msg_ok "$(translate "Metadata updated successfully for VG $vg")"
        fi
    done
    
    msg_ok "$(translate "LVM PV headers check completed")"
}


cleanup_duplicate_repos() {
    msg_info "$(translate "Cleaning up duplicate repositories...")"

    local cleaned_count=0
    local sources_file="/etc/apt/sources.list"


    if [[ -f "$sources_file" ]]; then
        local temp_file
        temp_file=$(mktemp)
        declare -A seen_repos

        while IFS= read -r line || [[ -n "$line" ]]; do
            if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then
                echo "$line" >> "$temp_file"
                continue
            fi

            if [[ "$line" =~ ^[[:space:]]*deb ]]; then
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
    fi


    local old_pve_files=(/etc/apt/sources.list.d/pve-*.list /etc/apt/sources.list.d/proxmox.list)

    for file in "${old_pve_files[@]}"; do
        if [[ -f "$file" ]]; then
            local base_name
            base_name=$(basename "$file" .list)
            local sources_equiv="/etc/apt/sources.list.d/${base_name}.sources"

            if [[ -f "$sources_equiv" ]] && grep -q "^Enabled: *true" "$sources_equiv"; then
                msg_info "$(translate "Removing old repository file: $(basename "$file")")"
                rm -f "$file"
                cleaned_count=$((cleaned_count + 1))
            fi
        fi
    done


    if [ "$cleaned_count" -gt 0 ]; then
        msg_ok "$(translate "Cleaned up $cleaned_count duplicate/old repositories")"
        apt-get update > /dev/null 2>&1 || true
    else
        msg_ok "$(translate "No duplicate repositories found")"
    fi
}

