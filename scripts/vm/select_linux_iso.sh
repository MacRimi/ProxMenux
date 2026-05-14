#!/usr/bin/env bash

# ==========================================================
# ProxMenux - Linux ISO Selector
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Linux installation source selector for the ProxMenux VM creator.
# Offers three paths to obtain the Linux installation media and
# also exposes the "Others" prebuilt VM menu used by the main
# dispatcher for community-maintained installers.
#
# Features:
# - Curated list of official Linux ISOs (Ubuntu, Debian, Fedora,
#   Arch, Rocky, Mint, openSUSE, Alpine, Kali, Manjaro) with
#   direct download URLs.
# - Cloud-Init automated installers (community scripts).
# - Pick an existing ISO from any Proxmox ISO storage.
# - Separate "Others Prebuilt VMs" selector (HAOS, Docker, Nextcloud)
#   used by the main menu's Community Scripts path.
# ==========================================================


LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
ISO_DIR="/var/lib/vz/template/iso"

[[ -f "$UTILS_FILE" ]] && source "$UTILS_FILE"
if [[ -f "$LOCAL_SCRIPTS/global/iso_storage_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS/global/iso_storage_helpers.sh"
fi
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
                  20 70 10 \
                  1 "$(printf '%-35s│ %s' 'Instalar con metodo tradicional' 'Desde ISO oficial')" \
                  2 "$(printf '%-35s│ %s' 'Instalar con script Cloud-Init' 'Helper Scripts')" \
                  3 "$(printf '%-35s│ %s' 'Instalar con ISO personal' 'Almacenamiento ISO')" \
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
        3 "$(printf '%-35s│ %s' "$desc3" "ISO Storage")" \
        4 "$back" \
        3>&1 1>&2 2>&3)
    fi

    if [[ $? -ne 0 || "$CHOICE" == "4" ]]; then
      unset ISO_NAME ISO_TYPE ISO_URL ISO_FILE ISO_PATH ISO_VOLID HN
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
    "Ubuntu 25.10|Desktop|ProxMenux|https://releases.ubuntu.com/25.10/ubuntu-25.10-desktop-amd64.iso"
    "Ubuntu 24.04|Desktop|ProxMenux|https://releases.ubuntu.com/24.04/ubuntu-24.04.4-desktop-amd64.iso"
    "Ubuntu 22.04|Desktop|ProxMenux|https://releases.ubuntu.com/22.04/ubuntu-22.04.5-desktop-amd64.iso"
    "Ubuntu 20.04|Desktop|ProxMenux|https://releases.ubuntu.com/20.04/ubuntu-20.04.6-desktop-amd64.iso"
    "Ubuntu 25.10 Server|CLI|ProxMenux|https://releases.ubuntu.com/25.10/ubuntu-25.10-live-server-amd64.iso"
    "Ubuntu 24.04 Server|CLI|ProxMenux|https://releases.ubuntu.com/24.04/ubuntu-24.04.4-live-server-amd64.iso"
    "Ubuntu 22.04 Server|CLI|ProxMenux|https://releases.ubuntu.com/22.04/ubuntu-22.04.5-live-server-amd64.iso"
    "Ubuntu 20.04 Server|CLI|ProxMenux|https://releases.ubuntu.com/20.04/ubuntu-20.04.6-live-server-amd64.iso"
    "Debian 13|Desktop|ProxMenux|https://cdimage.debian.org/debian-cd/current/amd64/iso-dvd/debian-13.4.0-amd64-DVD-1.iso"
    "Debian 12|Desktop|ProxMenux|https://cdimage.debian.org/cdimage/archive/12.13.0/amd64/iso-dvd/debian-12.13.0-amd64-DVD-1.iso"
    "Debian 11|Desktop|ProxMenux|https://cdimage.debian.org/cdimage/archive/11.11.0/amd64/iso-dvd/debian-11.11.0-amd64-DVD-1.iso"
    "Debian 13 Netinst|CLI|ProxMenux|https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.4.0-amd64-netinst.iso"
    "Debian 12 Netinst|CLI|ProxMenux|https://cdimage.debian.org/cdimage/archive/12.13.0/amd64/iso-cd/debian-12.13.0-amd64-netinst.iso"
    "Debian 11 Netinst|CLI|ProxMenux|https://cdimage.debian.org/cdimage/archive/11.11.0/amd64/iso-cd/debian-11.11.0-amd64-netinst.iso"
    "Fedora Workstation 42|Desktop|ProxMenux|https://download.fedoraproject.org/pub/fedora/linux/releases/42/Workstation/x86_64/iso/Fedora-Workstation-Live-42-1.1.x86_64.iso"
    "Arch Linux|CLI|ProxMenux|https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso"
    "Rocky Linux 9|Desktop|ProxMenux|https://download.rockylinux.org/pub/rocky/9/isos/x86_64/Rocky-9-latest-x86_64-dvd.iso"
    "Linux Mint 22.1|Desktop|ProxMenux|https://mirrors.edge.kernel.org/linuxmint/stable/22.1/linuxmint-22.1-cinnamon-64bit.iso"
    "openSUSE Leap 15.6|Desktop|ProxMenux|https://download.opensuse.org/distribution/leap/15.6/iso/openSUSE-Leap-15.6-DVD-x86_64-Media.iso"
    "Alpine Linux 3.21|Desktop|ProxMenux|https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/x86_64/alpine-virt-3.21.3-x86_64.iso"
    "Kali Linux 2026.1|Desktop|ProxMenux|https://cdimage.kali.org/kali-2026.1/kali-linux-2026.1-installer-amd64.iso"
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
    --menu "$(translate "Select the Linux distribution to install:")\n\n$HEADER_TEXT" 20 70 12 \
    "${MENU_OPTIONS[@]}" \
    3>&1 1>&2 2>&3)

  [[ $? -ne 0 ]] && return 1

  SELECTED="${URLS[$CHOICE]}"
  IFS='|' read -r ISO_NAME ISO_TYPE SOURCE ISO_URL <<< "$SELECTED"
  ISO_FILE=$(basename "$ISO_URL")
  ISO_PATH="$ISO_DIR/$ISO_FILE"
  ISO_VOLID="local:iso/$ISO_FILE"

  HN=$(echo "$ISO_NAME" | \
    sed 's/ (.*)//' | \
    tr -cs '[:alnum:]' '-' | \
    sed 's/^-*//' | \
    sed 's/-*$//' | \
    cut -c1-63)
              
  export ISO_NAME ISO_TYPE ISO_URL ISO_FILE ISO_PATH ISO_VOLID HN
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

  exec bash "$LOCAL_SCRIPTS/menus/create_vm_menu.sh"
}


function select_linux_custom_iso() {
  local volid
  ISO_LIST=()
  while read -r volid; do
    [[ -z "$volid" ]] && continue
    ISO_LIST+=("$volid" "$(iso_dialog_description "$volid")")
  done < <(iso_list_volids "all")

  if [[ ${#ISO_LIST[@]} -eq 0 ]]; then
    header_info
    msg_error "$(translate "No ISO images found in Proxmox ISO storages.")"
    sleep 2
    return 1
  fi

  ISO_VOLID=$(dialog --backtitle "ProxMenux" --title "$(translate "Available ISO Images")" \
    --menu "$(translate "Select a custom ISO to use:")\n\n$(printf '%-42s │ %-14s │ %s' "$(translate "ISO")" "$(translate "Storage")" "$(translate "Size")")" 22 86 12 \
    "${ISO_LIST[@]}" 3>&1 1>&2 2>&3)

  if [[ -z "$ISO_VOLID" ]]; then
    header_info
    msg_warn "$(translate "No ISO selected.")"
    return 1
  fi

  ISO_FILE=$(iso_name_from_volid "$ISO_VOLID")
  ISO_PATH=$(iso_volid_to_path "$ISO_VOLID")
  ISO_NAME="$ISO_FILE"             

  export ISO_PATH ISO_FILE ISO_NAME ISO_VOLID
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
  --menu "\n$(translate "Select one of the ready-to-run Linux VMs:")" 20 70 10 \
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


