#!/bin/bash

# ==========================================================
# ProxMenux - Manual LXC Conversion Guide
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 19/08/2025
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

show_command() {
    local step="$1"
    local description="$2"
    local command="$3"
    local note="$4"
    local command_extra="$5"
    
    echo -e "${BGN}${step}.${CL} ${BL}${description}${CL}"
    echo ""
    echo -e "${TAB}${command}"
    echo -e
    [[ -n "$note" ]] && echo -e "${TAB}${DARK_GRAY}${note}${CL}"
    [[ -n "$command_extra" ]] && echo -e "${TAB}${YW}${command_extra}${CL}"
    echo ""
}

show_privileged_to_unprivileged_guide() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Manual Guide: Convert LXC Privileged to Unprivileged")"
        
    echo -e "${TAB}${BL}------------------------------------------------------------------------${CL}"
    echo -e 
    echo -e "${TAB}${BGN}$(translate "Source:")${CL} ${BL}https://forum.proxmox.com/threads/converting-between-privileged-and-unprivileged-containers.97243/${CL}"
    echo -e
    echo -e 
    echo -e "${TAB}${BOLD}$(translate "IMPORTANT PREREQUISITES:")${CL}"
    echo -e
    echo -e "${TAB}${BGN}• $(translate "Container must be stopped before conversion")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Create a backup of your container before proceeding")${CL}"
    echo -e "${TAB}${BGN}• $(translate "This process changes file ownership inside the container")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Process may take several minutes depending on container size")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Works with LVM, ZFS, and BTRFS storage types")${CL}"
    echo -e 
    echo -e "${TAB}${BL}------------------------------------------------------------------------${CL}"
    echo -e 

    show_command "1" \
        "$(translate "List all containers to identify the privileged one:")" \
        "pct list" \
        "$(translate "Look for containers without 'unprivileged: 1' in their config")"

    show_command "2" \
        "$(translate "Stop the container if it's running:")" \
        "pct stop <container-id>" \
        "$(translate "Replace <container-id> with your actual container ID")" \
        "$(translate "Example: pct stop 114")"

    show_command "3" \
        "$(translate "Create a backup of the container configuration:")" \
        "cp /etc/pve/lxc/<container-id>.conf /etc/pve/lxc/<container-id>.conf.bak" \
        "$(translate "This creates a backup in case you need to revert changes")" \
        "$(translate "Example: cp /etc/pve/lxc/114.conf /etc/pve/lxc/114.conf.bak")"

    show_command "4" \
        "$(translate "Get the container's storage information:")" \
        "grep '^rootfs:' /etc/pve/lxc/<container-id>.conf" \
        "$(translate "This shows the storage type and disk identifier")" \
        "$(translate "Example output: rootfs: local-lvm:vm-114-disk-0,size=8G")"

    show_command "5" \
        "$(translate "Get the actual disk path:")" \
        "pvesm path <storage-identifier>" \
        "$(translate "Replace <storage-identifier> with the value from step 4")" \
        "$(translate "Example: pvesm path local-lvm:vm-114-disk-0")"

    echo -e "${TAB}${BOLD}$(translate "STEP 6: Choose commands based on your storage type")${CL}"
    echo -e
    echo -e "${TAB}${BGN}$(translate "If pvesm path returned a DIRECTORY (ZFS/BTRFS):")${CL}"
    echo -e "${TAB}${YW}$(translate "Example: /rpool/data/subvol-114-disk-0")${CL}"
    echo -e

    show_command "6a" \
        "$(translate "For ZFS/BTRFS - Set the mount path:")" \
        "MOUNT_PATH=\"/rpool/data/subvol-<container-id>-disk-0\"" \
        "$(translate "Replace with your actual path from step 5")" \
        "$(translate "Example: MOUNT_PATH=\"/rpool/data/subvol-114-disk-0\"")"

    echo -e "${TAB}${BGN}$(translate "If pvesm path returned a DEVICE (LVM):")${CL}"
    echo -e "${TAB}${YW}$(translate "Example: /dev/pve/vm-114-disk-0")${CL}"
    echo -e

    show_command "6b" \
        "$(translate "For LVM - Create mount directory and mount:")" \
        "mkdir -p /tmp/lxc_convert_<container-id>\nmount -o loop /dev/path/to/disk /tmp/lxc_convert_<container-id>\nMOUNT_PATH=\"/tmp/lxc_convert_<container-id>\"" \
        "$(translate "Replace paths with your actual values from step 5")" \
        "$(translate "Example: mkdir -p /tmp/lxc_convert_114")"

    show_command "7" \
        "$(translate "Convert file ownership (this takes time):")" \
        "find \"\$MOUNT_PATH\" -type f | while read file; do\n  if [ -e \"\$file\" ]; then\n    CURRENT_UID=\$(stat -c '%u' \"\$file\")\n    CURRENT_GID=\$(stat -c '%g' \"\$file\")\n    NEW_UID=\$((100000 + CURRENT_UID))\n    NEW_GID=\$((100000 + CURRENT_GID))\n    chown \"\$NEW_UID:\$NEW_GID\" \"\$file\"\n  fi\ndone" \
        "$(translate "This converts all file UIDs/GIDs by adding 100000")" \
        "$(translate "Process may take several minutes for large containers")"

    show_command "8" \
        "$(translate "Convert directory ownership:")" \
        "find \"\$MOUNT_PATH\" -type d | while read dir; do\n  if [ -e \"\$dir\" ]; then\n    CURRENT_UID=\$(stat -c '%u' \"\$dir\")\n    CURRENT_GID=\$(stat -c '%g' \"\$dir\")\n    NEW_UID=\$((100000 + CURRENT_UID))\n    NEW_GID=\$((100000 + CURRENT_GID))\n    chown \"\$NEW_UID:\$NEW_GID\" \"\$dir\"\n  fi\ndone" \
        "$(translate "This converts all directory UIDs/GIDs by adding 100000")"

    echo -e "${TAB}${BOLD}$(translate "STEP 9: Cleanup (LVM only)")${CL}"
    echo -e "${TAB}${YW}$(translate "Only run this if you used LVM (step 6b):")${CL}"
    echo -e

    show_command "9" \
        "$(translate "Unmount and cleanup (LVM only):")" \
        "umount /tmp/lxc_convert_<container-id>\nrmdir /tmp/lxc_convert_<container-id>" \
        "$(translate "Only needed if you mounted the filesystem in step 6b")" \
        "$(translate "Skip this step for ZFS/BTRFS")"

    show_command "10" \
        "$(translate "Add unprivileged flag to container configuration:")" \
        "echo 'unprivileged: 1' >> /etc/pve/lxc/<container-id>.conf" \
        "$(translate "This marks the container as unprivileged")"

    show_command "11" \
        "$(translate "Start the converted container:")" \
        "pct start <container-id>" \
        "$(translate "The container should now start as unprivileged")"

    show_command "12" \
        "$(translate "Verify the conversion:")" \
        "pct config <container-id> | grep unprivileged" \
        "$(translate "Should show 'unprivileged: 1'")"
    
    echo -e "${TAB}${BL}------------------------------------------------------------------------${CL}"
    echo -e 
    echo -e "${TAB}${BOLD}$(translate "STORAGE TYPE IDENTIFICATION:")${CL}"
    echo -e
    echo -e "${TAB}${BGN}• $(translate "LVM:")${CL} ${YW}pvesm path returns /dev/xxx (block device)${CL}"
    echo -e "${TAB}${BGN}• $(translate "ZFS:")${CL} ${YW}pvesm path returns /rpool/xxx (directory)${CL}"
    echo -e "${TAB}${BGN}• $(translate "BTRFS:")${CL} ${YW}pvesm path returns directory path${CL}"
    echo -e
    echo -e "${TAB}${BOLD}$(translate "TROUBLESHOOTING:")${CL}"
    echo -e
    echo -e "${TAB}${BGN}$(translate "If mount fails (LVM):")${CL} ${YW}Check that the container is stopped and disk path is correct${CL}"
    echo -e "${TAB}${BGN}$(translate "If path not accessible (ZFS/BTRFS):")${CL} ${YW}Verify the dataset/subvolume exists and is mounted${CL}"
    echo -e "${TAB}${BGN}$(translate "If container won't start:")${CL} ${YW}Check /var/log/pve/tasks/ for detailed error messages${CL}"
    echo -e "${TAB}${BGN}$(translate "To revert changes:")${CL} ${YW}cp /etc/pve/lxc/<container-id>.conf.bak /etc/pve/lxc/<container-id>.conf${CL}"
    echo -e

    echo -e 
    msg_success "$(translate "Press Enter to return to menu...")"
    echo -e 
    read -r
}

show_unprivileged_to_privileged_guide() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Manual Guide: Convert LXC Unprivileged to Privileged")"
        
    echo -e "${TAB}${BL}------------------------------------------------------------------------${CL}"
    echo -e 
    echo -e "${TAB}${RD}$(translate "SECURITY WARNING:")${CL} ${YW}$(translate "Privileged containers have full root access to the host system!")${CL}"
    echo -e "${TAB}${YW}$(translate "Only convert to privileged if absolutely necessary for your use case.")${CL}"
    echo -e
    echo -e 
    echo -e "${TAB}${BOLD}$(translate "IMPORTANT PREREQUISITES:")${CL}"
    echo -e
    echo -e "${TAB}${BGN}• $(translate "Container must be stopped before conversion")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Create a backup of your container before proceeding")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Understand the security implications of privileged containers")${CL}"
    echo -e "${TAB}${BGN}• $(translate "This is a simple configuration change")${CL}"
    echo -e 
    echo -e "${TAB}${BL}------------------------------------------------------------------------${CL}"
    echo -e 
    

    show_command "1" \
        "$(translate "List all containers to identify the unprivileged one:")" \
        "pct list" \
        "$(translate "Look for containers with 'unprivileged: 1' in their config")"

    show_command "2" \
        "$(translate "Check if container is unprivileged:")" \
        "pct config <container-id> | grep unprivileged" \
        "$(translate "Should show 'unprivileged: 1' if it's unprivileged")" \
        "$(translate "Example: pct config 110 | grep unprivileged")"

    show_command "3" \
        "$(translate "Stop the container if it's running:")" \
        "pct stop <container-id>" \
        "$(translate "Replace <container-id> with your actual container ID")" \
        "$(translate "Example: pct stop 110")"

    show_command "4" \
        "$(translate "Create a backup of the container configuration:")" \
        "cp /etc/pve/lxc/<container-id>.conf /etc/pve/lxc/<container-id>.conf.bak" \
        "$(translate "This creates a backup in case you need to revert changes")" \
        "$(translate "Example: cp /etc/pve/lxc/110.conf /etc/pve/lxc/110.conf.bak")"

    show_command "5" \
        "$(translate "Remove the unprivileged flag from configuration:")" \
        "sed -i '/^unprivileged: 1/d' /etc/pve/lxc/<container-id>.conf" \
        "$(translate "This removes the 'unprivileged: 1' line from the config")" \
        "$(translate "Example: sed -i '/^unprivileged: 1/d' /etc/pve/lxc/110.conf")"

    show_command "6" \
        "$(translate "Add explicit privileged flag (optional but recommended):")" \
        "echo 'unprivileged: 0' >> /etc/pve/lxc/<container-id>.conf" \
        "$(translate "This explicitly marks the container as privileged")"

    show_command "7" \
        "$(translate "Start the converted container:")" \
        "pct start <container-id>" \
        "$(translate "The container should now start as privileged")"

    show_command "8" \
        "$(translate "Verify the conversion:")" \
        "pct config <container-id> | grep unprivileged" \
        "$(translate "Should show 'unprivileged: 0' or no unprivileged line")"
    
    echo -e "${TAB}${BL}------------------------------------------------------------------------${CL}"
    echo -e 
    echo -e 
    echo -e "${TAB}${BOLD}$(translate "SECURITY CONSIDERATIONS:")${CL}"
    echo -e
    echo -e "${TAB}${RD}• $(translate "Privileged containers can access host devices directly")${CL}"
    echo -e "${TAB}${RD}• $(translate "Root inside container = root on host system")${CL}"
    echo -e "${TAB}${RD}• $(translate "Use only when unprivileged containers cannot meet your needs")${CL}"
    echo -e "${TAB}${RD}• $(translate "Consider security implications for production environments")${CL}"
    echo -e
    echo -e
    
    echo -e "${TAB}${BOLD}$(translate "TROUBLESHOOTING:")${CL}"
    echo -e
    echo -e "${TAB}${BGN}$(translate "If container won't start:")${CL} ${YW}Check /var/log/pve/tasks/ for detailed error messages${CL}"
    echo -e "${TAB}${BGN}$(translate "To revert changes:")${CL} ${YW}cp /etc/pve/lxc/<container-id>.conf.bak /etc/pve/lxc/<container-id>.conf${CL}"
    echo -e "${TAB}${BGN}$(translate "If config issues occur:")${CL} ${YW}Manually edit /etc/pve/lxc/<container-id>.conf${CL}"
    echo -e
    echo -e

    
    echo -e 
    msg_success "$(translate "Press Enter to return to menu...")"
    echo -e 
    read -r
}

show_lxc_conversion_manual_menu() {
    while true; do
        CHOICE=$(dialog --title "$(translate "LXC Conversion Manual Guides")" \
            --menu "$(translate "Select conversion guide:")" 18 70 10 \
            "1" "$(translate "Convert Privileged to Unprivileged")" \
            "2" "$(translate "Convert Unprivileged to Privileged")" \
            "3" "$(translate "Return to Main Menu")" \
            3>&1 1>&2 2>&3)
        
        case $CHOICE in
            1) show_privileged_to_unprivileged_guide ;;
            2) show_unprivileged_to_privileged_guide ;;
            3) return ;;
            *) return ;;
        esac
    done
}

# Main execution
show_lxc_conversion_manual_menu
