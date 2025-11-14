#!/bin/bash
# ==========================================================
# ProxMenux Host - NFS Host Manager for Proxmox Host
# ==========================================================
# Based on ProxMenux by MacRimi
# ==========================================================
# Description:
# This script allows you to manage NFS client mounts on Proxmox Host:
# - Mount external NFS shares on the host
# - Configure permanent mounts
# - Auto-discover NFS servers
# - Integrate with Proxmox storage system
# ==========================================================

# Configuration
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# Load common share functions
SHARE_COMMON_FILE="$LOCAL_SCRIPTS/global/share-common.func"
if ! source "$SHARE_COMMON_FILE" 2>/dev/null; then
    msg_warn "$(translate "Could not load shared functions. Using fallback methods.")"
    SHARE_COMMON_LOADED=false
else
    SHARE_COMMON_LOADED=true
fi



discover_nfs_servers() {
    show_proxmenux_logo
    msg_title "$(translate "Mount NFS Share on Host")"
    msg_info "$(translate "Scanning network for NFS servers...")"

    HOST_IP=$(hostname -I | awk '{print $1}')
    NETWORK=$(echo "$HOST_IP" | cut -d. -f1-3).0/24

    if ! which nmap >/dev/null 2>&1; then
        apt-get install -y nmap &>/dev/null
    fi

    SERVERS=$(nmap -p 2049 --open "$NETWORK" 2>/dev/null | grep -B 4 "2049/tcp open" | grep "Nmap scan report" | awk '{print $5}' | sort -u || true)
    
    if [[ -z "$SERVERS" ]]; then
        cleanup
        dialog --clear --title "$(translate "No Servers Found")" --msgbox "$(translate "No NFS servers found on the network.")\n\n$(translate "You can add servers manually.")" 10 60
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
        dialog --clear --title "$(translate "No Valid Servers")" --msgbox "$(translate "No accessible NFS servers found.")" 8 50
        return 1
    fi
    cleanup
    NFS_SERVER=$(whiptail --backtitle "ProxMenux" --title "$(translate "Select NFS Server")" --menu "$(translate "Choose an NFS server:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
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
                dialog --title "$(translate "No Recent Servers")" --msgbox "\n$(translate "No recent NFS servers found.")" 8 50
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
    if ! which showmount >/dev/null 2>&1; then
        whiptail --title "$(translate "NFS Client Error")" \
                 --msgbox "$(translate "showmount command is not working properly.")\n\n$(translate "Please check the installation.")" \
                 10 60
        return 1
    fi

    if ! ping -c 1 -W 3 "$NFS_SERVER" >/dev/null 2>&1; then
        whiptail --title "$(translate "Connection Error")" \
               --msgbox "$(translate "Cannot reach server") $NFS_SERVER\n\n$(translate "Please check:")\n• $(translate "Server IP/hostname is correct")\n• $(translate "Network connectivity")\n• $(translate "Server is online")" \
               12 70
        return 1
    fi

    if ! nc -z -w 3 "$NFS_SERVER" 2049 2>/dev/null; then
        whiptail --title "$(translate "NFS Port Error")" \
               --msgbox "$(translate "NFS port (2049) is not accessible on") $NFS_SERVER\n\n$(translate "Please check:")\n• $(translate "NFS server is running")\n• $(translate "Firewall settings")\n• $(translate "NFS service is enabled")" \
               12 70
        return 1
    fi

    EXPORTS_OUTPUT=$(showmount -e "$NFS_SERVER" 2>&1)
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

    OPTIONS=()
    while IFS= read -r export_line; do
        if [[ -n "$export_line" ]]; then
            EXPORT_PATH=$(echo "$export_line" | awk '{print $1}')
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


select_host_mount_point() {
    local export_name=$(basename "$NFS_EXPORT")
    local default_path="/mnt/shared_nfs_${export_name}"

    MOUNT_POINT=$(pmx_select_host_mount_point "$(translate "NFS Mount Point")" "$default_path")
    [[ -n "$MOUNT_POINT" ]] && return 0 || return 1
}



configure_host_mount_options() {
    MOUNT_TYPE=$(whiptail --title "$(translate "Mount Options")" --menu "$(translate "Select mount configuration:")" 15 70 4 \
    "1"     "$(translate "Default options read/write")" \
    "2"    "$(translate "Read-only mount")" \
    "3"      "$(translate "Enter custom options")" 3>&1 1>&2 2>&3)
    
    [[ $? -ne 0 ]] && return 1
    
    case "$MOUNT_TYPE" in
        1)
            MOUNT_OPTIONS="rw,hard,nofail,rsize=131072,wsize=131072,timeo=600,retrans=2" 
            ;;
        2)
            MOUNT_OPTIONS="ro,hard,nofail,rsize=131072,wsize=131072,timeo=600,retrans=2" 
            ;;
        3)

            MOUNT_OPTIONS=$(whiptail --inputbox "$(translate "Enter custom mount options:")" \
                10 70 "rw,hard,nofail,rsize=131072,wsize=131072,timeo=600,retrans=2" \
                --title "$(translate "Custom Options")" 3>&1 1>&2 2>&3)
            [[ $? -ne 0 ]] && return 1
            [[ -z "$MOUNT_OPTIONS" ]] && MOUNT_OPTIONS="rw,hard,nofail"
            ;;
        *)
            MOUNT_OPTIONS="rw,hard,nofail,rsize=131072,wsize=131072,timeo=600,retrans=2"
            ;;
    esac

    if whiptail --yesno "$(translate "Do you want to make this mount permanent?")\n\n$(translate "This will add the mount to /etc/fstab so it persists after reboot.")" 10 70 --title "$(translate "Permanent Mount")"; then
        PERMANENT_MOUNT=true
    else
        if [[ $? -eq 1 ]]; then
            PERMANENT_MOUNT=false
        else
            return 1
        fi
    fi

    
    TEMP_MOUNT="/tmp/nfs_test_$$"
    mkdir -p "$TEMP_MOUNT" 2>/dev/null
    
    NFS_PATH="$NFS_SERVER:$NFS_EXPORT"
    if timeout 10 mount -t nfs -o ro,soft,timeo=5 "$NFS_PATH" "$TEMP_MOUNT" 2>/dev/null; then
        umount "$TEMP_MOUNT" 2>/dev/null || true
        rmdir "$TEMP_MOUNT" 2>/dev/null || true
        msg_ok "$(translate "NFS export is accessible")"
        

        if whiptail --yesno "$(translate "Do you want to add this as Proxmox storage?")\n\n$(translate "This will make the NFS share available as storage in Proxmox web interface.")" 10 70 --title "$(translate "Proxmox Storage")"; then
            PROXMOX_STORAGE=true
            
            STORAGE_ID=$(whiptail --inputbox "$(translate "Enter storage ID for Proxmox:")" 10 60 "nfs-$(echo $NFS_SERVER | tr '.' '-')" --title "$(translate "Storage ID")" 3>&1 1>&2 2>&3)
            STORAGE_ID_RESULT=$?
            
            if [[ $STORAGE_ID_RESULT -ne 0 ]]; then
                if whiptail --yesno "$(translate "Storage ID input was cancelled.")\n\n$(translate "Do you want to continue without Proxmox storage integration?")" 10 70 --title "$(translate "Continue Without Storage")"; then
                    PROXMOX_STORAGE=false
                else
                    return 1
                fi
            else
                [[ -z "$STORAGE_ID" ]] && STORAGE_ID="nfs-$(echo $NFS_SERVER | tr '.' '-')"
            fi
        else
            DIALOG_RESULT=$?
            if [[ $DIALOG_RESULT -eq 1 ]]; then
                PROXMOX_STORAGE=false
            else
                return 1
            fi
        fi
    else

        rmdir "$TEMP_MOUNT" 2>/dev/null || true
        msg_warn "$(translate "NFS export accessibility test failed")"
        
        if whiptail --yesno "$(translate "The NFS export could not be validated for accessibility.")\n\n$(translate "This might be due to:")\n• $(translate "Network connectivity issues")\n• $(translate "Export permission restrictions")\n• $(translate "Firewall blocking access")\n\n$(translate "Do you want to continue mounting anyway?")\n$(translate "(Proxmox storage integration will be skipped)")" 16 80 --title "$(translate "Export Validation Failed")"; then
            PROXMOX_STORAGE=false
            msg_info2 "$(translate "Continuing without Proxmox storage integration due to accessibility issues.")"
            sleep 2
        else
            return 1
        fi
    fi
    
    return 0
}

validate_host_export_exists() {
    local server="$1"
    local export="$2"
    
    VALIDATION_OUTPUT=$(showmount -e "$server" 2>/dev/null | grep "^$export[[:space:]]")
    
    if [[ -n "$VALIDATION_OUTPUT" ]]; then
        return 0
    else
        show_proxmenux_logo
        echo -e
        msg_error "$(translate "Export not found on server:") $export"
        return 1
    fi
}

add_proxmox_nfs_storage() {
    local storage_id="$1"
    local server="$2"
    local export="$3"
    local content="${4:-backup,iso,vztmpl}"
    
    msg_info "$(translate "Starting Proxmox storage integration...")"
    
    if ! command -v pvesm >/dev/null 2>&1; then
        show_proxmenux_logo
        msg_error "$(translate "pvesm command not found. This should not happen on Proxmox.")"
        echo "Press Enter to continue..."
        read -r
        return 1
    fi
    
    msg_ok "$(translate "pvesm command found")"

    # Check if storage ID already exists
    if pvesm status "$storage_id" >/dev/null 2>&1; then
        msg_warn "$(translate "Storage ID already exists:") $storage_id"
        if ! whiptail --yesno "$(translate "Storage ID already exists. Do you want to remove and recreate it?")" 8 60 --title "$(translate "Storage Exists")"; then
            return 0 
        fi
        pvesm remove "$storage_id" 2>/dev/null || true
    fi
    
    msg_ok "$(translate "Storage ID is available")"

    
    # Let Proxmox handle NFS version negotiation automatically
    if pvesm_output=$(pvesm add nfs "$storage_id" \
        --server "$server" \
        --export "$export" \
        --content "$content" 2>&1); then
        
        msg_ok "$(translate "NFS storage added successfully!")"
        
        # Get the actual NFS version that Proxmox negotiated
        local nfs_version="Auto-negotiated"
        if pvesm config "$storage_id" 2>/dev/null | grep -q "options.*vers="; then
            nfs_version="v$(pvesm config "$storage_id" | grep "options" | grep -o "vers=[0-9.]*" | cut -d= -f2)"
        fi
        
        echo -e ""
        echo -e "${TAB}${BGN}$(translate "Storage ID:")${CL} ${BL}$storage_id${CL}"
        echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$server${CL}"
        echo -e "${TAB}${BGN}$(translate "Export:")${CL} ${BL}$export${CL}"
        echo -e "${TAB}${BGN}$(translate "Content Types:")${CL} ${BL}$content${CL}"
        echo -e "${TAB}${BGN}$(translate "NFS Version:")${CL} ${BL}$nfs_version${CL}"
        echo -e ""
        msg_ok "$(translate "Storage is now available in Proxmox web interface under Datacenter > Storage")"
        return 0
    else
        msg_error "$(translate "Failed to add NFS storage to Proxmox.")"
        echo "$(translate "Error details:"): $pvesm_output"
        msg_warn "$(translate "The NFS share is still mounted, but not added as Proxmox storage.")"
        msg_info2 "$(translate "You can add it manually through:")"
        echo -e "${TAB}• $(translate "Proxmox web interface: Datacenter > Storage > Add > NFS")"
        echo -e "${TAB}• $(translate "Command line:"): pvesm add nfs $storage_id --server $server --export $export --content backup,iso,vztmpl"
        return 1
    fi
}

prepare_host_directory() {
    local mount_point="$1"
    
    if [[ "$SHARE_COMMON_LOADED" == "true" ]]; then
        # Use common functions for advanced directory preparation
        local group_name
        group_name=$(pmx_choose_or_create_group "sharedfiles")
        if [[ -n "$group_name" ]]; then
            local host_gid
            host_gid=$(pmx_ensure_host_group "$group_name")
            if [[ -n "$host_gid" ]]; then
                pmx_prepare_host_shared_dir "$mount_point" "$group_name"
                pmx_share_map_set "$mount_point" "$group_name"
                msg_ok "$(translate "Directory prepared with shared group:") $group_name (GID: $host_gid)"
                return 0
            fi
        fi
        msg_warn "$(translate "Failed to use shared functions, using basic directory creation.")"
    fi
    
    # Fallback: basic directory creation
    if ! test -d "$mount_point"; then
        if mkdir -p "$mount_point"; then
            msg_ok "$(translate "Mount point created on host.")"
            return 0
        else
            msg_error "$(translate "Failed to create mount point on host.")"
            return 1
        fi
    fi
    return 0
}

mount_host_nfs_share() {
    if ! which showmount >/dev/null 2>&1; then
        msg_error "$(translate "NFS client tools not found. Please check Proxmox installation.")"
        return 1
    fi
    
    # Step 1: 
    select_nfs_server || return
    
    # Step 2: 
    select_nfs_export || return
    
    # Step 2.5: 
    if ! validate_host_export_exists "$NFS_SERVER" "$NFS_EXPORT"; then
        echo -e ""
        msg_error "$(translate "Cannot proceed with invalid export path.")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return
    fi
    
    # Step 3: 
    select_host_mount_point || return
    
    # Step 4: 
    configure_host_mount_options || return

    show_proxmenux_logo
    msg_title "$(translate "Mount NFS Share on Host")"
    msg_ok "$(translate "NFS server selected")"

    prepare_host_directory "$MOUNT_POINT" || return 1

    if mount | grep -q "$MOUNT_POINT"; then
        msg_warn "$(translate "Something is already mounted at") $MOUNT_POINT"
        if ! whiptail --yesno "$(translate "Do you want to unmount it first?")" 8 60 --title "$(translate "Already Mounted")"; then
            return
        fi
        umount "$MOUNT_POINT" 2>/dev/null || true
    fi

    NFS_PATH="$NFS_SERVER:$NFS_EXPORT"

    if mount -t nfs -o "$MOUNT_OPTIONS" "$NFS_PATH" "$MOUNT_POINT" > /dev/null 2>&1; then
        msg_ok "$(translate "NFS share mounted successfully on host!")"

        if touch "$MOUNT_POINT/.test_write" 2>/dev/null; then
            rm "$MOUNT_POINT/.test_write" 2>/dev/null
            msg_ok "$(translate "Write access confirmed.")"
        else
            msg_warn "$(translate "Read-only access (or no write permissions).")"
        fi

        if [[ "$PERMANENT_MOUNT" == "true" ]]; then
            sed -i "\|$MOUNT_POINT|d" /etc/fstab
            FSTAB_ENTRY="$NFS_PATH $MOUNT_POINT nfs $MOUNT_OPTIONS 0 0"
            echo "$FSTAB_ENTRY" >> /etc/fstab
            msg_ok "$(translate "Added to /etc/fstab for permanent mounting.")"

            msg_info "$(translate "Reloading systemd configuration...")"
            systemctl daemon-reload 2>/dev/null || true
            msg_ok "$(translate "Systemd configuration reloaded.")"
        fi

        if [[ "$PROXMOX_STORAGE" == "true" ]]; then
            add_proxmox_nfs_storage "$STORAGE_ID" "$NFS_SERVER" "$NFS_EXPORT" "$MOUNT_CONTENT"
        fi

        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Host Mount Information:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$NFS_SERVER${CL}"
        echo -e "${TAB}${BGN}$(translate "Export:")${CL} ${BL}$NFS_EXPORT${CL}"
        echo -e "${TAB}${BGN}$(translate "Host Mount Point:")${CL} ${BL}$MOUNT_POINT${CL}"
        echo -e "${TAB}${BGN}$(translate "Options:")${CL} ${BL}$MOUNT_OPTIONS${CL}"
        echo -e "${TAB}${BGN}$(translate "Permanent:")${CL} ${BL}$PERMANENT_MOUNT${CL}"
        if [[ "$PROXMOX_STORAGE" == "true" ]]; then
            echo -e "${TAB}${BGN}$(translate "Proxmox Storage ID:")${CL} ${BL}$STORAGE_ID${CL}"
        fi
        
    else
        msg_error "$(translate "Failed to mount NFS share on host.")"
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

view_host_nfs_mounts() {
    show_proxmenux_logo
    msg_title "$(translate "Current NFS Mounts on Host")"
    
    echo -e "$(translate "NFS mounts on Proxmox host:"):"
    echo "=================================="
    
    CURRENT_MOUNTS=$(mount | grep -E "type nfs|:.*on.*nfs" 2>/dev/null || true)
    if [[ -n "$CURRENT_MOUNTS" ]]; then
        echo -e "${BOLD}$(translate "Currently Mounted:")${CL}"
        echo "$CURRENT_MOUNTS"
        echo ""
    else
        echo "$(translate "No NFS shares currently mounted on host.")"
        echo ""
    fi
    
    FSTAB_NFS=$(grep "nfs" /etc/fstab 2>/dev/null || true)
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
                
                SERVER=$(echo "$NFS_PATH" | cut -d: -f1)
                EXPORT=$(echo "$NFS_PATH" | cut -d: -f2)
                
                echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$SERVER${CL}"
                echo -e "${TAB}${BGN}$(translate "Export:")${CL} ${BL}$EXPORT${CL}"
                echo -e "${TAB}${BGN}$(translate "Host Mount Point:")${CL} ${BL}$MOUNT_POINT${CL}"
                echo -e "${TAB}${BGN}$(translate "Options:")${CL} ${BL}$OPTIONS${CL}"
                
                if mount | grep -q "$MOUNT_POINT"; then
                    echo -e "${TAB}${BGN}$(translate "Status:")${CL} ${GN}$(translate "Mounted")${CL}"
                else
                    echo -e "${TAB}${BGN}$(translate "Status:")${CL} ${RD}$(translate "Not Mounted")${CL}"
                fi
                echo ""
            fi
        done <<< "$FSTAB_NFS"
    else
        echo "$(translate "No NFS mounts found in fstab.")"
    fi

    echo ""
    echo "$(translate "Proxmox NFS Storage Status:")"
    if which pvesm >/dev/null 2>&1; then
        NFS_STORAGES=$(pvesm status 2>/dev/null | grep "nfs" || true)
        if [[ -n "$NFS_STORAGES" ]]; then
            echo "$NFS_STORAGES"
        else
            echo "$(translate "No NFS storage configured in Proxmox.")"
        fi
    else
        echo "$(translate "pvesm command not available.")"
    fi
        
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

unmount_host_nfs_share() {
    MOUNTS=$(mount | grep -E "type nfs|:.*on.*nfs" | awk '{print $3}' | sort -u || true)
    FSTAB_MOUNTS=$(grep -E "nfs" /etc/fstab 2>/dev/null | grep -v "^#" | awk '{print $2}' | sort -u || true)

    ALL_MOUNTS=$(echo -e "$MOUNTS\n$FSTAB_MOUNTS" | sort -u | grep -v "^$" || true)
    
    if [[ -z "$ALL_MOUNTS" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Mounts")" --msgbox "\n$(translate "No NFS mounts found on host.")" 8 50
        return
    fi
    
    OPTIONS=()
    while IFS= read -r mount_point; do
        if [[ -n "$mount_point" ]]; then
            NFS_PATH=$(mount | grep "$mount_point" | awk '{print $1}' || grep "$mount_point" /etc/fstab | awk '{print $1}' || echo "Unknown")
            SERVER=$(echo "$NFS_PATH" | cut -d: -f1)
            EXPORT=$(echo "$NFS_PATH" | cut -d: -f2)
            OPTIONS+=("$mount_point" "$SERVER:$EXPORT")
        fi
    done <<< "$ALL_MOUNTS"
    
    SELECTED_MOUNT=$(dialog --backtitle "ProxMenux" --title "$(translate "Unmount NFS Share")" --menu "$(translate "Select mount point to unmount:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED_MOUNT" ]] && return

    NFS_PATH=$(mount | grep "$SELECTED_MOUNT" | awk '{print $1}' || grep "$SELECTED_MOUNT" /etc/fstab | awk '{print $1}' || echo "Unknown")
    SERVER=$(echo "$NFS_PATH" | cut -d: -f1)
    EXPORT=$(echo "$NFS_PATH" | cut -d: -f2)

    PROXMOX_STORAGE=""
    if which pvesm >/dev/null 2>&1; then
        NFS_STORAGES=$(pvesm status 2>/dev/null | grep "nfs" | awk '{print $1}' || true)
        while IFS= read -r storage_id; do
            if [[ -n "$storage_id" ]]; then
                STORAGE_INFO=$(pvesm config "$storage_id" 2>/dev/null || true)
                STORAGE_SERVER=$(echo "$STORAGE_INFO" | grep "server" | awk '{print $2}')
                STORAGE_EXPORT=$(echo "$STORAGE_INFO" | grep "export" | awk '{print $2}')
                if [[ "$STORAGE_SERVER" == "$SERVER" && "$STORAGE_EXPORT" == "$EXPORT" ]]; then
                    PROXMOX_STORAGE="$storage_id"
                    break
                fi
            fi
        done <<< "$NFS_STORAGES"
    fi

    CONFIRMATION_MSG="$(translate "Are you sure you want to unmount this NFS share?")\n\n$(translate "Mount Point:"): $SELECTED_MOUNT\n$(translate "Server:"): $SERVER\n$(translate "Export:"): $EXPORT\n\n$(translate "This will:")\n• $(translate "Unmount the NFS share")\n• $(translate "Remove from /etc/fstab")"
    
    if [[ -n "$PROXMOX_STORAGE" ]]; then
        CONFIRMATION_MSG="$CONFIRMATION_MSG\n• $(translate "Remove Proxmox storage:"): $PROXMOX_STORAGE"
    fi
    
    CONFIRMATION_MSG="$CONFIRMATION_MSG\n• $(translate "Remove mount point directory")"
    
    if whiptail --yesno "$CONFIRMATION_MSG" 16 80 --title "$(translate "Confirm Unmount")"; then
        show_proxmenux_logo
        msg_title "$(translate "Unmount NFS Share from Host")"
        
        if [[ -n "$PROXMOX_STORAGE" ]]; then
            if pvesm remove "$PROXMOX_STORAGE" 2>/dev/null; then
                msg_ok "$(translate "Proxmox storage removed successfully.")"
            else
                msg_warn "$(translate "Failed to remove Proxmox storage, continuing with unmount...")"
            fi
        fi

        if mount | grep -q "$SELECTED_MOUNT"; then
            if umount "$SELECTED_MOUNT"; then
                msg_ok "$(translate "Successfully unmounted.")"
            else
                msg_warn "$(translate "Failed to unmount. Trying force unmount...")"
                if umount -f "$SELECTED_MOUNT" 2>/dev/null; then
                    msg_ok "$(translate "Force unmount successful.")"
                else
                    msg_error "$(translate "Failed to unmount. Mount point may be busy.")"
                    echo -e "${TAB}$(translate "Try closing any applications using the mount point.")"
                fi
            fi
        fi

        msg_info "$(translate "Removing from /etc/fstab...")"
        sed -i "\|[[:space:]]$SELECTED_MOUNT[[:space:]]|d" /etc/fstab
        msg_ok "$(translate "Removed from /etc/fstab.")"
                
        echo -e ""
        msg_ok "$(translate "NFS share unmounted successfully from host!")"
        
        if [[ -n "$PROXMOX_STORAGE" ]]; then
            echo -e "${TAB}${BGN}$(translate "Proxmox storage removed:")${CL} ${BL}$PROXMOX_STORAGE${CL}"
        fi
        echo -e "${TAB}${BGN}$(translate "Mount point unmounted:")${CL} ${BL}$SELECTED_MOUNT${CL}"
        echo -e "${TAB}${BGN}$(translate "Removed from fstab:")${CL} ${BL}Yes${CL}"
    fi
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

manage_proxmox_storage() {
    if ! command -v pvesm >/dev/null 2>&1; then
        dialog --backtitle "ProxMenux" --title "$(translate "Error")" --msgbox "\n$(translate "pvesm command not found. This should not happen on Proxmox.")" 8 60
        return
    fi

    NFS_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "nfs" {print $1}')
    if [[ -z "$NFS_STORAGES" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No NFS Storage")" --msgbox "\n$(translate "No NFS storage found in Proxmox.")" 8 60
        return
    fi

    OPTIONS=()
    while IFS= read -r storage_id; do
        if [[ -n "$storage_id" ]]; then
            STORAGE_INFO=$(pvesm config "$storage_id" 2>/dev/null || true)
            SERVER=$(echo "$STORAGE_INFO" | grep "server" | awk '{print $2}')
            EXPORT=$(echo "$STORAGE_INFO" | grep "export" | awk '{print $2}')
            
            if [[ -n "$SERVER" && -n "$EXPORT" ]]; then
                OPTIONS+=("$storage_id" "$SERVER:$EXPORT")
            else
                OPTIONS+=("$storage_id" "$(translate "NFS Storage")")
            fi
        fi
    done <<< "$NFS_STORAGES"
    
    SELECTED_STORAGE=$(dialog --backtitle "ProxMenux" --title "$(translate "Manage Proxmox NFS Storage")" --menu "$(translate "Select storage to manage:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED_STORAGE" ]] && return

    STORAGE_INFO=$(pvesm config "$SELECTED_STORAGE" 2>/dev/null || true)
    SERVER=$(echo "$STORAGE_INFO" | grep "server" | awk '{print $2}')
    EXPORT=$(echo "$STORAGE_INFO" | grep "export" | awk '{print $2}')
    CONTENT=$(echo "$STORAGE_INFO" | grep "content" | awk '{print $2}')

    FSTAB_NFS=$(grep "nfs" /etc/fstab 2>/dev/null || true)
    if [[ -n "$FSTAB_NFS" ]]; then
        while IFS= read -r fstab_line; do
            if [[ -n "$fstab_line" && ! "$fstab_line" =~ ^# ]]; then
                NFS_PATH=$(echo "$fstab_line" | awk '{print $1}')
                MOUNT_POINT=$(echo "$fstab_line" | awk '{print $2}')
                OPTIONS=$(echo "$fstab_line" | awk '{print $4}')
                
                SERVER=$(echo "$NFS_PATH" | cut -d: -f1)
                EXPORT=$(echo "$NFS_PATH" | cut -d: -f2)
            fi
        done <<< "$FSTAB_NFS"
    fi

    if whiptail --yesno "$(translate "Are you sure you want to REMOVE storage") $SELECTED_STORAGE?\n\n$(translate "Server:"): $SERVER\n$(translate "Export:"): $EXPORT\n\n$(translate "WARNING: This will permanently remove the storage from Proxmox configuration.")\n$(translate "The NFS mount on the host will NOT be affected.")" 14 80 --title "$(translate "Remove Storage")"; then
        show_proxmenux_logo
        msg_title "$(translate "Remove Storage")"
        
        if pvesm remove "$SELECTED_STORAGE" 2>/dev/null; then
            msg_ok "$(translate "Storage removed successfully from Proxmox.")"
            echo -e ""
            msg_success "$(translate "Press Enter to return to menu...")"
            read -r
        else
            msg_error "$(translate "Failed to remove storage.")"
        fi
    fi
}

test_host_nfs_connectivity() {
    show_proxmenux_logo
    msg_title "$(translate "Test NFS Connectivity on Host")"
    
    echo -e "$(translate "NFS Client Status on Proxmox Host:"):"
    echo "=================================="

    if which showmount >/dev/null 2>&1; then
        echo "$(translate "NFS Client Tools: AVAILABLE")"

        if systemctl is-active --quiet rpcbind 2>/dev/null; then
            echo "$(translate "RPC Bind Service: RUNNING")"
        else
            echo "$(translate "RPC Bind Service: STOPPED")"
            msg_warn "$(translate "Starting rpcbind service...")"
            systemctl start rpcbind 2>/dev/null || true
        fi
        
        echo ""
        echo "$(translate "Current NFS mounts on host:")"
        CURRENT_MOUNTS=$(mount | grep -E "type nfs|:.*on.*nfs" 2>/dev/null || true)
        if [[ -n "$CURRENT_MOUNTS" ]]; then
            echo "$CURRENT_MOUNTS"
        else
            echo "$(translate "No NFS mounts active on host.")"
        fi
        
        echo ""
        echo "$(translate "Testing network connectivity...")"

        FSTAB_SERVERS=$(grep "nfs" /etc/fstab 2>/dev/null | awk '{print $1}' | cut -d: -f1 | sort -u || true)
        if [[ -n "$FSTAB_SERVERS" ]]; then
            while IFS= read -r server; do
                if [[ -n "$server" ]]; then
                    echo -n "$(translate "Testing") $server: "
                    if ping -c 1 -W 2 "$server" >/dev/null 2>&1; then
                        echo -e "${GN}$(translate "Reachable")${CL}"

                        echo -n "  $(translate "NFS port 2049"): "
                        if nc -z -w 2 "$server" 2049 2>/dev/null; then
                            echo -e "${GN}$(translate "Open")${CL}"
                        else
                            echo -e "${RD}$(translate "Closed")${CL}"
                        fi

                        echo -n "  $(translate "Export list test"): "
                        if showmount -e "$server" >/dev/null 2>&1; then
                            echo -e "${GN}$(translate "Available")${CL}"
                        else
                            echo -e "${RD}$(translate "Failed")${CL}"
                        fi
                    else
                        echo -e "${RD}$(translate "Unreachable")${CL}"
                    fi
                fi
            done <<< "$FSTAB_SERVERS"
        else
            echo "$(translate "No NFS servers configured to test.")"
        fi

        echo ""
        echo "$(translate "Proxmox NFS Storage Status:")"
        if which pvesm >/dev/null 2>&1; then
            NFS_STORAGES=$(pvesm status 2>/dev/null | grep "nfs" || true)
            if [[ -n "$NFS_STORAGES" ]]; then
                echo "$NFS_STORAGES"
            else
                echo "$(translate "No NFS storage configured in Proxmox.")"
            fi
        else
            echo "$(translate "pvesm command not available.")"
        fi
        
    else
        echo "$(translate "NFS Client Tools: NOT AVAILABLE")"
        echo ""
        echo "$(translate "This is unusual for Proxmox. NFS client tools should be installed.")"
    fi

    echo ""
    echo "$(translate "ProxMenux Extensions:")"
    if [[ "$SHARE_COMMON_LOADED" == "true" ]]; then
        echo "$(translate "Shared Functions: LOADED")"
        if [[ -f "$PROXMENUX_SHARE_MAP_DB" ]]; then
            MAPPED_DIRS=$(wc -l < "$PROXMENUX_SHARE_MAP_DB" 2>/dev/null || echo "0")
            echo "$(translate "Mapped directories:"): $MAPPED_DIRS"
        fi
    else
        echo "$(translate "Shared Functions: NOT LOADED (using fallback methods)")"
    fi
    
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

# === Main Menu ===
while true; do
    CHOICE=$(dialog --backtitle "ProxMenux" --title "$(translate "NFS Host Manager - Proxmox Host")" \
    --menu "$(translate "Choose an option:")" 22 80 14 \
    "1" "$(translate "Mount NFS Share on Host")" \
    "2" "$(translate "View Current Host NFS Mounts")" \
    "3" "$(translate "Unmount NFS Share from Host")" \
    "4" "$(translate "Remove Proxmox NFS Storage")" \
    "5" "$(translate "Test NFS Connectivity")" \
    "6" "$(translate "Exit")" \
    3>&1 1>&2 2>&3)
    
    RETVAL=$?
    if [[ $RETVAL -ne 0 ]]; then
        exit 0
    fi
    
    case $CHOICE in
        1) mount_host_nfs_share ;;
        2) view_host_nfs_mounts ;;
        3) unmount_host_nfs_share ;;
        4) manage_proxmox_storage ;;
        5) test_host_nfs_connectivity ;;
        6) exit 0 ;;
        *) exit 0 ;;
    esac
done
