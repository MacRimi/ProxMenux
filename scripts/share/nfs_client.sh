#!/bin/bash
# ==========================================================
# ProxMenu CT - NFS Client Manager for Proxmox LXC
# ==========================================================
# Based on ProxMenux by MacRimi
# ==========================================================
# Description:
# This script allows you to manage NFS client mounts inside Proxmox CTs:
# - Mount NFS shares (temporary and permanent)
# - View current mounts
# - Unmount and remove NFS shares
# - Auto-discover NFS servers
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
    dialog --backtitle "ProxMenux" --title "$(translate "Error")" --msgbox "$(translate "No CTs available in the system.")" 8 50
    exit 1
fi

CTID=$(dialog --backtitle "ProxMenux" --title "$(translate "Select CT")" --menu "$(translate "Select the CT to manage NFS client:")" 20 70 12 $CT_LIST 3>&1 1>&2 2>&3)
if [ -z "$CTID" ]; then
    dialog --backtitle "ProxMenux" --title "$(translate "Error")" --msgbox "$(translate "No CT was selected.")" 8 50
    exit 1
fi


# === Start CT if not running ===
CT_STATUS=$(pct status "$CTID" | awk '{print $2}')
if [ "$CT_STATUS" != "running" ]; then
    msg_info "$(translate "Starting CT") $CTID..."
    pct start "$CTID"
    sleep 2
    if [ "$(pct status "$CTID" | awk '{print $2}')" != "running" ]; then
        msg_error "$(translate "Failed to start the CT.")"
        exit 1
    fi
    msg_ok "$(translate "CT started successfully.")"
fi



install_nfs_client() {

    if pct exec "$CTID" -- dpkg -s nfs-common &>/dev/null; then
        return 0
    fi

    show_proxmenux_logo
    msg_title "$(translate "Installing NFS Client")"

    msg_info "$(translate "Installing NFS client packages...")"
    if ! pct exec "$CTID" -- apt-get update >/dev/null 2>&1; then
        msg_error "$(translate "Failed to update package list.")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi

    if ! pct exec "$CTID" -- apt-get install -y nfs-common >/dev/null 2>&1; then
        msg_error "$(translate "Failed to install NFS client packages.")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi

    if ! pct exec "$CTID" -- which showmount >/dev/null 2>&1; then
        msg_error "$(translate "showmount command not found after installation.")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi
    if ! pct exec "$CTID" -- which mount.nfs >/dev/null 2>&1; then
        msg_error "$(translate "mount.nfs command not found after installation.")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi

    msg_ok "$(translate "NFS client installed successfully.")"
    return 0
}



discover_nfs_servers() {
    show_proxmenux_logo
    msg_title "$(translate "NFS Host Manager - Proxmox Host")"
    msg_info "$(translate "Scanning network for NFS servers...")"

    

    HOST_IP=$(hostname -I | awk '{print $1}')
    NETWORK=$(echo "$HOST_IP" | cut -d. -f1-3).0/24
    

    if ! which nmap >/dev/null 2>&1; then
        apt-get install -y nmap &>/dev/null
    fi
    

    SERVERS=$(nmap -p 2049 --open "$NETWORK" 2>/dev/null | grep -B 4 "2049/tcp open" | grep "Nmap scan report" | awk '{print $5}' | sort -u || true)
    
    if [[ -z "$SERVERS" ]]; then
        cleanup
        whiptail --title "$(translate "No Servers Found")" --msgbox "$(translate "No NFS servers found on the network.")\n\n$(translate "You can add servers manually.")" 10 60
        return 1
    fi
    
    OPTIONS=()
    while IFS= read -r server; do
        if [[ -n "$server" ]]; then
            EXPORTS_COUNT=$(showmount -e "$server" 2>/dev/null | tail -n +2 | wc -l || echo "0")
            SERVER_INFO="NFS Server ($EXPORTS_COUNT exports)"
            OPTIONS+=("$server" "$SERVER_INFO")
        fi
    done <<< "$SERVERS"
    
    if [[ ${#OPTIONS[@]} -eq 0 ]]; then
        cleanup
        whiptail --title "$(translate "No Valid Servers")" --msgbox "$(translate "No accessible NFS servers found.")" 8 50
        return 1
    fi
    msg_ok "$(translate "NFS servers detected")"
    NFS_SERVER=$(whiptail --title "$(translate "Select NFS Server")" --menu "$(translate "Choose an NFS server:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -n "$NFS_SERVER" ]] && return 0 || return 1
}

select_nfs_server() {
    METHOD=$(dialog --backtitle "ProxMenux" --title "$(translate "NFS Server Selection")" --menu "$(translate "How do you want to select the NFS server?")" 15 70 3 \
    "auto" "$(translate "Auto-discover servers on network")" \
    "manual" "$(translate "Enter server IP/hostname manually")" \
    "recent" "$(translate "Select from recent servers")" 3>&1 1>&2 2>&3)
    
    case "$METHOD" in
        auto)
            discover_nfs_servers || return 1
            ;;
        manual)
            clear
            NFS_SERVER=$(whiptail --inputbox "$(translate "Enter NFS server IP or hostname:")" 10 60 --title "$(translate "NFS Server")" 3>&1 1>&2 2>&3)
            [[ -z "$NFS_SERVER" ]] && return 1
            ;;
        recent)
            clear
            RECENT=$(grep "nfs" /etc/fstab 2>/dev/null | awk '{print $1}' | cut -d: -f1 | sort -u || true)
            if [[ -z "$RECENT" ]]; then
                dialog --backtitle "ProxMenux" --title "$(translate "No Recent Servers")" --msgbox "\n$(translate "No recent NFS servers found.")" 8 50
                return 1
            fi
            
            OPTIONS=()
            while IFS= read -r server; do
                [[ -n "$server" ]] && OPTIONS+=("$server" "$(translate "Recent NFS server")")
            done <<< "$RECENT"
            
            NFS_SERVER=$(whiptail --title "$(translate "Recent NFS Servers")" --menu "$(translate "Choose a recent server:")" 20 70 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
            [[ -n "$NFS_SERVER" ]] && return 0 || return 1
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}

select_nfs_export() {
    clear
    if ! pct exec "$CTID" -- which showmount >/dev/null 2>&1; then
        whiptail --title "$(translate "NFS Client Error")" \
                 --msgbox "$(translate "showmount command is not working properly.")\n\n$(translate "Please check the installation.")" \
                 10 60
        return 1
    fi

    if ! pct exec "$CTID" -- ping -c 1 -W 3 "$NFS_SERVER" >/dev/null 2>&1; then
        whiptail --title "$(translate "Connection Error")" \
               --msgbox "$(translate "Cannot reach server") $NFS_SERVER\n\n$(translate "Please check:")\n• $(translate "Server IP/hostname is correct")\n• $(translate "Network connectivity")\n• $(translate "Server is online")" \
               12 70
        return 1
    fi
    

    if ! pct exec "$CTID" -- nc -z -w 3 "$NFS_SERVER" 2049 2>/dev/null; then
        whiptail --title "$(translate "NFS Port Error")" \
               --msgbox "$(translate "NFS port (2049) is not accessible on") $NFS_SERVER\n\n$(translate "Please check:")\n• $(translate "NFS server is running")\n• $(translate "Firewall settings")\n• $(translate "NFS service is enabled")" \
               12 70
        return 1
    fi
    

    EXPORTS_OUTPUT=$(pct exec "$CTID" -- showmount -e "$NFS_SERVER" 2>&1)
    EXPORTS_RESULT=$?
    
    if [[ $EXPORTS_RESULT -ne 0 ]]; then
        ERROR_MSG=$(echo "$EXPORTS_OUTPUT" | grep -i "error\|failed\|denied" | head -1)

        
        if echo "$EXPORTS_OUTPUT" | grep -qi "connection refused\|network unreachable"; then
            whiptail --title "$(translate "Network Error")" \
                   --msgbox "$(translate "Network connection failed to") $NFS_SERVER\n\n$(translate "Error:"): $ERROR_MSG\n\n$(translate "Please check:")\n• $(translate "Server is running")\n• $(translate "Network connectivity")\n• $(translate "Firewall settings")" \
                   14 80
        else
            whiptail --title "$(translate "NFS Error")" \
                   --msgbox "$(translate "Failed to connect to") $NFS_SERVER\n\n$(translate "Error:"): $ERROR_MSG" \
                   12 80
        fi
        return 1
    fi
    

    EXPORTS=$(echo "$EXPORTS_OUTPUT" | tail -n +2 | awk '{print $1}' | grep -v "^$")

    if [[ -z "$EXPORTS" ]]; then
        whiptail --title "$(translate "No Exports Found")" \
               --msgbox "$(translate "No exports found on server") $NFS_SERVER\n\n$(translate "Server response:")\n$(echo "$EXPORTS_OUTPUT" | head -10)\n\n$(translate "You can enter the export path manually.")" \
               16 80
    
        NFS_EXPORT=$(whiptail --inputbox "$(translate "Enter NFS export path (e.g., /mnt/shared):")" 10 60 --title "$(translate "Export Path")" 3>&1 1>&2 2>&3)
        [[ -z "$NFS_EXPORT" ]] && return 1
        return 0
    fi

    # Build options for whiptail
    OPTIONS=()
    while IFS= read -r export_line; do
        if [[ -n "$export_line" ]]; then
            EXPORT_PATH=$(echo "$export_line" | awk '{print $1}')
            # Get allowed clients if available
            CLIENTS=$(echo "$EXPORTS_OUTPUT" | grep "^$EXPORT_PATH" | awk '{for(i=2;i<=NF;i++) printf "%s ", $i; print ""}' | sed 's/[[:space:]]*$//')
            if [[ -n "$CLIENTS" ]]; then
                OPTIONS+=("$EXPORT_PATH" "$CLIENTS")
            else
                OPTIONS+=("$EXPORT_PATH" "$(translate "NFS export")")
            fi
        fi
    done <<< "$EXPORTS"
    
    if [[ ${#OPTIONS[@]} -eq 0 ]]; then
        whiptail --title "$(translate "No Available Exports")" \
               --msgbox "$(translate "No accessible exports found.")\n\n$(translate "You can enter the export path manually.")" \
               10 70
        
        NFS_EXPORT=$(whiptail --inputbox "$(translate "Enter NFS export path (e.g., /mnt/shared):")" 10 60 --title "$(translate "Export Path")" 3>&1 1>&2 2>&3)
        [[ -n "$NFS_EXPORT" ]] && return 0 || return 1
    fi
    
    NFS_EXPORT=$(whiptail --title "$(translate "Select NFS Export")" --menu "$(translate "Choose an export to mount:")" 20 70 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -n "$NFS_EXPORT" ]] && return 0 || return 1
}

select_mount_point() {
    while true; do
        METHOD=$(whiptail --title "$(translate "Select Mount Point")" --menu "$(translate "Where do you want to mount the NFS export?")" 15 70 3 \
        "existing" "$(translate "Select from existing folders in /mnt")" \
        "new" "$(translate "Create new folder in /mnt")" \
        "custom" "$(translate "Enter custom path")" 3>&1 1>&2 2>&3)
        
        case "$METHOD" in
            existing)
                DIRS=$(pct exec "$CTID" -- find /mnt -maxdepth 1 -mindepth 1 -type d 2>/dev/null)
                if [[ -z "$DIRS" ]]; then
                    whiptail --title "$(translate "No Folders")" --msgbox "$(translate "No folders found in /mnt. Please create a new folder.")" 8 60
                    continue
                fi
                
                OPTIONS=()
                while IFS= read -r dir; do
                    if [[ -n "$dir" ]]; then
                        name=$(basename "$dir")
                        if pct exec "$CTID" -- [ "$(ls -A "$dir" 2>/dev/null | wc -l)" -eq 0 ]; then
                            status="$(translate "Empty")"
                        else
                            status="$(translate "Contains files")"
                        fi
                        OPTIONS+=("$dir" "$name ($status)")
                    fi
                done <<< "$DIRS"
                
                MOUNT_POINT=$(whiptail --title "$(translate "Select Existing Folder")" --menu "$(translate "Choose a folder to mount the export:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
                
                if [[ -n "$MOUNT_POINT" ]]; then
                    if pct exec "$CTID" -- [ "$(ls -A "$MOUNT_POINT" 2>/dev/null | wc -l)" -gt 0 ]; then
                        FILE_COUNT=$(pct exec "$CTID" -- ls -A "$MOUNT_POINT" 2>/dev/null | wc -l)
                        if ! whiptail --yesno "$(translate "WARNING: The selected directory is not empty!")\n\n$(translate "Directory:"): $MOUNT_POINT\n$(translate "Contains:"): $FILE_COUNT $(translate "files/folders")\n\n$(translate "Mounting here will hide existing files until unmounted.")\n\n$(translate "Do you want to continue?")" 14 70 --title "$(translate "Directory Not Empty")"; then
                            continue
                        fi
                    fi
                    return 0
                fi
                ;;
            new)
                # Create default name from server and export
                EXPORT_NAME=$(basename "$NFS_EXPORT")
                DEFAULT_NAME="nfs_${NFS_SERVER}_${EXPORT_NAME}"
                FOLDER_NAME=$(whiptail --inputbox "$(translate "Enter new folder name:")" 10 60 "$DEFAULT_NAME" --title "$(translate "New Folder in /mnt")" 3>&1 1>&2 2>&3)
                if [[ -n "$FOLDER_NAME" ]]; then
                    MOUNT_POINT="/mnt/$FOLDER_NAME"
                    return 0
                fi
                ;;
            custom)
                MOUNT_POINT=$(whiptail --inputbox "$(translate "Enter full path for mount point:")" 10 70 "/mnt/nfs_share" --title "$(translate "Custom Path")" 3>&1 1>&2 2>&3)
                if [[ -n "$MOUNT_POINT" ]]; then
                    return 0
                fi
                ;;
            *)
                return 1
                ;;
        esac
    done
}

configure_mount_options() {
    MOUNT_TYPE=$(whiptail --title "$(translate "Mount Options")" --menu "$(translate "Select mount configuration:")" 15 70 4 \
    "default" "$(translate "Default options")" \
    "readonly" "$(translate "Read-only mount")" \
    "performance" "$(translate "Performance optimized")" \
    "custom" "$(translate "Custom options")" 3>&1 1>&2 2>&3)
    
    case "$MOUNT_TYPE" in
        default)
            MOUNT_OPTIONS="rw,hard,intr,rsize=8192,wsize=8192,timeo=14"
            ;;
        readonly)
            MOUNT_OPTIONS="ro,hard,intr,rsize=8192,timeo=14"
            ;;
        performance)
            MOUNT_OPTIONS="rw,hard,intr,rsize=1048576,wsize=1048576,timeo=14,retrans=2"
            ;;
        custom)
            MOUNT_OPTIONS=$(whiptail --inputbox "$(translate "Enter custom mount options:")" 10 70 "rw,hard,intr" --title "$(translate "Custom Options")" 3>&1 1>&2 2>&3)
            [[ -z "$MOUNT_OPTIONS" ]] && MOUNT_OPTIONS="rw,hard,intr"
            ;;
        *)
            MOUNT_OPTIONS="rw,hard,intr,rsize=8192,wsize=8192,timeo=14"
            ;;
    esac
    
    if whiptail --yesno "$(translate "Do you want to make this mount permanent?")\n\n$(translate "This will add the mount to /etc/fstab so it persists after reboot.")" 10 70 --title "$(translate "Permanent Mount")"; then
        PERMANENT_MOUNT=true
    else
        PERMANENT_MOUNT=false
    fi
}

validate_export_exists() {
    local server="$1"
    local export="$2"
    

    
    VALIDATION_OUTPUT=$(pct exec "$CTID" -- showmount -e "$server" 2>/dev/null | grep "^$export[[:space:]]")
    
    if [[ -n "$VALIDATION_OUTPUT" ]]; then

        return 0
    else
        show_proxmenux_logo
        echo -e
        msg_error "$(translate "Export not found on server:") $export"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi
}

mount_nfs_share() {
    # Step 0: Install NFS client first
    install_nfs_client || return
    
    # Step 1: Select server
    select_nfs_server || return
    
    # Step 2: Select export
    select_nfs_export || return
    
    # Step 2.5: Validate export exists
    if ! validate_export_exists "$NFS_SERVER" "$NFS_EXPORT"; then
        echo -e ""
        msg_error "$(translate "Cannot proceed with invalid export path.")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return
    fi
    
    # Step 3: Select mount point
    select_mount_point || return
    
    # Step 4: Configure mount options
    configure_mount_options || return


# ===================================================  

    show_proxmenux_logo
    msg_title "$(translate "Mount NFS Share on Host")"
    
# =====================================================
    
    
    if ! pct exec "$CTID" -- test -d "$MOUNT_POINT"; then
        if pct exec "$CTID" -- mkdir -p "$MOUNT_POINT"; then
            msg_ok "$(translate "Mount point created.")"
        else
            msg_error "$(translate "Failed to create mount point.")"
            return 1
        fi
    fi
    
    if pct exec "$CTID" -- mount | grep -q "$MOUNT_POINT"; then
        msg_warn "$(translate "Something is already mounted at") $MOUNT_POINT"
        if ! whiptail --yesno "$(translate "Do you want to unmount it first?")" 8 60 --title "$(translate "Already Mounted")"; then
            return
        fi
        pct exec "$CTID" -- umount "$MOUNT_POINT" 2>/dev/null || true
    fi
    
    # Build mount command
    NFS_PATH="$NFS_SERVER:$NFS_EXPORT"
    
    msg_info "$(translate "Testing NFS connection...")"
    if pct exec "$CTID" -- mount -t nfs -o "$MOUNT_OPTIONS" "$NFS_PATH" "$MOUNT_POINT"; then
        msg_ok "$(translate "NFS share mounted successfully!")"
        
        # Test write access
        if pct exec "$CTID" -- touch "$MOUNT_POINT/.test_write" 2>/dev/null; then
            pct exec "$CTID" -- rm "$MOUNT_POINT/.test_write" 2>/dev/null
            msg_ok "$(translate "Write access confirmed.")"
        else
            msg_warn "$(translate "Read-only access (or no write permissions).")"
        fi
        
        # Add to fstab if permanent
        if [[ "$PERMANENT_MOUNT" == "true" ]]; then
            pct exec "$CTID" -- sed -i "\|$MOUNT_POINT|d" /etc/fstab
            FSTAB_ENTRY="$NFS_PATH $MOUNT_POINT nfs $MOUNT_OPTIONS 0 0"
            pct exec "$CTID" -- bash -c "echo '$FSTAB_ENTRY' >> /etc/fstab"
            msg_ok "$(translate "Added to /etc/fstab for permanent mounting.")"
        fi
        
        # Show mount information
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Mount Information:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$NFS_SERVER${CL}"
        echo -e "${TAB}${BGN}$(translate "Export:")${CL} ${BL}$NFS_EXPORT${CL}"
        echo -e "${TAB}${BGN}$(translate "Mount Point:")${CL} ${BL}$MOUNT_POINT${CL}"
        echo -e "${TAB}${BGN}$(translate "Options:")${CL} ${BL}$MOUNT_OPTIONS${CL}"
        echo -e "${TAB}${BGN}$(translate "Permanent:")${CL} ${BL}$PERMANENT_MOUNT${CL}"
        
    else
        msg_error "$(translate "Failed to mount NFS share.")"
        echo -e "${TAB}$(translate "Please check:")"
        echo -e "${TAB}• $(translate "Server is accessible:"): $NFS_SERVER"
        echo -e "${TAB}• $(translate "Export exists:"): $NFS_EXPORT"
        echo -e "${TAB}• $(translate "Network connectivity")"
        echo -e "${TAB}• $(translate "NFS server is running")"
        echo -e "${TAB}• $(translate "Export permissions allow access")"
    fi
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

view_nfs_mounts() {
    show_proxmenux_logo
    msg_title "$(translate "Current NFS Mounts")"
    
    echo -e "$(translate "NFS mounts in CT") $CTID:"
    echo "=================================="
    
    # Show currently mounted NFS shares - VERSIÓN CORREGIDA
    CURRENT_MOUNTS=$(pct exec "$CTID" -- mount | grep -E "type nfs|:.*on.*nfs" 2>/dev/null || true)
    if [[ -n "$CURRENT_MOUNTS" ]]; then
        echo -e "${BOLD}$(translate "Currently Mounted:")${CL}"
        echo "$CURRENT_MOUNTS"
        echo ""
    else
        # Verificar si hay montajes NFS en fstab que estén activos
        ACTIVE_NFS_MOUNTS=$(pct exec "$CTID" -- grep "nfs" /etc/fstab 2>/dev/null | grep -v "^#" | while read -r line; do
            MOUNT_POINT=$(echo "$line" | awk '{print $2}')
            if pct exec "$CTID" -- mount | grep -q "$MOUNT_POINT"; then
                echo "$MOUNT_POINT"
            fi
        done)
        
        if [[ -n "$ACTIVE_NFS_MOUNTS" ]]; then
            echo -e "${BOLD}$(translate "Currently Mounted:")${CL}"
            while IFS= read -r mount_point; do
                if [[ -n "$mount_point" ]]; then
                    MOUNT_INFO=$(pct exec "$CTID" -- mount | grep "$mount_point")
                    echo "$MOUNT_INFO"
                fi
            done <<< "$ACTIVE_NFS_MOUNTS"
            echo ""
        else
            echo "$(translate "No NFS shares currently mounted.")"
            echo ""
        fi
    fi
    
    # Show fstab entries
    FSTAB_NFS=$(pct exec "$CTID" -- grep "nfs" /etc/fstab 2>/dev/null || true)
    if [[ -n "$FSTAB_NFS" ]]; then
        echo -e "${BOLD}$(translate "Permanent Mounts (fstab):")${CL}"
        echo "$FSTAB_NFS"
        echo ""
        
        echo -e "${TAB}${BOLD}$(translate "Mount Details:")${CL}"
        while IFS= read -r fstab_line; do
            if [[ -n "$fstab_line" && ! "$fstab_line" =~ ^# ]]; then
                NFS_PATH=$(echo "$fstab_line" | awk '{print $1}')
                MOUNT_POINT=$(echo "$fstab_line" | awk '{print $2}')
                OPTIONS=$(echo "$fstab_line" | awk '{print $4}')
                
                # Extract server and export from NFS path
                SERVER=$(echo "$NFS_PATH" | cut -d: -f1)
                EXPORT=$(echo "$NFS_PATH" | cut -d: -f2)
                
                echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$SERVER${CL}"
                echo -e "${TAB}${BGN}$(translate "Export:")${CL} ${BL}$EXPORT${CL}"
                echo -e "${TAB}${BGN}$(translate "Mount Point:")${CL} ${BL}$MOUNT_POINT${CL}"
                echo -e "${TAB}${BGN}$(translate "Options:")${CL} ${BL}$OPTIONS${CL}"
                
                # Check if currently mounted
                if pct exec "$CTID" -- mount | grep -q "$MOUNT_POINT"; then
                    echo -e "${TAB}${BGN}$(translate "Status:")${CL} ${GN}$(translate "Mounted")${CL}"
                else
                    echo -e "${TAB}${BGN}$(translate "Status:")${CL} ${RD}$(translate "Not Mounted")${CL}"
                fi
                echo ""
            fi
        done <<< "$FSTAB_NFS"
    else
        echo "$(translate "No permanent NFS mounts configured.")"
    fi
    
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}



unmount_nfs_share() {
    # Get current NFS mounts
    MOUNTS=$(pct exec "$CTID" -- mount | grep -E "type nfs|:.*on.*nfs" | awk '{print $3}' | sort -u || true)
    FSTAB_MOUNTS=$(pct exec "$CTID" -- grep -E "nfs" /etc/fstab 2>/dev/null | grep -v "^#" | awk '{print $2}' | sort -u || true)
    
    # Combine and deduplicate
    ALL_MOUNTS=$(echo -e "$MOUNTS\n$FSTAB_MOUNTS" | sort -u | grep -v "^$" || true)
    
    if [[ -z "$ALL_MOUNTS" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Mounts")" --msgbox "\n$(translate "No NFS mounts found.")" 8 50
        return
    fi
    
    OPTIONS=()
    while IFS= read -r mount_point; do
        [[ -n "$mount_point" ]] && OPTIONS+=("$mount_point" "")
    done <<< "$ALL_MOUNTS"
    
    SELECTED_MOUNT=$(dialog --backtitle "ProxMenux" --title "$(translate "Unmount NFS Share")" --menu "$(translate "Select mount point to unmount:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED_MOUNT" ]] && return
    
    if whiptail --yesno "$(translate "Are you sure you want to unmount this NFS share?")\n\n$(translate "Mount Point:"): $SELECTED_MOUNT\n\n$(translate "This will remove the mount from /etc/fstab.")" 12 80 --title "$(translate "Confirm Unmount")"; then
        show_proxmenux_logo
        msg_title "$(translate "Unmount NFS Share")"
        
        # Remove from fstab
        pct exec "$CTID" -- sed -i "\|[[:space:]]$SELECTED_MOUNT[[:space:]]|d" /etc/fstab
        msg_ok "$(translate "Removed from /etc/fstab.")"
        
        echo -e ""
        msg_ok "$(translate "NFS share unmount successfully. Reboot LXC required to take effect.")"
    fi
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}




test_nfs_connectivity() {
    show_proxmenux_logo
    msg_title "$(translate "Test NFS Connectivity")"
    
    echo -e "$(translate "NFS Client Status in CT") $CTID:"
    echo "=================================="
    
    # Check if NFS client is installed
    if pct exec "$CTID" -- dpkg -s nfs-common &>/dev/null; then
        echo "$(translate "NFS Client: INSTALLED")"
        
        # Check showmount
        if pct exec "$CTID" -- which showmount >/dev/null 2>&1; then
            echo "$(translate "NFS Client Tools: AVAILABLE")"
        else
            echo "$(translate "NFS Client Tools: NOT AVAILABLE")"
        fi
        
        # Check rpcbind service
        if pct exec "$CTID" -- systemctl is-active --quiet rpcbind 2>/dev/null; then
            echo "$(translate "RPC Bind Service: RUNNING")"
        else
            echo "$(translate "RPC Bind Service: STOPPED")"
            msg_warn "$(translate "Starting rpcbind service...")"
            pct exec "$CTID" -- systemctl start rpcbind 2>/dev/null || true
        fi
        
        echo ""
        echo "$(translate "Current NFS mounts:")"
        CURRENT_MOUNTS=$(pct exec "$CTID" -- mount | grep -E "type nfs|:.*on.*nfs" 2>/dev/null || true)
        if [[ -n "$CURRENT_MOUNTS" ]]; then
            echo "$CURRENT_MOUNTS"
        else
            # Check for active NFS mounts from fstab
            ACTIVE_NFS_MOUNTS=$(pct exec "$CTID" -- grep "nfs" /etc/fstab 2>/dev/null | grep -v "^#" | while read -r line; do
                MOUNT_POINT=$(echo "$line" | awk '{print $2}')
                if pct exec "$CTID" -- mount | grep -q "$MOUNT_POINT"; then
                    pct exec "$CTID" -- mount | grep "$MOUNT_POINT"
                fi
            done)
            
            if [[ -n "$ACTIVE_NFS_MOUNTS" ]]; then
                echo "$ACTIVE_NFS_MOUNTS"
            else
                echo "$(translate "No NFS mounts active.")"
            fi
        fi
        
        echo ""
        echo "$(translate "Testing network connectivity...")"
        
        # Test connectivity to known NFS servers from fstab
        FSTAB_SERVERS=$(pct exec "$CTID" -- grep "nfs" /etc/fstab 2>/dev/null | awk '{print $1}' | cut -d: -f1 | sort -u || true)
        if [[ -n "$FSTAB_SERVERS" ]]; then
            while IFS= read -r server; do
                if [[ -n "$server" ]]; then
                    echo -n "$(translate "Testing") $server: "
                    if pct exec "$CTID" -- ping -c 1 -W 2 "$server" >/dev/null 2>&1; then
                        echo -e "\033[1;92m$(translate "Reachable")\033[0m"
                        
                        # Test NFS port
                        echo -n "  $(translate "NFS port 2049"): "
                        if pct exec "$CTID" -- nc -z -w 2 "$server" 2049 2>/dev/null; then
                            echo -e "\033[1;92m$(translate "Open")\033[0m"
                        else
                            echo -e "\033[1;91m$(translate "Closed")\033[0m"
                        fi
                        
                        # Try to list exports
                        echo -n "  $(translate "Export list test"): "
                        if pct exec "$CTID" -- showmount -e "$server" >/dev/null 2>&1; then
                            echo -e "\033[1;92m$(translate "Available")\033[0m"
                        else
                            echo -e "\033[1;91m$(translate "Failed")\033[0m"
                        fi
                    else
                        echo -e "\033[1;91m$(translate "Unreachable")\033[0m"
                    fi
                fi
            done <<< "$FSTAB_SERVERS"
        else
            echo "$(translate "No NFS servers configured to test.")"
        fi
        
    else
        echo "$(translate "NFS Client: NOT INSTALLED")"
        echo ""
        echo "$(translate "Run 'Mount NFS Share' to install NFS client automatically.")"
    fi
    
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}


# === Main Menu ===
while true; do
    CHOICE=$(dialog --backtitle "ProxMenux" --title "$(translate "NFS Client Manager - CT") $CTID" \
    --menu "$(translate "Choose an option:")" 20 70 12 \
    "1" "$(translate "Mount NFS Share")" \
    "2" "$(translate "View Current Mounts")" \
    "3" "$(translate "Unmount NFS Share")" \
    "4" "$(translate "Test NFS Connectivity")" \
    "5" "$(translate "Exit")" \
    3>&1 1>&2 2>&3)
    
    RETVAL=$?
    if [[ $RETVAL -ne 0 ]]; then
        exit 0
    fi
    
    case $CHOICE in
        1) mount_nfs_share ;;
        2) view_nfs_mounts ;;
        3) unmount_nfs_share ;;
        4) test_nfs_connectivity ;;
        5) exit 0 ;;
        *) exit 0 ;;
    esac
done