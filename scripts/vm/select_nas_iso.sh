#!/usr/bin/env bash

# ==========================================================
# ProxMenux - NAS ISO Selector
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# NAS appliance selector for the ProxMenux VM creator. Lists the
# supported NAS operating systems, auto-detects their latest stable
# release (where possible), and prepares the ISO / image metadata
# for the generic VM wizard. Synology DSM and ZimaOS have their own
# dedicated flows; Umbrel OS runs an external community script.
#
# Features:
# - Auto-detects latest versions for TrueNAS SCALE/CORE, OMV,
#   XigmaNAS and Rockstor, with safe fallbacks.
# - Dispatches Synology DSM to the dedicated loader-based flow.
# - Dispatches ZimaOS to its own installer script.
# - Runs the Umbrel OS community installer (external script).
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_SCRIPTS_DEFAULT="/usr/local/share/proxmenux/scripts"
LOCAL_SCRIPTS="$LOCAL_SCRIPTS_DEFAULT"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$LOCAL_SCRIPTS_LOCAL/utils.sh" ]]; then
  LOCAL_SCRIPTS="$LOCAL_SCRIPTS_LOCAL"
  UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
elif [[ ! -f "$UTILS_FILE" ]]; then
  UTILS_FILE="$BASE_DIR/utils.sh"
fi

[[ -f "$UTILS_FILE" ]] && source "$UTILS_FILE"
load_language
initialize_cache

ISO_DIR="/var/lib/vz/template/iso"
mkdir -p "$ISO_DIR"

function _has_curl() {
  command -v curl >/dev/null 2>&1
}

function _latest_version_from_lines() {
  awk 'NF' | sort -V | tail -n 1
}

function resolve_truenas_scale_iso() {
  local default_ver="25.10.2.1"
  local base_url="https://download.sys.truenas.net/TrueNAS-SCALE-Goldeye"
  local detected_ver=""

  if _has_curl; then
    detected_ver=$(
      curl -fsSL "${base_url}/" 2>/dev/null \
        | grep -Eo '>[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?/' \
        | tr -d '>/' \
        | _latest_version_from_lines
    )
  fi

  [[ -z "$detected_ver" ]] && detected_ver="$default_ver"

  ISO_NAME="TrueNAS SCALE ${detected_ver} (Goldeye)"
  ISO_FILE="TrueNAS-SCALE-${detected_ver}.iso"
  ISO_URL="${base_url}/${detected_ver}/${ISO_FILE}"
  ISO_PATH="$ISO_DIR/$ISO_FILE"
  HN="TrueNAS-Scale"
}

function resolve_truenas_core_iso() {
  local default_file="TrueNAS-13.3-U1.2.iso"
  local detected_file=""
  local base_url="https://download.freenas.org/13.3/STABLE/latest/x64"

  if _has_curl; then
    detected_file=$(
      curl -fsSL "${base_url}/" 2>/dev/null \
        | grep -Eo 'TrueNAS-13\.3-[^"]+\.iso' \
        | head -n 1
    )
  fi

  [[ -z "$detected_file" ]] && detected_file="$default_file"

  ISO_NAME="TrueNAS CORE 13.3"
  ISO_FILE="$detected_file"
  ISO_URL="${base_url}/${ISO_FILE}"
  ISO_PATH="$ISO_DIR/$ISO_FILE"
  HN="TrueNAS-Core"
}

function resolve_omv_iso() {
  local default_ver="8.1.1"
  local detected_ver=""

  if _has_curl; then
    detected_ver=$(
      curl -fsSL "https://sourceforge.net/projects/openmediavault/files/iso/" 2>/dev/null \
        | grep -Eo '/projects/openmediavault/files/iso/[0-9]+\.[0-9]+\.[0-9]+/' \
        | sed -E 's|.*/iso/([0-9]+\.[0-9]+\.[0-9]+)/$|\1|' \
        | _latest_version_from_lines
    )
  fi

  [[ -z "$detected_ver" ]] && detected_ver="$default_ver"

  ISO_NAME="OpenMediaVault ${detected_ver}"
  ISO_FILE="openmediavault_${detected_ver}-amd64.iso"
  ISO_URL="https://sourceforge.net/projects/openmediavault/files/iso/${detected_ver}/${ISO_FILE}/download"
  ISO_PATH="$ISO_DIR/$ISO_FILE"
  HN="OpenMediaVault"
}

function resolve_xigmanas_iso() {
  local default_train="14.3.0.5"
  local default_build="14.3.0.5.10566"
  local detected_train=""
  local detected_build=""

  if _has_curl; then
    detected_train=$(
      curl -fsSL "https://sourceforge.net/projects/xigmanas/files/" 2>/dev/null \
        | grep -Eo '/projects/xigmanas/files/XigmaNAS-[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/' \
        | sed -E 's|.*/XigmaNAS-([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)/$|\1|' \
        | _latest_version_from_lines
    )
  fi

  [[ -z "$detected_train" ]] && detected_train="$default_train"

  if _has_curl; then
    detected_build=$(
      curl -fsSL "https://sourceforge.net/projects/xigmanas/files/XigmaNAS-${detected_train}/" 2>/dev/null \
        | grep -Eo "/projects/xigmanas/files/XigmaNAS-${detected_train}/[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/" \
        | sed -E "s|.*/XigmaNAS-${detected_train}/([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)/$|\\1|" \
        | _latest_version_from_lines
    )
  fi

  [[ -z "$detected_build" ]] && detected_build="$default_build"

  ISO_NAME="XigmaNAS-${detected_train}"
  ISO_FILE="XigmaNAS-x64-LiveCD-${detected_build}.iso"
  ISO_URL="https://sourceforge.net/projects/xigmanas/files/XigmaNAS-${detected_train}/${detected_build}/${ISO_FILE}/download"
  ISO_PATH="$ISO_DIR/$ISO_FILE"
  HN="XigmaNAS"
}

function resolve_rockstor_iso() {
  local default_file="Rockstor-Leap15.6-generic.x86_64-5.0.15-0.install.iso"
  local detected_file=""
  local base_url="https://rockstor.com/downloads/installer/leap/15.6/x86_64"

  if _has_curl; then
    detected_file=$(
      curl -fsSL "${base_url}/" 2>/dev/null \
        | grep -Eo 'Rockstor-Leap15\.6-generic\.x86_64-[0-9]+\.[0-9]+\.[0-9]+-[0-9]+\.install\.iso' \
        | _latest_version_from_lines
    )
  fi

  [[ -z "$detected_file" ]] && detected_file="$default_file"

  ISO_NAME="Rockstor"
  ISO_FILE="$detected_file"
  ISO_URL="${base_url}/${ISO_FILE}"
  ISO_PATH="$ISO_DIR/$ISO_FILE"
  HN="Rockstor"
}

function select_nas_iso() {

  local NAS_OPTIONS=(
    "1" "Synology DSM   VM          (Loader Linux-based)"
    "2" "TrueNAS SCALE  VM          (Goldeye)"
    "3" "TrueNAS CORE   VM          (FreeBSD based)"
    "4" "OpenMediaVault VM          (Debian based)"
    "5" "XigmaNAS       VM          (FreeBSD based)"
    "6" "Rockstor       VM          (openSUSE based)"
    "7" "ZimaOS         VM          (Proxmox-zimaos)"
    ""  ""
    ""  "\Z4───────────────── Community Scripts ─────────────────\Zn"
    "8" "Umbrel OS      VM          (Helper Scripts)"
    "9" "$(translate "Return to Main Menu")"
  )

  local NAS_TYPE
  NAS_TYPE=$(dialog --backtitle "ProxMenux" \
    --title "$(translate "NAS Systems")" \
    --menu "\n$(translate "Select the NAS system to install:")" 20 70 10 \
    "${NAS_OPTIONS[@]}" 3>&1 1>&2 2>&3)


  [[ $? -ne 0 ]] && return 1

  case "$NAS_TYPE" in
    1)
      bash "$LOCAL_SCRIPTS/vm/synology.sh"
      msg_success "$(translate "Press Enter to return to menu...")"
      read -r
      return 1
      ;;
    2)
      resolve_truenas_scale_iso
      ;;
    3)
      resolve_truenas_core_iso
      ;;
    4)
      resolve_omv_iso
      ;;
    5)
      resolve_xigmanas_iso
      ;;
    6)
      resolve_rockstor_iso
      ;;
    7)
      bash "$LOCAL_SCRIPTS/vm/zimaos.sh"
      msg_success "$(translate "Press Enter to return to menu...")"
      read -r
      return 1
      ;;
    8)
      HN="Umbrel OS"
      bash -c "$(wget -qLO - https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/vm/umbrel-os-vm.sh)"
      echo -e
      echo -e "${TAB}$(translate "Default Login Credentials:")"
      echo -e "${TAB}Username: umbrel"
      echo -e "${TAB}Password: umbrel"
      echo -e "${TAB}$(translate "After logging in, run: ip a to obtain the IP address.\nThen, enter that IP address in your web browser like this:\n  http://IP_ADDRESS\n\nThis will open the Umbral OS dashboard.")"
      echo -e
      msg_success "$(translate "Press Enter to return to menu...")"
      read -r
      
      whiptail --title "Proxmox VE - Umbrel OS" \
        --msgbox "$(translate "Umbrel OS installer script by Helper Scripts\n\nVisit the GitHub repo to learn more, contribute, or support the project:\n\nhttps://community-scripts.github.io/ProxmoxVE/scripts?id=umbrel-os-vm")" 15 70

      return 1
      ;;

    9)
      return 1
      ;;
  esac

  export ISO_NAME ISO_URL ISO_FILE ISO_PATH HN
  return 0
}
