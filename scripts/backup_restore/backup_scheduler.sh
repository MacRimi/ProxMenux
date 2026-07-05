#!/bin/bash
# ==========================================================
# ProxMenux - Scheduled Backup Jobs
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
  echo "ERROR: utils.sh not found." >&2
  exit 1
fi

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

JOBS_DIR="/var/lib/proxmenux/backup-jobs"
LOG_DIR="/var/log/proxmenux/backup-jobs"
mkdir -p "$JOBS_DIR" "$LOG_DIR" >/dev/null 2>&1 || true

_job_file() { echo "${JOBS_DIR}/$1.env"; }
_job_paths_file() { echo "${JOBS_DIR}/$1.paths"; }
_service_file() { echo "/etc/systemd/system/proxmenux-backup-$1.service"; }
_timer_file() { echo "/etc/systemd/system/proxmenux-backup-$1.timer"; }

_normalize_uint() {
  local v="${1:-0}"
  [[ "$v" =~ ^[0-9]+$ ]] || v=0
  echo "$v"
}

_write_job_env() {
  local file="$1"
  shift
  {
    echo "# ProxMenux scheduled backup job"
    local kv key val
    for kv in "$@"; do
      key="${kv%%=*}"
      val="${kv#*=}"
      printf '%s=%q\n' "$key" "$val"
    done
  } > "$file"
}

_list_jobs() {
  local f
  for f in "$JOBS_DIR"/*.env; do
    [[ -f "$f" ]] || continue
    basename "$f" .env
  done | sort
}

# Same as _list_jobs but skips one-shot manual runs (Sprint B).
# Manual entries are `.env` files with `MANUAL_RUN=1` — they're
# closed executions, not configured tasks. Used by "Show jobs"
# and "Run a job now" so those views only surface real backup
# tasks; Delete / Toggle keep using _list_jobs so the operator
# can still clean up leftover manual entries from those menus.
_list_scheduled_jobs() {
  local f id
  for f in "$JOBS_DIR"/*.env; do
    [[ -f "$f" ]] || continue
    grep -q '^MANUAL_RUN=1$' "$f" 2>/dev/null && continue
    id=$(basename "$f" .env)
    printf '%s\n' "$id"
  done | sort
}

# Returns 0 if the job is attached to a PVE vzdump storage (no systemd
# timer — the trigger comes from the vzdump hook, matched by PVE_STORAGE
# against $STOREID set by PVE for every backup phase).
_job_is_attached() {
  local id="$1" f
  f=$(_job_file "$id")
  [[ -f "$f" ]] || return 1
  grep -q "^PVE_STORAGE=" "$f"
}

# Reads a key=val pair from the job .env file (handles `printf %q`
# quoting that _write_job_env produces).
_job_env_get() {
  local id="$1" key="$2" f raw
  f=$(_job_file "$id")
  [[ -f "$f" ]] || return 1
  raw=$(grep -E "^${key}=" "$f" | head -1 | cut -d'=' -f2-)
  eval "echo $raw" 2>/dev/null || echo "$raw"
}

_show_job_status() {
  local id="$1"
  if _job_is_attached "$id"; then
    local storage
    storage=$(_job_env_get "$id" "PVE_STORAGE")
    local enabled
    enabled=$(_job_env_get "$id" "ENABLED")
    [[ "$enabled" == "0" ]] && { echo "attached(disabled) → storage:$storage"; return; }
    echo "attached → storage:$storage"
    return
  fi
  local timer_state="disabled" service_state
  systemctl is-enabled --quiet "proxmenux-backup-${id}.timer" >/dev/null 2>&1 && timer_state="enabled"
  service_state=$(systemctl is-active "proxmenux-backup-${id}.service" 2>/dev/null || echo "inactive")
  if [[ "$service_state" == "active" ]]; then
    echo "running"
  elif [[ "$timer_state" == "enabled" ]]; then
    echo "enabled"
  else
    echo "disabled"
  fi
}

_write_job_units() {
  local id="$1"
  local on_calendar="$2"
  local runner="$LOCAL_SCRIPTS/backup_restore/run_scheduled_backup.sh"
  [[ ! -f "$runner" ]] && runner="$SCRIPT_DIR/run_scheduled_backup.sh"

  cat > "$(_service_file "$id")" <<EOF
[Unit]
Description=ProxMenux Scheduled Backup Job (${id})
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=${runner} ${id}
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF

  cat > "$(_timer_file "$id")" <<EOF
[Unit]
Description=ProxMenux Scheduled Backup Timer (${id})

[Timer]
OnCalendar=${on_calendar}
Persistent=true
RandomizedDelaySec=120
Unit=proxmenux-backup-${id}.service

[Install]
WantedBy=timers.target
EOF

  systemctl daemon-reload >/dev/null 2>&1 || true
}

_prompt_retention() {
  local __out_var="$1"
  local last hourly daily weekly monthly yearly
  last=$(dialog --backtitle "ProxMenux" --title "$(translate "Retention")" \
    --inputbox "$(translate "keep-last (0 disables)")" 9 60 "7" 3>&1 1>&2 2>&3) || return 1
  hourly=$(dialog --backtitle "ProxMenux" --title "$(translate "Retention")" \
    --inputbox "$(translate "keep-hourly (0 disables)")" 9 60 "0" 3>&1 1>&2 2>&3) || return 1
  daily=$(dialog --backtitle "ProxMenux" --title "$(translate "Retention")" \
    --inputbox "$(translate "keep-daily (0 disables)")" 9 60 "7" 3>&1 1>&2 2>&3) || return 1
  weekly=$(dialog --backtitle "ProxMenux" --title "$(translate "Retention")" \
    --inputbox "$(translate "keep-weekly (0 disables)")" 9 60 "4" 3>&1 1>&2 2>&3) || return 1
  monthly=$(dialog --backtitle "ProxMenux" --title "$(translate "Retention")" \
    --inputbox "$(translate "keep-monthly (0 disables)")" 9 60 "3" 3>&1 1>&2 2>&3) || return 1
  yearly=$(dialog --backtitle "ProxMenux" --title "$(translate "Retention")" \
    --inputbox "$(translate "keep-yearly (0 disables)")" 9 60 "0" 3>&1 1>&2 2>&3) || return 1

  last=$(_normalize_uint "$last")
  hourly=$(_normalize_uint "$hourly")
  daily=$(_normalize_uint "$daily")
  weekly=$(_normalize_uint "$weekly")
  monthly=$(_normalize_uint "$monthly")
  yearly=$(_normalize_uint "$yearly")

  local -n out="$__out_var"
  out=(
    "KEEP_LAST=$last"
    "KEEP_HOURLY=$hourly"
    "KEEP_DAILY=$daily"
    "KEEP_WEEKLY=$weekly"
    "KEEP_MONTHLY=$monthly"
    "KEEP_YEARLY=$yearly"
  )
}

# Builds a "host backup attached to a PVE vzdump job" — no systemd
# timer is created; the trigger is the vzdump hook that fires when
# the parent job runs. Schedule and retention come from the parent.
_create_job_attached() {
  local id="$1"
  local backend="$2"

  local -a jobs=()
  mapfile -t jobs < <(hb_pve_list_vzdump_jobs_for_backend "$backend")
  if (( ${#jobs[@]} == 0 )); then
    dialog --backtitle "ProxMenux" --title "$(translate "No compatible PVE jobs")" \
      --msgbox "$(translate "No PVE vzdump job uses a") $backend $(translate "storage.")" 8 70
    return 1
  fi

  local -a menu=()
  local i=1 row pve_id pve_storage _ pve_schedule _pve_prune pve_enabled
  for row in "${jobs[@]}"; do
    IFS=$'\t' read -r pve_id pve_storage _ pve_schedule _pve_prune pve_enabled <<<"$row"
    local label="${pve_id}  ·  ${pve_storage}  ·  ${pve_schedule}"
    [[ "$pve_enabled" == "0" ]] && label+="  $(translate "(disabled)")"
    menu+=("$i" "$label")
    ((i++))
  done
  local sel
  sel=$(dialog --backtitle "ProxMenux" --title "$(translate "Pick PVE vzdump job")" \
    --menu "\n$(translate "Select the parent job to attach to:")" \
    "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${menu[@]}" \
    3>&1 1>&2 2>&3) || return 1

  local pve_prune
  IFS=$'\t' read -r pve_id pve_storage _ pve_schedule pve_prune pve_enabled <<<"${jobs[$((sel-1))]}"

  local profile_mode
  profile_mode=$(dialog --backtitle "ProxMenux" --title "$(translate "Profile")" \
    --menu "\n$(translate "Select backup profile:")" 12 68 4 \
    "default" "Default critical paths" \
    "custom"  "Custom selected paths" \
    3>&1 1>&2 2>&3) || return 1

  local -a paths=()
  hb_select_profile_paths "$profile_mode" paths || return 1

  local -a lines=(
    "JOB_ID=$id"
    "BACKEND=$backend"
    "PVE_PARENT_JOB=$pve_id"
    "PVE_STORAGE=$pve_storage"
    "PROFILE_MODE=$profile_mode"
    "ENABLED=1"
  )

  # Inherit retention from the parent job (one KEEP_* per prune-backups key).
  local kv
  while IFS= read -r kv; do
    [[ -n "$kv" ]] && lines+=("$kv")
  done < <(hb_pve_prune_to_keep_env "$pve_prune")

  case "$backend" in
    pbs)
      hb_select_pbs_repository || return 1
      local bid
      bid="hostcfg-$(hostname)"
      bid=$(dialog --backtitle "ProxMenux" --title "PBS" \
        --inputbox "$(translate "Backup ID for this job:")" \
        "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "$bid" 3>&1 1>&2 2>&3) || return 1
      bid=$(echo "$bid" | tr -cs '[:alnum:]_-' '-' | sed 's/-*$//')
      lines+=(
        "PBS_REPOSITORY=${HB_PBS_REPOSITORY}"
        "PBS_PASSWORD=${HB_PBS_SECRET}"
        "PBS_BACKUP_ID=${bid}"
      )
      ;;
    local)
      # Derive the dump directory from the storage entry. PVE stores
      # vzdump archives under <path>/dump/ when the storage is dir/nfs.
      local dest_dir="/var/lib/vz/dump"
      local sp
      sp=$(awk -v sid="$pve_storage" '
          /^[a-z]+:[[:space:]]/ { in_block=($2==sid) }
          in_block && /^[[:space:]]+path[[:space:]]/ { sub(/^[[:space:]]+path[[:space:]]+/,""); print; exit }
      ' /etc/pve/storage.cfg) || true
      [[ -n "$sp" ]] && dest_dir="${sp%/}/dump"
      lines+=("LOCAL_DEST_DIR=$dest_dir" "LOCAL_ARCHIVE_EXT=tar.zst")
      ;;
  esac

  _write_job_env "$(_job_file "$id")" "${lines[@]}"
  : > "$(_job_paths_file "$id")"
  local p
  for p in "${paths[@]}"; do
    echo "$p" >> "$(_job_paths_file "$id")"
  done

  # No unit / timer — the trigger is the vzdump hook fired by the parent PVE job.
  hb_install_vzdump_hook >/dev/null 2>&1 || \
    msg_warn "$(translate "Could not install vzdump hook in /etc/vzdump.conf")"

  show_proxmenux_logo
  msg_title "$(translate "Host backup attached to PVE job")"
  echo
  echo -e "${TAB}${BGN}$(translate "Job ID:")${CL} ${BL}${id}${CL}"
  echo -e "${TAB}${BGN}$(translate "Attached to PVE job:")${CL} ${BL}${pve_id}${CL}"
  echo -e "${TAB}${BGN}$(translate "Inherited schedule:")${CL} ${BL}${pve_schedule}${CL}"
  echo -e "${TAB}${BGN}$(translate "Inherited retention:")${CL} ${BL}${pve_prune}${CL}"
  echo -e "${TAB}${BGN}$(translate "Backend:")${CL} ${BL}${backend} → ${pve_storage}${CL}"
  echo
  msg_success "$(translate "Press Enter to continue...")"
  read -r
  return 0
}

_create_job() {
  local id backend on_calendar profile_mode
  id=$(dialog --backtitle "ProxMenux" --title "$(translate "New backup job")" \
    --inputbox "$(translate "Job ID (letters, numbers, - _)")" 9 68 "my-host-backup" 3>&1 1>&2 2>&3) || return 1
  [[ -z "$id" ]] && return 1
  id=$(echo "$id" | tr -cs '[:alnum:]_-' '-' | sed 's/^-*//; s/-*$//')
  [[ -z "$id" ]] && return 1
  [[ -f "$(_job_file "$id")" ]] && {
    dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
      --msgbox "$(translate "A job with this ID already exists.")" 8 62
    return 1
  }

  backend=$(dialog --backtitle "ProxMenux" --title "$(translate "Backend")" \
    --menu "\n$(translate "Select backup backend:")" 14 70 6 \
    "local" "Local archive" \
    "borg"  "Borg repository" \
    "pbs"   "Proxmox Backup Server" \
    3>&1 1>&2 2>&3) || return 1

  # Offer attach-mode for backends that map to a PVE storage. The
  # vzdump scheduler in PVE already handles trigger + retention for
  # VM/CT backups; the host backup can ride alongside it via a hook.
  # Borg has no PVE-side scheduler, so attach makes no sense there.
  if [[ "$backend" == "pbs" || "$backend" == "local" ]]; then
    local creation_mode
    creation_mode=$(dialog --backtitle "ProxMenux" --title "$(translate "How to schedule")" \
      --menu "\n$(translate "Choose how this host backup will be triggered:")" 14 78 4 \
      "new"    "$(translate "New scheduled job (own timer + retention)")" \
      "attach" "$(translate "Attach to an existing PVE vzdump job (inherit schedule + retention)")" \
      3>&1 1>&2 2>&3) || return 1
    if [[ "$creation_mode" == "attach" ]]; then
      # If no compatible PVE job exists yet, show a helpful pointer
      # instead of silently dropping back to "new" mode.
      if [[ -z "$(hb_pve_list_vzdump_jobs_for_backend "$backend" 2>/dev/null | head -1)" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No compatible PVE jobs")" \
          --msgbox "$(translate "No PVE vzdump job uses a") $backend $(translate "storage yet.")"$'\n\n'"$(translate "Create one first in Datacenter → Backup, then return here to attach.")" \
          12 78
        return 1
      fi
      _create_job_attached "$id" "$backend"
      return $?
    fi
  fi

  on_calendar=$(dialog --backtitle "ProxMenux" --title "$(translate "Schedule")" \
    --inputbox "$(translate "systemd OnCalendar expression")"$'\n'"$(translate "Example: daily or Mon..Fri 03:00")" \
    11 72 "daily" 3>&1 1>&2 2>&3) || return 1
  [[ -z "$on_calendar" ]] && return 1

  profile_mode=$(dialog --backtitle "ProxMenux" --title "$(translate "Profile")" \
    --menu "\n$(translate "Select backup profile:")" 12 68 4 \
    "default" "Default critical paths" \
    "custom"  "Custom selected paths" \
    3>&1 1>&2 2>&3) || return 1

  local -a paths=()
  hb_select_profile_paths "$profile_mode" paths || return 1

  local -a retention=()
  _prompt_retention retention || return 1

  local -a lines=(
    "JOB_ID=$id"
    "BACKEND=$backend"
    "ON_CALENDAR=$on_calendar"
    "PROFILE_MODE=$profile_mode"
    "ENABLED=1"
  )
  lines+=("${retention[@]}")

  case "$backend" in
    local)
      local dest_dir ext
      dest_dir=$(hb_select_local_target) || return 1
      ext=$(dialog --backtitle "ProxMenux" --title "$(translate "Archive format")" \
        --menu "\n$(translate "Select local archive format:")" 12 62 4 \
        "tar.zst" "tar + zstd (preferred)" \
        "tar.gz"  "tar + gzip" \
        3>&1 1>&2 2>&3) || return 1
      lines+=("LOCAL_DEST_DIR=$dest_dir" "LOCAL_ARCHIVE_EXT=$ext")
      ;;
    borg)
      local repo passphrase
      hb_select_borg_repo repo || return 1
      hb_prepare_borg_passphrase || return 1
      passphrase="${BORG_PASSPHRASE:-}"
      lines+=(
        "BORG_REPO=$repo"
        "BORG_PASSPHRASE=$passphrase"
        "BORG_ENCRYPT_MODE=${BORG_ENCRYPT_MODE:-none}"
      )
      ;;
    pbs)
      hb_select_pbs_repository || return 1
      # Propagate the operator cancel from the encryption dialog so the
      # wizard drops back to the previous step instead of saving a job
      # spec with a half-configured encryption block.
      hb_ask_pbs_encryption || return 1
      local bid
      bid="hostcfg-$(hostname)"
      bid=$(dialog --backtitle "ProxMenux" --title "PBS" \
        --inputbox "$(translate "Backup ID for this job:")" \
        "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "$bid" 3>&1 1>&2 2>&3) || return 1
      bid=$(echo "$bid" | tr -cs '[:alnum:]_-' '-' | sed 's/-*$//')
      lines+=(
        "PBS_REPOSITORY=${HB_PBS_REPOSITORY}"
        "PBS_PASSWORD=${HB_PBS_SECRET}"
        "PBS_BACKUP_ID=${bid}"
        "PBS_KEYFILE=${HB_PBS_KEYFILE:-}"
        "PBS_ENCRYPTION_PASSWORD=${HB_PBS_ENC_PASS:-}"
      )
      ;;
  esac

  _write_job_env "$(_job_file "$id")" "${lines[@]}"

  : > "$(_job_paths_file "$id")"
  local p
  for p in "${paths[@]}"; do
    echo "$p" >> "$(_job_paths_file "$id")"
  done

  _write_job_units "$id" "$on_calendar"
  systemctl enable --now "proxmenux-backup-${id}.timer" >/dev/null 2>&1 || true

  show_proxmenux_logo
  msg_title "$(translate "Scheduled backup job created")"
  echo -e ""
  echo -e "${TAB}${BGN}$(translate "Job ID:")${CL} ${BL}${id}${CL}"
  echo -e "${TAB}${BGN}$(translate "Backend:")${CL} ${BL}${backend}${CL}"
  echo -e "${TAB}${BGN}$(translate "Schedule:")${CL} ${BL}${on_calendar}${CL}"
  echo -e "${TAB}${BGN}$(translate "Status:")${CL} ${BL}$(_show_job_status "$id")${CL}"
  echo -e ""
  msg_success "$(translate "Press Enter to continue...")"
  read -r
  return 0
}

_pick_job() {
  local title="$1"
  local __out_var="$2"
  # Optional scope: "all" (default) surfaces every .env in JOBS_DIR
  # including one-shot manual runs; "scheduled" filters those out so
  # Run-now only shows real configured tasks. Delete / Toggle keep
  # the default so the operator can still clean up manual leftovers.
  local scope="${3:-all}"

  local -a ids=()
  if [[ "$scope" == "scheduled" ]]; then
    mapfile -t ids < <(_list_scheduled_jobs)
  else
    mapfile -t ids < <(_list_jobs)
  fi
  if [[ ${#ids[@]} -eq 0 ]]; then
    dialog --backtitle "ProxMenux" --title "$(translate "No jobs")" \
      --msgbox "$(translate "No scheduled backup jobs found.")" 8 62
    return 1
  fi

  # Build the menu rows. The loop variable is INTENTIONALLY named
  # `_iter_id` (not `id`) — every caller passes "id" as $__out_var so
  # the nameref below should point at the caller's local. A loop
  # variable named `id` here would shadow it, and the nameref would
  # silently write into _pick_job's own scope instead, leaving the
  # caller with an empty string. That manifested as:
  #   ✓ Job timer enabled: (empty)
  #   run_scheduled_backup.sh: Usage: ... <job_id>
  # Both reported on 2026-06-07.
  local -a menu=()
  local i=1 _iter_id
  for _iter_id in "${ids[@]}"; do
    menu+=("$i" "$_iter_id [$(_show_job_status "$_iter_id")]")
    ((i++))
  done
  local sel
  sel=$(dialog --backtitle "ProxMenux" --title "$title" \
    --menu "\n$(translate "Select a job:")" "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
    "${menu[@]}" 3>&1 1>&2 2>&3) || return 1

  local picked="${ids[$((sel-1))]}"
  local -n out="$__out_var"
  out="$picked"
  return 0
}

# Common screen reset for any post-dialog action result. The
# `dialog` calls in this script leave their box drawn on screen
# even after the user has confirmed; without this reset, the
# subsequent msg_ok / msg_warn / "Press Enter" output renders
# in the bottom-left corner UNDER the leftover dialog box.
# show_proxmenux_logo already runs `clear` internally, so we
# don't add another one — the convention used across proxmenux
# (create_vm_menu.sh, config_menu.sh, menu_post_install.sh) is:
#     show_proxmenux_logo → msg_title → result message
# Reported 2026-06-07 when the operator hit "Run job now" and
# saw "Job executed successfully" floating over the picker.
_render_action_screen() {
  show_proxmenux_logo
  msg_title "$1"
}

_job_run_now() {
  # "scheduled" scope — one-shot manual runs are closed executions,
  # not tasks to re-fire. Filtering them out of this picker prevents
  # accidental re-runs of an operator's past manual backups.
  local id=""
  _pick_job "$(translate "Run job now")" id scheduled || return 1
  # Defensive guard against a future regression of the nameref-shadowing
  # bug that left $id empty here on 2026-06-07. Without this, the runner
  # gets called with no argument and emits "Usage: ... <job_id>".
  if [[ -z "$id" ]]; then
    _render_action_screen "$(translate "Run job now")"
    msg_error "$(translate "Job selection returned empty id — aborting.")"
    msg_success "$(translate "Press Enter to continue...")"
    read -r
    return 1
  fi

  local runner="$LOCAL_SCRIPTS/backup_restore/run_scheduled_backup.sh"
  [[ ! -f "$runner" ]] && runner="$SCRIPT_DIR/run_scheduled_backup.sh"

  # Foreground execution — the runner detects TTY and prints a
  # colored progress layout (mirrors _bk_local in backup_host.sh).
  # Plain-text log file is still written for audit / scheduler runs.
  _render_action_screen "$(translate "Running backup job:") $id"
  echo
  "$runner" "$id"
  local runner_exit
  runner_exit=$?

  echo
  msg_success "$(translate "Press Enter to continue...")"
  read -r
  return $runner_exit
}

_job_toggle() {
  # "scheduled" scope — one-shot manual runs carry ENABLED=0 by
  # definition and can't be re-fired from a timer, so offering them
  # in this picker was noise. Delete keeps the "all" scope so the
  # operator can still clean up manual entries from that menu.
  local id=""
  _pick_job "$(translate "Enable/Disable job")" id scheduled || return 1
  if [[ -z "$id" ]]; then
    _render_action_screen "$(translate "Enable/Disable job")"
    msg_error "$(translate "Job selection returned empty id — aborting.")"
    msg_success "$(translate "Press Enter to continue...")"
    read -r
    return 1
  fi

  local action_label
  if _job_is_attached "$id"; then
    # Attached jobs have no systemd timer — flip the ENABLED flag in
    # the .env so the vzdump hook respects it on the next parent run.
    local f current
    f=$(_job_file "$id")
    current=$(_job_env_get "$id" "ENABLED")
    if [[ "$current" == "0" ]]; then
      sed -i 's/^ENABLED=.*/ENABLED=1/' "$f"
      action_label="enabled"
    else
      sed -i 's/^ENABLED=.*/ENABLED=0/' "$f"
      action_label="disabled"
    fi
  else
    if systemctl is-enabled --quiet "proxmenux-backup-${id}.timer" >/dev/null 2>&1; then
      systemctl disable --now "proxmenux-backup-${id}.timer" >/dev/null 2>&1 || true
      action_label="disabled"
    else
      systemctl enable --now "proxmenux-backup-${id}.timer" >/dev/null 2>&1 || true
      action_label="enabled"
    fi
  fi

  _render_action_screen "$(translate "Enable/Disable job")"
  if [[ "$action_label" == "disabled" ]]; then
    msg_warn "$(translate "Job disabled:") $id"
  else
    msg_ok "$(translate "Job enabled:") $id"
  fi
  msg_success "$(translate "Press Enter to continue...")"
  read -r
}

_job_delete() {
  local id=""
  _pick_job "$(translate "Delete job")" id || return 1
  # An empty id here would build malformed unit paths like
  # /etc/systemd/system/proxmenux-backup-.timer, and the subsequent
  # rm -f would silently no-op against bogus paths — making it LOOK
  # like a successful delete while the real job stays untouched.
  if [[ -z "$id" ]]; then
    _render_action_screen "$(translate "Delete job")"
    msg_error "$(translate "Job selection returned empty id — aborting.")"
    msg_success "$(translate "Press Enter to continue...")"
    read -r
    return 1
  fi
  local confirm_body
  confirm_body="$(translate "Delete scheduled backup job?")"$'\n\n'"ID: ${id}"
  if _job_is_attached "$id"; then
    local storage
    storage=$(_job_env_get "$id" "PVE_STORAGE")
    confirm_body+=$'\n'"$(translate "Type: attached to PVE storage") ${storage}"
    confirm_body+=$'\n\n'"$(translate "Only the host backup hook is removed — PVE vzdump jobs targeting this storage stay intact.")"
  fi
  if ! whiptail --title "$(translate "Confirm delete")" \
    --yesno "$confirm_body" 14 70; then
    return 1
  fi
  systemctl disable --now "proxmenux-backup-${id}.timer" >/dev/null 2>&1 || true
  rm -f "$(_service_file "$id")" "$(_timer_file "$id")" "$(_job_file "$id")" "$(_job_paths_file "$id")"
  systemctl daemon-reload >/dev/null 2>&1 || true

  _render_action_screen "$(translate "Delete job")"
  msg_ok "$(translate "Job deleted:") $id"
  msg_success "$(translate "Press Enter to continue...")"
  read -r
}

_show_jobs() {
  local tmp
  tmp=$(mktemp) || return

  # Per-job block: header line with status badge + 3 detail lines
  # summarising the backend destination and the last run — same
  # information the Monitor UI shows on the Backups tab, condensed
  # for the shell dialog.
  local -a job_ids=()
  local id
  while IFS= read -r id; do
    [[ -z "$id" ]] && continue
    job_ids+=("$id")
  done < <(_list_scheduled_jobs)

  {
    echo "=== $(translate "Scheduled backup jobs") ==="
    echo ""
    if [[ ${#job_ids[@]} -eq 0 ]]; then
      translate "No scheduled backup jobs configured."
    else
      local status backend dest label profile last_run last_result
      for id in "${job_ids[@]}"; do
        status=$(_show_job_status "$id")
        backend=$(_job_env_get "$id" BACKEND || echo "")
        profile=$(_job_env_get "$id" PROFILE_MODE || echo default)
        case "$backend" in
          pbs)
            local pbs_repo pbs_bid
            pbs_repo=$(_job_env_get "$id" PBS_REPOSITORY || echo "?")
            pbs_bid=$(_job_env_get "$id" PBS_BACKUP_ID || echo "?")
            dest="$pbs_repo  (id=$pbs_bid)"
            label="PBS"
            ;;
          local)
            dest=$(_job_env_get "$id" LOCAL_DEST_DIR || echo "?")
            label="Local archive"
            ;;
          borg)
            dest=$(_job_env_get "$id" BORG_REPO || echo "?")
            label="Borg"
            ;;
          *)
            dest="?"
            label="${backend:-?}"
            ;;
        esac
        last_run=""; last_result=""
        if [[ -f "${LOG_DIR}/${id}-last.status" ]]; then
          local last_at
          last_at=$(grep -m1 '^RUN_AT=' "${LOG_DIR}/${id}-last.status" | cut -d= -f2-)
          last_result=$(grep -m1 '^RESULT=' "${LOG_DIR}/${id}-last.status" | cut -d= -f2-)
          # Trim the timezone suffix for readability (14:13:54 vs 14:13:54+02:00)
          last_run="${last_at%%+*}"
          last_run="${last_run%%-[0-9][0-9]:[0-9][0-9]}"
          last_run="${last_run/T/ }"
        fi

        printf "• %s   [%s]\n" "$id" "$status"
        printf "    %-9s %s · %s\n" "$(translate "Backend:")" "$label" "$dest"
        printf "    %-9s %s\n" "$(translate "Profile:")" "$profile"
        if [[ -n "$last_run" ]]; then
          printf "    %-9s %s  →  %s\n" "$(translate "Last run:")" "$last_run" "${last_result:-?}"
        else
          printf "    %-9s %s\n" "$(translate "Last run:")" "$(translate "never")"
        fi
        echo ""
      done
    fi
  } > "$tmp"

  # Same window size as the parent scheduler menu — keeps the
  # dimensions consistent across the flow instead of one dialog
  # shrinking or growing per view.
  dialog --backtitle "ProxMenux" --title "$(translate "Scheduled backup jobs")" \
    --textbox "$tmp" "$HB_UI_MENU_H" "$HB_UI_MENU_W" || true
  rm -f "$tmp"
}

main_menu() {
  while true; do
    local choice
    choice=$(dialog --backtitle "ProxMenux" \
      --title "$(translate "Backup scheduler and retention")" \
      --menu "\n$(translate "Choose action:")" "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
      1 "$(translate "Create scheduled backup job")" \
      2 "$(translate "Show jobs and last run status")" \
      3 "$(translate "Run a job now")" \
      4 "$(translate "Enable / disable job timer")" \
      5 "$(translate "Delete job")" \
      0 "$(translate "Return")" \
      3>&1 1>&2 2>&3) || return 0

    case "$choice" in
      1) _create_job ;;
      2) _show_jobs ;;
      3) _job_run_now ;;
      4) _job_toggle ;;
      5) _job_delete ;;
      0) return 0 ;;
    esac
  done
}

main_menu
