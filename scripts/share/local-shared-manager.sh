#!/bin/bash
# ==========================================================
# ProxMenux - Local Shared Directory Manager
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT
# Version     : 1.0
# Last Updated: $(date +%d/%m/%Y)
# ==========================================================

# Configuration
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"



if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi


SHARE_COMMON_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/scripts/global/share-common.func"
if ! source <(curl -s "$SHARE_COMMON_URL" 2>/dev/null); then
    SHARE_COMMON_LOADED=false
else
    SHARE_COMMON_LOADED=true
fi

load_language
initialize_cache

# ==========================================================




create_shared_directory() {
    SHARED_DIR=$(pmx_select_host_mount_point "$(translate "Select Shared Directory Location")" "/mnt/shared")
    [[ -z "$SHARED_DIR" ]] && return


    if [[ -d "$SHARED_DIR" ]]; then
        if ! whiptail --yesno "$(translate "Directory already exists. Continue with permission setup?")" 10 70 --title "$(translate "Directory Exists")"; then
            return
        fi
    fi


    SHARE_GROUP=$(pmx_choose_or_create_group "sharedfiles") || return 1
    SHARE_GID=$(pmx_ensure_host_group "$SHARE_GROUP" 101000) || return 1


    if command -v setfacl >/dev/null 2>&1; then
        setfacl -k /mnt 2>/dev/null || true   
        setfacl -b /mnt 2>/dev/null || true  
    fi
    chmod 755 /mnt 2>/dev/null || true


    pmx_prepare_host_shared_dir "$SHARED_DIR" "$SHARE_GROUP" || return 1


    if command -v setfacl >/dev/null 2>&1; then
        setfacl -b -R "$SHARED_DIR" 2>/dev/null || true
    fi


    chown root:"$SHARE_GROUP" "$SHARED_DIR"
    chmod 2775 "$SHARED_DIR"

    pmx_share_map_set "$SHARED_DIR" "$SHARE_GROUP"

    show_proxmenux_logo
    msg_title "$(translate "Create Shared Directory")"

    echo -e ""
    echo -e "${TAB}${BOLD}$(translate "Shared Directory Created:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Directory:")${CL} ${BL}$SHARED_DIR${CL}"
    echo -e "${TAB}${BGN}$(translate "Group:")${CL} ${BL}$SHARE_GROUP (GID: $SHARE_GID)${CL}"
    echo -e "${TAB}${BGN}$(translate "Permissions:")${CL} ${BL}2775 (rwxrwsr-x)${CL}"
    echo -e "${TAB}${BGN}$(translate "Owner:")${CL} ${BL}root:$SHARE_GROUP${CL}"
    echo -e "${TAB}${BGN}$(translate "ACL Status:")${CL} ${BL}$(translate "Cleaned and set for POSIX inheritance")${CL}"
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}




create_shared_directory
