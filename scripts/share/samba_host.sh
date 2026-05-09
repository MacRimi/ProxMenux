#!/bin/bash
# ==========================================================
# ProxMenux - Samba Host Manager for Proxmox Host
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Registers external Samba (SMB / CIFS) shares as Proxmox
# storage via pvesm add cifs. Credentials are stored encrypted
# in /etc/pve/priv/storage/<id>.pw — no fstab entries needed.
#
# Features:
# - Auto-discover Samba servers on the local subnet
#   (nmap on ports 139/445 + nmblookup for NetBIOS names).
# - Guest or username/password authentication.
# - Share listing via smbclient -L (filtered to Disk shares).
# - Content-type checklist (no rootdir — Proxmox does not
#   support LXC rootfs on CIFS).
# - View, remove and connectivity-test for existing storages.
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

if ! command -v pveversion >/dev/null 2>&1; then
    dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
        --msgbox "$(translate "This script must be run on a Proxmox host.")" 8 60
    exit 1
fi

# ==========================================================
# STORAGE CONFIG READER
# ==========================================================
get_storage_config() {
    local storage_id="$1"
    awk -v id="$storage_id" '
        /^[a-z]+: / { found = ($0 ~ ": "id"$"); next }
        found && /^[^ \t]/ { exit }
        found { print }
    ' /etc/pve/storage.cfg
}

# ==========================================================
# SERVER DISCOVERY
# ==========================================================

discover_samba_servers() {
    show_proxmenux_logo
    msg_title "$(translate "Add Samba Share as Proxmox Storage")"
    msg_info "$(translate "Scanning network for Samba servers...")"

    HOST_IP=$(hostname -I | awk '{print $1}')
    NETWORK=$(echo "$HOST_IP" | cut -d. -f1-3).0/24

    for pkg in nmap samba-common-bin; do
        if ! which "${pkg%%-*}" >/dev/null 2>&1; then
            apt-get install -y "$pkg" &>/dev/null
        fi
    done

    SERVERS=$(nmap -p 139,445 --open "$NETWORK" 2>/dev/null | grep -B 4 -E "(139|445)/tcp open" | grep "Nmap scan report" | awk '{print $5}' | sort -u || true)
    if [[ -z "$SERVERS" ]]; then
        cleanup
        whiptail --title "$(translate "No Servers Found")" \
            --msgbox "$(translate "No Samba servers found on the network.")\n\n$(translate "You can add servers manually.")" 10 60
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
    METHOD=$(dialog --backtitle "ProxMenux" --title "$(translate "Samba Server Selection")" \
        --menu "$(translate "How do you want to select the Samba server?")" 15 70 2 \
        "auto"   "$(translate "Auto-discover servers on network")" \
        "manual" "$(translate "Enter server IP/hostname manually")" \
        3>&1 1>&2 2>&3)

    case "$METHOD" in
        auto)
            discover_samba_servers || return 1
            ;;
        manual)
            clear
            SAMBA_SERVER=$(whiptail --inputbox "$(translate "Enter Samba server IP:")" \
                10 60 --title "$(translate "Samba Server")" 3>&1 1>&2 2>&3)
            [[ -z "$SAMBA_SERVER" ]] && return 1
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}

# ==========================================================
# CREDENTIALS
# ==========================================================

get_samba_credentials() {
    AUTH_TYPE=$(whiptail --title "$(translate "Authentication")" \
        --menu "$(translate "Select authentication type:")" 12 60 2 \
        "user"  "$(translate "Username and password")" \
        "guest" "$(translate "Guest access (no authentication)")" \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    if [[ "$AUTH_TYPE" == "guest" ]]; then
        USE_GUEST=true
        USERNAME=""
        PASSWORD=""
        return 0
    fi

    USE_GUEST=false

    USERNAME=$(whiptail --inputbox "$(translate "Enter username:")" \
        10 60 --title "$(translate "Samba Username")" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 || -z "$USERNAME" ]] && return 1

    PASSWORD=$(whiptail --passwordbox "$(translate "Enter password:")" \
        10 60 --title "$(translate "Samba Password")" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    return 0
}

# ==========================================================
# SHARE SELECTION
# ==========================================================

select_samba_share() {
    if [[ "$USE_GUEST" == "true" ]]; then
        SHARES=$(smbclient -L "$SAMBA_SERVER" -N 2>/dev/null | awk '/Disk/ {print $1}' | sort -u || true)
    else
        SHARES=$(smbclient -L "$SAMBA_SERVER" -U "$USERNAME%$PASSWORD" 2>/dev/null | awk '/Disk/ {print $1}' | sort -u || true)
    fi

    if [[ -z "$SHARES" ]]; then
        whiptail --title "$(translate "No Available Shares")" \
            --msgbox "$(translate "No accessible shares found.")\n\n$(translate "You can enter the share name manually.")" \
            10 70
        SAMBA_SHARE=$(whiptail --inputbox "$(translate "Enter Samba share name:")" \
            10 60 --title "$(translate "Share Name")" 3>&1 1>&2 2>&3)
        [[ -z "$SAMBA_SHARE" ]] && return 1
        return 0
    fi

    OPTIONS=()
    while IFS= read -r share; do
        [[ -n "$share" ]] && OPTIONS+=("$share" "$(translate "Samba share")")
    done <<< "$SHARES"

    if [[ ${#OPTIONS[@]} -eq 0 ]]; then
        SAMBA_SHARE=$(whiptail --inputbox "$(translate "Enter Samba share name:")" \
            10 60 --title "$(translate "Share Name")" 3>&1 1>&2 2>&3)
        [[ -z "$SAMBA_SHARE" ]] && return 1
        return 0
    fi

    SAMBA_SHARE=$(whiptail --title "$(translate "Select Samba Share")" \
        --menu "$(translate "Choose a share to mount:")" 20 70 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -n "$SAMBA_SHARE" ]] && return 0 || return 1
}

# ==========================================================
# STORAGE CONFIGURATION
# ==========================================================

configure_cifs_storage() {
    STORAGE_ID=$(whiptail --inputbox "$(translate "Enter storage ID for Proxmox:")" \
        10 60 "cifs-$(echo "$SAMBA_SERVER" | tr '.' '-')" \
        --title "$(translate "Storage ID")" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1
    [[ -z "$STORAGE_ID" ]] && STORAGE_ID="cifs-$(echo "$SAMBA_SERVER" | tr '.' '-')"

    if [[ ! "$STORAGE_ID" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]]; then
        whiptail --msgbox "$(translate "Invalid storage ID. Use only letters, numbers, hyphens and underscores.")" 8 70
        return 1
    fi

    local raw_content
    raw_content=$(dialog --backtitle "ProxMenux" \
        --title "$(translate "Content Types")" \
        --checklist "\n$(translate "Select content types for this storage:")\n$(translate "(Import is selected by default — required for disk image imports)")" 18 65 7 \
        "import"   "$(translate "Import            — disk image imports")"   on  \
        "backup"   "$(translate "Backup            — VM and CT backups")"    off \
        "iso"      "$(translate "ISO image         — installation images")"  off \
        "vztmpl"   "$(translate "Container template— LXC templates")"        off \
        "images"   "$(translate "Disk image        — VM disk images")"       off \
        "snippets" "$(translate "Snippets          — hook scripts / config")" off \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    # Convert dialog checklist output (quoted space-separated) to comma-separated
    MOUNT_CONTENT=$(echo "$raw_content" | tr -d '"' | tr -s ' ' ',' | sed 's/^,//;s/,$//')
    [[ -z "$MOUNT_CONTENT" ]] && MOUNT_CONTENT="import"

    # Warn if images selected (CIFS locking issues with VM disks)
    if echo "$MOUNT_CONTENT" | grep -q "images"; then
        whiptail --title "$(translate "Warning: Disk Images on CIFS")" \
            --msgbox "$(translate "You selected 'Disk image' content on a CIFS/SMB storage.")\n\n$(translate "CIFS can cause file locking issues with VM disk operations.")\n$(translate "NFS is recommended for VM disk image storage.")\n\n$(translate "Continuing with your selection.")" \
            12 70
    fi

    return 0
}

add_proxmox_cifs_storage() {
    local storage_id="$1"
    local server="$2"
    local share="$3"
    local content="${4:-import}"

    if ! command -v pvesm >/dev/null 2>&1; then
        msg_error "$(translate "pvesm command not found. This should not happen on Proxmox.")"
        return 1
    fi

    msg_ok "$(translate "pvesm command found")"

    if pvesm status "$storage_id" >/dev/null 2>&1; then
        msg_warn "$(translate "Storage ID already exists:") $storage_id"
        if ! whiptail --yesno "$(translate "Storage ID already exists. Do you want to remove and recreate it?")" \
            8 60 --title "$(translate "Storage Exists")"; then
            return 0
        fi
        pvesm remove "$storage_id" 2>/dev/null || true
    fi

    msg_ok "$(translate "Storage ID is available")"
    msg_info "$(translate "Adding CIFS storage to Proxmox...")"

    local pvesm_result pvesm_output
    if [[ "$USE_GUEST" == "true" ]]; then
        pvesm_output=$(pvesm add cifs "$storage_id" \
            --server "$server" \
            --share "$share" \
            --content "$content" 2>&1)
        pvesm_result=$?
    else
        pvesm_output=$(pvesm add cifs "$storage_id" \
            --server "$server" \
            --share "$share" \
            --username "$USERNAME" \
            --password "$PASSWORD" \
            --content "$content" 2>&1)
        pvesm_result=$?
    fi

    if [[ $pvesm_result -eq 0 ]]; then
        msg_ok "$(translate "CIFS storage added successfully to Proxmox!")"
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Storage Added:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Storage ID:")${CL} ${BL}$storage_id${CL}"
        echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$server${CL}"
        echo -e "${TAB}${BGN}$(translate "Share:")${CL} ${BL}$share${CL}"
        echo -e "${TAB}${BGN}$(translate "Content Types:")${CL} ${BL}$content${CL}"
        echo -e "${TAB}${BGN}$(translate "Authentication:")${CL} ${BL}$([ "$USE_GUEST" == "true" ] && echo "Guest" || echo "User: $USERNAME")${CL}"
        echo -e "${TAB}${BGN}$(translate "Mount Path:")${CL} ${BL}/mnt/pve/$storage_id${CL}"
        echo -e ""
        msg_ok "$(translate "Storage is now available in Proxmox web interface under Datacenter > Storage")"
        return 0
    else
        msg_error "$(translate "Failed to add CIFS storage to Proxmox.")"
        echo -e "${TAB}$(translate "Error details:"): $pvesm_output"
        echo -e ""
        msg_info2 "$(translate "You can add it manually through:")"
        echo -e "${TAB}• $(translate "Proxmox web interface: Datacenter > Storage > Add > SMB/CIFS")"
        echo -e "${TAB}• pvesm add cifs $storage_id --server $server --share $share --username USER --password PASS --content $content"
        return 1
    fi
}

# ==========================================================
# MAIN OPERATIONS
# ==========================================================

add_cifs_to_proxmox() {
    if ! which smbclient >/dev/null 2>&1; then
        msg_info "$(translate "Installing Samba client tools...")"
        apt-get update &>/dev/null
        apt-get install -y cifs-utils smbclient &>/dev/null
        msg_ok "$(translate "Samba client tools installed")"
    fi

    # Step 1: Select server
    select_samba_server || return

    # Step 2: Get credentials
    get_samba_credentials || return

    # Step 3: Select share
    select_samba_share || return

    show_proxmenux_logo
    msg_title "$(translate "Add Samba Share as Proxmox Storage")"
    msg_ok "$(translate "Server:") $SAMBA_SERVER"
    msg_ok "$(translate "Share:") $SAMBA_SHARE"
    msg_ok "$(translate "Auth:") $([ "$USE_GUEST" == "true" ] && echo "Guest" || echo "User: $USERNAME")"

    # Step 4: Configure storage
    configure_cifs_storage || return

    # Step 5: Add to Proxmox
    show_proxmenux_logo
    msg_title "$(translate "Add Samba Share as Proxmox Storage")"
    msg_ok "$(translate "Server:") $SAMBA_SERVER"
    msg_ok "$(translate "Share:") $SAMBA_SHARE"
    msg_ok "$(translate "Storage ID:") $STORAGE_ID"
    msg_ok "$(translate "Content:") $MOUNT_CONTENT"
    echo -e ""

    add_proxmox_cifs_storage "$STORAGE_ID" "$SAMBA_SERVER" "$SAMBA_SHARE" "$MOUNT_CONTENT"

    echo -e ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

view_cifs_storages() {
    show_proxmenux_logo
    msg_title "$(translate "CIFS Storages in Proxmox")"

    echo "=================================================="
    echo ""

    if ! command -v pvesm >/dev/null 2>&1; then
        msg_error "$(translate "pvesm not found.")"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return
    fi

    CIFS_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "cifs" {print $1, $3}')
    if [[ -z "$CIFS_STORAGES" ]]; then
        msg_warn "$(translate "No CIFS storage configured in Proxmox.")"
        echo ""
        msg_info2 "$(translate "Use option 1 to add a Samba share as Proxmox storage.")"
    else
        echo -e "${BOLD}$(translate "CIFS Storages:")${CL}"
        echo ""
        while IFS=" " read -r storage_id storage_status; do
            [[ -z "$storage_id" ]] && continue
            local storage_info server share content username
            storage_info=$(get_storage_config "$storage_id")
            server=$(echo "$storage_info" | awk '$1 == "server" {print $2}')
            share=$(echo "$storage_info" | awk '$1 == "share" {print $2}')
            content=$(echo "$storage_info" | awk '$1 == "content" {print $2}')
            username=$(echo "$storage_info" | awk '$1 == "username" {print $2}')

            echo -e "${TAB}${BOLD}$storage_id${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Server:")${CL} ${BL}$server${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Share:")${CL} ${BL}$share${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Content:")${CL} ${BL}$content${CL}"
            if [[ -n "$username" ]]; then
                echo -e "${TAB}  ${BGN}$(translate "Username:")${CL} ${BL}$username${CL}"
            else
                echo -e "${TAB}  ${BGN}$(translate "Auth:")${CL} ${BL}Guest${CL}"
            fi
            echo -e "${TAB}  ${BGN}$(translate "Mount Path:")${CL} ${BL}/mnt/pve/$storage_id${CL}"
            if [[ "$storage_status" == "active" ]]; then
                echo -e "${TAB}  ${BGN}$(translate "Status:")${CL} ${GN}$(translate "Active")${CL}"
            else
                echo -e "${TAB}  ${BGN}$(translate "Status:")${CL} ${RD}$storage_status${CL}"
            fi
            echo ""
        done <<< "$CIFS_STORAGES"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

remove_cifs_storage() {
    if ! command -v pvesm >/dev/null 2>&1; then
        dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
            --msgbox "\n$(translate "pvesm not found.")" 8 60
        return
    fi

    CIFS_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "cifs" {print $1}')
    if [[ -z "$CIFS_STORAGES" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No CIFS Storage")" \
            --msgbox "\n$(translate "No CIFS storage found in Proxmox.")" 8 60
        return
    fi

    OPTIONS=()
    while IFS= read -r storage_id; do
        [[ -z "$storage_id" ]] && continue
        local storage_info server share
        storage_info=$(get_storage_config "$storage_id")
        server=$(echo "$storage_info" | awk '$1 == "server" {print $2}')
        share=$(echo "$storage_info" | awk '$1 == "share" {print $2}')
        OPTIONS+=("$storage_id" "$server/$share")
    done <<< "$CIFS_STORAGES"

    SELECTED=$(dialog --backtitle "ProxMenux" --title "$(translate "Remove CIFS Storage")" \
        --menu "$(translate "Select storage to remove:")" 20 80 10 \
        "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED" ]] && return

    local storage_info server share content username
    storage_info=$(get_storage_config "$SELECTED")
    server=$(echo "$storage_info" | awk '$1 == "server" {print $2}')
    share=$(echo "$storage_info" | awk '$1 == "share" {print $2}')
    content=$(echo "$storage_info" | awk '$1 == "content" {print $2}')
    username=$(echo "$storage_info" | awk '$1 == "username" {print $2}')

    if whiptail --yesno "$(translate "Remove Proxmox CIFS storage:")\n\n$SELECTED\n\n$(translate "Server:"): $server\n$(translate "Share:"): $share\n$(translate "Content:"): $content\n\n$(translate "WARNING: This removes the storage from Proxmox. The Samba server is not affected.")" \
        16 80 --title "$(translate "Confirm Remove")"; then

        show_proxmenux_logo
        msg_title "$(translate "Remove CIFS Storage")"

        if pvesm remove "$SELECTED" 2>/dev/null; then
            msg_ok "$(translate "Storage") $SELECTED $(translate "removed successfully from Proxmox.")"
        else
            msg_error "$(translate "Failed to remove storage.")"
        fi

        echo -e ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
    fi
}

test_samba_connectivity() {
    show_proxmenux_logo
    msg_title "$(translate "Test Samba Connectivity")"

    echo "=================================================="
    echo ""

    if which smbclient >/dev/null 2>&1; then
        msg_ok "$(translate "CIFS Client Tools: AVAILABLE")"
    else
        msg_warn "$(translate "CIFS Client Tools: NOT AVAILABLE - installing...")"
        apt-get update &>/dev/null
        apt-get install -y cifs-utils smbclient &>/dev/null
        msg_ok "$(translate "CIFS client tools installed.")"
    fi

    echo ""

    if command -v pvesm >/dev/null 2>&1; then
        echo -e "${BOLD}$(translate "Proxmox CIFS Storage Status:")${CL}"
        CIFS_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "cifs" {print $1, $3}')

        if [[ -n "$CIFS_STORAGES" ]]; then
            while IFS=" " read -r storage_id storage_status; do
                [[ -z "$storage_id" ]] && continue
                local server
                server=$(get_storage_config "$storage_id" | awk '$1 == "server" {print $2}')

                echo -n "  $storage_id ($server): "

                if ping -c 1 -W 2 "$server" >/dev/null 2>&1; then
                    echo -ne "${GN}$(translate "Reachable")${CL}"

                    if nc -z -w 2 "$server" 445 2>/dev/null; then
                        echo -e " | SMB 445: ${GN}$(translate "Open")${CL}"
                    elif nc -z -w 2 "$server" 139 2>/dev/null; then
                        echo -e " | NetBIOS 139: ${GN}$(translate "Open")${CL}"
                    else
                        echo -e " | SMB ports: ${RD}$(translate "Closed")${CL}"
                    fi

                    echo -n "    $(translate "Guest access test:"): "
                    if smbclient -L "$server" -N >/dev/null 2>&1; then
                        echo -e "${GN}$(translate "Available")${CL}"
                    else
                        echo -e "${YW}$(translate "Requires authentication")${CL}"
                    fi
                else
                    echo -e "${RD}$(translate "Unreachable")${CL}"
                fi

                if [[ "$storage_status" == "active" ]]; then
                    echo -e "    $(translate "Proxmox status:") ${GN}$storage_status${CL}"
                else
                    echo -e "    $(translate "Proxmox status:") ${RD}$storage_status${CL}"
                fi
                echo ""
            done <<< "$CIFS_STORAGES"
        else
            echo "  $(translate "No CIFS storage configured.")"
        fi
    else
        msg_warn "$(translate "pvesm not available.")"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

# ==========================================================
# MAIN MENU
# ==========================================================

while true; do
    CHOICE=$(dialog --backtitle "ProxMenux" \
        --title "$(translate "Samba Host Manager - Proxmox Host")" \
        --menu "$(translate "Choose an option:")" 18 70 6 \
        "1" "$(translate "Add Samba Share as Proxmox Storage")" \
        "2" "$(translate "View CIFS Storages")" \
        "3" "$(translate "Remove CIFS Storage")" \
        "4" "$(translate "Test Samba Connectivity")" \
        "5" "$(translate "Exit")" \
        3>&1 1>&2 2>&3)

    RETVAL=$?
    if [[ $RETVAL -ne 0 ]]; then
        exit 0
    fi

    case $CHOICE in
        1) add_cifs_to_proxmox ;;
        2) view_cifs_storages ;;
        3) remove_cifs_storage ;;
        4) test_samba_connectivity ;;
        5) exit 0 ;;
        *) exit 0 ;;
    esac
done
