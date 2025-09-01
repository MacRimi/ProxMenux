#!/bin/bash
# ==========================================================
# ProxMenux - LXC Mount Manager (Standalone - CLEAN v1)
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT
# Version     : 3.0-clean
# Last Updated: $(date +%d/%m/%Y)
# ==========================================================

BASE_DIR="/usr/local/share/proxmenux"
source "$BASE_DIR/utils.sh"


SHARE_COMMON_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/scripts/global/share-common.func"
if ! source <(curl -s "$SHARE_COMMON_URL" 2>/dev/null); then
    SHARE_COMMON_LOADED=false
else
    SHARE_COMMON_LOADED=true
fi

load_language
initialize_cache

# ==========================================================


get_container_uid_shift() {
    local ctid="$1"
    local conf="/etc/pve/lxc/${ctid}.conf"
    local uid_shift

    if [[ ! -f "$conf" ]]; then
        echo "100000"   
        return 0
    fi


    local unpriv
    unpriv=$(grep "^unprivileged:" "$conf" | awk '{print $2}')

    if [[ "$unpriv" == "1" ]]; then

        uid_shift=$(grep "^lxc.idmap" "$conf" | grep 'u 0' | awk '{print $5}' | head -1)
        echo "${uid_shift:-100000}"
        return 0
    fi

    echo "0"
    return 0
}


setup_container_access() {
    local ctid="$1" group_name="$2" host_gid="$3" host_dir="$4"
    local uid_shift mapped_gid

    if [[ ! "$ctid" =~ ^[0-9]+$ ]]; then
        msg_error "$(translate 'Invalid container ID format:') $ctid"
        return 1
    fi

    uid_shift=$(get_container_uid_shift "$ctid")

    if [[ "$uid_shift" -eq 0 ]]; then
        mapped_gid="$host_gid"
        msg_ok "$(translate "Privileged container - using same GID as host:") $host_gid"
    else
        mapped_gid=$((uid_shift + host_gid))
        msg_ok "$(translate "Unprivileged container - using mapped GID:") $mapped_gid (host GID: $host_gid, shift: $uid_shift)"
    fi


    pct exec "$ctid" -- sh -c "
        if ! getent group $group_name >/dev/null 2>&1; then
            groupadd -g $mapped_gid $group_name 2>/dev/null || true
        else
            ct_gid=\$(getent group $group_name | cut -d: -f3)
            if [ \"\$ct_gid\" != \"$mapped_gid\" ]; then
                groupdel $group_name 2>/dev/null || true
                groupadd -g $mapped_gid $group_name 2>/dev/null || true
            fi
        fi


        getent passwd | while IFS=: read -r username _ uid gid _ home _; do
            if [ \"\$uid\" -eq 0 ] || [ \"\$uid\" -ge 1000 ] || [ \"\$username\" = \"nobody\" ] || [ \"\$username\" = \"www-data\" ]; then
                usermod -aG $group_name \"\$username\" 2>/dev/null || true
            fi
        done
    " 2>/dev/null


    if command -v setfacl >/dev/null 2>&1; then
        pct exec "$ctid" -- getent passwd | awk -F: '{print $1, $3}' | while read user uid; do
            [[ "$uid" -eq 0 ]] && continue   
            host_uid=$((uid_shift + uid))
            setfacl -m u:$host_uid:rwx "$host_dir" 2>/dev/null || true
        done
        msg_ok "$(translate "ACL permissions applied for container users")"
    fi


    chmod 2775 "$host_dir" 2>/dev/null || true
    chgrp "$group_name" "$host_dir" 2>/dev/null || true

    msg_ok "$(translate "Group mapping ensured:") host=$host_gid → ct=$mapped_gid"
    msg_ok "$(translate "Multi-approach access configuration completed")"

    return 0
}





get_next_mp_index() {
    local ctid="$1"
    local conf="/etc/pve/lxc/${ctid}.conf"
    
    if [[ ! "$ctid" =~ ^[0-9]+$ ]] || [[ ! -f "$conf" ]]; then
        echo "0"
        return 0
    fi
    
    local used idx next=0
    used=$(awk -F: '/^mp[0-9]+:/ {print $1}' "$conf" | sed 's/mp//' | sort -n)
    for idx in $used; do
        [[ "$idx" -ge "$next" ]] && next=$((idx+1))
    done
    echo "$next"
}


add_bind_mount() {
    local ctid="$1" host_path="$2" ct_path="$3"
    local mpidx result
    
    if [[ ! "$ctid" =~ ^[0-9]+$ ]]; then
        msg_error "$(translate 'Invalid container ID format:') $ctid"
        return 1
    fi
    
    if [[ -z "$ctid" || -z "$host_path" || -z "$ct_path" ]]; then
        msg_error "$(translate "Missing arguments")"
        return 1
    fi


    if pct config "$ctid" | grep -q "$host_path"; then
        echo -e
        msg_warn "$(translate "Directory already mounted in container configuration.")"
        echo -e ""
        msg_success "$(translate 'Press Enter to return to menu...')"
        read -r
        return 1
    fi

    mpidx=$(get_next_mp_index "$ctid")
    
    result=$(pct set "$ctid" -mp${mpidx} "$host_path,mp=$ct_path,backup=0,ro=0,acl=1" 2>&1)

    if [[ $? -eq 0 ]]; then
        msg_ok "$(translate "Successfully mounted:") $host_path → $ct_path"
        return 0
    else
        msg_error "$(translate "Error mounting folder:") $result"
        return 1
    fi
}








select_container_mount_point() {
    local ctid="$1"
    local host_dir="$2"
    local choice mount_point existing_dirs options

    while true; do
        choice=$(whiptail --title "$(translate "Configure Mount Point inside LXC")" \
            --menu "$(translate "Where to mount inside container?")" 18 70 5 \
            "1" "$(translate "Create new directory in /mnt")" \
            "2" "$(translate "Use existing directory in /mnt")" \
            "3" "$(translate "Enter path manually")" \
            "4" "$(translate "Cancel")" 3>&1 1>&2 2>&3) || return 1

        case "$choice" in
            1)
                mount_point=$(whiptail --inputbox "$(translate "Enter folder name for /mnt:")" 10 60 "shared" 3>&1 1>&2 2>&3) || continue
                [[ -z "$mount_point" ]] && continue
                mount_point="/mnt/$mount_point"
                pct exec "$ctid" -- mkdir -p "$mount_point" 2>/dev/null
                ;;

            2)
                existing_dirs=$(pct exec "$ctid" -- ls -1 /mnt 2>/dev/null | awk '{print "/mnt/"$1" "$1}')
                if [[ -z "$existing_dirs" ]]; then
                    whiptail --msgbox "$(translate "No existing directories found in /mnt")" 8 60
                    continue
                fi
                mount_point=$(whiptail --title "$(translate "Select Existing Folder")" \
                    --menu "$(translate "Choose a folder from /mnt:")" 20 70 10 \
                    $existing_dirs 3>&1 1>&2 2>&3) || continue
                ;;

            3)
                mount_point=$(whiptail --inputbox "$(translate "Enter full path:")" 10 70 "/mnt/shared" 3>&1 1>&2 2>&3) || continue
                [[ -z "$mount_point" ]] && continue
                pct exec "$ctid" -- mkdir -p "$mount_point" 2>/dev/null
                ;;

            4)
                return 1
                ;;
        esac

        if pct exec "$ctid" -- test -d "$mount_point" 2>/dev/null; then
            echo "$mount_point"
            return 0
        else
            whiptail --msgbox "$(translate "Could not create or access directory:") $mount_point" 8 70
            continue
        fi
    done
}



mount_host_directory_to_lxc() {
    
    # Step 1: Select container
    local container_id
    container_id=$(select_lxc_container)
    if [[ $? -ne 0 || -z "$container_id" ]]; then
        return 1
    fi

    show_proxmenux_logo
    msg_title "$(translate 'Mount Host Directory to LXC Container')"

    # Step 1.1: Ensure running
    ct_status=$(pct status "$container_id" | awk '{print $2}')
    if [[ "$ct_status" != "running" ]]; then
        msg_info "$(translate "Starting container") $container_id..."
        if pct start "$container_id"; then
            sleep 3
            msg_ok "$(translate "Container started")"
        else
            msg_error "$(translate "Failed to start container")"
            return 1
        fi
    fi
    msg_ok "$(translate 'Select LXC container')"



    # Step 2: Select host directory
    local host_dir
    host_dir=$(select_host_directory)
    if [[ -z "$host_dir" ]]; then
        return 1
    fi
    msg_ok "$(translate 'Select Host directory')"

    # Step 3: Setup group
    local group_name="sharedfiles"
    local group_gid
    group_gid=$(pmx_ensure_host_group "$group_name")
    if [[ -z "$group_gid" ]]; then
        return 1
    fi
    
    # Set basic permissions
    chown -R root:"$group_name" "$host_dir" 2>/dev/null || true
    chmod -R 2775 "$host_dir" 2>/dev/null || true

    msg_ok "$(translate 'Select container mount point')"
    
    # Step 4: Select container mount point
    local ct_mount_point
    ct_mount_point=$(select_container_mount_point "$container_id" "$host_dir")
    if [[ -z "$ct_mount_point" ]]; then
        return 1
    fi
    
    # Step 5: Confirmation
    local uid_shift container_type
    uid_shift=$(get_container_uid_shift "$container_id")
    if [[ "$uid_shift" -eq 0 ]]; then
        container_type="$(translate 'Privileged')"
    else
        container_type="$(translate 'Unprivileged')"
    fi

    local confirm_msg="$(translate "Mount Configuration:")

$(translate "Container ID:"): $container_id ($container_type)
$(translate "Host Directory:"): $host_dir
$(translate "Container Mount Point:"): $ct_mount_point
$(translate "Shared Group:"): $group_name (GID: $group_gid)

$(translate "Proceed?")"

    if ! whiptail --title "$(translate "Confirm Mount")" --yesno "$confirm_msg" 16 70; then
        return 1
    fi
    
    # Step 6: Add mount
    if ! add_bind_mount "$container_id" "$host_dir" "$ct_mount_point"; then
        return 1
    fi
    




    # Step 7: Setup access ======================================================

    setup_container_access "$container_id" "$group_name" "$group_gid" "$host_dir"
    
    # ===========================================================================




    # Step 8: Final setup
    pct exec "$container_id" -- chgrp "$group_name" "$ct_mount_point" 2>/dev/null || true
    pct exec "$container_id" -- chmod 2775 "$ct_mount_point" 2>/dev/null || true
    
    # Step 9: Summary
    echo -e ""
    echo -e "${TAB}${BOLD}$(translate 'Mount Added Successfully:')${CL}"
    echo -e "${TAB}${BGN}$(translate 'Container:')${CL} ${BL}$container_id ($container_type)${CL}"
    echo -e "${TAB}${BGN}$(translate 'Host Directory:')${CL} ${BL}$host_dir${CL}"
    echo -e "${TAB}${BGN}$(translate 'Mount Point:')${CL} ${BL}$ct_mount_point${CL}"
    echo -e "${TAB}${BGN}$(translate 'Group:')${CL} ${BL}$group_name (GID: $group_gid)${CL}"
    

    echo -e ""
    if whiptail --yesno "$(translate "Restart container to activate mount?")" 8 60; then
        msg_info "$(translate 'Restarting container...')"
        if pct reboot "$container_id"; then
            sleep 5
            msg_ok "$(translate 'Container restarted successfully')"
            
            echo -e
            echo -e "${TAB}${BOLD}$(translate 'Testing access and read/write:')${CL}"
            test_user=$(pct exec "$container_id" -- sh -c "id -u ncp >/dev/null 2>&1 && echo ncp || echo www-data")

            if pct exec "$container_id" -- su -s /bin/bash $test_user -c "touch $ct_mount_point/test_access.txt" 2>/dev/null; then
                msg_ok "$(translate "Mount access and read/write successful (tested as $test_user)")"
                rm -f "$host_dir/test_access.txt" 2>/dev/null || true
            else
                msg_warn "$(translate "⚠ Access test failed - check permissions (user: $test_user)")"
            fi

        else
            msg_warn "$(translate 'Failed to restart - restart manually')"
        fi
    fi
    
    echo -e ""
    msg_success "$(translate 'Press Enter to continue...')"
    read -r
}

# ==========================================================


main_menu() {
    while true; do
        choice=$(dialog --title "$(translate 'LXC Mount Manager')" \
            --menu "$(translate 'Choose an option:')" 16 60 4 \
            "1" "$(translate 'Mount Host Directory to LXC')" \
            "2" "$(translate 'View Mount Points')" \
            "3" "$(translate 'Remove Mount Point')" \
            "4" "$(translate 'Exit')" 3>&1 1>&2 2>&3)
        
        case $choice in
            1)
                mount_host_directory_to_lxc
                ;;
            2)
                msg_info2 "$(translate 'Feature coming soon...')"
                read -p "$(translate 'Press Enter to continue...')"
                ;;
            3)
                msg_info2 "$(translate 'Feature coming soon...')"
                read -p "$(translate 'Press Enter to continue...')"
                ;;
            4|"")
                exit 0
                ;;
        esac
    done
}



main_menu
