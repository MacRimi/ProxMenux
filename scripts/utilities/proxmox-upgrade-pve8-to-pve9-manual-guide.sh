#!/bin/bash

# ==========================================================
# ProxMenu - Manual Proxmox VE 8 to 9 Upgrade Guide
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 13/08/2025
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

show_proxmox_upgrade_manual_guide() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "Proxmox VE 8 to 9 Manual Upgrade Guide")"
        
    echo -e "${TAB}${BL}------------------------------------------------------------------------${CL}"
    echo -e 
    echo -e "${TAB}${BGN}$(translate "Source:")${CL} ${BL}https://pve.proxmox.com/wiki/Upgrade_from_8_to_9${CL}"
    echo -e
    echo -e 
    echo -e "${TAB}${BOLD}$(translate "IMPORTANT PREREQUISITES:")${CL}"
    echo -e
    echo -e "${TAB}${BGN}• $(translate "System must be updated to latest PVE 8.4+ before starting")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Use SSH or terminal access (SSH recommended)")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Use tmux or screen to avoid interruptions")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Have valid backups of all VMs and containers")${CL}"
    echo -e "${TAB}${BGN}• $(translate "At least 5GB free space on root filesystem")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Do not run the upgrade from the Web UI virtual console (it will disconnect)")${CL}"
    echo -e 
    echo -e "${TAB}${BL}------------------------------------------------------------------------${CL}"
    echo -e 
    

    show_command "1" \
        "$(translate "Update system to latest PVE 8.4+ (if not done already):")\n\n" \
        "apt update && apt dist-upgrade -y" \
        "$(translate "Or use ProxMenux update function")" \
        "\n\n"
        

    show_command "2" \
        "$(translate "Verify PVE version (must be 8.4.1 or newer):")\n\n" \
        "pveversion" \
        "" \
        "\n"


    show_command "2.1" \
        "${YW}$(translate "If this node runs hyper-converged Ceph: ensure Ceph is 19.x (Squid) BEFORE upgrading PVE.")${CL}\n\n" \
        "ceph --version" \
        "$(translate "If not 19.x, upgrade Ceph (Reef→Squid) first per the official guide:") ${BL}https://pve.proxmox.com/wiki/Ceph_Squid${CL}" \
        "\n"



    show_command "3" \
        "$(translate "Run upgrade checklist script:")\n\n" \
        "pve8to9 --full" \
        "${YW}$(translate "If it warns about 'systemd-boot' meta-package, remove it:")${CL} apt remove systemd-boot" \
        "\n"
    

    show_command "4" \
        "$(translate "Start terminal multiplexer (recommended):")\n\n" \
        "tmux new-session -s upgrade    ${DARK_GRAY}$(translate "# Recommended: avoids disconnection during upgrade")${CL}\n\n    screen -S upgrade              ${DARK_GRAY}$(translate "# Alternative if you prefer screen")${CL}" \
        "" \
        "\n"
    

    show_command "5" \
        "$(translate "Update Debian repositories to Trixie:")\n\n" \
        "sed -i 's/bookworm/trixie/g' /etc/apt/sources.list" \
        "" \
        "\n"
    

    show_command "6" \
        "${YW}$(translate "Update PVE enterprise repository (Only if using enterprise):")${CL}\n\n" \
        "${CUS}sed -i 's/bookworm/trixie/g' /etc/apt/sources.list.d/pve-enterprise.list${CL}" \
        "$(translate "Skip this step if using no-subscription repository")" \
        "\n\n"
    

    show_command "7" \
        "${YW}$(translate "Add new PVE 9 enterprise repository (deb822 format) (Only if using enterprise):")${CL}\n\n" \
        "${CUS}cat > /etc/apt/sources.list.d/pve-enterprise.sources << EOF
Types: deb
URIs: https://enterprise.proxmox.com/debian/pve
Suites: trixie
Components: pve-enterprise
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF${CL}" \
        "$(translate "Only if using enterprise subscription")" \
        "\n\n"
    

    show_command "8" \
        "$(translate "OR add new PVE 9 no-subscription repository:")\n\n" \
        "cat > /etc/apt/sources.list.d/proxmox.sources << EOF
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF" \
        "$(translate "Only if using no-subscription repository")" \
        "\n\n"


    show_command "8.1" \
        "$(translate "Refresh APT index and verify repositories:")\n\n" \
        "apt update && apt policy | sed -n '1,120p'" \
        "$(translate "Ensure there are no errors and that proxmox-ve candidate shows 9.x")" \
        "\n"


    show_command "9" \
        "${YW}$(translate "Update Ceph repository (Only if using Ceph):")${CL}\n\n" \
        "${CUS}cat > /etc/apt/sources.list.d/ceph.sources << EOF
Types: deb
URIs: http://download.proxmox.com/debian/ceph-squid
Suites: trixie
Components: no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF${CL}" \
        "$(translate "Use enterprise URL if you have subscription.")" \
        "\n\n"
    

    show_command "10" \
        "$(translate "Remove old repository files:")\n\n" \
        "rm -f /etc/apt/sources.list.d/pve-enterprise.list /etc/apt/sources.list.d/ceph.list" \
        "$(translate "Also comment any remaining 'bookworm' entries in *.list if present.")" \
        "\n"
    

    show_command "11" \
        "$(translate "Update package index:")\n\n" \
        "apt update" \
        "" \
        "\n"
    

    show_command "12" \
        "$(translate "Disable kernel audit messages (optional but recommended):")\n\n" \
        "systemctl disable --now systemd-journald-audit.socket" \
        "" \
        "\n"
    

    show_command "13" \
        "$(translate "Start the main system upgrade:")\n\n" \
        "apt dist-upgrade" \
        "$(translate "This will take time. Answer prompts carefully - see notes below.")\n" \
        "\n"
    

    echo -e "${TAB}${BOLD}$(translate "UPGRADE PROMPTS - RECOMMENDED ANSWERS:")${CL}"
    echo -e
    echo -e "${TAB}${BGN}/etc/issue:${CL} ${YW}$(translate "Keep current version (N)")${CL}"
    echo -e "${TAB}${BGN}/etc/lvm/lvm.conf:${CL} ${YW}$(translate "Install maintainer's version (Y)")${CL}"
    echo -e "${TAB}${BGN}/etc/ssh/sshd_config:${CL} ${YW}$(translate "Install maintainer's version (Y)")${CL}"
    echo -e "${TAB}${BGN}/etc/default/grub:${CL} ${YW}$(translate "Keep current version (N) if modified")${CL}"
    echo -e "${TAB}${BGN}/etc/chrony/chrony.conf:${CL} ${YW}$(translate "Install maintainer's version (Y)")${CL}"
    echo -e "${TAB}${BGN}$(translate "Service restarts:")${CL} ${YW}$(translate "Use default (Yes)")${CL}"
    echo -e "${TAB}${BGN}apt-listchanges:${CL} ${YW}$(translate "Press 'q' to exit")${CL}"
    echo -e 
    echo -e 
    echo -e 


    show_command "13.1" \
        "${YW}$(translate "If booting in EFI mode with root on LVM: install GRUB for EFI")${CL}\n\n" \
        "[ -d /sys/firmware/efi ] && apt install grub-efi-amd64" \
        "$(translate "Per official known issues; ensures proper boot after upgrade")" \
        "\n"


    show_command "14" \
        "$(translate "Run checklist again to verify upgrade:")\n\n" \
        "pve8to9 --full" \
        "$(translate "Should show fewer or no issues")" \
        "\n"
    

    show_command "15" \
        "$(translate "Reboot the system:")\n\n" \
        "reboot" \
        "" \
        "\n"
    

    show_command "16" \
        "$(translate "After reboot, verify PVE version:")\n\n" \
        "pveversion" \
        "$(translate "Should show pve-manager/9.x.x")" \
        "\n"
    

    show_command "17" \
        "$(translate "Optional: Modernize repository sources:")\n\n" \
        "apt modernize-sources" \
        "$(translate "Converts to deb822; keeps .list backups as .bak")" \
        "\n"
    
    echo -e "${TAB}${BL}------------------------------------------------------------------------${CL}"
    echo -e 
    echo -e 
    echo -e "${TAB}${BOLD}$(translate "CLUSTER UPGRADE NOTES:")${CL}"
    echo -e
    echo -e "${TAB}${BGN}• $(translate "Upgrade one node at a time")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Migrate VMs away from node being upgraded")${CL}"
    echo -e "${TAB}${BGN}• $(translate "Wait for each node to complete before starting next")${CL}"
    echo -e "${TAB}${BGN}• $(translate "HA groups will be migrated to HA rules automatically")${CL}"
    echo -e 
    echo -e 
    
    echo -e 
    echo -e "${TAB}${BOLD}$(translate "TROUBLESHOOTING:")${CL}"
    echo -e
    echo -e "${TAB}${BGN}$(translate "If upgrade fails:")${CL} ${YW}apt -f install${CL}"
    echo -e "${TAB}${BGN}$(translate "If repositories error:")${CL} ${YW}Check /etc/apt/sources.list*${CL}"
    echo -e "${TAB}${BGN}$(translate "If 'proxmox-ve' removal warning:")${CL} ${YW}Fix repository configuration (ensure PVE 9 repo active)${CL}"
    echo -e "${TAB}${BGN}$(translate "Emergency recovery:")${CL} ${YW}Boot from rescue system${CL}"
    echo -e 
    echo -e 
    
    echo -e 
    msg_success "$(translate "Press Enter to return to menu...")"
    echo -e 
    read -r
}


# Main execution
show_proxmox_upgrade_manual_guide