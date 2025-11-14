#!/bin/bash
# ==========================================================
# ProxMenux CT - Samba Manager for Proxmox LXC
# ==========================================================
# Based on ProxMenux by MacRimi
# ==========================================================
# Description:
# This script allows you to manage Samba shares inside Proxmox CTs:
# - Create shared folders
# - View configured shares
# - Delete existing shares
# - Check Samba service status
# ==========================================================

# Configuration
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
CREDENTIALS_DIR="/etc/samba/credentials"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi


SHARE_COMMON_FILE="$LOCAL_SCRIPTS/global/share-common.func"
if ! source "$SHARE_COMMON_FILE" 2>/dev/null; then
    msg_error "$(translate "Could not load shared functions. Script cannot continue.")"
    exit 1
fi


load_language
initialize_cache


select_privileged_lxc


select_mount_point() {
    while true; do
        METHOD=$(whiptail --backtitle "ProxMenux" --title "$(translate "Select Folder")" \
            --menu "$(translate "How do you want to select the folder to share?")" 15 60 5 \
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
                
                MOUNT_POINT=$(whiptail --title "$(translate "Select Folder")" \
                    --menu "$(translate "Choose a folder to share:")" 20 60 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
                if [[ $? -ne 0 ]]; then
                    return 1
                fi
                [[ -n "$MOUNT_POINT" ]] && return 0
                ;;
            manual)
                CT_NAME=$(pct config "$CTID" | awk -F: '/hostname/ {print $2}' | xargs)
                DEFAULT_MOUNT_POINT="/mnt/${CT_NAME}_share"
                MOUNT_POINT=$(whiptail --title "$(translate "Mount Point")" \
                    --inputbox "$(translate "Enter the mount point for the shared folder (e.g., /mnt/myshare):")" \
                    10 70 "$DEFAULT_MOUNT_POINT" 3>&1 1>&2 2>&3)
                if [[ $? -ne 0 ]]; then
                    return 1
                fi
                clear
                if [[ -z "$MOUNT_POINT" ]]; then
                    whiptail --title "$(translate "Error")" --msgbox "\n$(translate "No mount point was specified.")" 8 50
                    continue
                else
                    return 0
                fi
                ;;
        esac
    done
}



create_share() {

    show_proxmenux_logo
    msg_title "$(translate "Create Samba server service")"
    sleep 2

    select_mount_point || return
    

    if ! pct exec "$CTID" -- test -d "$MOUNT_POINT"; then
        if whiptail --yesno "$(translate "The directory does not exist in the CT.")\n\n$MOUNT_POINT\n\n$(translate "Do you want to create it?")" 12 70 --title "$(translate "Create Directory")"; then
            pct exec "$CTID" -- mkdir -p "$MOUNT_POINT"
            msg_ok "$(translate "Directory created successfully.")"
        else
            msg_error "$(translate "Directory does not exist and was not created.")"
            return
        fi
    fi
    
    

    if pct exec "$CTID" -- dpkg -s samba &>/dev/null; then
        SAMBA_INSTALLED=true
    else
        SAMBA_INSTALLED=false
    fi
    

    if [ "$SAMBA_INSTALLED" = false ]; then
        echo -e "${TAB}$(translate "Installing Samba server packages inside the CT...")"
        pct exec "$CTID" -- bash -c "apt-get update && apt-get install -y samba samba-common-bin acl"
        
        USERNAME=$(whiptail --inputbox "$(translate "Enter the Samba username:")" 10 60 "proxmenux" --title "$(translate "Samba User")" 3>&1 1>&2 2>&3)
        [[ -z "$USERNAME" ]] && msg_error "$(translate "No username provided.")" && return
        
        while true; do
            PASSWORD1=$(whiptail --passwordbox "$(translate "Enter the password for Samba user:")" 10 60 --title "$(translate "Samba Password")" 3>&1 1>&2 2>&3)
            [[ -z "$PASSWORD1" ]] && msg_error "$(translate "No password provided.")" && return
            PASSWORD2=$(whiptail --passwordbox "$(translate "Confirm the password:")" 10 60 --title "$(translate "Confirm Password")" 3>&1 1>&2 2>&3)
            [[ -z "$PASSWORD2" ]] && msg_error "$(translate "Password confirmation is required.")" && return
            
            if [[ "$PASSWORD1" != "$PASSWORD2" ]]; then
                whiptail --title "$(translate "Password Mismatch")" --msgbox "$(translate "The passwords do not match. Please try again.")" 10 60
            else
                PASSWORD="$PASSWORD1"
                break
            fi
        done
        
        if ! pct exec "$CTID" -- id "$USERNAME" &>/dev/null; then
            pct exec "$CTID" -- adduser --disabled-password --gecos "" "$USERNAME"
        fi
        pct exec "$CTID" -- bash -c "echo -e '$PASSWORD\n$PASSWORD' | smbpasswd -a '$USERNAME'"
        
        msg_ok "$(translate "Samba server installed successfully.")"
    else
        USERNAME=$(pct exec "$CTID" -- pdbedit -L | awk -F: '{print $1}' | head -n1)
        msg_ok "$(translate "Samba server is already installed.")"
        echo -e "$(translate "Detected existing Samba user:") $USERNAME"
    fi
    

    IS_MOUNTED=$(pct exec "$CTID" -- mount | grep "$MOUNT_POINT" || true)
    if [[ -n "$IS_MOUNTED" ]]; then
        msg_info "$(translate "Detected a mounted directory from host. Setting up shared group...")"
        
        SHARE_GID=999
        GROUP_EXISTS=$(pct exec "$CTID" -- getent group sharedfiles || true)
        GID_IN_USE=$(pct exec "$CTID" -- getent group "$SHARE_GID" | cut -d: -f1 || true)
        
        if [[ -z "$GROUP_EXISTS" ]]; then
            if [[ -z "$GID_IN_USE" ]]; then
                pct exec "$CTID" -- groupadd -g "$SHARE_GID" sharedfiles
                msg_ok "$(translate "Group 'sharedfiles' created with GID $SHARE_GID")"
            else
                pct exec "$CTID" -- groupadd sharedfiles
                msg_warn "$(translate "GID $SHARE_GID already in use. Group 'sharedfiles' created with dynamic GID.")"
            fi
        else
            msg_ok "$(translate "Group 'sharedfiles' already exists inside the CT")"
        fi
        
        if pct exec "$CTID" -- getent group sharedfiles >/dev/null; then
            pct exec "$CTID" -- usermod -aG sharedfiles "$USERNAME"
            pct exec "$CTID" -- chown root:sharedfiles "$MOUNT_POINT"
            pct exec "$CTID" -- chmod 2775 "$MOUNT_POINT"
        else
            msg_error "$(translate "Group 'sharedfiles' was not created successfully. Skipping chown/usermod.")"
        fi
        
        HAS_ACCESS=$(pct exec "$CTID" -- su -s /bin/bash -c "test -w '$MOUNT_POINT' && echo yes || echo no" "$USERNAME" 2>/dev/null)
        if [ "$HAS_ACCESS" = "no" ]; then
            pct exec "$CTID" -- setfacl -R -m "u:$USERNAME:rwx" "$MOUNT_POINT"
            msg_warn "$(translate "ACL permissions applied to allow write access for user:") $USERNAME"
        else
            msg_ok "$(translate "Write access confirmed for user:") $USERNAME"
        fi
    else
        msg_ok "$(translate "No shared mount detected. Applying standard local access.")"
        pct exec "$CTID" -- chown -R "$USERNAME:$USERNAME" "$MOUNT_POINT"
        pct exec "$CTID" -- chmod -R 755 "$MOUNT_POINT"
        
        HAS_ACCESS=$(pct exec "$CTID" -- su -s /bin/bash -c "test -w '$MOUNT_POINT' && echo yes || echo no" "$USERNAME" 2>/dev/null)
        if [ "$HAS_ACCESS" = "no" ]; then
            pct exec "$CTID" -- setfacl -R -m "u:$USERNAME:rwx" "$MOUNT_POINT"
            msg_warn "$(translate "ACL permissions applied for local access for user:") $USERNAME"
        else
            msg_ok "$(translate "Write access confirmed for user:") $USERNAME"
        fi
    fi
    

    SHARE_OPTIONS=$(whiptail --title "$(translate "Share Options")" --menu "$(translate "Select share permissions:")" 15 70 3 \
    "rw" "$(translate "Read-Write access")" \
    "ro" "$(translate "Read-Only access")" \
    "custom" "$(translate "Custom options")" 3>&1 1>&2 2>&3)
    
    SHARE_NAME=$(basename "$MOUNT_POINT")
    
    case "$SHARE_OPTIONS" in
        rw)
            CONFIG=$(cat <<EOF
[$SHARE_NAME]
    comment = Shared folder for $USERNAME
    path = $MOUNT_POINT
    read only = no
    writable = yes
    browseable = yes
    guest ok = no
    valid users = $USERNAME
    force group = sharedfiles
    create mask = 0664
    directory mask = 2775
    force create mode = 0664
    force directory mode = 2775
    veto files = /lost+found/
EOF
)
            ;;
        ro)
            CONFIG=$(cat <<EOF
[$SHARE_NAME]
    comment = Read-only shared folder for $USERNAME
    path = $MOUNT_POINT
    read only = yes
    writable = no
    browseable = yes
    guest ok = no
    valid users = $USERNAME
    force group = sharedfiles
    veto files = /lost+found/
EOF
)
            ;;
        custom)
            CUSTOM_CONFIG=$(whiptail --inputbox "$(translate "Enter custom Samba configuration for this share:")" 15 80 "read only = no\nwritable = yes\nbrowseable = yes\nguest ok = no" --title "$(translate "Custom Configuration")" 3>&1 1>&2 2>&3)
            CONFIG=$(cat <<EOF
[$SHARE_NAME]
    comment = Custom shared folder for $USERNAME
    path = $MOUNT_POINT
    valid users = $USERNAME
    force group = sharedfiles
    $CUSTOM_CONFIG
    veto files = /lost+found/
EOF
)
            ;;
        *)
            CONFIG=$(cat <<EOF
[$SHARE_NAME]
    comment = Shared folder for $USERNAME
    path = $MOUNT_POINT
    read only = no
    writable = yes
    browseable = yes
    guest ok = no
    valid users = $USERNAME
    force group = sharedfiles
    create mask = 0664
    directory mask = 2775
    force create mode = 0664
    force directory mode = 2775
    veto files = /lost+found/
EOF
)
            ;;
    esac
    

    if pct exec "$CTID" -- grep -q "\[$SHARE_NAME\]" /etc/samba/smb.conf; then
        msg_warn "$(translate "The share already exists in smb.conf:") [$SHARE_NAME]"
        if whiptail --yesno "$(translate "Do you want to update the existing share?")" 10 60 --title "$(translate "Update Share")"; then
 
            pct exec "$CTID" -- sed -i "/^\[$SHARE_NAME\]/,/^$/d" /etc/samba/smb.conf
            pct exec "$CTID" -- bash -c "echo '$CONFIG' >> /etc/samba/smb.conf"
            msg_ok "$(translate "Share updated successfully.")"
        else
            return
        fi
    else
        msg_ok "$(translate "Adding new share to smb.conf...")"
        pct exec "$CTID" -- bash -c "echo '$CONFIG' >> /etc/samba/smb.conf"
        msg_ok "$(translate "Share added successfully.")"
    fi
    

    pct exec "$CTID" -- systemctl restart smbd.service
    

    CT_IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
    
    echo -e ""
    msg_ok "$(translate "Samba share created successfully!")"
    echo -e ""
    echo -e "${TAB}${BOLD}$(translate "Connection details:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Server IP:")${CL}  ${BL}$CT_IP${CL}"
    echo -e "${TAB}${BGN}$(translate "Share name:")${CL} ${BL}$SHARE_NAME${CL}"
    echo -e "${TAB}${BGN}$(translate "Share path:")${CL} ${BL}$MOUNT_POINT${CL}"
    echo -e "${TAB}${BGN}$(translate "Username:")${CL} ${BL}$USERNAME${CL}"
    echo -e
    
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}




view_shares() {
    show_proxmenux_logo
    msg_title "$(translate "View Current Shares")"
    
    echo -e "$(translate "Current Samba shares in CT") $CTID:"
    echo "=================================="
    
    if pct exec "$CTID" -- test -f /etc/samba/smb.conf; then

        SHARES=$(pct exec "$CTID" -- awk '/^\[.*\]/ && !/^\[global\]/ && !/^\[homes\]/ && !/^\[printers\]/ {print $0}' /etc/samba/smb.conf)
        if [[ -n "$SHARES" ]]; then

            while IFS= read -r share_line; do
                if [[ -n "$share_line" ]]; then
                    SHARE_NAME=$(echo "$share_line" | sed 's/\[//g' | sed 's/\]//g')
                    SHARE_PATH=$(pct exec "$CTID" -- awk "/^\[$SHARE_NAME\]/,/^$/ {if(/path =/) print \$3}" /etc/samba/smb.conf)
                    echo "$share_line -> $SHARE_PATH"
                fi
            done <<< "$SHARES"
            

            CT_IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
            USERNAME=$(pct exec "$CTID" -- pdbedit -L | awk -F: '{print $1}' | head -n1)
            
            echo ""
            echo "=================================="
            echo -e "${TAB}${BOLD}$(translate "Connection Details:")${CL}"
            echo -e "${TAB}${BGN}$(translate "Server IP:")${CL}  ${BL}$CT_IP${CL}"
            echo -e "${TAB}${BGN}$(translate "Username:")${CL}  ${BL}$USERNAME${CL}"
            echo ""
            
            echo -e "${TAB}${BOLD}$(translate "Available Shares:")${CL}"
            while IFS= read -r share_line; do
                if [[ -n "$share_line" ]]; then
                    SHARE_NAME=$(echo "$share_line" | sed 's/\[//g' | sed 's/\]//g')
                    SHARE_PATH=$(pct exec "$CTID" -- awk "/^\[$SHARE_NAME\]/,/^$/ {if(/path =/) print \$3}" /etc/samba/smb.conf)
                    echo -e "${TAB}${BGN}$(translate "Share name:")${CL} ${BL}$SHARE_NAME${CL}"
                    echo -e "${TAB}${BGN}$(translate "Share path:")${CL} ${BL}$SHARE_PATH${CL}"
                    echo -e "${TAB}${BGN}$(translate "Windows path:")${CL} ${YW}\\\\$CT_IP\\$SHARE_NAME${CL}"
                    echo -e "${TAB}${BGN}$(translate "Linux/Mac path:")${CL} ${YW}smb://$CT_IP/$SHARE_NAME${CL}"
                    echo ""
                fi
            done <<< "$SHARES"
            
        else
            echo "$(translate "No shares configured.")"
        fi
    else
        echo "$(translate "/etc/samba/smb.conf file does not exist.")"
    fi
    
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}




delete_share() {
    if ! pct exec "$CTID" -- test -f /etc/samba/smb.conf; then
        dialog --backtitle "ProxMenux" --title "$(translate "Error")" --msgbox "\n$(translate "No smb.conf file found.")" 8 50
        return
    fi
    

    SHARES=$(pct exec "$CTID" -- awk '/^\[.*\]/ && !/^\[global\]/ && !/^\[homes\]/ && !/^\[printers\]/ {gsub(/\[|\]/, ""); print NR, $0}' /etc/samba/smb.conf)
    
    if [[ -z "$SHARES" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Shares")" --msgbox "\n$(translate "No shares found in smb.conf.")" 8 60
        return
    fi
    
    OPTIONS=()
    while read -r line; do
        [[ -z "$line" ]] && continue
        NUM=$(echo "$line" | awk '{print $1}')
        SHARE_NAME=$(echo "$line" | awk '{print $2}')
        SHARE_PATH=$(pct exec "$CTID" -- awk "/^\[$SHARE_NAME\]/,/^$/ {if(/path =/) print \$3}" /etc/samba/smb.conf)
        [[ -z "$SHARE_NAME" ]] && continue
        OPTIONS+=("$SHARE_NAME" "$SHARE_NAME -> $SHARE_PATH")
    done <<< "$SHARES"
    
    SELECTED_SHARE=$(dialog --backtitle "ProxMenux" --title "$(translate "Delete Share")" --menu "$(translate "Select a share to delete:")" 20 70 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [ -z "$SELECTED_SHARE" ] && return
    
    SHARE_PATH=$(pct exec "$CTID" -- awk "/^\[$SELECTED_SHARE\]/,/^$/ {if(/path =/) print \$3}" /etc/samba/smb.conf)
    if whiptail --yesno "$(translate "Are you sure you want to delete this share?")\n\n$(translate "Share name:"): $SELECTED_SHARE\n$(translate "Share path:"): $SHARE_PATH" 12 70 --title "$(translate "Confirm Deletion")"; then
        show_proxmenux_logo
        msg_title "$(translate "Delete Share")"
        

        pct exec "$CTID" -- sed -i "/^\[$SELECTED_SHARE\]/,/^$/d" /etc/samba/smb.conf
        pct exec "$CTID" -- systemctl restart smbd.service
        msg_ok "$(translate "Share deleted and Samba service restarted.")"
    fi
    
    echo -e
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

check_samba_status() {
    show_proxmenux_logo
    msg_title "$(translate "Check Samba Status")"
    
    echo -e "$(translate "Samba Service Status in CT") $CTID:"
    echo "=================================="
    

    if pct exec "$CTID" -- dpkg -s samba &>/dev/null; then
        echo "$(translate "Samba Server: INSTALLED")"
        

        if pct exec "$CTID" -- systemctl is-active --quiet smbd; then
            echo "$(translate "Samba Service: RUNNING")"
        else
            echo "$(translate "Samba Service: STOPPED")"
        fi
        

        if pct exec "$CTID" -- systemctl is-active --quiet nmbd; then
            echo "$(translate "NetBIOS Service: RUNNING")"
        else
            echo "$(translate "NetBIOS Service: STOPPED")"
        fi
        

        echo ""
        echo "$(translate "Listening ports:")"
        pct exec "$CTID" -- ss -tlnp | grep -E ':(139|445)' || echo "$(translate "No Samba ports found")"
        

        echo ""
        echo "$(translate "Samba users:")"
        pct exec "$CTID" -- pdbedit -L 2>/dev/null || echo "$(translate "No Samba users found")"
        
    else
        echo "$(translate "Samba Server: NOT INSTALLED")"
    fi
    
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}



uninstall_samba() {

    if ! pct exec "$CTID" -- dpkg -s samba &>/dev/null; then
        dialog --backtitle "ProxMenux" --title "$(translate "Samba Not Installed")" --msgbox "\n$(translate "Samba server is not installed in this CT.")" 8 60
        return
    fi
    
    if ! whiptail --title "$(translate "Uninstall Samba Server")" \
        --yesno "$(translate "WARNING: This will completely remove Samba server from the CT.")\n\n$(translate "This action will:")\n$(translate "• Stop all Samba services")\n$(translate "• Remove all shares")\n$(translate "• Remove all Samba users")\n$(translate "• Uninstall Samba packages")\n$(translate "• Remove Samba groups")\n\n$(translate "Are you sure you want to continue?")" \
        18 70; then
        return
    fi

    
    show_proxmenux_logo
    msg_title "$(translate "Uninstall Samba Server")"
    

    msg_info "$(translate "Stopping Samba services...")"
    pct exec "$CTID" -- systemctl stop smbd 2>/dev/null || true
    pct exec "$CTID" -- systemctl stop nmbd 2>/dev/null || true
    pct exec "$CTID" -- systemctl disable smbd 2>/dev/null || true
    pct exec "$CTID" -- systemctl disable nmbd 2>/dev/null || true
    msg_ok "$(translate "Samba services stopped and disabled.")"
    

    if pct exec "$CTID" -- test -f /etc/samba/smb.conf; then
        pct exec "$CTID" -- cp /etc/samba/smb.conf /etc/samba/smb.conf.backup.$(date +%Y%m%d_%H%M%S)
        msg_ok "$(translate "Samba configuration backed up.")"
    fi
    

    SAMBA_USERS=$(pct exec "$CTID" -- pdbedit -L 2>/dev/null | awk -F: '{print $1}' || true)
    if [[ -n "$SAMBA_USERS" ]]; then
        while IFS= read -r user; do
            if [[ -n "$user" ]]; then
                pct exec "$CTID" -- smbpasswd -x "$user" 2>/dev/null || true
            fi
        done <<< "$SAMBA_USERS"
        msg_ok "$(translate "Samba users removed.")"
    fi
    


    pct exec "$CTID" -- apt-get remove --purge -y samba samba-common-bin samba-common 2>/dev/null || true
    pct exec "$CTID" -- apt-get autoremove -y 2>/dev/null || true
    msg_ok "$(translate "Samba packages removed.")"
    


    if pct exec "$CTID" -- getent group sharedfiles >/dev/null 2>&1; then

        GROUP_USERS=$(pct exec "$CTID" -- getent group sharedfiles | cut -d: -f4)
        if [[ -z "$GROUP_USERS" ]]; then
            pct exec "$CTID" -- groupdel sharedfiles 2>/dev/null || true
            msg_ok "$(translate "Samba group removed.")"
        else
            msg_warn "$(translate "Samba group kept (has users assigned).")"
        fi
    fi
    
    msg_info "$(translate "Cleaning up Samba directories...")"
    pct exec "$CTID" -- pkill -f smbd 2>/dev/null || true
    pct exec "$CTID" -- pkill -f nmbd 2>/dev/null || true
    
    pct exec "$CTID" -- rm -rf /var/lib/samba 2>/dev/null || true
    pct exec "$CTID" -- rm -rf /var/cache/samba 2>/dev/null || true
    
    sleep 2
    msg_ok "$(translate "Samba server has been completely uninstalled!")"
    echo -e ""
    echo -e "${TAB}${BOLD}$(translate "Uninstallation Summary:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Services:")${CL} ${BL}$(translate "Stopped and disabled")${CL}"
    echo -e "${TAB}${BGN}$(translate "Packages:")${CL} ${BL}$(translate "Removed")${CL}"
    echo -e "${TAB}${BGN}$(translate "Users:")${CL} ${BL}$(translate "Removed")${CL}"
    echo -e "${TAB}${BGN}$(translate "Configuration:")${CL} ${BL}$(translate "Backed up and cleared")${CL}"
    echo -e "${TAB}${BGN}$(translate "Groups:")${CL} ${BL}$(translate "Cleaned up")${CL}"
    echo -e
    
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}


# === Main Menu ===
while true; do
    CHOICE=$(dialog --backtitle "ProxMenux" --title "$(translate "Samba Manager - CT") $CTID" --menu "$(translate "Choose an option:")" 20 70 12 \
    "1" "$(translate "Create Samba server service")" \
    "2" "$(translate "View Current Shares")" \
    "3" "$(translate "Delete Share")" \
    "4" "$(translate "Check Samba Status")" \
    "5" "$(translate "Uninstall Samba Server")" \
    "6" "$(translate "Exit")" 3>&1 1>&2 2>&3)
    
    case $CHOICE in
        1) create_share ;;
        2) view_shares ;;
        3) delete_share ;;
        4) check_samba_status ;;
        5) uninstall_samba ;;
        6) exit 0 ;;
        *) exit 0 ;;
    esac
done
