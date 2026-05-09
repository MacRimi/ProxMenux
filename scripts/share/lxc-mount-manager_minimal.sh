#!/bin/bash
# ==========================================================
# ProxMenux - LXC Mount Manager
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Bind-mounts a host directory into an LXC container using
# Proxmox's native pct set -mpN syntax. Handles the permission
# quirks of unprivileged containers on the host side — never
# modifies anything inside the container.
#
# Features:
# - Unified host-directory picker (mounted CIFS/NFS shares,
#   fstab-inactive entries, /mnt/* local dirs, /mnt/pve/*
#   Proxmox storages, manual entry).
# - Active fix per source type:
#     - CIFS  → offer remount with uid=0,gid=0,file_mode=0777
#     - NFS   → offer chmod 1777 + setfacl on the share
#     - Local → offer chmod o+rwx + ACL (unprivileged only)
# - Auto-detects privileged vs unprivileged containers.
# - View / remove existing mp* entries.
# - Optional CT restart at end with mount-point smoke test.
# ==========================================================

BASE_DIR="/usr/local/share/proxmenux"
source "$BASE_DIR/utils.sh"

load_language
initialize_cache

# ==========================================================
# DIRECTORY DETECTION
# ==========================================================

detect_mounted_shares() {
    local mounted_shares=()

    while IFS= read -r line; do
        local device mount_point fs_type
        read -r device mount_point fs_type _ <<< "$line"

        local type=""
        case "$fs_type" in
            nfs|nfs4) type="NFS" ;;
            cifs)     type="CIFS/SMB" ;;
            *)        continue ;;
        esac

        # Skip internal Proxmox mounts
        local skip=false
        for internal in /mnt/pve/local /mnt/pve/local-lvm /mnt/pve/local-zfs \
                        /mnt/pve/backup /mnt/pve/dump /mnt/pve/images \
                        /mnt/pve/template /mnt/pve/snippets /mnt/pve/vztmpl; do
            if [[ "$mount_point" == "$internal" || "$mount_point" =~ ^${internal}/ ]]; then
                skip=true
                break
            fi
        done
        [[ "$skip" == true ]] && continue

        local size used
        local df_info
        df_info=$(df -h "$mount_point" 2>/dev/null | tail -n1)
        if [[ -n "$df_info" ]]; then
            size=$(echo "$df_info" | awk '{print $2}')
            used=$(echo "$df_info" | awk '{print $3}')
        else
            size="N/A"
            used="N/A"
        fi

        local source="Manual"
        [[ "$mount_point" =~ ^/mnt/pve/ ]] && source="Proxmox-Storage"

        mounted_shares+=("$mount_point|$device|$type|$size|$used|$source")
    done < /proc/mounts

    printf '%s\n' "${mounted_shares[@]}"
}

detect_fstab_network_mounts() {
    local fstab_mounts=()

    while IFS= read -r line; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// }" ]] && continue

        local source mount_point fs_type
        read -r source mount_point fs_type _ <<< "$line"

        local type=""
        case "$fs_type" in
            nfs|nfs4) type="NFS" ;;
            cifs)     type="CIFS/SMB" ;;
            *)        continue ;;
        esac

        [[ ! -d "$mount_point" ]] && continue

        # Skip if already mounted (already captured by detect_mounted_shares)
        local is_mounted=false
        while IFS= read -r proc_line; do
            local proc_mp proc_fs
            read -r _ proc_mp proc_fs _ <<< "$proc_line"
            if [[ "$proc_mp" == "$mount_point" && ("$proc_fs" == "nfs" || "$proc_fs" == "nfs4" || "$proc_fs" == "cifs") ]]; then
                is_mounted=true
                break
            fi
        done < /proc/mounts

        [[ "$is_mounted" == false ]] && fstab_mounts+=("$mount_point|$source|$type|0|0|fstab-inactive")
    done < /etc/fstab

    printf '%s\n' "${fstab_mounts[@]}"
}

detect_local_directories() {
    local local_dirs=()
    local network_mps=()

    # Collect network mount points to exclude
    while IFS='|' read -r mp _ _ _ _ _; do
        [[ -n "$mp" ]] && network_mps+=("$mp")
    done < <({ detect_mounted_shares; detect_fstab_network_mounts; })

    if [[ -d "/mnt" ]]; then
        for dir in /mnt/*/; do
            [[ ! -d "$dir" ]] && continue
            local dir_path="${dir%/}"
            [[ "$(basename "$dir_path")" == "pve" ]] && continue

            local is_network=false
            for nmp in "${network_mps[@]}"; do
                [[ "$dir_path" == "$nmp" ]] && is_network=true && break
            done
            [[ "$is_network" == true ]] && continue

            local dir_size
            dir_size=$(du -sh "$dir_path" 2>/dev/null | awk '{print $1}')
            local_dirs+=("$dir_path|Local|Directory|$dir_size|-|Manual")
        done
    fi

    printf '%s\n' "${local_dirs[@]}"
}

# ==========================================================
# HOST DIRECTORY SELECTION
# ==========================================================

detect_problematic_storage() {
    local dir="$1"
    local check_source="$2"
    local check_type="$3"

    while IFS='|' read -r mp _ type _ _ source; do
        if [[ "$mp" == "$dir" && "$source" == "$check_source" && "$type" == "$check_type" ]]; then
            return 0
        fi
    done < <(detect_mounted_shares)
    return 1
}

select_host_directory_unified() {
    local mounted_shares fstab_mounts local_dirs
    mounted_shares=$(detect_mounted_shares)
    fstab_mounts=$(detect_fstab_network_mounts)
    local_dirs=$(detect_local_directories)

    # Deduplicate and build option list
    local all_entries=()
    declare -A seen_paths

    # Process network shares (mounted + fstab)
    while IFS='|' read -r mp device type size used source; do
        [[ -z "$mp" ]] && continue
        [[ -n "${seen_paths[$mp]}" ]] && continue
        seen_paths["$mp"]=1

        local prefix=""
        case "$source" in
            "Proxmox-Storage") prefix="PVE-" ;;
            "fstab-inactive")  prefix="fstab(off)-" ;;
            *)                 prefix="" ;;
        esac

        local info="${prefix}${type}"
        [[ "$size" != "N/A" && "$size" != "0" ]] && info="${info} [${used}/${size}]"
        all_entries+=("$mp" "$info")
    done < <(echo "$mounted_shares"; echo "$fstab_mounts")

    # Process local directories
    while IFS='|' read -r mp _ type size _ _; do
        [[ -z "$mp" ]] && continue
        [[ -n "${seen_paths[$mp]}" ]] && continue
        seen_paths["$mp"]=1
        local info="Local"
        [[ -n "$size" && "$size" != "0" ]] && info="Local [${size}]"
        all_entries+=("$mp" "$info")
    done < <(echo "$local_dirs")

    # Add Proxmox storage paths (/mnt/pve/*)
    if [[ -d "/mnt/pve" ]]; then
        for dir in /mnt/pve/*/; do
            [[ ! -d "$dir" ]] && continue
            local dir_path="${dir%/}"
            [[ -n "${seen_paths[$dir_path]}" ]] && continue
            seen_paths["$dir_path"]=1
            all_entries+=("$dir_path" "Proxmox-Storage")
        done
    fi

    all_entries+=("MANUAL" "$(translate "Enter path manually")")

    local result
    result=$(dialog --clear --colors --title "$(translate "Select Host Directory")" \
        --menu "\n$(translate "Select the directory to bind to container:")" 25 85 15 \
        "${all_entries[@]}" 3>&1 1>&2 2>&3)

    local dialog_exit=$?
    [[ $dialog_exit -ne 0 ]] && return 1
    [[ -z "$result" || "$result" =~ ^━ ]] && return 1

    if [[ "$result" == "MANUAL" ]]; then
        result=$(whiptail --title "$(translate "Manual Path Entry")" \
            --inputbox "$(translate "Enter the full path to the host directory:")" \
            10 70 "/mnt/" 3>&1 1>&2 2>&3)
        [[ $? -ne 0 ]] && return 1
    fi

    [[ -z "$result" ]] && return 1

    if [[ ! -d "$result" ]]; then
        whiptail --title "$(translate "Invalid Path")" \
            --msgbox "$(translate "The selected path is not a valid directory:") $result" 8 70
        return 1
    fi

    # Store the storage type as a global so the main flow can act on it later.
    # We don't block the user here — the active fix happens after we know the container type.
    LMM_HOST_DIR_TYPE="local"
    if detect_problematic_storage "$result" "Proxmox-Storage" "CIFS/SMB"; then
        LMM_HOST_DIR_TYPE="cifs"
    elif detect_problematic_storage "$result" "Proxmox-Storage" "NFS"; then
        LMM_HOST_DIR_TYPE="nfs"
    fi

    echo "$result"
    return 0
}

# ==========================================================
# CONTAINER SELECTION
# ==========================================================

select_lxc_container() {
    local ct_list
    ct_list=$(pct list 2>/dev/null | awk 'NR>1 {print $1, $2, $3}')
    if [[ -z "$ct_list" ]]; then
        whiptail --title "Error" --msgbox "$(translate "No LXC containers available")" 8 50
        return 1
    fi

    local options=()
    while read -r id name status; do
        [[ -n "$id" && "$id" =~ ^[0-9]+$ ]] && options+=("$id" "${name:-unnamed} ($status)")
    done <<< "$ct_list"

    if [[ ${#options[@]} -eq 0 ]]; then
        dialog --title "Error" --msgbox "$(translate "No valid containers found")" 8 50
        return 1
    fi

    local ctid
    ctid=$(dialog --title "$(translate "Select LXC Container")" \
        --menu "$(translate "Select container:")" 25 85 15 \
        "${options[@]}" 3>&1 1>&2 2>&3)

    [[ $? -ne 0 || -z "$ctid" ]] && return 1
    echo "$ctid"
    return 0
}

select_container_mount_point() {
    local ctid="$1"
    local host_dir="$2"
    local base_name
    base_name=$(basename "$host_dir")

    while true; do
        local choice
        choice=$(dialog --clear --title "$(translate "Configure Mount Point inside LXC")" \
            --menu "\n$(translate "Where to mount inside container?")" 16 70 3 \
            "1" "$(translate "Create new directory in /mnt")" \
            "2" "$(translate "Enter path manually")" \
            "3" "$(translate "Cancel")" 3>&1 1>&2 2>&3)
        [[ $? -ne 0 ]] && return 1

        local mount_point
        case "$choice" in
            1)
                mount_point=$(whiptail --inputbox "$(translate "Enter folder name for /mnt:")" \
                    10 60 "$base_name" 3>&1 1>&2 2>&3)
                [[ $? -ne 0 || -z "$mount_point" ]] && continue
                mount_point="/mnt/$mount_point"
                ;;
            2)
                mount_point=$(whiptail --inputbox "$(translate "Enter full path:")" \
                    10 70 "/mnt/$base_name" 3>&1 1>&2 2>&3)
                [[ $? -ne 0 || -z "$mount_point" ]] && continue
                ;;
            3) return 1 ;;
        esac

        # Validate path format
        if [[ ! "$mount_point" =~ ^/ ]]; then
            whiptail --msgbox "$(translate "Path must be absolute (start with /)")" 8 60
            continue
        fi

        # Check if path is already used as a mount point in this CT
        if pct config "$ctid" 2>/dev/null | grep -qE "mp=${mount_point}(,|$)"; then
            whiptail --msgbox "$(translate "This path is already used as a mount point in this container.")" 8 70
            continue
        fi

        # Create directory inside CT (only if CT is running)
        local ct_status
        ct_status=$(pct status "$ctid" 2>/dev/null | awk '{print $2}')
        if [[ "$ct_status" == "running" ]]; then
            pct exec "$ctid" -- mkdir -p "$mount_point" 2>/dev/null
        fi

        echo "$mount_point"
        return 0
    done
}

# ==========================================================
# MOUNT MANAGEMENT
# ==========================================================

get_next_mp_index() {
    local ctid="$1"
    local conf="/etc/pve/lxc/${ctid}.conf"

    if [[ ! "$ctid" =~ ^[0-9]+$ ]] || [[ ! -f "$conf" ]]; then
        echo "0"
        return 0
    fi

    local next=0
    local used
    used=$(awk -F: '/^mp[0-9]+:/ {print $1}' "$conf" | sed 's/mp//' | sort -n)
    for idx in $used; do
        [[ "$idx" -ge "$next" ]] && next=$((idx + 1))
    done
    echo "$next"
}

add_bind_mount() {
    local ctid="$1"
    local host_path="$2"
    local ct_path="$3"

    if [[ ! "$ctid" =~ ^[0-9]+$ || -z "$host_path" || -z "$ct_path" ]]; then
        msg_error "$(translate "Invalid parameters for bind mount")"
        return 1
    fi

    # Check if this host path is already mounted in this CT
    if pct config "$ctid" 2>/dev/null | grep -qF " ${host_path},"; then
        msg_warn "$(translate "Mount already exists for this path in container") $ctid"
        return 1
    fi

    local mpidx
    mpidx=$(get_next_mp_index "$ctid")

    local result
    result=$(pct set "$ctid" -mp${mpidx} "$host_path,mp=$ct_path,shared=1,backup=0" 2>&1)

    if [[ $? -eq 0 ]]; then
        msg_ok "$(translate "Bind mount added:") $host_path → $ct_path (mp${mpidx})"
        return 0
    else
        msg_error "$(translate "Failed to add bind mount:") $result"
        return 1
    fi
}

# ==========================================================
# VIEW / REMOVE
# ==========================================================

view_mount_points() {
    show_proxmenux_logo
    msg_title "$(translate "Current LXC Mount Points")"

    local ct_list
    ct_list=$(pct list 2>/dev/null | awk 'NR>1 {print $1, $2, $3}')
    if [[ -z "$ct_list" ]]; then
        msg_warn "$(translate "No LXC containers found")"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi

    local found_mounts=false

    while read -r id name status; do
        [[ -z "$id" || ! "$id" =~ ^[0-9]+$ ]] && continue
        local conf="/etc/pve/lxc/${id}.conf"
        [[ ! -f "$conf" ]] && continue

        local mounts
        mounts=$(grep "^mp[0-9]*:" "$conf" 2>/dev/null)
        [[ -z "$mounts" ]] && continue

        found_mounts=true
        echo -e "${TAB}${BOLD}$(translate "Container") $id: $name ($status)${CL}"

        while IFS= read -r mount_line; do
            [[ -z "$mount_line" ]] && continue
            local mp_id mount_info host_path container_path options
            mp_id=$(echo "$mount_line" | cut -d: -f1)
            mount_info=$(echo "$mount_line" | cut -d: -f2-)
            host_path=$(echo "$mount_info" | cut -d, -f1)
            container_path=$(echo "$mount_info" | grep -o 'mp=[^,]*' | cut -d= -f2)
            options=$(echo "$mount_info" | sed 's/^[^,]*,mp=[^,]*,*//')

            echo -e "${TAB}  ${BGN}$mp_id:${CL} ${BL}$host_path${CL} → ${BL}$container_path${CL}"
            [[ -n "$options" ]] && echo -e "${TAB}    ${DGN}$options${CL}"
        done <<< "$mounts"
        echo ""
    done <<< "$ct_list"

    if [[ "$found_mounts" == false ]]; then
        msg_ok "$(translate "No mount points found in any container")"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

remove_mount_point() {
    show_proxmenux_logo
    msg_title "$(translate "Remove LXC Mount Point")"

    local container_id
    container_id=$(select_lxc_container)
    [[ $? -ne 0 || -z "$container_id" ]] && return 1

    local conf="/etc/pve/lxc/${container_id}.conf"
    if [[ ! -f "$conf" ]]; then
        msg_error "$(translate "Container configuration not found")"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi

    local mounts
    mounts=$(grep "^mp[0-9]*:" "$conf" 2>/dev/null)
    if [[ -z "$mounts" ]]; then
        show_proxmenux_logo
        msg_title "$(translate "Remove LXC Mount Point")"
        msg_warn "$(translate "No mount points found in container") $container_id"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi

    local options=()
    while IFS= read -r mount_line; do
        [[ -z "$mount_line" ]] && continue
        local mp_id mount_info host_path container_path
        mp_id=$(echo "$mount_line" | cut -d: -f1)
        mount_info=$(echo "$mount_line" | cut -d: -f2-)
        host_path=$(echo "$mount_info" | cut -d, -f1)
        container_path=$(echo "$mount_info" | grep -o 'mp=[^,]*' | cut -d= -f2)
        options+=("$mp_id" "$host_path → $container_path")
    done <<< "$mounts"

    if [[ ${#options[@]} -eq 0 ]]; then
        show_proxmenux_logo
        msg_title "$(translate "Remove LXC Mount Point")"
        msg_warn "$(translate "No valid mount points found")"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi

    local selected_mp
    selected_mp=$(dialog --clear --title "$(translate "Select Mount Point to Remove")" \
        --menu "\n$(translate "Select mount point to remove from container") $container_id:" 20 80 10 \
        "${options[@]}" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 || -z "$selected_mp" ]] && return 1

    local selected_mount_line mount_info host_path container_path
    selected_mount_line=$(grep "^${selected_mp}:" "$conf")
    mount_info=$(echo "$selected_mount_line" | cut -d: -f2-)
    host_path=$(echo "$mount_info" | cut -d, -f1)
    container_path=$(echo "$mount_info" | grep -o 'mp=[^,]*' | cut -d= -f2)

    local confirm_msg
    confirm_msg="$(translate "Remove Mount Point Confirmation:")

$(translate "Container ID"): $container_id
$(translate "Mount Point ID"): $selected_mp
$(translate "Host Path"): $host_path
$(translate "Container Path"): $container_path

$(translate "NOTE: The host directory and its contents will remain unchanged.")

$(translate "Proceed with removal")?"

    if ! dialog --clear --title "$(translate "Confirm Mount Point Removal")" --yesno "$confirm_msg" 18 80; then
        return 1
    fi

    show_proxmenux_logo
    msg_title "$(translate "Remove LXC Mount Point")"
    msg_info "$(translate "Removing mount point") $selected_mp $(translate "from container") $container_id..."

    if pct set "$container_id" --delete "$selected_mp" 2>/dev/null; then
        msg_ok "$(translate "Mount point removed successfully")"

        local ct_status
        ct_status=$(pct status "$container_id" | awk '{print $2}')
        if [[ "$ct_status" == "running" ]]; then
            echo ""
            if whiptail --yesno "$(translate "Container is running. Restart to apply changes?")" 8 60; then
                msg_info "$(translate "Restarting container...")"
                if pct reboot "$container_id"; then
                    sleep 3
                    msg_ok "$(translate "Container restarted successfully")"
                else
                    msg_warn "$(translate "Failed to restart container — restart manually")"
                fi
            fi
        fi

        echo ""
        echo -e "${TAB}${BOLD}$(translate "Mount Point Removal Summary:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Container:")${CL} ${BL}$container_id${CL}"
        echo -e "${TAB}${BGN}$(translate "Removed Mount:")${CL} ${BL}$selected_mp${CL}"
        echo -e "${TAB}${BGN}$(translate "Host Path:")${CL} ${BL}$host_path (preserved)${CL}"
        echo -e "${TAB}${BGN}$(translate "Container Path:")${CL} ${BL}$container_path (unmounted)${CL}"
    else
        msg_error "$(translate "Failed to remove mount point")"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

# ==========================================================
# ACTIVE FIXES FOR NETWORK STORAGE (CIFS / NFS)
# These functions act on problems instead of just warning about them.
# ==========================================================

lmm_fix_cifs_access() {
    local host_dir="$1"
    local is_unprivileged="$2"

    # CIFS mounted by Proxmox GUI uses uid=0/gid=0 by default (root only).
    # The fix: remount with uid/gid that the LXC can access.
    # We detect the current mount options and propose a corrected remount.

    local mount_src mount_opts
    mount_src=$(findmnt -n -o SOURCE --target "$host_dir" 2>/dev/null)
    mount_opts=$(findmnt -n -o OPTIONS --target "$host_dir" 2>/dev/null)

    if [[ -z "$mount_src" ]]; then
        dialog --backtitle "ProxMenux" \
            --title "$(translate "CIFS Mount Not Found")" \
            --msgbox "$(translate "Could not detect the CIFS mount for this directory. Try accessing it manually.")" 8 70
        return 0
    fi

    # Determine which uid/gid to use
    local target_uid target_gid
    if [[ "$is_unprivileged" == "1" ]]; then
        # Unprivileged LXC: container root (UID 0) maps to host UID 100000.
        # Use file_mode/dir_mode 0777 + uid=0/gid=0 — CIFS maps them to everyone.
        target_uid=0
        target_gid=0
    else
        target_uid=0
        target_gid=0
    fi

    # Build new options: strip existing uid/gid/file_mode/dir_mode, add ours
    local new_opts
    new_opts=$(echo "$mount_opts" | sed -E \
        's/(^|,)(uid|gid|file_mode|dir_mode)=[^,]*//g' | \
        sed 's/^,//')
    new_opts="${new_opts},uid=${target_uid},gid=${target_gid},file_mode=0777,dir_mode=0777"
    new_opts="${new_opts/#,/}"

    if dialog --backtitle "ProxMenux" \
        --title "$(translate "Fix CIFS Permissions")" \
        --yesno \
"$(translate "This CIFS share is mounted with restrictive permissions.")\n\n\
$(translate "ProxMenux can remount it with open permissions so any LXC can read and write.")\n\n\
$(translate "Current mount options:")\n${mount_opts}\n\n\
$(translate "New mount options to apply:")\n${new_opts}\n\n\
$(translate "Apply fix now? (The share will be briefly remounted)")" \
        18 84 3>&1 1>&2 2>&3; then

        msg_info "$(translate "Remounting CIFS share with open permissions...")"
        if umount "$host_dir" 2>/dev/null && \
           mount -t cifs "$mount_src" "$host_dir" -o "$new_opts" 2>/dev/null; then
            msg_ok "$(translate "CIFS share remounted — LXC containers can now read and write")"

            # Update fstab if the mount is there
            if grep -qF "$host_dir" /etc/fstab 2>/dev/null; then
                sed -i "s|^\(${mount_src}[[:space:]].*${host_dir}.*cifs[[:space:]]\).*|\1${new_opts} 0 0|" /etc/fstab 2>/dev/null || true
                msg_ok "$(translate "/etc/fstab updated — permissions will persist after reboot")"
            fi
        else
            msg_warn "$(translate "Could not remount automatically. Try manually or check credentials.")"
        fi
    fi
}

lmm_fix_nfs_access() {
    local host_dir="$1"
    local is_unprivileged="$2"
    local uid_shift="${3:-100000}"

    # NFS: the host cannot override server-side permissions.
    # BUT: if the server exports with root_squash (default), we can check
    # if no_root_squash or all_squash is possible, and guide the user.
    # What we CAN do on the host: apply a sticky+open directory as a cache layer
    # if the NFS mount allows it.

    local mount_src mount_opts
    mount_src=$(findmnt -n -o SOURCE --target "$host_dir" 2>/dev/null)
    mount_opts=$(findmnt -n -o OPTIONS --target "$host_dir" 2>/dev/null)

    # Try to detect if we can write to the NFS share as root
    local can_write=false
    local testfile="${host_dir}/.proxmenux_write_test_$$"
    if touch "$testfile" 2>/dev/null; then
        rm -f "$testfile" 2>/dev/null
        can_write=true
    fi

    local server_hint=""
    if [[ -n "$mount_src" ]]; then
        server_hint="${mount_src%%:*}"
    fi

    if [[ "$can_write" == "true" && "$is_unprivileged" == "1" ]]; then
        # Root on host CAN write to NFS, but unprivileged LXC UIDs (100000+)
        # will be squashed by the NFS server. We can set a world-writable sticky
        # dir on the share itself so the container can write to it.
        if dialog --backtitle "ProxMenux" \
            --title "$(translate "Fix NFS Access for Unprivileged LXC")" \
            --yesno \
"$(translate "NFS server export is writable from the host, but unprivileged LXC containers use mapped UIDs (${uid_shift}+) which the NFS server will squash.")\n\n\
$(translate "ProxMenux can apply open permissions on this NFS directory from the host so the container can read and write:")\n\n\
$(translate "  chmod 1777 + setfacl o::rwx (applied on the NFS share from this host)")\n\n\
$(translate "Note: this only works if the NFS server does NOT use 'all_squash' for root.")\n\
$(translate "If it still fails, the NFS server export options must be changed on the server.")\n\n\
$(translate "Apply fix now?")" \
            18 84 3>&1 1>&2 2>&3; then

            if chmod 1777 "$host_dir" 2>/dev/null; then
                msg_ok "$(translate "NFS directory permissions set — containers should now be able to write")"
            else
                msg_warn "$(translate "chmod failed — NFS server may be restricting changes from root")"
            fi

            if command -v setfacl >/dev/null 2>&1; then
                setfacl -m o::rwx "$host_dir" 2>/dev/null || true
                setfacl -m d:o::rwx "$host_dir" 2>/dev/null || true
            fi
        fi

    elif [[ "$can_write" == "false" ]]; then
        # Even root cannot write — NFS server is fully restrictive
        local server_msg=""
        [[ -n "$server_hint" ]] && server_msg="\n$(translate "NFS server:"): ${server_hint}"

        dialog --backtitle "ProxMenux" \
            --title "$(translate "NFS Access Restricted")" \
            --msgbox \
"$(translate "This NFS share is fully restricted — even the host root cannot write to it.")\n\
${server_msg}\n\n\
$(translate "ProxMenux cannot override NFS server-side permissions from the host.")\n\n\
$(translate "To allow LXC write access, change the NFS export on the server to include:")\n\n\
$(translate "  no_root_squash")     $(translate "(if only privileged LXCs need write access)")\n\
$(translate "  all_squash,anonuid=65534,anongid=65534")  $(translate "(for unprivileged LXCs)")\n\n\
$(translate "You can still mount this share for READ-ONLY access.")" \
            20 84 3>&1 1>&2 2>&3
    fi
}

# ==========================================================
# HOST PERMISSION CHECK (host-side only, never touches the container)
# ==========================================================

lmm_offer_host_permissions() {
    local host_dir="$1"
    local is_unprivileged="$2"

    # Privileged containers: UID 0 inside = UID 0 on host — always accessible
    [[ "$is_unprivileged" != "1" ]] && return 0

    # Check if 'others' already have r+x (minimum to traverse and read)
    local stat_perms others_bits
    stat_perms=$(stat -c "%a" "$host_dir" 2>/dev/null) || return 0
    others_bits=$(( 8#${stat_perms} & 7 ))

    # Check ACLs first if available (takes precedence over mode bits)
    if command -v getfacl >/dev/null 2>&1; then
        if getfacl -p "$host_dir" 2>/dev/null | grep -q "^other::.*r.*x"; then
            return 0  # ACL already grants others r+x or better
        fi
    fi

    # 5 = r-x (bits: r=4, x=1). If already r+x or rwx we're fine.
    (( (others_bits & 5) == 5 )) && return 0

    # Permissions are insufficient — offer to fix HOST directory only
    local current_perms
    current_perms=$(stat -c "%A" "$host_dir" 2>/dev/null)

    if dialog --backtitle "ProxMenux" \
        --title "$(translate "Unprivileged Container Access")" \
        --yesno \
"$(translate "The host directory may not be accessible from an unprivileged container.")\n\n\
$(translate "Unprivileged containers map their UIDs to high host UIDs (e.g. 100000+), which appear as 'others' on the host filesystem.")\n\n\
$(translate "Current permissions:"): ${current_perms}\n\n\
$(translate "Apply read+write access for 'others' on the host directory?")\n\n\
$(translate "(Only the host directory is modified. Nothing inside the container is changed.")" \
        16 80 3>&1 1>&2 2>&3; then

        chmod o+rwx "$host_dir" 2>/dev/null || true
        if command -v setfacl >/dev/null 2>&1; then
            setfacl -m o::rwx "$host_dir" 2>/dev/null || true
            setfacl -m d:o::rwx "$host_dir" 2>/dev/null || true
        fi
        msg_ok "$(translate "Host directory permissions updated — unprivileged containers can now access it")"
    fi
}

# ==========================================================
# MAIN FUNCTION — ADD MOUNT
# ==========================================================

mount_host_directory_minimal() {
    # Step 1: Select container
    local container_id
    container_id=$(select_lxc_container)
    [[ $? -ne 0 || -z "$container_id" ]] && return 1

    # Step 2: Select host directory
    local host_dir
    host_dir=$(select_host_directory_unified)
    [[ $? -ne 0 || -z "$host_dir" ]] && return 1

    # Step 3: Select container mount point
    local ct_mount_point
    ct_mount_point=$(select_container_mount_point "$container_id" "$host_dir")
    [[ $? -ne 0 || -z "$ct_mount_point" ]] && return 1

    # Step 4: Get container type info (for display only)
    local uid_shift container_type_display
    uid_shift=$(awk '/^lxc.idmap.*u 0/ {print $5}' "/etc/pve/lxc/${container_id}.conf" 2>/dev/null | head -1)
    local is_unprivileged
    is_unprivileged=$(grep "^unprivileged:" "/etc/pve/lxc/${container_id}.conf" 2>/dev/null | awk '{print $2}')
    if [[ "$is_unprivileged" == "1" ]]; then
        container_type_display="$(translate "Unprivileged")"
        uid_shift="${uid_shift:-100000}"
    else
        container_type_display="$(translate "Privileged")"
        uid_shift="0"
    fi

    # Step 5: Active fix for network storage (before confirmation, while we know container type)
    case "${LMM_HOST_DIR_TYPE:-local}" in
        cifs) lmm_fix_cifs_access "$host_dir" "$is_unprivileged" ;;
        nfs)  lmm_fix_nfs_access  "$host_dir" "$is_unprivileged" "$uid_shift" ;;
    esac

    # Step 6: Confirmation
    local confirm_msg
    confirm_msg="$(translate "Mount Configuration Summary:")

$(translate "Container ID"): $container_id ($container_type_display)
$(translate "Host Directory"): $host_dir
$(translate "Container Mount Point"): $ct_mount_point

$(translate "IMPORTANT NOTES:")
- $(translate "Nothing inside the container is modified")
- $(if [[ "$is_unprivileged" == "1" ]]; then
    translate "Host directory access for unprivileged containers has been prepared above"
  else
    translate "Privileged container — host root maps directly, no permission changes needed"
  fi)

$(translate "Proceed")?"

    if ! dialog --clear --title "$(translate "Confirm Mount")" --yesno "$confirm_msg" 22 80; then
        return 1
    fi

    show_proxmenux_logo
    msg_title "$(translate "Mount Host Directory to LXC")"
    msg_ok "$(translate "Container:") $container_id ($container_type_display)"
    msg_ok "$(translate "Host directory:") $host_dir"
    msg_ok "$(translate "Container mount point:") $ct_mount_point"

    # Step 7: Add bind mount
    if ! add_bind_mount "$container_id" "$host_dir" "$ct_mount_point"; then
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi

    # Step 8: Host permission check for local dirs (only if not already handled above for CIFS/NFS)
    if [[ "${LMM_HOST_DIR_TYPE:-local}" == "local" ]]; then
        lmm_offer_host_permissions "$host_dir" "$is_unprivileged"
    fi

    # Step 9: Summary
    echo ""
    echo -e "${TAB}${BOLD}$(translate "Mount Added Successfully:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Container:")${CL} ${BL}$container_id${CL}"
    echo -e "${TAB}${BGN}$(translate "Host Directory:")${CL} ${BL}$host_dir${CL}"
    echo -e "${TAB}${BGN}$(translate "Mount Point:")${CL} ${BL}$ct_mount_point${CL}"
    if [[ "$is_unprivileged" == "1" ]]; then
        echo -e "${TAB}${YW}$(translate "Unprivileged container — UID offset:") ${uid_shift}${CL}"
    else
        echo -e "${TAB}${DGN}$(translate "Privileged container — direct root access")${CL}"
    fi
    echo ""

    # Step 10: Offer restart
    echo ""
    if whiptail --yesno "$(translate "Restart container to activate mount?")" 8 60; then
        msg_info "$(translate "Restarting container...")"
        if pct reboot "$container_id"; then
            sleep 5
            msg_ok "$(translate "Container restarted successfully")"

            # Quick access test (read-only, no files written)
            local ct_status
            ct_status=$(pct status "$container_id" 2>/dev/null | awk '{print $2}')
            if [[ "$ct_status" == "running" ]]; then
                echo ""
                if pct exec "$container_id" -- test -d "$ct_mount_point" 2>/dev/null; then
                    msg_ok "$(translate "Mount point is accessible inside container")"
                else
                    msg_warn "$(translate "Mount point not yet accessible — may need manual permission adjustment")"
                fi
            fi
        else
            msg_warn "$(translate "Failed to restart — restart manually to activate mount")"
        fi
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

# ==========================================================
# MAIN MENU
# ==========================================================

main_menu() {
    while true; do
        local choice
        choice=$(dialog --title "$(translate "LXC Mount Manager")" \
            --menu "\n$(translate "Choose an option:")" 18 80 5 \
            "1" "$(translate "Add: Mount Host Directory into LXC")" \
            "2" "$(translate "View Mount Points")" \
            "3" "$(translate "Remove Mount Point")" \
            "4" "$(translate "Exit")" 3>&1 1>&2 2>&3)

        case $choice in
            1) mount_host_directory_minimal ;;
            2) view_mount_points ;;
            3) remove_mount_point ;;
            4|"") exit 0 ;;
        esac
    done
}

main_menu
