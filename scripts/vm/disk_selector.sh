#!/usr/bin/env bash

# ==========================================================
# ProxMenuX - Virtual Machine Creator Script
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_SCRIPTS_DEFAULT="/usr/local/share/proxmenux/scripts"

BASE_DIR="/usr/local/share/proxmenux"
LOCAL_SCRIPTS="$LOCAL_SCRIPTS_DEFAULT"
UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
if [[ -f "$LOCAL_SCRIPTS_LOCAL/utils.sh" ]]; then
  LOCAL_SCRIPTS="$LOCAL_SCRIPTS_LOCAL"
  UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
elif [[ ! -f "$UTILS_FILE" ]]; then
  UTILS_FILE="$BASE_DIR/utils.sh"
fi
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/vm_storage_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_LOCAL/global/vm_storage_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/vm_storage_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_DEFAULT/global/vm_storage_helpers.sh"
fi

load_language
initialize_cache

VIRTUAL_DISKS=()
IMPORT_DISKS=()
CONTROLLER_NVME_PCIS=()
PASSTHROUGH_DISKS=()

function _build_storage_plan_summary() {
  local virtual_count="${#VIRTUAL_DISKS[@]}"
  local import_count="${#IMPORT_DISKS[@]}"
  local controller_count="${#CONTROLLER_NVME_PCIS[@]}"
  local separator
  local summary
  separator="$(printf '%*s' 70 '' | tr ' ' '-')"
  summary="$(translate "Current selection:")\n"
  summary+="  - $(translate "Virtual disks"): $virtual_count\n"
  summary+="  - $(translate "Import disks"): $import_count\n"
  summary+="  - $(translate "Controllers + NVMe"): $controller_count\n"
  summary+="${separator}\n\n"
  echo -e "$summary"
}

function select_disk_type() {
  VIRTUAL_DISKS=()
  IMPORT_DISKS=()
  CONTROLLER_NVME_PCIS=()

  while true; do
    local choice
    choice=$(whiptail --backtitle "ProxMenux" --title "STORAGE PLAN" --menu "$(_build_storage_plan_summary)" 18 78 5 \
      "a" "$(translate "Add virtual disk")" \
      "b" "$(translate "Add import disk")" \
      "c" "$(translate "Add Controller or NVMe (PCI passthrough)")" \
      "r" "$(translate "Reset current storage selection")" \
      "d" "$(translate "──── [ Finish and continue ] ────")" \
      --ok-button "Select" --cancel-button "Cancel" 3>&1 1>&2 2>&3) || return 1

    case "$choice" in
      a)
        select_virtual_disk
        ;;
      b)
        select_import_disk
        ;;
      c)
        select_controller_nvme
        ;;
      r)
        VIRTUAL_DISKS=()
        IMPORT_DISKS=()
        CONTROLLER_NVME_PCIS=()
        ;;
      d|done)
        if [[ ${#VIRTUAL_DISKS[@]} -eq 0 && ${#IMPORT_DISKS[@]} -eq 0 && ${#CONTROLLER_NVME_PCIS[@]} -eq 0 ]]; then
          continue
        fi
        if [[ ${#VIRTUAL_DISKS[@]} -gt 0 ]]; then
          msg_ok "$(translate "Virtual Disks Created:")"
          for i in "${!VIRTUAL_DISKS[@]}"; do
            echo -e "${TAB}${BL}- $(translate "Disk") $((i+1)): ${VIRTUAL_DISKS[$i]}GB${CL}"
          done
        fi
        if [[ ${#IMPORT_DISKS[@]} -gt 0 ]]; then
          msg_ok "$(translate "Import Disks Selected:")"
          for i in "${!IMPORT_DISKS[@]}"; do
            local disk_info
            disk_info=$(lsblk -ndo MODEL,SIZE "${IMPORT_DISKS[$i]}" 2>/dev/null | xargs)
            echo -e "${TAB}${BL}- $(translate "Disk") $((i+1)): ${IMPORT_DISKS[$i]}${disk_info:+ ($disk_info)}${CL}"
          done
        fi
        if [[ ${#CONTROLLER_NVME_PCIS[@]} -gt 0 ]]; then
          msg_ok "$(translate "Controllers + NVMe Selected:")"
          for i in "${!CONTROLLER_NVME_PCIS[@]}"; do
            local pci_info
            pci_info=$(lspci -nn -s "${CONTROLLER_NVME_PCIS[$i]#0000:}" 2>/dev/null | sed 's/^[^ ]* //')
            echo -e "${TAB}${BL}- $(translate "Controller") $((i+1)): ${CONTROLLER_NVME_PCIS[$i]}${pci_info:+ ($pci_info)}${CL}"
          done
        fi
        PASSTHROUGH_DISKS=("${IMPORT_DISKS[@]}")
        DISK_TYPE="mixed"
        export DISK_TYPE VIRTUAL_DISKS IMPORT_DISKS CONTROLLER_NVME_PCIS PASSTHROUGH_DISKS
        return 0
        ;;
    esac
  done
}

# ==========================================================
# Select Virtual Disks
# ==========================================================
function select_virtual_disk() {
  msg_info "$(translate "Detecting storage for disk images...")"

  local STORAGE_MENU=()
  local TAG TYPE FREE ITEM
  while read -r line; do
    TAG=$(echo $line | awk '{print $1}')
    TYPE=$(echo $line | awk '{print $2}')
    FREE=$(echo $line | numfmt --field 4-6 --from-unit=K --to=iec --format "%.2f" | awk '{printf( "%9sB", $6)}')
    ITEM=$(printf "%-15s %-10s %-15s" "$TAG" "$TYPE" "$FREE")
    STORAGE_MENU+=("$TAG" "$ITEM" "OFF")
  done < <(pvesm status -content images | awk 'NR>1')

  local VALID
  VALID=$(pvesm status -content images | awk 'NR>1')
  if [ -z "$VALID" ]; then
    msg_error "Unable to detect a valid storage location."
    return 1
  fi

  local STORAGE
  if [ $((${#STORAGE_MENU[@]} / 3)) -eq 1 ]; then
    STORAGE=${STORAGE_MENU[0]}
  else
    [[ -n "${SPINNER_PID:-}" ]] && kill "$SPINNER_PID" >/dev/null 2>&1
    STORAGE=$(whiptail --backtitle "ProxMenuX" --title "$(translate "Select Storage")" --radiolist \
      "$(translate "Choose the storage for the virtual disk:")"$'\n' 20 78 10 \
      "${STORAGE_MENU[@]}" 3>&1 1>&2 2>&3)

    if [ $? -ne 0 ] || [ -z "$STORAGE" ]; then
      return 0
    fi
  fi

  local DISK_SIZE
  stop_spinner
  DISK_SIZE=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "System Disk Size (GB)")" 8 58 32 --title "VIRTUAL DISK" --cancel-button Cancel 3>&1 1>&2 2>&3)
  if [ $? -ne 0 ]; then
    return 0
  fi

  if [ -z "$DISK_SIZE" ]; then
    DISK_SIZE="32"
  fi
  VIRTUAL_DISKS+=("${STORAGE}:${DISK_SIZE}")

  export VIRTUAL_DISKS
}

# ==========================================================






# ==========================================================
# Select Import Disks
# ==========================================================
function select_import_disk() {
  msg_info "$(translate "Detecting available disks...")"

  _refresh_host_storage_cache
  local FREE_DISKS=()
  local DISK INFO MODEL SIZE LABEL DESCRIPTION
  while read -r DISK; do
    [[ "$DISK" =~ /dev/zd ]] && continue
    if _disk_is_host_system_used "$DISK"; then
      continue
    fi

    INFO=($(lsblk -dn -o MODEL,SIZE "$DISK"))
    MODEL="${INFO[@]::${#INFO[@]}-1}"
    SIZE="${INFO[-1]}"
    LABEL=""

    if _disk_used_in_guest_configs "$DISK"; then
      LABEL+=" [⚠ $(translate "In use by VM/LXC config")]"
    fi

    DESCRIPTION=$(printf "%-30s %10s%s" "$MODEL" "$SIZE" "$LABEL")
    if _array_contains "$DISK" "${IMPORT_DISKS[@]}"; then
      FREE_DISKS+=("$DISK" "$DESCRIPTION" "ON")
    else
      FREE_DISKS+=("$DISK" "$DESCRIPTION" "OFF")
    fi
  done < <(lsblk -dn -e 7,11 -o PATH)

  if [[ "${#FREE_DISKS[@]}" -eq 0 ]]; then
    stop_spinner
    whiptail --title "Error" --msgbox "$(translate "No importable disks available. System disks and protected disks are hidden.")" 9 70
    return 1
  fi

  local MAX_WIDTH TOTAL_WIDTH SELECTED_DISKS
  MAX_WIDTH=$(printf "%s\n" "${FREE_DISKS[@]}" | awk '{print length}' | sort -nr | head -n1)
  TOTAL_WIDTH=$((MAX_WIDTH + 20))
  [[ $TOTAL_WIDTH -lt 50 ]] && TOTAL_WIDTH=50
  cleanup
  SELECTED_DISKS=$(whiptail --title "Select Import Disks" --checklist \
    "$(translate "Select the disks you want to import (use spacebar to toggle):")" 20 $TOTAL_WIDTH 10 \
    "${FREE_DISKS[@]}" 3>&1 1>&2 2>&3)

  [[ $? -ne 0 ]] && return 1

  IMPORT_DISKS=()
  local DISK_INFO
  for DISK in $(echo "$SELECTED_DISKS" | tr -d '"'); do
    _array_contains "$DISK" "${IMPORT_DISKS[@]}" || IMPORT_DISKS+=("$DISK")
  done

  if [[ ${#IMPORT_DISKS[@]} -eq 0 ]]; then
    msg_warn "$(translate "No import disks selected for now.")"
    return 0
  fi

  export IMPORT_DISKS
  return 0
}

function select_passthrough_disk() {
  select_import_disk
}

function select_controller_nvme() {
  local VM_STORAGE_IOMMU_REBOOT_POLICY="defer"

  if declare -F _vm_storage_ensure_iommu_or_offer >/dev/null 2>&1; then
    if ! _vm_storage_ensure_iommu_or_offer; then
      return 1
    fi
  elif declare -F _pci_is_iommu_active >/dev/null 2>&1; then
    if ! _pci_is_iommu_active; then
      whiptail --title "Controller + NVMe" --msgbox \
"$(translate "IOMMU is not active on this host.")\n\n$(translate "Controller/NVMe passthrough requires IOMMU enabled in BIOS/UEFI and kernel.")\n\n$(translate "Enable IOMMU, reboot the host, and try again.")" \
        14 90
      return 1
    fi
  fi

  msg_info "$(translate "Detecting PCI storage controllers and NVMe devices...")"

  _refresh_host_storage_cache

  local menu_items=()
  local blocked_report=""
  local pci_path pci_full class_hex name controller_disks controller_desc disk safe_count blocked_count state slot_base hidden_target_count
  safe_count=0
  blocked_count=0
  hidden_target_count=0
  local target_vmid="${VMID:-}"

  while IFS= read -r pci_path; do
    pci_full=$(basename "$pci_path")
    class_hex=$(cat "$pci_path/class" 2>/dev/null | sed 's/^0x//')
    [[ -z "$class_hex" ]] && continue
    [[ "${class_hex:0:2}" != "01" ]] && continue
    slot_base=$(_pci_slot_base "$pci_full")

    # If target VM already has this slot assigned, hide it.
    if [[ -n "$target_vmid" ]] && _vm_has_pci_slot "$target_vmid" "$slot_base"; then
      hidden_target_count=$((hidden_target_count + 1))
      continue
    fi

    name=$(lspci -nn -s "${pci_full#0000:}" 2>/dev/null | sed 's/^[^ ]* //')
    [[ -z "$name" ]] && name="$(translate "Unknown storage controller")"

    controller_disks=()
    while IFS= read -r disk; do
      [[ -z "$disk" ]] && continue
      _array_contains "$disk" "${controller_disks[@]}" || controller_disks+=("$disk")
    done < <(_controller_block_devices "$pci_full")

    local -a blocked_reasons=()
    for disk in "${controller_disks[@]}"; do
      if _disk_is_host_system_used "$disk"; then
        blocked_reasons+=("${disk} (${DISK_USAGE_REASON})")
      elif _disk_used_in_guest_configs "$disk"; then
        blocked_reasons+=("${disk} ($(translate "In use by VM/LXC config"))")
      fi
    done

    if [[ ${#blocked_reasons[@]} -gt 0 ]]; then
      blocked_count=$((blocked_count + 1))
      blocked_report+="  •  ${pci_full} — $(_shorten_text "$name" 56)\n"
      continue
    fi

    local short_name
    short_name=$(_shorten_text "$name" 42)

    local assigned_suffix=""
    if [[ -n "$(_pci_assigned_vm_ids "$pci_full" "$target_vmid" 2>/dev/null | head -1)" ]]; then
      assigned_suffix=" | $(translate "Assigned to VM")"
    fi

    controller_desc="${short_name}${assigned_suffix}"

    if _array_contains "$pci_full" "${CONTROLLER_NVME_PCIS[@]}"; then
      state="ON"
    else
      state="OFF"
    fi

    menu_items+=("$pci_full" "$controller_desc" "$state")
    safe_count=$((safe_count + 1))
  done < <(ls -d /sys/bus/pci/devices/* 2>/dev/null | sort)

  stop_spinner
  if [[ $safe_count -eq 0 ]]; then
    local msg
    if [[ "$hidden_target_count" -gt 0 && "$blocked_count" -eq 0 ]]; then
      msg="$(translate "All detected controllers/NVMe are already present in the selected VM.")\n\n$(translate "No additional device needs to be added.")"
    else
      msg="$(translate "No available Controllers/NVMe devices were found.")\n\n"
    fi
    if [[ $blocked_count -gt 0 ]]; then
      msg+="$(translate "Hidden for safety"):\n${blocked_report}"
    fi
    whiptail --title "Controller + NVMe" --msgbox "$msg" 18 84
    return 1
  fi

  local selected
  selected=$(whiptail --title "Controller + NVMe" --checklist \
    "$(translate "Select available Controllers/NVMe to add:")" 20 96 10 \
    "${menu_items[@]}" 3>&1 1>&2 2>&3)

  [[ $? -ne 0 ]] && return 1

  CONTROLLER_NVME_PCIS=()
  local pci
  for pci in $(echo "$selected" | tr -d '"'); do
    _array_contains "$pci" "${CONTROLLER_NVME_PCIS[@]}" || CONTROLLER_NVME_PCIS+=("$pci")
  done

  if [[ ${#CONTROLLER_NVME_PCIS[@]} -eq 0 ]]; then
    msg_warn "$(translate "No Controller/NVMe selected for now.")"
    return 0
  fi

  if declare -F _vm_storage_confirm_controller_passthrough_risk >/dev/null 2>&1; then
    local vm_name_for_notice="${HN:-}"
    if ! _vm_storage_confirm_controller_passthrough_risk "${VMID:-}" "$vm_name_for_notice" "Controller + NVMe"; then
      CONTROLLER_NVME_PCIS=()
      return 1
    fi
  fi

  export CONTROLLER_NVME_PCIS
  return 0
}
# ==========================================================
