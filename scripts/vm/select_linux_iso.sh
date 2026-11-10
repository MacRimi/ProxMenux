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
#   Arch, Rocky, AlmaLinux, CentOS Stream, Oracle Linux, Mint,
#   Pop!_OS, Zorin OS, openSUSE, Alpine, Kali, Manjaro, CachyOS,
#   NixOS) with
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
                  2 "$(printf '%-35s│ %s' 'Instalar con script Cloud-Init' 'Community Scripts')" \
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
        2 "$(printf '%-35s│ %s' "$desc2" "Community Scripts")" \
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
    "Ubuntu 26.10|Desktop|ProxMenux|https://releases.ubuntu.com/26.10/ubuntu-26.10-desktop-amd64.iso"
    "Ubuntu 26.04 LTS|Desktop|ProxMenux|https://releases.ubuntu.com/26.04/ubuntu-26.04.1-desktop-amd64.iso"
    "Ubuntu 24.04 LTS|Desktop|ProxMenux|https://releases.ubuntu.com/24.04/ubuntu-24.04.5.1-desktop-amd64.iso"
    "Ubuntu 22.04 LTS|Desktop|ProxMenux|https://releases.ubuntu.com/22.04/ubuntu-22.04.5-desktop-amd64.iso"
    "Ubuntu 26.10 Server|CLI|ProxMenux|https://releases.ubuntu.com/26.10/ubuntu-26.10-live-server-amd64.iso"
    "Ubuntu 26.04 LTS Server|CLI|ProxMenux|https://releases.ubuntu.com/26.04/ubuntu-26.04.1-live-server-amd64.iso"
    "Ubuntu 24.04 LTS Server|CLI|ProxMenux|https://releases.ubuntu.com/24.04/ubuntu-24.04.5-live-server-amd64.iso"
    "Ubuntu 22.04 LTS Server|CLI|ProxMenux|https://releases.ubuntu.com/22.04/ubuntu-22.04.5-live-server-amd64.iso"
    "Debian 13|Desktop|ProxMenux|https://cdimage.debian.org/cdimage/archive/13.6.0/amd64/iso-dvd/debian-13.6.0-amd64-DVD-1.iso"
    "Debian 12|Desktop|ProxMenux|https://cdimage.debian.org/cdimage/archive/12.13.0/amd64/iso-dvd/debian-12.13.0-amd64-DVD-1.iso"
    "Debian 13 Netinst|CLI|ProxMenux|https://cdimage.debian.org/cdimage/archive/13.6.0/amd64/iso-cd/debian-13.6.0-amd64-netinst.iso"
    "Debian 12 Netinst|CLI|ProxMenux|https://cdimage.debian.org/cdimage/archive/12.13.0/amd64/iso-cd/debian-12.13.0-amd64-netinst.iso"
    "Fedora Workstation 45|Desktop|ProxMenux|https://download.fedoraproject.org/pub/fedora/linux/releases/45/Workstation/x86_64/iso/Fedora-Workstation-Live-45-1.4.x86_64.iso"
    "Fedora Workstation 44|Desktop|ProxMenux|https://download.fedoraproject.org/pub/fedora/linux/releases/44/Workstation/x86_64/iso/Fedora-Workstation-Live-44-1.7.x86_64.iso"
    "Arch Linux|CLI|ProxMenux|https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso"
    "Rocky Linux 10|Desktop|ProxMenux|https://download.rockylinux.org/pub/rocky/10/isos/x86_64/Rocky-10-latest-x86_64-dvd.iso"
    "Rocky Linux 9|Desktop|ProxMenux|https://download.rockylinux.org/pub/rocky/9/isos/x86_64/Rocky-9-latest-x86_64-dvd.iso"
    "AlmaLinux 10|Desktop|ProxMenux|https://repo.almalinux.org/almalinux/10/isos/x86_64/AlmaLinux-10-latest-x86_64-dvd.iso"
    "AlmaLinux 10 Minimal|CLI|ProxMenux|https://repo.almalinux.org/almalinux/10/isos/x86_64/AlmaLinux-10-latest-x86_64-minimal.iso"
    "AlmaLinux 9|Desktop|ProxMenux|https://repo.almalinux.org/almalinux/9/isos/x86_64/AlmaLinux-9-latest-x86_64-dvd.iso"
    "CentOS Stream 10|Desktop|ProxMenux|https://mirror.stream.centos.org/10-stream/BaseOS/x86_64/iso/CentOS-Stream-10-latest-x86_64-dvd1.iso"
    "CentOS Stream 9|Desktop|ProxMenux|https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/iso/CentOS-Stream-9-latest-x86_64-dvd1.iso"
    "Oracle Linux 10|Desktop|ProxMenux|https://yum.oracle.com/ISOS/OracleLinux/OL10/u2/x86_64/OracleLinux-R10-U2-x86_64-dvd.iso"
    "Oracle Linux 9|Desktop|ProxMenux|https://yum.oracle.com/ISOS/OracleLinux/OL9/u8/x86_64/OracleLinux-R9-U8-x86_64-dvd.iso"
    "Linux Mint 22.3 Cinnamon|Desktop|ProxMenux|https://mirrors.edge.kernel.org/linuxmint/stable/22.3/linuxmint-22.3-cinnamon-64bit.iso"
    "Linux Mint 22.3 Xfce|Desktop|ProxMenux|https://mirrors.edge.kernel.org/linuxmint/stable/22.3/linuxmint-22.3-xfce-64bit.iso"
    "openSUSE Leap 16.1|Desktop|ProxMenux|https://download.opensuse.org/distribution/leap/16.1/offline/Leap-16.1-offline-installer-x86_64.install.iso"
    "openSUSE Leap 16.0|Desktop|ProxMenux|https://download.opensuse.org/distribution/leap/16.0/offline/Leap-16.0-offline-installer-x86_64.install.iso"
    "Alpine Linux 3.24|CLI|ProxMenux|https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-virt-3.24.4-x86_64.iso"
    "Kali Linux 2026.3|Desktop|ProxMenux|https://cdimage.kali.org/kali-2026.3/kali-linux-2026.3-installer-amd64.iso"
    "Manjaro 26.1|Desktop|ProxMenux|https://download.manjaro.org/gnome/26.1.0/manjaro-gnome-26.1.0-260812-linux71.iso"
    "Pop!_OS 24.04|Desktop|ProxMenux|https://iso.pop-os.org/24.04/amd64/generic/28/pop-os_24.04_amd64_generic_28.iso"
    "Zorin OS 18.1 Core|Desktop|ProxMenux|https://mirrors.edge.kernel.org/zorinos-isos/18/Zorin-OS-18.1-Core-64-bit.iso"
    "Zorin OS 18.1 Lite|Desktop|ProxMenux|https://mirrors.edge.kernel.org/zorinos-isos/18/Zorin-OS-18.1-Lite-64-bit.iso"
    "CachyOS|Desktop|ProxMenux|https://iso.cachyos.org/desktop/260809/cachyos-desktop-linux-260809.iso"
    "NixOS 26.05|Desktop|ProxMenux|https://channels.nixos.org/nixos-26.05/latest-nixos-graphical-x86_64-linux.iso"
    "NixOS 26.05 Minimal|CLI|ProxMenux|https://channels.nixos.org/nixos-26.05/latest-nixos-minimal-x86_64-linux.iso"
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

  # The heading starts where dialog draws the rows: after the tag column,
  # with the list centred in its window, as the menu search lines up its own.
  local width=76 last_tag=$((INDEX - 1))
  local row_width=$((30 + 3 + 10 + 3 + 9))
  local pad=$(( (width - 8 - row_width - ${#last_tag} - 2) / 2 + ${#last_tag} + 4 ))
  HEADER_TEXT=$(printf "%*s%-30s │ %-10s │ %s" "$pad" "" \
    "$(translate "Description")" "$(translate "Type")" "$(translate "Source")")

  CHOICE=$(dialog --backtitle "ProxMenux" --no-collapse \
    --title "$(translate "Official Linux Distributions")" \
    --menu "$(translate "Select the Linux distribution to install:")\n\n$HEADER_TEXT" 22 $width 12 \
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
  # The maintained Debian and Ubuntu helpers select their own release.
  local CLOUDINIT_OPTIONS=(
    "1" "Arch Linux  (Cloud-Init automated)   │ Community Scripts"
    "2" "Debian      (Cloud-Init automated)   │ Community Scripts"
    "3" "Ubuntu      (Cloud-Init automated)   │ Community Scripts"
    "4" "$(translate "Return to Main Menu")"
  )

  local script_selection script_url script_content
  script_selection=$(dialog --backtitle "ProxMenux" --title "$(translate "Cloud-Init Automated Installers")" \
    --menu "\n$(translate "Select a pre-configured Linux VM script to execute:")" 20 78 10 \
    "${CLOUDINIT_OPTIONS[@]}" 3>&1 1>&2 2>&3)

  [[ $? -ne 0 ]] && return

  case "$script_selection" in
    1)
      script_url="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/archlinux-vm.sh"
      ;;
    2)
      script_url="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/debian-vm.sh"
      ;;
    3)
      script_url="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/ubuntu-vm.sh"
      ;;
    4)
      return
      ;;
    *)
      return 1
      ;;
  esac

  # Do not execute a failed or partial download through process substitution.
  if ! script_content=$(curl -fsSL --connect-timeout 5 --max-time 60 "$script_url") || [[ -z "${script_content//[[:space:]]/}" ]]; then
    dialog --title "Community Scripts" --msgbox "$(translate "Error: Failed to download the script.")" 8 70
    return 1
  fi
  bash -c "$script_content" || return $?

  msg_success "$(translate "Press Enter to return to menu...")"
  read -r

  whiptail --title "Community Scripts" \
           --msgbox "$(translate "Visit the website to discover more scripts, stay updated with the latest updates, and support the project:\n\nhttps://community-scripts.github.io/ProxmoxVE")" 15 70

  exec bash "$LOCAL_SCRIPTS/menus/create_vm_menu.sh"
}


function select_linux_custom_iso() {
  local volid
  local name display_name tag storage
  local selected_tag
  declare -A ISO_VOLID_BY_TAG=()
  ISO_LIST=()
  while read -r volid; do
    [[ -z "$volid" ]] && continue
    name=$(iso_name_from_volid "$volid")
    display_name=$(iso_display_name "$name" 58)
    storage=$(iso_storage_from_volid "$volid")
    tag="$display_name"
    if [[ -n "${ISO_VOLID_BY_TAG[$tag]:-}" ]]; then
      tag="$(iso_display_name "$name ($storage)" 58)"
    fi
    ISO_VOLID_BY_TAG["$tag"]="$volid"
    ISO_LIST+=("$tag" "$(iso_dialog_description "$volid")")
  done < <(iso_list_volids "all")

  if [[ ${#ISO_LIST[@]} -eq 0 ]]; then
    header_info
    msg_error "$(translate "No ISO images found in Proxmox ISO storages.")"
    sleep 2
    return 1
  fi

  selected_tag=$(dialog --backtitle "ProxMenux" --title "$(translate "Available ISO Images")" \
    --menu "$(translate "Select a custom ISO to use:")\n\n$(printf '%-58s %-10s %s' "$(translate "ISO")" "$(translate "Storage")" "$(translate "Size")")" 22 86 12 \
    "${ISO_LIST[@]}" 3>&1 1>&2 2>&3)

  if [[ -z "$selected_tag" ]]; then
    header_info
    msg_warn "$(translate "No ISO selected.")"
    return 1
  fi
  ISO_VOLID="${ISO_VOLID_BY_TAG[$selected_tag]}"

  ISO_FILE=$(iso_name_from_volid "$ISO_VOLID")
  ISO_PATH=$(iso_volid_to_path "$ISO_VOLID")
  ISO_NAME="$ISO_FILE"             

  export ISO_PATH ISO_FILE ISO_NAME ISO_VOLID
  export OS_TYPE="3"
  return 0
}



function select_linux_other_scripts() {
local OTHER_OPTIONS=(
  "1" "Home Assistant OS VM (HAOS)       │ Community Scripts"
  "2" "Docker VM (Debian + SSH + Docker) │ Community Scripts"
  "3" "Nextcloud                         │ Community Scripts"
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

whiptail --title "Community Scripts" \
  --msgbox "$(translate "Visit the website to discover more scripts, stay updated with the latest updates, and support the project:\n\nhttps://community-scripts.github.io/ProxmoxVE")" 15 70

return 1

}
