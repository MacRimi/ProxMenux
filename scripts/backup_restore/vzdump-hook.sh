#!/usr/bin/env bash
# ProxMenux vzdump hook: bridges PVE vzdump jobs to attached host-config
# backups. Installed system-wide via /etc/vzdump.conf ("script:" line).
# PVE 9 invokes the hook for every phase and only exports a fixed set of env
# vars (STOREID, DUMPDIR, VMTYPE, HOSTNAME, TARGET, LOGFILE) — JOB_ID is NOT
# exported. We therefore match each proxmenux .env by its PVE_STORAGE field
# against STOREID and only act once per PVE job, in the job-end phase.

set -u

PHASE="${1:-}"
PROXMENUX_JOBS_DIR="${PROXMENUX_JOBS_DIR:-/var/lib/proxmenux/backup-jobs}"
PROXMENUX_LOG_DIR="/var/log/proxmenux"
PROXMENUX_RUNNER="/usr/local/share/proxmenux/scripts/backup_restore/run_scheduled_backup.sh"
CHAIN_HOOK="/etc/proxmenux/vzdump-hook-chain.sh"

# Chain to any pre-existing hook that we displaced when we registered ours.
if [[ -x "$CHAIN_HOOK" ]]; then
  "$CHAIN_HOOK" "$@" || true
fi

[[ "$PHASE" != "job-end" ]] && exit 0
[[ -z "${STOREID:-}" ]] && exit 0

mkdir -p "$PROXMENUX_LOG_DIR"
HOOK_LOG="$PROXMENUX_LOG_DIR/vzdump-hook.log"
echo "[$(date '+%F %T')] phase=$PHASE STOREID=$STOREID" >>"$HOOK_LOG"

if [[ ! -x "$PROXMENUX_RUNNER" ]]; then
  echo "  runner missing: $PROXMENUX_RUNNER" >>"$HOOK_LOG"
  exit 0
fi

shopt -s nullglob
for env_file in "$PROXMENUX_JOBS_DIR"/*.env; do
  storage="" enabled="" pmx_id=""
  while IFS='=' read -r k v; do
    case "$k" in
      PVE_STORAGE) storage="$v" ;;
      ENABLED)     enabled="$v" ;;
      JOB_ID)      pmx_id="$v" ;;
    esac
  done <"$env_file"

  [[ "$storage" != "$STOREID" ]] && continue
  [[ "${enabled:-1}" != "1" ]] && { echo "  skip $pmx_id (disabled)" >>"$HOOK_LOG"; continue; }
  [[ -z "$pmx_id" ]] && continue

  echo "  -> run $pmx_id" >>"$HOOK_LOG"
  bash "$PROXMENUX_RUNNER" "$pmx_id" >>"$HOOK_LOG" 2>&1 || \
    echo "  ! $pmx_id exited non-zero" >>"$HOOK_LOG"
done

exit 0
