#!/usr/bin/env bash

# ==========================================================
# ProxMenuX - Virtual Machine Creator Script
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
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
UUP_REPO="$REPO_URL/scripts/vm"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
ISO_DIR="/var/lib/vz/template/iso"

[[ -f "$UTILS_FILE" ]] && source "$UTILS_FILE"
load_language
initialize_cache
mkdir -p "$ISO_DIR"

function select_windows_iso() {
  local EXIT_FLAG="no"
  local header
  if [[ "$LANGUAGE" == "es" ]]; then
    header=$(printf "%-41s│ %s" "      Descripción" "Fuente")
  else
    header=$(printf "%-43s│ %s" "        $(translate "Description")" "$(translate "Source")")
  fi

  while [[ "$EXIT_FLAG" != "yes" ]]; do
    if [[ "$LANGUAGE" == "es" ]]; then
      CHOICE=$(dialog --clear \
        --backtitle "ProxMenux" \
        --title "Opciones de instalación de Windows" \
        --menu "\nSeleccione el tipo de instalación de Windows:\n\n$header" \
        18 70 10 \
        1 "$(printf '%-34s│ %s' 'Instalar con ISO UUP Dump' 'UUP Dump ISO creator')" \
        2 "$(printf '%-34s│ %s' 'Instalar con ISO personal' 'Almacenamiento local')" \
        3 "Volver al menú principal" \
        3>&1 1>&2 2>&3)
    else
      local desc1 desc2 back
      desc1="$(translate "Install with ISO from UUP Dump")"
      desc2="$(translate "Install with personal ISO")"
      back="$(translate "Return to main menu")"
      CHOICE=$(dialog --clear \
        --backtitle "ProxMenux" \
        --title "$(translate "Windows Installation Options")" \
        --menu "\n$(translate "Select the type of Windows installation:")\n\n$header" \
        18 70 10 \
        1 "$(printf '%-35s│ %s' "$desc1" "UUP Dump creator")" \
        2 "$(printf '%-35s│ %s' "$desc2" "Local Storage")" \
        3 "$back" \
        3>&1 1>&2 2>&3)
    fi

    if [[ $? -ne 0 || "$CHOICE" == "3" ]]; then
      unset ISO_NAME ISO_TYPE ISO_URL ISO_FILE ISO_PATH HN
      return 1
    fi

    case "$CHOICE" in
      1)
        if source <(curl -fsSL "$UUP_REPO/uupdump_creator.sh"); then
          run_uupdump_creator || return 1
          detect_latest_iso_created || return 1
          EXIT_FLAG="yes"
        else
          msg_error "$(translate "UUP Dump script not found.")"
          return 1
        fi
        ;;
      2)
        select_existing_iso || return 1
        EXIT_FLAG="yes"
        ;;
    esac
  done
}


function select_existing_iso() {
  ISO_LIST=()
  while read -r line; do
    FILENAME=$(basename "$line")
    SIZE=$(du -h "$line" | cut -f1)
    ISO_LIST+=("$FILENAME" "$SIZE")
  done < <(find "$ISO_DIR" -type f -iname "*.iso" ! -iname "virtio*" | sort)

  if [[ ${#ISO_LIST[@]} -eq 0 ]]; then
    header_info
    msg_error "$(translate "No ISO images found in") $ISO_DIR."
    sleep 2
    return 1
  fi

  ISO_FILE=$(dialog --backtitle "ProxMenux" --title "$(translate "Available ISO Images")" \
    --menu "$(translate "Choose a Windows ISO to use:")" 20 70 10 \
    "${ISO_LIST[@]}" 3>&1 1>&2 2>&3)

  [[ -z "$ISO_FILE" ]] && msg_warn "$(translate "No ISO selected.")" && return 1

  ISO_PATH="$ISO_DIR/$ISO_FILE"
  ISO_NAME="$ISO_FILE"

  export ISO_PATH ISO_FILE ISO_NAME
  export OS_TYPE="2"
  
  return 0
}

function detect_latest_iso_created() {
  ISO_FILE=$(find "$ISO_DIR" -maxdepth 1 -type f -iname "*.iso" ! -iname "virtio*" -printf "%T@ %p\n" | sort -n | awk '{print $2}' | tail -n 1)

  if [[ -z "$ISO_FILE" ]]; then
    msg_error "$(translate "No ISO file detected after UUP Dump process.")"
    sleep 2
    return 1
  fi

  ISO_NAME=$(basename "$ISO_FILE")
  ISO_PATH="$ISO_FILE"

  export ISO_PATH ISO_FILE ISO_NAME
  export OS_TYPE="2"

  return 0
}
