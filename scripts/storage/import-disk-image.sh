#!/bin/bash

# ==========================================================
# ProxMenux - Import Disk Image to VM
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.3
# ==========================================================
# Description:
# Imports disk images (.img, .qcow2, .vmdk, .raw) into
# existing Proxmox VE VMs. Supports the default ISO directory
# and custom paths; all user decisions are collected up-front
# (Phase 1 dialogs) before any operation runs (Phase 2).
# ==========================================================

# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
BACKTITLE="ProxMenux"
UI_MENU_H=20
UI_MENU_W=84
UI_MENU_LIST_H=10
UI_SHORT_MENU_H=16
UI_SHORT_MENU_W=72
UI_SHORT_MENU_LIST_H=6
UI_MSG_H=10
UI_MSG_W=72
UI_YESNO_H=10
UI_YESNO_W=72
UI_RESULT_H=14
UI_RESULT_W=86

# shellcheck source=/dev/null
[[ -f "$UTILS_FILE" ]] && source "$UTILS_FILE"
load_language
initialize_cache
# Configuration ============================================


_get_default_images_dir() {
  for dir in /var/lib/vz/template/iso /var/lib/vz/template/images; do
    [[ -d "$dir" ]] && echo "$dir" && return 0
  done
  local store path
  for store in $(pvesm status -content images 2>/dev/null | awk 'NR>1 {print $1}'); do
    path=$(pvesm path "${store}:template" 2>/dev/null)
    [[ -d "$path" ]] && echo "$path" && return 0
  done
  echo "/var/lib/vz/template/iso"
}


# ==========================================================
# PHASE 1 — SELECTION
# All dialogs run here. No execution, no show_proxmenux_logo.
# ==========================================================

# ── Step 1: Select VM ─────────────────────────────────────
VM_OPTIONS=()
while read -r vmid vmname _rest; do
  VM_OPTIONS+=("$vmid" "${vmname:-VM-$vmid}")
done < <(qm list 2>/dev/null | awk 'NR>1')
stop_spinner

if [[ ${#VM_OPTIONS[@]} -eq 0 ]]; then
  dialog --backtitle "$BACKTITLE" \
    --title "$(translate 'No VMs Found')" \
    --msgbox "\n$(translate 'No VMs available in the system.')" \
    $UI_MSG_H $UI_MSG_W
  exit 1
fi

VMID=$(dialog --backtitle "$BACKTITLE" \
  --title "$(translate 'Select VM')" \
  --menu "$(translate 'Select the VM where you want to import the disk image:')" \
  $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
  "${VM_OPTIONS[@]}" \
  2>&1 >/dev/tty)
[[ -z "$VMID" ]] && exit 0


# ── Step 2: Select storage ────────────────────────────────
STORAGE_OPTIONS=()
while read -r storage type _rest; do
  STORAGE_OPTIONS+=("$storage" "$type")
done < <(pvesm status -content images 2>/dev/null | awk 'NR>1')
stop_spinner

if [[ ${#STORAGE_OPTIONS[@]} -eq 0 ]]; then
  dialog --backtitle "$BACKTITLE" \
    --title "$(translate 'No Storage Found')" \
    --msgbox "\n$(translate 'No storage volumes available for disk images.')" \
    $UI_MSG_H $UI_MSG_W
  exit 1
fi

if [[ ${#STORAGE_OPTIONS[@]} -eq 2 ]]; then
  # Only one storage available — auto-select it
  STORAGE="${STORAGE_OPTIONS[0]}"
else
  STORAGE=$(dialog --backtitle "$BACKTITLE" \
    --title "$(translate 'Select Storage')" \
    --menu "$(translate 'Select the storage volume for disk import:')" \
    $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
    "${STORAGE_OPTIONS[@]}" \
    2>&1 >/dev/tty)
  [[ -z "$STORAGE" ]] && exit 0
fi


# ── Step 3: Select image source directory ────────────────
ISO_DIR="/var/lib/vz/template/iso"

DIR_CHOICE=$(dialog --backtitle "$BACKTITLE" \
  --title "$(translate 'Image Source Directory')" \
  --menu "$(translate 'Select the directory containing disk images:')" \
  $UI_SHORT_MENU_H $UI_MENU_W $UI_SHORT_MENU_LIST_H \
  "$ISO_DIR" "$(translate 'Default ISO directory')" \
  "custom"   "$(translate 'Custom path...')" \
  2>&1 >/dev/tty)
[[ -z "$DIR_CHOICE" ]] && exit 0

if [[ "$DIR_CHOICE" == "custom" ]]; then
  IMAGES_DIR=$(dialog --backtitle "$BACKTITLE" \
    --title "$(translate 'Custom Directory')" \
    --inputbox "\n$(translate 'Enter the full path to the directory containing disk images:')\n$(translate 'Supported formats: .img, .qcow2, .vmdk, .raw')" \
    10 $UI_RESULT_W "" \
    2>&1 >/dev/tty)
  [[ -z "$IMAGES_DIR" ]] && exit 0
else
  IMAGES_DIR="$ISO_DIR"
fi

if [[ ! -d "$IMAGES_DIR" ]]; then
  dialog --backtitle "$BACKTITLE" \
    --title "$(translate 'Directory Not Found')" \
    --msgbox "\n$(translate 'The specified directory does not exist:')\n\n$IMAGES_DIR" \
    $UI_MSG_H $UI_MSG_W
  exit 1
fi

IMAGES=$(find "$IMAGES_DIR" -maxdepth 1 -type f \
  \( -name "*.img" -o -name "*.qcow2" -o -name "*.vmdk" -o -name "*.raw" \) \
  -printf '%f\n' 2>/dev/null | sort)

if [[ -z "$IMAGES" ]]; then
  dialog --backtitle "$BACKTITLE" \
    --title "$(translate 'No Disk Images Found')" \
    --msgbox "\n$(translate 'No compatible disk images found in:')\n\n$IMAGES_DIR\n\n$(translate 'Supported formats: .img, .qcow2, .vmdk, .raw')" \
    $UI_RESULT_H $UI_RESULT_W
  exit 1
fi


# ── Step 4: Select images ─────────────────────────────────
IMAGE_OPTIONS=()
while IFS= read -r img; do
  IMAGE_OPTIONS+=("$img" "" "OFF")
done <<< "$IMAGES"

# `--separate-output` prints each selected tag on its own line with no
# quoting, so we never need `eval` to split the output. The previous form
# `eval "declare -a A=($SELECTED)"` would execute backticks / $(...) baked
# into a filename — perfectly legal on ext4 — as shell commands. Audit
# Tier 6 — `import-disk-image.sh` `eval` sobre salida del dialog.
SELECTED_IMAGES_STR=$(dialog --backtitle "$BACKTITLE" \
  --separate-output \
  --title "$(translate 'Select Disk Images')" \
  --checklist "$(translate 'Select one or more disk images to import:')" \
  $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
  "${IMAGE_OPTIONS[@]}" \
  2>&1 >/dev/tty)
[[ -z "$SELECTED_IMAGES_STR" ]] && exit 0

declare -a SELECTED_ARRAY=()
while IFS= read -r _img; do
  [[ -n "$_img" ]] && SELECTED_ARRAY+=("$_img")
done <<< "$SELECTED_IMAGES_STR"


# ── Step 5: Per-image options ─────────────────────────────
declare -a IMG_NAMES=()
declare -a IMG_INTERFACES=()
declare -a IMG_SSD_OPTIONS=()
declare -a IMG_BOOTABLE=()

for IMAGE in "${SELECTED_ARRAY[@]}"; do
  IMAGE="${IMAGE//\"/}"

  INTERFACE=$(dialog --backtitle "$BACKTITLE" \
    --title "$(translate 'Interface Type') — $IMAGE" \
    --default-item "scsi" \
    --menu "$(translate 'Select the interface type for:') $IMAGE" \
    $UI_SHORT_MENU_H $UI_SHORT_MENU_W $UI_SHORT_MENU_LIST_H \
    "scsi"   "SCSI $(translate '(recommended)')" \
    "virtio" "VirtIO" \
    "sata"   "SATA" \
    "ide"    "IDE" \
    2>&1 >/dev/tty)
  [[ -z "$INTERFACE" ]] && continue

  SSD_OPTION=""
  if [[ "$INTERFACE" != "virtio" ]]; then
    if dialog --backtitle "$BACKTITLE" \
              --title "$(translate 'SSD Emulation') — $IMAGE" \
              --yesno "\n$(translate 'Enable SSD emulation for this disk?')" \
              $UI_YESNO_H $UI_YESNO_W; then
      SSD_OPTION=",ssd=1"
    fi
  fi

  BOOTABLE="no"
  if dialog --backtitle "$BACKTITLE" \
            --title "$(translate 'Boot Disk') — $IMAGE" \
            --yesno "\n$(translate 'Set this disk as the primary boot disk?')" \
            $UI_YESNO_H $UI_YESNO_W; then
    BOOTABLE="yes"
  fi

  IMG_NAMES+=("$IMAGE")
  IMG_INTERFACES+=("$INTERFACE")
  IMG_SSD_OPTIONS+=("$SSD_OPTION")
  IMG_BOOTABLE+=("$BOOTABLE")
done

if [[ ${#IMG_NAMES[@]} -eq 0 ]]; then
  exit 0
fi


# ==========================================================
# PHASE 2 — EXECUTION
# show_proxmenux_logo appears here exactly once.
# No dialogs from this point on.
# ==========================================================

show_proxmenux_logo
msg_title "$(translate 'Import Disk Image to VM')"

VM_NAME=$(qm config "$VMID" 2>/dev/null | awk '/^name:/ {print $2}')
msg_ok "$(translate 'VM:') ${VM_NAME:-VM-$VMID} (${VMID})"
msg_ok "$(translate 'Storage:') $STORAGE"
msg_ok "$(translate 'Image directory:') $IMAGES_DIR"
msg_ok "$(translate 'Images to import:') ${#IMG_NAMES[@]}"
echo ""

PROCESSED=0
FAILED=0

for i in "${!IMG_NAMES[@]}"; do
  IMAGE="${IMG_NAMES[$i]}"
  INTERFACE="${IMG_INTERFACES[$i]}"
  SSD_OPTION="${IMG_SSD_OPTIONS[$i]}"
  BOOTABLE="${IMG_BOOTABLE[$i]}"
  FULL_PATH="$IMAGES_DIR/$IMAGE"

  if [[ ! -f "$FULL_PATH" ]]; then
    msg_error "$(translate 'Image file not found:') $FULL_PATH"
    FAILED=$((FAILED + 1))
    continue
  fi

  # Snapshot of unused entries before import for reliable detection
  BEFORE_UNUSED=$(qm config "$VMID" 2>/dev/null | grep -E '^unused[0-9]+:' || true)

  TEMP_STATUS_FILE=$(mktemp)
  TEMP_DISK_FILE=$(mktemp)

  msg_info "$(translate 'Importing') $IMAGE..."

  (
    qm importdisk "$VMID" "$FULL_PATH" "$STORAGE" 2>&1
    echo $? > "$TEMP_STATUS_FILE"
  ) | while IFS= read -r line; do
    if [[ "$line" =~ [0-9]+\.[0-9]+% ]]; then
      echo -ne "\r${TAB}${BL}$(translate 'Importing') ${IMAGE}${CL} ${BASH_REMATCH[0]}   "
    fi
    if echo "$line" | grep -qiF "successfully imported disk"; then
      echo "$line" | sed -n "s/.*successfully imported disk as '\\([^']*\\)'.*/\\1/p" > "$TEMP_DISK_FILE"
    fi
  done
  echo -ne "\n"

  IMPORT_STATUS=$(cat "$TEMP_STATUS_FILE" 2>/dev/null)
  rm -f "$TEMP_STATUS_FILE"
  [[ -z "$IMPORT_STATUS" ]] && IMPORT_STATUS=1

  if [[ "$IMPORT_STATUS" -ne 0 ]]; then
    msg_error "$(translate 'Failed to import') $IMAGE"
    rm -f "$TEMP_DISK_FILE"
    FAILED=$((FAILED + 1))
    continue
  fi

  msg_ok "$(translate 'Image imported:') $IMAGE"

  # Primary: parse disk name from qm importdisk output
  IMPORTED_DISK=$(cat "$TEMP_DISK_FILE" 2>/dev/null | xargs)
  rm -f "$TEMP_DISK_FILE"

  # Fallback: compare unused entries before/after import
  if [[ -z "$IMPORTED_DISK" ]]; then
    AFTER_UNUSED=$(qm config "$VMID" 2>/dev/null | grep -E '^unused[0-9]+:' || true)
    NEW_LINE=$(comm -13 \
      <(echo "$BEFORE_UNUSED" | sort) \
      <(echo "$AFTER_UNUSED" | sort) | head -1)
    if [[ -n "$NEW_LINE" ]]; then
      IMPORTED_DISK=$(echo "$NEW_LINE" | cut -d':' -f2- | xargs)
    fi
  fi

  if [[ -z "$IMPORTED_DISK" ]]; then
    msg_error "$(translate 'Could not identify the imported disk in VM config')"
    FAILED=$((FAILED + 1))
    continue
  fi

  # Find the unusedN key that holds this disk (needed to clean it up after assignment)
  IMPORTED_ID=$(qm config "$VMID" 2>/dev/null | grep -F "$IMPORTED_DISK" | cut -d':' -f1 | head -1)

  # Find next available slot for the chosen interface
  LAST_SLOT=$(qm config "$VMID" 2>/dev/null | grep -oE "^${INTERFACE}[0-9]+" | grep -oE '[0-9]+' | sort -n | tail -1)
  if [[ -z "$LAST_SLOT" ]]; then
    NEXT_SLOT=0
  else
    NEXT_SLOT=$((LAST_SLOT + 1))
  fi

  msg_info "$(translate 'Configuring disk as') ${INTERFACE}${NEXT_SLOT}..."
  if qm set "$VMID" "--${INTERFACE}${NEXT_SLOT}" "${IMPORTED_DISK}${SSD_OPTION}" >/dev/null 2>&1; then
    msg_ok "$(translate 'Disk configured as') ${INTERFACE}${NEXT_SLOT}${SSD_OPTION:+ (SSD)}"

    # Remove the unusedN entry now that the disk is properly assigned
    if [[ -n "$IMPORTED_ID" ]]; then
      qm set "$VMID" -delete "$IMPORTED_ID" >/dev/null 2>&1
    fi

    if [[ "$BOOTABLE" == "yes" ]]; then
      msg_info "$(translate 'Setting boot order...')"
      if qm set "$VMID" --boot "order=${INTERFACE}${NEXT_SLOT}" >/dev/null 2>&1; then
        msg_ok "$(translate 'Boot order set to') ${INTERFACE}${NEXT_SLOT}"
      else
        msg_error "$(translate 'Could not set boot order for') ${INTERFACE}${NEXT_SLOT}"
      fi
    fi

    PROCESSED=$((PROCESSED + 1))
  else
    msg_error "$(translate 'Could not assign disk') ${INTERFACE}${NEXT_SLOT} $(translate 'to VM') $VMID"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
if [[ $FAILED -eq 0 ]]; then
  msg_ok "$(translate 'All images imported and configured successfully')"
elif [[ $PROCESSED -gt 0 ]]; then
  msg_warn "$(translate 'Completed with errors —') $(translate 'imported:') $PROCESSED, $(translate 'failed:') $FAILED"
else
  msg_error "$(translate 'All imports failed')"
fi

msg_success "$(translate 'Press Enter to return to menu...')"
read -r
