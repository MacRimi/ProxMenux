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

load_language
initialize_cache

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
      # Also drop the matching runner log so retention is symmetric:
      # one archive ↔ one log, never an orphan log left behind.
      local stem suffix
      stem=$(basename "$f")
      suffix=".${ext}"
      stem="${stem%"$suffix"}"
      rm -f "$f" "${f}.proxmenux.json" "${LOG_DIR}/${stem}.log" || true
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

# Look up a borg destination's passphrase from the proxmenux state
# directory. The shell convention is `borg-pass-<name>.txt` next to
# `borg-targets.txt`; we resolve the `<name>` by scanning targets for
# the one whose repository matches the runtime BORG_REPO.
_sb_borg_resolve_password() {
  local repo="$1"
  local cfg="${HB_STATE_DIR:-/usr/local/share/proxmenux}/borg-targets.txt"
  [[ -f "$cfg" && -n "$repo" ]] || return 1
  local found_name="" line name target_repo
  while IFS='|' read -r name target_repo _; do
    [[ -z "$name" || -z "$target_repo" ]] && continue
    if [[ "$target_repo" == "$repo" ]]; then
      found_name="$name"
      break
    fi
  done < "$cfg"
  [[ -z "$found_name" ]] && return 1
  local pf="${HB_STATE_DIR:-/usr/local/share/proxmenux}/borg-pass-${found_name}.txt"
  [[ -r "$pf" ]] || return 1
  cat "$pf"
}

_sb_run_borg() {
  local stage_root="$1"
  local archive_name="$2"
  local borg_bin repo passphrase encrypt_mode

  borg_bin=$(hb_ensure_borg) || { echo "borg binary not available"; return 1; }
  repo="${BORG_REPO:-}"
  passphrase="${BORG_PASSPHRASE:-}"
  encrypt_mode="${BORG_ENCRYPT_MODE:-none}"
  if [[ -z "$repo" ]]; then
    echo "BORG_REPO not configured"
    return 1
  fi
  # Empty passphrase + encrypted mode → look it up from the saved
  # destination sidecar (the canonical place for borg credentials,
  # same pattern as PBS). Jobs created against a destination that
  # has its passphrase stored no longer need to duplicate it in the
  # job .env.
  if [[ -z "$passphrase" && "$encrypt_mode" != "none" ]]; then
    passphrase=$(_sb_borg_resolve_password "$repo" 2>/dev/null || true)
  fi
  if [[ "$encrypt_mode" != "none" && -z "$passphrase" ]]; then
    echo "BORG_PASSPHRASE is required when encryption is enabled (mode=$encrypt_mode)"
    echo "  → save the passphrase on the destination or set it in the job .env"
    return 1
  fi

  # Re-export the credentials so child processes (borg, ssh) inherit
  # them. `source <job.env>` only assigns to the current shell — without
  # an explicit re-export, child `borg` calls drop back to ssh defaults
  # and a remote repo silently auth-fails with no log trail.
  export BORG_PASSPHRASE="$passphrase"
  [[ -n "${BORG_RSH:-}" ]] && export BORG_RSH
  export BORG_RELOCATED_REPO_ACCESS_IS_OK=yes
  export BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=yes

  # Probe the repo first when working with a local path. Three cases
  # the operator hits regularly:
  #   - path is a valid borg repo + creds match  → `borg list` works
  #   - path is a valid borg repo + creds DON'T match  → explicit
  #     "credentials don't match" error (a wrong passphrase saved on
  #     the destination, typically)
  #   - path exists, has files, but is NOT a borg repo → explicit
  #     "path is not empty" error so the operator points at a fresh
  #     subdirectory instead of hitting borg's confusing "There is
  #     already something at <path>" message
  if [[ "$repo" != ssh://* && -d "$repo" ]]; then
    if ! "$borg_bin" list "$repo" </dev/null >/dev/null 2>&1; then
      local repo_config="$repo/config"
      if [[ -f "$repo_config" ]] && grep -qE '^\[repository\]' "$repo_config" 2>/dev/null; then
        echo "Borg repository at ${repo} exists but the configured credentials don't match it."
        echo "  → the saved passphrase or encryption mode for this destination is wrong."
        return 1
      fi
      # Not a repo. If the directory isn't empty, init will fail with
      # "There is already something at <path>". Detect and explain.
      if find "$repo" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null | grep -q .; then
        echo "Path ${repo} is not a borg repository AND is not empty."
        echo "  → Borg refuses to initialize a repo where there are other files."
        echo "  → Point the destination at a fresh empty subdirectory (e.g. ${repo}/borgbackup)."
        return 1
      fi
    fi
  fi

  # Send stderr to stdout so the caller's `>>$log_file 2>&1` captures
  # borg's diagnostics. The previous `>/dev/null 2>&1` silenced every
  # error and made "Job finished with errors" impossible to debug.
  if ! hb_borg_init_if_needed "$borg_bin" "$repo" "$encrypt_mode" 2>&1; then
    return 1
  fi

  # Include manifest.json (top-level) when present. Borg needs the
  # paths spelled out explicitly — without this, parse_manifest can't
  # find the schema'd manifest on a restored Borg archive.
  local -a _borg_paths=(rootfs metadata)
  [[ -f "$stage_root/manifest.json" ]] && _borg_paths+=(manifest.json)
  (cd "$stage_root" && "$borg_bin" create --stats \
    "${repo}::${archive_name}" "${_borg_paths[@]}") 2>&1 || return 1

  "$borg_bin" prune -v --list "$repo" \
    ${KEEP_LAST:+--keep-last "$KEEP_LAST"} \
    ${KEEP_HOURLY:+--keep-hourly "$KEEP_HOURLY"} \
    ${KEEP_DAILY:+--keep-daily "$KEEP_DAILY"} \
    ${KEEP_WEEKLY:+--keep-weekly "$KEEP_WEEKLY"} \
    ${KEEP_MONTHLY:+--keep-monthly "$KEEP_MONTHLY"} \
    ${KEEP_YEARLY:+--keep-yearly "$KEEP_YEARLY"} \
    2>&1 || true

  echo "BORG_ARCHIVE=${archive_name}"
  return 0
}

# Resolve a PBS password for an auto-discovered Datacenter storage by
# matching the repository string against /etc/pve/storage.cfg and
# returning the contents of /etc/pve/priv/storage/<name>.pw. Used as a
# fallback when the job .env carries an empty PBS_PASSWORD — happens
# when the operator picks a PVE-managed PBS in the wizard (the .pw
# file is the canonical credential location for those).
#
# Implemented in pure bash because the previous awk version relied on
# `match($0, regex, arr)` which is a gawk extension and silently no-ops
# on mawk / busybox awk — leaving the password unresolved and breaking
# every manual / scheduled PBS run against a PVE-managed storage.
_sb_pbs_resolve_password() {
  local repo="$1"
  local cfg=/etc/pve/storage.cfg
  [[ -f "$cfg" && -n "$repo" ]] || return 1

  local current_type="" current_name="" server="" datastore="" username=""
  local found_name=""

  _try_match() {
    [[ "$current_type" == "pbs" && -n "$current_name" && -n "$server" && -n "$datastore" ]] || return
    local u="${username:-root@pam}"
    local built="${u}@${server}:${datastore}"
    if [[ "$built" == "$repo" ]]; then
      found_name="$current_name"
    fi
  }

  local line key val
  while IFS= read -r line; do
    if [[ "$line" =~ ^([a-z]+):[[:space:]]+(.+)$ ]]; then
      _try_match
      [[ -n "$found_name" ]] && break
      current_type="${BASH_REMATCH[1]}"
      current_name="${BASH_REMATCH[2]}"
      server=""; datastore=""; username=""
      continue
    fi
    if [[ "$line" =~ ^[[:space:]]+([a-zA-Z_]+)[[:space:]]+(.+)$ ]]; then
      key="${BASH_REMATCH[1]}"
      val="${BASH_REMATCH[2]}"
      case "$key" in
        server)    server="$val" ;;
        datastore) datastore="$val" ;;
        username)  username="$val" ;;
      esac
    fi
  done < "$cfg"
  # Final block may not have triggered the start-of-next-block check.
  [[ -z "$found_name" ]] && _try_match
  unset -f _try_match 2>/dev/null

  [[ -z "$found_name" ]] && return 1
  local pw_file="/etc/pve/priv/storage/${found_name}.pw"
  [[ -r "$pw_file" ]] || return 1
  cat "$pw_file"
}

# Return the certificate fingerprint of the PBS storage entry whose
# `<user>@<server>:<datastore>` matches $1. Mirrors the walker in
# `_sb_pbs_resolve_password` but reads the `fingerprint <sha>` line
# instead. Needed because attached scheduled jobs are created without
# PBS_FINGERPRINT in their .env (the wizard inherits it from
# `/etc/pve/storage.cfg`), and without a fingerprint the client falls
# back to an interactive `(y/n)` prompt at connect time — which never
# gets an answer under systemd, hanging the whole job. Empty result
# is a valid outcome (PBS behind a CA-signed cert doesn't need one);
# a missing storage entry returns non-zero so the caller can log it.
_sb_pbs_resolve_fingerprint() {
  local repo="$1"
  local cfg=/etc/pve/storage.cfg
  [[ -f "$cfg" && -n "$repo" ]] || return 1

  local current_type="" current_name="" server="" datastore="" username=""
  local current_fp=""
  local found_fp="" found_any=0

  local line key val
  while IFS= read -r line; do
    if [[ "$line" =~ ^([a-z]+):[[:space:]]+(.+)$ ]]; then
      if [[ "$current_type" == "pbs" && -n "$current_name" && -n "$server" && -n "$datastore" ]]; then
        local u="${username:-root@pam}"
        local built="${u}@${server}:${datastore}"
        if [[ "$built" == "$repo" ]]; then
          found_fp="$current_fp"
          found_any=1
          break
        fi
      fi
      current_type="${BASH_REMATCH[1]}"
      current_name="${BASH_REMATCH[2]}"
      server=""; datastore=""; username=""; current_fp=""
      continue
    fi
    if [[ "$line" =~ ^[[:space:]]+([a-zA-Z_]+)[[:space:]]+(.+)$ ]]; then
      key="${BASH_REMATCH[1]}"
      val="${BASH_REMATCH[2]}"
      case "$key" in
        server)      server="$val" ;;
        datastore)   datastore="$val" ;;
        username)    username="$val" ;;
        fingerprint) current_fp="$val" ;;
      esac
    fi
  done < "$cfg"
  # Final block may not have triggered the start-of-next-block check.
  if (( ! found_any )); then
    if [[ "$current_type" == "pbs" && -n "$current_name" && -n "$server" && -n "$datastore" ]]; then
      local u="${username:-root@pam}"
      local built="${u}@${server}:${datastore}"
      if [[ "$built" == "$repo" ]]; then
        found_fp="$current_fp"
        found_any=1
      fi
    fi
  fi

  (( found_any )) || return 1
  # Empty fingerprint is a legit outcome for CA-signed PBS setups.
  printf '%s' "$found_fp"
}

_sb_run_pbs() {
  local stage_root="$1"
  local backup_id="$2"
  local epoch="$3"
  # Stage the WHOLE root (rootfs/ + metadata/ + manifest.json), not
  # just rootfs/. Mirrors backup_host.sh::_bk_pbs (the TUI flow) — and
  # parse_manifest.sh / run_restore.sh need metadata/ + manifest.json
  # to compose a meaningful restore plan. With only rootfs/ in the
  # pxar, View Contents reports "no manifest.json" forever.
  local -a cmd=(
    proxmox-backup-client backup
    "hostcfg.pxar:${stage_root}"
    --repository "$PBS_REPOSITORY"
    --backup-type host
    --backup-id "$backup_id"
    --backup-time "$epoch"
  )

  # If the .env was created against a Datacenter-managed PBS storage,
  # PBS_PASSWORD is intentionally empty there (the credential lives in
  # /etc/pve/priv/storage/<name>.pw). Resolve it now so the rest of
  # this function can run unchanged.
  if [[ -z "${PBS_PASSWORD:-}" && -n "${PBS_REPOSITORY:-}" ]]; then
    PBS_PASSWORD=$(_sb_pbs_resolve_password "$PBS_REPOSITORY" 2>/dev/null || true)
  fi

  # Same treatment for PBS_FINGERPRINT. Attached scheduled jobs are
  # created without one (the wizard delegates trust to PVE's storage
  # config), and running proxmox-backup-client with an empty fingerprint
  # against a self-signed PBS drops into an interactive `(y/n)` prompt —
  # which under systemd never gets an answer and hangs the timer.
  # Resolving on-demand from storage.cfg matches the runtime behavior
  # PVE itself has for its own vzdump jobs.
  if [[ -z "${PBS_FINGERPRINT:-}" && -n "${PBS_REPOSITORY:-}" ]]; then
    PBS_FINGERPRINT=$(_sb_pbs_resolve_fingerprint "$PBS_REPOSITORY" 2>/dev/null || true)
  fi

  # PBS_ENCRYPTION_PASSWORD: the passphrase that unlocks the keyfile
  # itself when it was created with `--kdf scrypt`. The Import flow
  # persists it at pbs-key.pass (chmod 600, root-only, same trust
  # boundary as the keyfile). If the file is absent the keyfile is
  # kdf=none and no passphrase is needed. `PBS_ENCRYPTION_PASSWORD`
  # from the .env still wins if the operator set it there for a
  # per-job override.
  if [[ -z "${PBS_ENCRYPTION_PASSWORD:-}" ]]; then
    local _pbs_pass_file="/usr/local/share/proxmenux/pbs-key.pass"
    if [[ -r "$_pbs_pass_file" ]]; then
      PBS_ENCRYPTION_PASSWORD=$(cat "$_pbs_pass_file" 2>/dev/null || true)
    fi
  fi

  [[ -z "${PBS_REPOSITORY:-}" || -z "${PBS_PASSWORD:-}" ]] && return 1
  if [[ -n "${PBS_KEYFILE:-}" ]]; then
    cmd+=(--keyfile "$PBS_KEYFILE")
  fi

  # `</dev/null` on every proxmox-backup-client invocation defends
  # against any interactive prompt (fingerprint mismatch, keyfile
  # passphrase, ...) that would otherwise block on stdin under systemd
  # and freeze the timer for its entire timeout window. With the
  # fingerprint resolved above the prompt should never fire, but if
  # storage.cfg is out of sync (PBS cert rotated, entry renamed) we
  # want a fast, clear failure — not a silent hang.
  env PBS_PASSWORD="$PBS_PASSWORD" \
      PBS_ENCRYPTION_PASSWORD="${PBS_ENCRYPTION_PASSWORD:-}" \
      PBS_FINGERPRINT="${PBS_FINGERPRINT:-}" \
    "${cmd[@]}" </dev/null 2>&1 || return 1

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
      </dev/null 2>&1 || true

  # Upload the keyfile recovery blob alongside the main backup so the
  # operator can rebuild the keyfile on a fresh host. Only fires when:
  #   - this backup was encrypted (PBS_KEYFILE set), AND
  #   - the operator configured a recovery passphrase
  #     (pbs-key.recovery.enc exists, created by the UI's
  #     /pbs-recovery/setup endpoint or shell hb_pbs_setup_recovery).
  # The blob is already passphrase-encrypted by openssl, so we do NOT
  # pass --keyfile here: PBS stores it as a plain blob retrievable
  # without the keyfile, which is the whole point of the escrow.
  local recovery_enc="/usr/local/share/proxmenux/pbs-key.recovery.enc"
  if [[ -n "${PBS_KEYFILE:-}" && -f "$recovery_enc" ]]; then
    local keyrec_id
    keyrec_id="hostcfg-$(hostname)-keyrecovery"
    env PBS_PASSWORD="$PBS_PASSWORD" \
        PBS_FINGERPRINT="${PBS_FINGERPRINT:-}" \
      proxmox-backup-client backup \
        "keyrecovery.conf:${recovery_enc}" \
        --repository "$PBS_REPOSITORY" \
        --backup-type host \
        --backup-id "$keyrec_id" \
        --backup-time "$epoch" \
        </dev/null 2>&1 || true

    # Prune the paired keyrecovery group with the SAME retention
    # values as the main backup. Without this the keyrecovery snapshots
    # accumulate one per run while the main group is pruned to keep-*,
    # cluttering the datastore over time. Any single keyrecovery snapshot
    # is sufficient to reconstruct the keyfile — but matching retention
    # keeps the two groups aligned in count and makes cleanup obvious.
    env PBS_PASSWORD="$PBS_PASSWORD" \
        PBS_FINGERPRINT="${PBS_FINGERPRINT:-}" \
      proxmox-backup-client prune "host/${keyrec_id}" --repository "$PBS_REPOSITORY" \
        ${KEEP_LAST:+--keep-last "$KEEP_LAST"} \
        ${KEEP_HOURLY:+--keep-hourly "$KEEP_HOURLY"} \
        ${KEEP_DAILY:+--keep-daily "$KEEP_DAILY"} \
        ${KEEP_WEEKLY:+--keep-weekly "$KEEP_WEEKLY"} \
        ${KEEP_MONTHLY:+--keep-monthly "$KEEP_MONTHLY"} \
        ${KEEP_YEARLY:+--keep-yearly "$KEEP_YEARLY"} \
        </dev/null 2>&1 || true
  fi

  echo "PBS_SNAPSHOT=host/${backup_id}/${epoch}"
  return 0
}

# For attached jobs, re-read the parent vzdump job's prune-backups
# live from /etc/pve/jobs.cfg every run and rewrite KEEP_*. The .env
# only carries a snapshot of the parent's retention at creation time,
# so if the parent later gained (or changed) prune-backups the child
# would silently accumulate. Attached mode is authoritative from the
# parent by design — that's the whole point of "attached".
_sb_hydrate_attached_retention() {
  local parent="${PVE_PARENT_JOB:-}"
  [[ -z "$parent" ]] && return 0
  local cfg=/etc/pve/jobs.cfg
  [[ -f "$cfg" ]] || return 0

  local prune
  prune=$(awk -v pid="$parent" '
    /^vzdump:[[:space:]]/ { in_block=($2==pid); next }
    /^[a-z]+:/ { in_block=0; next }
    in_block && /^[[:space:]]+prune-backups[[:space:]]/ {
      sub(/^[[:space:]]+prune-backups[[:space:]]+/, "");
      print; exit
    }
  ' "$cfg")

  # Clear any KEEP_* the .env may have — those are the create-time
  # snapshot and are now stale. If the parent later removed prune-
  # backups altogether, this correctly stops pruning the child too.
  unset KEEP_LAST KEEP_HOURLY KEEP_DAILY KEEP_WEEKLY KEEP_MONTHLY KEEP_YEARLY

  [[ -z "$prune" ]] && return 0

  local kv
  while IFS= read -r kv; do
    [[ -n "$kv" ]] && export "${kv?}"
  done < <(hb_pve_prune_to_keep_env "$prune")
}

main() {
  local job_id="${1:-}"
  [[ -z "$job_id" ]] && { echo "Usage: $0 <job_id>" >&2; exit 1; }

  local job_file="${JOBS_DIR}/${job_id}.env"
  [[ -f "$job_file" ]] || { echo "Job not found: $job_id" >&2; exit 1; }

  # shellcheck source=/dev/null
  source "$job_file"

  # Attached jobs: re-read retention from the PVE parent live (see
  # _sb_hydrate_attached_retention above for the why). Standalone
  # jobs keep whatever KEEP_* the .env has.
  _sb_hydrate_attached_retention

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

  # Fire the lifecycle "start" event. Per-channel/per-event toggles in
  # Settings decide whether the user actually receives it
  # (host_backup_start ships with default_enabled=False).
  local _hb_dest=""
  case "${BACKEND:-}" in
    local) _hb_dest="${LOCAL_DEST_DIR:-/var/lib/vz/dump}" ;;
    borg)  _hb_dest="${BORG_REPO:-}" ;;
    pbs)   _hb_dest="${PBS_REPOSITORY:-}" ;;
  esac
  export HB_NOTIFY_BACKEND="${BACKEND:-}"
  export HB_NOTIFY_DESTINATION="$_hb_dest"
  export HB_NOTIFY_PROFILE_MODE="${PROFILE_MODE:-default}"
  export HB_NOTIFY_LOG_FILE="$log_file"
  hb_notify_lifecycle "start"

  local -a paths=()
  if [[ "${PROFILE_MODE:-default}" == "custom" && -f "${JOBS_DIR}/${job_id}.paths" ]]; then
    mapfile -t paths < "${JOBS_DIR}/${job_id}.paths"
  else
    # Default profile = base paths + operator-saved extras (the
    # TUI flow does the same — see hb_resolve_paths_mode in
    # lib_host_backup_common.sh). Without the extras line, the
    # `backup-extra-paths.txt` set in Settings was silently
    # ignored for scheduled / manual runs from the Monitor.
    mapfile -t paths < <(hb_default_profile_paths; hb_load_extra_paths)
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
      (( TTY )) && { echo; msg_info "$(translate "Sending backup to Borg repository...")"; stop_spinner; }
      echo "Sending backup to Borg repository ${BORG_REPO:-} ..." >>"$log_file"
      _sb_run_borg "$stage_root" "${job_id}-${ts}" >>"$log_file" 2>&1
      rc=$?
      archive_path="${BORG_REPO:-}::${job_id}-${ts}"
      ;;
    pbs)
      (( TTY )) && { echo; msg_info "$(translate "Sending backup to PBS...")"; stop_spinner; }
      echo "Sending backup to PBS ${PBS_REPOSITORY:-} (id=${PBS_BACKUP_ID:-hostcfg-$(hostname)}) ..." >>"$log_file"
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

  # Single source of truth for archive_size (was previously computed
  # only inside the TTY block, which left the notification body with
  # '-' for headless scheduled runs). Local backends know the actual
  # output file; PBS / Borg backends manage their own dedupe storage
  # so we leave '-' meaning "see repository for usage".
  local archive_size="-"
  if [[ "${BACKEND:-}" == "local" && -n "$archive_path" && -f "$archive_path" ]]; then
    archive_size=$(hb_file_size "$archive_path" 2>/dev/null || echo '-')
  fi
  local pretty_duration
  pretty_duration=$(hb_human_elapsed "$elapsed" 2>/dev/null || echo "${elapsed}s")

  if [[ $rc -eq 0 ]]; then
    echo "RESULT=ok" >>"$summary_file"
    echo "LOG_FILE=${log_file}" >>"$summary_file"
    echo "=== Job finished OK at $(date -Iseconds) ===" >>"$log_file"
    export HB_NOTIFY_DATA_SIZE="$staged_size"
    export HB_NOTIFY_ARCHIVE_SIZE="$archive_size"
    export HB_NOTIFY_DURATION="$pretty_duration"
    hb_notify_lifecycle "complete"
    if (( TTY )); then
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
    # Build a one-line reason from the last error-ish line in the log
    # so the notification body has something actionable rather than a
    # generic "Reason: unknown". Falls back to the literal exit code.
    local _hb_reason=""
    _hb_reason=$(grep -iE 'error|fail|fatal|abort' "$log_file" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//')
    [[ -z "$_hb_reason" ]] && _hb_reason="Runner exited with status ${rc}"
    export HB_NOTIFY_DATA_SIZE="${staged_size:-}"
    export HB_NOTIFY_ARCHIVE_SIZE="$archive_size"
    export HB_NOTIFY_DURATION="$pretty_duration"
    export HB_NOTIFY_REASON="$_hb_reason"
    hb_notify_lifecycle "fail"
    (( TTY )) && msg_error "$(translate "Backup failed. See log:") $log_file"
    exit 1
  fi
}

main "$@"
