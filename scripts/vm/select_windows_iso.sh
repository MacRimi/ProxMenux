#!/usr/bin/env bash

# ==============================================================
# ProxMenux - Windows ISO Selector (Dialog Edition)
# ==============================================================

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
  local CHOICE
  CHOICE=$(dialog --backtitle "ProxMenux" --title "$(translate "Windows ISO")" \
    --menu "$(translate "Select how to provide the Windows ISO:")" 15 60 5 \
    1 "$(translate "Use existing ISO from storage")" \
    2 "$(translate "Download ISO using UUP Dump")" \
    3 "$(translate "Return to Main Menu")" 3>&1 1>&2 2>&3)

  [[ $? -ne 0 ]] && return 1  # ESC o cancelar

  case "$CHOICE" in
    1)
      select_existing_iso || return 1
      ;;
    2)
      if source <(curl -fsSL "$UUP_REPO/uupdump_creator.sh"); then
          run_uupdump_creator || return 1
          detect_latest_iso_created || return 1
      else
        msg_error "$(translate "UUP Dump script not found.")"
        return 1
      fi
      ;;
    3)
      return 1
      ;;
  esac
  return 0
}

function select_existing_iso() {
  ISO_LIST=()
  while read -r line; do
    FILENAME=$(basename "$line")
    SIZE=$(du -h "$line" | cut -f1)
    ISO_LIST+=("$FILENAME" "$SIZE")
  done < <(find "$ISO_DIR" -type f -iname "*.iso" ! -iname "virtio*" | sort)

  if [[ ${#ISO_LIST[@]} -eq 0 ]]; then
    msg_error "$(translate "No ISO images found in $ISO_DIR.")"
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
  export OS_TYPE="windows"
  
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
  export OS_TYPE="windows"

  return 0
}
