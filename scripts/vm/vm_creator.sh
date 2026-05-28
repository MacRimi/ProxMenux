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
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/iso_storage_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_LOCAL/global/iso_storage_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/iso_storage_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_DEFAULT/global/iso_storage_helpers.sh"
fi
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/pci_passthrough_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_LOCAL/global/pci_passthrough_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/pci_passthrough_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_DEFAULT/global/pci_passthrough_helpers.sh"
fi

load_language
initialize_cache
VM_STORAGE_IOMMU_PENDING_REBOOT="${VM_STORAGE_IOMMU_PENDING_REBOOT:-0}"

# ==========================================================
# Mont ISOs
# ==========================================================
function mount_iso_to_vm() {
  local vmid="$1"
  local iso_path="$2"
  local device="$3"
  local iso_volid="${4:-}"
  local iso_label

  if [[ -z "$iso_volid" && -n "$iso_path" ]]; then
    if [[ "$iso_path" == *":iso/"* ]]; then
      iso_volid="$iso_path"
    elif [[ -f "$iso_path" ]] && declare -F iso_path_to_volid >/dev/null 2>&1; then
      iso_volid=$(iso_path_to_volid "$iso_path" 2>/dev/null || true)
    fi
  fi

  if [[ -z "$iso_volid" ]]; then
    msg_warn "$(translate "ISO not found to mount on device") $device"
    return 1
  fi

  iso_label="$(basename "${iso_volid#*:}")"
  if qm set "$vmid" -$device "${iso_volid},media=cdrom" >/dev/null 2>&1; then
    msg_ok "$(translate "Mounted ISO on device") $device → $iso_label"
  else
    msg_warn "$(translate "Could not mount ISO on device") $device → $iso_volid"
    return 1
  fi
}




# ==========================================================
# Select Interface Type
# ==========================================================
function select_interface_type() {
  INTERFACE_TYPE=$(whiptail --backtitle "ProxMenux" --title "$(translate "Select Disk Interface")" --radiolist \
    "$(translate "Select the bus type for the disks:")" 15 70 4 \
    "scsi"    "$(translate "SCSI   (recommended for Linux and Windows)")" ON \
    "sata"    "$(translate "SATA   (standard - high compatibility)")" OFF \
    "virtio"  "$(translate "VirtIO (advanced - high performance)")" OFF \
    "ide"     "IDE    (legacy)" OFF \
    3>&1 1>&2 2>&3) || {
      msg_warn "$(translate "Disk interface selection cancelled.")" >&2
      return 1
    }

  case "$INTERFACE_TYPE" in
    "scsi"|"sata")
      DISCARD_OPTS=",discard=on,ssd=on"
      ;;
    "virtio")
      DISCARD_OPTS=",discard=on"
      ;;
    "ide")
      DISCARD_OPTS=""
      ;;
  esac

  msg_ok "$(translate "Disk interface selected:") $INTERFACE_TYPE"
}

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
# EFI/TPM
# ==========================================================
function select_storage_target() {
  local PURPOSE="$1"
  local vmid="$2"
  local STORAGE=""
  local STORAGE_MENU=()

  while read -r line; do
    TAG=$(echo "$line" | awk '{print $1}')
    TYPE=$(echo "$line" | awk '{printf "%-10s", $2}')
    FREE=$(echo "$line" | numfmt --field 4-6 --from-unit=K --to=iec --format "%.2f" | awk '{printf("%9sB", $6)}')
    STORAGE_MENU+=("$TAG" "$(translate "Type:") $TYPE $(translate "Free:") $FREE" "OFF")
  done < <(pvesm status -content images | awk 'NR>1')

  if [[ ${#STORAGE_MENU[@]} -eq 0 ]]; then
    msg_error "$(translate "Unable to detect a valid storage location for $PURPOSE disk.")" >&2
    return 1
  elif [[ $((${#STORAGE_MENU[@]} / 3)) -eq 1 ]]; then
    STORAGE="${STORAGE_MENU[0]}"
  else
    [[ -n "${SPINNER_PID:-}" ]] && kill "$SPINNER_PID" >/dev/null 2>&1
    STORAGE=$(whiptail --backtitle "ProxMenux" --title "$(translate "$PURPOSE Disk Storage")" --radiolist \
      "$(translate "Choose the storage volume for the $PURPOSE disk (4MB):\n\nUse Spacebar to select.")" 16 70 6 \
      "${STORAGE_MENU[@]}" 3>&1 1>&2 2>&3) || {
        msg_warn "$(translate "$PURPOSE disk storage selection cancelled.")" >&2
        return 1
      }
  fi

  [[ -z "$STORAGE" ]] && return 1
  echo "$STORAGE"
}




# ==========================================================
# Guest Agent Configurator 
# ==========================================================
function configure_guest_agent() {
  if [[ -z "$VMID" ]]; then
    msg_error "$(translate "No VMID defined. Cannot apply guest agent config.")"
    return 1
  fi

  msg_info "$(translate "Adding QEMU Guest Agent support...")"

  # Habilitar el agente en la VM
  qm set "$VMID" -agent enabled=1 >/dev/null 2>&1

  # Añadir canal de comunicación virtio
  qm set "$VMID" -chardev socket,id=qga0,path=/var/run/qemu-server/$VMID.qga,server=on,wait=off >/dev/null 2>&1
  qm set "$VMID" -device virtio-serial-pci -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0 >/dev/null 2>&1

  msg_ok "$(translate "Guest Agent configuration applied")"

}

function run_gpu_passthrough_wizard() {
  [[ "${WIZARD_ADD_GPU:-no}" != "yes" ]] && return 0

  local gpu_script="$LOCAL_SCRIPTS/gpu_tpu/add_gpu_vm.sh"
  local wizard_result_file=""
  if [[ ! -f "$gpu_script" ]]; then
    local local_gpu_script
    local_gpu_script="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)/gpu_tpu/add_gpu_vm.sh"
    [[ -f "$local_gpu_script" ]] && gpu_script="$local_gpu_script"
  fi

  if [[ ! -f "$gpu_script" ]]; then
    msg_warn "$(translate "GPU passthrough assistant not found. You can run it later from Hardware Graphics.")"
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
# Create VM
# ==========================================================
function create_vm() {
  local BOOT_ORDER=""
  local DISK_INFO=""
  local DISK_INDEX=0
  local ISO_DIR="/var/lib/vz/template/iso"


  if [[ -n "$ISO_PATH" && -n "$ISO_URL" && ! -f "$ISO_PATH" ]]; then
  
    if [[ "$ISO_URL" == *"sourceforge.net"* ]]; then
   
      wget --content-disposition --show-progress -O "$ISO_PATH" "$ISO_URL"
    else
  
      wget --no-verbose --show-progress -O "$ISO_PATH" "$ISO_URL"
    fi

  
    if [[ -f "$ISO_PATH" ]]; then
      ISO_VOLID="${ISO_VOLID:-local:iso/$(basename "$ISO_PATH")}"
      msg_ok "$(translate "ISO image downloaded")"
    else
      msg_error "$(translate "Failed to download ISO image")"
      return 1
    fi
  fi

  if [[ "$OS_TYPE" == "2" ]]; then
	  GUEST_OS_TYPE="win10"
    else
	  GUEST_OS_TYPE="l26"
  fi

  local VM_TAGS="proxmenux"
  case "${OS_TYPE:-}" in
    1) VM_TAGS="proxmenux,nas" ;;
    2) VM_TAGS="proxmenux,windows" ;;
    *) VM_TAGS="proxmenux,linux" ;;
  esac



 # qm create "$VMID" -agent 1${MACHINE} -tablet 0 -localtime 1${BIOS_TYPE}${CPU_TYPE} \
 #   -cores "$CORE_COUNT" -memory "$RAM_SIZE" -name "$HN" -tags proxmenux \
 #   -net0 "virtio,bridge=$BRG,macaddr=$MAC$VLAN$MTU" -ostype "$GUEST_OS_TYPE" \
 #   -scsihw virtio-scsi-pci \
 #   $( [[ -n "$SERIAL_PORT" ]] && echo "-serial0 $SERIAL_PORT" ) >/dev/null 2>&1


if ! qm create "$VMID" \
  -agent 1${MACHINE:+ $MACHINE} \
  -localtime 1${BIOS_TYPE:+ $BIOS_TYPE}${CPU_TYPE:+ $CPU_TYPE} \
  -cores "$CORE_COUNT" \
  -memory "$RAM_SIZE" \
  -name "$HN" \
  -tags "$VM_TAGS" \
  -net0 "virtio,bridge=$BRG,macaddr=$MAC$VLAN$MTU" \
  -ostype "$GUEST_OS_TYPE" \
  -scsihw virtio-scsi-pci \
  $( [[ -n "$SERIAL_PORT" ]] && echo "-serial0 $SERIAL_PORT" ) \
  >/dev/null 2>&1; then
  msg_error "$(translate "Failed to create base VM. Check VM ID and host configuration.")"
  return 1
fi

if [[ "$OS_TYPE" == "2" ]]; then
  qm set "$VMID" -tablet 1 >/dev/null 2>&1
fi

  msg_ok "$(translate "Base VM created with ID") $VMID"




if [[ "$BIOS_TYPE" == *"ovmf"* ]]; then
  msg_info "$(translate "Configuring EFI disk")"
  if ! EFI_STORAGE=$(select_storage_target "EFI" "$VMID"); then
    msg_error "$(translate "EFI storage selection failed or was cancelled. VM creation aborted.")"
    return 1
  fi
  STORAGE_TYPE=$(pvesm status -storage "$EFI_STORAGE" | awk 'NR>1 {print $2}')
  EFI_DISK_ID="efidisk0"
  EFI_KEYS="0"

  [[ "$OS_TYPE" == "2" ]] && EFI_KEYS="1"

  if [[ "$STORAGE_TYPE" == "btrfs" || "$STORAGE_TYPE" == "dir" || "$STORAGE_TYPE" == "nfs" ]]; then
 
    if qm set "$VMID" -$EFI_DISK_ID "$EFI_STORAGE:4,efitype=4m,format=raw,pre-enrolled-keys=$EFI_KEYS" >/dev/null 2>&1; then
      msg_ok "$(translate "EFI disk created and configured on") $EFI_STORAGE"
    else
      msg_error "$(translate "Failed to configure EFI disk")"
    fi
  else

    EFI_DISK_NAME="vm-${VMID}-disk-efivars"
    if pvesm alloc "$EFI_STORAGE" "$VMID" "$EFI_DISK_NAME" 4M >/dev/null 2>&1; then
      if qm set "$VMID" -$EFI_DISK_ID "$EFI_STORAGE:$EFI_DISK_NAME,pre-enrolled-keys=$EFI_KEYS" >/dev/null 2>&1; then
        msg_ok "$(translate "EFI disk created and configured on") $EFI_STORAGE"
      else
        msg_error "$(translate "Failed to configure EFI disk")"
      fi
    else
      msg_error "$(translate "Failed to create EFI disk")"
    fi
  fi
fi






if [[ "$OS_TYPE" == "2" ]]; then
  msg_info "$(translate "Configuring TPM device")"
  if ! TPM_STORAGE=$(select_storage_target "TPM" "$VMID"); then
    msg_error "$(translate "TPM storage selection failed or was cancelled. VM creation aborted.")"
    return 1
  fi
  STORAGE_TYPE=$(pvesm status -storage "$TPM_STORAGE" | awk 'NR>1 {print $2}')
  TPM_ID="tpmstate0"

  if [[ "$STORAGE_TYPE" == "btrfs" || "$STORAGE_TYPE" == "dir" || "$STORAGE_TYPE" == "nfs" ]]; then

    if qm set "$VMID" -$TPM_ID "$TPM_STORAGE:4,version=v2.0,format=raw" >/dev/null 2>&1; then
      msg_ok "$(translate "TPM device added to VM")"
    else
      msg_error "$(translate "Failed to configure TPM device in VM")"
    fi
  else

    TPM_NAME="vm-${VMID}-tpmstate"
    if pvesm alloc "$TPM_STORAGE" "$VMID" "$TPM_NAME" 4M >/dev/null 2>&1; then
      if qm set "$VMID" -$TPM_ID "$TPM_STORAGE:$TPM_NAME,size=4M,version=v2.0" >/dev/null 2>&1; then
        msg_ok "$(translate "TPM device added to VM")"
      else
        msg_error "$(translate "Failed to configure TPM device in VM")"
      fi
    else
      msg_error "$(translate "Failed to create TPM state disk")"
    fi
  fi
fi







# ==========================================================
# Create Disks / Import Disks / Controller + NVMe
# ==========================================================

  local -a EFFECTIVE_IMPORT_DISKS=()
  if [[ ${#IMPORT_DISKS[@]} -gt 0 ]]; then
    EFFECTIVE_IMPORT_DISKS=("${IMPORT_DISKS[@]}")
  elif [[ ${#PASSTHROUGH_DISKS[@]} -gt 0 ]]; then
    EFFECTIVE_IMPORT_DISKS=("${PASSTHROUGH_DISKS[@]}")
  fi

  if [[ ${#VIRTUAL_DISKS[@]} -gt 0 || ${#EFFECTIVE_IMPORT_DISKS[@]} -gt 0 ]]; then
    if ! select_interface_type; then
      msg_error "$(translate "Disk interface is required to continue VM creation.")"
      return 1
    fi
  fi

  local NEXT_DISK_SLOT=0

  if [[ ${#VIRTUAL_DISKS[@]} -gt 0 ]]; then
    for i in "${!VIRTUAL_DISKS[@]}"; do
      DISK_INDEX=$((NEXT_DISK_SLOT+1))
      IFS=':' read -r STORAGE SIZE <<< "${VIRTUAL_DISKS[$i]}"
      DISK_NAME="vm-${VMID}-disk-${DISK_INDEX}"
      SLOT_NAME="${INTERFACE_TYPE}${NEXT_DISK_SLOT}"

      STORAGE_TYPE=$(pvesm status -storage "$STORAGE" | awk 'NR>1 {print $2}')
      case "$STORAGE_TYPE" in
        dir|nfs|btrfs)
          DISK_EXT=".raw"
          DISK_REF="$VMID/"
          ;;
        *)
          DISK_EXT=""
          DISK_REF=""
          ;;
      esac

      if [[ "$STORAGE_TYPE" == "btrfs" || "$STORAGE_TYPE" == "dir" || "$STORAGE_TYPE" == "nfs" ]]; then
 
            if qm set "$VMID" -$SLOT_NAME "$STORAGE:${SIZE},format=raw${DISCARD_OPTS}" >/dev/null 2>&1; then
              msg_ok "$(translate "Virtual disk") $DISK_INDEX ${SIZE}GB - $STORAGE ($SLOT_NAME)"
              DISK_INFO+="<p>Virtual Disk $DISK_INDEX: ${SIZE}GB ($STORAGE / $SLOT_NAME)</p>"
              [[ -z "$BOOT_ORDER" ]] && BOOT_ORDER="$SLOT_NAME"
              NEXT_DISK_SLOT=$((NEXT_DISK_SLOT + 1))
            else
              msg_error "$(translate "Failed to assign virtual disk") $DISK_INDEX"
            fi
          else

            #DISK_NAME="vm-${VMID}-disk-${DISK_INDEX}"

            if pvesm alloc "$STORAGE" "$VMID" "$DISK_NAME$DISK_EXT" "$SIZE"G >/dev/null 2>&1; then
              qm set "$VMID" -$SLOT_NAME "$STORAGE:${DISK_REF}${DISK_NAME}${DISK_EXT}${DISCARD_OPTS}" >/dev/null
              msg_ok "$(translate "Virtual disk") $DISK_INDEX ${SIZE}GB - $STORAGE ($SLOT_NAME)"
              DISK_INFO+="<p>Virtual Disk $DISK_INDEX: ${SIZE}GB ($STORAGE / $SLOT_NAME)</p>"
              [[ -z "$BOOT_ORDER" ]] && BOOT_ORDER="$SLOT_NAME"
              NEXT_DISK_SLOT=$((NEXT_DISK_SLOT + 1))
            else
              msg_error "$(translate "Failed to create disk") $DISK_INDEX"
            fi
          fi
    done
  fi



  if [[ ${#EFFECTIVE_IMPORT_DISKS[@]} -gt 0 ]]; then
    for i in "${!EFFECTIVE_IMPORT_DISKS[@]}"; do
      SLOT_NAME="${INTERFACE_TYPE}${NEXT_DISK_SLOT}"
      DISK="${EFFECTIVE_IMPORT_DISKS[$i]}"
      MODEL=$(lsblk -ndo MODEL "$DISK")
      SIZE=$(lsblk -ndo SIZE "$DISK")
      qm set "$VMID" -$SLOT_NAME "$DISK${DISCARD_OPTS}" >/dev/null 2>&1
      msg_ok "$(translate "Import disk assigned") ($DISK → $SLOT_NAME)"
      DISK_INFO+="<p>Import Disk $((NEXT_DISK_SLOT+1)): $DISK ($MODEL $SIZE)</p>"
      [[ -z "$BOOT_ORDER" ]] && BOOT_ORDER="$SLOT_NAME"
      NEXT_DISK_SLOT=$((NEXT_DISK_SLOT + 1))
    done
  fi

  if [[ ${#CONTROLLER_NVME_PCIS[@]} -gt 0 ]]; then
    # SR-IOV guard: drop Virtual Functions / active-PFs before staging.
    # Proxmox's VFIO rebind via qm hostpci would trigger the same VF-tree
    # collapse described in the GPU flows, so we exclude them and tell
    # the user to manage those passthroughs manually.
    #
    # UI choice: this runs mid-flow (phase 2 of the wizard, interleaved
    # with msg_info/msg_ok output), so a whiptail msgbox is used to force
    # the user to acknowledge the exclusion instead of letting the notice
    # scroll by with the rest of the processing output. After the user
    # clicks OK, a per-device msg_warn is emitted so the skipped BDFs
    # remain visible in the captured log.
    if declare -F _pci_sriov_filter_array >/dev/null 2>&1; then
      local _sriov_removed=""
      _sriov_removed=$(_pci_sriov_filter_array CONTROLLER_NVME_PCIS)
      if [[ -n "$_sriov_removed" ]]; then
        local _sriov_msg="" _entry _bdf _role _first _sb
        local -a _sriov_bdfs=()
        local _nl=$'\n'
        _sriov_msg="$(translate "The following devices were excluded from Controller/NVMe passthrough because they are part of an SR-IOV configuration:")"
        while IFS= read -r _entry; do
          [[ -z "$_entry" ]] && continue
          _bdf="${_entry%%|*}"
          _role="${_entry#*|}"
          _first="${_role%% *}"
          _sriov_bdfs+=("$_bdf")
          if [[ "$_first" == "vf" ]]; then
            _sriov_msg+="${_nl}  •  ${_bdf}  — $(translate "Virtual Function")"
          else
            _sriov_msg+="${_nl}  •  ${_bdf}  — $(translate "Physical Function with") ${_role#pf-active } $(translate "active VFs")"
          fi
        done <<< "$_sriov_removed"
        _sriov_msg+="${_nl}${_nl}$(translate "To pass SR-IOV Virtual Functions to a VM, edit the VM configuration manually via the Proxmox web interface.")"

        whiptail --backtitle "ProxMenux" \
          --title "$(translate "SR-IOV Configuration Detected")" \
          --msgbox "$_sriov_msg" 18 82

        for _sb in "${_sriov_bdfs[@]}"; do
          msg_warn "$(translate "Skipping SR-IOV device"): ${_sb}"
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
        CONTROLLER_CAN_STAGE=false
      fi
    fi

    if [[ "$CONTROLLER_CAN_STAGE" != "true" ]]; then
      :
    elif ! _vm_is_q35 "$VMID"; then
      msg_error "$(translate "Controller + NVMe passthrough requires machine type q35. Skipping controller assignment.")"
    else
      local hostpci_idx=0
      if declare -F _pci_next_hostpci_index >/dev/null 2>&1; then
        hostpci_idx=$(_pci_next_hostpci_index "$VMID" 2>/dev/null || echo 0)
      else
        local hostpci_existing
        hostpci_existing=$(qm config "$VMID" 2>/dev/null)
        while grep -q "^hostpci${hostpci_idx}:" <<< "$hostpci_existing"; do
          hostpci_idx=$((hostpci_idx + 1))
        done
      fi

      local pci bdf
      for pci in "${CONTROLLER_NVME_PCIS[@]}"; do
        bdf="${pci#0000:}"
        if declare -F _pci_function_assigned_to_vm >/dev/null 2>&1; then
          if _pci_function_assigned_to_vm "$pci" "$VMID"; then
            msg_warn "$(translate "Controller/NVMe already present in VM config") ($pci)"
            continue
          fi
        elif qm config "$VMID" 2>/dev/null | grep -qE "^hostpci[0-9]+:.*(0000:)?${bdf}([,[:space:]]|$)"; then
          msg_warn "$(translate "Controller/NVMe already present in VM config") ($pci)"
          continue
        fi

        local -a source_vms=()
        mapfile -t source_vms < <(_pci_assigned_vm_ids "$pci" "$VMID" 2>/dev/null)
        if [[ ${#source_vms[@]} -gt 0 ]]; then
          local has_running=false vmid action slot_base
          for vmid in "${source_vms[@]}"; do
            if _vm_status_is_running "$vmid"; then
              has_running=true
              msg_warn "$(translate "Controller/NVMe is in use by running VM") ${vmid} ($(translate "stop source VM first"))"
            fi
          done
          if $has_running; then
            continue
          fi

          action=$(prompt_controller_conflict_policy "$pci" "${source_vms[@]}")
          case "$action" in
            keep_disable_onboot)
              for vmid in "${source_vms[@]}"; do
                if _vm_onboot_is_enabled "$vmid"; then
                  if qm set "$vmid" -onboot 0 >/dev/null 2>&1; then
                    msg_warn "$(translate "Start on boot disabled for VM") ${vmid}"
                  fi
                fi
              done
              ;;
            move_remove_source)
              slot_base=$(_pci_slot_base "$pci")
              for vmid in "${source_vms[@]}"; do
                if _remove_pci_slot_from_vm_config "$vmid" "$slot_base"; then
                  msg_ok "$(translate "Controller/NVMe removed from source VM") ${vmid} (${pci})"
                fi
              done
              ;;
            *)
              msg_info2 "$(translate "Skipped device"): ${pci}"
              continue
              ;;
          esac
        fi

        if qm set "$VMID" --hostpci${hostpci_idx} "${pci},pcie=1" >/dev/null 2>&1; then
          msg_ok "$(translate "Controller/NVMe assigned") (hostpci${hostpci_idx} → ${pci})"
          DISK_INFO+="<p>Controller/NVMe: ${pci}</p>"
          BOOT_ORDER="${BOOT_ORDER:+$BOOT_ORDER;}hostpci${hostpci_idx}"
          hostpci_idx=$((hostpci_idx + 1))
        else
          msg_error "$(translate "Failed to assign Controller/NVMe") (${pci})"
        fi
      done

    fi
  fi





  if [[ -n "${ISO_VOLID:-}" || -f "${ISO_PATH:-}" ]]; then
    mount_iso_to_vm "$VMID" "$ISO_PATH" "ide2" "${ISO_VOLID:-}"
  fi

  
  if [[ "$OS_TYPE" == "2" ]]; then
    local VIRTIO_DIR="/var/lib/vz/template/iso"
    local VIRTIO_SELECTED=""
    local VIRTIO_VOLID=""
    local VIRTIO_DOWNLOAD_URL="https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"

    while true; do
      VIRTIO_OPTION=$(whiptail --title "ProxMenux - VirtIO Drivers" --menu "$(translate "Select how to provide VirtIO drivers")" 15 70 2 \
        "1" "$(translate "Download latest VirtIO ISO automatically")" \
        "2" "$(translate "Use existing VirtIO ISO from storage")" 3>&1 1>&2 2>&3)

      [[ $? -ne 0 ]] && msg_warn "$(translate "VirtIO ISO selection cancelled.")" && break

      case "$VIRTIO_OPTION" in
        1)

          if [[ -f "$VIRTIO_DIR/virtio-win.iso" ]]; then
            if whiptail --title "ProxMenux" --yesno "$(translate "A VirtIO ISO already exists. Do you want to overwrite it?")" 10 60; then
              wget -q --show-progress -O "$VIRTIO_DIR/virtio-win.iso" "$VIRTIO_DOWNLOAD_URL"
              if [[ -f "$VIRTIO_DIR/virtio-win.iso" ]]; then
                msg_ok "$(translate "VirtIO driver ISO downloaded successfully.")"
              else
                msg_error "$(translate "Failed to download VirtIO driver ISO.")"
              fi
            fi
          else
            wget -q --show-progress -O "$VIRTIO_DIR/virtio-win.iso" "$VIRTIO_DOWNLOAD_URL"
            if [[ -f "$VIRTIO_DIR/virtio-win.iso" ]]; then
              msg_ok "$(translate "VirtIO driver ISO downloaded successfully.")"
            else
              msg_error "$(translate "Failed to download VirtIO driver ISO.")"
            fi
          fi

          VIRTIO_SELECTED="$VIRTIO_DIR/virtio-win.iso"
          VIRTIO_VOLID="local:iso/virtio-win.iso"
          ;;
        2)

          local virtio_volid
          VIRTIO_LIST=()
          while read -r virtio_volid; do
            [[ -z "$virtio_volid" ]] && continue
            VIRTIO_LIST+=("$virtio_volid" "$(iso_dialog_description "$virtio_volid")")
          done < <(iso_list_volids "virtio")

          if [[ ${#VIRTIO_LIST[@]} -eq 0 ]]; then
            msg_warn "$(translate "No VirtIO ISO found. Please download one.")"
            continue  
          fi

          VIRTIO_VOLID=$(whiptail --title "ProxMenux - VirtIO ISOs" --menu "$(translate "Select a VirtIO ISO to use:")\n\n$(printf '%-42s │ %-14s │ %s' "$(translate "ISO")" "$(translate "Storage")" "$(translate "Size")")" 22 86 12 "${VIRTIO_LIST[@]}" 3>&1 1>&2 2>&3)

          if [[ -n "$VIRTIO_VOLID" ]]; then
            VIRTIO_SELECTED=$(iso_volid_to_path "$VIRTIO_VOLID")
          else
            msg_warn "$(translate "No VirtIO ISO selected. Please choose again.")"
            continue
          fi
          ;;
      esac

      if [[ -n "$VIRTIO_VOLID" || -f "$VIRTIO_SELECTED" ]]; then
        mount_iso_to_vm "$VMID" "$VIRTIO_SELECTED" "ide3" "$VIRTIO_VOLID"
      else
        msg_warn "$(translate "VirtIO ISO not found after selection.")"
      fi

      break
    done
  fi


  local BOOT_FINAL=""
  if [[ -n "$BOOT_ORDER" ]]; then
    BOOT_FINAL="$BOOT_ORDER"
  fi
  if [[ -n "${ISO_VOLID:-}" || -f "${ISO_PATH:-}" ]]; then
    BOOT_FINAL="${BOOT_FINAL:+$BOOT_FINAL;}ide2"
  fi
  if [[ -n "$BOOT_FINAL" ]]; then
    qm set "$VMID" -boot order="$BOOT_FINAL" >/dev/null
    msg_ok "$(translate "Boot order set to") $BOOT_FINAL"
  fi




  HTML_DESC="<div align='center'>
<table style='width: 100%; border-collapse: collapse;'>
<tr>
<td style='width: 100px; vertical-align: middle;'>
<img src='https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo_desc.png' alt='ProxMenux Logo' style='height: 100px;'>
</td>
<td style='vertical-align: middle;'>
<h1 style='margin: 0;'>$HN VM</h1>
<p style='margin: 0;'>Created with ProxMenux</p>
</td>
</tr>
</table>

<p>
<a href='https://macrimi.github.io/ProxMenux/docs/create-vm' target='_blank'><img src='https://img.shields.io/badge/📚_Docs-blue' alt='Docs'></a>
<a href='https://github.com/MacRimi/ProxMenux/blob/main/scripts/menus/create_vm_menu.sh' target='_blank'><img src='https://img.shields.io/badge/💻_Code-green' alt='Code'></a>
<a href='https://ko-fi.com/macrimi' target='_blank'><img src='https://img.shields.io/badge/☕_Ko--fi-red' alt='Ko-fi'></a>
</p>

<div>
${DISK_INFO}
</div>
</div>"

msg_info "$(translate "Setting VM description")"
if ! qm set "$VMID" -description "$HTML_DESC" >/dev/null 2>&1; then
    msg_error "$(translate "Failed to set VM description")"
else
    msg_ok "$(translate "VM description configured")"
fi

  if [[ "${WIZARD_ADD_GPU:-no}" == "yes" && "$START_VM" == "yes" ]]; then
    msg_warn "$(translate "Auto-start was skipped because GPU passthrough setup was requested.")"
    msg_warn "$(translate "After completing GPU setup, start the VM manually when the host is ready.")"
    START_VM="no"
  fi


  if [[ "$START_VM" == "yes" ]]; then
    qm start "$VMID"
    msg_ok "$(translate "VM started")"
  fi
  configure_guest_agent

if [[ "${WIZARD_ADD_GPU:-no}" == "yes" ]]; then
  WIZARD_GPU_RESULT="cancelled"
  run_gpu_passthrough_wizard
  local GPU_WIZARD_APPLIED="no"
  local GPU_WIZARD_REBOOT_REQUIRED="no"
  case "$WIZARD_GPU_RESULT" in
    applied)
      GPU_WIZARD_APPLIED="yes"
      ;;
    applied_reboot_required)
      GPU_WIZARD_APPLIED="yes"
      GPU_WIZARD_REBOOT_REQUIRED="yes"
      ;;
  esac
  if [[ "${VM_WIZARD_CAPTURE_ACTIVE:-0}" -eq 1 ]]; then
    stop_spinner
    exec 1>&8
    exec 8>&-
    VM_WIZARD_CAPTURE_ACTIVE=0
    show_proxmenux_logo
    cat "$VM_WIZARD_CAPTURE_FILE"
    rm -f "$VM_WIZARD_CAPTURE_FILE"
    VM_WIZARD_CAPTURE_FILE=""
  fi
  if [[ "$GPU_WIZARD_APPLIED" == "yes" ]]; then
    msg_success "$(translate "VM creation completed with GPU passthrough configured.")"
    if [[ "$GPU_WIZARD_REBOOT_REQUIRED" == "yes" ]]; then
      msg_warn "$(translate "Host VFIO configuration changed (initramfs updated). Reboot required before starting the VM.")"
    fi
  elif [[ "$WIZARD_GPU_RESULT" == "no_gpu" ]]; then
    msg_success "$(translate "VM creation completed. GPU passthrough was skipped (no compatible GPU detected).")"
  else
    msg_success "$(translate "VM creation completed. GPU passthrough was not applied.")"
  fi
  if [[ "$OS_TYPE" == "2" ]]; then
    echo -e "${TAB}$(translate "Next Steps:")"
    echo -e "${TAB}1. $(translate "Start the VM to begin Windows installation from the mounted ISO.")"
    echo -e "${TAB}2. $(translate "When asked to select a disk, click Load Driver and load the VirtIO drivers.")"
    echo -e "${TAB}   $(translate "Required if using a VirtIO or SCSI disk.")"
    echo -e "${TAB}3. $(translate "Also install the VirtIO network driver during setup to enable network access.")"
    echo -e "${TAB}4. $(translate "Continue the Windows installation as usual.")"
    echo -e "${TAB}5. $(translate "Once installed, open the VirtIO ISO and run the installer to complete driver setup.")"
    echo -e "${TAB}6. $(translate "Reboot the VM to complete the driver installation.")"
    if [[ "$GPU_WIZARD_APPLIED" == "yes" ]]; then
      echo -e "${TAB}- $(translate "If you want to use a physical monitor on the passthrough GPU:")"
      echo -e "${TAB}• $(translate "First install the GPU drivers inside the guest and verify remote access (RDP/SSH).")"
      echo -e "${TAB}• $(translate "Then change the VM display to none (vga: none) when the guest is stable.")"
      echo -e "${TAB}• $(translate "If passthrough fails on Windows: install RadeonResetBugFix.")"
    fi
    echo -e
  elif [[ "$OS_TYPE" == "3" ]]; then
    echo -e "${TAB}${GN}$(translate "Recommended: Install the QEMU Guest Agent in the VM")${CL}"
    echo -e "${TAB}$(translate "Run the following inside the VM:")"
    echo -e "${TAB}apt install qemu-guest-agent -y && systemctl enable --now qemu-guest-agent"
    if [[ "$GPU_WIZARD_APPLIED" == "yes" ]]; then
      echo -e "${TAB}- $(translate "If you want to use a physical monitor on the passthrough GPU:")"
      echo -e "${TAB}• $(translate "First install the GPU drivers inside the guest and verify remote access (RDP/SSH).")"
      echo -e "${TAB}• $(translate "Then change the VM display to none (vga: none) when the guest is stable.")"
    fi
    echo -e
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
  msg_success "$(translate "Press Enter to return to the main menu...")"
  read -r
  bash "$LOCAL_SCRIPTS/menus/create_vm_menu.sh"
  exit 0
fi

msg_success "$(translate "VM creation completed")"
if [[ "$OS_TYPE" == "2" ]]; then
  echo -e "${TAB}$(translate "Next Steps:")"
  echo -e "${TAB}1. $(translate "Start the VM to begin Windows installation from the mounted ISO.")"
  echo -e "${TAB}2. $(translate "When asked to select a disk, click Load Driver and load the VirtIO drivers.")"
  echo -e "${TAB}   $(translate "Required if using a VirtIO or SCSI disk.")"
  echo -e "${TAB}3. $(translate "Also install the VirtIO network driver during setup to enable network access.")"
  echo -e "${TAB}4. $(translate "Continue the Windows installation as usual.")"
  echo -e "${TAB}5. $(translate "Once installed, open the VirtIO ISO and run the installer to complete driver setup.")"
  echo -e "${TAB}6. $(translate "Reboot the VM to complete the driver installation.")"
  echo -e
elif [[ "$OS_TYPE" == "3" ]]; then
  echo -e "${TAB}${GN}$(translate "Recommended: Install the QEMU Guest Agent in the VM")${CL}"
  echo -e "${TAB}$(translate "Run the following inside the VM:")"
  echo -e "${TAB}apt install qemu-guest-agent -y && systemctl enable --now qemu-guest-agent"
  echo -e
fi

msg_success "$(translate "Press Enter to return to the main menu...")"
read -r
bash "$LOCAL_SCRIPTS/menus/create_vm_menu.sh"
exit 0

}
