#!/usr/bin/env bash

# ==========================================================
# ProxMenuX - Virtual Machine Creator Script
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
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
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi

load_language
initialize_cache

# ==========================================================
# Mont ISOs
# ==========================================================
function mount_iso_to_vm() {
  local vmid="$1"
  local iso_path="$2"
  local device="$3"

  if [[ -f "$iso_path" ]]; then
    local iso_basename
    iso_basename=$(basename "$iso_path")
    qm set "$vmid" -$device "local:iso/$iso_basename,media=cdrom" >/dev/null 2>&1
    msg_ok "$(translate "Mounted ISO on device") $device → $iso_basename"
  else
    msg_warn "$(translate "ISO not found to mount on device") $device"
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
    3>&1 1>&2 2>&3) || exit 1

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
    msg_error "$(translate "Unable to detect a valid storage location for $PURPOSE disk.")"
    exit 1
  elif [[ $((${#STORAGE_MENU[@]} / 3)) -eq 1 ]]; then
    STORAGE="${STORAGE_MENU[0]}"
  else
    kill $SPINNER_PID > /dev/null
    STORAGE=$(whiptail --backtitle "ProxMenux" --title "$(translate "$PURPOSE Disk Storage")" --radiolist \
      "$(translate "Choose the storage volume for the $PURPOSE disk (4MB):\n\nUse Spacebar to select.")" 16 70 6 \
      "${STORAGE_MENU[@]}" 3>&1 1>&2 2>&3) || exit 1
  fi

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
      msg_ok "$(translate "ISO image downloaded")"
    else
      msg_error "$(translate "Failed to download ISO image")"
      return
    fi
  fi

  if [[ "$OS_TYPE" == "2" ]]; then
	  GUEST_OS_TYPE="win10"
    else
	  GUEST_OS_TYPE="l26"
  fi



 # qm create "$VMID" -agent 1${MACHINE} -tablet 0 -localtime 1${BIOS_TYPE}${CPU_TYPE} \
 #   -cores "$CORE_COUNT" -memory "$RAM_SIZE" -name "$HN" -tags proxmenux \
 #   -net0 "virtio,bridge=$BRG,macaddr=$MAC$VLAN$MTU" -ostype "$GUEST_OS_TYPE" \
 #   -scsihw virtio-scsi-pci \
 #   $( [[ -n "$SERIAL_PORT" ]] && echo "-serial0 $SERIAL_PORT" ) >/dev/null 2>&1


qm create "$VMID" \
  -agent 1${MACHINE:+ $MACHINE} \
  -localtime 1${BIOS_TYPE:+ $BIOS_TYPE}${CPU_TYPE:+ $CPU_TYPE} \
  -cores "$CORE_COUNT" \
  -memory "$RAM_SIZE" \
  -name "$HN" \
  -tags proxmenux \
  -net0 "virtio,bridge=$BRG,macaddr=$MAC$VLAN$MTU" \
  -ostype "$GUEST_OS_TYPE" \
  -scsihw virtio-scsi-pci \
  $( [[ -n "$SERIAL_PORT" ]] && echo "-serial0 $SERIAL_PORT" ) \
  >/dev/null 2>&1

if [[ "$OS_TYPE" == "2" ]]; then
  qm set "$VMID" -tablet 1 >/dev/null 2>&1
fi

  msg_ok "$(translate "Base VM created with ID") $VMID"




if [[ "$BIOS_TYPE" == *"ovmf"* ]]; then
  msg_info "$(translate "Configuring EFI disk")"
  EFI_STORAGE=$(select_storage_target "EFI" "$VMID")
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
  TPM_STORAGE=$(select_storage_target "TPM" "$VMID")
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
# Create Diks
# ==========================================================


select_interface_type

  if [[ "$DISK_TYPE" == "virtual" && ${#VIRTUAL_DISKS[@]} -gt 0 ]]; then
    for i in "${!VIRTUAL_DISKS[@]}"; do
      DISK_INDEX=$((i+1))
      IFS=':' read -r STORAGE SIZE <<< "${VIRTUAL_DISKS[$i]}"
      DISK_NAME="vm-${VMID}-disk-${DISK_INDEX}"
      SLOT_NAME="${INTERFACE_TYPE}${i}"

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
            else
              msg_error "$(translate "Failed to create disk") $DISK_INDEX"
            fi
          fi
    done
  fi



  if [[ "$DISK_TYPE" == "passthrough" && ${#PASSTHROUGH_DISKS[@]} -gt 0 ]]; then
    for i in "${!PASSTHROUGH_DISKS[@]}"; do
      SLOT_NAME="${INTERFACE_TYPE}${i}"
      DISK="${PASSTHROUGH_DISKS[$i]}"
      MODEL=$(lsblk -ndo MODEL "$DISK")
      SIZE=$(lsblk -ndo SIZE "$DISK")
      qm set "$VMID" -$SLOT_NAME "$DISK${DISCARD_OPTS}" >/dev/null 2>&1
      msg_ok "$(translate "Passthrough disk assigned") ($DISK → $SLOT_NAME)"
      DISK_INFO+="<p>Passthrough Disk $((i+1)): $DISK ($MODEL $SIZE)</p>"
      [[ -z "$BOOT_ORDER" ]] && BOOT_ORDER="$SLOT_NAME"
    done
  fi





  if [[ -f "$ISO_PATH" ]]; then
    mount_iso_to_vm "$VMID" "$ISO_PATH" "ide2"
  fi

  
  if [[ "$OS_TYPE" == "2" ]]; then
    local VIRTIO_DIR="/var/lib/vz/template/iso"
    local VIRTIO_SELECTED=""
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
          ;;
        2)

          VIRTIO_LIST=()
          while read -r line; do
            FILENAME=$(basename "$line")
            SIZE=$(du -h "$line" | cut -f1)
            VIRTIO_LIST+=("$FILENAME" "$SIZE")
          done < <(find "$VIRTIO_DIR" -type f -iname "virtio*.iso" | sort)

          if [[ ${#VIRTIO_LIST[@]} -eq 0 ]]; then
            msg_warn "$(translate "No VirtIO ISO found. Please download one.")"
            continue  
          fi

          VIRTIO_FILE=$(whiptail --title "ProxMenux - VirtIO ISOs" --menu "$(translate "Select a VirtIO ISO to use:")" 20 70 10 "${VIRTIO_LIST[@]}" 3>&1 1>&2 2>&3)

          if [[ -n "$VIRTIO_FILE" ]]; then
            VIRTIO_SELECTED="$VIRTIO_DIR/$VIRTIO_FILE"
          else
            msg_warn "$(translate "No VirtIO ISO selected. Please choose again.")"
            continue
          fi
          ;;
      esac

      if [[ -n "$VIRTIO_SELECTED" && -f "$VIRTIO_SELECTED" ]]; then
        mount_iso_to_vm "$VMID" "$VIRTIO_SELECTED" "ide3"
      else
        msg_warn "$(translate "VirtIO ISO not found after selection.")"
      fi

      break
    done
  fi


  local BOOT_FINAL="$BOOT_ORDER"
  [[ -f "$ISO_PATH" ]] && BOOT_FINAL="$BOOT_ORDER;ide2"
  qm set "$VMID" -boot order="$BOOT_FINAL" >/dev/null
  msg_ok "$(translate "Boot order set to") $BOOT_FINAL"




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
<a href='https://macrimi.github.io/ProxMenux/docs/create-vm/synology' target='_blank'><img src='https://img.shields.io/badge/📚_Docs-blue' alt='Docs'></a>
<a href='https://github.com/MacRimi/ProxMenux/blob/main/scripts/vm/create_vm.sh' target='_blank'><img src='https://img.shields.io/badge/💻_Code-green' alt='Code'></a>
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


  if [[ "$START_VM" == "yes" ]]; then
    qm start "$VMID"
    msg_ok "$(translate "VM started")"
  fi
  configure_guest_agent
  msg_success "$(translate "VM creation completed")"

if [[ "$OS_TYPE" == "2" ]]; then
  echo -e "${TAB}${GN}$(translate "Next Steps:")${CL}"
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
  echo -e "${TAB}${CY}apt install qemu-guest-agent -y && systemctl enable --now qemu-guest-agent${CL}"
  echo -e
fi


msg_success "$(translate "Press Enter to return to the main menu...")"
read -r
bash <(curl -fsSL "$REPO_URL/scripts/menus/create_vm_menu.sh")
exit 0

}
