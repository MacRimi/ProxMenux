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

show_host_mount_resources_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Mount Remote Resources on Proxmox Host Guide")"
    
    msg_info2 "$(translate "Manual commands to mount NFS, Samba, and local resources directly on the Proxmox host. Execute these commands on the Proxmox host.")"
    echo -e 

    echo -e "${BOLD}${BL}=== NFS MOUNT ON HOST ===${CL}"
    echo -e
    
    show_command "1" \
        "$(translate "Install NFS client on host:")" \
        "apt-get update && apt-get install -y nfs-common" \
        "" \
        ""

    show_command "2" \
        "$(translate "Create host mount point:")" \
        "mkdir -p ${CUS}/mnt/host_nfs${CL}" \
        "$(translate "Replace /mnt/host_nfs with your preferred path.")" \
        ""

    show_command "3" \
        "$(translate "Create shared group on host:")" \
        "groupadd -g 101000 sharedfiles" \
        "$(translate "Creates universal group for NFS access.")" \
        ""

    show_command "4" \
        "$(translate "Mount NFS share on host:")" \
        "mount -t nfs ${CUS}192.168.1.100${CL}:${CUS}/mnt/nfs_export${CL} ${CUS}/mnt/host_nfs${CL}" \
        "$(translate "Replace server IP and remote path.")" \
        ""

    show_command "5" \
        "$(translate "Set host mount permissions:")" \
        "chgrp sharedfiles ${CUS}/mnt/host_nfs${CL}
chmod 2775 ${CUS}/mnt/host_nfs${CL}" \
        "$(translate "Ensures proper group access and inheritance.")" \
        ""

    echo -e "${BOLD}${BL}=== SAMBA/CIFS MOUNT ON HOST ===${CL}"
    echo -e

    show_command "6" \
        "$(translate "Install CIFS client on host:")" \
        "apt-get install -y cifs-utils" \
        "" \
        ""

    show_command "7" \
        "$(translate "Create Samba mount point:")" \
        "mkdir -p ${CUS}/mnt/host_samba${CL}" \
        "$(translate "Replace /mnt/host_samba with your preferred path.")" \
        ""

    show_command "8" \
        "$(translate "Create credentials file:")" \
        "cat > /etc/samba/host_credentials << EOF
username=${CUS}sambauser${CL}
password=${CUS}your_password${CL}
domain=WORKGROUP
EOF
chmod 600 /etc/samba/host_credentials" \
        "$(translate "Secure storage for Samba credentials.")" \
        ""

    show_command "9" \
        "$(translate "Mount Samba share on host:")" \
        "mount -t cifs //${CUS}192.168.1.100${CL}/${CUS}shared${CL} ${CUS}/mnt/host_samba${CL} -o credentials=/etc/samba/host_credentials,uid=0,gid=101000,file_mode=0664,dir_mode=2775" \
        "$(translate "Uses universal group GID 101000.")" \
        ""

    echo -e "${BOLD}${BL}=== LOCAL BIND MOUNT ON HOST ===${CL}"
    echo -e

    show_command "10" \
        "$(translate "Create source and target directories:")" \
        "mkdir -p ${CUS}/source/directory${CL}
mkdir -p ${CUS}/mnt/host_bind${CL}" \
        "$(translate "Create both source and mount point directories.")" \
        ""

    show_command "11" \
        "$(translate "Set up bind mount:")" \
        "mount --bind ${CUS}/source/directory${CL} ${CUS}/mnt/host_bind${CL}" \
        "$(translate "Creates a bind mount of local directory.")" \
        ""

    show_command "12" \
        "$(translate "Set universal permissions:")" \
        "chgrp sharedfiles ${CUS}/mnt/host_bind${CL}
chmod 2775 ${CUS}/mnt/host_bind${CL}" \
        "" \
        ""

    echo -e "${BOLD}${BL}=== MAKE MOUNTS PERMANENT ===${CL}"
    echo -e

    show_command "13" \
        "$(translate "Add NFS to fstab:")" \
        "echo '${CUS}192.168.1.100${CL}:${CUS}/mnt/nfs_export${CL} ${CUS}/mnt/host_nfs${CL} nfs defaults,_netdev 0 0' >> /etc/fstab" \
        "$(translate "_netdev waits for network before mounting.")" \
        ""

    show_command "14" \
        "$(translate "Add Samba to fstab:")" \
        "echo '//${CUS}192.168.1.100${CL}/${CUS}shared${CL} ${CUS}/mnt/host_samba${CL} cifs credentials=/etc/samba/host_credentials,uid=0,gid=101000,file_mode=0664,dir_mode=2775,_netdev 0 0' >> /etc/fstab" \
        "" \
        ""

    show_command "15" \
        "$(translate "Add bind mount to fstab:")" \
        "echo '${CUS}/source/directory${CL} ${CUS}/mnt/host_bind${CL} none bind 0 0' >> /etc/fstab" \
        "" \
        ""

    show_command "16" \
        "$(translate "Test fstab configuration:")" \
        "mount -a" \
        "$(translate "Mounts all entries in fstab to verify configuration.")" \
        ""

    show_command "17" \
        "$(translate "Verify all mounts:")" \
        "df -h | grep -E '(host_nfs|host_samba|host_bind)'" \
        "" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Important Notes:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Universal Group:")${CL} ${BL}GID 101000 works with all container types${CL}"
    echo -e "${TAB}${BGN}$(translate "Permissions:")${CL} ${BL}2775 = rwxrwsr-x (group sticky bit)${CL}"
    echo -e "${TAB}${BGN}$(translate "Network mounts:")${CL} ${BL}Use _netdev option in fstab${CL}"
    echo -e "${TAB}${BGN}$(translate "Security:")${CL} ${BL}Protect credential files with chmod 600${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_host_to_lxc_mount_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Mount Host Directory to LXC Container Guide")"
    
    msg_info2 "$(translate "Manual commands to mount a host directory into an LXC container. Execute these commands on the Proxmox host.")"
    echo -e 
    
    show_command "1" \
        "$(translate "Create the shared group on the host:")" \
        "groupadd -g 1000 sharedfiles" \
        "$(translate "Creates a group with GID 1000 for shared access.")" \
        ""

    show_command "2" \
        "$(translate "Create the host directory:")" \
        "mkdir -p ${CUS}/mnt/shared_data${CL}" \
        "$(translate "Replace /mnt/shared_data with your preferred path.")" \
        ""

    show_command "3" \
        "$(translate "Set ownership and permissions:")" \
        "chown root:sharedfiles ${CUS}/mnt/shared_data${CL}
chmod 2775 ${CUS}/mnt/shared_data${CL}" \
        "$(translate "Sets group ownership and sticky bit for inheritance.")" \
        ""

    show_command "4" \
        "$(translate "Add bind mount to LXC container:")" \
        "pct set ${CUS}<container-id>${CL} -mp0 ${CUS}/mnt/shared_data${CL},mp=${CUS}/mnt/shared${CL},backup=0,acl=1" \
        "$(translate "Replace <container-id>, host path, and container mount point.")" \
        "$(translate "Example: pct set 101 -mp0 /mnt/shared_data,mp=/mnt/shared,backup=0,acl=1")"

    show_command "5" \
        "$(translate "Enter the container to configure access:")" \
        "pct enter ${CUS}<container-id>${CL}" \
        "" \
        ""

    show_command "6" \
        "$(translate "Inside the container - create matching group:")" \
        "groupadd -g 1000 sharedfiles" \
        "$(translate "Creates the same group inside the container.")" \
        ""

    show_command "7" \
        "$(translate "Add users to the shared group:")" \
        "usermod -aG sharedfiles www-data
usermod -aG sharedfiles root" \
        "$(translate "Add any users that need access to the shared directory.")" \
        ""

    show_command "8" \
        "$(translate "Set container directory permissions:")" \
        "chgrp sharedfiles ${CUS}/mnt/shared${CL}
chmod 2775 ${CUS}/mnt/shared${CL}" \
        "" \
        ""

    show_command "9" \
        "$(translate "Test access (inside container):")" \
        "su - www-data -c 'touch ${CUS}/mnt/shared${CL}/test_file.txt'" \
        "$(translate "Verify that users can create files in the shared directory.")" \
        ""

    show_command "10" \
        "$(translate "Restart container to activate mount:")" \
        "exit
pct reboot ${CUS}<container-id>${CL}" \
        "$(translate "Exit container first, then restart from host.")" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Important Notes:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Mount point index:")${CL} ${BL}Use mp0, mp1, mp2, etc. for multiple mounts${CL}"
    echo -e "${TAB}${BGN}$(translate "Permissions:")${CL} ${BL}2775 = rwxrwsr-x (group sticky bit)${CL}"
    echo -e "${TAB}${BGN}$(translate "ACL support:")${CL} ${BL}acl=1 enables advanced permissions${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_nfs_server_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "NFS Server Installation Guide")"
    
    msg_info2 "$(translate "Manual commands to install NFS server in an LXC with universal compatibility. Remember to substitute the highlighted values.")"
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
        "$(translate "Create universal shared group:")" \
        "groupadd -g 101000 sharedfiles" \
        "$(translate "Creates group with GID 101000 for universal compatibility.")" \
        ""

    show_command "4" \
        "$(translate "Add existing users to shared group:")" \
        "usermod -aG sharedfiles root
usermod -aG sharedfiles www-data" \
        "$(translate "Add all users that need NFS access.")" \
        ""

    show_command "5" \
        "$(translate "Create remapped users for unprivileged containers:")" \
        "useradd -u 100000 -g sharedfiles -s /bin/false -M unpriv_root
useradd -u 100033 -g sharedfiles -s /bin/false -M unpriv_www" \
        "$(translate "Creates mapped users (original UID + 100000).")" \
        ""
    
    show_command "6" \
        "$(translate "Create the export directory:")" \
        "mkdir -p ${CUS}/mnt/nfs_export${CL}" \
        "$(translate "You can change /mnt/nfs_export to your preferred path.")" \
        ""
    
    show_command "7" \
        "$(translate "Set universal permissions:")" \
        "chown root:sharedfiles ${CUS}/mnt/nfs_export${CL}
chmod 2775 ${CUS}/mnt/nfs_export${CL}" \
        "$(translate "Sets group ownership and sticky bit for inheritance.")" \
        ""
    
    show_command "8" \
        "$(translate "Configure exports with universal compatibility:")" \
        "echo '${CUS}/mnt/nfs_export${CL} ${CUS}192.168.1.0/24${CL}(rw,sync,no_subtree_check,all_squash,anonuid=0,anongid=101000)' >> /etc/exports" \
        "$(translate "Replace directory path and network. Uses all_squash for universal access.")" \
        ""
    
    show_command "9" \
        "$(translate "Apply export configuration:")" \
        "exportfs -ra" \
        "" \
        ""
    
    show_command "10" \
        "$(translate "Restart NFS service:")" \
        "systemctl restart nfs-kernel-server" \
        "" \
        ""
        
    show_command "11" \
        "$(translate "Enable and start services:")" \
        "systemctl enable rpcbind nfs-kernel-server" \
        "$(translate "Ensure services start on boot.")" \
        ""
    
    show_command "12" \
        "$(translate "Verify installation:")" \
        "showmount -e localhost" \
        "" \
        ""
    
    show_command "13" \
        "$(translate "Test file creation:")" \
        "su - www-data -c 'touch ${CUS}/mnt/nfs_export${CL}/test_nfs.txt'" \
        "$(translate "Verify that users can create files in the export.")" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Universal Compatibility Options:")${CL}"
    echo -e "${TAB}${BGN}$(translate "all_squash:")${CL} ${BL}Maps all users to anonymous user${CL}"
    echo -e "${TAB}${BGN}$(translate "anonuid=0:")${CL} ${BL}Anonymous user = root (UID 0)${CL}"
    echo -e "${TAB}${BGN}$(translate "anongid=101000:")${CL} ${BL}Anonymous group = sharedfiles (GID 101000)${CL}"
    echo -e "${TAB}${BGN}$(translate "Result:")${CL} ${BL}Works with privileged and unprivileged containers${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_samba_server_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Samba Server Installation Guide")"
    
    msg_info2 "$(translate "Manual commands to install Samba server in an LXC with shared group support. Remember to substitute the highlighted values.")"
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
        "$(translate "Create shared group:")" \
        "groupadd -g 1000 sharedfiles" \
        "$(translate "Creates group with GID 1000 for shared access.")" \
        ""
    
    show_command "4" \
        "$(translate "Create the share directory:")" \
        "mkdir -p ${CUS}/mnt/samba_share${CL}" \
        "$(translate "You can change /mnt/samba_share to your preferred path.")" \
        ""
    
    show_command "5" \
        "$(translate "Set directory permissions:")" \
        "chown root:sharedfiles ${CUS}/mnt/samba_share${CL}
chmod 2775 ${CUS}/mnt/samba_share${CL}" \
        "$(translate "Sets group ownership and sticky bit for inheritance.")" \
        ""
    
    show_command "6" \
        "$(translate "Create a Samba user:")" \
        "adduser --disabled-password --gecos '' ${CUS}sambauser${CL}
usermod -aG sharedfiles ${CUS}sambauser${CL}" \
        "$(translate "Creates user and adds to shared group.")" \
        ""

    show_command "7" \
        "$(translate "Set the Samba password for the user:")" \
        "smbpasswd -a ${CUS}sambauser${CL}" \
        "$(translate "You will be prompted to enter and confirm a new password.")" \
        ""
    
    show_command "8" \
        "$(translate "Configure the Samba share:")" \
        "cat >> /etc/samba/smb.conf << EOF
[shared]
    comment = Shared folder
    path = ${CUS}/mnt/samba_share${CL}
    read only = no
    browseable = yes
    valid users = @sharedfiles
    force group = sharedfiles
    create mask = 0664
    directory mask = 2775
    force create mode = 0664
    force directory mode = 2775
EOF" \
        "$(translate "Uses @sharedfiles group for access control.")" \
        ""
    
    show_command "9" \
        "$(translate "Restart the Samba service:")" \
        "systemctl restart smbd" \
        "" \
        ""
    
    show_command "10" \
        "$(translate "Enable the Samba service:")" \
        "systemctl enable smbd" \
        "" \
        ""
    
    show_command "11" \
        "$(translate "Verify installation:")" \
        "smbclient -L localhost -U ${CUS}sambauser${CL}" \
        "$(translate "Test share listing. You will be prompted for password.")" \
        ""
        
    show_command "12" \
        "$(translate "Test file creation:")" \
        "su - ${CUS}sambauser${CL} -c 'touch ${CUS}/mnt/samba_share${CL}/test_samba.txt'" \
        "$(translate "Verify that the user can create files in the share.")" \
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
    
    msg_info2 "$(translate "Manual commands to configure an NFS client in an LXC with proper group mapping. Remember to substitute the highlighted values.")"
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
        "$(translate "Create matching shared group:")" \
        "groupadd -g 1000 sharedfiles" \
        "$(translate "Creates group that matches the NFS server group mapping.")" \
        ""

    show_command "4" \
        "$(translate "Add users to shared group:")" \
        "usermod -aG sharedfiles root
usermod -aG sharedfiles www-data" \
        "$(translate "Add users that need access to NFS files.")" \
        ""

    show_command "5" \
        "$(translate "Create local mount point:")" \
        "mkdir -p ${CUS}/mnt/nfsmount${CL}" \
        "$(translate "Create the directory where the remote share will be mounted.")" \
        ""

    show_command "6" \
        "$(translate "Mount the NFS share manually:")" \
        "mount -t nfs ${CUS}192.168.1.100${CL}:${CUS}/mnt/nfs_export${CL} ${CUS}/mnt/nfsmount${CL}" \
        "$(translate "Replace the IP, remote share path, and local mount point.")" \
        ""
    
    show_command "7" \
        "$(translate "Set local mount permissions:")" \
        "chgrp sharedfiles ${CUS}/mnt/nfsmount${CL}
chmod 2775 ${CUS}/mnt/nfsmount${CL}" \
        "$(translate "Ensures proper group access to the mounted share.")" \
        ""

    show_command "8" \
        "$(translate "Test access:")" \
        "su - www-data -c 'touch ${CUS}/mnt/nfsmount${CL}/test_client.txt'" \
        "$(translate "Verify that users can create files on the NFS share.")" \
        ""
    
    show_command "9" \
        "$(translate "Verify the mount:")" \
        "df -h | grep ${CUS}/mnt/nfsmount${CL}" \
        "" \
        ""

    show_command "10" \
        "$(translate "Add to fstab for automatic mounting:")" \
        "echo '${CUS}192.168.1.100${CL}:${CUS}/mnt/nfs_export${CL} ${CUS}/mnt/nfsmount${CL} nfs defaults,_netdev 0 0' >> /etc/fstab" \
        "$(translate "_netdev ensures mount waits for network. Replace IPs and paths.")" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Universal Compatibility:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Privileged containers:")${CL} ${BL}Direct UID/GID mapping${CL}"
    echo -e "${TAB}${BGN}$(translate "Unprivileged containers:")${CL} ${BL}all_squash maps to root:sharedfiles${CL}"
    echo -e "${TAB}${BGN}$(translate "Group GID:")${CL} ${BL}Use 1000 for privileged, auto-mapped for unprivileged${CL}"
    
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_samba_client_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Samba Client Configuration Guide")"
    
    msg_info2 "$(translate "Manual commands to configure a Samba client in an LXC with proper group mapping. Remember to substitute the highlighted values.")"
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
        "$(translate "Create matching shared group:")" \
        "groupadd -g 1000 sharedfiles" \
        "$(translate "Creates group that matches the Samba server group.")" \
        ""

    show_command "4" \
        "$(translate "Add users to shared group:")" \
        "usermod -aG sharedfiles root
usermod -aG sharedfiles www-data" \
        "$(translate "Add users that need access to Samba files.")" \
        ""
    
    show_command "5" \
        "$(translate "Create local mount point:")" \
        "mkdir -p ${CUS}/mnt/sambamount${CL}" \
        "$(translate "Create the directory where the remote share will be mounted.")" \
        ""

    show_command "6" \
        "$(translate "Create credentials file (optional but recommended):")" \
        "cat > /etc/samba/credentials << EOF
username=${CUS}sambauser${CL}
password=${CUS}your_password${CL}
domain=WORKGROUP
EOF
chmod 600 /etc/samba/credentials" \
        "$(translate "Secure way to store Samba credentials.")" \
        ""
    
    show_command "7" \
        "$(translate "Mount the Samba share manually:")" \
        "mount -t cifs //${CUS}192.168.1.100${CL}/${CUS}shared${CL} ${CUS}/mnt/sambamount${CL} -o credentials=/etc/samba/credentials,uid=0,gid=1000,file_mode=0664,dir_mode=2775" \
        "$(translate "Uses credentials file and sets proper permissions.")" \
        ""

    show_command "8" \
        "$(translate "Alternative - mount with username prompt:")" \
        "mount -t cifs //${CUS}192.168.1.100${CL}/${CUS}shared${CL} ${CUS}/mnt/sambamount${CL} -o username=${CUS}sambauser${CL},uid=0,gid=1000,file_mode=0664,dir_mode=2775" \
        "$(translate "You will be prompted for password.")" \
        ""

    show_command "9" \
        "$(translate "Test access:")" \
        "su - www-data -c 'touch ${CUS}/mnt/sambamount${CL}/test_client.txt'" \
        "$(translate "Verify that users can create files on the Samba share.")" \
        ""

    show_command "10" \
        "$(translate "Verify the mount:")" \
        "df -h | grep ${CUS}/mnt/sambamount${CL}" \
        "" \
        ""

    show_command "11" \
        "$(translate "Add to fstab for automatic mounting:")" \
        "echo '//${CUS}192.168.1.100${CL}/${CUS}shared${CL} ${CUS}/mnt/sambamount${CL} cifs credentials=/etc/samba/credentials,uid=0,gid=1000,file_mode=0664,dir_mode=2775,_netdev 0 0' >> /etc/fstab" \
        "$(translate "_netdev ensures mount waits for network.")" \
        ""
    
    echo -e "${BOR}"
    echo -e "${BOLD}$(translate "Mount Options Explained:")${CL}"
    echo -e "${TAB}${BGN}$(translate "uid=0:")${CL} ${BL}Files owned by root${CL}"
    echo -e "${TAB}${BGN}$(translate "gid=1000:")${CL} ${BL}Files belong to sharedfiles group${CL}"
    echo -e "${TAB}${BGN}$(translate "file_mode=0664:")${CL} ${BL}Files: rw-rw-r--${CL}"
    echo -e "${TAB}${BGN}$(translate "dir_mode=2775:")${CL} ${BL}Directories: rwxrwsr-x (sticky bit)${CL}"
    
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
            "3" "$(translate "NFS Server Installation (Universal)")" \
            "4" "$(translate "Samba Server Installation (with Groups)")" \
            "5" "$(translate "NFS Client Configuration (with Groups)")" \
            "6" "$(translate "Samba Client Configuration (with Groups)")" \
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
