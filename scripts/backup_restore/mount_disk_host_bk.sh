#!/bin/bash

# ==========================================================
# ProxMenux - Mount disk on Proxmox host for backups
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT
# Version     : 1.3-dialog
# Last Updated: 13/12/2024
# ==========================================================

REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
load_language
initialize_cache


mount_disk_host_bk() {



get_disk_info() {
    local disk=$1
    MODEL=$(lsblk -dn -o MODEL "$disk" | xargs)
    SIZE=$(lsblk -dn -o SIZE "$disk" | xargs)
    echo "$MODEL" "$SIZE"
}


is_usb_disk() {
    local disk=$1
    local disk_name=$(basename "$disk")
    

    if readlink -f "/sys/block/$disk_name/device" 2>/dev/null | grep -q "usb"; then
        return 0 
    fi
    

    if udevadm info --query=property --name="$disk" 2>/dev/null | grep -q "ID_BUS=usb"; then
        return 0  
    fi
    
    return 1
}


is_system_disk() {
    local disk=$1
    local disk_name=$(basename "$disk")
    

    local system_mounts=$(df -h | grep -E '^\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(/|/boot|/usr|/var|/home)$' | awk '{print $1}')
    

    for mount_dev in $system_mounts; do
   
        local mount_disk=""
        if [[ "$mount_dev" =~ ^/dev/mapper/ ]]; then
     
            local vg_name=$(lvs --noheadings -o vg_name "$mount_dev" 2>/dev/null | xargs)
            if [[ -n "$vg_name" ]]; then
                local pvs_list=$(pvs --noheadings -o pv_name -S vg_name="$vg_name" 2>/dev/null | xargs)
                for pv in $pvs_list; do
                    if [[ -n "$pv" && -e "$pv" ]]; then
                        mount_disk=$(lsblk -no PKNAME "$pv" 2>/dev/null)
                        if [[ -n "$mount_disk" && "/dev/$mount_disk" == "$disk" ]]; then
                            return 0  
                        fi
                    fi
                done
            fi
        elif [[ "$mount_dev" =~ ^/dev/[hsv]d[a-z][0-9]* || "$mount_dev" =~ ^/dev/nvme[0-9]+n[0-9]+p[0-9]+ ]]; then
      
            mount_disk=$(lsblk -no PKNAME "$mount_dev" 2>/dev/null)
            if [[ -n "$mount_disk" && "/dev/$mount_disk" == "$disk" ]]; then
                return 0  
            fi
        fi
    done
    

    local fs_type=$(lsblk -no FSTYPE "$disk" 2>/dev/null | head -1)
    if [[ "$fs_type" == "btrfs" ]]; then

        local temp_mount=$(mktemp -d)
        if mount -o ro "$disk" "$temp_mount" 2>/dev/null; then
   
            if btrfs subvolume list "$temp_mount" 2>/dev/null | grep -qE '(@|@home|@var|@boot|@root|root)'; then
                umount "$temp_mount" 2>/dev/null
                rmdir "$temp_mount" 2>/dev/null
                return 0  
            fi
            umount "$temp_mount" 2>/dev/null
        fi
        rmdir "$temp_mount" 2>/dev/null
        

        while read -r part; do
            if [[ -n "$part" ]]; then
                local part_fs=$(lsblk -no FSTYPE "/dev/$part" 2>/dev/null)
                if [[ "$part_fs" == "btrfs" ]]; then
                    local mount_point=$(lsblk -no MOUNTPOINT "/dev/$part" 2>/dev/null)
                    if [[ "$mount_point" == "/" || "$mount_point" == "/boot" || "$mount_point" == "/home" || "$mount_point" == "/var" ]]; then
                        return 0  
                    fi
                fi
            fi
        done < <(lsblk -ln -o NAME "$disk" | tail -n +2)
    fi
    

    local disk_uuid=$(blkid -s UUID -o value "$disk" 2>/dev/null)
    local part_uuids=()
    while read -r part; do
        if [[ -n "$part" ]]; then
            local uuid=$(blkid -s UUID -o value "/dev/$part" 2>/dev/null)
            if [[ -n "$uuid" ]]; then
                part_uuids+=("$uuid")
            fi
        fi
    done < <(lsblk -ln -o NAME "$disk" | tail -n +2)
    
 
    for uuid in "${part_uuids[@]}" "$disk_uuid"; do
        if [[ -n "$uuid" ]] && grep -q "UUID=$uuid" /etc/fstab; then
            local mount_point=$(grep "UUID=$uuid" /etc/fstab | awk '{print $2}')
            if [[ "$mount_point" == "/" || "$mount_point" == "/boot" || "$mount_point" == "/home" || "$mount_point" == "/var" ]]; then
                return 0  
            fi
        fi
    done
    

    if grep -q "$disk" /etc/fstab; then
        local mount_point=$(grep "$disk" /etc/fstab | awk '{print $2}')
        if [[ "$mount_point" == "/" || "$mount_point" == "/boot" || "$mount_point" == "/home" || "$mount_point" == "/var" ]]; then
            return 0 
        fi
    fi
    

    local disk_count=$(lsblk -dn -e 7,11 -o PATH | wc -l)
    if [[ "$disk_count" -eq 1 ]]; then
        return 0 
    fi
    
    return 1 
}


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

LVM_DEVICES=$(
    pvs --noheadings -o pv_name 2> >(grep -v 'File descriptor .* leaked') |
    while read -r dev; do
        [[ -n "$dev" && -e "$dev" ]] && readlink -f "$dev"
    done | sort -u
)

FREE_DISKS=()

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
    IS_SYSTEM=false
    IS_USB=false

 
    if is_system_disk "$DISK"; then
        IS_SYSTEM=true
    fi

  
    if is_usb_disk "$DISK"; then
        IS_USB=true
    fi

    while read -r part fstype; do
        [[ "$fstype" == "zfs_member" ]] && IS_ZFS=true
        [[ "$fstype" == "linux_raid_member" ]] && IS_RAID=true
        [[ "$fstype" == "LVM2_member" ]] && IS_LVM=true
        if grep -q "/dev/$part" <<< "$MOUNTED_DISKS"; then
            IS_MOUNTED=true
        fi
    done < <(lsblk -ln -o NAME,FSTYPE "$DISK" | tail -n +2)

    REAL_PATH=""
    if [[ -n "$DISK" && -e "$DISK" ]]; then
        REAL_PATH=$(readlink -f "$DISK")
    fi
    if [[ -n "$REAL_PATH" ]] && echo "$LVM_DEVICES" | grep -qFx "$REAL_PATH"; then
        IS_MOUNTED=true
    fi

    USED_BY=""
    REAL_PATH=""
    if [[ -n "$DISK" && -e "$DISK" ]]; then
        REAL_PATH=$(readlink -f "$DISK")
    fi
    CONFIG_DATA=$(grep -vE '^\s*#' /etc/pve/qemu-server/*.conf /etc/pve/lxc/*.conf 2>/dev/null)

    if grep -Fq "$REAL_PATH" <<< "$CONFIG_DATA"; then
        USED_BY="⚠ $(translate "In use")"
    else
        for SYMLINK in /dev/disk/by-id/*; do
            [[ -e "$SYMLINK" ]] || continue
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
    if $IS_ZFS; then SHOW_DISK=false; fi
    if $IS_MOUNTED; then SHOW_DISK=false; fi
    if $IS_SYSTEM; then SHOW_DISK=false; fi  

    if $SHOW_DISK; then
        [[ -n "$USED_BY" ]] && LABEL+=" [$USED_BY]"
        [[ "$IS_RAID" == true ]] && LABEL+=" ⚠ RAID"
        [[ "$IS_LVM" == true ]] && LABEL+=" ⚠ LVM"
        [[ "$IS_ZFS" == true ]] && LABEL+=" ⚠ ZFS"
        
        
        if $IS_USB; then
            LABEL+="  USB"
        else
            LABEL+="  $(translate "Internal")"
        fi
        
        DESCRIPTION=$(printf "%-30s %10s%s" "$MODEL" "$SIZE" "$LABEL")
        FREE_DISKS+=("$DISK" "$DESCRIPTION" "off")
    fi
done < <(lsblk -dn -e 7,11 -o PATH)

if [ "${#FREE_DISKS[@]}" -eq 0 ]; then
    dialog --title "$(translate "Error")" --msgbox "$(translate "No available disks found on the host.")" 8 60
    
    exit 1
fi


# Building the array for dialog (format: tag item on/off tag item on/off...)
DLG_LIST=()
for ((i=0; i<${#FREE_DISKS[@]}; i+=3)); do
    DLG_LIST+=("${FREE_DISKS[i]}" "${FREE_DISKS[i+1]}" "${FREE_DISKS[i+2]}")
done

SELECTED=$(dialog --clear --backtitle "ProxMenux" --title "$(translate "Select Disk")" \
    --radiolist "\n$(translate "Select the disk you want to mount on the host:")" 20 90 10 \
    "${DLG_LIST[@]}" 2>&1 >/dev/tty)

if [ -z "$SELECTED" ]; then
    dialog --title "$(translate "Error")" --msgbox "$(translate "No disk was selected.")" 8 50
    
    exit 1
fi


# ------------------- Partitions and formatting ------------------------

PARTITION=$(lsblk -rno NAME "$SELECTED" | awk -v disk="$(basename "$SELECTED")" '$1 != disk {print $1; exit}')
SKIP_FORMAT=false
DEFAULT_MOUNT="/mnt/backup"

if [ -n "$PARTITION" ]; then
    PARTITION="/dev/$PARTITION"
    CURRENT_FS=$(lsblk -no FSTYPE "$PARTITION" | xargs)
    if [[ "$CURRENT_FS" == "ext4" || "$CURRENT_FS" == "xfs" || "$CURRENT_FS" == "btrfs" ]]; then
        SKIP_FORMAT=true
      
    else
        dialog --title "$(translate "Unsupported Filesystem")" --yesno \
        "$(translate "The partition") $PARTITION $(translate "has an unsupported filesystem ($CURRENT_FS).\nDo you want to format it?")" 10 70
        if [ $? -ne 0 ]; then exit 0; fi
    fi
else
    CURRENT_FS=$(lsblk -no FSTYPE "$SELECTED" | xargs)
    if [[ "$CURRENT_FS" == "ext4" || "$CURRENT_FS" == "xfs" || "$CURRENT_FS" == "btrfs" ]]; then
        SKIP_FORMAT=true
        PARTITION="$SELECTED"

    else
        dialog --title "$(translate "No Valid Partitions")" --yesno \
        "$(translate "The disk has no partitions and no valid filesystem. Do you want to create a new partition and format it?")" 10 70
        if [ $? -ne 0 ]; then exit 0; fi

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
            dialog --title "$(translate "Partition Error")" --msgbox \
            "$(translate "Failed to create partition on disk") $SELECTED." 8 70
            exit 1
        fi
    fi
fi

if [ "$SKIP_FORMAT" != true ]; then
    FORMAT_TYPE=$(dialog --title "$(translate "Select Format Type")" --menu \
        "$(translate "Select the filesystem type for") $PARTITION:" 15 60 5 \
        "ext4" "$(translate "Extended Filesystem 4 (recommended)")" \
        "xfs" "XFS" \
        "btrfs" "Btrfs" 2>&1 >/dev/tty)
    if [ -z "$FORMAT_TYPE" ]; then
        dialog --title "$(translate "Format Cancelled")" --msgbox \
        "$(translate "Format operation cancelled. The disk will not be added.")" 8 60
        exit 0
    fi

    dialog --title "$(translate "WARNING")" --yesno \
    "$(translate "WARNING: This operation will FORMAT the disk") $PARTITION $(translate "with") $FORMAT_TYPE.\n\n$(translate "ALL DATA ON THIS DISK WILL BE PERMANENTLY LOST!")\n\n$(translate "Are you sure you want to continue")" 15 70
    if [ $? -ne 0 ]; then exit 0; fi

    echo -e "$(translate "Formatting partition") $PARTITION $(translate "with") $FORMAT_TYPE..."
    case "$FORMAT_TYPE" in
        "ext4") mkfs.ext4 -F "$PARTITION" ;;
        "xfs") mkfs.xfs -f "$PARTITION" ;;
        "btrfs") mkfs.btrfs -f "$PARTITION" ;;
    esac

    if [ $? -ne 0 ]; then
        cleanup
        dialog --title "$(translate "Format Failed")" --msgbox \
        "$(translate "Failed to format partition") $PARTITION $(translate "with") $FORMAT_TYPE." 12 70
        exit 1
    else
  
        partprobe "$SELECTED"
        sleep 2
    fi
fi


# ------------------- Mount point and permissions (modular, non-blocking) -------------------



    MOUNT_POINT=$(dialog --clear --title "$(translate "Mount Point")" \
        --inputbox "$(translate "Enter the mount point for the disk (e.g., /mnt/backup):")" \
        10 60 "$DEFAULT_MOUNT" 2>&1 >/dev/tty)

    if [ -z "$MOUNT_POINT" ]; then
        >&2 echo "$(translate "No mount point was specified.")"
        return 1
    fi

    mkdir -p "$MOUNT_POINT"

    UUID=$(blkid -s UUID -o value "$PARTITION")
    FS_TYPE=$(lsblk -no FSTYPE "$PARTITION" | xargs)
    FSTAB_ENTRY="UUID=$UUID $MOUNT_POINT $FS_TYPE defaults 0 0"

    if grep -q "UUID=$UUID" /etc/fstab; then
        sed -i "s|^.*UUID=$UUID.*|$FSTAB_ENTRY|" /etc/fstab
    else
        echo "$FSTAB_ENTRY" >> /etc/fstab
    fi

    mount "$MOUNT_POINT" 2> >(grep -v "systemd still uses")
    if [ $? -eq 0 ]; then
        if ! getent group sharedfiles >/dev/null; then
            groupadd sharedfiles
        fi

        chown root:sharedfiles "$MOUNT_POINT"
        chmod 2775 "$MOUNT_POINT"
        echo "$MOUNT_POINT" > /usr/local/share/proxmenux/last_backup_mount.txt

        MOUNT_POINT=$(echo "$MOUNT_POINT" | head -n1 | tr -d '\r\n\t ')
        echo "$MOUNT_POINT"
    else
        >&2 echo "$(translate "Failed to mount the disk at") $MOUNT_POINT"
        return 1
    fi

}
