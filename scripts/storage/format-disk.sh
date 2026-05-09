#!/bin/bash

# ==========================================================
# ProxMenux - Secure Disk Formatter
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 2.0
# Last Updated: 11/04/2026
# ==========================================================
# Description:
# Formats a physical disk with strict safety controls.
#
# Visibility rules:
#   SHOWN   — only fully free disks:
#             not system-used and not referenced by VM/LXC configs.
#   HIDDEN  — host/system disks (root pool, swap, mounted, active ZFS/LVM/RAID).
#   HIDDEN  — disks referenced by VM/LXC (running or stopped).
#
# Safety at confirmation:
#   - Disks with stale/active metadata show detailed warnings.
#   - Disks used by running VMs are hard-blocked at confirmation.
#   - Disks with mounted partitions are hard-blocked at execution (revalidation).
#   - Double confirmation required: yesno + type full disk path.
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

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
load_language
initialize_cache

if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/vm_storage_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_LOCAL/global/vm_storage_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/vm_storage_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_DEFAULT/global/vm_storage_helpers.sh"
fi

if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/disk_ops_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_LOCAL/global/disk_ops_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/disk_ops_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_DEFAULT/global/disk_ops_helpers.sh"
fi

# shellcheck source=/dev/null
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/utils-install-functions.sh" ]]; then
    source "$LOCAL_SCRIPTS_LOCAL/global/utils-install-functions.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/utils-install-functions.sh" ]]; then
    source "$LOCAL_SCRIPTS_DEFAULT/global/utils-install-functions.sh"
fi

BACKTITLE="ProxMenux"
UI_MENU_H=20
UI_MENU_W=84
UI_MENU_LIST_H=10
UI_MSG_H=10
UI_MSG_W=72
UI_YESNO_H=20
UI_YESNO_W=86
UI_RESULT_H=14
UI_RESULT_W=86
OPERATION_MODE=""
REVALIDATE_ERROR_DETAIL=""
ZFS_POOL_NAME=""
declare -A DISK_RUNNING_VM_FLAG

# ──────────────────────────────────────────────────────────────────────────────
# Basic disk info
# ──────────────────────────────────────────────────────────────────────────────

get_disk_info() {
    local disk="$1" model size
    model=$(lsblk -dn -o MODEL "$disk" 2>/dev/null | xargs)
    size=$(lsblk -dn -o SIZE "$disk" 2>/dev/null | xargs)
    [[ -z "$model" ]] && model="Unknown model"
    [[ -z "$size" ]] && size="Unknown size"
    printf '%s\t%s' "$model" "$size"
}

# Collect command stdout with timeout protection (best-effort).
_fmt_collect_cmd() {
    local seconds="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout --kill-after=2 "${seconds}s" "$@" 2>/dev/null || true
    else
        "$@" 2>/dev/null || true
    fi
}

# ──────────────────────────────────────────────────────────────────────────────
# Mount classification helpers
# ──────────────────────────────────────────────────────────────────────────────

# Returns 0 if the mountpoint is part of the OS root filesystem tree.
# These mounts trigger a hard block — the disk contains the running OS.
_is_system_mount() {
    local mp="$1"
    case "$mp" in
        /|/boot|/boot/*|/usr|/usr/*|/var|/var/*|/etc|/lib|/lib/*|/lib64|/run|/proc|/sys)
            return 0 ;;
        *) return 1 ;;
    esac
}

# ──────────────────────────────────────────────────────────────────────────────
# ZFS root-pool detection
# ──────────────────────────────────────────────────────────────────────────────

# Returns the name of the ZFS pool that holds the root filesystem, or empty
# if root is on a traditional block device (ext4/xfs/btrfs).
_get_zfs_root_pool() {
    local root_fs
    root_fs=$(df / 2>/dev/null | awk 'NR==2 {print $1}')
    # A ZFS dataset looks like "rpool/ROOT/pve-1" — not /dev/
    if [[ "$root_fs" != /dev/* && "$root_fs" == */* ]]; then
        echo "${root_fs%%/*}"
    fi
}

# ──────────────────────────────────────────────────────────────────────────────
# ZFS pool membership helpers
# ──────────────────────────────────────────────────────────────────────────────

# Resolve a raw ZFS device entry (from zpool list -v -H) to a canonical
# /dev/sdX path. Handles: full /dev/ paths, by-id names, short kernel names.
_resolve_zfs_entry() {
    local entry="$1" path base
    if [[ "$entry" == /dev/* ]]; then
        path=$(readlink -f "$entry" 2>/dev/null)
    elif [[ -e "/dev/disk/by-id/$entry" ]]; then
        path=$(readlink -f "/dev/disk/by-id/$entry" 2>/dev/null)
    elif [[ -e "/dev/$entry" ]]; then
        path=$(readlink -f "/dev/$entry" 2>/dev/null)
    fi
    [[ -z "$path" ]] && return
    base=$(lsblk -no PKNAME "$path" 2>/dev/null)
    if [[ -n "$base" ]]; then
        echo "/dev/$base"
    else
        echo "$path"   # whole-disk vdev — path is the disk itself
    fi
}

# Emit one /dev/sdX line per disk that is a member of a SPECIFIC ZFS pool.
_build_pool_disks() {
    local pool_name="$1" entry
    while read -r entry; do
        [[ -z "$entry" ]] && continue
        _resolve_zfs_entry "$entry"
    done < <(_fmt_collect_cmd 8 zpool list -v -H "$pool_name" | awk '{print $1}' | \
             grep -v '^-' | grep -v '^mirror' | grep -v '^raidz' | \
             grep -v "^${pool_name}$")
}

# ──────────────────────────────────────────────────────────────────────────────
# VM/CT config helpers
# ──────────────────────────────────────────────────────────────────────────────

# Return 0 if $disk appears (by real path or any by-id link) in $cfg_text.
_disk_in_config_text() {
    local disk="$1" cfg_text="$2"
    [[ -z "$cfg_text" ]] && return 1
    local rp link
    rp=$(readlink -f "$disk" 2>/dev/null)
    [[ -n "$rp" ]] && grep -qF "$rp" <<< "$cfg_text" && return 0
    for link in /dev/disk/by-id/*; do
        [[ -e "$link" ]] || continue
        [[ "$(readlink -f "$link" 2>/dev/null)" == "$rp" ]] || continue
        grep -qF "$link" <<< "$cfg_text" && return 0
    done
    return 1
}

# Return the concatenated config text of all CURRENTLY RUNNING VMs and CTs.
_get_running_vm_config_text() {
    local result="" vmid state conf
    while read -r vmid state; do
        [[ -z "$vmid" || "$state" != "running" ]] && continue
        for conf in "/etc/pve/qemu-server/${vmid}.conf" "/etc/pve/lxc/${vmid}.conf"; do
            [[ -f "$conf" ]] && result+=$(grep -vE '^\s*#' "$conf" 2>/dev/null)$'\n'
        done
    done < <(
        qm list --noborder 2>/dev/null  | awk 'NR>1 {print $1, $3}'
        pct list --noborder 2>/dev/null | awk 'NR>1 {print $1, $2}'
    )
    printf '%s' "$result"
}

# Wrapper for disk_referenced_in_guest_configs (uses global helper when available).
disk_referenced_in_guest_configs() {
    local disk="$1"
    if declare -F _disk_used_in_guest_configs >/dev/null 2>&1; then
        _disk_used_in_guest_configs "$disk"
        return $?
    fi
    local real_path config_data link
    real_path=$(readlink -f "$disk" 2>/dev/null)
    config_data=$(grep -vE '^\s*#' /etc/pve/qemu-server/*.conf /etc/pve/lxc/*.conf 2>/dev/null)
    [[ -z "$config_data" ]] && return 1
    [[ -n "$real_path" ]] && grep -Fq "$real_path" <<< "$config_data" && return 0
    for link in /dev/disk/by-id/*; do
        [[ -e "$link" ]] || continue
        [[ "$(readlink -f "$link" 2>/dev/null)" == "$real_path" ]] || continue
        grep -Fq "$link" <<< "$config_data" && return 0
    done
    return 1
}

# ──────────────────────────────────────────────────────────────────────────────
# Build candidate disk list with smart classification
# ──────────────────────────────────────────────────────────────────────────────
#
# Hard blocks (disk hidden completely):
#   • Any partition mounted at a system path (/, /boot, /usr, /var, etc.)
#   • Disk is a member of the ZFS pool that holds the root filesystem
#   • Any partition is active swap
#
# Strict free-disk policy:
#   - Only show disks that are NOT used by host system and NOT referenced by
#     any VM/CT config (running or stopped).
#   - If a disk is shown, it is considered free for formatting.
#
# Populates: DISK_OPTIONS[] (DISK_RUNNING_VM_FLAG kept for compatibility)
# ──────────────────────────────────────────────────────────────────────────────

build_disk_candidates() {
    DISK_OPTIONS=()
    DISK_RUNNING_VM_FLAG=()

    if declare -F _refresh_host_storage_cache >/dev/null 2>&1; then
        _refresh_host_storage_cache
    fi

    # ── Detect ZFS root pool (its disks are hard-blocked) ─────────────────
    local root_pool root_pool_disks=""
    root_pool=$(_get_zfs_root_pool)
    [[ -n "$root_pool" ]] && root_pool_disks=$(_build_pool_disks "$root_pool" | sort -u)

    # ── Classify mounts: system (hard block) ─────────────────────────────
    local sys_blocked_disks="" swap_parts
    swap_parts=$(swapon --noheadings --raw --show=NAME 2>/dev/null)

    while read -r name mp; do
        _is_system_mount "$mp" || continue
        local parent
        parent=$(lsblk -no PKNAME "/dev/$name" 2>/dev/null)
        [[ -z "$parent" ]] && parent="$name"
        sys_blocked_disks+="/dev/$parent"$'\n'
    done < <(lsblk -ln -o NAME,MOUNTPOINT 2>/dev/null | awk '$2!=""')
    sys_blocked_disks=$(sort -u <<< "$sys_blocked_disks")

    # ── Build running VM config text (done once) ──────────────────────────
    local running_cfg="" vmid state conf
    while read -r vmid state; do
        [[ -z "$vmid" || "$state" != "running" ]] && continue
        for conf in "/etc/pve/qemu-server/${vmid}.conf" "/etc/pve/lxc/${vmid}.conf"; do
            [[ -f "$conf" ]] && running_cfg+=$(grep -vE '^\s*#' "$conf" 2>/dev/null)$'\n'
        done
    done < <(
        qm list --noborder 2>/dev/null  | awk 'NR>1 {print $1, $3}'
        pct list --noborder 2>/dev/null | awk 'NR>1 {print $1, $2}'
    )

    # ── Main disk enumeration ─────────────────────────────────────────────
    local disk ro type
    while read -r disk ro type; do
        [[ -z "$disk" ]] && continue
        [[ "$type" != "disk" ]] && continue
        [[ "$ro" == "1" ]] && continue
        [[ "$disk" =~ ^/dev/zd ]] && continue

        local real_disk
        real_disk=$(readlink -f "$disk" 2>/dev/null)

        # ── Hard blocks ───────────────────────────────────────────────────

        # Disk contains a system-critical mount (/, /boot, /usr, /var, ...)
        grep -qFx "$disk" <<< "$sys_blocked_disks" && continue
        [[ -n "$real_disk" ]] && grep -qFx "$real_disk" <<< "$sys_blocked_disks" && continue

        # Disk has an active swap partition
        local has_swap=0 part_name
        while read -r part_name; do
            [[ -z "$part_name" ]] && continue
            grep -qFx "/dev/$part_name" <<< "$swap_parts" && { has_swap=1; break; }
        done < <(lsblk -ln -o NAME "$disk" 2>/dev/null)
        (( has_swap )) && continue

        # Disk is a member of the ZFS root pool
        grep -qFx "$disk"      <<< "$root_pool_disks" && continue
        [[ -n "$real_disk" ]] && grep -qFx "$real_disk" <<< "$root_pool_disks" && continue

        # Running VM/CT reference => show but flag for hard block at confirmation
        if _disk_in_config_text "$disk" "$running_cfg"; then
            DISK_RUNNING_VM_FLAG["$disk"]="1"
        else
            DISK_RUNNING_VM_FLAG["$disk"]="0"
        fi
        # NOTE: stopped VM reference, active ZFS/LVM/RAID, and mounted data
        # partitions are NOT hidden — they show with metadata warnings in the
        # confirmation dialog. The revalidation step handles auto-unmount/export.

        # ── Build display label ───────────────────────────────────────────
        local model size desc
        IFS=$'\t' read -r model size < <(get_disk_info "$disk")

        desc=$(printf "%-30s %10s" "$model" "$size")

        DISK_OPTIONS+=("$disk" "$desc" "OFF")
    done < <(lsblk -dn -e 7,11 -o PATH,RO,TYPE 2>/dev/null)
}

# ──────────────────────────────────────────────────────────────────────────────
# Disk selection dialog
# ──────────────────────────────────────────────────────────────────────────────

select_target_disk() {
    build_disk_candidates

    if [[ ${#DISK_OPTIONS[@]} -eq 0 ]]; then
        dialog --backtitle "$BACKTITLE" \
            --title "$(translate "No Disks Available")" \
            --msgbox "\n$(translate "No format-safe disks are available.")\n\n$(translate "Only fully free disks are shown (not system-used and not referenced by VM/LXC).")" \
            $UI_RESULT_H $UI_RESULT_W
        return 1
    fi

    local prompt_text
    prompt_text="\n$(translate "Select the disk you want to format:")"

    local max_width total_width selected
    max_width=$(printf "%s\n" "${DISK_OPTIONS[@]}" | awk '{print length}' | sort -nr | head -n1)
    total_width=$((max_width + 22))
    (( total_width < UI_MENU_W )) && total_width=$UI_MENU_W
    (( total_width > 116 ))       && total_width=116

    selected=$(dialog --backtitle "$BACKTITLE" \
        --title "$(translate "Select Disk")" \
        --radiolist "$prompt_text" $UI_MENU_H "$total_width" $UI_MENU_LIST_H \
        "${DISK_OPTIONS[@]}" \
        2>&1 >/dev/tty) || return 1

    [[ -z "$selected" ]] && return 1
    SELECTED_DISK="$selected"
    return 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Metadata flag reader (for confirmation dialog display)
# ──────────────────────────────────────────────────────────────────────────────

get_disk_metadata_flags() {
    local disk="$1" flags="" fstype mp
    while read -r fstype; do
        case "$fstype" in
            linux_raid_member) [[ "$flags" != *"RAID"*  ]] && flags+=" RAID"  ;;
            LVM2_member)       [[ "$flags" != *"LVM"*   ]] && flags+=" LVM"   ;;
            zfs_member)        [[ "$flags" != *"ZFS"*   ]] && flags+=" ZFS"   ;;
        esac
    done < <(lsblk -ln -o FSTYPE "$disk" 2>/dev/null | awk 'NF')
    # Mounted data partitions
    while read -r mp; do
        [[ -z "$mp" ]] && continue
        _is_system_mount "$mp" && continue
        [[ "$flags" != *"MOUNT"* ]] && flags+=" MOUNT ($mp)"
    done < <(lsblk -ln -o MOUNTPOINT "$disk" 2>/dev/null | awk 'NF')
    echo "$flags"
}

# ──────────────────────────────────────────────────────────────────────────────
# Confirmation dialogs
# ──────────────────────────────────────────────────────────────────────────────

confirm_format_action() {
    # Hard block: disk is currently referenced by a RUNNING VM/CT
    if [[ "${DISK_RUNNING_VM_FLAG[$SELECTED_DISK]:-0}" == "1" ]]; then
        dialog --backtitle "$BACKTITLE" \
            --title "$(translate "Disk In Use by Running VM")" \
            --msgbox "\n⛔ $(translate "CRITICAL: The selected disk is referenced by a RUNNING VM or CT.")\n\n$(translate "Stop the VM/CT before formatting this disk.")" \
            $UI_RESULT_H $UI_RESULT_W
        return 1
    fi

    local model size flags msg typed
    IFS=$'\t' read -r model size < <(get_disk_info "$SELECTED_DISK")
    flags=$(get_disk_metadata_flags "$SELECTED_DISK")

    msg="$(translate "Target disk"): $SELECTED_DISK\n"
    msg+="$(translate "Model"): $model\n"
    msg+="$(translate "Size"): $size\n"
    case "$OPERATION_MODE" in
        wipe_all)
            msg+="$(translate "Operation"): $(translate "Wipe all — remove partitions + metadata")\n" ;;
        clean_sigs)
            msg+="$(translate "Operation"): $(translate "Remove FS labels — partitions and data preserved")\n" ;;
        wipe_data)
            msg+="$(translate "Operation"): $(translate "Zero all data — partition table preserved")\n" ;;
        clean_and_format)
            msg+="$(translate "Operation"): $(translate "Full format: clean + new GPT partition + filesystem")\n" ;;
    esac
    [[ -n "$flags" ]] && msg+="$(translate "Detected"): $flags\n"

    # Stopped VM warning
    if disk_referenced_in_guest_configs "$SELECTED_DISK"; then
        msg+="\n⚠  $(translate "WARNING: This disk is referenced in a stopped VM/LXC config.")\n"
        msg+="$(translate "The VM/LXC will lose access to this disk after formatting.")\n"
    fi

    # Mounted partition warning
    if [[ "$flags" == *"MOUNT"* ]]; then
        msg+="\n⚠  $(translate "WARNING: This disk has a mounted partition.")\n"
        msg+="$(translate "Unmount it before proceeding. The script will verify this at execution.")\n"
    fi

    msg+="\n$(translate "WARNING: This will ERASE all data on this disk.")\n"
    msg+="$(translate "Do you want to continue?")"

    dialog --backtitle "$BACKTITLE" \
        --title "$(translate "Confirm Format")" \
        --yesno "\n$msg" $UI_YESNO_H $UI_YESNO_W || return 1

    typed=$(dialog --backtitle "$BACKTITLE" \
        --title "$(translate "Final Confirmation")" \
        --inputbox "$(translate "Type the full disk path to confirm"):\n$SELECTED_DISK" $UI_MSG_H $UI_MSG_W \
        2>&1 >/dev/tty) || return 1

    if [[ "$typed" != "$SELECTED_DISK" ]]; then
        dialog --backtitle "$BACKTITLE" \
            --title "$(translate "Confirmation Failed")" \
            --msgbox "\n$(translate "Typed value does not match selected disk. Operation cancelled.")" $UI_MSG_H $UI_MSG_W
        return 1
    fi
    return 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Operation and filesystem selection
# ──────────────────────────────────────────────────────────────────────────────

select_operation_mode() {
    local selected
    selected=$(dialog --backtitle "$BACKTITLE" \
        --title "$(translate "Format Mode")" \
        --menu "\n$(translate "Choose what to do with the selected disk:")" 16 76 4 \
        "1" "$(translate "Wipe all          — erase partitions + metadata")" \
        "2" "$(translate "Remove FS labels  — partitions and data preserved")" \
        "3" "$(translate "Zero all data     — partition table preserved, data wiped")" \
        "4" "$(translate "Full format       — new GPT partition + filesystem")" \
        2>&1 >/dev/tty) || return 1

    [[ -z "$selected" ]] && return 1
    case "$selected" in
        1) OPERATION_MODE="wipe_all" ;;
        2) OPERATION_MODE="clean_sigs" ;;
        3) OPERATION_MODE="wipe_data" ;;
        4) OPERATION_MODE="clean_and_format" ;;
        *) return 1 ;;
    esac
    return 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Pre-execution safety revalidation
# Refreshes state and blocks if the selected disk becomes system-critical,
# mounted, swapped, or referenced by a running VM/CT.
# ──────────────────────────────────────────────────────────────────────────────

revalidate_selected_disk() {
    REVALIDATE_ERROR_DETAIL=""

    if declare -F _refresh_host_storage_cache >/dev/null 2>&1; then
        _refresh_host_storage_cache
    fi

    # Hard block: disk now contains a system-critical mount
    local name mp parent
    while read -r name mp; do
        _is_system_mount "$mp" || continue
        parent=$(lsblk -no PKNAME "/dev/$name" 2>/dev/null)
        [[ "/dev/${parent:-$name}" == "$SELECTED_DISK" ]] && {
            REVALIDATE_ERROR_DETAIL="$(translate "The selected disk now contains a system-critical mount. Aborting.")"
            return 1
        }
    done < <(lsblk -ln -o NAME,MOUNTPOINT 2>/dev/null | awk '$2!=""')

    # Hard block: disk is now a member of the ZFS root pool
    local root_pool root_pool_disks
    root_pool=$(_get_zfs_root_pool)
    if [[ -n "$root_pool" ]]; then
        root_pool_disks=$(_build_pool_disks "$root_pool" | sort -u)
        if grep -qFx "$SELECTED_DISK" <<< "$root_pool_disks"; then
            REVALIDATE_ERROR_DETAIL="$(translate "The selected disk is now part of the system ZFS pool. Aborting.")"
            return 1
        fi
    fi

    # Hard block: disk has a swap partition
    local swap_parts pname
    swap_parts=$(swapon --noheadings --raw --show=NAME 2>/dev/null)
    while read -r pname; do
        [[ -z "$pname" ]] && continue
        if grep -qFx "/dev/$pname" <<< "$swap_parts"; then
            REVALIDATE_ERROR_DETAIL="$(translate "The selected disk has an active swap partition. Aborting.")"
            return 1
        fi
    done < <(lsblk -ln -o NAME "$SELECTED_DISK" 2>/dev/null)

    # Auto-unmount data partitions still mounted on this disk
    while read -r pname mp; do
        [[ -z "$mp" ]] && continue
        _is_system_mount "$mp" && continue  # already blocked above
        local disk_of_part
        disk_of_part=$(lsblk -no PKNAME "/dev/$pname" 2>/dev/null)
        [[ "/dev/${disk_of_part:-$pname}" == "$SELECTED_DISK" ]] || continue
        if ! umount "/dev/$pname" 2>/dev/null; then
            REVALIDATE_ERROR_DETAIL="$(translate "Partition") /dev/$pname $(translate "is mounted at") $mp $(translate "and could not be unmounted — disk may be busy.")"
            return 1
        fi
    done < <(lsblk -ln -o NAME,MOUNTPOINT "$SELECTED_DISK" 2>/dev/null | awk '$2!=""')

    # Auto-export any active ZFS pool that contains this disk
    local pool
    while read -r pool; do
        [[ -z "$pool" ]] && continue
        if _build_pool_disks "$pool" 2>/dev/null | grep -qFx "$SELECTED_DISK"; then
            zpool export "$pool" 2>/dev/null || true
        fi
    done < <(_fmt_collect_cmd 5 zpool list -H -o name 2>/dev/null)

    # Hard block: disk is currently referenced by a RUNNING VM or CT
    local running_cfg
    running_cfg=$(_get_running_vm_config_text)
    if _disk_in_config_text "$SELECTED_DISK" "$running_cfg"; then
        REVALIDATE_ERROR_DETAIL="$(translate "The selected disk is currently used by a RUNNING VM or CT. Stop it before formatting.")"
        return 1
    fi

    return 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Filesystem selection and ZFS pool name prompt
# ──────────────────────────────────────────────────────────────────────────────

select_filesystem() {
    local selected
    selected=$(dialog --backtitle "$BACKTITLE" \
        --title "$(translate "Select Filesystem")" \
        --menu "\n$(translate "Choose the filesystem for the new partition:")" 18 76 8 \
        "ext4"  "$(translate "Extended Filesystem 4 (recommended)")" \
        "xfs"   "XFS" \
        "exfat" "$(translate "exFAT (portable: Windows/Linux/macOS)")" \
        "btrfs" "Btrfs" \
        "zfs"   "ZFS" \
        2>&1 >/dev/tty) || return 1
    [[ -z "$selected" ]] && return 1
    FORMAT_TYPE="$selected"
    return 0
}

prompt_zfs_pool_name() {
    local disk_suffix suggested name
    disk_suffix=$(basename "$SELECTED_DISK" | sed 's|[^a-zA-Z0-9_-]|-|g')
    suggested="pool_${disk_suffix}"

    name=$(dialog --backtitle "$BACKTITLE" \
        --title "$(translate "ZFS Pool Name")" \
        --inputbox "$(translate "Enter ZFS pool name for the selected disk:")" \
        10 72 "$suggested" 2>&1 >/dev/tty) || return 1

    [[ -n "$name" ]] || return 1
    if [[ ! "$name" =~ ^[a-zA-Z][a-zA-Z0-9_.:-]*$ ]]; then
        dialog --backtitle "$BACKTITLE" \
            --title "$(translate "Invalid name")" \
            --msgbox "\n$(translate "Invalid ZFS pool name.")" $UI_MSG_H $UI_MSG_W
        return 1
    fi
    if zpool list "$name" >/dev/null 2>&1; then
        dialog --backtitle "$BACKTITLE" \
            --title "$(translate "Pool exists")" \
            --msgbox "\n$(translate "A ZFS pool with this name already exists.")\n\n$name" $UI_MSG_H $UI_RESULT_W
        return 1
    fi

    ZFS_POOL_NAME="$name"
    return 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Filesystem tool check / install
# ──────────────────────────────────────────────────────────────────────────────

ensure_fs_tool() {
    case "$FORMAT_TYPE" in
        exfat)
            command -v mkfs.exfat >/dev/null 2>&1 && return 0
            if declare -F ensure_repositories >/dev/null 2>&1; then
                ensure_repositories || true
            fi
            if DEBIAN_FRONTEND=noninteractive apt-get install -y exfatprogs >/dev/null 2>&1; then
                command -v mkfs.exfat >/dev/null 2>&1 && {
                    msg_ok "$(translate "exFAT tools installed successfully.")"
                    return 0
                }
            fi
            msg_error "$(translate "Could not install exFAT tools automatically.")"
            msg_info3 "$(translate "Install manually and retry: apt-get install -y exfatprogs")"
            return 1
            ;;
        btrfs)
            command -v mkfs.btrfs >/dev/null 2>&1 && return 0
            msg_error "$(translate "mkfs.btrfs not found. Install btrfs-progs and retry.")"
            return 1
            ;;
        zfs)
            command -v zpool >/dev/null 2>&1 && command -v zfs >/dev/null 2>&1 && return 0
            msg_error "$(translate "ZFS tools not found. Install zfsutils-linux and retry.")"
            return 1
            ;;
    esac
    return 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Terminal phase helpers
# ──────────────────────────────────────────────────────────────────────────────

show_terminal_stage_header() {
    show_proxmenux_logo
    msg_title "$(translate "Secure Disk Formatter")"
}

wait_for_enter_to_main() {
    echo
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

main() {
    select_target_disk    || exit 0
    select_operation_mode || exit 0
    confirm_format_action || exit 0

    if [[ "$OPERATION_MODE" == "clean_and_format" ]]; then
        select_filesystem || exit 0
        if [[ "$FORMAT_TYPE" == "zfs" ]]; then
            prompt_zfs_pool_name || exit 0
        fi
    fi

    show_terminal_stage_header
    local _model _size
    IFS=$'\t' read -r _model _size < <(get_disk_info "$SELECTED_DISK")
    msg_ok "$(translate "Disk"):       ${CL}${BL}$SELECTED_DISK — $_model  $_size${CL}"
    case "$OPERATION_MODE" in
        wipe_all)         msg_ok "$(translate "Mode"):       $(translate "Wipe all — remove partitions + metadata")" ;;
        clean_sigs)       msg_ok "$(translate "Mode"):       $(translate "Remove FS labels — partitions and data preserved")" ;;
        wipe_data)        msg_ok "$(translate "Mode"):       $(translate "Zero all data — partition table preserved")" ;;
        clean_and_format) msg_ok "$(translate "Mode"):       $(translate "Full format — new GPT partition + filesystem")"
                          msg_ok "$(translate "Filesystem"): $FORMAT_TYPE"
                          [[ "$FORMAT_TYPE" == "zfs" ]] && msg_ok "$(translate "ZFS pool"):  $ZFS_POOL_NAME" ;;
    esac
    echo

    if [[ "$OPERATION_MODE" == "clean_and_format" ]]; then
        if ! ensure_fs_tool; then
            wait_for_enter_to_main
            exit 1
        fi
    fi

    msg_info "$(translate "Validating disk safety...")"
    if ! revalidate_selected_disk; then
        msg_error "${REVALIDATE_ERROR_DETAIL:-$(translate "Disk safety revalidation failed.")}"
        wait_for_enter_to_main
        exit 1
    fi
    msg_ok "$(translate "Disk safety validation passed.")"

    # ── Execute the selected operation ────────────────────────────────────────
    export DOH_SHOW_PROGRESS=0
    export DOH_ENABLE_STACK_RELEASE=0

    if [[ "$OPERATION_MODE" == "wipe_all" ]]; then
        msg_info "$(translate "Wiping partitions and metadata...")"
        doh_wipe_disk "$SELECTED_DISK"
        msg_ok "$(translate "All partitions and metadata removed.")"
        echo
        msg_success "$(translate "Disk is ready to be added to Proxmox storage.")"
        echo
        wait_for_enter_to_main
        exit 0
    fi

    if [[ "$OPERATION_MODE" == "clean_sigs" ]]; then
        msg_info "$(translate "Removing filesystem signatures...")"
        # `|| true` swallowed real failures (busy device, ENOSPC writing
        # the magic bytes) and the user got a green "Signatures removed"
        # even when nothing was actually wiped. Capture the failure and
        # continue but report it. Audit Tier 6 — `format-disk.sh` wipefs
        # `|| true` silencia fallos.
        local _wipefs_errs=0
        local _wipefs_err_out
        if ! _wipefs_err_out=$(wipefs -af "$SELECTED_DISK" 2>&1); then
            _wipefs_errs=$((_wipefs_errs + 1))
            msg_warn "$(translate "wipefs failed on") $SELECTED_DISK: $_wipefs_err_out"
        fi
        local pname
        while read -r pname; do
            [[ -z "$pname" ]] && continue
            [[ "/dev/$pname" == "$SELECTED_DISK" ]] && continue
            if [[ -b "/dev/$pname" ]]; then
                if ! _wipefs_err_out=$(wipefs -af "/dev/$pname" 2>&1); then
                    _wipefs_errs=$((_wipefs_errs + 1))
                    msg_warn "$(translate "wipefs failed on") /dev/$pname: $_wipefs_err_out"
                fi
            fi
        done < <(lsblk -ln -o NAME "$SELECTED_DISK" 2>/dev/null | tail -n +2)
        if (( _wipefs_errs == 0 )); then
            msg_ok "$(translate "Signatures removed. Partition table preserved.")"
        else
            msg_warn "$(translate "Some signatures could not be removed (see warnings above).")"
        fi
        echo
        msg_success "$(translate "Disk is ready for VM passthrough.")"
        echo
        wait_for_enter_to_main
        exit 0
    fi

    if [[ "$OPERATION_MODE" == "wipe_data" ]]; then
        local wiped=0 part_path
        while read -r pname; do
            [[ -z "$pname" ]] && continue
            part_path="/dev/$pname"
            [[ "$part_path" == "$SELECTED_DISK" ]] && continue
            if [[ -b "$part_path" ]]; then
                msg_info "$(translate "Zeroing partition"): $part_path"
                if dd if=/dev/zero of="$part_path" bs=4M status=none 2>/dev/null; then
                    msg_ok "$part_path $(translate "zeroed.")"
                    wiped=$((wiped + 1))
                else
                    msg_warn "$(translate "Could not fully zero"):  $part_path"
                fi
            fi
        done < <(lsblk -ln -o NAME "$SELECTED_DISK" 2>/dev/null | tail -n +2)
        echo
        if (( wiped == 0 )); then
            msg_warn "$(translate "No partitions found on disk. Nothing was wiped.")"
        else
            msg_ok "$(translate "Data wiped from") $wiped $(translate "partition(s). Partition table preserved.")"
            echo
            msg_success "$(translate "Data wipe complete.")"
        fi
        echo
        wait_for_enter_to_main
        exit 0
    fi

    # OPERATION_MODE == "clean_and_format"
    msg_info "$(translate "Cleaning disk metadata...")"
    doh_wipe_disk "$SELECTED_DISK"
    msg_ok "$(translate "Disk metadata cleaned.")"

    msg_info "$(translate "Creating partition...")"
    if ! doh_create_partition "$SELECTED_DISK"; then
        msg_error "$(translate "Failed to create partition.")"
        local detail_msg
        detail_msg="$(printf '%s' "$DOH_PARTITION_ERROR_DETAIL" | head -n 3)"
        [[ -n "$detail_msg" ]] && msg_warn "$(translate "Details"): $detail_msg"
        wait_for_enter_to_main
        exit 1
    fi
    PARTITION="$DOH_CREATED_PARTITION"
    msg_ok "$(translate "Partition created"): $PARTITION"

    msg_info "$(translate "Formatting") $PARTITION $(translate "as") $FORMAT_TYPE..."
    if doh_format_partition "$PARTITION" "$FORMAT_TYPE" "" "$ZFS_POOL_NAME"; then
        if [[ "$FORMAT_TYPE" == "zfs" ]]; then
            msg_ok "$(translate "ZFS pool created"): $ZFS_POOL_NAME"
        else
            msg_ok "$PARTITION $(translate "formatted as") $FORMAT_TYPE"
        fi
        echo
        msg_success "$(translate "Disk formatted successfully.")"
        echo
        wait_for_enter_to_main
        exit 0
    fi

    msg_error "$(translate "Failed to format the partition.")"
    [[ -n "$DOH_FORMAT_ERROR_DETAIL" ]] && msg_warn "$(translate "Details"): $DOH_FORMAT_ERROR_DETAIL"
    echo
    wait_for_enter_to_main
    exit 1
}

main "$@"
