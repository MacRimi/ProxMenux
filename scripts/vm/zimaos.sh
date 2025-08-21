#!/usr/bin/env bash

# ==========================================================
# ProxMenuX - ZimaOS VM Creator Script
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 21/08/2025
# ==========================================================
# Description:
# This script automates the creation and configuration of a ZimaOS 
# Virtual machine (VM) in Proxmox VE. It simplifies the
# setup process by allowing both default and advanced configuration options.
#
# The script automates the complete VM creation process, including loader 
# download, disk configuration, and VM boot setup.
#
#
# ==========================================================


# Configuration ============================================
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

GEN_MAC="02"
for i in {1..5}; do
  BYTE=$(printf "%02X" $((RANDOM % 256)))
  GEN_MAC="${GEN_MAC}:${BYTE}"
done

NEXTID=$(pvesh get /cluster/nextid 2>/dev/null || echo "100")
NAME="ZimaOS VM"
IMAGES_DIR="/var/lib/vz/template/iso"
ERROR_FLAG=false





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
  show_proxmenux_logo
  echo -e "${BL}╔═══════════════════════════════════════════════╗${CL}"
  echo -e "${BL}║                                               ║${CL}"
  echo -e "${BL}║${YWB}                ZimaOS VM Creator              ${BL}║${CL}"
  echo -e "${BL}║                                               ║${CL}"
  echo -e "${BL}╚═══════════════════════════════════════════════╝${CL}"
  echo -e
}
# ==========================================================






# ==========================================================
# start Script
# ==========================================================
function start_script() {
  if (whiptail --backtitle "ProxMenuX" --title "SETTINGS" --yesno "$(translate  "Use Default Settings?")" --no-button Advanced 10 58); then
    header_info
    echo -e "${DEF}Using Default Settings${CL}"
    default_settings
  else
    header_info
    echo -e "${CUS}Using Advanced Settings${CL}"
    advanced_settings
  fi
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
  HN="ZimaOS"
  CPU_TYPE=" -cpu host"
  CORE_COUNT="2"
  RAM_SIZE="4096"
  BRG="vmbr0"
  MAC="$GEN_MAC"
  VLAN=""
  MTU=""
  SERIAL_PORT="socket"
  START_VM="no"
  INTERFACE_TYPE="scsi"
  DISCARD_OPTS=",discard=on,ssd=on"
  
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
  echo -e " ${TAB}${DGN}Disk Interface Type: ${BGN}${INTERFACE_TYPE}${CL}"
  echo -e
  echo -e "${DEF}Creating a $NAME using the above default settings${CL}"
 
  sleep 1
  select_disk_type
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
  if VM_NAME=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "Set Hostname")" 8 58 ZimaOS --title "HOSTNAME" --cancel-button Exit-Script 3>&1 1>&2 2>&3); then
    if [ -z $VM_NAME ]; then
      HN="ZimaOS"
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




  # Select Interface Type
  INTERFACE_TYPE=$(whiptail --backtitle "ProxMenuX" --title "$(translate "Select Disk Interface")" --radiolist \
    "$(translate "Select the bus type for the disks:")" 15 70 4 \
    "scsi"    "$(translate "SCSI   (recommended for Linux)")" ON \
    "sata"    "$(translate "SATA   (standard - high compatibility)")" OFF \
    "virtio"  "$(translate "VirtIO (advanced - high performance)")" OFF \
    3>&1 1>&2 2>&3) || exit 1

  case "$INTERFACE_TYPE" in
    "scsi"|"sata")
      DISCARD_OPTS=",discard=on,ssd=on"
      ;;
    "virtio")
      DISCARD_OPTS=",discard=on"
      ;;
  esac

  msg_ok "$(translate "Disk interface selected:") $INTERFACE_TYPE"


  # Confirmation
  if (whiptail --backtitle "ProxMenuX" --title "$(translate "ADVANCED SETTINGS COMPLETE")" --yesno "Ready to create a $NAME?" --no-button Do-Over 10 58); then
    echo -e
    echo -e "${CUS}Creating a $NAME using the above advanced settings${CL}"
    sleep 1
    select_disk_type
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
function select_disk_type() {

  DISK_TYPE=$(whiptail --backtitle "ProxMenuX" --title "DISK TYPE" --menu "$(translate "Choose disk type:")" 12 58 2 \
    "virtual" "$(translate "Create virtual disk")" \
    "passthrough" "$(translate "Use physical disk passthrough")" \
    --ok-button "Select" --cancel-button "Cancel" 3>&1 1>&2 2>&3)

  EXIT_STATUS=$?

  if [[ $EXIT_STATUS -ne 0 ]]; then
      clear
      header_info
      msg_error "Operation cancelled by user. Returning to start script..."
      sleep 2
      if whiptail --backtitle "ProxMenuX" --title "$NAME" --yesno "$(translate "This will create a New $NAME. Proceed?")" 10 58; then
        start_script
      else
        clear
        exit
      fi
  fi

  if [[ "$DISK_TYPE" == "virtual" ]]; then
      select_virtual_disk
  else
      select_passthrough_disk
  fi
}

# ==========================================================





# ==========================================================
# Select Virtual Disks
# ==========================================================
function select_virtual_disk() {

  VIRTUAL_DISKS=()      

  # Loop to add multiple disks
  local add_more_disks=true
  while $add_more_disks; do

  msg_info "Detecting available storage volumes..."

    # Get list of available storage
    STORAGE_MENU=()
    while read -r line; do
      TAG=$(echo $line | awk '{print $1}')
      TYPE=$(echo $line | awk '{print $2}')
      FREE=$(echo $line | numfmt --field 4-6 --from-unit=K --to=iec --format "%.2f" | awk '{printf( "%9sB", $6)}')
      ITEM=$(printf "%-15s %-10s %-15s" "$TAG" "$TYPE" "$FREE")
      STORAGE_MENU+=("$TAG" "$ITEM" "OFF")
    done < <(pvesm status -content images | awk 'NR>1')

    # Check that storage is available
    VALID=$(pvesm status -content images | awk 'NR>1')
    if [ -z "$VALID" ]; then
      msg_error "Unable to detect a valid storage location."
      sleep 2
      select_disk_type
    fi

    
    # Select storage
    if [ $((${#STORAGE_MENU[@]} / 3)) -eq 1 ]; then
      STORAGE=${STORAGE_MENU[0]}
      msg_ok "Using ${CL}${BL}$STORAGE${CL} ${GN}for Storage Location."
    else

      kill $SPINNER_PID > /dev/null
      STORAGE=$(whiptail --backtitle "ProxMenuX" --title "$(translate "Select Storage Volume")" --radiolist \
        "$(translate  "Choose the storage volume for the virtual disk:\n")" 20 78 10 \
        "${STORAGE_MENU[@]}" 3>&1 1>&2 2>&3)
      
      if [ $? -ne 0 ] || [ -z "$STORAGE" ]; then
        if [ ${#VIRTUAL_DISKS[@]} -eq 0 ]; then
          msg_error "No storage selected. At least one disk is required."
          select_disk_type
        else
          add_more_disks=false
          continue
        fi
      fi
      

    fi

    # Request disk size
    DISK_SIZE=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "System Disk Size (GB)")" 8 58 64 --title "VIRTUAL DISK" --cancel-button Cancel 3>&1 1>&2 2>&3)
    
    if [ $? -ne 0 ]; then
      if [ ${#VIRTUAL_DISKS[@]} -eq 0 ]; then
        msg_error "Disk size not specified. At least one disk is required."
        sleep 2
        select_disk_type
        
      else
        add_more_disks=false
        continue
      fi
    fi
    
    if [ -z "$DISK_SIZE" ]; then
      DISK_SIZE="64"
    fi

    # Store the configuration in the disk list
    VIRTUAL_DISKS+=("${STORAGE}:${DISK_SIZE}")


    # Ask if you want to create another disk
    if ! whiptail --backtitle "ProxMenuX" --title "$(translate "Add Another Disk")" \
      --yesno "$(translate "Do you want to add another virtual disk?")" 8 58; then
      add_more_disks=false
    fi
  done

  # Show summary of the created disks
  if [ ${#VIRTUAL_DISKS[@]} -gt 0 ]; then

    msg_ok "Virtual Disks Created:"
    for i in "${!VIRTUAL_DISKS[@]}"; do
      echo -e "${TAB}${BL}- Disk $((i+1)): ${VIRTUAL_DISKS[$i]}GB${CL}"
    done
  fi


  export VIRTUAL_DISKS


  select_loader
}

# ==========================================================






# ==========================================================
# Select Physical Disks
# ==========================================================
function select_passthrough_disk() {

  msg_info "$(translate "Detecting available disks...")"

  FREE_DISKS=()

  USED_DISKS=$(lsblk -n -o PKNAME,TYPE | grep 'lvm' | awk '{print "/dev/" $1}')
  MOUNTED_DISKS=$(lsblk -ln -o NAME,MOUNTPOINT | awk '$2!="" {print "/dev/" $1}')

  ZFS_DISKS=""
  ZFS_RAW=$(zpool list -v -H 2>/dev/null | awk '{print $1}' | grep -v '^NAME$' | grep -v '^-' | grep -v '^mirror')

  for entry in $ZFS_RAW; do
      path=""
      if [[ "$entry" == wwn-* || "$entry" == ata-* ]]; then
          if [ -e "/dev/disk/by-id/$entry" ]; then
              path=$(readlink -f "/dev/disk/by-id/$entry")
          fi
      elif [[ "$entry" == /dev/* ]]; then
          path="$entry"
      fi

      if [ -n "$path" ]; then
          base_disk=$(lsblk -no PKNAME "$path" 2>/dev/null)
          if [ -n "$base_disk" ]; then
              ZFS_DISKS+="/dev/$base_disk"$'\n'
          fi
      fi
  done

  ZFS_DISKS=$(echo "$ZFS_DISKS" | sort -u)
  LVM_DEVICES=$(pvs --noheadings -o pv_name 2> >(grep -v 'File descriptor .* leaked') | xargs -n1 readlink -f | sort -u)

  RAID_ACTIVE=$(grep -Po 'md\d+\s*:\s*active\s+raid[0-9]+' /proc/mdstat | awk '{print $1}' | sort -u)

  while read -r DISK; do
      [[ "$DISK" =~ /dev/zd ]] && continue

      INFO=($(lsblk -dn -o MODEL,SIZE "$DISK"))
      MODEL="${INFO[@]::${#INFO[@]}-1}"
      SIZE="${INFO[-1]}"
      LABEL=""
      SHOW_DISK=true

      IS_MOUNTED=false
      IS_RAID=false
      IS_ZFS=false
      IS_LVM=false

      while read -r part fstype; do
          [[ "$fstype" == "zfs_member" ]] && IS_ZFS=true
          [[ "$fstype" == "linux_raid_member" ]] && IS_RAID=true
          [[ "$fstype" == "LVM2_member" ]] && IS_LVM=true
          if grep -q "/dev/$part" <<< "$MOUNTED_DISKS"; then
              IS_MOUNTED=true
          fi
      done < <(lsblk -ln -o NAME,FSTYPE "$DISK" | tail -n +2)

      REAL_PATH=$(readlink -f "$DISK")
      if echo "$LVM_DEVICES" | grep -qFx "$REAL_PATH"; then
          IS_MOUNTED=true
      fi

      USED_BY=""
      REAL_PATH=$(readlink -f "$DISK")
      CONFIG_DATA=$(cat /etc/pve/qemu-server/*.conf /etc/pve/lxc/*.conf 2>/dev/null)

      if grep -Fq "$REAL_PATH" <<< "$CONFIG_DATA"; then
          USED_BY="⚠ $(translate "In use")"
      else
          for SYMLINK in /dev/disk/by-id/*; do
              if [[ "$(readlink -f "$SYMLINK")" == "$REAL_PATH" ]]; then
                  if grep -Fq "$SYMLINK" <<< "$CONFIG_DATA"; then
                      USED_BY="⚠ $(translate "In use")"
                      break
                  fi
              fi
          done
      fi

      if $IS_RAID && grep -q "$DISK" <<< "$(cat /proc/mdstat)" && grep -q "active raid" /proc/mdstat; then
          SHOW_DISK=false
      fi

      if $IS_ZFS || $IS_MOUNTED || [[ "$ZFS_DISKS" == *"$DISK"* ]]; then
          SHOW_DISK=false
      fi

      if $SHOW_DISK; then
        [[ -n "$USED_BY" ]] && LABEL+=" [$USED_BY]"
        [[ "$IS_RAID" == true ]] && LABEL+=" ⚠ RAID"
        [[ "$IS_LVM" == true ]] && LABEL+=" ⚠ LVM"
        [[ "$IS_ZFS" == true ]] && LABEL+=" ⚠ ZFS"
          DESCRIPTION=$(printf "%-30s %10s%s" "$MODEL" "$SIZE" "$LABEL")
          FREE_DISKS+=("$DISK" "$DESCRIPTION" "OFF")
      fi
  done < <(lsblk -dn -e 7,11 -o PATH)


  if [ "${#FREE_DISKS[@]}" -eq 0 ]; then
    cleanup
    whiptail --title "Error" --msgbox "$(translate "No disks available for this VM.")" 8 40
    select_disk_type
    return
  fi

  MAX_WIDTH=$(printf "%s\n" "${FREE_DISKS[@]}" | awk '{print length}' | sort -nr | head -n1)
  TOTAL_WIDTH=$((MAX_WIDTH + 20)) 
  [ $TOTAL_WIDTH -lt 50 ] && TOTAL_WIDTH=50
  cleanup
  SELECTED_DISKS=$(whiptail --title "Select Disks" --checklist \
    "$(translate "Select the disks you want to use (use spacebar to select):")" 20 $TOTAL_WIDTH 10 \
    "${FREE_DISKS[@]}" 3>&1 1>&2 2>&3)

  if [ -z "$SELECTED_DISKS" ]; then
    msg_error "Disk not specified. At least one disk is required."
    sleep 2
    select_disk_type
    return
  fi


  msg_ok "Disk passthrough selected:"
  PASSTHROUGH_DISKS=()
  for DISK in $(echo "$SELECTED_DISKS" | tr -d '"'); do
    DISK_INFO=$(lsblk -ndo MODEL,SIZE "$DISK" | xargs)
    echo -e "${TAB}${CL}${BL}- $DISK $DISK_INFO${GN}${CL}"
    PASSTHROUGH_DISKS+=("$DISK")
  done

  
  select_loader
}
# ==========================================================






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

  # Create the loader selection menu for ZimaOS
  LOADER_OPTION=$(whiptail --backtitle "ProxMenuX" --title "SELECT ZIMAOS IMAGE" --menu "$(translate "Choose ZimaOS image option:")" 15 70 4 \
    "1" "Download Latest ZimaOS Release" \
    "2" "Use Existing ZimaOS Image" \
    3>&1 1>&2 2>&3)

  if [ -z "$LOADER_OPTION" ]; then
    exit_script
  fi

  case $LOADER_OPTION in
    1)
      LOADER_TYPE="latest"
      LOADER_NAME="ZimaOS Latest"
      LOADER_URL="https://github.com/IceWhaleTech/ZimaOS/"
      echo -e "${DGN}${TAB}Selected: ${BGN}$LOADER_NAME${CL}"
      download_loader
      ;;
    2)
      LOADER_TYPE="existing"
      LOADER_NAME="ZimaOS"
      LOADER_URL="https://github.com/IceWhaleTech/ZimaOS/"
      echo -e "${DGN}${TAB}Selected: ${BGN}$LOADER_NAME${CL}"
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
  LOADER_FILE=$(whiptail --backtitle "ProxMenuX" --title "SELECT ZimaOS IMAGE" --menu "$(translate "Choose a ZimaOS image:")" 20 70 10 "${IMAGE_OPTIONS[@]}" 3>&1 1>&2 2>&3)
  
  if [ -z "$LOADER_FILE" ]; then
    msg_error "No ZimaOS image selected"
    exit_script
  fi
  
  echo -e "${DGN}${TAB}Using ZimaOS Image: ${BGN}$(basename "$LOADER_FILE")${CL}"
  FILE=$(basename "$LOADER_FILE")
}

function download_loader() {
  echo -e "${DGN}${TAB}Retrieving ZimaOS image${CL}"

  case $LOADER_TYPE in
    latest)
      
      # Get the latest release download URL
      DOWNLOAD_URL=$(curl -s https://api.github.com/repos/IceWhaleTech/ZimaOS/releases/latest \
        | grep "browser_download_url.*\.img" \
        | cut -d '"' -f 4 \
        | head -1)
      
      if [ -z "$DOWNLOAD_URL" ]; then
        msg_error "Failed to get latest ZimaOS release URL"
        sleep 2
        select_loader
        return
      fi
      
      # Extract filename from URL
      FILE=$(basename "$DOWNLOAD_URL")
      LOADER_FILE="$IMAGES_DIR/$FILE"
      
      # Check if file already exists
      if [ -f "$LOADER_FILE" ]; then
        if whiptail --backtitle "ProxMenuX" --title "FILE EXISTS" --yesno "$(translate "ZimaOS image already exists: $FILE\n\nDo you want to re-download it?")" 10 70; then
          rm -f "$LOADER_FILE"
        else
          echo -e "${DGN}${TAB}Using existing file: ${BGN}$FILE${CL}"
          return
        fi
      fi
      
      if wget -q --show-progress -O "$LOADER_FILE" "$DOWNLOAD_URL"; then
        msg_ok "Downloaded ZimaOS image successfully: $FILE"
      else
        msg_error "Failed to download ZimaOS image"
        rm -f "$LOADER_FILE"
        sleep 2
        select_loader
        return
      fi
      ;;
  esac
  
  # Verify the downloaded file
  if [ -f "$LOADER_FILE" ] && [ -s "$LOADER_FILE" ]; then
    echo -e "${DGN}${TAB}ZimaOS Image: ${BGN}$FILE${CL}"
    echo -e "${DGN}${TAB}File Size: ${BGN}$(du -h "$LOADER_FILE" | cut -f1)${CL}"
  else
    msg_error "Downloaded file is empty or corrupted"
    rm -f "$LOADER_FILE"
    sleep 2
    select_loader
  fi
}

# ==========================================================





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
    msg_error "Unable to detect a valid storage location for EFI disk."

  elif [ $((${#STORAGE_MENU[@]} / 3)) -eq 1 ]; then
    STORAGE=${STORAGE_MENU[0]}

  else
    kill $SPINNER_PID > /dev/null
    while [ -z "${STORAGE:+x}" ]; do
      STORAGE=$(whiptail --backtitle "ProxMenuX" --title "EFI Disk Storage" --radiolist \
        "$(translate "Choose the storage volume for the EFI disk (4MB):\n\nUse Spacebar to select.")" \
        16 $(($MSG_MAX_LENGTH + 23)) 6 \
        "${STORAGE_MENU[@]}" 3>&1 1>&2 2>&3) || exit 

    done

  fi
  
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
    msg_error "Unable to detect a valid storage location."
    exit 1
  elif [ $((${#STORAGE_MENU[@]} / 3)) -eq 1 ]; then
    STORAGE=${STORAGE_MENU[0]}
  else
    while [ -z "${STORAGE:+x}" ]; do
      STORAGE=$(whiptail --backtitle "ProxMenuX" --title "Storage Pools" --radiolist \
        "$(translate "Choose the storage volume for $purpose:\n\nUse Spacebar to select.")" \
        16 $(($MSG_MAX_LENGTH + 23)) 6 \
        "${STORAGE_MENU[@]}" 3>&1 1>&2 2>&3) || exit
    done
  fi
  
  echo "$STORAGE"
}





# ==========================================================
# Create VM
# ==========================================================
function create_vm() {

  # Create the VM
  qm create $VMID -agent 1${MACHINE} -tablet 0 -localtime 1${BIOS_TYPE}${CPU_TYPE} -cores $CORE_COUNT -memory $RAM_SIZE \
    -name $HN -tags proxmenux -net0 virtio,bridge=$BRG,macaddr=$MAC$VLAN$MTU -onboot 1 -ostype l26 -scsihw virtio-scsi-pci \
    -serial0 socket
  msg_ok "Create a $NAME"

  BOOT_ORDER_LIST=()  # Array to store boot order for all disks

  # Check if UEFI (OVMF) is being used ===================
  if [[ "$BIOS_TYPE" == *"ovmf"* ]]; then

    msg_info "Configuring EFI disk"
    EFI_STORAGE=$(select_efi_storage $VMID)
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

# Select storage volume for loader =======================
    LOADER_STORAGE=$(select_storage_volume $VMID "loader disk")
      
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
            else
                msg_error "Failed to assign loader disk"
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

    if [ "$DISK_TYPE" = "virtual" ]; then
        if [ ${#VIRTUAL_DISKS[@]} -eq 0 ]; then
            msg_error "No virtual disks configured."
            exit_script
        fi

        DISK_INFO=""
        CONSOLE_DISK_INFO=""

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
            
            DISK_NUM=$((i+1))
            DISK_NAME="vm-${VMID}-disk-${DISK_NUM}${DISK_EXT}"
            INTERFACE_ID="${INTERFACE_TYPE}$i"
            
            # Create virtual disk
            if [[ "$STORAGE_TYPE" == "btrfs" || "$STORAGE_TYPE" == "dir" || "$STORAGE_TYPE" == "nfs" ]]; then
            
              msg_info "Creating virtual disk (format=raw) for $STORAGE_TYPE..."
              if ! qm set "$VMID" -$INTERFACE_ID "$STORAGE:$SIZE,format=raw$DISCARD_OPTS" >/dev/null 2>&1; then
                msg_error "Failed to assign disk $DISK_NUM ($INTERFACE_ID) on $STORAGE"
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
              if ! qm set "$VMID" -$INTERFACE_ID "$STORAGE:${DISK_REF}$DISK_NAME$DISCARD_OPTS" >/dev/null 2>&1; then
                msg_error "Failed to configure virtual disk as $INTERFACE_ID"
                ERROR_FLAG=true
                continue
              fi
            fi

            msg_ok "Configured virtual disk as $INTERFACE_ID, ${SIZE}GB on ${CL}${BL}$STORAGE${CL} ${GN}"

            BOOT_ORDER_LIST+=("$INTERFACE_ID")
            
            # Add information to the description
            DISK_INFO="${DISK_INFO}<p>Virtual Disk $DISK_NUM: ${SIZE}GB on ${STORAGE} (${INTERFACE_TYPE}${i})</p>"
            CONSOLE_DISK_INFO="${CONSOLE_DISK_INFO}- Virtual Disk $DISK_NUM: ${SIZE}GB on ${STORAGE} ($INTERFACE_ID)\n"
        done


    # HTML description
HTML_DESC="<div align='center'>
<table style='width: 100%; border-collapse: collapse;'>
<tr>
<td style='width: 100px; vertical-align: middle;'>
<img src='https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo_desc.png' alt='ProxMenux Logo' style='height: 100px;'>
</td>
<td style='vertical-align: middle;'>
<h1 style='margin: 0;'>ZimaOS VM</h1>
<p style='margin: 0;'>Created with ProxMenuX</p>
<p style='margin: 0;'>$LOADER_NAME</p>
</td>
</tr>
</table>

<p>
<a href='https://macrimi.github.io/ProxMenux/' target='_blank'><img src='https://img.shields.io/badge/📚_Docs-blue' alt='Docs'></a>
<a href='https://raw.githubusercontent.com/MacRimi/ProxMenux/refs/heads/main/scripts/vm/zimaos.sh' target='_blank'><img src='https://img.shields.io/badge/💻_Code-green' alt='Code'></a>
<a href='$LOADER_URL' target='_blank'><img src='https://img.shields.io/badge/📦_Installer-orange' alt='Loader'></a>
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



    elif [ "$DISK_TYPE" = "passthrough" ]; then
        if [ ${#PASSTHROUGH_DISKS[@]} -eq 0 ]; then
            msg_error "No passthrough disks configured."
            exit_script
        fi

        DISK_INFO=""
        CONSOLE_DISK_INFO=""

        for i in "${!PASSTHROUGH_DISKS[@]}"; do
            DISK="${PASSTHROUGH_DISKS[$i]}"
            INTERFACE_ID="${INTERFACE_TYPE}$i"
            
            # Get disk information
            MODEL=$(lsblk -ndo MODEL "$DISK" 2>/dev/null || echo "Unknown")
            SIZE=$(lsblk -ndo SIZE "$DISK" 2>/dev/null || echo "Unknown")
            
            # Configure passthrough disk
            if qm set "$VMID" -$INTERFACE_ID "$DISK$DISCARD_OPTS" >/dev/null 2>&1; then
                msg_ok "Configured passthrough disk as $INTERFACE_ID: $DISK ($MODEL $SIZE)"
                BOOT_ORDER_LIST+=("$INTERFACE_ID")
                
                # Add information to the description
                DISK_INFO="${DISK_INFO}<p>Passthrough Disk $((i+1)): $DISK ($MODEL $SIZE) (${INTERFACE_TYPE}${i})</p>"
                CONSOLE_DISK_INFO="${CONSOLE_DISK_INFO}- Passthrough Disk $((i+1)): $DISK ($MODEL $SIZE) ($INTERFACE_ID)\n"
            else
                msg_error "Failed to configure passthrough disk $DISK as $INTERFACE_ID"
                ERROR_FLAG=true
            fi
        done


      # HTML description
HTML_DESC="<div align='center'>
<table style='width: 100%; border-collapse: collapse;'>
<tr>
<td style='width: 100px; vertical-align: middle;'>
<img src='https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo_desc.png' alt='ProxMenux Logo' style='height: 100px;'>
</td>
<td style='vertical-align: middle;'>
<h1 style='margin: 0;'>ZimaOS VM</h1>
<p style='margin: 0;'>Created with ProxMenuX</p>
<p style='margin: 0;'$LOADER_NAME</p>
</td>
</tr>
</table>

<p>
<a href='https://macrimi.github.io/ProxMenux/' target='_blank'><img src='https://img.shields.io/badge/📚_Docs-blue' alt='Docs'></a>
<a href='https://raw.githubusercontent.com/MacRimi/ProxMenux/refs/heads/main/scripts/vm/zimaos.sh' target='_blank'><img src='https://img.shields.io/badge/💻_Code-green' alt='Code'></a>
<a href='$LOADER_URL' target='_blank'><img src='https://img.shields.io/badge/📦_Installer-orange' alt='Loader'></a>
<a href='https://ko-fi.com/macrimi' target='_blank'><img src='https://img.shields.io/badge/☕_Ko--fi-red' alt='Ko-fi'></a>
</p>

<div>
${DISK_INFO}
</div>
</div>"


      result=$(qm set $VMID -description "$HTML_DESC" 2>&1)
      if [[ $? -eq 0 ]]; then
         msg_ok "Configured VM description"
      fi


    fi





    if [ ${#BOOT_ORDER_LIST[@]} -gt 0 ]; then
        BOOT_ORDER_LIST+=("ide0")  # Add IDE installer as last boot option
        BOOT_ORDER_STRING=$(IFS=';'; echo "${BOOT_ORDER_LIST[*]}")
        
        if qm set "$VMID" -boot order="$BOOT_ORDER_STRING" >/dev/null 2>&1; then
            msg_ok "Boot order configured: $BOOT_ORDER_STRING"
        else
            msg_error "Failed to configure boot order"
            ERROR_FLAG=true
        fi
    fi

}

# ==========================================================


header_info
sleep 1


if whiptail --backtitle "ProxMenuX" --title "$NAME" --yesno "$(translate "This will create a New $NAME. Proceed?")" 10 58; then
  start_script
else
  clear
  exit
fi


create_vm

# ==========================================================
