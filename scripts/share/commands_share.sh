#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.5
# Last Updated: 04/08/2025
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

show_nfs_server_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "NFS Server Installation Guide")"
    
    msg_info2 "$(translate "Manual commands to install NFS server in an LXC. Remember to substitute the highlighted values.")"
    echo -e 
    
    show_command "1" \
        "$(translate "Update package list:")" \
        "apt-get update" \
        "" \
        ""
    
    show_command "2" \
        "$(translate "Install NFS server packages:")" \
        "apt-get install -y nfs-kernel-server nfs-common rpcbind" \
        "" \
        ""
    
    show_command "3" \
        "$(translate "Create the export directory:")" \
        "mkdir -p ${CUS}/mnt/nfs_export${CL}" \
        "$(translate "You can change /mnt/nfs_export to your preferred path.")" \
        ""
    
    show_command "4" \
        "$(translate "Set permissions for the directory:")" \
        "chmod 755 ${CUS}/mnt/nfs_export${CL}" \
        "" \
        ""
    
    show_command "5" \
        "$(translate "Configure exports:")" \
        "echo '${CUS}/mnt/nfs_export${CL} ${CUS}192.168.1.0/24${CL}(rw,sync,no_subtree_check,no_root_squash)' >> /etc/exports" \
        "$(translate "Replace the directory path and the network IP with your own values.")" \
        ""
    
    show_command "6" \
        "$(translate "Apply export configuration:")" \
        "exportfs -ra" \
        "" \
        ""
    
    show_command "7" \
        "$(translate "Restart NFS service:")" \
        "systemctl restart nfs-kernel-server" \
        "" \
        ""
        
    show_command "8" \
        "$(translate "Enable and start services:")" \
        "systemctl enable rpcbind nfs-kernel-server" \
        "$(translate "Ensure services start on boot.")" \
        ""
    
    show_command "9" \
        "$(translate "Verify installation:")" \
        "showmount -e localhost" \
        "" \
        ""
    
    show_command "10" \
        "$(translate "Verify service status:")" \
        "systemctl status nfs-kernel-server" \
        "" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Additional Information:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Config file:")${CL} ${BL}/etc/exports${CL}"
    echo -e "${TAB}${BGN}$(translate "Service name:")${CL} ${BL}nfs-kernel-server${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_samba_server_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Samba Server Installation Guide")"
    
    msg_info2 "$(translate "Manual commands to install Samba server in an LXC. Remember to substitute the highlighted values.")"
    echo -e
    
    show_command "1" \
        "$(translate "Update package list:")" \
        "apt-get update" \
        "" \
        ""
    
    show_command "2" \
        "$(translate "Install Samba packages:")" \
        "apt-get install -y samba samba-common-bin acl" \
        "" \
        ""
    
    show_command "3" \
        "$(translate "Create the share directory:")" \
        "mkdir -p ${CUS}/mnt/samba_share${CL}" \
        "$(translate "You can change /mnt/samba_share to your preferred path.")" \
        ""
    
    show_command "4" \
        "$(translate "Set permissions for the directory:")" \
        "chmod 755 ${CUS}/mnt/samba_share${CL}" \
        "" \
        ""
    
    show_command "5" \
        "$(translate "Create a Samba user:")" \
        "adduser --disabled-password --gecos '' ${CUS}sambauser${CL}" \
        "$(translate "You can change 'sambauser' to your preferred username.")" \
        ""

    show_command "6" \
        "$(translate "Set the Samba password for the user:")" \
        "smbpasswd -a ${CUS}sambauser${CL}" \
        "$(translate "You will be prompted to enter and confirm a new password for the account.")" \
        ""
    
    show_command "7" \
        "$(translate "Configure the Samba share:")" \
        "cat >> /etc/samba/smb.conf << EOF
[shared]
    comment = Shared folder
    path = ${CUS}/mnt/samba_share${CL}
    read only = no
    browseable = yes
    valid users = ${CUS}sambauser${CL}
    create mask = 0664
    directory mask = 0775
EOF" \
        "$(translate "Replace 'path' and 'valid users' with your chosen values.")" \
        ""
    
    show_command "8" \
        "$(translate "Restart the Samba service:")" \
        "systemctl restart smbd" \
        "" \
        ""
    
    show_command "9" \
        "$(translate "Enable the Samba service:")" \
        "systemctl enable smbd" \
        "" \
        ""
    
    show_command "10" \
        "$(translate "Verify installation:")" \
        "smbclient -L localhost -U ${CUS}sambauser${CL}" \
        "$(translate "Test share listing and service status. You will be prompted for a password.")" \
        ""
        
    show_command "11" \
        "$(translate "Verify service status:")" \
        "systemctl status smbd" \
        "" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Connection Examples:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Windows:")${CL} ${YW}\\\\<server-ip>\\shared${CL}"
    echo -e "${TAB}${BGN}$(translate "Linux:")${CL} ${YW}smbclient //server-ip/shared -U sambauser${CL}"
    echo -e "${TAB}${BGN}$(translate "Mount:")${CL} ${YW}mount -t cifs //server-ip/shared /mnt/point -o username=sambauser${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_nfs_client_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "NFS Client Configuration Guide")"
    
    msg_info2 "$(translate "Manual commands to configure an NFS client in an LXC. Remember to substitute the highlighted values.")"
    echo -e
    
    show_command "1" \
        "$(translate "Update package list:")" \
        "apt-get update" \
        "" \
        ""
    
    show_command "2" \
        "$(translate "Install NFS client packages:")" \
        "apt-get install -y nfs-common" \
        "" \
        ""

    show_command "3" \
        "$(translate "Create local mount point:")" \
        "mkdir -p ${CUS}/mnt/nfsmount${CL}" \
        "$(translate "Create the directory where the remote share will be mounted.")" \
        ""

    show_command "4" \
        "$(translate "Mount the NFS share manually:")" \
        "mount ${CUS}192.168.1.100${CL}:${CUS}/mnt/nfs_export${CL} ${CUS}/mnt/nfsmount${CL}" \
        "$(translate "Replace the IP, remote share path, and local mount point.")" \
        ""
    
    show_command "5" \
        "$(translate "Verify the mount:")" \
        "df -h | grep ${CUS}/mnt/nfsmount${CL}" \
        "" \
        ""

    show_command "6" \
        "$(translate "Add to fstab for automatic mounting on boot:")" \
        "echo '${CUS}192.168.1.100${CL}:${CUS}/mnt/nfs_export${CL} ${CUS}/mnt/nfsmount${CL} nfs defaults 0 0' >> /etc/fstab" \
        "$(translate "Makes the mount persistent. Replace the IP and paths with your own values.")" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Additional Information:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Config file:")${CL} ${BL}/etc/fstab${CL}"
    echo -e "${TAB}${BGN}$(translate "Service name:")${CL} ${BL}nfs-common${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_samba_client_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Samba Client Configuration Guide")"
    
    msg_info2 "$(translate "Manual commands to configure a Samba client in an LXC. Remember to substitute the highlighted values.")"
    echo -e
    
    show_command "1" \
        "$(translate "Update package list:")" \
        "apt-get update" \
        "" \
        ""
    
    show_command "2" \
        "$(translate "Install Samba client packages:")" \
        "apt-get install -y cifs-utils" \
        "" \
        ""
    
    show_command "3" \
        "$(translate "Create local mount point:")" \
        "mkdir -p ${CUS}/mnt/sambamount${CL}" \
        "$(translate "Create the directory where the remote share will be mounted.")" \
        ""
    
    show_command "4" \
        "$(translate "Mount the Samba share manually:")" \
        "mount -t cifs //${CUS}192.168.1.100${CL}/${CUS}shared${CL} ${CUS}/mnt/sambamount${CL} -o username=${CUS}sambauser${CL},domain=WORKGROUP" \
        "$(translate "Replace the IP, share name, and username. You will be prompted for a password.")" \
        ""

    show_command "5" \
        "$(translate "Verify the mount:")" \
        "df -h | grep ${CUS}/mnt/sambamount${CL}" \
        "" \
        ""

    show_command "6" \
        "$(translate "Add to fstab for automatic mounting on boot:")" \
        "echo '//${CUS}192.168.1.100${CL}/${CUS}shared${CL} ${CUS}/mnt/sambamount${CL} cifs defaults,username=${CUS}sambauser${CL},uid=1000,gid=1000 0 0' >> /etc/fstab" \
        "$(translate "This makes the mount persistent. Replace the IP, share name, and username.")" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Additional Information:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Config file:")${CL} ${BL}/etc/fstab${CL}"
    echo -e "${TAB}${BGN}$(translate "Service name:")${CL} ${BL}cifs-utils${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}


show_help_menu() {
    while true; do
        CHOICE=$(dialog --title "$(translate "Help & Information")" \
            --menu "$(translate "Select help topic:")" 22 70 12 \
            "0" "$(translate "How to Access an LXC Terminal")" \
            "1" "$(translate "NFS Server Installation")" \
            "2" "$(translate "Samba Server Installation")" \
            "3" "$(translate "NFS Client Configuration")" \
            "4" "$(translate "Samba Client Configuration")" \
            "5" "$(translate "Return to Main Menu")" \
            3>&1 1>&2 2>&3)
        
        case $CHOICE in
            0) show_how_to_enter_lxc ;;
            1) show_nfs_server_help ;;
            2) show_samba_server_help ;;
            3) show_nfs_client_help ;;
            4) show_samba_client_help ;;
            5) return ;;
            *) return ;;
        esac
    done
}
show_help_menu