#!/bin/bash
# ==========================================================
# ProxMenux - iSCSI Host Manager for Proxmox Host
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Registers iSCSI targets as Proxmox storage via
# pvesm add iscsi. Proxmox manages the session natively via
# open-iscsi; LUNs appear as raw block devices for VM disks.
#
# Features:
# - Auto-installs open-iscsi + enables iscsid service.
# - sendtargets discovery against a portal (IP:port).
# - Auto-selects a single target; menu when several.
# - Storage ID derived from the IQN suffix.
# - Content type fixed to 'images' (block storage only).
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
# TOOLS
# ==========================================================

ensure_iscsi_tools() {
    if ! command -v iscsiadm >/dev/null 2>&1; then
        msg_info "$(translate "Installing iSCSI initiator tools...")"
        apt-get update &>/dev/null
        apt-get install -y open-iscsi &>/dev/null
        systemctl enable --now iscsid 2>/dev/null || true
        msg_ok "$(translate "iSCSI tools installed")"
    fi

    if ! systemctl is-active --quiet iscsid 2>/dev/null; then
        systemctl start iscsid 2>/dev/null || true
    fi
}

# ==========================================================
# TARGET DISCOVERY
# ==========================================================

select_iscsi_portal() {
    ISCSI_PORTAL=$(dialog --backtitle "ProxMenux" --title "$(translate "iSCSI Portal")" --inputbox \
        "$(translate "Enter iSCSI target portal IP or hostname:")\n\n$(translate "Examples:")\n  192.168.1.100\n  192.168.1.100:3260\n  nas.local" \
        14 65 3>&1 1>&2 2>&3)
    [[ $? -ne 0 || -z "$ISCSI_PORTAL" ]] && return 1

    # Normalise: if no port specified, add default 3260
    if [[ ! "$ISCSI_PORTAL" =~ :[0-9]+$ ]]; then
        ISCSI_PORTAL_DISPLAY="$ISCSI_PORTAL"
        ISCSI_PORTAL_FULL="${ISCSI_PORTAL}:3260"
    else
        ISCSI_PORTAL_DISPLAY="$ISCSI_PORTAL"
        ISCSI_PORTAL_FULL="$ISCSI_PORTAL"
    fi

    # Extract host for ping
    ISCSI_HOST=$(echo "$ISCSI_PORTAL" | cut -d: -f1)
    return 0
}

discover_iscsi_targets() {
    show_proxmenux_logo
    msg_title "$(translate "Add iSCSI Target as Proxmox Storage")"
    msg_ok "$(translate "Portal:") $ISCSI_PORTAL_DISPLAY"
    msg_info "$(translate "Testing connectivity to portal...")"

    if ! ping -c 1 -W 3 "$ISCSI_HOST" >/dev/null 2>&1; then
        msg_error "$(translate "Cannot reach portal:") $ISCSI_HOST"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi
    msg_ok "$(translate "Portal is reachable")"

    if ! nc -z -w 3 "$ISCSI_HOST" "${ISCSI_PORTAL_FULL##*:}" 2>/dev/null; then
        msg_warn "$(translate "iSCSI port") ${ISCSI_PORTAL_FULL##*:} $(translate "may be closed — trying discovery anyway...")"
    fi

    msg_info "$(translate "Discovering iSCSI targets...")"
    DISCOVERY_OUTPUT=$(iscsiadm --mode discovery --type sendtargets \
        --portal "$ISCSI_PORTAL_FULL" 2>&1)
    DISCOVERY_RESULT=$?

    if [[ $DISCOVERY_RESULT -ne 0 ]]; then
        msg_error "$(translate "iSCSI discovery failed")"
        echo -e "${TAB}$(translate "Error:"): $DISCOVERY_OUTPUT"
        echo ""
        msg_info2 "$(translate "Please check:")"
        echo -e "${TAB}• $(translate "Portal IP and port are correct")"
        echo -e "${TAB}• $(translate "iSCSI service is running on the target")"
        echo -e "${TAB}• $(translate "Firewall allows port") ${ISCSI_PORTAL_FULL##*:}"
        echo -e "${TAB}• $(translate "Initiator IQN is authorised on the target")"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi

    # Parse discovered targets: format is  <portal> <iqn>
    TARGETS=$(echo "$DISCOVERY_OUTPUT" | awk '{print $2}' | grep "^iqn\." | sort -u)

    if [[ -z "$TARGETS" ]]; then
        msg_warn "$(translate "No iSCSI targets found on portal") $ISCSI_PORTAL_DISPLAY"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi

    msg_ok "$(translate "Discovery successful")"
    return 0
}

select_iscsi_target() {
    local target_count
    target_count=$(echo "$TARGETS" | wc -l)

    if [[ "$target_count" -eq 1 ]]; then
        ISCSI_TARGET=$(echo "$TARGETS" | head -1)
        msg_ok "$(translate "Single target found — selected automatically:") $ISCSI_TARGET"
        return 0
    fi

    local options=()
    local i=1
    while IFS= read -r iqn; do
        [[ -z "$iqn" ]] && continue
        # Try to get LUN info for display
        local lun_info
        lun_info=$(iscsiadm --mode node --targetname "$iqn" --portal "$ISCSI_PORTAL_FULL" \
            --op show 2>/dev/null | grep "node.conn\[0\].address" | awk -F= '{print $2}' | tr -d ' ' || true)
        options+=("$i" "$iqn")
        i=$((i + 1))
    done <<< "$TARGETS"

    local choice
    choice=$(dialog --backtitle "ProxMenux" --title "$(translate "Select iSCSI Target")" \
        --menu "\n$(translate "Select target IQN:")" 20 90 10 \
        "${options[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$choice" ]] && return 1

    ISCSI_TARGET=$(echo "$TARGETS" | sed -n "${choice}p")
    [[ -z "$ISCSI_TARGET" ]] && return 1
    return 0
}

# ==========================================================
# STORAGE CONFIGURATION
# ==========================================================

configure_iscsi_storage() {
    # Suggest a storage ID derived from target IQN
    local iqn_suffix
    iqn_suffix=$(echo "$ISCSI_TARGET" | awk -F: '{print $NF}' | tr '.' '-' | cut -c1-20)
    local default_id="iscsi-${iqn_suffix}"

    STORAGE_ID=$(whiptail --inputbox "$(translate "Enter storage ID for Proxmox:")" \
        10 65 "$default_id" \
        --title "$(translate "Storage ID")" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1
    [[ -z "$STORAGE_ID" ]] && STORAGE_ID="$default_id"

    if [[ ! "$STORAGE_ID" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]]; then
        whiptail --msgbox "$(translate "Invalid storage ID. Use only letters, numbers, hyphens and underscores.")" 8 70
        return 1
    fi

    # iSCSI in Proxmox exposes block devices — content is always 'images'
    # (no file-level access like NFS/CIFS)
    MOUNT_CONTENT="images"

    whiptail --title "$(translate "iSCSI Content Type")" \
        --msgbox "$(translate "iSCSI storage provides raw block devices for VM disk images.")\n\n$(translate "Content type is fixed to:")\n\n  images\n\n$(translate "Each LUN will appear as a block device assignable to VMs.")" \
        12 70

    return 0
}

# ==========================================================
# PROXMOX INTEGRATION
# ==========================================================

add_proxmox_iscsi_storage() {
    local storage_id="$1"
    local portal="$2"
    local target="$3"
    local content="${4:-images}"

    if ! command -v pvesm >/dev/null 2>&1; then
        msg_error "$(translate "pvesm command not found. This should not happen on Proxmox.")"
        return 1
    fi

    if pvesm status "$storage_id" >/dev/null 2>&1; then
        msg_warn "$(translate "Storage ID already exists:") $storage_id"
        if ! whiptail --yesno "$(translate "Storage ID already exists. Do you want to remove and recreate it?")" \
            8 60 --title "$(translate "Storage Exists")"; then
            return 0
        fi
        pvesm remove "$storage_id" 2>/dev/null || true
    fi

    msg_ok "$(translate "Storage ID is available")"
    msg_info "$(translate "Adding iSCSI storage to Proxmox...")"

    local pvesm_output pvesm_result
    pvesm_output=$(pvesm add iscsi "$storage_id" \
        --portal "$portal" \
        --target "$target" \
        --content "$content" 2>&1)
    pvesm_result=$?

    if [[ $pvesm_result -eq 0 ]]; then
        msg_ok "$(translate "iSCSI storage added successfully to Proxmox!")"
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Storage Added:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Storage ID:")${CL} ${BL}$storage_id${CL}"
        echo -e "${TAB}${BGN}$(translate "Portal:")${CL} ${BL}$portal${CL}"
        echo -e "${TAB}${BGN}$(translate "Target IQN:")${CL} ${BL}$target${CL}"
        echo -e "${TAB}${BGN}$(translate "Content Types:")${CL} ${BL}$content${CL}"
        echo -e ""
        msg_ok "$(translate "Storage is now available in Proxmox web interface under Datacenter > Storage")"
        msg_info2 "$(translate "LUNs appear as block devices assignable to VMs")"
        return 0
    else
        msg_error "$(translate "Failed to add iSCSI storage to Proxmox.")"
        echo -e "${TAB}$(translate "Error details:"): $pvesm_output"
        echo -e ""
        msg_info2 "$(translate "You can add it manually through:")"
        echo -e "${TAB}• $(translate "Proxmox web interface: Datacenter > Storage > Add > iSCSI")"
        echo -e "${TAB}• pvesm add iscsi $storage_id --portal $portal --target $target --content $content"
        return 1
    fi
}

# ==========================================================
# MAIN OPERATIONS
# ==========================================================

add_iscsi_to_proxmox() {
    ensure_iscsi_tools

    # Step 1: Enter portal
    select_iscsi_portal || return

    # Step 2: Discover targets
    discover_iscsi_targets || return

    # Step 3: Select target
    select_iscsi_target || return

    show_proxmenux_logo
    msg_title "$(translate "Add iSCSI Target as Proxmox Storage")"
    msg_ok "$(translate "Portal:") $ISCSI_PORTAL_DISPLAY"
    msg_ok "$(translate "Target:") $ISCSI_TARGET"

    # Step 4: Configure storage
    configure_iscsi_storage || return

    # Step 5: Add to Proxmox
    show_proxmenux_logo
    msg_title "$(translate "Add iSCSI Target as Proxmox Storage")"
    msg_ok "$(translate "Portal:") $ISCSI_PORTAL_DISPLAY"
    msg_ok "$(translate "Target:") $ISCSI_TARGET"
    msg_ok "$(translate "Storage ID:") $STORAGE_ID"
    msg_ok "$(translate "Content:") $MOUNT_CONTENT"
    echo -e ""

    add_proxmox_iscsi_storage "$STORAGE_ID" "$ISCSI_PORTAL_FULL" "$ISCSI_TARGET" "$MOUNT_CONTENT"

    echo -e ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

view_iscsi_storages() {
    show_proxmenux_logo
    msg_title "$(translate "iSCSI Storages in Proxmox")"

    echo "=================================================="
    echo ""

    if ! command -v pvesm >/dev/null 2>&1; then
        msg_error "$(translate "pvesm not found.")"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return
    fi

    ISCSI_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "iscsi" {print $1, $3}')
    if [[ -z "$ISCSI_STORAGES" ]]; then
        msg_warn "$(translate "No iSCSI storage configured in Proxmox.")"
        echo ""
        msg_info2 "$(translate "Use option 1 to add an iSCSI target as Proxmox storage.")"
    else
        echo -e "${BOLD}$(translate "iSCSI Storages:")${CL}"
        echo ""
        while IFS=" " read -r storage_id storage_status; do
            [[ -z "$storage_id" ]] && continue
            local storage_info portal target content
            storage_info=$(get_storage_config "$storage_id")
            portal=$(echo "$storage_info" | awk '$1 == "portal" {print $2}')
            target=$(echo "$storage_info" | awk '$1 == "target" {print $2}')
            content=$(echo "$storage_info" | awk '$1 == "content" {print $2}')

            echo -e "${TAB}${BOLD}$storage_id${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Portal:")${CL} ${BL}$portal${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Target IQN:")${CL} ${BL}$target${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Content:")${CL} ${BL}$content${CL}"
            if [[ "$storage_status" == "active" ]]; then
                echo -e "${TAB}  ${BGN}$(translate "Status:")${CL} ${GN}$(translate "Active")${CL}"
            else
                echo -e "${TAB}  ${BGN}$(translate "Status:")${CL} ${RD}$storage_status${CL}"
            fi
            echo ""
        done <<< "$ISCSI_STORAGES"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

remove_iscsi_storage() {
    if ! command -v pvesm >/dev/null 2>&1; then
        dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
            --msgbox "\n$(translate "pvesm not found.")" 8 60
        return
    fi

    ISCSI_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "iscsi" {print $1}')
    if [[ -z "$ISCSI_STORAGES" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No iSCSI Storage")" \
            --msgbox "\n$(translate "No iSCSI storage found in Proxmox.")" 8 60
        return
    fi

    local options=()
    while IFS= read -r storage_id; do
        [[ -z "$storage_id" ]] && continue
        local storage_info portal target
        storage_info=$(get_storage_config "$storage_id")
        portal=$(echo "$storage_info" | awk '$1 == "portal" {print $2}')
        target=$(echo "$storage_info" | awk '$1 == "target" {print $2}')
        options+=("$storage_id" "$portal — ${target:0:40}")
    done <<< "$ISCSI_STORAGES"

    local SELECTED
    SELECTED=$(dialog --backtitle "ProxMenux" --title "$(translate "Remove iSCSI Storage")" \
        --menu "$(translate "Select storage to remove:")" 20 90 10 \
        "${options[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED" ]] && return

    local storage_info portal target content
    storage_info=$(get_storage_config "$SELECTED")
    portal=$(echo "$storage_info" | awk '$1 == "portal" {print $2}')
    target=$(echo "$storage_info" | awk '$1 == "target" {print $2}')
    content=$(echo "$storage_info" | awk '$1 == "content" {print $2}')

    if whiptail --yesno "$(translate "Remove Proxmox iSCSI storage:")\n\n$SELECTED\n\n$(translate "Portal:"): $portal\n$(translate "Target:"): $target\n$(translate "Content:"): $content\n\n$(translate "This removes the storage from Proxmox. The iSCSI target is not affected.")" \
        16 80 --title "$(translate "Confirm Remove")"; then

        show_proxmenux_logo
        msg_title "$(translate "Remove iSCSI Storage")"

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

test_iscsi_connectivity() {
    show_proxmenux_logo
    msg_title "$(translate "Test iSCSI Connectivity")"

    echo "=================================================="
    echo ""

    if command -v iscsiadm >/dev/null 2>&1; then
        msg_ok "$(translate "iSCSI Initiator: AVAILABLE")"
        local initiator_iqn
        initiator_iqn=$(cat /etc/iscsi/initiatorname.iscsi 2>/dev/null | grep "^InitiatorName=" | cut -d= -f2)
        [[ -n "$initiator_iqn" ]] && echo -e "  ${BGN}$(translate "Initiator IQN:")${CL} ${BL}$initiator_iqn${CL}"

        if systemctl is-active --quiet iscsid 2>/dev/null; then
            msg_ok "$(translate "iSCSI Daemon (iscsid): RUNNING")"
        else
            msg_warn "$(translate "iSCSI Daemon (iscsid): STOPPED")"
        fi
    else
        msg_warn "$(translate "iSCSI Initiator: NOT INSTALLED")"
        echo -e "  $(translate "Install with: apt-get install open-iscsi")"
    fi

    echo ""

    if command -v pvesm >/dev/null 2>&1; then
        echo -e "${BOLD}$(translate "Proxmox iSCSI Storage Status:")${CL}"
        ISCSI_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "iscsi" {print $1, $3}')

        if [[ -n "$ISCSI_STORAGES" ]]; then
            while IFS=" " read -r storage_id storage_status; do
                [[ -z "$storage_id" ]] && continue
                local portal
                portal=$(get_storage_config "$storage_id" | awk '$1 == "portal" {print $2}')
                local portal_host="${portal%%:*}"

                echo -n "  $storage_id ($portal): "

                if ping -c 1 -W 2 "$portal_host" >/dev/null 2>&1; then
                    echo -ne "${GN}$(translate "Reachable")${CL}"
                    local portal_port="${portal##*:}"
                    [[ "$portal_port" == "$portal" ]] && portal_port="3260"
                    if nc -z -w 2 "$portal_host" "$portal_port" 2>/dev/null; then
                        echo -e " | iSCSI port $portal_port: ${GN}$(translate "Open")${CL}"
                    else
                        echo -e " | iSCSI port $portal_port: ${RD}$(translate "Closed")${CL}"
                    fi
                else
                    echo -e "${RD}$(translate "Unreachable")${CL}"
                fi

                if [[ "$storage_status" == "active" ]]; then
                    echo -e "    $(translate "Proxmox status:") ${GN}$storage_status${CL}"
                else
                    echo -e "    $(translate "Proxmox status:") ${RD}$storage_status${CL}"
                fi

                # Show active iSCSI sessions for this target
                local target
                target=$(get_storage_config "$storage_id" | awk '$1 == "target" {print $2}')
                if command -v iscsiadm >/dev/null 2>&1; then
                    local session
                    session=$(iscsiadm --mode session 2>/dev/null | grep "$target" || true)
                    if [[ -n "$session" ]]; then
                        echo -e "    $(translate "Active session:") ${GN}$(translate "Connected")${CL}"
                    else
                        echo -e "    $(translate "Active session:") ${YW}$(translate "No active session")${CL}"
                    fi
                fi
                echo ""
            done <<< "$ISCSI_STORAGES"
        else
            echo "  $(translate "No iSCSI storage configured.")"
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
        --title "$(translate "iSCSI Host Manager - Proxmox Host")" \
        --menu "$(translate "Choose an option:")" 18 70 6 \
        "1" "$(translate "Add iSCSI Target as Proxmox Storage")" \
        "2" "$(translate "View iSCSI Storages")" \
        "3" "$(translate "Remove iSCSI Storage")" \
        "4" "$(translate "Test iSCSI Connectivity")" \
        "5" "$(translate "Exit")" \
        3>&1 1>&2 2>&3)

    RETVAL=$?
    if [[ $RETVAL -ne 0 ]]; then
        exit 0
    fi

    case $CHOICE in
        1) add_iscsi_to_proxmox ;;
        2) view_iscsi_storages ;;
        3) remove_iscsi_storage ;;
        4) test_iscsi_connectivity ;;
        5) exit 0 ;;
        *) exit 0 ;;
    esac
done
