#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.5
# Last Updated: 04/08/2025
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

show_how_to_enter_lxc() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "How to Access an LXC Terminal from Proxmox Host")"
    
    msg_info2 "$(translate "Use these commands on your Proxmox host to access an LXC container's terminal:")"
    echo -e 
    
    show_command "1" \
        "$(translate "Get a list of all your containers:")" \
        "pct list" \
        "" \
        ""

    show_command "2" \
        "$(translate "Enter the container's terminal")" \
        "pct enter ${CUS}<container-id>${CL}" \
        "$(translate "Replace <container-id> with the actual ID.")"\
        "$(translate "For example: pct enter 101")"

    show_command "3" \
        "$(translate "To exit the container's terminal, press:")" \
        "CTRL + D" \
        "" \
        ""
        
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_host_mount_resources_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Mount Remote Resources on Proxmox Host")"
    
    msg_info2 "$(translate "How to mount NFS and Samba shares directly on the Proxmox host. Proxmox already has the necessary tools installed.")"
    echo -e 

    echo -e "${BOLD}${BL}=== MOUNT NFS SHARE ===${CL}"
    echo -e
    
    show_command "1" \
        "$(translate "Create mount point:")" \
        "mkdir -p ${CUS}/mnt/nfs_share${CL}" \
        "$(translate "Replace with your preferred path.")" \
        ""

    show_command "2" \
        "$(translate "Mount NFS share:")" \
        "mount -t nfs ${CUS}192.168.1.100${CL}:${CUS}/path/to/share${CL} ${CUS}/mnt/nfs_share${CL}" \
        "$(translate "Replace IP and paths with your values.")" \
        ""

    show_command "3" \
        "$(translate "Make permanent (optional):")" \
        "echo '${CUS}192.168.1.100${CL}:${CUS}/path/to/share${CL} ${CUS}/mnt/nfs_share${CL} nfs4 rw,hard,intr,_netdev,rsize=1048576,wsize=1048576,timeo=600,retrans=2 0 0' >> /etc/fstab" \
        "$(translate "_netdev waits for network before mounting.")" \
        ""

    echo -e "${BOLD}${BL}=== MOUNT SAMBA SHARE ===${CL}"
    echo -e

    show_command "4" \
        "$(translate "Create mount point:")" \
        "mkdir -p ${CUS}/mnt/samba_share${CL}" \
        "$(translate "Replace with your preferred path.")" \
        ""

    show_command "5" \
        "$(translate "Mount Samba share:")" \
        "mount -t cifs //${CUS}192.168.1.100${CL}/${CUS}sharename${CL} ${CUS}/mnt/samba_share${CL} -o username=${CUS}user${CL}" \
        "$(translate "You will be prompted for password. Replace IP, share and user.")" \
        ""

    show_command "6" \
        "$(translate "Make permanent (optional):")" \
        "echo '//${CUS}192.168.1.100${CL}/${CUS}sharename${CL} ${CUS}/mnt/samba_share${CL} cifs username=${CUS}user${CL},password=${CUS}pass${CL},_netdev 0 0' >> /etc/fstab" \
        "$(translate "Replace with your credentials.")" \
        ""

    echo -e "${BOLD}${BL}=== CREATE LOCAL DIRECTORY ===${CL}"
    echo -e

    show_command "7" \
        "$(translate "Create directory:")" \
        "mkdir -p ${CUS}/mnt/local_share${CL}" \
        "$(translate "Creates a local directory on Proxmox host.")" \
        ""

    show_command "8" \
        "$(translate "Set permissions:")" \
        "chmod 755 ${CUS}/mnt/local_share${CL}" \
        "$(translate "Sets basic read/write permissions.")" \
        ""

    show_command "9" \
        "$(translate "Verify mounts:")" \
        "df -h" \
        "$(translate "Shows all mounted filesystems.")" \
        ""
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_host_to_lxc_mount_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Mount Host Directory to LXC Container")"
    
    msg_info2 "$(translate "How to mount a Proxmox host directory into an LXC container. Execute these commands on the Proxmox host.")"
    echo -e 
    
    show_command "1" \
        "$(translate "Add mount point to container:")" \
        "pct set ${CUS}<container-id>${CL} -mp0 ${CUS}/host/directory${CL},mp=${CUS}/container/path${CL},backup=0,shared=1" \
        "$(translate "Replace container-id, host directory and container path.")" \
        "$(translate "Example: pct set 101 -mp0 /mnt/shared,mp=/mnt/shared,,backup=0,shared=1")"

    show_command "2" \
        "$(translate "Restart container:")" \
        "pct reboot ${CUS}<container-id>${CL}" \
        "$(translate "Required to activate the mount point.")" \
        ""

    show_command "3" \
        "$(translate "Verify mount inside container:")" \
        "pct enter ${CUS}<container-id>${CL}
    df -h | grep ${CUS}/container/path${CL}" \
        "$(translate "Check if the directory is mounted.")" \
        ""

    show_command "4" \
        "$(translate "Remove mount point (if needed):")" \
        "pct set ${CUS}<container-id>${CL} --delete mp0" \
        "$(translate "Removes the mount point. Use mp1, mp2, etc. for other mounts.")" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Notes:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Mount indices:")${CL} ${BL}Use mp0, mp1, mp2, etc. for multiple mounts${CL}"
    echo -e "${TAB}${BGN}$(translate "Permissions:")${CL} ${BL}May need adjustment depending on directory type${CL}"
    echo -e "${TAB}${BGN}$(translate "Container types:")${CL} ${BL}Works with both privileged and unprivileged containers${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_nfs_server_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "NFS Server Installation")"
    
    msg_info2 "$(translate "How to install and configure an NFS server in an LXC container.")"
    echo -e 
    
    show_command "1" \
        "$(translate "Update and install packages:")" \
        "apt-get update && apt-get install -y nfs-kernel-server" \
        "" \
        ""

    show_command "2" \
        "$(translate "Create export directory:")" \
        "mkdir -p ${CUS}/mnt/nfs_export${CL}" \
        "$(translate "Replace with your preferred path.")" \
        ""
    
    show_command "3" \
        "$(translate "Set directory permissions:")" \
        "chmod 755 ${CUS}/mnt/nfs_export${CL}" \
        "" \
        ""
    
    show_command "4.1" \
        "$(translate "Configure exports (safe root_squash):")" \
        "echo '${CUS}/mnt/nfs_export${CL} ${CUS}192.168.1.0/24${CL}(rw,sync,no_subtree_check,root_squash)' >> /etc/exports" \
        "$(translate "Replace directory path and network range.")" \
        ""

    show_command "4.2" \
        "$(translate "Or Configure exports (map all users):")" \
        "echo '${CUS}/mnt/nfs_export${CL} ${CUS}192.168.1.0/24${CL}(rw,sync,no_subtree_check,all_squash,anonuid=0,anongid=0)' >> /etc/exports" \
        "$(translate "Replace directory path and network range.")" \
        ""

    
    show_command "5" \
        "$(translate "Apply configuration:")" \
        "exportfs -ra" \
        "" \
        ""
    
    show_command "6" \
        "$(translate "Start and enable service:")" \
        "systemctl restart nfs-kernel-server
    systemctl enable nfs-kernel-server" \
        "" \
        ""
    
    show_command "7" \
        "$(translate "Verify exports:")" \
        "showmount -e localhost" \
        "$(translate "Shows available NFS exports.")" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Export Options:")${CL}"
    echo -e "${TAB}${BGN}$(translate "rw:")${CL} ${BL}Read-write access${CL}"
    echo -e "${TAB}${BGN}$(translate "sync:")${CL} ${BL}Synchronous writes${CL}"
    echo -e "${TAB}${BGN}$(translate "no_subtree_check:")${CL} ${BL}Improves performance${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_samba_server_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Samba Server Installation")"
    
    msg_info2 "$(translate "How to install and configure a Samba server in an LXC container.")"
    echo -e
    
    show_command "1" \
        "$(translate "Update and install packages:")" \
        "apt-get update && apt-get install -y samba" \
        "" \
        ""
    
    show_command "2" \
        "$(translate "Create share directory:")" \
        "mkdir -p ${CUS}/mnt/samba_share${CL}" \
        "$(translate "Replace with your preferred path.")" \
        ""
    
    show_command "3" \
        "$(translate "Set directory permissions:")" \
        "chmod 755 ${CUS}/mnt/samba_share${CL}" \
        "" \
        ""
    
    show_command "4" \
        "$(translate "Create Samba user:")" \
        "adduser ${CUS}sambauser${CL}
    smbpasswd -a ${CUS}sambauser${CL}" \
        "$(translate "Replace with your username. You'll be prompted for password.")" \
        ""
    
    show_command "5" \
        "$(translate "Configure share:")" \
        "cat >> /etc/samba/smb.conf << EOF
[shared]
    comment = Shared folder
    path = ${CUS}/mnt/samba_share${CL}
    read only = no
    browseable = yes
    valid users = ${CUS}sambauser${CL}
EOF" \
        "$(translate "Replace path and username.")" \
        ""
    
    show_command "6" \
        "$(translate "Restart and enable service:")" \
        "systemctl restart smbd
    systemctl enable smbd" \
        "" \
        ""
    
    show_command "7" \
        "$(translate "Test configuration:")" \
        "smbclient -L localhost -U ${CUS}sambauser${CL}" \
        "$(translate "Lists available shares. You'll be prompted for password.")" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Connection Examples:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Windows:")${CL} ${YW}\\\\<server-ip>\\shared${CL}"
    echo -e "${TAB}${BGN}$(translate "Linux:")${CL} ${YW}smbclient //server-ip/shared -U sambauser${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_nfs_client_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "NFS Client Configuration")"
    
    msg_info2 "$(translate "How to configure an NFS client in an LXC container.")"
    echo -e
    
    show_command "1" \
        "$(translate "Update and install packages:")" \
        "apt-get update && apt-get install -y nfs-common" \
        "" \
        ""

    show_command "2" \
        "$(translate "Create mount point:")" \
        "mkdir -p ${CUS}/mnt/nfsmount${CL}" \
        "$(translate "Replace with your preferred path.")" \
        ""

    show_command "3" \
        "$(translate "Mount NFS share:")" \
        "mount -t nfs ${CUS}192.168.1.100${CL}:${CUS}/mnt/nfs_export${CL} ${CUS}/mnt/nfsmount${CL}" \
        "$(translate "Replace server IP and paths.")" \
        ""

    show_command "4" \
        "$(translate "Test access:")" \
        "ls -la ${CUS}/mnt/nfsmount${CL}" \
        "$(translate "Verify you can access the mounted share.")" \
        ""

    show_command "5" \
        "$(translate "Make permanent (optional):")" \
        "echo '${CUS}192.168.1.100${CL}:${CUS}/path/to/share${CL} ${CUS}/mnt/nfs_share${CL} nfs4 rw,hard,intr,_netdev,rsize=1048576,wsize=1048576,timeo=600,retrans=2 0 0' >> /etc/fstab" \
        "$(translate "Replace with your server IP and paths.")" \
        ""
    
    show_command "6" \
        "$(translate "Verify mount:")" \
        "df -h | grep nfs" \
        "$(translate "Shows NFS mounts.")" \
        ""
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_samba_client_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Samba Client Configuration")"
    
    msg_info2 "$(translate "How to configure a Samba client in an LXC container.")"
    echo -e
    
    show_command "1" \
        "$(translate "Update and install packages:")" \
        "apt-get update && apt-get install -y cifs-utils" \
        "" \
        ""

    show_command "2" \
        "$(translate "Create mount point:")" \
        "mkdir -p ${CUS}/mnt/sambamount${CL}" \
        "$(translate "Replace with your preferred path.")" \
        ""

    show_command "3" \
        "$(translate "Mount Samba share:")" \
        "mount -t cifs //${CUS}192.168.1.100${CL}/${CUS}shared${CL} ${CUS}/mnt/sambamount${CL} -o username=${CUS}sambauser${CL}" \
        "$(translate "Replace server IP, share name and username. You'll be prompted for password.")" \
        ""

    show_command "4" \
        "$(translate "Test access:")" \
        "ls -la ${CUS}/mnt/sambamount${CL}" \
        "$(translate "Verify you can access the mounted share.")" \
        ""

    show_command "5" \
        "$(translate "Create credentials file (optional):")" \
        "cat > /etc/samba/credentials << EOF
username=${CUS}sambauser${CL}
password=${CUS}your_password${CL}
EOF
chmod 600 /etc/samba/credentials" \
        "$(translate "Secure way to store credentials.")" \
        ""

    show_command "6" \
        "$(translate "Mount with credentials file:")" \
        "mount -t cifs //${CUS}192.168.1.100${CL}/${CUS}shared${CL} ${CUS}/mnt/sambamount${CL} -o credentials=/etc/samba/credentials" \
        "$(translate "No password prompt needed.")" \
        ""

    show_command "7" \
        "$(translate "Make permanent (optional):")" \
        "echo '//${CUS}192.168.1.100${CL}/${CUS}shared${CL} ${CUS}/mnt/sambamount${CL} cifs credentials=/etc/samba/credentials,_netdev 0 0' >> /etc/fstab" \
        "$(translate "Replace with your values.")" \
        ""
    
    show_command "8" \
        "$(translate "Verify mount:")" \
        "df -h | grep cifs" \
        "$(translate "Shows CIFS/Samba mounts.")" \
        ""
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_help_menu() {
    while true; do
        CHOICE=$(dialog --title "$(translate "Help & Information")" \
            --menu "$(translate "Select help topic:")" 24 80 14 \
            "0" "$(translate "How to Access an LXC Terminal")" \
            "1" "$(translate "Mount Remote Resources on Proxmox Host")" \
            "2" "$(translate "Mount Host Directory to LXC Container")" \
            "3" "$(translate "NFS Server Installation")" \
            "4" "$(translate "Samba Server Installation")" \
            "5" "$(translate "NFS Client Configuration")" \
            "6" "$(translate "Samba Client Configuration")" \
            "7" "$(translate "Return to Main Menu")" \
            3>&1 1>&2 2>&3)
        
        case $CHOICE in
            0) show_how_to_enter_lxc ;;
            1) show_host_mount_resources_help ;;
            2) show_host_to_lxc_mount_help ;;
            3) show_nfs_server_help ;;
            4) show_samba_server_help ;;
            5) show_nfs_client_help ;;
            6) show_samba_client_help ;;
            7) return ;;
            *) return ;;
        esac
    done
}
show_help_menu
