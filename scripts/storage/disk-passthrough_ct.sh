#!/bin/bash
# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.2
# Last Updated: 30/07/2025
# ==========================================================
# Description:
# This script allows users to assign physical disks to existing
# Proxmox containers (CTs) through an interactive menu.
# - Detects the system disk and excludes it from selection.
# - Lists all available CTs for the user to choose from.
# - Identifies and displays unassigned physical disks.
# - Allows the user to select multiple disks and attach them to a CT.
# - Configures the selected disks for the CT and verifies the assignment.
# - Uses persistent device paths to avoid issues with device order changes.
# ==========================================================

# Configuration ============================================
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# Get OS codename for repository configuration
OS_CODENAME="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs )"

# ==========================================================

# Function to get persistent device path
get_persistent_path() {
    local device="$1"
    local persistent_path=""
    
    # Try by-id first (most reliable)
    for path in /dev/disk/by-id/*; do
        if [[ -e "$path" && "$(readlink -f "$path")" == "$device" ]]; then
            # Prefer ata- or scsi- over wwn- for readability
            if [[ "$path" =~ ata-|scsi- ]]; then
                echo "$path"
                return 0
            elif [[ -z "$persistent_path" ]]; then
                persistent_path="$path"
            fi
        fi
    done
    
    # Return the first found by-id path if any
    if [[ -n "$persistent_path" ]]; then
        echo "$persistent_path"
        return 0
    fi
    
    # Try by-path as fallback
    for path in /dev/disk/by-path/*; do
        if [[ -e "$path" && "$(readlink -f "$path")" == "$device" ]]; then
            echo "$path"
            return 0
        fi
    done
    
    # Fallback to original device if no persistent path found
    msg_warn "$(translate "No persistent path found for") $device, $(translate "using direct path")"
    echo "$device"
}

# Function to ensure repositories are properly configured
ensure_repositories() {
    local sources_file="/etc/apt/sources.list"
    local need_update=false
    
    # Only verify the main repository with contrib and non-free
    if ! grep -q "deb.*${OS_CODENAME}.*main" "$sources_file"; then
        echo "deb http://deb.debian.org/debian ${OS_CODENAME} main contrib non-free non-free-firmware" >> "$sources_file"
        need_update=true
    fi
    
    if [ "$need_update" = true ]; then
        apt update >/dev/null 2>&1
    fi
    
    return 0
}

get_disk_info() {
    local disk=$1
    MODEL=$(lsblk -dn -o MODEL "$disk" | xargs)
    SIZE=$(lsblk -dn -o SIZE "$disk" | xargs)
    echo "$MODEL" "$SIZE"
}

# Ensure repositories are configured
ensure_repositories

CT_LIST=$(pct list | awk 'NR>1 {print $1, $3}')
if [ -z "$CT_LIST" ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No CTs available in the system.")" 8 40
    exit 1
fi

CTID=$(whiptail --title "$(translate "Select CT for destination disk")" --menu "$(translate "Select the CT to which you want to add disks:")" 15 60 8 $CT_LIST 3>&1 1>&2 2>&3)

if [ -z "$CTID" ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No CT was selected.")" 8 40
    exit 1
fi

CTID=$(echo "$CTID" | tr -d '"')

clear
show_proxmenux_logo
echo -e
msg_title "$(translate "Add Disk") Passthrough $(translate "to a LXC")"
echo -e
msg_ok "$(translate "CT selected successfully.")"

CT_STATUS=$(pct status "$CTID" | awk '{print $2}')
if [ "$CT_STATUS" != "running" ]; then
    msg_info "$(translate "Starting CT") $CTID..."
    pct start "$CTID"
    sleep 2
    if [ "$(pct status "$CTID" | awk '{print $2}')" != "running" ]; then
        msg_error "$(translate "Failed to start the CT.")"
        sleep 2
        exit 1
    fi
    msg_ok "$(translate "CT started successfully.")"
fi

CONF_FILE="/etc/pve/lxc/$CTID.conf"
if grep -q '^unprivileged: 1' "$CONF_FILE"; then
    if whiptail --title "$(translate "Privileged Container")" \
        --yesno "$(translate "The selected container is unprivileged. A privileged container is required for direct device passthrough.")\\n\\n$(translate "Do you want to convert it to a privileged container now?")" 12 70; then
        
        msg_info "$(translate "Stopping container") $CTID..."
        pct shutdown "$CTID" &>/dev/null
        for i in {1..10}; do
            sleep 1
            if [ "$(pct status "$CTID" | awk '{print $2}')" != "running" ]; then
                break
            fi
        done
        
        if [ "$(pct status "$CTID" | awk '{print $2}')" == "running" ]; then
            msg_error "$(translate "Failed to stop the container.")"
            exit 1
        fi
        msg_ok "$(translate "Container stopped.")"
        
        cp "$CONF_FILE" "$CONF_FILE.bak"
        sed -i '/^unprivileged: 1/d' "$CONF_FILE"
        echo "unprivileged: 0" >> "$CONF_FILE"
        msg_ok "$(translate "Container successfully converted to privileged.")"
        
        msg_info "$(translate "Starting container") $CTID..."
        pct start "$CTID" &>/dev/null
        sleep 2
        if [ "$(pct status "$CTID" | awk '{print $2}')" != "running" ]; then
            msg_error "$(translate "Failed to start the container.")"
            exit 1
        fi
        msg_ok "$(translate "Container started successfully.")"
    else
        whiptail --title "$(translate "Aborted")" \
            --msgbox "$(translate "Operation cancelled. Cannot continue with an unprivileged container.")" 10 60
        exit 1
    fi
fi

##########################################
msg_info "$(translate "Detecting available disks...")"

USED_DISKS=$(lsblk -n -o PKNAME,TYPE | grep 'lvm' | awk '{print "/dev/" $1}')
MOUNTED_DISKS=$(lsblk -ln -o NAME,MOUNTPOINT | awk '$2!="" {print "/dev/" $1}')

ZFS_DISKS=""
ZFS_RAW=$(zpool list -v -H 2>/dev/null | awk '{print $1}' | grep -v '^NAME$' | grep -v '^-' | grep -v '^mirror')
for entry in $ZFS_RAW; do
    path=""
    if [[ "$entry" == wwn-* || "$entry" == ata-* ]]; then
        if [ -e "/dev/disk/by-id/$entry" ]; then
            path=$(readlink -f "/dev/disk/by-id/$entry")
        fi
    elif [[ "$entry" == /dev/* ]]; then
        path="$entry"
    fi
    
    if [ -n "$path" ]; then
        base_disk=$(lsblk -no PKNAME "$path" 2>/dev/null)
        if [ -n "$base_disk" ]; then
            ZFS_DISKS+="/dev/$base_disk"$'\n'
        fi
    fi
done
ZFS_DISKS=$(echo "$ZFS_DISKS" | sort -u)

is_disk_in_use() {
    local disk="$1"
    while read -r part fstype; do
        case "$fstype" in
            zfs_member|linux_raid_member)
                return 0 ;;
        esac
        if echo "$MOUNTED_DISKS" | grep -q "/dev/$part"; then
            return 0
        fi
    done < <(lsblk -ln -o NAME,FSTYPE "$disk" | tail -n +2)
    
    if echo "$USED_DISKS" | grep -q "$disk" || echo "$ZFS_DISKS" | grep -q "$disk"; then
        return 0
    fi
    return 1
}

FREE_DISKS=()
LVM_DEVICES=$(pvs --noheadings -o pv_name 2> >(grep -v 'File descriptor .* leaked') | xargs -r -n1 readlink -f | sort -u)

if [[ -n "$LVM_DEVICES" ]] && echo "$LVM_DEVICES" | grep -qFx "$REAL_PATH"; then
    IS_MOUNTED=true
fi

RAID_ACTIVE=$(grep -Po 'md\d+\s*:\s*active\s+raid[0-9]+' /proc/mdstat | awk '{print $1}' | sort -u)

while read -r DISK; do
    [[ "$DISK" =~ /dev/zd ]] && continue
    
    INFO=($(get_disk_info "$DISK"))
    MODEL="${INFO[@]::${#INFO[@]}-1}"
    SIZE="${INFO[-1]}"
    LABEL=""
    SHOW_DISK=true
    IS_MOUNTED=false
    IS_RAID=false
    IS_ZFS=false
    IS_LVM=false
    
    while read -r part fstype; do
        [[ "$fstype" == "zfs_member" ]] && IS_ZFS=true
        [[ "$fstype" == "linux_raid_member" ]] && IS_RAID=true
        [[ "$fstype" == "LVM2_member" ]] && IS_LVM=true
        if grep -q "/dev/$part" <<< "$MOUNTED_DISKS"; then
            IS_MOUNTED=true
        fi
    done < <(lsblk -ln -o NAME,FSTYPE "$DISK" | tail -n +2)
    
    REAL_PATH=$(readlink -f "$DISK")
    if echo "$LVM_DEVICES" | grep -qFx "$REAL_PATH"; then
        IS_MOUNTED=true
    fi
    
    USED_BY=""
    REAL_PATH=$(readlink -f "$DISK")
    CONFIG_DATA=$(grep -vE '^\s*#' /etc/pve/qemu-server/*.conf /etc/pve/lxc/*.conf 2>/dev/null)
    
    if grep -Fq "$REAL_PATH" <<< "$CONFIG_DATA"; then
        USED_BY="⚠ $(translate "In use")"
    else
        for SYMLINK in /dev/disk/by-id/*; do
            if [[ "$(readlink -f "$SYMLINK")" == "$REAL_PATH" ]]; then
                if grep -Fq "$SYMLINK" <<< "$CONFIG_DATA"; then
                    USED_BY="⚠ $(translate "In use")"
                    break
                fi
            fi
        done
    fi
    
    if $IS_RAID && grep -q "$DISK" <<< "$(cat /proc/mdstat)"; then
        if grep -q "active raid" /proc/mdstat; then
            SHOW_DISK=false
        fi
    fi
    
    if $IS_ZFS; then
        SHOW_DISK=false
    fi
    
    if $IS_MOUNTED; then
        SHOW_DISK=false
    fi
    
    # Check if disk is already assigned to this CT using persistent paths
    if pct config "$CTID" | grep -vE '^\s*#|^description:' | grep -q "$DISK"; then
        SHOW_DISK=false
    else
        # Also check persistent paths
        PERSISTENT_DISK=$(get_persistent_path "$DISK")
        if [[ "$PERSISTENT_DISK" != "$DISK" ]] && pct config "$CTID" | grep -vE '^\s*#|^description:' | grep -q "$PERSISTENT_DISK"; then
            SHOW_DISK=false
        fi
    fi
    
    if $SHOW_DISK; then
        [[ -n "$USED_BY" ]] && LABEL+=" [$USED_BY]"
        [[ "$IS_RAID" == true ]] && LABEL+=" ⚠ RAID"
        [[ "$IS_LVM" == true ]] && LABEL+=" ⚠ LVM"
        [[ "$IS_ZFS" == true ]] && LABEL+=" ⚠ ZFS"
        
        DESCRIPTION=$(printf "%-30s %10s%s" "$MODEL" "$SIZE" "$LABEL")
        FREE_DISKS+=("$DISK" "$DESCRIPTION" "OFF")
    fi
done < <(lsblk -dn -e 7,11 -o PATH)

if [ "${#FREE_DISKS[@]}" -eq 0 ]; then
    cleanup
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No disks available for this CT.")" 8 40
    clear
    exit 1
fi

msg_ok "$(translate "Available disks detected.")"

######################################################
MAX_WIDTH=$(printf "%s\n" "${FREE_DISKS[@]}" | awk '{print length}' | sort -nr | head -n1)
TOTAL_WIDTH=$((MAX_WIDTH + 20))
if [ $TOTAL_WIDTH -lt 50 ]; then
    TOTAL_WIDTH=50
fi

SELECTED=$(whiptail --title "$(translate "Select Disks")" --radiolist \
    "$(translate "Select the disks you want to add:")" 20 $TOTAL_WIDTH 10 "${FREE_DISKS[@]}" 3>&1 1>&2 2>&3)

if [ -z "$SELECTED" ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No disks were selected.")" 10 64
    clear
    exit 1
fi

msg_ok "$(translate "Disks selected successfully.")"

DISKS_ADDED=0
ERROR_MESSAGES=""
SUCCESS_MESSAGES=""

msg_info "$(translate "Processing selected disks...")"

for DISK in $SELECTED; do
    DISK=$(echo "$DISK" | tr -d '"')
    DISK_INFO=$(get_disk_info "$DISK")
    
    ASSIGNED_TO=""
    RUNNING_CTS=""
    RUNNING_VMS=""
    
    while read -r CT_ID CT_NAME; do
        if [[ "$CT_ID" =~ ^[0-9]+$ ]] && pct config "$CT_ID" | grep -q "$DISK"; then
            ASSIGNED_TO+="CT $CT_ID $CT_NAME\n"
            CT_STATUS=$(pct status "$CT_ID" | awk '{print $2}')
            if [ "$CT_STATUS" == "running" ]; then
                RUNNING_CTS+="CT $CT_ID $CT_NAME\n"
            fi
        fi
    done < <(pct list | awk 'NR>1 {print $1, $3}')
    
    while read -r VM_ID VM_NAME; do
        if [[ "$VM_ID" =~ ^[0-9]+$ ]] && qm config "$VM_ID" | grep -q "$DISK"; then
            ASSIGNED_TO+="VM $VM_ID $VM_NAME\n"
            VM_STATUS=$(qm status "$VM_ID" | awk '{print $2}')
            if [ "$VM_STATUS" == "running" ]; then
                RUNNING_VMS+="VM $VM_ID $VM_NAME\n"
            fi
        fi
    done < <(qm list | awk 'NR>1 {print $1, $2}')
    
    if [ -n "$RUNNING_CTS" ] || [ -n "$RUNNING_VMS" ]; then
        ERROR_MESSAGES+="$(translate "The disk") $DISK_INFO $(translate "is in use by the following running VM(s) or CT(s):")\\n$RUNNING_CTS$RUNNING_VMS\\n\\n"
        continue
    fi
    
    if [ -n "$ASSIGNED_TO" ]; then
        cleanup
        whiptail --title "$(translate "Disk Already Assigned")" --yesno "$(translate "The disk") $DISK_INFO $(translate "is already assigned to the following VM(s) or CT(s):")\\n$ASSIGNED_TO\\n\\n$(translate "Do you want to continue anyway?")" 15 70
        if [ $? -ne 0 ]; then
            sleep 1
            exec "$0"
        fi
    fi
    
    cleanup
    
    if lsblk "$DISK" | grep -q "raid" || grep -q "${DISK##*/}" /proc/mdstat; then
        whiptail --title "$(translate "RAID Detected")" --msgbox "$(translate "The disk") $DISK_INFO $(translate "appears to be part of a") RAID. $(translate "For security reasons, the system cannot format it.")\\n\\n$(translate "If you are sure you want to use it, please remove the") RAID metadata $(translate "or format it manually using external tools.")\\n\\n$(translate "After that, run this script again to add it.")" 18 70
        clear
        exit
    fi
    
    MOUNT_POINT=$(whiptail --title "$(translate "Mount Point")" --inputbox "$(translate "Enter the mount point for the disk (e.g., /mnt/disk_passthrough):")" 10 60 "/mnt/disk_passthrough" 3>&1 1>&2 2>&3)
    
    if [ -z "$MOUNT_POINT" ]; then
        whiptail --title "$(translate "Error")" --msgbox "$(translate "No mount point was specified.")" 8 40
        continue
    fi
    
    msg_ok "$(translate "Mount point specified: $MOUNT_POINT")"
    
    PARTITION=$(lsblk -rno NAME "$DISK" | awk -v disk="$(basename "$DISK")" '$1 != disk {print $1; exit}')
    SKIP_FORMAT=false
    
    if [ -n "$PARTITION" ]; then
        PARTITION="/dev/$PARTITION"
        CURRENT_FS=$(lsblk -no FSTYPE "$PARTITION" | xargs)
        if [[ "$CURRENT_FS" == "ext4" || "$CURRENT_FS" == "xfs" || "$CURRENT_FS" == "btrfs" ]]; then
            SKIP_FORMAT=true
            msg_ok "$(translate "Detected existing filesystem") $CURRENT_FS $(translate "on") $PARTITION."
        else
            whiptail --title "$(translate "Unsupported Filesystem")" --yesno "$(translate "The partition") $PARTITION $(translate "has an unsupported filesystem ($CURRENT_FS).\\nDo you want to format it?")" 10 70
            if [ $? -ne 0 ]; then
                continue
            fi
        fi
    else
        CURRENT_FS=$(lsblk -no FSTYPE "$DISK" | xargs)
        if [[ "$CURRENT_FS" == "ext4" || "$CURRENT_FS" == "xfs" || "$CURRENT_FS" == "btrfs" ]]; then
            SKIP_FORMAT=true
            PARTITION="$DISK"
            msg_ok "$(translate "Detected filesystem") $CURRENT_FS $(translate "directly on disk") $DISK."
        else
            whiptail --title "$(translate "No Valid Partitions")" --yesno "$(translate "The disk has no partitions and no valid filesystem. Do you want to create a new partition and format it?")" 10 70
            if [ $? -ne 0 ]; then
                continue
            fi
            
            echo -e "$(translate "Creating partition table and partition...")"
            parted -s "$DISK" mklabel gpt
            parted -s "$DISK" mkpart primary 0% 100%
            sleep 2
            partprobe "$DISK"
            sleep 2
            
            PARTITION=$(lsblk -rno NAME "$DISK" | awk -v disk="$(basename "$DISK")" '$1 != disk {print $1; exit}')
            if [ -n "$PARTITION" ]; then
                PARTITION="/dev/$PARTITION"
            else
                whiptail --title "$(translate "Partition Error")" --msgbox "$(translate "Failed to create partition on disk") $DISK_INFO." 8 70
                continue
            fi
        fi
    fi
    
    if [ "$SKIP_FORMAT" != true ]; then
        CURRENT_FS=$(lsblk -no FSTYPE "$PARTITION" | xargs)
        if [[ "$CURRENT_FS" == "ext4" || "$CURRENT_FS" == "xfs" || "$CURRENT_FS" == "btrfs" ]]; then
            SKIP_FORMAT=true
            msg_ok "$(translate "Detected existing filesystem") $CURRENT_FS $(translate "on") $PARTITION. $(translate "Skipping format.")"
        else
            FORMAT_TYPE=$(whiptail --title "$(translate "Select Format Type")" --menu "$(translate "Select the filesystem type for") $DISK_INFO:" 15 60 6 \
                "ext4" "$(translate "Extended Filesystem 4 (recommended)")" \
                "xfs" "$(translate "XFS Filesystem")" \
                "btrfs" "$(translate "Btrfs Filesystem")" 3>&1 1>&2 2>&3)
            
            if [ -z "$FORMAT_TYPE" ]; then
                whiptail --title "$(translate "Format Cancelled")" --msgbox "$(translate "Format operation cancelled. The disk will not be added.")" 8 60
                continue
            fi
            
            whiptail --title "$(translate "WARNING")" --yesno "$(translate "WARNING: This operation will FORMAT the disk") $DISK_INFO $(translate "with") $FORMAT_TYPE.\\n\\n$(translate "ALL DATA ON THIS DISK WILL BE PERMANENTLY LOST!")\\n\\n$(translate "Are you sure you want to continue")" 15 70
            if [ $? -ne 0 ]; then
                whiptail --title "$(translate "Format Cancelled")" --msgbox "$(translate "Format operation cancelled. The disk will not be added.")" 8 60
                continue
            fi
        fi
    fi
    
    if [ "$SKIP_FORMAT" != true ]; then
        echo -e "$(translate "Formatting partition") $PARTITION $(translate "with") $FORMAT_TYPE..."
        case "$FORMAT_TYPE" in
            "ext4") mkfs.ext4 -F "$PARTITION" ;;
            "xfs") mkfs.xfs -f "$PARTITION" ;;
            "btrfs") mkfs.btrfs -f "$PARTITION" ;;
        esac
        
        if [ $? -ne 0 ]; then
            whiptail --title "$(translate "Format Failed")" --msgbox "$(translate "Failed to format partition") $PARTITION $(translate "with") $FORMAT_TYPE.\\n\\n$(translate "The disk may be in use by the system or have hardware issues.")" 12 70
            continue
        else
            msg_ok "$(translate "Partition") $PARTITION $(translate "successfully formatted with") $FORMAT_TYPE."
            partprobe "$DISK"
            sleep 2
        fi
    fi
    
    INDEX=0
    while pct config "$CTID" | grep -q "mp${INDEX}:"; do
        ((INDEX++))
    done
    
    # Determine the filesystem type for mount options
    CURRENT_FS=$(lsblk -no FSTYPE "$PARTITION" | xargs)
    if [[ -n "$CURRENT_FS" ]]; then
        FORMAT_TYPE="$CURRENT_FS"
    fi
    
    # Install filesystem tools in container if needed
    FS_PKG=""
    FS_BIN=""
    if [[ "$FORMAT_TYPE" == "xfs" ]]; then
        FS_PKG="xfsprogs"
        FS_BIN="mkfs.xfs"
    elif [[ "$FORMAT_TYPE" == "btrfs" ]]; then
        FS_PKG="btrfs-progs"
        FS_BIN="mkfs.btrfs"
    fi
    
    if [[ -n "$FS_PKG" && -n "$FS_BIN" ]]; then
        if ! pct exec "$CTID" -- sh -c "command -v $FS_BIN >/dev/null 2>&1"; then
            msg_info "$(translate "Installing required tools for $FORMAT_TYPE in CT $CTID...")"
            if pct exec "$CTID" -- sh -c "[ -f /etc/alpine-release ]"; then
                pct exec "$CTID" -- sh -c "apk update >/dev/null && apk add --no-progress $FS_PKG >/dev/null"
            elif pct exec "$CTID" -- sh -c "[ -f /etc/os-release ] && (grep -qE 'debian|ubuntu' /etc/os-release)"; then
                pct exec "$CTID" -- sh -c "apt-get update -qq >/dev/null && apt-get install -y -qq $FS_PKG >/dev/null"
            fi
            msg_ok "$(translate "Required tools for $FORMAT_TYPE installed in CT $CTID.")"
        fi
    fi
    
    ##############################################################################
    # Get persistent path for the partition
    PERSISTENT_PARTITION=$(get_persistent_path "$PARTITION")
    
    # Apply passthrough with persistent path
    CURRENT_FS=$(lsblk -no FSTYPE "$PARTITION" | xargs)
    if [ "$CURRENT_FS" == "xfs" ] || [ "$FORMAT_TYPE" == "xfs" ]; then
        RESULT=$(pct set "$CTID" -mp${INDEX} "$PERSISTENT_PARTITION,mp=$MOUNT_POINT,backup=0,ro=0" 2>&1)
    else
        RESULT=$(pct set "$CTID" -mp${INDEX} "$PERSISTENT_PARTITION,mp=$MOUNT_POINT,backup=0,ro=0,acl=1" 2>&1)
    fi
    
    # Adjust permissions inside the CT
    pct exec "$CTID" -- chmod -R 775 "$MOUNT_POINT" 2>/dev/null || true
    
    # Show confirmation with persistent identifier
    msg_ok "$(translate "Assigned using") $PERSISTENT_PARTITION"
    ##############################################################################
    
    if [ $? -eq 0 ]; then
        MESSAGE="$(translate "The disk") $DISK_INFO $(translate "has been successfully added to CT") $CTID $(translate "as a mount point at") $MOUNT_POINT."
        MESSAGE+="\\n$(translate "Using persistent path"): $PERSISTENT_PARTITION"
        
        if [ -n "$ASSIGNED_TO" ]; then
            MESSAGE+="\\n\\n$(translate "WARNING: This disk is also assigned to the following CT(s):")\\n$ASSIGNED_TO"
            MESSAGE+="\\n$(translate "Make sure not to start CTs that share this disk at the same time to avoid data corruption.")"
        fi
        
        SUCCESS_MESSAGES+="$MESSAGE\\n\\n"
        ((DISKS_ADDED++))
    else
        ERROR_MESSAGES+="$(translate "Could not add disk") $DISK_INFO $(translate "to CT") $CTID.\\n$(translate "Error:") $RESULT\\n\\n"
    fi
done

msg_ok "$(translate "Disk processing completed.")"

if [ -n "$SUCCESS_MESSAGES" ]; then
    MSG_LINES=$(echo "$SUCCESS_MESSAGES" | wc -l)
    whiptail --title "$(translate "Successful Operations")" --msgbox "$SUCCESS_MESSAGES" 16 70
fi

if [ -n "$ERROR_MESSAGES" ]; then
    whiptail --title "$(translate "Warnings and Errors")" --msgbox "$ERROR_MESSAGES" 16 70
fi

msg_success "$(translate "Press Enter to return to menu...")"
read -r
exit 0
