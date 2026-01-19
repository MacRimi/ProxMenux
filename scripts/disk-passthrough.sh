#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 28/01/2025
# ==========================================================
# Description:
# This script allows users to assign physical disks to existing
# Proxmox virtual machines (VMs) through an interactive menu.
# - Detects the system disk and excludes it from selection.
# - Lists all available VMs for the user to choose from.
# - Identifies and displays unassigned physical disks.
# - Allows the user to select multiple disks and attach them to a VM.
# - Supports interface types: SATA, SCSI, VirtIO, and IDE.
# - Ensures that disks are not already assigned to active VMs.
# - Warns about disk sharing between multiple VMs to avoid data corruption.
# - Configures the selected disks for the VM and verifies the assignment.
#
# The goal of this script is to simplify the process of assigning
# physical disks to Proxmox VMs, reducing manual configurations
# and preventing potential errors.
# ==========================================================


# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
load_language
initialize_cache
show_proxmenux_logo
# ==========================================================



get_disk_info() {
    local disk=$1
    MODEL=$(lsblk -dn -o MODEL "$disk" | xargs)
    SIZE=$(lsblk -dn -o SIZE "$disk" | xargs)
    echo "$MODEL" "$SIZE"
}


VM_LIST=$(qm list | awk 'NR>1 {print $1, $2}')
if [ -z "$VM_LIST" ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No VMs available in the system.")" 8 40
    exit 1
fi


VMID=$(whiptail --title "$(translate "Select VM")" --menu "$(translate "Select the VM to which you want to add disks:")" 15 60 8 $VM_LIST 3>&1 1>&2 2>&3)

if [ -z "$VMID" ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No VM was selected.")" 8 40
    exit 1
fi

VMID=$(echo "$VMID" | tr -d '"')


msg_ok "$(translate "VM selected successfully.")"


VM_STATUS=$(qm status "$VMID" | awk '{print $2}')
if [ "$VM_STATUS" == "running" ]; then
    whiptail --title "$(translate "Warning")" --msgbox "$(translate "The VM is powered on. Turn it off before adding disks.")" 12 60
    exit 1
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


    if qm config "$VMID" | grep -vE '^\s*#|^description:' | grep -q "$DISK"; then
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
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No disks available for this VM.")" 8 40
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


SELECTED=$(whiptail --title "$(translate "Select Disks")" --checklist \
    "$(translate "Select the disks you want to add:")" 20 $TOTAL_WIDTH 10 "${FREE_DISKS[@]}" 3>&1 1>&2 2>&3)

if [ -z "$SELECTED" ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No disks were selected.")" 10 64
    clear
    exit 1
fi

msg_ok "$(translate "Disks selected successfully.")"


INTERFACE=$(whiptail --title "$(translate "Interface Type")" --menu "$(translate "Select the interface type for all disks:")" 15 40 4 \
    "sata" "$(translate "Add as SATA")" \
    "scsi" "$(translate "Add as SCSI")" \
    "virtio" "$(translate "Add as VirtIO")" \
    "ide" "$(translate "Add as IDE")" 3>&1 1>&2 2>&3)

if [ -z "$INTERFACE" ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "No interface type was selected for the disks.")" 8 40
    clear
    exit 1
fi

msg_ok "$(translate "Interface type selected: $INTERFACE")"

DISKS_ADDED=0
ERROR_MESSAGES=""
SUCCESS_MESSAGES=""



msg_info "$(translate "Processing selected disks...")"

for DISK in $SELECTED; do
    DISK=$(echo "$DISK" | tr -d '"')
    DISK_INFO=$(get_disk_info "$DISK")

    ASSIGNED_TO=""
    RUNNING_VMS=""
    RUNNING_CTS=""

  
    while read -r VM_ID VM_NAME; do
        if [[ "$VM_ID" =~ ^[0-9]+$ ]] && qm config "$VM_ID" | grep -q "$DISK"; then
            ASSIGNED_TO+="VM $VM_ID $VM_NAME\n"
            VM_STATUS=$(qm status "$VM_ID" | awk '{print $2}')
            if [ "$VM_STATUS" == "running" ]; then
                RUNNING_VMS+="VM $VM_ID $VM_NAME\n"
            fi
        fi
    done < <(qm list | awk 'NR>1 {print $1, $2}')


    while read -r CT_ID CT_NAME; do
        if [[ "$CT_ID" =~ ^[0-9]+$ ]] && pct config "$CT_ID" | grep -q "$DISK"; then
            ASSIGNED_TO+="CT $CT_ID $CT_NAME\n"
            CT_STATUS=$(pct status "$CT_ID" | awk '{print $2}')
            if [ "$CT_STATUS" == "running" ]; then
                RUNNING_CTS+="CT $CT_ID $CT_NAME\n"
            fi
        fi
    done < <(pct list | awk 'NR>1 {print $1, $2}')

    if [ -n "$RUNNING_VMS" ] || [ -n "$RUNNING_CTS" ]; then
        ERROR_MESSAGES+="$(translate "The disk") $DISK_INFO $(translate "is currently in use by the following running VM(s) or CT(s):")\\n$RUNNING_VMS$RUNNING_CTS\\n\\n$(translate "You cannot add this disk while the VM or CT is running.")\\n$(translate "Please shut it down first and run this script again to add the disk.")\\n\\n"
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


    INDEX=0
    while qm config "$VMID" | grep -q "${INTERFACE}${INDEX}"; do
        ((INDEX++))
    done

    RESULT=$(qm set "$VMID" -${INTERFACE}${INDEX} "$DISK" 2>&1)

    if [ $? -eq 0 ]; then
        MESSAGE="$(translate "The disk") $DISK_INFO $(translate "has been successfully added to VM") $VMID."
        if [ -n "$ASSIGNED_TO" ]; then
            MESSAGE+="\\n\\n$(translate "WARNING: This disk is also assigned to the following VM(s):")\\n$ASSIGNED_TO"
            MESSAGE+="\\n$(translate "Make sure not to start VMs that share this disk at the same time to avoid data corruption.")"
        fi
        SUCCESS_MESSAGES+="$MESSAGE\\n\\n"
        ((DISKS_ADDED++))
    else
        ERROR_MESSAGES+="$(translate "Could not add disk") $DISK_INFO $(translate "to VM") $VMID.\\n$(translate "Error:") $RESULT\\n\\n"
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



exit 0
