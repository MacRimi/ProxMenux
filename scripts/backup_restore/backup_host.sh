#!/bin/bash
# ==========================================================
# ProxMenux - Host Config Backup / Restore
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.0
# Last Updated: 08/04/2026
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
    # shellcheck source=/dev/null
    source "$UTILS_FILE"
else
    echo "ERROR: utils.sh not found. Cannot continue." >&2
    exit 1
fi

# Source shared library
LIB_FILE="$SCRIPT_DIR/lib_host_backup_common.sh"
[[ ! -f "$LIB_FILE" ]] && LIB_FILE="$LOCAL_SCRIPTS_DEFAULT/backup_restore/lib_host_backup_common.sh"
if [[ -f "$LIB_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$LIB_FILE"
else
    msg_error "$(translate "Cannot load backup library: lib_host_backup_common.sh")"
    exit 1
fi

load_language
initialize_cache

if ! command -v pveversion >/dev/null 2>&1; then
    dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
        --msgbox "$(translate "This script must be run on a Proxmox host.")" 8 60
    exit 1
fi
if [[ $EUID -ne 0 ]]; then
    dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
        --msgbox "$(translate "This script must be run as root.")" 8 60
    exit 1
fi

# ==========================================================
# BACKUP — PBS
# ==========================================================
_bk_pbs() {
    local profile_mode="$1"
    local -a paths=()
    local backup_id epoch log_file staging_root t_start elapsed staged_size

    hb_select_pbs_repository || return 1
    hb_ask_pbs_encryption

    hb_select_profile_paths "$profile_mode" paths || return 1

    backup_id="hostcfg-$(hostname)"
    backup_id=$(dialog --backtitle "ProxMenux" --title "PBS" \
        --inputbox "$(hb_translate "Backup ID (group name in PBS):")" \
        "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "$backup_id" 3>&1 1>&2 2>&3) || return 1
    [[ -z "$backup_id" ]] && return 1
    # Sanitize: only alphanumeric, dash, underscore
    backup_id=$(echo "$backup_id" | tr -cs '[:alnum:]_-' '-' | sed 's/-*$//')

    log_file="/tmp/proxmenux-pbs-backup-$(date +%Y%m%d_%H%M%S).log"
    staging_root=$(mktemp -d /tmp/proxmenux-pbs-stage.XXXXXX)
    # shellcheck disable=SC2064
    trap "rm -rf '$staging_root'" RETURN

    show_proxmenux_logo
    msg_title "$(translate "Host Backup  →  PBS")"
    echo -e ""
    local _pbs_enc_label
    if [[ -n "$HB_PBS_KEYFILE_OPT" ]]; then _pbs_enc_label=$(hb_translate "Enabled"); else _pbs_enc_label=$(hb_translate "Disabled"); fi
    echo -e "${TAB}${BGN}$(translate "Repository:")${CL}  ${BL}${HB_PBS_REPOSITORY}${CL}"
    echo -e "${TAB}${BGN}$(translate "Backup ID:")${CL}   ${BL}${backup_id}${CL}"
    echo -e "${TAB}${BGN}$(translate "Encryption:")${CL}  ${BL}${_pbs_enc_label}${CL}"
    echo -e "${TAB}${BGN}$(translate "Paths:")${CL}"
    local p; for p in "${paths[@]}"; do echo -e "${TAB}    ${BL}•${CL} $p"; done
    echo -e ""

    msg_info "$(translate "Preparing files for backup...")"
    hb_prepare_staging "$staging_root" "${paths[@]}"
    staged_size=$(hb_file_size "$staging_root/rootfs")
    msg_ok "$(translate "Staging ready.") $(translate "Data size:") $staged_size"

    echo -e ""
    msg_info "$(translate "Connecting to PBS and starting backup...")"
    stop_spinner

    epoch=$(date +%s)
    t_start=$SECONDS

    # We back up the WHOLE staging_root (rootfs/ + metadata/) into
    # the .pxar — earlier versions used `$staging_root/rootfs` as
    # the source, which left metadata/ (hostname, pveversion,
    # selected paths, etc.) out of the archive. The compat check
    # in restore then had nothing to read and degraded to
    # cross-host warnings even on same-host restores. Old PBS
    # snapshots created with the rootfs-only source still restore
    # correctly via case 3 in _rs_check_layout (which wraps a flat
    # etc/var/root/usr layout into rootfs/ and creates an empty
    # metadata/), so this change is backward-compatible.
    local -a cmd=(
        proxmox-backup-client backup
        "hostcfg.pxar:$staging_root"
        --repository "$HB_PBS_REPOSITORY"
        --backup-type host
        --backup-id  "$backup_id"
        --backup-time "$epoch"
    )
    # shellcheck disable=SC2086  # intentional word-split: HB_PBS_KEYFILE_OPT="--keyfile /path"
    [[ -n "$HB_PBS_KEYFILE_OPT" ]] && cmd+=($HB_PBS_KEYFILE_OPT)

    : > "$log_file"
    if env \
        PBS_PASSWORD="$HB_PBS_SECRET" \
        PBS_ENCRYPTION_PASSWORD="${HB_PBS_ENC_PASS:-}" \
        PBS_FINGERPRINT="${HB_PBS_FINGERPRINT:-}" \
        "${cmd[@]}" 2>&1 | tee -a "$log_file"; then

        # Main backup OK — also upload the keyfile recovery blob if
        # one was configured. This runs as a SEPARATE backup group
        # (`host/proxmenux-keyrecovery-<host>`) with NO --keyfile,
        # so PBS stores it as a plain (non-PBS-encrypted) blob that
        # can be retrieved during fresh-install recovery. The blob
        # is still passphrase-protected by openssl.
        if [[ -f "$HB_STATE_DIR/pbs-key.recovery.enc" ]]; then
            hb_pbs_upload_recovery_blob "$epoch" \
                || msg_warn "$(translate "Recovery blob upload failed — main backup is OK, but keyfile recovery from PBS will not be available for this snapshot.")"
        fi

        elapsed=$((SECONDS - t_start))
        local snap_time
        snap_time=$(date -d "@$epoch" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || date -r "$epoch" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || echo "$epoch")
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Backup completed:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Method:")${CL}      ${BL}Proxmox Backup Server (PBS)${CL}"
        echo -e "${TAB}${BGN}$(translate "Repository:")${CL}  ${BL}${HB_PBS_REPOSITORY}${CL}"
        echo -e "${TAB}${BGN}$(translate "Backup ID:")${CL}   ${BL}${backup_id}${CL}"
        echo -e "${TAB}${BGN}$(translate "Snapshot:")${CL}    ${BL}host/${backup_id}/${snap_time}${CL}"
        echo -e "${TAB}${BGN}$(translate "Data size:")${CL}   ${BL}${staged_size}${CL}"
        echo -e "${TAB}${BGN}$(translate "Duration:")${CL}    ${BL}$(hb_human_elapsed "$elapsed")${CL}"
        echo -e "${TAB}${BGN}$(translate "Encryption:")${CL}  ${BL}${_pbs_enc_label}${CL}"
        # Only point at the log if it actually has output. On a clean
        # success the underlying tool is silent and surfacing an empty
        # file path just confuses the operator into thinking they need
        # to look at it.
        [[ -s "$log_file" ]] && echo -e "${TAB}${BGN}$(translate "Log:")${CL}         ${BL}${log_file}${CL}"
        echo -e ""
        msg_ok "$(translate "Backup completed successfully.")"
    else
        echo -e ""
        msg_error "$(translate "PBS backup failed.")"
        hb_show_log "$log_file" "$(translate "PBS backup error log")"
        echo -e ""
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

# ==========================================================
# BACKUP — BORG
# ==========================================================
_bk_borg() {
    local profile_mode="$1"
    local -a paths=()
    local borg_bin repo staging_root log_file t_start elapsed staged_size archive_name

    borg_bin=$(hb_ensure_borg) || return 1
    hb_select_borg_repo repo || return 1
    hb_prepare_borg_passphrase || return 1
    hb_select_profile_paths "$profile_mode" paths || return 1

    archive_name="hostcfg-$(hostname)-$(date +%Y%m%d_%H%M%S)"
    log_file="/tmp/proxmenux-borg-backup-$(date +%Y%m%d_%H%M%S).log"
    staging_root=$(mktemp -d /tmp/proxmenux-borg-stage.XXXXXX)
    # shellcheck disable=SC2064
    trap "rm -rf '$staging_root'" RETURN

    show_proxmenux_logo
    msg_title "$(translate "Host Backup  →  Borg")"
    echo -e ""
    local _borg_enc_label
    if [[ "${BORG_ENCRYPT_MODE:-none}" == "repokey" ]]; then _borg_enc_label=$(hb_translate "Enabled (repokey)"); else _borg_enc_label=$(hb_translate "Disabled"); fi
    echo -e "${TAB}${BGN}$(translate "Repository:")${CL}  ${BL}${repo}${CL}"
    echo -e "${TAB}${BGN}$(translate "Archive:")${CL}     ${BL}${archive_name}${CL}"
    echo -e "${TAB}${BGN}$(translate "Encryption:")${CL}  ${BL}${_borg_enc_label}${CL}"
    echo -e "${TAB}${BGN}$(translate "Paths:")${CL}"
    local p; for p in "${paths[@]}"; do echo -e "${TAB}    ${BL}•${CL} $p"; done
    echo -e ""

    msg_info "$(translate "Preparing files for backup...")"
    hb_prepare_staging "$staging_root" "${paths[@]}"
    staged_size=$(hb_file_size "$staging_root/rootfs")
    msg_ok "$(translate "Staging ready.") $(translate "Data size:") $staged_size"

    msg_info "$(translate "Initializing Borg repository if needed...")"
    if ! hb_borg_init_if_needed "$borg_bin" "$repo" "${BORG_ENCRYPT_MODE:-none}" >/dev/null 2>&1; then
        msg_error "$(translate "Failed to initialize Borg repository at:") $repo"
        return 1
    fi
    msg_ok "$(translate "Repository ready.")"

    echo -e ""
    msg_info "$(translate "Starting Borg backup...")"
    stop_spinner

    t_start=$SECONDS
    : > "$log_file"
    if (cd "$staging_root" && "$borg_bin" create --stats --progress \
        "$repo::$archive_name" rootfs metadata) 2>&1 | tee -a "$log_file"; then

        elapsed=$((SECONDS - t_start))
        # Extract compressed size from borg stats if available
        local borg_compressed
        borg_compressed=$(grep -i "this archive" "$log_file" | awk '{print $4, $5}' | tail -1)
        [[ -z "$borg_compressed" ]] && borg_compressed="$staged_size"
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Backup completed:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Method:")${CL}          ${BL}BorgBackup${CL}"
        echo -e "${TAB}${BGN}$(translate "Repository:")${CL}      ${BL}${repo}${CL}"
        echo -e "${TAB}${BGN}$(translate "Archive:")${CL}         ${BL}${archive_name}${CL}"
        echo -e "${TAB}${BGN}$(translate "Data size:")${CL}       ${BL}${staged_size}${CL}"
        echo -e "${TAB}${BGN}$(translate "Compressed size:")${CL} ${BL}${borg_compressed}${CL}"
        echo -e "${TAB}${BGN}$(translate "Duration:")${CL}        ${BL}$(hb_human_elapsed "$elapsed")${CL}"
        echo -e "${TAB}${BGN}$(translate "Encryption:")${CL}      ${BL}${_borg_enc_label}${CL}"
        [[ -s "$log_file" ]] && echo -e "${TAB}${BGN}$(translate "Log:")${CL}             ${BL}${log_file}${CL}"
        echo -e ""
        msg_ok "$(translate "Backup completed successfully.")"
    else
        echo -e ""
        msg_error "$(translate "Borg backup failed.")"
        hb_show_log "$log_file" "$(translate "Borg backup error log")"
        echo -e ""
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

# ==========================================================
# BACKUP — LOCAL tar
# ==========================================================
_bk_local() {
    local profile_mode="$1"
    local -a paths=()
    local dest_dir staging_root archive log_file t_start elapsed staged_size archive_size

    hb_require_cmd rsync rsync || return 1

    dest_dir=$(hb_prompt_dest_dir) || return 1
    hb_select_profile_paths "$profile_mode" paths || return 1

    # Safety check: if the destination directory is INSIDE any selected
    # backup path, creating the archive would copy the backup into
    # itself — recursion → corrupted archive or unbounded growth that
    # fills the disk. Common footgun when an operator adds a custom
    # path like /var/lib/vz and then picks /var/lib/vz/dump as
    # destination, or the default profile's /root and a destination
    # under /root/.
    local dest_real conflict=""
    dest_real=$(readlink -m "$dest_dir" 2>/dev/null || echo "$dest_dir")
    local p_real p
    for p in "${paths[@]}"; do
        p_real=$(readlink -m "$p" 2>/dev/null || echo "$p")
        if [[ "$dest_real" == "$p_real" || "$dest_real" == "$p_real"/* ]]; then
            conflict="$p"
            break
        fi
    done
    if [[ -n "$conflict" ]]; then
        local body
        body="$(translate "The archive destination directory is INSIDE one of the paths you are about to back up. Writing the archive there would copy the backup into itself — producing a corrupted archive, or growing without limit until the disk fills up.")"$'\n\n'
        body+="\Zb$(translate "Destination:")\ZB  \Z4${dest_dir}\Zn"$'\n'
        body+="\Zb$(translate "Conflicting path included in backup:")\ZB  \Z1${conflict}\Zn"$'\n\n'
        body+="$(translate "To fix this, do ONE of the following:")"$'\n'
        body+="  • $(translate "Choose a destination directory OUTSIDE of") ${conflict}"$'\n'
        body+="  • $(translate "Go to \"Manage custom paths\" and remove your custom entry that includes the destination")"$'\n'
        body+="  • $(translate "Use Custom backup and uncheck the conflicting path from the list")"
        dialog --backtitle "ProxMenux" --colors \
            --title "$(translate "Backup destination is inside the backup")" \
            --msgbox "$body" 20 88
        return 1
    fi

    archive="$dest_dir/hostcfg-$(hostname)-$(date +%Y%m%d_%H%M%S).tar.zst"
    log_file="/tmp/proxmenux-local-backup-$(date +%Y%m%d_%H%M%S).log"
    staging_root=$(mktemp -d /tmp/proxmenux-local-stage.XXXXXX)
    # shellcheck disable=SC2064
    trap "rm -rf '$staging_root'" RETURN

    show_proxmenux_logo
    msg_title "$(translate "Host Backup  →  Local archive")"
    echo -e ""
    echo -e "${TAB}${BGN}$(translate "Destination:")${CL}  ${BL}${archive}${CL}"
    echo -e "${TAB}${BGN}$(translate "Paths:")${CL}"
    local p; for p in "${paths[@]}"; do echo -e "${TAB}    ${BL}•${CL} $p"; done
    echo -e ""

    msg_info "$(translate "Preparing files for backup...")"
    hb_prepare_staging "$staging_root" "${paths[@]}"
    staged_size=$(hb_file_size "$staging_root/rootfs")
    msg_ok "$(translate "Staging ready.") $(translate "Data size:") $staged_size"

    echo -e ""
    msg_info "$(translate "Creating compressed archive...")"
    stop_spinner

    t_start=$SECONDS
    : > "$log_file"
    local tar_ok=0

    if command -v zstd >/dev/null 2>&1; then
        if tar --zstd -cf "$archive" -C "$staging_root" . >>"$log_file" 2>&1; then
            tar_ok=1
        fi
    else
        # Fallback: gzip (rename archive)
        archive="${archive%.zst}"
        archive="${archive%.tar}.tar.gz"
        if hb_ensure_pv; then
            local stage_bytes
            local pipefail_state
            stage_bytes=$(du -sb "$staging_root" 2>/dev/null | awk '{print $1}')
            pipefail_state=$(set -o | awk '$1=="pipefail" {print $2}')
            set -o pipefail
            if tar -cf - -C "$staging_root" . 2>>"$log_file" \
                | pv -s "$stage_bytes" | gzip > "$archive" 2>>"$log_file"; then
                tar_ok=1
            fi
            [[ "$pipefail_state" == "off" ]] && set +o pipefail
        else
            if tar -czf "$archive" -C "$staging_root" . >>"$log_file" 2>&1; then
                tar_ok=1
            fi
        fi
    fi

    elapsed=$((SECONDS - t_start))

    if [[ $tar_ok -eq 1 && -f "$archive" ]]; then
        # Drop a sidecar JSON next to the archive so the Monitor
        # (and any future tooling) can identify this as a
        # ProxMenux host backup regardless of any future rename.
        hb_write_archive_sidecar "$archive" "manual" "" "$profile_mode" || true

        archive_size=$(hb_file_size "$archive")
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Backup completed:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Method:")${CL}          ${BL}Local archive (tar)${CL}"
        echo -e "${TAB}${BGN}$(translate "Archive:")${CL}         ${BL}${archive}${CL}"
        echo -e "${TAB}${BGN}$(translate "Data size:")${CL}       ${BL}${staged_size}${CL}"
        echo -e "${TAB}${BGN}$(translate "Archive size:")${CL}    ${BL}${archive_size}${CL}"
        echo -e "${TAB}${BGN}$(translate "Duration:")${CL}        ${BL}$(hb_human_elapsed "$elapsed")${CL}"
        [[ -s "$log_file" ]] && echo -e "${TAB}${BGN}$(translate "Log:")${CL}             ${BL}${log_file}${CL}"
        echo -e ""
        msg_ok "$(translate "Backup completed successfully.")"
    else
        echo -e ""
        msg_error "$(translate "Local backup failed.")"
        hb_show_log "$log_file" "$(translate "Local backup error log")"
        echo -e ""
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi

    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

# ==========================================================
# BACKUP MENU
# ==========================================================
_bk_scheduler() {
    local scheduler="$LOCAL_SCRIPTS/backup_restore/backup_scheduler.sh"
    [[ ! -f "$scheduler" ]] && scheduler="$SCRIPT_DIR/backup_scheduler.sh"

    if [[ ! -f "$scheduler" ]]; then
        show_proxmenux_logo
        msg_error "$(translate "Scheduler script not found:") $scheduler"
        echo -e ""
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi

    bash "$scheduler"
}

_bk_manage_local_destinations() {
    while true; do
        # Snapshot all currently mounted USB backup partitions with size info
        local -a usb_mp=()
        local -a usb_desc=()
        local state path_or_dev label size fstype uuid
        while IFS=$'\t' read -r state path_or_dev label size fstype uuid; do
            [[ "$state" != "mounted" ]] && continue
            local dfline
            dfline=$(df -h "$path_or_dev" 2>/dev/null | tail -1)
            local used="?" avail="?" pct="?"
            if [[ -n "$dfline" ]]; then
                used=$(awk '{print $3}'  <<<"$dfline")
                avail=$(awk '{print $4}' <<<"$dfline")
                pct=$(awk '{print $5}'   <<<"$dfline")
            fi
            usb_mp+=("$path_or_dev")
            usb_desc+=("${label:-?}  [${fstype}]  $size  →  $path_or_dev  ($used $(translate "used"), $avail $(translate "free"), $pct)")
        done < <(hb_list_usb_partitions)

        local body=""
        if (( ${#usb_desc[@]} == 0 )); then
            body+="$(translate "No USB drives are currently mounted by ProxMenux.")"
        else
            body+="\Zb$(translate "Mounted USB drives:")\ZB"$'\n'
            local d
            for d in "${usb_desc[@]}"; do
                body+="  • ${d}"$'\n'
            done
        fi
        body+=$'\n'"$(translate "Local destinations are file paths — they are NOT registered as Proxmox storage.")"

        local -a menu_args=()
        menu_args+=("mount"   "+ $(translate "Mount a USB drive now")")
        if (( ${#usb_mp[@]} > 0 )); then
            menu_args+=("unmount" "− $(translate "Unmount a USB drive")")
        fi
        menu_args+=("back"    "$(translate "← Return")")

        local choice
        choice=$(dialog --backtitle "ProxMenux" --colors \
            --title "$(translate "Local archive destinations")" \
            --menu "\n${body}\n" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${menu_args[@]}" \
            3>&1 1>&2 2>&3) || break

        case "$choice" in
            mount)
                # Reuse the runtime USB picker; result is discarded.
                hb_prompt_mounted_path "/mnt/backup" >/dev/null || true
                ;;
            unmount)
                if (( ${#usb_mp[@]} == 0 )); then
                    continue
                fi
                local unmenu=() j=1 mp
                for mp in "${usb_mp[@]}"; do
                    unmenu+=("$j" "$mp"); ((j++))
                done
                local pick
                pick=$(dialog --backtitle "ProxMenux" \
                    --title "$(translate "Unmount USB drive")" \
                    --menu "\n$(translate "Pick a drive to unmount:")" \
                    "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${unmenu[@]}" \
                    3>&1 1>&2 2>&3) || continue
                local victim="${usb_mp[$((pick-1))]}"
                if umount "$victim" 2>/tmp/proxmenux-umount.log; then
                    rmdir "$victim" 2>/dev/null || true
                    dialog --backtitle "ProxMenux" --colors \
                        --msgbox "$(translate "Unmounted") \Z4${victim}\Zn" 8 70
                else
                    local err
                    err=$(cat /tmp/proxmenux-umount.log 2>/dev/null)
                    dialog --backtitle "ProxMenux" --colors \
                        --title "$(translate "Unmount failed")" \
                        --msgbox "$(translate "Could not unmount") \Z1${victim}\Zn.\n\n${err}" 12 78
                fi
                ;;
            back) break ;;
        esac
    done
}

_bk_manage_destinations() {
    while true; do
        local choice
        choice=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Configure backup destinations")" \
            --menu "\n$(translate "Pre-configure destinations so you don't have to enter them every time you back up.")" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
            1   "$(translate "Proxmox Backup Server (PBS) destinations")" \
            2   "$(translate "Borg repositories")" \
            3   "$(translate "Local archive destinations (mounted USBs, mount, unmount)")" \
            0   "$(translate "Return")" \
            3>&1 1>&2 2>&3) || break

        case "$choice" in
            1)
                hb_select_pbs_repository || true
                ;;
            2)
                local _discard=""
                hb_select_borg_repo _discard || true
                ;;
            3)
                _bk_manage_local_destinations
                ;;
            0) break ;;
        esac
    done
}

_bk_manage_extra_paths() {
    while true; do
        local -a paths=()
        mapfile -t paths < <(hb_load_extra_paths)
        local count=${#paths[@]}

        # Descriptive header for the manage menu. We avoid listing the actual
        # paths here — a user with dozens of entries would blow the dialog
        # box height and force scrolling. The count is enough; "− Remove a
        # path" shows the full list when the user actually needs to see it.
        local preview=""
        if (( count == 0 )); then
            preview="$(hb_translate "You haven't added any custom paths yet.")"
        else
            preview="$(hb_translate "Currently"): \Zb\Z4${count}\Zn $(hb_translate "custom path(s) saved.")"
        fi
        preview+=$'\n\n'"$(hb_translate "Custom paths are included in BOTH default and custom backup profiles.")"

        local choice
        choice=$(dialog --backtitle "ProxMenux" --colors \
            --title "$(translate "Manage custom backup paths")" \
            --menu "\n${preview}\n" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
            "add"  "$(translate "+ Add a path")" \
            "del"  "$(translate "− Remove a path")" \
            "back" "$(translate "← Return")" \
            3>&1 1>&2 2>&3) || break

        case "$choice" in
            add)
                local new_path
                new_path=$(dialog --backtitle "ProxMenux" \
                    --title "$(translate "Add custom path")" \
                    --inputbox "$(translate "Absolute path to a file or directory you want backed up:")" \
                    "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "/root/" 3>&1 1>&2 2>&3) || continue
                new_path="${new_path%/}"
                [[ -z "$new_path" ]] && continue
                if [[ ! -e "$new_path" ]]; then
                    dialog --backtitle "ProxMenux" --colors \
                        --title "$(translate "Path not found")" \
                        --msgbox "\Z1${new_path}\Zn\n\n$(translate "does not exist on this host. Path not added.")" 10 70
                    continue
                fi
                hb_add_extra_path "$new_path"
                ;;
            del)
                if (( count == 0 )); then
                    dialog --backtitle "ProxMenux" --msgbox \
                        "$(translate "You haven't added any custom paths yet.")" 8 60
                    continue
                fi
                local del_options=() j=1 p
                for p in "${paths[@]}"; do
                    del_options+=("$j" "$p" "off"); ((j++))
                done
                local del_selected
                del_selected=$(dialog --backtitle "ProxMenux" \
                    --title "$(translate "Remove custom paths")" \
                    --default-button ok \
                    --separate-output --checklist \
                    "\n$(translate "Tick the paths to remove (they will not be deleted from disk — only from this list):")" \
                    "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${del_options[@]}" \
                    3>&1 1>&2 2>&3) || continue
                # Empty selection → nothing to do
                [[ -z "$del_selected" ]] && continue
                local sel
                while read -r sel; do
                    [[ -z "$sel" ]] && continue
                    hb_del_extra_path "${paths[$((sel-1))]}"
                done <<< "$del_selected"
                ;;
            back) break ;;
        esac
    done
}

backup_menu() {
    while true; do
        local choice
        choice=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Host Config Backup")" \
            --menu "\n$(translate "Select backup method and profile:")" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
            ""  "$(translate "─── Default profile  (all critical paths) ──────────")" \
            1   "$(translate "Backup to Proxmox Backup Server (PBS)")" \
            2   "$(translate "Backup to Borg repository")" \
            3   "$(translate "Backup to local archive  (.tar.zst)")" \
            ""  "$(translate "─── Custom profile  (choose paths manually) ────────")" \
            4   "$(translate "Custom backup to PBS")" \
            5   "$(translate "Custom backup to Borg")" \
            6   "$(translate "Custom backup to local archive")" \
            0   "$(translate "Return")" \
            3>&1 1>&2 2>&3) || return 0

        case "$choice" in
            1) _bk_pbs   default ;;
            2) _bk_borg  default ;;
            3) _bk_local default ;;
            4) _bk_pbs   custom  ;;
            5) _bk_borg  custom  ;;
            6) _bk_local custom  ;;
            0) break ;;
        esac
    done
}

# ==========================================================
# RESTORE — EXTRACT TO STAGING
# ==========================================================
_rs_extract_pbs() {
    local staging_root="$1"
    local log_file
    log_file="/tmp/proxmenux-pbs-restore-$(date +%Y%m%d_%H%M%S).log"
    local -a snapshots=() archives=()
    local snapshot archive

    hb_require_cmd proxmox-backup-client proxmox-backup-client || return 1
    hb_select_pbs_repository || return 1

    # If we're restoring on a fresh host (or one where the keyfile
    # was wiped) the encrypted snapshots are unreadable until we
    # restore the keyfile. Look for a recovery blob in PBS and let
    # the operator decrypt it with their passphrase. We try this
    # silently up-front so subsequent steps (snapshot list, files,
    # restore) Just Work whether or not the snapshots happen to be
    # encrypted. Failure here is non-fatal: a missing recovery
    # blob plus an unencrypted snapshot is a perfectly valid case
    # and the rest of the flow handles it.
    if [[ ! -f "$HB_STATE_DIR/pbs-key.conf" ]]; then
        hb_pbs_try_keyfile_recovery "$HB_STATE_DIR/pbs-key.conf" || true
    fi

    # Current proxmox-backup-client prints both `snapshot list` and
    # `snapshot files` as a Unicode box-drawing table even when piped
    # — the old awk-by-whitespace parser captures the `│` column
    # separators instead of the data and ends up with an empty array.
    # We now request --output-format json and parse with jq, then
    # convert the epoch returned by `snapshot list` to the UTC ISO
    # form (`YYYY-MM-DDTHH:MM:SSZ`) that `snapshot files` and
    # `restore` actually accept as the snapshot path.
    #
    # Use dialog --infobox (not msg_info/msg_ok) so the "Listing…"
    # placeholder lives inside the dialog system and disappears the
    # moment the next dialog draws — no terminal text leaks between
    # menus.
    dialog --backtitle "ProxMenux" \
        --title "$(translate "Listing snapshots from PBS")" \
        --infobox "\n$(translate "Querying repository:") $HB_PBS_REPOSITORY" 7 78
    mapfile -t snapshots < <(
        PBS_PASSWORD="$HB_PBS_SECRET" \
        PBS_FINGERPRINT="${HB_PBS_FINGERPRINT:-}" \
        proxmox-backup-client snapshot list \
            --repository "$HB_PBS_REPOSITORY" \
            --output-format json 2>/dev/null \
        | jq -r '.[] | select(."backup-type" == "host" and ((."backup-id" | startswith("proxmenux-keyrecovery-")) | not)) | "\(."backup-type")|\(."backup-id")|\(."backup-time")"' 2>/dev/null \
        | while IFS='|' read -r _type _id _epoch; do
            local _iso
            _iso=$(date -u -d "@${_epoch}" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null \
                || date -u -r "${_epoch}" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null \
                || echo "${_epoch}")
            echo "${_type}/${_id}/${_iso}"
        done \
        | sort -r | awk '!seen[$0]++'
    )

    if [[ ${#snapshots[@]} -eq 0 ]]; then
        # Surface error as a blocking dialog so the operator can read
        # it. msg_error alone gets erased the moment we `return 1`
        # because the restore_menu loop redraws the source picker
        # immediately afterward.
        dialog --backtitle "ProxMenux" --title "$(translate "No snapshots")" \
            --msgbox "$(translate "No host snapshots were found in this PBS repository:")"$'\n\n'"$HB_PBS_REPOSITORY" \
            10 78
        return 1
    fi

    local menu=() i=1
    for snapshot in "${snapshots[@]}"; do menu+=("$i" "$snapshot"); ((i++)); done
    local sel
    sel=$(dialog --backtitle "ProxMenux" \
        --title "$(translate "Select snapshot to restore")" \
        --menu "\n$(translate "Available host snapshots:")" \
        "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${menu[@]}" 3>&1 1>&2 2>&3) || return 1
    snapshot="${snapshots[$((sel-1))]}"

    # `snapshot files` filenames carry a `.didx` (chunk index) or
    # `.blob` suffix that doesn't match the bare `.pxar` name that
    # `restore` expects. Strip it before filtering.
    mapfile -t archives < <(
        PBS_PASSWORD="$HB_PBS_SECRET" \
        PBS_FINGERPRINT="${HB_PBS_FINGERPRINT:-}" \
        proxmox-backup-client snapshot files "$snapshot" \
            --repository "$HB_PBS_REPOSITORY" \
            --output-format json 2>/dev/null \
        | jq -r '.[].filename' 2>/dev/null \
        | sed -e 's/\.didx$//' -e 's/\.blob$//' \
        | grep '\.pxar$' || true
    )
    if [[ ${#archives[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No archives")" \
            --msgbox "$(translate "No .pxar archives were found in this snapshot:")"$'\n\n'"$snapshot" \
            10 78
        return 1
    fi

    if printf '%s\n' "${archives[@]}" | grep -qx "hostcfg.pxar"; then
        archive="hostcfg.pxar"
    else
        menu=(); i=1
        for archive in "${archives[@]}"; do menu+=("$i" "$archive"); ((i++)); done
        sel=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Select archive")" \
            --menu "\n$(translate "Available archives:")" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
            "${menu[@]}" 3>&1 1>&2 2>&3) || return 1
        archive="${archives[$((sel-1))]}"
    fi

    show_proxmenux_logo
    msg_title "$(translate "Restore from PBS  →  staging")"
    echo -e ""
    echo -e "${TAB}${BGN}$(translate "Repository:")${CL}       ${BL}${HB_PBS_REPOSITORY}${CL}"
    echo -e "${TAB}${BGN}$(translate "Snapshot:")${CL}         ${BL}${snapshot}${CL}"
    echo -e "${TAB}${BGN}$(translate "Archive:")${CL}          ${BL}${archive}${CL}"
    echo -e "${TAB}${BGN}$(translate "Staging directory:")${CL} ${BL}${staging_root}${CL}"
    echo -e ""
    msg_info "$(translate "Extracting data from PBS...")"
    stop_spinner

    local key_opt="" enc_pass=""
    [[ -f "$HB_STATE_DIR/pbs-key.conf" ]] && key_opt="--keyfile $HB_STATE_DIR/pbs-key.conf"
    [[ -f "$HB_STATE_DIR/pbs-encryption-pass.txt" ]] && \
        enc_pass="$(<"$HB_STATE_DIR/pbs-encryption-pass.txt")"

    : > "$log_file"
    # PIPESTATUS check: `... | tee` masks the binary's exit code
    # with tee's (always 0). Without this, a failed decrypt or
    # missing keyfile would silently "succeed" — the staging
    # would be empty/garbage and _rs_check_layout would then say
    # "Incompatible archive", which is misleading. We capture the
    # client's actual exit code separately.
    local pbs_rc
    # shellcheck disable=SC2086
    env \
        PBS_PASSWORD="$HB_PBS_SECRET" \
        PBS_ENCRYPTION_PASSWORD="${enc_pass}" \
        PBS_FINGERPRINT="${HB_PBS_FINGERPRINT:-}" \
        proxmox-backup-client restore \
            "$snapshot" "$archive" "$staging_root" \
            --repository "$HB_PBS_REPOSITORY" \
            --allow-existing-dirs true \
            $key_opt \
        2>&1 | tee -a "$log_file"
    pbs_rc=${PIPESTATUS[0]}

    if [[ $pbs_rc -eq 0 ]]; then
        msg_ok "$(translate "Extraction completed.")"
        return 0
    fi

    # Decide whether this is the "encrypted snapshot without
    # keyfile" pattern. proxmox-backup-client emits messages like
    # `unable to load encryption key` / `no key found` / `Failed
    # to decrypt` when that's the cause. If so, surface a helpful
    # error rather than the raw log.
    local extra_hint=""
    if grep -qiE 'encryption key|unable to (load|read) key|no key (file|found)|decrypt|failed to decrypt' "$log_file" 2>/dev/null; then
        extra_hint=$'\n\n'"$(translate "This snapshot is encrypted but no keyfile is available on this host.")"
        if [[ -f "$HB_STATE_DIR/pbs-key.conf" ]]; then
            extra_hint+=$'\n\n'"$(translate "A keyfile is present but doesn't match the one used to create the snapshot. Make sure you have the correct keyfile from the source host.")"
        else
            extra_hint+=$'\n\n'"$(translate "No keyfile recovery copy was found in PBS for this snapshot — it was created before the recovery feature existed. The encrypted content cannot be recovered.")"
        fi
    fi

    dialog --backtitle "ProxMenux" --title "$(translate "PBS extraction failed")" \
        --msgbox "$(translate "Could not extract from PBS.")"$'\n\n'"$(translate "Snapshot:") $snapshot"$'\n'"$(translate "Archive:") $archive$extra_hint" \
        16 78
    hb_show_log "$log_file" "$(translate "PBS restore error log")"
    return 1
}

_rs_extract_borg() {
    local staging_root="$1"
    local borg_bin repo log_file
    log_file="/tmp/proxmenux-borg-restore-$(date +%Y%m%d_%H%M%S).log"
    local -a archives=()
    local archive

    borg_bin=$(hb_ensure_borg) || return 1
    hb_select_borg_repo repo || return 1
    # Same persistence path as backup: per-target pw file
    # ($HB_STATE_DIR/borg-pass-<name>.txt), legacy global pw, or
    # prompt-once-and-save fallback. Bug fix: the old code only
    # honored the legacy global file and re-prompted otherwise,
    # defeating the saved-target UX.
    hb_prepare_borg_passphrase || return 1

    # Pull NAME|START in one shot — borg supports strftime via :%fmt
    # in --format. Sort newest-first by the ISO timestamp so the most
    # recent backup is always on top regardless of archive naming.
    local -a archive_lines=()
    mapfile -t archive_lines < <(
        "$borg_bin" list "$repo" \
            --format '{start:%Y-%m-%d %H:%M:%S}|{archive}{NL}' </dev/null 2>/dev/null \
            | sort -r
    )
    if [[ ${#archive_lines[@]} -eq 0 ]]; then
        msg_error "$(translate "No archives found in this Borg repository.")"
        return 1
    fi
    archives=()
    local -a archive_labels=()
    local _start _name
    for line in "${archive_lines[@]}"; do
        _start="${line%%|*}"
        _name="${line#*|}"
        archives+=("$_name")
        # Menu label: ISO datetime first (sortable, fixed width),
        # then archive name. Easier to scan when several backups
        # ran the same day.
        archive_labels+=("${_start}  ·  ${_name}")
    done

    local menu=() i=1
    for archive in "${archive_labels[@]}"; do menu+=("$i" "$archive"); ((i++)); done
    local sel
    sel=$(dialog --backtitle "ProxMenux" \
        --title "$(translate "Select archive to restore")" \
        --menu "\n$(translate "Available Borg archives (newest first):")" \
        "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
        "${menu[@]}" 3>&1 1>&2 2>&3) || return 1
    archive="${archives[$((sel-1))]}"

    show_proxmenux_logo
    msg_title "$(translate "Restore from Borg  →  staging")"
    echo -e ""
    echo -e "${TAB}${BGN}$(translate "Repository:")${CL}       ${BL}${repo}${CL}"
    echo -e "${TAB}${BGN}$(translate "Archive:")${CL}          ${BL}${archive}${CL}"
    echo -e "${TAB}${BGN}$(translate "Staging directory:")${CL} ${BL}${staging_root}${CL}"
    echo -e ""
    msg_info "$(translate "Extracting data from Borg...")"
    stop_spinner

    : > "$log_file"
    if (cd "$staging_root" && "$borg_bin" extract --progress \
        "$repo::$archive" 2>&1 | tee -a "$log_file"); then
        msg_ok "$(translate "Extraction completed.")"
        return 0
    else
        msg_error "$(translate "Borg extraction failed.")"
        hb_show_log "$log_file" "$(translate "Borg restore error log")"
        return 1
    fi
}

_rs_extract_local() {
    local staging_root="$1"
    local log_file source_dir archive

    hb_require_cmd tar tar || return 1
    source_dir=$(hb_prompt_restore_source_dir) || return 1

    # Loop the picker on every recoverable failure so a corrupt
    # archive doesn't dump the operator back to the top-level
    # restore menu (which they then read as "the script never
    # offered me a restore mode"). They stay in the same dir,
    # pick another archive, or explicitly cancel out.
    while true; do
        archive=$(hb_prompt_local_archive "$source_dir" \
            "$(translate "Select backup archive to restore")") || return 1

        log_file="/tmp/proxmenux-local-restore-$(date +%Y%m%d_%H%M%S).log"

        show_proxmenux_logo
        msg_title "$(translate "Restore from local archive  →  staging")"
        echo -e ""
        echo -e "${TAB}${BGN}$(translate "Archive:")${CL}          ${BL}${archive}${CL}"
        echo -e "${TAB}${BGN}$(translate "Archive size:")${CL}     ${BL}$(hb_file_size "$archive")${CL}"
        echo -e "${TAB}${BGN}$(translate "Staging directory:")${CL} ${BL}${staging_root}${CL}"
        echo -e ""
        msg_info "$(translate "Extracting archive...")"
        stop_spinner

        : > "$log_file"
        # Wipe staging from a previous failed attempt so we don't
        # mix partial extractions across retries.
        find "$staging_root" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null

        if [[ "$archive" == *.zst ]]; then
            tar --zstd -xf "$archive" -C "$staging_root" >>"$log_file" 2>&1
        else
            tar -xf "$archive" -C "$staging_root" >>"$log_file" 2>&1
        fi
        local rc=$?

        if [[ $rc -eq 0 ]]; then
            msg_ok "$(translate "Extraction completed.")"
            return 0
        fi

        msg_error "$(translate "Extraction failed.")"
        hb_show_log "$log_file" "$(translate "Local restore error log")"

        # Recoverable: most often a corrupted archive (interrupted
        # mid-write, bad disk sector, partial copy). Give the user
        # a clear next step instead of silently bouncing back.
        local recover_msg recover_choice
        recover_msg="$(translate "The archive could not be extracted.")"$'\n\n'
        recover_msg+="$(translate "Most common cause: the archive is corrupted (interrupted write, partial copy, or storage issue).")"$'\n\n'
        recover_msg+="$(translate "Archive:") $archive"
        recover_choice=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Restore failed")" \
            --menu "$recover_msg" 16 80 4 \
            1 "$(translate "Try another archive")" \
            2 "$(translate "Delete this corrupt archive and pick another")" \
            0 "$(translate "Cancel restore")" \
            3>&1 1>&2 2>&3) || return 1

        case "$recover_choice" in
            1) continue ;;  # back to the picker
            2)
                if whiptail --title "$(translate "Delete archive")" \
                    --yesno "$(translate "Permanently delete this archive and its sidecar?")"$'\n\n'"$archive" \
                    11 78; then
                    rm -f "$archive" "${archive}.proxmenux.json"
                    msg_ok "$(translate "Archive deleted.")"
                fi
                continue
                ;;
            0|*) return 1 ;;
        esac
    done
}

# Ensure staging has rootfs/ layout (Borg may nest)
_rs_check_layout() {
    local staging_root="$1"

    # Case 1: new format — rootfs/ already present
    [[ -d "$staging_root/rootfs" ]] && return 0

    # Case 2: nested format (old Borg archives may include absolute tmp paths)
    local -a rootfs_hits=()
    mapfile -t rootfs_hits < <(find "$staging_root" -mindepth 2 -maxdepth 6 -type d -name rootfs 2>/dev/null)
    if [[ ${#rootfs_hits[@]} -gt 1 ]]; then
        dialog --backtitle "ProxMenux" \
            --title "$(translate "Incompatible archive")" \
            --msgbox "$(translate "Multiple rootfs directories were found in this archive. Restore cannot continue automatically.")" \
            9 76 || true
        return 1
    fi
    if [[ ${#rootfs_hits[@]} -eq 1 ]]; then
        local rootfs_dir nested
        rootfs_dir="${rootfs_hits[0]}"
        nested="$(dirname "$rootfs_dir")"
        mv "$rootfs_dir" "$staging_root/rootfs"
        if [[ -d "$nested/metadata" ]]; then
            mv "$nested/metadata" "$staging_root/metadata"
        fi
        mkdir -p "$staging_root/metadata"
        return 0
    fi

    # Case 3: flat format — config dirs extracted directly at staging root
    # (archives created by older scripts that didn't use staging layout)
    if [[ -d "$staging_root/etc" || -d "$staging_root/var" || \
          -d "$staging_root/root" || -d "$staging_root/usr" ]]; then
        local tmp
        tmp=$(mktemp -d "$staging_root/.rootfs_wrap.XXXXXX")
        local item
        for item in "$staging_root"/*/; do
            [[ "$item" == "$tmp/" ]] && continue
            mv "$item" "$tmp/" 2>/dev/null || true
        done
        find "$staging_root" -maxdepth 1 -type f -exec mv {} "$tmp/" \; 2>/dev/null || true
        mv "$tmp" "$staging_root/rootfs"
        mkdir -p "$staging_root/metadata"
        return 0
    fi

    local incompatible_msg
    incompatible_msg="$(translate "This archive does not contain a recognized backup layout.")"$'\n\n'"$(translate "Expected: rootfs/ directory, or /etc /var /root at archive root.")"$'\n'"$(translate "Use 'Export to file' to save it and inspect manually.")"
    dialog --backtitle "ProxMenux" \
        --title "$(translate "Incompatible archive")" \
        --msgbox "$incompatible_msg" 12 72 || true
    return 1
}

# ==========================================================
# RESTORE — REVIEW & APPLY
# ==========================================================
_rs_show_metadata() {
    local staging_root="$1"
    local meta="$staging_root/metadata"
    local tmp
    tmp=$(mktemp) || return 1
    trap 'rm -f "$tmp"; trap - INT TERM; kill -s INT "$$"' INT TERM
    {
        echo "═══ $(hb_translate "Backup information") ═══"
        echo ""
        if [[ -f "$meta/run_info.env" ]]; then
            while IFS='=' read -r k v; do
                printf "  %-20s %s\n" "$k:" "$v"
            done < "$meta/run_info.env"
        fi
        echo ""
        echo "═══ $(hb_translate "Paths included in backup") ═══"
        if [[ -f "$meta/selected_paths.txt" ]]; then
            sed 's/^/  \//' "$meta/selected_paths.txt"
        fi
        echo ""
        if [[ -f "$meta/missing_paths.txt" && -s "$meta/missing_paths.txt" ]]; then
            echo "═══ $(hb_translate "Paths not found at backup time") ═══"
            sed 's/^/  /' "$meta/missing_paths.txt"
            echo ""
        fi
        if [[ -f "$meta/pveversion.txt" ]]; then
            echo "═══ Proxmox version ═══"
            cat "$meta/pveversion.txt"
            echo ""
        fi
        if [[ -f "$meta/lsblk.txt" ]]; then
            echo "═══ Disk layout (lsblk -f) ═══"
            cat "$meta/lsblk.txt"
            echo ""
        fi
    } > "$tmp"
    dialog --backtitle "ProxMenux" --exit-label "OK" \
        --title "$(translate "Backup metadata")" \
        --textbox "$tmp" 28 110 || true
    rm -f "$tmp"
    trap - INT TERM
}

_rs_preview_diff() {
    local staging_root="$1"
    local -a paths=()
    hb_load_restore_paths "$staging_root" paths
    local tmp
    tmp=$(mktemp) || return 1
    trap 'rm -f "$tmp"; trap - INT TERM; kill -s INT "$$"' INT TERM
    {
        echo "$(hb_translate "Diff: current system vs backup (--- system  +++ backup)")"
        echo ""
        local rel src dst
        for rel in "${paths[@]}"; do
            src="$staging_root/rootfs/$rel"
            dst="/$rel"
            [[ -e "$src" ]] || continue
            echo "══════ /$rel ══════"
            if [[ -d "$src" ]]; then
                diff -qr "$dst" "$src" 2>/dev/null || true
            else
                diff -u "$dst" "$src" 2>/dev/null || true
            fi
            echo ""
        done
    } > "$tmp"
    dialog --backtitle "ProxMenux" --exit-label "OK" \
        --title "$(translate "Preview: changes that would be applied")" \
        --textbox "$tmp" 28 130 || true
    rm -f "$tmp"
    trap - INT TERM
}

_rs_export_to_file() {
    local staging_root="$1"
    local dest_dir archive archive_size t_start elapsed log_file
    local stage_bytes pipefail_state tar_ok

    dest_dir=$(hb_prompt_dest_dir) || return 1
    archive="$dest_dir/hostcfg-export-$(hostname)-$(date +%Y%m%d_%H%M%S).tar.gz"
    log_file="/tmp/proxmenux-export-$(date +%Y%m%d_%H%M%S).log"

    show_proxmenux_logo
    msg_title "$(translate "Export backup data to file")"
    echo -e ""
    echo -e "${TAB}${BGN}$(translate "Staging source:")${CL} ${BL}${staging_root}${CL}"
    echo -e "${TAB}${BGN}$(translate "Output archive:")${CL} ${BL}${archive}${CL}"
    echo -e ""
    echo -e "${TAB}$(translate "No changes will be made to the running system.")"
    echo -e ""
    stop_spinner

    t_start=$SECONDS
    tar_ok=0
    : > "$log_file"

    if hb_ensure_pv; then
        # Stream tar through pv so the operator sees a live progress
        # bar instead of staring at a frozen title for minutes. We
        # mirror the same pattern used by the local backup path
        # (_bk_local) so the experience is consistent across
        # create-archive and export-archive flows.
        stage_bytes=$(du -sb "$staging_root" 2>/dev/null | awk '{print $1}')
        pipefail_state=$(set -o | awk '$1=="pipefail" {print $2}')
        set -o pipefail
        echo -e "${TAB}$(translate "Compressing")  $(numfmt --to=iec-i --suffix=B "$stage_bytes" 2>/dev/null || printf '%s bytes' "$stage_bytes")  →  $archive"
        echo
        if tar -cf - -C "$staging_root" . 2>>"$log_file" \
            | pv -s "$stage_bytes" | gzip > "$archive" 2>>"$log_file"; then
            tar_ok=1
        fi
        [[ "$pipefail_state" == "off" ]] && set +o pipefail
    else
        # Offline / apt unavailable — silently fall back to a plain
        # tar so we still produce the archive. No "install pv" message:
        # if we couldn't install it ourselves, sending the operator off
        # to apt is just shifting our problem onto them.
        msg_info "$(translate "Creating export archive...")"
        stop_spinner
        if tar -czf "$archive" -C "$staging_root" . >>"$log_file" 2>&1; then
            tar_ok=1
        fi
    fi

    if [[ $tar_ok -eq 1 && -f "$archive" ]]; then
        elapsed=$((SECONDS - t_start))
        archive_size=$(hb_file_size "$archive")
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Export completed:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Archive:")${CL}      ${BL}${archive}${CL}"
        echo -e "${TAB}${BGN}$(translate "Archive size:")${CL} ${BL}${archive_size}${CL}"
        echo -e "${TAB}${BGN}$(translate "Duration:")${CL}     ${BL}$(hb_human_elapsed "$elapsed")${CL}"
        echo -e ""
        msg_ok "$(translate "Export completed. The running system has not been modified.")"
        echo -e ""
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 0
    else
        msg_error "$(translate "Export failed.")"
        hb_show_log "$log_file" "$(translate "Export error log")"
        echo -e ""
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi
}

_rs_warn_dangerous() {
    local staging_root="$1"
    local -a paths=()
    hb_load_restore_paths "$staging_root" paths
    local -a warnings=()
    local rel
    for rel in "${paths[@]}"; do
        local cls warn
        cls=$(hb_classify_path "$rel")
        if [[ "$cls" == "dangerous" ]]; then
            warn=$(hb_path_warning "$rel")
            [[ -n "$warn" ]] && warnings+=("/$rel")
        fi
    done
    [[ ${#warnings[@]} -eq 0 ]] && return 0

    local tmp; tmp=$(mktemp)
    {
        echo "$(hb_translate "WARNING — This backup contains paths that are risky to restore on a running system:")"
        echo ""
        for w in "${warnings[@]}"; do
            echo "  ⚠  $w"
            local detail; detail=$(hb_path_warning "${w#/}")
            [[ -n "$detail" ]] && echo "     $detail"
            echo ""
        done
        echo "$(hb_translate "Recommendation: use 'Export to file' for these paths and apply manually during a maintenance window.")"
    } > "$tmp"
    dialog --backtitle "ProxMenux" \
        --title "$(translate "Security Warning — read before applying")" \
        --exit-label "$(translate "I have read this")" \
        --textbox "$tmp" 24 92 || true
    rm -f "$tmp"
}

_rs_is_ssh_session() {
    [[ -n "${SSH_CONNECTION:-}" || -n "${SSH_CLIENT:-}" || -n "${SSH_TTY:-}" ]]
}

_rs_paths_include_network() {
    local rel
    for rel in "$@"; do
        [[ "$rel" == etc/network || "$rel" == etc/network/* || "$rel" == etc/resolv.conf ]] && return 0
    done
    return 1
}

_rs_write_cluster_recovery_helper() {
    local recovery_root="$1"
    local helper="${recovery_root}/apply-cluster-restore.sh"
    cat > "$helper" <<EOF
#!/bin/bash
set -euo pipefail

RECOVERY_ROOT="${recovery_root}"

echo "Cluster recovery helper"
echo "Source: \$RECOVERY_ROOT"
echo
echo "WARNING: run this only in a maintenance window."
echo "This script stops pve-cluster, copies extracted cluster data, and starts pve-cluster again."
echo
read -r -p "Type YES to continue: " ans
[[ "\$ans" == "YES" ]] || { echo "Aborted."; exit 1; }

systemctl stop pve-cluster || true

if [[ -d "\$RECOVERY_ROOT/etc/pve" ]]; then
  mkdir -p /etc/pve
  cp -a "\$RECOVERY_ROOT/etc/pve/." /etc/pve/ || true
fi

if [[ -d "\$RECOVERY_ROOT/var/lib/pve-cluster" ]]; then
  mkdir -p /var/lib/pve-cluster
  cp -a "\$RECOVERY_ROOT/var/lib/pve-cluster/." /var/lib/pve-cluster/ || true
fi

systemctl start pve-cluster || true
echo "Cluster recovery script finished."
EOF
    chmod +x "$helper" 2>/dev/null || true
}

_rs_apply() {
    local staging_root="$1"
    local group="$2"    # hot | reboot | all
    shift 2
    local -a paths=()
    if [[ $# -gt 0 ]]; then
        paths=("$@")
    else
        hb_load_restore_paths "$staging_root" paths
    fi

    local backup_root
    # Pre-restore safety snapshot lives outside /root for the same
    # reason as the cluster recovery dir — restoring /root with
    # `rsync --delete` would otherwise wipe it mid-flow.
    backup_root="/var/lib/proxmenux/pre-restore/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$backup_root"

    local applied=0 skipped=0 t_start elapsed
    local cluster_recovery_root="" CLUSTER_DATA_EXTRACTED=""
    t_start=$SECONDS

    local rel src dst cls
    for rel in "${paths[@]}"; do
        src="$staging_root/rootfs/$rel"
        dst="/$rel"
        [[ -e "$src" ]] || { ((skipped++)); continue; }

        # Smart-restore hardware-drift skip list (populated by
        # _rs_run_complete_guided when hb_assess_hardware_drift flags
        # paths that would break on this host's hardware). Each path
        # in $RS_SKIP_PATHS is one absolute path per line. Matching is
        # exact-or-descendant so "/etc/zfs/zpool.cache" listed in the
        # skip set covers itself when rel == "etc/zfs/zpool.cache".
        if [[ -n "${RS_SKIP_PATHS:-}" ]]; then
            local _abs="/$rel" _skip=""
            while IFS= read -r _skip; do
                [[ -z "$_skip" ]] && continue
                if [[ "$_abs" == "$_skip" || "$_abs" == "$_skip"/* ]]; then
                    ((skipped++))
                    continue 2
                fi
            done <<<"$RS_SKIP_PATHS"
        fi

        # Never restore cluster virtual filesystem data live.
        # Extract it for manual recovery in maintenance mode.
        # Path note: this used to live under /root/proxmenux-recovery/,
        # but a later iteration of the same loop applies /root from
        # the backup with `rsync --delete`, which wipes anything
        # under /root that isn't in the backup — including our
        # freshly-extracted recovery dir. We now stage it under
        # /var/lib/proxmenux/recovery/, which sits next to
        # restore-pending/ and isn't touched by any path apply.
        if [[ "$rel" == etc/pve* ]] || [[ "$rel" == var/lib/pve-cluster* ]]; then
            if [[ -z "$cluster_recovery_root" ]]; then
                cluster_recovery_root="/var/lib/proxmenux/recovery/$(date +%Y%m%d_%H%M%S)"
                mkdir -p "$cluster_recovery_root"
            fi
            mkdir -p "$cluster_recovery_root/$(dirname "$rel")"
            cp -a "$src" "$cluster_recovery_root/$rel" 2>/dev/null || true
            CLUSTER_DATA_EXTRACTED="$cluster_recovery_root"
            ((skipped++))
            continue
        fi

        cls=$(hb_classify_path "$rel")
        case "$group" in
            hot)    [[ "$cls" != "hot" ]]    && { ((skipped++)); continue; } ;;
            reboot) [[ "$cls" != "reboot" ]] && { ((skipped++)); continue; } ;;
            all)    ;; # apply everything
        esac

        # /etc/zfs: opt-in only
        if [[ "$rel" == "etc/zfs" || "$rel" == "etc/zfs/"* ]]; then
            [[ "${HB_RESTORE_INCLUDE_ZFS:-0}" != "1" ]] && { ((skipped++)); continue; }
        fi

        # Save current before overwriting
        if [[ -e "$dst" ]]; then
            mkdir -p "$backup_root/$(dirname "$rel")"
            cp -a "$dst" "$backup_root/$rel" 2>/dev/null || true
        fi

        # Apply
        if [[ -d "$src" ]]; then
            mkdir -p "$dst"
            # /usr/local/share/proxmenux/: symmetric to the backup-time excludes
            # in lib_host_backup_common.sh. We keep the destination's freshly-
            # installed code (scripts/, web/, AppImage/, monitor-app/, utils.sh)
            # and only restore the user's state (components_status.json, dbs,
            # configs). Without these excludes --delete would wipe the entire
            # /scripts/ tree on the target and the pending-restore boot service
            # would fail to find its own entry point.
            local -a rsync_extra=()
            if [[ "$rel" == "usr/local/share/proxmenux" ]]; then
                rsync_extra+=(
                    --exclude "scripts/"
                    --exclude "web/"
                    --exclude "monitor-app/"
                    --exclude "monitor-app.*/"
                    --exclude "AppImage/"
                    --exclude "images/"
                    --exclude "json/"
                    --exclude "utils.sh"
                    --exclude "helpers_cache.json"
                    --exclude "ProxMenux-Monitor.AppImage*"
                    --exclude "install_proxmenux*.sh"
                    --exclude "restore-pending/"
                )
            fi
            rsync -aAXH --delete "${rsync_extra[@]}" "$src/" "$dst/" 2>/dev/null && ((applied++)) || ((skipped++))
        else
            mkdir -p "$(dirname "$dst")"
            cp -a "$src" "$dst" 2>/dev/null && ((applied++)) || ((skipped++))
        fi
    done

    elapsed=$((SECONDS - t_start))
    [[ "$group" == "hot" || "$group" == "all" ]] && \
        systemctl daemon-reload >/dev/null 2>&1 || true

    echo -e ""
    echo -e "${TAB}${BOLD}$(translate "Restore applied:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Group:")${CL}              ${BL}${group}${CL}"
    echo -e "${TAB}${BGN}$(translate "Paths applied:")${CL}      ${BL}${applied}${CL}"
    echo -e "${TAB}${BGN}$(translate "Paths skipped:")${CL}      ${BL}${skipped}${CL}"
    echo -e "${TAB}${BGN}$(translate "Duration:")${CL}           ${BL}$(hb_human_elapsed "$elapsed")${CL}"
    echo -e "${TAB}${BGN}$(translate "Pre-restore backup:")${CL} ${BL}${backup_root}${CL}"
    echo -e ""

    if [[ "$group" == "hot" ]]; then
        msg_ok "$(translate "Hot changes applied. No reboot needed for these paths.")"
    else
        msg_warn "$(translate "Changes applied. A system reboot is recommended for them to take full effect.")"
    fi

    if [[ -n "$CLUSTER_DATA_EXTRACTED" ]]; then
        export HB_CLUSTER_DATA_EXTRACTED="$CLUSTER_DATA_EXTRACTED"
        _rs_write_cluster_recovery_helper "$CLUSTER_DATA_EXTRACTED"
        msg_info2 "$(translate "Cluster data will be applied automatically at next boot.")"
        msg_info2 "$(translate "Optional safety helper if you ever need to re-apply manually:") $CLUSTER_DATA_EXTRACTED/apply-cluster-restore.sh"
    else
        unset HB_CLUSTER_DATA_EXTRACTED
    fi
}

_rs_collect_plan_stats() {
    local staging_root="$1"
    local -a paths=()
    hb_load_restore_paths "$staging_root" paths

    RS_PLAN_TOTAL=0
    RS_PLAN_HOT=0
    RS_PLAN_REBOOT=0
    RS_PLAN_DANGEROUS=0
    RS_PLAN_HAS_CLUSTER=0
    RS_PLAN_HAS_NETWORK=0
    RS_PLAN_HAS_ZFS=0

    local rel cls
    RS_PLAN_TOTAL=${#paths[@]}
    for rel in "${paths[@]}"; do
        cls=$(hb_classify_path "$rel")
        case "$cls" in
            hot)       ((RS_PLAN_HOT++)) ;;
            reboot)    ((RS_PLAN_REBOOT++)) ;;
            dangerous) ((RS_PLAN_DANGEROUS++)) ;;
        esac

        [[ "$rel" == etc/network* ]] && RS_PLAN_HAS_NETWORK=1
        [[ "$rel" == etc/pve* || "$rel" == var/lib/pve-cluster* ]] && RS_PLAN_HAS_CLUSTER=1
        [[ "$rel" == etc/zfs* ]] && RS_PLAN_HAS_ZFS=1
    done
}

_rs_show_plan_summary() {
    local staging_root="$1"
    local meta="$staging_root/metadata"

    # dialog --colors needs --msgbox/--yesno/--infobox (not --textbox),
    # so we build the body as a string.
    local body
    body=$'\n'"\Zb═══ $(translate "Restore plan summary") ═══\ZB"$'\n\n'

    if [[ -f "$meta/run_info.env" ]]; then
        body+="\Zb$(translate "Backup origin metadata:")\ZB"$'\n'
        while IFS='=' read -r k v; do
            [[ -z "$k" ]] && continue
            body+="$(printf '  %-20s \Z4%s\Zn' "${k}:" "$v")"$'\n'
        done < "$meta/run_info.env"
        body+=$'\n'
    fi

    # Reboot-required and live-unsafe both go to the pending set and
    # are applied by the post-boot dispatcher — to the operator they're
    # the same bucket "things that complete after reboot".
    local _reboot_total=$(( RS_PLAN_REBOOT + RS_PLAN_DANGEROUS ))
    body+="\Zb$(translate "Detected paths in this backup:")\ZB \Zb\Z4${RS_PLAN_TOTAL}\Zn"$'\n'
    body+="  • $(translate "Safe to apply now"): \Zb\Z4${RS_PLAN_HOT}\Zn"$'\n'
    body+="  • $(translate "Require reboot"): \Zb\Z4${_reboot_total}\Zn"$'\n'
    body+=$'\n'

    if [[ "$RS_PLAN_HAS_NETWORK" -eq 1 ]]; then
        body+="  • $(translate "Includes /etc/network (may drop SSH immediately)")"$'\n'
    fi
    if [[ "$RS_PLAN_HAS_CLUSTER" -eq 1 ]]; then
        body+="  • \Z4$(translate "Includes cluster data (/etc/pve, /var/lib/pve-cluster)")\Zn"$'\n'
        body+="    $(translate "These paths will not be restored live and will be extracted for manual recovery.")"$'\n'
    fi
    if [[ "$RS_PLAN_HAS_ZFS" -eq 1 ]]; then
        if [[ "${HB_RESTORE_INCLUDE_ZFS:-0}" == "1" ]]; then
            body+="  • $(translate "Includes /etc/zfs"): \Zb$(translate "ENABLED for restore")\ZB"$'\n'
        else
            body+="  • $(translate "Includes /etc/zfs"): \Zb$(translate "DISABLED unless you enable it")\ZB"$'\n'
        fi
    fi
    body+=$'\n'
    body+="\Zb$(translate "Recommendation: start with Complete restore.")\ZB"

    dialog --backtitle "ProxMenux" --colors \
        --title "$(translate "Restore plan")" \
        --msgbox "$body" 24 94 || true
}

_rs_prompt_zfs_opt_in() {
    local staging_root="$1"
    export HB_RESTORE_INCLUDE_ZFS=0

    if [[ ! -d "$staging_root/rootfs/etc/zfs" ]]; then
        return 0
    fi

    # /etc/zfs/ on a Proxmox host ALWAYS contains package defaults
    # (zfs-functions, zpool.d/, zed.d/) — they're shipped by the
    # zfsutils-linux package and identical across PVE installs.
    # Only zpool.cache (and the keys/ subdir) carry host-specific
    # state, because zpool.cache references the source host's
    # physical disks by GUID. Anything else is safe to restore.
    local cache="$staging_root/rootfs/etc/zfs/zpool.cache"
    if [[ ! -f "$cache" ]]; then
        # No host-specific bits — restore defaults silently.
        export HB_RESTORE_INCLUDE_ZFS=1
        return 0
    fi

    # zpool.cache IS present. Two cases:
    #  - Same host restore (recovery on the source machine) → quietly
    #    include; the cache is correct for this host by definition.
    #  - Cross-host restore → loud warning: pool GUIDs in the cache
    #    won't match the target's disks, and Proxmox would try to
    #    import non-existent pools at next boot.
    local msg
    if [[ "${HB_COMPAT_SAME_HOST:-0}" == "1" ]]; then
        msg="$(translate "Backup includes /etc/zfs/zpool.cache. Restore it (same host detected)?")"
    else
        msg="$(translate "This backup includes /etc/zfs/zpool.cache (host-specific ZFS state).")"$'\n\n'"$(translate "Restore it ONLY if the target host has the same pools and disks as the source. Otherwise Proxmox may try to import non-existent pools at next boot.")"
    fi
    if whiptail --title "$(translate "ZFS configuration")" \
        --yesno "$msg" 12 78; then
        export HB_RESTORE_INCLUDE_ZFS=1
    fi
}

_rs_finish_flow() {
    echo -e ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
}

# Lists components that the post-boot dispatcher will reinstall in background
# after reboot, by reading the backup's components_status.json. Mirrors the
# COMPONENT_INSTALLERS array in apply_cluster_postboot.sh — keep both in sync.
# Echoes "<key>|<label>|<eta>" one per line for installed components.
_rs_list_pending_reinstalls() {
    local staging_root="$1"
    local state_file="$staging_root/rootfs/usr/local/share/proxmenux/components_status.json"
    [[ -f "$state_file" ]] || return 0
    command -v jq >/dev/null 2>&1 || return 0

    local -a known=(
        "nvidia_driver|NVIDIA driver (DKMS kernel compile)|~5-10 min"
        "amdgpu_top|amdgpu_top (GitHub .deb download)|~1 min"
        "intel_gpu_tools|intel-gpu-tools (apt)|~1 min"
        "coral_driver|Coral TPU driver (DKMS compile)|~3-5 min"
    )
    local entry key label eta status
    for entry in "${known[@]}"; do
        key="${entry%%|*}"
        label="${entry#*|}";  label="${label%%|*}"
        eta="${entry##*|}"
        status=$(jq -r ".${key}.status // \"\"" "$state_file" 2>/dev/null)
        [[ "$status" == "installed" ]] && printf '%s|%s|%s\n' "$key" "$label" "$eta"
    done
}

# Offers an immediate reboot after the pending restore is prepared, following
# the same UX pattern as the post-install script. Lists what will keep running
# in background after reboot so the operator isn't surprised when nvidia-smi
# or similar tools are missing for the first few minutes.
_rs_offer_reboot_after_pending() {
    local staging_root="$1"

    local -a reinstalls=()
    mapfile -t reinstalls < <(_rs_list_pending_reinstalls "$staging_root")

    local bg_block=""
    if (( ${#reinstalls[@]} > 0 )); then
        bg_block="$(translate "After reboot the system will be fully accessible (SSH, web UI, login), but the following components will be reinstalled in BACKGROUND — until they finish, commands like nvidia-smi may not yet be available:")"$'\n'
        local r key label eta
        for r in "${reinstalls[@]}"; do
            key="${r%%|*}"
            label="${r#*|}"; label="${label%%|*}"
            eta="${r##*|}"
            bg_block+="  • ${label}  (${eta})"$'\n'
        done
        bg_block+=$'\n'"$(translate "Monitor progress:")"$'\n'
        bg_block+="  tail -f /var/log/proxmenux/proxmenux-cluster-postboot-*.log"$'\n'
        bg_block+="  systemctl status proxmenux-apply-cluster-postboot.service"$'\n\n'
        bg_block+="$(translate "If notifications are enabled (Telegram/Discord/ntfy/...), you will receive a \"Host restore finished\" message when all background tasks complete.")"$'\n\n'
    fi

    local prompt="$(translate "Pending restore prepared. A reboot is required to complete it.")"$'\n\n'"${bg_block}$(translate "Reboot now?")"

    if whiptail --title "$(translate "Reboot Required")" \
            --yesno "$prompt" 22 90; then
        msg_warn "$(translate "Rebooting the system...")"
        sleep 1
        reboot
    else
        msg_info2 "$(translate "You can reboot later manually with: reboot")"
        msg_success "$(translate "Press Enter to continue...")"
        read -r
    fi
}

_rs_collect_pending_paths() {
    local mode="$1"
    shift
    local -a in_paths=("$@")
    local -A seen=()
    local -a out=()
    local rel cls

    for rel in "${in_paths[@]}"; do
        cls=$(hb_classify_path "$rel")
        case "$mode" in
            remaining_after_hot)
                [[ "$cls" == "hot" ]] && continue
                ;;
            all_selected)
                ;;
        esac
        [[ -z "$rel" || -n "${seen[$rel]}" ]] && continue

        # Drop hardware-drift skips (see RS_SKIP_PATHS comment in _rs_apply).
        if [[ -n "${RS_SKIP_PATHS:-}" ]]; then
            local _abs="/$rel" _skip="" _drop=0
            while IFS= read -r _skip; do
                [[ -z "$_skip" ]] && continue
                if [[ "$_abs" == "$_skip" || "$_abs" == "$_skip"/* ]]; then
                    _drop=1; break
                fi
            done <<<"$RS_SKIP_PATHS"
            (( _drop )) && continue
        fi

        seen["$rel"]=1
        out+=("$rel")
    done

    printf '%s\n' "${out[@]}"
}

_rs_install_pending_service_unit() {
    local onboot_script="$1"
    local unit_file="/etc/systemd/system/proxmenux-restore-onboot.service"

    # `network-pre.target` is a passive target activated by
    # systemd-networkd. On Proxmox the networking stack is
    # `networking.service` from ifupdown2, NOT systemd-networkd,
    # so network-pre.target is never reached — the original unit
    # had `ConditionResult=no` at boot and the pending restore
    # silently sat in `pending` state forever.
    #
    # The correct anchor on PVE is `networking.service`: we run
    # before it (so we can rewrite /etc/network in time for
    # ifupdown2 to read the new config) and we pull ourselves in
    # via `multi-user.target` which IS always activated at boot.
    cat > "$unit_file" <<EOF
[Unit]
Description=ProxMenux Pending Restore (on boot)
DefaultDependencies=no
After=local-fs.target
Before=networking.service
Wants=local-fs.target

[Service]
Type=oneshot
ExecStart=${onboot_script}
# 5-min cap. Original version had TimeoutStartSec=0 (unlimited)
# combined with update-initramfs -u -k all + update-grub +
# systemctl start pve-cluster in the script — and a single boot
# could hang for 15+ minutes with no recourse. With this cap, if
# the pending apply ever wedges, systemd kills it and the rest of
# boot continues. The pending state gets marked failed and the
# operator can re-run it manually from the menu after boot.
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF
}

_rs_prepare_pending_restore() {
    local staging_root="$1"
    shift
    local -a pending_paths=("$@")

    if [[ ${#pending_paths[@]} -eq 0 ]]; then
        msg_warn "$(translate "No pending paths to schedule for reboot.")"
        return 1
    fi

    local onboot_script="$LOCAL_SCRIPTS/backup_restore/apply_pending_restore.sh"
    [[ ! -f "$onboot_script" ]] && onboot_script="$SCRIPT_DIR/apply_pending_restore.sh"
    if [[ ! -x "$onboot_script" ]]; then
        msg_error "$(translate "Pending restore script not found or not executable:") $onboot_script"
        return 1
    fi

    local pending_base="/var/lib/proxmenux/restore-pending"
    local restore_id pending_dir created_at
    restore_id="$(date +%Y%m%d_%H%M%S)"
    pending_dir="${pending_base}/${restore_id}"
    created_at="$(date -Iseconds)"

    mkdir -p "$pending_dir/rootfs" "$pending_dir/metadata" "$pending_base/completed" || return 1

    local rel src dst
    : > "$pending_dir/apply-on-boot.list"
    for rel in "${pending_paths[@]}"; do
        src="$staging_root/rootfs/$rel"
        [[ -e "$src" ]] || continue
        dst="$pending_dir/rootfs/$rel"
        mkdir -p "$(dirname "$dst")"
        if [[ -d "$src" ]]; then
            mkdir -p "$dst"
            rsync -aAXH --delete "$src/" "$dst/" 2>/dev/null || true
        else
            cp -a "$src" "$dst" 2>/dev/null || true
        fi
        echo "$rel" >> "$pending_dir/apply-on-boot.list"
    done

    if [[ ! -s "$pending_dir/apply-on-boot.list" ]]; then
        rm -rf "$pending_dir"
        msg_warn "$(translate "Nothing to schedule for reboot from selected paths.")"
        return 1
    fi

    [[ -d "$staging_root/metadata" ]] && cp -a "$staging_root/metadata/." "$pending_dir/metadata/" 2>/dev/null || true

    cat > "$pending_dir/plan.env" <<EOF
RESTORE_ID=${restore_id}
CREATED_AT=${created_at}
HB_RESTORE_INCLUDE_ZFS=${HB_RESTORE_INCLUDE_ZFS:-0}
EOF
    # Persist hardware-drift skips so apply_pending_restore.sh can filter
    # them at boot. The RS_SKIP_PATHS env var only lives in the restore
    # menu session; without writing it to disk, paths that would break
    # the boot (stale EFI UUIDs, foreign zpool.cache, ...) leaked through
    # to the post-boot apply and ended up corrupting the bootloader.
    if [[ -n "${RS_SKIP_PATHS:-}" ]]; then
        printf '%s\n' "$RS_SKIP_PATHS" > "$pending_dir/rs-skip-paths.txt"
        chmod 600 "$pending_dir/rs-skip-paths.txt"
    fi
    echo "pending" > "$pending_dir/state"

    ln -sfn "$pending_dir" "$pending_base/current"

    _rs_install_pending_service_unit "$onboot_script"
    systemctl daemon-reload >/dev/null 2>&1 || true
    if ! systemctl enable proxmenux-restore-onboot.service >/dev/null 2>&1; then
        msg_error "$(translate "Could not enable on-boot restore service.")"
        return 1
    fi

    echo -e ""
    echo -e "${TAB}${BGN}$(translate "Pending restore ID:")${CL} ${BL}${restore_id}${CL}"
    echo -e "${TAB}${BGN}$(translate "Pending restore dir:")${CL} ${BL}${pending_dir}${CL}"
    msg_ok "$(translate "Pending restore prepared. It will run automatically at next boot.")"
    return 0
}

_rs_handle_ssh_network_risk() {
    local staging_root="$1"
    shift
    local -a selected_paths=("$@")

    _rs_is_ssh_session || return 0
    _rs_paths_include_network "${selected_paths[@]}" || return 0

    local schedule_msg
    schedule_msg="$(translate "You are connected via SSH and selected network-related restore paths.")"$'\n\n'"$(translate "Recommended: schedule these paths for next boot to avoid immediate SSH disconnection.")"$'\n\n'"$(translate "Do you want to schedule selected paths for next boot now?")"
    if whiptail --title "$(translate "SSH network risk")" \
        --yesno "$schedule_msg" \
        12 86; then
        local -a pending_paths=()
        mapfile -t pending_paths < <(_rs_collect_pending_paths all_selected "${selected_paths[@]}")
        show_proxmenux_logo
        msg_title "$(translate "Preparing pending restore (network-safe)")"
        if _rs_prepare_pending_restore "$staging_root" "${pending_paths[@]}"; then
            msg_warn "$(translate "Reboot is required to apply the scheduled restore.")"
        fi
        _rs_finish_flow
        return 2
    fi

    if ! whiptail --title "$(translate "High risk confirmation")" --defaultno \
        --yesno "$(translate "Continue with live apply now? SSH may disconnect immediately.")" \
        10 80; then
        return 1
    fi
    return 0
}

_rs_run_complete_guided() {
    local staging_root="$1"
    local -a all_paths=()
    hb_load_restore_paths "$staging_root" all_paths

    # ── Smart restore plan ──────────────────────────────────
    # Compare the backup metadata against the live host and surface
    # anything that would be unsafe to restore as-is (ZFS pool GUID
    # changed, fstab UUIDs gone, NVIDIA driver state for a host with
    # no NVIDIA card, ...). Only opens an extra dialog when there's
    # actually drift — same-hardware/same-host restores skip it.
    export RS_SKIP_PATHS=""
    local -a drift_lines=()
    mapfile -t drift_lines < <(hb_assess_hardware_drift "$staging_root" 2>/dev/null)
    if (( ${#drift_lines[@]} > 0 )); then
        local skip_paths=""
        local skip_components=""
        local plan_body
        plan_body="\Zb$(translate "Smart restore plan — hardware compatibility check")\ZB"$'\n\n'
        plan_body+="$(translate "The backup metadata was compared against this host. The following items will be SKIPPED to keep the boot safe:")"$'\n\n'

        # Identifier-based skips (ZFS pool GUID, boot EFI UUID, fstab UUID)
        # always fire on cross-host restores. The skip itself still applies
        # — only the dialog is suppressed when nothing else is signal-bearing.
        local -A _IDENTIFIER_PATHS=(
            ["/etc/zfs/zpool.cache"]=1
            ["/etc/kernel/proxmox-boot-uuids"]=1
            ["/etc/fstab"]=1
        )
        local dialog_signal=0
        local line key action reason
        for line in "${drift_lines[@]}"; do
            IFS=$'\t' read -r key action reason <<<"$line"
            [[ "$action" != "skip" ]] && continue
            if [[ "$key" == component:* ]]; then
                local cname="${key#component:}"
                skip_components+="${cname} "
                plan_body+="  \Z1•\Zn $(translate "Component:") \Zb${cname}\ZB"$'\n'
                plan_body+="    ${reason}"$'\n\n'
                dialog_signal=1
            else
                skip_paths+="${key}"$'\n'
                if [[ "${HB_COMPAT_SAME_HOST:-1}" == "0" ]] \
                    && [[ -n "${_IDENTIFIER_PATHS[$key]:-}" ]]; then
                    continue
                fi
                plan_body+="  \Z1•\Zn $(translate "Path:") \Zb${key}\ZB"$'\n'
                plan_body+="    ${reason}"$'\n\n'
                dialog_signal=1
            fi
        done

        # Persist for _rs_apply / _rs_collect_pending_paths to honor.
        # The drift summary is merged into the single confirmation
        # dialog below — no extra yes/no popup.
        RS_SKIP_PATHS="${skip_paths%$'\n'}"
        export RS_SKIP_PATHS
        # Stash the plan_body fragment so the confirm dialog can show it.
        RS_DRIFT_SUMMARY=""
        (( dialog_signal == 1 )) && RS_DRIFT_SUMMARY="$plan_body"
    fi

    # Build the rich confirmation body. Replaces the previous 4-strategy
    # menu — by design a Proxmox host restore always requires a reboot
    # for predictable end state (pmxcfs live writes + initramfs + driver
    # reinstall via the post-boot dispatcher all need it). Forcing the
    # strategy to "apply safe hot + pending for boot" gives the user the
    # full restore + zero-manual NVIDIA/Intel/Coral reinstall path with
    # one consistent UX, no footguns.
    local hot_count="${RS_PLAN_HOT:-0}"
    local pending_count=$(( ${RS_PLAN_REBOOT:-0} + ${RS_PLAN_DANGEROUS:-0} ))

    # Surface which components the post-boot dispatcher will reinstall
    # (read from the backup's components_status.json — same logic as
    # _rs_offer_reboot_after_pending).
    local -a reinstalls=()
    mapfile -t reinstalls < <(_rs_list_pending_reinstalls "$staging_root")
    local comp_line=""
    if (( ${#reinstalls[@]} > 0 )); then
        local r label
        comp_line=$'\n'"$(translate "After reboot, these components will reinstall in background:")"$'\n'
        for r in "${reinstalls[@]}"; do
            label="${r#*|}"; label="${label%%|*}"
            local eta="${r##*|}"
            comp_line+="  • ${label}  (${eta})"$'\n'
        done
    fi

    # dialog --colors lets us highlight the counts, the warning, and
    # the reinstall list. Inline escape codes:
    #   \Zb bold   \ZB unbold   \Zn reset all
    #   \Z2 green  \Z3 yellow   \Z4 blue   \Z1 red
    local body
    body="\Zb$(translate "A complete restore will:")\ZB"$'\n\n'
    body+="  • $(translate "Apply") \Zb\Z4${hot_count}\Zn $(translate "safe paths now (configs, packages, /etc, /root, ...)")"$'\n'
    body+="  • $(translate "Schedule") \Zb\Z4${pending_count}\Zn $(translate "paths for next boot (/etc/pve, guests, drivers, ...)")"$'\n'
    if (( ${#reinstalls[@]} > 0 )); then
        body+=$'\n'"\Zb$(translate "After reboot, these components will reinstall in background:")\ZB"$'\n'
        local r label eta
        for r in "${reinstalls[@]}"; do
            label="${r#*|}"; label="${label%%|*}"
            eta="${r##*|}"
            body+="  • \Zb${label}\ZB  (${eta})"$'\n'
        done
    fi
    # If smart restore flagged drift skips earlier, surface them here
    # so the operator sees everything in one screen instead of two
    # consecutive yes/no popups.
    if [[ -n "${RS_DRIFT_SUMMARY:-}" ]]; then
        body+=$'\n'"\Zb$(translate "Hardware compatibility — these items will be skipped to keep the boot safe:")\ZB"$'\n'
        # Trim the original header from the stashed plan_body — we only
        # want the bullet list.
        local _drift_bullets
        _drift_bullets=$(printf '%s\n' "$RS_DRIFT_SUMMARY" | sed -n '/\Z1•\Zn/,$p')
        body+="$_drift_bullets"$'\n'
    fi
    body+=$'\n'"\Zb\Z4$(translate "A reboot is required to finish the restore.")\Zn"$'\n\n'
    body+="$(translate "If notifications are enabled (Telegram/Discord/ntfy/...), you will receive a \"Host restore finished\" message when all background tasks complete.")"$'\n\n'
    body+="\Zb$(translate "Continue?")\ZB"

    if ! dialog --backtitle "ProxMenux" --colors \
            --title "$(translate "Confirm complete restore")" \
            --yesno "$body" 22 88; then
        return 1
    fi

    show_proxmenux_logo
    msg_title "$(translate "Applying safe paths and preparing pending restore")"
    [[ "$hot_count" -gt 0 ]] && _rs_apply "$staging_root" hot

    local -a pending_paths=()
    mapfile -t pending_paths < <(_rs_collect_pending_paths remaining_after_hot "${all_paths[@]}")
    local pending_ok=0
    if _rs_prepare_pending_restore "$staging_root" "${pending_paths[@]}"; then
        pending_ok=1
    fi
    # /etc/pve is in the pending set → defer guest configs to the
    # post-boot dispatcher (same as the old Strategy 3).
    _rs_run_complete_extras "$staging_root" 0
    if (( pending_ok )); then
        _rs_offer_reboot_after_pending "$staging_root"
    else
        _rs_finish_flow
    fi
    return 0
}

_rs_component_paths() {
    local comp_id="$1"
    case "$comp_id" in
        network)       printf '%s\n' etc/network etc/resolv.conf ;;
        ssh_access)    printf '%s\n' etc/ssh root/.ssh ;;
        host_identity) printf '%s\n' etc/hostname etc/hosts ;;
        cron_jobs)     printf '%s\n' etc/cron.d etc/cron.daily etc/cron.hourly etc/cron.weekly etc/cron.monthly etc/cron.allow etc/cron.deny var/spool/cron/crontabs ;;
        apt_repos)     printf '%s\n' etc/apt ;;
        kernel_boot)   printf '%s\n' etc/modules etc/modules-load.d etc/modprobe.d etc/default/grub etc/kernel etc/udev/rules.d etc/fstab etc/iscsi etc/multipath ;;
        systemd_custom) printf '%s\n' etc/systemd/system ;;
        scripts)       printf '%s\n' usr/local/bin usr/local/share/proxmenux root/bin root/scripts ;;
        root_config)   printf '%s\n' root/.bashrc root/.profile root/.bash_aliases root/.config ;;
        root_ssh)      printf '%s\n' root/.ssh ;;
        zfs_cfg)       printf '%s\n' etc/zfs ;;
        postfix_cfg)   printf '%s\n' etc/postfix ;;
        cluster_cfg)   printf '%s\n' etc/pve var/lib/pve-cluster ;;
    esac
}

_rs_component_label() {
    local comp_id="$1"
    case "$comp_id" in
        network)        echo "$(translate "Network (interfaces, DNS)")" ;;
        ssh_access)     echo "$(translate "SSH access (host + root)")" ;;
        host_identity)  echo "$(translate "Host identity (hostname, hosts)")" ;;
        cron_jobs)      echo "$(translate "Scheduled tasks (cron)")" ;;
        apt_repos)      echo "$(translate "APT and repositories")" ;;
        kernel_boot)    echo "$(translate "Kernel, modules and boot config")" ;;
        systemd_custom) echo "$(translate "Custom systemd units")" ;;
        scripts)        echo "$(translate "Custom scripts and ProxMenux files")" ;;
        root_config)    echo "$(translate "Root shell/profile config")" ;;
        root_ssh)       echo "$(translate "Root SSH keys/config")" ;;
        zfs_cfg)        echo "$(translate "ZFS configuration")" ;;
        postfix_cfg)    echo "$(translate "Postfix configuration")" ;;
        cluster_cfg)    echo "$(translate "Cluster configuration (advanced)")" ;;
        *)              echo "$comp_id" ;;
    esac
}

_rs_component_is_available() {
    local staging_root="$1"
    local comp_id="$2"
    local rel
    while IFS= read -r rel; do
        [[ -n "$rel" && -e "$staging_root/rootfs/$rel" ]] && return 0
    done < <(_rs_component_paths "$comp_id")
    return 1
}

_rs_unique_paths() {
    local __out_var="$1"
    shift
    local -A seen=()
    local -a uniq=()
    local p
    for p in "$@"; do
        [[ -z "$p" || -n "${seen[$p]}" ]] && continue
        seen["$p"]=1
        uniq+=("$p")
    done
    local -n __out_ref="$__out_var"
    __out_ref=("${uniq[@]}")
}

_rs_collect_stats_for_paths() {
    RS_SEL_TOTAL=0
    RS_SEL_HOT=0
    RS_SEL_REBOOT=0
    RS_SEL_DANGEROUS=0

    local rel cls
    RS_SEL_TOTAL=$#
    for rel in "$@"; do
        cls=$(hb_classify_path "$rel")
        case "$cls" in
            hot)       ((RS_SEL_HOT++)) ;;
            reboot)    ((RS_SEL_REBOOT++)) ;;
            dangerous) ((RS_SEL_DANGEROUS++)) ;;
        esac
    done
}

_rs_warn_dangerous_paths() {
    local -a selected_paths=("$@")
    local -a warnings=()
    local rel
    for rel in "${selected_paths[@]}"; do
        [[ "$(hb_classify_path "$rel")" == "dangerous" ]] && warnings+=("$rel")
    done
    [[ ${#warnings[@]} -eq 0 ]] && return 0

    local tmp
    tmp=$(mktemp) || return 0
    {
        echo "$(translate "WARNING — You selected risky paths for live restore:")"
        echo ""
        for rel in "${warnings[@]}"; do
            echo "  ⚠  /$rel"
            local detail
            detail=$(hb_path_warning "$rel")
            [[ -n "$detail" ]] && echo "     $detail"
            echo ""
        done
    } > "$tmp"

    dialog --backtitle "ProxMenux" \
        --title "$(translate "Security Warning — read before applying")" \
        --exit-label "$(translate "I have read this")" \
        --textbox "$tmp" 24 92 || true
    rm -f "$tmp"
}

_rs_select_component_paths() {
    local staging_root="$1"
    local __out_var="$2"
    local -n __out_ref="$__out_var"

    local -a component_ids=(
        network ssh_access host_identity cron_jobs apt_repos kernel_boot
        systemd_custom scripts root_config root_ssh zfs_cfg postfix_cfg cluster_cfg
    )
    local -a checklist=()
    local comp_id
    for comp_id in "${component_ids[@]}"; do
        _rs_component_is_available "$staging_root" "$comp_id" || continue
        checklist+=("$comp_id" "$(_rs_component_label "$comp_id")" "off")
    done

    if [[ ${#checklist[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No components available")" \
            --msgbox "$(translate "No restorable components were detected in this backup.")" 8 68
        return 1
    fi

    local selected
    selected=$(dialog --backtitle "ProxMenux" --separate-output \
        --title "$(translate "Custom restore by components")" \
        --checklist "\n$(translate "Select components to restore:")" \
        24 94 14 "${checklist[@]}" 3>&1 1>&2 2>&3) || return 1

    if [[ -z "$selected" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No components selected")" \
            --msgbox "$(translate "Select at least one component to continue.")" 8 66
        return 1
    fi

    local -a selected_paths=()
    while IFS= read -r comp_id; do
        [[ -z "$comp_id" ]] && continue
        local rel
        while IFS= read -r rel; do
            [[ -n "$rel" && -e "$staging_root/rootfs/$rel" ]] && selected_paths+=("$rel")
        done < <(_rs_component_paths "$comp_id")
    done <<< "$selected"

    _rs_unique_paths "$__out_var" "${selected_paths[@]}"

    if [[ ${#__out_ref[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No paths available")" \
            --msgbox "$(translate "Selected components have no matching paths in this backup.")" 8 72
        return 1
    fi
    return 0
}

_rs_run_custom_restore() {
    local staging_root="$1"
    local -a selected_paths=()

    _rs_select_component_paths "$staging_root" selected_paths || return 1
    _rs_collect_stats_for_paths "${selected_paths[@]}"

    while true; do
        local choice
        choice=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Custom restore")" \
            --menu "\n$(translate "Selected component paths:") ${RS_SEL_TOTAL}" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
            1 "$(translate "Apply safe changes now")  (${RS_SEL_HOT})" \
            2 "$(translate "Apply safe + reboot-required")  ($((RS_SEL_HOT + RS_SEL_REBOOT)))" \
            3 "$(translate "Apply all selected now (advanced)")  (${RS_SEL_TOTAL})" \
            4 "$(translate "Reselect components")" \
            5 "$(translate "Apply safe now + schedule remaining for next boot")" \
            6 "$(translate "Schedule selected components for next boot (no live apply)")" \
            0 "$(translate "Return")" \
            3>&1 1>&2 2>&3) || return 1

        case "$choice" in
            1)
                if [[ "$RS_SEL_HOT" -eq 0 ]]; then
                    dialog --backtitle "ProxMenux" --title "$(translate "Nothing to apply")" \
                        --msgbox "$(translate "No safe-now paths in selected components.")" 8 60
                    continue
                fi
                if ! whiptail --title "$(translate "Confirm")" \
                    --yesno "$(translate "Apply safe changes from selected components now?")" 9 72; then
                    continue
                fi
                show_proxmenux_logo
                msg_title "$(translate "Applying selected safe changes")"
                _rs_apply "$staging_root" hot "${selected_paths[@]}"
                [[ "$RS_SEL_REBOOT" -gt 0 || "$RS_SEL_DANGEROUS" -gt 0 ]] && \
                    msg_warn "$(translate "Some selected paths were not applied in safe mode.")"
                _rs_finish_flow
                return 0
                ;;

            2)
                if [[ $((RS_SEL_HOT + RS_SEL_REBOOT)) -eq 0 ]]; then
                    dialog --backtitle "ProxMenux" --title "$(translate "Nothing to apply")" \
                        --msgbox "$(translate "No safe/reboot paths in selected components.")" 8 64
                    continue
                fi
                if ! whiptail --title "$(translate "Confirm")" \
                    --yesno "$(translate "Apply safe + reboot-required paths from selected components now?")"$'\n\n'"$(translate "Risky live paths will be skipped.")" \
                    11 78; then
                    continue
                fi
                show_proxmenux_logo
                msg_title "$(translate "Applying selected safe + reboot changes")"
                [[ "$RS_SEL_HOT" -gt 0 ]] && _rs_apply "$staging_root" hot "${selected_paths[@]}"
                [[ "$RS_SEL_REBOOT" -gt 0 ]] && _rs_apply "$staging_root" reboot "${selected_paths[@]}"
                [[ "$RS_SEL_DANGEROUS" -gt 0 ]] && \
                    msg_warn "$(translate "Risky selected paths were skipped in this mode.")"
                _rs_finish_flow
                return 0
                ;;

            3)
                local ssh_network_rc
                _rs_handle_ssh_network_risk "$staging_root" "${selected_paths[@]}"
                ssh_network_rc=$?
                [[ $ssh_network_rc -eq 2 ]] && return 0
                [[ $ssh_network_rc -ne 0 ]] && continue

                [[ "$RS_SEL_DANGEROUS" -gt 0 ]] && _rs_warn_dangerous_paths "${selected_paths[@]}"
                if ! whiptail --title "$(translate "Final confirmation")" \
                    --yesno "$(translate "Apply ALL selected component paths now? This can include risky paths.")" \
                    10 78; then
                    continue
                fi
                show_proxmenux_logo
                msg_title "$(translate "Applying all selected component paths")"
                _rs_apply "$staging_root" all "${selected_paths[@]}"
                _rs_finish_flow
                return 0
                ;;

            4)
                _rs_select_component_paths "$staging_root" selected_paths || continue
                _rs_collect_stats_for_paths "${selected_paths[@]}"
                ;;

            5)
                if ! whiptail --title "$(translate "Confirm")" \
                    --yesno "$(translate "Apply safe selected paths now and schedule remaining selected paths for next boot?")" \
                    10 82; then
                    continue
                fi
                show_proxmenux_logo
                msg_title "$(translate "Applying safe selected paths and preparing pending restore")"
                [[ "$RS_SEL_HOT" -gt 0 ]] && _rs_apply "$staging_root" hot "${selected_paths[@]}"
                local -a pending_paths=()
                mapfile -t pending_paths < <(_rs_collect_pending_paths remaining_after_hot "${selected_paths[@]}")
                if _rs_prepare_pending_restore "$staging_root" "${pending_paths[@]}"; then
                    msg_warn "$(translate "Reboot is required to complete the pending restore.")"
                fi
                _rs_finish_flow
                return 0
                ;;

            6)
                if ! whiptail --title "$(translate "Confirm")" \
                    --yesno "$(translate "Schedule selected component paths for next boot without applying live changes now?")" \
                    10 82; then
                    continue
                fi
                local -a pending_paths=()
                mapfile -t pending_paths < <(_rs_collect_pending_paths all_selected "${selected_paths[@]}")
                show_proxmenux_logo
                msg_title "$(translate "Preparing selected pending restore")"
                if _rs_prepare_pending_restore "$staging_root" "${pending_paths[@]}"; then
                    msg_warn "$(translate "Reboot is required to apply the scheduled restore.")"
                fi
                _rs_finish_flow
                return 0
                ;;

            0)
                return 1
                ;;
        esac
    done
}

# Extras the Complete restore runs INLINE after applying file
# paths. The operator picked "Complete restore" — they implicitly
# asked for everything restorable from the backup. We don't ask
# them again about packages or guest configs, we just do it.
#
# Behaviour by strategy:
#   include_guests=1 → also copy LXC/QEMU .conf files (full mode)
#   include_guests=0 → skip them (safe / schedule-remaining modes
#                     where the operator opted out of risky paths)
# Packages are always installed when they're listed in the backup
# and missing on this host, regardless of strategy — installing
# user-installed packages is a prerequisite for the restored
# systemd units and config files to actually do anything.
_rs_run_complete_extras() {
    local staging_root="$1"
    local include_guests="${2:-1}"

    # ─ Packages — silent run when there's anything to do ──────
    local pkglist="$staging_root/metadata/packages.manual.list"
    if [[ -f "$pkglist" ]] \
        && command -v apt-mark >/dev/null 2>&1 \
        && command -v apt-get >/dev/null 2>&1; then
        local cur_pkgs_file
        cur_pkgs_file=$(mktemp)
        apt-mark showmanual 2>/dev/null | sort -u > "$cur_pkgs_file"
        local -a missing=()
        mapfile -t missing < <(comm -23 <(sort -u "$pkglist") "$cur_pkgs_file")
        rm -f "$cur_pkgs_file"
        if [[ ${#missing[@]} -gt 0 ]]; then
            echo
            # Split into apt-known vs unknown so the install count
            # announced below matches what apt-get will actually attempt.
            local -a installable=() unknown=()
            local pkg
            for pkg in "${missing[@]}"; do
                if apt-cache show "$pkg" >/dev/null 2>&1; then
                    installable+=("$pkg")
                else
                    unknown+=("$pkg")
                fi
            done

            if (( ${#installable[@]} > 0 )); then
                local _preview="${installable[*]:0:6}"
                (( ${#installable[@]} > 6 )) && _preview+=" … (+ $((${#installable[@]} - 6)) more)"
                echo -e "${TAB}${BGN}$(translate "Packages from backup to install:")${CL} ${BL}${_preview}${CL}"
                echo

                local apt_log="/var/log/proxmenux/restore-apt-$(date +%Y%m%d_%H%M%S).log"
                mkdir -p "$(dirname "$apt_log")" 2>/dev/null

                msg_info "$(translate "Refreshing apt cache...")"
                apt-get update -qq >"$apt_log" 2>&1 || true
                msg_ok "$(translate "apt cache refreshed.")"

                msg_info "$(translate "Installing") ${#installable[@]} $(translate "packages (this may take a few minutes)...")"
                # Full output to $apt_log so the spinner keeps turning
                # instead of stalling silently then dumping at the end.
                # --force-confold keeps the restored configs over any
                # ucf prompts that would otherwise block dpkg.
                DEBIAN_FRONTEND=noninteractive \
                    apt-get install -y \
                        -o Dpkg::Options::="--force-confdef" \
                        -o Dpkg::Options::="--force-confold" \
                        "${installable[@]}" >>"$apt_log" 2>&1
                local apt_rc=$?
                if (( apt_rc == 0 )); then
                    msg_ok "$(translate "Installed:") ${#installable[@]} $(translate "packages.")"
                else
                    msg_warn "$(translate "apt-get exited") ${apt_rc} — $(translate "see log:") $apt_log"
                fi
            fi
            if (( ${#unknown[@]} > 0 )); then
                msg_warn "$(translate "Skipped, not in apt cache:") ${unknown[*]:0:6}$([[ ${#unknown[@]} -gt 6 ]] && echo " … (+ $((${#unknown[@]} - 6)) more)")"
            fi
        fi
    fi

    # ─ Guest configs — only in full strategies ────────────────
    if [[ "$include_guests" == "1" ]]; then
        local nodes_root="$staging_root/rootfs/etc/pve/nodes"
        if [[ -d "$nodes_root" ]]; then
            local src_node_dir
            src_node_dir=$(find "$nodes_root" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)
            if [[ -n "$src_node_dir" ]]; then
                local -a lxc_confs=() qm_confs=()
                [[ -d "$src_node_dir/lxc"         ]] && mapfile -t lxc_confs < <(find "$src_node_dir/lxc"         -maxdepth 1 -type f -name '*.conf' 2>/dev/null | sort)
                [[ -d "$src_node_dir/qemu-server" ]] && mapfile -t qm_confs  < <(find "$src_node_dir/qemu-server" -maxdepth 1 -type f -name '*.conf' 2>/dev/null | sort)
                if [[ ${#lxc_confs[@]} -gt 0 || ${#qm_confs[@]} -gt 0 ]]; then
                    local cur_node target_lxc target_qm
                    cur_node=$(hostname)
                    target_lxc="/etc/pve/nodes/$cur_node/lxc"
                    target_qm="/etc/pve/nodes/$cur_node/qemu-server"
                    mkdir -p "$target_lxc" "$target_qm" 2>/dev/null
                    echo
                    msg_info "$(translate "Restoring guest configs (LXC + QEMU)...")"
                    stop_spinner
                    local copied=0 skipped=0 f vmid
                    for f in "${lxc_confs[@]}"; do
                        vmid=$(basename "$f" .conf)
                        if [[ -e "$target_lxc/$vmid.conf" ]]; then
                            ((skipped++))
                        elif cp "$f" "$target_lxc/$vmid.conf" 2>/dev/null; then
                            ((copied++))
                        fi
                    done
                    for f in "${qm_confs[@]}"; do
                        vmid=$(basename "$f" .conf)
                        if [[ -e "$target_qm/$vmid.conf" ]]; then
                            ((skipped++))
                        elif cp "$f" "$target_qm/$vmid.conf" 2>/dev/null; then
                            ((copied++))
                        fi
                    done
                    msg_ok "$(translate "Guest configs restored:") LXC+QEMU=$copied, $(translate "skipped (already exist)"):$skipped"
                    if (( copied > 0 )); then
                        echo -e "${TAB}${BL}$(translate "Use 'pct restore' / 'qmrestore' to recover their disks from your VM backups.")${CL}"
                    fi
                fi
            fi
        fi
    fi
}


_rs_apply_menu() {
    local staging_root="$1"

    _rs_collect_plan_stats "$staging_root"
    _rs_prompt_zfs_opt_in "$staging_root"
    # _rs_show_plan_summary intentionally NOT called here — the
    # essential plan info now appears inside the Complete restore
    # confirmation dialog (option 1). It's still reachable on demand
    # from option 6 of this menu.

    while true; do
        local choice
        choice=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Restore actions")" \
            --menu "\n$(translate "Choose how to continue:")" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
            1 "$(translate "Complete restore")" \
            2 "$(translate "Custom restore by components")" \
            3 "$(translate "Export to file (no system changes)")" \
            4 "$(translate "Preview changes (diff)")" \
            5 "$(translate "View backup metadata")" \
            6 "$(translate "View restore plan")" \
            0 "$(translate "Return")" \
            3>&1 1>&2 2>&3) || return 1

        case "$choice" in
            1)
                _rs_collect_plan_stats "$staging_root"
                _rs_run_complete_guided "$staging_root" && return 0
                ;;
            2)
                _rs_collect_plan_stats "$staging_root"
                _rs_run_custom_restore "$staging_root" && return 0
                ;;
            3)
                # _rs_export_to_file owns its own end-of-flow
                # (showing result + "Press Enter to return to menu")
                # so we don't call _rs_finish_flow here — doing so
                # would queue a second identical prompt.
                if _rs_export_to_file "$staging_root"; then
                    return 0
                fi
                ;;
            4) _rs_preview_diff "$staging_root" ;;
            5) _rs_show_metadata "$staging_root" ;;
            6)
                _rs_collect_plan_stats "$staging_root"
                _rs_show_plan_summary "$staging_root"
                ;;
            0) return 1 ;;
        esac
    done
}

# ==========================================================
# RESTORE MENU
# ==========================================================
restore_menu() {
    while true; do
        local choice
        choice=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Host Config Restore")" \
            --menu "\n$(translate "Select restore source:")" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
            1  "$(translate "Restore from Proxmox Backup Server (PBS)")" \
            2  "$(translate "Restore from Borg repository")" \
            3  "$(translate "Restore from local archive  (.tar.gz / .tar.zst)")" \
            0  "$(translate "Return")" \
            3>&1 1>&2 2>&3) || break
        [[ "$choice" == "0" ]] && break

        local staging_root
        staging_root=$(mktemp -d /tmp/proxmenux-restore.XXXXXX)

        local ok=0
        case "$choice" in
            1) _rs_extract_pbs   "$staging_root" && ok=1 ;;
            2) _rs_extract_borg  "$staging_root" && ok=1 ;;
            3) _rs_extract_local "$staging_root" && ok=1 ;;
        esac

        if [[ $ok -eq 1 ]] && _rs_check_layout "$staging_root"; then
            # Run the compatibility check BEFORE the apply menu so
            # the operator sees PVE-version / hostname / network /
            # storage drift up front. This also sets
            # HB_COMPAT_SAME_HOST, which downstream prompts
            # (_rs_prompt_zfs_opt_in) read to choose between the
            # silent same-host path and the loud cross-host path.
            hb_compat_check "$staging_root"
            if hb_show_compat_report; then
                if _rs_apply_menu "$staging_root"; then
                    rm -rf "$staging_root"
                    return 0
                fi
            fi
        fi

        rm -rf "$staging_root"
    done
}

# ==========================================================
# MAIN MENU
# ==========================================================
main_menu() {
    while true; do
        show_proxmenux_logo
        local choice
        choice=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Host Config Backup / Restore")" \
            --menu "\n$(translate "Select operation:")" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
            1   "$(translate "Backup host configuration")" \
            2   "$(translate "Restore host configuration")" \
            ""  "$(translate "─── Backup settings ────────────────────────────────")" \
            3   "$(translate "Manage custom paths (add / remove your folders)")" \
            4   "$(translate "Scheduled backups and retention policies")" \
            5   "$(translate "Configure backup destinations (PBS, Borg, local)")" \
            0   "$(translate "Return")" \
            3>&1 1>&2 2>&3) || break

        case "$choice" in
            1) backup_menu  ;;
            2) restore_menu ;;
            3) _bk_manage_extra_paths ;;
            4) _bk_scheduler ;;
            5) _bk_manage_destinations ;;
            0) break ;;
        esac
    done
}

main_menu
