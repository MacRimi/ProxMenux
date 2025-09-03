#!/bin/bash
# ==========================================================
# ProxMenu CT - NFS Manager for Proxmox LXC
# ==========================================================
# Based on ProxMenux by MacRimi
# ==========================================================
# Description:
# This script allows you to manage NFS shares inside Proxmox CTs:
# - Create NFS exports
# - View configured exports
# - Delete existing exports
# - Check NFS service status
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

# === Select CT ===
CT_LIST=$(pct list | awk 'NR>1 {print $1, $3}')
if [ -z "$CT_LIST" ]; then
    dialog --title "$(translate "Error")" --msgbox "$(translate "No CTs available in the system.")" 8 50
    exit 1
fi

CTID=$(dialog --title "$(translate "Select CT")" --menu "$(translate "Select the CT to manage NFS:")" 20 70 12 $CT_LIST 3>&1 1>&2 2>&3)
if [ -z "$CTID" ]; then
    dialog --title "$(translate "Error")" --msgbox "$(translate "No CT was selected.")" 8 50
    exit 1
fi


# === Start CT if not running ===
CT_STATUS=$(pct status "$CTID" | awk '{print $2}')
if [ "$CT_STATUS" != "running" ]; then
    show_proxmenux_logo
    msg_info "$(translate "Starting CT") $CTID..."
    pct start "$CTID"
    sleep 2
    if [ "$(pct status "$CTID" | awk '{print $2}')" != "running" ]; then
        msg_error "$(translate "Failed to start the CT.")"
        exit 1
    fi
    msg_ok "$(translate "CT started successfully.")"
fi

select_mount_point() {
    while true; do
        METHOD=$(dialog --title "$(translate "Select Folder")" \
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
                    dialog --title "$(translate "No Folders")" --msgbox "$(translate "No folders found inside /mnt in the CT.")" 8 60
                    continue
                fi
                
                OPTIONS=()
                while IFS= read -r dir; do
                    name=$(basename "$dir")
                    OPTIONS+=("$dir" "$name")
                done <<< "$DIRS"
                
                MOUNT_POINT=$(dialog --title "$(translate "Select Folder")" \
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
                    whiptail --title "$(translate "Error")" --msgbox "$(translate "No mount point was specified.")" 8 50
                    continue
                else
                    return 0
                fi
                ;;
        esac
    done
}

get_network_config() {
    clear
    NETWORK=$(whiptail --title "$(translate "Network Configuration")" --menu "$(translate "Select network access level:")" 15 70 4 \
    "local" "$(translate "Local network only (192.168.0.0/16)")" \
    "subnet" "$(translate "Specific subnet (enter manually)")" \
    "host" "$(translate "Specific host (enter IP)")" \
    "all" "$(translate "All networks (*) - NOT RECOMMENDED")" 3>&1 1>&2 2>&3)
    
    case "$NETWORK" in
        local)
            NETWORK_RANGE="192.168.0.0/16"
            ;;
        subnet)
            NETWORK_RANGE=$(whiptail --inputbox "$(translate "Enter subnet (e.g., 192.168.1.0/24):")" 10 60 "192.168.1.0/24" --title "$(translate "Subnet")" 3>&1 1>&2 2>&3)
            [[ -z "$NETWORK_RANGE" ]] && return 1
            ;;
        host)
            NETWORK_RANGE=$(whiptail --inputbox "$(translate "Enter host IP (e.g., 192.168.1.100):")" 10 60 --title "$(translate "Host IP")" 3>&1 1>&2 2>&3)
            [[ -z "$NETWORK_RANGE" ]] && return 1
            ;;
        all)
            if whiptail --yesno "$(translate "WARNING: This will allow access from ANY network.\nThis is a security risk. Are you sure?")" 10 60 --title "$(translate "Security Warning")"; then
                NETWORK_RANGE="*"
            else
                return 1
            fi
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}



create_nfs_export() {
    select_mount_point || return
    get_network_config || return
    

    if ! pct exec "$CTID" -- test -d "$MOUNT_POINT"; then
        if whiptail --yesno "$(translate "The directory does not exist in the CT.")\n\n$MOUNT_POINT\n\n$(translate "Do you want to create it?")" 12 70 --title "$(translate "Create Directory")"; then
            pct exec "$CTID" -- mkdir -p "$MOUNT_POINT"
            msg_ok "$(translate "Directory created successfully.")"
        else
            msg_error "$(translate "Directory does not exist and was not created.")"
            return
        fi
    fi
    show_proxmenux_logo
    msg_title "$(translate "Create NFS server service")"
    if pct exec "$CTID" -- dpkg -s nfs-kernel-server &>/dev/null; then
        NFS_INSTALLED=true
    else
        NFS_INSTALLED=false
    fi
    

    if [ "$NFS_INSTALLED" = false ]; then
        echo -e "${TAB}$(translate "Installing NFS server packages inside the CT...")"
        pct exec "$CTID" -- bash -c "apt-get update && apt-get install -y nfs-kernel-server nfs-common rpcbind"
        

        pct exec "$CTID" -- systemctl enable rpcbind
        pct exec "$CTID" -- systemctl enable nfs-kernel-server
        pct exec "$CTID" -- systemctl start rpcbind
        
        msg_ok "$(translate "NFS server installed successfully.")"
    else
        msg_ok "$(translate "NFS server is already installed.")"
    fi
    

    IS_MOUNTED=$(pct exec "$CTID" -- mount | grep "$MOUNT_POINT" || true)
    if [[ -n "$IS_MOUNTED" ]]; then
        msg_info "$(translate "Detected a mounted directory from host. Setting up shared group...")"
        
        SHARE_GID=999
        GROUP_EXISTS=$(pct exec "$CTID" -- getent group nfsshare || true)
        GID_IN_USE=$(pct exec "$CTID" -- getent group "$SHARE_GID" | cut -d: -f1 || true)
        
        if [[ -z "$GROUP_EXISTS" ]]; then
            if [[ -z "$GID_IN_USE" ]]; then
                pct exec "$CTID" -- groupadd -g "$SHARE_GID" nfsshare
                msg_ok "$(translate "Group 'nfsshare' created with GID $SHARE_GID")"
            else
                pct exec "$CTID" -- groupadd nfsshare
                msg_warn "$(translate "GID $SHARE_GID already in use. Group 'nfsshare' created with dynamic GID.")"
            fi
        else
            msg_ok "$(translate "Group 'nfsshare' already exists inside the CT")"
        fi
        
        pct exec "$CTID" -- chown root:nfsshare "$MOUNT_POINT"
        pct exec "$CTID" -- chmod 2775 "$MOUNT_POINT"
    else
        msg_ok "$(translate "No shared mount detected. Applying standard local access.")"
        pct exec "$CTID" -- chmod 755 "$MOUNT_POINT"
    fi
    

    EXPORT_OPTIONS=$(whiptail --title "$(translate "Export Options")" --menu "$(translate "Select export permissions:")" 15 70 3 \
        "rw" "$(translate "Read-Write access")" \
        "ro" "$(translate "Read-Only access")" \
        "custom" "$(translate "Custom options")" 3>&1 1>&2 2>&3)

    
    case "$EXPORT_OPTIONS" in
        rw)
            OPTIONS="rw,sync,no_subtree_check,no_root_squash"
            ;;
        ro)
            OPTIONS="ro,sync,no_subtree_check,root_squash"
            ;;
        custom)
            OPTIONS=$(whiptail --inputbox "$(translate "Enter custom NFS options:")" 10 70 "rw,sync,no_subtree_check,no_root_squash" --title "$(translate "Custom Options")" 3>&1 1>&2 2>&3)
            [[ -z "$OPTIONS" ]] && OPTIONS="rw,sync,no_subtree_check,no_root_squash"
            ;;
        *)
            OPTIONS="rw,sync,no_subtree_check,no_root_squash"
            ;;
    esac
    

    EXPORT_LINE="$MOUNT_POINT $NETWORK_RANGE($OPTIONS)"
    

    if pct exec "$CTID" -- grep -q "^$MOUNT_POINT " /etc/exports; then
        msg_warn "$(translate "Export already exists for:") $MOUNT_POINT"
        if whiptail --yesno "$(translate "Do you want to update the existing export?")" 10 60 --title "$(translate "Update Export")"; then

            pct exec "$CTID" -- sed -i "\|^$MOUNT_POINT |d" /etc/exports
            pct exec "$CTID" -- bash -c "echo '$EXPORT_LINE' >> /etc/exports"
            msg_ok "$(translate "Export updated successfully.")"
        else
            return
        fi
    else
        msg_ok "$(translate "Adding new export to /etc/exports...")"
        pct exec "$CTID" -- bash -c "echo '$EXPORT_LINE' >> /etc/exports"
        msg_ok "$(translate "Export added successfully.")"
    fi
    
    pct exec "$CTID" -- systemctl restart nfs-kernel-server
    pct exec "$CTID" -- exportfs -ra

    CT_IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
    echo -e ""
    msg_ok "$(translate "NFS export created successfully!")"
    echo -e ""
    echo -e "${TAB}${BOLD}$(translate "Connection details:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Mount options:")${CL} ${CUS}$OPTIONS${CL}"
    echo -e "${TAB}${BGN}$(translate "Server IP:")${CL}  ${CUS}$CT_IP${CL}"
    echo -e "${TAB}${BGN}$(translate "Export path:")${CL} ${CUS}$CT_IP:$MOUNT_POINT${CL}"
    
    echo -e
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
            

            CT_IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
            
            echo ""
            echo "=================================="
            echo -e "${TAB}${BOLD}$(translate "Connection Details:")${CL}"
            echo -e "${TAB}${BGN}$(translate "Server IP:")${CL}  ${CUS}$CT_IP${CL}"
            while IFS= read -r export_line; do
                if [[ -n "$export_line" ]]; then
                    EXPORT_PATH=$(echo "$export_line" | awk '{print $1}')
                    echo -e "${TAB}${BGN}$(translate "Export path:")${CL} ${CUS}$EXPORT_PATH${CL}"
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
 
 #   if ! pct exec "$CTID" -- test -f /etc/exports; then
 #       whiptail --title "$(translate "Error")" --msgbox "$(translate "No exports file found.")" 8 50
 #       return
 #   fi
    
 #   EXPORTS=$(pct exec "$CTID" -- awk '!/^#|^$/ {print NR, $0}' /etc/exports)
 #   if [[ -z "$EXPORTS" ]]; then
 #       whiptail --title "$(translate "No Exports")" --msgbox "$(translate "No exports found in /etc/exports.")" 8 60
 #       return
 #   fi



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

    
#    SELECTED_NUM=$(whiptail --title "$(translate "Delete Export")" --menu "$(translate "Select an export to delete:")" 20 70 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
#    [ -z "$SELECTED_NUM" ] && return


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
        --yesno "$(translate "WARNING: This will completely remove NFS server from the CT.")\n\n$(translate "This action will:")\n$(translate "• Stop all NFS services")\n$(translate "• Remove all exports")\n$(translate "• Uninstall NFS packages")\n$(translate "• Remove NFS groups")\n\n$(translate "Are you sure you want to continue?")" \
        16 70; then
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

    pct exec "$CTID" -- apt-get remove --purge -y nfs-kernel-server nfs-common 2>/dev/null || true
    pct exec "$CTID" -- apt-get autoremove -y 2>/dev/null || true
    msg_ok "$(translate "NFS packages removed.")"
    

    if pct exec "$CTID" -- getent group nfsshare >/dev/null 2>&1; then

        GROUP_USERS=$(pct exec "$CTID" -- getent group nfsshare | cut -d: -f4)
        if [[ -z "$GROUP_USERS" ]]; then
            pct exec "$CTID" -- groupdel nfsshare 2>/dev/null || true
            msg_ok "$(translate "NFS group removed.")"
        else
            msg_warn "$(translate "NFS group kept (has users assigned).")"
        fi
    fi
    

    msg_info "$(translate "Cleaning up remaining processes...")"
    pct exec "$CTID" -- pkill -f nfs 2>/dev/null || true
    pct exec "$CTID" -- pkill -f rpc 2>/dev/null || true
    sleep 2
    msg_ok "$(translate "NFS server has been completely uninstalled!")"
    echo -e ""
    echo -e "${TAB}${BOLD}$(translate "Uninstallation Summary:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Services:")${CL} ${BL}$(translate "Stopped and disabled")${CL}"
    echo -e "${TAB}${BGN}$(translate "Packages:")${CL} ${BL}$(translate "Removed")${CL}"
    echo -e "${TAB}${BGN}$(translate "Exports:")${CL} ${BL}$(translate "Cleared (backup created)")${CL}"
    echo -e "${TAB}${BGN}$(translate "Groups:")${CL} ${BL}$(translate "Cleaned up")${CL}"
    echo -e
    
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}




# === Main Menu ===
while true; do
    CHOICE=$(dialog --title "$(translate "NFS Manager - CT") $CTID" --menu "$(translate "Choose an option:")" 20 70 12 \
    "1" "$(translate "Create NFS server service")" \
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