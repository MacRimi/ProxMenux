#!/usr/bin/env bash

# ==========================================================
# ProxMenux - Windows ISO Selector
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Windows installation source selector for the ProxMenux VM
# creator. Offers two paths to obtain the Windows ISO and then
# hands over to the generic VM wizard for CPU, RAM, storage and
# optional GPU passthrough.
#
# Features:
# - Build an up-to-date Windows ISO via the UUP Dump creator.
# - Pick a Windows ISO already present in any Proxmox ISO storage.
# - Auto-detects the latest ISO created by UUP Dump.
# - Exports ISO metadata (name, path, OS_TYPE) for the wizard.
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
UUP_REPO="$LOCAL_SCRIPTS/vm"
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
        20 70 10 \
        1 "$(printf '%-34s│ %s' 'Instalar con ISO UUP Dump' 'UUP Dump ISO creator')" \
        2 "$(printf '%-34s│ %s' 'Instalar con ISO personal' 'Almacenamiento ISO')" \
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
        2 "$(printf '%-35s│ %s' "$desc2" "ISO Storage")" \
        3 "$back" \
        3>&1 1>&2 2>&3)
    fi

    if [[ $? -ne 0 || "$CHOICE" == "3" ]]; then
      unset ISO_NAME ISO_TYPE ISO_URL ISO_FILE ISO_PATH ISO_VOLID HN
      return 1
    fi

    case "$CHOICE" in
      1)
        if source "$UUP_REPO/uupdump_creator.sh"; then
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
  local volid
  ISO_LIST=()
  while read -r volid; do
    [[ -z "$volid" ]] && continue
    ISO_LIST+=("$volid" "$(iso_dialog_description "$volid")")
  done < <(iso_list_volids "windows")

  if [[ ${#ISO_LIST[@]} -eq 0 ]]; then
    header_info
    msg_error "$(translate "No ISO images found in Proxmox ISO storages.")"
    sleep 2
    return 1
  fi

  ISO_VOLID=$(dialog --backtitle "ProxMenux" --title "$(translate "Available ISO Images")" \
    --menu "$(translate "Choose a Windows ISO to use:")\n\n$(printf '%-42s │ %-14s │ %s' "$(translate "ISO")" "$(translate "Storage")" "$(translate "Size")")" 22 86 12 \
    "${ISO_LIST[@]}" 3>&1 1>&2 2>&3)

  [[ -z "$ISO_VOLID" ]] && msg_warn "$(translate "No ISO selected.")" && return 1

  ISO_FILE=$(iso_name_from_volid "$ISO_VOLID")
  ISO_PATH=$(iso_volid_to_path "$ISO_VOLID")
  ISO_NAME="$ISO_FILE"

  export ISO_PATH ISO_FILE ISO_NAME ISO_VOLID
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
  ISO_VOLID="local:iso/$ISO_NAME"

  export ISO_PATH ISO_FILE ISO_NAME ISO_VOLID
  export OS_TYPE="2"

  return 0
}
