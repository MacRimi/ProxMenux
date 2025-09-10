#!/bin/bash
# ==========================================================
# ProxMenu Host - Samba Host Manager for Proxmox Host
# ==========================================================
# Based on ProxMenux by MacRimi
# ==========================================================
# Description:
# This script allows you to manage Samba/CIFS client mounts on Proxmox Host:
# - Mount external Samba shares on the host
# - Configure permanent mounts with credentials
# - Auto-discover Samba servers
# - Integrate with Proxmox storage system
# ==========================================================

# Configuration
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
CREDENTIALS_DIR="/etc/samba/credentials"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# Load common share functions
SHARE_COMMON_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/scripts/global/share-common.func"
if ! source <(curl -s "$SHARE_COMMON_URL" 2>/dev/null); then
    msg_warn "$(translate "Could not load shared functions. Using fallback methods.")"
    SHARE_COMMON_LOADED=false
else
    SHARE_COMMON_LOADED=true
fi


if ! command -v pveversion >/dev/null 2>&1; then
    dialog --backtitle "ProxMenux" --title "$(translate "Error")" --msgbox "$(translate "This script must be run on a Proxmox host.")" 8 60
    exit 1
fi

discover_samba_servers() {
    show_proxmenux_logo
    msg_title "$(translate "Samba Host Manager - Proxmox Host")"
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
    CHOICE=$(whiptail --backtitle "ProxMenux" --title "$(translate "Select Samba Server")" \
        --menu "$(translate "Choose a Samba server:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)

    if [[ -n "$CHOICE" ]]; then
        SAMBA_SERVER="${SERVER_IPS[$CHOICE]}"
        return 0
    else
        return 1
    fi
}





select_samba_server() {
    METHOD=$(dialog --backtitle "ProxMenux" --title "$(translate "Samba Server Selection")" --menu "$(translate "How do you want to select the Samba server?")" 15 70 3 \
    "auto" "$(translate "Auto-discover servers on network")" \
    "manual" "$(translate "Enter server IP/hostname manually")" \
    "recent" "$(translate "Select from recent servers")" 3>&1 1>&2 2>&3)
    
    case "$METHOD" in
        auto)
            discover_samba_servers || return 1
            ;;
        manual)
            clear
            SAMBA_SERVER=$(whiptail --inputbox "$(translate "Enter Samba server IP:")" 10 60 --title "$(translate "Samba Server")" 3>&1 1>&2 2>&3)
            [[ -z "$SAMBA_SERVER" ]] && return 1
            ;;
        recent)
            clear
            RECENT=$(grep "cifs" /etc/fstab 2>/dev/null | awk '{print $1}' | cut -d/ -f3 | sort -u || true)
            if [[ -z "$RECENT" ]]; then
                dialog --backtitle "ProxMenux" --title "$(translate "No Recent Servers")" --msgbox "\n$(translate "No recent Samba servers found.")" 8 50
                return 1
            fi
            
            OPTIONS=()
            while IFS= read -r server; do
                [[ -n "$server" ]] && OPTIONS+=("$server" "$(translate "Recent Samba server")")
            done <<< "$RECENT"
            
            SAMBA_SERVER=$(whiptail --title "$(translate "Recent Samba Servers")" --menu "$(translate "Choose a recent server:")" 20 70 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
            [[ -n "$SAMBA_SERVER" ]] && return 0 || return 1
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
                msg_ok "$(translate "Guest access confirmed for share:") $share"
                ACCESSIBLE_SHARES="$ACCESSIBLE_SHARES$share\n"
            else
                msg_warn "$(translate "Guest access denied for share:") $share"
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
            msg_ok "$(translate "Using pre-validated guest shares")"
        else

            SHARES_OUTPUT=$(smbclient -L "$SAMBA_SERVER" -N 2>&1)
            SHARES_RESULT=$?
            if [[ $SHARES_RESULT -eq 0 ]]; then
                SHARES=$(echo "$SHARES_OUTPUT" | awk '/Disk/ && !/IPC\$/ && !/ADMIN\$/ && !/print\$/ {print $1}' | grep -v "^$")
            else
                msg_error "$(translate "Failed to get shares")"
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
            msg_error "$(translate "Unexpected error getting shares")"
            whiptail --title "$(translate "SMB Error")" \
                   --msgbox "$(translate "Failed to get shares from") $SAMBA_SERVER\n\n$(translate "This is unexpected since credentials were validated.")" \
                   12 80
            return 1
        fi
        
        SHARES=$(echo "$SHARES_OUTPUT" | awk '/Disk/ && !/IPC\$/ && !/ADMIN\$/ && !/print\$/ {print $1}' | grep -v "^$")
    fi
    
    msg_ok "$(translate "Shares retrieved successfully")"

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






select_host_mount_point() {
    local default_path="/mnt/shared_samba_${SAMBA_SHARE}"

    MOUNT_POINT=$(pmx_select_host_mount_point "$(translate "Samba Mount Point")" "$default_path")
    [[ -n "$MOUNT_POINT" ]] && return 0 || return 1
}




configure_host_mount_options() {
    MOUNT_TYPE=$(whiptail --title "$(translate "Mount Options")" --menu "$(translate "Select mount configuration:")" 15 70 4 \
    "1" "$(translate "Default options read/write")" \
    "2" "$(translate "Read-only mount")" \
    "3" "$(translate "Custom options")" 3>&1 1>&2 2>&3)
    
    [[ $? -ne 0 ]] && return 1
    
    case "$MOUNT_TYPE" in
        1)
            MOUNT_OPTIONS="rw,noperm,file_mode=0664,dir_mode=0775,iocharset=utf8"
            ;;
        2)
            MOUNT_OPTIONS="ro,noperm,file_mode=0444,dir_mode=0555,iocharset=utf8"
            ;;
        3)
            MOUNT_OPTIONS=$(whiptail --inputbox "$(translate "Enter custom mount options:")" 10 70 "rw,file_mode=0664,dir_mode=0775" --title "$(translate "Custom Options")" 3>&1 1>&2 2>&3)
            [[ $? -ne 0 ]] && return 1
            [[ -z "$MOUNT_OPTIONS" ]] && MOUNT_OPTIONS="rw,noperm,file_mode=0664,dir_mode=0775"
            ;;
        *)
            MOUNT_OPTIONS="rw,noperm,file_mode=0664,dir_mode=0775,iocharset=utf8"
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
    

    # Only ask about Proxmox storage if using username/password authentication
    if [[ "$USE_GUEST" != "true" ]]; then
        if whiptail --yesno "$(translate "Do you want to add this as Proxmox storage?")\n\n$(translate "This will make the Samba share available as storage in Proxmox web interface.")" 10 70 --title "$(translate "Proxmox Storage")"; then
            PROXMOX_STORAGE=true
            
            STORAGE_ID=$(whiptail --inputbox "$(translate "Enter storage ID for Proxmox:")" 10 60 "cifs-$(echo $SAMBA_SERVER | tr '.' '-')" --title "$(translate "Storage ID")" 3>&1 1>&2 2>&3)
            STORAGE_ID_RESULT=$?
            
            if [[ $STORAGE_ID_RESULT -ne 0 ]]; then
                if whiptail --yesno "$(translate "Storage ID input was cancelled.")\n\n$(translate "Do you want to continue without Proxmox storage integration?")" 10 70 --title "$(translate "Continue Without Storage")"; then
                    PROXMOX_STORAGE=false
                else
                    return 1
                fi
            else
                [[ -z "$STORAGE_ID" ]] && STORAGE_ID="cifs-$(echo $SAMBA_SERVER | tr '.' '-')"
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
        # For guest access, don't offer Proxmox storage integration
        PROXMOX_STORAGE=false
    fi
    
    return 0
}

create_credentials_file() {
    if [[ "$USE_GUEST" == "true" ]]; then
        return 0
    fi
    
    mkdir -p "$CREDENTIALS_DIR"
    chmod 700 "$CREDENTIALS_DIR"
    

    CRED_FILE="$CREDENTIALS_DIR/${SAMBA_SERVER}_${SAMBA_SHARE}.cred"
    

    cat > "$CRED_FILE" << EOF
username=$USERNAME
password=$PASSWORD
EOF
    
    chmod 600 "$CRED_FILE"
    msg_ok "$(translate "Credentials file created securely.")"
}

add_proxmox_cifs_storage() {
    local storage_id="$1"
    local server="$2"
    local share="$3"
    local mount_point="$4"
    
    if ! which pvesm >/dev/null 2>&1; then
        msg_error "$(translate "pvesm command not found. This should not happen on Proxmox.")"
        echo "Press Enter to continue..."
        read -r
        return 1
    fi
    
    msg_ok "$(translate "pvesm command found")"
    

    if pvesm status "$storage_id" >/dev/null 2>&1; then
        msg_warn "$(translate "Storage ID already exists:") $storage_id"
        if ! whiptail --yesno "$(translate "Storage ID already exists. Do you want to remove and recreate it?")" 8 60 --title "$(translate "Storage Exists")"; then
            return 0
        fi
        pvesm remove "$storage_id" 2>/dev/null || true
    fi
    
    msg_ok "$(translate "Storage ID is available")"
    

    CONTENT_LIST="backup,iso,vztmpl"
    

    msg_info "$(translate "Adding authenticated storage to Proxmox...")"
    PVESM_OUTPUT=$(pvesm add cifs "$storage_id" \
        --server "$server" \
        --share "$share" \
        --username "$USERNAME" \
        --password "$PASSWORD" \
        --content "$CONTENT_LIST" 2>&1)
    PVESM_RESULT=$?
    
    if [[ $PVESM_RESULT -eq 0 ]]; then
        msg_ok "$(translate "CIFS storage added successfully to Proxmox!")"
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Storage Added Information:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Storage ID:")${CL} ${BL}$storage_id${CL}"
        echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$server${CL}"
        echo -e "${TAB}${BGN}$(translate "Share:")${CL} ${BL}$share${CL}"
        echo -e "${TAB}${BGN}$(translate "Content Types:")${CL} ${BL}$CONTENT_LIST${CL}"
        echo -e "${TAB}${BGN}$(translate "Authentication:")${CL} ${BL}User: $USERNAME${CL}"
        echo -e ""
        msg_ok "$(translate "Storage is now available in Proxmox web interface under Datacenter > Storage")"
        return 0
    else

        msg_error "$(translate "Failed to add CIFS storage to Proxmox.")"
        echo -e "${TAB}$(translate "Error details:"): $PVESM_OUTPUT"
        msg_warn "$(translate "The Samba share is still mounted, but not added as Proxmox storage.")"
        echo -e ""
        msg_info2 "$(translate "You can add it manually through:")"
        echo -e "${TAB}• $(translate "Proxmox web interface: Datacenter > Storage > Add > SMB/CIFS")"
        echo -e "${TAB}• $(translate "Command line:"): pvesm add cifs $storage_id --server $server --share $share --username $USERNAME --password [PASSWORD] --content backup,iso,vztmpl"
        
        return 1
    fi
}

mount_host_samba_share() {

    if ! which smbclient >/dev/null 2>&1; then
        msg_info "$(translate "Installing Samba client tools...")"
        apt-get update &>/dev/null
        apt-get install -y cifs-utils smbclient &>/dev/null
        msg_ok "$(translate "Samba client tools installed")"
    fi
    
    # Step 1:
    select_samba_server || return
    
    # Step 2:
    get_samba_credentials || return
    
    # Step 3:
    select_samba_share || return
    
    # Step 4:
    select_host_mount_point || return
    
    # Step 5:
    configure_host_mount_options || return
    

    show_proxmenux_logo
    msg_title "$(translate "Mount Samba Share on Host")"
    

    prepare_host_directory "$MOUNT_POINT" || return 1
    

    if mount | grep -q "$MOUNT_POINT"; then
        msg_warn "$(translate "Something is already mounted at") $MOUNT_POINT"
        if ! whiptail --yesno "$(translate "Do you want to unmount it first?")" 8 60 --title "$(translate "Already Mounted")"; then
            return
        fi
        umount "$MOUNT_POINT" 2>/dev/null || true
    fi
    

    if [[ "$USE_GUEST" != "true" ]]; then
        create_credentials_file
        CRED_OPTION="credentials=$CRED_FILE"
    else
        CRED_OPTION="guest"
    fi


        # --- Ensure correct group mapping ---
    if [[ "$SHARE_COMMON_LOADED" == "true" ]]; then
        GROUP=$(pmx_share_map_get "$MOUNT_POINT")
        if [[ -z "$GROUP" ]]; then
            GROUP=$(pmx_choose_or_create_group "sharedfiles") || return 1
            pmx_share_map_set "$MOUNT_POINT" "$GROUP"
        fi

        HOST_GID=$(pmx_ensure_host_group "$GROUP" 101000) || return 1
        MOUNT_OPTIONS="$MOUNT_OPTIONS,gid=$HOST_GID,uid=0"
    fi

    

    FULL_OPTIONS="$MOUNT_OPTIONS,$CRED_OPTION"
    UNC_PATH="//$SAMBA_SERVER/$SAMBA_SHARE"
    
    msg_info "$(translate "Mounting Samba share...")"
    if mount -t cifs "$UNC_PATH" "$MOUNT_POINT" -o "$FULL_OPTIONS" > /dev/null 2>&1; then
        msg_ok "$(translate "Samba share mounted successfully on host!")"
        

        if touch "$MOUNT_POINT/.test_write" 2>/dev/null; then
            rm "$MOUNT_POINT/.test_write" 2>/dev/null
            msg_ok "$(translate "Write access confirmed.")"
        else
            msg_warn "$(translate "Read-only access (or no write permissions).")"
        fi
        

        if [[ "$PERMANENT_MOUNT" == "true" ]]; then

            sed -i "\|$MOUNT_POINT|d" /etc/fstab
            FSTAB_ENTRY="$UNC_PATH $MOUNT_POINT cifs $FULL_OPTIONS 0 0"
            echo "$FSTAB_ENTRY" >> /etc/fstab
            msg_ok "$(translate "Added to /etc/fstab for permanent mounting.")"
            

            systemctl daemon-reload 2>/dev/null || true
            msg_ok "$(translate "Systemd configuration reloaded.")"
        fi
        

        if [[ "$PROXMOX_STORAGE" == "true" ]]; then
            add_proxmox_cifs_storage "$STORAGE_ID" "$SAMBA_SERVER" "$SAMBA_SHARE" "$MOUNT_POINT"
        fi
        

        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Host Mount Information:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$SAMBA_SERVER${CL}"
        echo -e "${TAB}${BGN}$(translate "Share:")${CL} ${BL}$SAMBA_SHARE${CL}"
        echo -e "${TAB}${BGN}$(translate "Host Mount Point:")${CL} ${BL}$MOUNT_POINT${CL}"
        echo -e "${TAB}${BGN}$(translate "Options:")${CL} ${BL}$MOUNT_OPTIONS${CL}"
        echo -e "${TAB}${BGN}$(translate "Authentication:")${CL} ${BL}$([ "$USE_GUEST" == "true" ] && echo "Guest" || echo "User: $USERNAME")${CL}"
        echo -e "${TAB}${BGN}$(translate "Permanent:")${CL} ${BL}$PERMANENT_MOUNT${CL}"
        if [[ "$PROXMOX_STORAGE" == "true" ]]; then
            echo -e "${TAB}${BGN}$(translate "Proxmox Storage ID:")${CL} ${BL}$STORAGE_ID${CL}"
        fi
        
    else
        msg_error "$(translate "Failed to mount Samba share on host.")"
        echo -e "${TAB}$(translate "This should not happen since credentials were validated.")"
        echo -e "${TAB}$(translate "Please check system logs for details.")"
        

        if [[ "$USE_GUEST" != "true" && -n "$CRED_FILE" ]]; then
            rm -f "$CRED_FILE" 2>/dev/null || true
        fi
    fi
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

view_host_samba_mounts() {
    show_proxmenux_logo
    msg_title "$(translate "Current Samba Mounts on Host")"
    
    echo -e "$(translate "Samba/CIFS mounts on Proxmox host:"):"
    echo "=================================="
    

    CURRENT_MOUNTS=$(mount -t cifs 2>/dev/null || true)
    if [[ -n "$CURRENT_MOUNTS" ]]; then
        echo -e "${BOLD}$(translate "Currently Mounted:")${CL}"
        echo "$CURRENT_MOUNTS"
        echo ""
    else
        echo "$(translate "No Samba shares currently mounted on host.")"
        echo ""
    fi
    

    FSTAB_CIFS=$(grep "cifs" /etc/fstab 2>/dev/null || true)
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
                echo -e "${TAB}${BGN}$(translate "Host Mount Point:")${CL} ${BL}$MOUNT_POINT${CL}"
                echo -e "${TAB}${BGN}$(translate "Options:")${CL} ${BL}$OPTIONS${CL}"
                

                if echo "$OPTIONS" | grep -q "guest"; then
                    echo -e "${TAB}${BGN}$(translate "Authentication:")${CL} ${BL}Guest${CL}"
                elif echo "$OPTIONS" | grep -q "credentials="; then
                    CRED_FILE=$(echo "$OPTIONS" | grep -o "credentials=[^,]*" | cut -d= -f2)
                    echo -e "${TAB}${BGN}$(translate "Authentication:")${CL} ${BL}Credentials ($CRED_FILE)${CL}"
                fi
                

                if mount | grep -q "$MOUNT_POINT"; then
                    echo -e "${TAB}${BGN}$(translate "Status:")${CL} ${GN}$(translate "Mounted")${CL}"
                else
                    echo -e "${TAB}${BGN}$(translate "Status:")${CL} ${RD}$(translate "Not Mounted")${CL}"
                fi
                echo ""
            fi
        done <<< "$FSTAB_CIFS"
    else
        echo "$(translate "No Samba mounts found in fstab.")"
    fi
    

    echo -e "${BOLD}$(translate "Proxmox CIFS Storage:")${CL}"
    if which pvesm >/dev/null 2>&1; then
        CIFS_STORAGES=$(pvesm status 2>/dev/null | grep "cifs" | awk '{print $1}' || true)
        if [[ -n "$CIFS_STORAGES" ]]; then
            while IFS= read -r storage_id; do
                if [[ -n "$storage_id" ]]; then
                    echo -e "${TAB}${BGN}$(translate "Storage ID:")${CL} ${BL}$storage_id${CL}"
                    

                    STORAGE_INFO=$(pvesm config "$storage_id" 2>/dev/null || true)
                    if [[ -n "$STORAGE_INFO" ]]; then
                        SERVER=$(echo "$STORAGE_INFO" | grep "server" | awk '{print $2}')
                        SHARE=$(echo "$STORAGE_INFO" | grep "share" | awk '{print $2}')
                        CONTENT=$(echo "$STORAGE_INFO" | grep "content" | awk '{print $2}')
                        USERNAME=$(echo "$STORAGE_INFO" | grep "username" | awk '{print $2}')
                        
                        [[ -n "$SERVER" ]] && echo -e "${TAB}  ${BGN}$(translate "Server:")${CL} ${BL}$SERVER${CL}"
                        [[ -n "$SHARE" ]] && echo -e "${TAB}  ${BGN}$(translate "Share:")${CL} ${BL}$SHARE${CL}"
                        [[ -n "$CONTENT" ]] && echo -e "${TAB}  ${BGN}$(translate "Content:")${CL} ${BL}$CONTENT${CL}"
                        [[ -n "$USERNAME" ]] && echo -e "${TAB}  ${BGN}$(translate "Username:")${CL} ${BL}$USERNAME${CL}"
                    fi
                    echo ""
                fi
            done <<< "$CIFS_STORAGES"
        else
            echo -e "${TAB}$(translate "No CIFS storage configured in Proxmox")"
        fi
    else
        echo -e "${TAB}$(translate "pvesm command not available")"
    fi
    

    CRED_FILES=$(find "$CREDENTIALS_DIR" -name "*.cred" 2>/dev/null || true)
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

unmount_host_samba_share() {

    MOUNTS=$(mount -t cifs 2>/dev/null | awk '{print $3}' | sort -u || true)
    FSTAB_MOUNTS=$(grep -E "cifs" /etc/fstab 2>/dev/null | grep -v "^#" | awk '{print $2}' | sort -u || true)
    

    ALL_MOUNTS=$(echo -e "$MOUNTS\n$FSTAB_MOUNTS" | sort -u | grep -v "^$" || true)
    
    if [[ -z "$ALL_MOUNTS" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Mounts")" --msgbox "\n$(translate "No Samba mounts found on host.")" 8 50
        return
    fi
    
    OPTIONS=()
    while IFS= read -r mount_point; do
        if [[ -n "$mount_point" ]]; then

            UNC_PATH=$(mount | grep "$mount_point" | awk '{print $1}' || grep "$mount_point" /etc/fstab | awk '{print $1}' || echo "Unknown")
            SERVER=$(echo "$UNC_PATH" | cut -d/ -f3)
            SHARE=$(echo "$UNC_PATH" | cut -d/ -f4)
            OPTIONS+=("$mount_point" "$SERVER/$SHARE")
        fi
    done <<< "$ALL_MOUNTS"
    
    SELECTED_MOUNT=$(dialog --backtitle "ProxMenux" --title "$(translate "Unmount Samba Share")" --menu "$(translate "Select mount point to unmount:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED_MOUNT" ]] && return
    

    UNC_PATH=$(mount | grep "$SELECTED_MOUNT" | awk '{print $1}' || grep "$SELECTED_MOUNT" /etc/fstab | awk '{print $1}' || echo "Unknown")
    SERVER=$(echo "$UNC_PATH" | cut -d/ -f3)
    SHARE=$(echo "$UNC_PATH" | cut -d/ -f4)
    

    PROXMOX_STORAGE=""
    if which pvesm >/dev/null 2>&1; then

        CIFS_STORAGES=$(pvesm status 2>/dev/null | grep "cifs" | awk '{print $1}' || true)
        while IFS= read -r storage_id; do
            if [[ -n "$storage_id" ]]; then
                STORAGE_INFO=$(pvesm config "$storage_id" 2>/dev/null || true)
                STORAGE_SERVER=$(echo "$STORAGE_INFO" | grep "server" | awk '{print $2}')
                STORAGE_SHARE=$(echo "$STORAGE_INFO" | grep "share" | awk '{print $2}')
                if [[ "$STORAGE_SERVER" == "$SERVER" && "$STORAGE_SHARE" == "$SHARE" ]]; then
                    PROXMOX_STORAGE="$storage_id"
                    break
                fi
            fi
        done <<< "$CIFS_STORAGES"
    fi
    

    CONFIRMATION_MSG="$(translate "Are you sure you want to unmount this Samba share?")\n\n$(translate "Mount Point:"): $SELECTED_MOUNT\n$(translate "Server:"): $SERVER\n$(translate "Share:"): $SHARE\n\n$(translate "This will:")\n• $(translate "Unmount the Samba share")\n• $(translate "Remove from /etc/fstab")"
    
    if [[ -n "$PROXMOX_STORAGE" ]]; then
        CONFIRMATION_MSG="$CONFIRMATION_MSG\n• $(translate "Remove Proxmox storage:"): $PROXMOX_STORAGE"
    fi
    
    CONFIRMATION_MSG="$CONFIRMATION_MSG\n• $(translate "Remove credentials file")\n• $(translate "Remove mount point directory")"
    
    if whiptail --yesno "$CONFIRMATION_MSG" 18 80 --title "$(translate "Confirm Unmount")"; then
        show_proxmenux_logo
        msg_title "$(translate "Unmount Samba Share from Host")"
        

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
        

        CRED_FILE=$(grep "$SELECTED_MOUNT" /etc/fstab 2>/dev/null | grep -o "credentials=[^,]*" | cut -d= -f2 || true)
        

        sed -i "\|[[:space:]]$SELECTED_MOUNT[[:space:]]|d" /etc/fstab
        msg_ok "$(translate "Removed from /etc/fstab.")"
        

        if [[ -n "$CRED_FILE" && "$CRED_FILE" != "guest" ]]; then
            if test -f "$CRED_FILE"; then
                rm -f "$CRED_FILE"
                msg_ok "$(translate "Credentials file removed.")"
            fi
        fi
        
        echo -e ""
        msg_ok "$(translate "Samba share unmounted successfully from host!")"
        
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

manage_proxmox_cifs_storage() {
    if ! command -v pvesm >/dev/null 2>&1; then
        dialog --backtitle "ProxMenux" --title "$(translate "Error")" --msgbox "\n$(translate "pvesm command not found. This should not happen on Proxmox.")" 8 60
        return
    fi


    CIFS_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "cifs" {print $1}')
    if [[ -z "$CIFS_STORAGES" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No CIFS Storage")" --msgbox "\n$(translate "No CIFS storage found in Proxmox.")" 8 60
        return
    fi


    OPTIONS=()
    while IFS= read -r storage_id; do
        if [[ -n "$storage_id" ]]; then
            STORAGE_INFO=$(pvesm config "$storage_id" 2>/dev/null || true)
            SERVER=$(echo "$STORAGE_INFO" | grep "server" | awk '{print $2}')
            SHARE=$(echo "$STORAGE_INFO" | grep "share" | awk '{print $2}')
            
            if [[ -n "$SERVER" && -n "$SHARE" ]]; then
                OPTIONS+=("$storage_id" "$SERVER/$SHARE")
            else
                OPTIONS+=("$storage_id" "$(translate "CIFS Storage")")
            fi
        fi
    done <<< "$CIFS_STORAGES"
    
    SELECTED_STORAGE=$(dialog --backtitle "ProxMenux" --title "$(translate "Manage Proxmox CIFS Storage")" --menu "$(translate "Select storage to manage:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED_STORAGE" ]] && return


    STORAGE_INFO=$(pvesm config "$SELECTED_STORAGE" 2>/dev/null || true)
    SERVER=$(echo "$STORAGE_INFO" | grep "server" | awk '{print $2}')
    SHARE=$(echo "$STORAGE_INFO" | grep "share" | awk '{print $2}')
    CONTENT=$(echo "$STORAGE_INFO" | grep "content" | awk '{print $2}')

    if whiptail --yesno "$(translate "Are you sure you want to REMOVE storage:")\n\n$SELECTED_STORAGE\n\n$(translate "WARNING: This will permanently remove the storage from Proxmox configuration.")\n$(translate "The Samba mount on the host will NOT be affected.")" 14 80 --title "$(translate "Remove Storage")"; then
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

test_host_samba_connectivity() {
    show_proxmenux_logo
    msg_title "$(translate "Test Samba Connectivity on Host")"
    
    echo -e "$(translate "Samba/CIFS Client Status on Proxmox Host:"):"
    echo "=================================="
    

    if which smbclient >/dev/null 2>&1; then
        echo "$(translate "CIFS Client Tools: AVAILABLE")"
        

        if which mount.cifs >/dev/null 2>&1; then
            echo "$(translate "CIFS Mount Tools: AVAILABLE")"
        else
            echo "$(translate "CIFS Mount Tools: NOT AVAILABLE")"
        fi
        
        echo ""
        echo "$(translate "Current CIFS mounts on host:")"
        CURRENT_MOUNTS=$(mount -t cifs 2>/dev/null || true)
        if [[ -n "$CURRENT_MOUNTS" ]]; then
            echo "$CURRENT_MOUNTS"
        else
            echo "$(translate "No CIFS mounts active on host.")"
        fi
        
        echo ""
        echo "$(translate "Testing network connectivity...")"
        

        FSTAB_SERVERS=$(grep "cifs" /etc/fstab 2>/dev/null | awk '{print $1}' | cut -d/ -f3 | sort -u || true)
        if [[ -n "$FSTAB_SERVERS" ]]; then
            while IFS= read -r server; do
                if [[ -n "$server" ]]; then
                    echo -n "$(translate "Testing") $server: "
                    if ping -c 1 -W 2 "$server" >/dev/null 2>&1; then
                        echo -e "${GN}$(translate "Reachable")${CL}"
                        

                        if nc -z -w 2 "$server" 445 2>/dev/null; then
                            echo "  $(translate "SMB port 445:"): ${GN}$(translate "Open")${CL}"
                        elif nc -z -w 2 "$server" 139 2>/dev/null; then
                            echo "  $(translate "NetBIOS port 139:"): ${GN}$(translate "Open")${CL}"
                        else
                            echo "  $(translate "SMB ports:"): ${RD}$(translate "Closed")${CL}"
                        fi
                        

                        echo -n "  $(translate "Guest access test:"): "
                        if smbclient -L "$server" -N >/dev/null 2>&1; then
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
        echo "$(translate "Proxmox CIFS Storage Status:")"
        if which pvesm >/dev/null 2>&1; then
            CIFS_STORAGES=$(pvesm status 2>/dev/null | grep "cifs" || true)
            if [[ -n "$CIFS_STORAGES" ]]; then
                echo "$CIFS_STORAGES"
            else
                echo "$(translate "No CIFS storage configured in Proxmox.")"
            fi
        else
            echo "$(translate "pvesm command not available.")"
        fi
        

        echo ""
        echo "$(translate "Stored credentials:")"
        CRED_FILES=$(find "$CREDENTIALS_DIR" -name "*.cred" 2>/dev/null || true)
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
        echo "$(translate "CIFS Client Tools: NOT AVAILABLE")"
        echo ""
        echo "$(translate "Installing CIFS client tools...")"
        apt-get update &>/dev/null
        apt-get install -y cifs-utils smbclient &>/dev/null
        echo "$(translate "CIFS client tools installed.")"
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

# === Main Menu ===
while true; do
    CHOICE=$(dialog --backtitle "ProxMenux" --title "$(translate "Samba Host Manager - Proxmox Host")" \
    --menu "$(translate "Choose an option:")" 22 80 14 \
    "1" "$(translate "Mount Samba Share on Host")" \
    "2" "$(translate "View Current Host Samba Mounts")" \
    "3" "$(translate "Unmount Samba Share from Host")" \
    "4" "$(translate "Remove Proxmox CIFS Storage")" \
    "5" "$(translate "Test Samba Connectivity")" \
    "6" "$(translate "Exit")" \
    3>&1 1>&2 2>&3)
    
    RETVAL=$?
    if [[ $RETVAL -ne 0 ]]; then
        exit 0
    fi
    
    case $CHOICE in
        1) mount_host_samba_share ;;
        2) view_host_samba_mounts ;;
        3) unmount_host_samba_share ;;
        4) manage_proxmox_cifs_storage ;;
        5) test_host_samba_connectivity ;;
        6) exit 0 ;;
        *) exit 0 ;;
    esac
done
