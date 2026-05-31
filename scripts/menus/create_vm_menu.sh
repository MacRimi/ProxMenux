#!/usr/bin/env bash

# ==========================================================
# ProxMenux - Virtual Machine Creator Menu
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Central VM creation dispatcher for ProxMenux. Presents the user
# with OS-family options (NAS, Windows, Linux, macOS, Others) and
# routes to the matching ISO selector and configuration wizard.
#
# Features:
# - Dispatches to ISO selectors: NAS / Windows / Linux / Others.
# - Default vs Advanced flows: CPU, RAM, BIOS, network, storage.
# - Virtual disks, disk import, and Controller+NVMe passthrough.
# - Optional GPU passthrough wizard post-creation.
# - Auto-generates a styled HTML description for each VM.
# - macOS path is external: launches the OSX-PROXMOX installer.
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_DEFAULT="/usr/local/share/proxmenux/scripts"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$LOCAL_SCRIPTS_LOCAL/vm/disk_selector.sh" ]]; then
  LOCAL_SCRIPTS="$LOCAL_SCRIPTS_LOCAL"
else
  LOCAL_SCRIPTS="$LOCAL_SCRIPTS_DEFAULT"
fi

VM_REPO="$LOCAL_SCRIPTS/vm"
ISO_REPO="$LOCAL_SCRIPTS/vm"
MENU_REPO="$LOCAL_SCRIPTS/menus"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
[[ ! -f "$UTILS_FILE" ]] && UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

# Source utilities and required scripts
if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
else
    echo "Error: $UTILS_FILE not found"
    exit 1
fi

load_language
initialize_cache

# Source VM management scripts
[[ -f "$VM_REPO/vm_configurator.sh" ]] && source "$VM_REPO/vm_configurator.sh" || { echo "Error: vm_configurator.sh not found"; exit 1; }
[[ -f "$VM_REPO/disk_selector.sh" ]] && source "$VM_REPO/disk_selector.sh" || { echo "Error: disk_selector.sh not found"; exit 1; }
[[ -f "$VM_REPO/vm_creator.sh" ]] && source "$VM_REPO/vm_creator.sh" || { echo "Error: vm_creator.sh not found"; exit 1; }



function header_info() {
  clear
  show_proxmenux_logo
  msg_title "ProxMenux VM Creator"
}

VM_WIZARD_CAPTURE_FILE=""
VM_WIZARD_CAPTURE_ACTIVE=0
VM_STORAGE_IOMMU_PENDING_REBOOT=0

function start_vm_wizard_capture() {
  [[ "${VM_WIZARD_CAPTURE_ACTIVE:-0}" -eq 1 ]] && return 0
  VM_WIZARD_CAPTURE_FILE="/tmp/proxmenux_vm_wizard_screen_capture_$$.txt"
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

function has_usable_gpu_for_vm_passthrough() {
  lspci -nn 2>/dev/null \
    | grep -iE "VGA compatible controller|3D controller|Display controller" \
    | grep -ivE "Ethernet|Network|Audio" \
    | grep -ivE "ASPEED|AST[0-9]{3,4}|Matrox|G200e|BMC" \
    | grep -q .
}

# ==========================================================
# MAIN EXECUTION
# ==========================================================

#header_info
#echo -e "\n Loading..."
#sleep 1




function start_vm_configuration() {

  if (whiptail --title "ProxMenux" --yesno "$(translate "Use Default Settings?")" --no-button "$(translate "Advanced")" 10 60); then
    #header_info
    #load_default_vm_config "$OS_TYPE"

    if [[ -z "$HN" ]]; then
      HN=$(whiptail --inputbox "$(translate "Enter a name for the new virtual machine:")" 10 60 --title "VM Hostname" 3>&1 1>&2 2>&3)
      [[ -z "$HN" ]] && HN="custom-vm"
    fi
    header_info
    load_default_vm_config "$OS_TYPE"
    apply_default_vm_config
  else
    header_info
    echo -e "${CUS}$(translate "Using advanced configuration")${CL}"
    configure_vm_advanced "$OS_TYPE"
  fi
}



while true; do
  VM_STORAGE_IOMMU_PENDING_REBOOT=0
  WIZARD_CONFLICT_POLICY=""
  WIZARD_CONFLICT_SCOPE=""
  export WIZARD_CONFLICT_POLICY WIZARD_CONFLICT_SCOPE
  OS_TYPE=$(dialog --colors --backtitle "ProxMenux" \
    --title "$(translate "Select System Type")" \
    --menu "\n$(translate "Choose the type of virtual system to install:")" 20 70 10 \
    1 "$(translate "Create") VM System NAS" \
    2 "$(translate "Create") VM System Windows" \
    3 "$(translate "Create") VM System Linux" \
    ""          "" \
    ""  "\Z4───────────────── Community Scripts ─────────────────\Zn" \
    ""          "" \
    4 "$(translate "Create") VM System macOS (OSX-PROXMOX)" \
    5 "$(translate "Create") VM System Others (based Linux)" \
    ""          "" \
    6 "$(translate "Return to Main Menu")" \
    3>&1 1>&2 2>&3)

  [[ $? -ne 0 || "$OS_TYPE" == "6" ]] && exec bash "$MENU_REPO/main_menu.sh"

  case "$OS_TYPE" in
    1)
      source "$ISO_REPO/select_nas_iso.sh" && select_nas_iso || continue
      ;;
    2)
      source "$ISO_REPO/select_windows_iso.sh" && select_windows_iso || continue
      ;;
    3)
      source "$ISO_REPO/select_linux_iso.sh" && select_linux_iso || continue
      ;;
    4)
      whiptail --title "OSX-PROXMOX" --yesno "$(translate "This is an external script that creates a macOS VM in Proxmox VE in just a few steps, whether you are using AMD or Intel hardware.")\n\n$(translate "The script clones the osx-proxmox.com repository and once the setup is complete, the server will automatically reboot.")\n\n$(translate "Make sure there are no critical services running as they will be interrupted. Ensure your server can be safely rebooted.")\n\n$(translate  "Visit https://osx-proxmox.com for more information.")\n\n$(translate "Do you want to run the script now?")" 24 70
      if [[ $? -eq 0 ]]; then
        bash -c "$(curl -fsSL https://install.osx-proxmox.com)"
      fi
      continue
      ;;
    5)
      source "$ISO_REPO/select_linux_iso.sh" && select_linux_other_scripts || continue
      ;;
  esac

  if ! confirm_vm_creation; then
    stop_vm_wizard_capture
    continue  
  fi

  start_vm_wizard_capture

  if ! start_vm_configuration; then
    stop_vm_wizard_capture
    continue
  fi


  unset DISK_TYPE
  if ! select_disk_type; then
    stop_vm_wizard_capture
    msg_error "$(translate "Storage plan selection failed or cancelled")"
    continue  
  fi

  WIZARD_ADD_GPU="no"
  if has_usable_gpu_for_vm_passthrough; then
    if whiptail --backtitle "ProxMenux" --title "$(translate "Optional GPU Passthrough")" \
      --yesno "$(translate "Do you want to configure GPU passthrough for this VM now?")\n\n$(translate "This will launch the GPU assistant after VM creation and may require a host reboot.")" 12 78 --defaultno; then
      WIZARD_ADD_GPU="yes"
    fi
  else
    msg_warn "$(translate "No compatible GPU detected for VM passthrough. Skipping GPU wizard option.")"
  fi
  export WIZARD_ADD_GPU

  if [[ "$WIZARD_ADD_GPU" != "yes" ]]; then
    stop_vm_wizard_capture
  fi

  if ! create_vm; then
    stop_vm_wizard_capture
    msg_error "$(translate "VM creation failed or was cancelled during storage setup.")"
    continue
  fi
  stop_vm_wizard_capture
  break
done
