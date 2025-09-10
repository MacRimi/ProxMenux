#!/bin/bash

# ==========================================================
# ProxMenux - Mount independent disk on Proxmox host
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 08/04/2025
# ==========================================================
# Description:
# This script detects unassigned physical disks and allows
# the user to mount one of them on the host Proxmox system.
# - Detects unmounted and unassigned disks.
# - Filters out ZFS, LVM, RAID and system disks.
# - Allows selecting a disk.
# - Prepares partition and filesystem if needed.
# - Mounts the disk in the host at a defined mount point.
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
# ==========================================================

get_disk_info() {
    local disk=$1
    MODEL=$(lsblk -dn -o MODEL "$disk" | xargs)
    SIZE=$(lsblk -dn -o SIZE "$disk" | xargs)
    echo "$MODEL" "$SIZE"
}

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

LVM_DEVICES=$(pvs --noheadings -o pv_name 2> >(grep -v 'File descriptor .* leaked') | xargs -n1 readlink -f | sort -u)
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
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No available disks found on the host.")" 8 50
    clear
    exit 1
fi

msg_ok "$(translate "Available disks detected.")"

MAX_WIDTH=$(printf "%s\n" "${FREE_DISKS[@]}" | awk '{print length}' | sort -nr | head -n1)
TOTAL_WIDTH=$((MAX_WIDTH + 20))
TOTAL_WIDTH=$((TOTAL_WIDTH < 50 ? 50 : TOTAL_WIDTH))

SELECTED=$(whiptail --title "$(translate "Select Disk")" --radiolist \
    "$(translate "Select the disk you want to mount on the host:")" 20 $TOTAL_WIDTH 10 "${FREE_DISKS[@]}" 3>&1 1>&2 2>&3)

if [ -z "$SELECTED" ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No disk was selected.")" 10 50
    clear
    exit 1
fi



msg_ok "$(translate "Disk selected successfully:") $SELECTED"





################################################################




PARTITION=$(lsblk -rno NAME "$SELECTED" | awk -v disk="$(basename "$SELECTED")" '$1 != disk {print $1; exit}')

SKIP_FORMAT=false
DEFAULT_MOUNT="/mnt/data_shared"

if [ -n "$PARTITION" ]; then
    PARTITION="/dev/$PARTITION"
    CURRENT_FS=$(lsblk -no FSTYPE "$PARTITION" | xargs)

    if [[ "$CURRENT_FS" == "ext4" || "$CURRENT_FS" == "xfs" || "$CURRENT_FS" == "btrfs" ]]; then
        SKIP_FORMAT=true
        msg_ok "$(translate "Detected existing filesystem") $CURRENT_FS $(translate "on") $PARTITION."
    else
        whiptail --title "$(translate "Unsupported Filesystem")" --yesno "$(translate "The partition") $PARTITION $(translate "has an unsupported filesystem ($CURRENT_FS).\\nDo you want to format it?")" 10 70
        if [ $? -ne 0 ]; then
            exit 0
        fi
    fi
else
    CURRENT_FS=$(lsblk -no FSTYPE "$SELECTED" | xargs)

    if [[ "$CURRENT_FS" == "ext4" || "$CURRENT_FS" == "xfs" || "$CURRENT_FS" == "btrfs" ]]; then
        SKIP_FORMAT=true
        PARTITION="$SELECTED"
        msg_ok "$(translate "Detected filesystem") $CURRENT_FS $(translate "directly on disk") $SELECTED."
    else
        whiptail --title "$(translate "No Valid Partitions")" --yesno "$(translate "The disk has no partitions and no valid filesystem. Do you want to create a new partition and format it?")" 10 70
        if [ $? -ne 0 ]; then
            exit 0
        fi

        echo -e "$(translate "Creating partition table and partition...")"
        parted -s "$SELECTED" mklabel gpt
        parted -s "$SELECTED" mkpart primary 0% 100%
        sleep 2
        partprobe "$SELECTED"
        sleep 2

        PARTITION=$(lsblk -rno NAME "$SELECTED" | awk -v disk="$(basename "$SELECTED")" '$1 != disk {print $1; exit}')
        if [ -n "$PARTITION" ]; then
            PARTITION="/dev/$PARTITION"
        else
            whiptail --title "$(translate "Partition Error")" --msgbox "$(translate "Failed to create partition on disk") $SELECTED." 8 70
            exit 1
        fi
    fi
fi

if [ "$SKIP_FORMAT" != true ]; then
    FORMAT_TYPE=$(whiptail --title "$(translate "Select Format Type")" --menu "$(translate "Select the filesystem type for") $PARTITION:" 15 60 5 \
        "ext4" "$(translate "Extended Filesystem 4 (recommended)")" \
        "xfs" "XFS" \
        "btrfs" "Btrfs" 3>&1 1>&2 2>&3)

    if [ -z "$FORMAT_TYPE" ]; then
        whiptail --title "$(translate "Format Cancelled")" --msgbox "$(translate "Format operation cancelled. The disk will not be added.")" 8 60
        exit 0
    fi

    whiptail --title "$(translate "WARNING")" --yesno "$(translate "WARNING: This operation will FORMAT the disk") $PARTITION $(translate "with") $FORMAT_TYPE.\\n\\n$(translate "ALL DATA ON THIS DISK WILL BE PERMANENTLY LOST!")\\n\\n$(translate "Are you sure you want to continue")" 15 70
    if [ $? -ne 0 ]; then
        exit 0
    fi

    echo -e "$(translate "Formatting partition") $PARTITION $(translate "with") $FORMAT_TYPE..."
    case "$FORMAT_TYPE" in
        "ext4") mkfs.ext4 -F "$PARTITION" ;;
        "xfs") mkfs.xfs -f "$PARTITION" ;;
        "btrfs") mkfs.btrfs -f "$PARTITION" ;;
    esac

    if [ $? -ne 0 ]; then
        cleanup
        whiptail --title "$(translate "Format Failed")" --msgbox "$(translate "Failed to format partition") $PARTITION $(translate "with") $FORMAT_TYPE." 12 70
        exit 1
    else
        msg_ok "$(translate "Partition") $PARTITION $(translate "successfully formatted with") $FORMAT_TYPE."
        partprobe "$SELECTED"
        sleep 2
    fi
fi




################################################################





MOUNT_POINT=$(whiptail --title "$(translate "Mount Point")" \
    --inputbox "$(translate "Enter the mount point for the disk (e.g., /mnt/data_shared):")" \
    10 60 "$DEFAULT_MOUNT" 3>&1 1>&2 2>&3)

if [ -z "$MOUNT_POINT" ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No mount point was specified.")" 8 40
    exit 1
fi

msg_ok "$(translate "Mount point specified:") $MOUNT_POINT"

mkdir -p "$MOUNT_POINT"

UUID=$(blkid -s UUID -o value "$PARTITION")

# Obtener sistema de archivos real
FS_TYPE=$(lsblk -no FSTYPE "$PARTITION" | xargs)

FSTAB_ENTRY="UUID=$UUID $MOUNT_POINT $FS_TYPE defaults 0 0"

if grep -q "UUID=$UUID" /etc/fstab; then
    sed -i "s|^.*UUID=$UUID.*|$FSTAB_ENTRY|" /etc/fstab
    msg_ok "$(translate "fstab entry updated for") $UUID"
else
    echo "$FSTAB_ENTRY" >> /etc/fstab
    msg_ok "$(translate "fstab entry added for") $UUID"
fi


##################################################################

mount "$MOUNT_POINT" 2> >(grep -v "systemd still uses")

##################################################################


if [ $? -eq 0 ]; then
    if ! getent group sharedfiles >/dev/null; then
        groupadd sharedfiles
        msg_ok "$(translate "Group 'sharedfiles' created")"
    else
        msg_ok "$(translate "Group 'sharedfiles' already exists")"
    fi

    chown root:sharedfiles "$MOUNT_POINT"
    chmod 2775 "$MOUNT_POINT"

    whiptail --title "$(translate "Success")" --msgbox "$(translate "The disk has been successfully mounted at") $MOUNT_POINT" 8 60
    msg_ok "$(translate "Disk mounted at") $MOUNT_POINT"
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
else
    whiptail --title "$(translate "Mount Error")" --msgbox "$(translate "Failed to mount the disk at") $MOUNT_POINT" 8 60
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
    exit 1
fi
