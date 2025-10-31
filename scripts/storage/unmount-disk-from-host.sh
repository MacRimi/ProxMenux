#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 28/01/2025
# Description : Allows unmounting a previously mounted disk
# ==========================================================

REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
load_language
initialize_cache


MOUNTED_DISKS=($(mount | grep '^/dev/' | grep 'on /mnt/' | awk '{print $3}'))

if [[ ${#MOUNTED_DISKS[@]} -eq 0 ]]; then
    whiptail --title "$(translate "No Disks")" --msgbox "$(translate "No mounted disks found under /mnt.")" 8 50
    exit 0
fi


MENU_ITEMS=()
for MNT in "${MOUNTED_DISKS[@]}"; do
    UUID=$(blkid | grep "$MNT" | awk '{print $2}' | tr -d '"')
    DESC="$MNT $UUID"
    MENU_ITEMS+=("$MNT" "$DESC")
done

SELECTED=$(whiptail --title "$(translate "Unmount Disk")" --menu "$(translate "Select the disk you want to unmount:")" 20 70 10 "${MENU_ITEMS[@]}" 3>&1 1>&2 2>&3)

[[ -z "$SELECTED" ]] && exit 0


whiptail --title "$(translate "Confirm Unmount")" --yesno "$(translate "Are you sure you want to unmount") $SELECTED?" 10 60 || exit 0


umount "$SELECTED" 2>/dev/null
if [ $? -ne 0 ]; then
    whiptail --title "$(translate "Error")" --msgbox "$(translate "Failed to unmount disk at") $SELECTED" 8 60
    exit 1
else
    msg_ok "$(translate "Unmounted:") $SELECTED"
fi


whiptail --title "$(translate "Delete Mount Folder")" --yesno "$(translate "Do you want to delete the mount point folder") $SELECTED?" 10 60
if [ $? -eq 0 ]; then
    rm -rf "$SELECTED"
    msg_ok "$(translate "Deleted folder:") $SELECTED"
fi


DEVICE=$(findmnt -no SOURCE "$SELECTED")
UUID=$(blkid -s UUID -o value "$DEVICE")

if [ -n "$UUID" ]; then
    sed -i "/UUID=$UUID/d" /etc/fstab
    msg_ok "$(translate "fstab entry removed for") $UUID"
fi

whiptail --title "$(translate "Done")" --msgbox "$(translate "Disk unmounted and cleaned successfully.")" 8 60

