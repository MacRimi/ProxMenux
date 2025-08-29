#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 28/01/2025
# ==========================================================
# Description:
# This script provides an interactive command reference menu
# for Proxmox VE via dialog-based UI.
# - Categorized and translated lists of common and advanced commands.
# - Covers system, network, storage, VM/CT, updates, GPU passthrough,
#   ZFS, backup/restore, and essential CLI tools.
# - Allows users to view or execute commands directly from the menu.
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
# ===============================================================

# Colores
YELLOW="\033[0;33m"
GREEN="\033[0;32m"
NC="\033[0m"

if ! command -v dialog &>/dev/null; then
    apt update -qq >/dev/null 2>&1
    apt install -y dialog >/dev/null 2>&1
fi


# ===============================================================
# 01 Useful System Commands
# ===============================================================
show_system_commands() {
    while true; do
        clear
        echo -e "${YELLOW}$(translate 'Useful System Commands')${NC}"
        echo "----------------------------------------"
        echo -e " 1) ${GREEN}pveversion${NC}                         - $(translate 'Show Proxmox version')"
        echo -e " 2) ${GREEN}pveversion -v${NC}                      - $(translate 'Detailed Proxmox version info')"
        echo -e " 3) ${GREEN}systemctl status pveproxy${NC}          - $(translate 'Check Proxmox Web UI status')"
        echo -e " 4) ${GREEN}systemctl restart pveproxy${NC}         - $(translate 'Restart Web UI proxy')"
        echo -e " 5) ${GREEN}journalctl -xe${NC}                     - $(translate 'System errors and logs')"
        echo -e " 6) ${GREEN}uptime${NC}                             - $(translate 'System uptime')"
        echo -e " 7) ${GREEN}hostnamectl${NC}                        - $(translate 'System hostname and kernel info')"
        echo -e " 8) ${GREEN}free -h${NC}                            - $(translate 'RAM and swap usage')"
        echo -e " 9) ${GREEN}uptime -p${NC}                          - $(translate 'Pretty uptime format')"
        echo -e "10) ${GREEN}who -b${NC}                             - $(translate 'Last system boot time')"
        echo -e "11) ${GREEN}last -x | grep shutdown${NC}            - $(translate 'Previous shutdowns')"
        echo -e "12) ${GREEN}dmesg -T | tail -n 50${NC}              - $(translate 'Last 50 kernel log lines')"
        echo -e "13) ${GREEN}cat /etc/os-release${NC}                - $(translate 'OS release details')"
        echo -e "14) ${GREEN}uname -a${NC}                           - $(translate 'Kernel and architecture info')"
        echo -e "15) ${GREEN}uptime && w${NC}                        - $(translate 'Uptime and who is logged in')"
        echo -e "16) ${GREEN}whoami${NC}                             - $(translate 'Current user')"
        echo -e "17) ${GREEN}id${NC}                                 - $(translate 'Current user UID, GID and groups')"
        echo -e "18) ${GREEN}who${NC}                                - $(translate 'Logged-in users')"
        echo -e "19) ${GREEN}w${NC}                                  - $(translate 'User activity and uptime')"
        echo -e "20) ${GREEN}cut -d: -f1,3,4 /etc/passwd${NC}        - $(translate 'All users with UID and GID')"
        echo -e "21) ${GREEN}getent passwd | column -t -s :${NC}     - $(translate 'Readable user table (UID, shell, etc.)')"
		echo -e "22) ${GREEN}lynis audit system${NC}                 - $(translate 'Run a full security audit')"
		echo -e "23) ${GREEN}fastfetch${NC}                          - $(translate 'Display system summary in ASCII format')"
        echo -e " ${DEF}0) $(translate ' Back to previous menu or Esc + Enter')"
        echo
        echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter a number, or write or paste a command: ') ${CL}"
        read -r user_input

        # Check for Esc key press
        if [[ "$user_input" == $'\x1b' ]]; then
            break
        fi

        case "$user_input" in
            0) break ;;
            [1-9]|1[0-9]|2[0-3])
                case "$user_input" in
                    1) cmd="pveversion" ;;
                    2) cmd="pveversion -v" ;;
                    3) cmd="systemctl status pveproxy" ;;
                    4) cmd="systemctl restart pveproxy" ;;
                    5) cmd="journalctl -xe" ;;
                    6) cmd="uptime" ;;
                    7) cmd="hostnamectl" ;;
                    8) cmd="free -h" ;;
                    9) cmd="uptime -p" ;;
                    10) cmd="who -b" ;;
                    11) cmd="last -x | grep shutdown" ;;
                    12) cmd="dmesg -T | tail -n 50" ;;
                    13) cmd="cat /etc/os-release" ;;
                    14) cmd="uname -a" ;;
                    15) cmd="uptime && w" ;;
                    16) cmd="whoami" ;;
                    17) cmd="id" ;;
                    18) cmd="who" ;;
                    19) cmd="w" ;;
                    20) cmd="cut -d: -f1,3,4 /etc/passwd" ;;
                    21) cmd="getent passwd | column -t -s :" ;;
					22)
						if ! command -v lynis &>/dev/null; then
							echo -e "\n${RED}$(translate 'Lynis is not installed. Run: apt install lynis')${NC}\n"
							msg_success "$(translate 'Press ENTER to continue...')"
							read -r tmp
							continue
						fi
						cmd="lynis audit system"
						;;
					23)
						if ! command -v fastfetch &>/dev/null; then
							echo -e "\n${RED}$(translate 'Fastfetch is not installed. Run: apt install fastfetch')${NC}\n"
							msg_success "$(translate 'Press ENTER to continue...')"
							read -r tmp
							continue
						fi
						cmd="fastfetch"
						;;

                esac
                echo -e "\n${GREEN}> $cmd${NC}\n"
                bash -c "$cmd"
                echo
                msg_success "$(translate 'Press ENTER to continue...')"
                read -r tmp
                ;;
            *)
                if [[ -n "$user_input" ]]; then
                    echo -e "\n${GREEN}> $user_input${NC}\n"
                    bash -c "$user_input"
                    echo
                    msg_success "$(translate 'Press ENTER to continue...')"
                    read -r tmp
                fi
                ;;
        esac
    done
}


# ===============================================================
# 02 VM and CT Management Commands
# ===============================================================
show_vm_ct_commands() {
    while true; do
        clear
        echo -e "${YELLOW}$(translate 'VM and CT Management Commands')${NC}"
        echo "---------------------------------------------------"
        echo -e " 1) ${GREEN}qm list${NC}                  - $(translate 'List all virtual machines')"
        echo -e " 2) ${GREEN}pct list${NC}                 - $(translate 'List all LXC containers')"
        echo -e " 3) ${GREEN}qm start <vmid>${NC}          - $(translate 'Start a virtual machine. Use the correct <vmid>')"
        echo -e " 4) ${GREEN}pct start <ctid>${NC}         - $(translate 'Start a container. Use the correct <ctid>')"
        echo -e " 5) ${GREEN}qm stop <vmid>${NC}           - $(translate 'Force stop a virtual machine. Use the correct <vmid>')"
        echo -e " 6) ${GREEN}pct stop <ctid>${NC}          - $(translate 'Force stop a container. Use the correct <ctid>')"
        echo -e " 7) ${GREEN}qm config <vmid>${NC}         - $(translate 'Show VM configuration. Use the correct <vmid>')"
        echo -e " 8) ${GREEN}pct config <ctid>${NC}        - $(translate 'Show container configuration. Use the correct <ctid>')"
        echo -e " 9) ${GREEN}qm destroy <vmid>${NC}        - $(translate 'Delete a VM (irreversible). Use the correct <vmid>')"
        echo -e "10) ${GREEN}pct destroy <ctid>${NC}       - $(translate 'Delete a CT (irreversible). Use the correct <ctid>')"
        echo -e "11) ${GN}[Only with menu] Show CT users for permission mapping${NC} - $(translate 'root and real users only')"
        echo -e "12) ${GREEN}pct exec <ctid> -- getent passwd | column -t -s :${NC}     - $(translate 'Show CT users in table format')"
        echo -e "13) ${GREEN}pct exec <ctid> -- ps aux --sort=-%mem | head${NC}         - $(translate 'Top memory processes in CT')"
        echo -e " ${DEF}0) $(translate ' Back to previous menu or Esc + Enter')"
        echo
        echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter a number, or write or paste a command: ') ${CL}"
        read -r user_input

        # Check for Esc key press
        if [[ "$user_input" == $'\x1b' ]]; then
            break
        fi

        case "$user_input" in
            1) cmd="qm list" ;;
            2) cmd="pct list" ;;
            3) echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter VM ID: ')${CL}"; read -r id; cmd="qm start $id" ;;
            4) echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter CT ID: ')${CL}"; read -r id; cmd="pct start $id" ;;
            5) echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter VM ID: ')${CL}"; read -r id; cmd="qm stop $id" ;;
            6) echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter CT ID: ')${CL}"; read -r id; cmd="pct stop $id" ;;
            7) echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter VM ID: ')${CL}"; read -r id; cmd="qm config $id" ;;
            8) echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter CT ID: ')${CL}"; read -r id; cmd="pct config $id" ;;
            9) echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter VM ID: ')${CL}"; read -r id; cmd="qm destroy $id" ;;
            10) echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter CT ID: ')${CL}"; read -r id; cmd="pct destroy $id" ;;
            11)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter CT ID: ')${CL}"
                read -r id

                echo -e "\n${YELLOW}$(translate 'Listing relevant CT users and their mapped UID/GID on host...')${NC}\n"


                UID_SHIFT=$(grep "^lxc.idmap" /etc/pve/lxc/"$id".conf | grep 'u 0' | awk '{print $5}')
                UID_SHIFT=${UID_SHIFT:-100000}

                pct exec "$id" -- getent passwd | while IFS=: read -r username _ uid gid _ home _; do
                    if [ "$uid" -eq 0 ] || [ "$uid" -eq 65534 ] || [ "$uid" -ge 30 ]; then
                        real_uid=$((UID_SHIFT + uid))
                        real_gid=$((UID_SHIFT + gid))
                        echo -e "${GREEN}$(translate 'User')${NC}: $username"
                        echo -e "  $(translate 'UID in CT'): $uid"
                        echo -e "  $(translate 'GID in CT'): $gid"
                        echo -e "  $(translate 'Mapped UID on host'): $real_uid"
                        echo -e "  $(translate 'Mapped GID on host'): $real_gid"
                        echo
                    fi
                done
                ;;

            12)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter CT ID: ')${CL}"
                read -r id
                cmd="pct exec $id -- getent passwd | column -t -s :"
                ;; 

            13)
            
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter CT ID: ')${CL}"
                read -r id
                cmd="pct exec $id -- ps aux --sort=-%mem | head"
                ;;
            0) break ;;
            *) cmd="$user_input" ;;
        esac

        echo -e "\n${GREEN}> $cmd${NC}\n"
        bash -c "$cmd"
        echo
        msg_success "$(translate 'Press ENTER to continue...')"
        read -r tmp
    done
}



# ===============================================================
# 03 Storage and Disks Commands
# ===============================================================
show_storage_commands() {
    while true; do
        clear
        echo -e "${YELLOW}$(translate 'Storage and Disks Commands')${NC}"
        echo "--------------------------------------------------"
        echo -e " 1) ${GREEN}lsblk${NC}                       - $(translate 'List block devices and partitions')"
        echo -e " 2) ${GREEN}fdisk -l${NC}                    - $(translate 'List disks with detailed info')"
        echo -e " 3) ${GREEN}blkid${NC}                       - $(translate 'Show UUID and filesystem type of block devices')"
        echo -e " 4) ${GREEN}ls -lh /dev/disk/by-id/${NC}     - $(translate 'List disk persistent identifiers')"
        echo -e " 5) ${GREEN}parted -l${NC}                   - $(translate 'Detailed partition layout with GPT info')"
        echo -e " 6) ${GREEN}df -h${NC}                       - $(translate 'Show disk usage by mount point')"
        echo -e " 7) ${GREEN}du -sh /path${NC}                - $(translate 'Show size of a directory')"
        echo -e " 8) ${GREEN}mount | grep ^/dev${NC}          - $(translate 'Show mounted storage devices')"
        echo -e " 9) ${GREEN}cat /proc/mounts${NC}            - $(translate 'Show all active mounts from the kernel')"
        echo -e "10) ${GREEN}pvdisplay${NC}                   - $(translate 'Display physical volumes (LVM)')"
        echo -e "11) ${GREEN}vgdisplay${NC}                   - $(translate 'Display volume groups (LVM)')"
        echo -e "12) ${GREEN}lvdisplay${NC}                   - $(translate 'Display logical volumes (LVM)')"
        echo -e "13) ${GREEN}pvs${NC}                         - $(translate 'Concise output of physical volumes')"
        echo -e "14) ${GREEN}vgs${NC}                         - $(translate 'Concise output of volume groups')"
        echo -e "15) ${GREEN}lvs${NC}                         - $(translate 'Concise output of logical volumes')"
        echo -e "16) ${GREEN}cat /etc/pve/storage.cfg${NC}    - $(translate 'Show Proxmox storage configuration')"
        echo -e "17) ${GREEN}pvesm status${NC}                - $(translate 'Show status of all storage pools')"
        echo -e "18) ${GREEN}pvesm list <storage>${NC}        - $(translate 'List content of specific storage')"
        echo -e "19) ${GREEN}pvesm scan <storage>${NC}        - $(translate 'Scan storage for new content')"
        echo -e "20) ${GREEN}qm importdisk <vmid> <img> <storage>${NC}  - $(translate 'Import disk image to VM')"
        echo -e "21) ${GREEN}qm set <vmid> -<bus><index> <disk>${NC}    - $(translate 'Add physical disk to VM via') passthrough"
        echo -e "22) ${GREEN}qemu-img convert -O <format> <input> <output>${NC} - $(translate 'Convert disk image format')"
        echo -e " ${DEF}0) $(translate ' Back to previous menu or Esc + Enter')"
        echo
        echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter a number, or write or paste a command: ') ${CL}"
        read -r user_input

        # Esc key exit
        if [[ "$user_input" == $'\x1b' ]]; then
            break
        fi

        case "$user_input" in
            1) cmd="lsblk" ;;
            2) cmd="fdisk -l" ;;
            3) cmd="blkid" ;;
            4) cmd="ls -lh /dev/disk/by-id/" ;;
            5) cmd="parted -l" ;;
            6) cmd="df -h" ;;
            7)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter path to analyze: ')${CL}"
                read -r path
                cmd="du -sh $path"
                ;;
            8) cmd="mount | grep ^/dev" ;;
            9) cmd="cat /proc/mounts" ;;
            10) cmd="pvdisplay" ;;
            11) cmd="vgdisplay" ;;
            12) cmd="lvdisplay" ;;
            13) cmd="pvs" ;;
            14) cmd="vgs" ;;
            15) cmd="lvs" ;;
            16) cmd="cat /etc/pve/storage.cfg" ;;
            17) cmd="pvesm status" ;;
            19)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter storage ID: ')${CL}"
                read -r store
                cmd="pvesm list $store"
                ;;
            19)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter storage ID: ')${CL}"
                read -r store
                cmd="pvesm scan $store"
                ;;
            20)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter VM ID: ')${CL}"
                read -r vmid

                echo -e "\n${YELLOW}$(translate 'Available images in /var/lib/vz/images/:')${NC}"
                images=$(find /var/lib/vz/images/ -type f \( -iname "*.img" -o -iname "*.qcow2" -o -iname "*.vmdk" -o -iname "*.raw" \))

                if [[ -z "$images" ]]; then
                    echo -e "${RED}$(translate 'No disk images found in /var/lib/vz/images/. Please add an image first.')${NC}"
                    echo
                    msg_success "$(translate 'Press ENTER to return to the menu...')"
                    read -r
                    continue
                else
                    echo "$images"
                fi

                echo -en "\n${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter full path to the disk image (e.g., /var/lib/vz/images/xyz.img): ')${CL}"
                read -r image_path

                echo -e "\n${YELLOW}$(translate 'Available storage volumes:')${NC}"
                pvesm status | awk 'NR>1 {print " - "$1}'

                echo -en "\n${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter target storage name (e.g., local-lvm): ')${CL}"
                read -r storage

                cmd1="qm importdisk $vmid $image_path $storage"
                bash -c "$cmd1"
                echo

                disk_name=$(basename "$image_path")
                imported_volume="${storage}:vm-${vmid}-disk-0"

                echo -e "\n${YELLOW}$(translate 'Select disk interface type:')${NC}"
                echo " 1) sata"
                echo " 2) scsi"
                echo " 3) virtio"
                echo " 4) ide"
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter the number or type the interface name: ')${CL}"
                read -r iface_type

                case "$iface_type" in
                    1) iface="sata" ;;
                    2) iface="scsi" ;;
                    3) iface="virtio" ;;
                    4) iface="ide" ;;
                    *) iface="sata" ;;
                esac

                index=$(qm config "$vmid" | grep -oP "$iface\d+" | awk -F"$iface" '{print $2}' | sort -n | tail -n1)
                index=$((index + 1))

                echo -e "\n${YELLOW}$(translate 'Assigning imported disk to VM using the generated command')${NC}"
                sleep 1
                echo
                echo -e "\n${GREEN}> $cmd1${NC}\n"
                cmd="qm set $vmid -$iface$index $imported_volume"    
                ;;
            21)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter VM ID: ')${CL}"
                read -r vmid

                echo -e "\n${YELLOW}$(translate 'Scanning available physical disks...')${NC}"
                sleep 1

                echo -e "\n${YELLOW}$(translate 'Available physical disks for passthrough:')${NC}"
                printf "\n"

                lsblk -dno NAME,SIZE,MODEL | grep -vE 'boot|rpmb|loop|dm-|zd' | while read -r name size model; do
                disk_path="/dev/$name"
                by_id=$(find /dev/disk/by-id/ -lname "*$name" | grep -vE 'part[0-9]+$' | head -n1)
                if [[ -n "$by_id" ]]; then
                        printf "  %-60s (%s %s)\n" "$by_id" "$size" "$model"
                fi
                done

                echo
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter full disk path as shown above (starting with /dev/disk/by-id/xxx...): ')${CL}"
                read -r disk_path

                echo -e "\n${YELLOW}$(translate 'Select disk interface type:')${NC}"
                echo " 1) sata"
                echo " 2) scsi"
                echo " 3) virtio"
                echo " 4) ide"
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter the number or type the interface name: ')${CL}"
                read -r iface_type

                case "$iface_type" in
                        1) iface="sata" ;;
                        2) iface="scsi" ;;
                        3) iface="virtio" ;;
                        4) iface="ide" ;;
                        *) iface="sata" ;;
                esac

                index=$(qm config "$vmid" | grep -oP "$iface\d+" | awk -F"$iface" '{print $2}' | sort -n | tail -n1)
                                index=$((index + 1))

                echo -e "\n${YELLOW}$(translate 'Adding disk using the generated command to the selected VM')${NC}"
                sleep 1

                cmd="qm set $vmid -$iface$index $disk_path"
               ;;
            22)
                echo -e "\n${YELLOW}$(translate 'Convert disk image format using QEMU-IMG')${NC}"
                sleep 1

                echo -e "\n${YELLOW}$(translate 'Available images in /var/lib/vz/images/:')${NC}"
                images=$(find /var/lib/vz/images/ -type f \( -iname "*.img" -o -iname "*.qcow2" -o -iname "*.vmdk" -o -iname "*.raw" -o -iname "*.vdi" -o -iname "*.vpc" -o -iname "*.qed" \))

                if [[ -z "$images" ]]; then
                    echo -e "${RED}$(translate 'No disk images found in /var/lib/vz/images/. Please add an image first.')${NC}"
                    echo
                    msg_success "$(translate 'Press ENTER to return to the menu...')"
                    read -r
                    continue
                else
                    echo "$images"
                fi

                echo -en "\n${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter full path to the input image (e.g., /var/lib/vz/images/disk.vmdk): ')${CL}"
                read -r input_image

                echo -e "\n${YELLOW}$(translate 'Available output formats include:')${NC} qcow2, raw, qed"

                echo -en "\n${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter the full path to the output image (e.g., /var/lib/vz/images/output.qcow2): ')${CL}"
                read -r output_image
                valid_formats=("qcow2" "raw" "qed")
                output_format=$(echo "$output_image" | awk -F. '{print tolower($NF)}')

                if ! [[ " ${valid_formats[*]} " =~ " ${output_format} " ]]; then
                    echo -e "\n${RED}$(translate 'Unsupported output format:') .$output_format${NC}"
                    msg_success "$(translate 'Press ENTER to return...')"
                    read -r
                    continue
                fi
                echo -e "\n${YELLOW}$(translate 'Converting image using command:')${NC}"
                cmd="qemu-img convert -O $output_format $input_image $output_image"
               ;;
            0) break ;;
            *) cmd="$user_input" ;;
        esac

        echo -e "\n${GREEN}> $cmd${NC}\n"
        bash -c "$cmd"
        echo
        msg_success "$(translate 'Press ENTER to continue...')"
        read -r tmp
    done
}



# ===============================================================
# 04 Network Commands
# ===============================================================
show_network_commands() {
    while true; do
        clear
        echo -e "${YELLOW}$(translate 'Network Commands')${NC}"
        echo "------------------------------------------"
        echo -e " 1) ${GREEN}ip a${NC}                           - $(translate 'Show network interfaces and IPs')"
        echo -e " 2) ${GREEN}ip r${NC}                           - $(translate 'Show routing table')"
        echo -e " 3) ${GREEN}ping <host>${NC}                    - $(translate 'Check connectivity with another host')"
        echo -e " 4) ${GREEN}brctl show${NC}                     - $(translate 'Show configured network bridges')"
        echo -e " 5) ${GREEN}ifreload -a${NC}                    - $(translate 'Reload network configuration (ifupdown2)')"
        echo -e " 6) ${GREEN}cat /etc/network/interfaces${NC}    - $(translate 'Show raw network configuration')"
        echo -e " 7) ${GREEN}ip -s link${NC}                     - $(translate 'Show traffic statistics per interface')"
        echo -e " 8) ${GREEN}ethtool <iface>${NC}                - $(translate 'Show Ethernet device info')"
        echo -e " 9) ${GREEN}resolvectl status${NC}              - $(translate 'Show DNS resolution status')"
        echo -e "10) ${GREEN}dig <domain>${NC}                   - $(translate 'DNS lookup for a domain')"
        echo -e "11) ${GREEN}ss -tuln${NC}                       - $(translate 'Show listening ports (TCP/UDP)')"
        echo -e "12) ${GREEN}iptables -L -n -v${NC}              - $(translate 'Show active firewall rules (iptables)')"
        echo -e "13) ${GREEN}nft list ruleset${NC}               - $(translate 'Show nftables rules')"
        echo -e "14) ${GREEN}pve-firewall status${NC}            - $(translate 'Check Proxmox firewall status')"
        echo -e "15) ${GREEN}pve-firewall compile${NC}           - $(translate 'Compile firewall rules for all nodes')"
        echo -e "16) ${GREEN}pve-firewall reload${NC}            - $(translate 'Reload Proxmox firewall rules')"
        echo -e " ${DEF}0) $(translate ' Back to previous menu or Esc + Enter')"
        echo
        echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter a number, or write or paste a command: ') ${CL}"
        read -r user_input

        if [[ "$user_input" == $'\x1b' ]]; then
            break
        fi

        case "$user_input" in
            1) cmd="ip a" ;;
            2) cmd="ip r" ;;
            3)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter host or IP: ')${CL}"
                read -r host
                cmd="ping $host"
                ;;
            4) cmd="brctl show" ;;
            5) cmd="ifreload -a" ;;
            6) cmd="cat /etc/network/interfaces" ;;
            7) cmd="ip -s link" ;;
            8)
                echo -e "\n${YELLOW}$(translate 'Available network interfaces:')${NC}"
                ip -o link show | awk -F': ' '{print " - " $2}' | grep -v '^ - lo' | sort
                echo
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter interface name (e.g. eth0): ')${CL}"
                read -r iface
                cmd="ethtool $iface"
                ;;

            9) cmd="resolvectl status" ;;
            10)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter domain name: ')${CL}"
                read -r domain
                cmd="dig $domain"
                ;;
            11) cmd="ss -tuln" ;;
            12) cmd="iptables -L -n -v" ;;
            13) cmd="nft list ruleset" ;;
            14) cmd="pve-firewall status" ;;
            15) cmd="pve-firewall compile" ;;
            16) cmd="pve-firewall reload" ;;
            0) break ;;
            *) cmd="$user_input" ;;
        esac

        echo -e "\n${GREEN}> $cmd${NC}\n"
        bash -c "$cmd"
        echo
        msg_success "$(translate 'Press ENTER to continue...')"
        read -r tmp
    done
}




# ===============================================================
# 05 Updates and Packages Commands
# ===============================================================
show_update_commands() {
    while true; do
        clear
        echo -e "${YELLOW}$(translate 'Updates and Packages Commands')${NC}"
        echo "----------------------------------------------------"
        echo -e " 1) ${GREEN}apt update && apt upgrade -y${NC}   - $(translate 'Update and upgrade all system packages')"
        echo -e " 2) ${GREEN}apt dist-upgrade -y${NC}            - $(translate 'Full system upgrade, including dependencies')"
        echo -e " 3) ${GREEN}pveupdate${NC}                      - $(translate 'Update Proxmox package lists')"
        echo -e " 4) ${GREEN}pveupgrade${NC}                     - $(translate 'Show available Proxmox upgrades')"
        echo -e " 5) ${GREEN}apt autoremove --purge${NC}         - $(translate 'Remove unused packages and their config')"
        echo -e " ${DEF}0) $(translate ' Back to previous menu or Esc + Enter')"
        echo
        echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter a number, or write or paste a command: ') ${CL}"
        read -r user_input

        # Check for Esc key press
        if [[ "$user_input" == $'\x1b' ]]; then
            break
        fi

        case "$user_input" in
            1) cmd="apt update && apt upgrade -y" ;;
            2) cmd="apt dist-upgrade -y" ;;
            3) cmd="pveupdate" ;;
            4) cmd="pveupgrade" ;;
            5) cmd="apt autoremove --purge" ;;
            0) break ;;
            *) cmd="$user_input" ;;
        esac

        echo -e "\n${GREEN}> $cmd${NC}\n"
        bash -c "$cmd"
        echo
        msg_success "$(translate 'Press ENTER to continue...')"
        read -r tmp
    done
}


# ===============================================================
# 06 GPU Passthrough Commands
# ===============================================================
show_gpu_commands() {
    while true; do
        clear
        echo -e "${YELLOW}$(translate 'GPU Passthrough Commands')${NC}"
        echo "------------------------------------------------"
        echo -e " 1) ${GREEN}lspci -nn | grep -i nvidia${NC}       - $(translate 'List NVIDIA PCI devices')"
        echo -e " 2) ${GREEN}lspci -nn | grep -i vga${NC}          - $(translate 'List all VGA compatible devices')"
        echo -e " 3) ${GREEN}dmesg | grep -i vfio${NC}             - $(translate 'Check VFIO module messages')"
        echo -e " 4) ${GREEN}cat /etc/modprobe.d/vfio.conf${NC}    - $(translate 'Review VFIO passthrough configuration')"
        echo -e " 5) ${GREEN}update-initramfs -u${NC}              - $(translate 'Apply initramfs changes (VFIO)')"
        echo -e " 6) ${GREEN}cat /etc/default/grub${NC}            - $(translate 'Review GRUB options for IOMMU')"
        echo -e " 7) ${GREEN}update-grub${NC}                      - $(translate 'Apply GRUB changes')"
        echo -e " ${DEF}0) $(translate ' Back to previous menu or Esc + Enter')"
        echo
        echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter a number, or write or paste a command: ') ${CL}"
        read -r user_input

        # Check for Esc key press
        if [[ "$user_input" == $'\x1b' ]]; then
            break
        fi

        case "$user_input" in
            1) cmd="lspci -nn | grep -i nvidia" ;;
            2) cmd="lspci -nn | grep -i vga" ;;
            3) cmd="dmesg | grep -i vfio" ;;
            4) cmd="cat /etc/modprobe.d/vfio.conf" ;;
            5) cmd="update-initramfs -u" ;;
            6) cmd="cat /etc/default/grub" ;;
            7) cmd="update-grub" ;;
            0) break ;;
            *) cmd="$user_input" ;;
        esac

        echo -e "\n${GREEN}> $cmd${NC}\n"
        bash -c "$cmd"
        echo
        msg_success "$(translate 'Press ENTER to continue...')"
        read -r tmp
    done
}



# ===============================================================
# 07 ZFS Management Commands
# ===============================================================
show_zfs_commands() {
    while true; do
        clear
        echo -e "${YELLOW}$(translate 'ZFS Management Commands')${NC}"
        echo "------------------------------------------------"
        echo -e " 1) ${GREEN}zpool status${NC}                   - $(translate 'Show ZFS pool status')"
        echo -e " 2) ${GREEN}zpool list${NC}                     - $(translate 'List all ZFS pools')"
        echo -e " 3) ${GREEN}zfs list${NC}                       - $(translate 'List ZFS datasets and snapshots')"
        echo -e " 4) ${GREEN}zpool scrub <pool>${NC}             - $(translate 'Start scrub for a ZFS pool')"
        echo -e " 5) ${GREEN}zfs create <pool>/dataset${NC}      - $(translate 'Create a new dataset in a ZFS pool')"
        echo -e " 6) ${GREEN}zfs destroy <pool>/dataset${NC}     - $(translate 'Destroy a ZFS dataset (irreversible)')"
        echo -e " 7) ${GREEN}zpool import${NC}                   - $(translate 'List importable ZFS pools')"
        echo -e " 8) ${GREEN}zpool import <pool>${NC}            - $(translate 'Import a ZFS pool')"
        echo -e " 9) ${GREEN}zpool export <pool>${NC}            - $(translate 'Export a ZFS pool')"
        echo -e "10) ${GREEN}zfs mount -a${NC}                   - $(translate 'Mount all datasets')"
        echo -e "11) ${GREEN}zfs mount <pool/dataset>${NC}       - $(translate 'Mount specific dataset')"
        echo -e "12) ${GREEN}zpool status -v${NC}                - $(translate 'Verbose pool status')"
        echo -e "13) ${GREEN}zpool history${NC}                  - $(translate 'ZFS command history')"
        echo -e "14) ${GREEN}zpool clear <pool>${NC}             - $(translate 'Clear pool error state')"
        echo -e " ${DEF}0) $(translate ' Back to previous menu or Esc + Enter')"
        echo
        echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter a number, or write or paste a command: ') ${CL}"
        read -r user_input

        # Detect ESC
        if [[ "$user_input" == $'\x1b' ]]; then
            break
        fi

        case "$user_input" in
            1) cmd="zpool status" ;;
            2) cmd="zpool list" ;;
            3) cmd="zfs list" ;;
            4)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter pool name: ')${CL}"
                read -r pool
                cmd="zpool scrub $pool"
                ;;
            5)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter pool/dataset name: ')${CL}"
                read -r dataset
                cmd="zfs create $dataset"
                ;;
            6)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter pool/dataset to destroy: ')${CL}"
                read -r dataset
                cmd="zfs destroy $dataset"
                ;;
            7) cmd="zpool import" ;;
            8)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter pool name to import: ')${CL}"
                read -r pool
                cmd="zpool import $pool"
                ;;
            9)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter pool name to export: ')${CL}"
                read -r pool
                cmd="zpool export $pool"
                ;;
            10) cmd="zfs mount -a" ;;
            11)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter pool/dataset to mount: ')${CL}"
                read -r dataset
                cmd="zfs mount $dataset"
                ;;
            12) cmd="zpool status -v" ;;
            13) cmd="zpool history" ;;
            14)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter pool name to clear errors: ')${CL}"
                read -r pool
                cmd="zpool clear $pool"
                ;;
            0) break ;;
            *) cmd="$user_input" ;;
        esac

        echo -e "\n${GREEN}> $cmd${NC}\n"
        bash -c "$cmd"
        echo
        msg_success "$(translate 'Press ENTER to continue...')"
        read -r tmp
    done
}




# ===============================================================
# 08 Backup and Restore Commands
# ===============================================================
show_backup_commands() {
    while true; do
        clear
        echo -e "${YELLOW}$(translate 'Backup and Restore Commands')${NC}"
        echo "------------------------------------------------------"
        echo -e " 1) ${GREEN}vzdump <vmid>${NC}                            - $(translate 'Manual backup of a VM or CT')"
        echo -e " 2) ${GREEN}vzdump <vmid> --dumpdir /path${NC}            - $(translate 'Backup to a specific directory')"
        echo -e " 3) ${GREEN}vzdump --all${NC}                             - $(translate 'Backup all VMs and CTs')"
        echo -e " 4) ${GREEN}qmrestore /path/backup.vma.zst <vmid>${NC}    - $(translate 'Restore a VM from backup')"
        echo -e " 5) ${GREEN}pct restore <vmid> /path/backup.tar.zst${NC}  - $(translate 'Restore a CT from backup')"
        echo -e " 6) ${GREEN}ls /var/lib/vz/dump${NC}                      - $(translate 'List local backups')"
        echo -e " 7) ${GREEN}pvesm list <storage>${NC}                     - $(translate 'List backups in a specific storage')"
        echo -e " 8) ${GREEN}cat /etc/vzdump.conf${NC}                     - $(translate 'Show vzdump backup configuration')"
        echo -e " 9) ${GREEN}zstd -d <backup>.zst${NC}                     - $(translate 'Decompress backup manually')"
        echo -e "10) ${GREEN}vzdump --stdexcludes${NC}                     - $(translate 'Show standard exclude patterns')"
        echo -e " ${DEF}0) $(translate ' Back to previous menu or Esc + Enter')"
        echo
        echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter a number, or write or paste a command: ') ${CL}"
        read -r user_input

        # Check for Esc key press
        if [[ "$user_input" == $'\x1b' ]]; then
            break
        fi

        case "$user_input" in
            1)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter VM/CT ID: ')${CL}"
                read -r id
                cmd="vzdump $id"
                ;;
            2)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter VM/CT ID: ')${CL}"
                read -r id
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter destination path: ')${CL}"
                read -r path
                cmd="vzdump $id --dumpdir $path"
                ;;
            3) cmd="vzdump --all" ;;
            4)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter backup path (.vma.zst): ')${CL}"
                read -r backup
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter VM ID: ')${CL}"
                read -r id
                cmd="qmrestore $backup $id"
                ;;
            5)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter backup path (.tar.zst): ')${CL}"
                read -r backup
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter CT ID: ')${CL}"
                read -r id
                cmd="pct restore $id $backup"
                ;;
            6) cmd="ls /var/lib/vz/dump" ;;
            7)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter storage name: ')${CL}"
                read -r storage
                cmd="pvesm list $storage"
                ;;
            8) cmd="cat /etc/vzdump.conf" ;;
            9)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter backup file (.zst): ')${CL}"
                read -r file
                cmd="zstd -d $file"
                ;;
            10) cmd="vzdump --stdexcludes" ;;
            0) break ;;
            *) cmd="$user_input" ;;
        esac

        echo -e "\n${GREEN}> $cmd${NC}\n"
        bash -c "$cmd"
        echo
        msg_success "$(translate 'Press ENTER to continue...')"
        read -r tmp
    done
}




# ===============================================================
# 09 System CLI Tools Commands
# ===============================================================
show_tools_commands() {
    while true; do
        clear
        echo -e "${YELLOW}$(translate 'System CLI Tools')${NC}"
        echo "--------------------------------------------"
        echo -e " 1) ${GREEN}htop${NC}              - $(translate 'Interactive process viewer (press q to exit)')"
        echo -e " 2) ${GREEN}btop${NC}              - $(translate 'Modern resource monitor (press q to exit)')"
        echo -e " 3) ${GREEN}iftop${NC}             - $(translate 'Real-time bandwidth usage (press q to exit)')"
        echo -e " 4) ${GREEN}iotop${NC}             - $(translate 'Monitor disk I/O usage (press q to exit)')"
        echo -e " 5) ${GREEN}tmux${NC}              - $(translate 'Terminal multiplexer (Ctrl+b then d to detach, or type exit)')"
        echo -e " 6) ${GREEN}iperf3${NC}            - $(translate 'Network throughput test (client/server)')"
        echo -e " 7) ${GREEN}iptraf-ng${NC}         - $(translate 'Real-time network monitoring (press q to exit)')"
        echo -e " 8) ${GREEN}msr-tools${NC}         - $(translate 'Read/write CPU model-specific registers')"
        echo -e " 9) ${GREEN}net-tools${NC}         - $(translate 'Legacy network tools (e.g., ifconfig)')"
        echo -e "10) ${GREEN}whois${NC}             - $(translate 'Lookup domain registration info')"
        echo -e "11) ${GREEN}libguestfs-tools${NC}  - $(translate 'Manage and inspect VM disk images')"
        echo -e " ${DEF}0) $(translate ' Back to previous menu or Esc + Enter')"
        echo
        echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter a number, or write or paste a command: ') ${CL}"
        read -r user_input

        # Check for Esc key press
        if [[ "$user_input" == $'\x1b' ]]; then
            break
        fi

        case "$user_input" in
            1) cmd="htop" ;;
            2) cmd="btop" ;;
            3) cmd="iftop" ;;
            4) cmd="iotop" ;;
            5) cmd="tmux" ;;
            6)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Run as server or client? [s/c]: ')${CL}"
                read -r mode
                if [[ "$mode" == "s" ]]; then
                    cmd="iperf3 -s"
                elif [[ "$mode" == "c" ]]; then
                    echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter server IP: ')${CL}"
                    read -r server_ip
                    cmd="iperf3 -c $server_ip"
                else
                    msg_info2 "$(translate 'Invalid option. Skipping.')"
                    read -r
                    continue
                fi
                ;;
            7) cmd="iptraf-ng" ;;
            8)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter MSR register (e.g. 0x10): ')${CL}"
                read -r reg
                cmd="rdmsr $reg"
                ;;
            9) cmd="ifconfig -a" ;;
            10)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter domain: ')${CL}"
                read -r domain
                cmd="whois $domain"
                ;;
            11)
                echo -en "${TAB}${BOLD}${YW}${HOLD}$(translate 'Enter disk image path: ')${CL}"
                read -r path
                cmd="virt-inspector $path"
                ;;
            0) break ;;
            *) cmd="$user_input" ;;
        esac

        if ! command -v $(echo "$cmd" | awk '{print $1}') &>/dev/null; then
            if whiptail --yesno "$(translate "$cmd is not installed. Do you want to install it now?")" 10 60; then
                msg_info "$(translate "Installing") $cmd..."
                apt update -qq >/dev/null 2>&1
                apt install -y $(echo "$cmd" | awk '{print $1}') >/dev/null 2>&1
                msg_ok "$(translate "$cmd installed successfully")"
                sleep 2
            else
                msg_info2 "$(translate 'Skipping installation.')"
                read -r
                continue
            fi
        fi

        echo -e "\n${GREEN}> $cmd${NC}\n"
        bash -c "$cmd"
        echo
        msg_success "$(translate 'Press ENTER to continue...')"
        read -r tmp
    done
}




# ===============================================================
# Help and Info Menu
# ===============================================================
while true; do
    OPTION=$(dialog --stdout \
        --title "$(translate 'Help and Info')" \
        --menu "\n$(translate 'Select a category of useful commands:')" 20 70 9 \
        1 "$(translate 'Useful System Commands')" \
        2 "$(translate 'VM and CT Management Commands')" \
        3 "$(translate 'Storage and Disks Commands')" \
        4 "$(translate 'Network Commands')" \
        5 "$(translate 'Updates and Packages Commands')" \
        6 "$(translate 'GPU Passthrough Commands')" \
        7 "$(translate 'ZFS Management Commands')" \
        8 "$(translate 'Backup and Restore Commands')" \
        9 "$(translate 'System CLI Tools')" \
        0 "$(translate 'Exit')")

    EXIT_STATUS=$?

    if [[ $EXIT_STATUS -ne 0 ]]; then

        break
    fi

    case $OPTION in
        1) show_system_commands ;;
        2) show_vm_ct_commands ;;
        3) show_storage_commands ;;
        4) show_network_commands ;;
        5) show_update_commands ;;
        6) show_gpu_commands ;;
        7) show_zfs_commands ;;
        8) show_backup_commands ;;
        9) show_tools_commands ;;
        0) clear; break ;;  
        *)
            msg_info2 "$(translate 'Invalid option, please try again.')"
            read -r
            ;;
    esac
done


