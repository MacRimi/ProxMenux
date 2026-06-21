#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup restore — orchestrator
# ==========================================================
# Composes the four manifest-aware tools into a single restore
# workflow:
#
#   1. parse manifest             (parse_manifest.sh)
#   2. preflight checks           (preflight_checks.sh)        ← can fail
#   3. validate storage           (validate_storage.sh)        ← reports
#   4. network remap plan         (remap_network.sh)           ← reports
#   5. driver reinstall plan      (reinstall_drivers.sh)       ← reports
#
# By default it runs the four AS A DRY-RUN and prints the combined
# report. With --apply it executes the file extraction (delegated to
# the existing _rs_apply from backup_host.sh — placeholder for now)
# and then runs the driver reinstaller with --apply.
#
# Usage:
#   run_restore.sh <backup-archive-or-dir> [options]
#
# --mode <mode>  Restore mode preset (default: full)
#                full | storage_only | network_only | base | custom
# --json         Machine-readable combined report (default)
# --text         Human-friendly summary on stderr + JSON report on stdout
# --apply        Actually perform the restore (refuses if preflight fails)
# ==========================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${1:-}"
FORMAT="json"
APPLY=0
MODE="full"
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)  FORMAT="json" ;;
    --text)  FORMAT="text" ;;
    --apply) APPLY=1 ;;
    --mode)  shift; MODE="${1:-full}" ;;
  esac
  shift
done

[[ -z "$SOURCE" ]] && { printf 'run_restore: usage: %s <backup-archive-or-dir> [--apply]\n' "$0" >&2; exit 64; }

# ── Step 1: Parse manifest ──
manifest="$(bash "$SCRIPT_DIR/parse_manifest.sh" "$SOURCE")"

# ── Step 2: Resolve mode preset (which paths/components/actions apply) ──
mode_plan="$(bash "$SCRIPT_DIR/restore_modes.sh" "$MODE" "$SOURCE")"

# ── Step 3: Pre-flight checks (gate) ──
preflight="$(bash "$SCRIPT_DIR/preflight_checks.sh" "$SOURCE" || true)"
fail_count="$(printf '%s' "$preflight" | jq '.summary.fail')"

# ── Step 4: Storage validation ──
# Only report storage if the mode actually applies storage changes;
# otherwise we still surface the info but mark it as "not in mode".
storage_apply_in_mode="$(printf '%s' "$mode_plan" | jq -r '.storage_apply')"
storage="$(bash "$SCRIPT_DIR/validate_storage.sh" "$SOURCE")"

# ── Step 5: NIC remap plan ──
network_apply_in_mode="$(printf '%s' "$mode_plan" | jq -r '.network_apply')"
network="$(bash "$SCRIPT_DIR/remap_network.sh" "$SOURCE")"

# ── Step 6: Driver reinstaller plan ──
# In modes that don't include components (storage_only, network_only,
# custom-without-explicit), we narrow the driver plan to nothing.
components_in_mode="$(printf '%s' "$mode_plan" | jq -c '.components_include')"
drivers_full_plan="$(bash "$SCRIPT_DIR/reinstall_drivers.sh" "$SOURCE")"
drivers_plan="$(printf '%s' "$drivers_full_plan" | jq --argjson ids "$components_in_mode" '
  if ($ids | length) == 0 then
    .plan |= []
  else
    .plan |= map(select(.component_id as $id | $ids | index($id) != null))
  end
')"

drivers_applied='null'
apply_done=false
abort_reason=""

if [[ "$APPLY" == 1 ]]; then
  if [[ "$fail_count" -gt 0 ]]; then
    abort_reason="preflight has $fail_count failing check(s) — refusing --apply"
  else
    # Driver reinstall only runs if the selected mode includes components.
    # Modes that don't (storage_only, network_only) keep drivers untouched.
    if [[ "$(printf '%s' "$components_in_mode" | jq 'length')" -gt 0 ]]; then
      drivers_full="$(bash "$SCRIPT_DIR/reinstall_drivers.sh" "$SOURCE" --apply)"
      # Narrow to components selected by the mode
      drivers_applied="$(printf '%s' "$drivers_full" | jq --argjson ids "$components_in_mode" '
        .applied | map(select(.component_id as $id | $ids | index($id) != null))
      ')"
    else
      drivers_applied='[]'
    fi
    # TODO(13D): delegate the actual file extraction (paths_include /
    # paths_exclude from $mode_plan) + storage_apply / network_apply
    # decisions to backup_host.sh's _rs_apply(). This is the integration
    # seam between the manifest-aware tooling and the existing extraction
    # engine.
    apply_done=true
  fi
fi

# Decorate sections that aren't part of the selected mode so the report
# is honest about what would actually be touched.
storage_for_report="$(jq -n --argjson s "$storage" --argjson in_mode "$storage_apply_in_mode" \
  '$s + {in_selected_mode: $in_mode}')"
network_for_report="$(jq -n --argjson n "$network" --argjson in_mode "$network_apply_in_mode" \
  '$n + {in_selected_mode: $in_mode}')"

report="$(jq -n \
  --argjson manifest_source_host "$(printf '%s' "$manifest" | jq '.source_host')" \
  --argjson mode_plan "$mode_plan" \
  --argjson preflight "$preflight" \
  --argjson storage   "$storage_for_report" \
  --argjson network   "$network_for_report" \
  --argjson drivers_plan "$(printf '%s' "$drivers_plan" | jq '.plan')" \
  --argjson drivers_applied "$drivers_applied" \
  --argjson apply_done "$apply_done" \
  --arg     abort_reason "$abort_reason" \
  '{
    source_host_at_backup: $manifest_source_host,
    selected_mode:         $mode_plan,
    preflight:             $preflight,
    storage:               $storage,
    network:               $network,
    driver_reinstall: {
      plan:    $drivers_plan,
      applied: $drivers_applied
    },
    applied:      $apply_done,
    abort_reason: (if $abort_reason == "" then null else $abort_reason end)
  }')"

if [[ "$FORMAT" == "text" ]]; then
  # Brief human summary on stderr; the JSON still goes to stdout so the
  # caller can pipe it elsewhere.
  {
    printf '─────────────────────────────────────────────\n'
    printf 'ProxMenux Restore — dry-run report\n'
    printf '─────────────────────────────────────────────\n'
    printf 'Source host : %s (PVE %s)\n' \
      "$(printf '%s' "$report" | jq -r '.source_host_at_backup.hostname')" \
      "$(printf '%s' "$report" | jq -r '.source_host_at_backup.pve_version // "-"')"
    printf 'Mode        : %s — %s paths in, %s components\n' \
      "$MODE" \
      "$(printf '%s' "$report" | jq -r '.selected_mode.paths_include | length')" \
      "$(printf '%s' "$report" | jq -r '.selected_mode.components_include | length')"
    printf 'Pre-flight  : %s pass · %s warn · %s fail\n' \
      "$(printf '%s' "$report" | jq -r '.preflight.summary.pass')" \
      "$(printf '%s' "$report" | jq -r '.preflight.summary.warn')" \
      "$(printf '%s' "$report" | jq -r '.preflight.summary.fail')"
    printf 'Storage     : %s pools / %s LVM VGs / %s PVE storages  [in mode: %s]\n' \
      "$(printf '%s' "$report" | jq -r '.storage.zfs | length')" \
      "$(printf '%s' "$report" | jq -r '.storage.lvm | length')" \
      "$(printf '%s' "$report" | jq -r '.storage.pve_storage | length')" \
      "$(printf '%s' "$report" | jq -r '.storage.in_selected_mode')"
    printf 'Network     : %s keep / %s remap / %s orphan / %s new  [in mode: %s]\n' \
      "$(printf '%s' "$report" | jq -r '.network.keep | length')" \
      "$(printf '%s' "$report" | jq -r '.network.remap | length')" \
      "$(printf '%s' "$report" | jq -r '.network.orphan | length')" \
      "$(printf '%s' "$report" | jq -r '.network.new | length')" \
      "$(printf '%s' "$report" | jq -r '.network.in_selected_mode')"
    printf 'Drivers     : %s in plan\n' \
      "$(printf '%s' "$report" | jq -r '.driver_reinstall.plan | length')"
    if [[ "$APPLY" == 1 ]]; then
      printf '─── APPLY ───\n'
      if [[ -n "$abort_reason" ]]; then
        printf 'ABORTED: %s\n' "$abort_reason"
      else
        printf 'Drivers applied: %s\n' \
          "$(printf '%s' "$report" | jq -r '.driver_reinstall.applied | length')"
      fi
    fi
    printf '─────────────────────────────────────────────\n'
  } >&2
fi

printf '%s\n' "$report"
