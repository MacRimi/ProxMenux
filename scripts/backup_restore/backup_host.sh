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
    # Return 1 propagates operator cancel from the encryption / passphrase
    # dialogs so the outer menu shows the source picker again instead of
    # proceeding with a half-configured backup.
    hb_ask_pbs_encryption || return 1

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

    # Notify host_backup_start. Per-channel/per-event toggles in
    # Settings decide whether the user actually receives it; same
    # template the scheduled runner uses.
    export HB_NOTIFY_JOB_ID="manual-pbs-${backup_id}"
    export HB_NOTIFY_BACKEND="pbs"
    export HB_NOTIFY_DESTINATION="$HB_PBS_REPOSITORY"
    export HB_NOTIFY_PROFILE_MODE="$profile_mode"
    export HB_NOTIFY_LOG_FILE="$log_file"
    export HB_NOTIFY_DATA_SIZE="$staged_size"
    hb_notify_lifecycle "start"

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
        # one was configured AND this backup actually used the
        # keyfile. Gating on HB_PBS_KEYFILE_OPT (rather than only on
        # the file existing on disk) stops the upload when the
        # operator declined encryption for this run but a recovery
        # blob is still cached from a prior encrypted backup: in
        # that case the blob does not describe this snapshot and
        # uploading it as a paired recovery would be misleading.
        # This runs as a SEPARATE backup group
        # (`host/hostcfg-<host>-keyrecovery`) with NO --keyfile,
        # so PBS stores it as a plain (non-PBS-encrypted) blob that
        # can be retrieved during fresh-install recovery. The blob
        # is still passphrase-protected by openssl.
        if [[ -n "$HB_PBS_KEYFILE_OPT" && -f "$HB_STATE_DIR/pbs-key.recovery.enc" ]]; then
            hb_pbs_upload_recovery_blob "$epoch" \
                || msg_warn "$(translate "Recovery blob upload failed — main backup is OK, but keyfile recovery from PBS will not be available for this backup.")"
        fi

        elapsed=$((SECONDS - t_start))
        local snap_time
        snap_time=$(date -d "@$epoch" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || date -r "$epoch" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || echo "$epoch")
        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Backup completed:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Method:")${CL}      ${BL}Proxmox Backup Server (PBS)${CL}"
        echo -e "${TAB}${BGN}$(translate "Repository:")${CL}  ${BL}${HB_PBS_REPOSITORY}${CL}"
        echo -e "${TAB}${BGN}$(translate "Backup ID:")${CL}   ${BL}${backup_id}${CL}"
        echo -e "${TAB}${BGN}$(translate "Backup path:")${CL} ${BL}host/${backup_id}/${snap_time}${CL}"
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
        export HB_NOTIFY_ARCHIVE_SIZE="-"
        export HB_NOTIFY_DURATION="$(hb_human_elapsed "$elapsed" 2>/dev/null || echo "${elapsed}s")"
        hb_notify_lifecycle "complete"
    else
        echo -e ""
        msg_error "$(translate "PBS backup failed.")"
        local _hb_reason
        _hb_reason=$(grep -iE 'error|fail|fatal|abort' "$log_file" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//')
        [[ -z "$_hb_reason" ]] && _hb_reason="proxmox-backup-client returned non-zero"
        export HB_NOTIFY_ARCHIVE_SIZE="-"
        export HB_NOTIFY_DURATION="$(hb_human_elapsed "$((SECONDS - t_start))" 2>/dev/null || echo "")"
        export HB_NOTIFY_REASON="$_hb_reason"
        hb_notify_lifecycle "fail"
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

    export HB_NOTIFY_JOB_ID="manual-borg-${archive_name}"
    export HB_NOTIFY_BACKEND="borg"
    export HB_NOTIFY_DESTINATION="$repo"
    export HB_NOTIFY_PROFILE_MODE="$profile_mode"
    export HB_NOTIFY_LOG_FILE="$log_file"
    export HB_NOTIFY_DATA_SIZE="$staged_size"
    hb_notify_lifecycle "start"

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
    # Include manifest.json (top-level) when present — without it,
    # parse_manifest.sh can't read the schema'd manifest on restore.
    local -a _bk_borg_paths=(rootfs metadata)
    [[ -f "$staging_root/manifest.json" ]] && _bk_borg_paths+=(manifest.json)
    if (cd "$staging_root" && "$borg_bin" create --stats --progress \
        "$repo::$archive_name" "${_bk_borg_paths[@]}") 2>&1 | tee -a "$log_file"; then

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
        export HB_NOTIFY_ARCHIVE_SIZE="$borg_compressed"
        export HB_NOTIFY_DURATION="$(hb_human_elapsed "$elapsed" 2>/dev/null || echo "${elapsed}s")"
        hb_notify_lifecycle "complete"
    else
        echo -e ""
        msg_error "$(translate "Borg backup failed.")"
        local _hb_reason
        _hb_reason=$(grep -iE 'error|fail|fatal|abort' "$log_file" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//')
        [[ -z "$_hb_reason" ]] && _hb_reason="borg create returned non-zero"
        export HB_NOTIFY_ARCHIVE_SIZE="-"
        export HB_NOTIFY_DURATION="$(hb_human_elapsed "$((SECONDS - t_start))" 2>/dev/null || echo "")"
        export HB_NOTIFY_REASON="$_hb_reason"
        hb_notify_lifecycle "fail"
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

    dest_dir=$(hb_select_local_target) || return 1
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

    export HB_NOTIFY_JOB_ID="manual-local-$(basename "$archive" .tar.zst)"
    export HB_NOTIFY_BACKEND="local"
    export HB_NOTIFY_DESTINATION="$archive"
    export HB_NOTIFY_PROFILE_MODE="$profile_mode"
    export HB_NOTIFY_LOG_FILE="$log_file"
    export HB_NOTIFY_DATA_SIZE="$staged_size"
    hb_notify_lifecycle "start"

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
        export HB_NOTIFY_ARCHIVE_SIZE="$archive_size"
        export HB_NOTIFY_DURATION="$(hb_human_elapsed "$elapsed" 2>/dev/null || echo "${elapsed}s")"
        hb_notify_lifecycle "complete"
    else
        echo -e ""
        msg_error "$(translate "Local backup failed.")"
        local _hb_reason
        _hb_reason=$(grep -iE 'error|fail|fatal|abort' "$log_file" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//')
        [[ -z "$_hb_reason" ]] && _hb_reason="tar/zstd returned non-zero"
        export HB_NOTIFY_ARCHIVE_SIZE="-"
        export HB_NOTIFY_DURATION="$(hb_human_elapsed "$elapsed" 2>/dev/null || echo "${elapsed}s")"
        export HB_NOTIFY_REASON="$_hb_reason"
        hb_notify_lifecycle "fail"
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
        # Single configured target (or none → caller falls back to default)
        local current=""
        current=$(hb_get_local_target 2>/dev/null) || current=""

        local body=""
        if [[ -n "$current" ]]; then
            body+="\Zb$(translate "Currently configured target:")\ZB"$'\n'
            body+="  \Z4${current}\Zn"
        else
            body+="$(translate "No target configured.")"$'\n'
            body+="$(translate "Default will be used:") \Z4${HB_LOCAL_TARGET_DEFAULT}\Zn"
        fi

        local -a menu_args=()
        menu_args+=("default" "1   $(translate "Use default") (${HB_LOCAL_TARGET_DEFAULT})")
        menu_args+=("custom"  "2   $(translate "Use a custom path")")
        menu_args+=("usb"     "3   $(translate "Use a USB disk")")
        if [[ -n "$current" ]]; then
            menu_args+=("clear"   "C   $(translate "Clear configured target")")
        fi
        menu_args+=("back"    "$(translate "← Return")")

        local choice
        choice=$(dialog --backtitle "ProxMenux" --colors \
            --title "$(translate "Manage local backup target")" \
            --menu "\n${body}\n" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${menu_args[@]}" \
            3>&1 1>&2 2>&3) || break

        case "$choice" in
            default)
                hb_set_local_target "$HB_LOCAL_TARGET_DEFAULT"
                ;;
            custom)
                local new_path
                new_path=$(dialog --backtitle "ProxMenux" \
                    --title "$(translate "Custom path")" \
                    --inputbox "$(translate "Absolute directory path to use as backup target:")" \
                    "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "/backup" \
                    3>&1 1>&2 2>&3) || continue
                new_path=$(hb_trim_dialog_value "$new_path")
                [[ -z "$new_path" ]] && continue
                mkdir -p "$new_path" 2>/dev/null || {
                    dialog --backtitle "ProxMenux" --msgbox \
                        "$(translate "Cannot create:") $new_path" 8 60
                    continue
                }
                hb_set_local_target "$new_path"
                ;;
            usb)
                _bk_local_target_usb_submenu
                ;;
            clear)
                hb_clear_local_target
                ;;
            back) break ;;
        esac
    done
}

# Submenu reached when the user picks "Use a USB disk" in the local
# target manager. Lists mounted USB partitions so the operator can pick
# one as the target; mount / unmount are auxiliary actions for preparing
# a fresh disk or releasing one. Picking a USB sets it as the configured
# target and returns to the parent menu.
_bk_local_target_usb_submenu() {
    while true; do
        local -a usb_mp=()
        local -a usb_desc=()
        local state path_or_dev label size fstype uuid
        while IFS=$'\t' read -r state path_or_dev label size fstype uuid; do
            [[ "$state" != "mounted" ]] && continue
            usb_mp+=("$path_or_dev")
            usb_desc+=("${label:-?}  [${fstype}]  $size  →  $path_or_dev")
        done < <(hb_list_usb_partitions)

        local body=""
        if (( ${#usb_mp[@]} > 0 )); then
            body+="\Zb$(translate "USB drives mounted now:")\ZB"$'\n'
            local d
            for d in "${usb_desc[@]}"; do
                body+="  • ${d}"$'\n'
            done
        else
            body+="$(translate "No USB drives mounted by ProxMenux yet. Mount one first to use it as a target.")"
        fi

        local -a menu_args=()
        if (( ${#usb_mp[@]} > 0 )); then
            menu_args+=("pick"    "$(translate "Pick a mounted USB as target")")
        fi
        menu_args+=("mount"   "⊕ $(translate "Mount a USB drive now")")
        if (( ${#usb_mp[@]} > 0 )); then
            menu_args+=("unmount" "⊖ $(translate "Unmount a USB drive")")
        fi
        menu_args+=("back"    "$(translate "← Return")")

        local choice
        choice=$(dialog --backtitle "ProxMenux" --colors \
            --title "$(translate "USB disk target")" \
            --menu "\n${body}\n" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${menu_args[@]}" \
            3>&1 1>&2 2>&3) || break

        case "$choice" in
            pick)
                local pick_menu=() i=1 idx
                for idx in "${!usb_mp[@]}"; do
                    pick_menu+=("$i" "${usb_desc[$idx]}"); ((i++))
                done
                local pick
                pick=$(dialog --backtitle "ProxMenux" \
                    --title "$(translate "Pick USB target")" \
                    --menu "\n$(translate "Select the mounted USB to use as backup target:")" \
                    "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${pick_menu[@]}" \
                    3>&1 1>&2 2>&3) || continue
                hb_set_local_target "${usb_mp[$((pick-1))]}"
                return 0
                ;;
            mount)
                # Auxiliary: prepare a USB so it can be picked next pass.
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
            3   "$(translate "Local archive targets (paths + USB mount/unmount)")" \
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
            "view" "$(translate "View current paths")" \
            "add"  "$(translate "+ Add a path")" \
            "del"  "$(translate "− Remove a path")" \
            "back" "$(translate "← Return")" \
            3>&1 1>&2 2>&3) || break

        case "$choice" in
            view)
                if (( count == 0 )); then
                    dialog --backtitle "ProxMenux" --msgbox \
                        "$(translate "You haven't added any custom paths yet.")" 8 60
                    continue
                fi
                local list_body="" pv
                for pv in "${paths[@]}"; do
                    list_body+="• ${pv}"$'\n'
                done
                dialog --backtitle "ProxMenux" \
                    --title "$(translate "Custom backup paths") (${count})" \
                    --msgbox "\n${list_body}" \
                    "$HB_UI_MENU_H" "$HB_UI_MENU_W"
                ;;
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
        # 12 visible rows (3 separators + 6 actions + Return + blanks).
        # Override the global HB_UI_MENU_LIST=10 locally so every row
        # fits without a scrollbar; the height bump to 24 keeps the
        # dialog chrome (title + borders + question prompt) from
        # squeezing the list area.
        choice=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Host Config Backup")" \
            --menu "\n$(translate "Select backup method and profile:")" \
            24 "$HB_UI_MENU_W" 13 \
            ""  "$(translate "────────────────── Default profile ───────────────────")" \
            1   "$(translate "Backup to Proxmox Backup Server (PBS)")" \
            2   "$(translate "Backup to Borg repository")" \
            3   "$(translate "Backup to local archive  (.tar.zst)")" \
            ""  " " \
            ""  "$(translate "─────── Custom profile (choose paths manually) ───────")" \
            4   "$(translate "Custom backup to PBS")" \
            5   "$(translate "Custom backup to Borg")" \
            6   "$(translate "Custom backup to local archive")" \
            ""  " " \
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
    mapfile -t snapshots < <(
        PBS_PASSWORD="$HB_PBS_SECRET" \
        PBS_FINGERPRINT="${HB_PBS_FINGERPRINT:-}" \
        proxmox-backup-client snapshot list \
            --repository "$HB_PBS_REPOSITORY" \
            --output-format json 2>/dev/null \
        | jq -r '.[]
            | select(."backup-type" == "host"
                     and (
                          ((."backup-id" | startswith("proxmenux-keyrecovery-"))
                           or ((."backup-id" | startswith("hostcfg-")) and (."backup-id" | endswith("-keyrecovery"))))
                          | not
                         ))
            | "\(."backup-type")|\(."backup-id")|\(."backup-time")"' 2>/dev/null \
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
        dialog --backtitle "ProxMenux" --title "$(translate "No backups")" \
            --msgbox "$(translate "No host backups were found in this PBS repository:")"$'\n\n'"$HB_PBS_REPOSITORY" \
            10 78
        return 1
    fi

    local menu=() i=1
    for snapshot in "${snapshots[@]}"; do menu+=("$i" "$snapshot"); ((i++)); done
    local sel
    sel=$(dialog --backtitle "ProxMenux" \
        --title "$(translate "Select backup to restore")" \
        --menu "\n$(translate "Available host backups:")" \
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
            --msgbox "$(translate "No .pxar archives were found in this backup:")"$'\n\n'"$snapshot" \
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
    echo -e "${TAB}${BGN}$(translate "Backup:")${CL}         ${BL}${snapshot}${CL}"
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
        extra_hint=$'\n\n'"$(translate "This backup is encrypted but no keyfile is available on this host.")"
        if [[ -f "$HB_STATE_DIR/pbs-key.conf" ]]; then
            extra_hint+=$'\n\n'"$(translate "A keyfile is present but doesn't match the one used to create the backup. Make sure you have the correct keyfile from the source host.")"
        else
            extra_hint+=$'\n\n'"$(translate "No keyfile recovery copy was found in PBS for this backup — it was created before the recovery feature existed. The encrypted content cannot be recovered.")"
        fi
    fi

    dialog --backtitle "ProxMenux" --title "$(translate "PBS extraction failed")" \
        --msgbox "$(translate "Could not extract from PBS.")"$'\n\n'"$(translate "Backup:") $snapshot"$'\n'"$(translate "Archive:") $archive$extra_hint" \
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
    # Skip `systemctl daemon-reload` when invoked from the Monitor
    # (HB_MONITOR_FLOW=1). The reload itself doesn't restart the
    # Monitor's unit, but it marks units as "needs restart" and a
    # later systemctl call against the Monitor would cut the WS
    # session. The restored unit files are already on disk — they
    # take effect at the next reboot, which the Monitor flow asks
    # for explicitly at the end.
    if [[ "$group" == "hot" || "$group" == "all" ]] && [[ "${HB_MONITOR_FLOW:-0}" != "1" ]]; then
        systemctl daemon-reload >/dev/null 2>&1 || true
    fi

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
        msg_ok "$(translate "Cluster data will be applied automatically at next boot.")"
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
    if [[ "${HB_MONITOR_FLOW:-0}" == "1" ]]; then
        # Same UX as the TUI but the prompt explicitly says "close"
        # — the Monitor's ScriptTerminalModal sees isComplete=true on
        # WS close and dismisses (via the onComplete prop) so the
        # operator doesn't need to click the Close button.
        msg_success "$(translate "Press Enter to close...")"
        read -r
        return 0
    fi
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
        bg_block+="  • $(translate "ProxMenux Monitor → Backups tab (live progress card with ETA, logs, rollback delta)")"$'\n'
        bg_block+="  • tail -f /var/log/proxmenux/proxmenux-cluster-postboot-*.log"$'\n'
        bg_block+="  • systemctl status proxmenux-apply-cluster-postboot.service"$'\n\n'
        bg_block+="$(translate "If notifications are enabled (Telegram/Discord/ntfy/...), you will receive a \"Host restore finished\" message when all background tasks complete.")"$'\n\n'
    fi

    local prompt="$(translate "Pending restore prepared. A reboot is required to complete it.")"$'\n\n'"${bg_block}$(translate "Reboot now?")"

    # Same dialog for TUI and Monitor — mirrors the post-install
    # flow (Yes → reboot, No → "You can reboot later manually").
    # The Monitor's PTY backs whiptail correctly, so the operator
    # sees the same Yes/No prompt as in the shell.
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

# Destructive rollback executor. Reads vms_to_remove / lxcs_to_remove
# from the rollback.json and runs `qm/pct stop + destroy --purge`
# on each. Component uninstall is not done here yet — the installers
# don't expose --auto-uninstall — so we just log them as TODO.
# Idempotent: missing/already-destroyed guests are skipped.
_rs_execute_rollback() {
    local rb_file="$1"
    [[ ! -s "$rb_file" ]] && return 0
    command -v jq >/dev/null 2>&1 || { msg_warn "$(translate 'jq not available — skipping rollback execution')"; return 0; }

    local vmids lxcids comps
    vmids=$(jq -r '.vms_to_remove[]?'             "$rb_file" 2>/dev/null)
    lxcids=$(jq -r '.lxcs_to_remove[]?'           "$rb_file" 2>/dev/null)
    comps=$(jq  -r '.components_to_uninstall[]?'  "$rb_file" 2>/dev/null)

    if [[ -z "$vmids" && -z "$lxcids" && -z "$comps" ]]; then
        msg_ok "$(translate 'Rollback: nothing to remove (host matches backup)')"
        return 0
    fi

    msg_info2 "$(translate 'Executing destructive rollback (operator confirmed) ...')"

    local id
    for id in $vmids; do
        [[ -z "$id" ]] && continue
        if qm status "$id" >/dev/null 2>&1; then
            echo "  → qm stop $id (extra VM, created after backup)"
            qm stop "$id" --timeout 30 >/dev/null 2>&1 || true
            echo "  → qm destroy $id --purge"
            if qm destroy "$id" --purge >/dev/null 2>&1; then
                msg_ok "$(translate 'VM removed:') $id"
            else
                msg_error "$(translate 'Failed to destroy VM:') $id"
            fi
        else
            echo "  • VM $id no longer present — skip"
        fi
    done

    for id in $lxcids; do
        [[ -z "$id" ]] && continue
        if pct status "$id" >/dev/null 2>&1; then
            echo "  → pct stop $id (extra LXC, created after backup)"
            pct stop "$id" >/dev/null 2>&1 || true
            echo "  → pct destroy $id --purge"
            if pct destroy "$id" --purge >/dev/null 2>&1; then
                msg_ok "$(translate 'LXC removed:') $id"
            else
                msg_error "$(translate 'Failed to destroy LXC:') $id"
            fi
        else
            echo "  • LXC $id no longer present — skip"
        fi
    done

    if [[ -n "$comps" ]]; then
        local comp
        for comp in $comps; do
            [[ -z "$comp" ]] && continue
            # Until each installer ships --auto-uninstall we can only
            # flag these for the operator. Once nvidia/amd/intel/coral
            # support it, this branch can shell out the same way the
            # auto-reinstall path does.
            msg_warn "$(translate 'Component to uninstall manually (no --auto-uninstall yet):') $comp"
        done
    fi

    # ── VFIO orphan cleanup + initramfs regen (BEFORE the reboot) ──
    # Restore is additive: if the host has VFIO config files that the
    # backup doesn't, they survive the apply. The 10-proxmenux-vfio-bind
    # udev rule, the nvidia hard-blacklist, the vfio-bind.bdfs state file,
    # the renamed *.proxmenux-disabled-vfio sidecars — all of them keep
    # the GPU bound to vfio-pci across the next boot. apply_pending_restore.sh
    # DOES delete them, but it runs AFTER systemd-udevd has already
    # bound the GPU. We have to clean them up while we're still in the
    # operator's restore terminal, then regenerate initramfs so the
    # boot comes up with the host-mode driver stack from the start.
    local _pending_rootfs
    _pending_rootfs="$(dirname "$rb_file")/rootfs"
    [[ -d "$_pending_rootfs" ]] && _rs_cleanup_vfio_orphans "$_pending_rootfs"
}

# Remove VFIO/passthrough artifacts that exist on the host but not in
# the backup, and reactivate any host-mode sidecars the backup ships
# disabled. Idempotent. Called from _rs_execute_rollback when the
# operator has opted into destructive rollback.
_rs_cleanup_vfio_orphans() {
    local backup_root="$1"
    local changed=0 f active

    # Files that ProxMenux manages and that force vfio-pci binding.
    # If they're not in the backup, the backup represents a host that
    # was NOT in VFIO mode → drop them from the host too.
    local -a vfio_owned=(
        "/etc/udev/rules.d/10-proxmenux-vfio-bind.rules"
        "/etc/modprobe.d/proxmenux-nvidia-vfio-blacklist.conf"
        "/etc/modprobe.d/proxmenux-nvidia-blacklist.conf"
        "/etc/modprobe.d/nvidia-blacklist.conf"
        "/etc/proxmenux/vfio-bind.bdfs"
    )
    for f in "${vfio_owned[@]}"; do
        if [[ -e "$f" && ! -e "${backup_root}${f}" ]]; then
            rm -f "$f" 2>/dev/null
            echo "  → removed orphan VFIO file: $f"
            changed=1
        fi
    done

    # Re-enable host-mode sidecars: the switch_gpu_mode flow renames
    # `nvidia-vfio.conf` → `nvidia-vfio.conf.proxmenux-disabled-vfio`
    # (and the same for the NVIDIA udev rules) when going LXC-only.
    # If the backup ships the *disabled* sidecar, swap it back in.
    local -a sidecars=(
        "/etc/modules-load.d/nvidia-vfio.conf"
        "/etc/udev/rules.d/70-nvidia.rules"
    )
    for active in "${sidecars[@]}"; do
        local disabled="${active}.proxmenux-disabled"
        local disabled_vfio="${active}.proxmenux-disabled-vfio"
        # Check both possible suffixes the switch_gpu scripts use.
        for f in "$disabled_vfio" "$disabled"; do
            if [[ -e "${backup_root}${f}" && ! -e "${backup_root}${active}" ]]; then
                # Backup expects this sidecar active. If the host has
                # the live file, leave it (it's still there); if it
                # has the disabled rename, swap.
                if [[ ! -e "$active" && -e "$f" ]]; then
                    mv "$f" "$active" 2>/dev/null
                    echo "  → reactivated host-mode sidecar: $active"
                    changed=1
                fi
            fi
        done
    done

    if (( changed )); then
        echo "  → regenerating initramfs so the next boot drops the VFIO stack ..."
        if update-initramfs -u >/dev/null 2>&1; then
            msg_ok "$(translate 'VFIO orphans cleared and initramfs rebuilt — next boot will free the GPU.')"
        else
            msg_warn "$(translate 'VFIO orphans cleared but initramfs rebuild failed; check /var/log/proxmenux logs.')"
        fi
    fi
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

    # Persist the rollback plan: VMs/LXCs/components that exist
    # on the host but not in the backup. apply_cluster_postboot.sh
    # surfaces a read-only "what differs" report from this file
    # after the boot. When the operator opted into destructive
    # rollback (HB_ROLLBACK_EXECUTE=1) we also destroy those
    # guests RIGHT NOW — before the reboot — so the operator
    # sees `qm destroy` live in the Monitor terminal AND the
    # next boot comes up without those guests reserving hardware
    # (critical for GPU passthrough: a stale VM with hostpci
    # entries makes Proxmox auto-bind the GPU to vfio-pci before
    # the nvidia driver can claim it).
    local _rb_script="${SCRIPT_DIR}/restore/compute_rollback_plan.sh"
    [[ ! -x "$_rb_script" ]] && _rb_script="${LOCAL_SCRIPTS:-/usr/local/share/proxmenux/scripts}/backup_restore/restore/compute_rollback_plan.sh"
    if [[ -x "$_rb_script" ]]; then
        bash "$_rb_script" "$staging_root" > "$pending_dir/rollback.json" 2>/dev/null || true
        [[ ! -s "$pending_dir/rollback.json" ]] && rm -f "$pending_dir/rollback.json"
    fi

    if [[ "${HB_ROLLBACK_EXECUTE:-0}" == "1" && -s "$pending_dir/rollback.json" ]] \
       && command -v jq >/dev/null 2>&1; then
        _rs_execute_rollback "$pending_dir/rollback.json"
    fi

    cat > "$pending_dir/plan.env" <<EOF
RESTORE_ID=${restore_id}
CREATED_AT=${created_at}
HB_RESTORE_INCLUDE_ZFS=${HB_RESTORE_INCLUDE_ZFS:-0}
HB_ROLLBACK_EXECUTE=${HB_ROLLBACK_EXECUTE:-0}
HB_COMPAT_CROSS_VERSION=${HB_COMPAT_CROSS_VERSION:-0}
HB_COMPAT_KERNEL_DIRECTION=${HB_COMPAT_KERNEL_DIRECTION:-same}
HB_HYDRATION_APPLIED=${HB_HYDRATION_APPLIED:-0}
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

# ==========================================================
# Kernel-agnostic hydration for bk_older restores
# ==========================================================
# In bk_older direction we block whole-file restores of the
# kernel/boot-tied paths (see hb_unsafe_paths_cross_version) to
# stop the target's boot from being poisoned by systemd unit
# overrides, APT sources, GRUB defaults, etc. from an older
# base. But the operator's OWN customisations inside those
# paths (IOMMU cmdline, VFIO modules, usb-storage.quirks, custom
# GRUB_TIMEOUT, ...) are kernel-agnostic and should still land
# on the target — otherwise a fresh install after a restore
# forgets everything the operator tuned.
#
# The hydration functions below implement a merge-not-copy
# strategy: they read the operator-authored bits from the
# manifest (cmdline_extra, modules_loaded_at_boot) or from
# specific whitelisted files in the staging rootfs, and merge
# them into the target's live config without touching keys or
# tokens the target already carries. All four phases are
# idempotent and additive; running them twice is a no-op.
# ==========================================================

_rs_hyd_manifest() { echo "$1/metadata/manifest.json"; }

# List operator-authored kernel cmdline tokens from the manifest,
# one per line. Empty output = nothing to merge.
_rs_hyd_cmdline_tokens() {
    local manifest="$1"
    [[ -f "$manifest" ]] || return 0
    command -v jq >/dev/null 2>&1 || return 0
    jq -r '.kernel_params.cmdline_extra // [] | .[]' "$manifest" 2>/dev/null || true
}

# List modules the backup loaded at boot (from /etc/modules on
# the source host), one per line.
_rs_hyd_modules_at_boot() {
    local manifest="$1"
    [[ -f "$manifest" ]] || return 0
    command -v jq >/dev/null 2>&1 || return 0
    jq -r '.kernel_params.modules_loaded_at_boot // [] | .[]' "$manifest" 2>/dev/null || true
}

# Read a KEY=VALUE line from a `/etc/default/grub`-style file.
# Prints the raw VALUE part (including surrounding quotes) if
# present, empty otherwise. Handles both `KEY=value` and
# `KEY="value with spaces"` forms.
_rs_hyd_grub_read_key() {
    local file="$1" key="$2"
    [[ -f "$file" ]] || return 0
    # Grab the LAST assignment (later wins in shell-style config),
    # skip comment lines, tolerate leading whitespace.
    grep -E "^[[:space:]]*${key}=" "$file" 2>/dev/null | tail -1 | sed -E "s/^[[:space:]]*${key}=//"
}

# Write or replace a KEY=VALUE line in a `/etc/default/grub`-style
# file. If the key already exists (uncommented), rewrites its
# line in place; otherwise appends the new line at the end. Leaves
# comment lines untouched.
_rs_hyd_grub_write_key() {
    local file="$1" key="$2" value="$3"
    [[ -f "$file" ]] || return 1
    if grep -qE "^[[:space:]]*${key}=" "$file"; then
        # In-place rewrite of the last matching line. Use sed with
        # a temp file so partial failure doesn't corrupt the target.
        local tmp
        tmp="$(mktemp)"
        awk -v k="$key" -v v="$value" '
            BEGIN { pat = "^[[:space:]]*" k "=" }
            $0 ~ pat { print k "=" v; next }
            { print }
        ' "$file" > "$tmp" && mv "$tmp" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}

# Strip surrounding double quotes and split a GRUB_CMDLINE_-style
# value into whitespace-delimited tokens (one per line). Handles
# escaped inner quotes conservatively.
_rs_hyd_cmdline_split() {
    local raw="$1"
    raw="${raw%\"}"; raw="${raw#\"}"
    raw="${raw%\'}"; raw="${raw#\'}"
    # tr will collapse any run of whitespace; xargs normalises.
    tr -s '[:space:]' '\n' <<<"$raw" | sed '/^$/d'
}

# Merge two cmdline strings: target wins on ties (same key), any
# backup token whose KEY (or bare flag) is not in target is
# appended. Prints the merged cmdline as a single line without
# surrounding quotes. Also returns 0 if any token was added, 1
# if nothing changed — useful for the caller to decide whether
# an update-grub / proxmox-boot-tool refresh is needed.
_rs_hyd_cmdline_merge() {
    local target_line="$1" backup_line="$2"
    local -A target_keys=()
    local -a merged=()
    local t bkey
    while IFS= read -r t; do
        [[ -z "$t" ]] && continue
        merged+=("$t")
        bkey="${t%%=*}"
        target_keys["$bkey"]=1
    done < <(_rs_hyd_cmdline_split "$target_line")
    local added=0
    while IFS= read -r t; do
        [[ -z "$t" ]] && continue
        bkey="${t%%=*}"
        if [[ -z "${target_keys[$bkey]:-}" ]]; then
            merged+=("$t")
            target_keys["$bkey"]=1
            added=1
        fi
    done < <(_rs_hyd_cmdline_split "$backup_line")
    printf '%s' "${merged[*]}"
    (( added )) && return 0 || return 1
}

# Phase 1a — GRUB path
# ────────────────────
# Merge cmdline tokens from the backup's cmdline_extra into the
# target's live GRUB_CMDLINE_LINUX_DEFAULT (never overwrite existing
# tokens or keys). Also merge whitelisted GRUB_* keys from the
# backup's /etc/default/grub whose values differ. Reports one
# summary line per action into the global RS_HYDRATION_ACTIONS[].
# $3=mode: "plan" reports would-be actions only, "commit" writes.
_rs_hyd_grub() {
    local backup_rootfs="$1" manifest="$2" mode="${3:-commit}"
    local target="/etc/default/grub"
    local bk_file="$backup_rootfs/etc/default/grub"
    [[ -f "$target" ]] || return 0

    local changed=0

    # ── cmdline merge ──
    local bk_tokens
    bk_tokens="$(_rs_hyd_cmdline_tokens "$manifest" | tr '\n' ' ')"
    if [[ -n "${bk_tokens// /}" ]]; then
        local live_default merged_default added_tokens
        live_default="$(_rs_hyd_grub_read_key "$target" GRUB_CMDLINE_LINUX_DEFAULT)"
        local stripped="${live_default%\"}"; stripped="${stripped#\"}"
        if merged_default="$(_rs_hyd_cmdline_merge "$stripped" "$bk_tokens")"; then
            added_tokens="$(comm -13 \
                <(printf '%s\n' $stripped | sort -u) \
                <(printf '%s\n' $merged_default | sort -u) 2>/dev/null | tr '\n' ' ')"
            [[ "$mode" == "commit" ]] && _rs_hyd_grub_write_key "$target" GRUB_CMDLINE_LINUX_DEFAULT "\"${merged_default}\""
            RS_HYDRATION_ACTIONS+=("GRUB_CMDLINE_LINUX_DEFAULT — merge tokens: ${added_tokens}")
            changed=1
        fi
    fi

    # ── whitelisted GRUB_* keys from the backup file ──
    if [[ -f "$bk_file" ]]; then
        local key bk_val live_val
        while IFS= read -r key; do
            [[ -z "$key" ]] && continue
            [[ "$key" == "GRUB_CMDLINE_LINUX_DEFAULT" || "$key" == "GRUB_CMDLINE_LINUX" ]] && continue
            bk_val="$(_rs_hyd_grub_read_key "$bk_file" "$key")"
            [[ -z "$bk_val" ]] && continue
            live_val="$(_rs_hyd_grub_read_key "$target" "$key")"
            if [[ "$bk_val" != "$live_val" ]]; then
                [[ "$mode" == "commit" ]] && _rs_hyd_grub_write_key "$target" "$key" "$bk_val"
                RS_HYDRATION_ACTIONS+=("${key} — restore operator value from backup")
                changed=1
            fi
        done < <(hb_grub_keys_whitelist)
    fi

    (( changed )) && return 0 || return 1
}

# Phase 1b — systemd-boot / ZFS path
# ──────────────────────────────────
# /etc/kernel/cmdline is a single-line file holding the ENTIRE
# kernel cmdline (root=, boot=, rootflags=, plus operator tokens).
# We MUST NOT copy it verbatim across kernels — the target's fresh
# install references its own ZFS pool. Instead: keep the target's
# boot boilerplate, append the operator tokens from cmdline_extra
# that aren't already there.
_rs_hyd_kernel_cmdline() {
    local manifest="$1" mode="${2:-commit}"
    local target="/etc/kernel/cmdline"
    [[ -f "$target" ]] || return 0

    local bk_tokens
    bk_tokens="$(_rs_hyd_cmdline_tokens "$manifest" | tr '\n' ' ')"
    [[ -z "${bk_tokens// /}" ]] && return 1

    local live merged added_tokens
    live="$(cat "$target" 2>/dev/null | tr -d '\n')"
    if merged="$(_rs_hyd_cmdline_merge "$live" "$bk_tokens")"; then
        added_tokens="$(comm -13 \
            <(printf '%s\n' $live | sort -u) \
            <(printf '%s\n' $merged | sort -u) 2>/dev/null | tr '\n' ' ')"
        [[ "$mode" == "commit" ]] && printf '%s\n' "$merged" > "$target"
        RS_HYDRATION_ACTIONS+=("/etc/kernel/cmdline (systemd-boot/ZFS) — merge tokens: ${added_tokens}")
        return 0
    fi
    return 1
}

# Phase 2 — /etc/modules merge
# ────────────────────────────
# Append modules from modules_loaded_at_boot that are whitelisted
# AND not already present in /etc/modules. Preserves comments and
# existing entries.
_rs_hyd_modules() {
    local manifest="$1" mode="${2:-commit}"
    local target="/etc/modules"
    [[ -f "$target" ]] || return 0

    local -A live_modules=() whitelist=()
    local m line
    while IFS= read -r line; do
        line="${line%%#*}"
        m="$(printf '%s' "$line" | xargs)"
        [[ -n "$m" ]] && live_modules["$m"]=1
    done < "$target"
    while IFS= read -r m; do
        m="$(printf '%s' "$m" | xargs)"
        [[ -n "$m" ]] && whitelist["$m"]=1
    done < <(hb_hydration_module_whitelist)

    local added=0
    while IFS= read -r m; do
        m="$(printf '%s' "$m" | xargs)"
        [[ -z "$m" ]] && continue
        [[ -z "${whitelist[$m]:-}" ]] && continue
        [[ -n "${live_modules[$m]:-}" ]] && continue
        [[ "$mode" == "commit" ]] && printf '%s\n' "$m" >> "$target"
        live_modules["$m"]=1
        RS_HYDRATION_ACTIONS+=("/etc/modules — add: $m")
        added=1
    done < <(_rs_hyd_modules_at_boot "$manifest")

    (( added )) && return 0 || return 1
}

# Phase 3 — whitelisted files
# ───────────────────────────
# For each pattern in hb_hydration_files_patterns, copy the
# matching file from the staging rootfs to the live target IF the
# backup carries it and its content differs from the live copy.
_rs_hyd_files() {
    local backup_rootfs="$1" mode="${2:-commit}"
    local pattern src dst
    local copied=0
    while IFS= read -r pattern; do
        [[ -z "$pattern" ]] && continue
        while IFS= read -r src; do
            [[ -z "$src" || ! -f "$src" ]] && continue
            dst="${src#${backup_rootfs}}"
            [[ "$dst" == /* ]] || continue
            if ! cmp -s "$src" "$dst" 2>/dev/null; then
                if [[ "$mode" == "commit" ]]; then
                    mkdir -p "$(dirname "$dst")" 2>/dev/null || true
                    cp -a "$src" "$dst" 2>/dev/null || continue
                fi
                RS_HYDRATION_ACTIONS+=("${dst} — restore from backup")
                copied=1
            fi
        done < <(compgen -G "${backup_rootfs}${pattern}" 2>/dev/null || true)
    done < <(hb_hydration_files_patterns)
    (( copied )) && return 0 || return 1
}

# Orchestrator for the 4 phases. Two modes:
#   plan   — populates RS_HYDRATION_ACTIONS and RS_HYDRATION_SUMMARY
#            without writing to any live file. Safe to call before
#            the operator's final yes/no.
#   commit — actually writes to the live target and exports
#            HB_HYDRATION_APPLIED=1 if anything changed, so that
#            plan.env carries the flag and apply_pending_restore.sh
#            forces NEEDS_INITRAMFS/NEEDS_GRUB.
# Both modes are safe to call multiple times: writes are additive
# and idempotent, plan is side-effect free.
_rs_apply_bk_older_hydration() {
    local staging_root="$1" mode="${2:-commit}"
    local backup_rootfs="$staging_root/rootfs"
    local manifest
    manifest="$(_rs_hyd_manifest "$staging_root")"

    RS_HYDRATION_ACTIONS=()
    RS_HYDRATION_SUMMARY=""

    [[ -d "$backup_rootfs" ]] || return 0

    local bootloader
    bootloader="$(hb_detect_bootloader)"

    local any=0
    case "$bootloader" in
        systemd-boot)
            _rs_hyd_kernel_cmdline "$manifest" "$mode" && any=1 || true
            ;;
        grub|*)
            _rs_hyd_grub "$backup_rootfs" "$manifest" "$mode" && any=1 || true
            ;;
    esac
    _rs_hyd_modules "$manifest" "$mode" && any=1 || true
    _rs_hyd_files "$backup_rootfs" "$mode" && any=1 || true

    if (( any )); then
        if [[ "$mode" == "commit" ]]; then
            HB_HYDRATION_APPLIED=1
            export HB_HYDRATION_APPLIED
        fi
        local body a header
        if [[ "$mode" == "plan" ]]; then
            header="$(translate "Operator config that WILL be re-applied via kernel-agnostic merge")"
        else
            header="$(translate "Operator config re-applied via kernel-agnostic merge")"
        fi
        body="\Zb${header}\ZB"$'\n\n'
        for a in "${RS_HYDRATION_ACTIONS[@]}"; do
            body+="  \Z2•\Zn ${a}"$'\n'
        done
        RS_HYDRATION_SUMMARY="$body"
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

    # ── NIC remap (silent, staging_root) ─────────────────────
    # If hb_plan_nic_remaps found NIC(s) with the same MAC as the
    # backup but a different ifname on the target (motherboard
    # swap that shifted PCI addresses), rewrite the staging config
    # in-place so the restored /etc/network/interfaces references
    # the ifname that actually exists on this host. Also builds
    # a small summary block for the confirm dialog — informative
    # only, no yes/no.
    RS_NIC_REMAP_SUMMARY=""
    # `${#ARR[@]:-0}` is NOT valid bash — you get either length OR
    # default, never both. `hb_plan_nic_remaps` initialises both
    # arrays (empty declarations) before this runs, so plain
    # `${#ARR[@]}` returns 0 for the empty case without tripping
    # `set -u`. Reported by a user during restore: "line 2195: bad
    # substitution".
    if (( ${#HB_NIC_REMAP[@]} > 0 || ${#HB_NIC_MAC_CHANGED[@]} > 0 )); then
        local nr_body entry old_if new_if nic_mac old_mac
        nr_body="\Zb$(translate "NIC changes detected — adjusted automatically")\ZB"$'\n\n'
        for entry in "${HB_NIC_REMAP[@]}"; do
            IFS='|' read -r old_if new_if nic_mac <<<"$entry"
            nr_body+="  \Z4•\Zn $(translate "Renamed"): \Zb${old_if}\ZB → \Zb${new_if}\ZB  ($(translate "same MAC"): ${nic_mac})"$'\n'
        done
        for entry in "${HB_NIC_MAC_CHANGED[@]}"; do
            IFS='|' read -r new_if old_mac nic_mac <<<"$entry"
            nr_body+="  \Z4•\Zn \Zb${new_if}\ZB $(translate "has a new MAC"): ${nic_mac} ($(translate "was") ${old_mac})"$'\n'
            nr_body+="    $(translate "If your DHCP has a static reservation for the old MAC, update it.")"$'\n'
        done
        RS_NIC_REMAP_SUMMARY="$nr_body"
        hb_apply_nic_remaps "$staging_root"
    fi

    # ── Cross-version safe-restore filter ────────────────────
    # Only activates on `bk_older` (backup kernel older than target).
    # The reverse direction (`bk_newer`) restores cleanly as-is —
    # verified empirically on multiple 9.2 → 9.1 restores with GPU
    # passthrough / IOMMU / DKMS drivers.
    RS_CROSS_VERSION_SKIPS=""
    if [[ "${HB_COMPAT_KERNEL_DIRECTION:-same}" == "bk_older" ]]; then
        local -a cv_skipped=()
        local cv_line cv_path cv_reason cv_rel
        # The drift block above trims the trailing newline off
        # RS_SKIP_PATHS ("${skip_paths%$'\n'}"), so the first cv_path
        # appended below would be pasted onto the previous drift path
        # (bench-reproduced: `/etc/kernel/proxmox-boot-uuids/etc/default/grub`
        # in rs-skip-paths.txt broke the match on /etc/default/grub,
        # apply_pending_restore restored it from the backup, update-grub
        # generated a boot config against the backup kernel and the
        # host paniced on next reboot). Restore the missing separator.
        [[ -n "$RS_SKIP_PATHS" && "${RS_SKIP_PATHS: -1}" != $'\n' ]] && RS_SKIP_PATHS+=$'\n'
        while IFS=$'\t' read -r cv_path cv_reason; do
            [[ -z "$cv_path" ]] && continue
            cv_rel="${cv_path#/}"
            # Only skip when the backup actually carries the path —
            # otherwise the "excluded" line is misleading.
            if [[ -e "$staging_root/rootfs/$cv_rel" ]]; then
                cv_skipped+=("${cv_path}"$'\t'"${cv_reason}")
                RS_SKIP_PATHS+="${cv_path}"$'\n'
            fi
        done < <(hb_unsafe_paths_cross_version)

        if (( ${#cv_skipped[@]} > 0 )); then
            local cv_body
            cv_body="\Zb$(translate "Cross-version detected — safe restore mode")\ZB"$'\n\n'
            cv_body+="$(translate "The backup was taken on a different PVE or kernel major.minor. These paths will be SKIPPED to keep the boot safe:")"$'\n\n'
            for cv_line in "${cv_skipped[@]}"; do
                cv_path="${cv_line%%$'\t'*}"
                cv_reason="${cv_line#*$'\t'}"
                cv_body+="  \Z1•\Zn \Zb${cv_path}\ZB"$'\n'
                cv_body+="    $(translate "${cv_reason}")"$'\n\n'
            done
            RS_CROSS_VERSION_SKIPS="$cv_body"
        fi
        # Trim any leading duplicate newlines the concat may introduce.
        RS_SKIP_PATHS="${RS_SKIP_PATHS#$'\n'}"
        RS_SKIP_PATHS="${RS_SKIP_PATHS%$'\n'}"
        export RS_SKIP_PATHS

        # Kernel-agnostic hydration of operator-authored bits that
        # would otherwise be lost with the whole-file skip above.
        # See _rs_apply_bk_older_hydration for the four merge phases.
        # Runs in "plan" mode BEFORE the confirm dialog so
        # RS_HYDRATION_SUMMARY can preview what will be re-applied;
        # the commit runs AFTER the operator says yes, right before
        # the hot apply.
        _rs_apply_bk_older_hydration "$staging_root" plan
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
    # Silent NIC remap block first (informational, no action needed
    # from the operator — the staging config has already been
    # rewritten). Kept above drift/cross-version because it's the
    # least alarming and the most common on hardware refreshes.
    if [[ -n "${RS_NIC_REMAP_SUMMARY:-}" ]]; then
        body+=$'\n'"${RS_NIC_REMAP_SUMMARY}"
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
    # Same treatment for cross-version skips (PVE major or kernel
    # major.minor differ between backup and target). The stashed
    # body already carries its own header — merge it as-is.
    if [[ -n "${RS_CROSS_VERSION_SKIPS:-}" ]]; then
        body+=$'\n'"${RS_CROSS_VERSION_SKIPS}"
    fi
    # And the counterpart: what gets re-applied via kernel-agnostic
    # merge. Rendered in green because it's what the operator gets
    # back for free even though the whole file was skipped above.
    if [[ -n "${RS_HYDRATION_SUMMARY:-}" ]]; then
        body+=$'\n'"${RS_HYDRATION_SUMMARY}"
    fi
    body+=$'\n'"\Zb\Z4$(translate "A reboot is required to finish the restore.")\Zn"$'\n\n'
    body+="$(translate "After the reboot you can follow the post-restore work live from ProxMenux Monitor → Backups tab (ETA, per-component status, log tail, rollback delta).")"$'\n\n'
    body+="$(translate "If notifications are enabled (Telegram/Discord/ntfy/...), you will receive a \"Host restore finished\" message when all background tasks complete.")"$'\n\n'
    body+="\Zb$(translate "Continue?")\ZB"

    if ! dialog --backtitle "ProxMenux" --colors \
            --title "$(translate "Confirm complete restore")" \
            --yesno "$body" 22 88; then
        return 1
    fi

    # ── Destructive rollback opt-in ───────────────────────────
    # If the host has VMs / LXCs / components that are NOT in
    # the backup, ask whether we should ALSO destroy them as
    # part of "rollback to the backup state". Without this the
    # restore is additive — a stale VM with hostpci entries
    # will keep reserving the GPU for vfio-pci after the boot
    # (we hit this in the test). Skip the prompt entirely when
    # already in HB_MONITOR_FLOW: the web UI raised its own
    # destructive-ack checkbox and exported HB_ROLLBACK_EXECUTE.
    if [[ "${HB_MONITOR_FLOW:-0}" != "1" && "${HB_ROLLBACK_EXECUTE:-0}" != "1" ]]; then
        local _rb_script="${SCRIPT_DIR}/restore/compute_rollback_plan.sh"
        [[ ! -x "$_rb_script" ]] && _rb_script="${LOCAL_SCRIPTS:-/usr/local/share/proxmenux/scripts}/backup_restore/restore/compute_rollback_plan.sh"
        if [[ -x "$_rb_script" ]] && command -v jq >/dev/null 2>&1; then
            local _rb_json
            _rb_json=$(bash "$_rb_script" "$staging_root" 2>/dev/null || true)
            if [[ -n "$_rb_json" ]]; then
                local _rb_vms _rb_lxcs _rb_comps
                _rb_vms=$(jq  -r '.vms_to_remove           | join(", ")' <<<"$_rb_json" 2>/dev/null)
                _rb_lxcs=$(jq -r '.lxcs_to_remove          | join(", ")' <<<"$_rb_json" 2>/dev/null)
                _rb_comps=$(jq -r '.components_to_uninstall| join(", ")' <<<"$_rb_json" 2>/dev/null)
                if [[ -n "$_rb_vms" || -n "$_rb_lxcs" || -n "$_rb_comps" ]]; then
                    local rb_body
                    rb_body="\Zb\Z1$(translate "Destructive rollback")\ZB\Zn"$'\n\n'
                    rb_body+="$(translate "The following entries exist on the host but were NOT in the backup. To make the host EXACTLY match the backup state, they must be removed:")"$'\n\n'
                    [[ -n "$_rb_vms"   ]] && rb_body+="  \Z1•\Zn $(translate "VMs to destroy:")  \Zb${_rb_vms}\ZB"$'\n'
                    [[ -n "$_rb_lxcs"  ]] && rb_body+="  \Z1•\Zn $(translate "LXCs to destroy:") \Zb${_rb_lxcs}\ZB"$'\n'
                    [[ -n "$_rb_comps" ]] && rb_body+="  \Z1•\Zn $(translate "Components to uninstall (manual for now):") \Zb${_rb_comps}\ZB"$'\n'
                    rb_body+=$'\n'"\Zb\Z1$(translate "This is IRREVERSIBLE.")\ZB\Zn"$'\n\n'
                    rb_body+="$(translate "Pick Yes to destroy them now (before reboot). Pick No to keep the additive restore and clean up manually later.")"
                    if dialog --backtitle "ProxMenux" --colors \
                            --title "$(translate "Execute destructive rollback?")" \
                            --defaultno --yesno "$rb_body" 20 88; then
                        export HB_ROLLBACK_EXECUTE=1
                    fi
                fi
            fi
        fi
    fi

    show_proxmenux_logo
    msg_title "$(translate "Applying safe paths and preparing pending restore")"
    # Commit the kernel-agnostic hydration BEFORE hot apply so
    # /etc/modules, /etc/default/grub (or /etc/kernel/cmdline),
    # and whitelisted vfio/nvidia files carry the operator's
    # tokens by the time apply_pending_restore.sh reads its
    # pending list. plan.env picks up HB_HYDRATION_APPLIED=1
    # and forces NEEDS_INITRAMFS/NEEDS_GRUB post-boot.
    if [[ "${HB_COMPAT_KERNEL_DIRECTION:-same}" == "bk_older" ]]; then
        _rs_apply_bk_older_hydration "$staging_root" commit
    fi
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
    # All locals prefixed with `_rup_` so the nameref doesn't bind
    # to one of OUR locals when a caller passes the same array name
    # (e.g. `_rs_unique_paths uniq "$@"` — bash would otherwise
    # resolve `__out_ref → uniq` to our local instead of the caller's).
    local _rup_out_var="$1"
    shift
    local -A _rup_seen=()
    local -a _rup_uniq=()
    local _rup_p
    for _rup_p in "$@"; do
        [[ -z "$_rup_p" || -n "${_rup_seen[$_rup_p]}" ]] && continue
        _rup_seen["$_rup_p"]=1
        _rup_uniq+=("$_rup_p")
    done
    local -n _rup_out_ref="$_rup_out_var"
    _rup_out_ref=("${_rup_uniq[@]}")
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
    # IMPORTANT: every local inside this function must use a unique
    # prefix (`_rsp_`). Bash nameref resolution walks the dynamic
    # scope outwards and stops at the first matching name — if we
    # declare `local -a selected_paths=()` while the caller's array
    # is also called `selected_paths`, _rs_unique_paths's
    # `local -n __out_ref="selected_paths"` would resolve to OUR
    # local one and the caller's array silently stays empty (which
    # surfaced as the "Selected paths produced no entries to apply"
    # dialog despite a non-empty selection).
    local _rsp_out_var="$2"
    local -n _rsp_out_ref="$_rsp_out_var"

    # ── Build the list of paths actually present in this backup ──
    local -a _rsp_backup=()
    local _rsp_selected_file="$staging_root/metadata/selected_paths.txt"
    if [[ -f "$_rsp_selected_file" ]]; then
        local _rsp_rel
        while IFS= read -r _rsp_rel; do
            [[ -z "$_rsp_rel" ]] && continue
            _rsp_rel="${_rsp_rel#/}"
            [[ -e "$staging_root/rootfs/$_rsp_rel" ]] && _rsp_backup+=("$_rsp_rel")
        done < "$_rsp_selected_file"
    else
        # Pre-metadata backup: walk rootfs/ at depth 1-2.
        local _rsp_entry
        while IFS= read -r _rsp_entry; do
            [[ -z "$_rsp_entry" ]] && continue
            _rsp_entry="${_rsp_entry#./}"
            _rsp_backup+=("$_rsp_entry")
        done < <(cd "$staging_root/rootfs" 2>/dev/null \
            && find . -mindepth 1 -maxdepth 2 -print 2>/dev/null)
    fi

    if [[ ${#_rsp_backup[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No paths available")" \
            --msgbox "$(translate "This backup does not contain any restorable paths.")" 8 70
        return 1
    fi

    # ── Non-interactive bypass for the Monitor ──
    local _rsp_selected=""
    if [[ -n "${HB_PRESELECTED_PATHS:-}" ]]; then
        local IFS=','
        local _rsp_pp
        for _rsp_pp in $HB_PRESELECTED_PATHS; do
            _rsp_pp="${_rsp_pp#"${_rsp_pp%%[![:space:]]*}"}"
            _rsp_pp="${_rsp_pp%"${_rsp_pp##*[![:space:]]}"}"
            [[ -z "$_rsp_pp" ]] && continue
            _rsp_pp="${_rsp_pp#/}"
            local _rsp_known
            for _rsp_known in "${_rsp_backup[@]}"; do
                [[ "$_rsp_pp" == "$_rsp_known" ]] && { _rsp_selected+="${_rsp_pp}"$'\n'; break; }
            done
        done
        unset IFS
    fi

    # ── Dialog checklist (one entry per real backup path) ──
    if [[ -z "$_rsp_selected" ]]; then
        # In bk_older restores, kernel-tied paths are excluded from
        # the list entirely (bash `dialog` has no gray-out primitive,
        # so we hide the unsafe entries and surface their names in a
        # msgbox up front). Uses the same list `hb_unsafe_paths_cross_version`
        # returns — single source of truth with the safe filter used
        # by Full restore.
        local -A _rsp_blocked=()
        local -a _rsp_blocked_list=()
        if [[ "${HB_COMPAT_KERNEL_DIRECTION:-same}" == "bk_older" ]]; then
            local _rsp_bp _rsp_reason
            while IFS=$'\t' read -r _rsp_bp _rsp_reason; do
                [[ -z "$_rsp_bp" ]] && continue
                local _rsp_bp_rel="${_rsp_bp#/}"
                _rsp_blocked["$_rsp_bp_rel"]=1
            done < <(hb_unsafe_paths_cross_version)
        fi

        local -a _rsp_checklist=()
        local _rsp_p
        for _rsp_p in "${_rsp_backup[@]}"; do
            # Skip paths whose parent (or itself) is on the blocked
            # list: `/etc/systemd/system/foo` counts as blocked when
            # `/etc/systemd/system` is on the list.
            local _rsp_hit="" _rsp_probe="$_rsp_p"
            while [[ -n "$_rsp_probe" ]]; do
                if [[ -n "${_rsp_blocked[$_rsp_probe]:-}" ]]; then
                    _rsp_hit="/$_rsp_probe"
                    break
                fi
                [[ "$_rsp_probe" != *"/"* ]] && break
                _rsp_probe="${_rsp_probe%/*}"
            done
            if [[ -n "$_rsp_hit" ]]; then
                _rsp_blocked_list+=("$_rsp_hit")
                continue
            fi
            _rsp_checklist+=("$_rsp_p" "/$_rsp_p" "off")
        done

        # If any paths were dropped, show them in a msgbox before the
        # picker so the operator understands why they don't appear.
        if (( ${#_rsp_blocked_list[@]} > 0 )); then
            # Deduplicate — a folder can hide many child paths.
            local -A _rsp_seen=()
            local _rsp_list_str=""
            local _rsp_e
            for _rsp_e in "${_rsp_blocked_list[@]}"; do
                [[ -n "${_rsp_seen[$_rsp_e]:-}" ]] && continue
                _rsp_seen["$_rsp_e"]=1
                _rsp_list_str+="  • ${_rsp_e}"$'\n'
            done
            dialog --backtitle "ProxMenux" --colors \
                --title "$(translate "Cross-kernel — paths hidden from picker")" \
                --msgbox "$(translate "The following backup paths are kernel-tied and are excluded from the picker to keep the target's boot safe. The operator's own tuning inside these paths (IOMMU cmdline, VFIO IDs, custom quirks) is merged back automatically via kernel-agnostic merge:")"$'\n\n'"${_rsp_list_str}"$'\n'"$(translate "To copy any of these files verbatim, restore this backup on a host with the same kernel major.minor.")" \
                22 84
        fi

        if (( ${#_rsp_checklist[@]} == 0 )); then
            dialog --backtitle "ProxMenux" --title "$(translate "Nothing selectable")" \
                --msgbox "$(translate "Every path in this backup is kernel-tied: the restore applies these paths automatically via the safe-subset filter and re-merges the operator's tuning.")" 10 82
            return 1
        fi

        _rsp_selected=$(dialog --backtitle "ProxMenux" --separate-output \
            --title "$(translate "Custom restore by paths")" \
            --checklist "\n$(translate "Select the paths to restore (one per backup entry):")" \
            24 94 16 "${_rsp_checklist[@]}" 3>&1 1>&2 2>&3) || return 1

        if [[ -z "$_rsp_selected" ]]; then
            dialog --backtitle "ProxMenux" --title "$(translate "Nothing selected")" \
                --msgbox "$(translate "Select at least one path to continue.")" 8 66
            return 1
        fi
    fi

    local -a _rsp_picked=()
    local _rsp_line
    while IFS= read -r _rsp_line; do
        [[ -z "$_rsp_line" ]] && continue
        _rsp_picked+=("$_rsp_line")
    done <<< "$_rsp_selected"

    _rs_unique_paths "$_rsp_out_var" "${_rsp_picked[@]}"

    if [[ ${#_rsp_out_ref[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "Nothing to restore")" \
            --msgbox "$(translate "Selected paths produced no entries to apply.")" 8 70
        return 1
    fi
    return 0
}

_rs_run_custom_restore() {
    local staging_root="$1"
    local -a selected_paths=()

    _rs_select_component_paths "$staging_root" selected_paths || return 1
    _rs_collect_stats_for_paths "${selected_paths[@]}"

    # ── Smart auto-strategy (no 6-option menu any more) ──
    # The classifier already split every selected path into:
    #   RS_SEL_HOT       — applyable live, no risk
    #   RS_SEL_REBOOT    — needs reboot to take effect
    #   RS_SEL_DANGEROUS — applyable live but risky (e.g. network
    #                      from a SSH session)
    # The operator doesn't need to know that taxonomy. We just:
    #   1. Show ONE confirmation summarizing what happens.
    #   2. Apply hot paths now.
    #   3. Schedule reboot + dangerous paths for next boot.
    #   4. Tell the operator a reboot is needed when there's pending.

    if [[ "$RS_SEL_TOTAL" -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "Nothing to restore")" \
            --msgbox "$(translate "Selected paths produced no entries to apply.")" 8 70
        return 1
    fi

    # SSH/network protection — if the operator is on a SSH session
    # and selected network paths, offer to move EVERYTHING to next
    # boot (avoids disconnection mid-restore). _rs_handle_ssh_network_risk
    # returns 2 when it has already scheduled for boot — in that case
    # we're done.
    local ssh_network_rc
    _rs_handle_ssh_network_risk "$staging_root" "${selected_paths[@]}"
    ssh_network_rc=$?
    [[ $ssh_network_rc -eq 2 ]] && return 0
    [[ $ssh_network_rc -ne 0 ]] && return 1

    local hot_count="$RS_SEL_HOT"
    local pending_count=$(( RS_SEL_REBOOT + RS_SEL_DANGEROUS ))

    # In bk_older, preview the kernel-agnostic hydration so the
    # operator sees UPFRONT what will be re-applied automatically
    # (IOMMU cmdline, VFIO modules, custom GRUB_TIMEOUT, etc.)
    # even though the whole-file paths remain blocked from the
    # custom picker.
    if [[ "${HB_COMPAT_KERNEL_DIRECTION:-same}" == "bk_older" ]]; then
        _rs_apply_bk_older_hydration "$staging_root" plan
    fi

    local body
    body="\Zb$(translate "About to restore") ${RS_SEL_TOTAL} $(translate "selected path(s):")\ZB"$'\n\n'
    if (( hot_count > 0 )); then
        body+="  • $(translate "Apply") \Zb\Z4${hot_count}\Zn $(translate "now")"$'\n'
    fi
    if (( pending_count > 0 )); then
        body+="  • $(translate "Schedule") \Zb\Z4${pending_count}\Zn $(translate "for next boot (needs reboot to take effect)")"$'\n'
    fi
    if [[ -n "${RS_HYDRATION_SUMMARY:-}" ]]; then
        body+=$'\n'"${RS_HYDRATION_SUMMARY}"
    fi
    if (( pending_count > 0 )); then
        body+=$'\n'"\Zb\Z4$(translate "A reboot will be required to complete the restore.")\Zn"$'\n'
        body+="$(translate "Follow post-restore progress live from ProxMenux Monitor → Backups tab after the reboot.")"$'\n'
    fi
    body+=$'\n'"\Zb$(translate "Continue?")\ZB"

    if ! dialog --backtitle "ProxMenux" --colors \
        --title "$(translate "Confirm custom restore")" \
        --yesno "$body" 22 82; then
        return 1
    fi

    show_proxmenux_logo
    msg_title "$(translate "Applying custom restore")"

    # Commit the hydration BEFORE hot apply. Same rationale as in
    # the Complete flow: plan.env picks up HB_HYDRATION_APPLIED=1
    # so apply_pending_restore.sh forces initramfs+grub regen.
    if [[ "${HB_COMPAT_KERNEL_DIRECTION:-same}" == "bk_older" ]]; then
        _rs_apply_bk_older_hydration "$staging_root" commit
    fi

    if (( hot_count > 0 )); then
        _rs_apply "$staging_root" hot "${selected_paths[@]}"
    fi

    if (( pending_count > 0 )); then
        local -a pending_paths=()
        mapfile -t pending_paths < <(_rs_collect_pending_paths remaining_after_hot "${selected_paths[@]}")
        if _rs_prepare_pending_restore "$staging_root" "${pending_paths[@]}"; then
            msg_warn "$(translate "Reboot is required to complete the pending restore.")"
        fi
    elif [[ "${HB_HYDRATION_APPLIED:-0}" == "1" ]]; then
        # Custom restore picked only hot paths, but hydration
        # merged tokens into /etc/default/grub or /etc/kernel/cmdline
        # and/or added modules to /etc/modules. Those need
        # initramfs + bootloader refresh before the next reboot to
        # be effective. No post-boot dispatcher runs in this
        # branch (plan.env is only written by
        # _rs_prepare_pending_restore), so we do the reflows here.
        msg_info "$(translate "Regenerating boot artifacts for the merged kernel-agnostic changes...")"
        update-initramfs -u -k all >/dev/null 2>&1 || true
        local _bl
        _bl="$(hb_detect_bootloader)"
        case "$_bl" in
            systemd-boot) proxmox-boot-tool refresh >/dev/null 2>&1 || true ;;
            grub|*)       update-grub               >/dev/null 2>&1 || true ;;
        esac
        stop_spinner 2>/dev/null || true
        msg_ok "$(translate "Boot artifacts regenerated — reboot the host to activate the merged config.")"
    fi

    _rs_finish_flow
    return 0
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
            # ── Intelligent package filter (universal, not cross-version-only) ─
            #
            # `packages.manual.list` lists everything apt-marked as manual on
            # the SOURCE host. A blind `apt install` of that list on the
            # target can wreck it in two ways:
            #
            #   1. The backup pinned a package to an older SO-major (e.g.
            #      libzfs6linux from Proxmox 9.1) but the target already
            #      ships the newer sibling (libzfs7linux from 9.2). APT
            #      would resolve the older version by cascade-removing the
            #      newer one plus everything that depends on it
            #      (zfsutils-linux, zfs-initramfs, zfs-zed). The `zpool`
            #      binary vanishes → next reboot panics on rpool mount.
            #      Bench-reproduced on nvidia3 (9.2.3 / kernel 7.0.12) with
            #      an nvidia2 backup (9.1.9 / kernel 6.17.2).
            #
            #   2. Some packages are already present on the target because
            #      the fresh install included them — apt doesn't need us
            #      to re-request them, and re-requesting can pull config
            #      prompts we don't want during unattended restore.
            #
            # The filter runs three passes:
            #   (a) already_installed  → dpkg -s says the pkg is on target
            #   (b) provided_by_newer  → target already has libFOO<N>* where
            #                            the backup's pkg is libFOO<M>* with
            #                            M < N (SO-major bump between
            #                            Proxmox releases)
            #   (c) cascade_risk       → apt-get simulate proves the install
            #                            would REMOVE something critical
            #
            # Each pass populates a report array. Nothing is silent — the
            # operator sees the final tally with reasons.
            local -a rep_skipped_installed=()
            local -a rep_skipped_provided=()
            local -a rep_skipped_cascade=()
            local -a rep_unknown=()
            local -a candidates=()

            local pkg
            for pkg in "${missing[@]}"; do
                # Pass (a): already installed?
                if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null \
                    | grep -q '^install ok installed$'; then
                    rep_skipped_installed+=("$pkg")
                    continue
                fi
                # Pass (b): provided by newer sibling? Only for
                # `<base><N><suffix>` shaped names — the SO-major
                # convention used by libzfs<N>linux, libzpool<N>linux,
                # libnvpair<N>linux, libuutil<N>linux, libzstd<N>, etc.
                if [[ "$pkg" =~ ^(lib[a-z]+)([0-9]+)([a-z]*[0-9]*)$ ]]; then
                    local _base="${BASH_REMATCH[1]}"
                    local _num="${BASH_REMATCH[2]}"
                    local _suffix="${BASH_REMATCH[3]}"
                    local _newer_found=""
                    # Only look up to +5 majors ahead — enough to cover any
                    # realistic Proxmox jump without probing forever.
                    local _n
                    for _n in $(seq $((_num + 1)) $((_num + 5))); do
                        local _sibling="${_base}${_n}${_suffix}"
                        if dpkg-query -W -f='${Status}' "$_sibling" 2>/dev/null \
                            | grep -q '^install ok installed$'; then
                            _newer_found="$_sibling"
                            break
                        fi
                    done
                    if [[ -n "$_newer_found" ]]; then
                        rep_skipped_provided+=("${pkg}|${_newer_found}")
                        continue
                    fi
                fi
                # Not skipped yet — needs the apt cache to know if it's
                # installable at all. Unknown-to-apt goes to its own list.
                if apt-cache show "$pkg" >/dev/null 2>&1; then
                    candidates+=("$pkg")
                else
                    rep_unknown+=("$pkg")
                fi
            done

            # Pass (c): apt-simulate to catch cascade-remove risk. We
            # simulate the full candidate set first; if apt would remove
            # anything, iteratively drop the "first offender" (the pkg
            # that appears earliest in the simulated remove path) and
            # retry until the simulation is clean or the list is empty.
            local -a installable=()
            if (( ${#candidates[@]} > 0 )) && command -v apt-get >/dev/null 2>&1; then
                local _work=("${candidates[@]}")
                local _guard=0
                while (( ${#_work[@]} > 0 && _guard < 20 )); do
                    _guard=$((_guard + 1))
                    local _sim_out
                    _sim_out=$(DEBIAN_FRONTEND=noninteractive \
                        apt-get install -y --simulate --no-install-recommends \
                        -o Dpkg::Options::="--force-confdef" \
                        -o Dpkg::Options::="--force-confold" \
                        "${_work[@]}" 2>&1)
                    # Look for removals: apt marks them as `Remv <pkg>...`
                    # in the plan output.
                    local -a _would_remove=()
                    mapfile -t _would_remove < <(printf '%s\n' "$_sim_out" \
                        | awk '/^Remv / {print $2}')
                    if (( ${#_would_remove[@]} == 0 )); then
                        installable=("${_work[@]}")
                        break
                    fi
                    # Pick the offender: a package in _work whose install
                    # is directly linked to the removal. Heuristic — if
                    # any _work package shares the base+suffix pattern
                    # with a would-remove package but a different major,
                    # that's the offender. Otherwise, drop the last one
                    # (least "essential" by convention of the list).
                    local _offender=""
                    local _rm
                    for _rm in "${_would_remove[@]}"; do
                        if [[ "$_rm" =~ ^(lib[a-z]+)([0-9]+)([a-z]*[0-9]*)$ ]]; then
                            local _rmbase="${BASH_REMATCH[1]}"
                            local _rmsuffix="${BASH_REMATCH[3]}"
                            local _cand
                            for _cand in "${_work[@]}"; do
                                if [[ "$_cand" =~ ^${_rmbase}[0-9]+${_rmsuffix}$ ]]; then
                                    _offender="$_cand"; break
                                fi
                            done
                        fi
                        [[ -n "$_offender" ]] && break
                    done
                    if [[ -z "$_offender" ]]; then
                        # No obvious mapping — bail out safely: report
                        # everything as cascade risk and install nothing.
                        rep_skipped_cascade+=("${_work[@]/#/${_would_remove[0]}<-}")
                        _work=()
                        break
                    fi
                    rep_skipped_cascade+=("${_offender}|would remove ${_would_remove[*]:0:3}")
                    # Drop the offender and retry.
                    local -a _new_work=()
                    local _c
                    for _c in "${_work[@]}"; do
                        [[ "$_c" == "$_offender" ]] || _new_work+=("$_c")
                    done
                    _work=("${_new_work[@]}")
                done
            fi

            local -a unknown=("${rep_unknown[@]}")

            # ── Summarize what the filter decided ──
            if (( ${#rep_skipped_installed[@]} > 0 )); then
                local _prev="${rep_skipped_installed[*]:0:5}"
                (( ${#rep_skipped_installed[@]} > 5 )) && _prev+=" … (+ $((${#rep_skipped_installed[@]} - 5)) more)"
                echo -e "${TAB}${BGN}$(translate "Already installed — skipping"):${CL} ${BL}${_prev}${CL}"
            fi
            if (( ${#rep_skipped_provided[@]} > 0 )); then
                echo -e "${TAB}${BGN}$(translate "Provided by newer version — skipping"):${CL}"
                local _rec
                for _rec in "${rep_skipped_provided[@]}"; do
                    echo -e "${TAB}  ${DGN}${_rec%%|*}${CL} → ${BL}${_rec##*|}${CL}"
                done
            fi
            if (( ${#rep_skipped_cascade[@]} > 0 )); then
                echo -e "${TAB}${YWB}$(translate "Skipped to protect target system (would cascade-remove packages)"):${CL}"
                local _rec
                for _rec in "${rep_skipped_cascade[@]}"; do
                    echo -e "${TAB}  ${YWB}${_rec%%|*}${CL} — ${_rec##*|}"
                done
            fi

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

    # ── Cross-kernel notice (only for bk_older) ───────────────
    # When the backup was taken on a kernel older than the target,
    # let the operator know BEFORE they see the mode menu that
    # Full restore will silently skip kernel-tied paths and that
    # Custom will present them as blocked. Nothing to click through
    # for the reverse direction (bk_newer) — those restores go
    # through as-is because empirical testing shows they work.
    if [[ "${HB_COMPAT_KERNEL_DIRECTION:-same}" == "bk_older" ]]; then
        local _bkk="" _cur_k _cur_mm
        [[ -f "$staging_root/metadata/run_info.env" ]] && \
            _bkk=$(grep -m1 '^kernel=' "$staging_root/metadata/run_info.env" 2>/dev/null | cut -d= -f2-)
        _cur_k=$(uname -r 2>/dev/null || echo "?")
        _cur_mm=$(echo "$_cur_k" | cut -d. -f1-2)
        dialog --backtitle "ProxMenux" --colors \
            --title "$(translate "Cross-kernel restore — kernel-tied paths merged, not copied")" \
            --msgbox "$(translate "This backup was taken on kernel"): \Zb${_bkk}\ZB"$'\n'"$(translate "Target host runs"): \Zb${_cur_k}\ZB"$'\n\n'"\Zb$(translate "Everything restorable in this backup will be restored"):\ZB $(translate "VMs, LXCs, network, /etc/pve, users, cron, packages, drivers, ProxMenux state, etc.")"$'\n\n'"$(translate "Kernel/boot-tied files (boot config, /etc/systemd/system, initramfs config, apt sources, ZFS state, ...) are NOT copied verbatim to keep the target's boot safe. The operator's own tuning inside them (IOMMU cmdline, VFIO IDs, custom quirks, GRUB timeout, ...) is merged into the target's fresh copies automatically via kernel-agnostic merge.")" \
            20 84
    fi

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
            # Plan NIC remaps FIRST so hb_compat_check knows which
            # "missing" NICs are actually renames (same MAC, new
            # ifname after a motherboard swap) and can downgrade
            # them from FAIL to INFO. Also fills HB_NIC_MAC_CHANGED
            # for same-name-different-MAC hosts.
            hb_plan_nic_remaps "$staging_root"

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
        local choice
        choice=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Host Config Backup / Restore")" \
            --menu "\n$(translate "Select operation:")" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
            1   "$(translate "Backup host configuration")" \
            2   "$(translate "Restore host configuration")" \
            ""  " " \
            ""  "$(translate "─────────────────────── Backup settings ───────────────────────")" \
            ""  " " \
            3   "$(translate "Manage custom paths (add / remove your folders)")" \
            4   "$(translate "Scheduled backups and retention policies")" \
            5   "$(translate "Configure backup destinations (PBS, Borg, local)")" \
            ""  " " \
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

# Only spawn the TUI when invoked directly. Sourcing the file
# (e.g. from restore/monitor_apply.sh) imports all the functions
# without triggering the main menu.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main_menu
fi
