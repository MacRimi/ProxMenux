#!/bin/bash

# ==========================================================
# ProxMenux - Import Disk to VM (Passthrough)
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.2
# ==========================================================
# Description:
# Assigns physical disks to existing Proxmox VMs via an
# interactive menu. Uses persistent /dev/disk/by-id paths
# whenever available and blocks system / already-assigned disks.
#
# Features:
# - Detects and excludes the system disk.
# - Lists all VMs for selection.
# - Identifies unassigned physical disks.
# - Supports SATA, SCSI, VirtIO and IDE interfaces.
# - Warns about disk sharing between VMs to avoid corruption.
# - Verifies the assignment after attaching.
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

# shellcheck source=/dev/null
if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

# shellcheck source=/dev/null
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/vm_storage_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_LOCAL/global/vm_storage_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/vm_storage_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_DEFAULT/global/vm_storage_helpers.sh"
fi

BACKTITLE="ProxMenux"
UI_MENU_H=20
UI_MENU_W=84
UI_MENU_LIST_H=10
UI_SHORT_MENU_H=16
UI_SHORT_MENU_W=72
UI_SHORT_MENU_LIST_H=6
UI_MSG_H=10
UI_MSG_W=72
UI_YESNO_H=18
UI_YESNO_W=86
UI_RESULT_H=18
UI_RESULT_W=86

load_language
initialize_cache

if ! command -v pveversion >/dev/null 2>&1; then
    dialog --backtitle "$BACKTITLE" --title "$(translate "Error")" \
        --msgbox "$(translate "This script must be run on a Proxmox host.")" 8 60
    exit 1
fi
# ==========================================================


get_disk_info() {
    local disk=$1
    local model size
    model=$(lsblk -dn -o MODEL "$disk" | xargs)
    size=$(lsblk -dn -o SIZE "$disk" | xargs)
    [[ -z "$model" ]] && model="Unknown"
    printf '%s\t%s\n' "$model" "$size"
}

get_all_disk_paths() {
    local disk="$1"
    local real_path
    real_path=$(readlink -f "$disk" 2>/dev/null)

    [[ -n "$disk" ]] && echo "$disk"
    [[ -n "$real_path" ]] && echo "$real_path"

    local link
    for link in /dev/disk/by-id/* /dev/disk/by-path/*; do
        [[ -e "$link" ]] || continue
        [[ "$(readlink -f "$link" 2>/dev/null)" == "$real_path" ]] || continue
        echo "$link"
    done | sort -u
}

get_preferred_disk_path() {
    local disk="$1"
    local real_path
    real_path=$(readlink -f "$disk" 2>/dev/null)
    [[ -z "$real_path" ]] && { echo "$disk"; return 0; }

    local best="" best_score=99999
    local link name score
    for link in /dev/disk/by-id/*; do
        [[ -e "$link" ]] || continue
        [[ "$(readlink -f "$link" 2>/dev/null)" == "$real_path" ]] || continue
        name=$(basename "$link")
        [[ "$name" == *-part* ]] && continue

        case "$name" in
            ata-*|scsi-*|nvme-*) score=100 ;;
            wwn-*) score=200 ;;
            *) score=300 ;;
        esac
        score=$((score + ${#name}))
        if (( score < best_score )); then
            best="$link"
            best_score=$score
        fi
    done

    if [[ -n "$best" ]]; then
        echo "$best"
    else
        echo "$disk"
    fi
}

disk_referenced_in_config() {
    local config_text="$1"
    local disk="$2"
    local alias
    while read -r alias; do
        [[ -z "$alias" ]] && continue
        if grep -Fq "$alias" <<< "$config_text"; then
            return 0
        fi
    done < <(get_all_disk_paths "$disk")
    return 1
}


# ── DIALOG PHASE ──────────────────────────────────────────────────────────────

VM_LIST=$(qm list | awk 'NR>1 {print $1, $2}')
if [ -z "$VM_LIST" ]; then
    dialog --backtitle "$BACKTITLE" \
           --title "$(translate "Error")" \
           --msgbox "$(translate "No VMs available in the system.")" $UI_MSG_H $UI_MSG_W
    exit 1
fi

# shellcheck disable=SC2086
VMID=$(dialog --backtitle "$BACKTITLE" \
              --title "$(translate "Select VM")" \
              --menu "$(translate "Select the VM to which you want to add disks:")" $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
              $VM_LIST \
              2>&1 >/dev/tty)

if [ -z "$VMID" ]; then
    dialog --backtitle "$BACKTITLE" \
           --title "$(translate "Error")" \
           --msgbox "$(translate "No VM was selected.")" $UI_MSG_H $UI_MSG_W
    exit 1
fi

VMID=$(echo "$VMID" | tr -d '"')

VM_STATUS=$(qm status "$VMID" | awk '{print $2}')
if [ "$VM_STATUS" == "running" ]; then
    dialog --backtitle "$BACKTITLE" \
           --title "$(translate "Warning")" \
           --msgbox "$(translate "The VM is powered on. Turn it off before adding disks.")" $UI_MSG_H $UI_MSG_W
    exit 1
fi


# ── TERMINAL PHASE 1: detect disks ────────────────────────────────────────────
show_proxmenux_logo
msg_title "$(translate "Import Disk to VM")"
msg_ok "$(translate "VM $VMID selected successfully.")"
msg_info "$(translate "Detecting available disks...")"

_refresh_host_storage_cache
VM_CONFIG=$(qm config "$VMID" 2>/dev/null | grep -vE '^\s*#|^description:')

FREE_DISKS=()

while read -r DISK; do
    [[ "$DISK" =~ /dev/zd ]] && continue

    IFS=$'\t' read -r MODEL SIZE < <(get_disk_info "$DISK")
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
    if _disk_used_in_guest_configs "$DISK"; then
        USED_BY="⚠ $(translate "In use")"
    fi

    if $IS_RAID && grep -q "$DISK" <<< "$(cat /proc/mdstat)"; then
        if grep -q "active raid" /proc/mdstat; then
            SHOW_DISK=false
        fi
    fi

    if $IS_ZFS; then
        SHOW_DISK=false
    fi

    # Catch whole-disk ZFS vdevs with no partitions (e.g. bare NVMe ZFS)
    # The tail -n +2 trick misses them; ZFS_DISKS from _refresh_host_storage_cache covers them.
    if [[ -n "$ZFS_DISKS" ]] && \
       { grep -qFx "$DISK" <<< "$ZFS_DISKS" || \
         { [[ -n "$REAL_PATH" ]] && grep -qFx "$REAL_PATH" <<< "$ZFS_DISKS"; }; }; then
        SHOW_DISK=false
    fi

    if $IS_MOUNTED; then
        SHOW_DISK=false
    fi

    if disk_referenced_in_config "$VM_CONFIG" "$DISK"; then
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
    stop_spinner
    dialog --backtitle "$BACKTITLE" \
           --title "$(translate "Error")" \
           --msgbox "$(translate "No disks available for this VM.")" $UI_MSG_H $UI_MSG_W
    exit 1
fi

stop_spinner
msg_ok "$(translate "Available disks detected.")"


# ── DIALOG PHASE: select disks + interface ────────────────────────────────────

MAX_WIDTH=$(printf "%s\n" "${FREE_DISKS[@]}" | awk '{print length}' | sort -nr | head -n1)
TOTAL_WIDTH=$((MAX_WIDTH + 20))
if [ $TOTAL_WIDTH -lt $UI_MENU_W ]; then
    TOTAL_WIDTH=$UI_MENU_W
fi
if [ $TOTAL_WIDTH -gt 116 ]; then
    TOTAL_WIDTH=116
fi

SELECTED=$(dialog --backtitle "$BACKTITLE" \
    --title "$(translate "Select Disks")" \
    --checklist "\n$(translate "Select the disks you want to add:")" $UI_MENU_H $TOTAL_WIDTH $UI_MENU_LIST_H \
    "${FREE_DISKS[@]}" \
    2>&1 >/dev/tty)

if [ -z "$SELECTED" ]; then
    dialog --backtitle "$BACKTITLE" \
           --title "$(translate "Error")" \
           --msgbox "$(translate "No disks were selected.")" $UI_MSG_H $UI_MSG_W
    exit 1
fi

INTERFACE=$(dialog --backtitle "$BACKTITLE" \
    --title "$(translate "Interface Type")" \
    --menu "$(translate "Select the interface type for all disks:")" $UI_SHORT_MENU_H $UI_SHORT_MENU_W $UI_SHORT_MENU_LIST_H \
    "sata"   "$(translate "Add as SATA")" \
    "scsi"   "$(translate "Add as SCSI")" \
    "virtio" "$(translate "Add as VirtIO")" \
    "ide"    "$(translate "Add as IDE")" \
    2>&1 >/dev/tty)

if [ -z "$INTERFACE" ]; then
    dialog --backtitle "$BACKTITLE" \
           --title "$(translate "Error")" \
           --msgbox "$(translate "No interface type was selected for the disks.")" $UI_MSG_H $UI_MSG_W
    exit 1
fi


# ── DIALOG PHASE: per-disk pre-check ──────────────────────────────────────────
declare -a DISK_LIST=()
declare -a DISK_DESCRIPTIONS=()
declare -a DISK_ASSIGNED_TOS=()
declare -a NVME_SKIPPED=()

for DISK in $SELECTED; do
    DISK="${DISK//\"/}"
    DISK_INFO=$(get_disk_info "$DISK")

    ASSIGNED_TO=""
    RUNNING_VMS=""
    RUNNING_CTS=""

    while read -r VM_ID VM_NAME; do
        VM_CONFIG_RAW=$(qm config "$VM_ID" 2>/dev/null)
        if [[ "$VM_ID" =~ ^[0-9]+$ ]] && disk_referenced_in_config "$VM_CONFIG_RAW" "$DISK"; then
            ASSIGNED_TO+="VM $VM_ID $VM_NAME\n"
            VM_STATUS_CHK=$(qm status "$VM_ID" | awk '{print $2}')
            [[ "$VM_STATUS_CHK" == "running" ]] && RUNNING_VMS+="VM $VM_ID $VM_NAME\n"
        fi
    done < <(qm list | awk 'NR>1 {print $1, $2}')

    while read -r CT_ID CT_NAME; do
        CT_CONFIG_RAW=$(pct config "$CT_ID" 2>/dev/null)
        if [[ "$CT_ID" =~ ^[0-9]+$ ]] && disk_referenced_in_config "$CT_CONFIG_RAW" "$DISK"; then
            ASSIGNED_TO+="CT $CT_ID $CT_NAME\n"
            CT_STATUS_CHK=$(pct status "$CT_ID" | awk '{print $2}')
            [[ "$CT_STATUS_CHK" == "running" ]] && RUNNING_CTS+="CT $CT_ID $CT_NAME\n"
        fi
    done < <(pct list | awk 'NR>1 {print $1, $3}')

    if [ -n "$RUNNING_VMS" ] || [ -n "$RUNNING_CTS" ]; then
        dialog --backtitle "$BACKTITLE" \
               --title "$(translate "Disk In Use")" \
               --msgbox "$(translate "The disk") $DISK_INFO $(translate "is in use by the following running VM(s) or CT(s):")\\n$RUNNING_VMS$RUNNING_CTS\\n\\n$(translate "Stop them first and run this script again.")" $UI_RESULT_H $UI_RESULT_W
        continue
    fi

    if [ -n "$ASSIGNED_TO" ]; then
        if ! dialog --backtitle "$BACKTITLE" \
               --title "$(translate "Disk Already Assigned")" \
               --yesno "\n\n$(translate "The disk") $DISK_INFO $(translate "is already assigned to the following VM(s) or CT(s):")\\n$ASSIGNED_TO\\n\\n$(translate "Do you want to continue anyway?")" $UI_YESNO_H $UI_YESNO_W; then
            continue
        fi
    fi

    # NVMe: suggest PCIe passthrough for better performance
    if [[ "$DISK" =~ /dev/nvme ]] || \
       [[ "$(lsblk -dn -o TRAN "$DISK" 2>/dev/null | xargs)" == "nvme" ]]; then
        NVME_CHOICE=$(dialog --backtitle "$BACKTITLE" \
            --title "$(translate "NVMe Disk Detected")" \
            --default-item "disk" \
            --menu "\n$(translate "Adding this NVMe as a PCIe device (via 'Add Controller or NVMe PCIe to VM') gives better performance.")\n\n$(translate "How do you want to add it?")" \
            $UI_YESNO_H $UI_YESNO_W 2 \
            "disk" "$(translate "Add as disk (standard)")" \
            "pci"  "$(translate "Skip — I will add it as PCIe device")" \
            2>&1 >/dev/tty)
        if [[ "$NVME_CHOICE" == "pci" ]]; then
            NVME_SKIPPED+=("$DISK")
            continue
        fi
    fi

    DISK_LIST+=("$DISK")
    DISK_DESCRIPTIONS+=("$DISK_INFO")
    DISK_ASSIGNED_TOS+=("$ASSIGNED_TO")
done

if [ "${#DISK_LIST[@]}" -eq 0 ]; then
    show_proxmenux_logo
    msg_title "$(translate "Import Disk to VM")"
    msg_warn "$(translate "No disks were configured for processing.")"
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
    exit 0
fi


# ── TERMINAL PHASE: execute all disk operations ───────────────────────────────
show_proxmenux_logo
msg_title "$(translate "Import Disk to VM")"
msg_ok "$(translate "VM $VMID selected successfully.")"
msg_ok "$(translate "Disks to process:") ${#DISK_LIST[@]}"
for i in "${!DISK_LIST[@]}"; do
    IFS=$'\t' read -r _desc_model _desc_size <<< "${DISK_DESCRIPTIONS[$i]}"
    echo -e "${TAB}${BL}${DISK_LIST[$i]}  $_desc_model  $_desc_size${CL}"
done
if [[ ${#NVME_SKIPPED[@]} -gt 0 ]]; then
    echo ""
    msg_warn "$(translate "NVMe skipped (to add as PCIe use 'Add Controller or NVMe PCIe to VM'):")"
    for _nvme in "${NVME_SKIPPED[@]}"; do
        echo -e "${TAB}${BL}${_nvme}${CL}"
    done
fi
echo ""
msg_ok "$(translate "Interface type:") $INTERFACE"
echo ""

DISKS_ADDED=0

for i in "${!DISK_LIST[@]}"; do
    DISK="${DISK_LIST[$i]}"
    ASSIGNED_TO="${DISK_ASSIGNED_TOS[$i]}"
    IFS=$'\t' read -r _model _size <<< "${DISK_DESCRIPTIONS[$i]}"

    INDEX=0
    # Anchor the match: `^scsi1:` vs `^scsi1\d:`. The previous `grep -q
    # "scsi1"` matched scsi10/scsi11/... and skipped over a genuinely-free
    # scsi1 slot — the disk still got attached but a hole was left mid-
    # range. Audit Tier 6 — `disk-passthrough.sh` slot search no anchored.
    while qm config "$VMID" | grep -Eq "^${INTERFACE}${INDEX}:"; do
        ((INDEX++))
    done

    ASSIGN_PATH=$(get_preferred_disk_path "$DISK")
    msg_info "$(translate "Adding") $_model $_size $(translate "as") ${INTERFACE}${INDEX}..."
    if RESULT=$(qm set "$VMID" "-${INTERFACE}${INDEX}" "$ASSIGN_PATH" 2>&1); then
        msg_ok "$(translate "Disk added as") ${INTERFACE}${INDEX} $(translate "using") $ASSIGN_PATH"
        [[ -n "$ASSIGNED_TO" ]] && msg_warn "$(translate "WARNING: This disk is also assigned to:") $(echo -e "$ASSIGNED_TO" | tr '\n' ' ')"
        ((DISKS_ADDED++))
    else
        msg_error "$(translate "Could not add") $_model $_size: $RESULT"
    fi
done

echo ""
if [ "$DISKS_ADDED" -gt 0 ]; then
    msg_ok "$(translate "Completed.") $DISKS_ADDED $(translate "disk(s) added to VM") $VMID."
else
    msg_warn "$(translate "No disks were added.")"
fi
msg_success "$(translate "Press Enter to return to menu...")"
read -r
exit 0
