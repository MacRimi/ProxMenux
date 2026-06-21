#!/usr/bin/env bash
# ==========================================================
# ProxMenux Monitor restore wrapper
# ==========================================================
# Bridges the Monitor's "Restore" button to the TUI restore
# functions in backup_host.sh. The Monitor takes care of the
# extraction (snapshot → staging directory + manifest), then
# launches this script in a ScriptTerminalModal so the operator
# sees the same dialog flow used by the shell TUI.
#
# The Monitor's script_runner only forwards env vars (no argv).
# Inputs (env):
#   STAGING — absolute path to the prepared staging dir
#   MODE    — "full" or "custom"
#   PATHS   — CSV of absolute backup paths, only when MODE=custom
#             (e.g. "/etc/pve,/etc/network,/opt/mistuff").
#             Each must be present in <staging>/metadata/selected_paths.txt
#             or the wrapper drops it. Omit to let the TUI checklist
#             pop up so the operator can pick interactively.
#   ROLLBACK_EXECUTE — "1" to ask _rs_prepare_pending_restore to
#             run the destructive rollback (qm/pct destroy --purge)
#             on guests created after the backup. The frontend only
#             sets this after the operator ticks the "I understand…"
#             checkbox in the Complete restore confirm dialog. Has
#             no effect when MODE=custom.
# ==========================================================
# Note: NO `set -e` here. backup_host.sh + its sourced utils/lib
# emit a few non-zero exit codes during load (locale checks,
# optional commands missing, etc.) — under set -e those abort the
# wrapper silently and the operator only sees "Connection closed"
# in the Monitor terminal with no clue why. We rely on explicit
# error handling inside _rs_run_complete_guided / _rs_run_custom_restore.

STAGING="${STAGING:-}"
MODE="${MODE:-full}"
PATHS="${PATHS:-}"
ROLLBACK_EXECUTE="${ROLLBACK_EXECUTE:-0}"

# Also accept --staging / --mode / --paths / --rollback-execute
# positional args for direct CLI use outside the Monitor.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --staging)          shift; STAGING="${1:-}" ;;
    --mode)             shift; MODE="${1:-full}" ;;
    --paths)            shift; PATHS="${1:-}" ;;
    --rollback-execute) ROLLBACK_EXECUTE=1 ;;
    *) ;;
  esac
  shift
done

if [[ -z "$STAGING" || ! -d "$STAGING" ]]; then
  printf 'monitor_apply: STAGING missing or not a directory (%s)\n' "$STAGING" >&2
  exit 64
fi

HB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Source the library + the TUI. backup_host.sh carries a guard so
# sourcing it does NOT spawn the main menu — only the functions
# (_rs_check_layout, _rs_run_complete_guided, _rs_run_custom_restore,
# _rs_apply, ...) get loaded.
# shellcheck source=/dev/null
. "$HB_DIR/lib_host_backup_common.sh"
# shellcheck source=/dev/null
. "$HB_DIR/backup_host.sh"

# Normalize the staging layout to the canonical rootfs/+metadata/
# shape. The Monitor's Python extract path already does this, but
# rerunning here keeps the wrapper safe when invoked directly.
if ! _rs_check_layout "$STAGING"; then
  printf 'monitor_apply: archive layout not recognized in %s\n' "$STAGING" >&2
  exit 65
fi

# Tell the apply helpers that we're running under the Monitor.
# Two effects:
#  • _rs_apply skips its final `systemctl daemon-reload` so the
#    Monitor service unit isn't marked "needs restart" and the
#    WebSocket survives the apply (the restored unit file IS
#    written to disk — it'll take effect at the next reboot).
#  • _rs_run_complete_guided / _rs_run_custom_restore skip the
#    second "Reboot now?" dialog and instead emit one final
#    "Restore prepared — reboot when ready" line. The operator
#    closes the modal in the web UI and reboots from the host
#    panel; no need for two consecutive yes/no prompts.
export HB_MONITOR_FLOW=1

# Propagate the destructive-rollback opt-in to _rs_prepare_pending_restore.
# Only honored for MODE=full — custom restores never trigger guest destroy.
if [[ "$MODE" == "full" && "$ROLLBACK_EXECUTE" == "1" ]]; then
  export HB_ROLLBACK_EXECUTE=1
fi

case "$MODE" in
  full)
    # The TUI path runs `_rs_collect_plan_stats` before calling
    # `_rs_run_complete_guided`. We were skipping it here and that's
    # why the confirm dialog showed "0 rutas seguras ahora /
    # 0 rutas para el próximo arranque" when launched from the Monitor.
    _rs_collect_plan_stats "$STAGING"
    _rs_run_complete_guided "$STAGING"
    ;;
  custom)
    if [[ -n "$PATHS" ]]; then
      HB_PRESELECTED_PATHS="$PATHS" _rs_run_custom_restore "$STAGING"
    else
      _rs_run_custom_restore "$STAGING"
    fi
    ;;
  *)
    printf 'monitor_apply: unknown MODE %s (expected: full | custom)\n' "$MODE" >&2
    exit 66
    ;;
esac

# Clean exit. _rs_finish_flow under HB_MONITOR_FLOW already returns
# without waiting for Enter, so falling off the end here closes the
# PTY → the WS closes → the modal sees `isComplete=true` (script_runner
# sends "[Script exited with code 0]" on normal termination) so the
# ScriptTerminalModal won't try to auto-reconnect.
