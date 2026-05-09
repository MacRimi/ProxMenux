#!/bin/bash
# ==========================================================
# ProxMenux - Import Disk to LXC (Passthrough)
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.3
# ==========================================================
# Description:
# Assigns physical disks to existing Proxmox LXC containers
# via an interactive menu, using persistent device paths to
# avoid issues with device order changes.
#
# Features:
# - Detects and excludes the system disk.
# - Lists all containers for selection.
# - Identifies unassigned physical disks.
# - Configures the selected disks for the CT and verifies
#   the assignment.
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

# Returns the most stable /dev/disk/by-id symlink for a device.
# Prefers ata-/scsi-/nvme- > wwn- > other by-id > by-path > raw path.
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
            wwn-*)                score=200 ;;
            *)                    score=300 ;;
        esac
        score=$((score + ${#name}))
        if (( score < best_score )); then
            best="$link"
            best_score=$score
        fi
    done

    if [[ -n "$best" ]]; then
        echo "$best"
        return 0
    fi

    for link in /dev/disk/by-path/*; do
        [[ -e "$link" ]] || continue
        [[ "$(readlink -f "$link" 2>/dev/null)" == "$real_path" ]] || continue
        echo "$link"
        return 0
    done

    msg_warn "$(translate "No persistent path found for") $disk — $(translate "using direct path (not guaranteed to survive reboots).")"
    echo "$disk"
}

install_fs_tools_in_ct() {
    local ctid="$1"
    local pkg="$2"

    if pct exec "$ctid" -- sh -c "[ -f /etc/alpine-release ]"; then
        pct exec "$ctid" -- sh -c "apk update >/dev/null 2>&1 && apk add --no-progress $pkg >/dev/null 2>&1"
    elif pct exec "$ctid" -- sh -c "grep -qi 'arch' /etc/os-release 2>/dev/null"; then
        pct exec "$ctid" -- sh -c "pacman -Sy --noconfirm $pkg >/dev/null 2>&1"
    elif pct exec "$ctid" -- sh -c "grep -qiE 'debian|ubuntu' /etc/os-release 2>/dev/null"; then
        pct exec "$ctid" -- sh -c "apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq $pkg >/dev/null 2>&1"
    else
        return 1
    fi
}

get_disk_info() {
    local disk=$1
    local model size
    model=$(lsblk -dn -o MODEL "$disk" | xargs)
    size=$(lsblk -dn -o SIZE "$disk" | xargs)
    [[ -z "$model" ]] && model="Unknown"
    printf '%s\t%s\n' "$model" "$size"
}

# Suggest an unused mount point inside the CT for the given disk.
# Reads the CT config to collect already-used mp= paths, then returns
# the first free candidate: /mnt/disk_<devname>, /mnt/disk_<devname>_2, ...
_get_suggested_mount_point() {
    local ctid="$1"
    local disk="$2"
    local devname
    devname=$(basename "$disk")
    local base="/mnt/disk_${devname}"

    local used_mps
    used_mps=$(pct config "$ctid" 2>/dev/null | grep '^mp[0-9]*:' | \
               grep -oP 'mp=\K[^,]+' | sort)

    if ! grep -qxF "$base" <<< "$used_mps"; then
        echo "$base"; return
    fi
    local n=2
    while grep -qxF "${base}_${n}" <<< "$used_mps"; do
        ((n++))
    done
    echo "${base}_${n}"
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



CT_LIST=$(pct list | awk 'NR>1 {print $1, $3}')
if [ -z "$CT_LIST" ]; then
    dialog --backtitle "$BACKTITLE" \
           --title "$(translate "Error")" \
           --msgbox "$(translate "No CTs available in the system.")" $UI_MSG_H $UI_MSG_W
    exit 1
fi

# shellcheck disable=SC2086  # CT_LIST is intentionally word-split into dialog menu pairs
CTID=$(dialog --backtitle "$BACKTITLE" \
              --title "$(translate "Select CT for destination disk")" \
              --menu "$(translate "Select the CT to which you want to add disks:")" $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
              $CT_LIST \
              2>&1 >/dev/tty)

if [ -z "$CTID" ]; then
    dialog --backtitle "$BACKTITLE" \
           --title "$(translate "Error")" \
           --msgbox "$(translate "No CT was selected.")" $UI_MSG_H $UI_MSG_W
    exit 1
fi

CTID=$(echo "$CTID" | tr -d '"')

CT_STATUS=$(pct status "$CTID" | awk '{print $2}')
CT_RUNNING=false
[[ "$CT_STATUS" == "running" ]] && CT_RUNNING=true

# ── Check for unprivileged container — also a dialog, stays before show_proxmenux_logo ──
CONF_FILE="/etc/pve/lxc/$CTID.conf"
CONVERT_PRIVILEGED=false
if grep -q '^unprivileged: 1' "$CONF_FILE"; then
    if dialog --backtitle "$BACKTITLE" \
        --title "$(translate "Privileged Container")" \
        --yesno "\n\n$(translate "The selected container is unprivileged. A privileged container is required for direct device passthrough.")\\n\\n$(translate "Do you want to convert it to a privileged container now?")" $UI_YESNO_H $UI_YESNO_W; then
        CONVERT_PRIVILEGED=true
    else
        dialog --backtitle "$BACKTITLE" \
               --title "$(translate "Aborted")" \
               --msgbox "$(translate "Operation cancelled. Cannot continue with an unprivileged container.")" $UI_MSG_H $UI_MSG_W
        exit 1
    fi
fi

# ── TERMINAL PHASE 1 ──────────────────────────────────────────────────────────
show_proxmenux_logo
msg_title "$(translate "Import Disk to LXC")"
msg_ok "$(translate "CT $CTID selected successfully.")"

if [ "$CONVERT_PRIVILEGED" = true ]; then

    show_proxmenux_logo
    msg_title "$(translate "Import Disk to LXC")"

    CURRENT_CT_STATUS=$(pct status "$CTID" | awk '{print $2}')
    if [ "$CURRENT_CT_STATUS" == "running" ]; then
        msg_info "$(translate "Stopping container") $CTID..."
        pct shutdown "$CTID" &>/dev/null
        for i in {1..10}; do
            sleep 1
            [ "$(pct status "$CTID" | awk '{print $2}')" != "running" ] && break
        done
        if [ "$(pct status "$CTID" | awk '{print $2}')" == "running" ]; then
            msg_error "$(translate "Failed to stop the container.")"
            exit 1
        fi
        msg_ok "$(translate "Container stopped.")"
    fi

    cp "$CONF_FILE" "$CONF_FILE.bak"
    sed -i '/^unprivileged: 1/d' "$CONF_FILE"
    echo "unprivileged: 0" >> "$CONF_FILE"
    msg_ok "$(translate "Container successfully converted to privileged.")"

    if [ "$CT_RUNNING" = true ]; then
        msg_info "$(translate "Starting container") $CTID..."
        pct start "$CTID" &>/dev/null
        sleep 2
        if [ "$(pct status "$CTID" | awk '{print $2}')" != "running" ]; then
            msg_error "$(translate "Failed to start the container.")"
            CT_RUNNING=false
        else
            msg_ok "$(translate "Container started successfully.")"
        fi
    fi
fi

##########################################
msg_info "$(translate "Detecting available disks...")"

_refresh_host_storage_cache
# Read this CT's current config for the "already assigned to this CT" check
CT_CONFIG=$(pct config "$CTID" 2>/dev/null | grep -vE '^\s*#|^description:')

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

    if disk_referenced_in_config "$CT_CONFIG" "$DISK"; then
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
           --msgbox "$(translate "No disks available for this CT.")" $UI_MSG_H $UI_MSG_W
    exit 1
fi

stop_spinner

######################################################
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
    --checklist "$(translate "Select the disks you want to add:")" $UI_MENU_H $TOTAL_WIDTH $UI_MENU_LIST_H \
    "${FREE_DISKS[@]}" \
    2>&1 >/dev/tty)

if [ -z "$SELECTED" ]; then
    dialog --backtitle "$BACKTITLE" \
           --title "$(translate "Error")" \
           --msgbox "$(translate "No disks were selected.")" $UI_MSG_H $UI_MSG_W
    exit 1
fi

show_proxmenux_logo
msg_title "$(translate "Import Disk to LXC")"

msg_ok "$(translate "CT $CTID selected successfully.")"
msg_info "$(translate "Analyzing selected disks...")"



# ── DIALOG PHASE: collect config for each disk ────────────────────────────────
declare -a DISK_LIST=()
declare -a DISK_DESCRIPTIONS=()
declare -a DISK_MOUNT_POINTS=()
declare -a DISK_SKIP_FORMATS=()
declare -a DISK_FORMAT_TYPES=()
declare -a DISK_NEEDS_PARTITION=()
declare -a DISK_PARTITIONS=()
declare -a DISK_ASSIGNED_TOS=()
declare -a DISK_CURRENT_FSes=()

for DISK in $SELECTED; do
    DISK="${DISK//\"/}"
    DISK_INFO=$(get_disk_info "$DISK")

    ASSIGNED_TO=""
    RUNNING_CTS=""
    RUNNING_VMS=""

    while read -r CT_ID CT_NAME; do
        CT_CONFIG_RAW=$(pct config "$CT_ID" 2>/dev/null)
        if [[ "$CT_ID" =~ ^[0-9]+$ ]] && disk_referenced_in_config "$CT_CONFIG_RAW" "$DISK"; then
            ASSIGNED_TO+="CT $CT_ID $CT_NAME\n"
            CT_STATUS=$(pct status "$CT_ID" | awk '{print $2}')
            [[ "$CT_STATUS" == "running" ]] && RUNNING_CTS+="CT $CT_ID $CT_NAME\n"
        fi
    done < <(pct list | awk 'NR>1 {print $1, $3}')

    while read -r VM_ID VM_NAME; do
        VM_CONFIG_RAW=$(qm config "$VM_ID" 2>/dev/null)
        if [[ "$VM_ID" =~ ^[0-9]+$ ]] && disk_referenced_in_config "$VM_CONFIG_RAW" "$DISK"; then
            ASSIGNED_TO+="VM $VM_ID $VM_NAME\n"
            VM_STATUS=$(qm status "$VM_ID" | awk '{print $2}')
            [[ "$VM_STATUS" == "running" ]] && RUNNING_VMS+="VM $VM_ID $VM_NAME\n"
        fi
    done < <(qm list | awk 'NR>1 {print $1, $2}')


    stop_spinner
    if [ -n "$RUNNING_CTS" ] || [ -n "$RUNNING_VMS" ]; then
        dialog --backtitle "$BACKTITLE" \
               --title "$(translate "Disk In Use")" \
               --msgbox "$(translate "The disk") $DISK_INFO $(translate "is in use by the following running VM(s) or CT(s):")\\n$RUNNING_CTS$RUNNING_VMS\\n\\n$(translate "Stop them first and run this script again.")" $UI_RESULT_H $UI_RESULT_W
        continue
    fi

    if [ -n "$ASSIGNED_TO" ]; then
        if ! dialog --backtitle "$BACKTITLE" \
               --title "$(translate "Disk Already Assigned")" \
               --yesno "\n\n$(translate "The disk") $DISK_INFO $(translate "is already assigned to the following VM(s) or CT(s):")\\n$ASSIGNED_TO\\n\\n$(translate "Do you want to continue anyway?")" $UI_YESNO_H $UI_YESNO_W; then
            continue
        fi
    fi

    if lsblk "$DISK" | grep -q "raid" || grep -q "${DISK##*/}" /proc/mdstat; then
        dialog --backtitle "$BACKTITLE" \
               --title "$(translate "RAID Detected")" \
               --msgbox "\n$(translate "The disk") $DISK_INFO $(translate "appears to be part of a") RAID. $(translate "For security reasons, the system cannot format it.")\\n\\n$(translate "If you are sure you want to use it, please remove the") RAID metadata $(translate "or format it manually using external tools.")\\n\\n$(translate "After that, run this script again to add it.")" $UI_RESULT_H $UI_RESULT_W
        continue
    fi

    # 1. Detect current partition/FS state
    PARTITION=$(lsblk -rno NAME "$DISK" | awk -v disk="$(basename "$DISK")" '$1 != disk {print $1; exit}')
    SKIP_FORMAT=false
    NEEDS_PARTITION=false

    if [ -n "$PARTITION" ]; then
        PARTITION="/dev/$PARTITION"
        CURRENT_FS=$(lsblk -no FSTYPE "$PARTITION" | xargs)
    else
        CURRENT_FS=$(lsblk -no FSTYPE "$DISK" | xargs)
        PARTITION="$DISK"
    fi

    # 2. Ask what to do with this disk
    if [ -n "$CURRENT_FS" ]; then
        # Disk already has a filesystem — offer use-as-is or reformat
        DISK_ACTION=$(dialog --backtitle "$BACKTITLE" \
            --title "$(translate "Disk Setup")" \
            --menu "$(translate "Disk") $DISK_INFO\n$(translate "Detected filesystem:") $CURRENT_FS\n\n$(translate "What do you want to do?")" \
            $UI_SHORT_MENU_H $UI_SHORT_MENU_W $UI_SHORT_MENU_LIST_H \
            "use"    "$(translate "Use as-is — keep data and filesystem")" \
            "format" "$(translate "Format — erase and create new filesystem")" \
            2>&1 >/dev/tty)
        [ -z "$DISK_ACTION" ] && continue
    else
        DISK_ACTION="format"
    fi

    FORMAT_TYPE=""
    if [ "$DISK_ACTION" = "use" ]; then
        SKIP_FORMAT=true
        FORMAT_TYPE="$CURRENT_FS"
        # PARTITION already set correctly by the detection block above — do not modify
    else
        # 3. Ask desired filesystem for format
        FORMAT_TYPE=$(dialog --backtitle "$BACKTITLE" \
            --title "$(translate "Select Filesystem")" \
            --menu "$(translate "Select the filesystem for") $DISK_INFO:" \
            $UI_SHORT_MENU_H $UI_SHORT_MENU_W $UI_SHORT_MENU_LIST_H \
            "ext4"  "$(translate "ext4  — recommended, most compatible")" \
            "xfs"   "$(translate "xfs   — better for large files")" \
            "btrfs" "$(translate "btrfs — snapshots and compression")" \
            2>&1 >/dev/tty)
        [ -z "$FORMAT_TYPE" ] && continue

        # Check if already the right FS — otherwise need partition + format
        if [ "$CURRENT_FS" = "$FORMAT_TYPE" ]; then
            SKIP_FORMAT=true
        elif [ -z "$CURRENT_FS" ] && [ "$PARTITION" = "$DISK" ]; then
            NEEDS_PARTITION=true
            PARTITION=""
        fi

        # 4. Warn if data will be erased
        if [ "$SKIP_FORMAT" != true ]; then
            if ! dialog --backtitle "$BACKTITLE" \
                   --title "$(translate "WARNING")" \
                   --yesno "\n$(translate "WARNING: This will FORMAT the disk") $DISK_INFO $(translate "as") $FORMAT_TYPE.\\n\\n$(translate "ALL DATA ON THIS DISK WILL BE PERMANENTLY LOST!")\\n\\n$(translate "Are you sure?")" \
                   $UI_YESNO_H $UI_YESNO_W; then
                continue
            fi
        fi
    fi

    # 5. Ask mount point — suggest unique path based on device name
    SUGGESTED_MP=$(_get_suggested_mount_point "$CTID" "$DISK")
    MOUNT_POINT=$(dialog --backtitle "$BACKTITLE" \
                         --title "$(translate "Mount Point")" \
                         --inputbox "$(translate "Enter the mount point inside the CT for") $DISK_INFO:" \
                         $UI_MSG_H $UI_MSG_W "$SUGGESTED_MP" \
                         2>&1 >/dev/tty)

    if [ -z "$MOUNT_POINT" ]; then
        dialog --backtitle "$BACKTITLE" \
               --title "$(translate "Error")" \
               --msgbox "$(translate "No mount point was specified.")" $UI_MSG_H $UI_MSG_W
        continue
    fi

    DISK_LIST+=("$DISK")
    DISK_DESCRIPTIONS+=("$DISK_INFO")
    DISK_MOUNT_POINTS+=("$MOUNT_POINT")
    DISK_SKIP_FORMATS+=("$SKIP_FORMAT")
    DISK_FORMAT_TYPES+=("$FORMAT_TYPE")
    DISK_NEEDS_PARTITION+=("$NEEDS_PARTITION")
    DISK_PARTITIONS+=("$PARTITION")
    DISK_ASSIGNED_TOS+=("$ASSIGNED_TO")
    DISK_CURRENT_FSes+=("$CURRENT_FS")
done

if [ "${#DISK_LIST[@]}" -eq 0 ]; then
    show_proxmenux_logo
    msg_title "$(translate "Import Disk to LXC")"
    msg_warn "$(translate "No disks were configured for processing.")"
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
    exit 0
fi

# ── TERMINAL PHASE: execute all disk operations ───────────────────────────────
show_proxmenux_logo
msg_title "$(translate "Import Disk to LXC")"
msg_ok "$(translate "CT $CTID selected successfully.")"
msg_ok "$(translate "Disks to process:") ${#DISK_LIST[@]}"
for i in "${!DISK_LIST[@]}"; do
    IFS=$'\t' read -r _desc_model _desc_size <<< "${DISK_DESCRIPTIONS[$i]}"
    echo -e "${TAB}${BL}${DISK_LIST[$i]}  $_desc_model  $_desc_size${CL}"
done
echo ""

DISKS_ADDED=0

for i in "${!DISK_LIST[@]}"; do
    DISK="${DISK_LIST[$i]}"
    MOUNT_POINT="${DISK_MOUNT_POINTS[$i]}"
    SKIP_FORMAT="${DISK_SKIP_FORMATS[$i]}"
    FORMAT_TYPE="${DISK_FORMAT_TYPES[$i]}"
    NEEDS_PARTITION="${DISK_NEEDS_PARTITION[$i]}"
    PARTITION="${DISK_PARTITIONS[$i]}"
    ASSIGNED_TO="${DISK_ASSIGNED_TOS[$i]}"
    CURRENT_FS="${DISK_CURRENT_FSes[$i]}"
    DISK_INFO=$(get_disk_info "$DISK")

    echo ""
    msg_ok "$(translate "Disk:") $DISK → $MOUNT_POINT"

    if [ "$NEEDS_PARTITION" = true ]; then
        msg_info "$(translate "Creating partition table and partition...")"
        if ! parted -s "$DISK" mklabel gpt mkpart primary 0% 100% >/dev/null 2>&1; then
            msg_error "$(translate "Failed to create partition table on disk") $DISK_INFO."
            continue
        fi
        sleep 2
        partprobe "$DISK" 2>/dev/null || true
        udevadm settle 2>/dev/null || true
        # Wait up to 5 s for by-id symlinks to be created by udev
        for _i in {1..5}; do
            for _p in /dev/disk/by-id/*; do
                [[ "$(readlink -f "$_p" 2>/dev/null)" == "$DISK"* ]] && break 2
            done
            sleep 1
        done
        PARTITION=$(lsblk -rno NAME "$DISK" | awk -v disk="$(basename "$DISK")" '$1 != disk {print $1; exit}')
        if [ -n "$PARTITION" ]; then
            PARTITION="/dev/$PARTITION"
            msg_ok "$(translate "Partition created:") $PARTITION"
        else
            msg_error "$(translate "Failed to detect partition on disk") $DISK_INFO."
            continue
        fi
    fi

    if [ "$SKIP_FORMAT" != true ]; then
        msg_info "$(translate "Formatting partition") $PARTITION $(translate "with") $FORMAT_TYPE..."
        if ! case "$FORMAT_TYPE" in
            "ext4")  mkfs.ext4 -F "$PARTITION" >/dev/null 2>&1 ;;
            "xfs")   mkfs.xfs -f "$PARTITION"  >/dev/null 2>&1 ;;
            "btrfs") mkfs.btrfs -f "$PARTITION" >/dev/null 2>&1 ;;
        esac; then
            msg_error "$(translate "Failed to format partition") $PARTITION $(translate "with") $FORMAT_TYPE."
            continue
        fi
        msg_ok "$(translate "Partition") $PARTITION $(translate "successfully formatted with") $FORMAT_TYPE."
        partprobe "$DISK" >/dev/null 2>&1 || true
        sleep 2
    else
        msg_ok "$(translate "Disk already has") $FORMAT_TYPE $(translate "filesystem. Skipping format.")"
    fi

    INDEX=0
    while pct config "$CTID" | grep -q "mp${INDEX}:"; do
        ((INDEX++))
    done

    FS_PKG=""
    FS_BIN=""
    [[ "$FORMAT_TYPE" == "xfs" ]]   && FS_PKG="xfsprogs"   && FS_BIN="xfs_repair"
    [[ "$FORMAT_TYPE" == "btrfs" ]] && FS_PKG="btrfs-progs" && FS_BIN="btrfsck"

    if [[ -n "$FS_PKG" && -n "$FS_BIN" ]]; then
        if [ "$CT_RUNNING" = true ]; then
            if ! pct exec "$CTID" -- sh -c "command -v $FS_BIN >/dev/null 2>&1"; then
                msg_info "$(translate "Installing required tools for $FORMAT_TYPE in CT $CTID...")"
                if install_fs_tools_in_ct "$CTID" "$FS_PKG"; then
                    msg_ok "$(translate "Required tools for $FORMAT_TYPE installed in CT $CTID.")"
                else
                    msg_warn "$(translate "Could not install") $FS_PKG $(translate "automatically. Install it manually inside the container.")"
                fi
            fi
        else
            # CT is stopped — ask via whiptail (terminal-safe, no dialog on top of output)
            if whiptail --backtitle "$BACKTITLE" \
                        --title "$(translate "Filesystem Tools Required")" \
                        --yesno "$(translate "The filesystem") $FORMAT_TYPE $(translate "requires the package") $FS_PKG $(translate "installed inside CT") $CTID.\n\n$(translate "The container is currently stopped. Do you want to start it now to install the package?")\n\n$(translate "If you choose No, install") $FS_PKG $(translate "manually inside the container before starting it.")" \
                        $UI_YESNO_H $UI_YESNO_W; then
                msg_info "$(translate "Starting CT") $CTID..."
                pct start "$CTID" &>/dev/null
                sleep 2
                if [ "$(pct status "$CTID" | awk '{print $2}')" != "running" ]; then
                    msg_error "$(translate "Failed to start CT") $CTID. $(translate "Install") $FS_PKG $(translate "manually inside the container.")"
                else
                    msg_ok "$(translate "CT") $CTID $(translate "started.")"
                    CT_RUNNING=true
                    msg_info "$(translate "Installing") $FS_PKG $(translate "in CT") $CTID..."
                    if install_fs_tools_in_ct "$CTID" "$FS_PKG"; then
                        msg_ok "$FS_PKG $(translate "installed in CT") $CTID."
                    else
                        msg_warn "$(translate "Could not install") $FS_PKG $(translate "automatically. Install it manually inside the container.")"
                    fi
                fi
            else
                msg_warn "$(translate "Manual install required inside CT") $CTID:"
                echo -e "${DGN}${TAB}  Debian/Ubuntu:${CL} ${BL}apt-get install -y $FS_PKG${CL}"
                echo -e "${DGN}${TAB}  Arch:${CL}          ${BL}pacman -S --noconfirm $FS_PKG${CL}"
                echo -e "${DGN}${TAB}  Alpine:${CL}        ${BL}apk add $FS_PKG${CL}"
                echo
            fi
        fi
    fi

    PERSISTENT_PARTITION=$(get_preferred_disk_path "$PARTITION")

    msg_info "$(translate "Applying passthrough to CT") $CTID..."
    if [ "$FORMAT_TYPE" == "xfs" ]; then
        RESULT=$(pct set "$CTID" -mp${INDEX} "$PERSISTENT_PARTITION,mp=$MOUNT_POINT,backup=0,ro=0" 2>&1)
    else
        RESULT=$(pct set "$CTID" -mp${INDEX} "$PERSISTENT_PARTITION,mp=$MOUNT_POINT,backup=0,ro=0,acl=1" 2>&1)
    fi
    SET_STATUS=$?

    if [ $SET_STATUS -eq 0 ]; then
        msg_ok "$(translate "Disk assigned at") $MOUNT_POINT $(translate "using") $PERSISTENT_PARTITION"
        [[ -n "$ASSIGNED_TO" ]] && msg_warn "$(translate "WARNING: This disk is also assigned to:") $(echo -e "$ASSIGNED_TO" | tr '\n' ' ')"

        # Verify disk is accessible inside the CT
        if [ "$CT_RUNNING" = true ]; then
            msg_info "$(translate "Verifying disk accessibility in CT") $CTID..."
            sleep 1
            if pct exec "$CTID" -- sh -c "mountpoint -q '$MOUNT_POINT' || [ -d '$MOUNT_POINT' ]" 2>/dev/null; then
                msg_ok "$(translate "Disk verified and accessible inside CT at") $MOUNT_POINT"
            fi
        fi

        ((DISKS_ADDED++))
    else
        msg_error "$(translate "Could not add disk") $DISK_INFO $(translate "to CT") $CTID. $(translate "Error:") $RESULT"
    fi
done

echo ""
if [ "$DISKS_ADDED" -gt 0 ]; then
    msg_ok "$(translate "Completed.") $DISKS_ADDED $(translate "disk(s) added to CT") $CTID."
else
    msg_warn "$(translate "No disks were added.")"
fi
msg_success "$(translate "Press Enter to return to menu...")"
read -r
exit 0
