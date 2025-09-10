#!/bin/bash
# ==========================================================
# ProxMenux - LXC Mount Manager
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT
# Version     : 5.0-minimal
# Last Updated: $(date +%d/%m/%Y)
# ==========================================================

BASE_DIR="/usr/local/share/proxmenux"
source "$BASE_DIR/utils.sh"

load_language
initialize_cache



detect_mounted_shares() {
    local mounted_shares=()
    
    while IFS= read -r line; do
        local device mount_point fs_type options dump pass
        read -r device mount_point fs_type options dump pass <<< "$line"
        
        local is_network=false
        local type=""
        
        case "$fs_type" in
            nfs|nfs4)
                is_network=true
                type="NFS"
                ;;
            cifs)
                is_network=true
                type="CIFS/SMB"
                ;;
        esac
        

        if [[ "$is_network" == true ]]; then

            local exclude_internal=false
            local internal_mounts=(
                "/mnt/pve/local"
                "/mnt/pve/local-lvm" 
                "/mnt/pve/local-zfs"
                "/mnt/pve/backup"
                "/mnt/pve/snippets"
                "/mnt/pve/dump"
                "/mnt/pve/images"
                "/mnt/pve/template"
                "/mnt/pve/private"
                "/mnt/pve/vztmpl"
            )
            
            for internal_mount in "${internal_mounts[@]}"; do
                if [[ "$mount_point" == "$internal_mount" || "$mount_point" =~ ^${internal_mount}/ ]]; then
                    exclude_internal=true
                    break
                fi
            done
            

            if [[ "$exclude_internal" == false ]]; then

                local size used
                local df_info=$(df -h "$mount_point" 2>/dev/null | tail -n1)
                if [[ -n "$df_info" ]]; then
                    size=$(echo "$df_info" | awk '{print $2}')
                    used=$(echo "$df_info" | awk '{print $3}')
                else
                    size="N/A"
                    used="N/A"
                fi
                

                local mount_source="Manual"
                if [[ "$mount_point" =~ ^/mnt/pve/ ]]; then
                    mount_source="Proxmox-GUI"
                fi
                
                mounted_shares+=("$mount_point|$device|$type|$size|$used|$mount_source")
            fi
        fi
    done < /proc/mounts
    
    printf '%s\n' "${mounted_shares[@]}"
}

detect_fstab_network_mounts() {
    local fstab_mounts=()
    

    while IFS= read -r line; do

        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// }" ]] && continue
        

        local source mount_point fs_type options dump pass
        read -r source mount_point fs_type options dump pass <<< "$line"
        

        local is_network=false
        local type=""
        
        case "$fs_type" in
            nfs|nfs4)
                is_network=true
                type="NFS"
                ;;
            cifs)
                is_network=true
                type="CIFS/SMB"
                ;;
        esac
        
        if [[ "$is_network" == true && -d "$mount_point" ]]; then

            local is_mounted=false
            while IFS= read -r proc_line; do
                local proc_device proc_mount_point proc_fs_type
                read -r proc_device proc_mount_point proc_fs_type _ <<< "$proc_line"
                if [[ "$proc_mount_point" == "$mount_point" && ("$proc_fs_type" == "nfs" || "$proc_fs_type" == "nfs4" || "$proc_fs_type" == "cifs") ]]; then
                    is_mounted=true
                    break
                fi
            done < /proc/mounts
            

            if [[ "$is_mounted" == false ]]; then
                fstab_mounts+=("$mount_point|$source|$type|0|0|fstab-inactive")
            fi
        fi
    done < /etc/fstab
    
    printf '%s\n' "${fstab_mounts[@]}"
}


detect_local_directories() {
    local local_dirs=()
    local network_mounts=()
    

    local all_network_mounts
    all_network_mounts=$(detect_mounted_shares)
    local fstab_network_mounts
    fstab_network_mounts=$(detect_fstab_network_mounts)
    

    local combined_network_mounts="$all_network_mounts"$'\n'"$fstab_network_mounts"

    while IFS='|' read -r mount_point source type size used mount_source; do
        [[ -n "$mount_point" ]] && network_mounts+=("$mount_point")
    done <<< "$combined_network_mounts"
    
    if [[ -d "/mnt" ]]; then
        for dir in /mnt/*/; do
            if [[ -d "$dir" && "$(basename "$dir")" != "pve" ]]; then
                local dir_path="${dir%/}"  
                local dir_name=$(basename "$dir_path")
                

                local is_network_mount=false
                
                for network_mount in "${network_mounts[@]}"; do
                    if [[ "$dir_path" == "$network_mount" ]]; then
                        is_network_mount=true
                        break
                    fi
                done
                

                if [[ "$is_network_mount" == false ]]; then
                    local dir_size=$(du -sh "$dir_path" 2>/dev/null | awk '{print $1}')
                    local_dirs+=("$dir_path|Local|Directory|$dir_size|-|Manual")
                fi
            fi
        done
    fi
    
    printf '%s\n' "${local_dirs[@]}"
}


are_same_resource() {
    local path1="$1" source1="$2" type1="$3"
    local path2="$4" source2="$5" type2="$6"
    

    [[ "$type1" != "$type2" ]] && return 1
    

    local server1 share1 server2 share2
    
    if [[ "$type1" == "NFS" ]]; then

        server1=$(echo "$source1" | cut -d: -f1)
        share1=$(echo "$source1" | cut -d: -f2)
        server2=$(echo "$source2" | cut -d: -f1)
        share2=$(echo "$source2" | cut -d: -f2)
    elif [[ "$type1" == "CIFS/SMB" ]]; then

        server1=$(echo "$source1" | cut -d/ -f3)
        share1=$(echo "$source1" | cut -d/ -f4-)
        server2=$(echo "$source2" | cut -d/ -f3)
        share2=$(echo "$source2" | cut -d/ -f4-)
    else
        return 1
    fi
    

    if [[ "$server1" == "$server2" && "$share1" == "$share2" ]]; then
        return 0  
    else
        return 1  
    fi
}



detect_problematic_storage() {
    local mount_point="$1"
    local mount_source="$2"
    local type="$3"
    

    if [[ "$mount_source" == "Proxmox-GUI" && "$type" == "CIFS/SMB" ]]; then

        local permissions=$(stat -c '%a' "$mount_point" 2>/dev/null)
        local owner=$(stat -c '%U' "$mount_point" 2>/dev/null)
        local group=$(stat -c '%G' "$mount_point" 2>/dev/null)
        

        if [[ "$owner" == "root" && "$group" == "root" && "$permissions" =~ ^75[0-5]$ ]]; then
            return 0  
        fi
    fi
    
    return 1  
}




select_host_directory_unified() {
    local mounted_shares local_dirs options=() fstab_mounts
    

    mounted_shares=$(detect_mounted_shares)
    fstab_mounts=$(detect_fstab_network_mounts)
    local_dirs=$(detect_local_directories)
    

    local all_network_shares="$mounted_shares"
    if [[ -n "$fstab_mounts" ]]; then
        all_network_shares="$all_network_shares"$'\n'"$fstab_mounts"
    fi
    

    local has_local_dirs=false
    local has_network_shares=false
    
    [[ -n "$local_dirs" ]] && has_local_dirs=true
    [[ -n "$all_network_shares" ]] && has_network_shares=true
    
    if [[ "$has_local_dirs" == false && "$has_network_shares" == false ]]; then
        whiptail --title "$(translate "No Directories Found")" \
            --msgbox "$(translate "No directories found in /mnt and no mounted network shares detected.")\n\n$(translate "Please:")\n• Mount shares using Proxmox GUI\n• Create directories in /mnt\n• Use manual path entry" 12 70
        

        local manual_path
        manual_path=$(whiptail --title "$(translate "Manual Path Entry")" \
            --inputbox "$(translate "Enter the full path to the host directory:")" 10 70 "/mnt/" 3>&1 1>&2 2>&3)
        
        if [[ -n "$manual_path" && -d "$manual_path" ]]; then
            echo "$manual_path"
            return 0
        else
            return 1
        fi
    fi

    local processed_resources=()
    local final_shares=()
    

    while IFS='|' read -r mount_point source type size used mount_source; do
        if [[ -n "$mount_point" ]]; then

            local is_duplicate=false
            local duplicate_index=-1
            
            for i in "${!processed_resources[@]}"; do
                IFS='|' read -r proc_path proc_source proc_type proc_size proc_used proc_mount_source <<< "${processed_resources[$i]}"
                if are_same_resource "$mount_point" "$source" "$type" "$proc_path" "$proc_source" "$proc_type"; then

                    if [[ ("$mount_source" == "Manual" || "$proc_mount_source" =~ ^fstab) && "$proc_mount_source" == "Proxmox-GUI" ]]; then

                        is_duplicate=true
                        duplicate_index=$i
                        break
                    elif [[ "$mount_source" == "Proxmox-GUI" && ("$proc_mount_source" == "Manual" || "$proc_mount_source" =~ ^fstab) ]]; then

                        is_duplicate=true
                        break
                    fi
                fi
            done
            
            if [[ "$is_duplicate" == true && "$duplicate_index" -ge 0 ]]; then

                processed_resources[$duplicate_index]="$mount_point|$source|$type|$size|$used|$mount_source"
            elif [[ "$is_duplicate" == false ]]; then

                processed_resources+=("$mount_point|$source|$type|$size|$used|$mount_source")
            fi
        fi
    done <<< "$all_network_shares"

    if [[ "$has_local_dirs" == true ]]; then
        options+=("" "\Z4───────────────── LOCAL DIRECTORIES ─────────────────\Zn")
        
        while IFS='|' read -r dir_path source type size used mount_source; do
            if [[ -n "$dir_path" && "$type" == "Directory" ]]; then
                local dir_name=$(basename "$dir_path")
                local permissions=$(stat -c '%a' "$dir_path" 2>/dev/null)
                local owner_group=$(stat -c '%U:%G' "$dir_path" 2>/dev/null)
                options+=("$dir_path" "$dir_name ($size)")
            fi
        done <<< "$local_dirs"
    fi

    if [[ ${#processed_resources[@]} -gt 0 ]]; then

        [[ "$has_local_dirs" == true ]] && options+=("" "")
        options+=("" "\Z4────────────────── NETWORK SHARES──────────────────\Zn")
        
        for resource in "${processed_resources[@]}"; do
            IFS='|' read -r mount_point source type size used mount_source <<< "$resource"
            
            local share_name=$(basename "$source")
            local mount_name=$(basename "$mount_point")
            local permissions=$(stat -c '%a' "$mount_point" 2>/dev/null)
            local owner_group=$(stat -c '%U:%G' "$mount_point" 2>/dev/null)
            

            local alternatives=0
            while IFS='|' read -r alt_mount_point alt_source alt_type alt_size alt_used alt_mount_source; do
                if [[ -n "$alt_mount_point" && "$alt_mount_point" != "$mount_point" ]]; then
                    if are_same_resource "$mount_point" "$source" "$type" "$alt_mount_point" "$alt_source" "$alt_type"; then
                        alternatives=$((alternatives + 1))
                    fi
                fi
            done <<< "$all_network_shares"
            
            local alt_text=""
            [[ $alternatives -gt 0 ]] && alt_text=" (+$alternatives alternative$([ $alternatives -gt 1 ] && echo 's'))"
            

            local warning=""
            if detect_problematic_storage "$mount_point" "$mount_source" "$type"; then
                warning=" [READ-ONLY]"
            fi
            
            local prefix=""
            case "$mount_source" in
                "Proxmox-GUI")
                    prefix="GUI-"
                    ;;
                "fstab-active")
                    prefix="fstab-"
                    ;;
                "fstab-inactive")
                    prefix="fstab(off)-"
                    ;;
                *)
                    prefix=""
                    ;;
            esac
            
            options+=("$mount_point" "$prefix$type: $share_name → $mount_name ($size)$warning$alt_text")

        done
    fi
    

    options+=("" "")
    options+=("" "\Z4────────────────────── OTHER ──────────────────────\Zn")
    options+=("MANUAL" "$(translate "Enter path manually")")
    
    if [[ ${#options[@]} -eq 0 ]]; then
        dialog --title "$(translate "No Valid Options")" \
            --msgbox "$(translate "No valid directories or shares found.")" 8 50
        return 1
    fi
    

    local result
    result=$(dialog --clear --colors --title "$(translate "Select Host Directory")" \
        --menu "\n$(translate "Select the directory to bind to container:")" 25 85 15 \
        "${options[@]}" 3>&1 1>&2 2>&3)


    
    local dialog_result=$?
    if [[ $dialog_result -ne 0 ]]; then
        return 1
    fi
    

    if [[ -z "$result" || "$result" =~ ^━ ]]; then
        return 1
    fi

    
    if [[ "$result" == "MANUAL" ]]; then
        result=$(whiptail --title "$(translate "Manual Path Entry")" \
            --inputbox "$(translate "Enter the full path to the host directory:")" 10 70 "/mnt/" 3>&1 1>&2 2>&3)        
        if [[ $? -ne 0 ]]; then
            return 1
        fi
    fi

    if [[ -z "$result" ]]; then
        return 1
    fi

    if [[ ! -d "$result" ]]; then
        whiptail --title "$(translate "Invalid Path")" \
            --msgbox "$(translate "The selected path is not a valid directory:") $result" 8 70
        return 1
    fi


    if detect_problematic_storage "$result" "Proxmox-GUI" "CIFS/SMB"; then
dialog --clear --title "$(translate "CIFS Storage Notice")" --yesno "\
$(translate "\nThis directory is a CIFS storage configured from the Proxmox web interface.")\n\n\
$(translate "When CIFS storage is configured through the Proxmox GUI, it applies restrictive permissions.")\n\
$(translate "As a result, LXC containers can usually READ files but may NOT be able to WRITE.")\n\n\
$(translate "If you need WRITE access, cancel this operation and instead use the option:")\n\
$(translate "Configure Samba shared on Host")\n\n\

$(translate "Do you want to continue anyway?")" 18 80 3>&1 1>&2 2>&3

        dialog_result=$?

        case $dialog_result in
            0)  
                ;;
            1|255)  
                return 1
                ;;
        esac
    fi

    echo "$result"
    return 0
}




select_lxc_container() {
    local ct_list ctid ct_status
    
    ct_list=$(pct list 2>/dev/null | awk 'NR>1 {print $1, $2, $3}')
    if [[ -z "$ct_list" ]]; then
        whiptail --title "Error" \
            --msgbox "No LXC containers available" 8 50
        return 1
    fi

    local options=()
    while read -r id name status; do
        if [[ -n "$id" && "$id" =~ ^[0-9]+$ ]]; then
            name=${name:-"unnamed"}
            status=${status:-"unknown"}
            options+=("$id" "$name ($status)")
        fi
    done <<< "$ct_list"
    
    if [[ ${#options[@]} -eq 0 ]]; then
        dialog --title "Error" \
            --msgbox "No valid containers found" 8 50
        return 1
    fi

    ctid=$(dialog --title "Select LXC Container" \
        --menu "Select container:" 25 85 15 \
        "${options[@]}" 3>&1 1>&2 2>&3)
    
    local result=$?
    if [[ $result -ne 0 || -z "$ctid" ]]; then
        return 1
    fi

    echo "$ctid"
    return 0
}


select_container_mount_point() {
    local ctid="$1"
    local host_dir="$2"
    local choice mount_point base_name

    base_name=$(basename "$host_dir")

    while true; do
        choice=$(dialog --clear --title "$(translate "Configure Mount Point inside LXC")" \
            --menu "\n$(translate "Where to mount inside container?")" 18 70 5 \
            "1" "$(translate "Create new directory in /mnt")" \
            "2" "$(translate "Enter path manually")" \
            "3" "$(translate "Cancel")" 3>&1 1>&2 2>&3)
        
        local dialog_result=$?
        if [[ $dialog_result -ne 0 ]]; then
            return 1
        fi

        case "$choice" in
            1)
                mount_point=$(whiptail --inputbox "$(translate "Enter folder name for /mnt:")" \
                    10 60 "$base_name" 3>&1 1>&2 2>&3)
                if [[ $? -ne 0 ]]; then
                    continue
                fi
                [[ -z "$mount_point" ]] && continue
                mount_point="/mnt/$mount_point"
                pct exec "$ctid" -- mkdir -p "$mount_point" 2>/dev/null
                ;;

            2)
                mount_point=$(whiptail --inputbox "$(translate "Enter full path:")" \
                    10 70 "/mnt/$base_name" 3>&1 1>&2 2>&3)
                if [[ $? -ne 0 ]]; then
                    continue
                fi
                [[ -z "$mount_point" ]] && continue
                pct exec "$ctid" -- mkdir -p "$mount_point" 2>/dev/null
                ;;

            3)
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

# ==========================================================
# MOUNT MANAGEMENT FUNCTIONS
# ==========================================================


view_mount_points() {
    show_proxmenux_logo
    msg_title "$(translate 'Current LXC Mount Points')"
    
    local ct_list
    ct_list=$(pct list 2>/dev/null | awk 'NR>1 {print $1, $2, $3}')
    
    if [[ -z "$ct_list" ]]; then
        msg_warn "$(translate 'No LXC containers found')"
        echo -e ""
        msg_success "$(translate 'Press Enter to continue...')"
        read -r
        return 1
    fi
    
    local found_mounts=false
    
    while read -r id name status; do
        if [[ -n "$id" && "$id" =~ ^[0-9]+$ ]]; then
            local conf="/etc/pve/lxc/${id}.conf"
            if [[ -f "$conf" ]]; then
                local mounts
                mounts=$(grep "^mp[0-9]*:" "$conf" 2>/dev/null)
                
                if [[ -n "$mounts" ]]; then
                    if [[ "$found_mounts" == false ]]; then
                        found_mounts=true
                    fi
                    
                    echo -e "${TAB}${BOLD}$(translate 'Container') $id: $name ($status)${CL}"
                    
                    while IFS= read -r mount_line; do
                        if [[ -n "$mount_line" ]]; then
                            local mp_id=$(echo "$mount_line" | cut -d: -f1)
                            local mount_info=$(echo "$mount_line" | cut -d: -f2-)
                            local host_path=$(echo "$mount_info" | cut -d, -f1)
                            local container_path=$(echo "$mount_info" | grep -o 'mp=[^,]*' | cut -d= -f2)
                            local options=$(echo "$mount_info" | sed 's/^[^,]*,mp=[^,]*,*//')
                            
                            echo -e "${TAB}  ${BGN}$mp_id:${CL} ${BL}$host_path${CL} → ${BL}$container_path${CL}"
                            [[ -n "$options" ]] && echo -e "${TAB}    ${DGN}Options: $options${CL}"
                        fi
                    done <<< "$mounts"
                    echo ""
                fi
            fi
        fi
    done <<< "$ct_list"
    
    if [[ "$found_mounts" == false ]]; then
        msg_ok "$(translate 'No mount points found in any container')"
    fi
    
    echo -e ""
    msg_success "$(translate 'Press Enter to continue...')"
    read -r
}





remove_mount_point() {
    show_proxmenux_logo
    msg_title "$(translate 'Remove LXC Mount Point')"
    

    local container_id
    container_id=$(select_lxc_container)
    if [[ $? -ne 0 || -z "$container_id" ]]; then
        return 1
    fi
    
    local conf="/etc/pve/lxc/${container_id}.conf"
    if [[ ! -f "$conf" ]]; then
        msg_error "$(translate 'Container configuration not found')"
        echo -e ""
        msg_success "$(translate 'Press Enter to continue...')"
        read -r
        return 1
    fi
    

    local mounts
    mounts=$(grep "^mp[0-9]*:" "$conf" 2>/dev/null)
    
    if [[ -z "$mounts" ]]; then
        show_proxmenux_logo
        msg_title "$(translate 'Remove LXC Mount Point')"
        msg_warn "$(translate 'No mount points found in container') $container_id"
        echo -e ""
        msg_success "$(translate 'Press Enter to continue...')"
        read -r
        return 1
    fi
    

    local options=()
    while IFS= read -r mount_line; do
        if [[ -n "$mount_line" ]]; then
            local mp_id=$(echo "$mount_line" | cut -d: -f1)
            local mount_info=$(echo "$mount_line" | cut -d: -f2-)
            local host_path=$(echo "$mount_info" | cut -d, -f1)
            local container_path=$(echo "$mount_info" | grep -o 'mp=[^,]*' | cut -d= -f2)
            
            options+=("$mp_id" "$host_path → $container_path")
        fi
    done <<< "$mounts"
    
    if [[ ${#options[@]} -eq 0 ]]; then
        show_proxmenux_logo
        msg_title "$(translate 'Remove LXC Mount Point')"
        msg_warn "$(translate 'No valid mount points found')"
        echo -e ""
        msg_success "$(translate 'Press Enter to continue...')"
        read -r
        return 1
    fi
    

    local selected_mp
    selected_mp=$(dialog --clear --title "$(translate "Select Mount Point to Remove")" \
        --menu "\n$(translate "Select mount point to remove from container") $container_id:" 20 80 10 \
        "${options[@]}" 3>&1 1>&2 2>&3)
    
    if [[ $? -ne 0 || -z "$selected_mp" ]]; then
        return 1
    fi
    

    local selected_mount_line
    selected_mount_line=$(grep "^${selected_mp}:" "$conf")
    local mount_info=$(echo "$selected_mount_line" | cut -d: -f2-)
    local host_path=$(echo "$mount_info" | cut -d, -f1)
    local container_path=$(echo "$mount_info" | grep -o 'mp=[^,]*' | cut -d= -f2)

    local confirm_msg="$(translate "Remove Mount Point Confirmation:")

$(translate "Container ID"): $container_id
$(translate "Mount Point ID"): $selected_mp
$(translate "Host Path"): $host_path
$(translate "Container Path"): $container_path

$(translate "WARNING"): $(translate "This will remove the mount point from the container configuration.")
$(translate "The host directory and its contents will remain unchanged.")

$(translate "Proceed with removal")?"

    if ! dialog --clear --title "$(translate "Confirm Mount Point Removal")" --yesno "$confirm_msg" 18 80; then
        return 1
    fi
    
    show_proxmenux_logo
    msg_title "$(translate 'Remove LXC Mount Point')"
    
    msg_info "$(translate 'Removing mount point') $selected_mp $(translate 'from container') $container_id..."
    

    if pct set "$container_id" --delete "$selected_mp" 2>/dev/null; then
        msg_ok "$(translate 'Mount point removed successfully')"
        

        local ct_status
        ct_status=$(pct status "$container_id" | awk '{print $2}')
        
        if [[ "$ct_status" == "running" ]]; then
            echo -e ""
            if whiptail --yesno "$(translate "Container is running. Restart to apply changes?")" 8 60; then
                msg_info "$(translate 'Restarting container...')"
                if pct reboot "$container_id"; then
                    sleep 3
                    msg_ok "$(translate 'Container restarted successfully')"
                else
                    msg_warn "$(translate 'Failed to restart container - restart manually')"
                fi
            fi
        fi
        
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate 'Mount Point Removal Summary:')${CL}"
        echo -e "${TAB}${BGN}$(translate 'Container:')${CL} ${BL}$container_id${CL}"
        echo -e "${TAB}${BGN}$(translate 'Removed Mount:')${CL} ${BL}$selected_mp${CL}"
        echo -e "${TAB}${BGN}$(translate 'Host Path:')${CL} ${BL}$host_dir (preserved)${CL}"
        echo -e "${TAB}${BGN}$(translate 'Container Path:')${CL} ${BL}$container_path (unmounted)${CL}"
        
    else
        msg_error "$(translate 'Failed to remove mount point')"
    fi
    
    echo -e ""
    msg_success "$(translate 'Press Enter to continue...')"
    read -r
}





# ==========================================================
# MINIMAL CONTAINER SETUP (NO HOST MODIFICATIONS)
# ==========================================================

get_container_uid_shift() {
    local ctid="$1"
    local conf="/etc/pve/lxc/${ctid}.conf"

    if [[ ! -f "$conf" ]]; then
        echo "100000"   
        return 0
    fi

    local unpriv
    unpriv=$(grep "^unprivileged:" "$conf" | awk '{print $2}')

    if [[ "$unpriv" == "1" ]]; then
        local uid_shift=$(grep "^lxc.idmap" "$conf" | grep 'u 0' | awk '{print $5}' | head -1)
        echo "${uid_shift:-100000}"
        return 0
    fi

    echo "0"
    return 0
}






setup_minimal_container_access() {
    local ctid="$1" host_dir="$2" ct_mount_point="$3"
    local uid_shift container_type host_gid host_group mapped_gid
    
    
    host_gid=$(stat -c '%g' "$host_dir" 2>/dev/null)
    host_group=$(getent group "$host_gid" | cut -d: -f1 2>/dev/null)
    host_group=${host_group:-"root"}
    
    msg_ok "$(translate "Host directory info detected - preserving existing configuration")" >&2
    
    uid_shift=$(get_container_uid_shift "$ctid")

    if [[ "$uid_shift" -eq 0 ]]; then
        msg_ok "$(translate "PRIVILEGED container detected - using direct UID/GID mapping")" >&2
        mapped_gid="$host_gid"
        container_type="privileged"
    else
        msg_ok "$(translate "UNPRIVILEGED container detected - using mapped UID/GID")" >&2
        mapped_gid=$((uid_shift + host_gid))
        container_type="unprivileged"
        msg_ok "$(translate "UID shift:") $uid_shift, $(translate "Host GID:") $host_gid → $(translate "Container GID:") $mapped_gid" >&2
    fi

    msg_info "$(translate "Creating compatible group in container...")" >&2
    
    local container_group="shared_${host_gid}"
    
    pct exec "$ctid" -- groupadd -g "$mapped_gid" "$container_group" 2>/dev/null || true
    

    local users_added=0
    local user_list=""
    
    local temp_file="/tmp/users_$$.txt"
    pct exec "$ctid" -- awk -F: '$3 >= 25 && $3 < 65534 {print $1}' /etc/passwd > "$temp_file"
    
    if [[ -s "$temp_file" ]]; then
        while IFS= read -r username; do
            if [[ -n "$username" ]]; then
                if pct exec "$ctid" -- usermod -aG "$container_group" "$username" 2>/dev/null; then
                    users_added=$((users_added + 1))
                    user_list="$user_list $username"
                fi
            fi
        done < "$temp_file"
        
        if [[ $users_added -gt 0 ]]; then
            msg_ok "$(translate "Users added to group") $container_group: $users_added" >&2
        fi
    fi
    
    rm -f "$temp_file"

    if [[ "$container_type" == "unprivileged" ]]; then
        
        if ! command -v setfacl >/dev/null 2>&1; then
            apt-get update >/dev/null 2>&1
            apt-get install -y acl >/dev/null 2>&1
            msg_ok "$(translate "ACL tools installed")" >&2
        fi

        local acls_applied=0
        local acl_users=()
        

        while IFS=: read -r username _ ct_uid _; do
            if [[ $ct_uid -ge 25 && $ct_uid -lt 65534 ]]; then
                local host_uid=$((uid_shift + ct_uid))
                
                if setfacl -m u:$host_uid:rwx "$host_dir" 2>/dev/null && \
                   setfacl -m d:u:$host_uid:rwx "$host_dir" 2>/dev/null; then
                    acls_applied=$((acls_applied + 1))
                    acl_users+=("$username")
                fi
            fi
        done < <(pct exec "$ctid" -- cat /etc/passwd)
        
        if [[ $acls_applied -gt 0 ]]; then
            msg_ok "$(translate "ACL entries applied for") $acls_applied $(translate "users:") ${acl_users[*]}" >&2
        fi
    fi

    msg_info "$(translate "Configuring container mount point with setgid...")" >&2
    
    pct exec "$ctid" -- chgrp "$container_group" "$ct_mount_point" 2>/dev/null || true
    pct exec "$ctid" -- chmod 2775 "$ct_mount_point" 2>/dev/null || true

    msg_ok "$(translate "Container mount point configured with setgid")" >&2
    
    echo "$container_type|$host_group|$host_gid|$container_group|$mapped_gid"
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
        return 1
    fi
    
    if [[ -z "$ctid" || -z "$host_path" || -z "$ct_path" ]]; then
        return 1
    fi

    if pct config "$ctid" | grep -q "$host_path"; then
        msg_warn "$(translate "Mount already exists for this path")"
        return 1
    fi

    mpidx=$(get_next_mp_index "$ctid")
    
    result=$(pct set "$ctid" -mp${mpidx} "$host_path,mp=$ct_path,shared=1,backup=0,acl=1" 2>&1)

    if [[ $? -eq 0 ]]; then
        msg_ok "$(translate "Successfully mounted:") $host_path → $ct_path"
        return 0

    else
        msg_error "$(translate "Failed to add bind mount:") $result"
        return 1
    fi
}

# ==========================================================
# MAIN FUNCTION
# ==========================================================

mount_host_directory_minimal() {
    # Step 1: Select container
    local container_id
    container_id=$(select_lxc_container)
    if [[ $? -ne 0 || -z "$container_id" ]]; then
        return 1
    fi

    # Step 1.1: Ensure running
    ct_status=$(pct status "$container_id" | awk '{print $2}')
    if [[ "$ct_status" != "running" ]]; then
        show_proxmenux_logo
        msg_title "$(translate 'Mount Host Directory to LXC')"
        msg_info "$(translate "Starting container") $container_id..."
        if pct start "$container_id"; then
            sleep 3
            cleanup
        else
            msg_error "$(translate "Failed to start container")"
            echo -e ""
            msg_success "$(translate 'Press Enter to continue...')"
            read -r
            return 1
        fi
    fi


    # Step 2: Select host directory (unified menu)
    local host_dir
    host_dir=$(select_host_directory_unified)
    if [[ $? -ne 0 || -z "$host_dir" ]]; then
        return 1
    fi


    # Step 3: Select container mount point
    local ct_mount_point
    ct_mount_point=$(select_container_mount_point "$container_id" "$host_dir")
    if [[ $? -ne 0 || -z "$ct_mount_point" ]]; then
        return 1
    fi


    # Step 4: Get container info for confirmation
    local uid_shift container_type_display
    uid_shift=$(get_container_uid_shift "$container_id")
    if [[ "$uid_shift" -eq 0 ]]; then
        container_type_display="$(translate 'Privileged')"
    else
        container_type_display="$(translate 'Unprivileged')"
    fi


    # Step 4.1: Confirmation
    local confirm_msg="$(translate "Mount Configuration Summary:")

$(translate "Container ID"): $container_id ($container_type_display)
$(translate "Host Directory"): $host_dir
$(translate "Container Mount Point"): $ct_mount_point

$(translate "Notes:") 
- $(translate "The host directory will remain unchanged")
- $(translate "Basic permissions will be set inside the container")
- $(translate "ACL and setgid will be applied for group consistency")

$(translate "Proceed")?"

    if ! dialog --clear --title "$(translate "Confirm Mount point")" --yesno "$confirm_msg" 18 80; then
        return 1
    fi
    
    show_proxmenux_logo
    msg_title "$(translate 'Mount Host Directory to LXC')"

    msg_ok "$(translate 'Container selected:') $container_id"
    msg_ok "$(translate 'Container is running')"
    msg_ok "$(translate 'Host directory selected:') $host_dir"
    msg_ok "$(translate 'Container mount point selected:') $ct_mount_point"


    # Step 5: Add mount
    if ! add_bind_mount "$container_id" "$host_dir" "$ct_mount_point"; then
        echo -e ""
        msg_success "$(translate 'Press Enter to continue...')"
        read -r
        return 1
    fi
    
    # Step 6: Container setup
    local setup_info
    setup_info=$(setup_minimal_container_access "$container_id" "$host_dir" "$ct_mount_point")
    
    # Parse setup info
    IFS='|' read -r container_type host_group host_gid container_group mapped_gid fix_type <<< "$setup_info"
    
    msg_ok "$(translate "container configuration completed")"
    
    # Step 7: Summary
    echo -e ""
    echo -e "${TAB}${BOLD}$(translate 'Mount Added Successfully:')${CL}"
    echo -e "${TAB}${BGN}$(translate 'Container:')${CL} ${BL}$container_id ($container_type_display)${CL}"
    echo -e "${TAB}${BGN}$(translate 'Host Directory:')${CL} ${BL}$host_dir${CL}"
    echo -e "${TAB}${BGN}$(translate 'Mount Point:')${CL} ${BL}$ct_mount_point${CL}"
    echo -e "${TAB}${BGN}$(translate 'Action Taken:')${CL} ${BL}PRESERVE existing permissions${CL}"
    
    if [[ "$fix_type" == "cifs-fixed" ]]; then
        echo -e "${TAB}${BGN}$(translate 'Permission Strategy:')${CL} ${BL}CIFS compatibility fixes applied${CL}"
        echo -e "${TAB}${YW}$(translate 'WARNING:')${CL} ${BL}Storage CIFS de Proxmox puede ser solo LECTURA${CL}"
    else
        echo -e "${TAB}${BGN}$(translate 'Permission Strategy:')${CL} ${BL}$(if [[ "$container_type" == "unprivileged" ]]; then echo "ACL (mapped UIDs)"; else echo "Direct mapping"; fi)${CL}"
    fi

    # Step 8: Restart
    echo -e ""
    if whiptail --yesno "$(translate "Restart container to activate mount?")" 8 60; then
        msg_info "$(translate 'Restarting container...')"
        if pct reboot "$container_id"; then
            sleep 5
            msg_ok "$(translate 'Container restarted successfully')"
            
            echo -e ""
            echo -e "${TAB}${BOLD}$(translate 'Testing access and read/write:')${CL}"
            test_user=$(pct exec "$container_id" -- sh -c "id -u www-data >/dev/null 2>&1 && echo www-data || echo root")

            if pct exec "$container_id" -- su -s /bin/bash $test_user -c "touch $ct_mount_point/test_access.txt" 2>/dev/null; then
                msg_ok "$(translate "Mount access and read/write successful (tested as $test_user)")"
                rm -f "$host_dir/test_access.txt" 2>/dev/null || true
            else
                msg_warn "$(translate "⚠ Test read/write failed - may need additional configuration")"
                
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
            --menu "\n$(translate 'Choose an option:')" 25 85 15 \
            "1" "$(translate 'Mount point: Host Directory to LXC')" \
            "2" "$(translate 'View Mount Points')" \
            "3" "$(translate 'Remove Mount Point')" \
            "4" "$(translate 'Exit')" 3>&1 1>&2 2>&3)
        
        case $choice in
            1)
                mount_host_directory_minimal
                ;;
            2)
                view_mount_points
                ;;
            3)
                remove_mount_point
                ;;
            4|"")
                exit 0
                ;;
        esac
    done
}


main_menu
