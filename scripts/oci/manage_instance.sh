#!/bin/bash
# ==========================================================
# ProxMenux - Update or recreate one OCI instance
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Runs in the ProxMenux Monitor terminal. Opens the same flow as
# OCI manager Apps -> Manage installed OCI applications for one
# container, without the list:
#
#   VMID         - the container (required)
#   ACTION       - "update" or "recreate" (required)
#   KEEP_BACKUP  - storage where the backup taken before the
#                  update is kept (optional)
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
load_language
initialize_cache

if [[ ! ${VMID:-} =~ ^[0-9]{1,9}$ ]]; then
    msg_error "$(translate "Invalid VMID")"
    exit 1
fi
if [[ ${ACTION:-} != "update" && ${ACTION:-} != "recreate" ]]; then
    msg_error "$(translate "Invalid action")"
    exit 1
fi

args=(manage "$VMID" --action "$ACTION")
if [[ -n ${KEEP_BACKUP:-} ]]; then
    if [[ ! $KEEP_BACKUP =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
        msg_error "$(translate "Invalid storage name")"
        exit 1
    fi
    args+=(--keep-backup "$KEEP_BACKUP")
fi

exec bash "$LOCAL_SCRIPTS/oci/oci_manager_apps.sh" "${args[@]}"
