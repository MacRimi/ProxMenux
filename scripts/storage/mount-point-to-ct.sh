#!/bin/bash

# ==========================================================
# ProxMenux - Mount point from host into LXC container (CT)
# ==========================================================
# Author      : MacRimi
# License     : MIT
# Description : Mount a folder from /mnt on the host to a mount point in a CT
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
load_language
initialize_cache

#######################################################

CT_LIST=($(pct list | awk 'NR>1 {print $1":"$3}'))

if [[ ${#CT_LIST[@]} -eq 0 ]]; then
    whiptail --title "$(translate "No CTs")" --msgbox "$(translate "No containers found.")" 8 40
    exit 0
fi

CT_OPTIONS=()
for entry in "${CT_LIST[@]}"; do
    ID="${entry%%:*}"
    NAME="${entry##*:}"
    CT_OPTIONS+=("$ID" "$NAME")
done

CTID=$(whiptail --title "$(translate "Select CT")" --menu "$(translate "Select the container:")" 20 60 10 "${CT_OPTIONS[@]}" 3>&1 1>&2 2>&3)
[[ -z "$CTID" ]] && exit 0

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

#######################################################

select_origin_path() {
    METHOD=$(whiptail --title "$(translate "Select Host Folder")" --menu "$(translate "How do you want to select the host folder to mount?")" 15 60 5 \
    "auto" "$(translate "Select from /mnt")" \
    "manual" "$(translate "Enter path manually")" 3>&1 1>&2 2>&3)

    case "$METHOD" in
        auto)
            HOST_DIRS=(/mnt/*)
            OPTIONS=()
            for dir in "${HOST_DIRS[@]}"; do
                [[ -d "$dir" ]] && OPTIONS+=("$dir" "")
            done

            ORIGIN=$(whiptail --title "$(translate "Select Host Folder")" --menu "$(translate "Select the folder to mount:")" 20 60 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
            [[ -z "$ORIGIN" ]] && return 1
            ;;

        manual)
            ORIGIN=$(whiptail --title "$(translate "Enter Path")" --inputbox "$(translate "Enter the full path to the host folder:")" 10 60 "/mnt/" 3>&1 1>&2 2>&3)
            [[ -z "$ORIGIN" ]] && return 1
            ;;
    esac

    if [[ ! -d "$ORIGIN" ]]; then
        whiptail --title "$(translate "Error")" --msgbox "$(translate "The selected path is not a valid directory:")\n$ORIGIN" 8 60
        return 1
    fi

    # Preparar permisos en el host para uso compartido
    SHARE_GID=999
    if ! getent group sharedfiles >/dev/null; then
        groupadd -g "$SHARE_GID" sharedfiles
        msg_ok "$(translate "Group 'sharedfiles' created in the host with GID $SHARE_GID")"
    else
        msg_ok "$(translate "Group 'sharedfiles' already exists in the host")"
    fi

    chown root:sharedfiles "$ORIGIN"
    chmod 2775 "$ORIGIN"
    setfacl -d -m g:sharedfiles:rwx "$ORIGIN"
    setfacl -m g:sharedfiles:rwx "$ORIGIN"

    msg_ok "$(translate "Host folder prepared with shared group and permissions.")"

    return 0
}

select_origin_path || exit 0

#######################################################

CT_NAME=$(pct config "$CTID" | awk -F: '/hostname/ {print $2}' | xargs)
DEFAULT_MOUNT_POINT="/mnt/host_share"

MOUNT_POINT=$(whiptail --title "$(translate "Mount Point to CT")" \
--inputbox "$(translate "Enter the mount point inside the CT (e.g., /mnt/host_share):")" \
10 70 "$DEFAULT_MOUNT_POINT" 3>&1 1>&2 2>&3)

if [[ -z "$MOUNT_POINT" ]]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No mount point specified.")" 8 60
    exit 1
fi

if ! pct exec "$CTID" -- test -d "$MOUNT_POINT"; then
    if whiptail --yesno "$(translate "Directory does not exist in the CT.")\n\n$MOUNT_POINT\n\n$(translate "Do you want to create it?")" 12 70 --title "$(translate "Create Directory")"; then
        pct exec "$CTID" -- mkdir -p "$MOUNT_POINT"
        msg_ok "$(translate "Directory created inside CT:") $MOUNT_POINT"
    else
        msg_error "$(translate "Directory not created. Operation cancelled.")"
        exit 1
    fi
fi

INDEX=0
while pct config "$CTID" | grep -q "mp${INDEX}:"; do
    ((INDEX++))
    [[ $INDEX -ge 100 ]] && msg_error "Too many mount points." && exit 1
done

msg_info "$(translate "Mounting folder from host to CT...")"
RESULT=$(pct set "$CTID" -mp${INDEX} "$ORIGIN,mp=$MOUNT_POINT,backup=0,ro=0,acl=1" 2>&1)

if [[ $? -eq 0 ]]; then
    msg_ok "$(translate "Successfully mounted:")\n$ORIGIN → $CT_NAME:$MOUNT_POINT"
else
    msg_error "$(translate "Error mounting folder:")\n$RESULT"
    exit 1
fi

msg_success "$(translate "Press Enter to return to menu...")"
read -r

exit 0
