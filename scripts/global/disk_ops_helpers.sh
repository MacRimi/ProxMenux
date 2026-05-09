#!/usr/bin/env bash

# ==========================================================
# ProxMenux - Disk Operations Helpers
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.0
# Last Updated: 11/04/2026
# ==========================================================
# Shared low-level disk operations: wipe, partition, format.
# Consumed by format-disk.sh, disk_host.sh and future scripts.
#
# Output variables (set by helpers, read by callers):
#   DOH_CREATED_PARTITION    — partition path set by doh_create_partition()
#   DOH_PARTITION_ERROR_DETAIL — error detail set by doh_create_partition()
# ==========================================================

if [[ -n "${__PROXMENUX_DISK_OPS_HELPERS__}" ]]; then
    return 0
fi
__PROXMENUX_DISK_OPS_HELPERS__=1

# shellcheck disable=SC2034  # these are output variables read by callers (format-disk.sh, disk_host.sh)
DOH_CREATED_PARTITION=""
DOH_PARTITION_ERROR_DETAIL=""
DOH_FORMAT_ERROR_DETAIL=""
DOH_WIPE_ERROR_DETAIL=""

# Internal: print progress lines only when explicitly enabled by caller.
# Enabled with: export DOH_SHOW_PROGRESS=1
_doh_progress() {
    [[ "${DOH_SHOW_PROGRESS:-0}" == "1" ]] || return 0
    echo -e "${TAB}${YW}${HOLD}$*${CL}"
}

# Internal: collect command stdout with timeout protection (best-effort).
# Usage: _doh_collect_cmd <seconds> <cmd> [args...]
_doh_collect_cmd() {
    local seconds="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout --kill-after=2 "${seconds}s" "$@" 2>/dev/null || true
    else
        "$@" 2>/dev/null || true
    fi
}

# Internal: run a command with a timeout, suppressing all output including
# the bash "Killed" job notification that leaks when --kill-after re-raises
# SIGKILL. Plain SIGTERM is not enough for processes stuck in kernel D-state
# (uninterruptible I/O wait on a busy ZFS/LVM disk), so --kill-after=2 is
# needed. The notification is suppressed by temporarily redirecting the
# current shell's stderr with exec before the call and restoring it after.
# Usage: _doh_run_quick_cmd <seconds> <cmd> [args...]
_doh_run_quick_cmd() {
    local seconds="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        local _saved_stderr
        exec {_saved_stderr}>&2 2>/dev/null
        timeout --kill-after=2 "${seconds}s" "$@" >/dev/null 2>&1
        local rc=$?
        exec 2>&"${_saved_stderr}" {_saved_stderr}>&-
        return $rc
    fi
    "$@" >/dev/null 2>&1
}

# Internal: unmount all ZFS datasets then export (or destroy) any ZFS pools
# whose vdevs live on <disk>. Called at the very start of doh_wipe_disk so
# ZFS fully releases the device before wipefs/sgdisk/partprobe touch it.
# If the pool is still held after export, processes on it will be in D-state
# and --kill-after in _doh_run_quick_cmd handles the force-kill.
_doh_release_zfs_pools() {
    local disk="$1"
    command -v zpool >/dev/null 2>&1 || return 0

    local pool_name dev resolved base parent
    while read -r pool_name; do
        [[ -z "$pool_name" ]] && continue
        local found=false
        while read -r dev; do
            [[ -z "$dev" ]] && continue
            if [[ "$dev" == /dev/* ]]; then
                resolved=$(readlink -f "$dev" 2>/dev/null)
            elif [[ -e "/dev/disk/by-id/$dev" ]]; then
                resolved=$(readlink -f "/dev/disk/by-id/$dev" 2>/dev/null)
            elif [[ -e "/dev/$dev" ]]; then
                resolved=$(readlink -f "/dev/$dev" 2>/dev/null)
            else
                continue
            fi
            [[ -z "$resolved" ]] && continue
            base=$(lsblk -no PKNAME "$resolved" 2>/dev/null)
            parent="${base:+/dev/$base}"
            [[ -z "$parent" ]] && parent="$resolved"
            if [[ "$parent" == "$disk" || "$resolved" == "$disk" ]]; then
                found=true; break
            fi
        done < <(_doh_collect_cmd 12 zpool list -v -H "$pool_name" | awk '{print $1}' | \
                 grep -v '^-' | grep -v '^mirror' | grep -v '^raidz' | \
                 grep -v "^${pool_name}$")
        if $found; then
            _doh_progress "- Releasing active ZFS pool: $pool_name"
            # Unmount all datasets (reverse order: deepest first)
            if command -v zfs >/dev/null 2>&1; then
                while read -r ds; do
                    [[ -z "$ds" ]] && continue
                    timeout 10s zfs unmount -f "$ds" >/dev/null 2>&1 || true
                done < <(_doh_collect_cmd 10 zfs list -H -o name -r "$pool_name" | sort -r)
            fi
            # Export the pool so the kernel releases the block device
            timeout 30s zpool export -f "$pool_name" >/dev/null 2>&1 || true
            # Wait for udev to finish processing the device release
            udevadm settle --timeout=5 >/dev/null 2>&1 || true
            sleep 1
        fi
    done < <(_doh_collect_cmd 8 zpool list -H -o name)
}

# Internal: run a partitioning command with timeout, appending combined output to a file.
# Usage: _doh_part_cmd <seconds> <outfile> <cmd> [args...]
_doh_part_cmd() {
    local secs="$1" outfile="$2"
    shift 2
    if command -v timeout >/dev/null 2>&1; then
        timeout --kill-after=3 "${secs}s" "$@" >>"$outfile" 2>&1
    else
        "$@" >>"$outfile" 2>&1
    fi
}

# doh_wipe_disk <disk>
# Unmounts all partitions, deactivates swap, wipes all filesystem metadata
# and partition tables (wipefs + sgdisk + dd first/last 16 MiB).
# Never fails — all sub-commands run with "|| true".
doh_wipe_disk() {
    local disk="$1"
    local node mountpoint total_sectors seek_sectors discard_max base

    DOH_WIPE_ERROR_DETAIL=""
    _doh_progress "[1/8] Preparing disk $disk"

    # Optional heavy release flow (disabled by default to avoid hangs in busy hosts).
    if [[ "${DOH_ENABLE_STACK_RELEASE:-0}" == "1" ]]; then
        # Release any ZFS pools using this disk so the kernel lets go of it
        _doh_release_zfs_pools "$disk"

        # Deactivate any LVM VGs backed by this disk
        if command -v vgchange >/dev/null 2>&1; then
            local pv rp vg
            while read -r pv; do
                rp=$(readlink -f "$pv" 2>/dev/null)
                base=$(lsblk -no PKNAME "${rp:-$pv}" 2>/dev/null)
                if [[ "/dev/${base}" == "$disk" || "$rp" == "$disk" ]]; then
                    vg=$(_doh_collect_cmd 8 pvs --noheadings -o vg_name "${rp:-$pv}" | xargs)
                    [[ -n "$vg" ]] && _doh_run_quick_cmd 8 vgchange -an "$vg" || true
                fi
            done < <(_doh_collect_cmd 8 pvs --noheadings -o pv_name | xargs -r -n1)
        fi
    fi

    # Unmount all partitions
    _doh_progress "[2/8] Unmounting partitions"
    while read -r node mountpoint; do
        [[ -z "$node" || -z "$mountpoint" ]] && continue
        _doh_run_quick_cmd 8 umount -f "$node" || true
    done < <(lsblk -lnpo NAME,MOUNTPOINT "$disk" 2>/dev/null | awk 'NR>1 && $2!="" {print $1" "$2}')

    # Deactivate swap
    _doh_progress "[3/8] Disabling swap signatures"
    while read -r node; do
        [[ -z "$node" ]] && continue
        _doh_run_quick_cmd 8 swapoff "$node" || true
    done < <(lsblk -lnpo NAME "$disk" 2>/dev/null | awk 'NR>1 {print $1}')

    # Wipe filesystem signatures and RAID superblocks on every node
    _doh_progress "[4/8] Removing filesystem/RAID signatures"
    while read -r node; do
        [[ -z "$node" ]] && continue
        _doh_run_quick_cmd 10 wipefs -a -f "$node" || true
        if command -v mdadm >/dev/null 2>&1; then
            _doh_run_quick_cmd 8 mdadm --zero-superblock --force "$node" || true
        fi
    done < <(lsblk -lnpo NAME "$disk" 2>/dev/null)

    # Zap partition table
    _doh_progress "[5/8] Resetting partition table"
    _doh_run_quick_cmd 12 sgdisk --zap-all "$disk" || true

    # TRIM/discard if device supports it
    _doh_progress "[6/8] Attempting discard/TRIM when supported"
    discard_max=$(lsblk -dn -o DISC-MAX "$disk" 2>/dev/null | xargs)
    if [[ -n "$discard_max" && "$discard_max" != "0B" && "$discard_max" != "0" ]]; then
        _doh_run_quick_cmd 15 blkdiscard -f "$disk" || true
    fi

    # Zero first 16 MiB (destroys partition table / filesystem headers)
    _doh_progress "[7/8] Zeroing first metadata region"
    _doh_run_quick_cmd 20 dd if=/dev/zero of="$disk" bs=1M count=16 conv=fsync status=none || true

    # Zero last 16 MiB (destroys backup GPT header)
    _doh_progress "[8/8] Zeroing backup GPT region"
    total_sectors=$(blockdev --getsz "$disk" 2>/dev/null || echo 0)
    if [[ "$total_sectors" =~ ^[0-9]+$ ]] && (( total_sectors > 32768 )); then
        seek_sectors=$(( total_sectors - 32768 ))
        _doh_run_quick_cmd 20 dd if=/dev/zero of="$disk" bs=512 seek="$seek_sectors" count=32768 conv=fsync status=none || true
    fi

    udevadm settle --timeout=10 >/dev/null 2>&1 || true
    _doh_run_quick_cmd 8 partprobe "$disk" || true
    sleep 1
}

# doh_create_partition <disk>
# Creates a single GPT partition spanning the whole disk.
# Tries parted → sgdisk → sfdisk in order; stops at first success.
#
# On success: sets DOH_CREATED_PARTITION to the new partition path, returns 0.
# On failure: sets DOH_PARTITION_ERROR_DETAIL with tool diagnostics, returns 1.
doh_create_partition() {
    local disk="$1"
    local created=false tmp_out err_snippet

    DOH_CREATED_PARTITION=""
    DOH_PARTITION_ERROR_DETAIL=""

    _doh_run_quick_cmd 5 blockdev --setrw "$disk" || true

    # --- attempt 1: parted ---
    if command -v parted >/dev/null 2>&1; then
        tmp_out=$(mktemp)
        if _doh_part_cmd 15 "$tmp_out" parted -s -f "$disk" mklabel gpt; then
            if _doh_part_cmd 20 "$tmp_out" parted -s -f "$disk" mkpart primary 1MiB 100%; then
                created=true
            else
                err_snippet=$(tr '\n' ' ' <"$tmp_out" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')
                DOH_PARTITION_ERROR_DETAIL+="parted mkpart: ${err_snippet:-no details}"$'\n'
            fi
        else
            err_snippet=$(tr '\n' ' ' <"$tmp_out" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')
            DOH_PARTITION_ERROR_DETAIL+="parted mklabel: ${err_snippet:-no details}"$'\n'
        fi
        rm -f "$tmp_out"
    else
        DOH_PARTITION_ERROR_DETAIL+="parted command not found"$'\n'
    fi

    # --- attempt 2: sgdisk ---
    if [[ "$created" != "true" ]] && command -v sgdisk >/dev/null 2>&1; then
        tmp_out=$(mktemp)
        _doh_run_quick_cmd 10 sgdisk --zap-all "$disk" || true
        # sgdisk does not accept "1MiB" notation — use sector 2048 (= 1 MiB at 512 B/sector)
        if _doh_part_cmd 20 "$tmp_out" sgdisk -o -n 1:2048:0 -t 1:8300 "$disk"; then
            created=true
        else
            err_snippet=$(tr '\n' ' ' <"$tmp_out" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')
            DOH_PARTITION_ERROR_DETAIL+="sgdisk create: ${err_snippet:-no details}"$'\n'
        fi
        rm -f "$tmp_out"
    elif [[ "$created" != "true" ]]; then
        DOH_PARTITION_ERROR_DETAIL+="sgdisk command not found"$'\n'
    fi

    # --- attempt 3: sfdisk ---
    if [[ "$created" != "true" ]] && command -v sfdisk >/dev/null 2>&1; then
        tmp_out=$(mktemp)
        local sfdisk_ok=1
        if command -v timeout >/dev/null 2>&1; then
            printf 'label: gpt\n,;\n' | timeout --kill-after=3 20s sfdisk --wipe always "$disk" >>"$tmp_out" 2>&1
            sfdisk_ok=$?
        else
            printf 'label: gpt\n,;\n' | sfdisk --wipe always "$disk" >>"$tmp_out" 2>&1
            sfdisk_ok=$?
        fi
        if [[ $sfdisk_ok -eq 0 ]]; then
            created=true
        else
            err_snippet=$(tr '\n' ' ' <"$tmp_out" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')
            DOH_PARTITION_ERROR_DETAIL+="sfdisk create: ${err_snippet:-no details}"$'\n'
        fi
        rm -f "$tmp_out"
    elif [[ "$created" != "true" ]]; then
        DOH_PARTITION_ERROR_DETAIL+="sfdisk command not found"$'\n'
    fi

    [[ "$created" == "true" ]] || return 1

    # Wait for the kernel to expose the new partition node
    udevadm settle --timeout=10 >/dev/null 2>&1 || true
    _doh_run_quick_cmd 8 partprobe "$disk" || true

    local part
    for _ in {1..15}; do
        sleep 0.3
        part=$(lsblk -lnpo NAME "$disk" 2>/dev/null | awk 'NR==2{print; exit}')
        if [[ -n "$part" && -b "$part" ]]; then
            DOH_CREATED_PARTITION="$part"
            return 0
        fi
    done

    # Fallback: derive partition name from disk path (handles NVMe p-suffix)
    local fallback
    if [[ "$disk" =~ [0-9]$ ]]; then
        fallback="${disk}p1"
    else
        fallback="${disk}1"
    fi
    if [[ -b "$fallback" ]]; then
        DOH_CREATED_PARTITION="$fallback"
        return 0
    fi

    DOH_PARTITION_ERROR_DETAIL+="partition node not detected after table refresh"$'\n'
    return 1
}

# doh_format_partition <partition> <filesystem> [label] [zfs_pool_name] [zfs_mountpoint]
#
# Formats <partition> with <filesystem>.
#   label          : optional FS label for ext4/xfs/btrfs (ignored for ZFS)
#   zfs_pool_name  : required when filesystem=zfs; defaults to label if empty
#   zfs_mountpoint : ZFS pool mountpoint (default: "none" — no automatic mount)
#
# On failure: sets DOH_FORMAT_ERROR_DETAIL with tool diagnostics.
# Returns 0 on success, 1 on failure.
doh_format_partition() {
    local partition="$1"
    local filesystem="$2"
    local label="${3:-}"
    local zfs_pool="${4:-}"
    local zfs_mountpoint="${5:-none}"
    local tmp_out rc=1

    DOH_FORMAT_ERROR_DETAIL=""
    tmp_out=$(mktemp)

    case "$filesystem" in
        ext4)
            if [[ -n "$label" ]]; then
                mkfs.ext4 -F -L "$label" "$partition" >"$tmp_out" 2>&1; rc=$?
            else
                mkfs.ext4 -F "$partition" >"$tmp_out" 2>&1; rc=$?
            fi
            ;;
        xfs)
            if [[ -n "$label" ]]; then
                mkfs.xfs -f -L "$label" "$partition" >"$tmp_out" 2>&1; rc=$?
            else
                mkfs.xfs -f "$partition" >"$tmp_out" 2>&1; rc=$?
            fi
            ;;
        exfat)
            mkfs.exfat "$partition" >"$tmp_out" 2>&1; rc=$?
            ;;
        btrfs)
            if [[ -n "$label" ]]; then
                mkfs.btrfs -f -L "$label" "$partition" >"$tmp_out" 2>&1; rc=$?
            else
                mkfs.btrfs -f "$partition" >"$tmp_out" 2>&1; rc=$?
            fi
            ;;
        zfs)
            [[ -z "$zfs_pool" ]] && zfs_pool="${label:-pool}"
            zpool labelclear -f "$partition" >/dev/null 2>&1 || true
            zpool create -f -o ashift=12 \
                -O compression=lz4 -O atime=off -O xattr=sa -O acltype=posixacl \
                -m "$zfs_mountpoint" "$zfs_pool" "$partition" >"$tmp_out" 2>&1
            rc=$?
            ;;
        *)
            echo "Unknown filesystem: $filesystem" >"$tmp_out"
            rc=1
            ;;
    esac

    if [[ $rc -ne 0 ]]; then
        DOH_FORMAT_ERROR_DETAIL=$(tr '\n' ' ' <"$tmp_out" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')
    fi
    rm -f "$tmp_out"
    return $rc
}
