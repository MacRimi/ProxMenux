#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.1
# Last Updated: 29/05/2025
# ==========================================================
# Description:
# This script automates the process of importing disk images into Proxmox VE virtual machines (VMs), 
# making it easy to attach pre-existing disk files without manual configuration.
#
# Before running the script, ensure that disk images are available in /var/lib/vz/template/images/. 
# The script scans this directory for compatible formats (.img, .qcow2, .vmdk, .raw) and lists the available files.
#
# Using an interactive menu, you can:
# - Select a VM to attach the imported disk.
# - Choose one or multiple disk images for import.
# - Pick a storage volume in Proxmox for disk placement.
# - Assign a suitable interface (SATA, SCSI, VirtIO, or IDE).
# - Enable optional settings like SSD emulation or bootable disk configuration.
#
# Once completed, the script ensures the selected images are correctly attached and ready to use.
# ==========================================================

# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

[[ -f "$UTILS_FILE" ]] && source "$UTILS_FILE"
load_language
initialize_cache
# Configuration ============================================



detect_image_dir() {
  for store in $(pvesm status -content images | awk 'NR>1 {print $1}'); do
    path=$(pvesm path "${store}:template" 2>/dev/null)
    if [[ -d "$path" ]]; then
      for ext in raw img qcow2 vmdk; do
        if compgen -G "$path/*.$ext" > /dev/null; then
          echo "$path"
          return 0
        fi
      done
      for sub in images iso; do
        dir="$path/$sub"
        if [[ -d "$dir" ]]; then
          for ext in raw img qcow2 vmdk; do
            if compgen -G "$dir/*.$ext" > /dev/null; then
              echo "$dir"
              return 0
            fi
          done
        fi
      done
    fi
  done
  for fallback in /var/lib/vz/template/images /var/lib/vz/template/iso; do
    if [[ -d "$fallback" ]]; then
      for ext in raw img qcow2 vmdk; do
        if compgen -G "$fallback/*.$ext" > /dev/null; then
          echo "$fallback"
          return 0
        fi
      done
    fi
  done
  return 1
}


IMAGES_DIR=$(detect_image_dir)
if [[ -z "$IMAGES_DIR" ]]; then
  dialog --title "$(translate 'No Images Found')" \
         --msgbox "$(translate 'Could not find any directory containing disk images')\n\n$(translate 'Make sure there is at least one file with extension .img, .qcow2, .vmdk or .raw')" 15 60
  exit 1
fi

IMAGES=$(ls -A "$IMAGES_DIR" | grep -E "\.(img|qcow2|vmdk|raw)$")
if [ -z "$IMAGES" ]; then
  dialog --title "$(translate 'No Disk Images Found')" \
         --msgbox "$(translate 'No compatible disk images found in:')\n\n$IMAGES_DIR\n\n$(translate 'Supported formats: .img, .qcow2, .vmdk, .raw')" 15 60
  exit 1
fi


# 1. Select VM
msg_info "$(translate 'Getting VM list')"
VM_LIST=$(qm list | awk 'NR>1 {print $1" "$2}')
if [ -z "$VM_LIST" ]; then
    msg_error "$(translate 'No VMs available in the system')"
    exit 1
fi
msg_ok "$(translate 'VM list obtained')"

VMID=$(whiptail --title "$(translate 'Select VM')" --menu "$(translate 'Select the VM where you want to import the disk image:')" 15 60 8 $VM_LIST 3>&1 1>&2 2>&3)

if [ -z "$VMID" ]; then
   
    exit 1
fi



# 2. Select storage volume
msg_info "$(translate 'Getting storage volumes')"
STORAGE_LIST=$(pvesm status -content images | awk 'NR>1 {print $1}')
if [ -z "$STORAGE_LIST" ]; then
    msg_error "$(translate 'No storage volumes available')"
    exit 1
fi
msg_ok "$(translate 'Storage volumes obtained')"


STORAGE_OPTIONS=()
while read -r storage; do
    STORAGE_OPTIONS+=("$storage" "")
done <<< "$STORAGE_LIST"

STORAGE=$(whiptail --title "$(translate 'Select Storage')" --menu "$(translate 'Select the storage volume for disk import:')" 15 60 8 "${STORAGE_OPTIONS[@]}" 3>&1 1>&2 2>&3)

if [ -z "$STORAGE" ]; then
    
    exit 1
fi



# 3. Select disk images
msg_info "$(translate 'Scanning disk images')"
if [ -z "$IMAGES" ]; then
    msg_warn "$(translate 'No compatible disk images found in') $IMAGES_DIR"
    exit 0
fi
msg_ok "$(translate 'Disk images found')"

IMAGE_OPTIONS=()
while read -r img; do
    IMAGE_OPTIONS+=("$img" "" "OFF")
done <<< "$IMAGES"

SELECTED_IMAGES=$(whiptail --title "$(translate 'Select Disk Images')" --checklist "$(translate 'Select the disk images to import:')" 20 60 10 "${IMAGE_OPTIONS[@]}" 3>&1 1>&2 2>&3)

if [ -z "$SELECTED_IMAGES" ]; then
   
    exit 1
fi



# 4. Import each selected image
for IMAGE in $SELECTED_IMAGES; do


    IMAGE=$(echo "$IMAGE" | tr -d '"')


    INTERFACE=$(whiptail --title "$(translate 'Interface Type')" --menu "$(translate 'Select the interface type for the image:') $IMAGE" 15 40 4 \
    "sata" "SATA" \
    "scsi" "SCSI" \
    "virtio" "VirtIO" \
    "ide" "IDE" 3>&1 1>&2 2>&3)

    if [ -z "$INTERFACE" ]; then
        msg_error "$(translate 'No interface type selected for') $IMAGE"
        continue
    fi

    FULL_PATH="$IMAGES_DIR/$IMAGE"


    msg_info "$(translate 'Importing image:')"


    TEMP_DISK_FILE=$(mktemp)


    qm importdisk "$VMID" "$FULL_PATH" "$STORAGE" 2>&1 | while read -r line; do
        if [[ "$line" =~ transferred ]]; then

            PERCENT=$(echo "$line" | grep -oP "\d+\.\d+(?=%)")
 
            echo -ne "\r${TAB}${BL}-$(translate 'Importing image:') $IMAGE-${CL} ${PERCENT}%"
        elif [[ "$line" =~ successfully\ imported\ disk ]]; then

            echo "$line" | grep -oP "(?<=successfully imported disk ').*(?=')" > "$TEMP_DISK_FILE"
        fi
    done
    echo -ne "\n" 

    IMPORT_STATUS=${PIPESTATUS[0]} 

    if [ $IMPORT_STATUS -eq 0 ]; then
        msg_ok "$(translate 'Image imported successfully')"


        IMPORTED_DISK=$(cat "$TEMP_DISK_FILE")
        rm -f "$TEMP_DISK_FILE" 

   
        if [ -z "$IMPORTED_DISK" ]; then
   
            STORAGE_TYPE=$(pvesm status -storage "$STORAGE" | awk 'NR>1 {print $2}')

            if [[ "$STORAGE_TYPE" == "btrfs" || "$STORAGE_TYPE" == "dir" || "$STORAGE_TYPE" == "nfs" ]]; then
   
                UNUSED_LINE=$(qm config "$VMID" | grep -E '^unused[0-9]+:')
                IMPORTED_ID=$(echo "$UNUSED_LINE" | cut -d: -f1)
                IMPORTED_DISK=$(echo "$UNUSED_LINE" | cut -d: -f2- | xargs)
            else
   
                IMPORTED_DISK=$(qm config "$VMID" | grep -E 'unused[0-9]+' | tail -1 | cut -d: -f2- | xargs)
                IMPORTED_ID=$(qm config "$VMID" | grep -E 'unused[0-9]+' | tail -1 | cut -d: -f1)
            fi
        fi

        if [ -n "$IMPORTED_DISK" ]; then
       
            EXISTING_DISKS=$(qm config "$VMID" | grep -oP "${INTERFACE}\d+" | sort -n)
            if [ -z "$EXISTING_DISKS" ]; then
                NEXT_SLOT=0
            else
                LAST_SLOT=$(echo "$EXISTING_DISKS" | tail -n1 | sed "s/${INTERFACE}//")
                NEXT_SLOT=$((LAST_SLOT + 1))
            fi

   
            if [ "$INTERFACE" != "virtio" ]; then
                if (whiptail --title "$(translate 'SSD Emulation')" --yesno "$(translate 'Do you want to use SSD emulation for this disk?')" 10 60); then
                    SSD_OPTION=",ssd=1"
                else
                    SSD_OPTION=""
                fi
            else
                SSD_OPTION=""
            fi

            msg_info "$(translate 'Configuring disk')"

 
            if qm set "$VMID" --${INTERFACE}${NEXT_SLOT} "$IMPORTED_DISK${SSD_OPTION}" &>/dev/null; then
                msg_ok "$(translate 'Image') $IMAGE $(translate 'configured as') ${INTERFACE}${NEXT_SLOT}"

   
                if [[ -n "$IMPORTED_ID" ]]; then
                    qm set "$VMID" -delete "$IMPORTED_ID" >/dev/null 2>&1
                fi

  
                if (whiptail --title "$(translate 'Make Bootable')" --yesno "$(translate 'Do you want to make this disk bootable?')" 10 60); then
                    msg_info "$(translate 'Configuring disk as bootable')"

                    if qm set "$VMID" --boot c --bootdisk ${INTERFACE}${NEXT_SLOT} &>/dev/null; then
                        msg_ok "$(translate 'Disk configured as bootable')"
                    else
                        msg_error "$(translate 'Could not configure the disk as bootable')"
                    fi
                fi
            else
                msg_error "$(translate 'Could not configure disk') ${INTERFACE}${NEXT_SLOT} $(translate 'for VM') $VMID"
                echo "DEBUG: Tried to configure: --${INTERFACE}${NEXT_SLOT} \"$IMPORTED_DISK${SSD_OPTION}\""
                echo "DEBUG: VM config after import:"
                qm config "$VMID" | grep -E "(unused|${INTERFACE})"
            fi
        else
            msg_error "$(translate 'Could not find the imported disk')"
            echo "DEBUG: VM config after import:"
            qm config "$VMID"
        fi
    else
        msg_error "$(translate 'Could not import') $IMAGE"
    fi
done



msg_ok "$(translate 'All selected images have been processed')"
msg_success "$(translate "Press Enter to return to menu...")"
read -r
