#!/bin/bash
# ==========================================================
# ProxMenux - Run Scheduled Host Backup Job
# ==========================================================

set -u

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
  echo "ERROR: utils.sh not found" >&2
  exit 1
fi

LIB_FILE="$SCRIPT_DIR/lib_host_backup_common.sh"
[[ ! -f "$LIB_FILE" ]] && LIB_FILE="$LOCAL_SCRIPTS_DEFAULT/backup_restore/lib_host_backup_common.sh"
if [[ -f "$LIB_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$LIB_FILE"
else
  echo "ERROR: lib_host_backup_common.sh not found" >&2
  exit 1
fi

JOBS_DIR="${PMX_BACKUP_JOBS_DIR:-/var/lib/proxmenux/backup-jobs}"
LOG_DIR="${PMX_BACKUP_LOG_DIR:-/var/log/proxmenux/backup-jobs}"
LOCK_DIR="${PMX_BACKUP_LOCK_DIR:-/var/lock}"
mkdir -p "$JOBS_DIR" "$LOG_DIR" >/dev/null 2>&1 || true

_sb_prune_local() {
  local job_id="$1"
  local dest_dir="$2"
  local ext="$3" # tar.zst or tar.gz
  local keep_last="${KEEP_LAST:-0}"

  local -a files=()
  mapfile -t files < <(find "$dest_dir" -maxdepth 1 -type f -name "${job_id}-*.${ext}" | sort -r)
  [[ ${#files[@]} -eq 0 ]] && return 0

  if [[ "$keep_last" =~ ^[0-9]+$ ]] && (( keep_last > 0 )); then
    local idx=0
    for f in "${files[@]}"; do
      idx=$((idx+1))
      (( idx <= keep_last )) && continue
      # Remove the archive AND its sidecar in one shot — if we
      # leave .proxmenux.json files behind, the Monitor would
      # show them as broken entries pointing at deleted archives.
      rm -f "$f" "${f}.proxmenux.json" || true
    done
  fi
}

_sb_run_local() {
  local stage_root="$1"
  local job_id="$2"
  local ts="$3"
  local dest_dir="$4"
  local archive_ext="${LOCAL_ARCHIVE_EXT:-tar.zst}"
  local archive="${dest_dir}/${job_id}-${ts}.${archive_ext}"

  mkdir -p "$dest_dir" || return 1

  if [[ "$archive_ext" == "tar.zst" ]] && command -v zstd >/dev/null 2>&1; then
    tar --zstd -cf "$archive" -C "$stage_root" . >/dev/null 2>&1 || return 1
  else
    archive="${dest_dir}/${job_id}-${ts}.tar.gz"
    tar -czf "$archive" -C "$stage_root" . >/dev/null 2>&1 || return 1
    archive_ext="tar.gz"
  fi

  # Drop a sidecar JSON next to the archive — explicit marker the
  # Monitor can use to identify this as a scheduled host backup,
  # independent of any future rename of the archive.
  hb_write_archive_sidecar "$archive" "scheduled" "$job_id" "${PROFILE:-}" || true

  _sb_prune_local "$job_id" "$dest_dir" "$archive_ext"
  echo "LOCAL_ARCHIVE=$archive"
  return 0
}

_sb_run_borg() {
  local stage_root="$1"
  local archive_name="$2"
  local borg_bin repo passphrase

  borg_bin=$(hb_ensure_borg) || return 1
  repo="${BORG_REPO:-}"
  passphrase="${BORG_PASSPHRASE:-}"
  [[ -z "$repo" || -z "$passphrase" ]] && return 1

  # Re-export the credentials so child processes (borg, ssh) inherit
  # them. `source <job.env>` only assigns to the current shell — without
  # an explicit re-export, child `borg` calls drop back to ssh defaults
  # and a remote repo silently auth-fails with no log trail (since the
  # call is also `>/dev/null 2>&1`).
  export BORG_PASSPHRASE="$passphrase"
  [[ -n "${BORG_RSH:-}" ]] && export BORG_RSH
  export BORG_RELOCATED_REPO_ACCESS_IS_OK=yes
  export BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=yes

  if ! hb_borg_init_if_needed "$borg_bin" "$repo" "${BORG_ENCRYPT_MODE:-none}" >/dev/null 2>&1; then
    return 1
  fi

  (cd "$stage_root" && "$borg_bin" create --stats \
    "${repo}::${archive_name}" rootfs metadata) >/dev/null 2>&1 || return 1

  "$borg_bin" prune -v --list "$repo" \
    ${KEEP_LAST:+--keep-last "$KEEP_LAST"} \
    ${KEEP_HOURLY:+--keep-hourly "$KEEP_HOURLY"} \
    ${KEEP_DAILY:+--keep-daily "$KEEP_DAILY"} \
    ${KEEP_WEEKLY:+--keep-weekly "$KEEP_WEEKLY"} \
    ${KEEP_MONTHLY:+--keep-monthly "$KEEP_MONTHLY"} \
    ${KEEP_YEARLY:+--keep-yearly "$KEEP_YEARLY"} \
    >/dev/null 2>&1 || true

  echo "BORG_ARCHIVE=${archive_name}"
  return 0
}

_sb_run_pbs() {
  local stage_root="$1"
  local backup_id="$2"
  local epoch="$3"
  local -a cmd=(
    proxmox-backup-client backup
    "hostcfg.pxar:${stage_root}/rootfs"
    --repository "$PBS_REPOSITORY"
    --backup-type host
    --backup-id "$backup_id"
    --backup-time "$epoch"
  )

  [[ -z "${PBS_REPOSITORY:-}" || -z "${PBS_PASSWORD:-}" ]] && return 1
  if [[ -n "${PBS_KEYFILE:-}" ]]; then
    cmd+=(--keyfile "$PBS_KEYFILE")
  fi

  env PBS_PASSWORD="$PBS_PASSWORD" \
      PBS_ENCRYPTION_PASSWORD="${PBS_ENCRYPTION_PASSWORD:-}" \
      PBS_FINGERPRINT="${PBS_FINGERPRINT:-}" \
    "${cmd[@]}" 2>&1 || return 1

  # Best effort prune for PBS group.
  env PBS_PASSWORD="$PBS_PASSWORD" \
      PBS_FINGERPRINT="${PBS_FINGERPRINT:-}" \
    proxmox-backup-client prune "host/${backup_id}" --repository "$PBS_REPOSITORY" \
      ${KEEP_LAST:+--keep-last "$KEEP_LAST"} \
      ${KEEP_HOURLY:+--keep-hourly "$KEEP_HOURLY"} \
      ${KEEP_DAILY:+--keep-daily "$KEEP_DAILY"} \
      ${KEEP_WEEKLY:+--keep-weekly "$KEEP_WEEKLY"} \
      ${KEEP_MONTHLY:+--keep-monthly "$KEEP_MONTHLY"} \
      ${KEEP_YEARLY:+--keep-yearly "$KEEP_YEARLY"} \
      2>&1 || true

  echo "PBS_SNAPSHOT=host/${backup_id}/${epoch}"
  return 0
}

main() {
  local job_id="${1:-}"
  [[ -z "$job_id" ]] && { echo "Usage: $0 <job_id>" >&2; exit 1; }

  local job_file="${JOBS_DIR}/${job_id}.env"
  [[ -f "$job_file" ]] || { echo "Job not found: $job_id" >&2; exit 1; }

  # shellcheck source=/dev/null
  source "$job_file"

  local lock_file="${LOCK_DIR}/proxmenux-backup-${job_id}.lock"
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$lock_file" || exit 1
    if ! flock -n 9; then
      echo "Another run is active for job ${job_id}" >&2
      exit 1
    fi
  fi

  local ts log_file stage_root summary_file
  ts="$(date +%Y%m%d_%H%M%S)"
  log_file="${LOG_DIR}/${job_id}-${ts}.log"
  summary_file="${LOG_DIR}/${job_id}-last.status"
  stage_root="$(mktemp -d /tmp/proxmenux-sched-stage.XXXXXX)"

  {
    echo "JOB_ID=${job_id}"
    echo "RUN_AT=$(date -Iseconds)"
    echo "BACKEND=${BACKEND:-}"
    echo "PROFILE_MODE=${PROFILE_MODE:-default}"
  } >"$summary_file"

  {
    echo "=== Scheduled backup job ${job_id} started at $(date -Iseconds) ==="
    echo "Backend: ${BACKEND:-}"
    echo "Profile: ${PROFILE_MODE:-default}"
  } >"$log_file"

  local -a paths=()
  if [[ "${PROFILE_MODE:-default}" == "custom" && -f "${JOBS_DIR}/${job_id}.paths" ]]; then
    mapfile -t paths < "${JOBS_DIR}/${job_id}.paths"
  else
    mapfile -t paths < <(hb_default_profile_paths)
  fi

  if [[ ${#paths[@]} -eq 0 ]]; then
    echo "No paths configured for job" >>"$log_file"
    echo "RESULT=failed" >>"$summary_file"
    rm -rf "$stage_root"
    exit 1
  fi

  # Interactive output mirrors the colored layout of _bk_local in
  # backup_host.sh when stdout is a TTY (operator launched "Run job
  # now"). Otherwise — timer / vzdump hook — only the plain log
  # file is written.
  local TTY=0
  [[ -t 1 ]] && TTY=1

  if (( TTY )); then
    echo -e "${TAB}${BGN}$(translate "Backend:")${CL}        ${BL}${BACKEND}${CL}"
    echo -e "${TAB}${BGN}$(translate "Profile:")${CL}        ${BL}${PROFILE_MODE:-default}${CL}"
    echo -e "${TAB}${BGN}$(translate "Paths to back up:")${CL}  ${BL}${#paths[@]}${CL}"
    echo
    msg_info "$(translate "Preparing staging area...")"
  fi
  {
    echo "Paths to back up: ${#paths[@]}"
    echo "Preparing staging area at $stage_root ..."
  } >>"$log_file"
  hb_prepare_staging "$stage_root" "${paths[@]}" >>"$log_file" 2>&1
  local staged_files staged_size
  staged_files=$(find "$stage_root/rootfs" -type f 2>/dev/null | wc -l)
  staged_size=$(hb_file_size "$stage_root/rootfs" 2>/dev/null || echo "?")
  echo "Staging ready: $staged_files files copied (size $staged_size)." >>"$log_file"
  (( TTY )) && msg_ok "$(translate "Staging ready.") $(translate "Data size:") $staged_size — $staged_files $(translate "files")"

  local rc=1 t_start elapsed archive_path=""
  t_start=$SECONDS

  case "${BACKEND:-}" in
    local)
      (( TTY )) && { echo; msg_info "$(translate "Creating local archive...")"; stop_spinner; }
      echo "Writing local archive to ${LOCAL_DEST_DIR:-/var/lib/vz/dump} ..." >>"$log_file"
      local _output
      _output=$(_sb_run_local "$stage_root" "$job_id" "$ts" "${LOCAL_DEST_DIR:-/var/lib/vz/dump}" 2>>"$log_file")
      rc=$?
      echo "$_output" >>"$log_file"
      archive_path=$(grep "^LOCAL_ARCHIVE=" <<<"$_output" | cut -d'=' -f2-)
      ;;
    borg)
      (( TTY )) && { echo; msg_info "$(translate "Sending snapshot to Borg repository...")"; stop_spinner; }
      echo "Sending snapshot to Borg repository ${BORG_REPO:-} ..." >>"$log_file"
      _sb_run_borg "$stage_root" "${job_id}-${ts}" >>"$log_file" 2>&1
      rc=$?
      archive_path="${BORG_REPO:-}::${job_id}-${ts}"
      ;;
    pbs)
      (( TTY )) && { echo; msg_info "$(translate "Sending snapshot to PBS...")"; stop_spinner; }
      echo "Sending snapshot to PBS ${PBS_REPOSITORY:-} (id=${PBS_BACKUP_ID:-hostcfg-$(hostname)}) ..." >>"$log_file"
      _sb_run_pbs "$stage_root" "${PBS_BACKUP_ID:-hostcfg-$(hostname)}" "$(date +%s)" >>"$log_file" 2>&1
      rc=$?
      archive_path="${PBS_REPOSITORY:-}::host/${PBS_BACKUP_ID:-hostcfg-$(hostname)}"
      ;;
    *)
      echo "Unknown backend: ${BACKEND:-}" >>"$log_file"
      rc=1
      ;;
  esac

  elapsed=$((SECONDS - t_start))

  echo "Cleaning up staging area ..." >>"$log_file"
  rm -rf "$stage_root"

  if [[ $rc -eq 0 ]]; then
    echo "RESULT=ok" >>"$summary_file"
    echo "LOG_FILE=${log_file}" >>"$summary_file"
    echo "=== Job finished OK at $(date -Iseconds) ===" >>"$log_file"
    if (( TTY )); then
      local archive_size="-"
      case "${BACKEND:-}" in
        local) [[ -f "$archive_path" ]] && archive_size=$(hb_file_size "$archive_path") ;;
      esac
      local method_label
      case "${BACKEND:-}" in
        local) method_label="Local archive (tar)" ;;
        borg)  method_label="Borg repository" ;;
        pbs)   method_label="Proxmox Backup Server" ;;
      esac
      echo
      echo -e "${TAB}${BOLD}$(translate "Backup completed:")${CL}"
      echo -e "${TAB}${BGN}$(translate "Method:")${CL}        ${BL}${method_label}${CL}"
      [[ -n "$archive_path" ]] && \
        echo -e "${TAB}${BGN}$(translate "Archive:")${CL}       ${BL}${archive_path}${CL}"
      echo -e "${TAB}${BGN}$(translate "Data size:")${CL}     ${BL}${staged_size}${CL}"
      [[ "$archive_size" != "-" ]] && \
        echo -e "${TAB}${BGN}$(translate "Archive size:")${CL}  ${BL}${archive_size}${CL}"
      echo -e "${TAB}${BGN}$(translate "Duration:")${CL}      ${BL}$(hb_human_elapsed "$elapsed")${CL}"
      echo -e "${TAB}${BGN}$(translate "Log:")${CL}           ${BL}${log_file}${CL}"
      echo
      msg_ok "$(translate "Backup completed successfully.")"
    fi
    exit 0
  else
    echo "RESULT=failed" >>"$summary_file"
    echo "LOG_FILE=${log_file}" >>"$summary_file"
    echo "=== Job finished with errors at $(date -Iseconds) ===" >>"$log_file"
    (( TTY )) && msg_error "$(translate "Backup failed. See log:") $log_file"
    exit 1
  fi
}

main "$@"
