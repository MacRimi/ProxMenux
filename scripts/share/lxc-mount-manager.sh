#!/bin/bash
# ==========================================================
# ProxMenux - LXC Mount Manager
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT
# Version     : 3.1-enhanced
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




    # ===================================================================
    # CONTAINER TYPE DETECTION AND STRATEGY
    # ===================================================================

    if [[ "$uid_shift" -eq 0 ]]; then
        msg_ok "$(translate "PRIVILEGED container detected - using direct UID/GID mapping")"
        mapped_gid="$host_gid"
        container_type="privileged"
    else
        msg_ok "$(translate "UNPRIVILEGED container detected - using mapped UID/GID")"
        mapped_gid=$((uid_shift + host_gid))
        container_type="unprivileged"
        msg_ok "UID shift: $uid_shift, Host GID: $host_gid → Container GID: $mapped_gid"

    fi





    # ===================================================================
    # STEP 1: ACL TOOLS (only for unprivileged containers)
    # ===================================================================

    if [[ "$container_type" == "unprivileged" ]]; then
        if ! command -v setfacl >/dev/null 2>&1; then
            msg_info "$(translate "Installing ACL tools (REQUIRED for unprivileged containers)...")"
            apt-get update >/dev/null 2>&1
            apt-get install -y acl >/dev/null 2>&1
            if command -v setfacl >/dev/null 2>&1; then
                msg_ok "$(translate "ACL tools installed successfully")"
            else
                msg_error "$(translate "Failed to install ACL tools - permissions may not work correctly")"
            fi
        else
            msg_ok "$(translate "ACL tools already available")"
        fi
    else
        msg_ok "$(translate "Privileged container - ACL tools not required (using POSIX permissions)")"
    fi





    # ===================================================================
    # STEP 2: CONTAINER GROUP CONFIGURATION
    # ===================================================================

    msg_info "$(translate "Configuring container group with") $container_type $(translate "strategy...")"
    
    pct exec "$ctid" -- sh -c "
        # Remove existing group if GID is wrong
        if getent group $group_name >/dev/null 2>&1; then
            current_gid=\$(getent group $group_name | cut -d: -f3)
            if [ \"\$current_gid\" != \"$mapped_gid\" ]; then
                groupdel $group_name 2>/dev/null || true
            fi
        fi
        
        # Create group with correct GID
        groupadd -g $mapped_gid $group_name 2>/dev/null || true
    " 2>/dev/null

    msg_ok "$(translate "Container group configured:") $group_name (GID: $mapped_gid)"





    # ===================================================================
    # STEP 3: USER PROCESSING (different strategies)
    # ===================================================================

    local container_users
    container_users=$(pct exec "$ctid" -- getent passwd | awk -F: '{print $1 ":" $3}' 2>/dev/null)
    
    local users_added=0
    local acls_applied=0
    
    if [[ "$container_type" == "privileged" ]]; then

        
        msg_ok "$(translate "Privileged container:") $users_added $(translate "users added to group (no ACLs needed)")"
        
    else

        msg_info "$(translate "Using UNPRIVILEGED strategy: mapped UIDs + ACL permissions")"
        
        while IFS=: read -r username ct_uid; do
            if [[ -n "$username" && "$ct_uid" =~ ^[0-9]+$ ]]; then
                local host_uid=$((uid_shift + ct_uid))
                
                if pct exec "$ctid" -- usermod -aG "$group_name" "$username" 2>/dev/null; then
                    users_added=$((users_added + 1))
                    
                    if command -v setfacl >/dev/null 2>&1; then
                        setfacl -m u:$host_uid:rwx "$host_dir" 2>/dev/null
                        setfacl -m d:u:$host_uid:rwx "$host_dir" 2>/dev/null
                        acls_applied=$((acls_applied + 1))
                    fi
                    
                    case "$username" in
                        root|www-data|ncp|nobody|ubuntu|debian)
                            msg_ok "$(translate "Configured user:") $username (CT_UID:$ct_uid → HOST_UID:$host_uid)"
                            ;;
                    esac
                fi
            fi
        done <<< "$container_users"
        
        msg_ok "$(translate "Unprivileged container:") $users_added $(translate "users added,") $acls_applied $(translate "ACL entries applied")"
    fi




    # ===================================================================
    # STEP 4: DIRECTORY PERMISSIONS
    # ===================================================================
    msg_info "$(translate "Setting optimal directory permissions...")"
    
    chmod 2775 "$host_dir" 2>/dev/null || true
    chgrp "$group_name" "$host_dir" 2>/dev/null || true
    
    msg_ok "$(translate "Host directory permissions:") 2775 root:$group_name"





    # ===================================================================
    # STEP 5: VERIFICATION
    # ===================================================================
    msg_info "$(translate "Verifying configuration...")"
    
    if [[ "$container_type" == "unprivileged" ]] && command -v getfacl >/dev/null 2>&1; then
        local acl_count=$(getfacl "$host_dir" 2>/dev/null | grep "^user:" | grep -v "^user::" | wc -l)
        msg_ok "$(translate "ACL entries configured:") $acl_count"
        
        # Show sample ACL entries
        if [[ $acl_count -gt 0 ]]; then
            echo -e "${TAB}${BGN}$(translate "ACL entries:")${CL}"
            getfacl "$host_dir" 2>/dev/null | grep "^user:" | grep -v "^user::" | head -3 | while read acl_line; do
                echo -e "${TAB}  ${BL}$acl_line${CL}"
            done
        fi
    fi
    

    local test_users=("www-data" "root" "ncp" "nobody")
    local successful_tests=0
    
    for test_user in "${test_users[@]}"; do
        if pct exec "$ctid" -- id "$test_user" >/dev/null 2>&1; then
            if pct exec "$ctid" -- su -s /bin/bash "$test_user" -c "ls '$4' >/dev/null 2>&1" 2>/dev/null; then
                successful_tests=$((successful_tests + 1))
            fi
        fi
    done
    
    if [[ $successful_tests -gt 0 ]]; then
        msg_ok "$(translate "Access verification:") $successful_tests $(translate "users can access mount point")"
    fi


    if [[ "$container_type" == "privileged" ]]; then
        msg_ok "$(translate "PRIVILEGED container configuration completed - using direct POSIX permissions")"
    else
        msg_ok "$(translate "UNPRIVILEGED container configuration completed - using ACL permissions")"
    fi
    
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
    msg_ok "$(translate 'Container selected and running')"

    # Step 2: Select host directory
    local host_dir
    host_dir=$(select_host_directory)
    if [[ -z "$host_dir" ]]; then
        return 1
    fi
    msg_ok "$(translate 'Host directory selected')"

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

    msg_ok "$(translate 'Host group configured')"
    
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
    
    # Step 7: Setup access (handles both privileged and unprivileged)
    setup_container_access "$container_id" "$group_name" "$group_gid" "$host_dir"
    
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
    
    if [[ "$uid_shift" -eq 0 ]]; then
        echo -e "${TAB}${BGN}$(translate 'Permission Strategy:')${CL} ${BL}POSIX (direct mapping)${CL}"
    else
        echo -e "${TAB}${BGN}$(translate 'Permission Strategy:')${CL} ${BL}ACL (mapped UIDs)${CL}"
    fi

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

# Main menu
main_menu() {
    while true; do
        choice=$(dialog --title "$(translate 'LXC Mount Manager')" \
            --menu "\n$(translate 'Choose an option:')" 25 80 15 \
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
