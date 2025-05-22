#!/usr/bin/env bash

# ==========================================================
# ProxMenuX - Virtual Machine Creator Script
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 07/05/2025
# ==========================================================
# Description:
# This script is part of the central ProxMenux VM creation module. It allows users
# to create virtual machines (VMs) in Proxmox VE using either default or advanced
# configurations, streamlining the deployment of Linux, Windows, and other systems.
#
# Key features:
# - Supports both virtual disk creation and physical disk passthrough.
# - Automates CPU, RAM, BIOS, network and storage configuration.
# - Provides a user-friendly menu to select OS type, ISO image and disk interface.
# - Automatically generates a detailed and styled HTML description for each VM.
#
# All operations are designed to simplify and accelerate VM creation in a 
# consistent and maintainable way, using ProxMenux standards.
# ==========================================================


BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"

[[ -f "$UTILS_FILE" ]] && source "$UTILS_FILE"
load_language
initialize_cache

ISO_DIR="/var/lib/vz/template/iso"
mkdir -p "$ISO_DIR"

function select_nas_iso() {

  local NAS_OPTIONS=(
    "1" "Synology DSM   VM          (Loader Linux-based)"
    "2" "TrueNAS SCALE  VM          (Fangtooth)"
    "3" "TrueNAS CORE   VM          (FreeBSD based)"
    "4" "OpenMediaVault VM          (Debian based)"
    "5" "Rockstor       VM          (openSUSE based)"
    "6" "ZimaOS         VM          (R0GGER proxmox-zimaos)"
    "7" "$(translate "Return to Main Menu")"
  )

  local NAS_TYPE
  NAS_TYPE=$(dialog --backtitle "ProxMenux" \
    --title "$(translate "NAS Systems")" \
    --menu "\n$(translate "Select the NAS system to install:")" 18 70 10 \
    "${NAS_OPTIONS[@]}" 3>&1 1>&2 2>&3)


  [[ $? -ne 0 ]] && return 1

  case "$NAS_TYPE" in
    1)
      bash <(curl -s "$REPO_URL/scripts/vm/synology.sh")
      msg_success "$(translate "Press Enter to return to menu...")"
      read -r
      return 1
      ;;
    2)
      ISO_NAME="TrueNAS SCALE 25 (Fangtooth)"
      ISO_URL="https://download.truenas.com/TrueNAS-SCALE-Fangtooth/25.04.0/TrueNAS-SCALE-25.04.0.iso"
      ISO_FILE="TrueNAS-SCALE-25.04.0.iso"
      ISO_PATH="$ISO_DIR/$ISO_FILE"
      HN="TrueNAS-Scale"
      ;;
    3)
      ISO_NAME="TrueNAS CORE 13.3"
      ISO_URL="https://download.freenas.org/13.3/STABLE/latest/x64/TrueNAS-13.3-U1.2.iso"
      ISO_FILE="TrueNAS-13.3-U1.2.iso"
      ISO_PATH="$ISO_DIR/$ISO_FILE"
      HN="TrueNAS-Core"
      ;;
    4)
      ISO_NAME="OpenMediaVault 7.4.17"
      ISO_URL="https://sourceforge.net/projects/openmediavault/files/iso/7.4.17/openmediavault_7.4.17-amd64.iso/download"
      ISO_FILE="openmediavault_7.4.17-amd64.iso"
      ISO_PATH="$ISO_DIR/$ISO_FILE"
      HN="OpenMediaVault"
      ;;
    5)
      ISO_NAME="Rockstor"
      ISO_URL="https://rockstor.com/downloads/installer/leap/15.6/x86_64/Rockstor-Leap15.6-generic.x86_64-5.0.15-0.install.iso"
      ISO_FILE="Rockstor-Leap15.6-generic.x86_64-5.0.15-0.install.iso"
      ISO_PATH="$ISO_DIR/$ISO_FILE"
      HN="Rockstor"
      ;;
    6)
      HN="ZimaOS-VM"
      if ! confirm_vm_creation; then
        return 1
      fi
      bash -c "$(wget -qLO - https://raw.githubusercontent.com/R0GGER/proxmox-zimaos/refs/heads/main/zimaos_zimacube.sh)"
      msg_success "$(translate "Press Enter to return to menu...")"
      read -r
      
      whiptail --title "Proxmox VE - ZimaOS" \
        --msgbox "$(translate "ZimaOS installer script by R0GGER\n\nVisit the GitHub repo to learn more, contribute, or support the project:\n\nhttps://github.com/R0GGER/proxmox-zimaos")" 15 70

      return 1
      ;;

    7)
      return 1
      ;;
  esac

  export ISO_NAME ISO_URL ISO_FILE ISO_PATH HN
  return 0
}
