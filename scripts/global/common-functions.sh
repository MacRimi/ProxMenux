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
        if vgck --updatemetadata "$vg" 2>/dev/null && vgchange -ay "$vg" 2>/dev/null; then
            msg_ok "$(translate "Metadata updated successfully for VG $vg")"
        else
            msg_warn "$(translate "Metadata update failed for VG $vg. Review manually.")"
        fi
    done
    
    msg_ok "$(translate "LVM PV headers check completed")"
    register_tool "lvm_repair" true
}


cleanup_duplicate_repos() {
    local target_codename="$1"
    
    msg_info "$(translate "Cleaning up duplicate repositories...")"
    
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
        msg_ok "$(translate "Cleaned up $cleaned_count duplicate/old repositories")"
    else
        msg_ok "$(translate "No duplicate repositories found")"
    fi
    
    apt update > /dev/null 2>&1
}


get_available_pve_version() {
    local available_version=$(apt-cache policy pve-manager 2>/dev/null | grep -oP 'Candidate: \K[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    
    if [ -n "$available_version" ]; then
        echo "$available_version"
    else

        pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+\.[0-9]+' | head -1
    fi
}


perform_final_cleanup() {
    msg_info "$(translate "Performing system cleanup...")"
    apt-get -y autoremove > /dev/null 2>&1
    apt-get -y autoclean > /dev/null 2>&1
    msg_ok "$(translate "Cleanup finished")"
}


configure_repositories() {
    local pve_major="$1"
    local current_codename="$2"
    local target_codename="$3"
    local changes_made=false
    
    msg_info "$(translate "Configuring Proxmox VE ${pve_major}.x repositories...")"
    

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
    

    if [ "$pve_major" -ge 9 ] 2>/dev/null; then

        [ -f /etc/apt/sources.list.d/pve-public-repo.list ] && rm -f /etc/apt/sources.list.d/pve-public-repo.list
        [ -f /etc/apt/sources.list.d/pve-install-repo.list ] && rm -f /etc/apt/sources.list.d/pve-install-repo.list
        
        msg_info "$(translate "Creating Proxmox VE ${pve_major}.x no-subscription repository...")"
        cat > /etc/apt/sources.list.d/proxmox.sources << EOF
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: ${target_codename}
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
        msg_ok "$(translate "Proxmox VE ${pve_major}.x no-subscription repository created")"
        changes_made=true
    else

        if [ ! -f /etc/apt/sources.list.d/pve-public-repo.list ] || ! grep -q "pve-no-subscription" /etc/apt/sources.list.d/pve-public-repo.list; then
            msg_info "$(translate "Enabling free public Proxmox repository...")"
            echo "deb http://download.proxmox.com/debian/pve $target_codename pve-no-subscription" > /etc/apt/sources.list.d/pve-public-repo.list
            msg_ok "$(translate "Free public Proxmox repository enabled")"
            changes_made=true
        fi
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
    

    if grep -q "ftp.es.debian.org" "$sources_file"; then
        sed -i 's|ftp.es.debian.org|deb.debian.org|g' "$sources_file"
        changes_made=true
    fi
    

    if [ "$current_codename" != "$target_codename" ]; then
        msg_info "$(translate "Updating Debian repositories from $current_codename to $target_codename...")"
        sed -i "s/$current_codename/$target_codename/g" "$sources_file"
        changes_made=true
    fi
    

    cat > "$sources_file" << EOF
# Debian $target_codename repositories
deb http://deb.debian.org/debian $target_codename main contrib non-free non-free-firmware
deb http://deb.debian.org/debian $target_codename-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security $target_codename-security main contrib non-free non-free-firmware
EOF
    
    msg_ok "$(translate "Debian repositories configured for $target_codename")"
    

    local firmware_conf="/etc/apt/apt.conf.d/no-firmware-warnings.conf"
    if [ ! -f "$firmware_conf" ]; then
        echo 'APT::Get::Update::SourceListWarnings::NonFreeFirmware "false";' > "$firmware_conf"
    fi
    
    echo "$changes_made"
}


show_update_menu() {
    local pve_major="$1"
    local current_version="$2"
    local available_version="$3"
    local upgradable="$4"
    local security_updates="$5"
    
    if [ "$upgradable" -eq 0 ]; then
        if command -v whiptail >/dev/null 2>&1; then
            whiptail --title "$(translate "System Status")" \
                --msgbox "$(translate "System is already up to date.\n\nCurrent PVE version: $current_version\nNo packages need updating.")" 12 60
        fi
        return 1  
    fi
    
 
    local menu_text="$(translate "Update Information:")
    
$(translate "Current PVE version"): $current_version"
    
   
    if [ "$available_version" != "$current_version" ] && [ -n "$available_version" ]; then
        menu_text="$menu_text
$(translate "Available PVE version"): $available_version"
    fi
    
    menu_text="$menu_text

$(translate "Packages to upgrade"): $upgradable
$(translate "Security updates"): $security_updates

$(translate "Do you want to proceed with the system update?")"
    
    if command -v whiptail >/dev/null 2>&1; then
        if whiptail --title "$(translate "Proxmox VE ${pve_major}.x System Update")" \
            --yesno "$menu_text" 16 70; then
            return 0  
        else
            return 1  
        fi
    else
       
        echo "$menu_text"
        echo
        read -p "$(translate "Continue with update? (y/N): ")" -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            return 0
        else
            return 1
        fi
    fi
}
