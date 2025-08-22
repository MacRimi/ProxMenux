#!/bin/bash
# ==========================================================
# ProxMenu CT - Samba Client Manager for Proxmox LXC
# ==========================================================
# Based on ProxMenux by MacRimi
# ==========================================================
# Description:
# This script allows you to manage Samba/CIFS client mounts inside Proxmox CTs:
# - Mount Samba/CIFS shares (temporary and permanent)
# - View current mounts
# - Unmount and remove Samba shares
# - Auto-discover Samba servers
# - Manage credentials securely
# ==========================================================

# Configuration
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
CREDENTIALS_DIR="/etc/samba/credentials"

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

CTID=$(dialog --title "$(translate "Select CT")" --menu "$(translate "Select the CT to manage Samba client:")" 20 70 12 $CT_LIST 3>&1 1>&2 2>&3)
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

install_samba_client() {

    if pct exec "$CTID" -- dpkg -s cifs-utils &>/dev/null && pct exec "$CTID" -- dpkg -s smbclient &>/dev/null; then
        pct exec "$CTID" -- mkdir -p "$CREDENTIALS_DIR"
        pct exec "$CTID" -- chmod 700 "$CREDENTIALS_DIR"
        return 0
    fi

    show_proxmenux_logo
    msg_title "$(translate "Installing Samba Client")"
    msg_info "$(translate "Installing Samba/CIFS client packages...")"

    if ! pct exec "$CTID" -- apt-get update &>/dev/null; then
        msg_error "$(translate "Failed to update package list.")"
        return 1
    fi

    if ! pct exec "$CTID" -- apt-get install -y cifs-utils smbclient &>/dev/null; then
        msg_error "$(translate "Failed to install Samba client packages.")"
        return 1
    fi

    if ! pct exec "$CTID" -- which smbclient >/dev/null 2>&1; then
        msg_error "$(translate "smbclient command not found after installation.")"
        return 1
    fi
    if ! pct exec "$CTID" -- which mount.cifs >/dev/null 2>&1; then
        msg_error "$(translate "mount.cifs command not found after installation.")"
        return 1
    fi

    pct exec "$CTID" -- mkdir -p "$CREDENTIALS_DIR"
    pct exec "$CTID" -- chmod 700 "$CREDENTIALS_DIR"

    msg_ok "$(translate "Samba/CIFS client installed successfully.")"
    return 0
}


discover_samba_servers() {
    show_proxmenux_logo
    msg_title "$(translate "Samba LXC Manager")"
    msg_info "$(translate "Scanning network for Samba servers...")"


    HOST_IP=$(hostname -I | awk '{print $1}')
    NETWORK=$(echo "$HOST_IP" | cut -d. -f1-3).0/24


    for pkg in nmap samba-common-bin; do
        if ! which ${pkg%%-*} >/dev/null 2>&1; then
            apt-get install -y "$pkg" &>/dev/null
        fi
    done

    SERVERS=$(nmap -p 139,445 --open "$NETWORK" 2>/dev/null | grep -B 4 -E "(139|445)/tcp open" | grep "Nmap scan report" | awk '{print $5}' | sort -u || true)
    if [[ -z "$SERVERS" ]]; then
        cleanup
        whiptail --title "$(translate "No Servers Found")" --msgbox "$(translate "No Samba servers found on the network.")\n\n$(translate "You can add servers manually.")" 10 60
        return 1
    fi

    SERVER_LINES=()
    while IFS= read -r server; do
        [[ -z "$server" ]] && continue

        NB_NAME=$(nmblookup -A "$server" 2>/dev/null | awk '/<00> -.*B <ACTIVE>/ {print $1; exit}')

        if [[ -z "$NB_NAME" || "$NB_NAME" == "$server" || "$NB_NAME" == "address" || "$NB_NAME" == "-" ]]; then
            NB_NAME="Unknown"
        fi

        SERVER_LINES+=("$server|$NB_NAME ($server)")
    done <<< "$SERVERS"

    IFS=$'\n' SORTED=($(printf "%s\n" "${SERVER_LINES[@]}" | sort -t. -k1,1n -k2,2n -k3,3n -k4,4n))

    OPTIONS=()
    declare -A SERVER_IPS
    i=1
    for entry in "${SORTED[@]}"; do
        server="${entry%%|*}"
        label="${entry#*|}"
        OPTIONS+=("$i" "$label")
        SERVER_IPS["$i"]="$server"
        ((i++))
    done

    if [[ ${#OPTIONS[@]} -eq 0 ]]; then
        cleanup
        whiptail --title "$(translate "No Valid Servers")" --msgbox "$(translate "No accessible Samba servers found.")" 8 50
        return 1
    fi

    msg_ok "$(translate "Samba servers detected")"
    CHOICE=$(dialog --title "$(translate "Select Samba Server")" \
        --menu "$(translate "Choose a Samba server:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)

    if [[ -n "$CHOICE" ]]; then
        SAMBA_SERVER="${SERVER_IPS[$CHOICE]}"
        
        return 0
    else
        
        return 1
    fi
    
}

select_samba_server() {
    METHOD=$(dialog --title "$(translate "Samba Server Selection")" --menu "$(translate "How do you want to select the Samba server?")" 15 70 3 \
    "auto" "$(translate "Auto-discover servers on network")" \
    "manual" "$(translate "Enter server IP")" \
    "recent" "$(translate "Select from recent servers")" 3>&1 1>&2 2>&3)
    
    case "$METHOD" in
        auto)
            discover_samba_servers || return 1
            ;;
        manual)
            SAMBA_SERVER=$(whiptail --inputbox "$(translate "Enter Samba server IP:")" 10 60 --title "$(translate "Samba Server")" 3>&1 1>&2 2>&3)
            [[ -z "$SAMBA_SERVER" ]] && return 1
            ;;
        recent)

            RECENT=$(pct exec "$CTID" -- grep "cifs" /etc/fstab 2>/dev/null | awk '{print $1}' | cut -d/ -f3 | sort -u || true)
            if [[ -z "$RECENT" ]]; then
                whiptail --title "$(translate "No Recent Servers")" --msgbox "$(translate "No recent Samba servers found.")" 8 50
                return 1
            fi
            
            OPTIONS=()
            while IFS= read -r server; do
                [[ -n "$server" ]] && OPTIONS+=("$server" "$(translate "Recent Samba server")")
            done <<< "$RECENT"
            
            SAMBA_SERVER=$(whiptail --title "$(translate "Recent Samba Servers")" --menu "$(translate "Choose a recent server:")" 20 70 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
            [[ -z "$SAMBA_SERVER" ]] && return 1
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}






validate_guest_access() {
    local server="$1"
    
    show_proxmenux_logo
    msg_info "$(translate "Testing comprehensive guest access to server") $server..."
    
    GUEST_LIST_OUTPUT=$(smbclient -L "$server" -N 2>&1)
    GUEST_LIST_RESULT=$?
    
    if [[ $GUEST_LIST_RESULT -ne 0 ]]; then
        cleanup
        if echo "$GUEST_LIST_OUTPUT" | grep -qi "access denied\|logon failure"; then
            whiptail --title "$(translate "Guest Access Denied")" \
                   --msgbox "$(translate "Guest access is not allowed on this server.")\n\n$(translate "You need to use username and password authentication.")" \
                   10 70
        else
            whiptail --title "$(translate "Guest Access Error")" \
                   --msgbox "$(translate "Guest access failed.")\n\n$(translate "Error details:")\n$(echo "$GUEST_LIST_OUTPUT" | head -3)" \
                   12 70
        fi
        return 1
    fi
    sleep 2
    msg_ok "$(translate "Guest share listing successful")"

    GUEST_SHARES=$(echo "$GUEST_LIST_OUTPUT" | awk '/Disk/ && !/IPC\$/ && !/ADMIN\$/ && !/print\$/ {print $1}' | grep -v "^$")
    if [[ -z "$GUEST_SHARES" ]]; then
        whiptail --title "$(translate "No Guest Shares")" \
               --msgbox "$(translate "Guest access works for listing, but no shares are available.")\n\n$(translate "The server may require authentication for actual share access.")" \
               10 70
        return 1
    fi
    
    msg_ok "$(translate "Found guest-accessible shares:") $(echo "$GUEST_SHARES" | wc -l)"

    msg_info "$(translate "Step 2: Testing actual share access with guest...")"
    ACCESSIBLE_SHARES=""
    FAILED_SHARES=""
    sleep 1
    while IFS= read -r share; do
        if [[ -n "$share" ]]; then
            
            SHARE_TEST_OUTPUT=$(smbclient "//$server/$share" -N -c "ls" 2>&1)
            SHARE_TEST_RESULT=$?
            
            if [[ $SHARE_TEST_RESULT -eq 0 ]]; then
                echo -e
                msg_ok "$(translate "Guest access confirmed for share:") $share"
                echo -e
                ACCESSIBLE_SHARES="$ACCESSIBLE_SHARES$share\n"
            else
                msg_error "$(translate "Guest access denied for share:") $share"
                FAILED_SHARES="$FAILED_SHARES$share\n"
                
                if echo "$SHARE_TEST_OUTPUT" | grep -qi "access denied\|logon failure\|authentication"; then
                    msg_warn "  $(translate "Reason: Authentication required")"
                elif echo "$SHARE_TEST_OUTPUT" | grep -qi "permission denied"; then
                    msg_warn "  $(translate "Reason: Permission denied")"
                else
                    msg_warn "  $(translate "Reason: Access denied")"
                fi
            fi
        fi
    done <<< "$GUEST_SHARES"
    

    ACCESSIBLE_COUNT=$(echo -e "$ACCESSIBLE_SHARES" | grep -v "^$" | wc -l)
    FAILED_COUNT=$(echo -e "$FAILED_SHARES" | grep -v "^$" | wc -l)
    
    echo -e ""
    msg_info2 "$(translate "Guest Access Validation Results:")"
    echo -e "${TAB}${BGN}$(translate "Shares found:")${CL} ${BL}$(echo "$GUEST_SHARES" | wc -l)${CL}"
    echo -e "${TAB}${BGN}$(translate "Guest accessible:")${CL} ${GN}$ACCESSIBLE_COUNT${CL}"
    echo -e "${TAB}${BGN}$(translate "Authentication required:")${CL} ${YW}$FAILED_COUNT${CL}"
    
    if [[ $ACCESSIBLE_COUNT -gt 0 ]]; then
        msg_ok "$(translate "Guest access validated successfully!")"
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Available shares for guest access:")${CL}"
        while IFS= read -r share; do
            [[ -n "$share" ]] && echo -e "${TAB}• ${BL}$share${CL}"
        done <<< "$(echo -e "$ACCESSIBLE_SHARES" | grep -v "^$")"
        echo -e
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        clear

        VALIDATED_GUEST_SHARES="$ACCESSIBLE_SHARES"
        return 0
    else
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        whiptail --title "$(translate "Guest Access Failed")" \
               --msgbox "$(translate "While the server allows guest listing, no shares are actually accessible without authentication.")\n\n$(translate "You need to use username and password authentication.")" \
               12 70
        clear       
        return 1
    fi
}






get_samba_credentials() {
    while true; do
        CHOICE=$(whiptail --title "$(translate "Samba Credentials")" \
            --menu "$(translate "Select authentication mode:")" 13 60 2 \
            "1" "$(translate "Configure with username and password")" \
            "2" "$(translate "Configure as guest (no authentication)")" \
            3>&1 1>&2 2>&3)

        if [[ $? -ne 0 ]]; then
            return 1
        fi

        case "$CHOICE" in
            1)

                while true; do
                    USERNAME=$(whiptail --inputbox "$(translate "Enter username for Samba server:")" 10 60 --title "$(translate "Username")" 3>&1 1>&2 2>&3)
                    if [[ $? -ne 0 ]]; then
                        break
                    fi
                    if [[ -z "$USERNAME" ]]; then
                        whiptail --title "$(translate "Error")" --msgbox "$(translate "Username cannot be empty.")" 8 50
                        continue
                    fi

                    while true; do
                        PASSWORD=$(whiptail --passwordbox "$(translate "Enter password for") $USERNAME:" 10 60 --title "$(translate "Password")" 3>&1 1>&2 2>&3)
                        if [[ $? -ne 0 ]]; then
                            break
                        fi
                        if [[ -z "$PASSWORD" ]]; then
                            whiptail --title "$(translate "Error")" --msgbox "$(translate "Password cannot be empty.")" 8 50
                            continue
                        fi

                        PASSWORD_CONFIRM=$(whiptail --passwordbox "$(translate "Confirm password for") $USERNAME:" 10 60 --title "$(translate "Confirm Password")" 3>&1 1>&2 2>&3)
                        if [[ $? -ne 0 ]]; then
                            continue
                        fi
                        if [[ -z "$PASSWORD_CONFIRM" ]]; then
                            whiptail --title "$(translate "Error")" --msgbox "$(translate "Password confirmation cannot be empty.")" 8 50
                            continue
                        fi

                        if [[ "$PASSWORD" == "$PASSWORD_CONFIRM" ]]; then

                            show_proxmenux_logo
                            msg_info "$(translate "Validating credentials with server") $SAMBA_SERVER..."
                            

                            TEMP_CRED="/tmp/validate_cred_$$"
                            cat > "$TEMP_CRED" << EOF
username=$USERNAME
password=$PASSWORD
EOF
                            chmod 600 "$TEMP_CRED"
                            

                            SHARES_OUTPUT=$(smbclient -L "$SAMBA_SERVER" -A "$TEMP_CRED" 2>&1)
                            SHARES_RESULT=$?
                            
                            if [[ $SHARES_RESULT -eq 0 ]]; then

                                FIRST_SHARE=$(echo "$SHARES_OUTPUT" | awk '/Disk/ && !/IPC\$/ && !/ADMIN\$/ && !/print\$/ {print $1; exit}')
                                
                                if [[ -n "$FIRST_SHARE" ]]; then

                                    SHARE_TEST_OUTPUT=$(smbclient "//$SAMBA_SERVER/$FIRST_SHARE" -A "$TEMP_CRED" -c "ls" 2>&1)
                                    SHARE_TEST_RESULT=$?
                                    
                                    rm -f "$TEMP_CRED"
                                    
                                    if [[ $SHARE_TEST_RESULT -eq 0 ]]; then

                                        cleanup
                                        if echo "$SHARE_TEST_OUTPUT" | grep -qi "guest"; then
                                            whiptail --title "$(translate "Authentication Error")" \
                                                   --msgbox "$(translate "The server connected you as guest instead of the specified user.")\n\n$(translate "This means the credentials are incorrect.")\n\n$(translate "Please check:")\n• $(translate "Username is correct")\n• $(translate "Password is correct")\n• $(translate "User account exists on server")" \
                                                   14 70
                                        else
                                            msg_ok "$(translate "Credentials validated successfully")"
                                            USE_GUEST=false
                                            return 0
                                        fi
                                    else

                                        cleanup
                                        if echo "$SHARE_TEST_OUTPUT" | grep -qi "access denied\|logon failure\|authentication\|NT_STATUS_LOGON_FAILURE"; then
                                            whiptail --title "$(translate "Authentication Error")" \
                                                   --msgbox "$(translate "Invalid username or password.")\n\n$(translate "Error details:")\n$(echo "$SHARE_TEST_OUTPUT" | head -2)\n\n$(translate "Please check:")\n• $(translate "Username is correct")\n• $(translate "Password is correct")\n• $(translate "User account exists on server")" \
                                                   16 70
                                        elif echo "$SHARE_TEST_OUTPUT" | grep -qi "connection refused\|network unreachable"; then
                                            whiptail --title "$(translate "Network Error")" \
                                                   --msgbox "$(translate "Cannot connect to server") $SAMBA_SERVER\n\n$(translate "Please check network connectivity.")" \
                                                   10 60
                                            return 1
                                        else
                                            whiptail --title "$(translate "Share Access Error")" \
                                                   --msgbox "$(translate "Failed to access share with provided credentials.")\n\n$(translate "Error details:")\n$(echo "$SHARE_TEST_OUTPUT" | head -3)" \
                                                   12 70
                                        fi
                                    fi
                                else

                                    cleanup
                                    whiptail --title "$(translate "No Shares Available")" \
                                           --msgbox "$(translate "Cannot validate credentials - no shares available for testing.")\n\n$(translate "The server may not have accessible shares.")" \
                                           10 70
                                fi
                            else

                                rm -f "$TEMP_CRED"
                                

                                if echo "$SHARES_OUTPUT" | grep -qi "access denied\|logon failure\|authentication\|NT_STATUS_LOGON_FAILURE"; then
                                    cleanup
                                    whiptail --title "$(translate "Authentication Error")" \
                                           --msgbox "$(translate "Invalid username or password.")\n\n$(translate "Please check:")\n• $(translate "Username is correct")\n• $(translate "Password is correct")\n• $(translate "User account exists on server")\n• $(translate "Account is not locked")" \
                                           12 70
                                elif echo "$SHARES_OUTPUT" | grep -qi "connection refused\|network unreachable"; then
                                    cleanup
                                    whiptail --title "$(translate "Network Error")" \
                                           --msgbox "$(translate "Cannot connect to server") $SAMBA_SERVER\n\n$(translate "Please check network connectivity.")" \
                                           10 60
                                    return 1
                                else
                                    cleanup
                                    whiptail --title "$(translate "Connection Error")" \
                                           --msgbox "$(translate "Failed to connect to server.")\n\n$(translate "Error details:")\n$(echo "$SHARES_OUTPUT" | head -3)" \
                                           12 70
                                fi
                            fi

                            break
                        else
                            cleanup
                            whiptail --title "$(translate "Password Mismatch")" \
                                     --msgbox "$(translate "Passwords do not match. Please try again.")" \
                                     8 50

                        fi
                    done

                    if [[ $? -ne 0 ]]; then
                        break
                    fi
                done
                ;;
            2)

                if validate_guest_access "$SAMBA_SERVER"; then
                    USE_GUEST=true
                    return 0
                fi
                ;;
            *)
                return 1
                ;;
        esac
        

        if ! whiptail --yesno "$(translate "Authentication failed.")\n\n$(translate "Do you want to try different credentials or authentication method?")" 10 70 --title "$(translate "Try Again")"; then
            return 1
        fi

    done
}






select_samba_share() {
    if ! which smbclient >/dev/null 2>&1; then
        whiptail --title "$(translate "SMB Client Error")" \
                 --msgbox "$(translate "smbclient command is not working properly.")\n\n$(translate "Please check the installation.")" \
                 10 60
        return 1
    fi
    

    if [[ "$USE_GUEST" == "true" ]]; then

        if [[ -n "$VALIDATED_GUEST_SHARES" ]]; then
            SHARES=$(echo -e "$VALIDATED_GUEST_SHARES" | grep -v "^$")
        else

            SHARES_OUTPUT=$(smbclient -L "$SAMBA_SERVER" -N 2>&1)
            SHARES_RESULT=$?
            if [[ $SHARES_RESULT -eq 0 ]]; then
                SHARES=$(echo "$SHARES_OUTPUT" | awk '/Disk/ && !/IPC\$/ && !/ADMIN\$/ && !/print\$/ {print $1}' | grep -v "^$")
            else
                show_proxmenux_logo
                msg_error "$(translate "Failed to get shares")"
                echo -e
                msg_success "$(translate "Press Enter to continue...")"
                read -r
                return 1
            fi
        fi
    else

        TEMP_CRED="/tmp/temp_smb_cred_$$"
        cat > "$TEMP_CRED" << EOF
username=$USERNAME
password=$PASSWORD
EOF
        chmod 600 "$TEMP_CRED"
        
        SHARES_OUTPUT=$(smbclient -L "$SAMBA_SERVER" -A "$TEMP_CRED" 2>&1)
        SHARES_RESULT=$?
        
        rm -f "$TEMP_CRED"
        
        if [[ $SHARES_RESULT -ne 0 ]]; then
            whiptail --title "$(translate "SMB Error")" \
                   --msgbox "$(translate "Failed to get shares from") $SAMBA_SERVER\n\n$(translate "This is unexpected since credentials were validated.")" \
                   12 80
            return 1
        fi
        
        SHARES=$(echo "$SHARES_OUTPUT" | awk '/Disk/ && !/IPC\$/ && !/ADMIN\$/ && !/print\$/ {print $1}' | grep -v "^$")
    fi
    
    if [[ -z "$SHARES" ]]; then
        whiptail --title "$(translate "No Shares Found")" \
               --msgbox "$(translate "No shares found on server") $SAMBA_SERVER\n\n$(translate "You can enter the share name manually.")" \
               12 70
    
        SAMBA_SHARE=$(whiptail --inputbox "$(translate "Enter Samba share name:")" 10 60 --title "$(translate "Share Name")" 3>&1 1>&2 2>&3)
        [[ -z "$SAMBA_SHARE" ]] && return 1
        return 0
    fi


    OPTIONS=()
    while IFS= read -r share; do
        if [[ -n "$share" && "$share" != "IPC$" && "$share" != "ADMIN$" && "$share" != "print$" ]]; then

            if [[ "$USE_GUEST" == "true" ]]; then
                if echo -e "$VALIDATED_GUEST_SHARES" | grep -q "^$share$"; then
                    OPTIONS+=("$share" "$(translate "Guest accessible share")")
                fi
            else

                OPTIONS+=("$share" "$(translate "Samba share")")
            fi
        fi
    done <<< "$SHARES"
    
    if [[ ${#OPTIONS[@]} -eq 0 ]]; then
        whiptail --title "$(translate "No Available Shares")" \
               --msgbox "$(translate "No accessible shares found.")\n\n$(translate "You can enter the share name manually.")" \
               10 70
        
        SAMBA_SHARE=$(whiptail --inputbox "$(translate "Enter Samba share name:")" 10 60 --title "$(translate "Share Name")" 3>&1 1>&2 2>&3)
        [[ -z "$SAMBA_SHARE" ]] && return 1
        return 0
    fi
    
    SAMBA_SHARE=$(whiptail --title "$(translate "Select Samba Share")" --menu "$(translate "Choose a share to mount:")" 20 70 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -n "$SAMBA_SHARE" ]] && return 0 || return 1
}










select_mount_point() {
    while true; do
        METHOD=$(whiptail --title "$(translate "Select Mount Point")" --menu "$(translate "Where do you want to mount the Samba share?")" 15 70 3 \
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
                
                MOUNT_POINT=$(whiptail --title "$(translate "Select Existing Folder")" --menu "$(translate "Choose a folder to mount the share:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
                
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
                FOLDER_NAME=$(whiptail --inputbox "$(translate "Enter new folder name:")" 10 60 "${SAMBA_SHARE}" --title "$(translate "New Folder in /mnt")" 3>&1 1>&2 2>&3)
                if [[ -n "$FOLDER_NAME" ]]; then
                    MOUNT_POINT="/mnt/$FOLDER_NAME"
                    return 0
                fi
                ;;
            custom)
                MOUNT_POINT=$(whiptail --inputbox "$(translate "Enter full path for mount point:")" 10 70 "/mnt/samba_share" --title "$(translate "Custom Path")" 3>&1 1>&2 2>&3)
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
            MOUNT_OPTIONS="rw,file_mode=0664,dir_mode=0775,iocharset=utf8"
            ;;
        readonly)
            MOUNT_OPTIONS="ro,file_mode=0444,dir_mode=0555,iocharset=utf8"
            ;;
        performance)
            MOUNT_OPTIONS="rw,file_mode=0664,dir_mode=0775,iocharset=utf8,cache=strict,rsize=1048576,wsize=1048576"
            ;;
        custom)
            MOUNT_OPTIONS=$(whiptail --inputbox "$(translate "Enter custom mount options:")" 10 70 "rw,file_mode=0664,dir_mode=0775" --title "$(translate "Custom Options")" 3>&1 1>&2 2>&3)
            [[ -z "$MOUNT_OPTIONS" ]] && MOUNT_OPTIONS="rw,file_mode=0664,dir_mode=0775"
            ;;
        *)
            MOUNT_OPTIONS="rw,file_mode=0664,dir_mode=0775,iocharset=utf8"
            ;;
    esac
    

    if whiptail --yesno "$(translate "Do you want to make this mount permanent?")\n\n$(translate "This will add the mount to /etc/fstab so it persists after reboot.")" 10 70 --title "$(translate "Permanent Mount")"; then
        PERMANENT_MOUNT=true
    else
        PERMANENT_MOUNT=false
    fi
}

create_credentials_file() {
    if [[ "$USE_GUEST" == "true" ]]; then
        return 0
    fi
    

    CRED_FILE="$CREDENTIALS_DIR/${SAMBA_SERVER}_${SAMBA_SHARE}.cred"
    

    pct exec "$CTID" -- bash -c "cat > '$CRED_FILE' << EOF
username=$USERNAME
password=$PASSWORD
EOF"
    
    pct exec "$CTID" -- chmod 600 "$CRED_FILE"
    msg_ok "$(translate "Credentials file created securely.")"
}

validate_share_exists() {
    local server="$1"
    local share="$2"
    local use_guest="$3"
    local username="$4"
    local password="$5"
    
    
    if [[ "$use_guest" == "true" ]]; then
        VALIDATION_OUTPUT=$(pct exec "$CTID" -- smbclient -L "$server" -N 2>/dev/null | grep "^[[:space:]]*$share[[:space:]]")
    else
        TEMP_CRED="/tmp/validate_cred_$$"
        pct exec "$CTID" -- bash -c "cat > $TEMP_CRED << EOF
username=$username
password=$password
EOF"
        pct exec "$CTID" -- chmod 600 "$TEMP_CRED"
        
        VALIDATION_OUTPUT=$(pct exec "$CTID" -- smbclient -L "$server" -A "$TEMP_CRED" 2>/dev/null | grep "^[[:space:]]*$share[[:space:]]")
        pct exec "$CTID" -- rm -f "$TEMP_CRED"
    fi
    
    if [[ -n "$VALIDATION_OUTPUT" ]]; then
        return 0
    else
        show_proxmenux_logo
        msg_error "$(translate "Share not found on server:") $share"
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi
}

mount_samba_share() {
    # Step 0:
    install_samba_client || return
    
    # Step 1:
    select_samba_server || return
    
    # Step 2:
    get_samba_credentials || return
    
    # Step 3:
    select_samba_share || return
    
    if ! validate_share_exists "$SAMBA_SERVER" "$SAMBA_SHARE" "$USE_GUEST" "$USERNAME" "$PASSWORD"; then
        echo -e ""
        msg_error "$(translate "Cannot proceed with invalid share name.")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return
    fi
    
    # Step 4:
    select_mount_point || return
    
    # Step 5:
    configure_mount_options || return
    
    show_proxmenux_logo
    msg_title "$(translate "Installing Samba Client")"

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
    

    if [[ "$USE_GUEST" != "true" ]]; then
        create_credentials_file
        CRED_OPTION="credentials=$CRED_FILE"
    else
        CRED_OPTION="guest"
    fi
    
    FULL_OPTIONS="$MOUNT_OPTIONS,$CRED_OPTION"
    UNC_PATH="//$SAMBA_SERVER/$SAMBA_SHARE"
    

    #if pct exec "$CTID" -- mount -t cifs "$UNC_PATH" "$MOUNT_POINT" -o "$FULL_OPTIONS"; then
    if pct exec "$CTID" -- mount -t cifs "$UNC_PATH" "$MOUNT_POINT" -o "$FULL_OPTIONS" 2>/dev/null; then
        msg_ok "$(translate "Samba share mounted successfully!")"
        
        if pct exec "$CTID" -- touch "$MOUNT_POINT/.test_write" 2>/dev/null; then
            pct exec "$CTID" -- rm "$MOUNT_POINT/.test_write" 2>/dev/null
            msg_ok "$(translate "Write access confirmed.")"
        else
            msg_warn "$(translate "Read-only access (or no write permissions).")"
        fi
        

        if [[ "$PERMANENT_MOUNT" == "true" ]]; then
   

            pct exec "$CTID" -- sed -i "\|$MOUNT_POINT|d" /etc/fstab
            

            FSTAB_ENTRY="$UNC_PATH $MOUNT_POINT cifs $FULL_OPTIONS 0 0"
            pct exec "$CTID" -- bash -c "echo '$FSTAB_ENTRY' >> /etc/fstab"
            msg_ok "$(translate "Added to /etc/fstab for permanent mounting.")"
        fi
        

        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Mount Information:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$SAMBA_SERVER${CL}"
        echo -e "${TAB}${BGN}$(translate "Share:")${CL} ${BL}$SAMBA_SHARE${CL}"
        echo -e "${TAB}${BGN}$(translate "Mount Point:")${CL} ${BL}$MOUNT_POINT${CL}"
        echo -e "${TAB}${BGN}$(translate "Authentication:")${CL} ${BL}$([ "$USE_GUEST" == "true" ] && echo "Guest" || echo "User: $USERNAME")${CL}"
        echo -e "${TAB}${BGN}$(translate "Permanent:")${CL} ${BL}$PERMANENT_MOUNT${CL}"
        
    else
        msg_error "$(translate "Failed to mount Samba share.")"
        echo -e "${TAB}$(translate "Please check:")"
        echo -e "${TAB}• $(translate "Server is accessible:"): $SAMBA_SERVER"
        echo -e "${TAB}• $(translate "Share exists:"): $SAMBA_SHARE"
        echo -e "${TAB}• $(translate "Credentials are correct")"
        echo -e "${TAB}• $(translate "Network connectivity")"
        echo -e "${TAB}• $(translate "Samba server is running")"
        

        if [[ "$USE_GUEST" != "true" && -n "$CRED_FILE" ]]; then
            pct exec "$CTID" -- rm -f "$CRED_FILE" 2>/dev/null || true
        fi
    fi
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}



view_samba_mounts() {
    show_proxmenux_logo
    msg_title "$(translate "Current Samba Mounts")"
    
    echo -e "$(translate "Samba/CIFS mounts in CT") $CTID:"
    echo "=================================="
    

    CURRENT_MOUNTS=$(pct exec "$CTID" -- mount -t cifs 2>/dev/null || true)
    if [[ -n "$CURRENT_MOUNTS" ]]; then
        echo -e "${BOLD}$(translate "Currently Mounted:")${CL}"
        echo "$CURRENT_MOUNTS"
        echo ""
    else
        echo "$(translate "No Samba shares currently mounted.")"
        echo ""
    fi
    

    FSTAB_CIFS=$(pct exec "$CTID" -- grep "cifs" /etc/fstab 2>/dev/null || true)
    if [[ -n "$FSTAB_CIFS" ]]; then
        echo -e "${BOLD}$(translate "Permanent Mounts (fstab):")${CL}"
        echo "$FSTAB_CIFS"
        echo ""
        
        echo -e "${TAB}${BOLD}$(translate "Mount Details:")${CL}"
        while IFS= read -r fstab_line; do
            if [[ -n "$fstab_line" && ! "$fstab_line" =~ ^# ]]; then
                UNC_PATH=$(echo "$fstab_line" | awk '{print $1}')
                MOUNT_POINT=$(echo "$fstab_line" | awk '{print $2}')
                OPTIONS=$(echo "$fstab_line" | awk '{print $4}')
                

                SERVER=$(echo "$UNC_PATH" | cut -d/ -f3)
                SHARE=$(echo "$UNC_PATH" | cut -d/ -f4)
                
                echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$SERVER${CL}"
                echo -e "${TAB}${BGN}$(translate "Share:")${CL} ${BL}$SHARE${CL}"
                echo -e "${TAB}${BGN}$(translate "Mount Point:")${CL} ${BL}$MOUNT_POINT${CL}"
                

                if echo "$OPTIONS" | grep -q "guest"; then
                    echo -e "${TAB}${BGN}$(translate "Authentication:")${CL} ${BL}Guest${CL}"
                elif echo "$OPTIONS" | grep -q "credentials="; then
                    CRED_FILE=$(echo "$OPTIONS" | grep -o "credentials=[^,]*" | cut -d= -f2)
                    echo -e "${TAB}${BGN}$(translate "Authentication:")${CL} ${BL}Credentials ($CRED_FILE)${CL}"
                fi
                

                if pct exec "$CTID" -- mount | grep -q "$MOUNT_POINT"; then
                    echo -e "${TAB}${BGN}$(translate "Status:")${CL} ${GN}$(translate "Mounted")${CL}"
                else
                    echo -e "${TAB}${BGN}$(translate "Status:")${CL} ${RD}$(translate "Not Mounted")${CL}"
                fi
                echo ""
            fi
        done <<< "$FSTAB_CIFS"
    else
        echo "$(translate "No permanent Samba mounts configured.")"
    fi
    

    CRED_FILES=$(pct exec "$CTID" -- find "$CREDENTIALS_DIR" -name "*.cred" 2>/dev/null || true)
    if [[ -n "$CRED_FILES" ]]; then
        echo -e "${BOLD}$(translate "Stored Credentials:")${CL}"
        while IFS= read -r cred_file; do
            if [[ -n "$cred_file" ]]; then
                FILENAME=$(basename "$cred_file")
                echo -e "${TAB}• $FILENAME"
            fi
        done <<< "$CRED_FILES"
        echo ""
    fi
    
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}






unmount_samba_share() {

    MOUNTS=$(pct exec "$CTID" -- mount -t cifs 2>/dev/null | awk '{print $3}' | sort -u || true)

    FSTAB_MOUNTS=$(pct exec "$CTID" -- grep -E "cifs" /etc/fstab 2>/dev/null | grep -v "^#" | awk '{print $2}' | sort -u || true)
    

    ALL_MOUNTS=$(echo -e "$MOUNTS\n$FSTAB_MOUNTS" | sort -u | grep -v "^$" || true)
    
    if [[ -z "$ALL_MOUNTS" ]]; then
        dialog --title "$(translate "No Mounts")" --msgbox "\n$(translate "No Samba mounts found.")" 8 50
        return
    fi
    
    OPTIONS=()
    while IFS= read -r mount_point; do
        [[ -n "$mount_point" ]] && OPTIONS+=("$mount_point" "")
    done <<< "$ALL_MOUNTS"
    
    SELECTED_MOUNT=$(dialog --title "$(translate "Unmount Samba Share")" --menu "$(translate "Select mount point to unmount:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED_MOUNT" ]] && return
    

    if whiptail --yesno "$(translate "Are you sure you want to unmount this Samba share?")\n\n$(translate "Mount Point:") $SELECTED_MOUNT\n\n$(translate "This will remove the mount from /etc/fstab and delete credentials if present.")" 14 80 --title "$(translate "Confirm Unmount")"; then
        
        show_proxmenux_logo
        msg_title "$(translate "Unmount Samba Share")"

        CRED_FILE=$(pct exec "$CTID" -- grep -E "\s+$SELECTED_MOUNT\s+" /etc/fstab 2>/dev/null | grep -o "credentials=[^, ]*" | cut -d= -f2 || true)
        pct exec "$CTID" -- sed -i "\|[[:space:]]$SELECTED_MOUNT[[:space:]]|d" /etc/fstab
        msg_ok "$(translate "Removed from /etc/fstab.")"
        
        if [[ -n "$CRED_FILE" && "$CRED_FILE" != "guest" ]]; then
            if pct exec "$CTID" -- test -f "$CRED_FILE"; then
                pct exec "$CTID" -- rm -f "$CRED_FILE"
                msg_ok "$(translate "Credentials file removed.")"
            fi
        fi

        echo -e ""


        msg_ok "$(translate "Samba share unmount successfully. Reboot LXC required to take effect.")"
        echo -e ""
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
    fi

}







test_samba_connectivity() {
    show_proxmenux_logo
    msg_title "$(translate "Test Samba Connectivity")"
    
    echo -e "$(translate "Samba/CIFS Client Status in CT") $CTID:"
    echo "=================================="
    

    if pct exec "$CTID" -- dpkg -s cifs-utils &>/dev/null; then
        echo "$(translate "CIFS Client: INSTALLED")"
        

        if pct exec "$CTID" -- which smbclient >/dev/null 2>&1; then
            echo "$(translate "SMB Client Tools: AVAILABLE")"
        else
            echo "$(translate "SMB Client Tools: NOT AVAILABLE")"
        fi
        
        echo ""
        echo "$(translate "Current CIFS mounts:")"
        CURRENT_MOUNTS=$(pct exec "$CTID" -- mount -t cifs 2>/dev/null || true)
        if [[ -n "$CURRENT_MOUNTS" ]]; then
            echo "$CURRENT_MOUNTS"
        else
            echo "$(translate "No CIFS mounts active.")"
        fi
        
        echo ""
        echo "$(translate "Testing network connectivity...")"
        

        FSTAB_SERVERS=$(pct exec "$CTID" -- grep "cifs" /etc/fstab 2>/dev/null | awk '{print $1}' | cut -d/ -f3 | sort -u || true)
        if [[ -n "$FSTAB_SERVERS" ]]; then
            while IFS= read -r server; do
                if [[ -n "$server" ]]; then
                    echo -n "$(translate "Testing") $server: "
                    if pct exec "$CTID" -- ping -c 1 -W 2 "$server" >/dev/null 2>&1; then
                        echo -e "${GN}$(translate "Reachable")${CL}"
                        

                        if pct exec "$CTID" -- nc -z -w 2 "$server" 445 2>/dev/null; then
                            echo "  $(translate "SMB port 445:"): ${GN}$(translate "Open")${CL}"
                        elif pct exec "$CTID" -- nc -z -w 2 "$server" 139 2>/dev/null; then
                            echo "  $(translate "NetBIOS port 139:"): ${GN}$(translate "Open")${CL}"
                        else
                            echo "  $(translate "SMB ports:"): ${RD}$(translate "Closed")${CL}"
                        fi
                        

                        echo -n "  $(translate "Guest access test:"): "
                        if pct exec "$CTID" -- smbclient -L "$server" -N >/dev/null 2>&1; then
                            echo -e "${GN}$(translate "Available")${CL}"
                        else
                            echo -e "${YW}$(translate "Requires authentication")${CL}"
                        fi
                    else
                        echo -e "${RD}$(translate "Unreachable")${CL}"
                    fi
                fi
            done <<< "$FSTAB_SERVERS"
        else
            echo "$(translate "No Samba servers configured to test.")"
        fi
        

        echo ""
        echo "$(translate "Stored credentials:")"
        CRED_FILES=$(pct exec "$CTID" -- find "$CREDENTIALS_DIR" -name "*.cred" 2>/dev/null || true)
        if [[ -n "$CRED_FILES" ]]; then
            while IFS= read -r cred_file; do
                if [[ -n "$cred_file" ]]; then
                    FILENAME=$(basename "$cred_file")
                    echo "  • $FILENAME"
                fi
            done <<< "$CRED_FILES"
        else
            echo "  $(translate "No stored credentials found.")"
        fi
        
    else
        echo "$(translate "CIFS Client: NOT INSTALLED")"
        echo ""
        echo "$(translate "Run 'Mount Samba Share' to install CIFS client automatically.")"
    fi
    
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

# === Main Menu ===
while true; do
    CHOICE=$(dialog --title "$(translate "Samba Client Manager - CT") $CTID" \
        --menu "$(translate "Choose an option:")" 20 70 12 \
        "1" "$(translate "Mount Samba Share")" \
        "2" "$(translate "View Current Mounts")" \
        "3" "$(translate "Unmount Samba Share")" \
        "4" "$(translate "Test Samba Connectivity")" \
        "5" "$(translate "Exit")" \
        3>&1 1>&2 2>&3)

    RETVAL=$?
    if [[ $RETVAL -ne 0 ]]; then
        exit 0
    fi

    case $CHOICE in
        1) mount_samba_share ;;
        2) view_samba_mounts ;;
        3) unmount_samba_share ;;
        4) test_samba_connectivity ;;
        5) exit 0 ;;
        *) exit 0 ;;
    esac
done