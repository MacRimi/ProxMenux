#!/bin/bash
# ==========================================================
# ProxMenu CT - NFS Manager for Proxmox LXC (Simple + Universal)
# ==========================================================
# Based on ProxMenux by MacRimi
# ==========================================================
# Description:
# This script allows you to manage NFS shares inside Proxmox CTs:
# - Create NFS exports with universal sharedfiles group
# - View configured exports
# - Delete existing exports
# - Check NFS service status
# ==========================================================

# Configuration
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

# Load shared functions
SHARE_COMMON_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/scripts/global/share-common.func"
if ! source <(curl -s "$SHARE_COMMON_URL" 2>/dev/null); then
    msg_error "$(translate "Could not load shared functions. Script cannot continue.")"
    exit 1
fi

load_language
initialize_cache


select_privileged_lxc




setup_universal_sharedfiles_group() {
    local ctid="$1"
    
    msg_info "$(translate "Setting sharedfiles group with UID remapping...")"
    
    if ! pct exec "$ctid" -- getent group sharedfiles >/dev/null 2>&1; then
        pct exec "$ctid" -- groupadd -g 101000 sharedfiles
        msg_ok "$(translate "Created sharedfiles group (GID: 101000)")"
    else
        local current_gid=$(pct exec "$ctid" -- getent group sharedfiles | cut -d: -f3)
        if [[ "$current_gid" != "101000" ]]; then
            pct exec "$ctid" -- groupmod -g 101000 sharedfiles
            msg_ok "$(translate "Updated sharedfiles group to GID: 101000")"
        else
            msg_ok "$(translate "Sharedfiles group already exists (GID: 101000)")"
        fi
    fi
    

    local lxc_users=$(pct exec "$ctid" -- awk -F: '$3 >= 1000 && $3 < 65534 {print $1 ":" $3}' /etc/passwd)
    

    if [[ -n "$lxc_users" ]]; then
        msg_info "$(translate "Adding existing users to sharedfiles group...")"
        while IFS=: read -r username uid; do
            if [[ -n "$username" ]]; then
                pct exec "$ctid" -- usermod -a -G sharedfiles "$username" 2>/dev/null || true
                msg_ok "$(translate "Added user") $username (UID: $uid) $(translate "to sharedfiles group")"
            fi
        done <<< "$lxc_users"
    fi
    

    msg_info "$(translate "Creating UID remapping for unprivileged container compatibility...")"
    local remapped_count=0
    
    if [[ -n "$lxc_users" ]]; then
        while IFS=: read -r username uid; do
            if [[ -n "$uid" ]]; then
                local remapped_uid=$((uid + 100000))
                local remapped_username="remap_${uid}"
                

                if ! pct exec "$ctid" -- id "$remapped_username" >/dev/null 2>&1; then
                    pct exec "$ctid" -- useradd -u "$remapped_uid" -g sharedfiles -s /bin/false -M "$remapped_username" 2>/dev/null || true
                    msg_ok "$(translate "Created remapped user") $remapped_username (UID: $remapped_uid)"
                    ((remapped_count++))
                else

                    pct exec "$ctid" -- usermod -g sharedfiles "$remapped_username" 2>/dev/null || true
                fi
            fi
        done <<< "$lxc_users"
    fi
    

    local common_uids=(33 1000 1001 1002)  
    for base_uid in "${common_uids[@]}"; do
        local remapped_uid=$((base_uid + 100000))
        local remapped_username="remap_${base_uid}"
        
        if ! pct exec "$ctid" -- id "$remapped_username" >/dev/null 2>&1; then
            pct exec "$ctid" -- useradd -u "$remapped_uid" -g sharedfiles -s /bin/false -M "$remapped_username" 2>/dev/null || true
            msg_ok "$(translate "Created common remapped user") $remapped_username (UID: $remapped_uid)"
            ((remapped_count++))
        fi
    done
    
    msg_ok "$(translate "Universal sharedfiles group configured with") $remapped_count $(translate "remapped users")"
}




select_mount_point() {
    while true; do
        METHOD=$(whiptail --backtitle "ProxMenux" --title "$(translate "Select Folder")" \
            --menu "$(translate "How do you want to select the folder to export?")" 15 60 5 \
            "auto" "$(translate "Select from folders inside /mnt")" \
            "manual" "$(translate "Enter path manually")" \
            3>&1 1>&2 2>&3)
        
        if [[ $? -ne 0 ]]; then
            return 1
        fi

        case "$METHOD" in
            auto)
                DIRS=$(pct exec "$CTID" -- find /mnt -maxdepth 1 -mindepth 1 -type d 2>/dev/null)
                if [[ -z "$DIRS" ]]; then
                    whiptail --title "$(translate "No Folders")" --msgbox "$(translate "No folders found inside /mnt in the CT.")" 8 60
                    continue
                fi
                
                OPTIONS=()
                while IFS= read -r dir; do
                    name=$(basename "$dir")
                    OPTIONS+=("$dir" "$name")
                done <<< "$DIRS"
                
                MOUNT_POINT=$(whiptail --backtitle "ProxMenux" --title "$(translate "Select Folder")" \
                    --menu "$(translate "Choose a folder to export:")" 20 60 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
                if [[ $? -ne 0 ]]; then
                    return 1
                fi
                [[ -n "$MOUNT_POINT" ]] && return 0
                ;;
                manual)
                    CT_NAME=$(pct config "$CTID" | awk -F: '/hostname/ {print $2}' | xargs)
                    DEFAULT_MOUNT_POINT="/mnt/${CT_NAME}_nfs"
                    MOUNT_POINT=$(whiptail --title "$(translate "Mount Point")" \
                        --inputbox "$(translate "Enter the mount point for the NFS export (e.g., /mnt/mynfs):")" \
                        10 70 "$DEFAULT_MOUNT_POINT" 3>&1 1>&2 2>&3)
                    if [[ $? -ne 0 ]]; then
                        return 1
                    fi
                    if [[ -z "$MOUNT_POINT" ]]; then
                        whiptail --title "$(translate "Error")" \
                            --msgbox "$(translate "No mount point was specified.")" 8 50
                        continue
                    fi
                    pct exec "$CTID" -- mkdir -p "$MOUNT_POINT" 2>/dev/null
                    return 0
                    ;;
        esac
    done
}

get_network_config() {
    NETWORK=$(whiptail --backtitle "ProxMenux" --title "$(translate "Network Configuration")" --menu "\n$(translate "Select network access level:")" 15 70 4 \
    "1" "$(translate "Local network only (192.168.0.0/16)")" \
    "2" "$(translate "Specific subnet (enter manually)")" \
    "3" "$(translate "Specific host (enter IP)")" 3>&1 1>&2 2>&3)
    
    case "$NETWORK" in
        1)
            NETWORK_RANGE="192.168.0.0/16"
            ;;
        2)
            clear
            NETWORK_RANGE=$(whiptail --inputbox "$(translate "Enter subnet (e.g., 192.168.0.0/24):")" 10 60 "192.168.0.0/24" --title "$(translate "Subnet")" 3>&1 1>&2 2>&3)
            [[ -z "$NETWORK_RANGE" ]] && return 1
            ;;
        3)
            dialog
            NETWORK_RANGE=$(whiptail --inputbox "$(translate "Enter host IP (e.g., 192.168.0.100):")" 10 60 --title "$(translate "Host IP")" 3>&1 1>&2 2>&3)
            [[ -z "$NETWORK_RANGE" ]] && return 1
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}







select_export_options() {
    EXPORT_OPTIONS=$(whiptail --title "$(translate "Export Options")" --menu \
        "\n$(translate "Select export permissions:")" 15 70 3 \
        "1" "$(translate "Read-Write (recommended)")" \
        "2" "$(translate "Read-Only")" \
        "3" "$(translate "Custom options")" 3>&1 1>&2 2>&3)

    case "$EXPORT_OPTIONS" in
        1)
            OPTIONS="rw,sync,no_subtree_check,all_squash,anonuid=0,anongid=101000"
            ;;
        2)
            OPTIONS="ro,sync,no_subtree_check,all_squash,anonuid=0,anongid=101000"
            ;;
        3)
            OPTIONS=$(whiptail --inputbox "$(translate "Enter custom NFS options:")" \
                10 70 "rw,sync,no_subtree_check,all_squash,anonuid=0,anongid=101000" \
                --title "$(translate "Custom Options")" 3>&1 1>&2 2>&3)
            [[ -z "$OPTIONS" ]] && OPTIONS="rw,sync,no_subtree_check,all_squash,anonuid=0,anongid=101000"
            ;;
        *)
            OPTIONS="rw,sync,no_subtree_check,all_squash,anonuid=0,anongid=101000"
            ;;
    esac
}





create_nfs_export() {

    show_proxmenux_logo
    msg_title "$(translate "Create LXC server NFS")"


    select_mount_point || return
    get_network_config || return
    select_export_options || return


    msg_ok "$(translate "Directory successfully.")"


    if ! pct exec "$CTID" -- dpkg -s nfs-kernel-server &>/dev/null; then
        msg_info "$(translate "Installing NFS server packages inside the CT...")"
        pct exec "$CTID" -- bash -c "apt-get update && apt-get install -y nfs-kernel-server nfs-common rpcbind"
        pct exec "$CTID" -- systemctl enable --now rpcbind nfs-kernel-server
        msg_ok "$(translate "NFS server installed successfully.")"
    else
        msg_ok "$(translate "NFS server is already installed.")"
    fi


    setup_universal_sharedfiles_group "$CTID"


    msg_info "$(translate "Setting directory ownership and permissions...")"
    pct exec "$CTID" -- chown root:sharedfiles "$MOUNT_POINT"
    pct exec "$CTID" -- chmod 2775 "$MOUNT_POINT"  
    msg_ok "$(translate "Directory configured with sharedfiles group ownership")"



    EXPORT_LINE="$MOUNT_POINT $NETWORK_RANGE($OPTIONS)"


    if pct exec "$CTID" -- grep -q "^$MOUNT_POINT " /etc/exports; then
        if dialog --yesno "$(translate "Do you want to update the existing export?")" \
            10 60 --title "$(translate "Update Export")"; then
            pct exec "$CTID" -- sed -i "\|^$MOUNT_POINT |d" /etc/exports
            pct exec "$CTID" -- bash -c "echo '$EXPORT_LINE' >> /etc/exports"
            show_proxmenux_logo
            msg_title "$(translate "Create LXC server NFS")"
            msg_ok "$(translate "Directory successfully.")"
            msg_ok "$(translate "Export updated successfully.")"
            msg_ok "$(translate "NFS server is already installed.")"
            msg_ok "$(translate "Directory configured with sharedfiles group ownership")"

        fi
    else
        pct exec "$CTID" -- bash -c "echo '$EXPORT_LINE' >> /etc/exports"
        msg_ok "$(translate "Export added successfully.")"
    fi


    pct exec "$CTID" -- systemctl restart rpcbind nfs-kernel-server
    pct exec "$CTID" -- exportfs -ra


    CT_IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
    
    echo -e ""
    msg_ok "$(translate "NFS export created successfully!")"
    echo -e ""
    echo -e "${TAB}${BOLD}$(translate "Connection details:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Server IP:")${CL}  ${BL}$CT_IP${CL}"
    echo -e "${TAB}${BGN}$(translate "Export path:")${CL} ${BL}$MOUNT_POINT${CL}"
    echo -e "${TAB}${BGN}$(translate "Mount options:")${CL} ${BL}$OPTIONS${CL}"
    echo -e "${TAB}${BGN}$(translate "Network access:")${CL} ${BL}$NETWORK_RANGE${CL}"
    echo -e "${TAB}${BGN}$(translate "NFS Version:")${CL} ${BL}Auto-negotiation (NFSv3/NFSv4)${CL}"
    echo -e ""
    
    echo -e "${TAB}${BOLD}$(translate "Mount Examples:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Auto-negotiate:")${CL} ${BL}mount -t nfs $CT_IP:$MOUNT_POINT /mnt/nfs${CL}"
    echo -e "${TAB}${BGN}$(translate "Force NFSv4:")${CL} ${BL}mount -t nfs4 $CT_IP:$MOUNT_POINT /mnt/nfs${CL}"
    echo -e "${TAB}${BGN}$(translate "Force NFSv3:")${CL} ${BL}mount -t nfs -o vers=3 $CT_IP:$MOUNT_POINT /mnt/nfs${CL}"
    echo ""
    
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

view_exports() {
    show_proxmenux_logo
    msg_title "$(translate "View Current Exports")"
    
    echo -e "$(translate "Current NFS exports in CT") $CTID:"
    echo "=================================="
    
    if pct exec "$CTID" -- test -f /etc/exports; then
        EXPORTS=$(pct exec "$CTID" -- cat /etc/exports | grep -v '^#' | grep -v '^$')
        if [[ -n "$EXPORTS" ]]; then
            echo "$EXPORTS"
            echo ""
            echo "$(translate "Active exports:")"
            pct exec "$CTID" -- showmount -e localhost 2>/dev/null || echo "$(translate "No active exports or showmount not available")"
            

            echo ""
            echo "$(translate "Universal Group Configuration:")"
            echo "=================================="
            if pct exec "$CTID" -- getent group sharedfiles >/dev/null 2>&1; then
                local group_members=$(pct exec "$CTID" -- getent group sharedfiles | cut -d: -f4)
                local sharedfiles_gid=$(pct exec "$CTID" -- getent group sharedfiles | cut -d: -f3)
                echo "$(translate "Shared group: sharedfiles (GID:") $sharedfiles_gid)"
                
                local member_count=$(echo "$group_members" | tr ',' '\n' | wc -l)
                echo "$(translate "Total members:") $member_count $(translate "users")"
                

                local remapped_users=$(pct exec "$CTID" -- getent passwd | grep "^remap_" | wc -l)
                if [[ "$remapped_users" -gt 0 ]]; then
                    echo "$(translate "Remapped users:") $remapped_users $(translate "users (for unprivileged compatibility)")"
                fi
                
                echo "$(translate "Universal compatibility: ENABLED")"
                echo "$(translate "NFS Version: Auto-negotiation (NFSv3/NFSv4)")"
            else
                echo "$(translate "Universal group: NOT CONFIGURED")"
            fi

            CT_IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
            
            echo ""
            echo "=================================="
            echo -e "${TAB}${BOLD}$(translate "Connection Details:")${CL}"
            echo -e "${TAB}${BGN}$(translate "Server IP:")${CL}  ${BL}$CT_IP${CL}"
            while IFS= read -r export_line; do
                if [[ -n "$export_line" ]]; then
                    EXPORT_PATH=$(echo "$export_line" | awk '{print $1}')
                    echo -e "${TAB}${BGN}$(translate "Export path:")${CL} ${BL}$EXPORT_PATH${CL}"
                    echo ""
                fi
            done <<< "$EXPORTS"
            
        else
            echo "$(translate "No exports configured.")"
        fi
    else
        echo "$(translate "/etc/exports file does not exist.")"
    fi
    
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

delete_export() {
    if ! pct exec "$CTID" -- test -f /etc/exports; then
        dialog --title "$(translate "Error")" --msgbox "\n$(translate "No exports file found.")" 8 50
        return
    fi

    EXPORTS=$(pct exec "$CTID" -- awk '!/^#|^$/ {print NR, $0}' /etc/exports)
    if [[ -z "$EXPORTS" ]]; then
        dialog --title "$(translate "No Exports")" --msgbox "$(translate "No exports found in /etc/exports.")" 8 60
        return
    fi

    OPTIONS=()
    while read -r line; do
        [[ -z "$line" ]] && continue
        NUM=$(echo "$line" | awk '{print $1}')
        EXPORT_LINE=$(echo "$line" | cut -d' ' -f2-)
        EXPORT_PATH=$(echo "$EXPORT_LINE" | awk '{print $1}')
        EXPORT_CLIENT=$(echo "$EXPORT_LINE" | awk '{print $2}' | cut -d'(' -f1)
        [[ -z "$EXPORT_PATH" || -z "$EXPORT_CLIENT" ]] && continue
        OPTIONS+=("$NUM" "$EXPORT_PATH $EXPORT_CLIENT")
    done <<< "$EXPORTS"

    SELECTED_NUM=$(dialog --title "$(translate "Delete Export")" --menu "$(translate "Select an export to delete:")" 20 70 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [ -z "$SELECTED_NUM" ] && return

    EXPORT_LINE=$(echo "$EXPORTS" | awk -v num="$SELECTED_NUM" '$1 == num {$1=""; print substr($0,2)}')

    if whiptail --yesno "$(translate "Are you sure you want to delete this export?")\n\n$EXPORT_LINE" 10 70 --title "$(translate "Confirm Deletion")"; then
        show_proxmenux_logo
        msg_title "$(translate "Delete Export")"
        pct exec "$CTID" -- sed -i "${SELECTED_NUM}d" /etc/exports
        pct exec "$CTID" -- exportfs -ra
        pct exec "$CTID" -- systemctl restart nfs-kernel-server
        msg_ok "$(translate "Export deleted and NFS service restarted.")"
    fi
    
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

check_nfs_status() {
    show_proxmenux_logo
    msg_title "$(translate "Check NFS Status")"
    echo -e "$(translate "NFS Service Status in CT") $CTID:"
    echo "=================================="
    
    if pct exec "$CTID" -- dpkg -s nfs-kernel-server &>/dev/null; then
        echo "$(translate "NFS Server: INSTALLED")"
        
        if pct exec "$CTID" -- systemctl is-active --quiet nfs-kernel-server; then
            echo "$(translate "NFS Service: RUNNING")"
        else
            echo "$(translate "NFS Service: STOPPED")"
        fi
        
        if pct exec "$CTID" -- systemctl is-active --quiet rpcbind; then
            echo "$(translate "RPC Bind Service: RUNNING")"
        else
            echo "$(translate "RPC Bind Service: STOPPED")"
        fi
        

        echo ""
        echo "$(translate "NFS Version Configuration:")"
        echo "$(translate "Version: Auto-negotiation (NFSv3/NFSv4)")"
        echo "$(translate "Client determines best version to use")"
        

        echo ""
        echo "$(translate "Universal Group Configuration:")"
        if pct exec "$CTID" -- getent group sharedfiles >/dev/null 2>&1; then
            echo "$(translate "Shared group: CONFIGURED")"
            local group_members=$(pct exec "$CTID" -- getent group sharedfiles | cut -d: -f4)
            local sharedfiles_gid=$(pct exec "$CTID" -- getent group sharedfiles | cut -d: -f3)
            echo "$(translate "Group GID:") $sharedfiles_gid"
            
            local member_count=$(echo "$group_members" | tr ',' '\n' | wc -l)
            echo "$(translate "Total members:") $member_count $(translate "users")"
            
            local remapped_users=$(pct exec "$CTID" -- getent passwd | grep "^remap_" | wc -l)
            echo "$(translate "Remapped users:") $remapped_users $(translate "users")"
            
            echo "$(translate "Universal compatibility: ENABLED")"
        else
            echo "$(translate "Universal group: NOT CONFIGURED")"
        fi
        
        echo ""
        echo "$(translate "Listening ports:")"
        pct exec "$CTID" -- ss -tlnp | grep -E ':(111|2049|20048)' || echo "$(translate "No NFS ports found")"
        
    else
        echo "$(translate "NFS Server: NOT INSTALLED")"
    fi
    
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

uninstall_nfs() {
    if ! pct exec "$CTID" -- dpkg -s nfs-kernel-server &>/dev/null; then
        dialog --title "$(translate "NFS Not Installed")" --msgbox "\n$(translate "NFS server is not installed in this CT.")" 8 60
        return
    fi
    
    if ! whiptail --title "$(translate "Uninstall NFS Server")" \
        --yesno "$(translate "WARNING: This will completely remove NFS server from the CT.")\n\n$(translate "This action will:")\n$(translate "• Stop all NFS services")\n$(translate "• Remove all exports")\n$(translate "• Uninstall NFS packages")\n$(translate "• Remove universal sharedfiles group")\n$(translate "• Clean up remapped users")\n\n$(translate "Are you sure you want to continue?")" \
        18 70; then
        return
    fi
    
    show_proxmenux_logo
    msg_title "$(translate "Uninstall NFS Server")"

    msg_info "$(translate "Stopping NFS services...")"
    pct exec "$CTID" -- systemctl stop nfs-kernel-server 2>/dev/null || true
    pct exec "$CTID" -- systemctl stop rpcbind 2>/dev/null || true
    pct exec "$CTID" -- systemctl disable nfs-kernel-server 2>/dev/null || true
    pct exec "$CTID" -- systemctl disable rpcbind 2>/dev/null || true
    msg_ok "$(translate "NFS services stopped and disabled.")"
    
    if pct exec "$CTID" -- test -f /etc/exports; then
        pct exec "$CTID" -- truncate -s 0 /etc/exports
        msg_ok "$(translate "Exports cleared.")"
    fi    


    msg_info "$(translate "Removing remapped users...")"
    local remapped_users=$(pct exec "$CTID" -- getent passwd | grep "^remap_" | cut -d: -f1)
    if [[ -n "$remapped_users" ]]; then
        while IFS= read -r username; do
            if [[ -n "$username" ]]; then
                pct exec "$CTID" -- userdel "$username" 2>/dev/null || true
                msg_ok "$(translate "Removed remapped user:") $username"
            fi
        done <<< "$remapped_users"
    fi


    if pct exec "$CTID" -- getent group sharedfiles >/dev/null 2>&1; then
        local regular_members=$(pct exec "$CTID" -- getent group sharedfiles | cut -d: -f4 | tr ',' '\n' | grep -v "^remap_" | wc -l)
        if [[ "$regular_members" -eq 0 ]]; then
            pct exec "$CTID" -- groupdel sharedfiles 2>/dev/null || true
            msg_ok "$(translate "Removed sharedfiles group.")"
        else
            msg_warn "$(translate "Kept sharedfiles group (has regular users assigned).")"
        fi
    fi

    pct exec "$CTID" -- apt-get remove --purge -y nfs-kernel-server nfs-common 2>/dev/null || true
    pct exec "$CTID" -- apt-get autoremove -y 2>/dev/null || true
    msg_ok "$(translate "NFS packages removed.")"
    
    msg_info "$(translate "Cleaning up remaining processes...")"
    pct exec "$CTID" -- pkill -f nfs 2>/dev/null || true
    pct exec "$CTID" -- pkill -f rpc 2>/dev/null || true
    sleep 2
    msg_ok "$(translate "Universal NFS server has been completely uninstalled!")"
    echo -e ""
    echo -e "${TAB}${BOLD}$(translate "Uninstallation Summary:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Services:")${CL} ${BL}$(translate "Stopped and disabled")${CL}"
    echo -e "${TAB}${BGN}$(translate "Packages:")${CL} ${BL}$(translate "Removed")${CL}"
    echo -e "${TAB}${BGN}$(translate "Exports:")${CL} ${BL}$(translate "Cleared")${CL}"
    echo -e "${TAB}${BGN}$(translate "Universal Group:")${CL} ${BL}$(translate "Cleaned up")${CL}"
    echo -e "${TAB}${BGN}$(translate "Remapped Users:")${CL} ${BL}$(translate "Removed")${CL}"
    echo -e
    
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

# === Main Menu ===
while true; do
    CHOICE=$(dialog --title "$(translate "NFS LXC Manager - CT") $CTID" --menu "$(translate "Choose an option:")" 20 70 12 \
    "1" "$(translate "Create Universal NFS Export")" \
    "2" "$(translate "View Current Exports")" \
    "3" "$(translate "Delete Export")" \
    "4" "$(translate "Check NFS Status")" \
    "5" "$(translate "Uninstall NFS Server")" \
    "6" "$(translate "Exit")" 3>&1 1>&2 2>&3)
    
    case $CHOICE in
        1) create_nfs_export ;;
        2) view_exports ;;
        3) delete_export ;;
        4) check_nfs_status ;;
        5) uninstall_nfs ;;
        6) exit 0 ;;
        *) exit 0 ;;
    esac
done
