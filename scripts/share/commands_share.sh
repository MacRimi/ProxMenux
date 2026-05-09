#!/bin/bash

# ==========================================================
# ProxMenux - Storage & Share CLI Reference
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.6
# ==========================================================
# Description:
# Reference of the manual CLI commands behind the Storage &
# Share Manager flows (NFS / Samba / iSCSI client and server,
# bind mounts, Proxmox storage registration). Used as the
# Help & Info entry of the Storage & Share menu.
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

    echo -e "  ${DARK_GRAY}────────────────────────────────────────────────${CL}"
    echo -e "  ${BGN}${step}.${CL}  ${description}"
    echo ""
    while IFS= read -r line; do
        echo -e "${TAB}${line}"
    done <<< "$(echo -e "$command")"
    echo ""
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
        "$(translate "Enter the container terminal:")" \
        "pct enter ${CUS}<container-id>${CL}" \
        "$(translate "Replace <container-id> with the actual ID.")" \
        "$(translate "For example: pct enter 101")"

    show_command "3" \
        "$(translate "Exit the container terminal:")" \
        "exit" \
        "$(translate "Or press CTRL + D")" \
        ""

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_host_storage_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Host Storage (NFS / Samba via Proxmox)")"

    msg_info2 "$(translate "Current ProxMenux host scripts register remote shares as Proxmox storages using pvesm.")"
    msg_info2 "$(translate "This means Proxmox handles mount lifecycle natively (no manual /etc/fstab needed for NFS/CIFS host storages).")"
    echo -e

    echo -e "${BOLD}${BL}=== NFS AS PROXMOX STORAGE ===${CL}"
    echo -e

    show_command "1" \
        "$(translate "Add NFS storage:")" \
        "pvesm add nfs ${CUS}<storage-id>${CL} --server ${CUS}<nfs-server-ip>${CL} --export ${CUS}</export/path>${CL} --content ${CUS}import,backup,iso,vztmpl,images,snippets${CL}" \
        "$(translate "Use content types according to your use case.")" \
        "$(translate "Example: pvesm add nfs nfs-nas --server 192.168.1.50 --export /volume1/proxmox --content import,backup")"

    show_command "2" \
        "$(translate "List configured storages:")" \
        "pvesm status" \
        "$(translate "Shows status and type (nfs/cifs/dir/iscsi...).")" \
        ""

    show_command "3" \
        "$(translate "Remove NFS storage:")" \
        "pvesm remove ${CUS}<storage-id>${CL}" \
        "$(translate "Only removes storage definition, not remote data.")" \
        ""

    echo -e "${BOLD}${BL}=== SAMBA/CIFS AS PROXMOX STORAGE ===${CL}"
    echo -e

    show_command "4" \
        "$(translate "Add CIFS storage:")" \
        "pvesm add cifs ${CUS}<storage-id>${CL} --server ${CUS}<samba-server-ip>${CL} --share ${CUS}<share-name>${CL} --username ${CUS}<user>${CL} --password ${CUS}<pass>${CL} --content ${CUS}import,backup,iso,vztmpl,images,snippets${CL}" \
        "$(translate "For guest shares add: --options guest")" \
        ""

    show_command "5" \
        "$(translate "Inspect storage config block:")" \
        "sed -n '/^${CUS}<storage-id>${CL}:/,/^[^ ]/p' /etc/pve/storage.cfg" \
        "$(translate "Useful to verify options/content after script execution.")" \
        ""

    show_command "6" \
        "$(translate "Remove CIFS storage:")" \
        "pvesm remove ${CUS}<storage-id>${CL}" \
        "" \
        ""

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_local_share_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Local Shared Directory on Host")"

    msg_info2 "$(translate "Equivalent manual flow used by Local Shared Manager.")"
    msg_info2 "$(translate "No group creation required — uses world-writable sticky bit permissions.")"
    echo -e

    show_command "1" \
        "$(translate "Create shared directory:")" \
        "mkdir -p ${CUS}/mnt/shared${CL}" \
        "$(translate "Choose any host path you want to share with CTs.")" \
        ""

    show_command "2" \
        "$(translate "Set ownership and permissions:")" \
        "chown root:root ${CUS}/mnt/shared${CL}\nchmod 1777 ${CUS}/mnt/shared${CL}" \
        "$(translate "1777 = sticky bit + rwx for all. No shared group needed.")" \
        ""

    show_command "3" \
        "$(translate "Optional: apply default ACL so new files inherit permissions:")" \
        "setfacl -R -m d:u::rwx,d:g::rwx,d:o::rwx,m::rwx ${CUS}/mnt/shared${CL}" \
        "$(translate "Requires acl package. Skip if setfacl is not available.")" \
        ""

    show_command "4" \
        "$(translate "Optional: register this path as Proxmox dir storage:")" \
        "pvesm add dir ${CUS}<storage-id>${CL} --path ${CUS}/mnt/shared${CL} --content ${CUS}backup,iso,vztmpl,snippets${CL}" \
        "$(translate "Use images only if the directory is on suitable storage.")" \
        ""

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_disk_host_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Add Local Disk as Proxmox Storage")"

    msg_info2 "$(translate "Equivalent manual flow of disk_host.sh: partition, format, mount, persist, register in Proxmox.")"
    echo -e

    show_command "1" \
        "$(translate "Identify candidate disk (never use system disk):")" \
        "lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL" \
        "$(translate "Example target: /dev/sdb")" \
        ""

    show_command "2" \
        "$(translate "Wipe old signatures and partition table (DESTRUCTIVE):")" \
        "wipefs -a ${CUS}/dev/sdb${CL}\nsgdisk --zap-all ${CUS}/dev/sdb${CL}" \
        "$(translate "This erases existing metadata.")" \
        ""

    show_command "3" \
        "$(translate "Create GPT and one partition:")" \
        "parted -s ${CUS}/dev/sdb${CL} mklabel gpt\nparted -s ${CUS}/dev/sdb${CL} mkpart primary 0% 100%" \
        "" \
        ""

    show_command "4" \
        "$(translate "Format partition:")" \
        "mkfs.ext4 -F ${CUS}/dev/sdb1${CL}\n# or\nmkfs.xfs -f ${CUS}/dev/sdb1${CL}" \
        "" \
        ""

    show_command "5" \
        "$(translate "Mount and persist with UUID:")" \
        "mkdir -p ${CUS}/mnt/disk-sdb${CL}\nmount ${CUS}/dev/sdb1${CL} ${CUS}/mnt/disk-sdb${CL}\nblkid ${CUS}/dev/sdb1${CL}\n# Add UUID line to /etc/fstab" \
        "$(translate "Using UUID is recommended over /dev/sdX.")" \
        ""

    show_command "6" \
        "$(translate "Register mount path in Proxmox:")" \
        "pvesm add dir ${CUS}<storage-id>${CL} --path ${CUS}/mnt/disk-sdb${CL} --content ${CUS}images,backup${CL}" \
        "" \
        ""

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_iscsi_host_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Add iSCSI Target as Proxmox Storage")"

    msg_info2 "$(translate "Equivalent manual flow of iscsi_host.sh.")"
    echo -e

    show_command "1" \
        "$(translate "Install and start iSCSI initiator:")" \
        "apt-get update && apt-get install -y open-iscsi\nsystemctl enable --now iscsid" \
        "" \
        ""

    show_command "2" \
        "$(translate "Discover targets on portal:")" \
        "iscsiadm -m discovery -t sendtargets -p ${CUS}<portal-ip>:3260${CL}" \
        "$(translate "This returns available IQNs.")" \
        ""

    show_command "3" \
        "$(translate "Add iSCSI storage in Proxmox:")" \
        "pvesm add iscsi ${CUS}<storage-id>${CL} --portal ${CUS}<portal-ip>:3260${CL} --target ${CUS}<target-iqn>${CL} --content images" \
        "$(translate "Content is usually images for VM block devices.")" \
        ""

    show_command "4" \
        "$(translate "Verify iSCSI sessions and storage status:")" \
        "iscsiadm -m session\npvesm status" \
        "" \
        ""

    show_command "5" \
        "$(translate "Remove iSCSI storage definition:")" \
        "pvesm remove ${CUS}<storage-id>${CL}" \
        "" \
        ""

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_host_to_lxc_mount_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Host Directory to LXC Mount Point")"

    msg_info2 "$(translate "Current script uses native bind mounts with pct set -mpX.")"
    msg_info2 "$(translate "Safe design: no automatic ACL/ownership mutation on host or CT.")"
    echo -e

    show_command "1" \
        "$(translate "List containers:")" \
        "pct list" \
        "" \
        ""

    show_command "2" \
        "$(translate "Add bind mount to container:")" \
        "pct set ${CUS}<ctid>${CL} -mp0 ${CUS}/host/path${CL},mp=${CUS}/container/path${CL},backup=0,shared=1" \
        "$(translate "Use mp1/mp2/... for extra mount points.")" \
        ""

    show_command "3" \
        "$(translate "Check resulting config:")" \
        "pct config ${CUS}<ctid>${CL} | grep '^mp'" \
        "" \
        ""

    show_command "4" \
        "$(translate "Remove mount point:")" \
        "pct set ${CUS}<ctid>${CL} --delete mp0" \
        "" \
        ""

    show_command "5" \
        "$(translate "Verify inside container:")" \
        "pct enter ${CUS}<ctid>${CL}\ndf -h" \
        "$(translate "Confirm the mount path is visible.")" \
        ""

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_nfs_server_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "NFS Server in LXC (Privileged)")"

    msg_warn "$(translate "Use a privileged LXC for NFS server/client workflows.")"
    echo -e

    show_command "1" \
        "$(translate "Install server packages inside CT:")" \
        "apt-get update && apt-get install -y nfs-kernel-server nfs-common rpcbind" \
        "" \
        ""

    show_command "2" \
        "$(translate "Create export directory:")" \
        "mkdir -p ${CUS}/mnt/nfs_export${CL}\nchmod 755 ${CUS}/mnt/nfs_export${CL}" \
        "" \
        ""

    show_command "3" \
        "$(translate "Add export rule:")" \
        "echo '${CUS}/mnt/nfs_export${CL} ${CUS}192.168.1.0/24${CL}(rw,sync,no_subtree_check,root_squash)' >> /etc/exports" \
        "$(translate "Adjust network/CIDR to your environment.")" \
        ""

    show_command "4" \
        "$(translate "Apply and restart services:")" \
        "exportfs -ra\nsystemctl restart rpcbind nfs-kernel-server\nsystemctl enable rpcbind nfs-kernel-server" \
        "" \
        ""

    show_command "5" \
        "$(translate "Verify active exports:")" \
        "showmount -e localhost" \
        "" \
        ""

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_samba_server_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Samba Server in LXC (Privileged)")"

    msg_warn "$(translate "Use a privileged LXC for Samba client/server workflows.")"
    echo -e

    show_command "1" \
        "$(translate "Install Samba inside CT:")" \
        "apt-get update && apt-get install -y samba samba-common-bin acl" \
        "" \
        ""

    show_command "2" \
        "$(translate "Create share directory:")" \
        "mkdir -p ${CUS}/mnt/samba_share${CL}\nchmod 755 ${CUS}/mnt/samba_share${CL}" \
        "" \
        ""

    show_command "3" \
        "$(translate "Create Samba user:")" \
        "adduser ${CUS}sambauser${CL}\nsmbpasswd -a ${CUS}sambauser${CL}" \
        "" \
        ""

    show_command "4" \
        "$(translate "Add share block in /etc/samba/smb.conf:")" \
        "cat >> /etc/samba/smb.conf << 'EOF'\n[shared]\n  path = /mnt/samba_share\n  browseable = yes\n  read only = no\n  valid users = sambauser\nEOF" \
        "" \
        ""

    show_command "5" \
        "$(translate "Restart and enable Samba:")" \
        "systemctl restart smbd\nsystemctl enable smbd" \
        "" \
        ""

    show_command "6" \
        "$(translate "Test share visibility:")" \
        "smbclient -L localhost -U ${CUS}sambauser${CL}" \
        "" \
        ""

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_nfs_client_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "NFS Client in LXC (Privileged)")"

    msg_warn "$(translate "Current NFS client script supports privileged LXC only.")"
    echo -e

    show_command "1" \
        "$(translate "Install NFS client packages inside CT:")" \
        "apt-get update && apt-get install -y nfs-common" \
        "" \
        ""

    show_command "2" \
        "$(translate "Create mount point:")" \
        "mkdir -p ${CUS}/mnt/nfs_share${CL}" \
        "" \
        ""

    show_command "3" \
        "$(translate "Mount NFS share:")" \
        "mount -t nfs ${CUS}<server-ip>:/export/path${CL} ${CUS}/mnt/nfs_share${CL}" \
        "$(translate "Adjust options if needed (vers=4,hard,timeo,...).")" \
        ""

    show_command "4" \
        "$(translate "Persist mount in CT /etc/fstab (optional):")" \
        "echo '${CUS}<server-ip>:/export/path${CL} ${CUS}/mnt/nfs_share${CL} nfs defaults,_netdev,x-systemd.automount,noauto 0 0' >> /etc/fstab" \
        "" \
        ""

    show_command "5" \
        "$(translate "Verify mount:")" \
        "mount | grep nfs\ndf -h | grep nfs" \
        "" \
        ""

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_samba_client_help() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Samba Client in LXC (Privileged)")"

    msg_warn "$(translate "Current Samba client script supports privileged LXC only.")"
    echo -e

    show_command "1" \
        "$(translate "Install CIFS client packages inside CT:")" \
        "apt-get update && apt-get install -y cifs-utils" \
        "" \
        ""

    show_command "2" \
        "$(translate "Create mount point:")" \
        "mkdir -p ${CUS}/mnt/samba_share${CL}" \
        "" \
        ""

    show_command "3" \
        "$(translate "Create credentials file (recommended):")" \
        "cat > /etc/samba/credentials/proxmenux.cred << 'EOF'\nusername=${CUS}<user>${CL}\npassword=${CUS}<pass>${CL}\nEOF\nchmod 600 /etc/samba/credentials/proxmenux.cred" \
        "" \
        ""

    show_command "4" \
        "$(translate "Mount CIFS share:")" \
        "mount -t cifs //${CUS}<server-ip>/<share>${CL} ${CUS}/mnt/samba_share${CL} -o credentials=/etc/samba/credentials/proxmenux.cred,iocharset=utf8,file_mode=0664,dir_mode=0775" \
        "" \
        ""

    show_command "5" \
        "$(translate "Persist mount in CT /etc/fstab (optional):")" \
        "echo '//${CUS}<server-ip>/<share>${CL} ${CUS}/mnt/samba_share${CL} cifs credentials=/etc/samba/credentials/proxmenux.cred,_netdev,x-systemd.automount,noauto 0 0' >> /etc/fstab" \
        "" \
        ""

    show_command "6" \
        "$(translate "Verify mount:")" \
        "mount -t cifs\ndf -h | grep cifs" \
        "" \
        ""

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

show_help_menu() {
    while true; do
        CHOICE=$(dialog --title "$(translate "Help & Information")" \
            --menu "$(translate "Select help topic:")" 24 90 14 \
            "0" "$(translate "How to Access an LXC Terminal")" \
            "1" "$(translate "Host NFS/Samba as Proxmox Storage (pvesm)")" \
            "2" "$(translate "Local Shared Directory on Host")" \
            "3" "$(translate "Add Local Disk as Proxmox Storage")" \
            "4" "$(translate "Add iSCSI Target as Proxmox Storage")" \
            "5" "$(translate "Mount Host Directory to LXC Container")" \
            "6" "$(translate "NFS Client in LXC (privileged)")" \
            "7" "$(translate "Samba Client in LXC (privileged)")" \
            "8" "$(translate "NFS Server in LXC (privileged)")" \
            "9" "$(translate "Samba Server in LXC (privileged)")" \
            "10" "$(translate "Return to Share Menu")" \
            3>&1 1>&2 2>&3)

        case "$CHOICE" in
            0) show_how_to_enter_lxc ;;
            1) show_host_storage_help ;;
            2) show_local_share_help ;;
            3) show_disk_host_help ;;
            4) show_iscsi_host_help ;;
            5) show_host_to_lxc_mount_help ;;
            6) show_nfs_client_help ;;
            7) show_samba_client_help ;;
            8) show_nfs_server_help ;;
            9) show_samba_server_help ;;
            10) return ;;
            *) return ;;
        esac
    done
}

show_help_menu
