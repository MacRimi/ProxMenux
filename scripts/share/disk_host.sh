#!/bin/bash
# ==========================================================
# ProxMenux - Local Disk Manager for Proxmox Host
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Prepares a local SCSI / SATA / NVMe disk on the Proxmox host
# and registers it as Proxmox storage — either as a directory
# (pvesm add dir) or as a ZFS pool (pvesm add zfspool).
#
# Features:
# - Safety filter hides root / swap / mounted / in-use disks
#   and disks already referenced by any VM/CT config.
# - Format path: wipe + GPT + mkfs (ext4 / xfs / btrfs / zfs).
# - Reuse path: mount an existing filesystem without touching
#   the data.
# - UUID-based /etc/fstab entries with defaults,nofail.
# - Content-type presets (VM Storage / Standard NAS / All / Custom).
# - View, remove (with fstab cleanup) and list-disks helpers.
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

load_language
initialize_cache

if ! command -v pveversion >/dev/null 2>&1; then
    dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
        --msgbox "$(translate "This script must be run on a Proxmox host.")" 8 60
    exit 1
fi

# ==========================================================
# SYSTEM STORAGE DETECTION
# ==========================================================

# Returns the name of the ZFS pool containing the root filesystem, if any.
_get_system_zfs_pool() {
    local root_fs
    root_fs=$(df / 2>/dev/null | awk 'NR==2 {print $1}')
    if [[ "$root_fs" != /dev/* && "$root_fs" == */* ]]; then
        echo "${root_fs%%/*}"
    fi
}

# Returns 0 if the given pvesm storage is a user-created disk storage
# that should appear in add/remove menus. Returns 1 for system storages.
_is_user_disk_storage() {
    local storage_id="$1"
    local storage_type="$2"
    local sys_pool

    local cfg_path pool
    cfg_path=$(get_storage_config "$storage_id" | awk '$1 == "path" {print $2}')
    pool=$(get_storage_config "$storage_id" | awk '$1 == "pool" {print $2}')

    case "$storage_type" in
        dir)
            # User-created dir storages are always mounted under /mnt/
            [[ "$cfg_path" == /mnt/* ]] && return 0
            return 1
            ;;
        zfspool)
            # User-created ZFS pool storages are NOT on the root pool or its datasets
            sys_pool=$(_get_system_zfs_pool)
            if [[ -n "$sys_pool" ]]; then
                # Skip if pool is the root pool or a dataset within it (e.g. rpool/data)
                [[ "$pool" == "$sys_pool" || "$pool" == "$sys_pool/"* ]] && return 1
            fi
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# ==========================================================
# STORAGE CONFIG READER
# ==========================================================
get_storage_config() {
    local storage_id="$1"
    awk -v id="$storage_id" '
        /^[a-z]+: / { found = ($0 ~ ": "id"$"); next }
        found && /^[^ \t]/ { exit }
        found { print }
    ' /etc/pve/storage.cfg
}

# ==========================================================
# DISK DETECTION
# ==========================================================

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

    if [[ -n "$real_path" ]] && grep -Fq "$real_path" <<< "$config_data"; then
        return 0
    fi
    for link in /dev/disk/by-id/*; do
        [[ -e "$link" ]] || continue
        [[ "$(readlink -f "$link" 2>/dev/null)" == "$real_path" ]] || continue
        if grep -Fq "$link" <<< "$config_data"; then
            return 0
        fi
    done
    return 1
}

disk_used_by_host_storage() {
    local disk="$1"
    if declare -F _disk_is_host_system_used >/dev/null 2>&1; then
        _disk_is_host_system_used "$disk"
        return $?
    fi

    local mounted_disks swap_disks lvm_devices zfs_disks real_path path base_disk
    local part fstype part_path

    mounted_disks=$(lsblk -ln -o NAME,MOUNTPOINT | awk '$2!="" {print "/dev/" $1}')
    swap_disks=$(swapon --noheadings --raw --show=NAME 2>/dev/null)
    lvm_devices=$(pvs --noheadings -o pv_name 2>/dev/null | xargs -r -n1 readlink -f | sort -u)
    zfs_disks=""

    while read -r part fstype; do
        [[ -z "$part" ]] && continue
        part_path="/dev/$part"
        if grep -qFx "$part_path" <<< "$mounted_disks"; then
            return 0
        fi
        if grep -qFx "$part_path" <<< "$swap_disks"; then
            return 0
        fi
        case "$fstype" in
            zfs_member|linux_raid_member|LVM2_member)
                return 0
                ;;
        esac
    done < <(lsblk -ln -o NAME,FSTYPE "$disk" 2>/dev/null)

    while read -r entry; do
        [[ -z "$entry" ]] && continue
        path=""
        if [[ "$entry" == wwn-* || "$entry" == ata-* ]]; then
            [[ -e "/dev/disk/by-id/$entry" ]] && path=$(readlink -f "/dev/disk/by-id/$entry")
        elif [[ "$entry" == /dev/* ]]; then
            path="$entry"
        fi
        if [[ -n "$path" ]]; then
            base_disk=$(lsblk -no PKNAME "$path" 2>/dev/null)
            [[ -n "$base_disk" ]] && zfs_disks+="/dev/$base_disk"$'\n'
        fi
    done < <(zpool list -v -H 2>/dev/null | awk '{print $1}' | grep -v '^NAME$' | grep -v '^-' | grep -v '^mirror')

    real_path=$(readlink -f "$disk" 2>/dev/null)
    if [[ -n "$real_path" && -n "$lvm_devices" ]] && grep -qFx "$real_path" <<< "$lvm_devices"; then
        return 0
    fi
    if [[ -n "$zfs_disks" ]] && grep -qFx "$disk" <<< "$(echo "$zfs_disks" | sort -u)"; then
        return 0
    fi
    return 1
}

get_disk_info() {
    local disk="$1"
    local model size
    model=$(lsblk -dn -o MODEL "$disk" 2>/dev/null | xargs)
    size=$(lsblk -dn -o SIZE "$disk" 2>/dev/null | xargs)
    [[ -z "$model" ]] && model="$(translate "Unknown model")"
    [[ -z "$size" ]] && size="$(translate "Unknown size")"
    printf '%s\t%s\n' "$model" "$size"
}

get_available_disks() {
    if declare -F _refresh_host_storage_cache >/dev/null 2>&1; then
        _refresh_host_storage_cache
    fi

    while read -r disk ro type; do
        [[ -z "$disk" ]] && continue
        [[ "$type" != "disk" ]] && continue
        [[ "$ro" == "1" ]] && continue
        [[ "$disk" =~ ^/dev/zd ]] && continue

        if disk_used_by_host_storage "$disk"; then
            continue
        fi
        if disk_referenced_in_guest_configs "$disk"; then
            continue
        fi

        local model size
        IFS=$'\t' read -r model size < <(get_disk_info "$disk")
        [[ -z "$model" || "$model" == " " ]] && model="-"

        echo "$disk|$size — $model"
    done < <(lsblk -dn -e 7,11 -o PATH,RO,TYPE 2>/dev/null)
}

select_disk() {

    local disk_list
    disk_list=$(get_available_disks)

    if [[ -z "$disk_list" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Disks Found")" \
            --msgbox "\n$(translate "No available disks found.")\n\n$(translate "All disks may already be in use or mounted.")" 10 60
        return 1
    fi

    local options=()
    while IFS='|' read -r device info; do
        [[ -n "$device" ]] && options+=("$device" "$info")
    done <<< "$disk_list"

    if [[ ${#options[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Disks Found")" \
            --msgbox "\n$(translate "No suitable disks found.")" 8 60
        return 1
    fi

    SELECTED_DISK=$(dialog --backtitle "ProxMenux" --title "$(translate "Select Disk")" \
        --menu "\n$(translate "Select the disk to add as Proxmox storage:")\n$(translate "WARNING: All data on selected disk will be ERASED if formatted.")" \
        20 84 10 "${options[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED_DISK" ]] && return 1

    return 0
}

inspect_disk() {
    local disk="$1"

    # Check existing partitions/filesystem
    local partition_info
    partition_info=$(lsblk -no NAME,SIZE,FSTYPE,MOUNTPOINT "$disk" 2>/dev/null | tail -n +2)

    local existing_fs existing_node
    existing_fs=$(blkid -s TYPE -o value "$disk" 2>/dev/null || true)
    existing_node="$disk"
    if [[ -z "$existing_fs" ]]; then
        while read -r node fstype mountpoint; do
            [[ -z "$node" || -z "$fstype" ]] && continue
            [[ -n "$mountpoint" ]] && continue
            existing_fs="$fstype"
            existing_node="$node"
            break
        done < <(lsblk -lnpo NAME,FSTYPE,MOUNTPOINT "$disk" 2>/dev/null | awk 'NR>1 {print $1, $2, $3}')
    fi

    DISK_HAS_DATA=false
    DISK_EXISTING_FS=""
    DISK_EXISTING_NODE=""

    if [[ -n "$partition_info" || -n "$existing_fs" ]]; then
        DISK_HAS_DATA=true
        DISK_EXISTING_FS="$existing_fs"
        DISK_EXISTING_NODE="$existing_node"
    fi

    return 0
}

select_partition_action() {
    local disk="$1"
    inspect_disk "$disk"

    local disk_size
    disk_size=$(lsblk -ndo SIZE "$disk" 2>/dev/null)

    local menu_items=()
    menu_items+=("format" "$(translate "Format disk (ERASE all data)")")
    [[ -n "$DISK_EXISTING_FS" ]] && menu_items+=("use_existing" "$(translate "Use existing filesystem")")
    menu_items+=("cancel" "$(translate "Cancel")")

    local menu_text
    if [[ "$DISK_HAS_DATA" == "true" ]]; then
        menu_text="$(translate "Disk:"): $disk ($disk_size)\n"
        [[ -n "$DISK_EXISTING_FS" ]] && menu_text+="$(translate "Existing filesystem:"): $DISK_EXISTING_FS\n"
        menu_text+="\n$(translate "Options:")\n"
        menu_text+="• $(translate "Format: ERASE all data and create new filesystem")\n"
        [[ -n "$DISK_EXISTING_FS" ]] && menu_text+="• $(translate "Use existing: mount without formatting")\n"
        menu_text+="\n$(translate "Continue?")"
    else
        menu_text="$(translate "Disk:"): $disk ($disk_size)\n\n$(translate "Disk appears empty. It will be formatted.")"
    fi

    DISK_ACTION=$(dialog --backtitle "ProxMenux" --title "$(translate "Disk Setup")" \
        --menu "$menu_text" 20 84 8 \
        "${menu_items[@]}" 3>&1 1>&2 2>&3)

    [[ -z "$DISK_ACTION" || "$DISK_ACTION" == "cancel" ]] && return 1
    return 0
}

select_filesystem() {
    FILESYSTEM=$(dialog --backtitle "ProxMenux" --title "$(translate "Select Filesystem")" \
        --menu "\n$(translate "Choose filesystem for the disk:")" 16 72 5 \
        "ext4"  "$(translate "ext4  — Proxmox dir storage (recommended)")" \
        "xfs"   "$(translate "xfs   — Proxmox dir storage (large files and VMs)")" \
        "btrfs" "$(translate "btrfs — Proxmox dir storage (snapshots, compression)")" \
        "zfs"   "$(translate "zfs   — Proxmox ZFS pool storage")" \
        3>&1 1>&2 2>&3)
    [[ -z "$FILESYSTEM" ]] && return 1
    return 0
}

# Aligns disk_host with nfs_host.sh / samba_host.sh: the user can pick
# whether the disk shows up as a Proxmox storage (visible in Datacenter
# → Storage and usable for VM disks, backups, ISOs…) or whether it's
# only mounted on the host so LXCs can bind-mount it — or both at once.
# Without this chooser the script always registered as Proxmox storage,
# which forced users who only wanted host-side LXC bind-mounts to walk
# through the pvesm flow and then manually remove the storage entry.
select_mount_method() {
    MODE_PVESM=0
    MODE_FSTAB=0

    # ZFS only makes sense as a pvesm zfspool storage — there is no
    # "fstab only" equivalent for a ZFS pool (it's imported, not
    # fstab-mounted), so don't bother asking.
    if [[ "${FILESYSTEM:-}" == "zfs" ]]; then
        MODE_PVESM=1
        return 0
    fi

    local result
    result=$(dialog --backtitle "ProxMenux" \
        --title "$(translate "Mount Method")" \
        --checklist "\n$(translate "Choose how to make the disk available on this host. Mark one or both options:")\n\n$(translate "• Proxmox storage (pvesm): visible in Datacenter > Storage, usable for VMs/backups/ISOs")\n$(translate "• Host fstab: mounted at host path only, for LXC bind-mounts (NOT visible as Proxmox storage)")\n$(translate "• Both: registers as Proxmox storage AND keeps the mount available for LXC bind-mounts")" 20 84 2 \
        "pvesm" "$(translate "As Proxmox storage")"     off \
        "fstab" "$(translate "As host fstab mount only")" on \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    if echo "$result" | grep -qw "pvesm"; then MODE_PVESM=1; fi
    if echo "$result" | grep -qw "fstab"; then MODE_FSTAB=1; fi

    if [[ "$MODE_PVESM" -eq 0 && "$MODE_FSTAB" -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Method Selected")" \
            --msgbox "$(translate "You must select at least one mount method to continue.")" 8 60
        return 1
    fi
    return 0
}

# ==========================================================
# STORAGE CONFIGURATION
# ==========================================================

configure_disk_storage() {
    local disk_name
    disk_name=$(basename "$SELECTED_DISK")

    # The first prompt collects an identifier used both as the Proxmox
    # storage ID (when MODE_PVESM=1) and as the /mnt/<…> directory name
    # in either mode. The wording is adjusted so a user in fstab-only
    # mode isn't asked for a "Storage ID" they'll never see in Proxmox.
    local id_title id_prompt
    if [[ "$MODE_PVESM" -eq 1 ]]; then
        id_title="$(translate "Storage ID")"
        id_prompt="$(translate "Enter storage ID for Proxmox:")"
    else
        id_title="$(translate "Mount Name")"
        id_prompt="$(translate "Enter a name for the mount point (used as /mnt/<name>):")"
    fi

    STORAGE_ID=$(dialog --backtitle "ProxMenux" --title "$id_title" \
        --inputbox "$id_prompt" \
        10 70 "disk-${disk_name}" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1
    [[ -z "$STORAGE_ID" ]] && STORAGE_ID="disk-${disk_name}"

    if [[ ! "$STORAGE_ID" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "Invalid ID")" \
            --msgbox "$(translate "Invalid name. Use only letters, numbers, hyphens and underscores.")" 8 74
        return 1
    fi
    if [[ "${FILESYSTEM:-}" == "zfs" && ! "$STORAGE_ID" =~ ^[a-zA-Z][a-zA-Z0-9_.:-]*$ ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "Invalid ID")" \
            --msgbox "$(translate "For ZFS, storage ID must start with a letter and use only letters, numbers, dot, dash, underscore or colon.")" 9 86
        return 1
    fi

    MOUNT_PATH="/mnt/${STORAGE_ID}"
    MOUNT_PATH=$(dialog --backtitle "ProxMenux" --title "$(translate "Mount Path")" \
        --inputbox "$(translate "Enter mount path on host:")" \
        10 60 "$MOUNT_PATH" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 || -z "$MOUNT_PATH" ]] && return 1

    # Content types are a Proxmox storage concept — skip the prompt
    # entirely in fstab-only mode and leave MOUNT_CONTENT empty so
    # add_proxmox_dir_storage is never invoked downstream.
    if [[ "$MODE_PVESM" -ne 1 ]]; then
        MOUNT_CONTENT=""
        return 0
    fi

    CONTENT_TYPE=$(dialog --backtitle "ProxMenux" --title "$(translate "Content Types")" \
        --menu "$(translate "Select content types for this storage:")" 16 70 5 \
        "1" "$(translate "VM Storage     (images, backup)")" \
        "2" "$(translate "Standard NAS   (backup, iso, vztmpl)")" \
        "3" "$(translate "All types      (images, backup, iso, vztmpl, snippets)")" \
        "4" "$(translate "Custom")" \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    case "$CONTENT_TYPE" in
        1) MOUNT_CONTENT="images,backup" ;;
        2) MOUNT_CONTENT="backup,iso,vztmpl" ;;
        3) MOUNT_CONTENT="images,backup,iso,vztmpl,snippets" ;;
        4)
            MOUNT_CONTENT=$(dialog --backtitle "ProxMenux" --title "$(translate "Custom Content")" \
                --inputbox "$(translate "Enter content types (comma-separated):")" \
                10 70 "images,backup" 3>&1 1>&2 2>&3)
            [[ $? -ne 0 || -z "$MOUNT_CONTENT" ]] && MOUNT_CONTENT="images,backup"
            ;;
        *) return 1 ;;
    esac

    return 0
}

# ==========================================================
# DISK SETUP AND MOUNT
# ==========================================================

format_and_mount_disk() {
    local disk="$1"
    local mount_path="$2"
    local filesystem="$3"

    # Final confirmation before any destructive operation
    local disk_size
    disk_size=$(lsblk -ndo SIZE "$disk" 2>/dev/null)
    if ! dialog --backtitle "ProxMenux" --title "$(translate "CONFIRM FORMAT")" --yesno \
        "$(translate "FINAL CONFIRMATION — DATA WILL BE ERASED")\n\n$(translate "Disk:"): $disk ($disk_size)\n$(translate "Filesystem:"): $filesystem\n$(translate "Mount path:"): $mount_path\n\n$(translate "ALL DATA ON") $disk $(translate "WILL BE PERMANENTLY ERASED.")\n\n$(translate "Are you absolutely sure?")" \
        14 80; then
        return 1
    fi
    show_proxmenux_logo
    if [[ "$MODE_PVESM" -eq 1 && "$MODE_FSTAB" -eq 1 ]]; then
        msg_title "$(translate "Add Local Disk (Proxmox storage + host mount)")"
    elif [[ "$MODE_PVESM" -eq 1 ]]; then
        msg_title "$(translate "Add Local Disk as Proxmox Storage")"
    else
        msg_title "$(translate "Add Local Disk as Host Mount (for LXC bind-mounts)")"
    fi
    local _disk_model _disk_size _disk_label
    IFS=$'\t' read -r _disk_model _disk_size < <(get_disk_info "$disk")
    _disk_label="$disk"
    [[ -n "$_disk_size" && -n "$_disk_model" ]] && _disk_label="$disk — $_disk_size — $_disk_model"
    msg_ok "$(translate "Disk:") ${BL}${_disk_label}${CL}"
    msg_ok "$(translate "Action:") $DISK_ACTION"
    [[ "$DISK_ACTION" == "format" ]] && msg_ok "$(translate "Filesystem:") $FILESYSTEM"
    msg_ok "$(translate "Mount path:") $MOUNT_PATH"
    if [[ "$MODE_PVESM" -eq 1 ]]; then
        msg_ok "$(translate "Storage ID:") $STORAGE_ID"
        msg_ok "$(translate "Content:") $MOUNT_CONTENT"
    else
        msg_ok "$(translate "Mount Name:") $STORAGE_ID"
        msg_ok "$(translate "Method:") $(translate "host fstab only (not registered as Proxmox storage)")"
    fi
    msg_info "$(translate "Wiping existing partition table...")"
    doh_wipe_disk "$disk"
    msg_ok "$(translate "Partition table wiped")"
    msg_info "$(translate "Creating partition...")"
    if ! doh_create_partition "$disk"; then
        msg_error "$(translate "Failed to create partition table")"
        [[ -n "$DOH_PARTITION_ERROR_DETAIL" ]] && \
            msg_error "$(translate "Details"): $(printf '%s' "$DOH_PARTITION_ERROR_DETAIL" | head -n1)"
        return 1
    fi
    msg_ok "$(translate "Partition created")"
    local partition="$DOH_CREATED_PARTITION"

    # ZFS pre-flight checks (pool existence must be verified before format)
    if [[ "$filesystem" == "zfs" ]]; then
        if ! command -v zpool >/dev/null 2>&1; then
            msg_error "$(translate "zpool command not found. Install zfsutils-linux and retry.")"
            return 1
        fi
        if zpool list "$STORAGE_ID" >/dev/null 2>&1; then
            msg_error "$(translate "A ZFS pool with this name already exists:") $STORAGE_ID"
            return 1
        fi
    fi

    msg_info "$(translate "Formatting as") $filesystem..."
    if ! doh_format_partition "$partition" "$filesystem" "$STORAGE_ID" "$STORAGE_ID" "$mount_path"; then
        msg_error "$(translate "Failed to format disk as") $filesystem"
        return 1
    fi

    msg_ok "$(translate "Disk formatted as") $filesystem"

    DISK_PARTITION="$partition"
    return 0
}

mount_disk_permanently() {
    local partition="$1"
    local mount_path="$2"
    local filesystem="$3"

    if [[ "$filesystem" == "zfs" ]]; then
        if ! zpool list "$STORAGE_ID" >/dev/null 2>&1; then
            msg_error "$(translate "ZFS pool is not available after creation:") $STORAGE_ID"
            return 1
        fi
        msg_ok "$(translate "ZFS pool created and mounted at") $mount_path"
        return 0
    fi

    msg_info "$(translate "Creating mount point...")"
    if ! mkdir -p "$mount_path"; then
        msg_error "$(translate "Failed to create mount point:") $mount_path"
        return 1
    fi
    msg_ok "$(translate "Mount point created")"

    msg_info "$(translate "Mounting disk...")"
    if ! mount -t "$filesystem" "$partition" "$mount_path" 2>/dev/null; then
        msg_error "$(translate "Failed to mount disk")"
        return 1
    fi
    msg_ok "$(translate "Disk mounted at") $mount_path"

    msg_info "$(translate "Adding to /etc/fstab for permanent mounting...")"
    local disk_uuid
    disk_uuid=$(blkid -s UUID -o value "$partition" 2>/dev/null)

    if [[ -n "$disk_uuid" ]]; then
        # Remove any existing fstab entry for this UUID or mount point
        sed -i "\|UUID=$disk_uuid|d" /etc/fstab
        sed -i "\|[[:space:]]${mount_path}[[:space:]]|d" /etc/fstab
        echo "UUID=$disk_uuid  $mount_path  $filesystem  defaults,nofail  0  2" >> /etc/fstab
        msg_ok "$(translate "Added to /etc/fstab using UUID")"
    else
        sed -i "\|[[:space:]]${mount_path}[[:space:]]|d" /etc/fstab
        echo "$partition  $mount_path  $filesystem  defaults,nofail  0  2" >> /etc/fstab
        msg_ok "$(translate "Added to /etc/fstab using device path")"
    fi

    systemctl daemon-reload 2>/dev/null || true
    return 0
}

mount_existing_disk() {
    local disk="$1"
    local mount_path="$2"

    local existing_fs
    existing_fs=$(blkid -s TYPE -o value "$disk" 2>/dev/null || true)

    if [[ -z "$existing_fs" ]]; then
        msg_error "$(translate "Cannot detect filesystem on") $disk"
        return 1
    fi

    msg_info "$(translate "Creating mount point...")"
    mkdir -p "$mount_path"
    msg_ok "$(translate "Mount point created")"

    msg_info "$(translate "Mounting existing") $existing_fs $(translate "filesystem...")"
    if ! mount "$disk" "$mount_path" 2>/dev/null; then
        msg_error "$(translate "Failed to mount disk")"
        return 1
    fi
    msg_ok "$(translate "Disk mounted at") $mount_path"

    # Add to fstab
    local disk_uuid
    disk_uuid=$(blkid -s UUID -o value "$disk" 2>/dev/null)
    if [[ -n "$disk_uuid" ]]; then
        sed -i "\|UUID=$disk_uuid|d" /etc/fstab
        sed -i "\|[[:space:]]${mount_path}[[:space:]]|d" /etc/fstab
        echo "UUID=$disk_uuid  $mount_path  $existing_fs  defaults,nofail  0  2" >> /etc/fstab
        msg_ok "$(translate "Added to /etc/fstab")"
    fi

    DISK_PARTITION="$disk"
    systemctl daemon-reload 2>/dev/null || true
    return 0
}

add_proxmox_dir_storage() {
    local storage_id="$1"
    local path="$2"
    local content="$3"
    local storage_kind="dir"
    local pool_name="$storage_id"

    if [[ "${FILESYSTEM:-}" == "zfs" ]]; then
        storage_kind="zfspool"
    fi

    if ! command -v pvesm >/dev/null 2>&1; then
        msg_error "$(translate "pvesm command not found. This should not happen on Proxmox.")"
        return 1
    fi

    if pvesm status "$storage_id" >/dev/null 2>&1; then
        msg_warn "$(translate "Storage ID already exists:") $storage_id"
        if ! dialog --backtitle "ProxMenux" --title "$(translate "Storage Exists")" --yesno \
            "$(translate "Storage ID already exists. Do you want to remove and recreate it?")" \
            8 60; then
            return 0
        fi
        pvesm remove "$storage_id" 2>/dev/null || true
    fi

    msg_info "$(translate "Registering disk as Proxmox storage...")"
    local pvesm_output
    local add_ok=false
    if [[ "$storage_kind" == "zfspool" ]]; then
        if pvesm_output=$(pvesm add zfspool "$storage_id" \
            --pool "$pool_name" \
            --content "$content" 2>&1); then
            add_ok=true
        fi
    else
        if pvesm_output=$(pvesm add dir "$storage_id" \
            --path "$path" \
            --content "$content" 2>&1); then
            add_ok=true
        fi
    fi

    if [[ "$add_ok" == "true" ]]; then
        if [[ "$storage_kind" == "zfspool" ]]; then
            msg_ok "$(translate "ZFS storage added successfully to Proxmox!")"
            echo -e ""
            echo -e "${TAB}${BOLD}$(translate "Storage Added:")${CL}"
            echo -e "${TAB}${BGN}$(translate "Storage ID:")${CL} ${BL}$storage_id${CL}"
            echo -e "${TAB}${BGN}$(translate "Type:")${CL} ${BL}zfspool${CL}"
            echo -e "${TAB}${BGN}$(translate "Pool:")${CL} ${BL}$pool_name${CL}"
            echo -e "${TAB}${BGN}$(translate "Content Types:")${CL} ${BL}$content${CL}"
        else
            msg_ok "$(translate "Directory storage added successfully to Proxmox!")"
            echo -e ""
            echo -e "${TAB}${BOLD}$(translate "Storage Added:")${CL}"
            echo -e "${TAB}${BGN}$(translate "Storage ID:")${CL} ${BL}$storage_id${CL}"
            echo -e "${TAB}${BGN}$(translate "Path:")${CL} ${BL}$path${CL}"
            echo -e "${TAB}${BGN}$(translate "Content Types:")${CL} ${BL}$content${CL}"
        fi
        echo -e ""
        msg_ok "$(translate "Storage is now available in Proxmox web interface under Datacenter > Storage")"
        return 0
    else
        msg_error "$(translate "Failed to add storage to Proxmox.")"
        echo -e "${TAB}$(translate "Error details:"): $pvesm_output"
        echo -e ""
        msg_info2 "$(translate "You can add it manually through:")"
        if [[ "$storage_kind" == "zfspool" ]]; then
            echo -e "${TAB}• $(translate "Proxmox web interface: Datacenter > Storage > Add > ZFS")"
            echo -e "${TAB}• pvesm add zfspool $storage_id --pool $pool_name --content $content"
        else
            echo -e "${TAB}• $(translate "Proxmox web interface: Datacenter > Storage > Add > Directory")"
            echo -e "${TAB}• pvesm add dir $storage_id --path $path --content $content"
        fi
        return 1
    fi
}

# ==========================================================
# MAIN OPERATIONS
# ==========================================================

add_disk_to_proxmox() {
    # Check required tools
    for tool in parted mkfs.ext4 mkfs.xfs blkid lsblk sgdisk; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            show_proxmenux_logo
            msg_title "$(translate "Add Local Disk as Proxmox Storage")"
            msg_info "$(translate "Installing required tools...")"
            apt-get update &>/dev/null
            apt-get install -y parted e2fsprogs util-linux xfsprogs gdisk btrfs-progs &>/dev/null
            stop_spinner
            break
        fi
    done

    # Step 1: Select disk
    select_disk || return

    # Step 2: Inspect and choose action
    select_partition_action "$SELECTED_DISK" || return

    # Step 3: Filesystem selection (only if formatting)
    if [[ "$DISK_ACTION" == "format" ]]; then
        select_filesystem || return
        if [[ "$FILESYSTEM" == "zfs" ]] && ! command -v zpool >/dev/null 2>&1; then
            msg_error "$(translate "zpool not found. Install zfsutils-linux and retry.")"
            echo
            msg_success "$(translate "Press Enter to continue...")"
            read -r
            return 1
        fi
    fi

    # Step 3.5: Choose how the disk is exposed to Proxmox / the host.
    # Sets MODE_PVESM and MODE_FSTAB. ZFS is forced to MODE_PVESM=1
    # inside the helper because a ZFS pool can't be expressed as a
    # plain fstab mount.
    select_mount_method || return

    # Step 4: Configure storage options
    configure_disk_storage || return

    if declare -F _refresh_host_storage_cache >/dev/null 2>&1; then
        _refresh_host_storage_cache
    fi
    if disk_used_by_host_storage "$SELECTED_DISK"; then
        msg_error "$(translate "Safety check failed: selected disk is now used by host/system.")"
        echo
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi
    if disk_referenced_in_guest_configs "$SELECTED_DISK"; then
        msg_error "$(translate "Safety check failed: selected disk is referenced by a VM/LXC config.")"
        echo
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return 1
    fi

    # Step 5: Format/mount
    case "$DISK_ACTION" in
        format)
            format_and_mount_disk "$SELECTED_DISK" "$MOUNT_PATH" "$FILESYSTEM" || {
                echo ""
                msg_success "$(translate "Press Enter to continue...")"
                read -r
                return 1
            }
            mount_disk_permanently "$DISK_PARTITION" "$MOUNT_PATH" "$FILESYSTEM" || {
                echo ""
                msg_success "$(translate "Press Enter to continue...")"
                read -r
                return 1
            }
            ;;
        use_existing)
            local existing_node
            existing_node="${DISK_EXISTING_NODE:-$SELECTED_DISK}"
            mount_existing_disk "$existing_node" "$MOUNT_PATH" || {
                echo ""
                msg_success "$(translate "Press Enter to continue...")"
                read -r
                return 1
            }
            ;;
    esac

    # Step 6: Register in Proxmox (only if the user opted in)
    if [[ "$MODE_PVESM" -eq 1 ]]; then
        add_proxmox_dir_storage "$STORAGE_ID" "$MOUNT_PATH" "$MOUNT_CONTENT"
    else
        echo ""
        msg_ok "$(translate "Disk mounted at") $MOUNT_PATH"
        msg_info2 "$(translate "Not registered as Proxmox storage — use 'LXC Mount Manager' to bind-mount") $MOUNT_PATH $(translate "into an LXC.")"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

view_disk_storages() {
    show_proxmenux_logo
    msg_title "$(translate "Local Disk Storages in Proxmox")"

    echo "=================================================="
    echo ""

    if ! command -v pvesm >/dev/null 2>&1; then
        msg_error "$(translate "pvesm not found.")"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return
    fi

    # Show local storages managed by this menu (Directory + ZFS Pool), excluding system ones
    DIR_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "dir" || $2 == "zfspool" {print $1, $2, $3}')
    local user_storage_found=false
    if [[ -n "$DIR_STORAGES" ]]; then
        while IFS=" " read -r s_id s_type _; do
            [[ -z "$s_id" ]] && continue
            _is_user_disk_storage "$s_id" "$s_type" || continue
            user_storage_found=true
            break
        done <<< "$DIR_STORAGES"
    fi
    if [[ "$user_storage_found" == "false" ]]; then
        msg_warn "$(translate "No local storage configured in Proxmox.")"
        echo ""
        msg_info2 "$(translate "Use option 1 to add a local disk as Proxmox storage.")"
    else
        echo -e "${BOLD}$(translate "Local Storages:")${CL}"
        echo ""
        while IFS=" " read -r storage_id storage_type storage_status; do
            [[ -z "$storage_id" ]] && continue
            _is_user_disk_storage "$storage_id" "$storage_type" || continue
            local storage_info path content pool
            storage_info=$(get_storage_config "$storage_id")
            path=$(echo "$storage_info" | awk '$1 == "path" {print $2}')
            pool=$(echo "$storage_info" | awk '$1 == "pool" {print $2}')
            content=$(echo "$storage_info" | awk '$1 == "content" {print $2}')

            local disk_device=""
            if [[ -n "$path" ]]; then
                disk_device=$(findmnt -n -o SOURCE "$path" 2>/dev/null || true)
            fi

            local disk_size=""
            if [[ -n "$disk_device" ]]; then
                disk_size=$(lsblk -ndo SIZE "$disk_device" 2>/dev/null || true)
            fi

            echo -e "${TAB}${BOLD}$storage_id${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Type:")${CL} ${BL}${storage_type:-unknown}${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Path:")${CL} ${BL}$path${CL}"
            [[ -n "$pool" ]] && echo -e "${TAB}  ${BGN}$(translate "Pool:")${CL} ${BL}$pool${CL}"
            [[ -n "$disk_device" ]] && echo -e "${TAB}  ${BGN}$(translate "Device:")${CL} ${BL}$disk_device${CL}"
            [[ -n "$disk_size" ]] && echo -e "${TAB}  ${BGN}$(translate "Size:")${CL} ${BL}$disk_size${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Content:")${CL} ${BL}$content${CL}"
            if [[ "$storage_status" == "active" ]]; then
                echo -e "${TAB}  ${BGN}$(translate "Status:")${CL} ${GN}$(translate "Active")${CL}"
            else
                echo -e "${TAB}  ${BGN}$(translate "Status:")${CL} ${RD}$storage_status${CL}"
            fi
            echo ""
        done <<< "$DIR_STORAGES"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

_remove_pvesm_storage() {
    local storage_id="$1"
    local path pool content stype
    path=$(get_storage_config "$storage_id" | awk '$1 == "path" {print $2}')
    pool=$(get_storage_config "$storage_id" | awk '$1 == "pool" {print $2}')
    content=$(get_storage_config "$storage_id" | awk '$1 == "content" {print $2}')
    stype=$(pvesm status 2>/dev/null | awk -v id="$storage_id" '$1==id {print $2}')

    local msg
    msg="$(translate "WARNING: You are about to remove this Proxmox storage:")\n\n"
    msg+="  $(translate "Storage ID:") $storage_id\n"
    msg+="  $(translate "Type:") ${stype:-unknown}\n"
    [[ -n "$path" ]]    && msg+="  $(translate "Mount path:") $path\n"
    [[ -n "$pool" ]]    && msg+="  $(translate "ZFS pool:") $pool\n"
    [[ -n "$content" ]] && msg+="  $(translate "Content:") $content\n"
    msg+="\n$(translate "⚠ Disk data will NOT be erased.")\n"
    [[ -n "$path" ]] && msg+="$(translate "⚠ Disk will be unmounted and removed from /etc/fstab.")\n"
    [[ -n "$pool" ]] && msg+="$(translate "⚠ ZFS pool stays active — run 'zpool export $pool' to detach.")\n"
    msg+="\n$(translate "Continue?")"

    if ! dialog --backtitle "ProxMenux" --title "$(translate "Confirm Remove")" --yesno "$msg" 22 84; then
        return
    fi

    show_proxmenux_logo
    msg_title "$(translate "Remove Disk Storage")"

    # Step 1: Remove from Proxmox
    msg_info "$(translate "Removing storage from Proxmox...")"
    if ! pvesm remove "$storage_id" 2>/dev/null; then
        msg_error "$(translate "Failed to remove storage from Proxmox.")"
        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return
    fi
    msg_ok "$(translate "Storage") $storage_id $(translate "removed from Proxmox")"

    # Step 2: Unmount if mounted (dir-backed storages only)
    if [[ -n "$path" ]] && mountpoint -q "$path" 2>/dev/null; then
        msg_info "$(translate "Unmounting disk...")"
        if umount "$path" 2>/dev/null; then
            msg_ok "$(translate "Disk unmounted from") $path"
        else
            msg_warn "$(translate "Could not unmount") $path $(translate "— disk may be busy. Skipping fstab removal.")"
            echo ""
            msg_success "$(translate "Press Enter to continue...")"
            read -r
            return
        fi
    fi

    # Step 3: Remove /etc/fstab entry
    if [[ -n "$path" ]] && grep -q "[[:space:]]${path}[[:space:]]" /etc/fstab 2>/dev/null; then
        msg_info "$(translate "Removing from /etc/fstab...")"
        local tmp
        tmp=$(mktemp)
        awk -v mp="$path" '$2 != mp' /etc/fstab > "$tmp" && mv "$tmp" /etc/fstab
        systemctl daemon-reload 2>/dev/null || true
        msg_ok "$(translate "Removed from /etc/fstab")"
    fi

    # Step 3b: Export ZFS pool if applicable
    if [[ -n "$pool" ]] && zpool list "$pool" >/dev/null 2>&1; then
        msg_info "$(translate "Exporting ZFS pool...") $pool"
        if zpool export "$pool" 2>/dev/null; then
            msg_ok "$(translate "ZFS pool exported:") $pool"
        else
            msg_warn "$(translate "Could not export ZFS pool") $pool $(translate "— pool may be busy. Run manually: zpool export $pool")"
        fi
    fi

    # Step 4: Reboot prompt
    echo ""
    if whiptail --title "$(translate "Reboot Required")" --yesno \
        "\n$(translate "The storage has been removed and the disk unmounted.")\n\n$(translate "A server reboot is recommended for all changes to take full effect.")\n\n$(translate "Reboot now?")" \
        14 72; then
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        echo ""
        msg_warn "$(translate "Rebooting the system...")"
        reboot
    else
        echo ""
        msg_info2 "$(translate "Reboot pending — changes will take full effect after the next restart.")"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

_remove_fstab_entry() {
    local mount_point="$1"

    local fs fstype
    while IFS= read -r line; do
        [[ "$line" =~ ^# || -z "$line" ]] && continue
        local f mp ft
        read -r f mp ft _ <<< "$line"
        if [[ "$mp" == "$mount_point" ]]; then
            fs="$f"; fstype="$ft"; break
        fi
    done < /etc/fstab

    local device="$fs"
    if [[ "$fs" == UUID=* ]]; then
        device=$(blkid -U "${fs#UUID=}" 2>/dev/null || echo "$fs")
    fi
    local size=""
    [[ -b "$device" ]] && size=$(lsblk -ndo SIZE "$device" 2>/dev/null)

    local mounted=false
    findmnt -n "$mount_point" >/dev/null 2>&1 && mounted=true

    local msg
    msg="$(translate "WARNING: You are about to remove this disk mount:")\n\n"
    msg+="  $(translate "Mount point:") $mount_point\n"
    [[ -n "$device" && "$device" != "$fs" ]] && msg+="  $(translate "Device:") $device\n"
    msg+="  $(translate "Filesystem:") $fstype\n"
    [[ -n "$size" ]] && msg+="  $(translate "Size:") $size\n"
    local mounted_label; $mounted && mounted_label="$(translate "Yes")" || mounted_label="$(translate "No")"
    msg+="  $(translate "Currently mounted:") $mounted_label\n"
    msg+="\n$(translate "⚠ The disk will be unmounted.")\n"
    msg+="$(translate "⚠ The /etc/fstab entry will be removed.")\n"
    msg+="$(translate "⚠ Disk data will NOT be erased.")\n"
    msg+="\n$(translate "Continue?")"

    if dialog --backtitle "ProxMenux" --title "$(translate "Confirm Remove")" --yesno "$msg" 20 80; then
        show_proxmenux_logo
        msg_title "$(translate "Remove Disk from fstab")"

        if $mounted; then
            msg_info "$(translate "Unmounting") $mount_point..."
            if umount "$mount_point" 2>/dev/null; then
                msg_ok "$(translate "Unmounted successfully")"
            else
                msg_warn "$(translate "Could not unmount — disk may be busy. Removing fstab entry anyway.")"
            fi
        fi

        msg_info "$(translate "Removing from /etc/fstab...")"
        local tmp
        tmp=$(mktemp)
        awk -v mp="$mount_point" '$2 != mp' /etc/fstab > "$tmp"
        mv "$tmp" /etc/fstab
        systemctl daemon-reload 2>/dev/null || true
        msg_ok "$(translate "Removed from /etc/fstab")"

        echo ""
        msg_success "$(translate "Press Enter to continue...")"
        read -r
    fi
}

remove_disk_storage() {
    if ! command -v pvesm >/dev/null 2>&1; then
        dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
            --msgbox "\n$(translate "pvesm not found.")" 8 60
        return
    fi

    local OPTIONS=()
    local pvesm_paths=()

    # --- Source 1: pvesm user-created storages ---
    local ALL_STORAGES
    ALL_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "dir" || $2 == "zfspool" {print $1, $2}')
    while IFS= read -r line; do
        local storage_id storage_type
        storage_id=$(echo "$line" | awk '{print $1}')
        storage_type=$(echo "$line" | awk '{print $2}')
        [[ -z "$storage_id" ]] && continue
        _is_user_disk_storage "$storage_id" "$storage_type" || continue
        local path pool
        path=$(get_storage_config "$storage_id" | awk '$1 == "path" {print $2}')
        pool=$(get_storage_config "$storage_id" | awk '$1 == "pool" {print $2}')
        [[ -n "$path" ]] && pvesm_paths+=("$path")
        local label="[pvesm] ${storage_type}"
        [[ -n "$path" ]] && label+=" — $path"
        [[ -z "$path" && -n "$pool" ]] && label+=" — pool: $pool"
        OPTIONS+=("pvesm:$storage_id" "$label")
    done <<< "$ALL_STORAGES"

    # --- Source 2: fstab /mnt/ entries not already covered by pvesm ---
    while IFS= read -r line; do
        [[ "$line" =~ ^# || -z "$line" ]] && continue
        local fs mp fstype
        read -r fs mp fstype _ <<< "$line"
        [[ "$mp" == /mnt/* ]] || continue
        [[ "$fstype" == "proc" || "$fstype" == "sysfs" || "$fstype" == "tmpfs" || "$fstype" == "devtmpfs" || "$fstype" == "none" ]] && continue
        local covered=false
        for p in "${pvesm_paths[@]}"; do [[ "$p" == "$mp" ]] && covered=true && break; done
        $covered && continue
        local device="$fs"
        [[ "$fs" == UUID=* ]] && device=$(blkid -U "${fs#UUID=}" 2>/dev/null || echo "$fs")
        local size=""
        [[ -b "$device" ]] && size=$(lsblk -ndo SIZE "$device" 2>/dev/null)
        local label="[fstab] $mp ($fstype)"
        [[ -n "$size" ]] && label+=" [$size]"
        findmnt -n "$mp" >/dev/null 2>&1 && label+=" ✓" || label+=" (not mounted)"
        OPTIONS+=("fstab:$mp" "$label")
    done < /etc/fstab

    if [[ ${#OPTIONS[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Disk Storage")" \
            --msgbox "\n$(translate "No user-created disk storage or fstab mount found.")" 8 68
        return
    fi

    local SELECTED
    SELECTED=$(dialog --backtitle "ProxMenux" --title "$(translate "Remove Disk Storage")" \
        --menu "$(translate "Select storage to remove:")" 20 88 12 \
        "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED" ]] && return

    case "${SELECTED%%:*}" in
        pvesm) _remove_pvesm_storage "${SELECTED#pvesm:}" ;;
        fstab) _remove_fstab_entry   "${SELECTED#fstab:}" ;;
    esac
}

list_available_disks() {
    show_proxmenux_logo
    msg_title "$(translate "Available Disks on Host")"

    echo "=================================================="
    echo ""

    echo -e "${BOLD}$(translate "All block devices:")${CL}"
    echo ""
    lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL 2>/dev/null
    echo ""

    echo -e "${BOLD}$(translate "Proxmox local storages:")${CL}"
    if command -v pvesm >/dev/null 2>&1; then
        pvesm status 2>/dev/null | awk '$2 == "dir" || $2 == "zfspool" {print "  " $1, $2, $3}' || echo "  $(translate "None")"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

# ==========================================================
# MAIN MENU
# ==========================================================

while true; do
    CHOICE=$(dialog --backtitle "ProxMenux" \
        --title "$(translate "Local Disk Manager - Proxmox Host")" \
        --menu "$(translate "Choose an option:")" 18 70 6 \
        "1" "$(translate "Add Local Disk as Proxmox Storage")" \
        "2" "$(translate "View Disk Storages")" \
        "3" "$(translate "Remove Disk Storage")" \
        "4" "$(translate "List Available Disks")" \
        "5" "$(translate "Exit")" \
        3>&1 1>&2 2>&3)

    RETVAL=$?
    if [[ $RETVAL -ne 0 ]]; then
        exit 0
    fi

    case $CHOICE in
        1) add_disk_to_proxmox ;;
        2) view_disk_storages ;;
        3) remove_disk_storage ;;
        4) list_available_disks ;;
        5) exit 0 ;;
        *) exit 0 ;;
    esac
done
