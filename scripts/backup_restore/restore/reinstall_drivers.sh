#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup restore — driver reinstaller
# ==========================================================
# Walks the manifest's proxmenux_installed_components list and
# emits a plan (--dry-run, default) or actually invokes the
# installers (--apply). Each installer is called with:
#
#   bash <installer> --auto-from-manifest \
#       --version <version_at_backup> \
#       --id <component_id>
#
# The installers themselves are responsible for honoring those
# flags and running non-interactively. This script does NOT touch
# the host directly — it only delegates to the existing installers.
#
# Usage:
#   reinstall_drivers.sh <manifest> [--apply]
#
# Output: JSON {plan: [...], applied: [...] (only with --apply)}.
# ==========================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXMENUX_ROOT="/usr/local/share/proxmenux"   # where the installers live at runtime

SOURCE="${1:-}"
APPLY=0
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --root)  shift; PROXMENUX_ROOT="$1" ;;
  esac
  shift
done

[[ -z "$SOURCE" ]] && { printf 'reinstall_drivers: missing manifest source\n' >&2; exit 64; }

manifest="$(bash "$SCRIPT_DIR/parse_manifest.sh" "$SOURCE")"

plan='[]'
applied='[]'

while IFS= read -r comp; do
  [[ -z "$comp" ]] && continue
  id="$(printf '%s' "$comp" | jq -r '.id')"
  type="$(printf '%s' "$comp" | jq -r '.type // ""')"
  version="$(printf '%s' "$comp" | jq -r '.version_at_backup // ""')"
  installer_rel="$(printf '%s' "$comp" | jq -r '.proxmenux_installer // ""')"

  # Components without an installer are reinstalled manually by the
  # operator after restore (e.g. OCI apps like Tailscale). We still
  # surface them in the plan so the operator has the full list.
  if [[ -z "$installer_rel" ]]; then
    plan="$(jq --argjson acc "$plan" \
      --arg id "$id" --arg type "$type" --arg version "$version" \
      -n '$acc + [{
        component_id:    $id,
        type:            $type,
        version:         $version,
        installer:       null,
        action:          "manual_reinstall_required",
        reason:          "component has no installer mapping — operator must reinstall manually"
      }]')"
    continue
  fi

  installer_abs="$PROXMENUX_ROOT/$installer_rel"
  if [[ ! -f "$installer_abs" ]]; then
    plan="$(jq --argjson acc "$plan" \
      --arg id "$id" --arg type "$type" --arg version "$version" --arg ir "$installer_rel" \
      -n '$acc + [{
        component_id: $id,
        type:         $type,
        version:      $version,
        installer:    $ir,
        action:       "installer_missing",
        reason:       "installer script not present on this host — ProxMenux installation incomplete?"
      }]')"
    continue
  fi

  plan="$(jq --argjson acc "$plan" \
    --arg id "$id" --arg type "$type" --arg version "$version" --arg ir "$installer_rel" \
    -n '$acc + [{
      component_id: $id,
      type:         $type,
      version:      $version,
      installer:    $ir,
      action:       "will_invoke_installer",
      reason:       "bash <installer> --auto-from-manifest --version <V> --id <ID>"
    }]')"

  if [[ "$APPLY" == 1 ]]; then
    started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if bash "$installer_abs" --auto-from-manifest --version "$version" --id "$id" \
        >/tmp/proxmenux-restore-install-"$id".log 2>&1; then
      result="ok"; exit_code=0
    else
      exit_code=$?
      result="failed"
    fi
    finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    applied="$(jq --argjson acc "$applied" \
      --arg id "$id" --arg result "$result" --argjson ec "$exit_code" \
      --arg s "$started_at" --arg f "$finished_at" \
      -n '$acc + [{
        component_id: $id,
        result:       $result,
        exit_code:    $ec,
        started_at:   $s,
        finished_at:  $f,
        log:          ("/tmp/proxmenux-restore-install-" + $id + ".log")
      }]')"
  fi
done < <(printf '%s' "$manifest" | jq -c '.proxmenux_installed_components[]?')

if [[ "$APPLY" == 1 ]]; then
  jq -n --argjson plan "$plan" --argjson applied "$applied" '{plan: $plan, applied: $applied}'
else
  jq -n --argjson plan "$plan" '{plan: $plan}'
fi
