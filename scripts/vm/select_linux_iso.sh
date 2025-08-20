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


REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
ISO_DIR="/var/lib/vz/template/iso"

[[ -f "$UTILS_FILE" ]] && source "$UTILS_FILE"
load_language
initialize_cache

# ==============================================================
# FUNCIONES PRINCIPALES
# ==============================================================

function select_linux_iso() {

	local EXIT_FLAG="no"
	local header
	if [[ "$LANGUAGE" == "es" ]]; then
	  header=$(printf "%-43s│ %s" "       Descripción" "Fuente")
	else
	  header=$(printf "%-42s│ %s" "       $(translate "Description")" "$(translate "Source")")
	fi


  while [[ "$EXIT_FLAG" != "yes" ]]; do

    if [[ "$LANGUAGE" == "es" ]]; then

                CHOICE=$(dialog --clear \
                  --backtitle "ProxMenux" \
                  --title "Opciones de instalación de Linux" \
                  --menu "\nSeleccione el tipo de instalación de Linux:\n\n$header" \
                  18 72 10 \
                  1 "$(printf '%-35s│ %s' 'Instalar con metodo tradicional' 'Desde ISO oficial')" \
                  2 "$(printf '%-35s│ %s' 'Instalar con script Cloud-Init' 'Helper Scripts')" \
                  3 "$(printf '%-35s│ %s' 'Instalar con ISO personal' 'Almacenamiento local')" \
                  4 "Volver al menú principal" \
                  3>&1 1>&2 2>&3)
                        else
 
                local desc1 desc2 desc3 back
                desc1="$(translate "Install with traditional method")"
                desc2="$(translate "Install with Cloud-Init script")"
                desc3="$(translate "Install with personal ISO")"
                back="$(translate "Return to main menu")"
                          CHOICE=$(dialog --clear \
        --backtitle "ProxMenux" \
        --title "$(translate "Linux Installation Options")" \
        --menu "\n$(translate "Select the type of Linux installation:")\n\n$header" \
        18 70 10 \
        1 "$(printf '%-35s│ %s' "$desc1" "From official ISO")" \
        2 "$(printf '%-35s│ %s' "$desc2" "Helper Scripts")" \
        3 "$(printf '%-35s│ %s' "$desc3" "Local Storage")" \
        4 "$back" \
        3>&1 1>&2 2>&3)
    fi

    if [[ $? -ne 0 || "$CHOICE" == "4" ]]; then
      unset ISO_NAME ISO_TYPE ISO_URL ISO_FILE ISO_PATH HN
      return 1
    fi

    case "$CHOICE" in
      1) select_linux_iso_official && EXIT_FLAG="yes" ;;
      2) select_linux_cloudinit ;;
      3) select_linux_custom_iso && EXIT_FLAG="yes" ;;
    esac
  done
}




function select_linux_iso_official() {
  DISTROS=(
    "Ubuntu 25.04|Desktop|ProxMenux|https://releases.ubuntu.com/25.04/ubuntu-25.04-desktop-amd64.iso"
    "Ubuntu 24.04|Desktop|ProxMenux|https://releases.ubuntu.com/24.04/ubuntu-24.04.2-desktop-amd64.iso"
    "Ubuntu 22.04|Desktop|ProxMenux|https://releases.ubuntu.com/22.04/ubuntu-22.04.5-desktop-amd64.iso"
    "Ubuntu 20.04|Desktop|ProxMenux|https://releases.ubuntu.com/20.04/ubuntu-20.04.6-desktop-amd64.iso"
    "Ubuntu 25.04 Server|CLI|ProxMenux|https://releases.ubuntu.com/25.04/ubuntu-25.04-live-server-amd64.iso"
    "Ubuntu 24.04 Server|CLI|ProxMenux|https://releases.ubuntu.com/24.04/ubuntu-24.04.2-live-server-amd64.iso"
    "Ubuntu 22.04 Server|CLI|ProxMenux|https://releases.ubuntu.com/22.04/ubuntu-22.04.5-live-server-amd64.iso"
    "Ubuntu 20.04 Server|CLI|ProxMenux|https://releases.ubuntu.com/20.04/ubuntu-20.04.6-live-server-amd64.iso"
    "Debian 13|Desktop|ProxMenux|https://cdimage.debian.org/debian-cd/current/amd64/iso-dvd/debian-13.0.0-amd64-DVD-1.iso"
    "Debian 12|Desktop|ProxMenux|https://cdimage.debian.org/debian-cd/current/amd64/iso-dvd/debian-12.10.0-amd64-DVD-1.iso"
    "Debian 11|Desktop|ProxMenux|https://cdimage.debian.org/cdimage/archive/11.11.0/amd64/iso-dvd/debian-11.11.0-amd64-DVD-1.iso"
    "Debian 13 Netinst|CLI|ProxMenux|https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.0.0-amd64-netinst.iso"
    "Debian 12 Netinst|CLI|ProxMenux|https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-12.10.0-amd64-netinst.iso"
    "Debian 11 Netinst|CLI|ProxMenux|https://cdimage.debian.org/cdimage/archive/11.11.0/amd64/iso-cd/debian-11.11.0-amd64-netinst.iso"
    "Fedora Workstation 42|Desktop|ProxMenux|https://download.fedoraproject.org/pub/fedora/linux/releases/42/Workstation/x86_64/iso/Fedora-Workstation-Live-42-1.1.x86_64.iso"
    "Arch Linux|CLI|ProxMenux|https://geo.mirror.pkgbuild.com/iso/2025.07.01/archlinux-2025.07.01-x86_64.iso"
    "Rocky Linux 9.5|Desktop|ProxMenux|https://download.rockylinux.org/pub/rocky/9/isos/x86_64/Rocky-9.5-x86_64-dvd.iso"
    "Linux Mint 22.1|Desktop|ProxMenux|https://mirrors.edge.kernel.org/linuxmint/stable/22.1/linuxmint-22.1-cinnamon-64bit.iso"
    "openSUSE Leap 15.6|Desktop|ProxMenux|https://download.opensuse.org/distribution/leap/15.6/iso/openSUSE-Leap-15.6-DVD-x86_64-Media.iso"
    "Alpine Linux 3.21|Desktop|ProxMenux|https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/x86_64/alpine-virt-3.21.3-x86_64.iso"
    "Kali Linux 2025.1|Desktop|ProxMenux|https://cdimage.kali.org/kali-2025.1c/kali-linux-2025.1c-installer-amd64.iso"
    "Manjaro 25.0|Desktop|ProxMenux|https://download.manjaro.org/gnome/25.0.0/manjaro-gnome-25.0.0-250414-linux612.iso"
  )

  MENU_OPTIONS=()
  INDEX=0
  for entry in "${DISTROS[@]}"; do
    IFS='|' read -r NAME TYPE SOURCE URL <<< "$entry"
    LINE=$(printf "%-30s │ %-10s │ %s" "$NAME" "$TYPE" "$SOURCE")
    MENU_OPTIONS+=("$INDEX" "$LINE")
    URLS[$INDEX]="$entry"
    ((INDEX++))
  done

  HEADER="%-42s │ %-10s │ %s"
  HEADER_TEXT=$(printf "$HEADER" "            Distribution" "Type" "Script Install")

  CHOICE=$(dialog --backtitle "ProxMenux" \
    --title "$(translate "Official Linux Distributions")" \
    --menu "$(translate "Select the Linux distribution to install:")\n\n$HEADER_TEXT" 20 80 12 \
    "${MENU_OPTIONS[@]}" \
    3>&1 1>&2 2>&3)

  [[ $? -ne 0 ]] && return 1

  SELECTED="${URLS[$CHOICE]}"
  IFS='|' read -r ISO_NAME ISO_TYPE SOURCE ISO_URL <<< "$SELECTED"
  ISO_FILE=$(basename "$ISO_URL")
  ISO_PATH="$ISO_DIR/$ISO_FILE"

  HN=$(echo "$ISO_NAME" | \
    sed 's/ (.*)//' | \
    tr -cs '[:alnum:]' '-' | \
    sed 's/^-*//' | \
    sed 's/-*$//' | \
    cut -c1-63)
              
  export ISO_NAME ISO_TYPE ISO_URL ISO_FILE ISO_PATH HN
  export OS_TYPE="3"
  return 0
}


function select_linux_cloudinit() {
  local CLOUDINIT_OPTIONS=(
    "1" "Arch Linux   (Cloud-Init automated)   │ Helper Scripts"
    "2" "Debian 13    (Cloud-Init automated)   │ Helper Scripts"
    "3" "Debian 12    (Cloud-Init automated)   │ Helper Scripts"
    "4" "Ubuntu 22.04 (Cloud-Init automated)   │ Helper Scripts"
    "5" "Ubuntu 24.04 (Cloud-Init automated)   │ Helper Scripts"
    "6" "Ubuntu 24.10 (Cloud-Init automated)   │ Helper Scripts"
    "7" "Ubuntu 25.04 (Cloud-Init automated)   │ Helper Scripts"
    "8" "$(translate "Return to Main Menu")"
  )

  local script_selection
  script_selection=$(dialog --backtitle "ProxMenux" --title "$(translate "Cloud-Init Automated Installers")" \
    --menu "\n$(translate "Select a pre-configured Linux VM script to execute:")" 20 78 10 \
    "${CLOUDINIT_OPTIONS[@]}" 3>&1 1>&2 2>&3)

  [[ $? -ne 0 ]] && return

  case "$script_selection" in
    1)
      bash <(curl -s "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/archlinux-vm.sh")
      ;;
    2)
      bash <(curl -s "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/debian-13-vm.sh")
      ;;
    3)
      bash <(curl -s "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/debian-vm.sh")
      ;;
    4)
      bash <(curl -s "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/ubuntu2204-vm.sh")
      ;;
    5)
      bash <(curl -s "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/ubuntu2404-vm.sh")
      ;;
    6)
      bash <(curl -s "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/ubuntu2410-vm.sh")
      ;;
    7)
      bash <(curl -s "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/ubuntu2504-vm.sh")
      echo -e
      echo -e "after installation, checkout:\nhttps://github.com/community-scripts/ProxmoxVE/discussions/272"
      echo -e
      ;;  
    8)
      return
      ;;
  esac

  msg_success "$(translate "Press Enter to return to menu...")"
  read -r

  whiptail --title "Proxmox VE Helper-Scripts" \
           --msgbox "$(translate "Visit the website to discover more scripts, stay updated with the latest updates, and support the project:\n\nhttps://community-scripts.github.io/ProxmoxVE")" 15 70

  exec bash <(curl -s "$REPO_URL/scripts/vm/create_vm.sh")
}


function select_linux_custom_iso() {
  ISO_LIST=()
  while read -r line; do
    FILENAME=$(basename "$line")
    SIZE=$(du -h "$line" | cut -f1)
    ISO_LIST+=("$FILENAME" "$SIZE")
  done < <(find "$ISO_DIR" -type f -iname "*.iso" | sort)

  if [[ ${#ISO_LIST[@]} -eq 0 ]]; then
    header_info
    msg_error "$(translate "No ISO images found in") $ISO_DIR."
    sleep 2
    return 1
  fi

  ISO_FILE=$(dialog --backtitle "ProxMenux" --title "$(translate "Available ISO Images")" \
    --menu "$(translate "Select a custom ISO to use:")" 20 70 10 \
    "${ISO_LIST[@]}" 3>&1 1>&2 2>&3)

  if [[ -z "$ISO_FILE" ]]; then
    header_info
    msg_warn "$(translate "No ISO selected.")"
    return 1
  fi

  ISO_PATH="$ISO_DIR/$ISO_FILE"
  ISO_NAME="$ISO_FILE"             

  export ISO_PATH ISO_FILE ISO_NAME
  export OS_TYPE="3"
  return 0
}



function select_linux_other_scripts() {
local OTHER_OPTIONS=(
  "1" "Home Assistant OS VM (HAOS)       │ Helper Scripts"
  "2" "Docker VM (Debian + SSH + Docker) │ Helper Scripts"
  "3" "Nextcloud                         │ Helper Scripts"
  "4" "$(translate "Return to Main Menu")"
)

local choice
choice=$(dialog --backtitle "ProxMenux" \
  --title "$(translate "Other Prebuilt Linux VMs")" \
  --menu "\n$(translate "Select one of the ready-to-run Linux VMs:")" 18 70 10 \
  "${OTHER_OPTIONS[@]}" 3>&1 1>&2 2>&3)

if [[ $? -ne 0 || "$choice" == "4" ]]; then
  return 1
fi

case "$choice" in
  1)
    bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/haos-vm.sh)"
    ;;
  2)
    bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/docker-vm.sh)"
    echo -e
    echo -e "${TAB}$(translate "Default Login Credentials:")"
    echo -e "${TAB}Username: root"
    echo -e "${TAB}Password: docker"
    echo -e
    ;;
  3)
    bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/nextcloud-vm.sh)"
    echo -e
    echo -e "${TAB}$(translate "You can use the following credentials to login to the Nextcloud vm:")"
    echo -e "${TAB}Username: admin"
    echo -e "${TAB}$(translate "This VM requires extra installation steps, see install guide at:\nhttps://github.com/community-scripts/ProxmoxVE/discussions/144")"
    echo -e
    ;;
esac

msg_success "$(translate "Press Enter to return to menu...")"
read -r

whiptail --title "Proxmox VE Helper-Scripts" \
  --msgbox "$(translate "Visit the website to discover more scripts, stay updated with the latest updates, and support the project:\n\nhttps://community-scripts.github.io/ProxmoxVE")" 15 70

return 1

}






