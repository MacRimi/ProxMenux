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



BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi

load_language
initialize_cache


function confirm_vm_creation() {
  clear
  local CONFIRM_TITLE="${HN:-$(translate "New Virtual Machine")}"
  local CONFIRM_MSG="$(translate "This will create a new VM") $CONFIRM_TITLE. $(translate "Proceed?")"

  if ! whiptail --backtitle "ProxMenux" --title "$CONFIRM_TITLE" --yesno "$CONFIRM_MSG" 10 60; then
    header_info
    msg_warn "$(translate "VM creation cancelled by user.")"
    sleep 1
    return 1
  fi
  return 0
}


function generate_mac() {
  local GEN_MAC="02"
  for i in {1..5}; do
    BYTE=$(printf "%02X" $((RANDOM % 256)))
    GEN_MAC="${GEN_MAC}:${BYTE}"
  done
  echo "$GEN_MAC"
}

function load_default_vm_config() {
  local os_type="$1"

  VMID=$(pvesh get /cluster/nextid 2>/dev/null || echo "100")
  MAC=$(generate_mac)

  case "$os_type" in
    "1")

      CORE_COUNT="2"
      RAM_SIZE="8192"
      MACHINE=" -machine q35"
      BIOS_TYPE=" -bios ovmf"
      START_VM="no"
      ;;
    "2")

      CORE_COUNT="4"
      RAM_SIZE="8192"
      MACHINE=" -machine q35"
      BIOS_TYPE=" -bios ovmf"
      START_VM="no"
      ;;
    "3")

      CORE_COUNT="2"
      RAM_SIZE="4096"
      MACHINE=" -machine q35"
      BIOS_TYPE=" -bios ovmf"
      START_VM="no"
      ;;
  esac

  if [[ "$os_type" == "1" && "$HN" == "OpenMediaVault" ]]; then
  BIOS_TYPE=" -bios seabios"
  fi


  [[ -z "$CORE_COUNT" ]] && CORE_COUNT="2"
  [[ -z "$RAM_SIZE" ]] && RAM_SIZE="4096"

  CPU_TYPE=" -cpu host"
  BRG="vmbr0"
  VLAN=""
  MTU=""
  SERIAL_PORT="socket"
  FORMAT=""
  DISK_CACHE=""
  
}

function apply_default_vm_config() {
  echo -e "${DEF}$(translate "Applying default VM configuration")${CL}"
  echo -e " ${TAB}${DGN}$(translate "Virtual Machine ID")${CL}: ${BGN}$VMID${CL}"
  echo -e " ${TAB}${DGN}$(translate "Hostname")${CL}: ${BGN}$HN${CL}"
  echo -e " ${TAB}${DGN}$(translate "CPU Cores")${CL}: ${BGN}$CORE_COUNT${CL}"
  echo -e " ${TAB}${DGN}$(translate "RAM Size")${CL}: ${BGN}$RAM_SIZE MiB${CL}"
  echo -e " ${TAB}${DGN}$(translate "Machine Type")${CL}: ${BGN}${MACHINE/ -machine /}${CL}"
  echo -e " ${TAB}${DGN}$(translate "BIOS Type")${CL}: ${BGN}${BIOS_TYPE/ -bios /}${CL}"
  echo -e " ${TAB}${DGN}$(translate "CPU Model")${CL}: ${BGN}${CPU_TYPE/ -cpu /}${CL}"
  echo -e " ${TAB}${DGN}$(translate "Network Bridge")${CL}: ${BGN}$BRG${CL}"
  echo -e " ${TAB}${DGN}$(translate "MAC Address")${CL}: ${BGN}$MAC${CL}"
  echo -e " ${TAB}${DGN}$(translate "Start VM after creation")${CL}: ${BGN}$START_VM${CL}"
  echo -e
  echo -e "${DEF}$(translate "Creating VM with the above configuration")${CL}"
}



function configure_vm_advanced() {
  header_info


  NEXTID=$(pvesh get /cluster/nextid 2>/dev/null || echo "100")
  [[ -z "$MAC" ]] && MAC=$(generate_mac)

  # VMID
  while true; do
    VMID=$(whiptail --backtitle "ProxMenux" \
      --inputbox "$(translate "Set Virtual Machine ID")" 8 60 "$NEXTID" \
      --title "VM ID" --cancel-button Exit 3>&1 1>&2 2>&3) || return 1

    if [[ -z "$VMID" ]]; then
      VMID="$NEXTID"
    fi

    if qm status "$VMID" &>/dev/null || pct status "$VMID" &>/dev/null; then
      msg_error "$(translate "ID already in use. Please choose another.")"
      sleep 1
    else
      break
    fi
  done

  # Hostname
  HN=$(whiptail --backtitle "ProxMenux" \
    --inputbox "$(translate "Set Hostname")" 8 60 "$HN" \
    --title "Hostname" 3>&1 1>&2 2>&3) || return 1
  [[ -z "$HN" ]] && HN="vm-proxmenux"

  # Machine Type
  MACHINE_TYPE=$(whiptail --backtitle "ProxMenux" --title "$(translate "Machine Type")" \
    --radiolist "$(translate "Select machine type")" 10 60 2 \
    "q35"     "QEMU q35" ON \
    "i440fx"  "Legacy i440fx" OFF 3>&1 1>&2 2>&3) || return 1
  [[ "$MACHINE_TYPE" == "q35" ]] && MACHINE=" -machine q35" && FORMAT="" || MACHINE="" && FORMAT=",efitype=4m"

  # BIOS
  if [[ "$HN" == "OpenMediaVault" ]]; then
    BIOS_TYPE=" -bios seabios"
  else
    BIOS=$(whiptail --backtitle "ProxMenux" --title "$(translate "BIOS Type")" \
      --radiolist "$(translate "Choose BIOS type")" 10 60 2 \
      "ovmf"    "UEFI (OVMF)" ON \
      "seabios" "Legacy BIOS (SeaBIOS)" OFF 3>&1 1>&2 2>&3) || return 1
    BIOS_TYPE=" -bios $BIOS"
  fi

  # CPU Type
#  CPU_CHOICE=$(whiptail --backtitle "ProxMenux" --title "$(translate "CPU Model")" \
#    --radiolist "$(translate "Select CPU model")" 10 60 2 \
#    "host"  "Host (recommended)" ON \
#    "kvm64" "Generic KVM64" OFF 3>&1 1>&2 2>&3) || return 1
#  [[ "$CPU_CHOICE" == "host" ]] && CPU_TYPE=" -cpu host" || CPU_TYPE=" -cpu kvm64"

  CPU_CHOICE=$(whiptail --backtitle "ProxMenux" --title "$(translate "CPU Model")" \
  --radiolist "$(translate "Select CPU model")" 17 70 11 \
  "host"          "Host (recommended)" ON \
  "kvm64"         "Generic KVM64" OFF \
  "kvm32"         "Generic KVM32" OFF \
  "qemu64"        "QEMU 64-bit CPU" OFF \
  "qemu32"        "QEMU 32-bit CPU" OFF \
  "max"           "Expose all QEMU CPU features" OFF \
  "x86-64-v2"     "Nehalem-class (x86-64-v2)" OFF \
  "x86-64-v2-AES" "Same as v2 but with AES" OFF \
  "x86-64-v3"     "Haswell-class (x86-64-v3)" OFF \
  "x86-64-v4"     "Skylake-class (x86-64-v4)" OFF 3>&1 1>&2 2>&3) || return 1

  CPU_TYPE=" -cpu $CPU_CHOICE"

  # Core Count
  CORE_COUNT=$(whiptail --backtitle "ProxMenux" --inputbox "$(translate "Number of CPU cores (default: 2)")" \
    8 60 "${CORE_COUNT:-2}" --title "CPU Cores" 3>&1 1>&2 2>&3) || return 1
  [[ -z "$CORE_COUNT" ]] && CORE_COUNT="2"

  # RAM
  RAM_SIZE=$(whiptail --backtitle "ProxMenux" --inputbox "$(translate "Amount of RAM in MiB (default: 4096)")" \
    8 60 "${RAM_SIZE:-4096}" --title "RAM" 3>&1 1>&2 2>&3) || return 1
  [[ -z "$RAM_SIZE" ]] && RAM_SIZE="4096"

  # Bridge
  BRG=$(whiptail --backtitle "ProxMenux" --inputbox "$(translate "Set network bridge (default: vmbr0)")" \
    8 60 "${BRG:-vmbr0}" --title "Bridge" 3>&1 1>&2 2>&3) || return 1

  # MAC
  MAC_INPUT=$(whiptail --backtitle "ProxMenux" --inputbox "$(translate "Set MAC Address (leave empty for automatic)")" \
    8 60 "$MAC" --title "MAC Address" 3>&1 1>&2 2>&3) || return 1
  [[ -z "$MAC_INPUT" ]] && MAC=$(generate_mac) || MAC="$MAC_INPUT"

  # VLAN
  VLAN_INPUT=$(whiptail --backtitle "ProxMenux" --inputbox "$(translate "Set VLAN (leave empty for none)")" \
    8 60 "" --title "VLAN" 3>&1 1>&2 2>&3) || return 1
  VLAN=""
  [[ -n "$VLAN_INPUT" ]] && VLAN=",tag=$VLAN_INPUT"

  # MTU
  MTU_INPUT=$(whiptail --backtitle "ProxMenux" --inputbox "$(translate "Set MTU (leave empty for default)")" \
    8 60 "" --title "MTU" 3>&1 1>&2 2>&3) || return 1
  MTU=""
  [[ -n "$MTU_INPUT" ]] && MTU=",mtu=$MTU_INPUT"

  # Serial Port
  if (whiptail --backtitle "ProxMenux" --title "Serial Port" \
    --yesno "$(translate "Do you want to enable the serial port") (socket)?" 10 60); then
    SERIAL_PORT="socket"
  else
    SERIAL_PORT=""
  fi

  # Start VM
  if (whiptail --backtitle "ProxMenux" --title "$(translate "Start VM")" \
    --yesno "$(translate "Start VM after creation?")" 10 60); then
    START_VM="yes"
  else
    START_VM="no"
  fi

  echo -e "${CUS}$(translate "Using advanced configuration")${CL}"
  echo -e " ${TAB}${DGN}$(translate "Virtual Machine ID")${CL}: ${BGN}$VMID${CL}"
  echo -e " ${TAB}${DGN}$(translate "Hostname")${CL}: ${BGN}$HN${CL}"
  echo -e " ${TAB}${DGN}$(translate "CPU Cores")${CL}: ${BGN}$CORE_COUNT${CL}"
  echo -e " ${TAB}${DGN}$(translate "RAM Size")${CL}: ${BGN}$RAM_SIZE MiB${CL}"
  echo -e " ${TAB}${DGN}$(translate "Machine Type")${CL}: ${BGN}${MACHINE/ -machine /}${CL}"
  echo -e " ${TAB}${DGN}$(translate "BIOS Type")${CL}: ${BGN}${BIOS_TYPE/ -bios /}${CL}"
  echo -e " ${TAB}${DGN}$(translate "CPU Model")${CL}: ${BGN}${CPU_TYPE/ -cpu /}${CL}"
  echo -e " ${TAB}${DGN}$(translate "Network Bridge")${CL}: ${BGN}$BRG${CL}"
  echo -e " ${TAB}${DGN}$(translate "MAC Address")${CL}: ${BGN}$MAC${CL}"
  echo -e " ${TAB}${DGN}$(translate "VLAN")${CL}: ${BGN}${VLAN:-None}${CL}"
  echo -e " ${TAB}${DGN}$(translate "Interface MTU")${CL}: ${BGN}${MTU:-Default}${CL}"
  echo -e " ${TAB}${DGN}$(translate "Start VM")${CL}: ${BGN}$START_VM${CL}"
  echo -e
  echo -e "${CUS}$(translate "Creating VM with the above configuration")${CL}"
  sleep 1



  return 0
}
