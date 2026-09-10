#!/bin/bash
# ==========================================================
# ProxMenux - Local Shared Directory Manager
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Creates a host directory pre-configured for LXC bind mounts.
# Applies a permission profile (1777 + ACLs) that works for
# both privileged and unprivileged containers without UID/GID
# alignment.
#
# Features:
# - Auto-suggests a free name in /mnt (shared, shared2, …).
# - Accepts custom absolute paths outside /mnt.
# - chown root:root + chmod 1777 (sticky + world-rwx).
# - setfacl with default-inheritance ACLs so new files keep
#   the permissive profile.
# - Registers the directory in the ProxMenux share map for
#   later use by the LXC Mount Manager.
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_SCRIPTS_DEFAULT="/usr/local/share/proxmenux/scripts"
LOCAL_SCRIPTS="$LOCAL_SCRIPTS_DEFAULT"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"

if [[ -f "$LOCAL_SCRIPTS_LOCAL/utils.sh" ]]; then
    LOCAL_SCRIPTS="$LOCAL_SCRIPTS_LOCAL"
    UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
elif [[ ! -f "$UTILS_FILE" ]]; then
    UTILS_FILE="$BASE_DIR/utils.sh"
fi

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

if ! command -v pveversion >/dev/null 2>&1; then
    dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
        --msgbox "$(translate "This script must be run on a Proxmox host.")" 8 60
    exit 1
fi

# ==========================================================




lsm_apply_multi_unpriv_permissions() {
    local dir="$1"

    [[ -z "$dir" || ! -d "$dir" ]] && return 1

    # root:root ownership — no new group needed.
    chown root:root "$dir" 2>/dev/null || true

    # 1777 = sticky bit (prevents cross-container file deletion) + world-rwx.
    # Unprivileged LXC UIDs (100000+) appear as 'others' on the host,
    # so 'o+rwx' is what grants them read+write access.
    chmod 1777 "$dir" 2>/dev/null || true

    # Ensure existing content is readable/writable regardless of UID mapping.
    chmod -R a+rwX "$dir" 2>/dev/null || true
    find "$dir" -type d -exec chmod 1777 {} + 2>/dev/null || true

    if command -v setfacl >/dev/null 2>&1; then
        # Remove restrictive ACLs and enforce permissive inheritance for new files.
        setfacl -b -R "$dir" 2>/dev/null || true
        setfacl -R -m u::rwx,g::rwx,o::rwx,m::rwx "$dir" 2>/dev/null || true
        setfacl -R -m d:u::rwx,d:g::rwx,d:o::rwx,d:m::rwx "$dir" 2>/dev/null || true
    fi

    return 0
}

# Returns a free name like /mnt/shared, /mnt/shared2, /mnt/shared3 …
lsm_next_free_name() {
    local base="${1:-shared}"
    local candidate="/mnt/$base"
    [[ ! -d "$candidate" ]] && echo "$candidate" && return
    local n=2
    while [[ -d "/mnt/${base}${n}" ]]; do
        ((n++))
    done
    echo "/mnt/${base}${n}"
}

lsm_list_mnt_folders() {
    show_proxmenux_logo
    msg_title "$(translate "Folders in /mnt")"

    echo "=================================================="

    if [[ ! -d /mnt ]] || [[ -z "$(ls -A /mnt 2>/dev/null)" ]]; then
        echo ""
        echo -e "${TAB}$(translate "No folders found in /mnt.")"
    else
        local found=false
        while IFS= read -r dir; do
            [[ ! -d "$dir" ]] && continue
            found=true
            local perms owner
            perms=$(stat -c "%a" "$dir" 2>/dev/null)
            owner=$(stat -c "%U:%G" "$dir" 2>/dev/null)
            echo ""
            echo -e "${TAB}${BGN}$(translate "Directory:")${CL} ${BL}$dir${CL}"
            echo -e "${TAB}${BGN}$(translate "Permissions:")${CL} ${BL}${perms} $(stat -c "(%A)" "$dir" 2>/dev/null)${CL}"
            echo -e "${TAB}${BGN}$(translate "Owner:")${CL} ${BL}${owner}${CL}"
        done < <(find /mnt -mindepth 1 -maxdepth 1 -type d | sort)

        if [[ "$found" = false ]]; then
            echo ""
            echo -e "${TAB}$(translate "No folders found in /mnt.")"
        fi
    fi

    echo ""
    echo "=================================================="
    echo ""

    # Summary of /mnt available space
    if mountpoint -q /mnt 2>/dev/null || [[ -d /mnt ]]; then
        local mnt_avail mnt_total
        mnt_avail=$(df -h /mnt 2>/dev/null | awk 'NR==2{print $4}')
        mnt_total=$(df -h /mnt 2>/dev/null | awk 'NR==2{print $2}')
        if [[ -n "$mnt_avail" ]]; then
            echo -e "${TAB}${BGN}$(translate "Available space in /mnt:")${CL} ${BL}${mnt_avail} $(translate "of") ${mnt_total}${CL}"
            echo ""
        fi
    fi

    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

# Result is stored in LSM_SELECTED_MOUNT_POINT (not echoed) to avoid subshell issues
LSM_SELECTED_MOUNT_POINT=""

lsm_select_host_mount_point_dialog() {
    local title="${1:-$(translate "Select Shared Directory Location")}"
    local base_name="${2:-shared}"
    local choice folder_name result mount_point
    LSM_SELECTED_MOUNT_POINT=""

    # Auto-suggest a free name in /mnt
    local suggested
    suggested=$(lsm_next_free_name "$base_name")

    while true; do
        choice=$(dialog --backtitle "ProxMenux" \
            --title "$title" \
            --menu "\n$(translate "Where do you want the host folder?")" 16 72 4 \
            "1" "$(translate "Create new folder in /mnt")" \
            "2" "$(translate "Enter custom path")" \
            "3" "$(translate "View existing folders in /mnt")" \
            "4" "$(translate "Cancel")" \
            3>&1 1>&2 2>&3) || return 1

        case "$choice" in
            1)
                folder_name=$(dialog --backtitle "ProxMenux" \
                    --title "$(translate "Folder Name")" \
                    --inputbox "\n$(translate "Enter folder name for /mnt:")" 10 70 "$(basename "$suggested")" \
                    3>&1 1>&2 2>&3) || continue
                [[ -z "$folder_name" ]] && continue
                mount_point="/mnt/$folder_name"
                # Only warn if the user manually typed an existing name
                if [[ -d "$mount_point" ]]; then
                    if ! dialog --backtitle "ProxMenux" --title "$(translate "Directory Exists")" \
                            --yesno "\n$(translate "Directory already exists. Continue with permission setup?")" 8 70; then
                        continue
                    fi
                fi
                ;;
            2)
                result=$(dialog --backtitle "ProxMenux" \
                    --title "$(translate "Custom Path")" \
                    --inputbox "\n$(translate "Enter full path:")" 10 80 "" \
                    3>&1 1>&2 2>&3) || continue
                [[ -z "$result" ]] && continue
                mount_point="$result"
                if [[ -d "$mount_point" ]]; then
                    if ! dialog --backtitle "ProxMenux" --title "$(translate "Directory Exists")" \
                            --yesno "\n$(translate "Directory already exists. Continue with permission setup?")" 8 70; then
                        continue
                    fi
                fi
                ;;
            3)
                lsm_list_mnt_folders
                # Refresh suggestion after viewing
                suggested=$(lsm_next_free_name "$base_name")
                continue
                ;;
            4) return 1 ;;
            *) continue ;;
        esac

        if [[ ! "$mount_point" =~ ^/ ]]; then
            dialog --backtitle "ProxMenux" --title "$(translate "Invalid Path")" \
                --msgbox "\n$(translate "Path must be absolute (start with /).")" 8 60
            continue
        fi

        LSM_SELECTED_MOUNT_POINT="$mount_point"
        return 0
    done
}

create_shared_directory() {
    lsm_select_host_mount_point_dialog "$(translate "Select Shared Directory Location")" "shared"
    [[ -z "$LSM_SELECTED_MOUNT_POINT" ]] && return
    SHARED_DIR="$LSM_SELECTED_MOUNT_POINT"

    show_proxmenux_logo
    msg_title "$(translate "Create Shared Directory")"

    if ! mkdir -p "$SHARED_DIR" 2>/dev/null; then
        msg_error "$(translate "Failed to create directory:") $SHARED_DIR"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi
    msg_ok "$(translate "Directory created:") $SHARED_DIR"

    lsm_apply_multi_unpriv_permissions "$SHARED_DIR"

    pmx_share_map_set "$SHARED_DIR" "open"

    echo -e ""
    echo -e "${TAB}${BOLD}$(translate "Shared Directory Ready:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Directory:")${CL} ${BL}$SHARED_DIR${CL}"
    echo -e "${TAB}${BGN}$(translate "Permissions:")${CL} ${BL}1777 (rwxrwxrwt)${CL}"
    echo -e "${TAB}${BGN}$(translate "Owner:")${CL} ${BL}root:root${CL}"
    echo -e "${TAB}${BGN}$(translate "Access profile:")${CL} ${BL}$(translate "Compatible with privileged and unprivileged LXC containers")${CL}"
    echo -e "${TAB}${BGN}$(translate "ACL Status:")${CL} ${BL}$(translate "Open rwx + default inheritance for new files")${CL}"
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}




create_shared_directory
