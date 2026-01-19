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

function select_disk_type() {
  DISK_TYPE=$(whiptail --backtitle "ProxMenux" --title "DISK TYPE" --menu "$(translate "Choose disk type:")" 12 58 2 \
    "virtual" "$(translate "Create virtual disk")" \
    "passthrough" "$(translate "Use physical disk passthrough")" \
    --ok-button "Select" --cancel-button "Cancel" 3>&1 1>&2 2>&3)

  [[ -z "$DISK_TYPE" ]] && return 1

  if [[ "$DISK_TYPE" == "virtual" ]]; then
    select_virtual_disk
  else
    select_passthrough_disk
  fi
}

# ==========================================================
# Select Virtual Disks
# ==========================================================
function select_virtual_disk() {

  VIRTUAL_DISKS=()      


  local add_more_disks=true
  while $add_more_disks; do

  msg_info "Detecting available storage volumes..."


    STORAGE_MENU=()
    while read -r line; do
      TAG=$(echo $line | awk '{print $1}')
      TYPE=$(echo $line | awk '{print $2}')
      FREE=$(echo $line | numfmt --field 4-6 --from-unit=K --to=iec --format "%.2f" | awk '{printf( "%9sB", $6)}')
      ITEM=$(printf "%-15s %-10s %-15s" "$TAG" "$TYPE" "$FREE")
      STORAGE_MENU+=("$TAG" "$ITEM" "OFF")
    done < <(pvesm status -content images | awk 'NR>1')

 
    VALID=$(pvesm status -content images | awk 'NR>1')
    if [ -z "$VALID" ]; then
      msg_error "Unable to detect a valid storage location."
      sleep 2
      select_disk_type
    fi

    

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


    DISK_SIZE=$(whiptail --backtitle "ProxMenuX" --inputbox "$(translate "System Disk Size (GB)")" 8 58 32 --title "VIRTUAL DISK" --cancel-button Cancel 3>&1 1>&2 2>&3)
    
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
      DISK_SIZE="32"
    fi


    VIRTUAL_DISKS+=("${STORAGE}:${DISK_SIZE}")



    if ! whiptail --backtitle "ProxMenuX" --title "$(translate "Add Another Disk")" \
      --yesno "$(translate "Do you want to add another virtual disk?")" 8 58; then
      add_more_disks=false
    fi
  done


  if [ ${#VIRTUAL_DISKS[@]} -gt 0 ]; then

    msg_ok "Virtual Disks Created:"
    for i in "${!VIRTUAL_DISKS[@]}"; do
      echo -e "${TAB}${BL}- Disk $((i+1)): ${VIRTUAL_DISKS[$i]}GB${CL}"
    done
  fi


  export VIRTUAL_DISKS


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

  
}
# ==========================================================