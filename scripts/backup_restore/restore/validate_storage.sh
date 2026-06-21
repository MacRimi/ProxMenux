#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup restore — storage validation
# ==========================================================
# Walks the manifest's storage_inventory and reports per-pool /
# per-storage whether it can be auto-restored on this host. Builds
# the "what's safe to import vs needs manual work" picture that
# the orchestrator turns into actionable steps.
#
# Usage:
#   validate_storage.sh <manifest-json-path-or-archive>
#
# Output: JSON {zfs: [...], lvm: [...], pve_storage: [...]} with
# per-item action (auto_import / partial / manual_required / present)
# and the disks/parameters that drove the decision.
# ==========================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${1:-}"
[[ -z "$SOURCE" ]] && { printf 'validate_storage: missing manifest source\n' >&2; exit 64; }

manifest="$(bash "$SCRIPT_DIR/parse_manifest.sh" "$SOURCE")"

# ── ZFS pools ──
zfs_report='[]'
while IFS= read -r pool_json; do
  [[ -z "$pool_json" ]] && continue
  name="$(printf '%s' "$pool_json" | jq -r '.name')"
  needed_devs="$(printf '%s' "$pool_json" | jq -r '.devices_by_id[]?')"
  present=()
  missing=()
  while IFS= read -r dev; do
    [[ -z "$dev" ]] && continue
    if [[ -e "/dev/disk/by-id/$dev" ]]; then
      present+=("$dev")
    else
      missing+=("$dev")
    fi
  done <<< "$needed_devs"

  # Already imported?
  if zpool list -H -o name 2>/dev/null | grep -qFx "$name"; then
    action="present"
  elif [[ ${#missing[@]} -eq 0 ]]; then
    action="auto_import"
  elif [[ ${#present[@]} -gt 0 ]]; then
    action="partial"
  else
    action="manual_required"
  fi

  present_json="$(printf '%s\n' "${present[@]:-}" | jq -R . | jq -s 'map(select(. != ""))')"
  missing_json="$(printf '%s\n' "${missing[@]:-}" | jq -R . | jq -s 'map(select(. != ""))')"

  zfs_report="$(jq --argjson acc "$zfs_report" \
    --arg name "$name" \
    --arg action "$action" \
    --argjson present "$present_json" \
    --argjson missing "$missing_json" \
    -n '$acc + [{
      name:    $name,
      action:  $action,
      present: $present,
      missing: $missing
    }]')"
done < <(printf '%s' "$manifest" | jq -c '.storage_inventory.zfs_pools[]?')

# ── LVM volume groups ──
lvm_report='[]'
while IFS= read -r vg_json; do
  [[ -z "$vg_json" ]] && continue
  name="$(printf '%s' "$vg_json" | jq -r '.name')"
  if command -v vgs >/dev/null 2>&1 && vgs --noheadings -o vg_name 2>/dev/null | grep -qE "^[[:space:]]*${name}[[:space:]]*$"; then
    action="present"
  else
    action="manual_required"
  fi
  lvm_report="$(jq --argjson acc "$lvm_report" \
    --arg name "$name" --arg action "$action" \
    -n '$acc + [{ name: $name, action: $action }]')"
done < <(printf '%s' "$manifest" | jq -c '.storage_inventory.lvm.vgs[]?')

# ── PVE storage.cfg entries ──
# For each storage entry in the manifest we report whether it currently
# exists in the destination's storage.cfg (no action needed), whether the
# backing resource is reachable (e.g. NFS server pings), and what kind of
# follow-up is required if the storage.cfg is being restored.
pve_report='[]'
existing_pve_ids='[]'
if [[ -r /etc/pve/storage.cfg ]]; then
  existing_pve_ids="$(awk '/^[a-z]+:[[:space:]]+/{print $2}' /etc/pve/storage.cfg | jq -R . | jq -s .)"
fi

while IFS= read -r st_json; do
  [[ -z "$st_json" ]] && continue
  id="$(printf '%s' "$st_json" | jq -r '.id')"
  type="$(printf '%s' "$st_json" | jq -r '.type')"
  server="$(printf '%s' "$st_json" | jq -r '.server // ""')"
  pool="$(printf '%s' "$st_json" | jq -r '.pool // ""')"

  already_present="$(printf '%s' "$existing_pve_ids" | jq -r --arg i "$id" 'any(. == $i)')"
  reachable_note=""

  case "$type" in
    nfs|cifs)
      if [[ -n "$server" ]]; then
        if ping -c 1 -W 1 "$server" >/dev/null 2>&1; then
          reachable_note="reachable"
        else
          reachable_note="server_unreachable"
        fi
      fi
      ;;
    zfspool)
      # The pool name in storage.cfg is e.g. "rpool/data" — only valid
      # if the parent pool is imported.
      parent_pool="${pool%%/*}"
      if [[ -n "$parent_pool" ]] && zpool list -H -o name 2>/dev/null | grep -qFx "$parent_pool"; then
        reachable_note="pool_imported"
      else
        reachable_note="pool_not_imported"
      fi
      ;;
  esac

  if [[ "$already_present" == "true" ]]; then
    action="present"
  else
    action="will_be_restored"
  fi

  pve_report="$(jq --argjson acc "$pve_report" \
    --arg id "$id" --arg type "$type" --arg action "$action" --arg note "$reachable_note" \
    -n '$acc + [{
      id:     $id,
      type:   $type,
      action: $action,
      note:   (if $note == "" then null else $note end)
    }]')"
done < <(printf '%s' "$manifest" | jq -c '.storage_inventory.pve_storage_cfg[]?')

# Compose
jq -n \
  --argjson zfs "$zfs_report" \
  --argjson lvm "$lvm_report" \
  --argjson pve "$pve_report" \
  '{ zfs: $zfs, lvm: $lvm, pve_storage: $pve }'
