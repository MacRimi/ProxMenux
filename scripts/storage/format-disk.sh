#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 28/01/2025
# ==========================================================
# Description : Select and format physical disks
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
LVM_DEVICES=$(pvs --noheadings -o pv_name 2> >(grep -v 'File descriptor .* leaked') | xargs -n1 readlink -f | sort -u)
CONFIG_DATA=$(grep -vE '^\s*#' /etc/pve/qemu-server/*.conf /etc/pve/lxc/*.conf 2>/dev/null)

FREE_DISKS=()

while read -r DISK; do
    [[ "$DISK" =~ /dev/zd ]] && continue

    INFO=($(get_disk_info "$DISK"))
    MODEL="${INFO[@]::${#INFO[@]}-1}"
    SIZE="${INFO[-1]}"
    LABEL=""
    SHOW_DISK=true

    REAL_PATH=$(readlink -f "$DISK")
    USED_BY=""
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

    if echo "$LVM_DEVICES" | grep -qFx "$REAL_PATH"; then
        IS_LVM=true
    fi

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

    if $IS_ZFS || $IS_MOUNTED; then
        SHOW_DISK=false
    fi

    if $SHOW_DISK; then
        [[ "$IS_RAID" == true ]] && LABEL+=" ⚠ RAID"
        [[ -n "$USED_BY" ]] && LABEL+=" [$USED_BY]"
        [[ "$IS_LVM" == true ]] && LABEL+=" ⚠ LVM"
        [[ "$IS_ZFS" == true ]] && LABEL+=" ⚠ ZFS"
        DESCRIPTION=$(printf "%-30s %10s%s" "$MODEL" "$SIZE" "$LABEL")
        FREE_DISKS+=("$DISK" "$DESCRIPTION" "OFF")
    fi

done < <(lsblk -dn -e 7,11 -o PATH)

cleanup

if [ ${#FREE_DISKS[@]} -eq 0 ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No available disks found on the host.")" 8 50
    clear
    exit 1
fi

msg_ok "$(translate "Available disks detected.")"

MAX_WIDTH=$(printf "%s\n" "${FREE_DISKS[@]}" | awk '{print length}' | sort -nr | head -n1)
TOTAL_WIDTH=$((MAX_WIDTH + 20))
TOTAL_WIDTH=$((TOTAL_WIDTH < 50 ? 50 : TOTAL_WIDTH))

SELECTED=$(whiptail --title "$(translate "Select Disk")" --radiolist \
    "$(translate "Select the disk you want to format:")" 20 $TOTAL_WIDTH 10 "${FREE_DISKS[@]}" 3>&1 1>&2 2>&3)

if [ -z "$SELECTED" ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No disks were selected.")" 10 64
    clear
    exit 1
fi

SELECTED=$(echo "$SELECTED" | tr -d '"')
SELECTED_DISK="$SELECTED"


REAL_PATH=$(readlink -f "$SELECTED")
CT_MATCH=""
VM_MATCH=""

while read -r CT_ID CT_NAME; do
    if pct config "$CT_ID" | grep -q "$REAL_PATH"; then
        STATUS=$(pct status "$CT_ID" | awk '{print $2}')
        if [[ "$STATUS" == "running" ]]; then
            CT_MATCH="CT $CT_ID ($CT_NAME)"
            break
        fi
    fi
done < <(pct list | awk 'NR>1 {print $1, $3}')

while read -r VM_ID VM_NAME; do
    if qm config "$VM_ID" | grep -q "$REAL_PATH"; then
        STATUS=$(qm status "$VM_ID" | awk '{print $2}')
        if [[ "$STATUS" == "running" ]]; then
            VM_MATCH="VM $VM_ID ($VM_NAME)"
            break
        fi
    fi
done < <(qm list | awk 'NR>1 {print $1, $2}')

if [[ -n "$CT_MATCH" || -n "$VM_MATCH" ]]; then
    whiptail --title "$(translate "Disk In Use")" --msgbox "$(translate "The selected disk is currently assigned to:")\n\n$CT_MATCH $VM_MATCH\n\n$(translate "You must power off the VM or CT before formatting.")" 12 70
    exit 1
fi








#########################################################




SELECTED_DISK=$(echo "$SELECTED_DISK" | tr -d '"')

WARNING_FLAGS=""
if lsblk -no FSTYPE "$SELECTED_DISK" | grep -q "linux_raid_member"; then
    WARNING_FLAGS+=" RAID"
fi
if lsblk -no FSTYPE "$SELECTED_DISK" | grep -q "LVM2_member"; then
    WARNING_FLAGS+=" LVM"
fi
if lsblk -no FSTYPE "$SELECTED_DISK" | grep -q "zfs_member"; then
    WARNING_FLAGS+=" ZFS"
fi

if [ -n "$WARNING_FLAGS" ]; then
    whiptail --title "$(translate "Warning")" --msgbox "$(translate "This disk appears to have the following metadata:")$WARNING_FLAGS\\n\\n$(translate "They will be erased during formatting.")" 10 60
fi

whiptail --title "$(translate "Confirm Format")" --yesno "$(translate "WARNING: You are about to erase all data on")\\n$SELECTED_DISK\\n\\n$(translate "Are you sure you want to continue?")" 10 70 || exit 0

whiptail --title "$(translate "Final Confirmation")" --yesno "$(translate "FINAL WARNING: This operation will completely format the disk")\\n$SELECTED_DISK\\n\\n$(translate "ALL DATA WILL BE LOST. Proceed?")" 10 70 || exit 0




########################################



echo -e "$(translate "Stopping residual RAID or device mappings...")"

mdadm --misc --stop /dev/md* >/dev/null 2>&1
dmsetup remove_all >/dev/null 2>&1

echo -e "$(translate "Wiping disk metadata and old RAID signatures...")"

sgdisk --zap-all "$SELECTED_DISK" >/dev/null 2>&1
wipefs -a "$SELECTED_DISK" >/dev/null 2>&1

udevadm settle
partprobe "$SELECTED_DISK"
sleep 2

echo -e "$(translate "Creating partition table and partition...")"

parted -s "$SELECTED_DISK" mklabel gpt
parted -s "$SELECTED_DISK" mkpart primary 0% 100%

udevadm settle
partprobe "$SELECTED_DISK"
sleep 2






###########################################



udevadm settle
partprobe "$SELECTED_DISK"
sleep 2


PARTITION=$(lsblk -rno NAME "$SELECTED_DISK" | awk -v disk="$(basename "$SELECTED_DISK")" '$1 != disk {print $1; exit}')
if [ -z "$PARTITION" ]; then
    whiptail --title "$(translate "Partition Error")" --msgbox "$(translate "Failed to create partition on disk.")" 8 60
    exit 1
fi
PARTITION="/dev/$PARTITION"

FORMAT_TYPE=$(whiptail --title "$(translate "Select Filesystem")" --menu "$(translate "Choose the filesystem for the disk:")" 15 60 5 \
    "ext4" "$(translate "Extended Filesystem 4 (recommended)")" \
    "xfs" "XFS" \
    "btrfs" "Btrfs" 3>&1 1>&2 2>&3)

[[ -z "$FORMAT_TYPE" ]] && exit 0

echo -e "$(translate "Formatting partition") $PARTITION $(translate "as") $FORMAT_TYPE..."

case "$FORMAT_TYPE" in
    ext4) mkfs.ext4 -F "$PARTITION" ;;
    xfs) mkfs.xfs -f "$PARTITION" ;;
    btrfs) mkfs.btrfs -f "$PARTITION" ;;
esac

if [ $? -eq 0 ]; then
    msg_ok "$(translate "Disk formatted successfully:") $PARTITION"
    whiptail --title "$(translate "Success")" --msgbox "$(translate "Disk has been formatted successfully.")" 8 50
else
    whiptail --title "$(translate "Error")" --msgbox "$(translate "Failed to format the disk.")" 8 60
    exit 1
fi
