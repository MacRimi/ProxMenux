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

  export BORG_PASSPHRASE="$passphrase"

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

  env PBS_PASSWORD="$PBS_PASSWORD" PBS_ENCRYPTION_PASSWORD="${PBS_ENCRYPTION_PASSWORD:-}" \
    "${cmd[@]}" >/dev/null 2>&1 || return 1

  # Best effort prune for PBS group.
  proxmox-backup-client prune "host/${backup_id}" --repository "$PBS_REPOSITORY" \
    ${KEEP_LAST:+--keep-last "$KEEP_LAST"} \
    ${KEEP_HOURLY:+--keep-hourly "$KEEP_HOURLY"} \
    ${KEEP_DAILY:+--keep-daily "$KEEP_DAILY"} \
    ${KEEP_WEEKLY:+--keep-weekly "$KEEP_WEEKLY"} \
    ${KEEP_MONTHLY:+--keep-monthly "$KEEP_MONTHLY"} \
    ${KEEP_YEARLY:+--keep-yearly "$KEEP_YEARLY"} \
    >/dev/null 2>&1 || true

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

  hb_prepare_staging "$stage_root" "${paths[@]}" >>"$log_file" 2>&1

  local rc=1
  case "${BACKEND:-}" in
    local)
      _sb_run_local "$stage_root" "$job_id" "$ts" "${LOCAL_DEST_DIR:-/var/lib/vz/dump}" >>"$log_file" 2>&1
      rc=$?
      ;;
    borg)
      _sb_run_borg "$stage_root" "${job_id}-${ts}" >>"$log_file" 2>&1
      rc=$?
      ;;
    pbs)
      _sb_run_pbs "$stage_root" "${PBS_BACKUP_ID:-hostcfg-$(hostname)}" "$(date +%s)" >>"$log_file" 2>&1
      rc=$?
      ;;
    *)
      echo "Unknown backend: ${BACKEND:-}" >>"$log_file"
      rc=1
      ;;
  esac

  rm -rf "$stage_root"

  if [[ $rc -eq 0 ]]; then
    echo "RESULT=ok" >>"$summary_file"
    echo "LOG_FILE=${log_file}" >>"$summary_file"
    echo "=== Job finished OK at $(date -Iseconds) ===" >>"$log_file"
    exit 0
  else
    echo "RESULT=failed" >>"$summary_file"
    echo "LOG_FILE=${log_file}" >>"$summary_file"
    echo "=== Job finished with errors at $(date -Iseconds) ===" >>"$log_file"
    exit 1
  fi
}

main "$@"
