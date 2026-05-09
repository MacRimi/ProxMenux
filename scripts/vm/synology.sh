#!/usr/bin/env bash

# ==========================================================
# ProxMenux - Synology DSM VM Creator
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Creates and configures a Synology DSM (DiskStation Manager)
# virtual machine on Proxmox VE. Downloads one of the supported
# loaders (Arc, RR, TinyCore M-shell, or a custom one), imports
# it as the VM boot disk, and prepares CPU/RAM/network/storage
# through the ProxMenux default or advanced wizard.
#
# Features:
# - Supports Arc, RR, TinyCore M-shell and Custom loaders.
# - Default and Advanced configuration modes.
# - Virtual disks (SATA, up to 6) or physical disk passthrough.
# - Imports the loader as IDE for maximum compatibility.
# - Generates a styled HTML description attached to the VM.
#
# Credits:
# Original work by MacRimi. Incorporates ideas and snippets from
# tim104979's synology-vm.sh in the ProxmoxVE Helper-Scripts
# Community project (MIT):
# https://raw.githubusercontent.com/tim104979/ProxmoxVE/refs/heads/main/vm/synology-vm.sh
# ==========================================================


# Configuration ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_SCRIPTS_DEFAULT="/usr/local/share/proxmenux/scripts"
LOCAL_SCRIPTS="$LOCAL_SCRIPTS_DEFAULT"
BASE_DIR="/usr/local/share/proxmenux"
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
if [[ -f "$LOCAL_SCRIPTS_LOCAL/vm/disk_selector.sh" ]]; then
    source "$LOCAL_SCRIPTS_LOCAL/vm/disk_selector.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/vm/disk_selector.sh" ]]; then
    source "$LOCAL_SCRIPTS_DEFAULT/vm/disk_selector.sh"
fi
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/pci_passthrough_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_LOCAL/global/pci_passthrough_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/pci_passthrough_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_DEFAULT/global/pci_passthrough_helpers.sh"
fi
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/gpu_hook_guard_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_LOCAL/global/gpu_hook_guard_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/gpu_hook_guard_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_DEFAULT/global/gpu_hook_guard_helpers.sh"
fi
load_language
initialize_cache
# ==========================================================

GEN_MAC="02"
for i in {1..5}; do
  BYTE=$(printf "%02X" $((RANDOM % 256)))
  GEN_MAC="${GEN_MAC}:${BYTE}"
done

NEXTID=$(pvesh get /cluster/nextid 2>/dev/null || echo "100")
NAME="Synology VM"
IMAGES_DIR="/var/lib/vz/template/iso"
ERROR_FLAG=false
WIZARD_ADD_GPU="no"
WIZARD_GPU_RESULT="not_requested"
VM_WIZARD_CAPTURE_FILE=""
VM_WIZARD_CAPTURE_ACTIVE=0
VM_STORAGE_IOMMU_PENDING_REBOOT=0





function exit_script() {
  clear
      if whiptail --backtitle "ProxMenuX" --title "$NAME" --yesno "$(translate "This will create a New $NAME. Proceed?")" 10 58; then
        start_script
      else
        clear
        exit
      fi
}


# Define the header_info function at the beginning of the script

function header_info() {
  clear
  show_proxmenux_logo
  msg_title "Synology VM Creator"
}
# ==========================================================

function start_vm_wizard_capture() {
  [[ "${VM_WIZARD_CAPTURE_ACTIVE:-0}" -eq 1 ]] && return 0
  VM_WIZARD_CAPTURE_FILE="/tmp/proxmenux_synology_vm_wizard_capture_$$.txt"
  : >"$VM_WIZARD_CAPTURE_FILE"
  exec 8>&1
  exec > >(tee -a "$VM_WIZARD_CAPTURE_FILE")
  VM_WIZARD_CAPTURE_ACTIVE=1
}

function stop_vm_wizard_capture() {
  if [[ "${VM_WIZARD_CAPTURE_ACTIVE:-0}" -eq 1 ]]; then
    exec 1>&8
    exec 8>&-
    VM_WIZARD_CAPTURE_ACTIVE=0
  fi
  if [[ -n "${VM_WIZARD_CAPTURE_FILE:-}" && -f "$VM_WIZARD_CAPTURE_FILE" ]]; then
    rm -f "$VM_WIZARD_CAPTURE_FILE"
  fi
  VM_WIZARD_CAPTURE_FILE=""
}

function replay_vm_wizard_capture() {
  if [[ "${VM_WIZARD_CAPTURE_ACTIVE:-0}" -eq 1 ]]; then
    stop_spinner
    exec 1>&8
    exec 8>&-
    VM_WIZARD_CAPTURE_ACTIVE=0
  fi

  if [[ -n "${VM_WIZARD_CAPTURE_FILE:-}" && -f "$VM_WIZARD_CAPTURE_FILE" ]]; then
    show_proxmenux_logo
    cat "$VM_WIZARD_CAPTURE_FILE"
    rm -f "$VM_WIZARD_CAPTURE_FILE"
  fi
  VM_WIZARD_CAPTURE_FILE=""
}

function has_usable_gpu_for_vm_passthrough() {
  lspci -nn 2>/dev/null \
    | grep -iE "VGA compatible controller|3D controller|Display controller" \
    | grep -ivE "Ethernet|Network|Audio" \
    | grep -ivE "ASPEED|AST[0-9]{3,4}|Matrox|G200e|BMC" \
    | grep -q .
}

function prompt_optional_gpu_passthrough() {
  WIZARD_ADD_GPU="no"
  if has_usable_gpu_for_vm_passthrough; then
    if whiptail --backtitle "ProxMenuX" --title "$(translate "Optional GPU Passthrough")" \
      --yesno "$(translate "Do you want to configure GPU passthrough for this VM now?")\n\n$(translate "This will launch the GPU assistant after VM creation and may require a host reboot.")" 12 78 --defaultno; then
      WIZARD_ADD_GPU="yes"
    fi
  else
    msg_warn "$(translate "No compatible GPU detected for VM passthrough. Skipping GPU wizard option.")"
  fi
  export WIZARD_ADD_GPU
}

function run_gpu_passthrough_wizard() {
  [[ "${WIZARD_ADD_GPU:-no}" != "yes" ]] && return 0

  local gpu_script="$LOCAL_SCRIPTS/gpu_tpu/add_gpu_vm.sh"
  local local_gpu_script
  local wizard_result_file=""

  if [[ ! -f "$gpu_script" ]]; then
    local_gpu_script="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)/gpu_tpu/add_gpu_vm.sh"
    [[ -f "$local_gpu_script" ]] && gpu_script="$local_gpu_script"
  fi

  if [[ ! -f "$gpu_script" ]]; then
    msg_warn "$(translate "GPU passthrough assistant not found. You can run it later from Hardware Graphics.")"
    WIZARD_GPU_RESULT="cancelled"
    return 0
  fi

  msg_info2 "$(translate "Launching GPU passthrough assistant for VM") ${VMID}..."
  wizard_result_file="/tmp/proxmenux_gpu_wizard_result_${VMID}_$$.txt"
  : >"$wizard_result_file"
  bash "$gpu_script" --vmid "$VMID" --wizard --result-file "$wizard_result_file"

  if [[ -s "$wizard_result_file" ]]; then
    WIZARD_GPU_RESULT=$(head -n1 "$wizard_result_file" | tr -d '\r\n')
  else
    WIZARD_GPU_RESULT="cancelled"
  fi
  rm -f "$wizard_result_file"
}






# ==========================================================
# start Script
# ==========================================================
function start_script() {
  if (whiptail --backtitle "ProxMenuX" --title "SETTINGS" --yesno "$(translate  "Use Default Settings?")" --no-button Advanced 10 58); then
    header_info
    echo -e "${DEF}Using Default Settings${CL}"
    default_settings || return 1
  else
    header_info
    echo -e "${CUS}Using Advanced Settings${CL}"
    advanced_settings || return 1
  fi
  return 0
}
# ==========================================================




# ==========================================================
# Default Settings
# ==========================================================
function default_settings() {
  VMID="$NEXTID"
  FORMAT=""
  MACHINE=" -machine q35"
  BIOS_TYPE=" -bios ovmf"
  DISK_CACHE=""
  HN="Synology-DSM"
  CPU_TYPE=" -cpu host"
  CORE_COUNT="2"
  RAM_SIZE="4096"
  BRG="vmbr0"
  MAC="$GEN_MAC"
  VLAN=""
  MTU=""
  SERIAL_PORT="socket"
  START_VM="no"
  
  echo -e " ${TAB}${DGN}Using Virtual Machine ID: ${BGN}${VMID}${CL}"
  echo -e " ${TAB}${DGN}Using Machine Type: ${BGN}q35${CL}"
  echo -e " ${TAB}${DGN}Using BIOS Type: ${BGN}OVMF (UEFI)${CL}"
  echo -e " ${TAB}${DGN}Using Hostname: ${BGN}${HN}${CL}"
  echo -e " ${TAB}${DGN}Using CPU Model: ${BGN}Host${CL}"
  echo -e " ${TAB}${DGN}Allocated Cores: ${BGN}${CORE_COUNT}${CL}"
  echo -e " ${TAB}${DGN}Allocated RAM: ${BGN}${RAM_SIZE}${CL}"
  echo -e " ${TAB}${DGN}Using Bridge: ${BGN}${BRG}${CL}"
  echo -e " ${TAB}${DGN}Using MAC Address: ${BGN}${MAC}${CL}"
  echo -e " ${TAB}${DGN}Using VLAN: ${BGN}Default${CL}"
  echo -e " ${TAB}${DGN}Using Interface MTU Size: ${BGN}Default${CL}"
  echo -e " ${TAB}${DGN}Configuring Serial Port: ${BGN}${SERIAL_PORT}${CL}"
  echo -e " ${TAB}${DGN}Start VM when completed: ${BGN}${START_VM}${CL}"
  echo -e
  echo -e "${DEF}Creating a $NAME using the above default settings${CL}"
 
  sleep 1
  select_disk_type || return 1
}
# ==========================================================





# ==========================================================
# advanced Settings
# ==========================================================
function advanced_settings() {
  # VM ID Selection
  while true; do
    if VMID=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "Set Virtual Machine ID")" 8 58 $NEXTID --title "VIRTUAL MACHINE ID" --cancel-button Exit-Script 3>&1 1>&2 2>&3); then
      if [ -z "$VMID" ]; then
        VMID="$NEXTID"
      fi
      if pct status "$VMID" &>/dev/null || qm status "$VMID" &>/dev/null; then
        echo -e "${CROSS}${RD} ID $VMID is already in use${CL}"
        sleep 1
        continue
      fi
      echo -e "${DGN}Virtual Machine ID: ${BGN}$VMID${CL}"
      break
    else
      exit_script
    fi
  done

  # Machine Type Selection
  if MACH=$(whiptail --backtitle "ProxMenuX" --title "$(translate "MACHINE TYPE")" --radiolist --cancel-button Exit-Script "Choose Type" 10 58 2 \
    "q35" "Machine q35" ON \
    "i440fx" "Machine i440fx" OFF \
    3>&1 1>&2 2>&3); then
    if [ $MACH = q35 ]; then
      echo -e "${DGN}Using Machine Type: ${BGN}$MACH${CL}"
      FORMAT=""
      MACHINE=" -machine q35"
    else
      echo -e "${DGN}Using Machine Type: ${BGN}$MACH${CL}"
      FORMAT=",efitype=4m"
      MACHINE=""
    fi
  else
    exit_script
  fi

    # BIOS Type Selection 
  if BIOS=$(whiptail --backtitle "ProxMenuX" --title "$(translate "BIOS TYPE")" --radiolist --cancel-button Exit-Script "Choose BIOS Type" 10 58 2 \
    "ovmf" "UEFI (OVMF)" ON \
    "seabios" "SeaBIOS (Legacy)" OFF \
    3>&1 1>&2 2>&3); then
    if [ "$BIOS" = "seabios" ]; then
        echo -e "${DGN}Using BIOS Type: ${BGN}SeaBIOS${CL}"
        BIOS_TYPE=" -bios seabios"
    else
        echo -e "${DGN}Using BIOS Type: ${BGN}OVMF (UEFI)${CL}"
        BIOS_TYPE=" -bios ovmf"
    fi
  else
    exit_script
   fi

  # Hostname Selection
  if VM_NAME=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "Set Hostname")" 8 58 Synology-DSM --title "HOSTNAME" --cancel-button Exit-Script 3>&1 1>&2 2>&3); then
    if [ -z $VM_NAME ]; then
      HN="Synology-DSM"
      echo -e "${DGN}Using Hostname: ${BGN}$HN${CL}"
    else
      HN=$(echo ${VM_NAME,,} | tr -d ' ')
      echo -e "${DGN}Using Hostname: ${BGN}$HN${CL}"
    fi
  else
    exit_script
  fi

  # CPU Type Selection 
  if CPU_TYPE1=$(whiptail --backtitle "ProxMenuX" --title "$(translate "CPU MODEL")" --radiolist "Choose" --cancel-button Exit-Script 10 58 2 \
    "1" "Host" ON \
    "0" "KVM64" OFF \
    3>&1 1>&2 2>&3); then
    if [ $CPU_TYPE1 = "1" ]; then
      echo -e "${DGN}Using CPU Model: ${BGN}Host${CL}"
      CPU_TYPE=" -cpu host"
    else
      echo -e "${DGN}Using CPU Model: ${BGN}KVM64${CL}"
      CPU_TYPE=""
    fi
  else
    exit_script
  fi

  # Core Count Selection
  if CORE_COUNT=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "Allocate CPU Cores")" 8 58 2 --title "CORE COUNT" --cancel-button Exit-Script 3>&1 1>&2 2>&3); then
    if [ -z $CORE_COUNT ]; then
      CORE_COUNT="2"
      echo -e "${DGN}Allocated Cores: ${BGN}$CORE_COUNT${CL}"
    else
      echo -e "${DGN}Allocated Cores: ${BGN}$CORE_COUNT${CL}"
    fi
  else
    exit_script
  fi

  # RAM Size Selection
  if RAM_SIZE=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "Allocate RAM in MiB")" 8 58 4096 --title "RAM" --cancel-button Exit-Script 3>&1 1>&2 2>&3); then
    if [ -z $RAM_SIZE ]; then
      RAM_SIZE="4096"
      echo -e "${DGN}Allocated RAM: ${BGN}$RAM_SIZE${CL}"
    else
      echo -e "${DGN}Allocated RAM: ${BGN}$RAM_SIZE${CL}"
    fi
  else
    exit_script
  fi

  # Bridge Selection
  if BRG=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "Set a Bridge")" 8 58 vmbr0 --title "BRIDGE" --cancel-button Exit-Script 3>&1 1>&2 2>&3); then
    if [ -z $BRG ]; then
      BRG="vmbr0"
      echo -e "${DGN}Using Bridge: ${BGN}$BRG${CL}"
    else
      echo -e "${DGN}Using Bridge: ${BGN}$BRG${CL}"
    fi
  else
    exit_script
  fi

  # MAC Address Selection
  if MAC1=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "Set a MAC Address")" 8 58 $GEN_MAC --title "MAC ADDRESS" --cancel-button Exit-Script 3>&1 1>&2 2>&3); then
    if [ -z $MAC1 ]; then
      MAC="$GEN_MAC"
      echo -e "${DGN}Using MAC Address: ${BGN}$MAC${CL}"
    else
      MAC="$MAC1"
      echo -e "${DGN}Using MAC Address: ${BGN}$MAC1${CL}"
    fi
  else
    exit_script
  fi

  # VLAN Selection
  if VLAN1=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "Set a Vlan(leave blank for default)")" 8 58 --title "VLAN" --cancel-button Exit-Script 3>&1 1>&2 2>&3); then
    if [ -z $VLAN1 ]; then
      VLAN1="Default"
      VLAN=""
      echo -e "${DGN}Using Vlan: ${BGN}$VLAN1${CL}"
    else
      VLAN=",tag=$VLAN1"
      echo -e "${DGN}Using Vlan: ${BGN}$VLAN1${CL}"
    fi
  else
    exit_script
  fi

  # MTU Selection
  if MTU1=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "Set Interface MTU Size (leave blank for default)")" 8 58 --title "MTU SIZE" --cancel-button Exit-Script 3>&1 1>&2 2>&3); then
    if [ -z $MTU1 ]; then
      MTU1="Default"
      MTU=""
      echo -e "${DGN}Using Interface MTU Size: ${BGN}$MTU1${CL}"
    else
      MTU=",mtu=$MTU1"
      echo -e "${DGN}Using Interface MTU Size: ${BGN}$MTU1${CL}"
    fi
  else
    exit_script
  fi



  # Confirmation
  if (whiptail --backtitle "ProxMenuX" --title "$(translate "ADVANCED SETTINGS COMPLETE")" --yesno "Ready to create a $NAME?" --no-button Do-Over 10 58); then
    echo -e
    echo -e "${CUS}Creating a $NAME using the above advanced settings${CL}"
    sleep 1
    select_disk_type || return 1
  else
   header_info
   sleep 1
   echo -e "${CUS}Using Advanced Settings${CL}"
   advanced_settings
  fi
}
# ==========================================================





# ==========================================================
# Select Disk
# ==========================================================
VIRTUAL_DISKS=()
IMPORT_DISKS=()
CONTROLLER_NVME_PCIS=()
PASSTHROUGH_DISKS=()

function _build_storage_plan_summary() {
  local separator
  local summary
  separator="$(printf '%*s' 70 '' | tr ' ' '-')"
  summary="$(translate "Current selection:")\n"
  summary+="  - $(translate "Virtual disks"): ${#VIRTUAL_DISKS[@]}\n"
  summary+="  - $(translate "Import disks"): ${#IMPORT_DISKS[@]}\n"
  summary+="  - $(translate "Controllers + NVMe"): ${#CONTROLLER_NVME_PCIS[@]}\n"
  summary+="${separator}\n\n"
  echo -e "$summary"
}

function select_disk_type() {
  VIRTUAL_DISKS=()
  IMPORT_DISKS=()
  CONTROLLER_NVME_PCIS=()

  while true; do
    local choice
    choice=$(whiptail --backtitle "ProxMenuX" --title "STORAGE PLAN" --menu "$(_build_storage_plan_summary)" 18 78 5 \
      "a" "$(translate "Add virtual disk")" \
      "b" "$(translate "Add import disk")" \
      "c" "$(translate "Add Controller or NVMe (PCI passthrough)")" \
      "r" "$(translate "Reset current storage selection")" \
      "d" "$(translate "──── [ Finish and continue ] ────")" \
      --ok-button "Select" --cancel-button "Cancel" 3>&1 1>&2 2>&3) || {
      msg_warn "$(translate "Storage plan selection cancelled.")"
      return 1
    }

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
        select_loader || return 1
        return 0
        ;;
    esac
  done
}

function select_virtual_disk() {
  msg_info "Detecting available storage volumes..."

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
  if [[ -z "$VALID" ]]; then
    msg_error "Unable to detect a valid storage location."
    return 1
  fi

  local STORAGE
  if [[ $((${#STORAGE_MENU[@]} / 3)) -eq 1 ]]; then
    STORAGE=${STORAGE_MENU[0]}
  else
    [[ -n "${SPINNER_PID:-}" ]] && kill "$SPINNER_PID" >/dev/null 2>&1
    STORAGE=$(whiptail --backtitle "ProxMenuX" --title "$(translate "Select Storage Volume")" --radiolist \
      "$(translate  "Choose the storage volume for the virtual disk:\n")" 20 78 10 \
      "${STORAGE_MENU[@]}" 3>&1 1>&2 2>&3) || return 0
    [[ -z "$STORAGE" ]] && return 0
  fi

  local DISK_SIZE
  stop_spinner
  DISK_SIZE=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "System Disk Size (GB)")" 8 58 32 --title "VIRTUAL DISK" --cancel-button Cancel 3>&1 1>&2 2>&3) || return 0
  [[ -z "$DISK_SIZE" ]] && DISK_SIZE="32"

  VIRTUAL_DISKS+=("${STORAGE}:${DISK_SIZE}")
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
  local safe_count=0 blocked_count=0 hidden_target_count=0
  local pci_path pci_full class_hex name controller_disks disk state controller_desc slot_base
  local target_vmid="${VMID:-}"

  while IFS= read -r pci_path; do
    pci_full=$(basename "$pci_path")
    class_hex=$(cat "$pci_path/class" 2>/dev/null | sed 's/^0x//')
    [[ -z "$class_hex" || "${class_hex:0:2}" != "01" ]] && continue
    slot_base=$(_pci_slot_base "$pci_full")

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
      if [[ $blocked_count -gt 0 ]]; then
        msg+="$(translate "Hidden for safety"):\n${blocked_report}"
      fi
    fi
    whiptail --title "Controller + NVMe" --msgbox "$msg" 18 84
    return 1
  fi

  local selected
  selected=$(whiptail --title "Controller + NVMe" --checklist \
    "$(translate "Select available Controllers/NVMe to add:")" 20 96 10 \
    "${menu_items[@]}" 3>&1 1>&2 2>&3) || return 1

  CONTROLLER_NVME_PCIS=()
  local pci
  for pci in $(echo "$selected" | tr -d '"'); do
    CONTROLLER_NVME_PCIS+=("$pci")
  done

  if [[ ${#CONTROLLER_NVME_PCIS[@]} -gt 0 ]] && declare -F _vm_storage_confirm_controller_passthrough_risk >/dev/null 2>&1; then
    local vm_name_for_notice="${HN:-$NAME}"
    if ! _vm_storage_confirm_controller_passthrough_risk "${VMID:-}" "$vm_name_for_notice" "Controller + NVMe"; then
      CONTROLLER_NVME_PCIS=()
      return 1
    fi
  fi

  export CONTROLLER_NVME_PCIS
}

function select_passthrough_disk() {
  select_import_disk
}
# ==========================================================

function prompt_controller_conflict_policy() {
  local pci="$1"
  shift
  local -a source_vms=("$@")
  local msg vmid vm_name st ob
  msg="\n$(translate "Selected controller/NVMe is already assigned to other VM(s):")\n\n"
  for vmid in "${source_vms[@]}"; do
    vm_name=$(_vm_name_by_id "$vmid")
    st="stopped"; _vm_status_is_running "$vmid" && st="running"
    ob="0"; _vm_onboot_is_enabled "$vmid" && ob="1"
    msg+="  - VM ${vmid} (${vm_name}) [${st}, onboot=${ob}]\n"
  done
  msg+="\n$(translate "Choose action for this controller/NVMe:")"

  local choice
  choice=$(whiptail --title "$(translate "Controller/NVMe Conflict Policy")" --menu "$msg" 20 80 10 \
    "1" "$(translate "Keep in source VM(s) + disable onboot + add to target VM")" \
    "2" "$(translate "Move to target VM (remove from source VM config)")" \
    "3" "$(translate "Skip this device")" \
    3>&1 1>&2 2>&3) || { echo "skip"; return; }

  case "$choice" in
    1) echo "keep_disable_onboot" ;;
    2) echo "move_remove_source" ;;
    *) echo "skip" ;;
  esac
}






# ==========================================================
# Select Loader
# ==========================================================
function select_loader() {
  # Ensure the images directory exists
  if [ ! -d "$IMAGES_DIR" ]; then
    msg_info "Creating images directory"
    mkdir -p "$IMAGES_DIR"
    chmod 755 "$IMAGES_DIR"
    msg_ok "Images directory created: $IMAGES_DIR"
  fi

  # Create the loader selection menu
  LOADER_OPTION=$(whiptail --backtitle "ProxMenuX" --title "SELECT LOADER" --menu "$(translate "Choose a loader for Synology DSM:")" 15 70 4 \
    "1" "AuxXxilium Arc Loader" \
    "2" "RedPill Loader (RROrg - RR)" \
    "3" "TinyCore RedPill Loader (PeterSuh-Q3 M-shell)" \
    "4" "Custom Loader Image (from $IMAGES_DIR)" \
    3>&1 1>&2 2>&3)

  if [ -z "$LOADER_OPTION" ]; then
    exit_script
  fi

  case $LOADER_OPTION in
    1)
      LOADER_TYPE="arc"
      LOADER_NAME="AuxXxilium Arc"
      LOADER_URL="https://github.com/AuxXxilium/arc/"
      echo -e "${DGN}${TAB}Selected Loader: ${BGN}$LOADER_NAME${CL}"
      download_loader
      ;;
    2)
      LOADER_TYPE="redpill"
      LOADER_NAME="RedPill RR"
      LOADER_URL="https://github.com/RROrg/rr/"
      echo -e "${DGN}${TAB}Selected Loader: ${BGN}$LOADER_NAME${CL}"
      download_loader
      ;;
    3)
      LOADER_TYPE="tinycore"
      LOADER_NAME="TinyCore RedPill M-shell"
      LOADER_URL="https://github.com/PeterSuh-Q3/tinycore-redpill/"
      echo -e "${DGN}${TAB}Selected Loader: ${BGN}$LOADER_NAME${CL}"
      download_loader
      ;;
    4)
      LOADER_TYPE="custom"
      LOADER_NAME="Custom Image"
      LOADER_URL="https://xpenology.com/forum/"
      echo -e "${DGN}${TAB}Selected Loader: ${BGN}$LOADER_NAME${CL}"
      select_custom_image
      ;;
  esac
}

function select_custom_image() {
  # Check if there are any images in the directory
  IMAGES=$(find "$IMAGES_DIR" -type f -name "*.img" -o -name "*.iso" -o -name "*.qcow2" -o -name "*.vmdk" | sort)
  
  if [ -z "$IMAGES" ]; then
    whiptail --title "$(translate "No Images Found")" --msgbox "No compatible images found in $IMAGES_DIR\n\nSupported formats: .img, .iso, .qcow2, .vmdk\n\nPlease add some images and try again." 15 70
    select_loader
  fi
  
  # Create an array of image options for whiptail
  IMAGE_OPTIONS=()

  while read -r img; do
    filename=$(basename "$img")
    filesize=$(du -h "$img" | cut -f1)
    IMAGE_OPTIONS+=("$img" "$filesize")
  done <<< "$IMAGES"
  
  # Let the user select an image
  LOADER_FILE=$(whiptail --backtitle "ProxMenuX" --title "SELECT CUSTOM IMAGE" --menu "$(translate "Choose a custom image:")" 20 70 10 "${IMAGE_OPTIONS[@]}" 3>&1 1>&2 2>&3)
  
  if [ -z "$LOADER_FILE" ]; then
    msg_error "No custom image selected"
    exit_script
  fi
  
  echo -e "${DGN}${TAB}Using Custom Image: ${BGN}$(basename "$LOADER_FILE")${CL}"
  FILE=$(basename "$LOADER_FILE")
}
# ==========================================================







# ==========================================================
# Download Loader
# ==========================================================
function download_loader() {

  echo -e "${DGN}${TAB}Retrieving the URL for the ${BGN}$LOADER_NAME loader${CL}"

  if [[ "$LOADER_TYPE" == "arc" || "$LOADER_TYPE" == "redpill" ]] && ! command -v unzip &> /dev/null; then
    msg_info "Installing unzip..."
    apt-get update -qq && apt-get install -y unzip -qq >/dev/null 2>&1
    if ! command -v unzip &> /dev/null; then
      msg_error "Failed to install unzip"
      sleep 2
      return 1
    fi
    msg_ok "Installed unzip successfully."
  fi
  
  case $LOADER_TYPE in
    arc)
      curl -s https://api.github.com/repos/AuxXxilium/arc/releases/latest \
      | grep "browser_download_url.*\.img\.zip" \
      | cut -d '"' -f 4 \
      | xargs wget -q --show-progress -O "$IMAGES_DIR/arc.img.zip"
      
      if [ -f "$IMAGES_DIR/arc.img.zip" ]; then
        cd "$IMAGES_DIR"
        unzip -q arc.img.zip
        rm arc.img.zip
        FILE="arc.img"
        LOADER_FILE="$IMAGES_DIR/$FILE"
        cd - > /dev/null
      else
        msg_error "Failed to download $LOADER_NAME loader"
        sleep 1
        select_loader
      fi
      ;;
      
    redpill)
      curl -s https://api.github.com/repos/RROrg/rr/releases/latest \
      | grep "browser_download_url.*\.img\.zip" \
      | cut -d '"' -f 4 \
      | xargs wget -q --show-progress -O "$IMAGES_DIR/rr.img.zip"

      if [ -f "$IMAGES_DIR/rr.img.zip" ]; then
          cd "$IMAGES_DIR"
          msg_info "Unzipping $LOADER_NAME loader. Please wait..."
          unzip -qo rr.img.zip
          msg_ok "Unzipped $LOADER_NAME loader successfully."
          rm -f rr.img.zip
          FILE="rr.img"
          LOADER_FILE="$IMAGES_DIR/$FILE"
          cd - > /dev/null
      fi

      ;;
      
    tinycore)
      curl -s https://api.github.com/repos/PeterSuh-Q3/tinycore-redpill/releases/latest \
      | grep "browser_download_url.*tinycore-redpill.v.*img.gz" \
      | cut -d '"' -f 4 \
      | xargs wget -q --show-progress -O "$IMAGES_DIR/tinycore.img.gz"
      
      if [ -f "$IMAGES_DIR/tinycore.img.gz" ]; then
        cd "$IMAGES_DIR"

        msg_info "Unzipping $LOADER_NAME loader. Please wait..."
        gunzip -f tinycore.img.gz 2> /dev/null
        msg_ok "Unzipped $LOADER_NAME loader successfully."
        FILE="tinycore.img"
        LOADER_FILE="$IMAGES_DIR/$FILE"
        cd - > /dev/null

      else
        msg_error "Failed to download $LOADER_NAME loader"
        sleep 1
        select_loader
        
      fi
      ;;
  esac
  
  msg_ok "Downloaded ${CL}${BL}${FILE}${CL} to ${IMAGES_DIR}"
}
# =======================================================





# ==========================================================
# Select UEFI Storage 
# ==========================================================
function select_efi_storage() {
  local vmid=$1
  local STORAGE=""

  STORAGE_MENU=()

  while read -r line; do
    TAG=$(echo $line | awk '{print $1}')
    TYPE=$(echo $line | awk '{printf "%-10s", $2}')
    FREE=$(echo $line | numfmt --field 4-6 --from-unit=K --to=iec --format "%.2f" | awk '{printf( "%9sB", $6)}')
    
    ITEM="  Type: $TYPE Free: $FREE"
    OFFSET=2
    if [[ $((${#ITEM} + $OFFSET)) -gt ${MSG_MAX_LENGTH:-} ]]; then
      MSG_MAX_LENGTH=$((${#ITEM} + $OFFSET))
    fi

    STORAGE_MENU+=("$TAG" "$ITEM" "OFF")
  done < <(pvesm status -content images | awk 'NR>1')

  VALID=$(pvesm status -content images | awk 'NR>1')
  if [ -z "$VALID" ]; then
    msg_error "Unable to detect a valid storage location for EFI disk." >&2
    return 1

  elif [ $((${#STORAGE_MENU[@]} / 3)) -eq 1 ]; then
    STORAGE=${STORAGE_MENU[0]}

  else
    [[ -n "${SPINNER_PID:-}" ]] && kill "$SPINNER_PID" > /dev/null 2>&1
    while [ -z "${STORAGE:+x}" ]; do
      STORAGE=$(whiptail --backtitle "ProxMenuX" --title "EFI Disk Storage" --radiolist \
        "$(translate "Choose the storage volume for the EFI disk (4MB):\n\nUse Spacebar to select.")" \
        16 $(($MSG_MAX_LENGTH + 23)) 6 \
        "${STORAGE_MENU[@]}" 3>&1 1>&2 2>&3) || {
          msg_warn "$(translate "EFI storage selection cancelled.")" >&2
          return 1
        }

    done

  fi
  [[ -z "$STORAGE" ]] && return 1
  echo "$STORAGE"
}
# ==========================================================





# ==========================================================
# Select Storage Loader 
# ==========================================================
function select_storage_volume() {
  local vmid=$1
  local purpose=$2
  local STORAGE=""

  STORAGE_MENU=()

  while read -r line; do
    TAG=$(echo $line | awk '{print $1}')
    TYPE=$(echo $line | awk '{printf "%-10s", $2}')
    FREE=$(echo $line | numfmt --field 4-6 --from-unit=K --to=iec --format "%.2f" | awk '{printf( "%9sB", $6)}')
    
    ITEM="  Type: $TYPE Free: $FREE"
    OFFSET=2
    if [[ $((${#ITEM} + $OFFSET)) -gt ${MSG_MAX_LENGTH:-} ]]; then
      MSG_MAX_LENGTH=$((${#ITEM} + $OFFSET))
    fi

    STORAGE_MENU+=("$TAG" "$ITEM" "OFF")
  done < <(pvesm status -content images | awk 'NR>1')

  VALID=$(pvesm status -content images | awk 'NR>1')
  if [ -z "$VALID" ]; then
    msg_error "Unable to detect a valid storage location." >&2
    return 1
  elif [ $((${#STORAGE_MENU[@]} / 3)) -eq 1 ]; then
    STORAGE=${STORAGE_MENU[0]}
  else
    while [ -z "${STORAGE:+x}" ]; do
      STORAGE=$(whiptail --backtitle "ProxMenuX" --title "Storage Pools" --radiolist \
        "$(translate "Choose the storage volume for $purpose:\n\nUse Spacebar to select.")" \
        16 $(($MSG_MAX_LENGTH + 23)) 6 \
        "${STORAGE_MENU[@]}" 3>&1 1>&2 2>&3) || {
          msg_warn "$(translate "Storage selection cancelled for $purpose.")" >&2
          return 1
        }
    done
  fi
  [[ -z "$STORAGE" ]] && return 1
  echo "$STORAGE"
}






# ==========================================================
# Create VM
# ==========================================================
function create_vm() {

  # Create the VM
  if ! qm create $VMID -agent 1${MACHINE} -tablet 0 -localtime 1${BIOS_TYPE}${CPU_TYPE} -cores $CORE_COUNT -memory $RAM_SIZE \
    -name $HN -tags proxmenux,nas -net0 virtio,bridge=$BRG,macaddr=$MAC$VLAN$MTU -onboot 1 -ostype l26 -scsihw virtio-scsi-pci \
    -serial0 socket; then
    msg_error "Failed to create base VM. Check VM ID and host configuration."
    return 1
  fi
  msg_ok "Create a $NAME"


 
# Check if UEFI (OVMF) is being used ===================
  if [[ "$BIOS_TYPE" == *"ovmf"* ]]; then

    msg_info "Configuring EFI disk"
    if ! EFI_STORAGE=$(select_efi_storage $VMID); then
      msg_error "EFI storage selection failed or was cancelled."
      return 1
    fi
    EFI_DISK_NAME="vm-${VMID}-disk-efivars"
    
    # Determine storage type and extension
    STORAGE_TYPE=$(pvesm status -storage $EFI_STORAGE | awk 'NR>1 {print $2}')
    case $STORAGE_TYPE in
      nfs | dir)
        EFI_DISK_EXT=".raw"
        EFI_DISK_REF="$VMID/"
        ;;
      *)
        EFI_DISK_EXT=""
        EFI_DISK_REF=""
        ;;
    esac
    
    STORAGE_TYPE=$(pvesm status -storage "$EFI_STORAGE" | awk 'NR>1 {print $2}')
    EFI_DISK_ID="efidisk0"

    if [[ "$STORAGE_TYPE" == "btrfs" || "$STORAGE_TYPE" == "dir" || "$STORAGE_TYPE" == "nfs" ]]; then

        if qm set "$VMID" -$EFI_DISK_ID "$EFI_STORAGE:4,efitype=4m,format=raw,pre-enrolled-keys=0" >/dev/null 2>&1; then
            msg_ok "EFI disk created (raw) and configured on ${CL}${BL}$EFI_STORAGE${GN}${CL}"
        else
            msg_error "Failed to configure EFI disk"
            ERROR_FLAG=true
        fi
    else
 
        EFI_DISK_NAME="vm-${VMID}-disk-efivars"
        EFI_DISK_EXT=""
        EFI_DISK_REF=""

        if pvesm alloc "$EFI_STORAGE" "$VMID" "$EFI_DISK_NAME" 4M >/dev/null 2>&1; then
            if qm set "$VMID" -$EFI_DISK_ID "$EFI_STORAGE:${EFI_DISK_NAME},pre-enrolled-keys=0" >/dev/null 2>&1; then
                msg_ok "EFI disk created and configured on ${CL}${BL}$EFI_STORAGE${GN}${CL}"
            else
                msg_error "Failed to configure EFI disk"
                ERROR_FLAG=true
            fi
        else
            msg_error "Failed to create EFI disk"
            ERROR_FLAG=true
        fi
    fi


  fi
# ==========================================================


# Select storage volume for loader =======================

    if ! LOADER_STORAGE=$(select_storage_volume $VMID "loader disk"); then
      msg_error "Loader storage selection failed or was cancelled."
      return 1
    fi
      

    #Run the command in the background and capture its PID
    qm importdisk $VMID ${LOADER_FILE} $LOADER_STORAGE > /tmp/import_log_$VMID.txt 2>&1 &
    import_pid=$!

    # Show a simple progress indicator
    echo -n "Importing loader disk: "
    while kill -0 $import_pid 2>/dev/null; do
        echo -n "."
        sleep 2.5
    done

    wait $import_pid
    rm -f /tmp/import_log_$VMID.txt

    IMPORTED_DISK=$(qm config $VMID | grep -E 'unused[0-9]+' | tail -1 | cut -d: -f1)

    # If the disk was not imported correctly, show an error message but continue
    if [ -z "$IMPORTED_DISK" ]; then
          msg_error "Loader import failed. No disk detected."
          ERROR_FLAG=true
      else
          msg_ok "Loader imported successfully to ${CL}${BL}$LOADER_STORAGE${GN}${CL}"
    fi




 
    STORAGE_TYPE=$(pvesm status -storage "$LOADER_STORAGE" | awk 'NR>1 {print $2}')

    if [[ "$STORAGE_TYPE" == "btrfs" || "$STORAGE_TYPE" == "dir" || "$STORAGE_TYPE" == "nfs" ]]; then

        UNUSED_LINE=$(qm config "$VMID" | grep -E '^unused[0-9]+:')
        IMPORTED_ID=$(echo "$UNUSED_LINE" | cut -d: -f1)
        IMPORTED_REF=$(echo "$UNUSED_LINE" | cut -d: -f2- | xargs)

        if [[ -n "$IMPORTED_REF" && -n "$IMPORTED_ID" ]]; then
            if qm set "$VMID" -ide0 "$IMPORTED_REF" >/dev/null 2>&1; then
                msg_ok "Configured loader disk as ide0"
                qm set "$VMID" -delete "$IMPORTED_ID" >/dev/null 2>&1
            else
                msg_error "Failed to assign loader disk to ide0"
                ERROR_FLAG=true
            fi
        else
            msg_error "Loader import failed. No disk detected in config."
            ERROR_FLAG=true
        fi
    else

        DISK_NAME="vm-${VMID}-disk-0"
        if qm set "$VMID" -ide0 "$LOADER_STORAGE:${DISK_NAME}" >/dev/null 2>&1; then
            msg_ok "Configured loader disk as ide0"
        else
            msg_error "Failed to assign loader disk"
            ERROR_FLAG=true
        fi
    fi




    result=$(qm set "$VMID" -boot order=ide0 2>&1)
    if [[ $? -eq 0 ]]; then
          msg_ok "Loader configured as boot device."
      else
          ERROR_FLAG=true
    fi

# ==========================================================

DISK_INFO=""
CONSOLE_DISK_INFO=""
DISK_SLOT_INDEX=0

if [[ ${#VIRTUAL_DISKS[@]} -gt 0 ]]; then
    for i in "${!VIRTUAL_DISKS[@]}"; do
        IFS=':' read -r STORAGE SIZE <<< "${VIRTUAL_DISKS[$i]}"

        STORAGE_TYPE=$(pvesm status -storage $STORAGE | awk 'NR>1 {print $2}')
        case $STORAGE_TYPE in
            nfs | dir)
                DISK_EXT=".raw"
                DISK_REF="$VMID/"
                ;;
            *)
                DISK_EXT=""
                DISK_REF=""
                ;;
        esac

        DISK_NUM=$((DISK_SLOT_INDEX+1))
        DISK_NAME="vm-${VMID}-disk-${DISK_NUM}${DISK_EXT}"
        SATA_ID="sata${DISK_SLOT_INDEX}"

        if [[ "$STORAGE_TYPE" == "btrfs" || "$STORAGE_TYPE" == "dir" || "$STORAGE_TYPE" == "nfs" ]]; then
            msg_info "Creating virtual disk (format=raw) for $STORAGE_TYPE..."
            if ! qm set "$VMID" -$SATA_ID "$STORAGE:$SIZE,format=raw" >/dev/null 2>&1; then
              msg_error "Failed to assign disk $DISK_NUM ($SATA_ID) on $STORAGE"
              ERROR_FLAG=true
              continue
            fi
        else
            msg_info "Allocating virtual disk for $STORAGE_TYPE..."
            if ! pvesm alloc "$STORAGE" "$VMID" "$DISK_NAME" "$SIZE"G >/dev/null 2>&1; then
              msg_error "Failed to allocate virtual disk $DISK_NUM"
              ERROR_FLAG=true
              continue
            fi
            if ! qm set "$VMID" -$SATA_ID "$STORAGE:${DISK_REF}$DISK_NAME" >/dev/null 2>&1; then
              msg_error "Failed to configure virtual disk as $SATA_ID"
              ERROR_FLAG=true
              continue
            fi
        fi

        msg_ok "Configured virtual disk as $SATA_ID, ${SIZE}GB on ${CL}${BL}$STORAGE${CL} ${GN}"
        DISK_INFO="${DISK_INFO}<p>Virtual Disk $DISK_NUM: ${SIZE}GB on ${STORAGE}</p>"
        CONSOLE_DISK_INFO="${CONSOLE_DISK_INFO}- Virtual Disk $DISK_NUM: ${SIZE}GB on ${STORAGE} ($SATA_ID)\n"
        DISK_SLOT_INDEX=$((DISK_SLOT_INDEX + 1))
    done
fi

EFFECTIVE_IMPORT_DISKS=()
if [[ ${#IMPORT_DISKS[@]} -gt 0 ]]; then
    EFFECTIVE_IMPORT_DISKS=("${IMPORT_DISKS[@]}")
elif [[ ${#PASSTHROUGH_DISKS[@]} -gt 0 ]]; then
    EFFECTIVE_IMPORT_DISKS=("${PASSTHROUGH_DISKS[@]}")
fi

if [[ ${#EFFECTIVE_IMPORT_DISKS[@]} -gt 0 ]]; then
    for DISK in "${EFFECTIVE_IMPORT_DISKS[@]}"; do
        DISK_MODEL=$(lsblk -ndo MODEL "$DISK" | xargs)
        DISK_SIZE=$(lsblk -ndo SIZE "$DISK" | xargs)
        DISK_NUM=$((DISK_SLOT_INDEX+1))
        DISK_ID="sata${DISK_SLOT_INDEX}"

        if qm set "$VMID" -${DISK_ID} ${DISK} >/dev/null 2>&1; then
            msg_ok "Configured import disk ${CL}${BL}($DISK_MODEL $DISK_SIZE)${CL}${GN} as $DISK_ID"
            DISK_INFO="${DISK_INFO}<p>Import Disk ${DISK_NUM}: $DISK ($DISK_MODEL $DISK_SIZE)</p>"
            CONSOLE_DISK_INFO="${CONSOLE_DISK_INFO}- Import Disk ${DISK_NUM}: $DISK ($DISK_MODEL $DISK_SIZE) (${DISK_ID})\n"
            DISK_SLOT_INDEX=$((DISK_SLOT_INDEX + 1))
        else
            msg_error "Failed to configure import disk $DISK as $DISK_ID"
            ERROR_FLAG=true
        fi
    done
fi

if [[ ${#CONTROLLER_NVME_PCIS[@]} -gt 0 ]]; then
    # SR-IOV guard: exclude VFs / active PFs before staging. Mid-flow
    # phase-2 output; a whiptail msgbox stops the scrolling so the user
    # actually sees which devices were dropped. After the ack, each
    # skipped BDF is logged via msg_warn so the action is visible in the
    # captured log as well.
    if declare -F _pci_sriov_filter_array >/dev/null 2>&1; then
        SRIOV_REMOVED=$(_pci_sriov_filter_array CONTROLLER_NVME_PCIS)
        if [[ -n "$SRIOV_REMOVED" ]]; then
            SRIOV_MSG=""
            SRIOV_BDFS=()
            SRIOV_NL=$'\n'
            SRIOV_MSG="$(translate "The following devices were excluded from Controller/NVMe passthrough because they are part of an SR-IOV configuration:")"
            while IFS= read -r SRIOV_ENTRY; do
                [[ -z "$SRIOV_ENTRY" ]] && continue
                SRIOV_BDF="${SRIOV_ENTRY%%|*}"
                SRIOV_ROLE="${SRIOV_ENTRY#*|}"
                SRIOV_FIRST="${SRIOV_ROLE%% *}"
                SRIOV_BDFS+=("$SRIOV_BDF")
                if [[ "$SRIOV_FIRST" == "vf" ]]; then
                    SRIOV_MSG+="${SRIOV_NL}  •  ${SRIOV_BDF}  — $(translate "Virtual Function")"
                else
                    SRIOV_MSG+="${SRIOV_NL}  •  ${SRIOV_BDF}  — $(translate "Physical Function with") ${SRIOV_ROLE#pf-active } $(translate "active VFs")"
                fi
            done <<< "$SRIOV_REMOVED"
            SRIOV_MSG+="${SRIOV_NL}${SRIOV_NL}$(translate "To pass SR-IOV Virtual Functions to a VM, edit the VM configuration manually via the Proxmox web interface.")"

            whiptail --backtitle "ProxMenux" \
                --title "$(translate "SR-IOV Configuration Detected")" \
                --msgbox "$SRIOV_MSG" 18 82

            for SRIOV_SKIPPED in "${SRIOV_BDFS[@]}"; do
                msg_warn "$(translate "Skipping SR-IOV device"): ${SRIOV_SKIPPED}"
            done
        fi
    fi

    if [[ ${#CONTROLLER_NVME_PCIS[@]} -eq 0 ]]; then
        msg_warn "$(translate "No eligible Controller/NVMe devices remain after SR-IOV filtering. Skipping.")"
    fi
fi

if [[ ${#CONTROLLER_NVME_PCIS[@]} -gt 0 ]]; then
    local CONTROLLER_CAN_STAGE=true
    if declare -F _pci_is_iommu_active >/dev/null 2>&1 && ! _pci_is_iommu_active; then
        if [[ "${VM_STORAGE_IOMMU_PENDING_REBOOT:-0}" == "1" ]]; then
            msg_warn "$(translate "IOMMU was configured during this wizard and a reboot is pending.")"
            msg_warn "$(translate "Controller + NVMe assignment will be written now and become active after host reboot.")"
        else
            msg_error "$(translate "IOMMU is not active. Skipping Controller + NVMe assignment.")"
            ERROR_FLAG=true
            CONTROLLER_CAN_STAGE=false
        fi
    fi

    if [[ "$CONTROLLER_CAN_STAGE" != "true" ]]; then
        :
    elif ! _vm_is_q35 "$VMID"; then
        msg_error "$(translate "Controller + NVMe passthrough requires machine type q35. Skipping controller assignment.")"
        ERROR_FLAG=true
    else
        NEED_HOOK_SYNC=false
        HOSTPCI_INDEX=0
        if declare -F _pci_next_hostpci_index >/dev/null 2>&1; then
            HOSTPCI_INDEX=$(_pci_next_hostpci_index "$VMID" 2>/dev/null || echo 0)
        else
            while qm config "$VMID" | grep -q "^hostpci${HOSTPCI_INDEX}:"; do
                HOSTPCI_INDEX=$((HOSTPCI_INDEX + 1))
            done
        fi

        for PCI_DEV in "${CONTROLLER_NVME_PCIS[@]}"; do
            if declare -F _pci_function_assigned_to_vm >/dev/null 2>&1; then
                if _pci_function_assigned_to_vm "$PCI_DEV" "$VMID"; then
                    msg_warn "Controller/NVMe already present in VM config (${PCI_DEV})"
                    continue
                fi
            else
                local PCI_BDF
                PCI_BDF="${PCI_DEV#0000:}"
                if qm config "$VMID" 2>/dev/null | grep -qE "^hostpci[0-9]+:.*(0000:)?${PCI_BDF}([,[:space:]]|$)"; then
                    msg_warn "Controller/NVMe already present in VM config (${PCI_DEV})"
                    continue
                fi
            fi

            SOURCE_VMS=()
            mapfile -t SOURCE_VMS < <(_pci_assigned_vm_ids "$PCI_DEV" "$VMID" 2>/dev/null)
            if [[ ${#SOURCE_VMS[@]} -gt 0 ]]; then
                HAS_RUNNING=false
                for SRC_VMID in "${SOURCE_VMS[@]}"; do
                    if _vm_status_is_running "$SRC_VMID"; then
                        HAS_RUNNING=true
                        msg_warn "$(translate "Controller/NVMe is in use by running VM") ${SRC_VMID} ($(translate "stop source VM first"))"
                    fi
                done

                if [[ "$HAS_RUNNING" == "true" ]]; then
                    continue
                fi

                CONFLICT_ACTION=$(prompt_controller_conflict_policy "$PCI_DEV" "${SOURCE_VMS[@]}")
                case "$CONFLICT_ACTION" in
                    keep_disable_onboot)
                        for SRC_VMID in "${SOURCE_VMS[@]}"; do
                            if _vm_onboot_is_enabled "$SRC_VMID"; then
                                if qm set "$SRC_VMID" -onboot 0 >/dev/null 2>&1; then
                                    msg_warn "$(translate "Start on boot disabled for VM") ${SRC_VMID}"
                                fi
                            fi
                        done
                        NEED_HOOK_SYNC=true
                        ;;
                    move_remove_source)
                        SLOT_BASE=$(_pci_slot_base "$PCI_DEV")
                        for SRC_VMID in "${SOURCE_VMS[@]}"; do
                            if _remove_pci_slot_from_vm_config "$SRC_VMID" "$SLOT_BASE"; then
                                msg_ok "$(translate "Controller/NVMe removed from source VM") ${SRC_VMID} (${PCI_DEV})"
                            fi
                        done
                        ;;
                    *)
                        msg_info2 "$(translate "Skipped device"): ${PCI_DEV}"
                        continue
                        ;;
                esac
            fi

            if qm set "$VMID" --hostpci${HOSTPCI_INDEX} "${PCI_DEV},pcie=1" >/dev/null 2>&1; then
                msg_ok "Configured controller/NVMe as hostpci${HOSTPCI_INDEX}: ${PCI_DEV}"
                DISK_INFO="${DISK_INFO}<p>Controller/NVMe: ${PCI_DEV}</p>"
                CONSOLE_DISK_INFO="${CONSOLE_DISK_INFO}- Controller/NVMe: ${PCI_DEV} (hostpci${HOSTPCI_INDEX})\n"
                HOSTPCI_INDEX=$((HOSTPCI_INDEX + 1))
            else
                msg_error "Failed to configure controller/NVMe: ${PCI_DEV}"
                ERROR_FLAG=true
            fi
        done

        if [[ "$NEED_HOOK_SYNC" == "true" ]] && declare -F sync_proxmenux_gpu_guard_hooks >/dev/null 2>&1; then
            ensure_proxmenux_gpu_guard_hookscript
            sync_proxmenux_gpu_guard_hooks
            msg_ok "$(translate "VM hook guard synced for shared controller/NVMe protection")"
        fi
    fi
fi

if [[ ${#VIRTUAL_DISKS[@]} -eq 0 && ${#EFFECTIVE_IMPORT_DISKS[@]} -eq 0 && ${#CONTROLLER_NVME_PCIS[@]} -eq 0 ]]; then
    msg_error "No disks/controllers configured."
    exit_script
fi

# HTML description
HTML_DESC="<div align='center'>
<table style='width: 100%; border-collapse: collapse;'>
<tr>
<td style='width: 100px; vertical-align: middle;'>
<img src='https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo_desc.png' alt='ProxMenux Logo' style='height: 100px;'>
</td>
<td style='vertical-align: middle;'>
<h1 style='margin: 0;'>Synology DSM VM</h1>
<p style='margin: 0;'>Created with ProxMenuX</p>
<p style='margin: 0;'>Loader: $LOADER_NAME</p>
</td>
</tr>
</table>

<p>
<a href='https://macrimi.github.io/ProxMenux/docs/create-vm/synology' target='_blank'><img src='https://img.shields.io/badge/📚_Docs-blue' alt='Docs'></a>
<a href='https://raw.githubusercontent.com/MacRimi/ProxMenux/refs/heads/main/scripts/vm/synology.sh' target='_blank'><img src='https://img.shields.io/badge/💻_Code-green' alt='Code'></a>
<a href='$LOADER_URL' target='_blank'><img src='https://img.shields.io/badge/📦_Loader-orange' alt='Loader'></a>
<a href='https://ko-fi.com/macrimi' target='_blank'><img src='https://img.shields.io/badge/☕_Ko--fi-red' alt='Ko-fi'></a>
</p>

<div>
${DISK_INFO}
</div>
</div>"

msg_info "Setting VM description"
if ! qm set "$VMID" -description "$HTML_DESC" >/dev/null 2>&1; then
    msg_error "Failed to set VM description"
    exit_script
fi
msg_ok "Configured VM description"
  
  
if [ "$ERROR_FLAG" = true ]; then
   msg_error "VM created with errors. Check configuration." 
else
if [[ "${WIZARD_ADD_GPU:-no}" == "yes" ]]; then
  WIZARD_GPU_RESULT="cancelled"
  run_gpu_passthrough_wizard
  replay_vm_wizard_capture
fi

local GPU_WIZARD_APPLIED="no"
local GPU_WIZARD_REBOOT_REQUIRED="no"
case "${WIZARD_GPU_RESULT:-}" in
  applied)
    GPU_WIZARD_APPLIED="yes"
    ;;
  applied_reboot_required)
    GPU_WIZARD_APPLIED="yes"
    GPU_WIZARD_REBOOT_REQUIRED="yes"
    ;;
esac

if [[ "${WIZARD_ADD_GPU:-no}" == "yes" && "$GPU_WIZARD_APPLIED" == "yes" ]]; then
  msg_success "$(translate "Completed Successfully with GPU passthrough configured!")"
  if [[ "$GPU_WIZARD_REBOOT_REQUIRED" == "yes" ]]; then
    msg_warn "$(translate "Host VFIO configuration changed (initramfs updated). Reboot required before starting the VM.")"
  fi
else
  msg_success "$(translate "Completed Successfully!")"
  if [[ "${WIZARD_ADD_GPU:-no}" == "yes" && "$WIZARD_GPU_RESULT" == "no_gpu" ]]; then
    msg_warn "$(translate "GPU passthrough was skipped (no compatible GPU detected).")"
  elif [[ "${WIZARD_ADD_GPU:-no}" == "yes" && "$WIZARD_GPU_RESULT" != "applied" ]]; then
    msg_warn "$(translate "GPU passthrough was not applied.")"
  fi
fi

echo -e "${TAB}${GN}$(translate "Next Steps:")${CL}"
echo -e "${TAB}1. $(translate "Start the VM")"
echo -e "${TAB}2. $(translate "Open the VM console and wait for the loader to boot")"
echo -e "${TAB}3. $(translate "In the loader interface, follow the instructions to select your Synology model")"
echo -e "${TAB}4. $(translate "Complete the DSM installation wizard")"
echo -e "${TAB}5. $(translate "Find your device using https://finds.synology.com")"
if [[ "$GPU_WIZARD_APPLIED" == "yes" ]]; then
  echo -e "${TAB}- $(translate "If you want to use a physical monitor on the passthrough GPU:")"
  echo -e "${TAB}• $(translate "First complete DSM setup and verify Web UI/SSH access.")"
  echo -e "${TAB}• $(translate "Then change the VM display to none (vga: none) when the system is stable.")"
fi
local HOST_REBOOT_REQUIRED="no"
local REBOOT_REASONS=""
if [[ "${VM_STORAGE_IOMMU_PENDING_REBOOT:-0}" == "1" ]]; then
  HOST_REBOOT_REQUIRED="yes"
  msg_ok "$(translate "IOMMU has been enabled — a system reboot is required")"
  REBOOT_REASONS+="$(translate "IOMMU has been enabled on this system.")\n"
fi
if [[ "$GPU_WIZARD_REBOOT_REQUIRED" == "yes" ]]; then
  HOST_REBOOT_REQUIRED="yes"
  REBOOT_REASONS+="$(translate "GPU passthrough changes require a host reboot.")\n"
fi
if [[ "$HOST_REBOOT_REQUIRED" == "yes" ]]; then
  echo ""
  if whiptail --title "$(translate "Reboot Required")" --yesno \
"\n${REBOOT_REASONS}\n$(translate "A host reboot is required before starting the VM. Reboot now?")" 13 78; then
    msg_warn "$(translate "Rebooting the system...")"
    reboot
  else
    echo ""
    msg_info2 "$(translate "To use the VM without issues, the host must be restarted before starting it.")"
    msg_info2 "$(translate "Do not start the VM until the system has been rebooted.")"
  fi
fi
echo -e

#msg_success "$(translate "Press Enter to return to the main menu...")"
#read -r

fi
  
}

# ==========================================================



# ==========================================================
# Main execution
# ==========================================================
header_info
#echo -e "\n Loading..."
sleep 1

# Start script
if whiptail --backtitle "ProxMenuX" --title "$NAME" --yesno "$(translate "This will create a New $NAME. Proceed?")" 10 58; then
  start_vm_wizard_capture
  if ! start_script; then
    stop_vm_wizard_capture
    msg_warn "$(translate "VM creation cancelled before disk planning.")"
    exit 0
  fi
  prompt_optional_gpu_passthrough
  if [[ "${WIZARD_ADD_GPU:-no}" != "yes" ]]; then
    stop_vm_wizard_capture
  fi
else
  clear
  exit
fi

# Create VM
create_vm
stop_vm_wizard_capture

# ==========================================================
