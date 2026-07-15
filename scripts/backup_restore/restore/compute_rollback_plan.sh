#!/usr/bin/env bash
# ==========================================================
# ProxMenux — compute rollback plan (read-only)
# ==========================================================
# Compares a staged restore vs the current host state and emits
# a JSON document describing what a "rollback to backup state"
# would do:
#
#   {
#     "backup_time": "...",
#     "vms_in_backup":    [100, 101],
#     "vms_in_host":      [100, 101, 105],
#     "vms_to_remove":    [105],            // exist now, not in backup
#     "vms_to_restore":   [100, 101],       // present in both → reapplied
#     "lxcs_in_backup":   [201],
#     "lxcs_in_host":     [201, 202],
#     "lxcs_to_remove":   [202],
#     "lxcs_to_restore":  [201],
#     "components_to_uninstall": ["coral_driver"],   // installed now, missing in backup
#     "components_to_reinstall":  ["nvidia_driver"]  // installed in backup
#   }
#
# No side effects whatsoever — pure inspection. The actual
# rollback is applied later by apply_cluster_postboot.sh after
# the operator confirms in the UI.
#
# Usage:
#   compute_rollback_plan.sh <staging-directory>
#
# The staging directory must already be the post-extract layout
# (rootfs/ + metadata/) — list_paths.sh's normalization should
# have run first.
# ==========================================================
set -e

STAGING="${1:-}"
if [[ -z "$STAGING" || ! -d "$STAGING" ]]; then
  printf 'compute_rollback_plan: usage: %s <staging-directory>\n' "$0" >&2
  exit 64
fi

# ── Discover guest configs (VMs + LXCs) on both sides ──
# /etc/pve/nodes/<node>/qemu-server/<id>.conf for VMs
# /etc/pve/nodes/<node>/lxc/<id>.conf for LXCs
# We collect just the numeric IDs; the rollback only needs to
# know "exists in A, exists in B" — actual config rewrite is
# done by the standard restore path for /etc/pve.

_collect_ids() {
  # $1 = root directory, $2 = subdir under /etc/pve/nodes/<n>/
  local root="$1" sub="$2"
  if [[ -d "$root/etc/pve/nodes" ]]; then
    find "$root/etc/pve/nodes" -mindepth 3 -maxdepth 3 -path "*/$sub/*.conf" -print 2>/dev/null \
      | sed -E "s|.*/([0-9]+)\\.conf$|\\1|" | sort -un
  fi
}

mapfile -t vms_backup    < <(_collect_ids "$STAGING/rootfs" qemu-server)
mapfile -t vms_host      < <(_collect_ids "/" qemu-server)
mapfile -t lxcs_backup   < <(_collect_ids "$STAGING/rootfs" lxc)
mapfile -t lxcs_host     < <(_collect_ids "/" lxc)

_diff() {
  # Echoes lines from A that are NOT in B.
  local -n a_ref=$1
  local -n b_ref=$2
  local x y found
  for x in "${a_ref[@]}"; do
    found=0
    for y in "${b_ref[@]}"; do
      [[ "$x" == "$y" ]] && { found=1; break; }
    done
    (( found == 0 )) && echo "$x"
  done
}

mapfile -t vms_to_remove  < <(_diff vms_host vms_backup)
mapfile -t vms_to_restore < <(_diff vms_backup vms_host || true; for x in "${vms_backup[@]}"; do for y in "${vms_host[@]}"; do [[ "$x" == "$y" ]] && echo "$x"; done; done | sort -un)
mapfile -t vms_to_restore < <(printf '%s\n' "${vms_backup[@]}")
mapfile -t lxcs_to_remove  < <(_diff lxcs_host lxcs_backup)
mapfile -t lxcs_to_restore < <(printf '%s\n' "${lxcs_backup[@]}")

# ── Components: parse JSON on both sides, list deltas ──
backup_components_file="$STAGING/rootfs/usr/local/share/proxmenux/components_status.json"
host_components_file="/usr/local/share/proxmenux/components_status.json"

_installed_keys() {
  # Echoes one component key per line for `status == "installed"`.
  local f="$1"
  [[ ! -f "$f" ]] && return 0
  command -v jq >/dev/null 2>&1 || { return 0; }
  jq -r 'to_entries[] | select(.value.status == "installed") | .key' "$f" 2>/dev/null | sort -u
}

mapfile -t comps_backup < <(_installed_keys "$backup_components_file")
mapfile -t comps_host   < <(_installed_keys "$host_components_file")
mapfile -t comps_to_uninstall < <(_diff comps_host comps_backup)
mapfile -t comps_to_reinstall < <(printf '%s\n' "${comps_backup[@]}")

# ── Backup timestamp from metadata for the UI ──
backup_time=""
if [[ -f "$STAGING/metadata/run_info.env" ]]; then
  backup_time=$(grep -m1 '^generated_at=' "$STAGING/metadata/run_info.env" 2>/dev/null \
    | cut -d= -f2-)
fi

# ── Emit JSON. Pure printf — no jq required for the writer ──
_json_arr_int() {
  printf '['
  local first=1 v
  for v in "$@"; do
    [[ -z "$v" ]] && continue
    if (( first )); then printf '%s' "$v"; first=0
    else                 printf ',%s' "$v"
    fi
  done
  printf ']'
}
_json_arr_str() {
  printf '['
  local first=1 v esc
  for v in "$@"; do
    [[ -z "$v" ]] && continue
    esc="${v//\\/\\\\}"; esc="${esc//\"/\\\"}"
    if (( first )); then printf '"%s"' "$esc"; first=0
    else                 printf ',"%s"' "$esc"
    fi
  done
  printf ']'
}

printf '{'
printf '"backup_time":"%s"'                    "${backup_time//\"/\\\"}"
printf ',"vms_in_backup":';      _json_arr_int "${vms_backup[@]}"
printf ',"vms_in_host":';        _json_arr_int "${vms_host[@]}"
printf ',"vms_to_remove":';      _json_arr_int "${vms_to_remove[@]}"
printf ',"vms_to_restore":';     _json_arr_int "${vms_to_restore[@]}"
printf ',"lxcs_in_backup":';     _json_arr_int "${lxcs_backup[@]}"
printf ',"lxcs_in_host":';       _json_arr_int "${lxcs_host[@]}"
printf ',"lxcs_to_remove":';     _json_arr_int "${lxcs_to_remove[@]}"
printf ',"lxcs_to_restore":';    _json_arr_int "${lxcs_to_restore[@]}"
printf ',"components_to_uninstall":'; _json_arr_str "${comps_to_uninstall[@]}"
printf ',"components_to_reinstall":'; _json_arr_str "${comps_to_reinstall[@]}"
printf '}\n'
